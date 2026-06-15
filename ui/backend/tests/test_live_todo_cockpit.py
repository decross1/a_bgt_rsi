"""Live-data validation of the /todo cockpit backend + the Dashboard coupling.

Sibling of ``test_validate_live_real_data.py`` (which validates the coordinator
endpoints against the real on-disk apparatus). This module validates the
**cockpit** surface and the **dashboard N coupling** against the REAL primary
checkout: it builds the merged app in-process via ``TestClient(create_app())``
with NO overrides, so the app reads the hardcoded ``_PRIMARY_REPO`` defaults
exactly as the served UI does — the files the dashboard actually renders.

It asserts the live truth without re-hardcoding a row count that would rot:

- ``GET /api/todo/available`` — the capability handshake. Reports the NEW
  cockpit seams as currently false/stub (no writer is blessed yet), surfaces
  ``interpreter_present`` against the real ``.venv-chroma/bin/python``, and
  carries the ``two_voice_chat`` chat-pane gate flag the cockpit reads.
- ``GET /api/todo/concurrency`` — the ONE real (non-stub) read, against the
  REAL ``run_state/active_run.json`` (absent OR present): never 500s, always
  carries an ``active`` boolean.
- ``GET /api/human_todo`` — the ``{items, counts}`` wrapper the dashboard's
  "N need you →" coupling consumes. Confirms ``gate_verdict`` AND ``state_gate``
  keys exist in ``counts`` (Dashboard.tsx sums exactly those two), every item
  carries the contract keys, and every kind is inside the known enum.
- Every ``/api/todo`` POST stub WRITES NOTHING (inviolate rule 4 — a stub never
  fakes a write) and returns a read-only ``would_run``: no ledger/file appears
  under ``memory/`` or ``run_state/`` across the full POST surface, and the
  cockpit never execs.

Read-only: GETs and stub POSTs only. The stub-POST no-write assertion snapshots
the real ``memory/``+``run_state/`` listing before and after and asserts no
delta — if a future seam wiring accidentally writes, this fails loudly.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app

# The primary checkout the cockpit / human_todo / active_run.json all pin
# (mirrors backend.app._PRIMARY_REPO / todo_cockpit._PRIMARY_REPO).
_PRIMARY_REPO = Path("/home/decross1/projects/a_bgt_rsi")

# The NEW cockpit seams (todo_cockpit._SEAM_MODULES) — all currently false/stub.
_SEAM_ACTIONS = (
    "authorize_fix",
    "directive_signoff",
    "spawn_topic",
    "abstain",
    "calibration",
)

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


@pytest.fixture(scope="module")
def client() -> TestClient:
    """The merged app, no overrides — reads the REAL primary checkout exactly as
    the served UI does."""
    return TestClient(create_app())


# --------------------------------------------------------------------------- #
# GET /api/todo/available — capability handshake (live)
# --------------------------------------------------------------------------- #

def test_available_handshake_shape_live(client: TestClient):
    r = client.get("/api/todo/available")
    assert r.status_code == 200
    body = r.json()
    # The whole router is stub/advisory-only until the seam plan ships.
    assert body["available"] is False
    assert body["stub"] is True
    # Surfaced against the REAL interpreter on disk.
    expect_python = (_PRIMARY_REPO / ".venv-chroma" / "bin" / "python").exists()
    assert body["interpreter_present"] is expect_python
    actions = body["actions"]
    assert isinstance(actions, dict)
    # Every NEW seam is currently false (no blessed writer yet).
    for name in _SEAM_ACTIONS:
        assert actions[name] is False, f"{name} should be false/stub"


def test_available_reports_two_voice_chat_gate_live(client: TestClient):
    # The cockpit gates the two-voice chat pane on this flag, so the handshake
    # MUST report it (and it stays False until finding_session's two-stance
    # extension lands).
    actions = client.get("/api/todo/available").json()["actions"]
    assert "two_voice_chat" in actions
    assert actions["two_voice_chat"] is False


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
# Every POST stub writes NOTHING (inviolate rule 4) — vs the REAL data dirs
# --------------------------------------------------------------------------- #

# The full stub-POST surface with a VALID payload for each (so we exercise the
# write path, not the 422 path — a 422 trivially writes nothing).
_STUB_POSTS = (
    ("/api/todo/authorize_fix",
     {"ref_id": "F-live-1", "task": "do the thing", "note": "because"}),
    ("/api/todo/directive_signoff",
     {"iteration_id": "iter-live-1", "note": "ok", "directive": "proceed"}),
    ("/api/todo/spawn_topic",
     {"ref_id": "F-live-1", "kind": "finding", "topic": "a follow-up"}),
    ("/api/todo/abstain",
     {"ref_id": "F-live-1", "note": "no verdict yet"}),
    ("/api/todo/calibration",
     {"ref_id": "iter-live-1", "prediction": "valid", "confidence": 0.5}),
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


@pytest.mark.parametrize("path,payload", _STUB_POSTS)
def test_stub_post_is_read_only_would_run_live(client: TestClient, path, payload):
    r = client.post(path, json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    # Honest stub: status=stub + a read-only would_run argv, NO faked verdict.
    assert body["status"] == "stub"
    assert isinstance(body["would_run"], list) and body["would_run"]
    # would_run is illustrative argv, never an exec — the bare relative
    # interpreter token, never absolutized to a real exec target.
    assert body["would_run"][0] == ".venv-chroma/bin/python"
    assert body["would_run"][1] == "-m"
    assert "seam" in body


def test_full_stub_post_surface_writes_no_ledger_live(client: TestClient):
    """The whole stub-POST surface, fired in sequence, leaves the REAL
    memory/+run_state/ listing byte-for-byte unchanged — no ledger file is
    created under any tmp/real path (D-046: the cockpit shells blessed CLIs;
    stubs are read-only would_run)."""
    before = _data_listing()
    for path, payload in _STUB_POSTS:
        assert client.post(path, json=payload).status_code == 200
    after = _data_listing()
    created = after - before
    assert not created, f"stub POSTs created files (must write NOTHING): {created}"
    removed = before - after
    assert not removed, f"stub POSTs removed files: {removed}"
