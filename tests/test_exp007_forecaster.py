"""Tests for the exp007 LLM probability forecaster.

DESIGN-ONLY paper forecasting; NO live trading (CLAUDE.md CFTC guardrail).

Stubs ``call_sync`` on the forecaster module via monkeypatch — never hits the
real Gemma (mirrors tests/test_exp004_bidder.py / the exp003 pattern). Covers
clean JSON, JSON-in-prose, out-of-range clamping, and the
``prob=0.5 + "parse_failure:"`` path. Runs under MOCK_LLM (default shell).
"""
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from experiments.exp007_polymarket import forecaster as fc_mod


def _fake_call_sync(completion_text: str, request_id: str = "req-007"):
    """Build a call_sync stub returning a logged record with the given
    completion text. Accepts and ignores all kwargs the forecaster passes."""

    def stub(messages, **kwargs):
        return {
            "completion": completion_text,
            "wrapper_request_id": request_id,
        }

    return stub


QUESTION = "Will it rain in Seattle tomorrow?"


def test_clean_json_prob_parsed(monkeypatch):
    completion = json.dumps({"prob": 0.73, "reasoning": "wet season"})
    monkeypatch.setattr(fc_mod, "call_sync", _fake_call_sync(completion))

    out = fc_mod.forecast(QUESTION)

    assert out["prob"] == 0.73
    assert isinstance(out["prob"], float)
    assert out["reasoning"] == "wet season"
    assert not out["reasoning"].startswith("parse_failure:")


def test_json_wrapped_in_prose(monkeypatch):
    completion = (
        "Here is my estimate.\n"
        '{"prob": 0.4, "reasoning": "coin-ish"}\n'
        "Done."
    )
    monkeypatch.setattr(fc_mod, "call_sync", _fake_call_sync(completion))

    out = fc_mod.forecast(QUESTION, context="dry forecast")

    assert out["prob"] == 0.4


def test_prob_above_one_clamped(monkeypatch):
    completion = json.dumps({"prob": 1.5, "reasoning": "overconfident"})
    monkeypatch.setattr(fc_mod, "call_sync", _fake_call_sync(completion))

    out = fc_mod.forecast(QUESTION)

    assert out["prob"] == 1.0
    # clamping is not a parse failure
    assert not out["reasoning"].startswith("parse_failure:")


def test_prob_below_zero_clamped(monkeypatch):
    completion = json.dumps({"prob": -0.2, "reasoning": "impossible"})
    monkeypatch.setattr(fc_mod, "call_sync", _fake_call_sync(completion))

    out = fc_mod.forecast(QUESTION)

    assert out["prob"] == 0.0
    assert not out["reasoning"].startswith("parse_failure:")


def test_malformed_completion_yields_half_and_parse_failure(monkeypatch):
    completion = "I will not emit JSON; here is a paragraph instead."
    monkeypatch.setattr(fc_mod, "call_sync", _fake_call_sync(completion))

    out = fc_mod.forecast(QUESTION)

    assert out["prob"] == 0.5
    assert out["reasoning"].startswith("parse_failure:")


def test_nonnumeric_prob_is_parse_failure(monkeypatch):
    completion = json.dumps({"prob": "very likely", "reasoning": "x"})
    monkeypatch.setattr(fc_mod, "call_sync", _fake_call_sync(completion))

    out = fc_mod.forecast(QUESTION)

    assert out["prob"] == 0.5
    assert out["reasoning"].startswith("parse_failure:")


def test_missing_prob_field_is_parse_failure(monkeypatch):
    completion = json.dumps({"reasoning": "forgot the prob"})
    monkeypatch.setattr(fc_mod, "call_sync", _fake_call_sync(completion))

    out = fc_mod.forecast(QUESTION)

    assert out["prob"] == 0.5
    assert out["reasoning"].startswith("parse_failure:")


def test_reasoning_truncated(monkeypatch):
    long_reason = "z" * 1000
    completion = json.dumps({"prob": 0.5, "reasoning": long_reason})
    monkeypatch.setattr(fc_mod, "call_sync", _fake_call_sync(completion))

    out = fc_mod.forecast(QUESTION)

    assert out["reasoning"].endswith("...[truncated]")
    assert len(out["reasoning"]) <= fc_mod._REASONING_CHAR_CAP + len("...[truncated]")


def test_prompt_makes_no_trading_claim(monkeypatch):
    # Guardrail: the forecaster only forecasts. The prompt must not instruct
    # the model to trade, buy, sell, or place orders.
    blob = (fc_mod._SYSTEM_PROMPT + fc_mod._FORMAT_INSTRUCTION).lower()
    for forbidden in ("place an order", "buy ", "sell ", "wallet", "trade for"):
        assert forbidden not in blob
