"""Tests for workers.critic_loop_v0 (post Path-B sub-agent migration).

The worker delegates to orchestrator.subagent.run_subagent. We stub
that function with scripted SubAgentResults to exercise every status
+ verdict + consistency-guard path.
"""
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from workers import critic_loop_v0 as crit_mod
from orchestrator.subagent import SubAgentResult


def _neighbors(*doc_ids: str) -> list[dict]:
    return [
        {
            "doc_id": d,
            "content_hash": f"sha256:{d}",
            "score": 0.7 - 0.05 * i,
            "chunk_text": f"text for {d}",
            "source_layer": "foundational",
            "title": f"title-{d}",
        }
        for i, d in enumerate(doc_ids)
    ]


def _fake_run_subagent(*, status, result, errors=None, wrapper_call_ids=None,
                       turns_used=2, wall_seconds=1.5, output_tokens_used=200):
    """Build a stub that returns a fixed SubAgentResult regardless of args."""
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


# ── input validation ─────────────────────────────────────────────────


def test_empty_hypothesis_errors():
    out = crit_mod.critic_loop_v0("", _neighbors("a"))
    assert out["status"] == "error"


def test_neighbors_must_be_list():
    out = crit_mod.critic_loop_v0("h", "nope")
    assert out["status"] == "error"


# ── verdict paths (sub-agent passed) ─────────────────────────────────


def test_survives_verdict(monkeypatch):
    monkeypatch.setattr(crit_mod, "run_subagent", _fake_run_subagent(
        status="passed",
        result={
            "verdict": "survives",
            "rationale": "Nothing in retrieved literature contradicts.",
            "contradicting_paper_id": None,
        },
    ))
    out = crit_mod.critic_loop_v0("h", _neighbors("a", "b"))
    assert out["status"] == "passed"
    assert out["result"]["verdict"] == "survives"
    assert out["result"]["contradicting_paper_id"] is None
    # Sub-agent telemetry surfaces
    assert out["result"]["subagent_turns_used"] == 2
    assert out["result"]["subagent_status"] == "passed"


def test_falsified_verdict(monkeypatch):
    monkeypatch.setattr(crit_mod, "run_subagent", _fake_run_subagent(
        status="passed",
        result={
            "verdict": "falsified",
            "rationale": "Chunk a directly contradicts.",
            "contradicting_paper_id": "a",
        },
    ))
    out = crit_mod.critic_loop_v0("h", _neighbors("a", "b"))
    assert out["status"] == "passed"
    assert out["result"]["verdict"] == "falsified"
    assert out["result"]["contradicting_paper_id"] == "a"


def test_restated_verdict_with_citation(monkeypatch):
    monkeypatch.setattr(crit_mod, "run_subagent", _fake_run_subagent(
        status="passed",
        result={
            "verdict": "restated",
            "rationale": "Same claim as b.",
            "contradicting_paper_id": "b",
        },
    ))
    out = crit_mod.critic_loop_v0("h", _neighbors("a", "b"))
    assert out["status"] == "passed"
    assert out["result"]["verdict"] == "restated"
    assert out["result"]["contradicting_paper_id"] == "b"


def test_malformed_verdict(monkeypatch):
    monkeypatch.setattr(crit_mod, "run_subagent", _fake_run_subagent(
        status="passed",
        result={
            "verdict": "malformed",
            "rationale": "Not a coherent claim.",
            "contradicting_paper_id": None,
        },
    ))
    out = crit_mod.critic_loop_v0("h", _neighbors())
    assert out["status"] == "passed"
    assert out["result"]["verdict"] == "malformed"


# ── consistency guards ───────────────────────────────────────────────


def test_contradicting_paper_id_nulled_on_survives(monkeypatch):
    """Even if sub-agent spuriously cites a paper on `survives`, we null it."""
    monkeypatch.setattr(crit_mod, "run_subagent", _fake_run_subagent(
        status="passed",
        result={
            "verdict": "survives",
            "rationale": "ok",
            "contradicting_paper_id": "a",  # bad: shouldn't be set on survives
        },
    ))
    out = crit_mod.critic_loop_v0("h", _neighbors("a"))
    assert out["status"] == "passed"
    assert out["result"]["contradicting_paper_id"] is None
    assert any("nulling per schema" in e for e in out["errors"])


def test_contradicting_paper_id_must_be_in_seen_doc_ids(monkeypatch):
    """Sub-agent cited a doc_id we've never seen — null it with a warning."""
    monkeypatch.setattr(crit_mod, "run_subagent", _fake_run_subagent(
        status="passed",
        result={
            "verdict": "falsified",
            "rationale": "ok",
            "contradicting_paper_id": "not-in-list",
        },
    ))
    out = crit_mod.critic_loop_v0("h", _neighbors("a", "b"))
    assert out["status"] == "passed"
    assert out["result"]["contradicting_paper_id"] is None
    assert any("not in seen neighbors" in e for e in out["errors"])


def test_rationale_strips_channel_markup(monkeypatch):
    """Sub-agent's rationale gets channel markup stripped via _post_validate."""
    monkeypatch.setattr(crit_mod, "run_subagent", _fake_run_subagent(
        status="passed",
        result={
            "verdict": "survives",
            "rationale": "<channel|>thought\nNothing contradicts the claim.",
            "contradicting_paper_id": None,
        },
    ))
    out = crit_mod.critic_loop_v0("h", _neighbors("a"))
    assert out["status"] == "passed"
    assert "<channel|>" not in out["result"]["rationale"]
    assert "thought" not in out["result"]["rationale"].split("\n")[0]
    assert "Nothing contradicts" in out["result"]["rationale"]


# ── degraded paths ───────────────────────────────────────────────────


def test_schema_mismatch_falls_back_to_survives(monkeypatch):
    monkeypatch.setattr(crit_mod, "run_subagent", _fake_run_subagent(
        status="schema_mismatch",
        result={"some": "bad payload"},
        errors=["payload didn't validate"],
    ))
    out = crit_mod.critic_loop_v0("h", _neighbors("a"))
    assert out["status"] == "passed"
    assert out["result"]["verdict"] == "survives"
    assert any("schema mismatch" in e for e in out["errors"])
    assert out["result"]["subagent_status"] == "schema_mismatch"


def test_timeout_falls_back_to_survives(monkeypatch):
    monkeypatch.setattr(crit_mod, "run_subagent", _fake_run_subagent(
        status="timeout",
        result=None,
        errors=["max_wall_seconds exceeded"],
        turns_used=6,
        wall_seconds=91.5,
    ))
    out = crit_mod.critic_loop_v0("h", _neighbors("a"))
    assert out["status"] == "passed"
    assert out["result"]["verdict"] == "survives"
    assert out["result"]["subagent_status"] == "timeout"
    assert out["result"]["subagent_turns_used"] == 6
    assert out["result"]["subagent_wall_seconds"] == 91.5


def test_subagent_error_returns_worker_error(monkeypatch):
    """Unlike timeout/schema_mismatch (which default to 'survives'),
    a hard sub-agent error returns worker status=error so the
    orchestrator can decide whether to retry."""
    monkeypatch.setattr(crit_mod, "run_subagent", _fake_run_subagent(
        status="error",
        result=None,
        errors=["vllm down"],
    ))
    out = crit_mod.critic_loop_v0("h", _neighbors("a"))
    assert out["status"] == "error"
    assert out["result"] is None
    assert any("vllm down" in e for e in out["errors"])


# ── budget + parent_request_id wiring ────────────────────────────────


def test_passes_budget_through(monkeypatch):
    from orchestrator.subagent import SubAgentBudget
    captured = {}
    def stub(**kwargs):
        captured.update(kwargs)
        return SubAgentResult(
            status="passed",
            result={"verdict": "survives", "rationale": "ok", "contradicting_paper_id": None},
            wrapper_call_ids=["x"],
            turns_used=1, wall_seconds=0.1, output_tokens_used=10,
        )
    monkeypatch.setattr(crit_mod, "run_subagent", stub)
    custom = SubAgentBudget(max_turns=10, max_wall_seconds=180.0, max_tokens_total=20000)
    crit_mod.critic_loop_v0("h", _neighbors("a"), budget=custom)
    assert captured["budget"] == custom


def test_default_budget_when_omitted(monkeypatch):
    from orchestrator.subagent import SubAgentBudget
    captured = {}
    def stub(**kwargs):
        captured.update(kwargs)
        return SubAgentResult(
            status="passed",
            result={"verdict": "survives", "rationale": "ok", "contradicting_paper_id": None},
            wrapper_call_ids=["x"],
            turns_used=1, wall_seconds=0.1, output_tokens_used=10,
        )
    monkeypatch.setattr(crit_mod, "run_subagent", stub)
    crit_mod.critic_loop_v0("h", _neighbors("a"))
    # Default: 6 turns, 90s wall.
    assert captured["budget"].max_turns == 6
    assert captured["budget"].max_wall_seconds == 90.0


def test_parent_request_id_threads_through(monkeypatch):
    captured = {}
    def stub(**kwargs):
        captured.update(kwargs)
        return SubAgentResult(
            status="passed",
            result={"verdict": "survives", "rationale": "ok", "contradicting_paper_id": None},
            wrapper_call_ids=["x"],
            turns_used=1, wall_seconds=0.1, output_tokens_used=10,
        )
    monkeypatch.setattr(crit_mod, "run_subagent", stub)
    crit_mod.critic_loop_v0("h", _neighbors("a"), parent_request_id="iter-root-9")
    assert captured["parent_request_id"] == "iter-root-9"


def test_subagent_gets_query_chroma_tool(monkeypatch):
    """The critic sub-agent's toolbelt MUST include query_chroma so the
    sub-agent can fetch additional context when needed."""
    captured = {}
    def stub(**kwargs):
        captured.update(kwargs)
        return SubAgentResult(
            status="passed",
            result={"verdict": "survives", "rationale": "ok", "contradicting_paper_id": None},
            wrapper_call_ids=["x"],
            turns_used=1, wall_seconds=0.1, output_tokens_used=10,
        )
    monkeypatch.setattr(crit_mod, "run_subagent", stub)
    crit_mod.critic_loop_v0("h", _neighbors("a"))
    tool_names = [t["spec"]["function"]["name"] for t in captured["tools"]]
    assert "query_chroma" in tool_names
    assert "query_chroma" in captured["tool_dispatch"]


def test_caller_tag_in_subagent_call(monkeypatch):
    captured = {}
    def stub(**kwargs):
        captured.update(kwargs)
        return SubAgentResult(
            status="passed",
            result={"verdict": "survives", "rationale": "ok", "contradicting_paper_id": None},
            wrapper_call_ids=["x"],
            turns_used=1, wall_seconds=0.1, output_tokens_used=10,
        )
    monkeypatch.setattr(crit_mod, "run_subagent", stub)
    crit_mod.critic_loop_v0("h", _neighbors("a"))
    assert captured["name"] == "critic_loop_v0"
