# Flash payoff-assistance plans — preregistration

## Claim boundary

This study asks one narrow question: **under a frozen set of repeated
four-player public-goods scenarios, does access to an exact payoff-table tool
change Flash's one-round arithmetic accuracy or exact plan regret?** It does not test
market returns, equilibrium play, a trading strategy, general intelligence,
or production readiness. A result cannot by itself promote a finding to L2.

The current confirmatory design draft contains 30 distinct scenario pairs. Each
pair is evaluated once without a tool and once with a native tool. A scenario
pair—not a request, round, retry, or duplicated deterministic response—is the
independent unit. The panel is a finite designed panel and is not claimed to be
an IID sample from a broader population.

The 12-unit pilot associated with `iter-2026-09-15-007` motivates this design
only. Its responses, scores, and units are not carried into either cohort.

**Current execution status:** only the three-scenario technical shakedown is
preparable and runnable. Confirmatory preparation and execution fail closed.
The 30-scenario source panel exposed a design limitation during adversarial
review: 25 cells are analytical controls with a trivial full-horizon optimum;
only the five grim-opponent/own-payoff cells are horizon-sensitive. Before a
confirmatory version can be registered, that strategic panel must be broadened
or an explicit owner decision must retain it with objective-by-script strata.
Aggregate plan success may never be presented as a strategic-effect estimate.

## Frozen design

- Four players, eight rounds, binary contribute-all/retain-all actions.
- Public-goods payoff for player `i`:
  `E*(1-a_i) + m*E*sum(a)/4`.
- Scripted opponents: always retain, always contribute, or grim (contribute
  until the focal player first retains, then retain thereafter).
- Declared objective: focal player's cumulative payoff or cumulative group
  payoff.
- Two paired arms per scenario: direct and native payoff-table tool.
- Direct arm: one call. Tool arm: exactly one tool call plus one final call
  only when the invocation is exact. There are at most 90 calls.
- Deterministic inference: temperature 0, top-p 1, top-k 64, thinking off,
  256 output tokens, 30 seconds per call, 3,600 seconds for the run.
- No retry, repair, best-of-N, or post-hoc prompt change.

The tool reports exact reduced-rational payoff tables for focal action 0/1 and
0..3 other contributors. It reports formulas and values, but no opponent
trajectory, recommendation, optimal action, oracle plan, or regret.

Each final answer must be one bare JSON object containing an eight-action plan
and the focal/group **one-round** payoffs for a separately disclosed four-action
snapshot. This arithmetic probe does not depend on the opponent script, state,
or lookahead. Exact parsing and exact rational equality determine arithmetic
comprehension. A source-frozen simulator and dynamic-programming oracle then
score the separate strategic plan's cumulative objective regret. A
deterministic myopic controller is reported as a control. Invalid output is a
failure and remains in every denominator.

## Cohorts and order

The three-scenario shakedown is permanently disjoint from any confirmatory
panel. It may test transport, timing, parsing, and evidence replay only. Its
outputs are never pooled into the 30-scenario result or used as scientific
evidence. A future confirmatory version may run only after redesign review,
successful shakedown gates, and registration in the campaign/admission layer.

Arm order, scenario parameters, probe plans, exact controls, runtime identity,
source hashes, request policy, limits, and declared slots are frozen in a plan
before any request. Raw local SSE and private request/response metadata remain
outside Git and are independently replayed.

## Reporting

Report exact numerators and denominators for:

- strict valid plans;
- exact comprehension probes;
- exact native tool invocations;
- zero-regret plans;
- plans at least as good as the myopic control;
- complete paired scenarios; and
- tool-minus-direct regret direction among complete pairs.

Report failures, missing/ragged cells, timeouts, wire-unknown attempts, and
pre-wire failures. Do not report p-values, statistical significance, a
population-generalization claim, or an L2/strategy/model-upgrade conclusion.
