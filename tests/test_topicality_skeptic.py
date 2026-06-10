"""orchestrator/topicality_skeptic.py — the R0b independent domain attack.

All tests stub the wrapper; nothing touches a model or the network.
Three seams under test (D-045 residual 1):
  1. attack_topicality() contract — fail-OPEN None on MOCK/empty/unknown-
     backend/wrapper-failure/empty-completion; "unsure" never condemns;
     only the literal "off" condemns.
  2. orchestrator.topicality.check() escalation matrix — the skeptic runs
     ONLY when NARA_TOPICALITY_SKEPTIC=1 AND the primary judge did not
     condemn; only the skeptic's literal "off" escalates (to
     "off_independent"); every skeptic failure leaves the primary verdict
     standing.
  3. workers.retrieval_relevance R0b — "off_independent" condemns like
     "off" but is attributed to the independent skeptic (rule_fired R0b).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from orchestrator import topicality, topicality_skeptic
from workers.retrieval_relevance import relevance


@pytest.fixture()
def no_mock(monkeypatch, tmp_path):
    """Live-path env: MOCK_LLM off, escalation env unset (tests opt in
    explicitly), calls-log paths self-isolated to tmp (never logs/)."""
    monkeypatch.delenv("MOCK_LLM", raising=False)
    monkeypatch.delenv("NARA_TOPICALITY_SKEPTIC", raising=False)
    monkeypatch.delenv("NARA_SKEPTIC_BACKEND", raising=False)
    monkeypatch.setattr(topicality_skeptic, "CALLS_LOG_PATH",
                        str(tmp_path / "calls.jsonl"))
    monkeypatch.setattr(topicality, "CALLS_LOG_PATH",
                        str(tmp_path / "calls.jsonl"))


def _stub_attack(monkeypatch, content):
    # Wrapper records carry `completion` as a plain STRING (the 2026-06-09
    # dict-stub blocker) — never a dict-shaped completion.
    monkeypatch.setattr(topicality_skeptic, "call_sync",
                        lambda *a, **k: {"completion": content})


# --- 1. attack_topicality() contract -----------------------------------------

def test_mock_llm_returns_none(monkeypatch):
    monkeypatch.setenv("MOCK_LLM", "1")
    monkeypatch.setattr(topicality_skeptic, "call_sync",
                        lambda *a, **k: pytest.fail("network under MOCK_LLM"))
    assert topicality_skeptic.attack_topicality("anything") is None


def test_empty_hypothesis_none(no_mock, monkeypatch):
    monkeypatch.setattr(topicality_skeptic, "call_sync",
                        lambda *a, **k: pytest.fail("call_sync on empty input"))
    assert topicality_skeptic.attack_topicality("") is None
    assert topicality_skeptic.attack_topicality("   ") is None
    assert topicality_skeptic.attack_topicality(None) is None  # type: ignore[arg-type]


def test_off_on_unsure_passthrough(no_mock, monkeypatch):
    for d in ("on", "off", "unsure"):
        _stub_attack(
            monkeypatch,
            f'{{"domain": "{d}", "primary_subject": "s", "reason": "r"}}',
        )
        assert topicality_skeptic.attack_topicality("h") == d


def test_unparseable_is_unsure_never_off(no_mock, monkeypatch):
    _stub_attack(monkeypatch, "this is clearly off-domain but not json")
    assert topicality_skeptic.attack_topicality("h") == "unsure"
    _stub_attack(monkeypatch, '{"domain": "banana"}')  # off-enum
    assert topicality_skeptic.attack_topicality("h") == "unsure"
    _stub_attack(monkeypatch, '{"domain": "off" oops not json}')  # broken JSON
    assert topicality_skeptic.attack_topicality("h") == "unsure"


def test_empty_completion_is_none(no_mock, monkeypatch):
    _stub_attack(monkeypatch, "")
    assert topicality_skeptic.attack_topicality("h") is None


def test_wrapper_exception_fail_open_none(no_mock, monkeypatch):
    def boom(*a, **k):
        raise TimeoutError("qwen timed out")
    monkeypatch.setattr(topicality_skeptic, "call_sync", boom)
    assert topicality_skeptic.attack_topicality("h") is None


def test_unknown_backend_fail_open_none(no_mock, monkeypatch):
    # A bad backend name fails OPEN to None — never coerced to the default
    # (rule 4); call_sync must not even be reached.
    monkeypatch.setattr(
        topicality_skeptic, "call_sync",
        lambda *a, **k: pytest.fail("call_sync reached past unknown backend"))
    assert topicality_skeptic.attack_topicality("h", backend="does-not-exist") is None


def test_call_contract(no_mock, monkeypatch):
    # caller_tag/backend/token/temperature pins, and the default backend
    # resolution (NARA_SKEPTIC_BACKEND unset -> vllm-qwen).
    captured = {}
    def stub(messages, **kwargs):
        captured["messages"] = messages
        captured.update(kwargs)
        return {"completion": '{"domain": "off", "primary_subject": "s", "reason": "r"}'}
    monkeypatch.setattr(topicality_skeptic, "call_sync", stub)
    assert topicality_skeptic.attack_topicality("my claim") == "off"
    assert captured["caller_tag"] == "topicality_attack"
    assert captured["backend"] == "vllm-qwen"
    assert captured["max_tokens"] == 3072  # qwen reasoning channel; 512 starves
    assert captured["temperature"] == 0.0
    assert captured["messages"][1]["content"] == "my claim"


def test_env_backend_override(no_mock, monkeypatch):
    monkeypatch.setenv("NARA_SKEPTIC_BACKEND", "vllm-gemma")
    captured = {}
    def stub(messages, **kwargs):
        captured["backend"] = kwargs.get("backend")
        return {"completion": '{"domain": "on", "primary_subject": "s", "reason": "r"}'}
    monkeypatch.setattr(topicality_skeptic, "call_sync", stub)
    assert topicality_skeptic.attack_topicality("h") == "on"
    assert captured["backend"] == "vllm-gemma"


# --- 2. check() escalation matrix (orchestrator/topicality.py wiring) --------

def _stub_primary(monkeypatch, content):
    monkeypatch.setattr(topicality, "call_sync",
                        lambda *a, **k: {"completion": content})


def _spy_skeptic(monkeypatch, ret):
    calls = []
    def spy(text, backend=None):
        calls.append(text)
        return ret
    monkeypatch.setattr(topicality_skeptic, "attack_topicality", spy)
    return calls


def test_check_env_off_no_second_call(no_mock, monkeypatch):
    # Env unset -> primary only; the skeptic must not even be consulted.
    _stub_primary(monkeypatch, '{"domain": "on", "reason": "r"}')
    calls = _spy_skeptic(monkeypatch, "off")
    assert topicality.check("h") == "on"
    assert calls == []


def test_check_primary_off_skips_skeptic(no_mock, monkeypatch):
    # The primary already condemned -> "off" (R0), no second call burned.
    monkeypatch.setenv("NARA_TOPICALITY_SKEPTIC", "1")
    _stub_primary(monkeypatch, '{"domain": "off", "reason": "r"}')
    calls = _spy_skeptic(monkeypatch, "off")
    assert topicality.check("h") == "off"
    assert calls == []


def test_check_primary_on_skeptic_off_returns_off_independent(no_mock, monkeypatch):
    monkeypatch.setenv("NARA_TOPICALITY_SKEPTIC", "1")
    _stub_primary(monkeypatch, '{"domain": "on", "reason": "r"}')
    calls = _spy_skeptic(monkeypatch, "off")
    assert topicality.check("h") == "off_independent"
    assert calls == ["h"]


def test_check_primary_unsure_or_none_skeptic_off_returns_off_independent(
        no_mock, monkeypatch):
    monkeypatch.setenv("NARA_TOPICALITY_SKEPTIC", "1")
    _spy_skeptic(monkeypatch, "off")
    # primary "unsure" — not a condemnation, so the skeptic still gets a shot.
    _stub_primary(monkeypatch, '{"domain": "unsure", "reason": "r"}')
    assert topicality.check("h") == "off_independent"
    # primary None (wrapper failure, fail-open) — likewise escalates.
    def boom(*a, **k):
        raise RuntimeError("backend down")
    monkeypatch.setattr(topicality, "call_sync", boom)
    assert topicality.check("h") == "off_independent"


def test_check_skeptic_non_off_passthrough(no_mock, monkeypatch):
    # Skeptic "on"/"unsure"/None never escalates — the primary verdict stands.
    monkeypatch.setenv("NARA_TOPICALITY_SKEPTIC", "1")
    _stub_primary(monkeypatch, '{"domain": "on", "reason": "r"}')
    for second in ("on", "unsure", None):
        _spy_skeptic(monkeypatch, second)
        assert topicality.check("h") == "on"


def test_check_skeptic_exception_fail_open(no_mock, monkeypatch):
    monkeypatch.setenv("NARA_TOPICALITY_SKEPTIC", "1")
    _stub_primary(monkeypatch, '{"domain": "on", "reason": "r"}')
    def boom(*a, **k):
        raise TimeoutError("qwen down")
    monkeypatch.setattr(topicality_skeptic, "attack_topicality", boom)
    assert topicality.check("h") == "on"


def test_check_mock_llm_short_circuits_before_escalation(monkeypatch):
    # check() keeps its MOCK early-return: even with the gate env on,
    # neither judge runs and the no-signal None comes back.
    monkeypatch.setenv("MOCK_LLM", "1")
    monkeypatch.setenv("NARA_TOPICALITY_SKEPTIC", "1")
    monkeypatch.setattr(topicality, "call_sync",
                        lambda *a, **k: pytest.fail("network under MOCK_LLM"))
    calls = _spy_skeptic(monkeypatch, "off")
    assert topicality.check("h") is None
    assert calls == []


# --- 3. relevance R0b (workers/retrieval_relevance.py wiring) ----------------
# relevance() is PURE — no stubs needed. Healthy on-domain neighbors so the
# lexical rules R1/R2 stay quiet and only the topicality stamp can condemn.

_HYP = "Repeated cooperation strategies with payoff defection dynamics"


def _healthy_neighbors():
    return [
        {"score": 0.70, "chunk_text": "repeated prisoner dilemma cooperation "
         "tit for tat strategies payoff matrix", "source_layer": "foundational"},
        {"score": 0.68, "chunk_text": "folk theorem repeated interaction "
         "cooperation defection punishment", "source_layer": "foundational"},
    ]


def test_relevance_r0b_fires_on_off_independent():
    out = relevance(_healthy_neighbors(), _HYP, topicality="off_independent")
    assert out["low_confidence"] is True
    assert out["category"] == "off_domain"
    assert out["rule_fired"] == "R0b"
    assert out["relevance"] == 0.0
    assert out["topicality"] == "off_independent"
    # The reason must attribute the gate to the INDEPENDENT skeptic and
    # note that the primary judge passed it.
    assert "independent topicality attack" in out["reason"]
    assert "primary judge" in out["reason"]
    # Frozen trio intact (UI join contract).
    assert {"relevance", "low_confidence", "reason"} <= set(out.keys())


def test_relevance_r0_unchanged_for_off():
    out = relevance(_healthy_neighbors(), _HYP, topicality="off")
    assert out["low_confidence"] is True
    assert out["category"] == "off_domain"
    assert out["rule_fired"] == "R0"
    assert out["topicality"] == "off"
    assert "independent" not in out["reason"]


def test_relevance_none_unsure_unchanged():
    for t in ("on", "unsure", None):
        out = relevance(_healthy_neighbors(), _HYP, topicality=t)
        assert out["rule_fired"] not in ("R0", "R0b")
        assert out["low_confidence"] is False
        assert out["topicality"] == t
