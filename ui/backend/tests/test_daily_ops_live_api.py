"""HTTP admission tests for the separate, read-only daily-ops v3 route."""
import pytest
from fastapi import FastAPI, HTTPException, Response
from fastapi.testclient import TestClient

from backend.daily_ops_live_api import register


def _valid_summary():
    return {
        "schema_version": "daily-ops-summary/v3",
        "generated_at": "2026-09-25T00:00:00Z",
        "current_plan_revision": None,
        "daily_plan": None,
        "research_focus": {"status": "none", "observed_at": "2026-09-25T00:00:00Z"},
        "work_items": [], "waiting_on_you": [], "question_updates": [],
        "accomplishments": [], "improvements": [], "warnings": [],
        "sources": {"plan": None, "mailbox": None, "focus": None, "git": None},
        "agents": {
            name: {
                "label": name, "role": "read-only", "status": "idle", "detail": "d",
                "observed_at": "2026-09-25T00:00:00Z", "source": "test",
                "activity": None, "activity_at": None, "since": None,
            }
            for name in ("oracle", "pi_client", "nara", "meta_oracle")
        },
    }


def test_v3_summary_is_live_validated_and_private(tmp_path):
    app = FastAPI()
    register(app, repo_root=tmp_path, summary=_valid_summary)
    response = TestClient(app).get("/api/daily-ops/v3/summary")
    assert response.status_code == 200
    assert response.json()["schema_version"] == "daily-ops-summary/v3"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["vary"] == "Authorization, Origin"
    assert TestClient(app).post("/api/daily-ops/v3/summary", json={}).status_code == 405


def test_v3_summary_fails_closed_without_reading_a_legacy_cache(tmp_path):
    app = FastAPI()
    register(app, repo_root=tmp_path, summary=lambda: {"schema_version": "daily-ops-summary/v2"})
    response = TestClient(app).get("/api/daily-ops/v3/summary")
    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"


def test_v3_summary_fails_closed_for_an_actual_broken_mailbox_source(tmp_path):
    mailbox = tmp_path / "run_state" / "oracle_nara_mailbox.jsonl"
    mailbox.parent.mkdir(parents=True)
    # This is deliberately neither a valid row nor a valid chain: the route
    # must return 503 rather than convert it into a healthy empty projection.
    mailbox.write_text('{"schema":"oracle-nara-mailbox/v1","seq":1}\n')
    app = FastAPI()
    router = register(app, repo_root=tmp_path)
    endpoint = next(route.endpoint for route in router.routes
                    if route.path == "/api/daily-ops/v3/summary")
    # The installed TestClient/ASGI transport is known to hang in this lab.
    # The route's admission decision itself is deterministic and transport-free.
    with pytest.raises(HTTPException) as error:
        endpoint(Response())
    assert error.value.status_code == 503
    assert error.value.headers["Cache-Control"] == "no-store"


def test_v3_route_does_not_shadow_legacy_daily_ops_paths(tmp_path):
    app = FastAPI()
    app.get("/api/daily-ops/summary")(lambda: {"schema_version": "daily-ops-summary/v2"})
    register(app, repo_root=tmp_path, summary=_valid_summary)
    client = TestClient(app)
    assert client.get("/api/daily-ops/summary").json()["schema_version"] == "daily-ops-summary/v2"
    assert client.get("/api/daily-ops/v3/summary").json()["schema_version"] == "daily-ops-summary/v3"
