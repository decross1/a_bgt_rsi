"""Source-only chronological diagnostics; do not run during Flash freeze."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from bench.applied_trading import trade_only_baseline as baseline
from bench.applied_trading.public_archive_adapter import ArchiveError


def source_rows() -> list[dict]:
    start = datetime(2026, 7, 17, tzinfo=timezone.utc)
    rows = []
    for index in range(1440):
        hour = start + timedelta(hours=index)
        price = 100 + index * .01 + math.sin(index / 5)
        rows.append({"hour_start_utc": hour.isoformat(),
                     "last_trade_price": price,
                     "buy_aggressor_notional": 100 + index % 10,
                     "sell_aggressor_notional": 90 + index % 7,
                     "signed_flow_imbalance": .15 * math.sin(index / 11)})
    return rows


def test_fixed_calendar_and_exact_4h_embargo_denominators() -> None:
    assert len(baseline.fixed_days()) == 60
    assert baseline.fixed_days()[-1].isoformat() == "2026-09-14"
    rows = source_rows()
    train1, val1 = baseline.make_samples(rows, 1)
    train4, val4 = baseline.make_samples(rows, 4)
    assert (len(train1), len(val1)) == (954, 476)
    assert (len(train4), len(val4)) == (951, 473)
    assert min(row["decision_at"] for row in val1) == baseline.VAL_AFTER_EMBARGO
    assert max(row["label_available_at"] for row in train4) <= baseline.SPLIT_AT
    assert max(row["label_available_at"] for row in val4) <= baseline.END_AT


def test_fixed_ridge_uses_train_scalers_and_scores_all_validation_hours() -> None:
    train, val = baseline.make_samples(source_rows(), 1)
    report, predictions = baseline.score(train, val, horizon=1)
    assert report["validation_scored_rows"] == 476
    assert report["validation_coverage"] == 1
    assert len(predictions) == 476
    assert len(report["day_cluster_mse_improvement_95ci"]) == 2
    assert report["reference_cost"]["historical_executable_L2_or_fill_proven"] is False
    assert report["coefficients"]["baseline"]["feature_count"] == 3
    assert report["coefficients"]["flow_model"]["feature_count"] == 4


def test_missing_first_of_60_days_fails_instead_of_dropping_it(tmp_path) -> None:
    with pytest.raises(ArchiveError, match="missing complete public archive day"):
        baseline.load_days(tmp_path, symbol="BTCUSDT")
