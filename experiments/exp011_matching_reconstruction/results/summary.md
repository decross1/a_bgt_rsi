Verdict=NO. median tau 0.6742 < 0.9; only 30% of trials reached tau >= 0.8 (requires >= 90%).

# exp011 — stable-matching preference reconstruction

metric: `median_kendall_tau_at_termination` = 0.6742
trials: 40 (valid 40, errors 0)

## Locked decision rules

1. median tau >= 0.9 within Q <= 44: observed 0.6742 (max queries 44) -> FAIL
2. >= 90% of trials >= tau 0.8: observed 30% -> FAIL

## Attribution

Case (i) budget-limited: constraints were still accruing in the final 5 queries (median constraints_in_last5_queries = 1.5 > 0) — consistent with the panel's query-complexity refutation. exp011 counts as evidence FOR the refutation in this case.

## Non-gating diagnostics

- median queries_used: 36 (budget 44)
- median unresolved_pairs: 21.5 of 66
- median bits_per_query: 0.730 (log2(12!) = 28.8 bits required)
- median constraints_recorded: 27
- median of per-trial median deviation_size: 0.5
- median null tau p95 (100-permutation chance baseline): 0.3652

## Scored tau stratified by rank of t's best natural proposer

- rank 1: n=5, median tau 0.3636
- rank 2: n=8, median tau 0.5758
- rank 3: n=10, median tau 0.6439
- rank 4: n=4, median tau 0.7273
- rank 5: n=5, median tau 0.7879
- rank 6: n=1, median tau 0.8788
- rank 7: n=2, median tau 0.9242
- rank 9: n=1, median tau 0.9697
- rank 10: n=2, median tau 1.0000
- rank 11: n=1, median tau 1.0000
- rank 12: n=1, median tau 1.0000

## Control-arm caveat

No random-perturbation control arm was run in this block; the 2026-08-15 frontier methods review asked for one and the pre-registration requires its absence to be stated here.
