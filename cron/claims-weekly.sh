#!/usr/bin/env bash
# claims-weekly.sh -- Day 7 artifact. NOT yet installed in crontab.
#
# Runs `tools/claims_check.py --weekly-summary` once a week and appends
# the report to notes/weekly-claims-<UTC-date>.md. The summary is the
# claim-protocol-cleanliness figures the weekly retrospective consumes
# (agent/collision_protocol.md §3): overlapping_claims_now,
# expired_unreleased_total, active_now. These figures gate the
# concurrent-dispatch phase unlocks.
#
# Read-only against the repo state -- no JSONL writes, no state mutation.
# Output lands in notes/ (shared zone; any agent may write).
#
# Intended schedule (Sunday 04:00 UTC -- same slot family as
# snapshot-chroma at Sunday 04:30, clear of the 03:00 daily-arxiv ingest):
#   0 4 * * 0  /abs/path/to/repo/cron/claims-weekly.sh >> /home/decross1/cron-sla-sweep.log 2>&1
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT"

PYTHON="$REPO_ROOT/.venv-chroma/bin/python"
[ -x "$PYTHON" ] || { echo "FATAL: python not found at $PYTHON"; exit 1; }

STAMP="$(date -u +%Y%m%d)"
OUT="$REPO_ROOT/notes/weekly-claims-$STAMP.md"

echo "[claims-weekly] $(date -u +%FT%TZ) start -> $OUT"

{
  echo "# Weekly claims summary -- $(date -u +%FT%TZ)"
  echo
  echo '```'
  "$PYTHON" tools/claims_check.py --weekly-summary
  echo '```'
  echo
} >> "$OUT"

echo "[claims-weekly] $(date -u +%FT%TZ) done"
