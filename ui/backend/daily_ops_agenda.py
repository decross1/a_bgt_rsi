"""Read-only projection of the sealed Oracle daily-planning proposal.

The planner database is private authority-bearing state.  This module exposes
only a bounded owner-review projection after verifying the exact v1 canonical
envelope digest used by ``personal_agent.planning``.  It never imports that
separate checkout, writes planner state, approves a proposal, or executes a
task.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

_MAX_LATEST_BYTES = 16 * 1024
_MAX_DATABASE_BYTES = 8 * 1024 * 1024
_MAX_PAYLOAD_BYTES = 32 * 1024
_MAX_PROJECTED_TASK_TITLES = 3
_SEAL_VERSION = 1

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

_UNVERIFIED_WARNING = (
    "Pending Oracle agenda could not be verified; no plan revision or action "
    "binding is available."
)


class _InvalidAgenda(ValueError):
    """Internal fail-closed signal; details never cross the API boundary."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_time(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value or len(value) > 64:
        raise _InvalidAgenda(f"{field} is not a timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _InvalidAgenda(f"{field} is not a timestamp") from exc
    if parsed.tzinfo is None:
        raise _InvalidAgenda(f"{field} has no timezone")
    return parsed.astimezone(timezone.utc)


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise _InvalidAgenda("duplicate JSON key")
        value[key] = item
    return value


def _reject_constant(_value):
    raise _InvalidAgenda("non-finite JSON number")


def _read_regular(path: Path, maximum: int) -> bytes:
    fd = os.open(
        path,
        os.O_RDONLY
        | os.O_NONBLOCK
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise _InvalidAgenda("source is not one regular file")
        if before.st_size > maximum:
            raise _InvalidAgenda("source exceeds its byte bound")
        raw = bytearray()
        while True:
            chunk = os.read(fd, min(8192, maximum + 1 - len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
            if len(raw) > maximum:
                raise _InvalidAgenda("source exceeds its byte bound")
        after = os.fstat(fd)
        identity = lambda item: (
            item.st_dev, item.st_ino, item.st_mode, item.st_nlink,
            item.st_size, item.st_mtime_ns, item.st_ctime_ns,
        )
        if identity(before) != identity(after) or len(raw) != before.st_size:
            raise _InvalidAgenda("source changed while being read")
        return bytes(raw)
    finally:
        os.close(fd)


def _load_json_object(raw: bytes, maximum: int) -> dict[str, Any]:
    if len(raw) > maximum:
        raise _InvalidAgenda("JSON exceeds its byte bound")
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise _InvalidAgenda("invalid JSON") from exc
    if not isinstance(value, dict):
        raise _InvalidAgenda("expected a JSON object")
    return value


def _canonical_json(value: object) -> bytes:
    try:
        raw = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise _InvalidAgenda("value is not finite canonical JSON") from exc
    if len(raw) > _MAX_PAYLOAD_BYTES:
        raise _InvalidAgenda("canonical envelope exceeds its byte bound")
    return raw


def _text(value: object, field: str, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > maximum
        or "\x00" in value
    ):
        raise _InvalidAgenda(f"{field} is invalid")
    return value


def _validated_payload(payload: object) -> dict[str, Any]:
    """Validate only fields needed for safe display and proposal authority.

    Model, context, budget, workspace, and future informational fields remain
    part of the canonical digest but are not reinterpreted here.  Their policy
    belongs to the planner that sealed the proposal, not to this read model.
    """
    if not isinstance(payload, dict):
        raise _InvalidAgenda("payload is not an object")
    value = payload
    if (
        value.get("version") != 1
        or value.get("authority") != "proposal_only"
        or value.get("mode") != "read"
    ):
        raise _InvalidAgenda("payload authority or version is invalid")
    _text(value.get("objective"), "payload.objective", 2000)

    tasks = value.get("tasks")
    if not isinstance(tasks, list) or not 1 <= len(tasks) <= 16:
        raise _InvalidAgenda("payload task count is invalid")
    seen: set[str] = set()
    for index, raw_task in enumerate(tasks):
        required = {"id", "title", "why_now", "artifact", "validation", "owner"}
        if not isinstance(raw_task, dict) or not required.issubset(raw_task):
            raise _InvalidAgenda(f"payload.tasks[{index}] is invalid")
        task_id = raw_task["id"]
        if not isinstance(task_id, str) or not _ID.fullmatch(task_id) or task_id in seen:
            raise _InvalidAgenda("payload task id is invalid")
        seen.add(task_id)
        _text(raw_task["title"], "task.title", 200)
        _text(raw_task["why_now"], "task.why_now", 1200)
        _text(raw_task["artifact"], "task.artifact", 500)
        _text(raw_task["validation"], "task.validation", 1000)
        _text(raw_task["owner"], "task.owner", 80)

    # This also applies the original 32 KiB finite canonical JSON bound.
    _canonical_json(value)
    return value


def _database_row(database: Path, agenda_id: str, revision: str) -> tuple:
    info = database.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or info.st_size <= 0
        or info.st_size > _MAX_DATABASE_BYTES
    ):
        raise _InvalidAgenda("planner database is not a bounded regular file")

    uri = f"file:{quote(str(database.absolute()), safe='/')}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=0.25)
    try:
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA trusted_schema = OFF")
        connection.execute("PRAGMA busy_timeout = 250")
        if hasattr(connection, "setlimit"):
            connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 128 * 1024)
            connection.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, 4096)
            connection.setlimit(sqlite3.SQLITE_LIMIT_COLUMN, 32)
        progress = [0]

        def bounded_query():
            progress[0] += 1
            return int(progress[0] > 200)

        connection.set_progress_handler(bounded_query, 1000)
        rows = connection.execute(
            "SELECT agenda_id, revision_sha256, payload_json, created_at, expires_at, "
            "envelope_sha256, proposal_schema_version FROM agenda_proposals "
            "WHERE agenda_id = ? AND revision_sha256 = ? LIMIT 2",
            (agenda_id, revision),
        ).fetchall()
    finally:
        connection.close()
    if len(rows) != 1:
        raise _InvalidAgenda("configured planner row is missing or ambiguous")
    return rows[0]


def _decision(payload: dict[str, Any], *, agenda_id: str, revision: str,
              created: datetime, stale: bool) -> dict[str, object]:
    """Project one proposal-level review decision, never task-level blockers."""
    if stale:
        disposition = "amend_required"
        reason = (
            "This sealed proposal predates the selected research focus. Request an "
            "amendment against this exact revision before reviewing a replacement."
        )
    else:
        disposition = "review_required"
        reason = (
            "The sealed proposal has not received an exact-revision semantic review. "
            "Review or request an amendment; no execution is available from this card."
        )
    tasks = payload["tasks"]
    return {
        "id": f"agenda-{revision[:16]}",
        "agenda_id": agenda_id,
        "revision": revision,
        "title": "Review the proposed research agenda",
        "what": payload["objective"],
        "reason": reason,
        "disposition": disposition,
        "approval_required": False,
        "approve_enabled": False,
        "execution_available": False,
        "actions": ["modify", "skip"],
        "task_titles": [
            task["title"] for task in tasks[:_MAX_PROJECTED_TASK_TITLES]
        ],
        "source": f"Oracle proposal {agenda_id}; sealed revision {revision}",
        "observed_at": _iso(created),
    }


def read_pending_agenda(latest_path: str | Path,
                        focus_observed_at: str | None) -> dict[str, object]:
    """Return a bounded, verified pending-agenda projection.

    Any unknown schema, changed digest, unsafe source, missing sealed row, or
    SQLite failure removes both the revision and all task bindings.  A missing
    ``latest.json`` simply means there is no proposal to show.
    """

    result: dict[str, object] = {
        "agenda_id": None,
        "revision": None,
        "decision": None,
        "warnings": [],
    }
    latest = Path(latest_path).expanduser().absolute()
    try:
        raw = _read_regular(latest, _MAX_LATEST_BYTES)
    except FileNotFoundError:
        return result
    except (OSError, _InvalidAgenda):
        result["warnings"] = [_UNVERIFIED_WARNING]
        return result

    try:
        pointer = _load_json_object(raw, _MAX_LATEST_BYTES)
        if (
            pointer.get("schema_version") != "oracle-daily-proposal-cycle/v1"
            or pointer.get("execution_enabled") is not False
            or pointer.get("owner_approval") != "absent"
            or pointer.get("status") not in {"pending_owner_review", "unchanged_pending_review"}
        ):
            raise _InvalidAgenda("latest pointer is not a pending v1 proposal")
        agenda_id = pointer.get("agenda_id")
        revision = pointer.get("revision_sha256")
        if not isinstance(agenda_id, str) or not _ID.fullmatch(agenda_id):
            raise _InvalidAgenda("latest agenda id is invalid")
        if not isinstance(revision, str) or not _SHA256.fullmatch(revision):
            raise _InvalidAgenda("latest revision is invalid")

        row = _database_row(latest.parent / "agendas" / "planning.sqlite3", agenda_id, revision)
        (row_agenda, row_revision, payload_json, created_raw, expires_raw,
         envelope_sha, schema_version) = row
        if (
            row_agenda != agenda_id
            or row_revision != revision
            or envelope_sha != revision
            or type(schema_version) is not int
            or schema_version != _SEAL_VERSION
            or not isinstance(payload_json, str)
            or len(payload_json.encode("utf-8")) > _MAX_PAYLOAD_BYTES
        ):
            raise _InvalidAgenda("sealed row identity or schema is invalid")

        payload = _validated_payload(_load_json_object(
            payload_json.encode("utf-8"), _MAX_PAYLOAD_BYTES,
        ))
        created = _parse_time(created_raw, "created_at")
        expires = _parse_time(expires_raw, "expires_at")
        pointer_expiry = _parse_time(pointer.get("expires_at"), "latest.expires_at")
        if expires <= created or pointer_expiry != expires:
            raise _InvalidAgenda("proposal timestamps do not match")
        envelope = {
            "version": _SEAL_VERSION,
            "agenda_id": agenda_id,
            "created_at": _iso(created),
            "expires_at": _iso(expires),
            "payload": payload,
        }
        expected = hashlib.sha256(_canonical_json(envelope)).hexdigest()
        if expected != revision:
            raise _InvalidAgenda("canonical proposal digest changed")

        if _now() >= expires:
            result["warnings"] = [
                f"Pending Oracle agenda expired at {_iso(expires)}; no plan revision or decision is active."
            ]
            return result

        focus_time = None
        if focus_observed_at is not None:
            focus_time = _parse_time(focus_observed_at, "focus_observed_at")
        stale = focus_time is not None and created < focus_time
        tasks = payload["tasks"]
        warnings: list[str] = []
        if len(tasks) > _MAX_PROJECTED_TASK_TITLES:
            warnings.append(
                f"Pending Oracle agenda contains {len(tasks)} tasks; only the first "
                f"{_MAX_PROJECTED_TASK_TITLES} task titles are shown."
            )
        result.update(
            agenda_id=agenda_id,
            revision=revision,
            decision=_decision(
                payload, agenda_id=agenda_id, revision=revision,
                created=created, stale=stale,
            ),
            warnings=warnings,
        )
        return result
    except (OSError, sqlite3.Error, UnicodeError, TypeError, KeyError, _InvalidAgenda):
        result["warnings"] = [_UNVERIFIED_WARNING]
        return result


__all__ = ["read_pending_agenda"]
