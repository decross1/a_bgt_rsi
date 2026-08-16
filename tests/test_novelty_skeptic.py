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


# --- token starvation fix (D-041 step 1 prerequisite) ------------------------

def test_worker_max_tokens_wide_for_non_default_backend(cache, monkeypatch):
    # Independent (non-default) backends get the WIDE budget — 512 and 2048
    # starved the Qwen reasoning channel (2026-06-09) and 3072 was itself
    # binding by 2026-08-16 (p90 output AT the cap; 31 empty completions
    # across 651 calls). Pinned to the constant AND to the measured floor, so
    # a future retune cannot quietly drop back under the tail.
    # Default backend stays 512 (the non-reasoning Gemma persona).
    captured = {}
    def stub(messages, **kwargs):
        captured["max_tokens"] = kwargs.get("max_tokens")
        return _fake_call(json.dumps({
            "skeptic_class": "novel", "skeptic_rationale": "r",
            "skeptic_top_neighbor_id": None,
        }))(messages, **kwargs)
    monkeypatch.setattr(ns_mod, "call_sync", stub)
    _stage(cache, "it-tok1", _neighbors("a"), gemma_class="novel")
    ns_mod.novelty_skeptic("h", "it-tok1", backend="vllm-qwen")
    assert captured["max_tokens"] == ns_mod.ATTACK_MAX_TOKENS_INDEPENDENT
    assert ns_mod.ATTACK_MAX_TOKENS_INDEPENDENT >= 6144
    _stage(cache, "it-tok2", _neighbors("a"), gemma_class="novel")
    ns_mod.novelty_skeptic("h", "it-tok2", backend=ns_mod.DEFAULT_BACKEND)
    assert captured["max_tokens"] == 512


# =============================================================================
# orchestrator.novelty_skeptic.attack() — independent-skeptic ladder (D-041)
# =============================================================================
# attack() does its OWN retrieval (query_top_k) and its own chat call;
# both are stubbed here. MOCK_LLM is deleted for the live-path tests
# (the shell sets it by default, which would short-circuit to the stub).

from orchestrator import novelty_skeptic as atk_mod


def _attack_json(verdict, doc_id=None, rationale="grounded in chunk a1"):
    return json.dumps({
        "attack_verdict": verdict,
        "rationale": rationale,
        "contradicting_doc_id": doc_id,
    })


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
    monkeypatch.setattr(atk_mod, "query_top_k", stub)


def _stub_attack_call(monkeypatch, completion, captured=None):
    def stub(messages, **kwargs):
        if captured is not None:
            captured["messages"] = messages
            captured.update({k: v for k, v in kwargs.items()})
        return {"request_id": "req-attack", "completion": completion}
    monkeypatch.setattr(atk_mod, "call_sync", stub)


@pytest.fixture
def no_mock(monkeypatch):
    monkeypatch.delenv("MOCK_LLM", raising=False)


def test_attack_mock_llm_stub(monkeypatch):
    # Under MOCK_LLM the stub returns deterministically and touches
    # neither retrieval nor the model.
    monkeypatch.setenv("MOCK_LLM", "1")
    def boom(*a, **k):  # pragma: no cover
        raise AssertionError("network path reached under MOCK_LLM")
    monkeypatch.setattr(atk_mod, "query_top_k", boom)
    monkeypatch.setattr(atk_mod, "call_sync", boom)
    out = atk_mod.attack("h", iteration_id="it-1")
    assert out == {
        "attack_verdict": "inconclusive",
        "rationale": "MOCK_LLM stub",
        "contradicting_doc_id": None,
        "backend": "vllm-qwen",
        "model": "mock",
    }


def test_attack_refuted_parsing(no_mock, monkeypatch):
    _stub_retrieval(monkeypatch, _neighbors("a1", "b1"))
    _stub_attack_call(monkeypatch, _attack_json("refuted", doc_id="a1"))
    out = atk_mod.attack("h")
    assert out["attack_verdict"] == "refuted"
    assert out["contradicting_doc_id"] == "a1"
    # default backend resolves from NARA_SKEPTIC_BACKEND (vllm-qwen, the
    # 2026-06-09 ladder-validated step-1 backend)
    assert out["backend"] == "vllm-qwen"
    assert isinstance(out["model"], str) and out["model"]


def test_attack_survives_parsing(no_mock, monkeypatch):
    _stub_retrieval(monkeypatch, _neighbors("a1"))
    _stub_attack_call(monkeypatch, _attack_json("survives_attack"))
    out = atk_mod.attack("h")
    assert out["attack_verdict"] == "survives_attack"
    assert out["contradicting_doc_id"] is None


def test_attack_inconclusive_parsing(no_mock, monkeypatch):
    _stub_retrieval(monkeypatch, _neighbors("a1"))
    _stub_attack_call(monkeypatch, _attack_json("inconclusive"))
    out = atk_mod.attack("h")
    assert out["attack_verdict"] == "inconclusive"
    assert out["contradicting_doc_id"] is None


def test_attack_unparseable_is_inconclusive_never_survives(no_mock, monkeypatch):
    _stub_retrieval(monkeypatch, _neighbors("a1"))
    _stub_attack_call(monkeypatch, "the claim clearly survives my attack, no JSON here")
    out = atk_mod.attack("h")
    assert out["attack_verdict"] == "inconclusive"
    assert "survives my attack" in out["rationale"]  # raw text preserved


def test_attack_off_enum_verdict_is_inconclusive(no_mock, monkeypatch):
    _stub_retrieval(monkeypatch, _neighbors("a1"))
    _stub_attack_call(monkeypatch, _attack_json("totally-destroyed"))
    out = atk_mod.attack("h")
    assert out["attack_verdict"] == "inconclusive"


def test_attack_refuted_without_valid_doc_id_downgrades(no_mock, monkeypatch):
    # "refuted" citing a doc not in the skeptic's own retrieved set is
    # unverifiable -> inconclusive, never coerced.
    _stub_retrieval(monkeypatch, _neighbors("a1", "b1"))
    _stub_attack_call(monkeypatch, _attack_json("refuted", doc_id="not-retrieved"))
    out = atk_mod.attack("h")
    assert out["attack_verdict"] == "inconclusive"
    assert out["contradicting_doc_id"] is None
    assert "cited no doc_id" in out["rationale"]


def test_attack_refuted_with_null_doc_id_downgrades(no_mock, monkeypatch):
    _stub_retrieval(monkeypatch, _neighbors("a1"))
    _stub_attack_call(monkeypatch, _attack_json("refuted", doc_id=None))
    out = atk_mod.attack("h")
    assert out["attack_verdict"] == "inconclusive"


def test_attack_backend_selection_and_personas(no_mock, monkeypatch):
    # Step 1 (ollama-coder) and step 2 (vllm-gemma) route the backend
    # kwarg through and use DISTINCT system prompts — the gemma persona
    # is visibly adversarial so it is not the critic twice.
    _stub_retrieval(monkeypatch, _neighbors("a1"))
    cap1 = {}
    _stub_attack_call(monkeypatch, _attack_json("survives_attack"), captured=cap1)
    out1 = atk_mod.attack("h", backend="ollama-coder")
    cap2 = {}
    _stub_attack_call(monkeypatch, _attack_json("survives_attack"), captured=cap2)
    out2 = atk_mod.attack("h", backend="vllm-gemma")
    assert cap1["backend"] == "ollama-coder"
    assert cap2["backend"] == "vllm-gemma"
    assert out1["backend"] == "ollama-coder"
    assert out2["backend"] == "vllm-gemma"
    sys1 = cap1["messages"][0]["content"]
    sys2 = cap2["messages"][0]["content"]
    assert sys1 != sys2
    assert "HOSTILE REVIEWER" in sys2
    assert "HOSTILE REVIEWER" not in sys1


def test_attack_token_config(no_mock, monkeypatch):
    # The wide budget for non-default backends (the starvation fix, widened
    # 2026-08-16 to clear the measured tail); 512 on the wrapper default
    # backend.
    _stub_retrieval(monkeypatch, _neighbors("a1"))
    cap = {}
    _stub_attack_call(monkeypatch, _attack_json("survives_attack"), captured=cap)
    atk_mod.attack("h", backend="ollama-coder")
    assert cap["max_tokens"] == atk_mod.ATTACK_MAX_TOKENS_INDEPENDENT
    assert atk_mod.ATTACK_MAX_TOKENS_INDEPENDENT >= 6144
    cap2 = {}
    _stub_attack_call(monkeypatch, _attack_json("survives_attack"), captured=cap2)
    atk_mod.attack("h", backend=atk_mod.DEFAULT_BACKEND)
    assert cap2["max_tokens"] == 512


def test_attack_does_own_retrieval(no_mock, monkeypatch):
    # attack() queries with the hypothesis text and feeds ITS retrieved
    # doc_ids into the prompt; the iteration cache is never read.
    cap_ret, cap_call = {}, {}
    _stub_retrieval(monkeypatch, _neighbors("own-doc-1", "own-doc-2"), captured=cap_ret)
    _stub_attack_call(monkeypatch, _attack_json("survives_attack"), captured=cap_call)
    atk_mod.attack("my hypothesis text", iteration_id="it-42")
    assert cap_ret["query_text"] == "my hypothesis text"
    user_msg = cap_call["messages"][1]["content"]
    assert "own-doc-1" in user_msg and "own-doc-2" in user_msg
    # provenance: the iteration id rides as parent_request_id
    assert cap_call["parent_request_id"] == "it-42"


def test_attack_retrieval_failure_is_inconclusive(no_mock, monkeypatch):
    _stub_retrieval(monkeypatch, [], status="error")
    def boom(*a, **k):  # pragma: no cover
        raise AssertionError("call_sync reached despite failed retrieval")
    monkeypatch.setattr(atk_mod, "call_sync", boom)
    out = atk_mod.attack("h")
    assert out["attack_verdict"] == "inconclusive"
    assert "retrieval" in out["rationale"]


def test_attack_unknown_backend_is_inconclusive(no_mock, monkeypatch):
    def boom(*a, **k):  # pragma: no cover
        raise AssertionError("reached past unknown backend")
    monkeypatch.setattr(atk_mod, "query_top_k", boom)
    monkeypatch.setattr(atk_mod, "call_sync", boom)
    out = atk_mod.attack("h", backend="does-not-exist")
    assert out["attack_verdict"] == "inconclusive"
    assert "unknown skeptic backend" in out["rationale"]


def test_attack_empty_hypothesis_is_inconclusive(no_mock, monkeypatch):
    out = atk_mod.attack("   ")
    assert out["attack_verdict"] == "inconclusive"


def test_attack_wrapper_exception_is_inconclusive(no_mock, monkeypatch):
    _stub_retrieval(monkeypatch, _neighbors("a1"))
    def broken(*a, **k):
        raise TimeoutError("qwen timed out")
    monkeypatch.setattr(atk_mod, "call_sync", broken)
    out = atk_mod.attack("h")
    assert out["attack_verdict"] == "inconclusive"
    assert "qwen timed out" in out["rationale"]
