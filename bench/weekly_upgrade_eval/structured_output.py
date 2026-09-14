"""Strict structured-output parsing with explicit, non-salvaging failures.

This boundary intentionally accepts only one JSON object in the visible
completion channel.  It does not strip Markdown fences or reasoning tags,
extract a JSON substring, retry, repair, or coerce field values.  Callers can
therefore distinguish transport/protocol failures from substantive grader
failures without accidentally crediting a malformed response.
"""

from __future__ import annotations

import json
from collections.abc import Collection
from dataclasses import dataclass
from typing import Any

COMPLETION_NOT_TEXT = "completion_not_text"
EMPTY_COMPLETION = "empty_completion"
REASONING_CHANNEL_LEAKAGE = "reasoning_channel_leakage"
MARKDOWN_ENVELOPE = "markdown_envelope"
DUPLICATE_JSON_KEY = "duplicate_json_key"
NON_FINITE_JSON = "non_finite_json"
MALFORMED_JSON = "malformed_json"
TOP_LEVEL_SCHEMA = "top_level_schema"
FIELD_SCHEMA = "field_schema"

FAILURE_CODES = frozenset(
    {
        COMPLETION_NOT_TEXT,
        EMPTY_COMPLETION,
        REASONING_CHANNEL_LEAKAGE,
        MARKDOWN_ENVELOPE,
        DUPLICATE_JSON_KEY,
        NON_FINITE_JSON,
        MALFORMED_JSON,
        TOP_LEVEL_SCHEMA,
        FIELD_SCHEMA,
    }
)

_REASONING_MARKERS = (
    "<think>",
    "</think>",
    "<analysis>",
    "</analysis>",
    "[analysis]",
    "[/analysis]",
)


class _DuplicateKey(ValueError):
    pass


class _NonFinite(ValueError):
    pass


@dataclass(frozen=True)
class StructuredObjectResult:
    """Result of parsing one visible completion under a strict JSON contract."""

    payload: dict[str, Any] | None
    failure_code: str | None
    failure_detail: str | None

    @property
    def valid(self) -> bool:
        return self.failure_code is None

    def diagnostic(self) -> dict[str, str] | None:
        if self.failure_code is None:
            return None
        return {
            "failure_code": self.failure_code,
            "failure_detail": self.failure_detail or "structured output rejected",
        }


def _failed(code: str, detail: str) -> StructuredObjectResult:
    return StructuredObjectResult(None, code, detail)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey("duplicate object key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> Any:
    raise _NonFinite("non-finite JSON constant")


def parse_strict_json_object(
    content: Any,
    *,
    expected_keys: Collection[str] | None = None,
    reasoning_text: str | None = None,
) -> StructuredObjectResult:
    """Parse exactly one JSON object without repair, extraction, or coercion.

    ``reasoning_text`` is optional separate-channel text supplied by a caller.
    When present, an exact non-trivial echo in ``content`` is classified as
    reasoning-channel leakage.  Explicit reasoning tags in visible content are
    classified the same way even when the server does not expose that channel.
    """

    if not isinstance(content, str):
        return _failed(COMPLETION_NOT_TEXT, "visible completion is not text")
    if not content.strip():
        return _failed(EMPTY_COMPLETION, "visible completion is empty")

    lowered = content.casefold()
    if any(marker in lowered for marker in _REASONING_MARKERS):
        return _failed(
            REASONING_CHANNEL_LEAKAGE,
            "visible completion contains an explicit reasoning-channel marker",
        )
    if (
        isinstance(reasoning_text, str)
        and len(reasoning_text.strip()) >= 8
        and reasoning_text.strip() in content
    ):
        return _failed(
            REASONING_CHANNEL_LEAKAGE,
            "separate reasoning text was repeated in the visible completion",
        )
    if content.lstrip().startswith("```") or content.rstrip().endswith("```"):
        return _failed(
            MARKDOWN_ENVELOPE,
            "visible completion uses a Markdown fence around the JSON payload",
        )

    try:
        payload = json.loads(
            content,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except _DuplicateKey:
        return _failed(DUPLICATE_JSON_KEY, "JSON object contains a duplicate key")
    except _NonFinite:
        return _failed(NON_FINITE_JSON, "JSON contains NaN or an infinite value")
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return _failed(
            MALFORMED_JSON,
            f"visible completion is not exactly one JSON value at line {exc.lineno} column {exc.colno}",
        )

    if not isinstance(payload, dict):
        return _failed(TOP_LEVEL_SCHEMA, "top-level JSON value must be an object")
    if expected_keys is not None:
        expected = frozenset(expected_keys)
        if set(payload) != expected:
            return _failed(
                FIELD_SCHEMA,
                "top-level object fields differ from the exact response contract",
            )
    return StructuredObjectResult(payload, None, None)


__all__ = [
    "COMPLETION_NOT_TEXT",
    "DUPLICATE_JSON_KEY",
    "EMPTY_COMPLETION",
    "FAILURE_CODES",
    "FIELD_SCHEMA",
    "MALFORMED_JSON",
    "MARKDOWN_ENVELOPE",
    "NON_FINITE_JSON",
    "REASONING_CHANNEL_LEAKAGE",
    "TOP_LEVEL_SCHEMA",
    "StructuredObjectResult",
    "parse_strict_json_object",
]
