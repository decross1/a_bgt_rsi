#!/usr/bin/env bash
# exp008_qat_eval — bring up / tear down the SCRATCH QAT-eval container.
#
# SAFETY (CLAUDE.md inviolate rules): this script is EVAL-ONLY and SCRATCH-ONLY.
#   * It binds the scratch port :8002 ONLY. It MUST NEVER reference the
#     production port, the production image, the production container
#     (vllm-gemma4), or the MARLIN / MTP launch args. The production endpoint is
#     touched by NOTHING in this file.
#   * Distinct container name (qat-eval-scratch) so a teardown can never hit the
#     production container.
#
# Usage:
#   serve_qat.sh up B            # launch arm B (llama.cpp GGUF) on :8002
#   serve_qat.sh up C            # launch arm C (vLLM unquantized QAT) on :8002
#   serve_qat.sh up B --dry-run  # print the args, do NOT execute
#   serve_qat.sh down            # tear down the scratch container
set -uo pipefail

# --- constants: SCRATCH ONLY -------------------------------------------------
SCRATCH_PORT=8002
SCRATCH_NAME=qat-eval-scratch

# Arm B (llama.cpp GGUF). Image + model path are placeholders filled at run time.
LLAMACPP_IMG="ghcr.io/ggml-org/llama.cpp:server"
ARM_B_GGUF="/mnt/models/gemma-4-26b-a4b-it-qat-q4_0-gguf/model.gguf"   # PLACEHOLDER
ARM_B_SERVED_NAME="gemma-4-26b-a4b-qat-q4_0"

# Arm C (vLLM, unquantized QAT). EVAL image — NOT the production pin/args.
VLLM_EVAL_IMG="vllm/vllm-openai:v0.21.0"
ARM_C_WEIGHTS="/mnt/models/gemma-4-26b-a4b-it-qat-q4_0-unquantized"    # PLACEHOLDER
ARM_C_SERVED_NAME="gemma-4-26b-a4b-qat-unquantized"

usage() {
  cat <<EOF
exp008 serve_qat.sh — SCRATCH-only QAT eval server on :${SCRATCH_PORT}

  serve_qat.sh up B  [--dry-run]   launch arm B (llama.cpp GGUF) on :${SCRATCH_PORT}
  serve_qat.sh up C  [--dry-run]   launch arm C (vLLM unquantized QAT) on :${SCRATCH_PORT}
  serve_qat.sh down  [--dry-run]   tear down scratch container '${SCRATCH_NAME}'

NEVER touches production (prod port / vllm-gemma4 / MARLIN / MTP).
EOF
}

# Build the docker argv for an arm into the global array DOCKER_ARGS.
build_args() {
  local arm="$1"
  case "$arm" in
    B)
      DOCKER_ARGS=(
        docker run -d --name "$SCRATCH_NAME" --gpus all
        -v "${ARM_B_GGUF}:/models/model.gguf:ro"
        -p "${SCRATCH_PORT}:${SCRATCH_PORT}"
        "$LLAMACPP_IMG"
        --model /models/model.gguf
        --alias "$ARM_B_SERVED_NAME"
        --host 0.0.0.0
        --port "${SCRATCH_PORT}"
        --temp 0
        --parallel 1
      )
      ;;
    C)
      DOCKER_ARGS=(
        docker run -d --name "$SCRATCH_NAME" --gpus all
        -v "${ARM_C_WEIGHTS}:/models/qat-unquantized:ro"
        -p "${SCRATCH_PORT}:${SCRATCH_PORT}"
        "$VLLM_EVAL_IMG"
        --model /models/qat-unquantized
        --served-model-name "$ARM_C_SERVED_NAME"
        --host 0.0.0.0
        --port "${SCRATCH_PORT}"
        # This box (DGX Spark / GB10) has ~121.7 GiB UNIFIED memory shared with
        # the production vLLM server AND the OS/desktop, so vLLM typically sees
        # only ~60 GiB free even with the scratch arm alone. The unquantized-26B
        # weights are ~48 GiB; vLLM's startup check requires free >= util*total,
        # so util*121.7 must stay UNDER the ~60 GiB free. 0.46 -> ~56 GiB budget
        # (passes the check; ~8 GiB left for KV after weights). The eval prompts
        # are short so a small context is ample. If free memory is lower on your
        # box (other resident processes), drop this further or free memory.
        --gpu-memory-utilization 0.46
        --max-model-len 8192
        # Gemma 4 is multimodal (image-text-to-text); its vision encoder emits
        # max_tokens_per_mm_item (~2496) which, with chunked MM input disabled,
        # must fit in one batch. The default max_num_batched_tokens (2048) is
        # too small and vLLM refuses to start. Raise it above the per-item
        # budget (the text-only eval never sends images, but the encoder budget
        # is computed at startup regardless).
        --max-num-batched-tokens 8192
        --trust-remote-code
      )
      ;;
    *)
      echo "FATAL: unknown arm '$arm' (expected B or C)" >&2
      exit 1
      ;;
  esac
}

cmd_up() {
  local arm="${1:-}"
  local dry="${2:-}"
  if [[ -z "$arm" ]]; then usage; exit 1; fi
  build_args "$arm"

  # Pre-flight free-memory guard (2026-06-08 arm-C freeze). Refuses a launch that
  # would over-commit the GB10's ~121.7 GiB UNIFIED memory and starve the OS.
  # Needs: arm B (llama.cpp Q4_0 GGUF) ~16 GiB; arm C (vLLM unquantized, the
  # --gpu-memory-utilization 0.46 reserved budget) ~56 GiB.
  source "$(dirname "${BASH_SOURCE[0]}")/preflight_mem.sh"
  local need; case "$arm" in B) need=16 ;; C) need=56 ;; *) need=56 ;; esac

  if [[ "$dry" == "--dry-run" ]]; then
    echo "# DRY RUN — arm ${arm} on SCRATCH :${SCRATCH_PORT} (no execution)"
    printf '%q ' "${DOCKER_ARGS[@]}"; echo
    # Advisory only on a dry run: print the guard verdict, never abort.
    preflight_mem_guard "$need" || echo "# (advisory) pre-flight guard would REFUSE arm ${arm} (need ${need}GiB) at current free memory"
    return 0
  fi

  # Hard gate before any real launch — fail-closed on non-zero (inviolate rule 7).
  preflight_mem_guard "$need" || { echo "FATAL: pre-flight memory guard refused arm ${arm} launch (need ${need}GiB + OS margin); free memory or use a smaller arm" >&2; exit 1; }

  echo "[$(date +%T)] removing any prior scratch container '${SCRATCH_NAME}'"
  docker rm -f "$SCRATCH_NAME" 2>/dev/null || true
  echo "[$(date +%T)] launching arm ${arm} on :${SCRATCH_PORT}"
  "${DOCKER_ARGS[@]}" || { echo "FATAL: docker run failed" >&2; exit 1; }
  echo "[$(date +%T)] waiting for readiness on :${SCRATCH_PORT} (up to ~15 min)"
  for i in $(seq 1 180); do
    if curl -fsS "http://localhost:${SCRATCH_PORT}/health" >/dev/null 2>&1 \
       || curl -fsS "http://localhost:${SCRATCH_PORT}/v1/models" >/dev/null 2>&1; then
      echo "[$(date +%T)] scratch server READY after ~$((i*5))s"; return 0
    fi
    if ! docker ps --format '{{.Names}}' | grep -qx "$SCRATCH_NAME"; then
      echo "[$(date +%T)] CONTAINER EXITED EARLY"; docker logs "$SCRATCH_NAME" 2>&1 | tail -20; exit 1
    fi
    sleep 5
  done
  echo "[$(date +%T)] WARNING: readiness not confirmed in window"
}

cmd_down() {
  local dry="${1:-}"
  if [[ "$dry" == "--dry-run" ]]; then
    echo "# DRY RUN — teardown (no execution)"
    echo "docker rm -f ${SCRATCH_NAME}"
    return 0
  fi
  echo "[$(date +%T)] tearing down scratch container '${SCRATCH_NAME}'"
  docker rm -f "$SCRATCH_NAME" 2>/dev/null || true
  echo "[$(date +%T)] done"
}

main() {
  local sub="${1:-}"
  case "$sub" in
    up)   shift; cmd_up "$@";;
    down) shift; cmd_down "$@";;
    -h|--help|"") usage;;
    *) echo "FATAL: unknown subcommand '$sub'" >&2; usage; exit 1;;
  esac
}

main "$@"
