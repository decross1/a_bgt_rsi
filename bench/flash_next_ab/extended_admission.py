"""UNAPPLIED DRAFT: admit a pair only after both supervised windows finish.

The completed Flash cohort is not a new C0 qualification receipt: a written
harness/run.json remains ineligible until final exact restoration, raw safety
evidence, three probes, plan/source hashes, and process supervision agree.
"""
from __future__ import annotations

import hashlib
import math
from pathlib import Path

from .candidate_registry import MIA, CandidateSpec
from .compare import validate_run
from .evaluation_window import (
    EXTENDED_SERVING_PROFILE,
    MAX_EXTENDED_MEMORY_BYTES,
    MAX_EXTENDED_MEMORY_ROWS,
    RESEARCH_LEDGER,
    _evaluation_output,
    build_extended_evaluation_plan,
    extended_plan_sha256,
    load_evaluation_window,
)
from .harness import (
    _read_regular_file,
    _strict_object,
    _utc_datetime,
    _validate_cgroup_diagnostics,
    _validate_flash_probes,
    _validate_memory_log_v3,
    _validate_mia_probe_attempts,
)
from .observer_admission import validate_ui_observer
from .private_evidence import validate_private_evidence
from .qualification import (
    CONTAINER_NAME,
    DOCKER_MEMORY_LIMIT_BYTES,
    DOCKER_MEMORY_SWAP_TOTAL_BYTES,
    PAGING_POLICY,
    RESIDENTS,
    WEIGHT_FILES,
    _read_bounded_run_json,
    _runtime_identity,
    _verified_contract_raw,
    launch_argv,
    sha256,
)


class ExtendedAdmissionError(ValueError):
    """A completed benchmark window cannot be trusted or paired."""


def _require(test: bool, message: str) -> None:
    if not test:
        raise ExtendedAdmissionError(message)


def _read_raw(path: Path, label: str, ceiling: int) -> bytes:
    raw, observed = _read_regular_file(path, label=label, max_bytes=ceiling)
    _require(observed == path.absolute(), f"{label} path redirected")
    return raw


def _bound_evidence(output: Path, result: dict, filename: str, field: str, ceiling: int) -> dict:
    raw = _read_raw(output / filename, filename, ceiling)
    _require(
        result.get(field) == hashlib.sha256(raw).hexdigest(),
        f"{filename} raw digest differs from final window result",
    )
    return _strict_object(raw, filename)


def _supervisor_inputs(output: Path, window, plan: dict) -> tuple[dict, CandidateSpec | None]:
    """Bind the extended supervisor's bytes to the prior qualified runtime."""
    raw_contract = _read_raw(
        output / "launch-contract.raw.json", "extended raw contract", 2_000_000
    )
    snapshot = _strict_object(
        _read_raw(output / "launch-contract.snapshot.json", "contract snapshot", 2_000_000),
        "contract snapshot",
    )
    prior = _strict_object(
        _read_raw(output / "prior-c0-plan.snapshot.json", "prior C0 plan", 2_000_000),
        "prior C0 plan",
    )
    source_bundle = _strict_object(
        _read_raw(output / "controller-source-bundle.snapshot.json",
                  "registered source bundle snapshot", 2_000_000),
        "registered source bundle snapshot",
    )
    _require(
        source_bundle == plan.get("controller_source_bundle")
        and sha256(source_bundle) == plan.get("controller_source_bundle_sha256"),
        "supervisor lifecycle and observer source SHA bundle differs",
    )
    spec = MIA if plan.get("candidate_variant_id") == MIA.spec_id else None
    runtime = _runtime_identity(spec)
    _require(
        hashlib.sha256(raw_contract).hexdigest() == plan.get("contract_sha256")
        and _strict_object(raw_contract, "exact raw contract") == snapshot
        and snapshot.get("profile") == (spec.profile if spec else "C0-S1")
        and prior == window.qualification_plan
        and prior.get("contract_sha256") == plan["contract_sha256"]
        and prior.get("image_id") == runtime.image_id
        and prior.get("model_path") == str(runtime.model_path)
        and prior.get("model_artifact_sha256") == runtime.model_artifact_sha256
        and prior.get("docker_create_argv") == launch_argv(spec)
        and prior.get("paging_policy")
            == (spec.paging_policy() if spec else PAGING_POLICY)
        and plan.get("candidate_variant_id")
            == (spec.spec_id if spec else "nvidia-nvfp4-fc694b54")
        and plan.get("candidate_spec_sha256")
            == (spec.identity_sha256() if spec else None)
        and plan.get("extended_serving_profile") == EXTENDED_SERVING_PROFILE
        and plan.get("benchmark_plan_file_sha256")
            == window.benchmark_plan_file_sha256,
        "supervisor raw contract/prior qualified runtime snapshots differ",
    )
    _require(_verified_contract_raw(snapshot, plan["contract_sha256"], spec=spec)
             == raw_contract, "external source changed after the frozen window")
    return snapshot, spec


def _memory(output: Path, result: dict, plan: dict,
            spec: CandidateSpec | None) -> None:
    raw = _read_raw(output / "memory.jsonl", "extended safety memory log",
                    MAX_EXTENDED_MEMORY_BYTES)
    _require(
        result.get("memory_log_sha256") == hashlib.sha256(raw).hexdigest(),
        "extended memory log raw digest differs",
    )
    rows = [
        _strict_object(line, f"extended memory row {index}")
        for index, line in enumerate(raw.splitlines(), 1)
    ]
    _require(len(rows) <= MAX_EXTENDED_MEMORY_ROWS and
             plan["extended_serving_profile"] == EXTENDED_SERVING_PROFILE,
             "extended evidence exceeds its registered sample/profile bounds")
    samples = [row for row in rows if "mem_available_gib" in row]
    _require(samples and len(samples) == result.get("memory_samples"), "safety memory sample count differs")
    minimum = min(row["mem_available_gib"] for row in samples)
    _require(
        all(isinstance(row["mem_available_gib"], (int, float))
            and not isinstance(row["mem_available_gib"], bool)
            and math.isfinite(row["mem_available_gib"])
            and row["mem_available_gib"] >= plan["min_mem_available_gib"]
            for row in samples),
        "raw extended memory dipped below the research reserve",
    )
    _require(
        result.get("min_mem_available_gib") == minimum,
        "reported extended minimum memory differs from raw samples",
    )
    _require(
        result.get("pswpout_initial_pages") == samples[0].get("pswpout_pages")
        and result.get("pswpout_final_pages") == samples[-1].get("pswpout_pages")
        and result.get("pswpout_delta_pages")
        == samples[-1]["pswpout_pages"] - samples[0]["pswpout_pages"],
        "reported extended host swap differs from raw samples",
    )
    # Reuse the fully reviewed v3 reconstruction with its candidate cgroup
    # bind order, exact PID/start-ticks, zero attributed swap/local OOM,
    # no >10s blind spots, shared startup load+ready byte caps, and both
    # 60-second quiescence proofs, S1 page-in/PSI diagnostics, and raw sidecar.
    memory_limit = (spec.docker_memory_limit_bytes if spec is not None
                    else DOCKER_MEMORY_LIMIT_BYTES)
    _require(
        result.get("profile") == (spec.profile if spec else "C0-S1")
        and result.get("docker_memory_limit_bytes") == memory_limit
        and result.get("docker_memory_swap_total_bytes") == memory_limit
        and result.get("paging_policy")
            == (spec.paging_policy() if spec else PAGING_POLICY),
        "completed Flash window lacks the exact qualified C0-S1 no-swap profile",
    )
    _validate_cgroup_diagnostics(output / "result.json", raw, rows, result,
                                 spec=spec, extended_plan=plan)
    _validate_memory_log_v3(rows, samples, result, spec=spec,
                            extended_plan=plan)


def _final_identity(result: dict, state: dict) -> None:
    restore = result.get("restoration")
    _require(
        isinstance(restore, dict) and restore.get("status") == "verified"
        and restore.get("errors") == []
        and restore.get("sentinel_retained") is False,
        "runtime restoration is not exactly verified",
    )
    observed = restore.get("final_observation")
    initial = state.get("initial")
    _require(
        isinstance(initial, dict) and isinstance(observed, dict)
        and observed.get("sentinel_by_name") is None
        and observed.get("sentinel_by_id") is None
        and isinstance(observed.get("residents"), list)
        and len(observed["residents"]) == len(RESIDENTS),
        "exact final resident/sentinel observation is missing",
    )
    original = {
        row["name"]: row for row in initial["residents"]
        if isinstance(row, dict) and "name" in row
    }
    _require(len(original) == len(RESIDENTS), "resident capture is incomplete")
    for registered, final in zip(RESIDENTS, observed["residents"], strict=True):
        before = original.get(registered["name"])
        _require(
            isinstance(before, dict) and isinstance(final, dict)
            and before.get("id") == registered["id"]
            and before.get("image") == registered["image_id"]
            and before.get("running") is True
            and final.get("id") == before["id"]
            and final.get("name") == before["name"]
            and final.get("image") == before["image"]
            and final.get("running") is True
            and final.get("oom_killed") is False
            and final.get("state_error") == ""
            and final.get("restart_policy") == before["restart_policy"]
            and type(final.get("restart_count")) is int
            and final["restart_count"]
            == restore.get("resident_restart_baselines", {}).get(registered["name"]),
            "final incumbent identity or restart/OOM state differs",
        )
    healthy = observed.get("resident_health")
    _require(
        isinstance(healthy, list) and len(healthy) == len(RESIDENTS)
        and all(
            item.get("name") == registered["name"] and item.get("healthy") is True
            for item, registered in zip(healthy, RESIDENTS, strict=True)
        ),
        "final incumbent endpoint health differs",
    )
    service = observed.get("nara")
    _require(
        isinstance(service, dict) and service.get("ActiveState")
        == ("active" if initial.get("nara_was_active") else "inactive"),
        "Nara service not restored to its original activity",
    )
    _require(
        _utc_datetime(observed.get("observed_at"), "final identity time")
        <= _utc_datetime(restore.get("verified_at"), "restoration verification time")
        <= _utc_datetime(result.get("finished_at"), "result finish time"),
        "final identity observation occurred after the claimed verification",
    )


def _research_usage(pair_id: str, execution_sha: str, result: dict) -> None:
    raw = _read_raw(RESEARCH_LEDGER, "research usage journal", 64 * 1024 * 1024)
    candidates = [
        _strict_object(row, f"research journal row {index}")
        for index, row in enumerate(raw.splitlines(), 1)
        if row.strip()
    ]
    _require(
        any(
            row.get("schema") == "local-model-research-usage/v1"
            and row.get("event") == "extended_finished"
            and row.get("run_id") == f"{pair_id}.flash"
            and row.get("extended_plan_sha256") == execution_sha
            and row.get("status") == "complete"
            and row.get("restoration_status") == "verified"
            and row.get("weekly_budget_debit") is False
            and row.get("paid_api_calls") == 0
            and _utc_datetime(row.get("observed_at"), "research journal finish")
                <= _utc_datetime(result.get("finished_at"), "extended result finish")
            for row in candidates
        ),
        "completed window has no finished append-only research usage row",
    )


def validate_completed_flash_window(window_path: Path, output_dir: Path) -> dict:
    """Pure no-network gate for the already restored Flash window."""
    window = load_evaluation_window(window_path, expected_cohort="flash")
    output = _evaluation_output(window.pair_id, output_dir, must_be_absent=False)
    expected_plan = build_extended_evaluation_plan(window, output)
    plan = _read_bounded_run_json(output / "extended-plan.json", source="extended supervisor plan")
    _require(plan == expected_plan, "extended plan differs from registered source/C0")
    execution_sha = extended_plan_sha256(plan)
    contract, spec = _supervisor_inputs(output, window, plan)
    result = _read_bounded_run_json(output / "result.json", source="final extended result")
    state = _read_bounded_run_json(output / "state.json", source="final extended state")
    supervision = _read_bounded_run_json(output / "supervision.json", source="final supervisor")
    _require(
        result.get("schema") == "flash-next-extended-evaluation-result/v2"
        and result.get("status") == "complete"
        and result.get("qualification_error") is None
        and result.get("failure_class") is None
        and result.get("failure_stage") is None
        and result.get("pair_id") == window.pair_id
        and result.get("window_plan_sha256") == window.source_sha256
        and result.get("extended_plan_sha256") == execution_sha
        and result.get("prior_qualification_receipt_sha256")
        == plan["prior_qualification_receipt_sha256"]
        and result.get("benchmark_plan_file_sha256")
        == window.benchmark_plan_file_sha256
        and result.get("plan_sha256") == sha256(window.qualification_plan)
        and result.get("contract_sha256") == plan["contract_sha256"]
        and result.get("model_artifact_sha256") == plan["model_artifact_sha256"]
        and result.get("candidate_variant_id") == plan["candidate_variant_id"]
        and result.get("candidate_spec_sha256") == plan["candidate_spec_sha256"]
        and result.get("extended_serving_profile") == EXTENDED_SERVING_PROFILE
        and result.get("extended_serving_profile_sha256")
            == plan["extended_serving_profile_sha256"]
        and result.get("controller_source_bundle_sha256")
            == plan["controller_source_bundle_sha256"]
        and (spec is None or result.get("candidate")
             == window.qualification_plan.get("candidate"))
        and result.get("effective_invocation_deadline_seconds")
        == plan["effective_invocation_deadline_seconds"]
        and result.get("probe_count") == 3
        and result.get("weekly_budget_debit") is False
        and result.get("paid_api_calls") == 0
        and result.get("production_change_authorized") is False,
        "extended result status or frozen identity differs",
    )
    _require(
        state.get("schema") == "flash-next-extended-evaluation-state/v2"
        and state.get("pair_id") == window.pair_id
        and state.get("phase") == "complete"
        and state.get("result_status") == "complete"
        and state.get("plan_sha256") == sha256(window.qualification_plan)
        and state.get("extended_plan_sha256") == execution_sha
        and state.get("window_plan_sha256") == window.source_sha256
        and state.get("prior_qualification_receipt_sha256")
        == plan["prior_qualification_receipt_sha256"]
        and state.get("contract_sha256") == plan["contract_sha256"]
        and state.get("restoration") == result["restoration"]
        and state.get("extended_serving_profile") == EXTENDED_SERVING_PROFILE
        and state.get("extended_serving_profile_sha256")
            == plan["extended_serving_profile_sha256"]
        and state.get("controller_source_bundle_sha256")
            == plan["controller_source_bundle_sha256"]
        and (spec is None or state.get("candidate")
             == window.qualification_plan.get("candidate"))
        and isinstance(state.get("worker_pid"), int)
        and isinstance(state.get("worker_start_ticks"), int)
        and state["worker_start_ticks"] > 0,
        "extended worker state is not bound to complete restoration",
    )
    _require(
        supervision.get("schema") == "flash-next-extended-supervision/v1"
        and supervision.get("pair_id") == window.pair_id
        and supervision.get("window_plan_sha256") == window.source_sha256
        and supervision.get("extended_plan_sha256") == execution_sha
        and supervision.get("candidate_variant_id") == plan["candidate_variant_id"]
        and supervision.get("candidate_spec_sha256") == plan["candidate_spec_sha256"]
        and supervision.get("controller_source_bundle_sha256")
            == plan["controller_source_bundle_sha256"]
        and supervision.get("pid") == state["worker_pid"]
        and isinstance(supervision.get("argv"), list)
        and len(supervision["argv"]) == 8
        and isinstance(supervision["argv"][0], str)
        and supervision["argv"][0] == plan["launcher_python_path"]
        and supervision["argv"][1:] == [
            "-m", "bench.flash_next_ab.extended_lifecycle",
            "--worker", "--eval-plan", str(window.source_path),
            "--output-dir", str(output),
        ]
        and supervision.get("argv_sha256") == sha256(supervision["argv"])
        and supervision.get("worker_start_ticks") == state["worker_start_ticks"]
        and supervision.get("boot_id") == state.get("boot_id")
        and supervision.get("returncode") == 0
        and supervision.get("terminated_at_work_cutoff") is False
        and supervision.get("force_killed") is False
        and supervision.get("emergency_recovery") is None
        and supervision.get("hard_deadline_seconds")
            == plan["effective_invocation_deadline_seconds"]
        and type(supervision.get("elapsed_seconds")) in {int, float}
        and math.isfinite(supervision["elapsed_seconds"])
        and 0 < supervision["elapsed_seconds"]
            <= plan["effective_invocation_deadline_seconds"]
        and supervision.get("elapsed_seconds") <= 14_400,
        "extended process exited without a verified supervised runtime",
    )
    _final_identity(result, state)
    _require(
        _utc_datetime(result.get("finished_at"), "extended result completion")
        <= _utc_datetime(supervision.get("finished_at"), "extended supervision completion")
        <= _utc_datetime(state.get("invocation_deadline_at"), "extended hard deadline"),
        "extended result/supervisor exceeded the registered deadline",
    )
    _memory(output, result, plan, spec)
    ui_observer = validate_ui_observer(output, result, state, plan)
    readiness = _bound_evidence(output, result, "readiness.json", "readiness_file_sha256", 4 * 1024 * 1024)
    container = readiness.get("container")
    quiet = readiness.get("stabilization")
    quiet_keys = {
        "required_seconds": "required_seconds", "passed": "passed",
        "started_at": "started_at", "completed_at": "completed_at",
        "duration_seconds": "duration_seconds", "initial_pswpout_pages": "initial_pswpout_pages",
        "final_pswpout_pages": "final_pswpout_pages", "samples": "samples", "epoch": "epoch",
    }
    _require(
        isinstance(container, dict) and isinstance(quiet, dict)
        and readiness.get("models") == [plan["served_model"]]
        and container.get("id") == state.get("candidate_id")
        and container.get("pid") == result.get("candidate_cgroup_pid")
        and result.get("candidate_cgroup_path")
            == f"/system.slice/docker-{container.get('id')}.scope"
        and container.get("image") == plan["image_id"]
        and container.get("name")
            == (spec.container_name if spec else CONTAINER_NAME)
        and container.get("running") is True
        and container.get("oom_killed") is False
        and container.get("restart_count") == 0
        and container.get("memory_limit_bytes")
            == (spec.docker_memory_limit_bytes if spec else DOCKER_MEMORY_LIMIT_BYTES)
        and container.get("memory_swap_total_bytes")
            == (spec.docker_memory_limit_bytes if spec else DOCKER_MEMORY_SWAP_TOTAL_BYTES)
        and all(
            quiet.get(key) == result.get(f"ready_quiescence_{suffix}")
            for key, suffix in quiet_keys.items()
        ),
        "fresh Flash readiness/60-second stabilization differs",
    )
    probes = _bound_evidence(output, result, "probes.json", "probes_file_sha256", 4 * 1024 * 1024)
    _validate_flash_probes(
        probes,
        probe_set=window.qualification_plan["probe_set"],
        served_model=plan["served_model"],
        artifact_sha256=plan["model_artifact_sha256"],
        endpoint_name=spec.endpoint_name if spec else "flash_next",
    )
    _bound_evidence(output, result, "probe-attempts.json", "probe_attempts_sha256", 4 * 1024 * 1024)
    _validate_mia_probe_attempts(output, probes)
    model = _bound_evidence(output, result, "model-verification.json", "model_verification_file_sha256", 4 * 1024 * 1024)
    _require(
        model.get("artifact_sha256") == plan["model_artifact_sha256"]
        and model.get("full_sha256") is True
        and model.get("verified_files") == contract["model"]["files"]
        and model.get("safetensors_total_bytes")
            == (spec.safetensors_total_bytes if spec else
                sum(size for size, _ in WEIGHT_FILES.values()))
        and (spec is None or (
            model.get("candidate") == window.qualification_plan.get("candidate")
            and model.get("packed_ple") == window.qualification_plan.get("packed_ple")
            and model.get("proof_receipts")
                == window.qualification_plan.get("proof_receipts")
            and result.get("model_verification_sha256") == sha256(model)
            and result.get("packed_ple") == window.qualification_plan.get("packed_ple"))),
        "extended model-verification digest lacks the full registered checkpoint",
    )
    attempt = _bound_evidence(output, result, "harness-attempt.json", "harness_attempt_sha256", 4 * 1024 * 1024)
    _require(
        attempt.get("schema_version") == "flash-next-extended-evaluation-harness-attempt/v1"
        and attempt.get("status") == "harness_complete_pending_restoration"
        and attempt.get("evaluation_complete") is False
        and attempt.get("restoration_required") is True
        and attempt.get("pair_id") == window.pair_id
        and attempt.get("window_plan_sha256") == window.source_sha256
        and attempt.get("extended_plan_sha256") == execution_sha
        and attempt.get("benchmark_plan_file_sha256") == window.benchmark_plan_file_sha256
        and attempt.get("qualification_receipt_sha256")
            == plan["prior_qualification_receipt_sha256"]
        and attempt.get("harness_run_path") == str(output / "harness" / "run.json")
        and attempt.get("harness_run_sha256") == result.get("harness_run_sha256")
        and result.get("harness_attempt_status")
            == "harness_complete_pending_restoration",
        "harness attempt is incomplete or unbound from restored window",
    )
    run_raw = _read_raw(output / "harness" / "run.json", "Flash harness run", 8 * 1024 * 1024)
    _require(
        hashlib.sha256(run_raw).hexdigest() == result["harness_run_sha256"],
        "Flash harness raw run digest changed after restoration",
    )
    run = _strict_object(run_raw, "Flash harness run")
    validate_run(run, "flash")
    validate_private_evidence(run, output / "harness")
    _require(
        run.get("status") == "complete" and run.get("plan") == window.benchmark_plan
        and run.get("run_id") == f"{window.pair_id}-flash"
        and result.get("benchmark_budget_seconds")
            == window.runtime_budget_seconds,
        "Flash run is incomplete or differs from the frozen benchmark matrix",
    )
    _research_usage(window.pair_id, execution_sha, result)
    return {
        "schema": "flash-next-extended-completed-window-validation/v1",
        "pair_id": window.pair_id,
        "cohort": "flash",
        "result_sha256": hashlib.sha256(
            _read_raw(output / "result.json", "final result", 4 * 1024 * 1024)
        ).hexdigest(),
        "harness_run_sha256": result["harness_run_sha256"],
        "window_plan_sha256": window.source_sha256,
        "benchmark_plan_file_sha256": window.benchmark_plan_file_sha256,
        "restoration_verified": True,
        "ui_observer_log_sha256": ui_observer["observer_log_sha256"],
        "ui_observer_failed_ticks": ui_observer["failed_tick_count"],
        "weekly_budget_debit": False,
        "paid_api_calls": 0,
        "production_change_authorized": False,
    }


def validate_completed_pair(flash_window: Path, flash_output: Path, resident_window: Path, resident_output: Path) -> dict:
    """Both cohorts must pass completed-window gates before index/export."""
    flash = validate_completed_flash_window(flash_window, flash_output)
    from .resident_admission import validate_completed_resident_window

    resident = validate_completed_resident_window(resident_window, resident_output)
    _require(
        resident["pair_id"] == flash["pair_id"]
        and resident["benchmark_plan_file_sha256"]
            == flash["benchmark_plan_file_sha256"],
        "completed arms do not share the same immutable benchmark plan",
    )
    return {
        "schema": "flash-next-supervised-pair-validation/v1",
        "pair_id": flash["pair_id"],
        "flash": flash,
        "resident": resident,
        "promotion_authorized": False,
    }
