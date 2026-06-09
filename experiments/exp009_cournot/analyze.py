#!/usr/bin/env python3
"""exp009 — analyze trials.jsonl into a Cournot few-shot verdict.

Reads ``results/trials.jsonl`` (written by ``run.py``) and writes
``results/summary.md`` (human-readable, carries the Verdict=YES|NO
token) plus ``results/summary.json`` (machine-readable, read by
loop_bridge.py).

PRE-REGISTERED verdict rule (constants below, fixed before any run):

  PRIMARY metric: mean |q - q*| / q* pooled over both firms' valid
  quantities, per treatment arm.

  Verdict = YES iff
    mean_dev(explicit) < mean_dev(absent)            (comparative)
    AND mean_dev(explicit) <= EXPLICIT_DEVIATION_CEILING  (0.15)

  Rationale: the thesis (iter-2026-06-06-001) claims explicit few-shot
  marginal-cost examples improve convergence to the Nash quantity. The
  comparative condition makes the verdict a treatment effect, not mere
  competence; the 0.15 ceiling (15% relative deviation, i.e. within
  +/-4.5 units of q*=30 at defaults) requires the explicit arm to
  actually be NEAR Nash, so "worse than terrible" cannot pass. "Below
  band but close" is a FAIL (inviolate rule 4).

  SECONDARY (directional, reported, NOT verdict-bearing): the thesis's
  variance prediction var(q | explicit) < var(q | absent).

Invalid trials (unparseable quantities) are excluded from the metrics
and reported as counts — never imputed.

Run:
    ./.venv-chroma/bin/python experiments/exp009_cournot/analyze.py
"""
from __future__ import annotations

import json
from pathlib import Path
from statistics import mean, pvariance

EXP_DIR = Path(__file__).resolve().parent
TRIALS_PATH = EXP_DIR / "results" / "trials.jsonl"
SUMMARY_MD_PATH = EXP_DIR / "results" / "summary.md"
SUMMARY_JSON_PATH = EXP_DIR / "results" / "summary.json"

# --- pre-registered constants (fixed BEFORE any run) --------------------
PRIMARY_METRIC = "mean_abs_nash_deviation"  # mean |q - q*| / q* per arm
EXPLICIT_DEVIATION_CEILING = 0.15  # explicit arm must be within 15% of q*
TREATMENTS = ("absent", "explicit")


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


def arm_stats(rows: list[dict], treatment: str) -> dict:
    """Per-arm statistics over VALID trials only. Invalid trials are
    counted, never imputed."""
    arm = [r for r in rows if r.get("treatment") == treatment and "error" not in r]
    valid = [r for r in arm if r.get("valid")]
    deviations: list[float] = []
    quantities: list[float] = []
    for r in valid:
        for k_q, k_d in (("q1", "deviation_1"), ("q2", "deviation_2")):
            if r.get(k_q) is not None and r.get(k_d) is not None:
                quantities.append(float(r[k_q]))
                deviations.append(float(r[k_d]))
    return {
        "treatment": treatment,
        "n_trials": len(arm),
        "n_valid": len(valid),
        "n_invalid": len(arm) - len(valid),
        "mean_abs_deviation": mean(deviations) if deviations else None,
        "quantity_variance": pvariance(quantities) if len(quantities) >= 2 else None,
        "mean_quantity": mean(quantities) if quantities else None,
    }


def build_summary(rows: list[dict]) -> dict:
    """Pure: rows -> summary dict with the pre-registered verdict."""
    errors = [r for r in rows if "error" in r]
    arms = {t: arm_stats(rows, t) for t in TREATMENTS}
    explicit = arms["explicit"]
    absent = arms["absent"]

    if explicit["mean_abs_deviation"] is None or absent["mean_abs_deviation"] is None:
        verdict = "NO"
        verdict_reason = (
            "one or both treatment arms have zero valid trials — the "
            "pre-registered comparison cannot be evaluated (not coerced)."
        )
        comparative_holds = None
        ceiling_holds = None
    else:
        comparative_holds = (
            explicit["mean_abs_deviation"] < absent["mean_abs_deviation"])
        ceiling_holds = (
            explicit["mean_abs_deviation"] <= EXPLICIT_DEVIATION_CEILING)
        if comparative_holds and ceiling_holds:
            verdict = "YES"
            verdict_reason = (
                f"mean_dev(explicit)={explicit['mean_abs_deviation']:.4f} < "
                f"mean_dev(absent)={absent['mean_abs_deviation']:.4f} and "
                f"<= ceiling {EXPLICIT_DEVIATION_CEILING}."
            )
        else:
            verdict = "NO"
            parts = []
            if not comparative_holds:
                parts.append(
                    f"mean_dev(explicit)={explicit['mean_abs_deviation']:.4f} is "
                    f"NOT < mean_dev(absent)={absent['mean_abs_deviation']:.4f}")
            if not ceiling_holds:
                parts.append(
                    f"mean_dev(explicit)={explicit['mean_abs_deviation']:.4f} "
                    f"exceeds the pre-registered ceiling "
                    f"{EXPLICIT_DEVIATION_CEILING}")
            verdict_reason = "; ".join(parts) + "."

    # Secondary directional variance prediction (reported, not verdict-bearing).
    if (explicit["quantity_variance"] is not None
            and absent["quantity_variance"] is not None):
        variance_directional_holds = (
            explicit["quantity_variance"] < absent["quantity_variance"])
    else:
        variance_directional_holds = None

    return {
        "experiment_id": "exp009_cournot",
        "primary_metric": PRIMARY_METRIC,
        "explicit_deviation_ceiling": EXPLICIT_DEVIATION_CEILING,
        "verdict": verdict,
        "verdict_reason": verdict_reason,
        "comparative_holds": comparative_holds,
        "ceiling_holds": ceiling_holds,
        "variance_directional_holds": variance_directional_holds,
        "arms": arms,
        "n_errors": len(errors),
    }


def _fmt(x, spec=".4f") -> str:
    return "n/a" if x is None else format(x, spec)


def render_markdown(summary: dict) -> str:
    arms = summary["arms"]
    explicit = arms["explicit"]
    absent = arms["absent"]
    v = summary["verdict"]
    lines = [
        "# exp009 — Cournot few-shot marginal-cost summary",
        "",
        f"**Verdict={v}** — explicit few-shot marginal-cost examples "
        f"{'DID' if v == 'YES' else 'DID NOT'} reduce deviation from the "
        "Nash quantity per the pre-registered rule.",
        "",
        summary["verdict_reason"],
        "",
        "## Per-treatment statistics",
        "",
    ]
    for arm in (absent, explicit):
        lines += [
            f"### {arm['treatment']}",
            "",
            f"- trials: {arm['n_trials']} (valid: {arm['n_valid']}, "
            f"invalid: {arm['n_invalid']})",
            f"- mean |q - q*|/q*: {_fmt(arm['mean_abs_deviation'])}",
            f"- mean quantity: {_fmt(arm['mean_quantity'], '.2f')}",
            f"- quantity variance: {_fmt(arm['quantity_variance'], '.2f')}",
            "",
        ]
    lines += [
        "## Secondary signal (directional, NOT verdict-bearing)",
        "",
        f"- var(explicit) < var(absent): "
        f"{summary['variance_directional_holds']}",
        "",
        "## Pre-registered verdict rule",
        "",
        f"YES iff mean_dev(explicit) < mean_dev(absent) AND "
        f"mean_dev(explicit) <= {summary['explicit_deviation_ceiling']}.",
        "",
        f"Errors: {summary['n_errors']}",
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
