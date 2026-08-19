"""Hermetic tests for orchestrator/loop_health.py (LOOP_V1 P0, A8).

No network, no model calls, no real run_state/ — the clock is injected into
staleness_gap and the alert flag writes only under tmp_path. The load-bearing
proofs:
  - staleness is judged against the INJECTED clock (never wall time);
  - detect_stall fires ONLY when all three axes are zero (truth table);
  - a missing/invalid flag file exits 2 — absence is never a silent green;
  - write_alert_flag rejects bad levels (ValueError, never coerced).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from orchestrator import loop_health as lh


NOW = datetime(2026, 8, 14, 12, 0, 0, tzinfo=timezone.utc)


def _row(iteration_id="iter-x", ended_at=None, started_at=None):
    row = {"iteration_id": iteration_id}
    if ended_at is not None:
        row["ended_at"] = ended_at
    if started_at is not None:
        row["started_at"] = started_at
    return row


# ── staleness_gap ─────────────────────────────────────────────────────────


def test_staleness_fresh_iteration_is_none():
    rows = [_row(ended_at=(NOW - timedelta(hours=6)).isoformat())]
    assert lh.staleness_gap(rows, NOW) is None


def test_staleness_gap_fires_at_bar():
    ts = (NOW - timedelta(days=3, hours=2)).isoformat()
    msg = lh.staleness_gap([_row("iter-old", ended_at=ts)], NOW)
    assert msg is not None
    assert "3 days" in msg
    assert "iter-old" in msg


def test_staleness_exactly_at_stale_days_fires():
    ts = (NOW - timedelta(days=lh.STALE_DAYS)).isoformat()
    assert lh.staleness_gap([_row(ended_at=ts)], NOW) is not None


def test_staleness_uses_latest_row_not_first():
    rows = [
        _row("iter-old", ended_at=(NOW - timedelta(days=10)).isoformat()),
        _row("iter-new", ended_at=(NOW - timedelta(hours=1)).isoformat()),
    ]
    assert lh.staleness_gap(rows, NOW) is None


def test_staleness_z_suffix_and_started_at_fallback():
    ts = (NOW - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    assert lh.staleness_gap([_row(started_at=ts)], NOW) is None


def test_staleness_empty_rows_reports_never_iterated():
    msg = lh.staleness_gap([], NOW)
    assert msg is not None
    assert "never iterated" in msg


def test_staleness_unparseable_timestamps_reported_not_coerced():
    msg = lh.staleness_gap([_row(ended_at="not-a-date"), _row()], NOW)
    assert msg is not None
    assert "parseable" in msg


def test_staleness_naive_now_accepted():
    rows = [_row(ended_at=(NOW - timedelta(hours=1)).isoformat())]
    assert lh.staleness_gap(rows, NOW.replace(tzinfo=None)) is None


# ── ladder_gaps ───────────────────────────────────────────────────────────


def _cluster(cid, status="open", level="L1"):
    return {"cluster_id": cid, "status": status, "evidence_level": level}


def test_ladder_gaps_counts_open_by_level_in_order():
    state = {
        "c1": _cluster("c1", level="L3"),
        "c2": _cluster("c2", level="L3"),
        "c3": _cluster("c3", level="L1"),
    }
    gaps = lh.ladder_gaps(state)
    assert len(gaps) == 2
    assert gaps[0].startswith("1 open cluster(s) at L1")
    assert gaps[1].startswith("2 open cluster(s) at L3")
    assert "adversarial battery" in gaps[1]


def test_ladder_gaps_excludes_killed_surfaced_and_l5():
    state = {
        "c1": _cluster("c1", status="killed", level="L2"),
        "c2": _cluster("c2", status="surfaced", level="L4"),
        "c3": _cluster("c3", status="open", level="L5"),
    }
    assert lh.ladder_gaps(state) == []


def test_ladder_gaps_unknown_level_reported():
    state = {"c1": _cluster("c1", level="L9"), "c2": _cluster("c2", level=None)}
    gaps = lh.ladder_gaps(state)
    assert len(gaps) == 1
    assert "2 open cluster(s) with missing/unknown evidence_level" in gaps[0]


def test_ladder_gaps_empty_state():
    assert lh.ladder_gaps({}) == []


# ── detect_stall truth table ─────────────────────────────────────────────


def _report(executed):
    return {"run_id": "coordinator_test", "status": "executed",
            "executed": executed}


def test_stall_fires_when_all_three_axes_zero():
    report = _report([{"action": "noop", "status": "passed"}])
    out = lh.detect_stall(report, 0)
    assert out is not None
    assert out["signal"] == "loop_stalled"
    assert out["severity"] == "stalled"
    assert "coordinator_test" in out["detail"]


@pytest.mark.parametrize(
    "executed,ledger_events",
    [
        ([{"action": "run_loop_iteration", "status": "passed"}], 0),
        ([{"action": "run_loop_iteration", "status": "error"}], 0),  # attempt = activity
        # promote_findings counts only via ACTUAL promotions — the zombie pin.
        ([{"action": "promote_findings", "status": "passed",
           "result": {"promoted": [{"finding_id": "sf-x"}]}}], 0),
        ([], 1),
    ],
)
def test_stall_none_when_any_axis_active(executed, ledger_events):
    assert lh.detect_stall(_report(executed), ledger_events) is None


def test_stall_none_on_other_substantive_actions():
    """False-RED pin (2026-08-14 review): a cycle executing run_experiment /
    mine_paper_gap / forecast_markets — exactly what the D-059 planner
    orders for ladder gaps — is ACTIVE, not stalled."""
    for action in ("run_experiment", "mine_paper_gap", "forecast_markets",
                   "bubble_up"):
        report = _report([{"action": action, "status": "passed"}])
        assert lh.detect_stall(report, 0) is None, action


def test_stall_fires_on_empty_pool_promote_pass():
    """The 2026-08-05..14 zombie shape: promote_findings executed + 'passed'
    but promoted NOTHING, no iteration, no ledger movement -> stalled."""
    report = _report([{"action": "promote_findings", "status": "passed",
                       "result": {"promoted": []}}])
    out = lh.detect_stall(report, 0)
    assert out is not None and out["signal"] == "loop_stalled"


def test_stall_fires_on_empty_report():
    out = lh.detect_stall({}, 0)
    assert out is not None
    assert out["signal"] == "loop_stalled"


# ── gated vs stalled (2026-08-19 false-alarm fix) ────────────────────────


def _refusal(status, *, gate_reason=None, run_id="coordinator_9f92accc"):
    """The exact shape a coordinator gate refusal returns: a status, an
    errors line, and NO executed actions (coordinator.py:997/1022)."""
    report = {"run_id": run_id, "status": status,
              "errors": [f"refused: {status}"],
              "plan": [], "executed": [], "bubble_up": [], "attempts": []}
    if gate_reason is not None:
        report["gate_reason"] = gate_reason
    return report


@pytest.mark.parametrize("status,reason", [
    ("daily_budget_paced", "budget"),
    ("daily_budget_exhausted", "budget"),
    ("paused", "paused"),
])
def test_gate_reason_from_status(status, reason):
    assert lh.gate_reason(_refusal(status)) == reason


def test_gate_reason_enum_is_frozen_to_reasons_with_producers():
    """B2/NB1 (2026-08-19 review). Every reason the module will honor must
    have a live producer that REACHES emit_health_signals:
      budget -> coordinator.py's daily-budget gate,
      paused -> coordinator.py's pause-file kill switch.
    "lock"/"active_run" were deleted: flock contention is resolved in bash
    (cron Gate 1 -> exit 0, no Python) and in nara_daemon._run_pass (Gate 1
    -> "skipped:flock"), both of which return BEFORE any report exists."""
    assert set(lh._GATE_REASONS) == {"budget", "paused"}
    assert set(lh._GATE_REASON_BY_STATUS.values()) <= set(lh._GATE_REASONS)
    assert set(lh._GATE_LEVEL) == set(lh._GATE_REASONS)
    assert set(lh._GATE_DETAIL) == set(lh._GATE_REASONS)
    for status in ("lock_held", "active_run_held"):
        assert lh.gate_reason(_refusal(status)) is None


def test_gate_reason_prefers_explicit_field():
    """The coordinator stamps gate_reason directly; it wins over the map."""
    rep = _refusal("some_new_refusal_status", gate_reason="paused")
    assert lh.gate_reason(rep) == "paused"


def test_unrecognized_gate_reason_does_not_suppress_the_stall_signal(capsys):
    """NB1 — THE red-suppressor pin. gate_reason() used to return ANY truthy
    string and detect_stall bails on a non-None reason, so one stray key on a
    report permanently exempted it from the loop's only red signal. An
    unrecognized reason is now neither honored nor swallowed (rule 4): it is
    logged and the report falls through to the normal stall path."""
    rep = _refusal("weird", gate_reason="quota_exhausted")
    assert lh.gate_reason(rep) is None
    err = capsys.readouterr().err
    assert "quota_exhausted" in err and "unrecognized gate_reason" in err
    out = lh.detect_stall(rep, 0)
    assert out is not None and out["signal"] == "loop_stalled"
    assert lh.detect_gated(rep) is None


def test_unrecognized_gate_reason_still_falls_back_to_a_known_status():
    """Falling THROUGH is not dropping: a bogus explicit reason on a report
    whose status IS a known gate still resolves to that gate."""
    rep = _refusal("daily_budget_paced", gate_reason="typo_here")
    assert lh.gate_reason(rep) == "budget"


def test_gate_reason_none_for_a_real_cycle():
    assert lh.gate_reason(_report([{"action": "noop", "status": "passed"}])) is None
    assert lh.gate_reason({}) is None
    assert lh.gate_reason("not a dict") is None


@pytest.mark.parametrize("status", [
    "daily_budget_paced", "daily_budget_exhausted", "paused",
])
def test_gated_cycle_never_emits_loop_stalled(status):
    """THE regression pin. 2026-08-19T03:32:39Z: the daemon's heartbeat wake
    hit the coordinator's elapsed-share budget gate, the refusal report
    carried executed=[], and detect_stall read that emptiness as a stall —
    RED "loop_stalled" while the loop had iterated at 02:00/02:54/03:00 and
    the owner was mid finding-session."""
    assert lh.detect_stall(_refusal(status), 0) is None


@pytest.mark.parametrize("status,reason,level", [
    ("daily_budget_paced", "budget", "ok"),
    ("daily_budget_exhausted", "budget", "ok"),
    ("paused", "paused", "amber"),
])
def test_detect_gated_signal_reason_and_level(status, reason, level):
    out = lh.detect_gated(_refusal(status))
    assert out is not None
    assert out["signal"] == f"loop_gated:{reason}"
    assert out["reason"] == reason
    assert out["severity"] == "gated"
    assert out["level"] == level
    assert out["level"] != "red"          # a held cycle is never an alarm
    assert out["cycle_status"] == status
    assert "DELIBERATELY idle" in out["detail"]
    assert f"refused: {status}" in out["detail"]   # the gate's own words


def test_detect_gated_is_none_for_a_free_cycle():
    assert lh.detect_gated(_report([{"action": "noop", "status": "passed"}])) is None
    assert lh.detect_gated({}) is None


def test_empty_pool_promote_stall_survives_the_gated_carve_out():
    """The legitimate stall from 2026-08-18 stays a stall: that cycle was
    FREE to act (status 'executed'), planned promote_findings, and promoted
    nothing. The gated carve-out must not weaken it."""
    rep = _report([{"action": "promote_findings", "status": "passed",
                    "result": {"promoted": []}}])
    assert lh.gate_reason(rep) is None
    out = lh.detect_stall(rep, 0)
    assert out is not None and out["signal"] == "loop_stalled"


# ── gate AGE escalation (2026-08-19 review B1) ───────────────────────────

T0 = datetime(2026, 8, 19, 0, 0, tzinfo=timezone.utc)


def _flag_with_gate(gate):
    return {"level": "ok", "reasons": [], "updated_at": T0.isoformat(),
            "gate": gate}


def test_gate_continuity_starts_the_clock_when_there_is_no_prior_gate():
    gated = lh.detect_gated(_refusal("daily_budget_paced"))
    out = lh.gate_continuity(None, gated, T0)
    assert out["first_gated_at"] == T0.isoformat()
    assert out["consecutive"] == 1
    assert out["age_s"] == 0
    assert out["level"] == "ok"          # a FRESH budget gate is routine
    assert out["escalated"] is False
    assert lh.gate_escalation_reason(out) is None


@pytest.mark.parametrize("hours,level,escalated", [
    (0.5, "ok", False),
    (2.9, "ok", False),
    (3.0, "amber", True),      # GATE_AMBER_AFTER_S
    (11.9, "amber", True),
    (12.0, "red", True),       # GATE_RED_AFTER_S
    (30.0, "red", True),
])
def test_gate_continuity_escalates_by_age(hours, level, escalated):
    """B1 — the false-green pin at the unit level. A budget gate that never
    clears is the loop not moving; its level must climb with its AGE, not sit
    at the base "ok" forever just because each individual refusal is routine."""
    gated = lh.detect_gated(_refusal("daily_budget_paced"))
    prev = _flag_with_gate({"reason": "budget", "consecutive": 4,
                            "first_gated_at": T0.isoformat()})
    out = lh.gate_continuity(prev, gated, T0 + timedelta(hours=hours))
    assert out["level"] == level
    assert out["escalated"] is escalated
    assert out["consecutive"] == 5
    assert out["first_gated_at"] == T0.isoformat()   # clock is NOT restarted
    assert out["age_s"] == int(hours * 3600)


def test_gate_continuity_never_downgrades_below_the_base_level():
    """paused is amber at birth; an age below the amber bar must not read it
    back down to the budget gate's "ok"."""
    gated = lh.detect_gated(_refusal("paused"))
    prev = _flag_with_gate({"reason": "paused", "consecutive": 1,
                            "first_gated_at": T0.isoformat()})
    out = lh.gate_continuity(prev, gated, T0 + timedelta(minutes=10))
    assert out["level"] == "amber"


def test_gate_continuity_restarts_when_the_reason_changes():
    """A different gate is a different hold — it does not inherit the last
    one's age (that would fabricate an escalation nobody earned)."""
    gated = lh.detect_gated(_refusal("paused"))
    prev = _flag_with_gate({"reason": "budget", "consecutive": 20,
                            "first_gated_at": T0.isoformat()})
    out = lh.gate_continuity(prev, gated, T0 + timedelta(hours=20))
    assert out["first_gated_at"] == (T0 + timedelta(hours=20)).isoformat()
    assert out["consecutive"] == 1
    assert out["age_s"] == 0


@pytest.mark.parametrize("prev", [
    None, {}, {"level": "ok"}, {"gate": "not-a-dict"},
    {"gate": {"reason": "budget"}},                     # no first_gated_at
    {"gate": {"reason": "budget", "first_gated_at": "junk"}},
    {"gate": {"reason": "budget", "first_gated_at": None,
              "consecutive": "many"}},
])
def test_gate_continuity_restarts_rather_than_inventing_an_age(prev):
    """An absent/unreadable prior clock restarts at `now`. It never fabricates
    a first_gated_at it cannot read (rule 4) — and never crashes the cycle's
    own bookkeeping either."""
    gated = lh.detect_gated(_refusal("daily_budget_paced"))
    out = lh.gate_continuity(prev, gated, T0)
    assert out["first_gated_at"] == T0.isoformat()
    assert out["consecutive"] == 1
    assert out["age_s"] == 0


def test_gate_escalation_reason_names_the_gate_the_age_and_the_count():
    gated = lh.detect_gated(_refusal("daily_budget_paced"))
    prev = _flag_with_gate({"reason": "budget", "consecutive": 12,
                            "first_gated_at": T0.isoformat()})
    out = lh.gate_continuity(prev, gated, T0 + timedelta(hours=13))
    line = lh.gate_escalation_reason(out)
    assert line is not None
    assert "budget" in line and "13.0h" in line and "13 consecutive" in line
    assert "NO cycle has executed" in line


def test_gate_continuity_accepts_a_naive_clock():
    """The clock is injected; a naive stamp is read as UTC rather than
    exploding mid-cycle on a tz-aware subtraction."""
    gated = lh.detect_gated(_refusal("daily_budget_paced"))
    naive = datetime(2026, 8, 19, 13, 0)
    out = lh.gate_continuity(_flag_with_gate(
        {"reason": "budget", "consecutive": 1,
         "first_gated_at": T0.isoformat()}), gated, naive)
    assert out["age_s"] == 13 * 3600
    assert out["level"] == "red"


def test_worse_picks_the_more_severe_level():
    assert lh.worse("ok", "amber") == "amber"
    assert lh.worse("red", "amber") == "red"
    assert lh.worse("amber", "amber") == "amber"
    assert lh.worse("ok", "ok") == "ok"


# ── write_alert_flag ─────────────────────────────────────────────────────


def test_write_alert_flag_shape_and_transitions(tmp_path):
    flag = tmp_path / "loop_alert.json"
    lh.write_alert_flag(flag, "ok", [])
    data = json.loads(flag.read_text())
    assert data["level"] == "ok"
    assert data["reasons"] == []
    assert "updated_at" in data
    # transition ok -> red overwrites in place
    lh.write_alert_flag(flag, "red", ["loop_stalled"])
    data = json.loads(flag.read_text())
    assert data["level"] == "red"
    assert data["reasons"] == ["loop_stalled"]
    assert not (tmp_path / "loop_alert.json.tmp").exists()


@pytest.mark.parametrize("level", ["green", "RED", "", None])
def test_write_alert_flag_rejects_bad_level(tmp_path, level):
    with pytest.raises(ValueError):
        lh.write_alert_flag(tmp_path / "f.json", level, [])


def test_write_alert_flag_rejects_bad_reasons(tmp_path):
    with pytest.raises(ValueError):
        lh.write_alert_flag(tmp_path / "f.json", "ok", "not-a-list")


def test_write_alert_flag_gate_is_additive_and_not_sticky(tmp_path):
    """The gate block rides ALONGSIDE the pre-existing three fields (the UI
    backend returns the flag verbatim, so a new key must not displace one),
    and a later free-running cycle clears it by simply not writing it."""
    flag = tmp_path / "loop_alert.json"
    lh.write_alert_flag(flag, "ok", ["loop_gated:budget"],
                        gate={"reason": "budget", "status": "daily_budget_paced",
                              "detail": "on its ration"})
    data = json.loads(flag.read_text())
    assert data["level"] == "ok"
    assert data["reasons"] == ["loop_gated:budget"]
    assert "updated_at" in data
    assert data["gate"] == {"reason": "budget", "status": "daily_budget_paced",
                            "detail": "on its ration"}
    # Next cycle runs free: no gate key at all (never a stale "idle" marker).
    lh.write_alert_flag(flag, "ok", [])
    assert "gate" not in json.loads(flag.read_text())


@pytest.mark.parametrize("gate", ["budget", {}, {"reason": ""},
                                  {"reason": 3}, []])
def test_write_alert_flag_rejects_bad_gate(tmp_path, gate):
    with pytest.raises(ValueError):
        lh.write_alert_flag(tmp_path / "f.json", "ok", [], gate=gate)


# ── CLI --check exit codes ───────────────────────────────────────────────


@pytest.mark.parametrize("level,code", [("ok", 0), ("amber", 1), ("red", 2)])
def test_cli_check_exit_by_level(tmp_path, level, code):
    flag = tmp_path / "loop_alert.json"
    lh.write_alert_flag(flag, level, ["r"] if level != "ok" else [])
    assert lh.main(["--check", "--flag", str(flag)]) == code


def test_cli_check_missing_flag_exits_red(tmp_path):
    assert lh.main(["--check", "--flag", str(tmp_path / "absent.json")]) == 2


def test_cli_check_malformed_flag_exits_red(tmp_path):
    flag = tmp_path / "bad.json"
    flag.write_text("{not json")
    assert lh.main(["--check", "--flag", str(flag)]) == 2


def test_cli_check_invalid_level_exits_red(tmp_path):
    flag = tmp_path / "weird.json"
    flag.write_text(json.dumps({"level": "green", "reasons": []}))
    assert lh.main(["--check", "--flag", str(flag)]) == 2


def test_cli_without_check_exits_nonzero():
    assert lh.main([]) == 2


# ── frontier vendor health (2026-08-16, D-068) ──────────────────────────────

def _fc(vendor, code, ts="2026-08-16T01:00:00Z"):
    return {"timestamp": ts, "vendor": vendor, "exit_code": code}


def test_frontier_vendor_down_after_a_streak_of_nonzero_exits():
    rows = [_fc("codex", 0, "2026-08-15T19:30:02Z"),
            _fc("codex", 1, "2026-08-16T01:55:44Z"),
            _fc("codex", 1, "2026-08-16T01:56:08Z"),
            _fc("codex", 1, "2026-08-16T01:56:36Z"),
            _fc("claude", 0), _fc("claude", 0), _fc("claude", 0)]
    sigs = lh.detect_frontier_vendor_down(rows)
    assert [s["signal"] for s in sigs] == ["frontier_vendor_down:codex"]
    assert sigs[0]["severity"] == "degraded"
    # The detail must carry the last CLEAN call, so the outage window is
    # readable without re-deriving it from the ledger.
    assert "2026-08-15T19:30:02Z" in sigs[0]["detail"]


def test_one_clean_call_inside_the_window_clears_the_vendor():
    rows = [_fc("codex", 1), _fc("codex", 0), _fc("codex", 1)]
    assert lh.detect_frontier_vendor_down(rows) == []


def test_too_few_judgeable_rows_is_not_health():
    """Under the streak length there is not enough evidence either way — and
    'not enough evidence' is never reported as healthy OR as down."""
    assert lh.detect_frontier_vendor_down(
        [_fc("codex", 1), _fc("codex", 1)]) == []


def test_unknown_exit_codes_are_never_scored():
    """A row with a missing / non-integer exit_code is unknown. It is not a
    success and not a failure — it is skipped (rule 4)."""
    rows = [{"vendor": "codex"}, {"vendor": "codex", "exit_code": None},
            {"vendor": "codex", "exit_code": "1"}, "not-a-row",
            _fc("codex", 1), _fc("codex", 1)]
    assert lh.detect_frontier_vendor_down(rows) == []
    assert lh.detect_frontier_vendor_down(rows + [_fc("codex", 1)])[0][
        "signal"] == "frontier_vendor_down:codex"


def test_a_vendor_that_never_succeeded_says_so_honestly():
    rows = [_fc("codex", 1), _fc("codex", 1), _fc("codex", 1)]
    detail = lh.detect_frontier_vendor_down(rows)[0]["detail"]
    assert "never in this ledger" in detail
