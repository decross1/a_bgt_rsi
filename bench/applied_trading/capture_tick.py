"""One-study public Spot capture tick; timer activation is a separate step.

After a verified stale cursor, the timer may archive the old state, record an
unobserved gap, and bootstrap a NEW independent BTCUSDT lineage from venue
tail. It never chooses a cursor by timestamp or repairs a failed branch. The
three canonical Spark leases are read under nonblocking shared flocks and held
through one bounded capture, so a live model/weekly/coordinator lease causes an
immutable skipped tick. No account, model request, or order surface is present.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import signal
import stat
import time
import uuid
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from pathlib import Path

from bench.applied_trading import hourly_capture as continuation
from bench.applied_trading import public_spot_capture as collector
from bench.applied_trading.collection_projection import _read_relative

SCHEMA = "applied-trial-h1-capture-tick/v1"
STATE_SCHEMA = "applied-trial-h1-capture-tick-state/v1"
GAP_SCHEMA = "applied-trial-h1-capture-lineage-gap/v1"
SYMBOL = "BTCUSDT"
CAPTURE_ROOT = continuation.CAPTURE_ROOT
SCHEDULER_ROOT = CAPTURE_ROOT / "_scheduler"
CANONICAL_REPO = Path("/home/decross1/projects/a_bgt_rsi")
LOCK_NAMES = (
    ".weekly-upgrade-execution.lock",
    ".coordinator-cron.lock",
    ".weekly-upgrade-gpu.lock",
)
TICK_MAX_WALL_S = 90
BOOTSTRAP_MAX_WALL_S = 150
MAX_PREDECESSOR_AGE_S = 900
TRANSIENT_GET_COOLDOWN_S = 600
STATE_MAX_BYTES = 16_384
MAX_PAGES = 8
REGISTERED_COLLECTOR_SHA256 = "4310f64e61cb9b50c80f55f9e4d41557081ff99ad956420050a23be249315037"
REGISTERED_CONTINUATION_SHA256 = "0db474ec40a10c986c44f3c8639bc056f49793a188ff0d94c6d450a3b7f040bf"
STATE_KEYS = frozenset({
    "schema", "symbol", "collector_source_sha256", "continuation_source_sha256",
    "lineage_id", "mode", "bootstrap_warmup_path", "last_complete_path",
    "last_complete_sha256", "attempt_output_path", "blocked_reason", "updated_at",
})


class TickError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canon(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode() + b"\n"


def _utc(value: object) -> datetime:
    if not isinstance(value, str):
        raise TickError("receipt time is not UTC text")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TickError("receipt time is malformed") from exc
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        raise TickError("receipt time is not UTC")
    return parsed.astimezone(timezone.utc)


def _source_sha() -> str:
    actual = _actual_collector_sha()
    if actual != REGISTERED_COLLECTOR_SHA256:
        raise TickError("collector source differs from reviewed one-study registration")
    return actual


def _continuation_sha() -> str:
    actual = _actual_continuation_sha()
    if actual != REGISTERED_CONTINUATION_SHA256:
        raise TickError("continuation source differs from reviewed one-study registration")
    return actual


def _actual_collector_sha() -> str:
    return _sha(Path(collector.__file__).read_bytes())


def _actual_continuation_sha() -> str:
    return _sha(Path(continuation.__file__).read_bytes())


def _registered_sources_present() -> bool:
    return (_actual_collector_sha() == REGISTERED_COLLECTOR_SHA256
            and _actual_continuation_sha() == REGISTERED_CONTINUATION_SHA256)


def _fixed_dir(path: Path) -> None:
    if path.is_symlink() or not path.is_dir() or path.resolve() != path.absolute():
        raise TickError("registered capture/scheduler directory is redirected")


def _ensure_scheduler() -> None:
    _fixed_dir(CAPTURE_ROOT)
    if not SCHEDULER_ROOT.exists():
        SCHEDULER_ROOT.mkdir(mode=0o700)
    _fixed_dir(SCHEDULER_ROOT)
    for child in ("ticks", "abandoned", "gaps"):
        directory = SCHEDULER_ROOT / child
        if not directory.exists():
            directory.mkdir(mode=0o700)
        _fixed_dir(directory)


def _read_regular(path: Path, limit: int = STATE_MAX_BYTES) -> bytes:
    flags = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                           | getattr(os, "O_CLOEXEC", 0))
    try:
        fd = os.open(path.name, flags, dir_fd=directory_fd)
    except BaseException:
        os.close(directory_fd)
        raise
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            raise TickError("scheduler input is nonregular or oversized")
        parts = []
        remaining = limit + 1
        while remaining:
            part = os.read(fd, min(remaining, 65_536))
            if not part:
                break
            parts.append(part)
            remaining -= len(part)
        raw = b"".join(parts)
        after = os.fstat(fd)
        if len(raw) != before.st_size or len(raw) > limit or (
                before.st_size, before.st_ino, before.st_mtime_ns) != (
                after.st_size, after.st_ino, after.st_mtime_ns):
            raise TickError("scheduler input changed during read")
        return raw
    finally:
        os.close(fd)
        os.close(directory_fd)


def _state() -> tuple[dict | None, str | None]:
    path = SCHEDULER_ROOT / "state.json"
    if not path.exists() and not path.is_symlink():
        return None, None
    raw = _read_regular(path)
    value = collector.strict_json(raw)
    if not isinstance(value, dict) or set(value) != STATE_KEYS or value.get("schema") != STATE_SCHEMA:
        raise TickError("capture state has an unknown schema")
    if (value.get("symbol") != SYMBOL
            or not all(isinstance(value.get(key), str) and len(value[key]) == 64
                       for key in ("collector_source_sha256", "continuation_source_sha256"))
            or not isinstance(value.get("lineage_id"), str)
            or not value["lineage_id"].startswith("h1-")
            or any(value.get(key) is not None and not isinstance(value[key], str)
                   for key in ("bootstrap_warmup_path", "last_complete_path",
                               "last_complete_sha256", "attempt_output_path",
                               "blocked_reason"))):
        raise TickError("capture state source/symbol is malformed")
    if value.get("mode") not in {"attempting", "active", "blocked"}:
        raise TickError("capture state mode is unknown")
    _utc(value["updated_at"])
    if value["mode"] == "active" and (
            value["last_complete_path"] is None or value["last_complete_sha256"] is None
            or value["attempt_output_path"] is not None):
        raise TickError("active capture state has no exact sealed predecessor")
    return value, _sha(raw)


def _write_new(path: Path, raw: bytes) -> None:
    directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                           | getattr(os, "O_CLOEXEC", 0))
    try:
        fd = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                     | getattr(os, "O_CLOEXEC", 0), 0o600, dir_fd=directory_fd)
    except BaseException:
        os.close(directory_fd)
        raise
    try:
        view = memoryview(raw)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise TickError("scheduler receipt write failed")
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
        os.close(directory_fd)


def _replace_state(value: dict) -> None:
    path = SCHEDULER_ROOT / "state.json"
    temporary = SCHEDULER_ROOT / f".state-{uuid.uuid4().hex}.tmp"
    _write_new(temporary, _canon(value))
    directory_fd = os.open(SCHEDULER_ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.replace(temporary.name, path.name,
                   src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _tick_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "-" + uuid.uuid4().hex[:8]


def _receipt(*, tick_id: str, started_at: str, status: str, reason: str | None,
             requests_attempted: int | None = 0, batch: dict | None = None,
             extra_batch: dict | None = None, batch_path: Path | None = None,
             lineage_id: str | None = None,
             gap_relpath: str | None = None) -> dict:
    succeeded = (batch["requests_succeeded"] + (extra_batch["requests_succeeded"]
                 if extra_batch else 0)) if batch else (
                     0 if requests_attempted == 0 else None)
    failed = (batch["requests_failed"] + (extra_batch["requests_failed"]
              if extra_batch else 0)) if batch else (
                  0 if requests_attempted == 0 else None)
    verified = (bool(batch.get("attempt_denominator_verified") is True
                     and (extra_batch is None or extra_batch.get(
                         "attempt_denominator_verified") is True))
                if batch else requests_attempted == 0)
    return {"schema": SCHEMA, "tick_id": tick_id, "symbol": SYMBOL,
            "lineage_id": lineage_id,
            "collector_source_sha256": _actual_collector_sha(),
            "continuation_source_sha256": _actual_continuation_sha(),
            "registered_sources_present": _registered_sources_present(),
            "started_at": started_at, "finished_at": _now(),
            "status": status, "reason": reason,
            "gap_relpath": gap_relpath,
            "requests_attempted": requests_attempted,
            "batch_path": str(batch_path) if batch_path else None,
            "batch_sha256": (_sha(_read_relative(batch_path, "capture-batch.json", 32_000))
                             if batch_path and batch else None),
            "requests_succeeded": succeeded,
            "requests_failed": failed,
            "attempt_denominator_verified": bool(verified and requests_attempted
                == succeeded + failed) if succeeded is not None and failed is not None
                else False,
            "source_valid_batch": bool(batch and batch.get("status")
                                       == "complete_incremental_batch"),
            "feature_build": "deferred_separate_closed_hour_job",
            "orders_placed": 0, "credentials_used": False}


def _persist_tick(row: dict) -> None:
    target = SCHEDULER_ROOT / "ticks" / f"{row['tick_id']}.json"
    _write_new(target, _canon(row))


@contextmanager
def _scheduler_lock():
    path = SCHEDULER_ROOT / "capture-tick.lock"
    directory_fd = os.open(SCHEDULER_ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                           | getattr(os, "O_CLOEXEC", 0))
    try:
        fd = os.open(path.name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW
                     | getattr(os, "O_CLOEXEC", 0), 0o600, dir_fd=directory_fd)
    except BaseException:
        os.close(directory_fd)
        raise
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > 4_096:
            raise TickError("scheduler lock is nonregular or oversized")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise TickError("another capture tick holds the scheduler lock") from exc
        yield
    finally:
        os.close(fd)
        os.close(directory_fd)


@contextmanager
def _idle_leases():
    """Read-only SH flocks cooperate with the exact canonical EX leases."""
    run_state = CANONICAL_REPO / "run_state"
    if run_state.is_symlink() or not run_state.is_dir():
        yield "canonical_run_state_unavailable"
        return
    pause = SCHEDULER_ROOT / "pause_capture"
    if pause.exists() or pause.is_symlink():
        yield "operator_pause_capture"
        return
    handles: list[int] = []
    reason = None
    run_state_fd = None
    try:
        run_state_fd = os.open(run_state, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                               | getattr(os, "O_CLOEXEC", 0))
        for name in LOCK_NAMES:
            path = run_state / name
            if path.is_symlink() or not path.is_file():
                reason = f"missing_or_redirected_lease:{name}"
                break
            fd = os.open(name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW
                         | getattr(os, "O_CLOEXEC", 0), dir_fd=run_state_fd)
            handles.append(fd)
            info = os.fstat(fd)
            current = os.stat(name, dir_fd=run_state_fd, follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode) or info.st_size > 4_096 or (
                    info.st_dev, info.st_ino) != (current.st_dev, current.st_ino):
                reason = f"invalid_lease:{name}"
                break
            try:
                fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError:
                reason = f"research_lease_busy:{name}"
                break
    except OSError:
        reason = "research_lease_unreadable"
    try:
        yield reason
    finally:
        for fd in reversed(handles):
            os.close(fd)
        if run_state_fd is not None:
            os.close(run_state_fd)


def _capture_child() -> Path:
    for _ in range(4):
        child = CAPTURE_ROOT / ("spot-BTCUSDT-"
                + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
        if not child.exists() and not child.is_symlink():
            return child
        time.sleep(1)
    raise TickError("unique direct-child capture name could not be reserved")


def _batch(path: Path) -> tuple[dict, str]:
    checked, view, digest = continuation._verified_batch(path, CAPTURE_ROOT)
    if (view.get("attempt_denominator_verified") is not True
            or view.get("requests_unjournaled") != 0
            or checked.get("collector_source_sha256") != _source_sha()):
        raise TickError("candidate capture has unjournaled GETs or source drift")
    return checked, digest


def _fixed_capture(path_text: object) -> Path:
    if not isinstance(path_text, str):
        raise TickError("capture pointer is not a fixed path")
    path = Path(path_text)
    if not path.is_absolute():
        raise TickError("capture pointer is relative")
    return continuation._fixed_child(path, CAPTURE_ROOT)


def _signal_timeout(_signal: int, _frame: object) -> None:
    raise TimeoutError("capture tick wall deadline")


@contextmanager
def _deadline(seconds: int):
    previous = signal.signal(signal.SIGALRM, _signal_timeout)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def _attempt_state(*, lineage_id: str, output: Path, warmup: Path | None,
                   predecessor: Path | None) -> dict:
    return {"schema": STATE_SCHEMA, "symbol": SYMBOL,
            "collector_source_sha256": _source_sha(),
            "continuation_source_sha256": _continuation_sha(),
            "lineage_id": lineage_id,
            "mode": "attempting", "bootstrap_warmup_path": str(warmup) if warmup else None,
            "last_complete_path": str(predecessor) if predecessor else None,
            "last_complete_sha256": None,
            "attempt_output_path": str(output), "blocked_reason": None,
            "updated_at": _now()}


def _blocked(state: dict, reason: str) -> dict:
    return {**state, "mode": "blocked", "blocked_reason": reason,
            "updated_at": _now()}


def _sealed_transient_get(state: dict) -> dict | None:
    """Classify one sealed recoverable GET-unavailability branch; never retry it.

    Literal URLError does not expose its underlying reason in the journal, so
    its cause remains unknown. Fresh bootstrap keeps the same HTTPS/TLS checks.
    Redirects, HTTP 4xx, schema and response failures, cursor gaps, truncated
    journals and interrupted/unsealed children remain blocked.
    """
    if (state["mode"] != "blocked" or state["blocked_reason"] not in {
            "continuation_failed:TickError", "bootstrap_failed:TickError"}
            or state["attempt_output_path"] is None):
        return None
    try:
        child = _fixed_capture(state["attempt_output_path"])
        failed, failed_sha = _batch(child)
        if (failed["status"] != "incomplete" or failed["requests_failed"] != 1
                or failed["requests_attempted"] != (
                    failed["requests_succeeded"] + failed["requests_failed"])
                or failed["attempt_denominator_verified"] is not True
                or failed["failure"] is None or failed["cursor_gap"]
                or failed["page_gap"]):
            return None
        journal = _read_relative(child, "attempts.jsonl", 128_000)
        last = collector.strict_json(journal.splitlines()[-1])
        if (last["attempt_status"] != "failed" or last["raw_relpath"] is not None
                or last["raw_sha256"] is not None or last["raw_bytes"] != 0):
            return None
        recoverable = (
            last["failure_stage"] == "transport"
            and last["failure_code"] in {"TimeoutError", "URLError"}
            and last["http_status"] is None
        ) or (
            last["failure_stage"] == "http_contract"
            and last["failure_code"] == "HTTPError"
            and type(last["http_status"]) is int
            and 500 <= last["http_status"] <= 599
        )
        if not recoverable:
            return None
        failed_at = _utc(last["response_received_at"])
        failed_seal = _utc(failed["sealed_at"])
        current = datetime.now(timezone.utc)
        if failed_seal < failed_at or failed_seal > current or failed_at > current:
            return None
        old_sealed_at = None
        if state["last_complete_path"] is not None:
            predecessor = _fixed_capture(state["last_complete_path"])
            previous, previous_sha = _batch(predecessor)
            if (previous["status"] != "complete_incremental_batch"
                    or previous_sha != state["last_complete_sha256"]
                    or failed["from_aggregate_id"] != previous["next_aggregate_id"]
                    or _utc(previous["sealed_at"]) > _utc(failed["started_at"])):
                return None
            report = collector.strict_json(_read_relative(child, "continuation.json", 32_000))
            if (report["schema"] != continuation.SCHEMA
                    or report["status"] != "stopped_incomplete"
                    or report["previous_batch_path"] != str(predecessor)
                    or report["previous_batch_sha256"] != previous_sha
                    or report["batch_sha256"] != failed_sha
                    or report["from_aggregate_id"] != previous["next_aggregate_id"]
                    or report["collector_source_sha256"] != _source_sha()
                    or report["continuation_source_sha256"] != _continuation_sha()
                    or report["current_requests"] != {
                        key: failed[f"requests_{key}"]
                        for key in ("attempted", "succeeded", "failed")
                    }
                    or report["orders_placed"] != 0
                    or report["credentials_used"] is not False):
                return None
            old_sealed_at = previous["sealed_at"]
        elif state["bootstrap_warmup_path"] is not None:
            warmup = _fixed_capture(state["bootstrap_warmup_path"])
            warmup_batch, _ = _batch(warmup)
            if (warmup_batch["status"] != "incomplete"
                    or warmup_batch["initial_history_gap"] is not True
                    or warmup_batch["failure"] is not None
                    or warmup_batch["requests_failed"] != 0
                    or failed["from_aggregate_id"] != warmup_batch["next_aggregate_id"]
                    or _utc(warmup_batch["sealed_at"]) > _utc(failed["started_at"])):
                return None
        elif failed["from_aggregate_id"] is not None:
            return None
        return {
            "failed_output_path": str(child), "failed_batch_sha256": failed_sha,
            "failed_attempt_record_sha256": last["record_sha256"],
            "failed_request_received_at": last["response_received_at"],
            "failed_request_kind": last["kind"],
            "failed_http_status": last["http_status"],
            "failed_failure_code": last["failure_code"],
            "failed_cause_class": (
                "sealed_transport_unavailability_unknown"
                if last["failure_code"] == "URLError" else
                "sealed_timeout_or_http5xx_unavailability"
            ),
            "failed_requests_attempted": failed["requests_attempted"],
            "failed_backlog_unresolved": failed["backlog_unresolved"],
            "old_sealed_at": old_sealed_at,
        }
    except (TickError, collector.CaptureError, OSError, ValueError,
            KeyError, IndexError, TypeError):
        return None


def bootstrap_new(*, abandon_state_sha256: str | None = None,
                  max_wall_s: int = BOOTSTRAP_MAX_WALL_S,
                  _held_lock: bool = False,
                  _verified_stale_gap: dict | None = None,
                  _verified_transient_gap: dict | None = None) -> dict:
    """Restart from venue tail, archiving any exactly reviewed old branch."""
    if type(max_wall_s) is not int or not 60 <= max_wall_s <= BOOTSTRAP_MAX_WALL_S:
        raise TickError("bootstrap wall cap differs from registered 60..150 seconds")
    if _verified_stale_gap is not None and _verified_transient_gap is not None:
        raise TickError("only one registered lineage-gap cause is allowed")
    if (_verified_stale_gap is not None or _verified_transient_gap is not None) and not _held_lock:
        raise TickError("auto-new lineage requires the already-held scheduler and idle leases")
    _ensure_scheduler()
    started, tick_id = _now(), _tick_id()
    scheduler_context = nullcontext() if _held_lock else _scheduler_lock()
    lease_context = nullcontext(None) if _held_lock else _idle_leases()
    with scheduler_context, lease_context as lease_reason:
        if lease_reason:
            row = _receipt(tick_id=tick_id, started_at=started,
                           status="skipped_busy", reason=lease_reason)
            _persist_tick(row)
            return row
        prior, prior_sha = _state()
        if not _registered_sources_present():
            row = _receipt(tick_id=tick_id, started_at=started,
                           status="blocked", reason="registered_source_drift",
                           lineage_id=prior["lineage_id"] if prior else None)
            _persist_tick(row)
            if prior is not None:
                _replace_state(_blocked(prior, "registered_source_drift"))
            return row
        if _verified_stale_gap is not None and (
            prior is None or prior["mode"] != "active"
            or abandon_state_sha256 != prior_sha
            or set(_verified_stale_gap) != {
                "old_lineage_id", "old_state_sha256", "old_batch_sha256",
                "old_sealed_at",
            }
            or _verified_stale_gap["old_lineage_id"] != prior["lineage_id"]
            or _verified_stale_gap["old_state_sha256"] != prior_sha
            or _verified_stale_gap["old_batch_sha256"]
            != prior["last_complete_sha256"]
        ):
            raise TickError("auto-new lineage has no exact verified stale predecessor")
        if _verified_transient_gap is not None and (
            prior is None or prior["mode"] != "blocked"
            or abandon_state_sha256 != prior_sha
            or set(_verified_transient_gap) != {
                "failed_output_path", "failed_batch_sha256",
                "failed_attempt_record_sha256", "failed_request_received_at",
                "failed_request_kind", "failed_http_status",
                "failed_failure_code", "failed_requests_attempted",
                "failed_cause_class", "failed_backlog_unresolved",
                "old_sealed_at",
            }
            or _verified_transient_gap["failed_output_path"]
                != prior["attempt_output_path"]
            or _sealed_transient_get(prior) != _verified_transient_gap
            or (datetime.now(timezone.utc)
                - _utc(_verified_transient_gap["failed_request_received_at"])
                ).total_seconds() < TRANSIENT_GET_COOLDOWN_S
        ):
            raise TickError("auto-new lineage has no exact cooled transient GET branch")
        if prior is not None:
            if abandon_state_sha256 != prior_sha:
                raise TickError("new lineage needs exact prior state SHA acknowledgment")
            old_state_raw = _read_regular(SCHEDULER_ROOT / "state.json")
            abandoned = SCHEDULER_ROOT / "abandoned" / f"state-{prior_sha}.json"
            try:
                _write_new(abandoned, old_state_raw)
            except FileExistsError:
                if _read_regular(abandoned) != old_state_raw:
                    raise TickError("old lineage archive differs from exact state bytes")
        elif abandon_state_sha256 is not None:
            raise TickError("no prior capture state exists to acknowledge")
        lineage_id = "h1-" + tick_id
        gap_relpath = None
        if _verified_stale_gap is not None or _verified_transient_gap is not None:
            gap_relpath = f"gaps/gap-{tick_id}.json"
            gap = {
                "schema": GAP_SCHEMA,
                "reason": (
                    "verified_stale_cursor_new_lineage" if _verified_stale_gap else
                    "verified_transport_unavailability_unknown_new_lineage_after_cooldown"
                    if _verified_transient_gap["failed_cause_class"]
                    == "sealed_transport_unavailability_unknown" else
                    "verified_timeout_or_http5xx_new_lineage_after_cooldown"
                ),
                "old_lineage_id": prior["lineage_id"],
                "new_lineage_id": lineage_id,
                "old_state_sha256": prior_sha,
                "old_batch_sha256": (_verified_stale_gap["old_batch_sha256"]
                                     if _verified_stale_gap else prior["last_complete_sha256"]),
                "unobserved_after_old_seal_at": (
                    _verified_stale_gap["old_sealed_at"] if _verified_stale_gap
                    else _verified_transient_gap["old_sealed_at"]),
                "new_bootstrap_started_at": started,
                "collector_source_sha256": _source_sha(),
                "continuation_source_sha256": _continuation_sha(),
                "gap_is_explicit": True, "cursor_linked_across_gap": False,
                "requests_attempted_before_gap_receipt": (
                    0 if _verified_stale_gap else
                    _verified_transient_gap["failed_requests_attempted"]),
                "orders_placed": 0,
            }
            if _verified_transient_gap is not None:
                gap["failed_branch"] = _verified_transient_gap
            _write_new(SCHEDULER_ROOT / gap_relpath, _canon(gap))
        warmup_path = _capture_child()
        state = _attempt_state(lineage_id=lineage_id, output=warmup_path,
                               warmup=None, predecessor=None)
        _replace_state(state)  # A kill now leaves an orphan attempt, not an active cursor.
        second_path = None
        warmup = None
        current = None
        warmup_verified = False
        current_verified = False
        try:
            with _deadline(max_wall_s):
                warmup = collector.capture_once(warmup_path, symbol=SYMBOL,
                                                from_id=None, max_pages=1)
                checked_warmup, _ = _batch(warmup_path)
                warmup_verified = True
                if (checked_warmup.get("status") != "incomplete"
                        or checked_warmup.get("initial_history_gap") is not True
                        or checked_warmup.get("failure") is not None
                        or checked_warmup.get("requests_failed") != 0
                        or type(checked_warmup.get("next_aggregate_id")) is not int):
                    raise TickError("new warmup has no clean venue-tail cursor")
                second_path = _capture_child()
                state["attempt_output_path"] = str(second_path)
                state["bootstrap_warmup_path"] = str(warmup_path)
                _replace_state(state)
                current = collector.capture_once(
                    second_path, symbol=SYMBOL,
                    from_id=checked_warmup["next_aggregate_id"], max_pages=MAX_PAGES)
                checked_current, current_sha = _batch(second_path)
                current_verified = True
                if (checked_current.get("status") != "complete_incremental_batch"
                        or checked_current.get("from_aggregate_id")
                           != checked_warmup["next_aggregate_id"]
                        or checked_current.get("failure") is not None
                        or checked_current.get("requests_failed") != 0
                        or checked_current.get("cursor_gap")
                        or checked_current.get("page_gap")
                        or checked_current.get("backlog_unresolved")):
                    raise TickError("fresh incremental batch did not close the bootstrap")
            row = _receipt(tick_id=tick_id, started_at=started,
                           status="bootstrapped_complete", reason=None,
                           requests_attempted=(warmup["requests_attempted"]
                                               + current["requests_attempted"]),
                           batch=current, extra_batch=warmup,
                           batch_path=second_path,
                           lineage_id=lineage_id,
                           gap_relpath=gap_relpath)
            _persist_tick(row)
            _replace_state({**state, "mode": "active", "last_complete_path": str(second_path),
                            "last_complete_sha256": current_sha,
                            "attempt_output_path": None, "updated_at": _now()})
            return row
        except Exception as exc:  # noqa: BLE001 - journal every capture failure
            both_sealed = warmup_verified and current_verified
            row = _receipt(tick_id=tick_id, started_at=started,
                           status="blocked", reason="bootstrap_failed:" + type(exc).__name__,
                           requests_attempted=(warmup["requests_attempted"]
                                               + current["requests_attempted"]
                                               if both_sealed
                                               else None),
                           batch=current if both_sealed else None,
                           extra_batch=warmup if both_sealed else None,
                           batch_path=second_path if both_sealed else None,
                           lineage_id=lineage_id,
                           gap_relpath=gap_relpath)
            _persist_tick(row)
            _replace_state(_blocked(state, row["reason"]))
            return row


def run_once(*, max_wall_s: int = TICK_MAX_WALL_S) -> dict:
    if type(max_wall_s) is not int or not 30 <= max_wall_s <= TICK_MAX_WALL_S:
        raise TickError("tick wall cap differs from registered 30..90 seconds")
    _ensure_scheduler()
    started, tick_id = _now(), _tick_id()
    with _scheduler_lock(), _idle_leases() as lease_reason:
        if lease_reason:
            row = _receipt(tick_id=tick_id, started_at=started,
                           status="skipped_busy", reason=lease_reason)
            _persist_tick(row)
            return row
        state, state_sha = _state()
        if not _registered_sources_present():
            row = _receipt(tick_id=tick_id, started_at=started,
                           status="blocked", reason="registered_source_drift",
                           lineage_id=state["lineage_id"] if state else None)
            _persist_tick(row)
            if state is not None:
                _replace_state(_blocked(state, "registered_source_drift"))
            return row
        if state is None:
            row = _receipt(tick_id=tick_id, started_at=started,
                           status="blocked", reason="manual_new_lineage_required")
            _persist_tick(row)
            return row
        if (state["collector_source_sha256"] != _source_sha()
                or state["continuation_source_sha256"] != _continuation_sha()):
            row = _receipt(tick_id=tick_id, started_at=started,
                           status="blocked", reason="collector_source_drift",
                           lineage_id=state["lineage_id"])
            _persist_tick(row)
            _replace_state(_blocked(state, "collector_source_drift"))
            return row
        if state["mode"] != "active":
            if state["mode"] == "blocked" and state_sha is not None:
                failed = _sealed_transient_get(state)
                if failed is not None:
                    age = (datetime.now(timezone.utc)
                           - _utc(failed["failed_request_received_at"])).total_seconds()
                    if age < TRANSIENT_GET_COOLDOWN_S or max_wall_s < 60:
                        row = _receipt(
                            tick_id=tick_id, started_at=started,
                            status="skipped_get_unavailability_cooldown",
                            reason=("sealed_get_unavailability_cooldown" if age < TRANSIENT_GET_COOLDOWN_S
                                    else "auto_new_lineage_needs_at_least_60s"),
                            lineage_id=state["lineage_id"])
                        _persist_tick(row)
                        return row
                    return bootstrap_new(
                        abandon_state_sha256=state_sha, max_wall_s=max_wall_s,
                        _held_lock=True, _verified_transient_gap=failed)
            row = _receipt(tick_id=tick_id, started_at=started,
                           status="blocked", reason="prior_lineage_" + state["mode"],
                           requests_attempted=None if state["mode"] == "attempting" else 0,
                           lineage_id=state["lineage_id"])
            _persist_tick(row)
            if state["mode"] == "attempting":
                _replace_state(_blocked(state, "interrupted_prior_tick"))
            return row
        predecessor = _fixed_capture(state["last_complete_path"])
        try:
            previous, previous_sha = _batch(predecessor)
            if previous.get("status") != "complete_incremental_batch" or (
                    previous_sha != state["last_complete_sha256"]):
                raise TickError("last cursor pointer differs from its sealed batch")
            age = (datetime.now(timezone.utc) - _utc(previous["sealed_at"])).total_seconds()
            if age < 0:
                raise TickError("lineage cursor seal is in the future")
            if age > MAX_PREDECESSOR_AGE_S:
                # Only a source-matched, exactly sealed active predecessor may
                # cause a new independent venue-tail lineage. No old cursor is
                # passed to the new warmup; the missing interval is journaled
                # before the first new GET while these leases remain held.
                if state_sha is None:
                    raise TickError("verified stale state has no raw SHA")
                if max_wall_s < 60:
                    row = _receipt(
                        tick_id=tick_id, started_at=started,
                        status="skipped_short_wall_cap",
                        reason="auto_new_lineage_needs_at_least_60s",
                        lineage_id=state["lineage_id"])
                    _persist_tick(row)
                    return row
                return bootstrap_new(
                    abandon_state_sha256=state_sha,
                    max_wall_s=max_wall_s,
                    _held_lock=True,
                    _verified_stale_gap={
                        "old_lineage_id": state["lineage_id"],
                        "old_state_sha256": state_sha,
                        "old_batch_sha256": previous_sha,
                        "old_sealed_at": previous["sealed_at"],
                    })
        except (TickError, OSError, ValueError, KeyError) as exc:
            _replace_state(_blocked(state, "predecessor_invalid_or_stale:" + type(exc).__name__))
            row = _receipt(tick_id=tick_id, started_at=started, status="blocked",
                           reason="predecessor_invalid_or_stale:" + type(exc).__name__,
                           lineage_id=state["lineage_id"])
            _persist_tick(row)
            return row
        warmup = (_fixed_capture(state["bootstrap_warmup_path"])
                  if state.get("bootstrap_warmup_path") else None)
        output = _capture_child()
        attempting = _attempt_state(lineage_id=state["lineage_id"], output=output,
                                    warmup=warmup, predecessor=predecessor)
        attempting["last_complete_sha256"] = previous_sha
        _replace_state(attempting)
        batch = None
        try:
            with _deadline(max_wall_s):
                report = continuation.run_once(
                    previous_batch=predecessor, bootstrap_warmup=warmup,
                    output_dir=output, max_pages=MAX_PAGES)
                batch, batch_sha = _batch(output)
                if report.get("status") != "continued_complete" or (
                        batch.get("status") != "complete_incremental_batch"):
                    raise TickError("continuation stopped; preserve immutable failed branch")
            row = _receipt(tick_id=tick_id, started_at=started,
                           status="continued_complete", reason=None,
                           requests_attempted=batch["requests_attempted"],
                           batch=batch, batch_path=output,
                           lineage_id=state["lineage_id"])
            _persist_tick(row)
            _replace_state({**attempting, "mode": "active",
                            "bootstrap_warmup_path": None,
                            "last_complete_path": str(output),
                            "last_complete_sha256": batch_sha,
                            "attempt_output_path": None, "updated_at": _now()})
            return row
        except Exception as exc:  # noqa: BLE001 - preserve the stopped branch
            # If a child is killed before a batch is written, attempting state
            # remains and the next tick blocks instead of donating a cursor.
            if batch is None and (output / "capture-batch.json").is_file():
                try:
                    batch, _ = _batch(output)
                except (TickError, OSError, ValueError, KeyError):
                    batch = None
            reason = "continuation_failed:" + type(exc).__name__
            row = _receipt(tick_id=tick_id, started_at=started,
                           status="blocked", reason=reason,
                           requests_attempted=batch["requests_attempted"]
                           if batch else None, batch=batch,
                           batch_path=output if batch else None,
                           lineage_id=state["lineage_id"])
            _persist_tick(row)
            _replace_state(_blocked(attempting, reason))
            return row


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    choices = parser.add_mutually_exclusive_group(required=True)
    choices.add_argument("--plan", action="store_true")
    choices.add_argument("--bootstrap-new", action="store_true")
    choices.add_argument("--run-once", action="store_true")
    parser.add_argument("--abandon-state-sha256")
    parser.add_argument("--max-wall-s", type=int)
    args = parser.parse_args(argv)
    if args.plan:
        print(json.dumps({"schema": SCHEMA,
                          "mode": "manual_initial_bootstrap_then_bounded_auto_new_lineage_on_verified_stale_gap",
                          "symbol": SYMBOL, "max_pages": MAX_PAGES,
                          "tick_max_wall_s": TICK_MAX_WALL_S,
                          "bootstrap_max_wall_s": BOOTSTRAP_MAX_WALL_S,
                          "predecessor_max_age_s": MAX_PREDECESSOR_AGE_S,
                          "canonical_lease_names": LOCK_NAMES,
                          "timer_enabled": False, "orders": 0}, sort_keys=True))
        return 0
    if args.bootstrap_new:
        row = bootstrap_new(abandon_state_sha256=args.abandon_state_sha256,
                            max_wall_s=(BOOTSTRAP_MAX_WALL_S if args.max_wall_s is None
                                        else args.max_wall_s))
    else:
        if args.abandon_state_sha256 is not None:
            raise TickError("state abandonment is manual bootstrap-only")
        row = run_once(max_wall_s=(TICK_MAX_WALL_S if args.max_wall_s is None
                                   else args.max_wall_s))
    print(json.dumps({"status": row["status"], "reason": row["reason"],
                      "tick_id": row["tick_id"],
                      "requests_attempted": row["requests_attempted"]}, sort_keys=True))
    return 0 if row["status"] in {"continued_complete", "bootstrapped_complete",
                                  "skipped_busy", "skipped_get_unavailability_cooldown"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
