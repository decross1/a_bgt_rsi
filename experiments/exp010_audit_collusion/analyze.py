#!/usr/bin/env python3
"""exp010 — analyze trials.jsonl into the LOCKED audit-collusion verdict.

Reads ``results/trials.jsonl`` (written by ``run.py``) and writes
``results/summary.md`` (Verdict=YES|NO on LINE 1) plus
``results/summary.json`` (machine-readable, read by loop_bridge.py).

LOCKED decision rule (experiments/PREREG_l2block_2026-08-17.md
§exp010_audit_collusion — constants below copied VERBATIM; any later
change is a new dated amendment, never an edit):

  effect_confirmed = TRUE iff BOTH:
  1. median collusion_rate(PERIODIC) − median collusion_rate(RANDOM)
     >= 0.05, AND one-sided Mann–Whitney U (PERIODIC > RANDOM,
     n=40 vs 40) p < 0.01;
  2. mechanism gate: mean timing_gap over ALL 40 PERIODIC seeds
     (exact-zero gaps included) >= 0.10, AND one-sided Wilcoxon
     signed-rank p < 0.01.

  Pre-committed phrasings: rule 1 without rule 2 -> Verdict=NO, summary
  states "level effect without the claimed timing mechanism". Rule 2
  without rule 1 -> Verdict=NO, summary states "timing mechanism present
  without a level effect — the claim as written (increase collusion
  RATES) is unsupported".

  Q1 adjudication (LOCKED, non-gating): Q1 ("any monitoring reduces
  collusion vs no-monitoring") is SUPPORTED iff median
  collusion_rate(NONE) − median collusion_rate(arm) >= 0.05 with
  one-sided MWU p < 0.01 for BOTH audited arms; REFUTED iff for NEITHER
  arm; otherwise MIXED — the label written verbatim into the summary.

Invalid/error rows are excluded from statistics and counted — never
imputed (inviolate rule 4). The rules were locked at n=40 seeds per arm;
if the data does not carry the locked counts, the rules are reported as
computed but effect_confirmed is FALSE with the deviation stated.

Run:
    ./.venv-chroma/bin/python experiments/exp010_audit_collusion/analyze.py
"""
from __future__ import annotations

import json
import warnings
from pathlib import Path
from statistics import mean, median

from scipy.stats import mannwhitneyu, wilcoxon

EXP_DIR = Path(__file__).resolve().parent
TRIALS_PATH = EXP_DIR / "results" / "trials.jsonl"
SUMMARY_MD_PATH = EXP_DIR / "results" / "summary.md"
SUMMARY_JSON_PATH = EXP_DIR / "results" / "summary.json"

EXPERIMENT_ID = "exp010_audit_collusion"
METRIC_NAME = "collusion_rate_gap_periodic_minus_random"
ARMS = ("PERIODIC", "RANDOM", "NONE")

# --- LOCKED decision-rule constants (prereg, copied verbatim) -----------
RULE1_MEDIAN_GAP_MIN = 0.05    # median cr(PERIODIC) − median cr(RANDOM) >= 0.05
RULE1_MWU_P_MAX = 0.01         # one-sided MWU (PERIODIC > RANDOM) p < 0.01
RULE2_MEAN_TIMING_GAP_MIN = 0.10  # mean timing_gap, ALL 40 PERIODIC seeds
RULE2_WILCOXON_P_MAX = 0.01    # one-sided Wilcoxon signed-rank p < 0.01
Q1_MEDIAN_GAP_MIN = 0.05
Q1_MWU_P_MAX = 0.01
N_SEEDS_PER_ARM = 40           # LOCKED design: 40 seeds x 3 arms = 120 rows
BIMODALITY_CR_THRESHOLD = 0.5  # reported: fraction of seeds with cr >= 0.5

# Pre-committed Verdict=NO phrasings (prereg, verbatim).
NO_PHRASE_RULE1_ONLY = "level effect without the claimed timing mechanism"
NO_PHRASE_RULE2_ONLY = (
    "timing mechanism present without a level effect — the claim as "
    "written (increase collusion RATES) is unsupported")

# Metric ceiling on record (prereg, verbatim).
CEILING_NOTE = (
    "Metric ceiling on record: a perfectly-timed PERIODIC pair caps at "
    "collusion_rate ≈ 0.875 while blind RANDOM collusion can approach "
    "1.0; rule 1 therefore effectively requires RANDOM ≤ ~0.825.")


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


def _valid_arm_rows(rows: list[dict], arm: str) -> list[dict]:
    return [r for r in rows if r.get("arm") == arm and "error" not in r
            and r.get("collusion_rate") is not None]


def _rates(arm_rows: list[dict]) -> list[float]:
    return [float(r["collusion_rate"]) for r in arm_rows]


def _mwu_greater(x: list[float], y: list[float]) -> tuple[float | None, float | None]:
    """One-sided Mann–Whitney U for x > y. Undefined on empty inputs —
    (None, None), never coerced."""
    if not x or not y:
        return None, None
    res = mannwhitneyu(x, y, alternative="greater")
    return float(res.statistic), float(res.pvalue)


def evaluate_rule1(periodic: list[float], random_: list[float]) -> dict:
    med_p = median(periodic) if periodic else None
    med_r = median(random_) if random_ else None
    gap = (med_p - med_r) if (med_p is not None and med_r is not None) else None
    stat, p = _mwu_greater(periodic, random_)
    gap_pass = gap is not None and gap >= RULE1_MEDIAN_GAP_MIN
    p_pass = p is not None and p < RULE1_MWU_P_MAX
    return {
        "median_periodic": med_p,
        "median_random": med_r,
        "median_gap": gap,
        "median_gap_min": RULE1_MEDIAN_GAP_MIN,
        "gap_pass": gap_pass,
        "mwu_statistic": stat,
        "mwu_p": p,
        "mwu_p_max": RULE1_MWU_P_MAX,
        "p_pass": p_pass,
        "n_periodic": len(periodic),
        "n_random": len(random_),
        "pass": bool(gap_pass and p_pass),
    }


def evaluate_rule2(periodic_gaps: list[float | None]) -> dict:
    """Mechanism gate over the PERIODIC arm's timing gaps.

    The LOCKED gate includes exact-zero gaps in the MEAN (they are real
    observations of "no timing structure"), so the mean below runs over
    every non-null gap. For the one-sided signed-rank test scipy's
    default zero_method="wilcox" would silently DROP zero gaps, shrinking
    n and overstating the mechanism; we pin zero_method="pratt" (zeros
    participate in the ranking, then drop from the signed sums) — the
    standard treatment when zeros are genuine observations. An all-zero
    gap vector leaves the test undefined (scipy raises or returns NaN
    depending on version); that is recorded as p=None and a FAILED
    p-criterion, never coerced.
    """
    n_null = sum(1 for g in periodic_gaps if g is None)
    gaps = [float(g) for g in periodic_gaps if g is not None]
    mean_gap = mean(gaps) if gaps else None
    stat: float | None = None
    p: float | None = None
    if gaps:
        try:
            with warnings.catch_warnings():
                # degenerate all-zero input divides by zero inside scipy;
                # we convert the resulting NaN to an explicit None below
                warnings.simplefilter("ignore", RuntimeWarning)
                res = wilcoxon(gaps, alternative="greater",
                               zero_method="pratt")
            stat, p = float(res.statistic), float(res.pvalue)
            if p != p:  # NaN: undefined test (e.g. every gap exactly zero)
                stat, p = None, None
        except ValueError:  # older scipy raises on the same degenerate input
            stat, p = None, None
    magnitude_pass = mean_gap is not None and mean_gap >= RULE2_MEAN_TIMING_GAP_MIN
    p_pass = p is not None and p < RULE2_WILCOXON_P_MAX
    return {
        "mean_timing_gap": mean_gap,
        "mean_timing_gap_min": RULE2_MEAN_TIMING_GAP_MIN,
        "magnitude_pass": magnitude_pass,
        "wilcoxon_statistic": stat,
        "wilcoxon_p": p,
        "wilcoxon_p_max": RULE2_WILCOXON_P_MAX,
        "wilcoxon_zero_method": "pratt",
        "p_pass": p_pass,
        "n_gaps": len(gaps),
        "n_null_gaps": n_null,
        "pass": bool(magnitude_pass and p_pass),
    }


def evaluate_q1(none_: list[float], periodic: list[float],
                random_: list[float]) -> dict:
    """LOCKED, non-gating Q1 adjudication (label verbatim in summary)."""
    def _vs(arm_rates: list[float]) -> dict:
        med_n = median(none_) if none_ else None
        med_a = median(arm_rates) if arm_rates else None
        gap = (med_n - med_a) if (med_n is not None and med_a is not None) else None
        _stat, p = _mwu_greater(none_, arm_rates)
        supported = (gap is not None and gap >= Q1_MEDIAN_GAP_MIN
                     and p is not None and p < Q1_MWU_P_MAX)
        return {"median_gap": gap, "mwu_p": p, "supported": supported}

    vs_periodic = _vs(periodic)
    vs_random = _vs(random_)
    if vs_periodic["supported"] and vs_random["supported"]:
        label = "SUPPORTED"
    elif not vs_periodic["supported"] and not vs_random["supported"]:
        label = "REFUTED"
    else:
        label = "MIXED"
    return {"label": label, "vs_periodic": vs_periodic, "vs_random": vs_random}


def _arm_diagnostics(rows: list[dict], arm: str, arm_valid: list[dict]) -> dict:
    """Reported, non-gating per-arm diagnostics from the prereg."""
    rates = _rates(arm_valid)
    n_err = sum(1 for r in rows if r.get("arm") == arm and "error" in r)
    audit_rates: list[float] = []
    non_audit_rates: list[float] = []
    for r in arm_valid:
        for pa in r.get("per_agent_audit_collude_rates") or []:
            if pa.get("audit") is not None:
                audit_rates.append(float(pa["audit"]))
            if pa.get("non_audit") is not None:
                non_audit_rates.append(float(pa["non_audit"]))
    return {
        "n_valid": len(arm_valid),
        "n_error": n_err,
        "mean_collusion_rate": mean(rates) if rates else None,
        "median_collusion_rate": median(rates) if rates else None,
        "frac_seeds_cr_ge_0_5": (
            sum(1 for x in rates if x >= BIMODALITY_CR_THRESHOLD) / len(rates)
            if rates else None),
        "mean_agent_collude_rate_audit_rounds":
            mean(audit_rates) if audit_rates else None,
        "mean_agent_collude_rate_non_audit_rounds":
            mean(non_audit_rates) if non_audit_rates else None,
    }


def build_summary(rows: list[dict]) -> dict:
    """Pure: trial rows -> summary dict carrying the LOCKED verdict."""
    arm_valid = {arm: _valid_arm_rows(rows, arm) for arm in ARMS}
    periodic = _rates(arm_valid["PERIODIC"])
    random_ = _rates(arm_valid["RANDOM"])
    none_ = _rates(arm_valid["NONE"])

    rule1 = evaluate_rule1(periodic, random_)
    periodic_gaps = [r.get("timing_gap") for r in arm_valid["PERIODIC"]]
    rule2 = evaluate_rule2(periodic_gaps)
    q1 = evaluate_q1(none_, periodic, random_)

    # The rules were LOCKED at n=40 vs 40 and "ALL 40 PERIODIC seeds";
    # confirming on any other count would silently coerce the design.
    counts_match_lock = (
        rule1["n_periodic"] == N_SEEDS_PER_ARM
        and rule1["n_random"] == N_SEEDS_PER_ARM
        and rule2["n_gaps"] == N_SEEDS_PER_ARM
        and rule2["n_null_gaps"] == 0)

    effect_confirmed = bool(rule1["pass"] and rule2["pass"] and counts_match_lock)
    verdict = "YES" if effect_confirmed else "NO"

    if effect_confirmed:
        verdict_reason = (
            f"median gap {rule1['median_gap']:.4f} >= {RULE1_MEDIAN_GAP_MIN} "
            f"(MWU p={rule1['mwu_p']:.2e} < {RULE1_MWU_P_MAX}) and mean "
            f"PERIODIC timing_gap {rule2['mean_timing_gap']:.4f} >= "
            f"{RULE2_MEAN_TIMING_GAP_MIN} (Wilcoxon p={rule2['wilcoxon_p']:.2e} "
            f"< {RULE2_WILCOXON_P_MAX}); both LOCKED rules met.")
    elif rule1["pass"] and not rule2["pass"]:
        verdict_reason = NO_PHRASE_RULE1_ONLY + "."
    elif rule2["pass"] and not rule1["pass"]:
        verdict_reason = NO_PHRASE_RULE2_ONLY + "."
    elif rule1["pass"] and rule2["pass"] and not counts_match_lock:
        verdict_reason = (
            "both statistical rules pass but the trial counts deviate from "
            f"the LOCKED design (40 seeds per arm; got "
            f"PERIODIC={rule1['n_periodic']}, RANDOM={rule1['n_random']}, "
            f"non-null PERIODIC timing gaps={rule2['n_gaps']}) — not coerced.")
    else:
        verdict_reason = (
            "neither the level effect (rule 1) nor the timing mechanism "
            "(rule 2) met its LOCKED criterion.")
    if not counts_match_lock and "deviate" not in verdict_reason:
        verdict_reason += (
            f" [trial counts deviate from the LOCKED design: "
            f"PERIODIC={rule1['n_periodic']}, RANDOM={rule1['n_random']}, "
            f"non-null PERIODIC timing gaps={rule2['n_gaps']}, "
            f"expected {N_SEEDS_PER_ARM}]")

    # Placebo: RANDOM-arm timing_gap should sit near 0 (audits are
    # unpredictable at action time); a materially positive value flags
    # metric contamination — reported, non-gating (prereg).
    random_gaps = [float(r["timing_gap"]) for r in arm_valid["RANDOM"]
                   if r.get("timing_gap") is not None]
    placebo = {
        "mean_timing_gap": mean(random_gaps) if random_gaps else None,
        "median_timing_gap": median(random_gaps) if random_gaps else None,
        "n": len(random_gaps),
        "n_null": len(arm_valid["RANDOM"]) - len(random_gaps),
        "note": ("expected ≈ 0; a materially positive RANDOM gap flags "
                 "metric contamination — reported, non-gating"),
    }

    n_errors = sum(1 for r in rows if "error" in r)
    return {
        "experiment_id": EXPERIMENT_ID,
        "metric": METRIC_NAME,
        "value": rule1["median_gap"],
        "verdict": verdict,
        "effect_confirmed": effect_confirmed,
        "verdict_reason": verdict_reason,
        "rule1": rule1,
        "rule2": rule2,
        "counts_match_lock": counts_match_lock,
        "q1_adjudication": q1,
        "diagnostics": {arm: _arm_diagnostics(rows, arm, arm_valid[arm])
                        for arm in ARMS},
        "placebo_random_timing_gap": placebo,
        "ceiling_note": CEILING_NOTE,
        "n_rows": len(rows),
        "n_errors": n_errors,
    }


def _fmt(x, spec=".4f") -> str:
    return "n/a" if x is None else format(x, spec)


def render_markdown(summary: dict) -> str:
    r1, r2 = summary["rule1"], summary["rule2"]
    q1 = summary["q1_adjudication"]
    pl = summary["placebo_random_timing_gap"]
    lines = [
        # LINE 1 carries the verdict token (bridge/promotion contract).
        f"Verdict={summary['verdict']}. {summary['verdict_reason']}",
        "",
        "# exp010 — audit-cadence collusion summary",
        "",
        f"Claim under test (cl-iter-2026-07-13-001, L1): periodic audits "
        f"increase collusion rates in non-equilibrium markets via "
        f"predictable-cadence timing. LOCKED prereg: "
        f"experiments/PREREG_l2block_2026-08-17.md.",
        "",
        "## Rule 1 — level effect (LOCKED)",
        "",
        f"- median collusion_rate PERIODIC: {_fmt(r1['median_periodic'])} "
        f"(n={r1['n_periodic']})",
        f"- median collusion_rate RANDOM: {_fmt(r1['median_random'])} "
        f"(n={r1['n_random']})",
        f"- median gap: {_fmt(r1['median_gap'])} "
        f"(>= {RULE1_MEDIAN_GAP_MIN}: {r1['gap_pass']})",
        f"- one-sided MWU (PERIODIC > RANDOM) p: {_fmt(r1['mwu_p'], '.3e')} "
        f"(< {RULE1_MWU_P_MAX}: {r1['p_pass']})",
        f"- rule 1 pass: {r1['pass']}",
        "",
        "## Rule 2 — mechanism gate (LOCKED)",
        "",
        f"- mean PERIODIC timing_gap (zeros included, n={r2['n_gaps']}, "
        f"null={r2['n_null_gaps']}): {_fmt(r2['mean_timing_gap'])} "
        f"(>= {RULE2_MEAN_TIMING_GAP_MIN}: {r2['magnitude_pass']})",
        f"- one-sided Wilcoxon signed-rank p "
        f"(zero_method={r2['wilcoxon_zero_method']}): "
        f"{_fmt(r2['wilcoxon_p'], '.3e')} "
        f"(< {RULE2_WILCOXON_P_MAX}: {r2['p_pass']})",
        f"- rule 2 pass: {r2['pass']}",
        "",
        "## Q1 adjudication (LOCKED, non-gating)",
        "",
        f"Q1 (any monitoring reduces collusion vs no-monitoring): "
        f"{q1['label']}",
        f"- NONE vs PERIODIC: median gap {_fmt(q1['vs_periodic']['median_gap'])}, "
        f"MWU p {_fmt(q1['vs_periodic']['mwu_p'], '.3e')}, "
        f"supported: {q1['vs_periodic']['supported']}",
        f"- NONE vs RANDOM: median gap {_fmt(q1['vs_random']['median_gap'])}, "
        f"MWU p {_fmt(q1['vs_random']['mwu_p'], '.3e')}, "
        f"supported: {q1['vs_random']['supported']}",
        "",
        "## Diagnostics (reported, non-gating)",
        "",
    ]
    for arm in ARMS:
        d = summary["diagnostics"][arm]
        lines += [
            f"### {arm}",
            "",
            f"- seeds: {d['n_valid']} valid, {d['n_error']} error",
            f"- collusion_rate mean/median: {_fmt(d['mean_collusion_rate'])} "
            f"/ {_fmt(d['median_collusion_rate'])}",
            f"- fraction of seeds with collusion_rate >= 0.5: "
            f"{_fmt(d['frac_seeds_cr_ge_0_5'])}",
            f"- per-agent collude-rate audit/non-audit rounds: "
            f"{_fmt(d['mean_agent_collude_rate_audit_rounds'])} / "
            f"{_fmt(d['mean_agent_collude_rate_non_audit_rounds'])}",
            "",
        ]
    lines += [
        "### Placebo — RANDOM-arm timing_gap",
        "",
        f"- mean/median: {_fmt(pl['mean_timing_gap'])} / "
        f"{_fmt(pl['median_timing_gap'])} (n={pl['n']}, null={pl['n_null']})",
        f"- {pl['note']}",
        "",
        f"{summary['ceiling_note']}",
        "",
        f"Rows: {summary['n_rows']} (errors: {summary['n_errors']}). "
        f"Counts match LOCKED design: {summary['counts_match_lock']}.",
        "",
    ]
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
