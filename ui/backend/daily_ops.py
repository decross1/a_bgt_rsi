"""Bounded read model and trusted-owner seam for the daily lab workspace.

The dashboard is a consumer of two small runtime projections:

``daily_ops_summary.json``
    Human-readable goals, recent outcomes, the selected research focus and
    observed agent health.  A separate producer owns the projection; this
    module never infers completion from prose or mutates scientific state.

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
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from fastapi import APIRouter, Body, HTTPException, Query, Request


SUMMARY_SCHEMA = "daily-ops-summary/v1"
MESSAGES_SCHEMA = "daily-ops-messages/v1"
SUMMARY_NAME = "daily_ops_summary.json"
MESSAGES_NAME = "daily_ops_messages.jsonl"

MAX_SUMMARY_BYTES = 65_536
MAX_LOG_BYTES = 524_288
MAX_ROW_BYTES = 8_192
MAX_ROWS = 100
MAX_TEXT = 4_096
MAX_SHORT_TEXT = 512
MAX_ITEMS = 16
MAX_DEPTH = 12

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SUMMARY_FIELDS = {
    "schema_version", "generated_at", "goals", "accomplishments",
    "improvements", "research_focus", "agents", "warnings",
    "current_plan_revision",
}
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


def _validate_summary(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != _SUMMARY_FIELDS:
        raise ValueError("summary fields do not match the v1 contract")
    if value.get("schema_version") != SUMMARY_SCHEMA or not _timestamp(value.get("generated_at")):
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
    optional = {"in_reply_to"}
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


def register(
    app,
    *,
    state_dir: Path,
    owner_authorizer: Callable[[Request], bool] | None = None,
    message_router: Callable[[dict], dict] | None = None,
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
    capabilities = {
        "auth_required": True,
        "write_available": writable,
        "targets": ["oracle"],
        "intents": ["question", "change_request"],
        "nara_interaction": "ask_oracle_about_nara",
    }
    router = APIRouter(prefix="/api/daily-ops", tags=["daily-ops"])

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

    app.include_router(router)
    return router
