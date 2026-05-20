#!/usr/bin/env python3
"""
Day 3 task -- needle-in-a-haystack retrieval check for the ChromaDB
ingest pipeline.

Builds a haystack of `--haystack-tokens` filler tokens with a known fact
(the `--needle`) buried in the middle, adds the haystack to the named
ChromaDB collection in chunks, queries the collection, and writes the
top-1 hit + score to `--output` as JSON.

    python tests/needle_in_haystack.py \
        --collection day3_corpus \
        --needle "The secret access code for the retrieval test is QUARTZ-7741." \
        --haystack-tokens 8000 \
        --output logs/needle_result.json \
        --mock

--mock returns a deterministic fake hit so this scaffold is runnable and
testable before the real client exists.

DAY 3 wires in the real client: replace the real branch of
get_chroma_client() with the chromadb client created in .venv-chroma,
and create the collection with an explicit BGE-M3 embedding function.
The ChromaDB default embedder (all-MiniLM-L6-v2) is FORBIDDEN by
CLAUDE.md -- get_or_create_collection must NOT be allowed to fall back
to it. See notes/track-b-day3-4-scaffolds.md.

This file is owned by Track B (tests). It does not touch run_state/ and
never calls the vLLM endpoint.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


# --------------------------------------------------------------------------
# ChromaDB client -- stubbed at module level. Day 3 replaces the real branch.
# --------------------------------------------------------------------------
class _MockCollection:
    """Deterministic in-memory stand-in for a chromadb Collection.

    query() ranks stored documents by naive word overlap with the query,
    so a query derived from the needle reliably retrieves the needle
    chunk -- enough to exercise the test flow without an embedding model.
    """

    def __init__(self, name):
        self.name = name
        self._ids = []
        self._docs = []

    def add(self, ids, documents, **_kwargs):
        self._ids.extend(ids)
        self._docs.extend(documents)

    def query(self, query_texts, n_results=1):
        q = set(query_texts[0].lower().split())
        ranked = sorted(
            (
                (len(q & set(doc.lower().split())), idx)
                for idx, doc in enumerate(self._docs)
            ),
            key=lambda t: (t[0], -t[1]),
            reverse=True,
        )[:n_results]
        ids, docs, dists = [], [], []
        for overlap, idx in ranked:
            ids.append(self._ids[idx])
            docs.append(self._docs[idx])
            # Deterministic pseudo-distance: 0.0 == perfect overlap.
            dists.append(round(1.0 - overlap / max(len(q), 1), 4))
        return {"ids": [ids], "documents": [docs], "distances": [dists]}


class _MockClient:
    def get_or_create_collection(self, name, **_kwargs):
        return _MockCollection(name)


# DAY 3 (Track A): real client. The Chroma server runs at localhost:8001
# (host default 8000 is the vLLM endpoint). The embedder is BGE-M3 from
# local weights -- never the all-MiniLM default (CLAUDE.md rule 2). The
# collection uses cosine space so `score = 1 - distance` is a cosine
# similarity, matching the plan's >=0.85 / ~0.92 expectation.
_CHROMA_HOST = "localhost"
_CHROMA_PORT = 8001
_BGE_M3_WEIGHTS = "/mnt/models/bge-m3"


class _RealClient:
    """Wraps a chromadb HttpClient so the needle collection always uses
    the BGE-M3 embedding function and cosine space.

    main() calls get_or_create_collection(name) with no embedding
    function; this wrapper injects BGE-M3 and starts each run from a
    fresh collection (the haystack ids are regenerated per run)."""

    def __init__(self, client, ef):
        self._client = client
        self._ef = ef

    def get_or_create_collection(self, name, **_kwargs):
        try:
            self._client.delete_collection(name)
        except Exception:
            pass
        return self._client.create_collection(
            name=name,
            embedding_function=self._ef,
            configuration={"hnsw": {"space": "cosine"}},
            metadata={"embedding_function": "BGE-M3"},
        )


def get_chroma_client(mock):
    """Return a ChromaDB-compatible client.

    mock=True  -> deterministic in-memory stub (Track B / pre-Day-3).
    mock=False -> the real BGE-M3-backed client (Track A, Day 3).
    """
    if mock:
        return _MockClient()
    import chromadb
    from chromadb.utils import embedding_functions

    ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=_BGE_M3_WEIGHTS
    )
    client = chromadb.HttpClient(host=_CHROMA_HOST, port=_CHROMA_PORT)
    return _RealClient(client, ef)


# --------------------------------------------------------------------------
# Haystack construction
# --------------------------------------------------------------------------
_FILLER = (
    "Background filler material elaborates on unrelated context without "
    "bearing on the needle fact in any way whatsoever here. "
).split()


def build_haystack(needle, n_tokens, chunk_tokens):
    """Return (haystack_text, actual_token_count).

    Token counting is an approximation (whitespace split). DAY 3 should
    swap in the real tokenizer if exact parity with embedding-time
    chunking matters. The needle is inserted at a chunk boundary near the
    middle so it lands wholly inside one chunk.
    """
    words = []
    while len(words) < n_tokens:
        words.extend(_FILLER)
    words = words[:n_tokens]
    mid = (len(words) // 2 // chunk_tokens) * chunk_tokens
    words[mid:mid] = needle.split()
    return " ".join(words), len(words)


def chunk_text(text, chunk_tokens):
    words = text.split()
    return [
        " ".join(words[i : i + chunk_tokens])
        for i in range(0, len(words), chunk_tokens)
    ]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--collection", required=True,
                    help="ChromaDB collection name to add the haystack to and query.")
    ap.add_argument("--needle", required=True,
                    help="The fact buried in the haystack and searched for.")
    ap.add_argument("--haystack-tokens", type=int, required=True,
                    help="Approximate filler token count surrounding the needle.")
    ap.add_argument("--output", required=True,
                    help="Path to write the top-1 hit + score JSON.")
    ap.add_argument("--query", default=None,
                    help="Query text. Defaults to the needle; DAY 3 should pass a "
                         "paraphrased question for a genuine recall test.")
    ap.add_argument("--chunk-tokens", type=int, default=96,
                    help="Tokens per chunk when adding the haystack (default 96).")
    ap.add_argument("--mock", action="store_true",
                    help="Use the deterministic stub client (no embedding model).")
    ap.add_argument("--require-hit", action="store_true",
                    help="Exit non-zero if the needle is not in the top-1 hit.")
    args = ap.parse_args()

    query = args.query or args.needle

    haystack, actual_tokens = build_haystack(
        args.needle, args.haystack_tokens, args.chunk_tokens)
    chunks = chunk_text(haystack, args.chunk_tokens)
    ids = [f"chunk-{i}" for i in range(len(chunks))]

    client = get_chroma_client(mock=args.mock)
    collection = client.get_or_create_collection(args.collection)
    collection.add(ids=ids, documents=chunks)

    res = collection.query(query_texts=[query], n_results=1)
    hit_ids = res["ids"][0]
    if not hit_ids:
        print("FAIL: query returned no hits (empty collection?)", file=sys.stderr)
        sys.exit(1)

    distance = res["distances"][0][0]
    document = res["documents"][0][0]
    # Compare on normalized whitespace: build_haystack inserts the needle via
    # .split(), so the stored document carries it single-spaced regardless of
    # the whitespace in the raw --needle argument.
    needle_found = " ".join(args.needle.split()) in document

    result = {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "collection": args.collection,
        "needle": args.needle,
        "query": query,
        "mock": args.mock,
        "haystack_tokens_requested": args.haystack_tokens,
        "haystack_tokens_actual": actual_tokens,
        "chunk_tokens": args.chunk_tokens,
        "chunks_added": len(chunks),
        "top1": {
            "id": hit_ids[0],
            "document": document,
            "distance": distance,
            "score": round(1.0 - distance, 4),
        },
        "needle_found": needle_found,
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n")

    print(f"top-1 id   : {hit_ids[0]}")
    print(f"distance   : {distance}   score: {result['top1']['score']}")
    print(f"needle_found: {'PASS' if needle_found else 'FAIL'}")
    print(f"written    : {out}")

    if args.require_hit and not needle_found:
        print("NEEDLE NOT RETRIEVED", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
