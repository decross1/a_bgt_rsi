"""Bounded, exact-source projection for concise daily work cards.

The curated input is reviewer-authored UI data.  It may summarize authorized
development and an agenda review, but it cannot approve, seal, dispatch, or
execute either one.  Every projection is bound to both the currently verified
sealed proposal and the selected research-focus receipt so stale advice drops
out instead of surviving a focus or revision change.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .daily_ops import (
    MAX_SHORT_TEXT,
    MAX_TEXT,
    _identifier,
    _json_safe,
    _read_regular,
    _text,
    _timestamp,
    _unique_object,
)

WORK_PLAN_SCHEMA = "daily-ops-work-plan/v1"
MAX_WORK_PLAN_BYTES = 32_768
MAX_WORK_CARDS = 3

_CARD_FIELDS = {
    "id", "title", "what", "benefit", "cost", "conviction", "worth_time",
    "status", "owner", "depends_on",
}
_PLAN_FIELDS = {
    "schema_version", "agenda_id", "revision", "focus_receipt_sha256",
    "observed_at", "disposition", "decision_title", "decision_summary",
    "decision_reason", "source", "cards",
}
_CARD_STATUSES = {"authorized", "in_progress", "blocked", "done", "draft"}
_CARD_OWNERS = {"codex", "oracle", "nara", "lab"}
_EVIDENCE_KINDS = {"estimate", "measured", "unrated"}
_TIMING = {"do_now", "after_dependency", "hold", "unrated"}
_DISPOSITIONS = {"amend_required", "review_required"}
_SHA256 = set("0123456789abcdef")


def _sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in _SHA256 for char in value)
    )


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


def _worth_time(value: object) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {"recommendation", "basis"}
        and value.get("recommendation") in _TIMING
        and _text(value.get("basis"), MAX_SHORT_TEXT)
    )


def _validated_card(value: object, *, prior_ids: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _CARD_FIELDS:
        raise ValueError("work card fields are invalid")
    dependencies = value.get("depends_on")
    if (
        not _identifier(value.get("id"))
        or not _text(value.get("title"), MAX_SHORT_TEXT)
        or not _text(value.get("what"), MAX_TEXT)
        or not _text(value.get("benefit"), MAX_TEXT)
        or not _evidence(value.get("cost"))
        or not _conviction(value.get("conviction"))
        or not _worth_time(value.get("worth_time"))
        or value.get("status") not in _CARD_STATUSES
        or value.get("owner") not in _CARD_OWNERS
        or not isinstance(dependencies, list)
        or len(dependencies) > MAX_WORK_CARDS
        or len(set(dependencies)) != len(dependencies)
        or not all(_identifier(item) and item in prior_ids for item in dependencies)
    ):
        raise ValueError("work card is invalid")
    if value["id"] in prior_ids:
        raise ValueError("work card id is duplicated")
    return dict(value)


def _load_curated(path: Path) -> dict[str, Any]:
    raw = _read_regular(path, MAX_WORK_PLAN_BYTES)
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
        raise ValueError("curated work plan is invalid JSON") from exc
    if not isinstance(value, dict) or set(value) != _PLAN_FIELDS:
        raise ValueError("curated work plan fields are invalid")
    return value


def read_work_plan(
    path: str | Path,
    *,
    agenda: dict[str, object],
    focus_receipt_sha256: str | None,
) -> dict[str, object]:
    """Return cards plus a reviewed proposal disposition, or fail closed.

    Missing input is a normal empty state.  Invalid or mismatched input leaves
    the verified agenda's conservative decision intact and emits one bounded
    warning.  No estimates are synthesized from proposal prose.
    """
    fallback = {
        "work_cards": [],
        "agenda_decision": agenda.get("decision"),
        "warnings": [],
    }
    source = Path(path).expanduser().absolute()
    try:
        value = _load_curated(source)
    except FileNotFoundError:
        return fallback
    except (OSError, ValueError):
        fallback["warnings"] = [
            "Reviewed daily work cards are unavailable or invalid; no cost or conviction estimates are shown."
        ]
        return fallback

    try:
        decision = agenda.get("decision")
        if not isinstance(decision, dict):
            raise ValueError("no verified agenda is available")
        if (
            value.get("schema_version") != WORK_PLAN_SCHEMA
            or value.get("agenda_id") != agenda.get("agenda_id")
            or value.get("revision") != agenda.get("revision")
            or not _sha256(value.get("revision"))
            or value.get("focus_receipt_sha256") != focus_receipt_sha256
            or not _sha256(focus_receipt_sha256)
            or not _timestamp(value.get("observed_at"))
            or value.get("disposition") not in _DISPOSITIONS
            or not _text(value.get("decision_title"), MAX_SHORT_TEXT)
            or not _text(value.get("decision_summary"), MAX_TEXT)
            or not _text(value.get("decision_reason"), MAX_TEXT)
            or not _text(value.get("source"), MAX_SHORT_TEXT)
        ):
            raise ValueError("curated work plan source binding is invalid")
        raw_cards = value.get("cards")
        if not isinstance(raw_cards, list) or not 1 <= len(raw_cards) <= MAX_WORK_CARDS:
            raise ValueError("curated work card count is invalid")
        prior_ids: set[str] = set()
        cards = []
        for raw_card in raw_cards:
            card = _validated_card(raw_card, prior_ids=prior_ids)
            prior_ids.add(card["id"])
            cards.append({
                **card,
                "source": value["source"],
                "observed_at": value["observed_at"],
                "approval_required": False,
                "actions": ["modify", "skip", "reprioritize"],
            })
        agenda_decision = {
            **decision,
            "title": value["decision_title"],
            "what": value["decision_summary"],
            "reason": value["decision_reason"],
            "disposition": value["disposition"],
            "approval_required": False,
            "approve_enabled": False,
            "execution_available": False,
            "actions": ["modify", "skip"],
            "source": value["source"],
            "observed_at": value["observed_at"],
        }
        result = {
            "work_cards": cards,
            "agenda_decision": agenda_decision,
            "warnings": [],
        }
        if not _json_safe(result):
            raise ValueError("curated work plan is not safely JSON encodable")
        return result
    except (KeyError, TypeError, ValueError):
        fallback["warnings"] = [
            "Reviewed daily work cards do not match the current agenda and research focus; they were not shown."
        ]
        return fallback


__all__ = ["MAX_WORK_CARDS", "WORK_PLAN_SCHEMA", "read_work_plan"]
