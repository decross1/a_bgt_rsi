"""Focused tests for nonexecutable REST reference diagnostics."""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

import pytest

from bench.applied_trading import rest_reference_driver as driver
from bench.applied_trading.prospective_hourly_features import _canon, _sha
from bench.applied_trading.public_spot_capture import CaptureError


def topic_raw():
    return _canon({
        "schema": "applied-topic-transfer-draft/v1",
        "application_id": "h1-btcusdt-strategic-liquidity-paper",
        "primary_horizon_hours": 1,
        "prior": {"classification": "known_prior",
                  "mechanism_url": "https://example.org/known-prior"},
        "pipeline_action": {"science_ladder_changed": False,
                            "orders_authorized": False},
    })


def plan(tmp_path):
    collector = tmp_path / "collector.py"
    builder = tmp_path / "builder.py"
    collector.write_bytes(b"closed public collector source\n")
    builder.write_bytes(b"closed hourly builder source\n")
    value = {
        "schema": driver.PLAN_SCHEMA,
        "study_id": "h1-rest-pilot-001",
        "symbol": "BTCUSDT",
        "rule_origin": driver.RULE_ORIGIN,
        "topic_transfer_sha256": _sha(topic_raw()),
        "source": {
            "source_id": "binance-spot-public",
            "collector_source_sha256": _sha(collector.read_bytes()),
            "feature_builder_source_sha256": _sha(builder.read_bytes()),
        },
        "split": {
            "frozen_at": "2026-09-15T00:00:00Z",
            "forward_start": "2026-09-16T00:05:00Z",
            "forward_end": "2026-09-16T04:05:00Z",
        },
        "policy": {
            "hold_s": 3600, "latency_s": 30,
            "entry_timeout_s": 600, "exit_timeout_s": 600,
            "max_quote_receive_delay_s": 30,
            "max_observation_age_s": 300,
            "paper_size_quote": 100,
            "candidate": {
                "intercept_bps": 0, "momentum_weight_bps": 1,
                "flow_weight_bps": 60, "depletion_weight_bps": 80,
                "min_flow": 0.1, "min_depletion": 0.1,
            },
            "baseline": {"intercept_bps": 0, "momentum_weight_bps": 1},
        },
        "cost": {
            "fee_leg_bps": 10, "slippage_leg_bps": 5,
            "double_multiplier": 2, "fee_source_url": driver.FEE_URL,
        },
    }
    return value, collector, builder


def test_frozen_four_hour_plan_and_source_binding(tmp_path):
    value, collector, builder = plan(tmp_path)
    driver.validate_plan(value, collector_source=collector,
                         feature_builder_source=builder)
    collector.write_bytes(b"changed implementation\n")
    with pytest.raises(CaptureError, match="collector implementation changed"):
        driver.validate_plan(value, collector_source=collector,
                             feature_builder_source=builder)


def test_unmatched_momentum_or_late_freeze_rejected(tmp_path):
    value, collector, builder = plan(tmp_path)
    wrong = copy.deepcopy(value)
    wrong["policy"]["baseline"]["momentum_weight_bps"] = 2
    with pytest.raises(CaptureError, match="does not match"):
        driver.validate_plan(wrong, collector_source=collector,
                             feature_builder_source=builder)
    wrong = copy.deepcopy(value)
    wrong["split"]["frozen_at"] = wrong["split"]["forward_start"]
    with pytest.raises(CaptureError, match="unfrozen"):
        driver.validate_plan(wrong, collector_source=collector,
                             feature_builder_source=builder)


def test_public_evaluator_binds_raw_plan_to_effective_settings(tmp_path):
    value, collector, builder = plan(tmp_path)
    old = copy.deepcopy(value)
    old["policy"]["candidate"]["flow_weight_bps"] = 99
    with pytest.raises(CaptureError, match="hash-bound raw plan"):
        driver.evaluate(
            value, batch_paths=[tmp_path / "unused"],
            feature_dir=tmp_path / "unused-features",
            collector_source=collector, feature_builder_source=builder,
            plan_raw=_canon(old), topic_raw=topic_raw())


def test_public_evaluator_binds_known_prior_topic_bytes(tmp_path):
    value, collector, builder = plan(tmp_path)
    with pytest.raises(CaptureError, match="hash-bound transfer"):
        driver.evaluate(
            value, batch_paths=[tmp_path / "unused"],
            feature_dir=tmp_path / "unused-features",
            collector_source=collector, feature_builder_source=builder,
            plan_raw=_canon(value), topic_raw=b"{}\n")


def test_rest_request_must_start_after_boundary(monkeypatch):
    earliest = datetime(2026, 9, 16, 0, 5, 30, tzinfo=timezone.utc)
    early = {"started": earliest - timedelta(seconds=1),
             "received": earliest + timedelta(seconds=1),
             "batch_index": 0, "attempt_index": 0}
    later = {"started": earliest + timedelta(seconds=2),
             "received": earliest + timedelta(seconds=3),
             "batch_index": 0, "attempt_index": 1}
    monkeypatch.setattr(driver, "_quote_receipt", lambda frame, _batches: {
        "ask": 100.0, "ask_size_base": 2.0,
        "bid": 99.9, "bid_size_base": 2.0,
        "quote_id": str(frame["attempt_index"]),
        "sequence_valid": False,
    })
    selected = driver._first_reference_quote(
        [early, later], [], earliest, earliest + timedelta(minutes=1),
        30, side="entry", paper_size_quote=100)
    assert selected["quote_id"] == "1"


@pytest.mark.parametrize("missing_feature", [True, False])
def test_late_seal_cannot_turn_missing_feature_or_exit_into_zero_return(
    tmp_path, monkeypatch, missing_feature,
):
    value, collector, builder = plan(tmp_path)
    at = datetime(2026, 9, 16, 0, 5, tzinfo=timezone.utc)
    end = datetime(2026, 9, 16, 4, 5, tzinfo=timezone.utc)
    seal = end + timedelta(seconds=4200)
    features = []
    for index in range(1 if missing_feature else 4):
        decision = at + timedelta(hours=index)
        features.append({
            "decision_at": decision.isoformat(),
            "hour_end": (decision - timedelta(minutes=5)).isoformat(),
            "available_at": (decision - timedelta(minutes=2)).isoformat(),
            "book_snapshot_available_at": (decision - timedelta(minutes=2)).isoformat(),
            "usable_for_paper_observation": True,
            "rest_depth_has_diff_sequence_proof": False,
            "flow_imbalance": 0.1, "ask_depletion": 0.1,
            "momentum_bps": 0.0 if missing_feature else 100.0,
            "spread_bps": 2.0,
        })
    features_raw = b"".join(_canon(row) for row in features)
    recomputed_source = {
        "schema": "applied-trial-prospective-h1-feature-source/v1",
        "symbol": "BTCUSDT",
        "collector_source_sha256": value["source"]["collector_source_sha256"],
        "feature_builder_source_sha256": value["source"]["feature_builder_source_sha256"],
        "batch_receipts": [{"sha256": "a" * 64, "sealed_at": seal.isoformat()}],
    }
    source = {**recomputed_source, "features_sha256": _sha(features_raw)}
    feature_dir = tmp_path / "features"
    feature_dir.mkdir()
    (feature_dir / "feature-source.json").write_bytes(_canon(source))
    (feature_dir / "features.jsonl").write_bytes(features_raw)
    monkeypatch.setattr(driver, "derive", lambda *_a, **_kw: (
        recomputed_source, features))
    monkeypatch.setattr(driver, "_source_batches", lambda *_a: (
        recomputed_source["batch_receipts"], [], []))
    if not missing_feature:
        monkeypatch.setattr(driver, "_first_reference_quote",
                            lambda _depths, _batches, earliest, _latest,
                            _max_delay, *, side, **_kw: (
                                {"ask": 100.0,
                                 "response_received_at": (earliest + timedelta(seconds=1)).isoformat()}
                                if side == "entry" else None))
    result, cells = driver.evaluate(
        value, batch_paths=[tmp_path / "batch"], feature_dir=feature_dir,
        collector_source=collector, feature_builder_source=builder,
        plan_raw=_canon(value), topic_raw=topic_raw())
    assert len(cells) == result["scheduled_cells"] == 4
    assert result["source_valid_cells"] == (1 if missing_feature else 4)
    assert result["missing_feature_cells"] == (3 if missing_feature else 0)
    assert result["candidate"]["observed_reference_quote_pairs"] == 0
    assert result["candidate"]["net_bps_per_all_scheduled"] is None
    assert result["matched_momentum_baseline"]["net_bps_per_all_scheduled"] is None
    assert result["temporal_window_closed"] is True
    assert result["coverage_complete"] is False
    assert result["status"] == "closed_with_missing_evidence"
    assert result["candidate"]["unknown_outcome_cells"] > 0
    assert result["paper_supported"] is False
    assert result["nonexecutable_reference_only"] is True
    assert result["sequence_valid"] is False
    assert result["orders_placed"] == 0
