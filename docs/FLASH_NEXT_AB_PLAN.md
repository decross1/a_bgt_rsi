# Qwen Flash-Next lab comparison

The owner requested a researched DGX Spark configuration, reproducible model and
optimization downloads, and a matched comparison against the resident Gemma–Qwen
lab across existing benchmark families. Production promotion is a later decision.

Primary comparison: current role bundle versus Flash-Next in every local model
role. Generator-only and critic-only ablations separate role effects where
resources permit. Same-checkpoint author and critic are explicitly correlated;
they do not inherit the current different-checkpoint meaning of independent
scientific qualification. Evaluation outputs never write production findings.

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

Sequence: research and artifact hashes; audit/build immutable challenger;
qualify memory and protocol; reserve and run paired current/Flash cohort;
extend through registered families and context/stability tests; publish exact
coverage, failures, uncertainty and a retain/adopt-for-trial verdict. Unsupported
or unimplemented external benchmark suites remain explicitly not run.

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
