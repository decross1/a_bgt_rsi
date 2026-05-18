"""HTTP endpoint tests via FastAPI's TestClient."""
import json

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.tests.fixtures.gen import expected_manifest, write_fixtures


def _client(tmp_path):
    logs = tmp_path / "logs"
    write_fixtures(logs)
    telemetry = tmp_path / "telemetry.jsonl"
    telemetry.write_text(json.dumps({
        "timestamp": "2026-05-18T10:00:00.000+00:00",
        "gpu": None, "host": None, "vllm": None,
        "processes": [], "read_errors": None,
    }) + "\n")
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"plan_id": "test", "current_day": "day_1"}))
    return TestClient(create_app(logs_dir=logs, telemetry_file=telemetry,
                                 state_file=state))


def test_health(tmp_path):
    body = _client(tmp_path).get("/api/health").json()
    assert body["ok"] is True
    assert body["telemetry_last_seen"] == "2026-05-18T10:00:00.000+00:00"


def test_recent_tasks(tmp_path):
    body = _client(tmp_path).get("/api/recent_tasks").json()
    ids = [t["task_id"] for t in body["tasks"]]
    assert "day6_task_01" in ids
    assert ids[0] == "exp001_round_07"               # latest first


def test_chain_found(tmp_path):
    expected = expected_manifest()["day6_task_01"]
    body = _client(tmp_path).get("/api/chain/day6_task_01").json()
    assert body["found"] is True
    assert body["node_count"] == expected["node_count"]
    assert body["total_latency_ms"] == expected["total_latency_ms"]


def test_chain_not_found(tmp_path):
    assert _client(tmp_path).get("/api/chain/missing").status_code == 404


def test_state_passthrough(tmp_path):
    body = _client(tmp_path).get("/api/state").json()
    assert body["current_day"] == "day_1"


def test_telemetry_recent(tmp_path):
    body = _client(tmp_path).get("/api/telemetry/recent?limit=10").json()
    assert len(body["samples"]) == 1
    assert body["samples"][0]["timestamp"] == "2026-05-18T10:00:00.000+00:00"
