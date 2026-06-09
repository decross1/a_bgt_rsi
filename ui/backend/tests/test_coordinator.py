"""Coordinator (autonomy-observability) endpoint tests. Side-effect-free:
no real CLI invocation, no real run_state/memory writes — every path points
at tmp_path. Mirrors test_loop_v0.py's TestClient-against-tmp_path idiom.

Asserts each endpoint returns empty/204 when its (gitignored) data file is
absent, and returns newest-first rows when tmp files are written. Covers a
cycle with an "errored" outcome carrying an error string + a dispatched
iteration id, an active_run with kind="coordinator", findings, and bubbles.
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


# ─── active ────────────────────────────────────────────────────────────


def test_active_returns_204_when_no_cycle_in_flight(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/api/coordinator/active")
    assert resp.status_code == 204
    assert resp.content == b""


def test_active_returns_json_when_present(tmp_path):
    client = _client(tmp_path)
    active = {
        "kind": "coordinator",
        "run_id": "cyc-003",
        "current_step": "dispatch",
        "narration": "Chose 'Truthfulness of VCG' (topic_source=coordinator); "
        "dispatching a loop iteration.",
        "topic": "Truthfulness of VCG in combinatorial auctions",
        "topic_source": "coordinator",
        "started_at": "2026-06-09T12:00:00Z",
    }
    path = tmp_path / "coord_run_state" / "active_run.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(active), encoding="utf-8")
    resp = client.get("/api/coordinator/active")
    assert resp.status_code == 200
    assert resp.json() == active


def test_active_returns_204_when_file_disappears_mid_read(tmp_path):
    """Regression: producer atomically deletes active_run.json at cycle end.
    exists() may return True but read_text() then raises FileNotFoundError.
    The polling UI must see 204, not 500 (mirrors loop_v0 active)."""
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


# ─── findings ──────────────────────────────────────────────────────────


def test_findings_empty_when_log_missing(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/api/coordinator/findings")
    assert resp.status_code == 200
    assert resp.json() == {"findings": []}


def test_findings_returns_newest_first(tmp_path):
    client = _client(tmp_path)
    rows = [
        {
            "finding_id": "sf-iter-2026-06-09-001",
            "source_iteration_id": "iter-2026-06-09-001",
            "title": "VCG elicits truthful bids in the measured combinatorial setting",
            "novelty_class": "rediscovery",
            "critic_verdict": "restated",
            "promoted_at": "2026-06-09T10:05:00Z",
            "status": "surfaced",
        },
        {
            "finding_id": "sf-iter-2026-06-09-003",
            "source_iteration_id": "iter-2026-06-09-003",
            "title": "Level-k convergence rate refinement worth a real run",
            "novelty_class": "novel",
            "critic_verdict": "survives",
            "promoted_at": "2026-06-09T13:20:00Z",
            "status": "surfaced",
        },
    ]
    _write_jsonl(tmp_path / "coord_memory" / "surfaced_findings.jsonl", rows)
    resp = client.get("/api/coordinator/findings")
    findings = resp.json()["findings"]
    # newest-first by promoted_at.
    assert [f["finding_id"] for f in findings] == [
        "sf-iter-2026-06-09-003",
        "sf-iter-2026-06-09-001",
    ]
    assert findings[0]["title"].startswith("Level-k")


# ─── bubbles ───────────────────────────────────────────────────────────


def test_bubbles_empty_when_log_missing(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/api/coordinator/bubbles")
    assert resp.status_code == 200
    assert resp.json() == {"bubbles": []}


def test_bubbles_returns_newest_first(tmp_path):
    client = _client(tmp_path)
    rows = [
        {
            "timestamp": "2026-06-09T10:06:00Z",
            "run_id": "cyc-001",
            "finding_ids": ["sf-iter-2026-06-09-001"],
            "note": "A novel/survives verdict rested on off-domain retrieval — eyeball it.",
        },
        {
            "timestamp": "2026-06-09T11:35:00Z",
            "run_id": "cyc-002",
            "finding_ids": [],
            "note": "ml-intern returned 0 papers for this topic.",
        },
    ]
    _write_jsonl(tmp_path / "coord_memory" / "coordinator_bubbles.jsonl", rows)
    resp = client.get("/api/coordinator/bubbles")
    bubbles = resp.json()["bubbles"]
    # newest-first by timestamp.
    assert [b["run_id"] for b in bubbles] == ["cyc-002", "cyc-001"]
    assert bubbles[1]["note"].startswith("A novel/survives")


# ─── health signals ────────────────────────────────────────────────────


def test_health_signals_empty_when_log_missing(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/api/coordinator/health_signals")
    assert resp.status_code == 200
    assert resp.json() == {"health_signals": []}


def test_health_signals_returns_newest_first(tmp_path):
    client = _client(tmp_path)
    rows = [
        {
            "timestamp": "2026-06-09T10:06:00Z",
            "run_id": "cyc-001",
            "signal": "ml_intern_zero_papers",
            "severity": "degraded",
            "iteration_id": "iter-001",
            "papers_stored": 0,
            "detail": "ml_intern ran but stored 0 papers; external search was blind.",
        },
        {
            "timestamp": "2026-06-09T11:35:00Z",
            "run_id": "cyc-002",
            "signal": "qwen_degraded_empty_content",
            "severity": "degraded",
            "iteration_id": "iter-002",
            "empty_calls": 2,
            "total_calls": 3,
            "detail": "Qwen returned empty content on 2/3 calls; degraded, not down.",
        },
    ]
    _write_jsonl(tmp_path / "coord_run_state" / "health_signals.jsonl", rows)
    resp = client.get("/api/coordinator/health_signals")
    signals = resp.json()["health_signals"]
    # newest-first by timestamp.
    assert [s["signal"] for s in signals] == [
        "qwen_degraded_empty_content",
        "ml_intern_zero_papers",
    ]
    assert all(s["severity"] == "degraded" for s in signals)
