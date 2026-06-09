"""Live validation of the RUNNING :8700 server (post-merge restart).

Sibling of ``test_validate_live_real_data.py``, but with the opposite target:
that module asserts the **in-process** app (``TestClient(create_app())``) over
the real on-disk data; this one asserts the **served process** at
``http://localhost:8700`` — the binary the dashboard actually talks to. The two
read the same real files, so their payloads must agree; a divergence here means
the running server is importing stale code or pointing at the wrong paths
(exactly the pre-merge-404 failure mode the 2026-06-09 validation caught).

Skips cleanly (module-level ``skipif``) when nothing answers on :8700 — the
server is not guaranteed to be up in every checkout/CI context, and an absent
server is "not under test", not a failure. With the server up it asserts:

- every ``/api/coordinator/*`` route is live: 200, or 204 for ``/active`` when
  no cycle is in flight (the clean idle state, not a 404).
- ``/cycles`` carries the real history: >= 19 rows (the cohort observed at the
  post-merge restart was 73; the file is append-only so the count only grows —
  a lower bound stays green, an exact pin would rot), every row carrying the
  keys the frontend ``CoordinatorCycle`` type reads as non-optional.
- ``/findings`` / ``/bubbles`` / ``/health_signals`` return their
  ``{key: [...]}`` wrapper shape (list-valued; row counts are cohort-variant,
  the wrapper is the contract).
- ``/api/health`` reports ``ok`` with a version string, so a stale-binary skew
  is visible in the failure message, not just inferred.

Read-only: GETs only, never writes ``run_state/`` or ``memory/``.
"""
from __future__ import annotations

import httpx
import pytest

BASE_URL = "http://localhost:8700"
PROBE_TIMEOUT_S = 2.0


def _server_reachable() -> bool:
    """Quick probe: anything HTTP answering on :8700. Any response code counts
    as reachable — only a connect/timeout error means 'no server'."""
    try:
        httpx.get(f"{BASE_URL}/api/health", timeout=PROBE_TIMEOUT_S)
        return True
    except httpx.HTTPError:
        return False


_SERVER_UP = _server_reachable()

pytestmark = pytest.mark.skipif(
    not _SERVER_UP,
    reason=f"no live server answering on {BASE_URL} — live validation not applicable",
)

# Keys the frontend ``CoordinatorCycle`` type reads as non-optional
# (ui/frontend/src/types/schemas.ts). Mirrors test_validate_live_real_data.py.
_REQUIRED_CYCLE_KEYS = (
    "timestamp",
    "run_id",
    "agent",
    "topic",
    "topic_source",
    "plan",
    "outcomes",
)

# The append-only cycles file held 19+ rows when the post-merge server was
# validated (73 observed 2026-06-09). A lower bound is cohort-invariant: the
# count only grows; a drop below it means the server is reading the wrong file.
_MIN_CYCLE_ROWS = 19


def _get(path: str) -> httpx.Response:
    return httpx.get(f"{BASE_URL}{path}", timeout=PROBE_TIMEOUT_S)


def test_health_ok_with_version():
    resp = _get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("ok") is True
    # A version string makes stale-binary skew diagnosable from the payload.
    assert isinstance(body.get("version"), str) and body["version"]


def test_cycles_live_rows_carry_frontend_keys():
    resp = _get("/api/coordinator/cycles")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, dict)
    cycles = body.get("cycles")
    assert isinstance(cycles, list)
    assert len(cycles) >= _MIN_CYCLE_ROWS, (
        f"live /cycles returned {len(cycles)} rows — below the {_MIN_CYCLE_ROWS} "
        "floor; the served process is likely reading the wrong file or stale code"
    )
    for i, row in enumerate(cycles):
        assert isinstance(row, dict), f"cycles[{i}] is not an object"
        missing = [k for k in _REQUIRED_CYCLE_KEYS if k not in row]
        assert not missing, f"cycles[{i}] missing CoordinatorCycle keys: {missing}"


def test_active_is_200_or_204():
    resp = _get("/api/coordinator/active")
    assert resp.status_code in (200, 204), (
        f"/active returned {resp.status_code} — a 404 means the served process "
        "is pre-merge / stale code"
    )
    if resp.status_code == 200:
        # A live run must be a renderable object with the join-key `kind`.
        body = resp.json()
        assert isinstance(body, dict)
        assert "kind" in body


@pytest.mark.parametrize(
    ("path", "wrapper_key"),
    [
        ("/api/coordinator/findings", "findings"),
        ("/api/coordinator/bubbles", "bubbles"),
        ("/api/coordinator/health_signals", "health_signals"),
    ],
)
def test_wrapper_endpoints_return_keyed_list(path, wrapper_key):
    resp = _get(path)
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, dict), f"{path} did not return the wrapper object"
    assert wrapper_key in body, f"{path} missing its '{wrapper_key}' wrapper key"
    # Row counts are cohort-variant (files are append-only and may be absent →
    # empty list); the list-valued wrapper is the contract the panels render.
    assert isinstance(body[wrapper_key], list)
