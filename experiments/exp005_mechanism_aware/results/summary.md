# exp005 — mechanism-aware bidding summary

exp005 sharpens exp004's rediscovery probe: the bidder is told each mechanism's PAYMENT rule in plain mechanics (no auction-theory priming) and bids SEPARATELY into each one. The headline signal is the MEAN SIGNED RESIDUAL (bid - valuation): a NEGATIVE mean under first_price = bid-shading; ~0 under vcg = truthful.

Trials: 50

## Per-mechanism verdicts

### first_price

**Verdict: YES — 559/600 per-bundle bids (93.2%) within eps=5, threshold 75%; mean signed residual -1.56.**

- truthful_fraction (eps=5): 0.932
- mean_signed_residual: -1.565
- parse_failure_rate: 0.000

### sequential_second_price

**Verdict: YES — 572/600 per-bundle bids (95.3%) within eps=5, threshold 75%; mean signed residual -1.31.**

- truthful_fraction (eps=5): 0.953
- mean_signed_residual: -1.312
- parse_failure_rate: 0.000

### vcg

**Verdict: YES — 485/600 per-bundle bids (80.8%) within eps=5, threshold 75%; mean signed residual -4.90.**

- truthful_fraction (eps=5): 0.808
- mean_signed_residual: -4.902
- parse_failure_rate: 0.000

## Verdict rule (pre-registered)

Per mechanism: YES iff truthful_fraction >= 0.75; otherwise NO. BUT if parse_failure_rate > 0.25, the verdict is INVALID and overrides everything — a high parse-failure run defaults bid:=valuation, which would read as falsely truthful and drag the mean signed residual toward 0, masking shading (carryover #4).
