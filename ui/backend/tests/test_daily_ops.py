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
    MESSAGES_SCHEMA,
    SUMMARY_SCHEMA,
    _private_cache_headers,
    register,
)

NOW = "2026-09-20T08:30:00Z"
REVISION = "2026-09-20-r3"


def _summary():
    agent = {"source": "live observation", "observed_at": NOW, "detail": "No live run."}
    return {
        "schema_version": SUMMARY_SCHEMA,
        "generated_at": NOW,
        "current_plan_revision": REVISION,
        "daily_plan": {
            "id": REVISION, "date": "2026-09-20", "revision": "r3",
            "path": "run_state/daily_plans/2026-09-20-r3.json", "sha256": "a" * 64,
            "written_at": NOW, "is_current": True,
            "week_alignment": "Moves G0 first.",
            "bottlenecks": ["Nothing can select the next focus."],
            "review": {"note_msg_id": "oracle-0000000000000001", "sha_matches": True,
                       "verdict": "amend", "review_msg_id": "claude-0000000000000002",
                       "reviewed_at": NOW, "summary": "Accept d2.", "accepted_items": ["d2"]},
        },
        "research_focus": {"status": "none", "observed_at": NOW, "last_closure": {
            "focus_id": "payoff-assistance", "title": "Payoff assistance", "disposition": "killed",
            "closed_at": NOW, "reason": "Closed for opportunity cost.", "closure_sha256": "b" * 64}},
        "work_items": [{
            "id": "d1", "goal": "G7.1", "owner": "oracle", "lane": "oracle_dev", "repo": "a_bgt_rsi",
            "title": "Lane precheck", "why_today": "Retro finding.", "acceptance": "Tests pass.",
            "depends_on": [], "status": "merged", "detail": "Merge oracle/2026-09-20-d1",
            "evidence_msg_id": None, "evidence_sha": "2cbe6dbe8a39", "evidence_at": NOW,
        }],
        "waiting_on_you": [{
            "kind": "question", "id": "claude-0000000000000003", "title": "Two rulings",
            "asked_by": "claude", "asked_at": NOW, "msg_id": "claude-0000000000000003",
            "cli": "python -m orchestrator.oracle_mailbox post --kind answer",
        }],
        "accomplishments": [{"id": "2026-09-20:d1", "kind": "merged", "title": "d1 merged",
                             "at": NOW, "evidence": "2cbe6dbe8a39"}],
        "improvements": [{"sha": "2cbe6dbe8a39", "at": NOW, "subject": "Merge d1 (G7.1)",
                          "goals": ["G7.1"]}],
        "agents": {
            "oracle": {"label": "Oracle steward", "status": "working", **agent,
                       "activity": "daily-loop phase plan for 2026-09-20", "since": NOW},
            "pi_client": {"label": "Pi client for Oracle", "status": "idle", **agent},
            "nara": {"label": "Nara runner", "status": "idle", **agent},
        },
        "warnings": [],
        "sources": {"plan": NOW, "mailbox": NOW, "focus": NOW, "git": None},
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


def _get_request(path):
    return Request({"type": "http", "method": "GET", "path": path,
                    "headers": [], "query_string": b"", "server": ("test", 80),
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


def test_private_path_middleware_marks_success_and_failure_but_not_summary(tmp_path):
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
    assert "Cache-Control" not in summary.headers
    assert "Vary" not in summary.headers


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
    assert body["work_items"][0]["status"] == "merged"
    assert body["daily_plan"]["review"]["verdict"] == "amend"


@pytest.mark.parametrize("schema", ["daily-ops-summary/v1", "daily-ops-summary/v2"])
def test_retired_hand_curated_summaries_are_refused_not_shown(tmp_path, schema):
    value = _summary()
    value["schema_version"] = schema
    _write_summary(tmp_path, value)
    with pytest.raises(HTTPException) as caught:
        _endpoint(_endpoints(tmp_path), "/api/daily-ops/summary", "GET")()
    assert caught.value.status_code == 503


def test_without_a_relay_the_summary_is_derived_live_not_read_from_disk(tmp_path):
    stale = _summary()
    stale["generated_at"] = "2026-09-01T00:00:00Z"
    _write_summary(tmp_path, stale)
    live = _summary()
    app = FastAPI()
    register(app, state_dir=tmp_path, live_summary=lambda: live)
    endpoint = next(route.endpoint for route in app.routes
                    if getattr(route, "path", "") == "/api/daily-ops/summary")
    body = endpoint()
    assert body["generated_at"] == NOW and body["source_sha256"] is None
    live["agents"]["nara"]["status"] = "speaking_for_itself"
    with pytest.raises(HTTPException) as caught:
        endpoint()
    assert caught.value.status_code == 503


@pytest.mark.parametrize("mutate", [
    lambda value: value.update({"surprise": "unbound"}),
    lambda value: value.update({"current_plan_revision": "other-plan"}),
    lambda value: value["agents"]["nara"].update(status="speaking_for_itself"),
    lambda value: value["agents"]["oracle"].update(items=[]),
    lambda value: value["research_focus"].update(status="blocked"),
    lambda value: value["work_items"][0].update(status="done"),
    lambda value: value["work_items"][0].update(extra="x"),
    lambda value: value["daily_plan"]["review"].update(verdict="approve"),
    lambda value: value["waiting_on_you"][0].update(kind="decision"),
    lambda value: value["improvements"][0].update(goals=["not a goal"]),
    lambda value: value["sources"].update(plan="yesterday"),
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
