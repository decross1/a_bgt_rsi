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
from datetime import datetime, timedelta, timezone

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


# ── gated cycles are not stalls (2026-08-19 false-alarm fix) ──────────────


def _refusal(status, run_id="coordinator_9f92accc", gate_reason=None):
    """The report a coordinator gate refusal returns (coordinator.py:997 /
    :1022): a status + errors, NO plan and NO executed actions."""
    rep = {"run_id": run_id, "status": status,
           "errors": [f"refused: {status}"],
           "plan": [], "executed": [], "bubble_up": [], "attempts": []}
    if gate_reason is not None:
        rep["gate_reason"] = gate_reason
    return rep


def _emit(tmp_path, rep, flag_name="loop_alert.json", now=None):
    health = tmp_path / "health_signals.jsonl"
    flag = tmp_path / flag_name
    sigs = ccl.emit_health_signals(rep, health_path=str(health),
                                   run_log_path=str(tmp_path / "nope.jsonl"),
                                   calls_log_path=str(tmp_path / "nope2.jsonl"),
                                   frontier_calls_path=str(tmp_path / "nope3.jsonl"),
                                   alert_flag_path=str(flag), now=now)
    return sigs, json.loads(flag.read_text()), health


def test_budget_refusal_emits_loop_gated_not_loop_stalled(tmp_path):
    """THE 2026-08-19 regression pin. The 03:32:39Z RED came from THIS path:
    the daemon woke on its heartbeat, the coordinator's elapsed-share budget
    gate refused (executed=[]), and emit_health_signals read that emptiness
    as loop_stalled — while the loop had run iterations at 02:00/02:54/03:00
    and the owner was mid finding-session."""
    sigs, payload, health = _emit(
        tmp_path, _refusal("daily_budget_paced", gate_reason="budget"))
    names = [s["signal"] for s in sigs]
    assert names == ["loop_gated:budget"]
    assert "loop_stalled" not in names
    assert payload["level"] == "ok"          # NOT red
    assert payload["gate"]["reason"] == "budget"
    assert payload["gate"]["status"] == "daily_budget_paced"
    assert "DELIBERATELY idle" in payload["gate"]["detail"]
    # The signal is a first-class health row, not a swallowed one.
    rows = [json.loads(l) for l in health.read_text().splitlines() if l.strip()]
    assert [r["signal"] for r in rows] == ["loop_gated:budget"]
    assert rows[0]["run_id"] == "coordinator_9f92accc"
    assert rows[0]["severity"] == "gated"


def test_paused_gate_is_amber_and_named(tmp_path):
    """A HOLD an operator should see named, not read as silence — but still
    never (at birth) the red that means "the loop was free and did nothing"."""
    _, payload, _ = _emit(tmp_path, _refusal("paused"))
    assert payload["level"] == "amber"
    assert payload["gate"]["reason"] == "paused"
    assert "loop_gated:paused" in payload["reasons"]


def test_gated_cycle_still_reports_a_real_degraded_signal_as_amber(tmp_path):
    """Being held does not make a broken component healthy: a dead frontier
    vendor still wins amber over the gate's own "ok"."""
    health = tmp_path / "health_signals.jsonl"
    flag = tmp_path / "loop_alert.json"
    frontier = tmp_path / "frontier_calls.jsonl"
    frontier.write_text("".join(
        json.dumps({"vendor": "codex", "exit_code": 1,
                    "timestamp": f"2026-08-19T0{i}:00:00Z"}) + "\n"
        for i in range(3)))
    sigs = ccl.emit_health_signals(
        _refusal("daily_budget_paced", gate_reason="budget"),
        health_path=str(health),
        run_log_path=str(tmp_path / "nope.jsonl"),
        calls_log_path=str(tmp_path / "nope2.jsonl"),
        frontier_calls_path=str(frontier),
        alert_flag_path=str(flag))
    names = {s["signal"] for s in sigs}
    assert names == {"frontier_vendor_down:codex", "loop_gated:budget"}
    payload = json.loads(flag.read_text())
    assert payload["level"] == "amber"
    assert payload["gate"]["reason"] == "budget"   # the reason is still named


def test_free_cycle_flag_carries_no_gate_key(tmp_path):
    """The gate marker is never sticky — an ordinary cycle's flag omits it."""
    _, payload, _ = _emit(tmp_path, _report(executed=[
        {"action": "run_loop_iteration", "status": "passed",
         "result": {"iteration_id": "iter-2026-08-19-001"}}]))
    assert payload["level"] == "ok"
    assert "gate" not in payload


def test_empty_pool_promote_cycle_is_still_red(tmp_path):
    """The 2026-08-18 stall stays a stall: that cycle was FREE to act."""
    _, payload, _ = _emit(tmp_path, _report(executed=[
        {"action": "promote_findings", "status": "passed",
         "result": {"promoted": []}}]))
    assert payload["level"] == "red"
    assert "loop_stalled" in payload["reasons"]
    assert "gate" not in payload


def test_unrecognized_gate_reason_is_not_a_red_suppressor(tmp_path):
    """NB1 at the emit layer: a stray gate_reason on an otherwise-idle report
    must NOT buy an exemption from the loop's only red signal."""
    _, payload, _ = _emit(tmp_path, _refusal("no_valid_plan",
                                             gate_reason="whatever"))
    assert payload["level"] == "red"
    assert "loop_stalled" in payload["reasons"]
    assert "gate" not in payload


# ── B1: a gate that never clears escalates by AGE ────────────────────────

_DAY0 = datetime(2026, 8, 19, 0, 0, tzinfo=timezone.utc)


def _executed_cycle():
    return _report(executed=[
        {"action": "run_loop_iteration", "status": "passed",
         "result": {"iteration_id": "iter-2026-08-19-001"}}])


def test_a_day_of_nothing_but_budget_refusals_goes_amber_then_red(tmp_path):
    """B1 — THE false-green pin (2026-08-19 review).

    Before this fix the budget gate was the only reachable gate, it wrote a
    fresh level "ok" with a fresh updated_at on EVERY wake, the banner renders
    nothing for a fresh ok, and its only cross-cycle backstop (STALE_AFTER_MS,
    26h) keys off the very field the refusal path kept refreshing. So a
    coordinator wedged at its cap — a stuck ledger, a bug in
    _budget_allowance, a misread cap — refused all day and looked perfect.
    Silence is not the reward for being stuck: 24 hourly refusals and NOT ONE
    executed cycle must escalate ok -> amber (3h) -> red (12h)."""
    levels = []
    for hour in range(24):
        _, payload, _ = _emit(
            tmp_path, _refusal("daily_budget_paced", gate_reason="budget"),
            now=_DAY0 + timedelta(hours=hour))
        levels.append(payload["level"])
        # The flag keeps naming the gate the whole way — never a bare alarm.
        assert payload["gate"]["reason"] == "budget"
        assert payload["gate"]["consecutive"] == hour + 1
        assert payload["gate"]["first_gated_at"] == _DAY0.isoformat()

    assert levels[0:3] == ["ok", "ok", "ok"]           # < 3h: routine pacing
    assert levels[3:12] == ["amber"] * 9               # >= 3h: held too long
    assert levels[12:24] == ["red"] * 12               # >= 12h: not moving
    # And the red EXPLAINS itself (the owner's whole complaint was a red with
    # no explanation) — the escalation line rides in `reasons`.
    _, payload, _ = _emit(
        tmp_path, _refusal("daily_budget_paced", gate_reason="budget"),
        now=_DAY0 + timedelta(hours=24))
    escalation = [r for r in payload["reasons"] if "budget gate" in r]
    assert len(escalation) == 1
    assert "24.0h" in escalation[0]
    assert "NO cycle has executed" in escalation[0]
    assert payload["gate"]["age_s"] == 24 * 3600


def test_a_normal_mixed_day_stays_ok(tmp_path):
    """The other half of B1: refusals INTERLEAVED with executed cycles are the
    schedule working as designed. An executed cycle writes no gate block at
    all, which resets the clock — so a healthy loop never accumulates an
    escalation, no matter how many refusals it logs along the way."""
    levels = []
    for hour in range(24):
        # Two refusals for every executed cycle — normal pacing.
        report = (_executed_cycle() if hour % 3 == 2
                  else _refusal("daily_budget_paced", gate_reason="budget"))
        _, payload, _ = _emit(tmp_path, report,
                              now=_DAY0 + timedelta(hours=hour))
        levels.append(payload["level"])
        if "gate" in payload:
            # No refusal run ever gets old enough to escalate.
            assert payload["gate"]["age_s"] < 3 * 3600
    assert set(levels) == {"ok"}


def test_escalation_clears_the_moment_a_real_cycle_executes(tmp_path):
    """A red earned by age must not outlive the condition that earned it."""
    for hour in range(20):
        _, payload, _ = _emit(
            tmp_path, _refusal("daily_budget_paced", gate_reason="budget"),
            now=_DAY0 + timedelta(hours=hour))
    assert payload["level"] == "red"
    # The loop moves.
    _, payload, _ = _emit(tmp_path, _executed_cycle(),
                          now=_DAY0 + timedelta(hours=20))
    assert payload["level"] == "ok" and "gate" not in payload
    # The next refusal starts a FRESH clock, not a resumed one.
    _, payload, _ = _emit(
        tmp_path, _refusal("daily_budget_paced", gate_reason="budget"),
        now=_DAY0 + timedelta(hours=21))
    assert payload["level"] == "ok"
    assert payload["gate"]["consecutive"] == 1
    assert payload["gate"]["age_s"] == 0


def test_aged_gate_outranks_a_merely_degraded_signal(tmp_path):
    """Worst-of, never a downgrade: a 13h-held loop stays red even on a cycle
    that also carries an ordinary amber degraded signal."""
    frontier = tmp_path / "frontier_calls.jsonl"
    frontier.write_text("".join(
        json.dumps({"vendor": "codex", "exit_code": 1,
                    "timestamp": f"2026-08-19T0{i}:00:00Z"}) + "\n"
        for i in range(3)))
    health = tmp_path / "health_signals.jsonl"
    flag = tmp_path / "loop_alert.json"
    for hour in (0, 13):
        ccl.emit_health_signals(
            _refusal("daily_budget_paced", gate_reason="budget"),
            health_path=str(health),
            run_log_path=str(tmp_path / "nope.jsonl"),
            calls_log_path=str(tmp_path / "nope2.jsonl"),
            frontier_calls_path=str(frontier),
            alert_flag_path=str(flag),
            now=_DAY0 + timedelta(hours=hour))
    payload = json.loads(flag.read_text())
    assert payload["level"] == "red"
    assert "frontier_vendor_down:codex" in payload["reasons"]


# ── B2: the paused gate reaches a reader END TO END ──────────────────────


def test_pause_file_refusal_writes_a_named_gate_flag(tmp_path, monkeypatch):
    """B2 — the dead-gate fix, proven through the REAL coordinator entry
    point. gate_reason "paused" was stamped at coordinator.py:1001 and then
    thrown away: that branch wrote its cycle row and returned WITHOUT calling
    emit_health_signals, so no reader could ever see it. Now the pause-file
    refusal writes the flag it always claimed to."""
    from orchestrator import coordinator as co

    pause = tmp_path / "pause_coordinator"
    pause.write_text("")
    monkeypatch.setattr(co, "PAUSE_PATH", pause)
    monkeypatch.setattr(ccl, "DEFAULT_HEALTH_PATH",
                        tmp_path / "health_signals.jsonl")
    monkeypatch.setattr(ccl, "DEFAULT_CYCLES_PATH",
                        tmp_path / "coordinator_cycles.jsonl")
    called = {"plan": False}
    monkeypatch.setattr(
        co, "plan", lambda *a, **k: called.__setitem__("plan", True) or [])

    report = co.coordinator_cycle(
        dry_run=False,
        loop_memory_path=tmp_path / "loop_memory.jsonl",
        surfaced_path=tmp_path / "surfaced.jsonl",
        feedback_path=tmp_path / "feedback.jsonl",
        active_run_path=tmp_path / "active_run.json")

    assert report["status"] == "paused"
    assert report["gate_reason"] == "paused"
    assert called["plan"] is False          # still halted BEFORE any LLM call
    payload = json.loads((tmp_path / "loop_alert.json").read_text())
    assert payload["level"] == "amber"
    assert payload["gate"]["reason"] == "paused"
    assert payload["gate"]["status"] == "paused"
    assert payload["gate"]["consecutive"] == 1
    assert "loop_gated:paused" in payload["reasons"]
    assert "loop_stalled" not in payload["reasons"]
