# exp004 — combinatorial-auction truthfulness summary

exp004 is the HARDEST SYNTHETIC rung: combinatorial auctions over two items with KNOWN optimal solutions. It is the on-ramp to — NOT yet — the semi-synthetic mechanism-DESIGN tier (the mechanisms here are hand-written and verified against brute-force optimal welfare).

Trials: 150

## Per-mechanism verdicts

### first_price

**Verdict: YES — 1737/1800 per-bundle bids (96.5%) within eps=5, threshold 75%.**

- truthful_fraction (eps=5): 0.965
- mean_efficiency: 0.999
- mean_revenue: 82.93
- parse_failure_rate: 0.000

### sequential_second_price

**Verdict: YES — 1737/1800 per-bundle bids (96.5%) within eps=5, threshold 75%.**

- truthful_fraction (eps=5): 0.965
- mean_efficiency: 0.977
- mean_revenue: 61.14
- parse_failure_rate: 0.000

### vcg

**Verdict: YES — 1737/1800 per-bundle bids (96.5%) within eps=5, threshold 75%.**

- truthful_fraction (eps=5): 0.965
- mean_efficiency: 0.999
- mean_revenue: 63.66
- parse_failure_rate: 0.000

## Verdict rule (pre-registered)

Per mechanism: YES iff truthful_fraction >= 0.75; otherwise NO. BUT if parse_failure_rate > 0.25, the verdict is INVALID and overrides the truthful test — a high parse-failure run defaults bid:=valuation and would otherwise read as falsely truthful (carryover #4).
