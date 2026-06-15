"""`/todo` cockpit stub-endpoint tests (mirror test_attest.py's discipline).

The cockpit's NET-NEW seams have no writer of record yet (the primary ships
``docs/todo_cockpit_seam_plan.md`` first), so every POST here is an honest STUB:
it validates the payload shape (422 on missing/empty/out-of-enum, never a silent
default — inviolate rule 4), returns ``{status:"stub", seam, would_run:[argv...]}``
echoing the future blessed CLI argv, and writes NOTHING.

What is pinned:
- each stub returns ``status:"stub"`` + a NON-EMPTY would_run argv list (list,
  not string; interpreter + ``-m <module>`` + the seam-plan argv verbatim);
- 422 validation happens with NO write (the stubs never open a ledger anyway —
  there is no runner to stub; an autouse fixture asserts zero live-ledger rows);
- ``GET /api/todo/available`` shape: ``available: False`` (no NEW seam built),
  ``stub: True``, all per-action flags False;
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
    IDENTITY,
    SPAWN_TOPIC_KINDS,
    register,
)

_PRIMARY_REPO = Path("/home/decross1/projects/a_bgt_rsi")
# Live ledgers the FUTURE writers will touch. The stubs must add ZERO rows to
# any of them (they don't write at all — this is the belt-and-suspenders check).
_LIVE_LEDGERS = (
    "memory/loop_feedback.jsonl",
    "memory/dev_session_queue.jsonl",
    "memory/finding_followups.jsonl",
    "run_state/week1.run.jsonl",
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
        f"live ledgers changed during a stub test: {before} -> {after}")


@pytest.fixture()
def repo(tmp_path) -> Path:
    """A tmp 'primary repo root' — the interpreter + the seam target modules
    EXIST (for the /available existence checks) but are never executed; no stub
    ever runs a subprocess."""
    for rel in (".venv-chroma/bin/python",
                "orchestrator/todo_cli.py",
                "orchestrator/gate_cli.py",
                "orchestrator/finding_session.py"):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    return tmp_path


def _client(repo_root: Path) -> TestClient:
    app = FastAPI()
    register(app, repo_root=repo_root)
    return TestClient(app)


def _write_active_run(repo_root: Path, doc: dict) -> None:
    path = repo_root / "run_state" / "active_run.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")


# Known-good payloads per stub endpoint (used by the happy-path table).
_VALID_PAYLOADS = {
    "authorize_fix": {"ref_id": "sf-001", "task": "re-run novelty on 02",
                      "note": "looks promising, worth an autonomous fix"},
    "directive_signoff": {"iteration_id": "iter-2026-06-09-001",
                          "note": "journal checked",
                          "directive": "proceed to promotion bar"},
    "spawn_topic": {"ref_id": "sf-002", "kind": "finding",
                    "topic": "does this hold under the 03 anchor?"},
    "abstain": {"ref_id": "sf-003", "note": "need to re-look after the soak"},
    "calibration": {"ref_id": "sf-001", "prediction": "I think this is valid",
                    "confidence": 0.7},
}


# ─── GET /api/todo/available — capability handshake ─────────────────────


def test_available_reports_all_new_seams_unbuilt(repo):
    body = _client(repo).get("/api/todo/available").json()
    assert body["available"] is False          # no NEW seam is built yet
    assert body["stub"] is True                # the whole router is advisory
    # The five POST-seams PLUS two_voice_chat (the chat pane the frontend gates
    # on actions.two_voice_chat — it has no would-run CLI of its own).
    assert set(body["actions"]) == {
        "authorize_fix", "directive_signoff", "spawn_topic",
        "abstain", "calibration", "two_voice_chat"}
    assert all(v is False for v in body["actions"].values())


def test_available_reports_two_voice_chat_false(repo):
    # The frontend gates the chat pane on actions.two_voice_chat; the backend
    # must report it (False until the finding_session two-stance seam lands).
    actions = _client(repo).get("/api/todo/available").json()["actions"]
    assert "two_voice_chat" in actions
    assert actions["two_voice_chat"] is False


def test_available_does_not_duplicate_the_blessed_outcomes(repo):
    # The 4 blessed outcomes live in attest.py — they must NOT appear here.
    actions = _client(repo).get("/api/todo/available").json()["actions"]
    for blessed in ("gate_verdict", "finding_review", "bubble_ack", "defer"):
        assert blessed not in actions


# ─── POST stubs — happy path: status:"stub" + non-empty would_run ───────


@pytest.mark.parametrize("endpoint", sorted(_VALID_PAYLOADS))
def test_stub_returns_stub_status_and_nonempty_argv(repo, endpoint):
    resp = _client(repo).post(f"/api/todo/{endpoint}",
                              json=_VALID_PAYLOADS[endpoint])
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "stub"            # never a faked write/verdict
    assert isinstance(body["would_run"], list) # argv ARRAY, never a string
    assert len(body["would_run"]) > 0          # non-empty
    assert body["would_run"][1] == "-m"        # interpreter, -m, module, ...
    assert body["would_run"][2].startswith("orchestrator.")
    assert IDENTITY in body["would_run"]       # stamps human:ui


def test_authorize_fix_echoes_seam_plan_argv(repo):
    body = _client(repo).post("/api/todo/authorize_fix",
                              json=_VALID_PAYLOADS["authorize_fix"]).json()
    assert body["seam"] == "authorize-fix"
    assert body["would_run"][1:] == [
        "-m", "orchestrator.todo_cli", "authorize-fix",
        "--ref-id", "sf-001",
        "--task", "re-run novelty on 02",
        "--note", "looks promising, worth an autonomous fix",
        "--by", "human:ui",
    ]


def test_directive_signoff_is_gate_verdict_superset(repo):
    # would_run = the blessed gate_verdict argv PLUS --directive <next-step>.
    body = _client(repo).post("/api/todo/directive_signoff",
                              json=_VALID_PAYLOADS["directive_signoff"]).json()
    argv = body["would_run"]
    assert argv[1:3] == ["-m", "orchestrator.gate_cli"]
    assert "--directive" in argv
    assert argv[argv.index("--directive") + 1] == "proceed to promotion bar"
    # the bare gate_verdict flags are all present (clean degrade target)
    for flag, val in (("--iteration-id", "iter-2026-06-09-001"),
                      ("--verdict", "valid"),
                      ("--note", "journal checked"),
                      ("--gated-by", "human:ui")):
        assert argv[argv.index(flag) + 1] == val


def test_spawn_topic_and_abstain_echo_ref_and_identity(repo):
    st = _client(repo).post("/api/todo/spawn_topic",
                            json=_VALID_PAYLOADS["spawn_topic"]).json()
    assert st["seam"] == "spawn-topic"
    assert "--kind" in st["would_run"]
    ab = _client(repo).post("/api/todo/abstain",
                            json=_VALID_PAYLOADS["abstain"]).json()
    assert ab["seam"] == "abstain"
    # abstain is an explicit non-decision — no verdict flag in its argv.
    assert "--verdict" not in ab["would_run"]


def test_calibration_echoes_prediction_and_confidence(repo):
    body = _client(repo).post("/api/todo/calibration",
                              json=_VALID_PAYLOADS["calibration"]).json()
    argv = body["would_run"]
    assert argv[argv.index("--prediction") + 1] == "I think this is valid"
    assert "--confidence" in argv


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
    assert _client(repo).post("/api/todo/authorize_fix",
                              json=payload).status_code == 422


@pytest.mark.parametrize("payload", [
    {"note": "n", "directive": "d"},                   # missing iteration_id
    {"iteration_id": "-x", "note": "n", "directive": "d"},
    {"iteration_id": "iter-1", "directive": "d"},      # missing note
    {"iteration_id": "iter-1", "note": "n"},           # missing directive
    {"iteration_id": "iter-1", "note": "n", "directive": " "},
])
def test_directive_signoff_422(repo, payload):
    assert _client(repo).post("/api/todo/directive_signoff",
                              json=payload).status_code == 422


@pytest.mark.parametrize("payload", [
    {"ref_id": "sf-1", "kind": "bogus", "topic": "t"},    # out-of-enum kind
    {"ref_id": "sf-1", "kind": "", "topic": "t"},
    {"ref_id": "sf-1", "topic": "t"},                     # missing kind
    {"ref_id": "sf-1", "kind": "finding", "topic": ""},   # blank topic
    {"kind": "finding", "topic": "t"},                    # missing ref_id
])
def test_spawn_topic_422(repo, payload):
    assert _client(repo).post("/api/todo/spawn_topic",
                              json=payload).status_code == 422


def test_spawn_topic_accepts_every_frozen_kind(repo):
    for kind in SPAWN_TOPIC_KINDS:
        resp = _client(repo).post("/api/todo/spawn_topic", json={
            "ref_id": "sf-1", "kind": kind, "topic": "t"})
        assert resp.status_code == 200


@pytest.mark.parametrize("payload", [
    {"note": "n"},                                     # missing ref_id
    {"ref_id": "-x", "note": "n"},
    {"ref_id": "sf-1", "note": ""},                    # blank note
    {"ref_id": "sf-1"},                                # missing note
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
    assert _client(repo).post("/api/todo/calibration",
                              json=payload).status_code == 422


def test_calibration_accepts_boundary_confidence(repo):
    for c in (0.0, 1.0, 0, 1):
        resp = _client(repo).post("/api/todo/calibration", json={
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
