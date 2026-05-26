"""HTTP endpoint tests via FastAPI's TestClient."""
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
    body = _client(tmp_path).get("/api/health").json()
    assert body["ok"] is True
    assert body["telemetry_last_seen"] == "2026-05-18T10:00:00.000+00:00"


def test_state_passthrough(tmp_path):
    body = _client(tmp_path).get("/api/state").json()
    assert body["current_day"] == "day_1"


def test_baseline_endpoint(tmp_path):
    # No mtp.csv created — decode row falls back to the pre-MTP day-1 bench.
    body = _client(tmp_path).get("/api/baseline").json()
    rows = {r["key"]: r for r in body["rows"]}
    assert rows["decode_tok_per_s"]["source"] == "measured"
    assert "32.0 tok/s" in rows["decode_tok_per_s"]["value"]
    assert "MTP-engaged" not in rows["decode_tok_per_s"]["value"]
    assert rows["stack"]["source"] == "documented"


def test_baseline_endpoint_uses_mtp_csv(tmp_path):
    # bench/mtp.csv present — the MTP-enabled sweep drives the decode row.
    (tmp_path / "mtp.csv").write_text(
        "prompt_idx,prompt_tokens,completion_tokens,ttft_s,"
        "decode_tok_per_s,e2e_tok_per_s\n"
        "0,23,256,0.13,74.51,72.0\n1,24,256,0.12,89.81,86.4\n",
        encoding="utf-8")
    body = _client(tmp_path).get("/api/baseline").json()
    row = {r["key"]: r for r in body["rows"]}["decode_tok_per_s"]
    assert row["source"] == "measured"
    assert "MTP-engaged" in row["value"]
    assert "mtp.csv" in row["value"]
    assert "pre-MTP day-1" in row["value"]


def test_telemetry_recent(tmp_path):
    body = _client(tmp_path).get("/api/telemetry/recent?limit=10").json()
    assert len(body["samples"]) == 1
    assert body["samples"][0]["timestamp"] == "2026-05-18T10:00:00.000+00:00"
