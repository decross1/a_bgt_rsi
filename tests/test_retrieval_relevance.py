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

# The three FROZEN keys (UI join contract, commit 0fdb671) plus the T1a
# additive diagnostics. New keys are ADDITIVE per the frozen interface
# contract — the frozen trio never changes shape or meaning.
_FROZEN_KEYS = {"relevance", "low_confidence", "reason"}
_ALL_KEYS = _FROZEN_KEYS | {
    "anchor_cosine", "curated_overlap", "neighbor_spread", "category",
    "rule_fired", "topicality",
}


def test_output_shape_and_types():
    out = relevance(_ON_DOMAIN_NEIGHBORS, _ON_DOMAIN_HYP)
    assert set(out.keys()) == _ALL_KEYS
    assert isinstance(out["relevance"], float)
    assert isinstance(out["low_confidence"], bool)
    assert isinstance(out["reason"], str) and out["reason"]
    assert out["category"] in {"off_domain", "thin", "no_sharp_match", "empty", "ok"}
    assert out["rule_fired"] is None or isinstance(out["rule_fired"], str)


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
    assert set(out.keys()) == _ALL_KEYS
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


# =============================================================================
# T1a additions (2026-06-09 evening): anchor rules R3/R4, spread rule R5,
# legacy reduction, never-rescue invariant. Rules ship DISABLED (constants
# None); tests enable them via monkeypatched module constants.
# =============================================================================

# A 068-like neighbor set: 10 neighbors, scores tightly packed 0.604-0.631
# (spread 0.027), all lexically on-domain (so R1/R2 stay quiet and only the
# spread signal can flag).
_SPREAD_068_NEIGHBORS = [
    {"doc_id": f"clus-{i}", "score": round(0.631 - 0.003 * i, 4),
     "source_layer": "foundational",
     "title": "Repeated Games and Cooperation",
     "chunk_text": "cooperation defection repeated punishment sustained under "
                   "noisy observation of the opponent moves tit-for-tat stable "
                   "strategy agents"}
    for i in range(10)
]


# --- Legacy reduction (the shipped state must be bit-identical to today) -----

def test_legacy_reduction_off_domain():
    """anchor_cosine=None + shipped constants -> identical frozen-trio verdict
    to the pre-T1a gate, with R1/off_domain named in the new keys."""
    out = relevance(_OFF_DOMAIN_NEIGHBORS, _OFF_DOMAIN_HYP, anchor_cosine=None)
    assert out["low_confidence"] is True
    assert out["category"] == "off_domain"
    assert out["rule_fired"] == "R1"
    assert out["anchor_cosine"] is None


def test_legacy_reduction_on_domain_is_ok():
    out = relevance(_ON_DOMAIN_NEIGHBORS, _ON_DOMAIN_HYP)
    assert out["low_confidence"] is False
    assert out["category"] == "ok"
    assert out["rule_fired"] is None


def test_legacy_reduction_empty_category():
    out = relevance([], _ON_DOMAIN_HYP, anchor_cosine=0.7)
    assert out["category"] == "empty"
    assert out["rule_fired"] is None
    assert out["anchor_cosine"] == 0.7  # echoed even on the empty path


def test_anchor_inert_while_constants_none():
    """Shipped state: even an extreme anchor value changes NOTHING while
    ANCHOR_LOW/ANCHOR_BORDERLINE are None — the frozen trio is identical."""
    base = relevance(_ON_DOMAIN_NEIGHBORS, _ON_DOMAIN_HYP, anchor_cosine=None)
    low = relevance(_ON_DOMAIN_NEIGHBORS, _ON_DOMAIN_HYP, anchor_cosine=0.01)
    high = relevance(_ON_DOMAIN_NEIGHBORS, _ON_DOMAIN_HYP, anchor_cosine=0.99)
    for out in (low, high):
        for key in ("relevance", "low_confidence", "reason", "category",
                    "rule_fired"):
            assert out[key] == base[key]


def test_spread_rule_inert_while_spread_max_none():
    """Shipped state: the 068 fingerprint does NOT flag while SPREAD_MAX is
    None (ship disabled means ship disabled)."""
    out = relevance(_SPREAD_068_NEIGHBORS, _ON_DOMAIN_HYP)
    assert out["low_confidence"] is False
    assert out["category"] == "ok"


# --- New diagnostics are always reported -------------------------------------

def test_neighbor_spread_diagnostic_reported():
    """The 068 spread (0.631-0.604 = 0.027) is reported even with R5 off."""
    out = relevance(_SPREAD_068_NEIGHBORS, _ON_DOMAIN_HYP)
    assert out["neighbor_spread"] == 0.027


def test_curated_overlap_foundational_only():
    """curated_overlap reads ONLY source_layer=='foundational' neighbors;
    None when there are none."""
    out = relevance(_ON_DOMAIN_NEIGHBORS, _ON_DOMAIN_HYP)
    assert isinstance(out["curated_overlap"], float) and out["curated_overlap"] > 0
    live_only = [dict(n, source_layer="live_arxiv") for n in _ON_DOMAIN_NEIGHBORS]
    out2 = relevance(live_only, _ON_DOMAIN_HYP)
    assert out2["curated_overlap"] is None


# --- R3: hard off-domain by anchor --------------------------------------------

def test_r3_fires_below_anchor_low(monkeypatch):
    monkeypatch.setattr(rr, "ANCHOR_LOW", 0.45)
    out = relevance(_ON_DOMAIN_NEIGHBORS, _ON_DOMAIN_HYP, anchor_cosine=0.30)
    assert out["low_confidence"] is True
    assert out["category"] == "off_domain"
    assert out["rule_fired"] == "R3"
    assert "anchor" in out["reason"]


def test_r3_does_not_fire_above_anchor_low(monkeypatch):
    monkeypatch.setattr(rr, "ANCHOR_LOW", 0.45)
    out = relevance(_ON_DOMAIN_NEIGHBORS, _ON_DOMAIN_HYP, anchor_cosine=0.60)
    assert out["low_confidence"] is False
    assert out["category"] == "ok"


def test_r3_fires_on_cosine_only_path(monkeypatch):
    """R3 needs no text signal — it condemns on the anchor alone."""
    monkeypatch.setattr(rr, "ANCHOR_LOW", 0.45)
    out = relevance([{"doc_id": "a", "score": 0.72}], None, anchor_cosine=0.30)
    assert out["low_confidence"] is True
    assert out["rule_fired"] == "R3"


# --- The never-rescue invariant -----------------------------------------------

def test_high_anchor_never_rescues_r1(monkeypatch):
    """CRITICAL: the anchor only CONDEMNS. A sky-high anchor cosine must not
    suppress the lexical off-domain rule R1."""
    monkeypatch.setattr(rr, "ANCHOR_LOW", 0.45)
    monkeypatch.setattr(rr, "ANCHOR_BORDERLINE", 0.55)
    out = relevance(_OFF_DOMAIN_NEIGHBORS, _OFF_DOMAIN_HYP, anchor_cosine=0.95)
    assert out["low_confidence"] is True
    assert out["category"] == "off_domain"
    assert out["rule_fired"] == "R1"


def test_high_anchor_never_rescues_r2(monkeypatch):
    """Nor may it suppress the thin rule R2 (weak cosine + borderline overlap)."""
    monkeypatch.setattr(rr, "ANCHOR_LOW", 0.45)
    hyp = "alpha beta gamma delta epsilon zeta eta theta iota kappa"
    # top-3 overlaps 0.1 / 0.1 / 0.0 -> mean ~0.067 (above R1's 0.05, below
    # R2's 0.10) with all cosines < 0.55 -> the R2 'thin' fingerprint.
    neighbors = [
        {"doc_id": "a", "score": 0.50, "title": "t", "chunk_text": "alpha filler words here"},
        {"doc_id": "b", "score": 0.48, "title": "t", "chunk_text": "gamma filler words"},
        {"doc_id": "c", "score": 0.47, "title": "t", "chunk_text": "nothing matching whatsoever"},
    ]
    out = relevance(neighbors, hyp, anchor_cosine=0.95)
    assert out["low_confidence"] is True
    assert out["rule_fired"] == "R2"
    assert out["category"] == "thin"


# --- R4: borderline anchor + weak lexical corroboration ------------------------

_R4_HYP = "alpha beta gamma delta epsilon zeta eta theta iota kappa"
_R4_NEIGHBORS = [
    # overlaps 0.1 / 0.1 / 0.0 -> mean top-3 ~0.067: above the R1 floor
    # (0.05) and below the R4 corroboration line (0.10). Cosines >= 0.55 so
    # R2 stays quiet — only the anchor can flag this set.
    {"doc_id": "a", "score": 0.62, "source_layer": "live_arxiv",
     "title": "t", "chunk_text": "alpha filler words here"},
    {"doc_id": "b", "score": 0.60, "source_layer": "live_arxiv",
     "title": "t", "chunk_text": "beta other filler words"},
    {"doc_id": "c", "score": 0.58, "source_layer": "live_arxiv",
     "title": "t", "chunk_text": "nothing matching at all"},
]


def test_r4_fires_borderline_anchor_weak_overlap(monkeypatch):
    monkeypatch.setattr(rr, "ANCHOR_BORDERLINE", 0.55)
    out = relevance(_R4_NEIGHBORS, _R4_HYP, anchor_cosine=0.50)
    assert out["low_confidence"] is True
    assert out["category"] == "thin"
    assert out["rule_fired"] == "R4"


def test_r4_does_not_fire_above_borderline(monkeypatch):
    monkeypatch.setattr(rr, "ANCHOR_BORDERLINE", 0.55)
    out = relevance(_R4_NEIGHBORS, _R4_HYP, anchor_cosine=0.58)
    assert out["low_confidence"] is False
    assert out["category"] == "ok"


def test_r4_does_not_fire_with_healthy_lexical_signal(monkeypatch):
    """Borderline anchor alone is NOT enough — R4 needs lexical corroboration
    (the on-domain fixture has strong overall AND curated overlap)."""
    monkeypatch.setattr(rr, "ANCHOR_BORDERLINE", 0.55)
    out = relevance(_ON_DOMAIN_NEIGHBORS, _ON_DOMAIN_HYP, anchor_cosine=0.50)
    assert out["low_confidence"] is False
    assert out["category"] == "ok"


def test_r4_fires_on_low_curated_overlap(monkeypatch):
    """The Oc arm: overall overlap healthy (live neighbors echo the words)
    but the FOUNDATIONAL neighbors share almost nothing -> R4 still fires."""
    monkeypatch.setattr(rr, "ANCHOR_BORDERLINE", 0.55)
    hyp = "alpha beta gamma delta epsilon zeta eta theta iota kappa"
    neighbors = [
        {"doc_id": "live1", "score": 0.63, "source_layer": "live_arxiv",
         "title": "t", "chunk_text": "alpha beta gamma delta epsilon echoes"},
        {"doc_id": "live2", "score": 0.61, "source_layer": "live_arxiv",
         "title": "t", "chunk_text": "zeta eta theta iota kappa echoes"},
        {"doc_id": "found1", "score": 0.59, "source_layer": "foundational",
         "title": "t", "chunk_text": "totally disjoint vocabulary chunk"},
    ]
    out = relevance(neighbors, hyp, anchor_cosine=0.50)
    assert out["low_confidence"] is True
    assert out["rule_fired"] == "R4"


# --- R5: no-sharp-match spread diagnostic --------------------------------------

def test_r5_fires_on_068_fingerprint(monkeypatch):
    """10 neighbors, spread 0.027, max cosine 0.631 < 0.66 -> no_sharp_match."""
    monkeypatch.setattr(rr, "SPREAD_MAX", 0.03)
    out = relevance(_SPREAD_068_NEIGHBORS, _ON_DOMAIN_HYP)
    assert out["low_confidence"] is True
    assert out["category"] == "no_sharp_match"
    assert out["rule_fired"] == "R5"
    assert out["neighbor_spread"] == 0.027


def test_r5_does_not_fire_below_8_neighbors(monkeypatch):
    monkeypatch.setattr(rr, "SPREAD_MAX", 0.03)
    out = relevance(_SPREAD_068_NEIGHBORS[:7], _ON_DOMAIN_HYP)
    assert out["low_confidence"] is False
    assert out["category"] == "ok"


def test_r5_does_not_fire_on_wide_spread(monkeypatch):
    monkeypatch.setattr(rr, "SPREAD_MAX", 0.03)
    neighbors = [dict(n) for n in _SPREAD_068_NEIGHBORS]
    neighbors[-1]["score"] = 0.45  # spread now 0.181 — a real ranking
    out = relevance(neighbors, _ON_DOMAIN_HYP)
    assert out["category"] == "ok"


def test_r5_does_not_fire_above_cosine_ceiling(monkeypatch):
    """A tight spread at HIGH absolute similarity is fine (a dense pocket of
    genuinely matching chunks) — the ceiling keeps R5 to the moderate band."""
    monkeypatch.setattr(rr, "SPREAD_MAX", 0.03)
    neighbors = [dict(n, score=round(0.70 - 0.002 * i, 4))
                 for i, n in enumerate(_SPREAD_068_NEIGHBORS)]
    out = relevance(neighbors, _ON_DOMAIN_HYP)  # spread 0.018, maxcos 0.70 > 0.66
    assert out["category"] == "ok"


# ── R0: explicit LLM topicality judgment (2026-06-09 revision cycle) ────────
# Added after BOTH corpus-derived embedding anchors were falsified as
# off-domain separators (calibration gaps -0.079 / -0.075). Only the literal
# "off" condemns; "on"/"unsure"/None never gate (over-gating guard).


def _on_domain_neighbors():
    return [
        {"score": 0.70, "chunk_text": "repeated prisoner dilemma cooperation "
         "tit for tat strategies payoff matrix", "source_layer": "foundational"},
        {"score": 0.68, "chunk_text": "folk theorem repeated interaction "
         "cooperation defection punishment", "source_layer": "foundational"},
    ]


def test_r0_topicality_off_fires_even_on_healthy_retrieval():
    out = relevance(
        _on_domain_neighbors(),
        "Repeated cooperation strategies with payoff defection dynamics",
        topicality="off",
    )
    assert out["low_confidence"] is True
    assert out["category"] == "off_domain"
    assert out["rule_fired"] == "R0"
    assert out["topicality"] == "off"
    # Frozen trio still present.
    assert {"relevance", "low_confidence", "reason"} <= set(out.keys())


def test_r0_on_unsure_and_none_never_condemn():
    for t in ("on", "unsure", None):
        out = relevance(
            _on_domain_neighbors(),
            "Repeated cooperation strategies with payoff defection dynamics",
            topicality=t,
        )
        assert out["rule_fired"] != "R0"
        assert out["topicality"] == t


def test_r0_omitted_reduces_to_legacy_behavior():
    base = relevance(_on_domain_neighbors(),
                     "Repeated cooperation strategies with payoff defection dynamics")
    via_none = relevance(_on_domain_neighbors(),
                         "Repeated cooperation strategies with payoff defection dynamics",
                         topicality=None)
    assert base["low_confidence"] == via_none["low_confidence"]
    assert base["rule_fired"] == via_none["rule_fired"]


# ── D-052: relevance() PURITY w.r.t. topicality_advisory ────────────────────
# The NON-GATING topicality advisory is attached by nara AFTER relevance(),
# on the relevance stamp — relevance() itself must never know about it. It is
# not in the output contract (_ALL_KEYS) and cannot be produced by any
# topicality input. This guards the pure boundary D-052 relies on.

def test_relevance_never_emits_topicality_advisory_any_topicality():
    """relevance() never sets a 'topicality_advisory' key under ANY topicality
    input (on/off/off_independent/unsure/None) or on the empty/off paths."""
    for t in ("on", "off", "off_independent", "unsure", None):
        for neighbors, hyp in (
            (_ON_DOMAIN_NEIGHBORS, _ON_DOMAIN_HYP),
            (_OFF_DOMAIN_NEIGHBORS, _OFF_DOMAIN_HYP),
            ([], _ON_DOMAIN_HYP),
        ):
            out = relevance(neighbors, hyp, topicality=t)
            assert "topicality_advisory" not in out
            # The output key set is exactly the frozen+additive contract — the
            # advisory is NOT part of it (it lives one layer up, in nara).
            assert set(out.keys()) == _ALL_KEYS
