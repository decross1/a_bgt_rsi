"""Draft UI-only operating-mode reader for supervised resident follow-on windows.

This is an off-tree copy until the active GPU window restores. It reads exact
registered sources and current worker/memory evidence; it never starts or
probes a model and never infers comparative task quality.
"""
from __future__ import annotations

import math
import os
import re
import stat
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from . import model_runtime as mr

RUN_ID = re.compile(r"qfn-followon-[a-z0-9][a-z0-9._-]{0,63}\.resident\Z")
STATE_SCHEMA = "flash-followon-resident-state/v1"
PLAN_SCHEMA = "flash-followon-resident-plan/v1"
MEMORY_SCHEMA = "flash-next-resident-research-memory-sample/v1"
TAIL_BYTES = 32_768
MAX_LOG_BYTES = 64 * 1024 * 1024
MAX_TAIL_AGE = timedelta(seconds=10)
TERMINAL = frozenset({"complete", "supervisor_recovered", "recovery_unknown"})
PHASES = frozenset({
    "preflight", "sentinel_create", "nara_quiescing", "evaluation",
    "evaluation_complete_pending_restoration", "restoration",
    *TERMINAL,
})


def _require(ok: bool, reason: str) -> None:
    if not ok:
        raise mr.RuntimeSourceError(reason)


def latest_slot_mtime(root: Path) -> int | None:
    """Include invalid newest resident state so older Flash cannot mask it."""
    try:
        root_fd = os.open(root, mr._flags(directory=True))
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise mr.RuntimeSourceError("resident runtime root is unavailable") from exc
    try:
        times = []
        seen = 0
        with os.scandir(root_fd) as entries:
            for entry in entries:
                seen += 1
                if seen > mr.MAX_RUNS:
                    raise mr.RuntimeSourceError("resident runtime scan bound exceeded")
                if not RUN_ID.fullmatch(entry.name):
                    continue
                try:
                    child = os.open(
                        entry.name, mr._flags(directory=True), dir_fd=root_fd,
                    )
                except OSError as exc:
                    raise mr.RuntimeSourceError("resident runtime child is unavailable") from exc
                try:
                    directory = os.fstat(child)
                    try:
                        state = os.stat(
                            "state.json", dir_fd=child, follow_symlinks=False,
                        )
                        times.append(
                            state.st_mtime_ns if stat.S_ISREG(state.st_mode)
                            else max(directory.st_mtime_ns, state.st_mtime_ns)
                        )
                    except OSError:
                        times.append(directory.st_mtime_ns)
                finally:
                    os.close(child)
        return max(times) if times else None
    finally:
        os.close(root_fd)


def _worker(state: dict, run_path: Path, source: Path, launcher: str,
            proc_root: Path) -> None:
    pid = mr._nonnegative_integer(state.get("worker_pid"),
                                  "resident worker PID", positive=True)
    ticks = mr._nonnegative_integer(state.get("worker_start_ticks"),
                                    "resident worker start ticks", positive=True)
    process = proc_root / str(pid)
    raw_stat = mr._read_path(
        process / "stat", maximum=mr.MAX_PROC_BYTES,
        label="resident worker stat",
    )
    try:
        text = raw_stat.decode("utf-8")
        closing = text.rfind(")")
        observed = int(text[closing + 1:].split()[19])
    except (UnicodeError, ValueError, IndexError) as exc:
        raise mr.RuntimeSourceError("resident worker stat is malformed") from exc
    _require(closing >= 0 and observed == ticks,
             "resident worker process identity differs")
    command_raw = mr._read_path(
        process / "cmdline", maximum=mr.MAX_PROC_BYTES,
        label="resident worker cmdline",
    )
    try:
        command = [part.decode("utf-8")
                   for part in command_raw.rstrip(b"\0").split(b"\0")]
    except UnicodeError as exc:
        raise mr.RuntimeSourceError("resident worker cmdline is malformed") from exc
    _require(command == [
        launcher, "-m", "bench.flash_next_ab.resident_evaluation_window",
        "--worker", "--eval-plan", str(source), "--output-dir", str(run_path),
    ], "resident worker invocation differs from registration")


def _last_memory(path: Path, observed: datetime, state: dict) -> dict:
    """Read at most one complete recent JSONL row from a live 64 MiB log."""
    try:
        descriptor = os.open(path, mr._flags())
    except OSError as exc:
        raise mr.RuntimeSourceError("resident memory tail is unavailable") from exc
    try:
        before = os.fstat(descriptor)
        _require(stat.S_ISREG(before.st_mode)
                 and 0 < before.st_size <= MAX_LOG_BYTES,
                 "resident memory log exceeds its registered bound")
        start = max(0, before.st_size - TAIL_BYTES)
        chunk = os.pread(descriptor, before.st_size - start, start)
        after = os.fstat(descriptor)
        _require((before.st_dev, before.st_ino)
                 == (after.st_dev, after.st_ino)
                 and len(chunk) == before.st_size - start,
                 "resident memory log changed identity during tail read")
    finally:
        os.close(descriptor)
    if start:
        chunk = chunk.partition(b"\n")[2]
    complete = chunk.rsplit(b"\n", 1)[0]
    lines = complete.splitlines()
    _require(bool(lines) and len(lines[-1]) <= TAIL_BYTES,
             "resident memory tail has no complete row")
    row = mr._strict_object(lines[-1], "recent resident memory sample")
    sample_time = mr._parse_time(row.get("observed_at"),
                                 "resident memory observation")
    _require(timedelta(0) <= observed - sample_time <= MAX_TAIL_AGE,
             "resident memory sample is stale or future-dated")
    nara = row.get("nara")
    _require(row.get("schema") == MEMORY_SCHEMA
             and row.get("monitor_phase") == "evaluation"
             and row.get("watchdog_sentinel_id")
                == state.get("watchdog_sentinel_id")
             and isinstance(nara, dict)
             and nara.get("ActiveState") == "inactive"
             and row.get("cgroup_swap_capture_status")
                == "exact_incumbent_pid_cgroup_bound"
             and type(row.get("mem_available_gib")) in {int, float}
             and math.isfinite(row["mem_available_gib"])
             and row["mem_available_gib"] >= 20,
             "resident memory/paused-service evidence differs")
    initial = state.get("initial")
    _require(isinstance(initial, dict)
             and isinstance(initial.get("residents"), list)
             and all(isinstance(item, dict)
                     and {"id", "name", "pid"} <= set(item)
                     for item in initial["residents"])
             and isinstance(initial.get("cgroups_by_name"), dict)
             and row.get("incumbent_ids")
                == [item["id"] for item in initial["residents"]]
             and row.get("incumbent_containers") == initial["residents"]
             and row.get("incumbent_pids")
                == {item["name"]: item["pid"]
                    for item in initial["residents"]},
             "resident memory row no longer binds incumbent identities")
    cgroups = row.get("incumbent_cgroups")
    stable = (
        "path", "process_start_ticks", "memory_max_bytes",
        "memory_swap_max_bytes", "memory_events_oom",
        "memory_events_oom_kill",
    )
    _require(isinstance(cgroups, dict)
             and set(cgroups) == set(initial["cgroups_by_name"])
             and all(
                 isinstance(cgroups[name], dict)
                 and all(cgroups[name].get(key) == before.get(key)
                         for key in stable)
                 for name, before in initial["cgroups_by_name"].items()
             ), "resident memory row no longer binds incumbent cgroups")
    return row


def _terminal_restoration(run_fd: int, state: dict, plan: dict,
                          run_path: Path, source: Path, boot: str) -> tuple[str, str]:
    """Operational restoration only; this does not admit block scores.

    The resident completed-window gate currently expects a result.started_at
    field absent from the authentic result; durable state and supervision each
    carry that time. This branch checks the recorded terminal receipts without
    changing their bytes or asserting comparison eligibility.
    """
    result_raw = mr._read_fd(run_fd, "result.json", maximum=mr.MAX_RESULT_BYTES,
                             label="resident terminal result")
    result = mr._strict_object(
        result_raw,
        "resident terminal result",
    )
    supervision_raw = mr._read_fd(
        run_fd, "supervision.json", maximum=mr.MAX_RESULT_BYTES,
        label="resident terminal supervision",
    )
    supervision = mr._strict_object(
        supervision_raw,
        "resident terminal supervision",
    )
    expected_argv = [
        plan["launcher_python_path"], "-m",
        "bench.flash_next_ab.resident_evaluation_window", "--worker",
        "--eval-plan", str(source), "--output-dir", str(run_path),
    ]
    restoration = result.get("restoration")
    final = result.get("final_observation")
    initial = state.get("initial")
    _require(state.get("phase") == "complete"
             and state.get("result_status") == "complete"
             and result.get("schema") == "flash-followon-resident-result/v1"
             and result.get("status") == "complete"
             and supervision.get("schema")
                == "flash-followon-resident-supervision/v1"
             and supervision.get("complete") is True
             and supervision.get("returncode") == 0
             and supervision.get("terminated_at_work_cutoff") is False
             and supervision.get("force_killed") is False
             and supervision.get("emergency_recovery") is None
             and supervision.get("argv") == expected_argv
             and supervision.get("command_sha256")
                == q_sha256(expected_argv)
             and result.get("pair_id") == state.get("pair_id")
                == supervision.get("pair_id")
             and result.get("plan_sha256") == state.get("plan_sha256")
                == supervision.get("plan_sha256")
             and result.get("window_plan_sha256")
                == state.get("window_plan_sha256")
             and result.get("qualified_parent_window")
                == state.get("qualified_parent_window")
             and result.get("evaluation_kind") == "followon"
             and result.get("followon_block_count")
                == len(plan["followon_blocks"])
             and result.get("group_attempt_status")
                == "blocks_complete_pending_restoration"
             and result.get("exact_final_verification") is True
             and result.get("weekly_budget_debit") is False
             and result.get("paid_api_calls") == 0
             and result.get("production_change_authorized") is False
             and state.get("worker_pid") == supervision.get("pid")
             and state.get("worker_start_ticks")
                == supervision.get("worker_start_ticks")
             and supervision.get("boot_id") == state.get("boot_id") == boot
             and isinstance(initial, dict) and isinstance(final, dict)
             and isinstance(restoration, dict)
             and restoration == state.get("restoration")
             and final == state.get("final_observation")
             and restoration.get("status") == "verified"
             and restoration.get("errors") == []
             and restoration.get("sentinel_retained") is False
             and restoration.get("final_observation") == final
             and final.get("watchdog_sentinel_by_name") is None
             and final.get("watchdog_sentinel_by_id") is None,
             "resident terminal state/result/supervision or restoration differs")
    started = mr._parse_time(state.get("started_at"), "resident terminal start")
    supervision_started = mr._parse_time(supervision.get("started_at"),
                                         "resident supervision start")
    result_finished = mr._parse_time(result.get("finished_at"),
                                     "resident terminal finish")
    supervisor_finished = mr._parse_time(supervision.get("finished_at"),
                                         "resident supervision finish")
    _require(supervision_started <= started <= result_finished
             <= supervisor_finished,
             "resident terminal publication chronology differs")
    _require(initial.get("residents") == final.get("residents")
             and initial.get("residents_by_name")
                == final.get("residents_by_name")
             and isinstance(initial.get("cgroups_by_name"), dict)
             and isinstance(final.get("cgroups_by_name"), dict),
             "resident terminal containers changed from captured identities")
    baseline = initial["cgroups_by_name"]
    observed = final["cgroups_by_name"]
    stable = (
        "path", "process_start_ticks", "memory_max_bytes",
        "memory_swap_max_bytes", "memory_events_oom",
        "memory_events_oom_kill",
    )
    _require(set(baseline) == set(observed)
             and all(isinstance(before, dict)
                     and isinstance(observed[name], dict)
                     and all(before.get(key) == observed[name].get(key)
                             for key in stable)
                     for name, before in baseline.items()),
             "resident terminal cgroup identities changed")
    original_nara = initial.get("nara")
    current_nara = final.get("nara")
    _require(isinstance(original_nara, dict)
             and isinstance(current_nara, dict)
             and original_nara.get("ActiveState") in {"active", "inactive"}
             and current_nara.get("ActiveState")
                == original_nara.get("ActiveState"),
             "resident terminal Nara activity was not restored")
    expected_nara = ("running" if original_nara["ActiveState"] == "active"
                     else "paused")
    terminal_sha = mr._composite_sha256(
        result=mr._sha256(result_raw),
        supervision=mr._sha256(supervision_raw),
    )
    return expected_nara, terminal_sha


def q_sha256(value: object) -> str:
    from bench.flash_next_ab import qualification as q
    return q.sha256(value)


def project_resident_runtime(root: Path, *, proc_root: Path,
                             boot_id_path: Path, observed: datetime) -> dict[str, Any]:
    """Admit one resident research phase without claiming Flash serves."""
    from bench.flash_next_ab import followon_plans as plans
    from bench.flash_next_ab import qualification as q

    run_fd, run_id, state_raw = mr._open_latest_run(root, namespace=RUN_ID)
    try:
        run_path = root / run_id
        state = mr._strict_object(state_raw, "resident follow-on state")
        pair_id = run_id.removesuffix(".resident")
        _require(state.get("schema") == STATE_SCHEMA
                 and state.get("pair_id") == pair_id
                 and state.get("phase") in PHASES
                 and state.get("evaluation_kind") == "followon"
                 and state.get("monitor_memory_log_relpath")
                    == "resident-memory.jsonl",
                 "resident follow-on state is not registered")
        source = plans.grouped._plan_path(pair_id, "resident",
                                          plans.grouped.RESEARCH_ROOT)
        from .registered_followon_plan import registered_expected

        registered = registered_expected(source, run_path,
                                         cohort="resident")
        expected = registered["plan"]
        source_sha = registered["source_sha256"]
        plan_raw = mr._read_fd(run_fd, "plan.json", maximum=mr.MAX_PLAN_BYTES,
                               label="resident follow-on plan")
        plan = mr._strict_object(plan_raw, "resident follow-on plan")
        _require(plan == expected and plan.get("schema") == PLAN_SCHEMA
                 and plan.get("output_dir") == str(run_path)
                 and plan.get("window_plan_sha256") == source_sha
                 and state.get("window_plan_sha256") == source_sha
                 and state.get("plan_sha256") == q.sha256(plan)
                 and state.get("followon_blocks") == plan["followon_blocks"]
                 and state.get("qualified_parent_window")
                    == plan["qualified_parent_window"],
                 "resident state/plan/source bindings differ")
        boot = mr._read_path(boot_id_path, maximum=128,
                             label="resident worker boot ID").decode().strip()
        _require(state.get("boot_id") == boot,
                 "resident worker belongs to an earlier boot")
        phase = state["phase"]
        terminal_sha = ""
        if phase in TERMINAL:
            nara, terminal_sha = _terminal_restoration(
                run_fd, state, plan, run_path, source, boot,
            )
            mode = "resident"
        else:
            deadline = mr._parse_time(state.get("invocation_deadline_at"),
                                      "resident invocation deadline")
            _require(observed < deadline,
                     "resident worker deadline expired")
            _worker(state, run_path, source,
                    expected["launcher_python_path"], proc_root)
            if phase == "evaluation":
                _last_memory(run_path / "resident-memory.jsonl", observed, state)
                mode, nara = "resident", "paused"
            else:
                mode, nara = "transitioning", "unknown"
        return {
            "schema_version": mr.SCHEMA_VERSION,
            "observed_at": observed.isoformat(),
            "mode": mode, "mode_source": "followon_resident_state",
            "mode_source_sha256": mr._composite_sha256(
                state=mr._sha256(state_raw), plan=mr._sha256(plan_raw),
                window=source_sha, terminal=terminal_sha,
            ),
            "resident_services_expected": (
                "online" if mode == "resident" else "unknown"
            ),
            "nara_service_expected": nara,
            "run_id": run_id, "phase": phase,
            "candidate_variant": None, "source_error": None,
        }
    finally:
        os.close(run_fd)
