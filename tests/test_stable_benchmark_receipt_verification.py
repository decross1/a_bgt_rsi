from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from bench.stable_benchmark import (
    bind_run_manifest,
    load_definition,
    load_run_manifest,
    make_draft,
    publish_definition,
    run_arm,
    write_unissued_receipt,
)
from bench.stable_benchmark import supervised_window as window
from bench.stable_benchmark.admission import admission_source_hashes
from bench.stable_benchmark.manifest import canonical_json, write_document
from bench.stable_benchmark.receipt_verification import (
    ReceiptVerificationError,
    load_registration,
    verify_registered_comparison,
)
from bench.stable_benchmark.replay import replay_source_hashes
from bench.stable_benchmark.runner import (
    InvocationRequest,
    InvocationResult,
    execution_source_hashes,
)

ZERO = "0" * 64
ONE = "1" * 64


def _write(path: Path, value: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = canonical_json(value) + b"\n"
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _identities() -> dict[str, dict]:
    return {
        "vllm-gemma": {
            "served_model": "gemma-4-26b-a4b",
            "artifact_sha256": ZERO,
            "runtime_sha256": ONE,
            "max_context_tokens": 32768,
        },
        "vllm-qwen": {
            "served_model": "qwen3.8-27b-nvfp4-mtp",
            "artifact_sha256": ONE,
            "runtime_sha256": ZERO,
            "max_context_tokens": 16384,
        },
    }


def _route(backend: str, profile: str, identity: dict, effort: str | None) -> dict:
    return {
        "backend": backend,
        "model": identity["served_model"],
        "profile": profile,
        "expected_policy": {
            "temperature": 0.2,
            "top_p": 0.95,
            "reasoning_effort": effort,
            "sampling_extra": {},
        },
        "runtime_identity": identity,
    }


def _arm(arm_id: str) -> dict:
    identities = _identities()
    return {
        "id": arm_id,
        "label": arm_id,
        "seed": 17,
        "routes": {
            "gemma": _route("vllm-gemma", "precise", identities["vllm-gemma"], None),
            "qwen": _route(
                "vllm-qwen", "critic_current", identities["vllm-qwen"], "xhigh"
            ),
        },
        "role_map": {
            "capability": "gemma",
            "system_actor": "gemma",
            "system_critic": "qwen",
        },
    }


class _NeverCancel:
    def is_set(self) -> bool:
        return False


class _Monitor:
    phase = "evaluation"


def _registration_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    program = tmp_path / "program"
    lifecycle_root = tmp_path / "lifecycle" / "windows"
    monkeypatch.setattr(window, "PROGRAM_ROOT", program)
    monkeypatch.setattr(window, "DEFINITION_PATH", program / "definition.published.json")
    monkeypatch.setattr(window, "MANIFEST_ROOT", program / "manifests")
    monkeypatch.setattr(window, "RUN_ROOT", program / "runs")
    monkeypatch.setattr(
        window,
        "REGISTERED_PROGRAM_ROOTS",
        {"1.0.0": program, "1.1.0": program},
    )
    monkeypatch.setattr(window, "WINDOW_ROOT", lifecycle_root)

    definition_document = publish_definition(
        make_draft(),
        published_at="2026-09-16T00:00:00Z",
        witness={"kind": "preregistration_receipt", "ref": "test", "sha256": ONE},
    )
    write_document(window.DEFINITION_PATH, definition_document)
    definition = load_definition(window.DEFINITION_PATH, require_published=True)

    manifests = {}
    for arm_id in ("resident-stack-v1", "flash-stack-v1"):
        document = bind_run_manifest(
            definition,
            arm=_arm(arm_id),
            comparison_id="stable-comparison-v1",
            harness_identity={
                "scaffold_id": "stable-benchmark-runner-v1",
                "transport_contract": "injected-supervised-endpoint/v1",
                "source_sha256": execution_source_hashes(),
            },
        )
        path = window.MANIFEST_ROOT / f"stable-comparison-v1.{arm_id}.json"
        write_document(path, document)
        manifests[arm_id] = load_run_manifest(path, definition)

    resident = manifests["resident-stack-v1"]
    sources = {"bench/controller.py": "2" * 64}
    certificate = (
        {
            "qualification_receipt_sha256": ZERO,
            "artifact_inventory_sha256": ONE,
            "probe_scope": "fixed_literal_and_arithmetic_only",
        },
        _identities(),
    )
    plan = window.build_plan(
        definition,
        resident,
        window_id="stable-benchmark-20260916-a.resident",
        git_head="a" * 40,
        sources=sources,
        resident_certificate=certificate,
    )
    lifecycle_dir = Path(plan["window_dir"])
    lifecycle_dir.mkdir(parents=True)
    plan_sha = _write(lifecycle_dir / "window.json", plan)
    quiet = {
        "residents_by_name": {
            registered["name"]: {"id": registered["id"], "image": registered["image_id"]}
            for registered in window.RESIDENTS
        },
        "nara": {"ActiveState": "inactive"},
    }
    gate = window.freeze_execution_gate(
        definition,
        resident,
        plan=plan,
        window_dir=lifecycle_dir,
        quiet=quiet,
        monitor=_Monitor(),
        start_sample={"mem_available_gib": 40.0},
        sentinel_id="f" * 64,
    )

    arm = resident.document["arm"]

    def invoke(request: InvocationRequest) -> InvocationResult:
        role = "system_actor" if request.task["mode"] == "system_mission" else "capability"
        route = arm["routes"][arm["role_map"][role]]
        record = {
            "request_id": f"request-{request.task['id']}",
            "model": route["model"],
            "model_version": "test-runtime",
            "backend": route["backend"],
            "profile": route["profile"],
            "temperature": route["expected_policy"]["temperature"],
            "top_p": route["expected_policy"]["top_p"],
            "reasoning_effort": route["expected_policy"]["reasoning_effort"],
            "sampling_extra": route["expected_policy"]["sampling_extra"],
            "seed": arm["seed"],
            "max_tokens": request.task["resource"]["max_tokens_per_call"],
            "host_metadata": {"test": True},
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }
        return InvocationResult(
            completion="{}",
            records=(record,),
            failure_code="synthetic_invalid_output",
            failure_detail="verification fixture",
            attempt_count=1,
        )

    run_dir = Path(plan["run_dir"])
    run_arm(
        definition,
        resident,
        output_dir=run_dir,
        execution_gate=gate,
        absolute_deadline_monotonic=time.monotonic() + 30,
        cancel_event=_NeverCancel(),
        invoke=invoke,
    )
    for name in ("endpoint-bindings.json", "supervision-ready.json", "resource-guard.json"):
        (run_dir / name).write_bytes((lifecycle_dir / name).read_bytes())
    run_sha = hashlib.sha256((run_dir / "run.json").read_bytes()).hexdigest()
    gate_sha = hashlib.sha256((run_dir / "execution-gate.snapshot.json").read_bytes()).hexdigest()
    endpoint = json.loads((lifecycle_dir / "endpoint-bindings.json").read_text())
    ready = json.loads((lifecycle_dir / "supervision-ready.json").read_text())
    endpoint_frozen = datetime.fromisoformat(endpoint["frozen_at"])
    process_started = endpoint_frozen - timedelta(seconds=2)
    state_started = endpoint_frozen - timedelta(seconds=1)
    worker_pid = ready["worker_pid"]
    worker_ticks = ready["worker_start_ticks"]
    boot_id = ready["boot_id"]
    argv = [
        plan["launcher_python_path"], "-m", "bench.stable_benchmark.supervised_window",
        "--worker", "--window-id", plan["window_id"], "--run-manifest", str(resident.path),
    ]
    argv_sha = hashlib.sha256(canonical_json(argv)).hexdigest()
    _write(lifecycle_dir / "process.json", {
        "schema_version": window.PROCESS_SCHEMA,
        "window_id": plan["window_id"],
        "plan_sha256": plan_sha,
        "pid": worker_pid,
        "pgid": worker_pid,
        "worker_start_ticks": worker_ticks,
        "boot_id": boot_id,
        "argv_sha256": argv_sha,
        "started_at": process_started.isoformat(),
    })
    _write(lifecycle_dir / "state.json", {
        "schema_version": window.STATE_SCHEMA,
        "window_id": plan["window_id"],
        "plan_sha256": plan_sha,
        "definition_sha256": definition.raw_sha256,
        "run_manifest_sha256": resident.raw_sha256,
        "worker_pid": worker_pid,
        "worker_start_ticks": worker_ticks,
        "boot_id": boot_id,
        "started_at": state_started.isoformat(),
        "phase": "complete",
        "result_status": "complete",
        "execution_gate_sha256": gate_sha,
        "restoration": {"status": "verified"},
    })
    memory_log = canonical_json({"sample": 1}) + b"\n" + canonical_json({"sample": 2}) + b"\n"
    (lifecycle_dir / "resident-memory.jsonl").write_bytes(memory_log)
    result_finished = datetime.now(timezone.utc)
    result_sha = _write(lifecycle_dir / "result.json", {
        "schema_version": window.RESULT_SCHEMA,
        "window_id": plan["window_id"],
        "status": "complete",
        "plan_sha256": plan_sha,
        "definition_sha256": definition.raw_sha256,
        "run_manifest_sha256": resident.raw_sha256,
        "run_receipt_sha256": run_sha,
        "execution_gate_sha256": gate_sha,
        "preflight": {},
        "initial_observation": {},
        "quiet_observation": {},
        "final_observation": {},
        "monitor_end_passed": True,
        "no_guard_breach": True,
        "restoration_passed": True,
        "restoration": {"status": "verified", "errors": [], "sentinel_retained": False},
        "memory_samples": 2,
        "min_mem_available_gib": 30.0,
        "memory_log_sha256": hashlib.sha256(memory_log).hexdigest(),
        "nara_downtime_seconds": 0.0,
        "error": None,
        "failure_stage": None,
        "paid_api_calls": 0,
        "production_change_authorized": False,
        "finished_at": result_finished.isoformat().replace("+00:00", "Z"),
    })
    replay, admission, error = window.finalize_run(
        definition,
        resident,
        plan=plan,
        window_dir=lifecycle_dir,
        run_dir=run_dir,
        lifecycle_valid=True,
        lifecycle_result={
            "monitor_end_passed": True,
            "no_guard_breach": True,
            "restoration_passed": True,
        },
    )
    assert error is None and replay is not None and admission is not None
    supervision_finished = datetime.now(timezone.utc)
    _write(lifecycle_dir / "supervision.json", {
        "schema_version": window.SUPERVISION_SCHEMA,
        "window_id": plan["window_id"],
        "plan_sha256": plan_sha,
        "command_sha256": argv_sha,
        "argv": argv,
        "pid": worker_pid,
        "worker_start_ticks": worker_ticks,
        "boot_id": boot_id,
        "started_at": process_started.isoformat(),
        "hard_deadline_at": (
            process_started + timedelta(seconds=plan["window_deadline_seconds"])
        ).isoformat(),
        "returncode": 0,
        "complete": True,
        "terminated_at_work_cutoff": False,
        "force_killed": False,
        "emergency_recovery": None,
        "lifecycle_result_sha256": result_sha,
        "replay_terminal_status": "verified",
        "admission_status": "admitted",
        "finalization_error": None,
        "elapsed_seconds": (supervision_finished - process_started).total_seconds(),
        "finished_at": supervision_finished.isoformat(),
    })

    candidate = manifests["flash-stack-v1"]
    candidate_dir = window.RUN_ROOT / "stable-comparison-v1" / "flash-stack-v1"
    write_unissued_receipt(
        definition,
        candidate,
        output_dir=candidate_dir,
        reason="candidate failed its separately registered runtime gate before any suite call",
    )
    registration = {
        "schema_version": "stable-benchmark-comparison-registration/v1",
        "suite_id": definition.document["suite_id"],
        "release": definition.document["release"],
        "comparison_id": "stable-comparison-v1",
        "registered_at": "2026-09-16T00:01:00Z",
        "definition": {"path": str(definition.path), "sha256": definition.raw_sha256},
        "arms": [
            {
                "arm_id": "resident-stack-v1",
                "role": "reference",
                "manifest": {"path": str(resident.path), "sha256": resident.raw_sha256},
                "run_receipt_directory": str(run_dir),
                "execution_source_sha256": execution_source_hashes(),
                "replay_source_sha256": replay_source_hashes(),
                "admission_source_sha256": admission_source_hashes(),
                "lifecycle": {
                    "window_id": plan["window_id"],
                    "window_plan_sha256": plan_sha,
                    "worker_argv_sha256": argv_sha,
                    "controller_source_sha256": sources,
                    "receipt_directory": str(lifecycle_dir),
                },
            },
            {
                "arm_id": "flash-stack-v1",
                "role": "candidate",
                "manifest": {"path": str(candidate.path), "sha256": candidate.raw_sha256},
                "run_receipt_directory": str(candidate_dir),
                "execution_source_sha256": execution_source_hashes(),
                "replay_source_sha256": replay_source_hashes(),
                "admission_source_sha256": admission_source_hashes(),
                "lifecycle": None,
            },
        ],
    }
    registration_path = tmp_path / "repo" / "docs" / "benchmarks" / "registrations" / "stable-comparison-v1.json"
    _write(registration_path, registration)
    return definition, registration_path, lifecycle_dir


def test_registered_comparison_verifies_admitted_reference_and_unissued_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    definition, registration_path, _ = _registration_fixture(tmp_path, monkeypatch)
    registration = load_registration(registration_path, definition)
    reference, candidate = verify_registered_comparison(registration, definition=definition)
    assert reference.role == "reference"
    assert reference.admitted is True
    assert reference.admission_status == "admitted"
    assert reference.source_files_verified is False
    assert reference.resource_evidence_level == (
        "source_bound_supervisor_attestation_with_bounded_monitor_log_digest"
    )
    assert candidate.role == "candidate"
    assert candidate.terminal_status == "unissued"
    assert candidate.admitted is False
    assert candidate.resource_evidence_level is None


def test_registration_and_gate_tampering_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    definition, registration_path, lifecycle_dir = _registration_fixture(tmp_path, monkeypatch)
    value = json.loads(registration_path.read_text())
    value["arms"].reverse()
    _write(registration_path.with_name("reordered.json"), value)
    with pytest.raises(ReceiptVerificationError, match="reference then candidate"):
        load_registration(registration_path.with_name("reordered.json"), definition)

    registration = load_registration(registration_path, definition)
    endpoint = lifecycle_dir / "endpoint-bindings.json"
    endpoint.write_bytes(endpoint.read_bytes() + b" ")
    with pytest.raises(ReceiptVerificationError, match="copies differ|digest differs"):
        verify_registered_comparison(registration, definition=definition)


def test_lifecycle_identity_timeline_and_monitor_log_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    definition, registration_path, lifecycle_dir = _registration_fixture(tmp_path, monkeypatch)
    registration = load_registration(registration_path, definition)

    state_path = lifecycle_dir / "state.json"
    state_bytes = state_path.read_bytes()
    state = json.loads(state_bytes)
    state["worker_pid"] += 1
    _write(state_path, state)
    with pytest.raises(ReceiptVerificationError, match="different worker process identity"):
        verify_registered_comparison(registration, definition=definition)
    state_path.write_bytes(state_bytes)

    memory_path = lifecycle_dir / "resident-memory.jsonl"
    memory_bytes = memory_path.read_bytes()
    memory_path.write_bytes(memory_bytes + canonical_json({"sample": 3}) + b"\n")
    with pytest.raises(ReceiptVerificationError, match="log digest or sample count differs"):
        verify_registered_comparison(registration, definition=definition)
    memory_path.write_bytes(memory_bytes)

    supervision_path = lifecycle_dir / "supervision.json"
    supervision = json.loads(supervision_path.read_text())
    hard_deadline = datetime.fromisoformat(supervision["hard_deadline_at"])
    supervision["finished_at"] = (hard_deadline + timedelta(seconds=1)).isoformat()
    _write(supervision_path, supervision)
    with pytest.raises(ReceiptVerificationError, match="exceed supervision bounds"):
        verify_registered_comparison(registration, definition=definition)
