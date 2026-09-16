"""Read-only projection of an active stable-benchmark resident window.

The benchmark supervisor intentionally pauses Nara while it evaluates the
already-running resident models.  This reader admits that operational state
only from a preregistered lifecycle plan, its frozen source tree, an exact live
worker identity, and a fresh resident-monitor row.  Broken or stale evidence
returns an explicit unknown state and therefore cannot reveal an older,
reassuring runtime projection.  Verified terminal restoration returns ``None``
so the ordinary resident projection can resume.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from bench.stable_benchmark import receipt_verification as rv

from . import model_runtime as mr

REGISTRATION_ROOT_RELATIVE = Path("docs/benchmarks/registrations")
WINDOW_ROOT = Path(
    "/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-16/stable-benchmark/windows"
)
FROZEN_WORKTREE_ROOT = Path("/home/decross1/projects/a_bgt_rsi_worktrees")

MAX_REGISTRATIONS = 32
MAX_WINDOW_BYTES = 2 * 1024 * 1024
MAX_STATE_BYTES = 4 * 1024 * 1024
MAX_RESULT_BYTES = 8 * 1024 * 1024
MAX_SOURCE_BYTES = 16 * 1024 * 1024
MAX_MEMORY_BYTES = 64 * 1024 * 1024
MAX_MEMORY_TAIL_BYTES = 64 * 1024
MAX_MEMORY_AGE = timedelta(seconds=12)
MAX_CLOCK_SKEW = timedelta(seconds=5)
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
GIT_SHA = re.compile(r"[0-9a-f]{40}\Z")

ACTIVE_PHASES = frozenset(
    {
        "preflight",
        "sentinel_created",
        "nara_quiescing",
        "evaluation",
        "restoration",
    }
)
TERMINAL_PHASES = frozenset(
    {
        "complete",
        "failed",
        "supervisor_recovered",
        "recovery_unknown",
    }
)
MONITOR_PHASE = {
    "preflight": "setup",
    "sentinel_created": "setup",
    "nara_quiescing": "quiescing",
    "evaluation": "evaluation",
    "restoration": "restoration",
}
STATE_FIELDS = {
    "schema_version",
    "window_id",
    "pair_id",
    "phase",
    "plan_sha256",
    "definition_sha256",
    "run_manifest_sha256",
    "boot_id",
    "worker_pid",
    "worker_start_ticks",
    "started_at",
    "initial",
    "quiet_observation",
    "watchdog_sentinel_id",
    "nara_stop_attempted",
    "execution_gate_sha256",
    "restoration",
}
RECOVERY_SCHEMA = "stable-benchmark-supervisor-recovery/v1"
RECOVERY_FIELDS = {
    "schema_version",
    "window_id",
    "started_at",
    "status",
    "restoration",
    "error",
    "finished_at",
}
EXPECTED_RESIDENT_IDS = {
    "vllm-gemma4": "fc61a80d6c2d07b551c5afdd566a7c82ee05ad40c014d69c428e299e49101374",
    "vllm-qwen": "bcb6cd87757279ff77f1460cab2f8ad6cf1a2e46d19dad165b07dccecfa509bb",
}
STABLE_CGROUP_FIELDS = (
    "path",
    "process_start_ticks",
    "memory_max_bytes",
    "memory_swap_max_bytes",
    "memory_events_oom",
    "memory_events_oom_kill",
)


class StableRuntimeError(ValueError):
    """The latest registered stable lifecycle cannot be trusted."""


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise StableRuntimeError(reason)


def _unknown(
    observed: datetime,
    reason: str,
    *,
    comparison_id: str | None = None,
    run_id: str | None = None,
    phase: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": mr.SCHEMA_VERSION,
        "observed_at": observed.astimezone(timezone.utc).isoformat(),
        "mode": "unknown",
        "mode_source": "stable_benchmark_state",
        "mode_source_sha256": None,
        "resident_services_expected": "unknown",
        "nara_service_expected": "unknown",
        "comparison_id": comparison_id,
        "run_id": run_id,
        "phase": phase,
        "candidate_variant": None,
        "source_error": reason,
    }


def _read_document(
    path: Path, *, maximum: int, label: str
) -> tuple[dict[str, Any], bytes, str]:
    try:
        absolute = path.absolute()
        _require(absolute.resolve(strict=True) == absolute, f"{label} is redirected")
        raw = mr._read_path(absolute, maximum=maximum, label=label)
    except (OSError, mr.RuntimeSourceError) as exc:
        raise StableRuntimeError(f"{label} is unavailable") from exc
    value = mr._strict_object(raw, label)
    return value, raw, hashlib.sha256(raw).hexdigest()


def _read_hash(path: Path, *, maximum: int, label: str) -> str:
    try:
        absolute = path.absolute()
        _require(absolute.resolve(strict=True) == absolute, f"{label} is redirected")
        raw = mr._read_path(absolute, maximum=maximum, label=label)
    except (OSError, mr.RuntimeSourceError) as exc:
        raise StableRuntimeError(f"{label} is unavailable") from exc
    return hashlib.sha256(raw).hexdigest()


def _registration_files(repo: Path) -> list[Path]:
    root = repo.absolute() / REGISTRATION_ROOT_RELATIVE
    try:
        root_fd = os.open(root, mr._flags(directory=True))
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise StableRuntimeError("stable registration root is unavailable") from exc
    try:
        names: list[str] = []
        with os.scandir(root_fd) as entries:
            for entry in entries:
                names.append(entry.name)
                if len(names) > MAX_REGISTRATIONS:
                    raise StableRuntimeError(
                        "stable registration root exceeds its scan bound"
                    )
        paths = []
        for name in sorted(names):
            if not name.endswith(".json"):
                continue
            stem = name.removesuffix(".json")
            _require(
                rv.SAFE_ID.fullmatch(stem) is not None,
                "registration filename is unsafe",
            )
            paths.append(root / name)
        return paths
    finally:
        os.close(root_fd)


def _program_layout(
    registration: rv.LoadedRegistration,
    program_root: Path,
) -> dict[str, Any]:
    document = registration.document
    comparison_id = document["comparison_id"]
    _require(
        registration.path.name == f"{comparison_id}.json",
        "registration filename differs from its comparison ID",
    )
    _require(
        document["definition"]["path"]
        == str(program_root / "definition.published.json"),
        "registration definition is outside the stable program root",
    )
    reference = document["arms"][0]
    candidate = document["arms"][1]
    for arm in document["arms"]:
        arm_id = arm["arm_id"]
        _require(
            arm["manifest"]["path"]
            == str(program_root / "manifests" / f"{comparison_id}.{arm_id}.json"),
            "registered manifest is outside the stable program root",
        )
        _require(
            arm["run_receipt_directory"]
            == str(program_root / "runs" / comparison_id / arm_id),
            "registered run directory is outside the stable program root",
        )
    _require(reference["role"] == "reference", "stable reference arm is absent")
    lifecycle = reference.get("lifecycle")
    _require(isinstance(lifecycle, dict), "stable reference lifecycle is absent")
    _require(
        candidate["role"] == "candidate" and candidate.get("lifecycle") is None,
        "stable candidate is not preregistered as unissued",
    )
    return reference


def _attempt_exists(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise StableRuntimeError(
            "registered lifecycle directory is unavailable"
        ) from exc
    # The supervisor creates this exact directory only when it begins an
    # attempt. Its metadata time is deliberately irrelevant: touching an old
    # artifact cannot outrank a newer source-controlled registration.
    return True


def _select_attempt(
    repo: Path, program_root: Path
) -> tuple[rv.LoadedRegistration, dict[str, Any], Path] | None:
    attempted: list[
        tuple[
            datetime,
            str,
            str,
            rv.LoadedRegistration,
            dict[str, Any],
            Path,
        ]
    ] = []
    for path in _registration_files(repo):
        try:
            registration = rv.load_registration(path)
        except rv.ReceiptVerificationError as exc:
            raise StableRuntimeError("stable registration is invalid") from exc
        reference = _program_layout(registration, program_root)
        lifecycle = reference["lifecycle"]
        receipt_dir = Path(lifecycle["receipt_directory"])
        _require(
            receipt_dir == WINDOW_ROOT / lifecycle["window_id"],
            "registered lifecycle directory is outside the fixed stable root",
        )
        if _attempt_exists(receipt_dir):
            registered_at = datetime.fromisoformat(
                registration.document["registered_at"][:-1] + "+00:00"
            )
            attempted.append(
                (
                    registered_at,
                    registration.document["comparison_id"],
                    lifecycle["window_id"],
                    registration,
                    reference,
                    receipt_dir,
                )
            )
    if not attempted:
        return None
    attempted.sort(key=lambda item: item[:3], reverse=True)
    _, _, _, registration, reference, receipt_dir = attempted[0]
    return registration, reference, receipt_dir


def _source_tree(
    repo: Path,
    plan: dict[str, Any],
    lifecycle: dict[str, Any],
) -> Path:
    source_map = lifecycle["controller_source_sha256"]
    _require(
        plan.get("controller_source_sha256") == source_map,
        "window controller sources differ from preregistration",
    )
    expected_bundle = hashlib.sha256(
        json.dumps(
            source_map, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()
    _require(
        plan.get("controller_source_bundle_sha256") == expected_bundle,
        "window controller source bundle differs",
    )
    code_root = Path(str(plan.get("code_root", "")))
    _require(
        code_root.is_absolute()
        and code_root.parent == FROZEN_WORKTREE_ROOT
        and code_root != repo.absolute(),
        "stable source root is not an allowed frozen worktree",
    )
    try:
        _require(
            code_root.resolve(strict=True) == code_root and code_root.is_dir(),
            "stable source root is absent or redirected",
        )
    except OSError as exc:
        raise StableRuntimeError("stable source root is unavailable") from exc
    for relative, expected in source_map.items():
        pure = PurePosixPath(relative)
        _require(
            not pure.is_absolute() and ".." not in pure.parts and str(pure) == relative,
            "stable source path is unsafe",
        )
        observed = _read_hash(
            code_root / relative,
            maximum=MAX_SOURCE_BYTES,
            label=f"frozen stable source {relative}",
        )
        _require(observed == expected, f"frozen stable source differs: {relative}")
    return code_root


def _validate_window(
    registration: rv.LoadedRegistration,
    reference: dict[str, Any],
    receipt_dir: Path,
    program_root: Path,
    repo: Path,
) -> tuple[dict[str, Any], bytes, str, Path, list[str]]:
    lifecycle = reference["lifecycle"]
    plan, raw, digest = _read_document(
        receipt_dir / "window.json",
        maximum=MAX_WINDOW_BYTES,
        label="stable window plan",
    )
    _require(set(plan) == rv.WINDOW_FIELDS, "stable window fields differ")
    _require(
        plan.get("schema_version") == rv.WINDOW_SCHEMA
        and digest == lifecycle["window_plan_sha256"],
        "stable window schema or preregistered digest differs",
    )
    definition = registration.document["definition"]
    expected = {
        "window_id": lifecycle["window_id"],
        "pair_id": f"qfn-ab-{lifecycle['window_id']}",
        "execution_mode": "resident_only",
        "window_dir": str(receipt_dir),
        "run_dir": reference["run_receipt_directory"],
        "definition_path": definition["path"],
        "definition_sha256": definition["sha256"],
        "run_manifest_path": reference["manifest"]["path"],
        "run_manifest_sha256": reference["manifest"]["sha256"],
        "arm_id": reference["arm_id"],
        "comparison_id": registration.document["comparison_id"],
        "window_deadline_seconds": 3600,
        "restoration_reserve_seconds": 600,
        "runner_deadline_seconds": 1800,
        "preflight_min_mem_available_gib": 30,
        "monitor_min_mem_available_gib": 20,
        "monitor_max_sample_gap_seconds": 10,
        "nara_service": "nara-daemon.service",
        "nara_isolation": "stop_if_initially_active_then_restore",
        "resident_container_action": "read_and_verify_only",
        "paid_api_allowed": False,
        "production_change_authorized": False,
        "candidate_startup_supported": False,
    }
    _require(
        all(plan.get(key) == value for key, value in expected.items()),
        "stable window differs from preregistration or fixed lifecycle policy",
    )
    _require(
        GIT_SHA.fullmatch(str(plan.get("git_head", ""))) is not None,
        "git head is invalid",
    )
    _require(
        _read_hash(
            Path(definition["path"]),
            maximum=MAX_RESULT_BYTES,
            label="stable definition",
        )
        == definition["sha256"],
        "stable definition bytes differ from preregistration",
    )
    _require(
        _read_hash(
            Path(reference["manifest"]["path"]),
            maximum=MAX_RESULT_BYTES,
            label="stable run manifest",
        )
        == reference["manifest"]["sha256"],
        "stable run manifest bytes differ from preregistration",
    )
    code_root = _source_tree(repo, plan, lifecycle)
    launcher = str(code_root / ".venv-chroma/bin/python")
    _require(
        plan.get("launcher_python_path") == launcher, "stable launcher path differs"
    )
    argv = [
        launcher,
        "-m",
        "bench.stable_benchmark.supervised_window",
        "--worker",
        "--window-id",
        lifecycle["window_id"],
        "--run-manifest",
        reference["manifest"]["path"],
    ]
    argv_sha = hashlib.sha256(
        json.dumps(
            argv, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()
    _require(
        lifecycle.get("worker_argv_sha256") == argv_sha,
        "stable worker argv differs from preregistration",
    )
    return plan, raw, digest, code_root, argv


def _validate_initial(state: dict[str, Any]) -> dict[str, Any]:
    initial = state.get("initial")
    _require(isinstance(initial, dict), "stable initial observation is absent")
    residents = initial.get("residents")
    _require(
        isinstance(residents, list) and len(residents) == len(EXPECTED_RESIDENT_IDS),
        "stable resident set is incomplete",
    )
    by_name = initial.get("residents_by_name")
    cgroups = initial.get("cgroups_by_name")
    _require(
        isinstance(by_name, dict)
        and isinstance(cgroups, dict)
        and set(by_name) == set(EXPECTED_RESIDENT_IDS)
        and set(cgroups) == set(EXPECTED_RESIDENT_IDS),
        "stable resident identity maps are incomplete",
    )
    for row in residents:
        name = row.get("name") if isinstance(row, dict) else None
        _require(
            name in EXPECTED_RESIDENT_IDS
            and row.get("id") == EXPECTED_RESIDENT_IDS[name]
            and row.get("running") is True
            and row.get("oom_killed") is False
            and row.get("state_error") == ""
            and row.get("restart_policy") == "unless-stopped"
            and type(row.get("restart_count")) is int
            and row["restart_count"] >= 0
            and type(row.get("pid")) is int
            and row["pid"] > 0
            and isinstance(row.get("image"), str)
            and bool(row["image"])
            and isinstance(row.get("started_at"), str)
            and by_name.get(name) == row,
            "stable resident identity differs",
        )
        cgroup = cgroups[name]
        _require(
            isinstance(cgroup, dict)
            and cgroup.get("path")
            == f"/system.slice/docker-{EXPECTED_RESIDENT_IDS[name]}.scope"
            and type(cgroup.get("process_start_ticks")) is int
            and cgroup["process_start_ticks"] > 0
            and type(cgroup.get("memory_events_oom")) is int
            and cgroup["memory_events_oom"] >= 0
            and type(cgroup.get("memory_events_oom_kill")) is int
            and cgroup["memory_events_oom_kill"] >= 0
            and (
                cgroup.get("memory_max_bytes") == "max"
                or type(cgroup.get("memory_max_bytes")) is int
            )
            and (
                cgroup.get("memory_swap_max_bytes") == "max"
                or type(cgroup.get("memory_swap_max_bytes")) is int
            ),
            "stable resident cgroup identity differs",
        )
    nara = initial.get("nara")
    _require(
        isinstance(nara, dict)
        and nara.get("ActiveState") in {"active", "inactive"}
        and isinstance(nara.get("SubState"), str)
        and isinstance(nara.get("MainPID"), str)
        and nara["MainPID"].isdigit(),
        "stable initial Nara activity is unavailable",
    )
    return initial


def _parse_process_stat(path: Path) -> tuple[int, str]:
    raw = mr._read_path(path, maximum=mr.MAX_PROC_BYTES, label="stable worker stat")
    try:
        text = raw.decode("utf-8")
        closing = text.rfind(")")
        fields = text[closing + 1 :].split()
        state = fields[0]
        ticks = int(fields[19])
    except (UnicodeError, ValueError, IndexError) as exc:
        raise StableRuntimeError("stable worker stat is malformed") from exc
    _require(closing >= 0 and state not in {"Z", "X", "x"}, "stable worker is not live")
    return ticks, state


def _validate_live_process(
    state: dict[str, Any],
    process_receipt: dict[str, Any],
    *,
    code_root: Path,
    argv: list[str],
    proc_root: Path,
    boot_id_path: Path,
) -> None:
    pid = mr._nonnegative_integer(
        state.get("worker_pid"), "stable worker PID", positive=True
    )
    ticks = mr._nonnegative_integer(
        state.get("worker_start_ticks"), "stable worker start ticks", positive=True
    )
    _require(
        process_receipt.get("pid") == pid
        and process_receipt.get("worker_start_ticks") == ticks,
        "stable process receipt differs from state",
    )
    boot = (
        mr._read_path(boot_id_path, maximum=256, label="current boot identity")
        .decode("ascii")
        .strip()
    )
    _require(
        state.get("boot_id") == process_receipt.get("boot_id") == boot,
        "stable worker belongs to another boot",
    )
    process = proc_root / str(pid)
    observed_ticks, _ = _parse_process_stat(process / "stat")
    _require(observed_ticks == ticks, "stable worker process identity differs")
    raw_command = mr._read_path(
        process / "cmdline", maximum=mr.MAX_PROC_BYTES, label="stable worker cmdline"
    )
    try:
        command = [
            part.decode("utf-8") for part in raw_command.rstrip(b"\0").split(b"\0")
        ]
    except UnicodeError as exc:
        raise StableRuntimeError("stable worker cmdline is malformed") from exc
    _require(command == argv, "stable worker invocation differs from registration")
    expected_argv_sha = hashlib.sha256(
        json.dumps(
            argv, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()
    _require(
        process_receipt.get("argv_sha256") == expected_argv_sha,
        "stable process argv receipt differs",
    )
    cwd = process / "cwd"
    try:
        details = cwd.lstat()
        _require(
            stat.S_ISLNK(details.st_mode), "stable worker cwd is not a proc symlink"
        )
        observed_cwd = cwd.resolve(strict=True)
    except OSError as exc:
        raise StableRuntimeError("stable worker cwd is unavailable") from exc
    _require(
        observed_cwd == code_root, "stable worker runs outside the frozen worktree"
    )
    final_ticks, _ = _parse_process_stat(process / "stat")
    _require(final_ticks == ticks, "stable worker changed during validation")


def _last_memory(
    path: Path,
    *,
    observed: datetime,
    state: dict[str, Any],
    plan: dict[str, Any],
    initial: dict[str, Any],
) -> tuple[dict[str, Any], bytes]:
    try:
        descriptor = os.open(path, mr._flags())
    except OSError as exc:
        raise StableRuntimeError("stable resident monitor log is unavailable") from exc
    try:
        before = os.fstat(descriptor)
        _require(
            stat.S_ISREG(before.st_mode) and 0 < before.st_size <= MAX_MEMORY_BYTES,
            "stable resident monitor log exceeds its bound",
        )
        start = max(0, before.st_size - MAX_MEMORY_TAIL_BYTES)
        raw = os.pread(descriptor, before.st_size - start, start)
        after = os.fstat(descriptor)
        _require(
            (before.st_dev, before.st_ino) == (after.st_dev, after.st_ino)
            and len(raw) == before.st_size - start,
            "stable resident monitor log changed during read",
        )
    finally:
        os.close(descriptor)
    if start:
        raw = raw.partition(b"\n")[2]
    complete = raw.rsplit(b"\n", 1)[0]
    rows = complete.splitlines()
    _require(
        bool(rows) and len(rows[-1]) <= MAX_MEMORY_TAIL_BYTES,
        "monitor tail is incomplete",
    )
    row_raw = rows[-1]
    row = mr._strict_object(row_raw, "stable resident monitor sample")
    sample_time = mr._parse_time(row.get("observed_at"), "stable monitor observation")
    age = observed.astimezone(timezone.utc) - sample_time
    _require(
        -MAX_CLOCK_SKEW <= age <= MAX_MEMORY_AGE,
        "stable resident monitor sample is stale or future-dated",
    )
    phase = state["phase"]
    _require(
        row.get("schema") == "flash-next-resident-research-memory-sample/v1"
        and row.get("monitor_phase") == MONITOR_PHASE[phase]
        and row.get("watchdog_sentinel_id") == state.get("watchdog_sentinel_id")
        and row.get("cgroup_swap_capture_status") == "exact_incumbent_pid_cgroup_bound"
        and type(row.get("mem_available_gib")) in {int, float}
        and math.isfinite(row["mem_available_gib"])
        and row["mem_available_gib"] >= plan["monitor_min_mem_available_gib"],
        "stable resident monitor policy differs",
    )
    residents = row.get("incumbent_containers")
    _require(
        isinstance(residents, list)
        and [item.get("id") for item in residents]
        == [item["id"] for item in initial["residents"]]
        and all(
            item.get("running") is True and item.get("oom_killed") is False
            for item in residents
        ),
        "stable resident monitor identities differ",
    )
    cgroups = row.get("incumbent_cgroups")
    _require(
        isinstance(cgroups, dict)
        and set(cgroups) == set(initial["cgroups_by_name"])
        and all(
            isinstance(cgroups[name], dict)
            and all(
                cgroups[name].get(key) == baseline.get(key)
                for key in STABLE_CGROUP_FIELDS
            )
            for name, baseline in initial["cgroups_by_name"].items()
        ),
        "stable resident cgroup monitor identities differ",
    )
    nara = row.get("nara")
    _require(
        isinstance(nara, dict) and nara.get("ActiveState") in {"active", "inactive"},
        "stable Nara state is transitioning or absent",
    )
    if phase == "evaluation":
        quiet = state.get("quiet_observation")
        _require(
            isinstance(quiet, dict)
            and quiet.get("nara", {}).get("ActiveState") == "inactive"
            and nara["ActiveState"] == "inactive",
            "stable evaluation does not prove Nara isolation",
        )
    if nara["ActiveState"] == "inactive" and initial["nara"]["ActiveState"] == "active":
        _require(
            state.get("nara_stop_attempted") is True,
            "stable Nara pause has no registered stop attempt",
        )
    return row, row_raw


def _restoration_proof(initial: dict[str, Any], restoration: Any) -> None:
    _require(
        isinstance(restoration, dict)
        and restoration.get("status") == "verified"
        and restoration.get("errors") == []
        and restoration.get("sentinel_retained") is False,
        "stable restoration is not verified",
    )
    final = restoration.get("final_observation")
    _require(
        isinstance(final, dict)
        and final.get("watchdog_sentinel_by_name") is None
        and final.get("watchdog_sentinel_by_id") is None
        and final.get("residents_by_name") == initial.get("residents_by_name"),
        "stable final resident identity differs",
    )
    before_cgroups = initial.get("cgroups_by_name")
    final_cgroups = final.get("cgroups_by_name")
    _require(
        isinstance(before_cgroups, dict)
        and isinstance(final_cgroups, dict)
        and set(before_cgroups) == set(final_cgroups)
        and all(
            all(
                final_cgroups[name].get(key) == baseline.get(key)
                for key in STABLE_CGROUP_FIELDS
            )
            for name, baseline in before_cgroups.items()
        ),
        "stable final resident cgroups differ",
    )
    _require(
        final.get("nara", {}).get("ActiveState")
        == initial.get("nara", {}).get("ActiveState"),
        "stable final Nara activity differs from its baseline",
    )


def _terminal_restored(
    receipt_dir: Path,
    *,
    state: dict[str, Any],
    plan_sha: str,
    plan: dict[str, Any],
    argv: list[str],
) -> bool:
    phase = state.get("phase")
    _require(phase in TERMINAL_PHASES, "stable lifecycle phase is unsupported")
    if phase == "recovery_unknown":
        raise StableRuntimeError("stable lifecycle recovery remains unknown")
    initial = _validate_initial(state)
    if phase == "supervisor_recovered":
        recovery, _, _ = _read_document(
            receipt_dir / "supervisor-recovery.json",
            maximum=MAX_RESULT_BYTES,
            label="stable supervisor recovery",
        )
        _require(
            set(recovery) == RECOVERY_FIELDS
            and recovery.get("schema_version") == RECOVERY_SCHEMA
            and recovery.get("window_id") == plan["window_id"]
            and recovery.get("status") == "verified"
            and recovery.get("error") is None
            and recovery.get("restoration") == state.get("restoration"),
            "stable supervisor recovery receipt differs",
        )
        _restoration_proof(initial, recovery["restoration"])
        supervision, _, _ = _read_document(
            receipt_dir / "supervision.json",
            maximum=MAX_RESULT_BYTES,
            label="stable parent supervision",
        )
        _require(
            set(supervision) == rv.SUPERVISION_FIELDS
            and supervision.get("schema_version") == rv.SUPERVISION_SCHEMA
            and supervision.get("window_id") == plan["window_id"]
            and supervision.get("plan_sha256") == plan_sha
            and supervision.get("command_sha256")
            == hashlib.sha256(
                json.dumps(
                    argv, sort_keys=True, separators=(",", ":"), allow_nan=False
                ).encode()
            ).hexdigest()
            and supervision.get("argv") == argv
            and supervision.get("pid") == state.get("worker_pid")
            and supervision.get("worker_start_ticks") == state.get("worker_start_ticks")
            and supervision.get("boot_id") == state.get("boot_id")
            and supervision.get("emergency_recovery") == recovery,
            "stable recovered supervision receipt differs",
        )
        return True

    result, _, result_sha = _read_document(
        receipt_dir / "result.json",
        maximum=MAX_RESULT_BYTES,
        label="stable lifecycle result",
    )
    _require(
        set(result) == rv.RESULT_FIELDS
        and result.get("schema_version") == rv.RESULT_SCHEMA
        and result.get("window_id") == plan["window_id"]
        and result.get("plan_sha256") == plan_sha
        and result.get("definition_sha256") == plan["definition_sha256"]
        and result.get("run_manifest_sha256") == plan["run_manifest_sha256"]
        and result.get("restoration_passed") is True
        and result.get("restoration") == state.get("restoration")
        and result.get("status") in {"complete", "failed"},
        "stable lifecycle terminal result differs",
    )
    _require(
        state.get("phase") == result["status"]
        and state.get("result_status") == result["status"],
        "stable terminal state and result statuses differ",
    )
    _restoration_proof(initial, result["restoration"])
    supervision, _, _ = _read_document(
        receipt_dir / "supervision.json",
        maximum=MAX_RESULT_BYTES,
        label="stable parent supervision",
    )
    _require(
        set(supervision) == rv.SUPERVISION_FIELDS
        and supervision.get("schema_version") == rv.SUPERVISION_SCHEMA
        and supervision.get("window_id") == plan["window_id"]
        and supervision.get("plan_sha256") == plan_sha
        and supervision.get("command_sha256")
        == hashlib.sha256(
            json.dumps(
                argv, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode()
        ).hexdigest()
        and supervision.get("argv") == argv
        and supervision.get("pid") == state.get("worker_pid")
        and supervision.get("worker_start_ticks") == state.get("worker_start_ticks")
        and supervision.get("boot_id") == state.get("boot_id")
        and supervision.get("lifecycle_result_sha256") == result_sha,
        "stable terminal supervision receipt differs",
    )
    return True


def project_active_stable_runtime(
    *,
    repo: Path,
    program_root: Path,
    proc_root: Path,
    boot_id_path: Path,
    observed: datetime,
) -> dict[str, Any] | None:
    """Project one registered active resident window or fail closed.

    ``None`` means either no registered attempt exists or exact terminal
    restoration is proven.  Every attempted but untrusted/nonterminal state
    returns a model-runtime/v1 ``unknown`` row and must block older fallback.
    """
    comparison_id: str | None = None
    run_id: str | None = None
    phase: str | None = None
    try:
        _require(
            isinstance(observed, datetime) and observed.tzinfo is not None,
            "stable runtime observation time is invalid",
        )
        selected = _select_attempt(repo.absolute(), program_root.absolute())
        if selected is None:
            return None
        registration, reference, receipt_dir = selected
        comparison_id = registration.document["comparison_id"]
        lifecycle = reference["lifecycle"]
        run_id = lifecycle["window_id"]
        registered_at = datetime.fromisoformat(
            registration.document["registered_at"][:-1] + "+00:00"
        )
        _require(
            registered_at <= observed.astimezone(timezone.utc) + MAX_CLOCK_SKEW,
            "stable registration is future-dated",
        )
        plan, plan_raw, plan_sha, code_root, argv = _validate_window(
            registration,
            reference,
            receipt_dir,
            program_root.absolute(),
            repo.absolute(),
        )
        state, state_raw, _ = _read_document(
            receipt_dir / "state.json",
            maximum=MAX_STATE_BYTES,
            label="stable lifecycle state",
        )
        phase = state.get("phase") if isinstance(state.get("phase"), str) else None
        expected_state_fields = STATE_FIELDS | (
            {"result_status"} if "result_status" in state else set()
        )
        _require(
            set(state) == expected_state_fields, "stable lifecycle state fields differ"
        )
        _require(
            state.get("schema_version") == rv.STATE_SCHEMA
            and state.get("window_id") == run_id
            and state.get("pair_id") == plan["pair_id"]
            and state.get("plan_sha256") == plan_sha
            and state.get("definition_sha256") == plan["definition_sha256"]
            and state.get("run_manifest_sha256") == plan["run_manifest_sha256"]
            and phase in ACTIVE_PHASES | TERMINAL_PHASES,
            "stable lifecycle state differs from the registered plan",
        )
        if phase in TERMINAL_PHASES:
            _terminal_restored(
                receipt_dir, state=state, plan_sha=plan_sha, plan=plan, argv=argv
            )
            state_recheck = mr._read_path(
                receipt_dir / "state.json",
                maximum=MAX_STATE_BYTES,
                label="stable lifecycle state recheck",
            )
            _require(
                state_recheck == state_raw,
                "stable terminal lifecycle changed during projection",
            )
            return None

        initial = _validate_initial(state)
        process, process_raw, _ = _read_document(
            receipt_dir / "process.json",
            maximum=MAX_WINDOW_BYTES,
            label="stable process receipt",
        )
        _require(
            set(process) == rv.PROCESS_FIELDS
            and process.get("schema_version") == rv.PROCESS_SCHEMA
            and process.get("window_id") == run_id
            and process.get("plan_sha256") == plan_sha,
            "stable process receipt differs from the window plan",
        )
        _validate_live_process(
            state,
            process,
            code_root=code_root,
            argv=argv,
            proc_root=proc_root,
            boot_id_path=boot_id_path,
        )
        started = mr._parse_time(state.get("started_at"), "stable worker start")
        process_started = mr._parse_time(
            process.get("started_at"), "stable process start"
        )
        observed_utc = observed.astimezone(timezone.utc)
        _require(
            process_started <= started <= observed_utc + MAX_CLOCK_SKEW
            and observed_utc
            < process_started + timedelta(seconds=plan["window_deadline_seconds"]),
            "stable worker deadline or chronology differs",
        )
        memory, memory_raw = _last_memory(
            receipt_dir / "resident-memory.jsonl",
            observed=observed_utc,
            state=state,
            plan=plan,
            initial=initial,
        )
        state_recheck = mr._read_path(
            receipt_dir / "state.json",
            maximum=MAX_STATE_BYTES,
            label="stable lifecycle state recheck",
        )
        _require(
            state_recheck == state_raw,
            "stable lifecycle phase changed during projection",
        )
        _validate_live_process(
            state,
            process,
            code_root=code_root,
            argv=argv,
            proc_root=proc_root,
            boot_id_path=boot_id_path,
        )
        nara = "running" if memory["nara"]["ActiveState"] == "active" else "paused"
        return {
            "schema_version": mr.SCHEMA_VERSION,
            "observed_at": observed_utc.isoformat(),
            "mode": "resident",
            "mode_source": "stable_benchmark_state",
            "mode_source_sha256": mr._composite_sha256(
                registration=registration.raw_sha256,
                window=hashlib.sha256(plan_raw).hexdigest(),
                process=hashlib.sha256(process_raw).hexdigest(),
                state=hashlib.sha256(state_raw).hexdigest(),
                memory=hashlib.sha256(memory_raw).hexdigest(),
            ),
            "resident_services_expected": "online",
            "nara_service_expected": nara,
            "comparison_id": comparison_id,
            "run_id": run_id,
            "phase": phase,
            "candidate_variant": None,
            "source_error": None,
        }
    except (
        OSError,
        UnicodeError,
        ValueError,
        TypeError,
        AttributeError,
        rv.ReceiptVerificationError,
        mr.RuntimeSourceError,
        StableRuntimeError,
    ):
        return _unknown(
            observed,
            "stable benchmark state is absent, stale, or untrusted",
            comparison_id=comparison_id,
            run_id=run_id,
            phase=phase,
        )


__all__ = ["project_active_stable_runtime"]
