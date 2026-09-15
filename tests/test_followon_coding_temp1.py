"""CPU-only gate tests; run after Flash44 restore and new-source registration."""
from __future__ import annotations

import copy
import hashlib
import json
import threading
import time
from pathlib import Path

import pytest

from bench.flash_next_ab import followon_coding_temp1 as coding
from bench.flash_next_ab import private_evidence, transport

PARENT = Path(
    "/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-14/"
    "qwen-flash-next-research/evaluation/followon-qualified-parents/"
    "qfn-mia-mtp3-red47k-20260915-a.json"
)


def _plan():
    parent = json.loads(PARENT.read_bytes())
    route = {
        "served_model": parent["served_model"],
        "artifact_sha256": parent["model_artifact_sha256"],
        "runtime_sha256": parent["runtime_sha256"],
        "qualification_receipt_sha256": parent["qualification_receipt_sha256"],
    }
    return coding.freeze_plan(route,
                              candidate_variant_id=parent["candidate_spec_id"])


def test_exact_four_original_sources_and_new_sampling():
    plan = _plan()
    assert coding.validate_plan(plan) == plan
    assert [row["original_cell_id"] for row in plan["declared_cells"]] == list(coding.ORDER)
    assert [row["seed"] for row in plan["declared_cells"]] == [0, 0, 20260914, 20260914]
    assert plan["policy"] == {
        "temperature": 1, "top_p": 0.95, "top_k": 20,
        "enable_thinking": True, "reasoning_effort": "medium",
    }
    assert all(row["max_tokens"] == 8192 and row["timeout_s"] == 360
               for row in plan["declared_cells"])
    assert plan["caps"]["block_budget_seconds"] == 1560
    assert plan["comparison_eligible"] is False


def test_plan_tamper_rejected_before_any_call():
    plan = _plan()
    wrong = copy.deepcopy(plan)
    wrong["policy"]["temperature"] = 0
    with pytest.raises(ValueError):
        coding.validate_plan(wrong)
    wrong = copy.deepcopy(plan)
    wrong["declared_cells"][0]["max_tokens"] = 512
    with pytest.raises(ValueError):
        coding.validate_plan(wrong)
    wrong = copy.deepcopy(plan)
    wrong["declared_cells"][0]["original_cell_id"] = wrong["declared_cells"][1]["original_cell_id"]
    with pytest.raises(ValueError):
        coding.validate_plan(wrong)


def test_completed_run_needs_four_private_attempts():
    plan = _plan()
    rows = []
    for frozen in plan["declared_cells"]:
        rows.append({
            "diagnostic_cell_id": frozen["diagnostic_cell_id"],
            "original_cell_id": frozen["original_cell_id"],
            "family": frozen["family"], "endpoint_name": coding.ENDPOINT,
            "status": "timeout", "passed": False,
            "calls": [], "private_call_evidence": [],
        })
    run = {
        "schema_version": coding.RUN_SCHEMA, "plan": plan,
        "plan_sha256": plan["plan_sha256"], "endpoint_name": coding.ENDPOINT,
        "candidate_variant_id": plan["candidate_variant_id"],
        "declared_cells": 4, "runtime_budget_s": 1560,
        "comparison_eligible": False, "promotion_authorized": False,
        "status": "complete", "summary": {"attempted": 4}, "outcomes": rows,
    }
    with pytest.raises(ValueError):
        coding.validate_run(run, plan, coding.ENDPOINT)


def test_producer_four_real_transport_shaped_private_streams(tmp_path):
    """Invalid visible patches remain four returned, graded failures."""
    plan = _plan()
    observed_calls = []

    def fake_complete(endpoint, messages, *, policy, max_tokens,
                      timeout_s, seed, tools=None, cancel_event=None):
        body = transport.request_body(endpoint, messages, policy, max_tokens,
                                      seed, tools)
        request_sha = hashlib.sha256(transport.canonical(body)).hexdigest()
        response_id = f"cpu-test-{len(observed_calls)}"
        first = {"id": response_id, "model": endpoint.served_model,
                 "choices": [{"index": 0, "delta": {"content": "invalid_patch"},
                              "finish_reason": "stop"}]}
        usage = {"id": response_id, "model": endpoint.served_model,
                 "choices": [], "usage": {"prompt_tokens": 10,
                                          "completion_tokens": 1,
                                          "total_tokens": 11}}
        raw = (b"data: " + transport.canonical(first) + b"\n\n"
               + b"data: " + transport.canonical(usage) + b"\n\n"
               + b"data: [DONE]\n\n")
        accumulator = transport.StreamAccumulator(endpoint.served_model)
        accumulator.accept(transport.canonical(first).decode())
        accumulator.accept(transport.canonical(usage).decode())
        accumulator.accept("[DONE]")
        result = accumulator.result()
        result.update({
            "request_sha256": request_sha,
            "response_stream_sha256": hashlib.sha256(raw).hexdigest(),
            "latency_s": 0.1, "ttft_s": 0.05,
            "private_evidence": transport._private_response_evidence(
                accumulator, raw, response_bytes=len(raw)),
        })
        observed_calls.append(body)
        return result

    output = tmp_path / "group" / "blocks" / "00-coding"
    output.parent.parent.mkdir()
    run = coding.run_model(
        plan, endpoint_name=coding.ENDPOINT, seed_block=None,
        output_dir=output, runtime_budget_s=1560,
        admission_gate=lambda _plan, _endpoint: None,
        safety_check=lambda: None,
        work_cutoff_s=time.monotonic() + 1800,
        cancel_event=threading.Event(), invoke_fn=fake_complete,
    )
    assert run["status"] == "complete"
    assert run["summary"] == {"attempted": 4, "passed": 0, "timeouts": 0}
    assert len(observed_calls) == 4
    assert all(call["temperature"] == 1 and call["top_p"] == 0.95
               and call["top_k"] == 20 and call["max_tokens"] == 8192
               and call["reasoning_effort"] == "medium"
               for call in observed_calls)
    assert len(list((output / "private/streams").glob("*.sse"))) == 4
    coding.validate_run(run, plan, coding.ENDPOINT)
    private_evidence.validate_private_evidence(run, output)
    wrong = copy.deepcopy(run)
    wrong["abort_reason"] = "block_incomplete"
    with pytest.raises(ValueError):
        coding.validate_run(wrong, plan, coding.ENDPOINT)
