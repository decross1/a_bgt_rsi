import hashlib
import json
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from starlette.requests import Request

from backend.daily_ops import MESSAGES_SCHEMA, SUMMARY_SCHEMA, register


NOW = "2026-09-20T08:30:00Z"
REVISION = "agenda-20260920-r3"


def _summary():
    base = {
        "detail": "Bounded, source-linked operator summary.",
        "source": "verified runtime projection",
        "observed_at": NOW,
    }
    return {
        "schema_version": SUMMARY_SCHEMA,
        "generated_at": NOW,
        "current_plan_revision": REVISION,
        "goals": [{
            "id": "goal-1", "title": "Close the selected thesis gate",
            "status": "in_progress", "owner": "oracle", **base,
        }],
        "accomplishments": [{
            "id": "done-1", "title": "Replayed the calibration",
            "status": "complete", **base,
        }],
        "improvements": [{
            "id": "improvement-1", "title": "Bounded Oracle context",
            "status": "verified", **base,
        }],
        "research_focus": {
            "focus_id": "payoff-assistance",
            "title": "Exact payoff assistance and strategic planning",
            "status": "selected", "stage": "excluded calibration",
            "next_action": "Repair the tool contract and run a fresh calibration.",
            "next_gate": {
                "from": "excluded calibration replayed",
                "to": "registered study ready",
                "artifact": "fresh calibration receipt",
                "status": "pending", "owner": "lab",
            },
            "blockers": ["tool contract rejects benign assistant text"],
            "source_receipt_sha256": "a" * 64,
            "observed_at": NOW,
        },
        "agents": {
            "oracle": {
                "label": "Oracle steward", "status": "working",
                "detail": "Reviewing the selected thesis gate.",
                "source": base["source"], "observed_at": NOW,
            },
            "pi_client": {
                "label": "Pi client for Oracle", "status": "online",
                "detail": "Connected to Oracle after compaction.",
                "source": base["source"], "observed_at": NOW,
            },
            "nara": {
                "label": "Nara runner", "status": "idle",
                "detail": "Waiting on the selected research gate.",
                "source": base["source"], "observed_at": NOW,
            },
        },
        "warnings": [],
    }


def _message(*, request_id=None, actor="owner", intent="question",
             status="queued", text="What is blocking the next gate?",
             plan_revision=None, in_reply_to=None):
    row = {
        "request_id": request_id or str(uuid.uuid4()),
        "created_at": NOW, "actor": actor, "intent": intent,
        "status": status, "text": text, "target": "oracle",
        "plan_revision": plan_revision,
    }
    if in_reply_to is not None:
        row["in_reply_to"] = in_reply_to
    return row


def _endpoints(state_dir: Path, *, authorizer=None, router=None):
    app = FastAPI()
    register(app, state_dir=state_dir, owner_authorizer=authorizer,
             message_router=router)
    result = {}
    for route in app.routes:
        if not route.path.startswith("/api/daily-ops"):
            continue
        for method in route.methods or []:
            result[(route.path, method)] = route.endpoint
    return result


def _endpoint(routes, path, method):
    return routes[(path, method)]


def _request(token=None):
    headers = [] if token is None else [(b"authorization", f"Bearer {token}".encode())]
    return Request({
        "type": "http", "method": "POST", "path": "/api/daily-ops/messages",
        "headers": headers, "query_string": b"", "server": ("test", 80),
        "client": ("127.0.0.1", 1), "scheme": "http",
    })


def _write_summary(tmp_path: Path, value=None):
    raw = json.dumps(value or _summary(), separators=(",", ":")).encode()
    (tmp_path / "daily_ops_summary.json").write_bytes(raw)
    return raw


def _write_messages(tmp_path: Path, rows):
    (tmp_path / "daily_ops_messages.jsonl").write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_missing_sources_are_honest_and_write_is_fail_closed(tmp_path):
    routes = _endpoints(tmp_path)
    summary = _endpoint(routes, "/api/daily-ops/summary", "GET")()
    messages = _endpoint(routes, "/api/daily-ops/messages", "GET")(
        _request(), after=None, limit=50)
    assert summary["available"] is False
    assert summary["current_plan_revision"] is None
    assert summary["capabilities"] == {
        "auth_required": True, "write_available": False,
        "targets": ["oracle"], "intents": ["question", "change_request"],
        "nara_interaction": "ask_oracle_about_nara",
    }
    assert messages == {
        "schema_version": MESSAGES_SCHEMA, "available": False,
        "writable": False, "rows": [],
    }
    with pytest.raises(HTTPException, match="routing is not configured") as caught:
        _endpoint(routes, "/api/daily-ops/messages", "POST")(_request(), {
            "request_id": str(uuid.uuid4()), "target": "oracle",
            "intent": "question", "text": "Where are we stuck?",
        })
    assert caught.value.status_code == 503


def test_valid_summary_is_source_linked_and_explicit_about_agents(tmp_path):
    raw = _write_summary(tmp_path)
    routes = _endpoints(tmp_path, authorizer=lambda _request: True,
                        router=lambda _payload: {})
    body = _endpoint(routes, "/api/daily-ops/summary", "GET")()
    assert body["available"] is True
    assert body["source_sha256"] == hashlib.sha256(raw).hexdigest()
    assert body["current_plan_revision"] == REVISION
    assert body["agents"]["pi_client"]["label"] == "Pi client for Oracle"
    assert body["capabilities"]["write_available"] is True


@pytest.mark.parametrize("mutate", [
    lambda value: value.update({"surprise": "unbound"}),
    lambda value: value.update({"current_plan_revision": " bad "}),
    lambda value: value["agents"]["nara"].update(status="speaking_for_itself"),
    lambda value: value["research_focus"].update(source_receipt_sha256="not-a-hash"),
])
def test_invalid_summary_is_explicit_503(tmp_path, mutate):
    value = _summary()
    mutate(value)
    _write_summary(tmp_path, value)
    endpoint = _endpoint(_endpoints(tmp_path), "/api/daily-ops/summary", "GET")
    with pytest.raises(HTTPException, match="snapshot.*unavailable") as caught:
        endpoint()
    assert caught.value.status_code == 503


def test_summary_symlink_is_refused(tmp_path):
    source = tmp_path / "elsewhere.json"
    source.write_text(json.dumps(_summary()), encoding="utf-8")
    (tmp_path / "daily_ops_summary.json").symlink_to(source)
    endpoint = _endpoint(_endpoints(tmp_path), "/api/daily-ops/summary", "GET")
    with pytest.raises(HTTPException) as caught:
        endpoint()
    assert caught.value.status_code == 503


def test_message_projection_preserves_lifecycle_and_cursor(tmp_path):
    first = _message()
    second = _message(actor="system", intent="receipt", status="delivered",
                      text="Mailbox delivery observed.", in_reply_to=first["request_id"])
    third = _message(actor="oracle", intent="reply", status="acknowledged",
                     text="The fresh calibration is next.",
                     in_reply_to=first["request_id"], plan_revision=REVISION)
    _write_messages(tmp_path, [first, second, third])
    endpoint = _endpoint(_endpoints(
        tmp_path, authorizer=lambda _request: True, router=lambda _payload: {}
    ), "/api/daily-ops/messages", "GET")
    body = endpoint(_request(), after=None, limit=50)
    assert body["available"] is True and body["writable"] is True
    assert body["rows"] == [first, second, third]
    assert endpoint(_request(), after=first["request_id"], limit=10)["rows"] == [second, third]


def test_configured_message_thread_requires_owner_authentication(tmp_path):
    _write_messages(tmp_path, [_message()])
    endpoint = _endpoint(_endpoints(
        tmp_path, authorizer=lambda request: request.headers.get("authorization") == "Bearer key",
        router=lambda _payload: {},
    ), "/api/daily-ops/messages", "GET")
    with pytest.raises(HTTPException) as caught:
        endpoint(_request(), after=None, limit=50)
    assert caught.value.status_code == 403
    assert endpoint(_request("key"), after=None, limit=50)["available"] is True


def test_projection_refresher_runs_before_reads_and_route(tmp_path):
    _write_summary(tmp_path)
    _write_messages(tmp_path, [])
    refreshed = []
    request_id = str(uuid.uuid4())
    app = FastAPI()
    register(
        app,
        state_dir=tmp_path,
        owner_authorizer=lambda _request: True,
        message_router=lambda _payload: {
            "request_id": request_id, "status": "queued", "accepted_at": NOW,
            "duplicate": False, "expected_plan_revision": None,
        },
        projection_refresher=lambda: refreshed.append("refresh"),
    )
    routes = {}
    for route in app.routes:
        for method in route.methods or []:
            routes[(route.path, method)] = route.endpoint
    _endpoint(routes, "/api/daily-ops/summary", "GET")()
    _endpoint(routes, "/api/daily-ops/messages", "GET")(
        _request(), after=None, limit=50)
    _endpoint(routes, "/api/daily-ops/messages", "POST")(_request(), {
        "request_id": request_id, "target": "oracle", "intent": "question",
        "text": "What is the next gate?",
    })
    assert refreshed == ["refresh", "refresh", "refresh"]


def test_unknown_cursor_and_actor_shaped_row_fail_closed(tmp_path):
    _write_messages(tmp_path, [_message()])
    endpoint = _endpoint(_endpoints(
        tmp_path, authorizer=lambda _request: True, router=lambda _payload: {}
    ), "/api/daily-ops/messages", "GET")
    with pytest.raises(HTTPException) as caught:
        endpoint(_request(), after=str(uuid.uuid4()), limit=50)
    assert caught.value.status_code == 409

    _write_messages(tmp_path, [_message(actor="nara")])
    with pytest.raises(HTTPException, match="unavailable or invalid") as caught:
        endpoint(_request(), after=None, limit=50)
    assert caught.value.status_code == 503


def test_owner_question_is_authenticated_and_routed_exactly(tmp_path):
    calls = []
    request_id = str(uuid.uuid4())
    payload = {"request_id": request_id, "target": "oracle",
               "intent": "question", "text": "Ask Oracle why Nara is idle."}

    def authorize(request):
        calls.append(("auth", request.headers.get("authorization")))
        return request.headers.get("authorization") == "Bearer owner-key"

    def route(value):
        calls.append(("route", value))
        return {"request_id": request_id, "status": "queued",
                "accepted_at": NOW, "duplicate": False,
                "expected_plan_revision": None}

    endpoint = _endpoint(_endpoints(
        tmp_path, authorizer=authorize, router=route
    ), "/api/daily-ops/messages", "POST")
    receipt = endpoint(_request("owner-key"), payload)
    assert receipt["status"] == "queued"
    assert calls == [("auth", "Bearer owner-key"), ("route", payload)]


def test_auth_failure_never_calls_router(tmp_path):
    routed = []
    endpoint = _endpoint(_endpoints(
        tmp_path, authorizer=lambda _request: False,
        router=lambda value: routed.append(value),
    ), "/api/daily-ops/messages", "POST")
    with pytest.raises(HTTPException) as caught:
        endpoint(_request(), {"request_id": str(uuid.uuid4()),
                              "target": "oracle", "intent": "question",
                              "text": "Where are we stuck?"})
    assert caught.value.status_code == 403 and routed == []


def test_change_request_requires_and_binds_revision(tmp_path):
    request_id = str(uuid.uuid4())
    routed = []
    endpoint = _endpoint(_endpoints(
        tmp_path, authorizer=lambda _request: True,
        router=lambda value: routed.append(value) or {
            "request_id": request_id, "status": "queued", "accepted_at": NOW,
            "duplicate": False, "expected_plan_revision": REVISION,
        },
    ), "/api/daily-ops/messages", "POST")
    base = {"request_id": request_id, "target": "oracle",
            "intent": "change_request",
            "text": "Prioritize the tool-contract repair."}
    with pytest.raises(HTTPException) as caught:
        endpoint(_request(), base)
    assert caught.value.status_code == 422 and routed == []
    receipt = endpoint(_request(), {**base, "expected_plan_revision": REVISION})
    assert receipt["expected_plan_revision"] == REVISION


@pytest.mark.parametrize("payload", [
    {"target": "nara", "intent": "question", "text": "Speak as Nara"},
    {"target": "oracle", "intent": "approval", "text": "Approve all work"},
    {"target": "oracle", "intent": "question", "text": "x", "execute": True},
])
def test_unsafe_or_unbound_shape_rejected_before_routing(tmp_path, payload):
    routed = []
    endpoint = _endpoint(_endpoints(
        tmp_path, authorizer=lambda _request: True,
        router=lambda value: routed.append(value),
    ), "/api/daily-ops/messages", "POST")
    with pytest.raises(HTTPException) as caught:
        endpoint(_request(), {"request_id": str(uuid.uuid4()), **payload})
    assert caught.value.status_code == 422 and routed == []


def test_router_cannot_claim_delivery_as_immediate_success(tmp_path):
    request_id = str(uuid.uuid4())
    endpoint = _endpoint(_endpoints(
        tmp_path, authorizer=lambda _request: True,
        router=lambda _value: {
            "request_id": request_id, "status": "delivered", "accepted_at": NOW,
            "duplicate": False, "expected_plan_revision": None,
        },
    ), "/api/daily-ops/messages", "POST")
    with pytest.raises(HTTPException, match="invalid receipt") as caught:
        endpoint(_request(), {"request_id": request_id, "target": "oracle",
                              "intent": "question", "text": "What happened?"})
    assert caught.value.status_code == 502
