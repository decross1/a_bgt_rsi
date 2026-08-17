#!/usr/bin/env python3
"""exp011 — analyze trials.jsonl into a reconstruction verdict.

Reads ``results/trials.jsonl`` (written by ``run.py``) and writes
``results/summary.md`` (Verdict=YES|NO on line 1) plus machine-readable
``results/summary.json`` (read by loop_bridge.py).

Decision rule constants below are copied VERBATIM from the LOCKED
pre-registration (experiments/PREREG_l2block_2026-08-17.md §exp011):

  effect_confirmed = TRUE iff BOTH
    1. median kendall_tau >= 0.90 at attack termination within Q <= 44
       and perturbations of <= 2 lists per query;
    2. >= 90% of trials reach kendall_tau >= 0.80.

  Verdict=NO attribution (LOCKED, from recorded diagnostics):
    (i)  budget-limited — constraints still accruing in the final 5
         queries (median constraints_in_last5_queries > 0) — consistent
         with the panel's query-complexity refutation; exp011 counts as
         evidence FOR the refutation only in this case.
    (ii) attack-limited — unresolved_pairs plateaued with idle budget
         remaining — adjudicating NEITHER the claim nor the refutation.

The summary must state the absence of the random-perturbation control
arm (2026-08-15 frontier methods review). Error rows are excluded from
every statistic and counted — never imputed (inviolate rule 4).

Run:
    ./.venv-chroma/bin/python experiments/exp011_matching_reconstruction/analyze.py
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

EXP_DIR = Path(__file__).resolve().parent
TRIALS_PATH = EXP_DIR / "results" / "trials.jsonl"
SUMMARY_MD_PATH = EXP_DIR / "results" / "summary.md"
SUMMARY_JSON_PATH = EXP_DIR / "results" / "summary.json"

# --- LOCKED constants (verbatim from PREREG_l2block_2026-08-17.md) ------
MEDIAN_TAU_THRESHOLD = 0.90      # rule 1: median kendall_tau >= 0.90
TRIAL_TAU_FLOOR = 0.80           # rule 2: per-trial tau floor
TRIAL_FRACTION_REQUIRED = 0.90   # rule 2: >= 90% of trials reach the floor
Q_MAX = 44                       # rule 1: within Q <= 44
LAST5_WINDOW = 5                 # attribution case (i) window
METRIC_NAME = "median_kendall_tau_at_termination"

BITS_REQUIRED = math.log2(math.factorial(12))  # ~28.9 bits (prereg)
CONTROL_ARM_NOTE = (
    "No random-perturbation control arm was run in this block; the "
    "2026-08-15 frontier methods review asked for one and the "
    "pre-registration requires its absence to be stated here."
)


def _load_rows(path: Path = TRIALS_PATH) -> list[dict]:
    if not path.exists():
        raise SystemExit(f"FATAL: {path} does not exist — run run.py first")
    rows: list[dict] = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _median(rows: list[dict], key: str) -> float:
    return float(np.median([r[key] for r in rows]))


def build_summary(rows: list[dict]) -> dict:
    """Pure: rows -> summary dict with the LOCKED verdict + attribution."""
    errors = [r for r in rows if "error" in r]
    valid = [r for r in rows if "error" not in r]

    if not valid:
        return {
            "experiment_id": "exp011_matching_reconstruction",
            "metric": METRIC_NAME,
            "value": None,
            "verdict": "NO",
            "effect_confirmed": False,
            "verdict_reason": ("zero valid trials — the locked rules cannot "
                               "be evaluated (not coerced)."),
            "rules": None,
            "attribution": {"case": "unattributed"},
            "control_arm_note": CONTROL_ARM_NOTE,
            "n_trials": len(rows),
            "n_valid": 0,
            "n_errors": len(errors),
        }

    taus = [float(r["kendall_tau_scored"]) for r in valid]
    median_tau = float(np.median(taus))
    max_queries = max(int(r["queries_used"]) for r in valid)
    budget_respected = max_queries <= Q_MAX
    rule1_pass = (median_tau >= MEDIAN_TAU_THRESHOLD) and budget_respected
    fraction_at_floor = sum(1 for x in taus if x >= TRIAL_TAU_FLOOR) / len(taus)
    rule2_pass = fraction_at_floor >= TRIAL_FRACTION_REQUIRED
    effect_confirmed = rule1_pass and rule2_pass
    verdict = "YES" if effect_confirmed else "NO"

    # --- Verdict=NO attribution (LOCKED two-case rule) -------------------
    med_last5 = _median(valid, "constraints_in_last5_queries")
    med_unresolved = _median(valid, "unresolved_pairs")
    med_idle = float(np.median([Q_MAX - int(r["queries_used"]) for r in valid]))
    if verdict == "YES":
        case = "not_applicable"
        attribution_text = "Verdict=YES — no failure to attribute."
        refutation_supported = False
    elif med_last5 > 0:
        case = "budget_limited"
        attribution_text = (
            "Case (i) budget-limited: constraints were still accruing in "
            f"the final {LAST5_WINDOW} queries (median "
            f"constraints_in_last5_queries = {med_last5:g} > 0) — "
            "consistent with the panel's query-complexity refutation. "
            "exp011 counts as evidence FOR the refutation in this case.")
        refutation_supported = True
    elif med_unresolved > 0 and med_idle > 0:
        case = "attack_limited"
        attribution_text = (
            "Case (ii) attack-limited: unresolved_pairs plateaued (median "
            f"{med_unresolved:g} > 0) with idle budget remaining (median "
            f"{med_idle:g} unspent queries) — adjudicating NEITHER the "
            "claim nor the refutation.")
        refutation_supported = False
    else:
        case = "unattributed"
        attribution_text = (
            "Neither locked case matched: constraints were not accruing in "
            f"the final {LAST5_WINDOW} queries (median {med_last5:g}) and "
            f"unresolved_pairs/idle-budget medians ({med_unresolved:g}/"
            f"{med_idle:g}) do not show a plateau with idle budget. "
            "Reported honestly, not coerced into a case.")
        refutation_supported = False

    if verdict == "YES":
        verdict_reason = (
            f"median tau {median_tau:.4f} >= {MEDIAN_TAU_THRESHOLD} within "
            f"Q <= {Q_MAX}, and {fraction_at_floor:.0%} of trials >= "
            f"{TRIAL_TAU_FLOOR} (requires >= "
            f"{TRIAL_FRACTION_REQUIRED:.0%}).")
    else:
        parts = []
        if not budget_respected:
            parts.append(f"max queries_used {max_queries} exceeds "
                         f"Q_max {Q_MAX}")
        if median_tau < MEDIAN_TAU_THRESHOLD:
            parts.append(f"median tau {median_tau:.4f} < "
                         f"{MEDIAN_TAU_THRESHOLD}")
        if not rule2_pass:
            parts.append(f"only {fraction_at_floor:.0%} of trials reached "
                         f"tau >= {TRIAL_TAU_FLOOR} (requires >= "
                         f"{TRIAL_FRACTION_REQUIRED:.0%})")
        verdict_reason = "; ".join(parts) + "."

    # --- non-gating diagnostics (all reported, none verdict-bearing) -----
    strata: dict[str, dict] = {}
    for rank in sorted({int(r["rank_t_best_natural_proposer"]) for r in valid}):
        sub = [float(r["kendall_tau_scored"]) for r in valid
               if int(r["rank_t_best_natural_proposer"]) == rank]
        strata[str(rank)] = {"n": len(sub),
                             "median_tau": float(np.median(sub))}

    return {
        "experiment_id": "exp011_matching_reconstruction",
        "metric": METRIC_NAME,
        "value": median_tau,
        "verdict": verdict,
        "effect_confirmed": effect_confirmed,
        "verdict_reason": verdict_reason,
        "rules": {
            "rule1_median_tau": {
                "threshold": MEDIAN_TAU_THRESHOLD,
                "observed_median_tau": median_tau,
                "q_max": Q_MAX,
                "max_queries_used": max_queries,
                "budget_respected": budget_respected,
                "pass": rule1_pass,
            },
            "rule2_trial_floor": {
                "tau_floor": TRIAL_TAU_FLOOR,
                "required_fraction": TRIAL_FRACTION_REQUIRED,
                "observed_fraction": fraction_at_floor,
                "pass": rule2_pass,
            },
        },
        "attribution": {
            "case": case,
            "text": attribution_text,
            "refutation_supported": refutation_supported,
            "median_constraints_in_last5_queries": med_last5,
            "median_unresolved_pairs": med_unresolved,
            "median_idle_budget": med_idle,
        },
        "diagnostics": {
            "median_queries_used": _median(valid, "queries_used"),
            "median_unresolved_pairs": med_unresolved,
            "median_bits_per_query": _median(valid, "bits_per_query"),
            "bits_required_log2_12_factorial": BITS_REQUIRED,
            "median_constraints_recorded": _median(valid,
                                                   "constraints_recorded"),
            "median_of_median_deviation_size": _median(
                valid, "median_deviation_size"),
            "median_null_tau_p95": _median(valid, "null_tau_p95"),
        },
        "stratified_tau_by_rank_t_best_natural_proposer": strata,
        "control_arm_note": CONTROL_ARM_NOTE,
        "n_trials": len(rows),
        "n_valid": len(valid),
        "n_errors": len(errors),
    }


def render_markdown(summary: dict) -> str:
    v = summary["verdict"]
    lines = [
        f"Verdict={v}. {summary['verdict_reason']}",
        "",
        "# exp011 — stable-matching preference reconstruction",
        "",
        f"metric: `{summary['metric']}` = "
        + ("n/a" if summary["value"] is None else f"{summary['value']:.4f}"),
        f"trials: {summary['n_trials']} (valid {summary['n_valid']}, "
        f"errors {summary['n_errors']})",
        "",
        "## Locked decision rules",
        "",
    ]
    rules = summary.get("rules")
    if rules is None:
        lines.append("Rules not evaluable: zero valid trials.")
    else:
        r1, r2 = rules["rule1_median_tau"], rules["rule2_trial_floor"]
        lines += [
            f"1. median tau >= {r1['threshold']} within Q <= {r1['q_max']}: "
            f"observed {r1['observed_median_tau']:.4f} (max queries "
            f"{r1['max_queries_used']}) -> "
            f"{'PASS' if r1['pass'] else 'FAIL'}",
            f"2. >= {r2['required_fraction']:.0%} of trials >= tau "
            f"{r2['tau_floor']}: observed {r2['observed_fraction']:.0%} -> "
            f"{'PASS' if r2['pass'] else 'FAIL'}",
        ]
    lines += ["", "## Attribution", "", summary["attribution"].get(
        "text", summary["attribution"]["case"])]
    diag = summary.get("diagnostics")
    if diag:
        lines += [
            "",
            "## Non-gating diagnostics",
            "",
            f"- median queries_used: {diag['median_queries_used']:g} "
            f"(budget {Q_MAX})",
            f"- median unresolved_pairs: {diag['median_unresolved_pairs']:g} "
            "of 66",
            f"- median bits_per_query: {diag['median_bits_per_query']:.3f} "
            f"(log2(12!) = {diag['bits_required_log2_12_factorial']:.1f} "
            "bits required)",
            f"- median constraints_recorded: "
            f"{diag['median_constraints_recorded']:g}",
            f"- median of per-trial median deviation_size: "
            f"{diag['median_of_median_deviation_size']:g}",
            f"- median null tau p95 (100-permutation chance baseline): "
            f"{diag['median_null_tau_p95']:.4f}",
            "",
            "## Scored tau stratified by rank of t's best natural proposer",
            "",
        ]
        for rank, s in summary[
                "stratified_tau_by_rank_t_best_natural_proposer"].items():
            lines.append(f"- rank {rank}: n={s['n']}, "
                         f"median tau {s['median_tau']:.4f}")
    lines += ["", "## Control-arm caveat", "", summary["control_arm_note"], ""]
    return "\n".join(lines)


def main() -> int:
    rows = _load_rows()
    summary = build_summary(rows)
    SUMMARY_MD_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_MD_PATH.write_text(render_markdown(summary))
    SUMMARY_JSON_PATH.write_text(json.dumps(summary, indent=2) + "\n")
    print(f"wrote {SUMMARY_MD_PATH}")
    print(f"wrote {SUMMARY_JSON_PATH}")
    print(f"verdict: {summary['verdict']} — {summary['verdict_reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
