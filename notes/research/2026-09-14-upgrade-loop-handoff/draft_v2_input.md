# Weekly Model / Runtime / Inference-Policy Upgrade Loop — Agent Coding Handoff (DRAFT v2, pre-review)

**Project:** `decross1/a_bgt_rsi`
**Prepared:** 2026-09-13
**Status:** Proposed implementation/evaluation plan; no production cutover authorized.

## Executive decision

Optimize **verified scientific/coding task success per wall-clock and compute**, subject to reliability, reproducibility, and memory constraints—not raw tokens/sec.

Keep three upgrade surfaces causally separate:
1. **Model:** weights / quantization.
2. **Runtime:** vLLM/SGLang/etc., kernels, speculative decoding, KV policy.
3. **Inference policy/scaffold:** temperature, reasoning effort, context, candidate generation, critic selection, tools and prompts.

A challenger must not receive a better scaffold than an incumbent and then have the system-level gain attributed to its weights.

The highest-value near-term experiment is likely unlocking more capability from the models already installed, especially Qwen3.8-27B, before replacing them.

## 1. Re-establish actual state at session start

Gemma generator: Gemma 4 26B-A4B NVFP4, vllm/vllm-openai:v0.21.0, MARLIN MoE, MTP assistant 4 spec tokens, max_model_len=32768, max_num_batched_tokens=8192, gpu_memory_utilization=0.30, prefix caching + tool calling.
Qwen critic/secondary: Qwen3.8-27B NVFP4-MTP, same image, modelopt NVFP4, language-model-only, FP8 KV, qwen3_5_mtp 3 spec tokens, max_model_len=16384, max_num_seqs=2, gpu_memory_utilization=0.30, Qwen reasoning + coder tool parsers.
Wrapper: shared calls default to approximately temperature=0.0, top_p=1.0 unless overridden.
First task: re-read CLAUDE.md, START_HERE.md, LOOP_V1.md, latest session note, launcher, wrapper and decisions; inspect live /v1/models, boot logs, memory and recent call logs. Record drift. Runtime evidence beats this handoff.

## 2. Context and concurrency policy

Single-stream/concurrency≈1 is the primary benchmarking regime because consequential research calls matter more than aggregate server throughput. It does not itself make output faster.
64K is a capability/stress lane, not an assumed optimal default. Benchmark approximately 8K/16K/32K/64K and prefer the smallest context preserving task quality.
For literature/repository tasks compare retrieval + compact context against brute-force large context. Record task success, source fidelity, TTFT, decode, wall-clock, retries and memory.

## 3. Replace universal temperature-zero with role-aware inference profiles

Temperature zero is useful for extraction, deterministic validation, schemas/tool arguments and tightly specified edits. It is not automatically optimal for hypothesis generation, experiment design, debugging search, adversarial critique or scientific synthesis.

Implement named profiles, initially as experimental arms:
- deterministic: temperature 0.0, top_p 1.0, reasoning_effort none_or_low
- coding_precise: temperature 0.2, top_p 0.9, reasoning_effort medium
- scientist: temperature 0.7, top_p 0.95, reasoning_effort medium
- explore: temperature 1.0, top_p 0.95, reasoning_effort medium_or_high
- critic: temperature 0.7, top_p 0.95, reasoning_effort medium

Expose e.g. call_sync(..., profile="scientist"), preserve explicit overrides, and log the fully resolved policy.
For exploratory roles compare one deterministic answer against N=3 candidates -> independent critic/validator -> selection, holding total wall-clock/token budget roughly constant.

## 4. Runtime policy: immutable baseline, not permanent version

Do not casually remove the vLLM 0.21 production pin. Instead create a production lane (immutable known-good digest/commit and rollback point) and a challenger lane (newer vLLM/SGLang/other justified runtime, revision-pinned per experiment).
Promotion requires exact quant/backend, MTP, tools, reasoning parser, memory margin, repeated-call stability, deterministic fixtures, capability non-regression and rollback verification.
Do not silently edit CLAUDE.md inviolate rules. If evidence supports a new runtime, prepare a decision/pin amendment for explicit owner approval.

## 5. 1–2 coding-session plan

Session A — inference-policy instrumentation + eval harness: named inference profiles; per-call logging of model/backend, sampling, reasoning effort, output cap, input/output/reasoning tokens where available, latency and terminal status; frozen eval manifest; paired A/B runner; summary with paired deltas/confidence intervals; no production role swap.
Session B — challenger runtime lane: keep model weights fixed first. Compare current Qwen3.8 runtime with a current revision-pinned Spark-supported challenger. Test boot/memory, 8K–64K, speculation, tools, reasoning modes, science/coding panel, repeated long calls and cancellation/recovery. A speed gain matters insofar as it buys more useful inference compute.

## 6. Weekly Frontier Upgrade Loop

snapshot -> external_scan -> independent_proposals -> adversarial_cross_review -> preregister -> cheap_canaries -> full_eval_if_triggered -> decision -> implementation_if_approved -> regression -> promote_or_rollback -> journal

A frontier API model is an analyst/adversary, never the deployment authority.

Weekly snapshot given to the analyst: immutable production manifest; hardware/runtime/model hashes; role map; memory ledger; previous 7 days of eval summaries and failure clusters; current benchmark manifest; previous weekly recommendations and outcomes; repository constraints.

External scan: open-weight releases and quants; DGX Spark runtime/kernel changes; vLLM/SGLang/TRT-LLM/llama.cpp changes relevant to installed models; model-card inference recommendations; speculative-decoding developments; known correctness bugs; scientific/coding eval developments.

Every proposed change must be structured: claim, change_surface (model|runtime|inference_policy|scaffold|tool|context), evidence, expected_benefit, expected_metric, risk, implementation_cost, reversibility, confounders, minimum_experiment, promotion_threshold, abort_condition, sources.

Rubber-band frontier review: Analyst A = strongest OpenAI reasoning/coding model; Analyst B = strongest Claude model. Do not let them see each other's first proposal. A proposes; B falsifies A and proposes alternatives; A falsifies B; a context-isolated synthesis extracts disagreements resolvable by experiment; local preregistered measurements decide. If only one provider is available, use context-isolated proposer/adversary calls and record loss of model-family independence.

Weekly change budget: most weeks end NO_CHANGE; at most one production-affecting hypothesis per week; one surface at a time; no simultaneous model+runtime+prompt+policy change followed by a causal claim; security/correctness emergencies separate.

## 7. Evaluation portfolio

A. Tool/transport reliability — every candidate. ~100–200 fast fixtures: tool selection and wrong-tool traps; malformed/nested JSON; scientific notation and paths; long tool results; multi-turn chains; no-tool cases; cancellation/recovery. Metrics: syntactic validity, semantic argument correctness, tool choice, chain completion, empty-at-cap, retries, deterministic agreement where expected.
B. Private repo coding suite. ~20–40 frozen tasks from historical real bugs/changes with solution leakage scrubbed. Disposable worktrees/containers. Primary metric tests/task completion. Hidden fresh set from new production failures.
C. Scientific coding/reproducibility. Rotating subset of ScienceAgentBench Verified and/or CORE-Bench v1.1/OOD. Weekly 5–10 fixed canaries + 2–5 rotating/OOD; monthly/quarterly larger campaign.
D. Scientific discovery / hypothesis panel inspired by ResearchBench: inspiration retrieval; hypothesis composition; hypothesis ranking; falsifiable predictions; experiment design; self-critique. Blinded pairwise judges, cross-provider judging, human anchors.
E. Long-horizon research engineering: 1–3 "PaperBench-lite" tasks; periodic larger PaperBench/CORE campaigns.
F. Long-context synthesis: evidence packs at 8K/16K/32K/64K with distractors and contradictions; score retrieval, attribution, contradiction detection, synthesis correctness, unsupported claims, latency.

## 8. Metrics

Vector: science_success, coding_success, tool_reliability, long_context_fidelity, OOD_generalization, repeatability, wall_clock_to_correct, frontier_API_cost, local_compute_time, memory_peak, human_interventions.
Derived: Correct Task Throughput (CTT) = successful preregistered tasks / wall-clock hours by task family; Reliable Success Rate RSR_2of3; Science Utility per Hour (SUH). Never let a science gain hide a tool/reliability regression.

## 9. Sequential weekly experiment gates
1 evidence screen; 2 smoke; 3 canary; 4 paired panel with repeats; 5 expensive science/long-horizon only after material canary signal; 6 shadow; 7 promotion with recorded decision + rollback.

## 10. Adversarial critique / failure modes
Frontier says "update" (hypotheses only); benchmark chasing; judge circularity; scaffold confounding; stochastic noise; weekly overfitting; throughput Goodhart; contamination/saturation; autonomous self-modification spiral.

## 11. Why these benchmark choices
ScienceAgentBench Verified (102 tasks, verified 2026 release); CORE-Bench v1.1/OOD; ResearchBench (ACL 2026); PaperBench (periodic); private repo tasks; METR-style time-horizon thinking.

## 12. Weekly output contract
week, production_manifest_hash, frontier_analysts, sources_scanned, candidate_changes, experiments_run, results, regressions, decision (NO_CHANGE | POLICY_TRIAL | RUNTIME_TRIAL | MODEL_TRIAL | PROMOTE_PENDING_OWNER | ROLLBACK), confidence, unresolved_disagreements, next_trigger, artifacts. Distinguish verified local measurement / upstream claim / third-party measurement / frontier inference / speculation.

## 13. Initial preregistered experiment matrix
E1 inference policy per role (temp-0 vs moderate vs exploratory); E2 diversity+selection (1 deterministic vs 3 diverse + independent selection, budget held); E3 context 8K/16K/32K/64K; E4 runtime (same Qwen3.8 weights+policy, production vs challenger runtime); E5 model (only after 1–4, best incumbent config vs candidate at best preregistered deployable config).

## 14. Promotion philosophy
Research aggressively; change conservatively; measure causally; retain rollback. A new release / more context / more tok/s / higher temperature / a frontier recommendation is not an upgrade. An upgrade is a repeatable improvement in the project's actual scientific/coding work under declared constraints.

## Claims from the originating analysis that need external verification
- Qwen recommends thinking: temperature 1.0 / top_p 0.95; non-thinking: 0.7 / 0.8 (stated for "Flash-Next"); lower reasoning effort makes multi-turn agentic tasks slower overall due to retries.
- SGLang 0.5.19 added Qwen3.8 support; DGX Spark recipes moved to a September nightly for a zombie-request fix.
- Qwen3.8-27B on Spark via SGLang + DFlash2 reported ~64–78 tok/s single-stream through 65K context with high speculative acceptance.
- ScienceAgentBench Verified corrected false negatives (April 2026); CORE-Bench v1.1/OOD follow-up on reliability/efficiency/OOD; ResearchBench ACL 2026; PaperBench 8,316 rubric items / 20 papers; OpenAI estimated ~30% of SWE-Bench Pro tasks have issues; METR finding that Claude Code/Codex scaffolds did not automatically outperform evaluation scaffolds.
