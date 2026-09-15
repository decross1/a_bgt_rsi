"""Selected failure repairs under an existing supervised model window.

The 22 source tasks and their original graders are frozen before a call. Flash
uses explicit off and medium template controls; the resident Gemma lane uses
its native sampling policy and makes no reasoning-effort claim.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import adapters, harness
from .followon_timing import TimingRecorder, validate_timings
from .manifest import sha256_json
from .transport import complete

BENCHMARK = Path(
    "/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-14/"
    "qwen-flash-next-research/evaluation/window-plans/"
    "qfn-ab-mia-c0-20260915-a.benchmark.json"
)
BENCHMARK_SHA256 = "f7158704acf9df73f46e0fb587cf56d37c5127890dea36b2e56260df103f1991"
PLAN_SCHEMA = "flash-followon-selected-repair-plan/v1"
RUN_SCHEMA = "flash-followon-selected-repair-run/v1"
SUITE_ID = "flash-selected-topic-historical-code-repair-v1-20260915"
FLASH_CEILING = 4_500
RESIDENT_CEILING = 2_500
ENDPOINT_MODELS = {
    "resident_gemma": "gemma-4-26b-a4b",
    "flash_next_mia": "qwen3.8-flash-next-mia",
}
HEX = frozenset("0123456789abcdef")


def _require(ok: bool, reason: str) -> None:
    if not ok:
        raise ValueError(reason)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _source() -> tuple[dict[str, Any], list[adapters.CellDefinition]]:
    raw, actual = harness._read_regular_file(
        BENCHMARK, label="immutable first-pair benchmark", max_bytes=2_000_000,
    )
    _require(actual == BENCHMARK and _sha(raw) == BENCHMARK_SHA256,
             "first-pair benchmark source changed")
    benchmark = json.loads(raw)
    _require(benchmark.get("schema_version") == "flash-next-ab-plan/v1"
             and benchmark.get("promotion_authorized") is False,
             "selected repair source is not the immutable first pair")
    definitions = adapters.load_cells(
        families=("topic", "portfolio", "historical")
    )
    selected = [
        cell for cell in definitions
        if (cell.family == "historical"
            or cell.family == "portfolio" and cell.calls[0].role == "coding"
            or cell.family == "topic" and cell.task_id in {
                "T1", "T2", "T3", "T4", "T5", "T6",
            } and cell.condition.startswith("hypothesis:")
               and cell.seed == 17)
    ]
    _require(len(selected) == 22
             and [cell.family for cell in selected].count("topic") == 12
             and [cell.family for cell in selected].count("historical") == 6
             and [cell.family for cell in selected].count("portfolio") == 4
             and all(cell.cell_id in benchmark["cell_receipts"]
                     and cell.receipt() == benchmark["cell_receipts"][cell.cell_id]
                     for cell in selected),
             "selected task IDs or original adapter receipts changed")
    return benchmark, selected


def _qualified_route(name: str, value: dict[str, Any]) -> None:
    _require(isinstance(value, dict)
             and set(value) == {"served_model", "artifact_sha256",
                                "runtime_sha256", "qualification_receipt_sha256"}
             and value["served_model"] == ENDPOINT_MODELS[name]
             and all(isinstance(value[key], str) and len(value[key]) == 64
                     and set(value[key]) <= HEX
                     for key in ("artifact_sha256", "runtime_sha256",
                                 "qualification_receipt_sha256")),
             "repair route has no exact qualified model identity")


def _original_policy(benchmark: dict, cell: adapters.CellDefinition,
                     *, cohort: str) -> dict[str, Any]:
    arm = next(row for row in benchmark["arms"] if row["cohort"] == cohort)
    original = next(row for row in arm["routes"]
                    if row["role"] == cell.calls[0].role)
    return copy.deepcopy(original["policies"][cell.calls[0].policy_id])


def _policy(base: dict[str, Any], lane: str) -> dict[str, Any]:
    sampling = {key: value for key, value in base.items()
                if key not in {"reasoning_effort", "enable_thinking"}}
    if lane == "flash_off":
        sampling["enable_thinking"] = False
    elif lane == "flash_medium":
        sampling["enable_thinking"] = True
        sampling["reasoning_effort"] = "medium"
    return sampling


def freeze_plan(routes: dict[str, dict[str, Any]], *,
                candidate_variant_id: str) -> dict[str, Any]:
    _require(isinstance(routes, dict) and set(routes) == set(ENDPOINT_MODELS),
             "selected repair requires exact resident and Flash routes")
    for name, value in routes.items():
        _qualified_route(name, value)
    _require(isinstance(candidate_variant_id, str)
             and candidate_variant_id.startswith("mia-"),
             "selected repair candidate identity is absent")
    benchmark, selected = _source()
    cells: list[dict[str, Any]] = []
    policies: dict[str, dict[str, Any]] = {}
    for ordinal, cell in enumerate(selected):
        original = cell.calls[0]
        for lane in ("resident_native", "flash_off", "flash_medium"):
            endpoint = ("resident_gemma" if lane == "resident_native"
                        else "flash_next_mia")
            policy_id = f"selected-{ordinal:02d}-{lane}"
            base = _original_policy(
                benchmark, cell,
                cohort="resident" if lane == "resident_native" else "flash",
            )
            policies[policy_id] = _policy(base, lane)
            repair_id = f"selected/{ordinal:02d}/{lane}/{cell.cell_id}"
            cells.append({
                "repair_cell_id": repair_id, "original_cell_id": cell.cell_id,
                "endpoint_name": endpoint, "lane": lane,
                "policy_id": policy_id, "role": original.role,
                "seed": original.seed, "max_tokens": original.max_tokens,
                "timeout_s": original.timeout_s,
                "messages_sha256": sha256_json(list(original.messages)),
                "tools_sha256": sha256_json(list(original.tools)),
                "source_receipt_sha256": sha256_json(cell.receipt()),
            })
    # Alternate off/medium order within each task instead of always giving
    # one condition the warm-cache or early-window position.
    flash_cells = [row for ordinal in range(22)
                   for row in (cells[3*ordinal+1:3*ordinal+3]
                               if ordinal % 2 == 0 else
                               cells[3*ordinal+1:3*ordinal+3][::-1])]
    resident_cells = cells[::3]
    plan = {
        "schema_version": PLAN_SCHEMA, "suite_id": SUITE_ID,
        "benchmark_source_path": str(BENCHMARK),
        "benchmark_source_sha256": BENCHMARK_SHA256,
        "candidate_variant_id": candidate_variant_id,
        "routes": copy.deepcopy(routes), "policies": policies,
        "declared_cells": {
            "resident_gemma": resident_cells,
            "flash_next_mia": flash_cells,
        },
        "block_ceilings": {
            "resident_gemma": RESIDENT_CEILING,
            "flash_next_mia": FLASH_CEILING,
        },
        "matched_interpretation": "same source prompts, seeds, caps and original graders; model-native sampling and checkpoint differ",
        "medium_interpretation": "Flash-only exploratory template-policy control",
        "timeouts_are_measured_failures": True,
        "comparison_eligible": False, "promotion_authorized": False,
    }
    plan["plan_sha256"] = sha256_json(plan)
    return plan


def validate_plan(plan: dict[str, Any]) -> dict[str, Any]:
    _require(isinstance(plan, dict)
             and plan == freeze_plan(plan.get("routes", {}),
                                     candidate_variant_id=plan.get("candidate_variant_id")),
             "selected repair source, route or policies changed")
    return plan


def run_model(plan: dict[str, Any], *, endpoint_name: str,
              seed_block: None, output_dir: Path, runtime_budget_s: int,
              admission_gate, safety_check, work_cutoff_s: float,
              cancel_event=None, invoke_fn=complete,
              monotonic=time.monotonic) -> dict[str, Any]:
    validate_plan(plan)
    _require(endpoint_name in ENDPOINT_MODELS and seed_block is None
             and runtime_budget_s == plan["block_ceilings"][endpoint_name]
             and callable(admission_gate) and callable(safety_check)
             and callable(invoke_fn) and type(work_cutoff_s) in {int, float}
             and math.isfinite(work_cutoff_s),
             "selected repair lacks a frozen endpoint or armed controller")
    admission_gate(plan, endpoint_name)
    started = monotonic()
    _require(work_cutoff_s - started >= runtime_budget_s,
             "selected repair cannot fit before restoration")
    deadline = min(work_cutoff_s, started + runtime_budget_s)
    output = harness._output_dir(output_dir)
    output.mkdir(mode=0o700, parents=True)
    harness._write_json(output / "plan.json", plan)
    definitions = {cell.cell_id: cell for cell in _source()[1]}
    route = plan["routes"][endpoint_name]
    roles = {row["role"] for row in plan["declared_cells"][endpoint_name]}
    arm = {"routes": [{
        "role": role, "endpoint_name": endpoint_name,
        "served_model": route["served_model"],
        "artifact_sha256": route["artifact_sha256"],
        "runtime_sha256": route["runtime_sha256"],
        "policies": plan["policies"],
    } for role in sorted(roles)]}
    timing = TimingRecorder()
    observed_invoke = timing.wrap(invoke_fn)
    outcomes = []
    abort_reason = None
    private_ordinal = 0
    run_id = f"{SUITE_ID}-{endpoint_name}"

    def guarded() -> None:
        _require(not (cancel_event and cancel_event.is_set())
                 and monotonic() < deadline, "selected repair cancelled or cut off")
        _require(safety_check() is None,
                 "selected repair monitor returned an unexpected value")

    for frozen in plan["declared_cells"][endpoint_name]:
        cell_start = monotonic()
        row = {"repair_cell_id": frozen["repair_cell_id"],
               "original_cell_id": frozen["original_cell_id"],
               "lane": frozen["lane"], "endpoint_name": endpoint_name,
               "status": "not_run", "passed": False, "failure_code": None,
               "calls": [], "private_call_evidence": [], "grade_details_sha256": None}
        if abort_reason is None:
            evidence: list[dict[str, Any]] = []
            try:
                guarded()
                original = definitions[frozen["original_cell_id"]]
                original_call = original.calls[0]
                call = replace(
                    original_call, call_id=f"{frozen['repair_cell_id']}#0",
                    policy_id=frozen["policy_id"],
                )
                selected = replace(
                    original, cell_id=frozen["repair_cell_id"],
                    condition=frozen["lane"], calls=(call,),
                )

                def invoke(spec, _evidence=evidence):
                    guarded()
                    return harness._invoke_call(
                        spec, arm=arm,
                        deadline=min(deadline, monotonic() + spec.timeout_s),
                        invoke_fn=observed_invoke,
                        cancel_event=cancel_event, monotonic=monotonic,
                        evidence_sink=_evidence.append,
                    )

                graded = adapters.execute_cell(selected, invoke)
                row["calls"] = [call.receipt for call in graded.calls]
                row["status"] = graded.calls[0].status
                row["passed"] = graded.passed
                row["failure_code"] = graded.failure_code
                row["grade_details_sha256"] = sha256_json(graded.details)
                guarded()
            except Exception as exc:  # noqa: BLE001 - a controller/grade fault aborts restoration
                abort_reason = type(exc).__name__
                row["failure_code"] = "controller_or_grader_failure"
            finally:
                for private in evidence:
                    descriptor = harness._persist_private_call(
                        output, ordinal=private_ordinal,
                        evidence={**private, "run_id": run_id,
                                  "cohort": endpoint_name,
                                  "cell_id": frozen["repair_cell_id"]},
                    )
                    private_ordinal += 1
                    row["private_call_evidence"].append(descriptor)
        else:
            row["failure_code"] = "prior_block_abort"
        row["wall_s"] = max(0.0, monotonic() - cell_start)
        row["transport_timings"] = timing.for_calls(row["calls"])
        row["grade"] = {
            "grader_id": "selected:original-task-grader",
            "passed": row["passed"], "failure_code": row["failure_code"],
            "details": {"original_grader_details_sha256":
                        row["grade_details_sha256"],
                        "_private_call_evidence": {
                            "schema_version": harness.PRIVATE_INDEX_SCHEMA,
                            "artifacts": row["private_call_evidence"],
                        }},
        }
        outcomes.append(row)
        harness._write_json(output / "progress.json", {
            "run_id": run_id, "recorded_cells": len(outcomes),
            "abort_reason": abort_reason, "promotion_authorized": False,
        })
    complete = (abort_reason is None
                and len(outcomes) == len(plan["declared_cells"][endpoint_name])
                and all(row["status"] not in {"not_run", "cancelled"}
                        and len(row["calls"]) == 1
                        and len(row["private_call_evidence"]) == 1
                        for row in outcomes))
    result = {
        "schema_version": RUN_SCHEMA, "suite_id": SUITE_ID,
        "run_id": run_id, "endpoint_name": endpoint_name,
        "plan_sha256": plan["plan_sha256"], "plan": copy.deepcopy(plan),
        "declared_cells": len(plan["declared_cells"][endpoint_name]),
        "status": "complete" if complete else "incomplete",
        "outcomes": outcomes, "abort_reason": abort_reason,
        "runtime_budget_s": runtime_budget_s,
        "elapsed_s": max(0.0, monotonic() - started),
        "summary": {
            "attempted": sum(row["status"] != "not_run" for row in outcomes),
            "passed": sum(row["passed"] is True for row in outcomes),
            "timeouts": sum(row["status"] == "timeout" for row in outcomes),
        },
        "restoration_required": True, "comparison_eligible": False,
        "promotion_authorized": False,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    harness._write_json(output / "run.json", result)
    validate_run(result, plan, endpoint_name)
    return result


def validate_run(result: dict[str, Any], plan: dict[str, Any],
                 endpoint_name: str) -> None:
    validate_plan(plan)
    expected = plan["declared_cells"][endpoint_name]
    _require(result.get("schema_version") == RUN_SCHEMA
             and result.get("plan") == plan
             and result.get("plan_sha256") == plan["plan_sha256"]
             and result.get("endpoint_name") == endpoint_name
             and result.get("declared_cells") == len(expected)
             and result.get("runtime_budget_s")
                == plan["block_ceilings"][endpoint_name]
             and result.get("comparison_eligible") is False
             and result.get("promotion_authorized") is False,
             "selected repair run identity differs from its frozen source")
    rows = result.get("outcomes")
    _require(isinstance(rows, list) and len(rows) == len(expected),
             "selected repair omitted a declared denominator cell")
    for frozen, row in zip(expected, rows, strict=True):
        calls = row.get("calls")
        _require(row.get("repair_cell_id") == frozen["repair_cell_id"]
                 and row.get("original_cell_id") == frozen["original_cell_id"]
                 and row.get("lane") == frozen["lane"]
                 and row.get("endpoint_name") == endpoint_name
                 and isinstance(calls, list) and len(calls) <= 1,
                 "selected repair changed cell order or call count")
        if calls:
            call = calls[0]
            _require(call.get("call_id") == f"{frozen['repair_cell_id']}#0"
                     and call.get("role") == frozen["role"]
                     and call.get("endpoint_name") == endpoint_name
                     and call.get("served_model")
                        == plan["routes"][endpoint_name]["served_model"]
                     and call.get("artifact_sha256")
                        == plan["routes"][endpoint_name]["artifact_sha256"]
                     and call.get("policy_id") == frozen["policy_id"]
                     and call.get("resolved_policy_sha256")
                        == sha256_json(plan["policies"][frozen["policy_id"]])
                     and call.get("seed") == frozen["seed"]
                     and call.get("max_tokens") == frozen["max_tokens"]
                     and call.get("messages_sha256")
                        == frozen["messages_sha256"]
                     and call.get("tools_sha256") == frozen["tools_sha256"]
                     and 0 < call.get("timeout_s", 0) <= frozen["timeout_s"],
                     "selected repair call differs from its planned route/policy")
            validate_timings(calls, row.get("transport_timings"))
    if result.get("status") == "complete":
        _require(all(len(row["calls"]) == 1
                     and len(row.get("private_call_evidence", [])) == 1
                     and row["status"] in {"returned", "timeout", "error"}
                     for row in rows),
                 "selected repair complete run omitted attempted evidence")
