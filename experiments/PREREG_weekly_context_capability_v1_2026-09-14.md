# Preregistration: resident long-context capability canary v1

**Frozen:** 2026-09-14
**Suite:** `weekly-context-capability-public-synthetic-v1-2026-09-14`
**Status:** prepared and validated offline; no inference call has been made by
this preparation session.

**Pre-call revision note:** The original manifest at SHA-256
`df3714cce69b789d2f8567c68c957187d7c6ba73c09dd8aad3ea89797150998c`
was never executed. Before any model output, an audit corrected the disclosure
of the resident template policies, made every required evidence role explicit
in each task, and added a tokenizer/source/dependency-bound offline preflight.
The current hashes below supersede that unexecuted draft.

## Question and claim boundary

Can each resident model recover and reconcile exact, widely separated evidence
in the normal 8K lane and near the shared 14K lane while returning the exact
supporting source IDs?

This is a descriptive **model/context capability check**. It changes model
weights, template behavior, and backend together between arms, so it is not a
causal inference-policy comparison. Four public synthetic tasks are too few to
establish general scientific superiority. A pass or arm difference does not
authorize any production change.

All records are hand-authored synthetic development fixtures. They are not
empirical results, private data, a hidden benchmark, or evidence about an
external scientific claim.

## Frozen arms and order

Both arms use the existing `deterministic` generation profile resolved to
`temperature=0`, `top_p=1`, and seed 0, plus a 1,024-token output cap and a
120-second whole-request timeout including prefill. The profile leaves each
model's resident chat-template policy unchanged: Gemma is non-thinking, while
Qwen's current template default enables `xhigh` thinking. This comparison
therefore describes the two resident defaults; it does not isolate model
weights or thinking policy. Qwen's 1,024-token cap covers its complete generated
sequence, including any hidden reasoning.

| Arm | Existing backend/model | Serving context contract |
| --- | --- | --- |
| A | `vllm-gemma` / `gemma-4-26b-a4b` | non-thinking; 32,768 total tokens |
| B | `vllm-qwen` / `qwen3.8-27b-nvfp4-mtp` | template-default `xhigh` thinking; 16,384 total tokens |

The unchanged `bench.weekly_upgrade_eval` runner uses alternating AB/BA order.
The four tasks produce eight planned calls, with no retry.

## Frozen tasks and objective outcomes

| Task | Band | Planted reasoning target | Expected answer code | Exact citations |
| --- | --- | --- | --- | --- |
| `long_context_8k_grim_threshold` | ~8K | A claimed 0.40 grim-trigger threshold conflicts with the payoff-derived 0.50 threshold | `claim_contradicted_threshold_0_5` | `GT8A-CLAIM-0017`, `GT8A-PAYOFF-0073`, `GT8A-THRESHOLD-0132` |
| `long_context_8k_attrition` | ~8K | A complete-case increase conflicts with differential missing primary outcomes | `causal_increase_not_identified_differential_attrition` | `GT8B-PROTOCOL-0021`, `GT8B-PRELIM-0069`, `GT8B-ATTRITION-0111`, `GT8B-ANALYSIS-0143` |
| `long_context_14k_social_choice` | ~14K | A joint plurality/Condorcet claim conflicts with the ballot tally | `plurality_a_condorcet_b_claim_contradicted` | `GT14A-CLAIM-0029`, `GT14A-BALLOTS-0126`, `GT14A-TALLY-0239` |
| `long_context_14k_primary_endpoint` | ~14K | An abstract's causal claim conflicts with the null preregistered endpoint and correction | `primary_endpoint_null_abstract_claim_contradicted` | `GT14B-PLAN-0025`, `GT14B-RESULT-0117`, `GT14B-ABSTRACT-0213`, `GT14B-CORRECTION-0251` |

Each task question explicitly enumerates the evidence roles shown by the table
and requires exactly one focal source ID for every role, in that order. The
existing `evidence_attribution` grader requires the exact answer code and the
complete, duplicate-free citation set. An omitted or invented source fails;
the grader accepts the complete correct set in any order. The prompt requests
role order to make generation unambiguous. These instructions make the strict
citation contract part of the task rather than a post-hoc interpretation by
the grader.

## Frozen tokenization evidence

Token counts include the rendered system message, user pack, model-specific
chat template, and generation prompt. They were measured CPU-only with
Transformers 5.8.1, Tokenizers 0.22.2, and locally cached tokenizer artifacts using
`AutoTokenizer.apply_chat_template(tokenize=True, add_generation_prompt=True,
return_dict=False)`. Offline mode was forced. No weights, server, or GPU were
used. For every task, the default rendering was token-ID-for-token-ID identical to an
explicit `enable_thinking=false` rendering for Gemma and to an explicit
`enable_thinking=true, reasoning_effort=xhigh` rendering for Qwen.

| Task | Gemma input | Qwen input | Qwen total with 1,024 output reserve |
| --- | ---: | ---: | ---: |
| `long_context_8k_grim_threshold` | 8,104 | 8,138 | 9,162 |
| `long_context_8k_attrition` | 8,354 | 8,383 | 9,407 |
| `long_context_14k_social_choice` | 14,267 | 14,286 | 15,310 |
| `long_context_14k_primary_endpoint` | 14,537 | 14,573 | 15,597 |

The largest Qwen request retains 787 tokens below its 16,384 total-token server
limit after reserving the full output cap. The same largest request retains
17,207 tokens under Gemma's 32,768 limit.

Tokenizer provenance is frozen in `token_counts.json`, including all selected
tokenizer-affecting files present for each checkpoint, the rendered
chat-template hash, each full rendered token-ID-sequence hash, library versions,
and the explicit/default template-policy equivalence check. The CPU-only
context preflight reproduces the complete measurement before a Spark budget
reservation and emits a receipt bound to the manifest and execution-dependency
hashes. Any tokenizer, template, source, or frozen-count drift refuses the run.

This check uses the pinned host Transformers/Tokenizers libraries and the
model-volume tokenizer assets. It does not call a vLLM tokenize endpoint or
claim that a different server library implementation was independently
measured. The trial controller separately binds and checks the resident
container/runtime identity before and after generation.

## Runtime budget

- trial reservation: **1,230 Spark GPU-seconds**;
- evaluation payload deadline: **1,200 seconds**;
- eight calls x 120 seconds maximum = **960 seconds**;
- payload allowance remaining for sequential preflight/runner overhead:
  **240 seconds**; and
- no paid API, frontier call, network retrieval, retry, service mutation, or
  production promotion is part of this trial.

The shared weekly ledger and local-inference lease remain authoritative. If the
fixed payload plus controller reserve does not fit the remaining weekly budget,
the controller must refuse before launch. Interrupted or uncertain work is
charged under the existing trial-controller rules and is not replayed.

## Execution and grading rules

Before dispatch, the controller must verify:

1. every frozen artifact and execution dependency hash;
2. exact resident runtime/container identity and serving model IDs;
3. both named profiles resolve without overrides;
4. `MOCK_LLM` is absent and the registered manifest is exact;
5. the offline context preflight exactly reproduces the frozen tokenizer asset,
   template-policy, rendered-input, library-version, and token-count receipt;
6. all four full tokenized requests plus the output cap remain inside the
   Qwen limit; and
7. pause, owner lock, GPU lease, weekly ledger, finite deadline, and fresh
   output-directory checks pass.

Score each task/arm cell as pass, failed, timeout, transport-incomplete, or
budget-not-run using the existing runner. Report exact citation success,
completion status, input/output usage, empty-at-cap telemetry, request and
total wall time, and runtime provenance. Keep the four individual outcomes;
do not hide a 14K failure inside an aggregate 8K+14K percentage.

The primary descriptive comparison is each arm's 8K task success and 14K task
success. With two tasks per band, no confidence interval or one-cell difference
supports a broad capability claim. A valid result may establish only that a
specific frozen resident configuration did or did not complete these four
fixtures under the declared limits.

The 32K lane is excluded because it would be Gemma-only under current serving
contracts. The 64K lane is excluded because neither resident server currently
admits it. Neither may be silently truncated, rerouted, or inferred from this
trial.

## Frozen artifacts

| Artifact | SHA-256 |
| --- | --- |
| `bench/weekly_upgrade_context/generate_packs.py` | `66df4a88481b29137cb0dfac10981da7c0d45413ffd7137c690b2529d21514ed` |
| `bench/weekly_upgrade_context/packs.json` | `1ef8d9e02dd233d8126a71c8a4af43e63b19d8085b2f3fbe08619622167a7528` |
| `bench/weekly_upgrade_context/measure_tokens.py` | `dbb50f6b63896d5cdfd48c4479cf96cf043a0fc6a90387fba69ba0279fe12863` |
| `bench/weekly_upgrade_context/token_counts.json` | `f966245736f4a002441be0ee4eb552bcc8134c2ea75b8797ee05f01bd1974b45` |
| `bench/weekly_upgrade_context/preflight.py` | `143b8bb8707b7c1ca1140f52d0ab32122ef24fd0fce89cc6cef02334c243d32a` |
| `experiments/weekly_context_capability_v1_2026-09-14.json` | `7a65db923631d01c296ba8e65e924e646c9134082bb2a600c099eeb66eb6f735` |

Offline validation commands:

```bash
python3 -m bench.weekly_upgrade_context.generate_packs --check
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false \
  .venv-chroma/bin/python -m bench.weekly_upgrade_context.measure_tokens --check
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false \
  .venv-chroma/bin/python -c 'from bench.weekly_upgrade_context.preflight import validate_context_preflight; validate_context_preflight()'
.venv-chroma/bin/python -m pytest -q tests/test_weekly_upgrade_context.py
python3 -m bench.weekly_upgrade_eval.runner --plan \
  --manifest experiments/weekly_context_capability_v1_2026-09-14.json
```

These commands are preparation checks only. A live run requires separate trial
registry integration and the existing controller; invoking the runner directly
is not part of this preregistration.

## Post-measurement source maintenance

The live run used immutable commit `9d21f16` and tokenizer helper SHA-256
`2825f025034573ec727923e63f8ad3cc6c358b8dec490cd05cb98da21202fa7d`. A subsequent import-order-only lint fix
changes the current helper hash in the table above to `dbb50f6b63896d5cdfd48c4479cf96cf043a0fc6a90387fba69ba0279fe12863`.
It changes no prompts, token counts, model settings, grades or recorded result.
The executed checkout and its original artifacts remain intact; reproduce or
resume that run from `9d21f16`. This is source maintenance after measurement,
not a replacement preregistration or a rerun.
