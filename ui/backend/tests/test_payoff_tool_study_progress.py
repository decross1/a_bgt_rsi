"""Content-free payoff-tool UI admission and staged-status fixtures."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ui.backend import payoff_tool_study_progress as p


@pytest.fixture
def prepared(tmp_path: Path, monkeypatch):
    source = p.OUTPUT
    output = tmp_path / "payoff-tool-study" / p.STUDY_ID
    output.mkdir(parents=True)
    plan_raw = (source / "plan.json").read_bytes()
    (output / "plan.json").write_bytes(plan_raw)
    window = json.loads((source / "window.json").read_bytes())
    window["output_dir"] = str(output)
    window["plan"] = {"path": str(output / "plan.json"), "sha256": p.PLAN_SHA}
    (output / "window.json").write_bytes(json.dumps(
        window, sort_keys=True, separators=(",", ":"),
    ).encode() + b"\n")
    monkeypatch.setattr(p, "WINDOW_SHA", p._document(output / "window.json")[1])
    return tmp_path, output, json.loads(plan_raw)


def test_prepared_registered_attempt_has_no_arithmetic_counts(prepared):
    root, _output, _plan = prepared
    row = p.project_progress(root)
    assert row["status"] == "prepared_unissued"
    assert row["plan_raw_sha256"] == p.PLAN_SHA
    assert row["window_raw_sha256"] == p.WINDOW_SHA
    assert row["admission_raw_sha256"] is None
    assert row["results"] is None


def test_running_and_aborted_stages_still_withhold_scores(prepared):
    root, output, _plan = prepared
    (output / "state.json").write_bytes(b"{}\n")
    assert p.project_progress(root)["status"] == "execution_pending"
    restoration = {"status": "verified", "errors": [], "sentinel_retained": False}
    state = {"window_sha256": p.WINDOW_SHA, "phase": "aborted",
             "restoration": restoration}
    result = {"schema": "lab-model-window-result/v1", "window_id": p.STUDY_ID,
              "window_sha256": p.WINDOW_SHA, "cohort": "resident",
              "status": "aborted", "error": "closed", "restoration": restoration}
    supervisor = {"schema": "payoff-tool-study-supervision/v1",
                  "window_sha256": p.WINDOW_SHA, "returncode": 1,
                  "interrupted": None, "terminated_at_cutoff": False,
                  "emergency_restoration": None}
    for name, row in (("state.json", state), ("result.json", result),
                      ("supervision.json", supervisor)):
        (output / name).write_bytes(json.dumps(row).encode() + b"\n")
    projected = p.project_progress(root)
    assert projected["status"] == "aborted_unadmitted"
    assert projected["results"] is None


def test_fixed_closed_no_call_receipt_requires_absence_of_worker_sources(prepared, monkeypatch):
    root, output, _plan = prepared
    archived = json.loads((p.OUTPUT / "not-issued.json").read_bytes())
    archived["window_sha256"] = p.WINDOW_SHA
    (output / "not-issued.json").write_bytes(json.dumps(
        archived, sort_keys=True, separators=(",", ":"),
    ).encode() + b"\n")
    monkeypatch.setattr(p, "NONEXECUTION_SHA", p._document(output / "not-issued.json", 8_000)[1])
    row = p.project_progress(root)
    assert row["status"] == "closed_unissued"
    assert row["nonexecution_raw_sha256"] == p.NONEXECUTION_SHA
    assert row["results"] is None
    (output / "supervision-reservation.json").write_bytes(b"{}\n")
    assert p.project_progress(root)["status"] == "source_unavailable"


def test_resealed_nonexecution_count_is_not_a_closed_no_call_receipt(prepared, monkeypatch):
    root, output, _plan = prepared
    archived = json.loads((p.OUTPUT / "not-issued.json").read_bytes())
    archived["window_sha256"] = p.WINDOW_SHA
    archived["issued_model_calls"] = 1
    (output / "not-issued.json").write_bytes(json.dumps(archived).encode() + b"\n")
    monkeypatch.setattr(p, "NONEXECUTION_SHA", p._document(output / "not-issued.json", 8_000)[1])
    assert p.project_progress(root)["status"] == "source_unavailable"


def _public_run(plan: dict):
    slots = []
    outcomes = []
    issued = 0
    for fixture in plan["fixtures"]:
        pair = fixture["pair_id"]
        direct = {"slot_id": f"{pair}/direct", "status": "returned"}
        first = {"slot_id": f"{pair}/tool_first", "status": "returned"}
        executed = fixture["seat"] == 0
        last = ({"slot_id": f"{pair}/tool_final", "status": "returned"} if executed
                else {"slot_id": f"{pair}/tool_final", "status": "skipped",
                      "failure_code": "no_tool"})
        slots.extend((direct, first, last))
        for arm in fixture["arm_order"]:
            if arm == "direct":
                outcomes.append({"pair_id": pair, "arm": "direct",
                                 "calls": [{"status": "returned"}],
                                 "grade": {"details": {"strict_shape": True,
                                                       "both_correct": True}}})
                issued += 1
            else:
                tool_grade = {"parsed_tool_call": executed, "args_shape_valid": executed,
                              "args_correct": executed, "tool_executed": executed,
                              "failure_code": None if executed else "no_tool"}
                outcomes.append({"pair_id": pair, "arm": "tool",
                                 "calls": [{"status": "returned"}] * (2 if executed else 1),
                                 "grade": {"details": {"strict_shape": executed,
                                                       "both_correct": executed,
                                                       "tool": tool_grade}}})
                issued += 2 if executed else 1
    ordered = {slot["slot_id"]: slot for slot in slots}
    return {"schema_version": "payoff-tool-study-run/v1", "status": "complete",
            "window_id": p.STUDY_ID, "plan_raw_sha256": p.PLAN_SHA,
            "runtime_certificate": plan["runtime_certificate"],
            "claim_limit": p.CLAIM, "promotion_authorized": False,
            "declared_pairs": plan["declared_pairs"],
            "declared_slots": plan["declared_slots"],
            "slots": [ordered[sid] for sid in plan["declared_slots"]],
            "outcomes": outcomes, "issued_calls": issued, "elapsed_s": 301.4}


def test_public_recount_preserves_six_conditions_per_arm_and_causal_skips(prepared):
    _root, _output, plan = prepared
    counts = p._public_counts(plan, _public_run(plan))
    assert counts["declared_conditions_per_arm"] == 6
    assert counts["issued_calls"] == 15
    assert counts["direct"] == {"strict_shape": 6, "strict_both_correct": 6}
    assert counts["tool"]["native_calls_executed"] == 3
    assert counts["tool"]["causal_final_skips"] == 3
    assert counts["tool"]["strict_both_correct"] == 3


def test_resealed_public_causal_skip_or_denominator_is_rejected(prepared):
    _root, _output, plan = prepared
    run = _public_run(plan)
    run["slots"][5]["status"] = "returned"  # G1 seat 1 has no valid tool call.
    with pytest.raises(ValueError, match="causal final skip"):
        p._public_counts(plan, run)
    run = _public_run(plan)
    run["issued_calls"] = 14
    with pytest.raises(ValueError, match="summary relations"):
        p._public_counts(plan, run)


def test_router_returns_injected_content_free_projector():
    app = FastAPI()
    p.register(app, projector=lambda: {"schema_version": p.SCHEMA,
                                       "status": "prepared_unissued", "results": None})
    row = TestClient(app).get("/api/payoff_tool_study_progress").json()
    assert row["status"] == "prepared_unissued"
    assert row["results"] is None
