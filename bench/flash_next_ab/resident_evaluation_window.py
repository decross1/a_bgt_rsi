"""Supervise a qualified resident evaluation under Nara isolation.

Original portfolio and new follow-on sources have distinct exact selectors.
Every worker block remains inside the incumbent monitor and exact restoration
path; the CLI never treats an incomplete window as comparable evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import signal
import stat
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from orchestrator.weekly_upgrade_trial import canonical_root, resource_lease

from .compare import validate_run
from .evaluation_window import (
    FULL_COHORT_BUDGET_SECONDS,
    MIN_MEMORY_GIB,
    REGISTERED_CODE_ROOT,
    RESEARCH_LEDGER,
    RESTORATION_RESERVE_SECONDS,
    WINDOW_DEADLINE_SECONDS,
    WINDOW_RUN_ROOT,
    EvaluationWindowError,
    _append_usage,
    _atomic_json,
    _qualification_gate,
    frozen_controller_source_bundle,
    load_evaluation_window,
)
from .harness import _read_regular_file, run_harness
from .qualification import (
    IMAGE_ID,
    NARA_SERVICE,
    RESIDENTS,
    ROOT,
    HostOps,
    QualificationError,
    _available_gib,
    _bounded_nofollow_bytes,
    _inspect_container,
    _memory_events,
    _nonnegative_decimal,
    _process_start_ticks,
    _pswpout_pages,
    _read_bounded_run_json,
    _remaining_timeout,
    _self_start_ticks,
    _service_state,
    sha256,
    utc_now,
)


def _registered_output(pair_id: str, output_dir: str | Path, *, absent: bool) -> Path:
    output = Path(os.path.abspath(Path(output_dir)))
    expected = WINDOW_RUN_ROOT / f"{pair_id}.resident"
    if (
        WINDOW_RUN_ROOT.is_symlink() or not WINDOW_RUN_ROOT.is_dir()
        or WINDOW_RUN_ROOT.resolve() != WINDOW_RUN_ROOT
        or output != expected or output.parent != WINDOW_RUN_ROOT
        or (absent and output.exists())
        or (output.exists() and (output.is_symlink() or not output.is_dir()))
    ):
        raise EvaluationWindowError("resident cohort output is outside the pair namespace")
    return output


def _sentinel_name(pair_id: str) -> str:
    if re.fullmatch(r"(?:qfn-ab|qfn-followon)-[a-z0-9][a-z0-9._-]{0,63}", pair_id) is None:
        raise EvaluationWindowError("resident watchdog pair namespace is invalid")
    return f"vllm-qwen-ab-resident-{pair_id}"


def _sentinel_command(pair_id: str) -> list[str]:
    # This container is never started, has no GPU access, and keeps the
    # incumbent Docker IDs untouched while cron sees its A/B namespace.
    return [
        "docker", "create", "--name", _sentinel_name(pair_id),
        "--restart=no", "--network=none", IMAGE_ID, "/bin/true",
    ]


def _verify_sentinel(ops: HostOps, pair_id: str, sentinel_id: str) -> dict:
    if re.fullmatch(r"[0-9a-f]{64}", sentinel_id) is None:
        raise EvaluationWindowError("resident sentinel ID is untrusted")
    by_name = _inspect_container(ops, _sentinel_name(pair_id))
    by_id = _inspect_container(ops, sentinel_id)
    if (
        by_id is None or by_name is None
        or by_name["id"] != by_id["id"] or by_id["id"] != sentinel_id
        or by_id.get("name") != _sentinel_name(pair_id)
        or by_id.get("image") != IMAGE_ID or by_id.get("running") is not False
        or by_id.get("oom_killed") is not False or by_id.get("state_error") != ""
        or by_id.get("restart_policy") != "no"
    ):
        raise EvaluationWindowError("resident watchdog sentinel identity drifted")
    return by_id


def _create_sentinel(ops: HostOps, pair_id: str) -> str:
    name = _sentinel_name(pair_id)
    if _inspect_container(ops, name) is not None:
        raise EvaluationWindowError("resident watchdog sentinel already exists")
    raw_id = ops.run(_sentinel_command(pair_id), timeout=30).stdout.strip()
    _verify_sentinel(ops, pair_id, raw_id)
    return raw_id


def _ensure_nara_activity(ops: HostOps, initial: dict, *, deadline: float) -> dict:
    original = initial.get("nara", {}).get("ActiveState")
    if original not in {"active", "inactive"}:
        raise EvaluationWindowError("original Nara activity is not captured")
    _read_exact_residents(ops, initial, nara_transition=True)
    observed = _service_observation(ops, transitioning=True)
    if observed["ActiveState"] != original:
        action = "start" if original == "active" else "stop"
        ops.run(
            ["systemctl", "--user", action, NARA_SERVICE],
            timeout=_remaining_timeout(deadline, 30),
        )
    while time.monotonic() < deadline:
        _read_exact_residents(ops, initial, nara_transition=True)
        observed = _service_observation(ops, transitioning=True)
        if observed["ActiveState"] == original and (
            original == "inactive" or observed["SubState"] == "running"
            and int(observed["MainPID"]) > 0
        ):
            break
        time.sleep(min(1, max(0, deadline - time.monotonic())))
    else:
        raise EvaluationWindowError("original Nara activity was not restored before deadline")
    service = _service_state(ops)
    if service["ActiveState"] != original:
        raise EvaluationWindowError("original Nara activity changed during final verification")
    _read_exact_residents(ops, initial, nara_transition=True)
    return service


def _remove_sentinel(ops: HostOps, pair_id: str, sentinel_id: str, *, deadline: float) -> None:
    _verify_sentinel(ops, pair_id, sentinel_id)
    ops.run(
        ["docker", "rm", sentinel_id],
        timeout=_remaining_timeout(deadline, 20),
    )
    if (
        _inspect_container(ops, sentinel_id) is not None
        or _inspect_container(ops, _sentinel_name(pair_id)) is not None
    ):
        raise EvaluationWindowError("resident watchdog sentinel removal was not verified")


def restore_resident_window(
    ops: HostOps, state: dict, plan: dict, *, deadline: float,
    monitor: ResidentSafetyMonitor | None = None,
) -> dict:
    """Restore only the captured Nara activity; never stop/recreate residents."""
    errors: list[str] = []
    initial = state.get("initial")
    sentinel_id = state.get("watchdog_sentinel_id")
    pair_id = plan["pair_id"]
    if not isinstance(initial, dict):
        unexpected = _inspect_container(ops, _sentinel_name(pair_id))
        return {
            "status": "verified" if unexpected is None else "unknown",
            "verified_at": utc_now() if unexpected is None else None,
            "errors": [] if unexpected is None else ["uncaptured watchdog sentinel exists"],
            "sentinel_retained": unexpected is not None,
            "original_nara_activity": None, "final_observation": None,
            "no_mutation_verified": unexpected is None,
        }
    if sentinel_id is None and state.get("nara_stop_attempted") is False:
        unexpected = _inspect_container(ops, _sentinel_name(pair_id))
        if unexpected is None:
            final = _read_exact_residents(ops, initial)
            final["watchdog_sentinel_by_name"] = None
            final["watchdog_sentinel_by_id"] = None
            return {
                "status": "verified", "verified_at": utc_now(), "errors": [],
                "sentinel_retained": False,
                "original_nara_activity": initial["nara"]["ActiveState"],
                "final_observation": final, "no_mutation_verified": True,
            }
    original_activity = initial.get("nara", {}).get("ActiveState")
    if original_activity not in {"active", "inactive"}:
        errors.append("original service activity is unknown")
    try:
        _read_exact_residents(ops, initial, nara_transition=True)
    except Exception as exc:  # noqa: BLE001 - never start Nara ahead of exact model health
        errors.append(f"resident identity/health before Nara: {type(exc).__name__}: {exc}")
    if not errors:
        try:
            _ensure_nara_activity(ops, initial, deadline=deadline)
        except Exception as exc:  # noqa: BLE001 - continue independent final-state audits
            errors.append(f"original Nara activity: {type(exc).__name__}: {exc}")
    if not errors:
        try:
            _read_exact_residents(ops, initial, nara_transition=True)
            if monitor is not None:
                monitor.sample()
        except Exception as exc:  # noqa: BLE001 - exact model safety after Nara transition
            errors.append(f"resident identity/health after Nara: {type(exc).__name__}: {exc}")
    if not errors:
        try:
            if not isinstance(sentinel_id, str):
                raise EvaluationWindowError("durable watchdog sentinel ID is missing")
            _remove_sentinel(ops, pair_id, sentinel_id, deadline=deadline)
        except Exception as exc:  # noqa: BLE001 - preserve a known sentinel until verified
            errors.append(f"watchdog sentinel: {type(exc).__name__}: {exc}")
    final = None
    try:
        final = _read_exact_residents(ops, initial, nara_transition=True)
    except Exception as exc:  # noqa: BLE001 - final proof cannot be inferred from prior polls
        errors.append(f"final runtime observation: {type(exc).__name__}: {exc}")
    by_name = _inspect_container(ops, _sentinel_name(pair_id))
    by_id = _inspect_container(ops, sentinel_id) if isinstance(sentinel_id, str) else None
    sentinel_retained = by_name is not None or by_id is not None
    if final is not None:
        final["watchdog_sentinel_by_name"] = by_name
        final["watchdog_sentinel_by_id"] = by_id
    if not errors and sentinel_retained:
        errors.append("resident watchdog sentinel persisted after final health")
    if not errors and final is not None and final["nara"]["ActiveState"] != original_activity:
        errors.append("final Nara activity differs from its original activity")
    status = "verified" if not errors else "unknown"
    return {
        "status": status,
        "verified_at": utc_now() if status == "verified" else None,
        "errors": errors,
        "sentinel_retained": sentinel_retained,
        "original_nara_activity": original_activity,
        "final_observation": final,
        "no_mutation_verified": False,
    }


def _incumbent_cgroup_snapshot(container_id: str, pid: int) -> dict:
    """Bind an exact incumbent PID, accepting its existing unlimited cgroup."""
    if (
        re.fullmatch(r"[0-9a-f]{64}", container_id) is None
        or type(pid) is not int or pid <= 0
    ):
        raise EvaluationWindowError("incumbent cgroup identity is malformed")
    path = f"/system.slice/docker-{container_id}.scope"
    start_ticks = _process_start_ticks(pid)
    proc_path = Path(f"/proc/{pid}/cgroup")
    proc_before = _bounded_nofollow_bytes(proc_path, max_bytes=4096)
    if proc_before != f"0::{path}\n".encode():
        raise EvaluationWindowError("incumbent PID is outside its exact Docker scope")
    directory = os.open(
        Path("/sys/fs/cgroup") / path.removeprefix("/"),
        os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        def limit(filename: str) -> int | str:
            raw = _bounded_nofollow_bytes(Path(filename), max_bytes=128, dir_fd=directory)
            if raw.strip() == b"max":
                return "max"
            return _nonnegative_decimal(raw, label=f"incumbent cgroup {filename}")

        memory_max = limit("memory.max")
        swap_max = limit("memory.swap.max")
        current = _nonnegative_decimal(
            _bounded_nofollow_bytes(Path("memory.current"), max_bytes=128, dir_fd=directory),
            label="incumbent cgroup memory.current",
        )
        swap = _nonnegative_decimal(
            _bounded_nofollow_bytes(Path("memory.swap.current"), max_bytes=128, dir_fd=directory),
            label="incumbent cgroup memory.swap.current",
        )
        events = _memory_events(
            _bounded_nofollow_bytes(Path("memory.events.local"), max_bytes=4096, dir_fd=directory)
        )
    finally:
        os.close(directory)
    if _bounded_nofollow_bytes(proc_path, max_bytes=4096) != proc_before or _process_start_ticks(pid) != start_ticks:
        raise EvaluationWindowError("incumbent cgroup or PID changed during sampling")
    return {
        "path": path,
        "process_start_ticks": start_ticks,
        "memory_max_bytes": memory_max,
        "memory_swap_max_bytes": swap_max,
        "memory_current_bytes": current,
        "memory_swap_current_bytes": swap,
        "memory_events_local": events,
        "memory_events_oom": events["oom"],
        "memory_events_oom_kill": events["oom_kill"],
    }


def _service_observation(ops: HostOps, *, transitioning: bool = False) -> dict[str, str]:
    if not transitioning:
        return _service_state(ops)
    observed = ops.run(
        [
            "systemctl", "--user", "show", NARA_SERVICE,
            "--property=ActiveState", "--property=SubState", "--property=MainPID",
            "--no-pager",
        ],
        timeout=5,
    ).stdout
    fields: dict[str, str] = {}
    for line in observed.splitlines():
        key, separator, value = line.partition("=")
        if not separator or key in fields:
            raise EvaluationWindowError("Nara transition fields are ambiguous")
        fields[key] = value
    if (
        set(fields) != {"ActiveState", "SubState", "MainPID"}
        or fields["ActiveState"] not in {
            "active", "inactive", "activating", "deactivating", "failed"
        }
        or not fields["MainPID"].isdigit()
    ):
        raise EvaluationWindowError("Nara transition is not an expected service activity")
    return fields


def _read_exact_residents(
    ops: HostOps, initial: dict | None = None, *, nara_transition: bool = False
) -> dict:
    rows = []
    cgroups = {}
    for registered in RESIDENTS:
        identity = _inspect_container(ops, registered["id"])
        named = _inspect_container(ops, registered["name"])
        if (
            identity is None or named is None or named["id"] != registered["id"]
            or identity["id"] != registered["id"]
            or identity["name"] != registered["name"]
            or identity["image"] != registered["image_id"]
            or identity["running"] is not True
            or identity["oom_killed"] is not False
            or identity["state_error"] != ""
            or identity["restart_policy"] != "unless-stopped"
            or not isinstance(identity["restart_count"], int)
            or isinstance(identity["restart_count"], bool)
            or identity["restart_count"] < 0
        ):
            raise EvaluationWindowError("registered incumbent container changed")
        ops.http_bytes(registered["health_url"], timeout=2)
        if not isinstance(identity["pid"], int) or identity["pid"] <= 0:
            raise EvaluationWindowError("incumbent process PID is unavailable")
        cgroup = _incumbent_cgroup_snapshot(registered["id"], identity["pid"])
        if initial is not None:
            before = initial["residents_by_name"][registered["name"]]
            before_cgroup = initial["cgroups_by_name"][registered["name"]]
            if (
                identity["restart_count"] != before["restart_count"]
                or identity["pid"] != before["pid"]
                or identity["started_at"] != before["started_at"]
                or cgroup["path"] != before_cgroup["path"]
                or cgroup["process_start_ticks"]
                != before_cgroup["process_start_ticks"]
                or cgroup["memory_max_bytes"] != before_cgroup["memory_max_bytes"]
                or cgroup["memory_swap_max_bytes"] != before_cgroup["memory_swap_max_bytes"]
                or cgroup["memory_events_oom"]
                != before_cgroup["memory_events_oom"]
                or cgroup["memory_events_oom_kill"]
                != before_cgroup["memory_events_oom_kill"]
            ):
                raise EvaluationWindowError("incumbent restarted, migrated, or OOMed")
        rows.append(identity)
        cgroups[registered["name"]] = cgroup
    service = _service_observation(ops, transitioning=nara_transition)
    if not nara_transition and service["ActiveState"] not in {"active", "inactive"}:
        raise EvaluationWindowError("Nara service is not in a healthy baseline state")
    if initial is not None and not nara_transition and (
        service["ActiveState"] != initial["nara"]["ActiveState"]
        or (service["ActiveState"] == "active" and service["MainPID"] != initial["nara"]["MainPID"])
    ):
        raise EvaluationWindowError("Nara service changed during the incumbent window")
    return {
        "observed_at": utc_now(),
        "residents": rows,
        "residents_by_name": {row["name"]: row for row in rows},
        "cgroups_by_name": cgroups,
        "nara": service,
    }


class ResidentSafetyMonitor:
    """Only read-only inspections. Never equate incumbent swap to Flash swap."""

    def __init__(self, output: Path, ops: HostOps, initial: dict, *, deadline: float):
        self.output = output
        self.ops = ops
        self.initial = initial
        self.original = initial
        self.deadline = deadline
        self.cancel_event = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.failure: str | None = None
        self.samples = 0
        self.minimum_observed_gib = math.inf
        self._last_sample_mono: float | None = None
        self._last_swap_pages: int | None = None
        self._record_lock = threading.Lock()
        self._sample_lock = threading.Lock()
        self._stream = None
        self.phase = "setup"
        self.sentinel_id: str | None = None

    def bind_sentinel(self, sentinel_id: str) -> None:
        with self._sample_lock:
            if self.phase != "setup" or self.sentinel_id is not None:
                raise EvaluationWindowError("resident watchdog sentinel binding is out of order")
            self.sentinel_id = sentinel_id
            self._sample_unlocked()

    def transition(self, phase: str, *, cohort_initial: dict | None = None) -> None:
        allowed = {
            "setup": {"quiescing", "restoration"},
            "quiescing": {"evaluation", "restoration"},
            "evaluation": {"restoration"},
        }
        with self._sample_lock:
            if phase not in allowed.get(self.phase, set()):
                raise EvaluationWindowError("resident Nara isolation phase is out of order")
            if phase == "evaluation":
                if (
                    not isinstance(cohort_initial, dict)
                    or cohort_initial.get("nara", {}).get("ActiveState") != "inactive"
                    or cohort_initial.get("residents_by_name")
                        != self.original.get("residents_by_name")
                    or any(
                        cohort_initial.get("cgroups_by_name", {}).get(name, {}).get(key)
                        != before.get(key)
                        for name, before in self.original.get("cgroups_by_name", {}).items()
                        for key in (
                            "path", "process_start_ticks", "memory_max_bytes",
                            "memory_swap_max_bytes", "memory_events_oom", "memory_events_oom_kill"
                        )
                    )
                ):
                    raise EvaluationWindowError("quiesced incumbent models/Nara changed")
                self.initial = cohort_initial
            self.phase = phase
            self._sample_unlocked()

    def sample(self) -> dict:
        with self._sample_lock:
            return self._sample_unlocked()

    def _sample_unlocked(self) -> dict:
        now = time.monotonic()
        available = _available_gib()
        host_swap_pages = _pswpout_pages()
        if not math.isfinite(now) or not math.isfinite(available) or available < MIN_MEMORY_GIB:
            raise EvaluationWindowError("incumbent research memory gate breached")
        if now >= self.deadline:
            raise EvaluationWindowError("incumbent evaluation deadline reached")
        if self._last_sample_mono is not None and (now <= self._last_sample_mono or now - self._last_sample_mono > 10):
            raise EvaluationWindowError("incumbent safety monitor has a blind interval")
        if self._last_swap_pages is not None and host_swap_pages < self._last_swap_pages:
            raise EvaluationWindowError("host paging counter decreased")
        observed = _read_exact_residents(
            self.ops, self.initial,
            nara_transition=self.phase in {"quiescing", "restoration"},
        )
        if self.phase == "evaluation" and observed["nara"]["ActiveState"] != "inactive":
            raise EvaluationWindowError("Nara became active during the resident cohort")
        if time.monotonic() - now > 10:
            raise EvaluationWindowError("incumbent identity sampling was blind for over10 seconds")
        self._last_sample_mono = now
        self._last_swap_pages = host_swap_pages
        self.minimum_observed_gib = min(self.minimum_observed_gib, available)
        row = {
            "schema": "flash-next-resident-research-memory-sample/v1",
            "monitor_phase": self.phase,
            "watchdog_sentinel_id": self.sentinel_id,
            "observed_at": utc_now(),
            "observed_monotonic": now,
            "mem_available_gib": available,
            "host_pswpout_pages": host_swap_pages,
            "incumbent_ids": [item["id"] for item in observed["residents"]],
            "incumbent_restart_counts": {
                item["name"]: item["restart_count"] for item in observed["residents"]
            },
            "incumbent_pids": {
                item["name"]: item["pid"] for item in observed["residents"]
            },
            "incumbent_containers": observed["residents"],
            "incumbent_cgroups": observed["cgroups_by_name"],
            "nara": observed["nara"],
            "incumbent_cgroup_swap_bytes": {
                name: cgroup["memory_swap_current_bytes"]
                for name, cgroup in observed["cgroups_by_name"].items()
            },
            "cgroup_swap_capture_status": "exact_incumbent_pid_cgroup_bound",
        }
        with self._record_lock:
            if self._stream is None:
                raise EvaluationWindowError("incumbent evidence stream is not bound")
            self._stream.write(
                json.dumps(row, sort_keys=True, allow_nan=False).encode() + b"\n"
            )
            self._stream.flush()
        self.samples += 1
        return row

    def check(self) -> None:
        if self.failure is not None or self.cancel_event.is_set():
            raise EvaluationWindowError(self.failure or "incumbent monitor canceled")
        if self._last_sample_mono is None or time.monotonic() - self._last_sample_mono > 10:
            raise EvaluationWindowError("incumbent safety monitor is stale")

    def _background(self) -> None:
        while not self._stop.is_set():
            if self._stop.wait(1):
                break
            try:
                self.sample()
            except BaseException as exc:  # noqa: BLE001 - any read uncertainty cancels all cells
                self.failure = f"{type(exc).__name__}: {exc}"
                self.cancel_event.set()
                break

    def __enter__(self):
        fd = os.open(
            self.output,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            os.close(fd)
            raise EvaluationWindowError("incumbent evidence destination is not regular")
        self._stream = os.fdopen(fd, "wb")
        try:
            self.sample()
            self._thread = threading.Thread(target=self._background, daemon=True)
            self._thread.start()
        except BaseException:
            self._stream.close()
            self._stream = None
            raise
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
            if self._thread.is_alive():
                self.failure = self.failure or "resident monitor did not stop"
                self.cancel_event.set()
        if self._stream is not None:
            self._stream.flush()
            os.fsync(self._stream.fileno())
            self._stream.close()


def _resident_plan(window, output: Path) -> dict:
    sentinel_command = _sentinel_command(window.pair_id)
    controller_sources = frozen_controller_source_bundle()
    launcher = REGISTERED_CODE_ROOT / ".venv-chroma/bin/python"
    if not launcher.is_file() or launcher.resolve() != Path("/usr/bin/python3.12"):
        raise EvaluationWindowError("code-owned local resident Python launcher changed")
    return {
        "schema": "flash-next-resident-evaluation-plan/v2",
        "pair_id": window.pair_id,
        "cohort": "resident",
        "output_dir": str(output),
        "window_plan_path": str(window.source_path),
        "window_plan_sha256": window.source_sha256,
        "benchmark_plan_file_sha256": window.benchmark_plan_file_sha256,
        "resident_qualification_receipt_sha256": window.qualification_summary[
            "qualification_receipt_sha256"
        ],
        "effective_invocation_deadline_seconds": WINDOW_DEADLINE_SECONDS,
        "verification_reserve_seconds": RESTORATION_RESERVE_SECONDS,
        "benchmark_runtime_budget_seconds": FULL_COHORT_BUDGET_SECONDS,
        "min_mem_available_gib": MIN_MEMORY_GIB,
        "watchdog_sentinel_name": _sentinel_name(window.pair_id),
        "watchdog_sentinel_create_argv": sentinel_command,
        "watchdog_sentinel_create_argv_sha256": sha256(sentinel_command),
        "nara_service": NARA_SERVICE,
        "nara_isolation": "stop_if_initially_active_then_restore",
        "resident_container_action": "read_and_verify_only",
        "research_usage_journal": str(RESEARCH_LEDGER),
        "launcher_python_path": str(launcher),
        "controller_source_bundle": controller_sources,
        "controller_source_bundle_sha256": sha256(controller_sources),
        "weekly_budget_debit": False,
        "paid_api_allowed": False,
        "production_change_authorized": False,
    }


def _result_restored(output: Path, plan: dict) -> bool:
    try:
        result = _read_bounded_run_json(output / "result.json", source="incumbent window result")
    except Exception:  # noqa: BLE001 - supervisor treats any untrusted result as incomplete
        return False
    return bool(
        result.get("schema") == (
            "flash-followon-resident-result/v1"
            if plan.get("evaluation_kind") == "followon"
            else "flash-next-resident-evaluation-result/v2")
        and result.get("status") in {"complete", "failed"}
        and result.get("pair_id") == plan["pair_id"]
        and result.get("plan_sha256") == sha256(plan)
        and result.get("window_plan_sha256") == plan["window_plan_sha256"]
        and result.get("benchmark_plan_file_sha256") == plan["benchmark_plan_file_sha256"]
        and result.get("resident_qualification_receipt_sha256")
        == plan["resident_qualification_receipt_sha256"]
        and result.get("exact_final_verification") is True
        and isinstance(result.get("restoration"), dict)
        and result.get("restoration", {}).get("status") == "verified"
        and result.get("restoration", {}).get("errors") == []
        and result.get("restoration", {}).get("sentinel_retained") is False
        and result.get("restoration", {}).get("final_observation")
        == result.get("final_observation")
        and isinstance(result.get("final_observation"), dict)
        and result["final_observation"].get("watchdog_sentinel_by_name") is None
        and result["final_observation"].get("watchdog_sentinel_by_id") is None
        and result.get("weekly_budget_debit") is False
        and result.get("paid_api_calls") == 0
        and (plan.get("evaluation_kind") != "followon"
             or result.get("evaluation_kind") == "followon"
             and result.get("qualified_parent_window")
                == plan["qualified_parent_window"]
             and result.get("followon_block_count")
                == len(plan["followon_blocks"]))
    )


def _verified_result(output: Path, plan: dict) -> bool:
    try:
        result = _read_bounded_run_json(output / "result.json", source="incumbent window result")
    except Exception:  # noqa: BLE001 - an unreadable result cannot complete a window
        return False
    run_sha = (result.get("group_attempt_sha256")
               if plan.get("evaluation_kind") == "followon"
               else result.get("harness_run_sha256"))
    minimum = result.get("min_mem_available_gib")
    return bool(
        result.get("status") == "complete"
        and _result_restored(output, plan)
        and isinstance(result.get("memory_samples"), int)
        and result["memory_samples"] > 0
        and type(minimum) in {int, float} and math.isfinite(minimum)
        and minimum >= MIN_MEMORY_GIB
        and isinstance(run_sha, str) and re.fullmatch(r"[0-9a-f]{64}", run_sha)
        and (plan.get("evaluation_kind") != "followon"
             or result.get("group_attempt_status")
                == "blocks_complete_pending_restoration")
    )


def _parent_recovery_state(output: Path, plan: dict) -> dict:
    state = _read_bounded_run_json(output / "state.json", source="resident emergency state")
    initial = state.get("initial")
    if (
        state.get("schema") != (
            "flash-followon-resident-state/v1"
            if plan.get("evaluation_kind") == "followon"
            else "flash-next-resident-evaluation-state/v2")
        or state.get("pair_id") != plan["pair_id"]
        or state.get("plan_sha256") != sha256(plan)
        or state.get("window_plan_sha256") != plan["window_plan_sha256"]
        or state.get("monitor_memory_log_relpath") != "resident-memory.jsonl"
        or state.get("boot_id") != Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        or type(state.get("worker_pid")) is not int or state["worker_pid"] <= 0
        or type(state.get("worker_start_ticks")) is not int
        or state["worker_start_ticks"] <= 0
        or not isinstance(state.get("nara_stop_attempted"), bool)
    ):
        raise EvaluationWindowError("resident recovery state is not bound to the worker")
    if plan.get("evaluation_kind") == "followon" and (
        state.get("evaluation_kind") != "followon"
        or state.get("qualified_parent_window")
           != plan["qualified_parent_window"]
        or state.get("followon_blocks") != plan["followon_blocks"]
    ):
        raise EvaluationWindowError("follow-on resident recovery source changed")
    sentinel = state.get("watchdog_sentinel_id")
    if sentinel is not None and re.fullmatch(r"[0-9a-f]{64}", str(sentinel)) is None:
        raise EvaluationWindowError("resident recovery sentinel ID is untrusted")
    if initial is not None:
        if (
            not isinstance(initial, dict)
            or not isinstance(initial.get("residents"), list)
            or len(initial["residents"]) != len(RESIDENTS)
            or not isinstance(initial.get("residents_by_name"), dict)
            or not isinstance(initial.get("cgroups_by_name"), dict)
            or initial.get("nara", {}).get("ActiveState") not in {"active", "inactive"}
        ):
            raise EvaluationWindowError("resident recovery initial state is incomplete")
        for registered, captured in zip(RESIDENTS, initial["residents"], strict=True):
            if (
                not isinstance(captured, dict)
                or captured.get("id") != registered["id"]
                or captured.get("name") != registered["name"]
                or captured.get("image") != registered["image_id"]
                or captured.get("running") is not True
                or captured.get("oom_killed") is not False
                or captured.get("restart_policy") != "unless-stopped"
                or type(captured.get("pid")) is not int or captured["pid"] <= 0
                or initial["residents_by_name"].get(registered["name"]) != captured
                or initial["cgroups_by_name"].get(registered["name"], {}).get("path")
                != f"/system.slice/docker-{registered['id']}.scope"
            ):
                raise EvaluationWindowError("resident recovery captured model ID is untrusted")
    elif sentinel is not None or state["nara_stop_attempted"]:
        raise EvaluationWindowError("resident state records a mutation without captured models")
    return state


def supervisor_emergency_resident_restore(
    output: Path, plan: dict, *, deadline: float, ops: HostOps | None = None
) -> dict:
    """Recover original Nara activity from a worker's durable exact IDs."""
    ops = ops or HostOps()
    receipt = {
        "schema": ("flash-followon-resident-supervisor-recovery/v1"
                   if plan.get("evaluation_kind") == "followon"
                   else "flash-next-resident-supervisor-recovery/v1"),
        "pair_id": plan["pair_id"], "started_at": utc_now(),
        "status": "unknown", "restoration": None, "error": None,
    }
    try:
        state = _parent_recovery_state(output, plan)
        with resource_lease(canonical_root(ROOT)):
            by_name = _inspect_container(ops, _sentinel_name(plan["pair_id"]))
            if by_name is not None and state["watchdog_sentinel_id"] is None:
                if (
                    state["initial"] is None or by_name.get("image") != IMAGE_ID
                    or by_name.get("running") is not False
                    or not isinstance(by_name.get("id"), str)
                    or re.fullmatch(r"[0-9a-f]{64}", by_name["id"]) is None
                ):
                    raise EvaluationWindowError("uncaptured resident sentinel cannot be recovered")
                # The fixed name was absent at preflight and the exact image
                # is stopped; bind the ID durably before any service action.
                state["watchdog_sentinel_id"] = by_name["id"]
                _atomic_json(output / "state.json", state)
            restoration = restore_resident_window(
                ops, state, plan, deadline=deadline,
            )
        receipt["restoration"] = restoration
        receipt["status"] = restoration["status"]
        state["phase"] = (
            "supervisor_recovered" if restoration["status"] == "verified"
            else "recovery_unknown"
        )
        state["restoration"] = restoration
        _atomic_json(output / "state.json", state)
    except BaseException as exc:  # noqa: BLE001 - emergency uncertainty remains visible
        receipt["error"] = f"{type(exc).__name__}: {exc}"
    receipt["finished_at"] = utc_now()
    _atomic_json(output / "supervisor-recovery.json", receipt)
    _append_usage({
        "schema": "local-model-research-usage/v1",
        "event": "resident_supervisor_recovery",
        "pair_id": plan["pair_id"], "observed_at": utc_now(),
        "plan_sha256": sha256(plan), "restoration_status": receipt["status"],
        "weekly_budget_debit": False, "paid_api_calls": 0,
    })
    return receipt


def _worker(window, plan: dict, output: Path) -> int:
    followon_kind = plan.get("evaluation_kind") == "followon"
    if followon_kind:
        from .followon_dispatch import FOLLOWON_CODE_ROOT
        expected_root = FOLLOWON_CODE_ROOT
    else:
        expected_root = REGISTERED_CODE_ROOT
    if ROOT != expected_root:
        raise EvaluationWindowError("resident worker was imported outside the registered worktree")
    hard_deadline = time.monotonic() + plan["effective_invocation_deadline_seconds"]
    cutoff = hard_deadline - plan["verification_reserve_seconds"]
    started_wall = datetime.now(timezone.utc)
    state = {
        "schema": ("flash-followon-resident-state/v1" if followon_kind
                   else "flash-next-resident-evaluation-state/v2"),
        "pair_id": window.pair_id,
        "phase": "preflight",
        "plan_sha256": sha256(plan),
        "window_plan_sha256": window.source_sha256,
        "started_at": started_wall.isoformat(),
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "worker_pid": os.getpid(),
        "worker_start_ticks": _self_start_ticks(),
        "invocation_deadline_at": (
            started_wall + timedelta(seconds=plan["effective_invocation_deadline_seconds"])
        ).isoformat(),
        "initial": None,
        "quiet_observation": None,
        "watchdog_sentinel_id": None,
        "nara_stop_attempted": False,
        "restoration": {"status": "not_started"},
        "monitor_memory_log_relpath": "resident-memory.jsonl",
    }
    if followon_kind:
        state["evaluation_kind"] = "followon"
        state["qualified_parent_window"] = plan["qualified_parent_window"]
        state["followon_blocks"] = plan["followon_blocks"]
    _atomic_json(output / "state.json", state)
    _append_usage({
        "schema": "local-model-research-usage/v1",
        "event": "resident_evaluation_started",
        "pair_id": window.pair_id,
        "observed_at": utc_now(),
        "plan_sha256": sha256(plan),
        "weekly_budget_debit": False,
        "paid_api_calls": 0,
    })
    initial = None
    error = None
    failure_stage = None
    run_sha = None
    restoration: dict = {
        "status": "verified", "verified_at": utc_now(), "errors": [],
        "sentinel_retained": False, "no_mutation_verified": True,
        "final_observation": None, "original_nara_activity": None,
    }
    final_observation = None
    samples = 0
    minimum = None
    nara_stopped_mono = None
    nara_restored_mono = None
    with resource_lease(canonical_root(ROOT)):
        ops = HostOps()
        try:
            initial = _read_exact_residents(ops)
            if _available_gib() < MIN_MEMORY_GIB:
                raise EvaluationWindowError("incumbent preflight memory below20GiB")
            state["initial"] = initial
            state["phase"] = "sentinel_create"
            _atomic_json(output / "state.json", state)
            monitor = ResidentSafetyMonitor(
                output / "resident-memory.jsonl", ops, initial, deadline=hard_deadline
            )
            with monitor:
                try:
                    sentinel_id = _create_sentinel(ops, window.pair_id)
                    state["watchdog_sentinel_id"] = sentinel_id
                    _atomic_json(output / "state.json", state)
                    monitor.bind_sentinel(sentinel_id)
                    _verify_sentinel(ops, window.pair_id, sentinel_id)
                    state["phase"] = "nara_quiescing"
                    _atomic_json(output / "state.json", state)
                    monitor.transition("quiescing")
                    if initial["nara"]["ActiveState"] == "active":
                        state["nara_stop_attempted"] = True
                        _atomic_json(output / "state.json", state)
                        ops.run(
                            ["systemctl", "--user", "stop", NARA_SERVICE],
                            timeout=_remaining_timeout(cutoff, 30),
                        )
                        nara_stopped_mono = time.monotonic()
                    quiet = _read_exact_residents(
                        ops, initial, nara_transition=True
                    )
                    if quiet["nara"]["ActiveState"] != "inactive":
                        raise EvaluationWindowError("Nara was not quiescent before any resident call")
                    state["quiet_observation"] = quiet
                    _atomic_json(output / "state.json", state)
                    monitor.transition("evaluation", cohort_initial=quiet)
                    monitor.check()
                    _verify_sentinel(ops, window.pair_id, sentinel_id)
                    if cutoff - time.monotonic() < window.runtime_budget_seconds + 60:
                        raise EvaluationWindowError("full cohort exceeds the restoration cutoff")
                    state["phase"] = "evaluation"
                    _atomic_json(output / "state.json", state)
                    if followon_kind:
                        from .followon_admission import resident_callbacks
                        from .followon_dispatch import run_group

                        callbacks = resident_callbacks(
                            window, state, monitor, ops, cutoff=cutoff
                        )
                        run = run_group(
                            window.frozen, controller_callbacks=callbacks,
                            work_cutoff_s=cutoff,
                            cancel_event=monitor.cancel_event,
                        )
                    else:
                        run = run_harness(
                            window.benchmark_plan, cohort="resident",
                            output_dir=output / "harness",
                            runtime_budget_s=window.runtime_budget_seconds,
                            qualification_gate=_qualification_gate(window),
                            cancel_event=monitor.cancel_event,
                            run_id=f"{window.pair_id}-resident",
                        )
                        validate_run(run, "resident")
                    monitor.check()
                    expected_run_status = (
                        "blocks_complete_pending_restoration" if followon_kind
                        else "complete"
                    )
                    if run.get("status") != expected_run_status:
                        raise EvaluationWindowError(
                            "registered resident block group did not finish before restoration"
                        )
                    raw, observed_path = _read_regular_file(
                        (output / "group-attempt.json" if followon_kind
                         else output / "harness" / "run.json"),
                        label="incumbent run", max_bytes=8_000_000,
                    )
                    expected_run_path = (output / "group-attempt.json" if followon_kind
                                         else output / "harness" / "run.json")
                    if observed_path != expected_run_path.absolute():
                        raise EvaluationWindowError("incumbent harness run was redirected")
                    run_sha = hashlib.sha256(raw).hexdigest()
                except BaseException as exc:  # noqa: BLE001 - restoration must run for every mutation
                    error = f"{type(exc).__name__}: {exc}"
                    failure_stage = state["phase"]
                finally:
                    state["phase"] = "restoration"
                    _atomic_json(output / "state.json", state)
                    try:
                        if monitor.phase != "restoration":
                            monitor.transition("restoration")
                    except BaseException as exc:  # noqa: BLE001 - restore even without monitor
                        error = error or f"monitor restoration transition: {type(exc).__name__}: {exc}"
                        failure_stage = failure_stage or "restoration"
                    restoration = restore_resident_window(
                        ops, state, plan, deadline=hard_deadline,
                        monitor=monitor if monitor.phase == "restoration" else None,
                    )
                    state["restoration"] = restoration
                    _atomic_json(output / "state.json", state)
                    final_observation = restoration["final_observation"]
                    samples = monitor.samples
                    minimum = (
                        monitor.minimum_observed_gib
                        if math.isfinite(monitor.minimum_observed_gib) else None
                    )
            # A stuck background sampler cannot certify a finished window.
            if monitor.failure is not None:
                error = error or f"resident safety monitor: {monitor.failure}"
                failure_stage = failure_stage or "restoration"
            if _available_gib() < MIN_MEMORY_GIB or time.monotonic() >= hard_deadline:
                error = error or "final 20 GiB reserve or absolute deadline breached"
                failure_stage = failure_stage or "restoration"
            if nara_stopped_mono is not None and restoration["status"] == "verified":
                nara_restored_mono = time.monotonic()
        except BaseException as exc:  # noqa: BLE001 - never assume service restoration on failure
            error = f"{type(exc).__name__}: {exc}"
            failure_stage = failure_stage or state["phase"]
            # A failure before entering the monitor can still leave the
            # stopped watchdog sentinel or Nara state mutated. Inspect both.
            try:
                if restoration["status"] != "verified" or (
                    initial is not None and state.get("watchdog_sentinel_id") is not None
                    and restoration["no_mutation_verified"] is True
                ):
                    restoration = restore_resident_window(
                        ops, state, plan, deadline=hard_deadline
                    )
                final_observation = restoration.get("final_observation")
                state["restoration"] = restoration
                _atomic_json(output / "state.json", state)
            except BaseException as restore_exc:  # noqa: BLE001 - preserve unknown
                restoration = {
                    "status": "unknown", "verified_at": None,
                    "errors": [f"emergency service restore: {type(restore_exc).__name__}: {restore_exc}"],
                    "sentinel_retained": True, "final_observation": None,
                    "no_mutation_verified": False,
                }

    status = (
        "complete" if error is None and restoration["status"] == "verified"
        and run_sha is not None and minimum is not None
        else "failed" if restoration["status"] == "verified" else "unknown"
    )
    state["phase"] = (
        "complete" if status == "complete" else "failed"
        if restoration["status"] == "verified" else "recovery_unknown"
    )
    state["result_status"] = status
    state["restoration"] = restoration
    state["final_observation"] = final_observation
    _atomic_json(output / "state.json", state)
    nara_downtime_seconds = (
        max(
            0.0,
            (nara_restored_mono if nara_restored_mono is not None else time.monotonic())
            - nara_stopped_mono,
        )
        if nara_stopped_mono is not None else 0.0
    )
    result = {
        "schema": ("flash-followon-resident-result/v1" if followon_kind
                   else "flash-next-resident-evaluation-result/v2"),
        "pair_id": window.pair_id,
        "status": status,
        "plan_sha256": sha256(plan),
        "window_plan_sha256": window.source_sha256,
        "benchmark_plan_file_sha256": window.benchmark_plan_file_sha256,
        "resident_qualification_receipt_sha256": plan["resident_qualification_receipt_sha256"],
        "exact_final_verification": restoration["status"] == "verified",
        "initial_observation": initial,
        "quiet_observation": state["quiet_observation"],
        "final_observation": final_observation,
        "watchdog_sentinel_id": state["watchdog_sentinel_id"],
        "restoration": restoration,
        "nara_downtime_seconds": nara_downtime_seconds,
        "nara_downtime_seconds_basis": (
            "stop_confirmation_to_verified_original_activity"
            if nara_restored_mono is not None
            else "stop_confirmation_to_attempt_completion_upper_bound"
            if nara_stopped_mono is not None else "original_service_inactive_or_untouched"
        ),
        "memory_samples": samples,
        "min_mem_available_gib": minimum,
        "host_swap_action": "diagnostic_only",
        "candidate_cgroup_zero_swap_action": "not_applicable_to_incumbents",
        "error": error if error is not None else (
            "; ".join(restoration.get("errors", []))
            if restoration["status"] != "verified" else None
        ),
        "failure_stage": failure_stage if status != "complete" else None,
        "weekly_budget_debit": False,
        "paid_api_calls": 0,
        "production_change_authorized": False,
    }
    if followon_kind:
        result.update(
            evaluation_kind="followon",
            qualified_parent_window=plan["qualified_parent_window"],
            group_attempt_status=("blocks_complete_pending_restoration"
                                  if status == "complete" else None),
            group_attempt_sha256=run_sha,
            followon_block_count=len(plan["followon_blocks"]),
            followon_block_budget_total_seconds=plan[
                "followon_block_budget_total_seconds"],
        )
    else:
        result["harness_run_sha256"] = run_sha
    memory_file = output / "resident-memory.jsonl"
    if memory_file.exists():
        raw, observed_path = _read_regular_file(
            memory_file, label="incumbent raw memory log", max_bytes=64 * 1024 * 1024
        )
        if observed_path != memory_file.absolute():
            raise EvaluationWindowError("incumbent raw safety log path changed")
        result["memory_log_sha256"] = hashlib.sha256(raw).hexdigest()
    else:
        result["memory_log_sha256"] = None
    _append_usage({
        "schema": "local-model-research-usage/v1",
        "event": "resident_evaluation_finished",
        "pair_id": window.pair_id,
        "observed_at": utc_now(),
        "status": status,
        "plan_sha256": sha256(plan),
        "weekly_budget_debit": False,
        "paid_api_calls": 0,
    })
    result["finished_at"] = utc_now()
    _atomic_json(output / "result.json", result)
    return 0 if status == "complete" else 1


def _supervise(window, plan, output) -> int:
    if plan.get("evaluation_kind") == "followon":
        from .followon_dispatch import FOLLOWON_CODE_ROOT
        expected_root = FOLLOWON_CODE_ROOT
    else:
        expected_root = REGISTERED_CODE_ROOT
    if ROOT != expected_root:
        raise EvaluationWindowError("resident supervisor was imported outside the registered worktree")
    output.mkdir(mode=0o700)
    _atomic_json(output / "plan.json", plan)
    command = [
        plan["launcher_python_path"], "-m", "bench.flash_next_ab.resident_evaluation_window",
        "--worker", "--eval-plan", str(window.source_path), "--output-dir", str(output),
    ]
    env = dict(os.environ)
    for key in ("MOCK_LLM", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "VLLM_API_KEY"):
        env.pop(key, None)
    started_wall = datetime.now(timezone.utc)
    started = time.monotonic()
    hard_deadline = started + WINDOW_DEADLINE_SECONDS
    work_cutoff = hard_deadline - RESTORATION_RESERVE_SECONDS
    killed = False
    terminated = False
    with (output / "controller.log").open("xb") as stream:
        proc = subprocess.Popen(
            command, cwd=ROOT, env=env, stdout=stream,
            stderr=subprocess.STDOUT, start_new_session=True,
        )
        try:
            worker_start_ticks = _process_start_ticks(proc.pid)
        except (OSError, QualificationError):
            worker_start_ticks = None
        while proc.poll() is None and time.monotonic() < work_cutoff:
            time.sleep(min(1, max(0, work_cutoff - time.monotonic())))
        if proc.poll() is None:
            terminated = True
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        force_cutoff = min(work_cutoff + 90, hard_deadline - 500)
        while proc.poll() is None and time.monotonic() < force_cutoff:
            time.sleep(min(1, max(0, force_cutoff - time.monotonic())))
        if proc.poll() is None:
            killed = True
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            proc.wait(timeout=min(5, max(0.1, hard_deadline - time.monotonic())))
        except subprocess.TimeoutExpired:
            killed = True
            try:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=5)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                pass
    recovery = None
    if not _result_restored(output, plan):
        if proc.poll() is None:
            recovery = {
                "schema": ("flash-followon-resident-supervisor-recovery/v1"
                           if plan.get("evaluation_kind") == "followon"
                           else "flash-next-resident-supervisor-recovery/v1"),
                "status": "unknown", "error": "worker termination is not verified",
                "restoration": None,
            }
            _atomic_json(output / "supervisor-recovery.json", recovery)
        else:
            recovery = supervisor_emergency_resident_restore(
                output, plan, deadline=hard_deadline
            )
    elapsed = max(0, time.monotonic() - started)
    complete = (
        _verified_result(output, plan) and not killed and not terminated
        and recovery is None and proc.returncode == 0
        and worker_start_ticks is not None and elapsed <= WINDOW_DEADLINE_SECONDS
    )
    _atomic_json(output / "supervision.json", {
        "schema": ("flash-followon-resident-supervision/v1"
                   if plan.get("evaluation_kind") == "followon"
                   else "flash-next-resident-supervision/v1"),
        "pair_id": window.pair_id,
        "plan_sha256": sha256(plan),
        "command_sha256": sha256(command),
        "argv": command,
        "pid": proc.pid,
        "worker_start_ticks": worker_start_ticks,
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "started_at": started_wall.isoformat(),
        "hard_deadline_at": (
            started_wall + timedelta(seconds=WINDOW_DEADLINE_SECONDS)
        ).isoformat(),
        "returncode": proc.returncode,
        "complete": complete,
        "terminated_at_work_cutoff": terminated,
        "force_killed": killed,
        "emergency_recovery": recovery,
        "elapsed_seconds": elapsed,
        "finished_at": utc_now(),
    })
    return 0 if complete else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--plan", action="store_true")
    modes.add_argument("--run", action="store_true")
    modes.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--eval-plan", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    from .followon_selection import select_window

    selected = select_window(args.eval_plan, cohort="resident")
    if selected.kind == "followon":
        from .followon_plans import load_execution, resident_plan

        window = load_execution(args.eval_plan, cohort="resident")
        output = Path(os.path.abspath(args.output_dir))
        plan = resident_plan(window, output, must_be_absent=args.run)
    else:
        window = load_evaluation_window(args.eval_plan, expected_cohort="resident")
        output = _registered_output(window.pair_id, args.output_dir, absent=args.run)
        plan = _resident_plan(window, output)
    if args.plan:
        print(json.dumps(plan, sort_keys=True, indent=2, allow_nan=False))
        return 0
    if args.run:
        return _supervise(window, plan, output)
    if not output.is_dir() or output.is_symlink():
        raise EvaluationWindowError("resident supervisor output is absent or redirected")
    raw, observed = _read_regular_file(output / "plan.json", label="resident supervisor plan", max_bytes=2_000_000)
    if observed != (output / "plan.json").absolute() or json.loads(raw) != plan:
        raise EvaluationWindowError("resident worker plan differs from frozen supervisor")
    return _worker(window, plan, output)


if __name__ == "__main__":
    raise SystemExit(main())
