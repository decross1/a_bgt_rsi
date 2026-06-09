"""Tests for workers.retrieve_literature.

Stubs query_top_k via monkeypatch; no real Chroma needed.
"""
import sys
from pathlib import Path
from unittest import mock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from workers import retrieve_literature as rl_mod


def _fake_query(returned_neighbors):
    """Build a query_top_k stub returning the given neighbors."""
    def stub(text, k=10, collections=None, *, parent_request_id=None):
        return {
            "status": "passed",
            "result": {
                "k": k,
                "neighbors": list(returned_neighbors),
                "latency_ms": 1.0,
            },
            "errors": [],
            "parent_request_id": parent_request_id,
        }
    return stub


def test_empty_hypothesis_returns_error():
    out = rl_mod.retrieve_literature("", k=5)
    assert out["status"] == "error"
    assert any("required" in e for e in out["errors"])
    assert out["result"]["neighbors"] == []


def test_whitespace_hypothesis_returns_error():
    out = rl_mod.retrieve_literature("   \n  ", k=5)
    assert out["status"] == "error"


def test_dedupes_by_content_hash(monkeypatch):
    # Two duplicates by hash, plus a unique one — expect 2 results, the
    # duplicate kept is the higher-scoring one.
    fake = _fake_query([
        {"doc_id": "a1", "content_hash": "sha256:H1", "score": 0.50, "source_layer": "foundational"},
        {"doc_id": "a2", "content_hash": "sha256:H1", "score": 0.80, "source_layer": "foundational"},  # dup of above, higher score
        {"doc_id": "b1", "content_hash": "sha256:H2", "score": 0.60, "source_layer": "live_arxiv"},
    ])
    monkeypatch.setattr(rl_mod, "query_top_k", fake)
    out = rl_mod.retrieve_literature("anything", k=5)
    assert out["status"] == "passed"
    neighbors = out["result"]["neighbors"]
    assert len(neighbors) == 2
    # Sorted by score descending after dedup
    assert neighbors[0]["doc_id"] == "a2"
    assert neighbors[0]["score"] == 0.80
    assert neighbors[1]["doc_id"] == "b1"


def test_caps_k_at_50(monkeypatch):
    fake = _fake_query([])
    monkeypatch.setattr(rl_mod, "query_top_k", fake)
    out = rl_mod.retrieve_literature("x", k=10_000)
    # Doesn't crash; clamped silently.
    assert out["status"] == "passed"


def test_floors_k_at_1(monkeypatch):
    fake = _fake_query([{"doc_id": "a", "content_hash": "sha256:1", "score": 0.5, "source_layer": "foundational"}])
    monkeypatch.setattr(rl_mod, "query_top_k", fake)
    out = rl_mod.retrieve_literature("x", k=0)
    assert out["status"] == "passed"
    assert out["result"]["k"] == 1


def test_passes_parent_request_id_through(monkeypatch):
    captured = {}
    def stub(text, k=10, collections=None, *, parent_request_id=None):
        captured["parent"] = parent_request_id
        return {"status": "passed", "result": {"k": 0, "neighbors": [], "latency_ms": 0.1}, "errors": [], "parent_request_id": parent_request_id}
    monkeypatch.setattr(rl_mod, "query_top_k", stub)
    out = rl_mod.retrieve_literature("x", parent_request_id="req-abc")
    assert captured["parent"] == "req-abc"
    assert out["parent_request_id"] == "req-abc"


def test_propagates_query_top_k_error(monkeypatch):
    def stub(text, k=10, collections=None, *, parent_request_id=None):
        return {
            "status": "error",
            "result": {"k": 0, "neighbors": [], "latency_ms": 0.0},
            "errors": ["chroma boom"],
            "parent_request_id": parent_request_id,
        }
    monkeypatch.setattr(rl_mod, "query_top_k", stub)
    out = rl_mod.retrieve_literature("x")
    assert out["status"] == "error"
    assert "chroma boom" in out["errors"]


def test_handles_neighbors_with_no_content_hash(monkeypatch):
    # Graceful fallback: dedup-key falls back to doc_id when hash is missing.
    fake = _fake_query([
        {"doc_id": "a", "content_hash": None, "score": 0.5, "source_layer": "foundational"},
        {"doc_id": "b", "content_hash": None, "score": 0.6, "source_layer": "foundational"},
    ])
    monkeypatch.setattr(rl_mod, "query_top_k", fake)
    out = rl_mod.retrieve_literature("x", k=5)
    assert out["status"] == "passed"
    # Both kept (different doc_ids → different fallback keys).
    assert out["result"]["k"] == 2


# ----- T1c corpus de-drift: collection scoping ---------------------------


def test_default_collections_constants():
    """DEFAULT_QUERY_COLLECTIONS = foundational + papers_recent; the drifted
    ml_intern_fetched stays REGISTERED (D-038) but out of the default scope."""
    from orchestrator import chroma_query as cq
    assert cq.FOUNDATIONAL_COLLECTIONS == [
        name for name, layer in cq.COLLECTIONS.items() if layer == "foundational"
    ]
    assert cq.DEFAULT_QUERY_COLLECTIONS == cq.FOUNDATIONAL_COLLECTIONS + ["papers_recent"]
    assert "ml_intern_fetched" not in cq.DEFAULT_QUERY_COLLECTIONS
    assert "ml_intern_fetched" in cq.COLLECTIONS  # still registered


def test_query_top_k_default_scope_excludes_ml_intern(monkeypatch):
    """query_top_k's default scope queries DEFAULT_QUERY_COLLECTIONS only.
    Exercised on the real (non-mock) path with a stubbed collection."""
    from orchestrator import chroma_query as cq

    queried = []

    class _FakeColl:
        def query(self, query_texts, n_results):
            return {"metadatas": [[]], "documents": [[]], "distances": [[]]}

    monkeypatch.delenv("MOCK_LLM", raising=False)
    monkeypatch.setattr(cq, "_get_collection",
                        lambda name: queried.append(name) or _FakeColl())
    out = cq.query_top_k("x", k=3)
    assert out["status"] in ("passed", "error")
    assert queried == cq.DEFAULT_QUERY_COLLECTIONS


def test_query_top_k_explicit_ml_intern_still_queryable(monkeypatch):
    """ml_intern_fetched is reachable via explicit collections= (D-038)."""
    from orchestrator import chroma_query as cq

    queried = []

    class _FakeColl:
        def query(self, query_texts, n_results):
            return {"metadatas": [[]], "documents": [[]], "distances": [[]]}

    monkeypatch.delenv("MOCK_LLM", raising=False)
    monkeypatch.setattr(cq, "_get_collection",
                        lambda name: queried.append(name) or _FakeColl())
    cq.query_top_k("x", k=3, collections=["ml_intern_fetched"])
    assert queried == ["ml_intern_fetched"]


def test_retrieve_literature_default_passes_no_collections(monkeypatch):
    """include_ml_intern defaults False -> collections=None (query_top_k's
    default scope decides)."""
    captured = {}

    def stub(text, k=10, collections=None, *, parent_request_id=None):
        captured["collections"] = collections
        return {"status": "passed", "result": {"k": 0, "neighbors": [], "latency_ms": 0.1},
                "errors": [], "parent_request_id": parent_request_id}

    monkeypatch.setattr(rl_mod, "query_top_k", stub)
    out = rl_mod.retrieve_literature("x")
    assert out["status"] == "passed"
    assert captured["collections"] is None


def test_retrieve_literature_include_ml_intern_widens_scope(monkeypatch):
    """include_ml_intern=True -> DEFAULT_QUERY_COLLECTIONS + ml_intern_fetched."""
    from orchestrator.chroma_query import DEFAULT_QUERY_COLLECTIONS
    captured = {}

    def stub(text, k=10, collections=None, *, parent_request_id=None):
        captured["collections"] = collections
        return {"status": "passed", "result": {"k": 0, "neighbors": [], "latency_ms": 0.1},
                "errors": [], "parent_request_id": parent_request_id}

    monkeypatch.setattr(rl_mod, "query_top_k", stub)
    out = rl_mod.retrieve_literature("x", include_ml_intern=True)
    assert out["status"] == "passed"
    assert captured["collections"] == DEFAULT_QUERY_COLLECTIONS + ["ml_intern_fetched"]


def test_include_ml_intern_dedup_still_applies(monkeypatch):
    """Dedup by content_hash holds on the widened scope too."""
    fake = _fake_query([
        {"doc_id": "a1", "content_hash": "sha256:H1", "score": 0.50, "source_layer": "foundational"},
        {"doc_id": "mi1", "content_hash": "sha256:H1", "score": 0.80, "source_layer": "live_ml_intern"},
        {"doc_id": "b1", "content_hash": "sha256:H2", "score": 0.60, "source_layer": "live_arxiv"},
    ])
    monkeypatch.setattr(rl_mod, "query_top_k", fake)
    out = rl_mod.retrieve_literature("x", k=5, include_ml_intern=True)
    neighbors = out["result"]["neighbors"]
    assert len(neighbors) == 2
    assert neighbors[0]["doc_id"] == "mi1"  # higher-scoring dup kept


# ----- Slice-2 ML-Intern escalation trigger -----------------------------


def _foundational(book: str, chunk: int, score: float, hash_suffix: str | None = None) -> dict:
    h = f"sha256:{hash_suffix or f'{book}-{chunk}'}"
    return {
        "doc_id": f"{book}-chunk-{chunk}",
        "content_hash": h,
        "score": score,
        "source_layer": "foundational",
        "title": f"chapter from {book}",
    }


def _arxiv(arxiv_id: str, score: float) -> dict:
    return {
        "doc_id": arxiv_id,
        "content_hash": f"sha256:{arxiv_id}",
        "score": score,
        "source_layer": "live_arxiv",
        "title": "an arxiv paper",
    }


def test_escalation_field_always_present(monkeypatch):
    """Every passed retrieval carries an escalation decision."""
    fake = _fake_query([_foundational("osborne_rubinstein", 1, 0.5)])
    monkeypatch.setattr(rl_mod, "query_top_k", fake)
    out = rl_mod.retrieve_literature("x", k=5)
    esc = out["result"]["escalation"]
    # Contract fields present:
    for key in ("should_escalate", "max_score", "distinct_books", "books",
                "reason", "score_threshold", "min_distinct_books"):
        assert key in esc, f"missing {key} in escalation: {esc}"
    assert esc["score_threshold"] == rl_mod.RETRIEVAL_ESCALATION_SCORE_THRESHOLD
    assert esc["min_distinct_books"] == rl_mod.RETRIEVAL_ESCALATION_MIN_DISTINCT_BOOKS


def test_escalation_fires_when_weak_signal_and_narrow_coverage(monkeypatch):
    """Compound trigger TRUE: max_score < 0.70 AND distinct_books < 3."""
    fake = _fake_query([
        _foundational("osborne_rubinstein", 1, 0.65),
        _foundational("osborne_rubinstein", 2, 0.62),
        _foundational("osborne_rubinstein", 3, 0.60),
        _arxiv("2605.99999", 0.55),
    ])
    monkeypatch.setattr(rl_mod, "query_top_k", fake)
    out = rl_mod.retrieve_literature("x", k=10)
    esc = out["result"]["escalation"]
    assert esc["should_escalate"] is True
    assert esc["max_score"] == 0.65
    assert esc["distinct_books"] == 1  # only osborne_rubinstein counts
    assert esc["books"] == ["osborne_rubinstein"]


def test_escalation_suppressed_by_strong_signal(monkeypatch):
    """High max_score alone suppresses escalation regardless of coverage.
    (Matches paraphrase_probe.py's seed D — textbook phrasing, max
    score 0.7534, narrow foundational coverage, no escalation.)"""
    fake = _fake_query([
        _foundational("osborne_rubinstein", 1, 0.75),
        _foundational("osborne_rubinstein", 2, 0.70),
    ])
    monkeypatch.setattr(rl_mod, "query_top_k", fake)
    out = rl_mod.retrieve_literature("x", k=10)
    esc = out["result"]["escalation"]
    assert esc["should_escalate"] is False
    assert esc["max_score"] == 0.75
    assert esc["distinct_books"] == 1
    assert "no escalation" in esc["reason"]


def test_escalation_suppressed_by_diverse_coverage(monkeypatch):
    """Diverse foundational coverage suppresses escalation even when
    max_score is weak. (Matches paraphrase_probe.py's seed B —
    behavioral-econ phrasing, max score 0.6174, 4 foundational books
    in top-10, no escalation.)"""
    fake = _fake_query([
        _foundational("osborne_rubinstein", 1, 0.61),
        _foundational("camerer_bgt", 71, 0.60),
        _foundational("hofbauer_sigmund_egpd", 44, 0.60),
        _foundational("evolutionary-game-theory_compress", 836, 0.59),
    ])
    monkeypatch.setattr(rl_mod, "query_top_k", fake)
    out = rl_mod.retrieve_literature("x", k=10)
    esc = out["result"]["escalation"]
    assert esc["should_escalate"] is False
    assert esc["distinct_books"] == 4
    assert set(esc["books"]) == {
        "osborne_rubinstein", "camerer_bgt", "hofbauer_sigmund_egpd",
        "evolutionary-game-theory_compress",
    }


def test_escalation_arxiv_does_not_count_as_book(monkeypatch):
    """The foundational-book gate ignores arXiv chunks (the trigger's
    purpose is to detect narrow FOUNDATIONAL coverage — arXiv hits
    don't fill that need)."""
    fake = _fake_query([
        _foundational("osborne_rubinstein", 1, 0.65),
        _arxiv("2605.00001", 0.64),
        _arxiv("2605.00002", 0.63),
        _arxiv("2605.00003", 0.62),
        _arxiv("2605.00004", 0.61),
    ])
    monkeypatch.setattr(rl_mod, "query_top_k", fake)
    out = rl_mod.retrieve_literature("x", k=10)
    esc = out["result"]["escalation"]
    assert esc["distinct_books"] == 1  # only osborne_rubinstein
    assert esc["should_escalate"] is True


def test_escalation_no_neighbors_does_not_escalate(monkeypatch):
    """Empty retrieval → no escalation (would just yield more nothing)."""
    fake = _fake_query([])
    monkeypatch.setattr(rl_mod, "query_top_k", fake)
    out = rl_mod.retrieve_literature("x", k=10)
    esc = out["result"]["escalation"]
    assert esc["should_escalate"] is False
    assert esc["max_score"] == 0.0
    assert esc["distinct_books"] == 0
    assert "no neighbors" in esc["reason"]


def test_escalation_evaluates_only_top_k_for_diversity(monkeypatch):
    """The diversity gate looks at top-RETRIEVAL_ESCALATION_TOP_K, not
    all retained neighbors. A 12th-ranked Camerer chunk doesn't count."""
    # 10 osborne_rubinstein chunks (filling the diversity window), then
    # camerer_bgt at rank 11 + hofbauer at rank 12 — those don't count.
    neighbors = [_foundational("osborne_rubinstein", i, 0.69 - i * 0.001)
                 for i in range(10)]
    neighbors.append(_foundational("camerer_bgt", 99, 0.55))
    neighbors.append(_foundational("hofbauer_sigmund_egpd", 99, 0.54))
    fake = _fake_query(neighbors)
    monkeypatch.setattr(rl_mod, "query_top_k", fake)
    out = rl_mod.retrieve_literature("x", k=15)
    esc = out["result"]["escalation"]
    assert esc["distinct_books"] == 1  # only osborne_rubinstein in top-10
    assert esc["should_escalate"] is True
    # And the lower-ranked books are still in result.neighbors (the trigger
    # doesn't filter them out, it only evaluates).
    doc_ids = {n["doc_id"] for n in out["result"]["neighbors"]}
    assert "camerer_bgt-chunk-99" in doc_ids
    assert "hofbauer_sigmund_egpd-chunk-99" in doc_ids


def test_existing_callers_unaffected_by_escalation_field(monkeypatch):
    """Backward compat: k and neighbors are still the load-bearing
    fields; adding escalation didn't break anything."""
    fake = _fake_query([_foundational("osborne_rubinstein", 1, 0.5)])
    monkeypatch.setattr(rl_mod, "query_top_k", fake)
    out = rl_mod.retrieve_literature("x", k=5)
    assert out["result"]["k"] == 1
    assert out["result"]["neighbors"][0]["doc_id"] == "osborne_rubinstein-chunk-1"
    assert "latency_ms" in out["result"]
