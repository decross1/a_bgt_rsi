# Pre-registration — topic-scope planner action-key repair v2

**Prepared:** 2026-09-14
**Status:** registered inputs only; v2 has not been executed
**Domain:** game theory, behavioral game theory, learning in games, and the
D-075 delegation/liquid-democracy/social-choice/sortition extension

## Why this follow-up exists

The immutable v1 diagnostic remains the evidence of record. Its manifest is
`experiments/topic_scope_repair_2026-09-14.json`, SHA-256
`aab09640a9d377fc0a2a1c830223f5cd8b4e7e20299ac968d7bd01f2512b06a2`.
That run returned 79 of 80 declared calls because one control hypothesis did
not satisfy the chosen-candidate contract and therefore had no primary-R0
input. All eight candidate planner completions used menu-shaped
`{"name": ..., "args": ...}` objects. The frozen and production validators
require `{"action": ..., "args": ...}`, so all eight candidate planner
completions were protocol-invalid; all eight control planner completions were
valid. This is retained as a failed candidate result, not regraded.

Independent blind semantic annotation also left v1 `INVALID/INCOMPLETE` as an
overall topic repair: the candidate produced 13 of 45 annotated outputs that
were out of scope, two generic outputs, and only one of six grounded repairs
on the three repair topics. Primary R0 marked 14 candidate choices on-domain
while the independent reviewer marked 11, giving three disagreements. The
planner key repair cannot fix those hypothesis-generation failures.

## Single registered delta

V2 changes one experimental prompt: `arms[candidate].planner_system`. The
added text explains that menu objects use `name`, while output plan objects
must copy that value to `action`; it forbids an output `name` key and includes
positive and negative examples. The rendered prompt is sourced from the
dedicated commit:

`ca39c1a512241341f25845a007097969eddf5ea4`

The control prompt, both hypothesis prompts, topic inputs and anchors, planner
menu and states, primary-R0 prompt, sampling settings, seeds, order and request
ceilings are byte-for-byte unchanged from v1. The harness validates this
lineage against the original v1 manifest rather than trusting this statement.

The new immutable manifest is:

`experiments/topic_scope_repair_v2_2026-09-14.json`

- Manifest SHA-256:
  `fbe8d2740e50c08af1f28a94ac5d45bcb6237418cb6f8cbddb428375414ab3f3`
- Candidate planner-prompt canonical SHA-256:
  `4cd842a95e87ab5be39d9fce1b50339e4ee28f0d5c33a310eb3a9f6b7c505754`
- Superseded v1 candidate planner-prompt canonical SHA-256:
  `22f999016a6ee213fbdaa297c45439d5967d5f0268b3a169c04cb2f77d0fcbdf`

## Frozen matrix and resource envelope

The v1 matrix is repeated intact so no favorable rows can be selected after
seeing v1:

- eight topics, including exact T6;
- four planner states;
- control and candidate arms;
- seeds 17 and 29;
- alternating AB/BA order with reversed case order on seed 29;
- 32 hypothesis, 16 planner and 32 primary-R0 cells;
- serial calls, at most 30 seconds per hypothesis/planner request and 15
  seconds per primary-R0 request;
- 2,370-second evaluator payload inside a 2,400-second registered reservation;
- every error, deadline, missing dependent call and unparseable response stays
  in the denominator.

The unchanged hypothesis and R0 calls are intentionally inefficient. They
preserve the paired full-matrix contract and expose stochastic regressions;
their outcomes cannot be credited to the planner-format delta. If the shared
7,200-second weekly ledger cannot reserve the full card, defer this diagnostic
rather than dropping rows or changing only one arm.

## Predeclared checks

The format repair is supported only if all of the following hold:

1. All eight candidate planner calls return and validate under the frozen
   action menu.
2. None of the eight parsed candidate plans contains an output object with a
   `name` key in place of `action`.
3. Candidate P1, P2 and P4 select the preregistered preferred topic on both
   seeds and copy it exactly; candidate P3 selects no off-scope suggestion.
4. No candidate planner call exceeds its deadline, changes runtime identity,
   or produces an off-menu/unbudgeted plan.

Report the unchanged control cells as a drift sentinel. Do not delete a failed
control or candidate cell to make the checks pass.

Possible conclusions are:

- `FORMAT_CONTRACT_REPAIRED`: checks 1, 2 and 4 pass.
- `PLANNER_SCOPE_SIGNAL`: all four checks pass.
- `FORMAT_REPAIR_FAILED`: any of checks 1, 2 or 4 fails.
- `PLANNER_SCOPE_FAILED`: the format contract passes but check 3 fails.
- `INVALID/INCOMPLETE`: artifacts, provenance, transport, runtime identity or
  independent annotations are incomplete.

These are diagnostic labels. None authorizes dispatch, role-policy promotion,
runtime changes, service reload, scheduling, or a scientific-quality claim.

## Execution and artifact rules

Run only through a separately registered dispatcher card after it binds the
new manifest and execution-dependency hashes. Use a fresh output outside the
repository and live state roots. The harness records raw output before parsing,
does not dispatch menu actions, and exports a path-separated blind grading
package. Raw completions and the private arm map remain outside Git.

Offline planning is safe and makes no model calls:

```bash
.venv-chroma/bin/python -m bench.weekly_upgrade_eval.topic_scope --plan \
  --manifest experiments/topic_scope_repair_v2_2026-09-14.json --include-r0
```

Do not run the evaluator directly to bypass the shared weekly budget, GPU and
coordinator leases. A live command belongs in the dispatcher runbook after the
new card is committed and clean.
