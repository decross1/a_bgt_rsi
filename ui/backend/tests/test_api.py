"""HTTP endpoint tests via FastAPI's TestClient.

(The state-passthrough and baseline cases died with those endpoints in UI
simplification S3; the state/bench fixture wiring stays — create_app still
accepts the paths.)"""
import json

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.tests.fixtures.gen import write_fixtures


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
    state.write_text(json.dumps({
        "plan_id": "test", "current_day": "day_1",
        "metric_log": {"day1_tokens_per_sec": 32.03},
    }))
    bench = tmp_path / "day1.csv"
    bench.write_text("prompt_idx,completion_tokens,elapsed_s,decode_tok_per_s\n"
                     "0,256,8.0,32.0\n", encoding="utf-8")
    # mtp.csv left to individual tests to create so it points inside tmp_path.
    mtp = tmp_path / "mtp.csv"
    return TestClient(create_app(
        logs_dir=logs, telemetry_file=telemetry, state_file=state,
        bench_csv=bench, mtp_csv=mtp))


def test_health(tmp_path):
    # Forward-only tailer semantics (2026-08-15 fix): the first /api/health
    # ATTACHES at the telemetry file's EOF — pre-existing history is never
    # re-parsed (the 6.5GB hang), so last_seen starts None and picks up the
    # first sample appended AFTER the attach.
    client = _client(tmp_path)
    body = client.get("/api/health").json()
    assert body["ok"] is True
    assert body["telemetry_last_seen"] is None

    telemetry = tmp_path / "telemetry.jsonl"
    with open(telemetry, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "timestamp": "2026-05-18T10:00:05.000+00:00",
            "gpu": None, "host": None, "vllm": None,
            "processes": [], "read_errors": None,
        }) + "\n")
    body = client.get("/api/health").json()
    assert body["telemetry_last_seen"] == "2026-05-18T10:00:05.000+00:00"


def test_telemetry_recent(tmp_path):
    body = _client(tmp_path).get("/api/telemetry/recent?limit=10").json()
    assert len(body["samples"]) == 1
    assert body["samples"][0]["timestamp"] == "2026-05-18T10:00:00.000+00:00"
