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


def _stage(cache, iteration_id: str, neighbors: list[dict],
           relevance: dict | None = None) -> None:
    """Stage a retrieval-tool-result in the cache (mirrors what Nara does
    post-dispatch)."""
    result = {"k": len(neighbors), "neighbors": neighbors}
    if relevance is not None:
        result["relevance"] = relevance
    cache.write_entry(iteration_id, "retrieval", {
        "status": "passed",
        "result": result,
        "errors": [],
        "wrapper_request_id": "ret-test",
        "parent_request_id": None,
    })


def _stage_novelty(cache, iteration_id: str, cls: str, top: str | None = "b") -> None:
    """Stage a novelty-tool-result in the cache (Nara writes this after
    novelty_classify, before the critic runs)."""
    cache.write_entry(iteration_id, "novelty", {
        "status": "passed",
        "result": {"class": cls, "rationale": "r", "top_neighbor_id": top,
                   "low_confidence": False},
        "errors": [],
        "wrapper_request_id": "nov-test",
        "parent_request_id": None,
    })


def _survives_subagent():
    return _fake_run_subagent(
        status="passed",
        result={
            "verdict": "survives",
            "rationale": "Closest neighbor a discusses X but does not state the claim.",
            "contradicting_paper_id": None,
        },
    )


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


def test_schema_mismatch_falls_back_to_undecidable(cache, monkeypatch):
    # T1b intended behavior change: a sub-agent failure is NEVER evidence
    # of survival — the old 'survives' default was dangerous.
    monkeypatch.setattr(crit_mod, "run_subagent", _fake_run_subagent(
        status="schema_mismatch",
        result={"some": "bad payload"},
        errors=["payload didn't validate"],
    ))
    _stage(cache, "it-9", _neighbors("a"))
    out = crit_mod.critic_loop_v0("h", "it-9")
    assert out["status"] == "passed"
    assert out["result"]["verdict"] == "undecidable"
    assert any("schema mismatch" in e for e in out["errors"])
    assert out["result"]["subagent_status"] == "schema_mismatch"


def test_timeout_falls_back_to_undecidable(cache, monkeypatch):
    # T1b intended behavior change (same rationale as schema_mismatch).
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
    assert out["result"]["verdict"] == "undecidable"
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


# ── undecidable verdict + ordered decision procedure (T1b) ───────────


def test_allowed_verdicts_contains_undecidable():
    assert "undecidable" in crit_mod.ALLOWED_VERDICTS
    assert "undecidable" in crit_mod._CRITIC_OUTPUT_SCHEMA["properties"]["verdict"]["enum"]


def test_prompt_lists_restated_before_survives():
    p = crit_mod.CRITIC_AGENT_SYSTEM_PROMPT
    assert p.index('"restated"') < p.index('"survives"')
    assert "STEP 1" in p and "RESTATEMENT" in p
    assert "STEP 2" in p and "STEP 3" in p


def test_undecidable_verdict_passes_through(cache, monkeypatch):
    monkeypatch.setattr(crit_mod, "run_subagent", _fake_run_subagent(
        status="passed",
        result={
            "verdict": "undecidable",
            "rationale": "Retrieval too thin to run the checks.",
            "contradicting_paper_id": None,
        },
    ))
    _stage(cache, "ud-1", _neighbors("a"))
    out = crit_mod.critic_loop_v0("h", "ud-1")
    assert out["status"] == "passed"
    assert out["result"]["verdict"] == "undecidable"


def test_undecidable_nulls_contradicting_paper_id(cache, monkeypatch):
    monkeypatch.setattr(crit_mod, "run_subagent", _fake_run_subagent(
        status="passed",
        result={
            "verdict": "undecidable",
            "rationale": "thin",
            "contradicting_paper_id": "a",
        },
    ))
    _stage(cache, "ud-2", _neighbors("a"))
    out = crit_mod.critic_loop_v0("h", "ud-2")
    assert out["result"]["contradicting_paper_id"] is None
    assert any("nulling per schema" in e for e in out["errors"])


# ── coverage-adequacy bar ────────────────────────────────────────────


def test_relevance_category_not_ok_overrides_survives(cache, monkeypatch):
    monkeypatch.setattr(crit_mod, "run_subagent", _survives_subagent())
    _stage(cache, "cov-1", _neighbors("a"), relevance={
        "relevance": 0.2, "low_confidence": False,
        "reason": "no sharp match in retrieved set", "category": "no_sharp_match",
    })
    out = crit_mod.critic_loop_v0("h", "cov-1")
    assert out["result"]["verdict"] == "undecidable"
    assert out["result"]["verdict_overridden_from"] == "survives"
    assert "no_sharp_match" in out["result"]["override_reason"]
    assert out["result"]["rationale"].startswith(
        "(coverage-inadequate retrieval override:"
    )


def test_relevance_category_ok_keeps_survives(cache, monkeypatch):
    monkeypatch.setattr(crit_mod, "run_subagent", _survives_subagent())
    _stage(cache, "cov-2", _neighbors("a"), relevance={
        "relevance": 0.8, "low_confidence": False,
        "reason": "on-domain", "category": "ok",
    })
    out = crit_mod.critic_loop_v0("h", "cov-2")
    assert out["result"]["verdict"] == "survives"
    assert "verdict_overridden_from" not in out["result"]


def test_missing_category_treated_as_ok(cache, monkeypatch):
    # Legacy cached relevance rows carry no `category` field — they must
    # not trigger the coverage override.
    monkeypatch.setattr(crit_mod, "run_subagent", _survives_subagent())
    _stage(cache, "cov-3", _neighbors("a"), relevance={
        "relevance": 0.8, "low_confidence": False, "reason": "on-domain",
    })
    out = crit_mod.critic_loop_v0("h", "cov-3")
    assert out["result"]["verdict"] == "survives"


def test_low_confidence_survives_becomes_undecidable(cache, monkeypatch):
    # Hard rule: low_confidence true + 'survives' -> 'undecidable', even
    # without a category field.
    monkeypatch.setattr(crit_mod, "run_subagent", _survives_subagent())
    _stage(cache, "cov-4", _neighbors("a"), relevance={
        "relevance": 0.1, "low_confidence": True, "reason": "off-domain retrieval",
    })
    out = crit_mod.critic_loop_v0("h", "cov-4")
    assert out["result"]["verdict"] == "undecidable"
    assert out["result"]["verdict_overridden_from"] == "survives"
    assert "off-domain retrieval" in out["result"]["override_reason"]
    assert out["result"]["low_confidence"] is True


def test_category_override_does_not_touch_falsified(cache, monkeypatch):
    monkeypatch.setattr(crit_mod, "run_subagent", _fake_run_subagent(
        status="passed",
        result={
            "verdict": "falsified",
            "rationale": "Chunk a contradicts.",
            "contradicting_paper_id": "a",
        },
    ))
    _stage(cache, "cov-5", _neighbors("a"), relevance={
        "relevance": 0.2, "low_confidence": True,
        "reason": "thin", "category": "thin",
    })
    out = crit_mod.critic_loop_v0("h", "cov-5")
    assert out["result"]["verdict"] == "falsified"
    assert "verdict_overridden_from" not in out["result"]


# ── novelty-context injection + consistency warning ──────────────────


def test_novelty_rediscovery_injected_into_prompt(cache, monkeypatch):
    captured = {}
    def stub(**kwargs):
        captured.update(kwargs)
        return SubAgentResult(
            status="passed",
            result={"verdict": "restated", "rationale": "agrees",
                    "contradicting_paper_id": "b"},
            wrapper_call_ids=["x"],
            turns_used=1, wall_seconds=0.1, output_tokens_used=10,
        )
    monkeypatch.setattr(crit_mod, "run_subagent", stub)
    _stage(cache, "nov-1", _neighbors("a", "b"))
    _stage_novelty(cache, "nov-1", "rediscovery", top="b")
    out = crit_mod.critic_loop_v0("h", "nov-1")
    assert "REDISCOVERY of b" in captured["user_prompt"]
    assert "'restated', not 'survives'" in captured["user_prompt"]
    assert out["result"]["verdict"] == "restated"


def test_novelty_non_rediscovery_not_injected(cache, monkeypatch):
    captured = {}
    def stub(**kwargs):
        captured.update(kwargs)
        return SubAgentResult(
            status="passed",
            result={"verdict": "survives", "rationale": "closest neighbor a differs",
                    "contradicting_paper_id": None},
            wrapper_call_ids=["x"],
            turns_used=1, wall_seconds=0.1, output_tokens_used=10,
        )
    monkeypatch.setattr(crit_mod, "run_subagent", stub)
    _stage(cache, "nov-2", _neighbors("a"))
    _stage_novelty(cache, "nov-2", "novel", top=None)
    out = crit_mod.critic_loop_v0("h", "nov-2")
    assert "NOVELTY CONTEXT" not in captured["user_prompt"]
    assert out["errors"] == []


def test_novelty_cache_absence_tolerated(cache, monkeypatch):
    monkeypatch.setattr(crit_mod, "run_subagent", _survives_subagent())
    _stage(cache, "nov-3", _neighbors("a"))  # no novelty entry staged
    out = crit_mod.critic_loop_v0("h", "nov-3")
    assert out["status"] == "passed"
    assert out["result"]["verdict"] == "survives"


def test_survives_on_cached_rediscovery_appends_consistency_warning(cache, monkeypatch):
    monkeypatch.setattr(crit_mod, "run_subagent", _survives_subagent())
    _stage(cache, "nov-4", _neighbors("a", "b"))
    _stage_novelty(cache, "nov-4", "rediscovery", top="b")
    out = crit_mod.critic_loop_v0("h", "nov-4")
    # No deterministic flip — that would propagate novelty errors.
    assert out["result"]["verdict"] == "survives"
    assert any(e.startswith("consistency_warning:") for e in out["errors"])


# ── skeptic seam (env-gated, lazy import) ────────────────────────────


def _install_fake_skeptic(monkeypatch, attack_impl):
    """Install a fake orchestrator.novelty_skeptic so the worker's lazy
    `from orchestrator import novelty_skeptic` resolves to it."""
    import sys
    import types
    import orchestrator
    mod = types.ModuleType("orchestrator.novelty_skeptic")
    if attack_impl is not None:
        mod.attack = attack_impl
    monkeypatch.setitem(sys.modules, "orchestrator.novelty_skeptic", mod)
    monkeypatch.setattr(orchestrator, "novelty_skeptic", mod, raising=False)
    return mod


def test_skeptic_not_called_when_env_unset(cache, monkeypatch):
    monkeypatch.delenv("NARA_SKEPTIC", raising=False)
    calls = []
    _install_fake_skeptic(monkeypatch, lambda *a, **k: calls.append(1) or {
        "attack_verdict": "refuted", "rationale": "r",
        "contradicting_doc_id": None, "backend": "b", "model": "m",
    })
    monkeypatch.setattr(crit_mod, "run_subagent", _survives_subagent())
    _stage(cache, "sk-1", _neighbors("a"))
    out = crit_mod.critic_loop_v0("h", "sk-1")
    assert calls == []
    assert out["result"]["verdict"] == "survives"
    assert "skeptic_verdict" not in out["result"]


def test_skeptic_refuted_overrides_to_undecidable(cache, monkeypatch):
    monkeypatch.setenv("NARA_SKEPTIC", "1")
    captured = {}
    def attack(hypothesis_text, iteration_id=None, backend="ollama-coder"):
        captured["hyp"] = hypothesis_text
        captured["iteration_id"] = iteration_id
        return {"attack_verdict": "refuted", "rationale": "contradicted by doc-z",
                "contradicting_doc_id": "doc-z", "backend": backend, "model": "m"}
    _install_fake_skeptic(monkeypatch, attack)
    monkeypatch.setattr(crit_mod, "run_subagent", _survives_subagent())
    _stage(cache, "sk-2", _neighbors("a"))
    out = crit_mod.critic_loop_v0("hyp text", "sk-2")
    assert captured["hyp"] == "hyp text"
    assert captured["iteration_id"] == "sk-2"
    assert out["result"]["verdict"] == "undecidable"
    assert out["result"]["verdict_overridden_from"] == "survives"
    assert out["result"]["skeptic_verdict"] == "refuted"
    assert "contradicted by doc-z" in out["result"]["override_reason"]


def test_skeptic_inconclusive_overrides_to_undecidable(cache, monkeypatch):
    monkeypatch.setenv("NARA_SKEPTIC", "1")
    _install_fake_skeptic(monkeypatch, lambda *a, **k: {
        "attack_verdict": "inconclusive", "rationale": "could not decide",
        "contradicting_doc_id": None, "backend": "b", "model": "m",
    })
    monkeypatch.setattr(crit_mod, "run_subagent", _survives_subagent())
    _stage(cache, "sk-3", _neighbors("a"))
    out = crit_mod.critic_loop_v0("h", "sk-3")
    assert out["result"]["verdict"] == "undecidable"
    assert out["result"]["skeptic_verdict"] == "inconclusive"


def test_skeptic_survives_attack_keeps_verdict(cache, monkeypatch):
    monkeypatch.setenv("NARA_SKEPTIC", "1")
    _install_fake_skeptic(monkeypatch, lambda *a, **k: {
        "attack_verdict": "survives_attack", "rationale": "no contradiction found",
        "contradicting_doc_id": None, "backend": "b", "model": "m",
    })
    monkeypatch.setattr(crit_mod, "run_subagent", _survives_subagent())
    _stage(cache, "sk-4", _neighbors("a"))
    out = crit_mod.critic_loop_v0("h", "sk-4")
    assert out["result"]["verdict"] == "survives"
    assert out["result"]["skeptic_verdict"] == "survives_attack"
    assert "verdict_overridden_from" not in out["result"]


def test_skeptic_module_without_attack_noops(cache, monkeypatch):
    monkeypatch.setenv("NARA_SKEPTIC", "1")
    _install_fake_skeptic(monkeypatch, None)  # module lacks attack()
    monkeypatch.setattr(crit_mod, "run_subagent", _survives_subagent())
    _stage(cache, "sk-5", _neighbors("a"))
    out = crit_mod.critic_loop_v0("h", "sk-5")
    assert out["result"]["verdict"] == "survives"
    assert "skeptic_verdict" not in out["result"]


def test_skeptic_not_called_on_non_survives(cache, monkeypatch):
    monkeypatch.setenv("NARA_SKEPTIC", "1")
    calls = []
    _install_fake_skeptic(monkeypatch, lambda *a, **k: calls.append(1) or {
        "attack_verdict": "refuted", "rationale": "r",
        "contradicting_doc_id": None, "backend": "b", "model": "m",
    })
    monkeypatch.setattr(crit_mod, "run_subagent", _fake_run_subagent(
        status="passed",
        result={"verdict": "falsified", "rationale": "chunk a contradicts",
                "contradicting_paper_id": "a"},
    ))
    _stage(cache, "sk-6", _neighbors("a"))
    out = crit_mod.critic_loop_v0("h", "sk-6")
    assert calls == []
    assert out["result"]["verdict"] == "falsified"


def test_skeptic_not_called_on_low_confidence(cache, monkeypatch):
    # The coverage hard rule fires first; the skeptic only attacks a CLEAN
    # 'survives' (low_confidence false).
    monkeypatch.setenv("NARA_SKEPTIC", "1")
    calls = []
    _install_fake_skeptic(monkeypatch, lambda *a, **k: calls.append(1) or {
        "attack_verdict": "survives_attack", "rationale": "r",
        "contradicting_doc_id": None, "backend": "b", "model": "m",
    })
    monkeypatch.setattr(crit_mod, "run_subagent", _survives_subagent())
    _stage(cache, "sk-7", _neighbors("a"), relevance={
        "relevance": 0.1, "low_confidence": True, "reason": "off-domain",
    })
    out = crit_mod.critic_loop_v0("h", "sk-7")
    assert calls == []
    assert out["result"]["verdict"] == "undecidable"


def test_skeptic_crash_is_recorded_not_fatal(cache, monkeypatch):
    monkeypatch.setenv("NARA_SKEPTIC", "1")
    def broken(*a, **k):
        raise RuntimeError("ollama down")
    _install_fake_skeptic(monkeypatch, broken)
    monkeypatch.setattr(crit_mod, "run_subagent", _survives_subagent())
    _stage(cache, "sk-8", _neighbors("a"))
    out = crit_mod.critic_loop_v0("h", "sk-8")
    assert out["status"] == "passed"
    assert out["result"]["verdict"] == "survives"
    assert out["result"]["skeptic_verdict"].startswith("error:")
