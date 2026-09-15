"""The prepared Mia window must never be projected as an executed pilot."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ui.backend import mia_utility_pilot_progress as progress


def _write(path: Path, value: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _prepared_fixture(tmp_path: Path, monkeypatch):
    artifact_root = tmp_path / "outputs"
    child = artifact_root / progress.WINDOW_ID
    source_root = tmp_path / "registered-source"
    controller_path = source_root / "experiments/known_opponent_utility/mia_controller.py"
    controller_path.parent.mkdir(parents=True, exist_ok=True)
    controller_path.write_bytes(b"registered controller snapshot")
    controller_sha = hashlib.sha256(controller_path.read_bytes()).hexdigest()
    parent = tmp_path / "parent.json"
    parent_sha = _write(parent, {"registered": True})
    gemma = tmp_path / "gemma-admission.json"
    gemma_sha = _write(gemma, {"admitted": True})
    manifest_sha = _write(child / "manifest.snapshot.json", {
        "schema": "known-opponent-utility-response-pilot/v1",
        "study_id": "known-opponent-utility-response-pilot-v1",
        "source_root": str(source_root), "max_calls": 108, "horizon": 8,
    })
    for key, value in (("CONTROLLER_SHA256", controller_sha),
                       ("PARENT_PATH", parent), ("PARENT_SHA256", parent_sha),
                       ("GEMMA_ADMISSION_PATH", gemma),
                       ("GEMMA_ADMISSION_SHA256", gemma_sha),
                       ("MANIFEST_SHA256", manifest_sha)):
        monkeypatch.setattr(progress, key, value)
    window_sha = _write(child / "window.json", {
        "schema": "known-opponent-mia-study-window/v1",
        "window_id": progress.WINDOW_ID, "output_dir": str(child),
        "code_root": str(source_root), "cohort": "flash",
        "manifest": {"path": str(child / "manifest.snapshot.json"),
                     "sha256": manifest_sha},
        "qualified_parent": {"path": str(parent), "sha256": parent_sha,
                             "candidate_spec_id": progress.PROFILE_ID,
                             "candidate_spec_sha256": progress.PROFILE_SHA256},
        "matched_gemma": {"admission_path": str(gemma),
                          "admission_sha256": gemma_sha},
        "controller_sources": {
            "experiments/known_opponent_utility/mia_controller.py": {
                "path": str(controller_path), "sha256": controller_sha}},
        "policy": {"enable_thinking": False, "temperature": 0.0,
                   "top_k": 64, "top_p": 1.0},
        "wall_s": 3000, "pilot_s": 900, "restoration_reserve_s": 600,
        "comparison_eligible": False, "promotion_authorized": False,
        "trading_claim_authorized": False,
    })
    return artifact_root, source_root, child, window_sha


def test_prepared_window_does_not_publish_attempts_or_scores(tmp_path, monkeypatch):
    root, source_root, child, window_sha = _prepared_fixture(tmp_path, monkeypatch)
    _write(child / "pilot/run.json", {"attempted_calls": 108, "passed": 108})
    projected = progress.project_mia_pilot(
        root=root, source_root=source_root, expected_window_sha256=window_sha)
    assert projected["status"] == "prepared_admission_pending"
    assert projected["window_raw_sha256"] == window_sha
    assert projected["arms"] is None
    assert "attempted_calls" not in projected


def test_window_or_registered_source_drift_withholds_preparation(tmp_path, monkeypatch):
    root, source_root, child, window_sha = _prepared_fixture(tmp_path, monkeypatch)
    window = json.loads((child / "window.json").read_text())
    window["promotion_authorized"] = True
    _write(child / "window.json", window)
    assert progress.project_mia_pilot(
        root=root, source_root=source_root,
        expected_window_sha256=window_sha)["status"] == "source_unavailable"


def test_public_regret_requires_the_complete_eight_action_horizon():
    task = {"task_sha256": "a" * 64, "cell": {"objective": "own_payoff"}}
    full = {"task_sha256": "a" * 64, "cell": task["cell"],
            "comprehension": "failed", "valid_prefix_actions": 8,
            "scheduled_actions": 8, "calls": [{}] * 9,
            "first_invalid_round": None,
            "full_episode": {"episode_regret": "1/2"}}
    assert progress._public_cell(task, full)["episode_regret"] == "1/2"
    partial = {**full, "valid_prefix_actions": 3, "calls": [{}] * 5,
               "first_invalid_round": 4, "full_episode": None}
    assert progress._public_cell(task, partial)["episode_regret"] is None
    with pytest.raises(ValueError):
        progress._public_cell(task, {**partial, "full_episode": {"episode_regret": "0"}})
    with pytest.raises(ValueError):
        progress._public_cell(task, {**full, "full_episode": {"episode_regret": "1/0"}})


def test_public_raw_ref_rejects_changed_bytes_and_redirected_path(tmp_path):
    path = tmp_path / "receipt.json"
    sha = _write(path, {"public": True})
    assert progress._ref({"path": str(path), "sha256": sha}, path) == sha
    with pytest.raises(ValueError):
        progress._ref({"path": str(tmp_path / "other.json"), "sha256": sha}, path)
    _write(path, {"public": False})
    with pytest.raises(ValueError):
        progress._ref({"path": str(path), "sha256": sha}, path)


def _publication_fixture(tmp_path: Path, monkeypatch):
    root, source_root, child, _ = _prepared_fixture(tmp_path, monkeypatch)
    gemma_root = tmp_path / "gemma"
    cells = []
    tasks = []
    per_cell = []
    for ordinal in range(12):
        condition = {"ordinal": ordinal, "mix": "retainers",
                     "objective": "own_payoff" if ordinal % 2 == 0 else "joint_payoff",
                     "seat": ordinal % 2, "rule_label": "A" if ordinal % 2 == 0 else "B"}
        task_sha = f"{ordinal + 1:064x}"
        tasks.append({"cell": condition, "task_sha256": task_sha})
        cells.append({"cell": condition, "task_sha256": task_sha,
                      "comprehension": "failed", "valid_prefix_actions": 8,
                      "scheduled_actions": 8, "calls": [{}] * 9,
                      "first_invalid_round": None,
                      "full_episode": {"episode_regret": "0"}})
        numeric = {"arithmetic_status": "failed", "valid_action_prefix": 8,
                   "attempted_calls": 9, "first_invalid_round": None,
                   "complete_episode": True, "episode_regret": "0",
                   "zero_regret": True}
        per_cell.append({"ordinal": ordinal, "task_sha256": task_sha,
                         "mix": condition["mix"], "objective": condition["objective"],
                         "seat": condition["seat"],
                         "neutral_rule_label": condition["rule_label"],
                         "gemma": numeric, "mia": numeric})
    manifest = {"schema": "known-opponent-utility-response-pilot/v1",
                "study_id": "known-opponent-utility-response-pilot-v1",
                "source_root": str(source_root), "max_calls": 108, "horizon": 8,
                "manifest_sha256": "c" * 64, "schedule": [row["cell"] for row in tasks],
                "tasks": tasks, "policy": {"temperature": 0.0},
                "seed_base": 301, "max_tokens": 64, "per_call_timeout_s": 30.0,
                "max_window_s": 900}
    manifest_sha = _write(child / "manifest.snapshot.json", manifest)
    _write(child / "evaluation/manifest.json", manifest)
    gemma_manifest_sha = _write(gemma_root / "manifest.snapshot.json", manifest)
    _write(gemma_root / "pilot/manifest.json", manifest)
    monkeypatch.setattr(progress, "MANIFEST_SHA256", manifest_sha)
    run = {"schema": "known-opponent-utility-response-pilot-run/v1",
           "status": "complete", "manifest_sha256": "c" * 64,
           "scheduled_calls": 108, "attempted_calls": 108,
           "elapsed_s": 84.5, "cells": cells}
    gemma_run_sha = _write(gemma_root / "pilot/run.json", run)
    mia_run_sha = _write(child / "evaluation/run.json", run)
    monkeypatch.setattr(progress, "GEMMA_MANIFEST_SHA256", gemma_manifest_sha)
    monkeypatch.setattr(progress, "GEMMA_RUN_SHA256", gemma_run_sha)
    validation = {"admission_eligible": True, "recorded_episodes": 12,
                  "schema": "known-opponent-utility-response-validation/v1",
                  "status": "admitted_empirical_pilot",
                  "run_sha256": gemma_run_sha,
                  "manifest_sha256": "c" * 64,
                  "comparison_eligible": False, "private_content_exported": False,
                  "scientific_novelty_claimed": False,
                  "scheduled_action_calls": 96, "attempted_calls": 108,
                  "comprehension_passed": 0, "valid_action_calls": 96,
                  "complete_episodes": 12,
                  "zero_regret_complete_episodes": 12,
                  "returned_sse_verified": 108}
    gemma_admission_sha = _write(gemma_root / "admission.json", {
        "schema": "known-opponent-resident-study-admission/v1",
        "pilot_run_sha256": gemma_run_sha, "pilot_validation": validation,
    })
    gemma_admission_path = gemma_root / "admission.json"
    monkeypatch.setattr(progress, "GEMMA_ADMISSION_PATH", gemma_admission_path)
    monkeypatch.setattr(progress, "GEMMA_ADMISSION_SHA256", gemma_admission_sha)
    window_path = child / "window.json"
    window = json.loads(window_path.read_text())
    window["manifest"]["sha256"] = manifest_sha
    window["matched_gemma"] = {"admission_path": str(gemma_admission_path),
                               "admission_sha256": gemma_admission_sha}
    window_sha = _write(window_path, window)
    monkeypatch.setattr(progress, "WINDOW_SHA256", window_sha)
    restoration = {"status": "verified", "errors": [], "sentinel_retained": False}
    _write(child / "result.json", {"schema": "lab-model-window-result/v1",
                                   "status": "complete", "window_sha256": window_sha,
                                   "error": None, "restoration": restoration})
    _write(child / "state.json", {"phase": "complete", "window_sha256": window_sha,
                                  "restoration": restoration})
    _write(child / "supervision.json", {
        "schema": "known-opponent-mia-study-supervision/v1",
        "window_sha256": window_sha, "returncode": 0, "interrupted": None,
        "terminated_at_cutoff": False, "emergency_restoration": None})
    for path in progress._expected_refs(child, gemma_root)["gemma"].values():
        if not path.exists():
            _write(path, {"archived": True})
    for path in progress._expected_refs(child, gemma_root)["mia"].values():
        if not path.exists() and path.name != "admission.json":
            _write(path, {"archived": True})
    memory_raw = b'{"monitor_phase":"evaluation"}\n'
    (child / "memory.jsonl").write_bytes(memory_raw)
    _write(child / "admission.json", {
        "schema": "known-opponent-mia-study-admission/v1",
        "window_id": progress.WINDOW_ID, "window_sha256": window_sha,
        "matched_gemma_admission_sha256": gemma_admission_sha,
        "qualified_parent_sha256": progress.PARENT_SHA256,
        "pilot_run_sha256": mia_run_sha, "pilot_validation": validation,
        "memory": {"raw_sha256": hashlib.sha256(memory_raw).hexdigest(),
                   "samples": 1, "evaluation_samples": 1,
                   "minimum_mem_available_gib": 34.0},
        "result_sha256": hashlib.sha256((child / "result.json").read_bytes()).hexdigest(),
        "state_sha256": hashlib.sha256((child / "state.json").read_bytes()).hexdigest(),
        "supervision_sha256": hashlib.sha256((child / "supervision.json").read_bytes()).hexdigest(),
        "comparison_eligible": False, "promotion_authorized": False,
        "trading_claim_authorized": False,
    })
    raw_refs = {arm: {name: {"path": str(path),
                            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                      for name, path in paths.items()}
                for arm, paths in progress._expected_refs(child, gemma_root).items()}
    source_path = child / progress.REPORT_SOURCE_NAME
    source_path.write_bytes(b"frozen one-time comparison producer")
    source_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()
    summary = {"scheduled_cells": 12, "recorded_cells": 12,
               "scheduled_action_calls": 96, "attempted_calls": 108,
               "arithmetic_passed": 0, "valid_action_calls": 96,
               "complete_episodes": 12, "zero_regret_complete_episodes": 12,
               "returned_sse_verified": 108, "evaluator_elapsed_s": 84.5}
    canonical = lambda value: json.dumps(value, sort_keys=True, separators=(",", ":"),
                                         allow_nan=False).encode()
    matching = {"ordered_task_sha256": [task["task_sha256"] for task in tasks],
                "task_panel_sha256": hashlib.sha256(canonical(tasks)).hexdigest(),
                "schedule_sha256": hashlib.sha256(canonical(manifest["schedule"])).hexdigest(),
                "policy_sha256": hashlib.sha256(canonical(manifest["policy"])).hexdigest(),
                "seed_base": 301, "max_tokens": 64, "per_call_timeout_s": 30.0,
                "max_window_s": 900, "max_calls": 108, "horizon": 8,
                "fixed_game_conditions_matched": True,
                "adaptive_histories_and_later_call_seeds_may_differ": True}
    source_ref = {"path": str(source_path), "sha256": source_sha}
    report_sha = _write(child / "descriptive-comparison.json", {
        "schema": progress.REPORT_SCHEMA, "mia_window_id": progress.WINDOW_ID,
        "source_ref": source_ref, "raw_refs": raw_refs, "matching": matching,
        "arms": {"gemma": summary, "mia": summary}, "per_cell": per_cell,
        "terminal_replay": {"gemma": "recorded_admission_and_raw_refs_verified",
                            "mia": "current_source_terminal_gate_verified"},
        "comparison_eligible": False, "private_content_exported": False,
        "scientific_novelty_claimed": False, "trading_claim_authorized": False,
        "interpretation": "descriptive_matched_fixture_adaptive_serial_trajectories",
    })
    _write(child / "descriptive-comparison-index.json", {
        "schema": progress.INDEX_SCHEMA, "mia_window_id": progress.WINDOW_ID,
        "report_ref": {"path": str(child / "descriptive-comparison.json"),
                       "sha256": report_sha},
        "source_ref": source_ref, "raw_refs": raw_refs,
        "comparison_eligible": False, "private_content_exported": False,
    })
    return root, source_root, gemma_root, child, window_sha, source_sha


def test_completed_publication_rederives_only_content_free_12_cell_counts(tmp_path, monkeypatch):
    root, source_root, gemma_root, child, window_sha, source_sha = _publication_fixture(
        tmp_path, monkeypatch)
    pending = progress.project_mia_pilot(
        root=root, source_root=source_root, gemma_root=gemma_root,
        expected_window_sha256=window_sha,
        expected_report_source_sha256=None)
    assert pending["status"] == "recorded_admission_report_pending"
    assert pending["arms"] is None
    admitted = progress.project_mia_pilot(
        root=root, source_root=source_root, gemma_root=gemma_root,
        expected_window_sha256=window_sha,
        expected_report_source_sha256=source_sha)
    assert admitted["status"] == "admitted_descriptive"
    assert admitted["arms"]["mia"]["complete_episodes"] == 12
    assert admitted["arms"]["mia"]["zero_regret_complete_episodes"] == 12
    assert admitted["current_source_replay"] == "not_performed"
    assert all(key not in admitted["arms"]["mia"]
               for key in ("calls", "messages", "per_cell", "raw_response"))
    run = json.loads((child / "evaluation/run.json").read_text())
    manifest = json.loads((child / "manifest.snapshot.json").read_text())
    admission = json.loads((child / "admission.json").read_text())
    rows = json.loads((child / "descriptive-comparison.json").read_text())["per_cell"]
    with pytest.raises(ValueError):
        progress._public_arm(manifest, {**run, "elapsed_s": float("nan")},
                             admission, rows, "mia")
    run_path = child / "evaluation/run.json"
    run["cells"][0]["full_episode"]["episode_regret"] = "1"
    _write(run_path, run)
    withheld = progress.project_mia_pilot(
        root=root, source_root=source_root, gemma_root=gemma_root,
        expected_window_sha256=window_sha,
        expected_report_source_sha256=source_sha)
    assert withheld["status"] == "source_unavailable"
    assert withheld["arms"] is None


def test_resealed_public_report_cannot_invent_a_valid_action(tmp_path, monkeypatch):
    root, source_root, gemma_root, child, window_sha, source_sha = _publication_fixture(
        tmp_path, monkeypatch)
    report_path = child / "descriptive-comparison.json"
    report = json.loads(report_path.read_text())
    report["per_cell"][0]["mia"]["valid_action_prefix"] = 7
    report["arms"]["mia"]["valid_action_calls"] = 95
    report_sha = _write(report_path, report)
    index_path = child / "descriptive-comparison-index.json"
    index = json.loads(index_path.read_text())
    index["report_ref"]["sha256"] = report_sha
    _write(index_path, index)
    withheld = progress.project_mia_pilot(
        root=root, source_root=source_root, gemma_root=gemma_root,
        expected_window_sha256=window_sha,
        expected_report_source_sha256=source_sha)
    assert withheld["status"] == "source_unavailable"
    assert withheld["arms"] is None
    _prepared_fixture(tmp_path, monkeypatch)
    (source_root / "experiments/known_opponent_utility/mia_controller.py").write_bytes(
        b"changed registered controller")
    assert progress.project_mia_pilot(
        root=root, source_root=source_root,
        expected_window_sha256=window_sha)["status"] == "source_unavailable"
