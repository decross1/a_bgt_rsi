"""Live-data validation of the coordinator (autonomy-observability) endpoints.

Unlike ``test_coordinator.py`` (which points every path at ``tmp_path`` and is
side-effect-free), this module validates the **merged backend against the REAL
on-disk apparatus data** — the files the dashboard actually renders. It builds
the app with no overrides, so ``create_app()`` reads the primary checkout via
the hardcoded ``DEFAULT_COORDINATOR_*`` defaults (``_PRIMARY_REPO``), exactly as
the served UI does. The stale :8700 server is pre-merge and 404s on these
routes; this in-process app is the post-merge surface under test.

It is read-only: it never writes ``run_state/`` or ``memory/``. The assertions
key off what is actually on disk (via the backend's own ``_read_jsonl``) so the
test states the live truth without re-hardcoding a row count that would rot when
the apparatus appends another cycle:

- ``/cycles`` must return the real ``coordinator_cycles.jsonl`` rows newest-first,
  and **every** row must carry the keys ``CoordinatorCycle`` reads (the frontend
  type). An ``errored`` outcome must carry a non-empty ``error`` string so the
  failed-dispatch row is never silent — asserted over whatever errored rows the
  live cohort holds. (2026-06-09 snapshot: 13 rows, 2 errored ``RuntimeError:
  boom`` outcomes; the 2026-06-10 D-048 purge removed those, so an EMPTY errored
  cohort is the honest live state, not a miss. All rows remain
  ``topic_source="arxiv_pick"`` / ``agent="coordinator"``.)
- ``/findings``, ``/bubbles``, ``/health_signals`` are shape-correct
  (``{key: [...]}``) and, while their (gitignored) files are absent, return an
  empty list — the clean empty state the panels render.
- ``/active`` returns 204 when no cycle is in flight (its file is absent), so the
  Activity panel shows the clean idle state, not a crash.

If the real ``coordinator_cycles.jsonl`` is ever absent (e.g. the data dir
moves), the cycle-shape tests skip rather than false-fail — the file is
gitignored and not guaranteed to exist in every checkout. The absent-file
endpoints are asserted conditionally on the file's live presence, so a later
EMIT write does not turn this into a flaky red.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import backend.app as app_module
from backend.app import create_app
from backend.coordinator import _read_jsonl

# The real, gitignored apparatus artifacts the merged backend reads. Pulled from
# the module constants (not re-hardcoded) so this test follows the same source
# of truth as the served app and survives a path change.
_CYCLES_PATH = app_module.DEFAULT_COORDINATOR_RUN_STATE / "coordinator_cycles.jsonl"
_ACTIVE_PATH = app_module.DEFAULT_COORDINATOR_RUN_STATE / "active_run.json"
_HEALTH_PATH = app_module.DEFAULT_COORDINATOR_RUN_STATE / "health_signals.jsonl"
_FINDINGS_PATH = app_module.DEFAULT_COORDINATOR_MEMORY / "surfaced_findings.jsonl"
_BUBBLES_PATH = app_module.DEFAULT_COORDINATOR_MEMORY / "coordinator_bubbles.jsonl"

# Keys the frontend ``CoordinatorCycle`` type reads as non-optional
# (ui/frontend/src/types/schemas.ts). The card crashes / mis-renders if a real
# row is missing any of these, so every live row must carry them.
_REQUIRED_CYCLE_KEYS = (
    "timestamp",
    "run_id",
    "agent",
    "topic",
    "topic_source",
    "plan",
    "outcomes",
)


@pytest.fixture(scope="module")
def client() -> TestClient:
    """The merged app over the REAL primary-checkout data (no path overrides)."""
    return TestClient(create_app())


# ─── /cycles — the 13 real rows the Coordinator view renders ───────────────


def test_cycles_endpoint_shape_against_real_data(client):
    resp = client.get("/api/coordinator/cycles")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"cycles"}
    assert isinstance(body["cycles"], list)


@pytest.mark.skipif(
    not _CYCLES_PATH.exists(),
    reason=f"real coordinator_cycles.jsonl absent ({_CYCLES_PATH}); gitignored",
)
def test_cycles_returns_every_real_row_newest_first(client):
    """/cycles serves exactly the rows on disk, newest-first by timestamp."""
    on_disk = _read_jsonl(_CYCLES_PATH)
    assert on_disk, "real coordinator_cycles.jsonl exists but parsed to 0 rows"

    cycles = client.get("/api/coordinator/cycles").json()["cycles"]
    # Every well-formed on-disk row is served (the endpoint skips only malformed
    # JSON lines, of which the real file has none).
    assert len(cycles) == len(on_disk)

    timestamps = [c["timestamp"] for c in cycles]
    assert timestamps == sorted(timestamps, reverse=True), "not newest-first"


@pytest.mark.skipif(
    not _CYCLES_PATH.exists(),
    reason=f"real coordinator_cycles.jsonl absent ({_CYCLES_PATH}); gitignored",
)
def test_every_real_cycle_has_the_keys_the_card_reads(client):
    """Each real row carries every non-optional CoordinatorCycle key — the
    Coordinator card reads these unconditionally."""
    cycles = client.get("/api/coordinator/cycles").json()["cycles"]
    for c in cycles:
        missing = [k for k in _REQUIRED_CYCLE_KEYS if k not in c]
        assert not missing, f"cycle {c.get('run_id')!r} missing keys {missing}"
        # The list-typed fields the card maps over must actually be lists, so a
        # `.map` never throws on a real row.
        assert isinstance(c["plan"], list)
        assert isinstance(c["outcomes"], list)
        assert isinstance(c.get("promoted_finding_ids", []), list)
        assert isinstance(c.get("bubble_run_ids", []), list)
        for step in c["plan"]:
            assert "action" in step  # CoordinatorPlanStep.action is required


@pytest.mark.skipif(
    not _CYCLES_PATH.exists(),
    reason=f"real coordinator_cycles.jsonl absent ({_CYCLES_PATH}); gitignored",
)
def test_real_errored_outcomes_carry_an_error_string(client):
    """The headline 'make absence legible' contract: a failed dispatch is a row,
    and an ``errored`` outcome carries a non-empty ``error`` so the red row shows
    *why*. Cohort-variant: the 2026-06-09 file held 2 such outcomes (RuntimeError:
    boom); the D-048 purge removed them, so this may assert over zero rows —
    vacuously green is the honest read of a clean cohort."""
    cycles = client.get("/api/coordinator/cycles").json()["cycles"]
    errored = [
        o
        for c in cycles
        for o in c["outcomes"]
        if o.get("status") == "errored"
    ]
    for o in errored:
        assert "action" in o  # CoordinatorOutcome.action is required
        assert isinstance(o.get("error"), str) and o["error"], (
            "an errored outcome must carry a non-empty error string so the "
            "failed-dispatch row renders the reason, not a silent gap"
        )


@pytest.mark.skipif(
    not _CYCLES_PATH.exists(),
    reason=f"real coordinator_cycles.jsonl absent ({_CYCLES_PATH}); gitignored",
)
def test_live_cycle_provenance_snapshot(client):
    """Pins the live-cohort provenance invariants: every real cycle is
    coordinator-authored and arxiv-picked. The errored sub-cohort is VARIANT —
    the 2026-06-09 snapshot held 2 ``RuntimeError: boom`` dispatch failures,
    which the 2026-06-10 D-048 purge removed — so instead of pinning a count
    that rots with the data, assert the failed-dispatch field semantics on
    whatever errored rows exist. An empty errored cohort is the honest
    post-purge state, never a fabricated expectation of failure."""
    cycles = client.get("/api/coordinator/cycles").json()["cycles"]
    assert cycles, "expected ≥1 real coordinator cycle"
    assert all(c["agent"] == "coordinator" for c in cycles)
    assert all(c["topic_source"] == "arxiv_pick" for c in cycles)
    errored = [
        o for c in cycles for o in c["outcomes"] if o.get("status") == "errored"
    ]
    # When a failed dispatch IS present it must be legible: an action plus a
    # non-empty error string (the make-absence-legible contract).
    for o in errored:
        assert "action" in o
        assert isinstance(o.get("error"), str) and o["error"]


# ─── findings / bubbles / health_signals — clean empty state while absent ──


def test_findings_endpoint_clean_empty_state(client):
    """{findings: [...]} always; an empty list while the file is absent (the
    clean-empty-state the panel renders), never a crash."""
    resp = client.get("/api/coordinator/findings")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"findings"}
    assert isinstance(body["findings"], list)
    if not _FINDINGS_PATH.exists():
        assert body["findings"] == []


def test_bubbles_endpoint_clean_empty_state(client):
    resp = client.get("/api/coordinator/bubbles")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"bubbles"}
    assert isinstance(body["bubbles"], list)
    if not _BUBBLES_PATH.exists():
        assert body["bubbles"] == []


def test_health_signals_endpoint_clean_empty_state(client):
    resp = client.get("/api/coordinator/health_signals")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"health_signals"}
    assert isinstance(body["health_signals"], list)
    if not _HEALTH_PATH.exists():
        assert body["health_signals"] == []


# ─── active — 204 idle state while no cycle is in flight ───────────────────


def test_active_clean_idle_state(client):
    """204 (empty body) while active_run.json is absent → the Activity panel
    shows a clean idle state, not a blank gap or a 500. If a cycle is mid-flight
    (the file exists), it must instead be valid JSON the panel can render."""
    resp = client.get("/api/coordinator/active")
    if not _ACTIVE_PATH.exists():
        assert resp.status_code == 204
        assert resp.content == b""
    else:
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        # Sanity that on-disk JSON round-trips through the endpoint unchanged.
        assert data == json.loads(_ACTIVE_PATH.read_text(encoding="utf-8"))
