# exp006 — semi-synthetic mechanism-DESIGN summary

This IS the semi-synthetic mechanism-DESIGN tier: the LLM designed each mechanism (allocation + payments), scored against the VCG benchmark. No single ground-truth output exists.

**Verdict: NO** — mean allocative efficiency 0.710 and feasibility_rate 52.50% did not jointly clear the 0.90 / 90% pre-registered thresholds.

## Headline metrics

- Trials: 40 (errors: 0)
- Designer mean allocative efficiency: 0.710
- Feasibility rate: 21/40 (52.50%)
- Matches-VCG-allocation rate: 15/40 (37.50%)
- Parse failures: 13/40

## Efficiency statistics

Allocative efficiency = realized welfare of the LLM-designed allocation / optimal welfare, over the TRUE valuations.

- per-trial allocative efficiency: n=40 mean=0.710 median=0.983 sd=0.533 min=0.000 max=1.844

## Verdict thresholds (pre-registered)

- YES iff mean efficiency >= 0.90 AND feasibility_rate >= 90%.
- INVALID iff feasibility_rate < 50% (efficiency mean unreliable; not coerced to pass/fail).
- NO otherwise.
