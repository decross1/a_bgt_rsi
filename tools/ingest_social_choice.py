#!/usr/bin/env python3
"""D-075 R2 (owner-ratified 2026-08-18): one-shot curated social-choice
corpus ingest into `papers_recent`.

The August diagnosis (wf_c806049b): 20/21 off-domain kills were the lab's
OWN active topic — the corpus (and hence the topicality gates calibrated
against it) lacks the delegation / liquid-democracy / social-choice /
sortition literature the research program moved into. R2's ratified fix is
ADDITIVE CORPUS CONTENT: fetch a curated arXiv set for those topics and
ingest it through the SAME two-stage pipeline the daily cron uses
(cron/daily-arxiv.sh), so "the active research program is in-domain to its
own gates by construction".

REUSES, does not fork (the cron's exact path):
  - stage 1  pipeline/arxiv_scraper.py   — `_get_with_backoff` (the
    backoff/Retry-After discipline), `_normalize_entry` (the pipeline paper
    schema), `write_jsonl`. Only the QUERY differs: curated `all:"<topic>"`
    phrase searches sorted by relevance, instead of category+recency — the
    social-choice literature the gates need is mostly older than any
    since-days window.
  - stage 2  pipeline/embed_and_store.py — `load_papers`, `get_embedder`
    (BGE-M3, the pinned embedder), `get_collection` (same collection config)
    , `dedupe` (keyed on arxiv_id against what the collection already
    holds), `store`. Byte-identical storage path; safe to re-run.

Run REAL (the embedder must be live — MOCK_LLM would silently stub it):
    env -u MOCK_LLM .venv-chroma/bin/python tools/ingest_social_choice.py

MOCK_LLM=1 runs exercise the same code with the deterministic stub embedder
(tests only — never a real ingest).
"""
from __future__ import annotations

import argparse
import logging
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline import embed_and_store  # noqa: E402
from pipeline.arxiv_scraper import (  # noqa: E402
    _ATOM,
    _REQUEST_SPACING_S,
    _get_with_backoff,
    _normalize_entry,
    write_jsonl,
)

log = logging.getLogger("ingest_social_choice")

# The ratified topic families (D-075 R2). Each becomes one arXiv API
# phrase query: all:"<query>", sorted by relevance.
CURATED_QUERIES = (
    "liquid democracy",
    "delegative voting",
    "proxy voting",
    "sortition",
    "social choice theory",
    "voting power",
    "delegation games",
)

# ~40-paper cap ratified in the work order; per-query pull is deliberately
# larger than cap/len(queries) so round-robin merge still fills the cap
# when queries overlap heavily (these topics cross-cite constantly).
DEFAULT_CAP = 40
DEFAULT_PER_QUERY = 15

DEFAULT_DB_PATH = str(REPO_ROOT / "chroma_db")
DEFAULT_WEIGHTS = "/mnt/models/bge-m3"
DEFAULT_COLLECTION = "papers_recent"


def fetch_query(query: str, per_query: int) -> list[dict]:
    """One relevance-sorted arXiv API page for a curated phrase query.

    Uses the scraper's `_get_with_backoff` (same 429/5xx discipline as the
    cron) and `_normalize_entry` (same paper schema). Target-category set is
    empty: curated queries are topic-driven, so `category` falls back to
    each entry's primary category — honest metadata, no fabricated match.
    """
    body = _get_with_backoff({
        "search_query": f'all:"{query}"',
        "sortBy": "relevance",
        "sortOrder": "descending",
        "start": 0,
        "max_results": per_query,
    })
    root = ET.fromstring(body)
    papers = []
    for entry in root.findall(_ATOM + "entry"):
        paper = _normalize_entry(entry, set())
        if paper is not None:
            papers.append(paper)
    log.info("query %r: %d papers", query, len(papers))
    return papers


def merge_capped(per_query: dict[str, list[dict]], cap: int) -> list[dict]:
    """Round-robin merge across queries, dedup on arxiv_id, stop at cap.

    Round-robin (not concatenation) so every ratified topic family is
    represented even when the cap bites — the corpus extension must cover
    delegation AND sortition AND voting power, not 40 liquid-democracy hits.
    """
    seen: set[str] = set()
    merged: list[dict] = []
    queues = {q: list(papers) for q, papers in per_query.items()}
    while len(merged) < cap and any(queues.values()):
        for q in list(queues):
            if len(merged) >= cap:
                break
            while queues[q]:
                paper = queues[q].pop(0)
                if paper["arxiv_id"] not in seen:
                    seen.add(paper["arxiv_id"])
                    merged.append(paper)
                    break
    return merged


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cap", type=int, default=DEFAULT_CAP,
                        help=f"max papers to ingest (default {DEFAULT_CAP})")
    parser.add_argument("--per-query", type=int, default=DEFAULT_PER_QUERY,
                        help="papers fetched per curated query "
                             f"(default {DEFAULT_PER_QUERY})")
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH,
                        help="ChromaDB persistent-store directory")
    parser.add_argument("--bge-m3-weights", default=DEFAULT_WEIGHTS,
                        help="local path to the BGE-M3 weights")
    parser.add_argument("--collection", default=DEFAULT_COLLECTION,
                        help=f"target collection (default {DEFAULT_COLLECTION})")
    parser.add_argument("--output", default=None,
                        help="keep the stage-1 JSONL at this path "
                             "(default: a temp file)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")

    # ── stage 1: curated fetch (scraper path) ────────────────────────────
    per_query: dict[str, list[dict]] = {}
    for i, query in enumerate(CURATED_QUERIES):
        if i:
            time.sleep(_REQUEST_SPACING_S)  # same politeness as the cron
        per_query[query] = fetch_query(query, args.per_query)
    merged = merge_capped(per_query, args.cap)
    log.info("merged %d unique papers across %d queries (cap %d)",
             len(merged), len(CURATED_QUERIES), args.cap)

    if args.output:
        jsonl_path = args.output
    else:
        jsonl_path = tempfile.mkstemp(
            prefix="papers_social_choice_", suffix=".jsonl")[1]
    write_jsonl(merged, jsonl_path)

    # ── stage 2: embed + store (embed_and_store path, verbatim) ──────────
    papers = embed_and_store.load_papers(jsonl_path)
    embedder = embed_and_store.get_embedder(args.bge_m3_weights)
    collection = embed_and_store.get_collection(
        args.db_path, args.collection, embedder)

    before = collection.count()
    existing_ids = collection.get()["ids"]
    kept, n_dup, _, _ = embed_and_store.dedupe(papers, existing_ids)
    n_stored = embed_and_store.store(collection, kept, embedder)
    after = collection.count()

    log.info("REPORT: fetched=%d merged=%d already_present=%d ingested=%d "
             "collection %r count %d -> %d",
             sum(len(v) for v in per_query.values()), len(merged), n_dup,
             n_stored, args.collection, before, after)
    return 0


if __name__ == "__main__":
    sys.exit(main())
