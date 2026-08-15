"""Stale-run reaping (2026-08-15).

Two June registry entries were still rendering on the dashboard as runs with
"stale heartbeat — last sign of life 82902m ago" (57 days): sessions that died
without clear_active_run(). Reaping is explicit and append-only — the doc moves
to active_runs/abandoned/ with a recorded reason, never deleted — so a
post-mortem can still read what the run was doing.
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from orchestrator import active_run


@pytest.fixture(autouse=True)
def _tmp_registry(tmp_path, monkeypatch):
    monkeypatch.setattr(active_run, "ACTIVE_RUN_PATH", tmp_path / "active_run.json")
    monkeypatch.setattr(active_run, "RUNS_DIR", tmp_path / "active_runs")
    (tmp_path / "active_runs").mkdir()
    return tmp_path


def _write(tmp_path, run_id, *, hours_old, kind="ad_hoc"):
    ts = (datetime.now(timezone.utc) - timedelta(hours=hours_old)).isoformat()
    doc = {"run_id": run_id, "kind": kind, "label": f"label {run_id}",
           "started_at": ts, "heartbeat_at": ts}
    (tmp_path / "active_runs" / f"{run_id}.json").write_text(json.dumps(doc))
    return doc


def test_stale_entry_is_moved_not_deleted(_tmp_registry):
    _write(_tmp_registry, "dead-run", hours_old=57 * 24)
    reaped = active_run.reap_stale_runs(log=lambda row: None)
    assert [r["run_id"] for r in reaped] == ["dead-run"]
    assert not (_tmp_registry / "active_runs" / "dead-run.json").exists()
    moved = _tmp_registry / "active_runs" / "abandoned" / "dead-run.json"
    assert moved.exists(), "reaped runs are MOVED, never deleted"
    doc = json.loads(moved.read_text())
    assert doc["run_id"] == "dead-run"
    assert "abandoned_at" in doc and "heartbeat older than" in doc["abandoned_reason"]


def test_fresh_entry_is_left_alone(_tmp_registry):
    _write(_tmp_registry, "live-run", hours_old=0.1)
    assert active_run.reap_stale_runs(log=lambda row: None) == []
    assert (_tmp_registry / "active_runs" / "live-run.json").exists()


def test_unreadable_timestamp_is_never_reaped_on_a_guess(_tmp_registry):
    (_tmp_registry / "active_runs" / "weird.json").write_text(
        json.dumps({"run_id": "weird", "heartbeat_at": "not-a-date"}))
    assert active_run.reap_stale_runs(log=lambda row: None) == []
    assert (_tmp_registry / "active_runs" / "weird.json").exists()


def test_reaping_clears_a_mirror_owned_by_the_dead_run(_tmp_registry):
    doc = _write(_tmp_registry, "dead-owner", hours_old=48)
    (_tmp_registry / "active_run.json").write_text(json.dumps(doc))
    active_run.reap_stale_runs(log=lambda row: None)
    assert not (_tmp_registry / "active_run.json").exists()


def test_reaping_leaves_a_mirror_owned_by_someone_else(_tmp_registry):
    _write(_tmp_registry, "dead-run", hours_old=48)
    (_tmp_registry / "active_run.json").write_text(
        json.dumps({"run_id": "other-live-run"}))
    active_run.reap_stale_runs(log=lambda row: None)
    assert (_tmp_registry / "active_run.json").exists()


def test_each_reap_emits_a_run_log_row(_tmp_registry):
    _write(_tmp_registry, "dead-a", hours_old=10)
    _write(_tmp_registry, "dead-b", hours_old=20)
    rows = []
    active_run.reap_stale_runs(log=rows.append)
    assert len(rows) == 2
    for row in rows:
        assert row["task_id"] == "reap_stale_run"
        assert row["agent"] == "active_run"
        assert row["status"] == "passed"


def test_threshold_is_honored(_tmp_registry):
    _write(_tmp_registry, "three-hours", hours_old=3)
    assert active_run.reap_stale_runs(stale_hours=4, log=lambda r: None) == []
    assert len(active_run.reap_stale_runs(stale_hours=2, log=lambda r: None)) == 1


def test_missing_registry_dir_is_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(active_run, "ACTIVE_RUN_PATH", tmp_path / "active_run.json")
    monkeypatch.setattr(active_run, "RUNS_DIR", tmp_path / "nope")
    assert active_run.reap_stale_runs(log=lambda r: None) == []
