# Payoff action-interface calibration — excluded plan

**Status:** development-only, permanently excluded calibration  
**Dispatch:** not performed by this change  
**Scientific admission:** impossible for this cohort

## Purpose

This calibration asks whether the fixed resident Flash model can use three
interfaces while producing the same final response:

1. direct equations only;
2. a complete one-round payoff table; and
3. an exact calculator for one disclosed joint action.

It checks interface transport, current-row binding, exact arithmetic, and
whether a separately returned finite-horizon action plan remains scoreable.
It does not estimate model quality, confirm a research claim, supply L2
evidence, or support a market or production decision.

## Permanently excluded, parameter-disjoint panel

The four cells are source-frozen in `runner.py`. Their endowments
`{6,10,14,18}` are disjoint from the developmental 30-cell panel
`{4,8,12,16,20}`, the older payoff-assistance panels
`{4,5,7,8,9,11,12,13}`, and the known-opponent pilot (`E=5`). The runner also
binds the developmental primary-panel hash, embeds all 30 primary task hashes,
derives old payoff-panel hashes from their source, and source-hashes the pilot.
This is parameter/instance disjointness within the same public-goods game
family. It is not structural OOD coverage or generalization evidence.

| Cell | K | H | E | m | Seat | Probe | Other contributors |
|---|---:|---:|---:|---:|---:|---|---:|
| 01 | 1 | 4 | 6 | 7/6 | 0 | `[0,0,0,0]` | 0 |
| 02 | 2 | 6 | 10 | 8/5 | 1 | `[1,1,0,0]` | 1 |
| 03 | 3 | 9 | 14 | 9/7 | 2 | `[1,1,0,0]` | 2 |
| 04 | 4 | 12 | 18 | 11/6 | 3 | `[1,1,1,1]` | 3 |

Every cell uses the disclosed consecutive-retention trigger: the other three
players contribute while the focal retention streak is below `K`; a focal
contribution resets the streak; reaching `K` makes punishment absorbing. The
objective is cumulative focal material payoff. Dynamic programming and full
enumeration over all `2^H` plans must agree on one exact optimum, which must
strictly beat the deterministic myopic policy and contain a future-dependent
action. All four cells meet those requirements before any request can run.

The four cells cover both focal probe actions, all focal seats, all other-
contributor counts 0–3, and horizons 4, 6, 9, and 12. They are four designed
cases, not IID samples.

## Frozen arms and requests

All arms receive the same equations, game, opponent state machine, objective,
horizon, probe, seed, deterministic no-thinking policy, timeout, and final
response contract. Arm order is frozen per cell before dispatch.

- **Direct:** one final call, no tools.
- **Table:** exactly one table-tool call and, only after an exact invocation,
  one final call.
- **Calculator:** exactly one action-calculator call and, only after an exact
  invocation, one final call.

The table returns all immediate rows and no recommendation. The calculator
returns exact payoffs only for the supplied action and no strategy, action
comparison, state, horizon, regret, optimum, or future utility.

The final object always has exactly `probe` and `actions`. `probe` uses the
same calculator-output schema in every arm. `actions` must contain exactly the
cell horizon's number of binary focal actions.

## Fixed budget and runtime boundary

- 4 distinct units;
- 12 conditions;
- 20 maximum request slots (`1 + 2 + 2` per unit);
- 512 output tokens per call;
- 30 seconds per call;
- 900 seconds aggregate evaluator window;
- temperature 0, top-p 1, thinking off;
- 20 GiB host-memory floor checked immediately before and after every issued
  call, including the last call;
- one nonblocking cooperative GPU lease;
- exact resident checkpoint, runtime image, serving profile, deployment, live
  process/container identity, source hashes, panel hash, plan bytes, and oracle
  plan hashes bound before requests.

The runner uses the existing warm resident. It never starts, stops, restarts,
or changes model serving. Direct HTTP clients cannot be excluded by the
cooperative lease, so this calibration makes no isolated-latency claim.

## Independent validation

The validator must replay every stored raw SSE stream, private request, tool
call, deterministic tool response, calculator output, action plan, exact game
simulation, and public grade. It retains all declared slots, including failed,
skipped, and unissued slots. A complete bundle cannot validate with a pre-wire
failure or zero returned streams.

The grader reports transport/terminal status, JSON shape, numeric
representation, numeric parseability, row binding, contributor counts, exact
arithmetic, action-array validity, action scoreability, utility, regret, and
tool correctness separately. A bad probe does not erase a valid action plan;
malformed top-level JSON makes its contents unscoreable.

## Interpretation

Report per-arm counts over the fixed denominator of four and the raw cell
rows. Any calculator-versus-table difference is an interface-calibration
observation only. The results may be analyzed for instrument diagnostics, but
they are permanently excluded from confirmatory effect estimates, admission,
and L2. No p-value, causal model claim, generalization, evidence-rung movement,
production change, or promotion may be generated from this cohort. A later
study requires a distinct registered panel, verifier, and owner-authorized
dispatch.
