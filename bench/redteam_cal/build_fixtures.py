"""Deterministic fixture resolver/generator — D-075 R1a redteam calibration.

Prereg: experiments/PREREG_redteam_cal_2026-08-18.md (v2). Every resolution
rule below is the prereg's verbatim locked intent:

Known-good (12):
  (a) the 2 distinct genuine historical proceeds — rule verbatim:
      ``redteam.verdict=="proceed" AND subagent_status=="passed"`` over
      memory/loop_memory.jsonl. The rule must yield EXACTLY
      {iter-2026-06-09-005, iter-2026-06-09-006, iter-2026-06-19-012};
      -006 is then DROPPED as the pinned 0.998-similarity near-duplicate
      of -005 (one judgment cannot consume two slots). Any other hit set
      is a resolution mismatch -> refuse loudly.
  (b) the exp003 Vickrey claim: loop_memory iter-2026-05-27-028 (the
      exp003 bridge iteration; its experiment_outcome must be the LOCKED
      confirming exp003_vickrey_rediscovery Verdict=YES record).
  (c) the 3 expected-survives battery cases novel_on_01/02/03 from
      experiments/lit_falsification_battery/cases.jsonl.
  (d) 6 constructed sound claims, register-matched, 25-45 words, >=2
      carrying a rescuable because/via/rather-than clause that states
      its own ablation (constants below; band enforced at build time).

Known-bad (12):
  (a) the iter-2026-08-18-005 attribution-confound claim (loop_memory;
      its own redteam catch — flagged NON-INDEPENDENT for arm 1).
  (b) 7 planted-flaw constructions, 7 DISTINCT flaw classes, register-
      matched (constants below).
  (c) the 2 nonsense battery cases from cases.jsonl.
  (d) the 2 historical INTRINSIC-flaw kills recorded in
      run_state/frontier_cluster_screen.jsonl: cl-iter-2026-06-05-005
      (mischaracterizes RDP composition; double veto) and
      cl-iter-2026-05-27-004 (mechanism logically insufficient). Their
      hypothesis texts are recovered from the matching loop_memory
      iterations. EXCLUDED per prereg: novelty-only vetoes, L0
      no-evidence-record vetoes, and empirical Verdict=NO refutations
      (a cleanly refuted claim was demonstrably testable).

Every label_rationale defends its label under the fatal-flaw definition
("cannot be rescued by any reasonable design"), never by provenance.

Determinism: rebuilding from the source stores yields byte-identical
fixtures.jsonl (sorted keys, ascii-escaped, fixed row order). Any
mismatch between a fresh resolution and an existing manifest refuses
loudly (ResolutionError / exit 1) — inviolate rule 4: never coerced.

Usage:
    python -m bench.redteam_cal.build_fixtures            # write (refuses to
                                                          #  silently overwrite
                                                          #  a differing file)
    python -m bench.redteam_cal.build_fixtures --check    # verify only
    python -m bench.redteam_cal.build_fixtures --force    # overwrite
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LOOP_MEMORY_PATH = REPO_ROOT / "memory" / "loop_memory.jsonl"
BATTERY_CASES_PATH = (
    REPO_ROOT / "experiments" / "lit_falsification_battery" / "cases.jsonl"
)
SCREEN_PATH = REPO_ROOT / "run_state" / "frontier_cluster_screen.jsonl"
FIXTURES_PATH = Path(__file__).resolve().parent / "fixtures.jsonl"

LABEL_GOOD = "known_good"
LABEL_BAD = "known_bad"

# Prereg-pinned resolution expectations.
PROCEED_RULE_EXPECTED = {
    "iter-2026-06-09-005",
    "iter-2026-06-09-006",
    "iter-2026-06-19-012",
}
NEAR_DUP_DROP = "iter-2026-06-09-006"  # pinned 0.998-similarity near-dup of -005
EXP003_ITER = "iter-2026-05-27-028"
CONFOUND_ITER = "iter-2026-08-18-005"
BATTERY_GOOD_CASES = (
    "novel_on_01_quant_lockin",
    "novel_on_02_critic_flip_model",
    "novel_on_03_levelk_quantal_bridge",
)
BATTERY_BAD_CASES = ("nonsense_01_word_salad", "nonsense_02_not_a_question")
SCREEN_KILLS = ("cl-iter-2026-06-05-005", "cl-iter-2026-05-27-004")

# Register band for constructed rows (prereg: 25-45 words).
REGISTER_MIN_WORDS, REGISTER_MAX_WORDS = 25, 45


class ResolutionError(RuntimeError):
    """A fixture failed to resolve/verify against its source store."""


def word_count(text: str) -> int:
    """Register-band word count: whitespace tokens containing at least one
    alphanumeric character (bare em-dashes are not words)."""
    return sum(1 for t in text.split() if any(c.isalnum() for c in t))


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        raise ResolutionError(f"source store missing: {path}")
    rows = []
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _loop_memory_by_id() -> dict[str, dict]:
    return {
        r.get("iteration_id"): r
        for r in _load_jsonl(LOOP_MEMORY_PATH)
        if r.get("iteration_id")
    }


def _recover_embedded_chosen(raw: str, iteration_id: str) -> str:
    """iter-2026-06-05-005 stored its hypothesis 'text' as an embedded
    JSON blob {"candidates": [...], "chosen": "..."} whose LaTeX
    (``$\\epsilon$``) makes it invalid strict JSON. Deterministic
    recovery: escape lone backslashes that are not already valid JSON
    escapes, parse, take "chosen"."""
    fixed = re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", raw)
    try:
        inner = json.loads(fixed)
    except json.JSONDecodeError as exc:
        raise ResolutionError(
            f"{iteration_id}: embedded hypothesis blob failed deterministic "
            f"recovery: {exc}"
        ) from exc
    chosen = inner.get("chosen")
    if not isinstance(chosen, str) or not chosen.strip():
        raise ResolutionError(
            f"{iteration_id}: embedded hypothesis blob has no 'chosen' text"
        )
    return chosen.strip()


# ---------------------------------------------------------------------------
# Resolvers (each verifies against its source store; refuses loudly on drift)
# ---------------------------------------------------------------------------

def _resolve_historical_proceeds(lm: dict[str, dict]) -> dict[str, str]:
    """Apply the verbatim rule and pin-check the hit set, then drop -006."""
    hits = {
        rid
        for rid, rec in lm.items()
        if (rec.get("redteam") or {}).get("verdict") == "proceed"
        and (rec.get("redteam") or {}).get("subagent_status") == "passed"
    }
    if hits != PROCEED_RULE_EXPECTED:
        raise ResolutionError(
            "historical-proceed rule (redteam.verdict=='proceed' AND "
            "subagent_status=='passed') resolved to "
            f"{sorted(hits)}, expected {sorted(PROCEED_RULE_EXPECTED)} — "
            "loop_memory has drifted from the prereg pin; REFUSING. "
            "A disputed manifest is fixed before lock, never coerced."
        )
    kept = sorted(hits - {NEAR_DUP_DROP})
    out = {}
    for rid in kept:
        text = ((lm[rid].get("hypothesis") or {}).get("text") or "").strip()
        if not text:
            raise ResolutionError(f"{rid}: empty hypothesis.text in loop_memory")
        out[rid] = text
    return out


def _resolve_exp003(lm: dict[str, dict]) -> str:
    rec = lm.get(EXP003_ITER)
    if rec is None:
        raise ResolutionError(f"{EXP003_ITER} not found in loop_memory")
    eo = rec.get("experiment_outcome") or {}
    if eo.get("experiment_id") != "exp003_vickrey_rediscovery":
        raise ResolutionError(
            f"{EXP003_ITER}: experiment_outcome.experiment_id is "
            f"{eo.get('experiment_id')!r}, expected 'exp003_vickrey_rediscovery'"
        )
    if not str(eo.get("summary", "")).startswith("Verdict=YES"):
        raise ResolutionError(
            f"{EXP003_ITER}: exp003 outcome is not the locked confirming "
            f"Verdict=YES record (summary={eo.get('summary')!r})"
        )
    text = ((rec.get("hypothesis") or {}).get("text") or "").strip()
    if not text:
        raise ResolutionError(f"{EXP003_ITER}: empty hypothesis.text")
    return text


def _resolve_confound(lm: dict[str, dict]) -> str:
    rec = lm.get(CONFOUND_ITER)
    if rec is None:
        raise ResolutionError(f"{CONFOUND_ITER} not found in loop_memory")
    rt = rec.get("redteam") or {}
    if rt.get("verdict") != "fatal_flaw" or rt.get("subagent_status") != "passed":
        raise ResolutionError(
            f"{CONFOUND_ITER}: expected its own redteam catch "
            "(verdict=='fatal_flaw', subagent_status=='passed'); got "
            f"verdict={rt.get('verdict')!r} status={rt.get('subagent_status')!r}"
        )
    text = ((rec.get("hypothesis") or {}).get("text") or "").strip()
    if not text:
        raise ResolutionError(f"{CONFOUND_ITER}: empty hypothesis.text")
    return text


def _resolve_battery_cases() -> dict[str, str]:
    by_id = {r.get("case_id"): r for r in _load_jsonl(BATTERY_CASES_PATH)}
    out = {}
    for cid in BATTERY_GOOD_CASES + BATTERY_BAD_CASES:
        rec = by_id.get(cid)
        if rec is None:
            raise ResolutionError(f"battery case {cid} not found in cases.jsonl")
        text = (rec.get("hypothesis") or "").strip()
        if not text:
            raise ResolutionError(f"battery case {cid}: empty hypothesis")
        out[cid] = text
    return out


def _resolve_screen_kills(lm: dict[str, dict]) -> dict[str, str]:
    """Verify the two pinned intrinsic-flaw kills exist in the frontier
    screen ledger with a methods veto, then recover their hypothesis
    texts from the matching loop_memory iterations."""
    screen_by_id = {}
    for rec in _load_jsonl(SCREEN_PATH):
        cid = rec.get("cluster_id")
        if cid:
            screen_by_id[cid] = rec
    out = {}
    for cid in SCREEN_KILLS:
        srec = screen_by_id.get(cid)
        if srec is None:
            raise ResolutionError(f"{cid} not found in frontier_cluster_screen")
        methods = ((srec.get("screen") or {}).get("methods") or {})
        if methods.get("verdict") != "veto":
            raise ResolutionError(
                f"{cid}: expected an intrinsic methods veto in the screen "
                f"record; got {methods.get('verdict')!r}"
            )
        iter_id = cid.removeprefix("cl-")
        lrec = lm.get(iter_id)
        if lrec is None:
            raise ResolutionError(
                f"{cid}: matching loop_memory iteration {iter_id} not found"
            )
        raw = ((lrec.get("hypothesis") or {}).get("text") or "").strip()
        if not raw:
            raise ResolutionError(f"{iter_id}: empty hypothesis.text")
        if raw.startswith("{"):
            out[cid] = _recover_embedded_chosen(raw, iter_id)
        else:
            out[cid] = raw
    return out


# ---------------------------------------------------------------------------
# Constructed rows (frozen constants — part of the locked manifest)
# ---------------------------------------------------------------------------

CONSTRUCTED_GOOD = [
    {
        "id": "rtc-good-cons-01",
        "hypothesis_text": (
            "In repeated public goods games between LLM agents, framing "
            "contributions as losses rather than gains lowers steady-state "
            "contribution rates via loss-averse response to the payoff "
            "description, an effect separable by holding numeric payoffs "
            "fixed while crossing only the frame wording."
        ),
        "mechanism_clause_rescuable": True,
        "label_rationale": (
            "Sound: the via-clause names its own rescue — crossing frame "
            "wording with numeric payoffs held fixed isolates the framing "
            "channel; the outcome (steady-state contribution rate) is "
            "measurable and the predicted direction is falsifiable."
        ),
    },
    {
        "id": "rtc-good-cons-02",
        "hypothesis_text": (
            "In one-shot ultimatum games, LLM proposers offer larger shares "
            "when the responder is described as another AI agent than as a "
            "human, because identity framing shifts fairness priors — an "
            "attribution isolable by swapping the single identity token "
            "between otherwise byte-identical prompts."
        ),
        "mechanism_clause_rescuable": True,
        "label_rationale": (
            "Sound: the because-clause states its own ablation — swapping "
            "the single identity token between otherwise byte-identical "
            "prompts isolates the attribution; offer size is directly "
            "measurable and the direction can fail."
        ),
    },
    {
        "id": "rtc-good-cons-03",
        "hypothesis_text": (
            "Gemma 4 26B-A4B agents in a ten-round repeated trust game "
            "return a larger share of the tripled transfer when the "
            "remaining-round count is displayed than when it is omitted, "
            "with the gap widening over the final three rounds."
        ),
        "mechanism_clause_rescuable": False,
        "label_rationale": (
            "Sound: a concrete two-condition comparison with a defined "
            "observable (returned share of the tripled transfer) and a "
            "specific temporal signature (widening over the final three "
            "rounds); falsifiable exactly as stated."
        ),
    },
    {
        "id": "rtc-good-cons-04",
        "hypothesis_text": (
            "In Cournot duopoly between LLM agents given an explicit linear "
            "demand schedule, average chosen quantities land closer to the "
            "Cournot-Nash prediction than to the collusive benchmark within "
            "five rounds, at decoding temperatures of both 0.2 and 0.8."
        ),
        "mechanism_clause_rescuable": False,
        "label_rationale": (
            "Sound: both benchmarks (Cournot-Nash and collusive quantities) "
            "are computable from the stated demand schedule, the distance "
            "comparison is measurable, and the temperature scope makes the "
            "claim concretely checkable."
        ),
    },
    {
        "id": "rtc-good-cons-05",
        "hypothesis_text": (
            "LLM bidders in first-price sealed-bid auctions shade bids "
            "further below valuation as the announced number of rival "
            "bidders falls, rather than applying a fixed markdown, a "
            "distinction testable by varying only the announced rival count "
            "while holding the valuation distribution constant."
        ),
        "mechanism_clause_rescuable": True,
        "label_rationale": (
            "Sound: the rather-than contrast names its own identifying "
            "manipulation — varying only the announced rival count with the "
            "valuation distribution held constant separates responsive "
            "shading from a fixed markdown."
        ),
    },
    {
        "id": "rtc-good-cons-06",
        "hypothesis_text": (
            "In repeated matching-pennies play, Gemma 4 agents' action "
            "sequences fail a runs test for randomness at decoding "
            "temperature 0.2 but pass it at temperature 1.0, with the "
            "low-temperature deviation concentrated in over-alternation "
            "between the two actions."
        ),
        "mechanism_clause_rescuable": False,
        "label_rationale": (
            "Sound: the runs test is a defined procedure, both temperature "
            "conditions are stated, and the over-alternation signature is a "
            "measurable, falsifiable refinement — a clean statistical test "
            "as phrased."
        ),
    },
]

CONSTRUCTED_BAD = [
    {
        "id": "rtc-bad-cons-01",
        "flaw_class": "circularity",
        "hypothesis_text": (
            "LLM agents cooperate more in repeated Prisoner's Dilemma when "
            "they have higher dispositional cooperativeness, where "
            "dispositional cooperativeness is operationalized as the "
            "agent's observed cooperation rate in repeated Prisoner's "
            "Dilemma under the same prompt and settings."
        ),
        "label_rationale": (
            "Planted flaw class: CIRCULARITY. The predictor is defined as "
            "the outcome itself, so the claim reduces to X correlates with "
            "X; no design can separate measured cause from measured effect "
            "because they are the same measurement — unrescuable."
        ),
    },
    {
        "id": "rtc-bad-cons-02",
        "flaw_class": "unfalsifiable_clause",
        "hypothesis_text": (
            "In repeated public goods games, LLM agents contribute "
            "according to a latent social preference that can manifest as "
            "generosity, free-riding, or any intermediate pattern depending "
            "on unobservable prompt resonance, so any observed contribution "
            "profile confirms the preference is operating."
        ),
        "label_rationale": (
            "Planted flaw class: UNFALSIFIABLE CLAUSE. The claim licenses "
            "every possible observation as confirmation; no outcome could "
            "disconfirm it, and no design creates an outcome space it "
            "forbids — unrescuable as stated."
        ),
    },
    {
        "id": "rtc-bad-cons-03",
        "flaw_class": "undefined_metric",
        "hypothesis_text": (
            "Across bargaining and negotiation games, Gemma 4 agents "
            "exhibit higher strategic authenticity than Qwen agents of "
            "comparable size, with the authenticity differential exceeding "
            "0.3 units on the standard strategic-authenticity scale at "
            "every tested temperature."
        ),
        "label_rationale": (
            "Planted flaw class: UNDEFINED METRIC. 'Strategic authenticity' "
            "and its 'standard scale' do not exist and the claim supplies "
            "no operationalization; a quantitative threshold on a "
            "nonexistent unit cannot be measured by any design without "
            "inventing a different claim."
        ),
    },
    {
        "id": "rtc-bad-cons-04",
        "flaw_class": "unrescuable_confound",
        "hypothesis_text": (
            "Raising decoding temperature from 0.2 to 1.0 increases "
            "defection rates among LLM agents in repeated Prisoner's "
            "Dilemma because higher temperature increases the agents' "
            "strategic risk appetite rather than merely adding noise to "
            "action sampling."
        ),
        "label_rationale": (
            "Planted flaw class: UNRESCUABLE CONFOUND. The only "
            "manipulation the claim admits (temperature) changes "
            "action-sampling noise by definition, so the rather-than "
            "attribution pits a mechanism against a definitional "
            "consequence of the same knob; no design that manipulates "
            "temperature can separate them."
        ),
    },
    {
        "id": "rtc-bad-cons-05",
        "flaw_class": "theorem_contradiction",
        "hypothesis_text": (
            "In one-shot second-price sealed-bid auctions with independent "
            "private values, LLM bidders who bid strictly above their "
            "valuations earn higher expected profit than truthful bidders, "
            "because overbidding captures winning opportunities that "
            "truthful bidding forgoes at no added cost."
        ),
        "label_rationale": (
            "Planted flaw class: THEOREM CONTRADICTION. Truthful bidding "
            "weakly dominates in a second-price IPV auction (Vickrey); the "
            "extra wins from overbidding occur exactly when the price "
            "exceeds valuation, so the predicted profit ranking contradicts "
            "the theorem for any agent population — no design rescues an "
            "impossible expectation."
        ),
    },
    {
        "id": "rtc-bad-cons-06",
        "flaw_class": "internal_contradiction",
        "hypothesis_text": (
            "In a strictly one-shot Prisoner's Dilemma where both LLM "
            "agents are verified to comply with an instruction to play "
            "their dominant action, mutual cooperation nevertheless emerges "
            "in the majority of trials because compliance leaves room for "
            "anticipatory reciprocity."
        ),
        "label_rationale": (
            "Planted flaw class: INTERNAL CONTRADICTION. The premise "
            "(verified play of the dominant action, i.e. defection) "
            "logically excludes the predicted outcome (mutual cooperation); "
            "the claim asserts P and not-P about the same trials, and no "
            "experimental design can instantiate a contradiction."
        ),
    },
    {
        "id": "rtc-bad-cons-07",
        "flaw_class": "unobservable_construct",
        "hypothesis_text": (
            "Cooperation between LLM agents in repeated games is driven by "
            "each model's phenomenal empathy — what the exchange "
            "subjectively feels like to the network — a quantity the claim "
            "itself stipulates no behavioral or activation measurement can "
            "access even in principle."
        ),
        "label_rationale": (
            "Planted flaw class: UNOBSERVABLE CONSTRUCT. The proposed cause "
            "is stipulated to be inaccessible to any measurement in "
            "principle, so no design can couple it to data; the claim "
            "forecloses its own test by construction — unrescuable without "
            "replacing the construct."
        ),
    },
]


# ---------------------------------------------------------------------------
# Manifest assembly
# ---------------------------------------------------------------------------

def build_manifest() -> list[dict]:
    """Resolve + construct the 24 rows in canonical order. Refuses loudly
    (ResolutionError) on any drift between the source stores and the
    prereg pins."""
    lm = _loop_memory_by_id()
    proceeds = _resolve_historical_proceeds(lm)
    exp003_text = _resolve_exp003(lm)
    confound_text = _resolve_confound(lm)
    battery = _resolve_battery_cases()
    kills = _resolve_screen_kills(lm)

    rows: list[dict] = []

    # -- known-good: real-historical ------------------------------------
    rows.append({
        "id": "rtc-good-hist-01",
        "hypothesis_text": proceeds["iter-2026-06-09-005"],
        "label": LABEL_GOOD,
        "provenance": {
            "class": "real-historical",
            "source": "memory/loop_memory.jsonl",
            "source_id": "iter-2026-06-09-005",
            "resolution_rule": (
                "redteam.verdict=='proceed' AND subagent_status=='passed'; "
                "pinned near-duplicate of this row dropped per prereg so one "
                "judgment cannot consume two slots"
            ),
        },
        "label_rationale": (
            "Sound on its merits: a fully specified game (integer range, "
            "2/3-of-mean winner rule, explicit no-priming condition) with a "
            "distributional prediction separating three concrete outcomes "
            "(20-40 band vs Nash 0 vs uniform/50), directly measurable. The "
            "residual memorization worry is interpretive and rescuable by "
            "design (paraphrase probes), not fatal."
        ),
    })
    rows.append({
        "id": "rtc-good-hist-02",
        "hypothesis_text": proceeds["iter-2026-06-19-012"],
        "label": LABEL_GOOD,
        "provenance": {
            "class": "real-historical",
            "source": "memory/loop_memory.jsonl",
            "source_id": "iter-2026-06-19-012",
            "resolution_rule": (
                "redteam.verdict=='proceed' AND subagent_status=='passed'"
            ),
        },
        "label_rationale": (
            "Sound on its merits: states a payoff-differential mechanism "
            "and treats the second-order punishment cost as a measurable "
            "variable rather than a hand-wave; falsifiable by direct "
            "payoff-matrix manipulation; contradicts no established result "
            "— it sharpens one."
        ),
    })
    rows.append({
        "id": "rtc-good-hist-03",
        "hypothesis_text": exp003_text,
        "label": LABEL_GOOD,
        "provenance": {
            "class": "real-historical",
            "source": "memory/loop_memory.jsonl",
            "source_id": EXP003_ITER,
            "resolution_rule": (
                "exp003 Vickrey bridge iteration carrying the LOCKED "
                "confirming experiment_outcome (exp003_vickrey_rediscovery, "
                "Verdict=YES)"
            ),
        },
        "label_rationale": (
            "Testable to the point of having been tested: the claim names a "
            "fully specified mechanism, population, and a measurable "
            "outcome (truthful-bid fraction at a stated tolerance); a "
            "confirming LOCKED experiment proves testability — the benign "
            "direction of outcome-labeling. The label rests on demonstrated "
            "operationalizability, not on the positive result."
        ),
    })

    # -- known-good: battery ---------------------------------------------
    battery_good_rationales = {
        "novel_on_01_quant_lockin": (
            "Sound on its merits: names the substrate pair (NVFP4 vs BF16 "
            "Gemma 4), pins opponent and prompt, and makes two "
            "quantitatively separated predictions (lock at 1.00 vs a "
            "0.85-0.95 band); directly testable and contradicts no known "
            "result — precision-sensitivity of strategic behavior is open."
        ),
        "novel_on_02_critic_flip_model": (
            "Sound on its merits: a directional, operationalizable "
            "comparison (falsification rate under cross-family vs "
            "same-family critic) with a stated mechanism (non-shared blind "
            "spots) isolable by holding the generator fixed and swapping "
            "only the critic family. Historically over-gated at R0 — "
            "adversarially useful, but the label stands on the design's "
            "identifiability."
        ),
        "novel_on_03_levelk_quantal_bridge": (
            "Sound on its merits: both linkages are measurable (level-k "
            "assignment from guessing-game choices; temperature-to-lambda "
            "via quantal-response fits), monotonicity gives a crisp failure "
            "mode, and nothing established is contradicted."
        ),
    }
    for i, cid in enumerate(BATTERY_GOOD_CASES, start=1):
        rows.append({
            "id": f"rtc-good-batt-{i:02d}",
            "hypothesis_text": battery[cid],
            "label": LABEL_GOOD,
            "provenance": {
                "class": "battery",
                "source": "experiments/lit_falsification_battery/cases.jsonl",
                "source_id": cid,
            },
            "label_rationale": battery_good_rationales[cid],
        })

    # -- known-good: constructed ------------------------------------------
    for c in CONSTRUCTED_GOOD:
        rows.append({
            "id": c["id"],
            "hypothesis_text": c["hypothesis_text"],
            "label": LABEL_GOOD,
            "provenance": {
                "class": "constructed",
                "source": (
                    "constructed at lock for this battery (register-matched "
                    "sound claim, 25-45 words)"
                ),
                "mechanism_clause_rescuable": c["mechanism_clause_rescuable"],
            },
            "label_rationale": c["label_rationale"],
        })

    # -- known-bad: real-historical ----------------------------------------
    rows.append({
        "id": "rtc-bad-hist-01",
        "hypothesis_text": confound_text,
        "label": LABEL_BAD,
        "provenance": {
            "class": "real-historical",
            "source": "memory/loop_memory.jsonl",
            "source_id": CONFOUND_ITER,
            "non_independent_arm1": True,  # gemma-current's own 3-day-old catch
        },
        "label_rationale": (
            "Unrescuable attribution confound on the merits: the sole "
            "manipulated variable (context length) moves both candidate "
            "mechanisms — retrieval 'attention noise' and strategic "
            "capacity — together, so the rather-than attribution has no "
            "identifying intervention under any reasonable design that "
            "manipulates context length; as phrased the claim cannot be "
            "rescued, only replaced."
        ),
    })
    rows.append({
        "id": "rtc-bad-hist-02",
        "hypothesis_text": kills["cl-iter-2026-06-05-005"],
        "label": LABEL_BAD,
        "provenance": {
            "class": "real-historical",
            "source": (
                "run_state/frontier_cluster_screen.jsonl (double veto); text "
                "recovered from memory/loop_memory.jsonl iter-2026-06-05-005"
            ),
            "source_id": "cl-iter-2026-06-05-005",
        },
        "label_rationale": (
            "Category error contradicting an established result: RDP "
            "composition already tracks the log-moments the claim "
            "attributes uniquely to the Moments Accountant (Mironov 2017 "
            "subsumes the moments accountant within Renyi accounting), so "
            "the claimed tightness advantage compares a quantity to itself; "
            "no experimental design can rescue a comparison whose two arms "
            "are the same object."
        ),
    })
    rows.append({
        "id": "rtc-bad-hist-03",
        "hypothesis_text": kills["cl-iter-2026-05-27-004"],
        "label": LABEL_BAD,
        "provenance": {
            "class": "real-historical",
            "source": (
                "run_state/frontier_cluster_screen.jsonl (methods veto); text "
                "recovered from memory/loop_memory.jsonl iter-2026-05-27-004"
            ),
            "source_id": "cl-iter-2026-05-27-004",
        },
        "label_rationale": (
            "Mechanism logically insufficient: a Bayesian updater facing "
            "mean-zero observation noise forms unbiased beliefs about "
            "others' contributions, so the stated mechanism cannot generate "
            "the predicted systematically faster decay without an unstated "
            "asymmetry the claim neither names nor controls; the "
            "directional prediction is a non sequitur from the premises and "
            "cannot be rescued as stated."
        ),
    })

    # -- known-bad: battery ---------------------------------------------
    battery_bad_rationales = {
        "nonsense_01_word_salad": (
            "No coherent proposition is asserted: the string name-drops "
            "game-theory terms without a subject-mechanism-outcome "
            "structure, so there is nothing to operationalize, no "
            "prediction to test, and nothing a design could rescue — a "
            "claim must first exist."
        ),
        "nonsense_02_not_a_question": (
            "A definitional truism, not a hypothesis: it asserts an "
            "uncontested fact about textbooks and teaching with no "
            "variable, no comparison, and no predicted outcome; it is "
            "unfalsifiable as stated, and any 'rescue' would be the "
            "invention of a different claim."
        ),
    }
    for i, cid in enumerate(BATTERY_BAD_CASES, start=1):
        rows.append({
            "id": f"rtc-bad-batt-{i:02d}",
            "hypothesis_text": battery[cid],
            "label": LABEL_BAD,
            "provenance": {
                "class": "battery",
                "source": "experiments/lit_falsification_battery/cases.jsonl",
                "source_id": cid,
            },
            "label_rationale": battery_bad_rationales[cid],
        })

    # -- known-bad: constructed (7 distinct planted flaw classes) --------
    for c in CONSTRUCTED_BAD:
        rows.append({
            "id": c["id"],
            "hypothesis_text": c["hypothesis_text"],
            "label": LABEL_BAD,
            "provenance": {
                "class": "constructed",
                "source": (
                    "constructed at lock for this battery (register-matched "
                    "planted flaw)"
                ),
                "flaw_class": c["flaw_class"],
            },
            "label_rationale": c["label_rationale"],
        })

    _self_check(rows)
    return rows


def _self_check(rows: list[dict]) -> None:
    """Build-time integrity gates (inviolate rule 4: each stands alone;
    a violation refuses the build rather than emitting a bad manifest)."""
    if len(rows) != 24:
        raise ResolutionError(f"manifest has {len(rows)} rows, expected 24")
    ids = [r["id"] for r in rows]
    if len(set(ids)) != 24:
        raise ResolutionError("duplicate fixture ids in manifest")
    n_good = sum(1 for r in rows if r["label"] == LABEL_GOOD)
    n_bad = sum(1 for r in rows if r["label"] == LABEL_BAD)
    if (n_good, n_bad) != (12, 12):
        raise ResolutionError(f"label split {n_good}/{n_bad}, expected 12/12")
    for r in rows:
        if not str(r.get("label_rationale", "")).strip():
            raise ResolutionError(f"{r['id']}: empty label_rationale")
        if not str(r.get("hypothesis_text", "")).strip():
            raise ResolutionError(f"{r['id']}: empty hypothesis_text")
        if r["provenance"]["class"] == "constructed":
            wc = word_count(r["hypothesis_text"])
            if not (REGISTER_MIN_WORDS <= wc <= REGISTER_MAX_WORDS):
                raise ResolutionError(
                    f"{r['id']}: constructed row is {wc} words, outside the "
                    f"{REGISTER_MIN_WORDS}-{REGISTER_MAX_WORDS} register band"
                )
    # >=2 constructed sound claims carry a rescuable mechanism clause.
    n_clause = sum(
        1 for r in rows
        if r["provenance"].get("mechanism_clause_rescuable") is True
    )
    if n_clause < 2:
        raise ResolutionError(
            f"only {n_clause} constructed sound claims carry a rescuable "
            "mechanism-attribution clause; prereg requires >=2"
        )
    # 7 distinct planted flaw classes.
    classes = [
        r["provenance"]["flaw_class"] for r in rows
        if "flaw_class" in r["provenance"]
    ]
    if len(classes) != 7 or len(set(classes)) != 7:
        raise ResolutionError(
            f"planted flaw classes not 7-distinct: {classes}"
        )


def serialize(rows: list[dict]) -> str:
    return "".join(
        json.dumps(r, sort_keys=True, ensure_ascii=True) + "\n" for r in rows
    )


def load_manifest(path: Path = FIXTURES_PATH) -> list[dict]:
    return _load_jsonl(path)


def verify_manifest(rows: list[dict]) -> None:
    """Compare a manifest against a fresh resolution from the source
    stores. Any difference is a resolution mismatch -> refuse loudly."""
    fresh = build_manifest()
    if rows != fresh:
        fresh_by_id = {r["id"]: r for r in fresh}
        for r in rows:
            f = fresh_by_id.get(r["id"])
            if f is None:
                raise ResolutionError(
                    f"manifest row {r['id']} has no fresh-resolution match"
                )
            if r != f:
                diff_keys = [k for k in f if r.get(k) != f.get(k)]
                raise ResolutionError(
                    f"manifest row {r['id']} diverges from its source store "
                    f"on {diff_keys}; REFUSING (fixtures are frozen at lock "
                    "and must re-verify byte-for-byte)"
                )
        raise ResolutionError(
            "manifest diverges from fresh resolution (row set/order mismatch)"
        )


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    check_only = "--check" in args
    force = "--force" in args

    try:
        rows = build_manifest()
    except ResolutionError as exc:
        print(f"RESOLUTION MISMATCH — refusing: {exc}", file=sys.stderr)
        return 1

    payload = serialize(rows)
    if FIXTURES_PATH.exists():
        existing = FIXTURES_PATH.read_text()
        if existing == payload:
            print(f"fixtures.jsonl verified: {len(rows)} rows, byte-identical "
                  "to fresh resolution")
            return 0
        if check_only or not force:
            print(
                "REFUSING: bench/redteam_cal/fixtures.jsonl exists and "
                "DIFFERS from a fresh resolution. The manifest is frozen at "
                "lock; inspect the divergence (--check) or overwrite "
                "explicitly with --force.",
                file=sys.stderr,
            )
            return 1
    elif check_only:
        print("REFUSING --check: fixtures.jsonl does not exist", file=sys.stderr)
        return 1

    FIXTURES_PATH.write_text(payload)
    print(f"wrote {FIXTURES_PATH} ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
