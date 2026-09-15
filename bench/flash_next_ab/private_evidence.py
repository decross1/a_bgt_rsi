"""UNAPPLIED DRAFT: bind public call receipts to private local raw evidence.

The returned audit records contain content; this reader exposes only counts
and digests. A dashboard must never serialize these records to its API.
"""
from __future__ import annotations

import hashlib
import os
import re
import stat
from pathlib import Path

from .harness import (
    _BASE_URLS,
    MAX_PRIVATE_METADATA_BYTES,
    PRIVATE_CALL_SCHEMA,
    PRIVATE_INDEX_SCHEMA,
    _read_regular_file,
    _strict_object,
)
from .manifest import sha256_json
from .qualification import _open_nofollow_regular
from .transport import (
    MAX_RESPONSE_BYTES,
    LocalEndpoint,
    StreamAccumulator,
    TransportError,
    _sse_data,
    canonical,
    request_body,
)


class PrivateEvidenceError(ValueError):
    """The recorded model request/response provenance changed or is missing."""


def _require(valid: bool, message: str) -> None:
    if not valid:
        raise PrivateEvidenceError(message)


def _recorded(path: Path, *, label: str, ceiling: int, digest: str, count: int,
              allow_empty_transport: bool = False) -> bytes:
    _require(type(count) is int and 0 <= count <= ceiling, f"{label} length is invalid")
    if count == 0:
        _require(allow_empty_transport and digest == hashlib.sha256(b"").hexdigest(),
                 f"{label} zero-length stream is not a failed transport receipt")
        # Harness's general receipt reader intentionally refuses empty files.
        # A failed local transport can genuinely time out before the first SSE
        # byte. Bind that *one* private response through the same audited
        # openat/nofollow/nonblocking regular-file path without broadening JSON.
        descriptor = _open_nofollow_regular(path.absolute())
        try:
            initial = os.fstat(descriptor)
            _require(stat.S_ISREG(initial.st_mode) and initial.st_size == 0
                     and os.read(descriptor, 1) == b"", f"{label} is not an empty regular file")
            final = os.fstat(descriptor)
            _require(final.st_size == 0 and final.st_mtime_ns == initial.st_mtime_ns,
                     f"{label} changed during nofollow read")
        finally:
            os.close(descriptor)
        return b""
    raw, actual = _read_regular_file(path, label=label, max_bytes=ceiling)
    _require(
        actual == path.absolute() and len(raw) == count
        and hashlib.sha256(raw).hexdigest() == digest,
        f"{label} bytes or raw SHA-256 differ",
    )
    return raw


def _request_matches_raw(request: dict, call: dict) -> None:
    """Recompute the complete request digest from private messages and policy."""
    name = request.get("endpoint_name")
    _require(
        isinstance(name, str) and name in _BASE_URLS,
        "private request endpoint is not registered",
    )
    try:
        fingerprints_match = (
            sha256_json(request.get("resolved_policy")) == call.get("resolved_policy_sha256")
            and sha256_json(request.get("messages")) == call.get("messages_sha256")
            and sha256_json(request.get("tools")) == call.get("tools_sha256")
        )
    except (TypeError, ValueError) as exc:
        raise PrivateEvidenceError("private request fields are malformed") from exc
    _require(
        fingerprints_match,
        "public policy, messages or tool digest differs from private request",
    )
    try:
        endpoint = LocalEndpoint(
            name, _BASE_URLS[name], request["served_model"], request["artifact_sha256"]
        )
        tools = request.get("tools")
        body = request_body(
            endpoint, request["messages"], request["resolved_policy"],
            request["max_tokens"], request["seed"], tools or None,
        )
        expected = hashlib.sha256(canonical(body)).hexdigest()
    except (KeyError, TypeError, ValueError) as exc:
        raise PrivateEvidenceError("private request body is malformed") from exc
    _require(expected == call.get("request_sha256"), "private rendered request digest differs")


def _response_matches_raw(raw_stream: bytes, response: dict, call: dict) -> None:
    """Replay only completed SSE streams; errors remain recorded denominator cells."""
    try:
        accumulator = StreamAccumulator(call["served_model"])
        for line in raw_stream.splitlines():
            if accumulator.done and line.strip(b"\r"):
                raise PrivateEvidenceError("bytes appeared after response terminal marker")
            payload = _sse_data(line.rstrip(b"\r"))
            if payload is not None:
                accumulator.accept(payload)
        replayed = accumulator.result()
    except (KeyError, TypeError, ValueError, TransportError) as exc:
        raise PrivateEvidenceError("private returned response SSE is malformed") from exc
    for key in (
        "content", "reasoning_content", "tool_calls", "response_id",
        "response_model", "finish_reason", "usage",
    ):
        _require(replayed[key] == response.get(key), f"private response {key} differs from SSE")
    _require(
        replayed["stream_events"] >= 1,
        "private response SSE has no completed events",
    )


def validate_private_evidence(run: dict, harness_output: Path) -> dict:
    """Prove every returned/public call has its own nofollow private file."""
    _require(
        isinstance(run, dict) and run.get("status") == "complete"
        and isinstance(run.get("outcomes"), list),
        "the audited benchmark cohort was not complete",
    )
    calls_verified = 0
    streams_verified = 0
    identifiers: set[str] = set()
    metadata_paths: set[str] = set()
    for outcome in run["outcomes"]:
        _require(isinstance(outcome, dict), "benchmark outcome has no private provenance")
        calls = outcome.get("calls")
        grade = outcome.get("grade")
        details = grade.get("details") if isinstance(grade, dict) else None
        private = details.get("_private_call_evidence") if isinstance(details, dict) else None
        _require(
            isinstance(calls, list) and isinstance(private, dict)
            and private.get("schema_version") == PRIVATE_INDEX_SCHEMA
            and isinstance(private.get("artifacts"), list)
            and len(private["artifacts"]) == len(calls),
            "declared calls are missing their private evidence index",
        )
        for call, descriptor in zip(calls, private["artifacts"], strict=True):
            _require(
                isinstance(call, dict) and isinstance(descriptor, dict)
                and set(descriptor) == {
                    "call_id", "status", "metadata_path", "metadata_sha256",
                    "metadata_bytes", "raw_stream"
                }
                and descriptor["call_id"] == call.get("call_id")
                and descriptor["status"] == call.get("status")
                and descriptor["call_id"] not in identifiers
                and isinstance(descriptor["metadata_path"], str)
                and descriptor["metadata_path"] not in metadata_paths
                and re.fullmatch(
                    r"private/calls/[0-9]{4}-[0-9a-f]{16}\.json",
                    descriptor["metadata_path"],
                ) is not None,
                "public/private call identity or bounded metadata path differs",
            )
            identifiers.add(descriptor["call_id"])
            metadata_paths.add(descriptor["metadata_path"])
            metadata = _strict_object(
                _recorded(
                    harness_output / descriptor["metadata_path"],
                    label="private model call metadata", ceiling=MAX_PRIVATE_METADATA_BYTES,
                    digest=descriptor["metadata_sha256"],
                    count=descriptor["metadata_bytes"],
                ),
                "private model call metadata",
            )
            request = metadata.get("request")
            response = metadata.get("response")
            returned = call.get("status") == "returned"
            response_fields_bound = (
                all(response.get(key) == call.get(key) for key in (
                    "response_stream_sha256", "response_id", "response_model",
                    "finish_reason", "usage"
                )) if returned else all(
                    call.get(key) is None for key in (
                        "response_stream_sha256", "response_id", "response_model",
                        "finish_reason"
                    )
                )
            ) if isinstance(response, dict) else False
            _require(
                metadata.get("schema_version") == PRIVATE_CALL_SCHEMA
                and metadata.get("call_id") == call.get("call_id")
                and metadata.get("status") == call.get("status")
                and metadata.get("call_index") == call.get("call_index")
                and metadata.get("role") == call.get("role")
                and metadata.get("failure_code") == call.get("failure_code")
                and metadata.get("error") == call.get("error")
                and isinstance(request, dict) and isinstance(response, dict)
                and all(request.get(key) == call.get(key) for key in (
                    "endpoint_name", "served_model", "artifact_sha256",
                    "policy_id", "seed", "max_tokens", "timeout_s",
                    "request_sha256"
                ))
                and response_fields_bound
                and response.get("raw_stream_artifact") == descriptor.get("raw_stream"),
                "private request/response transcript differs from call receipt",
            )
            _request_matches_raw(request, call)
            stream = descriptor["raw_stream"]
            if stream is not None:
                stem = descriptor["metadata_path"].split("/")[-1].removesuffix(".json")
                _require(
                    isinstance(stream, dict)
                    and set(stream) == {"path", "sha256", "bytes"}
                    and stream.get("path") == f"private/streams/{stem}.sse"
                    and stream.get("sha256") == response.get("response_stream_sha256")
                    and (not returned or stream["sha256"] == call.get("response_stream_sha256")),
                    "model response stream descriptor differs from public call",
                )
                raw_stream = _recorded(
                    harness_output / stream["path"], label="raw model response stream",
                    ceiling=MAX_RESPONSE_BYTES, digest=stream["sha256"],
                    count=stream["bytes"],
                    allow_empty_transport=(
                        call.get("status") in {"timeout", "cancelled", "error"}
                        and call.get("failure_code") in {
                            "transport_timeout", "transport_cancelled", "transport_error"
                        }
                        and (response.get("content") == "" or response.get("content") is None)
                        and (response.get("reasoning_content") == "" or
                             response.get("reasoning_content") is None)
                        and response.get("tool_calls") == []
                        and response.get("response_id") is None
                        and response.get("finish_reason") is None
                        and response.get("usage") is None
                    ),
                )
                if call.get("status") == "returned":
                    _response_matches_raw(raw_stream, response, call)
                streams_verified += 1
            else:
                _require(
                    call.get("response_stream_sha256") is None
                    and response.get("response_stream_sha256") is None,
                    "nonempty model response lacks its private raw stream",
                )
            calls_verified += 1
    _require(calls_verified > 0, "complete benchmark produced no audited calls")
    return {
        "schema": "flash-next-private-call-raw-validation/v1",
        "calls_verified": calls_verified,
        "response_streams_verified": streams_verified,
        "private_content_exported": False,
    }
