#!/usr/bin/env bash
# One headless meta-oracle pass (docs/META_ORACLE_DAILY_LOOP.md): plan | code | retro.
# plan and code exit without a model call when nothing in the mailbox awaits review.
set -euo pipefail
MODE=${1:?usage: meta_oracle_run.sh plan|code|retro}
case "$MODE" in plan|code|retro) ;; *) echo "unknown mode: $MODE" >&2; exit 2 ;; esac
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
PY=.venv-chroma/bin/python
DAY=$(TZ=America/Los_Angeles date +%F)
LOG_DIR=logs/meta_oracle
mkdir -p "$LOG_DIR"

log_row() {  # status, actual
  "$PY" - "$MODE" "$DAY" "$1" "$2" <<'EOF'
import json, sys
from datetime import datetime, timezone
mode, day, status, actual = sys.argv[1:]
row = {"timestamp": datetime.now(timezone.utc).isoformat(), "task_id": f"meta-oracle:{mode}:{day}",
       "agent": "claude-meta-oracle", "status": status, "observable_actual": actual,
       "observable_expected": "reviews posted for every item awaiting review", "duration_ms": 0}
open("run_state/week1.run.jsonl", "a").write(json.dumps(row) + "\n")
EOF
}

if [ "$MODE" != retro ]; then
  if ! PENDING=$("$PY" - "$MODE" <<'EOF'
import sys
from orchestrator import oracle_mailbox as mb
mode, rows = sys.argv[1], mb.read()
reviewed = {r["in_reply_to"] for r in rows if r["kind"] == "review"}
title = lambda r: str(r["body"].get("title", ""))
if mode == "plan":
    want = [r for r in rows if r["kind"] == "note" and r["actor"] == "oracle" and title(r).startswith("PLAN READY")]
    want += [e["item"] for e in mb.fold(rows).values() if e["state"] == "open"]
else:
    want = [r for r in rows if r["kind"] == "note" and r["actor"] == "oracle" and title(r).startswith("READY FOR REVIEW")]
    want += [r for r in rows if r["kind"] == "receipt" and r["body"].get("state") == "validated"]
print(len([r for r in want if r["msg_id"] not in reviewed]))
EOF
  ); then
    log_row failed "pending-review check failed (mailbox unreadable?)"
    exit 1
  fi
  if [ "$PENDING" = 0 ]; then
    exit 0  # nothing awaits review; no model call and no log row
  fi
fi

SCRATCH=$(mktemp -d)
trap 'rm -rf "$SCRATCH"' EXIT
export SCRATCH
START=$(date +%s)
# The prompt goes on stdin because --add-dir takes every following argument. The API key
# is dropped so every run, timer or interactive, uses the Claude Max login (D-061).
if echo "Mode: $MODE. Date (America/Los_Angeles): $DAY. Scratch directory: $SCRATCH. Run this pass now." \
    | env -u ANTHROPIC_API_KEY claude -p --model claude-opus-5-5 --permission-mode auto \
      --append-system-prompt-file agent/prompts/meta_oracle.md \
      --add-dir /home/decross1/projects/oracle_system "$SCRATCH" \
      > "$LOG_DIR/$DAY-$MODE-$START.log" 2>&1; then
  log_row completed "mode $MODE finished in $(( $(date +%s) - START ))s; transcript $LOG_DIR/$DAY-$MODE-$START.log"
else
  log_row failed "claude exited $?; see $LOG_DIR/$DAY-$MODE-$START.log"
  exit 1
fi
