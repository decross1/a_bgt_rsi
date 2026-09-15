"""Source-only producer fixtures; do not execute during live model windows."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from bench.applied_trading import prospective_hourly_features as features
from bench.applied_trading.public_spot_capture import CaptureError


def ms(hour: int, minute: int, second: int = 0) -> int:
    return int(datetime(2026, 9, 15, hour, minute, second,
                        tzinfo=timezone.utc).timestamp() * 1000)


def fixture(monkeypatch, *, gap: bool = False, late_depth: bool = False,
            extra_trades: int = 0):
    paths = [Path("/tmp/batch-h1-a"), Path("/tmp/batch-h1-b")]
    first = {
        "source_id": "binance-spot-public", "started_at": "2026-09-15T07:59:00+00:00",
        "sealed_at": "2026-09-15T08:32:00+00:00",
        "from_aggregate_id": 100, "next_aggregate_id": 102 + extra_trades,
    }
    second = {
        "source_id": "binance-spot-public",
        "started_at": ("2026-09-15T08:56:00+00:00" if late_depth
                       else "2026-09-15T09:00:00+00:00"),
        "sealed_at": "2026-09-15T09:01:10+00:00",
        "from_aggregate_id": 102 + extra_trades + int(gap),
        "next_aggregate_id": 103 + extra_trades + int(gap),
    }
    depth = {"lastUpdateId": 42, "bids": [["100", "4"]],
             "asks": [["101", "2"]]}
    next_depth = {"lastUpdateId": 43, "bids": [["101", "4"]],
                  "asks": [["102", "1"]]}
    trade_a = [{"a": 100, "T": ms(7, 30), "p": "100", "q": "1", "m": True},
               {"a": 101, "T": ms(8, 30), "p": "101", "q": "1", "m": False}]
    trade_a.extend({"a": 102 + index, "T": ms(8, 31, index),
                    "p": "101", "q": "1", "m": False}
                   for index in range(extra_trades))
    trade_b = [{"a": 102 + extra_trades + int(gap), "T": ms(9, 0, 40),
                "p": "102", "q": "1", "m": False}]

    def attempt(kind, received, path):
        return {"kind": kind, "request_started_at": received,
                "response_received_at": received, "raw_relpath": path}

    rows = {
        (paths[0], "capture-batch.json"): json.dumps(first).encode(),
        (paths[1], "capture-batch.json"): json.dumps(second).encode(),
        (paths[0], "attempts.jsonl"): b"\n".join(json.dumps(row).encode() for row in [
            attempt("depth", "2026-09-15T08:00:00+00:00", "raw/0001-depth.json"),
            attempt("aggTrades", "2026-09-15T08:31:00+00:00", "raw/0002-aggTrades.json"),
        ]) + b"\n",
        (paths[1], "attempts.jsonl"): b"\n".join(json.dumps(row).encode() for row in [
            attempt("depth", "2026-09-15T09:00:30+00:00" if not late_depth
                    else "2026-09-15T08:58:00+00:00", "raw/0001-depth.json"),
            attempt("aggTrades", "2026-09-15T09:01:00+00:00", "raw/0002-aggTrades.json"),
        ]) + b"\n",
        (paths[0], "raw/0001-depth.json"): json.dumps(depth).encode(),
        (paths[0], "raw/0002-aggTrades.json"): json.dumps(trade_a).encode(),
        (paths[1], "raw/0001-depth.json"): json.dumps(next_depth).encode(),
        (paths[1], "raw/0002-aggTrades.json"): json.dumps(trade_b).encode(),
    }
    monkeypatch.setattr(features, "project_collection", lambda directory,
                        expected_collector_sha256: {
        "symbol": "BTCUSDT", "status": "complete_incremental_batch",
        "cursor_gap": False, "page_gap": False, "backlog_unresolved": False,
    })
    monkeypatch.setattr(features, "_read_relative", lambda directory, relative,
                        limit: rows[(directory, relative)])
    return paths


def test_right_and_left_markers_make_as_of_feature(monkeypatch):
    paths = fixture(monkeypatch)
    source, rows = features.derive(paths, collector_sha256="a" * 64,
                                   symbol="BTCUSDT")
    assert source["batch_count"] == 2
    assert len(rows) == 1  # The first observed hour lacks a left marker.
    assert rows[0]["hour_start"].startswith("2026-09-15T08:00")
    assert rows[0]["decision_at"].startswith("2026-09-15T09:05")
    assert rows[0]["flow_imbalance"] == 1
    assert rows[0]["usable_for_paper_observation"] is True
    assert rows[0]["rest_depth_has_diff_sequence_proof"] is False


def test_cursor_gap_rejected_before_a_feature(monkeypatch):
    paths = fixture(monkeypatch, gap=True)
    with pytest.raises(CaptureError, match="cursor"):
        features.derive(paths, collector_sha256="a" * 64, symbol="BTCUSDT")


def test_stale_depth_withholds_paper_use(monkeypatch):
    paths = fixture(monkeypatch, late_depth=True)
    _, rows = features.derive(paths, collector_sha256="a" * 64,
                              symbol="BTCUSDT")
    assert rows[0]["usable_for_paper_observation"] is False


def test_event_budget_accepts_bounded_source_and_rejects_next_event(monkeypatch):
    paths = fixture(monkeypatch, extra_trades=1)
    assert features.MAX_TRADES == 500_000
    source, rows = features.derive(paths, collector_sha256="a" * 64,
                                   symbol="BTCUSDT")
    assert source["batch_count"] == 2
    assert rows[0]["trade_count"] == 2
    monkeypatch.setattr(features, "MAX_TRADES", 3)
    with pytest.raises(CaptureError, match="bounded budget"):
        features.derive(paths, collector_sha256="a" * 64, symbol="BTCUSDT")
