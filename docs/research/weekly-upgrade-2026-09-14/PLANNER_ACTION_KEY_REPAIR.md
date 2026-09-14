# Planner action-key repair after the first topic diagnostic

## Finding

The first registered topic-scope run found a prompt/validator contract mismatch
in the candidate planner arm. `known_actions()` exposes menu documentation as
objects with a `name` field. The executable plan contract and
`validate_plan()` instead require every proposed row to contain exactly the
semantic keys `action` and `args`. The candidate prompt showed both structures
but did not explicitly map one to the other. All eight candidate planner calls
copied the menu representation and emitted `name`; all eight controls emitted
the valid `action` representation.

This failure is useful evidence. The validator rejected the malformed plans,
and the diagnostic never dispatched them. The v1 manifest, raw artifacts and
grades remain unchanged.

## Implemented source repair

Commit `ca39c1a512241341f25845a007097969eddf5ea4` adds one format paragraph to
`orchestrator/coordinator.py`. It says to copy the selected menu object's
`name` value under the output key `action`, forbids `name` in output rows,
requires exactly `action` and `args`, and provides a positive and negative
example.

Two focused tests establish both sides of the contract:

- the rendered planner prompt contains the explicit mapping and examples;
- the production `validate_plan()` rejects the exact minimal
  `{"name": "run_loop_iteration", "args": {...}}` failure and produces no
  normalized action.

The full `tests/test_coordinator.py` file passed 17 tests before the dedicated
commit. No model was called by that implementation/test step.

## V2 diagnostic

The v2 manifest and preregistration are:

- `experiments/topic_scope_repair_v2_2026-09-14.json`
- `experiments/PREREG_topic_scope_repair_v2_2026-09-14.md`

It preserves the original matrix and changes only the candidate planner
prompt plus the metadata needed to identify that source. The v1 run remains
the baseline evidence; v2 is a new experiment and cannot rewrite it.

## Separate hypothesis-prompt diagnosis

The action-key bug explains the candidate planner's protocol failures. It does
not explain the weak hypothesis repair. The candidate hypothesis prompt already
says that collaborative-ML accuracy, throughput and software quality are out
of scope and tells the model to formulate a new game or collective-choice
question. It still permits the model to use the off-scope title as inspiration.
That leaves a wide analogical path: retain the title's actors and methods,
rename components as players or strategies, and keep accuracy/throughput as
the real outcome. The prompt's negative examples are advisory; there is no
mandatory candidate-level rejection step or prohibition on carrying the
off-scope title's nouns, methods and metrics into the reset.

A useful fallback is an **outside-scope reset rule**, leaving the output schema
and in-scope verbatim rule unchanged:

```text
If the input is outside scope, discard its subject matter after classifying it.
Do not reuse its named method, system component, task, metric, or claimed
relationship in any candidate. Generate the replacement from a concrete
game/collective-choice mechanism: players or voters, available actions or
ballots, incentives or aggregation rule, and an outcome such as strategic
behavior, utility, welfare, equilibrium, voting power, or representation.
Before emitting, reject any replacement whose primary outcome is predictive
accuracy, loss, latency, throughput, robustness, or software quality. The
replacement must stand on its own and must not attribute it to the input.
```

That reset changes the estimand. By construction it cannot preserve a useful
game-theoretic mechanism that is genuinely present in an adjacent title, and
it cannot earn the frozen `grounded_transfer` measure. It should therefore be
a separately labeled safe-reset fallback, not the sole or primary repair.

The preferable next single delta is a **candidate-level strategic-mechanism
validation rule**. Preserve grounded transfer when the input supports a real
incentive or collective-choice question, but make the worker discard any
candidate whose actual dependent variable remains only model accuracy,
training throughput or software performance. Require it to identify the
decision-makers, feasible strategic choices, incentive or aggregation rule,
and game-dependent outcome before the candidate may be emitted. Accuracy,
robustness or efficiency can still be a legitimate outcome when it is
explicitly downstream of strategic behavior in a defined game; vocabulary
alone remains insufficient. If no candidate passes this internal screen, then
use the separately scored safe reset above.

Neither prompt change has been applied to the v2 planner-format repair or
tested. A future diagnostic must retain T5/T6/T7, blind semantic review,
grounded-transfer versus safe-reset labels, generic-output counts, and R0
disagreement. A fixed reset that emits the same unrelated game for every title
would be scope-safe but scientifically unhelpful, so diversity and
substantive-mechanism checks remain necessary.
