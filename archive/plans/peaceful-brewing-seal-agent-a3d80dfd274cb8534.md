> Imported from ~/.claude/plans/peaceful-brewing-seal-agent-a3d80dfd274cb8534.md on 2026-06-14; scratch original; reference-only.

# Qwen3.6-27B on DGX Spark — Critic / Coder Tier Quantization Plan

Date: 2026-05-26. Plan-mode research deliverable. No code touched; this file is read-only research.

## TL;DR (the recommendation up front)

**Run `sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP` under vLLM ≥ 0.20.2rc1 with `--kv-cache-dtype fp8 --quantization modelopt --speculative-config '{"method":"qwen3_next_mtp","num_speculative_tokens":3}'`.** That puts Qwen at ~21–26 GiB runtime (NVFP4 weights ~14 GiB + 850 MB BF16 MTP head + FP8 KV at moderate context) — comfortably under the 30 GiB joint budget — and is the only Qwen3.6-27B build that actually exercises GB10's NVFP4 tensor cores *and* keeps the native MTP head. The runner-up is `Qwen/Qwen3.6-27B-FP8` if NVFP4 stability bites; cost is ~10 GiB more and no fast NVFP4 path. **Q4_K_M / IQ4_XS GGUFs are not the right answer here**: same memory class as NVFP4 but no GB10 FP4 tensor-core path and no MTP in vLLM. Reserve GGUFs for llama.cpp-only fallback.

---

## 1. Qwen3.6-27B dense — quant table

Architecture (confirmed): dense, 27B params, 64 layers, hidden 5120, native 262 K ctx (1 M with YaRN), Apache 2.0, hybrid Gated DeltaNet + Gated Attention, **native MTP head trained in** ([Qwen/Qwen3.6-27B HF card](https://huggingface.co/Qwen/Qwen3.6-27B)).

| Quant | Source | On-disk | Runtime @ 32 K ctx (est.) | PPL Δ vs BF16 | GB10/CUDA 13.0 notes |
|---|---|---|---|---|---|
| BF16 | [Qwen/Qwen3.6-27B](https://huggingface.co/Qwen/Qwen3.6-27B) | 53.8 GB | ~57 GB + KV | 0 (ref) | Exceeds budget when co-resident with Gemma. |
| FP8 (block-128) | [Qwen/Qwen3.6-27B-FP8](https://huggingface.co/Qwen/Qwen3.6-27B) (official) | ~30 GB | ~33 GB | not officially published; kaitchup paywalled | Works in vLLM 0.21; no native FP4 tensor-core speedup on GB10. |
| NVFP4 (W4A4) | [sakamakismile/Qwen3.6-27B-NVFP4](https://huggingface.co/sakamakismile/Qwen3.6-27B-NVFP4), [sakamakismile/.../Text-NVFP4-MTP](https://huggingface.co/sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP), [AEON-7 NVFP4](https://huggingface.co/AEON-7/Qwen3.6-27B-AEON-Ultimate-Uncensored-NVFP4) | 17B-quantized-params ≈14 GB weights; full repo ~21–26 GB | **~21 GB** (LLM-only XS variant) to **~26 GB** with vision tower; KV FP8 keeps growth flat to 256 K | community AutoRound-style sweep "clearly falls behind" Intel INT4 on accuracy per [kaitchup](https://kaitchup.substack.com/p/qwen36-27b-quantization-fp8-vs-int4) (paywalled detail) — flagged | **Native NVFP4 fast path on GB10 SM121** with FlashInfer-CUTLASS, `--quantization modelopt`. |
| MXFP4 | Forthcoming per [search result](https://www.google.com/search?q=%22Qwen3.6-27B%22+MXFP4) — no public repo yet (2026-05-26) | — | — | — | Targets non-NVFP4 hardware; not relevant for GB10. |
| Intel AutoRound INT4 (sym, g128) | community Intel quant (Lorbus repo per kaitchup) | ~16 GB | ~18 GB | "especially strong" per [kaitchup](https://kaitchup.substack.com/p/qwen36-27b-quantization-fp8-vs-int4) | vLLM compressed-tensors path; no FP4 tensor-core speedup. MTP head preserved BF16. |
| AWQ INT4 (asym, g32) | hampsonw AWQ | ~16 GB | ~18 GB | not separately reported | vLLM AWQ path; no FP4 tensor-core speedup. |
| GPTQ INT4 | Qwen3 series generic per [Qwen speed-bench docs](https://qwen.readthedocs.io/en/latest/getting_started/speed_benchmark.html) | ~16 GB | ~18 GB | not separately reported | Works but typically below AWQ/AutoRound for this gen. |
| UD-IQ2_XXS | [unsloth GGUF](https://huggingface.co/unsloth/Qwen3.6-27B-GGUF) | 9.39 GB | ~11 GB | not published | llama.cpp only; no MTP in vLLM path. |
| UD-IQ2_M / UD-Q2_K_XL | unsloth GGUF | 10.8 / 11.8 GB | ~13 GB | not published | llama.cpp only. |
| UD-IQ3_XXS / Q3_K_S / Q3_K_M / UD-Q3_K_XL | unsloth GGUF | 12.0 / 12.4 / 13.6 / 14.5 GB | ~14–17 GB | not published per-quant; general Q3 ≈ +0.05–0.15 PPL | llama.cpp only. |
| IQ4_XS / Q4_K_S / IQ4_NL / Q4_0 / Q4_K_M / Q4_1 / UD-Q4_K_XL | unsloth GGUF | 15.4 / 15.9 / 16.1 / 15.8 / 16.8 / 17.3 / 17.6 GB | ~18–20 GB | Q4_K_M ≈ +0.1–0.3 PPL (+1–3 % rel) per general llama.cpp norms; not published per-quant for this model | llama.cpp only; **no fast NVFP4 path**, no vLLM MTP. |
| Q5_K_S / Q5_K_M / UD-Q5_K_XL | unsloth GGUF | 19.0 / 19.5 / 20.0 GB | ~21–23 GB | not published per-quant | llama.cpp only. |
| Q6_K / UD-Q6_K_XL | unsloth GGUF | 22.5 / 25.6 GB | ~25–28 GB | ≈ +0.01–0.05 PPL (general norm) | llama.cpp only. |
| Q8_0 / UD-Q8_K_XL | unsloth GGUF | 28.6 / 35.3 GB | ~31–38 GB | "essentially zero" Δ per general llama.cpp norms | Q8 fits but no MTP; UD-Q8_K_XL blows the budget. |

Sources: [unsloth/Qwen3.6-27B-GGUF](https://huggingface.co/unsloth/Qwen3.6-27B-GGUF), [recipes.vllm.ai/Qwen/Qwen3.6-27B](https://recipes.vllm.ai/Qwen/Qwen3.6-27B), [Quantized Models index](https://huggingface.co/models?other=base_model%3Aquantized%3AQwen%2FQwen3.6-27B).

**Flags / things I deliberately did not estimate:** per-quant PPL for IQ2/IQ3/IQ4 on this model — the Unsloth card and Qwen card do not publish them, and the kaitchup quality sweep is paywalled. The "+0.1–0.3 PPL for Q4_K_M" figure I cite is the general llama.cpp range, not a Qwen3.6-27B-specific measurement.

## 2. MTP / speculative decoding for Qwen3.6-27B

- **Native MTP, no separate draft model required.** Qwen3.6-27B is trained with MTP heads; vLLM enables it with `--speculative-config '{"method":"qwen3_next_mtp","num_speculative_tokens":2}'` per Qwen's own [HF launch command](https://huggingface.co/Qwen/Qwen3.6-27B). vLLM's [generic MTP page](https://docs.vllm.ai/en/latest/features/speculative_decoding/mtp/) confirms the family-must-support-MTP requirement.
- **MTP head footprint:** ~850 MB BF16 (15 tensors), kept un-quantized even in the NVFP4 build. Source: [sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP](https://huggingface.co/sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP).
- **Acceptance / speedup:** per-position acceptance ~87 % / 72 % / 61 %, mean accepted length ≈3–4 tokens with `num_speculative_tokens=3`. Reported **1.74× aggregate** (207 vs 119 tok/s) on Blackwell SM120 (RTX PRO 6000), 1.24–1.87× single-stream depending on output length. Source: [sakamakismile MTP card](https://huggingface.co/sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP).
- **DGX Spark GB10 (sm_121a) measured:** AEON-7 v4-DFlash recipe reports stock-vLLM single-stream **10.49 tok/s → 37.56 tok/s** (+258 %) on the same hardware class with NVFP4 + grafted DFlash drafter (k=15); independent NVIDIA dev forum thread sees ~10 tok/s baseline and notes recipe sensitivity. Sources: [AEON-7 DFlash repo](https://github.com/AEON-7/Qwen3.6-27B-AEON-Ultimate-Uncensored-DFlash), [NVIDIA dev forum slow-recipe thread](https://forums.developer.nvidia.com/t/slow-qwen-3-6-27b-nvfp4-recipe-feedback/370808).
- **Caveat (load-bearing):** DeltaNet's recurrent state breaks any reject-and-roll-back speculative pipeline; community reports gibberish + collapsing throughput on Qwen3.5-35B-A3B-FP8 + MTP ([vLLM #36872](https://github.com/vllm-project/vllm/issues/36872)). For Qwen3.6-27B dense the native qwen3_next_mtp path works, but treat first-day numbers as suspect until acceptance rate is logged.
- **vLLM version:** Qwen's launch command targets vLLM ≥ 0.17; the NVFP4-MTP recipe is validated on 0.19.1rc1; the AEON-7 DGX Spark image is 0.20.2rc1.dev166. **Our current pin `vllm/vllm-openai:v0.21.0` is forward of all three** — should be fine but the GB10 NVFP4 path on 0.21 is not yet community-validated for *this* model. Flag.

## 3. Qwen3-Coder-30B-A3B (MoE) — comparison

Architecture: 30B total, **3B active per token** → big bandwidth advantage on the 273 GB/s LPDDR5X. Apache 2.0.

| Quant | Source | On-disk | Runtime @ 32K (est.) | Notes |
|---|---|---|---|---|
| BF16 | [Qwen/Qwen3-Coder-30B-A3B-Instruct](https://huggingface.co/Qwen/Qwen3-Coder-30B-A3B-Instruct) | 61.1 GB | ~64 GB | Over budget. |
| FP8 (block-128) | [Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8](https://huggingface.co/Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8), [unsloth-FP8](https://huggingface.co/unsloth/Qwen3-30B-A3B-Instruct-2507-FP8) | ~32 GB | ~35 GB | Just over budget; vLLM/sglang supported. |
| GGUF UD-TQ1_0 / UD-IQ1_S / UD-IQ1_M | [unsloth GGUF](https://huggingface.co/unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF) | 8.01 / 8.91 / 9.63 GB | ~10–11 GB | 1-bit, MoE-friendly but coding quality unknown. |
| UD-IQ2_XXS / Q2_K / UD-IQ2_M / Q2_K_L / UD-Q2_K_XL | unsloth GGUF | 10.3 / 11.3 / 10.8 / 11.3 / 11.8 GB | ~12–14 GB | llama.cpp only. |
| UD-IQ3_XXS / Q3_K_S / Q3_K_M / UD-Q3_K_XL | unsloth GGUF | 12.8 / 13.3 / 14.7 / 13.8 GB | ~15–17 GB | llama.cpp only. |
| IQ4_XS / Q4_K_S / IQ4_NL / Q4_0 / Q4_K_M / Q4_1 / UD-Q4_K_XL | unsloth GGUF | 16.4 / 17.5 / 17.3 / 17.4 / 18.6 / 19.2 / 17.7 GB | ~19–22 GB | llama.cpp only. |
| Q5_K_S / Q5_K_M / UD-Q5_K_XL | unsloth GGUF | 21.1 / 21.7 / 21.7 GB | ~23–25 GB | llama.cpp only. |
| Q6_K / UD-Q6_K_XL | unsloth GGUF | 25.1 / 26.3 GB | ~27–29 GB | llama.cpp only; near budget ceiling. |
| Q8_0 / UD-Q8_K_XL | unsloth GGUF | 32.5 / 36 GB | ~34–38 GB | Over budget. |
| AWQ / GPTQ / NVFP4 | not located as of 2026-05-26 | — | — | None published in [quantized models index](https://huggingface.co/models?other=base_model%3Aquantized%3AQwen%2FQwen3-Coder-30B-A3B-Instruct) at time of search. |

**MTP for Qwen3-Coder-30B-A3B: no native head.** No `qwen3_next_mtp` variant exists for this model. Acceleration is via **EAGLE3 draft** (0.2 B params) trained by lmsys/SpecForge — but it's **SGLang-only**, not vLLM: [lmsys/SGLang-EAGLE3-Qwen3-Coder-30B-A3B-Instruct-SpecForge](https://huggingface.co/lmsys/SGLang-EAGLE3-Qwen3-Coder-30B-A3B-Instruct-SpecForge), `--speculative-num-steps 3 --speculative-num-draft-tokens 4`. Acceptance numbers not published on the card.

**Active-params bandwidth:** ~3 B activated per token vs ~27 B for the dense 27B. On a 273 GB/s system this is a ~9× peak-bandwidth advantage per token, which is the case for using A3B as the coder tier *if* we accept switching to SGLang. For pure tok/s on memory-bound decode the MoE will win even at the same on-disk size; for quality at fixed budget the dense 27B is the published flagship coder per Qwen's own benchmarks.

## 4. Recent optimizations relevant to Qwen3.6-27B-class

- **FP8 KV cache (`--kv-cache-dtype fp8`)**: supported in vLLM ≥ 0.19 for Qwen3.6-27B; halves KV memory, enables ~7× concurrency at 256 K with ~5–10 % per-token decode overhead. ([sakamakismile recipe](https://huggingface.co/sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP)).
- **FlashInfer-CUTLASS NVFP4 backend** on GB10 SM121: `VLLM_NVFP4_GEMM_BACKEND=flashinfer-cutlass`, `TORCH_CUDA_ARCH_LIST=12.1a` — required to hit the FP4 tensor cores ([AEON-7 DFlash](https://github.com/AEON-7/Qwen3.6-27B-AEON-Ultimate-Uncensored-DFlash)).
- **FlashAttention-3:** the Qwen3.6-27B architecture mixes Gated DeltaNet (linear-attention) + Gated Attention. FA3 applies only to the gated-attention layers; FA3-Qwen3.6 integration is not explicitly documented on the vLLM recipe page — no claim either way.
- **Sliding-window attention:** not used in this model — full attention in the gated-attn layers, recurrent state in the DeltaNet layers ([Qwen card](https://huggingface.co/Qwen/Qwen3.6-27B)).
- **GGUF imatrix / Unsloth Dynamic 2.0:** Unsloth claims UD-Q4_K_XL > Q4_K_M at near-equivalent size, and provides UD-IQ2 / UD-IQ3 with imatrix calibration. No per-model PPL numbers are published on the card for Qwen3.6-27B; do not cite a number.
- **DFlash external drafter (k=15):** community-trained, separate from Qwen's native MTP — gives the +258 % single-stream uplift on DGX Spark in the AEON-7 v4 image. Not yet upstream in vLLM 0.21.

## 5. Sweet-spot recommendation (≤ 30 GiB joint budget)

**Primary: `sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP` (LLM-only XS, ~21 GiB) under vLLM with NVFP4 + FP8 KV + qwen3_next_mtp(3).**

Why this and not the alternatives:

1. **Memory:** ~21 GiB (LLM-only) leaves a clean 9–10 GiB pad vs the 30 GiB practical budget; even the vision-tower-included 26 GiB variant fits. FP8 official is ~33 GiB → blows the joint budget. BF16 is impossible co-resident. UD-Q4_K_XL GGUF (17.6 GiB) is *smaller* but gives up the FP4 tensor-core path and vLLM MTP, which is where the speedup actually comes from on GB10.
2. **GB10 hardware fit:** NVFP4 is the only quant format that uses GB10's tcgen05 FP4 tensor cores. INT4/AWQ/GPTQ/GGUF Q4 all run on the slower compute path; on a 273 GB/s, FP4-native machine that's the wrong trade.
3. **MTP head preserved:** the `-MTP` variant keeps the 850 MB BF16 head, so we get the 1.24–1.87× single-stream and 1.74× aggregate speedup that DGX Spark NVFP4 alone does not give us. Without MTP, NVFP4 vs INT4 on GB10 is closer.
4. **Quality:** kaitchup notes NVFP4 trails Intel AutoRound INT4 on accuracy ([kaitchup](https://kaitchup.substack.com/p/qwen36-27b-quantization-fp8-vs-int4), paywalled specifics) — this is the load-bearing risk. **Mitigation:** validate critic-tier quality against Qwen3.6-27B-FP8 on the first iteration's eval set before locking it in. If NVFP4 quality fails the gate, fall back to FP8 and re-budget Gemma's `--gpu-memory-utilization`.

**Runner-up: `Qwen/Qwen3.6-27B-FP8` (official, block-128).** ~33 GiB resident — over the soft 30 GiB target. Pull Gemma's `--gpu-memory-utilization` from 0.4 → ~0.32 (~41 GiB Gemma working set) and FP8 fits with ~10 GiB headroom. No FP4 tensor-core speedup, but eliminates NVFP4 accuracy risk and avoids the community-image dependency.

**For the coder workload specifically:** if SGLang is acceptable, **Qwen3-Coder-30B-A3B-FP8 + EAGLE3 draft under SGLang** is competitive — 3 B active params means decode-bandwidth ~9× better than dense, and EAGLE3 stacks on top. But that means running two inference engines (vLLM for Gemma, SGLang for coder) — meaningful operational cost. If the coder tier and critic tier must be the same model and same engine, **the dense Qwen3.6-27B NVFP4-MTP recommendation above covers both**.

## Open questions to resolve before committing

1. Does vLLM 0.21.0 (our current pin) work with the NVFP4-MTP variant, or does the recipe require downgrading to 0.20.2rc1? Worth a focused smoke test before any LOOP_V0 iteration.
2. Confirm NVFP4 accuracy on our critic-tier eval before locking — kaitchup's paywalled comparison is the only signal that NVFP4 trails INT4 on quality.
3. Decide upfront whether the coder tier is "same model as critic" (dense 27B) or "different model" (A3B MoE under SGLang). Operating-model rule says one engine if possible.

## Sources (deduped)

- [Qwen/Qwen3.6-27B HF card](https://huggingface.co/Qwen/Qwen3.6-27B)
- [unsloth/Qwen3.6-27B-GGUF](https://huggingface.co/unsloth/Qwen3.6-27B-GGUF)
- [recipes.vllm.ai/Qwen/Qwen3.6-27B](https://recipes.vllm.ai/Qwen/Qwen3.6-27B)
- [sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP](https://huggingface.co/sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP)
- [sakamakismile/Qwen3.6-27B-NVFP4](https://huggingface.co/sakamakismile/Qwen3.6-27B-NVFP4)
- [AEON-7 NVFP4 repo](https://github.com/AEON-7/Qwen3.6-27B-AEON-Ultimate-Uncensored-DFlash)
- [Quantized Models for Qwen3.6-27B](https://huggingface.co/models?other=base_model%3Aquantized%3AQwen%2FQwen3.6-27B)
- [kaitchup FP8 vs INT4 vs NVFP4](https://kaitchup.substack.com/p/qwen36-27b-quantization-fp8-vs-int4) (paywalled body)
- [vLLM MTP docs](https://docs.vllm.ai/en/latest/features/speculative_decoding/mtp/)
- [vLLM issue #36872 — DeltaNet MTP gibberish](https://github.com/vllm-project/vllm/issues/36872)
- [NVIDIA dev forum slow-NVFP4 thread](https://forums.developer.nvidia.com/t/slow-qwen-3-6-27b-nvfp4-recipe-feedback/370808)
- [Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8](https://huggingface.co/Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8)
- [unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF](https://huggingface.co/unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF)
- [lmsys EAGLE3 SpecForge for Qwen3-Coder-30B-A3B](https://huggingface.co/lmsys/SGLang-EAGLE3-Qwen3-Coder-30B-A3B-Instruct-SpecForge)
- [Qwen3 speed benchmark docs](https://qwen.readthedocs.io/en/latest/getting_started/speed_benchmark.html)
