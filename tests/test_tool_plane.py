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
    assert body["tools"] == [tool_plane.TOOL_NAME]
    # A liveness ping must not load Chroma via assess_state.
    assert calls["n"] == 0


def test_tools_manifest_lists_the_one_tool(monkeypatch):
    client, _ = _client(monkeypatch)
    body = client.get("/tools").json()
    tools = body["tools"]
    assert len(tools) == 1
    tool = tools[0]
    assert tool["name"] == "get_apparatus_state"
    assert isinstance(tool["description"], str) and tool["description"]
    # No-arg tool: an object schema with empty properties.
    assert tool["input_schema"]["type"] == "object"
    assert tool["input_schema"]["properties"] == {}


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
