#!/usr/bin/env python3
"""exp001 — narrative-vs-list history-framing analysis (pre-registered).

Tests thesis iter-2026-05-27-001: "LLM agents in a repeated Prisoner's
Dilemma will exhibit significantly higher cooperation rates when the
history of interactions is presented as a cohesive narrative compared
to a structured list of move sequences."

Inputs are two run.py output dirs, one per arm:

    results/narrative/summary.json   (run.py --rules-variant narrative)
    results/list/summary.json        (run.py --rules-variant list)

Per-arm cooperation rate = unweighted mean of llm_coop_rate across the
arm's opponents (each opponent plays the same number of rounds, so the
unweighted mean equals the round-weighted mean on the standard plan).

Pre-registered verdict (constants below, fixed BEFORE any arm data
exist): Verdict=YES iff coop(narrative) - coop(list) >= 0.10.

Threshold rationale: the thesis claims "significantly higher"
cooperation, not merely nonzero. Baseline exp001 runs (results/
summary.json) sit at/near coop saturation vs reciprocators with
per-arm sampling noise well under 0.05 absolute at 500 rounds, so a
+0.10 absolute gap clears the noise floor with margin and matches the
magnitude treated as meaningful in the archived Horton-style expected
range (~0.60-0.95 vs reciprocators). The comparison is raw (no
rounding); "below threshold but close" is a NO (inviolate rule 4).

Writes results/summary.md containing the exact token Verdict=YES or
Verdict=NO (the same token finding_promotion._SURPRISE_RE keys on).

Run:
    ./.venv-chroma/bin/python experiments/exp001_repeated_pd/analyze.py
"""
from __future__ import annotations

import json
from pathlib import Path
from statistics import mean

EXP_DIR = Path(__file__).resolve().parent
NARRATIVE_SUMMARY_JSON = EXP_DIR / "results" / "narrative" / "summary.json"
LIST_SUMMARY_JSON = EXP_DIR / "results" / "list" / "summary.json"
SUMMARY_PATH = EXP_DIR / "results" / "summary.md"

# PRE-REGISTERED (see module docstring for rationale; do not tune
# post-hoc): YES iff coop(narrative) - coop(list) >= VERDICT_THRESHOLD.
VERDICT_THRESHOLD = 0.10
METRIC_NAME = "narrative_minus_list_cooperation"


def _load_arm(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(
            f"FATAL: {path} does not exist — run run.py with "
            "--rules-variant narrative|list and the matching --output-dir first"
        )
    with open(path) as fh:
        return json.load(fh)


def arm_coop_rate(summary: dict) -> float:
    """Unweighted mean LLM cooperation rate across the arm's opponents."""
    per_opp = summary.get("per_opponent") or []
    rates = [o["llm_coop_rate"] for o in per_opp if "llm_coop_rate" in o]
    if not rates:
        raise SystemExit("FATAL: summary.json has no per_opponent coop rates")
    return mean(rates)


def verdict_for(narrative_rate: float, list_rate: float) -> tuple[str, float]:
    """Pre-registered verdict + delta.

    The comparison is done in EXACT decimal arithmetic (Fraction over the
    float's decimal rendering) so a true boundary delta (e.g. 0.71 - 0.61)
    cannot verdict NO via binary-float subtraction error (0.0999...98 < 0.10).
    Fixed 2026-06-09 pre-data (no narrative/list arm has ever been run), so
    the pre-registration is unchanged in meaning: YES iff delta >= 0.10.
    """
    from fractions import Fraction
    d = Fraction(repr(narrative_rate)) - Fraction(repr(list_rate))
    return ("YES" if d >= Fraction("0.10") else "NO"), float(d)


def main() -> int:
    narrative = _load_arm(NARRATIVE_SUMMARY_JSON)
    listed = _load_arm(LIST_SUMMARY_JSON)
    nar_rate = arm_coop_rate(narrative)
    lst_rate = arm_coop_rate(listed)
    verdict, delta = verdict_for(nar_rate, lst_rate)
    total_rounds = (int(narrative.get("total_rounds") or 0)
                    + int(listed.get("total_rounds") or 0))

    body = [
        "# exp001 — narrative-vs-list history framing summary",
        "",
        f"Verdict={verdict} — narrative-framed history "
        f"{'DID' if verdict == 'YES' else 'DID NOT'} raise LLM cooperation "
        f"by at least {VERDICT_THRESHOLD:.2f} (absolute) over list-framed "
        "history in repeated PD (thesis iter-2026-05-27-001).",
        "",
        "## Headline metrics",
        "",
        f"- coop_rate(narrative): {nar_rate:.4f}",
        f"- coop_rate(list): {lst_rate:.4f}",
        f"- delta(narrative - list): {delta:+.4f}",
        f"- total rounds (both arms): {total_rounds}",
        f"- opponents(narrative): "
        f"{[o.get('opponent') for o in narrative.get('per_opponent', [])]}",
        f"- opponents(list): "
        f"{[o.get('opponent') for o in listed.get('per_opponent', [])]}",
        "",
        "## Verdict threshold (pre-registered)",
        "",
        f"YES iff coop_rate(narrative) - coop_rate(list) >= "
        f"{VERDICT_THRESHOLD:.2f}. Raw comparison; below-but-close is NO.",
        "",
    ]
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text("\n".join(body))
    print(f"wrote {SUMMARY_PATH}")
    print(f"verdict: {verdict} (delta={delta:+.4f}, "
          f"threshold={VERDICT_THRESHOLD:.2f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
