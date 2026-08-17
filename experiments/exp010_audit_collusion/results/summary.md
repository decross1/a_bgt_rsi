Verdict=NO. neither the level effect (rule 1) nor the timing mechanism (rule 2) met its LOCKED criterion.

# exp010 — audit-cadence collusion summary

Claim under test (cl-iter-2026-07-13-001, L1): periodic audits increase collusion rates in non-equilibrium markets via predictable-cadence timing. LOCKED prereg: experiments/PREREG_l2block_2026-08-17.md.

## Rule 1 — level effect (LOCKED)

- median collusion_rate PERIODIC: 0.0000 (n=40)
- median collusion_rate RANDOM: 0.0000 (n=40)
- median gap: 0.0000 (>= 0.05: False)
- one-sided MWU (PERIODIC > RANDOM) p: 6.775e-05 (< 0.01: True)
- rule 1 pass: False

## Rule 2 — mechanism gate (LOCKED)

- mean PERIODIC timing_gap (zeros included, n=40, null=0): 0.0252 (>= 0.1: False)
- one-sided Wilcoxon signed-rank p (zero_method=pratt): 8.744e-06 (< 0.01: True)
- rule 2 pass: False

## Q1 adjudication (LOCKED, non-gating)

Q1 (any monitoring reduces collusion vs no-monitoring): REFUTED
- NONE vs PERIODIC: median gap 0.0000, MWU p 7.312e-01, supported: False
- NONE vs RANDOM: median gap 0.0000, MWU p 6.217e-04, supported: False

## Diagnostics (reported, non-gating)

### PERIODIC

- seeds: 40 valid, 0 error
- collusion_rate mean/median: 0.0220 / 0.0000
- fraction of seeds with collusion_rate >= 0.5: 0.0000
- per-agent collude-rate audit/non-audit rounds: 0.0055 / 0.0812

### RANDOM

- seeds: 40 valid, 0 error
- collusion_rate mean/median: 0.0029 / 0.0000
- fraction of seeds with collusion_rate >= 0.5: 0.0000
- per-agent collude-rate audit/non-audit rounds: 0.0132 / 0.0155

### NONE

- seeds: 40 valid, 0 error
- collusion_rate mean/median: 0.0075 / 0.0000
- fraction of seeds with collusion_rate >= 0.5: 0.0000
- per-agent collude-rate audit/non-audit rounds: n/a / 0.1270

### Placebo — RANDOM-arm timing_gap

- mean/median: 0.0005 / 0.0000 (n=40, null=0)
- expected ≈ 0; a materially positive RANDOM gap flags metric contamination — reported, non-gating

Metric ceiling on record: a perfectly-timed PERIODIC pair caps at collusion_rate ≈ 0.875 while blind RANDOM collusion can approach 1.0; rule 1 therefore effectively requires RANDOM ≤ ~0.825.

Rows: 120 (errors: 0). Counts match LOCKED design: True.
