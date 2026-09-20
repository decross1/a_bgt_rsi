"""Offline authentication and regrading of complete v2 engineering bundles.

Replay reads retained evidence and recomputes pure checks. It does not contact
any model, acquire the serving lease, resume a run, or execute a local tool.
Digests establish bundle consistency, not an independent timestamp or signer.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import math
from pathlib import Path
from typing import Any

from experiments.payoff_tool_arithmetic import flash_resident as resident

from . import contract as core
from . import design, runner, wire

require = design.require
_RUN_KEYS = {
    "plan_claim",
    "schema_version",
    "status",
    "study_id",
    "cohort",
    "plan_raw_sha256",
    "source_sha256",
    "runtime_binding",
    "core_contract",
    "continuation_policy",
    "declared_units",
    "declared_conditions",
    "declared_slots",
    "slots",
    "outcomes",
    "accounting",
    "contention_observation",
    "resource_observations",
    "abort_reason",
    "elapsed_s",
    "weekly_two_hour_debit",
    "permanently_excluded",
    "scientific_admission_eligible",
    "scientific_admission_registered",
    "confirmation_authorized",
    "production_change_authorized",
    "promotion_authorized",
    "claim_limit",
    "private_content_exported",
}
_OUTCOME_KEYS = {
    "condition_id",
    "cell_id",
    "arm",
    "calls",
    "classification",
    "execution",
    "continuation_policy",
    "continuation_messages_sha256",
    "final_issued",
    "final_grade",
    "protocol",
}
_SLOT_KEYS = {
    "slot_id",
    "disposition",
    "status",
    "failure_code",
    "dispatch_state",
    "call",
    "private_descriptor",
}


def same(actual: Any, expected: Any, label: str) -> None:
    require(design.canonical(actual) == design.canonical(expected), f"{label} differs")


def _number(value: Any) -> bool:
    return type(value) in {int, float} and math.isfinite(value) and value >= 0


def _execution(
    value: dict, classification: core.ToolTurnClassification, arm: str, cell: dict
) -> core.ExecutionOutcome:
    require(
        type(value) is dict
        and set(value) == {f.name for f in dataclasses.fields(core.ExecutionOutcome)},
        "execution record shape differs",
    )
    result = runner.execution_from_record(value)
    require(
        result.schema_version == core.CONTRACT_VERSION
        and result.execution_attempted is True
        and result.source_binding_sha256 == classification.execution_binding_sha256,
        "execution binding differs",
    )
    require(
        result.execution_succeeded in {core.PASS, core.FAIL}
        and result.result_contract_valid in {core.PASS, core.FAIL, core.UNASSESSED},
        "execution assessment differs",
    )
    if result.retained_result_json_utf8 is not None:
        raw = result.retained_result_json_utf8
        require(
            type(raw) is bytes and len(raw) <= 1_000_000,
            "retained result byte bound differs",
        )
        expected_raw = json.dumps(
            result.retained_result,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        require(
            raw == expected_raw and design.sha(raw) == result.retained_result_sha256,
            "retained result bytes/digest differ",
        )
    else:
        require(
            result.retained_result is None and result.retained_result_sha256 is None,
            "result missing bytes but contains values",
        )
    if result.execution_succeeded == core.PASS:
        require(
            result.result_contract_valid == core.PASS
            and result.failure_code is None
            and result.error_type is None
            and result.retained_result_json_utf8 is not None,
            "successful execution fields differ",
        )
        require(
            design.result_validator_for(arm)(
                result.retained_result, classification.parsed_arguments
            )
            is True,
            "retained result fails pure validation",
        )
        if arm == "calculator":
            same(
                result.retained_result,
                cell["expected_probe"],
                "retained calculator arithmetic",
            )
    else:
        allowed = {
            "tool_execution_error": (core.UNASSESSED, False, True),
            "tool_result_not_finite_json": (core.FAIL, False, True),
            "tool_result_validator_error": (core.FAIL, True, True),
            "tool_result_contract_invalid": (core.FAIL, True, False),
        }
        require(result.failure_code in allowed, "execution failure code differs")
        assessment, retained, error = allowed[result.failure_code]
        require(
            result.result_contract_valid == assessment
            and (result.retained_result_json_utf8 is not None) is retained
            and (
                (type(result.error_type) is str and bool(result.error_type))
                if error
                else result.error_type is None
            ),
            "failed execution fields differ",
        )
        if result.failure_code == "tool_result_contract_invalid":
            require(
                design.result_validator_for(arm)(
                    result.retained_result, classification.parsed_arguments
                )
                is False,
                "claimed invalid tool result passes validation",
            )
    return result


def _resource_checks(run: dict, issued: list[dict]) -> None:
    resident._validate_idle_observation(run["contention_observation"])
    require(
        run["contention_observation"]["observed_idle"] is True,
        "run began with busy endpoint",
    )
    observations = run["resource_observations"]
    require(
        type(observations) is list
        and len(observations) in {2 * len(issued), 2 * len(issued) + 1},
        "resource observation denominator differs",
    )
    last_elapsed = 0.0
    for index, observation in enumerate(observations):
        require(
            type(observation) is dict
            and set(observation)
            == {
                "stage",
                "slot_id",
                "ready",
                "memory_gib",
                "runtime_identity_matches",
                "elapsed_s",
                "error",
            },
            "resource observation shape differs",
        )
        require(
            _number(observation["elapsed_s"])
            and last_elapsed <= observation["elapsed_s"] <= run["elapsed_s"],
            "resource clock differs",
        )
        last_elapsed = observation["elapsed_s"]
        require(
            observation["ready"] is None or type(observation["ready"]) is bool,
            "readiness type differs",
        )
        require(
            observation["runtime_identity_matches"] is None
            or type(observation["runtime_identity_matches"]) is bool,
            "runtime match type differs",
        )
        require(
            observation["memory_gib"] is None or _number(observation["memory_gib"]),
            "memory observation differs",
        )
        require(
            observation["error"] is None or type(observation["error"]) is str,
            "resource error type differs",
        )
        healthy = (
            observation["ready"] is True
            and observation["runtime_identity_matches"] is True
            and observation["error"] is None
            and observation["memory_gib"] is not None
            and observation["memory_gib"] >= design.MEMORY_FLOOR_GIB
        )
        if index < 2 * len(issued):
            slot = issued[index // 2]
            require(
                observation["slot_id"] == slot["slot_id"]
                and observation["stage"]
                == ("pre_call" if index % 2 == 0 else "post_call"),
                "resource/call order differs",
            )
            if (
                index % 2 == 0
                or index < 2 * len(issued) - 1
                or run["status"] == "complete"
            ):
                require(healthy, "issued call lacks healthy resource observation")
        else:
            require(
                run["status"] == "aborted"
                and observation["stage"] == "pre_call"
                and observation["slot_id"] in run["declared_slots"]
                and observation["slot_id"] not in {s["slot_id"] for s in issued},
                "extra resource observation is not an unissued abort",
            )


def _abort_check(run: dict, issued: list[dict]) -> None:
    if run["status"] == "complete":
        return
    reason = run["abort_reason"]
    observations = run["resource_observations"]
    last = observations[-1] if observations else None
    final_call = issued[-1] if issued else None
    unissued = run["accounting"]["unissued_after_abort"] > 0
    extra_pre = len(observations) == 2 * len(issued) + 1
    # Local executor failure is recorded after the post-wire checks and takes
    # precedence over a simultaneous transport/resource cancellation boundary.
    failures = [
        o
        for o in run["outcomes"]
        if o["execution"] and o["execution"]["execution_succeeded"] == core.FAIL
    ]
    if failures:
        require(
            len(failures) == 1
            and final_call is not None
            and unissued
            and not extra_pre,
            "execution abort has an impossible boundary",
        )
        failure = failures[0]
        same(
            reason,
            f"{failure['execution']['failure_code']}:{failure['condition_id']}",
            "execution abort reason",
        )
        require(
            final_call["slot_id"]
            == failure["condition_id"]
            .replace("/table", "/table_first")
            .replace("/calculator", "/calculator_first"),
            "execution abort is detached from last call",
        )
        return

    def resource_reason(observation, before: bool, sid: str = ""):
        suffix = "_before_next_call" if before else f"_after_call:{sid}"
        if observation["error"] is not None:
            return "runtime_probe_failed" + suffix
        if observation["ready"] is not True:
            return "Flash_not_ready" + suffix
        if (
            observation["memory_gib"] is None
            or observation["memory_gib"] < design.MEMORY_FLOOR_GIB
        ):
            return "memory_floor" + suffix
        if observation["runtime_identity_matches"] is not True:
            return "runtime_identity_changed" + suffix
        return None

    if extra_pre:
        require(
            unissued and last["stage"] == "pre_call", "pre-call abort boundary differs"
        )
        trigger = resource_reason(last, True)
        if trigger is not None:
            same(reason, trigger, "pre-call abort precedence")
            return
        allowed = {"cancelled_after_pre_call_probes"}
        if run["elapsed_s"] >= design.EVALUATOR_BUDGET_S - design.CALL_TIMEOUT_S - 0.05:
            allowed.add("evaluator_budget_after_pre_call_probes")
        require(
            reason in allowed, "abort reason does not match healthy pre-call boundary"
        )
        return

    if final_call:
        sid = final_call["slot_id"]
        if final_call["dispatch_state"] == "prewire_failure":
            trigger = f"prewire_failure:{sid}"
        elif final_call["status"] == "cancelled":
            trigger = "transport_cancelled"
        elif final_call["status"] == "integrity_error":
            trigger = f"transport_evidence_integrity_error:{sid}"
        else:
            trigger = resource_reason(last, False, sid)
        if trigger is not None:
            same(reason, trigger, "post-call abort precedence")
            return
    # Event state has no independent SSE proof. Accept only the exact reachable
    # runner boundary, never a replacement for a higher-priority observed fault.
    allowed = (
        {"cancelled_before_next_call"} if unissued else {"cancelled_after_last_call"}
    )
    if final_call:
        allowed.add(f"cancelled_after_call:{final_call['slot_id']}")
        if run["elapsed_s"] > design.EVALUATOR_BUDGET_S:
            allowed.add(f"evaluator_budget_after_call:{final_call['slot_id']}")
    if (
        unissued
        and run["elapsed_s"] >= design.EVALUATOR_BUDGET_S - design.CALL_TIMEOUT_S - 0.05
    ):
        allowed.add("evaluator_budget_before_next_call")
    require(reason in allowed, "abort reason has no recorded boundary or trigger")


def _validate(plan_path: str | Path, output_dir: str | Path) -> dict:
    """Verify an entire frozen run; raise on incomplete or inconsistent evidence."""
    plan, plan_sha = design.load_plan(plan_path)
    output = resident._artifact_path(
        Path(output_dir),
        Path(plan["artifact_policy"]["private_root"]),
        label="v2 replay output",
    )
    run, raw_run = resident._read_object(
        output / "run.json", label="v2 run", ceiling=8_000_000
    )
    require(
        set(run) == _RUN_KEYS and run["schema_version"] == design.RUN_SCHEMA,
        "run schema differs",
    )
    same(run["plan_raw_sha256"], plan_sha, "plan digest")
    claim_root = Path(plan["artifact_policy"]["private_root"])
    claim = runner.read_plan_claim(claim_root, run["plan_claim"])
    same(
        run["plan_claim"]["path"],
        runner.claim_path(claim_root, plan["study_id"])
        .relative_to(claim_root)
        .as_posix(),
        "plan claim path",
    )
    same(
        claim,
        {
            "schema_version": runner.PLAN_CLAIM_SCHEMA,
            "study_id": plan["study_id"],
            "plan_raw_sha256": plan_sha,
            "output": str(output),
        },
        "single-use plan claim",
    )
    for key in (
        "study_id",
        "cohort",
        "source_sha256",
        "runtime_binding",
        "core_contract",
        "continuation_policy",
        "declared_units",
        "declared_conditions",
        "declared_slots",
        "permanently_excluded",
        "scientific_admission_eligible",
        "scientific_admission_registered",
        "confirmation_authorized",
        "production_change_authorized",
        "promotion_authorized",
        "claim_limit",
    ):
        same(run[key], plan[key], key)
    require(
        run["weekly_two_hour_debit"] is False
        and run["private_content_exported"] is False,
        "run authority or private export differs",
    )
    require(
        run["status"] in {"complete", "aborted"} and _number(run["elapsed_s"]),
        "run status/clock differs",
    )
    require(
        (run["abort_reason"] is None)
        if run["status"] == "complete"
        else (type(run["abort_reason"]) is str and bool(run["abort_reason"])),
        "abort reason differs",
    )
    require(
        type(run["slots"]) is list
        and all(type(s) is dict and set(s) == _SLOT_KEYS for s in run["slots"]),
        "slot shape differs",
    )
    same(
        [s["slot_id"] for s in run["slots"]],
        plan["declared_slots"],
        "slot order/denominator",
    )
    accounting = runner.account(run["slots"])
    same(run["accounting"], accounting, "accounting")
    require(accounting["attempted_calls"] <= design.MAX_CALLS, "call cap exceeded")
    if run["status"] == "complete":
        require(
            accounting["unissued_after_abort"] == 0,
            "complete run contains aborted slots",
        )
    slots = {s["slot_id"]: s for s in run["slots"]}
    require(
        type(run["outcomes"]) is list
        and all(type(o) is dict and set(o) == _OUTCOME_KEYS for o in run["outcomes"]),
        "outcome shape differs",
    )
    same(
        [o["condition_id"] for o in run["outcomes"]],
        plan["declared_conditions"],
        "condition order/denominator",
    )
    call_index = 0
    issued = []
    tool_attempts = 0
    execution_order_slots = []
    protocol_hashes = []
    used_paths = set()
    grades = {
        arm: {
            facet: {state: 0 for state in ("pass", "fail", "unassessed")}
            for facet in ("terminal_contract_valid", "substantive_correct")
        }
        for arm in ("direct", "table", "calculator")
    }
    for ordinal, outcome in enumerate(run["outcomes"]):
        cell_id, arm = outcome["condition_id"].split("/")
        cell = next(c for c in plan["scenarios"] if c["cell_id"] == cell_id)
        first_id = f"{cell_id}/direct" if arm == "direct" else f"{cell_id}/{arm}_first"
        final_id = None if arm == "direct" else f"{cell_id}/{arm}_final"
        require(
            outcome["cell_id"] == cell_id and outcome["arm"] == arm,
            "condition identity differs",
        )
        execution_order_slots.append(slots[first_id])
        if final_id:
            execution_order_slots.append(slots[final_id])
        protocol = runner.read_protocol(output, outcome["protocol"])
        same(
            outcome["protocol"]["path"],
            runner.protocol_path(output, ordinal, outcome["condition_id"])
            .relative_to(output)
            .as_posix(),
            "protocol path",
        )
        protocol_hashes.append(outcome["protocol"]["sha256"])
        for key, value in {
            "condition_id": outcome["condition_id"],
            "cell_id": cell_id,
            "arm": arm,
            "first_slot_id": first_id,
            "final_slot_id": final_id,
        }.items():
            same(protocol[key], value, f"protocol {key}")
        markers = []
        calls = []

        def read_call(
            slot_id: str,
            evidence: Any,
            messages: list,
            tools: list,
            *,
            _cell=cell,
            _markers=markers,
            _calls=calls,
        ):
            nonlocal call_index
            slot = slots[slot_id]
            if slot["call"] is None:
                require(evidence is None, "unissued slot has private call evidence")
                return None
            metadata, _ = wire.replay_call(
                output=output,
                descriptor=slot["private_descriptor"],
                call=slot["call"],
                slot=slot,
                plan_value=plan,
                cell=_cell,
                slot_id=slot_id,
                messages=messages,
                tools=tools,
            )
            require(
                slot["call"]["call_index"] == call_index
                and type(slot["call"]["call_index"]) is int,
                "call index/order differs",
            )
            for path in (
                slot["private_descriptor"]["metadata_path"],
                (slot["private_descriptor"].get("raw_stream") or {}).get("path"),
            ):
                if path is not None:
                    require(path not in used_paths, "private call artifact reused")
                    used_paths.add(path)
            response = metadata["response"]
            expected = {
                "status": metadata["status"],
                "dispatch_state": metadata["dispatch_state"],
                "content": response["content"],
                "reasoning_content": response["reasoning_content"],
                "tool_calls": response["tool_calls"] or [],
                "receipt": slot["call"],
                "descriptor": slot["private_descriptor"],
            }
            same(evidence, expected, "private protocol/wire response")
            _markers.append(
                {"slot_id": slot_id, "call_ordinal": call_index, "state": "attempting"}
            )
            _calls.append(slot["call"])
            issued.append(slot)
            call_index += 1
            return expected

        first = read_call(
            first_id,
            protocol["first_call"],
            design.messages(cell, arm),
            [] if arm == "direct" else [design.tool_spec(arm)],
        )
        classification = execution = scaffold = continuation = continuation_sha = None
        final = first if arm == "direct" else None
        expected_failure = None
        if first is not None and arm != "direct":
            classification = core.classify_tool_turn(
                status=first["status"],
                receipt=first["receipt"],
                tool_calls=first["tool_calls"],
                content=first["content"],
                reasoning_content=first["reasoning_content"],
                expectation=design.expectation(cell, arm),
            )
            same(
                protocol["classification"],
                runner.record(classification),
                "replayed classification",
            )
            if classification.execution_eligible:
                same(
                    protocol["execution_marker"],
                    {
                        "state": "attempting",
                        "source_binding_sha256": classification.execution_binding_sha256,
                    },
                    "durable execution marker",
                )
                execution = _execution(protocol["execution"], classification, arm, cell)
                tool_attempts += 1
                if execution.execution_succeeded == core.PASS:
                    scaffold = core.build_empty_content_continuation(
                        classification, execution
                    )
                    continuation = [
                        *design.messages(cell, arm),
                        *scaffold.messages(),
                        copy.deepcopy(design.FINAL_INSTRUCTION),
                    ]
                    continuation_sha = design.sha(design.canonical(continuation))
                    final = read_call(
                        final_id, protocol["final_call"], continuation, []
                    )
                    if final is None:
                        require(
                            slots[final_id]["disposition"] == "unissued_after_abort",
                            "successful tool has unexplained missing final",
                        )
                        expected_failure = slots[final_id]["failure_code"]
                else:
                    require(
                        run["status"] == "aborted"
                        and slots[final_id]["disposition"] == "unissued_after_abort",
                        "failed execution did not abort final",
                    )
                    expected_failure = execution.failure_code
            else:
                expected_failure = (
                    classification.failure_codes[0]
                    if classification.failure_codes
                    else "execution_ineligible"
                )
                if slots[final_id]["disposition"] == "unissued_after_abort":
                    require(
                        run["status"] == "aborted",
                        "ineligible final claims abort in complete run",
                    )
                    same(
                        slots[final_id]["failure_code"],
                        run["abort_reason"],
                        "ineligible final abort reason",
                    )
                else:
                    require(
                        slots[final_id]["disposition"] == "skipped_unissued",
                        "ineligible tool final was not skipped",
                    )
                    same(
                        slots[final_id]["failure_code"], expected_failure, "skip reason"
                    )
        elif first is None:
            require(
                slots[first_id]["disposition"] == "unissued_after_abort",
                "first slot unexplained skip",
            )
            expected_failure = slots[first_id]["failure_code"]
            if final_id:
                require(
                    slots[final_id]["disposition"] == "unissued_after_abort",
                    "unissued first has issued final",
                )
                same(
                    slots[final_id]["failure_code"],
                    expected_failure,
                    "paired abort reason",
                )
        if final is not None:
            expected_failure = final["receipt"]["failure_code"]
            final_grade = design.final_grade(
                final["content"],
                final["status"],
                final["receipt"],
                final["tool_calls"],
                cell,
            )
        else:
            final_grade = runner._not_run_final(cell)
        same(
            protocol["classification"],
            runner.record(classification),
            "private classification",
        )
        if execution is None:
            require(
                protocol["execution_marker"] is None and protocol["execution"] is None,
                "ineligible/unissued execution evidence exists",
            )
        same(protocol["continuation"], runner.record(scaffold), "retained continuation")
        same(
            protocol["continuation_request_messages"],
            continuation,
            "continuation request",
        )
        same(
            protocol["continuation_messages_sha256"],
            continuation_sha,
            "continuation hash",
        )
        if arm == "direct" or final is None:
            require(protocol["final_call"] is None, "unexpected private final")
        same(protocol["wire_attempts"], markers, "wire attempt markers")
        same(protocol["failure_code"], expected_failure, "protocol terminal failure")
        same(protocol["final_grade"], final_grade, "private final grade")
        same(outcome["calls"], calls, "condition call receipts")
        same(
            outcome["classification"],
            runner._public_classification(classification),
            "public classification",
        )
        same(
            outcome["execution"],
            runner._public_execution(execution),
            "public execution",
        )
        same(
            outcome["continuation_policy"],
            None if arm == "direct" else design.CONTINUATION_POLICY,
            "outcome continuation policy",
        )
        same(
            outcome["continuation_messages_sha256"],
            continuation_sha,
            "public continuation hash",
        )
        same(outcome["final_issued"], final is not None, "final issue status")
        same(outcome["final_grade"], final_grade, "public regrade")
        for facet in grades[arm]:
            grades[arm][facet][final_grade["contract"][facet]] += 1
    require(
        call_index == accounting["attempted_calls"], "replayed call denominator differs"
    )
    abort_seen = False
    for slot in execution_order_slots:
        if slot["disposition"] == "unissued_after_abort":
            abort_seen = True
            same(slot["failure_code"], run["abort_reason"], "unissued abort binding")
        elif abort_seen:
            require(False, "work continued after an aborted slot")
    _resource_checks(run, issued)
    _abort_check(run, issued)
    return {
        "schema_version": design.VALIDATION_SCHEMA,
        "status": "valid",
        "verification_kind": "offline_replay_verification",
        "study_id": plan["study_id"],
        "plan_raw_sha256": plan_sha,
        "run_raw_sha256": design.sha(raw_run),
        "source_sha256": plan["source_sha256"],
        "protocol_sha256": protocol_hashes,
        "run_status": run["status"],
        "accounting": accounting,
        "declared_units": design.UNITS,
        "declared_conditions": design.CONDITIONS,
        "recorded_tool_attempts_verified": tool_attempts,
        "model_calls_executed_by_replay": 0,
        "tool_calls_executed_by_replay": 0,
        "facets_by_arm": grades,
        "primary_denominator_per_arm": design.UNITS,
        "permanently_excluded": True,
        "scientific_admission_eligible": False,
        "confirmation_authorized": False,
        "claim_limit": design.CLAIM_LIMIT,
    }


def validate(plan_path: str | Path, output_dir: str | Path) -> dict:
    """Validate untrusted persisted objects with one explicit rejection type."""
    try:
        return _validate(plan_path, output_dir)
    except (
        KeyError,
        TypeError,
        IndexError,
        StopIteration,
        OverflowError,
        RecursionError,
        UnicodeError,
    ) as error:
        raise design.CalibrationError(
            f"malformed v2 replay evidence: {type(error).__name__}"
        ) from error
