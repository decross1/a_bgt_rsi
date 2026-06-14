> Imported from ~/.claude/plans/peaceful-brewing-seal-agent-a6d822d6b420662cd.md on 2026-06-14; scratch original; reference-only.

# Cohabitation research: vLLM (Gemma 4 26B-A4B-NVFP4) + Ollama (Qwen3.6-27B) on DGX Spark GB10

Date: 2026-05-26. All findings are research-only — plan mode active, no system changes proposed.

---

## 1. vLLM 2025–2026 features for footprint / cohabitation

| Feature | Flag | Landed in | Effect | Notes for our stack |
| --- | --- | --- | --- | --- |
| FP8 KV cache | `--kv-cache-dtype fp8` | Long-standing; matured in v0.19.1; full attention-quant in 2026 ([blog](https://vllm.ai/blog/2026-04-22-fp8-kvcache)) | per-token KV cost ~54% of BF16 (≈46% saving) | Recovers ~94% AUC@128k for BF16-weight MoE, ~98% for FP8-weight MoE on Qwen3-30B-A3B. **Caveat for Gemma**: `head_dim=256` triggers two-level FP8 accumulation, making prefill ~1.6× slower for long contexts. Recommend pairing with `--kv-cache-dtype-skip-layers sliding_window` ([docs](https://docs.vllm.ai/en/latest/features/quantization/quantized_kvcache/)) so Gemma's 25 sliding-window layers stay BF16 and only the 5 global layers go FP8. **Skip-layers flag exists in main, not confirmed in v0.21.0 — verify before relying on it.**
| Automatic prefix caching | `--enable-prefix-caching` (default on in V1) | V1 default ([docs](https://docs.vllm.ai/en/stable/design/prefix_caching/)) | Cuts TTFT for repeating system prompts; modest extra KV blocks | High win for the agent loop (system prompt + scaffold reused). ai-muninn measured TTFT of 0.12s on cache hit vs 2–4s cold. |
| Chunked prefill | `--enable-chunked-prefill` (always-on in V1) | V1; can't be disabled ([issue 18547](https://github.com/vllm-project/vllm/issues/18547)) | Caps prefill peak memory, batches with decode | Already in effect; nothing to change. |
| Sliding-window attention | model-driven | Native to Gemma 4 | Bounds KV per layer to 1024 tokens for 25/30 layers ([kaitchup](https://kaitchup.substack.com/p/gemma-4-31b-and-26b-a4b-architecture)) | Already exploited by Gemma's architecture. |
| MTP / speculative decoding | `--speculative-config '{"method":"mtp","num_speculative_tokens":N}'` | Gemma-4 MTP in v0.21.0 ([v0.21.0 release](https://github.com/vllm-project/vllm/releases/tag/v0.21.0)); Qwen3.6-27B MTP in recipes ([recipe](https://recipes.vllm.ai/Qwen/Qwen3.6-27B)) | 1.5–2× decode speedup; small KV/scratch overhead | Already on for Gemma. **Qwen MTP is not relevant for us — Qwen runs in Ollama, not vLLM.**
| Sleep mode | `--enable-sleep-mode` + `VLLM_SERVER_DEV_MODE=1` | Blog 2025-10-26 ([blog](https://vllm.ai/blog/2025-10-26-sleep-mode)) | Releases up to 90% of GPU memory in place; wake 18–200× faster than cold start | **Most useful single feature for our cohabitation problem.** Level-1 offloads weights to CPU RAM and discards KV; wakes in 3–6 s for large models. Lets us keep the vLLM process alive while Qwen has the floor. **Confirm v0.21 carries it** — flag exists in main; recipe entry for it dates Oct 2025 so likely yes, but verify in `/v1/server_info`.
| `--gpu-memory-utilization` semantics | engine arg | Long-standing | Reserves `frac × visible_GPU_memory` at startup for weights + activations + KV ([forum](https://discuss.vllm.ai/t/what-does-gpu-memory-utilisation-include/1651)) | **Reserve-at-startup, not grow-on-demand.** On unified memory this is a hard up-front allocation against the shared 128 GiB pool — that is why our current 0.9 default is dangerous when Ollama is also loaded. NVIDIA forum guidance: drop to **0.6–0.7** under cohabitation. |
| `--cpu-offload-gb` | engine arg | Stable ([sleep-mode docs](https://docs.vllm.ai/en/latest/features/sleep_mode/)) | Pages weights to CPU, costs PCIe-bandwidth per token | On unified memory this is essentially free as "transfer" but still counts against the 128 GiB pool, so it only helps if we want a smaller hot working set. Not a primary lever. |

Not in v0.21 (flag if you want them): per-head FP8 scales via FlashAttention-3 generalized static quant; the `--kv-cache-dtype-skip-layers` argument; some newer NVFP4 KV refinements. All in main, may require nightly image.

---

## 2. Ollama 0.24+ features

| Feature | Variable / option | Effect |
| --- | --- | --- |
| `OLLAMA_KEEP_ALIVE` | env, default `5m`; `0` = unload immediately; negative = forever ([FAQ](https://docs.ollama.com/faq)) | Set per-request `keep_alive: 0` to drop Qwen from memory between bursts. This is the cohabitation lever. |
| `OLLAMA_NUM_PARALLEL` | env, default 1 (auto 1–4 by free memory) | Each parallel slot allocates its own KV cache. Keep at **1** under cohabitation. |
| KV cache quant | `OLLAMA_KV_CACHE_TYPE=q8_0` (or `q4_0`) ([smcleod blog](https://smcleod.net/2024/12/bringing-k/v-context-quantisation-to-ollama/)) | Halves (q8_0) or thirds (q4_0) KV memory. **Requires `OLLAMA_FLASH_ATTENTION=1`** and silently falls back to f16 on unsupported archs. |
| Flash attention | `OLLAMA_FLASH_ATTENTION=1` | Prerequisite for the above; "no negative impact." |
| `num_ctx` per request | model option | KV scales **linearly in context length**. The 19.7 GiB-at-256K observation → ~2.46 GiB at 32K. Confirmed by community: each halving of context halves KV ([insiderllm](https://insiderllm.com/guides/kv-cache-optimization-guide/)). |
| Unified memory escape hatch | `GGML_CUDA_ENABLE_UNIFIED_MEMORY=1` ([nvidia forum](https://forums.developer.nvidia.com/t/running-a-full-llm-stack-on-dgx-spark-gb10-your-application-litellm-llama-swap-vllm-llama-cpp-ollama/367580)) | Required on GB10 so llama.cpp reads `/proc/meminfo` instead of `cudaMemGetInfo`. |
| Concurrent unload | `keep_alive: 0` via `/api/generate` then check `/api/ps` ([ai-muninn](https://ai-muninn.com/en/blog/dgx-spark-vllm-qwen35-setup)) | Cleanly returns memory to the pool before vLLM grows. |

---

## 3. Cross-engine cohabitation patterns

The most-cited GB10 recipe is **llama-swap + LiteLLM in front of vLLM and Ollama** ([NVIDIA forum thread](https://forums.developer.nvidia.com/t/running-a-full-llm-stack-on-dgx-spark-gb10-your-application-litellm-llama-swap-vllm-llama-cpp-ollama/367580)). Concrete reusable knobs from that recipe:

- vLLM: `--attention-backend FLASHINFER --enable-prefix-caching --kv-cache-dtype fp8 --load-format fastsafetensors`, GPU-util clamped to **`[0.60, 0.85]`** dynamically against actual free VRAM.
- Ollama: `OLLAMA_FLASH_ATTENTION=1 OLLAMA_NUM_PARALLEL=1 OLLAMA_LLM_LIBRARY=cuda_v13 GGML_CUDA_ENABLE_UNIFIED_MEMORY=1`, single model at a time, `--ctx-size 16384`.
- System ceiling reserved at **126.5 GiB** (1.5 GiB OS headroom — tighter than our 10 GiB target; we should be more conservative).

ai-muninn explicitly notes: **unload Ollama via `keep_alive:0` and verify `/api/ps` is empty before starting vLLM** ([source](https://ai-muninn.com/en/blog/dgx-spark-vllm-qwen35-setup)). No safe way to grow vLLM into memory Ollama already holds.

---

## 4. DGX Spark / GB10 specifics

- LMSYS review confirms 273 GB/s LPDDR5x as the binding constraint for inference on this device ([LMSYS](https://www.lmsys.org/blog/2025-10-13-nvidia-dgx-spark/)).
- No MIG on GB10 ([NVIDIA forum](https://forums.developer.nvidia.com/t/can-i-use-ollama-or-vllm-on-the-gb10-to-run-multiple-llm-models-simultaneously/352903)); no hardware-level partitioning of unified memory between processes. Cohabitation is by convention only.
- NIM containers: not currently optimized for GB10 / unified memory; nothing actionable for our v0.21 + Ollama setup. (Inferred from absence in NVIDIA's DGX Spark playbooks repo.)
- `GGML_CUDA_ENABLE_UNIFIED_MEMORY=1` is the official workaround for incorrect free-memory detection on GB10.

---

## 5. KV cache size estimates

**Gemma 4 26B-A4B at 32K** (from [kaitchup architecture deep-dive](https://kaitchup.substack.com/p/gemma-4-31b-and-26b-a4b-architecture)):

- 30 layers: 25 sliding-window (1024 tok cap each, 8 KV heads × 256 head_dim) + 5 global (2 KV heads × 512 head_dim).
- BF16 at 256K: ~5.20 GiB total. Crucially **most of that growth is in the 5 global layers** — sliding-window layers are bounded by the 1024-tok window, not by `max_model_len`.
- At 32K (BF16): global-layer scaling dominates → **~1.0 GiB**. With FP8 on the global layers only: **~0.5 GiB**.
- Sliding-window architecture is why Gemma 26B-A4B is so KV-cheap. This is the dominant reason it fits alongside Qwen at all.

**Qwen3.6-27B Dense at 32K** (from your own Ollama log + linearity confirmation in [insiderllm](https://insiderllm.com/guides/kv-cache-optimization-guide/)):

- Q4_K_M weights ~16 GB. KV scales linearly in context.
- Observed: **19.7 GiB KV at 256K** → **~2.46 GiB at 32K** (F16 KV).
- With `OLLAMA_KV_CACHE_TYPE=q8_0`: **~1.23 GiB at 32K**.
- With `q4_0`: ~0.6 GiB but with measurable quality cost on attention-heavy code tasks.

---

## 6. Bandwidth modeling

- 273 GB/s is shared by both engines via the unified memory controller.
- **Sequential decode** (one model at a time): no contention. Practical throughputs cited:
  - Gemma 26B-A4B (3.8B active, FP4 weights): ~2 GB read per token → ~135 tok/s theoretical, ~20–50 tok/s actual with overhead (matches LMSYS Llama 3.1 8B FP8 numbers as a comparable-active-size proxy).
  - Qwen3.6-27B dense Q4_K_M: ~16 GB read per token → ~17 tok/s theoretical; Ollama community report `Qwen3:32b` at 9.46 tok/s on Spark.
- **Concurrent decode**: dendro-logic's concurrency benchmark ([source](https://dendro-logic.com/engineering/nvidia-dgx-spark-concurrency-benchmark/)) shows that *within one model* concurrent streams share a single weight-read pass, so contention is minimal. **Across two different models** there is no shared-read benefit: aggregate per-token bandwidth demand simply sums. Combined Gemma+Qwen decode would saturate 273 GB/s (≈2 + 16 = 18 GB/token at 15 tok/s aggregate = 270 GB/s) and degrade both. **Recommendation: keep LOOP_V0 strictly sequential as the architecture already mandates.** Phase-2 concurrent will need Gemma-only concurrency or model-server sleep/swap.
- No published two-model side-by-side bandwidth study found.

---

## 7. Recommended configuration

Single most important change: **drop `--gpu-memory-utilization` to 0.55–0.60** so vLLM only reserves ~70–77 GiB of the 128 GiB pool, leaving ~50 GiB for Qwen + ~10 GiB OS headroom.

### vLLM relaunch (Gemma 4 26B-A4B-NVFP4)

```bash
docker run -d --name gemma --gpus all --ipc host --shm-size 32gb \
  -p 8000:8000 -v /mnt/models/gemma-4-26b-a4b-nvfp4:/model \
  vllm/vllm-openai:v0.21.0 \
  --model /model \
  --served-model-name gemma-4-26b-a4b \
  --moe-backend marlin \
  --max-model-len 32768 \
  --max-num-batched-tokens 8192 \
  --max-num-seqs 4 \
  --gpu-memory-utilization 0.55 \
  --enable-prefix-caching \
  --kv-cache-dtype fp8 \
  --speculative-config '{"method":"mtp","num_speculative_tokens":4}' \
  --enable-sleep-mode
```

Reasoning per flag (workload-dependent values flagged):

- `--gpu-memory-utilization 0.55` — reserve-at-startup behavior + 128 GiB shared pool; 0.55 ≈ 70 GiB leaves room for Qwen (~30 GiB hot) + 10 GiB OS. **Tune up to 0.60 if Qwen is sleep-mode-only.**
- `--kv-cache-dtype fp8` — ~50% KV cut; caveat: prefill slowdown on Gemma's head_dim=256. **Workload-dependent**: if our system prompts are short and decode-dominant, FP8 is a win; if prefill-dominant, benchmark first.
- `--enable-prefix-caching` — chat-style repeated system prompt; near-universal win.
- `--max-num-batched-tokens 8192` and `--max-num-seqs 4` — keep KV pressure low so we have a stable headroom number.
- `--enable-sleep-mode` — the cohabitation primitive. When Qwen needs to grow past available headroom, hit `POST /sleep?level=1` on vLLM; weights persist on CPU RAM; wake with `POST /wake_up` in 3–6 s. **Flag exists in main, dated Oct 2025; verify availability in v0.21.0 image at startup.**
- MTP `num_speculative_tokens=4` — recipe value for Gemma 4 26B ([recipe](https://docs.vllm.ai/projects/recipes/en/latest/Google/Gemma4.html)).
- No `--enable-chunked-prefill` flag because V1 has it on by default.

### Ollama configuration (Qwen3.6-27B dense)

Systemd env:

```
OLLAMA_FLASH_ATTENTION=1
OLLAMA_KV_CACHE_TYPE=q8_0
OLLAMA_NUM_PARALLEL=1
OLLAMA_MAX_LOADED_MODELS=1
OLLAMA_KEEP_ALIVE=5m
OLLAMA_LLM_LIBRARY=cuda_v13
GGML_CUDA_ENABLE_UNIFIED_MEMORY=1
```

Per-request (in the agent_wrapper Qwen call):

```json
{
  "model": "qwen3.6:27b-q4_K_M",
  "options": { "num_ctx": 32768, "num_gpu": 99 },
  "keep_alive": "5m"
}
```

Reasoning:

- `num_ctx: 32768` — matches vLLM, holds KV at ~1.2 GiB (q8_0). **Workload-dependent**: drop to 16K if coder turns are short.
- `OLLAMA_KV_CACHE_TYPE=q8_0` — measurable memory win, negligible quality loss on code; requires Flash Attention. **Validate q8_0 actually picks up — silently falls back to f16 on unsupported archs.**
- `OLLAMA_NUM_PARALLEL=1` — no second KV slot. Coder/critic is single-shot for LOOP_V0.
- `OLLAMA_MAX_LOADED_MODELS=1` — Ollama won't try to keep two GGUFs resident.
- `keep_alive: "5m"` baseline; pass `"keep_alive": 0` after the critic call when we know the next turn is Gemma to free ~17 GiB cleanly.
- `GGML_CUDA_ENABLE_UNIFIED_MEMORY=1` — required on GB10.

### Memory budget (steady state, LOOP_V0)

| Component | Resident |
| --- | --- |
| vLLM Gemma weights (NVFP4) + activations + CUDA graphs | ~17 GiB |
| vLLM KV (FP8, 32K, max-num-seqs=4) | ~3 GiB |
| vLLM reserved headroom (from `--gpu-memory-utilization 0.55`) | ~50 GiB (latent, available for batch growth) |
| Ollama Qwen Q4_K_M weights | ~16 GiB |
| Ollama KV (q8_0, 32K, num_parallel=1) | ~1.2 GiB |
| OS + buffers | ~10 GiB |
| **Total** | **~97 GiB resident, ~30 GiB free** |

Comfortably under 128 GiB with ≥10 GiB headroom satisfied.

### Operating discipline

1. LOOP_V0 stays sequential (one decoder at a time) per ARCHITECTURE.md bandwidth note.
2. Before a Gemma burst that needs more KV, send `keep_alive:0` to Ollama and confirm `/api/ps` is empty.
3. Before a Qwen burst, send `POST /sleep?level=1` to vLLM and confirm via `/v1/server_info`.
4. Phase-2 concurrent decode is **not safe** at full quality with these two models; revisit only after Gemma-only concurrency saturates.

---

## Open verifications (not changes — just things to check before adopting)

1. Does `vllm/vllm-openai:v0.21.0` actually expose `--enable-sleep-mode`? Check `vllm serve --help` inside the container.
2. Does `vllm/vllm-openai:v0.21.0` accept `--kv-cache-dtype-skip-layers`? If not, FP8 KV on Gemma is an accuracy/prefill-speed trade — measure on our prompts.
3. Confirm `OLLAMA_KV_CACHE_TYPE=q8_0` engages for Qwen3.6 arch (look for "kv cache: q8_0" in the model load log; silent f16 fallback would defeat the budget).
4. Confirm `keep_alive:0` round-trip + `/api/ps` empty before promoting the cohabitation runbook.

---

## Sources

- vLLM v0.21.0 release: https://github.com/vllm-project/vllm/releases/tag/v0.21.0
- vLLM FP8 KV blog (2026-04-22): https://vllm.ai/blog/2026-04-22-fp8-kvcache
- vLLM quantized KV docs: https://docs.vllm.ai/en/latest/features/quantization/quantized_kvcache/
- vLLM Sleep Mode blog: https://vllm.ai/blog/2025-10-26-sleep-mode
- vLLM Sleep Mode docs: https://docs.vllm.ai/en/latest/features/sleep_mode/
- vLLM Gemma 4 recipe: https://docs.vllm.ai/projects/recipes/en/latest/Google/Gemma4.html
- vLLM Qwen3.6-27B recipe: https://recipes.vllm.ai/Qwen/Qwen3.6-27B
- vLLM optimization docs: https://docs.vllm.ai/en/stable/configuration/optimization/
- vLLM prefix caching design: https://docs.vllm.ai/en/stable/design/prefix_caching/
- vLLM forum on gpu-memory-utilization: https://discuss.vllm.ai/t/what-does-gpu-memory-utilisation-include/1651
- vLLM chunked-prefill always-on issue: https://github.com/vllm-project/vllm/issues/18547
- Ollama FAQ (keep_alive, num_parallel): https://docs.ollama.com/faq
- Ollama K/V quantization (smcleod): https://smcleod.net/2024/12/bringing-k/v-context-quantisation-to-ollama/
- KV cache scaling primer: https://insiderllm.com/guides/kv-cache-optimization-guide/
- NVIDIA forum — full LLM stack on GB10: https://forums.developer.nvidia.com/t/running-a-full-llm-stack-on-dgx-spark-gb10-your-application-litellm-llama-swap-vllm-llama-cpp-ollama/367580
- NVIDIA forum — multi-model on GB10: https://forums.developer.nvidia.com/t/can-i-use-ollama-or-vllm-on-the-gb10-to-run-multiple-llm-models-simultaneously/352903
- ai-muninn Qwen3.5-35B on Spark: https://ai-muninn.com/en/blog/dgx-spark-vllm-qwen35-setup
- LMSYS DGX Spark review: https://www.lmsys.org/blog/2025-10-13-nvidia-dgx-spark/
- Dendro Logic concurrency benchmark: https://dendro-logic.com/engineering/nvidia-dgx-spark-concurrency-benchmark/
- kaitchup Gemma 4 architecture: https://kaitchup.substack.com/p/gemma-4-31b-and-26b-a4b-architecture
