#!/usr/bin/env python3
"""chroma_init_with_bge_m3.py — Day 3 (day3_block2_chroma_install).

Stands up a ChromaDB collection backed by the BGE-M3 embedding function
and populates it with a 10-document test set.

CLAUDE.md inviolate rule 2: the embedder is BGE-M3, never ChromaDB's
default all-MiniLM-L6-v2 (which collapses to 0.4-0.6 retrieval accuracy
on dense math text). The collection metadata records
`embedding_function: "BGE-M3"` so the hard-checkpoint validation can
confirm the embedder without runtime introspection.

Connects to a running `chroma run` server over HTTP. Chroma's own
default port is 8000; on this host 8000 is the vLLM endpoint
(LOCAL_LLM_BASE_URL), so the server and this script default to 8001.
"""
import argparse
import sys

import chromadb
from chromadb.utils import embedding_functions

# Ten short game-theory facts — enough to confirm the embedder runs and
# the collection populates. Not a corpus; the textbook ingest is the
# next task.
TEST_DOCS = [
    "Nash equilibrium is a strategy profile from which no player gains by deviating unilaterally.",
    "A subgame perfect equilibrium induces a Nash equilibrium in every subgame.",
    "The one-deviation principle holds in finite-horizon games of perfect information.",
    "An evolutionarily stable strategy resists invasion by any sufficiently rare mutant.",
    "In the repeated prisoner's dilemma, reciprocity can sustain cooperation at a high discount factor.",
    "The folk theorem characterises the equilibrium payoff set of infinitely repeated games.",
    "A mixed strategy is a probability distribution over a player's pure actions.",
    "Backward induction solves finite perfect-information games from the terminal nodes upward.",
    "A dominant strategy is at least as good as any alternative regardless of opponents' play.",
    "Correlated equilibrium generalises Nash equilibrium via a public randomisation device.",
]

DEFAULT_PORT = 8001  # Chroma default 8000 is occupied by the vLLM endpoint.


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bge-m3-weights", required=True,
                    help="path to the local BGE-M3 weights directory")
    ap.add_argument("--collection-name", required=True)
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = ap.parse_args()

    # BGE-M3 loaded from the local weights — sentence-transformers layout.
    ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=args.bge_m3_weights
    )

    client = chromadb.HttpClient(host=args.host, port=args.port)

    # Idempotent: drop any stale collection from a prior run.
    try:
        client.delete_collection(args.collection_name)
    except Exception:
        pass

    coll = client.create_collection(
        name=args.collection_name,
        embedding_function=ef,
        metadata={"embedding_function": "BGE-M3"},
    )
    coll.add(
        documents=TEST_DOCS,
        ids=[f"doc-{i}" for i in range(len(TEST_DOCS))],
    )

    count = coll.count()
    ef_meta = (coll.metadata or {}).get("embedding_function")
    print(f"collection={args.collection_name} count={count} "
          f"embedding_function={ef_meta}")

    ok = True
    if count != len(TEST_DOCS):
        print(f"FATAL: expected {len(TEST_DOCS)} docs, got {count}", file=sys.stderr)
        ok = False
    if ef_meta != "BGE-M3":
        print(f"FATAL: embedding_function metadata is {ef_meta!r}, not 'BGE-M3'",
              file=sys.stderr)
        ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
