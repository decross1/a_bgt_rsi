"""Production run-log attribution and fallback regressions.

The old proposed implementation mirror has been removed. Every assertion now
exercises the actual runtime; landed D-043 behavior is a required regression,
not a permissive expected-failure marker. No model calls are made.
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from orchestrator import runtime as runtime_mod

_set_current_agent = runtime_mod.set_current_agent


def _log_event(log_path: Path, event: dict, *, agent=None) -> None:
    assert runtime_mod.RUN_LOG_PATH == log_path
    runtime_mod.PyRuntime(tool_registry={}).log_event(event, agent=agent)


def _read_rows(log_path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in log_path.read_text().splitlines()
        if line.strip()
    ]


@pytest.fixture()
def log_path(tmp_path, monkeypatch):
    path = tmp_path / "run.jsonl"
    monkeypatch.setattr(runtime_mod, "RUN_LOG_PATH", path)
    return path


@pytest.fixture(autouse=True)
def _reset_agent():
    # Reset the ContextVar around each test so state never leaks between cases.
    previous = runtime_mod.get_current_agent()
    _set_current_agent("nara")
    try:
        yield
    finally:
        _set_current_agent(previous)


# ---------------------------------------------------------------------------
# 1. Production attribution contract.
# ---------------------------------------------------------------------------

def test_legacy_call_defaults_agent_to_nara(log_path):
    # A pre-existing call site passes ONLY a dict (no agent). It must keep
    # working and the row must carry the default identity "nara".
    _log_event(log_path, {"task_id": "t1", "status": "passed"})
    (row,) = _read_rows(log_path)
    assert row["agent"] == "nara"
    assert row["task_id"] == "t1"
    assert row["status"] == "passed"
    assert row["timestamp"].endswith("Z")


def test_explicit_agent_param_overrides_default(log_path):
    _log_event(
        log_path, {"task_id": "t2", "status": "passed"}, agent="coordinator"
    )
    (row,) = _read_rows(log_path)
    assert row["agent"] == "coordinator"


def test_contextvar_threads_agent_to_unmodified_call_sites(log_path):
    # The coordinator (or a workflow) sets the agent ONCE; the ~13 nara.py
    # call sites are never touched yet every row they emit inherits it.
    _set_current_agent("coordinator")
    _log_event(log_path, {"event_type": "loop_v0_iteration_start"})
    _log_event(log_path, {"event_type": "loop_v0_iteration_complete"})
    rows = _read_rows(log_path)
    assert [r["agent"] for r in rows] == ["coordinator", "coordinator"]


def test_workflow_role_stamp_format(log_path):
    # A fanned-out workflow agent stamps "workflow:wf_<id>/<role>".
    _set_current_agent("workflow:wf_abc123/limb-b")
    _log_event(log_path, {"event_type": "build_start"})
    (row,) = _read_rows(log_path)
    assert row["agent"] == "workflow:wf_abc123/limb-b"


def test_explicit_agent_beats_contextvar(log_path):
    # Per-call explicit agent wins over the ambient ContextVar.
    _set_current_agent("coordinator")
    _log_event(log_path, {"event_type": "x"}, agent="nara")
    (row,) = _read_rows(log_path)
    assert row["agent"] == "nara"


def test_omitting_agent_does_not_crash_backcompat(log_path):
    # Back-compat: the no-agent path must never raise (mirrors the existing
    # test_log_event_appends_with_timestamp contract, now with agent present).
    _log_event(log_path, {})
    _log_event(log_path, {"status": "failed"})
    rows = _read_rows(log_path)
    assert len(rows) == 2
    for row in rows:
        assert "agent" in row  # always present, never missing
        assert row["agent"] == "nara"


def test_set_none_resets_to_default(log_path):
    # set_current_agent(None) must reset to the default identity, not store None
    # (a None agent in a row would defeat the REQUIRED-field guarantee).
    _set_current_agent("coordinator")
    _set_current_agent(None)
    _log_event(log_path, {"event_type": "x"})
    (row,) = _read_rows(log_path)
    assert row["agent"] == "nara"


def test_skill_used_optional_passes_through(log_path):
    # `skill_used` is OPTIONAL: when a caller includes it in the event dict it
    # is preserved; when absent the row simply omits it (no crash, not forced).
    _log_event(
        log_path, {"event_type": "x", "skill_used": "code-review"}
    )
    _log_event(log_path, {"event_type": "y"})
    with_skill, without_skill = _read_rows(log_path)
    assert with_skill["skill_used"] == "code-review"
    assert "skill_used" not in without_skill


# ---------------------------------------------------------------------------
# 2. Live-code regression test against the REAL PyRuntime. The spine edit
#    LANDED (P0-B/D-043); this was the xfail landing-signal probe and is now a
#    plain test pinning the live behavior.
# ---------------------------------------------------------------------------

def test_real_log_event_threads_agent_when_applied(tmp_path, monkeypatch):
    import orchestrator.runtime as runtime_mod
    from orchestrator.runtime import PyRuntime

    # The applied spine edit: runtime.py exposes set_current_agent + log_event
    # writes an `agent` field. Both assertions must hold.
    fake_log = tmp_path / "run.jsonl"
    monkeypatch.setattr(runtime_mod, "RUN_LOG_PATH", fake_log)

    sig = inspect.signature(PyRuntime.log_event)
    assert "agent" in sig.parameters, "log_event must accept an `agent` param"

    rt = PyRuntime(tool_registry={})
    set_agent = getattr(runtime_mod, "set_current_agent", None)
    assert set_agent is not None, "runtime must expose set_current_agent"
    set_agent("coordinator")
    try:
        rt.log_event({"task_id": "live", "status": "passed"})
    finally:
        set_agent(None)

    (row,) = [
        json.loads(line)
        for line in fake_log.read_text().splitlines()
        if line.strip()
    ]
    assert row["agent"] == "coordinator"


# ---------------------------------------------------------------------------
# 3. Landed D-043 contract: every fallback names its skill.
# ---------------------------------------------------------------------------

def test_loop_v0_fallback_rows_carry_skill_used(monkeypatch):
    # Reuses the loop-v1 integration fakes (sibling-module import, same
    # pattern as _orchestrator_contract.py consumers) to drive the REAL
    # nara.run_iteration through the meta_review-raise fallback site — the
    # same harness as test_meta_review_failure_degrades_gracefully.
    import test_loop_v1_integration as lv1

    from orchestrator import nara

    def _boom(**kwargs):
        raise RuntimeError("meta_review exploded")

    monkeypatch.setattr(nara, "_meta_review", _boom)
    monkeypatch.setattr(nara, "_redteam_critic",
                        lambda *a, **k: lv1._redteam("proceed"))
    monkeypatch.setattr(nara, "get_backend",
                        lambda b: lv1._FakeBackend(lv1._full_chain_script()))
    monkeypatch.setattr(nara.iteration_cache, "write_entry",
                        lambda *a, **k: None)
    monkeypatch.setattr(
        nara, "finalize_iteration_record",
        lambda record: {"status": "passed", "loop_memory_path": "x",
                        "iteration_id": record["iteration_id"]},
    )
    monkeypatch.setattr(nara, "_next_iteration_id",
                        lambda *a, **k: "iter-2026-06-10-901")

    rt = lv1._FakeRuntime(lv1._tool_table())
    nara.run_iteration("test topic", runtime=rt)

    fallbacks = [e for e in rt.events
                 if e.get("event_type") == "loop_v0_fallback"]
    assert fallbacks, "meta_review crash must log a loop_v0_fallback event"
    # POST-diff contract: every fallback row names the canonical skill.
    for event in fallbacks:
        assert event.get("skill_used") == "fallback"
