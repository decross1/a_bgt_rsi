#!/usr/bin/env bash
# day1_block2_vllm_serve — launch vLLM Gemma 4 26B NVFP4 (baseline, no MTP).
#
# vLLM image RE-PINNED 2026-05-18 (human-authorized) to v0.20.0. The prior
# :gemma4-cu130 tag shipped vLLM 0.19.1.dev6, which cannot load the
# nvidia/Gemma-4-26B-A4B-NVFP4 checkpoint (KeyError on per-expert NVFP4
# input_scale at gemma4.py load_weights). The checkpoint's model card
# specifies vllm/vllm-openai:v0.20.0. MTP stays deferred (DECISIONS.md D-019).
#
# Run with the docker group active:  sg docker -c 'bash setup/day1_vllm_serve.sh'
set -uo pipefail
cd /home/decross1/projects/a_bgt_rsi || exit 1

IMG=vllm/vllm-openai:v0.20.0
LOG=/tmp/vllm_startup.log

echo "[$(date +%T)] === pull $IMG ==="
docker pull "$IMG" || { echo "FATAL: docker pull failed"; exit 1; }

echo "[$(date +%T)] === image digest (D-017) -> run_state/vllm_image.digest ==="
docker inspect --format '{{join .RepoDigests "\n"}}' "$IMG" | tee run_state/vllm_image.digest

echo "[$(date +%T)] === image vllm + torch/CUDA version ==="
docker run --rm --entrypoint python3 "$IMG" -c "import vllm,torch; print('vllm',vllm.__version__); print('torch',torch.__version__,'cuda',torch.version.cuda)" 2>&1 | tail -3

echo "[$(date +%T)] === remove any prior vllm-gemma4 container ==="
docker rm -f vllm-gemma4 2>/dev/null || true

echo "[$(date +%T)] === docker run (NVFP4 baseline, --moe-backend marlin) ==="
docker run -d --name vllm-gemma4 --gpus all \
  -v /mnt/models/gemma-4-26b-a4b-nvfp4:/models/gemma-4-26b-a4b-nvfp4:ro \
  -p 8000:8000 \
  "$IMG" \
  --model /models/gemma-4-26b-a4b-nvfp4 \
  --served-model-name gemma-4-26b-a4b \
  --moe-backend marlin \
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
echo "[$(date +%T)] === DONE ==="
