"""Robustness tests for the autonomy-observability read endpoints — the
adversarial-input half of test_coordinator.py. The producer (the primary
session's coordinator spine) owns these gitignored JSONL/JSON files; the UI
reads them live, so a half-written append, a stray non-object line, a giant
backlog, or the active-file delete-race must DEGRADE (skip the bad row / 204),
never 500. A coordinator cycle that ran "dark" is exactly when the human reaches
for this UI; a single bad byte must not blank it.

Centered on ``GET /api/coordinator/active`` (single-object ``active_run.json``)
and the shared ``_read_jsonl`` reader behind the list endpoints (exercised via
``/api/coordinator/cycles``). Mirrors test_coordinator.py's TestClient-against-
tmp_path idiom (coordinator_run_state / coordinator_memory create_app params);
side-effect-free, no real run_state/memory writes.
"""
from __future__ import annotations

import json
import unittest.mock as mock
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import create_app


def _client(tmp_path) -> TestClient:
    """Build a TestClient with every path pinned at tmp_path (as test_coordinator
    does). The coordinator dirs are intentionally NOT pre-created — the
    absent-file cases rely on that; cases that need a file mkdir it themselves."""
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


def _active_path(tmp_path) -> Path:
    return tmp_path / "coord_run_state" / "active_run.json"


def _cycles_path(tmp_path) -> Path:
    return tmp_path / "coord_run_state" / "coordinator_cycles.jsonl"


# ─── /active (single-object active_run.json) ─────────────────────────────


def test_active_absent_returns_204(tmp_path):
    """(a) The file is absent (the common cold path — no cycle in flight, and
    the gitignored file may simply never have been written)."""
    client = _client(tmp_path)
    resp = client.get("/api/coordinator/active")
    assert resp.status_code == 204
    assert resp.content == b""


def test_active_present_object_served(tmp_path):
    """A well-shaped live cycle is served verbatim (the happy path the
    robustness cases degrade toward)."""
    client = _client(tmp_path)
    active = {
        "kind": "coordinator",
        "run_id": "coordinator_live",
        "current_step": "dispatch",
        "narration": "Chose an arxiv_pick topic; dispatching a loop iteration.",
    }
    path = _active_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(active), encoding="utf-8")
    resp = client.get("/api/coordinator/active")
    assert resp.status_code == 200
    assert resp.json() == active


def test_active_delete_race_returns_204_not_500(tmp_path):
    """(e) The exists()->read race: the producer atomically deletes
    active_run.json at cycle end, so exists() may return True but the
    subsequent read_text() raises FileNotFoundError. The polling UI must see
    204 (cycle just finished), never a 500. Mirrors loop_v0.active."""
    client = _client(tmp_path)
    path = _active_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"kind": "coordinator"}), encoding="utf-8")

    real_read_text = type(path).read_text

    def race_read_text(self, *args, **kwargs):
        # Only the active-run path disappears mid-read; everything else reads
        # normally (don't break the unrelated reads create_app may do).
        if str(self) == str(path):
            raise FileNotFoundError(str(self))
        return real_read_text(self, *args, **kwargs)

    with mock.patch.object(type(path), "read_text", race_read_text):
        resp = client.get("/api/coordinator/active")
    assert resp.status_code == 204
    assert resp.content == b""


def test_active_malformed_json_is_500_not_silent(tmp_path):
    """A truncated/half-written active_run.json (invalid JSON, the file exists
    and reads) is a real producer fault for a single-object file and surfaces
    as 500 — NOT silently coerced to an empty 204 (inviolate rule 4: a failure
    is reported, never recoded). Distinct from the delete-race, which is a
    legitimate end-of-cycle 204."""
    client = _client(tmp_path)
    path = _active_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"kind": "coordinator", "narration": ', encoding="utf-8")
    resp = client.get("/api/coordinator/active")
    assert resp.status_code == 500


# ─── shared _read_jsonl reader (via /cycles) ─────────────────────────────


def test_cycles_absent_returns_empty(tmp_path):
    """(a) The list file is absent -> empty list, never 500."""
    client = _client(tmp_path)
    resp = client.get("/api/coordinator/cycles")
    assert resp.status_code == 200
    assert resp.json() == {"cycles": []}


def test_cycles_malformed_lines_interleaved_skipped(tmp_path):
    """(b) Malformed (non-JSON) lines interleaved with valid rows — a
    half-flushed append or a truncated final line — are skipped; the valid rows
    are still served, never a 500."""
    client = _client(tmp_path)
    path = _cycles_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '{"run_id":"a","timestamp":"2026-06-09T00:00:00Z"}\n'
        "this-line-is-not-json\n"
        '{"run_id":"b","timestamp":"2026-06-08T00:00:00Z"}\n'
        '{"run_id":"c","timestamp":"2026-06-07T00:00:00Z"\n'  # truncated, no close
        '{"run_id":"d","timestamp":"2026-06-06T00:00:00Z"}\n',
        encoding="utf-8",
    )
    resp = client.get("/api/coordinator/cycles")
    assert resp.status_code == 200
    ids = [c["run_id"] for c in resp.json()["cycles"]]
    # Valid rows survive in newest-first order; the two malformed lines vanish.
    assert ids == ["a", "b", "d"]


def test_cycles_non_dict_json_lines_skipped(tmp_path):
    """(c) Non-dict JSON lines — a bare number, string, array, null, or bool on
    their own line — are VALID JSON (so they pass the JSONDecodeError guard) but
    have no ``.get``; the newest-first sort would 500 on them. They must be
    skipped like malformed lines, leaving the real dict rows served."""
    client = _client(tmp_path)
    path = _cycles_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '{"run_id":"a","timestamp":"2026-06-09T00:00:00Z"}\n'
        "42\n"
        '"a bare string row"\n'
        "[1, 2, 3]\n"
        "null\n"
        "true\n"
        '{"run_id":"b","timestamp":"2026-06-08T00:00:00Z"}\n',
        encoding="utf-8",
    )
    resp = client.get("/api/coordinator/cycles")
    assert resp.status_code == 200
    ids = [c["run_id"] for c in resp.json()["cycles"]]
    assert ids == ["a", "b"]


def test_cycles_large_file_served(tmp_path):
    """(d) A large backlog (5k rows) is served without error — the reader stays
    linear and never falls over on volume."""
    client = _client(tmp_path)
    path = _cycles_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {"run_id": f"r{i:05d}", "timestamp": f"2026-06-09T{i % 24:02d}:00:00Z"}
        for i in range(5000)
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    resp = client.get("/api/coordinator/cycles")
    assert resp.status_code == 200
    assert len(resp.json()["cycles"]) == 5000


def test_cycles_large_file_with_garbage_interleaved_served(tmp_path):
    """(b)+(c)+(d) together — the realistic worst case: a large file where
    malformed and non-dict lines are sprinkled through. Every valid dict row is
    served; the count equals only the valid rows; no 500."""
    client = _client(tmp_path)
    path = _cycles_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    valid = 0
    for i in range(5000):
        if i % 500 == 0:
            lines.append("not-json-garbage")
        elif i % 500 == 1:
            lines.append("12345")  # bare number
        else:
            lines.append(
                json.dumps(
                    {"run_id": f"r{i:05d}", "timestamp": f"2026-06-09T{i % 24:02d}:00:00Z"}
                )
            )
            valid += 1
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    resp = client.get("/api/coordinator/cycles")
    assert resp.status_code == 200
    assert len(resp.json()["cycles"]) == valid
