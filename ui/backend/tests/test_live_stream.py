"""WebSocket /api/live streams newly-appended lines, forward-only."""
import json
import time

from fastapi.testclient import TestClient

from backend.app import create_app


def _app(tmp_path, telemetry):
    return create_app(logs_dir=tmp_path, telemetry_file=telemetry,
                       state_file=tmp_path / "state.json")


def test_emits_new_lines_in_order(tmp_path):
    telemetry = tmp_path / "telemetry.jsonl"
    telemetry.write_text(json.dumps({"timestamp": "pre-existing"}) + "\n")
    client = TestClient(_app(tmp_path, telemetry))
    with client.websocket_connect("/api/live") as ws:
        time.sleep(0.6)                       # let the server seek past existing content
        with open(telemetry, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"timestamp": "new-1"}) + "\n")
            fh.write(json.dumps({"timestamp": "new-2"}) + "\n")
        first = ws.receive_json()
        second = ws.receive_json()
    assert first == {"source": "telemetry", "line": {"timestamp": "new-1"}}
    assert second == {"source": "telemetry", "line": {"timestamp": "new-2"}}


def test_forward_only_skips_preexisting(tmp_path):
    telemetry = tmp_path / "telemetry.jsonl"
    telemetry.write_text(json.dumps({"timestamp": "old"}) + "\n")
    client = TestClient(_app(tmp_path, telemetry))
    with client.websocket_connect("/api/live") as ws:
        time.sleep(0.6)
        with open(telemetry, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"timestamp": "fresh"}) + "\n")
        message = ws.receive_json()
    assert message["source"] == "telemetry"
    assert message["line"]["timestamp"] == "fresh"   # never replays "old"
