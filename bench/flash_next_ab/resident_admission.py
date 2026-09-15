"""UNAPPLIED DRAFT: read-only gate for a fully supervised incumbent cohort.

A saved harness run is only a pending observation. This gate requires the
unchanged original residents, continuous raw safety evidence, a complete frozen
run, and an independently completed worker/supervisor before pairing it.
"""
from __future__ import annotations

import hashlib
import math
import re
from datetime import timedelta
from pathlib import Path

from .compare import validate_run
from .evaluation_window import (
    MIN_MEMORY_GIB,
    RESEARCH_LEDGER,
    WINDOW_DEADLINE_SECONDS,
    load_evaluation_window,
)
from .harness import _read_regular_file, _strict_object, _utc_datetime
from .private_evidence import validate_private_evidence
from .qualification import RESIDENTS, sha256
from .resident_evaluation_window import _registered_output, _resident_plan


class ResidentAdmissionError(ValueError):
    """The incumbent window cannot support a paired result."""


def _require(valid: bool, message: str) -> None:
    if not valid:
        raise ResidentAdmissionError(message)


def _raw(path: Path, label: str, maximum: int) -> bytes:
    content, actual = _read_regular_file(path, label=label, max_bytes=maximum)
    _require(actual == path.absolute(), f"{label} path changed")
    return content


def _json(path: Path, label: str, maximum: int = 2_000_000) -> dict:
    return _strict_object(_raw(path, label, maximum), label)


def _identity(initial: dict, quiet: dict, final: dict) -> None:
    _require(
        isinstance(initial, dict) and isinstance(quiet, dict) and isinstance(final, dict)
        and isinstance(initial.get("residents"), list)
        and isinstance(quiet.get("residents"), list)
        and isinstance(final.get("residents"), list)
        and len(initial["residents"]) == len(RESIDENTS)
        and len(quiet["residents"]) == len(RESIDENTS)
        and len(final["residents"]) == len(RESIDENTS),
        "initial/final incumbent identities are incomplete",
    )
    names = {registered["name"] for registered in RESIDENTS}
    for observation in (initial, quiet, final):
        _require(
            isinstance(observation.get("residents_by_name"), dict)
            and set(observation["residents_by_name"]) == names
            and isinstance(observation.get("cgroups_by_name"), dict)
            and set(observation["cgroups_by_name"]) == names
            and isinstance(observation.get("nara"), dict)
            and observation["nara"].get("ActiveState") in {"active", "inactive"},
            "incumbent names, cgroups, or Nara observation differ",
        )
    original = initial["nara"]
    restored = final["nara"]
    _require(
        original["ActiveState"] in {"active", "inactive"}
        and quiet["nara"]["ActiveState"] == "inactive"
        and restored["ActiveState"] == original["ActiveState"]
        and (
            original["ActiveState"] == "inactive"
            or original["SubState"] == restored["SubState"] == "running"
            and original["MainPID"].isdigit() and int(original["MainPID"]) > 0
            and restored["MainPID"].isdigit() and int(restored["MainPID"]) > 0
        ),
        "Nara was not quiescent for resident calls or restored healthy",
    )
    for registered, before, quiesced, after in zip(
        RESIDENTS, initial["residents"], quiet["residents"],
        final["residents"], strict=True
    ):
        stable = ("id", "name", "image", "restart_policy", "restart_count", "pid", "started_at")
        _require(
            isinstance(before, dict) and isinstance(after, dict)
            and before.get("id") == registered["id"]
            and before.get("name") == registered["name"]
            and before.get("image") == registered["image_id"]
            and all(observed.get(key) == before.get(key)
                    for observed in (quiesced, after) for key in stable)
            and all(observed.get("running") is True
                    and observed.get("oom_killed") is False
                    and observed.get("state_error") == ""
                    for observed in (before, quiesced, after))
            and before.get("restart_policy") == "unless-stopped"
            and type(before.get("restart_count")) is int
            and type(before.get("pid")) is int and before["pid"] > 0
            and observation_row_matches(initial, before)
            and observation_row_matches(quiet, quiesced)
            and observation_row_matches(final, after),
            "incumbent container identity, restart, or health differs",
        )
        early = initial["cgroups_by_name"][registered["name"]]
        middle = quiet["cgroups_by_name"][registered["name"]]
        late = final["cgroups_by_name"][registered["name"]]
        _cgroup(early, registered["id"])
        _cgroup(middle, registered["id"])
        _cgroup(late, registered["id"])
        _require(
            all(observed[key] == early[key] for observed in (middle, late) for key in (
                "path", "process_start_ticks", "memory_max_bytes",
                "memory_swap_max_bytes", "memory_events_oom", "memory_events_oom_kill"
            )),
            "incumbent cgroup changed or reported an OOM",
        )


def observation_row_matches(observation: dict, row: dict) -> bool:
    return observation["residents_by_name"].get(row["name"]) == row


def _cgroup(row: dict, container_id: str) -> None:
    _require(
        isinstance(row, dict)
        and row.get("path") == f"/system.slice/docker-{container_id}.scope"
        and type(row.get("process_start_ticks")) is int
        and row["process_start_ticks"] > 0
        and all(type(row.get(key)) is int and row[key] >= 0 for key in (
            "memory_current_bytes", "memory_swap_current_bytes",
            "memory_events_oom", "memory_events_oom_kill",
        ))
        and all(row.get(key) == "max" or type(row.get(key)) is int and row[key] >= 0
            for key in ("memory_max_bytes", "memory_swap_max_bytes")),
        "incumbent cgroup PID, kernel limit, or counter is malformed",
    )


def _memory(output: Path, result: dict, initial: dict, quiet: dict, final: dict) -> None:
    content = _raw(output / "resident-memory.jsonl", "resident safety log", 64 * 1024 * 1024)
    _require(
        hashlib.sha256(content).hexdigest() == result.get("memory_log_sha256"),
        "resident raw safety evidence changed",
    )
    rows = [_strict_object(line, f"resident memory row {i}")
            for i, line in enumerate(content.splitlines(), 1)]
    _require(
        len(rows) >= 2 and len(rows) == result.get("memory_samples"),
        "resident safety sampling count is incomplete",
    )
    initial_at = _utc_datetime(initial.get("observed_at"), "resident initial identity")
    final_at = _utc_datetime(final.get("observed_at"), "resident final identity")
    previous_mono = None
    previous_swap = None
    previous_at = initial_at
    minimum = math.inf
    phases: list[str] = []
    sentinel_id = result["watchdog_sentinel_id"]
    expected_phase = ("setup", "quiescing", "evaluation", "restoration")
    for row in rows:
        observed_at = _utc_datetime(row.get("observed_at"), "resident memory timestamp")
        seconds = row.get("observed_monotonic")
        available = row.get("mem_available_gib")
        pages = row.get("host_pswpout_pages")
        _require(
            row.get("schema") == "flash-next-resident-research-memory-sample/v1"
            and type(seconds) in {int, float} and math.isfinite(seconds) and seconds >= 0
            and type(available) in {int, float} and math.isfinite(available)
            and available >= MIN_MEMORY_GIB
            and type(pages) is int and pages >= 0
            and (previous_mono is None or 0 < seconds - previous_mono <= 10)
            and (previous_swap is None or pages >= previous_swap)
            and previous_at <= observed_at <= final_at,
            "resident memory, counter, chronology, or sampling cadence breached",
        )
        minimum = min(minimum, available)
        phase = row.get("monitor_phase")
        _require(
            phase in expected_phase
            and (not phases or phase == phases[-1]
                 or expected_phase.index(phase) == expected_phase.index(phases[-1]) + 1)
            and (row.get("watchdog_sentinel_id") in {None, sentinel_id})
            and (phase == "setup" or row.get("watchdog_sentinel_id") == sentinel_id),
            "resident Nara isolation or watchdog sampling chronology differs",
        )
        phases.append(phase)
        expected = initial["residents"]
        _require(
            row.get("incumbent_ids") == [item["id"] for item in expected]
            and row.get("incumbent_restart_counts")
                == {item["name"]: item["restart_count"] for item in expected}
            and row.get("incumbent_pids")
                == {item["name"]: item["pid"] for item in expected}
            and row.get("incumbent_containers") == expected
            and row.get("cgroup_swap_capture_status")
                == "exact_incumbent_pid_cgroup_bound",
            "resident safety sample changed incumbent identities",
        )
        cgroups = row.get("incumbent_cgroups")
        nara = row.get("nara")
        _require(
            isinstance(nara, dict)
            and nara.get("ActiveState") in {
                "active", "inactive", "activating", "deactivating", "failed"
            }
            and type(nara.get("MainPID")) is str and nara["MainPID"].isdigit()
            and (
                phase == "setup" and nara == initial["nara"]
                or phase == "evaluation" and nara == quiet["nara"]
                or phase == "quiescing"
                or phase == "restoration"
            ),
            "resident model observation includes unexpected Nara activity",
        )
        _require(
            isinstance(cgroups, dict)
            and set(cgroups) == set(initial["cgroups_by_name"])
            and row.get("incumbent_cgroup_swap_bytes")
                == {name: cgroup.get("memory_swap_current_bytes")
                    for name, cgroup in cgroups.items()},
            "resident raw cgroup sampling is missing or inconsistent",
        )
        for resident in RESIDENTS:
            name = resident["name"]
            snapshot = cgroups[name]
            _cgroup(snapshot, resident["id"])
            baseline = initial["cgroups_by_name"][name]
            _require(
                all(snapshot[key] == baseline[key] for key in (
                    "path", "process_start_ticks", "memory_max_bytes",
                    "memory_swap_max_bytes", "memory_events_oom", "memory_events_oom_kill"
                )),
                "resident process, kernel limit, or local OOM changed during cohort",
            )
        previous_mono = seconds
        previous_swap = pages
        previous_at = observed_at
    _require(result.get("min_mem_available_gib") == minimum, "reported resident minimum differs")
    _require(
        phases[0] == "setup" and phases[-1] == "restoration"
        and all(phase in phases for phase in expected_phase)
        and rows[-1]["nara"]["ActiveState"] == initial["nara"]["ActiveState"]
        and rows[-1]["watchdog_sentinel_id"] == sentinel_id,
        "resident quiescence, evaluation, or restoration was not sampled",
    )
    _require(
        _utc_datetime(rows[0].get("observed_at"), "first resident safety sample")
            <= initial_at + timedelta(seconds=10)
        and final_at <= previous_at + timedelta(seconds=10),
        "resident monitoring stopped before the final exact identity check",
    )


def _usage(window, result: dict, result_at) -> None:
    content = _raw(RESEARCH_LEDGER, "local model research usage", 64 * 1024 * 1024)
    entries = [_strict_object(line, f"usage journal row {i}")
               for i, line in enumerate(content.splitlines(), 1) if line]
    started = [row for row in entries
               if row.get("event") == "resident_evaluation_started"
               and row.get("pair_id") == window.pair_id]
    ended = [row for row in entries
             if row.get("event") == "resident_evaluation_finished"
             and row.get("pair_id") == window.pair_id]
    _require(
        len(started) == 1 and len(ended) == 1
        and ended[0].get("status") == "complete"
        and all(row.get("plan_sha256") == result["plan_sha256"]
            and row.get("weekly_budget_debit") is False
            and row.get("paid_api_calls") == 0 for row in (*started, *ended))
        and _utc_datetime(started[0].get("observed_at"), "resident usage start")
            <= _utc_datetime(ended[0].get("observed_at"), "resident usage end")
            <= result_at,
        "completed resident cohort has no ordered uncapped usage entries",
    )


def validate_completed_resident_window(window_path: Path, output_dir: Path) -> dict:
    """Admit a resident run only after exact final identity and supervisor exit."""
    window = load_evaluation_window(window_path, expected_cohort="resident")
    output = _registered_output(window.pair_id, output_dir, absent=False)
    expected = _resident_plan(window, output)
    plan = _json(output / "plan.json", "resident supervisor plan")
    _require(plan == expected, "resident supervisor plan differs from frozen source")
    result = _json(output / "result.json", "resident final window result")
    state = _json(output / "state.json", "resident final worker state")
    supervisor = _json(output / "supervision.json", "resident final supervisor")
    restoration = result.get("restoration")
    sentinel_id = result.get("watchdog_sentinel_id")
    _require(
        result.get("schema") == "flash-next-resident-evaluation-result/v2"
        and result.get("pair_id") == window.pair_id
        and result.get("status") == "complete"
        and result.get("error") is None
        and result.get("exact_final_verification") is True
        and result.get("plan_sha256") == sha256(plan)
        and result.get("window_plan_sha256") == window.source_sha256
        and result.get("benchmark_plan_file_sha256") == window.benchmark_plan_file_sha256
        and result.get("resident_qualification_receipt_sha256")
            == plan["resident_qualification_receipt_sha256"]
        and isinstance(restoration, dict)
        and restoration.get("status") == "verified"
        and restoration.get("errors") == []
        and restoration.get("sentinel_retained") is False
        and restoration.get("no_mutation_verified") is False
        and restoration.get("original_nara_activity")
            == result.get("initial_observation", {}).get("nara", {}).get("ActiveState")
        and restoration.get("final_observation") == result.get("final_observation")
        and isinstance(sentinel_id, str)
        and re.fullmatch(r"[0-9a-f]{64}", sentinel_id)
        and result.get("host_swap_action") == "diagnostic_only"
        and result.get("candidate_cgroup_zero_swap_action")
            == "not_applicable_to_incumbents"
        and result.get("weekly_budget_debit") is False
        and result.get("paid_api_calls") == 0
        and result.get("production_change_authorized") is False,
        "resident window is incomplete or differs from frozen source",
    )
    _require(
        state.get("schema") == "flash-next-resident-evaluation-state/v2"
        and state.get("pair_id") == window.pair_id
        and state.get("plan_sha256") == sha256(plan)
        and state.get("window_plan_sha256") == window.source_sha256
        and state.get("phase") == "complete"
        and state.get("result_status") == "complete"
        and type(state.get("worker_pid")) is int and state["worker_pid"] > 0
        and type(state.get("worker_start_ticks")) is int and state["worker_start_ticks"] > 0
        and isinstance(state.get("boot_id"), str) and len(state["boot_id"]) == 36
        and state.get("initial") == result.get("initial_observation")
        and state.get("quiet_observation") == result.get("quiet_observation")
        and state.get("final_observation") == result.get("final_observation")
        and state.get("watchdog_sentinel_id") == sentinel_id
        and state.get("restoration") == restoration
        and state.get("nara_stop_attempted") is
            (result["initial_observation"]["nara"]["ActiveState"] == "active")
        and state.get("monitor_memory_log_relpath") == "resident-memory.jsonl",
        "resident worker identity, phase, or initial state differs",
    )
    command = [
        plan["launcher_python_path"], "-m", "bench.flash_next_ab.resident_evaluation_window",
        "--worker", "--eval-plan", str(window.source_path), "--output-dir", str(output),
    ]
    _require(
        supervisor.get("schema") == "flash-next-resident-supervision/v1"
        and supervisor.get("pair_id") == window.pair_id
        and supervisor.get("plan_sha256") == sha256(plan)
        and supervisor.get("command_sha256") == sha256(command)
        and supervisor.get("argv") == command
        and supervisor.get("pid") == state["worker_pid"]
        and supervisor.get("worker_start_ticks") == state["worker_start_ticks"]
        and supervisor.get("boot_id") == state["boot_id"]
        and supervisor.get("returncode") == 0
        and supervisor.get("complete") is True
        and supervisor.get("terminated_at_work_cutoff") is False
        and supervisor.get("force_killed") is False
        and supervisor.get("emergency_recovery") is None
        and type(supervisor.get("elapsed_seconds")) in {int, float}
        and math.isfinite(supervisor["elapsed_seconds"])
        and 0 < supervisor["elapsed_seconds"] <= WINDOW_DEADLINE_SECONDS,
        "resident worker did not complete within its exact supervisor deadline",
    )
    initial = state["initial"]
    quiet = state["quiet_observation"]
    final = result.get("final_observation")
    _identity(initial, quiet, final)
    _require(
        final.get("watchdog_sentinel_by_name") is None
        and final.get("watchdog_sentinel_by_id") is None,
        "resident watchdog sentinel was not removed after exact restoration",
    )
    started = _utc_datetime(initial.get("observed_at"), "resident initial observation")
    quiesced = _utc_datetime(quiet.get("observed_at"), "resident quiescence")
    finished = _utc_datetime(final.get("observed_at"), "resident final observation")
    parent_started = _utc_datetime(supervisor.get("started_at"), "supervisor start")
    worker_started = _utc_datetime(state.get("started_at"), "resident worker start")
    result_at = _utc_datetime(result.get("finished_at"), "resident result finish")
    supervisor_at = _utc_datetime(supervisor.get("finished_at"), "resident supervisor finish")
    deadline_at = _utc_datetime(state.get("invocation_deadline_at"), "resident deadline")
    parent_deadline_at = _utc_datetime(supervisor.get("hard_deadline_at"), "supervisor deadline")
    _require(
        parent_started <= worker_started <= started <= quiesced <= finished <= result_at
        <= supervisor_at <= parent_deadline_at
        and parent_deadline_at - parent_started == timedelta(seconds=WINDOW_DEADLINE_SECONDS)
        and deadline_at - worker_started == timedelta(seconds=WINDOW_DEADLINE_SECONDS)
        and result_at <= deadline_at,
        "resident actual observation, publication, or deadline chronology differs",
    )
    _memory(output, result, initial, quiet, final)
    harness_path = output / "harness" / "run.json"
    run_raw = _raw(harness_path, "resident harness run", 8 * 1024 * 1024)
    _require(
        result.get("harness_run_sha256") == hashlib.sha256(run_raw).hexdigest(),
        "resident harness run changed after final identity verification",
    )
    run = _strict_object(run_raw, "resident harness run")
    validate_run(run, "resident")
    validate_private_evidence(run, output / "harness")
    _require(
        run.get("schema_version") == "flash-next-ab-run/v1"
        and run.get("status") == "complete"
        and run.get("run_id") == f"{window.pair_id}-resident"
        and run.get("plan") == window.benchmark_plan
        and run.get("promotion_authorized") is False
        and run.get("elapsed_s") <= window.runtime_budget_seconds,
        "resident complete cohort differs from immutable benchmark matrix",
    )
    _usage(window, result, result_at)
    return {
        "schema": "flash-next-resident-completed-window-validation/v1",
        "pair_id": window.pair_id,
        "cohort": "resident",
        "result_sha256": hashlib.sha256(
            _raw(output / "result.json", "resident final result", 2_000_000)
        ).hexdigest(),
        "harness_run_sha256": result["harness_run_sha256"],
        "benchmark_plan_file_sha256": window.benchmark_plan_file_sha256,
        "restoration_verified": True,
        "weekly_budget_debit": False,
        "paid_api_calls": 0,
        "production_change_authorized": False,
    }
