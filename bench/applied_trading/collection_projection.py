"""Content-free, read-only projection of one sealed public capture batch.

The raw files and attempt chain are checked before any UI row is returned.
This is data-collection visibility, not a paper strategy score.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import urllib.parse
from pathlib import Path

from . import public_spot_capture as capture_source
from .public_spot_capture import (
    ATTEMPT_SCHEMA,
    SCHEMA,
    CaptureError,
    _url,
    canonical,
    strict_json,
)

MAX_JOURNAL_BYTES = 128_000
MAX_BATCH_BYTES = 32_000
MAX_ATTEMPTS = 34
RAW_FILE_PATTERN = re.compile(r"^raw/[0-9]{4}-(time|depth|aggTrades)\.json$")
RAW_LIMITS = {"time": 2_048, "depth": 16_384, "aggTrades": 512_000}
HISTORICAL_COLLECTOR_SHA256 = (
    "780d846508ac2a5003d32bb372ddab68b5fb406c55feefab82794d553053bcf5"
)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_relative(directory: Path, relative: str, limit: int) -> bytes:
    parts = relative.split("/")
    if len(parts) > 2 or any(part in ("", ".", "..") for part in parts):
        raise CaptureError("projection input name escapes sealed batch")
    if directory.is_symlink() or not directory.is_dir():
        raise CaptureError("projection batch root is redirected or absent")
    root_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        if len(parts) == 2:
            raw_fd = os.open(parts[0], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
        else:
            raw_fd = root_fd
        try:
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=raw_fd)
            try:
                before = os.fstat(fd)
                if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
                    raise CaptureError("projection input is nonregular or oversized")
                chunks = []
                remaining = limit + 1
                while remaining:
                    part = os.read(fd, min(remaining, 65_536))
                    if not part:
                        break
                    chunks.append(part)
                    remaining -= len(part)
                data = b"".join(chunks)
                after = os.fstat(fd)
                if len(data) > limit or (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
                    raise CaptureError("projection input changed during read")
                return data
            finally:
                os.close(fd)
        finally:
            if raw_fd != root_fd:
                os.close(raw_fd)
    finally:
        os.close(root_fd)


def project_collection(directory: Path, *, expected_collector_sha256: str | None = None) -> dict:
    batch_raw = _read_relative(directory, "capture-batch.json", MAX_BATCH_BYTES)
    batch = strict_json(batch_raw)
    if not isinstance(batch, dict) or batch.get("schema") != SCHEMA or batch.get("source_id") != "binance-spot-public":
        raise CaptureError("batch is not the registered public Spot capture")
    if batch.get("paper_only") is not True or batch.get("public_get_only") is not True or batch.get("orders_placed") != 0 or batch.get("credentials_used") is not False:
        raise CaptureError("batch cannot be displayed as paper public-read-only")
    if expected_collector_sha256 is not None and batch.get("collector_source_sha256") != expected_collector_sha256:
        raise CaptureError("collector source differs from registered source")
    journal_raw = (
        b"" if batch.get("attempt_count") == 0 and batch.get("attempts_sha256") is None
        else _read_relative(directory, "attempts.jsonl", MAX_JOURNAL_BYTES)
    )
    if batch.get("attempts_sha256") != (_digest(journal_raw) if journal_raw else None):
        raise CaptureError("attempt journal bytes differ from sealed receipt")
    lines = journal_raw.splitlines()
    if not 0 <= len(lines) <= MAX_ATTEMPTS or len(lines) != batch.get("attempt_count"):
        raise CaptureError("attempt count is not sealed or bounded")
    previous = "0" * 64
    total_raw = 0
    gaps = False
    kinds = []
    raw_paths = set()
    succeeded = failed = 0
    failed_seen = False
    valid_kinds = []
    for line in lines:
        if len(line) > 4_096:
            raise CaptureError("attempt journal row exceeds bound")
        row = strict_json(line)
        if not isinstance(row, dict) or row.get("schema") != ATTEMPT_SCHEMA or row.get("method") != "GET" or row.get("source_id") != batch["source_id"] or row.get("symbol") != batch.get("symbol"):
            raise CaptureError("attempt does not bind public GET batch")
        if row.get("prior_record_sha256") != previous:
            raise CaptureError("attempt hash chain is broken")
        observed_hash = row.get("record_sha256")
        if observed_hash != _digest(canonical({key: value for key, value in row.items() if key != "record_sha256"})):
            raise CaptureError("attempt row digest differs")
        previous = observed_hash
        attempt_status = row.get("attempt_status")
        if attempt_status not in {"succeeded", "failed"} or failed_seen:
            raise CaptureError("public GET outcome is missing or resumed after a failure")
        if attempt_status == "succeeded":
            if (row.get("failure_stage") is not None
                    or row.get("failure_code") is not None
                    or row.get("http_status") != 200):
                raise CaptureError("successful public GET has a failure receipt")
            succeeded += 1
        else:
            if (row.get("failure_stage") not in {
                "transport", "http_contract", "response_bound",
                "response_validation", "artifact_write"
            } or not isinstance(row.get("failure_code"), str)
                    or not row["failure_code"]):
                raise CaptureError("failed public GET has no bounded cause")
            failed_seen = True
            failed += 1
        kind = row.get("kind")
        relative = row.get("raw_relpath")
        if kind not in RAW_LIMITS:
            raise CaptureError("public GET kind differs")
        url = row.get("url")
        if kind == "aggTrades" and isinstance(url, str):
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query, keep_blank_values=True)
            if set(query) not in ({"symbol", "limit"}, {"symbol", "limit", "fromId"}) or any(len(values) != 1 for values in query.values()):
                raise CaptureError("trade GET query differs from fixed public route")
            try:
                from_id = int(query["fromId"][0]) if "fromId" in query else None
            except ValueError as exc:
                raise CaptureError("trade cursor is not numeric") from exc
            expected_url = _url(kind, batch["symbol"], from_id)
        else:
            expected_url = _url(kind, batch["symbol"])
        if url != expected_url:
            raise CaptureError("attempt URL differs from fixed public endpoint")
        if relative is None:
            if (attempt_status != "failed" or row.get("raw_sha256") is not None
                    or row.get("raw_bytes") != 0
                    or row.get("failure_stage") == "response_validation"):
                raise CaptureError("public GET omitted a successful response body")
        else:
            if (not isinstance(relative, str)
                    or RAW_FILE_PATTERN.fullmatch(relative) is None
                    or not relative.endswith(f"-{kind}.json")
                    or relative in raw_paths):
                raise CaptureError("raw public frame path/kind differs")
            raw_paths.add(relative)
            raw = _read_relative(directory, relative, RAW_LIMITS[kind])
            if row.get("raw_sha256") != _digest(raw) or row.get("raw_bytes") != len(raw):
                raise CaptureError("raw public frame differs from attempt")
            total_raw += len(raw)
            if attempt_status == "failed" and (
                row.get("failure_stage") != "response_validation"
                or row.get("http_status") != 200
            ):
                raise CaptureError("failed response frame does not bind HTTP 200 validation")
        if attempt_status == "succeeded":
            valid_kinds.append(kind)
        if kind == "depth" and row.get("venue_event_at") is not None:
            raise CaptureError("REST depth cannot claim venue event time")
        gaps |= row.get("cursor_gap") is True or row.get("page_gap") is True
        kinds.append(kind)
    if previous != batch.get("chain_root_sha256") or total_raw != batch.get("total_raw_bytes") or total_raw > 16_000_000:
        raise CaptureError("batch totals or chain root differ")
    issued = batch.get("requests_attempted")
    if (type(issued) is not int or not 0 <= issued <= MAX_ATTEMPTS
            or issued < len(lines)
            or batch.get("attempt_denominator_verified") is not (issued == len(lines))
            or batch.get("requests_succeeded") != succeeded
            or batch.get("requests_failed") != failed):
        raise CaptureError("issued GET denominator differs from the sealed journal")
    expected_kinds = (["time", "depth"] + ["aggTrades"] * (len(kinds) - 2)) if len(kinds) >= 2 else kinds
    if kinds != expected_kinds or (len(kinds) == 1 and kinds != ["time"]):
        raise CaptureError("public GET sequence differs")
    if gaps != (batch.get("cursor_gap") is True or batch.get("page_gap") is True):
        raise CaptureError("gap state differs from attempt frames")
    if batch.get("status") == "complete_incremental_batch" and (
        len(lines) < 3 or failed or issued != len(lines)
        or batch.get("failure") is not None or batch.get("initial_history_gap")
        or batch.get("backlog_unresolved") or gaps
    ):
        raise CaptureError("batch falsely claims incremental completion")
    if len(lines) < 3 and batch.get("failure") is None:
        raise CaptureError("short public capture has no recorded failure")
    if batch.get("status") not in {"incomplete", "complete_incremental_batch"}:
        raise CaptureError("batch status is not registered")
    return {
        "schema": "applied-trial-data-collection-projection/v1",
        "stage": "data_collection",
        "source_id": batch["source_id"],
        "symbol": batch["symbol"],
        "status": batch["status"],
        "started_at": batch.get("started_at"),
        "sealed_at": batch.get("sealed_at"),
        "batch_sha256": _digest(batch_raw),
        "collector_source_sha256": batch.get("collector_source_sha256"),
        "collector_source_verified": expected_collector_sha256 is not None,
        "attempt_count": len(lines),
        "requests_attempted": issued,
        "requests_succeeded": succeeded,
        "requests_failed": failed,
        "requests_unjournaled": issued - len(lines),
        "attempt_denominator_verified": issued == len(lines),
        "source_valid_frames": succeeded,
        "raw_bytes": total_raw,
        "has_depth_snapshot": "depth" in valid_kinds,
        "trade_pages": valid_kinds.count("aggTrades"),
        "cursor_gap": batch.get("cursor_gap") is True,
        "page_gap": batch.get("page_gap") is True,
        "backlog_unresolved": batch.get("backlog_unresolved") is True,
        "depth_venue_event_time": "unavailable",
        "historical_executable_l2_proven": False,
        "study_preregistered": False,
        "paper_result": "not_tested",
        "orders_placed": 0,
    }


def project_known_collection(directory: Path) -> dict:
    """Classify two observed collector versions without claiming missing code proof.

    The historical 780d source bytes were not preserved. Its sealed GET/raw
    receipt can be checked, but the original code identity is unavailable.
    Unknown source hashes remain invalid rather than self-registering.
    """
    batch = strict_json(_read_relative(directory, "capture-batch.json", MAX_BATCH_BYTES))
    if not isinstance(batch, dict):
        raise CaptureError("batch source receipt is malformed")
    source_sha = batch.get("collector_source_sha256")
    current_sha = _digest(Path(capture_source.__file__).read_bytes())
    if source_sha == current_sha:
        row = project_collection(directory, expected_collector_sha256=current_sha)
        row["collector_source_status"] = "current_verified"
    elif source_sha == HISTORICAL_COLLECTOR_SHA256:
        row = project_collection(directory)
        row["collector_source_status"] = "historical_source_unavailable"
    else:
        raise CaptureError("batch collector source is not a known version")
    return row


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only content-free projection of a sealed public capture batch")
    parser.add_argument("--collection-dir", type=Path, required=True)
    parser.add_argument("--expected-source-sha256")
    args = parser.parse_args(argv)
    if not args.collection_dir.is_absolute():
        raise CaptureError("collection directory must be absolute")
    expected = args.expected_source_sha256
    if expected is not None and re.fullmatch(r"[0-9a-f]{64}", expected) is None:
        raise CaptureError("registered collector SHA-256 is malformed")
    print(json.dumps(project_collection(args.collection_dir, expected_collector_sha256=expected), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
