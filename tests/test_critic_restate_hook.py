"""Tests for the critic's restatement-skeptic hook (residual-2 seam).

workers.critic_loop_v0._maybe_run_restate_skeptic: env-gated
(NARA_RESTATE_SKEPTIC=1), fires only on a novelty-judged rediscovery
whose critic verdict is survives/undecidable on CLEAN retrieval (not
rel_low, category ok/absent), and overrides the verdict to "restated" —
with verdict_overridden_from / restate_verdict / contradicting_paper_id
provenance — ONLY when the attack returns a doc-grounded "restated".

A fake orchestrator.restate_skeptic module is injected via sys.modules
so the worker's lazy import resolves to it; no real module code runs.
The helpers below are deliberate LOCAL copies of the staging fixtures
(incl. a local `cache` redirect), so this file stays disjoint from
test_critic_loop_v0.py and self-isolates its filesystem paths.
"""
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from workers import critic_loop_v0 as crit_mod
from orchestrator.subagent import SubAgentResult


@pytest.fixture
def cache(tmp_path, monkeypatch):
    """Redirect iteration_cache.CACHE_ROOT to a per-test tmp dir (local
    copy — shadows the conftest fixture of the same name)."""
    from orchestrator import iteration_cache
    monkeypatch.setattr(iteration_cache, "CACHE_ROOT", tmp_path / "iteration_cache")
    return iteration_cache


@pytest.fixture(autouse=True)
def _gates_unset(monkeypatch):
    """Deterministic env: both skeptic gates start unset in every test."""
    monkeypatch.delenv("NARA_RESTATE_SKEPTIC", raising=False)
    monkeypatch.delenv("NARA_SKEPTIC", raising=False)


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
    cache.write_entry(iteration_id, "novelty", {
        "status": "passed",
        "result": {"class": cls, "rationale": "r", "top_neighbor_id": top,
                   "low_confidence": False},
        "errors": [],
        "wrapper_request_id": "nov-test",
        "parent_request_id": None,
    })


def _fake_run_subagent(*, status, result, errors=None):
    def stub(**kwargs):
        return SubAgentResult(
            status=status,
            result=result,
            errors=errors or [],
            wrapper_call_ids=["sa-rid-1"],
            turns_used=2,
            wall_seconds=1.5,
            output_tokens_used=200,
        )
    return stub


def _subagent_verdict(verdict, doc_id=None):
    return _fake_run_subagent(
        status="passed",
        result={"verdict": verdict, "rationale": "critic rationale",
                "contradicting_paper_id": doc_id},
    )


def _install_fake_restate(monkeypatch, impl):
    """Install a fake orchestrator.restate_skeptic so the worker's lazy
    `from orchestrator import restate_skeptic` resolves to it."""
    import orchestrator
    mod = types.ModuleType("orchestrator.restate_skeptic")
    if impl is not None:
        mod.restate_attack = impl
    monkeypatch.setitem(sys.modules, "orchestrator.restate_skeptic", mod)
    monkeypatch.setattr(orchestrator, "restate_skeptic", mod, raising=False)
    return mod


def _restated(doc_id="prior-art-1"):
    return {
        "restate_verdict": "restated",
        "rationale": "chunk prior-art-1 already states the phenomenon",
        "restating_doc_id": doc_id,
        "canonical_statement": "canonical form",
        "backend": "vllm-qwen",
        "model": "m",
    }


# ── trigger gating ───────────────────────────────────────────────────


def test_not_called_when_env_unset(cache, monkeypatch):
    calls = []
    _install_fake_restate(monkeypatch, lambda *a, **k: calls.append(1) or _restated())
    monkeypatch.setattr(crit_mod, "run_subagent", _subagent_verdict("survives"))
    _stage(cache, "rh-1", _neighbors("a", "b"))
    _stage_novelty(cache, "rh-1", "rediscovery", top="b")
    out = crit_mod.critic_loop_v0("h", "rh-1")
    assert calls == []
    assert out["result"]["verdict"] == "survives"
    assert "restate_verdict" not in out["result"]


def test_not_called_when_novelty_not_rediscovery(cache, monkeypatch):
    monkeypatch.setenv("NARA_RESTATE_SKEPTIC", "1")
    calls = []
    _install_fake_restate(monkeypatch, lambda *a, **k: calls.append(1) or _restated())
    monkeypatch.setattr(crit_mod, "run_subagent", _subagent_verdict("survives"))
    _stage(cache, "rh-2", _neighbors("a"))
    _stage_novelty(cache, "rh-2", "novel", top=None)
    out = crit_mod.critic_loop_v0("h", "rh-2")
    assert calls == []
    assert out["result"]["verdict"] == "survives"
    assert "restate_verdict" not in out["result"]


def test_not_called_when_novelty_entry_absent(cache, monkeypatch):
    monkeypatch.setenv("NARA_RESTATE_SKEPTIC", "1")
    calls = []
    _install_fake_restate(monkeypatch, lambda *a, **k: calls.append(1) or _restated())
    monkeypatch.setattr(crit_mod, "run_subagent", _subagent_verdict("survives"))
    _stage(cache, "rh-3", _neighbors("a"))  # no novelty entry staged
    out = crit_mod.critic_loop_v0("h", "rh-3")
    assert calls == []
    assert out["result"]["verdict"] == "survives"


@pytest.mark.parametrize("verdict,doc", [
    ("falsified", "a"), ("restated", "a"), ("malformed", None),
])
def test_not_called_on_falsified_or_restated_verdict(cache, monkeypatch, verdict, doc):
    monkeypatch.setenv("NARA_RESTATE_SKEPTIC", "1")
    calls = []
    _install_fake_restate(monkeypatch, lambda *a, **k: calls.append(1) or _restated())
    monkeypatch.setattr(crit_mod, "run_subagent", _subagent_verdict(verdict, doc_id=doc))
    it = f"rh-4-{verdict}"
    _stage(cache, it, _neighbors("a"))
    _stage_novelty(cache, it, "rediscovery")
    out = crit_mod.critic_loop_v0("h", it)
    assert calls == []
    assert out["result"]["verdict"] == verdict
    assert "restate_verdict" not in out["result"]


def test_not_called_on_low_confidence_or_non_ok_category(cache, monkeypatch):
    monkeypatch.setenv("NARA_RESTATE_SKEPTIC", "1")
    calls = []
    _install_fake_restate(monkeypatch, lambda *a, **k: calls.append(1) or _restated())
    monkeypatch.setattr(crit_mod, "run_subagent", _subagent_verdict("survives"))
    # low_confidence retrieval: the coverage bar flips to undecidable and
    # the call-site guard keeps the restate skeptic out — a verdict on
    # gated retrieval is never promoted.
    _stage(cache, "rh-5a", _neighbors("a"), relevance={
        "relevance": 0.1, "low_confidence": True, "reason": "off-domain",
    })
    _stage_novelty(cache, "rh-5a", "rediscovery")
    out = crit_mod.critic_loop_v0("h", "rh-5a")
    assert calls == []
    assert out["result"]["verdict"] == "undecidable"
    assert "restate_verdict" not in out["result"]
    # non-ok category (low_confidence false): same guard.
    monkeypatch.setattr(crit_mod, "run_subagent", _subagent_verdict("survives"))
    _stage(cache, "rh-5b", _neighbors("a"), relevance={
        "relevance": 0.3, "low_confidence": False,
        "reason": "no sharp match", "category": "no_sharp_match",
    })
    _stage_novelty(cache, "rh-5b", "rediscovery")
    out2 = crit_mod.critic_loop_v0("h", "rh-5b")
    assert calls == []
    assert out2["result"]["verdict"] == "undecidable"
    assert "restate_verdict" not in out2["result"]


def test_module_without_restate_attack_noops(cache, monkeypatch):
    monkeypatch.setenv("NARA_RESTATE_SKEPTIC", "1")
    _install_fake_restate(monkeypatch, None)  # module lacks restate_attack()
    monkeypatch.setattr(crit_mod, "run_subagent", _subagent_verdict("survives"))
    _stage(cache, "rh-6", _neighbors("a"))
    _stage_novelty(cache, "rh-6", "rediscovery")
    out = crit_mod.critic_loop_v0("h", "rh-6")
    assert out["result"]["verdict"] == "survives"
    assert "restate_verdict" not in out["result"]


# ── override semantics ───────────────────────────────────────────────


def test_survives_flips_to_restated_with_provenance(cache, monkeypatch):
    monkeypatch.setenv("NARA_RESTATE_SKEPTIC", "1")
    captured = {}
    def impl(hypothesis_text, iteration_id=None, backend=None,
             novelty_top_neighbor_id=None):
        captured.update(hyp=hypothesis_text, it=iteration_id,
                        top=novelty_top_neighbor_id)
        return _restated(doc_id="prior-art-1")
    _install_fake_restate(monkeypatch, impl)
    monkeypatch.setattr(crit_mod, "run_subagent", _subagent_verdict("survives"))
    _stage(cache, "rh-7", _neighbors("a", "b"))
    _stage_novelty(cache, "rh-7", "rediscovery", top="b")
    out = crit_mod.critic_loop_v0("hyp text", "rh-7")
    assert captured == {"hyp": "hyp text", "it": "rh-7", "top": "b"}
    res = out["result"]
    assert res["verdict"] == "restated"
    assert res["verdict_overridden_from"] == "survives"
    assert res["restate_verdict"] == "restated"
    assert res["contradicting_paper_id"] == "prior-art-1"
    assert "restatement skeptic" in res["override_reason"]
    assert "vllm-qwen" in res["override_reason"]
    # the flip dissolves the rediscovery/survives consistency warning
    assert not any(e.startswith("consistency_warning:") for e in out["errors"])


def test_undecidable_flips_to_restated(cache, monkeypatch):
    monkeypatch.setenv("NARA_RESTATE_SKEPTIC", "1")
    _install_fake_restate(monkeypatch, lambda *a, **k: _restated(doc_id="prior-art-2"))
    monkeypatch.setattr(crit_mod, "run_subagent", _subagent_verdict("undecidable"))
    _stage(cache, "rh-8", _neighbors("a"))
    _stage_novelty(cache, "rh-8", "rediscovery")
    out = crit_mod.critic_loop_v0("h", "rh-8")
    assert out["result"]["verdict"] == "restated"
    assert out["result"]["verdict_overridden_from"] == "undecidable"
    assert out["result"]["contradicting_paper_id"] == "prior-art-2"


def test_not_restated_leaves_verdict_unchanged(cache, monkeypatch):
    monkeypatch.setenv("NARA_RESTATE_SKEPTIC", "1")
    _install_fake_restate(monkeypatch, lambda *a, **k: {
        "restate_verdict": "not_restated", "rationale": "carries new content",
        "restating_doc_id": None, "canonical_statement": "c",
        "backend": "vllm-qwen", "model": "m",
    })
    monkeypatch.setattr(crit_mod, "run_subagent", _subagent_verdict("survives"))
    _stage(cache, "rh-9", _neighbors("a"))
    _stage_novelty(cache, "rh-9", "rediscovery")
    out = crit_mod.critic_loop_v0("h", "rh-9")
    assert out["result"]["verdict"] == "survives"
    assert out["result"]["restate_verdict"] == "not_restated"
    assert "verdict_overridden_from" not in out["result"]
    # honest residue: survives + rediscovery still gets the warning
    assert any(e.startswith("consistency_warning:") for e in out["errors"])


def test_inconclusive_leaves_verdict_unchanged(cache, monkeypatch):
    monkeypatch.setenv("NARA_RESTATE_SKEPTIC", "1")
    _install_fake_restate(monkeypatch, lambda *a, **k: {
        "restate_verdict": "inconclusive", "rationale": "could not decide",
        "restating_doc_id": None, "canonical_statement": None,
        "backend": "vllm-qwen", "model": "m",
    })
    monkeypatch.setattr(crit_mod, "run_subagent", _subagent_verdict("undecidable"))
    _stage(cache, "rh-10", _neighbors("a"))
    _stage_novelty(cache, "rh-10", "rediscovery")
    out = crit_mod.critic_loop_v0("h", "rh-10")
    assert out["result"]["verdict"] == "undecidable"
    assert out["result"]["restate_verdict"] == "inconclusive"
    assert "verdict_overridden_from" not in out["result"]


def test_restated_without_doc_id_no_override(cache, monkeypatch):
    # Defense in depth: even if a (buggy) module returns "restated" with
    # no doc_id, the hook never moves the verdict ungrounded.
    monkeypatch.setenv("NARA_RESTATE_SKEPTIC", "1")
    _install_fake_restate(monkeypatch, lambda *a, **k: _restated(doc_id=None))
    monkeypatch.setattr(crit_mod, "run_subagent", _subagent_verdict("survives"))
    _stage(cache, "rh-11", _neighbors("a"))
    _stage_novelty(cache, "rh-11", "rediscovery")
    out = crit_mod.critic_loop_v0("h", "rh-11")
    assert out["result"]["verdict"] == "survives"
    assert out["result"]["restate_verdict"] == "restated"
    assert "verdict_overridden_from" not in out["result"]
    assert out["result"]["contradicting_paper_id"] is None


def test_crash_recorded_not_fatal(cache, monkeypatch):
    monkeypatch.setenv("NARA_RESTATE_SKEPTIC", "1")
    def broken(*a, **k):
        raise RuntimeError("qwen down")
    _install_fake_restate(monkeypatch, broken)
    monkeypatch.setattr(crit_mod, "run_subagent", _subagent_verdict("survives"))
    _stage(cache, "rh-12", _neighbors("a"))
    _stage_novelty(cache, "rh-12", "rediscovery")
    out = crit_mod.critic_loop_v0("h", "rh-12")
    assert out["status"] == "passed"
    assert out["result"]["verdict"] == "survives"
    assert out["result"]["restate_verdict"].startswith("error:")
    assert "qwen down" in out["result"]["restate_verdict"]


# ── ordering vs the survives-attack (D-041 seam) ─────────────────────


def test_restate_flip_prevents_survives_skeptic(cache, monkeypatch):
    # The restate hook runs BEFORE _maybe_run_skeptic; a flip to
    # 'restated' means the survives-attack never fires.
    monkeypatch.setenv("NARA_RESTATE_SKEPTIC", "1")
    monkeypatch.setenv("NARA_SKEPTIC", "1")
    _install_fake_restate(monkeypatch, lambda *a, **k: _restated())
    attack_calls = []
    import orchestrator
    nm = types.ModuleType("orchestrator.novelty_skeptic")
    nm.attack = lambda *a, **k: attack_calls.append(1) or {
        "attack_verdict": "refuted", "rationale": "r",
        "contradicting_doc_id": "x", "backend": "b", "model": "m",
    }
    monkeypatch.setitem(sys.modules, "orchestrator.novelty_skeptic", nm)
    monkeypatch.setattr(orchestrator, "novelty_skeptic", nm, raising=False)
    monkeypatch.setattr(crit_mod, "run_subagent", _subagent_verdict("survives"))
    _stage(cache, "rh-13", _neighbors("a"))
    _stage_novelty(cache, "rh-13", "rediscovery")
    out = crit_mod.critic_loop_v0("h", "rh-13")
    assert out["result"]["verdict"] == "restated"
    assert attack_calls == []
    assert "skeptic_verdict" not in out["result"]


def test_result_contract_docstring_mentions_restate_verdict():
    assert "restate_verdict" in crit_mod.critic_loop_v0.__doc__
