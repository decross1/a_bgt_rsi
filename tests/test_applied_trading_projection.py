"""Closed UI-source proof tests; intentionally not executed during live freeze."""

from __future__ import annotations

import pytest
from test_applied_trading_paper_driver import capture, raw_digests
from test_applied_trading_trial_contract import manifest, observation

from bench.applied_trading.paper_driver import evaluate
from bench.applied_trading.projection import project
from bench.applied_trading.trial_contract import TrialError, sha256


def _bound_result():
    value = manifest()
    result, ledger = evaluate(value, capture(), [observation()], [], raw_digests())
    ledger_data = b"".join(
        __import__("json").dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"
        for row in ledger
    )
    result["paper_ledger_sha256"] = sha256(ledger_data)
    return value, result, ledger


def test_projection_contains_no_raw_quotes_text_or_live_action() -> None:
    value, result, ledger = _bound_result()
    projection = project(value, result, ledger)
    assert projection["paper_only"] is True
    assert projection["live_order_action_available"] is False
    assert projection["prior_classification"] == "known_prior"
    assert "observation_id" not in projection
    assert "entry_quote_id" not in projection
    assert "raw_response" not in projection


def test_cross_trial_or_unbound_ledger_is_excluded() -> None:
    value, result, ledger = _bound_result()
    ledger[0]["trial_id"] = "another-trial"
    with pytest.raises(TrialError, match="cross-trial"):
        project(value, result, ledger)


def test_projection_rejects_promotion_or_incomplete_ledger() -> None:
    value, result, ledger = _bound_result()
    result["promotion_to_science_or_live_orders"] = True
    with pytest.raises(TrialError, match="paper evidence only"):
        project(value, result, ledger)
    value, result, ledger = _bound_result()
    ledger.pop()
    with pytest.raises(TrialError, match="incomplete"):
        project(value, result, ledger)


def test_self_claimed_paper_supported_strings_do_not_admit_ui() -> None:
    value, result, ledger = _bound_result()
    result["disposition"] = "paper_supported"
    result["capture_admission"] = "verified_external"
    result["placebo_admission"] = "passed"
    with pytest.raises(TrialError, match="not integrated"):
        project(value, result, ledger)
