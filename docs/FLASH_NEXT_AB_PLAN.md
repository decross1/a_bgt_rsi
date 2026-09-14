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

The 120-minute weekly limit remains in force. A separate one-time evaluation
allowance was asked about; a pending question grants no additional runtime.
Downloads and CPU-only runtime preparation proceed independently. Every live
trial must have a finite reservation and restoration procedure. The current
models and serving pins remain the rollback baseline.

Sequence: research and artifact hashes; audit/build immutable challenger;
qualify memory and protocol; reserve and run paired current/Flash cohort;
extend through registered families and context/stability tests; publish exact
coverage, failures, uncertainty and a retain/adopt-for-trial verdict. Unsupported
or unimplemented external benchmark suites remain explicitly not run.
