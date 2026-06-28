#!/usr/bin/env bash
# serve-models.sh -- canonical launcher for the two resident vLLM servers on the
# GB10 unified-memory box. Captures the EXACT production `docker run` for each so
# the config (incl. --gpu-memory-utilization and --restart) survives a container
# re-create -- closing the "un-scripted docker run" gap (D-057, 2026-06-28).
#
# MEMORY BUDGET (D-057): both servers must co-reside UNDER the 30 GiB OS margin
# the preflight guards (experiments/exp008_qat_eval/preflight_mem.sh; ref the
# 2026-06-08 arm-C freeze). The two NVFP4 27B-class weight sets are ~18.6-18.9
# GiB EACH and near-incompressible; the only real slack is KV cache. Gemma was
# trimmed 0.40 -> 0.30 (it carried 26 GiB / 21.87x KV headroom; 0.30 still gives
# ~11x for single-stream orchestration) which frees ~12 GiB. Qwen stays 0.25
# (its weights dominate its budget; little to give). Net: MemAvailable ~35 GiB
# with BOTH resident, clearing the 30 GiB margin with cushion.
#   * Do NOT raise utilization without re-running preflight_mem.sh and confirming
#     the margin still clears with both servers up.
#   * NEVER lower the OS margin instead (inviolate rule 7; the freeze disproved a
#     thin margin).
#   * Gemma MUST log `Using 'MARLIN' NvFp4 MoE backend` (inviolate rule 2). If it
#     logs CUTLASS_FP4, STOP -- the flag did not pick up.
set -euo pipefail

IMAGE="vllm/vllm-openai:v0.21.0"   # inviolate version pin (CLAUDE.md rule 2)

serve_gemma() {
  docker rm -f vllm-gemma4 2>/dev/null || true
  docker run -d --name vllm-gemma4 --restart unless-stopped --gpus all \
    -p 8000:8000 \
    -v /mnt/models/gemma-4-26b-a4b-nvfp4:/models/gemma-4-26b-a4b-nvfp4 \
    -v /mnt/models/gemma-4-26b-a4b-it-assistant:/models/gemma-4-26b-a4b-it-assistant \
    "$IMAGE" \
    --model /models/gemma-4-26b-a4b-nvfp4 \
    --served-model-name gemma-4-26b-a4b \
    --moe-backend marlin \
    --speculative-config '{"method":"mtp","model":"/models/gemma-4-26b-a4b-it-assistant","num_speculative_tokens":4}' \
    --max-model-len 32768 \
    --max-num-batched-tokens 8192 \
    --gpu-memory-utilization 0.30 \
    --enable-prefix-caching \
    --trust-remote-code \
    --enable-auto-tool-choice \
    --tool-call-parser gemma4
}

serve_qwen() {
  docker rm -f vllm-qwen 2>/dev/null || true
  docker run -d --name vllm-qwen --restart unless-stopped --gpus all \
    -p 8001:8000 \
    -v /mnt/models/qwen3.6-27b-nvfp4-mtp:/models/qwen3.6-27b-nvfp4-mtp \
    "$IMAGE" \
    --model /models/qwen3.6-27b-nvfp4-mtp \
    --served-model-name qwen3.6-27b-nvfp4-mtp \
    --trust-remote-code \
    --quantization modelopt \
    --language-model-only \
    --max-model-len 16384 \
    --max-num-seqs 2 \
    --kv-cache-dtype fp8 \
    --gpu-memory-utilization 0.25 \
    --reasoning-parser qwen3 \
    --speculative-config '{"method":"qwen3_5_mtp","num_speculative_tokens":3}' \
    --enable-auto-tool-choice \
    --tool-call-parser qwen3_coder
}

case "${1:-both}" in
  gemma) serve_gemma ;;
  qwen)  serve_qwen ;;
  both)  serve_gemma; serve_qwen ;;
  *) echo "usage: $0 [gemma|qwen|both]" >&2; exit 2 ;;
esac
echo "launched: ${1:-both} (poll :8000 / :8001 /v1/models for readiness; ~2-3 min load each)"
