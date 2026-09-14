# Weekly model, runtime, and inference-policy upgrade loop

**Project:** `decross1/a_bgt_rsi`

**Research and handoff date:** 2026-09-14 UTC; supersedes the supplied 2026-09-13 draft.

**Verdict:** **EVALUATE inference policies first; build an evidence-driven weekly maintenance loop; retain the production configuration pending measured results.**

This is a coding-session handoff, not evidence that an upgrade has already succeeded. It combines repository inspection, primary-source research, three delegated research/audit agents, and two adversarial passes with actual Claude. The [review record](REVIEW_RECORD.md) separates findings, reviewer disagreements, and remaining unknowns.

The objective is **more verified scientific and coding work per unit wall-clock and compute**, subject to reliability, reproducibility, memory headroom, and acceptable interactive latency. The project's scientific domain is game theory, behavioral game theory, and learning in games. A generic coding leaderboard or a fluent hypothesis is an incomplete measure of that objective.

## 1. Scope, authority, and first-session state

Implementers should deliver the policy/instrumentation and evaluation work below as ordinary repository maintenance. The user's standing grant, recorded in the current host's [AGENTS.md](../../../AGENTS.md), already authorizes applicable Codex file edits, commits, pushes, merges, conflict resolution, and PR delivery without repeated permission. That file and `.codex/` were untracked at audit time; a fresh clone of remote `main` does not automatically inherit them. Carry the canonical checkout's current authority/configuration into new worktrees as instructed by the user. Preserve other sessions' changes and satisfy applicable checks.

This handoff does not authorize a production cutover, consistent with the supplied draft's status and existing runtime gates. Installing a weekly service, changing resident model roles or runtime pins, and giving a deployed autonomous worker broader authority require their own concrete activation decision. Do not confuse that boundary with permission for ordinary code/PR work. Frontier analysis here is a **maintenance function**; it does not turn frontier models into generators of the live scientific record or give them access to write `loop_memory` or the framework brain.

At session start, read [CLAUDE.md](../../../CLAUDE.md), [START_HERE.md](../../../START_HERE.md), [LOOP_V1.md](../../../LOOP_V1.md), [research_program_v2.md](../../sources/research_program_v2.md), the latest session note, and relevant decisions. Record local HEAD, dirty paths, worktrees, current remote `main`, live server identity, boot arguments/logs, available physical memory, and recent call outcomes. A local checkout, remote branch, launcher, and running container can describe different states; retain all four identities.

### Verified baseline on 2026-09-14

Local `main` is `1cb23033708fa1308bc2ddee30a4d38eb454049d`, sixteen commits ahead of cached `origin/main` and GitHub's current `main`, both `6f6c5923f5aba9eb08fa8c63e7dca444934f3b1c`. The checkout contains substantial unrelated dirty/untracked work. Launcher, wrapper and Nara source have no committed difference between these refs; launcher and wrapper are clean locally.

Read-only inspection of [cron/serve-models.sh](../../../cron/serve-models.sh), live `/v1/models`, selected Docker command metadata and boot logs confirmed:

| Setting | Gemma generator/PI | Qwen independent skeptic |
|---|---|---|
| Model | Gemma 4 26B-A4B NVFP4 | Qwen3.8-27B NVFP4-MTP |
| Served name | `gemma-4-26b-a4b` | `qwen3.8-27b-nvfp4-mtp` |
| Runtime | vLLM 0.21.0 | vLLM 0.21.0 |
| Context cap | 32,768 | 16,384 |
| Quant/backend | ModelOpt FP4; MARLIN MoE confirmed | ModelOpt NVFP4; language-model-only |
| Speculation | Gemma assistant; four tokens | `qwen3_5_mtp`; three tokens |
| Additional settings | Batched-token cap 8,192; prefix caching; Gemma4 tools | FP8 KV; max sequences two; Qwen reasoning/coder tool parsers |
| Effective boot settings beyond launcher text | KV dtype resolved to `fp8_e4m3` | Prefix caching disabled |
| Memory utilization flag | 0.30 | 0.30 |

Both containers' RepoDigest matches the recorded `vllm/vllm-openai@sha256:a230095847e93bd4df9888b33dab956fa9504537b828a23657d2b26fed57b5c9`. The launcher still names the mutable version tag, so digest enforcement on recreation is an implementation gap. Its Qwen `.25` memory comment is stale; the actual argument is `.30`.

At the idle snapshot, `MemAvailable` was `44,028,848 kB` (approximately **41.99 GiB**), above the project's **30 GiB** margin. This is one idle observation, not a long-request memory qualification. Qwen boot warnings identify deprecated MTP naming, forced scheduled-token limits, and uncalibrated FP8 attention scaling as testable leads; none proves an observed scientific regression.

**Temperature is not globally zero in actual use.** Wrapper defaults and Nara's direct tool loop are zero, but hypothesis generation already uses `0.7/0.95`, coordinator planning `0.1/0.9`, and other roles use `0.2` or `0.3`. Consolidate those existing policies before changing them. Local requests/logs do not expose a verified reasoning-effort setting; the assertion that Qwen currently runs at low effort is unsupported. The recent primary call-log slice contained no Qwen rows, so historical qualification cannot be presented as current production quality telemetry.

**The weekly frontier agenda is already live:** crontab runs it at Sunday **05:30 UTC** (`30 5 * * 0`), and September 6/13 logs show provider proposals. Its source comments saying dark/Monday are stale. The coordinator also runs hourly and through an active daemon; the watchdog runs every five minutes. The seven-day frontier ledger contains 572 calls, including 91 Codex timeouts. The existing abstract action budget is not API-dollar or device-hour accounting.

### Existing integration points to reuse

| Existing component | Use in this work | Audit finding / required change |
|---|---|---|
| [agent_wrapper/wrapper.py](../../../agent_wrapper/wrapper.py) | Resolve profiles consistently in sync, async, and tool-loop calls | Preserve explicit overrides and log effective settings, not just a requested profile name. |
| [orchestrator/nara.py](../../../orchestrator/nara.py) | Route its direct `be.create_chat` path through the same resolver | This bypasses the shared wrapper tool loop and hard-codes temperature zero and a 1,024-token output cap. A wrapper-only change misses the main path. |
| [agent_wrapper/backends/ollama_openai.py](../../../agent_wrapper/backends/ollama_openai.py) | Correct backend provenance | Qwen currently reuses this adapter and can inherit Ollama-flavored identity despite being served by vLLM. Fix metadata before runtime comparisons. |
| [agent_wrapper/frontier_cli.py](../../../agent_wrapper/frontier_cli.py) | Subscription CLI transport and invocation receipts | Resolve a working binary, verify auth mode, detect errors/empty output, record requested and returned model identity. Never silently fall back to a metered API. |
| [workers/frontier_review.py](../../../workers/frontier_review.py) | Existing methods/novelty reviewer patterns | Reuse transport and validation patterns; a scientific reviewer and an infrastructure analyst have different output contracts. |
| [orchestrator/frontier_agenda.py](../../../orchestrator/frontier_agenda.py) | Reference for bounded frontier invocation | This proposes research topics; it is not the upgrade controller. Its `dry_run` suppresses agenda writes but still invokes providers and appends frontier-call ledger rows. It is neither offline, cost-free nor write-free. |
| [orchestrator/self_improve.py](../../../orchestrator/self_improve.py) | Reuse evidence, bounded revision and cross-review stage patterns | Its Tier-P gate refuses schema, cron, orchestrator and version-pin changes; it cannot own this infrastructure lane without a separately defined runtime contract. |
| [cron/weekly-frontier-agenda.sh](../../../cron/weekly-frontier-agenda.sh) | Existing locking, pause and sentinel conventions | Inspect actual installation before integrating. Do not create competing scheduled owners of the Spark. |
| [schema/frontier_call.schema.json](../../../schema/frontier_call.schema.json) | Versioned transport receipts | Current schema is closed to undeclared fields. Add a compatible version/migration or separate upgrade record; do not silently append unsupported metadata. |
| [schema/calls.jsonl.schema.json](../../../schema/calls.jsonl.schema.json) | Local call telemetry | This schema is also closed; coordinate profile fields with producers, validators and activity projections. |
| [tests/test_critic_eval_scoring.py](../../../tests/test_critic_eval_scoring.py) | Existing critic regression seed | Twenty fixtures contain nineteen flawed hypotheses and one sound hypothesis; token-overlap grading is not proof of substantive critique. Create balanced valid/flawed/underdetermined items. |

The installed default npm Claude launcher failed because its native binary was absent. `/usr/bin/claude` version `2.1.143` worked with authenticated Max access for this review. This is a concrete preflight fixture: unavailable analysis must never become a successful empty report. The invocation details and actual returned model are in the review record.

## 2. Correct the evaluation philosophy

Use this decision order:

1. **Hardware fit and reproducibility.** Can the deployable configuration run within the actual shared-memory and service constraints?
2. **Scientific capability.** Does it calculate, test, reproduce, synthesize, and falsify correctly?
3. **Programming and agentic capability.** Does it finish bounded repository and tool tasks?
4. **Reliability.** Does it avoid fabricated sources, malformed tools, empty-at-cap responses, retry storms, and corrupted results?
5. **Successful work per elapsed time.** Include failed attempts, reasoning, selection, execution, and validation.
6. **Raw performance.** TTFT, prefill, decode, and aggregate throughput diagnose the result; they do not substitute for it.

Separate weights, quantization, runtime, decoding, context/retrieval, and scaffold effects. Compare a new model against a well-tuned incumbent under matched resources. Also retain the current production arm, so the report shows both the immediately obtainable system gain and the narrower causal attribution.

### Context is independent of concurrency

Concurrency approximately one is the primary measurement regime for the project's consequential research calls. Report concurrent aggregate throughput separately. Neither a large context allocation nor single-stream measurement inherently makes decode faster.

Use **8K–32K as a normal-workload evaluation range**, with a **tested 64K capability lane** when needed. Include 2K and 16K in serving measurements to connect short prompts and the claimed production limits. Reserve output tokens inside the model's total context cap.

For a controlled context test, give every arm the same relevant evidence, questions, contradictions, and answer key. Add or relocate fixed distractors to test length and position. Record UTF-8 bytes and each model's token counts; tokenizers differ. Separately compare a realistic retrieval pipeline plus compact context against broad-context ingestion. That second experiment measures a context-management system, not context length alone.

Prefer the smallest context that preserves quality. Long-context reports must include source fidelity, unsupported claims, TTFT, task completion time, and peak physical memory. Decode speed at 64K does not establish useful long-context reasoning.

## 3. Role-aware inference policy

The proposed profiles are **experimental arms**, not scientifically established optima. Temperature changes the sampling distribution; higher temperature does not establish greater intelligence. Temperature zero also does not guarantee reproducibility across kernels, runtime versions, or nondeterministic operations.

Start with a backward-compatible profile layer:

```python
call_sync(..., profile="scientist")
call_async(..., profile="coding_precise")
call_with_tools(..., profile="critic", temperature=0.0)  # explicit override wins
```

Use an `UNSET` sentinel or equivalent to distinguish omitted arguments from an explicit `temperature=0.0`. Precedence should be: **explicit call override → selected experimental profile → validated model/runtime defaults → legacy fallback**, with provenance recorded for each resolved setting. Calls without a profile retain current behavior until a measured policy promotion.

| Profile intent | Initial sampling arm | Reasoning intent | Function to evaluate |
|---|---|---|---|
| `deterministic` | temperature 0; top_p 1 | Minimal supported reasoning | Extraction, constrained transforms, tool arguments |
| `coding_precise` | temperature 0.2; top_p 0.9 | Moderate | Explicit-spec code edits and debugging |
| `scientist` | temperature 0.7; top_p 0.95 | Moderate | Scientific synthesis and analysis |
| `explore` | temperature 1; top_p 0.95 | Moderate or extended | Hypotheses and alternative experiments |
| `critic` | temperature 0.7; top_p 0.95 | Moderate | Counterexamples, confounds, disconfirming evidence |

These logical intents must be mapped by an adapter for the **exact model, template, and serving runtime**. Strings such as `none_or_low` and `medium_or_high` are not API values. Do not send unsupported effort controls or silently accept controls the server ignores.

### Verified model-card differences

| Contract | Qwen3.8-27B | Gemma 4 26B-A4B |
|---|---|---|
| Published thinking sampling | temperature 1, top_p .95, top_k 20; min_p 0; presence penalty 0; repetition penalty 1 | temperature 1, top_p .95, top_k 64 |
| Published non-thinking sampling | temperature .7, top_p .8, top_k 20; min_p 0; presence penalty 1.5; repetition penalty 1 | Use the exact supported template/generation contract; do not inherit Qwen penalties |
| Reasoning control | `xhigh` default, `medium`, `low` documented | Thinking on/off; no equivalent documented Qwen effort ladder |
| Prior thought history | Preserve according to the model's template contract | Remove previous thought content and retain final answers, **except tool-call turns, where thinking content is preserved** |

Sources: [Qwen3.8-27B official card](https://huggingface.co/Qwen/Qwen3.8-27B/blob/main/README.md), [Gemma pinned official card](https://huggingface.co/google/gemma-4-26B-A4B/blob/560dbcf0c2515abf83c1641b43e21bbcf178e2d7/README.md), [Gemma generation configuration](https://huggingface.co/google/gemma-4-26B-A4B/blob/560dbcf0c2515abf83c1641b43e21bbcf178e2d7/generation_config.json).

Gemma A4B can emit an empty thought-channel block with thinking disabled. Add parser fixtures for that behavior and for the tool-call history exception; thinking off does not mean channel tags disappear. [Gemma card](https://huggingface.co/google/gemma-4-26B-A4B/blob/560dbcf0c2515abf83c1641b43e21bbcf178e2d7/README.md).

Qwen's card warns that reducing effort can increase total completion time through failures and retries. Its recommendations warrant local trials; they do not prove that the production vLLM pin honors the same request controls. Test the actual payload/template and multi-turn behavior. Preserve thought history only in its intended internal model context; this is not a request to expose reasoning in user-facing artifacts. [Qwen card](https://huggingface.co/Qwen/Qwen3.8-27B/blob/main/README.md).

### Required policy and telemetry behavior

- A capability registry declares sampling fields, reasoning controls, history formatting, tool support, output budgets, and context limits per validated configuration.
- Profile selection must work across normal, async, tool-loop, retry, and fallback paths. Invalid profiles and incompatible settings produce explicit validation outcomes.
- Record model/checkpoint revision, backend/runtime identity, profile and adapter version, effective temperature/top_p/top_k/min_p/penalties where supported, reasoning intent and actual wire parameters, seed, output cap, truncation, tool schema hash, and context policy.
- Record input/output/reasoning token counts **when supplied by the server**; otherwise use `null` and an availability reason. Do not fabricate reasoning-token counts by subtracting incomparable counters.
- Record queue time, TTFT where measurable, total latency, retries, request/cancellation IDs, finish reason, empty-at-cap status, tool semantic validity, and the terminal task outcome. Link calls to a task and experiment run.
- Keep sensitive full prompts outside default telemetry; hash inputs and retain task-approved artifacts. Log transport status independently from the scientific verdict.

### Exploration plus selection

Two ablations answer different questions:

1. **Sampling diversity:** hold the three-candidate scaffold and selector fixed; compare deterministic versus diverse sampling.
2. **Product policy:** compare one longer answer with self-check/refinement against three candidates plus an independent critic/validator under the same total device-time budget.

Charge every candidate, reasoning token, retry, selector call, tool execution, and validator. Use executable validation where possible. The selector must not see the answer key. Report individual success, whether the pool contained a correct answer, and whether the selected answer was correct. Pool `pass@3` is diagnostic; selected success is the deployable result.

## 4. Runtime challenger lane

Keep an immutable, known-good production manifest and rollback recipe. Evaluate challengers using the same weights and inference policy wherever technically possible. A launch flag or container tag is not enough provenance: pin the digest/commit, checkpoint and drafter revisions, quantizer/calibration provenance, CUDA/kernel/backend, KV format, all flags, and server template/parser versions.

Read [DECISIONS.md](../../../DECISIONS.md) D-072 through D-074 and [Qwen role setups](../../qwen38_role_setups.md) first: the repository already separates reasoning/MTP/KV factors, describes a gated SGLang development lane, and records production qualification/rollback. Extend those decisions rather than restarting the investigation. Newer vLLM, SGLang, llama.cpp or TRT-LLM may qualify if exact model/hardware support warrants a bounded test; Flash-Next/Ling replacement claims remain untested leads in this handoff.

The SGLang cookbook establishes concrete Qwen3.8/MTP/DFlash deployment support on Spark. Its published GB10 correctness matrix uses 8K input and 1K output and explicitly does not remeasure throughput/acceptance. Its single-model memory recipe cannot establish Gemma co-residency. [Official cookbook](https://docs.sglang.io/cookbook/autoregressive/Qwen/Qwen3.8-27B).

The reported “64–78 tok/s through 65K” comes from a **third-party reproduction**, using a separately quantized DFlash2 drafter, an NVFP4 target, **BF16 KV**, **thinking disabled**, temperature zero and 512 output tokens. It reports roughly 70 decode tok/s through 65K across two boots; cold TTFT around 65K is approximately 36 seconds. It did not measure this project's scientific task quality or dual residency. Treat this as a promising challenger hypothesis, not a demonstrated fourfold research improvement. [Reproduction configuration](https://github.com/pangoleen/qwen3.8-27b-dgx-spark-dflash2/blob/master/README.md), [measured results](https://github.com/pangoleen/qwen3.8-27b-dgx-spark-dflash2/blob/master/RESULTS.md).

DFlash2 is a separate trained drafter, not the target's native MTP head. Quantized-target-head support required a specific SGLang change; issue reports also show deterministic divergence in some configurations. Algorithmic verification alone does not prove token identity for the deployed finite-precision stack. [Drafter card](https://huggingface.co/incoai/Qwen3.8-27B-DFlash2), [quantized-head fix](https://github.com/sgl-project/sglang/pull/35496), [thinking-mode divergence report](https://github.com/sgl-project/sglang/issues/38009).

SGLang's disconnected-request cleanup in PR #35255 is absent from the 0.5.19 tagged code, despite the close merge/release dates. Choose a verified post-fix immutable build, then test cancellation and batch transitions; another transition issue remained open at this audit. [Cleanup PR](https://github.com/sgl-project/sglang/pull/35255), [0.5.19 source](https://raw.githubusercontent.com/sgl-project/sglang/v0.5.19/python/sglang/srt/managers/tokenizer_manager.py), [transition issue](https://github.com/sgl-project/sglang/issues/36876).

Use the smallest sequence that resolves the attribution question:

| Arm | Purpose |
|---|---|
| Current vLLM + current native MTP | Actual production baseline |
| Newer validated vLLM + same native MTP | Runtime-version effect |
| Pinned SGLang + same native MTP, if supported | Serving-stack effect with speculation held as close as possible |
| Pinned SGLang + DFlash2 | Combined runtime/drafter system effect |
| Target-only controls where feasible | Attribute speculation speed and quality deltas |

Unsupported combinations are explicitly `NOT_SUPPORTED`; do not manufacture a factorial cell. Separately measure a candidate's best deployable configuration. If KV precision or a drafter changes, label that change rather than calling all of the gain a runtime upgrade.

### Fit and regression gates

The DGX Spark's CPU and GPU share physical memory. Measure system `MemAvailable`, attributable resident allocations, cache behavior, and memory peaks through load, prefill, decode, cancellation, and repeated long requests. Avoid double-counting shared CPU/GPU pages. Retain the existing **30 GiB project headroom requirement** for affected experiments. The supplied draft's approximately 105 GB attributable peak and 20 GB available are research suggestions, not authority to weaken the current gate; these bounds may conflict and must be reconciled explicitly, with GB/GiB units clear. A single-model recipe does not prove dual residency.

Disk-backed components may qualify only with demonstrated bounded residency. Record resident weights, disk footprint, page-cache pressure, cold faults, and sustained I/O. A checkpoint larger than RAM is neither automatically impossible nor proven workable.

Required gates cover:

- Correct NVFP4 load and intended backend; Gemma MARLIN boot evidence; Qwen quantization/KV correctness.
- Native MTP or external drafter support and actual acceptance/verification-step measurements.
- Tool selection, argument semantics, reasoning parsing/history, and structured-output integrity.
- Repeated-call stability, memory growth, disconnect/cancellation races, timeout recovery, and no duplicate side effects.
- Known deterministic fixtures and task-level quality at the intended stochastic policy. Exact token parity and task parity are different claims.
- Both resident models' workloads when testing a shared runtime or residency policy.
- A reproducible rollback rehearsal in the challenger environment.

Run serving measurements at supported 2K/8K/16K/32K/64K inputs, with declared output lengths and warm/cold cache conditions. Report peak memory, TTFT, prefill/decode, final-answer time, reasoning budget, and failure counts. Do not load challengers over active research services; obtain an idle resource lease and serialize replay unless concurrent headroom has been demonstrated. [cron/watchdog.sh](../../../cron/watchdog.sh) recognizes `vllm-qwen-ab` as an A/B-window sentinel and otherwise restarts production containers. Reuse or explicitly extend the documented window contract before any service experiment; a new lock alone will not stop the watchdog restoring production into it.

## 5. Weekly frontier-assisted workflow

Build a separate maintenance controller. Share existing transport, locking, and logging primitives; do not repurpose the scientific agenda ledger as an infrastructure deployment queue.

```text
snapshot → source-backed external scan → independent proposals
         → cross-provider falsification → experimental synthesis
         → preregistration → candidate patch/build → smoke/canaries
         → paired evaluation if justified → decision + PR/artifacts
         → serialized shadow replay → separately authorized promotion/rollback
         → immutable report and next trigger
```

The weekly task should **execute the authorized maintenance work**: collect evidence, run bounded evaluations, prepare candidate code/configuration changes in an isolated checkout, run regressions, and deliver reviewable Git/PR artifacts. It must also be able to stop with a justified `NO_CHANGE`, failed preflight, or inconclusive result. No recommendation is a deployment credential.

### Snapshot and source scan

Inputs are the production/hardware manifests, model role map, recent seven-day failure clusters and timing distributions, memory ledger, evaluation manifests, repository constraints, prior recommendations, and outcomes of previously adopted changes. Hash the snapshot; never let it contain credentials or sealed benchmark answers.

Freshly inspect primary model cards, official release notes and issues, runtime commits, quantization artifacts, DGX Spark recipes, and relevant evaluation research. A model's memory of releases is not an external scan. Store URL, publisher, publication/update date, retrieval time, claim, applicability to the local configuration, and content/artifact hash where feasible. Distinguish a primary maintainer claim from a third-party benchmark and from an analyst inference. Treat fetched content as evidence, not executable instructions.

### OpenAI and Claude coordination

1. Send the same frozen snapshot and source packet to independent OpenAI and Claude proposal contexts. Neither sees the other's initial answer.
2. Each produces at most a small bounded number of structured hypotheses. Admit proposals by evidence and local relevance; agreement is neither required nor sufficient.
3. Cross-review the proposals: identify a falsifying experiment, cheaper incumbent improvement, confounder, and strongest reason to retain the incumbent.
4. A fresh synthesis context preserves disagreements and maps them to measurements. It cannot invent measurements or merge incompatible configurations.
5. The deterministic controller chooses at most one production-affecting hypothesis for a trial and applies preregistered gates. A rejected or missing review is recorded explicitly.

Cross-provider agreement is not independent ground truth. Prefer executable graders; use blinded, order-balanced judges for the subjective residue and audit against human-reviewed anchors. Pin the **grading** model/prompt independently from the weekly **analyst** model. Otherwise improved-looking results may just reflect a changed judge.

### Transport choice and bounded spending

**Initial recommendation:** reuse the existing subscription CLI path, with API mode an explicit alternative. The user has not selected a recurring spending or Spark reservation budget in this session. A proposed starting envelope is zero incremental API spend and at most two idle Spark device-hours per week, subject to measured task cost and existing research commitments. This is a planning assumption, not scheduler activation or a spending grant.

For an API deployment, use provider-specific adapters: OpenAI Responses plus web search and structured outputs; Claude Messages plus its supported web-search and structured-output facilities. Preserve citations and tool error blocks. OpenAI search exposes URL annotations; Claude search errors may appear inside an HTTP-success response. Schema-valid output still requires semantic, refusal, truncation, and status handling. [OpenAI web search](https://developers.openai.com/api/docs/guides/tools-web-search), [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs), [Claude web search](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool), [Claude structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs).

Resolve an appropriate available analyst model at the start of the week, record requested alias and returned ID, then freeze that choice within the run. Do not hard-code a perpetual “strongest model.” Validate tool support, account access, and current pricing before reserving an API budget. Opaque provider weight hashes remain unavailable; record that limitation instead of inventing immutable provenance.

Subscription and API modes must be explicit. Preserve the existing API-key stripping in subscription mode, report quotas/usage separately from billed dollars, and never switch billing modes on an authentication failure. Claude's `--bare` mode skips subscription/OAuth authentication; it is therefore not the right isolation shortcut for a Max-only call. Use a verified invocation contract for the installed CLI. [Claude programmatic usage](https://code.claude.com/docs/en/headless).

### Controller requirements

- One run ID and lease per ISO week, production-manifest hash, and trial. Resume stages idempotently; an explicit rerun gets a new attempt ID. Reserve budgets before calls, not after duplicate results are detected.
- Bound provider calls, search/tool uses, input/output, retries, disk artifacts, and total deadline. Terminate child process groups on cancellation and confirm requests have stopped consuming resources.
- Persist each stage atomically with hashes. Resume only if inputs/configuration match; never mix trials after a configuration change.
- Honor existing pause/sentinel/resource ownership conventions. A maintenance worker receives an explicit bounded contract and cannot acquire direct-session authority merely by launching `codex`.
- A true `plan`/offline preview must not call providers, load a model, or mutate ledgers. Test this contract with a fake transport.
- Missing critical provenance blocks the affected comparison. Optional unavailable metadata is `null` with a reason; it must not unnecessarily block unrelated work.
- Keep scheduled research running on its incumbent. Resource contention yields `RESOURCE_DEFERRED`, not a service restart.

Use separate status and scientific decision fields:

```yaml
run_status: COMPLETE  # or FRONTIER_UNAVAILABLE, INVALID_EVAL, RESOURCE_DEFERRED, BUDGET_EXHAUSTED
decision: NO_CHANGE  # or CONTINUE_TRIAL, REJECT, PROMOTE_PENDING_OWNER, ROLLBACK_RECOMMENDED
change_surface: inference_policy  # model, runtime, quantization, context, scaffold, or null
evidence_status: SUFFICIENT  # or INSUFFICIENT, DEGRADED_SINGLE_PROVIDER
```

A single-provider fallback may produce a clearly labeled exploratory report when configured; it must not silently satisfy a two-provider gate. `NO_CHANGE` means no justified change, not an infrastructure failure disguised as a scientific conclusion. Do not make a target quota of either upgrades or no-change weeks.

## 6. Discrete evaluation portfolio

Build **task-level tests of actual research functions**, with immutable inputs, objective graders where possible, explicit timeout/resource caps, and hidden variants. Every scored field needs a reference value, executable invariant or adjudicated rubric anchor, plus a test demonstrating rejection of a plausible wrong answer. Allow multiple valid solutions and trajectories. A required JSON field alone does not validate scientific correctness.

| Family and function | Concrete task / artifact | Grader and primary failure it catches |
|---|---|---|
| Tool/transport execution | Retrieve → extract → calculate with a deterministic fake service; wrong-tool/no-tool traps, malformed values, cancellation and bounded retry | Check semantic arguments, legal state transitions, side-effect count, completion and error status. Schema validity alone is insufficient. |
| Formal game reasoning | Small payoff matrices; Nash best responses, correlated-equilibrium obedience, dominance, regret | Exact arithmetic or independent numerical residual checks; action/player permutations and positive affine payoff transformations, with transformed oracles, catch memorization. |
| Scientific simulation/coding | Repair a repeated-game simulator or payoff aggregator; reproduce a fixed result on hidden seeds | Hidden behavioral tests, numeric tables, provenance and fresh execution. A patch that merely alters expected outputs fails. |
| Evidence/retrieval | Extract population, treatment, estimate, uncertainty and limitation from fixed papers/tables with stable span IDs | Claim/span precision and recall, exact numbers, contradiction detection, unsupported-source count, appropriate abstention. |
| Critic/falsifier | Matched valid, confounded, and underdetermined claims, including a universal claim with an executable counterexample | Balanced verdict accuracy, valid witness, false-rejection rate, missed-fault rate; reject-everything is penalized. |
| Experiment design | Submit the full estimator, uncertainty/test, decision and stopping procedure for clustered repeated-game episodes | Simulate held-out null/alternative seeds; grade randomization unit, coverage/type-I error and power with Monte Carlo uncertainty. Prose rubric only for non-executable residue. |
| Whole research loop | A bounded paper/evidence → simulation → analysis → verdict microcampaign, including a planted null or missing source | Check artifacts, legal tool trace, source lineage, correct terminal verdict, stopping rule, resource cap and human interventions. |
| Long-context synthesis | Same evidence/answers in compact and distractor-heavy packs at multiple token lengths | Citation fidelity, contradiction detection, instruction retention, unsupported claims, TTFT and time to correct result. |

### Initial exact fixtures

These are newly proposed apparatus tests, not solutions to the human's Block 1 coursework.

**GT-EQ-001:** In a zero-sum game with row payoff `A=[[3,0],[1,2]]` and column payoff `-A`, request a mixed-strategy equilibrium and value. The reference is row probabilities `[0.25,0.75]`, column `[0.5,0.5]`, value `1.5`. Grade normalization, nonnegativity and maximum unilateral improvement. Use player/action permutations and player-wise positive affine payoff transformations, transforming the oracle and residual scales accordingly. Do not claim that one Lemke–Howson run enumerates all equilibria. Completeness tests need a suitably bounded, validated oracle.

**GT-REGRET-001:** Payoff vectors are `[(1,0),(0,1),(1,0),(0,1)]`; chosen action indices are `[1,0,1,0]`. Earned payoff is `0`, best fixed-action payoff is `2`, cumulative external regret is `2` and average regret is `0.5`. The unrestricted per-round oracle chooses `[0,1,0,1]`, makes three switches and earns `4`; it answers a different question. Require the comparator definition and numeric result.

**GT-PD-001:** Four undiscounted rounds, payoffs `(R,S,T,P)=(3,0,5,1)`, simultaneous TFT versus AllD, TFT cooperates initially and copies the opponent's previous move thereafter. Totals are `3` and `8`. Hidden tests catch same-round lookahead, payoff transposition, invalid-action coercion, and off-by-one horizons.

**GT-CRITIC-001:** Pair a session-confounded cooperation claim with a correctly randomized version and an underpowered null. Require an executable witness or proposed reanalysis where available; score each class separately. Do not inherit the existing nineteen-to-one class balance or reward keyword overlap as a science verdict.

**GT-DESIGN-001:** Supply a seeded episode-level data-generating process with repeated turns, a null and a known treatment effect. Require estimator, SE/interval or test statistic, decision rule, clustering unit and stopping rule. Preserve the independent episode/session as the randomization/uncertainty unit. Evaluate over grader-held-out synthetic seeds with Monte Carlo error and a predeclared tolerance; a turn-level pseudo-replication analysis should fail calibrated coverage checks.

QRE fitting is a later numeric task: assess optimization residuals and held-out predictive likelihood with calibrated uncertainty, not a blanket ±10% recovery requirement around a noisy parameter. Strategy identification requires informative probe opponents or an equivalence/abstention answer: identical observed cooperation can be consistent with AllC, TFT, and Grim.

### Reuse the existing apparatus before expanding it

| Existing asset | Immediate use |
|---|---|
| [Literature-falsification battery](../../../experiments/lit_falsification_battery) | Twenty-two retrieval-relevance/off-domain and novelty/critic-enum cases; useful narrow integrity canaries, not broad citation/science grading. |
| [Red-team fixtures](../../../bench/redteam_cal/fixtures.jsonl) and [locked protocol](../../../experiments/PREREG_redteam_cal_2026-08-18.md) | Twenty-four balanced good/bad cases; parse health and `fatal_flaw`/`proceed` discrimination under that protocol, not executable counterexample quality. |
| [Qwen production-seat batteries](../../../bench/qwen_ab_3bcd) | Reuse role transport regressions; stages 3b–3d emphasize liveness, parsing and nonempty output with single samples and fixed temperatures. Passing them is not a science-capability gain. |
| [Idea-judge calibration](../../../bench/judge_cal/set_v2.jsonl) | Seventy-four pairs labeled through lexical/ledger clustering, not independent semantic adjudication. Use for operational temperature/order behavior; audit/relabel before a scientific-equivalence gate. |
| [FP8 A/B assets](../../../bench/fp8_ab) and [window plan](../../qwen_fp8_windows_plan.md) | Reuse provenance, speculation metrics, tool probe, isolation and rollback patterns. |
| [Repeated PD](../../../experiments/exp001_repeated_pd), [mechanism design](../../../experiments/exp006_mechanism_design), [Cournot](../../../experiments/exp009_cournot) | Derive bounded simulator/code/analysis fixtures; separate deterministic analyzer tests from model-dependent behavior. |

Some existing critic/readjudication protocols are explicitly marked draft. Do not silently turn those into locked promotion gates. Existing experiment thresholds describe their original protocols, not universal upgrade standards. Real model/pipeline measurements require `env -u MOCK_LLM`; mock runs verify harness behavior and cannot establish model performance.

### MVP versus mature counts

Assemble a **30-item seed panel** from validated existing assets plus missing exact fixtures: ten tool/protocol items, eight exact scientific/numeric items, six balanced critic/evidence items, and six bounded coding/reproduction items. This is an implementation target, not a claim that all tasks fit two hours or establish small statistical gains. Begin by timing a smaller vertical slice. Thirty core plus ten OOD items, five repeats and two configurations would be **400 runs**; a two-hour cap would allow only eighteen seconds per run including setup. Do not copy that incompatible design/budget from the raw Claude review.

Expand toward 100–200 tool fixtures and 20–40 private coding tasks as meaningful historical failures and validated graders become available. Add a few end-to-end campaigns and separate evidence packs. Do not pad the suite with trivial variants or call repeated seeds independent new tasks.

Maintain an open development set, fixed regression core, sealed confirmation pool, and rotating incident/OOD pool. Define the OOD shift: held-out game family, task template, transformation class, failure mechanism or source domain. New seeds from the same generator are held-out IID data, not automatically OOD. A directory or same-host container is not sealed from a full-access maintenance agent. Use a separately permissioned evaluator service/account inaccessible to the optimizing process, withholding labels, solution history and answer-bearing tools. If that isolation is unavailable, describe the panel as a held-out regression set and reduce claims accordingly.

## 7. External benchmarks: verified roles and limits

| Benchmark | Verified scope as of 2026-09-14 | Use here |
|---|---|---|
| ScienceAgentBench | ICLR 2025 describes 102 tasks from 44 papers; the official repository released “Verified” artifacts intended to mitigate false negatives on 2026-04-30. That update is not a separate peer-reviewed paper. [Paper](https://proceedings.iclr.cc/paper_files/paper/2025/hash/f12b4df26344f3be803c06b555252efe-Abstract-Conference.html), [release record](https://github.com/OSU-NLP-Group/ScienceAgentBench/blob/main/README.md) | Periodic scientific program/execution checks; exact dataset revision and evaluator pinned. Domain transfer to game theory remains a question. |
| CORE-Bench v1.1/OOD | The 2026-06-23 follow-up is a preprint: 39 corrected hard-level v1.1 tasks and 19 OOD tasks, with analyses of reliability, efficiency and scaffold effects. [Primary paper](https://arxiv.org/abs/2606.26158) | Periodic computational reproduction/OOD campaign; do not present a small near-saturated panel as a broad measure of science. |
| ResearchBench | Findings of ACL 2026 reports 1,386 papers across 12 disciplines and retrieval/composition/ranking tasks. The current dataset card reports different per-task counts and gated access. [Paper](https://aclanthology.org/2026.findings-acl.644/), [dataset](https://huggingface.co/datasets/ankilok/ResearchBench/blob/main/README.md) | Inspire stage-specific tests. Publication-aligned hypotheses and LLM scores do not establish novelty, truth or experimental value. Pin accessible artifacts and usage terms. |
| PaperBench | Twenty ICML 2024 papers and 8,316 rubric items; released 2025-04-02. Fresh execution matters, but grading also uses LLM judgments. [Release](https://openai.com/index/paperbench/), [paper](https://cdn.openai.com/papers/22265bac-3191-44e5-b057-7aaacd8e90cd/paperbench.pdf) | One to three internal mini-replications; larger campaign periodically. Avoid calling a cheap code-only proxy equivalent to full reproduction. |
| Terminal-Bench / Science | Terminal-Bench 4.0 released 2026-08-28; Science 0.1 released 2026-08-27 with 70 tasks. [4.0 release](https://www.tbench.ai/news/terminal-bench-4-0), [Science release](https://www.tbench.ai/news/terminal-bench-science-0-1) | Selected executable external tasks after resource calibration. Pin benchmark, harness and container; historical scores across revisions are not interchangeable. |
| METR time horizon | Expresses task difficulty in human-expert completion time at a specified model success probability. [Methodology](https://evals.alignment.org/time-horizons/) | Structure occasional longer tasks. It is not the model's runtime or a direct measure of local scientific productivity. |

The weekly core should stay private and project-shaped. A monthly sample might contain five ScienceAgentBench tasks, two relevant CORE tasks, and a few terminal-science tasks **only after measuring cost**. Larger campaigns belong before a consequential model/runtime promotion or on a periodic research schedule. Version changes and grader repairs require both arms to be rerun.

## 8. Metrics and statistical design

Report a vector: science/coding success, tool semantic reliability, citation fidelity, formal correctness, OOD results, repeatability, time to correct result, API cost, local device-time, peak memory, retries, and human interventions. Do not let a subjective hypothesis score offset corrupted tools or fabricated evidence.

**Correct Task Throughput:** `successful preregistered tasks / total end-to-end elapsed hours on a fixed serialized task manifest`. Include failures, timeouts, loading where relevant, retries, candidate selection, execution and validation. Report by task family with a frozen task mixture; leased device-hours, API use and aggregate concurrent makespan are separate resource metrics. Report cold-start and steady-state throughput separately. A success floor prevents gaming the metric by giving up quickly.

**Reliable Success Rate:** report the full repeat-success distribution, including `RSR_2of3` and all-three success. The former is useful but must not stand in for a stricter reliability requirement. Anthropic distinguishes at-least-one success from consistent success across trials in its agent-evaluation guidance. [Agent evals](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents).

**Science Utility per Hour:** preregistered rubric credit divided by all charged time. Publish the component scores and weights. Include successful-task conditional latency, failure fraction, and capped time-to-correct separately; do not exclude timeouts and present the remaining latency as unconditional task performance.

### Smallest credible comparison

1. Tune profiles on development tasks; select one candidate and one primary function before seeing sealed outcomes.
2. Freeze both configurations, task/grader manifests, caps, materiality threshold, analysis code, and stopping rule. At least one end-to-end cost measurement must precede a larger run.
3. Run both arms on the same independently generated task instances. Randomize AB/BA order, reset state, and declare warm/cold cache conditions. A shared seed is useful provenance but does not guarantee matched randomness across implementations.
4. Use repeats to estimate within-task instability and paired task summaries for fixed-panel performance. Resample paired items within declared strata when justified. Generated items sharing a template may remain correlated; transfer to unseen templates/families needs top-level template clusters and more independent templates. Do not count seeds as new tasks or rely on eight broad family clusters for precise intervals.
5. Publish both-pass, incumbent-only, candidate-only, and both-fail counts plus per-family outcomes and uncertainty. The initial 30-item panel supports diagnostics and discovery of large effects, not tight noninferiority.
6. Confirm promising results on a fresh, preregistered held-out panel sized using pilot discordance/variance and the required margin. No automatic production promotion from the small discovery panel.

As a simple independent-binomial illustration, zero failures among 100 cases gives a one-sided 95% upper failure bound of approximately 3%; about 299 independent zero-failure cases are needed to put it below 1%. Correlated fixtures weaken that interpretation. A finite “all critical fixtures passed” gate means exactly that, not proven near-perfect field reliability.

Repeated candidate tuning and weekly looks create selection bias. Use a fixed planned confirmation sample initially. If later adopting sequential inference, preregister the spending rule or an appropriate confidence-sequence design **before all confirmatory looks**. Spend error budget on attempted looks, not only apparent winners. A conventional confidence interval used as a decision threshold is still an inferential test. [Always-valid inference](https://pubsonline.informs.org/doi/10.1287/opre.2021.2135).

Keep a fixed core to bridge weeks. Fresh sealed OOD tasks can validly inform a same-week paired confirmation when specified in advance; do not compare one week's raw score on one panel with the next week's score on a different panel. A revealed confirmation set becomes development/regression data; retuned candidates need fresh sealed items or a preregistered sequential evaluator that withholds item-level feedback. A grader defect invalidates affected results and triggers a version bump plus rerun, not a post hoc threshold change.

### Provisional decision gates

- **Must-pass invariants:** every named protocol, forbidden-side-effect, source-ID and provenance fixture passes. These finite tests can veto a candidate even when statistical sample sizes are small.
- **Fit:** existing physical headroom/resource contracts pass; no unexplained growth, crashes, request leaks, or duplicate side effects.
- **Target improvement:** preregister a material improvement for one function; an illustrative discovery trigger is ten percentage points in success, or fifteen percent in capped mean time-to-correct/CTT with a declared success noninferiority margin. Successful-only median latency cannot satisfy it. These are proposed calibration values, not validated thresholds.
- **Non-regression:** show per-family results and adequate uncertainty for the claimed margins. If the sample cannot establish the requirement, return `CONTINUE_TRIAL`/insufficient evidence.
- **Confirmation and shadow:** replicate on sealed tasks and replay representative inputs under a resource lease. No live traffic influence until the separate production decision.

Baseline calibration should estimate variance and task cost over several runs. Four weeks may help establish drift, but waiting four calendar weeks is not a prerequisite to fix instrumentation or evaluate an obvious bounded correctness bug.

## 9. Delivery plan and acceptance criteria

### Coding session A: policy and measurement

Deliver a small adapter-aware policy module and data definitions; update all wrapper entry points **and Nara's direct backend path**; repair Qwen backend provenance; add compatible telemetry; create a manifest and paired-run skeleton; implement a meaningful vertical slice of objective fixtures. Suggested new locations are `agent_wrapper/generation_policy.py`, `schema/upgrade_run.schema.json`, `experiments/weekly_upgrade/`, and `orchestrator/weekly_upgrade.py`; reconcile with current architecture before choosing paths.

Required checks: omitted settings preserve legacy requests, explicit zero overrides a profile, unsupported effort fails clearly, sync/async/tool/retry paths agree, telemetry reflects actual resolution, mocks cannot be mistaken for real measurements, and one numeric oracle rejects a plausible wrong output. Use a fake service for transport/state tests, then the smallest authorized real smoke when a safe resource window exists.

### Coding session B: bounded controller and first policy trial

Deliver snapshot/preflight, true offline preview, source/candidate schemas, independent frontier calls and cross-review, resumable stage receipts, budget/deadline enforcement, and report generation. Use the existing subscription transport with explicit error handling. Prepare candidate code/configuration and regression evidence in an isolated checkout; complete authorized Git/PR delivery.

Run the first paired policy comparison only after verifying the live baseline and cost. Prefer one role/model and current versus model-card-supported settings; label this a **policy-bundle** comparison when several settings change. Individual-knob attribution needs follow-up ablations. Avoid a combinatorial temperature × effort × role × model sweep before screening. The expanded fixture counts, external benchmark integrations, and runtime installation campaign are follow-on work, not a credible two-session guarantee.

### Subsequent experiments, in priority order

1. Installed-model policy: current policy versus validated thinking/sampling/budget, by function.
2. Diversity and selection: matched total resource budget, with selector cost and correctness included.
3. Context: same semantic evidence across lengths; retrieval comparison separately.
4. Runtime/drafter: same checkpoint/policy first, staged controls from section 4.
5. Model replacement: deployable quant against both current production and best validated incumbent policy/runtime.

A speed gain should be reinvested in a bounded experiment on reasoning, validation or additional candidates. Measure whether this improves completed scientific work; do not assume more generated tokens are beneficial.

### Scheduler activation packet, prepared after implementation

Provide the exact weekly command, timezone/window, budget, model/provider mode, pause switch, log retention, resource lease, integration with the **existing Sunday agenda, hourly/event coordinator and watchdog**, smoke evidence, and rollback procedure. Keep one owner of scheduling. Until that activation decision, the implementation can run manually or offline as authorized; this document does not install a cron or alter services.

## 10. Immutable output contracts

Each candidate needs a validated record with these fields:

```yaml
candidate_id: "content-addressed identifier"
claim: "specific expected local improvement"
change_surface: inference_policy
evidence: []  # typed local / primary-upstream / third-party / inference
sources: []   # URLs, dates, retrieval receipts and applicability
expected_metric: "selected task success at fixed end-to-end budget"
expected_benefit: "magnitude and basis, or explicitly unknown"
risk: []
implementation_cost: "estimated engineering and device-time"
reversibility: "exact rollback artifact"
confounders: []
minimum_experiment: "frozen task/configuration references"
promotion_threshold: "preregistered criterion and confirmation requirement"
abort_condition: []
```

The weekly report adds: week/run/attempt IDs, production and candidate manifest hashes, actual frontier model identities and transport outcomes, evidence freshness, budget reservations/actual use, preregistration hash, experiments attempted/completed/invalid, all paired outcomes, uncertainty, critical regressions, unresolved disagreements, decision and status, attribution by change surface, code/PR/artifact links, rollback readiness, and the exact next trigger that would change the decision.

Archive source excerpts sparingly, source URLs and hashes, prompts, validated model outputs, configuration manifests and analysis code. Preserve grader/answer isolation. Scientific findings that require reproduction must remain reproducible using the project's pinned local apparatus; external analyst advice is supporting maintenance evidence.

## 11. Reusable evaluation prompt

```text
Evaluate whether this model, deployable quantization, runtime, inference policy,
context policy, or scaffold improves a_bgt_rsi's verified game-theory/scientific
and programming work per elapsed time under its actual DGX Spark constraints.

First verify local checkout, remote main, launch manifests, running services,
memory, roles, recent failure logs, and existing gates. Label unknowns.
Never infer current production from this prompt or a historical benchmark.

Priority: hardware fit → science/coding capability → reliability → successful
tasks per total wall-clock → raw decode speed. Report concurrency≈1 first;
aggregate throughput separately. For context/runtime candidates that pass cheap
gates, test supported 2K/8K/16K/32K/64K lanes within the declared budget;
64K is a capability test, not a default allocation. Keep semantic evidence
matched, reserve output context, and report per-tokenizer counts.

Compare the candidate with BOTH resident models where their roles apply,
including current production and the best validated incumbent configuration.
Separate weights, quantization, runtime/drafter, decoding, context/retrieval,
and scaffold effects. Test exact model-card-supported reasoning/sampling;
do not impose one temperature or reasoning API across model families.

Try to falsify: memory fit, local capability gain, benefit over a tuned
incumbent, retry/cap reliability, runtime maintainability, quantization
quality, useful context, speculation speed/correctness, artifact provenance.
Distinguish decode-only speed from TTFT and complete task time.

Preregister the primary task family, controls, budgets, fixture/grader hashes,
repeats, uncertainty analysis, stopping rule and confirmation requirements.
Use executable function tests, balanced critic cases, source-grounded
synthesis and bounded end-to-end research tasks. Treat public leaderboards
and LLM judgments as supporting evidence. Include every failure, timeout,
selector and validation cost. Use a separately permissioned evaluator; if
unavailable, label the panel held-out regression rather than sealed.

Start with decision = NO_CHANGE | CONTINUE_TRIAL | REJECT | PROMOTE_PENDING_OWNER,
change_surface = model | runtime | quantization | inference_policy | context |
scaffold, and executed_cutover as a separate status. Then give baseline, candidate, memory, science,
coding, tools/reliability, resolved settings, context performance, raw speed,
correct task throughput on the fixed manifest including all failed attempts
and charged costs, paired uncertainty, deltas versus incumbents,
causal attribution, smallest useful patch, risks, and decision-change triggers.
Cite load-bearing external claims with exact primary sources and dates.

Deliver authorized candidate code/PR/evaluation artifacts. Production
activation follows the separately recorded contract; model advice does not
change repository or runtime authority. Explicitly report missing providers,
invalid evaluations and insufficient evidence. NO_CHANGE is a valid outcome.
```

The deliverable is a repeatable improvement in actual scientific work, supported by attributable measurements and a recoverable implementation.
