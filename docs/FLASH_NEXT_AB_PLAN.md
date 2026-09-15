# Qwen Flash-Next lab comparison

The owner requested a researched DGX Spark configuration, reproducible model and
optimization downloads, and a matched comparison against the resident Gemma–Qwen
lab across existing benchmark families. Production promotion is a later decision.

Primary comparison: current role bundle versus Flash-Next in every local model
role. Generator-only and critic-only ablations separate role effects where
resources permit. The owner removed the two-model concurrent-residency
requirement; [the topology amendment](MODEL_TOPOLOGY_POLICY.md) permits a
single-primary candidate and separate critic arrangements. Same-checkpoint
author and critic are correlated, but that topology is not an automatic veto.
Measure critic errors and validated outcomes. Evaluation outputs never write
production findings.

The primary development suite preserves explicit native `top_k` values:
Gemma 64, resident Qwen 20, Flash 20. This is a deployable system comparison
with an intentional policy difference, not a weights-only experiment. The
superseded common-20 draft was archived before either cohort ran; a matched
top-k sensitivity comparison needs its own preregistration and suite identity.

Freeze weights, runtime image/source/patches, tokenizer, tool/reasoning controls,
role routing, fixture/grader identity, repetitions, caps, seed and stopping rules
before execution. Measure successes including failed and timed-out attempts,
wall-clock to correct completion, tool/format reliability, memory headroom,
prefill/decode/TTFT, critic missed faults and false rejections. Public historical
fixtures are development evidence, not a sealed confirmation set.

Research currently favors NVIDIA NVFP4 with disk-backed n-gram embeddings for
one 128GB Spark. A fully resident checkpoint does not fit. Initial qualification
keeps memory/precision controls conservative and tests speculation separately.
External one-Spark speed reports are hypotheses until locally reproduced.

On 2026-09-15 the owner explicitly exempted local model research and A/B testing
from the normal weekly maintenance compute allowance: “For these type of things
you have free budget - this is a local llm, not running a real pipeline.”
Record this research usage separately; do not debit or enlarge the existing
120-minute weekly maintenance ledger. This authorization applies to local model
R&D, not paid frontier APIs or production research. Every invocation still has
a finite preregistered deadline, hardware limits and a restoration procedure.
The current models and serving pins remain the rollback baseline.

The owner subsequently set the Flash research reserve to 20 GB. These isolated
experiments use a conservative 20 GiB `MemAvailable` floor. Earlier failures
under the 30 GiB floor remain unchanged; the ordinary production contract is
not rewritten by this research exception. Record setup, candidate execution,
and restoration memory/paging evidence so load behavior and rollback behavior
can be assessed separately.

Sequence: research and artifact hashes; audit/build immutable challenger;
qualify memory and protocol; reserve and run paired current/Flash cohort;
extend through registered families and context/stability tests; publish exact
coverage, failures, uncertainty and a retain/adopt-for-trial verdict. Unsupported
or unimplemented external benchmark suites remain explicitly not run.

## Context, thinking, quantization and speed experiments

The owner reaffirmed this active goal on 2026-09-15 and explicitly requested
alternative Flash quants, all relevant speed controls, different context lengths
and different thinking levels. These are required evaluation dimensions, not
assumed improvements. Keep the first paired bundle result separate from later
optimization cohorts; never retroactively change its policy or denominator.

Screen NVIDIA NVFP4 and the pinned Mia mixed-quant export independently. If
neither achieves the resource/quality target, evaluate the documented W4A16 or
GGUF alternatives with their own runtime and quantization provenance. Every
artifact requires its own correctness evidence; smaller disk size does not
establish lower resident memory or inherited quality.

Evaluate actual input lengths around 2K, 8K, 16K, 32K and 64K where supported,
with output/reasoning headroom reserved in the server context limit. Keep 64K
as a capability lane. Compare retrieval plus compact context against longer
evidence packs, recording both evidence availability and actual token counts.

The pinned NVIDIA and Mia templates accept thinking off (`enable_thinking=false`)
and `low`, `medium`, `xhigh` reasoning effort; they reject `high`. CPU template
rendering verified these controls on 2026-09-15; runtime delivery and task effects
still require evaluation. Test these supported levels by role. Record output caps,
reasoning tokens, empty-at-cap failures, retries and time to correct completion.
Compare adaptive escalation against fixed effort. Unsupported effort labels
must be reported as unavailable, never silently downgraded.

Screen MTP depth and draft settings, exact-model DFlash support, NVMe-backed
PLE/weight storage, packed representations, prewarm/read parallelism, KV
precision and allocation, prefix caching, scheduling, batching and kernels.
Require an actual compatible draft/runtime artifact for DFlash; evidence from
the dense 27B checkpoint cannot establish compatibility with Flash-Next.
Measure cold and warm behavior separately and single-stream performance first.

Change one control at a time for screening, then freeze promising combinations
for repeated task-quality and reliability comparisons. Include the strongest
tested incumbent policy in the optimized comparison. All supported dimensions
receive a measured result or an explicit, evidenced reason for exclusion.
Retain the 20 GiB reserve, local research accounting, exact rollback and finite
invocation limits throughout. No optimization result is a production cutover.

## Viewing the evidence

Benchmark Progress (`/benchmarks`) includes a separate **Local model research**
section. It shows recorded Flash runtime qualifications and paired benchmark
results. These entries do not debit the weekly allowance, extend historical
score series, or increase the weekly comparable-transition count.

Qualification receipts are read from the isolated research artifact directory.
An unfinished receipt does not prove that its process is still running. A
qualification pass establishes only its fixed runtime/protocol checks.

After paired execution, an operator exports `evaluation/dashboard-index.json`
with schema `flash-next-dashboard-index/v1` and a `comparisons` array. Each entry
contains an `id` and `resident`/`flash` references with an artifact-relative
`path` and raw-file `sha256`. A `qualifications` object supplies the resident
`receipt` and `artifacts` paths, and the Flash `receipt`, `plan`, and `contract`
paths. The same qualification validators that admit execution must accept those
sources and bind their hashes to the run arms. The dashboard verifies both run source hashes and the
run contracts before deriving family counts. It does not expose model responses
or machine-local paths. It reads at most four indexed comparisons and twelve
qualification receipts, with an explicit truncation notice.

Incomplete comparisons retain attempt counts and withhold success rates,
throughput and deltas. Throughput is successful **task runs** per hour including
failed attempts and grading, not a count of distinct tasks. Topic output protocol
is not a judgment of scientific topic quality. Full reports retain task-level
uncertainty and the difference between bundle effects and model-weight effects.
