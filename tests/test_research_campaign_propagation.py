from __future__ import annotations

import json
from pathlib import Path

import pytest

from orchestrator import coordinator as coord
from orchestrator import coordinator_cycle_log as cycle_log
from orchestrator import finding_promotion, nara, nara_daemon
from orchestrator import research_campaign as campaigns


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def _activate(tmp_path: Path, monkeypatch) -> dict:
    campaign = campaigns.load_campaign()
    pointer = tmp_path / "active_research_campaign.json"
    pointer.write_text(
        json.dumps(
            {
                "schema_version": "research-campaign-activation/v1",
                "campaign_id": campaign["campaign_id"],
                "campaign_manifest_sha256": campaign["_manifest_sha256"],
                "activated_at": "2026-09-14T22:20:00Z",
                "activated_by": "test-owner",
            }
        )
    )
    monkeypatch.setattr(campaigns, "DEFAULT_ACTIVATION_PATH", pointer)
    monkeypatch.delenv("NARA_RESEARCH_CAMPAIGN", raising=False)
    return campaign


def _paths(tmp_path: Path) -> dict[str, str]:
    paths = {
        "loop_memory_path": tmp_path / "loop.jsonl",
        "feedback_path": tmp_path / "feedback.jsonl",
        "surfaced_path": tmp_path / "surfaced.jsonl",
        "active_run_path": tmp_path / "active.json",
    }
    for key in ("loop_memory_path", "feedback_path", "surfaced_path"):
        paths[key].write_text("")
    return {key: str(value) for key, value in paths.items()}


@pytest.fixture(autouse=True)
def _isolate_coordinator(tmp_path, monkeypatch):
    monkeypatch.setattr(coord, "PAUSE_PATH", tmp_path / "pause")
    monkeypatch.setattr(coord, "BUDGET_LEDGER_PATH", tmp_path / "budget.jsonl")
    monkeypatch.setattr(coord.active_run, "write_active_run", lambda *a, **k: {})
    monkeypatch.setattr(coord.active_run, "update_active_run", lambda *a, **k: None)
    monkeypatch.setattr(coord.active_run, "clear_active_run", lambda: None)
    monkeypatch.setattr(coord, "set_run_id", lambda _value: None)
    monkeypatch.setattr(coord, "set_current_agent", lambda _value: None)
    monkeypatch.setattr(
        coord.coordinator_cycle_log,
        "write_coordinator_cycle",
        lambda *a, **k: None,
    )


def test_assessment_filters_legacy_and_different_campaign_rows(tmp_path):
    campaign = campaigns.load_campaign()
    topic = campaign["topic_policy"]["topics"][0]["text"]
    exact_link = campaigns.bind_topic(campaign, topic)
    other_link = dict(exact_link, campaign_id="different-campaign")
    paths = _paths(tmp_path)
    _write_jsonl(
        Path(paths["loop_memory_path"]),
        [
            {"iteration_id": "iter-2026-09-14-001", "seed": {"topic": topic}},
            {
                "iteration_id": "iter-2026-09-14-002",
                "campaign": other_link,
                "seed": {"topic": topic},
            },
            {
                "iteration_id": "iter-2026-09-14-003",
                "campaign": exact_link,
                "seed": {"topic": topic},
                "gate_status": "pending",
            },
        ],
    )
    _write_jsonl(
        Path(paths["feedback_path"]),
        [
            {"iteration_id": "iter-2026-09-14-001", "verdict": "valid"},
            {"iteration_id": "iter-2026-09-14-003", "verdict": "needs_revision"},
        ],
    )
    _write_jsonl(
        Path(paths["surfaced_path"]),
        [
            {
                "finding_id": "sf-legacy",
                "source_iteration_id": "iter-2026-09-14-001",
                "status": "surfaced",
                "evidence_level": "L4",
            },
            {
                "finding_id": "sf-exact",
                "source_iteration_id": "iter-2026-09-14-003",
                "campaign": exact_link,
                "status": "surfaced",
                "evidence_level": "L4",
            },
        ],
    )

    state = coord.assess_state(campaign_id=campaign["campaign_id"], **paths)
    assert [row["iteration_id"] for row in state["recent_findings"]] == [
        "iter-2026-09-14-003",
    ]
    assert [row["finding_id"] for row in state["surfaced_pending"]] == ["sf-exact"]
    assert state["topic_suggestions"] == []
    assert (
        state["campaign_context"]["campaign_manifest_sha256"]
        == (campaign["_manifest_sha256"])
    )


@pytest.mark.parametrize("collision_kind", ["exact", "legacy", "different"])
def test_cross_cohort_duplicate_iteration_is_not_scored_or_replayed(
    tmp_path,
    collision_kind,
):
    campaign = campaigns.load_campaign()
    topic = campaign["topic_policy"]["topics"][0]["text"]
    link = campaigns.bind_topic(campaign, topic)
    paths = _paths(tmp_path)
    exact = {
        "iteration_id": "iter-2026-09-14-001",
        "campaign": link,
        "seed": {"topic": topic},
    }
    collision = dict(exact)
    if collision_kind == "legacy":
        collision.pop("campaign")
    elif collision_kind == "different":
        collision["campaign"] = dict(link, campaign_id="different-campaign")
    _write_jsonl(Path(paths["loop_memory_path"]), [exact, collision])
    state = coord.assess_state(campaign_id=campaign["campaign_id"], **paths)
    assert state["recent_findings"] == []
    assert state["topic_suggestions"] == []


@pytest.mark.parametrize(
    "plan",
    [
        [{"action": "run_loop_iteration", "args": {"topic": "rewritten topic"}}],
        [
            {
                "action": "run_experiment",
                "args": {"tier": "synthetic", "experiment_id": "x"},
            }
        ],
        [{"action": "bubble_up", "args": {"finding_ids": ["sf-legacy"]}}],
    ],
)
def test_campaign_gate_replans_then_refuses_invalid_plan(
    tmp_path,
    monkeypatch,
    plan,
):
    campaign = _activate(tmp_path, monkeypatch)
    paths = _paths(tmp_path)
    monkeypatch.setattr(
        coord,
        "call_sync",
        lambda *a, **k: {"completion": json.dumps(plan), "request_id": "r"},
    )

    report = coord.coordinator_cycle(budget=6, dry_run=True, **paths)
    assert report["status"] == "no_valid_plan"
    assert len(report["attempts"]) == 3
    assert all(not attempt["ok"] for attempt in report["attempts"])
    assert report["state"]["campaign_context"]["campaign_id"] == campaign["campaign_id"]


def test_active_pointer_admits_only_available_exact_seed(tmp_path, monkeypatch):
    campaign = _activate(tmp_path, monkeypatch)
    paths = _paths(tmp_path)
    topic = campaign["topic_policy"]["topics"][0]["text"]
    plan = [{"action": "run_loop_iteration", "args": {"topic": topic}}]
    monkeypatch.setattr(
        coord,
        "call_sync",
        lambda *a, **k: {"completion": json.dumps(plan), "request_id": "r"},
    )

    report = coord.coordinator_cycle(budget=3, dry_run=True, **paths)
    assert report["status"] == "planned"
    assert report["plan"][0]["args"]["topic"] == topic
    suggestion = report["state"]["topic_suggestions"][0]
    assert suggestion["campaign"] == campaigns.bind_topic(campaign, topic)


def test_executed_campaign_bubble_persists_loader_derived_link(
    tmp_path, monkeypatch,
):
    campaign = _activate(tmp_path, monkeypatch)
    paths = _paths(tmp_path)
    bubbles_path = tmp_path / "coordinator_bubbles.jsonl"
    plan = [{
        "action": "bubble_up",
        "args": {
            "question": "Should the campaign continue this line of inquiry?",
            "kind": "A",
            "allowed_actions": ["sign_off", "reject"],
        },
    }]
    monkeypatch.setattr(
        coord,
        "call_sync",
        lambda *a, **k: {"completion": json.dumps(plan), "request_id": "r"},
    )
    monkeypatch.setattr(coord, "DEFAULT_COORDINATOR_BUBBLES", bubbles_path)
    monkeypatch.setattr(
        coord.coordinator_cycle_log, "emit_health_signals", lambda _report: [],
    )

    report = coord.coordinator_cycle(
        budget=1,
        dry_run=False,
        execute_handlers={"bubble_up": coord.handle_bubble_up},
        **paths,
    )

    assert report["status"] == "executed"
    assert report["bubble_receipts"][0]["status"] == "persisted"
    row = json.loads(bubbles_path.read_text())
    topic = campaign["topic_policy"]["topics"][0]["text"]
    assert row["campaign"] == campaigns.bind_topic(campaign, topic)
    assert "campaign" not in row["request"]["args"]


def test_env_cannot_activate_campaign_without_pointer(tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    missing = tmp_path / "missing-activation.json"
    monkeypatch.setattr(campaigns, "DEFAULT_ACTIVATION_PATH", missing)
    monkeypatch.setenv("NARA_RESEARCH_CAMPAIGN", campaigns.DEFAULT_CAMPAIGN_ID)
    called = []
    monkeypatch.setattr(coord, "call_sync", lambda *a, **k: called.append(True))
    with pytest.raises(campaigns.CampaignError, match="without an activation pointer"):
        coord.coordinator_cycle(budget=3, dry_run=True, **paths)
    assert called == []


def test_default_handlers_inject_campaign_outside_model_args(monkeypatch):
    seen: list[tuple] = []
    monkeypatch.setattr(
        nara,
        "run_iteration",
        lambda topic, **kwargs: seen.append(("run", topic, kwargs)) or {},
    )
    monkeypatch.setattr(
        finding_promotion,
        "promote_findings",
        lambda **kwargs: seen.append(("promote", kwargs)) or {"near_misses": []},
    )
    campaign = campaigns.load_campaign()
    handlers = coord._default_execute_handlers(
        campaign_id=campaigns.DEFAULT_CAMPAIGN_ID,
        campaign_manifest_sha256=campaign["_manifest_sha256"],
    )
    handlers["run_loop_iteration"](topic="exact")
    handlers["promote_findings"](max_candidates=2)
    assert seen[0][2]["campaign_id"] == campaigns.DEFAULT_CAMPAIGN_ID
    assert seen[0][2]["campaign_manifest_sha256"] == campaign["_manifest_sha256"]
    assert seen[1][1]["campaign_id"] == campaigns.DEFAULT_CAMPAIGN_ID
    assert seen[1][1]["campaign_manifest_sha256"] == campaign["_manifest_sha256"]


def test_same_id_manifest_swap_is_refused_at_read_and_dispatch_boundaries(
    monkeypatch,
    tmp_path,
):
    campaign = campaigns.load_campaign()
    changed = dict(campaign, _manifest_sha256="0" * 64)
    topic = campaign["topic_policy"]["topics"][0]["text"]

    monkeypatch.setattr(campaigns, "load_campaign", lambda *_a, **_k: changed)
    with pytest.raises(campaigns.CampaignError, match="changed before assessment"):
        coord.assess_state(
            campaign_id=campaign["campaign_id"],
            campaign_manifest_sha256=campaign["_manifest_sha256"],
            **_paths(tmp_path),
        )

    monkeypatch.setattr(campaigns, "load_active_campaign", lambda: changed)
    with pytest.raises(campaigns.CampaignError, match="changed after dispatch"):
        nara.run_iteration(
            topic,
            campaign_id=campaign["campaign_id"],
            campaign_manifest_sha256=campaign["_manifest_sha256"],
        )
    with pytest.raises(campaigns.CampaignError, match="changed after dispatch"):
        finding_promotion.promote_findings(
            loop_memory_path=tmp_path / "loop.jsonl",
            feedback_path=tmp_path / "feedback.jsonl",
            surfaced_path=tmp_path / "surfaced.jsonl",
            campaign_id=campaign["campaign_id"],
            campaign_manifest_sha256=campaign["_manifest_sha256"],
        )


def test_cycle_log_copies_campaign_context_and_exact_topic_link():
    campaign = campaigns.load_campaign()
    topic = campaign["topic_policy"]["topics"][0]["text"]
    context = campaigns.campaign_context(campaign)
    link = campaigns.bind_topic(campaign, topic)
    report = {
        "run_id": "coordinator_test",
        "status": "planned",
        "dry_run": True,
        "plan": [{"name": "run_loop_iteration", "args": {"topic": topic}}],
        "executed": [],
        "bubble_up": [],
        "attempts": [],
        "state": {
            "campaign_context": context,
            "topic_suggestions": [
                {
                    "topic": topic,
                    "source": "campaign_preregistered",
                    "campaign": link,
                }
            ],
        },
    }
    row = cycle_log.cycle_row_from_report(report, timestamp="2026-09-14T23:00:00Z")
    assert row["campaign_context"] == context
    assert row["campaign"] == link
    assert row["planner_state"]["campaign_context"] == context


def test_daemon_uses_pointer_for_campaign_agenda_and_cycle(tmp_path, monkeypatch):
    campaign = _activate(tmp_path, monkeypatch)
    topic = campaign["topic_policy"]["topics"][0]["text"]
    seen: list[tuple[str, str | None]] = []

    def assessment(*, campaign_id=None):
        seen.append(("assess", campaign_id))
        return {"topic_suggestions": [{"topic": topic}], "gaps": []}

    def cycle(**kwargs):
        seen.append(("cycle", kwargs.get("campaign_id")))
        return {"status": "executed"}

    monkeypatch.setattr(nara_daemon.coordinator, "assess_state", assessment)
    monkeypatch.setattr(nara_daemon.coordinator, "coordinator_cycle", cycle)
    assert nara_daemon._agenda() == [{"topic": topic}]
    assert nara_daemon._run_cycle(3)["status"] == "executed"
    assert seen == [
        ("assess", campaign["campaign_id"]),
        ("cycle", campaign["campaign_id"]),
    ]


def test_cycle_log_uses_single_campaign_link_after_seed_consumed():
    campaign = campaigns.load_campaign()
    topic = campaign["topic_policy"]["topics"][0]["text"]
    link = campaigns.bind_topic(campaign, topic)
    report = {
        "run_id": "coordinator_promote",
        "status": "planned",
        "dry_run": True,
        "plan": [{"name": "promote_findings", "args": {}}],
        "executed": [],
        "bubble_up": [],
        "attempts": [],
        "state": {
            "campaign_context": campaigns.campaign_context(campaign),
            "campaign_topic_links": [link],
            "topic_suggestions": [],
        },
    }
    row = cycle_log.cycle_row_from_report(report)
    assert row["campaign"] == link
