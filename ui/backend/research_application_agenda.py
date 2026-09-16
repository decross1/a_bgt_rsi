"""Authored research direction, explicitly separate from executed study evidence."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "docs/v2/research_application_agenda.json"
SCHEMA = "research-application-agenda/v1"
MAX_SOURCE_BYTES = 32_768
MAX_TEXT = 4_096
MAX_URL = 2_048
MAX_LIST = 32
SAFE_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,95}\Z")
TOP_FIELDS = {
    "schema_version", "agenda_id", "recorded_at", "status",
    "owner_direction", "selection_rule", "horizon", "research_question",
    "execution_authorized", "data_entitlement_verified", "lanes",
    "next_agenda", "history_policy", "sources",
}
LANE_FIELDS = {
    "id", "label", "priority", "status", "mechanism", "test",
    "requirements", "kill_condition", "source_ids",
}
NEXT_FIELDS = {"id", "label", "status", "deliverable"}
SOURCE_FIELDS = {"id", "title", "url", "accessed_at"}
LANE_CONTRACT = (
    ("options", "preferred_to_investigate", "data_and_identification_review"),
    (
        "prediction_markets", "alternative_if_mechanism_fits",
        "data_and_identification_review",
    ),
    ("crypto", "mechanism_dependent", "no_default_asset_selected"),
)
NEXT_IDS = ("mechanism", "data", "experiment", "transfer")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate agenda key: {key}")
        result[key] = value
    return result


def _text(value, *, maximum=MAX_TEXT) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= maximum
        and value == value.strip()
        and all(ord(char) >= 32 or char in "\t\n\r" for char in value)
    )


def _identifier(value) -> bool:
    return isinstance(value, str) and SAFE_ID.fullmatch(value) is not None


def _string_list(value, *, identifiers=False) -> bool:
    return (
        isinstance(value, list)
        and len(value) <= MAX_LIST
        and all(_identifier(item) if identifiers else _text(item) for item in value)
        and len(set(value)) == len(value)
    )


def _utc_timestamp(value) -> bool:
    if not isinstance(value, str) or len(value) > 40 or not value.endswith("Z"):
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == timezone.utc.utcoffset(parsed)


def _calendar_date(value) -> bool:
    if not isinstance(value, str) or len(value) != 10:
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _web_url(value) -> bool:
    if (
        not isinstance(value, str)
        or not _text(value, maximum=MAX_URL)
        or any(char.isspace() or char == "\\" for char in value)
    ):
        return False
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except (ValueError, UnicodeError):
        return False
    return (
        parsed.scheme in {"http", "https"}
        and bool(parsed.hostname)
        and "." in parsed.hostname
        and parsed.username is None
        and parsed.password is None
        and (port is None or 1 <= port <= 65_535)
    )


def _display_shape(data: dict) -> bool:
    if set(data) != TOP_FIELDS:
        return False
    if not (
        data.get("schema_version") == SCHEMA
        and _identifier(data.get("agenda_id"))
        and _utc_timestamp(data.get("recorded_at"))
        and data.get("status") == "proposed_research_agenda"
        and all(
            _text(data.get(key))
            for key in (
                "owner_direction", "selection_rule", "horizon",
                "research_question", "history_policy",
            )
        )
        and data.get("execution_authorized") is False
        and data.get("data_entitlement_verified") is False
    ):
        return False

    lanes = data.get("lanes")
    if not isinstance(lanes, list) or len(lanes) != len(LANE_CONTRACT):
        return False
    for lane, (lane_id, priority, status) in zip(lanes, LANE_CONTRACT):
        if not (
            isinstance(lane, dict)
            and set(lane) == LANE_FIELDS
            and lane.get("id") == lane_id
            and lane.get("priority") == priority
            and lane.get("status") == status
            and all(
                _text(lane.get(key))
                for key in ("label", "mechanism", "test", "kill_condition")
            )
            and _string_list(lane.get("requirements"))
            and _string_list(lane.get("source_ids"), identifiers=True)
        ):
            return False

    next_agenda = data.get("next_agenda")
    if not isinstance(next_agenda, list) or len(next_agenda) != len(NEXT_IDS):
        return False
    for row, expected_id in zip(next_agenda, NEXT_IDS):
        if not (
            isinstance(row, dict)
            and set(row) == NEXT_FIELDS
            and row.get("id") == expected_id
            and row.get("status") == "proposed"
            and _text(row.get("label"))
            and _text(row.get("deliverable"))
        ):
            return False

    sources = data.get("sources")
    if not isinstance(sources, list) or not (1 <= len(sources) <= MAX_LIST):
        return False
    source_ids = []
    for source in sources:
        if not (
            isinstance(source, dict)
            and set(source) == SOURCE_FIELDS
            and _identifier(source.get("id"))
            and _text(source.get("title"))
            and _web_url(source.get("url"))
            and _calendar_date(source.get("accessed_at"))
        ):
            return False
        source_ids.append(source["id"])
    referenced = {
        source_id for lane in lanes for source_id in lane["source_ids"]
    }
    return len(set(source_ids)) == len(source_ids) and referenced == set(source_ids)


def _read_source(path: Path) -> bytes:
    if path.is_symlink() or path.resolve() != path.absolute():
        raise ValueError("agenda source redirected")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as handle:
        before = os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_SOURCE_BYTES:
            raise ValueError("agenda source is not a bounded regular file")
        raw = handle.read(MAX_SOURCE_BYTES + 1)
        after = os.fstat(handle.fileno())
    if (
        len(raw) != before.st_size
        or len(raw) > MAX_SOURCE_BYTES
        or (before.st_dev, before.st_ino, before.st_size)
        != (after.st_dev, after.st_ino, after.st_size)
    ):
        raise ValueError("agenda source changed or exceeded its read bound")
    return raw


def project_agenda(path: Path = DEFAULT_PATH) -> dict:
    result = {"schema_version": SCHEMA,
              "generated_at": datetime.now(timezone.utc).isoformat(),
              "available": False, "agenda": None, "source_sha256": None,
              "warnings": []}
    try:
        raw = _read_source(path)
        data = json.loads(
            raw,
            object_pairs_hook=_unique_object,
            parse_constant=lambda item: (_ for _ in ()).throw(
                ValueError(f"non-finite agenda constant: {item}")
            ),
        )
        if not isinstance(data, dict) or not _display_shape(data):
            raise ValueError("agenda source differs from its declared contract")
        from .iteration_journey import _encoder_safe
        if not _encoder_safe(data):
            raise ValueError("agenda source cannot be safely represented")
        result.update(available=True, agenda=data,
                      source_sha256=hashlib.sha256(raw).hexdigest())
    except (
        OSError, UnicodeError, ValueError, TypeError, AttributeError,
        RecursionError,
    ):
        result["warnings"].append("Research application agenda is unavailable or invalid.")
    return result


def register(app, *, path: Path = DEFAULT_PATH) -> None:
    router = APIRouter()

    @router.get("/api/research_application_agenda")
    def research_application_agenda():
        return project_agenda(path)

    app.include_router(router)
