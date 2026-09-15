"""Synthetic local archive tests; source-only until the Flash window closes."""

from __future__ import annotations

import hashlib
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from bench.applied_trading import public_archive_adapter as archive


def _files(tmp_path: Path, *, ids: tuple[int, int] = (7, 8)) -> tuple[Path, Path]:
    day = date(2026, 9, 14)
    zip_name, checksum_name, csv_name = archive.expected_names("BTCUSDT", day)
    zip_path = tmp_path / zip_name
    checksum_path = tmp_path / checksum_name
    at_ms = int(datetime(2026, 9, 14, 12, 1, tzinfo=timezone.utc).timestamp() * 1000)
    rows = (
        f"{ids[0]},100.0,2.0,11,11,{at_ms},false,true\n"
        f"{ids[1]},101.0,1.0,12,12,{at_ms + 1000},true,true\n"
    )
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as handle:
        handle.writestr(csv_name, rows)
    checksum_path.write_text(f"{hashlib.sha256(zip_path.read_bytes()).hexdigest()}  {zip_name}\n")
    return zip_path, checksum_path


def test_local_checksum_trade_only_hourly_flow_and_no_historical_l2(tmp_path) -> None:
    zip_path, checksum_path = _files(tmp_path)
    result = archive.process_local(zip_path, checksum_path, tmp_path / "out", symbol="BTCUSDT", day=date(2026, 9, 14))
    assert result["historical_executable_l2_proven"] is False
    assert result["orders_placed"] == 0
    assert result["hourly_rows"] == 1
    row = (tmp_path / "out/hourly-flow.jsonl").read_text()
    assert '"buy_aggressor_notional":200.0' in row
    assert '"sell_aggressor_notional":101.0' in row
    assert '"data_available_at_historical_decision":"not_proven_by_archive"' in row


def test_official_digest_and_id_gap_fail_closed(tmp_path) -> None:
    zip_path, checksum_path = _files(tmp_path)
    checksum_path.write_text("0" * 64 + "  " + zip_path.name + "\n")
    with pytest.raises(archive.ArchiveError, match="official SHA"):
        archive.validate_checksum(zip_path, checksum_path, symbol="BTCUSDT", day=date(2026, 9, 14))
    zip_path, checksum_path = _files(tmp_path, ids=(7, 9))
    with pytest.raises(archive.ArchiveError, match="ID gap"):
        archive.hourly_flow(zip_path, symbol="BTCUSDT", day=date(2026, 9, 14), zip_sha256="a" * 64)


def test_public_one_day_fetch_uses_only_fixed_urls_and_official_digest(tmp_path, monkeypatch) -> None:
    zip_path, checksum_path = _files(tmp_path)
    payloads = {"zip": zip_path.read_bytes(), "checksum": checksum_path.read_bytes()}
    seen = []

    def fixed_get(url: str, *, limit: int) -> bytes:
        seen.append((url, limit))
        return payloads["checksum" if url.endswith(".CHECKSUM") else "zip"]

    monkeypatch.setattr(archive, "_get_official", fixed_get)
    result = archive.fetch_and_process(tmp_path / "fetched", symbol="BTCUSDT", day=date(2026, 9, 14))
    assert len(seen) == 2
    assert all(url.startswith("https://data.binance.vision/data/spot/daily/aggTrades/BTCUSDT/") for url, _ in seen)
    assert result["orders_placed"] == 0
    assert result["processed_source_receipt_sha256"] == hashlib.sha256((tmp_path / "fetched/processed/source-receipt.json").read_bytes()).hexdigest()
