"""`/todo` cockpit endpoint tests (mirror test_attest.py's discipline).

Three of the cockpit seams now exec their BLESSED CLI (D-046 — the CLI is the
writer of record) via ``attest._exec_blessed`` with an injected stub runner:

- ``authorize_fix``     -> ``orchestrator.authorize_fix authorize-fix ...``
- ``directive_signoff`` -> ``orchestrator.finding_session --set-status <FID>
  validated --note ... --directive ... --by human:ui`` (keyed on FINDING_ID)
- ``calibration``       -> ``orchestrator.calibration_cli calibration ...``

The remaining two seams are SESSION-EXITS, not one-shot writers — there is no
one-shot CLI verb for ``spawn_topic`` (5) / ``abstain`` (6); the only writer is
``finding_session``'s ``end_session`` reached through the chat session. So those
two endpoints WRITE NOTHING and exec NOTHING — they validate the id (422 on bad)
and return an honest ``{status:"session_exit", outcome, via}`` indicator.

What is pinned:
- each one-shot seam calls ``_exec_blessed`` with the RIGHT module + argv token
  list (asserted via the injected stub runner; the stub returns canned stdout —
  tests NEVER exec a real CLI or a real model);
- ``spawn_topic`` / ``abstain`` return the session-exit indicator, exec NOTHING,
  and write NOTHING (the autouse fixture asserts zero live-ledger rows);
- 422 validation happens with NO exec / NO write (out-of-shape input rejected,
  never coerced — inviolate rule 4);
- ``GET /api/todo/available`` shape: the three one-shot seams + ``two_voice_chat``
  flip True when their modules exist; ``spawn_topic`` / ``abstain`` stay False;
  the ``allowed_action_endpoints`` map is present + correct;
- ``GET /api/todo/concurrency`` is the ONE real read: tmp ``active_run.json`` =>
  ``active: True`` + surfaced fields; missing file => ``active: False``.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.todo_cockpit import (
    ALLOWED_ACTION_ENDPOINTS,
    IDENTITY,
    SPAWN_TOPIC_KINDS,
    register,
)

_PRIMARY_REPO = Path("/home/decross1/projects/a_bgt_rsi")
# Live ledgers the real writers touch. The cockpit must add ZERO rows to any of
# them in a test: the one-shot seams go through an injected STUB runner (no real
# exec), and the session-exits don't exec at all. Belt-and-suspenders check.
_LIVE_LEDGERS = (
    "memory/loop_feedback.jsonl",
    "memory/dev_session_queue.jsonl",
    "memory/finding_followups.jsonl",
    "run_state/week1.run.jsonl",
    "run_state/events.jsonl",
)


def _ledger_sizes() -> dict[str, int | None]:
    sizes: dict[str, int | None] = {}
    for rel in _LIVE_LEDGERS:
        path = _PRIMARY_REPO / rel
        sizes[rel] = (len(path.read_text(encoding="utf-8").splitlines())
                      if path.exists() else None)
    return sizes


@pytest.fixture(autouse=True)
def no_live_ledger_writes():
    """Snapshot check: zero rows added to any live ledger during a test."""
    before = _ledger_sizes()
    yield
    after = _ledger_sizes()
    assert after == before, (
        f"live ledgers changed during a cockpit test: {before} -> {after}")


class _StubRunner:
    """Injected in place of ``subprocess.run`` — records every blessed-exec argv
    and returns a canned zero-exit CompletedProcess-like result with VALID JSON
    on stdout (so ``_exec_blessed``'s ``json.loads`` succeeds). NEVER spawns a
    process (no real CLI, no real model)."""

    def __init__(self, stdout: str = '{"ok": true}', returncode: int = 0,
                 stderr: str = ""):
        self.calls: list[dict] = []
        self._stdout = stdout
        self._returncode = returncode
        self._stderr = stderr

    def __call__(self, argv, **kwargs):
        self.calls.append({"argv": list(argv), "kwargs": kwargs})

        class _Proc:
            returncode = self._returncode
            stdout = self._stdout
            stderr = self._stderr
        return _Proc()

    @property
    def last_argv(self) -> list[str]:
        assert self.calls, "no blessed exec was attempted"
        return self.calls[-1]["argv"]

    @property
    def last_module(self) -> str:
        # argv = [<python>, "-m", <module>, *tokens]
        argv = self.last_argv
        assert argv[1] == "-m", f"argv not a `-m` exec: {argv}"
        return argv[2]

    @property
    def last_tokens(self) -> list[str]:
        return self.last_argv[3:]


@pytest.fixture()
def repo(tmp_path) -> Path:
    """A tmp 'primary repo root' — the interpreter + the CORRECTED blessed seam
    modules EXIST (for the /available existence checks) but are never executed;
    the one-shot seams exec through the injected stub runner only."""
    for rel in (".venv-chroma/bin/python",
                "orchestrator/authorize_fix.py",
                "orchestrator/calibration_cli.py",
                "orchestrator/finding_session.py"):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    return tmp_path


def _client(repo_root: Path, runner=None) -> TestClient:
    app = FastAPI()
    register(app, repo_root=repo_root, runner=runner)
    return TestClient(app)


def _write_active_run(repo_root: Path, doc: dict) -> None:
    path = repo_root / "run_state" / "active_run.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")


# Known-good payloads per endpoint (used by the happy-path table). NB:
# directive_signoff keys on FINDING_ID now (not iteration_id); spawn_topic /
# abstain key on finding_id too (the session they exit is finding-scoped).
_VALID_PAYLOADS = {
    "authorize_fix": {"ref_id": "sf-001", "task": "re-run novelty on 02",
                      "note": "looks promising, worth an autonomous fix"},
    "directive_signoff": {"finding_id": "sf-001",
                          "note": "journal checked",
                          "directive": "proceed to promotion bar"},
    "spawn_topic": {"finding_id": "sf-002",
                    "topic": "does this hold under the 03 anchor?"},
    "abstain": {"finding_id": "sf-003", "note": "need to re-look after the soak"},
    "calibration": {"ref_id": "sf-001", "prediction": "I think this is valid",
                    "confidence": 0.7},
}

# The three seams that exec a blessed CLI (vs the two session-exits).
_ONE_SHOT_ENDPOINTS = ("authorize_fix", "directive_signoff", "calibration")
_SESSION_EXIT_ENDPOINTS = ("spawn_topic", "abstain")


# ─── GET /api/todo/available — capability handshake ─────────────────────


def test_available_flips_oneshot_seams_when_modules_present(repo):
    body = _client(repo).get("/api/todo/available").json()
    # The three one-shot seams light up because their CORRECTED modules exist.
    actions = body["actions"]
    assert actions["authorize_fix"] is True
    assert actions["directive_signoff"] is True
    assert actions["calibration"] is True
    # The chat seam landed -> two_voice_chat is True (finding_session.py exists).
    assert actions["two_voice_chat"] is True
    # spawn_topic / abstain stay False — they are session-exits, not one-shots.
    assert actions["spawn_topic"] is False
    assert actions["abstain"] is False
    # Every one-shot seam + the chat gate present => available True.
    assert body["available"] is True
    assert body["interpreter_present"] is True


def test_available_keys_are_the_five_actions_plus_chat(repo):
    actions = _client(repo).get("/api/todo/available").json()["actions"]
    assert set(actions) == {
        "authorize_fix", "directive_signoff", "spawn_topic",
        "abstain", "calibration", "two_voice_chat"}


def test_available_reports_two_voice_chat_true_when_chat_seam_present(repo):
    # The frontend gates the chat pane on actions.two_voice_chat; the chat seam
    # (finding_session) landed, so it is True when finding_session.py exists.
    actions = _client(repo).get("/api/todo/available").json()["actions"]
    assert "two_voice_chat" in actions
    assert actions["two_voice_chat"] is True


def test_available_two_voice_chat_false_when_finding_session_absent(tmp_path):
    # Only the interpreter exists — no finding_session.py => the chat gate (and
    # directive_signoff) are False, but the shape is stable.
    (tmp_path / ".venv-chroma" / "bin").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".venv-chroma" / "bin" / "python").write_text("", encoding="utf-8")
    actions = _client(tmp_path).get("/api/todo/available").json()["actions"]
    assert actions["two_voice_chat"] is False
    assert actions["directive_signoff"] is False


def test_available_exposes_allowed_action_endpoints_map(repo):
    body = _client(repo).get("/api/todo/available").json()
    assert body["allowed_action_endpoints"] == ALLOWED_ACTION_ENDPOINTS


def test_available_does_not_duplicate_the_blessed_outcomes(repo):
    # The 4 blessed outcomes live in attest.py — they must NOT appear here.
    actions = _client(repo).get("/api/todo/available").json()["actions"]
    for blessed in ("gate_verdict", "finding_review", "bubble_ack", "defer"):
        assert blessed not in actions


# ─── the allowed_actions -> cockpit endpoint map is present + correct ───


def test_allowed_action_endpoints_map_is_correct():
    # Documented in docs/cockpit_seam_wiring.md "allowed_actions -> cockpit
    # endpoint name map". sign_off covers BOTH directive sign-off and the bare
    # attest finding_review; refine_authorize_fix -> /authorize_fix; etc.
    assert ALLOWED_ACTION_ENDPOINTS["sign_off"] == [
        "/api/todo/directive_signoff", "/api/attest/finding_review"]
    assert ALLOWED_ACTION_ENDPOINTS["reject"] == ["/api/attest/finding_review"]
    assert ALLOWED_ACTION_ENDPOINTS["refine_defer"] == ["/api/attest/defer"]
    assert ALLOWED_ACTION_ENDPOINTS["refine_authorize_fix"] == [
        "/api/todo/authorize_fix"]
    # spawn_topic / abstain are session-exits (chat seam -> end_session).
    assert ALLOWED_ACTION_ENDPOINTS["spawn_topic"] == ["session-exit"]
    assert ALLOWED_ACTION_ENDPOINTS["abstain"] == ["session-exit"]


# ─── one-shot seams: exec the RIGHT blessed module + argv (stub runner) ──


def test_authorize_fix_execs_authorize_fix_module(repo):
    stub = _StubRunner()
    resp = _client(repo, runner=stub).post(
        "/api/todo/authorize_fix", json=_VALID_PAYLOADS["authorize_fix"])
    assert resp.status_code == 200
    # CORRECTED module: orchestrator.authorize_fix (was mis-targeted at todo_cli).
    assert stub.last_module == "orchestrator.authorize_fix"
    assert stub.last_tokens == [
        "authorize-fix",
        "--ref-id", "sf-001",
        "--task", "re-run novelty on 02",
        "--note", "looks promising, worth an autonomous fix",
        "--by", "human:ui",
    ]
    # The stub's canned JSON stdout is returned verbatim (not a faked verdict).
    assert resp.json() == {"ok": True}


def test_directive_signoff_execs_finding_session_set_status_with_finding_id(repo):
    stub = _StubRunner()
    resp = _client(repo, runner=stub).post(
        "/api/todo/directive_signoff", json=_VALID_PAYLOADS["directive_signoff"])
    assert resp.status_code == 200
    # CORRECTED module: finding_session --set-status (was mis-targeted at gate_cli
    # with verdict-style argv keyed on iteration_id).
    assert stub.last_module == "orchestrator.finding_session"
    assert stub.last_tokens == [
        "--set-status", "sf-001", "validated",
        "--note", "journal checked",
        "--directive", "proceed to promotion bar",
        "--by", "human:ui",
    ]
    # The old verdict-style flags are GONE.
    assert "--iteration-id" not in stub.last_tokens
    assert "--verdict" not in stub.last_tokens
    assert "--gated-by" not in stub.last_tokens


def test_directive_signoff_requires_finding_id_not_iteration_id(repo):
    stub = _StubRunner()
    # A caller still sending only iteration_id (no finding_id) must 422 — and
    # MUST NOT exec the CLI (the writer needs a finding_id).
    resp = _client(repo, runner=stub).post("/api/todo/directive_signoff", json={
        "iteration_id": "iter-2026-06-09-001",
        "note": "journal checked", "directive": "proceed"})
    assert resp.status_code == 422
    assert stub.calls == [], "must not exec when finding_id is missing"


def test_calibration_execs_calibration_cli_module(repo):
    stub = _StubRunner()
    resp = _client(repo, runner=stub).post(
        "/api/todo/calibration", json=_VALID_PAYLOADS["calibration"])
    assert resp.status_code == 200
    # CORRECTED module: orchestrator.calibration_cli (was mis-targeted at gate_cli).
    assert stub.last_module == "orchestrator.calibration_cli"
    assert stub.last_tokens == [
        "calibration",
        "--ref-id", "sf-001",
        "--prediction", "I think this is valid",
        # --confidence round-trips through the CLI's type=float via repr(float()).
        "--confidence", repr(0.7),
        "--by", "human:ui",
    ]


def test_calibration_confidence_repr_round_trips(repo):
    # repr(float(0.1)) == "0.1" — the float repr the CLI's type=float re-parses.
    stub = _StubRunner()
    _client(repo, runner=stub).post("/api/todo/calibration", json={
        "ref_id": "sf-1", "prediction": "p", "confidence": 0.1})
    argv = stub.last_tokens
    conf = argv[argv.index("--confidence") + 1]
    assert conf == "0.1"
    assert float(conf) == 0.1


@pytest.mark.parametrize("endpoint", _ONE_SHOT_ENDPOINTS)
def test_oneshot_seam_stamps_identity_and_uses_argv_array(repo, endpoint):
    stub = _StubRunner()
    resp = _client(repo, runner=stub).post(
        f"/api/todo/{endpoint}", json=_VALID_PAYLOADS[endpoint])
    assert resp.status_code == 200
    argv = stub.last_argv
    assert isinstance(argv, list)              # argv ARRAY, never a string
    assert argv[1] == "-m"                     # interpreter, -m, module, ...
    assert argv[2].startswith("orchestrator.")
    assert IDENTITY in argv                    # stamps human:ui


def test_oneshot_seam_propagates_cli_nonzero_as_502(repo):
    # A nonzero CLI exit -> 502 with stderr verbatim (attest._exec_blessed
    # contract); the cockpit never fakes a success shape.
    stub = _StubRunner(stdout="", returncode=1, stderr="rejected: bad ref_id\n")
    resp = _client(repo, runner=stub).post(
        "/api/todo/authorize_fix", json=_VALID_PAYLOADS["authorize_fix"])
    assert resp.status_code == 502
    body = resp.json()
    assert body["rc"] == 1
    assert body["stderr"] == "rejected: bad ref_id\n"   # verbatim


# ─── session-exits: spawn_topic / abstain WRITE NOTHING + exec NOTHING ───


def test_spawn_topic_returns_session_exit_and_execs_nothing(repo):
    stub = _StubRunner()
    resp = _client(repo, runner=stub).post(
        "/api/todo/spawn_topic", json=_VALID_PAYLOADS["spawn_topic"])
    assert resp.status_code == 200
    body = resp.json()
    # Honest session-exit indicator — NOT a stub would_run, NOT a faked write.
    assert body["status"] == "session_exit"
    assert body["outcome"] == "spawn_topic"
    assert body["finding_id"] == "sf-002"
    assert "end_session" in body["via"]
    assert "would_run" not in body
    # No CLI exec at all (the only writer is the in-session end_session).
    assert stub.calls == []


def test_abstain_returns_session_exit_and_execs_nothing(repo):
    stub = _StubRunner()
    resp = _client(repo, runner=stub).post(
        "/api/todo/abstain", json=_VALID_PAYLOADS["abstain"])
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "session_exit"
    # abstain maps to end_session outcome "abandoned" (no verdict ledger).
    assert body["outcome"] == "abandoned"
    assert body["finding_id"] == "sf-003"
    assert "end_session" in body["via"]
    # abstain is an explicit non-decision — no verdict anywhere, no exec.
    assert "verdict" not in body
    assert stub.calls == []


@pytest.mark.parametrize("endpoint", _SESSION_EXIT_ENDPOINTS)
def test_session_exit_validates_finding_id(repo, endpoint):
    stub = _StubRunner()
    # Missing finding_id => 422 (still validates the id), and execs nothing.
    resp = _client(repo, runner=stub).post(f"/api/todo/{endpoint}", json={})
    assert resp.status_code == 422
    assert stub.calls == []
    # A leading-dash id is rejected (argv-flag-injection guard preserved).
    resp = _client(repo, runner=stub).post(
        f"/api/todo/{endpoint}", json={"finding_id": "-sf-1"})
    assert resp.status_code == 422
    assert stub.calls == []


# ─── 422 validation — required fields / out-of-enum, never coerced ──────


@pytest.mark.parametrize("payload", [
    {"task": "t", "note": "n"},                        # missing ref_id
    {"ref_id": "", "task": "t", "note": "n"},
    {"ref_id": "-sf-001", "task": "t", "note": "n"},   # leading-dash flag inject
    {"ref_id": "sf-001", "note": "n"},                 # missing task
    {"ref_id": "sf-001", "task": "  ", "note": "n"},   # blank task
    {"ref_id": "sf-001", "task": "t", "note": ""},     # blank note
])
def test_authorize_fix_422(repo, payload):
    stub = _StubRunner()
    assert _client(repo, runner=stub).post(
        "/api/todo/authorize_fix", json=payload).status_code == 422
    assert stub.calls == [], "422 must not exec the CLI"


@pytest.mark.parametrize("payload", [
    {"note": "n", "directive": "d"},                   # missing finding_id
    {"finding_id": "-x", "note": "n", "directive": "d"},
    {"finding_id": "sf-1", "directive": "d"},          # missing note
    {"finding_id": "sf-1", "note": "n"},               # missing directive
    {"finding_id": "sf-1", "note": "n", "directive": " "},
])
def test_directive_signoff_422(repo, payload):
    stub = _StubRunner()
    assert _client(repo, runner=stub).post(
        "/api/todo/directive_signoff", json=payload).status_code == 422
    assert stub.calls == [], "422 must not exec the CLI"


@pytest.mark.parametrize("payload", [
    {"topic": "t"},                                    # missing finding_id
    {"finding_id": "-x", "topic": "t"},                # leading-dash inject
    {"finding_id": ""},                                # blank finding_id
    {"finding_id": "sf-1"},                            # missing topic
    {"finding_id": "sf-1", "topic": "  "},             # blank topic
])
def test_spawn_topic_422(repo, payload):
    assert _client(repo).post(
        "/api/todo/spawn_topic", json=payload).status_code == 422


def test_spawn_topic_kinds_enum_still_exposed():
    # SPAWN_TOPIC_KINDS stays a module constant (the session names the follow-up
    # kind), even though the session-exit endpoint no longer validates it.
    assert SPAWN_TOPIC_KINDS == ("finding", "step")


@pytest.mark.parametrize("payload", [
    {},                                                # missing finding_id
    {"finding_id": "-x"},
    {"finding_id": ""},
    {"finding_id": "sf-1"},                            # missing note
    {"finding_id": "sf-1", "note": "  "},              # blank note
])
def test_abstain_422(repo, payload):
    assert _client(repo).post("/api/todo/abstain", json=payload).status_code == 422


@pytest.mark.parametrize("payload", [
    {"prediction": "p", "confidence": 0.5},            # missing ref_id
    {"ref_id": "sf-1", "confidence": 0.5},             # missing prediction
    {"ref_id": "sf-1", "prediction": "p"},             # missing confidence
    {"ref_id": "sf-1", "prediction": "p", "confidence": "high"},  # non-numeric
    {"ref_id": "sf-1", "prediction": "p", "confidence": True},    # bool != number
    {"ref_id": "sf-1", "prediction": "p", "confidence": 1.5},     # out of [0,1]
    {"ref_id": "sf-1", "prediction": "p", "confidence": -0.1},
])
def test_calibration_422(repo, payload):
    stub = _StubRunner()
    assert _client(repo, runner=stub).post(
        "/api/todo/calibration", json=payload).status_code == 422
    assert stub.calls == [], "422 must not exec the CLI"


def test_calibration_accepts_boundary_confidence(repo):
    stub = _StubRunner()
    for c in (0.0, 1.0, 0, 1):
        resp = _client(repo, runner=stub).post("/api/todo/calibration", json={
            "ref_id": "sf-1", "prediction": "p", "confidence": c})
        assert resp.status_code == 200


# ─── GET /api/todo/concurrency — the ONE real (non-stub) read ───────────


def test_concurrency_absent_file_is_inactive(repo):
    body = _client(repo).get("/api/todo/concurrency").json()
    assert body == {"active": False}


def test_concurrency_surfaces_active_run_fields(repo):
    _write_active_run(repo, {
        "kind": "loop_v0", "label": "iter-2026-06-14-001",
        "narration": "embedding the candidate", "started_at": "2026-06-14T10:00:00Z"})
    body = _client(repo).get("/api/todo/concurrency").json()
    assert body["active"] is True
    assert body["kind"] == "loop_v0"
    assert body["label"] == "iter-2026-06-14-001"
    assert body["narration"] == "embedding the candidate"


def test_concurrency_omits_absent_optional_fields(repo):
    _write_active_run(repo, {"kind": "ad_hoc", "label": "promote_findings"})
    body = _client(repo).get("/api/todo/concurrency").json()
    assert body == {"active": True, "kind": "ad_hoc", "label": "promote_findings"}


def test_concurrency_malformed_file_fails_safe_to_inactive(repo):
    path = repo / "run_state" / "active_run.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    assert _client(repo).get("/api/todo/concurrency").json() == {"active": False}
