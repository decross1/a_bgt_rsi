"""Derive as-of H1 Spot liquidity/flow features from sealed public GET batches.

No market request, order, account, model call, or historical L2 claim occurs
here. The source contains no order or model call surface.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .collection_projection import _read_relative, project_collection
from .public_spot_capture import CaptureError, strict_json

SCHEMA = "applied-trial-prospective-h1-features/v1"
SOURCE_ID = "binance-spot-public"
MAX_BATCHES = 96
MAX_TRADES = 500_000
MAX_DEPTH_AGE_S = 300
MINUTE_OFFSET = 5


def _require(ok: bool, reason: str) -> None:
    if not ok:
        raise CaptureError(reason)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canon(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode() + b"\n"


def _utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise CaptureError("source receipt timestamp is malformed") from exc
    _require(parsed.tzinfo is not None, "source receipt timestamp is naive")
    return parsed.astimezone(timezone.utc)


def _num(value: Any, *, positive: bool = False) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise CaptureError("public price/size is not numeric") from exc
    _require(math.isfinite(parsed) and parsed >= 0 and
             (not positive or parsed > 0), "public price/size is nonfinite or nonpositive")
    return parsed


def _day_hour(t: datetime) -> datetime:
    return t.replace(minute=0, second=0, microsecond=0)


def _decision_after(t: datetime) -> datetime:
    grid = _day_hour(t) + timedelta(minutes=MINUTE_OFFSET)
    return grid if t <= grid else grid + timedelta(hours=1)


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


def _source_batches(paths: list[Path], collector_sha256: str,
                    symbol: str) -> tuple[list[dict], list[dict], list[dict]]:
    _require(1 <= len(paths) <= MAX_BATCHES and len(paths) == len(set(paths)),
             "prospective feature input is unbounded or duplicated")
    batches: list[dict] = []
    depths: list[dict] = []
    trades: list[dict] = []
    previous_next = None
    previous_seal = None
    for index, directory in enumerate(paths):
        projected = project_collection(directory,
                                       expected_collector_sha256=collector_sha256)
        _require(projected["symbol"] == symbol
                 and projected["status"] == "complete_incremental_batch"
                 and not projected["cursor_gap"] and not projected["page_gap"]
                 and not projected["backlog_unresolved"],
                 "H1 feature source has a missing/capped cursor or wrong symbol")
        batch_raw = _read_relative(directory, "capture-batch.json", 128_000)
        batch = strict_json(batch_raw)
        _require(isinstance(batch, dict) and batch.get("source_id") == SOURCE_ID
                 and type(batch.get("from_aggregate_id")) is int
                 and type(batch.get("next_aggregate_id")) is int
                 and (previous_next is None or batch["from_aggregate_id"] == previous_next)
                 and (previous_seal is None or
                      _utc(batch["started_at"]) >= previous_seal),
                 "prospective aggregate-trade cursor is not contiguous")
        previous_next = batch["next_aggregate_id"]
        previous_seal = _utc(batch["sealed_at"])
        batch_info = {"path": str(directory), "sha256": _sha(batch_raw),
                      "started_at": batch["started_at"],
                      "sealed_at": batch["sealed_at"],
                      "from_aggregate_id": batch["from_aggregate_id"],
                      "next_aggregate_id": batch["next_aggregate_id"]}
        batches.append(batch_info)
        attempts_raw = _read_relative(directory, "attempts.jsonl", 128_000)
        for ordinal, line in enumerate(attempts_raw.splitlines()):
            row = strict_json(line)
            _require(isinstance(row, dict), "source GET attempt is not an object")
            kind = row.get("kind")
            if kind not in {"depth", "aggTrades"}:
                continue
            received = _utc(row["response_received_at"])
            started = _utc(row["request_started_at"])
            _require(started <= received <= _utc(batch["sealed_at"]),
                     "public GET frame has impossible receipt chronology")
            raw = _read_relative(directory, row["raw_relpath"], 2_000_000)
            payload = strict_json(raw)
            frame = {"batch_index": index, "attempt_index": ordinal,
                     "raw_sha256": _sha(raw), "started": started,
                     "received": received, "payload": payload}
            if kind == "depth":
                _require(isinstance(payload, dict) and
                         type(payload.get("lastUpdateId")) is int,
                         "REST depth lacks its snapshot update ID")
                bids, asks = payload.get("bids"), payload.get("asks")
                _require(isinstance(bids, list) and isinstance(asks, list)
                         and 1 <= len(bids) <= 5 and 1 <= len(asks) <= 5,
                         "REST depth levels differ from bounded L5")
                bid = _num(bids[0][0], positive=True)
                ask = _num(asks[0][0], positive=True)
                _require(bid < ask, "REST book is crossed or empty")
                bid_size = sum(_num(level[1]) for level in bids)
                ask_size = sum(_num(level[1]) for level in asks)
                depths.append({**frame, "bid": bid, "ask": ask,
                               "bid_size": bid_size, "ask_size": ask_size,
                               "mid": (bid + ask) / 2})
            else:
                _require(isinstance(payload, list) and len(payload) <= 1000,
                         "aggregate-trade page exceeds public limit")
                for item in payload:
                    _require(isinstance(item, dict) and type(item.get("a")) is int
                             and type(item.get("T")) is int
                             and type(item.get("m")) is bool,
                             "aggregate-trade event is malformed")
                    event = datetime.fromtimestamp(item["T"] / 1000, tz=timezone.utc)
                    _require(event <= received + timedelta(seconds=30),
                             "trade event time is beyond local receipt/clock tolerance")
                    notional = _num(item["p"], positive=True) * _num(item["q"])
                    trades.append({"id": item["a"], "event": event,
                                   "received": received, "raw_sha256": frame["raw_sha256"],
                                   "signed_notional": -notional if item["m"] else notional,
                                   "notional": notional})
                    _require(len(trades) <= MAX_TRADES,
                             "aggregate-trade feature input exceeds bounded budget")
    _require(depths and trades and len({row["id"] for row in trades}) == len(trades),
             "prospective input has no unique trades/depth")
    ids = [row["id"] for row in trades]
    _require(ids == list(range(ids[0], ids[-1] + 1)),
             "aggregate-trade IDs are missing, reordered or duplicated")
    _require(all(trades[i]["event"] <= trades[i + 1]["event"]
                 for i in range(len(trades) - 1)),
             "aggregate-trade event time regressed across a closed-hour marker")
    return batches, depths, trades


def derive(paths: list[Path], *, collector_sha256: str, symbol: str) -> tuple[dict, list[dict]]:
    batches, depths, trades = _source_batches(paths, collector_sha256, symbol)
    by_hour: dict[datetime, list[dict]] = defaultdict(list)
    for trade in trades:
        by_hour[_day_hour(trade["event"])].append(trade)
    features = []
    for hour in sorted(by_hour):
        hour_end = hour + timedelta(hours=1)
        if not any(row["event"] < hour for row in trades):
            continue  # First observed hour has no proved left boundary.
        # A trade with event time on/after the hour boundary is the right-tail
        # witness; it must itself have been received before the feature decision.
        markers = [row for row in trades if row["event"] >= hour_end]
        if not markers:
            continue
        hour_trades = by_hour[hour]
        available = max([row["received"] for row in hour_trades] +
                        [markers[0]["received"]])
        decision = _decision_after(available)
        before = [row for row in depths if row["received"] <= available]
        if not before:
            continue
        depth = before[-1]
        previous = next((row for row in reversed(before[:-1])
                         if row["received"] <= hour), None)
        total = sum(row["notional"] for row in hour_trades)
        signed = sum(row["signed_notional"] for row in hour_trades)
        age = (decision - depth["received"]).total_seconds()
        feature = {
            "schema": SCHEMA, "symbol": symbol, "hour_start": hour.isoformat(),
            "hour_end": hour_end.isoformat(), "available_at": available.isoformat(),
            "decision_at": decision.isoformat(),
            "trade_cursor_contiguous": True,
            "right_tail_marker_id": markers[0]["id"],
            "trade_count": len(hour_trades),
            "flow_imbalance": signed / total if total > 0 else None,
            "bid": depth["bid"], "ask": depth["ask"],
            "spread_bps": 10_000 * (depth["ask"] - depth["bid"]) / depth["mid"],
            "book_snapshot_available_at": depth["received"].isoformat(),
            "book_snapshot_age_s": age,
            "rest_depth_has_venue_event_time": False,
            "rest_depth_has_diff_sequence_proof": False,
            "ask_depletion": (max(0.0, min(1.0,
                              1 - depth["ask_size"] / previous["ask_size"]))
                              if previous and previous["ask_size"] > 0 else None),
            "momentum_bps": (10_000 * (depth["mid"] / previous["mid"] - 1)
                             if previous else None),
            "usable_for_paper_observation": age <= MAX_DEPTH_AGE_S
                and available <= decision and previous is not None and total > 0,
            "source_frame_sha256s": sorted({depth["raw_sha256"]}
                                           | {row["raw_sha256"] for row in hour_trades}
                                           | {markers[0]["raw_sha256"]}),
        }
        feature["source_bundle_sha256"] = _sha(_canon(feature["source_frame_sha256s"]))
        features.append(feature)
    source = {"schema": "applied-trial-prospective-h1-feature-source/v1",
              "source_id": SOURCE_ID, "symbol": symbol,
              "collector_source_sha256": collector_sha256,
              "feature_builder_source_sha256": _sha(Path(__file__).read_bytes()),
              "batch_receipts": batches, "batch_count": len(batches),
              "feature_count": len(features),
              "usable_feature_count": sum(row["usable_for_paper_observation"]
                                          for row in features),
              "historical_L2_claim": False, "orders_placed": 0,
              "study_preregistered": False, "paper_result": "not_tested"}
    return source, features


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-batch", type=Path, action="append", required=True)
    parser.add_argument("--symbol", choices=("BTCUSDT", "ETHUSDT"), required=True)
    parser.add_argument("--expected-collector-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    _require(len(args.expected_collector_sha256) == 64 and all(
        char in "0123456789abcdef" for char in args.expected_collector_sha256),
        "registered collector source SHA is malformed")
    output = args.output_dir.absolute()
    _require(not output.exists() and output.parent.is_dir()
             and not output.parent.is_symlink(),
             "feature output is not a new regular direct child")
    source, features = derive([item.absolute() for item in args.input_batch],
                              collector_sha256=args.expected_collector_sha256,
                              symbol=args.symbol)
    output.mkdir(mode=0o700)
    feature_bytes = b"".join(_canon(row) for row in features)
    _write_new(output / "features.jsonl", feature_bytes)
    source["features_sha256"] = _sha(feature_bytes)
    _write_new(output / "feature-source.json", _canon(source))
    print(json.dumps({"feature_count": len(features),
                      "usable_feature_count": source["usable_feature_count"],
                      "feature_source_path": str(output / "feature-source.json")},
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
