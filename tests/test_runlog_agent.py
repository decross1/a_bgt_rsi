"""Tests for the threaded `agent` field on the run logger (LIMB B).

Governance item P0-B (attested 2026-06-09, → D-043): every run-log row must
carry an `agent` attribution field (REQUIRED) plus an optional `skill_used`.
The mechanism threads `agent` through `orchestrator.runtime.PyRuntime.log_event`
without breaking the ~13 existing call sites in `orchestrator/nara.py`, all of
which pass a single positional dict and no `agent`.

This limb may NOT edit `orchestrator/runtime.py` (that is a spine edit drafted
for the integrator). So the suite is split honestly:

1. `_log_event_proposed` — a tiny local helper in THIS file that mirrors the
   exact proposed logic (a `current_agent` ContextVar + a keyword-only
   `agent=None` param that falls back to the ContextVar, defaulting to
   "nara"). These tests are green TODAY and pin the contract the integrator
   must reproduce verbatim in runtime.py. They are the real verification of
   the design.

2. `test_real_log_event_threads_agent_when_applied` — a probe against the LIVE
   `PyRuntime.log_event`. Originally xfail(strict=False) awaiting the
   integrator; the spine edit LANDED (runtime.py threads `agent` via the
   `_current_agent` ContextVar + `set_current_agent`), the probe xpassed, and
   the D-043 closeout (2026-06-10) flipped it to a plain regression test.

3. D-043 closeout probes (2026-06-10): xfail(strict=False) tests pinning the
   two drafted-but-unapplied spine diffs in
   ui_overhaul_gallery/spine_drafts/ — the tool-plane nemoclaw attribution
   probe lives in tests/test_tool_plane.py; the nara loop_v0_fallback
   `skill_used: "fallback"` emission probe lives HERE. Same landing-signal
   pattern as the original probe: green (xfail) today, xpass the moment the
   integrator applies the diffs.

Rule 4 (no coerced near-miss): nothing here fakes a pass — the local helper is
genuine, and the live-code probe is honestly marked as not-yet-passing.

Hermetic + green under MOCK_LLM (no model calls; embedders unused).
"""
from __future__ import annotations

import contextvars
import inspect
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Local mirror of the PROPOSED runtime.py logic (drafted for the integrator).
# Keep this byte-for-byte aligned with the spine_edit in the structured report.
# ---------------------------------------------------------------------------

# Mirrors the proposed module-level ContextVar in orchestrator/runtime.py.
# A run-mode driver sets this once (coordinator / nara / a workflow role);
# every log_event in that context inherits it. ContextVar (not a global) so
# concurrent async iterations don't clobber each other — same pattern as
# agent_wrapper.wrapper._run_id. Default "nara" = the host orchestrator
# identity, so legacy call sites attribute correctly with zero edits.
_current_agent: contextvars.ContextVar = contextvars.ContextVar(
    "_current_agent", default="nara"
)


def _set_current_agent(agent):
    """Mirror of proposed runtime.set_current_agent (None resets to default)."""
    return _current_agent.set(agent if agent is not None else "nara")


def _get_current_agent():
    """Mirror of proposed runtime.get_current_agent."""
    return _current_agent.get()


def _utcnow_iso_stub() -> str:
    # The real log_event stamps a UTC ISO timestamp; a fixed stub keeps the
    # test hermetic and free of clock flakiness. Behavior under test is the
    # `agent` threading, not the timestamp (already covered elsewhere).
    return "2026-06-09T00:00:00Z"


def _log_event_proposed(log_path: Path, event: dict, *, agent=None) -> None:
    """Exact mirror of the PROPOSED PyRuntime.log_event body.

    Signature change vs. today: a single keyword-only `agent=None`. Because
    every existing caller passes only a positional dict, none of them is
    affected — `agent` defaults to None, which resolves to the run's identity
    via the ContextVar. An explicit `agent=` overrides per-call. An `agent`
    key already inside `event` (should not happen) is preserved by the caller
    and not clobbered, since we set the resolved value first then splat event.
    """
    resolved = agent if agent is not None else _get_current_agent()
    row = {"timestamp": _utcnow_iso_stub(), "agent": resolved, **event}
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _read_rows(log_path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in log_path.read_text().splitlines()
        if line.strip()
    ]


@pytest.fixture()
def log_path(tmp_path):
    return tmp_path / "run.jsonl"


@pytest.fixture(autouse=True)
def _reset_agent():
    # Reset the ContextVar around each test so state never leaks between cases.
    token = _current_agent.set("nara")
    try:
        yield
    finally:
        _current_agent.reset(token)


# ---------------------------------------------------------------------------
# 1. Proposed-logic tests (green today; pin the integrator's contract).
# ---------------------------------------------------------------------------

def test_legacy_call_defaults_agent_to_nara(log_path):
    # A pre-existing call site passes ONLY a dict (no agent). It must keep
    # working and the row must carry the default identity "nara".
    _log_event_proposed(log_path, {"task_id": "t1", "status": "passed"})
    (row,) = _read_rows(log_path)
    assert row["agent"] == "nara"
    assert row["task_id"] == "t1"
    assert row["status"] == "passed"
    assert row["timestamp"].endswith("Z")


def test_explicit_agent_param_overrides_default(log_path):
    _log_event_proposed(
        log_path, {"task_id": "t2", "status": "passed"}, agent="coordinator"
    )
    (row,) = _read_rows(log_path)
    assert row["agent"] == "coordinator"


def test_contextvar_threads_agent_to_unmodified_call_sites(log_path):
    # The coordinator (or a workflow) sets the agent ONCE; the ~13 nara.py
    # call sites are never touched yet every row they emit inherits it.
    _set_current_agent("coordinator")
    _log_event_proposed(log_path, {"event_type": "loop_v0_iteration_start"})
    _log_event_proposed(log_path, {"event_type": "loop_v0_iteration_complete"})
    rows = _read_rows(log_path)
    assert [r["agent"] for r in rows] == ["coordinator", "coordinator"]


def test_workflow_role_stamp_format(log_path):
    # A fanned-out workflow agent stamps "workflow:wf_<id>/<role>".
    _set_current_agent("workflow:wf_abc123/limb-b")
    _log_event_proposed(log_path, {"event_type": "build_start"})
    (row,) = _read_rows(log_path)
    assert row["agent"] == "workflow:wf_abc123/limb-b"


def test_explicit_agent_beats_contextvar(log_path):
    # Per-call explicit agent wins over the ambient ContextVar.
    _set_current_agent("coordinator")
    _log_event_proposed(log_path, {"event_type": "x"}, agent="nara")
    (row,) = _read_rows(log_path)
    assert row["agent"] == "nara"


def test_omitting_agent_does_not_crash_backcompat(log_path):
    # Back-compat: the no-agent path must never raise (mirrors the existing
    # test_log_event_appends_with_timestamp contract, now with agent present).
    _log_event_proposed(log_path, {})
    _log_event_proposed(log_path, {"status": "failed"})
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
    _log_event_proposed(log_path, {"event_type": "x"})
    (row,) = _read_rows(log_path)
    assert row["agent"] == "nara"


def test_skill_used_optional_passes_through(log_path):
    # `skill_used` is OPTIONAL: when a caller includes it in the event dict it
    # is preserved; when absent the row simply omits it (no crash, not forced).
    _log_event_proposed(
        log_path, {"event_type": "x", "skill_used": "code-review"}
    )
    _log_event_proposed(log_path, {"event_type": "y"})
    with_skill, without_skill = _read_rows(log_path)
    assert with_skill["skill_used"] == "code-review"
    assert "skill_used" not in without_skill


# ---------------------------------------------------------------------------
# 2. Live-code regression test against the REAL PyRuntime. The spine edit
#    LANDED (P0-B/D-043); this was the xfail landing-signal probe and is now a
#    plain test pinning the live behavior.
# ---------------------------------------------------------------------------

def test_real_log_event_threads_agent_when_applied(tmp_path, monkeypatch):
    from orchestrator.runtime import PyRuntime
    import orchestrator.runtime as runtime_mod

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
# 3. D-043 closeout probe: loop_v0_fallback rows name their skill. xfail until
#    the integrator applies spine_drafts/nara_fallback_skill.diff (rule 6 names
#    fallback as the canonical skill_used; orchestrator/nara.py is SPINE, so
#    the edit is drafted, not made here).
# ---------------------------------------------------------------------------

@pytest.mark.xfail(
    reason=(
        "pending spine diff application — "
        "ui_overhaul_gallery/spine_drafts/nara_fallback_skill.diff adds "
        "skill_used='fallback' to the three loop_v0_fallback log_event "
        "payloads in orchestrator/nara.py (D-043). Flips to xpass the moment "
        "the integrator applies it — that xpass is the landing signal."
    ),
    strict=False,
)
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
