"""Fixed 60-day, trade-only 1h/4h historical horizon diagnostic.

One immutable 40-day development / 20-day validation split and 4-hour embargo.
Official daily aggregate-trade ZIPs are rehashed; missing days/hours fail rather
than disappear. Prices are reference last trades, never executable quotes.
No orders, credentials, paid feeds, model calls, or hyperparameter search.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import public_archive_adapter as archive_source
from .collection_projection import _read_relative
from .public_archive_adapter import SCHEMA as HOURLY_SCHEMA
from .public_archive_adapter import (
    SOURCE_SCHEMA,
    ArchiveError,
    expected_names,
    public_urls,
    validate_checksum,
)
from .public_spot_capture import strict_json

SCHEMA = "applied-trial-trade-only-reference-baseline/v1"
START_DAY = date(2026, 7, 17)
END_DAY = date(2026, 9, 14)
DEV_DAYS = 40
VAL_DAYS = 20
SPLIT_AT = datetime(2026, 8, 26, tzinfo=timezone.utc)
VAL_AFTER_EMBARGO = SPLIT_AT + timedelta(hours=4)
END_AT = datetime(2026, 9, 15, tzinfo=timezone.utc)
HORIZONS = (1, 4)
RIDGE_LAMBDA = 1.0
BOOTSTRAP_SEED = 20260915
BOOTSTRAP_DRAWS = 1000
FEE_LEG_BPS = 10.0
SLIPPAGE_LEG_BPS = 5.0
FEE_URL = "https://www.binance.com/en/support/faq/detail/115000429332"


def _require(ok: bool, reason: str) -> None:
    if not ok:
        raise ArchiveError(reason)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canon(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode() + b"\n"


def _write_new(path: Path, raw: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                 getattr(os, "O_CLOEXEC", 0), 0o600)
    try:
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(fd)


def _utc(value: Any) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ArchiveError("hourly source time is malformed") from exc
    _require(parsed.tzinfo is not None, "hourly source time is timezone-naive")
    return parsed.astimezone(timezone.utc)


def _finite(value: Any, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ArchiveError("historical price/notional is not numeric")
    number = float(value)
    _require(math.isfinite(number) and number >= 0
             and (not positive or number > 0),
             "historical price/notional is nonfinite or nonpositive")
    return number


def _signed(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ArchiveError("historical signed flow is not numeric")
    number = float(value)
    _require(math.isfinite(number) and -1 <= number <= 1,
             "historical signed flow is outside [-1,1]")
    return number


def fixed_days() -> list[date]:
    days = [START_DAY + timedelta(days=index) for index in range(DEV_DAYS + VAL_DAYS)]
    _require(len(days) == 60 and days[-1] == END_DAY,
             "registered historical calendar changed")
    return days


def load_days(root: Path, *, symbol: str) -> tuple[list[dict], list[dict]]:
    """No skipped day/hour: reread ZIP/CHECKSUM and its 24 sealed trade rows."""
    _require(symbol in {"BTCUSDT", "ETHUSDT"} and root.is_dir()
             and not root.is_symlink(), "archive root/symbol is unregistered")
    all_rows = []
    receipts = []
    for day in fixed_days():
        day_dir = root / f"{symbol}-{day.isoformat()}"
        processed = day_dir / "processed"
        _require(day_dir.is_dir() and not day_dir.is_symlink()
                 and processed.is_dir() and not processed.is_symlink(),
                 f"missing complete public archive day {day}")
        zip_name, checksum_name, _ = expected_names(symbol, day)
        zip_path, checksum_path = day_dir / zip_name, day_dir / checksum_name
        _require(zip_path.is_file() and not zip_path.is_symlink()
                 and checksum_path.is_file() and not checksum_path.is_symlink(),
                 f"archive ZIP/CHECKSUM missing or redirected for {day}")
        zip_sha, checksum_sha = validate_checksum(
            zip_path, checksum_path, symbol=symbol, day=day
        )
        receipt_raw = _read_relative(processed, "source-receipt.json", 128_000)
        flow_raw = _read_relative(processed, "hourly-flow.jsonl", 2_000_000)
        fetch_raw = _read_relative(day_dir, "fetch-receipt.json", 128_000)
        receipt = strict_json(receipt_raw)
        fetch = strict_json(fetch_raw)
        _require(isinstance(fetch, dict)
                 and fetch.get("schema")
                    == "applied-trial-binance-archive-public-fetch/v1"
                 and fetch.get("source_id") == "binance-spot-public-archive"
                 and fetch.get("symbol") == symbol
                 and fetch.get("day") == day.isoformat()
                 and fetch.get("urls") == public_urls(symbol, day)
                 and fetch.get("fetcher_source_sha256")
                    == _sha(Path(archive_source.__file__).read_bytes())
                 and fetch.get("zip_sha256") == zip_sha
                 and fetch.get("checksum_raw_sha256") == checksum_sha
                 and fetch.get("processed_source_receipt_sha256") == _sha(receipt_raw)
                 and fetch.get("historical_executable_l2_proven") is False
                 and fetch.get("orders_placed") == 0
                 and fetch.get("credentials_used") is False,
                 f"public HTTPS fetch receipt differs from daily archive for {day}")
        _require(isinstance(receipt, dict)
                 and receipt.get("schema") == SOURCE_SCHEMA
                 and receipt.get("source_id") == "binance-spot-public-archive"
                 and receipt.get("symbol") == symbol
                 and receipt.get("day") == day.isoformat()
                 and receipt.get("urls") == public_urls(symbol, day)
                 and receipt.get("zip_sha256") == zip_sha
                 and receipt.get("checksum_raw_sha256") == checksum_sha
                 and receipt.get("hourly_flow_sha256") == _sha(flow_raw)
                 and receipt.get("hourly_rows") == 24
                 and receipt.get("historical_executable_l2_proven") is False
                 and receipt.get("orders_placed") == 0,
                 f"daily source proof or complete 24-hour coverage differs for {day}")
        lines = flow_raw.splitlines()
        _require(len(lines) == 24, f"daily trade feature hour count differs for {day}")
        for ordinal, line in enumerate(lines):
            row = strict_json(line)
            expected = datetime.combine(day, datetime.min.time(),
                                        tzinfo=timezone.utc) + timedelta(hours=ordinal)
            _require(isinstance(row, dict) and row.get("schema") == HOURLY_SCHEMA
                     and row.get("symbol") == symbol
                     and row.get("raw_archive_zip_sha256") == zip_sha
                     and _utc(row.get("hour_start_utc")) == expected
                     and row.get("trade_event_time_basis") == "venue_trade_event"
                     and row.get("data_available_at_historical_decision")
                        == "not_proven_by_archive"
                     and row.get("historical_executable_quote_available") is False
                     and type(row.get("trade_count")) is int
                     and row["trade_count"] > 0,
                     f"hourly trade row missing, reordered or claiming quotes for {day}")
            for key in ("first_trade_price", "last_trade_price"):
                _finite(row.get(key), positive=True)
            for key in ("buy_aggressor_notional", "sell_aggressor_notional"):
                _finite(row.get(key))
            _signed(row.get("signed_flow_imbalance"))
            all_rows.append(row)
        receipts.append({"day": day.isoformat(),
                         "fetch_receipt_sha256": _sha(fetch_raw),
                         "source_receipt_sha256": _sha(receipt_raw),
                         "hourly_flow_sha256": _sha(flow_raw),
                         "zip_sha256": zip_sha,
                         "checksum_raw_sha256": checksum_sha,
                         "hourly_rows": 24, "missing_hours": 0})
    _require(len(all_rows) == 1440 and len(receipts) == 60,
             "60-day source has a cherry-picked or missing row")
    return all_rows, receipts


def make_samples(rows: list[dict], horizon: int) -> tuple[list[dict], list[dict]]:
    """Features lag at least one full hour; labels use subsequent last trades."""
    _require(horizon in HORIZONS and len(rows) == 1440,
             "fixed historical horizon/coverage changed")
    prices = [_finite(row["last_trade_price"], positive=True) for row in rows]
    volume = [math.log1p(_finite(row["buy_aggressor_notional"]) +
                         _finite(row["sell_aggressor_notional"])) for row in rows]
    flow = [float(row["signed_flow_imbalance"]) for row in rows]
    times = [_utc(row["hour_start_utc"]) for row in rows]
    _require(all(times[i + 1] - times[i] == timedelta(hours=1)
                 for i in range(len(times) - 1)),
             "historical rows are not a continuous hourly source")
    sample_rows = []
    for index in range(5, len(rows) - horizon):
        # Every input is from an earlier *closed* archive hour than the index
        # used as reference price. No future label is in model features.
        lag_return = 10_000 * math.log(prices[index - 1] / prices[index - 2])
        past_four = [10_000 * math.log(prices[index - k] / prices[index - k - 1])
                     for k in range(1, 5)]
        lag_vol = math.sqrt(sum(item * item for item in past_four) / 4)
        outcome = 10_000 * math.log(prices[index + horizon] / prices[index])
        features = [lag_return, lag_vol, volume[index - 1], flow[index - 1]]
        sample_rows.append({"hour": times[index],
                            "decision_at": times[index] + timedelta(hours=1),
                            "label_available_at": times[index + horizon]
                                + timedelta(hours=1),
                            "features": features, "label_bps": outcome,
                            "day": times[index].date().isoformat()})
    dev = [row for row in sample_rows
           if row["decision_at"] < SPLIT_AT
           and row["label_available_at"] <= SPLIT_AT]
    val = [row for row in sample_rows
           if VAL_AFTER_EMBARGO <= row["decision_at"]
           and row["label_available_at"] <= END_AT]
    expected_dev = 960 - 5 - horizon
    expected_val = 480 - 3 - horizon
    _require(len(dev) == expected_dev and len(val) == expected_val,
             "predeclared dev/embargo/end-horizon denominator changed")
    return dev, val


def _solve(matrix: list[list[float]], values: list[float]) -> list[float]:
    width = len(values)
    augmented = [matrix[i][:] + [values[i]] for i in range(width)]
    for pivot in range(width):
        row = max(range(pivot, width), key=lambda i: abs(augmented[i][pivot]))
        augmented[pivot], augmented[row] = augmented[row], augmented[pivot]
        divisor = augmented[pivot][pivot]
        _require(abs(divisor) > 1e-12, "fixed ridge system is singular")
        augmented[pivot] = [item / divisor for item in augmented[pivot]]
        for other in range(width):
            if other != pivot:
                scale = augmented[other][pivot]
                augmented[other] = [augmented[other][col] -
                                    scale * augmented[pivot][col]
                                    for col in range(width + 1)]
    return [augmented[i][-1] for i in range(width)]


def fit_fixed_ridge(train: list[dict], *, with_flow: bool) -> dict:
    _require(len(train) >= 100, "fixed ridge needs full development coverage")
    feature_count = 4 if with_flow else 3
    means = [sum(row["features"][j] for row in train) / len(train)
             for j in range(feature_count)]
    scales = [math.sqrt(sum((row["features"][j] - means[j]) ** 2
                            for row in train) / len(train)) or 1.0
              for j in range(feature_count)]
    width = feature_count + 1
    matrix = [[0.0] * width for _ in range(width)]
    values = [0.0] * width
    for row in train:
        x = [1.0] + [(row["features"][j] - means[j]) / scales[j]
                     for j in range(feature_count)]
        y = row["label_bps"]
        for i in range(width):
            values[i] += x[i] * y
            for j in range(width):
                matrix[i][j] += x[i] * x[j]
    for j in range(1, width):
        matrix[j][j] += RIDGE_LAMBDA
    coefficients = _solve(matrix, values)
    _require(all(math.isfinite(item) for item in coefficients),
             "frozen ridge produced a nonfinite coefficient")
    return {"ridge_lambda": RIDGE_LAMBDA, "feature_count": feature_count,
            "training_rows": len(train), "means": means,
            "scales": scales, "coefficients": coefficients,
            "feature_names": ["lagged_return_bps", "lagged_four_hour_vol_bps",
                              "lagged_log_notional"] +
                (["lagged_signed_taker_flow"] if with_flow else [])}


def predict(model: dict, row: dict) -> float:
    x = [1.0] + [(row["features"][j] - model["means"][j]) / model["scales"][j]
                 for j in range(model["feature_count"])]
    return sum(coefficient * feature for coefficient, feature
               in zip(model["coefficients"], x, strict=True))


def _day_bootstrap(deltas: list[dict], key: str) -> list[float]:
    by_day: dict[str, list[float]] = {}
    for row in deltas:
        by_day.setdefault(row["day"], []).append(row[key])
    _require(len(by_day) == VAL_DAYS and all(by_day.values()),
             "validation uncertainty lost a predeclared day cluster")
    day_means = [sum(values) / len(values)
                 for _, values in sorted(by_day.items())]
    rng = random.Random(BOOTSTRAP_SEED + (1 if key == "mse_improvement" else 2))
    draws = sorted(sum(rng.choice(day_means) for _ in day_means) / len(day_means)
                   for _ in range(BOOTSTRAP_DRAWS))
    return [draws[int(.025 * (BOOTSTRAP_DRAWS - 1))],
            draws[int(.975 * (BOOTSTRAP_DRAWS - 1))]]


def score(train: list[dict], val: list[dict], *, horizon: int) -> tuple[dict, list[dict]]:
    baseline = fit_fixed_ridge(train, with_flow=False)
    enhanced = fit_fixed_ridge(train, with_flow=True)
    source_rows = []
    roundtrip = 2 * (FEE_LEG_BPS + SLIPPAGE_LEG_BPS)
    for row in val:
        base = predict(baseline, row)
        added = predict(enhanced, row)
        actual = row["label_bps"]
        mse_base = (actual - base) ** 2
        mse_added = (actual - added) ** 2
        sign_base = (base >= 0) == (actual >= 0)
        sign_added = (added >= 0) == (actual >= 0)
        source_rows.append({"hour": row["hour"].isoformat(), "day": row["day"],
                            "decision_at": row["decision_at"].isoformat(),
                            "horizon_hours": horizon,
                            "actual_reference_return_bps": actual,
                            "baseline_predicted_bps": base,
                            "flow_model_predicted_bps": added,
                            "mse_improvement": mse_base - mse_added,
                            "direction_improvement": int(sign_added) - int(sign_base),
                            "baseline_reference_net_bps":
                                actual - roundtrip if base > roundtrip else 0.0,
                            "flow_reference_net_bps":
                                actual - roundtrip if added > roundtrip else 0.0,
                            "baseline_doubled_reference_net_bps":
                                actual - 2 * roundtrip if base > 2 * roundtrip else 0.0,
                            "flow_doubled_reference_net_bps":
                                actual - 2 * roundtrip if added > 2 * roundtrip else 0.0})
    n = len(val)
    _require(n == 480 - 3 - horizon, "validation score dropped an eligible hour")
    def average(key: str) -> float:
        return sum(row[key] for row in source_rows) / n
    base_mse = sum((row["actual_reference_return_bps"] -
                    row["baseline_predicted_bps"]) ** 2 for row in source_rows) / n
    flow_mse = sum((row["actual_reference_return_bps"] -
                    row["flow_model_predicted_bps"]) ** 2 for row in source_rows) / n
    base_direction = sum((row["baseline_predicted_bps"] >= 0) ==
                         (row["actual_reference_return_bps"] >= 0)
                         for row in source_rows) / n
    flow_direction = sum((row["flow_model_predicted_bps"] >= 0) ==
                         (row["actual_reference_return_bps"] >= 0)
                         for row in source_rows) / n
    report = {"horizon_hours": horizon,
              "development_train_rows": len(train),
              "validation_eligible_rows": n, "validation_scored_rows": n,
              "validation_coverage": 1.0,
              "embargo_hours": 4, "end_horizon_excluded_hours": horizon,
              "baseline_mse_bps2": base_mse, "flow_model_mse_bps2": flow_mse,
              "mse_improvement_bps2": average("mse_improvement"),
              "day_cluster_mse_improvement_95ci":
                  _day_bootstrap(source_rows, "mse_improvement"),
              "baseline_directional_accuracy": base_direction,
              "flow_model_directional_accuracy": flow_direction,
              "directional_improvement": average("direction_improvement"),
              "day_cluster_directional_improvement_95ci":
                  _day_bootstrap(source_rows, "direction_improvement"),
              "reference_cost": {"fee_leg_bps": FEE_LEG_BPS,
                                 "slippage_leg_bps_assumed": SLIPPAGE_LEG_BPS,
                                 "roundtrip_bps_assumed": roundtrip,
                                 "doubled_roundtrip_bps_assumed": 2 * roundtrip,
                                 "fee_source_url": FEE_URL,
                                 "historical_executable_L2_or_fill_proven": False},
              "reference_net_bps_per_eligible_hour": {
                  "no_trade": 0.0,
                  "baseline": average("baseline_reference_net_bps"),
                  "flow_model": average("flow_reference_net_bps"),
                  "baseline_doubled": average("baseline_doubled_reference_net_bps"),
                  "flow_model_doubled": average("flow_doubled_reference_net_bps")},
              "coefficients": {"baseline": baseline, "flow_model": enhanced},
              "reference_only_no_trading_edge_claim": True}
    return report, source_rows


def run(root: Path, *, symbol: str, output: Path) -> dict:
    _require(not output.exists() and output.parent.is_dir()
             and not output.parent.is_symlink(),
             "reference result must be a new regular direct child")
    rows, per_day = load_days(root, symbol=symbol)
    scores = []
    predictions = []
    for horizon in HORIZONS:
        dev, val = make_samples(rows, horizon)
        report, values = score(dev, val, horizon=horizon)
        scores.append(report)
        predictions.extend(values)
    output.mkdir(mode=0o700)
    private = output / "private"
    private.mkdir(mode=0o700)
    prediction_raw = b"".join(_canon(item) for item in predictions)
    _write_new(private / "validation-predictions.jsonl", prediction_raw)
    result = {"schema": SCHEMA, "status": "complete_trade_only_reference",
              "symbol": symbol, "calendar_start": START_DAY.isoformat(),
              "calendar_end": END_DAY.isoformat(),
              "development_days": DEV_DAYS, "validation_days": VAL_DAYS,
              "split_at": SPLIT_AT.isoformat(),
              "validation_after_embargo": VAL_AFTER_EMBARGO.isoformat(),
              "ridge_lambda_fixed": RIDGE_LAMBDA,
              "hyperparameter_search": False,
              "horizons_hours": [1, 4],
              "source_scope": "historical_trade_only",
              "baseline_features": ["lagged_return", "lagged_vol", "lagged_volume"],
              "additional_game_theory_proxy": "lagged_signed_taker_flow",
              "limitations": ["no_historical_executable_quotes_or_fills",
                              "no_historical_book_depth",
                              "no_funding_or_open_interest",
                              "last_trade_reference_prices_only",
                              "reference_cost_not_account_specific",
                              "overlapping_four_hour_signals_not_inventory_simulated"],
              "daily_source_receipts": per_day,
              "daily_sources_count": len(per_day),
              "hourly_source_rows": len(rows),
              "validation_predictions_private_sha256": _sha(prediction_raw),
              "scores": scores,
              "use": "chronological_development_validation_reference_only",
              "historical_executable_quote_or_L2_proven": False,
              "paper_forward_result": "not_tested",
              "orders_placed": 0,
              "model_source_sha256": _sha(Path(__file__).read_bytes())}
    _write_new(output / "result.json", _canon(result))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--symbol", choices=("BTCUSDT", "ETHUSDT"), required=True)
    parser.add_argument("--archive-root", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    _require(args.plan != args.run, "choose exactly one plan or run mode")
    if args.plan:
        print(json.dumps({"schema": SCHEMA, "symbol": args.symbol,
                          "days": len(fixed_days()), "first_day": START_DAY.isoformat(),
                          "last_day": END_DAY.isoformat(),
                          "archive_layout": f"{args.symbol}-YYYY-MM-DD/processed",
                          "development_days": DEV_DAYS, "validation_days": VAL_DAYS,
                          "embargo_hours": 4, "horizons_hours": HORIZONS,
                          "downloads": 0, "orders": 0}, sort_keys=True))
        return 0
    _require(args.archive_root is not None and args.output_dir is not None,
             "run needs one complete archived root and new output")
    result = run(args.archive_root.absolute(), symbol=args.symbol,
                 output=args.output_dir.absolute())
    print(json.dumps({"status": result["status"],
                      "result_path": str(args.output_dir / "result.json"),
                      "daily_sources_count": result["daily_sources_count"]},
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
