"""Bounded model-wire evidence for the excluded native-tool v2 shakedown.

This module is deliberately narrower than the runner.  It renders one frozen
request, records one transport attempt, and replays the resulting private
request/response evidence.  It never executes a tool or grades model content.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bench.flash_next_ab import harness, private_evidence, transport
from experiments.payoff_tool_arithmetic import flash_resident as resident

from .design import (
    CALL_TIMEOUT_S,
    MAX_TOKENS,
    POLICY,
    POLICY_ID,
    PRIVATE_SCHEMA,
    canonical,
    sha,
)

ROLE = "excluded_calibration_v2"
_MAX_ORDINAL = 9_999
_MAX_ERROR_CHARS = 4_096
_DIGEST = re.compile(r"[0-9a-f]{64}")
_METADATA_PATH = re.compile(r"private/calls/[0-9]{4}-[0-9a-f]{16}\.json")
_STREAM_PATH = re.compile(r"private/streams/[0-9]{4}-[0-9a-f]{16}\.sse")

_DESCRIPTOR_KEYS = {
    "call_id",
    "status",
    "metadata_path",
    "metadata_sha256",
    "metadata_bytes",
    "raw_stream",
}
_METADATA_KEYS = {
    "schema_version",
    "call_id",
    "call_index",
    "role",
    "status",
    "dispatch_state",
    "request",
    "response",
    "failure_code",
    "error",
}
_REQUEST_KEYS = {
    "endpoint_name",
    "served_model",
    "artifact_sha256",
    "policy_id",
    "resolved_policy",
    "resolved_policy_sha256",
    "seed",
    "max_tokens",
    "timeout_s",
    "messages",
    "messages_sha256",
    "tools",
    "tools_sha256",
    "request_sha256",
}
_RESPONSE_KEYS = {
    "content",
    "reasoning_content",
    "tool_calls",
    "content_sha256",
    "reasoning_content_sha256",
    "tool_calls_sha256",
    "response_id",
    "response_model",
    "finish_reason",
    "usage",
    "stream_events",
    "response_bytes",
    "response_stream_sha256",
    "raw_stream_artifact",
}
_CALL_KEYS = {
    "call_index",
    "call_id",
    "role",
    "endpoint_name",
    "served_model",
    "artifact_sha256",
    "policy_id",
    "resolved_policy_sha256",
    "seed",
    "max_tokens",
    "timeout_s",
    "messages_sha256",
    "tools_sha256",
    "request_sha256",
    "status",
    "dispatch_state",
    "wall_s",
    "response_stream_sha256",
    "response_id",
    "response_model",
    "finish_reason",
    "usage",
    "content_sha256",
    "reasoning_content_sha256",
    "tool_calls_sha256",
    "failure_code",
    "error",
}
_STATUSES = {"returned", "timeout", "cancelled", "transport_error", "integrity_error"}
_DISPATCH_STATES = {"confirmed_dispatched", "wire_unknown", "prewire_failure"}


class WireError(ValueError):
    """The v2 wire receipt or its private evidence is not replayable."""


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise WireError(reason)


def _digest(value: Any) -> bool:
    return type(value) is str and _DIGEST.fullmatch(value) is not None


def _strict_utf8_json(value: Any, label: str) -> None:
    """Ensure private evidence can retain the value without Unicode repair."""

    try:
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8", errors="strict")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise WireError(f"{label} is not strict UTF-8 finite JSON") from exc


def _json_sha(value: Any, label: str) -> str:
    _strict_utf8_json(value, label)
    try:
        return sha(canonical(value))
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise WireError(f"{label} is not canonical JSON") from exc


def _text_sha(value: str, label: str) -> str:
    _require(type(value) is str, f"{label} is not text")
    try:
        raw = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise WireError(f"{label} is not strict UTF-8") from exc
    return sha(raw)


def _error_text(exc: BaseException, *, diagnostic: str) -> str:
    """Return a bounded public error label without exception-controlled text."""

    exception_type = type(exc).__name__
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]{0,127}", exception_type) is None:
        exception_type = "Exception"
    _require(
        type(diagnostic) is str
        and re.fullmatch(r"[a-z][a-z0-9 _-]{0,255}", diagnostic) is not None,
        "wire diagnostic label is invalid",
    )
    return f"{exception_type}: {diagnostic}"[:_MAX_ERROR_CHARS]


def _time(value: Any, label: str) -> float:
    _require(
        type(value) in {int, float} and math.isfinite(float(value)),
        f"{label} is not finite",
    )
    return float(value)


def _raw_candidate(value: Any) -> bytes | None:
    if type(value) is not dict:
        return None
    raw = value.get("raw_response_stream")
    if type(raw) is bytes and len(raw) <= transport.MAX_RESPONSE_BYTES:
        return raw
    return None


def _validated_private_response(value: Any) -> dict[str, Any]:
    """Validate transport's complete private envelope, including exact types."""

    try:
        response = harness._private_response(value, returned=None)
    except (harness.HarnessError, TypeError, ValueError) as exc:
        raise WireError("transport private response evidence is malformed") from exc
    _require(type(value) is dict, "transport private response evidence is not an object")
    _require(type(response["raw_response_stream"]) is bytes, "private raw stream type differs")
    _require(type(response["content"]) is str, "private content type differs")
    _require(type(response["reasoning_content"]) is str, "private reasoning type differs")
    _require(type(response["tool_calls"]) is list, "private tool calls type differs")
    _require(
        type(response["stream_events"]) is int and response["stream_events"] >= 0,
        "private stream event count differs",
    )
    _require(
        type(response["response_bytes"]) is int and response["response_bytes"] >= 0,
        "private response byte count type differs",
    )
    _require(_digest(response["response_stream_sha256"]), "private stream digest differs")
    _require(
        response["response_id"] is None
        or (type(response["response_id"]) is str and bool(response["response_id"])),
        "private response identifier type differs",
    )
    _require(
        response["response_model"] is None
        or response["response_model"] == resident.ENDPOINT.served_model,
        "private response model type differs",
    )
    _require(
        response["finish_reason"] is None
        or (
            type(response["finish_reason"]) is str
            and response["finish_reason"]
            in {"stop", "length", "tool_calls", "content_filter"}
        ),
        "private finish reason type differs",
    )
    _require(
        response["usage"] is None or type(response["usage"]) is dict,
        "private usage type differs",
    )
    _text_sha(response["content"], "private content")
    _text_sha(response["reasoning_content"], "private reasoning content")
    _json_sha(response["tool_calls"], "private tool calls")
    return response


def _accumulator_snapshot(accumulator: transport.StreamAccumulator) -> dict[str, Any]:
    """Return the channels transport had accepted before a partial failure."""

    return {
        "content": "".join(accumulator.content),
        "reasoning_content": "".join(accumulator.reasoning),
        "tool_calls": [
            copy.deepcopy(accumulator.tools[key])
            for key in sorted(accumulator.tools)
        ],
        "response_id": accumulator.response_id,
        "response_model": (
            accumulator.expected_model if accumulator.has_model else None
        ),
        "finish_reason": accumulator.finish_reason,
        "usage": copy.deepcopy(accumulator.usage),
        "stream_events": accumulator.events,
    }


def _partial_response_matches_raw(
    raw_stream: bytes, response: dict[str, Any]
) -> None:
    """Authenticate a failed call's accumulator snapshot from retained SSE.

    A timeout or byte-ceiling failure can leave a final non-newline fragment
    buffered and unparsed.  EOF can instead cause that same final fragment to
    be parsed before the terminal completeness check fails.  Replay admits
    either transport-reachable state, but never a channel value that cannot be
    derived from the retained bytes.
    """

    _require(type(raw_stream) is bytes, "partial raw response is not bytes")
    expected = {
        key: response[key]
        for key in (
            "content",
            "reasoning_content",
            "tool_calls",
            "response_id",
            "response_model",
            "finish_reason",
            "usage",
            "stream_events",
        )
    }
    pieces = raw_stream.split(b"\n")
    complete_lines = pieces[:-1]
    tail = pieces[-1]
    include_tail_values = (False, True) if tail else (False,)
    snapshots = []
    for include_tail in include_tail_values:
        accumulator = transport.StreamAccumulator(resident.ENDPOINT.served_model)
        lines = [*complete_lines]
        if include_tail:
            lines.append(tail)
        for line in lines:
            try:
                payload = transport._sse_data(line.rstrip(b"\r"))
                if payload is not None:
                    accumulator.accept(payload)
            except transport.TransportError:
                # The live transport attaches the accumulator after the
                # failing parse, including any earlier mutations in that event.
                break
        snapshots.append(_accumulator_snapshot(accumulator))
    _require(
        any(snapshot == expected for snapshot in snapshots),
        "partial response channels differ from retained raw SSE",
    )


def _response_record(
    response: dict[str, Any] | None, raw_stream: bytes | None
) -> dict[str, Any]:
    if response is None:
        content = reasoning = None
        tool_calls: list[dict[str, Any]] = []
        response_id = response_model = finish_reason = usage = stream_events = None
        content_sha = reasoning_sha = tools_sha = None
    else:
        content = response["content"]
        reasoning = response["reasoning_content"]
        tool_calls = copy.deepcopy(response["tool_calls"])
        response_id = response["response_id"]
        response_model = response["response_model"]
        finish_reason = response["finish_reason"]
        usage = copy.deepcopy(response["usage"])
        stream_events = response["stream_events"]
        content_sha = _text_sha(content, "response content")
        reasoning_sha = _text_sha(reasoning, "response reasoning content")
        tools_sha = _json_sha(tool_calls, "response tool calls")
    return {
        "content": content,
        "reasoning_content": reasoning,
        "tool_calls": tool_calls,
        "content_sha256": content_sha,
        "reasoning_content_sha256": reasoning_sha,
        "tool_calls_sha256": tools_sha,
        "response_id": response_id,
        "response_model": response_model,
        "finish_reason": finish_reason,
        "usage": usage,
        "stream_events": stream_events,
        "response_bytes": len(raw_stream) if raw_stream is not None else None,
        "response_stream_sha256": (
            hashlib.sha256(raw_stream).hexdigest() if raw_stream is not None else None
        ),
    }


def _returned_matches_transport(
    returned: Any,
    *,
    body: dict[str, Any],
    request_sha: str,
    private_response: dict[str, Any],
    response: dict[str, Any],
) -> None:
    _require(type(returned) is dict, "transport result is not an object")
    try:
        harness._private_response(returned.get("private_evidence"), returned=returned)
    except (harness.HarnessError, KeyError, TypeError, ValueError) as exc:
        raise WireError("public/private transport response differs") from exc
    _require(returned.get("request_sha256") == request_sha, "transport request digest differs")
    _require(returned.get("resolved_request") == body, "transport rendered request differs")
    _require(
        returned.get("endpoint") == resident.ENDPOINT.__dict__,
        "transport endpoint receipt differs",
    )
    _require(
        type(returned.get("response_bytes")) is int
        and returned["response_bytes"] == response["response_bytes"],
        "transport response byte receipt differs",
    )
    _require(
        type(returned.get("stream_events")) is int
        and returned["stream_events"] == private_response["stream_events"],
        "transport stream event receipt differs",
    )
    _require(
        type(returned.get("retries")) is int and returned["retries"] == 0,
        "transport retry receipt differs",
    )
    _require(
        returned.get("response_stream_sha256") == response["response_stream_sha256"],
        "transport response stream digest differs",
    )
    _require(
        type(returned.get("content")) is str
        and type(returned.get("reasoning_content")) is str
        and type(returned.get("tool_calls")) is list
        and type(returned.get("response_id")) is str
        and bool(returned["response_id"])
        and returned.get("response_model") == resident.ENDPOINT.served_model
        and type(returned.get("finish_reason")) is str
        and type(returned.get("usage")) is dict,
        "returned response channels or terminal receipt are malformed",
    )
    if "latency_s" in returned:
        _require(
            type(returned["latency_s"]) in {int, float}
            and math.isfinite(float(returned["latency_s"]))
            and float(returned["latency_s"]) >= 0,
            "transport latency receipt differs",
        )
    if "ttft_s" in returned:
        _require(
            returned["ttft_s"] is None
            or (
                type(returned["ttft_s"]) in {int, float}
                and math.isfinite(float(returned["ttft_s"]))
                and float(returned["ttft_s"]) >= 0
            ),
            "transport first-token receipt differs",
        )
    _require(
        private_response["response_model"] == resident.ENDPOINT.served_model,
        "private response model differs",
    )


@dataclass(frozen=True)
class Call:
    status: str
    dispatch_state: str
    content: str | None
    reasoning_content: str | None
    tool_calls: tuple[dict[str, Any], ...]
    receipt: dict[str, Any]
    descriptor: dict[str, Any]


def invoke(
    *,
    output: Path,
    ordinal: int,
    study_id: str,
    slot_id: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    seed: int,
    cancel_event: Any,
    invoke_fn: Callable[..., dict[str, Any]],
    monotonic: Callable[[], float],
) -> Call:
    """Invoke one resident request and persist a strict v2 evidence record."""

    _require(isinstance(output, Path) and output.is_absolute(), "wire output must be an absolute Path")
    _require(type(ordinal) is int and 0 <= ordinal <= _MAX_ORDINAL, "call ordinal is invalid")
    _require(
        type(study_id) is str
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}", study_id) is not None,
        "study ID is invalid",
    )
    _require(
        type(slot_id) is str
        and 0 < len(slot_id) <= 255
        and "\x00" not in slot_id,
        "slot ID is invalid",
    )
    _require(type(messages) is list and bool(messages), "messages must be a nonempty list")
    _require(type(tools) is list, "tools must be a list")
    _require(type(seed) is int, "seed must be an exact integer")
    _require(callable(invoke_fn) and callable(monotonic), "wire dependencies are not callable")

    policy_sha = _json_sha(POLICY, "resolved policy")
    messages_sha = _json_sha(messages, "messages")
    tools_sha = _json_sha(tools, "tools")
    body = transport.request_body(
        resident.ENDPOINT,
        copy.deepcopy(messages),
        copy.deepcopy(POLICY),
        MAX_TOKENS,
        seed,
        copy.deepcopy(tools) or None,
    )
    request_sha = sha(transport.canonical(body))
    call_id = f"{study_id}/{slot_id}"
    base = {
        "call_index": ordinal,
        "call_id": call_id,
        "role": ROLE,
        "endpoint_name": resident.ENDPOINT.name,
        "served_model": resident.ENDPOINT.served_model,
        "artifact_sha256": resident.ENDPOINT.artifact_sha256,
        "policy_id": POLICY_ID,
        "resolved_policy_sha256": policy_sha,
        "seed": seed,
        "max_tokens": MAX_TOKENS,
        "timeout_s": CALL_TIMEOUT_S,
        "messages_sha256": messages_sha,
        "tools_sha256": tools_sha,
        "request_sha256": request_sha,
    }

    started = _time(monotonic(), "wire start time")
    private_response: dict[str, Any] | None = None
    raw_stream: bytes | None = None
    status: str
    dispatch_state: str
    failure_code: str | None
    error: str | None
    returned: Any = None

    try:
        returned = invoke_fn(
            resident.ENDPOINT,
            copy.deepcopy(messages),
            policy=copy.deepcopy(POLICY),
            max_tokens=MAX_TOKENS,
            timeout_s=CALL_TIMEOUT_S,
            seed=seed,
            tools=copy.deepcopy(tools) or None,
            cancel_event=cancel_event,
        )
    except Exception as exc:  # noqa: BLE001 - every issued slot needs a disposition
        attached = getattr(exc, "private_evidence", None)
        raw_stream = _raw_candidate(attached)
        if attached is not None:
            try:
                private_response = _validated_private_response(attached)
                _require(raw_stream is not None, "transport evidence lacks raw bytes")
                _partial_response_matches_raw(raw_stream, private_response)
            except WireError:
                private_response = None
                status = "integrity_error"
                failure_code = "transport_evidence_integrity_error"
                error = _error_text(
                    exc, diagnostic="transport evidence integrity failure"
                )
            else:
                status = (
                    "cancelled"
                    if isinstance(exc, transport.TransportCancelled)
                    else "timeout"
                    if isinstance(exc, TimeoutError)
                    else "transport_error"
                )
                failure_code = (
                    "transport_cancelled"
                    if status == "cancelled"
                    else "transport_timeout"
                    if status == "timeout"
                    else "transport_error"
                    if isinstance(exc, transport.TransportError)
                    else "unexpected_transport_error"
                )
                error = _error_text(
                    exc,
                    diagnostic=(
                        "transport cancelled"
                        if status == "cancelled"
                        else "transport timed out"
                        if status == "timeout"
                        else "transport failed"
                    ),
                )
        elif isinstance(exc, (transport.TransportCancelled, TimeoutError, transport.TransportError)):
            status = "integrity_error"
            failure_code = "transport_evidence_integrity_error"
            error = _error_text(
                exc, diagnostic="transport exception lacked private evidence"
            )
        else:
            status = "transport_error"
            failure_code = "unexpected_transport_error"
            error = _error_text(exc, diagnostic="unexpected transport failure")
        if raw_stream:
            dispatch_state = "confirmed_dispatched"
        elif raw_stream is not None or status == "integrity_error" or isinstance(
            exc, (transport.TransportCancelled, TimeoutError, transport.TransportError)
        ):
            dispatch_state = "wire_unknown"
        else:
            dispatch_state = "prewire_failure"
    else:
        attached = returned.get("private_evidence") if type(returned) is dict else None
        raw_stream = _raw_candidate(attached)
        try:
            private_response = _validated_private_response(attached)
            response_for_replay = _response_record(private_response, raw_stream)
            _require(raw_stream is not None, "returned transport lacks a raw stream")
            try:
                private_evidence._response_matches_raw(
                    raw_stream,
                    response_for_replay,
                    {"served_model": resident.ENDPOINT.served_model},
                )
            except private_evidence.PrivateEvidenceError as exc:
                raise WireError("returned raw SSE differs from its response receipt") from exc
            _returned_matches_transport(
                returned,
                body=body,
                request_sha=request_sha,
                private_response=private_response,
                response=response_for_replay,
            )
        except (WireError, KeyError, TypeError, ValueError) as exc:
            # A structurally valid private response is retained only after the
            # raw SSE itself has been replayed.  Otherwise raw bytes are the
            # sole trustworthy diagnostic evidence.
            if not isinstance(exc, WireError) or "public/private" not in str(exc):
                try:
                    if raw_stream is None or private_response is None:
                        private_response = None
                    else:
                        probe = _response_record(private_response, raw_stream)
                        private_evidence._response_matches_raw(
                            raw_stream,
                            probe,
                            {"served_model": resident.ENDPOINT.served_model},
                        )
                except (WireError, private_evidence.PrivateEvidenceError):
                    private_response = None
            status = "integrity_error"
            failure_code = "transport_evidence_integrity_error"
            error = _error_text(
                exc, diagnostic="returned transport evidence integrity failure"
            )
            dispatch_state = "confirmed_dispatched" if raw_stream else "wire_unknown"
        else:
            status = "returned"
            dispatch_state = "confirmed_dispatched"
            failure_code = error = None

    try:
        finished = _time(monotonic(), "wire finish time")
        wall_s = max(0.0, finished - started)
    except WireError as exc:
        wall_s = 0.0
        status = "integrity_error"
        failure_code = "transport_evidence_integrity_error"
        error = _error_text(exc, diagnostic="wire clock integrity failure")
        if raw_stream:
            dispatch_state = "confirmed_dispatched"
        elif dispatch_state != "prewire_failure":
            dispatch_state = "wire_unknown"

    response = _response_record(private_response, raw_stream)
    terminal = status == "returned"
    receipt = {
        **base,
        "status": status,
        "dispatch_state": dispatch_state,
        "wall_s": wall_s,
        "response_stream_sha256": response["response_stream_sha256"] if terminal else None,
        "response_id": response["response_id"] if terminal else None,
        "response_model": response["response_model"] if terminal else None,
        "finish_reason": response["finish_reason"] if terminal else None,
        "usage": copy.deepcopy(response["usage"]) if terminal else None,
        "content_sha256": response["content_sha256"],
        "reasoning_content_sha256": response["reasoning_content_sha256"],
        "tool_calls_sha256": response["tool_calls_sha256"],
        "failure_code": failure_code,
        "error": error,
    }
    evidence = {
        "schema_version": PRIVATE_SCHEMA,
        "call_id": call_id,
        "call_index": ordinal,
        "role": ROLE,
        "status": status,
        "dispatch_state": dispatch_state,
        "request": {
            "endpoint_name": resident.ENDPOINT.name,
            "served_model": resident.ENDPOINT.served_model,
            "artifact_sha256": resident.ENDPOINT.artifact_sha256,
            "policy_id": POLICY_ID,
            "resolved_policy": copy.deepcopy(POLICY),
            "resolved_policy_sha256": policy_sha,
            "seed": seed,
            "max_tokens": MAX_TOKENS,
            "timeout_s": CALL_TIMEOUT_S,
            "messages": copy.deepcopy(messages),
            "messages_sha256": messages_sha,
            "tools": copy.deepcopy(tools),
            "tools_sha256": tools_sha,
            "request_sha256": request_sha,
        },
        "response": response,
        "failure_code": failure_code,
        "error": error,
        "_raw_response_stream": raw_stream,
    }
    descriptor = harness._persist_private_call(output, ordinal=ordinal, evidence=evidence)
    return Call(
        status=status,
        dispatch_state=dispatch_state,
        content=response["content"],
        reasoning_content=response["reasoning_content"],
        tool_calls=tuple(copy.deepcopy(response["tool_calls"])),
        receipt=receipt,
        descriptor=descriptor,
    )


def _strict_descriptor(descriptor: Any) -> dict[str, Any]:
    _require(type(descriptor) is dict and set(descriptor) == _DESCRIPTOR_KEYS,
             "private descriptor shape differs")
    _require(type(descriptor.get("call_id")) is str and bool(descriptor["call_id"]),
             "private descriptor call ID differs")
    _require(type(descriptor.get("status")) is str and descriptor["status"] in _STATUSES,
             "private descriptor status differs")
    path = descriptor.get("metadata_path")
    _require(type(path) is str and _METADATA_PATH.fullmatch(path) is not None,
             "private metadata path differs")
    _require(_digest(descriptor.get("metadata_sha256")), "private metadata digest differs")
    _require(type(descriptor.get("metadata_bytes")) is int
             and 0 < descriptor["metadata_bytes"] <= harness.MAX_PRIVATE_METADATA_BYTES,
             "private metadata byte count differs")
    stream = descriptor.get("raw_stream")
    if stream is not None:
        _require(type(stream) is dict and set(stream) == {"path", "sha256", "bytes"},
                 "private stream descriptor shape differs")
        _require(type(stream.get("path")) is str
                 and _STREAM_PATH.fullmatch(stream["path"]) is not None,
                 "private stream path differs")
        _require(_digest(stream.get("sha256")), "private stream digest differs")
        _require(type(stream.get("bytes")) is int
                 and 0 <= stream["bytes"] <= transport.MAX_RESPONSE_BYTES,
                 "private stream byte count differs")
        _require(Path(stream["path"]).stem == Path(path).stem,
                 "private metadata and stream identities differ")
    return descriptor


def metadata(
    output: Path, descriptor: dict[str, Any]
) -> tuple[dict[str, Any], bytes | None]:
    """Read one nofollow private v2 record and its exact raw SSE bytes."""

    _require(isinstance(output, Path) and output.is_absolute(), "wire output must be an absolute Path")
    descriptor = _strict_descriptor(descriptor)
    try:
        raw, resolved = harness._read_regular_file(
            output / descriptor["metadata_path"],
            label="private v2 calibration call",
            max_bytes=harness.MAX_PRIVATE_METADATA_BYTES,
        )
    except harness.HarnessError as exc:
        raise WireError(f"private v2 metadata is unavailable: {exc}") from exc
    _require(
        resolved == (output / descriptor["metadata_path"]).absolute()
        and len(raw) == descriptor["metadata_bytes"]
        and sha(raw) == descriptor["metadata_sha256"],
        "private metadata bytes differ",
    )
    try:
        value = harness._strict_object(raw, "private v2 calibration call")
    except harness.HarnessError as exc:
        raise WireError(f"private v2 metadata JSON differs: {exc}") from exc
    _require(
        value.get("schema_version") == PRIVATE_SCHEMA
        and set(value) == _METADATA_KEYS,
        "private v2 metadata schema differs",
    )
    _require(type(value.get("request")) is dict and set(value["request"]) == _REQUEST_KEYS,
             "private v2 request schema differs")
    _require(type(value.get("response")) is dict and set(value["response"]) == _RESPONSE_KEYS,
             "private v2 response schema differs")

    stream_descriptor = descriptor["raw_stream"]
    raw_stream = None
    if stream_descriptor is not None:
        try:
            raw_stream = private_evidence._recorded(
                output / stream_descriptor["path"],
                label="private v2 calibration SSE",
                ceiling=transport.MAX_RESPONSE_BYTES,
                digest=stream_descriptor["sha256"],
                count=stream_descriptor["bytes"],
                allow_empty_transport=value.get("status") != "returned",
            )
        except private_evidence.PrivateEvidenceError as exc:
            raise WireError(f"private v2 SSE bytes differ: {exc}") from exc
    _require(
        value["response"].get("raw_stream_artifact") == stream_descriptor,
        "private response/stream binding differs",
    )
    return value, raw_stream


def _validate_response_shape(response: dict[str, Any], raw_stream: bytes | None) -> None:
    content = response["content"]
    reasoning = response["reasoning_content"]
    calls = response["tool_calls"]
    _require(content is None or type(content) is str, "private content type differs")
    _require(reasoning is None or type(reasoning) is str, "private reasoning type differs")
    _require(type(calls) is list, "private tool calls type differs")
    expected_content = _text_sha(content, "private content") if content is not None else None
    expected_reasoning = (
        _text_sha(reasoning, "private reasoning content") if reasoning is not None else None
    )
    events = response["stream_events"]
    evidence_available = type(events) is int and events >= 0
    _require(events is None or evidence_available, "private stream event count differs")
    expected_tools = _json_sha(calls, "private tool calls") if evidence_available else None
    _require(
        response["content_sha256"] == expected_content
        and response["reasoning_content_sha256"] == expected_reasoning
        and response["tool_calls_sha256"] == expected_tools,
        "private response channel digest differs",
    )
    if not evidence_available:
        _require(
            content is None
            and reasoning is None
            and calls == []
            and response["content_sha256"] is None
            and response["reasoning_content_sha256"] is None
            and response["tool_calls_sha256"] is None
            and response["response_id"] is None
            and response["response_model"] is None
            and response["finish_reason"] is None
            and response["usage"] is None,
            "raw-only response contains unauthenticated channels",
        )
    _require(
        response["response_id"] is None
        or (type(response["response_id"]) is str and bool(response["response_id"])),
        "private response ID type differs",
    )
    _require(
        response["response_model"] is None
        or response["response_model"] == resident.ENDPOINT.served_model,
             "private response model type differs")
    _require(
        response["finish_reason"] is None
        or (
            type(response["finish_reason"]) is str
            and response["finish_reason"]
            in {"stop", "length", "tool_calls", "content_filter"}
        ),
             "private finish reason type differs")
    _require(response["usage"] is None or type(response["usage"]) is dict,
             "private usage type differs")
    if raw_stream is None:
        _require(
            response["response_bytes"] is None
            and response["response_stream_sha256"] is None
            and events is None,
            "missing raw stream has a private stream receipt",
        )
    else:
        _require(
            type(response["response_bytes"]) is int
            and response["response_bytes"] == len(raw_stream)
            and response["response_stream_sha256"] == sha(raw_stream),
            "private raw stream receipt differs",
        )


def replay_call(
    *,
    output: Path,
    descriptor: dict[str, Any],
    call: dict[str, Any],
    slot: dict[str, Any],
    plan_value: dict[str, Any],
    cell: dict[str, Any],
    slot_id: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> tuple[dict[str, Any], bool]:
    """Replay a call without contacting a model or executing a local tool."""

    value, raw_stream = metadata(output, descriptor)
    _require(type(call) is dict and set(call) == _CALL_KEYS, "public call receipt shape differs")
    _require(type(slot) is dict and type(plan_value) is dict and type(cell) is dict,
             "replay bindings are not objects")
    _require(type(slot_id) is str and bool(slot_id), "replay slot ID differs")
    _require(type(messages) is list and bool(messages) and type(tools) is list,
             "replay request containers differ")
    _require(type(call["call_index"]) is int and 0 <= call["call_index"] <= _MAX_ORDINAL,
             "public call index differs")
    _require(type(call["wall_s"]) in {int, float}
             and math.isfinite(float(call["wall_s"]))
             and 0 <= float(call["wall_s"]),
             "public call latency differs")
    _require(type(call["status"]) is str and call["status"] in _STATUSES,
             "public call status differs")
    _require(type(call["dispatch_state"]) is str
             and call["dispatch_state"] in _DISPATCH_STATES,
             "public dispatch state differs")
    for key in (
        "resolved_policy_sha256",
        "messages_sha256",
        "tools_sha256",
        "request_sha256",
    ):
        _require(_digest(call[key]), f"public {key} differs")
    for key in ("content_sha256", "reasoning_content_sha256", "tool_calls_sha256"):
        _require(call[key] is None or _digest(call[key]), f"public {key} differs")
    for key in (
        "call_id",
        "role",
        "endpoint_name",
        "served_model",
        "artifact_sha256",
        "policy_id",
    ):
        _require(type(call[key]) is str and bool(call[key]), f"public {key} type differs")
    _require(type(call["seed"]) is int, "public seed type differs")
    _require(type(call["max_tokens"]) is int, "public max token type differs")
    _require(
        type(call["timeout_s"]) in {int, float}
        and math.isfinite(float(call["timeout_s"])),
        "public timeout type differs",
    )
    _require(
        call["response_stream_sha256"] is None
        or _digest(call["response_stream_sha256"]),
        "public response stream digest differs",
    )
    _require(
        call["response_id"] is None
        or (type(call["response_id"]) is str and bool(call["response_id"])),
        "public response ID type differs",
    )
    _require(
        call["response_model"] is None or type(call["response_model"]) is str,
        "public response model type differs",
    )
    _require(
        call["finish_reason"] is None or type(call["finish_reason"]) is str,
        "public finish reason type differs",
    )
    _require(call["usage"] is None or type(call["usage"]) is dict,
             "public usage type differs")
    _require(call["failure_code"] is None or type(call["failure_code"]) is str,
             "public failure code type differs")
    _require(call["error"] is None or type(call["error"]) is str,
             "public error type differs")

    request = value["request"]
    response = value["response"]
    _validate_response_shape(response, raw_stream)
    if raw_stream is not None and response["stream_events"] is not None:
        _partial_response_matches_raw(raw_stream, response)
    _require(
        type(request["endpoint_name"]) is str
        and type(request["served_model"]) is str
        and type(request["artifact_sha256"]) is str
        and type(request["policy_id"]) is str
        and type(request["resolved_policy"]) is dict
        and type(request["seed"]) is int
        and type(request["max_tokens"]) is int
        and type(request["timeout_s"]) in {int, float}
        and math.isfinite(float(request["timeout_s"]))
        and type(request["messages"]) is list
        and type(request["tools"]) is list
        and all(
            _digest(request[key])
            for key in (
                "resolved_policy_sha256",
                "messages_sha256",
                "tools_sha256",
                "request_sha256",
            )
        )
        and type(cell.get("seed")) is int
        and request["messages"] == messages
        and request["tools"] == tools
        and request["resolved_policy"] == POLICY
        and request["seed"] == cell["seed"]
        and request["max_tokens"] == MAX_TOKENS
        and request["timeout_s"] == CALL_TIMEOUT_S
        and request["endpoint_name"] == resident.ENDPOINT.name
        and request["served_model"] == resident.ENDPOINT.served_model
        and request["artifact_sha256"] == resident.ENDPOINT.artifact_sha256
        and request["policy_id"] == POLICY_ID,
        "private frozen request differs",
    )
    policy_sha = _json_sha(POLICY, "resolved policy")
    messages_sha = _json_sha(messages, "messages")
    tools_sha = _json_sha(tools, "tools")
    body = transport.request_body(
        resident.ENDPOINT,
        copy.deepcopy(messages),
        copy.deepcopy(POLICY),
        MAX_TOKENS,
        cell["seed"],
        copy.deepcopy(tools) or None,
    )
    request_sha = sha(transport.canonical(body))
    _require(
        request["resolved_policy_sha256"] == policy_sha
        and request["messages_sha256"] == messages_sha
        and request["tools_sha256"] == tools_sha
        and request["request_sha256"] == request_sha
        and call["resolved_policy_sha256"] == policy_sha
        and call["messages_sha256"] == messages_sha
        and call["tools_sha256"] == tools_sha
        and call["request_sha256"] == request_sha,
        "private/public request digest differs",
    )
    _require(
        call["endpoint_name"] == resident.ENDPOINT.name
        and call["served_model"] == resident.ENDPOINT.served_model
        and call["artifact_sha256"] == resident.ENDPOINT.artifact_sha256
        and call["policy_id"] == POLICY_ID
        and call["seed"] == cell["seed"]
        and call["max_tokens"] == MAX_TOKENS
        and call["timeout_s"] == CALL_TIMEOUT_S
        and call["role"] == ROLE,
        "public route, identity, policy, or limits differ",
    )
    _require(
        type(plan_value.get("study_id")) is str and bool(plan_value["study_id"]),
        "replay study ID differs",
    )
    expected_call_id = f"{plan_value['study_id']}/{slot_id}"
    _require(
        slot.get("call") == call
        and slot.get("private_descriptor") == descriptor
        and slot.get("status") == call["status"]
        and slot.get("dispatch_state") == call["dispatch_state"]
        and slot.get("failure_code") == call["failure_code"]
        and descriptor["call_id"] == call["call_id"] == expected_call_id
        and descriptor["status"] == call["status"],
        "slot/public/private call binding differs",
    )
    _require(
        value["call_id"] == call["call_id"]
        and value["call_index"] == call["call_index"]
        and value["role"] == call["role"]
        and value["status"] == call["status"]
        and value["dispatch_state"] == call["dispatch_state"]
        and value["failure_code"] == call["failure_code"]
        and value["error"] == call["error"],
        "private/public response identity differs",
    )
    _require(
        call["content_sha256"] == response["content_sha256"]
        and call["reasoning_content_sha256"] == response["reasoning_content_sha256"]
        and call["tool_calls_sha256"] == response["tool_calls_sha256"],
        "public/private response channel digest differs",
    )

    returned = call["status"] == "returned"
    if returned:
        _require(
            raw_stream is not None
            and len(raw_stream) > 0
            and call["dispatch_state"] == "confirmed_dispatched"
            and type(response["content"]) is str
            and type(response["reasoning_content"]) is str
            and type(response["stream_events"]) is int
            and response["stream_events"] >= 1
            and call["response_stream_sha256"] == response["response_stream_sha256"]
            and call["response_id"] == response["response_id"]
            and call["response_model"] == response["response_model"]
            and call["finish_reason"] == response["finish_reason"]
            and call["usage"] == response["usage"]
            and call["failure_code"] is None
            and call["error"] is None,
            "returned response receipt differs",
        )
        try:
            private_evidence._response_matches_raw(raw_stream, response, call)
        except private_evidence.PrivateEvidenceError as exc:
            raise WireError(f"returned raw SSE replay failed: {exc}") from exc
    else:
        _require(
            all(
                call[key] is None
                for key in (
                    "response_stream_sha256",
                    "response_id",
                    "response_model",
                    "finish_reason",
                    "usage",
                )
            )
            and type(call["failure_code"]) is str
            and bool(call["failure_code"])
            and type(call["error"]) is str
            and bool(call["error"]),
            "failed response exported a terminal receipt",
        )
        expected_failure = {
            "timeout": "transport_timeout",
            "cancelled": "transport_cancelled",
            "integrity_error": "transport_evidence_integrity_error",
        }.get(call["status"])
        if expected_failure is not None:
            _require(call["failure_code"] == expected_failure, "failure code differs from status")
        elif call["status"] == "transport_error":
            _require(call["failure_code"] in {"transport_error", "unexpected_transport_error"},
                     "transport failure code differs")
        authenticated_partial_required = call["status"] in {"timeout", "cancelled"} or (
            call["status"] == "transport_error"
            and call["failure_code"] == "transport_error"
        )
        if authenticated_partial_required:
            _require(
                raw_stream is not None and type(response["stream_events"]) is int,
                "transport failure lacks authenticated partial evidence",
            )
        if call["dispatch_state"] == "confirmed_dispatched":
            _require(raw_stream is not None and len(raw_stream) > 0,
                     "confirmed failed call lacks raw bytes")
        elif call["dispatch_state"] == "wire_unknown":
            _require(raw_stream in {None, b""}, "wire-unknown call has nonempty raw bytes")
        else:
            _require(raw_stream is None, "pre-wire failure has raw bytes")
    return value, returned
