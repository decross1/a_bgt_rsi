# Day 1 bench debug — `day1_block2_bench` tok/s below floor

**Date:** 2026-05-18
**Result:** median single-stream decode **32.03 tok/s** (`bench/day1.csv`).
Plan hard floor 40; plan band [50, 110]; calibration ~52. **FAULT.**

Per-prompt: 31.3 / 32.1 / 32.0 / 32.0 / 32.1 tok/s — dead stable across
all 5 prompts (256-token completions). Steady-state, not degrading.

## Investigation — plan `on_failure` order

1. **Filesystem cache full?** NO. `free -h`: `buff/cache` 1.3 GiB only.
   The documented cache→~16 tok/s slowdown is not occurring. The 30-min
   `drop_caches` cron is in place.
2. **Thermal throttling?** NO. `nvidia-smi`: GPU 43 °C;
   `clocks_event_reasons.active = 0x0`; HW and SW Thermal Slowdown
   counters both 0 µs.
3. **BF16 instead of NVFP4?** NO — NVFP4 confirmed:
   `quantization=modelopt_fp4`, "Detected ModelOpt NVFP4 checkpoint",
   `Using 'MARLIN' NvFp4 MoE backend`.

All three plan-suspected causes are ruled out.

## Probable causes (structural)

- **GB10 has no native FP4 compute** (SM12x — see D-018). vLLM logs
  `marlin_utils_fp4.py:300`: *"Your GPU does not have native support
  for FP4 computation... Weight-only FP4 compression will be used
  leveraging the Marlin kernel. This may degrade performance..."* The
  plan's ~52 calibration (ai-muninn, vLLM 0.19+) may not transfer to
  v0.20.0 + this checkpoint on GB10.
- **Attention forced to `TRITON_ATTN`** — Gemma 4's heterogeneous head
  dims (head_dim 256 / global 512) force the Triton attention path.
- **Memory pressure** — `free -h`: 119/121 GiB used, 4.8 GiB swap in
  use. vLLM's default `gpu_memory_utilization` grabbed a very large KV
  cache on the unified-memory system. Not a direct decode-speed cause,
  but a config to revisit (lower `gpu_memory_utilization`).

## Status / recommendation

32 tok/s is below the plan floor. Task #7 logged `failed`; the metric
is recorded honestly (`metric_log.day1_tokens_per_sec = 32.03`). Task #7
is **not** a hard checkpoint — Day 1 can continue. Throughput tuning
(attention backend, KV-cache sizing, and MTP once a post-PR-#41745
image is pinned) is optimization work. Escalated to the human for the
call: accept 32 tok/s as the Day-1 baseline number, or pause Day 1 for
a tuning pass.
