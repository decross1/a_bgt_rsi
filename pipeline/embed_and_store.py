#!/usr/bin/env python3
"""
Day 5 arXiv pipeline -- stage 2 of 2: embed abstracts and store.

Reads the JSONL produced by pipeline/arxiv_scraper.py, embeds each paper's
*abstract* (not the full paper) with BGE-M3, and inserts the vectors into a
named ChromaDB collection. New papers are de-duplicated against whatever the
collection already holds, keyed on arxiv_id, so the script is safe to run
daily from cron.

Usage:
    python3 pipeline/embed_and_store.py \\
        --input /tmp/papers_day5.jsonl \\
        --collection papers_recent \\
        --bge-m3-weights /mnt/models/bge-m3

Pins (see CLAUDE.md / START_HERE.md):
  - Embedding model is BGE-M3 -- NOT ChromaDB's default all-MiniLM-L6-v2.
  - Embeddings are computed here and passed to ChromaDB explicitly, so the
    collection never silently falls back to a default embedding function.

Testing: set MOCK_LLM=1 to swap the real BGE-M3 load for a deterministic
stub embedder. Track A owns the real model weights and the live ChromaDB;
this module imports neither at import time -- both are loaded lazily so the
file can be unit-tested without GPU or model artifacts present.
"""
import argparse
import hashlib
import json
import logging
import os
import sys

log = logging.getLogger("embed_and_store")

# BGE-M3 dense embedding dimensionality. The mock embedder matches it so
# stubbed runs exercise the same ChromaDB code paths as real ones.
_BGE_M3_DIM = 1024


class _MockEmbedder:
    """Deterministic stand-in for BGE-M3 used when MOCK_LLM is set.

    Maps text -> a fixed _BGE_M3_DIM vector by hashing. Not semantically
    meaningful; it only lets the storage path run without the real model.
    """

    name = "BGE-M3"  # reported identically so collection metadata is honest

    def encode(self, texts):
        vectors = []
        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            # Tile the 32-byte digest out to _BGE_M3_DIM floats in [0, 1).
            raw = (digest * ((_BGE_M3_DIM // len(digest)) + 1))[:_BGE_M3_DIM]
            vectors.append([b / 255.0 for b in raw])
        return vectors


class _BGEM3Embedder:
    """Real BGE-M3 dense-vector embedder, loaded lazily from local weights."""

    name = "BGE-M3"

    def __init__(self, weights_path):
        # Imported lazily: Track A owns these deps; tests never reach here.
        from FlagEmbedding import BGEM3FlagModel

        self._model = BGEM3FlagModel(weights_path, use_fp16=True)

    def encode(self, texts):
        out = self._model.encode(texts, batch_size=16, max_length=8192)
        # BGEM3FlagModel returns {'dense_vecs': ndarray, ...}.
        return [vec.tolist() for vec in out["dense_vecs"]]


def get_embedder(weights_path):
    """Return a BGE-M3 embedder, or the deterministic stub under MOCK_LLM."""
    if os.environ.get("MOCK_LLM"):
        log.warning("MOCK_LLM set -- using the deterministic stub embedder")
        return _MockEmbedder()
    return _BGEM3Embedder(weights_path)


def load_papers(input_path):
    """Load papers from a JSONL file, skipping blank lines."""
    papers = []
    with open(input_path, "r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                papers.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{input_path}:{lineno} is not valid JSON: {exc}") from exc
    log.info("loaded %d papers from %s", len(papers), input_path)
    return papers


def dedupe(papers, existing_ids):
    """Drop papers already stored, lacking an id, or lacking an abstract.

    De-dup key is arxiv_id. Dropped, each into its own counter:
    within-batch and against-collection duplicates; papers carrying no
    arxiv_id; and papers whose abstract is missing/empty (the abstract is
    what we embed). Returns (kept, n_dup, n_no_id, n_no_abstract).
    """
    kept = []
    seen = set(existing_ids)
    n_dup = 0
    n_no_id = 0
    n_no_abstract = 0
    for paper in papers:
        arxiv_id = paper.get("arxiv_id")
        if not arxiv_id:
            n_no_id += 1
            continue
        if arxiv_id in seen:
            n_dup += 1
            continue
        abstract = (paper.get("abstract") or "").strip()
        if not abstract:
            n_no_abstract += 1
            continue
        seen.add(arxiv_id)
        kept.append(paper)
    log.info("dedupe: %d new, %d duplicates, %d without an id, "
             "%d without an abstract",
             len(kept), n_dup, n_no_id, n_no_abstract)
    return kept, n_dup, n_no_id, n_no_abstract


def get_collection(db_path, collection_name):
    """Open (or create) the ChromaDB collection, tagged with the BGE-M3 pin.

    ChromaDB is imported lazily so this module stays unit-testable without
    it installed. Track A owns the live store at chroma_db/.
    """
    import chromadb

    client = chromadb.PersistentClient(path=db_path)
    return client.get_or_create_collection(
        name=collection_name,
        # Embeddings are supplied explicitly on add(); the metadata records
        # the pin so validation can confirm BGE-M3 (not all-MiniLM-L6-v2).
        metadata={"embedding_model": "BGE-M3", "hnsw:space": "cosine"},
    )


def store(collection, papers, embedder):
    """Embed each paper's abstract and add it to the collection."""
    if not papers:
        log.info("nothing new to store")
        return 0
    abstracts = [p["abstract"] for p in papers]
    embeddings = embedder.encode(abstracts)
    metadatas = [
        {
            "title": p.get("title", ""),
            "authors": ", ".join(p.get("authors") or []),
            "arxiv_id": p["arxiv_id"],
            "semantic_scholar_id": p.get("semantic_scholar_id") or "",
            "citation_count": p.get("citation_count", 0),
            "category": p.get("category", ""),
            "publication_date": p.get("publication_date") or "",
        }
        for p in papers
    ]
    collection.add(
        ids=[p["arxiv_id"] for p in papers],
        documents=abstracts,
        embeddings=embeddings,
        metadatas=metadatas,
    )
    log.info("stored %d papers in collection '%s'", len(papers), collection.name)
    return len(papers)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", required=True,
                        help="JSONL produced by pipeline/arxiv_scraper.py")
    parser.add_argument("--collection", required=True,
                        help="ChromaDB collection name, e.g. papers_recent")
    parser.add_argument("--bge-m3-weights", required=True,
                        help="local path to the BGE-M3 weights")
    parser.add_argument("--db-path", default="chroma_db",
                        help="ChromaDB persistent-store directory (default: chroma_db)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    papers = load_papers(args.input)
    embedder = get_embedder(args.bge_m3_weights)
    collection = get_collection(args.db_path, args.collection)

    existing_ids = collection.get()["ids"]
    kept, _, _, _ = dedupe(papers, existing_ids)
    n_stored = store(collection, kept, embedder)

    log.info("done: %d papers added, collection now holds %d",
             n_stored, collection.count())
    return 0


if __name__ == "__main__":
    sys.exit(main())
