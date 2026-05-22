#!/usr/bin/env bash
# snapshot-chroma.sh -- weekly backup of the ChromaDB vector store.
#
# tar+gzip the whole chroma_db/ directory (SQLite + HNSW segment files)
# to a snapshot directory. The store is git-ignored, so this snapshot is
# the only thing between a disk loss and re-ingesting everything. The
# archive contains the documents, metadata, and embeddings -- it is a
# full backup of the ingested data, not just the vectors.
#
# Destination is LOCAL for now. An off-host location (NAS / object
# store) is a pending decision -- when chosen, either edit SNAPSHOT_DIR
# below or set CHROMA_SNAPSHOT_DIR in the crontab line.
#
# Installed as a weekly cron job (Sunday 04:30 -- clear of the 03:00
# daily-arxiv ingest). Idempotent and self-contained.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

# Override with CHROMA_SNAPSHOT_DIR. Default: a local dir outside the repo.
SNAPSHOT_DIR="${CHROMA_SNAPSHOT_DIR:-$HOME/backups/a_bgt_rsi-chroma}"
KEEP=12   # retain this many most-recent snapshots; older ones are pruned

STORE="$REPO_ROOT/chroma_db"
[ -d "$STORE" ] || { echo "FATAL: no chroma_db store at $STORE"; exit 1; }

mkdir -p "$SNAPSHOT_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
ARCHIVE="$SNAPSHOT_DIR/chroma_db-$STAMP.tar.gz"

echo "[snapshot-chroma] $(date -u +%FT%TZ) start -> $ARCHIVE"
tar czf "$ARCHIVE" -C "$REPO_ROOT" chroma_db
echo "[snapshot-chroma] wrote $(du -h "$ARCHIVE" | cut -f1)  $ARCHIVE"

# Retention: keep the KEEP newest archives, prune the rest.
mapfile -t OLD < <(ls -1t "$SNAPSHOT_DIR"/chroma_db-*.tar.gz 2>/dev/null | tail -n +$((KEEP + 1)))
for f in "${OLD[@]}"; do
  echo "[snapshot-chroma] pruning old snapshot $f"
  rm -f "$f"
done

RETAINED="$(ls -1 "$SNAPSHOT_DIR"/chroma_db-*.tar.gz 2>/dev/null | wc -l)"
echo "[snapshot-chroma] $(date -u +%FT%TZ) done -- $RETAINED snapshot(s) retained in $SNAPSHOT_DIR"
