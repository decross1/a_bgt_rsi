from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from orchestrator.research_campaign import (
    DEFAULT_CAMPAIGN_ID,
    DEFAULT_CAMPAIGN_MANIFEST,
    REPO_ROOT,
    CampaignError,
    available_topics,
    bind_topic,
    campaign_context,
    classify_record,
    load_active_campaign,
    load_campaign,
    public_campaign,
    record_matches,
    unique_matching_records,
)


def _campaign_tree(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    root = tmp_path / "repo"
    for relative in (
        "schema/research_campaign.schema.json",
        "schema/research_campaign_activation.schema.json",
        "schema/research_campaign_closure.schema.json",
        "experiments/research_campaign_v2_agentic_game_theory_20260914.json",
        "experiments/agentic_game_theory_v2_calibration_2026-09-14.json",
        "experiments/PREREG_agentic_game_theory_v2_calibration_2026-09-14.md",
    ):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / relative, target)
    registry = {
        DEFAULT_CAMPAIGN_ID: "experiments/research_campaign_v2_agentic_game_theory_20260914.json",
    }
    return root, registry


def test_default_campaign_binds_question_topic_and_study_artifacts():
    campaign = load_campaign()
    assert campaign["campaign_id"] == DEFAULT_CAMPAIGN_ID
    assert campaign["status"] == "prepared"
    assert campaign["_path"] == DEFAULT_CAMPAIGN_MANIFEST
    assert len(campaign["_manifest_sha256"]) == 64
    assert public_campaign(campaign).get("_path") is None
    assert (
        campaign_context(campaign)["campaign_manifest_sha256"]
        == (campaign["_manifest_sha256"])
    )

    topic = campaign["topic_policy"]["topics"][0]
    link = bind_topic(campaign, topic["text"])
    assert link["campaign_id"] == DEFAULT_CAMPAIGN_ID
    assert link["topic_id"] == topic["topic_id"]
    assert classify_record({"campaign": link}, campaign) == "explicit_match"
    assert record_matches({"campaign": link}, campaign) is True


def test_membership_is_never_inferred_from_topic_or_time():
    campaign = load_campaign()
    topic = campaign["topic_policy"]["topics"][0]
    legacy = {
        "ended_at": "2099-01-01T00:00:00Z",
        "seed": {"topic": topic["text"], "source": "coordinator"},
    }
    assert classify_record(legacy, campaign) == "unlinked_legacy"

    malformed = {"campaign": {"campaign_id": DEFAULT_CAMPAIGN_ID}}
    assert classify_record(malformed, campaign) == "malformed_campaign_link"
    wrong = bind_topic(campaign, topic["text"])
    wrong["topic_sha256"] = "0" * 64
    assert classify_record({"campaign": wrong}, campaign) == "campaign_link_mismatch"

    hostile_shape = bind_topic(campaign, topic["text"])
    hostile_shape["topic_sha256"] = {"nested": "not a scalar"}
    assert (
        classify_record({"campaign": hostile_shape}, campaign)
        == "malformed_campaign_link"
    )


def test_duplicate_record_identity_is_withheld_across_all_cohorts():
    campaign = load_campaign()
    topic = campaign["topic_policy"]["topics"][0]["text"]
    link = bind_topic(campaign, topic)
    different = dict(link, campaign_id="different-campaign")
    rows = [
        {"iteration_id": "iter-2026-09-14-001", "campaign": link},
        {"iteration_id": "iter-2026-09-14-001", "campaign": link},
        {"iteration_id": "iter-2026-09-14-002", "campaign": link},
        {"iteration_id": "iter-2026-09-14-002"},
        {"iteration_id": "iter-2026-09-14-003", "campaign": link},
        {"iteration_id": "iter-2026-09-14-003", "campaign": different},
        {"iteration_id": "iter-2026-09-14-004", "campaign": link},
    ]
    assert unique_matching_records(
        rows,
        campaign,
        identity_field="iteration_id",
    ) == [rows[-1]]


def test_topic_seed_is_available_once_then_consumed_by_exact_link():
    campaign = load_campaign()
    topic = campaign["topic_policy"]["topics"][0]
    suggestions = available_topics(campaign, [])
    assert suggestions == [
        {
            "topic": topic["text"],
            "source": "campaign_preregistered",
            "campaign_id": DEFAULT_CAMPAIGN_ID,
            "topic_id": topic["topic_id"],
            "topic_sha256": topic["text_sha256"],
            "campaign": bind_topic(campaign, topic["text"]),
        }
    ]
    legacy_same_text = {"seed": {"topic": topic["text"]}}
    assert len(available_topics(campaign, [legacy_same_text])) == 1
    assert (
        available_topics(
            campaign,
            [{"campaign": bind_topic(campaign, topic["text"])}],
        )
        == []
    )


def test_loader_rejects_tampered_hashes_and_redirected_manifest(tmp_path):
    root, registry = _campaign_tree(tmp_path)
    manifest_path = root / registry[DEFAULT_CAMPAIGN_ID]
    raw = json.loads(manifest_path.read_text())
    raw["research_question"]["text"] += " changed"
    manifest_path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(CampaignError, match="question hash"):
        load_campaign(DEFAULT_CAMPAIGN_ID, repo_root=root, registry=registry)

    root, registry = _campaign_tree(tmp_path / "redirect")
    manifest_path = root / registry[DEFAULT_CAMPAIGN_ID]
    real = root / "elsewhere.json"
    manifest_path.replace(real)
    manifest_path.symlink_to(real)
    with pytest.raises(CampaignError, match="redirected"):
        load_campaign(DEFAULT_CAMPAIGN_ID, repo_root=root, registry=registry)


def test_loader_rejects_study_content_that_no_longer_matches_bound_hash(tmp_path):
    root, registry = _campaign_tree(tmp_path)
    study = root / "experiments/agentic_game_theory_v2_calibration_2026-09-14.json"
    study.write_text(study.read_text() + "\n", encoding="utf-8")
    with pytest.raises(CampaignError, match="study manifest hash"):
        load_campaign(DEFAULT_CAMPAIGN_ID, repo_root=root, registry=registry)


def test_loader_rejects_duplicate_topic_text_even_with_distinct_ids(tmp_path):
    root, registry = _campaign_tree(tmp_path)
    manifest_path = root / registry[DEFAULT_CAMPAIGN_ID]
    raw = json.loads(manifest_path.read_text())
    duplicate = dict(raw["topic_policy"]["topics"][0])
    duplicate["topic_id"] = "topic-distinct-id-002"
    raw["topic_policy"]["topics"].append(duplicate)
    manifest_path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(CampaignError, match="topic texts are duplicated"):
        load_campaign(DEFAULT_CAMPAIGN_ID, repo_root=root, registry=registry)


def test_manifest_lifecycle_fields_cannot_be_mutated_in_place(tmp_path):
    root, registry = _campaign_tree(tmp_path)
    manifest_path = root / registry[DEFAULT_CAMPAIGN_ID]
    raw = json.loads(manifest_path.read_text())
    raw["status"] = "active"
    manifest_path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(CampaignError, match="research campaign fails schema"):
        load_campaign(DEFAULT_CAMPAIGN_ID, repo_root=root, registry=registry)


def test_activation_pointer_is_required_and_hash_bound(tmp_path):
    root, _registry = _campaign_tree(tmp_path)
    campaign = load_campaign(DEFAULT_CAMPAIGN_ID, repo_root=root)
    activation = root / "run_state" / "active_research_campaign.json"
    activation.parent.mkdir(parents=True)

    assert (
        load_active_campaign(
            repo_root=root,
            activation_path=activation,
            env_campaign_id="",
        )
        is None
    )
    with pytest.raises(CampaignError, match="without an activation pointer"):
        load_active_campaign(
            repo_root=root,
            activation_path=activation,
            env_campaign_id=DEFAULT_CAMPAIGN_ID,
        )

    pointer = {
        "schema_version": "research-campaign-activation/v1",
        "campaign_id": DEFAULT_CAMPAIGN_ID,
        "campaign_manifest_sha256": campaign["_manifest_sha256"],
        "activated_at": "2026-09-14T22:20:00Z",
        "activated_by": "owner",
    }
    activation.write_text(json.dumps(pointer), encoding="utf-8")
    active = load_active_campaign(
        repo_root=root,
        activation_path=activation,
        env_campaign_id=DEFAULT_CAMPAIGN_ID,
        now=datetime(2026, 9, 14, 22, 30, tzinfo=timezone.utc),
    )
    assert active is not None
    assert active["_activation"] == pointer

    pointer["campaign_manifest_sha256"] = "0" * 64
    activation.write_text(json.dumps(pointer), encoding="utf-8")
    with pytest.raises(CampaignError, match="manifest hash differs"):
        load_active_campaign(
            repo_root=root,
            activation_path=activation,
            env_campaign_id="",
            now=datetime(2026, 9, 14, 22, 30, tzinfo=timezone.utc),
        )


def test_activation_pointer_rejects_redirect_and_env_mismatch(tmp_path):
    root, _registry = _campaign_tree(tmp_path)
    campaign = load_campaign(DEFAULT_CAMPAIGN_ID, repo_root=root)
    pointer = {
        "schema_version": "research-campaign-activation/v1",
        "campaign_id": DEFAULT_CAMPAIGN_ID,
        "campaign_manifest_sha256": campaign["_manifest_sha256"],
        "activated_at": "2026-09-14T22:20:00Z",
        "activated_by": "owner",
    }
    activation = root / "run_state" / "active_research_campaign.json"
    activation.parent.mkdir(parents=True)
    activation.write_text(json.dumps(pointer), encoding="utf-8")
    with pytest.raises(CampaignError, match="environment.*differ"):
        load_active_campaign(
            repo_root=root,
            activation_path=activation,
            env_campaign_id="some-other-campaign",
            now=datetime(2026, 9, 14, 22, 30, tzinfo=timezone.utc),
        )

    target = root / "run_state" / "real-pointer.json"
    activation.replace(target)
    activation.symlink_to(target)
    with pytest.raises(CampaignError, match="redirected"):
        load_active_campaign(
            repo_root=root,
            activation_path=activation,
            env_campaign_id="",
            now=datetime(2026, 9, 14, 22, 30, tzinfo=timezone.utc),
        )

    activation.unlink()
    activation.symlink_to(root / "run_state" / "absent-target.json")
    with pytest.raises(CampaignError, match="redirected"):
        load_active_campaign(
            repo_root=root,
            activation_path=activation,
            env_campaign_id="",
            now=datetime(2026, 9, 14, 22, 30, tzinfo=timezone.utc),
        )


def test_activation_chronology_and_separate_closure_fail_closed(tmp_path):
    root, _registry = _campaign_tree(tmp_path)
    campaign = load_campaign(DEFAULT_CAMPAIGN_ID, repo_root=root)
    link_before_activation = bind_topic(
        campaign,
        campaign["topic_policy"]["topics"][0]["text"],
    )
    activation = root / "run_state" / "active_research_campaign.json"
    activation.parent.mkdir(parents=True)
    pointer = {
        "schema_version": "research-campaign-activation/v1",
        "campaign_id": DEFAULT_CAMPAIGN_ID,
        "campaign_manifest_sha256": campaign["_manifest_sha256"],
        "activated_at": "2026-09-14T22:10:00Z",
        "activated_by": "test-owner",
    }
    activation.write_text(json.dumps(pointer), encoding="utf-8")
    now = datetime(2026, 9, 14, 22, 30, tzinfo=timezone.utc)
    with pytest.raises(CampaignError, match="predates.*declaration"):
        load_active_campaign(repo_root=root, now=now)

    pointer["activated_at"] = "2026-09-14T23:00:00Z"
    activation.write_text(json.dumps(pointer), encoding="utf-8")
    with pytest.raises(CampaignError, match="timestamp is in the future"):
        load_active_campaign(repo_root=root, now=now)

    pointer["activated_at"] = "2026-09-14T22:20:00Z"
    activation.write_text(json.dumps(pointer), encoding="utf-8")
    assert load_active_campaign(repo_root=root, now=now) is not None
    closure = root / "run_state/research_campaign_closures" / (
        f"{DEFAULT_CAMPAIGN_ID}.json"
    )
    closure.parent.mkdir(parents=True)
    closure.write_text(json.dumps({
        "schema_version": "research-campaign-closure/v1",
        "campaign_id": DEFAULT_CAMPAIGN_ID,
        "campaign_manifest_sha256": campaign["_manifest_sha256"],
        "closed_at": "2026-09-14T22:25:00Z",
        "closed_by": "test-owner",
    }))
    with pytest.raises(CampaignError, match="campaign is closed"):
        load_active_campaign(repo_root=root, now=now)

    # Lifecycle receipts never rewrite the declaration or invalidate links
    # already copied into research records.
    reloaded = load_campaign(DEFAULT_CAMPAIGN_ID, repo_root=root)
    assert reloaded["_manifest_sha256"] == campaign["_manifest_sha256"]
    assert classify_record({"campaign": link_before_activation}, reloaded) == (
        "explicit_match"
    )
