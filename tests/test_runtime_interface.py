"""Tests for orchestrator.runtime.

PyRuntime contract:
- dispatch_tool routes to the registry and passes parent_request_id.
- log_event appends one JSON line to run.jsonl with a timestamp.
- read_state / write_state / delete_state round-trip.
- write_state is atomic (no .tmp file left behind).

NemoClawRuntime stub:
- Every method raises NotImplementedError citing D-031.
"""
import json
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from orchestrator.runtime import PyRuntime, NemoClawRuntime, RUN_LOG_PATH


def _make_runtime_with_fake_tools():
    def echo(value, *, parent_request_id):
        return {"status": "passed", "result": {"echo": value, "parent_request_id": parent_request_id}}

    def boom(*, parent_request_id):
        raise RuntimeError("intentional")

    return PyRuntime(tool_registry={"echo": echo, "boom": boom})


def test_dispatch_routes_and_passes_parent_request_id():
    rt = _make_runtime_with_fake_tools()
    out = rt.dispatch_tool("echo", {"value": 42}, parent_request_id="req-1")
    assert out["status"] == "passed"
    assert out["result"]["echo"] == 42
    assert out["result"]["parent_request_id"] == "req-1"


def test_dispatch_unknown_tool_raises_keyerror():
    rt = _make_runtime_with_fake_tools()
    with pytest.raises(KeyError, match="unknown tool"):
        rt.dispatch_tool("nope", {}, parent_request_id="req-1")


def test_dispatch_propagates_tool_exception():
    rt = _make_runtime_with_fake_tools()
    with pytest.raises(RuntimeError, match="intentional"):
        rt.dispatch_tool("boom", {}, parent_request_id="req-1")


def test_log_event_appends_with_timestamp(tmp_path, monkeypatch):
    # Redirect RUN_LOG_PATH to a tmp file so we don't pollute the real one.
    fake_log = tmp_path / "run.jsonl"
    monkeypatch.setattr("orchestrator.runtime.RUN_LOG_PATH", fake_log)
    rt = _make_runtime_with_fake_tools()
    rt.log_event({"task_id": "test1", "status": "passed"})
    rt.log_event({"task_id": "test2", "status": "failed"})

    rows = [json.loads(line) for line in fake_log.read_text().splitlines() if line.strip()]
    assert len(rows) == 2
    for row in rows:
        assert "timestamp" in row
        # ISO 8601 with Z suffix
        assert row["timestamp"].endswith("Z")
    assert rows[0]["task_id"] == "test1"
    assert rows[1]["task_id"] == "test2"


def test_state_roundtrip_and_atomicity(tmp_path, monkeypatch):
    # Point REPO_ROOT at tmp so state files are scoped to the test.
    monkeypatch.setattr("orchestrator.runtime.REPO_ROOT", tmp_path)
    rt = _make_runtime_with_fake_tools()

    # read_state on missing file returns None
    assert rt.read_state("run_state/active_iteration.json") is None

    rt.write_state("run_state/active_iteration.json", {"foo": "bar", "n": 7})
    assert (tmp_path / "run_state" / "active_iteration.json").exists()
    # No .tmp left behind
    assert not (tmp_path / "run_state" / "active_iteration.json.tmp").exists()

    got = rt.read_state("run_state/active_iteration.json")
    assert got == {"foo": "bar", "n": 7}

    rt.delete_state("run_state/active_iteration.json")
    assert rt.read_state("run_state/active_iteration.json") is None
    # delete_state is idempotent on missing
    rt.delete_state("run_state/active_iteration.json")


def test_nemoclaw_runtime_is_stub():
    rt = NemoClawRuntime()
    with pytest.raises(NotImplementedError, match="D-031"):
        rt.dispatch_tool("x", {}, parent_request_id="r")
    with pytest.raises(NotImplementedError, match="D-031"):
        rt.log_event({})
    with pytest.raises(NotImplementedError, match="D-031"):
        rt.read_state("x")
    with pytest.raises(NotImplementedError, match="D-031"):
        rt.write_state("x", {})
    with pytest.raises(NotImplementedError, match="D-031"):
        rt.delete_state("x")
