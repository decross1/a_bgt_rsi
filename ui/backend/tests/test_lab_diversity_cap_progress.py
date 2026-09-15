"""Closed cap results must keep literal source and forty-call denominators."""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ui.backend import lab_diversity_cap_progress as cap


def _plan() -> dict:
    cells = [f"diversity-cap/{task}/cap-{tokens}/seed-401"
             for task in cap.TASKS for tokens in (384, 1536)]
    refs = {f"source/{i}": "0" * 64 for i in range(15)}
    refs["bench/flash_next_ab/lab_eval_diversity_cap.py"] = cap.EVALUATOR_SHA
    return {"schema_version": "lab-mia-diversity-cap-plan/v1",
            "suite_id": "mia-diversity-cap384-cap1536-five-reused-task-pairs-20260915-v1",
            "caps": [384, 1536], "cohorts": ["flash"],
            "generator_timeout_s": 60.0, "selector_timeout_s": 20.0,
            "declared_call_count": 40, "declared_cells": cells,
            "claim_limit": cap.CLAIM, "promotion_authorized": False,
            "evaluator_source_bundle": refs}


def _window() -> dict:
    refs = {f"source/{i}": {"path": "/source", "sha256": "0" * 64}
            for i in range(43)}
    for path, sha in (("bench/flash_next_ab/lab_window.py", cap.CONTROLLER_SHA),
                      ("bench/flash_next_ab/lab_eval_diversity_cap.py", cap.EVALUATOR_SHA)):
        refs[path] = {"path": str(cap.CODE_ROOT / path), "sha256": sha}
    return {"schema": "lab-model-window/v1",
            "window_id": "qfn-ab-lab-diversity-cap-20260915-a",
            "evaluation_kind": "diversity_cap", "cohort": "flash",
            "code_root": str(cap.CODE_ROOT), "output_dir": str(cap.OUTPUT),
            "evaluation_plan": {"path": str(cap.PLAN), "sha256": cap.PLAN_SHA},
            "candidate_spec_id": cap.VARIANT, "runtime_budget_s": 2200,
            "wall_s": 4500, "restoration_reserve_s": 600,
            "promotion_authorized": False, "controller_sources": refs}


def _run(plan: dict) -> dict:
    outcomes = []
    for task in cap.TASKS:
        for tokens in (384, 1536):
            passed = task == cap.TASKS[0]
            calls = [{"role": "generator", "max_tokens": tokens,
                      "timeout_s": 60.0, "status": "returned"} for _ in range(3)]
            calls.append({"role": "validator", "max_tokens": 128,
                          "timeout_s": 20.0, "status": "returned"})
            outcomes.append({"cell_id": f"diversity-cap/{task}/cap-{tokens}/seed-401",
                             "task_id": task, "cohort": "flash", "calls": calls,
                             "passed": passed, "grade": {"passed": passed,
                                 "details": {"existing_grade": {
                                     "task_success": passed, "valid_count": 2}}}})
    return {"schema_version": "lab-mia-diversity-cap-run/v1", "status": "complete",
            "cohort": "flash", "plan_raw_sha256": cap.PLAN_SHA,
            "declared_call_count": 40, "issued_call_count": 40,
            "claim_limit": cap.CLAIM, "promotion_authorized": False,
            "outcomes": outcomes}


def test_exact_registration_and_source_drift() -> None:
    plan, window = _plan(), _window()
    cap._registered(plan, window)
    window["controller_sources"]["bench/flash_next_ab/lab_window.py"]["sha256"] = "f" * 64
    with pytest.raises(ValueError):
        cap._registered(plan, window)


def test_public_run_recounts_underlying_objective_and_protocol() -> None:
    plan = _plan()
    plan["declared_cells"] = [row["cell_id"] for row in _run(plan)["outcomes"]]
    run = _run(plan)
    counts, paired = cap._public_summary(plan, run)
    assert counts["384"]["valid_proposals"] == 10
    assert counts["1536"]["creditable_protocol_pass"] == 1
    assert paired == {"cap1536_pass_cap384_fail": 0,
                      "cap384_pass_cap1536_fail": 0,
                      "both_pass": 1, "neither_pass": 4}
    run["outcomes"][0]["calls"][0]["timeout_s"] = 20.0
    with pytest.raises(ValueError):
        cap._public_summary(plan, run)


def test_out_of_order_and_resealed_public_grade_rejected() -> None:
    plan = _plan()
    run = _run(plan)
    run["outcomes"][0], run["outcomes"][1] = run["outcomes"][1], run["outcomes"][0]
    with pytest.raises(ValueError):
        cap._public_summary(plan, run)
    run = _run(plan)
    run["outcomes"][0]["grade"]["passed"] = False
    with pytest.raises(ValueError):
        cap._public_summary(plan, run)


def test_incomplete_terminal_is_distinct_from_admission_pending(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(cap, "OUTPUT", tmp_path)
    assert cap._terminal_status() == "prepared_unissued"
    (tmp_path / "state.json").write_text("{}")
    assert cap._terminal_status() == "execution_pending"
    (tmp_path / "result.json").write_text(json.dumps({"window_sha256": cap.WINDOW_SHA,
                                                        "status": "failed"}))
    (tmp_path / "supervision.json").write_text(json.dumps({"window_sha256": cap.WINDOW_SHA,
                                                             "returncode": 1}))
    assert cap._terminal_status() == "incomplete_terminal"


def test_cap_count_relations_and_nonfinite_time_rejected() -> None:
    row = {"condition_cells": 5, "generator_calls": 15,
           "generator_returned": 15, "generator_timeout": 0,
           "length_reasoning_only_empty": 0, "empty_visible_final": 0,
           "valid_proposals": 10, "selector_calls": 5,
           "selector_returned": 5, "selector_timeout": 0,
           "underlying_objective_success": 1, "creditable_protocol_pass": 1,
           "generator_finish_reason_histogram": {"stop": 15},
           "generator_call_wall_s": 45.0, "selector_call_wall_s": 5.0}
    assert cap._cap(row, 384)["valid_proposals"] == 10
    with pytest.raises(ValueError):
        cap._cap({**row, "empty_visible_final": 16}, 384)
    with pytest.raises(ValueError):
        cap._cap({**row, "generator_call_wall_s": float("nan")}, 384)


def test_read_only_endpoint_keeps_pending_counts_null() -> None:
    app = FastAPI()
    cap.register(app, projector=lambda: {"schema_version": cap.SCHEMA,
                                         "status": "prepared_unissued", "results": None})
    row = TestClient(app).get("/api/lab_diversity_cap_progress").json()
    assert row["status"] == "prepared_unissued"
    assert row["results"] is None
