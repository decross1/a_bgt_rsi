#!/usr/bin/env bash
# run-critic-eval.sh -- Day 9 (Track C stretch) artifact. NOT yet
# installed in crontab. Same human-step discipline as cron/daily-arxiv.sh,
# cron/sla-sweep.sh, cron/claims-weekly.sh, cron/snapshot-chroma.sh: the
# script is committed; a human installs it via crontab when the
# upstream worker (Day-39 W2-01) lands.
#
# Runs the critic agent against the 20 Day-39 fixtures (the JSONL view
# at tests/fixtures/critic_eval_inputs.jsonl, derived from the per-file
# fixtures under experiments/fixtures/critic_hypotheses/) and writes
# the critic responses to a timestamped output dir under logs/critic_eval/.
# Track A's Day-39 eval consumes the output dir to score the
# substantive-critique rate (target: critic flags >=80% of the 19
# flawed fixtures with a substantively different critique).
#
# This wrapper assumes the Day-39 critic worker lands at
# workers/critic.py with the CLI:
#   workers/critic.py --input <jsonl> --output-dir <dir>
# If the worker is not yet present the wrapper exits non-zero with a
# clear message rather than silently no-op'ing.
#
# Intended schedule once Day 39 installs it (02:30 local, before the
# daily-arxiv cron at 03:00):
#   30 2 * * *  /abs/path/to/repo/cron/run-critic-eval.sh >> /abs/path/to/repo/logs/cron-critic-eval.log 2>&1
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT"

PYTHON="$REPO_ROOT/.venv-chroma/bin/python"
CRITIC_WORKER="$REPO_ROOT/workers/critic.py"
INPUT_JSONL="$REPO_ROOT/tests/fixtures/critic_eval_inputs.jsonl"
OUT_ROOT="$REPO_ROOT/logs/critic_eval"
OUT_DIR="$OUT_ROOT/$(date -u +%Y%m%dT%H%M%SZ)"

[ -x "$PYTHON" ]         || { echo "FATAL: python not found at $PYTHON"; exit 1; }
[ -f "$CRITIC_WORKER" ]  || { echo "FATAL: workers/critic.py not present yet (Day-39 W2-01 deliverable). Aborting -- this is by design until the worker lands."; exit 2; }
[ -f "$INPUT_JSONL" ]    || { echo "FATAL: critic input JSONL not at $INPUT_JSONL"; exit 1; }

mkdir -p "$OUT_DIR"

echo "[run-critic-eval] $(date -u +%FT%TZ) start"
echo "[run-critic-eval] input:  $INPUT_JSONL"
echo "[run-critic-eval] output: $OUT_DIR"

# Critic agent calls the real LLM. Strip MOCK_LLM so the stub embedder
# does not silently take over (see memory/mock-llm-track-a-env).
env -u MOCK_LLM "$PYTHON" "$CRITIC_WORKER" \
  --input "$INPUT_JSONL" \
  --output-dir "$OUT_DIR"

echo "[run-critic-eval] $(date -u +%FT%TZ) done"
