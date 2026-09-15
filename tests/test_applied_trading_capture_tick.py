"""Producer-shaped cases for the bounded public Spot capture tick."""

from __future__ import annotations

import fcntl
import json
import os
import urllib.error
import urllib.parse
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from bench.applied_trading import capture_tick as tick


def test_capture_tick_registers_full_collector_page_cap_and_exact_continuation():
    assert tick.MAX_PAGES == tick.collector.MAX_PAGES == 32
    assert tick._actual_continuation_sha() == tick.REGISTERED_CONTINUATION_SHA256


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
    for name in (".weekly-upgrade-execution.lock", ".coordinator-cron.lock",
                 ".weekly-upgrade-gpu.lock"):
        (run_state / name).write_text("")
    meminfo = tmp_path / "meminfo"
    meminfo.write_text(f"MemAvailable: {32 * 1024**2} kB\n")
    monkeypatch.setattr(tick, "MEMINFO_PATH", meminfo)
    monkeypatch.setattr(tick, "CAPTURE_ROOT", captures)
    monkeypatch.setattr(tick, "SCHEDULER_ROOT", scheduler)
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


def test_gpu_lease_does_not_block_cpu_capture(isolated, monkeypatch):
    captures, _scheduler, run_state, rows, states = isolated
    previous, output = captures / "previous", captures / "next"
    batch = _complete()
    output.mkdir()
    (output / "capture-batch.json").write_text(json.dumps(batch))
    monkeypatch.setattr(tick, "_state", lambda: (_active(previous), "d" * 64))
    monkeypatch.setattr(tick, "_fixed_capture", lambda text: Path(text))
    monkeypatch.setattr(tick, "_batch", lambda _path: (batch, "c" * 64))
    monkeypatch.setattr(tick, "_capture_child", lambda: output)
    calls = []
    monkeypatch.setattr(tick.continuation, "run_once",
                        lambda **kwargs: (calls.append(kwargs) or
                                          {"status": "continued_complete"}))
    with (run_state / ".weekly-upgrade-gpu.lock").open("rb") as holder:
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = tick.run_once()
    assert result["status"] == "continued_complete"
    assert result["requests_attempted"] == 3
    assert len(calls) == 1 and states[-1]["mode"] == "active"
    assert rows == [result]


@pytest.mark.parametrize("meminfo,reason", [
    ("MemAvailable: 1024 kB\n", "memory_available_below_21gib"),
    ("MemTotal: 128000000 kB\n", "memory_available_unverified"),
    ("MemAvailable: -1 kB\n", "memory_available_unverified"),
    ("MemAvailable: 128 GiB\n", "memory_available_unverified"),
])
def test_memory_pressure_or_unknown_issues_zero_gets(isolated, monkeypatch, meminfo, reason):
    _captures, _scheduler, _run_state, rows, _states = isolated
    tick.MEMINFO_PATH.write_text(meminfo)
    monkeypatch.setattr(tick.continuation, "run_once",
                        lambda **_kwargs: pytest.fail("memory gate issued GET"))
    result = tick.run_once()
    assert result["status"] == "skipped_busy"
    assert result["reason"] == reason
    assert result["requests_attempted"] == result["requests_succeeded"] == 0
    assert result["attempt_denominator_verified"] is True
    assert rows == [result]


def test_capture_scheduler_still_excludes_second_tick(isolated):
    _captures, scheduler, _run_state, _rows, _states = isolated
    with (scheduler / "capture-tick.lock").open("wb") as holder:
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(tick.TickError, match="another capture tick"):
            tick.run_once()


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
    assert calls == [(None, 1), (42, 32)]
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
    assert calls == [(None, 1), (42, 32)]
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


def _transient_fixture(captures: Path, monkeypatch, *, code: str = "HTTPError",
                       status: int | None = 503, stage: str = "http_contract"):
    previous = captures / "spot-BTCUSDT-20260915T010000Z"
    output = captures / "spot-BTCUSDT-20260915T010500Z"
    old_seal = (datetime.now(timezone.utc) - timedelta(minutes=21)).isoformat()
    failed_at = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
    sealed = (datetime.now(timezone.utc) - timedelta(minutes=19)).isoformat()
    state = {**_active(previous), "mode": "blocked",
             "attempt_output_path": str(output),
             "blocked_reason": "continuation_failed:TickError"}
    previous_batch = _complete(sealed_at=old_seal)
    failed_batch = {
        **_complete(from_id=11, next_id=11, sealed_at=sealed),
        "started_at": failed_at,
        "status": "incomplete", "failure": "CaptureAttemptError: public GET failed",
        "requests_attempted": 3, "requests_succeeded": 2,
        "requests_failed": 1,
    }
    last = {"attempt_status": "failed", "raw_relpath": None,
            "raw_sha256": None, "raw_bytes": 0, "failure_stage": stage,
            "failure_code": code, "http_status": status,
            "response_received_at": failed_at,
            "record_sha256": "e" * 64, "kind": "aggTrades"}
    report = {"schema": tick.continuation.SCHEMA,
              "status": "stopped_incomplete", "previous_batch_path": str(previous),
              "previous_batch_sha256": "c" * 64,
              "batch_sha256": "d" * 64, "from_aggregate_id": 11,
              "collector_source_sha256": "a" * 64,
              "continuation_source_sha256": "b" * 64,
              "current_requests": {"attempted": 3, "succeeded": 2, "failed": 1},
              "orders_placed": 0, "credentials_used": False}
    monkeypatch.setattr(tick, "_fixed_capture", lambda text: Path(text))
    monkeypatch.setattr(tick, "_batch", lambda path: (
        (previous_batch, "c" * 64) if path == previous
        else (failed_batch, "d" * 64)))
    monkeypatch.setattr(tick, "_read_relative", lambda _path, name, _limit: (
        tick._canon(last) if name == "attempts.jsonl"
        else tick._canon(report)))
    return state


def test_sealed_http_5xx_get_can_start_new_lineage_after_cooldown(isolated, monkeypatch):
    captures, _scheduler, _run_state, rows, states = isolated
    state = _transient_fixture(captures, monkeypatch)
    verified = tick._sealed_transient_get(state)
    assert verified is not None
    assert verified["failed_batch_sha256"] == "d" * 64
    assert verified["failed_http_status"] == 503
    assert verified["failed_cause_class"] == "sealed_timeout_or_http5xx_unavailability"
    monkeypatch.setattr(tick, "_state", lambda: (state, "f" * 64))
    requested = []
    monkeypatch.setattr(tick, "bootstrap_new", lambda **kwargs: (
        requested.append(kwargs) or {"status": "bootstrapped_complete"}))
    assert tick.run_once()["status"] == "bootstrapped_complete"
    assert requested[0]["_verified_transient_gap"] == verified
    assert requested[0]["abandon_state_sha256"] == "f" * 64
    assert requested[0]["_held_lock"] is True
    assert rows == states == []


@pytest.mark.parametrize("code,status,stage", [
    ("HTTPError", 429, "http_contract"),
    ("OSError", None, "transport"),
    ("CaptureError", 200, "response_validation"),
])
def test_unclassified_get_failure_stays_blocked(isolated, monkeypatch,
                                                code, status, stage):
    captures, _scheduler, _run_state, _rows, _states = isolated
    state = _transient_fixture(captures, monkeypatch,
                               code=code, status=status, stage=stage)
    assert tick._sealed_transient_get(state) is None


def test_sealed_transient_gap_archived_before_any_new_get(isolated, monkeypatch):
    captures, scheduler, _run_state, rows, states = isolated
    (scheduler / "gaps").mkdir()
    prior = captures / "spot-BTCUSDT-20260915T010000Z"
    failed_output = captures / "spot-BTCUSDT-20260915T010500Z"
    old_state = {**_active(prior), "mode": "blocked",
                 "attempt_output_path": str(failed_output),
                 "blocked_reason": "continuation_failed:TickError"}
    old_raw = tick._canon(old_state)
    old_sha = tick._sha(old_raw)
    failed = {
        "failed_output_path": str(failed_output), "failed_batch_sha256": "d" * 64,
        "failed_attempt_record_sha256": "e" * 64,
        "failed_request_received_at": (
            datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat(),
        "failed_request_kind": "aggTrades", "failed_http_status": 503,
        "failed_failure_code": "HTTPError", "failed_requests_attempted": 3,
        "failed_cause_class": "sealed_timeout_or_http5xx_unavailability",
        "failed_backlog_unresolved": False,
        "old_sealed_at": (
            datetime.now(timezone.utc) - timedelta(minutes=21)).isoformat(),
    }
    monkeypatch.setattr(tick, "_state", lambda: (old_state, old_sha))
    monkeypatch.setattr(tick, "_sealed_transient_get", lambda _state: failed)
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
    seen = []

    def fake_capture(output_dir, *, symbol, from_id, max_pages):
        assert symbol == "BTCUSDT"
        assert list((scheduler / "gaps").glob("gap-*.json"))
        assert list((scheduler / "abandoned").glob(f"state-{old_sha}.json"))
        seen.append((from_id, max_pages))
        output_dir.mkdir()
        value = warmup if from_id is None else current
        (output_dir / "capture-batch.json").write_text(json.dumps(value) + "\n")
        return value

    monkeypatch.setattr(tick.collector, "capture_once", fake_capture)
    monkeypatch.setattr(tick, "_batch", lambda path: (
        (warmup, "g" * 64) if path.name.endswith("040000Z")
        else (current, "h" * 64)))
    result = tick.bootstrap_new(
        abandon_state_sha256=old_sha, max_wall_s=90, _held_lock=True,
        _verified_transient_gap=failed)
    gap = json.loads((scheduler / result["gap_relpath"]).read_text())
    assert seen == [(None, 1), (42, 32)]
    assert gap["reason"] == "verified_timeout_or_http5xx_new_lineage_after_cooldown"
    assert gap["failed_branch"] == failed
    assert gap["requests_attempted_before_gap_receipt"] == 3
    assert gap["cursor_linked_across_gap"] is False
    assert rows == [result] and states[-1]["mode"] == "active"


def test_blocked_transient_preserves_memory_preflight(isolated, monkeypatch):
    captures, _scheduler, _run_state, rows, _states = isolated
    tick.MEMINFO_PATH.write_text("MemAvailable: 1024 kB\n")
    state = {**_active(captures / "unused"), "mode": "blocked",
             "blocked_reason": "continuation_failed:TickError"}
    monkeypatch.setattr(tick, "_state", lambda: (state, "f" * 64))
    monkeypatch.setattr(tick, "_sealed_transient_get",
                        lambda _state: pytest.fail("memory gate inspected failed branch"))
    result = tick.run_once()
    assert result["status"] == "skipped_busy"
    assert result["reason"] == "memory_available_below_21gib"
    assert rows == [result] and result["requests_attempted"] == 0


def test_transient_get_waits_for_exact_600_second_cooldown(isolated, monkeypatch):
    captures, _scheduler, _run_state, rows, _states = isolated
    state = {**_active(captures / "unused"), "mode": "blocked",
             "blocked_reason": "continuation_failed:TickError"}
    failed_at = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
    failed = {"failed_request_received_at": failed_at.isoformat()}
    monkeypatch.setattr(tick, "_state", lambda: (state, "f" * 64))
    monkeypatch.setattr(tick, "_sealed_transient_get", lambda _state: failed)
    requested = []
    monkeypatch.setattr(tick, "bootstrap_new", lambda **kwargs: (
        requested.append(kwargs) or {"status": "bootstrapped_complete"}))

    class FrozenDatetime(datetime):
        current = failed_at + timedelta(seconds=599)

        @classmethod
        def now(cls, tz=None):
            return cls.current.astimezone(tz) if tz else cls.current

    monkeypatch.setattr(tick, "datetime", FrozenDatetime)
    assert tick.run_once()["status"] == "skipped_get_unavailability_cooldown"
    assert requested == [] and rows[-1]["reason"] == "sealed_get_unavailability_cooldown"
    FrozenDatetime.current = failed_at + timedelta(seconds=600)
    assert tick.run_once()["status"] == "bootstrapped_complete"
    assert len(requested) == 1


@pytest.mark.parametrize("failure_kind", ["http503", "urlerror"])
def test_real_collector_unavailability_replays_and_journal_tamper_blocks(
        isolated, monkeypatch, failure_kind):
    """Use the actual public GET collector and independent batch validator."""
    captures, _scheduler, _run_state, _rows, _states = isolated
    warmup = captures / "spot-BTCUSDT-20260915T010000Z"
    previous = captures / "spot-BTCUSDT-20260915T010001Z"
    failed = captures / "spot-BTCUSDT-20260915T010002Z"
    monkeypatch.setattr(tick, "_source_sha", tick._actual_collector_sha)
    monkeypatch.setattr(tick, "_continuation_sha", tick._actual_continuation_sha)

    class FakeResponse:
        status = 200

        def __init__(self, url, raw):
            self.url, self.raw = url, raw
            self.headers = {"Content-Type": "application/json"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def geturl(self):
            return self.url

        def read(self, _bound):
            return self.raw

    def fake_urlopen(request, *, timeout):
        assert timeout == tick.collector.REQUEST_TIMEOUT_S
        url = request.full_url
        kind = urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1]
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        if kind == "time":
            payload = {"serverTime": now_ms}
        elif kind == "depth":
            payload = {"lastUpdateId": 100,
                       "bids": [["99.0", "1.0"]],
                       "asks": [["101.0", "1.0"]]}
        else:
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
            from_id = int(query["fromId"][0]) if "fromId" in query else None
            if from_id == 3:
                if failure_kind == "http503":
                    raise urllib.error.HTTPError(url, 503, "upstream 503", None, None)
                raise urllib.error.URLError("network unavailable; reason unknown")
            trade_id = 1 if from_id is None else from_id
            payload = [{"a": trade_id, "T": now_ms - 1000, "m": False,
                        "p": "100.0", "q": "1.0"}]
        return FakeResponse(url, json.dumps(payload).encode())

    monkeypatch.setattr(tick.collector.urllib.request, "urlopen", fake_urlopen)
    first = tick.collector.capture_once(warmup, symbol="BTCUSDT",
                                         from_id=None, max_pages=1)
    assert first["initial_history_gap"] is True and first["next_aggregate_id"] == 2
    second = tick.collector.capture_once(previous, symbol="BTCUSDT",
                                          from_id=2, max_pages=8)
    assert second["status"] == "complete_incremental_batch"
    _prior, prior_sha = tick._batch(previous)
    report = tick.continuation.run_once(
        previous_batch=previous, bootstrap_warmup=warmup,
        output_dir=failed, max_pages=8, root=captures)
    assert report["status"] == "stopped_incomplete"
    failed_batch, failed_sha = tick._batch(failed)
    assert failed_batch["requests_attempted"] == 3
    assert failed_batch["requests_succeeded"] == 2
    assert failed_batch["requests_failed"] == 1

    state = {"schema": tick.STATE_SCHEMA, "symbol": "BTCUSDT",
             "collector_source_sha256": tick._source_sha(),
             "continuation_source_sha256": tick._continuation_sha(),
             "lineage_id": "h1-producer-test", "mode": "blocked",
             "bootstrap_warmup_path": str(warmup),
             "last_complete_path": str(previous),
             "last_complete_sha256": prior_sha,
             "attempt_output_path": str(failed),
             "blocked_reason": "continuation_failed:TickError",
             "updated_at": tick._now()}
    classified = tick._sealed_transient_get(state)
    assert classified is not None
    assert classified["failed_batch_sha256"] == failed_sha
    assert classified["failed_http_status"] == (503 if failure_kind == "http503" else None)
    assert classified["failed_cause_class"] == (
        "sealed_timeout_or_http5xx_unavailability" if failure_kind == "http503"
        else "sealed_transport_unavailability_unknown")

    journal = failed / "attempts.jsonl"
    original_journal = journal.read_bytes()
    code = b"HTTPError" if failure_kind == "http503" else b"URLError"
    journal.write_bytes(original_journal.replace(code, b"X" + code[1:]))
    assert tick._sealed_transient_get(state) is None
    journal.write_bytes(original_journal)
    batch_path = failed / "capture-batch.json"
    altered = json.loads(batch_path.read_text())
    altered["collector_source_sha256"] = "0" * 64
    batch_path.write_text(json.dumps(altered, sort_keys=True, indent=2) + "\n")
    assert tick._sealed_transient_get(state) is None
