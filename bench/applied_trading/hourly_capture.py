"""Manual, locked Spot capture continuation; no timer or order surface.

One invocation issues at most two metadata GETs and eight aggTrades GETs.
Only a sealed, cursor-contiguous predecessor can donate a cursor. A failed or
incomplete successor stops the chain until it is inspected; there is no retry
or scheduler activation in this module.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import stat
import urllib.parse
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from . import public_spot_capture as capture_source
from .collection_projection import _read_relative, project_collection
from .public_spot_capture import (
    MAX_PAGES,
    SYMBOLS,
    CaptureError,
    _validate_trades,
    _write_exclusive,
    capture_once,
    strict_json,
)

SCHEMA = "applied-trial-spot-capture-continuation/v1"
CAPTURE_ROOT = Path(
    "/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-15/"
    "applied-trading-public-data/captures"
)
OLD_COLLECTOR_SHA256 = (
    "780d846508ac2a5003d32bb372ddab68b5fb406c55feefab82794d553053bcf5"
)
NAME = re.compile(r"spot-(BTCUSDT|ETHUSDT)-[0-9]{8}T[0-9]{6}Z\Z")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _current_collector_sha256() -> str:
    return _sha(Path(capture_source.__file__).read_bytes())


def _fixed_child(path: Path, root: Path) -> Path:
    absolute = path.absolute()
    if (absolute.parent != root or NAME.fullmatch(absolute.name) is None
            or root.is_symlink() or not root.is_dir()
            or absolute.is_symlink()):
        raise CaptureError("capture is not a fixed-root direct child")
    return absolute


def _verified_batch(path: Path, root: Path) -> tuple[dict, dict, str]:
    path = _fixed_child(path, root)
    raw = _read_relative(path, "capture-batch.json", 32_000)
    batch = strict_json(raw)
    if not isinstance(batch, dict) or batch.get("symbol") not in SYMBOLS:
        raise CaptureError("sealed Spot batch is malformed")
    source_sha = batch.get("collector_source_sha256")
    if source_sha not in {OLD_COLLECTOR_SHA256, _current_collector_sha256()}:
        raise CaptureError("batch collector source is unregistered")
    projection = project_collection(path, expected_collector_sha256=source_sha)
    if projection["requests_unjournaled"] or not projection["attempt_denominator_verified"]:
        raise CaptureError("prior GET request denominator is incomplete")
    # The original smoke collector checked trade ID/time/side but not p/q.
    # Revalidate its raw returned trade frames before a cursor is reused.
    journal = _read_relative(path, "attempts.jsonl", 128_000)
    for line in journal.splitlines():
        attempt = strict_json(line)
        if attempt["kind"] != "aggTrades" or attempt["attempt_status"] != "succeeded":
            continue
        frame = strict_json(_read_relative(path, attempt["raw_relpath"], 512_000))
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(attempt["url"]).query)
        requested = int(query["fromId"][0]) if "fromId" in query else None
        checked = _validate_trades(frame, requested, attempt["response_received_at"])
        if checked["cursor_gap"] or checked["page_gap"]:
            raise CaptureError("sealed trade frame has a cursor/ID gap")
    return batch, projection, _sha(raw)


@contextmanager
def _one_capture_lock(root: Path, symbol: str):
    lock_path = root / f".{symbol.lower()}-capture.lock"
    flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(lock_path, flags, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > 4_096:
            raise CaptureError("capture lock is not a bounded regular file")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise CaptureError("another Spot capture holds the lock") from exc
        yield
    finally:
        os.close(fd)


def _prior_totals(previous_path: Path, previous: dict, prior_sha: str,
                  bootstrap_warmup: Path | None, root: Path) -> dict[str, int]:
    try:
        raw = _read_relative(previous_path, "continuation.json", 32_000)
    except FileNotFoundError:
        raw = None
    if raw is not None:
        if bootstrap_warmup is not None:
            raise CaptureError("bootstrap warmup cannot be supplied after a chained run")
        prior = strict_json(raw)
        if (not isinstance(prior, dict) or prior.get("schema") != SCHEMA
                or prior.get("batch_sha256") != prior_sha
                or prior.get("symbol") != previous["symbol"]
                or prior.get("status") != "continued_complete"):
            raise CaptureError("predecessor continuation receipt is unbound")
        totals = prior.get("cumulative_requests")
        if not isinstance(totals, dict) or any(
                type(totals.get(key)) is not int or totals[key] < 0
                for key in ("attempted", "succeeded", "failed")):
            raise CaptureError("predecessor request totals are malformed")
        if totals["attempted"] != totals["succeeded"] + totals["failed"]:
            raise CaptureError("predecessor request denominator differs")
        return totals
    if bootstrap_warmup is None:
        raise CaptureError("first continuation needs its sealed warmup batch")
    warmup, warmup_view, _ = _verified_batch(bootstrap_warmup, root)
    if (warmup["symbol"] != previous["symbol"]
            or warmup["status"] != "incomplete"
            or warmup.get("initial_history_gap") is not True
            or warmup.get("next_aggregate_id") != previous.get("from_aggregate_id")
            or warmup_view["requests_attempted"] == 0
            or warmup["sealed_at"] > previous["started_at"]):
        raise CaptureError("warmup does not bind the first complete cursor")
    return {
        key: warmup_view[f"requests_{key}"] + previous[f"requests_{key}"]
        for key in ("attempted", "succeeded", "failed")
    }


def run_once(*, previous_batch: Path, output_dir: Path,
             bootstrap_warmup: Path | None = None,
             max_pages: int = 8, root: Path = CAPTURE_ROOT) -> dict[str, Any]:
    if type(max_pages) is not int or not 1 <= max_pages <= min(8, MAX_PAGES):
        raise CaptureError("continuation page cap must be 1..8")
    previous_path = _fixed_child(previous_batch, root)
    output_path = _fixed_child(output_dir, root)
    if output_path.exists() or previous_path == output_path:
        raise CaptureError("continuation output must be new")
    with _one_capture_lock(root, previous_path.name.split("-")[1]):
        previous, view, prior_sha = _verified_batch(previous_path, root)
        if (previous["status"] != "complete_incremental_batch"
                or view["status"] != "complete_incremental_batch"
                or previous.get("cursor_gap") or previous.get("page_gap")
                or previous.get("backlog_unresolved")
                or type(previous.get("next_aggregate_id")) is not int):
            raise CaptureError("predecessor is incomplete or lacks a sealed cursor")
        symbol = previous["symbol"]
        if output_path.name.split("-")[1] != symbol:
            raise CaptureError("successor symbol differs from predecessor")
        totals = _prior_totals(previous_path, previous, prior_sha,
                               bootstrap_warmup, root)
        successor = capture_once(
            output_path, symbol=symbol,
            from_id=previous["next_aggregate_id"], max_pages=max_pages)
        current_raw = _read_relative(output_path, "capture-batch.json", 32_000)
        current_sha = _sha(current_raw)
        cumulative = {
            key: totals[key] + successor[f"requests_{key}"]
            for key in ("attempted", "succeeded", "failed")
        }
        if cumulative["attempted"] != cumulative["succeeded"] + cumulative["failed"]:
            raise CaptureError("issued GET request chain lost a denominator")
        report = {
            "schema": SCHEMA, "symbol": symbol,
            "status": ("continued_complete" if successor["status"]
                       == "complete_incremental_batch" else "stopped_incomplete"),
            "previous_batch_path": str(previous_path),
            "previous_batch_sha256": prior_sha,
            "batch_sha256": current_sha,
            "from_aggregate_id": previous["next_aggregate_id"],
            "next_aggregate_id": successor["next_aggregate_id"],
            "prior_requests": totals,
            "current_requests": {
                key: successor[f"requests_{key}"]
                for key in ("attempted", "succeeded", "failed")
            },
            "cumulative_requests": cumulative,
            "continuation_source_sha256": _sha(Path(__file__).read_bytes()),
            "collector_source_sha256": _current_collector_sha256(),
            "stopped_reason": successor["failure"] or (
                successor["status"] if successor["status"]
                != "complete_incremental_batch" else None),
            "paper_result": "not_tested", "orders_placed": 0,
            "credentials_used": False,
        }
        _write_exclusive(output_path / "continuation.json",
                         json.dumps(report, sort_keys=True, indent=2,
                                    allow_nan=False).encode() + b"\n")
        return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--run-once", action="store_true")
    parser.add_argument("--previous-batch", type=Path)
    parser.add_argument("--bootstrap-warmup", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--max-pages", type=int, default=8)
    args = parser.parse_args(argv)
    if args.plan == args.run_once:
        raise CaptureError("choose exactly --plan or --run-once")
    if args.plan:
        print(json.dumps({"schema": SCHEMA, "mode": "manual_run_once",
                          "max_pages": min(8, MAX_PAGES),
                          "fixed_capture_root": str(CAPTURE_ROOT),
                          "timer_active": False, "orders": 0}, sort_keys=True))
        return 0
    if (args.previous_batch is None or args.output_dir is None
            or not args.previous_batch.is_absolute()
            or not args.output_dir.is_absolute()
            or (args.bootstrap_warmup is not None
                and not args.bootstrap_warmup.is_absolute())):
        raise CaptureError("run-once needs absolute registered batch paths")
    report = run_once(
        previous_batch=args.previous_batch, output_dir=args.output_dir,
        bootstrap_warmup=args.bootstrap_warmup, max_pages=args.max_pages)
    print(json.dumps({"status": report["status"],
                      "receipt": str(args.output_dir / "continuation.json"),
                      "cumulative_requests": report["cumulative_requests"]},
                     sort_keys=True))
    return 0 if report["status"] == "continued_complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
