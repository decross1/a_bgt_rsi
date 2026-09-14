"""Run the bounded public synthetic game/science development portfolio.

``--plan`` is read-only and never imports the model wrapper. ``--run`` writes
only to a fresh isolated output directory, performs 16 serial calls, and never
dispatches a coordinator action or changes production state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .code_sandbox import SandboxUnavailable, run_case, sandbox_runtime_identity
from .graders import GradeResult, grade_task
from .manifest import (
    DEFAULT_MANIFEST,
    REPO_ROOT,
    ManifestError,
    canonical_json,
    load_manifest,
    plan_dict,
    validate_manifest,
)

RUN_SCHEMA_VERSION = "weekly-upgrade-game-science-run/v1"
EXECUTION_SOURCE_FILES = (
    Path(__file__).with_name("manifest.py"),
    Path(__file__).with_name("graders.py"),
    Path(__file__).with_name("code_sandbox.py"),
    Path(__file__).resolve(),
)
RESERVED_OUTPUT_ROOTS = tuple(
    (REPO_ROOT / name).resolve()
    for name in ("logs", "memory", "run_state", "journal", "findings")
)
InvokeFn = Callable[..., dict[str, Any]]


def _number(value: Any, where: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{where} must be a finite number")  # noqa: TRY004
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0):
        suffix = " > 0" if positive else ""
        raise ValueError(f"{where} must be finite{suffix}")
    return result


def _write_json(path: Path, value: Any) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_bytes(canonical_json(value) + b"\n")
    temp.replace(path)


def _append_jsonl(path: Path, value: Any) -> None:
    with path.open("ab") as handle:
        handle.write(canonical_json(value) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())


def _strict_object(value: Any) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(value, str):
        return None, "completion is not text"

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key!r}")
            result[key] = item
        return result

    def reject_constant(value: str) -> Any:
        raise ValueError(f"non-finite JSON constant: {value}")

    try:
        parsed = json.loads(
            value,
            object_pairs_hook=unique_object,
            parse_constant=reject_constant,
        )
    except (json.JSONDecodeError, ValueError) as exc:
        return None, f"completion is not one strict JSON value: {exc}"
    if not isinstance(parsed, dict):
        return None, "completion JSON must be an object"
    return parsed, None


def _validate_output_dir(path: str | Path) -> Path:
    output = Path(path).expanduser().resolve()
    if output == REPO_ROOT:
        raise ValueError("output directory cannot be the repository root")
    for reserved in RESERVED_OUTPUT_ROOTS:
        if output == reserved or reserved in output.parents:
            raise ValueError(f"output directory cannot be under live root {reserved}")
    if output.exists():
        raise FileExistsError(f"output directory already exists: {output}")
    return output


def _runtime_identity(
    record: Any, arm: dict[str, Any], task: dict[str, Any]
) -> tuple[dict[str, Any], str | None]:
    if not isinstance(record, dict):
        return {}, "wrapper result is not an object"
    identity = {
        "model": record.get("model"),
        "model_version": record.get("model_version"),
        "backend": record.get("backend"),
        "host_metadata": record.get("host_metadata"),
        "profile": record.get("profile"),
        "temperature": record.get("temperature"),
        "top_p": record.get("top_p"),
        "seed": record.get("seed"),
        "reasoning_effort": record.get("reasoning_effort"),
        "sampling_extra": record.get("sampling_extra"),
        "max_tokens": record.get("max_tokens"),
    }
    if identity["model"] != arm["model"]:
        return identity, f"model drift: expected {arm['model']!r}, got {identity['model']!r}"
    if identity["backend"] != arm["backend"]:
        return identity, f"backend drift: expected {arm['backend']!r}, got {identity['backend']!r}"
    if not isinstance(identity["model_version"], str) or not identity["model_version"].strip():
        return identity, "model_version provenance is missing"
    if not isinstance(identity["host_metadata"], dict):
        return identity, "host_metadata provenance is missing"
    expected = {
        "profile": arm["profile"],
        "temperature": arm["expected_policy"]["temperature"],
        "top_p": arm["expected_policy"]["top_p"],
        "seed": arm["seed"],
        "reasoning_effort": arm["expected_policy"]["reasoning_effort"],
    }
    for key, value in expected.items():
        if identity[key] != value:
            return identity, f"resolved policy drift for {key}: expected {value!r}, got {identity[key]!r}"
    if not isinstance(identity["sampling_extra"], dict):
        return identity, "resolved sampling_extra provenance is missing"
    if identity["max_tokens"] != task["max_tokens"]:
        return identity, (
            f"resolved max_tokens drift: expected {task['max_tokens']!r}, "
            f"got {identity['max_tokens']!r}"
        )
    return identity, None


def _messages(task: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": task["system"]},
        {"role": "user", "content": task["prompt"]},
    ]


def _call_kwargs(
    arm: dict[str, Any], task: dict[str, Any], calls_log: Path, remaining_s: float
) -> dict[str, Any]:
    return {
        "profile": arm["profile"],
        "seed": arm["seed"],
        "max_tokens": task["max_tokens"],
        "request_timeout_s": min(float(task["request_timeout_s"]), remaining_s),
        "caller_tag": f"weekly_upgrade.portfolio.{task['family']}",
        "parent_request_id": None,
        "log_path": str(calls_log),
        "backend": arm["backend"],
        "model": arm["model"],
    }


def _error_status(exc: Exception) -> str:
    return "timeout" if isinstance(exc, TimeoutError) or "timeout" in type(exc).__name__.lower() else "error"


def _summarize(outcomes: list[dict[str, Any]], elapsed_s: float) -> dict[str, Any]:
    arms = sorted({row["arm"] for row in outcomes})
    families = sorted({row["family"] for row in outcomes})
    by_arm: dict[str, dict[str, Any]] = {}
    for arm in arms:
        rows = [row for row in outcomes if row["arm"] == arm]
        passed = sum(row.get("passed") is True for row in rows)
        by_arm[arm] = {
            "attempted": len(rows),
            "passed": passed,
            "pass_rate": passed / len(rows) if rows else None,
            "by_family": {
                family: {
                    "attempted": sum(row["family"] == family for row in rows),
                    "passed": sum(
                        row["family"] == family and row.get("passed") is True for row in rows
                    ),
                }
                for family in families
            },
        }
    total_passed = sum(row.get("passed") is True for row in outcomes)
    return {
        "by_arm": by_arm,
        "elapsed_s_including_failures": elapsed_s,
        "correct_task_throughput_per_hour": (
            total_passed / (elapsed_s / 3600) if elapsed_s > 0 else None
        ),
    }


def run_experiment(
    manifest: dict[str, Any],
    *,
    output_dir: str | Path,
    runtime_budget_s: float,
    invoke: InvokeFn | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Execute the exact paired matrix, keeping every declared cell."""
    validate_manifest({key: value for key, value in manifest.items() if not key.startswith("_")})
    runtime = _number(runtime_budget_s, "runtime_budget_s", positive=True)
    ceiling = float(manifest["resource_limits"]["max_total_runtime_s"])
    if runtime > ceiling:
        raise ValueError(f"runtime_budget_s cannot exceed {ceiling}")
    output = _validate_output_dir(output_dir)
    if invoke is None and os.environ.get("MOCK_LLM"):
        raise ValueError("REFUSE live portfolio while MOCK_LLM is set")
    output.mkdir(parents=True)
    shutil.copyfile(manifest["_path"], output / "manifest.snapshot.json")

    run_id = f"weekly-portfolio-{uuid.uuid4()}"
    start = monotonic()
    deadline = start + runtime
    grading_elapsed = 0.0
    raw_path = output / "raw_attempts.jsonl"
    parsed_path = output / "outcomes.jsonl"
    calls_log = output / "calls.jsonl"
    outcomes: list[dict[str, Any]] = []
    execution_hashes = {
        str(path.relative_to(REPO_ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in EXECUTION_SOURCE_FILES
    }
    plan = plan_dict(manifest)
    arms = {arm["id"]: arm for arm in manifest["arms"]}
    tasks = {task["id"]: task for task in manifest["tasks"]}
    sandbox_expected = manifest["sandbox_runtime"]
    try:
        sandbox_observed = sandbox_runtime_identity(
            bwrap_path=sandbox_expected["bubblewrap_path"],
            python_path=sandbox_expected["python_path"],
        )
    except SandboxUnavailable as exc:
        sandbox_observed = None
        sandbox_error = str(exc)
    else:
        sandbox_error = (
            None
            if sandbox_observed == sandbox_expected
            else "sandbox runtime differs from the preregistered content identity"
        )

    def portfolio_code_runner(
        source: str,
        function_name: str,
        arguments: list[Any],
        *,
        timeout_s: float,
    ) -> Any:
        if sandbox_error is not None:
            raise SandboxUnavailable(sandbox_error)
        return run_case(
            source,
            function_name,
            arguments,
            timeout_s=timeout_s,
            max_output_bytes=manifest["resource_limits"]["max_raw_completion_bytes"],
            bwrap_path=sandbox_expected["bubblewrap_path"],
            python_path=sandbox_expected["python_path"],
        )

    invoke_fn = invoke
    if invoke_fn is None:
        from agent_wrapper import worker_activity, wrapper

        def isolated_call(messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]:
            prior_path = worker_activity.DEFAULT_LOG_PATH
            prior_run_id = wrapper.get_run_id()
            worker_activity.DEFAULT_LOG_PATH = output / "worker_activity.jsonl"
            wrapper.set_run_id(run_id)
            try:
                return wrapper.call_sync(messages, **kwargs)
            finally:
                wrapper.set_run_id(prior_run_id)
                worker_activity.DEFAULT_LOG_PATH = prior_path

        invoke_fn = isolated_call

    def persist(status: str) -> dict[str, Any]:
        elapsed = max(0.0, monotonic() - start)
        artifact = {
            "schema_version": RUN_SCHEMA_VERSION,
            "run_id": run_id,
            "status": status,
            "manifest_sha256": manifest["_raw_sha256"],
            "configuration_sha256": manifest["_configuration_sha256"],
            "execution_source_sha256": execution_hashes,
            "sandbox_runtime_expected": sandbox_expected,
            "sandbox_runtime_observed": sandbox_observed,
            "sandbox_runtime_valid": sandbox_error is None,
            "sandbox_runtime_error": sandbox_error,
            "runtime_budget_s": runtime,
            "grading_elapsed_s": grading_elapsed,
            "declared_attempts": len(plan["order"]),
            "attempts_recorded": len(outcomes),
            "outcomes": outcomes,
            "summary": _summarize(outcomes, elapsed),
            "promotion_authorized": False,
        }
        _write_json(output / "run.json", artifact)
        return artifact

    persist("running")

    for execution_index, planned in enumerate(plan["order"]):
        task = tasks[planned["task_id"]]
        arm = arms[planned["arm"]]
        before = monotonic()
        remaining = deadline - before
        base = {
            "attempt_id": planned["attempt_id"],
            "execution_index": execution_index,
            "task_id": task["id"],
            "family": task["family"],
            "mode": task["mode"],
            "arm": arm["id"],
            "request_timeout_s": min(float(task["request_timeout_s"]), remaining) if remaining > 0 else None,
        }
        if remaining <= 0:
            raw = {**base, "status": "not_run_budget", "completion": None, "error": "runtime budget exhausted"}
            _append_jsonl(raw_path, raw)
            outcome = {
                **base,
                "status": "not_run_budget",
                "passed": False,
                "failure_code": "budget",
                "reason": "runtime budget exhausted",
            }
        else:
            try:
                record = invoke_fn(
                    _messages(task),
                    **_call_kwargs(arm, task, calls_log, remaining),
                )
            except Exception as exc:  # noqa: BLE001 - every call remains a denominator row
                status = _error_status(exc)
                raw = {
                    **base,
                    "status": status,
                    "completion": None,
                    "error": f"{type(exc).__name__}: {exc}",
                }
                _append_jsonl(raw_path, raw)
                outcome = {
                    **base,
                    "status": status,
                    "passed": False,
                    "failure_code": "transport",
                    "reason": raw["error"],
                }
            else:
                completion = record.get("completion") if isinstance(record, dict) else None
                completion_bytes = (
                    completion.encode("utf-8") if isinstance(completion, str) else b""
                )
                oversized = len(completion_bytes) > manifest["resource_limits"]["max_raw_completion_bytes"]
                raw = {
                    **base,
                    "status": "returned",
                    "completion": None if oversized else completion,
                    "completion_sha256": hashlib.sha256(completion_bytes).hexdigest(),
                    "completion_bytes": len(completion_bytes),
                    "completion_omitted_over_limit": oversized,
                    "request_id": record.get("request_id") if isinstance(record, dict) else None,
                    "usage": record.get("usage") if isinstance(record, dict) else None,
                    "response_telemetry": (
                        {
                            "finish_reason": record.get("finish_reason"),
                            "reasoning_chars": record.get("reasoning_chars"),
                        }
                        if isinstance(record, dict)
                        else None
                    ),
                    "error": None,
                }
                _append_jsonl(raw_path, raw)  # durable before parse or execution
                identity, drift = _runtime_identity(record, arm, task)
                request_id = record.get("request_id") if isinstance(record, dict) else None
                if not isinstance(request_id, str) or not request_id.strip():
                    drift = "; ".join(
                        part for part in (drift, "request_id provenance is missing") if part
                    )
                payload, parse_error = _strict_object(None if oversized else completion)
                if oversized:
                    grade = GradeResult(False, "completion exceeded the raw-output limit", failure_code="output_limit")
                elif drift:
                    grade = GradeResult(False, drift, failure_code="runtime_drift")
                elif parse_error:
                    grade = GradeResult(False, parse_error, failure_code="schema")
                elif grading_elapsed >= manifest["resource_limits"]["max_grading_runtime_s"]:
                    grade = GradeResult(False, "grading budget exhausted", failure_code="inconclusive_grader")
                else:
                    grade_start = monotonic()
                    grade_ceiling = float(
                        manifest["resource_limits"]["max_grading_runtime_s"]
                    )
                    grade = grade_task(
                        task,
                        payload,
                        code_runner=portfolio_code_runner,
                        grading_deadline=min(
                            deadline,
                            grade_start + max(0.0, grade_ceiling - grading_elapsed),
                        ),
                        monotonic=monotonic,
                    )
                    grading_elapsed += max(0.0, monotonic() - grade_start)
                outcome = {
                    **base,
                    "status": "returned",
                    "request_id": request_id,
                    "runtime_identity": identity,
                    "runtime_identity_valid": drift is None,
                    "passed": grade.passed,
                    "failure_code": grade.failure_code,
                    "reason": grade.reason,
                    "grade_details": grade.details,
                }
        outcome["duration_s"] = max(0.0, monotonic() - before)
        _append_jsonl(parsed_path, outcome)
        outcomes.append(outcome)
        persist("running")

    complete_transport = len(outcomes) == len(plan["order"]) and all(
        row["status"] == "returned" for row in outcomes
    )
    runtime_identity_fields = {"model", "model_version", "backend", "host_metadata"}
    identities = {
        json.dumps(
            {
                key: value
                for key, value in row["runtime_identity"].items()
                if key in runtime_identity_fields
            },
            sort_keys=True,
        )
        for row in outcomes
        if isinstance(row.get("runtime_identity"), dict)
    }
    runtime_valid = (
        len(outcomes) == len(plan["order"])
        and all(row.get("runtime_identity_valid") is True for row in outcomes)
        and len(identities) == 1
    )
    grader_valid = not any(
        row.get("failure_code") == "inconclusive_grader" for row in outcomes
    )
    if not complete_transport:
        status = "incomplete_transport"
    elif not runtime_valid:
        status = "invalid_runtime_drift"
    elif not grader_valid:
        status = "invalid_grader"
    else:
        status = "complete"
    return persist(status)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--output-dir")
    parser.add_argument("--runtime-budget-s", type=float)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        manifest = load_manifest(args.manifest)
        if args.plan:
            print(json.dumps(plan_dict(manifest), indent=2))
            return 0
        if not args.output_dir or args.runtime_budget_s is None:
            raise ValueError("--run requires --output-dir and --runtime-budget-s")
        if os.environ.get("MOCK_LLM"):
            raise ValueError("REFUSE live portfolio while MOCK_LLM is set")
        result = run_experiment(
            manifest,
            output_dir=args.output_dir,
            runtime_budget_s=args.runtime_budget_s,
        )
        print(json.dumps(result, indent=2))
        return 0 if result["status"] == "complete" else 1
    except (ManifestError, ValueError, OSError) as exc:
        print(f"REFUSE: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
