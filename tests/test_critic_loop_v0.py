"""Tests for workers.critic_loop_v0.

Stubs wrapper.call_sync. Covers all four verdicts, schema-consistency
guards (contradicting_paper_id allowed only for falsified/restated),
and the unparseable-output fallback to "survives".
"""
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from workers import critic_loop_v0 as crit_mod


def _fake_call(completion_text: str, request_id: str = "req-crit"):
    def stub(messages, **kwargs):
        return {
            "request_id": request_id,
            "completion": completion_text,
            "model": "gemma-4-26b-a4b",
            "model_version": "test",
            "parent_request_id": kwargs.get("parent_request_id"),
            "caller_tag": kwargs.get("caller_tag"),
            "usage": {"input_tokens": 100, "output_tokens": 60},
            "latency_ms": 100.0,
        }
    return stub


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


def test_empty_hypothesis_errors():
    out = crit_mod.critic_loop_v0("", _neighbors("a"))
    assert out["status"] == "error"


def test_neighbors_must_be_list():
    out = crit_mod.critic_loop_v0("h", "nope")
    assert out["status"] == "error"


def test_survives_verdict(monkeypatch):
    completion = json.dumps({
        "verdict": "survives",
        "rationale": "Nothing in the retrieved set contradicts the claim.",
        "contradicting_paper_id": None,
    })
    monkeypatch.setattr(crit_mod, "call_sync", _fake_call(completion))
    out = crit_mod.critic_loop_v0("h", _neighbors("a", "b"))
    assert out["status"] == "passed"
    assert out["result"]["verdict"] == "survives"
    assert out["result"]["contradicting_paper_id"] is None


def test_falsified_verdict(monkeypatch):
    completion = json.dumps({
        "verdict": "falsified",
        "rationale": "Chunk a contradicts directly.",
        "contradicting_paper_id": "a",
    })
    monkeypatch.setattr(crit_mod, "call_sync", _fake_call(completion))
    out = crit_mod.critic_loop_v0("h", _neighbors("a", "b"))
    assert out["status"] == "passed"
    assert out["result"]["verdict"] == "falsified"
    assert out["result"]["contradicting_paper_id"] == "a"


def test_restated_verdict_with_citation(monkeypatch):
    completion = json.dumps({
        "verdict": "restated",
        "rationale": "Same claim as b.",
        "contradicting_paper_id": "b",
    })
    monkeypatch.setattr(crit_mod, "call_sync", _fake_call(completion))
    out = crit_mod.critic_loop_v0("h", _neighbors("a", "b"))
    assert out["status"] == "passed"
    assert out["result"]["verdict"] == "restated"
    assert out["result"]["contradicting_paper_id"] == "b"


def test_malformed_verdict(monkeypatch):
    completion = json.dumps({
        "verdict": "malformed",
        "rationale": "Not a coherent claim.",
        "contradicting_paper_id": None,
    })
    monkeypatch.setattr(crit_mod, "call_sync", _fake_call(completion))
    out = crit_mod.critic_loop_v0("h", _neighbors())
    assert out["status"] == "passed"
    assert out["result"]["verdict"] == "malformed"


def test_contradicting_paper_id_nulled_on_survives(monkeypatch):
    # Even if the model spuriously emits a citation on `survives`,
    # we null it to match the schema's intent.
    completion = json.dumps({
        "verdict": "survives",
        "rationale": "ok",
        "contradicting_paper_id": "a",
    })
    monkeypatch.setattr(crit_mod, "call_sync", _fake_call(completion))
    out = crit_mod.critic_loop_v0("h", _neighbors("a"))
    assert out["status"] == "passed"
    assert out["result"]["contradicting_paper_id"] is None
    assert any("nulling per schema" in e for e in out["errors"])


def test_contradicting_paper_id_must_be_in_neighbors(monkeypatch):
    completion = json.dumps({
        "verdict": "falsified",
        "rationale": "ok",
        "contradicting_paper_id": "not-in-list",
    })
    monkeypatch.setattr(crit_mod, "call_sync", _fake_call(completion))
    out = crit_mod.critic_loop_v0("h", _neighbors("a", "b"))
    assert out["status"] == "passed"
    assert out["result"]["contradicting_paper_id"] is None
    assert any("not in retrieved" in e for e in out["errors"])


def test_invalid_verdict_falls_back_to_survives(monkeypatch):
    completion = json.dumps({
        "verdict": "definitely-true",
        "rationale": "...",
        "contradicting_paper_id": None,
    })
    monkeypatch.setattr(crit_mod, "call_sync", _fake_call(completion))
    out = crit_mod.critic_loop_v0("h", _neighbors("a"))
    assert out["status"] == "passed"
    assert out["result"]["verdict"] == "survives"  # absence-of-evidence default
    assert any("defaulted" in e or "unparseable" in e for e in out["errors"])


def test_unparseable_completion_falls_back_to_survives(monkeypatch):
    completion = "I cannot find any contradictions in the retrieved literature."
    monkeypatch.setattr(crit_mod, "call_sync", _fake_call(completion))
    out = crit_mod.critic_loop_v0("h", _neighbors("a"))
    assert out["status"] == "passed"
    assert out["result"]["verdict"] == "survives"
    assert any("unparseable" in e for e in out["errors"])
    assert "cannot find" in out["result"]["rationale"]


def test_wrapper_exception_returns_error(monkeypatch):
    def broken(*a, **k):
        raise RuntimeError("vllm crashed")
    monkeypatch.setattr(crit_mod, "call_sync", broken)
    out = crit_mod.critic_loop_v0("h", _neighbors("a"))
    assert out["status"] == "error"
    assert any("vllm crashed" in e for e in out["errors"])


def test_passes_caller_tag(monkeypatch):
    captured = {}
    def stub(messages, **kwargs):
        captured["tag"] = kwargs.get("caller_tag")
        return {
            "request_id": "rid",
            "completion": json.dumps({"verdict": "survives", "rationale": "ok", "contradicting_paper_id": None}),
            "model": "gemma", "model_version": "test",
            "parent_request_id": kwargs.get("parent_request_id"),
            "caller_tag": kwargs.get("caller_tag"),
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "latency_ms": 1,
        }
    monkeypatch.setattr(crit_mod, "call_sync", stub)
    crit_mod.critic_loop_v0("h", _neighbors("a"))
    assert captured["tag"] == "critic_loop_v0"
