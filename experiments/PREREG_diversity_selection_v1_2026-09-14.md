# Preregistration — Gemma diversity + selection scaffold v1 follow-through

**Date frozen:** 2026-09-14  
**Execution class:** bounded local evaluation only  
**Manifest:** `experiments/diversity_selection_v1_2026-09-14.json`  
**Model:** resident `gemma-4-26b-a4b` on `vllm-gemma`  
**Production change authorized:** no

## Question

On five new, finite game-theory and collective-choice construction tasks, does
three-call directive-separated exploration followed by a strict objective
selector produce more useful independent candidates than a matched
single-call deterministic control?

This tests the complete v1 scaffold. It does not isolate temperature from the
prompt directives, call decomposition, or selector.

## Why this is a new version

The public dev-v0 trial returned all 25 calls, but its exploratory condition
scored 0/5 creditable task successes versus 3/5 for control and produced only
two unique valid proposals versus six. Accepting Markdown-fenced JSON after the
fact would have changed the candidate result only to 1/5, so fence removal is
not an adequate repair.

The v1 follow-through makes only versioned additions:

1. five new task texts, numeric instances, IDs, and seeds;
2. three independent proposal calls with different preregistered search
   directives and no access to one another's output;
3. a selector instructed to choose the lowest-numbered objectively valid slot;
4. explicit separate-reasoning-channel and JSON-only visible-answer wording;
5. a strict local parser that classifies failures and performs no extraction,
   repair, coercion, retry, or salvage.

The dev-v0 manifest, prompts, parsers, scores, and artifacts retain their
original behavior.

## Frozen cells and budgets

For each of five tasks:

- **control:** one deterministic call, seed 503, at most 1,280 output tokens and
  80 seconds; it emits three proposals and the lowest valid index;
- **diverse_select:** three independent `explore` calls, seeds 101, 211, and
  307, each at most 384 output tokens and 20 seconds, followed by one
  deterministic selector call, seed 401, at most 128 tokens and 20 seconds.

The output-token ceilings are matched at 1,280 per task per condition. Request
ceilings are matched at 80 seconds per task per condition. Calls are serial and
condition-group order alternates by task. There are exactly 25 calls, at most
800 seconds of summed request ceilings, an 850-second payload cap, and an
880-second external reservation when registered. No retries are allowed.

## Fresh objective tasks

All tasks are public synthetic development fixtures with exhaustive finite
graders:

| ID | Construction | Enumerable valid proposals |
|---|---|---:|
| `DIV1-GT-ASSURANCE-002` | two-action assurance equilibrium | 2 |
| `DIV1-GT-CONDORCET-002` | 9-voter plurality/Condorcet reversal | 18 |
| `DIV1-GT-DELEGATION-002` | four-voter acyclic delegation target | 64 |
| `DIV1-GT-COORDINATION-002` | strict coordination game with 1/3 mixing | 28 |
| `DIV1-GT-COALITION-002` | minimal winning coalition at quota 8 | 5 |

None of these exact task instances or seeds appeared in dev-v0. They remain a
public development panel, not a hidden generalization benchmark.

## Structured-output contract

The visible completion must be exactly one JSON object. Reasoning belongs in a
server-provided separate reasoning channel when available. Visible reasoning
tags, Markdown fences, duplicate keys, non-finite constants, multiple JSON
values, wrong outer fields, wrong value types, or wrong proposal shapes are
protocol failures and remain in the fixed denominator.

The pinned wrapper has no separately qualified server-enforced structured
output mode for this Gemma path. This manifest therefore records
`prompt_only_unqualified` and relies on the strict local parser. Enabling a
server response schema later requires a new manifest version and a new runtime
qualification; it must not happen silently during this trial.

Failure classes are reported separately:

- malformed/non-finite/duplicate JSON;
- visible reasoning-channel leakage;
- Markdown envelope;
- top-level or field/proposal schema failure;
- objectively infeasible but schema-valid proposal;
- schema-valid selector choosing something other than the lowest valid slot;
- transport, deadline, or runtime-provenance failure.

A protocol-invalid call is never salvaged into a successful proposal.

## Metrics

Fixed denominator: five tasks per condition.

Primary metrics:

- creditable task successes per condition;
- valid unique feasible proposals per condition;
- exact objective selector successes per condition.

Diagnostics:

- returned calls out of 25;
- structured-output failures by frozen taxonomy;
- schema-valid but objectively invalid proposals;
- substantive selector failures;
- failure-inclusive elapsed wall time.

The local finite grader is the authority. No model or frontier judge grades the
primary result.

## Preregistered interpretation

Label **SCAFFOLD_RECOVERED_ON_PUBLIC_V1** only if all of the following hold:

1. all 25 calls return with one bound runtime identity;
2. `diverse_select` succeeds on at least 4/5 tasks and no fewer tasks than
   control;
3. `diverse_select` produces at least eight valid unique proposals in total,
   at least two more than control;
4. its selector chooses the lowest valid slot on every candidate task having a
   valid proposal; and
5. no result depended on salvage, retries, altered tasks, or altered caps.

Otherwise label **NO_V1_SCAFFOLD_GAIN** when execution is complete, or
**INCOMPLETE** for transport, deadline, runtime-drift, or missing-evidence
failures. Report protocol and substantive failure categories even when the
primary rule fails.

A recovered label is limited to this public five-task development panel. It
does not authorize a production profile change. A subsequent promotion claim
requires a separately preregistered held-out task panel with adequate repeats.

## Kill conditions

Abort or withhold credit if the manifest hash, task/grader hashes, source
hashes, prompts, seeds, call order, policy metadata, runtime identity, fixed
call matrix, or time/token ceilings drift. Count timeouts and invalid outputs;
do not drop them. The run cannot authorize promotion or write production state.
