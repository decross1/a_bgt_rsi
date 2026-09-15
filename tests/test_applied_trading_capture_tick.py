"""Producer-shaped cases for the bounded public Spot capture tick."""

from __future__ import annotations

import fcntl
import json
import os
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from bench.applied_trading import capture_tick as tick


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    captures = tmp_path / "captures"
    scheduler = captures / "_scheduler"
    scheduler.mkdir(parents=True)
    (scheduler / "ticks").mkdir()
    (scheduler / "abandoned").mkdir()
    canonical = tmp_path / "canonical"
    run_state = canonical / "run_state"
    run_state.mkdir(parents=True)
    for name in tick.LOCK_NAMES:
        (run_state / name).write_text("")
    monkeypatch.setattr(tick, "CAPTURE_ROOT", captures)
    monkeypatch.setattr(tick, "SCHEDULER_ROOT", scheduler)
    monkeypatch.setattr(tick, "CANONICAL_REPO", canonical)
    monkeypatch.setattr(tick, "_ensure_scheduler", lambda: None)
    monkeypatch.setattr(tick, "_source_sha", lambda: "a" * 64)
    monkeypatch.setattr(tick, "_continuation_sha", lambda: "b" * 64)
    rows, states = [], []
    monkeypatch.setattr(tick, "_persist_tick", rows.append)
    monkeypatch.setattr(tick, "_replace_state", states.append)
    return captures, scheduler, run_state, rows, states


def _active(previous: Path, *, bootstrap: Path | None = None) -> dict:
    return {"schema": tick.STATE_SCHEMA, "symbol": "BTCUSDT",
            "collector_source_sha256": "a" * 64,
            "continuation_source_sha256": "b" * 64,
            "lineage_id": "h1-testlineage", "mode": "active",
            "bootstrap_warmup_path": str(bootstrap) if bootstrap else None,
            "last_complete_path": str(previous),
            "last_complete_sha256": "c" * 64,
            "attempt_output_path": None,
            "blocked_reason": None, "updated_at": tick._now()}


def _complete(*, from_id: int = 10, next_id: int = 11,
              sealed_at: str | None = None) -> dict:
    return {"status": "complete_incremental_batch", "from_aggregate_id": from_id,
            "next_aggregate_id": next_id, "sealed_at": sealed_at or tick._now(),
            "attempt_denominator_verified": True,
            "requests_attempted": 3, "requests_succeeded": 3, "requests_failed": 0,
            "failure": None, "cursor_gap": False, "page_gap": False,
            "backlog_unresolved": False}


def test_busy_canonical_lease_issues_zero_gets(isolated, monkeypatch):
    captures, _scheduler, run_state, rows, _states = isolated
    monkeypatch.setattr(tick, "_state", lambda: (_active(captures / "unused"), "d" * 64))
    monkeypatch.setattr(tick.continuation, "run_once",
                        lambda **_kwargs: pytest.fail("busy lease issued GET"))
    with (run_state / ".weekly-upgrade-gpu.lock").open("rb") as holder:
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = tick.run_once()
    assert result["status"] == "skipped_busy"
    assert result["requests_attempted"] == result["requests_succeeded"] == 0
    assert result["attempt_denominator_verified"] is True
    assert rows == [result]


def test_operator_pause_records_zero_get_skip(isolated, monkeypatch):
    _captures, scheduler, _run_state, rows, _states = isolated
    (scheduler / "pause_capture").write_text("model research window\n")
    monkeypatch.setattr(tick.continuation, "run_once",
                        lambda **_kwargs: pytest.fail("paused tick issued GET"))
    result = tick.run_once()
    assert result["status"] == "skipped_busy"
    assert result["reason"] == "operator_pause_capture"
    assert result["requests_attempted"] == 0 and rows == [result]


def test_state_fifo_is_rejected_without_blocking(isolated):
    _captures, scheduler, _run_state, _rows, _states = isolated
    os.mkfifo(scheduler / "state.json")
    with pytest.raises(tick.TickError, match="nonregular"):
        tick._state()


def test_source_drift_blocks_before_network(isolated, monkeypatch):
    captures, _scheduler, _run_state, rows, states = isolated
    old = {**_active(captures / "unused"), "collector_source_sha256": "f" * 64}
    monkeypatch.setattr(tick, "_state", lambda: (old, "d" * 64))
    monkeypatch.setattr(tick.continuation, "run_once",
                        lambda **_kwargs: pytest.fail("source-drift tick issued GET"))
    result = tick.run_once()
    assert result["status"] == "blocked" and result["reason"] == "collector_source_drift"
    assert rows == [result] and states[-1]["mode"] == "blocked"


def test_long_pause_requests_new_independent_lineage_not_old_cursor(isolated, monkeypatch):
    captures, _scheduler, _run_state, rows, states = isolated
    prior = captures / "spot-BTCUSDT-20260915T000000Z"
    monkeypatch.setattr(tick, "_state", lambda: (_active(prior), "d" * 64))
    monkeypatch.setattr(tick, "_fixed_capture", lambda _text: prior)
    old = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    monkeypatch.setattr(tick, "_batch", lambda _path: (_complete(sealed_at=old), "c" * 64))
    monkeypatch.setattr(tick.continuation, "run_once",
                        lambda **_kwargs: pytest.fail("stale cursor issued GET"))
    requested = []
    monkeypatch.setattr(tick, "bootstrap_new", lambda **kwargs: (
        requested.append(kwargs) or {"status": "bootstrapped_complete"}))
    result = tick.run_once()
    assert result["status"] == "bootstrapped_complete"
    assert requested[0]["abandon_state_sha256"] == "d" * 64
    assert requested[0]["_held_lock"] is True
    assert requested[0]["_verified_stale_gap"] == {
        "old_lineage_id": "h1-testlineage",
        "old_state_sha256": "d" * 64,
        "old_batch_sha256": "c" * 64,
        "old_sealed_at": old,
    }
    assert rows == [] and states == []


def test_verified_stale_gap_receipt_precedes_first_new_get(isolated, monkeypatch):
    captures, scheduler, _run_state, rows, states = isolated
    (scheduler / "gaps").mkdir()
    prior = captures / "spot-BTCUSDT-20260915T000000Z"
    old_state = _active(prior)
    old_raw = tick._canon(old_state)
    old_sha = tick._sha(old_raw)
    old_seal = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    monkeypatch.setattr(tick, "_state", lambda: (old_state, old_sha))
    monkeypatch.setattr(tick, "_read_regular", lambda _path, *_args: old_raw)
    monkeypatch.setattr(tick, "_deadline", lambda _seconds: nullcontext())
    names = iter((captures / "spot-BTCUSDT-20260915T040000Z",
                  captures / "spot-BTCUSDT-20260915T040001Z"))
    monkeypatch.setattr(tick, "_capture_child", lambda: next(names))
    warmup = {"status": "incomplete", "initial_history_gap": True,
              "next_aggregate_id": 42, "requests_attempted": 3,
              "requests_succeeded": 3, "requests_failed": 0,
              "attempt_denominator_verified": True, "failure": None}
    current = _complete(from_id=42, next_id=43)
    calls = []

    def fake_capture(output_dir, *, symbol, from_id, max_pages):
        assert symbol == "BTCUSDT"
        assert list((scheduler / "gaps").glob("gap-*.json"))
        assert list((scheduler / "abandoned").glob(f"state-{old_sha}.json"))
        calls.append((from_id, max_pages))
        output_dir.mkdir()
        value = warmup if from_id is None else current
        (output_dir / "capture-batch.json").write_text(json.dumps(value) + "\n")
        return value

    monkeypatch.setattr(tick.collector, "capture_once", fake_capture)
    monkeypatch.setattr(tick, "_batch", lambda path: (
        (warmup, "e" * 64) if path.name.endswith("040000Z")
        else (current, "f" * 64)))
    result = tick.bootstrap_new(
        abandon_state_sha256=old_sha, max_wall_s=90,
        _held_lock=True, _verified_stale_gap={
            "old_lineage_id": old_state["lineage_id"],
            "old_state_sha256": old_sha,
            "old_batch_sha256": old_state["last_complete_sha256"],
            "old_sealed_at": old_seal,
        })
    gap = json.loads((scheduler / result["gap_relpath"]).read_text())
    assert calls == [(None, 1), (42, 8)]
    assert gap["old_state_sha256"] == old_sha
    assert gap["old_lineage_id"] == old_state["lineage_id"]
    assert gap["new_lineage_id"] == result["lineage_id"]
    assert gap["unobserved_after_old_seal_at"] == old_seal
    assert gap["cursor_linked_across_gap"] is False
    assert result["status"] == "bootstrapped_complete"
    assert result["requests_attempted"] == 6
    assert states[-1]["mode"] == "active"
    assert rows == [result]


def test_hard_killed_attempt_is_a_stop_marker(isolated, monkeypatch):
    captures, _scheduler, _run_state, rows, states = isolated
    interrupted = {**_active(captures / "unused"), "mode": "attempting",
                   "attempt_output_path": str(captures / "spot-BTCUSDT-20260915T010000Z")}
    monkeypatch.setattr(tick, "_state", lambda: (interrupted, "d" * 64))
    monkeypatch.setattr(tick.continuation, "run_once",
                        lambda **_kwargs: pytest.fail("interrupted branch issued GET"))
    result = tick.run_once()
    assert result["status"] == "blocked" and result["requests_attempted"] is None
    assert result["attempt_denominator_verified"] is False
    assert rows == [result] and states[-1]["blocked_reason"] == "interrupted_prior_tick"


def test_new_bootstrap_uses_venue_tail_not_old_lineage(isolated, monkeypatch):
    captures, _scheduler, _run_state, rows, states = isolated
    first = captures / "spot-BTCUSDT-20260915T020000Z"
    second = captures / "spot-BTCUSDT-20260915T020001Z"
    names = iter((first, second))
    monkeypatch.setattr(tick, "_capture_child", lambda: next(names))
    monkeypatch.setattr(tick, "_state", lambda: (None, None))
    monkeypatch.setattr(tick, "_deadline", lambda _seconds: nullcontext())
    calls = []
    warmup = {"status": "incomplete", "initial_history_gap": True,
              "next_aggregate_id": 42, "requests_attempted": 3,
              "requests_succeeded": 3, "requests_failed": 0,
              "attempt_denominator_verified": True, "failure": None}
    current = _complete(from_id=42, next_id=43)

    def fake_capture(output_dir, *, symbol, from_id, max_pages):
        assert symbol == "BTCUSDT"
        calls.append((from_id, max_pages))
        output_dir.mkdir()
        value = warmup if from_id is None else current
        (output_dir / "capture-batch.json").write_text(json.dumps(value) + "\n")
        return value

    monkeypatch.setattr(tick.collector, "capture_once", fake_capture)
    monkeypatch.setattr(tick, "_batch", lambda path: (
        (warmup, "d" * 64) if path == first else (current, "e" * 64)))
    result = tick.bootstrap_new()
    assert calls == [(None, 1), (42, 8)]
    assert result["status"] == "bootstrapped_complete"
    assert result["requests_attempted"] == result["requests_succeeded"] == 6
    assert result["requests_failed"] == 0
    assert result["attempt_denominator_verified"] is True
    assert states[-1]["mode"] == "active" and states[-1]["last_complete_path"] == str(second)
    assert rows == [result]


def test_failed_but_sealed_bootstrap_preserves_get_denominator(isolated, monkeypatch):
    captures, _scheduler, _run_state, rows, states = isolated
    first = captures / "spot-BTCUSDT-20260915T021000Z"
    second = captures / "spot-BTCUSDT-20260915T021001Z"
    names = iter((first, second))
    monkeypatch.setattr(tick, "_capture_child", lambda: next(names))
    monkeypatch.setattr(tick, "_state", lambda: (None, None))
    monkeypatch.setattr(tick, "_deadline", lambda _seconds: nullcontext())
    warmup = {"status": "incomplete", "initial_history_gap": True,
              "next_aggregate_id": 42, "requests_attempted": 3,
              "requests_succeeded": 3, "requests_failed": 0,
              "attempt_denominator_verified": True, "failure": None}
    capped = {**_complete(from_id=42, next_id=43), "status": "incomplete",
              "backlog_unresolved": True}

    def fake_capture(output_dir, *, symbol, from_id, max_pages):
        assert symbol == "BTCUSDT"
        output_dir.mkdir()
        value = warmup if from_id is None else capped
        (output_dir / "capture-batch.json").write_text(json.dumps(value) + "\n")
        return value

    monkeypatch.setattr(tick.collector, "capture_once", fake_capture)
    monkeypatch.setattr(tick, "_batch", lambda path: (
        (warmup, "d" * 64) if path == first else (capped, "e" * 64)))
    result = tick.bootstrap_new()
    assert result["status"] == "blocked"
    assert result["requests_attempted"] == result["requests_succeeded"] == 6
    assert result["requests_failed"] == 0 and result["attempt_denominator_verified"] is True
    assert result["source_valid_batch"] is False
    assert rows == [result] and states[-1]["mode"] == "blocked"


def test_incomplete_successor_never_advances_state(isolated, monkeypatch):
    captures, _scheduler, _run_state, rows, states = isolated
    previous = captures / "spot-BTCUSDT-20260915T030000Z"
    output = captures / "spot-BTCUSDT-20260915T030500Z"
    monkeypatch.setattr(tick, "_state", lambda: (_active(previous), "d" * 64))
    monkeypatch.setattr(tick, "_fixed_capture", lambda _text: previous)
    monkeypatch.setattr(tick, "_capture_child", lambda: output)
    monkeypatch.setattr(tick, "_deadline", lambda _seconds: nullcontext())
    stopped = {**_complete(from_id=11, next_id=12), "status": "incomplete",
               "backlog_unresolved": True}

    def fake_batch(path):
        return (_complete(), "c" * 64) if path == previous else (stopped, "e" * 64)

    def fake_continue(**_kwargs):
        output.mkdir()
        (output / "capture-batch.json").write_text(json.dumps(stopped) + "\n")
        return {"status": "continued_stopped"}

    monkeypatch.setattr(tick, "_batch", fake_batch)
    monkeypatch.setattr(tick.continuation, "run_once", fake_continue)
    result = tick.run_once()
    assert result["status"] == "blocked"
    assert result["requests_attempted"] == 3
    assert result["source_valid_batch"] is False
    assert rows == [result] and states[-1]["mode"] == "blocked"
    assert states[-1]["last_complete_path"] == str(previous)
