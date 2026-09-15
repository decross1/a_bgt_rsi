"""One-shot, bounded Binance Spot public GET capture for paper research.

No POST, order, account, credential, wallet or model calls.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "applied-trial-binance-public-capture-batch/v1"
ATTEMPT_SCHEMA = "applied-trial-public-get-attempt/v1"
HOST = "https://data-api.binance.vision"
SYMBOLS = frozenset({"BTCUSDT", "ETHUSDT"})
MAX_PAGES = 32
MAX_TOTAL_BYTES = 16_000_000
MAX_JSON_BYTES = {"time": 2_048, "depth": 16_384, "aggTrades": 512_000}
REQUEST_TIMEOUT_S = 8
USER_AGENT = "a-bgt-rsi-paper-public-data-research/1.0"
FEE_REFERENCE_URL = "https://www.binance.com/en/support/faq/detail/115000429332"


class CaptureError(ValueError):
    pass


class CaptureAttemptError(CaptureError):
    """An issued GET failed; its bounded public metadata must be journaled."""

    def __init__(self, receipt: dict, reason: str):
        super().__init__(reason)
        self.receipt = receipt


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise CaptureError("duplicate JSON key in public response")
        result[key] = value
    return result


def _nonfinite(value: str):
    raise CaptureError(f"nonfinite public JSON value {value}")


def strict_json(raw: bytes) -> Any:
    try:
        return json.loads(raw, object_pairs_hook=_pairs, parse_constant=_nonfinite)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CaptureError("public response is not strict JSON") from exc


def _url(kind: str, symbol: str, from_id: int | None = None) -> str:
    if symbol not in SYMBOLS:
        raise CaptureError("symbol is not in the fixed BTC/ETH Spot registry")
    if kind == "time":
        return f"{HOST}/api/v3/time"
    if kind == "depth":
        return f"{HOST}/api/v3/depth?" + urllib.parse.urlencode({"symbol": symbol, "limit": 5})
    if kind == "aggTrades":
        query = {"symbol": symbol, "limit": 1000}
        if from_id is not None:
            if type(from_id) is not int or not 0 <= from_id <= 2**63 - 1:
                raise CaptureError("aggregate-trade cursor is invalid")
            query["fromId"] = from_id
        return f"{HOST}/api/v3/aggTrades?" + urllib.parse.urlencode(query)
    raise CaptureError("public GET kind is not registered")


def _fetch(kind: str, symbol: str, from_id: int | None = None) -> tuple[Any, bytes, dict]:
    url = _url(kind, symbol, from_id)
    started_at = now()
    request = urllib.request.Request(
        url, method="GET", headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    http_status = None
    failure_stage = None
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:
            http_status = response.status
            if response.status != 200 or response.geturl() != url:
                failure_stage = "http_contract"
                raise CaptureError("public GET status or redirect differs")
            content_type = response.headers.get("Content-Type", "")
            if "json" not in content_type.lower():
                failure_stage = "http_contract"
                raise CaptureError("public GET content type differs")
            raw = response.read(MAX_JSON_BYTES[kind] + 1)
            if len(raw) > MAX_JSON_BYTES[kind]:
                failure_stage = "response_bound"
                raise CaptureError("public GET exceeds response bound")
    except (CaptureError, urllib.error.URLError, TimeoutError, OSError) as exc:
        if isinstance(exc, urllib.error.HTTPError):
            http_status = exc.code
            failure_stage = "http_contract"
        receipt = {
            "schema": ATTEMPT_SCHEMA, "kind": kind,
            "source_id": "binance-spot-public", "symbol": symbol,
            "method": "GET", "url": url,
            "request_started_at": started_at,
            "response_received_at": now(), "http_status": http_status,
            "attempt_status": "failed",
            "failure_stage": failure_stage or "transport",
            "failure_code": type(exc).__name__,
            "raw_relpath": None, "raw_sha256": None, "raw_bytes": 0,
            "timestamp_basis": "venue_trade_event" if kind == "aggTrades"
                else "local_http_response",
            "venue_event_at": None,
            "fee_reference_url": FEE_REFERENCE_URL,
            "ordinary_reference_fee_leg_bps": 10.0,
        }
        raise CaptureAttemptError(receipt, f"public GET {kind} failed: {type(exc).__name__}") from exc
    received_at = now()
    receipt = {
        "schema": ATTEMPT_SCHEMA,
        "kind": kind,
        "source_id": "binance-spot-public",
        "symbol": symbol,
        "method": "GET",
        "url": url,
        "request_started_at": started_at,
        "response_received_at": received_at,
        "http_status": 200,
        "attempt_status": "received",
        "failure_stage": None,
        "failure_code": None,
        "raw_sha256": sha256(raw),
        "raw_bytes": len(raw),
        "timestamp_basis": "venue_trade_event" if kind == "aggTrades" else "local_http_response",
        "venue_event_at": None,
        "fee_reference_url": FEE_REFERENCE_URL,
        "ordinary_reference_fee_leg_bps": 10.0,
    }
    # Strict JSON/content validation happens after the raw 200 body is durably
    # written. An invalid response is still an issued GET in the denominator.
    return None, raw, receipt


def _write_exclusive(path: Path, raw: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        view = memoryview(raw)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise CaptureError("exclusive artifact write failed")
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)


def _append_chain(path: Path, record: dict, prior_hash: str) -> str:
    row = {**record, "prior_record_sha256": prior_hash}
    row_hash = sha256(canonical(row))
    row["record_sha256"] = row_hash
    data = canonical(row) + b"\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    try:
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise CaptureError("attempt journal write failed")
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
    return row_hash


def _validate_depth(payload: Any) -> dict:
    if not isinstance(payload, dict) or type(payload.get("lastUpdateId")) is not int:
        raise CaptureError("depth response lacks snapshot update ID")
    for side in ("bids", "asks"):
        levels = payload.get(side)
        if not isinstance(levels, list) or not 1 <= len(levels) <= 5:
            raise CaptureError("depth response lacks bounded levels")
        for level in levels:
            if not isinstance(level, list) or len(level) != 2:
                raise CaptureError("depth level shape differs")
            try:
                price, size = float(level[0]), float(level[1])
            except (TypeError, ValueError) as exc:
                raise CaptureError("depth level is not numeric") from exc
            if not math.isfinite(price) or not math.isfinite(size) or not 0 < price < 1e9 or not 0 <= size < 1e9:
                raise CaptureError("depth level is invalid")
    if float(payload["bids"][0][0]) >= float(payload["asks"][0][0]):
        raise CaptureError("depth snapshot is crossed or locked")
    return {"last_update_id": payload["lastUpdateId"], "bid_levels": len(payload["bids"]), "ask_levels": len(payload["asks"])}


def _validate_trades(payload: Any, requested_from_id: int | None,
                     received_at: str | None = None) -> dict:
    if not isinstance(payload, list) or len(payload) > 1000:
        raise CaptureError("aggregate-trade page is malformed")
    ids = []
    for row in payload:
        if (not isinstance(row, dict) or type(row.get("a")) is not int
                or type(row.get("T")) is not int or type(row.get("m")) is not bool
                or type(row.get("p")) is not str or type(row.get("q")) is not str):
            raise CaptureError("aggregate-trade ID/event-time/side/price/size differs")
        try:
            price, size = float(row["p"]), float(row["q"])
        except (TypeError, ValueError) as exc:
            raise CaptureError("aggregate-trade price/size is nonnumeric") from exc
        if (not 0 <= row["a"] <= 2**63 - 1
                or not 1_483_228_800_000 <= row["T"] <= 2**63 - 1
                or not math.isfinite(price) or not math.isfinite(size)
                or not 0 < price < 1e9 or not 0 < size < 1e9):
            raise CaptureError("aggregate-trade ID/time/price/size is invalid")
        if received_at is not None:
            received_ms = int(datetime.fromisoformat(
                received_at.replace("Z", "+00:00")
            ).timestamp() * 1000)
            if row["T"] > received_ms + 30_000:
                raise CaptureError("aggregate-trade event is future of local receipt")
        ids.append(row["a"])
    page_gap = any(ids[i] + 1 != ids[i + 1] for i in range(len(ids) - 1))
    cursor_gap = requested_from_id is not None and bool(ids) and ids[0] != requested_from_id
    return {"row_count": len(ids), "first_aggregate_id": ids[0] if ids else None, "last_aggregate_id": ids[-1] if ids else None, "page_gap": page_gap, "cursor_gap": cursor_gap, "trade_event_time_unit": "milliseconds"}


def capture_once(output_dir: Path, *, symbol: str, from_id: int | None, max_pages: int) -> dict:
    if symbol not in SYMBOLS or type(max_pages) is not int or not 1 <= max_pages <= MAX_PAGES:
        raise CaptureError("symbol/page plan is not bounded")
    if from_id is not None:
        _url("aggTrades", symbol, from_id)  # Reject a nonrequestable cursor before any GET.
    if output_dir.exists() or output_dir.parent.is_symlink() or not output_dir.parent.is_dir():
        raise CaptureError("output must be a new direct child of a regular parent")
    output_dir.mkdir(mode=0o700)
    raw_dir = output_dir / "raw"
    raw_dir.mkdir(mode=0o700)
    journal = output_dir / "attempts.jsonl"
    chain = "0" * 64
    total_bytes = 0
    receipts = []
    requests_issued = 0
    cursor = from_id
    backlog_unresolved = False
    initial_history_gap = from_id is None
    started_at = now()
    failure = None

    def issue(kind: str, ordinal: int, requested_cursor: int | None = None) -> tuple[Any, dict]:
        nonlocal chain, total_bytes, requests_issued
        requests_issued += 1  # Count before the GET, including transport failure.
        try:
            _, raw, receipt = _fetch(kind, symbol, requested_cursor)
        except CaptureAttemptError as exc:
            chain = _append_chain(journal, exc.receipt, chain)
            receipts.append(exc.receipt)
            raise
        raw_path = raw_dir / f"{ordinal:04d}-{kind}.json"
        relative = f"raw/{ordinal:04d}-{kind}.json"
        try:
            if total_bytes + len(raw) > MAX_TOTAL_BYTES:
                raise CaptureError("capture batch exceeds total raw-byte budget")
            _write_exclusive(raw_path, raw)
            total_bytes += len(raw)
            receipt["raw_relpath"] = relative
            payload = strict_json(raw)
            if kind == "time":
                if not isinstance(payload, dict) or type(payload.get("serverTime")) is not int:
                    raise CaptureError("time response lacks venue server clock")
                receipt["server_time_ms"] = payload["serverTime"]
                local_received_ms = int(datetime.fromisoformat(
                    receipt["response_received_at"].replace("Z", "+00:00")
                ).timestamp() * 1000)
                receipt["server_minus_local_ms"] = payload["serverTime"] - local_received_ms
                if abs(receipt["server_minus_local_ms"]) > 30_000:
                    raise CaptureError("venue/local clock difference exceeds 30 seconds")
            elif kind == "depth":
                receipt.update(_validate_depth(payload))
                receipt["venue_event_at"] = None  # No REST venue event time.
            else:
                receipt.update(_validate_trades(
                    payload, requested_cursor, receipt["response_received_at"]))
        except (CaptureError, OSError, ValueError) as exc:
            receipt["attempt_status"] = "failed"
            receipt["failure_stage"] = (
                "response_validation" if receipt.get("raw_relpath") else "artifact_write"
            )
            receipt["failure_code"] = type(exc).__name__
            if not receipt.get("raw_relpath"):
                receipt["raw_sha256"] = None
                receipt["raw_bytes"] = 0
            chain = _append_chain(journal, receipt, chain)
            receipts.append(receipt)
            raise
        receipt["attempt_status"] = "succeeded"
        chain = _append_chain(journal, receipt, chain)
        receipts.append(receipt)
        return payload, receipt

    try:
        for ordinal, kind in enumerate(("time", "depth")):
            issue(kind, ordinal)
        prior_last = None
        for page in range(max_pages):
            _payload, receipt = issue("aggTrades", page + 2, cursor)
            summary = receipt
            # requested_cursor is prior_last+1 on later pages, so the
            # validation/journal already binds a cross-page cursor gap.
            if receipt["cursor_gap"] or receipt["page_gap"]:
                break
            if summary["last_aggregate_id"] is None:
                backlog_unresolved = False
                break
            prior_last = summary["last_aggregate_id"]
            cursor = prior_last + 1
            if summary["row_count"] < 1000:
                backlog_unresolved = False
                break
            backlog_unresolved = True
    except (CaptureError, OSError, ValueError) as exc:
        failure = f"{type(exc).__name__}: {exc}"
    batch = {
        "schema": SCHEMA,
        "collector_source_sha256": sha256(Path(__file__).read_bytes()),
        "capture_plan_sha256": sha256(canonical({"symbol": symbol, "from_aggregate_id": from_id, "max_pages": max_pages, "host": HOST, "methods": ["GET"]})),
        "source_id": "binance-spot-public",
        "symbol": symbol,
        "paper_only": True,
        "public_get_only": True,
        "status": "incomplete" if failure or initial_history_gap or backlog_unresolved or any(r.get("cursor_gap") or r.get("page_gap") for r in receipts) else "complete_incremental_batch",
        "started_at": started_at,
        "sealed_at": now(),
        "from_aggregate_id": from_id,
        "requested_max_pages": max_pages,
        "next_aggregate_id": cursor,
        "initial_history_gap": initial_history_gap,
        "backlog_unresolved": backlog_unresolved,
        "cursor_gap": any(r.get("cursor_gap") for r in receipts),
        "page_gap": any(r.get("page_gap") for r in receipts),
        "attempt_count": len(receipts),
        "requests_attempted": requests_issued,
        "requests_succeeded": sum(row.get("attempt_status") == "succeeded"
                                  for row in receipts),
        "requests_failed": sum(row.get("attempt_status") == "failed"
                               for row in receipts),
        "attempt_denominator_verified": requests_issued == len(receipts),
        "total_raw_bytes": total_bytes,
        "attempts_sha256": sha256(journal.read_bytes()) if journal.exists() else None,
        "chain_root_sha256": chain,
        "failure": failure,
        "fee_reference_url": FEE_REFERENCE_URL,
        "ordinary_reference_fee_leg_bps": 10.0,
        "venue_timestamp_note": "aggTrades.T is venue event time; REST depth has no venue event time and is available only at local HTTP receipt",
        "orders_placed": 0,
        "credentials_used": False,
    }
    _write_exclusive(output_dir / "capture-batch.json", json.dumps(batch, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n")
    return batch


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="One-shot public GET Spot capture; no orders")
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--symbol", choices=sorted(SYMBOLS), required=True)
    parser.add_argument("--from-id", type=int)
    parser.add_argument("--max-pages", type=int, default=8)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    if args.plan == args.run or not 1 <= args.max_pages <= MAX_PAGES:
        raise CaptureError("select exactly one of --plan/--run with bounded pages")
    if args.plan:
        print(json.dumps({"source_id": "binance-spot-public", "symbol": args.symbol, "methods": ["GET"], "from_aggregate_id": args.from_id, "max_pages": args.max_pages, "max_total_bytes": MAX_TOTAL_BYTES, "orders": 0, "collector_source_sha256": sha256(Path(__file__).read_bytes())}, sort_keys=True))
        return 0
    if args.output_dir is None or not args.output_dir.is_absolute():
        raise CaptureError("--run needs an absolute new output directory")
    result = capture_once(args.output_dir, symbol=args.symbol, from_id=args.from_id, max_pages=args.max_pages)
    print(json.dumps({"status": result["status"], "batch_path": str(args.output_dir / "capture-batch.json"), "next_aggregate_id": result["next_aggregate_id"]}, sort_keys=True))
    return 0 if result["status"] == "complete_incremental_batch" else 1


if __name__ == "__main__":
    raise SystemExit(main())
