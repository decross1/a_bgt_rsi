"""Selected repair source and call bindings, with no model or service calls."""
from __future__ import annotations

import copy
import hashlib
import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from bench.flash_next_ab import followon_completed_window_admission as completed
from bench.flash_next_ab import followon_prepare as first
from bench.flash_next_ab import followon_selected_repair as repair
from bench.flash_next_ab.private_evidence import validate_private_evidence
from bench.flash_next_ab.transport import (
    StreamAccumulator,
    _private_response_evidence,
    canonical,
    request_body,
)


def _plan():
    parent = first._parents(first.PARENT_ID)
    original = first._routes(parent)
    routes = {key: first._public_route(original[key])
              for key in ("resident_gemma", "flash_next_mia")}
    return repair.freeze_plan(
        routes, candidate_variant_id="mia-925d7be6-mtp3-reduced47k-v2opt-v1"
    )


def test_repair_freezes_exact_22_existing_tasks_and_distinct_interpretations():
    plan = _plan()
    assert repair.validate_plan(plan) == plan
    assert len(plan["declared_cells"]["resident_gemma"]) == 22
    assert len(plan["declared_cells"]["flash_next_mia"]) == 44
    assert {row["lane"] for row in plan["declared_cells"]["flash_next_mia"]} == {
        "flash_off", "flash_medium",
    }
    assert all("reasoning_effort" not in
               plan["policies"][row["policy_id"]]
               for row in plan["declared_cells"]["resident_gemma"])
    assert all(plan["policies"][row["policy_id"]]["enable_thinking"] is False
               for row in plan["declared_cells"]["flash_next_mia"]
               if row["lane"] == "flash_off")
    assert all(plan["policies"][row["policy_id"]]["reasoning_effort"] == "medium"
               for row in plan["declared_cells"]["flash_next_mia"]
               if row["lane"] == "flash_medium")
    altered = copy.deepcopy(plan)
    altered["declared_cells"]["flash_next_mia"][0]["seed"] += 1
    with pytest.raises(ValueError, match="source, route or policies"):
        repair.validate_plan(altered)


def test_repair_requires_current_controller_gate_before_creating_output(
    tmp_path: Path,
):
    plan = _plan()
    output = tmp_path / "repair"
    with pytest.raises(RuntimeError, match="unqualified"):
        repair.run_model(
            plan, endpoint_name="flash_next_mia", seed_block=None,
            output_dir=output, runtime_budget_s=repair.FLASH_CEILING,
            admission_gate=lambda *_: (_ for _ in ()).throw(
                RuntimeError("unqualified")
            ),
            safety_check=lambda: None, work_cutoff_s=10_000,
            monotonic=lambda: 0.0,
        )
    assert not output.exists()


def test_repair_run_rejects_wrong_model_or_policy_before_private_join(
    monkeypatch,
):
    plan = _plan()
    endpoint = "resident_gemma"
    cells = plan["declared_cells"][endpoint]
    run = {
        "schema_version": repair.RUN_SCHEMA, "plan": plan,
        "plan_sha256": plan["plan_sha256"], "endpoint_name": endpoint,
        "declared_cells": len(cells),
        "runtime_budget_s": repair.RESIDENT_CEILING,
        "comparison_eligible": False, "promotion_authorized": False,
        "status": "incomplete",
        "outcomes": [
            {"repair_cell_id": cell["repair_cell_id"],
             "original_cell_id": cell["original_cell_id"],
             "lane": cell["lane"], "endpoint_name": endpoint,
             "calls": []}
            for cell in cells
        ],
    }
    repair.validate_run(run, plan, endpoint)
    first_cell = cells[0]
    run["outcomes"][0]["calls"] = [{
        "call_id": f"{first_cell['repair_cell_id']}#0",
        "role": first_cell["role"], "endpoint_name": "flash_next_mia",
    }]
    with pytest.raises(ValueError, match="planned route/policy"):
        repair.validate_run(run, plan, endpoint)


class _SourceShapedTransport:
    def __init__(self):
        self.calls = 0

    def __call__(self, endpoint, messages, *, policy, max_tokens,
                 timeout_s, seed, tools=None, cancel_event=None):
        self.calls += 1
        accumulator = StreamAccumulator(endpoint.served_model)
        chunks = [
            {"id": f"repair-{self.calls}", "model": endpoint.served_model,
             "choices": [{"index": 0, "delta": {"content": "{}"},
                          "finish_reason": "stop"}]},
            {"id": f"repair-{self.calls}", "model": endpoint.served_model,
             "choices": [], "usage": {"prompt_tokens": 20,
                                      "completion_tokens": 2,
                                      "total_tokens": 22}},
        ]
        lines = [json.dumps(item) for item in chunks] + ["[DONE]"]
        raw = b"".join(f"data: {line}\n\n".encode() for line in lines)
        for line in lines:
            accumulator.accept(line)
        body = request_body(endpoint, messages, policy, max_tokens, seed, tools)
        result = accumulator.result()
        result.update({
            "latency_s": 0.01, "ttft_s": 0.005,
            "request_sha256": hashlib.sha256(canonical(body)).hexdigest(),
            "response_stream_sha256": hashlib.sha256(raw).hexdigest(),
            "endpoint": endpoint.__dict__, "resolved_request": body,
            "response_bytes": len(raw), "retries": 0,
            "private_evidence": _private_response_evidence(
                accumulator, raw, response_bytes=len(raw)),
        })
        return result


@pytest.mark.parametrize(
    ("endpoint", "attempts", "ceiling"),
    [("resident_gemma", 22, repair.RESIDENT_CEILING),
     ("flash_next_mia", 44, repair.FLASH_CEILING)],
)
def test_repair_produces_complete_denominator_and_raw_sse(
    tmp_path, endpoint, attempts, ceiling,
):
    plan = _plan()
    fake = _SourceShapedTransport()
    output = tmp_path / f"{endpoint}-repair"
    result = repair.run_model(
        plan, endpoint_name=endpoint, seed_block=None,
        output_dir=output, runtime_budget_s=ceiling,
        admission_gate=lambda *_: None, safety_check=lambda: None,
        work_cutoff_s=time.monotonic() + ceiling + 60,
        cancel_event=threading.Event(), invoke_fn=fake,
    )
    assert result["status"] == "complete"
    assert result["summary"]["attempted"] == attempts and fake.calls == attempts
    repair.validate_run(result, plan, endpoint)
    proof = validate_private_evidence(result, output)
    assert proof["calls_verified"] == attempts
    assert proof["private_content_exported"] is False
    group = tmp_path / f"{endpoint}-group"
    child = group / "blocks" / "00-selected-repair"
    child.parent.mkdir(parents=True)
    output.rename(child)
    declaration = {
        "block_id": "selected-repair-0", "kind": "selected_repair",
        "endpoint_name": endpoint,
        "output_relative": "blocks/00-selected-repair",
    }
    window = SimpleNamespace(
        document={"blocks": [declaration]},
        frozen=SimpleNamespace(block_plans=(plan,)),
    )
    run_sha = hashlib.sha256((child / "run.json").read_bytes()).hexdigest()
    listed = {
        "ordinal": 0, "block_id": declaration["block_id"],
        "kind": "selected_repair",
        "status": "complete_pending_restoration", "reason_code": None,
        "run_sha256": run_sha, "attempted": attempts,
        "passed": result["summary"]["passed"],
        "timeouts": result["summary"]["timeouts"],
    }
    admitted = completed._block(window, group, 0, listed)
    assert admitted["private_calls_verified"] == attempts
    assert admitted["run_sha256"] == run_sha
