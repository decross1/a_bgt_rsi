"""Coordinator (autonomy-observability) endpoint tests. Side-effect-free:
no real CLI invocation, no real run_state/memory writes — every path points
at tmp_path. Mirrors test_loop_v0.py's TestClient-against-tmp_path idiom.

Asserts the /cycles endpoint returns empty when its (gitignored) data file
is absent, and newest-first rows when tmp files are written — including a
cycle with an "errored" outcome carrying an error string + a dispatched
iteration id. (The active/findings/bubbles/health_signals sibling endpoints
were retired in UI simplification S3.)
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import create_app


def _client(tmp_path) -> TestClient:
    """Build a TestClient that points every path at tmp_path.

    Pins the non-coordinator paths at benign tmp fixtures (as test_loop_v0
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
    # loop_v0 paths — kept distinct so loop_v0's endpoints don't collide with
    # the coordinator dirs under test.
    loop_run_state = tmp_path / "loop_run_state"
    loop_run_state.mkdir(exist_ok=True)
    journal_dir = tmp_path / "journal"
    journal_dir.mkdir(exist_ok=True)
    loop_memory = tmp_path / "loop_memory.jsonl"

    # Coordinator paths under test. NOTE: the dirs are intentionally NOT
    # pre-created — the absent-file tests rely on them being empty, and
    # _read_jsonl/active tolerate a missing dir. Tests that need a file mkdir
    # it themselves.
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


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


# ─── cycles ────────────────────────────────────────────────────────────


def test_cycles_empty_when_log_missing(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/api/coordinator/cycles")
    assert resp.status_code == 200
    assert resp.json() == {"cycles": []}


def test_cycles_returns_newest_first_with_errored_outcome(tmp_path):
    client = _client(tmp_path)
    rows = [
        {
            "timestamp": "2026-06-09T10:00:00Z",
            "run_id": "cyc-001",
            "agent": "coordinator",
            "topic": "Truthfulness of VCG in combinatorial auctions",
            "topic_source": "coordinator",
            "plan": [{"action": "run_loop_iteration", "args": {"k": 8}}],
            "outcomes": [{"action": "run_loop_iteration", "status": "passed"}],
            "dispatched_iteration_id": "iter-2026-06-09-001",
            "promoted_finding_ids": ["find-001"],
            "bubble_run_ids": ["cyc-001"],
        },
        {
            "timestamp": "2026-06-09T11:30:00Z",
            "run_id": "cyc-002",
            "agent": "coordinator",
            "topic": "code-quality heuristics for PR review",
            "topic_source": "arxiv_pick",
            "plan": [{"action": "run_loop_iteration", "args": {}}],
            # The headline failed-dispatch case: errored + a real error string.
            "outcomes": [
                {
                    "action": "run_loop_iteration",
                    "status": "errored",
                    "error": "ValueError: 'code_quality' is not a valid SeedSource enum",
                }
            ],
            "dispatched_iteration_id": "iter-2026-06-09-002",
            "promoted_finding_ids": [],
            "bubble_run_ids": [],
        },
    ]
    _write_jsonl(tmp_path / "coord_run_state" / "coordinator_cycles.jsonl", rows)
    resp = client.get("/api/coordinator/cycles")
    assert resp.status_code == 200
    cycles = resp.json()["cycles"]
    # Newest-first by timestamp.
    assert [c["run_id"] for c in cycles] == ["cyc-002", "cyc-001"]
    errored = cycles[0]["outcomes"][0]
    assert errored["status"] == "errored"
    assert "not a valid SeedSource enum" in errored["error"]
    assert cycles[0]["dispatched_iteration_id"] == "iter-2026-06-09-002"


def test_cycles_skips_malformed_lines(tmp_path):
    client = _client(tmp_path)
    path = tmp_path / "coord_run_state" / "coordinator_cycles.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '{"run_id":"a","timestamp":"2026-06-09T00:00:00Z"}\n'
        "not-json-and-should-be-skipped\n"
        '{"run_id":"b","timestamp":"2026-06-08T00:00:00Z"}\n',
        encoding="utf-8",
    )
    resp = client.get("/api/coordinator/cycles")
    ids = [c["run_id"] for c in resp.json()["cycles"]]
    assert ids == ["a", "b"]


# (The active / findings / bubbles / health_signals cases died with those
# endpoints in UI simplification S3 — /api/coordinator/cycles is the one
# surviving coordinator endpoint; the D-047 registry covers the live run.)
