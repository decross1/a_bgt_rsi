"""orchestrator/topicality.py — the R0 LLM domain-judgment helper.

All tests stub the wrapper; nothing touches a model. The contract under
test: None on MOCK/failure (fail-open), "unsure" on unparseable-but-
responsive output, literal enum pass-through otherwise.
"""
from __future__ import annotations

import pytest

from orchestrator import topicality


@pytest.fixture()
def no_mock(monkeypatch):
    monkeypatch.delenv("MOCK_LLM", raising=False)


def _stub(monkeypatch, content):
    # Wrapper records carry `completion` as a plain STRING (the exact shape
    # agent_wrapper/wrapper.py logs) — a dict-shaped stub here previously
    # masked a production-dead R0 (2026-06-09 review blocker).
    monkeypatch.setattr(
        topicality, "call_sync",
        lambda *a, **k: {"completion": content},
    )


def test_mock_llm_short_circuits_to_none(monkeypatch):
    monkeypatch.setenv("MOCK_LLM", "1")
    monkeypatch.setattr(topicality, "call_sync",
                        lambda *a, **k: pytest.fail("network under MOCK_LLM"))
    assert topicality.check("anything") is None


def test_empty_hypothesis_is_none(no_mock):
    assert topicality.check("") is None
    assert topicality.check("   ") is None


def test_on_off_unsure_pass_through(no_mock, monkeypatch):
    for d in ("on", "off", "unsure"):
        _stub(monkeypatch, f'{{"domain": "{d}", "reason": "r"}}')
        assert topicality.check("h") == d


def test_unparseable_json_is_unsure_not_off(no_mock, monkeypatch):
    _stub(monkeypatch, "this is not json at all")
    assert topicality.check("h") == "unsure"
    _stub(monkeypatch, '{"domain": "banana"}')
    assert topicality.check("h") == "unsure"


def test_wrapper_failure_is_none_fail_open(no_mock, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("backend down")
    monkeypatch.setattr(topicality, "call_sync", boom)
    assert topicality.check("h") is None


def test_empty_completion_is_none(no_mock, monkeypatch):
    _stub(monkeypatch, "")
    assert topicality.check("h") is None
