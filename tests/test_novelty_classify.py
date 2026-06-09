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


def _stage_retrieval(
    cache, iteration_id: str, neighbors: list[dict], relevance: dict | None = None
) -> None:
    """Mimic what Nara does after retrieve_literature returns: write the
    full tool_result dict to the cache under the 'retrieval' key."""
    result = {"k": len(neighbors), "neighbors": neighbors}
    if relevance is not None:
        result["relevance"] = relevance
    cache.write_entry(iteration_id, "retrieval", {
        "status": "passed",
        "result": result,
        "errors": [],
        "wrapper_request_id": "ret-test",
        "parent_request_id": None,
    })


def _axes_completion(phenomenon, substrate="na", direction="silent",
                     rationale="grounded reasoning", top="a"):
    return json.dumps({
        "phenomenon": phenomenon,
        "substrate": substrate,
        "predicted_direction": direction,
        "rationale": rationale,
        "top_neighbor_id": top,
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
    # Legacy class-only payload: still accepted (Gemma is stochastic about
    # format), but flagged with a warning and novelty_axes = None.
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
    assert out["result"]["novelty_axes"] is None
    assert any("legacy 'class'" in e for e in out["errors"])


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


# ── two-axis rubric (T1b) ────────────────────────────────────────────


def test_axes_novel_phenomenon_is_novel(cache, monkeypatch):
    completion = _axes_completion("novel", "na", "silent", top=None)
    monkeypatch.setattr(nc_mod, "call_sync", _fake_call(completion))
    _stage_retrieval(cache, "ax-1", _neighbors("a", "b"))
    out = nc_mod.novelty_classify("h", "ax-1")
    assert out["status"] == "passed"
    assert out["result"]["class"] == "novel"
    assert out["result"]["novelty_axes"] == {
        "phenomenon": "novel", "substrate": "na", "predicted_direction": "silent",
    }
    assert out["errors"] == []


def test_axes_known_matches_unstudied_substrate_is_rediscovery(cache, monkeypatch):
    # The iteration-068 case: p-beauty/level-k on Gemma — known phenomenon,
    # unstudied substrate, predicts the published direction. Honest label is
    # the transfer/replication bucket, i.e. legacy class 'rediscovery'.
    completion = _axes_completion("known", "unstudied_llm", "matches", top="a")
    monkeypatch.setattr(nc_mod, "call_sync", _fake_call(completion))
    _stage_retrieval(cache, "ax-2", _neighbors("a", "b"))
    out = nc_mod.novelty_classify("p-beauty level-k on gemma", "ax-2")
    assert out["result"]["class"] == "rediscovery"
    assert out["result"]["novelty_axes"]["substrate"] == "unstudied_llm"
    assert out["result"]["top_neighbor_id"] == "a"


def test_axes_known_silent_is_rediscovery(cache, monkeypatch):
    completion = _axes_completion("known", "studied_llm", "silent", top="a")
    monkeypatch.setattr(nc_mod, "call_sync", _fake_call(completion))
    _stage_retrieval(cache, "ax-3", _neighbors("a"))
    out = nc_mod.novelty_classify("h", "ax-3")
    assert out["result"]["class"] == "rediscovery"


def test_axes_known_deviates_is_novel(cache, monkeypatch):
    completion = _axes_completion("known", "studied_llm", "deviates", top="a")
    monkeypatch.setattr(nc_mod, "call_sync", _fake_call(completion))
    _stage_retrieval(cache, "ax-4", _neighbors("a"))
    out = nc_mod.novelty_classify("h", "ax-4")
    assert out["result"]["class"] == "novel"
    assert out["result"]["novelty_axes"]["predicted_direction"] == "deviates"


def test_axes_incoherent_is_nonsense_with_null_axes(cache, monkeypatch):
    completion = _axes_completion("incoherent", top=None)
    monkeypatch.setattr(nc_mod, "call_sync", _fake_call(completion))
    _stage_retrieval(cache, "ax-5", _neighbors("a"))
    out = nc_mod.novelty_classify("h", "ax-5")
    assert out["result"]["class"] == "nonsense"
    assert out["result"]["novelty_axes"] is None


def test_axes_ambiguous_is_unclear_with_null_axes(cache, monkeypatch):
    completion = _axes_completion("ambiguous", top="a")
    monkeypatch.setattr(nc_mod, "call_sync", _fake_call(completion))
    _stage_retrieval(cache, "ax-6", _neighbors("a"))
    out = nc_mod.novelty_classify("h", "ax-6")
    assert out["result"]["class"] == "unclear"
    assert out["result"]["novelty_axes"] is None


def test_invalid_substrate_defaults_to_na_with_warning(cache, monkeypatch):
    completion = _axes_completion("novel", "quantum_llm", "silent", top="a")
    monkeypatch.setattr(nc_mod, "call_sync", _fake_call(completion))
    _stage_retrieval(cache, "ax-7", _neighbors("a"))
    out = nc_mod.novelty_classify("h", "ax-7")
    assert out["result"]["class"] == "novel"
    assert out["result"]["novelty_axes"]["substrate"] == "na"
    assert any("substrate=" in e for e in out["errors"])


def test_invalid_direction_on_known_fails_closed_to_unclear(cache, monkeypatch):
    completion = _axes_completion("known", "na", "sideways", top="a")
    monkeypatch.setattr(nc_mod, "call_sync", _fake_call(completion))
    _stage_retrieval(cache, "ax-8", _neighbors("a"))
    out = nc_mod.novelty_classify("h", "ax-8")
    assert out["result"]["class"] == "unclear"
    assert out["result"]["novelty_axes"] is None
    assert any("predicted_direction=" in e for e in out["errors"])


def test_axes_top_neighbor_id_still_validated(cache, monkeypatch):
    completion = _axes_completion("known", "na", "matches", top="not-in-list")
    monkeypatch.setattr(nc_mod, "call_sync", _fake_call(completion))
    _stage_retrieval(cache, "ax-9", _neighbors("a", "b"))
    out = nc_mod.novelty_classify("h", "ax-9")
    assert out["result"]["top_neighbor_id"] is None
    assert any("not in retrieved" in e for e in out["errors"])


def test_low_confidence_novel_overridden_to_unclear(cache, monkeypatch):
    completion = _axes_completion("novel", "na", "silent", top=None)
    monkeypatch.setattr(nc_mod, "call_sync", _fake_call(completion))
    _stage_retrieval(cache, "ax-10", _neighbors("a"), relevance={
        "relevance": 0.1, "low_confidence": True,
        "reason": "off-domain retrieval: almost no shared vocabulary",
    })
    out = nc_mod.novelty_classify("h", "ax-10")
    assert out["result"]["class"] == "unclear"
    assert out["result"]["verdict_overridden_from"] == "novel"
    assert "off-domain retrieval" in out["result"]["override_reason"]
    assert out["result"]["low_confidence"] is True
    # The model's axes judgment is preserved; only the class is downgraded.
    assert out["result"]["novelty_axes"]["phenomenon"] == "novel"
    assert any("overridden to 'unclear'" in e for e in out["errors"])


def test_low_confidence_rediscovery_not_overridden(cache, monkeypatch):
    completion = _axes_completion("known", "na", "matches", top="a")
    monkeypatch.setattr(nc_mod, "call_sync", _fake_call(completion))
    _stage_retrieval(cache, "ax-11", _neighbors("a"), relevance={
        "relevance": 0.1, "low_confidence": True, "reason": "thin retrieval",
    })
    out = nc_mod.novelty_classify("h", "ax-11")
    assert out["result"]["class"] == "rediscovery"
    assert "verdict_overridden_from" not in out["result"]


def test_unparseable_fallback_has_null_axes(cache, monkeypatch):
    monkeypatch.setattr(nc_mod, "call_sync", _fake_call("no json at all"))
    _stage_retrieval(cache, "ax-12", _neighbors("a"))
    out = nc_mod.novelty_classify("h", "ax-12")
    assert out["result"]["class"] == "unclear"
    assert out["result"]["novelty_axes"] is None


def test_prompt_carries_two_axis_calibration_rules():
    p = nc_mod.NOVELTY_SYSTEM_PROMPT
    assert "TRANSFER/REPLICATION" in p
    assert "falsity is the critic's job" in p.lower() or "critic's job" in p
    assert "truism" in p
    assert "deterministic code" in p.lower()
