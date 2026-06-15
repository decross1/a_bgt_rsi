"""Tests for the NARA_R0_ADVISORY demotion of the primary R0 topicality gate.

D-053 (2026-06-15) — the same shape D-052 applied to the independent
topicality SKEPTIC, applied one rule earlier to the PRIMARY R0 judge. The
primary judge's "off" verdict (orchestrator/topicality.py:_primary_check)
cannot be separated from a camouflaged off-domain claim using hypothesis
text alone (confirmed 4× — D-045/D-050/D-052 +
docs/overgating_promotion_analysis.md), so it over-gates the on-domain novel
case `novel_on_02`. NARA_R0_ADVISORY=1 demotes the primary "off" from a gate
(relevance.low_confidence=True) to a NON-GATING additive advisory
(relevance.r0_advisory=="off"), mirroring relevance.topicality_advisory.

Contract verified here:
  1. Flag OFF (default) — primary "off" sets low_confidence=True (today's
     gate), no r0_advisory key. BYTE-IDENTICAL to pre-D-053.
  2. Flag ON — primary "off" does NOT set low_confidence (the lexical/cosine
     ladder owns the gate); r0_advisory=="off" rides additively.
  3. Flag ON — a downstream `novel` classification on on-domain retrieval is
     NOT downgraded to `unclear` by R0, because low_confidence stays False
     (the novelty_classify.py:434 override reads relevance.low_confidence).
  4. Dark-default purity — with the flag unset every existing relevance path
     is byte-identical (no r0_advisory under any topicality input).

relevance() is PURE; novelty_classify() is stubbed (call_sync +
iteration_cache) so NO real LLM call leaks. Run:
    MOCK_LLM=1 ./.venv-chroma/bin/python -m pytest tests/test_r0_advisory.py -q
"""
from __future__ import annotations

import workers.novelty_classify as nc
from workers.novelty_classify import novelty_classify
from workers.retrieval_relevance import relevance


# On-domain fixtures (mirror tests/test_retrieval_relevance.py): a repeated-PD
# hypothesis against game-theory neighbors with lexical overlap well above the
# 0.05 floor, so the lexical/cosine ladder reads on-domain (low_confidence
# False) — which is what isolates "the gate no longer comes from R0".
_ON_DOMAIN_HYP = (
    "In repeated prisoner dilemma between agents, cooperation emerges and is "
    "sustained when defection triggers punishment, supporting tit-for-tat as a "
    "stable strategy under noisy observation of the opponent's moves."
)
_ON_DOMAIN_NEIGHBORS = [
    {"doc_id": "axelrod-1", "score": 0.66, "source_layer": "foundational",
     "title": "Repeated Prisoner Dilemma and Cooperation",
     "chunk_text": "In the repeated prisoner dilemma, cooperation can be "
                   "sustained when each defection is met with punishment; "
                   "tit-for-tat cooperates first then mirrors the opponent's "
                   "previous move, and remains stable under noisy observation."},
    {"doc_id": "axelrod-2", "score": 0.64, "source_layer": "foundational",
     "title": "Strategy Stability under Noise",
     "chunk_text": "A strategy is stable when no agent can profit by deviating; "
                   "defection and cooperation outcomes depend on the punishment "
                   "scheme and the noisy signal of the opponent moves."},
    {"doc_id": "axelrod-3", "score": 0.61, "source_layer": "live_arxiv",
     "title": "Sustained Cooperation in Repeated Games",
     "chunk_text": "Cooperation among agents in repeated games is sustained by "
                   "tit-for-tat punishment under noisy observation of moves."},
]


# --- 1. Flag OFF: primary "off" still gates, no advisory key ----------------

def test_flag_off_primary_off_still_gates(monkeypatch):
    """Default (env unset): topicality 'off' -> low_confidence True (R0 gate),
    no r0_advisory key. Byte-identical to pre-D-053."""
    monkeypatch.delenv("NARA_R0_ADVISORY", raising=False)
    out = relevance(_ON_DOMAIN_NEIGHBORS, _ON_DOMAIN_HYP, topicality="off")
    assert out["low_confidence"] is True
    assert out["rule_fired"] == "R0"
    assert out["category"] == "off_domain"
    assert "r0_advisory" not in out


def test_flag_explicit_zero_primary_off_still_gates(monkeypatch):
    """NARA_R0_ADVISORY=0 (explicit dark) is identical to unset."""
    monkeypatch.setenv("NARA_R0_ADVISORY", "0")
    out = relevance(_ON_DOMAIN_NEIGHBORS, _ON_DOMAIN_HYP, topicality="off")
    assert out["low_confidence"] is True
    assert out["rule_fired"] == "R0"
    assert "r0_advisory" not in out


# --- 2. Flag ON: primary "off" demoted to a non-gating advisory -------------

def test_flag_on_primary_off_demoted_to_advisory(monkeypatch):
    """NARA_R0_ADVISORY=1: topicality 'off' does NOT set low_confidence; it
    rides as r0_advisory=='off' and the lexical/cosine ladder owns the gate
    (on-domain neighbors -> low_confidence False, rule_fired None)."""
    monkeypatch.setenv("NARA_R0_ADVISORY", "1")
    out = relevance(_ON_DOMAIN_NEIGHBORS, _ON_DOMAIN_HYP, topicality="off")
    assert out["low_confidence"] is False
    assert out["r0_advisory"] == "off"
    # The gate, if any, no longer comes from R0 — the ladder read it on-domain.
    assert out["rule_fired"] is None
    assert out["category"] == "ok"


def test_flag_on_advisory_does_not_override_ladder_gate(monkeypatch):
    """Flag ON does not suppress the lexical gate: an OFF-domain-by-vocabulary
    set (overlap < 0.05) still gates via R1 — the advisory is additive, and
    low_confidence comes from the real signal, not R0."""
    monkeypatch.setenv("NARA_R0_ADVISORY", "1")
    off_hyp = (
        "FASE optimizes code quality by minimizing the divergence between the "
        "semantic entropy of a code snippet and a gold-standard corpus, "
        "measured by cyclomatic complexity and unit test coverage."
    )
    out = relevance(_ON_DOMAIN_NEIGHBORS, off_hyp, topicality="off")
    # The advisory still rides, but the lexical ladder independently gates.
    assert out["r0_advisory"] == "off"
    assert out["low_confidence"] is True
    assert out["rule_fired"] == "R1"  # the lexical gate, NOT R0


def test_flag_on_off_independent_still_gates(monkeypatch):
    """Scope guard: the demotion targets only the PRIMARY 'off'. The R0b
    independent skeptic ('off_independent') keeps its existing gating and emits
    no r0_advisory."""
    monkeypatch.setenv("NARA_R0_ADVISORY", "1")
    out = relevance(_ON_DOMAIN_NEIGHBORS, _ON_DOMAIN_HYP,
                    topicality="off_independent")
    assert out["low_confidence"] is True
    assert out["rule_fired"] == "R0b"
    assert "r0_advisory" not in out


# --- 3. Flag ON: downstream novel classification is NOT downgraded by R0 -----

def _stub_novel_call_sync(monkeypatch):
    """Stub wrapper.call_sync (as imported into novelty_classify) to return a
    deterministic 'novel' completion — no real LLM call (MOCK_LLM-safe)."""
    def _fake_call_sync(messages, **kwargs):
        return {
            "completion": (
                '{"phenomenon": "novel", "substrate": "unstudied_llm", '
                '"predicted_direction": "deviates", '
                '"rationale": "novel claim", "top_neighbor_id": "axelrod-1"}'
            ),
            "request_id": "rid-stub",
        }
    monkeypatch.setattr(nc, "call_sync", _fake_call_sync)


def _stub_retrieval_cache(monkeypatch, relevance_stamp):
    """Stub iteration_cache.read_entry (as used by novelty_classify) to return
    a retrieval tool_result whose result.relevance is `relevance_stamp` — the
    exact shape nara.py writes."""
    def _fake_read_entry(iteration_id, key):
        assert key == "retrieval"
        return {
            "status": "passed",
            "result": {
                "neighbors": _ON_DOMAIN_NEIGHBORS,
                "relevance": relevance_stamp,
            },
        }
    monkeypatch.setattr(nc.iteration_cache, "read_entry", _fake_read_entry)


def test_flag_off_novel_is_downgraded_by_r0(monkeypatch):
    """Baseline for contrast: flag OFF, primary 'off' -> relevance gates ->
    novel is downgraded to unclear (novelty_classify.py:434 override)."""
    monkeypatch.delenv("NARA_R0_ADVISORY", raising=False)
    rel = relevance(_ON_DOMAIN_NEIGHBORS, _ON_DOMAIN_HYP, topicality="off")
    assert rel["low_confidence"] is True  # the R0 gate is live
    _stub_novel_call_sync(monkeypatch)
    _stub_retrieval_cache(monkeypatch, rel)
    res = novelty_classify(_ON_DOMAIN_HYP, "iter-test")["result"]
    assert res["class"] == "unclear"
    assert res.get("verdict_overridden_from") == "novel"


def test_flag_on_novel_not_downgraded_by_r0(monkeypatch):
    """Flag ON, primary 'off' on on-domain retrieval -> relevance does NOT
    gate (low_confidence False), so the novel verdict is PRESERVED — R0 no
    longer downgrades it to unclear."""
    monkeypatch.setenv("NARA_R0_ADVISORY", "1")
    rel = relevance(_ON_DOMAIN_NEIGHBORS, _ON_DOMAIN_HYP, topicality="off")
    assert rel["low_confidence"] is False
    assert rel["r0_advisory"] == "off"
    _stub_novel_call_sync(monkeypatch)
    _stub_retrieval_cache(monkeypatch, rel)
    res = novelty_classify(_ON_DOMAIN_HYP, "iter-test")["result"]
    assert res["class"] == "novel"
    assert "verdict_overridden_from" not in res
    assert res["low_confidence"] is False


# --- 4. Dark-default purity: no r0_advisory under any non-flagged path -------

def test_dark_default_never_emits_r0_advisory(monkeypatch):
    """With the flag unset, relevance() never emits r0_advisory under any
    topicality input or retrieval shape (byte-identical surface)."""
    monkeypatch.delenv("NARA_R0_ADVISORY", raising=False)
    for t in ("on", "off", "off_independent", "unsure", None):
        for neighbors, hyp in (
            (_ON_DOMAIN_NEIGHBORS, _ON_DOMAIN_HYP),
            ([], _ON_DOMAIN_HYP),
            (None, _ON_DOMAIN_HYP),
        ):
            out = relevance(neighbors, hyp, topicality=t)
            assert "r0_advisory" not in out


def test_flag_on_non_off_topicality_emits_no_advisory(monkeypatch):
    """Even with the flag ON, r0_advisory rides ONLY when the primary judge
    said 'off' — 'on'/'unsure'/None carry no advisory (they never gated)."""
    monkeypatch.setenv("NARA_R0_ADVISORY", "1")
    for t in ("on", "unsure", None):
        out = relevance(_ON_DOMAIN_NEIGHBORS, _ON_DOMAIN_HYP, topicality=t)
        assert "r0_advisory" not in out
        assert out["low_confidence"] is False  # on-domain, no gate
