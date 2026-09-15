"""Small CPU-only private provenance tests. Run after any live load ends."""
from __future__ import annotations

import hashlib
import importlib
import json

import pytest

from bench.flash_next_ab.harness import (
    _BASE_URLS,
    PRIVATE_CALL_SCHEMA,
    _persist_private_call,
)
from bench.flash_next_ab.manifest import sha256_json
from bench.flash_next_ab.transport import LocalEndpoint, canonical, request_body


def module():
    return importlib.import_module("bench.flash_next_ab.private_evidence")


def fixture(tmp_path):
    harness = tmp_path / "harness"
    stem = "0001-" + hashlib.sha256(b"call-1").hexdigest()[:16]
    stream_path = f"private/streams/{stem}.sse"
    metadata_path = f"private/calls/{stem}.json"
    model = "gemma-4-26b-a4b"
    stream = b"".join((
        ("data: " + json.dumps({
            "id": "cmpl-1", "model": model,
            "choices": [{"index": 0, "delta": {
                "content": "private-only synthetic model response",
            }, "finish_reason": "stop"}],
        }, separators=(",", ":")) + "\n\n").encode(),
        ("data: " + json.dumps({
            "id": "cmpl-1", "model": model, "choices": [],
            "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        }, separators=(",", ":")) + "\n\n").encode(),
        b"data: [DONE]\n\n",
    ))
    stream_file = harness / stream_path
    stream_file.parent.mkdir(parents=True)
    stream_file.write_bytes(stream)
    stream_descriptor = {
        "path": stream_path, "sha256": hashlib.sha256(stream).hexdigest(),
        "bytes": len(stream),
    }
    policy = {"temperature": 0, "top_p": 1}
    messages = [{"role": "user", "content": "synthetic private request"}]
    tools = []
    endpoint = LocalEndpoint("resident_gemma", _BASE_URLS["resident_gemma"], model, "a" * 64)
    request_digest = hashlib.sha256(
        canonical(request_body(endpoint, messages, policy, 128, 123))
    ).hexdigest()
    call = {
        "call_id": "call-1", "call_index": 0, "role": "architect",
        "status": "returned", "failure_code": None, "error": None,
        "endpoint_name": "resident_gemma", "served_model": model,
        "artifact_sha256": "a" * 64, "policy_id": "temperature-zero",
        "resolved_policy_sha256": sha256_json(policy),
        "messages_sha256": sha256_json(messages),
        "tools_sha256": sha256_json(tools),
        "seed": 123, "max_tokens": 128, "timeout_s": 10,
        "request_sha256": request_digest,
        "response_stream_sha256": stream_descriptor["sha256"],
        "response_id": "cmpl-1", "response_model": model,
        "finish_reason": "stop",
        "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
    }
    request_keys = (
        "endpoint_name", "served_model", "artifact_sha256", "policy_id",
        "seed", "max_tokens", "timeout_s", "request_sha256"
    )
    response_keys = (
        "response_stream_sha256", "response_id", "response_model", "finish_reason", "usage"
    )
    metadata = {
        "schema_version": "flash-next-ab-private-call/v1", "call_id": call["call_id"],
        "call_index": 0, "role": "architect", "status": "returned",
        "failure_code": None, "error": None,
        "request": {
            **{key: call[key] for key in request_keys},
            "resolved_policy": policy, "messages": messages, "tools": tools,
        },
        "response": {
            **{key: call[key] for key in response_keys},
            "raw_stream_artifact": stream_descriptor,
            "content": "private-only synthetic model response",
            "reasoning_content": "", "tool_calls": [],
            "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        },
    }
    metadata_file = harness / metadata_path
    metadata_file.parent.mkdir(parents=True)
    raw_metadata = (json.dumps(metadata, sort_keys=True) + "\n").encode()
    metadata_file.write_bytes(raw_metadata)
    descriptor = {
        "call_id": call["call_id"], "status": "returned",
        "metadata_path": metadata_path,
        "metadata_sha256": hashlib.sha256(raw_metadata).hexdigest(),
        "metadata_bytes": len(raw_metadata), "raw_stream": stream_descriptor,
    }
    run = {
        "status": "complete", "outcomes": [{
            "calls": [call], "grade": {"details": {
                "_private_call_evidence": {
                    "schema_version": "flash-next-ab-private-evidence-index/v1",
                    "artifacts": [descriptor],
                },
            }},
        }],
    }
    return harness, run, metadata_file, stream_file


def test_metadata_and_response_bytes_bind_without_exporting_content(tmp_path):
    gate = module()
    harness, run, _, _ = fixture(tmp_path)
    proof = gate.validate_private_evidence(run, harness)
    assert proof["calls_verified"] == 1
    assert proof["response_streams_verified"] == 1
    assert proof["private_content_exported"] is False
    assert "private-only" not in json.dumps(proof)


@pytest.mark.parametrize("kind", ("metadata", "stream", "public_request"))
def test_lost_or_drifted_private_provenance_is_rejected(tmp_path, kind):
    gate = module()
    harness, run, metadata_file, stream_file = fixture(tmp_path)
    if kind == "metadata":
        metadata_file.write_bytes(metadata_file.read_bytes() + b"{")
    elif kind == "stream":
        stream_file.write_bytes(stream_file.read_bytes() + b"x")
    else:
        run["outcomes"][0]["calls"][0]["request_sha256"] = "c" * 64
    with pytest.raises(gate.PrivateEvidenceError):
        gate.validate_private_evidence(run, harness)


@pytest.mark.parametrize("field", ("messages", "content"))
def test_resealed_metadata_must_match_rendered_request_and_raw_sse(tmp_path, field):
    gate = module()
    harness, run, metadata_file, _ = fixture(tmp_path)
    metadata = json.loads(metadata_file.read_text())
    if field == "messages":
        metadata["request"]["messages"][0]["content"] = "resealed other question"
    else:
        metadata["response"]["content"] = "resealed invented answer"
    raw = (json.dumps(metadata, sort_keys=True) + "\n").encode()
    metadata_file.write_bytes(raw)
    descriptor = run["outcomes"][0]["grade"]["details"]["_private_call_evidence"]["artifacts"][0]
    descriptor["metadata_sha256"] = hashlib.sha256(raw).hexdigest()
    descriptor["metadata_bytes"] = len(raw)
    with pytest.raises(gate.PrivateEvidenceError):
        gate.validate_private_evidence(run, harness)


def test_failed_call_with_partial_private_stream_is_kept_in_denominator(tmp_path):
    gate = module()
    harness, run, metadata_file, stream_file = fixture(tmp_path)
    call = run["outcomes"][0]["calls"][0]
    descriptor = run["outcomes"][0]["grade"]["details"]["_private_call_evidence"]["artifacts"][0]
    call.update(
        status="timeout", failure_code="request_timeout", error="TimeoutError: synthetic timeout",
        response_stream_sha256=None, response_id=None, response_model=None,
        finish_reason=None, usage=None,
    )
    descriptor["status"] = "timeout"
    partial = stream_file.read_bytes().split(b"data: {", 2)[1]
    # Keep the first valid SSE event, before usage and the [DONE] marker.
    first = b"data: {" + partial
    first = first[: first.index(b"\n\n") + 2]
    stream_file.write_bytes(first)
    raw_sha = hashlib.sha256(first).hexdigest()
    descriptor["raw_stream"].update(sha256=raw_sha, bytes=len(first))
    metadata = json.loads(metadata_file.read_text())
    metadata.update(status="timeout", failure_code=call["failure_code"], error=call["error"])
    metadata["response"]["raw_stream_artifact"] = descriptor["raw_stream"]
    metadata["response"]["response_stream_sha256"] = raw_sha
    raw = (json.dumps(metadata, sort_keys=True) + "\n").encode()
    metadata_file.write_bytes(raw)
    descriptor.update(metadata_sha256=hashlib.sha256(raw).hexdigest(), metadata_bytes=len(raw))
    proof = gate.validate_private_evidence(run, harness)
    assert proof["calls_verified"] == 1
    assert proof["response_streams_verified"] == 1


def test_resealed_public_usage_must_match_private_raw_sse(tmp_path):
    gate = module()
    harness, run, _, _ = fixture(tmp_path)
    run["outcomes"][0]["calls"][0]["usage"] = {
        "prompt_tokens": 1, "completion_tokens": 20, "total_tokens": 21,
    }
    with pytest.raises(gate.PrivateEvidenceError, match="transcript differs"):
        gate.validate_private_evidence(run, harness)


def first_byte_timeout(tmp_path):
    """Use the real shared harness producer to write a 0-byte SSE receipt."""
    harness, run, existing_metadata, existing_stream = fixture(tmp_path)
    call = run["outcomes"][0]["calls"][0]
    call.update(
        status="timeout", failure_code="transport_timeout",
        error="TimeoutError: model request exceeded its wall-clock deadline",
        response_stream_sha256=None, response_id=None, response_model=None,
        finish_reason=None, usage=None,
    )
    metadata = json.loads(existing_metadata.read_text())
    response = {
        "content": "", "reasoning_content": "", "tool_calls": [],
        "response_id": None, "response_model": None, "finish_reason": None,
        "usage": None, "response_stream_sha256": hashlib.sha256(b"").hexdigest(),
    }
    written = _persist_private_call(
        harness, ordinal=0,
        evidence={
            "schema_version": PRIVATE_CALL_SCHEMA,
            "call_id": call["call_id"], "call_index": call["call_index"],
            "role": call["role"], "status": "timeout",
            "request": metadata["request"], "response": response,
            "failure_code": call["failure_code"], "error": call["error"],
            "_raw_response_stream": b"",
        },
    )
    assert written["raw_stream"]["bytes"] == 0
    assert (harness / written["raw_stream"]["path"]).stat().st_size == 0
    run["outcomes"][0]["grade"]["details"]["_private_call_evidence"]["artifacts"] = [written]
    existing_metadata.unlink()
    existing_stream.unlink()
    return harness, run, written


def test_real_producer_pre_first_byte_timeout_is_valid_denominator(tmp_path):
    gate = module()
    harness, run, _descriptor = first_byte_timeout(tmp_path)
    proof = gate.validate_private_evidence(run, harness)
    assert proof["calls_verified"] == proof["response_streams_verified"] == 1


def test_empty_returned_stream_or_resealed_partial_content_is_rejected(tmp_path):
    gate = module()
    harness, run, descriptor = first_byte_timeout(tmp_path)
    call = run["outcomes"][0]["calls"][0]
    call.update(status="returned", failure_code=None, error=None)
    descriptor["status"] = "returned"
    with pytest.raises(gate.PrivateEvidenceError):
        gate.validate_private_evidence(run, harness)

    call.update(status="timeout", failure_code="transport_timeout",
                error="TimeoutError: model request exceeded its wall-clock deadline")
    descriptor["status"] = "timeout"
    metadata_path = harness / descriptor["metadata_path"]
    recorded = json.loads(metadata_path.read_bytes())
    recorded["response"]["content"] = "resealed private text without SSE bytes"
    raw = (json.dumps(recorded, sort_keys=True) + "\n").encode()
    metadata_path.write_bytes(raw)
    descriptor["metadata_sha256"] = hashlib.sha256(raw).hexdigest()
    descriptor["metadata_bytes"] = len(raw)
    with pytest.raises(gate.PrivateEvidenceError):
        gate.validate_private_evidence(run, harness)


def test_empty_private_stream_symlink_does_not_block_or_admit(tmp_path):
    gate = module()
    harness, run, descriptor = first_byte_timeout(tmp_path)
    stream_file = harness / descriptor["raw_stream"]["path"]
    source = tmp_path / "source.txt"
    source.write_bytes(b"")
    stream_file.unlink()
    stream_file.symlink_to(source)
    with pytest.raises((gate.PrivateEvidenceError, OSError)):
        gate.validate_private_evidence(run, harness)
