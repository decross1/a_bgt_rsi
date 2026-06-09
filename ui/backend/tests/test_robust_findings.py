"""Robustness tests for /api/coordinator/findings (and the /active read-race).

The findings/bubbles/cycles/health_signals endpoints all read producer-owned,
gitignored JSONL with the shared ``coordinator._read_jsonl`` helper and then
``rows.sort(key=lambda r: r.get(...))``. That ``.get`` is the hazard: a single
bad line must never 500 the endpoint. This file pins the contract for the
``surfaced_findings.jsonl`` source specifically (per the validation handoff):

  (a) file absent              -> {"findings": []} (200, never 500)
  (b) malformed lines mixed in -> malformed skipped, valid served
  (c) non-dict JSON lines      -> a bare number/string/array/bool/null line is
                                  VALID JSON (survives json.loads) and would land
                                  in `rows` as a non-dict; `.get` on it raises
                                  AttributeError -> 500. They must be dropped.
  (d) a large file (5k rows)   -> served without error
  (e) /active read-race        -> exists() True but read_text() raises
                                  FileNotFoundError (producer deletes the file at
                                  cycle end) -> 204, not 500

Mirrors test_coordinator.py: TestClient against tmp_path via the
coordinator_run_state / coordinator_memory create_app params, no real
run_state/memory writes. ``raise_server_exceptions=False`` so a regressed
endpoint surfaces as an observed 500 (the thing we guard) instead of bubbling
the exception out of the test client.
"""
from __future__ import annotations

import json
import unittest.mock as mock
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import create_app


def _client(tmp_path) -> TestClient:
    """TestClient with every path pinned at tmp_path (the test_coordinator idiom).

    The coordinator run_state/memory dirs are intentionally NOT pre-created — the
    absent-file case relies on the dir being missing, and _read_jsonl/active
    tolerate that. Tests that need a file mkdir its parent themselves.
    ``raise_server_exceptions=False`` lets a regression be asserted as a 500
    response rather than raised out of the client.
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
    return TestClient(app, raise_server_exceptions=False)


def _findings_path(tmp_path) -> Path:
    return tmp_path / "coord_memory" / "surfaced_findings.jsonl"


# ─── (a) absent file ─────────────────────────────────────────────────────


def test_findings_absent_file_returns_empty_not_500(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/api/coordinator/findings")
    assert resp.status_code == 200
    assert resp.json() == {"findings": []}


# ─── (b) malformed lines interleaved with valid ──────────────────────────


def test_findings_skips_malformed_lines_serves_valid(tmp_path):
    client = _client(tmp_path)
    path = _findings_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Two valid dict rows bracketing genuinely un-parseable garbage lines.
    path.write_text(
        '{"finding_id":"a","promoted_at":"2026-06-09T10:00:00Z"}\n'
        "THIS IS NOT JSON {{{\n"
        "}{ broken\n"
        '{"finding_id":"b","promoted_at":"2026-06-08T10:00:00Z"}\n',
        encoding="utf-8",
    )
    resp = client.get("/api/coordinator/findings")
    assert resp.status_code == 200
    findings = resp.json()["findings"]
    # Malformed dropped; both valid rows served, newest-first by promoted_at.
    assert [f["finding_id"] for f in findings] == ["a", "b"]


# ─── (c) non-dict JSON lines (the .get hazard) ───────────────────────────


def test_findings_skips_non_dict_json_lines(tmp_path):
    """A bare number/string/array/bool/null is VALID JSON, so it survives
    json.loads and (pre-guard) lands in `rows` as a non-dict — then the
    endpoint's `rows.sort(key=lambda r: r.get("promoted_at"))` raises
    AttributeError → 500. Every non-dict line must be dropped like a malformed
    one, leaving only the real dict record."""
    client = _client(tmp_path)
    path = _findings_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "42\n"  # bare int
        '"just a string"\n'  # bare string
        "[1, 2, 3]\n"  # bare array
        "null\n"  # bare null
        "true\n"  # bare bool
        "3.14\n"  # bare float
        '{"finding_id":"only-real-row","promoted_at":"2026-06-09T10:00:00Z"}\n',
        encoding="utf-8",
    )
    resp = client.get("/api/coordinator/findings")
    assert resp.status_code == 200
    findings = resp.json()["findings"]
    assert [f["finding_id"] for f in findings] == ["only-real-row"]


def test_findings_all_non_dict_lines_yield_empty(tmp_path):
    """A file that is ENTIRELY non-dict JSON lines degrades to the clean empty
    state (200 + []), never a 500 from the sort."""
    client = _client(tmp_path)
    path = _findings_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('1\n"x"\n[]\nnull\nfalse\n', encoding="utf-8")
    resp = client.get("/api/coordinator/findings")
    assert resp.status_code == 200
    assert resp.json() == {"findings": []}


# ─── (d) large file ──────────────────────────────────────────────────────


def test_findings_large_file_served(tmp_path):
    client = _client(tmp_path)
    path = _findings_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {"finding_id": f"f{i}", "promoted_at": f"2026-06-09T{i % 24:02d}:00:00Z"}
        for i in range(5000)
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    resp = client.get("/api/coordinator/findings")
    assert resp.status_code == 200
    assert len(resp.json()["findings"]) == 5000


# ─── (e) /active exists()->read race ─────────────────────────────────────


def test_active_read_race_returns_204_not_500(tmp_path):
    """exists() may return True but read_text() then raises FileNotFoundError —
    the producer deletes active_run.json atomically at cycle end. The polling UI
    must see 204, not 500 (mirrors loop_v0.active and test_coordinator)."""
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
