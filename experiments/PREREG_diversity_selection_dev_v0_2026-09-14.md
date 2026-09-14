# Preregistration — Gemma diversity plus objective selection v0

**Prepared:** 2026-09-14, before any call for this suite
**Suite:** `gemma-diversity-selection-public-dev-v0-2026-09-14`
**Evidence class:** public synthetic development
**Production authority:** none

## Question

On five finite game-theory and collective-choice construction tasks, does a
three-seed exploratory scaffold plus deterministic selection return more
distinct valid proposals than one deterministic call asked to generate and
select among three proposals?

The evaluator uses no semantic or frontier-model judge. It enumerates or
directly checks feasibility from the declared game, ballot, delegation,
payoff, or coalition rules. “Diversity” means distinct canonical feasible
solutions. It does not mean scientific novelty, usefulness outside these
tasks, or general research quality.

## Frozen artifacts

- Manifest: `experiments/diversity_selection_dev_v0_2026-09-14.json`
- Literal manifest SHA-256:
  `0d1bb84609d7d7ea6f3c60a3ea4ae5a2670c727b47fe3400b906c1af68314ff4`
- Canonical configuration SHA-256:
  `e0895d859281c939f8df9794ae4f0b52373fbe4e4953a29420d64a04a8db88ed`
- Manifest loader SHA-256:
  `34905c2f4fd18334ef3224ff53b3557e99585b5159014708420d0ca6fc335806`
- Objective graders SHA-256:
  `f804340ee5397bae9bda908e64096cdd85c4d8cbd7c8c7c8656dcd79b25f6efd`
- Runner SHA-256:
  `f3113ba55b4c01aceaca61180b5d796a9860885ba1a5086c64b2fe747e048506`
- Receipt validator SHA-256:
  `d74d62067fe544d68fa5b587fbf94c351d1032776ec7c3a388275863bf2eef5d`

The manifest freezes literal task objects, model identity, profiles, seeds,
order, output caps, deadlines and resource ceilings. A controller that admits
a live run must also bind these committed execution-source hashes and a clean
Git execution tree.

## Conditions and matched budgets

Both conditions use served model `gemma-4-26b-a4b` on backend `vllm-gemma`.

**Control:** one `deterministic` call, seed 0, asked to return exactly three
proposals and its selected index. Its maximum output is 1,280 tokens and its
request deadline is 80 seconds.

**Diverse plus selection:** three independent `explore` calls, seeds 11, 29
and 47, each returning one proposal with a 384-token and 20-second cap; then
one `deterministic` validator call, seed 0, with a 128-token and 20-second cap.
The validator sees only parsed candidate objects or null placeholders, the
task and the public feasibility contract. It does not receive grader answers.

Thus each condition has an exact 1,280-token output ceiling and 80-second
request-time ceiling per task. They deliberately differ in request count and
input-token work; no claim of matched total compute or API cost is permitted.
There are no retries. Condition-group order alternates by task:

```text
task 1: control, diverse_select
task 2: diverse_select, control
task 3: control, diverse_select
task 4: diverse_select, control
task 5: control, diverse_select
```

Each diverse group always runs proposal seeds 11, 29, 47 before its validator.
The validator call's `parent_request_id` is the last successfully returned
proposal request ID; its prompt contains the three parsed proposal slots. The
receipt reconstructs both links and rejects an unrelated or substituted
selection call.

## Tasks and feasibility sets

The visible panel contains:

1. two pure equilibria in a fixed 2×2 coordination game;
2. six seven-voter profiles where plurality elects A and Condorcet elects B;
3. nine three-voter delegation graphs resolving to A=2, B=1 without exhaustion;
4. thirty bounded integer coordination matrices with two strict diagonal
   equilibria and mixed probability 0.5; and
5. three minimal winning coalitions in `[6:4,3,2,1]`.

The loader re-enumerates each finite domain and refuses a task with fewer than
two valid solutions. Exact proposal schemas prevent explanatory text or extra
fields from receiving credit. Coalition order is canonicalized so a reordered
coalition is a duplicate rather than spurious diversity.

## Outcomes

The primary descriptive estimand is:

```text
sum(valid_unique_count across five diverse_select outcomes)
minus
sum(valid_unique_count across five control outcomes)
```

Report the five paired per-task differences as well as the sum. Secondary
outputs are valid proposal count, selected-valid, task success and objective
recovery: selecting a valid candidate when at least one candidate is invalid.

A task success is creditable only when all calls declared for its condition
returned, every returned runtime identity matches, every completion schema
parsed, at least one proposal is objectively valid, and the selected proposal
is valid. Missing, timed-out, errored, oversized, malformed and drifted calls
remain in the 25-call denominator. The raw completion is durable before any
parse or grade. A validator failure cannot be replaced by the harness choosing
the objectively best slot.

Five public tasks and one frozen seed set yield development evidence only.
Any apparent advantage must be repeated on a separately frozen or held-out
panel before changing a production inference policy.

## Resource and mutation boundary

- 25 calls, serial.
- Maximum request-time envelope: 800 seconds.
- Evaluator payload ceiling: 850 seconds.
- Proposed controller reservation: 880 charged Spark GPU-seconds.
- Maximum retained raw completion: 131,072 bytes per call.
- Outputs go only to a fresh external directory.
- No action dispatch, tool execution, scheduler change, service mutation,
  production-ledger write, frontier API call or promotion decision.

The canonical shared weekly controller must reserve the entire 880 seconds
within the 7,200-second Spark cap. If the complete matrix does not fit, defer
it whole rather than remove a seed, task, validator or condition.

## Offline command

```bash
python3 -m bench.weekly_upgrade_diversity.runner \
  --plan \
  --manifest experiments/diversity_selection_dev_v0_2026-09-14.json
```

This command only validates and prints the frozen 25-call plan. This document
does not itself register or run the experiment.
