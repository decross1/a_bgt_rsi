#!/usr/bin/env bash
# day4 — relaunch vLLM Gemma 4 26B NVFP4 with tool calling enabled.
#
# Why: day4_block2_e2e_test needs the OpenAI-compatible chat-completions API
# to accept tool_choice="auto". vLLM rejects that unless the server was
# launched with `--enable-auto-tool-choice` AND `--tool-call-parser <name>`.
# vLLM 0.21.0 ships a Gemma4-specific parser registered as `gemma4` at
# /usr/local/lib/python3.12/dist-packages/vllm/tool_parsers/__init__.py:185.
#
# This script is a delta over setup/day2_vllm_serve_mtp.sh: same image, same
# weights, same MoE backend, same MTP speculative config -- two flags added.
# All Day-2 throughput properties (MARLIN MoE backend, MTP draft model) are
# preserved.
#
# Run with the docker group active:  sg docker -c 'bash setup/day4_vllm_serve_tools.sh'
set -uo pipefail
cd /home/decross1/projects/a_bgt_rsi || exit 1

IMG=vllm/vllm-openai:v0.21.0
LOG=/tmp/vllm_startup_tools.log

echo "[$(date +%T)] === pull $IMG ==="
docker pull "$IMG" || { echo "FATAL: docker pull failed"; exit 1; }

echo "[$(date +%T)] === image digest (D-017) ==="
docker inspect --format '{{join .RepoDigests "\n"}}' "$IMG"

echo "[$(date +%T)] === remove any prior vllm-gemma4 container ==="
docker rm -f vllm-gemma4 2>/dev/null || true

# MTP speculative decoding -- unchanged from day2.
SPEC='{"method":"mtp","model":"/models/gemma-4-26b-a4b-it-assistant","num_speculative_tokens":4}'

echo "[$(date +%T)] === docker run (NVFP4 + MTP + tool-calling) ==="
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
  --enable-auto-tool-choice \
  --tool-call-parser gemma4 \
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
echo "-- MoE backend (MUST be MARLIN, per CLAUDE.md inviolate rule 2) --"
grep -iE "marlin|cutlass" "$LOG" | head -5
echo "-- speculative / MTP --"
grep -iE "speculat|mtp|gemma4_mtp|draft" "$LOG" | head -10
echo "-- tool-call parser registration --"
grep -iE "tool.?call|tool.?parser|gemma4_tool" "$LOG" | head -10
echo "[$(date +%T)] === DONE ==="
