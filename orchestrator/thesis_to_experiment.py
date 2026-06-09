"""Reverse-path constructor: surviving literature thesis -> experiment spec.

The forward LOOP_V0 path runs experiment -> analyze -> loop_bridge ->
run_iteration. This module is the reverse arrow (docs/
thesis_to_experiment_construction.md, Part 1): it takes a literature
*survivor* (novelty class novel/unclear, critic verdict "survives",
low_confidence false, no experiment_outcome) and deterministically
routes it onto a classical game with a known equilibrium, emitting the
pre-registered experiment spec that drives run.py/analyze.py.

Pure dispatch + spec emission: NO LLM call, NO model dependency, no
spine edits. The routing table is fixed (resist abstraction — this is
a dispatcher over six classical games, not a game synthesizer). The
tier registry is consulted READ-ONLY to decide built-vs-design-only.

Routing rule (deterministic, ranked): match thesis text + neighbor
titles against each row's keyword set, in table order; pick the FIRST
matching game that already has a built experiment (cheapest path);
if no match is built, emit the first match as a design-only spec that
names the missing experiment rather than coercing to the wrong game
(inviolate rule 4). No keyword match -> None: that thesis is not
constructible in the synthetic tier yet.
"""
from __future__ import annotations

from orchestrator import tier_registry

# Eligibility gate: only literature SURVIVORS get a constructed
# experiment. The critic verdict must be exactly "survives" — the new
# "undecidable" verdict fails closed here by construction, exactly like
# falsified/restated/malformed.
ELIGIBLE_NOVELTY = ("novel", "unclear")

# Fixed keyword -> game routing table, in design-doc order (the table in
# thesis_to_experiment_construction.md (a)). Each row carries the fixed
# spec parameters for its game: the treatment axis, opponent classes,
# primary metric, trial floor, the PRE-REGISTERED expected range, and
# the known-equilibrium anchor. experiment_id names the experiment dir
# that closes the row (None = genuinely missing, always design-only).
_GAMES: list[dict] = [
    {
        "game": "repeated_pd",
        "experiment_id": "exp001_repeated_pd",
        # PD-SPECIFIC tokens only (2026-06-09 review): bare cooperation
        # vocabulary ("cooperation", "defect", ...) also matches public
        # goods / stag hunt theses and, with repeated_pd first AND built,
        # would route them onto the wrong runnable game. Generic
        # cooperation words deliberately do NOT appear here.
        "keywords": ("repeated prisoner", "prisoner's dilemma",
                     "prisoners dilemma", "repeated pd", "iterated pd",
                     "tit-for-tat", "tit for tat", "grim trigger",
                     "history framing"),
        "treatment": {"factor": "history_framing",
                      "levels": ["list", "narrative"]},
        "opponent_classes": ["tft", "grim_trigger", "all_c", "all_d",
                             "mirror_llm"],
        "metric": "coop_rate",
        "n_trials": 50,
        "expected_range": {"primary": [0.60, 0.95],
                           "directional": "coop(narrative) > coop(list)"},
        "equilibrium_anchor": ("folk-theorem cooperation vs reciprocators; "
                               "defect vs all-D"),
    },
    {
        "game": "public_goods",
        "experiment_id": None,  # genuinely missing — always design-only
        "keywords": ("public goods", "free-riding", "free riding",
                     "conditional cooperation", "contribution"),
        "treatment": {"factor": "thesis_manipulation",
                      "levels": ["control", "treatment"]},
        "opponent_classes": ["self_play"],
        "metric": "mean_contribution_fraction",
        "n_trials": 50,
        "expected_range": {"primary": [0.0, 1.0],
                           "directional": ("contribution tracks the "
                                           "MPCR-dependent Nash prediction")},
        "equilibrium_anchor": ("MPCR-dependent Nash contribution "
                               "(interior or zero)"),
    },
    {
        "game": "stag_hunt",
        "experiment_id": None,  # genuinely missing — always design-only
        "keywords": ("stag hunt", "risk-dominance", "risk-dominant",
                     "payoff-dominance", "payoff-dominant", "coordination",
                     "equilibrium selection"),
        "treatment": {"factor": "thesis_manipulation",
                      "levels": ["control", "treatment"]},
        "opponent_classes": ["self_play"],
        "metric": "stag_rate",
        "n_trials": 50,
        "expected_range": {"primary": [0.0, 1.0],
                           "directional": ("equilibrium selection tracks "
                                           "risk dominance")},
        "equilibrium_anchor": ("risk-dominant vs payoff-dominant pure "
                               "equilibria"),
    },
    {
        "game": "cournot",
        # Limb F is building exp009_cournot; until it is registered in
        # tier_registry._TIER_MAP this row resolves design-only.
        "experiment_id": "exp009_cournot",
        "keywords": ("cournot", "duopoly", "oligopoly",
                     "quantity competition", "marginal cost",
                     "nash quantity"),
        "treatment": {"factor": "few_shot_marginal_cost",
                      "levels": ["absent", "explicit"]},
        "opponent_classes": ["self_play", "fixed_nash_responder"],
        "metric": "mean_abs_deviation_from_nash_quantity",
        "n_trials": 50,
        "expected_range": {"primary": [0.0, 0.15],
                           "directional": ("variance(explicit) < "
                                           "variance(absent)")},
        "equilibrium_anchor": "q_star = (a - c) / (3 b)",
    },
    {
        "game": "vickrey",
        "experiment_id": "exp003_vickrey_rediscovery",
        "keywords": ("vickrey", "second-price", "second price", "sealed-bid",
                     "sealed bid", "truthful bidding", "dominant strategy"),
        "treatment": {"factor": "thesis_manipulation",
                      "levels": ["control", "treatment"]},
        "opponent_classes": ["llm_bidders"],
        "metric": "truthful_bid_fraction",
        "n_trials": 50,
        "expected_range": {"primary": [0.75, 1.0],
                           "directional": ("truthful-bid fraction >= the "
                                           "pre-registered 0.75 threshold")},
        "equilibrium_anchor": ("truthful bidding is the dominant strategy "
                               "(Vickrey)"),
    },
    {
        "game": "combinatorial_vcg",
        "experiment_id": "exp004_combinatorial_auction",
        "keywords": ("combinatorial bid", "combinatorial auction", "bundle",
                     "vcg", "complementarity"),
        "treatment": {"factor": "thesis_manipulation",
                      "levels": ["control", "treatment"]},
        "opponent_classes": ["llm_bidders"],
        "metric": "efficiency",
        "n_trials": 50,
        "expected_range": {"primary": [0.75, 1.0],
                           "directional": ("truthful bundle bidding under "
                                           "VCG strategyproofness")},
        "equilibrium_anchor": ("VCG is strategyproof; truthful bundle "
                               "bids dominant"),
    },
]


def is_eligible(novelty_class: str | None, critic_verdict: str | None,
                low_confidence: bool) -> bool:
    """True iff the row is a literature survivor worth constructing for.

    "undecidable" (and falsified/restated/malformed) fail the
    `== "survives"` check — the gate fails closed.
    """
    return (novelty_class in ELIGIBLE_NOVELTY
            and critic_verdict == "survives"
            and not low_confidence)


def _is_built(experiment_id: str | None) -> bool:
    """READ-ONLY tier-registry consult: built = registered + run.py +
    loop_bridge.py present (analyze alone can't bridge the verdict back)."""
    if not experiment_id:
        return False
    try:
        entry = tier_registry.get_experiment(experiment_id)
    except KeyError:
        return False
    return bool(entry["has_run"] and entry["has_loop_bridge"])


def dispatch(thesis_text: str, novelty_class: str | None,
             critic_verdict: str | None, low_confidence: bool,
             neighbor_titles: list[str] | None = None, *,
             source_iteration_id: str | None = None) -> dict | None:
    """Route a surviving thesis onto a classical game; emit the spec.

    Returns the design-doc spec dict, or None when the thesis is
    ineligible or matches no game keyword (not constructible yet).
    """
    if not is_eligible(novelty_class, critic_verdict, low_confidence):
        return None
    haystack = " ".join([thesis_text or ""] + list(neighbor_titles or [])).lower()
    matches = [row for row in _GAMES
               if any(kw in haystack for kw in row["keywords"])]
    if not matches:
        return None
    chosen = next((row for row in matches if _is_built(row["experiment_id"])),
                  matches[0])
    design_only = not _is_built(chosen["experiment_id"])
    return {
        "source_iteration_id": source_iteration_id,
        "game": chosen["game"],
        "claim": thesis_text,  # verbatim — never paraphrased
        "treatment": dict(chosen["treatment"]),
        "opponent_classes": list(chosen["opponent_classes"]),
        "metric": chosen["metric"],
        "n_trials": chosen["n_trials"],
        "expected_range": dict(chosen["expected_range"]),
        "equilibrium_anchor": chosen["equilibrium_anchor"],
        "design_only": design_only,
        # additive convenience: which experiment dir closes (or would
        # close) this spec; None when the game has no named experiment.
        "experiment_id": chosen["experiment_id"],
    }
