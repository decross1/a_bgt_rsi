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
