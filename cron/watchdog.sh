#!/usr/bin/env bash
# Model-server watchdog (downtime lesson 2026-08-15). Every run: if a prod
# vLLM container is not running, start it and log LOUDLY. Never touches a
# container that exists-and-runs; never creates containers (docker start
# only — the canonical launch stays cron/serve-models.sh, D-057).
#
# Deliberate guard: the A/B-window scratch container name (vllm-qwen-ab)
# doubles as a "window open" sentinel — while it exists, prod being down is
# INTENTIONAL and the watchdog stands down (a window is a human/primary
# decision; auto-restarting prod mid-window would collide on ports/memory).
#
# Install (human, one line):
#   */5 * * * * /home/decross1/projects/a_bgt_rsi/cron/watchdog.sh >> /home/decross1/projects/a_bgt_rsi/logs/watchdog.log 2>&1
set -u
ts() { date -u +%FT%TZ; }

if docker ps -a --format '{{.Names}}' | grep -q '^vllm-qwen-ab'; then
  echo "[$(ts)] A/B window open (vllm-qwen-ab present) — standing down"
  exit 0
fi

# Reap stale run-registry entries (2026-08-15): a session that dies without
# clear_active_run() otherwise shows on the dashboard as a "run" forever (two
# June entries were still there 57 days later). Explicit + append-only: docs
# move to run_state/active_runs/abandoned/ with a reason, never deleted.
REPO="/home/decross1/projects/a_bgt_rsi"
"$REPO/.venv-chroma/bin/python" -m orchestrator.active_run --reap 2>&1 \
  | grep -v '^0 stale run' || true

rc=0
for c in vllm-gemma4 vllm-qwen; do
  running=$(docker inspect -f '{{.State.Running}}' "$c" 2>/dev/null || echo "absent")
  if [ "$running" != "true" ]; then
    echo "[$(ts)] WATCHDOG: $c is $running — starting"
    docker start "$c" || { echo "[$(ts)] WATCHDOG: docker start $c FAILED"; rc=1; }
  fi
done
exit $rc
