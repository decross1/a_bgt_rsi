import asyncio
import hashlib
import json
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

from backend.daily_ops import (
    LEGACY_SUMMARY_SCHEMA,
    MESSAGES_SCHEMA,
    SUMMARY_SCHEMA,
    _private_cache_headers,
    register,
)

NOW = "2026-09-20T08:30:00Z"
REVISION = "agenda-20260920-r3"


def _summary():
    base = {
        "detail": "Bounded, source-linked operator summary.",
        "source": "verified runtime projection",
        "observed_at": NOW,
    }
    card = {
        "id": "runner", "title": "Complete the v2 runner",
        "what": "Build the versioned runner and deterministic replay path.",
        "benefit": "Makes a fresh shakedown technically possible and auditable.",
        "cost": {"summary": "4–8 engineering hours; 0 model/GPU hours.",
                 "kind": "estimate", "basis": "Reviewer planning estimate."},
        "conviction": {"score": 9, "kind": "estimate",
                       "basis": "Worth-doing judgment, not a scientific probability."},
        "worth_time": {"recommendation": "do_now",
                       "basis": "Closes the selected thesis's missing runner seam."},
        "status": "authorized", "owner": "codex", "depends_on": [],
        "source": "exact-revision semantic review", "observed_at": NOW,
        "approval_required": False,
        "actions": ["modify", "skip", "reprioritize"],
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
        "work_cards": [card],
        "agenda_decision": {
            "id": "agenda-20260920-r3", "agenda_id": "oracle-agenda-r3",
            "revision": REVISION, "title": "Request a corrected draft",
            "what": "Replace two stale tasks while preserving the selected thesis.",
            "reason": "Exact-revision semantic review found stale task content.",
            "disposition": "amend_required", "approval_required": False,
            "approve_enabled": False, "execution_available": False,
            "actions": ["modify", "skip"],
            "task_titles": ["Complete the v2 runner"],
            "source": "exact-revision semantic review", "observed_at": NOW,
        },
    }


def _message(*, request_id=None, actor="owner", intent="question",
             status="queued", text="What is blocking the next gate?",
             plan_revision=None, in_reply_to=None, responder_label=None):
    row = {
        "request_id": request_id or str(uuid.uuid4()),
        "created_at": NOW, "actor": actor, "intent": intent,
        "status": status, "text": text, "target": "oracle",
        "plan_revision": plan_revision,
    }
    if in_reply_to is not None:
        row["in_reply_to"] = in_reply_to
    if responder_label is not None:
        row["responder_label"] = responder_label
    return row


def _endpoints(state_dir: Path, *, authorizer=None, router=None,
               decision_router=None):
    app = FastAPI()
    register(app, state_dir=state_dir, owner_authorizer=authorizer,
             message_router=router, decision_router=decision_router)
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


def _get_request(path, token=None, *, method="GET", origin=None):
    headers = [] if token is None else [
        (b"authorization", f"Bearer {token}".encode()),
    ]
    if origin is not None:
        headers.append((b"origin", origin.encode()))
    return Request({"type": "http", "method": method, "path": path,
                    "headers": headers, "query_string": b"", "server": ("test", 80),
                    "client": ("127.0.0.1", 1), "scheme": "http"})


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
        "decision_write_available": False,
        "decision_actions": ["modify", "skip", "reprioritize"],
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
    with pytest.raises(HTTPException, match="decision routing is not configured") as caught:
        _endpoint(routes, "/api/daily-ops/decisions", "POST")(
            _request(), _owner_decision(),
        )
    assert caught.value.status_code == 503


def test_private_thread_cache_headers_preserve_existing_vary():
    response = JSONResponse({"rows": []})
    response.headers["Vary"] = "Accept-Encoding, origin"
    assert _private_cache_headers(response) is response
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Vary"] == "Accept-Encoding, origin, Authorization"


def test_private_path_middleware_marks_success_failure_and_summary(tmp_path):
    app = FastAPI()
    register(app, state_dir=tmp_path)
    dispatch = next(
        middleware.kwargs["dispatch"]
        for middleware in app.user_middleware
        if middleware.kwargs.get("dispatch", None)
        and middleware.kwargs["dispatch"].__name__ == "_daily_ops_private_response_headers"
    )

    async def exercise(path, status):
        async def call_next(_request):
            return JSONResponse({"detail": "test"}, status_code=status)
        return await dispatch(_get_request(path), call_next)

    success = asyncio.run(exercise("/api/daily-ops/messages", 200))
    failure = asyncio.run(exercise("/api/daily-ops/messages", 403))
    decision = asyncio.run(exercise("/api/daily-ops/decisions", 409))
    summary = asyncio.run(exercise("/api/daily-ops/summary", 200))
    for response in (success, failure, decision):
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["Vary"] == "Authorization, Origin"
    assert summary.status_code == 503
    assert summary.headers["Cache-Control"] == "no-store"
    assert summary.headers["Vary"] == "Authorization, Origin"


def test_summary_http_gate_denies_before_projection_and_preserves_owner_auth_contract(
    tmp_path,
):
    allowed_origin = "http://10.0.0.73:5173"

    def authorize(request):
        origin = request.headers.get("origin")
        return (
            request.headers.get("authorization") == "Bearer key"
            and (origin is None or origin == allowed_origin)
        )

    app = FastAPI()
    register(app, state_dir=tmp_path, owner_authorizer=authorize)
    dispatch = next(
        middleware.kwargs["dispatch"]
        for middleware in app.user_middleware
        if middleware.kwargs.get("dispatch", None)
        and middleware.kwargs["dispatch"].__name__
        == "_daily_ops_private_response_headers"
    )
    reached = []

    async def call_next(request):
        reached.append(request.method)
        return JSONResponse({"work_cards": [{"private": "projection"}]})

    denied = (
        _get_request("/api/daily-ops/summary"),
        _get_request("/api/daily-ops/summary", "wrong"),
        _get_request("/api/daily-ops/summary/", "key", origin="http://evil.invalid"),
        _get_request("/api/daily-ops/summary", method="HEAD"),
    )
    for request in denied:
        response = asyncio.run(dispatch(request, call_next))
        assert response.status_code == 403
        assert json.loads(response.body) == {"detail": "owner authentication required"}
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["Vary"] == "Authorization, Origin"
        assert b"work_cards" not in response.body
    assert reached == []

    for request in (
        _get_request("/api/daily-ops/summary", "key"),
        _get_request(
            "/api/daily-ops/summary", "key", method="HEAD", origin=allowed_origin,
        ),
    ):
        response = asyncio.run(dispatch(request, call_next))
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["Vary"] == "Authorization, Origin"
    assert reached == ["GET", "HEAD"]


def test_summary_http_gate_hides_authentication_failures(tmp_path):
    def unavailable(_request):
        raise HTTPException(status_code=401, detail="private credential detail")

    app = FastAPI()
    register(app, state_dir=tmp_path, owner_authorizer=unavailable)
    dispatch = next(
        middleware.kwargs["dispatch"]
        for middleware in app.user_middleware
        if middleware.kwargs.get("dispatch", None)
        and middleware.kwargs["dispatch"].__name__
        == "_daily_ops_private_response_headers"
    )
    reached = []

    async def call_next(_request):
        reached.append(True)
        return JSONResponse({"work_cards": [{"private": "projection"}]})

    for method in ("GET", "HEAD"):
        response = asyncio.run(dispatch(
            _get_request("/api/daily-ops/summary", "key", method=method), call_next,
        ))
        assert response.status_code == 503
        assert json.loads(response.body) == {"detail": "owner authentication unavailable"}
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["Vary"] == "Authorization, Origin"
        assert b"credential" not in response.body
        assert b"work_cards" not in response.body
    assert reached == []


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
    assert body["work_cards"][0]["conviction"]["score"] == 9
    assert body["agenda_decision"]["approve_enabled"] is False


def test_legacy_v1_summary_remains_readable_during_atomic_rollout(tmp_path):
    value = _summary()
    value["schema_version"] = LEGACY_SUMMARY_SCHEMA
    value.pop("work_cards")
    value.pop("agenda_decision")
    _write_summary(tmp_path, value)

    body = _endpoint(_endpoints(tmp_path), "/api/daily-ops/summary", "GET")()

    assert body["schema_version"] == LEGACY_SUMMARY_SCHEMA
    assert "work_cards" not in body
    assert "agenda_decision" not in body


@pytest.mark.parametrize("mutate", [
    lambda value: value.update({"surprise": "unbound"}),
    lambda value: value.update({"current_plan_revision": " bad "}),
    lambda value: value["agents"]["nara"].update(status="speaking_for_itself"),
    lambda value: value["research_focus"].update(source_receipt_sha256="not-a-hash"),
    lambda value: value["work_cards"][0]["conviction"].update(score=90),
    lambda value: value["agenda_decision"].update(revision="different-revision"),
    lambda value: value["agenda_decision"].update(approve_enabled=True),
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


def test_message_projection_preserves_bound_responder_identity(tmp_path):
    first = _message(responder_label="Oracle bounded UI responder")
    reply = _message(actor="oracle", intent="reply", status="acknowledged",
                     text="Summary-only response.", in_reply_to=first["request_id"],
                     responder_label="Oracle bounded UI responder")
    _write_messages(tmp_path, [first, reply])
    endpoint = _endpoint(_endpoints(
        tmp_path, authorizer=lambda _request: True, router=lambda _payload: {}
    ), "/api/daily-ops/messages", "GET")
    assert endpoint(_request(), after=None, limit=50)["rows"] == [first, reply]


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


@pytest.mark.parametrize("row", [
    _message(actor="oracle", intent="reply", status="acknowledged"),
    _message(actor="system", intent="receipt", status="queued"),
    _message(actor="owner", intent="reply", status="acknowledged"),
    _message(intent="change_request", plan_revision=None),
])
def test_message_actor_intent_lifecycle_combinations_are_not_invented(tmp_path, row):
    _write_messages(tmp_path, [row])
    endpoint = _endpoint(_endpoints(
        tmp_path, authorizer=lambda _request: True, router=lambda _payload: {}
    ), "/api/daily-ops/messages", "GET")
    with pytest.raises(HTTPException) as caught:
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


def _owner_decision(*, action="modify", target_kind="agenda", note="Draft the correction."):
    value = {
        "request_id": str(uuid.uuid4()),
        "target_kind": target_kind,
        "target_id": "agenda-20260920-r3" if target_kind == "agenda" else "runner",
        "action": action,
        "expected_plan_revision": REVISION,
    }
    if note is not None:
        value["note"] = note
    if action == "reprioritize":
        value["priority"] = "now"
    return value


def test_decision_request_is_authenticated_and_returns_queued_only_receipt(tmp_path):
    calls = []
    payload = _owner_decision()

    def route(value):
        calls.append(value)
        return {
            "request_id": value["request_id"], "status": "queued",
            "accepted_at": NOW, "duplicate": False,
            "target_kind": value["target_kind"], "target_id": value["target_id"],
            "action": value["action"],
            "expected_plan_revision": value["expected_plan_revision"],
            "execution_available": False,
        }

    routes = _endpoints(
        tmp_path, authorizer=lambda request: request.headers.get("authorization") == "Bearer key",
        router=lambda _value: {}, decision_router=route,
    )
    endpoint = _endpoint(routes, "/api/daily-ops/decisions", "POST")
    with pytest.raises(HTTPException) as caught:
        endpoint(_request(), payload)
    assert caught.value.status_code == 403 and calls == []

    receipt = endpoint(_request("key"), payload)
    assert receipt == {
        "request_id": payload["request_id"], "status": "queued",
        "accepted_at": NOW, "duplicate": False,
        "target_kind": "agenda", "target_id": "agenda-20260920-r3",
        "action": "modify", "expected_plan_revision": REVISION,
        "execution_available": False,
    }
    assert calls == [payload]


def test_message_and_decision_write_capabilities_are_independent(tmp_path):
    summary_only_message = _endpoint(_endpoints(
        tmp_path, authorizer=lambda _request: True, router=lambda _value: {},
    ), "/api/daily-ops/summary", "GET")()
    assert summary_only_message["capabilities"]["write_available"] is True
    assert summary_only_message["capabilities"]["decision_write_available"] is False

    decision_only = _endpoint(_endpoints(
        tmp_path, authorizer=lambda _request: True,
        decision_router=lambda _value: {},
    ), "/api/daily-ops/summary", "GET")()
    assert decision_only["capabilities"]["write_available"] is False
    assert decision_only["capabilities"]["decision_write_available"] is True


@pytest.mark.parametrize("mutation", [
    lambda value: value.update(action="approve"),
    lambda value: value.pop("expected_plan_revision"),
    lambda value: value.update(target_kind="nara"),
    lambda value: value.update(action="modify", note=None),
    lambda value: value.update(action="reprioritize", target_kind="agenda", priority="now"),
    lambda value: value.update(action="skip", priority="now"),
    lambda value: value.update(action="modify", note="x" * 3001),
    lambda value: value.update(action="modify", note="🧠" * 1000),
])
def test_invalid_or_authority_claiming_decisions_are_rejected_before_routing(
    tmp_path, mutation,
):
    routed = []
    payload = _owner_decision(target_kind="work_card")
    mutation(payload)
    endpoint = _endpoint(_endpoints(
        tmp_path, authorizer=lambda _request: True,
        decision_router=lambda value: routed.append(value),
    ), "/api/daily-ops/decisions", "POST")
    with pytest.raises(HTTPException) as caught:
        endpoint(_request(), payload)
    assert caught.value.status_code == 422
    assert routed == []


def test_decision_router_cannot_claim_execution_or_immediate_completion(tmp_path):
    payload = _owner_decision(action="skip", target_kind="work_card", note=None)
    endpoint = _endpoint(_endpoints(
        tmp_path, authorizer=lambda _request: True,
        decision_router=lambda value: {
            "request_id": value["request_id"], "status": "approved",
            "accepted_at": NOW, "duplicate": False,
            "target_kind": value["target_kind"], "target_id": value["target_id"],
            "action": value["action"],
            "expected_plan_revision": value["expected_plan_revision"],
            "execution_available": True,
        },
    ), "/api/daily-ops/decisions", "POST")
    with pytest.raises(HTTPException, match="invalid receipt") as caught:
        endpoint(_request(), payload)
    assert caught.value.status_code == 502
