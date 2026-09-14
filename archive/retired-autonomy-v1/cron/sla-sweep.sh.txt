#!/usr/bin/env bash
# sla-sweep.sh -- Day 7 artifact. NOT yet installed in crontab.
#
# Runs the two janitorial sweepers that operationalize the agent-autonomy
# SLA framework (agent/autonomy.md §2) and the claim/lock protocol
# (agent/collision_protocol.md §1.3, §7):
#
#   1. tools/gate_sla_check.py -- soft-gate auto-clear (4h) and hard-gate
#      escalation (48h). Writes no_objection entries to attestations.jsonl
#      and hard_gate_sla_expired entries to escalations.jsonl.
#   2. tools/claims_check.py --gc -- identifies stale claims whose
#      expires_at passed > 24h ago. Reports only; archival is Track-A only.
#
# Both tools are read-mostly: gate_sla_check.py appends to shared JSONL
# logs (which Track C is allowed to append to); claims_check.py --gc is
# read-only. Neither mutates run_state/week1.state.json.
#
# Intended schedule (every 15 minutes -- matches the SLA cadence assumed
# by gate_sla_check.py's docstring):
#   */15 * * * *  /abs/path/to/repo/cron/sla-sweep.sh >> /home/decross1/cron-sla-sweep.log 2>&1
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT"

# Use .venv-chroma -- it has the deps the tools need (pyyaml for
# claims_check ownership validation; stdlib-only for gate_sla_check, but
# we use one interpreter for both). .venv lacks pyyaml.
PYTHON="$REPO_ROOT/.venv-chroma/bin/python"
[ -x "$PYTHON" ] || { echo "FATAL: python not found at $PYTHON"; exit 1; }

echo "[sla-sweep] $(date -u +%FT%TZ) start"

echo "[sla-sweep] gate_sla_check.py"
"$PYTHON" tools/gate_sla_check.py

echo "[sla-sweep] claims_check.py --gc"
"$PYTHON" tools/claims_check.py --gc

echo "[sla-sweep] $(date -u +%FT%TZ) done"
