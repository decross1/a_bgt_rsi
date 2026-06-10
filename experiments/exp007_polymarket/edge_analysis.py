#!/usr/bin/env python3
# DESIGN-ONLY paper forecasting; NO live trading (CLAUDE.md CFTC guardrail).
"""exp007 — retrodictive edge analysis over forecast rows (PAPER ONLY).

Consumes the rows run.py writes to ``results/forecasts.jsonl``
(``{market_id, question, prob, market_prob, outcome, wall_s}``) and does
hypothetical paper accounting on RESOLVED markets. Zero trading surface:
no order, no wallet, no network, no I/O of any kind.

Edge per market is signed: ``edge = prob - market_prob``. A market is
*actionable* when ``abs(edge) > threshold`` AND ``outcome is not None``.

Paper rule (hypothetical 1-unit stake per actionable market):
  - ``edge > +threshold``  -> BUY YES at ``market_prob``; payout 1 if
    ``outcome == 1``, so ``pnl = outcome - market_prob``.
  - ``edge < -threshold``  -> BUY NO at ``1 - market_prob``;
    ``pnl = (1 - outcome) - (1 - market_prob)``.

Purely retrodictive: prices are resolution-time fixture prices, with no
slippage, fees, or sizing (see the ``assumptions`` list in the output).
Malformed rows (e.g. run.py error rows without prob/market_prob) are
skipped — never raised on — and counted in ``n_skipped``; ``n_total``
counts every input row, so ``len(per_market) == n_total - n_skipped``.
``mean_abs_edge`` is over resolved rows (0.0 when none). ``hit_rate`` is
the fraction of actionable bets with ``pnl > 0`` (None when no bets).
"""
from __future__ import annotations

ASSUMPTIONS = [
    "Purely retrodictive paper accounting on RESOLVED markets only; "
    "no order is or will be placed (zero trading surface).",
    "Prices are resolution-time fixture prices (market_prob captured at "
    "fetch), not executable quotes.",
    "No slippage, no fees, no position sizing: hypothetical flat 1-unit "
    "stake per actionable market.",
]


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def analyze_edges(rows: list[dict], threshold: float = 0.05) -> dict:
    """Paper edge accounting over forecast rows. Pure function, no I/O.

    See the module docstring for the paper rule and field semantics.
    """
    per_market: list[dict] = []
    n_skipped = 0
    n_resolved = 0
    abs_edges_resolved: list[float] = []
    pnls: list[float] = []
    for r in rows:
        if (not isinstance(r, dict) or not _num(r.get("prob"))
                or not _num(r.get("market_prob"))):
            n_skipped += 1
            continue
        outcome = r.get("outcome")
        if outcome is not None and not _num(outcome):
            n_skipped += 1
            continue
        edge = r["prob"] - r["market_prob"]
        side = None
        pnl = None
        if outcome is not None:
            n_resolved += 1
            abs_edges_resolved.append(abs(edge))
            if edge > threshold:
                side = "yes"
                pnl = outcome - r["market_prob"]
            elif edge < -threshold:
                side = "no"
                pnl = (1.0 - outcome) - (1.0 - r["market_prob"])
            if pnl is not None:
                pnls.append(pnl)
        per_market.append({
            "market_id": r.get("market_id"),
            "edge": edge,
            "side": side,
            "pnl_units": pnl,
        })
    n_actionable = len(pnls)
    return {
        "threshold": threshold,
        "n_total": len(rows),
        "n_skipped": n_skipped,
        "n_resolved": n_resolved,
        "n_actionable": n_actionable,
        "mean_abs_edge": (sum(abs_edges_resolved) / n_resolved
                          if n_resolved else 0.0),
        "hypothetical_pnl_units": sum(pnls),
        "hit_rate": (sum(1 for p in pnls if p > 0) / n_actionable
                     if n_actionable else None),
        "per_market": per_market,
        "assumptions": list(ASSUMPTIONS),
    }
