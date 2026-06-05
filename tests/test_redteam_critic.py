"""Tests for workers.redteam_critic (Step 2.5 pre-experiment red-team).

The worker delegates to orchestrator.subagent.run_subagent. We stub that
function with scripted SubAgentResults to exercise every status + verdict +
consistency-guard path. Unlike critic_loop_v0 this worker takes
`hypothesis_text` directly (no iteration_cache read), so no cache fixture is
needed and the test is fully self-contained under MOCK_LLM.
"""
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from workers import redteam_critic as rt_mod
from orchestrator.subagent import SubAgentResult


def _fake_run_subagent(*, status, result, errors=None, wrapper_call_ids=None,
                       turns_used=2, wall_seconds=1.5, output_tokens_used=200):
    """Build a stub returning a fixed SubAgentResult regardless of args."""
    def stub(**kwargs):
        return SubAgentResult(
            status=status,
            result=result,
            errors=errors or [],
            wrapper_call_ids=wrapper_call_ids or ["sa-rid-1"],
            turns_used=turns_used,
            wall_seconds=wall_seconds,
            output_tokens_used=output_tokens_used,
        )
    return stub


# ── shape + verdict (the headline assertion the brief calls for) ──────


def test_shape_and_verdict_enum_under_mock_llm(monkeypatch):
    monkeypatch.setattr(rt_mod, "run_subagent", _fake_run_subagent(
        status="passed",
        result={
            "verdict": "proceed",
            "critique": "No fatal flaw; the claim is testable.",
            "suggested_revision": None,
            "confidence": 0.8,
        },
    ))
    out = rt_mod.redteam_critic("some hypothesis", "iter-2026-06-05-001")
    assert out["status"] == "passed"
    res = out["result"]
    assert set(["verdict", "critique", "suggested_revision", "confidence"]).issubset(res)
    assert res["verdict"] in {"fatal_flaw", "proceed"}
    assert isinstance(res["critique"], str)
    assert isinstance(res["confidence"], float)
    assert res["subagent_status"] == "passed"
    assert res["subagent_turns_used"] == 2


# ── input validation ─────────────────────────────────────────────────


def test_empty_hypothesis_errors():
    out = rt_mod.redteam_critic("", "iter-1")
    assert out["status"] == "error"
    assert any("hypothesis_text" in e for e in out["errors"])


def test_empty_iteration_id_errors():
    out = rt_mod.redteam_critic("h", "")
    assert out["status"] == "error"
    assert any("iteration_id" in e for e in out["errors"])


# ── verdict paths (sub-agent passed) ─────────────────────────────────


def test_fatal_flaw_verdict_keeps_revision(monkeypatch):
    monkeypatch.setattr(rt_mod, "run_subagent", _fake_run_subagent(
        status="passed",
        result={
            "verdict": "fatal_flaw",
            "critique": "Contradicts backward induction.",
            "suggested_revision": "Restrict to infinite horizon.",
            "confidence": 0.9,
        },
    ))
    out = rt_mod.redteam_critic("h", "iter-2")
    assert out["status"] == "passed"
    assert out["result"]["verdict"] == "fatal_flaw"
    assert out["result"]["suggested_revision"] == "Restrict to infinite horizon."


# ── consistency guards ───────────────────────────────────────────────


def test_revision_nulled_on_proceed(monkeypatch):
    monkeypatch.setattr(rt_mod, "run_subagent", _fake_run_subagent(
        status="passed",
        result={
            "verdict": "proceed",
            "critique": "ok",
            "suggested_revision": "leftover revision",
            "confidence": 0.7,
        },
    ))
    out = rt_mod.redteam_critic("h", "iter-3")
    assert out["status"] == "passed"
    assert out["result"]["suggested_revision"] is None
    assert any("nulling per schema" in e for e in out["errors"])


def test_confidence_clamped(monkeypatch):
    monkeypatch.setattr(rt_mod, "run_subagent", _fake_run_subagent(
        status="passed",
        result={
            "verdict": "proceed",
            "critique": "ok",
            "suggested_revision": None,
            "confidence": 1.7,
        },
    ))
    out = rt_mod.redteam_critic("h", "iter-4")
    assert out["result"]["confidence"] == 1.0


def test_critique_strips_channel_markup(monkeypatch):
    monkeypatch.setattr(rt_mod, "run_subagent", _fake_run_subagent(
        status="passed",
        result={
            "verdict": "proceed",
            "critique": "<channel|>thought\nThe claim is well-posed.",
            "suggested_revision": None,
            "confidence": 0.5,
        },
    ))
    out = rt_mod.redteam_critic("h", "iter-5")
    assert "<channel|>" not in out["result"]["critique"]
    assert "The claim is well-posed" in out["result"]["critique"]


# ── degraded paths default to proceed (do not block the chain) ───────


def test_schema_mismatch_falls_back_to_proceed(monkeypatch):
    monkeypatch.setattr(rt_mod, "run_subagent", _fake_run_subagent(
        status="schema_mismatch",
        result={"some": "bad payload"},
        errors=["payload didn't validate"],
    ))
    out = rt_mod.redteam_critic("h", "iter-6")
    assert out["status"] == "passed"
    assert out["result"]["verdict"] == "proceed"
    assert out["result"]["subagent_status"] == "schema_mismatch"
    assert any("schema mismatch" in e for e in out["errors"])


def test_timeout_falls_back_to_proceed(monkeypatch):
    monkeypatch.setattr(rt_mod, "run_subagent", _fake_run_subagent(
        status="timeout",
        result=None,
        errors=["max_wall_seconds exceeded"],
        turns_used=3,
        wall_seconds=46.0,
    ))
    out = rt_mod.redteam_critic("h", "iter-7")
    assert out["status"] == "passed"
    assert out["result"]["verdict"] == "proceed"
    assert out["result"]["subagent_status"] == "timeout"
    assert out["result"]["subagent_wall_seconds"] == 46.0


def test_subagent_error_returns_worker_error(monkeypatch):
    monkeypatch.setattr(rt_mod, "run_subagent", _fake_run_subagent(
        status="error",
        result=None,
        errors=["vllm down"],
    ))
    out = rt_mod.redteam_critic("h", "iter-8")
    assert out["status"] == "error"
    assert out["result"] is None
    assert any("vllm down" in e for e in out["errors"])


# ── budget + wiring ──────────────────────────────────────────────────


def test_default_budget_when_omitted(monkeypatch):
    captured = {}
    def stub(**kwargs):
        captured.update(kwargs)
        return SubAgentResult(
            status="passed",
            result={"verdict": "proceed", "critique": "ok",
                    "suggested_revision": None, "confidence": 0.5},
            wrapper_call_ids=["x"],
            turns_used=1, wall_seconds=0.1, output_tokens_used=10,
        )
    monkeypatch.setattr(rt_mod, "run_subagent", stub)
    rt_mod.redteam_critic("h", "iter-9")
    assert captured["budget"].max_turns == 3
    assert captured["budget"].max_wall_seconds == 45.0


def test_parent_request_id_threads_through(monkeypatch):
    captured = {}
    def stub(**kwargs):
        captured.update(kwargs)
        return SubAgentResult(
            status="passed",
            result={"verdict": "proceed", "critique": "ok",
                    "suggested_revision": None, "confidence": 0.5},
            wrapper_call_ids=["x"],
            turns_used=1, wall_seconds=0.1, output_tokens_used=10,
        )
    monkeypatch.setattr(rt_mod, "run_subagent", stub)
    rt_mod.redteam_critic("h", "iter-10", parent_request_id="iter-root-9")
    assert captured["parent_request_id"] == "iter-root-9"


def test_caller_tag_in_subagent_call(monkeypatch):
    captured = {}
    def stub(**kwargs):
        captured.update(kwargs)
        return SubAgentResult(
            status="passed",
            result={"verdict": "proceed", "critique": "ok",
                    "suggested_revision": None, "confidence": 0.5},
            wrapper_call_ids=["x"],
            turns_used=1, wall_seconds=0.1, output_tokens_used=10,
        )
    monkeypatch.setattr(rt_mod, "run_subagent", stub)
    rt_mod.redteam_critic("h", "iter-11")
    assert captured["name"] == "redteam_critic"
