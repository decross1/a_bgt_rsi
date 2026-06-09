"""Tests for the coordinator brain (orchestrator/coordinator.py).

Offline + MOCK_LLM-safe: we mock the ONE plan LLM call (call_sync, patched
where the coordinator imports it), stub active_run writes so nothing touches
run_state/, and feed fixture instrumentation via tmp_path. We mock the execute
handlers so no real loop iteration / promotion / model call runs.

The load-bearing proof: a scripted INVALID (off-menu) plan is REJECTED, re-
planned, and if still invalid the cycle returns status="no_valid_plan" and
NO handler is called.
"""
from __future__ import annotations

import json

import pytest

import orchestrator.coordinator as coord


# ── fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _stub_active_run(monkeypatch):
    """Never touch run_state/active_run.json from a test."""
    monkeypatch.setattr(coord.active_run, "write_active_run",
                        lambda *a, **k: {"run_id": a[0] if a else "x"})
    monkeypatch.setattr(coord.active_run, "update_active_run",
                        lambda *a, **k: None)
    monkeypatch.setattr(coord.active_run, "clear_active_run", lambda: None)
    monkeypatch.setattr(coord, "set_run_id", lambda _x: None)


@pytest.fixture
def state_files(tmp_path):
    """Write fixture instrumentation files; return their paths as a dict."""
    loop_memory = tmp_path / "loop_memory.jsonl"
    feedback = tmp_path / "loop_feedback.jsonl"
    surfaced = tmp_path / "surfaced_findings.jsonl"
    active_run_path = tmp_path / "active_run.json"

    rows = [
        {
            "iteration_id": "iter-2026-06-05-001",
            "hypothesis": {"text": "Tit-for-tat dominates in noisy PD."},
            "novelty": {"class": "novel", "rationale": "no near neighbor"},
            "critique": {"verdict": "survives", "rationale": "robust"},
            "gate_status": "pending",
            "journal_entry_path": "journal/x.md",
        },
        {
            "iteration_id": "iter-2026-06-05-002",
            "hypothesis": {"text": "VCG is strategyproof in this auction."},
            "novelty": {"class": "rediscovery", "rationale": "known"},
            "critique": {"verdict": "survives"},
            "experiment_outcome": {"summary": "96.5% truthful over 150 trials"},
            "gate_status": "gated",
        },
    ]
    loop_memory.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    feedback.write_text(json.dumps({
        "iteration_id": "iter-2026-06-05-002",
        "verdict": "valid", "note": "solid",
        "gated_at": "2026-06-05T19:19:02Z", "gated_by": "decross1",
    }) + "\n")
    surfaced.write_text(json.dumps({
        "finding_id": "sf-iter-2026-06-05-099",
        "source_iteration_id": "iter-2026-06-05-099",
        "title": "An older surfaced finding",
        "status": "surfaced",
    }) + "\n")
    # active_run.json absent -> idle.
    return {
        "loop_memory_path": str(loop_memory),
        "feedback_path": str(feedback),
        "surfaced_path": str(surfaced),
        "active_run_path": str(active_run_path),
    }


def _mock_call_sync_returning(plan_obj):
    """A call_sync stub that returns a record whose completion is plan_obj JSON."""
    def _stub(messages, **kwargs):
        return {"request_id": "req-test", "completion": json.dumps(plan_obj)}
    return _stub


# ── assess_state ────────────────────────────────────────────────────────


def test_assess_state_builds_snapshot(state_files):
    snap = coord.assess_state(**state_files)
    assert snap["in_flight"]["active"] is False
    assert snap["in_flight"]["run"] is None
    assert len(snap["recent_findings"]) == 2
    by_id = {f["iteration_id"]: f for f in snap["recent_findings"]}
    assert by_id["iter-2026-06-05-001"]["novelty"] == "novel"
    assert by_id["iter-2026-06-05-002"]["human_verdict"] == "valid"
    # iter-001 has no human verdict + gate pending -> an open thread.
    assert "iter-2026-06-05-001" in snap["open_threads"]
    assert "iter-2026-06-05-002" not in snap["open_threads"]
    # surfaced finding with status "surfaced" -> pending review.
    assert any(s["finding_id"] == "sf-iter-2026-06-05-099"
               for s in snap["surfaced_pending"])
    # gaps mention the novel+surviving unpromoted iter-001.
    assert any("not yet through promotion" in g for g in snap["gaps"])
    # experiments discovered via tier_registry (real, read-only).
    assert isinstance(snap["experiments"], dict)


def test_assess_state_active_run_in_flight(state_files, tmp_path):
    ar = tmp_path / "active_run.json"
    ar.write_text(json.dumps({
        "run_id": "loop-1", "kind": "loop_v0", "label": "running",
    }))
    files = dict(state_files)
    files["active_run_path"] = str(ar)
    snap = coord.assess_state(**files)
    assert snap["in_flight"]["active"] is True
    assert snap["in_flight"]["run"]["run_id"] == "loop-1"


def test_assess_state_missing_files_degrade(tmp_path):
    """All sources absent -> partial snapshot, never raises."""
    snap = coord.assess_state(
        loop_memory_path=str(tmp_path / "nope.jsonl"),
        surfaced_path=str(tmp_path / "nope2.jsonl"),
        feedback_path=str(tmp_path / "nope3.jsonl"),
        active_run_path=str(tmp_path / "nope4.json"),
    )
    assert snap["recent_findings"] == []
    assert snap["in_flight"]["active"] is False
    assert any("no loop iterations" in g for g in snap["gaps"])


# ── plan ──────────────────────────────────────────────────────────────────


def test_plan_extracts_array(monkeypatch, state_files):
    plan_obj = [{"action": "noop", "args": {"reason": "nothing to do"}}]
    monkeypatch.setattr(coord, "call_sync", _mock_call_sync_returning(plan_obj))
    snap = coord.assess_state(**state_files)
    got = coord.plan(snap, budget=6)
    assert got == plan_obj


def test_plan_call_failure_returns_empty(monkeypatch, state_files):
    def _boom(*a, **k):
        raise RuntimeError("backend down")
    monkeypatch.setattr(coord, "call_sync", _boom)
    snap = coord.assess_state(**state_files)
    assert coord.plan(snap, budget=6) == []


# ── coordinator_cycle: dry-run ────────────────────────────────────────────


def test_cycle_dry_run_returns_plan_calls_no_handler(monkeypatch, state_files):
    valid_plan = [
        {"action": "run_loop_iteration", "args": {"topic": "noisy PD"}},
        {"action": "bubble_up",
         "args": {"finding_ids": ["sf-iter-2026-06-05-099"], "note": "look"}},
    ]
    monkeypatch.setattr(coord, "call_sync", _mock_call_sync_returning(valid_plan))

    called = []
    handlers = {
        name: (lambda *a, n=name, **k: called.append(n))
        for name in ("run_loop_iteration", "promote_findings", "bubble_up", "noop")
    }

    report = coord.coordinator_cycle(
        budget=6, dry_run=True, execute_handlers=handlers, **state_files,
    )
    assert report["status"] == "planned"
    assert report["dry_run"] is True
    assert [s["name"] for s in report["plan"]] == [
        "run_loop_iteration", "bubble_up",
    ]
    assert called == []  # NO handler called in dry-run
    # bubble_up summary present in the report.
    assert report["bubble_up"][0]["finding_ids"] == ["sf-iter-2026-06-05-099"]


# ── coordinator_cycle: execute ────────────────────────────────────────────


def test_cycle_execute_calls_handlers_in_order(monkeypatch, state_files):
    valid_plan = [
        {"action": "run_loop_iteration", "args": {"topic": "noisy PD"}},
        {"action": "promote_findings", "args": {"max_candidates": 2}},
        {"action": "noop", "args": {"reason": "done"}},
    ]
    monkeypatch.setattr(coord, "call_sync", _mock_call_sync_returning(valid_plan))

    order = []
    handlers = {
        "run_loop_iteration": lambda *, topic: order.append(("run", topic)) or {"status": "passed"},
        "promote_findings": lambda *, max_candidates=None: order.append(("promote", max_candidates)) or {"status": "passed"},
        "bubble_up": lambda **k: {"status": "passed"},
        "noop": lambda *, reason: order.append(("noop", reason)) or {"status": "passed"},
    }

    report = coord.coordinator_cycle(
        budget=6, dry_run=False, execute_handlers=handlers, **state_files,
    )
    assert report["status"] == "executed"
    assert order == [
        ("run", "noisy PD"), ("promote", 2), ("noop", "done"),
    ]
    assert [e["status"] for e in report["executed"]] == ["passed", "passed", "passed"]


def test_cycle_execute_handler_error_does_not_crash(monkeypatch, state_files):
    valid_plan = [{"action": "noop", "args": {"reason": "x"}}]
    monkeypatch.setattr(coord, "call_sync", _mock_call_sync_returning(valid_plan))
    handlers = {"noop": lambda **k: (_ for _ in ()).throw(RuntimeError("boom"))}
    report = coord.coordinator_cycle(
        budget=6, dry_run=False, execute_handlers=handlers, **state_files,
    )
    assert report["status"] == "executed"
    assert report["executed"][0]["status"] == "error"
    assert "boom" in report["executed"][0]["reason"]


# ── the guardrail proof: invalid plan -> replan -> no_valid_plan ──────────


def test_invalid_offmenu_plan_rejected_no_handler_called(monkeypatch, state_files):
    """An off-menu action is rejected on EVERY attempt -> no_valid_plan, and
    NO handler is ever called. This is the constrained-action-space guardrail."""
    bad_plan = [{"action": "launch_live_trade", "args": {"size": 1000}}]
    call_count = {"n": 0}

    def _stub(messages, **kwargs):
        call_count["n"] += 1
        return {"request_id": "r", "completion": json.dumps(bad_plan)}
    monkeypatch.setattr(coord, "call_sync", _stub)

    called = []
    handlers = {
        name: (lambda *a, n=name, **k: called.append(n))
        for name in ("run_loop_iteration", "promote_findings", "bubble_up", "noop")
    }

    report = coord.coordinator_cycle(
        budget=6, dry_run=False, execute_handlers=handlers, **state_files,
    )
    assert report["status"] == "no_valid_plan"
    assert called == []  # GUARDRAIL: nothing executed
    assert report["plan"] == []
    # bounded replan: initial attempt + up to 2 replans = 3 plan calls.
    assert call_count["n"] == coord._MAX_REPLANS + 1
    assert len(report["attempts"]) == coord._MAX_REPLANS + 1
    # the off-menu name shows up in the rejection errors.
    assert any("launch_live_trade" in e for e in report["errors"])


def test_invalid_then_valid_replan_succeeds(monkeypatch, state_files):
    """First plan off-menu, second plan valid -> the replan recovers."""
    plans = [
        [{"action": "do_something_off_menu", "args": {}}],
        [{"action": "noop", "args": {"reason": "recovered"}}],
    ]
    seq = iter(plans)

    def _stub(messages, **kwargs):
        return {"request_id": "r", "completion": json.dumps(next(seq))}
    monkeypatch.setattr(coord, "call_sync", _stub)

    report = coord.coordinator_cycle(
        budget=6, dry_run=True, **state_files,
    )
    assert report["status"] == "planned"
    assert [s["name"] for s in report["plan"]] == ["noop"]


def test_over_budget_plan_rejected(monkeypatch, state_files):
    """A plan whose total cost exceeds budget is rejected by the validator."""
    # run_loop_iteration costs 3 each; two of them = 6 > budget 4.
    over = [
        {"action": "run_loop_iteration", "args": {"topic": "a"}},
        {"action": "run_loop_iteration", "args": {"topic": "b"}},
    ]
    monkeypatch.setattr(coord, "call_sync", _mock_call_sync_returning(over))

    called = []
    handlers = {"run_loop_iteration": lambda **k: called.append("run")}
    report = coord.coordinator_cycle(
        budget=4, dry_run=False, execute_handlers=handlers, **state_files,
    )
    assert report["status"] == "no_valid_plan"
    assert called == []
    assert any("budget" in e for e in report["errors"])
