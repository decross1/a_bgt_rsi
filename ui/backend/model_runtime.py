"""Fail-closed projection of the authorized local-model operating mode.

Endpoint reachability says what answers; it cannot say whether stopping the
resident bundle was intentional.  This module reads the qualification
controller's fixed, versioned state and admits an active research mode only
when the state is bound to the current boot, the exact live worker process,
the registered plan/contract, an unexpired deadline, and a fresh memory-gate
sample.  It executes no commands and never inspects or mutates containers.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

QUALIFICATION_ROOT = Path(
    "/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-14/"
    "qwen-flash-next-research/qualification-runs"
)
BOOT_ID_PATH = Path("/proc/sys/kernel/random/boot_id")
PROC_ROOT = Path("/proc")

SCHEMA_VERSION = "model-runtime/v1"
STATE_SCHEMA = "qwen-flash-next-qualification-state/v2"
MEMORY_SCHEMA = "qwen-flash-next-memory-sample/v2"
RUN_ID = re.compile(r"qfn-c0-[A-Za-z0-9][A-Za-z0-9._-]{0,79}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
CONTAINER_ID = re.compile(r"[0-9a-f]{64}\Z")
MAX_RUNS = 128
MAX_STATE_BYTES = 256 * 1024
MAX_PLAN_BYTES = 2 * 1024 * 1024
MAX_CONTRACT_BYTES = 4 * 1024 * 1024
MAX_RESULT_BYTES = 2 * 1024 * 1024
MAX_MEMORY_BYTES = 4 * 1024 * 1024
MAX_PROC_BYTES = 32 * 1024
MAX_MEMORY_AGE_SECONDS = 5.0
MAX_CLOCK_SKEW_SECONDS = 5.0

SETUP_PHASES = frozenset(
    {"preflight", "model_verification", "setup_quiescence", "sentinel_create"}
)
CANDIDATE_PHASES = frozenset(
    {"candidate_start", "readiness", "probes", "qualification_passed"}
)
TRANSITION_PHASES = frozenset({"resident_stop", "restoring"})
TERMINAL_PHASES = frozenset(
    {"complete", "supervisor_recovered", "recovery_unknown"}
)
PHASES = SETUP_PHASES | CANDIDATE_PHASES | TRANSITION_PHASES | TERMINAL_PHASES


class RuntimeSourceError(ValueError):
    pass


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _composite_sha256(**parts: str) -> str:
    raw = json.dumps(
        parts, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    return _sha256(raw)


def _strict_object(raw: bytes, label: str) -> dict[str, Any]:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise RuntimeSourceError(f"duplicate key in {label}")
            result[key] = value
        return result

    def nonfinite(value):
        raise RuntimeSourceError(f"non-finite number in {label}: {value}")

    try:
        value = json.loads(
            raw, object_pairs_hook=unique, parse_constant=nonfinite
        )
    except (UnicodeError, ValueError, TypeError) as exc:
        raise RuntimeSourceError(f"invalid JSON in {label}") from exc
    if not isinstance(value, dict):
        raise RuntimeSourceError(f"{label} must be an object")
    return value


def _flags(*, directory: bool = False) -> int:
    value = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
    value |= getattr(os, "O_NOFOLLOW", 0)
    if directory:
        value |= os.O_DIRECTORY
    return value


def _read_fd(parent_fd: int, name: str, *, maximum: int, label: str) -> bytes:
    try:
        descriptor = os.open(name, _flags(), dir_fd=parent_fd)
    except OSError as exc:
        raise RuntimeSourceError(f"{label} is unavailable") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > maximum:
            raise RuntimeSourceError(f"{label} exceeds its regular-file bound")
        chunks = []
        remaining = maximum + 1
        while remaining:
            chunk = os.read(descriptor, min(remaining, 256 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        if (
            len(raw) > maximum
            or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        ):
            raise RuntimeSourceError(f"{label} changed during its bounded read")
        return raw
    finally:
        os.close(descriptor)


def _read_path(path: Path, *, maximum: int, label: str) -> bytes:
    parent = path.parent
    try:
        parent_fd = os.open(parent, _flags(directory=True))
    except OSError as exc:
        raise RuntimeSourceError(f"{label} parent is unavailable") from exc
    try:
        return _read_fd(parent_fd, path.name, maximum=maximum, label=label)
    finally:
        os.close(parent_fd)


def _parse_time(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or len(value) > 64:
        raise RuntimeSourceError(f"{label} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeSourceError(f"{label} is invalid") from exc
    if parsed.tzinfo is None:
        raise RuntimeSourceError(f"{label} lacks a timezone")
    return parsed.astimezone(timezone.utc)


def _canonical_sha256(value: Any) -> str:
    return _sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    )


def _open_latest_run(root: Path) -> tuple[int, str, bytes]:
    """Open the latest direct child and return its fd, id and raw state."""
    try:
        root_fd = os.open(root, _flags(directory=True))
    except OSError as exc:
        raise RuntimeSourceError("qualification state root is unavailable") from exc
    candidates: list[tuple[int, str, bytes]] = []
    try:
        with os.scandir(root_fd) as entries:
            names = []
            for entry in entries:
                names.append(entry.name)
                if len(names) > MAX_RUNS:
                    raise RuntimeSourceError(
                        "qualification state root exceeds the scan bound"
                    )
        for name in names:
            if not RUN_ID.fullmatch(name):
                continue
            try:
                run_fd = os.open(name, _flags(directory=True), dir_fd=root_fd)
            except OSError:
                continue
            try:
                directory_mtime = os.fstat(run_fd).st_mtime_ns
                details = os.stat(
                    "state.json", dir_fd=run_fd, follow_symlinks=False
                )
                if not stat.S_ISREG(details.st_mode):
                    candidates.append((max(directory_mtime, details.st_mtime_ns), name, b""))
                    continue
                raw = _read_fd(
                    run_fd,
                    "state.json",
                    maximum=MAX_STATE_BYTES,
                    label="runtime state",
                )
                candidates.append((details.st_mtime_ns, name, raw))
            except (OSError, RuntimeSourceError):
                # An unreadable newest state must still prevent fallback to a
                # stale older run. Preserve its mtime as an invalid candidate.
                try:
                    details = os.stat(
                        "state.json", dir_fd=run_fd, follow_symlinks=False
                    )
                    candidates.append((details.st_mtime_ns, name, b""))
                except OSError:
                    candidates.append((directory_mtime, name, b""))
            finally:
                os.close(run_fd)
        if not candidates:
            raise RuntimeSourceError("no qualification runtime state is available")
        _, name, raw = max(candidates, key=lambda item: (item[0], item[1]))
        if not raw:
            raise RuntimeSourceError("latest qualification runtime state is invalid")
        run_fd = os.open(name, _flags(directory=True), dir_fd=root_fd)
        return run_fd, name, raw
    finally:
        os.close(root_fd)


def _validate_registered_plan(
    run_path: Path,
    state: dict[str, Any],
    plan: dict[str, Any],
    contract: dict[str, Any],
    contract_raw_sha256: str,
) -> None:
    """Reuse the controller's exact allowlist instead of duplicating it."""
    try:
        from bench.flash_next_ab import qualification

        validated_contract = qualification.validate_contract(contract)
        expected_plan = qualification.plan_qualification(
            validated_contract, contract_raw_sha256, run_path
        )
    except Exception as exc:
        raise RuntimeSourceError("runtime plan or contract is unregistered") from exc
    if plan != expected_plan:
        raise RuntimeSourceError("runtime plan differs from the controller allowlist")
    if state.get("contract_sha256") != contract_raw_sha256:
        raise RuntimeSourceError("runtime contract hash differs")


def _validate_initial(state: dict[str, Any]) -> bool:
    initial = state.get("initial")
    if not isinstance(initial, dict) or not isinstance(
        initial.get("nara_was_active"), bool
    ):
        raise RuntimeSourceError("captured resident state is unavailable")
    residents = initial.get("residents")
    if not isinstance(residents, list) or len(residents) != 2:
        raise RuntimeSourceError("captured resident set is invalid")
    expected = {
        "vllm-gemma4": "fc61a80d6c2d07b551c5afdd566a7c82ee05ad40c014d69c428e299e49101374",
        "vllm-qwen": "bcb6cd87757279ff77f1460cab2f8ad6cf1a2e46d19dad165b07dccecfa509bb",
    }
    observed = {}
    for row in residents:
        if not isinstance(row, dict) or row.get("name") in observed:
            raise RuntimeSourceError("captured resident row is invalid")
        observed[row.get("name")] = row
    if set(observed) != set(expected):
        raise RuntimeSourceError("captured resident identities are incomplete")
    for name, identity in expected.items():
        row = observed[name]
        if row.get("id") != identity or row.get("running") is not True:
            raise RuntimeSourceError("captured resident identity differs")
    return initial["nara_was_active"]


def _validate_process(
    state: dict[str, Any], run_path: Path, proc_root: Path
) -> None:
    pid = state.get("worker_pid")
    ticks = state.get("worker_start_ticks")
    if (
        isinstance(pid, bool)
        or not isinstance(pid, int)
        or pid <= 0
        or isinstance(ticks, bool)
        or not isinstance(ticks, int)
        or ticks <= 0
    ):
        raise RuntimeSourceError("worker process identity is invalid")
    process = proc_root / str(pid)
    stat_raw = _read_path(process / "stat", maximum=MAX_PROC_BYTES, label="worker stat")
    try:
        text = stat_raw.decode("utf-8")
        closing = text.rfind(")")
        fields_from_three = text[closing + 1 :].split()
        observed_ticks = int(fields_from_three[19])
    except (UnicodeError, ValueError, IndexError) as exc:
        raise RuntimeSourceError("worker stat is malformed") from exc
    if closing < 0 or observed_ticks != ticks:
        raise RuntimeSourceError("worker process start identity differs")

    command_raw = _read_path(
        process / "cmdline", maximum=MAX_PROC_BYTES, label="worker command"
    )
    try:
        command = [part.decode("utf-8") for part in command_raw.rstrip(b"\0").split(b"\0")]
    except UnicodeError as exc:
        raise RuntimeSourceError("worker command is malformed") from exc
    try:
        from bench.flash_next_ab.qualification import CONTRACT_PATH
    except Exception as exc:
        raise RuntimeSourceError("worker command allowlist is unavailable") from exc
    expected_tail = [
        "-m",
        "bench.flash_next_ab.qualification",
        "--worker",
        "--contract",
        str(CONTRACT_PATH),
        "--output-dir",
        str(run_path),
    ]
    if (
        len(command) != 1 + len(expected_tail)
        or not Path(command[0]).is_absolute()
        or not Path(command[0]).name.startswith("python")
        or command[1:] != expected_tail
    ):
        raise RuntimeSourceError("worker command differs from the allowlist")


def _latest_memory(
    run_fd: int, now: datetime, *, floor_gib: float, mutation: bool
) -> tuple[dict[str, Any], str]:
    raw = _read_fd(
        run_fd, "memory.jsonl", maximum=MAX_MEMORY_BYTES, label="memory gate"
    )
    lines = [line for line in raw.splitlines() if line.strip()]
    if not lines:
        raise RuntimeSourceError("memory gate has no samples")
    row_raw = lines[-1]
    row = _strict_object(row_raw, "memory gate sample")
    observed_at = _parse_time(row.get("observed_at"), "memory observed_at")
    age = (now - observed_at).total_seconds()
    available = row.get("mem_available_gib")
    if (
        isinstance(floor_gib, bool)
        or not isinstance(floor_gib, (int, float))
        or not math.isfinite(floor_gib)
        or floor_gib <= 0
        or age < -MAX_CLOCK_SKEW_SECONDS
        or age > MAX_MEMORY_AGE_SECONDS
        or isinstance(available, bool)
        or not isinstance(available, (int, float))
        or not math.isfinite(available)
        or available < floor_gib
    ):
        raise RuntimeSourceError("memory gate sample is stale or below its floor")
    if row.get("schema") != MEMORY_SCHEMA:
        raise RuntimeSourceError("memory gate sample schema is unsupported")
    if mutation and (
        row.get("monitor_phase") != "mutation"
        or row.get("mutation_pswpout_delta_pages") != 0
    ):
        raise RuntimeSourceError("mutation memory gate is not clean")
    return row, _sha256(row_raw)


def _terminal_restoration(
    run_fd: int,
    run_path: Path,
    run_id: str,
    state: dict[str, Any],
    plan: dict[str, Any],
    *,
    started: datetime,
    observed: datetime,
    terminal_validator: Callable[[Path], None],
) -> str:
    restoration = state.get("restoration")
    if (
        not isinstance(restoration, dict)
        or restoration.get("status") != "verified"
        or restoration.get("errors") != []
        or restoration.get("sentinel_retained") is not False
    ):
        raise RuntimeSourceError("terminal restoration is not verified")
    verified_at = _parse_time(restoration.get("verified_at"), "restoration verified_at")
    if verified_at < started or verified_at > observed + timedelta(seconds=MAX_CLOCK_SKEW_SECONDS):
        raise RuntimeSourceError("terminal restoration time is inconsistent")
    if state["phase"] == "recovery_unknown":
        raise RuntimeSourceError("supervisor recovery is unknown")
    filename = (
        "result.json" if state["phase"] == "complete" else "supervisor-recovery.json"
    )
    raw = _read_fd(run_fd, filename, maximum=MAX_RESULT_BYTES, label="restoration receipt")
    receipt = _strict_object(raw, "restoration receipt")
    if state["phase"] == "complete":
        terminal_validator(run_path)
        valid = (
            receipt.get("schema") == "qwen-flash-next-qualification-result/v2"
            and receipt.get("run_id") == run_id
            and receipt.get("contract_sha256") == state["contract_sha256"]
            and receipt.get("plan_sha256") == _canonical_sha256(plan)
            and isinstance(receipt.get("restoration"), dict)
            and receipt["restoration"] == restoration
        )
    else:
        valid = (
            receipt.get("schema") == "qwen-flash-next-supervisor-recovery/v1"
            and receipt.get("run_id") == run_id
            and receipt.get("status") == "verified"
            and isinstance(receipt.get("restoration"), dict)
            and receipt["restoration"] == restoration
        )
    if not valid:
        raise RuntimeSourceError("restoration receipt is not bound to the runtime state")
    return _sha256(raw)


def _validate_complete_receipt(run_path: Path) -> None:
    """Apply the shared source validator before admitting a completed run."""
    try:
        from bench.flash_next_ab.harness import validate_flash_qualification_files

        validate_flash_qualification_files(
            receipt_path=run_path / "result.json",
            qualification_plan_path=run_path / "plan.json",
            contract_snapshot_path=run_path / "launch-contract.snapshot.json",
            contract_raw_path=run_path / "launch-contract.raw.json",
            require_passed=False,
        )
    except Exception as exc:
        raise RuntimeSourceError("completed qualification proof is invalid") from exc


def _unknown(observed_at: str, error: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "observed_at": observed_at,
        "mode": "unknown",
        "mode_source": "none",
        "mode_source_sha256": None,
        "resident_services_expected": "unknown",
        "nara_service_expected": "unknown",
        "run_id": None,
        "phase": None,
        "source_error": error,
    }


def project_model_runtime(
    qualification_root: Path = QUALIFICATION_ROOT,
    *,
    proc_root: Path = PROC_ROOT,
    boot_id_path: Path = BOOT_ID_PATH,
    now: Callable[[], datetime] | None = None,
    plan_validator: Callable[..., None] = _validate_registered_plan,
    terminal_validator: Callable[[Path], None] = _validate_complete_receipt,
) -> dict[str, Any]:
    """Project one bounded operating-mode record. Never raises."""
    observed = (now or (lambda: datetime.now(timezone.utc)))().astimezone(timezone.utc)
    observed_at = observed.isoformat()
    run_fd = None
    try:
        run_fd, run_id, state_raw = _open_latest_run(qualification_root)
        state = _strict_object(state_raw, "runtime state")
        if (
            state.get("schema") != STATE_SCHEMA
            or state.get("run_id") != run_id
            or state.get("phase") not in PHASES
            or not SHA256.fullmatch(str(state.get("plan_sha256", "")))
            or not SHA256.fullmatch(str(state.get("contract_sha256", "")))
            or state.get("memory_log_relpath") != "memory.jsonl"
        ):
            raise RuntimeSourceError("runtime state identity is unsupported")

        plan_raw = _read_fd(run_fd, "plan.json", maximum=MAX_PLAN_BYTES, label="runtime plan")
        contract_raw = _read_fd(
            run_fd,
            "launch-contract.raw.json",
            maximum=MAX_CONTRACT_BYTES,
            label="runtime contract",
        )
        plan = _strict_object(plan_raw, "runtime plan")
        contract = _strict_object(contract_raw, "runtime contract")
        if _canonical_sha256(plan) != state["plan_sha256"]:
            raise RuntimeSourceError("runtime plan hash differs")
        contract_sha = _sha256(contract_raw)
        if contract_sha != state["contract_sha256"]:
            raise RuntimeSourceError("runtime contract hash differs")
        run_path = qualification_root / run_id
        try:
            path_details = os.stat(run_path, follow_symlinks=False)
            descriptor_details = os.fstat(run_fd)
        except OSError as exc:
            raise RuntimeSourceError("runtime directory identity is unavailable") from exc
        if (
            not stat.S_ISDIR(path_details.st_mode)
            or (path_details.st_dev, path_details.st_ino)
            != (descriptor_details.st_dev, descriptor_details.st_ino)
        ):
            raise RuntimeSourceError("runtime directory changed during admission")
        plan_validator(run_path, state, plan, contract, contract_sha)

        started = _parse_time(state.get("started_at"), "runtime started_at")
        updated = _parse_time(state.get("updated_at"), "runtime updated_at")
        deadline = _parse_time(
            state.get("invocation_deadline_at"), "runtime invocation_deadline_at"
        )
        duration = plan.get("invocation_deadline_seconds")
        if (
            isinstance(duration, bool)
            or not isinstance(duration, int)
            or not 1 <= duration <= 3_600
            or abs((deadline - (started + timedelta(seconds=duration))).total_seconds())
            > 0.001
            or updated < started
            or updated > observed + timedelta(seconds=MAX_CLOCK_SKEW_SECONDS)
        ):
            raise RuntimeSourceError("runtime lifecycle clock is inconsistent")
        current_boot = _read_path(
            boot_id_path, maximum=256, label="current boot identity"
        ).decode("ascii").strip()
        if state.get("boot_id") != current_boot:
            raise RuntimeSourceError("runtime state belongs to another boot")

        phase = state["phase"]
        nara_initially_active = False
        receipt_sha = None
        memory_sha = None
        if phase in TERMINAL_PHASES:
            nara_initially_active = _validate_initial(state)
            receipt_sha = _terminal_restoration(
                run_fd,
                run_path,
                run_id,
                state,
                plan,
                started=started,
                observed=observed,
                terminal_validator=terminal_validator,
            )
            mode = "resident"
            resident_expected = "online"
            nara_expected = "running" if nara_initially_active else "paused"
        else:
            if observed >= deadline:
                raise RuntimeSourceError("runtime authorization deadline expired")
            _validate_process(state, run_path, proc_root)
            _, memory_sha = _latest_memory(
                run_fd,
                observed,
                floor_gib=plan.get("min_mem_available_gib"),
                mutation=phase in CANDIDATE_PHASES or phase in TRANSITION_PHASES,
            )
            if phase in CANDIDATE_PHASES:
                if not CONTAINER_ID.fullmatch(str(state.get("candidate_id", ""))):
                    raise RuntimeSourceError("candidate identity is unavailable")
                nara_initially_active = _validate_initial(state)
                mode = "candidate_research"
                resident_expected = "stopped"
                nara_expected = "paused"
            else:
                mode = "transitioning"
                resident_expected = "unknown"
                nara_expected = "unknown"

        source_sha = _composite_sha256(
            state=_sha256(state_raw),
            plan=_sha256(plan_raw),
            contract=contract_sha,
            memory=memory_sha or "",
            restoration=receipt_sha or "",
        )
        if _read_fd(
            run_fd,
            "state.json",
            maximum=MAX_STATE_BYTES,
            label="runtime state recheck",
        ) != state_raw:
            raise RuntimeSourceError("runtime phase changed during admission")
        return {
            "schema_version": SCHEMA_VERSION,
            "observed_at": observed_at,
            "mode": mode,
            "mode_source": "qualification_state",
            "mode_source_sha256": source_sha,
            "resident_services_expected": resident_expected,
            "nara_service_expected": nara_expected,
            "run_id": run_id,
            "phase": phase,
            "source_error": None,
        }
    except (OSError, RuntimeSourceError, ValueError, TypeError, AttributeError):
        return _unknown(observed_at, "runtime state is absent, stale, or untrusted")
    finally:
        if run_fd is not None:
            os.close(run_fd)


__all__ = [
    "QUALIFICATION_ROOT",
    "RuntimeSourceError",
    "project_model_runtime",
]
