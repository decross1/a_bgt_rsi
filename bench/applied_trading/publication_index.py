"""Publish a fixed, complete BTCUSDT trade-only reference baseline.

This is a content-free public index. It reads no exchange URL, does not start
capture, and cannot publish a partial 60-day result. The original result and
private predictions remain immutable in their own result child.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

from . import public_archive_adapter, trade_only_baseline
from .collection_projection import _read_relative
from .public_spot_capture import strict_json

DATA_ROOT = Path(
    "/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-15/"
    "applied-trading-public-data"
)
ARCHIVE_ROOT = DATA_ROOT / "archives"
REFERENCE_ROOT = DATA_ROOT / "reference-results"
PUBLICATION_ROOT = DATA_ROOT / "publications"
GATE_NAME = "source-gate-BTCUSDT-fixed60-v1.json"
INDEX_NAME = "fixed60-BTCUSDT-v1.json"
GATE_SCHEMA = "applied-trading-complete-60-day-source-gate/v1"
INDEX_SCHEMA = "applied-trading-publication/v1"


class PublicationError(RuntimeError):
    pass


def _must(ok: bool, message: str) -> None:
    if not ok:
        raise PublicationError(message)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canon(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode() + b"\n"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _fixed_directory(path: Path) -> None:
    _must(path.is_dir() and not path.is_symlink()
          and path.resolve() == path.absolute(),
          "publication input directory is absent or redirected")


def _read_from_child(child: Path, name: str, limit: int) -> bytes:
    _fixed_directory(child)
    return _read_relative(child, name, limit)


def _source_sha(module: object) -> str:
    path = Path(module.__file__)
    _must(path.is_file() and not path.is_symlink(),
          "baseline/archive source is unavailable")
    return _sha(path.read_bytes())


def _relative_file(child: Path, suffix: str) -> str:
    return f"reference-results/{child.name}/{suffix}"


def admit_baseline(result_child: Path) -> tuple[dict, bytes, bytes, list[dict]]:
    """Reread the original 60 ZIPs and all source receipts before admission."""
    _fixed_directory(DATA_ROOT)
    _fixed_directory(ARCHIVE_ROOT)
    _fixed_directory(REFERENCE_ROOT)
    _fixed_directory(result_child)
    _must(result_child.parent == REFERENCE_ROOT and
          result_child.name.startswith("BTCUSDT-fixed60-") and
          len(result_child.name) <= 80 and
          all(char.isalnum() or char in "-_" for char in result_child.name),
          "baseline result is not a registered direct child")

    result_raw = _read_from_child(result_child, "result.json", 1_000_000)
    prediction_raw = _read_from_child(
        result_child, "private/validation-predictions.jsonl", 8_000_000)
    result = strict_json(result_raw)
    _must(isinstance(result, dict)
          and result.get("schema") == trade_only_baseline.SCHEMA
          and result.get("status") == "complete_trade_only_reference"
          and result.get("symbol") == "BTCUSDT"
          and result.get("calendar_start") == "2026-07-17"
          and result.get("calendar_end") == "2026-09-14"
          and result.get("development_days") == 40
          and result.get("validation_days") == 20
          and result.get("hourly_source_rows") == 1440
          and result.get("daily_sources_count") == 60
          and result.get("horizons_hours") == [1, 4]
          and result.get("source_scope") == "historical_trade_only"
          and result.get("model_source_sha256") ==
              _source_sha(trade_only_baseline)
          and result.get("validation_predictions_private_sha256") ==
              _sha(prediction_raw)
          and result.get("historical_executable_quote_or_L2_proven") is False
          and result.get("paper_forward_result") == "not_tested"
          and result.get("orders_placed") == 0,
          "historical result lacks fixed reference-only identity")

    rows, rehashed_days = trade_only_baseline.load_days(
        ARCHIVE_ROOT, symbol="BTCUSDT")
    _must(result.get("daily_source_receipts") == rehashed_days,
          "result daily digests differ from 60 currently rehashed source days")
    # A source-only gate could admit fabricated positive scores with perfectly
    # genuine daily digests. Recompute the frozen, deterministic grade and
    # private validation rows from the rehashed source itself.
    replay_scores = []
    replay_predictions = []
    for horizon in (1, 4):
        dev, val = trade_only_baseline.make_samples(rows, horizon)
        replay_score, replay_values = trade_only_baseline.score(
            dev, val, horizon=horizon)
        replay_scores.append(replay_score)
        replay_predictions.extend(replay_values)
    _must(result.get("scores") == replay_scores,
          "published numeric scores differ from deterministic 60-day replay")
    _must(prediction_raw == b"".join(
        trade_only_baseline._canon(row) for row in replay_predictions),
        "private predictions differ from deterministic 60-day replay")
    _must(type(result.get("scores")) is list and len(result["scores"]) == 2,
          "historical result score horizons are missing")
    for score, horizon in zip(result["scores"], (1, 4)):
        expected = 480 - 3 - horizon
        _must(isinstance(score, dict)
              and score.get("horizon_hours") == horizon
              and score.get("validation_eligible_rows") == expected
              and score.get("validation_scored_rows") == expected
              and score.get("validation_coverage") == 1.0
              and score.get("reference_only_no_trading_edge_claim") is True
              and score.get("reference_cost", {}).get(
                  "historical_executable_L2_or_fill_proven") is False,
              "historical result has a selective or mislabelled score")
        for key in ("baseline_mse_bps2", "flow_model_mse_bps2",
                    "baseline_directional_accuracy",
                    "flow_model_directional_accuracy"):
            value = score.get(key)
            _must(type(value) in (float, int) and math.isfinite(value),
                  f"historical {key} is nonfinite or missing")
    lines = prediction_raw.splitlines()
    _must(len(lines) == 949,
          "private validation prediction denominator differs")
    counts = {1: 0, 4: 0}
    for line in lines:
        row = strict_json(line)
        _must(isinstance(row, dict) and row.get("horizon_hours") in counts,
              "private prediction has an undeclared horizon")
        counts[row["horizon_hours"]] += 1
    _must(counts == {1: 476, 4: 473},
          "private prediction horizon counts differ")
    return result, result_raw, prediction_raw, rehashed_days


def make_receipts(result_child: Path) -> tuple[dict, dict]:
    result, result_raw, predictions_raw, days = admit_baseline(result_child)
    result_relpath = _relative_file(result_child, "result.json")
    predictions_relpath = _relative_file(
        result_child, "private/validation-predictions.jsonl")
    baseline_sha = _source_sha(trade_only_baseline)
    archive_sha = _source_sha(public_archive_adapter)
    publisher_sha = _sha(Path(__file__).read_bytes())
    gate = {
        "schema": GATE_SCHEMA, "status": "admitted", "symbol": "BTCUSDT",
        "calendar_start": "2026-07-17", "calendar_end": "2026-09-14",
        "daily_sources_count": 60, "hourly_source_rows": 1440,
        "daily_source_receipts": days,
        "source_replay": "full_60_day_rehash_at_publication",
        "grade_replay": "deterministic_two_horizon_scores_and_private_predictions",
        "archive_adapter_source_sha256": archive_sha,
        "baseline_runner_source_sha256": baseline_sha,
        "gate_builder_source_sha256": publisher_sha,
        "result_relpath": result_relpath,
        "result_raw_sha256": _sha(result_raw),
        "private_predictions_relpath": predictions_relpath,
        "private_predictions_raw_sha256": _sha(predictions_raw),
        "reference_only": True,
        "historical_executable_quotes_proven": False,
        "paper_forward_result": "not_tested",
    }
    gate_raw = _canon(gate)
    index = {
        "schema": INDEX_SCHEMA, "kind": "fixed60_baseline",
        "status": "admitted", "symbol": "BTCUSDT",
        "published_at": _utc_now(),
        "gate_relpath": "publications/" + GATE_NAME,
        "gate_raw_sha256": _sha(gate_raw),
        "result_relpath": result_relpath,
        "result_raw_sha256": _sha(result_raw),
        "private_predictions_relpath": predictions_relpath,
        "private_predictions_raw_sha256": _sha(predictions_raw),
        "baseline_runner_source_sha256": baseline_sha,
        "archive_adapter_source_sha256": archive_sha,
        "reference_only": True,
        "historical_executable_quotes_proven": False,
        "paper_forward_result": "not_tested",
    }
    _must(result["daily_source_receipts"] == gate["daily_source_receipts"],
          "source gate and result diverged")
    return gate, index


def _write_new(name: str, raw: bytes) -> None:
    _fixed_directory(PUBLICATION_ROOT)
    directory_fd = os.open(PUBLICATION_ROOT, os.O_RDONLY | os.O_DIRECTORY |
                           os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0))
    try:
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                     os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
                     0o600, dir_fd=directory_fd)
        try:
            view = memoryview(raw)
            while view:
                size = os.write(fd, view)
                _must(size > 0, "publication write failed")
                view = view[size:]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def publish(result_child: Path) -> dict:
    gate, index = make_receipts(result_child)
    _must(not (PUBLICATION_ROOT / INDEX_NAME).exists()
          and not (PUBLICATION_ROOT / INDEX_NAME).is_symlink(),
          "fixed baseline publication already exists")
    gate_path = PUBLICATION_ROOT / GATE_NAME
    if gate_path.exists() or gate_path.is_symlink():
        # A crash after the gate, before the final index, is recoverable only
        # by repeating the full source/grade admission and proving the exact
        # immutable gate bytes. A different gate is never overwritten.
        _must(_read_relative(PUBLICATION_ROOT, GATE_NAME, 256_000) ==
              _canon(gate),
              "orphan gate differs from freshly replayed 60-day result")
    else:
        _write_new(GATE_NAME, _canon(gate))
    # The UI must reject a gate alone. The index is the final publish marker.
    _write_new(INDEX_NAME, _canon(index))
    return index


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result-child", type=Path, required=True)
    parser.add_argument("--publish-baseline", action="store_true")
    args = parser.parse_args(argv)
    child = args.result_child.absolute()
    if args.publish_baseline:
        index = publish(child)
    else:
        _gate, index = make_receipts(child)
    print(json.dumps({"status": index["status"],
                      "result_raw_sha256": index["result_raw_sha256"],
                      "gate_raw_sha256": index["gate_raw_sha256"],
                      "index_path": str(PUBLICATION_ROOT / INDEX_NAME)
                      if args.publish_baseline else None}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
