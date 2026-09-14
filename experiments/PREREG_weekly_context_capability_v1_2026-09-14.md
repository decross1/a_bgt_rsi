# Preregistration: resident long-context capability canary v1

**Frozen:** 2026-09-14
**Suite:** `weekly-context-capability-public-synthetic-v1-2026-09-14`
**Status:** prepared and validated offline; no inference call has been made by
this preparation session.

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

Both arms use the existing `deterministic` generation profile, seed 0, a
1,024-token output cap, and a 120-second whole-request timeout including
prefill.

| Arm | Existing backend/model | Serving context contract |
| --- | --- | --- |
| A | `vllm-gemma` / `gemma-4-26b-a4b` | 32,768 total tokens |
| B | `vllm-qwen` / `qwen3.8-27b-nvfp4-mtp` | 16,384 total tokens |

The unchanged `bench.weekly_upgrade_eval` runner uses alternating AB/BA order.
The four tasks produce eight planned calls, with no retry.

## Frozen tasks and objective outcomes

| Task | Band | Planted reasoning target | Expected answer code | Exact citations |
| --- | --- | --- | --- | --- |
| `long_context_8k_grim_threshold` | ~8K | A claimed 0.40 grim-trigger threshold conflicts with the payoff-derived 0.50 threshold | `claim_contradicted_threshold_0_5` | `GT8A-CLAIM-0017`, `GT8A-PAYOFF-0073`, `GT8A-THRESHOLD-0132` |
| `long_context_8k_attrition` | ~8K | A complete-case increase conflicts with differential missing primary outcomes | `causal_increase_not_identified_differential_attrition` | `GT8B-PROTOCOL-0021`, `GT8B-PRELIM-0069`, `GT8B-ATTRITION-0111`, `GT8B-ANALYSIS-0143` |
| `long_context_14k_social_choice` | ~14K | A joint plurality/Condorcet claim conflicts with the ballot tally | `plurality_a_condorcet_b_claim_contradicted` | `GT14A-CLAIM-0029`, `GT14A-BALLOTS-0126`, `GT14A-TALLY-0239` |
| `long_context_14k_primary_endpoint` | ~14K | An abstract's causal claim conflicts with the null preregistered endpoint and correction | `primary_endpoint_null_abstract_claim_contradicted` | `GT14B-PLAN-0025`, `GT14B-RESULT-0117`, `GT14B-ABSTRACT-0213`, `GT14B-CORRECTION-0251` |

The existing `evidence_attribution` grader requires the exact answer code and
the complete, duplicate-free citation set. An omitted or invented source fails.

## Frozen tokenization evidence

Token counts include the rendered system message, user pack, model-specific
chat template, and generation prompt. They were measured CPU-only with
Transformers 5.8.1 and locally cached tokenizer artifacts using
`AutoTokenizer.apply_chat_template(tokenize=True, add_generation_prompt=True,
return_dict=False)`. Offline mode was forced. No weights, server, or GPU were
used.

| Task | Gemma input | Qwen input | Qwen total with 1,024 output reserve |
| --- | ---: | ---: | ---: |
| `long_context_8k_grim_threshold` | 8,021 | 8,055 | 9,079 |
| `long_context_8k_attrition` | 8,255 | 8,285 | 9,309 |
| `long_context_14k_social_choice` | 14,186 | 14,205 | 15,229 |
| `long_context_14k_primary_endpoint` | 14,447 | 14,481 | 15,505 |

The largest Qwen request retains 879 tokens below its 16,384 total-token server
limit after reserving the full output cap. The same largest request retains
17,297 tokens under Gemma's 32,768 limit.

Tokenizer provenance is frozen in `token_counts.json`, including the tokenizer
JSON, tokenizer configuration, and rendered chat-template hashes. Any tokenizer
or template drift invalidates this preregistration until the artifacts and
counts are reviewed and frozen again.

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
5. all four full tokenized requests plus the output cap remain inside the
   Qwen limit; and
6. pause, owner lock, GPU lease, weekly ledger, finite deadline, and fresh
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
| `bench/weekly_upgrade_context/generate_packs.py` | `3fe1ba544eed22cfa0c94930b036b1eb74a5a247fe1ece32b39cb7d0c4fb90e6` |
| `bench/weekly_upgrade_context/packs.json` | `004f3aaca24b9d40152e4d77db0975569b41db779e99239aacad1cb1f4e13554` |
| `bench/weekly_upgrade_context/measure_tokens.py` | `ec2a93d29eadd3b5b9639fc71266510284b1ffbd4b73108c4b8e1b5e299a890b` |
| `bench/weekly_upgrade_context/token_counts.json` | `5850aa3448ec40945fb6aaff4ab143a4fe77a67ab2f6810fa9d17baade23484e` |
| `experiments/weekly_context_capability_v1_2026-09-14.json` | `df3714cce69b789d2f8567c68c957187d7c6ba73c09dd8aad3ea89797150998c` |

Offline validation commands:

```bash
python3 -m bench.weekly_upgrade_context.generate_packs --check
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false \
  .venv-chroma/bin/python -m bench.weekly_upgrade_context.measure_tokens --check
.venv-chroma/bin/python -m pytest -q tests/test_weekly_upgrade_context.py
python3 -m bench.weekly_upgrade_eval.runner --plan \
  --manifest experiments/weekly_context_capability_v1_2026-09-14.json
```

These commands are preparation checks only. A live run requires separate trial
registry integration and the existing controller; invoking the runner directly
is not part of this preregistration.
