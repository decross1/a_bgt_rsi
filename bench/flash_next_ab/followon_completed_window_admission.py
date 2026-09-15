"""Pure admission of an exactly restored grouped model window.

This does not start models or publish scores. Each recorded block is checked
against its frozen plan and private call bytes, then the existing Flash or
resident safety reconstruction is applied to the same supervised window.
The original first-pair completed gates remain untouched.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path

from bench.flash_next_ab import extended_admission as flash_safety
from bench.flash_next_ab import followon_dispatch as grouped
from bench.flash_next_ab import followon_plans as plans
from bench.flash_next_ab import qualification as q
from bench.flash_next_ab import resident_admission as resident_safety
from bench.flash_next_ab.harness import (
    PRIVATE_INDEX_SCHEMA,
    HarnessError,
    _read_regular_file,
    _strict_object,
    _utc_datetime,
)
from bench.flash_next_ab.private_evidence import (
    _response_matches_raw,
    validate_private_evidence,
)

GATE_SCHEMA = "flash-followon-completed-window-validation/v1"
PAIR_SCHEMA = "flash-followon-restored-pair-validation/v1"
MAX_GROUP_BYTES = 2_000_000
MAX_BLOCK_BYTES = 8 * 1024 * 1024


class FollowonAdmissionError(ValueError):
    pass


def _require(ok: bool, reason: str) -> None:
    if not ok:
        raise FollowonAdmissionError(reason)


def _raw(path: Path, label: str, ceiling: int) -> bytes:
    raw, observed = _read_regular_file(path, label=label, max_bytes=ceiling)
    _require(observed == path.absolute(), f"{label} path was redirected")
    return raw


def _json(path: Path, label: str, ceiling: int = 2_000_000) -> dict:
    return _strict_object(_raw(path, label, ceiling), label)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _private_checked_run(run: dict, kind: str, child: Path) -> dict:
    """Build a validation-only index; never write response/error text."""
    checked = copy.deepcopy(run)
    if kind in {"context", "mtp0_controls", "mtp_decode_timing"}:
        checked["status"] = "complete"
    if kind == "context":
        checked["outcomes"] = [row for row in checked["outcomes"] if row.get("calls")]
    for row in checked["outcomes"]:
        if kind in {"thinking", "context", "mtp0_controls",
                    "mtp_decode_timing"}:
            descriptors = row.get("private_call_evidence")
            _require(isinstance(descriptors, list)
                     and len(descriptors) == len(row.get("calls", [])),
                     "diagnostic call omitted its private raw index")
            grade = row.get("grade") if isinstance(row.get("grade"), dict) else {}
            details = grade.get("details") if isinstance(grade.get("details"), dict) else {}
            details["_private_call_evidence"] = {
                "schema_version": PRIVATE_INDEX_SCHEMA,
                "artifacts": descriptors,
            }
            grade["details"] = details
            row["grade"] = grade
        if kind == "context":
            # Context public rows intentionally omit transport error strings.
            # Recover them solely inside the pure private validator copy.
            for call, descriptor in zip(row["calls"],
                                        row["private_call_evidence"], strict=True):
                metadata = _json(child / descriptor["metadata_path"],
                                 "private context call", 512_000)
                _require(_sha(_raw(child / descriptor["metadata_path"],
                                   "private context call", 512_000))
                         == descriptor["metadata_sha256"],
                         "private context call metadata drifted")
                call["error"] = metadata.get("error")
    return checked


def _thinking_triggers(child: Path, run: dict) -> None:
    """Recompute the public adaptive trigger from the byte-verified first call."""
    from bench.flash_next_ab import followon_thinking as runner
    from bench.weekly_upgrade_effort import manifest as effort_manifest
    from bench.weekly_upgrade_effort import runner as effort_runner

    source = effort_manifest.load_manifest(runner.SOURCE_MANIFEST)
    tasks = {task["id"]: task for task in source["tasks"]}
    for row in run["outcomes"]:
        calls = row["calls"]
        adaptive = row["condition"] == "adaptive" and row["role"] != "critic"
        trigger = None
        if adaptive:
            descriptor = row["private_call_evidence"][0]
            raw = _raw(child / descriptor["metadata_path"],
                       "adaptive first-call private metadata", 512_000)
            _require(_sha(raw) == descriptor.get("metadata_sha256")
                     and len(raw) == descriptor.get("metadata_bytes"),
                     "adaptive first-call private metadata drifted")
            metadata = _strict_object(raw, "adaptive first-call private metadata")
            response = metadata.get("response")
            _require(isinstance(response, dict)
                     and metadata.get("call_id") == calls[0]["call_id"]
                     and metadata.get("status") == calls[0]["status"],
                     "adaptive first-call content does not match its receipt")
            task = tasks.get(row["task_id"])
            _require(isinstance(task, dict),
                     "adaptive first-call source task is unavailable")
            content = response.get("content")
            if calls[0]["status"] == "returned":
                _require(isinstance(content, str),
                         "adaptive returned content is unavailable")
                parsed, failure = effort_runner.protocol(
                    content, task["output_schema"]
                )
            else:
                parsed, failure = None, "transport"
            previous = {"effort": "medium", "status": calls[0]["status"],
                        "protocol_failure": failure,
                        "needs_review": parsed.get("needs_review") if parsed else None}
            trigger = effort_runner.route(row["role"], "adaptive", previous)
            if len(calls) == 2:
                usage = calls[0].get("usage")
                used = usage.get("completion_tokens") if isinstance(usage, dict) else None
                has_output = bool(content or response.get("reasoning_content")
                                  or response.get("tool_calls"))
                _require(calls[0]["status"] == "returned"
                         and type(used) is int
                         and 0 <= used <= runner.TOTAL_TOKENS // 2
                         and (used != 0 or not has_output)
                         and trigger == "xhigh",
                         "adaptive retry was not caused by a valid public trigger")
        _require(row.get("escalation_public_trigger") is (trigger == "xhigh")
                 and (len(calls) != 2 or trigger == "xhigh"),
                 "adaptive escalation count lacks source-bound trigger")


def _block(window: plans.FollowonExecution, output: Path, ordinal: int,
           listed: dict) -> dict:
    declaration = window.document["blocks"][ordinal]
    plan = window.frozen.block_plans[ordinal]
    _require(listed.get("ordinal") == ordinal
             and listed.get("block_id") == declaration["block_id"]
             and listed.get("kind") == declaration["kind"]
             and listed.get("status") == "complete_pending_restoration"
             and listed.get("reason_code") is None,
             "group block did not complete before restoration")
    child = output / declaration["output_relative"]
    raw = _raw(child / "run.json", "completed diagnostic block", MAX_BLOCK_BYTES)
    run = _strict_object(raw, "completed diagnostic block")
    _require(listed.get("run_sha256") == _sha(raw)
             and run.get("promotion_authorized") is False,
             "group block bytes or publication authority differ")
    kind = declaration["kind"]
    if kind == "thinking":
        _require(grouped._thinking_block_complete(
            run, plan, declaration["endpoint_name"], declaration["seed_block"]
        ), "thinking block was incomplete or identity changed")
    elif kind == "context":
        from bench.flash_next_ab import followon_context as runner
        runner.validate_run(run)
        selected_ids = [row["cell_id"] for row in plan["declared_cells"]
                        if row["target_input_tokens"]
                           == declaration["target_block"]]
        _require(run.get("status") == "block_complete"
                 and run.get("plan") == plan
                 and run.get("plan_sha256") == plan.get("plan_sha256")
                 and run.get("endpoint_name")
                    == declaration["endpoint_name"]
                 and run.get("target_block") == declaration["target_block"]
                 and run.get("qualification_receipt_sha256")
                    == window.document["route_bindings"][declaration[
                        "endpoint_name"]]["qualification_receipt_sha256"]
                 and len(selected_ids) == 12
                 and run.get("declared_cells") == selected_ids
                 and run.get("summary", {}).get("attempted") == 12,
                 "context block omitted supported measured cells")
    elif kind == "market_canaries":
        from bench.flash_next_ab import followon_market_canaries as runner
        runner.validate_plan(plan)
        _require(grouped._market_block_complete(
            run, plan, declaration["endpoint_name"], declaration["seed_block"]
        ), "market canary block was incomplete or identity changed")
    elif kind == "selected_repair":
        from bench.flash_next_ab import followon_selected_repair as runner
        runner.validate_run(run, plan, declaration["endpoint_name"])
        _require(run.get("status") == "complete"
                 and run.get("summary", {}).get("attempted")
                    == (44 if declaration["endpoint_name"] == "flash_next_mia"
                        else 22)
                 and run.get("abort_reason") is None,
                 "selected repair omitted its measured denominator cells")
    elif kind == "coding_temp1_medium":
        from bench.flash_next_ab import followon_coding_temp1 as runner
        runner.validate_run(run, plan, declaration["endpoint_name"])
        _require(run.get("status") == "complete"
                 and run.get("summary", {}).get("attempted") == 4
                 and run.get("abort_reason") is None,
                 "registered coding diagnostic omitted one of four attempts")
    elif kind == "mtp0_controls":
        from bench.flash_next_ab import mtp0_controls as runner
        runner.validate_run(run, plan)
        _require(grouped._mtp0_block_complete(
            run, plan, declaration["endpoint_name"]
        ),
                 "MTP0 control panel omitted declared calls")
    elif kind == "mtp_decode_timing":
        from bench.flash_next_ab import mtp_decode_diagnostic as runner
        runner.validate_run(run, plan)
        _require(grouped._mtp_decode_block_complete(
            run, plan, declaration["endpoint_name"]
        ), "MTP decode block omitted frozen repeated calls")
    else:
        raise FollowonAdmissionError("unregistered diagnostic block kind")
    if kind == "context" or kind == "mtp0_controls":
        expected_counts = (
            run["summary"]["attempted"], run["summary"]["passed"],
            run["summary"]["timeout"]
        )
    elif kind == "mtp_decode_timing":
        expected_counts = (run["summary"]["attempted"], None,
                           run["summary"]["timeout"])
    else:
        outcomes = run["outcomes"]
        expected_counts = (
            sum(row["status"] != "not_run" for row in outcomes),
            sum(row["passed"] is True for row in outcomes),
            sum(row["status"] == "timeout" for row in outcomes),
        )
    _require((listed.get("attempted"), listed.get("passed"),
              listed.get("timeouts")) == expected_counts,
             "group counters differ from frozen public block receipts")
    private = validate_private_evidence(
        _private_checked_run(run, kind, child), child
    )
    _require(private.get("calls_verified", 0) > 0
             and private.get("private_content_exported") is False,
             "diagnostic private transport was not byte-verified")
    if kind == "thinking":
        _thinking_triggers(child, run)
    return {"block_id": declaration["block_id"], "kind": kind,
            "run_sha256": _sha(raw),
            "private_calls_verified": private["calls_verified"],
            "attempted": listed["attempted"], "passed": listed["passed"],
            "timeouts": listed["timeouts"]}


def _chronology(result: dict, supervision: dict) -> None:
    started = _utc_datetime(result.get("started_at"), "follow-on started")
    restored = _utc_datetime(result.get("restoration", {}).get("verified_at"),
                             "follow-on exact restoration")
    finished = _utc_datetime(result.get("finished_at"), "follow-on result")
    supervised = _utc_datetime(supervision.get("finished_at"),
                               "follow-on supervisor")
    _require(started <= restored <= finished <= supervised,
             "follow-on receipt was published before exact restoration")


def _profile_canary(output: Path, result: dict, state: dict,
                    spec: object) -> dict:
    from bench.flash_next_ab.followon_profiles import (
        MIA_CTX69632,
        requires_profile_canary,
    )
    if not requires_profile_canary(spec):
        return {"required": False}
    canary_raw = _raw(output / "profile-canary.json",
                      "profile canary summary", 2_000_000)
    attempts_raw = _raw(output / "profile-canary-attempts.json",
                        "profile canary attempts", 2_000_000)
    summary = _strict_object(canary_raw, "profile canary summary")
    attempts = _strict_object(attempts_raw, "profile canary attempts")
    rows = attempts.get("results")
    required = 1 if spec is MIA_CTX69632 else 12
    _require(result.get("profile_canary_sha256") == _sha(canary_raw)
             and result.get("profile_canary_attempts_sha256")
                == _sha(attempts_raw)
             and result.get("profile_canary_status")
                == state.get("profile_canary_status") == summary.get("status")
                == "passed"
             and result.get("profile_canary_attempt_count")
                == summary.get("attempt_count") == required
             and summary.get("spec_id") == spec.spec_id
             and attempts.get("spec_id") == spec.spec_id
             and result.get("profile_canary_protocol_sha256")
                == state.get("profile_canary_protocol_sha256")
                == summary.get("protocol_sha256")
                == attempts.get("protocol_sha256")
             and result.get("profile_canary_suite") == summary.get("suite")
             and isinstance(rows, list) and len(rows) == required
             and all(isinstance(row, dict) and row.get("status") == "passed"
                     for row in rows),
             "registered profile omitted closed 12/1-call canary proof")
    from bench.flash_next_ab.followon_canaries import (
        CONTEXT_SELECTED_MESSAGES_SHA256,
        decoded_view,
    )
    from bench.flash_next_ab.followon_native_packet import (
        MESSAGE_SHA256,
        PACK_SHA256,
    )
    for row in rows:
        public = row.get("public_response")
        descriptor = row.get("private_response")
        _require(isinstance(public, dict)
                 and isinstance(descriptor, dict)
                 and public.get("response_model") == spec.served_name
                 and descriptor.get("response_stream_sha256")
                    == public.get("response_stream_sha256")
                 and isinstance(descriptor.get("private_stream_relpath"), str)
                 and descriptor["private_stream_relpath"].startswith(
                     "private-probes/canary_")
                 and descriptor["private_stream_relpath"].endswith(".sse"),
                 "profile public/private call identity drifted")
        stream = _raw(output / descriptor["private_stream_relpath"],
                      "profile raw response SSE", 16 * 1024 * 1024)
        _require(len(stream) == descriptor.get("response_stream_bytes")
                 and _sha(stream) == descriptor["response_stream_sha256"],
                 "profile raw response stream changed")
        _response_matches_raw(stream, public, {"served_model": spec.served_name})
        view = decoded_view(public)
        _require(row.get("decoded_view") == view,
                 "profile decoded status differs from raw stream")
        request_id = row.get("request_id")
        if spec is MIA_CTX69632:
            _require(row.get("source_messages_sha256")
                     == CONTEXT_SELECTED_MESSAGES_SHA256 == MESSAGE_SHA256
                     and summary.get("protocol_sha256") == PACK_SHA256
                     and public.get("usage", {}).get("prompt_tokens") == 65_581
                     and view.get("content") == (
                         '{"answer_code":"claim_contradicted_threshold_0_5",'
                         '"citations":["GT8A-CLAIM-0017","GT8A-PAYOFF-0073",'
                         '"GT8A-THRESHOLD-0132"]}'
                     )
                     and view.get("tool_calls") == []
                     and view.get("finish_reason") == "stop",
                     "native context canary lacks the true near-ceiling prompt")
        elif request_id == "literal64":
            _require(view.get("content") == "ALPHA17_BETA703_GAMMA29_DELTA11"
                     and view.get("finish_reason") == "stop",
                     "MTP literal output differs from raw SSE")
        elif request_id == "short_reasoned_answer":
            _require(view.get("content") == "1,1,1,1"
                     and view.get("finish_reason") == "stop",
                     "MTP arithmetic output differs from raw SSE")
        elif request_id == "structured_tool":
            calls = view.get("tool_calls")
            try:
                arguments = json.loads(calls[0]["arguments"])
            except (IndexError, KeyError, TypeError, ValueError,
                    json.JSONDecodeError):
                arguments = None
            _require(isinstance(calls, list) and len(calls) == 1
                     and calls[0].get("name") == "record_probe"
                     and arguments == {"label": "mtp-parity", "value": 703}
                     and view.get("finish_reason") == "tool_calls",
                     "MTP tool output differs from raw SSE")
        elif request_id == "code_generation":
            _require(view.get("finish_reason") == "stop",
                     "MTP code stream lacks a clean terminal response")
        else:
            raise FollowonAdmissionError("profile canary request was not registered")
    return {"required": True, "spec_id": spec.spec_id,
            "canary_sha256": _sha(canary_raw), "attempt_count": required,
            "private_streams_verified": required}


def _common(window: plans.FollowonExecution, output: Path,
            plan: dict) -> tuple[dict, dict, dict, dict, list[dict]]:
    _require(output == Path(window.document["output_dir"])
             and output.is_dir() and not output.is_symlink()
             and output.resolve() == output,
             "completed follow-on output differs from registered direct child")
    result = _json(output / "result.json", "completed follow-on result")
    state = _json(output / "state.json", "completed follow-on state")
    supervisor = _json(output / "supervision.json", "completed follow-on supervisor")
    raw_attempt = _raw(output / "group-attempt.json", "completed grouped attempt",
                       MAX_GROUP_BYTES)
    attempt = _strict_object(raw_attempt, "completed grouped attempt")
    _require(result.get("status") == "complete"
             and state.get("phase") == "complete"
             and state.get("result_status") == "complete"
             and result.get("restoration", {}).get("status") == "verified"
             and result.get("restoration", {}).get("errors") == []
             and result.get("restoration", {}).get("sentinel_retained") is False
             and result.get("exact_final_verification", True) is True
             and result.get("weekly_budget_debit") is False
             and result.get("paid_api_calls") == 0
             and result.get("production_change_authorized") is False
             and result.get("group_attempt_status")
                == "blocks_complete_pending_restoration"
             and result.get("group_attempt_sha256") == _sha(raw_attempt)
             and attempt.get("schema_version") == grouped.ATTEMPT_SCHEMA
             and attempt.get("status") == "blocks_complete_pending_restoration"
             and attempt.get("abort_reason") is None
             and attempt.get("window_id") == window.pair_id
             and attempt.get("cohort") == window.cohort
             and attempt.get("window_plan_sha256") == window.source_sha256
             and attempt.get("followon_source_bundle_sha256")
                == window.document["followon_source_bundle_sha256"]
             and attempt.get("restoration_required") is True
             and attempt.get("comparison_eligible") is False
             and attempt.get("promotion_authorized") is False,
             "group/result state is incomplete or unbound to restoration")
    blocks = attempt.get("blocks")
    _require(isinstance(blocks, list)
             and len(blocks) == len(window.document["blocks"]),
             "group receipt omitted a declared block")
    validated = [_block(window, output, ordinal, listed)
                 for ordinal, listed in enumerate(blocks)]
    module = ("bench.flash_next_ab.extended_lifecycle"
              if window.cohort == "flash"
              else "bench.flash_next_ab.resident_evaluation_window")
    argv = [plan["launcher_python_path"], "-m", module, "--worker",
            "--eval-plan", str(window.source_path),
            "--output-dir", str(output)]
    _require(supervisor.get("returncode") == 0
             and supervisor.get("terminated_at_work_cutoff") is False
             and supervisor.get("force_killed") is False
             and supervisor.get("emergency_recovery") is None
             and supervisor.get("pid") == state.get("worker_pid")
             and supervisor.get("worker_start_ticks")
                == state.get("worker_start_ticks")
             and supervisor.get("boot_id") == state.get("boot_id")
             and supervisor.get("argv") == argv
             and (supervisor.get("argv_sha256") == q.sha256(argv)
                  if window.cohort == "flash" else
                  supervisor.get("command_sha256") == q.sha256(argv))
             and type(supervisor.get("elapsed_seconds")) in {int, float}
             and math.isfinite(supervisor["elapsed_seconds"])
             and 0 < supervisor["elapsed_seconds"] <= 14_400,
             "supervisor did not close the same complete worker")
    _chronology(result, supervisor)
    return result, state, supervisor, attempt, validated


def _supervisor_inputs(window: plans.FollowonExecution, output: Path,
                       plan: dict, cohort: str) -> None:
    """Replay supervisor inputs as well as terminal result and monitor bytes."""
    source_snapshot = plan.get("controller_source_bundle")
    _require(source_snapshot == window.document["followon_source_bundle"]
             and source_snapshot == grouped.frozen_followon_source_bundle()
             and plan.get("controller_source_bundle_sha256")
                == grouped._canonical_sha(source_snapshot),
             "registered follow-on controller source changed after supervision")
    if cohort == "flash":
        # The existing pure gate binds all four durable supervisor inputs:
        # raw contract, parsed contract, prior qualification plan and source
        # bundle snapshot. It also rechecks the exact registered contract bytes
        # and candidate image/model/launch argv against the prior C0 receipt.
        try:
            contract_raw = _raw(output / "launch-contract.raw.json",
                                "Flash raw launch contract", 2_000_000)
            contract = _strict_object(contract_raw, "Flash raw launch contract")
            _require(_sha(contract_raw) == plan.get("contract_sha256")
                     and _json(output / "launch-contract.snapshot.json",
                               "Flash launch contract snapshot") == contract
                     and _json(output / "prior-c0-plan.snapshot.json",
                               "Flash prior qualification snapshot")
                        == window.qualification_plan
                     and _json(output / "controller-source-bundle.snapshot.json",
                               "Flash controller source snapshot")
                        == source_snapshot,
                     "Flash launch or source snapshot is missing or drifted")
            if window.v5_parent is None:
                flash_safety._supervisor_inputs(output, window.parent, plan)
            else:
                # A selected v5 image is qualified by its own immutable,
                # restored profile receipt. The original C0 gate cannot
                # replay this distinct launch contract or image.
                parent = window.v5_parent
                spec = parent.spec
                ref = parent.document["source_refs"]["launch-contract.raw.json"]
                registered_raw = _raw(Path(ref["path"]),
                                      "v5 registered launch contract", 2_000_000)
                _require(_sha(registered_raw) == ref["sha256"]
                         and contract_raw == registered_raw
                         and q._verified_contract_raw(
                             contract, plan["contract_sha256"], spec=spec,
                         ) == contract_raw
                         and plan.get("candidate_variant_id") == spec.spec_id
                         and plan.get("candidate_spec_sha256")
                            == spec.identity_sha256()
                         and plan.get("image_id") == spec.image_id
                         and plan.get("docker_create_argv")
                            == parent.qualification_plan["docker_create_argv"]
                         and plan.get("docker_create_argv_sha256")
                            == parent.qualification_plan["docker_create_argv_sha256"]
                         and plan.get("v5_qualified_parent")
                            == window.document["v5_qualified_parent"],
                         "v5 launch differs from its own admitted profile")
        except (HarnessError, KeyError, TypeError, ValueError) as exc:
            raise FollowonAdmissionError(
                "Flash raw launch or source snapshot is missing or drifted"
            ) from exc
    else:
        # Resident supervision has no external model launch contract. Its
        # complete execution plan is its durable controller-source snapshot.
        _require(_json(output / "plan.json", "resident execution/source snapshot")
                 == plan,
                 "resident supervisor execution or source snapshot drifted")


def validate_completed_window(source_path: Path, output_dir: Path,
                              *, cohort: str) -> dict:
    """Accept only a complete restored grouped window; no score projection."""
    window = plans.load_execution(Path(source_path), cohort=cohort)
    output = Path(output_dir).absolute()
    plan = (plans.flash_plan(window, output) if cohort == "flash"
            else plans.resident_plan(window, output))
    _require(_json(output / ("extended-plan.json" if cohort == "flash"
                             else "plan.json"), "supervisor execution plan") == plan,
             "supervisor did not execute the frozen follow-on plan")
    _supervisor_inputs(window, output, plan, cohort)
    result, state, supervisor, _attempt, blocks = _common(window, output, plan)
    _require(result.get("pair_id") == window.pair_id
             and result.get("window_plan_sha256") == window.source_sha256
             and result.get("plan_sha256")
                == (q.sha256(window.qualification_plan)
                    if cohort == "flash" else q.sha256(plan))
             and result.get("qualified_parent_window")
                == window.document["qualified_parent_window"],
             "terminal result changed the frozen parent/window/plan")
    if cohort == "flash":
        _require(result.get("schema") == "flash-followon-flash-result/v1"
                 and state.get("schema") == "flash-followon-flash-state/v1"
                 and supervisor.get("schema")
                    == "flash-followon-flash-supervision/v1"
                 and result.get("extended_plan_sha256") == q.sha256(plan)
                 and state.get("extended_plan_sha256") == q.sha256(plan)
                 and supervisor.get("extended_plan_sha256") == q.sha256(plan)
                 and result.get("probe_count") == 3
                 and result.get("qualification_error") is None
                 and result.get("failure_class") is None
                 and result.get("failure_stage") is None
                 and result.get("memory_samples", 0) > 0
                 and type(result.get("min_mem_available_gib")) in {float, int}
                 and math.isfinite(result["min_mem_available_gib"])
                 and result["min_mem_available_gib"] >= 20,
                 "Flash grouped result lacks completed C0-equivalent safety proof")
        if window.v5_parent is not None:
            _require(result.get("v5_qualified_parent")
                     == window.document["v5_qualified_parent"]
                     and state.get("v5_qualified_parent")
                        == window.document["v5_qualified_parent"]
                     and plan.get("v5_qualified_parent")
                        == window.document["v5_qualified_parent"],
                     "selected v5 result or state changed its admitted parent")
        flash_safety._final_identity(result, state)
        from bench.flash_next_ab.followon_profiles import (
            SPECS_BY_ID,
            is_registered_spec,
        )
        variant = plan["candidate_variant_id"]
        spec = (None if variant == "nvidia-nvfp4-fc694b54"
                else SPECS_BY_ID.get(variant))
        _require(variant == "nvidia-nvfp4-fc694b54"
                 or spec is not None and is_registered_spec(spec),
                 "Flash profile is not a code-owned candidate spec")
        flash_safety._memory(output, result, plan, spec)
        flash_safety.validate_ui_observer(output, result, state, plan)
        profile_proof = _profile_canary(output, result, state, spec)
    else:
        _require(result.get("schema") == "flash-followon-resident-result/v1"
                 and state.get("schema") == "flash-followon-resident-state/v1"
                 and supervisor.get("schema")
                    == "flash-followon-resident-supervision/v1"
                 and supervisor.get("complete") is True
                 and result.get("exact_final_verification") is True,
                 "resident grouped result lacks completed isolation proof")
        initial = result.get("initial_observation")
        quiet = result.get("quiet_observation")
        final = result.get("final_observation")
        resident_safety._identity(initial, quiet, final)
        resident_safety._memory(output, result, initial, quiet, final)
        profile_proof = {"required": False}
    return {"schema": GATE_SCHEMA, "window_id": window.pair_id,
            "cohort": cohort, "window_plan_sha256": window.source_sha256,
            "qualified_parent_window_sha256": window.parent.source_sha256,
            "controller_source_bundle_sha256": window.document[
                "followon_source_bundle_sha256"],
            "execution_plan_sha256": q.sha256(plan),
            "result_sha256": _sha(_raw(output / "result.json", "final result", 2_000_000)),
            "group_attempt_sha256": result["group_attempt_sha256"],
            "supervision_sha256": _sha(_raw(output / "supervision.json", "supervision", 2_000_000)),
            "blocks": blocks, "exact_restoration_verified": True,
            "profile_canary": profile_proof,
            "comparison_eligible": False, "promotion_authorized": False,
            "private_content_exported": False}


def validate_completed_pair(flash_source: Path, flash_output: Path,
                            resident_source: Path, resident_output: Path) -> dict:
    """Bind two restored diagnostics without claiming a model win."""
    flash_window = plans.load_execution(flash_source, cohort="flash")
    resident_window = plans.load_execution(resident_source, cohort="resident")
    _require(flash_window.pair_id == resident_window.pair_id
             and flash_window.document["study_id"]
                == resident_window.document["study_id"],
             "follow-on cohorts do not share one declared study/window")
    flash = validate_completed_window(flash_source, flash_output,
                                      cohort="flash")
    resident = validate_completed_window(resident_source, resident_output,
                                         cohort="resident")
    left = flash_window.document["blocks"]
    right = resident_window.document["blocks"]
    _require(len(left) == len(right)
             and all(a["kind"] == b["kind"]
                     and a["seed_block"] == b["seed_block"]
                     and a["target_block"] == b["target_block"]
                     for a, b in zip(left, right, strict=True)),
             "grouped cohorts have a different declared cell/seed form")
    if flash_window.document["study_id"] == "selected-profile-repair-v1":
        _require(
            flash_window.frozen.block_plans[0]
            == resident_window.frozen.block_plans[0]
            and flash_window.frozen.block_plans[0]["candidate_variant_id"]
                == flash_window.document["candidate_variant_id"],
            "selected repair cohorts did not share exact frozen tasks/policies",
        )
    return {"schema": PAIR_SCHEMA, "window_id": flash_window.pair_id,
            "study_id": flash_window.document["study_id"],
            "flash": flash, "resident": resident,
            "paired_blocks": [
                {"ordinal": index, "kind": a["kind"],
                 "seed_block": a["seed_block"],
                 "target_block": a["target_block"],
                 "routes_match_for_model_bundle": (
                     a["endpoint_name"] in {"flash_next_mia", "flash_next"}
                     and b["endpoint_name"] == "resident_qwen"
                 ),
                 "candidate_endpoint_name": a["endpoint_name"],
                 "resident_endpoint_name": b["endpoint_name"]}
                for index, (a, b) in enumerate(zip(left, right, strict=True))
            ],
            "score_claim_authorized": False,
            "comparison_eligible": False,
            "promotion_authorized": False,
            "private_content_exported": False}
