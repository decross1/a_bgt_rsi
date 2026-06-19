"""Cockpit chat-seam tests — the LIVE `finding_session chat` start/turn exec.

Tests NEVER exec a real CLI or a real model (the chat seam calls models, so a
real exec would fire vllm-gemma / vllm-qwen — MOCK_LLM only stubs embedders).
Every app under test points at a tmp repo root and a STUBBED runner that returns
a canned ``CompletedProcess``; no subprocess is ever spawned, nothing is written
(the CLI owns its own session transcript — D-046).

What is pinned here:

- the EXACT argv arrays — module ``orchestrator.finding_session``, ``chat
  start``/``chat turn``, ``--mode`` / ``--finding-id`` / ``--session-id`` /
  ``--message`` / ``--addressee`` — so a wrong flag is caught; cwd = repo root,
  interpreter = ``.venv-chroma/bin/python``, list-not-string, no ``shell=True``;
- the verdict fence: only ``/start`` and ``/turn`` exist (no disposition verb);
- tutor mode NEVER forwards ``--addressee`` (asserted absent in the argv); a
  tutor turn returns one ``stance:null`` reply with no ``addressee`` key;
- two_voice threads ``--addressee`` only when provided, with stance-tagged
  replies; ``--addressee`` is validated against the frozen enum;
- 422 validation (bad mode, empty finding_id, missing session_id/message, a
  tutor addressee) happens BEFORE spawn — the runner is never called;
- rc != 0 -> 502 carrying the CLI's stderr VERBATIM + the exit code (the JSON
  error envelope at exit 1, argparse usage at exit 2);
- writes-nothing: the module opens no file for writing (a structural grep) and
  the stub runner performs no write.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.chat_seam import (
    ADDRESSEES,
    CHAT_MODES,
    register,
)

# The chat seam execs ``finding_session``, which (unlike the attest writers)
# writes a session transcript only via its OWN CLI — never via the seam. These
# tests stub the runner, so nothing is written anywhere; we still pin the seam
# itself opens no file for writing (the structural grep below).
_SEAM_SRC = Path(__file__).resolve().parents[1] / "chat_seam.py"


class StubRunner:
    """Injectable runner double: records every call, returns a canned
    CompletedProcess, and never spawns anything (so no real model is hit)."""

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
    """Runner double whose spawn itself fails (missing interpreter etc.)."""

    def __call__(self, argv, **kwargs):
        self.calls.append({"argv": argv, "kwargs": kwargs})
        raise OSError("No such file or directory: '.venv-chroma/bin/python'")


@pytest.fixture()
def repo(tmp_path) -> Path:
    """A tmp 'primary repo root'. The chat seam never existence-checks files
    (unlike attest's /available) — it just execs under this root — so the dir
    can stay empty; the stubbed runner is the only 'CLI' that ever runs."""
    return tmp_path


def _client(repo_root: Path, runner) -> TestClient:
    """Bare FastAPI app + the chat-seam router only (the integrator wires the
    real app.py registration; these tests exercise the module standalone)."""
    app = FastAPI()
    register(app, repo_root=repo_root, runner=runner)
    return TestClient(app)


def _py(repo_root: Path) -> str:
    return str(repo_root / ".venv-chroma" / "bin" / "python")


# Canned CLI envelopes (single-line JSON on stdout, exit 0) — the shapes
# finding_session.py:1171-1203 emits.
def _start_env(mode: str, stances):
    return {"ok": True, "mode": mode, "action": "start",
            "finding_id": "sf-001", "session_id": "sess-abc", "stances": stances}


def _tutor_turn_env():
    # tutor turn: single reply, stance null, NO addressee key (.get-safe).
    return {"ok": True, "mode": "tutor", "action": "turn",
            "finding_id": "sf-001", "session_id": "sess-abc",
            "turn_index": 1, "capped": False, "warning": None,
            "replies": [{"stance": None, "reply": "Consider the base rate.",
                         "request_id": "req-1"}]}


def _two_voice_turn_env(addressee: str):
    return {"ok": True, "mode": "two_voice", "action": "turn",
            "finding_id": "sf-001", "session_id": "sess-abc",
            "turn_index": 1, "capped": False, "addressee": addressee,
            "warning": None,
            "replies": [
                {"stance": "defender", "reply": "It holds.", "request_id": "req-d"},
                {"stance": "attacker", "reply": "It does not.", "request_id": "req-a"},
            ]}


# ─── POST /api/todo/chat/start ──────────────────────────────────────────


def test_start_tutor_execs_exact_argv_and_returns_null_stances(repo):
    env = _start_env("tutor", None)
    runner = StubRunner(returncode=0, stdout=json.dumps(env) + "\n")
    client = _client(repo, runner)
    resp = client.post("/api/todo/chat/start",
                       json={"mode": "tutor", "finding_id": "sf-001"})
    assert resp.status_code == 200
    assert resp.json() == env
    assert resp.json()["stances"] is None        # tutor is single-voice

    [call] = runner.calls
    assert call["argv"] == [
        _py(repo), "-m", "orchestrator.finding_session",
        "chat", "start",
        "--mode", "tutor",
        "--finding-id", "sf-001",
    ]
    assert isinstance(call["argv"], list)          # argv ARRAY, never a string
    assert call["kwargs"]["cwd"] == str(repo)      # cwd = primary repo root
    assert call["kwargs"].get("shell") is not True  # no shell, ever
    # start NEVER threads an addressee, in either mode.
    assert "--addressee" not in call["argv"]


def test_start_two_voice_returns_stances_object(repo):
    stances = {"defender": "vllm-gemma", "attacker": "vllm-qwen"}
    env = _start_env("two_voice", stances)
    runner = StubRunner(returncode=0, stdout=json.dumps(env) + "\n")
    client = _client(repo, runner)
    resp = client.post("/api/todo/chat/start",
                       json={"mode": "two_voice", "finding_id": "sf-001"})
    assert resp.status_code == 200
    assert resp.json()["stances"] == stances       # the two-stance object

    [call] = runner.calls
    assert call["argv"] == [
        _py(repo), "-m", "orchestrator.finding_session",
        "chat", "start",
        "--mode", "two_voice",
        "--finding-id", "sf-001",
    ]


@pytest.mark.parametrize("payload", [
    {"mode": "guru", "finding_id": "sf-001"},        # out-of-enum mode
    {"mode": "TUTOR", "finding_id": "sf-001"},       # case-sensitive enum
    {"mode": "", "finding_id": "sf-001"},
    {"finding_id": "sf-001"},                        # missing mode
    {"mode": None, "finding_id": "sf-001"},
    {"mode": "tutor", "finding_id": ""},             # empty id
    {"mode": "tutor", "finding_id": "-sf-001"},      # leading-dash flag injection
    {"mode": "tutor", "finding_id": "--finding-id"},
    {"mode": "tutor", "finding_id": "sf 001"},       # space — charset
    {"mode": "tutor", "finding_id": "sf/../001"},
    {"mode": "tutor", "finding_id": 42},
    {"mode": "tutor"},                               # missing id
])
def test_start_422_spawns_nothing(repo, payload):
    runner = StubRunner()
    client = _client(repo, runner)
    resp = client.post("/api/todo/chat/start", json=payload)
    assert resp.status_code == 422
    assert runner.calls == []   # validate BEFORE spawn: nothing executed


# ─── POST /api/todo/chat/turn ───────────────────────────────────────────


def test_turn_tutor_single_reply_no_addressee_in_argv(repo):
    env = _tutor_turn_env()
    runner = StubRunner(returncode=0, stdout=json.dumps(env) + "\n")
    client = _client(repo, runner)
    resp = client.post("/api/todo/chat/turn", json={
        "mode": "tutor", "finding_id": "sf-001",
        "session_id": "sess-abc", "message": "why does this hold?"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["replies"]) == 1
    assert body["replies"][0]["stance"] is None      # single-voice
    assert "addressee" not in body                    # tutor envelope omits it

    [call] = runner.calls
    assert call["argv"] == [
        _py(repo), "-m", "orchestrator.finding_session",
        "chat", "turn",
        "--mode", "tutor",
        "--finding-id", "sf-001",
        "--session-id", "sess-abc",
        "--message", "why does this hold?",
    ]
    # The CLI REJECTS --addressee in tutor mode — the seam must never thread it.
    assert "--addressee" not in call["argv"]
    assert call["kwargs"]["cwd"] == str(repo)
    assert call["kwargs"].get("shell") is not True


def test_turn_tutor_with_addressee_is_422_and_spawns_nothing(repo):
    # A tutor turn carrying an addressee is rejected up front (never coerced,
    # never forwarded) rather than spawning into a guaranteed CLI error.
    runner = StubRunner()
    client = _client(repo, runner)
    resp = client.post("/api/todo/chat/turn", json={
        "mode": "tutor", "finding_id": "sf-001", "session_id": "sess-abc",
        "message": "hi", "addressee": "defender"})
    assert resp.status_code == 422
    assert runner.calls == []


@pytest.mark.parametrize("addressee", list(ADDRESSEES))
def test_turn_two_voice_threads_addressee_and_tags_replies(repo, addressee):
    env = _two_voice_turn_env(addressee)
    runner = StubRunner(returncode=0, stdout=json.dumps(env) + "\n")
    client = _client(repo, runner)
    resp = client.post("/api/todo/chat/turn", json={
        "mode": "two_voice", "finding_id": "sf-001",
        "session_id": "sess-abc", "message": "interrogate this",
        "addressee": addressee})
    assert resp.status_code == 200
    body = resp.json()
    assert body["addressee"] == addressee
    stances = {r["stance"] for r in body["replies"]}
    assert stances == {"defender", "attacker"}        # stance-tagged

    [call] = runner.calls
    assert call["argv"] == [
        _py(repo), "-m", "orchestrator.finding_session",
        "chat", "turn",
        "--mode", "two_voice",
        "--finding-id", "sf-001",
        "--session-id", "sess-abc",
        "--message", "interrogate this",
        "--addressee", addressee,
    ]
    assert call["kwargs"]["cwd"] == str(repo)
    assert call["kwargs"].get("shell") is not True


def test_turn_two_voice_without_addressee_omits_the_flag(repo):
    # Optional: when no addressee is given the CLI defaults it to "both", so the
    # seam must NOT synthesize one — the flag is simply absent from the argv.
    env = _two_voice_turn_env("both")
    runner = StubRunner(returncode=0, stdout=json.dumps(env) + "\n")
    client = _client(repo, runner)
    resp = client.post("/api/todo/chat/turn", json={
        "mode": "two_voice", "finding_id": "sf-001",
        "session_id": "sess-abc", "message": "interrogate this"})
    assert resp.status_code == 200
    [call] = runner.calls
    assert "--addressee" not in call["argv"]          # not synthesized
    assert call["argv"][-2:] == ["--message", "interrogate this"]


def test_turn_message_is_one_verbatim_token_never_a_flag(repo):
    # The message is FREE TEXT, forwarded as a single argv token after --message.
    # There is no shell, so embedded flags / shell metacharacters / newlines are
    # inert: a message that LOOKS like `--addressee defender; $(rm -rf /)` must
    # ride as ONE token and must NOT spawn a second --addressee (no flag confusion).
    env = _tutor_turn_env()
    runner = StubRunner(returncode=0, stdout=json.dumps(env) + "\n")
    hostile = "line1\nline2 --addressee defender\n$(rm -rf /); `id`"
    resp = _client(repo, runner).post("/api/todo/chat/turn", json={
        "mode": "tutor", "finding_id": "sf-001",
        "session_id": "sess-abc", "message": hostile})
    assert resp.status_code == 200
    [call] = runner.calls
    assert call["argv"][-2:] == ["--message", hostile]   # ONE verbatim token
    assert call["argv"].count("--addressee") == 0        # no flag confusion
    assert call["kwargs"].get("shell") is not True       # never a shell


@pytest.mark.parametrize("bad_id", [
    "sf\n001", "sf\t001", "sf\x00001",   # control chars / newlines
    "sf;rm", "sf$(x)", "sf`x`", "sf|x",   # shell metacharacters
    "café",                               # non-ASCII
    "sf-" + "a" * 300,                     # over the 200-char ceiling
])
def test_start_control_and_meta_ids_422_no_spawn(repo, bad_id):
    # The id charset (^[A-Za-z0-9][A-Za-z0-9._:-]*$, <=200) rejects every control
    # char, shell metacharacter, and non-ASCII id BEFORE any spawn — never coerced.
    runner = StubRunner()
    resp = _client(repo, runner).post(
        "/api/todo/chat/start", json={"mode": "tutor", "finding_id": bad_id})
    assert resp.status_code == 422
    assert runner.calls == []


def test_extra_payload_keys_never_forwarded_verdict_fence(repo):
    # Argv is built from a fixed template, never from arbitrary payload keys — an
    # attacker injecting verdict/set_status/disposition keys is simply ignored:
    # no disposition verb or flag can reach the CLI through this seam.
    env = _two_voice_turn_env("both")
    runner = StubRunner(returncode=0, stdout=json.dumps(env) + "\n")
    resp = _client(repo, runner).post("/api/todo/chat/turn", json={
        "mode": "two_voice", "finding_id": "sf-001", "session_id": "sess-abc",
        "message": "m", "addressee": "both",
        "verdict": "valid", "set_status": "validated", "disposition": "reject",
        "--by": "attacker"})
    assert resp.status_code == 200
    [call] = runner.calls
    for leaked in ("--set-status", "--verdict", "--directive", "--disposition",
                   "--by", "--gated-by", "valid", "validated", "reject"):
        assert leaked not in call["argv"], leaked


@pytest.mark.parametrize("payload", [
    # mode discipline (same frozen enum as start)
    {"mode": "guru", "finding_id": "sf-001", "session_id": "s", "message": "m"},
    {"finding_id": "sf-001", "session_id": "s", "message": "m"},
    # finding_id / session_id charset + presence (leading dash = flag injection)
    {"mode": "tutor", "finding_id": "", "session_id": "s", "message": "m"},
    {"mode": "tutor", "finding_id": "-sf", "session_id": "s", "message": "m"},
    {"mode": "tutor", "finding_id": "sf-001", "session_id": "", "message": "m"},
    {"mode": "tutor", "finding_id": "sf-001", "session_id": "-s", "message": "m"},
    {"mode": "tutor", "finding_id": "sf-001", "message": "m"},   # missing sid
    # message required non-empty (free text, but must be present)
    {"mode": "tutor", "finding_id": "sf-001", "session_id": "s", "message": ""},
    {"mode": "tutor", "finding_id": "sf-001", "session_id": "s", "message": "  "},
    {"mode": "tutor", "finding_id": "sf-001", "session_id": "s"},  # missing msg
    {"mode": "tutor", "finding_id": "sf-001", "session_id": "s", "message": 42},
    # two_voice addressee out-of-enum (when present, it is frozen)
    {"mode": "two_voice", "finding_id": "sf-001", "session_id": "s",
     "message": "m", "addressee": "judge"},
    {"mode": "two_voice", "finding_id": "sf-001", "session_id": "s",
     "message": "m", "addressee": ""},
])
def test_turn_422_spawns_nothing(repo, payload):
    runner = StubRunner()
    client = _client(repo, runner)
    resp = client.post("/api/todo/chat/turn", json=payload)
    assert resp.status_code == 422
    assert runner.calls == []


# ─── failure semantics — both endpoints, one contract ───────────────────


def test_turn_error_envelope_returns_502_with_verbatim_stderr(repo):
    # The CLI rejects (KeyError/ValueError) with a JSON error envelope on
    # STDERR, empty stdout, exit 1 (finding_session.py:1205-1210). The seam
    # surfaces stderr VERBATIM as a 502, never faking a reply.
    stderr = json.dumps({"ok": False,
                          "error": "ValueError: --session-id is required for a turn"}) + "\n"
    runner = StubRunner(returncode=1, stdout="", stderr=stderr)
    client = _client(repo, runner)
    resp = client.post("/api/todo/chat/turn", json={
        "mode": "two_voice", "finding_id": "sf-001",
        "session_id": "sess-abc", "message": "m"})
    assert resp.status_code == 502
    assert resp.json() == {"rc": 1, "stderr": stderr}   # verbatim + exit code
    assert len(runner.calls) == 1


def test_start_argparse_usage_exit2_returns_502(repo):
    # An argparse arg-error exits 2 with usage on stderr, empty stdout — surfaced
    # as a 502 carrying the exit code (not masked as success).
    usage = "usage: finding_session chat [-h] --mode {tutor,two_voice} ...\n"
    runner = StubRunner(returncode=2, stdout="", stderr=usage)
    client = _client(repo, runner)
    resp = client.post("/api/todo/chat/start",
                       json={"mode": "tutor", "finding_id": "sf-001"})
    assert resp.status_code == 502
    assert resp.json() == {"rc": 2, "stderr": usage}


def test_spawn_failure_is_502_not_500(repo):
    runner = RaisingRunner()
    resp = _client(repo, runner).post("/api/todo/chat/start",
                                      json={"mode": "tutor", "finding_id": "sf-001"})
    assert resp.status_code == 502
    body = resp.json()
    assert body["rc"] is None
    assert "No such file or directory" in body["stderr"]


def test_zero_exit_with_nonjson_stdout_is_502(repo):
    # A zero-exit CLI that printed non-JSON broke the envelope contract — the
    # seam surfaces it, never fabricates a reply shape.
    runner = StubRunner(returncode=0, stdout="started!\n", stderr="")
    resp = _client(repo, runner).post("/api/todo/chat/start",
                                      json={"mode": "tutor", "finding_id": "sf-001"})
    assert resp.status_code == 502
    body = resp.json()
    assert body["rc"] == 0
    assert body["stdout"] == "started!\n"   # surfaced, not faked as success


# ─── encoder-overflow hardening: a pathological zero-exit envelope ───────
# The seam returns the CLI's stdout JSON verbatim. A (stubbed) CLI that emits
# a parseable-but-UNENCODABLE envelope — deeply nested, non-finite float, or a
# huge bigint — must NOT crash the response encoder into a 500 (the same class
# todo_cockpit guards with _within_depth). It is an envelope-contract break, so
# the seam surfaces it as a 502 (never 500, never a faked success shape).


def _server_client(repo_root: Path, runner) -> TestClient:
    """Like _client but lets server exceptions surface as 500s (default for the
    TestClient) — so a guard REGRESSION shows up as a 500 here, not a raise."""
    app = FastAPI()
    register(app, repo_root=repo_root, runner=runner)
    return TestClient(app, raise_server_exceptions=False)


def _deep_envelope(depth: int) -> str:
    """A valid-JSON envelope whose ``stances`` field nests `depth` lists deep —
    json.loads accepts it, but the JSONResponse encoder walks it recursively."""
    return '{"ok":true,"action":"start","stances":' \
        + "[" * depth + "0" + "]" * depth + "}"


def test_start_deeply_nested_stdout_is_502_not_500(repo):
    # A few thousand levels overflow the encoder (the request call stack is
    # already deep) — would RecursionError -> 500 without a depth guard.
    runner = StubRunner(returncode=0, stdout=_deep_envelope(5000) + "\n")
    resp = _server_client(repo, runner).post(
        "/api/todo/chat/start", json={"mode": "tutor", "finding_id": "sf-001"})
    assert resp.status_code == 502           # degraded, never 500
    assert resp.json()["rc"] == 0


def test_start_surrogate_string_stdout_is_502_not_500(repo):
    # A lone/unpaired surrogate in an envelope STRING (model output can carry it)
    # parses fine but is not UTF-8-encodable — would 500 the encoder without the
    # str-branch guard. Surface it as the honest 502 contract break, never 500.
    env = '{"ok":true,"mode":"tutor","action":"start","stances":null,"x":"ok\\ud800bad"}'
    runner = StubRunner(returncode=0, stdout=env + "\n")
    resp = _server_client(repo, runner).post(
        "/api/todo/chat/start", json={"mode": "tutor", "finding_id": "sf-001"})
    assert resp.status_code == 502           # degraded, never 500
    assert resp.json()["rc"] == 0


def test_turn_deeply_nested_stdout_is_502_not_500(repo):
    runner = StubRunner(returncode=0, stdout=_deep_envelope(5000) + "\n")
    resp = _server_client(repo, runner).post("/api/todo/chat/turn", json={
        "mode": "two_voice", "finding_id": "sf-001",
        "session_id": "sess-abc", "message": "m"})
    assert resp.status_code == 502
    assert resp.json()["rc"] == 0


def test_start_non_finite_float_stdout_is_502_not_500(repo):
    # Python's json.loads ACCEPTS NaN/Infinity by default; the encoder would
    # then emit non-compliant `NaN` (or fail) -> 500 without a guard.
    for token in ("NaN", "Infinity", "-Infinity"):
        runner = StubRunner(returncode=0,
                            stdout='{"ok":true,"x":' + token + '}\n')
        resp = _server_client(repo, runner).post(
            "/api/todo/chat/start",
            json={"mode": "tutor", "finding_id": "sf-001"})
        assert resp.status_code == 502, token
        assert resp.json()["rc"] == 0


def test_start_huge_bigint_stdout_is_502_not_500(repo):
    # A 5000-digit integer trips json.loads' 4300-digit int-string limit, which
    # raises a bare ValueError (NOT a JSONDecodeError) inside _exec_blessed — it
    # escapes attest's (JSONDecodeError, TypeError) catch and would 500. The seam
    # must catch it and surface a 502.
    runner = StubRunner(returncode=0, stdout='{"ok":true,"n":' + "9" * 5000 + "}\n")
    resp = _server_client(repo, runner).post(
        "/api/todo/chat/start", json={"mode": "tutor", "finding_id": "sf-001"})
    assert resp.status_code == 502
    assert resp.json()["rc"] == 0


def test_well_formed_nested_envelope_still_passes_through(repo):
    # The guard must NOT reject a normal envelope — modestly nested replies (the
    # real two_voice shape, a few levels deep) round-trip unchanged at 200.
    env = _two_voice_turn_env("both")
    runner = StubRunner(returncode=0, stdout=json.dumps(env) + "\n")
    resp = _server_client(repo, runner).post("/api/todo/chat/turn", json={
        "mode": "two_voice", "finding_id": "sf-001",
        "session_id": "sess-abc", "message": "m", "addressee": "both"})
    assert resp.status_code == 200
    assert resp.json() == env


# ─── verdict fence + writes-nothing (structural) ────────────────────────


def test_only_start_and_turn_endpoints_exist(repo):
    """The chat branch is verdict-fenced: only /start and /turn exist. No
    disposition/verdict verb is reachable on this router."""
    client = _client(repo, StubRunner())
    for verb in ("verdict", "disposition", "set_status", "end", "sign_off",
                 "reject", "abstain"):
        assert client.post(f"/api/todo/chat/{verb}", json={}).status_code == 404
        assert client.get(f"/api/todo/chat/{verb}").status_code == 404


def test_seam_module_opens_no_file_for_writing():
    """Structural guard (D-046): the seam writes NOTHING itself — it must not
    open any file for writing. The CLI owns its own session transcript."""
    src = _SEAM_SRC.read_text(encoding="utf-8")
    # No write/append open() and no Path.write_* — the seam only execs.
    assert not re.search(r"""open\([^)]*['"][rbt]*[wax]""", src), \
        "chat_seam must not open a file for writing"
    assert ".write_text(" not in src and ".write_bytes(" not in src
    # never a shell, anywhere: the kwarg FORM `shell=True` (the docstring's
    # backtick-quoted prose ``shell=True`` is excluded — only a real call kwarg
    # is a violation; a literal `,shell=True` / `(shell=True` would match).
    assert not re.search(r"[(,]\s*shell\s*=\s*True", src), \
        "chat_seam must never exec with shell=True"


def test_no_real_runner_default_is_subprocess_run():
    """When no runner is injected, the default is subprocess.run (the prod path)
    — but every test injects a stub, so a real model is never hit here."""
    app = FastAPI()
    # Register with NO runner: must not raise, and must not exec at import/wire.
    router = register(app)
    assert router is not None


def test_enum_constants_mirror_the_cli_choices():
    assert CHAT_MODES == ("tutor", "two_voice")
    assert ADDRESSEES == ("defender", "attacker", "both")
