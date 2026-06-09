"""Robustness tests for GET /api/coordinator/health_signals (and the shared
``coordinator._read_jsonl`` it rides on). The endpoint reads a producer-owned,
gitignored, append-only JSONL (``run_state/health_signals.jsonl``) the UI does
not control — so it must survive a file that is absent, partially written, or
carrying non-record lines, and never return a 500 to the polling dashboard.

Side-effect-free: every path points at tmp_path (the test_coordinator.py
TestClient-against-tmp_path idiom via create_app's coordinator_run_state /
coordinator_memory params). Covers:

  (a) file absent                       -> 200 {"health_signals": []}
  (b) malformed lines among valid ones  -> malformed skipped, valid served
  (c) non-dict JSON lines (bare scalar/ -> skipped (no AttributeError 500 from
      string/array)                        the .get() sort key); regression for
                                           the real bug fixed in coordinator.py
  (d) a large file (5k rows)            -> served, all rows, newest-first
  (e) the active-run exists()->read race (file deleted mid-read) -> 204 not 500
      [/active only — the one endpoint with read-after-exists]
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import create_app


def _client(tmp_path) -> TestClient:
    """Build a TestClient pointing every path at tmp_path (mirrors
    test_coordinator._client). The coordinator dirs are intentionally left
    un-pre-created so the absent-file path is exercised; tests that need a file
    mkdir it themselves."""
    (tmp_path / "logs").mkdir(exist_ok=True)
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"current_day": "coordinator"}), encoding="utf-8")
    telemetry = tmp_path / "telemetry.jsonl"
    telemetry.write_text("", encoding="utf-8")
    bench = tmp_path / "day1.csv"
    bench.write_text(
        "prompt_idx,completion_tokens,elapsed_s,decode_tok_per_s\n0,256,8.0,32.0\n",
        encoding="utf-8",
    )
    mtp = tmp_path / "mtp.csv"

    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    loop_run_state = tmp_path / "loop_run_state"
    loop_run_state.mkdir(exist_ok=True)
    journal_dir = tmp_path / "journal"
    journal_dir.mkdir(exist_ok=True)
    loop_memory = tmp_path / "loop_memory.jsonl"

    coord_run_state = tmp_path / "coord_run_state"
    coord_memory = tmp_path / "coord_memory"

    app = create_app(
        logs_dir=tmp_path / "logs",
        telemetry_file=telemetry,
        state_file=state,
        bench_csv=bench,
        mtp_csv=mtp,
        loop_v0_repo=repo,
        loop_v0_run_state=loop_run_state,
        loop_v0_journal=journal_dir,
        loop_v0_memory=loop_memory,
        coordinator_run_state=coord_run_state,
        coordinator_memory=coord_memory,
    )
    return TestClient(app)


def _hs_path(tmp_path) -> Path:
    return tmp_path / "coord_run_state" / "health_signals.jsonl"


def _valid_signal(ts: str, signal: str) -> dict:
    return {
        "timestamp": ts,
        "run_id": "cyc-x",
        "signal": signal,
        "severity": "degraded",
        "detail": f"{signal} fired",
    }


# ─── (a) absent file ─────────────────────────────────────────────────────


def test_health_signals_absent_file_returns_empty(tmp_path):
    """The producer is gitignored and may never have run — absent file is the
    cold path, not an error. 200 with an empty list, not a 404/500."""
    client = _client(tmp_path)
    resp = client.get("/api/coordinator/health_signals")
    assert resp.status_code == 200
    assert resp.json() == {"health_signals": []}


# ─── (b) malformed lines interleaved with valid ones ─────────────────────


def test_health_signals_skips_malformed_lines_serves_valid(tmp_path):
    """A half-written append / truncated line is unparseable JSON. It is
    skipped; the surrounding valid rows still serve (never a 500). Blank lines
    are ignored too."""
    client = _client(tmp_path)
    path = _hs_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_valid_signal("2026-06-09T10:00:00Z", "ml_intern_zero_papers"))
        + "\n"
        + "{not-valid-json, truncated append\n"
        + "\n"  # blank line
        + json.dumps(_valid_signal("2026-06-09T11:00:00Z", "qwen_degraded_empty_content"))
        + "\n",
        encoding="utf-8",
    )
    resp = client.get("/api/coordinator/health_signals")
    assert resp.status_code == 200
    signals = resp.json()["health_signals"]
    # Both valid rows survive; the malformed/blank lines are dropped.
    assert [s["signal"] for s in signals] == [
        "qwen_degraded_empty_content",
        "ml_intern_zero_papers",
    ]


# ─── (c) non-dict JSON lines ─────────────────────────────────────────────


def test_health_signals_skips_non_dict_json_lines(tmp_path):
    """Regression: a bare number / string / array is VALID JSON, so it survives
    json.loads and (pre-fix) landed in `rows` as a non-dict. The endpoint's
    `rows.sort(key=lambda r: r.get("timestamp") ...)` then raised
    AttributeError on `.get` → a 500 from one stray line. Such lines are now
    dropped like a malformed one; the dict rows still serve."""
    client = _client(tmp_path)
    path = _hs_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                json.dumps(
                    _valid_signal("2026-06-09T10:00:00Z", "ml_intern_zero_papers")
                ),
                "42",  # bare number
                json.dumps("a bare string"),  # bare string
                json.dumps([1, 2, 3]),  # bare array
                "null",  # bare null
                json.dumps(
                    _valid_signal(
                        "2026-06-09T11:00:00Z", "qwen_degraded_empty_content"
                    )
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    resp = client.get("/api/coordinator/health_signals")
    assert resp.status_code == 200  # not a 500
    signals = resp.json()["health_signals"]
    assert [s["signal"] for s in signals] == [
        "qwen_degraded_empty_content",
        "ml_intern_zero_papers",
    ]


def test_health_signals_all_non_dict_lines_returns_empty(tmp_path):
    """A file made up ENTIRELY of non-dict lines (e.g. a producer that wrote a
    bare-array log by mistake) degrades to an empty list, not a 500."""
    client = _client(tmp_path)
    path = _hs_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("1\n2\n\"x\"\n[]\nnull\n", encoding="utf-8")
    resp = client.get("/api/coordinator/health_signals")
    assert resp.status_code == 200
    assert resp.json() == {"health_signals": []}


# ─── (d) large file ──────────────────────────────────────────────────────


def test_health_signals_large_file_served(tmp_path):
    """A long-running loop produces a large append-only log. 5k rows serve
    without error and stay newest-first by timestamp."""
    client = _client(tmp_path)
    path = _hs_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 5000
    lines = [
        json.dumps(
            {
                "timestamp": f"2026-06-09T{(i % 24):02d}:{(i % 60):02d}:00Z",
                "run_id": f"cyc-{i}",
                "signal": "ml_intern_zero_papers",
                "severity": "degraded",
                "seq": i,
            }
        )
        for i in range(n)
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    resp = client.get("/api/coordinator/health_signals")
    assert resp.status_code == 200
    signals = resp.json()["health_signals"]
    assert len(signals) == n
    # Newest-first: the returned timestamps are non-increasing.
    timestamps = [s["timestamp"] for s in signals]
    assert timestamps == sorted(timestamps, reverse=True)


# ─── (e) active-run exists()->read race (the one read-after-exists path) ──


def test_active_returns_204_when_file_deleted_mid_read(tmp_path):
    """The producer atomically deletes active_run.json at cycle end. exists()
    can return True, then read_text() raises FileNotFoundError. The polling UI
    must get a 204 (cold path), never a 500. (health_signals has no
    read-after-exists window — _read_jsonl re-checks via open() inside its own
    try — so the race lives on /active; assert it here per the brief.)"""
    import unittest.mock as mock

    client = _client(tmp_path)
    path = tmp_path / "coord_run_state" / "active_run.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"kind": "coordinator"}), encoding="utf-8")

    real_read_text = type(path).read_text

    def race_read_text(self, *args, **kwargs):
        if str(self) == str(path):
            raise FileNotFoundError(str(self))
        return real_read_text(self, *args, **kwargs)

    with mock.patch.object(type(path), "read_text", race_read_text):
        resp = client.get("/api/coordinator/active")
    assert resp.status_code == 204
    assert resp.content == b""
