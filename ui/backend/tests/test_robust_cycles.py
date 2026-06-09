"""Robustness tests for the coordinator JSONL endpoints — a stray producer
line must NEVER 500 the panel (the autonomy-observability surface is a
human-as-auditor view; a hard error there is worse than a skipped row).

Mirrors test_coordinator.py's TestClient-against-tmp_path idiom (side-effect
free: every path points at tmp_path, no real run_state/memory reads/writes).

Covers, for the /cycles source helper (`_read_jsonl`) and the /active reader:
  (a) file absent                         -> empty body / 204, not 500
  (b) malformed lines interleaved w/ valid -> malformed skipped, valid served
  (c) non-dict JSON lines (bare number /   -> skipped (regression: a bare scalar
      string / array)                          is VALID JSON, survives json.loads,
                                               and `.get` on it crashed the sort)
  (d) a large file (5k rows)               -> served, newest-first, no error
  (e) /active exists()->read race          -> 204, not 500 (file deleted mid-read)

The non-dict case (c) is the real fixed bug: `_read_jsonl` appended whatever
`json.loads` returned, so a line like ``42`` landed in `rows`, and the
endpoint's ``rows.sort(key=lambda r: r.get("timestamp"))`` then raised
``AttributeError: 'int' object has no attribute 'get'`` — an unhandled 500.
The same helper backs /cycles, /findings, /bubbles, /health_signals, so the
regression is asserted on /cycles and spot-checked across the others.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import create_app


def _client(tmp_path) -> TestClient:
    """Build a TestClient with every path under tmp_path (mirrors
    test_coordinator._client). The coordinator dirs are intentionally NOT
    pre-created so the absent-file paths exercise the missing-dir branch."""
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


def _cycles_path(tmp_path) -> Path:
    p = tmp_path / "coord_run_state" / "coordinator_cycles.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


# ─── (a) absent file ─────────────────────────────────────────────────────


def test_cycles_absent_file_is_empty_not_500(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/api/coordinator/cycles")
    assert resp.status_code == 200
    assert resp.json() == {"cycles": []}


def test_active_absent_file_is_204_not_500(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/api/coordinator/active")
    assert resp.status_code == 204
    assert resp.content == b""


# ─── (b) malformed lines interleaved with valid ──────────────────────────


def test_cycles_malformed_lines_skipped_valid_served(tmp_path):
    """A garbage line between valid rows is skipped; the valid rows are still
    served newest-first. Never a 500."""
    client = _client(tmp_path)
    _cycles_path(tmp_path).write_text(
        '{"run_id":"a","timestamp":"2026-06-09T03:00:00Z"}\n'
        "{this is not valid json at all]\n"
        "\n"  # blank line — also skipped
        '{"run_id":"b","timestamp":"2026-06-09T01:00:00Z"}\n'
        "}{\n"  # more garbage
        '{"run_id":"c","timestamp":"2026-06-09T02:00:00Z"}\n',
        encoding="utf-8",
    )
    resp = client.get("/api/coordinator/cycles")
    assert resp.status_code == 200
    ids = [c["run_id"] for c in resp.json()["cycles"]]
    # only the 3 valid rows, newest (03:00) -> oldest (01:00)
    assert ids == ["a", "c", "b"]


# ─── (c) non-dict JSON lines (the regression for the real fixed bug) ──────


def test_cycles_non_dict_lines_skipped_not_500(tmp_path):
    """Regression. A bare scalar/array line is VALID JSON, so it survives
    json.loads; before the fix it landed in `rows` and the newest-first sort
    did `.get` on it -> AttributeError -> 500. Now it is dropped like a
    malformed line, and the dict rows are served unharmed."""
    client = _client(tmp_path)
    _cycles_path(tmp_path).write_text(
        '{"run_id":"a","timestamp":"2026-06-09T02:00:00Z"}\n'
        "42\n"  # bare number
        '"just-a-string"\n'  # bare string
        "[1, 2, 3]\n"  # bare array
        "true\n"  # bare bool
        "null\n"  # bare null
        '{"run_id":"b","timestamp":"2026-06-09T01:00:00Z"}\n',
        encoding="utf-8",
    )
    resp = client.get("/api/coordinator/cycles")
    assert resp.status_code == 200
    cycles = resp.json()["cycles"]
    # only the two dict rows survive; the five non-dict lines are gone.
    assert [c["run_id"] for c in cycles] == ["a", "b"]


def test_cycles_only_non_dict_lines_yields_empty(tmp_path):
    """A file of nothing but bare scalars/arrays must serve an empty list
    (not 500, not a list of scalars)."""
    client = _client(tmp_path)
    _cycles_path(tmp_path).write_text("1\n2\n[]\n\"x\"\nnull\n", encoding="utf-8")
    resp = client.get("/api/coordinator/cycles")
    assert resp.status_code == 200
    assert resp.json() == {"cycles": []}


def test_all_jsonl_endpoints_tolerate_non_dict_lines(tmp_path):
    """The same `_read_jsonl` helper backs findings / bubbles / health_signals;
    a bare-scalar line interleaved with a valid dict must not 500 any of them."""
    client = _client(tmp_path)
    crs = tmp_path / "coord_run_state"
    cm = tmp_path / "coord_memory"
    crs.mkdir(parents=True, exist_ok=True)
    cm.mkdir(parents=True, exist_ok=True)

    (cm / "surfaced_findings.jsonl").write_text(
        "123\n"
        '{"finding_id":"f1","promoted_at":"2026-06-09T00:00:00Z"}\n',
        encoding="utf-8",
    )
    (cm / "coordinator_bubbles.jsonl").write_text(
        '"oops"\n'
        '{"run_id":"b1","timestamp":"2026-06-09T00:00:00Z"}\n',
        encoding="utf-8",
    )
    (crs / "health_signals.jsonl").write_text(
        "[1, 2]\n"
        '{"signal":"s1","timestamp":"2026-06-09T00:00:00Z"}\n',
        encoding="utf-8",
    )

    rf = client.get("/api/coordinator/findings")
    assert rf.status_code == 200
    assert [f["finding_id"] for f in rf.json()["findings"]] == ["f1"]

    rb = client.get("/api/coordinator/bubbles")
    assert rb.status_code == 200
    assert [b["run_id"] for b in rb.json()["bubbles"]] == ["b1"]

    rh = client.get("/api/coordinator/health_signals")
    assert rh.status_code == 200
    assert [s["signal"] for s in rh.json()["health_signals"]] == ["s1"]


# ─── (d) a large file ────────────────────────────────────────────────────


def test_cycles_large_file_served_without_error(tmp_path):
    """5k rows: served in one shot, newest-first, no error. Guards against an
    accidental O(n^2)/recursion regression in the read+sort path."""
    client = _client(tmp_path)
    n = 5000
    lines = []
    for i in range(n):
        # ascending timestamps; row i older than row i+1
        ts = f"2026-06-09T{i // 3600:02d}:{(i // 60) % 60:02d}:{i % 60:02d}Z"
        lines.append(json.dumps({"run_id": f"cyc-{i:05d}", "timestamp": ts}))
    _cycles_path(tmp_path).write_text("\n".join(lines) + "\n", encoding="utf-8")

    resp = client.get("/api/coordinator/cycles")
    assert resp.status_code == 200
    cycles = resp.json()["cycles"]
    assert len(cycles) == n
    # newest-first: the highest-index (latest timestamp) row leads.
    assert cycles[0]["run_id"] == f"cyc-{n - 1:05d}"
    assert cycles[-1]["run_id"] == "cyc-00000"


# ─── (e) active exists()->read race ──────────────────────────────────────


def test_active_file_deleted_mid_read_is_204_not_500(tmp_path):
    """The producer atomically deletes active_run.json at cycle end; exists()
    can return True while the subsequent read_text() raises FileNotFoundError.
    The polling UI must see 204, not 500."""
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
