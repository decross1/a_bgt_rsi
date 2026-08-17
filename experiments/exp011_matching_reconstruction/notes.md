# exp011 — stable-matching preference reconstruction

Claim under test (cl-iter-2026-07-15-001, L1): "An adversary can
reconstruct the preference rankings of a specific agent by observing
the deviation in the resulting stable matching when a small, targeted
subset of agent preferences is perturbed."

Pre-registration (LOCKED): `experiments/PREREG_l2block_2026-08-17.md`
§exp011. Decision-rule constants in `analyze.py` are copied verbatim
from it. Fully numerical — zero LLM calls per trial.

## How to run

```bash
# 40 trials, base seed 20260817 (defaults; milliseconds-scale)
./.venv-chroma/bin/python experiments/exp011_matching_reconstruction/run.py
./.venv-chroma/bin/python experiments/exp011_matching_reconstruction/analyze.py
# bridge (dry-run default; --live needs env -u MOCK_LLM + Gemma)
./.venv-chroma/bin/python experiments/exp011_matching_reconstruction/loop_bridge.py
```

## Locked decision rule

effect_confirmed = TRUE iff BOTH: (1) median scored Kendall tau >= 0.90
at attack termination within Q <= 44 and <= 2 perturbed lists per query;
(2) >= 90% of trials reach tau >= 0.80. Verdict=NO attribution is the
locked two-case rule: (i) budget-limited iff median
constraints_in_last5_queries > 0 (evidence FOR the panel's
query-complexity refutation); (ii) attack-limited iff unresolved_pairs
plateaued with idle budget (adjudicates neither).

## Implementation decisions (within the locked design)

- **Mode-2 constraint recording.** The prereg pins Mode 1's recording
  verbatim and, for Mode 2, only the probe structure (promote-a +
  demote-frontier-f, k=2, deterministic schedule targeting the largest
  constraint-unordered group). Mode 2 records via the prereg's own
  "provably proposed" principle applied to the observed full matching:
  any man whose observed partner sits strictly below t on his own
  PERTURBED list must have proposed to t and been rejected, so
  mu'(t) >_t that man. Mode 1 records exactly the pinned constraints
  and nothing more.
- **Current known frontier f.** Recomputed each Mode-2 query from the
  constraint closure: the lowest man known to dominate every member of
  the largest unordered group (fewest men known below him; tie-break by
  index); fallback = the baseline match of t. Largest unordered group =
  exact maximum antichain (brute force over 2^12 masks, lowest-mask
  tie-break).
- **Mode-2 early termination.** The schedule tracks issued (a, f)
  pairs; since the mechanism is deterministic, re-issuing one is a
  no-op, so the attack stops when the schedule is exhausted (plateau)
  or all 66 pairs resolve — "attack may terminate early" per prereg.
- **Merge-sort fallback on unresolved comparisons.** When a Mode-1
  probe returns c not in {a, b}, the merge takes the LEFT element
  (stable, deterministic). The merge output is never scored; only the
  recorded constraint DAG is.
- **bits_per_query** counts DISTINCT directly-recorded constraints /
  queries_used. **constraints_in_last5_queries** counts new-to-the-set
  direct constraints recorded in the final 5 issued queries (an edge
  already implied by transitive closure still counts if the direct edge
  is new — a slightly liberal reading toward case (i)).
- **rank_t_best_natural_proposer** is 1-based (1 = t's most preferred)
  rank of t's baseline match in t's true ranking.
- **Null baseline**: per trial, 100 uniform random permutations scored
  with the plain (all-pairs) Kendall tau against the true ranking;
  null_tau_p95 = 95th percentile.

## Caveat on record

No random-perturbation control arm was run in this block (requested by
the 2026-08-15 frontier methods review); `analyze.py` states its
absence in both summary outputs, per the prereg.
