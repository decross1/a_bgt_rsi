#!/usr/bin/env bash
# weekly-frontier-agenda.sh -- weekly frontier agenda-synthesis runway.
# Shipped DARK (LOOP_V1 P2): NOT installed in crontab, and it FAILS CLOSED
# until the human clears the G1 frontier-ToS gate by creating the sentinel
# run_state/frontier_tos_ratified. Hypothesis/ledger text leaves the box on
# every synthesis call, so the gate is the human's, not the apparatus's.
# Clones the run-coordinator.sh gate ladder:
#   1. flock single-instance      run_state/.frontier-agenda-cron.lock
#   2. ToS sentinel               run_state/frontier_tos_ratified MUST exist
#   3. human kill switch          run_state/pause_frontier MUST NOT exist
# A refusal at gates 1-3 logs and exits 0: pre-ratification a refusal is the
# DESIGNED state, not an error, and cron must stay quiet about it. No memory
# preflight: synthesis only spawns the frontier CLIs (subprocess seams), it
# never loads a local model.
set -euo pipefail

# Resolve the repo root from this script's own location (cron/ sits one level
# below the root) so the script works regardless of the caller cwd.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT"

mkdir -p "$REPO_ROOT/logs"
exec >> "$REPO_ROOT/logs/frontier-cron.log" 2>&1

log() { echo "[weekly-frontier-agenda] $(date -u +%FT%TZ) $*"; }

PYTHON="$REPO_ROOT/.venv-chroma/bin/python"
RATIFIED="$REPO_ROOT/run_state/frontier_tos_ratified"
PAUSE="$REPO_ROOT/run_state/pause_frontier"
LOCK="$REPO_ROOT/run_state/.frontier-agenda-cron.lock"

log "start"

# Gate 1 -- single instance. A held lock means a prior synthesis is still
# running (two frontier CLI turns can be slow). Skipping is normal.
exec 9>"$LOCK"
if ! flock -n 9; then
  log "SKIP: lock $LOCK is held -- a prior synthesis is still running. Exit 0."
  exit 0
fi

# Gate 2 -- ToS sentinel. ONLY the human creates this file, and creating it
# IS the act of clearing G1 (frontier ToS/off-box). Until then every firing
# refuses; this refusal is the designed dark state.
if [ ! -f "$RATIFIED" ]; then
  log "REFUSE: frontier ToS gate G1 not cleared ($RATIFIED absent). Ledger text may not leave the box; this refusal is the designed dark state. Exit 0."
  exit 0
fi

# Gate 3 -- pause file. Anyone (human or agent) may `touch` it to halt the
# runway; only the human removes it. Nothing bypasses this gate.
if [ -f "$PAUSE" ]; then
  log "REFUSE: pause file $PAUSE present -- human kill switch honored. Exit 0."
  exit 0
fi

[ -x "$PYTHON" ] || { log "FATAL: python not found at $PYTHON"; exit 1; }

# One synthesis pass. env -u MOCK_LLM (rule 10: a stubbed frontier makes the
# agenda meaningless).
log "launch: frontier_agenda --once"
rc=0
env -u MOCK_LLM "$PYTHON" -m orchestrator.frontier_agenda --once || rc=$?
log "done rc=$rc"
exit "$rc"

# ---------------------------------------------------------------------------
# !!! DO NOT ENABLE BEFORE G1 (frontier ToS) IS CLEARED !!!
# Installing this in crontab today is safe-but-pointless (every firing refuses
# at gate 2 and exits 0), but the operating intent is that the crontab line
# and the sentinel land TOGETHER, by the HUMAN, on ratification day:
#   crontab -e    # weekly, Monday 08:00; the script manages its own log
#   0 8 * * 1 /home/decross1/projects/a_bgt_rsi/cron/weekly-frontier-agenda.sh
#   touch /home/decross1/projects/a_bgt_rsi/run_state/frontier_tos_ratified
# To halt later without touching crontab:
#   touch /home/decross1/projects/a_bgt_rsi/run_state/pause_frontier
# ---------------------------------------------------------------------------
