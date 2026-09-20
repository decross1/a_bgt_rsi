"""Protocol tests for the hypothesis-generation boundary.

Every model call is stubbed. These tests verify that only a complete,
validated candidate selection can enter the scientific pipeline.
"""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from workers import hypothesize as hyp_mod


def _record(
    completion: str,
    request_id: str = "req-xyz",
    *,
    finish_reason: str | None = "stop",
) -> dict:
    return {
        "request_id": request_id,
        "completion": completion,
        "finish_reason": finish_reason,
        "reasoning_chars": 0,
        "model": "nvidia/Qwen3.8-Flash-Next-NVFP4",
        "model_version": "test",
        "usage": {"input_tokens": 100, "output_tokens": 50},
        "latency_ms": 100.0,
    }


def _sequence_call_sync(*records: dict):
    calls: list[dict] = []
    queue = list(records)

    def stub(messages, **kwargs):
        calls.append({"messages": messages, **kwargs})
        if not queue:
            raise AssertionError("hypothesize exceeded its bounded call count")
        return queue.pop(0)

    stub.calls = calls
    return stub


def _valid(candidate: str = "A testable strategic-interaction hypothesis.") -> str:
    return json.dumps({"candidates": [candidate], "chosen": candidate})


def test_empty_topic_returns_error():
    out = hyp_mod.hypothesize("")
    assert out["status"] == "error"
    assert any("required" in error for error in out["errors"])


def test_as_stated_env_bypasses_llm_and_returns_topic_verbatim(monkeypatch):
    def must_not_be_called(*_args, **_kwargs):
        raise AssertionError("call_sync must not run in evaluate-as-stated mode")

    monkeypatch.setattr(hyp_mod, "call_sync", must_not_be_called)
    monkeypatch.setenv("HYPOTHESIZE_AS_STATED", "1")
    topic = "Cooperation lock-in observed in repeated PD at a 100% rate."
    out = hyp_mod.hypothesize(topic, parent_request_id="par-1")

    assert out["status"] == "passed"
    assert out["result"] == {
        "text": topic,
        "candidates_considered": 1,
        "all_candidates": [topic],
    }
    assert out["parent_request_id"] == "par-1"
    assert any("HYPOTHESIZE_AS_STATED" in error for error in out["errors"])


@pytest.mark.parametrize("value", [None, "", "0", "false", "no"])
def test_as_stated_false_values_use_the_model(monkeypatch, value):
    stub = _sequence_call_sync(_record(_valid()))
    monkeypatch.setattr(hyp_mod, "call_sync", stub)
    if value is None:
        monkeypatch.delenv("HYPOTHESIZE_AS_STATED", raising=False)
    else:
        monkeypatch.setenv("HYPOTHESIZE_AS_STATED", value)

    out = hyp_mod.hypothesize("a topic")

    assert out["status"] == "passed"
    assert len(stub.calls) == 1


def test_clean_json_requires_and_preserves_exact_selection(monkeypatch):
    candidates = [
        "A1: Cooperation rises below threshold T.",
        "A2: Tit-for-tat dominance breaks above 8K context.",
        "A3: Defection emerges above a reasoning-depth threshold.",
    ]
    completion = json.dumps({"candidates": candidates, "chosen": candidates[1]})
    stub = _sequence_call_sync(_record(completion, "req-1"))
    monkeypatch.setattr(hyp_mod, "call_sync", stub)

    out = hyp_mod.hypothesize("LLM cooperation", parent_request_id="p1")

    assert out["status"] == "passed"
    assert out["wrapper_request_id"] == "req-1"
    assert out["parent_request_id"] == "p1"
    assert out["result"] == {
        "text": candidates[1],
        "candidates_considered": 3,
        "all_candidates": candidates,
    }
    assert out["errors"] == []
    assert stub.calls[0]["max_tokens"] == 1024


def test_outer_whitespace_is_normalized_before_selection(monkeypatch):
    completion = json.dumps({"candidates": ["  A testable claim.\n"], "chosen": "A testable claim. "})
    monkeypatch.setattr(hyp_mod, "call_sync", _sequence_call_sync(_record(completion)))

    out = hyp_mod.hypothesize("topic")

    assert out["status"] == "passed"
    assert out["result"]["text"] == "A testable claim."
    assert out["result"]["all_candidates"] == ["A testable claim."]


@pytest.mark.parametrize("candidates", [["A", " A "], ["word " * 81], ["x" * 1201]])
def test_duplicate_or_unbounded_candidates_fail_after_bounded_repair(monkeypatch, candidates):
    completion = json.dumps({"candidates": candidates, "chosen": candidates[0]})
    stub = _sequence_call_sync(_record(completion), _record(completion))
    monkeypatch.setattr(hyp_mod, "call_sync", stub)

    out = hyp_mod.hypothesize("topic")

    assert out["status"] == "error"
    assert out["result"] is None
    assert len(stub.calls) == 2
    assert all("field_schema" in error for error in out["errors"])


def test_complete_json_fence_is_the_only_envelope_tolerated(monkeypatch):
    completion = f"```json\n{_valid('X')}\n```"
    monkeypatch.setattr(
        hyp_mod, "call_sync", _sequence_call_sync(_record(completion))
    )

    out = hyp_mod.hypothesize("anything")

    assert out["status"] == "passed"
    assert out["result"]["text"] == "X"


def test_protocol_words_inside_a_valid_candidate_are_not_leakage(monkeypatch):
    candidate = "Agents receiving the literal token <think> defect more often."
    monkeypatch.setattr(
        hyp_mod, "call_sync", _sequence_call_sync(_record(_valid(candidate)))
    )

    out = hyp_mod.hypothesize("protocol-token signaling game")

    assert out["status"] == "passed"
    assert out["result"]["text"] == candidate


@pytest.mark.parametrize("candidate", ["<think>hidden route</think> Claim.", '{"chosen":"nested"}'])
def test_raw_envelope_inside_a_candidate_cannot_enter_research(monkeypatch, candidate):
    stub = _sequence_call_sync(_record(_valid(candidate)), _record(_valid(candidate)))
    monkeypatch.setattr(hyp_mod, "call_sync", stub)
    out = hyp_mod.hypothesize("topic")
    assert out["status"] == "error"
    assert out["result"] is None
    assert len(stub.calls) == 2


def test_one_bounded_repair_can_recover_protocol_failure(monkeypatch):
    malformed = "Here are some candidates in prose, without the contract."
    stub = _sequence_call_sync(
        _record(malformed, "req-initial"),
        _record(_valid("Repaired candidate."), "req-repair"),
    )
    monkeypatch.setattr(hyp_mod, "call_sync", stub)

    out = hyp_mod.hypothesize("topic", parent_request_id="outer")

    assert out["status"] == "passed"
    assert out["result"]["text"] == "Repaired candidate."
    assert out["wrapper_request_id"] == "req-repair"
    assert any("malformed_json" in error for error in out["errors"])
    assert len(stub.calls) == 2
    assert stub.calls[1]["caller_tag"] == "hypothesize_repair"
    assert stub.calls[1]["parent_request_id"] == "req-initial"
    assert stub.calls[1]["temperature"] == 0.2
    assert stub.calls[1]["max_tokens"] == 1024
    assert malformed not in json.dumps(stub.calls[1]["messages"])


@pytest.mark.parametrize(
    ("completion", "finish_reason", "failure_code"),
    [
        ("Here is JSON: " + _valid("X") + " thanks", "stop", "malformed_json"),
        (
            "<|channel>analysis<channel|>\n" + _valid("X"),
            "stop",
            "reasoning_channel_leakage",
        ),
        ("", "stop", "empty_completion"),
        (_valid("X"), "length", "truncated_completion"),
        (_valid("X"), None, "incomplete_completion"),
        (
            json.dumps({"candidates": ["A", "B"], "chosen": "C"}),
            "stop",
            "field_schema",
        ),
        (
            json.dumps({"candidates": ["A", "B", "C", "D"], "chosen": "A"}),
            "stop",
            "field_schema",
        ),
    ],
)
def test_invalid_output_never_becomes_a_hypothesis(
    monkeypatch, completion, finish_reason, failure_code
):
    stub = _sequence_call_sync(
        _record(completion, "req-1", finish_reason=finish_reason),
        _record(completion, "req-2", finish_reason=finish_reason),
    )
    monkeypatch.setattr(hyp_mod, "call_sync", stub)

    out = hyp_mod.hypothesize("topic")

    assert out["status"] == "error"
    assert out["result"] is None
    assert out["wrapper_request_id"] == "req-2"
    assert len(stub.calls) == 2
    assert all(failure_code in error for error in out["errors"])


@pytest.mark.parametrize(
    "completion,failure_code",
    [
        ('{"candidates":["A"],"chosen":"A","chosen":"B"}', "duplicate_json_key"),
        ('{"candidates":["A","A"],"chosen":"A"}', "field_schema"),
        ('{"candidates":["A"],"chosen":"A","score":NaN}', "non_finite_json"),
    ],
)
def test_ambiguous_or_nonstandard_json_is_rejected(
    monkeypatch, completion, failure_code
):
    stub = _sequence_call_sync(_record(completion), _record(completion))
    monkeypatch.setattr(hyp_mod, "call_sync", stub)

    out = hyp_mod.hypothesize("topic")

    assert out["status"] == "error"
    assert out["result"] is None
    assert all(failure_code in error for error in out["errors"])


def test_wrapper_exception_returns_error_without_hidden_retry(monkeypatch):
    calls = []

    def broken(*args, **kwargs):
        calls.append((args, kwargs))
        raise ConnectionError("model unreachable")

    monkeypatch.setattr(hyp_mod, "call_sync", broken)
    out = hyp_mod.hypothesize("topic")

    assert out["status"] == "error"
    assert out["result"] is None
    assert any("model unreachable" in error for error in out["errors"])
    assert len(calls) == 1


def test_repair_exception_preserves_initial_request_provenance(monkeypatch):
    calls = []

    def stub(messages, **kwargs):
        calls.append({"messages": messages, **kwargs})
        if len(calls) == 1:
            return _record("not json", "req-initial")
        raise TimeoutError("repair deadline")

    monkeypatch.setattr(hyp_mod, "call_sync", stub)
    out = hyp_mod.hypothesize("topic", parent_request_id="outer")

    assert out["status"] == "error"
    assert out["result"] is None
    assert out["wrapper_request_id"] == "req-initial"
    assert out["parent_request_id"] == "outer"
    assert any("repair deadline" in error for error in out["errors"])


def test_passes_parent_request_id_to_initial_wrapper_call(monkeypatch):
    stub = _sequence_call_sync(_record(_valid(), "rid"))
    monkeypatch.setattr(hyp_mod, "call_sync", stub)

    hyp_mod.hypothesize("t", parent_request_id="parent-xyz")

    assert stub.calls[0]["parent_request_id"] == "parent-xyz"
    assert stub.calls[0]["caller_tag"] == "hypothesize"
