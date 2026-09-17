from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from orchestrator import daily_research
from orchestrator.research_campaign import (
    DAILY_AGENTIC_GAME_THEORY_CAMPAIGN_ID,
    LINK_FIELDS,
    REPO_ROOT,
    CampaignError,
    all_topics,
    available_topics,
    bind_topic,
    classify_record,
    load_campaign,
)
from orchestrator.research_topic_registry import register_topic

MANIFEST_RELATIVE = (
    "experiments/research_campaign_daily_agentic_game_theory_20260917.json"
)
OPENED_AT = datetime(2026, 9, 17, 16, 23, tzinfo=timezone.utc)


def _campaign_tree(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    root = tmp_path / "repo"
    for relative in (
        "schema/research_campaign.schema.json",
        MANIFEST_RELATIVE,
    ):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / relative, target)
    return root, {DAILY_AGENTIC_GAME_THEORY_CAMPAIGN_ID: MANIFEST_RELATIVE}


def _load(root: Path, registry: dict[str, str]) -> dict:
    return load_campaign(
        DAILY_AGENTIC_GAME_THEORY_CAMPAIGN_ID,
        repo_root=root,
        registry=registry,
    )


def _source(index: int, *, arxiv_id: str | None = None) -> dict[str, str]:
    return {
        "kind": "daily_arxiv_paper",
        "id": arxiv_id or f"2609.{index:05d}",
        "sha256": f"{index + 1:064x}",
        "ingestion_run_id": (
            f"daily-arxiv-20260917T15000{index}Z-1234-{index + 1:08x}"
        ),
        "ingestion_input_sha256": f"{index + 11:064x}",
        "ingestion_terminal_sha256": f"{index + 21:064x}",
    }


def _topic(index: int) -> str:
    return (
        f"Source-bound exploratory topic {index}: identify a falsifiable game-theory "
        "question, an analytical comparator, and evidence that would disconfirm it."
    )


@pytest.fixture(autouse=True)
def _verified_literature(monkeypatch):
    monkeypatch.setattr(
        daily_research,
        "literature_candidates",
        lambda **_kwargs: [
            {"topic": _topic(index), "source": _source(index)}
            for index in range(1, 8)
        ],
    )


def test_registration_is_receipt_bound_and_old_links_remain_seven_fields(tmp_path):
    root, registry = _campaign_tree(tmp_path)
    campaign = _load(root, registry)
    assert all_topics(campaign) == []

    registered_at = OPENED_AT + timedelta(minutes=10)
    topic = register_topic(
        campaign,
        _topic(1),
        source=_source(1),
        loop_rows=[],
        now=registered_at,
        repo_root=root,
    )
    assert topic["source"] == "campaign_registered"
    assert topic["registration_source"] == _source(1)
    assert topic["registered_at"] == "2026-09-17T16:33:00Z"

    receipt = (
        root
        / "run_state/research_topic_registry"
        / DAILY_AGENTIC_GAME_THEORY_CAMPAIGN_ID
        / f"{topic['topic_id']}.json"
    )
    raw = receipt.read_bytes()
    assert receipt.is_file() and not receipt.is_symlink()
    assert hashlib.sha256(raw).hexdigest() == topic["topic_registration_sha256"]
    assert json.loads(raw)["source"] == _source(1)

    reloaded = _load(root, registry)
    assert all_topics(reloaded) == [topic]
    link = bind_topic(reloaded, topic["text"])
    assert set(link) == LINK_FIELDS | {"topic_registration_sha256"}
    assert classify_record({"campaign": link}, reloaded) == "explicit_match"
    assert available_topics(reloaded, [{"campaign": link}]) == []

    unbound = {"seed": {"topic": topic["text"]}, "ended_at": "2099-01-01T00:00:00Z"}
    assert classify_record(unbound, reloaded) == "unlinked_legacy"
    old_shape = dict(link)
    old_shape.pop("topic_registration_sha256")
    assert set(old_shape) == LINK_FIELDS
    assert classify_record({"campaign": old_shape}, reloaded) == (
        "campaign_link_mismatch"
    )


def test_registered_link_rejects_evidence_started_before_registration(tmp_path):
    root, registry = _campaign_tree(tmp_path)
    campaign = _load(root, registry)
    topic = register_topic(
        campaign,
        _topic(1),
        source=_source(1),
        loop_rows=[],
        now=OPENED_AT + timedelta(minutes=10),
        repo_root=root,
    )
    link = bind_topic(campaign, topic["text"])
    assert classify_record({"campaign": link}, campaign) == "explicit_match"
    assert classify_record(
        {"campaign": link, "started_at": "2026-09-17T16:32:59Z"}, campaign
    ) == "campaign_link_mismatch"
    assert classify_record(
        {"campaign": link, "started_at": topic["registered_at"]}, campaign
    ) == "explicit_match"
    assert classify_record(
        {"campaign": link, "started_at": "not-a-time"}, campaign
    ) == "malformed_record"


def test_duplicate_source_text_pending_and_daily_caps_are_enforced(tmp_path):
    root, registry = _campaign_tree(tmp_path)
    campaign = _load(root, registry)
    first = register_topic(
        campaign,
        _topic(1),
        source=_source(1),
        loop_rows=[],
        now=OPENED_AT + timedelta(minutes=10),
        repo_root=root,
    )
    with pytest.raises(CampaignError, match="duplicates an existing topic"):
        register_topic(
            campaign,
            _topic(1),
            source=_source(2),
            loop_rows=[],
            now=OPENED_AT + timedelta(minutes=11),
            repo_root=root,
        )
    with pytest.raises(CampaignError, match="duplicates an existing source"):
        register_topic(
            campaign,
            _topic(2),
            source=_source(1),
            loop_rows=[],
            now=OPENED_AT + timedelta(minutes=11),
            repo_root=root,
        )
    with pytest.raises(CampaignError, match="pending cap reached"):
        register_topic(
            campaign,
            _topic(2),
            source=_source(2),
            loop_rows=[{
                "campaign": bind_topic(campaign, first["text"]),
                "started_at": "2026-09-17T16:32:59Z",
            }],
            now=OPENED_AT + timedelta(minutes=11),
            repo_root=root,
        )

    rows = [{"campaign": bind_topic(campaign, first["text"])}]
    second = register_topic(
        campaign,
        _topic(2),
        source=_source(2),
        loop_rows=rows,
        now=OPENED_AT + timedelta(minutes=11),
        repo_root=root,
    )
    rows.append({"campaign": bind_topic(campaign, second["text"])})
    third = register_topic(
        campaign,
        _topic(3),
        source=_source(3),
        loop_rows=rows,
        now=OPENED_AT + timedelta(minutes=12),
        repo_root=root,
    )
    rows.append({"campaign": bind_topic(campaign, third["text"])})
    with pytest.raises(CampaignError, match="daily cap reached"):
        register_topic(
            campaign,
            _topic(4),
            source=_source(4),
            loop_rows=rows,
            now=OPENED_AT + timedelta(minutes=13),
            repo_root=root,
        )


def test_bad_time_does_not_write_and_future_receipt_fails_closed(tmp_path):
    root, registry = _campaign_tree(tmp_path)
    campaign = _load(root, registry)
    with pytest.raises(CampaignError, match="predates campaign opening"):
        register_topic(
            campaign,
            _topic(1),
            source=_source(1),
            loop_rows=[],
            now=OPENED_AT - timedelta(seconds=1),
            repo_root=root,
        )
    assert not (root / "run_state/research_topic_registry").exists()

    topic = register_topic(
        campaign,
        _topic(1),
        source=_source(1),
        loop_rows=[],
        now=OPENED_AT + timedelta(minutes=10),
        repo_root=root,
    )
    receipt = (
        root
        / "run_state/research_topic_registry"
        / DAILY_AGENTIC_GAME_THEORY_CAMPAIGN_ID
        / f"{topic['topic_id']}.json"
    )
    value = json.loads(receipt.read_bytes())
    value["registered_at"] = "2099-01-01T00:00:00Z"
    receipt.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(CampaignError, match="timestamp is in the future"):
        _load(root, registry)


def test_forged_source_is_rejected_before_registry_write(tmp_path, monkeypatch):
    root, registry = _campaign_tree(tmp_path)
    campaign = _load(root, registry)
    monkeypatch.setattr(
        daily_research,
        "literature_candidates",
        lambda **_kwargs: [{"topic": _topic(1), "source": _source(1)}],
    )
    forged = {**_source(1), "sha256": "f" * 64}
    with pytest.raises(CampaignError, match="exact currently verified"):
        register_topic(
            campaign,
            _topic(1),
            source=forged,
            loop_rows=[],
            now=OPENED_AT + timedelta(minutes=10),
            repo_root=root,
        )
    assert not (root / "run_state/research_topic_registry").exists()


def test_fabricated_topic_with_valid_source_is_rejected_before_write(
    tmp_path, monkeypatch,
):
    root, registry = _campaign_tree(tmp_path)
    campaign = _load(root, registry)
    monkeypatch.setattr(
        daily_research,
        "literature_candidates",
        lambda **_kwargs: [{"topic": _topic(1), "source": _source(1)}],
    )
    with pytest.raises(CampaignError, match="exact currently verified"):
        register_topic(
            campaign,
            "Fabricated topic text with no exact verified candidate.",
            source=_source(1),
            loop_rows=[],
            now=OPENED_AT + timedelta(minutes=10),
            repo_root=root,
        )
    assert not (root / "run_state/research_topic_registry").exists()


def test_corrupt_or_nonregular_registry_entry_fails_closed(tmp_path):
    root, registry = _campaign_tree(tmp_path)
    campaign = _load(root, registry)
    topic = register_topic(
        campaign,
        _topic(1),
        source=_source(1),
        loop_rows=[],
        now=OPENED_AT + timedelta(minutes=10),
        repo_root=root,
    )
    directory = (
        root
        / "run_state/research_topic_registry"
        / DAILY_AGENTIC_GAME_THEORY_CAMPAIGN_ID
    )
    receipt = directory / f"{topic['topic_id']}.json"
    receipt.write_bytes(b"{not-json\n")
    with pytest.raises(CampaignError, match="not strict JSON"):
        _load(root, registry)

    receipt.unlink()
    fifo = directory / "topic-registered-aaaaaaaaaaaaaaaaaaaaaaaa.json"
    os.mkfifo(fifo)
    with pytest.raises(CampaignError, match="non-regular"):
        _load(root, registry)


def test_frozen_campaign_cannot_accept_runtime_registration():
    campaign = load_campaign()
    assert set(bind_topic(campaign, all_topics(campaign)[0]["text"])) == LINK_FIELDS
    with pytest.raises(CampaignError, match="registered exploratory campaign"):
        register_topic(
            campaign,
            _topic(1),
            source=_source(1),
            loop_rows=[],
            now=OPENED_AT,
        )
