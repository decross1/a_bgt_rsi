"""Run the bounded six-task public-historical repair baseline.

The model receives one scrubbed defect contract and one base file per call. It
cannot issue commands. Its only accepted output is a unified diff for the one
registered path; grading happens afterward in a networkless bubblewrap process.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .manifest import (
    DEFAULT_MANIFEST,
    REPO_ROOT,
    ManifestError,
    canonical_json,
    git_blob,
    load_manifest,
    messages_for,
    plan_dict,
    sha256_json,
    validate_manifest,
)
from .sandbox import (
    GraderResult,
    SandboxUnavailable,
    apply_candidate_patch,
    grader_receipt_sha256,
    install_grader,
    materialize_workspace,
    run_grader,
    sandbox_runtime_identity,
)

RUN_SCHEMA_VERSION = "weekly-upgrade-historical-repair-run/v1"
EXECUTION_SOURCE_FILES = tuple(
    Path(__file__).with_name(name)
    for name in ("manifest.py", "grader_assets.py", "sandbox.py", "runner.py", "receipt.py")
)
RESERVED_OUTPUT_ROOTS = tuple(
    (REPO_ROOT / name).resolve()
    for name in ("logs", "memory", "run_state", "journal", "findings")
)
InvokeFn = Callable[..., dict[str, Any]]


def _write_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(canonical_json(value) + b"\n")
    temporary.replace(path)


def _append_jsonl(path: Path, value: Any) -> None:
    with path.open("ab") as handle:
        handle.write(canonical_json(value) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())


def _output_dir(path: str | Path) -> Path:
    output = Path(path).expanduser().resolve()
    if output == REPO_ROOT or REPO_ROOT in output.parents:
        raise ValueError("output directory must be outside the repository")
    if any(output == root or root in output.parents for root in RESERVED_OUTPUT_ROOTS):
        raise ValueError("output directory cannot be under a live state root")
    if output.exists():
        raise FileExistsError("output directory already exists")
    return output


def _strict_patch_object(value: Any, expected_path: str) -> tuple[dict[str, str] | None, str | None]:
    if not isinstance(value, str):
        return None, "completion_not_text"

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = item
        return result

    try:
        parsed = json.loads(
            value, object_pairs_hook=unique,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("non-finite")),
        )
    except (json.JSONDecodeError, ValueError):
        return None, "completion_not_strict_json"
    if not isinstance(parsed, dict) or set(parsed) != {"path", "patch"}:
        return None, "completion_schema"
    if parsed.get("path") != expected_path:
        return None, "completion_path"
    if not isinstance(parsed.get("patch"), str):
        return None, "completion_patch_not_text"
    return {"path": parsed["path"], "patch": parsed["patch"]}, None


def _runtime_identity(
    record: Any, arm: dict[str, Any], task: dict[str, Any],
) -> tuple[dict[str, Any], str | None]:
    if not isinstance(record, dict):
        return {}, "wrapper_result_not_object"
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
    expected = {
        "model": arm["model"], "backend": arm["backend"], "profile": arm["profile"],
        "temperature": arm["expected_policy"]["temperature"],
        "top_p": arm["expected_policy"]["top_p"], "seed": arm["seed"],
        "reasoning_effort": arm["expected_policy"]["reasoning_effort"],
        "max_tokens": task["max_tokens"],
    }
    for key, wanted in expected.items():
        if identity.get(key) != wanted:
            return identity, f"runtime_drift_{key}"
    if not isinstance(identity["model_version"], str) or not identity["model_version"].strip():
        return identity, "runtime_model_version_missing"
    if not isinstance(identity["host_metadata"], dict):
        return identity, "runtime_host_metadata_missing"
    if identity["sampling_extra"] != {}:
        return identity, "runtime_drift_sampling_extra"
    return identity, None


def _call_kwargs(
    manifest: dict[str, Any], task: dict[str, Any], calls_log: Path, remaining_s: float,
) -> dict[str, Any]:
    arm = manifest["arm"]
    return {
        "profile": arm["profile"], "seed": arm["seed"],
        "max_tokens": task["max_tokens"],
        "request_timeout_s": min(float(task["request_timeout_s"]), remaining_s),
        "caller_tag": "weekly_upgrade.historical_repair", "parent_request_id": None,
        "log_path": str(calls_log), "backend": arm["backend"], "model": arm["model"],
    }


def _summary(outcomes: list[dict[str, Any]], elapsed_s: float) -> dict[str, Any]:
    successes = sum(row.get("creditable_success") is True for row in outcomes)
    return {
        "provenance_class": "public_historical",
        "contamination_resistant": False,
        "comparison_eligible": False,
        "comparison_reason": "single_arm_descriptive_baseline",
        "objective_cases_total": len(outcomes),
        "successful_repairs": successes,
        "success_rate": successes / len(outcomes) if outcomes else None,
        "transport_attempts_expected": 6,
        "transport_attempts_returned": sum(row.get("status") == "returned" for row in outcomes),
        "valid_patches": sum(row.get("patch_status") == "valid" for row in outcomes),
        "grader_timeouts": sum(
            isinstance(row.get("grader"), dict) and row["grader"].get("timed_out") is True
            for row in outcomes
        ),
        "elapsed_s_including_failures": elapsed_s,
        "correct_task_throughput_per_hour": (
            successes / (elapsed_s / 3600) if elapsed_s > 0 else None
        ),
    }


def run_experiment(
    manifest: dict[str, Any], *, output_dir: str | Path, runtime_budget_s: float,
    invoke: InvokeFn | None = None, monotonic: Callable[[], float] = time.monotonic,
    grader_fn: Callable[..., GraderResult] = run_grader,
) -> dict[str, Any]:
    validate_manifest({key: value for key, value in manifest.items() if not key.startswith("_")})
    if (
        isinstance(runtime_budget_s, bool) or not isinstance(runtime_budget_s, (int, float))
        or not math.isfinite(float(runtime_budget_s)) or runtime_budget_s <= 0
        or runtime_budget_s > manifest["resource_limits"]["max_total_runtime_s"]
    ):
        raise ValueError("runtime_budget_s is outside the frozen positive ceiling")
    output = _output_dir(output_dir)
    if invoke is None and os.environ.get("MOCK_LLM"):
        raise ValueError("REFUSE live historical repair run while MOCK_LLM is set")
    output.mkdir(parents=True)
    shutil.copyfile(manifest["_path"], output / "manifest.snapshot.json")

    run_id = f"weekly-historical-{uuid.uuid4()}"
    start = monotonic()
    deadline = start + float(runtime_budget_s)
    grading_elapsed = 0.0
    raw_path = output / "raw_attempts.jsonl"
    outcome_path = output / "outcomes.jsonl"
    calls_log = output / "calls.jsonl"
    outcomes: list[dict[str, Any]] = []
    plan = plan_dict(manifest)
    arm = manifest["arm"]
    execution_hashes = {
        str(path.relative_to(REPO_ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in EXECUTION_SOURCE_FILES
    }
    expected_sandbox = manifest["sandbox_runtime"]
    try:
        observed_sandbox = sandbox_runtime_identity(
            bwrap_path=expected_sandbox["bubblewrap_path"],
            python_path=expected_sandbox["python_path"],
        )
    except SandboxUnavailable:
        observed_sandbox = None
        sandbox_error = "sandbox_runtime_unavailable"
    else:
        sandbox_error = None if observed_sandbox == expected_sandbox else "sandbox_runtime_drift"

    invoke_fn = invoke
    if invoke_fn is None:
        from agent_wrapper import worker_activity, wrapper

        def isolated_call(messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]:
            previous_path = worker_activity.DEFAULT_LOG_PATH
            previous_run = wrapper.get_run_id()
            worker_activity.DEFAULT_LOG_PATH = output / "worker_activity.jsonl"
            wrapper.set_run_id(run_id)
            try:
                return wrapper.call_sync(messages, **kwargs)
            finally:
                wrapper.set_run_id(previous_run)
                worker_activity.DEFAULT_LOG_PATH = previous_path

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
            "sandbox_runtime_expected": expected_sandbox,
            "sandbox_runtime_observed": observed_sandbox,
            "sandbox_runtime_valid": sandbox_error is None,
            "sandbox_runtime_error": sandbox_error,
            "runtime_budget_s": float(runtime_budget_s),
            "grading_elapsed_s": grading_elapsed,
            "declared_attempts": len(plan["order"]),
            "attempts_recorded": len(outcomes),
            "outcomes": outcomes,
            "summary": _summary(outcomes, elapsed),
            "provenance": {
                "class": manifest["publication_class"],
                "contamination_resistant": manifest["contamination_resistant"],
                "source_proof_sha256": manifest["source_proof"]["sha256"],
                "single_arm": True,
            },
            "promotion_authorized": False,
        }
        _write_json(output / "run.json", artifact)
        return artifact

    persist("running")
    for execution_index, (planned, task) in enumerate(zip(plan["order"], manifest["tasks"], strict=True)):
        before = monotonic()
        remaining = deadline - before
        timeout = min(float(task["request_timeout_s"]), remaining) if remaining > 0 else None
        base = {
            "attempt_id": planned["attempt_id"], "execution_index": execution_index,
            "task_id": task["id"], "arm_id": arm["id"],
            "input_sha256": planned["input_sha256"], "grader_sha256": planned["grader_sha256"],
            "request_timeout_s": timeout,
        }
        base_source = git_blob(task["base"]["commit"], task["base"]["repair_path"]).decode("utf-8")
        messages = messages_for(task, base_source)
        raw = {
            **base, "status": "not_run_budget", "request_id": None, "completion": None,
            "completion_sha256": None, "completion_bytes": None,
            "completion_omitted_over_limit": False, "usage": None,
            "response_telemetry": None, "error": "runtime_budget_exhausted",
        }
        identity: dict[str, Any] | None = None
        drift: str | None = None
        if remaining > 0:
            try:
                record = invoke_fn(messages, **_call_kwargs(manifest, task, calls_log, remaining))
            except Exception as exc:  # noqa: BLE001 - every declared task remains a denominator
                raw["status"] = "timeout" if isinstance(exc, TimeoutError) or "timeout" in type(exc).__name__.lower() else "error"
                raw["error"] = type(exc).__name__
            else:
                completion = record.get("completion") if isinstance(record, dict) else None
                completion_bytes = completion.encode("utf-8") if isinstance(completion, str) else b""
                oversized = len(completion_bytes) > manifest["resource_limits"]["max_raw_completion_bytes"]
                identity, drift = _runtime_identity(record, arm, task)
                request_id = record.get("request_id") if isinstance(record, dict) else None
                if not isinstance(request_id, str) or not request_id.strip():
                    drift = drift or "runtime_request_id_missing"
                raw.update({
                    "status": "returned", "request_id": request_id,
                    "completion": None if oversized else completion,
                    "completion_sha256": hashlib.sha256(completion_bytes).hexdigest(),
                    "completion_bytes": len(completion_bytes),
                    "completion_omitted_over_limit": oversized,
                    "usage": record.get("usage") if isinstance(record, dict) else None,
                    "response_telemetry": ({
                        "finish_reason": record.get("finish_reason"),
                        "reasoning_chars": record.get("reasoning_chars"),
                    } if isinstance(record, dict) else None),
                    "error": "completion_output_limit" if oversized else None,
                })
        raw["duration_s"] = max(0.0, monotonic() - before)
        _append_jsonl(raw_path, raw)

        outcome = {
            **base, "status": raw["status"], "request_id": raw["request_id"],
            "runtime_identity": identity, "runtime_identity_valid": drift is None if identity is not None else False,
            "runtime_identity_error": drift,
            "patch_status": "not_attempted", "patch_error": None,
            "patch_sha256": None, "patch_bytes": 0, "repaired_file_sha256": None,
            "grader": None, "grader_receipt_sha256": None,
            "creditable_success": False,
        }
        if raw["status"] == "returned":
            payload, parse_error = _strict_patch_object(
                None if raw["completion_omitted_over_limit"] else raw["completion"],
                task["base"]["repair_path"],
            )
            if raw["completion_omitted_over_limit"]:
                parse_error = "completion_output_limit"
            if drift is not None:
                outcome["patch_error"] = drift
            elif parse_error is not None:
                outcome["patch_status"] = "invalid"
                outcome["patch_error"] = parse_error
            elif sandbox_error is not None:
                outcome["patch_error"] = sandbox_error
            else:
                with tempfile.TemporaryDirectory(prefix=f"weekly-historical-{task['id'].lower()}-") as raw_workspace:
                    workspace = Path(raw_workspace) / "workspace"
                    try:
                        materialize_workspace(
                            task, workspace,
                            max_archive_bytes=manifest["resource_limits"]["max_workspace_archive_bytes"],
                            max_files=manifest["resource_limits"]["max_workspace_files"],
                        )
                        patch_result = apply_candidate_patch(
                            workspace, allowed_path=task["base"]["repair_path"],
                            patch=payload["patch"],
                            max_patch_bytes=manifest["resource_limits"]["max_patch_bytes"],
                        )
                    except SandboxUnavailable:
                        patch_result = None
                        outcome["patch_error"] = "workspace_unavailable"
                    if patch_result is not None:
                        outcome.update({
                            "patch_status": "valid" if patch_result.valid else "invalid",
                            "patch_error": patch_result.code,
                            "patch_sha256": patch_result.patch_sha256,
                            "patch_bytes": patch_result.patch_bytes,
                            "repaired_file_sha256": patch_result.repaired_file_sha256,
                        })
                    if patch_result is not None and patch_result.valid:
                        grade_start: float | None = None
                        try:
                            install_grader(task, workspace)
                            grade_start = monotonic()
                            grader_timeout = min(
                                float(task["grader_timeout_s"]),
                                max(0.0, manifest["resource_limits"]["max_grading_runtime_s"] - grading_elapsed),
                                max(0.0, deadline - grade_start),
                            )
                            if grader_timeout <= 0:
                                raise SandboxUnavailable("grading budget exhausted")
                            grade = grader_fn(
                                task, workspace,
                                bwrap_path=expected_sandbox["bubblewrap_path"],
                                python_path=expected_sandbox["python_path"],
                                timeout_s=grader_timeout,
                                max_output_bytes=manifest["resource_limits"]["max_grader_output_bytes"],
                                monotonic=monotonic,
                            )
                        except SandboxUnavailable:
                            outcome["patch_error"] = "grader_unavailable"
                        else:
                            grade_dict = asdict(grade)
                            outcome["grader"] = grade_dict
                            outcome["grader_receipt_sha256"] = grader_receipt_sha256(
                                attempt_id=planned["attempt_id"],
                                input_sha256=planned["input_sha256"],
                                patch_sha256=patch_result.patch_sha256,
                                grader_sha256=planned["grader_sha256"],
                                sandbox_identity=expected_sandbox,
                                result=grade,
                            )
                            outcome["creditable_success"] = grade.passed
                        finally:
                            if grade_start is not None:
                                grading_elapsed += max(0.0, monotonic() - grade_start)

        outcome["duration_s"] = max(0.0, monotonic() - before)
        _append_jsonl(outcome_path, outcome)
        outcomes.append(outcome)
        persist("running")

    all_returned = len(outcomes) == len(plan["order"]) and all(
        row["status"] == "returned" for row in outcomes
    )
    runtime_valid = all_returned and all(row["runtime_identity_valid"] is True for row in outcomes)
    identities = {
        sha256_json({key: row["runtime_identity"].get(key) for key in ("model", "model_version", "backend", "host_metadata")})
        for row in outcomes if isinstance(row.get("runtime_identity"), dict)
    }
    runtime_valid = runtime_valid and len(identities) == 1
    grader_valid = sandbox_error is None and all(
        not (row["patch_status"] == "valid" and row.get("grader") is None)
        for row in outcomes
    )
    status = (
        "incomplete_transport" if not all_returned else
        "invalid_runtime_drift" if not runtime_valid else
        "invalid_grader" if not grader_valid else "complete"
    )
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
        result = run_experiment(
            manifest, output_dir=args.output_dir, runtime_budget_s=args.runtime_budget_s,
        )
        print(json.dumps(result, indent=2))
        return 0 if result["status"] == "complete" else 1
    except (ManifestError, ValueError, OSError) as exc:
        print(f"REFUSE: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "EXECUTION_SOURCE_FILES", "RUN_SCHEMA_VERSION", "_runtime_identity", "_strict_patch_object",
    "_summary", "main", "run_experiment",
]
