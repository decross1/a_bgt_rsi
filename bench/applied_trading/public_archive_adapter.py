"""Binance Spot aggTrades archive fetch and trade-only development adapter.

No ZIP downloads, HTTP clients, quotes, model calls or orders. It turns a
previously acquired, SHA-256-checked public trade archive into hourly
**historical trade-only** features; it cannot establish historical executable
L2 prices or contemporaneous archive availability.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import re
import urllib.error
import urllib.request
import zipfile
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

SCHEMA = "applied-trial-binance-historical-flow/v1"
SOURCE_SCHEMA = "applied-trial-binance-archive-source/v1"
SYMBOLS = frozenset({"BTCUSDT", "ETHUSDT"})
MAX_ZIP_BYTES = 80_000_000
MAX_UNCOMPRESSED_BYTES = 300_000_000
MAX_ROWS = 5_000_000
FETCH_TIMEOUT_S = 30
CHECKSUM_MAX_BYTES = 2_048
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class ArchiveError(ValueError):
    pass


def sha256_file(path: Path, *, max_bytes: int) -> str:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > max_bytes:
        raise ArchiveError("archive input is redirected, nonregular or oversized")
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as handle:
        while block := handle.read(65_536):
            total += len(block)
            if total > max_bytes:
                raise ArchiveError("archive changed or exceeded byte bound")
            digest.update(block)
    return digest.hexdigest()


def expected_names(symbol: str, day: date) -> tuple[str, str, str]:
    if symbol not in SYMBOLS or not isinstance(day, date):
        raise ArchiveError("archive universe/date differs")
    stem = f"{symbol}-aggTrades-{day.isoformat()}"
    return f"{stem}.zip", f"{stem}.zip.CHECKSUM", f"{stem}.csv"


def public_urls(symbol: str, day: date) -> dict:
    zip_name, checksum_name, _ = expected_names(symbol, day)
    base = f"https://data.binance.vision/data/spot/daily/aggTrades/{symbol}/"
    return {"zip_url": base + zip_name, "checksum_url": base + checksum_name,
            "source_kind": "official_public_trade_archive_only", "historical_l2_available": False}


def validate_checksum(zip_file: Path, checksum_file: Path, *, symbol: str, day: date) -> tuple[str, str]:
    zip_name, checksum_name, _ = expected_names(symbol, day)
    if zip_file.name != zip_name or checksum_file.name != checksum_name:
        raise ArchiveError("local files do not match the fixed official archive names")
    checksum_raw_sha = sha256_file(checksum_file, max_bytes=CHECKSUM_MAX_BYTES)
    line = checksum_file.read_text(encoding="ascii").strip().splitlines()
    if len(line) != 1:
        raise ArchiveError("official checksum file must contain one line")
    fields = line[0].split()
    if len(fields) not in (1, 2) or HEX64.fullmatch(fields[0].lower()) is None:
        raise ArchiveError("official checksum format differs")
    if len(fields) == 2 and Path(fields[1]).name != zip_name:
        raise ArchiveError("checksum names a different ZIP")
    zip_sha = sha256_file(zip_file, max_bytes=MAX_ZIP_BYTES)
    if zip_sha != fields[0].lower():
        raise ArchiveError("archive ZIP differs from official SHA-256")
    return zip_sha, checksum_raw_sha


def _event_at(raw: str, day: date) -> datetime:
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ArchiveError("trade timestamp is not an integer") from exc
    # Binance Spot public-data archive changed timestamp units in 2025. The
    # unit is selected by documented magnitude and pinned in the receipt.
    unit = 1_000_000 if value >= 10**14 else 1_000
    try:
        instant = datetime.fromtimestamp(value / unit, timezone.utc)
    except (OverflowError, ValueError) as exc:
        raise ArchiveError("trade timestamp is out of bounds") from exc
    if instant.date() != day:
        raise ArchiveError("trade event is outside the named UTC archive day")
    return instant


def _parse_trade(row: list[str], day: date) -> tuple[int, datetime, float, float, bool]:
    if len(row) != 8:
        raise ArchiveError("Spot aggregate trade CSV row does not have eight columns")
    try:
        aggregate_id = int(row[0])
        price = float(row[1])
        quantity = float(row[2])
    except (ValueError, TypeError) as exc:
        raise ArchiveError("aggregate trade ID/price/size is malformed") from exc
    if aggregate_id < 0 or not all(math.isfinite(x) for x in (price, quantity)) or not 0 < price < 1e9 or not 0 < quantity < 1e9:
        raise ArchiveError("aggregate trade price/size/ID is invalid")
    event = _event_at(row[5], day)
    maker_flag = row[6].strip().lower()
    if maker_flag not in ("true", "false"):
        raise ArchiveError("buyer-is-maker flag differs")
    return aggregate_id, event, price, quantity, maker_flag == "true"


def hourly_flow(zip_file: Path, *, symbol: str, day: date, zip_sha256: str) -> list[dict]:
    _, _, expected_csv = expected_names(symbol, day)
    buckets = defaultdict(lambda: {"buy_aggressor_notional": 0.0, "sell_aggressor_notional": 0.0, "trade_count": 0, "first_price": None, "last_price": None, "first_aggregate_id": None, "last_aggregate_id": None})
    prior_id = None
    count = 0
    with zipfile.ZipFile(zip_file) as archive:
        members = archive.infolist()
        if len(members) != 1 or members[0].filename != expected_csv or members[0].file_size > MAX_UNCOMPRESSED_BYTES or members[0].is_dir():
            raise ArchiveError("ZIP member name/count/uncompressed size differs")
        with archive.open(members[0]) as stream:
            text = io.TextIOWrapper(stream, encoding="utf-8", newline="")
            reader = csv.reader(text)
            for row in reader:
                if count == 0 and row and row[0].lower() in {"agg_trade_id", "aggtradeid"}:
                    continue  # Pin optional header, but never discard data row.
                aggregate_id, event, price, size, buyer_is_maker = _parse_trade(row, day)
                if prior_id is not None and aggregate_id != prior_id + 1:
                    raise ArchiveError("historical aggregate-trade ID gap")
                prior_id = aggregate_id
                count += 1
                if count > MAX_ROWS:
                    raise ArchiveError("archive exceeds historical row bound")
                hour = event.replace(minute=0, second=0, microsecond=0)
                bucket = buckets[hour]
                notional = price * size
                # Binance m=True means buyer was maker, i.e. seller aggressed.
                key = "sell_aggressor_notional" if buyer_is_maker else "buy_aggressor_notional"
                bucket[key] += notional
                bucket["trade_count"] += 1
                if bucket["first_price"] is None:
                    bucket["first_price"] = price
                    bucket["first_aggregate_id"] = aggregate_id
                bucket["last_price"] = price
                bucket["last_aggregate_id"] = aggregate_id
    rows = []
    for hour in sorted(buckets):
        bucket = buckets[hour]
        buy = bucket["buy_aggressor_notional"]
        sell = bucket["sell_aggressor_notional"]
        total = buy + sell
        if not total or not math.isfinite(total):
            raise ArchiveError("historical notional is invalid")
        rows.append({
            "schema": SCHEMA,
            "symbol": symbol,
            "hour_start_utc": hour.isoformat().replace("+00:00", "Z"),
            "trade_event_time_basis": "venue_trade_event",
            "data_available_at_historical_decision": "not_proven_by_archive",
            "raw_archive_zip_sha256": zip_sha256,
            "first_aggregate_id": bucket["first_aggregate_id"],
            "last_aggregate_id": bucket["last_aggregate_id"],
            "trade_count": bucket["trade_count"],
            "buy_aggressor_notional": buy,
            "sell_aggressor_notional": sell,
            "signed_flow_imbalance": (buy - sell) / total,
            "first_trade_price": bucket["first_price"],
            "last_trade_price": bucket["last_price"],
            "historical_executable_quote_available": False,
        })
    return rows


def _write_exclusive(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise ArchiveError("historical artifact write failed")
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)


def _get_official(url: str, *, limit: int) -> bytes:
    if not url.startswith("https://data.binance.vision/data/spot/daily/aggTrades/"):
        raise ArchiveError("archive GET URL is outside the official fixed registry")
    request = urllib.request.Request(url, method="GET", headers={"User-Agent": "a-bgt-rsi-paper-public-data-research/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_S) as response:
            if response.status != 200 or response.geturl() != url:
                raise ArchiveError("official archive status or redirect differs")
            declared = response.headers.get("Content-Length")
            if declared is not None and int(declared) > limit:
                raise ArchiveError("official archive exceeds declared size bound")
            raw = response.read(limit + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ArchiveError(f"official archive GET failed: {type(exc).__name__}") from exc
    if len(raw) > limit:
        raise ArchiveError("official archive exceeds read size bound")
    return raw


def fetch_and_process(output_dir: Path, *, symbol: str, day: date) -> dict:
    """One fixed public GET pair for one completed UTC day, then local trade-only features."""
    if day >= datetime.now(timezone.utc).date():
        raise ArchiveError("daily archive day is not yet complete")
    zip_name, checksum_name, _ = expected_names(symbol, day)
    urls = public_urls(symbol, day)
    if output_dir.exists() or output_dir.parent.is_symlink() or not output_dir.parent.is_dir():
        raise ArchiveError("public fetch output must be a new direct child")
    output_dir.mkdir(mode=0o700)
    checksum_raw = _get_official(urls["checksum_url"], limit=CHECKSUM_MAX_BYTES)
    zip_raw = _get_official(urls["zip_url"], limit=MAX_ZIP_BYTES)
    zip_path = output_dir / zip_name
    checksum_path = output_dir / checksum_name
    _write_exclusive(checksum_path, checksum_raw)
    _write_exclusive(zip_path, zip_raw)
    source = process_local(zip_path, checksum_path, output_dir / "processed", symbol=symbol, day=day)
    fetch = {
        "schema": "applied-trial-binance-archive-public-fetch/v1",
        "source_id": "binance-spot-public-archive",
        "symbol": symbol,
        "day": day.isoformat(),
        "urls": urls,
        "fetcher_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "zip_sha256": source["zip_sha256"],
        "checksum_raw_sha256": source["checksum_raw_sha256"],
        "processed_source_receipt_sha256": hashlib.sha256((output_dir / "processed/source-receipt.json").read_bytes()).hexdigest(),
        "historical_executable_l2_proven": False,
        "orders_placed": 0,
        "credentials_used": False,
    }
    _write_exclusive(output_dir / "fetch-receipt.json", json.dumps(fetch, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n")
    return fetch


def process_local(zip_file: Path, checksum_file: Path, output_dir: Path, *, symbol: str, day: date) -> dict:
    zip_sha, checksum_sha = validate_checksum(zip_file, checksum_file, symbol=symbol, day=day)
    rows = hourly_flow(zip_file, symbol=symbol, day=day, zip_sha256=zip_sha)
    if output_dir.exists() or output_dir.parent.is_symlink() or not output_dir.parent.is_dir():
        raise ArchiveError("historical output must be a new direct child")
    output_dir.mkdir(mode=0o700)
    flow_raw = b"".join(json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n" for row in rows)
    _write_exclusive(output_dir / "hourly-flow.jsonl", flow_raw)
    source = {
        "schema": SOURCE_SCHEMA,
        "source_id": "binance-spot-public-archive",
        "symbol": symbol,
        "day": day.isoformat(),
        "urls": public_urls(symbol, day),
        "zip_sha256": zip_sha,
        "checksum_raw_sha256": checksum_sha,
        "hourly_flow_sha256": hashlib.sha256(flow_raw).hexdigest(),
        "hourly_rows": len(rows),
        "historical_executable_l2_proven": False,
        "use": "development_and_chronological_validation_only",
        "orders_placed": 0,
    }
    _write_exclusive(output_dir / "source-receipt.json", json.dumps(source, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n")
    return source


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local archive validation and trade-only development features")
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--process-local", action="store_true")
    parser.add_argument("--fetch-public", action="store_true")
    parser.add_argument("--symbol", choices=sorted(SYMBOLS), required=True)
    parser.add_argument("--day", type=date.fromisoformat, required=True)
    parser.add_argument("--zip-file", type=Path)
    parser.add_argument("--checksum-file", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    if sum((args.plan, args.process_local, args.fetch_public)) != 1:
        raise ArchiveError("select exactly --plan, --process-local or --fetch-public")
    if args.plan:
        print(json.dumps(public_urls(args.symbol, args.day), sort_keys=True))
        return 0
    if args.fetch_public:
        if args.output_dir is None or not args.output_dir.is_absolute():
            raise ArchiveError("public fetch needs an absolute new output directory")
        result = fetch_and_process(args.output_dir, symbol=args.symbol, day=args.day)
        print(json.dumps({"status": "verified_trade_only_archive", "fetch_receipt": str(args.output_dir / "fetch-receipt.json"), "zip_sha256": result["zip_sha256"]}, sort_keys=True))
        return 0
    if not all(p is not None and p.is_absolute() for p in (args.zip_file, args.checksum_file, args.output_dir)):
        raise ArchiveError("local processing requires absolute fixed file/output paths")
    source = process_local(args.zip_file, args.checksum_file, args.output_dir, symbol=args.symbol, day=args.day)
    print(json.dumps({"status": "validated_local_trade_only", "source_receipt": str(args.output_dir / "source-receipt.json"), "hourly_rows": source["hourly_rows"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
