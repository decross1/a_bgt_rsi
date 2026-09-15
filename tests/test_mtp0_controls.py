"""Producer-shaped MTP0 control block source tests; NOT RUN during pair.

The injected transport returns a real StreamAccumulator/private-SSE shape so
the genuine harness._invoke_call/private writer runs for all 12 control cells.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time

import pytest

from bench.flash_next_ab import harness, qualification as q
from bench.flash_next_ab.candidate_registry import MIA
from bench.flash_next_ab.mtp0_controls import (
    BLOCK_BUDGET_S, SEED_BLOCK, freeze_plan, run_model, validate_run,
)
from bench.flash_next_ab.transport import (
    StreamAccumulator, _private_response_evidence, canonical, request_body,
)


def _route():
    return {
        "served_model": MIA.served_name,
        "artifact_sha256": MIA.model_artifact_sha256(),
        "runtime_sha256": harness._qualification_runtime_sha256(
            image_id=MIA.image_id,
            command_sha256=q.sha256(MIA.launch_argv(compilation_config=q.COMPILATION_CONFIG)),
        ),
        "qualification_receipt_sha256": "a" * 64,
    }


class _Complete:
    def __init__(self, timeout_first=False):
        self.calls = 0
        self.timeout_first = timeout_first

    def __call__(self, endpoint, messages, *, policy, max_tokens, timeout_s,
                 seed, tools=None, cancel_event=None):
        self.calls += 1
        accumulator = StreamAccumulator(endpoint.served_model)
        if self.calls == 1 and self.timeout_first:
            exc = TimeoutError("before first SSE byte")
            exc.private_evidence = _private_response_evidence(
                accumulator, b"", response_bytes=0)
            raise exc
        prompt = messages[-1]["content"]
        if "ALPHA17_BETA703" in prompt:
            text = "ALPHA17_BETA703_GAMMA29_DELTA11"
        elif "Four players" in prompt:
            text = "1,1,1,1"
        elif "clamp01" in prompt:
            text = "def clamp01(value):\n    return min(1.0, max(0.0, float(value)))"
        else:
            text = ""
        tool_calls = None
        if "record_probe" in prompt:
            tool_calls = [{"index": 0, "id": "call-generated-id",
                           "type": "function", "function": {
                               "name": "record_probe",
                               "arguments": '{"label":"mtp-parity","value":703}',
                           }}]
        chunks = [
            {"id": "control-response", "model": endpoint.served_model,
             "choices": [{"index": 0, "delta": {
                 **({"content": text} if text else {}),
                 **({"tool_calls": tool_calls} if tool_calls else {}),
             }, "finish_reason": "tool_calls" if tool_calls else "stop"}]},
            {"id": "control-response", "model": endpoint.served_model,
             "choices": [], "usage": {"prompt_tokens": 36,
                                      "completion_tokens": 4, "total_tokens": 40}},
        ]
        lines = [json.dumps(item) for item in chunks] + ["[DONE]"]
        raw_stream = b"".join(f"data: {line}\n\n".encode() for line in lines)
        for line in lines:
            accumulator.accept(line)
        body = request_body(endpoint, messages, policy, max_tokens, seed, tools)
        request_raw = canonical(body)
        result = accumulator.result()
        result.update({
            "latency_s": 0.01, "ttft_s": 0.005,
            "request_sha256": hashlib.sha256(request_raw).hexdigest(),
            "response_stream_sha256": hashlib.sha256(raw_stream).hexdigest(),
            "endpoint": endpoint.__dict__, "resolved_request": body,
            "response_bytes": len(raw_stream), "retries": 0,
            "private_evidence": _private_response_evidence(
                accumulator, raw_stream, response_bytes=len(raw_stream)),
        })
        return result


def _window(tmp_path):
    root = tmp_path / "window"
    root.mkdir()
    return root / "blocks" / "mtp0-control"


def test_actual_12_call_control_producer_private_sse_and_gate(tmp_path):
    plan = freeze_plan(_route())
    output = _window(tmp_path)
    invoked = _Complete()
    admissions = []
    result = run_model(
        plan, endpoint_name=MIA.endpoint_name, seed_block=SEED_BLOCK,
        output_dir=output, runtime_budget_s=BLOCK_BUDGET_S,
        admission_gate=lambda value, name: admissions.append((value, name)),
        safety_check=lambda: None, work_cutoff_s=time.monotonic() + 1000,
        cancel_event=threading.Event(), invoke_fn=invoked,
    )
    validate_run(result, plan)
    assert admissions == [(plan, MIA.endpoint_name)] and invoked.calls == 12
    assert result["summary"] == {"attempted": 12, "returned": 12,
                                  "passed": 12, "timeout": 0, "error": 0}
    assert result["controls_ready_for_parity"] is True
    assert result["comparison_eligible"] is False
    for row in result["outcomes"]:
        descriptor = row["private_call_evidence"][0]
        assert (output / descriptor["metadata_path"]).is_file()
        assert (output / descriptor["raw_stream"]["path"]).is_file()
    raw = (output / "run.json").read_bytes()
    assert b"ALPHA17_BETA703_GAMMA29_DELTA11" not in raw
    assert b"raw_response_stream" not in raw


def test_pre_first_byte_timeout_is_complete_attempted_failure(tmp_path):
    plan = freeze_plan(_route())
    output = _window(tmp_path)
    result = run_model(
        plan, endpoint_name=MIA.endpoint_name, seed_block=SEED_BLOCK,
        output_dir=output, runtime_budget_s=BLOCK_BUDGET_S,
        admission_gate=lambda *_: None, safety_check=lambda: None,
        work_cutoff_s=time.monotonic() + 1000,
        cancel_event=threading.Event(), invoke_fn=_Complete(timeout_first=True),
    )
    validate_run(result, plan)
    assert result["summary"]["attempted"] == 12
    assert result["summary"]["timeout"] == 1
    assert result["controls_ready_for_parity"] is False
    descriptor = result["outcomes"][0]["private_call_evidence"][0]
    assert descriptor["raw_stream"]["bytes"] == 0
    assert (output / descriptor["raw_stream"]["path"]).read_bytes() == b""


def test_mixed_route_rejected_before_any_output_or_model_call(tmp_path):
    plan = freeze_plan(_route())
    plan["route"]["runtime_sha256"] = "f" * 64
    output = _window(tmp_path)
    invoked = _Complete()
    with pytest.raises(ValueError):
        run_model(plan, endpoint_name=MIA.endpoint_name, seed_block=SEED_BLOCK,
                  output_dir=output, runtime_budget_s=BLOCK_BUDGET_S,
                  admission_gate=lambda *_: None, safety_check=lambda: None,
                  work_cutoff_s=time.monotonic() + 1000,
                  cancel_event=threading.Event(), invoke_fn=invoked)
    assert invoked.calls == 0 and not output.exists()
