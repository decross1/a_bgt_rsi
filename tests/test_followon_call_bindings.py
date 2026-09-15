"""Adverse frozen-call checks; run only after the first live pair closes.

The raw private-byte replay has separate producer→gate tests. These fixtures
prove that a self-consistent transport receipt cannot stand in for a different
declared cell, route or reasoning policy.
"""
from __future__ import annotations

import copy

from bench.flash_next_ab import followon_dispatch as grouped
from bench.flash_next_ab import followon_market_canaries as market
from bench.flash_next_ab import followon_thinking as thinking
from bench.flash_next_ab.followon_timing import TimingRecorder
from bench.flash_next_ab.manifest import sha256_json
from bench.flash_next_ab.transport import MIA_ARTIFACT_SHA256
from bench.weekly_upgrade_effort import manifest as effort_manifest
from bench.weekly_upgrade_effort import runner as effort_runner

ROUTES = {
    "resident_qwen": {"served_model": "qwen3.8-27b-nvfp4-mtp",
                      "artifact_sha256": "a" * 64, "runtime_sha256": "b" * 64,
                      "qualification_receipt_sha256": "c" * 64},
    "flash_next_mia": {"served_model": "qwen3.8-flash-next-mia",
                       "artifact_sha256": MIA_ARTIFACT_SHA256,
                       "runtime_sha256": "e" * 64,
                       "qualification_receipt_sha256": "f" * 64},
}


def _returned_call(cell, route, *, endpoint, condition, policy, messages,
                   cap, timeout, seed):
    return {"call_index": 0, "call_id": f"{cell['cell_id']}#0",
            "role": cell["role"], "endpoint_name": endpoint,
            "served_model": route["served_model"],
            "artifact_sha256": route["artifact_sha256"],
            "policy_id": condition,
            "resolved_policy_sha256": sha256_json(policy),
            "messages_sha256": sha256_json(messages),
            "tools_sha256": sha256_json([]), "seed": seed,
            "max_tokens": cap, "timeout_s": timeout,
            "status": "returned", "wall_s": 2.0,
            "request_sha256": "1" * 64, "response_stream_sha256": "2" * 64,
            "response_model": route["served_model"],
            "usage": {"prompt_tokens": 20, "completion_tokens": 5}}


def _unavailable_timing(call):
    return TimingRecorder().for_calls([call])


def thinking_run():
    plan = thinking.freeze_plan(thinking.PILOT_ID, ROUTES)
    route = ROUTES["flash_next_mia"]
    manifest = effort_manifest.load_manifest(thinking.SOURCE_MANIFEST)
    tasks = {task["id"]: task for task in manifest["tasks"]}
    outcomes = []
    for cell in plan["declared_cells"]:
        adaptive = cell["condition"] == "adaptive"
        bounded = adaptive and cell["role"] != "critic"
        condition = ("xhigh" if adaptive and cell["role"] == "critic"
                     else "medium" if adaptive else cell["condition"])
        call = _returned_call(
            cell, route, endpoint="flash_next_mia", condition=condition,
            policy=plan["policies"][condition],
            messages=effort_runner.messages(tasks[cell["task_id"]], retry=False),
            cap=thinking.TOTAL_TOKENS // 2 if bounded else thinking.TOTAL_TOKENS,
            timeout=thinking.CELL_TIMEOUT_S / 2 if bounded else thinking.CELL_TIMEOUT_S,
            seed=cell["seed"],
        )
        outcomes.append({**cell, "endpoint_name": "flash_next_mia",
                         "served_model": route["served_model"],
                         "artifact_sha256": route["artifact_sha256"],
                         "runtime_sha256": route["runtime_sha256"],
                         "status": "returned", "passed": False,
                         "execution_error_type": None,
                         "returned_usage_valid": True,
                         "escalated": False, "calls": [call],
                         "private_call_evidence": [{"call_id": call["call_id"]}],
                         "transport_timings": _unavailable_timing(call)})
    return plan, {"schema_version": thinking.RUN_SCHEMA, "status": "complete",
                  "endpoint_name": "flash_next_mia", "seed_block": 71,
                  "plan": copy.deepcopy(plan),
                  "plan_sha256": plan["plan_sha256"],
                  "qualification_receipt_sha256": route["qualification_receipt_sha256"],
                  "declared_cells": 30, "outcomes": outcomes,
                  "promotion_authorized": False}


def test_thinking_call_must_match_frozen_route_and_policy():
    plan, run = thinking_run()
    assert grouped._thinking_block_complete(run, plan, "flash_next_mia", 71)
    wrong_route = copy.deepcopy(run)
    wrong_route["outcomes"][0]["calls"][0]["endpoint_name"] = "resident_qwen"
    assert not grouped._thinking_block_complete(wrong_route, plan, "flash_next_mia", 71)
    wrong_policy = copy.deepcopy(run)
    wrong_policy["outcomes"][0]["calls"][0]["resolved_policy_sha256"] = "9" * 64
    assert not grouped._thinking_block_complete(wrong_policy, plan, "flash_next_mia", 71)


def market_run():
    plan = market.build_plan(ROUTES)
    route = ROUTES["flash_next_mia"]
    source, _ = market._source()
    tasks = {task["task_id"]: task for task in source["tasks"]}
    cells = [cell for cell in plan["declared_cells"] if cell["seed"] == 107]
    outcomes = []
    for cell in cells:
        call = _returned_call(
            cell, route, endpoint="flash_next_mia",
            condition=cell["condition"],
            policy=plan["policies"][cell["condition"]],
            messages=[{"role": "user", "content": tasks[cell["task_id"]]["prompt"]}],
            cap=plan["max_tokens"], timeout=plan["cell_timeout_s"],
            seed=cell["seed"],
        )
        private = [{"call_id": call["call_id"]}]
        outcomes.append({**cell, "status": "returned", "passed": False,
                         "calls": [call], "private_call_evidence": private,
                         "transport_timings": _unavailable_timing(call),
                         "grade": {"details": {"_private_call_evidence":
                                               {"artifacts": private}}}})
    return plan, {"schema_version": market.RUN_SCHEMA, "status": "complete",
                  "endpoint_name": "flash_next_mia", "seed_block": 107,
                  "source": plan["source"], "route": route,
                  "plan": copy.deepcopy(plan),
                  "plan_sha256": plan["plan_sha256"],
                  "declared_cells": 24, "outcomes": outcomes,
                  "comparison_eligible": False,
                  "promotion_authorized": False}


def test_market_call_must_match_frozen_route_and_policy():
    plan, run = market_run()
    assert grouped._market_block_complete(run, plan, "flash_next_mia", 107)
    wrong_route = copy.deepcopy(run)
    wrong_route["outcomes"][0]["calls"][0]["served_model"] = "qwen3.8-27b-nvfp4-mtp"
    assert not grouped._market_block_complete(wrong_route, plan, "flash_next_mia", 107)
    wrong_policy = copy.deepcopy(run)
    wrong_policy["outcomes"][0]["calls"][0]["policy_id"] = "medium_reasoning"
    assert not grouped._market_block_complete(wrong_policy, plan, "flash_next_mia", 107)
