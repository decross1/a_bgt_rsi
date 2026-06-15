"""Tests for the generalized coordinator escalation (seam 2).

Covers the ADDITIVE generalization of the coordinator bubble into a generic
escalation: the legacy finding-id bubble {finding_ids, note} stays valid and
keeps surfacing; a generic {question, context, kind, allowed_actions}
escalation persists; kind/allowed_actions validate fail-closed (rule 4 — an
off-enum value is an honest error, never a silent coercion); and the A+B-only
count contract excludes read-receipts (kind C).

Offline + MOCK_LLM-safe: no model call is made (we exercise the handler /
persist / collect / count directly, plus the dispatch loop with a scripted
plan via a call_sync stub). All writes go to tmp_path; real memory/ and
run_state/ are never touched (active_run stubbed).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft7Validator

import orchestrator.coordinator as coord

REPO_ROOT = Path(__file__).resolve().parent.parent
ESCALATION_SCHEMA = json.loads(
    (REPO_ROOT / "schema" / "escalation.schema.json").read_text()
)


# ── fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _stub_active_run(monkeypatch):
    """Never touch run_state/active_run.json from a test (mirrors
    test_coordinator)."""
    monkeypatch.setattr(coord.active_run, "write_active_run",
                        lambda *a, **k: {"run_id": a[0] if a else "x"})
    monkeypatch.setattr(coord.active_run, "update_active_run",
                        lambda *a, **k: None)
    monkeypatch.setattr(coord.active_run, "clear_active_run", lambda: None)
    monkeypatch.setattr(coord, "set_run_id", lambda _x: None)


def _read_rows(path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


# ── handler: legacy form back-compat ──────────────────────────────────────


def test_handle_bubble_up_legacy_finding_ids_still_passes():
    out = coord.handle_bubble_up(finding_ids=["sf-001", "sf-002"], note="look")
    assert out["status"] == "passed"
    assert out["result"]["finding_ids"] == ["sf-001", "sf-002"]
    assert out["result"]["note"] == "look"
    # generic fields default to None on a legacy call.
    assert out["result"]["kind"] is None
    assert out["result"]["question"] is None


def test_handle_bubble_up_generic_escalation_passes():
    out = coord.handle_bubble_up(
        question="Is exp009 Cournot collusion topical for the loop?",
        context="novelty=novel, critic=survives, but no human verdict yet",
        kind="A",
        allowed_actions=["sign_off", "reject", "refine_defer"],
    )
    assert out["status"] == "passed"
    r = out["result"]
    assert r["question"].startswith("Is exp009")
    assert r["kind"] == "A"
    assert r["allowed_actions"] == ["sign_off", "reject", "refine_defer"]
    assert r["finding_ids"] == []  # no finding ids on a pure generic escalation


def test_handle_bubble_up_empty_is_rejected():
    """rule 4 — never fabricate a surfacing: no finding_ids AND no question."""
    with pytest.raises(ValueError):
        coord.handle_bubble_up()
    with pytest.raises(ValueError):
        coord.handle_bubble_up(question="   ")  # whitespace-only is empty


# ── handler: fail-closed validation (rule 4) ──────────────────────────────


def test_handle_bubble_up_unknown_kind_raises():
    with pytest.raises(ValueError):
        coord.handle_bubble_up(question="q", kind="Z")


def test_handle_bubble_up_offenum_allowed_action_raises():
    with pytest.raises(ValueError):
        coord.handle_bubble_up(
            question="q", kind="A", allowed_actions=["sign_off", "delete_repo"],
        )


# ── persistence: legacy + generic, back-compat on-disk shape ──────────────


def test_persist_legacy_bubble_keeps_ui_reader_fields(tmp_path):
    """The legacy on-disk shape stays compatible with the UI reader
    (human_todo._bubble_ack_items consumes run_id/timestamp/note)."""
    bubbles = [{"finding_ids": ["sf-009"], "note": "review me"}]
    p = tmp_path / "coordinator_bubbles.jsonl"
    coord._persist_bubble_up(bubbles, run_id="coordinator_abc", path=p)
    rows = _read_rows(p)
    assert len(rows) == 1
    row = rows[0]
    assert row["run_id"] == "coordinator_abc"
    assert row["finding_ids"] == ["sf-009"]
    assert row["note"] == "review me"
    assert "timestamp" in row
    # A legacy bubble carries NO empty generic keys (additive-only write).
    assert "kind" not in row
    assert "question" not in row
    Draft7Validator(ESCALATION_SCHEMA).validate(row)


def test_persist_generic_escalation_writes_four_fields(tmp_path):
    bubbles = [{
        "finding_ids": [],
        "note": None,
        "question": "Should we run the real Cournot trials?",
        "context": "synthetic results look strong",
        "kind": "A",
        "allowed_actions": ["sign_off", "refine_authorize_fix"],
    }]
    p = tmp_path / "coordinator_bubbles.jsonl"
    coord._persist_bubble_up(bubbles, run_id="coordinator_def", path=p)
    row = _read_rows(p)[0]
    assert row["question"] == "Should we run the real Cournot trials?"
    assert row["context"] == "synthetic results look strong"
    assert row["kind"] == "A"
    assert row["allowed_actions"] == ["sign_off", "refine_authorize_fix"]
    # back-compat fields present too.
    assert row["run_id"] == "coordinator_def"
    assert "timestamp" in row
    Draft7Validator(ESCALATION_SCHEMA).validate(row)


# ── schema: both forms valid, off-enum invalid ────────────────────────────


def test_schema_accepts_legacy_and_generic_forms():
    v = Draft7Validator(ESCALATION_SCHEMA)
    legacy = {
        "run_id": "coordinator_1", "timestamp": "2026-06-14T00:00:00Z",
        "finding_ids": ["sf-1"], "note": "n",
    }
    generic = {
        "run_id": "coordinator_2", "timestamp": "2026-06-14T00:00:00Z",
        "question": "q?", "context": "c", "kind": "B",
        "allowed_actions": ["reject", "abstain"],
    }
    v.validate(legacy)
    v.validate(generic)


def test_schema_rejects_offenum_kind_and_action():
    v = Draft7Validator(ESCALATION_SCHEMA)
    bad_kind = {
        "run_id": "r", "timestamp": "2026-06-14T00:00:00Z",
        "question": "q", "kind": "Z",
    }
    bad_action = {
        "run_id": "r", "timestamp": "2026-06-14T00:00:00Z",
        "question": "q", "kind": "A", "allowed_actions": ["nuke"],
    }
    assert v.iter_errors(bad_kind)
    assert list(v.iter_errors(bad_kind))
    assert list(v.iter_errors(bad_action))
    # run_id is required by the schema (the persist always stamps it).
    assert list(v.iter_errors({"timestamp": "2026-06-14T00:00:00Z"}))


# ── the A+B-only count contract (excludes C) ──────────────────────────────


def test_count_actionable_escalations_excludes_read_receipts(tmp_path):
    p = tmp_path / "coordinator_bubbles.jsonl"
    rows = [
        # legacy finding-id bubble: no `kind` -> taxonomy C -> NOT counted.
        {"run_id": "r1", "timestamp": "t", "finding_ids": ["sf-1"], "note": "n"},
        # explicit read-receipt -> NOT counted.
        {"run_id": "r2", "timestamp": "t", "question": "ack?", "kind": "C"},
        # judgment -> counted.
        {"run_id": "r3", "timestamp": "t", "question": "decide?", "kind": "A"},
        # blocking-halt -> counted.
        {"run_id": "r4", "timestamp": "t", "question": "halt?", "kind": "B"},
    ]
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    assert coord.count_actionable_escalations(path=p) == 2


def test_count_actionable_escalations_missing_file_is_zero(tmp_path):
    assert coord.count_actionable_escalations(path=tmp_path / "nope.jsonl") == 0


# ── collect -> persist -> count pipeline (the seam-2 path I own) ──────────


def test_collect_carries_generic_fields_then_persists_and_counts(tmp_path):
    """The part of the path seam 2 owns: a validated plan with a generic
    bubble_up flows _collect_bubble_up -> _persist_bubble_up ->
    count_actionable_escalations. (The plan->validator step is gated by
    coordinator_actions.bubble_up arg_schema, which is OUT OF this seam's
    contract — see the discrepancy test below.)"""
    validated = [{
        "name": "bubble_up",
        "args": {
            "finding_ids": ["sf-iter-x"],
            "question": "Is iter-x worth promoting?",
            "kind": "A",
            "allowed_actions": ["sign_off", "reject"],
        },
    }]
    collected = coord._collect_bubble_up(validated, executed=None)
    assert collected[0]["question"] == "Is iter-x worth promoting?"
    assert collected[0]["kind"] == "A"

    p = tmp_path / "coordinator_bubbles.jsonl"
    coord._persist_bubble_up(collected, run_id="coordinator_e2e", path=p)
    row = _read_rows(p)[0]
    assert row["kind"] == "A"
    assert row["question"] == "Is iter-x worth promoting?"
    assert row["allowed_actions"] == ["sign_off", "reject"]
    assert row["finding_ids"] == ["sf-iter-x"]
    Draft7Validator(ESCALATION_SCHEMA).validate(row)
    assert coord.count_actionable_escalations(path=p) == 1


def test_validator_accepts_generic_bubble_args():
    """Seam 2 closed end-to-end (2026-06-15): the planner CAN emit a generic
    {question, context, kind, allowed_actions} bubble_up. coordinator_actions
    .bubble_up now accepts the legacy finding-id form OR the generic escalation
    form (anyOf finding_ids|question); the kind/allowed_actions ENUMs stay
    enforced fail-closed by handle_bubble_up (single source of truth), so this
    planner gate only checks the shape. (Was the DISCREPANCY pin.)"""
    from orchestrator.coordinator_actions import validate_plan
    # a well-formed generic escalation validates at the planner gate
    generic_plan = [{
        "action": "bubble_up",
        "args": {"question": "is the PD cooperation result robust?",
                 "kind": "A", "allowed_actions": ["sign_off", "reject"]},
    }]
    assert validate_plan(generic_plan, budget=6)["ok"] is True
    # the legacy finding-id bubble still validates (back-compat)
    legacy_plan = [{"action": "bubble_up", "args": {"finding_ids": ["f1"]}}]
    assert validate_plan(legacy_plan, budget=6)["ok"] is True
    # an empty bubble (neither finding_ids nor question) is still rejected
    empty_plan = [{"action": "bubble_up", "args": {"note": "no payload"}}]
    assert validate_plan(empty_plan, budget=6)["ok"] is False
