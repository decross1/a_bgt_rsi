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

---

## Follow-up investigation — 2026-05-18 (`/investigate`)

The three causes above were checked correctly, but two of them stopped
one query short, and a fourth cause was never examined.

### Finding 1 — the benchmark measured the wrong quantity

`scripts/bench_tokens_per_sec.py` (original) computed
`completion_tokens / total_http_elapsed` and labelled it
`decode_tok_per_s`. That wall-clock window includes queue + prefill +
network + decode — it is **end-to-end throughput**, not decode rate.
Two-point estimate from the original CSV (91-tok row vs 256-tok rows):
true decode ≈ 32.5 tok/s, fixed overhead ≈ 0.10 s. The mislabel costs
~1–2 % here; it would explode for short outputs or a loaded server.

**Fixed.** The script now streams the response, timestamps first/last
token (`decode = (completion_tokens-1)/(t_last-t_first)`), reports TTFT
separately, discards a warmup request, pins `ignore_eos` so every
sample is equal length, reports median/min/max/stddev, and cross-checks
against the server `/metrics` histograms. Verified 2026-05-18: client
decode 32.43 tok/s vs server `/metrics` 32.42 tok/s — independent
agreement within 0.03 tok/s. A `--sweep-context` mode was added for E2.

### Finding 2 — decode is compute-bound at a capped clock

Live decode probe (400-token generation, GPU sampled with
`nvidia-smi dmon`):

| Signal              | Observed under load        | Meaning                          |
|---------------------|----------------------------|----------------------------------|
| SM utilisation      | 96 %, pegged               | compute-bound, not bandwidth     |
| Graphics clock      | 2411 MHz (max 3003)        | running at 80 % of peak          |
| Power draw          | 28 W, GPU 48 °C            | not thermal — power/profile cap  |
| `SW Power Capping`  | ~3.1 h accumulated counter | the SW power cap has been active |

The original investigation checked `clocks_event_reasons.active = 0x0`
— but that reads the throttle *event flags* on an **idle** GPU. The
*counter* (`nvidia-smi -q -d PERFORMANCE`) shows ~3.1 h of accumulated
SW power capping, and under load the clock sits at 80 % of max.

### Root cause

> **[Partly superseded — see "E1 result" below. The E1 clock experiment
> disproved the *compute-bound* reading: decode is memory-bandwidth-bound.
> The Marlin FP4 path is still implicated, but as a memory-traffic cost,
> not on-chip dequant compute.]**

On GB10 (SM12x, no native FP4 — D-018) vLLM runs the **Marlin
weight-only FP4** path, dequantising 4-bit weights on-chip every token;
the startup log warns it "may degrade performance for compute-heavy
workloads" and that the part has too few SMs for `max_autotune_gemm`.
Decode is therefore **compute-bound on FP4 dequant** (96 % SM util
confirms it) — and that compute runs at a power-capped ~2411 MHz clock.
The D-002 "273 GB/s bandwidth roofline → ~52 tok/s" model assumes a
*bandwidth-bound* decode and does not apply here (see DECISIONS D-021).
The dead-stable 32.0x readings fit a clean compute roofline at a fixed
clock.

**The "structural, accept 32" conclusion was premature** — the clock
cap is a concrete, untested, possibly floor-clearing lever:
32.5 × (3003/2411) ≈ 40.5 tok/s.

### Experiment / task plan

Falsifiable; each has a decision rule. GPU-state changes (E1) are left
to a human — this box also runs the production server.

- **E1 — clock/power cap test** *(cheapest; possibly clears the floor)*.
  `nvidia-smi -lgc <max>`; re-bench; watch `dmon` clock + the
  `SW Power Capping` counter. Find the DGX Spark system power profile
  (`nvpmodel` is absent — Spark-specific control) and set max
  performance. PASS: clock holds ≥2900 and tok/s ≥1.15×. FAIL: clock
  won't hold → hard SoC envelope, document. Reversible (`-rgc`).
- **E2 — decode rate vs context length**. `--sweep-context` mode (now
  in the script): lengths 256/4k/16k/64k(/128k). The bench only ever
  measured a near-empty KV cache; this gives the operating-range curve
  and shows whether TRITON_ATTN attention cost collapses long-context
  decode.
- **E3 — benchmark correctness**. Done (Finding 1).
- **E4 — concurrency / aggregate throughput**. Bench 1/2/3/4/8
  concurrent streams; D-002's "~115 tok/s at 3 concurrent" is untested.
  If aggregate scales well, single-stream may be the wrong KPI.
- **E5 — right-size KV cache** *(hygiene)*. Server runs
  `--max-model-len 262144` → 88 GiB KV cache → host at 119/121 GiB +
  4.8 GiB swap. Relaunch with `--max-model-len 32768
  --gpu-memory-utilization 0.6`; expect no decode change (confirms KV
  size is not the cause) but a box that is not swapping.
- **E6 — FP4 MoE backend comparison** *(research, off the prod path)*.
  In a scratch container, measure the NVFP4 MoE backends that init on
  SM12x + a newer vLLM Marlin kernel. Does not touch the D-003 /
  CLAUDE.md MARLIN pin.
- **E7 — MTP / speculative decoding** *(highest upside; blocked)*.
  Already roadmapped (D-019); amortises per-token compute — the right
  lever for a compute-bound decode (~1.5–2×). Re-attempt when a vLLM
  image ≥ PR #41745 is available.
- **E8 — attention backend**. TRITON_ATTN is forced by Gemma 4's
  heterogeneous head dims. Low priority; E2's curve shows whether
  attention dominates at long context. Do not override the forced
  backend (it prevents numerical divergence).
- **R1 — re-derive the throughput requirement**. The floor 40 / band
  [50,110] came from the now-superseded bandwidth roofline. Re-derive
  from a GB10 compute roofline or from the apparatus's latency budget.
  Flag for plan correction (as the run log already did for serve
  check #2).

### Accuracy side-issues (not throughput — separate track)

Startup log flags: fp8 KV-cache scale defaulted to 1.0, a w1/w3
`weight_scale_2` mismatch, a missing q-scale. These do not affect
tok/s but mean the served model may be subtly wrong — validate before
trusting any eval numbers.

---

## E1 result — 2026-05-18 (executed): clock is not the lever

Ran the corrected bench with the GPU clock locked (`nvidia-smi -lgc
3003`) while sampling `nvidia-smi dmon`.

| Condition             | clock under load | power | decode tok/s |
|-----------------------|------------------|-------|--------------|
| baseline (unlocked)   | 2411 MHz         | 28 W  | 32.4         |
| `-lgc 3003` locked    | ~2548–2574 MHz   | 38 W  | 32.46        |

The lock did not reach 3003 — the SoC power governor still held the
clock at ~2560 MHz — but it *did* rise ~6 % over baseline, and power
rose ~35 % (28→38 W). **Decode tok/s did not move** (32.4 → 32.46,
within run-to-run noise; server `/metrics` cross-check 32.42).

**Conclusion — E1 FAIL, and it disproves the compute-bound diagnosis.**
A ~6 % clock increase producing 0 % throughput change means decode is
**not** clock/compute-bound. The 96 % SM utilisation seen earlier was
warps *resident and stalled on memory*, not SMs doing saturating
arithmetic — SM util does not distinguish the two. Decode is
**memory-bound**.

Specifically **weight-bandwidth-bound**: the E2 sweep showed decode
nearly flat across context length (32.3 @ 256-ctx → 31.6 @ 2816-ctx),
so KV-cache reads are not the bottleneck — the per-token cost is
reading the model weights (BF16 dense + 4-bit MoE experts) from the
unified LPDDR5X each decode step. A faster clock cannot help that; the
SMs just wait faster. The D-002 memory-bandwidth roofline was
qualitatively right; the 32-vs-~52 gap is in the *memory path* (Marlin
weight-only FP4 access pattern, or effective LPDDR5X bandwidth well
below the 273 GB/s nominal) — not the clock. Recorded in DECISIONS
D-021 (rewritten).

The clock lock was reverted (`nvidia-smi -rgc`) — it cost +10 W /
+~6 °C for zero throughput gain.

### Revised lever priority

- **E7 — MTP / speculative decoding — now the clear #1.** For a
  weight-bandwidth-bound decode, MTP reads the weights once per forward
  pass and emits K tokens → near-Kx speedup until it re-hits a bound.
  Blocked only on a vLLM image ≥ PR #41745.
- **E6 — FP4 MoE kernel** — secondary: a kernel with a better weight
  memory-access pattern (or a newer Marlin) could lift effective
  bandwidth toward the 273 GB/s nominal.
- **E1 (clock) — closed, FAIL.** Not a throughput lever on GB10.
- **E5 (KV right-sizing)** — confirmed *not* a throughput lever;
  worthwhile only as memory hygiene (clears host swap).
- **E2 / E4 / E8 / R1** — unchanged; E2 already partly run (the
  context-flatness result above came from it).
