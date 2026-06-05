#!/usr/bin/env python3
# DESIGN-ONLY paper forecasting; NO live trading (CLAUDE.md CFTC guardrail).
"""exp007 — analyze forecasts.jsonl into a paper-forecasting verdict.

Reads ``results/forecasts.jsonl`` (written by ``run.py``), scores the rows
OFFLINE with ``scoring.summarize`` (Brier / Brier Skill Score vs the
market-implied probability), and writes ``results/summary.json`` +
``results/summary.md``.

The verdict is about FORECASTING SKILL, not trading P&L. There is no
position, no order, no money:

  - INSUFFICIENT   : fewer than MIN_SAMPLE resolved rows to judge skill.
  - BEATS_MARKET   : BSS > 0 over at least MIN_SAMPLE rows (the model's
                     probabilities are better-calibrated than the
                     contemporaneous market price).
  - BELOW_MARKET   : otherwise (BSS <= 0).

Run:
    ./.venv-chroma/bin/python experiments/exp007_polymarket/analyze.py
"""
from __future__ import annotations

import json
from pathlib import Path

import sys

EXP_DIR = Path(__file__).resolve().parent
REPO_ROOT = EXP_DIR.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from experiments.exp007_polymarket import scoring  # noqa: E402

FORECASTS_PATH = EXP_DIR / "results" / "forecasts.jsonl"
SUMMARY_JSON_PATH = EXP_DIR / "results" / "summary.json"
SUMMARY_MD_PATH = EXP_DIR / "results" / "summary.md"

MIN_SAMPLE = 10  # below this, skill is not judged (INSUFFICIENT)


def _load_rows() -> list[dict]:
    if not FORECASTS_PATH.exists():
        raise SystemExit(f"FATAL: {FORECASTS_PATH} does not exist — run run.py first")
    rows: list[dict] = []
    with open(FORECASTS_PATH) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _verdict(summary: dict) -> str:
    if summary["n"] < MIN_SAMPLE:
        return "INSUFFICIENT"
    if summary["bss"] > 0.0:
        return "BEATS_MARKET"
    return "BELOW_MARKET"


def main() -> int:
    rows = _load_rows()
    scorable = [r for r in rows if "error" not in r]
    errors = [r for r in rows if "error" in r]

    summary = scoring.summarize(scorable)
    verdict = _verdict(summary)

    out = {
        "verdict": verdict,
        "n": summary["n"],
        "mean_brier_model": summary["mean_brier_model"],
        "mean_brier_market": summary["mean_brier_market"],
        "bss": summary["bss"],
        "calibration_note": summary["calibration_note"],
        "errors": len(errors),
        "min_sample": MIN_SAMPLE,
    }
    SUMMARY_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_JSON_PATH.write_text(json.dumps(out, indent=2) + "\n")

    body = [
        "# exp007 — Polymarket paper-forecasting summary",
        "",
        "DESIGN-ONLY paper forecasting; NO live trading (CLAUDE.md CFTC guardrail).",
        "",
        f"**Verdict: {verdict}**",
        "",
        "This is a paper-forecasting result — forecasting skill vs the market "
        "price, NOT trading P&L. No position, no order, no money.",
        "",
        "## Headline metrics",
        "",
        f"- Resolved rows scored (n): {summary['n']} (errors: {len(errors)})",
        f"- Mean Brier (model): {summary['mean_brier_model']:.4f}",
        f"- Mean Brier (market): {summary['mean_brier_market']:.4f}",
        f"- Brier Skill Score (model vs market): {summary['bss']:.4f}",
        f"- Calibration note: {summary['calibration_note']}",
        "",
        "## Verdict rule",
        "",
        f"- INSUFFICIENT iff n < {MIN_SAMPLE}.",
        "- BEATS_MARKET iff BSS > 0 over at least the minimum sample "
        "(model better-calibrated than the contemporaneous market price).",
        "- BELOW_MARKET otherwise.",
        "",
    ]
    SUMMARY_MD_PATH.write_text("\n".join(body))

    print(f"wrote {SUMMARY_JSON_PATH}")
    print(f"wrote {SUMMARY_MD_PATH}")
    print(f"verdict: {verdict} (n={summary['n']}, bss={summary['bss']:.4f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
