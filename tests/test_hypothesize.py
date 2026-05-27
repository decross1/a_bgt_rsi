"""Tests for workers.hypothesize.

Stubs wrapper.call_sync via monkeypatch — never hits the real Gemma.
Exercises the JSON-extraction + validation pipeline against a variety
of completions Gemma might realistically emit (clean JSON, JSON-in-prose,
channel-markup-wrapped JSON, malformed JSON, plain prose).
"""
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from workers import hypothesize as hyp_mod


def _fake_call_sync(completion_text: str, request_id: str = "req-xyz"):
    """Build a call_sync stub returning a logged record with the given
    completion text."""
    def stub(messages, *, temperature=0.0, top_p=1.0, seed=None, max_tokens=None,
             caller_tag="unspecified", parent_request_id=None,
             retrieval_context=None, log_path=None, model=None):
        return {
            "request_id": request_id,
            "completion": completion_text,
            "model": "gemma-4-26b-a4b",
            "model_version": "test",
            "parent_request_id": parent_request_id,
            "caller_tag": caller_tag,
            "usage": {"input_tokens": 100, "output_tokens": 50},
            "latency_ms": 100.0,
        }
    return stub


def test_empty_topic_returns_error():
    out = hyp_mod.hypothesize("")
    assert out["status"] == "error"
    assert any("required" in e for e in out["errors"])


def test_as_stated_env_bypasses_llm_and_returns_topic_verbatim(monkeypatch):
    """HYPOTHESIZE_AS_STATED=1 short-circuits the LLM call — used when the
    user wants the topic tested verbatim (e.g., deliberately-wrong claims
    where hypothesize's rewrite would sanitize the wrongness). Critical:
    no wrapper call is made, so the test patches call_sync to raise if
    invoked — that's the assertion."""
    def must_not_be_called(*a, **kw):
        raise AssertionError("call_sync MUST NOT be called when HYPOTHESIZE_AS_STATED is set")
    monkeypatch.setattr(hyp_mod, "call_sync", must_not_be_called)
    monkeypatch.setenv("HYPOTHESIZE_AS_STATED", "1")
    topic = "Cooperation lock-in observed in repeated PD vs Tit-for-Tat at 100% rate."
    out = hyp_mod.hypothesize(topic, parent_request_id="par-1")
    assert out["status"] == "passed"
    assert out["result"]["text"] == topic
    assert out["result"]["candidates_considered"] == 1
    assert out["result"]["all_candidates"] == [topic]
    assert out["parent_request_id"] == "par-1"
    assert any("HYPOTHESIZE_AS_STATED" in e for e in out["errors"])


def test_as_stated_disabled_when_env_unset(monkeypatch):
    """When the env var is unset / empty / false, hypothesize uses the
    normal LLM path. Patched call_sync must be reached."""
    completion = json.dumps({
        "candidates": ["only one candidate as a sanity check"],
        "chosen": "only one candidate as a sanity check",
    })
    monkeypatch.setattr(hyp_mod, "call_sync", _fake_call_sync(completion))
    monkeypatch.delenv("HYPOTHESIZE_AS_STATED", raising=False)
    out = hyp_mod.hypothesize("a topic")
    assert out["status"] == "passed"
    assert out["result"]["text"] == "only one candidate as a sanity check"
    # And explicit false values are treated as off.
    for falsy in ("", "0", "false", "no"):
        monkeypatch.setenv("HYPOTHESIZE_AS_STATED", falsy)
        monkeypatch.setattr(hyp_mod, "call_sync", _fake_call_sync(completion))
        out = hyp_mod.hypothesize("a topic")
        assert out["result"]["text"] == "only one candidate as a sanity check", falsy


def test_clean_json_with_3_candidates(monkeypatch):
    completion = json.dumps({
        "candidates": [
            "A1: Cooperation rates rise with compute budget below threshold T.",
            "A2: TfT dominance breaks when context window exceeds 8K tokens.",
            "A3: Defection equilibria emerge above a critical reasoning-depth.",
        ],
        "chosen": "A1: Cooperation rates rise with compute budget below threshold T.",
    })
    monkeypatch.setattr(hyp_mod, "call_sync", _fake_call_sync(completion, "req-1"))
    out = hyp_mod.hypothesize("LLM cooperation under compute constraints", parent_request_id="p1")
    assert out["status"] == "passed"
    assert out["wrapper_request_id"] == "req-1"
    assert out["parent_request_id"] == "p1"
    assert out["result"]["candidates_considered"] == 3
    assert len(out["result"]["all_candidates"]) == 3
    assert "A1:" in out["result"]["text"]
    assert out["errors"] == []


def test_clean_json_with_1_candidate(monkeypatch):
    completion = json.dumps({
        "candidates": ["Only one hypothesis worth proposing."],
        "chosen": "Only one hypothesis worth proposing.",
    })
    monkeypatch.setattr(hyp_mod, "call_sync", _fake_call_sync(completion))
    out = hyp_mod.hypothesize("some topic")
    assert out["status"] == "passed"
    assert out["result"]["candidates_considered"] == 1


def test_json_wrapped_in_prose(monkeypatch):
    # Gemma sometimes adds an opening line. Extractor should still find the JSON.
    completion = (
        "Here are the candidates:\n\n"
        + json.dumps({"candidates": ["X"], "chosen": "X"})
        + "\n\nLet me know if you want more."
    )
    monkeypatch.setattr(hyp_mod, "call_sync", _fake_call_sync(completion))
    out = hyp_mod.hypothesize("anything")
    assert out["status"] == "passed"
    assert out["result"]["text"] == "X"


def test_json_with_channel_markup(monkeypatch):
    # Real-world Gemma 4 emits this artifact sometimes (we've seen it).
    completion = (
        "<|channel>thought\n<channel|>\n"
        + json.dumps({"candidates": ["valid hypothesis"], "chosen": "valid hypothesis"})
    )
    monkeypatch.setattr(hyp_mod, "call_sync", _fake_call_sync(completion))
    out = hyp_mod.hypothesize("anything")
    assert out["status"] == "passed"
    assert out["result"]["text"] == "valid hypothesis"


def test_chosen_not_in_candidates_still_promoted(monkeypatch):
    completion = json.dumps({
        "candidates": ["A", "B"],
        "chosen": "C",  # Gemma rephrased instead of copying verbatim
    })
    monkeypatch.setattr(hyp_mod, "call_sync", _fake_call_sync(completion))
    out = hyp_mod.hypothesize("topic")
    assert out["status"] == "passed"
    # chosen is promoted to the front of all_candidates; A/B truncated to fit cap of 3
    assert out["result"]["text"] == "C"
    assert out["result"]["all_candidates"][0] == "C"
    assert "A" in out["result"]["all_candidates"] or "B" in out["result"]["all_candidates"]


def test_malformed_json_falls_back_to_raw(monkeypatch):
    completion = "Cooperation rises with binding compute constraints — but the JSON parser shouldn't find anything balanced here."
    monkeypatch.setattr(hyp_mod, "call_sync", _fake_call_sync(completion))
    out = hyp_mod.hypothesize("topic")
    # Status passed but with annotation
    assert out["status"] == "passed"
    assert any("fell back" in e for e in out["errors"])
    assert "Cooperation rises" in out["result"]["text"]
    assert out["result"]["candidates_considered"] == 1


def test_empty_completion_falls_back_with_placeholder(monkeypatch):
    monkeypatch.setattr(hyp_mod, "call_sync", _fake_call_sync(""))
    out = hyp_mod.hypothesize("topic")
    assert out["status"] == "passed"
    assert "(empty" in out["result"]["text"] or out["result"]["text"]


def test_wrapper_exception_returns_error(monkeypatch):
    def broken(*args, **kwargs):
        raise ConnectionError("vllm unreachable")
    monkeypatch.setattr(hyp_mod, "call_sync", broken)
    out = hyp_mod.hypothesize("topic")
    assert out["status"] == "error"
    assert any("vllm unreachable" in e for e in out["errors"])
    assert out["result"] is None


def test_caps_candidates_at_3(monkeypatch):
    # Gemma went off-script and gave 5; we cap to 3 per the schema.
    completion = json.dumps({
        "candidates": ["A", "B", "C", "D", "E"],
        "chosen": "A",
    })
    monkeypatch.setattr(hyp_mod, "call_sync", _fake_call_sync(completion))
    out = hyp_mod.hypothesize("topic")
    assert out["status"] == "passed"
    assert out["result"]["candidates_considered"] == 3
    assert len(out["result"]["all_candidates"]) == 3


def test_passes_parent_request_id_to_wrapper(monkeypatch):
    captured = {}
    def stub(messages, **kwargs):
        captured["parent"] = kwargs.get("parent_request_id")
        captured["tag"] = kwargs.get("caller_tag")
        return {
            "request_id": "rid",
            "completion": json.dumps({"candidates": ["X"], "chosen": "X"}),
            "model": "gemma",
            "model_version": "test",
            "parent_request_id": kwargs.get("parent_request_id"),
            "caller_tag": kwargs.get("caller_tag"),
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "latency_ms": 1,
        }
    monkeypatch.setattr(hyp_mod, "call_sync", stub)
    hyp_mod.hypothesize("t", parent_request_id="parent-xyz")
    assert captured["parent"] == "parent-xyz"
    assert captured["tag"] == "hypothesize"
