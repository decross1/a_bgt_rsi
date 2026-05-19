#!/usr/bin/env bash
# day2 throughput tuning — relaunch vLLM Gemma 4 26B NVFP4 WITH MTP.
#
# Why: the day_2 50-call sweep failed check #3 (aggregate 29.75 tok/s vs the
# 40 floor). Investigation (D-021) established decode is weight-bandwidth-
# bound at ~32 tok/s on GB10 — clock/kernel levers are dead. MTP (Multi-Token
# Prediction) speculative decoding is the one lever that clears the floor: it
# reads the target weights once per K tokens. A DGX Spark community benchmark
# reached ~108 tok/s single-stream with MTP on this exact model.
#
# Image RE-PINNED v0.20.0 -> v0.21.0: v0.21.0 is the FIRST vLLM release that
# includes PR #41745 (Gemma4 MTP support, merged 2026-05-06 @ 27e0057). The
# v0.20.0 image has no gemma4_mtp.py and no Gemma4 MTP registry entry. Because
# v0.21.0 is a release (not the preview image), the merged fix is bundled —
# no infra/vllm_patches/gemma4_mtp.py bind-mount is needed.
#
# Run with the docker group active:  sg docker -c 'bash setup/day2_vllm_serve_mtp.sh'
set -uo pipefail
cd /home/decross1/projects/a_bgt_rsi || exit 1

IMG=vllm/vllm-openai:v0.21.0
LOG=/tmp/vllm_startup_mtp.log

echo "[$(date +%T)] === pull $IMG ==="
docker pull "$IMG" || { echo "FATAL: docker pull failed"; exit 1; }

echo "[$(date +%T)] === image digest (D-017) ==="
docker inspect --format '{{join .RepoDigests "\n"}}' "$IMG"

echo "[$(date +%T)] === image vllm + torch/CUDA version ==="
docker run --rm --entrypoint python3 "$IMG" -c \
  "import vllm,torch; print('vllm',vllm.__version__); print('torch',torch.__version__,'cuda',torch.version.cuda)" 2>&1 | tail -3

echo "[$(date +%T)] === remove any prior vllm-gemma4 container ==="
docker rm -f vllm-gemma4 2>/dev/null || true

# MTP speculative decoding. The drafter MUST pair with the IT target (D-019);
# num_speculative_tokens=4 per D-019 and the DGX Spark community benchmark.
SPEC='{"method":"mtp","model":"/models/gemma-4-26b-a4b-it-assistant","num_speculative_tokens":4}'

echo "[$(date +%T)] === docker run (NVFP4 + MTP, --moe-backend marlin) ==="
docker run -d --name vllm-gemma4 --gpus all \
  -v /mnt/models/gemma-4-26b-a4b-nvfp4:/models/gemma-4-26b-a4b-nvfp4:ro \
  -v /mnt/models/gemma-4-26b-a4b-it-assistant:/models/gemma-4-26b-a4b-it-assistant:ro \
  -p 8000:8000 \
  "$IMG" \
  --model /models/gemma-4-26b-a4b-nvfp4 \
  --served-model-name gemma-4-26b-a4b \
  --moe-backend marlin \
  --speculative-config "$SPEC" \
  --max-model-len 32768 \
  --max-num-batched-tokens 8192 \
  --trust-remote-code \
  || { echo "FATAL: docker run failed"; exit 1; }

echo "[$(date +%T)] === wait for readiness (poll /health, up to ~15 min) ==="
READY=no
for i in $(seq 1 180); do
  if curl -fsS http://localhost:8000/health >/dev/null 2>&1; then
    READY=yes; echo "[$(date +%T)] server READY after ~$((i*5))s"; break
  fi
  if ! docker ps --format '{{.Names}}' | grep -qx vllm-gemma4; then
    echo "[$(date +%T)] CONTAINER EXITED EARLY"; break
  fi
  sleep 5
done

echo "[$(date +%T)] === startup log -> $LOG ==="
docker logs vllm-gemma4 > "$LOG" 2>&1
echo "log lines: $(wc -l < "$LOG")"
echo "container status: $(docker ps -a --filter name=vllm-gemma4 --format '{{.Status}}')"
echo "READY=$READY"
echo
echo "[$(date +%T)] === verification greps ==="
echo "-- MoE backend (MUST be MARLIN) --"
grep -iE "marlin|cutlass" "$LOG" | head -5
echo "-- speculative / MTP --"
grep -iE "speculat|mtp|gemma4_mtp|draft" "$LOG" | head -10
echo "[$(date +%T)] === DONE ==="
