#!/usr/bin/env bash
# run-coordinator.sh -- the always-on runway for the coordinator brain.
# Shipped DARK on 2026-06-10 (SP-wf-2026-06-10-S3-runway): NOT installed in
# crontab, and it FAILS CLOSED until the human ratifies D-049. The CLAUDE.md
# continuous-orchestrator guardrail stands until that ratification; this
# script exists so the only thing ratification changes is one crontab line
# plus one sentinel file -- no new code lands on the day the bar is cleared.
#
# One invocation = ONE `coordinator --once --execute` cycle (the coordinator
# itself stays single-shot; cron supplies the cadence). Every launch is gated:
#   1. flock single-instance      run_state/.coordinator-cron.lock
#   2. ratification sentinel      run_state/d049_ratified MUST exist
#   3. human kill switch          run_state/pause_coordinator MUST NOT exist
#   4. memory preflight           need=0 (resident servers) + the guard's 30 GiB OS margin
# A refusal at gates 1-4 logs and exits 0: pre-D-049 a refusal is the DESIGNED
# state, not an error, and cron must stay quiet about it.
set -euo pipefail

# Resolve the repo root from this script's own location (cron/ sits one level
# below the root) so the script works regardless of the caller cwd.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT"

mkdir -p "$REPO_ROOT/logs"
exec >> "$REPO_ROOT/logs/coordinator-cron.log" 2>&1

log() { echo "[run-coordinator] $(date -u +%FT%TZ) $*"; }

PYTHON="$REPO_ROOT/.venv-chroma/bin/python"
RATIFIED="$REPO_ROOT/run_state/d049_ratified"
PAUSE="$REPO_ROOT/run_state/pause_coordinator"
LOCK="$REPO_ROOT/run_state/.coordinator-cron.lock"
MEM_GUARD="$REPO_ROOT/experiments/exp008_qat_eval/preflight_mem.sh"
BUDGET=6        # matches the coordinator argparse default; explicit anyway
# Cycles only CALL the already-resident vLLM servers (gemma :8000,
# qwen :8001 — both serving before any cycle runs); the action menu cannot
# launch a new model, so the additional need is 0. preflight_mem_guard
# still enforces its hard-pinned 30 GiB OS margin (GB10 unified pool,
# 2026-06-08 freeze). With both servers resident, MemAvailable sits ~30
# GiB — a need>0 here would refuse every cycle by construction (caught
# live 2026-06-10 on the first soak).
MEM_NEED_GIB=0

log "start"

# Gate 1 -- single instance. A held lock means a prior cycle is still running
# (a real cycle can be long: iteration + skeptic). Skipping is normal.
exec 9>"$LOCK"
if ! flock -n 9; then
  log "SKIP: lock $LOCK is held -- a prior cycle is still running. Exit 0."
  exit 0
fi

# Gate 2 -- ratification sentinel. ONLY the human creates this file, and
# creating it IS the act of ratifying D-049. Until then every firing refuses.
if [ ! -f "$RATIFIED" ]; then
  log "REFUSE: D-049 not ratified ($RATIFIED absent). Continuous operation stays out-of-scope per CLAUDE.md; this refusal is the designed dark state. Exit 0."
  exit 0
fi

# Gate 3 -- pause file. Anyone (human or agent) may `touch` it to halt the
# runway; only the human removes it. Nothing bypasses this gate.
if [ -f "$PAUSE" ]; then
  log "REFUSE: pause file $PAUSE present -- human kill switch honored. Exit 0."
  exit 0
fi

[ -x "$PYTHON" ] || { log "FATAL: python not found at $PYTHON"; exit 1; }

# Gate 4 -- memory preflight (reads /proc/meminfo MemAvailable; NEVER
# nvidia-smi on this unified-memory box). Non-zero return = refuse/fail-closed.
# shellcheck source=../experiments/exp008_qat_eval/preflight_mem.sh
source "$MEM_GUARD"
if ! preflight_mem_guard "$MEM_NEED_GIB"; then
  log "REFUSE: preflight_mem_guard rejected need=${MEM_NEED_GIB}GiB (+30 OS margin) -- a skeptic load now could starve the OS. Exit 0."
  exit 0
fi

# Secrets seam (P0, LOOP_V1 2026-08-14): cron does NOT inherit the user's
# interactive shell env, so SEMANTIC_SCHOLAR_API_KEY was absent in every
# cron cycle — the true cause of the 24× ml_intern_zero_papers signals
# (external search blind on ~60% of iterations; the arXiv-429 theory was
# wrong). The human creates cron/secrets.env (git-ignored) with:
#   export SEMANTIC_SCHOLAR_API_KEY=...
# Absence is LOUD, never silent (rule 7).
SECRETS_ENV="$REPO_ROOT/cron/secrets.env"
# shellcheck source=/dev/null
[ -f "$SECRETS_ENV" ] && source "$SECRETS_ENV"
if [ -z "${SEMANTIC_SCHOLAR_API_KEY:-}" ]; then
  log "WARN: SEMANTIC_SCHOLAR_API_KEY absent (no $SECRETS_ENV) — external"
  log "WARN: search will be BLIND this cycle (ml_intern_zero_papers expected)."
fi

# The cycle. env -u MOCK_LLM (rule 10: a stubbed embedder makes the cycle
# meaningless); NARA_SKEPTIC=1 arms the vllm-qwen skeptic seam in the critic.
# D-059 (2026-08-14) retired NARA_PROMOTION_VOTE_ADVISORY (D-053): the vote is
# now the evidence ladder's L3->L4 rung — surfacing requires L4+, and the vote
# only runs on L3 candidates. The 06-25 flip's measured outcome (31/31 refuted
# findings promoted, zero human-dispositioned) is recorded in D-059.
log "launch: coordinator --once --execute --budget $BUDGET (NARA_SKEPTIC=1)"
rc=0
env -u MOCK_LLM NARA_SKEPTIC=1 "$PYTHON" -m orchestrator.coordinator \
  --once --execute --budget "$BUDGET" || rc=$?
log "done rc=$rc"
exit "$rc"

# ---------------------------------------------------------------------------
# !!! DO NOT ENABLE BEFORE D-049 IS RATIFIED !!!
# Installing this in crontab today is safe-but-pointless (every firing refuses
# at gate 2 and exits 0), but the operating intent is that the crontab line
# and the sentinel land TOGETHER, by the HUMAN, on ratification day:
#   crontab -e    # morning + afternoon cycles; the script manages its own log
#   0 9,15 * * * /home/decross1/projects/a_bgt_rsi/cron/run-coordinator.sh
#   touch /home/decross1/projects/a_bgt_rsi/run_state/d049_ratified
# To halt later without touching crontab:
#   touch /home/decross1/projects/a_bgt_rsi/run_state/pause_coordinator
# ---------------------------------------------------------------------------
