"""Bounded one-arm runner for the stable laboratory benchmark.

The runner never starts, stops, swaps, or probes a model.  A supervisor admits
an already-served runtime and injects either ``invoke_via_wrapper`` or a
source-bound endpoint transport.  The run receipt is evidence, not admission;
independent replay and an external supervisor receipt are required later.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable

from .graders import GradeResult, grade_task
from .manifest import (
    LoadedDocument,
    ManifestError,
    canonical_json,
    validate_definition,
    validate_run_manifest,
)


RUN_SCHEMA = "stable-benchmark-run-receipt/v1"
GRADING_RESERVE_SECONDS = 5.0
REPO_ROOT = Path(__file__).resolve().parents[2]
RESERVED_OUTPUT_ROOTS = tuple(
    (REPO_ROOT / name).resolve() for name in ("logs", "memory", "run_state")
)
SOURCE_FILES = tuple(Path(__file__).with_name(name) for name in (
    "__init__.py", "fixtures.py", "graders.py", "manifest.py", "runner.py",
)) + tuple(REPO_ROOT / path for path in (
    # ``invoke_via_wrapper`` imports these files, directly or transitively.
    # Binding them prevents a policy or transport edit from being presented as
    # the same harness version in a later weekly run.
    "agent_wrapper/__init__.py",
    "agent_wrapper/wrapper.py",
    "agent_wrapper/worker_activity.py",
    "agent_wrapper/generation_policy.py",
    "agent_wrapper/upgrade_lease.py",
    "agent_wrapper/backends/__init__.py",
    "agent_wrapper/backends/base.py",
    "agent_wrapper/backends/anthropic.py",
    "agent_wrapper/backends/ollama_openai.py",
    "agent_wrapper/backends/qwen_vllm.py",
    "agent_wrapper/backends/vllm_openai.py",
    "schema/calls.jsonl.schema.json",
    "bench/weekly_upgrade_portfolio/code_sandbox.py",
))
CELL_STATUSES = frozenset({
    "passed", "failed", "abstained", "timeout", "transport_error",
    "invalid_output", "invalid", "skipped_budget", "unissued",
})


@dataclass(frozen=True)
class InvocationRequest:
    run_id: str
    task: dict[str, Any]
    arm: dict[str, Any]
    absolute_deadline_monotonic: float
    calls_log_path: Path
    worker_activity_path: Path


@dataclass(frozen=True)
class InvocationResult:
    completion: str
    records: tuple[dict[str, Any], ...]
    tool_trace: tuple[dict[str, Any], ...] = ()
    failure_code: str | None = None
    failure_detail: str | None = None
    attempt_count: int | None = None


InvokeFn = Callable[[InvocationRequest], InvocationResult]


class InvocationFailure(RuntimeError):
    """Transport failure carrying the issued-attempt ledger known to the adapter."""

    def __init__(
        self,
        message: str,
        *,
        attempt_count: int,
        records: tuple[dict[str, Any], ...] = (),
        timed_out: bool = False,
    ):
        super().__init__(message)
        self.attempt_count = attempt_count
        self.records = records
        self.timed_out = timed_out


def _exception_timed_out(exc: BaseException) -> bool:
    """Recognize a timeout through at most four wrapper/cause levels."""
    current: BaseException | None = exc
    seen: set[int] = set()
    for _ in range(4):
        if current is None or id(current) in seen:
            break
        seen.add(id(current))
        if (
            isinstance(current, TimeoutError)
            or getattr(current, "timed_out", False) is True
            or "timeout" in type(current).__name__.lower()
        ):
            return True
        current = current.__cause__ or current.__context__
    return False


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execution_source_hashes() -> dict[str, str]:
    return {
        str(path.relative_to(REPO_ROOT)): _sha_file(path)
        for path in SOURCE_FILES
    }


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def strict_json_object(content: Any) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(content, str) or not content.strip():
        return None, "visible completion is empty or not text"
    if content.lstrip().startswith("```") or content.rstrip().endswith("```"):
        return None, "Markdown envelopes are outside the versioned response contract"
    lowered = content.casefold()
    if any(marker in lowered for marker in ("<think>", "</think>", "<analysis>", "</analysis>")):
        return None, "reasoning-channel markup appeared in the visible completion"
    try:
        payload = json.loads(
            content,
            object_pairs_hook=_unique_object,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"non-finite {value}")),
        )
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        return None, f"completion is not exactly one finite JSON object: {exc}"
    if not isinstance(payload, dict):
        return None, "top-level completion must be an object"
    return payload, None


def validate_output_dir(path: Path | str) -> Path:
    output = Path(path).expanduser().resolve()
    if output == REPO_ROOT:
        raise ValueError("output directory cannot be the repository root")
    for reserved in RESERVED_OUTPUT_ROOTS:
        if output == reserved or reserved in output.parents:
            raise ValueError(f"output directory cannot be under {reserved}")
    if output.exists():
        raise FileExistsError(f"output directory already exists: {output}")
    return output


def _write_atomic(path: Path, value: Any) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("xb") as stream:
        stream.write(canonical_json(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)


def _append_private(path: Path, value: Any) -> None:
    with path.open("ab") as stream:
        stream.write(canonical_json(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def _tool_entries(task: dict[str, Any], trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for tool in task["tools"]:
        name = tool["name"]
        fixtures = tool["fixtures"]

        def implementation(_name: str = name, _fixtures: list[dict[str, Any]] = fixtures, **kwargs: Any) -> Any:
            result: Any = {"error": "not_found", "received_arguments": kwargs}
            for fixture in _fixtures:
                if fixture["arguments"] == kwargs:
                    result = fixture["result"]
                    break
            trace.append({"name": _name, "arguments": kwargs, "result": result})
            return result

        entries.append({
            "spec": {
                "type": "function",
                "function": {
                    "name": name,
                    "description": tool["description"],
                    "parameters": tool["parameters"],
                },
            },
            "impl": implementation,
        })
    return entries


def _fraction_fields(prefix: str, value: Fraction) -> dict[str, int]:
    return {f"{prefix}_num": value.numerator, f"{prefix}_den": value.denominator}


def _execute_system_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Execute the three micro-workflow tools from arguments, never fixture lookup."""
    if name == "compute_public_goods":
        contributions = arguments["contributions"]
        focal = arguments["focal_index"]
        multiplier = Fraction(arguments["multiplier_num"], arguments["multiplier_den"])
        if not contributions or focal < 0 or focal >= len(contributions):
            return {"error": "invalid_focal_index"}
        total = sum(contributions)
        endowment = arguments["endowment"]
        focal_utility = Fraction(endowment - contributions[focal]) + multiplier * total / len(contributions)
        joint_utility = Fraction(len(contributions) * endowment - total) + multiplier * total
        return {**_fraction_fields("focal", focal_utility), **_fraction_fields("joint", joint_utility)}
    if name == "evaluate_vickrey":
        value = arguments["value"]
        candidate = arguments["candidate_bid"]
        others = arguments["other_bids"]

        def utility(bid: int) -> tuple[int, int]:
            bids = [bid, *others]
            winner = max(range(len(bids)), key=lambda index: (bids[index], -index))
            price = sorted(bids, reverse=True)[1]
            return (value - price if winner == 0 else 0), winner

        own, winner = utility(candidate)
        best = max(utility(bid)[0] for bid in range(13))
        values = [value, *others]
        return {
            "own_utility": own,
            "efficient_winner": values[winner] == max(values),
            "regret": best - own,
        }
    if name == "check_evidence_support":
        denominator = arguments["denominator"]
        if denominator is None:
            return {"supported": False, "reason_code": "missing_denominator"}
        if denominator <= 0 or arguments["count"] < 0 or arguments["count"] > denominator:
            return {"supported": False, "reason_code": "invalid_count_or_denominator"}
        observed = Fraction(arguments["count"], denominator)
        supported = arguments["claim"] == "rate_is_60_percent" and observed == Fraction(3, 5)
        return {"supported": supported, "reason_code": "rate_matches" if supported else "rate_differs"}
    if name == "format_note":
        return {"formatted": arguments["note"]}
    return {"error": "unknown_tool"}


def _run_system_tool(task: dict[str, Any], name: Any, arguments: Any) -> dict[str, Any]:
    if not isinstance(name, str) or not isinstance(arguments, dict):
        return {"error": "unknown_tool_or_arguments"}
    selected = next((tool for tool in task["tools"] if tool["name"] == name), None)
    if selected is None:
        return {"error": "unknown_tool"}
    from jsonschema import Draft202012Validator

    errors = sorted(Draft202012Validator(selected["parameters"]).iter_errors(arguments), key=str)
    if errors:
        return {"error": "schema_validation", "detail": errors[0].message[:300]}
    try:
        return _execute_system_tool(name, arguments)
    except (ArithmeticError, KeyError, TypeError, ValueError) as exc:
        return {"error": "tool_execution", "detail": f"{type(exc).__name__}: {exc}"[:300]}


def _route(request: InvocationRequest, role: str) -> dict[str, Any]:
    route_id = request.arm["role_map"][role]
    return request.arm["routes"][route_id]


def _common_kwargs(request: InvocationRequest, *, role: str, max_tokens: int, timeout_s: float) -> dict[str, Any]:
    route = _route(request, role)
    return {
        "backend": route["backend"],
        "model": route["model"],
        "profile": route["profile"],
        "seed": request.arm["seed"],
        "max_tokens": max_tokens,
        "request_timeout_s": timeout_s,
        "caller_tag": f"stable_benchmark:{request.task['id']}",
        "parent_request_id": request.run_id,
        "log_path": str(request.calls_log_path),
    }


def _remaining(request: InvocationRequest) -> float:
    remaining = request.absolute_deadline_monotonic - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("episode deadline elapsed before the request")
    return remaining


def _remaining_for_inference(request: InvocationRequest) -> float:
    """Keep a small part of the episode deadline for trusted local grading."""
    remaining = _remaining(request) - GRADING_RESERVE_SECONDS
    if remaining <= 0:
        raise TimeoutError("episode grading reserve reached before the request")
    return remaining


def invoke_via_wrapper(request: InvocationRequest) -> InvocationResult:
    """Call the already-running local wrapper; never manage model lifecycle."""
    from agent_wrapper import worker_activity
    from agent_wrapper.wrapper import (
        ToolCallError,
        call_sync,
        call_with_tools,
        get_run_id,
        set_run_id,
    )

    task = request.task
    resource = task["resource"]
    max_tokens = resource["max_tokens_per_call"]
    prior_activity = worker_activity.DEFAULT_LOG_PATH
    prior_run_id = get_run_id()
    worker_activity.DEFAULT_LOG_PATH = request.worker_activity_path
    set_run_id(request.run_id)
    try:
        if task["mode"] == "system_mission":
            trace: list[dict[str, Any]] = []
            actor_contract = (
                task["prompt"]
                + "\nActor response contract: return exactly three fields: tool (the tool name), "
                "arguments (one object), and draft (one object). Available tool schemas: "
                + json.dumps([
                    {"name": tool["name"], "description": tool["description"], "parameters": tool["parameters"]}
                    for tool in task["tools"]
                ], sort_keys=True)
            )
            try:
                actor = call_sync(
                    [{"role": "system", "content": task["system"]}, {"role": "user", "content": actor_contract}],
                    **_common_kwargs(
                        request,
                        role="system_actor",
                        max_tokens=max_tokens,
                        timeout_s=min(60.0, _remaining_for_inference(request)),
                    ),
                )
            except Exception as exc:
                raise InvocationFailure(
                    str(exc), attempt_count=1, timed_out=_exception_timed_out(exc)
                ) from exc
            actor_payload, actor_error = strict_json_object(actor.get("completion"))
            if (
                actor_error
                or actor_payload is None
                or set(actor_payload) != {"tool", "arguments", "draft"}
                or not isinstance(actor_payload.get("arguments"), dict)
                or not isinstance(actor_payload.get("draft"), dict)
            ):
                return InvocationResult(
                    completion=actor.get("completion", ""),
                    records=(actor,),
                    failure_code="invalid_actor_output",
                    failure_detail=actor_error or "actor response fields or object types differ",
                )
            result = _run_system_tool(task, actor_payload["tool"], actor_payload["arguments"])
            trace.append({"name": actor_payload["tool"], "arguments": actor_payload["arguments"], "result": result})
            critic_prompt = (
                task["prompt"]
                + "\nReview and replace the actor draft using the trusted tool receipt. "
                + "Actor: " + json.dumps(actor_payload, sort_keys=True)
                + "\nTrusted tool receipt: " + json.dumps(trace[0], sort_keys=True)
                + "\nReturn only the final artifact requested by the mission."
            )
            try:
                critic = call_sync(
                    [{"role": "system", "content": task["system"]}, {"role": "user", "content": critic_prompt}],
                    **_common_kwargs(
                        request,
                        role="system_critic",
                        max_tokens=max_tokens,
                        timeout_s=_remaining_for_inference(request),
                    ),
                )
            except Exception as exc:
                raise InvocationFailure(
                    str(exc),
                    attempt_count=2,
                    records=(actor,),
                    timed_out=_exception_timed_out(exc),
                ) from exc
            return InvocationResult(
                completion=critic.get("completion", ""),
                records=(actor, critic),
                tool_trace=tuple(trace),
            )

        messages = [
            {"role": "system", "content": task["system"]},
            {"role": "user", "content": task["prompt"]},
        ]
        kwargs = _common_kwargs(
            request,
            role="capability",
            max_tokens=max_tokens,
            timeout_s=_remaining(request),
        )
        if task["mode"] == "tools":
            trace = []
            try:
                records = tuple(call_with_tools(
                    messages,
                    _tool_entries(task, trace),
                    max_depth=task["resource"]["max_model_calls"] - 1,
                    **kwargs,
                ))
            except ToolCallError as exc:
                return InvocationResult(
                    completion=(exc.records[-1].get("completion", "") if exc.records else ""),
                    records=tuple(exc.records),
                    tool_trace=tuple(trace),
                    failure_code=exc.failure_code,
                    failure_detail=str(exc),
                )
            return InvocationResult(
                completion=records[-1].get("completion", "") if records else "",
                records=records,
                tool_trace=tuple(trace),
            )
        record = call_sync(messages, **kwargs)
        return InvocationResult(completion=record.get("completion", ""), records=(record,))
    finally:
        set_run_id(prior_run_id)
        worker_activity.DEFAULT_LOG_PATH = prior_activity


def _validate_execution_gate(
    gate: Any,
    definition: LoadedDocument,
    run_manifest: LoadedDocument,
) -> dict[str, Any]:
    required = {
        "admitted", "definition_sha256", "run_manifest_sha256", "route_runtime_identities",
        "endpoint_bindings_sha256", "supervision_receipt_sha256", "resource_guard_sha256",
    }
    if not isinstance(gate, dict) or set(gate) != required or gate.get("admitted") is not True:
        raise ValueError("external execution gate is absent or malformed")
    if gate["definition_sha256"] != definition.raw_sha256 or gate["run_manifest_sha256"] != run_manifest.raw_sha256:
        raise ValueError("external execution gate binds different manifest bytes")
    arm = run_manifest.document["arm"]
    expected_identities = {
        route_id: route["runtime_identity"] for route_id, route in arm["routes"].items()
    }
    if gate["route_runtime_identities"] != expected_identities:
        raise ValueError("external execution gate binds different route runtimes")
    for key in ("endpoint_bindings_sha256", "supervision_receipt_sha256", "resource_guard_sha256"):
        value = gate[key]
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError(f"external execution gate {key} is not a SHA-256 digest")
    return gate


def _validate_record(record: dict[str, Any], task: dict[str, Any], arm: dict[str, Any], role: str) -> str | None:
    route_id = arm["role_map"][role]
    route = arm["routes"][route_id]
    if record.get("model") != route["model"] or record.get("backend") != route["backend"]:
        return "served model or backend differs from the bound arm"
    if record.get("profile") != route["profile"]:
        return "generation profile differs from the bound arm"
    if record.get("seed") != arm["seed"]:
        return "seed differs from the bound arm"
    if record.get("max_tokens") != task["resource"]["max_tokens_per_call"]:
        return "max_tokens differs from the task ceiling"
    policy = route["expected_policy"]
    for key in ("temperature", "top_p", "reasoning_effort", "sampling_extra"):
        if key not in record or record[key] != policy[key]:
            return f"{key} differs from the bound policy"
    for key in ("request_id", "model_version", "host_metadata", "usage"):
        if key not in record:
            return f"runtime provenance field {key} is missing"
    return None


def _status_for_grade(grade: GradeResult) -> str:
    if grade.abstained:
        return "abstained"
    if grade.passed:
        return "passed"
    if grade.failure_code in {"invalid_output"}:
        return "invalid_output"
    if grade.failure_code in {"grader_unavailable", "grader_invalid"}:
        return "invalid"
    return "failed"


def _public_outcome(
    task: dict[str, Any],
    result: InvocationResult,
    grade: GradeResult,
    *,
    duration_s: float,
    grading_duration_s: float,
    model_calls: int,
    model_calls_exact: bool,
    raw_sha256: str,
) -> dict[str, Any]:
    usage = {"input_tokens": 0, "output_tokens": 0}
    for record in result.records:
        row = record.get("usage") or {}
        for key in usage:
            if isinstance(row.get(key), int) and not isinstance(row[key], bool):
                usage[key] += row[key]
    return {
        "task_id": task["id"],
        "panel": task["panel"],
        "domain": task["domain"],
        "construct": task["construct"],
        "cell_status": _status_for_grade(grade),
        "score_credit": grade.passed,
        "failure_code": grade.failure_code,
        "reason": grade.reason,
        "model_calls": model_calls,
        "model_calls_exact": model_calls_exact,
        "duration_s": round(duration_s, 6),
        "grading_duration_s": round(grading_duration_s, 6),
        "usage": usage,
        "metrics": grade.metrics,
        "raw_evidence_sha256": raw_sha256,
    }


def _terminal_outcome(task: dict[str, Any], status: str, reason: str) -> dict[str, Any]:
    if status not in CELL_STATUSES:
        raise ValueError(f"unsupported terminal status {status!r}")
    return {
        "task_id": task["id"], "panel": task["panel"], "domain": task["domain"],
        "construct": task["construct"], "cell_status": status, "score_credit": False,
        "failure_code": status, "reason": reason, "model_calls": 0,
        "model_calls_exact": True,
        "duration_s": 0.0, "grading_duration_s": 0.0,
        "usage": {"input_tokens": 0, "output_tokens": 0},
        "metrics": {}, "raw_evidence_sha256": None,
    }


def _summarize(outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts = {status: 0 for status in sorted(CELL_STATUSES)}
    panels: dict[str, dict[str, int]] = {}
    constructs: dict[str, dict[str, int]] = {}
    for row in outcomes:
        status_counts[row["cell_status"]] += 1
        for target, key in ((panels, row["panel"]), (constructs, row["construct"])):
            bucket = target.setdefault(key, {"planned": 0, "credited": 0})
            bucket["planned"] += 1
            bucket["credited"] += int(row["score_credit"])
    return {
        "independent_units_planned": len(outcomes),
        "independent_units_accounted": len(outcomes),
        "credited": sum(row["score_credit"] for row in outcomes),
        "status_counts": status_counts,
        "model_calls": sum(row["model_calls"] for row in outcomes),
        "model_calls_semantics": (
            "exact" if all(row["model_calls_exact"] for row in outcomes)
            else "conservative_upper_bound_where_transport_failed"
        ),
        "by_panel": panels,
        "by_construct": constructs,
        "omnibus_score": None,
    }


def run_arm(
    definition: LoadedDocument,
    run_manifest: LoadedDocument,
    *,
    output_dir: Path | str,
    execution_gate: dict[str, Any],
    absolute_deadline_monotonic: float,
    cancel_event: Any,
    invoke: InvokeFn = invoke_via_wrapper,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Execute exactly one bound arm under an external supervisor gate.

    The output directory must not exist.  ``cancel_event`` must expose
    ``is_set()``.  No retries occur.  The runner accounts for all 21 units and
    emits a terminal run receipt even when the deadline or cancellation aborts
    remaining work.
    """
    validate_definition(definition.document, require_published=True)
    validate_run_manifest(run_manifest.document, definition)
    harness = run_manifest.document["harness_identity"]
    if (
        harness["scaffold_id"] != "stable-benchmark-runner-v1"
        or harness["source_sha256"] != execution_source_hashes()
    ):
        raise ValueError("bound harness identity differs from the executable source bundle")
    _validate_execution_gate(execution_gate, definition, run_manifest)
    if not callable(getattr(cancel_event, "is_set", None)):
        raise ValueError("cancel_event must expose is_set()")
    if not isinstance(absolute_deadline_monotonic, (int, float)) or not math.isfinite(float(absolute_deadline_monotonic)):
        raise ValueError("absolute_deadline_monotonic must be finite")
    output = validate_output_dir(output_dir)
    if absolute_deadline_monotonic <= monotonic():
        raise ValueError("absolute deadline has already elapsed")
    output.mkdir(parents=True, mode=0o700)
    private = output / "private"
    private.mkdir(mode=0o700)
    shutil.copyfile(definition.path, output / "definition.snapshot.json")
    shutil.copyfile(run_manifest.path, output / "run-manifest.snapshot.json")
    _write_atomic(output / "execution-gate.snapshot.json", execution_gate)
    raw_path = private / "raw-attempts.jsonl"
    raw_path.touch(mode=0o600)
    run_id = f"{definition.document['suite_id']}-{run_manifest.document['arm']['id']}-{uuid.uuid4().hex[:12]}"
    started_at = _utc_now()
    started = monotonic()
    outcomes: list[dict[str, Any]] = []
    terminal = "complete"
    arm = run_manifest.document["arm"]

    for task in definition.document["tasks"]:
        if cancel_event.is_set() or monotonic() >= absolute_deadline_monotonic:
            terminal = "aborted"
            outcomes.append(_terminal_outcome(task, "skipped_budget", "supervisor cancellation or deadline before episode"))
            continue
        episode_deadline = min(
            absolute_deadline_monotonic,
            monotonic() + task["resource"]["episode_timeout_s"],
        )
        request = InvocationRequest(
            run_id=run_id,
            task=task,
            arm=arm,
            absolute_deadline_monotonic=episode_deadline,
            calls_log_path=private / "calls.jsonl",
            worker_activity_path=private / "worker-activity.jsonl",
        )
        before = monotonic()
        try:
            result = invoke(request)
            if not isinstance(result, InvocationResult):
                raise TypeError("invoke must return InvocationResult")
        except Exception as exc:  # every planned unit remains visible
            duration = max(0.0, monotonic() - before)
            timeout = _exception_timed_out(exc)
            partial_records = tuple(getattr(exc, "records", ()))
            declared_attempts = getattr(exc, "attempt_count", None)
            attempts_exact = isinstance(declared_attempts, int) and not isinstance(declared_attempts, bool)
            attempts = (
                declared_attempts
                if attempts_exact
                else task["resource"]["max_model_calls"]
            )
            attempts = max(attempts, len(partial_records))
            raw = {
                "task_id": task["id"], "status": "timeout" if timeout else "transport_error",
                "completion": None, "records": list(partial_records), "tool_trace": [],
                "attempt_count": attempts,
                "attempt_count_exact": attempts_exact,
                "inference_duration_s": round(duration, 6), "grading_duration_s": 0.0,
                "deadline_exceeded": timeout, "deadline_phase": "inference" if timeout else None,
                "error": f"{type(exc).__name__}: {str(exc)[:1000]}",
            }
            raw_sha = hashlib.sha256(canonical_json(raw)).hexdigest()
            _append_private(raw_path, {**raw, "raw_evidence_sha256": raw_sha})
            outcome = _terminal_outcome(task, raw["status"], raw["error"])
            outcome["model_calls"] = attempts
            outcome["model_calls_exact"] = attempts_exact
            outcome["duration_s"] = round(duration, 6)
            outcome["raw_evidence_sha256"] = raw_sha
            outcomes.append(outcome)
            continue

        inference_finished = monotonic()
        inference_duration = max(0.0, inference_finished - before)
        attempts = result.attempt_count if result.attempt_count is not None else len(result.records)
        drift = None
        if (
            isinstance(attempts, bool)
            or not isinstance(attempts, int)
            or attempts < len(result.records)
            or attempts < 1
            or attempts > task["resource"]["max_model_calls"]
        ):
            drift = "model-call ceiling exceeded"
        for record_index, record in enumerate(result.records):
            role = (
                "system_actor" if task["mode"] == "system_mission" and record_index == 0
                else "system_critic" if task["mode"] == "system_mission"
                else "capability"
            )
            drift = drift or _validate_record(record, task, arm, role)
        inference_late = inference_finished > episode_deadline
        grading_started = monotonic()
        grade = GradeResult(False, "episode returned after its monotonic deadline", "invalid_output")
        if not inference_late:
            if drift:
                grade = GradeResult(False, drift, "grader_invalid")
            elif result.failure_code:
                grade = GradeResult(False, result.failure_detail or result.failure_code, "invalid_output")
            else:
                payload, parse_error = strict_json_object(result.completion)
                grade = (
                    GradeResult(False, parse_error or "invalid completion", "invalid_output")
                    if payload is None
                    else grade_task(task, payload, tool_trace=list(result.tool_trace))
                )
        grading_duration = max(0.0, monotonic() - grading_started)
        grading_late = not inference_late and monotonic() > episode_deadline
        if grading_late:
            grade = GradeResult(False, "trusted grading exceeded the episode deadline", "grader_invalid")
        duration = max(0.0, monotonic() - before)
        raw = {
            "task_id": task["id"],
            "status": "returned",
            "completion": result.completion,
            "records": list(result.records),
            "tool_trace": list(result.tool_trace),
            "failure_code": result.failure_code,
            "failure_detail": result.failure_detail,
            "attempt_count": attempts,
            "attempt_count_exact": True,
            "inference_duration_s": round(inference_duration, 6),
            "grading_duration_s": round(grading_duration, 6),
            "deadline_exceeded": inference_late or grading_late,
            "deadline_phase": "inference" if inference_late else "grading" if grading_late else None,
        }
        raw_sha = hashlib.sha256(canonical_json(raw)).hexdigest()
        _append_private(raw_path, {**raw, "raw_evidence_sha256": raw_sha})
        if inference_late:
            outcome = _terminal_outcome(task, "timeout", "episode returned after its monotonic deadline")
            outcome["model_calls"] = attempts
            outcome["model_calls_exact"] = True
            outcome["duration_s"] = round(duration, 6)
            outcome["raw_evidence_sha256"] = raw_sha
            outcomes.append(outcome)
            continue
        outcomes.append(_public_outcome(
            task,
            result,
            grade,
            duration_s=duration,
            grading_duration_s=grading_duration,
            model_calls=attempts,
            model_calls_exact=True,
            raw_sha256=raw_sha,
        ))

    elapsed = max(0.0, monotonic() - started)
    if sum(row["model_calls"] for row in outcomes) > definition.document["resource_envelope"]["max_model_calls_per_arm"]:
        terminal = "aborted"
    receipt = {
        "schema_version": RUN_SCHEMA,
        "run_id": run_id,
        "terminal_status": terminal,
        "started_at": started_at,
        "finished_at": _utc_now(),
        "elapsed_s": round(elapsed, 6),
        "definition_sha256": definition.raw_sha256,
        "run_manifest_sha256": run_manifest.raw_sha256,
        "execution_gate_sha256": hashlib.sha256((output / "execution-gate.snapshot.json").read_bytes()).hexdigest(),
        "execution_source_sha256": execution_source_hashes(),
        "arm_id": arm["id"],
        "comparison_id": run_manifest.document["comparison_id"],
        "outcomes": outcomes,
        "summary": _summarize(outcomes),
        "replay_status": "not_run",
        "admission_status": "not_evaluated",
        "promotion_authorized": False,
    }
    _write_atomic(output / "run.json", receipt)
    return receipt


def write_unissued_receipt(
    definition: LoadedDocument,
    run_manifest: LoadedDocument,
    *,
    output_dir: Path | str,
    reason: str,
) -> dict[str, Any]:
    """Account for an arm that never received an execution gate or model call."""
    validate_definition(definition.document, require_published=True)
    validate_run_manifest(run_manifest.document, definition)
    output = validate_output_dir(output_dir)
    output.mkdir(parents=True, mode=0o700)
    if definition.path is None or run_manifest.path is None:
        raise ValueError("unissued receipt requires file-backed definition and run manifest")
    shutil.copyfile(definition.path, output / "definition.snapshot.json")
    shutil.copyfile(run_manifest.path, output / "run-manifest.snapshot.json")
    outcomes = [_terminal_outcome(task, "unissued", reason) for task in definition.document["tasks"]]
    receipt = {
        "schema_version": RUN_SCHEMA,
        "run_id": f"{definition.document['suite_id']}-{run_manifest.document['arm']['id']}-unissued",
        "terminal_status": "unissued",
        "started_at": None,
        "finished_at": _utc_now(),
        "elapsed_s": 0.0,
        "definition_sha256": definition.raw_sha256,
        "run_manifest_sha256": run_manifest.raw_sha256,
        "execution_gate_sha256": None,
        "execution_source_sha256": execution_source_hashes(),
        "arm_id": run_manifest.document["arm"]["id"],
        "comparison_id": run_manifest.document["comparison_id"],
        "outcomes": outcomes,
        "summary": _summarize(outcomes),
        "replay_status": "not_applicable",
        "admission_status": "withheld_unissued",
        "promotion_authorized": False,
    }
    _write_atomic(output / "run.json", receipt)
    return receipt


__all__ = [
    "CELL_STATUSES", "InvocationFailure", "InvocationRequest", "InvocationResult", "execution_source_hashes",
    "invoke_via_wrapper", "run_arm", "strict_json_object", "validate_output_dir",
    "write_unissued_receipt",
]
