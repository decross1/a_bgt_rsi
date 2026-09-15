"""Bounded public projection of the one-shot native payoff-tool diagnostic."""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter

from .model_runtime import _read_path

ROOT = Path("/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-15/lab-eight-hour")
STUDY_ID = "qfn-followon-payoff-tool-20260915-a"
OUTPUT = ROOT / "payoff-tool-study" / STUDY_ID
PLAN = OUTPUT / "plan.json"
WINDOW = OUTPUT / "window.json"
ADMISSION = OUTPUT / "admission.json"
NONEXECUTION = OUTPUT / "not-issued.json"
CODE_ROOT = Path("/home/decross1/projects/a_bgt_rsi_worktrees/lab-payoff-tool-20260915")
PLAN_SHA = "45a29a0f04f700b5a0c62bbe531b2a0d595f555026270237666059f493878d84"
WINDOW_SHA = "e49b3f4d0872bb03f6ec35efcceab9f5b4ed784cd05608ab15f36336996d5e58"
CONTROLLER_SHA = "3d190ab4f885fdd13fbc71caf179ba602794aa2392441fcbc970ae3f0d9b14bd"
RUNNER_SHA = "c71ab99f143f8716708c2d879a0f86fa3e9be536f28e6522fd2bb7c149601956"
CALIBRATION_SHA = "88182c3475181cb2d2ccdde7e4377283ff85b9108076d67f98609db34a3a88ae"
PREREG_SHA = "6fcd8eb8b275c79fd3e35e0a53c5ee5b8c2faeeeb732f43d89063caba0834aeb"
# Freeze after the no-overwrite terminal admission is published and reviewed.
ADMISSION_SHA: str | None = None
NONEXECUTION_SHA = "95341e159bdb32c82acc3b8165e8c7025ea22391ba26a5383209cecffbaf2259"
SCHEMA = "payoff-tool-study-ui-progress/v1"
CLAIM = "native calculator invocation and arithmetic only; no strategy, theory promotion, or model promotion"
BOUND_RAW = {
    "state.json": 2_000_000, "result.json": 2_000_000,
    "supervision.json": 2_000_000, "supervision-start.json": 2_000_000,
    "supervision-reservation.json": 2_000_000, "ready-proof.json": 2_000_000,
    "monitor-arm.json": 2_000_000, "memory.jsonl": 8_000_000,
}
ABSENT_AFTER_CLOSE = (
    "supervision-reservation.json", "supervision-start.json", "supervision.json",
    "state.json", "result.json", "ready-proof.json", "monitor-arm.json",
    "memory.jsonl", "evaluation", "root-preflight.json", "admission.json",
)


def _document(path: Path, maximum: int = 2_000_000) -> tuple[dict, str]:
    raw = _read_path(path, maximum=maximum, label="payoff-tool public document")
    row = json.loads(raw)
    if not isinstance(row, dict):
        raise TypeError("payoff-tool public document is not an object")
    return row, hashlib.sha256(raw).hexdigest()


def _count(value: object, limit: int) -> int:
    if type(value) is not int or not 0 <= value <= limit:
        raise ValueError("payoff-tool public count exceeds registered denominator")
    return value


def _registered(plan: dict, window: dict, output: Path) -> None:
    sources, runner_sources = window.get("controller_sources"), plan.get("source_sha256")
    exact = {
        "bench/payoff_tool_study/controller.py": CONTROLLER_SHA,
        "bench/payoff_tool_study/runner.py": RUNNER_SHA,
        "bench/agentic_game_theory/calibration.py": CALIBRATION_SHA,
        "experiments/payoff_tool_arithmetic/PREREGISTRATION.md": PREREG_SHA,
    }
    if (plan.get("schema_version") != "payoff-tool-study-plan/v1"
            or plan.get("code_root") != str(CODE_ROOT)
            or plan.get("claim_limit") != CLAIM
            or plan.get("evaluator_budget_s") != 600.0
            or plan.get("call_timeout_s") != 25.0
            or plan.get("max_tokens") != 256
            or not isinstance(plan.get("declared_pairs"), list)
            or len(plan["declared_pairs"]) != 6
            or not isinstance(plan.get("fixtures"), list)
            or len(plan["fixtures"]) != 6
            or not isinstance(plan.get("declared_slots"), list)
            or len(plan["declared_slots"]) != 18
            or not isinstance(runner_sources, dict) or len(runner_sources) != 9
            or any(runner_sources.get(name) != sha for name, sha in exact.items()
                   if name != "bench/payoff_tool_study/controller.py")
            or plan.get("runtime_certificate", {}).get("endpoint_name") != "resident_gemma"
            or plan["runtime_certificate"].get("served_model") != "gemma-4-26b-a4b"
            or window.get("schema") != "payoff-tool-study-window/v1"
            or window.get("window_id") != STUDY_ID or window.get("cohort") != "resident"
            or window.get("code_root") != str(CODE_ROOT)
            or window.get("output_dir") != str(output)
            or window.get("plan") != {"path": str(output / "plan.json"), "sha256": PLAN_SHA}
            or window.get("runtime_certificate") != plan["runtime_certificate"]
            or window.get("wall_s") != 1500 or window.get("evaluator_s") != 600
            or window.get("worker_restoration_reserve_s") != 600
            or window.get("parent_soft_signal_s") != 1470
            or window.get("parent_emergency_restoration_s") != 300
            or window.get("comparison_eligible") is not False
            or window.get("promotion_authorized") is not False
            or window.get("trading_claim_authorized") is not False
            or not isinstance(sources, dict) or len(sources) != 45
            or any(sources.get(name) != {"path": str(CODE_ROOT / name), "sha256": sha}
                   for name, sha in exact.items())):
        raise ValueError("payoff-tool plan/window is outside registered source tuple")
    fixtures = plan["fixtures"]
    expected_pairs = [row.get("pair_id") for row in fixtures if isinstance(row, dict)]
    expected_slots = [f"{pair}/{kind}" for pair in expected_pairs
                      for kind in ("direct", "tool_first", "tool_final")]
    if (len(set(expected_pairs)) != 6 or expected_pairs != plan["declared_pairs"]
            or expected_slots != plan["declared_slots"]
            or any(row.get("arm_order") not in (["direct", "tool"], ["tool", "direct"])
                   for row in fixtures)):
        raise ValueError("payoff-tool pairs, condition order or slots differ")
    tool = plan.get("tool_spec")
    function = tool.get("function") if isinstance(tool, dict) else None
    if not isinstance(function, dict) or function.get("name") != "shared_return":
        raise ValueError("payoff-tool native function differs")


def _terminal(output: Path) -> tuple[str, dict | None, dict | None, dict | None]:
    result_path, supervisor_path = output / "result.json", output / "supervision.json"
    if not result_path.exists() and not supervisor_path.exists():
        running = (output / "state.json").exists() or (output / "supervision-start.json").exists()
        return ("execution_pending" if running else "prepared_unissued"), None, None, None
    if not result_path.exists() or not supervisor_path.exists():
        return "execution_pending", None, None, None
    result, _ = _document(result_path)
    state, _ = _document(output / "state.json")
    supervisor, _ = _document(supervisor_path)
    restoration = result.get("restoration")
    if (result.get("schema") != "lab-model-window-result/v1"
            or result.get("window_id") != STUDY_ID
            or result.get("window_sha256") != WINDOW_SHA
            or result.get("cohort") != "resident"
            or state.get("window_sha256") != WINDOW_SHA
            or state.get("restoration") != restoration
            or supervisor.get("schema") != "payoff-tool-study-supervision/v1"
            or supervisor.get("window_sha256") != WINDOW_SHA):
        raise ValueError("payoff-tool terminal raw binding differs")
    clean = (result.get("status") == "complete" and result.get("error") is None
             and isinstance(restoration, dict) and restoration.get("status") == "verified"
             and restoration.get("errors") == [] and restoration.get("sentinel_retained") is False
             and state.get("phase") == "complete"
             and supervisor.get("returncode") == 0
             and supervisor.get("interrupted") is None
             and supervisor.get("terminated_at_cutoff") is False
             and supervisor.get("emergency_restoration") is None)
    return ("awaiting_admission" if clean else "aborted_unadmitted"), result, state, supervisor


def _closed_unissued(output: Path) -> str:
    """Admit only the exact archived prelaunch refusal and continuing no-call state."""
    row, raw_sha = _document(output / "not-issued.json", 8_000)
    if (raw_sha != NONEXECUTION_SHA
            or row.get("schema") != "payoff-tool-study-nonexecution/v1"
            or row.get("window_id") != STUDY_ID
            or row.get("window_sha256") != WINDOW_SHA
            or row.get("plan_sha256") != PLAN_SHA
            or row.get("status") != "closed_unissued"
            or row.get("reason_code") != "coordinator_resource_lock_at_final_preflight"
            or row.get("final_preflight_error") != "resource is occupied: .coordinator-cron.lock"
            or row.get("latest_safe_start") != "2026-09-15T23:25:00Z"
            or row.get("post_cutoff_coordinator_absent_observed_at") != "2026-09-15T23:25:12Z"
            or row.get("scheduled_conditions") != 12
            or row.get("scheduled_slots") != 18
            or row.get("issued_model_calls") != 0
            or row.get("model_quality_result") is not None
            or row.get("production_mutation_issued") is not False
            or row.get("comparison_eligible") is not False
            or row.get("promotion_authorized") is not False
            or row.get("trading_claim_authorized") is not False
            or row.get("absent_paths_at_close") != list(ABSENT_AFTER_CLOSE)
            or any((output / name).exists() or (output / name).is_symlink()
                   for name in ABSENT_AFTER_CLOSE)):
        raise ValueError("payoff-tool closed no-call receipt or present sources differ")
    return raw_sha


def _public_counts(plan: dict, run: dict) -> dict:
    if (run.get("schema_version") != "payoff-tool-study-run/v1"
            or run.get("status") != "complete"
            or run.get("window_id") != STUDY_ID
            or run.get("plan_raw_sha256") != PLAN_SHA
            or run.get("runtime_certificate") != plan["runtime_certificate"]
            or run.get("claim_limit") != CLAIM
            or run.get("promotion_authorized") is not False
            or run.get("declared_pairs") != plan["declared_pairs"]
            or run.get("declared_slots") != plan["declared_slots"]):
        raise ValueError("payoff-tool public run identity differs")
    slots, outcomes = run.get("slots"), run.get("outcomes")
    if (not isinstance(slots, list) or len(slots) != 18
            or [row.get("slot_id") for row in slots if isinstance(row, dict)]
                != plan["declared_slots"]
            or any(row.get("status") == "not_run" for row in slots)
            or not isinstance(outcomes, list) or len(outcomes) != 12):
        raise ValueError("payoff-tool 18-slot/12-condition accounting differs")
    expected = [(f["pair_id"], arm) for f in plan["fixtures"] for arm in f["arm_order"]]
    if [(row.get("pair_id"), row.get("arm")) for row in outcomes if isinstance(row, dict)] != expected:
        raise ValueError("payoff-tool pair/condition order differs")
    by_slot = {row["slot_id"]: row for row in slots}
    direct_shape = direct_correct = tool_shape = tool_correct = parsed = executed = final_issued = skipped = 0
    issued = 0
    for row in outcomes:
        calls = row.get("calls")
        grade = row.get("grade")
        details = grade.get("details") if isinstance(grade, dict) else None
        if not isinstance(calls, list) or not isinstance(details, dict):
            raise TypeError("payoff-tool public condition is missing")
        pair = row["pair_id"]
        issued += len(calls)
        shape, correct = details.get("strict_shape"), details.get("both_correct")
        if type(shape) is not bool or type(correct) is not bool or correct and not shape:
            raise ValueError("payoff-tool strict arithmetic grade differs")
        if row["arm"] == "direct":
            if (len(calls) != 1 or by_slot[f"{pair}/direct"].get("status") != calls[0].get("status")):
                raise ValueError("payoff-tool direct slot/call differs")
            direct_shape += shape
            direct_correct += correct
        else:
            tool = details.get("tool")
            if not isinstance(tool, dict) or any(type(tool.get(key)) is not bool for key in (
                    "parsed_tool_call", "args_shape_valid", "args_correct", "tool_executed")):
                raise ValueError("payoff-tool native tool grade differs")
            if (tool["tool_executed"] and not tool["args_correct"]
                    or tool["args_correct"] and not tool["args_shape_valid"]
                    or tool["args_shape_valid"] and not tool["parsed_tool_call"]
                    or len(calls) != (2 if tool["tool_executed"] else 1)
                    or by_slot[f"{pair}/tool_first"].get("status") != calls[0].get("status")):
                raise ValueError("payoff-tool tool-first causal call differs")
            last = by_slot[f"{pair}/tool_final"]
            if tool["tool_executed"]:
                if last.get("status") != calls[1].get("status"):
                    raise ValueError("executed payoff-tool final call differs")
                final_issued += 1
            else:
                if last.get("status") != "skipped" or last.get("failure_code") != tool.get("failure_code"):
                    raise ValueError("invalid payoff-tool first call lacks causal final skip")
                skipped += 1
            parsed += tool["parsed_tool_call"]
            executed += tool["tool_executed"]
            tool_shape += shape
            tool_correct += correct
    if (issued != _count(run.get("issued_calls"), 18)
            or direct_shape > 6 or direct_correct > direct_shape
            or tool_shape > final_issued or tool_correct > tool_shape
            or final_issued + skipped != 6 or executed != final_issued):
        raise ValueError("payoff-tool public summary relations differ")
    elapsed = run.get("elapsed_s")
    if type(elapsed) not in (int, float) or not math.isfinite(elapsed) or not 0 <= elapsed <= 600:
        raise ValueError("payoff-tool evaluator elapsed time is invalid")
    return {
        "declared_pairs": 6, "declared_conditions_per_arm": 6,
        "declared_slots": 18, "issued_calls": issued,
        "direct": {"strict_shape": direct_shape, "strict_both_correct": direct_correct},
        "tool": {"native_calls_parsed": parsed, "native_calls_executed": executed,
                 "final_calls_issued": final_issued, "causal_final_skips": skipped,
                 "strict_shape": tool_shape, "strict_both_correct": tool_correct},
        "recorded_evaluator_elapsed_s": float(elapsed),
        "source_replay": "publication_time_only",
    }


def _admitted(output: Path, plan: dict, result: dict, state: dict, supervisor: dict) -> dict:
    if ADMISSION_SHA is None:
        raise ValueError("terminal admission SHA not frozen")
    admission, admission_sha = _document(output / "admission.json", 2_000_000)
    if admission_sha != ADMISSION_SHA:
        raise ValueError("terminal admission raw SHA differs")
    if (admission.get("schema") != "payoff-tool-study-completed-admission/v1"
            or admission.get("window_id") != STUDY_ID
            or admission.get("window_sha256") != WINDOW_SHA
            or admission.get("plan_sha256") != PLAN_SHA
            or admission.get("admitted") is not True
            or admission.get("comparison_eligible") is not False
            or admission.get("promotion_authorized") is not False
            or admission.get("trading_claim_authorized") is not False):
        raise ValueError("payoff-tool admission identity or claim differs")
    refs = admission.get("raw_refs")
    if not isinstance(refs, dict) or set(refs) != set(BOUND_RAW):
        raise ValueError("payoff-tool admitted raw inventory differs")
    for name, maximum in BOUND_RAW.items():
        raw = _read_path(output / name, maximum=maximum, label="admitted payoff-tool public raw")
        if refs[name] != hashlib.sha256(raw).hexdigest():
            raise ValueError("payoff-tool admitted raw bytes differ")
    run_raw = _read_path(output / "evaluation/run.json", maximum=3_000_000,
                         label="admitted payoff-tool public run")
    run_sha = hashlib.sha256(run_raw).hexdigest()
    if admission.get("pilot_run_sha256") != run_sha or result.get("evaluation_run_sha256") != run_sha:
        raise ValueError("payoff-tool terminal/public run SHA differs")
    replay = admission.get("replay")
    if (not isinstance(replay, dict) or replay.get("admitted") is not True
            or replay.get("status") != "passed"
            or replay.get("raw_sse_replay_passed") is not True
            or replay.get("grade_replay_passed") is not True
            or replay.get("run_raw_sha256") != run_sha
            or replay.get("plan_raw_sha256") != PLAN_SHA
            or replay.get("declared_pairs") != 6
            or replay.get("declared_conditions") != 12
            or replay.get("declared_slots") != 18):
        raise ValueError("payoff-tool archived private/grade replay differs")
    run = json.loads(run_raw)
    if not isinstance(run, dict):
        raise TypeError("payoff-tool public run is not an object")
    gate = run.get("controller_admission")
    if gate != {"admitted": True, "runtime_certificate": plan["runtime_certificate"],
                "window_id": STUDY_ID, "window_sha256": WINDOW_SHA,
                "ready_proof_sha256": refs["ready-proof.json"],
                "monitor_arm_sha256": refs["monitor-arm.json"]}:
        raise ValueError("payoff-tool run admission differs from bound ready proofs")
    if replay.get("issued_calls") != run.get("issued_calls"):
        raise ValueError("payoff-tool replay and public call denominator differ")
    # Terminal fields were checked in _terminal; parsed values are intentionally
    # not exported, only independently recounted public grades.
    if state.get("phase") != "complete" or supervisor.get("returncode") != 0:
        raise ValueError("payoff-tool terminal was not clean")
    return _public_counts(plan, run)


def project_progress(root: Path = ROOT) -> dict:
    """Hash-only polling; private SSE and exact grading replay at publication."""
    output = root / "payoff-tool-study" / STUDY_ID
    observed_at = datetime.now(timezone.utc).isoformat()
    entry = {
        "schema_version": SCHEMA, "observed_at": observed_at,
        "window_id": STUDY_ID, "status": "source_unavailable",
        "plan_raw_sha256": None, "window_raw_sha256": None,
        "admission_raw_sha256": None, "nonexecution_raw_sha256": None,
        "results": None,
        "private_content_exported": False, "comparison_eligible": False,
        "promotion_authorized": False, "trading_claim_authorized": False,
    }
    try:
        plan, plan_sha = _document(output / "plan.json")
        window, window_sha = _document(output / "window.json")
        if plan_sha != PLAN_SHA or window_sha != WINDOW_SHA:
            raise ValueError("payoff-tool registered plan/window raw bytes differ")
        _registered(plan, window, output)
        entry.update(plan_raw_sha256=plan_sha, window_raw_sha256=window_sha)
        if (output / "not-issued.json").exists() or (output / "not-issued.json").is_symlink():
            entry["nonexecution_raw_sha256"] = _closed_unissued(output)
            entry["status"] = "closed_unissued"
            return entry
        status, result, state, supervisor = _terminal(output)
        entry["status"] = status
        if status != "awaiting_admission":
            return entry
        if not (output / "admission.json").exists() or ADMISSION_SHA is None:
            return entry
        entry["results"] = _admitted(output, plan, result, state, supervisor)
        entry["admission_raw_sha256"] = ADMISSION_SHA
        entry["status"] = "closed_admitted"
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        entry["status"] = "source_unavailable"
        entry["results"] = None
        entry["admission_raw_sha256"] = None
        entry["nonexecution_raw_sha256"] = None
    return entry


def register(app, *, projector: Callable[[], dict] = project_progress) -> None:
    router = APIRouter()

    @router.get("/api/payoff_tool_study_progress")
    def payoff_tool_study_progress():
        return projector()

    app.include_router(router)
