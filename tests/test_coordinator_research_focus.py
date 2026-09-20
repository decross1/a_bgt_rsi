"""Focus blocks discovery, not independently eligible promotion work."""
from __future__ import annotations

import json

from orchestrator import coordinator, daily_research, research_focus


def test_vote_ready_ids_are_derived_from_evidence_not_gap_prose(tmp_path):
    ledger = tmp_path / "loop.jsonl"
    ledger.write_text(json.dumps({
        "iteration_id": "iter-legacy-valid-l3",
        "hypothesis": {"text": "A concrete claim"},
        "retrieval": {"relevance": {"low_confidence": False}},
        "novelty": {"class": "novel"}, "critique": {"verdict": "survives"},
        "experiment_outcome": {"trials": 30, "summary": "Recorded legacy result"},
        "cross_tier_comparison": {"agreement": True},
    }) + "\n")
    state = coordinator.assess_state(
        loop_memory_path=ledger, surfaced_path=tmp_path / "surfaced.jsonl",
        feedback_path=tmp_path / "feedback.jsonl", active_run_path=tmp_path / "active.json")
    assert state["vote_ready_iteration_ids"] == ["iter-legacy-valid-l3"]


def test_focus_preserves_structured_promotion_eligibility(monkeypatch, tmp_path):
    monkeypatch.setattr(research_focus, "project_focus", lambda _root: {
        "status": "selected", "intake_policy": "focus_before_new_topics"})
    monkeypatch.setattr(daily_research, "replenish", lambda *_a: (_ for _ in ()).throw(
        AssertionError("discovery must stay held")))
    # Eligibility is produced by assess_state; changing human-readable gap
    # wording must not suppress it. Campaign-specific promotion gates still run.
    monkeypatch.setattr(coordinator, "assess_state", lambda **_kw: {
        "topic_suggestions": [{"topic": "unused"}], "gaps": ["Eligible for panel"],
        "vote_ready_iteration_ids": ["iter-active-eligible"],
    })
    planned = []

    def plan(state, **_kw):
        planned.append(state)
        return [{"action": "promote_findings", "args": {}}]

    monkeypatch.setattr(coordinator, "plan", plan)
    monkeypatch.setattr(coordinator.coordinator_cycle_log, "write_coordinator_cycle", lambda *_a: None)
    campaign = {"campaign_id": "daily", "_manifest_sha256": "a" * 64,
                "topic_policy": {"mode": "registered_exploratory"}, "_repo_root": tmp_path,
                "campaign_actions": {"admitted": ["promote_findings", "noop"], "deferred": []}}
    result = coordinator._coordinator_cycle(
        run_id="focus-promotion", budget=6, dry_run=True, execute_handlers=None,
        backend=None, model=None, loop_memory_path=tmp_path / "loop.jsonl",
        surfaced_path=tmp_path / "surfaced.jsonl", feedback_path=tmp_path / "feedback.jsonl",
        active_run_path=tmp_path / "active.json", campaign=campaign)
    assert len(planned) == 1
    assert result["status"] == "planned"
    assert result["state"]["topic_suggestions"] == []
    assert [step["name"] for step in result["plan"]] == ["promote_findings"]
