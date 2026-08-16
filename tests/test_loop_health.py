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
