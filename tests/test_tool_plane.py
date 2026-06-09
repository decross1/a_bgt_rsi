"""Hermetic tests for the host tool plane (orchestrator/tool_plane.py).

Green under MOCK_LLM AND without it: every test injects a stub `assess` so the
real Chroma-loading `coordinator.assess_state` is NEVER called (its
topic-suggestion seam loads BGE-M3, which MOCK_LLM does NOT stub). The tool
plane itself is a pure pass-through, so the tests assert the HTTP contract — the
manifest, the call envelope, and that the endpoints relay the snapshot verbatim.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from orchestrator import tool_plane


# A representative assess_state snapshot (shape per coordinator.assess_state's
# docstring). The stub records call count so we can prove /health does NOT
# trigger an assess (no Chroma load on a liveness ping).
_FAKE_STATE = {
    "in_flight": {"active": False, "run": None},
    "recent_findings": [
        {"iteration_id": "iter-x-001", "hypothesis": "h", "novelty": "novel",
         "critic": "survives", "experiment_outcome": None,
         "gate_status": "pending", "human_verdict": None},
    ],
    "open_threads": ["iter-x-001"],
    "gaps": ["1 recent iteration(s) await a human gate verdict"],
    "surfaced_pending": [],
    "experiments": {},
    "topic_suggestions": [{"topic": "a topic", "source": "arxiv_pick"}],
}


def _client(monkeypatch):
    calls = {"n": 0}

    def _stub_assess():
        calls["n"] += 1
        return _FAKE_STATE

    app = tool_plane.create_app(assess=_stub_assess)
    return TestClient(app), calls


def test_health_does_not_call_assess(monkeypatch):
    client, calls = _client(monkeypatch)
    body = client.get("/health").json()
    assert body["ok"] is True
    # Both tools are advertised (read + the run_loop_iteration compute tool).
    assert body["tools"] == [tool_plane.TOOL_NAME, tool_plane.RUN_TOOL_NAME]
    # A liveness ping must not load Chroma via assess_state.
    assert calls["n"] == 0


def test_tools_manifest_lists_the_read_tool(monkeypatch):
    client, _ = _client(monkeypatch)
    body = client.get("/tools").json()
    tools = body["tools"]
    # Two tools now: the read snapshot + the run_loop_iteration compute tool.
    assert len(tools) == 2
    by_name = {t["name"] for t in tools}
    assert by_name == {"get_apparatus_state", "run_loop_iteration"}
    read_tool = next(t for t in tools if t["name"] == "get_apparatus_state")
    assert isinstance(read_tool["description"], str) and read_tool["description"]
    # No-arg tool: an object schema with empty properties.
    assert read_tool["input_schema"]["type"] == "object"
    assert read_tool["input_schema"]["properties"] == {}


def test_call_returns_state_in_envelope(monkeypatch):
    client, calls = _client(monkeypatch)
    resp = client.post("/tools/get_apparatus_state")
    assert resp.status_code == 200
    body = resp.json()
    assert body["tool"] == "get_apparatus_state"
    assert body["ok"] is True
    # The snapshot is relayed verbatim — no field dropped or renamed.
    assert body["result"] == _FAKE_STATE
    assert calls["n"] == 1


def test_call_is_a_pure_passthrough_of_arbitrary_snapshot(monkeypatch):
    # Whatever assess returns is relayed unchanged (the plane adds no logic).
    sentinel = {"in_flight": {"active": True, "run": {"run_id": "r1"}},
                "weird_extra_key": [1, 2, 3]}
    app = tool_plane.create_app(assess=lambda: sentinel)
    body = TestClient(app).post("/tools/get_apparatus_state").json()
    assert body["result"] == sentinel


def test_default_app_wires_real_assess_without_calling_it():
    # The module-level app binds the REAL coordinator.assess_state (the host
    # production wiring). We assert the wiring identity WITHOUT invoking it
    # (calling it would load Chroma). create_app's default param is the proof.
    from orchestrator.coordinator import assess_state
    assert tool_plane.create_app.__defaults__ is None  # all kw-only
    # The keyword default is the real assess_state.
    import inspect
    sig = inspect.signature(tool_plane.create_app)
    assert sig.parameters["assess"].default is assess_state


def test_manifest_matches_the_agent_bundle_tool_name():
    # Guardrail: the static OpenClaw bundle manifest must name the SAME tool the
    # plane serves, or the in-sandbox smoke calls a non-existent endpoint.
    bundle = (
        Path(__file__).resolve().parent.parent
        / "agent" / "nemoclaw_nara" / "tools.json"
    )
    manifest = json.loads(bundle.read_text())
    names = {t["name"] for t in manifest["tools"]}
    assert tool_plane.TOOL_NAME in names


# ---------------------------------------------------------------------------
# run_loop_iteration — the first compute/write tool. Every test below injects a
# stub run_iteration (a real model is NEVER loaded) and an explicit in-flight
# predicate, so the server-side boundary (topic gate + one-at-a-time) is
# exercised hermetically.
# ---------------------------------------------------------------------------

# A representative finalize_iteration_record shape (the subset the tool reads).
_FAKE_RECORD = {
    "iteration_id": "iter-2026-06-09-001",
    "seed": {"topic": "t", "source": "nemoclaw_agent"},
    "novelty": {"class": "novel", "rationale": "r", "low_confidence": False},
    "critique": {"verdict": "survives", "rationale": "r", "low_confidence": False},
    "journal_entry_path": "journal/iterations/042.md",
    "nara_summary": "s",
    "tool_calls_made": ["journal_writer"],
}


def _run_client(*, in_flight=False, record=None):
    """A TestClient with stubbed run_iteration + in-flight predicate.

    Records the (topic, source) the plane passed so the happy-path test can
    assert the server pins source='nemoclaw_agent' (the boundary identity)."""
    calls = {"n": 0, "topic": None, "source": None}

    def _stub_run(topic, *, source=None, **kwargs):
        calls["n"] += 1
        calls["topic"] = topic
        calls["source"] = source
        return record if record is not None else _FAKE_RECORD

    app = tool_plane.create_app(
        assess=lambda: {},  # never used by the run endpoint
        run_iteration=_stub_run,
        iteration_in_flight=lambda: in_flight,
    )
    return TestClient(app), calls


def test_run_tool_rejects_empty_and_whitespace_topic():
    client, calls = _run_client()
    for bad in ("", "   ", "\t\n"):
        body = client.post("/tools/run_loop_iteration", json={"topic": bad}).json()
        assert body == {"tool": "run_loop_iteration", "ok": False, "error": "topic_empty"}
    # A rejected topic must NOT have spent any host compute.
    assert calls["n"] == 0


def test_run_tool_rejects_oversized_topic():
    client, calls = _run_client()
    resp = client.post("/tools/run_loop_iteration", json={"topic": "x" * 201})
    assert resp.status_code == 200  # gated, NOT a 500
    body = resp.json()
    assert body["ok"] is False
    assert body["error"] == "topic_too_long_max_200"
    assert calls["n"] == 0
    # The boundary value (exactly 200) is accepted.
    ok = client.post("/tools/run_loop_iteration", json={"topic": "y" * 200}).json()
    assert ok["ok"] is True
    assert calls["n"] == 1


def test_run_tool_rejects_non_string_and_missing_topic():
    client, calls = _run_client()
    for bad in (123, None, ["a"], {"k": "v"}):
        body = client.post("/tools/run_loop_iteration", json={"topic": bad}).json()
        assert body["ok"] is False
        assert body["error"] == "topic_must_be_string"
    # Missing topic entirely (empty body) — also a non-string.
    body = client.post("/tools/run_loop_iteration", json={}).json()
    assert body["ok"] is False
    assert body["error"] == "topic_must_be_string"
    assert calls["n"] == 0


def test_run_tool_refuses_when_iteration_in_flight():
    client, calls = _run_client(in_flight=True)
    resp = client.post("/tools/run_loop_iteration", json={"topic": "a good topic"})
    assert resp.status_code == 200  # refusal is a 200 envelope, not a 503/500
    body = resp.json()
    assert body == {
        "tool": "run_loop_iteration", "ok": False, "error": "iteration_in_flight",
    }
    # One-at-a-time means we never even called run_iteration.
    assert calls["n"] == 0


def test_run_tool_happy_path_returns_extracted_result_envelope():
    client, calls = _run_client(in_flight=False)
    resp = client.post("/tools/run_loop_iteration", json={"topic": "  Vickrey truthfulness  "})
    assert resp.status_code == 200
    body = resp.json()
    assert body["tool"] == "run_loop_iteration"
    assert body["ok"] is True
    assert body["result"] == {
        "iteration_id": "iter-2026-06-09-001",
        "novelty_class": "novel",
        "critic_verdict": "survives",
        "low_confidence": False,
        "journal_entry_path": "journal/iterations/042.md",
    }
    # Boundary identity: the plane pins source='nemoclaw_agent' and passes the
    # stripped topic (leading/trailing whitespace removed before run).
    assert calls["n"] == 1
    assert calls["source"] == "nemoclaw_agent"
    assert calls["topic"] == "Vickrey truthfulness"


def test_run_tool_low_confidence_ors_novelty_and_critique():
    # low_confidence surfaces a degraded signal from EITHER substructure.
    rec = {
        "iteration_id": "iter-2026-06-09-002",
        "seed": {"topic": "t", "source": "nemoclaw_agent"},
        "novelty": {"class": "unclear", "rationale": "r", "low_confidence": True},
        "critique": {"verdict": "survives", "rationale": "r", "low_confidence": False},
        "journal_entry_path": "journal/iterations/043.md",
        "nara_summary": "s",
        "tool_calls_made": ["journal_writer"],
    }
    client, _ = _run_client(record=rec)
    body = client.post("/tools/run_loop_iteration", json={"topic": "t"}).json()
    assert body["result"]["low_confidence"] is True
    assert body["result"]["novelty_class"] == "unclear"


def test_run_tool_tolerates_degraded_record_missing_substructures():
    # A degraded chain still returns a VALID record without novelty/critique;
    # the extraction must read defensively (None, not a KeyError/500).
    rec = {
        "iteration_id": "iter-2026-06-09-003",
        "seed": {"topic": "t", "source": "nemoclaw_agent"},
        "journal_entry_path": "journal/iterations/044.md",
        "nara_summary": "s",
        "tool_calls_made": ["journal_writer_stub"],
    }
    client, _ = _run_client(record=rec)
    resp = client.post("/tools/run_loop_iteration", json={"topic": "t"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["result"] == {
        "iteration_id": "iter-2026-06-09-003",
        "novelty_class": None,
        "critic_verdict": None,
        "low_confidence": False,
        "journal_entry_path": "journal/iterations/044.md",
    }


def test_tools_manifest_lists_run_loop_iteration_with_exact_schema():
    client, _ = _run_client()
    tools = client.get("/tools").json()["tools"]
    by_name = {t["name"]: t for t in tools}
    assert tool_plane.RUN_TOOL_NAME in by_name
    run_tool = by_name["run_loop_iteration"]
    assert isinstance(run_tool["description"], str) and run_tool["description"]
    # EXACT input_schema the agent bundle (limb L2) mirrors — keep in lockstep.
    assert run_tool["input_schema"] == {
        "type": "object",
        "properties": {"topic": {"type": "string"}},
        "required": ["topic"],
        "additionalProperties": False,
    }


def test_health_lists_both_tools():
    client, _ = _run_client()
    body = client.get("/health").json()
    assert body["ok"] is True
    assert body["tools"] == [tool_plane.TOOL_NAME, tool_plane.RUN_TOOL_NAME]


def test_default_app_wires_real_run_iteration_without_calling_it():
    # The module-level app binds the REAL nara.run_iteration (host production
    # wiring). Assert the wiring identity WITHOUT invoking it (a real call
    # loads a model). create_app's keyword default is the proof.
    import inspect

    from orchestrator.nara import run_iteration as real_run

    sig = inspect.signature(tool_plane.create_app)
    assert sig.parameters["run_iteration"].default is real_run
    # in-flight predicate defaults to the active_run.json existence check.
    assert sig.parameters["iteration_in_flight"].default is (
        tool_plane._default_iteration_in_flight
    )


# ── MCP streamable-HTTP endpoint (2026-06-09, T2 path-a wiring) ─────────────
# OpenClaw 2026.5.18 consumes mcp.servers via the official MCP SDK client
# (JSON-RPC over POST /mcp); these pin the JSON-RPC envelope around the SAME
# gated closures the REST endpoints use.


def _mcp_client(record=None, in_flight=False):
    calls = {"n": 0, "topic": None, "source": None}

    def _stub_run(topic, *, source=None, **kwargs):
        calls["n"] += 1
        calls["topic"] = topic
        calls["source"] = source
        return record if record is not None else _FAKE_RECORD

    app = tool_plane.create_app(
        assess=lambda: _FAKE_STATE,
        run_iteration=_stub_run,
        iteration_in_flight=lambda: in_flight,
    )
    return TestClient(app), calls


def _rpc(client, method, params=None, msg_id=1):
    body = {"jsonrpc": "2.0", "id": msg_id, "method": method}
    if params is not None:
        body["params"] = params
    return client.post("/mcp", json=body)


def test_mcp_initialize_returns_protocol_and_tools_capability():
    client, _ = _mcp_client()
    out = _rpc(client, "initialize").json()
    assert out["jsonrpc"] == "2.0" and out["id"] == 1
    assert out["result"]["protocolVersion"] == tool_plane.MCP_PROTOCOL_VERSION
    assert "tools" in out["result"]["capabilities"]


def test_mcp_notification_without_id_gets_202():
    client, _ = _mcp_client()
    resp = client.post(
        "/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert resp.status_code == 202


def test_mcp_tools_list_remaps_input_schema_key():
    client, _ = _mcp_client()
    tools = _rpc(client, "tools/list").json()["result"]["tools"]
    names = [t["name"] for t in tools]
    assert names == [tool_plane.TOOL_NAME, tool_plane.RUN_TOOL_NAME]
    for t in tools:
        assert "inputSchema" in t and "input_schema" not in t
    # Schema content identical to the REST manifest.
    rest = client.get("/tools").json()["tools"]
    assert tools[1]["inputSchema"] == rest[1]["input_schema"]


def test_mcp_tools_call_get_apparatus_state_wraps_rest_envelope():
    client, _ = _mcp_client()
    out = _rpc(client, "tools/call",
               {"name": tool_plane.TOOL_NAME, "arguments": {}}).json()
    assert out["result"]["isError"] is False
    inner = json.loads(out["result"]["content"][0]["text"])
    assert inner["ok"] is True and inner["result"] == _FAKE_STATE


def test_mcp_tools_call_run_loop_iteration_pins_nemoclaw_source():
    client, calls = _mcp_client()
    out = _rpc(client, "tools/call",
               {"name": tool_plane.RUN_TOOL_NAME,
                "arguments": {"topic": "a real GT topic"}}).json()
    inner = json.loads(out["result"]["content"][0]["text"])
    assert inner["ok"] is True
    assert calls["source"] == "nemoclaw_agent"
    assert calls["topic"] == "a real GT topic"


def test_mcp_tools_call_run_error_surfaces_as_is_error_not_500():
    client, calls = _mcp_client(in_flight=True)
    out = _rpc(client, "tools/call",
               {"name": tool_plane.RUN_TOOL_NAME,
                "arguments": {"topic": "t"}}).json()
    assert out["result"]["isError"] is True
    inner = json.loads(out["result"]["content"][0]["text"])
    assert inner["error"] == "iteration_in_flight"
    assert calls["n"] == 0


def test_mcp_unknown_tool_and_method_yield_jsonrpc_errors():
    client, _ = _mcp_client()
    out = _rpc(client, "tools/call", {"name": "nope", "arguments": {}}).json()
    assert out["error"]["code"] == -32602
    out2 = _rpc(client, "resources/list").json()
    assert out2["error"]["code"] == -32601
