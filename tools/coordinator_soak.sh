#!/usr/bin/env bash
# coordinator_soak.sh -- SUPERVISED N-cycle soak driver for the coordinator.
# Usage: tools/coordinator_soak.sh --cycles N --interval-s S [--budget B] [--i-am-supervising]
#
# The one sanctioned exception to the dark always-on runway
# (cron/run-coordinator.sh): a HUMAN WATCHING THE TERMINAL may drive N spaced
# `coordinator --once --execute` cycles before D-049 is ratified, by passing
# --i-am-supervising. That flag bypasses ONLY the ratification sentinel
# (run_state/d049_ratified); it NEVER bypasses the pause file
# (run_state/pause_coordinator), which is re-checked before every cycle. Each
# cycle is still single-shot `--once`; this loop is the human's cadence, not
# a daemon (foreground only, dies with the tty).
#
# Exit codes: 0 = clean stop (N cycles done, pause file seen, mem-guard stop,
# or INT/TERM); 1 = refused at startup / fatal misconfig; 2 = usage error.
# One JSON line per cycle -> logs/coordinator-soak.log; progress -> stdout.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT"

PYTHON="$REPO_ROOT/.venv-chroma/bin/python"
RATIFIED="$REPO_ROOT/run_state/d049_ratified"
PAUSE="$REPO_ROOT/run_state/pause_coordinator"
MEM_GUARD="$REPO_ROOT/experiments/exp008_qat_eval/preflight_mem.sh"
SOAK_LOG="$REPO_ROOT/logs/coordinator-soak.log"
# Cycles call the ALREADY-RESIDENT servers (gemma :8000, qwen :8001) and
# cannot launch a new model; need=0, with the guard's hard-pinned 30 GiB
# OS margin still enforced (need=25 refused every cycle by construction —
# caught live on the first soak, 2026-06-10).
MEM_NEED_GIB=0

CYCLES="" INTERVAL_S="" BUDGET=6 SUPERVISED=0
usage() { echo "usage: $0 --cycles N --interval-s S [--budget B] [--i-am-supervising]" >&2; exit 2; }
while [ $# -gt 0 ]; do
  case "$1" in
    --cycles)           CYCLES="${2:?--cycles needs a value}"; shift 2 ;;
    --interval-s)       INTERVAL_S="${2:?--interval-s needs a value}"; shift 2 ;;
    --budget)           BUDGET="${2:?--budget needs a value}"; shift 2 ;;
    --i-am-supervising) SUPERVISED=1; shift ;;
    *) echo "unknown arg: $1" >&2; usage ;;
  esac
done
[[ "$CYCLES" =~ ^[1-9][0-9]*$ && "$INTERVAL_S" =~ ^[0-9]+$ && "$BUDGET" =~ ^[1-9][0-9]*$ ]] || usage

log() { echo "[soak] $(date -u +%FT%TZ) $*"; }

[ -x "$PYTHON" ] || { log "FATAL: python not found at $PYTHON"; exit 1; }

# Fail closed exactly like the cron runway unless a human attests supervision.
# (--i-am-supervising substitutes for the sentinel only -- gate (a), never (b).)
if [ "$SUPERVISED" -ne 1 ] && [ ! -f "$RATIFIED" ]; then
  log "REFUSE: D-049 not ratified ($RATIFIED absent) and no --i-am-supervising."
  log "        Pre-ratification soaks require a watching human. Exit 1."
  exit 1
fi

# shellcheck source=../experiments/exp008_qat_eval/preflight_mem.sh
source "$MEM_GUARD"
mkdir -p "$REPO_ROOT/logs"

STOP=0
trap 'STOP=1; log "INT/TERM received -- stopping after current bookkeeping"' INT TERM

log "soak start: cycles=$CYCLES interval_s=$INTERVAL_S budget=$BUDGET supervised=$SUPERVISED"
for (( i = 1; i <= CYCLES; i++ )); do
  if [ -f "$PAUSE" ]; then
    log "STOP before cycle $i/$CYCLES: pause file $PAUSE present (never bypassed). Exit 0."
    exit 0
  fi
  if ! preflight_mem_guard "$MEM_NEED_GIB"; then
    log "STOP before cycle $i/$CYCLES: mem guard refused need=${MEM_NEED_GIB}GiB+margin. Exit 0."
    exit 0
  fi
  start_ts="$(date -u +%FT%TZ)"
  log "cycle $i/$CYCLES start"
  rc=0
  env -u MOCK_LLM NARA_SKEPTIC=1 "$PYTHON" -m orchestrator.coordinator \
    --once --execute --budget "$BUDGET" || rc=$?
  end_ts="$(date -u +%FT%TZ)"
  printf '{"cycle":%d,"of":%d,"start":"%s","end":"%s","exit_code":%d,"supervised":%s}\n' \
    "$i" "$CYCLES" "$start_ts" "$end_ts" "$rc" \
    "$([ "$SUPERVISED" -eq 1 ] && echo true || echo false)" >> "$SOAK_LOG"
  log "cycle $i/$CYCLES end rc=$rc"
  if [ "$STOP" -eq 1 ]; then log "STOP: signal during cycle $i. Exit 0."; exit 0; fi
  if (( i < CYCLES )); then
    log "sleeping ${INTERVAL_S}s before next cycle"
    sleep "$INTERVAL_S" & SLEEP_PID=$!
    wait "$SLEEP_PID" || true
    kill "$SLEEP_PID" 2>/dev/null || true
    if [ "$STOP" -eq 1 ]; then log "STOP: signal during sleep. Exit 0."; exit 0; fi
  fi
done
log "soak complete: $CYCLES cycle(s) done."
