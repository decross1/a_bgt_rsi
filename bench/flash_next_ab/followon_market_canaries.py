"""Fresh GT/application-validity diagnostics inside an existing supervised window.

No model launch, resource lease, or standalone live CLI is provided here.
The caller supplies a qualified route, armed monitor, and restoration deadline.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from bench.flash_next_ab import harness
from bench.flash_next_ab.adapters import CallSpec
from bench.flash_next_ab.followon_timing import TimingRecorder
from bench.flash_next_ab.manifest import sha256_json
from bench.flash_next_ab.transport import complete

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "experiments/flash_market_canaries_v1_20260915.json"
PLAN_SCHEMA = "flash-fresh-market-canary-plan/v1"
RUN_SCHEMA = "flash-fresh-market-canary-run/v1"
ENDPOINTS = {
    "resident_qwen": "qwen3.8-27b-nvfp4-mtp",
    "flash_next_mia": "qwen3.8-flash-next-mia",
}
SEEDS = (107, 509)
CONDITIONS = ("deterministic", "medium_reasoning")
POLICIES = {
    "deterministic": {"temperature": 0.0, "top_p": 1.0, "top_k": 20,
                      "enable_thinking": False},
    "medium_reasoning": {"temperature": 1.0, "top_p": 0.95, "top_k": 20,
                         "enable_thinking": True, "reasoning_effort": "medium"},
}
CELL_SECONDS = 90
BLOCK_SECONDS = 2220
ROLES = {"generator", "planner", "critic", "evidence", "execution", "coding", "validator"}


def _require(value, message):
    if not value:
        raise ValueError(message)


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source():
    data = json.loads(FIXTURES.read_text())
    tasks = data["tasks"]
    _require(data["schema"] == "flash-fresh-market-game-theory-canaries/v1"
             and len(tasks) == 12 and len({t["task_id"] for t in tasks}) == 12,
             "fresh fixture set differs")
    for task in tasks:
        _require(task["role"] in ROLES and isinstance(task["prompt"], str)
                 and isinstance(task["expected"], dict) and task["expected"],
                 "fresh task shape differs")
    source = {
        "fixture_sha256": _hash(FIXTURES),
        "module_sha256": _hash(Path(__file__)),
        "suite_id": data["suite_id"],
        "tasks": [{"task_id": t["task_id"], "role": t["role"],
                   "prompt_sha256": sha256_json(t["prompt"]),
                   "grader_sha256": sha256_json(t["expected"])} for t in tasks],
    }
    return data, source


def build_plan(routes):
    _require(isinstance(routes, dict) and set(routes) == set(ENDPOINTS),
             "fresh diagnostic requires exact Qwen and Mia routes")
    for name, route in routes.items():
        _require(isinstance(route, dict) and route.get("served_model") == ENDPOINTS[name]
                 and all(isinstance(route.get(key), str)
                         and re.fullmatch(r"[0-9a-f]{64}", route[key])
                         for key in ("artifact_sha256", "runtime_sha256", "qualification_receipt_sha256")),
                 "fresh route lacks qualified identity")
    _, source = _source()
    cells = []
    for seed in SEEDS:
        for index, task in enumerate(source["tasks"]):
            order = CONDITIONS if index % 2 == 0 else CONDITIONS[::-1]
            for condition in order:
                cells.append({"cell_id": f"fresh/{task['task_id']}/{condition}/seed-{seed}",
                              "task_id": task["task_id"], "role": task["role"],
                              "condition": condition, "seed": seed})
    result = {"schema_version": PLAN_SCHEMA, "suite_id": source["suite_id"],
            "source": source, "routes": copy.deepcopy(routes), "declared_cells": cells,
            "policies": copy.deepcopy(POLICIES), "max_tokens": 4096,
            "cell_timeout_s": CELL_SECONDS, "seed_block_budget_s": BLOCK_SECONDS,
            "comparison_scope": "Qwen27B versus Mia scientific-validity diagnostic, separate from role bundle",
            "promotion_authorized": False}
    result["plan_sha256"] = sha256_json(result)
    return result


def validate_plan(plan):
    _require(isinstance(plan, dict) and plan == build_plan(plan.get("routes")),
             "fresh diagnostic plan/source changed")
    return plan


def _strict_object(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result
    def nonfinite(_):
        raise ValueError("nonfinite JSON value")
    value = json.loads(text, object_pairs_hook=pairs, parse_constant=nonfinite)
    if not isinstance(value, dict):
        raise ValueError("not one JSON object")  # noqa: TRY004 - invalid wire document
    return value


def _matches(value, expected):
    if set(value) != set(expected):
        return False
    for key, wanted in expected.items():
        got = value[key]
        if type(wanted) is int:
            if type(got) is not int or got != wanted:
                return False
        elif type(wanted) is float:
            if type(got) not in (int, float):
                return False
            try:
                if not math.isfinite(got) or abs(got - wanted) > 1e-6:
                    return False
            except (OverflowError, ValueError):
                return False
        elif type(got) is not type(wanted) or got != wanted:
            return False
    return True


def _shape_matches(value, expected):
    if set(value) != set(expected):
        return False
    return all(type(value[key]) in (int, float) if type(wanted) is float
               else type(value[key]) is type(wanted)
               for key, wanted in expected.items())


def grade(content, expected):
    if not isinstance(content, str) or not content.strip():
        return {"passed": False, "failure_code": "empty_content",
                "normalized_envelope_passed": None}
    try:
        value = _strict_object(content)
    except (ValueError, TypeError, RecursionError):
        match = re.fullmatch(r"\s*```(?:json)?[ \t]*\r?\n(.*?)\r?\n```\s*", content, re.DOTALL)
        normalized = None
        if match:
            try:
                normalized = _matches(_strict_object(match.group(1)), expected)
            except (ValueError, TypeError, RecursionError):
                normalized = False
        return {"passed": False, "failure_code": "markdown_envelope" if match else "malformed_json",
                "normalized_envelope_passed": normalized}
    if not _shape_matches(value, expected):
        return {"passed": False, "failure_code": "schema_violation",
                "normalized_envelope_passed": None}
    passed = _matches(value, expected)
    return {"passed": passed, "failure_code": None if passed else "substantive_mistake",
            "normalized_envelope_passed": None}


def run_model(plan, endpoint_name, *, seed_block, output_dir, runtime_budget_s,
              admission_gate, safety_check, work_cutoff_s, cancel_event=None,
              invoke_fn=complete, monotonic=time.monotonic):
    validate_plan(plan)
    _require(endpoint_name in ENDPOINTS and seed_block in SEEDS,
             "fresh route/seed not registered")
    _require(callable(admission_gate) and callable(safety_check) and callable(invoke_fn),
             "fresh diagnostic needs controller admission and monitor")
    _require(type(runtime_budget_s) in (int, float) and runtime_budget_s == BLOCK_SECONDS
             and type(work_cutoff_s) in (int, float) and math.isfinite(work_cutoff_s),
             "fresh block deadline differs")
    if cancel_event is not None:
        _require(callable(getattr(cancel_event, "is_set", None)), "invalid cancellation event")
    admission_gate(plan, endpoint_name)
    started = monotonic()
    _require(work_cutoff_s - started >= runtime_budget_s, "fresh block will not fit")
    deadline = min(work_cutoff_s, started + runtime_budget_s)

    def guarded():
        _require(not (cancel_event and cancel_event.is_set()), "cancelled")
        _require(monotonic() < deadline, "fresh block cutoff")
        _require(safety_check() is None, "unexpected monitor contract")
        _require(not (cancel_event and cancel_event.is_set()), "cancelled")

    guarded()
    data, _ = _source()
    tasks = {task["task_id"]: task for task in data["tasks"]}
    cells = [cell for cell in plan["declared_cells"] if cell["seed"] == seed_block]
    _require(len(cells) == 24, "fresh block task count differs")
    output = harness._output_dir(output_dir)
    output.mkdir(mode=0o700, parents=True)
    run_id = f"{plan['suite_id']}-{endpoint_name}-seed-{seed_block}"
    harness._write_json(output / "plan.json", plan)
    route = plan["routes"][endpoint_name]
    arm = {"routes": [{"role": role, "endpoint_name": endpoint_name,
                        "served_model": route["served_model"],
                        "artifact_sha256": route["artifact_sha256"],
                        "runtime_sha256": route["runtime_sha256"],
                        "policies": plan["policies"]} for role in sorted(ROLES)]}
    outcomes = []
    timing = TimingRecorder()
    observed_invoke = timing.wrap(invoke_fn)
    ordinal = 0
    abort_reason = None
    for cell in cells:
        task = tasks[cell["task_id"]]
        row = {**cell, "status": "not_run", "passed": False,
               "failure_code": None, "calls": [], "private_call_evidence": [], "wall_s": 0.0}
        cell_start = monotonic()
        if abort_reason is None:
            try:
                guarded()
                private = []
                spec = CallSpec(call_index=0, call_id=f"{cell['cell_id']}#0",
                                role=cell["role"], policy_id=cell["condition"],
                                seed=seed_block, max_tokens=plan["max_tokens"],
                                timeout_s=CELL_SECONDS, required=True,
                                messages=({"role": "user", "content": task["prompt"]},))
                call = harness._invoke_call(spec, arm=arm,
                                           deadline=min(deadline, cell_start + CELL_SECONDS),
                                           invoke_fn=observed_invoke, cancel_event=cancel_event,
                                           monotonic=monotonic, evidence_sink=private.append)
                row["status"] = call.status
                row["calls"].append(call.receipt)
                evidence = {**private[0], "run_id": run_id, "cohort": endpoint_name,
                            "cell_id": cell["cell_id"]}
                descriptor = harness._persist_private_call(output, ordinal=ordinal, evidence=evidence)
                ordinal += 1
                row["private_call_evidence"].append(descriptor)
                if call.status == "returned":
                    row.update(grade(call.content, task["expected"]))
                else:
                    row["failure_code"] = call.status
                guarded()
            except Exception as exc:  # noqa: BLE001 - preserve denominator on controller failure
                abort_reason = type(exc).__name__
                row["failure_code"] = "controller_or_evidence_failure"
                row["passed"] = False
        else:
            row["failure_code"] = "prior_block_abort"
        row["wall_s"] = max(0.0, monotonic() - cell_start)
        row["transport_timings"] = timing.for_calls(row["calls"])
        row["grade"] = {
            "passed": row["passed"], "failure_code": row["failure_code"],
            "details": {"normalized_envelope_passed": row.get("normalized_envelope_passed"),
                        "_private_call_evidence": {
                            "schema_version": harness.PRIVATE_INDEX_SCHEMA,
                            "artifacts": row["private_call_evidence"]}},
        }
        outcomes.append(row)
        harness._write_json(output / "checkpoint.json", {
            "schema_version": "flash-fresh-market-canary-checkpoint/v1",
            "run_id": run_id, "recorded_cells": [r["cell_id"] for r in outcomes],
            "promotion_authorized": False})
    complete_block = abort_reason is None and len(outcomes) == 24 and all(
        row["status"] not in {"not_run", "cancelled"} and len(row["private_call_evidence"]) == 1
        for row in outcomes)
    result = {"schema_version": RUN_SCHEMA, "suite_id": plan["suite_id"],
              "run_id": run_id, "endpoint_name": endpoint_name, "seed_block": seed_block,
              "plan_sha256": plan["plan_sha256"], "plan": copy.deepcopy(plan),
              "declared_cells": len(cells), "runtime_budget_s": runtime_budget_s,
              "source": plan["source"],
              "route": route, "status": "complete" if complete_block else "incomplete",
              "outcomes": outcomes, "elapsed_s": max(0.0, monotonic() - started),
              "abort_reason": abort_reason, "restoration_required": True,
              "comparison_eligible": False, "promotion_authorized": False,
              "recorded_at": datetime.now(timezone.utc).isoformat()}
    harness._write_json(output / "run.json", result)
    (output / "checkpoint.json").unlink(missing_ok=True)
    return result
