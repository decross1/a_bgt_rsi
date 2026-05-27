#!/usr/bin/env python3
"""exp003 — analyze trials.jsonl into a Vickrey-rediscovery verdict.

Reads ``results/trials.jsonl`` (written by ``run.py``) and writes
``results/summary.md`` with:
  - residual statistics (bid - valuation), per bidder and pooled
  - the truthful-bid fraction at epsilon=5 and epsilon=10
  - a top-line Vickrey-rediscovery verdict (YES / NO / MIXED) based on
    a pre-registered threshold: >=75% of trials with mean |residual| <= 5

The verdict threshold is conservative — Vickrey's dominant-strategy
result predicts truthful bidding to within sampling noise, so a
substantially lower fraction is evidence the model has NOT
rediscovered the result.

Run:
    ./.venv-chroma/bin/python experiments/exp003_vickrey_rediscovery/analyze.py
"""
from __future__ import annotations

import json
from pathlib import Path
from statistics import mean, median, stdev

EXP_DIR = Path(__file__).resolve().parent
TRIALS_PATH = EXP_DIR / "results" / "trials.jsonl"
SUMMARY_PATH = EXP_DIR / "results" / "summary.md"

EPS_TIGHT = 5.0
EPS_LOOSE = 10.0
VERDICT_THRESHOLD = 0.75  # fraction of trials with mean |residual| <= EPS_TIGHT


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


def _trial_mean_abs_residual(row: dict) -> float | None:
    resids = row.get("bid_residuals")
    if not resids:
        return None
    return mean(abs(r) for r in resids)


def _fmt_stat(values: list[float], name: str) -> str:
    if not values:
        return f"- {name}: n=0"
    m = mean(values)
    md = median(values)
    sd = stdev(values) if len(values) >= 2 else 0.0
    mn = min(values)
    mx = max(values)
    return (f"- {name}: n={len(values)} mean={m:+.2f} "
            f"median={md:+.2f} sd={sd:.2f} min={mn:+.2f} max={mx:+.2f}")


def main() -> int:
    rows = _load_rows()
    ok = [r for r in rows if "error" not in r]
    errors = [r for r in rows if "error" in r]
    n_trials = len(ok)
    if n_trials == 0:
        SUMMARY_PATH.write_text("# exp003 summary\n\nNo successful trials.\n")
        print(f"wrote {SUMMARY_PATH} (no successful trials)")
        return 1

    # Pooled residuals across all bidders × trials.
    all_residuals: list[float] = []
    for r in ok:
        all_residuals.extend(r.get("bid_residuals", []))

    # Per-trial: mean |residual|; used to compute the truthful fraction.
    trial_mean_abs = [_trial_mean_abs_residual(r) for r in ok]
    trial_mean_abs = [x for x in trial_mean_abs if x is not None]
    truthful_tight = sum(1 for x in trial_mean_abs if x <= EPS_TIGHT)
    truthful_loose = sum(1 for x in trial_mean_abs if x <= EPS_LOOSE)
    fraction_tight = truthful_tight / len(trial_mean_abs) if trial_mean_abs else 0.0
    fraction_loose = truthful_loose / len(trial_mean_abs) if trial_mean_abs else 0.0

    # Parse-failure rate (bidder.py defaults to bid = valuation on parse failure
    # AND prefixes reasoning with "parse_failure:" — observable here).
    parse_failures = 0
    for r in ok:
        for reason in r.get("reasonings", []):
            if isinstance(reason, str) and reason.startswith("parse_failure"):
                parse_failures += 1
    total_bids = sum(len(r.get("bids", [])) for r in ok)
    parse_failure_rate = parse_failures / total_bids if total_bids else 0.0

    # Tie-break rate.
    tie_breaks = sum(1 for r in ok if r.get("tie_break"))

    # Pre-registered verdict.
    if fraction_tight >= VERDICT_THRESHOLD:
        verdict = "YES"
        verdict_blurb = (
            f"{truthful_tight}/{len(trial_mean_abs)} trials "
            f"({100*fraction_tight:.0f}%) had mean |residual| <= "
            f"{EPS_TIGHT:.0f}, meeting the {100*VERDICT_THRESHOLD:.0f}% "
            "pre-registered threshold."
        )
    else:
        verdict = "NO"
        verdict_blurb = (
            f"only {truthful_tight}/{len(trial_mean_abs)} trials "
            f"({100*fraction_tight:.0f}%) had mean |residual| <= "
            f"{EPS_TIGHT:.0f}, below the {100*VERDICT_THRESHOLD:.0f}% "
            "pre-registered threshold."
        )

    body = [
        "# exp003 — Vickrey rediscovery summary",
        "",
        f"**Verdict: {verdict}** — LLM bidders {'DID' if verdict == 'YES' else 'DID NOT'} "
        "rediscover truthful bidding as the dominant strategy in a sealed-bid "
        "second-price auction.",
        "",
        verdict_blurb,
        "",
        "## Headline metrics",
        "",
        f"- Trials: {n_trials} (errors: {len(errors)})",
        f"- LLM calls: {total_bids}",
        f"- Parse failures: {parse_failures}/{total_bids} "
        f"({100*parse_failure_rate:.1f}%)",
        f"- Tie-break trials: {tie_breaks}/{n_trials}",
        f"- Truthful fraction at eps={EPS_TIGHT}: "
        f"{truthful_tight}/{len(trial_mean_abs)} "
        f"({100*fraction_tight:.1f}%)",
        f"- Truthful fraction at eps={EPS_LOOSE}: "
        f"{truthful_loose}/{len(trial_mean_abs)} "
        f"({100*fraction_loose:.1f}%)",
        "",
        "## Residual statistics",
        "",
        "Residual = bid - private_valuation. Truthful bidding under "
        "Vickrey's theorem implies residual ≈ 0.",
        "",
        _fmt_stat(all_residuals, "pooled bid residuals (per LLM call)"),
        _fmt_stat(trial_mean_abs, "per-trial mean |residual|"),
        "",
        "## Verdict threshold (pre-registered)",
        "",
        f"YES iff fraction of trials with mean |residual| <= {EPS_TIGHT} "
        f"is >= {100*VERDICT_THRESHOLD:.0f}%.",
        "",
    ]
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text("\n".join(body))
    print(f"wrote {SUMMARY_PATH}")
    print(f"verdict: {verdict} (truthful fraction at eps={EPS_TIGHT}: "
          f"{100*fraction_tight:.1f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
