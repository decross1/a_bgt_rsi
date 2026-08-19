"""Hermetic tests for the MCP submit+poll seam (orchestrator/submitted_run.py
+ the tool plane's submit_loop_iteration / poll_run endpoints).

Green under MOCK_LLM=1 and model-free by construction: every test injects a
stub run_iteration through create_app's existing params, and the `seam`
fixture SELF-ISOLATES every filesystem path the seam touches (tickets dir,
active_run mirror + registry, active_iteration board, run log) — no reliance
on conftest, no live artifact is ever written (D-048 invariant). Blocking
stubs gate on threading.Event so the tests control duration; the fixture
releases every registered event and joins the executor thread in teardown
(no sleeps as assertions — wait-loops with deadlines only).
"""
from __future__ import annotations

import json
import os
import threading
import time

import pytest
from fastapi.testclient import TestClient

from orchestrator import active_run, submitted_run, tool_plane
from orchestrator import runtime as runtime_mod


# Same representative record shape as tests/test_tool_plane.py::_FAKE_RECORD —
# the seam must persist the SAME 5-field envelope the sync tool extracts.
_FAKE_RECORD = {
    "iteration_id": "iter-2026-06-10-001",
    "seed": {"topic": "t", "source": "nemoclaw_agent"},
    "novelty": {"class": "novel", "rationale": "r", "low_confidence": False},
    "critique": {"verdict": "survives", "rationale": "r", "low_confidence": False},
    "journal_entry_path": "journal/iterations/042.md",
    "nara_summary": "s",
    "tool_calls_made": ["journal_writer"],
}


class _Seam:
    """Per-test handle: tmp root + an Event factory whose events are ALL
    released in teardown, so a forgotten release can never strand the
    executor thread past the monkeypatched-path scope (it would otherwise
    write to live artifact paths once the patches unwind)."""

    def __init__(self, tmp):
        self.tmp = tmp
        self.events: list[threading.Event] = []

    def event(self) -> threading.Event:
        e = threading.Event()
        self.events.append(e)
        return e


@pytest.fixture
def seam(tmp_path, monkeypatch):
    monkeypatch.setattr(submitted_run, "TICKETS_DIR",
                        tmp_path / "tool_plane_submits")
    monkeypatch.setattr(submitted_run, "ACTIVE_ITERATION_PATH",
                        tmp_path / "active_iteration.json")
    monkeypatch.setattr(active_run, "ACTIVE_RUN_PATH",
                        tmp_path / "active_run.json")
    monkeypatch.setattr(active_run, "RUNS_DIR", tmp_path / "active_runs")
    monkeypatch.setattr(runtime_mod, "RUN_LOG_PATH",
                        tmp_path / "week1.run.jsonl")
    submitted_run._live = None
    handle = _Seam(tmp_path)
    yield handle
    for e in handle.events:  # release any still-gated stub
        e.set()
    live = submitted_run._live
    if live is not None:
        live.join(timeout=5)
        if live.is_alive():  # loud, never silent — a leaked thread would
            raise RuntimeError("submitted-run thread leaked past teardown")
    submitted_run._live = None


def _app(*, record=None, raise_exc=None, gate=None, in_flight=None,
         capture=None):
    """TestClient with a stubbed run_iteration injected via create_app.

    Default in-flight predicate reads the (monkeypatched) active_run mirror
    at call time — the same existence semantics as the production default,
    pointed at tmp. `gate` blocks the stub until the test releases it."""
    calls = {"n": 0, "topic": None, "source": None}

    def _stub_run(topic, *, source=None, **kwargs):
        calls["n"] += 1
        calls["topic"] = topic
        calls["source"] = source
        if capture is not None:
            capture["agent"] = runtime_mod.get_current_agent()
        if gate is not None:
            gate.wait(timeout=10)
        if raise_exc is not None:
            raise raise_exc
        return record if record is not None else _FAKE_RECORD

    predicate = in_flight if in_flight is not None else (
        lambda: active_run.ACTIVE_RUN_PATH.exists())
    app = tool_plane.create_app(
        assess=lambda: {},
        run_iteration=_stub_run,
        iteration_in_flight=predicate,
    )
    return TestClient(app), calls


def _wait_for(cond, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.02)
    return False


def _submit(client, topic="a good topic"):
    return client.post("/tools/submit_loop_iteration",
                       json={"topic": topic}).json()


def _poll(client, run_id):
    return client.post("/tools/poll_run", json={"run_id": run_id}).json()


def _registered(run_id):
    return active_run._run_path(run_id).exists()


def _join_executor():
    t = submitted_run._live
    if t is not None:
        t.join(timeout=5)


def test_submit_returns_immediately_and_registers_ad_hoc_run(seam):
    gate = seam.event()
    client, _ = _app(gate=gate)
    t0 = time.monotonic()
    body = _submit(client, "Vickrey truthfulness under budgets")
    assert time.monotonic() - t0 < 2.0  # returned while the stub is blocked
    assert body["tool"] == "submit_loop_iteration" and body["ok"] is True
    run_id = body["result"]["run_id"]
    assert run_id.startswith("mcpsub-")
    assert body["result"] == {
        "run_id": run_id, "status": "running", "poll_with": "poll_run",
    }
    # The executor thread registers the ticket as a D-047 ad_hoc run:
    # per-run registry file + foreground mirror both appear.
    assert _wait_for(lambda: _registered(run_id), timeout=2.0)
    registry = json.loads(active_run._run_path(run_id).read_text())
    assert registry["kind"] == "ad_hoc"
    assert registry["run_id"] == run_id
    # The mirror is written a beat AFTER the per-run registry file, so this
    # must WAIT like every other mirror assertion in this file — a bare
    # exists() here failed roughly 1 run in 5 under parallel load (flake
    # diagnosed 2026-08-19; the race was in the test, not the writer).
    assert _wait_for(lambda: active_run.ACTIVE_RUN_PATH.exists(), timeout=2.0)
    gate.set()
    _join_executor()
    ticket = submitted_run.read_ticket(run_id)
    assert ticket["status"] == "finished"


def test_submit_validates_topic_with_same_error_strings(seam):
    client, calls = _app()
    for bad, err in [("", "topic_empty"), ("   ", "topic_empty"),
                     (123, "topic_must_be_string"),
                     ("x" * 201, "topic_too_long_max_200")]:
        body = client.post("/tools/submit_loop_iteration",
                           json={"topic": bad}).json()
        assert body == {"tool": "submit_loop_iteration", "ok": False,
                        "error": err}
    # Missing topic entirely — also a non-string.
    body = client.post("/tools/submit_loop_iteration", json={}).json()
    assert body["error"] == "topic_must_be_string"
    # No ticket was ever created; no compute spent.
    assert not submitted_run.TICKETS_DIR.exists()
    assert calls["n"] == 0


def test_submit_refuses_second_submit_while_first_running(seam):
    gate = seam.event()
    client, calls = _app(gate=gate)
    first = _submit(client)["result"]["run_id"]
    # Wait for the first run's registration so the refusal payload can
    # name it deterministically (mirror written by the executor thread).
    assert _wait_for(lambda: active_run.ACTIVE_RUN_PATH.exists())
    second = _submit(client, "another topic")
    assert second["ok"] is False
    assert second["error"] == "iteration_in_flight"
    assert second["in_flight"]["run_id"] == first
    gate.set()
    _join_executor()
    assert calls["n"] == 1  # the refused submit never reached the stub


def test_submit_refuses_when_foreign_run_in_flight(seam):
    # A human/coordinator run is live (predicate True): submit refuses
    # before any ticket exists. in_flight is None — no mirror to read.
    client, calls = _app(in_flight=lambda: True)
    body = _submit(client)
    assert body["ok"] is False and body["error"] == "iteration_in_flight"
    assert body["in_flight"] is None
    assert not submitted_run.TICKETS_DIR.exists()
    assert calls["n"] == 0


def test_sync_run_refuses_while_submitted_run_live(seam):
    gate = seam.event()
    client, calls = _app(gate=gate)
    _submit(client)
    assert _wait_for(lambda: active_run.ACTIVE_RUN_PATH.exists())
    # The SAME mirror predicate gates the synchronous tool: cross-tool
    # one-at-a-time holds while the submitted run is live.
    body = client.post("/tools/run_loop_iteration",
                       json={"topic": "t"}).json()
    assert body == {"tool": "run_loop_iteration", "ok": False,
                    "error": "iteration_in_flight"}
    gate.set()
    _join_executor()
    assert calls["n"] == 1


def test_poll_running_reports_registry_and_active_iteration(seam):
    gate = seam.event()
    client, _ = _app(gate=gate)
    run_id = _submit(client)["result"]["run_id"]
    assert _wait_for(lambda: _registered(run_id))
    # The live step board nara refreshes per step (here: hand-written to
    # the monkeypatched path, exactly the subset poll reads verbatim).
    submitted_run.ACTIVE_ITERATION_PATH.write_text(json.dumps({
        "iteration_id": "iter-2026-06-10-007",
        "current_step": "novelty_classify",
        "latest_narration": "classifying novelty",
        "steps": [{"name": "hypothesize", "status": "done", "extra": "x"},
                  {"name": "novelty_classify", "status": "running"}],
    }))
    out = _poll(client, run_id)
    assert out["tool"] == "poll_run" and out["ok"] is True
    res = out["result"]
    assert res["status"] == "running" and res["run_id"] == run_id
    assert res["registry"]["kind"] == "ad_hoc"
    assert isinstance(res["heartbeat_age_s"], (int, float))
    assert res["stale"] is False
    ai = res["active_iteration"]
    assert ai["iteration_id"] == "iter-2026-06-10-007"
    assert ai["current_step"] == "novelty_classify"
    assert ai["latest_narration"] == "classifying novelty"
    assert ai["steps"] == [
        {"name": "hypothesize", "status": "done"},
        {"name": "novelty_classify", "status": "running"},
    ]
    assert isinstance(ai["updated_at"], str) and ai["updated_at"]
    gate.set()
    _join_executor()


def test_poll_finished_returns_exact_result_envelope(seam):
    client, _ = _app(record=_FAKE_RECORD)
    run_id = _submit(client)["result"]["run_id"]
    assert _wait_for(
        lambda: (submitted_run.read_ticket(run_id) or {}).get("status")
        == "finished")
    _join_executor()
    out = _poll(client, run_id)
    assert out["ok"] is True
    res = out["result"]
    assert res["status"] == "finished" and res["run_id"] == run_id
    assert res["result"] == {
        "iteration_id": "iter-2026-06-10-001",
        "novelty_class": "novel",
        "critic_verdict": "survives",
        "low_confidence": False,
        "journal_entry_path": "journal/iterations/042.md",
    }
    assert isinstance(res["submitted_at"], str)
    assert isinstance(res["finished_at"], str)
    # Clean teardown: the thread deregistered its ad_hoc run — per-run
    # registry file AND foreground mirror are gone.
    assert not _registered(run_id)
    assert not active_run.ACTIVE_RUN_PATH.exists()


def test_poll_failed_when_run_iteration_raises(seam):
    client, _ = _app(raise_exc=RuntimeError("boom"))
    run_id = _submit(client)["result"]["run_id"]
    assert _wait_for(
        lambda: (submitted_run.read_ticket(run_id) or {}).get("status")
        == "failed")
    _join_executor()
    out = _poll(client, run_id)
    assert out["ok"] is True  # the POLL succeeded; the RUN failed
    res = out["result"]
    assert res["status"] == "failed"
    assert "RuntimeError: boom" in res["error"]
    # Registry + mirror cleaned even on failure (the finally path).
    assert not _registered(run_id)
    assert not active_run.ACTIVE_RUN_PATH.exists()
    # Rule 6: the failure logged as a first-class row, attributed to the
    # sandbox identity (D-043 parity).
    rows = [json.loads(l) for l
            in runtime_mod.RUN_LOG_PATH.read_text().splitlines() if l.strip()]
    failed = [r for r in rows
              if r.get("event_type") == "tool_plane_submit_failed"]
    assert failed and failed[0]["agent"] == "nemoclaw_agent"
    assert failed[0]["run_id"] == run_id


def test_poll_unknown_run_id(seam):
    client, _ = _app()
    for foreign in ("mcpsub-20990101T000000Z-beef", "iter-2026-06-10-001"):
        out = _poll(client, foreign)
        assert out == {"tool": "poll_run", "ok": False,
                       "error": "unknown_run_id"}


def test_poll_detects_server_restart_via_pid(seam):
    client, _ = _app()
    # A ticket left "running" by a DEAD process (pid that is not ours):
    # the executor thread cannot exist — threads die with the process.
    run_id = "mcpsub-20260610T000000Z-dead"
    submitted_run.TICKETS_DIR.mkdir(parents=True)
    (submitted_run.TICKETS_DIR / f"{run_id}.json").write_text(json.dumps({
        "run_id": run_id, "status": "running", "topic": "t",
        "submitted_at": "2026-06-10T00:00:00Z", "pid": os.getpid() + 99999,
    }))
    # An orphaned registry doc is REPORTED, never auto-deleted (rule 4).
    orphan = active_run._run_path(run_id)
    orphan.parent.mkdir(parents=True)
    orphan.write_text(json.dumps({"run_id": run_id, "kind": "ad_hoc"}))
    out = _poll(client, run_id)
    res = out["result"]
    assert res["status"] == "failed"
    assert res["error"] == "server_restart_mid_run"
    assert res["orphaned_registry"] is True
    assert orphan.exists()  # report-only: the file was not touched
    # The one reconciliation write: the seam's OWN ticket is now failed
    # on disk, so a second poll answers stably from the terminal state.
    assert submitted_run.read_ticket(run_id)["status"] == "failed"
    again = _poll(client, run_id)["result"]
    assert again["status"] == "failed"
    assert again["error"] == "server_restart_mid_run"


def test_thread_attributes_agent_nemoclaw(seam):
    captured = {}
    client, _ = _app(capture=captured)
    run_id = _submit(client)["result"]["run_id"]
    assert _wait_for(
        lambda: (submitted_run.read_ticket(run_id) or {}).get("status")
        == "finished")
    _join_executor()
    # Inside the executor thread the runtime identity is the sandbox agent
    # (a fresh thread context would otherwise default to "nara").
    assert captured["agent"] == "nemoclaw_agent"
    rows = [json.loads(l) for l
            in runtime_mod.RUN_LOG_PATH.read_text().splitlines() if l.strip()]
    accepted = [r for r in rows
                if r.get("event_type") == "tool_plane_submit_accepted"]
    assert accepted and accepted[0]["agent"] == "nemoclaw_agent"
    assert accepted[0]["run_id"] == run_id
    # The terminal row carries the run_id <-> iteration_id join.
    finished = [r for r in rows
                if r.get("event_type") == "tool_plane_submit_finished"]
    assert finished and finished[0]["iteration_id"] == "iter-2026-06-10-001"


def test_manifests_and_mcp_list_include_four_tools_with_exact_schemas(seam):
    client, _ = _app()
    four = ["get_apparatus_state", "run_loop_iteration",
            "submit_loop_iteration", "poll_run"]
    assert client.get("/health").json()["tools"] == four
    rest = client.get("/tools").json()["tools"]
    assert [t["name"] for t in rest] == four
    by_name = {t["name"]: t for t in rest}
    # submit's input_schema is IDENTICAL to run_loop_iteration's.
    assert (by_name["submit_loop_iteration"]["input_schema"]
            == by_name["run_loop_iteration"]["input_schema"])
    assert by_name["poll_run"]["input_schema"] == {
        "type": "object",
        "properties": {"run_id": {"type": "string"}},
        "required": ["run_id"],
        "additionalProperties": False,
    }
    out = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1,
                                    "method": "tools/list"}).json()
    mcp_tools = out["result"]["tools"]
    assert [t["name"] for t in mcp_tools] == four
    for t in mcp_tools:  # MCP spells the key inputSchema — remap holds
        assert "inputSchema" in t and "input_schema" not in t
    assert (mcp_tools[2]["inputSchema"]
            == by_name["submit_loop_iteration"]["input_schema"])


def test_mcp_tools_call_dispatches_submit_and_poll(seam):
    gate = seam.event()
    client, _ = _app(gate=gate)

    def _rpc(method, params, msg_id=1):
        return client.post("/mcp", json={
            "jsonrpc": "2.0", "id": msg_id, "method": method,
            "params": params}).json()

    out = _rpc("tools/call", {"name": "submit_loop_iteration",
                              "arguments": {"topic": "a real GT topic"}})
    assert out["result"]["isError"] is False
    inner = json.loads(out["result"]["content"][0]["text"])
    assert inner["ok"] is True
    run_id = inner["result"]["run_id"]
    assert run_id.startswith("mcpsub-")
    gate.set()
    assert _wait_for(
        lambda: (submitted_run.read_ticket(run_id) or {}).get("status")
        == "finished")
    _join_executor()
    out = _rpc("tools/call", {"name": "poll_run",
                              "arguments": {"run_id": run_id}}, msg_id=2)
    assert out["result"]["isError"] is False
    inner = json.loads(out["result"]["content"][0]["text"])
    assert inner["ok"] is True
    assert inner["result"]["status"] == "finished"
    assert inner["result"]["result"]["critic_verdict"] == "survives"
    # Unknown tools still answer with the JSON-RPC -32602 error.
    out = _rpc("tools/call", {"name": "nope", "arguments": {}}, msg_id=3)
    assert out["error"]["code"] == -32602


def test_ticket_writes_are_atomic_under_crash_injection(seam):
    # Crash between the tmp write and the rename: the destination ticket
    # must still hold the ORIGINAL, fully-valid JSON — never a partial.
    ticket = submitted_run.new_ticket("t")
    run_id = ticket["run_id"]
    before = submitted_run.read_ticket(run_id)
    assert before["status"] == "running"

    def _boom(src, dst):
        raise OSError("crash injected between tmp write and replace")

    # Scoped MonkeyPatch context — NOT the function-scoped `monkeypatch`
    # fixture, whose undo() would also unwind the seam fixture's path
    # redirects and point reads at live artifacts.
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(submitted_run.os, "replace", _boom)
        with pytest.raises(OSError, match="crash injected"):
            submitted_run.finish_ticket(run_id, {"iteration_id": "x"})
    after = submitted_run.read_ticket(run_id)  # parseable -> not partial
    assert after == before
