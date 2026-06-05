#!/usr/bin/env python3
"""exp006 — analyze trials.jsonl into a mechanism-DESIGN verdict.

This IS the semi-synthetic mechanism-DESIGN tier (labelled honestly): the
LLM designed each mechanism (allocation + payments) and every design was
scored against the VCG benchmark. There is no single ground-truth output;
the metrics measure how close the LLM's self-authored mechanisms get to the
known optimum.

Reads ``results/trials.jsonl`` (written by run.py) and writes
``results/summary.md`` + ``results/summary.json`` with:
  - mean allocative_efficiency of the LLM-designed mechanisms,
  - feasibility_rate (fraction of designs that sell each item at most once
    with valid bundles/indices; parse failures count as INfeasible),
  - matches_vcg_rate (fraction whose allocation equals VCG's),
  - a top-line verdict.

Verdict (pre-registered):
  - YES   iff mean_efficiency >= 0.90 AND feasibility_rate >= 0.90
            (the LLM designs near-optimal, feasible mechanisms),
  - INVALID iff feasibility_rate < 0.50 — so many designs failed to parse
            or were infeasible that the efficiency mean is unreliable and
            no near-optimality claim can stand. The mean is NOT coerced into
            a pass or a clean NO; the unreliability is surfaced.
  - NO    otherwise.

Note the efficiency mean is computed over ALL successful trials (feasible
or not), so an infeasible/garbage design drags it down honestly rather than
being silently dropped.

Run:
    ./.venv-chroma/bin/python experiments/exp006_mechanism_design/analyze.py
"""
from __future__ import annotations

import json
from pathlib import Path
from statistics import mean, median, stdev

EXP_DIR = Path(__file__).resolve().parent
TRIALS_PATH = EXP_DIR / "results" / "trials.jsonl"
SUMMARY_MD_PATH = EXP_DIR / "results" / "summary.md"
SUMMARY_JSON_PATH = EXP_DIR / "results" / "summary.json"

EFFICIENCY_THRESHOLD = 0.90      # mean allocative efficiency for a YES
FEASIBILITY_THRESHOLD = 0.90     # feasibility rate for a YES
FEASIBILITY_FLOOR = 0.50         # below this the efficiency mean is unreliable


def _load_rows() -> list[dict]:
    if not TRIALS_PATH.exists():
        raise SystemExit(f"FATAL: {TRIALS_PATH} does not exist — run run.py first")
    rows: list[dict] = []
    with open(TRIALS_PATH) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _fmt_stat(values: list[float], name: str) -> str:
    if not values:
        return f"- {name}: n=0"
    m = mean(values)
    md = median(values)
    sd = stdev(values) if len(values) >= 2 else 0.0
    mn = min(values)
    mx = max(values)
    return (f"- {name}: n={len(values)} mean={m:.3f} "
            f"median={md:.3f} sd={sd:.3f} min={mn:.3f} max={mx:.3f}")


def _compute_verdict(mean_eff: float, feasibility_rate: float) -> tuple[str, str]:
    """Return (verdict, blurb). INVALID gate takes precedence over YES/NO."""
    if feasibility_rate < FEASIBILITY_FLOOR:
        return (
            "INVALID",
            f"feasibility_rate {feasibility_rate:.2%} is below the "
            f"{FEASIBILITY_FLOOR:.0%} floor — too many designs failed to "
            "parse or were infeasible, so the efficiency mean "
            f"({mean_eff:.3f}) is unreliable. No near-optimality claim "
            "stands.",
        )
    if mean_eff >= EFFICIENCY_THRESHOLD and feasibility_rate >= FEASIBILITY_THRESHOLD:
        return (
            "YES",
            f"mean allocative efficiency {mean_eff:.3f} >= "
            f"{EFFICIENCY_THRESHOLD:.2f} AND feasibility_rate "
            f"{feasibility_rate:.2%} >= {FEASIBILITY_THRESHOLD:.0%} — the "
            "LLM designed near-optimal, feasible mechanisms.",
        )
    return (
        "NO",
        f"mean allocative efficiency {mean_eff:.3f} and feasibility_rate "
        f"{feasibility_rate:.2%} did not jointly clear the "
        f"{EFFICIENCY_THRESHOLD:.2f} / {FEASIBILITY_THRESHOLD:.0%} "
        "pre-registered thresholds.",
    )


def main() -> int:
    rows = _load_rows()
    ok = [r for r in rows if "error" not in r]
    errors = [r for r in rows if "error" in r]
    n_trials = len(ok)
    if n_trials == 0:
        SUMMARY_MD_PATH.parent.mkdir(parents=True, exist_ok=True)
        SUMMARY_MD_PATH.write_text("# exp006 summary\n\nNo successful trials.\n")
        SUMMARY_JSON_PATH.write_text(json.dumps({"verdict": "INVALID",
                                                 "n_trials": 0}, indent=2))
        print(f"wrote {SUMMARY_MD_PATH} (no successful trials)")
        return 1

    efficiencies = [float(r["efficiency"]) for r in ok]
    n_feasible = sum(1 for r in ok if r.get("is_feasible"))
    n_matches_vcg = sum(1 for r in ok if r.get("matches_vcg_alloc"))

    mean_eff = mean(efficiencies)
    feasibility_rate = n_feasible / n_trials
    matches_vcg_rate = n_matches_vcg / n_trials

    # Parse failures are observable: propose_allocation prefixes reasoning
    # with "parse_failure" on a malformed completion.
    parse_failures = sum(
        1 for r in ok
        if isinstance(r.get("proposal", {}).get("reasoning"), str)
        and r["proposal"]["reasoning"].startswith("parse_failure")
    )

    verdict, verdict_blurb = _compute_verdict(mean_eff, feasibility_rate)

    summary_obj = {
        "verdict": verdict,
        "n_trials": n_trials,
        "n_errors": len(errors),
        "designer_mean_efficiency": mean_eff,
        "feasibility_rate": feasibility_rate,
        "matches_vcg_rate": matches_vcg_rate,
        "n_feasible": n_feasible,
        "n_matches_vcg": n_matches_vcg,
        "parse_failures": parse_failures,
        "efficiency_threshold": EFFICIENCY_THRESHOLD,
        "feasibility_threshold": FEASIBILITY_THRESHOLD,
        "feasibility_floor": FEASIBILITY_FLOOR,
    }

    body = [
        "# exp006 — semi-synthetic mechanism-DESIGN summary",
        "",
        "This IS the semi-synthetic mechanism-DESIGN tier: the LLM designed "
        "each mechanism (allocation + payments), scored against the VCG "
        "benchmark. No single ground-truth output exists.",
        "",
        f"**Verdict: {verdict}** — {verdict_blurb}",
        "",
        "## Headline metrics",
        "",
        f"- Trials: {n_trials} (errors: {len(errors)})",
        f"- Designer mean allocative efficiency: {mean_eff:.3f}",
        f"- Feasibility rate: {n_feasible}/{n_trials} ({feasibility_rate:.2%})",
        f"- Matches-VCG-allocation rate: {n_matches_vcg}/{n_trials} "
        f"({matches_vcg_rate:.2%})",
        f"- Parse failures: {parse_failures}/{n_trials}",
        "",
        "## Efficiency statistics",
        "",
        "Allocative efficiency = realized welfare of the LLM-designed "
        "allocation / optimal welfare, over the TRUE valuations.",
        "",
        _fmt_stat(efficiencies, "per-trial allocative efficiency"),
        "",
        "## Verdict thresholds (pre-registered)",
        "",
        f"- YES iff mean efficiency >= {EFFICIENCY_THRESHOLD:.2f} AND "
        f"feasibility_rate >= {FEASIBILITY_THRESHOLD:.0%}.",
        f"- INVALID iff feasibility_rate < {FEASIBILITY_FLOOR:.0%} "
        "(efficiency mean unreliable; not coerced to pass/fail).",
        "- NO otherwise.",
        "",
    ]
    SUMMARY_MD_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_MD_PATH.write_text("\n".join(body))
    SUMMARY_JSON_PATH.write_text(json.dumps(summary_obj, indent=2))
    print(f"wrote {SUMMARY_MD_PATH}")
    print(f"wrote {SUMMARY_JSON_PATH}")
    print(f"verdict: {verdict} (mean_eff={mean_eff:.3f} "
          f"feasibility_rate={feasibility_rate:.2%})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
