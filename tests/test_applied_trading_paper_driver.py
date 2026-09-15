"""Producer-shaped offline tests, deliberately unexecuted during live benchmark."""

from __future__ import annotations

import pytest
from test_applied_trading_trial_contract import manifest, observation, quote

from bench.applied_trading.paper_driver import evaluate
from bench.applied_trading.trial_contract import TrialError


def capture(sealed_at: str = "2026-09-16T01:01:00Z") -> dict:
    return {
        "schema": "applied-trial-capture-receipt/v1",
        "trial_id": "spot-liquidity-test-001",
        "source_id": "binance-spot-public",
        "collector_source_sha256": "a" * 64,
        "observations_sha256": "e" * 64,
        "quotes_sha256": "f" * 64,
        "capture_started_at": "2026-09-14T23:00:00Z",
        "capture_sealed_at": sealed_at,
        "chain_root_sha256": "0" * 64,
    }


def raw_digests() -> dict[str, str]:
    return {
        "manifest.json": "1" * 64,
        "capture-receipt.json": "2" * 64,
        "observations.jsonl": "3" * 64,
        "quotes.jsonl": "4" * 64,
    }


def test_scheduled_denominator_keeps_missing_observations_and_future_cells() -> None:
    value = manifest()
    result, ledger = evaluate(value, capture("2026-09-15T12:00:00Z"), [observation()], [], raw_digests())
    assert len(ledger) == result["scheduled_cells"] == 24
    assert result["run_status"] == "incomplete"
    assert result["disposition"] == "not_tested"
    assert result["future_unissued_cells"] > 0
    assert ledger[0]["candidate"]["status"] == "not_run"
    assert ledger[0]["candidate"]["reason"] == "no_later_valid_entry_quote"


def test_later_bid_ask_and_cost_are_used_for_paper_fill() -> None:
    value = manifest()
    quotes = [
        quote("entry-0001", "2026-09-15T00:00:02Z", 100.0, 100.1),
        quote("exit-0001", "2026-09-15T01:00:02Z", 101.0, 101.1),
    ]
    result, ledger = evaluate(value, capture(), [observation()], quotes, raw_digests())
    row = ledger[0]["candidate"]
    assert row["status"] == "filled_paper"
    assert row["entry_quote_id"] == "entry-0001"
    assert row["exit_quote_id"] == "exit-0001"
    expected = 10_000 * (101.0 / 100.1 - 1) - 24.0
    assert row["paper_net_bps"] == pytest.approx(expected)
    assert row["paper_net_doubled_cost_bps"] == pytest.approx(expected - 24.0)
    assert result["candidate"]["paper_fills"] == 1
    # A positive selected fill with only one valid day never becomes a finding.
    assert result["disposition"] == "not_tested"
    assert result["capture_admission"] == "unverified_external_proof"


def test_decision_cost_kill_blocks_small_directional_move() -> None:
    value = manifest()
    value["policy"]["candidate"]["intercept_bps"] = 1.0
    value["policy"]["candidate"]["flow_weight_bps"] = 0.0
    value["policy"]["candidate"]["depletion_weight_bps"] = 0.0
    value["policy"]["baseline"]["intercept_bps"] = 1.0
    result, ledger = evaluate(value, capture(), [observation()], [], raw_digests())
    assert ledger[0]["candidate"]["status"] == "no_intent"
    assert ledger[0]["candidate"]["decision_cost_floor_bps"] > 20.0
    assert result["candidate"]["paper_fills"] == 0


def test_early_or_invalid_quotes_do_not_fabricate_execution() -> None:
    value = manifest()
    early = quote("early-0001", "2026-09-14T23:59:59Z", 100.0, 100.1)
    invalid = quote("bad-0001", "2026-09-15T00:00:02Z", 100.0, 100.1)
    invalid["sequence_valid"] = False
    result, ledger = evaluate(value, capture(), [observation()], [early, invalid], raw_digests())
    assert ledger[0]["candidate"]["status"] == "not_run"
    assert ledger[0]["candidate"]["reason"] == "no_later_valid_entry_quote"
    assert result["candidate"]["paper_fills"] == 0


def test_late_received_quote_is_not_executable_at_its_old_price() -> None:
    delayed = quote("delayed-0001", "2026-09-15T00:00:02Z", 100.0, 100.1)
    delayed["received_at"] = "2026-09-15T00:00:20Z"
    delayed["available_at"] = "2026-09-15T00:00:20Z"
    _, ledger = evaluate(manifest(), capture(), [observation()], [delayed], raw_digests())
    assert ledger[0]["candidate"]["status"] == "not_run"
    assert ledger[0]["candidate"]["reason"] == "no_later_valid_entry_quote"


def test_depth_request_started_before_latency_cannot_fill_later_slot() -> None:
    row = quote("pre-latency-0001", "2026-09-15T00:00:00Z", 100.0, 100.1)
    row["received_at"] = "2026-09-15T00:00:02Z"
    row["available_at"] = "2026-09-15T00:00:02Z"
    _, ledger = evaluate(manifest(), capture(), [observation()], [row], raw_digests())
    assert ledger[0]["candidate"]["reason"] == "no_later_valid_entry_quote"


def test_invalid_observation_is_counted_not_imputed_as_no_trade_gain() -> None:
    row = observation()
    row["book_valid"] = False
    result, ledger = evaluate(manifest(), capture(), [row], [], raw_digests())
    assert result["invalid_or_stale_observation_cells"] == 1
    assert ledger[0]["source_status"] == "invalid_or_stale_observation"
    assert ledger[0]["no_trade_paper_net_bps"] is None


def test_duplicate_decision_opportunity_cannot_donate_one_source_twice() -> None:
    a = observation()
    b = {**a, "observation_id": "obs-0002"}
    with pytest.raises(TrialError, match="ambiguous"):
        evaluate(manifest(), capture(), [a, b], [], raw_digests())
