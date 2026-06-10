"""Offline tests for the per-call inference-internals emitter."""
from __future__ import annotations

import json

import pytest

from agent_wrapper import worker_activity
from agent_wrapper.worker_activity import emit_worker_activity


def _read_rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_emits_row_with_correct_throughput(tmp_path):
    log_path = tmp_path / "worker_activity.jsonl"
    emit_worker_activity(
        run_id="run-1",
        task_id="task-7",
        output_tokens=200,
        max_tokens=500,
        latency_ms=2000.0,
        timestamp="2026-06-06T00:00:00Z",
        log_path=log_path,
    )

    rows = _read_rows(log_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["timestamp"] == "2026-06-06T00:00:00Z"
    assert row["run_id"] == "run-1"
    assert row["task_id"] == "task-7"
    assert row["tokens_generated"] == 200
    assert row["tokens_target"] == 500
    # 200 tokens / 2.0 s = 100 tok/s
    assert row["tok_per_s"] == 100.0
    # (500 - 200) / 100 = 3.0 s
    assert row["eta_s"] == 3.0
    assert row["synthetic"] is False


def test_appends_rather_than_overwrites(tmp_path):
    log_path = tmp_path / "worker_activity.jsonl"
    for i in range(3):
        emit_worker_activity(
            run_id="run-1",
            task_id=f"task-{i}",
            output_tokens=10,
            max_tokens=20,
            latency_ms=1000.0,
            timestamp="2026-06-06T00:00:00Z",
            log_path=log_path,
        )
    rows = _read_rows(log_path)
    assert [r["task_id"] for r in rows] == ["task-0", "task-1", "task-2"]


def test_zero_latency_gives_zero_rate_and_null_eta(tmp_path):
    log_path = tmp_path / "worker_activity.jsonl"
    emit_worker_activity(
        run_id="run-1",
        task_id="task-7",
        output_tokens=200,
        max_tokens=500,
        latency_ms=0,
        timestamp="2026-06-06T00:00:00Z",
        log_path=log_path,
    )
    row = _read_rows(log_path)[0]
    assert row["tok_per_s"] == 0.0
    assert row["eta_s"] is None


def test_eta_never_negative(tmp_path):
    # output already exceeds target -> eta floors at 0
    log_path = tmp_path / "worker_activity.jsonl"
    emit_worker_activity(
        run_id="run-1",
        task_id="task-7",
        output_tokens=600,
        max_tokens=500,
        latency_ms=1000.0,
        timestamp="2026-06-06T00:00:00Z",
        log_path=log_path,
    )
    row = _read_rows(log_path)[0]
    assert row["eta_s"] == 0.0


def test_never_raises_when_log_path_unwritable(tmp_path, monkeypatch):
    def _boom(*args, **kwargs):
        raise OSError("disk on fire")

    monkeypatch.setattr("builtins.open", _boom)
    # Must return cleanly, not raise.
    result = emit_worker_activity(
        run_id="run-1",
        task_id="task-7",
        output_tokens=200,
        max_tokens=500,
        latency_ms=2000.0,
        timestamp="2026-06-06T00:00:00Z",
        log_path=tmp_path / "worker_activity.jsonl",
    )
    assert result is None


def test_default_log_path_points_at_logs_dir():
    """Pin the PRODUCTION default. The autouse _no_live_artifacts guard
    (tests/conftest.py, D-048) patches the runtime attribute to tmp for
    every test, so reload the module to observe the source-defined value;
    the guard's monkeypatch teardown restores its own state afterwards."""
    import importlib

    mod = importlib.reload(worker_activity)
    assert mod.DEFAULT_LOG_PATH.name == "worker_activity.jsonl"
    assert mod.DEFAULT_LOG_PATH.parent.name == "logs"
