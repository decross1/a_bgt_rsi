# exp007 — Polymarket paper-forecasting summary

DESIGN-ONLY paper forecasting; NO live trading (CLAUDE.md CFTC guardrail).

**Verdict: BELOW_MARKET**

This is a paper-forecasting result — forecasting skill vs the market price, NOT trading P&L. No position, no order, no money.

## Headline metrics

- Resolved rows scored (n): 18 (errors: 0)
- Mean Brier (model): 0.2443
- Mean Brier (market): 0.0000
- Brier Skill Score (model vs market): -4528257032.8441
- Calibration note: model trails market over 18 resolved rows (BSS=-4528257032.8441)

## Verdict rule

- INSUFFICIENT iff n < 10.
- BEATS_MARKET iff BSS > 0 over at least the minimum sample (model better-calibrated than the contemporaneous market price).
- BELOW_MARKET otherwise.
