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
