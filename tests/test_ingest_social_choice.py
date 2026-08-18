"""Tests for tools/ingest_social_choice.py — the D-075 R2 curated corpus
ingest.

The tool REUSES the cron's two-stage pipeline (pipeline/arxiv_scraper.py
stage 1, pipeline/embed_and_store.py stage 2); these tests cover the parts
the tool itself owns — the curated query fetch/parse, the round-robin
capped merge — plus one end-to-end main() run against a monkeypatched
arXiv API and a real (tmp-path) ChromaDB store under the MOCK_LLM stub
embedder, asserting the collection-count delta and arxiv_id dedupe the
real run reports.

Run: MOCK_LLM=1 .venv-chroma/bin/python -m pytest tests/test_ingest_social_choice.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

import tools.ingest_social_choice as isc  # noqa: E402


# ── Atom fixtures (mirror tests/test_arxiv_scraper.py) ──────────────────────

def _entry(arxiv_id, title="A Title", summary="An abstract.",
           primary="cs.GT"):
    return (f"<entry><id>http://arxiv.org/abs/{arxiv_id}</id>"
            f"<title>{title}</title><summary>{summary}</summary>"
            f"<published>2026-08-01T12:00:00Z</published>"
            f"<author><name>Ada Lovelace</name></author>"
            f'<arxiv:primary_category term="{primary}"/>'
            f'<category term="{primary}"/></entry>')


def _feed(*entries):
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<feed xmlns="http://www.w3.org/2005/Atom" '
            'xmlns:arxiv="http://arxiv.org/schemas/atom">'
            + "".join(entries) + "</feed>")


def _paper(arxiv_id):
    return {"title": f"T {arxiv_id}", "abstract": f"A {arxiv_id}",
            "authors": ["X"], "arxiv_id": arxiv_id,
            "semantic_scholar_id": None, "citation_count": 0,
            "category": "cs.GT", "publication_date": "2026-08-01"}


# ── fetch_query ──────────────────────────────────────────────────────────────

def test_fetch_query_builds_phrase_query_and_parses(monkeypatch):
    """The curated query is a relevance-sorted all:"<phrase>" search, parsed
    through the scraper's own _normalize_entry (same paper schema)."""
    captured = {}

    def fake_get(params):
        captured.update(params)
        return _feed(_entry("2608.13085", title="Representation in Peer "
                            "Selection: A Liquid Democracy Perspective"),
                     _entry("1802.08020", title="Liquid Democracy: An "
                            "Algorithmic Perspective"))

    monkeypatch.setattr(isc, "_get_with_backoff", fake_get)
    papers = isc.fetch_query("liquid democracy", 15)
    assert captured["search_query"] == 'all:"liquid democracy"'
    assert captured["sortBy"] == "relevance"
    assert captured["max_results"] == 15
    assert [p["arxiv_id"] for p in papers] == ["2608.13085", "1802.08020"]
    # The pipeline paper schema (stage 2 consumes these keys verbatim).
    assert set(papers[0]) == {"title", "abstract", "authors", "arxiv_id",
                              "semantic_scholar_id", "citation_count",
                              "category", "publication_date"}


# ── merge_capped ─────────────────────────────────────────────────────────────

def test_merge_round_robin_represents_every_query():
    per_query = {
        "liquid democracy": [_paper("ld.1"), _paper("ld.2"), _paper("ld.3")],
        "sortition": [_paper("so.1"), _paper("so.2")],
        "voting power": [_paper("vp.1")],
    }
    merged = isc.merge_capped(per_query, cap=3)
    assert [p["arxiv_id"] for p in merged] == ["ld.1", "so.1", "vp.1"]


def test_merge_dedupes_on_arxiv_id_across_queries():
    shared = _paper("shared.1")
    per_query = {
        "liquid democracy": [shared, _paper("ld.2")],
        "delegative voting": [dict(shared), _paper("dv.2")],
    }
    merged = isc.merge_capped(per_query, cap=10)
    ids = [p["arxiv_id"] for p in merged]
    assert ids.count("shared.1") == 1
    assert set(ids) == {"shared.1", "ld.2", "dv.2"}


def test_merge_respects_cap():
    per_query = {"q": [_paper(f"p.{i}") for i in range(10)]}
    assert len(isc.merge_capped(per_query, cap=4)) == 4


def test_merge_exhausts_short_queues_without_stalling():
    per_query = {"a": [_paper("a.1")], "b": [], "c": [_paper("c.1"),
                                                      _paper("c.2")]}
    merged = isc.merge_capped(per_query, cap=40)
    assert {p["arxiv_id"] for p in merged} == {"a.1", "c.1", "c.2"}


# ── end-to-end main() against a tmp ChromaDB store ───────────────────────────

@pytest.mark.usefixtures("monkeypatch")
def test_main_ingests_and_dedupes_against_existing(monkeypatch, tmp_path,
                                                   capsys):
    """main() runs the cron's stage-2 path against a real (tmp) store: first
    run ingests all unique papers; a re-run ingests 0 (arxiv_id dedupe)."""
    monkeypatch.setenv("MOCK_LLM", "1")  # stub embedder; storage path real
    monkeypatch.setattr(isc, "CURATED_QUERIES", ("liquid democracy",
                                                 "sortition"))
    monkeypatch.setattr(isc, "_REQUEST_SPACING_S", 0)
    feeds = {
        "liquid democracy": _feed(_entry("2608.13085"), _entry("1802.08020")),
        "sortition": _feed(_entry("2001.00001"), _entry("1802.08020")),
    }

    def fake_get(params):
        phrase = params["search_query"][len('all:"'):-1]
        return feeds[phrase]

    monkeypatch.setattr(isc, "_get_with_backoff", fake_get)

    db = str(tmp_path / "chroma")
    argv = ["--db-path", db, "--collection", "papers_recent",
            "--bge-m3-weights", "unused-under-mock",
            "--output", str(tmp_path / "curated.jsonl")]
    assert isc.main(argv) == 0

    import chromadb
    coll = chromadb.PersistentClient(path=db).get_collection("papers_recent")
    assert coll.count() == 3  # 4 fetched, 1 cross-query duplicate
    assert set(coll.get()["ids"]) == {"2608.13085", "1802.08020",
                                      "2001.00001"}

    # Re-run: everything already present -> 0 stored, count unchanged.
    assert isc.main(argv) == 0
    assert coll.count() == 3
