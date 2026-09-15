"""Prospective four-task coding/patch diagnostic under a v5 supervised window.

This preserves original task prompts and graders from the immutable first pair.
Only the registered model sampling policy, output cap and call timeout differ.
The controller owns admission, host/cgroup monitoring, cancellation and restore.
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
from . import followon_selected_repair as original
from .followon_profiles import MIA_MTP3_REDUCED47K_OPT, SPECS_BY_ID, is_registered_spec
from .followon_timing import TimingRecorder, validate_timings
from .manifest import sha256_json
from .transport import complete

PROTOCOL_SHA256 = "8dfb32bae0192271b696026438fb3e0610d34f265308dadf8da4247cff5285f5"
PLAN_SCHEMA = "flash-followon-coding-temp1-plan/v1"
RUN_SCHEMA = "flash-followon-coding-temp1-run/v1"
STUDY_ID = "coding-temp1-medium-and-decode-v1"
KIND = "coding_temp1_medium"
ENDPOINT = "flash_next_mia"
CEILING_S = 1560
CALL_TIMEOUT_S = 360
MAX_TOKENS = 8192
POLICY_ID = "prospective-temp1-medium"
POLICY = {"temperature": 1, "top_p": 0.95, "top_k": 20,
          "enable_thinking": True, "reasoning_effort": "medium"}
ORDER = (
    "portfolio/CODE-D075-DELEGATION-001/policy-A-critic_current/seed-0",
    "portfolio/CODE-GT-REGRET-001/policy-A-critic_current/seed-0",
    "historical/HCP-001/matched/seed-20260914",
    "historical/HCP-002/matched/seed-20260914",
)


def _require(ok: bool, reason: str) -> None:
    if not ok:
        raise ValueError(reason)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _protocol() -> dict[str, Any]:
    path = Path(__file__).absolute().with_name("CODING_TEMP1_PROTOCOL.json")
    raw, actual = harness._read_regular_file(
        path, label="prospective coding protocol", max_bytes=16_000)
    _require(actual == path and _sha(raw) == PROTOCOL_SHA256,
             "prospective coding protocol raw bytes changed")
    document = json.loads(raw)
    _require(document.get("schema") == "flash-followon-coding-temp1-protocol/v1"
             and document.get("study_id") == STUDY_ID
             and tuple(document.get("ordered_original_cell_ids", [])) == ORDER
             and document.get("sampling_policy") == POLICY
             and document.get("call_caps") == {
                 "maximum_calls": 4, "max_output_tokens_per_call": MAX_TOKENS,
                 "timeout_seconds_per_call": CALL_TIMEOUT_S,
                 "block_budget_seconds": CEILING_S,
             }
             and document.get("comparison_eligible") is False
             and document.get("promotion_authorized") is False,
             "prospective coding protocol shape changed")
    return document


def _definitions() -> tuple[dict, list[adapters.CellDefinition]]:
    benchmark, selected = original._source()  # First-126 raw SHA/task receipts.
    available = {cell.cell_id: cell for cell in selected}
    _require(all(cell_id in available for cell_id in ORDER),
             "four original coding/patch tasks are unavailable")
    cells = [available[cell_id] for cell_id in ORDER]
    _require([cell.family for cell in cells] == ["portfolio", "portfolio",
                                                 "historical", "historical"]
             and all(len(cell.calls) == 1 and cell.calls[0].role == "coding"
                     for cell in cells)
             and all(cell.receipt() == benchmark["cell_receipts"][cell.cell_id]
                     for cell in cells),
             "original coding prompts or graders differ from first pair")
    return benchmark, cells


def freeze_plan(route: dict[str, Any], *, candidate_variant_id: str) -> dict:
    """Freeze four original cells and a separately qualified literal v5 route."""
    _protocol()
    spec = SPECS_BY_ID.get(candidate_variant_id)
    _require(spec is MIA_MTP3_REDUCED47K_OPT
             and is_registered_spec(spec)
             and spec.endpoint_name == ENDPOINT,
             "prospective coding requires the admitted optimized reduced MTP3 literal")
    original._qualified_route(ENDPOINT, route)
    _require(route["served_model"] == spec.served_name
             and route["artifact_sha256"] == spec.model_artifact_sha256(),
             "prospective coding route differs from qualified literal")
    _benchmark, cells = _definitions()
    declared = []
    for ordinal, cell in enumerate(cells):
        source = cell.calls[0]
        declared.append({
            "ordinal": ordinal,
            "diagnostic_cell_id": f"coding-temp1/{ordinal:02d}/{cell.cell_id}",
            "original_cell_id": cell.cell_id,
            "family": cell.family, "role": "coding",
            "seed": source.seed,
            "messages_sha256": sha256_json(list(source.messages)),
            "tools_sha256": sha256_json(list(source.tools)),
            "original_receipt_sha256": sha256_json(cell.receipt()),
            "policy_id": POLICY_ID,
            "max_tokens": MAX_TOKENS,
            "timeout_s": CALL_TIMEOUT_S,
        })
    plan = {
        "schema_version": PLAN_SCHEMA, "study_id": STUDY_ID,
        "protocol_sha256": PROTOCOL_SHA256,
        "immutable_first_pair_benchmark_sha256": original.BENCHMARK_SHA256,
        "candidate_variant_id": spec.spec_id,
        "candidate_spec_sha256": spec.identity_sha256(),
        "endpoint_name": ENDPOINT,
        "route": copy.deepcopy(route),
        "policy_id": POLICY_ID, "policy": copy.deepcopy(POLICY),
        "declared_cells": declared,
        "caps": {"maximum_calls": 4, "max_output_tokens_per_call": MAX_TOKENS,
                 "timeout_seconds_per_call": CALL_TIMEOUT_S,
                 "block_budget_seconds": CEILING_S},
        "task_order_frozen_before_scores": True,
        "original_tasks_and_graders_unchanged": True,
        "timeouts_are_measured_failures": True,
        "sampling_change_is_prospective_diagnostic": True,
        "comparison_eligible": False, "promotion_authorized": False,
        "scientific_novelty_claim": False, "trading_claim_authorized": False,
    }
    plan["plan_sha256"] = sha256_json(plan)
    return plan


def validate_plan(plan: dict) -> dict:
    _require(isinstance(plan, dict) and plan.get("schema_version") == PLAN_SCHEMA,
             "coding plan schema differs")
    expected = freeze_plan(plan.get("route"),
                           candidate_variant_id=plan.get("candidate_variant_id"))
    _require(plan == expected, "coding tasks, grader, policy or route drifted")
    return plan


def run_model(plan: dict, *, endpoint_name: str, seed_block: None,
              output_dir: str | Path, runtime_budget_s: float,
              admission_gate, safety_check, work_cutoff_s: float,
              cancel_event=None, invoke_fn=complete,
              monotonic=time.monotonic) -> dict:
    validate_plan(plan)
    _require(endpoint_name == ENDPOINT and seed_block is None
             and runtime_budget_s == CEILING_S
             and callable(admission_gate) and callable(safety_check)
             and callable(invoke_fn)
             and type(work_cutoff_s) in {int, float}
             and math.isfinite(work_cutoff_s),
             "coding block lacks the exact qualified route or controller")
    admission_gate(plan, endpoint_name)
    started = monotonic()
    _require(work_cutoff_s - started >= CEILING_S,
             "coding block cannot fit before restoration cutoff")
    deadline = min(work_cutoff_s, started + CEILING_S)
    output = harness._output_dir(output_dir)
    output.mkdir(mode=0o700, parents=True)
    harness._write_json(output / "plan.json", plan)
    _, definitions = _definitions()
    by_id = {cell.cell_id: cell for cell in definitions}
    route = plan["route"]
    arm = {"cohort": "flash", "routes": [{
        "role": "coding", "endpoint_name": ENDPOINT,
        "served_model": route["served_model"],
        "artifact_sha256": route["artifact_sha256"],
        "runtime_sha256": route["runtime_sha256"],
        "policies": {POLICY_ID: POLICY},
    }]}
    recorder = TimingRecorder()
    measured = recorder.wrap(invoke_fn)
    outcomes = []
    abort_reason = None
    private_ordinal = 0

    def guarded() -> None:
        _require(not (cancel_event and cancel_event.is_set())
                 and monotonic() < deadline
                 and safety_check() is None,
                 "coding block canceled, cut off or monitor breached")

    for frozen in plan["declared_cells"]:
        before = monotonic()
        row = {
            "diagnostic_cell_id": frozen["diagnostic_cell_id"],
            "original_cell_id": frozen["original_cell_id"],
            "family": frozen["family"], "endpoint_name": ENDPOINT,
            "status": "not_run", "passed": False, "failure_code": None,
            "calls": [], "private_call_evidence": [],
            "grader_details_sha256": None,
        }
        evidence = []
        if abort_reason is None:
            try:
                guarded()
                original_cell = by_id[frozen["original_cell_id"]]
                call = replace(
                    original_cell.calls[0],
                    call_id=f"{frozen['diagnostic_cell_id']}#0",
                    policy_id=POLICY_ID,
                    max_tokens=MAX_TOKENS,
                    timeout_s=CALL_TIMEOUT_S,
                )
                diagnostic = replace(
                    original_cell, cell_id=frozen["diagnostic_cell_id"],
                    condition="prospective-temp1-medium", calls=(call,),
                )

                def invoke(spec, evidence_sink=evidence.append):
                    guarded()
                    return harness._invoke_call(
                        spec, arm=arm,
                        deadline=min(deadline, monotonic() + CALL_TIMEOUT_S),
                        invoke_fn=measured, cancel_event=cancel_event,
                        monotonic=monotonic, evidence_sink=evidence_sink,
                    )

                graded = adapters.execute_cell(diagnostic, invoke)
                row["calls"] = [item.receipt for item in graded.calls]
                row["status"] = graded.calls[0].status
                row["passed"] = graded.passed
                row["failure_code"] = graded.failure_code
                row["grader_details_sha256"] = sha256_json(graded.details)
                guarded()
            except Exception as exc:  # noqa: BLE001 - stop after any grader/monitor fault.
                abort_reason = type(exc).__name__
                row["failure_code"] = "controller_or_grader_failure"
            finally:
                for private in evidence:
                    descriptor = harness._persist_private_call(
                        output, ordinal=private_ordinal,
                        evidence={**private, "run_id": STUDY_ID,
                                  "cohort": ENDPOINT,
                                  "cell_id": frozen["diagnostic_cell_id"]},
                    )
                    private_ordinal += 1
                    row["private_call_evidence"].append(descriptor)
        else:
            row["failure_code"] = "prior_block_abort"
        row["wall_s"] = max(0.0, monotonic() - before)
        row["transport_timings"] = recorder.for_calls(row["calls"])
        row["grade"] = {
            "grader_id": "original-portfolio-or-historical",
            "passed": row["passed"], "failure_code": row["failure_code"],
            "details": {"original_grader_details_sha256": row["grader_details_sha256"],
                        "_private_call_evidence": {
                            "schema_version": harness.PRIVATE_INDEX_SCHEMA,
                            "artifacts": row["private_call_evidence"]}},
        }
        outcomes.append(row)
        harness._write_json(output / "progress.json", {
            "study_id": STUDY_ID, "recorded_cells": len(outcomes),
            "abort_reason": abort_reason, "promotion_authorized": False,
        })
    complete = (abort_reason is None and len(outcomes) == 4
                and all(row["status"] in {"returned", "timeout", "error"}
                        and len(row["calls"]) == 1
                        and len(row["private_call_evidence"]) == 1
                        for row in outcomes))
    result = {
        "schema_version": RUN_SCHEMA, "study_id": STUDY_ID,
        "plan": copy.deepcopy(plan), "plan_sha256": plan["plan_sha256"],
        "endpoint_name": ENDPOINT, "candidate_variant_id": plan["candidate_variant_id"],
        "declared_cells": 4, "status": "complete" if complete else "incomplete",
        "outcomes": outcomes, "abort_reason": abort_reason,
        "runtime_budget_s": runtime_budget_s,
        "elapsed_s": max(0.0, monotonic() - started),
        "summary": {
            "attempted": sum(row["status"] != "not_run" for row in outcomes),
            "passed": sum(row["passed"] is True for row in outcomes),
            "timeouts": sum(row["status"] == "timeout" for row in outcomes),
        },
        "restoration_required": True, "comparison_eligible": False,
        "promotion_authorized": False, "trading_claim_authorized": False,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    harness._write_json(output / "run.json", result)
    validate_run(result, plan, ENDPOINT)
    return result


def validate_run(result: dict, plan: dict, endpoint_name: str) -> None:
    validate_plan(plan)
    rows = result.get("outcomes")
    _require(endpoint_name == ENDPOINT
             and result.get("schema_version") == RUN_SCHEMA
             and result.get("plan") == plan
             and result.get("plan_sha256") == plan["plan_sha256"]
             and result.get("endpoint_name") == ENDPOINT
             and result.get("candidate_variant_id") == plan["candidate_variant_id"]
             and result.get("declared_cells") == 4
             and result.get("runtime_budget_s") == CEILING_S
             and result.get("comparison_eligible") is False
             and result.get("promotion_authorized") is False
             and isinstance(rows, list) and len(rows) == 4,
             "coding run identity or denominator differs")
    route = plan["route"]
    for frozen, row in zip(plan["declared_cells"], rows, strict=True):
        calls = row.get("calls")
        _require(row.get("diagnostic_cell_id") == frozen["diagnostic_cell_id"]
                 and row.get("original_cell_id") == frozen["original_cell_id"]
                 and row.get("family") == frozen["family"]
                 and row.get("endpoint_name") == ENDPOINT
                 and isinstance(calls, list) and len(calls) <= 1,
                 "coding task identity/order or call count changed")
        grade = row.get("grade")
        details = grade.get("details") if isinstance(grade, dict) else None
        private = row.get("private_call_evidence")
        _require(isinstance(grade, dict) and isinstance(details, dict)
                 and grade.get("passed") is row.get("passed")
                 and grade.get("failure_code") == row.get("failure_code")
                 and details.get("original_grader_details_sha256")
                    == row.get("grader_details_sha256")
                 and isinstance(private, list) and len(private) == len(calls)
                 and details.get("_private_call_evidence") == {
                     "schema_version": harness.PRIVATE_INDEX_SCHEMA,
                     "artifacts": private,
                 },
                 "coding grade/private index differs from its public outcome")
        if calls:
            call = calls[0]
            descriptor = private[0]
            _require(call.get("call_id") == f"{frozen['diagnostic_cell_id']}#0"
                     and call.get("role") == "coding"
                     and call.get("endpoint_name") == ENDPOINT
                     and call.get("served_model") == route["served_model"]
                     and call.get("artifact_sha256") == route["artifact_sha256"]
                     and call.get("policy_id") == POLICY_ID
                     and call.get("resolved_policy_sha256") == sha256_json(POLICY)
                     and call.get("seed") == frozen["seed"]
                     and call.get("messages_sha256") == frozen["messages_sha256"]
                     and call.get("tools_sha256") == frozen["tools_sha256"]
                     and call.get("max_tokens") == MAX_TOKENS
                     and type(call.get("timeout_s")) in {int, float}
                     and math.isfinite(call["timeout_s"])
                     and 0 < call["timeout_s"] <= CALL_TIMEOUT_S
                     and call.get("status") in {"returned", "timeout", "error"},
                     "coding call differs from exact task/policy/cap")
            _require(row.get("status") == call.get("status")
                     and (call.get("status") == "returned" or row.get("passed") is False)
                     and isinstance(descriptor, dict)
                     and descriptor.get("call_id") == call.get("call_id")
                     and descriptor.get("status") == call.get("status"),
                     "coding outcome/private call status changed")
            validate_timings(calls, row.get("transport_timings"))
        else:
            _require(row.get("status") == "not_run" and not private,
                     "coding unattempted outcome claims a call")
    summary = result.get("summary")
    _require(isinstance(summary, dict)
             and summary.get("attempted")
                == sum(row.get("status") != "not_run" for row in rows)
             and summary.get("passed")
                == sum(row.get("passed") is True for row in rows)
             and summary.get("timeouts")
                == sum(row.get("status") == "timeout" for row in rows),
             "coding public summary differs from four outcome rows")
    if result.get("status") == "complete":
        _require(result.get("abort_reason") is None
                 and all(len(row["calls"]) == 1
                     and len(row.get("private_call_evidence", [])) == 1
                     for row in rows)
                 and summary.get("attempted") == 4,
                 "complete coding block omitted a planned attempted call")
