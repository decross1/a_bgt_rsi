"""Bounded public projection of the registered Mia known-opponent pilot.

The prepared window is operational evidence only. Pilot counts are withheld
until the independent restored-window admission and descriptive publication
have exact raw-byte bindings.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from fractions import Fraction
from pathlib import Path

from . import model_runtime as mr

ARTIFACT_ROOT = Path(
    "/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-15/"
    "lab-eight-hour/known-opponent-utility-mia"
)
SOURCE_ROOT = Path(
    "/home/decross1/projects/a_bgt_rsi_worktrees/lab-mia-known-opponent-20260915"
)
WINDOW_ID = "qfn-followon-known-opponent-mia-lab8h-a"
WINDOW_SHA256 = "e7fe427734237b9eacef901e0ebbe9e91925ba61356acc73e6e6791879f3c951"
CONTROLLER_SHA256 = "e2b3dcaa56b856d8fe49692351005d2052a983782d4566140afb8a31e6739760"
MANIFEST_SHA256 = "cb4d4789f82c6dd424407bf911e8ed63084e6ff4ce3c75bcf00f0a51ef95b607"
GEMMA_ADMISSION_SHA256 = "824403c23c6969eeb1e2cbc11c4ec2c5222cf7ff2123cbc867427868042bcee1"
GEMMA_MANIFEST_SHA256 = "b68d84921eded4310a78b89d35d24bd6056885e051ad4dc3328b704c0ca00d89"
GEMMA_RUN_SHA256 = "70763bd0c9a685722a3d01a5412abfbed1bebcf2eb0c7707578709115521c4be"
PARENT_SHA256 = "338e86bd0a929dc3b9c445a5758481bc3f0d897728050eda30c852e29461f796"
PROFILE_ID = "mia-925d7be6-mtp3-reduced47k-v2opt-v1"
PROFILE_SHA256 = "e71d3134f407cad3c288c21f9485c27352676dbb7de647c5b567777256702a50"
PARENT_PATH = Path(
    "/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-14/"
    "qwen-flash-next-research/evaluation/followon-qualified-parents/"
    "qfn-mia-mtp3-red47k-20260915-a.json"
)
GEMMA_ADMISSION_PATH = Path(
    "/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-15/"
    "lab-eight-hour/known-opponent-utility/"
    "qfn-followon-known-opponent-lab8h-a/admission.json"
)
SCHEMA = "known-opponent-mia-ui-observation/v1"
REPORT_SOURCE_NAME = "descriptive-comparison-source.py"
REPORT_SOURCE_SHA256 = "13130d40ca08396c5a54b67cc3ffd4168e629831971325d7eae368dd656c4f34"
REPORT_SCHEMA = "known-opponent-mia-gemma-descriptive-comparison/v1"
INDEX_SCHEMA = "known-opponent-mia-gemma-comparison-index/v1"
HEX_SHA = re.compile(r"[0-9a-f]{64}\Z")


def _read(path: Path, maximum: int, label: str) -> tuple[dict, str]:
    raw = mr._read_path(path, maximum=maximum, label=label)
    return mr._strict_object(raw, label), hashlib.sha256(raw).hexdigest()


def _unavailable(status: str) -> dict:
    return {"schema_version": SCHEMA, "status": status, "window_id": WINDOW_ID,
            "window_raw_sha256": None, "matched_gemma_admission_sha256": None,
            "current_source_replay": "not_performed", "comparison_eligible": False,
            "promotion_authorized": False, "trading_claim_authorized": False,
            "private_content_exported": False, "arms": None,
            "report_raw_sha256": None, "index_raw_sha256": None,
            "report_source_sha256": None, "mia_admission_sha256": None}


def _prepared(root: Path, source_root: Path, *, window_sha256: str) -> dict | None:
    child = root / WINDOW_ID
    try:
        window, raw_sha = _read(child / "window.json", 2_000_000, "Mia study window")
        manifest, manifest_sha = _read(child / "manifest.snapshot.json", 1_000_000,
                                       "Mia pilot manifest")
        controller_raw = mr._read_path(
            source_root / "experiments/known_opponent_utility/mia_controller.py",
            maximum=160_000, label="Mia registered controller")
        parent_raw = mr._read_path(PARENT_PATH, maximum=160_000,
                                   label="Mia qualified parent")
        gemma_raw = mr._read_path(GEMMA_ADMISSION_PATH, maximum=16_384,
                                  label="matched resident pilot admission")
        if (raw_sha != window_sha256 or manifest_sha != MANIFEST_SHA256 or
                hashlib.sha256(controller_raw).hexdigest() != CONTROLLER_SHA256 or
                hashlib.sha256(parent_raw).hexdigest() != PARENT_SHA256 or
                hashlib.sha256(gemma_raw).hexdigest() != GEMMA_ADMISSION_SHA256 or
                window.get("schema") != "known-opponent-mia-study-window/v1" or
                window.get("window_id") != WINDOW_ID or
                window.get("output_dir") != str(child) or
                window.get("code_root") != str(source_root) or
                window.get("cohort") != "flash" or
                window.get("manifest") != {"path": str(child / "manifest.snapshot.json"),
                                           "sha256": MANIFEST_SHA256} or
                window.get("qualified_parent") != {
                    "path": str(PARENT_PATH),
                    "sha256": PARENT_SHA256,
                    "candidate_spec_id": PROFILE_ID,
                    "candidate_spec_sha256": PROFILE_SHA256,
                } or
                not isinstance(window.get("matched_gemma"), dict) or
                window["matched_gemma"].get("admission_path") != str(GEMMA_ADMISSION_PATH) or
                window["matched_gemma"].get("admission_sha256") != GEMMA_ADMISSION_SHA256 or
                window.get("policy") != {"enable_thinking": False, "temperature": 0.0,
                                         "top_k": 64, "top_p": 1.0} or
                window.get("wall_s") != 3000 or window.get("pilot_s") != 900 or
                window.get("restoration_reserve_s") != 600 or
                window.get("comparison_eligible") is not False or
                window.get("promotion_authorized") is not False or
                window.get("trading_claim_authorized") is not False or
                not isinstance(window.get("controller_sources"), dict) or
                window["controller_sources"].get(
                    "experiments/known_opponent_utility/mia_controller.py") != {
                    "path": str(source_root / "experiments/known_opponent_utility/mia_controller.py"),
                    "sha256": CONTROLLER_SHA256,
                } or
                manifest.get("schema") != "known-opponent-utility-response-pilot/v1" or
                manifest.get("study_id") != "known-opponent-utility-response-pilot-v1" or
                manifest.get("source_root") != str(source_root) or
                manifest.get("max_calls") != 108 or manifest.get("horizon") != 8):
            return None
        return {"window_raw_sha256": raw_sha,
                "matched_gemma_admission_sha256": GEMMA_ADMISSION_SHA256}
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, AttributeError):
        return None


def _count(value: object, maximum: int) -> bool:
    return type(value) is int and 0 <= value <= maximum


def _recorded_admission(child: Path) -> str | None:
    """Observe the archived receipt without repeating its private SSE replay."""
    try:
        admission, admission_sha = _read(child / "admission.json", 16_384,
                                         "Mia archived admission")
        result, result_sha = _read(child / "result.json", 32_768,
                                   "Mia terminal result")
        state, state_sha = _read(child / "state.json", 64_000,
                                 "Mia terminal state")
        supervision, supervision_sha = _read(child / "supervision.json", 16_384,
                                             "Mia terminal supervision")
        run, run_sha = _read(child / "evaluation/run.json", 1_000_000,
                             "Mia public pilot run")
        validation, memory = admission.get("pilot_validation"), admission.get("memory")
        if (admission.get("schema") != "known-opponent-mia-study-admission/v1" or
                admission.get("window_id") != WINDOW_ID or
                admission.get("window_sha256") != WINDOW_SHA256 or
                admission.get("matched_gemma_admission_sha256") !=
                GEMMA_ADMISSION_SHA256 or
                admission.get("qualified_parent_sha256") != PARENT_SHA256 or
                admission.get("result_sha256") != result_sha or
                admission.get("state_sha256") != state_sha or
                admission.get("supervision_sha256") != supervision_sha or
                admission.get("pilot_run_sha256") != run_sha or
                admission.get("comparison_eligible") is not False or
                admission.get("promotion_authorized") is not False or
                admission.get("trading_claim_authorized") is not False or
                not isinstance(validation, dict) or
                validation.get("schema") !=
                "known-opponent-utility-response-validation/v1" or
                validation.get("status") != "admitted_empirical_pilot" or
                validation.get("admission_eligible") is not True or
                validation.get("run_sha256") != run_sha or
                validation.get("comparison_eligible") is not False or
                validation.get("private_content_exported") is not False or
                validation.get("scientific_novelty_claimed") is not False or
                result.get("schema") != "lab-model-window-result/v1" or
                result.get("status") != "complete" or
                result.get("window_sha256") != WINDOW_SHA256 or
                result.get("error") is not None or
                not isinstance(result.get("restoration"), dict) or
                result["restoration"].get("status") != "verified" or
                result["restoration"].get("errors") != [] or
                result["restoration"].get("sentinel_retained") is not False or
                state.get("phase") != "complete" or
                state.get("window_sha256") != WINDOW_SHA256 or
                state.get("restoration") != result["restoration"] or
                supervision.get("schema") !=
                "known-opponent-mia-study-supervision/v1" or
                supervision.get("window_sha256") != WINDOW_SHA256 or
                supervision.get("returncode") != 0 or
                supervision.get("interrupted") is not None or
                supervision.get("terminated_at_cutoff") is not False or
                supervision.get("emergency_restoration") is not None or
                run.get("manifest_sha256") != validation.get("manifest_sha256") or
                run.get("scheduled_calls") != 108 or
                not isinstance(memory, dict) or
                not isinstance(memory.get("raw_sha256"), str) or
                HEX_SHA.fullmatch(memory["raw_sha256"]) is None):
            return None
        raw = mr._read_path(child / "memory.jsonl", maximum=8_000_000,
                            label="Mia archived admission memory")
        if hashlib.sha256(raw).hexdigest() != memory["raw_sha256"]:
            return None
        return admission_sha
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, AttributeError):
        return None


def _ref(value: object, path: Path, *, maximum: int = 2_000_000) -> str:
    if (not isinstance(value, dict) or set(value) != {"path", "sha256"} or
            value.get("path") != str(path) or
            not isinstance(value.get("sha256"), str) or
            HEX_SHA.fullmatch(value["sha256"]) is None):
        raise ValueError("comparison public ref is not registered")
    raw = mr._read_path(path, maximum=maximum, label="comparison archived public ref")
    sha = hashlib.sha256(raw).hexdigest()
    if sha != value["sha256"]:
        raise ValueError("comparison archived public bytes differ")
    return sha


def _expected_refs(child: Path, gemma_root: Path) -> dict[str, dict[str, Path]]:
    return {
        "gemma": {
            "admission": gemma_root / "admission.json",
            "manifest": gemma_root / "manifest.snapshot.json",
            "pilot_manifest": gemma_root / "pilot/manifest.json",
            "run": gemma_root / "pilot/run.json",
            "window": gemma_root / "window.json",
            "result": gemma_root / "result.json",
            "supervision": gemma_root / "supervision.json",
        },
        "mia": {
            "admission": child / "admission.json",
            "manifest": child / "manifest.snapshot.json",
            "pilot_manifest": child / "evaluation/manifest.json",
            "run": child / "evaluation/run.json",
            "window": child / "window.json",
            "result": child / "result.json",
            "state": child / "state.json",
            "supervision": child / "supervision.json",
            "supervision_start": child / "supervision-start.json",
            "supervision_reservation": child / "supervision-reservation.json",
            "ready_proof": child / "admission-ready-proof.json",
            "profile_canary": child / "profile-canary.json",
            "profile_canary_attempts": child / "profile-canary-attempts.json",
        },
    }


def _public_cell(task: dict, cell: dict) -> dict:
    """Reconstruct only the content-free row; no raw SSE replay in API polling."""
    if (cell.get("cell") != task.get("cell") or
            cell.get("task_sha256") != task.get("task_sha256") or
            cell.get("comprehension") not in {"passed", "failed", "unknown"} or
            not _count(cell.get("valid_prefix_actions"), 8) or
            cell.get("scheduled_actions") != 8 or
            not isinstance(cell.get("calls"), list) or
            not 1 <= len(cell["calls"]) <= 9):
        raise ValueError("comparison public cell differs from admitted task")
    prefix = cell["valid_prefix_actions"]
    invalid = cell.get("first_invalid_round")
    full = cell.get("full_episode")
    if prefix == 8:
        if invalid is not None or len(cell["calls"]) != 9 or not isinstance(full, dict):
            raise ValueError("full episode is not eight valid actions")
        regret = full.get("episode_regret")
        if not isinstance(regret, str) or len(regret) > 32:
            raise ValueError("episode regret is unavailable")
        try:
            value = Fraction(regret)
        except (ValueError, ZeroDivisionError) as exc:
            raise ValueError("episode regret is malformed") from exc
        if value < 0 or str(value) != regret:
            raise ValueError("episode regret is not canonical")
        zero: bool | None = value == 0
    else:
        if (type(invalid) is not int or invalid != prefix + 1 or
                len(cell["calls"]) != prefix + 2 or full is not None):
            raise ValueError("incomplete episode has an invented regret")
        regret, zero = None, None
    return {"arithmetic_status": cell["comprehension"],
            "valid_action_prefix": prefix, "attempted_calls": len(cell["calls"]),
            "first_invalid_round": invalid, "complete_episode": prefix == 8,
            "episode_regret": regret, "zero_regret": zero}


def _public_arm(manifest: dict, run: dict, admission: dict,
                expected_rows: list[dict], arm: str) -> dict:
    tasks, cells = manifest.get("tasks"), run.get("cells")
    validation = admission.get("pilot_validation")
    if (not isinstance(tasks, list) or not isinstance(cells, list) or
            not isinstance(validation, dict) or len(tasks) != 12 or
            len(cells) != 12 or len(expected_rows) != 12 or
            validation.get("schema") !=
            "known-opponent-utility-response-validation/v1" or
            validation.get("status") != "admitted_empirical_pilot" or
            validation.get("admission_eligible") is not True or
            validation.get("comparison_eligible") is not False or
            validation.get("private_content_exported") is not False or
            validation.get("scientific_novelty_claimed") is not False or
            validation.get("recorded_episodes") != 12):
        raise ValueError("comparison arm lacks admitted twelve-cell record")
    projected = []
    utility = {"own_payoff": {"complete": 0, "zero_regret": 0},
               "joint_payoff": {"complete": 0, "zero_regret": 0}}
    for ordinal, (task, cell, expected) in enumerate(
            zip(tasks, cells, expected_rows, strict=True)):
        if (not isinstance(task, dict) or not isinstance(cell, dict) or
                not isinstance(expected, dict) or expected.get("ordinal") != ordinal or
                expected.get("task_sha256") != task.get("task_sha256") or
                not isinstance(task.get("cell"), dict)):
            raise ValueError("comparison task order differs")
        condition = task["cell"]
        if (expected.get("mix") != condition.get("mix") or
                expected.get("objective") != condition.get("objective") or
                expected.get("seat") != condition.get("seat") or
                expected.get("neutral_rule_label") != condition.get("rule_label") or
                condition.get("objective") not in utility):
            raise ValueError("comparison game condition differs")
        numeric = _public_cell(task, cell)
        if expected.get(arm) != numeric:
            raise ValueError("comparison public row differs from run")
        projected.append(numeric)
        if numeric["complete_episode"]:
            utility[condition["objective"]]["complete"] += 1
            utility[condition["objective"]]["zero_regret"] += numeric["zero_regret"] is True
    arithmetic = sum(row["arithmetic_status"] == "passed" for row in projected)
    actions = sum(row["valid_action_prefix"] for row in projected)
    attempted = sum(row["attempted_calls"] for row in projected)
    complete = sum(row["complete_episode"] for row in projected)
    zero = sum(row["zero_regret"] is True for row in projected)
    returned = validation.get("returned_sse_verified")
    elapsed = run.get("elapsed_s")
    if (not _count(returned, 108) or returned > attempted or
            type(elapsed) not in {int, float} or not math.isfinite(elapsed) or
            not 0 <= elapsed <= 960 or
            validation.get("scheduled_action_calls") != 96 or
            validation.get("attempted_calls") != attempted or
            validation.get("comprehension_passed") != arithmetic or
            validation.get("valid_action_calls") != actions or
            validation.get("complete_episodes") != complete or
            validation.get("zero_regret_complete_episodes") != zero):
        raise ValueError("comparison producer totals differ from archived admission")
    return {"scheduled_cells": 12, "recorded_cells": 12,
            "scheduled_action_calls": 96, "attempted_calls": attempted,
            "arithmetic_passed": arithmetic, "valid_action_calls": actions,
            "complete_episodes": complete, "zero_regret_complete_episodes": zero,
            "returned_sse_verified": returned, "evaluator_elapsed_s": elapsed,
            "by_utility": utility}


def _published(child: Path, gemma_root: Path,
               *, expected_source_sha256: str | None) -> dict | None:
    """Recompute public counts from archived raws after the one-time private gate."""
    if (expected_source_sha256 is None or
            HEX_SHA.fullmatch(expected_source_sha256) is None):
        return None
    index, index_sha = _read(child / "descriptive-comparison-index.json", 100_000,
                             "Mia comparison index")
    report, report_sha = _read(child / "descriptive-comparison.json", 200_000,
                               "Mia descriptive comparison")
    source_path = child / REPORT_SOURCE_NAME
    source_ref = {"path": str(source_path), "sha256": expected_source_sha256}
    refs = report.get("raw_refs")
    if (index.get("schema") != INDEX_SCHEMA or
            report.get("schema") != REPORT_SCHEMA or
            index.get("mia_window_id") != WINDOW_ID or
            report.get("mia_window_id") != WINDOW_ID or
            index.get("report_ref") != {
                "path": str(child / "descriptive-comparison.json"),
                "sha256": report_sha} or
            index.get("source_ref") != source_ref or
            report.get("source_ref") != source_ref or
            index.get("raw_refs") != refs or
            index.get("comparison_eligible") is not False or
            index.get("private_content_exported") is not False or
            report.get("comparison_eligible") is not False or
            report.get("private_content_exported") is not False or
            report.get("scientific_novelty_claimed") is not False or
            report.get("trading_claim_authorized") is not False or
            report.get("terminal_replay") != {
                "gemma": "recorded_admission_and_raw_refs_verified",
                "mia": "current_source_terminal_gate_verified"} or
            report.get("interpretation") !=
            "descriptive_matched_fixture_adaptive_serial_trajectories"):
        raise ValueError("comparison index/report does not bind publication")
    _ref(source_ref, source_path, maximum=160_000)
    expected = _expected_refs(child, gemma_root)
    if (not isinstance(refs, dict) or set(refs) != set(expected) or
            not all(isinstance(refs[arm], dict) and set(refs[arm]) == set(paths)
                    for arm, paths in expected.items())):
        raise ValueError("comparison public raw inventory differs")
    for arm, paths in expected.items():
        for name, path in paths.items():
            _ref(refs[arm][name], path)
    gemma_admission, gemma_admission_sha = _read(
        expected["gemma"]["admission"], 16_384, "matched Gemma admission")
    mia_admission, mia_admission_sha = _read(
        expected["mia"]["admission"], 16_384, "Mia restored-window admission")
    gemma_manifest, gemma_manifest_sha = _read(
        expected["gemma"]["manifest"], 1_000_000, "matched Gemma manifest")
    mia_manifest, mia_manifest_sha = _read(
        expected["mia"]["manifest"], 1_000_000, "Mia pilot manifest")
    gemma_run, gemma_run_sha = _read(
        expected["gemma"]["run"], 1_000_000, "matched Gemma run")
    mia_run, mia_run_sha = _read(
        expected["mia"]["run"], 1_000_000, "Mia pilot run")
    mia_result, _ = _read(expected["mia"]["result"], 32_768, "Mia terminal result")
    mia_state, _ = _read(expected["mia"]["state"], 64_000, "Mia terminal state")
    mia_supervision, _ = _read(expected["mia"]["supervision"], 16_384,
                               "Mia terminal supervision")
    memory = mia_admission.get("memory")
    if (not isinstance(memory, dict) or
            not isinstance(memory.get("raw_sha256"), str) or
            HEX_SHA.fullmatch(memory["raw_sha256"]) is None or
            not _count(memory.get("samples"), 6000) or memory["samples"] == 0 or
            not _count(memory.get("evaluation_samples"), 6000) or
            memory["evaluation_samples"] == 0 or
            memory["evaluation_samples"] > memory["samples"] or
            type(memory.get("minimum_mem_available_gib")) not in {int, float} or
            not math.isfinite(memory["minimum_mem_available_gib"]) or
            memory["minimum_mem_available_gib"] < 20):
        raise ValueError("Mia admission memory summary is unbound")
    memory_raw = mr._read_path(child / "memory.jsonl", maximum=8_000_000,
                               label="Mia admitted memory history")
    if hashlib.sha256(memory_raw).hexdigest() != memory["raw_sha256"]:
        raise ValueError("Mia admitted memory bytes differ")
    if (gemma_admission_sha != GEMMA_ADMISSION_SHA256 or
            gemma_manifest_sha != GEMMA_MANIFEST_SHA256 or
            gemma_run_sha != GEMMA_RUN_SHA256 or
            mia_manifest_sha != MANIFEST_SHA256 or
            gemma_admission.get("schema") !=
            "known-opponent-resident-study-admission/v1" or
            mia_admission.get("schema") != "known-opponent-mia-study-admission/v1" or
            mia_admission.get("window_id") != WINDOW_ID or
            mia_admission.get("window_sha256") != WINDOW_SHA256 or
            mia_admission.get("matched_gemma_admission_sha256") !=
            gemma_admission_sha or
            mia_admission.get("pilot_run_sha256") != mia_run_sha or
            gemma_admission.get("pilot_run_sha256") != gemma_run_sha or
            mia_admission.get("pilot_validation", {}).get("run_sha256") != mia_run_sha or
            gemma_admission.get("pilot_validation", {}).get("run_sha256") !=
            gemma_run_sha or
            mia_admission.get("qualified_parent_sha256") != PARENT_SHA256 or
            mia_admission.get("result_sha256") != refs["mia"]["result"]["sha256"] or
            mia_admission.get("state_sha256") != refs["mia"]["state"]["sha256"] or
            mia_admission.get("supervision_sha256") !=
            refs["mia"]["supervision"]["sha256"] or
            mia_admission.get("comparison_eligible") is not False or
            mia_admission.get("promotion_authorized") is not False or
            mia_admission.get("trading_claim_authorized") is not False or
            mia_result.get("schema") != "lab-model-window-result/v1" or
            mia_result.get("status") != "complete" or
            mia_result.get("window_sha256") != WINDOW_SHA256 or
            mia_result.get("error") is not None or
            not isinstance(mia_result.get("restoration"), dict) or
            mia_result["restoration"].get("status") != "verified" or
            mia_result["restoration"].get("errors") != [] or
            mia_result["restoration"].get("sentinel_retained") is not False or
            mia_state.get("phase") != "complete" or
            mia_state.get("window_sha256") != WINDOW_SHA256 or
            mia_state.get("restoration") != mia_result["restoration"] or
            mia_supervision.get("schema") !=
            "known-opponent-mia-study-supervision/v1" or
            mia_supervision.get("window_sha256") != WINDOW_SHA256 or
            mia_supervision.get("returncode") != 0 or
            mia_supervision.get("interrupted") is not None or
            mia_supervision.get("terminated_at_cutoff") is not False or
            mia_supervision.get("emergency_restoration") is not None or
            gemma_manifest.get("manifest_sha256") !=
            gemma_run.get("manifest_sha256") or
            gemma_manifest.get("manifest_sha256") !=
            gemma_admission.get("pilot_validation", {}).get("manifest_sha256") or
            mia_manifest.get("manifest_sha256") != mia_run.get("manifest_sha256") or
            mia_manifest.get("manifest_sha256") !=
            mia_admission.get("pilot_validation", {}).get("manifest_sha256") or
            gemma_manifest_sha != refs["gemma"]["manifest"]["sha256"] or
            gemma_manifest_sha != refs["gemma"]["pilot_manifest"]["sha256"] or
            mia_manifest_sha != refs["mia"]["pilot_manifest"]["sha256"] or
            mia_run.get("scheduled_calls") != 108 or
            gemma_run.get("scheduled_calls") != 108 or
            mia_run.get("status") not in
            {"complete", "completed_schedule_with_unknown_actions"}):
        raise ValueError("comparison restored admission or manifest differs")
    matching = report.get("matching")
    if (not isinstance(matching, dict) or
            any(gemma_manifest.get(key) != mia_manifest.get(key) for key in
                ("schedule", "tasks", "policy", "seed_base", "max_tokens",
                 "per_call_timeout_s", "max_window_s", "max_calls", "horizon")) or
            matching.get("ordered_task_sha256") !=
            [task.get("task_sha256") for task in mia_manifest["tasks"]] or
            matching.get("seed_base") != 301 or matching.get("max_tokens") != 64 or
            matching.get("per_call_timeout_s") != 30.0 or
            matching.get("max_window_s") != 900 or matching.get("max_calls") != 108 or
            matching.get("horizon") != 8 or
            matching.get("fixed_game_conditions_matched") is not True or
            matching.get("adaptive_histories_and_later_call_seeds_may_differ") is not True):
        raise ValueError("comparison fixed game conditions are not matched")
    for key, value in (("task_panel_sha256", mia_manifest["tasks"]),
                       ("schedule_sha256", mia_manifest["schedule"]),
                       ("policy_sha256", mia_manifest["policy"])):
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         allow_nan=False).encode()
        if matching.get(key) != hashlib.sha256(raw).hexdigest():
            raise ValueError("comparison matched task hash differs")
    rows, arms = report.get("per_cell"), report.get("arms")
    if (not isinstance(rows, list) or len(rows) != 12 or
            not isinstance(arms, dict) or set(arms) != {"gemma", "mia"} or
            not all(isinstance(row, dict) for row in rows)):
        raise ValueError("comparison per-cell or arm inventory differs")
    summaries = {}
    for arm, manifest, run, admission in (
            ("gemma", gemma_manifest, gemma_run, gemma_admission),
            ("mia", mia_manifest, mia_run, mia_admission)):
        rebuilt = _public_arm(manifest, run, admission, rows, arm)
        reported = arms[arm]
        if (not isinstance(reported, dict) or
                any(reported.get(key) != value for key, value in rebuilt.items()
                    if key != "by_utility")):
            raise ValueError("comparison reported arm counts differ from raw run")
        summaries[arm] = rebuilt
    return {"schema_version": SCHEMA, "status": "admitted_descriptive",
            "window_id": WINDOW_ID, "window_raw_sha256": WINDOW_SHA256,
            "matched_gemma_admission_sha256": gemma_admission_sha,
            "mia_admission_sha256": mia_admission_sha,
            "report_raw_sha256": report_sha, "index_raw_sha256": index_sha,
            "report_source_sha256": expected_source_sha256,
            "current_source_replay": "not_performed",
            "comparison_eligible": False, "promotion_authorized": False,
            "trading_claim_authorized": False, "private_content_exported": False,
            "arms": summaries}


def project_mia_pilot(*, root: Path = ARTIFACT_ROOT,
                      source_root: Path = SOURCE_ROOT,
                      expected_window_sha256: str = WINDOW_SHA256,
                      gemma_root: Path = GEMMA_ADMISSION_PATH.parent,
                      expected_report_source_sha256: str | None = REPORT_SOURCE_SHA256) -> dict:
    """Expose preparation distinctly from eventual admitted descriptive counts."""
    child = root / WINDOW_ID
    if not (child / "window.json").exists():
        return _unavailable("not_prepared")
    prepared = _prepared(root, source_root, window_sha256=expected_window_sha256)
    if prepared is None:
        return _unavailable("source_unavailable")
    if not (child / "descriptive-comparison-index.json").exists():
        if (child / "admission.json").exists():
            admission_sha = _recorded_admission(child)
            if admission_sha is None:
                return _unavailable("source_unavailable")
            return {**_unavailable("recorded_admission_report_pending"),
                    **prepared, "mia_admission_sha256": admission_sha}
        return {**_unavailable("prepared_admission_pending"), **prepared}
    try:
        published = _published(child, gemma_root,
                               expected_source_sha256=expected_report_source_sha256)
        if published is None:
            admission_sha = _recorded_admission(child)
            if admission_sha is None:
                return _unavailable("source_unavailable")
            return {**_unavailable("recorded_admission_report_pending"),
                    **prepared, "mia_admission_sha256": admission_sha}
        return published
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, AttributeError):
        return _unavailable("source_unavailable")
