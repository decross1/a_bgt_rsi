"""Source-only proposed tests; do not execute during Flash measurement freeze."""

from __future__ import annotations

import pytest

from bench.applied_trading.trial_contract import (
    TrialError,
    strict_json,
    validate_manifest,
    validate_observation,
    validate_quote,
)


def manifest() -> dict:
    return {
        "schema": "applied_trial/v1",
        "trial_id": "spot-liquidity-test-001",
        "trial_type": "spot_liquidity_state",
        "paper_only": True,
        "prior": {"mechanism_id": "cont-order-flow-imbalance", "classification": "known_prior", "url": "https://arxiv.org/abs/1011.6402", "source_campaign_link": None},
        "source": {"venue": "binance_spot_public", "source_id": "binance-spot-public", "symbols": ["BTCUSDT"], "collector_source_sha256": "a" * 64, "development_archive_sha256": "b" * 64, "training_receipt_sha256": "e" * 64, "validation_receipt_sha256": "f" * 64},
        "split": {"development_start": "2026-07-01T00:00:00Z", "development_end": "2026-08-10T00:00:00Z", "validation_start": "2026-08-10T00:00:00Z", "validation_end": "2026-08-30T00:00:00Z", "frozen_at": "2026-09-14T12:00:00Z", "forward_start": "2026-09-15T00:00:00Z", "forward_end": "2026-09-16T00:00:00Z"},
        "policy": {"decision_interval_s": 3600, "hold_s": 3600, "latency_s": 1, "entry_timeout_s": 30, "exit_timeout_s": 30, "max_observation_age_s": 300, "max_quote_receive_delay_s": 5, "paper_size_quote": 100.0, "max_open_positions_per_symbol": 1, "candidate": {"intercept_bps": 40.0, "flow_weight_bps": 20.0, "depletion_weight_bps": 20.0, "momentum_weight_bps": 0.0, "min_flow": 0.2, "min_depletion": 0.2}, "baseline": {"intercept_bps": 40.0, "momentum_weight_bps": 0.0}},
        "cost": {"fee_leg_bps": 10.0, "slippage_leg_bps": 2.0, "double_multiplier": 2, "fee_source_url": "https://www.binance.com/en/support/faq/detail/115000429332"},
        "gates": {"min_valid_forward_days": 10, "min_valid_decision_fraction_per_day": 0.75, "min_fillable_candidate": 10, "min_fillable_days": 5, "min_incremental_net_bps_per_schedule": 0.0},
    }


def observation() -> dict:
    return {
        "schema": "applied-trial-spot-observation/v1",
        "observation_id": "obs-0001",
        "source_id": "binance-spot-public",
        "symbol": "BTCUSDT",
        "decision_at": "2026-09-15T00:00:00Z",
        "timestamp_basis": "local_http_snapshot",
        "venue_event_at": None,
        "request_started_at": "2026-09-14T23:59:58Z",
        "received_at": "2026-09-14T23:59:59Z",
        "available_at": "2026-09-14T23:59:59Z",
        "raw_sha256": "c" * 64,
        "book_valid": True,
        "sequence_valid": True,
        "bid": 100.0,
        "ask": 100.1,
        "flow_imbalance": 0.4,
        "ask_depletion": 0.5,
        "momentum_bps": 1.0,
    }


def quote(quote_id: str, at: str, bid: float, ask: float) -> dict:
    return {
        "schema": "applied-trial-spot-quote/v1",
        "quote_id": quote_id,
        "source_id": "binance-spot-public",
        "symbol": "BTCUSDT",
        "timestamp_basis": "local_http_snapshot",
        "venue_event_at": None,
        "request_started_at": at,
        "received_at": at,
        "available_at": at,
        "raw_sha256": "d" * 64,
        "book_valid": True,
        "sequence_valid": True,
        "bid": bid,
        "ask": ask,
        "bid_size_base": 100.0,
        "ask_size_base": 100.0,
    }


def test_v1_manifest_accepts_cited_prior_and_requires_exact_campaign_match() -> None:
    value = manifest()
    validate_manifest(value)
    value["prior"]["source_campaign_link"] = {"campaign_id": "similar-topic"}
    with pytest.raises(TrialError, match="exact registered shape"):
        validate_manifest(value)
    value["prior"]["source_campaign_link"] = {
        "schema_version": "research-campaign-link/v1",
        "campaign_id": "v2-agentic-game-theory-20260914",
        "campaign_manifest_sha256": "1" * 64,
        "research_question_id": "question-001",
        "research_question_sha256": "2" * 64,
        "topic_id": "topic-001",
        "topic_sha256": "3" * 64,
    }
    with pytest.raises(TrialError, match="unbound campaign"):
        validate_manifest(value)
    validate_manifest(value, campaign_link_matches=lambda link: link == value["prior"]["source_campaign_link"])
    value["prior"]["url"] = "https://papers.example.org/another-known-mechanism"
    validate_manifest(value, campaign_link_matches=lambda link: True)


def test_chronological_freeze_and_spot_fee_floor_are_locked() -> None:
    value = manifest()
    value["split"]["frozen_at"] = "2026-09-15T12:00:00Z"
    with pytest.raises(TrialError, match="chronology"):
        validate_manifest(value)
    value = manifest()
    value["cost"]["fee_leg_bps"] = 0.0
    with pytest.raises(TrialError, match="fee floor"):
        validate_manifest(value)


def test_backup_venue_cannot_enter_with_unmeasured_fee_contract() -> None:
    value = manifest()
    value["source"]["venue"] = "coinbase_advanced_public"
    value["source"]["symbols"] = ["BTC-USD"]
    with pytest.raises(TrialError, match="unregistered public spot venue"):
        validate_manifest(value)


def test_duplicate_json_keys_and_nonfinite_values_fail_closed() -> None:
    with pytest.raises(TrialError, match="duplicate"):
        strict_json(b'{"a":1,"a":2}', "fixture")
    with pytest.raises(TrialError, match="nonfinite"):
        strict_json(b'{"a":NaN}', "fixture")


def test_late_received_feature_cannot_donate_to_earlier_decision() -> None:
    row = observation()
    row["received_at"] = "2026-09-15T00:00:01Z"
    row["available_at"] = "2026-09-15T00:00:01Z"
    with pytest.raises(TrialError, match="available as of"):
        validate_observation(row, manifest())


def test_invalid_book_is_recordable_but_not_usable() -> None:
    row = observation()
    row["book_valid"] = False
    validate_observation(row, manifest())
    row["book_valid"] = "yes"
    with pytest.raises(TrialError, match="malformed"):
        validate_observation(row, manifest())


def test_wrong_source_symbol_or_crossed_quote_rejected() -> None:
    row = quote("quote-0001", "2026-09-15T00:00:02Z", 100.0, 100.1)
    validate_quote(row, manifest())
    row["symbol"] = "ETHUSDT"
    with pytest.raises(TrialError, match="unregistered"):
        validate_quote(row, manifest())
    row = quote("quote-0001", "2026-09-15T00:00:02Z", 101.0, 100.1)
    with pytest.raises(TrialError, match="spread"):
        validate_quote(row, manifest())


def test_local_rest_book_must_not_claim_venue_event_timestamp() -> None:
    row = quote("quote-0001", "2026-09-15T00:00:02Z", 100.0, 100.1)
    row["venue_event_at"] = "2026-09-15T00:00:02Z"
    with pytest.raises(TrialError, match="invent"):
        validate_quote(row, manifest())
