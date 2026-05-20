# Track C — Day 4: fixed PD strategies for exp001_repeated_pd

Side-track drafted on Day 4 for the Day 7 experiment. Track A will
merge this on Day 7 morning, before the LLM-vs-fixed-opponent runs.

## What this lands

- `experiments/exp001_repeated_pd/strategies.py` — four deterministic
  reference strategies for the iterated Prisoner's Dilemma, exposed as:
    1. Pure functions `History -> {'C', 'D'}` (the core, easy to unit
       test).
    2. GRA `BaseAgent` subclasses that wrap each pure function and
       maintain `(own, opp)` history via `observe(own, opp)`.
- `tests/test_strategies.py` — 11 unit tests; runs each strategy for 5
  rounds against a fixed opponent sequence and asserts the produced
  own-action sequence, for both the pure function and the wrapping
  agent.

## Naming — why the in-code names are coded

The four academic-literature names for these strategies are part of
the experiment design. CLAUDE.md / Track-C scope forbids letting any
of these strings reach an LLM prompt or LLM-visible docstring, because
naming them tips the model off to the experimental setup it is being
evaluated in. So this file uses neutral code names internally:

| Code name in `strategies.py` | What the strategy does |
| --- | --- |
| `decide_mirror` / `MirrorAgent` | Round 1 cooperates; subsequent rounds copy the opponent's previous move. |
| `decide_latch` / `LatchAgent` | Cooperates until the opponent ever defects; defects forever afterward. |
| `decide_constant_c` / `ConstantCAgent` | Always cooperates. |
| `decide_constant_d` / `ConstantDAgent` | Always defects. |

These are reference baselines, not the LLM player itself, so the
literature names live only here (and in the human-readable
experiment plan), never in strings the LLM sees.

## Action encoding

OpenSpiel's matrix Prisoner's Dilemma convention:

- action `0` → "C" (cooperate)
- action `1` → "D" (defect)

The pure decision functions trade in the `'C'` / `'D'` letters; the
`compute_action` wrapper translates to OpenSpiel ints via
`strategies.ACTION_INT`.

## GRA contract notes

From `clones/game-reasoning-arena/src/game_reasoning_arena/arena/agents/base_agent.py`:

- `BaseAgent.compute_action(observation: Dict[str, Any]) -> int` is the
  required abstract method. In practice (see `random_agent.py`)
  implementations return `{"action": int, "reasoning": str}` and the
  matrix-game env supplies `observation = {"state_string", "legal_actions",
  "prompt"}`.
- The env does **not** thread per-round opponent history into the
  observation, so each fixed agent maintains its own
  `(own_action, opp_action)` log via an explicit `observe(own, opp)`
  call from the driver after each round.

If the `game_reasoning_arena` package is not importable in the current
venv, `strategies.py` falls back to a tiny in-file `BaseAgent` stub so
unit tests run anywhere. On Day 7 with the real package installed,
the agents drop straight onto the real `BaseAgent`.

## Test coverage

Each strategy is exercised for 5 rounds against a fixed opponent
sequence chosen to make its identity falsifiable:

| Strategy | Opp sequence | Expected own | Tests what |
| --- | --- | --- | --- |
| `decide_mirror` | C D C D C | C C D C D | Round 1 = C; round n = opp[n-1] |
| `decide_latch` | C C D C C | C C C D D | Latches on first opp-D, stays D |
| `decide_constant_c` | D D D D D | C C C C C | Constant under maximum provocation |
| `decide_constant_d` | C C C C C | D D D D D | Constant despite cooperation |

An extra `decide_latch` test ([(C,D),(C,C)…]) confirms the trigger does
not un-latch even after a long cooperative tail from the opponent.

## Out of scope (Track C, Day 4)

- LLM player itself — Track A owns the GPU and the LLM-vs-fixed runs.
- Tournament harness / scoring grid — pulled in on Day 7.
- Stochastic strategies (e.g. generous mirror, win-stay-lose-shift) —
  out of scope for the Day 7 baseline.
