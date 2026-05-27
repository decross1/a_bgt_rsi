"""Tests for workers.critic_loop_v0 (post Path-B + reference-passing).

The worker delegates to orchestrator.subagent.run_subagent. We stub that
function with scripted SubAgentResults to exercise every status + verdict
+ consistency-guard path. Post reference-passing the worker reads
`neighbors` from the per-iteration cache by `iteration_id`, so each test
pre-populates the cache via the `cache` fixture in tests/conftest.py.
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


def _stage(cache, iteration_id: str, neighbors: list[dict]) -> None:
    """Stage a retrieval-tool-result in the cache (mirrors what Nara does
    post-dispatch)."""
    cache.write_entry(iteration_id, "retrieval", {
        "status": "passed",
        "result": {"k": len(neighbors), "neighbors": neighbors},
        "errors": [],
        "wrapper_request_id": "ret-test",
        "parent_request_id": None,
    })


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


def test_empty_hypothesis_errors(cache):
    _stage(cache, "it-1", _neighbors("a"))
    out = crit_mod.critic_loop_v0("", "it-1")
    assert out["status"] == "error"


def test_empty_iteration_id_errors(cache):
    out = crit_mod.critic_loop_v0("h", "")
    assert out["status"] == "error"
    assert any("iteration_id" in e for e in out["errors"])


def test_cache_miss_errors(cache):
    out = crit_mod.critic_loop_v0("h", "it-missing")
    assert out["status"] == "error"
    assert any("iteration cache miss" in e for e in out["errors"])


# ── verdict paths (sub-agent passed) ─────────────────────────────────


def test_survives_verdict(cache, monkeypatch):
    monkeypatch.setattr(crit_mod, "run_subagent", _fake_run_subagent(
        status="passed",
        result={
            "verdict": "survives",
            "rationale": "Nothing in retrieved literature contradicts.",
            "contradicting_paper_id": None,
        },
    ))
    _stage(cache, "it-2", _neighbors("a", "b"))
    out = crit_mod.critic_loop_v0("h", "it-2")
    assert out["status"] == "passed"
    assert out["result"]["verdict"] == "survives"
    assert out["result"]["contradicting_paper_id"] is None
    assert out["result"]["subagent_turns_used"] == 2
    assert out["result"]["subagent_status"] == "passed"


def test_falsified_verdict(cache, monkeypatch):
    monkeypatch.setattr(crit_mod, "run_subagent", _fake_run_subagent(
        status="passed",
        result={
            "verdict": "falsified",
            "rationale": "Chunk a directly contradicts.",
            "contradicting_paper_id": "a",
        },
    ))
    _stage(cache, "it-3", _neighbors("a", "b"))
    out = crit_mod.critic_loop_v0("h", "it-3")
    assert out["status"] == "passed"
    assert out["result"]["verdict"] == "falsified"
    assert out["result"]["contradicting_paper_id"] == "a"


def test_restated_verdict_with_citation(cache, monkeypatch):
    monkeypatch.setattr(crit_mod, "run_subagent", _fake_run_subagent(
        status="passed",
        result={
            "verdict": "restated",
            "rationale": "Same claim as b.",
            "contradicting_paper_id": "b",
        },
    ))
    _stage(cache, "it-4", _neighbors("a", "b"))
    out = crit_mod.critic_loop_v0("h", "it-4")
    assert out["status"] == "passed"
    assert out["result"]["verdict"] == "restated"
    assert out["result"]["contradicting_paper_id"] == "b"


def test_malformed_verdict(cache, monkeypatch):
    monkeypatch.setattr(crit_mod, "run_subagent", _fake_run_subagent(
        status="passed",
        result={
            "verdict": "malformed",
            "rationale": "Not a coherent claim.",
            "contradicting_paper_id": None,
        },
    ))
    _stage(cache, "it-5", _neighbors())
    out = crit_mod.critic_loop_v0("h", "it-5")
    assert out["status"] == "passed"
    assert out["result"]["verdict"] == "malformed"


# ── consistency guards ───────────────────────────────────────────────


def test_contradicting_paper_id_nulled_on_survives(cache, monkeypatch):
    monkeypatch.setattr(crit_mod, "run_subagent", _fake_run_subagent(
        status="passed",
        result={
            "verdict": "survives",
            "rationale": "ok",
            "contradicting_paper_id": "a",
        },
    ))
    _stage(cache, "it-6", _neighbors("a"))
    out = crit_mod.critic_loop_v0("h", "it-6")
    assert out["status"] == "passed"
    assert out["result"]["contradicting_paper_id"] is None
    assert any("nulling per schema" in e for e in out["errors"])


def test_contradicting_paper_id_must_be_in_seen_doc_ids(cache, monkeypatch):
    monkeypatch.setattr(crit_mod, "run_subagent", _fake_run_subagent(
        status="passed",
        result={
            "verdict": "falsified",
            "rationale": "ok",
            "contradicting_paper_id": "not-in-list",
        },
    ))
    _stage(cache, "it-7", _neighbors("a", "b"))
    out = crit_mod.critic_loop_v0("h", "it-7")
    assert out["status"] == "passed"
    assert out["result"]["contradicting_paper_id"] is None
    assert any("not in seen neighbors" in e for e in out["errors"])


def test_rationale_strips_channel_markup(cache, monkeypatch):
    monkeypatch.setattr(crit_mod, "run_subagent", _fake_run_subagent(
        status="passed",
        result={
            "verdict": "survives",
            "rationale": "<channel|>thought\nNothing contradicts the claim.",
            "contradicting_paper_id": None,
        },
    ))
    _stage(cache, "it-8", _neighbors("a"))
    out = crit_mod.critic_loop_v0("h", "it-8")
    assert out["status"] == "passed"
    assert "<channel|>" not in out["result"]["rationale"]
    assert "thought" not in out["result"]["rationale"].split("\n")[0]
    assert "Nothing contradicts" in out["result"]["rationale"]


# ── degraded paths ───────────────────────────────────────────────────


def test_schema_mismatch_falls_back_to_survives(cache, monkeypatch):
    monkeypatch.setattr(crit_mod, "run_subagent", _fake_run_subagent(
        status="schema_mismatch",
        result={"some": "bad payload"},
        errors=["payload didn't validate"],
    ))
    _stage(cache, "it-9", _neighbors("a"))
    out = crit_mod.critic_loop_v0("h", "it-9")
    assert out["status"] == "passed"
    assert out["result"]["verdict"] == "survives"
    assert any("schema mismatch" in e for e in out["errors"])
    assert out["result"]["subagent_status"] == "schema_mismatch"


def test_timeout_falls_back_to_survives(cache, monkeypatch):
    monkeypatch.setattr(crit_mod, "run_subagent", _fake_run_subagent(
        status="timeout",
        result=None,
        errors=["max_wall_seconds exceeded"],
        turns_used=6,
        wall_seconds=91.5,
    ))
    _stage(cache, "it-10", _neighbors("a"))
    out = crit_mod.critic_loop_v0("h", "it-10")
    assert out["status"] == "passed"
    assert out["result"]["verdict"] == "survives"
    assert out["result"]["subagent_status"] == "timeout"
    assert out["result"]["subagent_turns_used"] == 6
    assert out["result"]["subagent_wall_seconds"] == 91.5


def test_subagent_error_returns_worker_error(cache, monkeypatch):
    monkeypatch.setattr(crit_mod, "run_subagent", _fake_run_subagent(
        status="error",
        result=None,
        errors=["vllm down"],
    ))
    _stage(cache, "it-11", _neighbors("a"))
    out = crit_mod.critic_loop_v0("h", "it-11")
    assert out["status"] == "error"
    assert out["result"] is None
    assert any("vllm down" in e for e in out["errors"])


# ── budget + parent_request_id wiring ────────────────────────────────


def test_passes_budget_through(cache, monkeypatch):
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
    _stage(cache, "it-12", _neighbors("a"))
    custom = SubAgentBudget(max_turns=10, max_wall_seconds=180.0, max_tokens_total=20000)
    crit_mod.critic_loop_v0("h", "it-12", budget=custom)
    assert captured["budget"] == custom


def test_default_budget_when_omitted(cache, monkeypatch):
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
    _stage(cache, "it-13", _neighbors("a"))
    crit_mod.critic_loop_v0("h", "it-13")
    assert captured["budget"].max_turns == 6
    assert captured["budget"].max_wall_seconds == 90.0


def test_parent_request_id_threads_through(cache, monkeypatch):
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
    _stage(cache, "it-14", _neighbors("a"))
    crit_mod.critic_loop_v0("h", "it-14", parent_request_id="iter-root-9")
    assert captured["parent_request_id"] == "iter-root-9"


def test_subagent_gets_query_chroma_tool(cache, monkeypatch):
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
    _stage(cache, "it-15", _neighbors("a"))
    crit_mod.critic_loop_v0("h", "it-15")
    tool_names = [t["spec"]["function"]["name"] for t in captured["tools"]]
    assert "query_chroma" in tool_names
    assert "query_chroma" in captured["tool_dispatch"]


def test_caller_tag_in_subagent_call(cache, monkeypatch):
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
    _stage(cache, "it-16", _neighbors("a"))
    crit_mod.critic_loop_v0("h", "it-16")
    assert captured["name"] == "critic_loop_v0"
