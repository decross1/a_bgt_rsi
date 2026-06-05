"""Tests for the exp004 LLM bundle-bidder.

Stubs ``call_sync`` on the bidder module via monkeypatch — never hits the real
Gemma (mirrors tests/test_hypothesize.py / the exp003 pattern). Covers clean
JSON, JSON-in-prose, and the truthful-default + ``parse_failure:`` paths.
"""
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from experiments.exp004_combinatorial_auction import bidder as bidder_mod


BUNDLE_TUPLES = ((0,), (1,), (0, 1))


def _fake_call_sync(completion_text: str, request_id: str = "req-xyz"):
    """Build a call_sync stub returning a logged record with the given
    completion text. Accepts and ignores all kwargs the bidder passes."""

    def stub(messages, **kwargs):
        return {
            "completion": completion_text,
            "wrapper_request_id": request_id,
        }

    return stub


def _valuation():
    return {(0,): 30.0, (1,): 40.0, (0, 1): 65.0}


def test_clean_json_maps_labels_to_frozen_tuples(monkeypatch):
    completion = json.dumps(
        {"bids": {"A": 30, "B": 40, "AB": 65}, "reasoning": "split the items"}
    )
    monkeypatch.setattr(bidder_mod, "call_sync", _fake_call_sync(completion))

    out = bidder_mod.compute_bundle_bids(_valuation())

    assert set(out["bids"].keys()) == set(BUNDLE_TUPLES)
    for t in BUNDLE_TUPLES:
        assert isinstance(out["bids"][t], float)
    assert out["bids"][(0,)] == 30.0
    assert out["bids"][(1,)] == 40.0
    assert out["bids"][(0, 1)] == 65.0
    assert not out["reasoning"].startswith("parse_failure:")


def test_json_wrapped_in_prose(monkeypatch):
    completion = (
        "Sure, here is my decision.\n"
        '{"bids": {"A": 12.5, "B": 0, "AB": 50}, "reasoning": "bundle is worth more"}\n'
        "Thanks."
    )
    monkeypatch.setattr(bidder_mod, "call_sync", _fake_call_sync(completion))

    out = bidder_mod.compute_bundle_bids(_valuation())

    assert out["bids"] == {(0,): 12.5, (1,): 0.0, (0, 1): 50.0}
    assert all(isinstance(v, float) for v in out["bids"].values())


def test_malformed_completion_yields_truthful_default(monkeypatch):
    completion = "I refuse to emit JSON, here is a paragraph instead."
    monkeypatch.setattr(bidder_mod, "call_sync", _fake_call_sync(completion))

    val = _valuation()
    out = bidder_mod.compute_bundle_bids(val)

    # truthful default: bids == valuation, observable parse_failure reasoning
    assert out["bids"] == {t: float(val[t]) for t in BUNDLE_TUPLES}
    assert out["reasoning"].startswith("parse_failure:")


def test_missing_bids_field_is_parse_failure(monkeypatch):
    completion = json.dumps({"reasoning": "forgot the bids"})
    monkeypatch.setattr(bidder_mod, "call_sync", _fake_call_sync(completion))

    val = _valuation()
    out = bidder_mod.compute_bundle_bids(val)

    assert out["bids"] == {t: float(val[t]) for t in BUNDLE_TUPLES}
    assert out["reasoning"].startswith("parse_failure:")


def test_one_invalid_bundle_bid_is_parse_failure(monkeypatch):
    completion = json.dumps(
        {"bids": {"A": 10, "B": "not-a-number", "AB": 30}, "reasoning": "x"}
    )
    monkeypatch.setattr(bidder_mod, "call_sync", _fake_call_sync(completion))

    val = _valuation()
    out = bidder_mod.compute_bundle_bids(val)

    assert out["bids"] == {t: float(val[t]) for t in BUNDLE_TUPLES}
    assert out["reasoning"].startswith("parse_failure:")


def test_negative_bid_is_parse_failure(monkeypatch):
    completion = json.dumps(
        {"bids": {"A": -5, "B": 40, "AB": 65}, "reasoning": "x"}
    )
    monkeypatch.setattr(bidder_mod, "call_sync", _fake_call_sync(completion))

    val = _valuation()
    out = bidder_mod.compute_bundle_bids(val)

    assert out["bids"] == {t: float(val[t]) for t in BUNDLE_TUPLES}
    assert out["reasoning"].startswith("parse_failure:")


def test_prompt_is_neutral_no_theory_leak(monkeypatch):
    # The probe is only valid if the prompt never names the answer.
    blob = (bidder_mod._SYSTEM_PROMPT + bidder_mod._FORMAT_INSTRUCTION).lower()
    for forbidden in ("truthful", "dominant strategy", "vcg",
                      "report your value", "strategyproof"):
        assert forbidden not in blob


def test_valuation_missing_key_raises(monkeypatch):
    monkeypatch.setattr(bidder_mod, "call_sync", _fake_call_sync("{}"))
    with pytest.raises(ValueError):
        bidder_mod.compute_bundle_bids({(0,): 1.0, (1,): 2.0})


def test_reasoning_truncated(monkeypatch):
    long_reason = "z" * 1000
    completion = json.dumps(
        {"bids": {"A": 1, "B": 2, "AB": 3}, "reasoning": long_reason}
    )
    monkeypatch.setattr(bidder_mod, "call_sync", _fake_call_sync(completion))

    out = bidder_mod.compute_bundle_bids(_valuation())
    assert out["reasoning"].endswith("...[truncated]")
    assert len(out["reasoning"]) <= bidder_mod._REASONING_CHAR_CAP + len("...[truncated]")
