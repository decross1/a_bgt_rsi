"""Repo-wide pytest fixtures.

- `cache`: per-test iteration_cache redirect (opt-in).
- `_no_live_artifacts` (AUTOUSE, 2026-06-10 / D-048): every test runs with
  the live-artifact default paths redirected to tmp. Tests had been
  polluting the real apparatus files through def-time-bound defaults —
  23 "RuntimeError: boom" coordinator cycles, 3,930 fake-model call
  records (82% of logs/calls.jsonl), and 210 fixture subagent run-log
  rows rendered on the live dashboard. Tests that pass explicit paths
  (the norm) are unaffected; tests that monkeypatch the same attributes
  themselves simply win inside their own scope. The invariant this buys:
  a full pytest run adds ZERO rows to run_state/, logs/, memory/.
"""
from __future__ import annotations

import pytest

from agent_wrapper import worker_activity
from orchestrator import active_run, coordinator, coordinator_cycle_log
from orchestrator import finding_session, iteration_cache, nara
from orchestrator import restate_skeptic
from orchestrator import runtime as runtime_mod
from orchestrator import submitted_run, todo_cli, topicality
from orchestrator import topicality_skeptic


@pytest.fixture
def cache(tmp_path, monkeypatch):
    """Redirect iteration_cache.CACHE_ROOT to a per-test tmp dir.

    Returns the iteration_cache module so tests can call
    `cache.write_entry(...)` / `cache.read_entry(...)` directly with the
    redirect already in place. Workers (which import the module by name)
    pick up the redirect automatically.
    """
    monkeypatch.setattr(iteration_cache, "CACHE_ROOT", tmp_path / "iteration_cache")
    return iteration_cache


@pytest.fixture(autouse=True)
def _no_live_artifacts(tmp_path, monkeypatch):
    """Redirect every live-artifact default path to tmp (see module docstring).
    All targets resolve their defaults IN-BODY (None / sentinel), so
    monkeypatching the module attribute is sufficient."""
    monkeypatch.setattr(active_run, "ACTIVE_RUN_PATH",
                        tmp_path / "active_run.json")
    monkeypatch.setattr(active_run, "RUNS_DIR", tmp_path / "active_runs")
    # Fresh ownership stack per test (contextvars aren't monkeypatchable;
    # tests share one context, so a stale run_id would leak across tests).
    active_run._active_run_stack.set(())
    # The run log: subagent_start/finish + log_event both resolve this
    # module global at call time. Without this patch the suite re-polluted
    # the live week1.run.jsonl through run_subagent (caught by the
    # 2026-06-10 review — 210 junk rows in one day).
    monkeypatch.setattr(runtime_mod, "RUN_LOG_PATH",
                        tmp_path / "week1.run.jsonl")
    monkeypatch.setattr(worker_activity, "DEFAULT_LOG_PATH",
                        tmp_path / "worker_activity.jsonl")
    monkeypatch.setattr(coordinator_cycle_log, "DEFAULT_CYCLES_PATH",
                        tmp_path / "coordinator_cycles.jsonl")
    monkeypatch.setattr(coordinator_cycle_log, "DEFAULT_HEALTH_PATH",
                        tmp_path / "health_signals.jsonl")
    monkeypatch.setattr(coordinator, "DEFAULT_COORDINATOR_BUBBLES",
                        tmp_path / "coordinator_bubbles.jsonl")
    # Session-3 β-bound paths (same leak class caught the same day it was
    # introduced: execute-cycle tests were charging the LIVE daily ledger).
    monkeypatch.setattr(coordinator, "BUDGET_LEDGER_PATH",
                        tmp_path / "coordinator_budget.jsonl")
    monkeypatch.setattr(coordinator, "PAUSE_PATH",
                        tmp_path / "pause_coordinator")
    monkeypatch.setattr(coordinator, "DEFAULT_NEAR_MISSES",
                        tmp_path / "promotion_near_misses.jsonl")
    monkeypatch.setattr(coordinator, "DEFAULT_FOLLOWUPS",
                        tmp_path / "finding_followups.jsonl")
    monkeypatch.setattr(nara, "_DEFAULT_LOG_PATH",
                        str(tmp_path / "calls.jsonl"))
    # topicality.check() is driven directly by nara (not via the runtime),
    # logs to its own module-level CALLS_LOG_PATH, and makes a REAL model
    # call when MOCK_LLM is unset — both redirected here. (The suite's
    # convention remains: run pytest with MOCK_LLM=1.) NOTE: ~9 modules
    # bind CALLS_LOG_PATH from the LOOP_V0_CALLS_LOG env var at IMPORT
    # time, so setenv here would be dead code — only call-time attribute
    # patches work; today's tests pass explicit paths to those modules.
    monkeypatch.setattr(topicality, "CALLS_LOG_PATH",
                        str(tmp_path / "calls.jsonl"))
    # D-046 write-back ledgers (call-time-resolved defaults).
    monkeypatch.setattr(todo_cli, "ACKS_PATH",
                        tmp_path / "coordinator_acks.jsonl")
    monkeypatch.setattr(todo_cli, "QUEUE_PATH",
                        tmp_path / "dev_session_queue.jsonl")
    monkeypatch.setattr(finding_session, "DEFAULT_SURFACED",
                        tmp_path / "surfaced_findings.jsonl")
    monkeypatch.setattr(finding_session, "DEFAULT_STATUS_AUDIT",
                        tmp_path / "surfaced_findings.status.jsonl")
    # MCP submit+poll ticket store (call-time-resolved, same leak class).
    monkeypatch.setattr(submitted_run, "TICKETS_DIR",
                        tmp_path / "tool_plane_submits")
    # The two D-050 skeptics log to their own module-level CALLS_LOG_PATH
    # (same import-time-env class as topicality, redirected above) — path
    # isolation so the D-048 invariant doesn't rest on the MOCK gate alone.
    monkeypatch.setattr(topicality_skeptic, "CALLS_LOG_PATH",
                        str(tmp_path / "calls.jsonl"))
    monkeypatch.setattr(restate_skeptic, "CALLS_LOG_PATH",
                        str(tmp_path / "calls.jsonl"))
