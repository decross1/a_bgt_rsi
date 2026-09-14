"""Contract tests for the shared weekly Spark-budget journal."""
from __future__ import annotations

import json
import multiprocessing
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from orchestrator.weekly_upgrade_budget import (
    BudgetCorruptionError,
    BudgetError,
    BudgetExceededError,
    BudgetLedger,
    DuplicateRunError,
    InvalidTransitionError,
    UnknownRunError,
    WeekBoundaryError,
)

MONDAY = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
MANIFEST = "a" * 64


def _reserve_process(
    path: str, start: multiprocessing.synchronize.Event, index: int, queue
) -> None:
    ledger = BudgetLedger(path)
    start.wait()
    try:
        ledger.reserve(f"parallel-{index}", 1_000, MANIFEST, now=MONDAY)
    except BudgetExceededError:
        queue.put("rejected")
    else:
        queue.put("reserved")


def test_reserve_finish_releases_unused_and_interruption_stays_fully_charged(tmp_path: Path):
    ledger = BudgetLedger(tmp_path / "shared" / "budget.jsonl")

    first = ledger.reserve("completed-run", 1_000, MANIFEST, now=MONDAY)
    assert first["charged_s"] == 1_000
    finished = ledger.finish(
        "completed-run", 125.5, "completed", now=MONDAY + timedelta(minutes=3)
    )
    assert finished["charged_s"] == 125.5

    ledger.reserve("interrupted-run", 500, "b" * 64, now=MONDAY)
    interrupted = ledger.finish(
        "interrupted-run", 12, "interrupted", now=MONDAY + timedelta(minutes=4)
    )
    assert interrupted["charged_s"] == 500

    snapshot = ledger.snapshot(now=MONDAY)
    assert snapshot["reserved_s"] == 0
    assert snapshot["consumed_s"] == 625.5
    assert snapshot["remaining_s"] == 6_574.5
    assert snapshot["active_run_ids"] == []


def test_active_crash_remains_charged_and_duplicate_never_authorizes_retry(tmp_path: Path):
    ledger = BudgetLedger(tmp_path / "budget.jsonl")
    ledger.reserve("crashed-run", 7_200, MANIFEST, now=MONDAY)

    reopened = BudgetLedger(ledger.path)
    assert reopened.snapshot(now=MONDAY)["charged_s"] == 7_200
    assert reopened.existing("crashed-run")["state"] == "reserved"
    with pytest.raises(DuplicateRunError):
        reopened.reserve("crashed-run", 1, MANIFEST, now=MONDAY + timedelta(days=7))
    with pytest.raises(BudgetExceededError):
        reopened.reserve("blind-retry", 1, MANIFEST, now=MONDAY)


def test_completion_overrun_is_recorded_honestly_and_blocks_later_dispatch(tmp_path: Path):
    ledger = BudgetLedger(tmp_path / "budget.jsonl")
    ledger.reserve("overrun", 7_000, MANIFEST, now=MONDAY)
    receipt = ledger.finish(
        "overrun", 7_350, "completed", now=MONDAY + timedelta(hours=2, minutes=3)
    )
    assert receipt["charged_s"] == 7_350
    snapshot = ledger.snapshot(now=MONDAY)
    assert snapshot["charged_s"] == 7_350
    assert snapshot["remaining_s"] == 0
    assert snapshot["overrun_s"] == 150
    with pytest.raises(BudgetExceededError):
        ledger.reserve("after-overrun", 0, MANIFEST, now=MONDAY)


def test_imported_terminal_debit_is_exact_and_can_expose_prior_overrun(tmp_path: Path):
    ledger = BudgetLedger(tmp_path / "budget.jsonl")
    row = ledger.debit("prior-untracked", 7_250, MANIFEST, now=MONDAY)
    assert row["status"] == "imported"
    assert row["charged_s"] == 7_250
    assert ledger.snapshot(now=MONDAY)["overrun_s"] == 50
    with pytest.raises(DuplicateRunError):
        ledger.debit("prior-untracked", 1, MANIFEST, now=MONDAY)


def test_reservation_cannot_cross_utc_iso_week_boundary(tmp_path: Path):
    ledger = BudgetLedger(tmp_path / "budget.jsonl")
    sunday = datetime(2026, 9, 20, 23, 59, tzinfo=timezone.utc)
    ledger.reserve("ends-exactly", 60, MANIFEST, now=sunday)
    with pytest.raises(WeekBoundaryError):
        ledger.reserve("crosses", 60.001, MANIFEST, now=sunday)

    next_week = ledger.snapshot(now=datetime(2026, 9, 21, tzinfo=timezone.utc))
    assert next_week["week_id"] == "2026-W39"
    assert next_week["charged_s"] == 0
    with pytest.raises(DuplicateRunError):
        ledger.reserve("ends-exactly", 1, MANIFEST, now=datetime(2026, 9, 21, tzinfo=timezone.utc))


def test_late_terminal_receipt_stays_attributed_to_reservation_week(tmp_path: Path):
    ledger = BudgetLedger(tmp_path / "budget.jsonl")
    sunday = datetime(2026, 9, 20, 23, 58, tzinfo=timezone.utc)
    ledger.reserve("late-receipt", 60, MANIFEST, now=sunday)
    ledger.finish(
        "late-receipt",
        180,
        "completed",
        now=datetime(2026, 9, 21, 0, 1, tzinfo=timezone.utc),
    )

    prior = ledger.snapshot(now=sunday)
    current = ledger.snapshot(now=datetime(2026, 9, 21, 0, 2, tzinfo=timezone.utc))
    assert prior["consumed_s"] == 180
    assert current["charged_s"] == 0
    assert ledger.existing("late-receipt")["week_id"] == "2026-W38"


@pytest.mark.parametrize(
    "bad",
    [
        True,
        False,
        -1,
        float("nan"),
        float("inf"),
        -float("inf"),
        10**400,
        "1",
        None,
    ],
)
def test_numeric_inputs_reject_bools_negative_nonfinite_and_nonnumeric(tmp_path: Path, bad):
    ledger = BudgetLedger(tmp_path / "budget.jsonl")
    with pytest.raises(BudgetError):
        ledger.reserve(f"bad-{type(bad).__name__}", bad, MANIFEST, now=MONDAY)


def test_invalid_identifiers_timestamps_statuses_and_transitions_fail(tmp_path: Path):
    ledger = BudgetLedger(tmp_path / "budget.jsonl")
    with pytest.raises(BudgetError):
        ledger.reserve("bad/run", 1, MANIFEST, now=MONDAY)
    with pytest.raises(BudgetError):
        ledger.reserve("run", 1, "A" * 64, now=MONDAY)
    with pytest.raises(BudgetError):
        ledger.reserve("run", 1, MANIFEST, now=datetime(2026, 9, 14))  # noqa: DTZ001 -- rejection test
    with pytest.raises(UnknownRunError):
        ledger.finish("missing", 1, "completed", now=MONDAY)

    ledger.reserve("run", 10, MANIFEST, now=MONDAY)
    with pytest.raises(BudgetError):
        ledger.finish("run", 1, "success", now=MONDAY)
    ledger.finish("run", 1, "failed", now=MONDAY)
    with pytest.raises(InvalidTransitionError):
        ledger.finish("run", 1, "completed", now=MONDAY)


@pytest.mark.parametrize(
    "contents",
    [
        b"",
        b'{"partial":true}',
        b'{not-json}\n',
        b'{"event":"made-up"}\n',
        b'NaN\n',
        b'\n',
    ],
)
def test_corrupt_or_partial_journal_fails_closed_without_appending(tmp_path: Path, contents: bytes):
    path = tmp_path / "budget.jsonl"
    path.write_bytes(contents)
    ledger = BudgetLedger(path)
    before = path.read_bytes()
    with pytest.raises(BudgetCorruptionError):
        ledger.reserve("must-not-write", 1, MANIFEST, now=MONDAY)
    assert path.read_bytes() == before


def test_tampering_and_hash_chain_break_fail_closed(tmp_path: Path):
    path = tmp_path / "budget.jsonl"
    ledger = BudgetLedger(path)
    ledger.reserve("one", 10, MANIFEST, now=MONDAY)
    ledger.finish("one", 2, "completed", now=MONDAY)

    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[0]["reserved_s"] = 11.0
    path.write_text(
        "\n".join(
            json.dumps(row, sort_keys=True, separators=(",", ":")) for row in rows
        )
        + "\n"
    )
    with pytest.raises(BudgetCorruptionError):
        ledger.snapshot(now=MONDAY)


def test_independent_processes_cannot_overspend_shared_week(tmp_path: Path):
    path = tmp_path / "budget.jsonl"
    ctx = multiprocessing.get_context("fork")
    start = ctx.Event()
    queue = ctx.Queue()
    processes = [
        ctx.Process(target=_reserve_process, args=(str(path), start, index, queue))
        for index in range(8)
    ]
    for process in processes:
        process.start()
    start.set()
    results = [queue.get(timeout=10) for _ in processes]
    for process in processes:
        process.join(timeout=10)
        assert process.exitcode == 0

    assert results.count("reserved") == 7
    assert results.count("rejected") == 1
    snapshot = BudgetLedger(path).snapshot(now=MONDAY)
    assert snapshot["charged_s"] == 7_000
    assert len(snapshot["active_run_ids"]) == 7
    assert snapshot["journal_event_count"] == 7
