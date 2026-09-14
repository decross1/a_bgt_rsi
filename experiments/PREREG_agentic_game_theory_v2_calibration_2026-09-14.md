# V2 first study: incentives, information and agent cooperation

Campaign: `v2-agentic-game-theory-20260914`. This is a CPU calibration and a study-design starting point. It schedules no local or frontier model calls and is not a claim of research novelty.

Four agents receive five units each per round and either retain or contribute all five. The public pool is doubled and divided equally. Material payoff is `5 - contribution + 2 * total_contribution / 4`. Enumerate all sixteen stage profiles and sixty-four unilateral comparisons for each utility definition. Individual material payoff makes retention strictly dominant. Joint material payoff makes contribution strictly dominant. These are different games because the utility functions differ; a cooperation increase alone is not an improvement in rationality.

For eight-round classical controls, enumerate all 81 assignments of retain, contribute and previous-majority policies across four players, under both utility labels and both observation contracts: 324 simulations. Policies remain fixed across objectives; this does not pretend to measure incentive responsiveness of classical policies. Exact rational arithmetic records payoffs and stage utility regret. Stage regret does not establish repeated-game optimality.

The information manipulation needs care: own payoff and own contribution already reveal aggregate contributions in this game. Public history additionally reveals player identities. The previous-majority baseline must therefore act identically under the two observation contracts. A design that called the private arm uninformed would be confounded. Later identity-sensitive reciprocity tasks must explicitly address this and counterbalance identity labels/opponent placement.

Before any LLM trial: complete the literature/novelty gate, freeze tasks and policies, define a bounded reservation under the existing weekly cap, decide repeated samples and paired uncertainty analysis, and validate strict action transport. Separate protocol failures, wrong utility calculations, strategic choices, and scientific claims. Retain all scheduled attempts and failures in denominators. Never present CPU calibration as a completed scientific finding or an LLM benchmark win.

Primary screen and related-work boundaries: [external context](../docs/v2/research/EXTERNAL_CONTEXT.md). LLM games involving competition/cooperation already have substantial prior work. The initial value is a reliable, project-specific measurement apparatus and an evidence-grounded question, not a presumed novel result.

Run the local control with:

```bash
python -m bench.agentic_game_theory.calibration --output /absolute/fresh/path/calibration.json
```

The result binds source and manifest hashes, records zero model calls, preserves all action traces, and refuses output-file overwrite. Legacy research ledgers and earlier benchmark scores are untouched.
