#!/usr/bin/env bash
# weekly-frontier-agenda.sh -- installed weekly frontier maintenance owner.
# The existing agenda pass retains its gates. A DEFAULT-OFF branch enabled only
# by NARA_WEEKLY_UPGRADE=1 replaces that firing with the bounded review/trial
# cycle under the same owner lock and subscription-only transports.
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
TIMEOUT_BIN="$(command -v timeout || true)"
RATIFIED="$REPO_ROOT/run_state/frontier_tos_ratified"
PAUSE="$REPO_ROOT/run_state/pause_frontier"
LOCK="$REPO_ROOT/run_state/.frontier-agenda-cron.lock"

log "start"

# Gate 1 -- single instance. A held lock means a prior synthesis is still
# running (two frontier CLI turns can be slow). Skipping is normal.
[ ! -L "$LOCK" ] && { [ ! -e "$LOCK" ] || [ -f "$LOCK" ]; } || {
  log "FATAL: lock $LOCK is redirected or non-regular"
  exit 1
}
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

# The installed owner stays unchanged until this explicit flag is set in its
# process environment. Enabled runs replace the legacy agenda pass so the same
# firing cannot spend an agenda call plus the two-call review budget.
WEEKLY_UPGRADE_ENABLED="${NARA_WEEKLY_UPGRADE:-0}"
case "$WEEKLY_UPGRADE_ENABLED" in
  0)
    log "weekly upgrade cycle disabled; launch frontier_agenda --once"
    rc=0
    env -u MOCK_LLM "$PYTHON" -m orchestrator.frontier_agenda --once || rc=$?
    log "agenda done rc=$rc"
    exit "$rc"
    ;;
  1) ;;
  *) log "FATAL: NARA_WEEKLY_UPGRADE must be exactly 0 or 1"; exit 2 ;;
esac

[ -n "$TIMEOUT_BIN" ] || { log "FATAL: timeout command is unavailable"; exit 1; }

bounded_uint() {
  local name="$1" value="$2" minimum="$3" maximum="$4"
  if [[ ! "$value" =~ ^(0|[1-9][0-9]{0,4})$ ]] \
      || (( value < minimum || value > maximum )); then
    log "FATAL: $name must be an integer in [$minimum,$maximum]"
    return 2
  fi
}

REVIEW_DEADLINE_S="${NARA_WEEKLY_UPGRADE_REVIEW_DEADLINE_S:-600}"
CALL_TIMEOUT_S="${NARA_WEEKLY_UPGRADE_CALL_TIMEOUT_S:-300}"
FETCH_DEADLINE_S="${NARA_WEEKLY_UPGRADE_FETCH_DEADLINE_S:-60}"
CYCLE_DEADLINE_S="${NARA_WEEKLY_UPGRADE_CYCLE_DEADLINE_S:-3300}"
bounded_uint NARA_WEEKLY_UPGRADE_REVIEW_DEADLINE_S "$REVIEW_DEADLINE_S" 181 1800
bounded_uint NARA_WEEKLY_UPGRADE_CALL_TIMEOUT_S "$CALL_TIMEOUT_S" 181 1800
bounded_uint NARA_WEEKLY_UPGRADE_FETCH_DEADLINE_S "$FETCH_DEADLINE_S" 1 120
bounded_uint NARA_WEEKLY_UPGRADE_CYCLE_DEADLINE_S "$CYCLE_DEADLINE_S" 1 7200
if (( CALL_TIMEOUT_S > REVIEW_DEADLINE_S )); then
  log "FATAL: call timeout cannot exceed the review deadline"
  exit 2
fi

OUTPUT_ROOT="${NARA_WEEKLY_UPGRADE_OUTPUT_ROOT:-${REPO_ROOT}_weekly_upgrade_runs}"
SOURCE_PACKET="${NARA_WEEKLY_UPGRADE_SOURCE_PACKET:-}"
EXPLICIT_FETCH_CONFIG="${NARA_WEEKLY_UPGRADE_FETCH_CONFIG:-}"
FETCH_CONFIG="${EXPLICIT_FETCH_CONFIG:-$REPO_ROOT/bench/weekly_upgrade_eval/sources.json}"
if [ -n "$SOURCE_PACKET" ] && [ -n "$EXPLICIT_FETCH_CONFIG" ]; then
  log "FATAL: choose a source packet or fetch config, not both"
  exit 2
fi

cycle_args=(
  -m orchestrator.weekly_upgrade_cycle --run
  --repo-root "$REPO_ROOT"
  --output-root "$OUTPUT_ROOT"
  --frontier-call-budget 2
  --review-deadline-s "$REVIEW_DEADLINE_S"
  --call-timeout-s "$CALL_TIMEOUT_S"
  --cycle-deadline-s "$CYCLE_DEADLINE_S"
  --fetch-deadline-s "$FETCH_DEADLINE_S"
  --max-gpu-minutes 120
)
if [ -n "$SOURCE_PACKET" ]; then
  cycle_args+=(--source-packet "$SOURCE_PACKET")
else
  cycle_args+=(--fetch-config "$FETCH_CONFIG")
fi
if [ -n "${NARA_WEEKLY_UPGRADE_TRIAL_MANIFEST:-}" ]; then
  cycle_args+=(--trial-manifest "$NARA_WEEKLY_UPGRADE_TRIAL_MANIFEST")
fi

# `timeout` is a backstop if the Python controller or its supervision path is
# killed/wedged. The controller's smaller internal deadline preserves time to
# write a terminal receipt; the outer owner then sends TERM and KILL finitely.
HARD_DEADLINE_S=$((CYCLE_DEADLINE_S + 20))
log "launch: weekly upgrade cycle (subscription calls=2, Spark cap=120m)"
rc=0
env -u MOCK_LLM WEEKLY_UPGRADE_OWNER_LOCK_FD=9 \
  "$TIMEOUT_BIN" --signal=TERM --kill-after=10s "${HARD_DEADLINE_S}s" \
  "$PYTHON" "${cycle_args[@]}" || rc=$?
log "weekly upgrade cycle done rc=$rc"
exit "$rc"

# ---------------------------------------------------------------------------
# Current owner schedule is 30 5 * * 0 (Sunday 05:30 UTC). This file does not
# install or edit it. To halt frontier work without touching crontab:
#   touch /home/decross1/projects/a_bgt_rsi/run_state/pause_frontier
# To halt only this cycle while retaining the agenda:
#   touch /home/decross1/projects/a_bgt_rsi/run_state/pause_weekly_upgrade
# ---------------------------------------------------------------------------
