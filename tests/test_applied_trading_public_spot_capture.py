"""Public GET capture producer and failure-denominator tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from bench.applied_trading import public_spot_capture as capture


def _receipt(kind: str) -> dict:
    return {
        "schema": capture.ATTEMPT_SCHEMA,
        "kind": kind,
        "source_id": "binance-spot-public",
        "symbol": "BTCUSDT",
        "method": "GET",
        "url": capture._url(kind, "BTCUSDT", 101 if kind == "aggTrades" else None),
        "request_started_at": capture.now(),
        "response_received_at": capture.now(),
        "http_status": 200,
        "raw_sha256": "a" * 64,
        "raw_bytes": 4,
        "timestamp_basis": "local_http_response",
        "venue_event_at": None,
        "fee_reference_url": capture.FEE_REFERENCE_URL,
        "ordinary_reference_fee_leg_bps": 10.0,
    }


def _fake_fetch(kind: str, symbol: str, from_id: int | None = None):
    if kind == "time":
        payload = {"serverTime": int(datetime.now(timezone.utc).timestamp() * 1000)}
    elif kind == "depth":
        payload = {"lastUpdateId": 7, "bids": [["100.0", "1.0"]], "asks": [["100.1", "1.0"]]}
    else:
        payload = [{"a": 101,
                    "T": int(datetime.now(timezone.utc).timestamp() * 1000),
                    "p": "100.0", "q": "1.0", "m": True}]
    raw = json.dumps(payload, sort_keys=True).encode()
    receipt = _receipt(kind)
    receipt["url"] = capture._url(kind, symbol, from_id)
    receipt["raw_sha256"] = capture.sha256(raw)
    receipt["raw_bytes"] = len(raw)
    return payload, raw, receipt


def test_public_incremental_batch_has_no_venue_book_timestamp_or_orders(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(capture, "_fetch", _fake_fetch)
    batch = capture.capture_once(tmp_path / "batch-001", symbol="BTCUSDT", from_id=101, max_pages=1)
    assert batch["status"] == "complete_incremental_batch"
    assert batch["orders_placed"] == 0 and batch["credentials_used"] is False
    assert batch["collector_source_sha256"] == capture.sha256(Path(capture.__file__).read_bytes())
    assert batch["requests_attempted"] == 3
    assert batch["requests_succeeded"] == 3
    assert batch["requests_failed"] == 0
    assert batch["attempt_denominator_verified"] is True
    attempts = [json.loads(row) for row in (tmp_path / "batch-001/attempts.jsonl").read_text().splitlines()]
    assert attempts[1]["kind"] == "depth"
    assert attempts[1]["venue_event_at"] is None
    assert attempts[1]["timestamp_basis"] == "local_http_response"
    assert attempts[2]["first_aggregate_id"] == 101
    assert all(row["attempt_status"] == "succeeded" for row in attempts)


def test_initial_cursor_warmup_is_incomplete_not_an_asof_backtest(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(capture, "_fetch", _fake_fetch)
    batch = capture.capture_once(tmp_path / "warmup", symbol="BTCUSDT", from_id=None, max_pages=1)
    assert batch["status"] == "incomplete"
    assert batch["initial_history_gap"] is True


def test_public_depth_nonfinite_and_trade_page_gap_are_visible() -> None:
    with pytest.raises(capture.CaptureError, match="invalid"):
        capture._validate_depth({"lastUpdateId": 1, "bids": [["NaN", "1"]], "asks": [["100", "1"]]})
    summary = capture._validate_trades(
        [{"a": 101, "T": 1_789_500_000_000, "p": "100", "q": "1", "m": True},
         {"a": 103, "T": 1_789_500_000_001, "p": "101", "q": "1", "m": False}], 101
    )
    assert summary["page_gap"] is True
    with pytest.raises(capture.CaptureError, match="price/size"):
        capture._validate_trades(
            [{"a": 101, "T": 1_789_500_000_000,
              "p": "NaN", "q": "1", "m": True}], 101)


def test_http_200_invalid_depth_is_attempted_and_raw_preserved(tmp_path, monkeypatch) -> None:
    def invalid_depth(kind: str, symbol: str, from_id: int | None = None):
        payload, raw, receipt = _fake_fetch(kind, symbol, from_id)
        if kind == "depth":
            raw = b'{"lastUpdateId":7,"bids":"bad","asks":[]}'
            receipt["raw_sha256"] = capture.sha256(raw)
            receipt["raw_bytes"] = len(raw)
        return payload, raw, receipt

    monkeypatch.setattr(capture, "_fetch", invalid_depth)
    output = tmp_path / "invalid-depth"
    batch = capture.capture_once(output, symbol="BTCUSDT", from_id=101, max_pages=1)
    attempts = [json.loads(line) for line in (output / "attempts.jsonl").read_text().splitlines()]
    assert batch["status"] == "incomplete"
    assert batch["requests_attempted"] == 2
    assert batch["requests_succeeded"] == 1
    assert batch["requests_failed"] == 1
    assert attempts[-1]["kind"] == "depth"
    assert attempts[-1]["attempt_status"] == "failed"
    assert attempts[-1]["failure_stage"] == "response_validation"
    assert attempts[-1]["http_status"] == 200
    assert attempts[-1]["raw_sha256"] == capture.sha256(
        (output / "raw/0001-depth.json").read_bytes()
    )
