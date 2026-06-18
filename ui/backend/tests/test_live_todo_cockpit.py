"""Live-data validation of the /todo cockpit backend + the Dashboard coupling.

Sibling of ``test_validate_live_real_data.py`` (which validates the coordinator
endpoints against the real on-disk apparatus). This module validates the
**cockpit** surface and the **dashboard N coupling** against the REAL primary
checkout: the GET reads build the merged app in-process via
``TestClient(create_app())`` with NO overrides, so the app reads the hardcoded
``_PRIMARY_REPO`` defaults exactly as the served UI does — the files the
dashboard actually renders.

The POST seams now exec their BLESSED CLI (D-046 — the CLI is the writer of
record). A live test must NEVER exec a real CLI or a real model, so the POST
checks build a cockpit-only app with an INJECTED STUB runner (over the real
``_PRIMARY_REPO`` so the seams are "available"); the stub records the argv and
returns canned JSON without spawning anything. The GET reads stay on the real
merged app.

It asserts the live truth without re-hardcoding a row count that would rot:

- ``GET /api/todo/available`` — the capability handshake. With the real
  corrected modules on disk the three one-shot seams + ``two_voice_chat`` are
  True; ``spawn_topic`` / ``abstain`` stay False (session-exits). Surfaces
  ``interpreter_present`` against the real ``.venv-chroma/bin/python`` and the
  documented ``allowed_action_endpoints`` map.
- ``GET /api/todo/concurrency`` — the ONE real (non-stub) read, against the
  REAL ``run_state/active_run.json`` (absent OR present): never 500s, always
  carries an ``active`` boolean.
- ``GET /api/human_todo`` — the ``{items, counts}`` wrapper the dashboard's
  "N need you →" coupling consumes. Confirms ``gate_verdict`` AND ``state_gate``
  keys exist in ``counts`` (Dashboard.tsx sums exactly those two), every item
  carries the contract keys, and every kind is inside the known enum.
- Every ``/api/todo`` POST, fired with the injected STUB runner, WRITES NOTHING
  (inviolate rule 4 — no real exec, no faked write): no ledger/file appears
  under ``memory/`` or ``run_state/`` across the full POST surface.

Read-only against disk: the GETs read the real checkout; the POSTs use a stub
runner so no real CLI runs (the no-write snapshot proves it).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.todo_cockpit import register as register_cockpit

# The primary checkout the cockpit / human_todo / active_run.json all pin
# (mirrors backend.app._PRIMARY_REPO / todo_cockpit._PRIMARY_REPO).
_PRIMARY_REPO = Path("/home/decross1/projects/a_bgt_rsi")

# The three one-shot cockpit seams that exec a blessed CLI (vs the two
# session-exits spawn_topic / abstain).
_ONE_SHOT_ACTIONS = ("authorize_fix", "directive_signoff", "calibration")
_SESSION_EXIT_ACTIONS = ("spawn_topic", "abstain")

# The human_todo producer's frozen kind enum (human_todo.KINDS).
_HUMAN_TODO_KINDS = frozenset((
    "gate_verdict",
    "finding_review",
    "bubble_ack",
    "stale_active_run",
    "state_gate",
))

# The contract keys every human_todo item carries (human_todo._item).
_TODO_ITEM_KEYS = frozenset((
    "kind", "id", "title", "since", "detail", "resolve_command",
))


class _StubRunner:
    """Stand-in for ``subprocess.run`` — records argv, returns a canned zero-exit
    result with VALID JSON stdout. NEVER spawns a process (no real CLI/model)."""

    def __init__(self):
        self.calls: list[list[str]] = []

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))

        class _Proc:
            returncode = 0
            stdout = '{"ok": true}'
            stderr = ""
        return _Proc()


@pytest.fixture(scope="module")
def client() -> TestClient:
    """The merged app, no overrides — reads the REAL primary checkout exactly as
    the served UI does (GET reads only)."""
    return TestClient(create_app())


def _cockpit_client(runner) -> TestClient:
    """A cockpit-only app over the REAL _PRIMARY_REPO but with an INJECTED stub
    runner, so a POST exercises the exec path WITHOUT spawning a real CLI."""
    app = FastAPI()
    register_cockpit(app, repo_root=_PRIMARY_REPO, runner=runner)
    return TestClient(app)


# --------------------------------------------------------------------------- #
# GET /api/todo/available — capability handshake (live)
# --------------------------------------------------------------------------- #

def test_available_handshake_shape_live(client: TestClient):
    r = client.get("/api/todo/available")
    assert r.status_code == 200
    body = r.json()
    # Surfaced against the REAL interpreter on disk.
    expect_python = (_PRIMARY_REPO / ".venv-chroma" / "bin" / "python").exists()
    assert body["interpreter_present"] is expect_python
    actions = body["actions"]
    assert isinstance(actions, dict)
    # The three one-shot seams light up iff their corrected module is on disk.
    for name in _ONE_SHOT_ACTIONS:
        rel = {
            "authorize_fix": "orchestrator/authorize_fix.py",
            "directive_signoff": "orchestrator/finding_session.py",
            "calibration": "orchestrator/calibration_cli.py",
        }[name]
        expect = expect_python and (_PRIMARY_REPO / rel).exists()
        assert actions[name] is expect, f"{name} availability vs disk"
    # spawn_topic / abstain stay False — they are session-exits, not one-shots.
    for name in _SESSION_EXIT_ACTIONS:
        assert actions[name] is False, f"{name} is a session-exit (stays false)"


def test_available_reports_two_voice_chat_gate_live(client: TestClient):
    # The cockpit gates the two-voice chat pane on this flag. The chat seam
    # (finding_session) landed, so it is True iff finding_session.py is on disk.
    body = client.get("/api/todo/available").json()
    actions = body["actions"]
    assert "two_voice_chat" in actions
    expect = ((_PRIMARY_REPO / ".venv-chroma" / "bin" / "python").exists()
              and (_PRIMARY_REPO / "orchestrator" / "finding_session.py").exists())
    assert actions["two_voice_chat"] is expect


def test_available_exposes_allowed_action_endpoints_map_live(client: TestClient):
    body = client.get("/api/todo/available").json()
    endpoints = body["allowed_action_endpoints"]
    # The documented escalation allowed_actions -> cockpit endpoint map.
    assert endpoints["refine_authorize_fix"] == ["/api/todo/authorize_fix"]
    assert endpoints["sign_off"] == [
        "/api/todo/directive_signoff", "/api/attest/finding_review"]
    assert endpoints["spawn_topic"] == ["session-exit"]


# --------------------------------------------------------------------------- #
# GET /api/todo/concurrency — the ONE real read, vs REAL active_run.json
# --------------------------------------------------------------------------- #

def test_concurrency_against_real_active_run_live(client: TestClient):
    r = client.get("/api/todo/concurrency")
    # Never 500s — always a safe body with an `active` boolean.
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["active"], bool)
    active_run = _PRIMARY_REPO / "run_state" / "active_run.json"
    if not active_run.exists():
        # Absent file => clean idle, the live state in this checkout.
        assert body == {"active": False}
    else:
        # Present => active:true with at most the surfaced scalar fields.
        assert body["active"] is True
        assert set(body) <= {"active", "kind", "label", "narration"}


# --------------------------------------------------------------------------- #
# GET /api/human_todo — the {items, counts} the Dashboard N coupling consumes
# --------------------------------------------------------------------------- #

def test_human_todo_wrapper_and_coupling_keys_live(client: TestClient):
    r = client.get("/api/human_todo")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"items", "counts"}
    counts = body["counts"]
    assert isinstance(counts, dict)
    # The Dashboard "N need you →" coupling sums exactly these two keys
    # (ui/frontend/src/routes/Dashboard.tsx:153). They MUST be present so the
    # coupling never reads `undefined`.
    assert "gate_verdict" in counts, "Dashboard sums counts.gate_verdict"
    assert "state_gate" in counts, "Dashboard sums counts.state_gate"
    # Every known kind has a counts slot (the producer seeds all KINDS to 0).
    assert _HUMAN_TODO_KINDS <= set(counts)
    for kind, n in counts.items():
        assert isinstance(n, int) and n >= 0


def test_human_todo_items_shape_and_kinds_live(client: TestClient):
    body = client.get("/api/human_todo").json()
    items = body["items"]
    counts = body["counts"]
    assert isinstance(items, list)
    # Counts must reconcile with the items actually listed (per-kind).
    recomputed = {k: 0 for k in counts}
    for item in items:
        assert set(item) >= _TODO_ITEM_KEYS, f"item missing contract keys: {set(item)}"
        assert item["kind"] in _HUMAN_TODO_KINDS, f"unknown kind {item['kind']!r}"
        recomputed[item["kind"]] += 1
    for kind in _HUMAN_TODO_KINDS:
        assert recomputed[kind] == counts[kind], (
            f"count/item mismatch for {kind}: "
            f"{counts[kind]} counted vs {recomputed[kind]} listed")


# --------------------------------------------------------------------------- #
# Every POST writes NOTHING (inviolate rule 4) — stub runner, vs the REAL dirs
# --------------------------------------------------------------------------- #

# The full POST surface with a VALID payload for each (so we exercise the write
# path, not the 422 path — a 422 trivially writes nothing). directive_signoff /
# spawn_topic / abstain key on finding_id now (the U4 corrections).
_POSTS = (
    ("/api/todo/authorize_fix",
     {"ref_id": "F-live-1", "task": "do the thing", "note": "because"}),
    ("/api/todo/directive_signoff",
     {"finding_id": "F-live-1", "note": "ok", "directive": "proceed"}),
    ("/api/todo/spawn_topic",
     {"finding_id": "F-live-1", "topic": "a follow-up"}),
    ("/api/todo/abstain",
     {"finding_id": "F-live-1", "note": "no verdict yet"}),
    ("/api/todo/calibration",
     {"ref_id": "F-live-1", "prediction": "valid", "confidence": 0.5}),
)


def _data_listing() -> set[str]:
    """Every file under the REAL memory/ + run_state/ (the dirs a faked write
    would land in). A set so an added/removed file shows as a delta."""
    out: set[str] = set()
    for sub in ("memory", "run_state"):
        d = _PRIMARY_REPO / sub
        if d.exists():
            out |= {str(p) for p in d.rglob("*") if p.is_file()}
    return out


@pytest.mark.parametrize("path,payload", _POSTS)
def test_post_is_honest_and_does_not_exec_real_cli_live(path, payload):
    stub = _StubRunner()
    r = _cockpit_client(stub).post(path, json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    if path.endswith(("spawn_topic", "abstain")):
        # Session-exit: honest indicator, NO exec, NO faked write.
        assert body["status"] == "session_exit"
        assert body["finding_id"] == "F-live-1"
        assert stub.calls == []
    else:
        # One-shot seam: exec'd the blessed CLI through the STUB (never a real
        # process). The stub's canned JSON is returned verbatim.
        assert body == {"ok": True}
        assert len(stub.calls) == 1
        argv = stub.calls[0]
        assert argv[1] == "-m" and argv[2].startswith("orchestrator.")
        assert "human:ui" in argv


def test_full_post_surface_writes_no_ledger_live():
    """The whole POST surface, fired in sequence with a STUB runner, leaves the
    REAL memory/+run_state/ listing byte-for-byte unchanged — no ledger file is
    created (D-046: the cockpit execs blessed CLIs; the stub runs no real CLI,
    so nothing is written)."""
    stub = _StubRunner()
    cockpit = _cockpit_client(stub)
    before = _data_listing()
    for path, payload in _POSTS:
        assert cockpit.post(path, json=payload).status_code == 200
    after = _data_listing()
    created = after - before
    assert not created, f"POSTs created files (must write NOTHING): {created}"
    removed = before - after
    assert not removed, f"POSTs removed files: {removed}"
