"""Bounded, read-only view of the frozen five-pair Mia cap diagnostic."""
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
PLAN = ROOT / "mia-diversity-cap-paired-v1.plan.json"
OUTPUT = ROOT / "model-windows/qfn-ab-lab-diversity-cap-20260915-a.flash"
WINDOW = OUTPUT / "window.json"
REPLAY = ROOT / "mia-diversity-cap-paired-v1.replay.json"
CODE_ROOT = Path("/home/decross1/projects/a_bgt_rsi_worktrees/lab-diversity-cap-20260915")
PLAN_SHA = "f1250b9c1965f9be99790153f63263c4240ed88aca44fc535abb7d8130c90f45"
WINDOW_SHA = "765768788240c6f25ded459c98534aa771b06cb9b2408c33d3c0c43ea8e44287"
# Set only after the no-overwrite terminal replay is published and reviewed.
# The standalone receipt has no immutable index, so its final raw SHA is the
# score-admission anchor. Prepared/live/failed states need no receipt.
REPLAY_SHA: str | None = None
EVALUATOR_SHA = "b4144701927e6b1e012dddd5965de87e58b235b4d2e9b196e90c55404d395f98"
CONTROLLER_SHA = "f8625250b6efbf6eb188615ef653ba057b7dd2e4ae9e8f71b6dc782ccc92fff0"
VARIANT = "mia-925d7be6-mtp3-reduced47k-v2opt-v1"
CLAIM = "REUSED_FIVE_TASK_DEVELOPMENT_CAP_DIAGNOSTIC_NOT_HELDOUT"
TASKS = (
    "DIV1-GT-ASSURANCE-002", "DIV1-GT-CONDORCET-002",
    "DIV1-GT-DELEGATION-002", "DIV1-GT-COORDINATION-002",
    "DIV1-GT-COALITION-002",
)
SCHEMA = "lab-diversity-cap-ui-progress/v1"
REPLAY_SCHEMA = "lab-mia-diversity-cap-replay/v1"


def _document(path: Path, ceiling: int) -> tuple[dict, str]:
    raw = _read_path(path, maximum=ceiling, label="diversity-cap public document")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise TypeError("diversity-cap public document is not an object")
    return value, hashlib.sha256(raw).hexdigest()


def _count(value: object, limit: int) -> int:
    if type(value) is not int or not 0 <= value <= limit:
        raise ValueError("diversity-cap count exceeds registered denominator")
    return value


def _seconds(value: object) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 100_000:
        raise ValueError("diversity-cap recorded time is invalid")
    return float(value)


def _registered(plan: dict, window: dict) -> None:
    evaluator = "bench/flash_next_ab/lab_eval_diversity_cap.py"
    controller = "bench/flash_next_ab/lab_window.py"
    sources = window.get("controller_sources")
    refs = plan.get("evaluator_source_bundle")
    if (plan.get("schema_version") != "lab-mia-diversity-cap-plan/v1"
            or plan.get("suite_id") != "mia-diversity-cap384-cap1536-five-reused-task-pairs-20260915-v1"
            or plan.get("caps") != [384, 1536]
            or plan.get("cohorts") != ["flash"]
            or plan.get("generator_timeout_s") != 60.0
            or plan.get("selector_timeout_s") != 20.0
            or plan.get("declared_call_count") != 40
            or len(plan.get("declared_cells", [])) != 10
            or plan.get("claim_limit") != CLAIM
            or plan.get("promotion_authorized") is not False
            or not isinstance(refs, dict) or len(refs) != 16
            or refs.get(evaluator) != EVALUATOR_SHA
            or window.get("schema") != "lab-model-window/v1"
            or window.get("window_id") != "qfn-ab-lab-diversity-cap-20260915-a"
            or window.get("evaluation_kind") != "diversity_cap"
            or window.get("cohort") != "flash"
            or window.get("code_root") != str(CODE_ROOT)
            or window.get("output_dir") != str(OUTPUT)
            or window.get("evaluation_plan") != {"path": str(PLAN), "sha256": PLAN_SHA}
            or window.get("candidate_spec_id") != VARIANT
            or window.get("runtime_budget_s") != 2200
            or window.get("wall_s") != 4500
            or window.get("restoration_reserve_s") != 600
            or window.get("promotion_authorized") is not False
            or not isinstance(sources, dict) or len(sources) != 45
            or sources.get(controller) != {
                "path": str(CODE_ROOT / controller), "sha256": CONTROLLER_SHA}
            or sources.get(evaluator) != {
                "path": str(CODE_ROOT / evaluator), "sha256": EVALUATOR_SHA}):
        raise ValueError("cap plan/window is outside the exact registered source tuple")


def _terminal_status() -> str:
    if not (OUTPUT / "result.json").exists() and not (OUTPUT / "supervision.json").exists():
        return "prepared_unissued" if not (OUTPUT / "state.json").exists() else "execution_pending"
    try:
        result, _ = _document(OUTPUT / "result.json", 2_000_000)
        supervision, _ = _document(OUTPUT / "supervision.json", 2_000_000)
        if (result.get("window_sha256") != WINDOW_SHA
                or supervision.get("window_sha256") != WINDOW_SHA):
            return "source_unavailable"
        if (result.get("status") != "complete"
                or supervision.get("returncode") != 0
                or supervision.get("interrupted") is not None
                or supervision.get("terminated_at_cutoff") is not False
                or supervision.get("emergency_restoration") is not None):
            return "incomplete_terminal"
        return "awaiting_admission"
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return "source_unavailable"


def _cap(value: object, cap: int) -> dict:
    if not isinstance(value, dict):
        raise TypeError("cap replay row missing")
    counts = {
        key: _count(value.get(key), limit) for key, limit in {
            "condition_cells": 5, "generator_calls": 15,
            "generator_returned": 15, "generator_timeout": 15,
            "length_reasoning_only_empty": 15, "empty_visible_final": 15,
            "valid_proposals": 15, "selector_calls": 5,
            "selector_returned": 5, "selector_timeout": 5,
            "underlying_objective_success": 5, "creditable_protocol_pass": 5,
        }.items()
    }
    if (counts["condition_cells"] != 5 or counts["generator_calls"] != 15
            or counts["selector_calls"] != 5
            or counts["generator_returned"] + counts["generator_timeout"] > 15
            or counts["selector_returned"] + counts["selector_timeout"] > 5
            or counts["length_reasoning_only_empty"] > counts["empty_visible_final"]
            or counts["empty_visible_final"] > counts["generator_returned"]
            or counts["creditable_protocol_pass"] > counts["underlying_objective_success"]):
        raise ValueError("cap replay count relations differ")
    histogram = value.get("generator_finish_reason_histogram")
    if (not isinstance(histogram, dict) or len(histogram) > 8
            or any(not isinstance(key, str) or len(key) > 48 for key in histogram)
            or sum(_count(v, 15) for v in histogram.values()) != 15):
        raise ValueError("cap generator finish histogram differs")
    return {"cap_tokens": cap, **counts,
            "recorded_generator_call_wall_s": _seconds(value.get("generator_call_wall_s")),
            "recorded_selector_call_wall_s": _seconds(value.get("selector_call_wall_s"))}


def _public_summary(plan: dict, run: dict) -> tuple[dict[str, dict], dict[str, int]]:
    """Recount bounded public calls and grade numbers without private response bytes."""
    declared = plan.get("declared_cells")
    outcomes = run.get("outcomes")
    if (run.get("schema_version") != "lab-mia-diversity-cap-run/v1"
            or run.get("status") != "complete"
            or run.get("cohort") != "flash"
            or run.get("plan_raw_sha256") != PLAN_SHA
            or run.get("declared_call_count") != 40
            or run.get("issued_call_count") != 40
            or run.get("claim_limit") != CLAIM
            or run.get("promotion_authorized") is not False
            or not isinstance(declared, list) or len(declared) != 10
            or not isinstance(outcomes, list) or len(outcomes) != 10
            or [row.get("cell_id") for row in outcomes if isinstance(row, dict)] != declared):
        raise ValueError("cap public run differs from frozen ten-cell plan")
    summary = {str(cap): {key: 0 for key in (
        "generator_returned", "generator_timeout", "selector_returned",
        "selector_timeout", "valid_proposals", "underlying_objective_success",
        "creditable_protocol_pass")} for cap in (384, 1536)}
    pass_pairs: dict[str, dict[str, bool]] = {task: {} for task in TASKS}
    for row in outcomes:
        if not isinstance(row, dict):
            raise TypeError("cap public outcome is not an object")
        cell_id = row["cell_id"]
        matches = [(task, cap) for task in TASKS for cap in (384, 1536)
                   if cell_id == f"diversity-cap/{task}/cap-{cap}/seed-401"]
        if len(matches) != 1 or row.get("cohort") != "flash" or row.get("task_id") != matches[0][0]:
            raise ValueError("cap public task identity differs")
        task, cap = matches[0]
        arm = summary[str(cap)]
        calls = row.get("calls")
        if not isinstance(calls, list) or len(calls) != 4:
            raise ValueError("cap public call denominator differs")
        for i, call in enumerate(calls):
            if not isinstance(call, dict):
                raise TypeError("cap public call is not an object")
            generator = i < 3
            if (call.get("role") != ("generator" if generator else "validator")
                    or call.get("max_tokens") != (cap if generator else 128)
                    or call.get("timeout_s") != (60.0 if generator else 20.0)
                    or call.get("status") not in {"returned", "timeout", "error", "cancelled"}):
                raise ValueError("cap public call route or bound differs")
            if call["status"] in {"returned", "timeout"}:
                arm[("generator_" if generator else "selector_") +
                    call["status"]] += 1
        grade = row.get("grade")
        details = grade.get("details") if isinstance(grade, dict) else None
        existing = details.get("existing_grade") if isinstance(details, dict) else None
        if (not isinstance(existing, dict) or type(existing.get("task_success")) is not bool
                or type(row.get("passed")) is not bool
                or grade.get("passed") != row["passed"]):
            raise ValueError("cap public numeric grade differs")
        arm["valid_proposals"] += _count(existing.get("valid_count"), 3)
        arm["underlying_objective_success"] += int(existing["task_success"])
        arm["creditable_protocol_pass"] += int(row["passed"])
        pass_pairs[task][str(cap)] = row["passed"]
    if any(set(pair) != {"384", "1536"} for pair in pass_pairs.values()):
        raise ValueError("cap public five-task pair incomplete")
    pairs = {
        "cap1536_pass_cap384_fail": sum(p["1536"] and not p["384"] for p in pass_pairs.values()),
        "cap384_pass_cap1536_fail": sum(p["384"] and not p["1536"] for p in pass_pairs.values()),
        "both_pass": sum(p["384"] and p["1536"] for p in pass_pairs.values()),
        "neither_pass": sum(not p["384"] and not p["1536"] for p in pass_pairs.values()),
    }
    return summary, pairs


def _admitted(replay: dict, plan: dict) -> dict:
    if (replay.get("schema_version") != REPLAY_SCHEMA
            or replay.get("status") != "closed_window_replay_passed"
            or replay.get("window_id") != "qfn-ab-lab-diversity-cap-20260915-a"
            or replay.get("window_raw_sha256") != WINDOW_SHA
            or replay.get("plan_raw_sha256") != PLAN_SHA
            or replay.get("candidate_variant_id") != VARIANT
            or replay.get("declared_task_pairs") != 5
            or replay.get("declared_condition_cells") != 10
            or replay.get("declared_calls") != 40
            or replay.get("attempted_calls") != 40
            or replay.get("private_calls_verified") != 40
            or replay.get("private_streams_verified") != 40
            or replay.get("mismatches") != []
            or replay.get("restoration_verified") is not True
            or replay.get("supervisor_closed") is not True
            or replay.get("original_primary_scores_changed") is not False
            or replay.get("claim_limit") != CLAIM
            or replay.get("private_content_exported") is not False
            or replay.get("promotion_authorized") is not False):
        raise ValueError("cap replay admission or claim differs")
    for field, path, ceiling in (
            ("result_raw_sha256", OUTPUT / "result.json", 2_000_000),
            ("state_raw_sha256", OUTPUT / "state.json", 2_000_000),
            ("supervision_raw_sha256", OUTPUT / "supervision.json", 2_000_000),
            ("supervision_start_raw_sha256", OUTPUT / "supervision-start.json", 2_000_000),
            ("profile_canary_raw_sha256", OUTPUT / "profile-canary.json", 2_000_000),
            ("profile_canary_attempts_raw_sha256", OUTPUT / "profile-canary-attempts.json", 8_000_000),
            ("admission_ready_proof_raw_sha256", OUTPUT / "admission-ready-proof.json", 2_000_000),
            ("run_raw_sha256", OUTPUT / "evaluation/run.json", 16_000_000),
            ("memory_raw_sha256", OUTPUT / "memory.jsonl", 8_000_000)):
        raw = _read_path(path, maximum=ceiling, label="bound cap public raw")
        if replay.get(field) != hashlib.sha256(raw).hexdigest():
            raise ValueError("cap replay raw binding differs")
    result, _ = _document(OUTPUT / "result.json", 2_000_000)
    state, _ = _document(OUTPUT / "state.json", 2_000_000)
    supervisor, _ = _document(OUTPUT / "supervision.json", 2_000_000)
    restoration = result.get("restoration")
    if (result.get("schema") != "lab-model-window-result/v1"
            or result.get("window_sha256") != WINDOW_SHA
            or result.get("status") != "complete"
            or result.get("error") is not None
            or result.get("evaluation_run_sha256") != replay["run_raw_sha256"]
            or state.get("window_sha256") != WINDOW_SHA
            or state.get("phase") != "complete"
            or state.get("restoration") != restoration
            or not isinstance(restoration, dict)
            or restoration.get("status") != "verified"
            or restoration.get("errors") != []
            or restoration.get("sentinel_retained") is not False
            or supervisor.get("window_sha256") != WINDOW_SHA
            or supervisor.get("returncode") != 0
            or supervisor.get("interrupted") is not None
            or supervisor.get("terminated_at_cutoff") is not False
            or supervisor.get("emergency_restoration") is not None):
        raise ValueError("cap replay terminal restoration differs")
    caps = replay.get("by_cap")
    if not isinstance(caps, dict) or set(caps) != {"384", "1536"}:
        raise ValueError("cap replay arm inventory differs")
    shown = {str(cap): _cap(caps[str(cap)], cap) for cap in (384, 1536)}
    run, _ = _document(OUTPUT / "evaluation/run.json", 16_000_000)
    public, public_pairs = _public_summary(plan, run)
    for cap in ("384", "1536"):
        if any(shown[cap][key] != value for key, value in public[cap].items()):
            raise ValueError("cap replay counters differ from bound public run")
    pairs = replay.get("paired_task_protocol_differences")
    pair_keys = ("cap1536_pass_cap384_fail", "cap384_pass_cap1536_fail", "both_pass", "neither_pass")
    if (not isinstance(pairs, dict) or set(pairs) != set(pair_keys)
            or sum(_count(pairs[k], 5) for k in pair_keys) != 5
            or pairs != public_pairs):
        raise ValueError("five cap-pair differences differ")
    return {"caps": shown, "paired_task_protocol_differences":
            {key: pairs[key] for key in pair_keys},
            "recorded_evaluator_elapsed_s": _seconds(replay.get("recorded_evaluator_elapsed_s")),
            "source_replay": "publication_time_only"}


def project_progress(*, root: Path = ROOT) -> dict:
    """Project only exact fixed source refs; do not replay private streams per poll."""
    # `root` is a fixture seam. Production paths are literal children of ROOT.
    plan_path = root / PLAN.name
    output = root / "model-windows/qfn-ab-lab-diversity-cap-20260915-a.flash"
    window_path = output / "window.json"
    replay_path = root / REPLAY.name
    observed = datetime.now(timezone.utc).isoformat()
    entry = {"schema_version": SCHEMA, "observed_at": observed,
             "status": "source_unavailable", "window_id": "qfn-ab-lab-diversity-cap-20260915-a",
             "plan_raw_sha256": None, "window_raw_sha256": None,
             "replay_raw_sha256": None, "results": None,
             "original_primary_scores_changed": False, "private_content_exported": False,
             "promotion_authorized": False, "comparison_eligible": False}
    try:
        plan, plan_sha = _document(plan_path, 2_000_000)
        window, window_sha = _document(window_path, 2_000_000)
        if plan_sha != PLAN_SHA or window_sha != WINDOW_SHA:
            raise ValueError("registered plan/window raw differs")
        _registered(plan, window)
        entry.update(plan_raw_sha256=plan_sha, window_raw_sha256=window_sha)
        if replay_path.exists() or replay_path.is_symlink():
            if REPLAY_SHA is None:
                entry["status"] = "awaiting_admission"
                return entry
            replay, replay_sha = _document(replay_path, 256_000)
            if replay_sha != REPLAY_SHA:
                raise ValueError("cap terminal replay differs from frozen raw SHA")
            entry["replay_raw_sha256"] = replay_sha
            # Fixture substitution is intentionally limited to the fixed root.
            if root != ROOT:
                raise ValueError("fixture root cannot admit live cap scores")
            entry["results"] = _admitted(replay, plan)
            entry["status"] = "closed_replay_admitted"
        elif root == ROOT:
            entry["status"] = _terminal_status()
        else:
            entry["status"] = "prepared_unissued"
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        pass
    return entry


def register(app, *, projector: Callable[[], dict] = project_progress) -> None:
    router = APIRouter()

    @router.get("/api/lab_diversity_cap_progress")
    def lab_diversity_cap_progress():
        return projector()

    app.include_router(router)
