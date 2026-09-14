"""Summarize repeated objective-evaluator artifacts without model calls.

The summarizer consumes complete ``runner.py`` artifact directories.  It reads
only each ``run.json`` and its sibling ``manifest.snapshot.json`` and emits no
prompts, completions, tool arguments, or grader prose.  Structural uncertainty
fails closed; operationally incomplete runs remain in every denominator but
can never support a gain decision.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import uuid
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from agent_wrapper.generation_policy import resolve_generation_policy

from .manifest import (
    EvaluationManifest,
    ManifestError,
    canonical_json,
    load_manifest,
    sha256_json,
)
from .runner import RUN_SCHEMA_VERSION, InvocationResult, grade_task
from .stats import COMPLETED_STATUSES, paired_bootstrap_ci

SUMMARY_SCHEMA_VERSION = "weekly-upgrade-eval-repeats/v1"
MAX_RUN_BYTES = 32 * 1024 * 1024
VALID_OUTCOME_STATUSES = frozenset(
    {"passed", "failed", "timeout", "error", "not_run_budget"}
)
INCOMPLETE_RUN_STATUSES = frozenset({"incomplete_budget", "incomplete_transport"})
LOCKED_PILOT_MANIFESTS = {
    17: "88aacc3868dc116f30ba6c9769834886a1ec26071967f7cf8ae5d7413a5b71aa",
    29: "1a2a24131cf9a5047cb30ea6b1aee748964df4dab6d48c1c702af3dc6c62e02f",
    43: "b0e8c83c0662141880ad8c7af514b61827f1391f270a849efcbcb5483bbbb287",
}
LOCKED_PILOT_PREFIX = "weekly-qwen-effort-pilot-20260914"
LOCKED_PILOT_RUNTIME_BUDGET_S = 2_220.0
LOCKED_PILOT_TRANSPORT = "invoke_via_wrapper"
EXPECTED_HARNESS_PATHS = frozenset({
    "bench/weekly_upgrade_eval/manifest.py",
    "bench/weekly_upgrade_eval/runner.py",
    "bench/weekly_upgrade_eval/stats.py",
})
REQUIRED_RUNTIME_PROVENANCE = frozenset({
    "backend",
    "model",
    "model_version",
    "temperature",
    "top_p",
    "seed",
    "max_tokens",
    "host_metadata",
    "profile",
    "reasoning_effort",
    "sampling_extra",
    "finish_reason",
    "reasoning_chars",
})
WRAPPER_PROTOCOL_FAILURE_CODES = frozenset({
    "tool_unknown", "tool_json", "tool_schema", "tool_depth",
})
DERIVED_FAILURE_CODES = frozenset({
    "parse_failure", "tool_semantics", "incorrect_answer",
})


class RepeatValidationError(ValueError):
    """An input is structurally invalid, so no comparative metric is trusted."""

    kind = "INVALID"


@dataclass(frozen=True)
class _LoadedRun:
    path: Path
    artifact_sha256: str
    artifact: dict[str, Any]
    manifest: EvaluationManifest
    seed: int
    arms: tuple[str, str]
    task_ids: tuple[str, ...]
    families: dict[str, str]
    outcomes: dict[tuple[str, str], dict[str, Any]]
    controller_identity: bytes | None


def _invalid(message: str) -> RepeatValidationError:
    return RepeatValidationError(message)


def _strict_json(path: Path, *, maximum_bytes: int = MAX_RUN_BYTES) -> tuple[dict[str, Any], bytes]:
    try:
        size = path.stat().st_size
        if size > maximum_bytes:
            raise _invalid(f"artifact exceeds {maximum_bytes} bytes: {path}")
        raw = path.read_bytes()
    except OSError as exc:
        raise _invalid(f"cannot read {path}: {exc}") from exc
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_unique_object,
            parse_constant=lambda token: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON number {token}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise _invalid(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise _invalid(f"artifact root must be an object: {path}")
    return value, raw


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _finite_nonnegative(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _invalid(f"{where} must be a finite non-negative number")
    try:
        number = float(value)
    except OverflowError as exc:
        raise _invalid(f"{where} must be a finite non-negative number") from exc
    if not math.isfinite(number) or number < 0:
        raise _invalid(f"{where} must be a finite non-negative number")
    return number


def _sha(value: Any, where: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise _invalid(f"{where} must be lowercase SHA-256 hex")
    return value


def _mapping(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _invalid(f"{where} must be an object")
    return value


def _sequence(value: Any, where: str) -> list[Any]:
    if not isinstance(value, list):
        raise _invalid(f"{where} must be an array")
    return value


def _load_manifest_snapshot(run_path: Path, expected_sha256: str) -> EvaluationManifest:
    snapshot_path = run_path.parent / "manifest.snapshot.json"
    try:
        manifest = load_manifest(snapshot_path)
    except ManifestError as exc:
        raise _invalid(f"invalid manifest snapshot beside {run_path}: {exc}") from exc
    if manifest.raw_sha256 != expected_sha256:
        raise _invalid(f"manifest snapshot hash mismatch beside {run_path}")
    return manifest


def _arm_seed(manifest: EvaluationManifest, run_path: Path) -> int:
    seeds = {arm.seed for arm in manifest.arms}
    if len(seeds) != 1:
        raise _invalid(f"arms do not share one seed in {run_path}")
    seed = next(iter(seeds))
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise _invalid(f"repeat seed must be an integer in {run_path}")
    return seed


def _validate_hash_map(value: Any, expected: dict[str, str], where: str) -> None:
    mapping = _mapping(value, where)
    if set(mapping) != set(expected):
        raise _invalid(f"{where} task IDs do not match manifest")
    for key, expected_digest in expected.items():
        if _sha(mapping[key], f"{where}.{key}") != expected_digest:
            raise _invalid(f"{where}.{key} does not match manifest")


def _validate_harness(value: Any, run_path: Path) -> dict[str, str]:
    mapping = _mapping(value, f"{run_path}.provenance.harness_file_sha256")
    if not mapping:
        raise _invalid(f"empty harness provenance in {run_path}")
    result: dict[str, str] = {}
    for key, digest in mapping.items():
        if not isinstance(key, str) or not key:
            raise _invalid(f"invalid harness path in {run_path}")
        result[key] = _sha(digest, f"{run_path}.harness.{key}")
    if set(result) != EXPECTED_HARNESS_PATHS:
        raise _invalid(
            f"harness provenance paths differ from the objective runner in {run_path}"
        )
    return result


def _nonnegative_integer(value: Any, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _invalid(f"{where} must be a non-negative integer")
    return value


def _expected_runtime_policy(arm: Any, run_path: Path) -> dict[str, Any]:
    if arm.model is None:
        raise _invalid(f"repeat arm {arm.id!r} must freeze an explicit model in {run_path}")
    try:
        resolved = resolve_generation_policy(
            profile=arm.profile,
            backend_name=arm.backend,
            model_name=arm.model,
            seed=arm.seed,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise _invalid(f"cannot resolve frozen policy for arm {arm.id!r}: {exc}") from exc
    return {
        "backend": arm.backend,
        "model": arm.model,
        "temperature": resolved.logged_params["temperature"],
        "top_p": resolved.logged_params["top_p"],
        "seed": resolved.logged_params["seed"],
        "max_tokens": arm.max_tokens,
        "profile": arm.profile,
        "reasoning_effort": resolved.reasoning_effort,
        "sampling_extra": dict(resolved.sampling_extra),
    }


def _validate_usage(row: dict[str, Any], cell: tuple[str, str], run_path: Path) -> None:
    usage = _mapping(row.get("usage"), f"{run_path}.{cell}.usage")
    if not {"input_tokens", "output_tokens"} <= set(usage):
        raise _invalid(f"token usage is incomplete for {cell!r} in {run_path}")
    _nonnegative_integer(usage["input_tokens"], f"{run_path}.{cell}.input_tokens")
    _nonnegative_integer(usage["output_tokens"], f"{run_path}.{cell}.output_tokens")


def _validate_completed_grade(
    row: dict[str, Any], task: Any, cell: tuple[str, str], run_path: Path
) -> None:
    completion = row.get("completion")
    if not isinstance(completion, str):
        raise _invalid(f"completion must be a string for {cell!r} in {run_path}")
    tool_calls_raw = _sequence(
        row.get("tool_calls"), f"{run_path}.{cell}.tool_calls"
    )
    if any(not isinstance(call, dict) for call in tool_calls_raw):
        raise _invalid(f"tool calls must be objects for {cell!r} in {run_path}")
    failure_code = row.get("failure_code")
    known_codes = WRAPPER_PROTOCOL_FAILURE_CODES | DERIVED_FAILURE_CODES
    if failure_code is not None and failure_code not in known_codes:
        raise _invalid(f"unknown failure code for {cell!r} in {run_path}")
    if row["status"] == "passed" and failure_code is not None:
        raise _invalid(f"passed cell has a failure code for {cell!r} in {run_path}")
    if failure_code in WRAPPER_PROTOCOL_FAILURE_CODES:
        if task.mode != "tools" or row["status"] != "failed":
            raise _invalid(f"tool protocol failure is inconsistent for {cell!r} in {run_path}")
        by_name = {tool["name"]: tool for tool in task.tools}
        if failure_code == "tool_unknown":
            consistent = any(call.get("name") not in by_name for call in tool_calls_raw)
        elif failure_code == "tool_json":
            consistent = any(
                isinstance(call.get("arguments"), dict)
                and set(call["arguments"]) == {"__malformed_arguments__"}
                for call in tool_calls_raw
            )
        elif failure_code == "tool_schema":
            consistent = any(
                call.get("name") in by_name
                and isinstance(call.get("arguments"), dict)
                and bool(list(Draft202012Validator(
                    by_name[call["name"]]["parameters"]
                ).iter_errors(call["arguments"])))
                for call in tool_calls_raw
            )
        else:
            # The runner fixes max_depth=2, so exhaustion contains three
            # tool-emitting turns and therefore at least three decoded calls.
            consistent = len(tool_calls_raw) >= 3
        if not consistent:
            raise _invalid(
                f"tool protocol evidence does not support {failure_code!r} "
                f"for {cell!r} in {run_path}"
            )
        regrade_failure_code = failure_code
    else:
        regrade_failure_code = None
    result = InvocationResult(
        completion=completion,
        tool_calls=tuple(tool_calls_raw),
        failure_code=regrade_failure_code,
    )
    observed = grade_task(task, result)
    if observed.passed:
        expected_failure_code = None
    elif task.mode == "tools":
        expected_failure_code = "tool_semantics"
    else:
        try:
            parsed = json.loads(completion)
        except (json.JSONDecodeError, TypeError):
            parsed = None
        expected_failure_code = (
            "parse_failure" if not isinstance(parsed, dict) else "incorrect_answer"
        )
    if failure_code in WRAPPER_PROTOCOL_FAILURE_CODES:
        expected_failure_code = failure_code
    if failure_code != expected_failure_code:
        raise _invalid(f"derived failure code differs for {cell!r} in {run_path}")
    expected_grade = {
        "passed": observed.passed,
        "reason": observed.reason,
        "details": observed.details,
    }
    if row.get("grade") != expected_grade:
        raise _invalid(f"objective regrade differs for {cell!r} in {run_path}")


def _validate_response_telemetry(
    row: dict[str, Any], cell: tuple[str, str], run_path: Path
) -> None:
    if row["status"] not in COMPLETED_STATUSES:
        return
    telemetry = _mapping(
        row.get("response_telemetry"), f"{run_path}.{cell}.response_telemetry"
    )
    if set(telemetry) != {
        "empty_at_cap", "finish_reasons", "reasoning_chars", "reasoning_tokens"
    }:
        raise _invalid(f"response telemetry fields differ for {cell!r} in {run_path}")
    _nonnegative_integer(
        telemetry["empty_at_cap"], f"{run_path}.{cell}.empty_at_cap"
    )
    finish_reasons = _sequence(
        telemetry["finish_reasons"], f"{run_path}.{cell}.finish_reasons"
    )
    if not finish_reasons or any(
        reason is not None and not isinstance(reason, str) for reason in finish_reasons
    ):
        raise _invalid(f"invalid finish reasons for {cell!r} in {run_path}")
    if telemetry["empty_at_cap"] > len(finish_reasons):
        raise _invalid(f"empty-at-cap count exceeds response count for {cell!r} in {run_path}")
    reasoning_chars = telemetry["reasoning_chars"]
    if reasoning_chars is not None:
        _nonnegative_integer(reasoning_chars, f"{run_path}.{cell}.reasoning_chars")
    if telemetry["reasoning_tokens"] is not None:
        _nonnegative_integer(
            telemetry["reasoning_tokens"], f"{run_path}.{cell}.reasoning_tokens"
        )


def _validate_runtime(
    row: dict[str, Any], arm: Any, cell: tuple[str, str], run_path: Path
) -> None:
    runtime = _mapping(
        row.get("runtime_provenance"),
        f"{run_path}.{cell}.runtime_provenance",
    )
    runtime_digest = row.get("runtime_provenance_sha256")
    status = row["status"]
    if status in COMPLETED_STATUSES:
        missing = sorted(REQUIRED_RUNTIME_PROVENANCE - set(runtime))
        if missing:
            raise _invalid(
                f"runtime provenance is missing {missing} for {cell!r} in {run_path}"
            )
        observed_digest = _sha(runtime_digest, f"{run_path}.{cell}.runtime_sha256")
        if observed_digest != sha256_json(runtime):
            raise _invalid(f"runtime provenance hash mismatch for {cell!r}")
        expected = _expected_runtime_policy(arm, run_path)
        for key, expected_value in expected.items():
            if runtime.get(key) != expected_value:
                raise _invalid(f"observed {key} drift for {cell!r} in {run_path}")
        if not isinstance(runtime.get("model_version"), str) or not runtime["model_version"]:
            raise _invalid(f"missing model version for {cell!r} in {run_path}")
        if not isinstance(runtime.get("host_metadata"), dict) or not runtime["host_metadata"]:
            raise _invalid(f"missing host metadata for {cell!r} in {run_path}")
        finish_reason = runtime.get("finish_reason")
        if finish_reason is not None and not isinstance(finish_reason, str):
            raise _invalid(f"invalid finish reason for {cell!r} in {run_path}")
        reasoning_chars = runtime.get("reasoning_chars")
        if reasoning_chars is not None:
            _nonnegative_integer(
                reasoning_chars, f"{run_path}.{cell}.reasoning_chars"
            )
    elif runtime:
        observed_digest = _sha(runtime_digest, f"{run_path}.{cell}.runtime_sha256")
        if observed_digest != sha256_json(runtime):
            raise _invalid(f"runtime provenance hash mismatch for {cell!r}")
    elif runtime_digest is not None:
        raise _invalid(f"empty runtime provenance has a hash for {cell!r}")


def _expected_execution_cells(manifest: EvaluationManifest) -> list[tuple[str, str]]:
    cells: list[tuple[str, str]] = []
    for index, task in enumerate(manifest.tasks):
        arm_order = manifest.arms if index % 2 == 0 else tuple(reversed(manifest.arms))
        cells.extend((task.id, arm.id) for arm in arm_order)
    return cells


def _validate_execution_order(
    artifact: dict[str, Any], manifest: EvaluationManifest,
    by_cell: dict[tuple[str, str], dict[str, Any]], run_path: Path,
) -> None:
    rows = _sequence(artifact.get("execution_order"), f"{run_path}.execution_order")
    expected_all = _expected_execution_cells(manifest)
    observed_cells: list[tuple[str, str]] = []
    for position, raw in enumerate(rows, start=1):
        row = _mapping(raw, f"{run_path}.execution_order[{position - 1}]")
        if set(row) != {"execution_index", "task_id", "arm_id", "request_timeout_s"}:
            raise _invalid(f"execution-order fields differ at position {position} in {run_path}")
        if row.get("execution_index") != position:
            raise _invalid(f"execution indices are not contiguous in {run_path}")
        cell = (row.get("task_id"), row.get("arm_id"))
        if cell not in by_cell:
            raise _invalid(f"unknown execution-order cell {cell!r} in {run_path}")
        outcome = by_cell[cell]
        if outcome.get("execution_index") != position:
            raise _invalid(f"outcome execution index differs for {cell!r} in {run_path}")
        observed_timeout = _finite_nonnegative(
            row.get("request_timeout_s"),
            f"{run_path}.execution_order[{position - 1}].request_timeout_s",
        )
        if not math.isclose(
            observed_timeout, float(outcome["request_timeout_s"]), abs_tol=1e-6
        ):
            raise _invalid(f"execution deadline differs for {cell!r} in {run_path}")
        observed_cells.append(cell)
    if observed_cells != expected_all[: len(observed_cells)]:
        raise _invalid(f"execution order is not the frozen AB/BA prefix in {run_path}")
    expected_executed = [
        cell for cell in expected_all if by_cell[cell]["status"] != "not_run_budget"
    ]
    if observed_cells != expected_executed:
        raise _invalid(f"execution order does not match executed outcomes in {run_path}")
    for cell in expected_all[len(observed_cells):]:
        row = by_cell[cell]
        if row["status"] != "not_run_budget" or row.get("execution_index") is not None:
            raise _invalid(f"budget-skipped suffix is inconsistent for {cell!r} in {run_path}")


def _validate_outcomes(
    artifact: dict[str, Any], manifest: EvaluationManifest, run_path: Path
) -> tuple[dict[tuple[str, str], dict[str, Any]], dict[str, str], str]:
    task_ids = {task.id for task in manifest.tasks}
    arm_ids = {arm.id for arm in manifest.arms}
    expected_cells = {(task_id, arm_id) for task_id in task_ids for arm_id in arm_ids}
    expected_inputs = {task.id: task.input_sha256 for task in manifest.tasks}
    expected_graders = {task.id: task.grader_sha256 for task in manifest.tasks}
    families = {task.id: task.family for task in manifest.tasks}
    tasks = {task.id: task for task in manifest.tasks}
    arms = {arm.id: arm for arm in manifest.arms}
    by_cell: dict[tuple[str, str], dict[str, Any]] = {}

    for index, outcome in enumerate(_sequence(artifact.get("outcomes"), f"{run_path}.outcomes")):
        row = _mapping(outcome, f"{run_path}.outcomes[{index}]")
        cell = (row.get("task_id"), row.get("arm_id"))
        if cell not in expected_cells:
            raise _invalid(f"unexpected outcome cell {cell!r} in {run_path}")
        if cell in by_cell:
            raise _invalid(f"duplicate outcome cell {cell!r} in {run_path}")
        task_id, arm_id = cell
        if row.get("family") != families[task_id]:
            raise _invalid(f"family drift for {task_id!r} in {run_path}")
        if row.get("input_sha256") != expected_inputs[task_id]:
            raise _invalid(f"input hash drift for {task_id!r} in {run_path}")
        if row.get("grader_sha256") != expected_graders[task_id]:
            raise _invalid(f"grader hash drift for {task_id!r} in {run_path}")
        status = row.get("status")
        if status not in VALID_OUTCOME_STATUSES:
            raise _invalid(f"invalid outcome status {status!r} in {run_path}")
        grade = _mapping(row.get("grade"), f"{run_path}.{task_id}.{arm_id}.grade")
        if not isinstance(grade.get("passed"), bool):
            raise _invalid(f"non-boolean grade result for {cell!r} in {run_path}")
        if grade["passed"] != (status == "passed"):
            raise _invalid(f"grade/status contradiction for {cell!r} in {run_path}")
        duration_s = _finite_nonnegative(
            row.get("duration_s"), f"{run_path}.{task_id}.{arm_id}.duration_s"
        )
        timeout = row.get("request_timeout_s")
        if timeout is None:
            if status != "not_run_budget":
                raise _invalid(f"missing request deadline for executed cell {cell!r}")
            if duration_s != 0 or row.get("execution_index") is not None:
                raise _invalid(f"budget-skipped cell has execution data for {cell!r}")
        else:
            timeout_s = _finite_nonnegative(timeout, f"{run_path}.{task_id}.{arm_id}.deadline")
            if timeout_s <= 0 or timeout_s > arms[arm_id].request_timeout_s:
                raise _invalid(f"request deadline exceeds frozen arm for {cell!r}")
            if status in COMPLETED_STATUSES and duration_s > timeout_s + 1e-6:
                raise _invalid(f"completed cell exceeded its deadline for {cell!r}")
            execution_index = row.get("execution_index")
            if (
                isinstance(execution_index, bool)
                or not isinstance(execution_index, int)
                or execution_index <= 0
            ):
                raise _invalid(f"executed cell lacks a valid execution index for {cell!r}")
        _validate_usage(row, cell, run_path)
        if status in COMPLETED_STATUSES:
            _validate_completed_grade(row, tasks[task_id], cell, run_path)
        _validate_response_telemetry(row, cell, run_path)
        _validate_runtime(row, arms[arm_id], cell, run_path)
        by_cell[cell] = row

    missing = sorted(expected_cells - set(by_cell))
    if missing:
        raise _invalid(f"missing outcome cells in {run_path}: {missing}")

    _validate_execution_order(artifact, manifest, by_cell, run_path)

    statuses = {row["status"] for row in by_cell.values()}
    if statuses <= COMPLETED_STATUSES:
        derived_run_status = "complete"
    elif "not_run_budget" in statuses:
        derived_run_status = "incomplete_budget"
    else:
        derived_run_status = "incomplete_transport"
    if artifact.get("status") != derived_run_status:
        raise _invalid(
            f"run status {artifact.get('status')!r} contradicts outcomes in {run_path}"
        )
    return by_cell, families, derived_run_status


def _load_controller_evidence(run_path: Path, artifact_sha256: str) -> bytes | None:
    """Return the cross-repeat execution identity for a dispatcher-verified run.

    Standalone or injected runner artifacts remain useful descriptive inputs,
    but they cannot activate the locked pilot decision rule.  A partial
    controller graph is structural uncertainty and therefore invalid.
    """
    if run_path.parent.name != "evaluation":
        return None
    output = run_path.parent.parent
    names = ("trial_plan.json", "trial_result.json", "preflight.json", "postflight.json")
    paths = {name: output / name for name in names}
    present = {name for name, path in paths.items() if path.exists()}
    if not present:
        return None
    if present != set(names):
        raise _invalid(f"partial controller evidence beside {run_path}")
    if any(path.is_symlink() or not path.is_file() for path in paths.values()):
        raise _invalid(f"redirected controller evidence beside {run_path}")

    plan, _ = _strict_json(paths["trial_plan.json"])
    result, _ = _strict_json(paths["trial_result.json"])
    preflight, _ = _strict_json(paths["preflight.json"])
    postflight, _ = _strict_json(paths["postflight.json"])
    try:
        from orchestrator import weekly_upgrade_trial as controller

        receipt = controller.evaluation_receipt(plan, output)
    except Exception as exc:
        raise _invalid(f"controller could not verify {run_path}: {exc}") from exc

    if not isinstance(receipt, dict) or not isinstance(
        receipt.get("artifact_sha256"), dict
    ):
        raise _invalid(f"controller returned an invalid receipt for {run_path}")
    result_evaluation = result.get("evaluation")
    if not isinstance(result_evaluation, dict):
        raise _invalid(f"controller result lacks an evaluation receipt in {run_path}")
    result_hashes = result_evaluation.get("artifact_sha256")
    if not isinstance(result_hashes, dict):
        raise _invalid(f"controller result lacks artifact hashes in {run_path}")
    if (
        plan.get("kind") != "objective"
        or plan.get("manifest_sha256")
        != result_hashes.get("manifest.snapshot.json")
        or plan.get("production_change_authorized") is not False
    ):
        raise _invalid(f"controller plan does not bind the objective artifact in {run_path}")
    # The manifest snapshot's artifact hash is the raw registered manifest hash.
    if plan.get("manifest_sha256") != receipt["artifact_sha256"]["manifest.snapshot.json"]:
        raise _invalid(f"controller manifest receipt differs for {run_path}")
    if receipt.get("sha256") != artifact_sha256 or result_evaluation != receipt:
        raise _invalid(f"controller result does not bind the exact run artifact in {run_path}")
    # A bounded, fully receipted transport failure is usable negative evidence.
    # Keep structural failures invalid, but do not discard a timed-out planned
    # cell merely because the dispatcher correctly marked the trial failed.
    # The decision layer independently forces INCOMPLETE and supports_gain=False.
    evaluation_status = receipt.get("status")
    if evaluation_status == "complete" and receipt.get("execution_complete") is True:
        terminal_status, returncode = "completed", 0
    elif (evaluation_status in INCOMPLETE_RUN_STATUSES
          and receipt.get("execution_complete") is False):
        terminal_status, returncode = "failed", 3
    else:
        raise _invalid(f"controller receipt has no bounded terminal evaluation: {run_path}")
    if (
        result.get("status") != terminal_status
        or result.get("error") is not None
        or result.get("trial_id") != plan.get("trial_id")
        or result.get("plan_sha256") != controller._sha(plan)
        or result.get("evaluation_dir") != str(run_path.parent)
        or result.get("semantic_benefit_measured") is not False
        or result.get("production_change_authorized") is not False
        or not isinstance(result.get("process"), dict)
        or result["process"].get("returncode") != returncode
    ):
        raise _invalid(f"controller terminal result does not match its bounded evaluation: {run_path}")
    budget = result.get("budget_receipt")
    binding = controller._sha({"plan": plan, "output": str(output.resolve())})
    if (
        not isinstance(budget, dict)
        or budget.get("run_id") != plan.get("trial_id")
        or budget.get("manifest_sha256") != binding
        or budget.get("state") != "finished"
        or budget.get("status") != terminal_status
    ):
        raise _invalid(f"controller budget receipt does not bind the run in {run_path}")
    try:
        canonical_root = controller.canonical_root(controller.ROOT)
    except Exception as exc:
        raise _invalid(f"canonical controller root is unavailable for {run_path}: {exc}") from exc
    ledger_path = canonical_root / "run_state" / "weekly_upgrade_budget.jsonl"
    if ledger_path.is_symlink() or not ledger_path.is_file():
        raise _invalid(f"canonical budget ledger is absent or redirected for {run_path}")
    try:
        canonical_budget = controller.BudgetLedger(ledger_path).existing(plan["trial_id"])
    except Exception as exc:
        raise _invalid(f"canonical budget ledger could not verify {run_path}: {exc}") from exc
    if canonical_budget != budget:
        raise _invalid(f"output budget receipt differs from the canonical ledger in {run_path}")
    state_path = (
        canonical_root / "run_state" / "weekly_upgrade" / "trials"
        / f"{plan['trial_id']}.json"
    )
    if state_path.is_symlink() or not state_path.is_file():
        raise _invalid(f"canonical controller journal is absent or redirected for {run_path}")
    state, _ = _strict_json(state_path)
    if (
        state.get("phase") != "finished"
        or state.get("plan") != plan
        or state.get("output") != str(output.resolve())
        or state.get("binding_sha256") != binding
        or state.get("result") != result
    ):
        raise _invalid(f"canonical controller journal does not bind {run_path}")
    runtime_identity = preflight.get("runtime_identity")
    if (
        not isinstance(runtime_identity, list)
        or not runtime_identity
        or postflight.get("runtime_identity") != runtime_identity
    ):
        raise _invalid(f"serving runtime identity is absent or drifted in {run_path}")
    dependencies = plan.get("execution_dependencies")
    if not isinstance(dependencies, dict) or not dependencies:
        raise _invalid(f"controller plan lacks frozen execution dependencies in {run_path}")
    for name, digest in dependencies.items():
        if not isinstance(name, str) or not name:
            raise _invalid(f"controller dependency path is invalid in {run_path}")
        _sha(digest, f"{run_path}.execution_dependencies.{name}")
    return canonical_json({
        "execution_dependencies": dependencies,
        "runtime_identity": runtime_identity,
    })


def _load_run(path: Path) -> _LoadedRun:
    run_path = path.expanduser().resolve()
    artifact, raw = _strict_json(run_path)
    if artifact.get("schema_version") != RUN_SCHEMA_VERSION:
        raise _invalid(f"unsupported run schema in {run_path}")
    run_id = artifact.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise _invalid(f"missing run_id in {run_path}")
    provenance = _mapping(artifact.get("provenance"), f"{run_path}.provenance")
    manifest_sha256 = _sha(
        provenance.get("manifest_sha256"), f"{run_path}.provenance.manifest_sha256"
    )
    manifest = _load_manifest_snapshot(run_path, manifest_sha256)
    if not run_id.startswith(f"{manifest.suite_id}-"):
        raise _invalid(f"run_id does not bind to the manifest suite in {run_path}")
    if provenance.get("manifest_configuration_sha256") != manifest.configuration_sha256:
        raise _invalid(f"manifest configuration hash mismatch in {run_path}")
    expected_inputs = {task.id: task.input_sha256 for task in manifest.tasks}
    expected_graders = {task.id: task.grader_sha256 for task in manifest.tasks}
    _validate_hash_map(
        provenance.get("task_input_sha256"), expected_inputs, f"{run_path}.task_inputs"
    )
    _validate_hash_map(
        provenance.get("task_grader_sha256"), expected_graders, f"{run_path}.task_graders"
    )
    _validate_harness(provenance.get("harness_file_sha256"), run_path)
    if provenance.get("arms") != [arm.as_dict() for arm in manifest.arms]:
        raise _invalid(f"embedded arm configuration differs from manifest in {run_path}")
    if provenance.get("source_snapshot_declared") != manifest.source_snapshot:
        raise _invalid(f"source snapshot drift in {run_path}")
    run_configuration = _mapping(
        provenance.get("run_configuration"), f"{run_path}.run_configuration"
    )
    if run_configuration.get("manifest_configuration_sha256") != manifest.configuration_sha256:
        raise _invalid(f"run configuration manifest hash mismatch in {run_path}")
    if _sha(
        provenance.get("run_configuration_sha256"),
        f"{run_path}.run_configuration_sha256",
    ) != sha256_json(run_configuration):
        raise _invalid(f"run configuration hash mismatch in {run_path}")
    runtime_budget_s = _finite_nonnegative(
        run_configuration.get("runtime_budget_s"), f"{run_path}.runtime_budget_s"
    )
    if runtime_budget_s <= 0:
        raise _invalid(f"runtime budget must be positive in {run_path}")
    if (
        not isinstance(run_configuration.get("transport"), str)
        or not run_configuration["transport"]
    ):
        raise _invalid(f"missing transport identity in {run_path}")

    outcomes, families, _ = _validate_outcomes(artifact, manifest, run_path)
    elapsed_s = _finite_nonnegative(
        artifact.get("elapsed_wall_s"), f"{run_path}.elapsed_wall_s"
    )
    summed_duration = sum(float(row["duration_s"]) for row in outcomes.values())
    if summed_duration > elapsed_s + 1e-5:
        raise _invalid(f"summed task duration exceeds elapsed wall time in {run_path}")
    promotion = _mapping(artifact.get("promotion"), f"{run_path}.promotion")
    if promotion.get("authorized") is not False:
        raise _invalid(f"runner artifact unexpectedly claims promotion authority in {run_path}")
    seed = _arm_seed(manifest, run_path)
    controller_identity = _load_controller_evidence(
        run_path, hashlib.sha256(raw).hexdigest()
    )
    return _LoadedRun(
        path=run_path,
        artifact_sha256=hashlib.sha256(raw).hexdigest(),
        artifact=artifact,
        manifest=manifest,
        seed=seed,
        arms=manifest.arm_ids,
        task_ids=tuple(task.id for task in manifest.tasks),
        families=families,
        outcomes=outcomes,
        controller_identity=controller_identity,
    )


def _normalized_arm(arm: Any) -> dict[str, Any]:
    value = arm.as_dict()
    value.pop("seed")
    return value


def _suite_prefix(manifest: EvaluationManifest, seed: int) -> str:
    suffix = f"-seed{seed}"
    if not manifest.suite_id.endswith(suffix):
        raise _invalid(
            f"suite_id {manifest.suite_id!r} does not end with its seed {seed}"
        )
    return manifest.suite_id[: -len(suffix)]


def _compatibility_document(run: _LoadedRun) -> dict[str, Any]:
    config = dict(run.artifact["provenance"]["run_configuration"])
    config.pop("manifest_configuration_sha256", None)
    tasks = {
        task.id: {
            "family": task.family,
            "input_sha256": task.input_sha256,
            "grader_sha256": task.grader_sha256,
            "definition_sha256": sha256_json(task.as_dict()),
        }
        for task in run.manifest.tasks
    }
    return {
        "suite_prefix": _suite_prefix(run.manifest, run.seed),
        "description": run.manifest.description,
        "schema_version": run.manifest.schema_version,
        "bootstrap_seed": run.manifest.bootstrap_seed,
        "bootstrap_samples": run.manifest.bootstrap_samples,
        "source_snapshot": run.manifest.source_snapshot,
        "arms_without_seed": [_normalized_arm(arm) for arm in run.manifest.arms],
        "tasks": tasks,
        "harness_file_sha256": run.artifact["provenance"]["harness_file_sha256"],
        "run_configuration_without_manifest_hash": config,
    }


def _validate_compatible(
    runs: list[_LoadedRun],
) -> tuple[tuple[str, str], list[str], dict[str, str], str]:
    run_ids = [run.artifact["run_id"] for run in runs]
    if len(run_ids) != len(set(run_ids)):
        raise _invalid("duplicate run_id; an artifact cannot be counted twice")
    seeds = [run.seed for run in runs]
    if len(seeds) != len(set(seeds)):
        raise _invalid("duplicate repeat seed")
    first = runs[0]
    compatibility = _compatibility_document(first)
    for run in runs[1:]:
        if run.arms != first.arms:
            raise _invalid("arm IDs or order differ across repeats")
        if _compatibility_document(run) != compatibility:
            raise _invalid(
                "repeat configuration drift; only seed and task/execution order may differ"
            )
    identities_by_arm: dict[str, set[bytes]] = {arm: set() for arm in first.arms}
    for run in runs:
        for arm in first.arms:
            for task_id in run.task_ids:
                row = run.outcomes[(task_id, arm)]
                if row["status"] not in COMPLETED_STATUSES:
                    continue
                runtime = row["runtime_provenance"]
                identities_by_arm[arm].add(canonical_json({
                    "model_version": runtime["model_version"],
                    "host_metadata": runtime["host_metadata"],
                }))
    for arm, identities in identities_by_arm.items():
        if len(identities) > 1:
            raise _invalid(f"model/runtime environment drift for arm {arm!r} across repeats")
    declared_first, declared_second = first.manifest.arms
    if (
        declared_first.backend == declared_second.backend
        and declared_first.model == declared_second.model
        and identities_by_arm[first.arms[0]]
        and identities_by_arm[first.arms[1]]
        and identities_by_arm[first.arms[0]] != identities_by_arm[first.arms[1]]
    ):
        raise _invalid("model/runtime environment differs between matched policy arms")
    controller_identities = {
        run.controller_identity for run in runs if run.controller_identity is not None
    }
    if len(controller_identities) > 1:
        raise _invalid("controller execution dependencies or serving runtime drifted")
    task_ids = sorted(first.task_ids)
    return first.arms, task_ids, first.families, sha256_json(compatibility)


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _ctt(successes: int, wall_s: float) -> float | None:
    return round(successes / (wall_s / 3_600.0), 6) if wall_s > 0 else None


def _locked_pilot(runs: list[_LoadedRun]) -> bool:
    return (
        len(runs) == 3
        and {run.seed for run in runs} == set(LOCKED_PILOT_MANIFESTS)
        and all(
            _suite_prefix(run.manifest, run.seed) == LOCKED_PILOT_PREFIX
            and run.manifest.raw_sha256 == LOCKED_PILOT_MANIFESTS[run.seed]
            and run.artifact["provenance"]["run_configuration"].get("transport")
            == LOCKED_PILOT_TRANSPORT
            and run.artifact["provenance"]["run_configuration"].get("runtime_budget_s")
            == LOCKED_PILOT_RUNTIME_BUDGET_S
            and run.controller_identity is not None
            for run in runs
        )
    )


def _decision(
    *,
    locked_pilot: bool,
    incomplete: bool,
    arms: tuple[str, str],
    arm_metrics: dict[str, dict[str, Any]],
    rsr: dict[str, Any] | None,
    tool_failures: dict[str, int],
) -> tuple[str, bool, list[str]]:
    first, second = arms
    if incomplete:
        return "INCOMPLETE", False, [
            "At least one run contains timeout, transport, or budget-skipped work."
        ]
    if not locked_pilot or rsr is None:
        return "NOT_APPLICABLE", False, [
            (
                "The locked Qwen pilot rule requires its exact three manifests, "
                "fixed live transport/budget, and complete hash-bound controller evidence."
            )
        ]

    a_success = arm_metrics[first]["passed"]
    b_success = arm_metrics[second]["passed"]
    a_rsr = rsr["arms"][first]["solved_task_count"]
    b_rsr = rsr["arms"][second]["solved_task_count"]
    reasons: list[str] = []
    if b_success < a_success:
        reasons.append("candidate has fewer successful attempts")
    if b_rsr < a_rsr:
        reasons.append("candidate has lower RSR_2of3")
    if tool_failures[second] > tool_failures[first]:
        reasons.append("candidate has more semantic tool failures")
    if reasons:
        return "RETAIN_INCUMBENT", False, reasons

    count_gain = b_success - a_success >= 2
    a_ctt = arm_metrics[first]["correct_task_throughput_per_hour"]
    b_ctt = arm_metrics[second]["correct_task_throughput_per_hour"]
    ctt_gain = (
        a_ctt is not None
        and a_ctt > 0
        and b_ctt is not None
        and b_ctt >= 1.15 * a_ctt
    )
    if b_success >= 1 and (count_gain or ctt_gain):
        trigger = (
            "at least two additional successes"
            if count_gain
            else "CTT improved by at least 15%"
        )
        return "EVALUATE_LARGER", True, [trigger]
    return "NO_MATERIAL_SIGNAL", False, [
        "Completed results did not meet the preregistered larger-evaluation threshold."
    ]


def load_and_summarize(
    run_paths: Sequence[Path | str], *, bootstrap_samples: int | None = None
) -> dict[str, Any]:
    """Validate and aggregate repeated ``run.json`` artifacts.

    Structural errors raise :class:`RepeatValidationError`.  Operationally
    incomplete cells are retained as failures and yield an ``INCOMPLETE``
    decision with ``supports_gain=false``.
    """
    if not run_paths:
        raise _invalid("at least one run artifact is required")
    runs = [_load_run(Path(path)) for path in run_paths]
    arms, task_ids, families, compatibility_sha256 = _validate_compatible(runs)
    runs.sort(key=lambda item: item.seed)
    seeds = [run.seed for run in runs]
    samples = runs[0].manifest.bootstrap_samples if bootstrap_samples is None else bootstrap_samples
    if isinstance(samples, bool) or not isinstance(samples, int) or not 100 <= samples <= 100_000:
        raise _invalid("bootstrap_samples must be an integer in [100, 100000]")

    cells: dict[tuple[str, int, str], dict[str, Any]] = {}
    task_rows: list[dict[str, Any]] = []
    arm_statuses: dict[str, Counter[str]] = {arm: Counter() for arm in arms}
    arm_successes = {arm: 0 for arm in arms}
    arm_wall = {arm: 0.0 for arm in arms}
    arm_protocol: dict[str, dict[str, Any]] = {
        arm: {
            "failure_codes": Counter(),
            "empty_at_cap": 0,
            "finish_reasons": Counter(),
            "input_tokens": 0,
            "output_tokens": 0,
            "reasoning_chars": 0,
            "reasoning_chars_observed": 0,
            "reasoning_tokens": 0,
            "reasoning_tokens_observed": 0,
        }
        for arm in arms
    }
    family_counts: dict[str, dict[str, dict[str, Any]]] = defaultdict(
        lambda: {
            arm: {"planned": 0, "passed": 0, "wall_s": 0.0, "statuses": Counter()}
            for arm in arms
        }
    )

    for run in runs:
        for task_id in task_ids:
            for arm in arms:
                outcome = run.outcomes[(task_id, arm)]
                cells[(task_id, run.seed, arm)] = outcome
                passed = outcome["status"] == "passed"
                duration = float(outcome["duration_s"])
                arm_statuses[arm][outcome["status"]] += 1
                arm_successes[arm] += int(passed)
                arm_wall[arm] += duration
                protocol = arm_protocol[arm]
                failure_code = outcome.get("failure_code")
                if failure_code is not None:
                    protocol["failure_codes"][failure_code] += 1
                usage = outcome["usage"]
                protocol["input_tokens"] += usage["input_tokens"]
                protocol["output_tokens"] += usage["output_tokens"]
                telemetry = outcome.get("response_telemetry") or {}
                protocol["empty_at_cap"] += telemetry.get("empty_at_cap", 0)
                for reason in telemetry.get("finish_reasons", []):
                    protocol["finish_reasons"][reason or "null"] += 1
                if telemetry.get("reasoning_chars") is not None:
                    protocol["reasoning_chars"] += telemetry["reasoning_chars"]
                    protocol["reasoning_chars_observed"] += 1
                if telemetry.get("reasoning_tokens") is not None:
                    protocol["reasoning_tokens"] += telemetry["reasoning_tokens"]
                    protocol["reasoning_tokens_observed"] += 1
                family = family_counts[families[task_id]][arm]
                family["planned"] += 1
                family["passed"] += int(passed)
                family["wall_s"] += duration
                family["statuses"][outcome["status"]] += 1

    for task_id in task_ids:
        seed_rows = []
        for seed in seeds:
            arms_row = {
                arm: {
                    "status": cells[(task_id, seed, arm)]["status"],
                    "passed": cells[(task_id, seed, arm)]["status"] == "passed",
                    "failure_code": cells[(task_id, seed, arm)].get("failure_code"),
                    "duration_s": float(cells[(task_id, seed, arm)]["duration_s"]),
                    "usage": dict(cells[(task_id, seed, arm)]["usage"]),
                    "response_telemetry": dict(
                        cells[(task_id, seed, arm)].get("response_telemetry") or {}
                    ),
                    "runtime_provenance_sha256": cells[(task_id, seed, arm)].get(
                        "runtime_provenance_sha256"
                    ),
                }
                for arm in arms
            }
            seed_rows.append({"seed": seed, "arms": arms_row})
        task_rows.append({
            "task_id": task_id,
            "family": families[task_id],
            "seeds": seed_rows,
            "mean_success_delta_b_minus_a": round(
                sum(
                    int(cells[(task_id, seed, arms[1])]["status"] == "passed")
                    - int(cells[(task_id, seed, arms[0])]["status"] == "passed")
                    for seed in seeds
                )
                / len(seeds),
                6,
            ),
        })

    arm_metrics = {
        arm: {
            "planned": len(task_ids) * len(seeds),
            "passed": arm_successes[arm],
            "failure_inclusive_pass_rate": _rate(
                arm_successes[arm], len(task_ids) * len(seeds)
            ),
            "status_counts": dict(sorted(arm_statuses[arm].items())),
            "summed_arm_wall_s_including_failures": round(arm_wall[arm], 6),
            "correct_task_throughput_per_hour": _ctt(arm_successes[arm], arm_wall[arm]),
            "protocol_metrics": {
                "failure_code_counts": dict(sorted(
                    arm_protocol[arm]["failure_codes"].items()
                )),
                "parse_failures": arm_protocol[arm]["failure_codes"]["parse_failure"],
                "semantic_tool_failures": sum(
                    arm_protocol[arm]["failure_codes"][code]
                    for code in ({"tool_semantics"} | WRAPPER_PROTOCOL_FAILURE_CODES)
                ),
                "empty_at_cap": arm_protocol[arm]["empty_at_cap"],
                "finish_reason_counts": dict(sorted(
                    arm_protocol[arm]["finish_reasons"].items()
                )),
                "input_tokens": arm_protocol[arm]["input_tokens"],
                "output_tokens": arm_protocol[arm]["output_tokens"],
                "reasoning_chars": (
                    arm_protocol[arm]["reasoning_chars"]
                    if arm_protocol[arm]["reasoning_chars_observed"] else None
                ),
                "reasoning_chars_observed_cells": arm_protocol[arm][
                    "reasoning_chars_observed"
                ],
                "reasoning_tokens": (
                    arm_protocol[arm]["reasoning_tokens"]
                    if arm_protocol[arm]["reasoning_tokens_observed"] else None
                ),
                "reasoning_tokens_observed_cells": arm_protocol[arm][
                    "reasoning_tokens_observed"
                ],
            },
        }
        for arm in arms
    }
    family_metrics: dict[str, Any] = {}
    for family_name, by_arm in sorted(family_counts.items()):
        family_metrics[family_name] = {"arms": {}}
        for arm, values in by_arm.items():
            family_metrics[family_name]["arms"][arm] = {
                "planned": values["planned"],
                "passed": values["passed"],
                "failure_inclusive_pass_rate": _rate(values["passed"], values["planned"]),
                "status_counts": dict(sorted(values["statuses"].items())),
                "summed_arm_wall_s_including_failures": round(values["wall_s"], 6),
                "correct_task_throughput_per_hour": _ctt(values["passed"], values["wall_s"]),
            }

    rsr: dict[str, Any] | None = None
    if len(seeds) == 3:
        rsr = {
            "definition": "task succeeds in at least 2 of exactly 3 seeded attempts",
            "arms": {},
        }
        for arm in arms:
            per_task = {
                task_id: sum(
                    cells[(task_id, seed, arm)]["status"] == "passed" for seed in seeds
                )
                for task_id in task_ids
            }
            distribution = Counter(per_task.values())
            rsr["arms"][arm] = {
                "solved_task_count": sum(count >= 2 for count in per_task.values()),
                "at_least_one_success_task_count": sum(
                    count >= 1 for count in per_task.values()
                ),
                "all_three_success_task_count": distribution[3],
                "task_template_count": len(task_ids),
                "success_count_distribution": {
                    str(count): distribution[count] for count in range(4)
                },
                "successes_by_task": per_task,
            }

    task_deltas = [row["mean_success_delta_b_minus_a"] for row in task_rows]
    bootstrap = paired_bootstrap_ci(
        task_deltas,
        samples=samples,
        seed=runs[0].manifest.bootstrap_seed,
    )
    incomplete = any(run.artifact["status"] in INCOMPLETE_RUN_STATUSES for run in runs)
    tool_failures = {
        arm: arm_metrics[arm]["protocol_metrics"]["semantic_tool_failures"]
        for arm in arms
    }
    locked = _locked_pilot(runs)
    decision, supports_gain, decision_reasons = _decision(
        locked_pilot=locked,
        incomplete=incomplete,
        arms=arms,
        arm_metrics=arm_metrics,
        rsr=rsr,
        tool_failures=tool_failures,
    )
    all_successes = sum(arm_successes.values())
    sum_all_arm_wall = sum(arm_wall.values())

    return {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "validation_status": "INCOMPLETE" if incomplete else "VALID",
        "supports_gain": supports_gain,
        "decision": decision,
        "decision_reasons": decision_reasons,
        "decision_rule": (
            "locked_qwen_effort_pilot_2026-09-14" if locked else "not_applicable"
        ),
        "arm_ids": list(arms),
        "seeds": seeds,
        "task_template_count": len(task_ids),
        "planned_outcome_count": len(task_ids) * len(seeds) * len(arms),
        "arms": arm_metrics,
        "semantic_tool_failures": tool_failures,
        "rsr_2of3": rsr,
        "task_clustered_paired_bootstrap": bootstrap,
        "by_family": family_metrics,
        "task_by_seed": task_rows,
        "failure_inclusive_correct_task_throughput": {
            "successful_arm_tasks": all_successes,
            "summed_all_arm_wall_s": round(sum_all_arm_wall, 6),
            "successful_tasks_per_summed_arm_hour": _ctt(all_successes, sum_all_arm_wall),
        },
        "provenance": {
            "compatibility_sha256": compatibility_sha256,
            "bootstrap_samples": samples,
            "bootstrap_seed": runs[0].manifest.bootstrap_seed,
            "runs": [
                {
                    "seed": run.seed,
                    "run_id": run.artifact["run_id"],
                    "run_artifact_sha256": run.artifact_sha256,
                    "manifest_sha256": run.manifest.raw_sha256,
                    "manifest_configuration_sha256": run.manifest.configuration_sha256,
                    "run_configuration_sha256": run.artifact["provenance"][
                        "run_configuration_sha256"
                    ],
                    "controller_verified": run.controller_identity is not None,
                    "controller_identity_sha256": (
                        hashlib.sha256(run.controller_identity).hexdigest()
                        if run.controller_identity is not None else None
                    ),
                }
                for run in runs
            ],
        },
        "notice": (
            "Descriptive objective evaluation only. No result authorizes a production "
            "policy change. Raw completions and tool payloads are intentionally omitted."
        ),
    }


def _write_fresh(path: Path, value: dict[str, Any]) -> None:
    output = path.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(f"output already exists; use a fresh path: {output}")
    temporary = output.with_name(f".{output.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    payload = canonical_json(value) + b"\n"
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, output)
        except FileExistsError as exc:
            raise FileExistsError(f"output already exists; use a fresh path: {output}") from exc
        directory_fd = os.open(output.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", nargs="+", type=Path, required=True, help="run.json paths")
    parser.add_argument("--output", type=Path, help="fresh JSON summary path")
    parser.add_argument("--bootstrap-samples", type=int, help="override descriptive samples")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        summary = load_and_summarize(
            args.runs, bootstrap_samples=args.bootstrap_samples
        )
        if args.output is not None:
            _write_fresh(args.output, summary)
        else:
            sys.stdout.buffer.write(canonical_json(summary) + b"\n")
    except (RepeatValidationError, FileExistsError) as exc:
        error = {
            "schema_version": SUMMARY_SCHEMA_VERSION,
            "validation_status": "INVALID",
            "supports_gain": False,
            "error": str(exc),
        }
        sys.stderr.buffer.write(canonical_json(error) + b"\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
