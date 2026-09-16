"""Current campaign lists never import old findings or clear global gates."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import experiments, human_todo, iteration_journey, lab_todo, ladder, loop_v0, research_scope
from orchestrator.research_campaign import bind_topic, load_campaign

REPO = Path(__file__).resolve().parents[3]


def write_rows(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.delenv("NARA_RESEARCH_CAMPAIGN", raising=False)
    root = tmp_path / "repo"
    for relative in (
        "schema/research_campaign.schema.json",
        "schema/research_campaign_activation.schema.json",
        "schema/research_campaign_closure.schema.json",
        "experiments/research_campaign_v2_agentic_game_theory_20260914.json",
        "experiments/agentic_game_theory_v2_calibration_2026-09-14.json",
        "experiments/PREREG_agentic_game_theory_v2_calibration_2026-09-14.md",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / relative, path)
    campaign = load_campaign(repo_root=root)
    (root / "run_state").mkdir()
    (root / "memory").mkdir()
    (root / "run_state/active_research_campaign.json").write_text(
        json.dumps(
            {
                "schema_version": "research-campaign-activation/v1",
                "campaign_id": campaign["campaign_id"],
                "campaign_manifest_sha256": campaign["_manifest_sha256"],
                "activated_at": datetime.now(timezone.utc).isoformat(),
                "activated_by": "test operator",
            }
        )
    )
    link = bind_topic(campaign, campaign["topic_policy"]["topics"][0]["text"])
    current = {
        "iteration_id": "iter-current",
        "campaign": link,
        "seed": {"topic": "current topic"},
        "ended_at": "2026-09-15T00:00:00Z",
        "gate_status": "pending",
        "experiment_outcome": {"metric": "score", "value": 1},
    }
    old = {**current, "iteration_id": "iter-old", "seed": {"topic": "old research"}}
    old.pop("campaign")
    write_rows(root / "memory/loop_memory.jsonl", [old, current])
    app = FastAPI()
    research_scope.register(app, repo_root=root, memory_dir=root / "memory")
    iteration_journey.register(app, repo_root=root, memory_dir=root / "memory")
    loop_v0.register(
        app,
        repo_root=root,
        run_state_dir=root / "run_state",
        journal_dir=root / "journal",
        loop_memory_path=root / "memory/loop_memory.jsonl",
    )
    human_todo.register(
        app, run_state_dir=root / "run_state", memory_dir=root / "memory"
    )
    ladder.register(app, repo_root=root, memory_dir=root / "memory")
    experiments.register(
        app,
        experiments_dir=root / "experiments",
        loop_memory_path=root / "memory/loop_memory.jsonl",
    )
    lab_todo.register(
        app,
        repo_root=root,
        run_state_dir=root / "run_state",
        memory_dir=root / "memory",
        builder=lambda: pytest.fail("active campaign read invoked global builder"),
    )
    return root, TestClient(app), current, old


def test_default_api_history_and_explicit_current_are_separate(setup):
    root, client, current, _old = setup
    before = (root / "memory/loop_memory.jsonl").read_bytes()
    assert len(client.get("/api/loop_v0/iterations").json()["iterations"]) == 2
    response = client.get(
        "/api/loop_v0/iterations?research_scope=active&fields=iteration_id&limit=1"
    )
    assert response.status_code == 200
    assert response.json()["iterations"] == [{"iteration_id": "iter-current"}]
    assert (
        response.json()["research_scope"]["campaign"]["campaign_id"]
        == current["campaign"]["campaign_id"]
    )
    assert (root / "memory/loop_memory.jsonl").read_bytes() == before


def test_duplicate_cross_history_id_cannot_borrow_campaign_membership(setup):
    root, client, current, old = setup
    write_rows(
        root / "memory/loop_memory.jsonl",
        [current, {**old, "iteration_id": current["iteration_id"]}],
    )
    assert (
        client.get("/api/loop_v0/iterations?research_scope=active").json()["iterations"]
        == []
    )
    detail = client.get("/api/iteration/iter-current/journey?research_scope=active")
    assert detail.status_code == 200
    assert detail.json()["found"] is False
    assert detail.json()["research_scope"]["status"] == "active"
    assert client.get("/api/iteration/iter-current/journey?research_scope=all").json()["found"] is True


def test_journey_preserves_exact_campaign_scope_and_explicit_archive_access(setup):
    root, client, current, old = setup
    before = (root / "memory/loop_memory.jsonl").read_bytes()
    active = client.get("/api/iteration/iter-current/journey?research_scope=active").json()
    assert active["found"] is True
    assert active["iteration"] == current
    assert active["research_scope"]["campaign"]["campaign_id"] == current["campaign"]["campaign_id"]
    hidden = client.get("/api/iteration/iter-old/journey?research_scope=active").json()
    assert hidden["found"] is False
    assert "iteration" not in hidden
    archive = client.get("/api/iteration/iter-old/journey?research_scope=all").json()
    assert archive["iteration"] == old
    assert archive["research_scope"]["status"] == "all_research"
    legacy = client.get("/api/iteration/iter-old/journey").json()
    assert legacy["iteration"] == old
    assert "research_scope" not in legacy
    assert (root / "memory/loop_memory.jsonl").read_bytes() == before


@pytest.mark.parametrize("damage", ["bad_hash", "bad_json", "symlink"])
def test_bad_activation_fails_closed_and_history_stays_readable(setup, damage):
    root, client, _, _ = setup
    path = root / "run_state/active_research_campaign.json"
    if damage == "bad_hash":
        value = json.loads(path.read_text())
        value["campaign_manifest_sha256"] = "0" * 64
        path.write_text(json.dumps(value))
    elif damage == "bad_json":
        path.write_text("{broken")
    else:
        path.unlink()
        path.symlink_to(root / "absent")
    assert client.get("/api/research_scope").status_code == 503
    assert client.get("/api/iteration/iter-current/journey?research_scope=active").status_code == 503
    assert client.get("/api/iteration/iter-current/journey?research_scope=all").json()["found"] is True
    assert (
        client.get("/api/loop_v0/iterations?research_scope=active").status_code == 503
    )
    assert (
        len(
            client.get("/api/loop_v0/iterations?research_scope=all").json()[
                "iterations"
            ]
        )
        == 2
    )


def test_no_active_campaign_is_not_implicit_all_history(setup):
    root, client, _, _ = setup
    (root / "run_state/active_research_campaign.json").unlink()
    assert client.get("/api/research_scope").json()["status"] == "no_active_campaign"
    assert (
        client.get("/api/loop_v0/iterations?research_scope=active").json()["iterations"]
        == []
    )
    assert client.get("/api/iteration/iter-current/journey?research_scope=active").json()["found"] is False


@pytest.mark.parametrize("damage", ["malformed", "symlink", "oversized"])
def test_broken_campaign_source_is_not_zero(setup, monkeypatch, damage):
    root, client, _, _ = setup
    path = root / "memory/loop_memory.jsonl"
    if damage == "malformed":
        path.write_text("{broken\n")
    elif damage == "symlink":
        original = path.read_text()
        path.unlink()
        (root / "redirect").write_text(original)
        path.symlink_to(root / "redirect")
    else:
        monkeypatch.setattr(research_scope, "MAX_SOURCE_BYTES", 1)
    assert (
        client.get("/api/loop_v0/iterations?research_scope=active").status_code == 503
    )
    assert client.get("/api/iteration/iter-current/journey?research_scope=active").status_code == 503


def test_scoped_todo_preserves_global_safety_gate_and_omitted_count(setup):
    root, client, _current, _old = setup
    (root / "run_state/week1.state.json").write_text(
        json.dumps({"human_gates_pending": ["global safety gate"]})
    )
    data = client.get("/api/human_todo?research_scope=active").json()
    assert {item["id"] for item in data["items"] if item["kind"] == "gate_verdict"} == {
        "iter-current"
    }
    assert data["counts"]["state_gate"] == 1
    assert data["research_scope"]["omitted_historical_items"] == 1
    assert data["research_scope"]["global_safety_gates_retained"] is True


def test_old_and_mixed_collections_cannot_donate_rungs(setup):
    root, _client, _current, _old = setup
    # Use real reducer state shape to isolate membership selection from the
    # ledger's independent event-schema contract.
    scope = research_scope.ResearchScope("active", root, root / "memory")
    state = {
        "current": {"members": ["iter-current"], "evidence_level": "L1"},
        "old": {"members": ["iter-old"], "evidence_level": "L5"},
        "mixed": {"members": ["iter-old", "iter-current"], "evidence_level": "L5"},
    }
    assert scope.clusters(state) == {"current": state["current"]}


def test_reused_experiment_id_does_not_import_old_summary(setup):
    root, client, _current, _old = setup
    results = root / "experiments/exp001_repeated_pd/results"
    results.mkdir(parents=True)
    (results / "summary.json").write_text(json.dumps({"verdict": "YES", "score": 1}))
    data = client.get("/api/research?research_scope=active").json()
    assert all(not tier["experiments"] for tier in data["tiers"])
    assert data["untiered"] == []
    assert client.get("/api/research?research_scope=all").json()["tiers"][0][
        "experiments"
    ]


def test_active_queue_does_not_invoke_global_or_model_assisted_builder(setup):
    _root, client, _, _ = setup
    data = client.get("/api/lab_todo?research_scope=active").json()
    assert data["agenda"] == []
    assert data["refine_candidates"] == []
    assert data["gaps_source"] == "unavailable"
    assert data["research_scope"]["mode"] == "active"


def test_unknown_scope_rejected(setup):
    _, client, _, _ = setup
    assert client.get("/api/loop_v0/iterations?research_scope=typo").status_code == 422


def test_duplicate_json_campaign_key_is_unavailable_not_current(setup):
    root, client, current, _ = setup
    path = root / "memory/loop_memory.jsonl"
    raw = json.dumps(current)
    path.write_text(raw[:-1] + ',"campaign":null}\n')
    assert (
        client.get("/api/loop_v0/iterations?research_scope=active").status_code == 503
    )


def test_parent_directory_redirect_does_not_import_external_research(setup):
    root, client, _, _ = setup
    original = root / "memory"
    redirect = root / "redirect-memory"
    original.rename(redirect)
    original.symlink_to(redirect, target_is_directory=True)
    assert (
        client.get("/api/loop_v0/iterations?research_scope=active").status_code == 503
    )


def ledger_events(*members):
    rows = [{
        "event_type": "cluster_created", "ts": "2026-09-15T00:00:00Z",
        "cluster_id": "cl-campaign", "member_id": members[0],
        "origin": "consolidation",
    }]
    rows.extend({
        "event_type": "member_added", "ts": "2026-09-15T00:00:01Z",
        "cluster_id": "cl-campaign", "member_id": member,
    } for member in members[1:])
    rows.append({
        "event_type": "evidence_level_changed", "ts": "2026-09-15T00:00:02Z",
        "cluster_id": "cl-campaign", "evidence_level": "L5",
    })
    return rows


@pytest.mark.parametrize("endpoint", ["ladder", "lab_todo", "human_todo"])
@pytest.mark.parametrize("damage", ["redirect", "invalid_schema", "oversized"])
def test_every_active_ledger_consumer_uses_guarded_snapshot(setup, monkeypatch, endpoint, damage):
    root, client, _, _ = setup
    path = root / "memory/idea_ledger.jsonl"
    write_rows(path, ledger_events("iter-current"))
    if damage == "redirect":
        target = root / "external-ledger.jsonl"
        path.rename(target)
        path.symlink_to(target)
    elif damage == "invalid_schema":
        write_rows(path, [{"event_type": "invented"}])
    else:
        monkeypatch.setattr(research_scope, "MAX_SOURCE_BYTES", 1)
    assert client.get(f"/api/{endpoint}?research_scope=active").status_code == 503


def test_active_human_card_does_not_inherit_mixed_collection_facts(setup):
    root, client, _, _ = setup
    write_rows(root / "memory/idea_ledger.jsonl", ledger_events("iter-old", "iter-current"))
    history = client.get("/api/human_todo?research_scope=all").json()
    history_current = next(item for item in history["items"] if item["id"] == "iter-current")
    assert "L5" in history_current["doing"]
    current = client.get("/api/human_todo?research_scope=active").json()
    card = next(item for item in current["items"] if item["id"] == "iter-current")
    assert "cluster" not in card
    assert "L5" not in card["doing"]
    assert "iter-old" not in json.dumps(card)
    assert client.get("/api/ladder?research_scope=active").json()["clusters"] == []


def test_active_human_card_retains_exclusively_current_collection_facts(setup):
    root, client, _, _ = setup
    write_rows(root / "memory/idea_ledger.jsonl", ledger_events("iter-current"))
    current = client.get("/api/human_todo?research_scope=active").json()
    card = next(item for item in current["items"] if item["id"] == "iter-current")
    assert card["cluster"]["cluster_id"] == "cl-campaign"
    assert "L5" in card["doing"]
    assert len(client.get("/api/ladder?research_scope=active").json()["clusters"]) == 1


def test_active_experiment_verdict_uses_only_admitted_json_not_legacy_sidecar(setup, monkeypatch):
    root, client, current, _ = setup
    results = root / "experiments/exp001_repeated_pd/results"
    results.mkdir(parents=True)
    summary = {"campaign": current["campaign"], "per_opponent": [
        {"opponent": "old", "llm_mean": 1.0, "baseline_mean": 2.0,
         "delta": -1.0, "ci95": [-2.0, -0.5], "verdict": "NO"},
    ]}
    (results / "summary.json").write_text(json.dumps(summary))
    external = root / "external.md"
    external.write_text("**Verdict: YES from unrelated research**\n")
    (results / "summary.md").symlink_to(external)
    monkeypatch.setattr(experiments, "_resolve_headline", lambda _: pytest.fail("active verdict reopened legacy sidecars"))
    data = client.get("/api/research?research_scope=active").json()
    entry = data["tiers"][0]["experiments"][0]
    assert "unrelated" not in json.dumps(entry)


def test_active_experiment_rejects_mismatched_named_identity(setup):
    root, client, current, _ = setup
    results = root / "experiments/exp001_repeated_pd/results"
    results.mkdir(parents=True)
    (results / "summary.json").write_text(json.dumps({
        "campaign": current["campaign"], "experiment_id": "exp-old-reused", "verdict": "YES",
    }))
    data = client.get("/api/research?research_scope=active").json()
    assert all(not tier["experiments"] for tier in data["tiers"])


def test_multiple_current_bubbles_are_distinct_and_acknowledge_individually(setup):
    root, client, current, _ = setup
    bubbles = [{"run_id": "cycle-current", "step_id": f"cycle-current:step:{index}",
                "campaign": current["campaign"], "note": f"ask {index}"} for index in (1, 2)]
    write_rows(root / "memory/coordinator_bubbles.jsonl", bubbles)
    data = client.get("/api/human_todo?research_scope=active").json()
    assert {i["id"] for i in data["items"] if i["kind"] == "bubble_ack"} == {
        "cycle-current:step:1", "cycle-current:step:2",
    }
    write_rows(root / "memory/coordinator_acks.jsonl", [{"bubble_run_id": "cycle-current:step:1"}])
    data = client.get("/api/human_todo?research_scope=active").json()
    assert [i["id"] for i in data["items"] if i["kind"] == "bubble_ack"] == ["cycle-current:step:2"]
    write_rows(root / "memory/coordinator_acks.jsonl", [{"bubble_run_id": "cycle-current"}])
    assert client.get("/api/human_todo?research_scope=active").json()["counts"]["bubble_ack"] == 0


def test_modern_bubble_identity_collision_with_history_is_excluded(setup):
    root, client, current, _ = setup
    write_rows(root / "memory/coordinator_bubbles.jsonl", [
        {"run_id": "cycle", "step_id": "cycle:step:1", "campaign": current["campaign"], "note": "current"},
        {"run_id": "cycle:step:1", "note": "old colliding record"},
    ])
    assert client.get("/api/human_todo?research_scope=active").json()["counts"]["bubble_ack"] == 0
