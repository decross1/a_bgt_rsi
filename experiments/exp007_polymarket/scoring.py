#!/usr/bin/env python3
"""exp007 — forecasting scoring: Brier score + Brier Skill Score.

DESIGN-ONLY paper forecasting; NO live trading (CLAUDE.md CFTC guardrail).

This module is the OFFLINE scoring half of the Polymarket paper-forecasting
sandbox rung. It never touches the network, never places an order, never
signs a transaction, never authenticates anywhere. It consumes three numbers
per market — the model's probability forecast, the market price at forecast
time, and the realized binary outcome — and scores forecasting skill.

The research metric is forecasting skill measured as the Brier Skill Score
(BSS) of the model's forecasts relative to the contemporaneous market price
as the reference forecaster (per docs/sources/research_program_v2.md). A
positive BSS means the model's probabilities beat the market price; negative
means worse.

Definitions
-----------
Brier score (lower is better)::

    brier(p, y) = (p - y) ** 2          y in {0.0, 1.0}

Brier Skill Score relative to a reference (higher is better, <=1)::

    BSS = 1 - mean(model_briers) / mean(market_briers)

Pure python; no LLM, no I/O.
"""
from __future__ import annotations

from statistics import mean
from typing import Optional


def brier(prob: float, outcome: float) -> float:
    """Brier score for one binary forecast.

    ``outcome`` is the realized event indicator, 0.0 or 1.0.
    Returns the squared error ``(prob - outcome) ** 2`` in [0, 1].
    A perfect forecast (prob == outcome) scores 0.0.
    """
    return (prob - outcome) ** 2


def brier_skill_score(
    model_briers: list[float], market_briers: list[float]
) -> float:
    """Brier Skill Score of the model relative to the market reference.

    ``BSS = 1 - mean(model_briers) / mean(market_briers)``. BSS > 0 means the
    model beats the market price; BSS == 0 means parity; BSS < 0 means worse.

    The reference (market) mean Brier is the denominator. If it is zero — the
    market itself was a perfect forecaster on every scored row — the skill
    ratio is undefined, so we guard the divide-by-zero and return 0.0 rather
    than coercing a near-miss or raising. An empty input is likewise 0.0.
    """
    if not model_briers or not market_briers:
        return 0.0
    market_mean = mean(market_briers)
    if market_mean == 0.0:
        return 0.0
    return 1.0 - mean(model_briers) / market_mean


def summarize(rows: list[dict]) -> dict:
    """Score a batch of forecast rows.

    Each row is ``{"prob": float, "market_prob": float, "outcome": float|None}``.
    Rows with ``outcome is None`` are unresolved and SKIPPED — they contribute
    to neither count nor either mean. ``outcome`` for scored rows is 0.0/1.0.

    Returns::

        {
          "n": int,                    # scored (resolved) rows
          "mean_brier_model": float,
          "mean_brier_market": float,
          "bss": float,                # model vs market, see brier_skill_score
          "calibration_note": str,
        }

    With no resolved rows, the means are 0.0, bss is 0.0, and the note says so.
    """
    resolved = [r for r in rows if r.get("outcome") is not None]
    n = len(resolved)
    if n == 0:
        return {
            "n": 0,
            "mean_brier_model": 0.0,
            "mean_brier_market": 0.0,
            "bss": 0.0,
            "calibration_note": "no resolved rows",
        }

    model_briers = [brier(r["prob"], r["outcome"]) for r in resolved]
    market_briers = [brier(r["market_prob"], r["outcome"]) for r in resolved]
    mean_model = mean(model_briers)
    mean_market = mean(market_briers)
    bss = brier_skill_score(model_briers, market_briers)

    if bss > 0.0:
        note = f"model beats market over {n} resolved rows (BSS={bss:.4f})"
    elif bss < 0.0:
        note = f"model trails market over {n} resolved rows (BSS={bss:.4f})"
    else:
        note = f"model at parity with market over {n} resolved rows"

    return {
        "n": n,
        "mean_brier_model": mean_model,
        "mean_brier_market": mean_market,
        "bss": bss,
        "calibration_note": note,
    }
