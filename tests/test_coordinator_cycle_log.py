"""Hermetic tests for orchestrator/coordinator_cycle_log.py (Limb C EMIT layer).

No network, no model calls, MOCK_LLM-safe: every function is either pure (the
row/health builders) or writes to a tmp_path JSONL. We feed synthetic
coordinator reports + run-log / calls-log rows and assert the EXACT UI contract
schema and the degraded-signal detection.

The load-bearing proofs:
  - a FAILED dispatch (executed status="error") becomes an explicit `outcomes`
    row with status="errored" + the error string — never a silent gap;
  - ml-intern "stored 0 papers" and Qwen "empty content" are detected from the
    iteration's run-log / calls-log evidence and written as degraded signals.
"""
from __future__ import annotations

import json

from orchestrator import coordinator_cycle_log as ccl


# ── fixtures ──────────────────────────────────────────────────────────────


def _report(*, status="executed", run_id="coordinator_abc12345",
            topic="FASE: Fast Adaptive Semantic Entropy for Code Quality",
            topic_source="arxiv_recent", executed=None, bubble_up=None):
    """A coordinator_cycle report dict shaped like coordinator._coordinator_cycle."""
    return {
        "run_id": run_id,
        "status": status,
        "dry_run": False,
        "plan": [
            {"name": "run_loop_iteration", "cost": 3,
             "args": {"topic": topic}},
            {"name": "noop", "cost": 0, "args": {"reason": "one iter is enough"}},
        ],
        "state": {"topic_suggestions": [{"topic": topic, "source": topic_source}]},
        "executed": executed if executed is not None else [
            {"action": "run_loop_iteration", "status": "passed",
             "result": {"iteration_id": "iter-2026-06-09-001"}},
            {"action": "noop", "status": "passed", "result": {"reason": "ok"}},
        ],
        "bubble_up": bubble_up if bubble_up is not None else [],
        "errors": [],
    }


# ── cycle_row_from_report (pure) ──────────────────────────────────────────


def test_row_maps_topic_plan_and_dispatched_iteration():
    row = ccl.cycle_row_from_report(_report(), timestamp="2026-06-09T00:00:00Z")
    assert row["timestamp"] == "2026-06-09T00:00:00Z"
    assert row["run_id"] == "coordinator_abc12345"
    assert row["agent"] == "coordinator"
    assert row["topic"].startswith("FASE")
    assert row["topic_source"] == "arxiv_recent"
    assert row["status"] == "executed"
    # plan rows are {action, args} only (no cost in the contract row).
    assert row["plan"][0] == {
        "action": "run_loop_iteration",
        "args": {"topic": row["topic"]},
    }
    assert "cost" not in row["plan"][0]
    # the successful run_loop_iteration's iteration_id is the join key.
    assert row["dispatched_iteration_id"] == "iter-2026-06-09-001"
    # both actions succeeded -> outcomes mirror them.
    assert row["outcomes"] == [
        {"action": "run_loop_iteration", "status": "passed"},
        {"action": "noop", "status": "passed"},
    ]
    assert row["promoted_finding_ids"] == []
    assert row["bubble_run_ids"] == []


def test_failed_dispatch_is_explicit_outcome_row_never_silent():
    """The headline 2026-06-09 fix: a failed run_loop_iteration is a ROW with
    status='errored' + the error, not an absent line."""
    rep = _report(executed=[
        {"action": "run_loop_iteration", "status": "error",
         "reason": "ValidationError: 'coordinator' is not one of the enum"},
    ])
    row = ccl.cycle_row_from_report(rep)
    assert row["outcomes"] == [{
        "action": "run_loop_iteration",
        "status": "errored",
        "error": "ValidationError: 'coordinator' is not one of the enum",
    }]
    # a failed dispatch produced no iteration -> no join key, the failure is the
    # outcome row (the contract's source of truth for dispatch outcome).
    assert "dispatched_iteration_id" not in row


def test_skipped_action_carries_reason_as_error_field():
    rep = _report(executed=[
        {"action": "run_loop_iteration", "status": "skipped",
         "reason": "budget exhausted (spent=6, cost=3, budget=6)"},
    ])
    row = ccl.cycle_row_from_report(rep)
    assert row["outcomes"][0]["status"] == "skipped"
    assert "budget exhausted" in row["outcomes"][0]["error"]


def test_promoted_finding_ids_collected_from_promote_action():
    rep = _report(executed=[
        {"action": "promote_findings", "status": "passed",
         "result": {"promoted": [
             {"finding_id": "sf-iter-2026-06-09-001"},
             {"finding_id": "sf-iter-2026-06-08-002"},
         ], "examined": 3}},
    ])
    row = ccl.cycle_row_from_report(rep)
    assert row["promoted_finding_ids"] == [
        "sf-iter-2026-06-09-001", "sf-iter-2026-06-08-002",
    ]
    # no run_loop_iteration this cycle -> no dispatched id.
    assert "dispatched_iteration_id" not in row


def test_bubble_run_ids_present_only_when_a_bubble_was_raised():
    rep = _report(bubble_up=[{"finding_ids": ["sf-x"], "note": "look at this"}])
    row = ccl.cycle_row_from_report(rep)
    assert row["bubble_run_ids"] == ["coordinator_abc12345"]


def test_no_valid_plan_report_degrades_to_a_row_with_no_outcomes():
    """A guardrail-rejected cycle (no plan executed) still produces a row so the
    UI shows 'the loop ran, planned nothing valid' rather than nothing."""
    rep = {
        "run_id": "coordinator_dead0000", "status": "no_valid_plan",
        "errors": ["off-menu action 'launch_live_trade'"],
        "plan": [], "executed": [],
        "state": {"topic_suggestions": []},
    }
    row = ccl.cycle_row_from_report(rep)
    assert row["status"] == "no_valid_plan"
    assert row["plan"] == []
    assert row["outcomes"] == []
    assert row["topic"] is None
    assert "dispatched_iteration_id" not in row


def test_unknown_status_is_not_coerced_to_pass():
    """Inviolate rule 4: an unexpected status passes through verbatim, never
    silently recoded to 'passed'."""
    rep = _report(executed=[
        {"action": "noop", "status": "weird_new_state", "reason": "huh"},
    ])
    row = ccl.cycle_row_from_report(rep)
    assert row["outcomes"][0]["status"] == "weird_new_state"


# ── health-signal detection (pure) ────────────────────────────────────────


def test_detect_ml_intern_zero_papers():
    run_log = [
        {"event_type": "loop_v0_ml_intern", "phase": "dispatch",
         "iteration_id": "iter-2026-06-09-001"},
        {"event_type": "loop_v0_ml_intern", "phase": "result",
         "iteration_id": "iter-2026-06-09-001", "status": "passed",
         "papers_stored": 0},
    ]
    sig = ccl.detect_ml_intern_zero("iter-2026-06-09-001", run_log)
    assert sig is not None
    assert sig["signal"] == "ml_intern_zero_papers"
    assert sig["severity"] == "degraded"
    assert sig["papers_stored"] == 0


def test_detect_ml_intern_no_signal_when_papers_stored():
    run_log = [
        {"event_type": "loop_v0_ml_intern", "phase": "result",
         "iteration_id": "iter-2026-06-09-001", "status": "passed",
         "papers_stored": 7},
    ]
    assert ccl.detect_ml_intern_zero("iter-2026-06-09-001", run_log) is None


def test_detect_ml_intern_no_signal_when_never_ran():
    assert ccl.detect_ml_intern_zero("iter-2026-06-09-001", []) is None


def test_detect_qwen_degraded_empty_content():
    calls = [
        {"run_id": "iter-2026-06-09-001", "model": "qwen3.6-27b-nvfp4-mtp",
         "completion": ""},
        {"run_id": "iter-2026-06-09-001", "model": "qwen3.6-27b-nvfp4-mtp",
         "completion": "   \n  "},
        {"run_id": "iter-2026-06-09-001", "model": "gemma-4-26b-a4b",
         "completion": "a real gemma answer"},  # not qwen -> ignored
    ]
    sig = ccl.detect_qwen_degraded("iter-2026-06-09-001", calls)
    assert sig is not None
    assert sig["signal"] == "qwen_degraded_empty_content"
    assert sig["empty_calls"] == 2
    assert sig["total_calls"] == 2  # only the 2 qwen rows counted


def test_detect_qwen_degraded_via_ollama_8001_endpoint():
    calls = [
        {"run_id": "iter-2026-06-09-001", "model": "served-model",
         "host_metadata": {"backend": "ollama",
                           "ollama_base_url": "http://127.0.0.1:8001/v1"},
         "completion": None},
    ]
    sig = ccl.detect_qwen_degraded("iter-2026-06-09-001", calls)
    assert sig is not None and sig["empty_calls"] == 1


def test_detect_qwen_no_signal_when_content_present():
    calls = [
        {"run_id": "iter-2026-06-09-001", "model": "qwen3.6-27b-nvfp4-mtp",
         "completion": '{"verdict": "refuted"}'},
    ]
    assert ccl.detect_qwen_degraded("iter-2026-06-09-001", calls) is None


def test_detect_qwen_no_signal_when_other_iterations_only():
    """Scoping: a different iteration's empty qwen rows must NOT flag this one."""
    calls = [
        {"run_id": "iter-2026-06-05-001", "model": "qwen3.6-27b-nvfp4-mtp",
         "completion": ""},
    ]
    assert ccl.detect_qwen_degraded("iter-2026-06-09-001", calls) is None


# ── writers (tmp_path I/O, best-effort) ───────────────────────────────────


def test_write_coordinator_cycle_appends_one_jsonl_row(tmp_path):
    path = tmp_path / "coordinator_cycles.jsonl"
    written = ccl.write_coordinator_cycle(_report(), cycles_path=str(path))
    assert written is not None
    lines = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    assert len(lines) == 1
    assert lines[0]["run_id"] == "coordinator_abc12345"
    assert lines[0]["dispatched_iteration_id"] == "iter-2026-06-09-001"
    # second cycle appends, never truncates.
    ccl.write_coordinator_cycle(_report(run_id="coordinator_def67890"),
                                cycles_path=str(path))
    lines = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    assert len(lines) == 2
    assert lines[1]["run_id"] == "coordinator_def67890"


def test_write_coordinator_cycle_never_raises_on_bad_path(tmp_path):
    # a path whose parent is a FILE (not a dir) makes mkdir/open fail; the
    # writer must swallow it and return the row it built (best-effort).
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file")
    bad = blocker / "nested" / "cycles.jsonl"
    # builder still succeeds; the write silently fails -> returns the row.
    row = ccl.write_coordinator_cycle(_report(), cycles_path=str(bad))
    assert row is not None  # did not raise
    assert not bad.exists()


def test_emit_health_signals_writes_both_when_degraded(tmp_path):
    run_log = tmp_path / "run.jsonl"
    calls = tmp_path / "calls.jsonl"
    health = tmp_path / "health_signals.jsonl"
    run_log.write_text(json.dumps({
        "event_type": "loop_v0_ml_intern", "phase": "result",
        "iteration_id": "iter-2026-06-09-001", "status": "passed",
        "papers_stored": 0,
    }) + "\n")
    calls.write_text(json.dumps({
        "run_id": "iter-2026-06-09-001", "model": "qwen3.6-27b-nvfp4-mtp",
        "completion": "",
    }) + "\n")

    sigs = ccl.emit_health_signals(
        _report(), health_path=str(health),
        run_log_path=str(run_log), calls_log_path=str(calls),
    )
    names = {s["signal"] for s in sigs}
    assert names == {"ml_intern_zero_papers", "qwen_degraded_empty_content"}
    rows = [json.loads(line) for line in health.read_text().splitlines() if line.strip()]
    assert len(rows) == 2
    assert all(r["run_id"] == "coordinator_abc12345" for r in rows)
    assert all("timestamp" in r for r in rows)


def test_emit_health_signals_stall_when_no_dispatch(tmp_path):
    """P0 (LOOP_V1, replaces the pre-D-059 no-dispatch noop pin): a cycle
    that dispatched nothing, promoted nothing, and moved no ledger cluster
    now emits a loop_stalled signal and a RED alert flag — the 2026-08-05..14
    zombie ran 20 such cycles with the health channel structurally silent."""
    health = tmp_path / "health_signals.jsonl"
    flag = tmp_path / "loop_alert.json"
    rep = _report(executed=[
        {"action": "noop", "status": "passed", "result": {}},
    ])
    sigs = ccl.emit_health_signals(rep, health_path=str(health),
                                   run_log_path=str(tmp_path / "nope.jsonl"),
                                   calls_log_path=str(tmp_path / "nope2.jsonl"),
                                   alert_flag_path=str(flag))
    assert len(sigs) == 1
    assert sigs[0]["signal"] == "loop_stalled"
    assert health.exists()
    payload = json.loads(flag.read_text())
    assert payload["level"] == "red"
    assert "loop_stalled" in payload["reasons"]


def test_emit_health_signals_ok_flag_on_active_cycle(tmp_path):
    """An iteration-dispatching cycle with healthy detectors writes an OK
    flag (the alert surface always reflects the latest cycle)."""
    health = tmp_path / "health_signals.jsonl"
    flag = tmp_path / "loop_alert.json"
    rep = _report(executed=[
        {"action": "run_loop_iteration", "status": "passed",
         "result": {"iteration_id": "iter-2026-08-14-001"}},
    ])
    sigs = ccl.emit_health_signals(rep, health_path=str(health),
                                   run_log_path=str(tmp_path / "nope.jsonl"),
                                   calls_log_path=str(tmp_path / "nope2.jsonl"),
                                   alert_flag_path=str(flag))
    assert sigs == []
    assert json.loads(flag.read_text())["level"] == "ok"


def test_emit_health_signals_no_signal_when_healthy(tmp_path):
    run_log = tmp_path / "run.jsonl"
    calls = tmp_path / "calls.jsonl"
    health = tmp_path / "health_signals.jsonl"
    run_log.write_text(json.dumps({
        "event_type": "loop_v0_ml_intern", "phase": "result",
        "iteration_id": "iter-2026-06-09-001", "status": "passed",
        "papers_stored": 5,
    }) + "\n")
    calls.write_text(json.dumps({
        "run_id": "iter-2026-06-09-001", "model": "qwen3.6-27b-nvfp4-mtp",
        "completion": '{"verdict": "stands"}',
    }) + "\n")
    sigs = ccl.emit_health_signals(_report(), health_path=str(health),
                                   run_log_path=str(run_log), calls_log_path=str(calls))
    assert sigs == []
    assert not health.exists()
