"""Immutable claim values for a future, explicitly integrated I1 boundary.

Pure functions: no models, cache, journal, ledger, or filesystem access.
This version uses sorted compact JSON (not RFC 8785); no Unicode/text
normalization or lossy metadata extraction is performed. Existing runtime
callers do not use this candidate. Consistent bytes do not authenticate actors.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math
import re
from typing import Any


class BindingError(ValueError):
    """An identity or canonical input cannot be verified."""


def digest(data: bytes) -> str:
    return "sha256:" + sha256(data).hexdigest()


def require_digest(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        raise BindingError("expected a lowercase sha256 digest")
    return value


def require_id(value: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise BindingError("expected a nonempty identity without outer whitespace")
    return value


def _validate_json(value: Any) -> None:
    if type(value) is str:
        value.encode("utf-8", errors="strict")
    elif type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise BindingError("JSON object keys must be strings")
            _validate_json(key)
            _validate_json(item)
    elif type(value) is list:
        for item in value:
            _validate_json(item)
    elif type(value) is float:
        if not math.isfinite(value):
            raise BindingError("non-finite JSON number")
    elif value is not None and type(value) not in (bool, int):
        raise BindingError("non-JSON value")


def canonical_bytes(value: Any) -> bytes:
    try:
        _validate_json(value)
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise BindingError(f"invalid canonical JSON: {exc}") from exc


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise BindingError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(data: bytes | str) -> Any:
    try:
        result = json.loads(data, object_pairs_hook=_pairs)
        canonical_bytes(result)  # also reject NaN, overflow, invalid scalars
        return result
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise BindingError(f"invalid JSON evidence: {exc}") from exc


@dataclass(frozen=True)
class Claim:
    canonical: bytes
    claim_sha256: str
    supersedes: str | None = None

    def __post_init__(self):
        if type(self.canonical) is not bytes:
            raise BindingError("claim must own immutable bytes")
        payload = load_json(self.canonical)
        if type(payload) is not dict or not isinstance(payload.get("text"), str) \
                or not payload["text"].strip():
            raise BindingError("claim requires a nonempty text field")
        if canonical_bytes(payload) != self.canonical:
            raise BindingError("claim bytes are not canonical")
        require_digest(self.claim_sha256)
        if digest(self.canonical) != self.claim_sha256:
            raise BindingError("claim bytes/hash mismatch")
        if self.supersedes is not None:
            require_digest(self.supersedes)
            if self.supersedes == self.claim_sha256:
                raise BindingError("a revision must change the claim")

    def payload(self) -> dict:
        return load_json(self.canonical)  # fresh object, never owned state


def admit_claim(payload: dict, *, supersedes: Claim | None = None) -> Claim:
    data = canonical_bytes(payload)
    return Claim(data, digest(data), None if supersedes is None
                 else supersedes.claim_sha256)


def bind_arguments(claim: Claim, arguments: dict, *, attempt_id: str,
                   iteration_id: str) -> dict:
    """Supply canonical inputs; future worker adapters must accept this shape."""
    if type(arguments) is not dict:
        raise BindingError("arguments must be an object")
    out = load_json(canonical_bytes(arguments))
    out.update(attempt_id=require_id(attempt_id),
               iteration_id=require_id(iteration_id),
               input_claim_sha256=claim.claim_sha256,
               input_claim=claim.payload(),
               hypothesis_text=claim.payload()["text"])
    return out


def verify_binding(claim: Claim, value: dict, *, attempt_id: str,
                   iteration_id: str) -> None:
    """Fail closed before a future dispatch or journal eligibility decision."""
    if type(value) is not dict:
        raise BindingError("binding must be an object")
    expected = {"attempt_id": require_id(attempt_id),
                "iteration_id": require_id(iteration_id),
                "input_claim_sha256": claim.claim_sha256}
    if any(value.get(key) != item for key, item in expected.items()):
        raise BindingError("missing or mismatched claim/attempt/iteration identity")
    if canonical_bytes(value.get("input_claim")) != claim.canonical:
        raise BindingError("input claim bytes mismatch")
    if value.get("hypothesis_text") != claim.payload()["text"]:
        raise BindingError("hypothesis text mismatch")
