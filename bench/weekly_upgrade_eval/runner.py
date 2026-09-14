"""Run a frozen, paired inference-policy canary without production writes.

Examples::

    python3 -m bench.weekly_upgrade_eval.runner --plan \
        --manifest bench/weekly_upgrade_eval/fixtures.json

    env -u MOCK_LLM python3 -m bench.weekly_upgrade_eval.runner --run \
        --manifest /path/to/preregistered.json \
        --output-dir /path/to/new/isolated/run \
        --runtime-budget-s 1800

``--plan`` only reads files and prints JSON.  ``--run`` connects to the local
wrapper, but only after all arguments and the manifest validate.  It never
changes a model, service, role, scheduler, decision ledger, or promotion state.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .manifest import (
    DEFAULT_MANIFEST_PATH,
    Arm,
    EvaluationManifest,
    ManifestError,
    Task,
    canonical_json,
    load_manifest,
    sha256_json,
)
from .stats import summarize_outcomes

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_SCHEMA_VERSION = "weekly-upgrade-eval-run/v1"
HARNESS_FILES = (
    Path(__file__).with_name("manifest.py"),
    Path(__file__),
    Path(__file__).with_name("stats.py"),
)
RESERVED_OUTPUT_ROOTS = tuple(
    (REPO_ROOT / name).resolve() for name in ("logs", "memory", "run_state")
)


@dataclass(frozen=True)
class InvocationRequest:
    """One bounded arm/task request passed to the injectable transport seam."""

    run_id: str
    task: Task
    arm: Arm
    request_timeout_s: float
    calls_log_path: Path
    worker_activity_path: Path


@dataclass(frozen=True)
class InvocationResult:
    completion: str
    records: tuple[dict[str, Any], ...] = ()
    tool_calls: tuple[dict[str, Any], ...] = ()
    runtime_provenance: dict[str, Any] = field(default_factory=dict)
    failure_code: str | None = None


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    reason: str
    details: dict[str, Any] = field(default_factory=dict)


InvokeFn = Callable[[InvocationRequest], InvocationResult]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _strict_object(text: str) -> tuple[dict[str, Any] | None, str | None]:
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        return None, f"completion is not one strict JSON value: {exc}"
    if not isinstance(payload, dict):
        return None, "completion JSON must be an object"
    return payload, None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _close(actual: Any, expected: Any, tolerance: float) -> bool:
    actual_number = _number(actual)
    expected_number = _number(expected)
    return (
        actual_number is not None
        and expected_number is not None
        and abs(actual_number - expected_number) <= tolerance
    )


def _exact_keys(payload: dict[str, Any], expected: dict[str, Any]) -> str | None:
    if set(payload) != set(expected):
        return (
            f"JSON fields differ: got {sorted(payload)}, expected "
            f"{sorted(expected)}"
        )
    return None


def _grade_zero_sum(payload: dict[str, Any], expected: dict[str, Any], tol: float) -> GradeResult:
    keys_error = _exact_keys(payload, expected)
    if keys_error:
        return GradeResult(False, keys_error)
    for key in ("row_mixture", "column_mixture"):
        values = payload.get(key)
        target = expected[key]
        if not isinstance(values, list) or len(values) != 2:
            return GradeResult(False, f"{key} must contain two probabilities")
        if any(_number(value) is None or not 0 <= float(value) <= 1 for value in values):
            return GradeResult(False, f"{key} contains an invalid probability")
        if not _close(sum(values), 1.0, tol):
            return GradeResult(False, f"{key} probabilities do not sum to one")
        if any(not _close(value, wanted, tol) for value, wanted in zip(values, target)):
            return GradeResult(False, f"{key} is not the equilibrium mixture")
    if not _close(payload.get("value"), expected["value"], tol):
        return GradeResult(False, "value is not the equilibrium value")
    return GradeResult(True, "exact equilibrium and value")


def _grade_numeric_object(
    payload: dict[str, Any], expected: dict[str, Any], tol: float, label: str
) -> GradeResult:
    keys_error = _exact_keys(payload, expected)
    if keys_error:
        return GradeResult(False, keys_error)
    for key, wanted in expected.items():
        if isinstance(wanted, list):
            if payload.get(key) != wanted:
                return GradeResult(False, f"{key} has the wrong trace")
        elif not _close(payload.get(key), wanted, tol):
            return GradeResult(False, f"{key} is numerically wrong")
    return GradeResult(True, f"exact {label}")


def _grade_critic(payload: dict[str, Any], expected: dict[str, Any]) -> GradeResult:
    keys_error = _exact_keys(payload, expected)
    if keys_error:
        return GradeResult(False, keys_error)
    if payload.get("verdict") != expected["verdict"]:
        return GradeResult(False, "wrong fatal/proceed decision")
    if payload.get("reason_code") != expected["reason_code"]:
        return GradeResult(False, "verdict lacks the expected substantive reason")
    return GradeResult(True, "verdict and substantive reason match")


def _grade_evidence(payload: dict[str, Any], expected: dict[str, Any]) -> GradeResult:
    keys_error = _exact_keys(payload, expected)
    if keys_error:
        return GradeResult(False, keys_error)
    if payload.get("answer_code") != expected["answer_code"]:
        return GradeResult(False, "answer is not supported by the supplied packet")
    citations = payload.get("citations")
    if not isinstance(citations, list) or any(not isinstance(item, str) for item in citations):
        return GradeResult(False, "citations must be an array of document IDs")
    if len(citations) != len(set(citations)):
        return GradeResult(False, "citations contain duplicates")
    if set(citations) != set(expected["citations"]):
        return GradeResult(False, "citation set is incomplete or unsupported")
    return GradeResult(True, "supported answer with exact evidence IDs")


def _json_equivalent(actual: Any, expected: Any, tolerance: float) -> bool:
    if _number(expected) is not None:
        return _close(actual, expected, tolerance)
    if isinstance(expected, dict):
        return (
            isinstance(actual, dict)
            and set(actual) == set(expected)
            and all(
                _json_equivalent(actual[key], value, tolerance)
                for key, value in expected.items()
            )
        )
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(actual) == len(expected)
            and all(
                _json_equivalent(a_value, e_value, tolerance)
                for a_value, e_value in zip(actual, expected)
            )
        )
    return actual == expected


def _grade_tool(
    payload: dict[str, Any], expected: dict[str, Any], tool_calls: tuple[dict[str, Any], ...],
    tolerance: float,
) -> GradeResult:
    if len(tool_calls) != 1:
        return GradeResult(
            False,
            f"expected exactly one relevant tool call, observed {len(tool_calls)}",
        )
    observed = tool_calls[0]
    if observed.get("name") != expected["tool_name"]:
        return GradeResult(False, "selected the wrong tool")
    if observed.get("arguments") != expected["arguments"]:
        return GradeResult(False, "tool arguments are semantically wrong")
    if not _json_equivalent(payload, expected["answer"], tolerance):
        return GradeResult(False, "final answer does not match the selected tool result")
    return GradeResult(True, "one exact tool call and correct grounded answer")


def grade_task(task: Task, result: InvocationResult) -> GradeResult:
    """Apply the frozen objective grader for one task."""
    if result.failure_code is not None:
        return GradeResult(False, result.failure_code)
    payload, error = _strict_object(result.completion)
    if error or payload is None:
        return GradeResult(False, error or "invalid completion")
    grader = task.grader
    kind = grader["kind"]
    expected = grader["expected"]
    tolerance = float(grader.get("absolute_tolerance", 1e-6))
    if kind == "zero_sum_equilibrium":
        return _grade_zero_sum(payload, expected, tolerance)
    if kind == "external_regret":
        return _grade_numeric_object(payload, expected, tolerance, "regret accounting")
    if kind == "repeated_pd_trace":
        return _grade_numeric_object(payload, expected, tolerance, "repeated-game trace")
    if kind == "critic_classification":
        return _grade_critic(payload, expected)
    if kind == "evidence_attribution":
        return _grade_evidence(payload, expected)
    if kind == "tool_semantics":
        return _grade_tool(payload, expected, result.tool_calls, tolerance)
    raise ManifestError(f"no grader implementation for {kind!r}")


def _decode_tool_calls(records: tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], ...]:
    decoded: list[dict[str, Any]] = []
    for record in records:
        completion = record.get("completion")
        if not isinstance(completion, str):
            continue
        try:
            items = json.loads(completion)
        except json.JSONDecodeError:
            continue
        if not isinstance(items, list):
            continue
        for item in items:
            function = item.get("function") if isinstance(item, dict) else None
            if not isinstance(function, dict) or not isinstance(function.get("name"), str):
                continue
            arguments = function.get("arguments")
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = {"__malformed_arguments__": arguments}
            else:
                # OpenAI tool arguments must be a JSON-encoded string. Match
                # the wrapper's audited TypeError path for null/object values.
                arguments = {"__malformed_arguments__": arguments}
            decoded.append({"name": function["name"], "arguments": arguments})
    return tuple(decoded)


def _runtime_provenance(records: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    if not records:
        return {}
    first = records[0]
    keys = (
        "model", "model_version", "backend", "temperature", "top_p", "seed",
        "max_tokens", "host_metadata", "profile", "reasoning_effort",
        "sampling_extra", "finish_reason", "reasoning_chars",
    )
    return {key: first[key] for key in keys if key in first}


def _validate_live_record_provenance(
    request: InvocationRequest, records: tuple[dict[str, Any], ...]
) -> None:
    if not records:
        raise RuntimeError("wrapper returned no call records")
    from agent_wrapper.generation_policy import resolve_generation_policy
    resolved = resolve_generation_policy(
        profile=request.arm.profile, backend_name=request.arm.backend,
        model_name=request.arm.model or records[0].get("model"), seed=request.arm.seed,
        caller_tag=f"weekly_upgrade_eval:{request.task.id}",
    )
    expected = {**dict(resolved.logged_params), "profile": request.arm.profile,
                "reasoning_effort": resolved.reasoning_effort,
                "sampling_extra": dict(resolved.sampling_extra),
                "max_tokens": request.arm.max_tokens}
    identity = None
    for index, record in enumerate(records):
        if record.get("backend") != request.arm.backend:
            raise RuntimeError(
                f"record {index} backend {record.get('backend')!r} does not "
                f"match frozen arm {request.arm.backend!r}"
            )
        if request.arm.model is not None and record.get("model") != request.arm.model:
            raise RuntimeError(
                f"record {index} model {record.get('model')!r} does not match "
                f"frozen arm {request.arm.model!r}"
            )
        if not isinstance(record.get("model_version"), str) or not record["model_version"]:
            raise RuntimeError(f"record {index} lacks model_version provenance")
        if not isinstance(record.get("host_metadata"), dict):
            raise RuntimeError(f"record {index} lacks host_metadata provenance")
        for key, value in expected.items():
            if key not in record or record[key] != value:
                raise RuntimeError(f"record {index} effective policy drift: {key}")
        current = (record["model_version"], record["host_metadata"])
        if identity is not None and current != identity:
            raise RuntimeError(f"record {index} runtime changed within tool loop")
        identity = current


def _tool_entries(task: Task) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for tool in task.tools:
        expected_arguments = tool["expected_arguments"]
        result = tool["result"]

        def implementation(
            _expected=expected_arguments, _result=result, **kwargs: Any
        ) -> Any:
            if kwargs != _expected:
                return {"error": "not_found", "received_arguments": kwargs}
            return _result

        entries.append({
            "spec": {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["parameters"],
                },
            },
            "impl": implementation,
        })
    return entries


def invoke_via_wrapper(request: InvocationRequest) -> InvocationResult:
    """Live local-server adapter, imported only after ``--run`` validation."""
    from agent_wrapper import worker_activity
    from agent_wrapper.wrapper import (
        ToolCallError,
        call_sync,
        call_with_tools,
        get_run_id,
        set_run_id,
    )

    # The wrapper's activity sink is module-scoped.  The evaluation process is
    # single-threaded, so redirect it to this run before any request.  Calls and
    # worker activity therefore stay under the explicit artifact directory.
    prior_activity_path = worker_activity.DEFAULT_LOG_PATH
    prior_run_id = get_run_id()
    worker_activity.DEFAULT_LOG_PATH = request.worker_activity_path
    set_run_id(request.run_id)
    common: dict[str, Any] = {
        "backend": request.arm.backend,
        "profile": request.arm.profile,
        "max_tokens": request.arm.max_tokens,
        "request_timeout_s": request.request_timeout_s,
        "log_path": str(request.calls_log_path),
        "caller_tag": f"weekly_upgrade_eval:{request.task.id}",
        "parent_request_id": request.run_id,
    }
    if request.arm.model is not None:
        common["model"] = request.arm.model
    if request.arm.seed is not None:
        common["seed"] = request.arm.seed
    messages = [
        {"role": "system", "content": request.task.system},
        {"role": "user", "content": request.task.prompt},
    ]
    failure_code = None
    try:
        if request.task.mode == "tools":
            records_raw = call_with_tools(
                messages,
                _tool_entries(request.task),
                max_depth=2,
                **common,
            )
            records = tuple(records_raw)
        else:
            records = (call_sync(messages, **common),)
    except ToolCallError as exc:
        # Model-emitted tool/schema errors are measured failures, not missing
        # transport. Keep the already-emitted records for provenance and cost.
        records = exc.records
        failure_code = exc.failure_code
        if not records:
            raise RuntimeError("tool failure has no auditable partial records") from exc
    finally:
        # This adapter can also be called from a long-lived process in tests or
        # manual tooling. Never strand later application calls on eval sinks.
        set_run_id(prior_run_id)
        worker_activity.DEFAULT_LOG_PATH = prior_activity_path
    _validate_live_record_provenance(request, records)
    completion = records[-1].get("completion", "") if records else ""
    return InvocationResult(
        completion=completion,
        records=records,
        tool_calls=_decode_tool_calls(records),
        runtime_provenance=_runtime_provenance(records),
        failure_code=failure_code,
    )


def validate_live_configuration(manifest: EvaluationManifest) -> None:
    """Resolve every frozen profile/backend/model tuple before any call."""
    # Importing wrapper installs the concrete backends in the registry.  A
    # fresh CLI process otherwise sees an empty registry at this preflight.
    from agent_wrapper import wrapper as _wrapper  # noqa: F401
    from agent_wrapper.backends import get_backend
    from agent_wrapper.generation_policy import resolve_generation_policy

    for arm in manifest.arms:
        backend = get_backend(arm.backend)
        model = arm.model or backend.default_model
        resolve_generation_policy(
            profile=arm.profile,
            backend_name=arm.backend,
            model_name=model,
            caller_tag="weekly_upgrade_eval:preflight",
        )


def _harness_hashes() -> dict[str, str]:
    return {
        str(path.relative_to(REPO_ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in HARNESS_FILES
    }


def validate_output_dir(path: Path | str) -> Path:
    """Require a fresh artifact directory outside live append-only roots."""
    output = Path(path).expanduser().resolve()
    if output == REPO_ROOT:
        raise ValueError("output directory cannot be the repository root")
    for reserved in RESERVED_OUTPUT_ROOTS:
        if output == reserved or reserved in output.parents:
            raise ValueError(
                f"output directory cannot be under live artifact root {reserved}"
            )
    if output.exists():
        raise FileExistsError(
            f"output directory already exists; use a fresh path: {output}"
        )
    return output


def _write_json_atomic(path: Path, value: Any) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_bytes(canonical_json(value) + b"\n")
    temp.replace(path)


def _exception_status(exc: Exception) -> str:
    name = type(exc).__name__.lower()
    return "timeout" if isinstance(exc, TimeoutError) or "timeout" in name else "error"


def _result_outcome(
    *,
    request: InvocationRequest,
    execution_index: int,
    result: InvocationResult,
    duration_s: float,
) -> dict[str, Any]:
    grade = grade_task(request.task, result)
    usage = {"input_tokens": 0, "output_tokens": 0}
    for record in result.records:
        record_usage = record.get("usage") or {}
        for key in usage:
            value = record_usage.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                usage[key] += value
    return {
        "task_id": request.task.id,
        "family": request.task.family,
        "arm_id": request.arm.id,
        "execution_index": execution_index,
        "status": "passed" if grade.passed else "failed",
        "failure_code": (result.failure_code or (
            None if grade.passed else "tool_semantics" if request.task.mode == "tools"
            else "parse_failure" if _strict_object(result.completion)[0] is None
            else "incorrect_answer")),
        "duration_s": round(duration_s, 6),
        "request_timeout_s": request.request_timeout_s,
        "input_sha256": request.task.input_sha256,
        "grader_sha256": request.task.grader_sha256,
        "grade": {
            "passed": grade.passed,
            "reason": grade.reason,
            "details": grade.details,
        },
        "completion": result.completion,
        "tool_calls": list(result.tool_calls),
        "usage": usage,
        "response_telemetry": {
            "empty_at_cap": sum(not str(record.get("completion", "")).strip()
                and (record.get("finish_reason") == "length"
                     or record.get("usage", {}).get("output_tokens", 0) >= request.arm.max_tokens)
                for record in result.records),
            "finish_reasons": [record.get("finish_reason") for record in result.records],
            "reasoning_chars": (sum(record["reasoning_chars"] for record in result.records)
                if result.records and all(isinstance(record.get("reasoning_chars"), int)
                                          for record in result.records) else None),
            "reasoning_tokens": None,
        },
        "runtime_provenance": result.runtime_provenance,
        "runtime_provenance_sha256": sha256_json(result.runtime_provenance),
    }


def _failure_outcome(
    *, task: Task, arm: Arm, execution_index: int | None, status: str,
    duration_s: float, request_timeout_s: float | None, error: str,
) -> dict[str, Any]:
    return {
        "task_id": task.id,
        "family": task.family,
        "arm_id": arm.id,
        "execution_index": execution_index,
        "status": status,
        "duration_s": round(max(0.0, duration_s), 6),
        "request_timeout_s": request_timeout_s,
        "input_sha256": task.input_sha256,
        "grader_sha256": task.grader_sha256,
        "grade": {"passed": False, "reason": error, "details": {}},
        "completion": "",
        "tool_calls": [],
        "usage": {"input_tokens": 0, "output_tokens": 0},
        "runtime_provenance": {},
        "runtime_provenance_sha256": None,
    }


def run_evaluation(
    manifest: EvaluationManifest,
    *,
    output_dir: Path,
    runtime_budget_s: float,
    invoke: InvokeFn = invoke_via_wrapper,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Execute one AB/BA panel and write a single honest final artifact.

    ``output_dir`` must already be validated and must not exist.  The global
    monotonic budget is checked before every request.  Each transport receives
    the smaller of its arm timeout and the remaining budget, so an in-flight
    call has a concrete deadline.  There are no retries.
    """
    if not math.isfinite(runtime_budget_s) or runtime_budget_s <= 0:
        raise ValueError("runtime_budget_s must be finite and > 0")
    output_dir = validate_output_dir(output_dir)
    manifest_bytes = manifest.path.read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != manifest.raw_sha256:
        raise RuntimeError("manifest changed after validation; refusing to run")
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "manifest.snapshot.json").write_bytes(manifest_bytes)

    run_id = f"{manifest.suite_id}-{uuid.uuid4().hex[:12]}"
    calls_paths = {
        arm.id: output_dir / f"calls.{arm.id}.jsonl" for arm in manifest.arms
    }
    activity_path = output_dir / "worker_activity.jsonl"
    started_at = _utc_now()
    start = monotonic()
    outcomes_by_cell: dict[tuple[str, str], dict[str, Any]] = {}
    execution_order: list[dict[str, Any]] = []
    execution_index = 0
    budget_exhausted = False

    for task_index, task in enumerate(manifest.tasks):
        arm_order = (
            manifest.arms if task_index % 2 == 0 else tuple(reversed(manifest.arms))
        )
        for arm in arm_order:
            cell = (task.id, arm.id)
            elapsed_before = monotonic() - start
            remaining = runtime_budget_s - elapsed_before
            if budget_exhausted or remaining <= 0:
                budget_exhausted = True
                outcomes_by_cell[cell] = _failure_outcome(
                    task=task,
                    arm=arm,
                    execution_index=None,
                    status="not_run_budget",
                    duration_s=0.0,
                    request_timeout_s=None,
                    error="global monotonic runtime budget exhausted before request",
                )
                continue

            request_timeout = min(arm.request_timeout_s, remaining)
            request = InvocationRequest(
                run_id=run_id,
                task=task,
                arm=arm,
                request_timeout_s=request_timeout,
                calls_log_path=calls_paths[arm.id],
                worker_activity_path=activity_path,
            )
            execution_index += 1
            execution_order.append({
                "execution_index": execution_index,
                "task_id": task.id,
                "arm_id": arm.id,
                "request_timeout_s": round(request_timeout, 6),
            })
            request_start = monotonic()
            try:
                result = invoke(request)
                if not isinstance(result, InvocationResult):
                    raise TypeError("invoke must return InvocationResult")
            except Exception as exc:  # recorded as a failed planned outcome
                duration = monotonic() - request_start
                status = _exception_status(exc)
                outcomes_by_cell[cell] = _failure_outcome(
                    task=task,
                    arm=arm,
                    execution_index=execution_index,
                    status=status,
                    duration_s=duration,
                    request_timeout_s=request_timeout,
                    error=f"{type(exc).__name__}: {str(exc)[:1000]}",
                )
                if monotonic() - start >= runtime_budget_s:
                    budget_exhausted = True
                continue

            duration = monotonic() - request_start
            total_elapsed = monotonic() - start
            if duration > request_timeout or total_elapsed > runtime_budget_s:
                outcomes_by_cell[cell] = _failure_outcome(
                    task=task,
                    arm=arm,
                    execution_index=execution_index,
                    status="timeout",
                    duration_s=duration,
                    request_timeout_s=request_timeout,
                    error="request returned after its monotonic deadline; result discarded",
                )
                if total_elapsed >= runtime_budget_s:
                    budget_exhausted = True
            else:
                try:
                    outcomes_by_cell[cell] = _result_outcome(
                        request=request,
                        execution_index=execution_index,
                        result=result,
                        duration_s=duration,
                    )
                except Exception as exc:
                    outcomes_by_cell[cell] = _failure_outcome(
                        task=task,
                        arm=arm,
                        execution_index=execution_index,
                        status="error",
                        duration_s=duration,
                        request_timeout_s=request_timeout,
                        error=(
                            "grader/artifact failure: "
                            f"{type(exc).__name__}: {str(exc)[:1000]}"
                        ),
                    )

    # A budget hit may occur after the final completed call.  Fill every
    # planned cell explicitly so partial work cannot disappear from a rate.
    for task in manifest.tasks:
        for arm in manifest.arms:
            cell = (task.id, arm.id)
            if cell not in outcomes_by_cell:
                outcomes_by_cell[cell] = _failure_outcome(
                    task=task,
                    arm=arm,
                    execution_index=None,
                    status="not_run_budget",
                    duration_s=0.0,
                    request_timeout_s=None,
                    error="global monotonic runtime budget exhausted before request",
                )

    # Use the identical recorded duration for the derived summary so another
    # reader can reproduce throughput exactly from run.json.
    elapsed_s = round(max(0.0, monotonic() - start), 6)
    outcomes = [
        outcomes_by_cell[(task.id, arm.id)]
        for task in manifest.tasks
        for arm in manifest.arms
    ]
    incomplete_statuses = {
        outcome["status"]
        for outcome in outcomes
        if outcome["status"] not in {"passed", "failed"}
    }
    if "not_run_budget" in incomplete_statuses:
        run_status = "incomplete_budget"
    elif incomplete_statuses:
        run_status = "incomplete_transport"
    else:
        run_status = "complete"
    run_configuration = {
        "manifest_configuration_sha256": manifest.configuration_sha256,
        "runtime_budget_s": runtime_budget_s,
        "transport": getattr(invoke, "__qualname__", repr(invoke)),
    }
    artifact = {
        "schema_version": RUN_SCHEMA_VERSION,
        "run_id": run_id,
        "status": run_status,
        "started_at": started_at,
        "finished_at": _utc_now(),
        "elapsed_wall_s": round(elapsed_s, 6),
        "provenance": {
            "manifest_path": str(manifest.path),
            "manifest_sha256": manifest.raw_sha256,
            "manifest_configuration_sha256": manifest.configuration_sha256,
            "run_configuration_sha256": sha256_json(run_configuration),
            "run_configuration": run_configuration,
            "task_input_sha256": {
                task.id: task.input_sha256 for task in manifest.tasks
            },
            "task_grader_sha256": {
                task.id: task.grader_sha256 for task in manifest.tasks
            },
            "harness_file_sha256": _harness_hashes(),
            "source_snapshot_declared": manifest.source_snapshot,
            "arms": [arm.as_dict() for arm in manifest.arms],
        },
        "execution_order": execution_order,
        "outcomes": outcomes,
        "summary": summarize_outcomes(
            outcomes,
            task_ids=[task.id for task in manifest.tasks],
            task_families={task.id: task.family for task in manifest.tasks},
            arm_ids=manifest.arm_ids,
            elapsed_s=elapsed_s,
            bootstrap_samples=manifest.bootstrap_samples,
            bootstrap_seed=manifest.bootstrap_seed,
        ),
        "promotion": {
            "authorized": False,
            "decision": None,
            "reason": (
                "This harness emits descriptive evidence only and never "
                "changes production or makes a promotion decision."
            ),
        },
    }
    _write_json_atomic(output_dir / "run.json", artifact)
    return artifact


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true", help="print plan; no calls or writes")
    mode.add_argument("--run", action="store_true", help="execute the paired local canary")
    parser.add_argument(
        "--manifest",
        type=Path,
        required=True,
        help=f"frozen JSON manifest (bundled example: {DEFAULT_MANIFEST_PATH})",
    )
    parser.add_argument("--output-dir", type=Path, help="fresh isolated artifact directory")
    parser.add_argument(
        "--runtime-budget-s",
        type=float,
        help="hard wall-clock budget for the complete paired run",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        manifest = load_manifest(args.manifest)
    except ManifestError as exc:
        parser.error(str(exc))

    if args.plan:
        print(json.dumps(manifest.plan_dict(), indent=2, sort_keys=True))
        return 0

    if args.output_dir is None:
        parser.error("--run requires --output-dir")
    if args.runtime_budget_s is None:
        parser.error("--run requires --runtime-budget-s")
    if os.environ.get("MOCK_LLM") is not None:
        print(
            "REFUSE --run: MOCK_LLM is set. Unset it explicitly for a live "
            "local-server evaluation; no output was written.",
            file=sys.stderr,
        )
        return 2
    try:
        validate_live_configuration(manifest)
        output_dir = validate_output_dir(args.output_dir)
        artifact = run_evaluation(
            manifest,
            output_dir=output_dir,
            runtime_budget_s=args.runtime_budget_s,
        )
    except (FileExistsError, KeyError, ManifestError, ValueError) as exc:
        print(f"REFUSE --run: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "run_id": artifact["run_id"],
        "status": artifact["status"],
        "artifact": str(output_dir / "run.json"),
    }, sort_keys=True))
    return 0 if artifact["status"] == "complete" else 3


if __name__ == "__main__":
    raise SystemExit(main())
