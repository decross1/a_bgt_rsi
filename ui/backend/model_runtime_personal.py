"""Read-only projection of the bounded personal Flash serving sessions.

This is an operational overlay, not qualification or promotion evidence.  It
only admits code-owned Mia and SGLang session families and binds an active state
to a fresh heartbeat plus the exact live controller process identity.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

BASE = Path(
    "/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-18/"
    "flash-personal-recovery"
)
MIA_SESSION_ROOT = BASE / "session-a"  # historical receipt; production discovers peers
SGLANG_RUNTIME_ROOT = BASE / "sglang-fallback-prep/runtime"
SGLANG_SESSION_ROOT = (
    SGLANG_RUNTIME_ROOT / "session-s3-readiness-v5-001"
)
PROC_ROOT = Path("/proc")

SCHEMA_VERSION = "model-runtime/v1"
MODE_SOURCE = "personal_session_state"
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
RUN_ID = re.compile(r"session-[a-z0-9][a-z0-9-]{0,63}\Z")
SGLANG_RUN_ID = re.compile(r"session-s3-readiness-v5-[0-9]{3}\Z")
MAX_FILE_BYTES = 512 * 1024
MAX_MIA_SESSIONS = 32
MAX_SGLANG_SESSIONS = 32
MAX_BASE_ENTRIES = 256
MAX_CLOCK_SKEW_SECONDS = 5.0
SG_HEARTBEAT_MAX_AGE_SECONDS = 15.0

SG_IMAGE = "sha256:2ee545cf877ae8497c123637e061b6e6313c624e30018f975969b1d554e27f56"
SG_MODEL = "nvidia/Qwen3.8-Flash-Next-NVFP4"
SG_MODEL_REVISION = "fc694b54fb0174e0913e6adf86691ef85a4ead47"
SG_PROFILE_SHA256 = "2d84e1dc107a48b9ef5967ebd4c7a9c288ec54ac6d5e8ae8d0d973fe82e1c84b"
SG_ADAPTER = BASE / "sglang-fallback-prep/guard_uid1000_alloc_v4.py"
SG_PROFILE = BASE / "sglang-fallback-prep/nextn-32k-c1-s3.json"
SG_SOURCES = BASE / "sglang-fallback-prep/source/locks/sources.json"


class PersonalRuntimeError(ValueError):
    pass


@dataclass(frozen=True)
class _Result:
    status: str
    projection: dict[str, Any] | None = None
    error: str | None = None


def _discover_mia_sessions(base: Path) -> tuple[list[Path], str | None]:
    """List only direct, non-symlink ``session-*`` directories under BASE."""
    descriptor = None
    try:
        descriptor = os.open(
            base,
            os.O_RDONLY | os.O_NONBLOCK | os.O_DIRECTORY
            | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        names = []
        with os.scandir(descriptor) as entries:
            for count, entry in enumerate(entries, start=1):
                if count > MAX_BASE_ENTRIES:
                    raise PersonalRuntimeError("personal artifact root exceeds scan cap")
                if not RUN_ID.fullmatch(entry.name):
                    continue
                if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
                    raise PersonalRuntimeError(
                        "Mia session entry is not a regular directory"
                    )
                names.append(entry.name)
        names.sort()
        if len(names) > MAX_MIA_SESSIONS:
            raise PersonalRuntimeError("too many fixed-root Mia session receipts")
        return [base / name for name in names], None
    except FileNotFoundError:
        return [], None
    except (OSError, PersonalRuntimeError) as exc:
        return [], str(exc)
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _discover_sglang_sessions(base: Path) -> tuple[list[Path], str | None]:
    """List only the exact numbered v5 session family under its fixed root."""
    descriptor = None
    try:
        descriptor = os.open(
            base,
            os.O_RDONLY | os.O_NONBLOCK | os.O_DIRECTORY
            | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        names = []
        with os.scandir(descriptor) as entries:
            for count, entry in enumerate(entries, start=1):
                if count > MAX_BASE_ENTRIES:
                    raise PersonalRuntimeError("SGLang runtime root exceeds scan cap")
                if not SGLANG_RUN_ID.fullmatch(entry.name):
                    continue
                if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
                    raise PersonalRuntimeError(
                        "SGLang session entry is not a regular directory"
                    )
                names.append(entry.name)
        names.sort()
        if len(names) > MAX_SGLANG_SESSIONS:
            raise PersonalRuntimeError("too many fixed-root SGLang session receipts")
        return [base / name for name in names], None
    except FileNotFoundError:
        return [], None
    except (OSError, PersonalRuntimeError) as exc:
        return [], str(exc)
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _strict_object(raw: bytes, label: str) -> dict[str, Any]:
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise PersonalRuntimeError(f"duplicate key in {label}")
            value[key] = item
        return value

    def nonfinite(value):
        raise PersonalRuntimeError(f"non-finite number in {label}: {value}")

    try:
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=unique, parse_constant=nonfinite
        )
    except (UnicodeError, ValueError, TypeError) as exc:
        raise PersonalRuntimeError(f"invalid JSON in {label}") from exc
    if not isinstance(value, dict):
        raise PersonalRuntimeError(f"{label} must be an object")
    return value


def _read_regular(root: Path, relative: str, label: str) -> tuple[bytes, dict[str, Any]]:
    try:
        root_fd = os.open(
            root,
            os.O_RDONLY | os.O_NONBLOCK | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
    except OSError as exc:
        raise PersonalRuntimeError(f"{label} session root is unavailable") from exc
    descriptor = None
    opened_directories: list[int] = []
    try:
        parts = Path(relative).parts
        if not parts or any(part in {"", ".", ".."} for part in parts):
            raise PersonalRuntimeError(f"{label} path is malformed")
        parent_fd = root_fd
        for part in parts[:-1]:
            parent_fd = os.open(
                part,
                os.O_RDONLY | os.O_NONBLOCK | os.O_DIRECTORY
                | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=parent_fd,
            )
            opened_directories.append(parent_fd)
        descriptor = os.open(
            parts[-1],
            os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent_fd,
        )
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode) or details.st_size > MAX_FILE_BYTES:
            raise PersonalRuntimeError(f"{label} is not a bounded regular file")
        chunks = []
        remaining = MAX_FILE_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) > MAX_FILE_BYTES:
            raise PersonalRuntimeError(f"{label} exceeds its byte limit")
        return raw, _strict_object(raw, label)
    except OSError as exc:
        raise PersonalRuntimeError(f"{label} is unavailable") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        for directory in reversed(opened_directories):
            os.close(directory)
        os.close(root_fd)


def _parse_time(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or len(value) > 64:
        raise PersonalRuntimeError(f"{label} is malformed")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PersonalRuntimeError(f"{label} is malformed") from exc
    if parsed.tzinfo is None:
        raise PersonalRuntimeError(f"{label} lacks a timezone")
    return parsed.astimezone(timezone.utc)


def _fresh(value: Any, observed: datetime, maximum_age: float, label: str) -> None:
    at = _parse_time(value, label)
    if at > observed + timedelta(seconds=MAX_CLOCK_SKEW_SECONDS):
        raise PersonalRuntimeError(f"{label} is in the future")
    if (observed - at).total_seconds() > maximum_age:
        raise PersonalRuntimeError(f"{label} is stale")


def _proc_identity(
    proc_root: Path, pid: Any, start_ticks: Any, *, expected_parent: int | None = None
) -> list[str]:
    if type(pid) is not int or type(start_ticks) is not int or pid <= 1 or start_ticks <= 0:
        raise PersonalRuntimeError("process identity is malformed")
    try:
        raw_stat = (proc_root / str(pid) / "stat").read_bytes()
        raw_cmdline = (proc_root / str(pid) / "cmdline").read_bytes()
    except OSError as exc:
        raise PersonalRuntimeError("bound process is absent") from exc
    if len(raw_stat) > 32_768 or len(raw_cmdline) > 32_768:
        raise PersonalRuntimeError("bound process evidence is oversized")
    close = raw_stat.rfind(b")")
    if close < 0:
        raise PersonalRuntimeError("process stat is malformed")
    fields = raw_stat[close + 2 :].split()
    try:
        state = fields[0]
        parent = int(fields[1])
        observed_ticks = int(fields[19])
    except (IndexError, ValueError) as exc:
        raise PersonalRuntimeError("process stat is malformed") from exc
    if state == b"Z" or observed_ticks != start_ticks:
        raise PersonalRuntimeError("bound process exited or its PID was reused")
    if expected_parent is not None and parent != expected_parent:
        raise PersonalRuntimeError("bound process parent changed")
    if not raw_cmdline or not raw_cmdline.endswith(b"\0"):
        raise PersonalRuntimeError("process command line is unavailable")
    try:
        argv = [part.decode("utf-8") for part in raw_cmdline[:-1].split(b"\0")]
    except UnicodeError as exc:
        raise PersonalRuntimeError("process command line is malformed") from exc
    if not argv or any(not part for part in argv):
        raise PersonalRuntimeError("process command line is malformed")
    return argv


def _flag(argv: list[str], name: str) -> str:
    positions = [index for index, value in enumerate(argv) if value == name]
    if len(positions) != 1 or positions[0] + 1 >= len(argv):
        raise PersonalRuntimeError(f"process flag {name} is absent or ambiguous")
    return argv[positions[0] + 1]


def _projection(
    *, observed: datetime, endpoint: str, run_id: str, phase: str,
    candidate_id: str, source_parts: dict[str, bytes]
) -> dict[str, Any]:
    digest = hashlib.sha256()
    for name in sorted(source_parts):
        digest.update(name.encode("ascii") + b"\0" + source_parts[name] + b"\0")
    return {
        "schema_version": SCHEMA_VERSION,
        "observed_at": observed.isoformat(),
        "mode": "candidate_research",
        "mode_source": MODE_SOURCE,
        "mode_source_sha256": digest.hexdigest(),
        "resident_services_expected": "stopped",
        "nara_service_expected": "paused",
        "run_id": run_id,
        "phase": phase,
        "candidate_variant": None,
        "personal_endpoint": endpoint,
        "candidate_id": candidate_id,
        "source_error": None,
    }


def _unknown(observed: datetime, error: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "observed_at": observed.isoformat(),
        "mode": "unknown",
        "mode_source": MODE_SOURCE,
        "mode_source_sha256": None,
        "resident_services_expected": "unknown",
        "nara_service_expected": "unknown",
        "run_id": None,
        "phase": None,
        "candidate_variant": None,
        "personal_endpoint": None,
        "candidate_id": None,
        "source_error": error,
    }


def _mia(root: Path, proc_root: Path, observed: datetime) -> _Result:
    if not root.exists():
        return _Result("inactive")
    try:
        if root.is_symlink() or not RUN_ID.fullmatch(root.name):
            raise PersonalRuntimeError("Mia session root identity is unsupported")
        state_raw, state = _read_regular(root, "state.json", "Mia state")
        phase = state.get("phase")
        if phase == "restored" and (state.get("restoration") or {}).get("status") == "verified":
            return _Result("inactive")
        if phase in {"restoration_failed"}:
            return _Result("terminal_invalid", error="Mia restoration failed")
        if phase not in {"starting", "ready"}:
            raise PersonalRuntimeError("Mia session transition is not live-serving")
        candidate_id = state.get("candidate_id")
        if not SHA256.fullmatch(str(candidate_id or "")):
            raise PersonalRuntimeError("Mia candidate identity is malformed")
        if state.get("output") != str(root):
            raise PersonalRuntimeError("Mia state output root differs")
        heartbeat_raw, heartbeat = _read_regular(root, "heartbeat.json", "Mia heartbeat")
        policy_raw, policy = _read_regular(root, "policy.json", "Mia policy")
        supervisor_raw, supervisor = _read_regular(root, "supervisor.json", "Mia supervisor")
        maximum_age = policy.get("worker_heartbeat_max_age_s")
        if type(maximum_age) is not int or not 5 <= maximum_age <= 120:
            raise PersonalRuntimeError("Mia heartbeat policy is unsupported")
        _fresh(heartbeat.get("at"), observed, float(maximum_age), "Mia heartbeat")
        if heartbeat.get("phase") != phase or heartbeat.get("pid") != supervisor.get("worker_pid"):
            raise PersonalRuntimeError("Mia heartbeat identity differs")
        parent = supervisor.get("pid")
        if state.get("parent_pid") != parent or type(parent) is not int or parent <= 1:
            raise PersonalRuntimeError("Mia supervisor identity differs")
        argv = _proc_identity(
            proc_root,
            supervisor.get("worker_pid"),
            supervisor.get("worker_start_ticks"),
            expected_parent=parent,
        )
        if (
            len(argv) < 4
            or Path(argv[0]).name not in {"python", "python3"}
            or argv[1:4] != ["-m", "bench.flash_next_ab.personal_session", "--worker"]
            or _flag(argv, "--output-dir") != str(root)
        ):
            raise PersonalRuntimeError("Mia worker command differs")
        if phase == "ready":
            data = (state.get("readiness") or {}).get("data")
            if (
                not isinstance(data, list) or len(data) != 1
                or not isinstance(data[0], dict)
                or data[0].get("id") != "qwen3.8-flash-next-mia"
                or data[0].get("max_model_len") != 32768
            ):
                raise PersonalRuntimeError("Mia ready model identity differs")
        if _read_regular(root, "state.json", "Mia state recheck")[0] != state_raw:
            raise PersonalRuntimeError("Mia state changed during admission")
        return _Result(
            "active",
            _projection(
                observed=observed, endpoint="mia", run_id=root.name, phase=phase,
                candidate_id=candidate_id,
                source_parts={
                    "state": state_raw, "heartbeat": heartbeat_raw,
                    "policy": policy_raw, "supervisor": supervisor_raw,
                    "process": "\0".join(argv).encode(),
                },
            ),
        )
    except (OSError, PersonalRuntimeError, ValueError, TypeError, AttributeError) as exc:
        return _Result("invalid", error=str(exc))


def _sglang(root: Path, proc_root: Path, observed: datetime) -> _Result:
    if not root.exists():
        return _Result("inactive")
    try:
        if root.is_symlink() or not RUN_ID.fullmatch(root.name):
            raise PersonalRuntimeError("SGLang session root identity is unsupported")
        state_raw, state = _read_regular(root, "state.json", "SGLang state")
        if state.get("schema") != "flash-sglang-session-state/v1":
            raise PersonalRuntimeError("SGLang state schema differs")
        phase = state.get("phase")
        if phase in {"restored", "restored_after_failure"}:
            restoration = state.get("restoration") or {}
            if restoration.get("status") == "verified":
                return _Result("inactive")
            raise PersonalRuntimeError("SGLang terminal restoration is unverified")
        if phase in {"restoration_failed", "failed_restoring"}:
            status = "terminal_invalid" if phase == "restoration_failed" else "invalid"
            return _Result(status, error="SGLang restoration failed or is unresolved")
        if phase not in {"starting", "ready"}:
            raise PersonalRuntimeError("SGLang session transition is not live-serving")
        candidate_id = state.get("candidate_id")
        if not SHA256.fullmatch(str(candidate_id or "")):
            raise PersonalRuntimeError("SGLang candidate identity is malformed")
        deadline = _parse_time(state.get("candidate_stop_at_or_before"), "SGLang stop deadline")
        if observed >= deadline:
            raise PersonalRuntimeError("SGLang serving authorization expired")
        heartbeat_raw, heartbeat = _read_regular(root, "heartbeat.json", "SGLang heartbeat")
        policy_raw, policy = _read_regular(root, "policy.json", "SGLang policy")
        process_raw, process = _read_regular(root, "guard-process.json", "SGLang guard process")
        launch_raw, launch = _read_regular(
            root, "guard-state/launch-record.json", "SGLang launch record"
        )
        _fresh(heartbeat.get("at"), observed, SG_HEARTBEAT_MAX_AGE_SECONDS, "SGLang heartbeat")
        if heartbeat.get("phase") != "live" or heartbeat.get("candidate_id") != candidate_id:
            raise PersonalRuntimeError("SGLang heartbeat identity differs")
        if (
            process.get("schema") != "flash-sglang-guard-process/v1"
            or process.get("pid") != state.get("guard_pid")
            or process.get("start_ticks") != state.get("guard_start_ticks")
        ):
            raise PersonalRuntimeError("SGLang guard process receipt differs")
        argv = _proc_identity(proc_root, process.get("pid"), process.get("start_ticks"))
        receipt_sha = (state.get("receipt") or {}).get("receipt_sha256")
        if (
            len(argv) < 2
            or Path(argv[0]).name not in {"python", "python3"}
            or argv[1] != str(SG_ADAPTER)
            or _flag(argv, "--image") != SG_IMAGE
            or _flag(argv, "--profile") != str(SG_PROFILE)
            or _flag(argv, "--sources") != str(SG_SOURCES)
            or _flag(argv, "--receipt-sha256") != receipt_sha
            or _flag(argv, "--state-dir") != str(root / "guard-state")
            or _flag(argv, "--max-watch-seconds") != "0"
        ):
            raise PersonalRuntimeError("SGLang guard command differs")
        if hashlib.sha256(launch_raw).hexdigest() != state.get("launch_record_sha256"):
            raise PersonalRuntimeError("SGLang launch record hash differs")
        if (
            launch.get("cid") != candidate_id
            or launch.get("image") != SG_IMAGE
            or launch.get("model") != SG_MODEL
            or launch.get("model_sha") != SG_MODEL_REVISION
            or launch.get("profile_sha256") != SG_PROFILE_SHA256
            or launch.get("receipt_sha256") != receipt_sha
            or state.get("candidate_name") != "qwen38fn-" + str(launch.get("nonce"))
            or policy.get("image_id") != SG_IMAGE
            or policy.get("model") != SG_MODEL
            or policy.get("model_revision") != SG_MODEL_REVISION
            or policy.get("profile_sha256") != SG_PROFILE_SHA256
            or policy.get("context_length") != 32768
            or "127.0.0.1:30080:30000" not in launch.get("argv", [])
        ):
            raise PersonalRuntimeError("SGLang runtime identity differs")
        passive = heartbeat.get("passive_models_heartbeat")
        passive_identity = {"id": SG_MODEL, "max_model_len": 32768}
        passive_identity_sha = hashlib.sha256(
            json.dumps(
                passive_identity, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode()
        ).hexdigest()
        if phase == "ready" and (
            not isinstance(passive, dict)
            or passive.get("schema") != "flash-sglang-passive-model-heartbeat/v1"
            or passive.get("kind") != "passive_models_identity"
            or passive.get("status") != 200
            or passive.get("models") != [SG_MODEL]
            or passive.get("max_model_len") != 32768
            or passive.get("identity_projection") != passive_identity
            or passive.get("canonical_identity_sha256") != passive_identity_sha
        ):
            raise PersonalRuntimeError("SGLang ready heartbeat identity differs")
        if _read_regular(root, "state.json", "SGLang state recheck")[0] != state_raw:
            raise PersonalRuntimeError("SGLang state changed during admission")
        return _Result(
            "active",
            _projection(
                observed=observed, endpoint="sglang", run_id=root.name, phase=phase,
                candidate_id=candidate_id,
                source_parts={
                    "state": state_raw, "heartbeat": heartbeat_raw,
                    "policy": policy_raw, "guard_process": process_raw,
                    "launch_record": launch_raw, "process": "\0".join(argv).encode(),
                },
            ),
        )
    except (OSError, PersonalRuntimeError, ValueError, TypeError, AttributeError) as exc:
        return _Result("invalid", error=str(exc))


def maybe_project_personal(
    *,
    mia_root: Path | None = None,
    mia_base: Path = BASE,
    sglang_root: Path | None = None,
    sglang_base: Path = SGLANG_RUNTIME_ROOT,
    proc_root: Path = PROC_ROOT,
    observed: datetime | None = None,
) -> dict[str, Any] | None:
    """Return an active/invalid personal overlay, or ``None`` when restored/absent."""
    current = (observed or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if mia_root is None:
        mia_roots, mia_discovery_error = _discover_mia_sessions(mia_base)
    else:
        mia_roots = [mia_root]
        mia_discovery_error = None
    if sglang_root is None:
        sglang_roots, sglang_discovery_error = _discover_sglang_sessions(sglang_base)
    else:
        sglang_roots = [sglang_root]
        sglang_discovery_error = None
    results = [*(_mia(root, proc_root, current) for root in mia_roots)]
    results.extend(_sglang(root, proc_root, current) for root in sglang_roots)
    active = [row.projection for row in results if row.status == "active"]
    invalid = [row.error for row in results if row.status == "invalid"]
    terminal_invalid = [row.error for row in results if row.status == "terminal_invalid"]
    invalid.extend(
        error
        for error in (mia_discovery_error, sglang_discovery_error)
        if error is not None
    )
    if len(active) > 1:
        return _unknown(current, "multiple fixed personal sessions claim the runtime")
    if invalid:
        return _unknown(current, "personal session state is stale, ambiguous, or untrusted")
    # A newer, process-bound active session supersedes an old terminal failure.
    # With no active owner, the failed restoration remains fail-closed.
    if terminal_invalid and not active:
        return _unknown(current, "personal session terminal restoration is untrusted")
    return active[0] if active else None


__all__ = [
    "MIA_SESSION_ROOT",
    "SGLANG_RUNTIME_ROOT",
    "SGLANG_SESSION_ROOT",
    "maybe_project_personal",
]
