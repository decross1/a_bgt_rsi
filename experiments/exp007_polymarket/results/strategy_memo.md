# exp007 — Polymarket PAPER strategy memo

> PAPER STRATEGY ONLY. No real trading. No live capital at risk. For research purposes only. Do not use to place real orders.

**Headline:** Verdict=BELOW_MARKET. Brier Skill Score vs the market-implied probability over 18 resolved markets: -4528257032.8441 (forecasting skill, not trading P&L).

## Top edges (hypothetical, retrodictive)

| market_id | edge | side | pnl_units |
| --- | --- | --- | --- |
| 63 | +1.0000 | yes | +0.0000 |
| 19 | +0.9500 | yes | -0.0000 |
| 64 | +0.7500 | yes | +0.0000 |
| 57 | +0.6500 | yes | +0.0000 |
| 47 | +0.5500 | yes | +0.0000 |

## Paper rule

Hypothetical 1-unit stake per actionable market (abs(prob - market_prob) > threshold, resolved markets only): BUY YES at market_prob when edge > +threshold (pnl = outcome - market_prob); BUY NO at 1 - market_prob when edge < -threshold (pnl = (1 - outcome) - (1 - market_prob)). Retrodictive paper accounting only — no order is or will be placed.

Assumptions:

- Purely retrodictive paper accounting on RESOLVED markets only; no order is or will be placed (zero trading surface).
- Prices are resolution-time fixture prices (market_prob captured at fetch), not executable quotes.
- No slippage, no fees, no position sizing: hypothetical flat 1-unit stake per actionable market.

## Limitations

- Retrodictive: forecasts were made on already-resolved markets, so this measures calibration against the frozen fetch-time price, not live tradability.
- Fixture prices, no order book: no slippage, no fees, no fill uncertainty, no position sizing; pnl units are not money.
- Small, non-random market sample; hypothetical units do not compound.
- Polymarket is design-only (CLAUDE.md out-of-scope) until CFTC compliance work is done; this memo must never drive a real order.
