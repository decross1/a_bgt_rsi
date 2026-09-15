"""A recorded pilot may expose bounded counts without its private responses."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import types
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import research_ops_status as status

MANIFEST_SHA = "a" * 64


def _write(path: Path, row: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(row, sort_keys=True, separators=(",", ":")).encode("utf-8")
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _fixture(tmp_path: Path) -> tuple[dict, Path, Path, Path]:
    repo_root = tmp_path / "registered-code"
    repo_root.mkdir()
    root = tmp_path / "pilot-root"
    child = root / status.PILOT_ID
    child.mkdir(parents=True)
    schedule = [{"id": "cell-" + str(index), "ordinal": index,
                 "objective": "own_payoff" if index < 6 else "joint_payoff"}
                for index in range(12)]
    tasks = [{"cell": row, "comprehension_messages": [
        {"role": "user", "content": "form-one" if index % 2 == 0 else "form-two"}]}
        for index, row in enumerate(schedule)]
    manifest = {"schema": "known-opponent-utility-response-pilot/v1",
                "study_id": "known-opponent-utility-response-pilot-v1",
                "source_root": str(repo_root), "max_calls": 108, "horizon": 8,
                "comprehension_feedback": "none", "manifest_sha256": MANIFEST_SHA,
                "schedule": schedule, "tasks": tasks}
    manifest_sha = _write(child / "manifest.snapshot.json", manifest)
    cells = [{"cell": row, "scheduled_actions": 8, "valid_prefix_actions": 8,
              "comprehension": "failed", "full_episode": {"episode_regret":
                  "0" if index < 3 else "5"}}
             for index, row in enumerate(schedule)]
    run = {"schema": "known-opponent-utility-response-pilot-run/v1",
           "status": "complete", "scheduled_calls": 108, "attempted_calls": 108,
           "manifest_sha256": MANIFEST_SHA, "cells": cells,
           "private_response": "never publish this"}
    run_sha = _write(child / "pilot/run.json", run)
    window = {"schema": "known-opponent-resident-study-window/v1",
              "window_id": status.PILOT_ID, "output_dir": str(child),
              "code_root": str(repo_root),
              "manifest": {"path": str(child / "manifest.snapshot.json"),
                           "sha256": manifest_sha}}
    window_sha = _write(child / "window.json", window)
    result = {"schema": "known-opponent-resident-study-result/v1",
              "status": "observed_restored", "window_sha256": window_sha,
              "pilot_run_sha256": run_sha, "error": None,
              "restoration": {"status": "verified", "errors": [],
                              "sentinel_retained": False}}
    result_sha = _write(child / "result.json", result)
    supervision = {"schema": "known-opponent-resident-study-supervision/v1",
                   "window_sha256": window_sha, "returncode": 0,
                   "interrupted": None, "terminated_at_cutoff": False,
                   "emergency_restoration": None}
    supervision_sha = _write(child / "supervision.json", supervision)
    validation = {"schema": "known-opponent-utility-response-validation/v1",
                  "status": "admitted_empirical_pilot", "admission_eligible": True,
                  "run_sha256": run_sha, "manifest_sha256": MANIFEST_SHA,
                  "comparison_eligible": False, "private_content_exported": False,
                  "scientific_novelty_claimed": False, "attempted_calls": 108,
                  "complete_episodes": 12, "scheduled_action_calls": 96,
                  "scheduled_episodes": 12, "valid_action_calls": 96,
                  "zero_regret_complete_episodes": 3, "comprehension_passed": 0}
    admission = {"schema": "known-opponent-resident-study-admission/v1",
                 "window_id": status.PILOT_ID, "window_sha256": window_sha,
                 "result_sha256": result_sha, "supervision_sha256": supervision_sha,
                 "pilot_run_sha256": run_sha, "comparison_eligible": False,
                 "promotion_authorized": False, "trading_claim_authorized": False,
                 "pilot_validation": validation}
    admission_sha = _write(child / "admission.json", admission)
    view = {"schema": "research-ops-status/v1",
            "empirical_pilot": {"status": "recorded_admitted",
                                "window_id": status.PILOT_ID,
                                "admission_receipt_sha256": admission_sha,
                                "pilot_run_sha256": run_sha,
                                "attempted_calls": 108, "complete_episodes": 12,
                                "current_source_replay": "not_performed"},
            "next_work": {"code": "review_admitted_empirical_pilot",
                          "pilot_admission_receipt_sha256": admission_sha}}
    return view, root, repo_root, child


def test_exact_archived_gate_projects_syntax_and_separate_utility_counts(tmp_path):
    view, root, repo_root, _child = _fixture(tmp_path)
    behavior = status._pilot_behavior(view, root, repo_root)
    assert behavior["valid_action_calls"] == 96
    assert behavior["scheduled_action_calls"] == 96
    assert behavior["zero_regret_complete_episodes"] == 3
    assert behavior["comprehension_passed"] == 0
    assert behavior["comprehension_prompt_forms"] == 2
    assert behavior["by_utility"] == {
        "own_payoff": {"complete": 6, "zero_regret": 3},
        "joint_payoff": {"complete": 6, "zero_regret": 0}}
    assert "form-one" not in str(behavior)
    assert "never publish" not in str(behavior)
    enriched = status._enrich(view, root, repo_root)
    assert enriched["empirical_pilot"]["behavior_summary"] == behavior
    assert "behavior_summary" not in view["empirical_pilot"]
    view["next_work"]["code"] = "run_preregistered_campaign_topic"
    assert status._pilot_behavior(view, root, repo_root) == behavior


def test_drift_or_overclaim_withholds_behavior_counts(tmp_path):
    view, root, repo_root, child = _fixture(tmp_path)
    wrong = copy.deepcopy(view)
    wrong["empirical_pilot"]["admission_receipt_sha256"] = "b" * 64
    wrong["next_work"]["pilot_admission_receipt_sha256"] = "b" * 64
    assert status._pilot_behavior(wrong, root, repo_root) is None
    admission_path = child / "admission.json"
    admission = json.loads(admission_path.read_text(encoding="utf-8"))
    admission["pilot_validation"]["zero_regret_complete_episodes"] = 13
    new_sha = _write(admission_path, admission)
    view["empirical_pilot"]["admission_receipt_sha256"] = new_sha
    view["next_work"]["pilot_admission_receipt_sha256"] = new_sha
    assert status._pilot_behavior(view, root, repo_root) is None
    admission["pilot_validation"]["zero_regret_complete_episodes"] = 3
    admission["pilot_validation"]["valid_action_calls"] = 97
    new_sha = _write(admission_path, admission)
    view["empirical_pilot"]["admission_receipt_sha256"] = new_sha
    assert status._pilot_behavior(view, root, repo_root) is None


def test_out_of_order_cells_withhold_behavior_counts(tmp_path):
    view, root, repo_root, child = _fixture(tmp_path)
    run_path, admission_path = child / "pilot/run.json", child / "admission.json"
    run = json.loads(run_path.read_text(encoding="utf-8"))
    run["cells"][0], run["cells"][1] = run["cells"][1], run["cells"][0]
    run_sha = _write(run_path, run)
    admission = json.loads(admission_path.read_text(encoding="utf-8"))
    admission["pilot_run_sha256"] = run_sha
    admission["pilot_validation"]["run_sha256"] = run_sha
    admission_sha = _write(admission_path, admission)
    view["empirical_pilot"]["pilot_run_sha256"] = run_sha
    view["empirical_pilot"]["admission_receipt_sha256"] = admission_sha
    view["next_work"]["pilot_admission_receipt_sha256"] = admission_sha
    assert status._pilot_behavior(view, root, repo_root) is None


def test_changed_comprehension_forms_withhold_behavior_counts(tmp_path):
    view, root, repo_root, child = _fixture(tmp_path)
    # The two repeated forms are part of the fixed study, not 12 new questions.
    manifest_path = child / "manifest.snapshot.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for index, task in enumerate(manifest["tasks"]):
        task["comprehension_messages"][0]["content"] = "unique-" + str(index)
    manifest_sha = _write(manifest_path, manifest)
    window_path = child / "window.json"
    window = json.loads(window_path.read_text(encoding="utf-8"))
    window["manifest"]["sha256"] = manifest_sha
    window_sha = _write(window_path, window)
    result_path, supervision_path = child / "result.json", child / "supervision.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["window_sha256"] = window_sha
    result_sha = _write(result_path, result)
    supervision = json.loads(supervision_path.read_text(encoding="utf-8"))
    supervision["window_sha256"] = window_sha
    supervision_sha = _write(supervision_path, supervision)
    admission_path = child / "admission.json"
    admission = json.loads(admission_path.read_text(encoding="utf-8"))
    admission.update(window_sha256=window_sha, result_sha256=result_sha,
                     supervision_sha256=supervision_sha)
    admission_sha = _write(admission_path, admission)
    view["empirical_pilot"]["admission_receipt_sha256"] = admission_sha
    view["next_work"]["pilot_admission_receipt_sha256"] = admission_sha
    assert status._pilot_behavior(view, root, repo_root) is None


def test_registered_route_enriches_only_matching_admitted_public_refs(monkeypatch, tmp_path):
    view, root, repo_root, child = _fixture(tmp_path)
    module = types.ModuleType("orchestrator.research_ops_status")
    module.project_research_ops_status = lambda *, repo_root, ingestion_root: view
    monkeypatch.setitem(sys.modules, "orchestrator.research_ops_status", module)
    app = FastAPI()
    status.register(app, repo_root=repo_root, pilot_root=root)
    client = TestClient(app)
    first = client.get("/api/research_ops_status")
    assert first.status_code == 200
    assert first.json()["empirical_pilot"]["behavior_summary"]["valid_action_calls"] == 96
    assert "form-one" not in first.text
    admission_path = child / "admission.json"
    admission_path.write_text("{}", encoding="utf-8")
    drifted = client.get("/api/research_ops_status")
    assert drifted.status_code == 200
    assert "behavior_summary" not in drifted.json()["empirical_pilot"]
