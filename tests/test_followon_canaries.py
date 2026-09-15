"""Producer-shaped canary and private-stream source tests.

This uses transport.StreamAccumulator and _private_response_evidence to make
genuine nested raw-SSE bytes, then the real qualification private stream writer.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from bench.flash_next_ab import qualification as q
from bench.flash_next_ab.followon_canaries import (
    CONTEXT_EXPECTED_TEXT,
    CONTEXT_SELECTED_CELL_ID,
    FollowonCanaryError,
    compare_mtp_decoded_controls,
    run_profile_canary,
)
from bench.flash_next_ab.followon_profiles import MIA_CTX69632, MIA_MTP1
from bench.flash_next_ab.followon_qualification_admission import (
    _validate_profile_canary,
)
from bench.flash_next_ab.manifest import sha256_json
from bench.flash_next_ab.transport import (
    StreamAccumulator,
    _private_response_evidence,
    canonical,
    request_body,
)


class _Monitor:
    cancel_event = threading.Event()

    def check(self):
        return None


def _stream_result(model, *, text="", tools=None, prompt_tokens=36):
    accumulator = StreamAccumulator(model)
    generated = {
        "id": "canary-response-1", "model": model,
        "choices": [{"index": 0, "delta": {
            **({"content": text} if text else {}),
            **({"tool_calls": [{"index": 0, "id": "call-random",
                                "type": "function", "function": tools[0]["function"]}]
                } if tools else {}),
        }, "finish_reason": "tool_calls" if tools else "stop"}],
    }
    usage = {"id": "canary-response-1", "model": model, "choices": [],
             "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": 4,
                       "total_tokens": prompt_tokens + 4}}
    lines = [json.dumps(generated), json.dumps(usage), "[DONE]"]
    raw = b"".join(f"data: {line}\n\n".encode() for line in lines)
    for line in lines:
        accumulator.accept(line)
    result = accumulator.result()
    result["response_stream_sha256"] = hashlib.sha256(raw).hexdigest()
    result["private_evidence"] = _private_response_evidence(
        accumulator, raw, response_bytes=len(raw))
    return result


class _Ops:
    def __init__(self, *, wrong_literal=False, context_input_tokens=None):
        self.calls = 0
        self.wrong_literal = wrong_literal
        self.context_input_tokens = context_input_tokens

    def complete(self, endpoint, messages, **kwargs):
        self.calls += 1
        prompt = messages[-1]["content"]
        result = None
        if "ALPHA17_BETA703" in prompt:
            text = "WRONG" if self.wrong_literal else "ALPHA17_BETA703_GAMMA29_DELTA11"
            result = _stream_result(endpoint.served_model, text=text)
        elif "Four players" in prompt:
            result = _stream_result(endpoint.served_model, text="1,1,1,1")
        elif "clamp01" in prompt:
            result = _stream_result(endpoint.served_model, text="def clamp01(value):\n    return min(1.0, max(0.0, float(value)))")
        elif "record_probe" in prompt:
            result = _stream_result(endpoint.served_model,
                                  tools=[{"function": {"name": "record_probe",
                                                       "arguments": '{"label":"mtp-parity","value":703}'}}])
        else:
            result = _stream_result(endpoint.served_model, text=CONTEXT_EXPECTED_TEXT,
                                    prompt_tokens=self.context_input_tokens or 65_581)
        body = request_body(endpoint, messages, kwargs["policy"],
                            kwargs["max_tokens"], kwargs["seed"], kwargs.get("tools"))
        result.update({"request_sha256": hashlib.sha256(canonical(body)).hexdigest(),
                       "resolved_request": body, "endpoint": endpoint.__dict__,
                       "latency_s": 0.01, "ttft_s": 0.005})
        return result


def test_fullvocab_mtp_canary_real_nested_bytes_durable(tmp_path):
    ops = _Ops()
    summary = run_profile_canary(
        ops, _Monitor(), spec=MIA_MTP1, output=tmp_path, timeout_s=120,
        work_deadline=time.monotonic() + 100,
        atomic_write=q._atomic_write, record_private=q._probe_private_response,
    )
    assert summary["status"] == "passed" and summary["attempt_count"] == 12
    assert summary["lossless_claim"] is False
    attempts = json.loads((tmp_path / "profile-canary-attempts.json").read_text())
    assert len(attempts["results"]) == 12
    assert all(row["status"] == "passed" for row in attempts["results"])
    for row in attempts["results"]:
        assert (tmp_path / row["private_response"]["private_stream_relpath"]).is_file()
        assert isinstance(row["public_response"]["content"], str)
        assert "private_evidence" not in row["public_response"]
    assert b"raw_response_stream" not in (tmp_path / "profile-canary-attempts.json").read_bytes()
    now = datetime.now(timezone.utc)
    result = {
        "started_at": (now - timedelta(minutes=1)).isoformat(),
        "restoration": {"verified_at": (now + timedelta(minutes=1)).isoformat()},
        "profile_canary_status": "passed",
        "profile_canary_sha256": hashlib.sha256(
            (tmp_path / "profile-canary.json").read_bytes()).hexdigest(),
        "profile_canary_attempts_sha256": hashlib.sha256(
            (tmp_path / "profile-canary-attempts.json").read_bytes()).hexdigest(),
        "profile_canary_protocol_sha256": summary["protocol_sha256"],
        "profile_canary_suite": summary["suite"],
        "profile_canary_attempt_count": 12,
        "profile_canary_timeout_seconds": 120,
    }
    _validate_profile_canary(tmp_path, result, MIA_MTP1)


def test_wrong_returned_literal_is_durable_failure(tmp_path):
    with pytest.raises(FollowonCanaryError):
        run_profile_canary(
            _Ops(wrong_literal=True), _Monitor(), spec=MIA_MTP1,
            output=tmp_path, timeout_s=120, work_deadline=time.monotonic() + 100,
            atomic_write=q._atomic_write, record_private=q._probe_private_response,
        )
    attempts = json.loads((tmp_path / "profile-canary-attempts.json").read_text())
    assert attempts["results"][0]["status"] == "failed"
    assert attempts["results"][0]["public_response"]["content"] == "WRONG"
    assert (tmp_path / attempts["results"][0]["private_response"]["private_stream_relpath"]).is_file()
    assert json.loads((tmp_path / "profile-canary.json").read_text())["status"] == "failed"


def test_native69632_canary_binds_server_usage_and_answer(tmp_path, monkeypatch):
    packet = {"pack_sha256": "f7e0619be42ca770c39728a51b3a73a92562780be7797662c4f63139ba5c7876",
              "cell_id": CONTEXT_SELECTED_CELL_ID,
              "actual_input_tokens": 65_581, "max_tokens": 2048,
              "messages": [{"role": "user", "content": "frozen packet placeholder"}],
              "expected": CONTEXT_EXPECTED_TEXT}
    packet["source_messages_sha256"] = sha256_json(packet["messages"])
    monkeypatch.setattr("bench.flash_next_ab.followon_canaries.CONTEXT_SELECTED_MESSAGES_SHA256",
                        packet["source_messages_sha256"])
    summary = run_profile_canary(
        _Ops(context_input_tokens=65_581), _Monitor(), spec=MIA_CTX69632,
        output=tmp_path, timeout_s=300, work_deadline=time.monotonic() + 400,
        atomic_write=q._atomic_write, record_private=q._probe_private_response,
        native_context_packet_factory=lambda: packet,
    )
    assert summary["status"] == "passed" and summary["attempt_count"] == 1
    assert summary["lossless_claim"] is False


def test_repeated_control_nondeterminism_blocks_causal_attribution():
    from bench.flash_next_ab import followon_canaries
    protocol = json.loads(Path(followon_canaries.__file__).with_name(
        "MTP_PARITY_PROTOCOL.json").read_text())
    def call(letter, request_id):
        return {"content": letter, "reasoning_content": "", "tool_calls": [],
                "finish_reason": "stop", "response_model": MIA_MTP1.served_name,
                "request_sha256": hashlib.sha256(request_id.encode()).hexdigest(),
                "resolved_request": {"seed": 17, "messages": [request_id]},
                "endpoint": {"name": MIA_MTP1.endpoint_name,
                             "artifact_sha256": MIA_MTP1.model_artifact_sha256()}}
    a = {row["id"]: [call("A", row["id"])] * 3 for row in protocol["requests"]}
    b = {name: list(rows) for name, rows in a.items()}
    assert all("parity_observed" in status for status in
               compare_mtp_decoded_controls(a, b).values())
    a["code_generation"] = [a["code_generation"][0], call("B", "code_generation"),
                            a["code_generation"][0]]
    assert compare_mtp_decoded_controls(a, b)["code_generation"] == "control_nondeterminism_confounded"
    a["code_generation"] = [a["code_generation"][0]] * 3
    b["code_generation"] = [call("C", "code_generation")] * 3
    assert compare_mtp_decoded_controls(a, b)["code_generation"] == "decoded_output_parity_failed"
    b["code_generation"] = [dict(call("C", "code_generation"),
                                 request_sha256="f" * 64)] * 3
    with pytest.raises(FollowonCanaryError):
        compare_mtp_decoded_controls(a, b)
