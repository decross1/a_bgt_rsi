#!/usr/bin/env bash
# daily-arxiv.sh -- receipt-bound daily literature ingestion.
#
# Fetches a three-day overlapping cs.MA / cs.GT / econ.TH window, then embeds
# fresh fetched inputs with BGE-M3. Every invocation gets durable started and
# terminal receipts; a failed fetch keeps the last-success input as provenance
# only. The embedder deduplicates arxiv_id on repeated successful windows.
#
# Source: arXiv OAI-PMH category sets with the legacy arXiv query API as a
# complete-run fallback (DECISIONS.md D-027) -- no API key required. The
# scraper serializes requests at arXiv's documented one-per-three-second cap.
#
# The existing 03:00 UTC crontab entry remains the only scheduler.
set -euo pipefail

# Resolve the repo root from this script's own location (cron/ sits one
# level below the root) so the script works regardless of the caller cwd.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT"

PYTHON="$REPO_ROOT/.venv-chroma/bin/python"
BGE_M3_WEIGHTS=/mnt/models/bge-m3

[ -x "$PYTHON" ]            || { echo "FATAL: python not found at $PYTHON"; exit 1; }
[ -d "$BGE_M3_WEIGHTS" ]    || { echo "FATAL: BGE-M3 weights not at $BGE_M3_WEIGHTS"; exit 1; }

echo "[daily-arxiv] $(date -u +%FT%TZ) start"

# The job unsets MOCK_LLM in both subprocesses and records the actual arXiv
# interface, source-sidecar SHA, retry codes, fetched JSONL SHA/cache, and
# whether embedding was actually attempted.
env -u MOCK_LLM "$PYTHON" -m pipeline.daily_arxiv_job --run

echo "[daily-arxiv] $(date -u +%FT%TZ) done"
