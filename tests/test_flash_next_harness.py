import copy
import hashlib
import json
import os
import stat
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from bench.flash_next_ab import qualification as q
from bench.flash_next_ab.compare import summarize_pair, validate_run
from bench.flash_next_ab.harness import (
    HarnessError,
    run_harness,
    validate_flash_qualification_files,
    validate_qualification_receipt,
    validate_resident_qualification_files,
)
from bench.flash_next_ab.manifest import (
    build_plan,
    make_arm_receipt,
    sha256_file,
)
from bench.flash_next_ab.transport import (
    TransportCancelled,
    canonical,
    request_body,
)


def arms():
    return [
        make_arm_receipt(
            "resident",
            qualification_receipt_sha256="1" * 64,
            artifact_sha256_by_endpoint={
                "resident_gemma": "2" * 64,
                "resident_qwen": "3" * 64,
            },
            runtime_sha256_by_endpoint={
                "resident_gemma": "4" * 64,
                "resident_qwen": "5" * 64,
            },
        ),
        make_arm_receipt(
            "flash",
            qualification_receipt_sha256="6" * 64,
            artifact_sha256_by_endpoint={"flash_next": "7" * 64},
            runtime_sha256_by_endpoint={"flash_next": "8" * 64},
        ),
    ]


def small_plan(count=1):
    full, _ = build_plan(arms(), families=["objective"])
    plan, _ = build_plan(
        arms(),
        families=["objective"],
        cell_ids=full["declared_cells"][:count],
    )
    return plan


def response(endpoint, messages, **kwargs):
    body = request_body(
        endpoint,
        messages,
        kwargs["policy"],
        kwargs["max_tokens"],
        kwargs["seed"],
        kwargs["tools"],
    )
    stream = b"data: private fake response\n\n"
    usage = {"prompt_tokens": 10, "completion_tokens": 1, "total_tokens": 11}
    result = {
        "request_sha256": hashlib.sha256(canonical(body)).hexdigest(),
        "response_stream_sha256": hashlib.sha256(stream).hexdigest(),
        "response_model": endpoint.served_model,
        "response_id": f"response-{endpoint.name}",
        "content": "{}",
        "reasoning_content": "private-reasoning",
        "tool_calls": [],
        "usage": usage,
        "finish_reason": "stop",
    }
    result["private_evidence"] = {
        "content": result["content"],
        "reasoning_content": result["reasoning_content"],
        "tool_calls": result["tool_calls"],
        "response_id": result["response_id"],
        "response_model": result["response_model"],
        "finish_reason": result["finish_reason"],
        "usage": usage,
        "stream_events": 1,
        "response_bytes": len(stream),
        "response_stream_sha256": result["response_stream_sha256"],
        "raw_response_stream": stream,
    }
    return result


def gate(_plan, _cohort):
    return None


def registered_contract(version=3):
    contract = {
        "schema": f"qwen-flash-next-qualification/v{version}",
        "contract_id": "qwen38-flash-next-c0-20260915",
        "profile": "C0",
        "image": {"id": q.IMAGE_ID, "architecture": "arm64"},
        "model": {
            "repository": q.MODEL_REPOSITORY,
            "revision": q.MODEL_REVISION,
            "host_path": str(q.MODEL_PATH),
            "container_path": "/models/qwen",
            "served_name": q.SERVED_MODEL,
            "safetensors_total_bytes": q.MODEL_TOTAL_BYTES,
            "tensor_payload_bytes": q.MODEL_TENSOR_BYTES,
            "repository_total_bytes": q.MODEL_REPOSITORY_BYTES,
            "artifact_sha256": q.model_artifact_sha256(),
            "files": q.expected_model_files(),
            "full_sha256_before_mutation": True,
        },
        "runtime": {
            "container_name": q.CONTAINER_NAME,
            "host_address": "127.0.0.1",
            "host_port": 8012,
            "container_port": 8000,
            "compile_cache_path": str(q.COMPILE_CACHE),
            "max_model_len": q.MAX_MODEL_LEN,
            "max_num_seqs": 1,
            "gpu_memory_utilization": 0.75,
            "kv_cache_memory_bytes": q.KV_CACHE_MEMORY_BYTES,
            "max_num_batched_tokens": 4096,
            "kv_cache_dtype": "auto",
            "mamba_ssm_cache_dtype": "float32",
            "mtp_speculative_tokens": 0,
            "prefix_caching": False,
            "async_scheduling": False,
            "qsa_exact_topk": True,
            "language_model_only": True,
        },
        "safety": {
            "resident_containers": [dict(row) for row in q.RESIDENTS],
            "nara_service": q.NARA_SERVICE,
            "min_mem_available_gib": 20,
            "invocation_deadline_seconds": 3600,
            "readiness_deadline_seconds": 1200,
            "restoration_reserve_seconds": 600,
            "setup_quiescence_seconds": 60,
            "memory_poll_seconds": 1,
            "probe_timeout_seconds": 120,
        },
        "accounting": {
            "class": "uncapped-local-model-research",
            "weekly_budget_debit": False,
            "paid_api_allowed": False,
            "journal_path": str(q.RESEARCH_LEDGER),
        },
        "probe_set": "flash-next-minimal-v1",
    }
    if version == 3:
        contract["safety"].update({
            "ready_quiescence_seconds": 60,
            "paging_policy": copy.deepcopy(q.PAGING_POLICY),
        })
    return contract


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


@pytest.fixture(autouse=True)
def registered_test_run_root(monkeypatch, tmp_path):
    monkeypatch.setattr(q, "OUTPUT_ROOT", tmp_path)


def passing_flash_receipts(tmp_path, version=3):
    tmp_path = tmp_path / "qfn-c0-test"
    tmp_path.mkdir()
    contract = registered_contract(version)
    contract_path = tmp_path / "launch-contract.snapshot.json"
    write_json(contract_path, contract)
    raw_contract_path = tmp_path / "launch-contract.raw.json"
    raw_contract_path.write_text(
        json.dumps(contract, sort_keys=False, separators=(",", ":")) + "\n"
    )
    contract_sha256 = sha256_file(raw_contract_path)
    launch = q.launch_argv()
    qualification_plan = {
        "schema": f"qwen-flash-next-qualification-plan/v{version}",
        "contract_id": contract["contract_id"],
        "contract_sha256": contract_sha256,
        "profile": "C0",
        "image_id": q.IMAGE_ID,
        "model_artifact_sha256": q.model_artifact_sha256(),
        "served_model": q.SERVED_MODEL,
        "docker_create_argv": launch,
        "docker_create_argv_sha256": q.sha256(launch),
        "probe_set": contract["probe_set"],
        "min_mem_available_gib": 20,
        "setup_quiescence_seconds": 60,
        "weekly_budget_debit": False,
        "paid_api_allowed": False,
        "production_change_authorized": False,
    }
    if version == 3:
        qualification_plan = q.plan_qualification(contract, contract_sha256, tmp_path)
    plan_path = tmp_path / "plan.json"
    write_json(plan_path, qualification_plan)
    endpoint = {
        "name": "flash_next",
        "served_model": q.SERVED_MODEL,
        "artifact_sha256": q.model_artifact_sha256(),
    }
    text_rows = [
        {
            "probe_id": "exact_literal",
            "content": "FLASH_NEXT_OK_17",
            "tool_calls": [],
            "finish_reason": "stop",
            "response_model": q.SERVED_MODEL,
            "endpoint": endpoint,
        },
        {
            "probe_id": "exact_arithmetic",
            "content": "703",
            "tool_calls": [],
            "finish_reason": "stop",
            "response_model": q.SERVED_MODEL,
            "endpoint": endpoint,
        },
        {
            "probe_id": "exact_tool_call",
            "content": "",
            "tool_calls": [
                {
                    "function": {
                        "name": "record_probe",
                        "arguments": json.dumps(
                            {"label": "flash-next", "value": 703}
                        ),
                    }
                }
            ],
            "finish_reason": "tool_calls",
            "response_model": q.SERVED_MODEL,
            "endpoint": endpoint,
        },
    ]
    write_json(
        tmp_path / "probes.json",
        {"probe_set": contract["probe_set"], "results": text_rows},
    )
    write_json(
        tmp_path / "model-verification.json",
        {
            "artifact_sha256": q.model_artifact_sha256(),
            "full_sha256": True,
            "safetensors_total_bytes": q.MODEL_TOTAL_BYTES,
            "verified_files": q.expected_model_files(),
        },
    )
    def memory_row(
        observed_at, *, pages, phase="setup", quiet=False, available=40.0
    ):
        return {
            "schema": "qwen-flash-next-memory-sample/v2",
            "observed_at": observed_at,
            "monitor_phase": phase,
            "setup_quiescence_active": quiet,
            "mem_available_gib": available,
            "pswpout_pages": pages,
            "pswpout_delta_pages": pages - 10,
            "setup_pswpout_delta_pages": 2 if phase == "mutation" else pages - 10,
            "mutation_pswpout_delta_pages": 0 if phase == "mutation" else None,
        }

    memory_rows = [
        memory_row("2026-09-15T23:59:59+00:00", pages=10),
        *[
            memory_row(
                f"2026-09-16T00:{second // 60:02d}:{second % 60:02d}+00:00",
                pages=12,
                quiet=True,
            )
            for second in range(61)
        ],
        memory_row("2026-09-16T00:01:00.500000+00:00", pages=12),
        *[
            memory_row(
                f"2026-09-16T00:01:{second:02d}+00:00",
                pages=12,
                phase="mutation",
            )
            for second in range(1, 60, 5)
        ],
        memory_row(
            "2026-09-16T00:02:00+00:00",
            pages=12,
            phase="mutation",
            available=39.0,
        ),
    ]
    (tmp_path / "memory.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in memory_rows)
    )
    result = {
        "schema": "qwen-flash-next-qualification-result/v2",
        "run_id": "qfn-c0-test",
        "status": "passed",
        "qualification_error": None,
        "failure_stage": None,
        "restoration": {
            "status": "verified",
            "verified_at": "2026-09-16T00:01:59+00:00",
            "errors": [],
            "sentinel_retained": False,
            "no_mutation_verified": False,
        },
        "contract_sha256": contract_sha256,
        "plan_sha256": q.sha256(qualification_plan),
        "model_artifact_sha256": q.model_artifact_sha256(),
        "elapsed_seconds": 10.0,
        "challenger_gpu_seconds": 5.0,
        "all_gpu_research_seconds": 5.0,
        "resident_downtime_seconds": 6.0,
        "memory_samples": len(memory_rows),
        "min_mem_available_gib": 39.0,
        "pswpout_initial_pages": 10,
        "pswpout_final_pages": 12,
        "pswpout_delta_pages": 2,
        "setup_pswpout_initial_pages": 10,
        "setup_pswpout_final_pages": 12,
        "setup_pswpout_delta_pages": 2,
        "setup_quiescence_required_seconds": 60,
        "setup_quiescence_passed": True,
        "setup_quiescence_started_at": "2026-09-16T00:00:00+00:00",
        "setup_quiescence_completed_at": "2026-09-16T00:01:00+00:00",
        "setup_quiescence_duration_seconds": 60.0,
        "setup_quiescence_initial_pswpout_pages": 12,
        "setup_quiescence_final_pswpout_pages": 12,
        "setup_quiescence_samples": 61,
        "mutation_window_started_at": "2026-09-16T00:01:01+00:00",
        "mutation_pswpout_initial_pages": 12,
        "mutation_pswpout_final_pages": 12,
        "mutation_pswpout_delta_pages": 0,
        "mutation_final_sample_at": "2026-09-16T00:02:00+00:00",
        "probe_count": 3,
        "weekly_budget_debit": False,
        "paid_api_calls": 0,
        "production_change_authorized": False,
    }
    receipt_path = tmp_path / "result.json"
    if version == 3:
        (tmp_path / "memory.jsonl").unlink()
        result.update(v3_monitor_proof(tmp_path / "memory.jsonl"))
        write_json(tmp_path / "readiness.json", {
            "ready_at": result["ready_quiescence_started_at"], "models": [q.SERVED_MODEL],
            "container": {
                "id": "c" * 64, "pid": 123, "image": q.IMAGE_ID, "name": q.CONTAINER_NAME,
                "running": True, "oom_killed": False, "restart_count": 0,
            },
            "stabilization": {key: result[f"ready_quiescence_{key}"] for key in (
                "required_seconds", "passed", "started_at", "completed_at", "duration_seconds",
                "initial_pswpout_pages", "final_pswpout_pages", "samples", "epoch",
            )},
        })
    write_json(receipt_path, result)
    return receipt_path, plan_path, contract_path


def v3_monitor_proof(path):
    """Produce real controller telemetry with an injected host and virtual clock."""
    now = [0.0]
    pages = [10]
    cid = "c" * 64
    base = datetime(2026, 9, 16, tzinfo=timezone.utc)
    candidate = {
        "id": cid, "name": q.CONTAINER_NAME, "image": q.IMAGE_ID,
        "running": True, "oom_killed": False, "restart_count": 0, "pid": 123,
    }
    cgroup = {
        "path": f"/system.slice/docker-{cid}.scope", "process_start_ticks": 12345,
        "memory_swap_current_bytes": 0, "memory_events_oom": 0, "memory_events_oom_kill": 0,
    }
    def sleep(seconds):
        now[0] += seconds

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(q.time, "sleep", sleep)
        patch.setattr(q, "utc_now", lambda: (base + timedelta(seconds=now[0])).isoformat())
        patch.setattr(q, "_inspect_container", lambda *_: candidate)
        monitor = q.MemoryMonitor(
            path, object(), reader=lambda: 39.0, swap_reader=lambda: pages[0],
            cgroup_reader=lambda *_: dict(cgroup), clock=lambda: now[0],
        )
        with path.open("xb") as stream:
            monitor._stream = stream
            monitor._sample_once()
            sleep(1)
            pages[0] = 12
            monitor.require_setup_quiescence(duration_s=60, deadline=300)
            monitor.begin_mutation_window()
            monitor.arm(cid)
            sleep(1)
            pages[0] += 394  # Small host paging is allowed; candidate swap stays zero.
            monitor._sample_once()
            monitor.require_ready_quiescence(duration_s=60, deadline=300)
            sleep(1)
            monitor._sample_once()
            sleep(1)
            monitor._sample_once()
            monitor.begin_restoration()
            monitor.disarm()
            sleep(1)
            pages[0] += 522059  # Restoration paging is diagnostic, not a candidate veto.
            monitor._sample_once()
        assert monitor.failure is None
        result = {
            "schema": "qwen-flash-next-qualification-result/v3",
            "restoration": {"status": "verified", "verified_at": q.utc_now(), "errors": [], "sentinel_retained": False},
            "memory_samples": monitor.samples, "min_mem_available_gib": 39.0,
            "pswpout_initial_pages": 10, "pswpout_final_pages": pages[0], "pswpout_delta_pages": pages[0] - 10,
            "setup_pswpout_initial_pages": 10, "setup_pswpout_final_pages": 12, "setup_pswpout_delta_pages": 2,
            "mutation_window_started_at": monitor.mutation_window_started_at,
            "mutation_pswpout_initial_pages": 12, "mutation_pswpout_final_pages": pages[0],
            "mutation_pswpout_delta_pages": pages[0] - 12, "mutation_final_sample_at": monitor.mutation_final_sample_at,
            "startup_pswpout_initial_pages": 12, "startup_pswpout_final_pages": 406,
            "startup_pswpout_delta_pages": 394, "startup_pswpout_delta_bytes": 394 * 4096,
            "paging_policy": copy.deepcopy(q.PAGING_POLICY), "paging_phase_summaries": copy.deepcopy(monitor.phase_summaries),
            "paging_violations": [],
            "paging_warning_phases": [phase for phase, summary in monitor.phase_summaries.items() if summary["pswpout_delta_bytes"] > 0],
            "candidate_cgroup_path": cgroup["path"], "candidate_cgroup_pid": 123,
            "candidate_cgroup_start_ticks": 12345,
            "candidate_cgroup_samples": monitor.candidate_cgroup_samples,
            "candidate_cgroup_swap_peak_bytes": 0, "candidate_cgroup_oom_initial": 0,
            "candidate_cgroup_oom_final": 0, "candidate_cgroup_oom_kill_initial": 0,
            "candidate_cgroup_oom_kill_final": 0, "ready_quiescence_epoch": monitor.ready_quiescence_epoch,
        }
        for phase in ("setup", "ready"):
            result[f"{phase}_quiescence_required_seconds"] = 60
            for name in ("passed", "started_at", "completed_at", "duration_seconds", "samples"):
                result[f"{phase}_quiescence_{name}"] = getattr(monitor, f"{phase}_quiescence_{name}")
            for name in ("initial_pswpout", "final_pswpout"):
                result[f"{phase}_quiescence_{name}_pages"] = getattr(monitor, f"{phase}_quiescence_{name}")
        return result


def test_run_receipt_passes_the_independent_comparator_contract(tmp_path):
    plan = small_plan()
    result = run_harness(
        plan,
        cohort="resident",
        output_dir=tmp_path / "run",
        runtime_budget_s=30,
        qualification_gate=gate,
        invoke_fn=response,
        run_id="resident-smoke",
    )
    assert result["status"] == "complete"
    assert list(validate_run(result, "resident")) == plan["declared_cells"]
    assert result["outcomes"][0]["status"] == "returned"
    assert result["outcomes"][0]["passed"] is False
    assert result["outcomes"][0]["wall_s"] >= result["outcomes"][0]["calls"][0]["wall_s"]
    assert (tmp_path / "run/run.json").is_file()
    assert not (tmp_path / "run/checkpoint.json").exists()
    evidence = result["outcomes"][0]["grade"]["details"]["_private_call_evidence"]
    descriptor = evidence["artifacts"][0]
    metadata_path = tmp_path / "run" / descriptor["metadata_path"]
    metadata_raw = metadata_path.read_bytes()
    metadata = json.loads(metadata_raw)
    assert hashlib.sha256(metadata_raw).hexdigest() == descriptor["metadata_sha256"]
    assert metadata["response"]["content"] == "{}"
    assert metadata["response"]["reasoning_content"] == "private-reasoning"
    assert metadata["request"]["messages"]
    stream_path = tmp_path / "run" / descriptor["raw_stream"]["path"]
    assert hashlib.sha256(stream_path.read_bytes()).hexdigest() == descriptor["raw_stream"]["sha256"]
    assert stat.S_IMODE(metadata_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(metadata_path.parent.parent.stat().st_mode) == 0o700


def test_gate_failure_precedes_filesystem_or_model_activity(tmp_path):
    called = False

    def invoke(*_args, **_kwargs):
        nonlocal called
        called = True

    def refuse(_plan, _cohort):
        raise HarnessError("qualification did not pass")

    output = tmp_path / "never-created"
    with pytest.raises(HarnessError, match="qualification"):
        run_harness(
            small_plan(),
            cohort="flash",
            output_dir=output,
            runtime_budget_s=30,
            qualification_gate=refuse,
            invoke_fn=invoke,
        )
    assert called is False
    assert not output.exists()


def test_timeout_is_a_failure_inclusive_completed_cell(tmp_path):
    attempts = 0

    def timeout_then_return(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TimeoutError("stalled")
        return response(*args, **kwargs)

    result = run_harness(
        small_plan(count=2),
        cohort="flash",
        output_dir=tmp_path / "timeouts",
        runtime_budget_s=30,
        qualification_gate=gate,
        invoke_fn=timeout_then_return,
    )
    assert result["status"] == "complete"
    assert [row["status"] for row in result["outcomes"]] == ["timeout", "returned"]
    assert result["outcomes"][0]["calls"][0]["request_sha256"] is not None
    validate_run(result, "flash")


def test_cancellation_aborts_and_emits_explicit_not_run_denominators(tmp_path):
    cancel = threading.Event()

    def cancelled(*_args, **_kwargs):
        cancel.set()
        raise TransportCancelled("owner cancellation")

    result = run_harness(
        small_plan(count=2),
        cohort="resident",
        output_dir=tmp_path / "cancelled",
        runtime_budget_s=30,
        qualification_gate=gate,
        invoke_fn=cancelled,
        cancel_event=cancel,
    )
    assert result["status"] == "aborted"
    assert [row["status"] for row in result["outcomes"]] == ["cancelled", "not_run"]
    assert result["outcomes"][1]["calls"] == []
    assert result["outcomes"][1]["wall_s"] == 0
    validate_run(result, "resident")


def test_source_or_adapter_drift_refuses_before_output(tmp_path):
    plan = small_plan()
    changed = copy.deepcopy(plan)
    cell_id = changed["declared_cells"][0]
    changed["cell_receipts"][cell_id]["adapter"]["source_sha256"] = "f" * 64
    adapter_id = changed["cell_receipts"][cell_id]["adapter"]["id"]
    for adapter in changed["adapter_bundle"]:
        if adapter["id"] == adapter_id:
            adapter["source_sha256"] = "f" * 64
    with pytest.raises(HarnessError, match="drift"):
        run_harness(
            changed,
            cohort="flash",
            output_dir=tmp_path / "drift",
            runtime_budget_s=30,
            qualification_gate=gate,
            invoke_fn=response,
        )
    assert not (tmp_path / "drift").exists()


def test_two_cohorts_share_one_plan_and_are_comparison_eligible(tmp_path):
    plan = small_plan(count=2)
    resident = run_harness(
        plan,
        cohort="resident",
        output_dir=tmp_path / "resident",
        runtime_budget_s=30,
        qualification_gate=gate,
        invoke_fn=response,
        run_id="resident-run",
    )
    flash = run_harness(
        plan,
        cohort="flash",
        output_dir=tmp_path / "flash",
        runtime_budget_s=30,
        qualification_gate=gate,
        invoke_fn=response,
        run_id="flash-run",
    )
    comparison = summarize_pair(resident, flash, bootstrap_samples=100)
    assert comparison["comparison_eligible"] is True
    assert comparison["promotion_authorized"] is False


def test_passing_flash_qualification_is_crossbound_to_registered_arm(tmp_path):
    receipt_path, qualification_plan_path, contract_path = passing_flash_receipts(
        tmp_path
    )
    summary = validate_flash_qualification_files(
        receipt_path,
        qualification_plan_path,
        contract_path,
        require_passed=True,
    )
    assert summary["pswpout_delta_pages"] == 522455
    assert summary["setup_pswpout_delta_pages"] == 2
    assert summary["mutation_pswpout_delta_pages"] == 522453
    flash = make_arm_receipt(
        "flash",
        qualification_receipt_sha256=summary["qualification_receipt_sha256"],
        artifact_sha256_by_endpoint={
            "flash_next": summary["model_artifact_sha256"]
        },
        runtime_sha256_by_endpoint={"flash_next": summary["runtime_sha256"]},
    )
    plan, _ = build_plan([arms()[0], flash], families=["context"])
    assert (
        validate_qualification_receipt(
            plan,
            "flash",
            receipt_path=receipt_path,
            qualification_plan_path=qualification_plan_path,
            contract_snapshot_path=contract_path,
        )["admission_eligible"]
        is True
    )


def test_flash_admission_rejects_swap_inside_the_mutation_window(tmp_path):
    receipt_path, qualification_plan_path, contract_path = passing_flash_receipts(
        tmp_path, version=2
    )
    rows = [
        json.loads(line)
        for line in (receipt_path.parent / "memory.jsonl").read_text().splitlines()
    ]
    rows[-1]["pswpout_pages"] = 13
    rows[-1]["pswpout_delta_pages"] = 3
    rows[-1]["mutation_pswpout_delta_pages"] = 1
    (receipt_path.parent / "memory.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows)
    )
    result = json.loads(receipt_path.read_text())
    result["pswpout_final_pages"] = 13
    result["pswpout_delta_pages"] = 3
    result["mutation_pswpout_final_pages"] = 13
    result["mutation_pswpout_delta_pages"] = 1
    write_json(receipt_path, result)

    summary = validate_flash_qualification_files(
        receipt_path, qualification_plan_path, contract_path
    )
    assert summary["admission_eligible"] is False
    assert any("mutation" in reason for reason in summary["admission_failures"])


def test_flash_admission_rejects_a_claimed_short_quiescence(tmp_path):
    receipt_path, qualification_plan_path, contract_path = passing_flash_receipts(
        tmp_path
    )
    result = json.loads(receipt_path.read_text())
    result["setup_quiescence_duration_seconds"] = 59.999
    write_json(receipt_path, result)

    summary = validate_flash_qualification_files(
        receipt_path, qualification_plan_path, contract_path
    )
    assert summary["admission_eligible"] is False
    assert any("quiescence" in reason for reason in summary["admission_failures"])


@pytest.mark.parametrize("corruption", [
    "candidate_swap", "candidate_oom", "pid_reuse", "missing_candidate",
    "missing_bind", "sample_gap", "short_ready", "policy_change",
    "boolean_counter", "forged_phase_summary", "missing_transition",
    "counter_rewind", "swapped_phase", "hidden_host_growth", "late_bind",
    "emergency_stop", "missing_restoration_boundary", "early_bind",
    "startup_reset", "forged_startup_summary",
])
def test_v3_admission_reconstructs_raw_proof_and_rejects_tampering(tmp_path, corruption):
    receipt, plan, contract = passing_flash_receipts(tmp_path)
    result = json.loads(receipt.read_text())
    path = receipt.parent / "memory.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    serving = next(row for row in rows if row.get("monitor_phase") == "probes")
    if corruption == "candidate_swap":
        serving["candidate"]["cgroup"]["memory_swap_current_bytes"] = 4096
    elif corruption == "candidate_oom":
        serving["candidate"]["cgroup"]["memory_events_oom"] = 1
    elif corruption == "pid_reuse":
        serving["candidate"]["cgroup"]["process_start_ticks"] += 1
    elif corruption == "missing_candidate":
        del serving["candidate"]
    elif corruption == "missing_bind":
        rows = [row for row in rows if row.get("schema") != "qwen-flash-next-cgroup-bind/v1"]
    elif corruption == "sample_gap":
        serving["elapsed_monotonic_seconds"] += 20
    elif corruption == "short_ready":
        result["ready_quiescence_duration_seconds"] = 59.99
    elif corruption == "policy_change":
        result["paging_policy"]["candidate_cgroup_swap_max_bytes"] = 4096
    elif corruption == "boolean_counter":
        serving["candidate"]["cgroup"]["memory_events_oom"] = False
    elif corruption == "forged_phase_summary":
        result["paging_phase_summaries"]["load"]["max_window_5s_bytes"] = 0
    elif corruption == "missing_transition":
        next(row for row in rows if row.get("transition_to") == "probes")["transition_to"] = None
    elif corruption == "counter_rewind":
        serving["pswpout_pages"] -= 1
    elif corruption == "swapped_phase":
        serving["monitor_phase"] = "restoration"
    elif corruption == "hidden_host_growth":
        serving["pswpout_pages"] += 8192
    elif corruption == "late_bind":
        bind = next(row for row in rows if row.get("schema") == "qwen-flash-next-cgroup-bind/v1")
        rows.remove(bind)
        rows.append(bind)
    elif corruption == "early_bind":
        bind = next(row for row in rows if row.get("schema") == "qwen-flash-next-cgroup-bind/v1")
        rows.remove(bind)
        rows.insert(0, bind)
    elif corruption == "emergency_stop":
        rows.append({"event": "emergency_candidate_stop", "candidate_id": "c" * 64, "returncode": 0})
    elif corruption == "missing_restoration_boundary":
        first = next(row for row in rows if row.get("monitor_phase") == "restoration")
        del first["candidate"]
        result["candidate_cgroup_samples"] -= 1
    elif corruption == "startup_reset":
        ready = next(row for row in rows if row.get("monitor_phase") == "ready")
        ready["gate_initial_pswpout_pages"] = ready["pswpout_pages"]
        ready["gate_pswpout_delta_pages"] = 0
        ready["gate_pswpout_delta_bytes"] = 0
        ready["host_swap_5s_bytes"] = 0
        ready["host_swap_60s_bytes"] = 0
    elif corruption == "forged_startup_summary":
        result["startup_pswpout_delta_pages"] = 0
        result["startup_pswpout_delta_bytes"] = 0
    write_json(receipt, result)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    with pytest.raises(HarnessError):
        validate_flash_qualification_files(receipt, plan, contract, require_passed=True)


def test_v2_pass_is_retained_as_history_without_v3_admission(tmp_path):
    receipt, plan, contract = passing_flash_receipts(tmp_path, version=2)
    summary = validate_flash_qualification_files(receipt, plan, contract)
    assert summary["status"] == "passed"
    assert summary["admission_eligible"] is False
    assert any("legacy" in item for item in summary["admission_failures"])


@pytest.mark.parametrize("failure", ["missing", "wrong_model", "later_readiness", "different_pid"])
def test_v3_requires_exact_readiness_before_quiet_proof(tmp_path, failure):
    receipt, plan, contract = passing_flash_receipts(tmp_path)
    path = receipt.parent / "readiness.json"
    ready = json.loads(path.read_text())
    if failure == "missing":
        path.unlink()
    else:
        if failure == "wrong_model":
            ready["models"] = ["wrong-model"]
        elif failure == "later_readiness":
            ready["ready_at"] = "2026-09-16T01:00:00+00:00"
        elif failure == "different_pid":
            ready["container"]["pid"] = 999
        write_json(path, ready)
    with pytest.raises(HarnessError, match="readiness"):
        validate_flash_qualification_files(receipt, plan, contract, require_passed=True)


@pytest.mark.parametrize("field", ["output_dir", "endpoint", "resource_locks", "invocation_deadline_seconds"])
def test_v3_requires_the_complete_registered_plan(tmp_path, field):
    receipt, plan, contract = passing_flash_receipts(tmp_path)
    document = json.loads(plan.read_text())
    del document[field]
    write_json(plan, document)
    result = json.loads(receipt.read_text())
    result["plan_sha256"] = q.sha256(document)
    write_json(receipt, result)
    with pytest.raises(HarnessError, match="full registered plan"):
        validate_flash_qualification_files(receipt, plan, contract, require_passed=True)


@pytest.mark.parametrize("corruption", ["run_id", "missing_errors", "failure_stage", "boolean_paid_calls", "extra_probe"])
def test_v3_rejects_malformed_pass_semantics(tmp_path, corruption):
    receipt, plan, contract = passing_flash_receipts(tmp_path)
    result = json.loads(receipt.read_text())
    if corruption == "run_id":
        result["run_id"] = "qfn-c0-different"
    elif corruption == "missing_errors":
        del result["restoration"]["errors"]
    elif corruption == "failure_stage":
        result["failure_stage"] = "restoration"
    elif corruption == "boolean_paid_calls":
        result["paid_api_calls"] = False
    elif corruption == "extra_probe":
        path = receipt.parent / "probes.json"
        probes = json.loads(path.read_text())
        probes["results"].insert(0, "unexpected")
        write_json(path, probes)
    write_json(receipt, result)
    with pytest.raises(HarnessError):
        validate_flash_qualification_files(receipt, plan, contract, require_passed=True)


def test_flash_admission_rejects_a_sub_20_gib_contract(tmp_path):
    receipt_path, qualification_plan_path, contract_path = passing_flash_receipts(
        tmp_path
    )
    contract = json.loads(contract_path.read_text())
    contract["safety"]["min_mem_available_gib"] = 19
    write_json(contract_path, contract)
    raw_contract_path = receipt_path.parent / "launch-contract.raw.json"
    raw_contract_path.write_text(json.dumps(contract, separators=(",", ":")) + "\n")
    qualification_plan = json.loads(qualification_plan_path.read_text())
    qualification_plan["contract_sha256"] = sha256_file(raw_contract_path)
    qualification_plan["min_mem_available_gib"] = 19
    write_json(qualification_plan_path, qualification_plan)
    result = json.loads(receipt_path.read_text())
    result["contract_sha256"] = sha256_file(raw_contract_path)
    result["plan_sha256"] = q.sha256(qualification_plan)
    write_json(receipt_path, result)
    summary = validate_flash_qualification_files(
        receipt_path, qualification_plan_path, contract_path
    )
    assert summary["admission_eligible"] is False
    assert any("20 GiB" in reason for reason in summary["admission_failures"])


def test_receipt_reader_rejects_fifo_without_blocking(tmp_path):
    fifo = tmp_path / "result.json"
    os.mkfifo(fifo)
    started = time.monotonic()
    with pytest.raises(HarnessError, match="regular file"):
        validate_flash_qualification_files(fifo, fifo, fifo)
    assert time.monotonic() - started < 1


def test_receipt_reader_rejects_a_symlinked_parent(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    (target / "result.json").write_text("{}")
    redirected = tmp_path / "redirected"
    redirected.symlink_to(target, target_is_directory=True)
    with pytest.raises(HarnessError, match="redirected"):
        validate_flash_qualification_files(
            redirected / "result.json",
            redirected / "result.json",
            redirected / "result.json",
        )


ARTIFACT_ROOT = (
    "/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-14/"
    "qwen-flash-next-research"
)
FAILED_C0_RESULT = f"{ARTIFACT_ROOT}/qualification-runs/qfn-c0-20260915-0100/result.json"
FAILED_C0_PLAN = f"{ARTIFACT_ROOT}/qualification-runs/qfn-c0-20260915-0100/plan.json"
FAILED_C0_SNAPSHOT = (
    f"{ARTIFACT_ROOT}/qualification-runs/qfn-c0-20260915-0100/"
    "launch-contract.snapshot.json"
)
FAILED_C0_CONTRACT = f"{ARTIFACT_ROOT}/runtime/launch-contract.c0.v1-3757f596d03bd3d3.json"
RESIDENT_QUALIFICATION = f"{ARTIFACT_ROOT}/runtime/resident-qualification-v2.json"
RESIDENT_ARTIFACTS = f"{ARTIFACT_ROOT}/runtime/resident-model-artifacts.json"


@pytest.mark.canonical_corpus(
    FAILED_C0_RESULT, FAILED_C0_PLAN, FAILED_C0_SNAPSHOT, FAILED_C0_CONTRACT
)
def test_actual_failed_c0_is_valid_history_but_cannot_admit_calls():
    summary = validate_flash_qualification_files(
        FAILED_C0_RESULT,
        FAILED_C0_PLAN,
        FAILED_C0_SNAPSHOT,
        contract_raw_path=FAILED_C0_CONTRACT,
    )
    assert summary["status"] == "failed"
    assert summary["admission_eligible"] is False
    assert summary["qualification_receipt_sha256"] == (
        "c58f9f623eed98a94546ddca837ea98e48bfe5255dd62a980d3825c407ab6cf7"
    )
    with pytest.raises(HarnessError, match="not admissible"):
        validate_flash_qualification_files(
            FAILED_C0_RESULT,
            FAILED_C0_PLAN,
            FAILED_C0_SNAPSHOT,
            contract_raw_path=FAILED_C0_CONTRACT,
            require_passed=True,
        )


@pytest.mark.canonical_corpus(RESIDENT_QUALIFICATION, RESIDENT_ARTIFACTS)
def test_actual_resident_receipts_recompute_artifacts_and_runtime_bindings(tmp_path):
    summary = validate_resident_qualification_files(
        RESIDENT_QUALIFICATION,
        RESIDENT_ARTIFACTS,
        require_passed=True,
    )
    assert summary["admission_eligible"] is True
    assert summary["probe_scope"] == "fixed_literal_and_arithmetic_only"
    assert summary["artifact_sha256_by_endpoint"] == {
        "resident_gemma": "c63860e164ed838e0b829de106bfe5ed5f8cd82a7db391c752954c69862ee0af",
        "resident_qwen": "dae0d24c2c46e072aa7975825d14b161dabb475643669f66824dc645a597c10f",
    }

    # Endpoint identity follows the registered container ID, not array order.
    reordered = json.loads(Path(RESIDENT_QUALIFICATION).read_text())
    reordered["before"]["runtime_identity"].reverse()
    reordered["after"]["runtime_identity"].reverse()
    reordered_path = tmp_path / "resident-reordered.json"
    write_json(reordered_path, reordered)
    assert validate_resident_qualification_files(
        reordered_path, RESIDENT_ARTIFACTS, require_passed=True
    )["admission_eligible"]

    inventory = json.loads(Path(RESIDENT_ARTIFACTS).read_text())
    inventory["models"]["resident_gemma"]["artifact_sha256"] = "f" * 64
    inventory_path = tmp_path / "tampered-inventory.json"
    write_json(inventory_path, inventory)
    with pytest.raises(HarnessError, match="does not bind"):
        validate_resident_qualification_files(
            RESIDENT_QUALIFICATION,
            inventory_path,
            require_passed=True,
        )
