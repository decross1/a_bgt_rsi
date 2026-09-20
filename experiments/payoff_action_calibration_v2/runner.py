"""Durable runner for the excluded native-tool v2 engineering shakedown.

The public ``run.json`` contains dispositions, grades, and digests.  Exact
model text, reasoning, calls, and the retained local-tool result live in one
private protocol record per condition.  A durable marker is written before
every model request and before every local execution.  Runs are never resumed:
an existing output directory may contain an ambiguous in-flight marker and is
therefore refused.
"""

from __future__ import annotations

import copy
import dataclasses
import errno
import json
import math
import os
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any

from bench.flash_next_ab import harness, transport
from experiments.payoff_tool_arithmetic import flash_resident as resident
from orchestrator.weekly_upgrade_trial import resource_lease

from . import contract as core
from . import design, wire

PRIVATE_PROTOCOL_SCHEMA = design.PROTOCOL_SCHEMA
PLAN_CLAIM_SCHEMA = "flash-payoff-action-calibration-plan-claim/v2"
_BYTES_TAG = "$bytes_hex"
_CLAIM_PATH = re.compile(r"private-claims/[0-9a-f]{64}\.json")
_FINAL_INSTRUCTION = {
    "role": "user",
    "content": "Use the exact tool result. Return only the required bare JSON.",
}


@dataclass(frozen=True)
class ConditionProtocol:
    """Complete private evidence for one frozen cell/arm condition."""

    schema_version: str
    condition_id: str
    cell_id: str
    arm: str
    first_slot_id: str
    final_slot_id: str | None
    stage: str
    wire_attempts: tuple[dict[str, Any], ...] = ()
    first_call: dict[str, Any] | None = None
    classification: dict[str, Any] | None = None
    execution_marker: dict[str, Any] | None = None
    execution: dict[str, Any] | None = None
    continuation: dict[str, Any] | None = None
    continuation_request_messages: tuple[dict[str, Any], ...] | None = None
    continuation_messages_sha256: str | None = None
    final_call: dict[str, Any] | None = None
    final_grade: dict[str, Any] | None = None
    failure_code: str | None = None


def record(value: Any) -> Any:
    """Convert dataclass evidence to strict JSON values, retaining bytes as hex."""

    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {field.name: record(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, bytes):
        return {_BYTES_TAG: value.hex()}
    if isinstance(value, tuple):
        return [record(item) for item in value]
    if isinstance(value, list):
        return [record(item) for item in value]
    if isinstance(value, Mapping):
        design.require(
            all(isinstance(key, str) for key in value),
            "protocol record object keys must be strings",
        )
        return {key: record(item) for key, item in value.items()}
    if value is None or type(value) in {bool, int, float, str}:
        return value
    raise design.CalibrationError(
        f"unsupported protocol record value: {type(value).__name__}"
    )


def unrecord(value: Any) -> Any:
    """Reverse :func:`record`, including strict validation of tagged bytes."""

    if isinstance(value, list):
        return [unrecord(item) for item in value]
    if isinstance(value, dict):
        if set(value) == {_BYTES_TAG}:
            encoded = value[_BYTES_TAG]
            design.require(
                isinstance(encoded, str)
                and len(encoded) % 2 == 0
                and all(character in "0123456789abcdef" for character in encoded),
                "protocol bytes tag is malformed",
            )
            return bytes.fromhex(encoded)
        return {key: unrecord(item) for key, item in value.items()}
    return value


def classification_from_record(value: Mapping[str, Any]) -> core.ToolTurnClassification:
    """Reconstruct a core classification from persisted private evidence."""

    decoded = unrecord(dict(value))
    decoded["pretool_content"] = core.TextEvidence(**decoded["pretool_content"])
    decoded["reasoning_content"] = core.TextEvidence(**decoded["reasoning_content"])
    decoded["failure_codes"] = tuple(decoded["failure_codes"])
    return core.ToolTurnClassification(**decoded)


def execution_from_record(value: Mapping[str, Any]) -> core.ExecutionOutcome:
    decoded = unrecord(dict(value))
    return core.ExecutionOutcome(**decoded)


def continuation_from_record(value: Mapping[str, Any]) -> core.ContinuationScaffold:
    decoded = unrecord(dict(value))
    return core.ContinuationScaffold(**decoded)


def final_grade_from_record(value: Mapping[str, Any]) -> core.FinalGrade:
    decoded = unrecord(dict(value))
    decoded["failure_codes"] = tuple(decoded["failure_codes"])
    return core.FinalGrade(**decoded)


def _protocol_bytes(protocol: ConditionProtocol) -> bytes:
    # ensure_ascii=True preserves even deliberately unencodable surrogate evidence.
    return json.dumps(
        record(protocol),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8") + b"\n"


def claim_path(root: str | Path, study_id: str) -> Path:
    """Return the one permanent claim path for a study identity."""

    design.require(isinstance(study_id, str) and bool(study_id), "study ID is invalid")
    filename = f"{design.sha(study_id.encode('utf-8', errors='strict'))}.json"
    return Path(root) / "private-claims" / filename


def _open_directory_nofollow(path: Path, *, label: str) -> int:
    """Open an existing absolute directory without following any path symlink."""

    design.require(path.is_absolute(), f"{label} must be absolute")
    normalized = Path(os.path.abspath(path))
    close_on_exec = getattr(os, "O_CLOEXEC", 0)
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    flags = os.O_RDONLY | os.O_DIRECTORY | close_on_exec | no_follow
    try:
        descriptor = os.open(normalized.anchor, flags)
        for part in normalized.parts[1:]:
            try:
                child = os.open(part, flags, dir_fd=descriptor)
            except OSError:
                os.close(descriptor)
                raise
            os.close(descriptor)
            descriptor = child
    except OSError as error:
        raise design.CalibrationError(f"{label} is unavailable or redirected") from error
    return descriptor


def _claim_plan(
    root: Path,
    *,
    study_id: str,
    plan_raw_sha256: str,
    output: Path,
) -> dict[str, Any]:
    """Permanently consume a plan/study identity before any effectful call."""

    body = {
        "schema_version": PLAN_CLAIM_SCHEMA,
        "study_id": study_id,
        "plan_raw_sha256": plan_raw_sha256,
        "output": str(output),
    }
    raw = design.canonical(body) + b"\n"
    target = claim_path(root, study_id)
    root_descriptor = _open_directory_nofollow(root, label="plan artifact root")
    claim_directory: int | None = None
    claim_file: int | None = None
    created_directory = False
    close_on_exec = getattr(os, "O_CLOEXEC", 0)
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    try:
        try:
            os.mkdir("private-claims", mode=0o700, dir_fd=root_descriptor)
            created_directory = True
        except FileExistsError:
            pass
        directory_flags = os.O_RDONLY | os.O_DIRECTORY | close_on_exec | no_follow
        try:
            claim_directory = os.open(
                "private-claims", directory_flags, dir_fd=root_descriptor
            )
        except OSError as error:
            raise design.CalibrationError(
                "plan claim directory is unavailable or redirected"
            ) from error
        if created_directory:
            os.fsync(root_descriptor)
        try:
            claim_file = os.open(
                target.name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | close_on_exec | no_follow,
                0o600,
                dir_fd=claim_directory,
            )
        except OSError as error:
            if error.errno == errno.EEXIST:
                raise design.CalibrationError(
                    "plan/study already claimed; v2 plans are single-use"
                ) from error
            raise design.CalibrationError("plan claim could not be created") from error
        view = memoryview(raw)
        while view:
            written = os.write(claim_file, view)
            design.require(written > 0, "plan claim persistence made no progress")
            view = view[written:]
        os.fsync(claim_file)
        os.fsync(claim_directory)
    finally:
        if claim_file is not None:
            os.close(claim_file)
        if claim_directory is not None:
            os.close(claim_directory)
        os.close(root_descriptor)
    return {
        "path": target.relative_to(root).as_posix(),
        "sha256": design.sha(raw),
        "bytes": len(raw),
    }


def read_plan_claim(
    root: str | Path, descriptor: Mapping[str, Any]
) -> dict[str, Any]:
    """Read and authenticate the permanent single-use plan claim."""

    design.require(
        type(descriptor) is dict
        and set(descriptor) == {"path", "sha256", "bytes"}
        and isinstance(descriptor.get("path"), str)
        and _CLAIM_PATH.fullmatch(descriptor["path"]) is not None
        and isinstance(descriptor.get("sha256"), str)
        and type(descriptor.get("bytes")) is int,
        "plan claim descriptor is malformed",
    )
    artifact_root = Path(os.path.abspath(Path(root).expanduser()))
    path = artifact_root / descriptor["path"]
    try:
        raw, resolved = harness._read_regular_file(
            path,
            label="v2 single-use plan claim",
            max_bytes=16_384,
        )
    except harness.HarnessError as error:
        raise design.CalibrationError("plan claim is unavailable or redirected") from error
    design.require(
        resolved == Path(os.path.abspath(path))
        and len(raw) == descriptor["bytes"]
        and design.sha(raw) == descriptor["sha256"],
        "plan claim bytes differ",
    )
    try:
        value = harness._strict_object(raw, "v2 single-use plan claim")
    except harness.HarnessError as error:
        raise design.CalibrationError("plan claim JSON is invalid") from error
    design.require(
        set(value) == {"schema_version", "study_id", "plan_raw_sha256", "output"}
        and value.get("schema_version") == PLAN_CLAIM_SCHEMA,
        "plan claim schema differs",
    )
    return value


def protocol_path(output: Path, ordinal: int, condition_id: str) -> Path:
    suffix = design.sha(condition_id.encode("utf-8"))[:16]
    return output / "private" / "protocols" / f"{ordinal:04d}-{suffix}.json"


def _persist_protocol(
    output: Path, ordinal: int, protocol: ConditionProtocol
) -> dict[str, Any]:
    """Atomically durably replace one private condition protocol record."""

    path = protocol_path(output, ordinal, protocol.condition_id)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    raw = _protocol_bytes(protocol)
    temporary = path.with_name(path.name + ".pending")
    design.require(not temporary.exists(), "stale protocol update marker exists")
    descriptor: int | None = None
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            design.require(written > 0, "protocol persistence made no progress")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        if descriptor is not None:
            os.close(descriptor)
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    relative = path.relative_to(output).as_posix()
    return {"path": relative, "sha256": design.sha(raw), "bytes": len(raw)}


def read_protocol(
    output: str | Path,
    descriptor: Mapping[str, Any],
    *,
    require_terminal: bool = True,
) -> dict[str, Any]:
    """Read and authenticate a condition protocol for replay."""

    design.require(
        type(descriptor) is dict
        and set(descriptor) == {"path", "sha256", "bytes"}
        and isinstance(descriptor.get("path"), str)
        and isinstance(descriptor.get("sha256"), str)
        and type(descriptor.get("bytes")) is int,
        "private protocol descriptor is malformed",
    )
    relative = Path(descriptor["path"])
    design.require(
        not relative.is_absolute()
        and relative.parts[:2] == ("private", "protocols")
        and ".." not in relative.parts,
        "private protocol path is invalid",
    )
    output_path = Path(os.path.abspath(Path(output).expanduser()))
    path = output_path / relative
    try:
        raw, resolved = harness._read_regular_file(
            path,
            label="private v2 condition protocol",
            max_bytes=4_000_000,
        )
    except harness.HarnessError as error:
        raise design.CalibrationError("private protocol is unavailable or redirected") from error
    design.require(
        resolved == Path(os.path.abspath(path)),
        "private protocol resolved path differs",
    )
    design.require(
        len(raw) == descriptor["bytes"] and design.sha(raw) == descriptor["sha256"],
        "private protocol bytes differ",
    )
    try:
        value = harness._strict_object(raw, "private v2 condition protocol")
    except harness.HarnessError as error:
        raise design.CalibrationError("private protocol JSON is invalid") from error
    design.require(
        set(value) == {field.name for field in fields(ConditionProtocol)}
        and value.get("schema_version") == PRIVATE_PROTOCOL_SCHEMA,
        "private protocol schema differs",
    )
    allowed_stages = {
        "initialized",
        "wire_attempting",
        "classified",
        "execution_attempting",
        "execution_persisted",
        "terminal",
    }
    design.require(value.get("stage") in allowed_stages, "private protocol stage differs")
    if require_terminal:
        design.require(value["stage"] == "terminal", "private protocol is incomplete")
    return value


def _call_evidence(call: wire.Call) -> dict[str, Any]:
    return {
        "status": call.status,
        "dispatch_state": call.dispatch_state,
        "content": call.content,
        "reasoning_content": call.reasoning_content,
        "tool_calls": copy.deepcopy(list(call.tool_calls)),
        "receipt": copy.deepcopy(call.receipt),
        "descriptor": copy.deepcopy(call.descriptor),
    }


def _issued_slot(call: wire.Call, slot_id: str) -> dict[str, Any]:
    disposition = "returned" if call.status == "returned" else "failed"
    return {
        "slot_id": slot_id,
        "disposition": disposition,
        "status": call.status,
        "failure_code": call.receipt.get("failure_code"),
        "dispatch_state": call.dispatch_state,
        "call": copy.deepcopy(call.receipt),
        "private_descriptor": copy.deepcopy(call.descriptor),
    }


def _unissued_slot(slot_id: str, disposition: str, failure_code: str) -> dict[str, Any]:
    design.require(
        disposition in {"skipped_unissued", "unissued_after_abort"},
        "unissued disposition invalid",
    )
    return {
        "slot_id": slot_id,
        "disposition": disposition,
        "status": "skipped" if disposition == "skipped_unissued" else "not_run",
        "failure_code": failure_code,
        "dispatch_state": "not_issued",
        "call": None,
        "private_descriptor": None,
    }


def account(slots: list[dict[str, Any]]) -> dict[str, int]:
    """Verify and count an exhaustive fixed-denominator slot list."""

    counts = {
        "declared_slots": len(slots),
        "attempted_calls": 0,
        "confirmed_dispatched_calls": 0,
        "wire_unknown_attempts": 0,
        "prewire_failures": 0,
        "returned_calls": 0,
        "failed_calls": 0,
        "skipped_unissued": 0,
        "unissued_after_abort": 0,
    }
    dispatch_counts = {
        "confirmed_dispatched": "confirmed_dispatched_calls",
        "wire_unknown": "wire_unknown_attempts",
        "prewire_failure": "prewire_failures",
    }
    for slot in slots:
        disposition = slot.get("disposition")
        if disposition in {"returned", "failed"}:
            receipt = slot.get("call")
            design.require(
                type(receipt) is dict
                and type(slot.get("private_descriptor")) is dict
                and disposition
                == ("returned" if receipt.get("status") == "returned" else "failed")
                and slot.get("status") == receipt.get("status")
                and slot.get("failure_code") == receipt.get("failure_code")
                and slot.get("dispatch_state") == receipt.get("dispatch_state")
                and slot.get("dispatch_state") in dispatch_counts,
                "issued slot does not derive from its call receipt",
            )
            counts["attempted_calls"] += 1
            counts["returned_calls" if disposition == "returned" else "failed_calls"] += 1
            counts[dispatch_counts[slot["dispatch_state"]]] += 1
        else:
            design.require(
                disposition in {"skipped_unissued", "unissued_after_abort"}
                and slot.get("status")
                == ("skipped" if disposition == "skipped_unissued" else "not_run")
                and isinstance(slot.get("failure_code"), str)
                and bool(slot["failure_code"])
                and slot.get("dispatch_state") == "not_issued"
                and slot.get("call") is None
                and slot.get("private_descriptor") is None,
                "unissued slot receipt is malformed",
            )
            counts[disposition] += 1
    design.require(
        counts["returned_calls"]
        + counts["failed_calls"]
        + counts["skipped_unissued"]
        + counts["unissued_after_abort"]
        == counts["declared_slots"],
        "slot accounting is not exhaustive",
    )
    design.require(
        counts["confirmed_dispatched_calls"]
        + counts["wire_unknown_attempts"]
        + counts["prewire_failures"]
        == counts["attempted_calls"],
        "dispatch accounting is not exhaustive",
    )
    return counts


def _public_classification(
    classification: core.ToolTurnClassification | None,
) -> dict[str, Any] | None:
    if classification is None:
        return None
    return {
        "transport_status": classification.transport_status,
        "transport_returned": classification.transport_returned,
        "receipt_complete": classification.receipt_complete,
        "finish_reason_tool_calls": classification.finish_reason_tool_calls,
        "tool_calls_container": classification.tool_calls_container,
        "single_tool_call": classification.single_tool_call,
        "call_shape_valid": classification.call_shape_valid,
        "call_text_encoding_valid": classification.call_text_encoding_valid,
        "tool_name_valid": classification.tool_name_valid,
        "arguments_text_within_bound": classification.arguments_text_within_bound,
        "arguments_depth_within_bound": classification.arguments_depth_within_bound,
        "arguments_json_valid": classification.arguments_json_valid,
        "arguments_contract_valid": classification.arguments_contract_valid,
        "arguments_exact": classification.arguments_exact,
        "pretool_content": {
            "state": classification.pretool_content.state,
            "type_valid": classification.pretool_content.type_valid,
            "encoding_valid": classification.pretool_content.encoding_valid,
            "utf8_bytes": classification.pretool_content.utf8_bytes,
            "within_bound": classification.pretool_content.within_bound,
        },
        "reasoning_content": {
            "state": classification.reasoning_content.state,
            "type_valid": classification.reasoning_content.type_valid,
            "encoding_valid": classification.reasoning_content.encoding_valid,
            "utf8_bytes": classification.reasoning_content.utf8_bytes,
            "within_bound": classification.reasoning_content.within_bound,
        },
        "call_count": classification.call_count,
        "execution_eligible": classification.execution_eligible,
        "strict_v1_comparable": classification.strict_v1_comparable,
        "failure_codes": list(classification.failure_codes),
        "record_sha256": design.sha(design.canonical(record(classification))),
    }


def _public_execution(execution: core.ExecutionOutcome | None) -> dict[str, Any] | None:
    if execution is None:
        return None
    return {
        "execution_attempted": execution.execution_attempted,
        "execution_succeeded": execution.execution_succeeded,
        "result_contract_valid": execution.result_contract_valid,
        "source_binding_sha256": execution.source_binding_sha256,
        "retained_result_sha256": execution.retained_result_sha256,
        "failure_code": execution.failure_code,
        "error_type": execution.error_type,
        "record_sha256": design.sha(design.canonical(record(execution))),
    }


def _not_run_final(cell: dict[str, Any]) -> dict[str, Any]:
    return design.final_grade(None, "not_run", None, (), cell)


def run(
    plan_path: str | Path,
    output_dir: str | Path,
    *,
    cancel_event: Any,
    invoke_fn: Callable[..., dict[str, Any]] = transport.complete,
    runtime_snapshot_fn: Callable[[], dict[str, Any]] = resident._live_runtime_binding,
    ready_fn: Callable[[], bool] = resident._ready,
    memory_fn: Callable[[], float] = resident._available_gib,
    idle_probe_fn: Callable[[], dict[str, Any]] = resident._endpoint_idle_probe,
    lock_factory: Callable[[Path], Any] = resource_lease,
    monotonic: Callable[[], float] = time.monotonic,
    executors: Mapping[str, Callable[[dict[str, Any]], Any]] | None = None,
) -> dict[str, Any]:
    """Run every frozen v2 condition or give each planned slot one disposition."""

    # Refuse before loading any mutable source-dependent plan material.  An
    # existing directory may contain a durable in-flight marker from a crash.
    requested_output = Path(output_dir).resolve(strict=False)
    design.require(
        not requested_output.exists(), "output already exists; v2 runs never resume"
    )
    plan, plan_sha = design.load_plan(plan_path)
    design.require(callable(getattr(cancel_event, "is_set", None)), "cancel event missing")
    output = resident._artifact_path(
        Path(output_dir),
        Path(plan["artifact_policy"]["private_root"]),
        label="payoff action v2 output",
    )
    design.require(not output.exists(), "output already exists; v2 runs never resume")
    if executors is not None:
        design.require(type(executors) is dict, "executor overrides must be a dict")
        design.require(
            set(executors).issubset({"table", "calculator"})
            and all(callable(value) for value in executors.values()),
            "executor overrides are malformed",
        )

    started = monotonic()
    deadline = started + design.EVALUATOR_BUDGET_S
    slots: dict[str, dict[str, Any]] = {}
    outcomes: list[dict[str, Any]] = []
    resource_observations: list[dict[str, Any]] = []
    ordinal = 0
    abort_reason: str | None = None

    def observe(stage: str, slot_id: str) -> tuple[dict[str, Any], Any]:
        observation = {
            "stage": stage,
            "slot_id": slot_id,
            "ready": None,
            "memory_gib": None,
            "runtime_identity_matches": None,
            "elapsed_s": max(0.0, monotonic() - started),
            "error": None,
        }
        current = None
        try:
            ready = ready_fn()
            available = float(memory_fn())
            design.require(math.isfinite(available), "memory probe is non-finite")
            current = runtime_snapshot_fn() if ready else None
            observation.update(
                ready=ready,
                memory_gib=available,
                runtime_identity_matches=current == plan["runtime_binding"],
            )
        except Exception as error:  # noqa: BLE001 - bounded public state evidence
            observation["error"] = (
                f"{type(error).__name__}:runtime probe failed"
            )
        resource_observations.append(observation)
        return observation, current

    def can_issue(slot_id: str) -> bool:
        nonlocal abort_reason
        if abort_reason is not None:
            return False
        if cancel_event.is_set():
            abort_reason = "cancelled_before_next_call"
            return False
        if deadline - monotonic() < design.CALL_TIMEOUT_S + 0.05:
            abort_reason = "evaluator_budget_before_next_call"
            return False
        observation, current = observe("pre_call", slot_id)
        if observation["error"] is not None:
            abort_reason = "runtime_probe_failed_before_next_call"
        elif observation["ready"] is not True:
            abort_reason = "Flash_not_ready_before_next_call"
        elif observation["memory_gib"] < design.MEMORY_FLOOR_GIB:
            abort_reason = "memory_floor_before_next_call"
        elif current != plan["runtime_binding"]:
            abort_reason = "runtime_identity_changed_before_next_call"
        elif cancel_event.is_set():
            abort_reason = "cancelled_after_pre_call_probes"
        elif deadline - monotonic() < design.CALL_TIMEOUT_S + 0.05:
            abort_reason = "evaluator_budget_after_pre_call_probes"
        return abort_reason is None

    def issue(
        slot_id: str,
        request_messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        seed: int,
        before_wire: Callable[[int], None],
    ) -> tuple[wire.Call, dict[str, Any]]:
        nonlocal ordinal, abort_reason
        design.require(
            ordinal < int(plan["limits"]["max_calls"]), "call budget exceeded"
        )
        before_wire(ordinal)
        call = wire.invoke(
            output=output,
            ordinal=ordinal,
            study_id=plan["study_id"],
            slot_id=slot_id,
            messages=request_messages,
            tools=tools,
            seed=seed,
            cancel_event=cancel_event,
            invoke_fn=invoke_fn,
            monotonic=monotonic,
        )
        ordinal += 1
        slot = _issued_slot(call, slot_id)
        post, current = observe("post_call", slot_id)
        if call.receipt.get("timeout_s") != design.CALL_TIMEOUT_S:
            abort_reason = f"shortened_timeout:{slot_id}"
        elif slot["dispatch_state"] == "prewire_failure":
            abort_reason = f"prewire_failure:{slot_id}"
        elif call.status == "cancelled":
            abort_reason = "transport_cancelled"
        elif call.status == "integrity_error":
            abort_reason = f"transport_evidence_integrity_error:{slot_id}"
        elif post["error"] is not None:
            abort_reason = f"runtime_probe_failed_after_call:{slot_id}"
        elif post["ready"] is not True:
            abort_reason = f"Flash_not_ready_after_call:{slot_id}"
        elif post["memory_gib"] < design.MEMORY_FLOOR_GIB:
            abort_reason = f"memory_floor_after_call:{slot_id}"
        elif current != plan["runtime_binding"]:
            abort_reason = f"runtime_identity_changed_after_call:{slot_id}"
        elif cancel_event.is_set():
            abort_reason = f"cancelled_after_call:{slot_id}"
        elif deadline - monotonic() < 0:
            abort_reason = f"evaluator_budget_after_call:{slot_id}"
        return call, slot

    with lock_factory(resident.CANONICAL_ROOT):
        design.require(plan["source_sha256"] == design.sources(), "source changed")
        admission_memory = float(memory_fn())
        design.require(
            ready_fn() is True
            and math.isfinite(admission_memory)
            and admission_memory >= design.MEMORY_FLOOR_GIB,
            "resident Flash or memory floor unavailable",
        )
        design.require(
            runtime_snapshot_fn() == plan["runtime_binding"],
            "runtime identity changed after plan freeze",
        )
        contention = idle_probe_fn()
        resident._validate_idle_observation(contention)
        design.require(contention["observed_idle"] is True, "endpoint busy before start")
        design.require(not cancel_event.is_set(), "calibration cancelled during admission")
        # The claim is intentionally permanent.  If anything fails after this
        # point, a retry cannot distinguish whether an external effect occurred.
        plan_claim = _claim_plan(
            Path(plan["artifact_policy"]["private_root"]),
            study_id=plan["study_id"],
            plan_raw_sha256=plan_sha,
            output=output,
        )
        # exist_ok=False is a second in-lock refusal against creation races.
        output.mkdir(mode=0o700, parents=True, exist_ok=False)
        output.chmod(0o700)

        for cell in plan["scenarios"]:
            for arm in cell["arm_order"]:
                condition_id = f"{cell['cell_id']}/{arm}"
                first_id = (
                    f"{cell['cell_id']}/direct"
                    if arm == "direct"
                    else f"{cell['cell_id']}/{arm}_first"
                )
                final_id = None if arm == "direct" else f"{cell['cell_id']}/{arm}_final"
                protocol_ordinal = plan["declared_conditions"].index(condition_id)
                protocol = ConditionProtocol(
                    schema_version=PRIVATE_PROTOCOL_SCHEMA,
                    condition_id=condition_id,
                    cell_id=cell["cell_id"],
                    arm=arm,
                    first_slot_id=first_id,
                    final_slot_id=final_id,
                    stage="initialized",
                )
                protocol_descriptor = _persist_protocol(
                    output, protocol_ordinal, protocol
                )
                calls: list[dict[str, Any]] = []
                classification: core.ToolTurnClassification | None = None
                execution: core.ExecutionOutcome | None = None
                continuation_sha: str | None = None
                final_issued = False

                def persist(next_protocol: ConditionProtocol) -> None:
                    nonlocal protocol, protocol_descriptor
                    protocol = next_protocol
                    protocol_descriptor = _persist_protocol(
                        output, protocol_ordinal, protocol  # noqa: B023
                    )

                def mark_wire(slot_id: str, call_ordinal: int) -> None:
                    marker = {
                        "slot_id": slot_id,
                        "call_ordinal": call_ordinal,
                        "state": "attempting",
                    }
                    persist(
                        replace(
                            protocol,  # noqa: B023
                            stage="wire_attempting",
                            wire_attempts=(*protocol.wire_attempts, marker),  # noqa: B023
                        )
                    )

                if abort_reason is not None or not can_issue(first_id):
                    reason = abort_reason or "aborted"
                    slots[first_id] = _unissued_slot(
                        first_id, "unissued_after_abort", reason
                    )
                    if final_id is not None:
                        slots[final_id] = _unissued_slot(
                            final_id, "unissued_after_abort", reason
                        )
                    final_grade = _not_run_final(cell)
                    persist(
                        replace(
                            protocol,
                            stage="terminal",
                            final_grade=copy.deepcopy(final_grade),
                            failure_code=reason,
                        )
                    )
                elif arm == "direct":
                    first, first_slot = issue(
                        first_id,
                        design.messages(cell, arm),
                        [],
                        cell["seed"],
                        lambda call_ordinal, sid=first_id: mark_wire(
                            sid, call_ordinal
                        ),
                    )
                    slots[first_id] = first_slot
                    calls.append(copy.deepcopy(first.receipt))
                    final_issued = (
                        type(first.receipt) is dict
                        and first.receipt.get("call_id")
                        == f"{plan['study_id']}/{first_id}"
                    )
                    final_grade = design.final_grade(
                        first.content,
                        first.status,
                        first.receipt,
                        first.tool_calls,
                        cell,
                    )
                    persist(
                        replace(
                            protocol,
                            stage="terminal",
                            first_call=_call_evidence(first),
                            final_grade=copy.deepcopy(final_grade),
                            failure_code=first.receipt.get("failure_code"),
                        )
                    )
                else:
                    first, first_slot = issue(
                        first_id,
                        design.messages(cell, arm),
                        [design.tool_spec(arm)],
                        cell["seed"],
                        lambda call_ordinal, sid=first_id: mark_wire(
                            sid, call_ordinal
                        ),
                    )
                    slots[first_id] = first_slot
                    calls.append(copy.deepcopy(first.receipt))
                    classification = core.classify_tool_turn(
                        status=first.status,
                        receipt=first.receipt,
                        tool_calls=first.tool_calls,
                        content=first.content,
                        reasoning_content=first.reasoning_content,
                        expectation=design.expectation(cell, arm),
                    )
                    persist(
                        replace(
                            protocol,
                            stage="classified",
                            first_call=_call_evidence(first),
                            classification=record(classification),
                            failure_code=(
                                classification.failure_codes[0]
                                if classification.failure_codes
                                else None
                            ),
                        )
                    )
                    if classification.execution_eligible:
                        marker = {
                            "state": "attempting",
                            "source_binding_sha256": (
                                classification.execution_binding_sha256
                            ),
                        }
                        persist(
                            replace(
                                protocol,
                                stage="execution_attempting",
                                execution_marker=marker,
                            )
                        )
                        executor = (
                            executors[arm]
                            if executors is not None and arm in executors
                            else design.executor_for(arm)
                        )
                        execution = core.execute_once(
                            classification,
                            executor=executor,
                            result_validator=design.result_validator_for(arm),
                        )
                        if (
                            execution.execution_succeeded == core.PASS
                            and execution.result_contract_valid == core.PASS
                        ):
                            scaffold = core.build_empty_content_continuation(
                                classification, execution
                            )
                            assistant_message, tool_message = scaffold.messages()
                            continuation_messages = [
                                *design.messages(cell, arm),
                                assistant_message,
                                tool_message,
                                copy.deepcopy(_FINAL_INSTRUCTION),
                            ]
                            continuation_sha = design.sha(
                                design.canonical(continuation_messages)
                            )
                            persist(
                                replace(
                                    protocol,
                                    stage="execution_persisted",
                                    execution=record(execution),
                                    continuation=record(scaffold),
                                    continuation_request_messages=tuple(
                                        copy.deepcopy(continuation_messages)
                                    ),
                                    continuation_messages_sha256=continuation_sha,
                                    failure_code=None,
                                )
                            )
                            if abort_reason is None and can_issue(final_id):
                                final, final_slot = issue(
                                    final_id,
                                    continuation_messages,
                                    [],
                                    cell["seed"],
                                    lambda call_ordinal, sid=final_id: mark_wire(
                                        sid, call_ordinal
                                    ),
                                )
                                design.require(
                                    final.receipt.get("messages_sha256")
                                    == continuation_sha,
                                    "final request is not bound to retained continuation",
                                )
                                slots[final_id] = final_slot
                                calls.append(copy.deepcopy(final.receipt))
                                final_issued = (
                                    type(final.receipt) is dict
                                    and final.receipt.get("call_id")
                                    == f"{plan['study_id']}/{final_id}"
                                )
                                final_grade = design.final_grade(
                                    final.content,
                                    final.status,
                                    final.receipt,
                                    final.tool_calls,
                                    cell,
                                )
                                persist(
                                    replace(
                                        protocol,
                                        stage="terminal",
                                        final_call=_call_evidence(final),
                                        final_grade=copy.deepcopy(final_grade),
                                        failure_code=final.receipt.get(
                                            "failure_code"
                                        ),
                                    )
                                )
                            else:
                                reason = abort_reason or "final_not_issued"
                                slots[final_id] = _unissued_slot(
                                    final_id,
                                    "unissued_after_abort",
                                    reason,
                                )
                                final_grade = _not_run_final(cell)
                                persist(
                                    replace(
                                        protocol,
                                        stage="terminal",
                                        final_grade=copy.deepcopy(final_grade),
                                        failure_code=reason,
                                    )
                                )
                        else:
                            reason = execution.failure_code or "tool_execution_failed"
                            abort_reason = f"{reason}:{condition_id}"
                            slots[final_id] = _unissued_slot(
                                final_id, "unissued_after_abort", abort_reason
                            )
                            final_grade = _not_run_final(cell)
                            persist(
                                replace(
                                    protocol,
                                    stage="terminal",
                                    execution=record(execution),
                                    final_grade=copy.deepcopy(final_grade),
                                    failure_code=reason,
                                )
                            )
                    else:
                        reason = (
                            classification.failure_codes[0]
                            if classification.failure_codes
                            else "execution_ineligible"
                        )
                        slots[final_id] = _unissued_slot(
                            final_id,
                            (
                                "unissued_after_abort"
                                if abort_reason is not None
                                else "skipped_unissued"
                            ),
                            abort_reason or reason,
                        )
                        final_grade = _not_run_final(cell)
                        persist(
                            replace(
                                protocol,
                                stage="terminal",
                                final_grade=copy.deepcopy(final_grade),
                                failure_code=reason,
                            )
                        )

                outcomes.append(
                    {
                        "condition_id": condition_id,
                        "cell_id": cell["cell_id"],
                        "arm": arm,
                        "calls": calls,
                        "classification": _public_classification(classification),
                        "execution": _public_execution(execution),
                        "continuation_policy": (
                            design.CONTINUATION_POLICY if arm != "direct" else None
                        ),
                        "continuation_messages_sha256": continuation_sha,
                        "final_issued": final_issued,
                        "final_grade": copy.deepcopy(final_grade),
                        "protocol": copy.deepcopy(protocol_descriptor),
                    }
                )

        if cancel_event.is_set() and abort_reason is None:
            abort_reason = "cancelled_after_last_call"
        for slot_id in plan["declared_slots"]:
            slots.setdefault(
                slot_id,
                _unissued_slot(
                    slot_id,
                    "unissued_after_abort",
                    abort_reason or "not_reached",
                ),
            )
        design.require(
            {outcome["condition_id"] for outcome in outcomes}
            == set(plan["declared_conditions"]),
            "condition accounting is not exhaustive",
        )
        ordered_slots = [slots[slot_id] for slot_id in plan["declared_slots"]]
        accounting = account(ordered_slots)
        design.require(
            accounting["attempted_calls"] <= int(plan["limits"]["max_calls"]),
            "call budget exceeded",
        )
        result = {
            "schema_version": design.RUN_SCHEMA,
            "status": "aborted" if abort_reason is not None else "complete",
            "study_id": plan["study_id"],
            "cohort": plan["cohort"],
            "plan_raw_sha256": plan_sha,
            "plan_claim": plan_claim,
            "source_sha256": copy.deepcopy(plan["source_sha256"]),
            "runtime_binding": copy.deepcopy(plan["runtime_binding"]),
            "core_contract": core.CONTRACT_VERSION,
            "continuation_policy": design.CONTINUATION_POLICY,
            "declared_units": copy.deepcopy(plan["declared_units"]),
            "declared_conditions": copy.deepcopy(plan["declared_conditions"]),
            "declared_slots": copy.deepcopy(plan["declared_slots"]),
            "slots": ordered_slots,
            "outcomes": outcomes,
            "accounting": accounting,
            "contention_observation": contention,
            "resource_observations": resource_observations,
            "abort_reason": abort_reason,
            "elapsed_s": max(0.0, monotonic() - started),
            "weekly_two_hour_debit": False,
            "permanently_excluded": True,
            "scientific_admission_eligible": False,
            "scientific_admission_registered": False,
            "confirmation_authorized": False,
            "production_change_authorized": False,
            "promotion_authorized": False,
            "claim_limit": plan["claim_limit"],
            "private_content_exported": False,
        }
        with (output / "run.json").open("xb") as stream:
            stream.write(design.canonical(result) + b"\n")
        (output / "run.json").chmod(0o600)
        return result


__all__ = [
    "PLAN_CLAIM_SCHEMA",
    "PRIVATE_PROTOCOL_SCHEMA",
    "ConditionProtocol",
    "account",
    "claim_path",
    "classification_from_record",
    "continuation_from_record",
    "execution_from_record",
    "final_grade_from_record",
    "protocol_path",
    "read_plan_claim",
    "read_protocol",
    "record",
    "run",
    "unrecord",
]
