"""Sealed collection visibility and collector-version boundary tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from bench.applied_trading import collection_projection as projection
from bench.applied_trading import public_spot_capture as capture


def _fake_fetch(kind: str, symbol: str, from_id: int | None = None):
    payload = (
        {"serverTime": int(datetime.now(timezone.utc).timestamp() * 1000)} if kind == "time"
        else {"lastUpdateId": 1, "bids": [["100", "1"]], "asks": [["101", "1"]]} if kind == "depth"
        else [{"a": 101,
               "T": int(datetime.now(timezone.utc).timestamp() * 1000),
               "p": "100.0", "q": "1.0", "m": False}]
    )
    raw = json.dumps(payload).encode()
    return payload, raw, {
        "schema": capture.ATTEMPT_SCHEMA, "kind": kind, "source_id": "binance-spot-public",
        "symbol": symbol, "method": "GET", "url": capture._url(kind, symbol, from_id),
        "request_started_at": capture.now(), "response_received_at": capture.now(),
        "http_status": 200, "raw_sha256": capture.sha256(raw), "raw_bytes": len(raw),
        "timestamp_basis": "local_http_response", "venue_event_at": None,
        "fee_reference_url": capture.FEE_REFERENCE_URL, "ordinary_reference_fee_leg_bps": 10.0,
    }


def test_content_free_projection_checks_every_raw_attempt(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(capture, "_fetch", _fake_fetch)
    root = tmp_path / "batch"
    capture.capture_once(root, symbol="BTCUSDT", from_id=101, max_pages=1)
    row = projection.project_collection(root, expected_collector_sha256=batch_source_hash())
    assert row["stage"] == "data_collection"
    assert row["paper_result"] == "not_tested"
    assert row["orders_placed"] == 0
    assert row["collector_source_verified"] is True
    assert row["attempt_count"] == 3
    assert row["requests_attempted"] == 3
    assert row["requests_succeeded"] == 3
    assert row["requests_failed"] == 0
    assert row["source_valid_frames"] == 3
    (root / "raw/0001-depth.json").write_bytes(b'[{"changed":true}]')
    with pytest.raises(capture.CaptureError, match="raw public frame differs"):
        projection.project_collection(root, expected_collector_sha256=batch_source_hash())


def batch_source_hash() -> str:
    return capture.sha256(Path(capture.__file__).read_bytes())


def test_failed_early_batch_is_visible_but_never_complete(tmp_path, monkeypatch) -> None:
    def fail(kind, symbol, from_id=None):
        started = capture.now()
        raise capture.CaptureAttemptError({
            "schema": capture.ATTEMPT_SCHEMA, "kind": kind,
            "source_id": "binance-spot-public", "symbol": symbol,
            "method": "GET", "url": capture._url(kind, symbol, from_id),
            "request_started_at": started, "response_received_at": capture.now(),
            "http_status": None, "attempt_status": "failed",
            "failure_stage": "transport", "failure_code": "TimeoutError",
            "raw_relpath": None, "raw_sha256": None, "raw_bytes": 0,
            "timestamp_basis": "local_http_response", "venue_event_at": None,
            "fee_reference_url": capture.FEE_REFERENCE_URL,
            "ordinary_reference_fee_leg_bps": 10.0,
        }, "offline")

    monkeypatch.setattr(capture, "_fetch", fail)
    root = tmp_path / "batch-failed"
    batch = capture.capture_once(root, symbol="BTCUSDT", from_id=101, max_pages=1)
    assert batch["status"] == "incomplete"
    row = projection.project_collection(root)
    assert row["attempt_count"] == 1
    assert row["requests_attempted"] == 1
    assert row["requests_succeeded"] == 0
    assert row["requests_failed"] == 1
    assert row["source_valid_frames"] == 0
    assert row["status"] == "incomplete"


def test_http_200_invalid_depth_not_source_valid(tmp_path, monkeypatch) -> None:
    def invalid_depth(kind, symbol, from_id=None):
        payload, raw, receipt = _fake_fetch(kind, symbol, from_id)
        if kind == "depth":
            raw = b'{"lastUpdateId":1,"bids":"bad","asks":[]}'
            receipt["raw_sha256"] = capture.sha256(raw)
            receipt["raw_bytes"] = len(raw)
        return payload, raw, receipt

    monkeypatch.setattr(capture, "_fetch", invalid_depth)
    root = tmp_path / "invalid-depth"
    capture.capture_once(root, symbol="BTCUSDT", from_id=101, max_pages=1)
    row = projection.project_collection(root, expected_collector_sha256=batch_source_hash())
    assert row["requests_attempted"] == 2
    assert row["requests_failed"] == 1
    assert row["source_valid_frames"] == 1
    assert row["has_depth_snapshot"] is False
    (root / "raw/0001-depth.json").write_bytes(b"changed")
    with pytest.raises(capture.CaptureError, match="raw public frame differs"):
        projection.project_collection(root, expected_collector_sha256=batch_source_hash())


def test_observed_old_source_is_available_as_receipt_but_not_code_verified(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(capture, "_fetch", _fake_fetch)
    root = tmp_path / "observed-old-source"
    capture.capture_once(root, symbol="BTCUSDT", from_id=101, max_pages=1)
    receipt_path = root / "capture-batch.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["collector_source_sha256"] = projection.HISTORICAL_COLLECTOR_SHA256
    receipt_path.write_text(json.dumps(receipt, sort_keys=True))
    row = projection.project_known_collection(root)
    assert row["collector_source_status"] == "historical_source_unavailable"
    assert row["collector_source_verified"] is False
    assert row["requests_attempted"] == row["source_valid_frames"] == 3
    receipt["collector_source_sha256"] = "0" * 64
    receipt_path.write_text(json.dumps(receipt, sort_keys=True))
    with pytest.raises(capture.CaptureError, match="not a known version"):
        projection.project_known_collection(root)
