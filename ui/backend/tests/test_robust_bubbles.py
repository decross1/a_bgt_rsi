"""Robustness tests for the coordinator data endpoints — the producer-owned
JSONL files (``memory/coordinator_bubbles.jsonl`` et al.) are written by the
primary-session spine and may be partial, legacy, or mid-append. A single
stray line must never 500 the endpoint that the auditor UI polls.

Focuses on ``/api/coordinator/bubbles`` and its shared reader (``_read_jsonl``),
plus the ``/active`` delete-race that the cycle-end teardown creates. Mirrors
``test_coordinator.py``'s TestClient-against-tmp_path idiom (no real CLI, no
real run_state/memory writes — every path points at tmp_path).

Categories (per the autonomy-observability hardening handoff):
  (a) file absent                       -> {"bubbles": []} (not 500)
  (b) malformed lines interleaved valid -> malformed skipped, valid served
  (c) non-dict JSON lines (bare scalar) -> skipped (the .get()-on-int 500 guard)
  (d) a large file (5k rows)            -> served without error
  (e) /active exists()->read race       -> 204, not 500
"""
from __future__ import annotations

import json
import unittest.mock as mock
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import create_app


def _client(tmp_path) -> TestClient:
    """Build a TestClient that points every path at tmp_path.

    Pins the non-coordinator paths at benign tmp fixtures (as test_coordinator
    does) so the other endpoints see nothing real, and points the coordinator
    run_state/memory dirs at tmp_path so we control the data files under test.
    """
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

    # Coordinator paths under test — intentionally NOT pre-created so the
    # absent-file path is the cold path the reader must tolerate.
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


def _bubbles_path(tmp_path) -> Path:
    return tmp_path / "coord_memory" / "coordinator_bubbles.jsonl"


# ─── (a) absent file ───────────────────────────────────────────────────


def test_bubbles_absent_file_is_empty_not_500(tmp_path):
    """No file (the gitignored cold path) → clean empty list, never a 500."""
    client = _client(tmp_path)
    resp = client.get("/api/coordinator/bubbles")
    assert resp.status_code == 200
    assert resp.json() == {"bubbles": []}


# ─── (b) malformed lines interleaved with valid ─────────────────────────


def test_bubbles_skips_malformed_lines_serves_valid(tmp_path):
    """A half-written append / truncated line is not valid JSON. It is skipped
    while the valid rows around it are still served (the endpoint stays useful
    while a primary-session producer bug is being fixed)."""
    client = _client(tmp_path)
    path = _bubbles_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"run_id": "b1", "timestamp": "2026-06-09T03:00:00Z", "note": "one"})
        + "\n"
        "this-is-not-json{{{\n"
        '{"run_id": "b2", "timestamp": "2026-06-09T02:00:00Z", "note": "two", \n'  # truncated mid-object
        + json.dumps({"run_id": "b3", "timestamp": "2026-06-09T01:00:00Z", "note": "three"})
        + "\n",
        encoding="utf-8",
    )
    resp = client.get("/api/coordinator/bubbles")
    assert resp.status_code == 200
    rows = resp.json()["bubbles"]
    # Only the three well-formed rows survive; newest-first by timestamp.
    assert [r["run_id"] for r in rows] == ["b1", "b3"]
    # The truncated b2 line was dropped, not partially reconstructed.
    assert all(r["run_id"] != "b2" for r in rows)


# ─── (c) non-dict JSON lines (the .get()-on-scalar 500 guard) ───────────


def test_bubbles_skips_non_dict_json_lines(tmp_path):
    """A bare scalar/array/null line is VALID JSON, so it survives json.loads
    and (without the guard) lands in `rows` as a non-dict. The endpoint then
    sorts via `r.get("timestamp")` — `.get` on an int/str/list/None raises
    AttributeError → one stray line 500s the whole endpoint. Regression: each
    non-dict line is dropped the same way a malformed line is."""
    client = _client(tmp_path)
    path = _bubbles_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"run_id": "b1", "timestamp": "2026-06-09T03:00:00Z", "note": "one"})
        + "\n"
        "42\n"  # bare int
        '"just a string"\n'  # bare string
        "[1, 2, 3]\n"  # bare array
        "null\n"  # JSON null -> Python None
        "true\n"  # bare bool
        + json.dumps({"run_id": "b2", "timestamp": "2026-06-09T02:00:00Z", "note": "two"})
        + "\n",
        encoding="utf-8",
    )
    resp = client.get("/api/coordinator/bubbles")
    # The headline: no 500 from the scalar lines hitting `.get()`.
    assert resp.status_code == 200
    rows = resp.json()["bubbles"]
    # Only the two dict rows survive, and every served row IS a dict.
    assert [r["run_id"] for r in rows] == ["b1", "b2"]
    assert all(isinstance(r, dict) for r in rows)


def test_bubbles_all_non_dict_lines_yields_empty(tmp_path):
    """A file of nothing but non-dict lines → empty list, not a 500 and not
    a list of bare scalars the frontend would crash rendering."""
    client = _client(tmp_path)
    path = _bubbles_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("1\n2\n[ ]\n\"x\"\nnull\n", encoding="utf-8")
    resp = client.get("/api/coordinator/bubbles")
    assert resp.status_code == 200
    assert resp.json() == {"bubbles": []}


# ─── (d) large file ─────────────────────────────────────────────────────


def test_bubbles_large_file_served(tmp_path):
    """5k rows are served in one read without error (the endpoint reads the
    whole file; this guards against a future change that would choke on size)."""
    client = _client(tmp_path)
    path = _bubbles_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "run_id": f"b{i:05d}",
            "timestamp": f"2026-06-09T{i % 24:02d}:{i % 60:02d}:00Z",
            "note": "x",
        }
        for i in range(5000)
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    resp = client.get("/api/coordinator/bubbles")
    assert resp.status_code == 200
    served = resp.json()["bubbles"]
    assert len(served) == 5000
    # Newest-first: the max timestamp sorts to the front.
    timestamps = [r.get("timestamp") or "" for r in served]
    assert timestamps == sorted(timestamps, reverse=True)


# ─── (e) /active exists()->read race ────────────────────────────────────


def test_active_delete_race_is_204_not_500(tmp_path):
    """The producer atomically deletes active_run.json at cycle end. exists()
    may return True but the subsequent read_text() then raises
    FileNotFoundError. The polling UI must see 204 (cycle just finished), not a
    500 (mirrors test_coordinator's active-race + loop_v0)."""
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
