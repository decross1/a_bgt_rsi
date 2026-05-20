"""Day-4 readers + chain-by-request_id walker against synthesized fixtures.

Day 3.5 (events.jsonl) and day 4 (day4_e2e.jsonl, day4_robust.jsonl) have
not landed in Track A yet, so these tests run against the synthesized
fixtures from backend.tests.fixtures.gen.write_day4_fixtures.
"""
import json

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.chain import LogStore, build_chain_by_request_id
from backend.day4 import read_events, read_robustness
from backend.tests.fixtures.gen import (DAY4_E2E_CHAINS, day4_robust_expected,
                                        write_day4_fixtures, write_fixtures)


def _client(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    write_day4_fixtures(logs)
    telemetry = tmp_path / "telemetry.jsonl"
    telemetry.write_text("")
    state = tmp_path / "state.json"
    state.write_text("{}")
    bench = tmp_path / "day1.csv"
    bench.write_text("decode_tok_per_s\n")
    mtp = tmp_path / "mtp.csv"
    return TestClient(create_app(logs_dir=logs, telemetry_file=telemetry,
                                 state_file=state, bench_csv=bench, mtp_csv=mtp))


def test_chain_by_request_id_walks_two_link_chain(tmp_path):
    manifest = write_day4_fixtures(tmp_path)
    store = LogStore(tmp_path)
    rid = manifest["chains"]["day4_chain_search"]
    result = build_chain_by_request_id(store, rid)
    assert result["found"] is True
    # 1 wrapper root + 2 tool children = 3 nodes; latencies 540+88+72=700.
    assert result["node_count"] == 3
    assert result["total_latency_ms"] == 700
    assert result["root"]["request_id"] == rid
    assert [c["caller_tag"] for c in result["root"]["children"]] == ["tool", "tool"]


def test_chain_by_request_id_unknown(tmp_path):
    write_day4_fixtures(tmp_path)
    result = build_chain_by_request_id(LogStore(tmp_path), "no-such-id")
    assert result["found"] is False


def test_malformed_tool_calls_flagged_as_parse_error(tmp_path):
    # day4_chain_malformed deliberately writes tool_calls as a string. The
    # walker must surface parse_error rather than silently format-fixing.
    manifest = write_day4_fixtures(tmp_path)
    rid = manifest["chains"]["day4_chain_malformed"]
    result = build_chain_by_request_id(LogStore(tmp_path), rid)
    assert result["found"] is True
    # parse_error on the wrapper itself: 1 (wrapper) + 1 (child marked
    # parse_error in the fixture) = 2 malformed nodes.
    assert result["malformed_tool_calls"] == 2
    assert result["root"]["parse_error"] is True
    assert result["root"]["tool_calls_malformed"] is True


def test_retrieval_context_passed_through(tmp_path):
    # Simulate a day-3.5 record carrying retrieval_context. The walker passes
    # the list through as a first-class field so the inspector can render it.
    (tmp_path / "day4_e2e.jsonl").write_text(json.dumps({
        "request_id": "wrap-1", "parent_request_id": None,
        "caller_tag": "wrapper", "timestamp": "t", "latency_ms": 100,
        "retrieval_context": [
            {"doc_id": "doc-A", "content_hash": "abc", "chunk_offset": 0, "chunk_length": 512},
            {"doc_id": "doc-B", "content_hash": "def", "chunk_offset": 512, "chunk_length": 480},
        ],
    }) + "\n")
    result = build_chain_by_request_id(LogStore(tmp_path), "wrap-1")
    assert result["found"] is True
    assert result["root"]["retrieval_context"] is not None
    assert [c["doc_id"] for c in result["root"]["retrieval_context"]] == ["doc-A", "doc-B"]


def test_retrieval_context_wrong_shape_ignored(tmp_path):
    # If the field is the wrong shape (e.g. a string), drop it rather than
    # leak a typed-list contract to the UI.
    (tmp_path / "day4_e2e.jsonl").write_text(json.dumps({
        "request_id": "wrap-2", "parent_request_id": None,
        "caller_tag": "wrapper", "timestamp": "t", "latency_ms": 50,
        "retrieval_context": "not a list",
    }) + "\n")
    result = build_chain_by_request_id(LogStore(tmp_path), "wrap-2")
    assert result["root"]["retrieval_context"] is None


def test_read_events_returns_events_when_present(tmp_path):
    write_day4_fixtures(tmp_path)
    body = read_events(tmp_path / "events.jsonl")
    assert body["available"] is True
    types = sorted(e["event_type"] for e in body["events"])
    assert types == ["calibration_entry", "human_intervention"]


def test_read_events_absent_file(tmp_path):
    body = read_events(tmp_path / "events.jsonl")
    assert body["available"] is False
    assert body["events"] == []


def test_read_events_drops_records_without_event_type(tmp_path):
    (tmp_path / "events.jsonl").write_text(
        json.dumps({"event_type": "human_intervention", "actor": "ops"}) + "\n"
        + json.dumps({"actor": "no_type"}) + "\n")
    body = read_events(tmp_path / "events.jsonl")
    assert len(body["events"]) == 1


def test_read_robustness_summary(tmp_path):
    write_day4_fixtures(tmp_path)
    summary = read_robustness(tmp_path / "day4_robust.jsonl")
    expected = day4_robust_expected()
    assert summary["available"] is True
    assert summary["trial_count"] == expected["trials"]
    assert summary["invocations"] == expected["invocations"]
    assert summary["invocation_rate"] == expected["invocation_rate"]
    assert summary["median_latency_ms"] == expected["median_latency_ms"]
    # Outcomes tally over the fixture: 7 ok, 2 missed, 1 timeout.
    assert summary["outcomes"] == {"ok": 7, "missed": 2, "timeout": 1}


def test_read_robustness_absent_file(tmp_path):
    summary = read_robustness(tmp_path / "day4_robust.jsonl")
    assert summary["available"] is False
    assert summary["invocations"] == 0
    assert summary["median_latency_ms"] is None


def test_api_day4_chains_endpoint(tmp_path):
    body = _client(tmp_path).get("/api/day4/chains").json()
    assert body["available"] is True
    names = {c["caller_tag"] for c in body["chains"]}
    # all three day-4 fixture chains are rooted at a wrapper.
    assert names == {"wrapper"}
    # one of them carries the malformed flag.
    assert sum(c["malformed_tool_calls"] for c in body["chains"]) >= 1


def test_api_chain_by_request_endpoint(tmp_path):
    client = _client(tmp_path)
    listing = client.get("/api/day4/chains").json()
    rid = next(c["request_id"] for c in listing["chains"]
               if c["malformed_tool_calls"] == 0)
    walk = client.get(f"/api/chain_by_request/{rid}").json()
    assert walk["found"] is True
    assert walk["root"]["request_id"] == rid


def test_api_chain_by_request_404(tmp_path):
    assert _client(tmp_path).get("/api/chain_by_request/nope").status_code == 404


def test_api_events_endpoint(tmp_path):
    body = _client(tmp_path).get("/api/events").json()
    assert body["available"] is True
    assert len(body["events"]) == 2


def test_api_robustness_endpoint(tmp_path):
    body = _client(tmp_path).get("/api/robustness").json()
    assert body["available"] is True
    assert body["invocation_rate"] == 0.8
    assert body["median_latency_ms"] == day4_robust_expected()["median_latency_ms"]
