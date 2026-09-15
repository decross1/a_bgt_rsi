"""The UI route is a read-only adapter over the registered pure producer."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.research_ops_status import register


def test_route_passes_exact_roots_and_returns_projection(tmp_path: Path):
    app = FastAPI()
    ingestion = tmp_path / "ingestion"
    calls = []
    result = {"schema": "research-ops-status/v1", "observed_at": "2026-09-15T16:00:00Z",
              "campaign_queue": {"status": "unknown"}}

    def producer(*, repo_root, ingestion_root):
        calls.append((repo_root, ingestion_root))
        return result

    register(app, repo_root=tmp_path, ingestion_root=ingestion, projector=producer)
    response = TestClient(app).get("/api/research_ops_status")
    assert response.status_code == 200
    assert response.json() == result
    assert calls == [(tmp_path, ingestion)]
