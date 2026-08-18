"""Doc-id → title resolution: every observed id family maps to the title
sitting in Chroma metadata; everything else stays honestly absent.

All tests ride a FAKE chroma client (id-keyed dicts) — no real store, no
embedder, no network. The fake mirrors the real client surface this module
touches: list_collections / get_collection / collection.get(ids|limit).
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.doc_titles import MAX_IDS, register


class FakeCollection:
    def __init__(self, docs):
        self._docs = dict(docs)          # id -> metadata dict
        self.get_calls = 0               # pins the LRU (no re-hit on cache)

    def get(self, ids=None, limit=None, include=None):
        self.get_calls += 1
        if ids is not None:
            found = [(i, self._docs[i]) for i in ids if i in self._docs]
        else:
            found = list(self._docs.items())[: limit or len(self._docs)]
        return {"ids": [i for i, _ in found],
                "metadatas": [m for _, m in found]}


class _Named:
    def __init__(self, name):
        self.name = name


class FakeClient:
    def __init__(self, collections):
        self._collections = collections

    def list_collections(self):
        return [_Named(n) for n in self._collections]

    def get_collection(self, name):
        try:
            return self._collections[name]
        except KeyError:
            raise ValueError(f"Collection {name} does not exist.")


PAPERS = FakeCollection({
    "2404.08492": {
        "title": "Strategic Interactions between Large Language Models-based "
                 "Agents in Beauty Contests",
        "publication_date": "2024-04-12",
        "arxiv_id": "2404.08492",
    },
})
ML_INTERN = FakeCollection({
    "0905.3640": {
        "title": "Coevolutionary Genetic Algorithms for Establishing Nash "
                 "Equilibrium in Symmetric Cournot Games",
        "publication_date": "2009-01-01",
    },
    "s2:d6e3d22cc5cacb7b5f28ae8b0ce45b100bbf744f": {
        "title": "Strategic Investment in Power and Heat Markets",
        "publication_date": "2021-01-01",
    },
})
# Real shape: the chunk-id stem does NOT match the collection name.
OSBORNE = FakeCollection({
    "osborne_rubinstein-chunk-850": {
        "book": "osborne_rubinstein",
        "chapter_title": "8 Repeated Games",
        "page_range": "150-151",
        "section": "8.2 Infinitely Repeated Games",
    },
    "osborne_rubinstein-chunk-0": {"book": "osborne_rubinstein"},
})
WEIBULL = FakeCollection({
    "evolutionary-game-theory_compress-chunk-0": {
        "book": "evolutionary-game-theory_compress",
        "chapter_title": "", "page_range": "1-293", "section": "",
    },
    "evolutionary-game-theory_compress-chunk-213": {
        "book": "evolutionary-game-theory_compress",
        "chapter_title": "", "page_range": "1-293", "section": "",
    },
})
# A scratch collection with non-chunk ids must not poison the stem map.
SCRATCH = FakeCollection({"doc-0": {}})


def _client():
    return FakeClient({
        "papers_recent": PAPERS,
        "ml_intern_fetched": ML_INTERN,
        "osborne_rubinstein": OSBORNE,
        "weibull_egt": WEIBULL,
        "day3_test": SCRATCH,
    })


def _app(factory=None):
    app = FastAPI()
    register(app, client_factory=factory or _client)
    return TestClient(app)


def _get(client, ids):
    return client.get("/api/doc_titles", params={"ids": ids})


def test_arxiv_id_resolves_from_papers_recent_with_year():
    resp = _get(_app(), "2404.08492")
    assert resp.status_code == 200
    body = resp.json()
    assert body["2404.08492"]["kind"] == "paper"
    assert body["2404.08492"]["title"].startswith("Strategic Interactions")
    assert body["2404.08492"]["detail"] == "2024"


def test_arxiv_id_falls_back_to_ml_intern_fetched():
    body = _get(_app(), "0905.3640").json()
    assert body["0905.3640"]["kind"] == "paper"
    assert "Coevolutionary" in body["0905.3640"]["title"]


def test_s2_id_resolves_from_ml_intern_fetched():
    sid = "s2:d6e3d22cc5cacb7b5f28ae8b0ce45b100bbf744f"
    body = _get(_app(), sid).json()
    assert body[sid] == {"title": "Strategic Investment in Power and Heat "
                                  "Markets",
                         "kind": "s2", "detail": "2021"}


def test_book_chunk_composes_label_chapter_and_pages():
    body = _get(_app(), "osborne_rubinstein-chunk-850").json()
    info = body["osborne_rubinstein-chunk-850"]
    assert info["kind"] == "book"
    assert info["title"] == ("Osborne & Rubinstein, A Course in Game Theory"
                             " — 8 Repeated Games (pp 150-151)")
    assert info["detail"] == "8.2 Infinitely Repeated Games"


def test_compress_chunk_maps_by_derived_stem_not_collection_name():
    # "evolutionary-game-theory_compress" is weibull_egt's id stem — the
    # resolver must find the collection by peeking, never by name-matching.
    cid = "evolutionary-game-theory_compress-chunk-213"
    body = _get(_app(), cid).json()
    assert body[cid]["kind"] == "book"
    # Empty chapter_title → no dangling separator; pages still appended.
    assert body[cid]["title"] == ("Weibull, Evolutionary Game Theory "
                                  "(pp 1-293)")


def test_unresolved_ids_are_absent_not_faked():
    body = _get(_app(), "9999.00001,weird:id,unknown_book-chunk-3").json()
    assert body == {}


def test_mixed_batch_resolves_each_family_in_one_call():
    ids = ",".join(["2404.08492",
                    "s2:d6e3d22cc5cacb7b5f28ae8b0ce45b100bbf744f",
                    "osborne_rubinstein-chunk-850",
                    "not-a-real-id"])
    body = _get(_app(), ids).json()
    assert set(body) == {"2404.08492",
                         "s2:d6e3d22cc5cacb7b5f28ae8b0ce45b100bbf744f",
                         "osborne_rubinstein-chunk-850"}


def test_batch_over_cap_is_an_explicit_400():
    ids = ",".join(f"2404.{10000 + i}" for i in range(MAX_IDS + 1))
    resp = _get(_app(), ids)
    assert resp.status_code == 400
    assert f"> {MAX_IDS}" in resp.json()["detail"]


def test_repeat_lookup_hits_the_cache_not_the_collection():
    papers = FakeCollection({"2404.08492": {"title": "T",
                                            "publication_date": "2024-04-12"}})
    client = FakeClient({"papers_recent": papers,
                         "ml_intern_fetched": FakeCollection({})})
    app = _app(lambda: client)
    _get(app, "2404.08492")
    first = papers.get_calls
    _get(app, "2404.08492")
    assert papers.get_calls == first  # second request never re-queried


def test_broken_chroma_is_an_honest_503_never_a_silent_empty_map():
    def boom():
        raise ModuleNotFoundError("No module named 'chromadb'")
    resp = _get(_app(boom), "2404.08492")
    assert resp.status_code == 503
    assert "chroma unavailable" in resp.json()["detail"]


def test_empty_ids_param_is_an_empty_map():
    assert _get(_app(), "").json() == {}


def test_chromadb_importable_under_the_backend_test_venv():
    # The task's runtime premise: title resolution needs a backend served
    # from .venv-chroma. Skips (rather than lies) on a venv without it.
    chromadb = pytest.importorskip("chromadb")
    assert hasattr(chromadb, "PersistentClient")
