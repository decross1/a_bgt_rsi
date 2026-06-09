"""Tests for the reverse-path dispatcher (orchestrator/thesis_to_experiment).

Pure/deterministic — no LLM, no run_state reads at runtime. The two
thesis fixtures are the REAL worked examples from
docs/thesis_to_experiment_construction.md, copied verbatim from
run_state/iteration_cache/<id>/hypothesis.json (2026-06-09).
"""
from __future__ import annotations

from orchestrator import thesis_to_experiment as t2e

# Verbatim from run_state/iteration_cache/iter-2026-05-27-001/hypothesis.json
PD_THESIS = (
    "LLM agents in a repeated Prisoner's Dilemma will exhibit significantly "
    "higher cooperation rates when the history of interactions is presented "
    "as a cohesive narrative compared to a structured list of move sequences."
)

# Verbatim from run_state/iteration_cache/iter-2026-06-06-001/hypothesis.json
COURNOT_THESIS = (
    "The convergence of LLM agents to the Nash quantity in a Cournot duopoly "
    "is modulated by the presence of few-shot prompting examples that "
    "explicitly define the marginal cost parameter, which reduces the "
    "variance of the agents' quantity-selection logits."
)


def _dispatch(thesis, **kw):
    args = dict(novelty_class="novel", critic_verdict="survives",
                low_confidence=False)
    args.update(kw)
    return t2e.dispatch(thesis, args["novelty_class"], args["critic_verdict"],
                        args["low_confidence"],
                        args.get("neighbor_titles"),
                        source_iteration_id=args.get("source_iteration_id"))


# ---- worked example 1: PD thesis -> built exp001, full spec ----

def test_pd_thesis_routes_to_built_exp001():
    spec = _dispatch(PD_THESIS, source_iteration_id="iter-2026-05-27-001")
    assert spec is not None
    assert spec["game"] == "repeated_pd"
    assert spec["design_only"] is False  # exp001 has run.py + loop_bridge.py
    assert spec["experiment_id"] == "exp001_repeated_pd"
    assert spec["claim"] == PD_THESIS  # verbatim, never paraphrased
    assert spec["source_iteration_id"] == "iter-2026-05-27-001"
    assert spec["treatment"] == {"factor": "history_framing",
                                 "levels": ["list", "narrative"]}
    assert spec["metric"] == "coop_rate"
    assert spec["expected_range"]["directional"] == "coop(narrative) > coop(list)"
    assert "folk-theorem" in spec["equilibrium_anchor"]


# ---- worked example 2: Cournot thesis -> full spec (exp009 built+registered
# 2026-06-09: limb F shipped run/analyze/loop_bridge, integrator registered it
# in _TIER_MAP) ----

def test_cournot_thesis_routes_runnable_spec():
    spec = _dispatch(COURNOT_THESIS, source_iteration_id="iter-2026-06-06-001")
    assert spec is not None
    assert spec["game"] == "cournot"
    assert spec["design_only"] is False
    assert spec["experiment_id"] == "exp009_cournot"
    assert spec["claim"] == COURNOT_THESIS
    assert spec["metric"] == "mean_abs_deviation_from_nash_quantity"
    assert spec["expected_range"]["primary"] == [0.0, 0.15]
    assert spec["equilibrium_anchor"] == "q_star = (a - c) / (3 b)"
    assert spec["treatment"]["factor"] == "few_shot_marginal_cost"


# ---- eligibility gate ----

def test_undecidable_verdict_is_ineligible():
    # "undecidable" fails closed: it is not "survives", by construction.
    assert _dispatch(PD_THESIS, critic_verdict="undecidable") is None
    assert t2e.is_eligible("novel", "undecidable", False) is False


def test_falsified_restated_malformed_ineligible():
    for v in ("falsified", "restated", "malformed", None):
        assert _dispatch(PD_THESIS, critic_verdict=v) is None


def test_rediscovery_and_nonsense_novelty_ineligible():
    for nc in ("rediscovery", "nonsense", None):
        assert _dispatch(PD_THESIS, novelty_class=nc) is None
    assert _dispatch(PD_THESIS, novelty_class="unclear") is not None


def test_low_confidence_ineligible():
    assert _dispatch(PD_THESIS, low_confidence=True) is None


# ---- routing edges ----

def test_no_keyword_match_returns_none():
    assert _dispatch(
        "Semantic entropy of decoder logits predicts hallucination rate "
        "in retrieval-augmented summarization.") is None


def test_neighbor_titles_participate_in_routing():
    spec = _dispatch(
        "LLM agents converge to the known equilibrium under repetition.",
        neighbor_titles=["Truthful bidding in sealed-bid second-price "
                         "auctions with LLM bidders"])
    assert spec is not None
    assert spec["game"] == "vickrey"
    assert spec["design_only"] is False  # exp003 is fully built


def test_first_built_match_preferred_over_earlier_design_only_match():
    # public_goods (table-earlier, no experiment) AND vickrey (built):
    # the dispatcher must pick the first BUILT match, not the first match.
    spec = _dispatch(
        "Free-riding in public goods contribution games mirrors truthful "
        "bidding behavior in sealed-bid second-price Vickrey auctions.")
    assert spec is not None
    assert spec["game"] == "vickrey"
    assert spec["design_only"] is False


def test_only_unbuilt_match_emits_design_only_stub():
    spec = _dispatch(
        "Free-riding in public goods contribution games increases with "
        "group size for LLM agents.")
    assert spec is not None
    assert spec["game"] == "public_goods"
    assert spec["design_only"] is True
    assert spec["experiment_id"] is None  # genuinely missing experiment
