"""Durable weekly Spark-budget accounting for upgrade experiments.

The ledger is deliberately independent of output directories.  Every caller
that shares a journal path shares one 7,200-second allowance per UTC ISO week.
Reservations are pessimistic: an active or interrupted run is charged its full
declared maximum until a trustworthy terminal receipt says otherwise.

This module accounts for time only.  It does not acquire the cooperative GPU
lease or start a process; the dispatcher must hold that separate lease before
turning a reservation into execution.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "weekly-upgrade-budget-v1"
DEFAULT_WEEKLY_LIMIT_S = 7_200.0
MAX_JOURNAL_BYTES = 64 * 1024 * 1024

RELEASING_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})
FULL_CHARGE_TERMINAL_STATUSES = frozenset({"interrupted", "unknown"})
TERMINAL_STATUSES = RELEASING_TERMINAL_STATUSES | FULL_CHARGE_TERMINAL_STATUSES

_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class BudgetError(RuntimeError):
    """Base class for a budget contract violation."""


class BudgetCorruptionError(BudgetError):
    """The durable journal cannot be trusted and therefore fails closed."""


class BudgetExceededError(BudgetError):
    """A reservation would exceed the current UTC ISO week's allowance."""


class DuplicateRunError(BudgetError):
    """A run identifier was already recorded and may never be reused."""


class UnknownRunError(BudgetError):
    """A terminal receipt refers to no recorded reservation."""


class InvalidTransitionError(BudgetError):
    """A run cannot make the requested state transition."""


class WeekBoundaryError(BudgetError):
    """A reservation's maximum runtime can enter the next UTC ISO week."""


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise BudgetError(f"value is not canonical JSON: {exc}") from exc


def _sha256(value: Any) -> str:
    raw = value if isinstance(value, bytes) else _canonical(value)
    return hashlib.sha256(raw).hexdigest()


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BudgetError(f"{name} must be a finite non-negative number")
    try:
        result = float(value)
    except OverflowError as exc:
        raise BudgetError(f"{name} must be a finite non-negative number") from exc
    if not math.isfinite(result) or result < 0:
        raise BudgetError(f"{name} must be a finite non-negative number")
    return result


def _run_id(value: Any) -> str:
    if not isinstance(value, str) or not _RUN_ID.fullmatch(value):
        raise BudgetError(
            "run_id must be 1-128 safe ASCII characters and start alphanumeric"
        )
    return value


def _manifest_sha256(value: Any) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise BudgetError("manifest_sha256 must be 64 lowercase hexadecimal characters")
    return value


def _now(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise BudgetError("now must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(value: Any) -> datetime:
    if not isinstance(value, str):
        raise BudgetCorruptionError("event_at must be a string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BudgetCorruptionError(f"invalid event_at: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise BudgetCorruptionError("event_at must include a timezone")
    return parsed.astimezone(timezone.utc)


def _week(value: datetime) -> tuple[str, datetime, datetime]:
    utc = value.astimezone(timezone.utc)
    start = datetime(utc.year, utc.month, utc.day, tzinfo=timezone.utc) - timedelta(
        days=utc.weekday()
    )
    end = start + timedelta(days=7)
    iso_year, iso_week, _ = utc.isocalendar()
    return f"{iso_year}-W{iso_week:02d}", start, end


def _event_hash(row: dict[str, Any]) -> str:
    unsigned = dict(row)
    unsigned.pop("event_sha256", None)
    return _sha256(unsigned)


def _strict_json(raw: bytes, line_number: int) -> dict[str, Any]:
    try:
        value = json.loads(
            raw,
            parse_constant=lambda token: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON number {token}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise BudgetCorruptionError(
            f"invalid journal JSON at line {line_number}: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise BudgetCorruptionError(f"journal line {line_number} is not an object")
    if raw != _canonical(value):
        raise BudgetCorruptionError(f"journal line {line_number} is not canonical JSON")
    return value


def _require_keys(row: dict[str, Any], expected: set[str], line_number: int) -> None:
    if set(row) != expected:
        missing = sorted(expected - set(row))
        extra = sorted(set(row) - expected)
        raise BudgetCorruptionError(
            f"journal line {line_number} has invalid fields; missing={missing}, extra={extra}"
        )


class BudgetLedger:
    """A process-safe, append-only weekly budget ledger.

    ``path`` must be the one shared journal location for every weekly-upgrade
    output directory.  Run IDs are globally single-use so a crash, retry, or ISO
    week rollover cannot turn an old reservation into permission to execute it
    again.
    """

    def __init__(self, path: str | os.PathLike[str]):
        self.path = Path(path)
        self.lock_path = self.path.with_name(f"{self.path.name}.lock")
        # This is a project contract rather than caller configuration.  Making
        # it constructor-configurable would let two processes sharing one
        # journal enforce different limits.
        self.limit_s = DEFAULT_WEEKLY_LIMIT_S

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _read_events(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        if not self.path.is_file():
            raise BudgetCorruptionError(f"budget journal is not a regular file: {self.path}")
        size = self.path.stat().st_size
        if size > MAX_JOURNAL_BYTES:
            raise BudgetCorruptionError(
                f"budget journal exceeds {MAX_JOURNAL_BYTES} bytes"
            )
        raw = self.path.read_bytes()
        if not raw:
            # The module never intentionally creates an empty journal.  An
            # existing empty file can therefore only be manual damage or a
            # process dying between O_CREAT and its first durable record.
            raise BudgetCorruptionError("budget journal exists but is empty")
        if not raw.endswith(b"\n"):
            raise BudgetCorruptionError("budget journal has a partial final record")

        events: list[dict[str, Any]] = []
        previous: str | None = None
        for line_number, line in enumerate(raw.splitlines(), start=1):
            if not line:
                raise BudgetCorruptionError(f"blank journal record at line {line_number}")
            row = _strict_json(line, line_number)
            common = {
                "schema_version", "sequence", "event", "event_at", "week_id",
                "run_id", "manifest_sha256", "previous_event_sha256", "event_sha256",
            }
            event_type = row.get("event")
            if event_type == "reserve":
                _require_keys(row, common | {"reserved_s"}, line_number)
            elif event_type == "finish":
                _require_keys(
                    row,
                    common | {"reserved_s", "elapsed_s", "charged_s", "status"},
                    line_number,
                )
            elif event_type == "debit":
                _require_keys(row, common | {"elapsed_s", "charged_s", "status"}, line_number)
            else:
                raise BudgetCorruptionError(
                    f"invalid event type at line {line_number}: {event_type!r}"
                )

            if row["schema_version"] != SCHEMA_VERSION:
                raise BudgetCorruptionError(f"invalid schema_version at line {line_number}")
            if type(row["sequence"]) is not int or row["sequence"] != line_number:
                raise BudgetCorruptionError(f"invalid sequence at line {line_number}")
            if row["previous_event_sha256"] != previous:
                raise BudgetCorruptionError(f"broken hash chain at line {line_number}")
            if not isinstance(row["event_sha256"], str) or row["event_sha256"] != _event_hash(row):
                raise BudgetCorruptionError(f"invalid event hash at line {line_number}")
            try:
                _run_id(row["run_id"])
                _manifest_sha256(row["manifest_sha256"])
            except BudgetError as exc:
                raise BudgetCorruptionError(
                    f"invalid identifier at line {line_number}: {exc}"
                ) from exc
            event_time = _parse_iso(row["event_at"])
            week_id, _, _ = _week(event_time)
            # A finish can honestly arrive after the week boundary.  It remains
            # attributed to the reservation week and is checked against that
            # reservation by _states below.
            if event_type in {"reserve", "debit"} and row["week_id"] != week_id:
                raise BudgetCorruptionError(
                    f"week_id does not match event_at at line {line_number}"
                )
            for field in ("reserved_s", "elapsed_s", "charged_s"):
                if field in row:
                    try:
                        _number(row[field], field)
                    except BudgetError as exc:
                        raise BudgetCorruptionError(
                            f"invalid {field} at line {line_number}: {exc}"
                        ) from exc
            if (
                event_type == "finish"
                and (not isinstance(row["status"], str) or row["status"] not in TERMINAL_STATUSES)
            ):
                raise BudgetCorruptionError(f"invalid finish status at line {line_number}")
            if event_type == "debit" and row["status"] != "imported":
                raise BudgetCorruptionError(f"invalid debit status at line {line_number}")
            previous = row["event_sha256"]
            events.append(row)

        # Transition and derived-value validation is part of corruption checking.
        self._states(events)
        return events

    def _states(self, events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        states: dict[str, dict[str, Any]] = {}
        for line_number, row in enumerate(events, start=1):
            run_id = row["run_id"]
            event_type = row["event"]
            if event_type in {"reserve", "debit"} and run_id in states:
                raise BudgetCorruptionError(f"duplicate run_id at line {line_number}: {run_id}")
            if event_type == "reserve":
                reserved_s = float(row["reserved_s"])
                event_time = _parse_iso(row["event_at"])
                _, _, week_end = _week(event_time)
                try:
                    maximum_end = event_time + timedelta(seconds=reserved_s)
                except OverflowError as exc:
                    raise BudgetCorruptionError(
                        f"reservation maximum exceeds datetime range at line {line_number}"
                    ) from exc
                if maximum_end > week_end:
                    raise BudgetCorruptionError(
                        f"reservation crosses ISO week boundary at line {line_number}"
                    )
                prior_charge = self._week_charge(states, row["week_id"])
                if prior_charge + reserved_s > self.limit_s:
                    raise BudgetCorruptionError(
                        f"reservation overspends weekly limit at line {line_number}"
                    )
                states[run_id] = {
                    "run_id": run_id,
                    "manifest_sha256": row["manifest_sha256"],
                    "week_id": row["week_id"],
                    "reserved_s": reserved_s,
                    "elapsed_s": None,
                    "charged_s": reserved_s,
                    "state": "reserved",
                    "status": None,
                    "reserved_at": row["event_at"],
                    "finished_at": None,
                }
            elif event_type == "debit":
                if float(row["charged_s"]) != float(row["elapsed_s"]):
                    raise BudgetCorruptionError(f"invalid debit charge at line {line_number}")
                states[run_id] = {
                    "run_id": run_id,
                    "manifest_sha256": row["manifest_sha256"],
                    "week_id": row["week_id"],
                    "reserved_s": 0.0,
                    "elapsed_s": float(row["elapsed_s"]),
                    "charged_s": float(row["charged_s"]),
                    "state": "finished",
                    "status": "imported",
                    "reserved_at": None,
                    "finished_at": row["event_at"],
                }
            else:
                state = states.get(run_id)
                if state is None:
                    raise BudgetCorruptionError(f"finish without reserve at line {line_number}")
                if state["state"] != "reserved":
                    raise BudgetCorruptionError(f"duplicate finish at line {line_number}")
                if row["manifest_sha256"] != state["manifest_sha256"]:
                    raise BudgetCorruptionError(f"finish manifest mismatch at line {line_number}")
                if row["week_id"] != state["week_id"]:
                    raise BudgetCorruptionError(f"finish week mismatch at line {line_number}")
                if float(row["reserved_s"]) != state["reserved_s"]:
                    raise BudgetCorruptionError(
                        f"finish reservation mismatch at line {line_number}"
                    )
                elapsed = float(row["elapsed_s"])
                expected_charge = (
                    max(state["reserved_s"], elapsed)
                    if row["status"] in FULL_CHARGE_TERMINAL_STATUSES
                    else elapsed
                )
                if float(row["charged_s"]) != expected_charge:
                    raise BudgetCorruptionError(f"invalid finish charge at line {line_number}")
                if _parse_iso(row["event_at"]) < _parse_iso(state["reserved_at"]):
                    raise BudgetCorruptionError(
                        f"finish predates reservation at line {line_number}"
                    )
                state.update({
                    "elapsed_s": elapsed,
                    "charged_s": expected_charge,
                    "state": "finished",
                    "status": row["status"],
                    "finished_at": row["event_at"],
                })
        return states

    def _append(self, row: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
        row = {
            "schema_version": SCHEMA_VERSION,
            "sequence": len(events) + 1,
            **row,
            "previous_event_sha256": events[-1]["event_sha256"] if events else None,
        }
        row["event_sha256"] = _event_hash(row)
        payload = _canonical(row) + b"\n"
        created = not self.path.exists()
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        fd = os.open(self.path, flags, 0o600)
        try:
            view = memoryview(payload)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError("short write to budget journal")
                view = view[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
        if created:
            directory_fd = os.open(self.path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        return row

    @staticmethod
    def _week_charge(states: dict[str, dict[str, Any]], week_id: str) -> float:
        return sum(state["charged_s"] for state in states.values() if state["week_id"] == week_id)

    def reserve(
        self,
        run_id: str,
        seconds: float,
        manifest_sha256: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        run_id = _run_id(run_id)
        seconds = _number(seconds, "seconds")
        manifest_sha256 = _manifest_sha256(manifest_sha256)
        event_time = _now(now)
        week_id, _, week_end = _week(event_time)
        try:
            maximum_end = event_time + timedelta(seconds=seconds)
        except OverflowError as exc:
            raise WeekBoundaryError("reservation maximum exceeds datetime range") from exc
        if maximum_end > week_end:
            raise WeekBoundaryError(
                f"reservation maximum crosses UTC ISO week boundary at {_iso(week_end)}"
            )

        with self._locked():
            events = self._read_events()
            states = self._states(events)
            if run_id in states:
                raise DuplicateRunError(f"run_id has already been recorded: {run_id}")
            charged = self._week_charge(states, week_id)
            if charged + seconds > self.limit_s:
                raise BudgetExceededError(
                    f"reservation would charge {charged + seconds:.6f}s against "
                    f"the {self.limit_s:.6f}s limit for {week_id}"
                )
            self._append({
                "event": "reserve",
                "event_at": _iso(event_time),
                "week_id": week_id,
                "run_id": run_id,
                "manifest_sha256": manifest_sha256,
                "reserved_s": seconds,
            }, events)
            return {
                "run_id": run_id,
                "manifest_sha256": manifest_sha256,
                "week_id": week_id,
                "reserved_s": seconds,
                "elapsed_s": None,
                "charged_s": seconds,
                "state": "reserved",
                "status": None,
                "reserved_at": _iso(event_time),
                "finished_at": None,
            }

    def finish(
        self,
        run_id: str,
        elapsed_s: float,
        status: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        run_id = _run_id(run_id)
        elapsed_s = _number(elapsed_s, "elapsed_s")
        if status not in TERMINAL_STATUSES:
            raise BudgetError(f"status must be one of {sorted(TERMINAL_STATUSES)}")
        event_time = _now(now)

        with self._locked():
            events = self._read_events()
            states = self._states(events)
            state = states.get(run_id)
            if state is None:
                raise UnknownRunError(f"no reservation for run_id: {run_id}")
            if state["state"] != "reserved":
                raise InvalidTransitionError(f"run_id is already terminal: {run_id}")
            if event_time < _parse_iso(state["reserved_at"]):
                raise InvalidTransitionError("terminal receipt predates its reservation")
            charged_s = (
                max(state["reserved_s"], elapsed_s)
                if status in FULL_CHARGE_TERMINAL_STATUSES
                else elapsed_s
            )
            self._append({
                "event": "finish",
                "event_at": _iso(event_time),
                "week_id": state["week_id"],
                "run_id": run_id,
                "manifest_sha256": state["manifest_sha256"],
                "reserved_s": state["reserved_s"],
                "elapsed_s": elapsed_s,
                "charged_s": charged_s,
                "status": status,
            }, events)
            return {
                **state,
                "elapsed_s": elapsed_s,
                "charged_s": charged_s,
                "state": "finished",
                "status": status,
                "finished_at": _iso(event_time),
            }

    def debit(
        self,
        run_id: str,
        seconds: float,
        manifest_sha256: str,
        now: datetime | None = None,
        status: str = "imported",
    ) -> dict[str, Any]:
        """Record exact prior usage that did not have a reservation.

        A debit is an honest terminal receipt, so it is persisted even when it
        takes the week over budget.  Such an overrun makes future reservations
        fail until the next ISO week.
        """
        run_id = _run_id(run_id)
        seconds = _number(seconds, "seconds")
        manifest_sha256 = _manifest_sha256(manifest_sha256)
        if status != "imported":
            raise BudgetError("debit status must be 'imported'")
        event_time = _now(now)
        week_id, _, _ = _week(event_time)

        with self._locked():
            events = self._read_events()
            states = self._states(events)
            if run_id in states:
                raise DuplicateRunError(f"run_id has already been recorded: {run_id}")
            self._append({
                "event": "debit",
                "event_at": _iso(event_time),
                "week_id": week_id,
                "run_id": run_id,
                "manifest_sha256": manifest_sha256,
                "elapsed_s": seconds,
                "charged_s": seconds,
                "status": status,
            }, events)
            return {
                "run_id": run_id,
                "manifest_sha256": manifest_sha256,
                "week_id": week_id,
                "reserved_s": 0.0,
                "elapsed_s": seconds,
                "charged_s": seconds,
                "state": "finished",
                "status": "imported",
                "reserved_at": None,
                "finished_at": _iso(event_time),
            }

    def snapshot(self, now: datetime | None = None) -> dict[str, Any]:
        event_time = _now(now)
        week_id, week_start, week_end = _week(event_time)
        with self._locked():
            events = self._read_events()
            states = self._states(events)
            current = [state for state in states.values() if state["week_id"] == week_id]
            reserved_s = sum(
                state["reserved_s"] for state in current if state["state"] == "reserved"
            )
            consumed_s = sum(
                state["charged_s"] for state in current if state["state"] == "finished"
            )
            charged_s = reserved_s + consumed_s
            return {
                "schema_version": SCHEMA_VERSION,
                "week_id": week_id,
                "week_start": _iso(week_start),
                "week_end": _iso(week_end),
                "limit_s": self.limit_s,
                "reserved_s": reserved_s,
                "consumed_s": consumed_s,
                "charged_s": charged_s,
                "remaining_s": max(0.0, self.limit_s - charged_s),
                "overrun_s": max(0.0, charged_s - self.limit_s),
                "active_run_ids": sorted(
                    state["run_id"] for state in current if state["state"] == "reserved"
                ),
                "terminal_run_ids": sorted(
                    state["run_id"] for state in current if state["state"] == "finished"
                ),
                "journal_event_count": len(events),
                "journal_head_sha256": events[-1]["event_sha256"] if events else None,
            }

    def existing(self, run_id: str) -> dict[str, Any] | None:
        run_id = _run_id(run_id)
        with self._locked():
            events = self._read_events()
            state = self._states(events).get(run_id)
            return dict(state) if state is not None else None
