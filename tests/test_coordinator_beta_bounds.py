"""Session-3 β bounds (D-049 draft) + v2 action plumbing.

Offline (MOCK_LLM-friendly): no model calls — plan() is stubbed where a
cycle runs. Covers the kill switch, the daily executed-cycle ledger,
promotion near-miss persistence, follow-up topic surfacing, and the v2
action arg-schemas through validate_plan.
"""
import json

import pytest

from orchestrator import coordinator as co
from orchestrator.coordinator_actions import validate_plan


def _stub_plan(monkeypatch, plan_list):
    monkeypatch.setattr(co, "plan", lambda *a, **k: plan_list)


def _cycle_kwargs(tmp_path):
    return dict(
        loop_memory_path=tmp_path / "loop_memory.jsonl",
        surfaced_path=tmp_path / "surfaced.jsonl",
        feedback_path=tmp_path / "feedback.jsonl",
        active_run_path=tmp_path / "active_run.json",
    )


# ── v2 action schemas through the validator ───────────────────────────────

def test_run_experiment_action_validates():
    ok = validate_plan(
        [{"action": "run_experiment",
          "args": {"tier": "synthetic", "experiment_id": "exp001_repeated_pd"}}],
        budget=6,
    )
    assert ok["ok"], ok["errors"]
    assert ok["normalized"][0]["cost"] == 5

    bad = validate_plan(
        [{"action": "run_experiment", "args": {"tier": "synthetic"}}],
        budget=6,
    )
    assert not bad["ok"]  # experiment_id required


def test_forecast_markets_action_validates_and_bounds_n():
    ok = validate_plan([{"action": "forecast_markets", "args": {}}], budget=6)
    assert ok["ok"], ok["errors"]
    too_big = validate_plan(
        [{"action": "forecast_markets", "args": {"n": 500}}], budget=6)
    assert not too_big["ok"]  # n capped at 50


# ── kill switch ───────────────────────────────────────────────────────────

def test_pause_file_halts_cycle_before_any_call(tmp_path, monkeypatch):
    monkeypatch.setattr(co, "PAUSE_PATH", tmp_path / "pause_coordinator")
    co.PAUSE_PATH.write_text("")
    called = {"plan": False}
    monkeypatch.setattr(
        co, "plan", lambda *a, **k: called.__setitem__("plan", True) or [])
    report = co.coordinator_cycle(dry_run=False, **_cycle_kwargs(tmp_path))
    assert report["status"] == "paused"
    assert called["plan"] is False  # halted BEFORE the LLM call
    assert report["executed"] == []


# ── daily executed-cycle ledger ───────────────────────────────────────────

def test_daily_ledger_blocks_execute_but_not_dry_run(tmp_path, monkeypatch):
    ledger = tmp_path / "coordinator_budget.jsonl"
    monkeypatch.setattr(co, "BUDGET_LEDGER_PATH", ledger)
    monkeypatch.setattr(co, "PAUSE_PATH", tmp_path / "absent")
    monkeypatch.setattr(co, "DAILY_BUDGET_CAP", 6)
    co._charge_daily_ledger("seed_run", 6, path=ledger)

    report = co.coordinator_cycle(dry_run=False, budget=6,
                                  **_cycle_kwargs(tmp_path))
    assert report["status"] == "daily_budget_exhausted"

    # Dry-run is never charged or blocked by the ledger.
    _stub_plan(monkeypatch, [{"action": "noop", "args": {"reason": "idle"}}])
    report = co.coordinator_cycle(dry_run=True, budget=6,
                                  **_cycle_kwargs(tmp_path))
    assert report["status"] == "planned"


def test_executed_cycle_charges_ledger(tmp_path, monkeypatch):
    ledger = tmp_path / "coordinator_budget.jsonl"
    monkeypatch.setattr(co, "BUDGET_LEDGER_PATH", ledger)
    monkeypatch.setattr(co, "PAUSE_PATH", tmp_path / "absent")
    _stub_plan(monkeypatch, [{"action": "noop", "args": {"reason": "idle"}}])
    report = co.coordinator_cycle(dry_run=False, budget=6,
                                  **_cycle_kwargs(tmp_path))
    assert report["status"] == "executed"
    rows = [json.loads(l) for l in ledger.read_text().splitlines()]
    assert len(rows) == 1 and rows[0]["spent"] == 0  # noop costs 0
    assert co._daily_spent(path=ledger) == 0


# ── near-miss persistence ─────────────────────────────────────────────────

def test_persist_near_misses_appends_rows(tmp_path):
    path = tmp_path / "promotion_near_misses.jsonl"
    co._persist_near_misses(
        {"promoted": [], "near_misses": [
            {"source_iteration_id": "iter-X", "reason": "quorum unmet",
             "stage": "adversarial"},
        ]},
        path=path,
    )
    rows = [json.loads(l) for l in path.read_text().splitlines()]
    assert rows[0]["source_iteration_id"] == "iter-X"
    assert rows[0]["stage"] == "adversarial"
    co._persist_near_misses({"near_misses": []}, path=path)  # no-op
    assert len(path.read_text().splitlines()) == 1


def test_persist_near_misses_keyed_dedup(tmp_path):
    """P0 (LOOP_V1) zombie pin: the same (source_iteration_id, stage, reason)
    re-persisted next cycle appends ZERO rows — the stalled 2026-08-05..14
    loop re-appended the same ~140 rows/day, 5,513 rows of duplication."""
    path = tmp_path / "promotion_near_misses.jsonl"
    result = {"promoted": [], "near_misses": [
        {"source_iteration_id": "iter-X", "reason": "quorum unmet",
         "stage": "adversarial"},
    ]}
    co._persist_near_misses(result, path=path)
    co._persist_near_misses(result, path=path)  # identical next cycle
    assert len(path.read_text().splitlines()) == 1
    # A genuinely new reason still appends.
    co._persist_near_misses({"near_misses": [
        {"source_iteration_id": "iter-X", "reason": "refuted 3/3",
         "stage": "adversarial"}]}, path=path)
    assert len(path.read_text().splitlines()) == 2


# ── follow-up topic surfacing (the orphaned queue gets a consumer) ───────

def test_followup_topics_surface_first(tmp_path, monkeypatch):
    followups = tmp_path / "finding_followups.jsonl"
    followups.write_text(json.dumps(
        {"finding_id": "sf-1", "new_topic": "probe the q=45 anchoring"}) + "\n")
    monkeypatch.setattr(
        co, "pick_morning_topic",
        lambda loop_memory_path=None: ("arxiv topic", "arxiv_pick"))
    out = co._topic_suggestions(tmp_path / "loop_memory.jsonl",
                                followups_path=followups)
    assert out[0] == {"topic": "probe the q=45 anchoring",
                      "source": "finding_followup"}
    assert out[-1]["source"] == "arxiv_pick"


# ── v2 handler wiring (the review's gap: no test exercised the handlers) ──

def test_forecast_markets_handler_runs_sweep_score_memo(monkeypatch):
    """The handler chains run -> analyze -> memo with real symbols (the
    invented-symbol bug shipped exactly because nothing imported them)."""
    import experiments.exp007_polymarket.analyze as an
    import experiments.exp007_polymarket.run as rn
    import experiments.exp007_polymarket.strategy_memo as sm

    calls = {}
    monkeypatch.setattr(rn, "main",
                        lambda argv: calls.setdefault("run_argv", argv) and 0 or 0)
    monkeypatch.setattr(an, "main", lambda: calls.setdefault("analyzed", True) and 0 or 0)
    monkeypatch.setattr(sm, "build_and_write_memo",
                        lambda **kw: {"strategy_id": "stub"})
    out = co.handle_forecast_markets(n=7, live_data=False)
    assert out["status"] == "passed"
    assert calls["run_argv"] == ["--n", "7"]  # no --live-data
    assert out["result"]["memo"] == {"strategy_id": "stub"}


def test_forecast_markets_memo_failure_degrades_explicitly(monkeypatch):
    import experiments.exp007_polymarket.analyze as an
    import experiments.exp007_polymarket.run as rn
    import experiments.exp007_polymarket.strategy_memo as sm

    monkeypatch.setattr(rn, "main", lambda argv: 0)
    monkeypatch.setattr(an, "main", lambda: 0)

    def _boom(**kw):
        raise FileNotFoundError("summary.json missing")
    monkeypatch.setattr(sm, "build_and_write_memo", _boom)
    out = co.handle_forecast_markets(n=5, live_data=False)
    assert out["status"] == "passed"  # sweep+score succeeded
    assert out["result"]["memo"] is None
    assert "FileNotFoundError" in out["result"]["memo_note"]


def test_run_experiment_handler_maps_args(monkeypatch):
    import orchestrator.autoresearch as ar

    seen = {}

    def _stub(tier, experiment_id, **kw):
        seen.update(tier=tier, experiment_id=experiment_id, **kw)
        return {"iteration_id": "iter-stub"}
    monkeypatch.setattr(ar, "run_autoresearch", _stub)
    out = co.handle_run_experiment(
        tier="synthetic", experiment_id="exp009_cournot", run_real=False)
    assert out["status"] == "passed"
    assert seen["reuse_results"] is True and seen["run_experiment"] is False
    assert seen["live"] is True and seen["source"] == "coordinator"


# ── budget PACING (2026-08-16) ──────────────────────────────────────────────

def test_allowance_grows_with_the_clock_and_starts_at_the_floor():
    """The cap is a DAY's budget. First-come-first-served spent it by 11:00 on
    2026-08-16 and left nine hourly cycles with nothing to do; the allowance is
    the elapsed share instead."""
    from datetime import datetime, timezone

    def at(h, m=0):
        return co._budget_allowance(
            datetime(2026, 8, 16, h, m, tzinfo=timezone.utc), cap=60, floor=3)

    assert at(0, 0) == 3            # the day can always start
    assert at(6, 0) == 18           # a quarter of the day -> 15 + floor
    assert at(12, 0) == 33
    assert at(23, 59) == 60         # never exceeds the cap
    # Monotonic: later in the day is never a smaller allowance.
    hours = [at(h) for h in range(24)]
    assert hours == sorted(hours)


def test_pacing_can_be_disabled_and_then_the_whole_cap_is_available():
    from datetime import datetime, timezone
    import orchestrator.coordinator as mod
    old = mod.BUDGET_PACING
    try:
        mod.BUDGET_PACING = False
        assert mod._budget_allowance(
            datetime(2026, 8, 16, 0, 1, tzinfo=timezone.utc), cap=60) == 60
    finally:
        mod.BUDGET_PACING = old


def test_paced_refusal_is_distinct_from_exhaustion_and_writes_no_cycle_row(
        tmp_path, monkeypatch):
    """A refusal is not a cycle. Writing it to coordinator_cycles.jsonl is what
    put nine empty 'no valid plan' rows on the dashboard in one afternoon — it
    is logged as a refusal instead (rule 6 satisfied, dashboard not lied to)."""
    ledger = tmp_path / "coordinator_budget.jsonl"
    monkeypatch.setattr(co, "BUDGET_LEDGER_PATH", ledger)
    monkeypatch.setattr(co, "PAUSE_PATH", tmp_path / "absent")
    monkeypatch.setattr(co, "DAILY_BUDGET_CAP", 60)
    monkeypatch.setattr(co, "_budget_allowance", lambda *a, **k: 6)
    co._charge_daily_ledger("seed", 6, path=ledger)

    wrote: list = []
    monkeypatch.setattr(co.coordinator_cycle_log, "write_coordinator_cycle",
                        lambda report, **kw: wrote.append(report))
    report = co.coordinator_cycle(dry_run=False, budget=3,
                                  **_cycle_kwargs(tmp_path))
    # Under its elapsed share, but nowhere near the daily cap.
    assert report["status"] == "daily_budget_paced"
    assert "elapsed-share allowance" in report["errors"][0]
    assert wrote == [], "a budget refusal must not be recorded as a cycle"


def test_true_exhaustion_still_says_exhausted(tmp_path, monkeypatch):
    ledger = tmp_path / "coordinator_budget.jsonl"
    monkeypatch.setattr(co, "BUDGET_LEDGER_PATH", ledger)
    monkeypatch.setattr(co, "PAUSE_PATH", tmp_path / "absent")
    monkeypatch.setattr(co, "DAILY_BUDGET_CAP", 6)
    monkeypatch.setattr(co, "_budget_allowance", lambda *a, **k: 6)
    co._charge_daily_ledger("seed", 6, path=ledger)
    report = co.coordinator_cycle(dry_run=False, budget=3,
                                  **_cycle_kwargs(tmp_path))
    assert report["status"] == "daily_budget_exhausted"
    assert f"cap {6}" in report["errors"][0]


# ── activity portfolio (owner directive 2026-08-16) ─────────────────────────

def test_a_spent_class_is_skipped_while_other_classes_stay_open(
        tmp_path, monkeypatch):
    """The point of the portfolio: exhausting ideation must not stop research.
    On 2026-08-16 one class took 100% of the day (19 cycles, one topic) and no
    other class ran at all."""
    ledger = tmp_path / "coordinator_budget.jsonl"
    monkeypatch.setattr(co, "BUDGET_LEDGER_PATH", ledger)
    monkeypatch.setattr(co, "PAUSE_PATH", tmp_path / "absent")
    monkeypatch.setattr(co, "DAILY_BUDGET_CAP", 60)
    monkeypatch.setattr(co, "_budget_allowance", lambda *a, **k: 60)
    # Ideation already had its whole share today; research untouched.
    co._charge_daily_ledger("seed", 24, path=ledger, by_class={"ideation": 24})

    ran: list = []
    _stub_plan(monkeypatch, [
        {"action": "run_loop_iteration", "args": {"topic": "t"}},
        {"action": "promote_findings", "args": {}},
    ])
    report = co.coordinator_cycle(
        dry_run=False, budget=6,
        execute_handlers={
            "run_loop_iteration": lambda **k: ran.append("ideation"),
            "promote_findings": lambda **k: ran.append("research"),
        },
        **_cycle_kwargs(tmp_path))
    by_action = {e["action"]: e for e in report["executed"]}
    assert by_action["run_loop_iteration"]["status"] == "skipped"
    assert "activity share spent: ideation" in by_action["run_loop_iteration"]["reason"]
    assert by_action["promote_findings"]["status"] == "passed"
    assert ran == ["research"]


def test_charge_row_records_the_class_breakdown(tmp_path, monkeypatch):
    ledger = tmp_path / "coordinator_budget.jsonl"
    monkeypatch.setattr(co, "BUDGET_LEDGER_PATH", ledger)
    monkeypatch.setattr(co, "PAUSE_PATH", tmp_path / "absent")
    monkeypatch.setattr(co, "_budget_allowance", lambda *a, **k: 60)
    _stub_plan(monkeypatch, [{"action": "promote_findings", "args": {}}])
    co.coordinator_cycle(dry_run=False, budget=6,
                         execute_handlers={"promote_findings": lambda **k: None},
                         **_cycle_kwargs(tmp_path))
    row = [json.loads(l) for l in ledger.read_text().splitlines() if l.strip()][-1]
    assert row["by_class"] == {"research": 2}


def test_pre_portfolio_ledger_rows_count_as_ideation_not_as_nothing():
    """Rows written before by_class existed were all ideation in fact. Counting
    them as unclassified would hand today's ideation share back for free."""
    import tempfile, os as _os
    with tempfile.TemporaryDirectory() as d:
        p = _os.path.join(d, "b.jsonl")
        today = co.datetime.now(co.timezone.utc).strftime("%Y-%m-%d")
        with open(p, "w") as fh:
            fh.write(json.dumps({"date": today, "spent": 9}) + "\n")
            fh.write(json.dumps({"date": today, "spent": 2,
                                 "by_class": {"research": 2}}) + "\n")
        assert co._daily_spent_by_class(path=p) == {"ideation": 9, "research": 2}


def test_every_menu_action_has_a_portfolio_class():
    """An unmapped action would silently draw from ideation. Catch it here."""
    from orchestrator.coordinator_actions import ACTIONS
    unmapped = sorted(set(ACTIONS) - set(co.ACTIVITY_CLASS_OF))
    assert not unmapped, f"actions missing a portfolio class: {unmapped}"
