"""Tests for workers.novelty_classify.

Stubs wrapper.call_sync; never hits real Gemma. Exercises the
classification path against the four allowed buckets, malformed
inputs, and edge cases on top_neighbor_id validation.
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


def test_empty_hypothesis_errors():
    out = nc_mod.novelty_classify("", _neighbors("a"))
    assert out["status"] == "error"


def test_neighbors_must_be_a_list():
    out = nc_mod.novelty_classify("h", "not a list")
    assert out["status"] == "error"


def test_novel_classification(monkeypatch):
    completion = json.dumps({
        "class": "novel",
        "rationale": "No retrieved chunk matches the claim about compute thresholds.",
        "top_neighbor_id": None,
    })
    monkeypatch.setattr(nc_mod, "call_sync", _fake_call(completion))
    out = nc_mod.novelty_classify("compute-threshold claim", _neighbors("a", "b"))
    assert out["status"] == "passed"
    assert out["result"]["class"] == "novel"
    assert out["result"]["top_neighbor_id"] is None
    assert out["errors"] == []


def test_rediscovery_classification(monkeypatch):
    completion = json.dumps({
        "class": "rediscovery",
        "rationale": "Chunk a1 states this verbatim.",
        "top_neighbor_id": "a1",
    })
    monkeypatch.setattr(nc_mod, "call_sync", _fake_call(completion))
    out = nc_mod.novelty_classify("h", _neighbors("a1", "b1"))
    assert out["status"] == "passed"
    assert out["result"]["class"] == "rediscovery"
    assert out["result"]["top_neighbor_id"] == "a1"


def test_nonsense_classification(monkeypatch):
    completion = json.dumps({
        "class": "nonsense",
        "rationale": "Not a coherent research question.",
        "top_neighbor_id": None,
    })
    monkeypatch.setattr(nc_mod, "call_sync", _fake_call(completion))
    out = nc_mod.novelty_classify("asdfgh", _neighbors())
    assert out["status"] == "passed"
    assert out["result"]["class"] == "nonsense"


def test_unclear_classification(monkeypatch):
    completion = json.dumps({
        "class": "unclear",
        "rationale": "Neighbors don't address the claim directly.",
        "top_neighbor_id": "a",
    })
    monkeypatch.setattr(nc_mod, "call_sync", _fake_call(completion))
    out = nc_mod.novelty_classify("h", _neighbors("a", "b"))
    assert out["status"] == "passed"
    assert out["result"]["class"] == "unclear"


def test_invalid_top_neighbor_id_is_nulled(monkeypatch):
    completion = json.dumps({
        "class": "rediscovery",
        "rationale": "ok",
        "top_neighbor_id": "not-in-the-list",
    })
    monkeypatch.setattr(nc_mod, "call_sync", _fake_call(completion))
    out = nc_mod.novelty_classify("h", _neighbors("a", "b"))
    assert out["status"] == "passed"
    assert out["result"]["top_neighbor_id"] is None
    assert any("not in retrieved" in e for e in out["errors"])


def test_invalid_class_falls_back_to_unclear(monkeypatch):
    # Model emitted a bucket we don't accept.
    completion = json.dumps({
        "class": "very-novel-much-wow",
        "rationale": "...",
        "top_neighbor_id": None,
    })
    monkeypatch.setattr(nc_mod, "call_sync", _fake_call(completion))
    out = nc_mod.novelty_classify("h", _neighbors("a"))
    assert out["status"] == "passed"
    assert out["result"]["class"] == "unclear"
    assert any("unparseable" in e or "defaulted" in e for e in out["errors"])


def test_unparseable_completion_falls_back_to_unclear(monkeypatch):
    completion = "I think this is novel because reasons."  # no JSON
    monkeypatch.setattr(nc_mod, "call_sync", _fake_call(completion))
    out = nc_mod.novelty_classify("h", _neighbors("a"))
    assert out["status"] == "passed"
    assert out["result"]["class"] == "unclear"
    assert any("unparseable" in e for e in out["errors"])
    # Rationale captures the model's prose for the human to read.
    assert "novel because reasons" in out["result"]["rationale"]


def test_wrapper_exception_returns_error(monkeypatch):
    def broken(*a, **k):
        raise TimeoutError("vllm timed out")
    monkeypatch.setattr(nc_mod, "call_sync", broken)
    out = nc_mod.novelty_classify("h", _neighbors("a"))
    assert out["status"] == "error"
    assert any("vllm timed out" in e for e in out["errors"])


def test_missing_rationale_defaults_to_empty(monkeypatch):
    completion = json.dumps({"class": "novel", "top_neighbor_id": None})
    monkeypatch.setattr(nc_mod, "call_sync", _fake_call(completion))
    out = nc_mod.novelty_classify("h", _neighbors())
    assert out["status"] == "passed"
    assert out["result"]["class"] == "novel"
    assert out["result"]["rationale"] == ""
    assert any("rationale missing" in e for e in out["errors"])


def test_passes_caller_tag_and_parent(monkeypatch):
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
    nc_mod.novelty_classify("h", _neighbors("a"), parent_request_id="par-1")
    assert captured["tag"] == "novelty_classify"
    assert captured["parent"] == "par-1"
