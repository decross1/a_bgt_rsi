"""Pure publication contract tests; full ZIP replay is tested by baseline."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from bench.applied_trading import publication_index as p


def _days() -> list[dict]:
    return [{"day": day.isoformat(), "fetch_receipt_sha256": "a" * 64,
             "source_receipt_sha256": "b" * 64,
             "hourly_flow_sha256": "c" * 64,
             "zip_sha256": "d" * 64,
             "checksum_raw_sha256": "e" * 64,
             "hourly_rows": 24, "missing_hours": 0}
            for day in p.trade_only_baseline.fixed_days()]


def _fixture(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    child = tmp_path / "reference-results" / "BTCUSDT-fixed60-test-a"
    child.mkdir(parents=True)
    monkeypatch.setattr(p, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(p, "ARCHIVE_ROOT", tmp_path / "archives")
    monkeypatch.setattr(p, "REFERENCE_ROOT", child.parent)
    monkeypatch.setattr(p, "PUBLICATION_ROOT", tmp_path / "publications")
    (tmp_path / "archives").mkdir()
    (tmp_path / "publications").mkdir()
    days = _days()
    monkeypatch.setattr(p.trade_only_baseline, "load_days",
                        lambda _root, *, symbol: ([{}] * 1440, days))
    monkeypatch.setattr(p, "_source_sha", lambda _module: "f" * 64)
    prediction_raw = b"".join(
        p._canon({"horizon_hours": horizon, "ordinal": ordinal})
        for horizon, count in ((1, 476), (4, 473))
        for ordinal in range(count))
    scores = [{"horizon_hours": horizon,
               "validation_eligible_rows": count,
               "validation_scored_rows": count,
               "validation_coverage": 1.0,
               "reference_only_no_trading_edge_claim": True,
               "reference_cost": {
                   "historical_executable_L2_or_fill_proven": False},
               "baseline_mse_bps2": 10.0, "flow_model_mse_bps2": 9.0,
               "baseline_directional_accuracy": .50,
               "flow_model_directional_accuracy": .51}
              for horizon, count in ((1, 476), (4, 473))]
    monkeypatch.setattr(p.trade_only_baseline, "make_samples",
                        lambda _rows, _horizon: ([], []))
    monkeypatch.setattr(p.trade_only_baseline, "score",
                        lambda _dev, _val, *, horizon: (
                            scores[0 if horizon == 1 else 1],
                            [{"horizon_hours": horizon, "ordinal": ordinal}
                             for ordinal in range(476 if horizon == 1 else 473)]))
    result = {"schema": p.trade_only_baseline.SCHEMA,
              "status": "complete_trade_only_reference", "symbol": "BTCUSDT",
              "calendar_start": "2026-07-17", "calendar_end": "2026-09-14",
              "development_days": 40, "validation_days": 20,
              "hourly_source_rows": 1440, "daily_sources_count": 60,
              "horizons_hours": [1, 4], "source_scope": "historical_trade_only",
              "model_source_sha256": "f" * 64,
              "validation_predictions_private_sha256": p._sha(prediction_raw),
              "historical_executable_quote_or_L2_proven": False,
              "paper_forward_result": "not_tested", "orders_placed": 0,
              "daily_source_receipts": days, "scores": scores}
    payload = {"result.json": p._canon(result),
               "private/validation-predictions.jsonl": prediction_raw}
    monkeypatch.setattr(p, "_read_from_child",
                        lambda _child, name, _limit: payload[name])
    return child, result, payload


def test_complete_gate_binds_result_and_prediction(monkeypatch, tmp_path):
    child, result, payload = _fixture(monkeypatch, tmp_path)
    gate, index = p.make_receipts(child)
    assert gate["daily_sources_count"] == 60
    assert gate["hourly_source_rows"] == 1440
    assert gate["daily_source_receipts"] == result["daily_source_receipts"]
    assert index["gate_raw_sha256"] == p._sha(p._canon(gate))
    assert index["private_predictions_raw_sha256"] == p._sha(
        payload["private/validation-predictions.jsonl"])
    assert gate["reference_only"] and not gate["historical_executable_quotes_proven"]


def test_cannot_publish_cherry_picked_daily_digest(monkeypatch, tmp_path):
    child, result, payload = _fixture(monkeypatch, tmp_path)
    altered = copy.deepcopy(result)
    altered["daily_source_receipts"][0]["zip_sha256"] = "0" * 64
    payload["result.json"] = p._canon(altered)
    with pytest.raises(p.PublicationError, match="daily digests"):
        p.make_receipts(child)


def test_cannot_publish_missing_validation_prediction(monkeypatch, tmp_path):
    child, result, payload = _fixture(monkeypatch, tmp_path)
    prediction = payload["private/validation-predictions.jsonl"].splitlines(
        keepends=True)[:-1]
    payload["private/validation-predictions.jsonl"] = b"".join(prediction)
    result["validation_predictions_private_sha256"] = p._sha(
        payload["private/validation-predictions.jsonl"])
    payload["result.json"] = p._canon(result)
    with pytest.raises(p.PublicationError, match="private predictions"):
        p.make_receipts(child)


def test_cannot_publish_fabricated_positive_score(monkeypatch, tmp_path):
    child, result, payload = _fixture(monkeypatch, tmp_path)
    altered = copy.deepcopy(result)
    altered["scores"][0]["flow_model_mse_bps2"] = -999.0
    payload["result.json"] = p._canon(altered)
    with pytest.raises(p.PublicationError, match="numeric scores"):
        p.make_receipts(child)


def test_gate_written_before_final_index(monkeypatch, tmp_path):
    child, _result, _payload = _fixture(monkeypatch, tmp_path)
    names = []
    monkeypatch.setattr(p, "_write_new", lambda name, _raw: names.append(name))
    p.publish(child)
    assert names == [p.GATE_NAME, p.INDEX_NAME]


def test_orphan_gate_only_finalized_after_full_replay(monkeypatch, tmp_path):
    child, _result, _payload = _fixture(monkeypatch, tmp_path)
    gate, _index = p.make_receipts(child)
    p._write_new(p.GATE_NAME, p._canon(gate))
    assert not (p.PUBLICATION_ROOT / p.INDEX_NAME).exists()
    p.publish(child)
    assert (p.PUBLICATION_ROOT / p.INDEX_NAME).is_file()
