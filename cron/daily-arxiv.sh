#!/usr/bin/env bash
# daily-arxiv.sh -- Day 5 artifact. NOT yet installed in crontab; Day 6
# enables it.
#
# Pulls the last 24 hours of cs.MA / cs.GT / econ.TH abstracts from the
# arXiv API, embeds them with BGE-M3, and appends to the `papers_recent`
# ChromaDB collection. Idempotent: pipeline/embed_and_store.py
# deduplicates on arxiv_id, so a same-day re-run adds nothing.
#
# Source: arXiv API (DECISIONS.md D-027) -- no API key required.
#
# Intended schedule once Day 6 installs it (03:00 local):
#   0 3 * * *  /abs/path/to/repo/cron/daily-arxiv.sh >> /abs/path/to/repo/logs/cron-arxiv.log 2>&1
set -euo pipefail

# Resolve the repo root from this script's own location (cron/ sits one
# level below the root) so the script works regardless of the caller cwd.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT"

PYTHON="$REPO_ROOT/.venv-chroma/bin/python"
BGE_M3_WEIGHTS=/mnt/models/bge-m3
PAPERS_JSONL="$(mktemp /tmp/papers_daily_XXXXXX.jsonl)"
trap 'rm -f "$PAPERS_JSONL"' EXIT

[ -x "$PYTHON" ]            || { echo "FATAL: python not found at $PYTHON"; exit 1; }
[ -d "$BGE_M3_WEIGHTS" ]    || { echo "FATAL: BGE-M3 weights not at $BGE_M3_WEIGHTS"; exit 1; }

echo "[daily-arxiv] $(date -u +%FT%TZ) start"

# Track A uses the real BGE-M3 model. Strip MOCK_LLM in case it is set in
# the environment -- it is a Track B/C testing flag and would silently
# swap in the deterministic stub embedder.
env -u MOCK_LLM "$PYTHON" pipeline/arxiv_scraper.py \
  --categories cs.MA,cs.GT,econ.TH \
  --since-days 1 \
  --output "$PAPERS_JSONL"

env -u MOCK_LLM "$PYTHON" pipeline/embed_and_store.py \
  --input "$PAPERS_JSONL" \
  --collection papers_recent \
  --bge-m3-weights "$BGE_M3_WEIGHTS" \
  --db-path "$REPO_ROOT/chroma_db"

echo "[daily-arxiv] $(date -u +%FT%TZ) done"
