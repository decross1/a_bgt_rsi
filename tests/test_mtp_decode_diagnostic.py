"""CPU-only producer tests for the separate three-call decode diagnostic."""
from __future__ import annotations

import hashlib
import json
import threading
import time

import pytest

from bench.flash_next_ab import harness, qualification as q
from bench.flash_next_ab.followon_profiles import MIA_MTP2
from bench.flash_next_ab.mtp_decode_diagnostic import (
    BLOCK_BUDGET_S, SEED_BLOCK, freeze_plan, run_model, validate_run,
)
from bench.flash_next_ab.transport import (
    StreamAccumulator, _private_response_evidence, canonical, request_body,
)


def _route():
    spec = MIA_MTP2
    return {"served_model": spec.served_name,
            "artifact_sha256": spec.model_artifact_sha256(),
            "runtime_sha256": harness._qualification_runtime_sha256(
                image_id=spec.image_id,
                command_sha256=q.sha256(
                    spec.launch_argv(compilation_config=q.COMPILATION_CONFIG))),
            "qualification_receipt_sha256": "a" * 64}


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
        event = {"id": f"decode_{self.calls}", "model": endpoint.served_model,
                 "choices": [{"index": 0,
                              "delta": {"content": "i,square,cube\n1,1,1\n"},
                              "finish_reason": "stop"}]}
        usage = {"id": f"decode_{self.calls}", "model": endpoint.served_model,
                 "choices": [],
                 "usage": {"prompt_tokens": 26, "completion_tokens": 15,
                           "total_tokens": 41}}
        lines = [json.dumps(event), json.dumps(usage), "[DONE]"]
        raw = b"".join(f"data: {line}\n\n".encode() for line in lines)
        for line in lines:
            accumulator.accept(line)
        body = request_body(endpoint, messages, policy, max_tokens, seed, tools)
        returned = accumulator.result()
        returned.update({"latency_s": 0.00001, "ttft_s": 0.000005,
                         "request_sha256": hashlib.sha256(canonical(body)).hexdigest(),
                         "response_stream_sha256": hashlib.sha256(raw).hexdigest(),
                         "endpoint": endpoint.__dict__, "resolved_request": body,
                         "response_bytes": len(raw), "retries": 0,
                         "private_evidence": _private_response_evidence(
                             accumulator, raw, response_bytes=len(raw))})
        return returned


def _output(tmp_path):
    root = tmp_path / "grouped-window"
    root.mkdir()
    return root / "blocks" / "mtp_decode_timing"


def test_actual_three_call_mtp2_producer_private_timing_and_early_stop(tmp_path):
    plan = freeze_plan(MIA_MTP2.spec_id, _route())
    output = _output(tmp_path)
    invoked = _Complete()
    run = run_model(
        plan, endpoint_name=MIA_MTP2.endpoint_name, seed_block=SEED_BLOCK,
        output_dir=output, runtime_budget_s=BLOCK_BUDGET_S,
        admission_gate=lambda *_: None, safety_check=lambda: None,
        work_cutoff_s=time.monotonic() + 1000,
        cancel_event=threading.Event(), invoke_fn=invoked,
    )
    validate_run(run, plan)
    assert invoked.calls == 3
    assert run["summary"] == {"attempted": 3, "returned": 3,
                               "timeout": 0, "error": 0, "early_stop": 3}
    assert run["comparison_eligible"] is False
    assert all(row["timing"]["schema_version"] == "flash-followon-call-timing/v1"
               for row in run["outcomes"])
    for row in run["outcomes"]:
        descriptor = row["private_call_evidence"][0]
        assert (output / descriptor["metadata_path"]).is_file()
        assert (output / descriptor["raw_stream"]["path"]).is_file()
    assert b"i,square,cube" not in (output / "run.json").read_bytes()


def test_pre_first_byte_timeout_stays_in_complete_three_call_denominator(tmp_path):
    plan = freeze_plan(MIA_MTP2.spec_id, _route())
    output = _output(tmp_path)
    run = run_model(
        plan, endpoint_name=MIA_MTP2.endpoint_name, seed_block=SEED_BLOCK,
        output_dir=output, runtime_budget_s=BLOCK_BUDGET_S,
        admission_gate=lambda *_: None, safety_check=lambda: None,
        work_cutoff_s=time.monotonic() + 1000,
        cancel_event=threading.Event(), invoke_fn=_Complete(timeout_first=True),
    )
    validate_run(run, plan)
    assert run["summary"]["timeout"] == 1
    assert run["outcomes"][0]["timing"]["status"] == "unavailable"
    descriptor = run["outcomes"][0]["private_call_evidence"][0]
    assert descriptor["raw_stream"]["bytes"] == 0
    assert (output / descriptor["raw_stream"]["path"]).read_bytes() == b""


def test_resealed_wrong_policy_call_rejected_by_block_validator(tmp_path):
    plan = freeze_plan(MIA_MTP2.spec_id, _route())
    run = run_model(
        plan, endpoint_name=MIA_MTP2.endpoint_name, seed_block=SEED_BLOCK,
        output_dir=_output(tmp_path), runtime_budget_s=BLOCK_BUDGET_S,
        admission_gate=lambda *_: None, safety_check=lambda: None,
        work_cutoff_s=time.monotonic() + 1000,
        cancel_event=threading.Event(), invoke_fn=_Complete(),
    )
    run["outcomes"][0]["calls"][0]["resolved_policy_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="recorded request"):
        validate_run(run, plan)
