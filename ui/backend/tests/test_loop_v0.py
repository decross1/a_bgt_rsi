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


# (The GET /active + GET /processes cases died with those endpoints in UI
# simplification S3; the process-status REAP semantics stay pinned below via
# the /iterations join — the surviving observable.)


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
    "/api/loop_v0/iterations",
])
def test_endpoints_routed(tmp_path, path):
    # Smoke that the router is mounted on the app at the expected prefix.
    client, _ = _client(tmp_path)
    resp = client.get(path)
    assert resp.status_code in (200, 204)


# ─── Process-status tracking (PID + exit-status) ──────────────────────


class _CompletableProc:
    """Test double for subprocess.Popen with a controllable .poll() return.

    By default .poll() returns None (still running). Tests can call
    .complete(rc) to make subsequent .poll() return that exit code,
    simulating the subprocess having exited.
    """

    def __init__(self, pid: int):
        self.pid = pid
        self._rc: int | None = None

    def poll(self) -> int | None:
        return self._rc

    def complete(self, rc: int) -> None:
        self._rc = rc


def test_iterations_join_reports_error_and_kill_statuses(tmp_path):
    """PORTED from the deleted /processes suite (S3): the reap semantics —
    non-zero rc -> exited_error_<rc>, negative rc -> killed_signal_<sig> —
    stay pinned via the /iterations join, the surviving observable."""
    procs: list[_CompletableProc] = []
    def popen(cmd, cwd=None, **kw):
        p = _CompletableProc(pid=6000 + len(procs))
        procs.append(p)
        return p
    client, _ = _client(tmp_path, popen=popen)
    client.post("/api/loop_v0/start", json={"topic": "topic-err"})
    client.post("/api/loop_v0/start", json={"topic": "topic-kill"})
    procs[0].complete(2)   # non-zero exit
    procs[1].complete(-9)  # SIGKILL
    (tmp_path / "memory" / "loop_memory.jsonl").write_text(
        json.dumps({
            "iteration_id": "iter-e",
            "ended_at": "2026-05-26T14:00:00Z",
            "seed": {"topic": "topic-err", "source": "human_ui"},
        }) + "\n" + json.dumps({
            "iteration_id": "iter-k",
            "ended_at": "2026-05-26T15:00:00Z",
            "seed": {"topic": "topic-kill", "source": "human_ui"},
        }) + "\n",
        encoding="utf-8")
    rows = {r["iteration_id"]: r
            for r in client.get("/api/loop_v0/iterations").json()["iterations"]}
    assert rows["iter-e"]["process_status"] == "exited_error_2"
    assert rows["iter-e"]["process_exit_code"] == 2
    assert rows["iter-k"]["process_status"] == "killed_signal_9"


def test_iterations_join_process_status_by_topic(tmp_path):
    procs: list[_CompletableProc] = []
    def popen(cmd, cwd=None, **kw):
        p = _CompletableProc(pid=5000 + len(procs))
        procs.append(p)
        return p
    client, _ = _client(tmp_path, popen=popen)
    # Spawn + complete a process.
    client.post("/api/loop_v0/start", json={"topic": "topic-x"})
    procs[0].complete(0)
    # Write a matching iteration_record in loop_memory.
    (tmp_path / "memory" / "loop_memory.jsonl").write_text(
        json.dumps({
            "iteration_id": "iter-2026-05-26-001",
            "ended_at": "2026-05-26T14:00:00Z",
            "seed": {"topic": "topic-x", "source": "human_ui"},
        }) + "\n",
        encoding="utf-8")
    rows = client.get("/api/loop_v0/iterations").json()["iterations"]
    assert len(rows) == 1
    assert rows[0]["process_status"] == "exited_clean"
    assert rows[0]["process_pid"] == 5000
    assert rows[0]["process_exit_code"] == 0


def test_iterations_omit_process_status_when_no_match(tmp_path):
    client, _ = _client(tmp_path)  # default stub popen
    (tmp_path / "memory" / "loop_memory.jsonl").write_text(
        json.dumps({
            "iteration_id": "iter-2026-05-26-001",
            "ended_at": "2026-05-26T14:00:00Z",
            "seed": {"topic": "unrelated", "source": "human_cli"},
        }) + "\n",
        encoding="utf-8")
    rows = client.get("/api/loop_v0/iterations").json()["iterations"]
    assert len(rows) == 1
    assert "process_status" not in rows[0]
    assert "process_pid" not in rows[0]
