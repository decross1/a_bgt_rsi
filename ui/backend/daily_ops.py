"""Bounded read model and trusted-owner seam for the daily lab workspace.

The dashboard is a consumer of two small runtime projections:

``daily_ops_summary.json``
    Human-readable goals, recent outcomes, the selected research focus and
    observed agent health.  A separate producer owns the projection; this
    module never infers completion from prose or mutates scientific state.
    Its ``generated_at`` value is the curated daily-notes update time, not the
    time a live health projection happened to be read.

``daily_ops_messages.jsonl``
    An append-only projection of owner requests and *observed* delivery/reply
    receipts.  Actor labels are recorded metadata, not authentication.

The POST endpoint is deliberately inert unless both an owner authorizer and a
message router are injected by the process that starts the backend.  Saving a
message locally is not represented as delivery.  The router must durably and
idempotently enqueue the request to the real Oracle mailbox; its narrow receipt
is returned verbatim after validation.  Plan-change requests remain advisory
and cannot express agenda approval or execution authority.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import subprocess
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException, Query, Request
from starlette.responses import Response

LEGACY_SUMMARY_SCHEMA = "daily-ops-summary/v1"
SUMMARY_SCHEMA = "daily-ops-summary/v2"
MESSAGES_SCHEMA = "daily-ops-messages/v1"
SUMMARY_NAME = "daily_ops_summary.json"
MESSAGES_NAME = "daily_ops_messages.jsonl"

MAX_SUMMARY_BYTES = 65_536
MAX_LOG_BYTES = 524_288
MAX_ROW_BYTES = 8_192
MAX_ROWS = 100
MAX_TEXT = 4_096
MAX_DECISION_NOTE = 3_000
MAX_SHORT_TEXT = 512
MAX_ITEMS = 16
MAX_DEPTH = 12

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SUMMARY_FIELDS_V1 = {
    "schema_version", "generated_at", "goals", "accomplishments",
    "improvements", "research_focus", "agents", "warnings",
    "current_plan_revision",
}
_SUMMARY_FIELDS_V2 = _SUMMARY_FIELDS_V1 | {"work_cards", "agenda_decision"}
_GOAL_STATUSES = {"planned", "in_progress", "blocked", "done", "awaiting_owner"}
_GOAL_OWNERS = {"codex", "oracle", "nara", "owner", "lab"}
_IMPROVEMENT_STATUSES = {"proposed", "implemented", "verified", "blocked"}
_AGENT_STATUSES = {"online", "working", "idle", "waiting", "degraded", "offline", "unknown"}
_FOCUS_STATUSES = {"selected", "blocked", "complete", "unavailable"}
_GATE_STATUSES = {"pending", "blocked", "complete"}
_ACTORS = {"owner", "oracle", "system"}
_INTENTS = {"question", "change_request", "reply", "receipt"}
_REQUEST_INTENTS = {"question", "change_request"}
_MESSAGE_STATUSES = {"queued", "delivered", "acknowledged", "failed"}
_PRIVATE_PATHS = {"/api/daily-ops/messages", "/api/daily-ops/decisions"}
_WORK_CARD_STATUSES = {"authorized", "in_progress", "blocked", "done", "draft"}
_EVIDENCE_KINDS = {"estimate", "measured", "unrated"}
_WORTH_TIME = {"do_now", "after_dependency", "hold", "unrated"}
_AGENDA_DISPOSITIONS = {"amend_required", "review_required"}
_DECISION_ACTIONS = {"modify", "skip", "reprioritize"}
_DECISION_TARGETS = {"agenda", "work_card"}


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _timestamp(value: object) -> bool:
    if not isinstance(value, str) or not value.endswith("Z") or len(value) > 40:
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == timezone.utc.utcoffset(parsed)


def _text(value: object, maximum: int = MAX_TEXT) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= maximum
        and value == value.strip()
        and all(ord(char) >= 32 or char in "\t\n\r" for char in value)
    )


def _identifier(value: object) -> bool:
    return isinstance(value, str) and _SAFE_ID.fullmatch(value) is not None


def _json_safe(value: object) -> bool:
    stack = [(value, 0)]
    while stack:
        node, depth = stack.pop()
        if depth > MAX_DEPTH:
            return False
        if isinstance(node, float) and not math.isfinite(node):
            return False
        if isinstance(node, str):
            try:
                node.encode("utf-8")
            except UnicodeEncodeError:
                return False
        if isinstance(node, dict):
            stack.extend((key, depth) for key in node)
            stack.extend((item, depth + 1) for item in node.values())
        elif isinstance(node, list):
            stack.extend((item, depth + 1) for item in node)
    return True


def _private_cache_headers(response: Response) -> Response:
    """Keep the authenticated owner thread and queue receipts out of caches."""
    response.headers["Cache-Control"] = "no-store"
    vary = [item.strip() for item in response.headers.get("Vary", "").split(",")
            if item.strip()]
    existing = {item.lower() for item in vary}
    for item in ("Authorization", "Origin"):
        if item.lower() not in existing:
            vary.append(item)
            existing.add(item.lower())
    response.headers["Vary"] = ", ".join(vary)
    return response


def _read_regular(path: Path, maximum: int) -> bytes:
    """Read one stable, bounded regular file without following a symlink."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as handle:
        before = os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > maximum:
            raise ValueError("source is not a bounded regular file")
        raw = handle.read(maximum + 1)
        after = os.fstat(handle.fileno())
    if (
        len(raw) != before.st_size
        or len(raw) > maximum
        or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    ):
        raise ValueError("source changed while being read or exceeded its bound")
    return raw


def _summary_item(value: object, *, kind: str) -> bool:
    if not isinstance(value, dict):
        return False
    common = {"id", "title", "detail", "source", "observed_at"}
    expected = common | ({"status", "owner"} if kind == "goal" else {"status"})
    if set(value) != expected:
        return False
    if not (
        _identifier(value.get("id"))
        and _text(value.get("title"), MAX_SHORT_TEXT)
        and _text(value.get("detail"))
        and _text(value.get("source"), MAX_SHORT_TEXT)
        and _timestamp(value.get("observed_at"))
    ):
        return False
    if kind == "goal":
        return value.get("status") in _GOAL_STATUSES and value.get("owner") in _GOAL_OWNERS
    if kind == "improvement":
        return value.get("status") in _IMPROVEMENT_STATUSES
    return value.get("status") == "complete"


def _focus(value: object) -> bool:
    if value is None:
        return True
    if not isinstance(value, dict) or set(value) != {
        "focus_id", "title", "status", "stage", "next_action", "next_gate",
        "blockers", "source_receipt_sha256", "observed_at",
    }:
        return False
    gate = value.get("next_gate")
    return (
        _identifier(value.get("focus_id"))
        and _text(value.get("title"), MAX_SHORT_TEXT)
        and value.get("status") in _FOCUS_STATUSES
        and _text(value.get("stage"), MAX_SHORT_TEXT)
        and _text(value.get("next_action"))
        and isinstance(gate, dict)
        and set(gate) == {"from", "to", "artifact", "status", "owner"}
        and all(_text(gate.get(field), MAX_SHORT_TEXT) for field in ("from", "to", "artifact", "owner"))
        and gate.get("status") in _GATE_STATUSES
        and isinstance(value.get("blockers"), list)
        and len(value["blockers"]) <= MAX_ITEMS
        and all(_text(item, MAX_SHORT_TEXT) for item in value["blockers"])
        and isinstance(value.get("source_receipt_sha256"), str)
        and _SHA256.fullmatch(value["source_receipt_sha256"]) is not None
        and _timestamp(value.get("observed_at"))
    )


def _agents(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != {"oracle", "pi_client", "nara"}:
        return False
    for key, row in value.items():
        if not isinstance(row, dict) or set(row) != {"label", "status", "detail", "observed_at", "source"}:
            return False
        if not (
            _text(row.get("label"), MAX_SHORT_TEXT)
            and row.get("status") in _AGENT_STATUSES
            and _text(row.get("detail"))
            and _timestamp(row.get("observed_at"))
            and _text(row.get("source"), MAX_SHORT_TEXT)
        ):
            return False
        if key == "pi_client" and "client" not in row["label"].lower():
            return False
    return True


def _evidence(value: object) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {"summary", "kind", "basis"}
        and _text(value.get("summary"), MAX_SHORT_TEXT)
        and value.get("kind") in _EVIDENCE_KINDS
        and _text(value.get("basis"), MAX_SHORT_TEXT)
    )


def _conviction(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != {"score", "kind", "basis"}:
        return False
    score = value.get("score")
    kind = value.get("kind")
    return (
        kind in _EVIDENCE_KINDS
        and _text(value.get("basis"), MAX_SHORT_TEXT)
        and (
            (kind == "unrated" and score is None)
            or (kind != "unrated" and type(score) is int and 0 <= score <= 10)
        )
    )


def _work_cards(value: object) -> bool:
    if not isinstance(value, list) or len(value) > 3:
        return False
    prior: set[str] = set()
    for card in value:
        expected = {
            "id", "title", "what", "benefit", "cost", "conviction",
            "worth_time", "status", "owner", "depends_on", "source",
            "observed_at", "approval_required", "actions",
        }
        if not isinstance(card, dict) or set(card) != expected:
            return False
        ident = card.get("id")
        dependencies = card.get("depends_on")
        actions = card.get("actions")
        worth = card.get("worth_time")
        if not (
            _identifier(ident)
            and ident not in prior
            and _text(card.get("title"), MAX_SHORT_TEXT)
            and _text(card.get("what"))
            and _text(card.get("benefit"))
            and _evidence(card.get("cost"))
            and _conviction(card.get("conviction"))
            and isinstance(worth, dict)
            and set(worth) == {"recommendation", "basis"}
            and worth.get("recommendation") in _WORTH_TIME
            and _text(worth.get("basis"), MAX_SHORT_TEXT)
            and card.get("status") in _WORK_CARD_STATUSES
            and card.get("owner") in _GOAL_OWNERS - {"owner"}
            and isinstance(dependencies, list)
            and len(dependencies) <= 3
            and len(set(dependencies)) == len(dependencies)
            and all(_identifier(item) and item in prior for item in dependencies)
            and _text(card.get("source"), MAX_SHORT_TEXT)
            and _timestamp(card.get("observed_at"))
            and card.get("approval_required") is False
            and isinstance(actions, list)
            and 1 <= len(actions) <= 3
            and len(set(actions)) == len(actions)
            and set(actions).issubset(_DECISION_ACTIONS)
            and "reprioritize" in actions
        ):
            return False
        prior.add(ident)
    return True


def _agenda_decision(value: object, current_revision: object) -> bool:
    if value is None:
        return current_revision is None
    expected = {
        "id", "agenda_id", "revision", "title", "what", "reason",
        "disposition", "approval_required", "approve_enabled",
        "execution_available", "actions", "task_titles", "source",
        "observed_at",
    }
    if not isinstance(value, dict) or set(value) != expected:
        return False
    actions = value.get("actions")
    titles = value.get("task_titles")
    return (
        _identifier(value.get("id"))
        and _identifier(value.get("agenda_id"))
        and _identifier(value.get("revision"))
        and value.get("revision") == current_revision
        and _text(value.get("title"), MAX_SHORT_TEXT)
        and _text(value.get("what"))
        and _text(value.get("reason"))
        and value.get("disposition") in _AGENDA_DISPOSITIONS
        and value.get("approval_required") is False
        and value.get("approve_enabled") is False
        and value.get("execution_available") is False
        and isinstance(actions, list)
        and 1 <= len(actions) <= 2
        and len(set(actions)) == len(actions)
        and set(actions).issubset({"modify", "skip"})
        and isinstance(titles, list)
        and len(titles) <= 3
        and all(_text(title, MAX_SHORT_TEXT) for title in titles)
        and _text(value.get("source"), MAX_SHORT_TEXT)
        and _timestamp(value.get("observed_at"))
    )


def _validate_summary(value: object) -> dict:
    if not isinstance(value, dict):
        raise ValueError("summary is not an object")
    schema = value.get("schema_version")
    expected = _SUMMARY_FIELDS_V2 if schema == SUMMARY_SCHEMA else _SUMMARY_FIELDS_V1
    if schema not in {SUMMARY_SCHEMA, LEGACY_SUMMARY_SCHEMA} or set(value) != expected:
        raise ValueError("summary fields do not match a supported contract")
    if not _timestamp(value.get("generated_at")):
        raise ValueError("summary schema or timestamp is invalid")
    revision = value.get("current_plan_revision")
    if revision is not None and not _identifier(revision):
        raise ValueError("summary current plan revision is invalid")
    for field, kind in (
        ("goals", "goal"), ("accomplishments", "accomplishment"),
        ("improvements", "improvement"),
    ):
        rows = value.get(field)
        if not isinstance(rows, list) or len(rows) > MAX_ITEMS or not all(
            _summary_item(row, kind=kind) for row in rows
        ):
            raise ValueError(f"summary {field} is invalid")
    warnings = value.get("warnings")
    if not isinstance(warnings, list) or len(warnings) > MAX_ITEMS or not all(
        _text(item, MAX_SHORT_TEXT) for item in warnings
    ):
        raise ValueError("summary warnings are invalid")
    if not _focus(value.get("research_focus")) or not _agents(value.get("agents")):
        raise ValueError("summary focus or agent observations are invalid")
    if schema == SUMMARY_SCHEMA and (
        not _work_cards(value.get("work_cards"))
        or not _agenda_decision(value.get("agenda_decision"), revision)
    ):
        raise ValueError("summary work cards or agenda decision are invalid")
    if not _json_safe(value):
        raise ValueError("summary is not safely JSON encodable")
    return value


def _message_row(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    required = {
        "request_id", "created_at", "actor", "intent", "status", "text",
        "target", "plan_revision",
    }
    optional = {"in_reply_to", "responder_label"}
    if not required.issubset(value) or not set(value).issubset(required | optional):
        return False
    try:
        parsed_id = uuid.UUID(str(value.get("request_id")))
    except (ValueError, TypeError, AttributeError):
        return False
    reply_to = value.get("in_reply_to")
    if reply_to is not None:
        try:
            uuid.UUID(str(reply_to))
        except (ValueError, TypeError, AttributeError):
            return False
    structural = (
        str(parsed_id) == value.get("request_id")
        and _timestamp(value.get("created_at"))
        and value.get("actor") in _ACTORS
        and value.get("intent") in _INTENTS
        and value.get("status") in _MESSAGE_STATUSES
        and _text(value.get("text"))
        and value.get("target") == "oracle"
        and (
            value.get("plan_revision") is None
            or _identifier(value.get("plan_revision"))
        )
        and (
            value.get("responder_label") is None
            or _text(value.get("responder_label"), MAX_SHORT_TEXT)
        )
        and _json_safe(value)
    )
    if not structural:
        return False
    actor = value["actor"]
    intent = value["intent"]
    status = value["status"]
    has_parent = reply_to is not None
    if actor == "owner":
        return (
            intent in _REQUEST_INTENTS
            and status == "queued"
            and not has_parent
            and (
                intent != "change_request"
                or value["plan_revision"] is not None
            )
        )
    if actor == "system":
        return intent == "receipt" and status in {"delivered", "failed"} and has_parent
    return actor == "oracle" and intent == "reply" and status == "acknowledged" and has_parent


def _load_summary(path: Path) -> dict:
    raw = _read_regular(path, MAX_SUMMARY_BYTES)
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"summary JSON is invalid: {exc}") from exc
    result = _validate_summary(value)
    return {
        **result,
        "available": True,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
    }


def _load_messages(path: Path) -> list[dict]:
    raw = _read_regular(path, MAX_LOG_BYTES)
    rows = []
    for index, line in enumerate(raw.splitlines(), start=1):
        if not line:
            continue
        if len(line) > MAX_ROW_BYTES:
            raise ValueError(f"message row {index} exceeds its byte bound")
        try:
            row = json.loads(line, object_pairs_hook=_unique_object)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            raise ValueError(f"message row {index} is invalid JSON: {exc}") from exc
        if not _message_row(row):
            raise ValueError(f"message row {index} violates the v1 contract")
        rows.append(row)
    return rows


def _request_payload(payload: object) -> dict:
    required = {"request_id", "target", "intent", "text"}
    optional = {"expected_plan_revision"}
    if not isinstance(payload, dict) or not required.issubset(payload) or not set(payload).issubset(required | optional):
        raise HTTPException(status_code=422, detail="owner message fields do not match the v1 contract")
    try:
        parsed = uuid.UUID(str(payload.get("request_id")))
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(status_code=422, detail="request_id must be a canonical UUID") from exc
    if str(parsed) != payload.get("request_id"):
        raise HTTPException(status_code=422, detail="request_id must be a canonical UUID")
    if payload.get("target") != "oracle":
        raise HTTPException(status_code=422, detail="target must be oracle; Pi is its client and Nara is observed state")
    if payload.get("intent") not in _REQUEST_INTENTS:
        raise HTTPException(status_code=422, detail="intent must be question or change_request")
    if not _text(payload.get("text")):
        raise HTTPException(status_code=422, detail=f"text must be non-empty and at most {MAX_TEXT} characters")
    revision = payload.get("expected_plan_revision")
    if revision is not None and not _identifier(revision):
        raise HTTPException(status_code=422, detail="expected_plan_revision is invalid")
    if payload.get("intent") == "change_request" and revision is None:
        raise HTTPException(
            status_code=422,
            detail="change_request requires expected_plan_revision",
        )
    return dict(payload)


def _decision_payload(payload: object) -> dict:
    required = {
        "request_id", "target_kind", "target_id", "action",
        "expected_plan_revision",
    }
    optional = {"note", "priority"}
    if (not isinstance(payload, dict) or not required.issubset(payload)
            or not set(payload).issubset(required | optional)):
        raise HTTPException(
            status_code=422,
            detail="owner decision fields do not match the v1 contract",
        )
    try:
        parsed = uuid.UUID(str(payload.get("request_id")))
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(status_code=422, detail="request_id must be a canonical UUID") from exc
    if str(parsed) != payload.get("request_id"):
        raise HTTPException(status_code=422, detail="request_id must be a canonical UUID")
    target = payload.get("target_kind")
    action = payload.get("action")
    note = payload.get("note")
    priority = payload.get("priority")
    if (
        target not in _DECISION_TARGETS
        or not _identifier(payload.get("target_id"))
        or action not in _DECISION_ACTIONS
        or not _identifier(payload.get("expected_plan_revision"))
        or (
            note is not None
            and (
                not _text(note, MAX_DECISION_NOTE)
                or not _json_safe(note)
                or len(note.encode("utf-8")) > MAX_DECISION_NOTE
            )
        )
        or (priority is not None and priority not in {"now", "next", "later"})
    ):
        raise HTTPException(status_code=422, detail="owner decision is invalid")
    if action == "modify" and note is None:
        raise HTTPException(status_code=422, detail="modify requires a note")
    if action == "reprioritize":
        if target != "work_card" or priority is None:
            raise HTTPException(
                status_code=422,
                detail="reprioritize requires a work card and priority",
            )
    elif priority is not None:
        raise HTTPException(status_code=422, detail="priority is only valid for reprioritize")
    return dict(payload)


def _router_receipt(
    value: object,
    request_id: str,
    expected_plan_revision: str | None,
) -> dict:
    if not isinstance(value, dict) or set(value) != {
        "request_id", "status", "accepted_at", "duplicate",
        "expected_plan_revision",
    }:
        raise ValueError("router receipt fields do not match the v1 contract")
    if (
        value.get("request_id") != request_id
        or value.get("status") != "queued"
        or not _timestamp(value.get("accepted_at"))
        or not isinstance(value.get("duplicate"), bool)
        or value.get("expected_plan_revision")
        != expected_plan_revision
    ):
        raise ValueError("router receipt is invalid")
    return value


def _decision_router_receipt(value: object, payload: dict) -> dict:
    expected = {
        "request_id", "status", "accepted_at", "duplicate", "target_kind",
        "target_id", "action", "expected_plan_revision", "execution_available",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("decision router receipt fields do not match the v1 contract")
    if (
        value.get("request_id") != payload["request_id"]
        or value.get("status") != "queued"
        or not _timestamp(value.get("accepted_at"))
        or not isinstance(value.get("duplicate"), bool)
        or value.get("target_kind") != payload["target_kind"]
        or value.get("target_id") != payload["target_id"]
        or value.get("action") != payload["action"]
        or value.get("expected_plan_revision") != payload["expected_plan_revision"]
        or value.get("execution_available") is not False
    ):
        raise ValueError("decision router receipt is invalid")
    return value


def register(
    app,
    *,
    state_dir: Path,
    owner_authorizer: Callable[[Request], bool] | None = None,
    message_router: Callable[[dict], dict] | None = None,
    decision_router: Callable[[dict], dict] | None = None,
    projection_refresher: Callable[[], None] | None = None,
) -> APIRouter:
    """Attach the daily-ops routes.

    ``owner_authorizer`` and ``message_router`` are a pair: omitting either
    makes the write path unavailable.  This prevents a local JSON append from
    masquerading as delivery to the live Oracle session.
    """
    root = Path(state_dir)
    summary_path = root / SUMMARY_NAME
    messages_path = root / MESSAGES_NAME
    writable = owner_authorizer is not None and message_router is not None
    decisions_writable = owner_authorizer is not None and decision_router is not None
    capabilities = {
        "auth_required": True,
        "write_available": writable,
        "targets": ["oracle"],
        "intents": ["question", "change_request"],
        "nara_interaction": "ask_oracle_about_nara",
        "decision_write_available": decisions_writable,
        "decision_actions": ["modify", "skip", "reprioritize"],
    }
    router = APIRouter(prefix="/api/daily-ops", tags=["daily-ops"])

    @app.middleware("http")
    async def _daily_ops_private_response_headers(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.rstrip("/") in _PRIVATE_PATHS:
            _private_cache_headers(response)
        return response

    def _refresh_projection() -> None:
        if projection_refresher is None:
            return
        try:
            projection_refresher()
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="daily operations projection refresh is unavailable",
            ) from exc

    def _require_owner(request: Request) -> None:
        if owner_authorizer is None:
            raise HTTPException(status_code=503, detail="owner authentication is unavailable")
        try:
            authorized = owner_authorizer(request)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=503, detail="owner authentication is unavailable") from exc
        if authorized is not True:
            raise HTTPException(status_code=403, detail="owner authentication required")

    @router.get("/summary")
    def summary():
        _refresh_projection()
        if not summary_path.exists():
            return {
                "schema_version": SUMMARY_SCHEMA,
                "available": False,
                "generated_at": None,
                "source_sha256": None,
                "current_plan_revision": None,
                "goals": [],
                "accomplishments": [],
                "improvements": [],
                "research_focus": None,
                "agents": {},
                "warnings": ["daily operations snapshot is not available"],
                "work_cards": [],
                "agenda_decision": None,
                "capabilities": capabilities,
            }
        try:
            return {**_load_summary(summary_path), "capabilities": capabilities}
        except (OSError, ValueError) as exc:
            raise HTTPException(
                status_code=503,
                detail="daily operations snapshot is unavailable or invalid",
            ) from exc

    @router.get("/messages")
    def messages(
        request: Request,
        after: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=MAX_ROWS),
    ):
        if not writable:
            return {
                "schema_version": MESSAGES_SCHEMA,
                "available": False,
                "writable": False,
                "rows": [],
            }
        _require_owner(request)
        _refresh_projection()
        if not messages_path.exists():
            return {
                "schema_version": MESSAGES_SCHEMA,
                "available": False,
                "writable": True,
                "rows": [],
            }
        try:
            rows = _load_messages(messages_path)
        except (OSError, ValueError) as exc:
            raise HTTPException(
                status_code=503,
                detail="daily operations messages are unavailable or invalid",
            ) from exc
        if after is not None:
            try:
                parsed = uuid.UUID(after)
            except (ValueError, TypeError, AttributeError) as exc:
                raise HTTPException(status_code=422, detail="after must be a canonical UUID") from exc
            if str(parsed) != after:
                raise HTTPException(status_code=422, detail="after must be a canonical UUID")
            indexes = [index for index, row in enumerate(rows) if row["request_id"] == after]
            if not indexes:
                raise HTTPException(status_code=409, detail="after cursor is not present in the bounded message log")
            rows = rows[indexes[-1] + 1:]
        return {
            "schema_version": MESSAGES_SCHEMA,
            "available": True,
            "writable": writable,
            "rows": rows[-limit:],
        }

    @router.post("/messages")
    def post_message(request: Request, payload: dict = Body(...)):
        value = _request_payload(payload)
        if owner_authorizer is None or message_router is None:
            raise HTTPException(status_code=503, detail="trusted owner message routing is not configured")
        _require_owner(request)
        _refresh_projection()
        try:
            receipt = message_router(value)
            return _router_receipt(
                receipt,
                value["request_id"],
                value.get("expected_plan_revision"),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise HTTPException(status_code=502, detail="Oracle message routing failed") from exc
        except ValueError as exc:
            raise HTTPException(status_code=502, detail="Oracle router returned an invalid receipt") from exc

    @router.post("/decisions")
    def post_decision(request: Request, payload: dict = Body(...)):
        value = _decision_payload(payload)
        if owner_authorizer is None or decision_router is None:
            raise HTTPException(status_code=503, detail="trusted owner decision routing is not configured")
        _require_owner(request)
        _refresh_projection()
        try:
            return _decision_router_receipt(decision_router(value), value)
        except HTTPException:
            raise
        except (OSError, subprocess.SubprocessError) as exc:
            raise HTTPException(status_code=502, detail="Oracle decision routing failed") from exc
        except ValueError as exc:
            raise HTTPException(status_code=502, detail="Oracle decision router returned an invalid receipt") from exc

    app.include_router(router)
    return router
