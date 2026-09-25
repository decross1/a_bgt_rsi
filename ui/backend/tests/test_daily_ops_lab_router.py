"""LabMailboxRouter: owner decision buttons write ONE row to the lab mailbox.

Covers the D-084 owner-ui authority write path: authorize() reuses the same
Origin allowlist + bearer token contract as DailyOpsBridge, and route_decision
writes exactly one row via the real orchestrator.oracle_mailbox.post_once, never a
second, and only when authorized.
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from backend import daily_ops_bridge, daily_ops_live as live
from backend.app import create_app
from backend.daily_ops_bridge import LabMailboxRouter

live._orchestrator()  # puts the checkout's orchestrator on sys.path
from orchestrator import oracle_mailbox  # noqa: E402

REVISION = "2026-09-23"


def _private(path: Path):
    path.mkdir(parents=True, mode=0o700)
    path.chmod(0o700)
    return path


def _install_plan(root: Path):
    plans = _private(root / "run_state" / "daily_plans") if not (root / "run_state" / "daily_plans").exists() \
        else root / "run_state" / "daily_plans"
    plans.mkdir(parents=True, exist_ok=True)
    plan = {
        "date": REVISION, "week_alignment": "G0 first.",
        "bottlenecks": [],
        "items": [
            {"id": "d1", "owner": "oracle", "lane": "oracle_dev", "goal": "G7.1",
             "repo": "a_bgt_rsi", "title": "Lane precheck gate", "why_today": "x",
             "allowed_write_paths": ["orchestrator/nara_lane.py"], "acceptance": "Tests pass.",
             "depends_on": [], "flash_minutes": 10},
            {"id": "d2", "owner": "nara", "lane": "nara_dev", "goal": "G7.1",
             "repo": "a_bgt_rsi", "title": "Lab state packet", "why_today": "x",
             "allowed_write_paths": ["tools/lab_state_packet.py"], "acceptance": "Tests pass.",
             "depends_on": [], "flash_minutes": 10},
        ],
    }
    (plans / f"{REVISION}.json").write_text(json.dumps(plan))
    return plan


@pytest.fixture()
def repo(tmp_path):
    _install_plan(tmp_path)
    return tmp_path


@pytest.fixture()
def config(tmp_path):
    private = _private(tmp_path / "private")
    (private / "owner.key").write_text("k" * 48 + "\n", encoding="ascii")
    (private / "owner.key").chmod(0o600)
    return {"private_root": str(private), "allowed_origins": ["http://10.0.0.73:5173"]}


def _request(*, token="k" * 48, origin="http://10.0.0.73:5173"):
    headers = []
    if token is not None:
        headers.append((b"authorization", f"Bearer {token}".encode()))
    if origin is not None:
        headers.append((b"origin", origin.encode()))
    return Request({"type": "http", "method": "POST", "path": "/api/daily-ops/decisions",
                    "headers": headers, "query_string": b"", "server": ("test", 80),
                    "client": ("10.0.0.4", 4000), "scheme": "http"})


def _append_unchecked_mailbox_row(path: Path, row: dict, *, generate_msg_id: bool = True) -> dict:
    """Append a correctly chained row while bypassing current writer validation."""
    existing = oracle_mailbox.read(path)
    unchecked = {**row, "prev_sha256": existing[-1]["row_sha256"] if existing else None}
    if generate_msg_id:
        actor = unchecked["actor"]
        unchecked["msg_id"] = (
            f"{actor.split(':')[0]}-"
            f"{hashlib.sha256(oracle_mailbox._canonical(unchecked)).hexdigest()[:16]}"
        )
    unchecked["row_sha256"] = hashlib.sha256(oracle_mailbox._canonical(unchecked)).hexdigest()
    with path.open("a") as handle:
        handle.write(json.dumps(unchecked) + "\n")
    return unchecked


def test_authorized_decision_writes_exactly_one_correctly_shaped_row(repo, config):
    router = LabMailboxRouter(config, repo_root=repo)
    assert router.authorize(_request()) is True
    receipt = router.route_decision({
        "request_id": "11111111-1111-1111-1111-111111111111",
        "target_kind": "work_card", "target_id": "d1", "action": "approve",
        "expected_plan_revision": REVISION, "note": "Go ahead.",
    })
    assert receipt["status"] == "queued"
    assert receipt["duplicate"] is False
    assert receipt["execution_available"] is False

    rows = oracle_mailbox.read(repo / "run_state" / "oracle_nara_mailbox.jsonl")
    assert len(rows) == 1
    row = rows[0]
    assert row["actor"] == "human:derrick"
    assert row["kind"] == "note"
    assert row["to"] == "oracle"  # d1's lane is oracle_dev
    assert row["body"]["decision"] == "approve"
    assert row["body"]["target"] == {"plan": REVISION, "item": "d1"}
    assert row["body"]["text"] == "Go ahead."
    assert row["body"]["via"] == "owner-ui"
    assert row["body"]["authority"] == "owner, D-084"
    assert row["body"]["title"] == f"OWNER DECISION: approve {REVISION}:d1"


def test_nara_dev_item_routes_to_nara(repo, config):
    router = LabMailboxRouter(config, repo_root=repo)
    router.route_decision({
        "request_id": "22222222-2222-2222-2222-222222222222",
        "target_kind": "work_card", "target_id": "d2", "action": "decline",
        "expected_plan_revision": REVISION, "note": "",
    })
    rows = oracle_mailbox.read(repo / "run_state" / "oracle_nara_mailbox.jsonl")
    assert rows[-1]["to"] == "nara"


def test_plan_retry_survives_a_later_plan_revision_and_rejects_changed_payload(repo, config):
    router = LabMailboxRouter(config, repo_root=repo)
    payload = {
        "request_id": "21212121-2121-2121-2121-212121212121",
        "target_kind": "work_card", "target_id": "d1", "action": "approve",
        "expected_plan_revision": REVISION, "note": "Go ahead.",
    }
    assert router.route_decision(payload)["duplicate"] is False
    old_plan = json.loads((repo / "run_state" / "daily_plans" / f"{REVISION}.json").read_text())
    old_plan["date"] = "2026-09-24"
    (repo / "run_state" / "daily_plans" / "2026-09-24.json").write_text(json.dumps(old_plan))

    retry = router.route_decision(payload)
    assert retry["duplicate"] is True
    assert len(oracle_mailbox.read(repo / "run_state" / "oracle_nara_mailbox.jsonl")) == 1

    with pytest.raises(HTTPException, match="idempotency_key"):
        router.route_decision({**payload, "note": "Actually hold."})


def test_reprioritize_persists_priority_and_rejects_changed_priority_retry(repo, config):
    router = LabMailboxRouter(config, repo_root=repo)
    payload = {
        "request_id": "23232323-2323-2323-2323-232323232323",
        "target_kind": "work_card", "target_id": "d1", "action": "reprioritize",
        "expected_plan_revision": REVISION, "note": "Move this up.", "priority": "now",
    }

    assert router.route_decision(payload)["duplicate"] is False
    mailbox = repo / "run_state" / "oracle_nara_mailbox.jsonl"
    rows = oracle_mailbox.read(mailbox)
    assert len(rows) == 1
    assert rows[0]["body"]["priority"] == "now"
    assert router.route_decision(payload)["duplicate"] is True

    with pytest.raises(HTTPException, match="idempotency_key") as caught:
        router.route_decision({**payload, "priority": "later"})
    assert caught.value.status_code == 409
    assert len(oracle_mailbox.read(mailbox)) == 1


def test_reply_to_a_question_posts_an_answer_in_reply_to_it(repo, config):
    mailbox = repo / "run_state" / "oracle_nara_mailbox.jsonl"
    question = oracle_mailbox.post("oracle", "question", {"title": "What next?"}, to="owner", path=mailbox)
    router = LabMailboxRouter(config, repo_root=repo)
    receipt = router.route_decision({
        "request_id": "33333333-3333-3333-3333-333333333333",
        "target_kind": "question", "target_id": question["msg_id"], "action": "reply",
        "expected_plan_revision": REVISION, "note": "Do the safe thing.",
    })
    assert receipt["target_kind"] == "question"
    rows = oracle_mailbox.read(mailbox)
    answer = rows[-1]
    assert answer["kind"] == "answer"
    assert answer["actor"] == "human:derrick"
    assert answer["to"] == "oracle"
    assert answer["in_reply_to"] == question["msg_id"]
    assert answer["body"]["text"] == "Do the safe thing."
    assert answer["body"]["expected_plan_revision"] == REVISION
    retry = router.route_decision({
        "request_id": "33333333-3333-3333-3333-333333333333",
        "target_kind": "question", "target_id": question["msg_id"], "action": "reply",
        "expected_plan_revision": REVISION, "note": "Do the safe thing.",
    })
    assert retry["duplicate"] is True
    assert len(oracle_mailbox.read(mailbox)) == 2
    with pytest.raises(HTTPException, match="no longer open"):
        router.route_decision({
            "request_id": "34333333-3333-3333-3333-333333333333",
            "target_kind": "question", "target_id": question["msg_id"], "action": "reply",
            "expected_plan_revision": REVISION, "note": "A second answer.",
        })
    assert len(oracle_mailbox.read(mailbox)) == 2


def test_question_retry_binds_expected_plan_revision(repo, config):
    mailbox = repo / "run_state" / "oracle_nara_mailbox.jsonl"
    question = oracle_mailbox.post("oracle", "question", {"title": "What next?"}, to="owner", path=mailbox)
    router = LabMailboxRouter(config, repo_root=repo)
    payload = {
        "request_id": "35333333-3333-3333-3333-333333333333",
        "target_kind": "question", "target_id": question["msg_id"], "action": "reply",
        "expected_plan_revision": REVISION, "note": "Do the safe thing.",
    }
    assert router.route_decision(payload)["duplicate"] is False
    assert router.route_decision(payload)["duplicate"] is True
    with pytest.raises(HTTPException, match="idempotency_key") as caught:
        router.route_decision({**payload, "expected_plan_revision": "2026-09-24"})
    assert caught.value.status_code == 409
    assert len(oracle_mailbox.read(mailbox)) == 2


@pytest.mark.parametrize(("poison_schema", "forced_msg_id"), [
    ("oracle-nara-mailbox/v999", None),
    (oracle_mailbox.SCHEMA, "human-not-writer-derived"),
])
def test_router_quarantines_malformed_owner_answer_for_retry_and_fresh_request(
        repo, config, poison_schema, forced_msg_id):
    mailbox = repo / "run_state" / "oracle_nara_mailbox.jsonl"
    router = LabMailboxRouter(config, repo_root=repo)
    question = oracle_mailbox.post("oracle", "question", {"title": "Proceed?"}, to="owner", path=mailbox)
    retry_payload = {
        "request_id": "37333333-3333-3333-3333-333333333333",
        "target_kind": "question", "target_id": question["msg_id"], "action": "approve",
        "expected_plan_revision": REVISION, "note": "Proceed safely.",
    }
    malformed_body = {
        "text": "Proceed safely.", "via": "owner-ui", "authority": "owner, D-084",
        "request_id": retry_payload["request_id"], "target_kind": "question",
        "expected_plan_revision": REVISION, "decision": "approve",
    }
    poison = {
        "schema": poison_schema, "seq": 2, "ts": "2026-09-25T00:00:01+00:00",
        "actor": "human:derrick", "to": "oracle", "kind": "answer",
        "in_reply_to": question["msg_id"], "body": malformed_body, "expires_at": None,
    }
    if forced_msg_id is not None:
        poison["msg_id"] = forced_msg_id
    _append_unchecked_mailbox_row(mailbox, poison, generate_msg_id=forced_msg_id is None)

    accepted = router.route_decision(retry_payload)
    assert accepted["duplicate"] is False
    rows = oracle_mailbox.read(mailbox)
    assert len(rows) == 3 and rows[-1]["schema"] == oracle_mailbox.SCHEMA
    assert router.route_decision(retry_payload)["duplicate"] is True
    with pytest.raises(HTTPException, match="no longer open"):
        router.route_decision({**retry_payload, "request_id": "38333333-3333-3333-3333-333333333333"})

    second = oracle_mailbox.post("oracle", "question", {"title": "Proceed again?"}, to="owner", path=mailbox)
    second_poison = {
        "schema": poison_schema, "seq": 5, "ts": "2026-09-25T00:00:02+00:00",
        "actor": "human:derrick", "to": "oracle", "kind": "answer",
        "in_reply_to": second["msg_id"],
        "body": {
            "text": "malformed", "via": "owner-ui", "authority": "owner, D-084",
            "request_id": "39333333-3333-3333-3333-333333333333", "target_kind": "question",
            "expected_plan_revision": REVISION,
        },
        "expires_at": None,
    }
    if forced_msg_id is not None:
        second_poison["msg_id"] = forced_msg_id + "-second"
    _append_unchecked_mailbox_row(
        mailbox, second_poison, generate_msg_id=forced_msg_id is None,
    )
    fresh = router.route_decision({
        "request_id": "40333333-3333-3333-3333-333333333333",
        "target_kind": "question", "target_id": second["msg_id"], "action": "reply",
        "expected_plan_revision": REVISION, "note": "This is the valid answer.",
    })
    assert fresh["duplicate"] is False
    assert oracle_mailbox.read(mailbox)[-1]["body"]["text"] == "This is the valid answer."


def test_plan_append_rechecks_currentness_at_its_linearization_point(repo, config, monkeypatch):
    router = LabMailboxRouter(config, repo_root=repo)
    original = daily_ops_bridge.current_plan
    calls = 0

    def rollover(root):
        nonlocal calls
        calls += 1
        if calls == 1:
            return original(root)
        newer = _install_plan(root)
        newer["date"] = "2026-09-24"
        return "2026-09-24", newer

    monkeypatch.setattr(daily_ops_bridge, "current_plan", rollover)
    with pytest.raises(HTTPException, match="plan revision changed") as caught:
        router.route_decision({
            "request_id": "36333333-3333-3333-3333-333333333333",
            "target_kind": "work_card", "target_id": "d1", "action": "approve",
            "expected_plan_revision": REVISION, "note": "Proceed.",
        })
    assert caught.value.status_code == 409
    assert calls == 2
    assert not (repo / "run_state" / "oracle_nara_mailbox.jsonl").exists()


def test_approve_on_a_question_posts_a_direct_human_answer(repo, config):
    mailbox = repo / "run_state" / "oracle_nara_mailbox.jsonl"
    question = oracle_mailbox.post("oracle", "question", {"title": "Proceed?"}, to="owner", path=mailbox)
    router = LabMailboxRouter(config, repo_root=repo)
    router.route_decision({
        "request_id": "44444444-4444-4444-4444-444444444444",
        "target_kind": "question", "target_id": question["msg_id"], "action": "approve",
        "expected_plan_revision": REVISION, "note": "",
    })
    rows = oracle_mailbox.read(mailbox)
    answer = rows[-1]
    assert answer["kind"] == "answer"
    assert answer["actor"] == "human:derrick"
    assert answer["in_reply_to"] == question["msg_id"]
    assert answer["body"]["decision"] == "approve"


def test_unauthorized_or_wrong_origin_never_writes(repo, config):
    router = LabMailboxRouter(config, repo_root=repo)
    assert router.authorize(_request(token="wrong" * 10)) is False
    assert router.authorize(_request(origin="http://evil.example")) is False
    mailbox = repo / "run_state" / "oracle_nara_mailbox.jsonl"
    assert not mailbox.exists()


def test_unknown_decision_target_or_action_is_rejected(repo, config):
    router = LabMailboxRouter(config, repo_root=repo)
    with pytest.raises(HTTPException):
        router.route_decision({
            "request_id": "55555555-5555-5555-5555-555555555555",
            "target_kind": "work_card", "target_id": "does-not-exist", "action": "approve",
            "expected_plan_revision": REVISION, "note": "",
        })
    assert not (repo / "run_state" / "oracle_nara_mailbox.jsonl").exists()


def test_over_long_text_is_rejected_before_it_reaches_the_router():
    from backend.daily_ops import _decision_payload
    with pytest.raises(HTTPException):
        _decision_payload({
            "request_id": "66666666-6666-6666-6666-666666666666",
            "target_kind": "work_card", "target_id": "d1", "action": "modify",
            "expected_plan_revision": REVISION, "note": "x" * 3001,
        })


def test_end_to_end_via_the_http_decision_route(repo, config, monkeypatch):
    router = LabMailboxRouter(config, repo_root=repo)
    app = create_app(
        loop_v0_repo=repo, loop_v0_run_state=repo / "run_state", loop_v0_journal=repo / "journal",
        loop_v0_memory=repo / "memory" / "loop_memory.jsonl",
        coordinator_run_state=repo / "run_state", coordinator_memory=repo / "memory",
        daily_ops_authorizer=router.authorize, daily_ops_router=None,
        daily_ops_decision_router=router.route_decision,
        daily_ops_live_summary=lambda: {
            "schema_version": "daily-ops-summary/v3", "generated_at": "2026-09-23T00:00:00Z",
            "current_plan_revision": None, "daily_plan": None,
            "research_focus": {"status": "none", "observed_at": "2026-09-23T00:00:00Z"},
            "work_items": [], "waiting_on_you": [], "question_updates": [],
            "accomplishments": [], "improvements": [],
            "agents": {}, "warnings": [], "sources": {"plan": None, "mailbox": None, "focus": None, "git": None},
        },
    )
    client = TestClient(app)
    response = client.post("/api/daily-ops/decisions", json={
        "request_id": "77777777-7777-7777-7777-777777777777",
        "target_kind": "work_card", "target_id": "d1", "action": "defer",
        "expected_plan_revision": REVISION, "note": "Not this week.",
    }, headers={"Authorization": "Bearer " + "k" * 48, "Origin": "http://10.0.0.73:5173"})
    assert response.status_code == 200, response.text
    rows = oracle_mailbox.read(repo / "run_state" / "oracle_nara_mailbox.jsonl")
    assert len(rows) == 1
    assert rows[0]["body"]["decision"] == "defer"

    # No Authorization header -> unauthorized, and nothing new is written.
    response = client.post("/api/daily-ops/decisions", json={
        "request_id": "88888888-8888-8888-8888-888888888888",
        "target_kind": "work_card", "target_id": "d2", "action": "approve",
        "expected_plan_revision": REVISION,
    }, headers={"Origin": "http://10.0.0.73:5173"})
    assert response.status_code == 403
    rows = oracle_mailbox.read(repo / "run_state" / "oracle_nara_mailbox.jsonl")
    assert len(rows) == 1


def test_http_plan_linked_question_approve_is_a_direct_answer_and_closes_projected_card(repo, config):
    """The plan-card click answers its concrete question through the authenticated route."""
    path = repo / "run_state" / "daily_plans" / f"{REVISION}.json"
    plan = json.loads(path.read_text())
    plan["items"][0]["lane"] = "owner_decision"
    path.write_text(json.dumps(plan))
    mailbox = repo / "run_state" / "oracle_nara_mailbox.jsonl"
    question = oracle_mailbox.post("oracle", "question", {
        "question": "Approve the safe rollout?", "ref": {"item": "d1"},
    }, to="owner", path=mailbox)
    router = LabMailboxRouter(config, repo_root=repo)
    from backend import daily_ops
    api = FastAPI()
    daily_ops.register(api, state_dir=repo / "state", owner_authorizer=router.authorize,
                       decision_router=router.route_decision)
    endpoint = next(route.endpoint for route in api.routes if route.path == "/api/daily-ops/decisions")
    receipt = endpoint(_request(), {
        "request_id": "99999999-9999-9999-9999-999999999999",
        "target_kind": "question", "target_id": question["msg_id"], "action": "approve",
        "expected_plan_revision": REVISION, "note": "Proceed with the safe rollout.",
    })
    assert receipt["target_kind"] == "question" and receipt["duplicate"] is False
    rows = oracle_mailbox.read(mailbox)
    answer = rows[-1]
    assert (answer["kind"], answer["actor"], answer["in_reply_to"], answer["body"]["decision"]) == (
        "answer", "human:derrick", question["msg_id"], "approve")
    first_written = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    items, claimed = live.work_items(plan, rows, {}, live._Git(repo), datetime.now(timezone.utc), first_written)
    assert items[0]["status"] == "answered"
    assert live.waiting_on_you(REVISION, items, claimed, rows, first_written.isoformat()) == []
