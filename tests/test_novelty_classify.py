"""Tests for workers.novelty_classify.

Stubs wrapper.call_sync; never hits real Gemma. After the reference-passing
refactor the worker reads neighbors from the per-iteration cache by
`iteration_id`, so each test pre-populates the cache via the `cache`
fixture (see tests/conftest.py).
"""
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from workers import novelty_classify as nc_mod


def _fake_call(completion_text: str, request_id: str = "req-nov"):
    def stub(messages, **kwargs):
        return {
            "request_id": request_id,
            "completion": completion_text,
            "model": "gemma-4-26b-a4b",
            "model_version": "test",
            "parent_request_id": kwargs.get("parent_request_id"),
            "caller_tag": kwargs.get("caller_tag"),
            "usage": {"input_tokens": 100, "output_tokens": 50},
            "latency_ms": 100.0,
        }
    return stub


def _neighbors(*doc_ids: str) -> list[dict]:
    return [
        {
            "doc_id": d,
            "content_hash": f"sha256:{d}",
            "score": 0.7 - 0.05 * i,
            "chunk_text": f"chunk text for {d}",
            "source_layer": "foundational",
            "title": f"title-{d}",
        }
        for i, d in enumerate(doc_ids)
    ]


def _stage_retrieval(cache, iteration_id: str, neighbors: list[dict]) -> None:
    """Mimic what Nara does after retrieve_literature returns: write the
    full tool_result dict to the cache under the 'retrieval' key."""
    cache.write_entry(iteration_id, "retrieval", {
        "status": "passed",
        "result": {"k": len(neighbors), "neighbors": neighbors},
        "errors": [],
        "wrapper_request_id": "ret-test",
        "parent_request_id": None,
    })


def test_empty_hypothesis_errors(cache):
    _stage_retrieval(cache, "it-1", _neighbors("a"))
    out = nc_mod.novelty_classify("", "it-1")
    assert out["status"] == "error"


def test_empty_iteration_id_errors(cache):
    out = nc_mod.novelty_classify("h", "")
    assert out["status"] == "error"
    assert any("iteration_id" in e for e in out["errors"])


def test_cache_miss_errors(cache):
    # No retrieval staged for this iteration_id.
    out = nc_mod.novelty_classify("h", "it-missing")
    assert out["status"] == "error"
    assert any("iteration cache miss" in e for e in out["errors"])


def test_novel_classification(cache, monkeypatch):
    completion = json.dumps({
        "class": "novel",
        "rationale": "No retrieved chunk matches the claim about compute thresholds.",
        "top_neighbor_id": None,
    })
    monkeypatch.setattr(nc_mod, "call_sync", _fake_call(completion))
    _stage_retrieval(cache, "it-2", _neighbors("a", "b"))
    out = nc_mod.novelty_classify("compute-threshold claim", "it-2")
    assert out["status"] == "passed"
    assert out["result"]["class"] == "novel"
    assert out["result"]["top_neighbor_id"] is None
    assert out["errors"] == []


def test_rediscovery_classification(cache, monkeypatch):
    completion = json.dumps({
        "class": "rediscovery",
        "rationale": "Chunk a1 states this verbatim.",
        "top_neighbor_id": "a1",
    })
    monkeypatch.setattr(nc_mod, "call_sync", _fake_call(completion))
    _stage_retrieval(cache, "it-3", _neighbors("a1", "b1"))
    out = nc_mod.novelty_classify("h", "it-3")
    assert out["status"] == "passed"
    assert out["result"]["class"] == "rediscovery"
    assert out["result"]["top_neighbor_id"] == "a1"


def test_nonsense_classification(cache, monkeypatch):
    completion = json.dumps({
        "class": "nonsense",
        "rationale": "Not a coherent research question.",
        "top_neighbor_id": None,
    })
    monkeypatch.setattr(nc_mod, "call_sync", _fake_call(completion))
    _stage_retrieval(cache, "it-4", _neighbors())
    out = nc_mod.novelty_classify("asdfgh", "it-4")
    assert out["status"] == "passed"
    assert out["result"]["class"] == "nonsense"


def test_unclear_classification(cache, monkeypatch):
    completion = json.dumps({
        "class": "unclear",
        "rationale": "Neighbors don't address the claim directly.",
        "top_neighbor_id": "a",
    })
    monkeypatch.setattr(nc_mod, "call_sync", _fake_call(completion))
    _stage_retrieval(cache, "it-5", _neighbors("a", "b"))
    out = nc_mod.novelty_classify("h", "it-5")
    assert out["status"] == "passed"
    assert out["result"]["class"] == "unclear"


def test_invalid_top_neighbor_id_is_nulled(cache, monkeypatch):
    completion = json.dumps({
        "class": "rediscovery",
        "rationale": "ok",
        "top_neighbor_id": "not-in-the-list",
    })
    monkeypatch.setattr(nc_mod, "call_sync", _fake_call(completion))
    _stage_retrieval(cache, "it-6", _neighbors("a", "b"))
    out = nc_mod.novelty_classify("h", "it-6")
    assert out["status"] == "passed"
    assert out["result"]["top_neighbor_id"] is None
    assert any("not in retrieved" in e for e in out["errors"])


def test_invalid_class_falls_back_to_unclear(cache, monkeypatch):
    completion = json.dumps({
        "class": "very-novel-much-wow",
        "rationale": "...",
        "top_neighbor_id": None,
    })
    monkeypatch.setattr(nc_mod, "call_sync", _fake_call(completion))
    _stage_retrieval(cache, "it-7", _neighbors("a"))
    out = nc_mod.novelty_classify("h", "it-7")
    assert out["status"] == "passed"
    assert out["result"]["class"] == "unclear"
    assert any("unparseable" in e or "defaulted" in e for e in out["errors"])


def test_unparseable_completion_falls_back_to_unclear(cache, monkeypatch):
    completion = "I think this is novel because reasons."  # no JSON
    monkeypatch.setattr(nc_mod, "call_sync", _fake_call(completion))
    _stage_retrieval(cache, "it-8", _neighbors("a"))
    out = nc_mod.novelty_classify("h", "it-8")
    assert out["status"] == "passed"
    assert out["result"]["class"] == "unclear"
    assert any("unparseable" in e for e in out["errors"])
    assert "novel because reasons" in out["result"]["rationale"]


def test_wrapper_exception_returns_error(cache, monkeypatch):
    def broken(*a, **k):
        raise TimeoutError("vllm timed out")
    monkeypatch.setattr(nc_mod, "call_sync", broken)
    _stage_retrieval(cache, "it-9", _neighbors("a"))
    out = nc_mod.novelty_classify("h", "it-9")
    assert out["status"] == "error"
    assert any("vllm timed out" in e for e in out["errors"])


def test_missing_rationale_defaults_to_empty(cache, monkeypatch):
    completion = json.dumps({"class": "novel", "top_neighbor_id": None})
    monkeypatch.setattr(nc_mod, "call_sync", _fake_call(completion))
    _stage_retrieval(cache, "it-10", _neighbors())
    out = nc_mod.novelty_classify("h", "it-10")
    assert out["status"] == "passed"
    assert out["result"]["class"] == "novel"
    assert out["result"]["rationale"] == ""
    assert any("rationale missing" in e for e in out["errors"])


def test_passes_caller_tag_and_parent(cache, monkeypatch):
    captured = {}
    def stub(messages, **kwargs):
        captured["tag"] = kwargs.get("caller_tag")
        captured["parent"] = kwargs.get("parent_request_id")
        return {
            "request_id": "rid",
            "completion": json.dumps({"class": "novel", "rationale": "r", "top_neighbor_id": None}),
            "model": "gemma",
            "model_version": "test",
            "parent_request_id": kwargs.get("parent_request_id"),
            "caller_tag": kwargs.get("caller_tag"),
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "latency_ms": 1,
        }
    monkeypatch.setattr(nc_mod, "call_sync", stub)
    _stage_retrieval(cache, "it-11", _neighbors("a"))
    nc_mod.novelty_classify("h", "it-11", parent_request_id="par-1")
    assert captured["tag"] == "novelty_classify"
    assert captured["parent"] == "par-1"
