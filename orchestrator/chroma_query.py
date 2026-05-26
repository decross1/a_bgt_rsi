"""Chroma + BGE-M3 query helper.

Reusable across workers and orchestrator. Pattern lifted from
tests/test_papers_retrieval.py:_query_real (Day 5), generalized to
query both collections (`papers_recent` for live arXiv, `osborne_rubinstein`
for the foundational textbook layer) in a single call.

Caching: the BGE-M3 embedder is heavy to load (~3-5s). We cache a
single instance on first call. PersistentClient is also cached.

MOCK_LLM: if set, this module returns deterministic stub neighbors
matching the test fixture shape, so callers can run without the GPU.
The wrapper's MOCK_LLM-as-silent-stub footgun is mitigated by the
caller's `env -u MOCK_LLM` convention; we honor MOCK_LLM here purely
so test runs work.
"""
from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
CHROMA_PATH = REPO_ROOT / "chroma_db"
BGE_M3_WEIGHTS = os.environ.get("BGE_M3_WEIGHTS", "/mnt/models/bge-m3")

# Collection → source_layer label. Add new collections here as the
# knowledge base grows.
COLLECTIONS = {
    "papers_recent":      "live_arxiv",
    "osborne_rubinstein": "foundational",
}


_EMBEDDER = None
_CLIENT = None
_COLLECTION_CACHE: dict[str, Any] = {}


def _content_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_real_client():
    """Lazy-load the BGE-M3 embedder and Chroma client; cache them."""
    global _EMBEDDER, _CLIENT
    if _EMBEDDER is None or _CLIENT is None:
        import chromadb
        from chromadb.utils import embedding_functions
        _EMBEDDER = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=BGE_M3_WEIGHTS
        )
        _CLIENT = chromadb.PersistentClient(path=str(CHROMA_PATH))
    return _EMBEDDER, _CLIENT


def _get_collection(name: str):
    if name in _COLLECTION_CACHE:
        return _COLLECTION_CACHE[name]
    embedder, client = _load_real_client()
    coll = client.get_collection(name=name, embedding_function=embedder)
    _COLLECTION_CACHE[name] = coll
    return coll


def _mock_neighbors(text: str, k: int) -> list[dict]:
    """Deterministic stub for MOCK_LLM. Returns k synthetic neighbors
    that LOOK like real ones (right shape, plausible scores) so callers
    can exercise downstream logic. NEVER masquerade as production."""
    out = []
    for i in range(min(k, 5)):
        chunk = f"[MOCK chunk {i} for query: {text[:60]!r}]"
        out.append({
            "doc_id":       f"mock-{i:03d}",
            "content_hash": _content_hash(chunk),
            "score":        round(0.9 - i * 0.1, 4),
            "chunk_text":   chunk,
            "source_layer": "foundational" if i % 2 == 0 else "live_arxiv",
            "title":        f"Mock title {i}",
        })
    return out


def query_top_k(
    text: str,
    k: int = 10,
    collections: list[str] | None = None,
    *,
    parent_request_id: str | None = None,
) -> dict:
    """Query top-K nearest neighbors across the named collections,
    merge, sort by score, and return.

    Args:
        text: query string (a claim, hypothesis, or topic).
        k: total neighbors to return (across collections).
        collections: list of Chroma collection names. Defaults to all
            of COLLECTIONS.

    Returns:
        {
          "status": "passed" | "error",
          "result": {
            "k": int,
            "neighbors": [
              {doc_id, content_hash, score, chunk_text, source_layer, title?},
              ...
            ],
            "latency_ms": float,
          },
          "errors": [str, ...],
          "parent_request_id": str | None,
        }
    """
    if collections is None:
        collections = list(COLLECTIONS.keys())

    if os.environ.get("MOCK_LLM"):
        # Honored only because callers might leave the var set by
        # mistake; result is stubbed but the contract holds.
        return {
            "status": "passed",
            "result": {
                "k": k,
                "neighbors": _mock_neighbors(text, k),
                "latency_ms": 0.1,
                "mock": True,
            },
            "errors": [],
            "parent_request_id": parent_request_id,
        }

    t0 = time.perf_counter()
    all_neighbors: list[dict] = []
    errors: list[str] = []

    # Pull k from each collection so the merge has enough headroom;
    # the final cut to top-k happens after merging.
    per_coll_k = k
    for coll_name in collections:
        if coll_name not in COLLECTIONS:
            errors.append(f"unknown collection {coll_name!r}")
            continue
        try:
            coll = _get_collection(coll_name)
            res = coll.query(query_texts=[text], n_results=per_coll_k)
        except Exception as exc:
            errors.append(f"{coll_name}: {exc!r}")
            continue
        source_layer = COLLECTIONS[coll_name]
        metas = res.get("metadatas", [[]])[0]
        docs = res.get("documents", [[]])[0]
        dists = res.get("distances", [[]])[0]
        for meta, doc, dist in zip(metas, docs, dists):
            meta = meta or {}
            # doc_id: prefer arxiv_id; for textbook chunks, build one
            # from book + chunk_index.
            arxiv_id = meta.get("arxiv_id")
            book = meta.get("book")
            chunk_index = meta.get("chunk_index")
            if arxiv_id:
                doc_id = str(arxiv_id)
            elif book is not None and chunk_index is not None:
                doc_id = f"{book}-chunk-{chunk_index}"
            else:
                # Fallback — content-addressable
                doc_id = _content_hash(doc or "")[:18]
            title = meta.get("title") or meta.get("chapter_title")
            chunk_text = doc or ""
            score = round(1.0 - float(dist), 4) if dist is not None else 0.0
            all_neighbors.append({
                "doc_id":       doc_id,
                "content_hash": _content_hash(chunk_text),
                "score":        score,
                "chunk_text":   chunk_text,
                "source_layer": source_layer,
                "title":        title,
            })

    all_neighbors.sort(key=lambda n: n["score"], reverse=True)
    neighbors = all_neighbors[:k]

    latency_ms = round((time.perf_counter() - t0) * 1000.0, 3)
    status = "passed" if not errors else ("passed" if neighbors else "error")
    return {
        "status": status,
        "result": {
            "k": k,
            "neighbors": neighbors,
            "latency_ms": latency_ms,
        },
        "errors": errors,
        "parent_request_id": parent_request_id,
    }


if __name__ == "__main__":
    # Smoke test: `env -u MOCK_LLM python -m orchestrator.chroma_query`
    import json
    out = query_top_k("Tit-for-Tat dominance in repeated Prisoner's Dilemma", k=5)
    print(json.dumps(out, indent=2, default=str))
