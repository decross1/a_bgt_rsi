"""Tests for workers.novelty_skeptic.

Stubs wrapper.call_sync; never hits a real model. MOCK_LLM stubs
EMBEDDERS only — the skeptic makes a CHAT completion, so the chat call
MUST be monkeypatched here to stay hermetic (same pattern as
tests/test_novelty_classify.py).

The worker reads BOTH the cached `retrieval` (for neighbors) and the
cached `novelty` (for Gemma's verdict) by `iteration_id`, so each test
stages both via the `cache` fixture (tests/conftest.py).

Backend resolution: the worker calls get_backend(<name>) for the
provenance stamp (.name / .model_version). That reads registered backend
metadata only — it does NOT touch the network — so tests use the real
default "vllm-gemma" registry name.
"""
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from workers import novelty_skeptic as ns_mod


def _fake_call(completion_text: str, request_id: str = "req-skeptic"):
    def stub(messages, **kwargs):
        return {
            "request_id": request_id,
            "completion": completion_text,
            "model": "qwen3.6-27b-nvfp4-mtp",
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


def _stage(cache, iteration_id: str, neighbors: list[dict],
           gemma_class: str = "novel", gemma_rationale: str = "gemma says so",
           gemma_top: str | None = None) -> None:
    """Stage the two cache entries the skeptic consumes: the retrieval
    tool_result (neighbors) and the novelty tool_result (Gemma's verdict),
    exactly as Nara writes them."""
    cache.write_entry(iteration_id, "retrieval", {
        "status": "passed",
        "result": {"k": len(neighbors), "neighbors": neighbors},
        "errors": [],
        "wrapper_request_id": "ret-test",
        "parent_request_id": None,
    })
    cache.write_entry(iteration_id, "novelty", {
        "status": "passed",
        "result": {
            "class": gemma_class,
            "rationale": gemma_rationale,
            "top_neighbor_id": gemma_top,
        },
        "errors": [],
        "wrapper_request_id": "nov-test",
        "parent_request_id": None,
    })


# --- input / cache guards ---------------------------------------------------

def test_empty_hypothesis_errors(cache):
    _stage(cache, "it-1", _neighbors("a"))
    out = ns_mod.novelty_skeptic("", "it-1")
    assert out["status"] == "error"


def test_empty_iteration_id_errors(cache):
    out = ns_mod.novelty_skeptic("h", "")
    assert out["status"] == "error"
    assert any("iteration_id" in e for e in out["errors"])


def test_retrieval_cache_miss_errors(cache):
    # novelty staged but no retrieval.
    cache.write_entry("it-missing-ret", "novelty", {
        "status": "passed",
        "result": {"class": "novel", "rationale": "x", "top_neighbor_id": None},
        "errors": [], "wrapper_request_id": "n", "parent_request_id": None,
    })
    out = ns_mod.novelty_skeptic("h", "it-missing-ret")
    assert out["status"] == "error"
    assert any("cache miss for retrieval" in e for e in out["errors"])


def test_novelty_cache_miss_errors(cache):
    # retrieval staged but no novelty (skeptic needs Gemma's verdict).
    cache.write_entry("it-missing-nov", "retrieval", {
        "status": "passed",
        "result": {"k": 1, "neighbors": _neighbors("a")},
        "errors": [], "wrapper_request_id": "r", "parent_request_id": None,
    })
    out = ns_mod.novelty_skeptic("h", "it-missing-nov")
    assert out["status"] == "error"
    assert any("cache miss for novelty" in e for e in out["errors"])


def test_invalid_cached_gemma_class_errors(cache):
    _stage(cache, "it-badgemma", _neighbors("a"), gemma_class="garbage")
    out = ns_mod.novelty_skeptic("h", "it-badgemma")
    assert out["status"] == "error"
    assert any("novelty.result.class" in e for e in out["errors"])


# --- agree / disagree (the headline signal) ---------------------------------

def test_agreement_true_when_classes_match(cache, monkeypatch):
    completion = json.dumps({
        "skeptic_class": "novel",
        "skeptic_rationale": "No neighbor covers this; concur with the first model.",
        "skeptic_top_neighbor_id": None,
    })
    monkeypatch.setattr(ns_mod, "call_sync", _fake_call(completion))
    _stage(cache, "it-2", _neighbors("a", "b"), gemma_class="novel")
    out = ns_mod.novelty_skeptic("compute-threshold claim", "it-2")
    assert out["status"] == "passed"
    assert out["result"]["skeptic_class"] == "novel"
    assert out["result"]["agreement"] is True
    assert out["errors"] == []


def test_agreement_false_on_dissent(cache, monkeypatch):
    # Gemma said novel; the skeptic downgrades to rediscovery (the
    # integrity-relevant direction — model over-claiming novelty).
    completion = json.dumps({
        "skeptic_class": "rediscovery",
        "skeptic_rationale": "Neighbor a1 already states this; the first model over-claimed novelty.",
        "skeptic_top_neighbor_id": "a1",
    })
    monkeypatch.setattr(ns_mod, "call_sync", _fake_call(completion))
    _stage(cache, "it-3", _neighbors("a1", "b1"), gemma_class="novel")
    out = ns_mod.novelty_skeptic("h", "it-3")
    assert out["status"] == "passed"
    assert out["result"]["skeptic_class"] == "rediscovery"
    assert out["result"]["agreement"] is False
    assert out["result"]["skeptic_top_neighbor_id"] == "a1"


def test_provenance_fields_stamped(cache, monkeypatch):
    completion = json.dumps({
        "skeptic_class": "novel", "skeptic_rationale": "r", "skeptic_top_neighbor_id": None,
    })
    monkeypatch.setattr(ns_mod, "call_sync", _fake_call(completion))
    _stage(cache, "it-prov", _neighbors("a"), gemma_class="novel")
    out = ns_mod.novelty_skeptic("h", "it-prov")
    # Default route is the gemma_persona plumbing backend.
    assert out["result"]["skeptic_backend"] == "vllm-gemma"
    # model_version comes from the resolved backend, not the stub record.
    assert isinstance(out["result"]["skeptic_model_version"], str)
    assert out["result"]["skeptic_model_version"]


def test_independent_backend_is_labelled(cache, monkeypatch):
    # An independent route stamps its own registry name so a consumer can
    # tell a real second opinion from a self-check.
    completion = json.dumps({
        "skeptic_class": "rediscovery", "skeptic_rationale": "r", "skeptic_top_neighbor_id": None,
    })
    monkeypatch.setattr(ns_mod, "call_sync", _fake_call(completion))
    _stage(cache, "it-qwen", _neighbors("a"), gemma_class="novel")
    out = ns_mod.novelty_skeptic("h", "it-qwen", backend="vllm-qwen")
    assert out["result"]["skeptic_backend"] == "vllm-qwen"
    assert out["result"]["skeptic_backend"] != "vllm-gemma"  # not a self-check


def test_unknown_backend_errors_not_coerced(cache, monkeypatch):
    # A bad backend name is a hard error — NOT silently coerced to the
    # default (rule 4 / explicit-fallback discipline). call_sync must not
    # even be reached.
    def boom(*a, **k):  # pragma: no cover - asserts it is never called
        raise AssertionError("call_sync reached despite unknown backend")
    monkeypatch.setattr(ns_mod, "call_sync", boom)
    _stage(cache, "it-badbe", _neighbors("a"))
    out = ns_mod.novelty_skeptic("h", "it-badbe", backend="does-not-exist")
    assert out["status"] == "error"
    assert any("unknown skeptic backend" in e for e in out["errors"])


# --- validation: never coerce a malformed skeptic class ---------------------

def test_invalid_skeptic_class_rejected_falls_back_to_unclear(cache, monkeypatch):
    completion = json.dumps({
        "skeptic_class": "very-novel-much-wow",  # off-enum
        "skeptic_rationale": "...",
        "skeptic_top_neighbor_id": None,
    })
    monkeypatch.setattr(ns_mod, "call_sync", _fake_call(completion))
    _stage(cache, "it-7", _neighbors("a"), gemma_class="novel")
    out = ns_mod.novelty_skeptic("h", "it-7")
    assert out["status"] == "passed"
    assert out["result"]["skeptic_class"] == "unclear"  # not coerced to a near enum
    # gemma said novel, skeptic fell back to unclear -> no false agreement.
    assert out["result"]["agreement"] is False
    assert any("unparseable" in e or "defaulted" in e for e in out["errors"])


def test_unparseable_completion_falls_back_to_unclear(cache, monkeypatch):
    completion = "I think the first model was right, this is novel."  # no JSON
    monkeypatch.setattr(ns_mod, "call_sync", _fake_call(completion))
    _stage(cache, "it-8", _neighbors("a"), gemma_class="novel")
    out = ns_mod.novelty_skeptic("h", "it-8")
    assert out["status"] == "passed"
    assert out["result"]["skeptic_class"] == "unclear"
    assert any("unparseable" in e for e in out["errors"])
    assert "this is novel" in out["result"]["skeptic_rationale"]


def test_fallback_agreement_true_when_gemma_also_unclear(cache, monkeypatch):
    # Fallback class is unclear; if Gemma also said unclear the flag is a
    # genuine match, not a coerced one.
    completion = "garbage no json"
    monkeypatch.setattr(ns_mod, "call_sync", _fake_call(completion))
    _stage(cache, "it-uu", _neighbors("a"), gemma_class="unclear")
    out = ns_mod.novelty_skeptic("h", "it-uu")
    assert out["result"]["skeptic_class"] == "unclear"
    assert out["result"]["agreement"] is True


def test_invalid_top_neighbor_id_is_nulled(cache, monkeypatch):
    completion = json.dumps({
        "skeptic_class": "rediscovery",
        "skeptic_rationale": "ok",
        "skeptic_top_neighbor_id": "not-in-the-list",
    })
    monkeypatch.setattr(ns_mod, "call_sync", _fake_call(completion))
    _stage(cache, "it-6", _neighbors("a", "b"), gemma_class="rediscovery")
    out = ns_mod.novelty_skeptic("h", "it-6")
    assert out["status"] == "passed"
    assert out["result"]["skeptic_top_neighbor_id"] is None
    assert any("not in retrieved" in e for e in out["errors"])


def test_missing_rationale_defaults_to_empty(cache, monkeypatch):
    completion = json.dumps({"skeptic_class": "novel", "skeptic_top_neighbor_id": None})
    monkeypatch.setattr(ns_mod, "call_sync", _fake_call(completion))
    _stage(cache, "it-10", _neighbors(), gemma_class="novel")
    out = ns_mod.novelty_skeptic("h", "it-10")
    assert out["status"] == "passed"
    assert out["result"]["skeptic_class"] == "novel"
    assert out["result"]["skeptic_rationale"] == ""
    assert any("skeptic_rationale missing" in e for e in out["errors"])


def test_wrapper_exception_returns_error(cache, monkeypatch):
    def broken(*a, **k):
        raise TimeoutError("qwen timed out")
    monkeypatch.setattr(ns_mod, "call_sync", broken)
    _stage(cache, "it-9", _neighbors("a"))
    out = ns_mod.novelty_skeptic("h", "it-9")
    assert out["status"] == "error"
    assert any("qwen timed out" in e for e in out["errors"])


def test_passes_caller_tag_parent_and_backend(cache, monkeypatch):
    captured = {}
    def stub(messages, **kwargs):
        captured["tag"] = kwargs.get("caller_tag")
        captured["parent"] = kwargs.get("parent_request_id")
        captured["backend"] = kwargs.get("backend")
        return {
            "request_id": "rid",
            "completion": json.dumps({
                "skeptic_class": "novel", "skeptic_rationale": "r",
                "skeptic_top_neighbor_id": None,
            }),
            "model": "qwen",
            "model_version": "test",
            "parent_request_id": kwargs.get("parent_request_id"),
            "caller_tag": kwargs.get("caller_tag"),
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "latency_ms": 1,
        }
    monkeypatch.setattr(ns_mod, "call_sync", stub)
    _stage(cache, "it-11", _neighbors("a"), gemma_class="novel")
    ns_mod.novelty_skeptic("h", "it-11", parent_request_id="par-1", backend="vllm-qwen")
    assert captured["tag"] == "novelty_skeptic"
    assert captured["parent"] == "par-1"
    assert captured["backend"] == "vllm-qwen"


def test_env_backend_override(cache, monkeypatch):
    # NOVELTY_SKEPTIC_BACKEND selects the route when no kwarg is given,
    # mirroring how critic_loop_v0 reads CRITIC_BACKEND.
    captured = {}
    def stub(messages, **kwargs):
        captured["backend"] = kwargs.get("backend")
        return _fake_call(json.dumps({
            "skeptic_class": "novel", "skeptic_rationale": "r",
            "skeptic_top_neighbor_id": None,
        }))(messages, **kwargs)
    monkeypatch.setattr(ns_mod, "call_sync", stub)
    monkeypatch.setenv("NOVELTY_SKEPTIC_BACKEND", "vllm-qwen")
    _stage(cache, "it-env", _neighbors("a"), gemma_class="novel")
    out = ns_mod.novelty_skeptic("h", "it-env")
    assert captured["backend"] == "vllm-qwen"
    assert out["result"]["skeptic_backend"] == "vllm-qwen"
