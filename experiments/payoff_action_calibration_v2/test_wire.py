from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from bench.flash_next_ab import transport
from experiments.payoff_action_calibration_v2 import design, wire
from experiments.payoff_tool_arithmetic import flash_resident as resident

MESSAGES = [
    {"role": "system", "content": "Use the supplied exact arithmetic tool."},
    {"role": "user", "content": "Compute the frozen payoff."},
]
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "public_goods_joint_action_payoff",
            "description": "Return exact payoffs.",
            "parameters": {
                "type": "object",
                "properties": {"E": {"type": "integer"}},
                "required": ["E"],
                "additionalProperties": False,
            },
        },
    }
]
SEED = 2_026_092_200
STUDY = "native-tool-v2-wire-test"
SLOT = "cell-01/calculator/tool"


def _clock(start: float = 10.0, finish: float = 10.25):
    values = iter((start, finish))
    return lambda: next(values)


def _accept(raw: bytes, endpoint=resident.ENDPOINT):
    accumulator = transport.StreamAccumulator(endpoint.served_model)
    for line in raw.splitlines():
        payload = transport._sse_data(line.rstrip(b"\r"))
        if payload is not None:
            accumulator.accept(payload)
    return accumulator


def _complete_raw(endpoint=resident.ENDPOINT) -> bytes:
    call = {
        "index": 0,
        "id": "call-native-v2",
        "type": "function",
        "function": {
            "name": TOOLS[0]["function"]["name"],
            "arguments": '{"E":22}',
        },
    }
    response_id = "response-native-v2"
    chunk = {
        "id": response_id,
        "model": endpoint.served_model,
        "choices": [
            {
                "index": 0,
                "delta": {
                    "reasoning_content": "private-trace",
                    "content": "visible pre-tool text",
                    "tool_calls": [call],
                },
                "finish_reason": "tool_calls",
            }
        ],
    }
    usage = {
        "id": response_id,
        "model": endpoint.served_model,
        "choices": [],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
    }
    return (
        b"data: "
        + json.dumps(chunk, separators=(",", ":")).encode()
        + b"\n\n"
        + b"data: "
        + json.dumps(usage, separators=(",", ":")).encode()
        + b"\n\n"
        + b"data: [DONE]\n\n"
    )


def _returned(
    endpoint,
    messages,
    *,
    policy,
    max_tokens,
    timeout_s,
    seed,
    tools,
    cancel_event,
):
    assert endpoint == resident.ENDPOINT
    assert messages == MESSAGES
    assert policy == design.POLICY
    assert max_tokens == design.MAX_TOKENS
    assert timeout_s == design.CALL_TIMEOUT_S
    assert seed == SEED
    assert tools == TOOLS
    raw = _complete_raw(endpoint)
    accumulator = _accept(raw, endpoint)
    result = accumulator.result()
    body = transport.request_body(endpoint, messages, policy, max_tokens, seed, tools)
    result.update(
        {
            "request_sha256": hashlib.sha256(transport.canonical(body)).hexdigest(),
            "response_stream_sha256": hashlib.sha256(raw).hexdigest(),
            "endpoint": endpoint.__dict__,
            "resolved_request": body,
            "response_bytes": len(raw),
            "retries": 0,
            "private_evidence": transport._private_response_evidence(
                accumulator, raw, response_bytes=len(raw)
            ),
        }
    )
    return result


def _invoke(tmp_path: Path, invoke_fn=_returned):
    output = tmp_path / "run"
    output.mkdir(parents=True)
    call = wire.invoke(
        output=output,
        ordinal=0,
        study_id=STUDY,
        slot_id=SLOT,
        messages=copy.deepcopy(MESSAGES),
        tools=copy.deepcopy(TOOLS),
        seed=SEED,
        cancel_event=None,
        invoke_fn=invoke_fn,
        monotonic=_clock(),
    )
    return output, call


def _slot(call: wire.Call) -> dict:
    return {
        "slot_id": SLOT,
        "disposition": "returned" if call.status == "returned" else "failed",
        "status": call.status,
        "failure_code": call.receipt["failure_code"],
        "dispatch_state": call.dispatch_state,
        "call": call.receipt,
        "private_descriptor": call.descriptor,
    }


def _replay(output: Path, call: wire.Call):
    return wire.replay_call(
        output=output,
        descriptor=call.descriptor,
        call=call.receipt,
        slot=_slot(call),
        plan_value={"study_id": STUDY},
        cell={"seed": SEED},
        slot_id=SLOT,
        messages=copy.deepcopy(MESSAGES),
        tools=copy.deepcopy(TOOLS),
    )


def test_returned_call_requires_raw_sse_replay_and_binds_separate_channels(tmp_path):
    output, call = _invoke(tmp_path)

    assert call.status == "returned"
    assert call.dispatch_state == "confirmed_dispatched"
    assert call.content == "visible pre-tool text"
    assert call.reasoning_content == "private-trace"
    assert len(call.tool_calls) == 1
    assert call.receipt["role"] == wire.ROLE
    assert call.receipt["content_sha256"] == hashlib.sha256(
        call.content.encode("utf-8")
    ).hexdigest()
    assert call.receipt["reasoning_content_sha256"] == hashlib.sha256(
        call.reasoning_content.encode("utf-8")
    ).hexdigest()
    assert call.receipt["request_sha256"] == hashlib.sha256(
        transport.canonical(
            transport.request_body(
                resident.ENDPOINT,
                MESSAGES,
                design.POLICY,
                design.MAX_TOKENS,
                SEED,
                TOOLS,
            )
        )
    ).hexdigest()

    metadata, returned = _replay(output, call)
    assert returned is True
    assert metadata["schema_version"] == design.PRIVATE_SCHEMA
    assert metadata["schema_version"].endswith("/v2")
    assert metadata["request"]["messages"] == MESSAGES
    assert metadata["request"]["tools"] == TOOLS
    assert metadata["response"]["content"] == call.content
    assert metadata["response"]["reasoning_content"] == call.reasoning_content
    assert metadata["response"]["tool_calls"] == list(call.tool_calls)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda result: result.update(request_sha256="0" * 64),
        lambda result: result.update(resolved_request={"forged": True}),
        lambda result: result.update(content="forged visible content"),
    ],
)
def test_contradictory_returned_receipt_is_integrity_error_not_returned(
    tmp_path, mutate
):
    def corrupt(*args, **kwargs):
        result = _returned(*args, **kwargs)
        mutate(result)
        return result

    output, call = _invoke(tmp_path, corrupt)
    assert call.status == "integrity_error"
    assert call.receipt["failure_code"] == "transport_evidence_integrity_error"
    assert call.receipt["finish_reason"] is None
    assert call.receipt["response_stream_sha256"] is None
    assert call.receipt["error"] == (
        "WireError: returned transport evidence integrity failure"
    )
    assert _replay(output, call)[1] is False


def test_bytes_after_done_are_retained_but_cannot_be_returned_or_exposed(tmp_path):
    def corrupt_raw(*args, **kwargs):
        result = _returned(*args, **kwargs)
        evidence = result["private_evidence"]
        raw = evidence["raw_response_stream"] + b'data: {"late":true}\n\n'
        evidence["raw_response_stream"] = raw
        evidence["response_bytes"] = len(raw)
        evidence["response_stream_sha256"] = hashlib.sha256(raw).hexdigest()
        result["response_bytes"] = len(raw)
        result["response_stream_sha256"] = hashlib.sha256(raw).hexdigest()
        return result

    output, call = _invoke(tmp_path, corrupt_raw)
    assert call.status == "integrity_error"
    assert call.dispatch_state == "confirmed_dispatched"
    assert call.content is None
    assert call.reasoning_content is None
    assert call.tool_calls == ()
    assert call.descriptor["raw_stream"]["bytes"] > len(_complete_raw())
    metadata, raw = wire.metadata(output, call.descriptor)
    assert raw.endswith(b'{"late":true}\n\n')
    assert metadata["response"]["content"] is None
    assert _replay(output, call)[1] is False


def test_missing_or_self_inconsistent_private_evidence_is_explicit_integrity_failure(
    tmp_path,
):
    def missing(*args, **kwargs):
        result = _returned(*args, **kwargs)
        result.pop("private_evidence")
        return result

    output, call = _invoke(tmp_path / "missing", missing)
    assert call.status == "integrity_error"
    assert call.dispatch_state == "wire_unknown"
    assert call.descriptor["raw_stream"] is None
    assert call.receipt["content_sha256"] is None
    assert _replay(output, call)[1] is False

    def bad_digest(*args, **kwargs):
        result = _returned(*args, **kwargs)
        result["private_evidence"]["response_stream_sha256"] = "0" * 64
        return result

    output, call = _invoke(tmp_path / "bad-digest", bad_digest)
    assert call.status == "integrity_error"
    assert call.dispatch_state == "confirmed_dispatched"
    assert call.content is None
    assert call.descriptor["raw_stream"]["sha256"] == hashlib.sha256(
        _complete_raw()
    ).hexdigest()
    assert _replay(output, call)[1] is False


def _partial_error(exception_type):
    def invoke(endpoint, *_args, **_kwargs):
        response_id = "partial-native-v2"
        chunk = {
            "id": response_id,
            "model": endpoint.served_model,
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "reasoning_content": "partial-reasoning",
                        "content": "partial-visible",
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "partial-call",
                                "type": "function",
                                "function": {
                                    "name": TOOLS[0]["function"]["name"],
                                    "arguments": '{"E":',
                                },
                            }
                        ],
                    },
                    "finish_reason": None,
                }
            ],
        }
        raw = b"data: " + json.dumps(chunk, separators=(",", ":")).encode() + b"\n\n"
        accumulator = _accept(raw, endpoint)
        exc = exception_type("synthetic partial failure")
        exc.private_evidence = transport._private_response_evidence(
            accumulator, raw, response_bytes=len(raw)
        )
        raise exc

    return invoke


@pytest.mark.parametrize(
    ("exception_type", "status", "failure_code"),
    [
        (TimeoutError, "timeout", "transport_timeout"),
        (transport.TransportCancelled, "cancelled", "transport_cancelled"),
        (transport.TransportError, "transport_error", "transport_error"),
    ],
)
def test_partial_transport_failures_retain_private_diagnostics_without_credit(
    tmp_path, exception_type, status, failure_code
):
    output, call = _invoke(tmp_path, _partial_error(exception_type))
    assert call.status == status
    assert call.dispatch_state == "confirmed_dispatched"
    assert call.content == "partial-visible"
    assert call.reasoning_content == "partial-reasoning"
    assert len(call.tool_calls) == 1
    assert call.receipt["failure_code"] == failure_code
    assert call.receipt["finish_reason"] is None
    assert call.receipt["response_id"] is None
    assert call.receipt["response_stream_sha256"] is None
    metadata, returned = _replay(output, call)
    assert returned is False
    assert metadata["response"]["content"] == "partial-visible"
    assert metadata["response"]["reasoning_content"] == "partial-reasoning"
    assert metadata["response"]["tool_calls"] == list(call.tool_calls)


@pytest.mark.parametrize(
    ("exception_type", "channel"),
    [
        (TimeoutError, "content"),
        (transport.TransportCancelled, "reasoning_content"),
        (transport.TransportError, "tool_calls"),
    ],
)
def test_contradictory_partial_channels_are_integrity_errors_and_raw_only(
    tmp_path, exception_type, channel
):
    partial = _partial_error(exception_type)

    def forged(*args, **kwargs):
        try:
            partial(*args, **kwargs)
        except exception_type as error:
            if channel == "tool_calls":
                error.private_evidence[channel] = []
            else:
                error.private_evidence[channel] = "forged diagnostic text"
            raise

    output, call = _invoke(tmp_path, forged)
    assert call.status == "integrity_error"
    assert call.receipt["failure_code"] == "transport_evidence_integrity_error"
    assert call.receipt["error"].endswith("transport evidence integrity failure")
    assert call.dispatch_state == "confirmed_dispatched"
    assert call.content is None
    assert call.reasoning_content is None
    assert call.tool_calls == ()
    assert call.descriptor["raw_stream"]["bytes"] > 0
    metadata, returned = _replay(output, call)
    assert returned is False
    assert metadata["response"]["stream_events"] is None


def test_replay_rederives_partial_channels_after_metadata_and_digest_rebinding(tmp_path):
    output, original = _invoke(tmp_path, _partial_error(TimeoutError))
    descriptor = copy.deepcopy(original.descriptor)
    metadata_path = output / descriptor["metadata_path"]
    value = json.loads(metadata_path.read_bytes())
    forged_content = "forged after capture"
    forged_sha = hashlib.sha256(forged_content.encode("utf-8")).hexdigest()
    value["response"]["content"] = forged_content
    value["response"]["content_sha256"] = forged_sha
    raw = design.canonical(value) + b"\n"
    metadata_path.write_bytes(raw)
    descriptor["metadata_sha256"] = hashlib.sha256(raw).hexdigest()
    descriptor["metadata_bytes"] = len(raw)
    receipt = copy.deepcopy(original.receipt)
    receipt["content_sha256"] = forged_sha
    forged = wire.Call(
        original.status,
        original.dispatch_state,
        forged_content,
        original.reasoning_content,
        original.tool_calls,
        receipt,
        descriptor,
    )

    with pytest.raises(wire.WireError, match="partial response channels differ"):
        _replay(output, forged)


def test_replay_rejects_channels_in_raw_only_integrity_metadata(tmp_path):
    def missing(*args, **kwargs):
        result = _returned(*args, **kwargs)
        result.pop("private_evidence")
        return result

    output, original = _invoke(tmp_path, missing)
    assert original.status == "integrity_error"
    descriptor = copy.deepcopy(original.descriptor)
    metadata_path = output / descriptor["metadata_path"]
    value = json.loads(metadata_path.read_bytes())
    content = "forged raw-only content"
    reasoning = "forged raw-only reasoning"
    value["response"]["content"] = content
    value["response"]["reasoning_content"] = reasoning
    value["response"]["tool_calls"] = [{"forged": True}]
    value["response"]["content_sha256"] = hashlib.sha256(content.encode()).hexdigest()
    value["response"]["reasoning_content_sha256"] = hashlib.sha256(
        reasoning.encode()
    ).hexdigest()
    # stream_events=None means there is no authenticated accumulator snapshot,
    # so an attacker cannot legitimize tool calls by adding a digest either.
    value["response"]["tool_calls_sha256"] = None
    raw = design.canonical(value) + b"\n"
    metadata_path.write_bytes(raw)
    descriptor["metadata_sha256"] = hashlib.sha256(raw).hexdigest()
    descriptor["metadata_bytes"] = len(raw)
    receipt = copy.deepcopy(original.receipt)
    receipt["content_sha256"] = value["response"]["content_sha256"]
    receipt["reasoning_content_sha256"] = value["response"][
        "reasoning_content_sha256"
    ]
    forged = wire.Call(
        original.status,
        original.dispatch_state,
        content,
        reasoning,
        ({"forged": True},),
        receipt,
        descriptor,
    )

    with pytest.raises(wire.WireError, match="raw-only response"):
        _replay(output, forged)


def test_replay_cannot_relabel_missing_evidence_as_timeout(tmp_path):
    def missing(*args, **kwargs):
        result = _returned(*args, **kwargs)
        result.pop("private_evidence")
        return result

    output, original = _invoke(tmp_path, missing)
    descriptor = copy.deepcopy(original.descriptor)
    metadata_path = output / descriptor["metadata_path"]
    value = json.loads(metadata_path.read_bytes())
    value["status"] = "timeout"
    value["failure_code"] = "transport_timeout"
    value["error"] = "TimeoutError: transport timed out"
    raw = design.canonical(value) + b"\n"
    metadata_path.write_bytes(raw)
    descriptor["status"] = "timeout"
    descriptor["metadata_sha256"] = hashlib.sha256(raw).hexdigest()
    descriptor["metadata_bytes"] = len(raw)
    receipt = copy.deepcopy(original.receipt)
    receipt["status"] = "timeout"
    receipt["failure_code"] = "transport_timeout"
    receipt["error"] = value["error"]
    forged = wire.Call(
        "timeout",
        original.dispatch_state,
        None,
        None,
        (),
        receipt,
        descriptor,
    )

    with pytest.raises(wire.WireError, match="lacks authenticated partial"):
        _replay(output, forged)


def test_empty_cancel_stream_is_wire_unknown_and_replayable(tmp_path):
    def cancel(endpoint, *_args, **_kwargs):
        accumulator = transport.StreamAccumulator(endpoint.served_model)
        exc = transport.TransportCancelled("cancelled before first response byte")
        exc.private_evidence = transport._private_response_evidence(
            accumulator, b"", response_bytes=0
        )
        raise exc

    output, call = _invoke(tmp_path, cancel)
    assert call.status == "cancelled"
    assert call.dispatch_state == "wire_unknown"
    assert call.descriptor["raw_stream"] == {
        "path": call.descriptor["raw_stream"]["path"],
        "sha256": hashlib.sha256(b"").hexdigest(),
        "bytes": 0,
    }
    assert call.content == ""
    assert call.reasoning_content == ""
    assert call.tool_calls == ()
    assert _replay(output, call)[1] is False


def test_transport_exception_without_private_evidence_is_integrity_failure(tmp_path):
    def absent(*_args, **_kwargs):
        raise TimeoutError("synthetic timeout without transport evidence")

    output, call = _invoke(tmp_path, absent)
    assert call.status == "integrity_error"
    assert call.dispatch_state == "wire_unknown"
    assert "lacked private evidence" in call.receipt["error"]
    assert _replay(output, call)[1] is False


def test_exception_text_never_enters_public_or_shared_error_receipts(tmp_path):
    sentinel = "PRIVATE_MODEL_TEXT_AND_TOKEN_7f54"

    def failed(endpoint, *_args, **_kwargs):
        accumulator = transport.StreamAccumulator(endpoint.served_model)
        error = transport.TransportError(sentinel)
        error.private_evidence = transport._private_response_evidence(
            accumulator, b"", response_bytes=0
        )
        raise error

    output, call = _invoke(tmp_path, failed)
    assert call.status == "transport_error"
    assert call.receipt["error"] == "TransportError: transport failed"
    assert sentinel not in json.dumps(call.receipt, sort_keys=True)
    metadata, _raw = wire.metadata(output, call.descriptor)
    assert sentinel not in json.dumps(metadata, sort_keys=True)


def test_replay_rejects_v1_schema_even_when_attacker_rebinds_metadata_digest(tmp_path):
    output, call = _invoke(tmp_path)
    descriptor = copy.deepcopy(call.descriptor)
    metadata_path = output / descriptor["metadata_path"]
    value = json.loads(metadata_path.read_bytes())
    value["schema_version"] = "flash-payoff-action-calibration-private-call/v1"
    raw = design.canonical(value) + b"\n"
    metadata_path.write_bytes(raw)
    descriptor["metadata_sha256"] = hashlib.sha256(raw).hexdigest()
    descriptor["metadata_bytes"] = len(raw)
    with pytest.raises(wire.WireError, match="v2 metadata schema"):
        wire.metadata(output, descriptor)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("call_index", True, "call index"),
        ("wall_s", float("nan"), "latency"),
        ("content_sha256", "0" * 64, "channel digest"),
    ],
)
def test_replay_rejects_strict_type_latency_and_channel_digest_tampering(
    tmp_path, field, value, message
):
    output, original = _invoke(tmp_path)
    receipt = copy.deepcopy(original.receipt)
    receipt[field] = value
    forged = wire.Call(
        original.status,
        original.dispatch_state,
        original.content,
        original.reasoning_content,
        original.tool_calls,
        receipt,
        original.descriptor,
    )
    with pytest.raises(wire.WireError, match=message):
        _replay(output, forged)


def test_replay_rejects_changed_raw_file_before_parsing_or_model_access(tmp_path):
    output, call = _invoke(tmp_path)
    stream_path = output / call.descriptor["raw_stream"]["path"]
    stream_path.write_bytes(stream_path.read_bytes() + b"tampered")
    with pytest.raises(wire.WireError, match="SSE bytes differ"):
        _replay(output, call)
