# V2 first LLM phase: known-opponent optimal response

This refines the [initial calibration](PREREG_agentic_game_theory_v2_calibration_2026-09-14.md) after independent Claude design review. It retains campaign `v2-agentic-game-theory-20260914` and makes no model calls. The first LLM phase isolates the utility objective; the player-identity observation factor is deferred until there is an explicit causal mechanism and matched information salience.

Use one LLM seat against three committed scripted bots. The three opponent groups are all-retain, all-contribute, and all-grim-trigger. A grim bot starts by contributing and retains forever after any player defects in an earlier round. Actions within a round are simultaneous. The exact script, payoff formula, prior state and eight-round horizon must be disclosed to the model. Otherwise a perfect-information oracle could not grade rationality under the model's information set.

Use neutral labels for scoring rule A/B and give the actual formula. In the individual rule utility is the focal player's material payoff; in the joint rule it is the sum of all material payoffs. Public history includes the aggregate explicitly. A separate comprehension question tests payoff arithmetic before game play; retain comprehension failures as their own category and in the preregistered episode denominator. The comprehension item may prime behavior, so both arms must receive a matched item and its inclusion must be frozen.

`bench/agentic_game_theory/optimal_control.py` solves the finite-horizon response exactly with dynamic programming and validates it against exhaustive action sequences in tests. Against three grim bots under individual utility, the optimum is seven contributions followed by last-round defection: utility 82.5 versus 47.5 for immediate defection. This makes repeated-game utility consistency distinct from cooperation. It is a best response to committed scripts, not a claim about equilibrium among four independently strategic agents or human behavior.

The starting design has three opponent groups × two utility rules × two focal seat positions = twelve cells. A game uses eight LLM action calls plus a comprehension call, rather than thirty-two player calls. Twelve cells with one episode each are an engineering pilot, not twelve independent replications per condition. Choose repeated episodes, seeds, order/label counterbalancing and a paired statistical plan only after measuring actual latency under a frozen model policy and the remaining weekly cap. Never assume the 324 earlier condition checks are 324 independent observations.

Primary future outcomes: valid actions / scheduled actions, payoff comprehension, episode utility, exact episode regret, focal-seat cooperation rate, group cooperation rate, wall time and calls including all failures. Per-decision regret is measured against optimal continuation and telescopes to episode regret; it is not stage-game regret. Report all ties as optimal. Parser failure cannot be imputed as a strategic defection or cooperation. A treatment effect on an agent with a different disclosed utility function is not a model capability improvement.

CPU validation command:

```bash
python3 -m bench.agentic_game_theory.optimal_control --output /absolute/fresh/path/optimal-control.json
```

Before LLM execution, register a concrete manifest with immutable task/source/model/policy hashes and a bounded reservation. This document is a calibrated study protocol, not that execution admission. Retain the existing research/novelty/evidence gates and human validation boundary.
