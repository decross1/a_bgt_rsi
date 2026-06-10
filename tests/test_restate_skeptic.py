"""Tests for orchestrator.restate_skeptic — the residual-2 restatement
attack (canonicalize -> fresh retrieval + cached-neighbor union ->
transfer-rule judge).

restate_attack() makes TWO call_sync calls (caller_tags
restate_canonicalize then restate_judge) plus its own query_top_k; all
are stubbed here, keyed on caller_tag. The iteration cache is redirected
to tmp by a LOCAL fixture (self-isolated — no reliance on shared
conftest fixtures). MOCK_LLM is deleted for the live-path tests (the
shell sets it by default, which would short-circuit to the stub).
"""
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from orchestrator import restate_skeptic as rs_mod


def _neighbors(*doc_ids: str) -> list[dict]:
    return [
        {
            "doc_id": d,
            "content_hash": f"sha256:{d}",
            "score": 0.7 - 0.05 * i,
            "chunk_text": f"text for {d}",
            "source_layer": "foundational",
            "title": f"title-{d}",
        }
        for i, d in enumerate(doc_ids)
    ]


def _canon_json(statement="In the ultimatum game, responders reject low offers."):
    return json.dumps({
        "canonical_statement": statement,
        "concept_names": ["ultimatum game"],
    })


def _judge_json(verdict, doc_id=None, rationale="chunk a1 states the phenomenon"):
    return json.dumps({
        "restate_verdict": verdict,
        "rationale": rationale,
        "restating_doc_id": doc_id,
    })


@pytest.fixture
def isolated_cache(tmp_path, monkeypatch):
    """Redirect iteration_cache.CACHE_ROOT to a per-test tmp dir (local
    copy of the conftest `cache` fixture so this file self-isolates)."""
    from orchestrator import iteration_cache
    monkeypatch.setattr(iteration_cache, "CACHE_ROOT", tmp_path / "iteration_cache")
    return iteration_cache


@pytest.fixture
def no_mock(monkeypatch):
    monkeypatch.delenv("MOCK_LLM", raising=False)


def _stub_retrieval(monkeypatch, neighbors, status="passed", captured=None):
    def stub(text, k=10, **kwargs):
        if captured is not None:
            captured["query_text"] = text
            captured["k"] = k
        return {
            "status": status,
            "result": {"k": k, "neighbors": neighbors, "latency_ms": 0.1},
            "errors": [],
            "parent_request_id": kwargs.get("parent_request_id"),
        }
    monkeypatch.setattr(rs_mod, "query_top_k", stub)


def _stub_calls(monkeypatch, canonicalize=None, judge=None, captured=None):
    """Stub call_sync keyed on caller_tag. Defaults: a parseable
    canonicalize and a not_restated judge. Pass an Exception instance to
    raise it for that call. `captured` collects kwargs per caller_tag."""
    canonicalize = _canon_json() if canonicalize is None else canonicalize
    judge = _judge_json("not_restated") if judge is None else judge

    def stub(messages, **kwargs):
        tag = kwargs.get("caller_tag")
        if captured is not None:
            captured.setdefault(tag, []).append({"messages": messages, **kwargs})
        completion = canonicalize if tag == "restate_canonicalize" else judge
        if isinstance(completion, Exception):
            raise completion
        return {"request_id": f"req-{tag}", "completion": completion}
    monkeypatch.setattr(rs_mod, "call_sync", stub)


# ── fail-open early exits ────────────────────────────────────────────


def test_mock_stub_inconclusive(monkeypatch):
    # Under MOCK_LLM the stub returns deterministically and touches
    # neither retrieval nor the model.
    monkeypatch.setenv("MOCK_LLM", "1")
    def boom(*a, **k):  # pragma: no cover
        raise AssertionError("network path reached under MOCK_LLM")
    monkeypatch.setattr(rs_mod, "query_top_k", boom)
    monkeypatch.setattr(rs_mod, "call_sync", boom)
    out = rs_mod.restate_attack("h", iteration_id="it-1")
    assert out == {
        "restate_verdict": "inconclusive",
        "rationale": "MOCK_LLM stub",
        "restating_doc_id": None,
        "canonical_statement": None,
        "backend": "vllm-qwen",
        "model": "mock",
    }


def test_empty_hypothesis_inconclusive(no_mock):
    out = rs_mod.restate_attack("   ")
    assert out["restate_verdict"] == "inconclusive"
    assert out["restating_doc_id"] is None


def test_unknown_backend_inconclusive(no_mock, monkeypatch):
    def boom(*a, **k):  # pragma: no cover
        raise AssertionError("reached past unknown backend")
    monkeypatch.setattr(rs_mod, "query_top_k", boom)
    monkeypatch.setattr(rs_mod, "call_sync", boom)
    out = rs_mod.restate_attack("h", backend="does-not-exist")
    assert out["restate_verdict"] == "inconclusive"
    assert "unknown skeptic backend" in out["rationale"]


# ── step 1: canonicalize ─────────────────────────────────────────────


def test_canonicalize_failure_falls_back_to_original_text(no_mock, monkeypatch):
    cap_ret = {}
    _stub_retrieval(monkeypatch, _neighbors("a1"), captured=cap_ret)
    _stub_calls(monkeypatch, canonicalize="no json here at all")
    out = rs_mod.restate_attack("my plain-language claim")
    # retrieval was queried with the RAW hypothesis, not a canonical form
    assert cap_ret["query_text"] == "my plain-language claim"
    assert out["canonical_statement"] is None
    # the fallback is explicit in the rationale
    assert "original claim text" in out["rationale"]
    assert out["restate_verdict"] == "not_restated"


def test_canonicalize_exception_falls_back_to_original_text(no_mock, monkeypatch):
    cap_ret = {}
    _stub_retrieval(monkeypatch, _neighbors("a1"), captured=cap_ret)
    _stub_calls(monkeypatch, canonicalize=TimeoutError("qwen timed out"))
    out = rs_mod.restate_attack("h")
    assert cap_ret["query_text"] == "h"
    assert out["canonical_statement"] is None
    assert "canonicalize call failed" in out["rationale"]
    assert out["restate_verdict"] == "not_restated"


def test_canonicalize_success_drives_retrieval_query(no_mock, monkeypatch):
    cap_ret = {}
    _stub_retrieval(monkeypatch, _neighbors("a1"), captured=cap_ret)
    _stub_calls(monkeypatch)
    out = rs_mod.restate_attack("two players split a sum; lowball offers get rejected")
    assert cap_ret["query_text"] == (
        "In the ultimatum game, responders reject low offers."
    )
    assert out["canonical_statement"] == (
        "In the ultimatum game, responders reject low offers."
    )


# ── step 2: retrieval + neighbor union ───────────────────────────────


def test_retrieval_failure_inconclusive(no_mock, monkeypatch):
    _stub_retrieval(monkeypatch, [], status="error")
    cap = {}
    _stub_calls(monkeypatch, captured=cap)
    out = rs_mod.restate_attack("h")
    assert out["restate_verdict"] == "inconclusive"
    assert "retrieval" in out["rationale"]
    # the judge never ran
    assert "restate_judge" not in cap


def test_novelty_top_neighbor_unioned_into_judge_neighbors(
    no_mock, monkeypatch, isolated_cache
):
    # The fresh query misses the neighbor novelty cited; the cached chunk
    # is appended so the judge SEES it and its doc_id is a VALID citation.
    isolated_cache.write_entry("it-7", "retrieval", {
        "status": "passed",
        "result": {"k": 2, "neighbors": _neighbors("fresh-1", "nov-top")},
        "errors": [],
    })
    cap = {}
    _stub_retrieval(monkeypatch, _neighbors("fresh-1", "fresh-2"))
    _stub_calls(monkeypatch, judge=_judge_json("restated", doc_id="nov-top"),
                captured=cap)
    out = rs_mod.restate_attack(
        "h", iteration_id="it-7", novelty_top_neighbor_id="nov-top",
    )
    judge_user = cap["restate_judge"][0]["messages"][1]["content"]
    assert "nov-top" in judge_user
    assert out["restate_verdict"] == "restated"
    assert out["restating_doc_id"] == "nov-top"


def test_top_neighbor_already_fresh_not_duplicated(
    no_mock, monkeypatch, isolated_cache
):
    isolated_cache.write_entry("it-8", "retrieval", {
        "status": "passed",
        "result": {"k": 1, "neighbors": _neighbors("nov-top")},
        "errors": [],
    })
    cap = {}
    _stub_retrieval(monkeypatch, _neighbors("nov-top", "fresh-2"))
    _stub_calls(monkeypatch, captured=cap)
    rs_mod.restate_attack("h", iteration_id="it-8", novelty_top_neighbor_id="nov-top")
    judge_user = cap["restate_judge"][0]["messages"][1]["content"]
    assert judge_user.count("doc_id='nov-top'") == 1


def test_cache_miss_for_top_neighbor_non_fatal(no_mock, monkeypatch, isolated_cache):
    # No cache entry staged — read_entry raises KeyError; the attack
    # proceeds on the fresh set alone.
    cap = {}
    _stub_retrieval(monkeypatch, _neighbors("fresh-1"))
    _stub_calls(monkeypatch, captured=cap)
    out = rs_mod.restate_attack(
        "h", iteration_id="it-missing", novelty_top_neighbor_id="nov-top",
    )
    assert out["restate_verdict"] == "not_restated"
    judge_user = cap["restate_judge"][0]["messages"][1]["content"]
    assert "nov-top" not in judge_user


# ── step 3: judge parsing + doc_id discipline ────────────────────────


def test_judge_unparseable_inconclusive(no_mock, monkeypatch):
    _stub_retrieval(monkeypatch, _neighbors("a1"))
    _stub_calls(monkeypatch, judge="clearly restated, but no JSON here")
    out = rs_mod.restate_attack("h")
    assert out["restate_verdict"] == "inconclusive"
    assert "unparseable or off-enum" in out["rationale"]


def test_judge_off_enum_inconclusive(no_mock, monkeypatch):
    _stub_retrieval(monkeypatch, _neighbors("a1"))
    _stub_calls(monkeypatch, judge=_judge_json("totally-novel"))
    out = rs_mod.restate_attack("h")
    assert out["restate_verdict"] == "inconclusive"


def test_judge_wrapper_exception_inconclusive(no_mock, monkeypatch):
    _stub_retrieval(monkeypatch, _neighbors("a1"))
    _stub_calls(monkeypatch, judge=TimeoutError("qwen timed out"))
    out = rs_mod.restate_attack("h")
    assert out["restate_verdict"] == "inconclusive"
    assert "qwen timed out" in out["rationale"]


def test_restated_without_valid_doc_id_downgraded_to_inconclusive(
    no_mock, monkeypatch
):
    # "restated" citing a doc not in the judge's candidate set is
    # unverifiable -> inconclusive, never coerced (rule 4).
    _stub_retrieval(monkeypatch, _neighbors("a1", "b1"))
    _stub_calls(monkeypatch, judge=_judge_json("restated", doc_id="not-retrieved"))
    out = rs_mod.restate_attack("h")
    assert out["restate_verdict"] == "inconclusive"
    assert out["restating_doc_id"] is None
    assert "cited no doc_id" in out["rationale"]
    # a null doc_id downgrades the same way
    _stub_calls(monkeypatch, judge=_judge_json("restated", doc_id=None))
    out2 = rs_mod.restate_attack("h")
    assert out2["restate_verdict"] == "inconclusive"


def test_restated_with_in_set_doc_id_returned(no_mock, monkeypatch):
    _stub_retrieval(monkeypatch, _neighbors("a1", "b1"))
    _stub_calls(monkeypatch, judge=_judge_json("restated", doc_id="a1"))
    out = rs_mod.restate_attack("h")
    assert out["restate_verdict"] == "restated"
    assert out["restating_doc_id"] == "a1"
    # default backend resolves from NARA_SKEPTIC_BACKEND (vllm-qwen)
    assert out["backend"] == "vllm-qwen"
    assert isinstance(out["model"], str) and out["model"]


def test_not_restated_nulls_doc_id(no_mock, monkeypatch):
    _stub_retrieval(monkeypatch, _neighbors("a1"))
    _stub_calls(monkeypatch, judge=_judge_json("not_restated", doc_id="a1"))
    out = rs_mod.restate_attack("h")
    assert out["restate_verdict"] == "not_restated"
    assert out["restating_doc_id"] is None


# ── call-shape contract ──────────────────────────────────────────────


def test_call_params_and_caller_tags(no_mock, monkeypatch):
    cap = {}
    _stub_retrieval(monkeypatch, _neighbors("a1"))
    _stub_calls(monkeypatch, captured=cap)
    rs_mod.restate_attack("h", iteration_id="it-42")
    canon = cap["restate_canonicalize"][0]
    judge = cap["restate_judge"][0]
    assert canon["temperature"] == 0.0
    assert canon["max_tokens"] == 3072
    assert canon["parent_request_id"] == "it-42"
    assert canon["backend"] == "vllm-qwen"
    assert judge["temperature"] == 0.2
    assert judge["top_p"] == 0.95
    assert judge["max_tokens"] == 3072
    assert judge["parent_request_id"] == "it-42"
    assert judge["backend"] == "vllm-qwen"
    # the judge prompt carries the transfer rule and both phrasings
    judge_sys = judge["messages"][0]["content"]
    assert "TRANSFER RULE" in judge_sys
    judge_user = judge["messages"][1]["content"]
    assert "Claim (original phrasing):" in judge_user
    assert "Canonical restatement" in judge_user


def test_frozen_result_keys(no_mock, monkeypatch):
    _stub_retrieval(monkeypatch, _neighbors("a1"))
    _stub_calls(monkeypatch, judge=_judge_json("restated", doc_id="a1"))
    out = rs_mod.restate_attack("h")
    assert set(out) == {
        "restate_verdict", "rationale", "restating_doc_id",
        "canonical_statement", "backend", "model",
    }


def test_explicit_backend_kwarg_overrides_env(no_mock, monkeypatch):
    monkeypatch.setenv("NARA_SKEPTIC_BACKEND", "vllm-qwen")
    cap = {}
    _stub_retrieval(monkeypatch, _neighbors("a1"))
    _stub_calls(monkeypatch, captured=cap)
    out = rs_mod.restate_attack("h", backend="vllm-gemma")
    assert cap["restate_canonicalize"][0]["backend"] == "vllm-gemma"
    assert cap["restate_judge"][0]["backend"] == "vllm-gemma"
    assert out["backend"] == "vllm-gemma"
