"""Bounded read model and trusted-owner seam for the daily lab workspace.

The dashboard is a consumer of two small runtime projections:

``daily_ops_summary.json``
    The live v3 projection (``daily_ops_live``): today's plan of record, the
    research focus, per-item work status from the lab mailbox and git, owner
    requests, and observed agent activity.  Every section is re-derived from its
    producer on refresh; ``generated_at`` is that projection time and each
    section carries its own source time.  With no relay configured, the summary
    endpoint derives the same projection in memory instead of reading a file.

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

SUMMARY_SCHEMA = "daily-ops-summary/v3"
MESSAGES_SCHEMA = "daily-ops-messages/v1"
SUMMARY_NAME = "daily_ops_summary.json"
MESSAGES_NAME = "daily_ops_messages.jsonl"

MAX_SUMMARY_BYTES = 131_072
MAX_LOG_BYTES = 524_288
MAX_ROW_BYTES = 8_192
MAX_ROWS = 100
MAX_TEXT = 4_096
MAX_DECISION_NOTE = 3_000
MAX_SHORT_TEXT = 512
MAX_DEPTH = 12

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_AGENT_STATUSES = {
    "online", "active", "working", "idle", "waiting", "degraded", "stale", "failed", "offline", "unknown",
}
_ACTORS = {"owner", "oracle", "system"}
_INTENTS = {"question", "change_request", "reply", "receipt"}
_REQUEST_INTENTS = {"question", "change_request"}
_MESSAGE_STATUSES = {"queued", "delivered", "acknowledged", "failed"}
_PRIVATE_PATHS = {"/api/daily-ops/messages", "/api/daily-ops/decisions"}
_DECISION_ACTIONS = {"modify", "skip", "reprioritize", "approve", "decline", "defer", "reply"}
_DECISION_TARGETS = {"agenda", "work_card", "question"}
_QUESTION_ACTIONS = {"approve", "decline", "defer", "reply"}
_PLAN_ACTIONS = {"modify", "skip", "reprioritize", "approve", "decline", "defer"}


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


def _agents(value: object) -> bool:
    """Slim live agent cards: status, one "Now" line, since/observed times, relay."""
    if not isinstance(value, dict) or not {"oracle", "pi_client", "nara"} <= set(value) <= {
        "oracle", "pi_client", "nara", "meta_oracle",
    }:
        return False
    for key, row in value.items():
        if not isinstance(row, dict) or not (
            {"label", "status", "detail", "observed_at", "source"} <= set(row)
            <= {"label", "status", "detail", "observed_at", "source",
                "role", "activity", "activity_at", "since", "relay"}
        ):
            return False
        relay = row.get("relay")
        if not (
            _text(row.get("label"), MAX_SHORT_TEXT)
            and row.get("status") in _AGENT_STATUSES
            and _text(row.get("detail"))
            and _timestamp(row.get("observed_at"))
            and _text(row.get("source"), MAX_SHORT_TEXT)
            and ("role" not in row or _text(row["role"], MAX_SHORT_TEXT))
            and (row.get("activity") is None or _text(row["activity"], MAX_SHORT_TEXT))
            and all(row.get(k) is None or _timestamp(row[k]) for k in ("activity_at", "since"))
            and (relay is None or (
                isinstance(relay, dict) and set(relay) == {"status", "detail", "observed_at", "source"}
                and relay.get("status") in _AGENT_STATUSES and _text(relay.get("detail"))
                and _timestamp(relay.get("observed_at")) and _text(relay.get("source"), MAX_SHORT_TEXT)
            ))
        ):
            return False
        if key == "pi_client" and "client" not in row["label"].lower():
            return False
    return True


def _validate_summary(value: object) -> dict:
    """Accept only the live v3 projection; retired v1/v2 briefs are refused."""
    if not isinstance(value, dict) or value.get("schema_version") != SUMMARY_SCHEMA:
        raise ValueError("summary fields do not match a supported contract")
    from .daily_ops_live import validate_live  # lazy: daily_ops_live imports this module
    validate_live(value, _agents)
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
    if target == "question" and action not in _QUESTION_ACTIONS:
        raise HTTPException(status_code=422, detail="a question accepts only approve, decline, defer or reply")
    if target != "question" and action not in _PLAN_ACTIONS:
        raise HTTPException(status_code=422, detail="a plan target does not accept reply")
    if action in ("modify", "reply") and note is None:
        raise HTTPException(status_code=422, detail=f"{action} requires a note")
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
    live_summary: Callable[[], dict] | None = None,
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
        if projection_refresher is None and live_summary is not None:
            # No relay writes the projection: derive it now instead of serving
            # whatever file an earlier producer left behind.
            try:
                value = _validate_summary(live_summary())
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise HTTPException(
                    status_code=503,
                    detail="daily operations live projection is unavailable or invalid",
                ) from exc
            return {**value, "available": True, "source_sha256": None,
                    "capabilities": capabilities}
        if not summary_path.exists():
            return {
                "schema_version": SUMMARY_SCHEMA,
                "available": False,
                "generated_at": None,
                "source_sha256": None,
                "current_plan_revision": None,
                "daily_plan": None,
                "research_focus": None,
                "work_items": [],
                "waiting_on_you": [],
                "accomplishments": [],
                "improvements": [],
                "agents": {},
                "warnings": ["daily operations snapshot is not available"],
                "sources": {"plan": None, "mailbox": None, "focus": None, "git": None},
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
