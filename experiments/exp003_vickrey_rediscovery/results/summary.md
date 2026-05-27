# exp003 — Vickrey rediscovery summary

**Verdict: YES** — LLM bidders DID rediscover truthful bidding as the dominant strategy in a sealed-bid second-price auction.

50/50 trials (100%) had mean |residual| <= 5, meeting the 75% pre-registered threshold.

## Headline metrics

- Trials: 50 (errors: 0)
- LLM calls: 200
- Parse failures: 0/200 (0.0%)
- Tie-break trials: 0/50
- Truthful fraction at eps=5.0: 50/50 (100.0%)
- Truthful fraction at eps=10.0: 50/50 (100.0%)

## Residual statistics

Residual = bid - private_valuation. Truthful bidding under Vickrey's theorem implies residual ≈ 0.

- pooled bid residuals (per LLM call): n=200 mean=+0.00 median=+0.00 sd=0.00 min=-0.00 max=+0.00
- per-trial mean |residual|: n=50 mean=+0.00 median=+0.00 sd=0.00 min=+0.00 max=+0.00

## Verdict threshold (pre-registered)

YES iff fraction of trials with mean |residual| <= 5.0 is >= 75%.
