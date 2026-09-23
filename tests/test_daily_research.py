from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

from orchestrator import coordinator, daily_research, research_campaign
from pipeline import daily_arxiv_job

NOW = datetime(2026, 9, 17, 16, tzinfo=timezone.utc)


def paper(identifier, category="cs.GT", title="Strategic delegation in auctions"):
    return {"arxiv_id": identifier, "category": category, "title": title,
            "abstract": "We study incentive compatibility in a strategic game."}


def source(monkeypatch, papers, *, completed=NOW):
    pointer = {"finished_at": completed.isoformat(), "cache_relpath": "cache/input.jsonl",
               "run_id": "daily-arxiv-test", "input_sha256": "a" * 64,
               "terminal_sha256": "b" * 64}
    monkeypatch.setattr(daily_arxiv_job, "_last_success", lambda _root: pointer)
    monkeypatch.setattr(daily_arxiv_job, "_read_regular", lambda *_args:
                        b"\n".join(json.dumps(row).encode() for row in papers))


def test_source_filters_generic_ml_and_binds_original_paper(monkeypatch, tmp_path):
    valid = paper("2609.12345")
    generic = {**paper("2609.12346", "cs.MA", "Faster collaborative training"),
               "abstract": "Higher classification accuracy with parallel GPUs."}
    source(monkeypatch, [valid, generic, paper("2609.12347", "cs.CV"), paper("../../bad")])
    candidates = daily_research.literature_candidates(repo_root=tmp_path, now=NOW)
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["source"]["id"] == valid["arxiv_id"]
    assert candidate["source"]["sha256"] == hashlib.sha256(json.dumps(
        valid, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    assert candidate["source"]["ingestion_terminal_sha256"] == "b" * 64
    assert "not a registered experiment" in candidate["topic"]
    assert len(candidate["topic"]) <= 2000


@pytest.mark.parametrize("completed", [NOW - timedelta(days=8), NOW + timedelta(seconds=1)])
def test_stale_or_future_success_cannot_supply_daily_topic(monkeypatch, tmp_path, completed):
    source(monkeypatch, [paper("2609.12345")], completed=completed)
    assert daily_research.literature_candidates(repo_root=tmp_path, now=NOW) == []


def test_corrupt_success_is_not_reported_as_empty(monkeypatch, tmp_path):
    def corrupt(_root):
        raise daily_arxiv_job.IngestionError("cache SHA drifted")
    monkeypatch.setattr(daily_arxiv_job, "_last_success", corrupt)
    with pytest.raises(daily_arxiv_job.IngestionError):
        daily_research.literature_candidates(repo_root=tmp_path, now=NOW)


def test_malformed_consumption_ledger_is_not_an_empty_queue(tmp_path):
    ledger = tmp_path / "loop.jsonl"
    ledger.write_text('{"iteration_id":"a"}\n{truncated\n')
    with pytest.raises(daily_arxiv_job.IngestionError, match="malformed"):
        daily_research.read_loop_rows(ledger)


def test_source_identity_dedup_survives_new_ingestion_hash(monkeypatch, tmp_path):
    source(monkeypatch, [paper("2609.12345"), paper("2609.12346")])
    campaign = {"topic_policy": {"mode": "registered_exploratory"}, "_repo_root": tmp_path}
    monkeypatch.setattr(research_campaign, "all_topics", lambda _c: [{
        "text_sha256": "f" * 64, "registered_at": NOW.isoformat(),
        "registration_source": {"id": "2609.12346"},
    }])
    rows = daily_research.queue_candidates(campaign, now=NOW)
    assert [row["source"]["id"] for row in rows] == ["2609.12345"]


def test_daily_capacity_resets_without_reusing_sources(monkeypatch, tmp_path):
    from orchestrator import research_topic_registry
    monkeypatch.setattr(research_topic_registry, "MAX_REGISTRATIONS_PER_UTC_DAY", 3)  # a configured cap
    source(monkeypatch, [paper("2609.12345")])
    campaign = {"topic_policy": {"mode": "registered_exploratory"}, "_repo_root": tmp_path}
    registered = [{"text_sha256": str(i) * 64, "registered_at": NOW.isoformat(),
                   "registration_source": {"id": f"2609.0000{i}"}} for i in range(3)]
    monkeypatch.setattr(research_campaign, "all_topics", lambda _c: registered)
    assert daily_research.queue_candidates(campaign, now=NOW) == []
    assert len(daily_research.queue_candidates(campaign, now=NOW + timedelta(days=1))) == 1


def test_topic_id_resolution_preserves_raw_attempt_and_rejects_unknown():
    raw = [{"action": "run_loop_iteration", "args": {"topic": "topic-available"}},
           {"action": "run_loop_iteration", "args": {"topic": "topic-consumed"}}]
    result = coordinator._resolve_campaign_topic_ids(raw, {"topic_suggestions": [
        {"topic_id": "topic-available", "topic": "Registered exact text"}]})
    assert result[0]["args"]["topic"] == "Registered exact text"
    assert result[1]["args"]["topic"] == "topic-consumed"
    assert raw[0]["args"]["topic"] == "topic-available"


def test_same_registered_topic_cannot_dispatch_twice_in_one_plan():
    campaign = research_campaign.load_campaign()
    topic = campaign["topic_policy"]["topics"][0]["text"]
    state = {"topic_suggestions": research_campaign.available_topics(campaign, [])}
    plan = [{"name": "run_loop_iteration", "args": {"topic": topic}}] * 2
    errors = coordinator._campaign_plan_errors(plan, campaign=campaign, state=state)
    assert len(errors) == 1
    assert "not currently available" in errors[0]


def test_starved_queue_writes_receipt_without_planner(monkeypatch, tmp_path):
    campaign = {"campaign_id": "test-campaign", "_manifest_sha256": "a" * 64,
                "topic_policy": {"mode": "registered_exploratory"}}
    monkeypatch.setattr(daily_research, "replenish", lambda *_a: {
        "status": "queue_starved", "reason": "no_unused_verified_literature"})
    monkeypatch.setattr(research_campaign, "load_active_campaign", lambda: campaign)
    monkeypatch.setattr(coordinator, "assess_state", lambda **_k: {"topic_suggestions": [], "gaps": []})
    monkeypatch.setattr(coordinator, "plan", lambda *_a, **_k: pytest.fail("planner called"))
    receipts = []
    monkeypatch.setattr(coordinator.coordinator_cycle_log, "write_coordinator_cycle", receipts.append)
    monkeypatch.setattr(coordinator.coordinator_cycle_log, "emit_health_signals", lambda *_a: None)
    report = coordinator._coordinator_cycle(
        run_id="test", budget=6, dry_run=False, execute_handlers=None,
        backend=None, model=None, loop_memory_path=tmp_path / "loop.jsonl",
        surfaced_path=tmp_path / "surfaced.jsonl", feedback_path=tmp_path / "feedback.jsonl",
        active_run_path=tmp_path / "active.json", campaign=campaign,
    )
    assert report["status"] == "queue_starved"
    assert report["attempts"] == report["executed"] == []
    assert receipts == [report]


def test_nara_rechecks_registration_before_model_call(monkeypatch):
    from orchestrator import nara
    campaign = research_campaign.load_campaign()
    topic = campaign["topic_policy"]["topics"][0]["text"]
    link = research_campaign.bind_topic(campaign, topic)
    monkeypatch.setattr(research_campaign, "load_active_campaign", lambda: campaign)
    monkeypatch.setattr(nara, "get_backend", lambda *_a: pytest.fail("model path entered"))
    with pytest.raises(research_campaign.CampaignError, match="after dispatch"):
        nara.run_iteration(topic, expected_campaign_link={**link, "topic_sha256": "0" * 64})


def test_registered_daily_intake_uses_normal_validator_without_planner(monkeypatch, tmp_path):
    campaign = research_campaign.load_campaign(
        research_campaign.DAILY_AGENTIC_GAME_THEORY_CAMPAIGN_ID)
    seed = research_campaign.load_campaign()["topic_policy"]["topics"][0]
    campaign["_registered_topics"] = [{**seed, "source": "campaign_registered",
                                       "topic_registration_sha256": "c" * 64,
                                       "registration_source": {"id": "2609.12345"},
                                       "registered_at": NOW.isoformat()}]
    state = {"topic_suggestions": research_campaign.available_topics(campaign, []),
             "gaps": []}
    monkeypatch.setattr(coordinator, "assess_state", lambda **_k: state)
    monkeypatch.setattr(coordinator, "plan", lambda *_a, **_k: pytest.fail("planner called"))
    monkeypatch.setattr(coordinator.active_run, "update_active_run", lambda **_k: None)
    monkeypatch.setattr(coordinator.coordinator_cycle_log, "write_coordinator_cycle", lambda *_a: None)
    report = coordinator._coordinator_cycle(
        run_id="daily-intake", budget=6, dry_run=True, execute_handlers=None,
        backend=None, model=None, loop_memory_path=tmp_path / "loop.jsonl",
        surfaced_path=tmp_path / "surfaced.jsonl", feedback_path=tmp_path / "feedback.jsonl",
        active_run_path=tmp_path / "active.json", campaign=campaign,
    )
    assert report["status"] == "planned"
    assert report["plan"][0]["args"]["topic"] == seed["text"]
    assert report["plan"][0]["cost"] == 3
    assert report["attempts"] == []
    assert report["state"]["plan_origin"] == "registered_daily_queue"


def test_broken_ledger_halts_before_assessing_available_topic(monkeypatch, tmp_path):
    campaign = research_campaign.load_campaign(
        research_campaign.DAILY_AGENTIC_GAME_THEORY_CAMPAIGN_ID)
    ledger = tmp_path / "loop.jsonl"
    ledger.write_text("{broken")
    monkeypatch.setattr(coordinator, "assess_state", lambda **_k: pytest.fail("continued after bad ledger"))
    receipts = []
    monkeypatch.setattr(coordinator.coordinator_cycle_log, "write_coordinator_cycle", receipts.append)
    monkeypatch.setattr(coordinator.coordinator_cycle_log, "emit_health_signals", lambda *_a: None)
    result = coordinator._coordinator_cycle(
        run_id="bad-ledger", budget=6, dry_run=False, execute_handlers=None,
        backend=None, model=None, loop_memory_path=ledger,
        surfaced_path=tmp_path / "surfaced.jsonl", feedback_path=tmp_path / "feedback.jsonl",
        active_run_path=tmp_path / "active.json", campaign=campaign,
    )
    assert result["status"] == "topic_source_unavailable"
    assert receipts == [result]


def test_no_daily_topic_limit_by_default(monkeypatch, tmp_path):
    from orchestrator import research_topic_registry
    monkeypatch.setattr(research_topic_registry, "MAX_REGISTRATIONS_PER_UTC_DAY", 0)
    source(monkeypatch, [paper("2609.12345")])
    campaign = {"topic_policy": {"mode": "registered_exploratory"}, "_repo_root": tmp_path}
    registered = [{"text_sha256": str(i) * 64, "registered_at": NOW.isoformat(),
                   "registration_source": {"id": f"2609.0000{i}"}} for i in range(3)]
    monkeypatch.setattr(research_campaign, "all_topics", lambda _c: registered)
    assert daily_research.queue_candidates(campaign, now=NOW) != []  # three today do not stop a fourth
