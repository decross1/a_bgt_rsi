"""In-UI attestation endpoint tests — Task 3 backend (D-046, blessed).

Tests NEVER exec against the live ledgers (the contract's test rule): every
app under test points at a tmp repo root and a STUBBED runner — no real
subprocess is ever spawned, no real CLI runs, nothing is written. An autouse
fixture snapshots the four live write-back ledgers around every test and
asserts zero rows were added.

What is pinned here:

- the EXACT argv arrays (incl. ``--gated-by human:ui`` / ``--by human:ui``),
  cwd = repo root, interpreter = .venv-chroma/bin/python, list-not-string,
  no ``shell=True``;
- 422 validation happens BEFORE spawn — the runner is never called;
- rc != 0 -> 502 carrying the CLI's stderr VERBATIM + the exit code;
- rc == 0 -> the CLI's stdout JSON returned, in BOTH stdout shapes
  (gate_cli/todo_cli print the appended ledger row; finding_session
  --set-status prints the envelope);
- the /api/attest/available capability handshake, true and false paths;
- NO direct-resolution endpoints for stale_active_run / state_gate
  (not blessed — defer is their only action).
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.attest import (
    DEFER_KINDS,
    FINDING_STATUSES,
    GATE_VERDICTS,
    IDENTITY,
    register,
)

_PRIMARY_REPO = Path("/home/decross1/projects/a_bgt_rsi")
# The four ledgers the blessed CLIs write. Tests must add ZERO rows to any.
_LIVE_LEDGERS = (
    "memory/loop_feedback.jsonl",
    "memory/dev_session_queue.jsonl",
    "memory/coordinator_acks.jsonl",
    "memory/surfaced_findings.status.jsonl",
)


def _ledger_sizes() -> dict[str, int | None]:
    """Line count per live ledger; None when the file does not exist (a
    test creating a previously-absent ledger is also a violation)."""
    sizes: dict[str, int | None] = {}
    for rel in _LIVE_LEDGERS:
        path = _PRIMARY_REPO / rel
        if path.exists():
            sizes[rel] = len(path.read_text(encoding="utf-8").splitlines())
        else:
            sizes[rel] = None
    return sizes


@pytest.fixture(autouse=True)
def no_live_ledger_writes():
    """Snapshot check: zero rows added to live write-back ledgers."""
    before = _ledger_sizes()
    yield
    after = _ledger_sizes()
    assert after == before, (
        f"live write-back ledgers changed during a test: {before} -> {after}")


class StubRunner:
    """Injectable runner double: records every call, returns a canned
    CompletedProcess, and never spawns anything."""

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


_REPO_FILES = (
    "orchestrator/gate_cli.py",
    "orchestrator/todo_cli.py",
    "orchestrator/finding_session.py",
    ".venv-chroma/bin/python",
)


@pytest.fixture()
def repo(tmp_path) -> Path:
    """A tmp 'primary repo root': the three blessed modules + the interpreter
    EXIST (for the /available existence checks) but are never executed —
    the runner is always stubbed."""
    for rel in _REPO_FILES:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    return tmp_path


def _client(repo_root: Path, runner) -> TestClient:
    """Bare FastAPI app + the attest router only (the integrator wires the
    real app.py registration; these tests exercise the module standalone)."""
    app = FastAPI()
    register(app, repo_root=repo_root, runner=runner)
    return TestClient(app)


def _py(repo_root: Path) -> str:
    return str(repo_root / ".venv-chroma" / "bin" / "python")


# Known-good payloads per endpoint (used by failure-path parametrization).
_VALID_PAYLOADS = {
    "gate_verdict": {"iteration_id": "iter-2026-06-09-001",
                     "verdict": "valid", "note": "journal checked"},
    "finding_review": {"finding_id": "sf-001",
                       "status": "validated", "note": "replicated locally"},
    "bubble_ack": {"bubble_run_id": "cyc-014", "note": "seen, harmless"},
    "defer": {"kind": "gate_verdict", "ref_id": "iter-2026-06-09-001",
              "note": "needs the primary session"},
}


# ─── /api/attest/available — capability handshake ──────────────────────


def test_available_true_when_modules_and_interpreter_exist(repo):
    client = _client(repo, StubRunner())
    resp = client.get("/api/attest/available")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "available": True,
        "actions": {"gate_verdict": True, "finding_review": True,
                    "bubble_ack": True, "defer": True},
    }


def test_available_false_when_interpreter_missing(repo):
    (repo / ".venv-chroma" / "bin" / "python").unlink()
    client = _client(repo, StubRunner())
    body = client.get("/api/attest/available").json()
    assert body["available"] is False
    assert body["actions"] == {"gate_verdict": False, "finding_review": False,
                               "bubble_ack": False, "defer": False}


def test_available_per_action_granularity(repo):
    # Only finding_session.py missing -> only finding_review degrades.
    (repo / "orchestrator" / "finding_session.py").unlink()
    client = _client(repo, StubRunner())
    body = client.get("/api/attest/available").json()
    assert body["available"] is False
    assert body["actions"] == {"gate_verdict": True, "finding_review": False,
                               "bubble_ack": True, "defer": True}


def test_available_false_on_empty_repo_root(tmp_path):
    client = _client(tmp_path / "nowhere", StubRunner())
    body = client.get("/api/attest/available").json()
    assert body["available"] is False
    assert not any(body["actions"].values())


def test_available_never_calls_the_runner(repo):
    runner = StubRunner()
    _client(repo, runner).get("/api/attest/available")
    assert runner.calls == []


# ─── POST /api/attest/gate_verdict ──────────────────────────────────────


def test_gate_verdict_execs_exact_argv(repo):
    # gate_cli prints the appended ledger row itself (single-line JSON).
    row = {"iteration_id": "iter-2026-06-09-001", "verdict": "valid",
           "note": "journal checked", "gated_at": "2026-06-10T12:00:00Z",
           "gated_by": "human:ui"}
    runner = StubRunner(returncode=0, stdout=json.dumps(row) + "\n")
    client = _client(repo, runner)
    resp = client.post("/api/attest/gate_verdict",
                       json=_VALID_PAYLOADS["gate_verdict"])
    assert resp.status_code == 200
    assert resp.json() == row
    assert resp.json()["gated_by"] == IDENTITY

    [call] = runner.calls
    assert call["argv"] == [
        _py(repo), "-m", "orchestrator.gate_cli",
        "--iteration-id", "iter-2026-06-09-001",
        "--verdict", "valid",
        "--note", "journal checked",
        "--gated-by", "human:ui",
    ]
    assert isinstance(call["argv"], list)          # argv ARRAY, never a string
    assert call["kwargs"]["cwd"] == str(repo)      # cwd = primary repo root
    assert call["kwargs"].get("shell") is not True  # no shell, ever


@pytest.mark.parametrize("verdict", list(GATE_VERDICTS))
def test_gate_verdict_accepts_every_frozen_verdict(repo, verdict):
    runner = StubRunner(stdout=json.dumps({"verdict": verdict}))
    client = _client(repo, runner)
    resp = client.post("/api/attest/gate_verdict", json={
        "iteration_id": "iter-2026-06-09-001", "verdict": verdict,
        "note": "ok"})
    assert resp.status_code == 200
    [call] = runner.calls
    assert call["argv"][6] == verdict


@pytest.mark.parametrize("payload", [
    # out-of-enum verdicts — frozen, never coerced
    {"iteration_id": "iter-001", "verdict": "approve", "note": "x"},
    {"iteration_id": "iter-001", "verdict": "VALID", "note": "x"},
    {"iteration_id": "iter-001", "verdict": "", "note": "x"},
    {"iteration_id": "iter-001", "note": "x"},                    # missing
    {"iteration_id": "iter-001", "verdict": None, "note": "x"},
    # note required non-empty
    {"iteration_id": "iter-001", "verdict": "valid", "note": ""},
    {"iteration_id": "iter-001", "verdict": "valid", "note": "   "},
    {"iteration_id": "iter-001", "verdict": "valid"},             # missing
    {"iteration_id": "iter-001", "verdict": "valid", "note": 42},
    # id charset — leading dash is the argv-flag-confusion injection vector
    {"iteration_id": "-iter-001", "verdict": "valid", "note": "x"},
    {"iteration_id": "--gated-by", "verdict": "valid", "note": "x"},
    {"iteration_id": "", "verdict": "valid", "note": "x"},
    {"iteration_id": "iter 001", "verdict": "valid", "note": "x"},
    {"iteration_id": "iter/../001", "verdict": "valid", "note": "x"},
    {"iteration_id": 42, "verdict": "valid", "note": "x"},
    {"verdict": "valid", "note": "x"},                            # missing id
])
def test_gate_verdict_422_spawns_nothing(repo, payload):
    runner = StubRunner()
    client = _client(repo, runner)
    resp = client.post("/api/attest/gate_verdict", json=payload)
    assert resp.status_code == 422
    assert runner.calls == []   # validate BEFORE spawn: nothing executed


# ─── POST /api/attest/finding_review ────────────────────────────────────


def test_finding_review_execs_exact_argv_and_returns_envelope(repo):
    # finding_session --set-status prints an ENVELOPE (indent=2), NOT a bare
    # ledger row — the human:ui stamp is status_audit_row.changed_by.
    envelope = {
        "finding_id": "sf-001",
        "session_id": None,
        "outcome": "validated",
        "loop_feedback_row": {
            "iteration_id": "iter-2026-06-08-002", "verdict": "valid",
            "note": "replicated locally", "gated_at": "2026-06-10T12:00:00Z",
            "gated_by": "human:ui",
        },
        "status_audit_row": {
            "finding_id": "sf-001", "status": "valid",
            "changed_at": "2026-06-10T12:00:00Z", "changed_by": "human:ui",
            "session_id": None, "reason": "replicated locally",
        },
    }
    runner = StubRunner(stdout=json.dumps(envelope, indent=2) + "\n")
    client = _client(repo, runner)
    resp = client.post("/api/attest/finding_review",
                       json=_VALID_PAYLOADS["finding_review"])
    assert resp.status_code == 200
    assert resp.json() == envelope                       # returned as-is
    assert resp.json()["status_audit_row"]["changed_by"] == IDENTITY

    [call] = runner.calls
    assert call["argv"] == [
        _py(repo), "-m", "orchestrator.finding_session",
        "--set-status", "sf-001", "validated",
        "--note", "replicated locally",
        "--by", "human:ui",
    ]
    assert call["kwargs"]["cwd"] == str(repo)
    assert call["kwargs"].get("shell") is not True


def test_finding_review_in_review_envelope_has_null_feedback_row(repo):
    envelope = {"finding_id": "sf-003", "session_id": None,
                "outcome": "in_review", "loop_feedback_row": None,
                "status_audit_row": {"finding_id": "sf-003",
                                     "status": "in_review",
                                     "changed_at": "2026-06-10T12:00:00Z",
                                     "changed_by": "human:ui",
                                     "session_id": None,
                                     "reason": "needs a deeper look"}}
    runner = StubRunner(stdout=json.dumps(envelope, indent=2))
    client = _client(repo, runner)
    resp = client.post("/api/attest/finding_review", json={
        "finding_id": "sf-003", "status": "in_review",
        "note": "needs a deeper look"})
    assert resp.status_code == 200
    assert resp.json()["loop_feedback_row"] is None      # in_review shape
    [call] = runner.calls
    assert call["argv"][3:6] == ["--set-status", "sf-003", "in_review"]


@pytest.mark.parametrize("payload", [
    # the GATE enum is NOT the finding enum — frozen, no cross-acceptance
    {"finding_id": "sf-001", "status": "valid", "note": "x"},
    {"finding_id": "sf-001", "status": "invalid", "note": "x"},
    {"finding_id": "sf-001", "status": "surfaced", "note": "x"},
    {"finding_id": "sf-001", "note": "x"},
    # note + id discipline
    {"finding_id": "sf-001", "status": "validated", "note": ""},
    {"finding_id": "sf-001", "status": "validated", "note": "  "},
    {"finding_id": "-sf-001", "status": "validated", "note": "x"},
    {"finding_id": "", "status": "validated", "note": "x"},
    {"status": "validated", "note": "x"},
])
def test_finding_review_422_spawns_nothing(repo, payload):
    runner = StubRunner()
    resp = _client(repo, runner).post("/api/attest/finding_review", json=payload)
    assert resp.status_code == 422
    assert runner.calls == []


# ─── POST /api/attest/bubble_ack ────────────────────────────────────────


def test_bubble_ack_execs_exact_argv(repo):
    # todo_cli prints the appended ledger row (indent=2).
    row = {"bubble_run_id": "cyc-014", "ack_by": "human:ui",
           "acked_at": "2026-06-10T12:00:00Z", "note": "seen, harmless"}
    runner = StubRunner(stdout=json.dumps(row, indent=2) + "\n")
    client = _client(repo, runner)
    resp = client.post("/api/attest/bubble_ack",
                       json=_VALID_PAYLOADS["bubble_ack"])
    assert resp.status_code == 200
    assert resp.json() == row
    assert resp.json()["ack_by"] == IDENTITY

    [call] = runner.calls
    assert call["argv"] == [
        _py(repo), "-m", "orchestrator.todo_cli",
        "ack",
        "--bubble-run-id", "cyc-014",
        "--note", "seen, harmless",
        "--by", "human:ui",
    ]
    assert call["kwargs"]["cwd"] == str(repo)
    assert call["kwargs"].get("shell") is not True


@pytest.mark.parametrize("payload", [
    {"bubble_run_id": "cyc-014", "note": ""},
    {"bubble_run_id": "cyc-014", "note": "   "},
    {"bubble_run_id": "cyc-014"},
    {"bubble_run_id": "-cyc-014", "note": "x"},
    {"bubble_run_id": "", "note": "x"},
    {"bubble_run_id": "cyc 014", "note": "x"},
    {"note": "x"},
])
def test_bubble_ack_422_spawns_nothing(repo, payload):
    runner = StubRunner()
    resp = _client(repo, runner).post("/api/attest/bubble_ack", json=payload)
    assert resp.status_code == 422
    assert runner.calls == []


# ─── POST /api/attest/defer ─────────────────────────────────────────────


@pytest.mark.parametrize("kind", list(DEFER_KINDS))
def test_defer_execs_exact_argv_for_every_kind(repo, kind):
    # Defer is blessed for EVERY kind — including stale_active_run and
    # state_gate, whose direct resolution is not blessed.
    row = {"ref_id": "ref-001", "kind": kind, "note": "route to dev session",
           "status": "open", "attested_by": "human:ui",
           "deferred_at": "2026-06-10T12:00:00Z"}
    runner = StubRunner(stdout=json.dumps(row, indent=2))
    client = _client(repo, runner)
    resp = client.post("/api/attest/defer", json={
        "kind": kind, "ref_id": "ref-001", "note": "route to dev session"})
    assert resp.status_code == 200
    assert resp.json() == row
    assert resp.json()["attested_by"] == IDENTITY

    [call] = runner.calls
    assert call["argv"] == [
        _py(repo), "-m", "orchestrator.todo_cli",
        "defer",
        "--kind", kind,
        "--ref-id", "ref-001",
        "--note", "route to dev session",
        "--by", "human:ui",
    ]
    assert call["kwargs"]["cwd"] == str(repo)
    assert call["kwargs"].get("shell") is not True


@pytest.mark.parametrize("payload", [
    {"kind": "unknown_kind", "ref_id": "r-1", "note": "x"},
    {"kind": "", "ref_id": "r-1", "note": "x"},
    {"ref_id": "r-1", "note": "x"},                       # missing kind
    {"kind": "gate_verdict", "ref_id": "-r-1", "note": "x"},
    {"kind": "gate_verdict", "ref_id": "", "note": "x"},
    {"kind": "gate_verdict", "note": "x"},                # missing ref_id
    {"kind": "gate_verdict", "ref_id": "r-1", "note": ""},
    {"kind": "gate_verdict", "ref_id": "r-1", "note": " "},
    {"kind": "gate_verdict", "ref_id": "r-1"},            # missing note
])
def test_defer_422_spawns_nothing(repo, payload):
    runner = StubRunner()
    resp = _client(repo, runner).post("/api/attest/defer", json=payload)
    assert resp.status_code == 422
    assert runner.calls == []


# ─── failure semantics — every endpoint, one contract ───────────────────


@pytest.mark.parametrize("endpoint", sorted(_VALID_PAYLOADS))
def test_nonzero_exit_returns_502_with_verbatim_stderr(repo, endpoint):
    stderr = ("rejected: verdict 'maybe' is not one of "
              "['valid', 'invalid', 'needs_revision']\n  (never coerced)\n")
    runner = StubRunner(returncode=1, stdout="", stderr=stderr)
    client = _client(repo, runner)
    resp = client.post(f"/api/attest/{endpoint}", json=_VALID_PAYLOADS[endpoint])
    assert resp.status_code == 502
    # stderr VERBATIM (whitespace, newlines and all) + the exit code.
    assert resp.json() == {"rc": 1, "stderr": stderr}
    assert len(runner.calls) == 1


def test_nonzero_exit_preserves_exit_code(repo):
    runner = StubRunner(returncode=2, stderr="usage: gate_cli ...")
    resp = _client(repo, runner).post("/api/attest/gate_verdict",
                                      json=_VALID_PAYLOADS["gate_verdict"])
    assert resp.status_code == 502
    assert resp.json() == {"rc": 2, "stderr": "usage: gate_cli ..."}


def test_spawn_failure_is_502_not_500(repo):
    runner = RaisingRunner()
    resp = _client(repo, runner).post("/api/attest/defer",
                                      json=_VALID_PAYLOADS["defer"])
    assert resp.status_code == 502
    body = resp.json()
    assert body["rc"] is None
    assert "No such file or directory" in body["stderr"]


def test_zero_exit_with_nonjson_stdout_is_502(repo):
    runner = StubRunner(returncode=0, stdout="wrote it!\n", stderr="")
    resp = _client(repo, runner).post("/api/attest/gate_verdict",
                                      json=_VALID_PAYLOADS["gate_verdict"])
    assert resp.status_code == 502
    body = resp.json()
    assert body["rc"] == 0
    assert body["stdout"] == "wrote it!\n"   # surfaced, not faked as success


# ─── unblessed kinds have NO direct-resolution endpoints ────────────────


@pytest.mark.parametrize("kind", ["stale_active_run", "state_gate"])
def test_no_direct_resolution_endpoint_for_unblessed_kinds(repo, kind):
    """Contract table row 5: direct resolution of these kinds is NOT
    blessed; the only attestation for them is /api/attest/defer."""
    client = _client(repo, StubRunner())
    assert client.post(f"/api/attest/{kind}", json={
        "ref_id": "r-1", "note": "x"}).status_code == 404
    assert client.get(f"/api/attest/{kind}").status_code == 404


# ─── frozen-enum constants stay frozen ──────────────────────────────────


def test_enum_constants_mirror_the_blessed_contract():
    assert GATE_VERDICTS == ("valid", "invalid", "needs_revision")
    assert FINDING_STATUSES == ("validated", "rejected", "in_review")
    assert DEFER_KINDS == ("gate_verdict", "finding_review", "bubble_ack",
                           "stale_active_run", "state_gate")
    assert IDENTITY == "human:ui"
