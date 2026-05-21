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


def test_malformed_tool_calls_flagged_specifically(tmp_path):
    # day4_chain_malformed deliberately writes tool_calls as a string. The
    # walker surfaces tool_calls_malformed on the wrapper and counts ONLY
    # that — not the child's generic parse_error — toward the banner. The
    # two failure modes are kept distinct so the banner does not conflate
    # an unrelated wrapper parse error with corrupted tool_calls.
    manifest = write_day4_fixtures(tmp_path)
    rid = manifest["chains"]["day4_chain_malformed"]
    result = build_chain_by_request_id(LogStore(tmp_path), rid)
    assert result["found"] is True
    assert result["root"]["tool_calls_malformed"] is True
    assert result["root"]["parse_error"] is True            # explicit on record
    # Only the wrapper has tool_calls_malformed; the child has parse_error
    # but not tool_calls_malformed, so the count is 1.
    assert result["malformed_tool_calls"] == 1


def test_parse_error_distinct_from_tool_calls_malformed(tmp_path):
    # day6_task_02 (existing fixture) has a wrapper with parse_error=True but
    # NO tool_calls. After the decoupling, that chain must not count toward
    # malformed_tool_calls — the banner must not fire on this chain.
    write_fixtures(tmp_path)
    from backend.chain import build_chain
    result = build_chain(LogStore(tmp_path), "day6_task_02")
    assert result["found"] is True
    assert result["malformed_tool_calls"] == 0
    # The per-node parse_error badge is still there for the affected node;
    # just no chain-level banner.
    flagged = [n for n in result["root"]["children"][0]["children"]
               if n["parse_error"]]
    assert len(flagged) == 1


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


def test_completion_tool_call_synthesized_as_tool_node(tmp_path):
    # Shape 3 (ui_plan.md section 9): Track A's real day-4 logs put the tool
    # call in `completion` as an OpenAI-style JSON string, not in a
    # `tool_calls` array. The walker synthesizes a kind="tool" child from it.
    completion = json.dumps([{
        "id": "chatcmpl-tool-1", "type": "function",
        "function": {"name": "get_payoff_matrix",
                     "arguments": '{"game_name": "prisoners_dilemma"}'},
    }])
    (tmp_path / "day4_e2e.jsonl").write_text(json.dumps({
        "request_id": "root-1", "parent_request_id": None,
        "caller_tag": "test_tool_call_e2e", "timestamp": "t",
        "latency_ms": 640, "completion": completion,
    }) + "\n")
    result = build_chain_by_request_id(LogStore(tmp_path), "root-1")
    assert result["found"] is True
    assert result["node_count"] == 2               # root call + 1 synthesized tool
    tools = [c for c in result["root"]["children"] if c["kind"] == "tool"]
    assert len(tools) == 1
    assert tools[0]["caller_tag"] == "get_payoff_matrix"
    assert tools[0]["embedded"] is True
    assert tools[0]["request_id"] is None
    # The completion tool call has no latency of its own — the wrapper
    # latency already covers it; the total must not double-count.
    assert result["total_latency_ms"] == 640


def test_completion_plain_text_is_not_a_tool_node(tmp_path):
    # An ordinary text answer in `completion` must not be mistaken for a tool
    # call — no synthesized child, no malformed flag.
    (tmp_path / "day4_e2e.jsonl").write_text(json.dumps({
        "request_id": "root-2", "parent_request_id": None,
        "caller_tag": "wrapper", "timestamp": "t", "latency_ms": 100,
        "completion": "The payoff matrix is (3,3), (0,5), (5,0), (1,1).",
    }) + "\n")
    result = build_chain_by_request_id(LogStore(tmp_path), "root-2")
    assert result["node_count"] == 1
    assert result["root"]["tool_calls_malformed"] is False


def test_completion_malformed_tool_call_flagged(tmp_path):
    # A completion that opens like a tool-call array but does not parse is
    # flagged tool_calls_malformed — surfaced for the inspector banner,
    # never silently repaired.
    (tmp_path / "day4_e2e.jsonl").write_text(json.dumps({
        "request_id": "root-3", "parent_request_id": None,
        "caller_tag": "wrapper", "timestamp": "t", "latency_ms": 120,
        "completion": '[{"id": "x", "type": "function", '
                      '"function": {"name": "get_payoff_matrix"',
    }) + "\n")
    result = build_chain_by_request_id(LogStore(tmp_path), "root-3")
    assert result["root"]["tool_calls_malformed"] is True
    assert result["malformed_tool_calls"] == 1
    # Malformed → no tool child synthesized; the raw record is shown as stored.
    assert result["node_count"] == 1


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
    # day4_robust.jsonl is a chained call log: each run is a wrapper-root call
    # whose `completion` carries (or misses) a tool call. read_robustness
    # derives the invocation rate from the roots, not from an `invoked` flag.
    write_day4_fixtures(tmp_path)
    summary = read_robustness(tmp_path / "day4_robust.jsonl")
    expected = day4_robust_expected()
    assert summary["available"] is True
    assert summary["trial_count"] == expected["trials"]
    assert summary["invocations"] == expected["invocations"]
    assert summary["invocation_rate"] == expected["invocation_rate"]
    assert summary["median_latency_ms"] == expected["median_latency_ms"]
    # Fixture runs: 3 ok (tool invoked), 1 missed, 1 malformed completion.
    assert summary["outcomes"] == {"ok": 3, "missed": 1, "malformed": 1}


def test_read_robustness_absent_file(tmp_path):
    summary = read_robustness(tmp_path / "day4_robust.jsonl")
    assert summary["available"] is False
    assert summary["invocations"] == 0
    assert summary["median_latency_ms"] is None


def test_read_robustness_excludes_child_calls(tmp_path):
    # The chained log carries child calls (parent_request_id set) alongside
    # run roots. Children are the tool-result follow-up, not runs — only
    # wrapper-root calls count as trials, so trial_count < line count.
    write_day4_fixtures(tmp_path)
    lines = [ln for ln in
             (tmp_path / "day4_robust.jsonl").read_text().splitlines() if ln]
    summary = read_robustness(tmp_path / "day4_robust.jsonl")
    assert len(lines) > summary["trial_count"]      # file has child lines too
    assert summary["trial_count"] == 5
    assert all(t["caller_tag"].startswith("test_tool_call_robustness/run")
               for t in summary["trials"])


def test_read_robustness_flags_malformed_completion(tmp_path):
    # A run whose root completion opens like a tool-call array but does not
    # parse is "malformed" — surfaced, never silently repaired or counted
    # as an invocation.
    write_day4_fixtures(tmp_path)
    summary = read_robustness(tmp_path / "day4_robust.jsonl")
    malformed = [t for t in summary["trials"] if t["outcome"] == "malformed"]
    assert len(malformed) == 1
    assert malformed[0]["invoked"] is False
    assert malformed[0]["latency_ms"] is not None   # the call still happened


def test_api_day4_chains_endpoint(tmp_path):
    body = _client(tmp_path).get("/api/day4/chains").json()
    assert body["available"] is True
    names = {c["caller_tag"] for c in body["chains"]}
    # all three day-4 fixture chains are rooted at a wrapper.
    assert names == {"wrapper"}
    # one of them carries the malformed flag.
    assert sum(c["malformed_tool_calls"] for c in body["chains"]) >= 1


def test_api_day4_chains_excludes_day2_standalone_calls(tmp_path):
    # Regression: day-2 records all carry parent_request_id=null per the schema
    # (chains start day 4). A cross-file enumeration would surface those as
    # "day-4 chains". The endpoint is scoped to day4_e2e.jsonl specifically.
    logs = tmp_path / "logs"
    logs.mkdir()
    write_day4_fixtures(logs)
    # Write a few synthetic day-2 records — same standalone-call shape as the
    # real logs/day2.jsonl: parent_request_id=null, no tool_calls children.
    day2 = "\n".join(json.dumps({
        "request_id": f"day2-{i}", "parent_request_id": None,
        "caller_tag": "test_50_calls/sweep", "timestamp": f"2026-05-19T03:57:0{i}Z",
        "latency_ms": 100,
    }) for i in range(3))
    (logs / "day2.jsonl").write_text(day2 + "\n")
    telemetry = tmp_path / "telemetry.jsonl"
    telemetry.write_text("")
    state = tmp_path / "state.json"
    state.write_text("{}")
    bench = tmp_path / "day1.csv"
    bench.write_text("decode_tok_per_s\n")
    mtp = tmp_path / "mtp.csv"
    client = TestClient(create_app(logs_dir=logs, telemetry_file=telemetry,
                                   state_file=state, bench_csv=bench, mtp_csv=mtp))
    body = client.get("/api/day4/chains").json()
    listed = {c["request_id"] for c in body["chains"]}
    # day-2 records must not leak in; only the three day-4 wrapper roots.
    assert not any(rid.startswith("day2-") for rid in listed)
    assert len(listed) == len(DAY4_E2E_CHAINS)


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
    assert body["invocation_rate"] == 0.6          # 3 of 5 runs invoked
    assert body["median_latency_ms"] == day4_robust_expected()["median_latency_ms"]
