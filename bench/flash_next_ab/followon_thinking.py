"""Off-tree, opt-in thinking-policy sweep over the frozen six role-effort tasks.

This module does not launch models or acquire a hardware lease.  ``run_model``
requires a controller-supplied admission gate before creating an output or
issuing a call; it is intended to be invoked only inside a qualified, monitored
research window.  The CLI exposes source/count inspection only.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bench.flash_next_ab import harness
from bench.flash_next_ab.adapters import CallSpec
from bench.flash_next_ab.followon_timing import TimingRecorder
from bench.flash_next_ab.manifest import (
    REPO_ROOT,
    canonical_json,
    sha256_file,
    sha256_json,
)
from bench.flash_next_ab.transport import LocalEndpoint, complete
from bench.weekly_upgrade_effort import manifest as effort_manifest
from bench.weekly_upgrade_effort import runner as effort_runner

SOURCE_MANIFEST = REPO_ROOT / "experiments/weekly_role_effort_v1_2026-09-14.json"
SOURCE_FILES = (
    "bench/weekly_upgrade_effort/manifest.py",
    "bench/weekly_upgrade_effort/runner.py",
    "bench/weekly_upgrade_eval/structured_output.py",
    "bench/flash_next_ab/adapters.py",
    "bench/flash_next_ab/manifest.py",
    "bench/flash_next_ab/transport.py",
    "bench/flash_next_ab/harness.py",
)
PLAN_SCHEMA = "flash-thinking-role-effort-plan/v1"
RUN_SCHEMA = "flash-thinking-role-effort-run/v1"
PILOT_ID = "flash-thinking-role-effort-pilot-v1-20260915"
REPEAT_ID = "flash-thinking-role-effort-repeat-v1-20260915"
SEEDS = {PILOT_ID: (71,), REPEAT_ID: (173, 271, 419)}
ARMS = ("off", "low", "medium", "xhigh", "adaptive")
ENDPOINTS = {
    "resident_qwen": ("http://127.0.0.1:8001/v1", "qwen3.8-27b-nvfp4-mtp"),
    "flash_next": ("http://127.0.0.1:8012/v1", "qwen3.8-flash-next"),
    "flash_next_mia": ("http://127.0.0.1:8012/v1", "qwen3.8-flash-next-mia"),
}
FLASH_ENDPOINTS = frozenset(("flash_next", "flash_next_mia"))
TOTAL_TOKENS = 4096
CELL_TIMEOUT_S = 90.0
SAMPLING = {"temperature": 0.2, "top_p": 0.95, "top_k": 20}


class SweepWindowAbort(RuntimeError):
    """A closed safety reason; never serialize the underlying monitor error."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(value: Any, where: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{where} must be a lowercase SHA-256")
    return value


def _source() -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = effort_manifest.load_manifest(SOURCE_MANIFEST)
    planned = effort_manifest.plan_dict(manifest)
    source = {
        "manifest_path": str(SOURCE_MANIFEST),
        "manifest_sha256": manifest["_raw_sha256"],
        "configuration_sha256": manifest["_configuration_sha256"],
        "source_suite_id": manifest["suite_id"],
        "source_files": {
            relative: sha256_file(REPO_ROOT / relative) for relative in SOURCE_FILES
        },
        "sweep_module_sha256": sha256_file(Path(__file__)),
        "task_receipts": {
            task["id"]: {
                "role": task["role"],
                "input_sha256": planned["input_sha256"][task["id"]],
                "grader_sha256": planned["grader_sha256"][task["id"]],
            }
            for task in manifest["tasks"]
        },
    }
    return manifest, source


def policy(condition: str) -> dict[str, Any]:
    """Keep sampling fixed while changing exact Qwen template controls."""
    if condition not in ARMS[:-1]:
        raise ValueError("adaptive is a route, not one request policy")
    result = dict(SAMPLING)
    result["enable_thinking"] = condition != "off"
    if condition != "off":
        result["reasoning_effort"] = condition
    return result


def _cells(suite_id: str, source: dict[str, Any]) -> list[dict[str, Any]]:
    if suite_id not in SEEDS:
        raise ValueError(
            "suite ID must be one of the preregistered pilot/repeat cohorts"
        )
    task_ids = list(source["task_receipts"])
    cells = []
    for seed_index, seed in enumerate(SEEDS[suite_id]):
        for task_index, task_id in enumerate(task_ids):
            role = source["task_receipts"][task_id]["role"]
            rotated = (
                ARMS[(task_index + seed_index) % len(ARMS) :]
                + ARMS[: (task_index + seed_index) % len(ARMS)]
            )
            for condition in rotated:
                cells.append(
                    {
                        "cell_id": (
                            f"thinking/{suite_id}/{task_id}/{condition}/seed-{seed}"
                        ),
                        "task_id": task_id,
                        "role": role,
                        "condition": condition,
                        "seed": seed,
                        "input_sha256": source["task_receipts"][task_id][
                            "input_sha256"
                        ],
                        "grader_sha256": source["task_receipts"][task_id][
                            "grader_sha256"
                        ],
                    }
                )
    return cells


def draft(suite_id: str = PILOT_ID) -> dict[str, Any]:
    """CPU-only source plan; no runtime receipt and no execution authority."""
    _manifest, source = _source()
    cells = _cells(suite_id, source)
    per_model = len(cells)
    adaptive_candidates = sum(
        row["condition"] == "adaptive" and row["role"] != "critic" for row in cells
    )
    return {
        "schema_version": PLAN_SCHEMA,
        "suite_id": suite_id,
        "source": source,
        "declared_cells": cells,
        "policies": {condition: policy(condition) for condition in ARMS[:-1]},
        "caps": {
            "total_completion_tokens_per_cell": TOTAL_TOKENS,
            "total_wall_seconds_per_cell": CELL_TIMEOUT_S,
            "adaptive_first_noncritic_tokens": TOTAL_TOKENS // 2,
            "adaptive_first_noncritic_seconds": CELL_TIMEOUT_S / 2,
            "adaptive_max_calls": 2,
        },
        "counts": {
            "tasks": 6,
            "roles": {role: 2 for role in ("critic", "evidence", "execution")},
            "arms": len(ARMS),
            "seeds": len(SEEDS[suite_id]),
            "cells_per_model": per_model,
            "paired_cells": 2 * per_model,
            "maximum_calls_per_model": per_model + adaptive_candidates,
            "maximum_paired_calls": 2 * (per_model + adaptive_candidates),
            "cell_wall_ceiling_seconds_per_model": int(per_model * CELL_TIMEOUT_S),
        },
        "routes": None,
        "promotion_authorized": False,
        "limitations": [
            "Only two public fixtures each for critic, evidence, and execution.",
            "Repeated seeds rerun the same six tasks; they are not new tasks.",
            "Execution grades tool selection/arguments, not completed tool chains.",
            "Within-model arms isolate policy; cross-model deltas mix weights/runtime.",
        ],
    }


def freeze_plan(suite_id: str, routes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Bind the CPU source plan to separate, hash-verified runtime receipts."""
    if (not isinstance(routes, dict) or len(routes) != 2
            or "resident_qwen" not in routes
            or len(set(routes) & FLASH_ENDPOINTS) != 1
            or set(routes) - ({"resident_qwen"} | FLASH_ENDPOINTS)):
        raise ValueError("routes must contain resident Qwen and exactly one registered Flash variant")
    bound = {}
    for endpoint_name, row in routes.items():
        if not isinstance(row, dict) or set(row) != {
            "served_model",
            "artifact_sha256",
            "runtime_sha256",
            "qualification_receipt_sha256",
        }:
            raise ValueError("route identity fields differ")
        if row["served_model"] != ENDPOINTS[endpoint_name][1]:
            raise ValueError("route served model differs from fixed endpoint")
        bound[endpoint_name] = {
            key: _digest(row[key], f"{endpoint_name}.{key}")
            if key != "served_model"
            else row[key]
            for key in row
        }
        LocalEndpoint(
            endpoint_name,
            ENDPOINTS[endpoint_name][0],
            row["served_model"],
            row["artifact_sha256"],
        ).validate()
    plan = draft(suite_id)
    plan["routes"] = bound
    plan["plan_sha256"] = sha256_json(
        {k: v for k, v in plan.items() if k != "plan_sha256"}
    )
    return plan


def validate_plan(plan: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(plan, dict) or plan.get("suite_id") not in SEEDS:
        raise ValueError("thinking sweep plan is absent or unknown")
    routes = plan.get("routes")
    if not isinstance(routes, dict):
        raise TypeError("draft plan has no qualified runtime routes")
    expected = freeze_plan(plan["suite_id"], routes)
    if plan != expected:
        raise ValueError("source, policies, cohort, or runtime bindings drifted")
    return _source()


def _step(
    call,
    task: dict[str, Any],
    condition: str,
    retry: bool,
    private_response: dict[str, Any],
) -> dict[str, Any]:
    payload, protocol_failure = (
        effort_runner.protocol(call.content, task["output_schema"])
        if call.status == "returned"
        else (None, "transport")
    )
    usage = call.receipt.get("usage")
    used = usage.get("completion_tokens") if isinstance(usage, dict) else None
    has_output_channel = bool(
        call.content
        or private_response.get("reasoning_content")
        or private_response.get("tool_calls")
    )
    usage_valid = (
        type(used) is int
        and 0 <= used <= call.spec.max_tokens
        and (used != 0 or not has_output_channel)
    )
    return {
        "effort": condition,
        "seed": call.spec.seed,
        "max_tokens": call.spec.max_tokens,
        "request_timeout_s": call.receipt["timeout_s"],
        "retry": retry,
        "parent_request_id": None,
        "request_id": call.receipt.get("response_id"),
        "output_tokens": used if usage_valid else 0,
        "usage_valid": usage_valid,
        "completion": call.content,
        "protocol_failure": protocol_failure,
        "needs_review": payload.get("needs_review") if payload else None,
        "runtime_valid": call.status == "returned" and usage_valid,
        "runtime_identity": {
            "endpoint_name": call.receipt["endpoint_name"],
            "model": call.receipt.get("response_model"),
        },
        "status": call.status,
        "duration_s": call.receipt["wall_s"],
    }


def _write_json(path: Path, value: Any) -> None:
    raw = canonical_json(value) + b"\n"
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)
    os.replace(temporary, path)


def _append_jsonl(path: Path, value: Any) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "ab", closefd=False) as stream:
            stream.write(canonical_json(value) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)


def run_model(
    plan: dict[str, Any],
    *,
    endpoint_name: str,
    seed_block: int | None = None,
    output_dir: str | Path,
    runtime_budget_s: float,
    admission_gate: Callable[[dict[str, Any], str], None],
    safety_check: Callable[[], None],
    work_cutoff_s: float,
    invoke_fn: Callable[..., dict[str, Any]] = complete,
    cancel_event: Any = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Run one model serially, only inside a caller-owned safety window.

    The admission gate must verify current qualification/raw receipt and the
    exact route/active lease.  The supplied controller monitor is checked before
    output, each cell/call, after transport, and after grading.  Restoration is
    a separate post-window export gate; this module has no network launch CLI.
    """
    manifest, _source_receipt = validate_plan(plan)
    if endpoint_name not in plan["routes"]:
        raise ValueError("endpoint must belong to the exact frozen Qwen/Flash pair")
    if plan["suite_id"] == REPEAT_ID:
        if type(seed_block) is not int or seed_block not in SEEDS[REPEAT_ID]:
            raise ValueError("repeat execution requires one frozen seed block")
    elif seed_block not in (None, SEEDS[PILOT_ID][0]):
        raise ValueError("pilot execution has only seed 71")
    selected_cells = [
        cell
        for cell in plan["declared_cells"]
        if seed_block is None or cell["seed"] == seed_block
    ]
    if not selected_cells:
        raise ValueError("seed block has no declared cells")
    block_ceiling_s = len(selected_cells) * CELL_TIMEOUT_S
    if not callable(admission_gate):
        raise TypeError("a qualified window admission gate is required")
    if not callable(safety_check):
        raise TypeError("a continuously armed controller safety check is required")
    if (
        isinstance(runtime_budget_s, bool)
        or not isinstance(runtime_budget_s, (int, float))
        or not math.isfinite(runtime_budget_s)
        or runtime_budget_s != block_ceiling_s
    ):
        raise ValueError("runtime budget must cover the full frozen sweep block")
    if not callable(invoke_fn):
        raise TypeError("invoke_fn must be callable")
    if (
        isinstance(work_cutoff_s, bool)
        or not isinstance(work_cutoff_s, (int, float))
        or not math.isfinite(work_cutoff_s)
    ):
        raise ValueError("controller work cutoff must be a finite monotonic deadline")
    if cancel_event is not None and not callable(getattr(cancel_event, "is_set", None)):
        raise TypeError("cancel_event must expose is_set()")
    admission_gate(plan, endpoint_name)  # Before creating output or invoking a model.
    start = monotonic()
    if work_cutoff_s - start < runtime_budget_s:
        raise ValueError("full sweep block does not fit before restoration cutoff")
    deadline = start + runtime_budget_s

    def guarded() -> None:
        if cancel_event and cancel_event.is_set():
            raise SweepWindowAbort("cancelled")
        if monotonic() >= min(deadline, work_cutoff_s):
            raise SweepWindowAbort("work_cutoff")
        try:
            monitor_result = safety_check()
        except Exception as exc:
            raise SweepWindowAbort("monitor_check_failed") from exc
        if monitor_result is not None:
            raise SweepWindowAbort("monitor_check_contract")
        if cancel_event and cancel_event.is_set():
            raise SweepWindowAbort("cancelled")

    guarded()  # Before creating any artifact; no past restoration is consulted.
    output = harness._output_dir(output_dir)
    output.mkdir(mode=0o700, parents=True)
    output.chmod(0o700)
    run_id = (
        f"{plan['suite_id']}-{endpoint_name}-seed-{seed_block or 71}-{uuid.uuid4().hex}"
    )
    _write_json(output / "plan.json", plan)
    _write_json(
        output / "source_manifest.snapshot.json",
        {
            "source_path": str(SOURCE_MANIFEST),
            "source_sha256": plan["source"]["manifest_sha256"],
            "configuration_sha256": plan["source"]["configuration_sha256"],
        },
    )
    tasks = {task["id"]: task for task in manifest["tasks"]}
    started_at = _utc()
    outcomes = []
    timing = TimingRecorder()
    observed_invoke = timing.wrap(invoke_fn)
    evidence_ordinal = 0
    safety_abort_reason = None
    route = plan["routes"][endpoint_name]
    arm = {
        "routes": [
            {
                "role": role,
                "endpoint_name": endpoint_name,
                "served_model": route["served_model"],
                "artifact_sha256": route["artifact_sha256"],
                "runtime_sha256": route["runtime_sha256"],
                "policies": copy.deepcopy(plan["policies"]),
            }
            for role in ("critic", "evidence", "execution")
        ]
    }
    for cell in selected_cells:
        task = tasks[cell["task_id"]]
        cell_start = monotonic()
        cell_deadline = min(deadline, cell_start + CELL_TIMEOUT_S)
        calls = []
        steps = []
        private = []
        execution_error = None
        not_run_reason = None
        if safety_abort_reason is None:
            try:
                guarded()
            except SweepWindowAbort as exc:
                safety_abort_reason = exc.reason
                not_run_reason = exc.reason
        else:
            not_run_reason = safety_abort_reason

        def issue(condition: str, *, retry: bool, cap: int, timeout: float,
                  seed: int, _cell=cell, _task=task, _calls=calls,
                  _steps=steps, _private=private, _deadline=cell_deadline):
            # Bind this loop's state even though each issue is called before
            # the next cell. No retry may inherit another cell's route/task.
            nonlocal evidence_ordinal
            guarded()  # Also applies to the adaptive second call.
            spec = CallSpec(
                call_index=len(_calls),
                call_id=f"{_cell['cell_id']}#{len(_calls)}",
                role=_cell["role"],
                policy_id=condition,
                seed=seed,
                max_tokens=cap,
                timeout_s=timeout,
                required=not retry,
                messages=tuple(effort_runner.messages(_task, retry=retry)),
            )
            call = harness._invoke_call(
                spec,
                arm=arm,
                deadline=_deadline,
                invoke_fn=observed_invoke,
                cancel_event=cancel_event,
                monotonic=monotonic,
                evidence_sink=_private.append,
            )
            _calls.append(call)
            _steps.append(_step(call, _task, condition, retry,
                                _private[-1]["response"]))
            evidence = {
                **_private[-1],
                "run_id": run_id,
                "cohort": endpoint_name,
                "cell_id": _cell["cell_id"],
            }
            descriptor = harness._persist_private_call(
                output, ordinal=evidence_ordinal, evidence=evidence
            )
            evidence_ordinal += 1
            return descriptor

        descriptors = []
        first_condition = (
            "xhigh"
            if cell["condition"] == "adaptive" and cell["role"] == "critic"
            else "medium"
            if cell["condition"] == "adaptive"
            else cell["condition"]
        )
        first_is_bounded = cell["condition"] == "adaptive" and cell["role"] != "critic"
        if safety_abort_reason is not None:
            not_run_reason = safety_abort_reason
        elif monotonic() < cell_deadline - 0.05 and not (
            cancel_event and cancel_event.is_set()
        ):
            try:
                descriptors.append(
                    issue(
                        first_condition,
                        retry=False,
                        cap=TOTAL_TOKENS // 2 if first_is_bounded else TOTAL_TOKENS,
                        timeout=CELL_TIMEOUT_S / 2
                        if first_is_bounded
                        else CELL_TIMEOUT_S,
                        seed=cell["seed"],
                    )
                )
                guarded()  # The transport/evidence descriptor is already durable.
            except SweepWindowAbort as exc:
                safety_abort_reason = exc.reason
                execution_error = "SweepWindowAbort" if calls else None
                not_run_reason = exc.reason if not calls else None
            except Exception as exc:  # noqa: BLE001 - fail evidence after persistence faults
                execution_error = type(exc).__name__
                safety_abort_reason = "runner_error"
        elif cancel_event and cancel_event.is_set():
            not_run_reason = "cancelled"
        else:
            not_run_reason = "budget"
        trigger = None
        if (
            first_is_bounded
            and steps
            and execution_error is None
            and safety_abort_reason is None
        ):
            trigger = effort_runner.route(cell["role"], "adaptive", steps[0])
        escalation_not_attempted_reason = None
        if (
            trigger == "xhigh"
            and steps[0]["runtime_valid"]
            and safety_abort_reason is None
        ):
            used = steps[0]["output_tokens"]
            remaining = TOTAL_TOKENS - used
            if remaining > 0 and monotonic() < cell_deadline - 0.05:
                try:
                    descriptors.append(
                        issue(
                            "xhigh",
                            retry=True,
                            cap=remaining,
                            timeout=CELL_TIMEOUT_S,
                            seed=cell["seed"] + 1,
                        )
                    )
                    guarded()
                except SweepWindowAbort as exc:
                    safety_abort_reason = exc.reason
                    execution_error = "SweepWindowAbort"
                    escalation_not_attempted_reason = exc.reason
                except Exception as exc:  # noqa: BLE001 - never score partial retry as a win
                    execution_error = type(exc).__name__
                    escalation_not_attempted_reason = "runner_error"
                    safety_abort_reason = "runner_error"
            else:
                escalation_not_attempted_reason = "budget"
        elif trigger == "xhigh":
            # Missing/over-cap usage cannot be charged as zero to create a retry.
            escalation_not_attempted_reason = "unreliable_usage_or_identity"
        duration = max(0.0, monotonic() - cell_start)
        planned = {
            "attempt_id": cell["cell_id"],
            "task_id": cell["task_id"],
            "arm": cell["condition"],
        }
        grade = effort_runner.grade_outcome(manifest, task, planned, steps, duration)
        if safety_abort_reason is None:
            try:
                guarded()  # No later call may proceed on an unsafe graded cell.
            except SweepWindowAbort as exc:
                safety_abort_reason = exc.reason
                execution_error = "SweepWindowAbort"
        usage_complete = bool(calls) and all(step["runtime_valid"] for step in steps)
        returned_usage_valid = all(
            step["usage_valid"] for step in steps if step["status"] == "returned"
        )
        status = (
            "not_run" if not calls else "error" if execution_error else grade["status"]
        )
        passed = bool(
            grade["passed"] and status == "returned" and execution_error is None
        )
        failure_code = (
            not_run_reason
            if not calls
            else "runner_error"
            if execution_error
            else grade["failure_code"]
        )
        outcome = {
            "cell_id": cell["cell_id"],
            "task_id": cell["task_id"],
            "role": cell["role"],
            "condition": cell["condition"],
            "seed": cell["seed"],
            "endpoint_name": endpoint_name,
            "served_model": route["served_model"],
            "artifact_sha256": route["artifact_sha256"],
            "runtime_sha256": route["runtime_sha256"],
            "status": status,
            "passed": passed,
            "wall_s": duration,
            "output_tokens": grade["output_tokens"] if usage_complete else None,
            "usage_complete": usage_complete,
            "returned_usage_valid": returned_usage_valid,
            "escalated": len(calls) > 1,
            "escalation_public_trigger": trigger == "xhigh",
            "escalation_not_attempted_reason": escalation_not_attempted_reason,
            "failure_code": failure_code,
            "execution_error_type": execution_error,
            "not_run_reason": not_run_reason,
            "input_sha256": cell["input_sha256"],
            "grader_sha256": cell["grader_sha256"],
            "calls": [copy.deepcopy(call.receipt) for call in calls],
            "transport_timings": timing.for_calls([call.receipt for call in calls]),
            "private_call_evidence": descriptors,
            "grader_receipt": {
                "passed": passed,
                "failure_code": failure_code,
                "source_grade_passed_before_evidence_gate": grade["passed"],
                **{
                    key: grade[key]
                    for key in (
                        "protocol_valid",
                        "runtime_valid",
                        "step_protocol_failures",
                        "step_transport_statuses",
                        "needs_review_signals",
                    )
                },
            },
        }
        _append_jsonl(output / "outcomes.jsonl", outcome)
        outcomes.append(outcome)
    elapsed = max(0.0, monotonic() - start)
    recorded_cohort_complete = all(
        row["calls"]
        and len(row["calls"]) == len(row["private_call_evidence"])
        and row["execution_error_type"] is None
        and row["status"] != "cancelled"
        for row in outcomes
    ) and not (cancel_event and cancel_event.is_set())
    returned_usage_complete = all(row["returned_usage_valid"] for row in outcomes)
    summary = {
        condition: {
            "declared": sum(row["condition"] == condition for row in outcomes),
            "attempted": sum(
                row["condition"] == condition and bool(row["calls"]) for row in outcomes
            ),
            "passed": sum(
                row["condition"] == condition and row["passed"] for row in outcomes
            ),
            "returned": sum(
                row["condition"] == condition and row["status"] == "returned"
                for row in outcomes
            ),
            "calls": sum(
                len(row["calls"]) for row in outcomes if row["condition"] == condition
            ),
            "escalations": sum(
                row["escalated"] for row in outcomes if row["condition"] == condition
            ),
            "wall_s_including_failures": sum(
                row["wall_s"] for row in outcomes if row["condition"] == condition
            ),
            "by_role": {
                role: {
                    "declared": sum(
                        row["condition"] == condition and row["role"] == role
                        for row in outcomes
                    ),
                    "passed": sum(
                        row["condition"] == condition
                        and row["role"] == role
                        and row["passed"]
                        for row in outcomes
                    ),
                }
                for role in ("critic", "evidence", "execution")
            },
        }
        for condition in ARMS
    }
    result = {
        "schema_version": RUN_SCHEMA,
        "run_id": run_id,
        "suite_id": plan["suite_id"],
        "seed_block": seed_block or 71,
        "endpoint_name": endpoint_name,
        "status": (
            "aborted"
            if safety_abort_reason is not None or not recorded_cohort_complete
            else "evidence_incomplete"
            if not returned_usage_complete
            else "complete"
        ),
        "transport_all_returned": all(row["status"] == "returned" for row in outcomes),
        "aborted_reason": safety_abort_reason,
        "plan_sha256": plan["plan_sha256"],
        "plan": copy.deepcopy(plan),
        "qualification_receipt_sha256": route["qualification_receipt_sha256"],
        "started_at": started_at,
        "finished_at": _utc(),
        "elapsed_s": elapsed,
        "runtime_budget_s": runtime_budget_s,
        "declared_cells": len(selected_cells),
        "plan_declared_cells": len(plan["declared_cells"]),
        "outcomes": outcomes,
        "summary": summary,
        "promotion_authorized": False,
        "claim_limit": "DESCRIPTIVE_POLICY_SWEEP_NO_PROMOTION",
    }
    _write_json(output / "run.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--draft", action="store_true", required=True)
    parser.add_argument("--suite-id", choices=tuple(SEEDS), default=PILOT_ID)
    args = parser.parse_args()
    print(json.dumps(draft(args.suite_id)["counts"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
