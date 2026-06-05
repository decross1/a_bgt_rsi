#!/usr/bin/env python3
"""Step 5 cross-MECHANISM replication driver (synthetic tier only).

NOTE ON SCOPE: this is HONESTLY a cross-MECHANISM stand-in *within the
synthetic tier* — there is no semi-synthetic rung in the apparatus yet,
so this is NOT a true cross-tier replication. It compares two synthetic
sandbox experiments (exp001 repeated PD, exp003 Vickrey auction) against
one shared claim and reports whether they agree. When they disagree the
disagreement is recorded as a DIAGNOSTIC SIGNAL, never silently discarded.

Shared claim:
  "an unprimed LLM rediscovers the game-theoretic equilibrium of a
   mechanism it was not told about."

Reader/bridge pattern (build_comparison + --dry-run/--live argparse +
run_iteration import) is copied from
experiments/exp003_vickrey_rediscovery/loop_bridge.py.

Two modes:
  --dry-run (default) : print the cross_tier_comparison dict as JSON,
                        make NO LLM call. Safe under MOCK_LLM.
  --live              : thread the dict into a LOOP_V0 iteration via
                        orchestrator.nara.run_iteration (needs a live
                        backend; run under `env -u MOCK_LLM`).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

EXP_DIR = Path(__file__).resolve().parent
PD_SUMMARY = EXP_DIR / "exp001_repeated_pd" / "results" / "summary.json"
VICKREY_SUMMARY = EXP_DIR / "exp003_vickrey_rediscovery" / "results" / "summary.md"
COMBINATORIAL_SUMMARY = (
    EXP_DIR / "exp004_combinatorial_auction" / "results" / "summary.json"
)

CLAIM = (
    "an unprimed LLM rediscovers the game-theoretic equilibrium of a "
    "mechanism it was not told about."
)

# The cross-RUNG claim: same rediscovery, escalated along auction COMPLEXITY
# (single-item second-price -> combinatorial VCG). Still the synthetic tier;
# this is an honest cross-mechanism-FAMILY upgrade, NOT a cross-tier leap.
CROSS_RUNG_CLAIM = (
    "an unprimed LLM rediscovers strategyproof truthful bidding across "
    "auction COMPLEXITY (single-item -> combinatorial)."
)


def _pd_adapter(summary_path: Path) -> dict:
    """Map exp001 repeated-PD summary.json -> a one-mechanism claim record.

    Tiny, PD-specific. The equilibrium signature of a strategically-aware
    player in repeated PD is: cooperate with reciprocating opponents
    (tft/grim_trigger/all_c/mirror_llm ~ full coop) AND defect markedly
    more against an unconditional defector (all_d). "supports" iff both
    hold: reciprocator coop is high and all_d coop is clearly lower.
    """
    data = json.loads(summary_path.read_text())
    by_opp = {row["opponent"]: row["llm_coop_rate"] for row in data["per_opponent"]}
    reciprocators = [
        by_opp[o] for o in ("tft", "grim_trigger", "all_c", "mirror_llm") if o in by_opp
    ]
    recip_min = min(reciprocators) if reciprocators else 0.0
    all_d_coop = by_opp.get("all_d", 1.0)
    # equilibrium play: cooperate with reciprocators, punish all_d
    value = recip_min - all_d_coop
    supports = recip_min >= 0.9 and all_d_coop <= 0.5
    return {
        "experiment": "exp001_repeated_pd",
        "metric": "reciprocator_coop_minus_all_d_coop",
        "value": value,
        "supports": supports,
    }


def _vickrey_adapter(summary_path: Path) -> dict:
    """Map exp003 Vickrey summary.md -> a one-mechanism claim record.

    Tiny, Vickrey-specific. "supports" iff the truthful-bid fraction at
    eps=5 meets the pre-registered 0.75 threshold.
    """
    needle = "Truthful fraction at eps=5.0: "
    fraction = None
    for line in summary_path.read_text().splitlines():
        if needle in line:
            # "- Truthful fraction at eps=5.0: 50/50 (100.0%)"
            pct = line.split(needle, 1)[1].split("(", 1)[1].rstrip().rstrip(")")
            fraction = float(pct.rstrip("%")) / 100.0
            break
    if fraction is None:
        raise SystemExit(f"FATAL: could not parse truthful fraction from {summary_path}")
    return {
        "experiment": "exp003_vickrey_rediscovery",
        "metric": "truthful_bid_fraction",
        "value": fraction,
        "supports": fraction >= 0.75,
    }


def _combinatorial_adapter(summary_json_path: Path) -> dict:
    """Map exp004 summary.json -> a one-mechanism claim record.

    Tiny, exp004-specific. The cross-rung signal is the VCG mechanism's
    truthful-bid fraction (VCG is the strategyproof anchor). "supports"
    iff that fraction meets the pre-registered 0.75 threshold.
    """
    data = json.loads(Path(summary_json_path).read_text())
    vcg = None
    for m in data.get("per_mechanism", []):
        if m.get("mechanism") == "vcg":
            vcg = m
            break
    if vcg is None:
        raise SystemExit(
            f"FATAL: no 'vcg' mechanism in {summary_json_path} per_mechanism"
        )
    fraction = float(vcg["truthful_fraction"])
    return {
        "experiment": "exp004_combinatorial_auction",
        "metric": "vcg_truthful_fraction",
        "value": fraction,
        "supports": fraction >= 0.75,
    }


def build_comparison(summary_a_path, summary_b_path) -> dict:
    """Read the two synthetic-tier summaries and build the
    cross_tier_comparison dict. mechanism_a := PD, mechanism_b := Vickrey."""
    a = _pd_adapter(Path(summary_a_path))
    b = _vickrey_adapter(Path(summary_b_path))
    agreement = a["supports"] == b["supports"]
    if agreement:
        note = (
            f"Both mechanisms agree (supports={a['supports']}); the shared "
            "claim replicates across these two synthetic-tier mechanisms."
        )
    else:
        note = (
            "DIAGNOSTIC SIGNAL — mechanisms DISAGREE on the shared claim: "
            f"{a['experiment']} supports={a['supports']} but "
            f"{b['experiment']} supports={b['supports']}. Not discarded; "
            "recorded for follow-up on what differs between the mechanisms."
        )
    return {
        "claim": CLAIM,
        "mechanism_a": a,
        "mechanism_b": b,
        "agreement": agreement,
        "diagnostic_note": note,
    }


def build_cross_rung_comparison(
    vickrey_summary_path=VICKREY_SUMMARY,
    combinatorial_summary_path=COMBINATORIAL_SUMMARY,
) -> dict:
    """Compare rung-1 (exp003 Vickrey single-item second-price truthful) vs
    rung-2 (exp004 combinatorial VCG truthful) on the shared CROSS_RUNG_CLAIM.

    This is an honest cross-mechanism-FAMILY upgrade along auction COMPLEXITY
    — both rungs live in the SYNTHETIC tier (there is no semi-synthetic rung
    in the apparatus yet). When the rungs disagree the disagreement is a
    DIAGNOSTIC SIGNAL, never silently discarded.
    """
    rung_1 = _vickrey_adapter(Path(vickrey_summary_path))
    rung_2 = _combinatorial_adapter(Path(combinatorial_summary_path))
    agreement = rung_1["supports"] == rung_2["supports"]
    if agreement:
        note = (
            f"Both rungs agree (supports={rung_1['supports']}); strategyproof "
            "truthful bidding replicates across auction complexity "
            "(single-item second-price -> combinatorial VCG), within the "
            "synthetic tier."
        )
    else:
        note = (
            "DIAGNOSTIC SIGNAL — rungs DISAGREE on the shared claim: "
            f"{rung_1['experiment']} supports={rung_1['supports']} but "
            f"{rung_2['experiment']} supports={rung_2['supports']}. Not "
            "discarded; recorded for follow-up on whether combinatorial "
            "complexity breaks the single-item rediscovery."
        )
    return {
        "claim": CROSS_RUNG_CLAIM,
        "tier": "synthetic (cross-mechanism-family, NOT cross-tier)",
        "rung_1": rung_1,
        "rung_2": rung_2,
        "agreement": agreement,
        "diagnostic_note": note,
    }


def build_topic_seed(comparison: dict) -> str:
    a, b = comparison["mechanism_a"], comparison["mechanism_b"]
    return (
        "Across two unrelated synthetic game-theoretic mechanisms (repeated "
        "prisoner's dilemma and a sealed-bid second-price auction), an "
        "unprimed LLM rediscovers the equilibrium strategy it was not told "
        f"about (PD supports={a['supports']}, Vickrey supports="
        f"{b['supports']}, agreement={comparison['agreement']})."
    )


def build_cross_rung_topic_seed(comparison: dict) -> str:
    r1, r2 = comparison["rung_1"], comparison["rung_2"]
    return (
        "Escalating auction COMPLEXITY within the synthetic tier (single-item "
        "second-price -> two-item combinatorial VCG), an unprimed LLM "
        "rediscovers strategyproof truthful bidding it was not told about "
        f"(Vickrey supports={r1['supports']}, combinatorial-VCG supports="
        f"{r2['supports']}, agreement={comparison['agreement']})."
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true", default=True,
                   help="print the comparison dict, make no LLM call (default)")
    p.add_argument("--live", dest="dry_run", action="store_false",
                   help="thread the comparison into run_iteration")
    p.add_argument("--cross-rung", action="store_true", default=False,
                   help="compare rung-1 (exp003 Vickrey) vs rung-2 (exp004 "
                        "combinatorial VCG) on truthful bidding across auction "
                        "complexity, instead of the PD×Vickrey comparison")
    args = p.parse_args(argv)

    if args.cross_rung:
        comparison = build_cross_rung_comparison(
            VICKREY_SUMMARY, COMBINATORIAL_SUMMARY
        )
        topic = build_cross_rung_topic_seed(comparison)
    else:
        comparison = build_comparison(PD_SUMMARY, VICKREY_SUMMARY)
        topic = build_topic_seed(comparison)

    print("=== replication_driver (cross-MECHANISM, synthetic tier) ===")
    print()
    print("cross_tier_comparison:")
    print(json.dumps(comparison, indent=2))
    print()

    if args.dry_run:
        print("[dry-run] not calling run_iteration. Pass --live to run.")
        return 0

    from orchestrator.nara import run_iteration

    print("=== running LOOP_V0 iteration with the comparison ===")
    record = run_iteration(
        topic=topic,
        source="human_cli",
        cross_tier_comparison=comparison,
    )
    print(f"iteration_id: {record.get('iteration_id')}")
    print(f"journal_entry_path: {record.get('journal_entry_path')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
