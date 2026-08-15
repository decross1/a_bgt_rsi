"""Lab-channel seam tests — the S4 `orchestrator.lab_channel` exec surface.

Tests NEVER exec a real CLI or a real model: every app under test points at a
tmp repo root and a STUBBED runner returning a canned CompletedProcess; no
subprocess is ever spawned, nothing is written (the CLI owns the transcript
and every ledger write).

What is pinned here:

- the EXACT argv arrays for the three verbs — ``timeline [--since --limit]``,
  ``turn --role --message``, ``delegate --kind --text [--cluster-id]
  [--objective]`` — cwd = repo root, interpreter = .venv-chroma/bin/python,
  list-not-string, no shell, no env manipulation (the server env rides in);
- the per-verb exec caps: timeline 30s (pure read), turn 300s (live Gemma),
  delegate 120s (one-shot write);
- timeline stdout parsing: "<ts>  [<kind>]  <message>" rows, multi-line
  messages reattached as continuations;
- capability gating: /turn and /delegate return an honest PREVIEW (no exec,
  no write) when the CLI module / interpreter are absent;
- 422 validation happens BEFORE any spawn (bad role/kind, empty text, argv
  flag-confusion vectors on since/cluster_id);
- rc != 0 -> 502 carrying the CLI's stderr VERBATIM (the "rejected: ..."
  line rides un-summarized);
- the fence: the router surface is exactly {available, timeline, turn,
  delegate} — no disposition verb is reachable; the module opens no file for
  writing (structural grep).
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.lab_channel_seam import (
    DELEGATE_KINDS,
    ROLES,
    _parse_timeline,
    register,
)

_SEAM_SRC = Path(__file__).resolve().parents[1] / "lab_channel_seam.py"


class StubRunner:
    """Injectable runner double: records every call, returns a canned
    CompletedProcess, never spawns anything."""

    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.calls: list[dict] = []

    def __call__(self, argv, **kwargs):
        self.calls.append({"argv": argv, "kwargs": kwargs})
        return subprocess.CompletedProcess(
            argv, self.returncode, self.stdout, self.stderr)


class RaisingRunner(StubRunner):
    """Runner double whose spawn itself fails."""

    def __call__(self, argv, **kwargs):
        self.calls.append({"argv": argv, "kwargs": kwargs})
        raise OSError("No such file or directory: '.venv-chroma/bin/python'")


@pytest.fixture()
def repo(tmp_path) -> Path:
    """A tmp 'primary repo root' where the capability probe PASSES: the
    interpreter + the blessed CLI module both exist on disk."""
    py = tmp_path / ".venv-chroma" / "bin" / "python"
    py.parent.mkdir(parents=True)
    py.write_text("")
    cli = tmp_path / "orchestrator" / "lab_channel.py"
    cli.parent.mkdir(parents=True)
    cli.write_text("")
    return tmp_path


@pytest.fixture()
def bare_repo(tmp_path) -> Path:
    """A tmp root where the capability probe FAILS (no interpreter, no CLI)."""
    return tmp_path


def _client(repo_root: Path, runner) -> TestClient:
    app = FastAPI()
    register(app, repo_root=repo_root, runner=runner)
    return TestClient(app)


def _py(repo_root: Path) -> str:
    return str(repo_root / ".venv-chroma" / "bin" / "python")


# ─── GET /api/channel/available ─────────────────────────────────────────


def test_available_true_when_cli_and_interpreter_exist(repo):
    runner = StubRunner()
    body = _client(repo, runner).get("/api/channel/available").json()
    assert body["available"] is True
    assert body["actions"] == {"timeline": True, "turn": True,
                               "delegate": True}
    assert runner.calls == []          # never execs


def test_available_false_on_bare_root(bare_repo):
    body = _client(bare_repo, StubRunner()).get("/api/channel/available").json()
    assert body["available"] is False
    assert body["actions"] == {"timeline": False, "turn": False,
                               "delegate": False}


# ─── GET /api/channel/timeline ──────────────────────────────────────────

_TIMELINE_STDOUT = (
    "2026-08-15T10:00:00Z  [event]  cycle: kv-cache · executed · 3 plan action(s) · promoted 0\n"
    "2026-08-15T10:05:00Z  [human]  what is running?\n"
    "2026-08-15T10:05:30Z  [nara]  line one\nline two continues\n"
    "2026-08-15T11:00:00Z  [event]  loop alert: ok\n"
)


def test_timeline_execs_bare_argv_and_parses_rows(repo):
    runner = StubRunner(returncode=0, stdout=_TIMELINE_STDOUT)
    resp = _client(repo, runner).get("/api/channel/timeline")
    assert resp.status_code == 200
    rows = resp.json()["rows"]
    assert [r["kind"] for r in rows] == ["event", "human", "nara", "event"]
    assert rows[0]["ts"] == "2026-08-15T10:00:00Z"
    assert rows[0]["message"].startswith("cycle: kv-cache")
    # the multi-line nara reply is reattached as ONE row, newline preserved
    assert rows[2]["message"] == "line one\nline two continues"

    [call] = runner.calls
    assert call["argv"] == [_py(repo), "-m", "orchestrator.lab_channel",
                            "timeline"]
    assert isinstance(call["argv"], list)
    assert call["kwargs"]["cwd"] == str(repo)
    assert call["kwargs"].get("shell") is not True
    assert "env" not in call["kwargs"]       # server env rides in untouched
    assert call["kwargs"]["timeout"] == 30   # pure read — short cap


def test_timeline_threads_since_and_limit(repo):
    runner = StubRunner(returncode=0, stdout="")
    resp = _client(repo, runner).get(
        "/api/channel/timeline?since=2026-08-15T00:00:00Z&limit=200")
    assert resp.status_code == 200
    assert resp.json() == {"rows": []}
    [call] = runner.calls
    assert call["argv"][-4:] == ["--since", "2026-08-15T00:00:00Z",
                                 "--limit", "200"]


@pytest.mark.parametrize("query", [
    "since=-1d",                       # leading dash = flag confusion
    "since=now",                       # not a timestamp shape
    "since=2026-08-15%2010:00",        # embedded space
    "since=" + "1" * 100,              # over-length
    "limit=0",
    "limit=-5",
    "limit=100000",
    "limit=ten",
])
def test_timeline_bad_params_422_no_spawn(repo, query):
    runner = StubRunner()
    resp = _client(repo, runner).get(f"/api/channel/timeline?{query}")
    assert resp.status_code == 422
    assert runner.calls == []


def test_timeline_cli_failure_is_502_with_verbatim_stderr(repo):
    runner = StubRunner(returncode=1, stdout="", stderr="boom: ledger exploded\n")
    resp = _client(repo, runner).get("/api/channel/timeline")
    assert resp.status_code == 502
    assert resp.json() == {"rc": 1, "stderr": "boom: ledger exploded\n"}


def test_parse_timeline_drops_leading_orphan_lines_only():
    # A continuation with no row to belong to is skipped (tolerant read-only
    # posture); everything after the first row shape is kept.
    rows = _parse_timeline("orphan noise\n2026-08-15T10:00:00Z  [human]  hi\n")
    assert rows == [{"ts": "2026-08-15T10:00:00Z", "kind": "human",
                     "message": "hi"}]


# ─── POST /api/channel/turn ─────────────────────────────────────────────


def test_turn_execs_exact_argv_and_returns_reply(repo):
    runner = StubRunner(returncode=0, stdout="the loop is healthy.\n")
    resp = _client(repo, runner).post(
        "/api/channel/turn", json={"role": "nara", "message": "status?"})
    assert resp.status_code == 200
    assert resp.json() == {"status": "passed", "role": "nara",
                           "reply": "the loop is healthy."}
    [call] = runner.calls
    assert call["argv"] == [_py(repo), "-m", "orchestrator.lab_channel",
                            "turn", "--role", "nara", "--message", "status?"]
    assert call["kwargs"]["cwd"] == str(repo)
    assert call["kwargs"].get("shell") is not True
    assert "env" not in call["kwargs"]
    assert call["kwargs"]["timeout"] == 300   # live-model cap, not the write cap


def test_turn_pi_role_threads(repo):
    runner = StubRunner(returncode=0, stdout="reply\n")
    resp = _client(repo, runner).post(
        "/api/channel/turn", json={"role": "pi", "message": "what's alive?"})
    assert resp.status_code == 200
    assert resp.json()["role"] == "pi"
    [call] = runner.calls
    assert call["argv"][4:6] == ["--role", "pi"]


def test_turn_message_is_one_verbatim_token_never_a_flag(repo):
    runner = StubRunner(returncode=0, stdout="r\n")
    hostile = "line1\nline2 --role pi\n$(rm -rf /); `id`"
    resp = _client(repo, runner).post(
        "/api/channel/turn", json={"role": "nara", "message": hostile})
    assert resp.status_code == 200
    [call] = runner.calls
    assert call["argv"][-2:] == ["--message", hostile]   # ONE verbatim token
    assert call["argv"].count("--role") == 1             # no flag confusion
    assert call["kwargs"].get("shell") is not True


@pytest.mark.parametrize("payload", [
    {"role": "gemma", "message": "m"},       # out-of-enum role
    {"role": "NARA", "message": "m"},        # case-sensitive
    {"role": "", "message": "m"},
    {"message": "m"},                        # missing role
    {"role": None, "message": "m"},
    {"role": "nara", "message": ""},         # empty message
    {"role": "nara", "message": "   "},
    {"role": "nara"},                        # missing message
    {"role": "nara", "message": 42},
])
def test_turn_422_spawns_nothing(repo, payload):
    runner = StubRunner()
    resp = _client(repo, runner).post("/api/channel/turn", json=payload)
    assert resp.status_code == 422
    assert runner.calls == []


def test_turn_capability_off_is_preview_no_exec(bare_repo):
    runner = StubRunner(returncode=0, stdout="never-used\n")
    resp = _client(bare_repo, runner).post(
        "/api/channel/turn", json={"role": "nara", "message": "hello"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "preview"
    assert body["available"] is False
    assert body["would_run"] == {"role": "nara", "message": "hello"}
    assert runner.calls == []                # nothing executed, nothing written


def test_turn_cli_failure_is_502_with_verbatim_stderr(repo):
    stderr = "rejected: message must be non-empty — refusing a blank turn\n"
    runner = StubRunner(returncode=1, stdout="", stderr=stderr)
    resp = _client(repo, runner).post(
        "/api/channel/turn", json={"role": "pi", "message": "m"})
    assert resp.status_code == 502
    assert resp.json() == {"rc": 1, "stderr": stderr}


def test_turn_spawn_failure_is_502_not_500(repo):
    resp = _client(repo, RaisingRunner()).post(
        "/api/channel/turn", json={"role": "nara", "message": "m"})
    assert resp.status_code == 502
    body = resp.json()
    assert body["rc"] is None
    assert "No such file or directory" in body["stderr"]


# ─── POST /api/channel/delegate ─────────────────────────────────────────


def _delegate_env(kind: str):
    return {"status": "passed", "kind": kind,
            "rows": [{"event_type": "agenda_item_added"}],
            "mirror": {"kind": "human", "message": f"DELEGATED[{kind}]: x"}}


def test_delegate_research_execs_exact_argv_and_returns_cli_json(repo):
    env = _delegate_env("research")
    runner = StubRunner(returncode=0, stdout=json.dumps(env) + "\n")
    resp = _client(repo, runner).post("/api/channel/delegate", json={
        "kind": "research", "text": "probe the eviction schedule"})
    assert resp.status_code == 200
    assert resp.json() == env                 # CLI stdout JSON verbatim
    [call] = runner.calls
    assert call["argv"] == [
        _py(repo), "-m", "orchestrator.lab_channel",
        "delegate", "--kind", "research",
        "--text", "probe the eviction schedule"]
    assert call["kwargs"]["cwd"] == str(repo)
    assert call["kwargs"].get("shell") is not True
    assert call["kwargs"]["timeout"] == 120   # one-shot write cap
    # no optional flag synthesized when absent
    assert "--cluster-id" not in call["argv"]
    assert "--objective" not in call["argv"]


def test_delegate_threads_optional_cluster_id_and_objective(repo):
    env = _delegate_env("improvement")
    runner = StubRunner(returncode=0, stdout=json.dumps(env) + "\n")
    resp = _client(repo, runner).post("/api/channel/delegate", json={
        "kind": "improvement", "text": "fix the tailer",
        "cluster_id": "cl-abc", "objective": "seek EOF on first attach"})
    assert resp.status_code == 200
    [call] = runner.calls
    assert call["argv"][-4:] == ["--cluster-id", "cl-abc",
                                 "--objective", "seek EOF on first attach"]


@pytest.mark.parametrize("payload", [
    {"kind": "verdict", "text": "t"},          # out-of-enum kind
    {"kind": "RESEARCH", "text": "t"},         # case-sensitive
    {"text": "t"},                             # missing kind
    {"kind": "research", "text": ""},          # empty text
    {"kind": "research", "text": "  "},
    {"kind": "research"},                      # missing text
    {"kind": "research", "text": 42},
    # cluster_id flag-confusion / charset vectors
    {"kind": "research", "text": "t", "cluster_id": "-cl"},
    {"kind": "research", "text": "t", "cluster_id": "--cluster-id"},
    {"kind": "research", "text": "t", "cluster_id": "cl abc"},
    {"kind": "research", "text": "t", "cluster_id": ""},
    {"kind": "research", "text": "t", "cluster_id": 42},
    # objective present-but-blank is rejected, never silently dropped
    {"kind": "improvement", "text": "t", "objective": "  "},
])
def test_delegate_422_spawns_nothing(repo, payload):
    runner = StubRunner()
    resp = _client(repo, runner).post("/api/channel/delegate", json=payload)
    assert resp.status_code == 422
    assert runner.calls == []


def test_delegate_capability_off_is_preview_no_exec(bare_repo):
    runner = StubRunner()
    resp = _client(bare_repo, runner).post("/api/channel/delegate", json={
        "kind": "research", "text": "an idea"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "preview"
    assert body["would_run"]["kind"] == "research"
    assert runner.calls == []


def test_delegate_rejected_cli_is_502_with_verbatim_stderr(repo):
    stderr = ("rejected: cluster 'cl-nope' not found in the idea ledger — "
              "refusing an agenda item the reducer would reject\n")
    runner = StubRunner(returncode=1, stdout="", stderr=stderr)
    resp = _client(repo, runner).post("/api/channel/delegate", json={
        "kind": "research", "text": "t", "cluster_id": "cl-nope"})
    assert resp.status_code == 502
    assert resp.json() == {"rc": 1, "stderr": stderr}


def test_delegate_extra_payload_keys_never_forwarded(repo):
    # Argv is built from a fixed template — verdict/disposition keys an
    # attacker injects are simply ignored (the fence, argv side).
    env = _delegate_env("research")
    runner = StubRunner(returncode=0, stdout=json.dumps(env) + "\n")
    resp = _client(repo, runner).post("/api/channel/delegate", json={
        "kind": "research", "text": "t",
        "verdict": "valid", "set_status": "validated", "--by": "attacker"})
    assert resp.status_code == 200
    [call] = runner.calls
    for leaked in ("--verdict", "--set-status", "--by", "valid", "validated"):
        assert leaked not in call["argv"], leaked


# ─── the fence + writes-nothing (structural) ────────────────────────────


def test_router_surface_is_exactly_the_three_verbs_plus_available(repo):
    """No disposition verb is reachable: the surface is {available, timeline,
    turn, delegate} and nothing else."""
    client = _client(repo, StubRunner())
    for verb in ("verdict", "disposition", "set_status", "end", "sign_off",
                 "reject", "abstain", "promote", "kill"):
        assert client.post(f"/api/channel/{verb}", json={}).status_code == 404
        assert client.get(f"/api/channel/{verb}").status_code == 404
    # the three verbs exist (wrong-method probes hit 405, not 404)
    assert client.post("/api/channel/timeline", json={}).status_code == 405
    assert client.get("/api/channel/turn").status_code == 405
    assert client.get("/api/channel/delegate").status_code == 405


def test_seam_module_opens_no_file_for_writing():
    """Structural guard (D-046): the seam writes NOTHING itself — the CLI owns
    the transcript and every ledger write."""
    src = _SEAM_SRC.read_text(encoding="utf-8")
    assert not re.search(r"""open\([^)]*['"][rbt]*[wax]""", src), \
        "lab_channel_seam must not open a file for writing"
    assert ".write_text(" not in src and ".write_bytes(" not in src
    assert not re.search(r"[(,]\s*shell\s*=\s*True", src), \
        "lab_channel_seam must never exec with shell=True"
    # env is inherited from the server, never constructed here
    assert not re.search(r"[(,]\s*env\s*=", src), \
        "lab_channel_seam must not manipulate the exec env"


def test_enum_constants_mirror_the_cli_choices():
    assert ROLES == ("nara", "pi")
    assert DELEGATE_KINDS == ("research", "improvement")


def test_register_default_runner_does_not_exec_at_wire():
    app = FastAPI()
    router = register(app)
    assert router is not None
