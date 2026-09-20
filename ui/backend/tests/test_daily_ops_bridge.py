import json
import subprocess
import uuid
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from backend import daily_ops_bridge as bridge_module
from backend.daily_ops_bridge import DailyOpsBridge


SESSION = "01a0bbce-8fe5-7290-8ea6-2f247da2115e"
NOW = datetime(2026, 9, 20, 9, 0, tzinfo=timezone.utc)
REVISION = "b" * 64


def _iso(value=NOW):
    return value.isoformat().replace("+00:00", "Z")


def _private(path: Path):
    path.mkdir(parents=True, mode=0o700)
    path.chmod(0o700)
    return path


def _json(path: Path, value, *, mode=0o600):
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")
    path.chmod(mode)


def _brief():
    base = {"detail": "Verified source-linked state.", "source": "test receipt",
            "observed_at": _iso()}
    return {
        "schema_version": "daily-ops-summary/v1", "generated_at": _iso(),
        "current_plan_revision": None,
        "goals": [{"id": "gate", "title": "Close the next gate",
                   "status": "in_progress", "owner": "oracle", **base}],
        "accomplishments": [{"id": "done", "title": "Bounded context",
                             "status": "complete", **base}],
        "improvements": [{"id": "memory", "title": "Targeted recall",
                          "status": "verified", **base}],
        "research_focus": {
            "focus_id": "payoff-assistance", "title": "Payoff assistance",
            "status": "selected", "stage": "calibration",
            "next_action": "Repair and replay the tool contract.",
            "next_gate": {"from": "calibration", "to": "registration",
                          "artifact": "fresh receipt", "status": "pending",
                          "owner": "lab"},
            "blockers": ["fresh replay required"],
            "source_receipt_sha256": "a" * 64, "observed_at": _iso(),
        },
        "agents": {
            "oracle": {"label": "Oracle", "status": "unknown", **base},
            "pi_client": {"label": "Pi client", "status": "unknown", **base},
            "nara": {"label": "Nara runner", "status": "idle", **base},
        },
        "warnings": [],
    }


@pytest.fixture()
def relay(tmp_path, monkeypatch):
    monkeypatch.setattr(bridge_module, "_now", lambda: NOW)
    # The sealed SQLite reader has its own integration/tamper suite. Relay
    # tests isolate its validated projection interface from mailbox behavior.
    monkeypatch.setattr(bridge_module, "read_pending_agenda", lambda latest, focus: {
        "revision": json.loads(Path(latest).read_text())["revision_sha256"],
        "goals": [], "warnings": [],
    })
    state = _private(tmp_path / "state")
    private = _private(tmp_path / "private")
    mailbox = _private(tmp_path / "mailbox")
    for name in ("inbox", "processing", "processed", "failed", "outbox"):
        _private(mailbox / name)
    _json(private / "owner.key", "k" * 48)
    # _token expects the raw token rather than a JSON string.
    (private / "owner.key").write_text("k" * 48 + "\n", encoding="ascii")
    (private / "owner.key").chmod(0o600)
    _json(mailbox / "latest-status.json", {
        "schema_version": 1, "status": "active", "session_id": SESSION,
        "pending_count": 0, "updated_at": _iso(),
        "capabilities": {"review_scope": True, "durable_review_scope": True},
    })
    planner = private / "planner.json"
    _json(planner, {
        "schema_version": "oracle-daily-proposal-cycle/v1",
        "revision_sha256": REVISION,
        "expires_at": _iso(NOW + timedelta(hours=12)),
        "execution_enabled": False,
    })
    _json(state / "daily_ops_brief.json", _brief())
    config = {
        "private_root": str(private), "mailbox_root": str(mailbox),
        "session_id": SESSION, "allowed_origins": ["http://10.0.0.73:5173"],
        "planner_latest": str(planner),
    }
    return {
        "bridge": DailyOpsBridge(state, config), "state": state,
        "private": private, "mailbox": mailbox, "config": config,
    }


def _request(*, token="k" * 48, origin="http://10.0.0.73:5173"):
    headers = []
    if token is not None:
        headers.append((b"authorization", f"Bearer {token}".encode()))
    if origin is not None:
        headers.append((b"origin", origin.encode()))
    return Request({"type": "http", "method": "POST", "path": "/api/daily-ops/messages",
                    "headers": headers, "query_string": b"", "server": ("test", 80),
                    "client": ("10.0.0.4", 4000), "scheme": "http"})


def _payload(*, request_id=None, text="What blocks the next gate?",
             intent="question", revision=None):
    value = {"request_id": request_id or str(uuid.uuid4()), "target": "oracle",
             "intent": intent, "text": text}
    if revision is not None:
        value["expected_plan_revision"] = revision
    return value


def _receipt(relay, request_id, *, status, text=None):
    value = {"schema_version": 1, "id": "owner-ui-" + request_id,
             "session_id": SESSION, "status": status, "updated_at": _iso()}
    if text is not None:
        value["visible_final_text"] = text
    _json(relay["mailbox"] / "outbox" / ("owner-ui-" + request_id + ".json"), value)


def _force_refresh(relay):
    relay["bridge"]._last_refresh = 0.0
    relay["bridge"].refresh()
    return [json.loads(line) for line in
            (relay["state"] / "daily_ops_messages.jsonl").read_text().splitlines()]


def test_authorization_requires_exact_bearer_and_allowed_browser_origin(relay):
    bridge = relay["bridge"]
    assert bridge.authorize(_request()) is True
    assert bridge.authorize(_request(token="wrong" * 10)) is False
    assert bridge.authorize(_request(token=None)) is False
    assert bridge.authorize(_request(origin="http://evil.invalid")) is False
    # Non-browser local clients may omit Origin but still need the exact token.
    assert bridge.authorize(_request(origin=None)) is True


def test_route_writes_one_advisory_envelope_and_idempotent_duplicate(relay):
    payload = _payload()
    first = relay["bridge"].route(payload)
    second = relay["bridge"].route(payload)
    envelope_path = relay["mailbox"] / "inbox" / ("owner-ui-" + payload["request_id"] + ".json")
    envelope = json.loads(envelope_path.read_text())

    assert first == {"request_id": payload["request_id"], "status": "queued",
                     "accepted_at": _iso(), "duplicate": False,
                     "expected_plan_revision": None}
    assert second["duplicate"] is True
    assert envelope["authority"] == "advisory_only"
    assert envelope["approval_required"] is False
    assert envelope["session_id"] == SESSION
    assert payload["text"] in envelope["text"]
    assert envelope["review_scope"] == {
        "read_paths": [str(relay["state"] / "daily_ops_summary.json")],
        "draft_path": str(relay["mailbox"] / "review-drafts" / ("owner-ui-" + payload["request_id"] + ".md")),
    }
    assert len(list((relay["mailbox"] / "inbox").glob("*.json"))) == 1


@pytest.mark.parametrize("capabilities", [
    None,
    {"review_scope": True},
    {"durable_review_scope": True},
    {"review_scope": False, "durable_review_scope": True},
    {"review_scope": True, "durable_review_scope": False},
])
def test_owner_request_requires_scoped_and_durable_mailbox_enforcement(relay, capabilities):
    status_path = relay["mailbox"] / "latest-status.json"
    value = json.loads(status_path.read_text())
    if capabilities is None:
        value.pop("capabilities")
    else:
        value["capabilities"] = capabilities
    _json(status_path, value)
    with pytest.raises(HTTPException) as caught:
        relay["bridge"].route(_payload())
    assert caught.value.status_code == 503
    assert "update must be loaded" in caught.value.detail
    assert list(relay["bridge"].requests.iterdir()) == []
    assert list((relay["mailbox"] / "inbox").iterdir()) == []

    relay["bridge"]._last_refresh = 0.0
    relay["bridge"].refresh()
    summary = json.loads((relay["state"] / "daily_ops_summary.json").read_text())
    assert summary["agents"]["oracle"]["status"] == "degraded"
    assert summary["agents"]["pi_client"]["status"] == "degraded"
    assert "update must be loaded" in summary["agents"]["oracle"]["detail"]


def test_same_request_id_with_changed_payload_conflicts(relay):
    payload = _payload()
    relay["bridge"].route(payload)
    with pytest.raises(HTTPException) as caught:
        relay["bridge"].route({**payload, "text": "different"})
    assert caught.value.status_code == 409


def test_change_request_is_bound_to_current_unexpired_revision(relay):
    payload = _payload(intent="change_request", revision="c" * 64)
    with pytest.raises(HTTPException) as caught:
        relay["bridge"].route(payload)
    assert caught.value.status_code == 409
    assert not list((relay["bridge"].requests).glob("*.json"))

    accepted = relay["bridge"].route({**payload, "expected_plan_revision": REVISION})
    assert accepted["expected_plan_revision"] == REVISION


def test_durable_request_without_envelope_is_replayed_exactly(relay):
    payload = _payload()
    relay["bridge"].route(payload)
    envelope = relay["mailbox"] / "inbox" / ("owner-ui-" + payload["request_id"] + ".json")
    original = envelope.read_bytes()
    envelope.unlink()

    receipt = relay["bridge"].route(payload)
    assert receipt["duplicate"] is True
    assert envelope.read_bytes() == original


def test_encoded_mailbox_limit_rejects_before_durable_request(relay):
    payload = _payload(text="🧠" * 4096)
    with pytest.raises(HTTPException) as caught:
        relay["bridge"].route(payload)
    assert caught.value.status_code == 422
    assert not (relay["bridge"].requests / (payload["request_id"] + ".json")).exists()
    assert not (relay["mailbox"] / "inbox" /
                ("owner-ui-" + payload["request_id"] + ".json")).exists()


@pytest.mark.parametrize(
    ("mailbox_status", "expected_status", "expected_actor", "expected_intent"),
    [
        ("submitted", "delivered", "system", "receipt"),
        ("running", "delivered", "system", "receipt"),
        ("dispatch_error", "failed", "system", "receipt"),
        ("processing_failed", "failed", "system", "receipt"),
    ],
)
def test_real_mailbox_states_project_without_inventing_completion(
    relay, mailbox_status, expected_status, expected_actor, expected_intent,
):
    payload = _payload()
    relay["bridge"].route(payload)
    _receipt(relay, payload["request_id"], status=mailbox_status)
    rows = _force_refresh(relay)
    response_rows = [row for row in rows if row.get("in_reply_to") == payload["request_id"]]
    assert len(response_rows) == 1
    assert response_rows[0]["status"] == expected_status
    assert response_rows[0]["actor"] == expected_actor
    assert response_rows[0]["intent"] == expected_intent
    assert "complete" not in response_rows[0]["text"].lower()


def test_dispatching_before_send_does_not_claim_delivery(relay):
    payload = _payload()
    relay["bridge"].route(payload)
    _receipt(relay, payload["request_id"], status="dispatching")
    rows = _force_refresh(relay)
    assert [row for row in rows if row.get("in_reply_to") == payload["request_id"]] == []


def test_completed_turn_requires_visible_answer_to_project_oracle_reply(relay):
    payload = _payload()
    relay["bridge"].route(payload)
    _receipt(relay, payload["request_id"], status="completed",
             text="The fresh replay is the next gate.")
    rows = _force_refresh(relay)
    reply = next(row for row in rows if row.get("in_reply_to") == payload["request_id"])
    assert (reply["actor"], reply["intent"], reply["status"]) == (
        "oracle", "reply", "acknowledged")
    assert reply["text"] == "The fresh replay is the next gate."


def test_completed_turn_without_visible_answer_is_delivery_only(relay):
    payload = _payload()
    relay["bridge"].route(payload)
    _receipt(relay, payload["request_id"], status="completed", text="")
    rows = _force_refresh(relay)
    receipt = next(row for row in rows if row.get("in_reply_to") == payload["request_id"])
    assert (receipt["actor"], receipt["intent"], receipt["status"]) == (
        "system", "receipt", "delivered")
    assert "No task completion is inferred" in receipt["text"]


@pytest.mark.parametrize(
    ("status", "expected"),
    [("active", "idle"), ("running", "working"), ("processing_blocked", "degraded")],
)
def test_live_mailbox_states_are_observed_without_calling_work_offline(relay, status, expected):
    _json(relay["mailbox"] / "latest-status.json", {
        "schema_version": 1, "status": status, "session_id": SESSION,
        "pending_count": 1 if status != "active" else 0, "updated_at": _iso(),
        "capabilities": {"review_scope": True, "durable_review_scope": True},
    })
    relay["bridge"]._last_refresh = 0.0
    relay["bridge"].refresh()
    summary = json.loads((relay["state"] / "daily_ops_summary.json").read_text())
    assert summary["agents"]["oracle"]["status"] == expected
    assert summary["agents"]["pi_client"]["status"] == expected


def test_refresh_preserves_curated_notes_timestamp_across_day_rollover(relay):
    brief = _brief()
    prior_day = _iso(NOW - timedelta(days=1))
    brief["generated_at"] = prior_day
    _json(relay["state"] / "daily_ops_brief.json", brief)

    _force_refresh(relay)
    summary = json.loads((relay["state"] / "daily_ops_summary.json").read_text())

    assert summary["generated_at"] == prior_day
    assert summary["goals"][0]["status"] == "in_progress"
    assert summary["agents"]["nara"]["observed_at"] == _iso()


def test_running_mailbox_can_queue_but_processing_block_refuses(relay):
    _json(relay["mailbox"] / "latest-status.json", {
        "schema_version": 1, "status": "running", "session_id": SESSION,
        "pending_count": 1, "updated_at": _iso(),
        "capabilities": {"review_scope": True, "durable_review_scope": True},
    })
    queued = _payload()
    assert relay["bridge"].route(queued)["status"] == "queued"

    _json(relay["mailbox"] / "latest-status.json", {
        "schema_version": 1, "status": "processing_blocked", "session_id": SESSION,
        "pending_count": 1, "updated_at": _iso(),
        "capabilities": {"review_scope": True, "durable_review_scope": True},
    })
    blocked = _payload()
    with pytest.raises(HTTPException) as caught:
        relay["bridge"].route(blocked)
    assert caught.value.status_code == 503
    assert not (relay["bridge"].requests / (blocked["request_id"] + ".json")).exists()


def test_nara_observation_uses_fixed_systemd_query_and_cache(relay, monkeypatch):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, "active\n", "")

    monkeypatch.setattr(bridge_module.subprocess, "run", run)
    first = relay["bridge"]._observe_nara()
    second = relay["bridge"]._observe_nara()
    assert first == second
    assert first["status"] == "online"
    assert calls == [([
        "/usr/bin/systemctl", "--user", "show", "nara-daemon.service",
        "--property=ActiveState", "--value",
    ], {"capture_output": True, "text": True, "timeout": 1, "check": False})]


def test_focus_projection_is_bound_to_active_pointer_digest(relay):
    focus = {
        "schema_version": "research-focus-selection/v1",
        "focus_id": "fresh-focus", "title": "Fresh selected thesis",
        "stage": "blocked", "next_action": "Produce the fresh receipt.",
        "next_gate": {"from": "calibration", "to": "registration",
                      "artifact": "bound receipt", "status": "blocked",
                      "owner": "lab"},
        "blockers": ["receipt missing"], "selected_at": _iso(),
    }
    raw = (json.dumps(focus, sort_keys=True, separators=(",", ":")) + "\n").encode()
    sha = hashlib.sha256(raw).hexdigest()
    directory = relay["state"] / "research_focus"
    directory.mkdir()
    (directory / (sha + ".json")).write_bytes(raw)
    _json(relay["state"] / "active_research_focus.json", {
        "schema_version": "research-focus/v1", "receipt_sha256": sha,
    })

    _force_refresh(relay)
    summary = json.loads((relay["state"] / "daily_ops_summary.json").read_text())
    assert summary["research_focus"]["focus_id"] == "fresh-focus"
    assert summary["research_focus"]["status"] == "blocked"
    assert summary["research_focus"]["source_receipt_sha256"] == sha

    (directory / (sha + ".json")).write_bytes(raw + b" ")
    _force_refresh(relay)
    summary = json.loads((relay["state"] / "daily_ops_summary.json").read_text())
    assert summary["research_focus"] is None
    assert "Current research focus could not be verified." in summary["warnings"]


def test_projection_is_bounded_to_fifty_requests_and_one_hundred_rows(relay):
    requests = relay["bridge"].requests
    for ordinal in range(60):
        ident = str(uuid.UUID(int=ordinal + 1))
        record = {"payload": _payload(request_id=ident),
                  "accepted_at": _iso(NOW + timedelta(seconds=ordinal)),
                  "expires_at": _iso(NOW + timedelta(hours=6)),
                  "envelope_id": "owner-ui-" + ident}
        _json(requests / (ident + ".json"), record)
        _receipt(relay, ident, status="completed", text=f"reply {ordinal}")
    rows = _force_refresh(relay)
    assert len(rows) == 100
    owner_ids = {row["request_id"] for row in rows if row["actor"] == "owner"}
    assert len(owner_ids) == 50


def test_refresh_failure_after_durable_enqueue_does_not_turn_post_into_failure(relay, monkeypatch):
    payload = _payload()

    def fail_refresh():
        raise ValueError("projection source broke after enqueue")

    monkeypatch.setattr(relay["bridge"], "refresh", fail_refresh)
    receipt = relay["bridge"].route(payload)
    assert receipt["status"] == "queued"
    assert (relay["bridge"].requests / (payload["request_id"] + ".json")).exists()
    assert (relay["mailbox"] / "inbox" /
            ("owner-ui-" + payload["request_id"] + ".json")).exists()
