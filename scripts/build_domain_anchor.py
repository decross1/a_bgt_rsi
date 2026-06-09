#!/usr/bin/env python3
"""build_domain_anchor.py — offline builder for run_state/domain_anchor.json.

Derives the GT-domain anchor: the renormalized mean of the L2-normalized
stored chunk embeddings across every FOUNDATIONAL collection. The
foundational list is derived from orchestrator.chroma_query.COLLECTIONS
where the value == "foundational" — NEVER a hand-maintained second list.
NO re-embedding happens here: the vectors are already stored in Chroma
and are fetched with collection.get(include=["embeddings"]) in batches.

Run SERIALLY by the integrator against the real store (a few seconds):

    ./.venv-chroma/bin/python scripts/build_domain_anchor.py

Output: run_state/domain_anchor.json
  {"model": "bge-m3", "dim": 1024, "vector": [...],
   "collections": {name: chunk_count, ...},
   "built_at": iso-utc, "builder_commit": git-short-sha}

Also prints each collection-centroid's cosine to the global centroid —
a collection far from the rest flags corpus heterogeneity worth a look
before the anchor is trusted for calibration (P-009).
"""
from __future__ import annotations

import argparse
import datetime
import json
import math
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

DEFAULT_OUT = REPO_ROOT / "run_state" / "domain_anchor.json"


def _normalize(vec: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in vec))
    if n == 0.0:
        raise ValueError("zero-norm vector")
    return [x / n for x in vec]


def centroid(vectors: list[list[float]]) -> list[float]:
    """Pure: L2-normalize each vector, mean them, renormalize the mean.
    Raises ValueError on empty input, dim mismatch, or zero-norm result."""
    if not vectors:
        raise ValueError("centroid: no vectors")
    dim = len(vectors[0])
    acc = [0.0] * dim
    for v in vectors:
        if len(v) != dim:
            raise ValueError(f"centroid: dim mismatch ({len(v)} != {dim})")
        nv = _normalize([float(x) for x in v])
        for i, x in enumerate(nv):
            acc[i] += x
    return _normalize(acc)


def _cosine(a: list[float], b: list[float]) -> float:
    na, nb = _normalize(a), _normalize(b)
    return sum(x * y for x, y in zip(na, nb))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Build the GT-domain anchor centroid from the stored "
                    "foundational-collection embeddings (no re-embedding).")
    ap.add_argument("--out", default=str(DEFAULT_OUT),
                    help=f"output path (default {DEFAULT_OUT})")
    ap.add_argument("--batch", type=int, default=500,
                    help="collection.get() batch size (default 500)")
    args = ap.parse_args(argv)

    import chromadb  # heavy import deferred so --help stays instant
    from orchestrator.chroma_query import CHROMA_PATH, COLLECTIONS

    names = sorted(n for n, layer in COLLECTIONS.items() if layer == "foundational")
    if not names:
        print("ERROR: no foundational collections in COLLECTIONS", file=sys.stderr)
        return 1

    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    global_acc: list[float] | None = None
    coll_centroids: dict[str, list[float]] = {}
    counts: dict[str, int] = {}

    for name in names:
        coll = client.get_collection(name=name)
        coll_acc: list[float] | None = None
        n_chunks = 0
        offset = 0
        while True:
            res = coll.get(include=["embeddings"], limit=args.batch, offset=offset)
            embs = res.get("embeddings")
            if embs is None or len(embs) == 0:
                break
            for emb in embs:
                nv = _normalize([float(x) for x in emb])
                if coll_acc is None:
                    coll_acc = [0.0] * len(nv)
                    if global_acc is None:
                        global_acc = [0.0] * len(nv)
                for i, x in enumerate(nv):
                    coll_acc[i] += x
                    global_acc[i] += x
                n_chunks += 1
            offset += len(embs)
        if coll_acc is None or n_chunks == 0:
            print(f"WARN: collection {name!r} has no embeddings; skipped",
                  file=sys.stderr)
            continue
        coll_centroids[name] = _normalize(coll_acc)
        counts[name] = n_chunks

    if global_acc is None or not counts:
        print("ERROR: no embeddings found in any foundational collection",
              file=sys.stderr)
        return 1
    global_centroid = _normalize(global_acc)

    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except Exception:
        commit = "unknown"

    print(f"global centroid: dim={len(global_centroid)} "
          f"chunks={sum(counts.values())} collections={len(counts)}")
    print("per-collection centroid cosine to global (heterogeneity sanity):")
    for name in sorted(counts):
        cos = _cosine(coll_centroids[name], global_centroid)
        print(f"  {name:30s} chunks={counts[name]:6d} cos_to_global={cos:.4f}")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "model": "bge-m3",
        "dim": len(global_centroid),
        "vector": global_centroid,
        "collections": counts,
        "built_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "builder_commit": commit,
    }), encoding="utf-8")
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
