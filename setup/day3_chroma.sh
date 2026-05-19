#!/usr/bin/env bash
# day3_block2_chroma_install — pre-staged Day 3 setup (queued by day_2 end-of-day).
#
# Stands up ChromaDB with the BGE-M3 embedding function. ChromaDB's
# default embedder (all-MiniLM-L6-v2) is FORBIDDEN by CLAUDE.md inviolate
# rule 2 — it collapses to 0.4–0.6 retrieval accuracy on dense math text.
# BGE-M3 weights are pre-staged at /mnt/models/bge-m3 (confirmed present
# at day_2 end-of-day).
#
# Run on Day 3 Block 2, after day3_block1_reading. Mirrors the
# `day3_block2_chroma_install` task command in plan.yaml.
set -uo pipefail
cd /home/decross1/projects/a_bgt_rsi || exit 1

BGE_M3_WEIGHTS=/mnt/models/bge-m3
[ -d "$BGE_M3_WEIGHTS" ] || { echo "FATAL: BGE-M3 weights not at $BGE_M3_WEIGHTS"; exit 1; }

# Fresh, isolated venv for the retrieval layer (separate from .venv).
python3 -m venv .venv-chroma
# shellcheck disable=SC1091
source .venv-chroma/bin/activate
pip install chromadb            # Day 3: pin to the current stable version

# Start the Chroma server against the repo-local store.
chroma run --path ./chroma_db &
sleep 5

# Initialise a 10-doc test collection with the BGE-M3 embedding function.
# NOTE: scripts/chroma_init_with_bge_m3.py is authored on Day 3 (Track A,
# or drafted by Track C) — it must create the collection with an explicit
# BGE-M3 embedding function, never the all-MiniLM-L6-v2 default.
python3 scripts/chroma_init_with_bge_m3.py \
  --bge-m3-weights "$BGE_M3_WEIGHTS" \
  --collection-name day3_test

# Validation (day3_block2_chroma_install, hard checkpoint):
#  - chroma server listening on its default port
#  - collection metadata embedding_function == "BGE-M3" (NOT all-MiniLM-L6-v2)
#  - test collection count == 10
