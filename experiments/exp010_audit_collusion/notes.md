# exp010 — audit-cadence collusion (cl-iter-2026-07-13-001)

LOCKED prereg: `experiments/PREREG_l2block_2026-08-17.md`
§exp010_audit_collusion. Every decision-rule constant in `analyze.py` is
copied verbatim from that section; changes require a new dated amendment
there, never an edit here.

## What it is

Repeated 2-player pricing game (COLLUDE/DEFECT, T=5000 rounds), two
independent tabular Q-learners per trial, an auditor that fines own-play
COLLUDE F=20 on audit rounds, three arms at equal expected audit
frequency 1/8: PERIODIC (every 8th round, learnable phase), RANDOM
(i.i.d. Bernoulli 1/8), NONE (Q1 adjudication arm). 40 seeds × 3 arms =
120 trial rows; metrics over the last 1000 rounds. Fully numerical —
zero LLM calls in the trial path.

## Run

```bash
# headline run (120 trials, ~seconds; pure numeric, MOCK_LLM-safe)
./.venv-chroma/bin/python experiments/exp010_audit_collusion/run.py
./.venv-chroma/bin/python experiments/exp010_audit_collusion/analyze.py
# bridge (dry-run default; --live needs env -u MOCK_LLM + vllm-gemma)
./.venv-chroma/bin/python experiments/exp010_audit_collusion/loop_bridge.py
```

## Implementation choices the prereg does not pin (recorded, not silent)

- **Initial last-actions**: both agents' `own_last`/`opp_last` start at
  DEFECT at t=0 (the stage game's static equilibrium action). The prereg
  pins the state layout but not t=0 initialization.
- **Greedy tie-break**: deterministic lowest action index (DEFECT) on
  exact Q-ties, so a fixed seed reproduces trajectories bit-for-bit.
- **Sub-seed derivation**: per trial, `random.Random(trial_seed)` draws
  32-bit sub-seeds in pinned order (agent0, agent1, auditor).
- **`mean_collusion` row field**: mean of the two agents' individual
  COLLUDE rates over the measurement window (diagnostic only, distinct
  from `collusion_rate` = both-collude fraction; non-gating).
- **Wilcoxon zero handling** (rule 2): exact-zero timing gaps are
  included in the gated MEAN; the signed-rank test uses
  `zero_method="pratt"` so zeros are ranked rather than silently dropped
  (scipy's default `"wilcox"` would shrink n and overstate the
  mechanism). An all-zero gap vector leaves the test undefined →
  recorded as p=None, rule 2 FAILS (never coerced).
- **Locked-count guard**: the rules were locked at n=40 vs 40 and "ALL
  40 PERIODIC seeds"; `analyze.py` reports statistics on whatever rows
  exist but sets `effect_confirmed=False` (with the deviation stated)
  when counts differ from the locked design.

## EV arithmetic on record (prereg)

Blind mutual collusion earns 10 − 20/8 = 7.5/round > mutual defection 5;
perfectly timed collusion earns 9.375; COLLUDE on a known audit round is
strictly dominated. Metric ceiling: perfectly-timed PERIODIC caps at
collusion_rate ≈ 0.875 while blind RANDOM collusion can approach 1.0, so
rule 1 effectively requires RANDOM ≤ ~0.825.
