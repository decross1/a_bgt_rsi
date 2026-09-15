"""Exact source-shaped tests for topic exhaustion and productive status."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from orchestrator.research_campaign import (
    DEFAULT_CAMPAIGN_ID,
    KNOWN_OPPONENT_CAMPAIGN_ID,
    CampaignError,
    bind_topic,
    load_campaign,
)
from orchestrator.research_ops_status import main, project_research_ops_status
from pipeline import daily_arxiv_job as job

NOW = datetime(2026, 9, 15, 16, 30, tzinfo=timezone.utc)
SOURCE_ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN_FILES = (
    "schema/research_campaign.schema.json",
    "schema/research_campaign_activation.schema.json",
    "schema/research_campaign_closure.schema.json",
    "experiments/research_campaign_v2_agentic_game_theory_20260914.json",
    "experiments/agentic_game_theory_v2_calibration_2026-09-14.json",
    "experiments/PREREG_agentic_game_theory_v2_calibration_2026-09-14.md",
    "experiments/research_campaign_v2_known_opponent_utility_20260915.json",
    "experiments/known_opponent_utility_response_2026-09-15.json",
    "experiments/PREREG_known_opponent_utility_response_2026-09-15.md",
    "experiments/known_opponent_utility/pilot.py",
    "experiments/known_opponent_utility/manifest.schema.json",
    "experiments/known_opponent_utility/admission.py",
    "experiments/known_opponent_utility/loop_bridge.py",
)


def _write(root: Path, relative: str, value: object) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n")


def _rows(root: Path, relative: str, rows: list[dict]) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))


def _root(tmp_path: Path, campaign_id: str = DEFAULT_CAMPAIGN_ID) -> Path:
    root = tmp_path / "repo"
    for relative in CAMPAIGN_FILES:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SOURCE_ROOT / relative, target)
    campaign = load_campaign(campaign_id, repo_root=root)
    _write(root, "run_state/active_research_campaign.json", {
        "schema_version": "research-campaign-activation/v1",
        "campaign_id": campaign_id,
        "campaign_manifest_sha256": campaign["_manifest_sha256"],
        "activated_at": "2026-09-15T16:20:00Z",
        "activated_by": "ops-status-test",
    })
    for relative in ("memory/loop_memory.jsonl", "run_state/coordinator_cycles.jsonl",
                     "run_state/coordinator_budget.jsonl"):
        _rows(root, relative, [])
    return root


def test_exact_link_consumes_topic_but_does_not_claim_global_no_work(tmp_path):
    root = _root(tmp_path)
    campaign = load_campaign(repo_root=root)
    topic = campaign["topic_policy"]["topics"][0]
    _rows(root, "memory/loop_memory.jsonl", [
        {"iteration_id": "legacy-same-text", "seed": {"topic": topic["text"]}},
        {"iteration_id": "iter-2026-09-15-001", "campaign": bind_topic(campaign, topic["text"]),
         "ended_at": "2026-09-15T01:48:19Z", "gate_status": "pending",
         "hypothesis": "PRIVATE_HYPOTHESIS_DO_NOT_EXPORT"},
    ])
    _rows(root, "run_state/coordinator_cycles.jsonl", [{
        "timestamp": "2026-09-15T16:00:00Z", "run_id": "coordinator_test",
        "status": "executed", "topic": "PRIVATE_TOPIC_DO_NOT_EXPORT",
        "plan": [{"action": "noop", "args": {"reason": "no eligible campaign topic"}}],
        "outcomes": [{"action": "noop", "status": "passed"}],
    }])
    _rows(root, "run_state/coordinator_budget.jsonl", [
        {"date": "2026-09-15", "spent": 3},
    ])
    x = project_research_ops_status(repo_root=root, observed_at=NOW)
    assert x["campaign_queue"]["status"] == "all_registered_topics_consumed"
    assert x["campaign_queue"]["consumed_count"] == 1
    assert x["campaign_queue"]["eligible_count"] == 0
    assert x["dispatch_gate"]["other_actionable_work"] == "not_assessed"
    assert x["last_productive"]["iteration_id"] == "iter-2026-09-15-001"
    assert x["last_productive"]["kind"] == "campaign_iteration_recorded"
    assert x["last_cycle"]["action_code"] == "noop"
    assert x["budget"]["spent_today"] == 3
    assert x["next_registered_campaign"]["registered_topic_count"] == 3
    assert x["next_registered_campaign"]["activation_required"] is True
    assert x["next_work"]["code"] == "activate_registered_successor"
    assert x["next_work"]["campaign_id"] == KNOWN_OPPONENT_CAMPAIGN_ID
    assert "PRIVATE" not in json.dumps(x)


def test_unlinked_text_does_not_consume_and_broken_loop_is_unknown(tmp_path):
    root = _root(tmp_path)
    campaign = load_campaign(repo_root=root)
    topic = campaign["topic_policy"]["topics"][0]
    _rows(root, "memory/loop_memory.jsonl", [
        {"iteration_id": "legacy", "seed": {"topic": topic["text"]}},
    ])
    x = project_research_ops_status(repo_root=root, observed_at=NOW)
    assert x["campaign_queue"]["status"] == "eligible"
    assert x["campaign_queue"]["eligible_topic_ids"] == [topic["topic_id"]]
    assert x["next_work"]["code"] == "run_preregistered_campaign_topic"
    (root / "memory/loop_memory.jsonl").write_text("{bad row}\n")
    x = project_research_ops_status(repo_root=root, observed_at=NOW)
    assert x["campaign_queue"]["status"] == "unknown"
    assert x["campaign_queue"]["eligible_count"] is None


def test_new_campaign_has_three_distinct_eligible_topics(tmp_path):
    root = _root(tmp_path, KNOWN_OPPONENT_CAMPAIGN_ID)
    x = project_research_ops_status(repo_root=root, observed_at=NOW)
    assert x["active_campaign"]["campaign_id"] == KNOWN_OPPONENT_CAMPAIGN_ID
    assert x["campaign_queue"]["status"] == "eligible"
    assert x["campaign_queue"]["eligible_count"] == 3
    assert len(set(x["campaign_queue"]["eligible_topic_ids"])) == 3
    assert x["next_registered_campaign"] is None
    assert x["next_work"]["code"] == "run_preregistered_campaign_topic"


def test_one_new_iteration_proposes_empirical_study_with_two_topics_still_queued(tmp_path):
    root = _root(tmp_path, KNOWN_OPPONENT_CAMPAIGN_ID)
    campaign = load_campaign(KNOWN_OPPONENT_CAMPAIGN_ID, repo_root=root)
    first = campaign["topic_policy"]["topics"][0]
    _rows(root, "memory/loop_memory.jsonl", [{
        "iteration_id": "iter-new-001",
        "ended_at": "2026-09-15T16:25:00Z",
        "campaign": bind_topic(campaign, first["text"]),
        "gate_status": "pending",
    }])
    x = project_research_ops_status(repo_root=root, observed_at=NOW)
    assert x["campaign_queue"]["eligible_count"] == 2
    assert x["next_work"]["code"] == "freeze_and_run_registered_empirical_study"
    assert x["next_work"]["study_id"] == "known-opponent-utility-response-pilot-v1"
    assert x["next_work"]["preregistration_sha256"] == campaign[
        "study_manifests"][0]["preregistration_sha256"]


def test_new_campaign_refuses_execution_source_drift(tmp_path):
    root = _root(tmp_path, KNOWN_OPPONENT_CAMPAIGN_ID)
    producer = root / "experiments/known_opponent_utility/pilot.py"
    producer.write_bytes(producer.read_bytes() + b"# unregistered change\n")
    with pytest.raises(CampaignError, match="execution source hash differs"):
        load_campaign(KNOWN_OPPONENT_CAMPAIGN_ID, repo_root=root)


def test_plan_cli_exports_only_content_free_registered_work(monkeypatch, capsys):
    monkeypatch.setattr(
        "orchestrator.research_ops_status.project_research_ops_status",
        lambda: {
            "schema": "research-ops-status/v1", "observed_at": "2026-09-15T16:30:00Z",
            "active_campaign": None, "campaign_queue": {"status": "unknown"},
            "next_work": {"code": "source_unknown"},
            "dispatch_gate": {"other_actionable_work": "not_assessed"},
            "private_topic": "PRIVATE_NEVER_EXPORT",
        },
    )
    assert main(["--plan"]) == 0
    output = capsys.readouterr().out
    assert json.loads(output)["next_work"]["code"] == "source_unknown"
    assert "PRIVATE" not in output


def test_ingestion_status_retains_last_success_but_shows_new_failed_attempt(tmp_path):
    root = _root(tmp_path)
    ingestion_root = tmp_path / "ingestion"
    paper = b'{"arxiv_id":"2609.12345"}\n'
    first_at = datetime(2026, 9, 15, 3, 0, tzinfo=timezone.utc)
    failed_at = datetime(2026, 9, 15, 3, 1, tzinfo=timezone.utc)

    def first_executor(argv, _timeout):
        if "--output" in argv:
            Path(argv[argv.index("--output") + 1]).write_bytes(paper)
        return job.CommandResult(0, "")

    job.run_job(state_root=ingestion_root, executor=first_executor,
                now=lambda: first_at, python="/registered/python")
    job.run_job(state_root=ingestion_root, executor=lambda _a, _t: job.CommandResult(
        1, "HTTP 429 before retry 6"), now=lambda: failed_at,
        python="/registered/python")
    x = project_research_ops_status(repo_root=root, ingestion_root=ingestion_root,
                                    observed_at=NOW)
    ingest = x["ingestion"]
    assert ingest["source_status"] == "available"
    assert ingest["latest_attempt_status"] == "fetch_failed"
    assert ingest["latest_failure_code"] == "arxiv_http_429_retry_exhausted"
    assert ingest["last_success_input_sha256"] == job._sha(paper)
    assert ingest["last_success_paper_count"] == 1
    assert ingest["latest_attempt_receipt_sha256"] != ingest["last_success_pointer_sha256"]


def test_legacy_cron_failure_is_visible_without_claiming_a_job_receipt(tmp_path):
    root = _root(tmp_path)
    legacy = tmp_path / "cron-daily-arxiv.log"
    legacy.write_text(
        "[daily-arxiv] 2026-09-15T03:00:00Z start\n"
        "WARNING: HTTP 429 before retry 1\n"
        "WARNING: HTTP 503 before retry 6\n"
        "ArxivScraperError: request failed after 6 retries\n"
    )
    x = project_research_ops_status(repo_root=root,
                                    legacy_ingestion_log=legacy, observed_at=NOW)
    view = x["ingestion_legacy_log"]
    assert view["status"] == "fetch_failed_log_observed"
    assert view["http_codes_observed"] == ["429", "503"]
    assert view["retry_count_observed"] == 6
    assert view["receipt_bound"] is False
    assert view["log_sha256"] is not None
