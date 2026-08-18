"""GET /api/loop_v0/iterations ?fields= / ?limit= projection (perf, 2026-08-18).

The full payload measured 3.4 MB / 2.9 s on the live backend while Pulse's
sparkgrid needs only the timestamp column. These tests pin the projection:
no params = the exact historical full rows; ``fields`` keeps only requested
keys the row actually has (absent keys omitted, never invented as null);
``limit`` truncates AFTER the newest-first sort.

Register-fn direct (the test_served_models idiom) — only the loop_v0 router
is under test.
"""
from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.loop_v0 import register


ROWS = [
    {"iteration_id": "iter-001", "ended_at": "2026-05-24T11:00:00Z",
     "seed": {"topic": "a"}, "verdict": "NO"},
    {"iteration_id": "iter-003", "ended_at": "2026-05-26T14:00:00Z",
     "seed": {"topic": "c"}},  # deliberately NO verdict key
    {"iteration_id": "iter-002", "ended_at": "2026-05-25T19:00:00Z",
     "seed": {"topic": "b"}, "verdict": "YES"},
]


def _client(tmp_path) -> TestClient:
    memory = tmp_path / "loop_memory.jsonl"
    memory.write_text("\n".join(json.dumps(r) for r in ROWS) + "\n",
                      encoding="utf-8")
    app = FastAPI()
    register(app, repo_root=tmp_path, run_state_dir=tmp_path,
             journal_dir=tmp_path, loop_memory_path=memory)
    return TestClient(app)


def test_no_params_is_the_historical_full_payload(tmp_path):
    body = _client(tmp_path).get("/api/loop_v0/iterations").json()
    ids = [r["iteration_id"] for r in body["iterations"]]
    assert ids == ["iter-003", "iter-002", "iter-001"]
    assert body["iterations"][0]["seed"] == {"topic": "c"}  # full rows


def test_fields_projects_to_requested_columns_only(tmp_path):
    body = _client(tmp_path).get(
        "/api/loop_v0/iterations?fields=iteration_id,ended_at").json()
    rows = body["iterations"]
    assert [r["iteration_id"] for r in rows] == \
        ["iter-003", "iter-002", "iter-001"]
    for r in rows:
        assert set(r) == {"iteration_id", "ended_at"}


def test_fields_omits_absent_keys_never_invents_null(tmp_path):
    rows = _client(tmp_path).get(
        "/api/loop_v0/iterations?fields=iteration_id,verdict"
    ).json()["iterations"]
    by_id = {r["iteration_id"]: r for r in rows}
    assert by_id["iter-001"]["verdict"] == "NO"
    assert "verdict" not in by_id["iter-003"]  # omitted, not null


def test_limit_truncates_after_newest_first_sort(tmp_path):
    rows = _client(tmp_path).get(
        "/api/loop_v0/iterations?limit=2").json()["iterations"]
    assert [r["iteration_id"] for r in rows] == ["iter-003", "iter-002"]


def test_fields_and_limit_compose(tmp_path):
    rows = _client(tmp_path).get(
        "/api/loop_v0/iterations?fields=ended_at&limit=1").json()["iterations"]
    assert rows == [{"ended_at": "2026-05-26T14:00:00Z"}]
