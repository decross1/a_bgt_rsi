"""Tests for workers.retrieval_relevance — the critic-honesty relevance gate.

The function is PURE (no LLM, no embedding), so these tests need no
monkeypatching and run identically under MOCK_LLM. Cases are calibrated
against the real distributions in memory/loop_memory.jsonl as of
2026-06-09 (see the worker's module docstring):

  - OFF-DOMAIN (the iter-2026-06-09-001 bug fingerprint: a code-quality
    hypothesis retrieved against game-theory textbooks) -> low_confidence
    True.
  - ON-DOMAIN (a game-theory hypothesis retrieved against game-theory
    neighbors, lexical overlap well above the 0.05 floor) -> low_confidence
    False.
  - EMPTY / malformed retrieval -> low_confidence True.

The thresholds being asserted are the calibrated constants; if they are
retuned the fixtures (which mirror real data) should still bracket them.
"""
from __future__ import annotations

import workers.retrieval_relevance as rr
from workers.retrieval_relevance import relevance


# --- Fixtures mirroring real loop_memory rows -------------------------------

# The bug: hypothesis is about code quality / semantic entropy; neighbors are
# game-theory textbook chunks. Near-zero lexical overlap, mid-band cosine.
_OFF_DOMAIN_HYP = (
    "FASE (Fast Adaptive Semantic Entropy) optimizes code quality by "
    "minimizing the divergence between the semantic entropy of a code "
    "snippet and the entropy distribution of a gold-standard corpus, where "
    "code quality is measured by reduction in cyclomatic complexity and "
    "increase in unit test coverage."
)
_OFF_DOMAIN_NEIGHBORS = [
    {"doc_id": "osborne-272", "score": 0.6026, "source_layer": "foundational",
     "title": "3 Mixed, Correlated, and Evolutionary Equilibrium",
     "chunk_text": "For each structure of the random events there is a pattern "
                   "of behavior that leads to the same equilibrium. If before an "
                   "increase in the price of eggs there was an equilibrium..."},
    {"doc_id": "osborne-041", "score": 0.5914, "source_layer": "foundational",
     "title": "2 Nash Equilibrium",
     "chunk_text": "A Nash equilibrium is a steady state of the play of a "
                   "strategic game in which each player holds the correct "
                   "expectation about the other players' behavior and acts rationally."},
    {"doc_id": "osborne-bargain", "score": 0.5871, "source_layer": "foundational",
     "title": "7 Bargaining Games",
     "chunk_text": "The bargaining problem concerns the division of a surplus "
                   "between two players who must reach unanimous agreement."},
]

# On-domain: a repeated-PD / cooperation hypothesis retrieved against
# game-theory neighbors that actually discuss cooperation, defection, repeated
# play. High lexical overlap.
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


# --- Core calibrated cases --------------------------------------------------

def test_off_domain_flags_low_confidence():
    """The iter-2026-06-09-001 fingerprint must be flagged low_confidence."""
    out = relevance(_OFF_DOMAIN_NEIGHBORS, _OFF_DOMAIN_HYP)
    assert out["low_confidence"] is True
    assert 0.0 <= out["relevance"] <= 1.0
    # The reason must name the actual cause (off-domain / overlap), so a
    # consumer can surface *why* the verdict was tempered.
    assert "off-domain" in out["reason"] or "overlap" in out["reason"]


def test_on_domain_does_not_flag():
    """A genuinely on-domain retrieval set must NOT be downgraded."""
    out = relevance(_ON_DOMAIN_NEIGHBORS, _ON_DOMAIN_HYP)
    assert out["low_confidence"] is False
    assert out["relevance"] > rr.LOW_OVERLAP_THRESHOLD


def test_empty_retrieval_is_low_confidence():
    """Empty retrieval is no basis for novel/survives (rule 4)."""
    out = relevance([], _ON_DOMAIN_HYP)
    assert out["low_confidence"] is True
    assert out["relevance"] == 0.0
    assert "empty" in out["reason"].lower() or "0 neighbors" in out["reason"]


def test_none_neighbors_is_low_confidence():
    out = relevance(None, _ON_DOMAIN_HYP)
    assert out["low_confidence"] is True
    assert out["relevance"] == 0.0


# --- Output contract --------------------------------------------------------

def test_output_shape_and_types():
    out = relevance(_ON_DOMAIN_NEIGHBORS, _ON_DOMAIN_HYP)
    assert set(out.keys()) == {"relevance", "low_confidence", "reason"}
    assert isinstance(out["relevance"], float)
    assert isinstance(out["low_confidence"], bool)
    assert isinstance(out["reason"], str) and out["reason"]


def test_relevance_is_clamped_to_unit_interval():
    for neighbors, hyp in [
        (_OFF_DOMAIN_NEIGHBORS, _OFF_DOMAIN_HYP),
        (_ON_DOMAIN_NEIGHBORS, _ON_DOMAIN_HYP),
        ([{"score": 5.0, "chunk_text": "cooperation defection", "title": "x"}],
         "cooperation defection"),  # absurd score must not blow past 1.0
    ]:
        out = relevance(neighbors, hyp)
        assert 0.0 <= out["relevance"] <= 1.0


# --- Robustness / fallback paths --------------------------------------------

def test_no_hypothesis_falls_back_to_cosine_strong():
    """No hypothesis text -> cosine-only; strong cosine -> confident."""
    out = relevance(
        [{"doc_id": "a", "score": 0.72, "chunk_text": "anything"}], None
    )
    assert out["low_confidence"] is False
    assert "cosine-only" in out["reason"]


def test_no_hypothesis_falls_back_to_cosine_weak():
    """No hypothesis text -> cosine-only; weak cosine -> low_confidence."""
    out = relevance(
        [{"doc_id": "a", "score": 0.40, "chunk_text": "anything"}], None
    )
    assert out["low_confidence"] is True
    assert "cosine-only" in out["reason"]


def test_neighbors_without_text_use_cosine_signal():
    """Neighbors carrying only a score (no chunk_text/title) -> cosine path,
    even when a hypothesis is supplied (there is nothing to overlap against)."""
    out = relevance([{"doc_id": "a", "score": 0.65}], _ON_DOMAIN_HYP)
    assert out["low_confidence"] is False  # strong cosine
    assert "cosine-only" in out["reason"]


def test_missing_or_nonnumeric_scores_do_not_crash():
    """A neighbor with a missing / non-numeric score must be tolerated."""
    neighbors = [
        {"doc_id": "a", "chunk_text": "cooperation defection repeated", "title": "x"},
        {"doc_id": "b", "score": "oops", "chunk_text": "tit for tat punishment"},
    ]
    out = relevance(neighbors, _ON_DOMAIN_HYP)
    assert set(out.keys()) == {"relevance", "low_confidence", "reason"}
    assert 0.0 <= out["relevance"] <= 1.0


def test_generic_gametheory_tokens_do_not_rescue_off_domain():
    """'nash'/'equilibrium'/'game' are stopworded: an off-domain hypothesis
    that happens to contain them must NOT be rescued by neighbors that also
    contain them (this is the GT-corpus rescue trap the calibration warns of)."""
    hyp = "semantic entropy code quality cyclomatic complexity nash equilibrium game"
    neighbors = [
        {"doc_id": "g", "score": 0.60, "title": "Nash Equilibrium",
         "chunk_text": "nash equilibrium game strategic players rationality"},
    ]
    out = relevance(neighbors, hyp)
    # Only the generic GT words overlap; the substantive code tokens do not ->
    # must still read as off-domain.
    assert out["low_confidence"] is True


def test_thin_borderline_is_low_confidence():
    """Borderline overlap AND weak cosine together -> low_confidence (thin)."""
    # Overlap above the 0.05 floor but below 0.10, with cosine below 0.55.
    hyp = "alpha beta gamma delta epsilon zeta eta theta iota kappa"
    neighbors = [
        {"doc_id": "a", "score": 0.50, "title": "t", "chunk_text": "alpha unrelated words here"},
        {"doc_id": "b", "score": 0.48, "title": "t", "chunk_text": "more unrelated text"},
        {"doc_id": "c", "score": 0.47, "title": "t", "chunk_text": "still nothing matching"},
    ]
    out = relevance(neighbors, hyp)
    # 1 of 10 hyp tokens overlaps in the top neighbor -> max overlap 0.1,
    # top-3 mean ~0.033 < 0.05 -> off-domain branch fires. Either way it is
    # low_confidence; assert the honest outcome, not the exact branch.
    assert out["low_confidence"] is True
