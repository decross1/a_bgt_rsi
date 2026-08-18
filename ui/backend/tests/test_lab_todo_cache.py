"""GET /api/lab_todo stale-while-revalidate cache (perf, 2026-08-18).

On the live .venv-chroma backend the payload build runs assess_state — BGE-M3
embedder + Chroma query INSIDE the request, measured >120 s under load — and
the UI's old bare 30 s poll stacked concurrent builds until the whole backend
threadpool starved (that pileup was the owner-reported "page keeps
refreshing"). These tests pin the replacement semantics with an injected
builder + clock:

- cold path builds synchronously once; ``cache_age_s`` is 0.0;
- within the fresh window a repeat GET serves the cache (builder NOT
  re-invoked) and names its age honestly;
- past the fresh window the STALE payload is served immediately while ONE
  background rebuild runs (single-flight), after which the fresh payload
  serves;
- a failing rebuild keeps the last good payload serving and NAMES the failure
  in ``refresh_error`` (rule 7: the degraded path is explicit) — it never
  blanks the queue;
- a cold-path failure is still the honest 500 it always was;
- the COLD path takes the same single-flight latch (adversarial review
  2026-08-18): concurrent cold GETs run exactly ONE build — the concurrent
  arrival gets an honest 503 + ``building: true``, never a second build;
- a FAILING cold builder backs off: within ``cold_retry_s`` the named error
  is served without re-invoking the builder.
"""
from __future__ import annotations

import threading
import time

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.lab_todo import register


class _Clock:
    def __init__(self):
        self.t = 5000.0

    def __call__(self):
        return self.t


def _payload(n):
    return {
        "agent_gaps": [f"gap build {n}"],
        "human_gaps": [],
        "gaps_source": "last_cycle",
        "gaps_as_of": None,
        "owed": [],
        "agenda": [],
        "refine_candidates": [],
        "generated_at": f"2026-08-18T00:00:0{n}Z",
    }


def _client(tmp_path, builder, clock, fresh_s=90.0, cold_retry_s=15.0):
    app = FastAPI()
    register(app, repo_root=tmp_path, run_state_dir=tmp_path,
             memory_dir=tmp_path, builder=builder, clock=clock,
             fresh_s=fresh_s, cold_retry_s=cold_retry_s)
    return TestClient(app)


def test_cold_path_builds_once_and_fresh_window_serves_cache(tmp_path):
    clock = _Clock()
    builds = []

    def builder():
        builds.append(1)
        return _payload(len(builds))

    client = _client(tmp_path, builder, clock)
    first = client.get("/api/lab_todo").json()
    assert len(builds) == 1
    assert first["cache_age_s"] == 0.0
    assert first["refresh_error"] is None

    clock.t += 30.0  # inside the 90 s fresh window
    second = client.get("/api/lab_todo").json()
    assert len(builds) == 1  # served from cache — builder untouched
    assert second["agent_gaps"] == ["gap build 1"]
    assert second["generated_at"] == first["generated_at"]  # honest age…
    assert second["cache_age_s"] == 30.0  # …and it says so explicitly


def test_stale_serves_immediately_and_one_background_rebuild_runs(tmp_path):
    clock = _Clock()
    builds = []
    rebuilt = threading.Event()

    def builder():
        builds.append(1)
        if len(builds) > 1:
            rebuilt.set()
        return _payload(len(builds))

    client = _client(tmp_path, builder, clock)
    client.get("/api/lab_todo")
    clock.t += 120.0  # past the fresh window

    stale = client.get("/api/lab_todo").json()
    # Served IMMEDIATELY from cache (the request never waits on the rebuild)
    # and the staleness is named, not hidden.
    assert stale["agent_gaps"] == ["gap build 1"]
    assert stale["cache_age_s"] == 120.0

    assert rebuilt.wait(timeout=5.0), "background rebuild never ran"
    # The rebuild thread flips `building` off after storing; give it a beat.
    deadline = time.time() + 5.0
    while time.time() < deadline:
        fresh = client.get("/api/lab_todo").json()
        if fresh["agent_gaps"] == ["gap build 2"]:
            break
        time.sleep(0.02)
    assert fresh["agent_gaps"] == ["gap build 2"]
    assert len(builds) == 2  # single-flight: exactly one rebuild


def test_failed_rebuild_keeps_serving_and_names_the_error(tmp_path):
    clock = _Clock()
    builds = []
    failed = threading.Event()

    def builder():
        builds.append(1)
        if len(builds) > 1:
            failed.set()
            raise HTTPException(status_code=500,
                                detail="idea_ledger unreadable: boom")
        return _payload(1)

    client = _client(tmp_path, builder, clock)
    client.get("/api/lab_todo")
    clock.t += 120.0
    client.get("/api/lab_todo")  # triggers the background rebuild
    assert failed.wait(timeout=5.0)

    deadline = time.time() + 5.0
    body = None
    while time.time() < deadline:
        body = client.get("/api/lab_todo").json()
        if body["refresh_error"]:
            break
        time.sleep(0.02)
    # The last good queue still serves — never blanked — and the failure is
    # NAMED on the payload (rule 7), not silent.
    assert body["agent_gaps"] == ["gap build 1"]
    assert "idea_ledger unreadable: boom" in body["refresh_error"]


def test_cold_path_failure_is_still_an_honest_500(tmp_path):
    # (The default no-injection wiring — real builder, real clock — is
    # exercised end-to-end by the existing test_lab_todo.py suite, whose
    # every request now flows through this cache's cold path.)
    def builder():
        raise HTTPException(status_code=500,
                            detail="idea_ledger unreadable: cold boom")

    client = _client(tmp_path, builder, _Clock())
    resp = client.get("/api/lab_todo")
    assert resp.status_code == 500
    assert "cold boom" in resp.json()["detail"]


def test_concurrent_cold_requests_run_exactly_one_build(tmp_path):
    """The cold-path stampede pin (adversarial review 2026-08-18): with
    nothing cached, N concurrent GETs take ONE ``building`` latch — one
    synchronous build; the concurrent arrival is answered immediately with
    an honest 503 + building flag, never a stacked second build."""
    clock = _Clock()
    builds = []
    entered = threading.Event()
    release = threading.Event()

    def builder():
        builds.append(1)
        entered.set()
        assert release.wait(timeout=5.0), "builder never released"
        return _payload(len(builds))

    client = _client(tmp_path, builder, clock)

    results: list = []

    def first():
        results.append(client.get("/api/lab_todo"))

    t = threading.Thread(target=first, daemon=True)
    t.start()
    assert entered.wait(timeout=5.0), "first cold build never started"

    # A concurrent cold request while the first is mid-build: answered NOW,
    # honestly, without invoking the builder a second time.
    waiter = client.get("/api/lab_todo")
    assert waiter.status_code == 503
    body = waiter.json()
    assert body["building"] is True
    assert "building" in body["detail"]
    assert len(builds) == 1  # the latch held — no second concurrent build

    release.set()
    t.join(timeout=5.0)
    assert not t.is_alive()
    assert results[0].status_code == 200
    assert results[0].json()["agent_gaps"] == ["gap build 1"]

    # The eventual result now serves everyone from cache — still one build.
    after = client.get("/api/lab_todo").json()
    assert after["agent_gaps"] == ["gap build 1"]
    assert len(builds) == 1


def test_failing_cold_build_backs_off(tmp_path):
    """A broken builder must not be hammered per poll: within cold_retry_s
    the recorded error serves WITHOUT re-invoking the build; past the
    window exactly one retry is allowed."""
    clock = _Clock()
    builds = []

    def builder():
        builds.append(1)
        raise HTTPException(status_code=500,
                            detail="idea_ledger unreadable: cold boom")

    client = _client(tmp_path, builder, clock, cold_retry_s=15.0)
    first = client.get("/api/lab_todo")
    assert first.status_code == 500
    assert len(builds) == 1

    # Inside the backoff window: same named error, builder NOT re-invoked.
    clock.t += 5.0
    again = client.get("/api/lab_todo")
    assert again.status_code == 500
    assert "cold boom" in again.json()["detail"]
    assert "backing off" in again.json()["detail"]
    assert len(builds) == 1

    # Past the window: one retry runs (and fails honestly again).
    clock.t += 20.0
    retry = client.get("/api/lab_todo")
    assert retry.status_code == 500
    assert len(builds) == 2
