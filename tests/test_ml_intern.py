"""Offline tests for workers.ml_intern (run under MOCK_LLM, no network).

`_s2_search` is monkeypatched to a canned S2 response, and `db_path` is a
per-test tmp dir so the real `chroma_db/` is never touched. Under MOCK_LLM
`get_embedder` returns the deterministic stub, so embed + store run without
the BGE-M3 weights or a GPU.
"""
from __future__ import annotations

import pytest

from workers import ml_intern as mli


def _item(paper_id, *, arxiv=None, abstract="an abstract", year=2020, cites=3):
    """Build one canned S2 paper-search `data` item."""
    external = {"ArXiv": arxiv} if arxiv else {}
    return {
        "paperId": paper_id,
        "externalIds": external,
        "title": f"Title {paper_id}",
        "abstract": abstract,
        "authors": [{"name": "Ada Lovelace"}, {"name": "Alan Turing"}],
        "year": year,
        "citationCount": cites,
    }


def test_happy_path_stores_and_maps_ids(tmp_path, monkeypatch):
    """Mixed arXiv / non-arXiv items: arXiv-bearing keeps its real id, the
    arXiv-less one maps to `s2:<paperId>`, null-abstract is dropped."""
    canned = [
        _item("p-arxiv", arxiv="2401.00001"),
        _item("p-noarxiv"),                       # -> s2:p-noarxiv
        _item("p-nullabs", abstract=None),        # dropped by dedupe
    ]
    monkeypatch.setattr(mli, "_s2_search", lambda q, **kw: list(canned))

    out = mli.ml_intern(
        "Tit-for-tat dominates in repeated games. Extra sentence here.",
        "iter-007",
        parent_request_id="req-1",
        db_path=str(tmp_path / "chroma"),
    )

    assert out["status"] == "passed"
    assert out["errors"] == []
    assert out["parent_request_id"] == "req-1"
    res = out["result"]
    assert res["collection"] == "ml_intern_fetched"
    assert res["escalated_from"] == "iter-007"
    # query is keyphrase-reduced to <=6 distinctive content terms (stopwords
    # 'for'/'in' dropped) so S2's keyword-AND search is not over-constrained
    # (the 2026-06-09 root cause: a 39-term hypothesis returned total=0).
    assert res["query"] == "Tit tat dominates repeated games Extra"
    assert res["papers_fetched"] == 3          # all three mapped
    assert res["papers_stored"] == 2           # null-abstract dropped

    # Verify the actual stored ids via the mapping rule.
    assert mli._map_s2_paper(canned[0])["arxiv_id"] == "2401.00001"
    assert mli._map_s2_paper(canned[1])["arxiv_id"] == "s2:p-noarxiv"


def test_dedup_within_collection(tmp_path, monkeypatch):
    """Two items resolving to the same id -> only one stored."""
    canned = [
        _item("dup", arxiv="2401.99999"),
        _item("dup2", arxiv="2401.99999"),   # same arxiv id -> dup
    ]
    monkeypatch.setattr(mli, "_s2_search", lambda q, **kw: list(canned))

    out = mli.ml_intern(
        "Coordination failure in beauty-contest games.",
        "iter-008",
        db_path=str(tmp_path / "chroma"),
    )
    assert out["status"] == "passed"
    assert out["result"]["papers_fetched"] == 2
    assert out["result"]["papers_stored"] == 1


def test_missing_api_key_errors_without_raising(tmp_path, monkeypatch):
    """No SEMANTIC_SCHOLAR_API_KEY -> error envelope, no exception."""
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
    # Real _s2_search so the missing-key guard fires.
    out = mli.ml_intern(
        "Some hypothesis about auctions.",
        "iter-009",
        db_path=str(tmp_path / "chroma"),
    )
    assert out["status"] == "error"
    assert out["result"] is None
    assert out["errors"]


def test_s2_down_errors_without_raising(tmp_path, monkeypatch):
    """S2 exhaustion (MLInternFetchError) -> error envelope, no raise."""
    def _boom(query, **kw):
        raise mli.MLInternFetchError("S2 unreachable after retries")

    monkeypatch.setattr(mli, "_s2_search", _boom)
    out = mli.ml_intern(
        "Some hypothesis about auctions.",
        "iter-010",
        db_path=str(tmp_path / "chroma"),
    )
    assert out["status"] == "error"
    assert out["result"] is None
    assert any("S2 unreachable" in e for e in out["errors"])


def test_empty_hypothesis_errors(tmp_path):
    """Empty / whitespace hypothesis -> error envelope."""
    out = mli.ml_intern("   ", "iter-011", db_path=str(tmp_path / "chroma"))
    assert out["status"] == "error"
    assert out["result"] is None
    assert out["errors"]
