#!/usr/bin/env python3
"""
Day 5 task day5_block2_retrieval_test -- retrieval sanity check for the
`papers_recent` ChromaDB collection.

Queries `papers_recent` for the top-k most similar papers to --query,
measures query latency, and writes the ranked results + latency to
--output as JSON. The literature layer this exercises feeds Day 7's
experiment context, so this is a real go/no-go check, not a smoke test.

    python3 tests/test_papers_retrieval.py \
        --query "LLM agents in repeated games" \
        --top-k 3 \
        --output bench/day5_retrieval.json

MOCK MODE: with MOCK_LLM=1 set, the query is served by a deterministic
in-memory stub of 3 fake papers (ranked by word overlap) -- so this
scaffold is runnable and testable before `papers_recent` exists. The
stub never calls an embedding model or an LLM endpoint.

Drafted by Track B on Day 3. The real (non-mock) branch is wired by
Day 5 once pipeline/embed_and_store.py has built `papers_recent`; every
real-branch assumption is tagged DAY5-CONTRACT. See
notes/track-b-day5-6-scaffolds.md.

Plan validation (day5_block2_retrieval_test): latency_ms < 1000 (gated
here via --max-latency-ms); >=1 of top-k genuinely relevant (human
review of the written JSON -- not gated by this script).
"""
import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

COLLECTION = "papers_recent"

# --------------------------------------------------------------------------
# Mock corpus -- 3 fake papers, used only when MOCK_LLM=1. Fields mirror
# what pipeline/embed_and_store.py stores per paper (plan.yaml
# day5_block2_pipeline_implementation): title, abstract, authors,
# arxiv_id, semantic_scholar_id, citation_count.
# --------------------------------------------------------------------------
_MOCK_PAPERS = [
    {
        "arxiv_id": "2402.10001",
        "semantic_scholar_id": "ss-mock-0001",
        "title": "Cooperation and Defection: LLM Agents in Repeated Games",
        "abstract": ("We study large language model agents playing repeated "
                     "games such as the iterated prisoner's dilemma. Agents "
                     "negotiate, retaliate, and form tacit cooperation over "
                     "many rounds. We measure how prompt framing shifts the "
                     "equilibrium between cooperation and defection."),
        "authors": ["A. Researcher", "B. Scholar"],
        "citation_count": 42,
    },
    {
        "arxiv_id": "2402.10002",
        "semantic_scholar_id": "ss-mock-0002",
        "title": "Mechanism Design for Multi-Agent Language Model Markets",
        "abstract": ("We design auction and matching mechanisms for "
                     "populations of language model agents. The focus is "
                     "incentive compatibility and welfare; repeated "
                     "interaction and reputation are treated only briefly."),
        "authors": ["C. Economist"],
        "citation_count": 11,
    },
    {
        "arxiv_id": "2402.10003",
        "semantic_scholar_id": "ss-mock-0003",
        "title": "A Survey of Transformer Pretraining Objectives",
        "abstract": ("We survey pretraining objectives for transformer "
                     "language models, including masked and autoregressive "
                     "losses. This work concerns pretraining, not agents or "
                     "game-theoretic interaction."),
        "authors": ["D. Surveyor", "E. Author"],
        "citation_count": 130,
    },
]


def _words(text):
    """Lower-cased word tokens, punctuation stripped -- so 'agents.' and
    'agents' match. Naive on purpose: this is a deterministic stand-in for
    BGE-M3 similarity, not a real ranker."""
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _query_mock(query, top_k):
    """Rank the mock corpus by naive word overlap with the query. Returns
    (ranked, latency_ms) where ranked is a list of (paper, distance) --
    distance 0.0 == perfect overlap, so a game-theory query surfaces the
    on-topic papers first."""
    t0 = time.perf_counter()
    q = _words(query)
    scored = []
    for paper in _MOCK_PAPERS:
        text = _words(paper["title"] + " " + paper["abstract"])
        overlap = len(q & text)
        distance = round(1.0 - overlap / max(len(q), 1), 4)
        scored.append((paper, distance))
    scored.sort(key=lambda t: t[1])
    latency_ms = round((time.perf_counter() - t0) * 1000.0, 3)
    return scored[:top_k], latency_ms


def _query_real(query, top_k, chroma_path, bge_m3_weights):
    """Query the real `papers_recent` collection. Wired on Day 5.

    Returns (ranked, latency_ms). The BGE-M3 model load and ChromaDB
    client open are one-time setup and are deliberately NOT counted in
    latency_ms -- the plan's sub-second target is QUERY latency (embed the
    query string + ANN search), not cold-start model initialization; in
    production the model is resident and only the query cost recurs.

    DAY5-CONTRACT (resolved Day 5): `papers_recent` is created by
    pipeline/embed_and_store.py, whose _BGEM3Embedder wraps the SAME
    chromadb SentenceTransformerEmbeddingFunction over /mnt/models/bge-m3
    used here -- identical class, identical model_name -- so the query and
    the stored vectors share an embedding space (CLAUDE.md inviolate rule
    2: BGE-M3, never the all-MiniLM-L6-v2 default)."""
    import chromadb
    from chromadb.utils import embedding_functions

    ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=bge_m3_weights)
    client = chromadb.PersistentClient(path=chroma_path)
    collection = client.get_collection(name=COLLECTION, embedding_function=ef)

    # Time only the query -- model load + client open above are one-time
    # setup, not query latency (see docstring).
    t0 = time.perf_counter()
    res = collection.query(query_texts=[query], n_results=top_k)
    latency_ms = round((time.perf_counter() - t0) * 1000.0, 3)

    metas = res.get("metadatas", [[]])[0]
    docs = res.get("documents", [[]])[0]
    dists = res.get("distances", [[]])[0]
    out = []
    for meta, doc, dist in zip(metas, docs, dists):
        meta = meta or {}
        paper = {
            "arxiv_id": meta.get("arxiv_id"),
            "semantic_scholar_id": meta.get("semantic_scholar_id"),
            "title": meta.get("title"),
            "abstract": meta.get("abstract") or doc,
            "authors": meta.get("authors"),
            "citation_count": meta.get("citation_count"),
        }
        out.append((paper, round(float(dist), 4)))
    return out, latency_ms


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--query", required=True,
                    help="Natural-language query against papers_recent.")
    ap.add_argument("--top-k", type=int, default=3,
                    help="Number of papers to retrieve (default 3).")
    ap.add_argument("--output", required=True,
                    help="Path to write the ranked results + latency JSON.")
    ap.add_argument("--chroma-path", default="chroma_db",
                    help="ChromaDB persistent path (real mode only).")
    ap.add_argument("--bge-m3-weights", default="/mnt/models/bge-m3",
                    help="BGE-M3 weights for embedding the query "
                         "(real mode only). DAY5-CONTRACT: must match "
                         "pipeline/embed_and_store.py.")
    ap.add_argument("--max-latency-ms", type=float, default=None,
                    help="If set, exit non-zero when query latency exceeds "
                         "this. Plan target is 1000 ms.")
    args = ap.parse_args()

    if args.top_k < 1:
        ap.error("--top-k must be >= 1")

    mock = bool(os.environ.get("MOCK_LLM"))

    if mock:
        ranked, latency_ms = _query_mock(args.query, args.top_k)
    else:
        ranked, latency_ms = _query_real(args.query, args.top_k,
                                         args.chroma_path, args.bge_m3_weights)

    results = []
    for rank, (paper, distance) in enumerate(ranked, 1):
        results.append({
            "rank": rank,
            "arxiv_id": paper.get("arxiv_id"),
            "semantic_scholar_id": paper.get("semantic_scholar_id"),
            "title": paper.get("title"),
            "abstract": paper.get("abstract"),
            "authors": paper.get("authors"),
            "citation_count": paper.get("citation_count"),
            "distance": distance,
            "score": round(1.0 - distance, 4),
        })

    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "collection": COLLECTION,
        "query": args.query,
        "top_k": args.top_k,
        "mock": mock,
        "latency_ms": latency_ms,
        "result_count": len(results),
        "results": results,
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n")

    print(f"mode       : {'mock' if mock else 'real'}")
    print(f"query      : {args.query!r}")
    print(f"latency_ms : {latency_ms}  (target < 1000)")
    print(f"results    : {len(results)}")
    for r in results:
        print(f"  #{r['rank']} {r['score']:.4f}  {r['arxiv_id']}  {r['title']}")
    print(f"written    : {out}")

    if len(results) == 0:
        print("FAIL: retrieval returned no papers (empty collection?)",
              file=sys.stderr)
        sys.exit(1)
    if args.max_latency_ms is not None and latency_ms >= args.max_latency_ms:
        print(f"FAIL: latency {latency_ms} ms >= {args.max_latency_ms} ms",
              file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
