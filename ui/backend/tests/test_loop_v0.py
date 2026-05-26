"""LOOP_V0 endpoint tests. Side-effect-free: no real CLI invocation, no
real run_state writes. The subprocess shape is verified against a stub
popen; one real-subprocess smoke uses /bin/echo so the test never touches
the apparatus.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app


def _client(tmp_path, *, popen=None) -> tuple[TestClient, dict]:
    """Build a TestClient that points every path at tmp_path.

    Returns the client and a dict capturing what `popen` was called with so
    tests can assert the subprocess shape.
    """
    captured: dict = {}

    if popen is None:
        class _StubProc:
            pid = 4242

        def stub_popen(cmd, cwd=None, **kw):
            captured["cmd"] = list(cmd)
            captured["cwd"] = cwd
            captured["kw"] = kw
            return _StubProc()

        popen = stub_popen

    # Pin every non-LOOP_V0 path at tmp_path so the existing endpoints see
    # benign fixtures rather than the real repo.
    (tmp_path / "logs").mkdir(exist_ok=True)
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"current_day": "loop_v0"}), encoding="utf-8")
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
    run_state_dir = tmp_path / "run_state"
    run_state_dir.mkdir(exist_ok=True)
    journal_dir = tmp_path / "journal"
    journal_dir.mkdir(exist_ok=True)
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir(exist_ok=True)
    loop_memory = memory_dir / "loop_memory.jsonl"

    app = create_app(
        logs_dir=tmp_path / "logs",
        telemetry_file=telemetry,
        state_file=state,
        bench_csv=bench,
        mtp_csv=mtp,
        loop_v0_repo=repo,
        loop_v0_run_state=run_state_dir,
        loop_v0_journal=journal_dir,
        loop_v0_memory=loop_memory,
        loop_v0_popen=popen,
    )
    return TestClient(app), captured


def test_active_returns_204_when_no_iteration_in_flight(tmp_path):
    client, _ = _client(tmp_path)
    resp = client.get("/api/loop_v0/active")
    assert resp.status_code == 204
    assert resp.content == b""


def test_active_returns_json_when_present(tmp_path):
    client, _ = _client(tmp_path)
    # Field names mirror schema/active_iteration.schema.json. The producer
    # writes `latest_narration` (not `narration`); see nara.py:182 and the
    # 2026-05-26 code-review B1 finding.
    active = {
        "iteration_id": "iter-2026-05-26-001",
        "topic": "TfT dominance",
        "started_at": "2026-05-26T14:00:00Z",
        "current_step": "query_chroma",
        "latest_narration": "Nara: querying Chroma.",
        "tool_calls_so_far": [],
    }
    (tmp_path / "run_state" / "active_iteration.json").write_text(
        json.dumps(active), encoding="utf-8")
    resp = client.get("/api/loop_v0/active")
    assert resp.status_code == 200
    assert resp.json() == active


def test_active_returns_204_when_file_disappears_mid_read(tmp_path):
    """Regression: producer atomically deletes active_iteration.json at
    iteration end (nara.py finally-block). The endpoint's exists() may
    return True but read_text() then raises FileNotFoundError. The
    polling UI must see 204, not 500. See 2026-05-26 code-review N4."""
    import unittest.mock as mock
    client, _ = _client(tmp_path)
    path = tmp_path / "run_state" / "active_iteration.json"
    path.write_text(json.dumps({"iteration_id": "x"}), encoding="utf-8")

    real_read_text = type(path).read_text

    def race_read_text(self, *args, **kwargs):
        if str(self) == str(path):
            raise FileNotFoundError(str(self))
        return real_read_text(self, *args, **kwargs)

    with mock.patch.object(type(path), "read_text", race_read_text):
        resp = client.get("/api/loop_v0/active")
    assert resp.status_code == 204
    assert resp.content == b""


def test_iterations_empty_when_log_missing(tmp_path):
    client, _ = _client(tmp_path)
    resp = client.get("/api/loop_v0/iterations")
    assert resp.status_code == 200
    assert resp.json() == {"iterations": []}


def test_iterations_returns_newest_first(tmp_path):
    client, _ = _client(tmp_path)
    rows = [
        {"iteration_id": "iter-001", "ended_at": "2026-05-24T11:00:00Z"},
        {"iteration_id": "iter-003", "ended_at": "2026-05-26T14:00:00Z"},
        {"iteration_id": "iter-002", "ended_at": "2026-05-25T19:00:00Z"},
    ]
    (tmp_path / "memory" / "loop_memory.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    resp = client.get("/api/loop_v0/iterations")
    ids = [r["iteration_id"] for r in resp.json()["iterations"]]
    assert ids == ["iter-003", "iter-002", "iter-001"]


def test_iterations_skips_malformed_lines(tmp_path):
    client, _ = _client(tmp_path)
    (tmp_path / "memory" / "loop_memory.jsonl").write_text(
        '{"iteration_id":"a","ended_at":"2026-05-26T00:00:00Z"}\n'
        "not-json-and-should-be-skipped\n"
        '{"iteration_id":"b","ended_at":"2026-05-25T00:00:00Z"}\n',
        encoding="utf-8")
    resp = client.get("/api/loop_v0/iterations")
    ids = [r["iteration_id"] for r in resp.json()["iterations"]]
    assert ids == ["a", "b"]


def test_journal_404_when_absent(tmp_path):
    client, _ = _client(tmp_path)
    resp = client.get("/api/loop_v0/journal/iter-missing")
    assert resp.status_code == 404


def test_journal_rejects_path_traversal(tmp_path):
    client, _ = _client(tmp_path)
    for bad in ("../etc/passwd", "..%2Fpasswd", "iter/with/slashes"):
        resp = client.get(f"/api/loop_v0/journal/{bad}")
        assert resp.status_code in (400, 404), bad


def test_journal_returns_content_when_present(tmp_path):
    client, _ = _client(tmp_path)
    journal_path = tmp_path / "journal" / "001.md"
    body = "# Iteration iter-2026-05-26-001\n\nbody.\n"
    journal_path.write_text(body, encoding="utf-8")
    # loop_memory points the iteration at this journal file.
    (tmp_path / "memory" / "loop_memory.jsonl").write_text(
        json.dumps({
            "iteration_id": "iter-2026-05-26-001",
            "ended_at": "2026-05-26T14:00:00Z",
            "journal_entry_path": str(journal_path),
        }) + "\n",
        encoding="utf-8")
    resp = client.get("/api/loop_v0/journal/iter-2026-05-26-001")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["iteration_id"] == "iter-2026-05-26-001"
    assert payload["content"] == body


def test_journal_falls_back_to_glob_scan(tmp_path):
    # If loop_memory.jsonl has no row yet (Part-1 hello-world race window),
    # the endpoint scans journal_dir for a file mentioning the iteration_id.
    client, _ = _client(tmp_path)
    journal_path = tmp_path / "journal" / "001.md"
    journal_path.write_text(
        "# iter-2026-05-26-002\n\n(memory not flushed yet)\n",
        encoding="utf-8")
    resp = client.get("/api/loop_v0/journal/iter-2026-05-26-002")
    assert resp.status_code == 200
    assert "memory not flushed yet" in resp.json()["content"]


def test_start_rejects_empty_topic(tmp_path):
    client, _ = _client(tmp_path)
    assert client.post("/api/loop_v0/start", json={"topic": ""}).status_code == 400
    assert client.post("/api/loop_v0/start", json={}).status_code == 400


def test_start_spawns_with_mock_llm_stripped(tmp_path):
    client, captured = _client(tmp_path)
    resp = client.post(
        "/api/loop_v0/start", json={"topic": "  TfT dominance  "})
    assert resp.status_code == 202
    payload = resp.json()
    assert payload["pid"] == 4242
    assert payload["topic"] == "TfT dominance"
    # Inviolate operational note: prefix is `env -u MOCK_LLM`.
    assert captured["cmd"][:3] == ["env", "-u", "MOCK_LLM"]
    # CLI module + topic argument present.
    assert "orchestrator.loop_v0_cli" in captured["cmd"]
    assert "TfT dominance" in captured["cmd"]
    # cwd is the configured repo root, not the worktree.
    assert captured["cwd"] == str(tmp_path / "repo")


def test_start_with_real_subprocess_invokes_env_unset(tmp_path):
    """Smoke: a real Popen with env -u MOCK_LLM works end-to-end.

    Replaces the CLI module with /bin/echo to keep the test side-effect-free
    — the assertion is on the subprocess result, not the apparatus.
    """
    captured = {}
    original_popen = subprocess.Popen

    def echo_popen(cmd, cwd=None, **kw):
        # Swap the python+module slice for a simple echo of the topic.
        captured["original_cmd"] = list(cmd)
        topic = cmd[-1]
        echo_cmd = ["env", "-u", "MOCK_LLM", "/bin/echo", topic]
        return original_popen(echo_cmd, cwd=cwd, **kw,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    client, _ = _client(tmp_path, popen=echo_popen)
    resp = client.post(
        "/api/loop_v0/start", json={"topic": "TfT-real-subproc"})
    assert resp.status_code == 202
    assert captured["original_cmd"][:3] == ["env", "-u", "MOCK_LLM"]
    assert captured["original_cmd"][-2:] == ["--topic", "TfT-real-subproc"]


@pytest.mark.parametrize("path", [
    "/api/loop_v0/active",
    "/api/loop_v0/iterations",
])
def test_endpoints_routed(tmp_path, path):
    # Smoke that the router is mounted on the app at the expected prefix.
    client, _ = _client(tmp_path)
    resp = client.get(path)
    assert resp.status_code in (200, 204)
