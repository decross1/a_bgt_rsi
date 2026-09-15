"""Manual continuation proves cursor/GET accounting without live network."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from bench.applied_trading import hourly_capture, public_spot_capture


def _fake_fetch(kind: str, symbol: str, from_id: int | None = None):
    at = int(datetime.now(timezone.utc).timestamp() * 1000)
    if kind == "time":
        payload = {"serverTime": at}
    elif kind == "depth":
        payload = {"lastUpdateId": 7, "bids": [["100.0", "1.0"]],
                   "asks": [["100.1", "1.0"]]}
    else:
        payload = [{"a": from_id or 50, "T": at,
                    "p": "100.0", "q": "1.0", "m": False}]
    raw = json.dumps(payload, sort_keys=True).encode()
    received_at = public_spot_capture.now()
    receipt = {
        "schema": public_spot_capture.ATTEMPT_SCHEMA,
        "kind": kind, "source_id": "binance-spot-public",
        "symbol": symbol, "method": "GET",
        "url": public_spot_capture._url(kind, symbol, from_id),
        "request_started_at": received_at,
        "response_received_at": received_at,
        "http_status": 200,
        "raw_sha256": public_spot_capture.sha256(raw),
        "raw_bytes": len(raw),
        "timestamp_basis": "venue_trade_event" if kind == "aggTrades"
            else "local_http_response",
        "venue_event_at": None,
        "fee_reference_url": public_spot_capture.FEE_REFERENCE_URL,
        "ordinary_reference_fee_leg_bps": 10.0,
    }
    return None, raw, receipt


def _path(root, minute: str):
    return root / f"spot-BTCUSDT-20260915T09{minute}00Z"


def test_one_locked_continuation_binds_bootstrap_and_all_issued_gets(tmp_path, monkeypatch):
    monkeypatch.setattr(public_spot_capture, "_fetch", _fake_fetch)
    warmup, prior, output = (_path(tmp_path, minute)
                             for minute in ("00", "01", "02"))
    assert public_spot_capture.capture_once(
        warmup, symbol="BTCUSDT", from_id=None, max_pages=1)["status"] == "incomplete"
    assert public_spot_capture.capture_once(
        prior, symbol="BTCUSDT", from_id=51, max_pages=1)["status"] == "complete_incremental_batch"
    report = hourly_capture.run_once(
        previous_batch=prior, bootstrap_warmup=warmup,
        output_dir=output, max_pages=1, root=tmp_path)
    assert report["status"] == "continued_complete"
    assert report["from_aggregate_id"] == 52
    assert report["cumulative_requests"] == {
        "attempted": 9, "succeeded": 9, "failed": 0,
    }
    assert (output / "continuation.json").is_file()
    successor = _path(tmp_path, "03")
    next_report = hourly_capture.run_once(
        previous_batch=output, output_dir=successor,
        max_pages=1, root=tmp_path)
    assert next_report["cumulative_requests"]["attempted"] == 12


def test_incomplete_predecessor_blocks_before_any_get(tmp_path, monkeypatch):
    monkeypatch.setattr(public_spot_capture, "_fetch", _fake_fetch)
    warmup = _path(tmp_path, "00")
    public_spot_capture.capture_once(
        warmup, symbol="BTCUSDT", from_id=None, max_pages=1)
    def no_get(*_args, **_kwargs):
        raise AssertionError("incomplete predecessor issued a GET")
    monkeypatch.setattr(public_spot_capture, "_fetch", no_get)
    with pytest.raises(public_spot_capture.CaptureError, match="predecessor is incomplete"):
        hourly_capture.run_once(
            previous_batch=warmup, output_dir=_path(tmp_path, "01"),
            bootstrap_warmup=warmup, max_pages=1, root=tmp_path)
