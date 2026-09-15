"""Closed, stdlib-only applied-trial contract. No network or orders.

Do not treat self-consistent capture timestamps as
independent proof of prospective acquisition; external collector admission is
required before a positive paper finding.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MANIFEST_SCHEMA = "applied_trial/v1"
CAPTURE_SCHEMA = "applied-trial-capture-receipt/v1"
OBS_SCHEMA = "applied-trial-spot-observation/v1"
QUOTE_SCHEMA = "applied-trial-spot-quote/v1"
RESULT_SCHEMA = "applied-trial-result/v1"
DISPOSITIONS = frozenset(
    {"not_tested", "invalid", "negative", "paper_supported", "needs_replication"}
)
VENUES = frozenset({"binance_spot_public"})
FILE_LIMITS = {
    "manifest.json": 128_000,
    "capture-receipt.json": 128_000,
    "observations.jsonl": 16_000_000,
    "quotes.jsonl": 32_000_000,
}
HEX64 = re.compile(r"^[0-9a-f]{64}$")
ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,95}$")
MAX_ROWS = 60_000
MAX_LINE_BYTES = 8_192


class TrialError(ValueError):
    """A bounded input is malformed or not linked to its frozen trial."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_sha256(value: Any) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    )


def utc(value: Any, where: str) -> datetime:
    if not isinstance(value, str):
        raise TrialError(f"{where} must be RFC3339 UTC")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TrialError(f"{where} is not RFC3339") from exc
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        raise TrialError(f"{where} must have UTC offset")
    return parsed.astimezone(timezone.utc)


def number(value: Any, where: str, *, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise TrialError(f"{where} must be a number")
    out = float(value)
    if not math.isfinite(out) or not low <= out <= high:
        raise TrialError(f"{where} is nonfinite or out of bounds")
    return out


def integer(value: Any, where: str, *, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise TrialError(f"{where} must be a bounded integer")
    return value


def object_keys(value: Any, required: set[str], where: str) -> dict:
    if not isinstance(value, dict) or set(value) != required:
        raise TrialError(f"{where} has missing or unexpected fields")
    return value


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict:
    out = {}
    for key, value in pairs:
        if key in out:
            raise TrialError("duplicate JSON object field")
        out[key] = value
    return out


def _bad_constant(value: str) -> None:
    raise TrialError(f"nonfinite JSON constant {value}")


def strict_json(data: bytes, where: str) -> Any:
    try:
        return json.loads(
            data,
            object_pairs_hook=_unique_pairs,
            parse_constant=_bad_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TrialError(f"{where} is not strict JSON") from exc


def read_fixed(trial_dir: Path, name: str) -> bytes:
    """Read a fixed-name regular input with a hard size bound and no leaf redirect."""
    if name not in FILE_LIMITS or trial_dir.is_symlink() or not trial_dir.is_dir():
        raise TrialError("trial root or fixed input name is invalid")
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
    root_fd = os.open(trial_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open(name, flags, dir_fd=root_fd)
        try:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_size > FILE_LIMITS[name]:
                raise TrialError(f"{name} is non-regular or oversized")
            chunks: list[bytes] = []
            remaining = FILE_LIMITS[name] + 1
            while remaining:
                part = os.read(fd, min(remaining, 65_536))
                if not part:
                    break
                chunks.append(part)
                remaining -= len(part)
            data = b"".join(chunks)
            after = os.fstat(fd)
            if len(data) > FILE_LIMITS[name] or (
                before.st_size,
                before.st_mtime_ns,
                before.st_ino,
            ) != (
                after.st_size,
                after.st_mtime_ns,
                after.st_ino,
            ):
                raise TrialError(f"{name} changed during read")
            return data
        finally:
            os.close(fd)
    except OSError as exc:
        raise TrialError(f"{name} cannot be read safely") from exc
    finally:
        os.close(root_fd)


def read_jsonl(data: bytes, where: str) -> list[dict]:
    rows: list[dict] = []
    for line in data.splitlines():
        if not line.strip():
            continue
        if len(line) > MAX_LINE_BYTES or len(rows) >= MAX_ROWS:
            raise TrialError(f"{where} exceeds row bound")
        row = strict_json(line, where)
        if not isinstance(row, dict):
            raise TrialError(f"{where} row is not an object")
        rows.append(row)
    return rows


def _digest(value: Any, where: str) -> str:
    if not isinstance(value, str) or HEX64.fullmatch(value) is None:
        raise TrialError(f"{where} is not a SHA-256 hex digest")
    return value


def _id(value: Any, where: str) -> str:
    if not isinstance(value, str) or ID.fullmatch(value) is None:
        raise TrialError(f"{where} is not a bounded ID")
    return value


def validate_manifest(
    value: Any, *, campaign_link_matches: Callable[[dict], bool] | None = None
) -> dict:
    manifest = object_keys(
        value,
        {"schema", "trial_id", "trial_type", "paper_only", "prior", "source", "split", "policy", "cost", "gates"},
        "manifest",
    )
    if manifest["schema"] != MANIFEST_SCHEMA or manifest["trial_type"] != "spot_liquidity_state" or manifest["paper_only"] is not True:
        raise TrialError("v1 is a paper-only spot-liquidity trial")
    _id(manifest["trial_id"], "trial_id")
    prior = object_keys(manifest["prior"], {"mechanism_id", "classification", "url", "source_campaign_link"}, "prior")
    _id(prior["mechanism_id"], "mechanism_id")
    if prior["classification"] != "known_prior":
        raise TrialError("v1 requires a declared known-prior mechanism")
    if (
        not isinstance(prior["url"], str)
        or not prior["url"].startswith("https://")
        or len(prior["url"]) > 300
        or any(ch.isspace() for ch in prior["url"])
    ):
        raise TrialError("mechanism source URL must be a bounded HTTPS citation")
    link = prior["source_campaign_link"]
    if link is not None:
        if not isinstance(link, dict) or set(link) != {
            "schema_version", "campaign_id", "campaign_manifest_sha256",
            "research_question_id", "research_question_sha256", "topic_id", "topic_sha256",
        } or link["schema_version"] != "research-campaign-link/v1":
            raise TrialError("campaign link is not the exact registered shape")
        for key in ("campaign_manifest_sha256", "research_question_sha256", "topic_sha256"):
            _digest(link[key], f"campaign.{key}")
        for key in ("campaign_id", "research_question_id", "topic_id"):
            _id(link[key], f"campaign.{key}")
        if campaign_link_matches is None or campaign_link_matches(link) is not True:
            raise TrialError("unbound campaign link; load and match its campaign first")
    source = object_keys(manifest["source"], {"venue", "source_id", "symbols", "collector_source_sha256", "development_archive_sha256", "training_receipt_sha256", "validation_receipt_sha256"}, "source")
    if source["venue"] not in VENUES:
        raise TrialError("unregistered public spot venue")
    _id(source["source_id"], "source_id")
    if source["source_id"] != "binance-spot-public":
        raise TrialError("source ID does not match the closed public venue")
    _digest(source["collector_source_sha256"], "collector source")
    _digest(source["development_archive_sha256"], "development archive")
    _digest(source["training_receipt_sha256"], "sealed training receipt")
    _digest(source["validation_receipt_sha256"], "sealed validation receipt")
    if not isinstance(source["symbols"], list) or not 1 <= len(source["symbols"]) <= 2 or len(set(source["symbols"])) != len(source["symbols"]):
        raise TrialError("v1 has one or two unique spot symbols")
    if not set(source["symbols"]) <= {"BTCUSDT", "ETHUSDT"}:
        raise TrialError("symbol does not match the registered public venue")
    split = object_keys(manifest["split"], {"development_start", "development_end", "validation_start", "validation_end", "forward_start", "forward_end", "frozen_at"}, "split")
    dev_start, dev_end, val_start, val_end, forward_start, forward_end, frozen = (
        utc(split[key], f"split.{key}") for key in (
            "development_start", "development_end", "validation_start", "validation_end", "forward_start", "forward_end", "frozen_at"
        )
    )
    if not (dev_start < dev_end <= val_start < val_end <= frozen < forward_start < forward_end):
        raise TrialError("split/freeze chronology is not sealed and ordered")
    if (forward_end - forward_start).days > 31 or (forward_end - forward_start).total_seconds() < 86400:
        raise TrialError("forward window is not bounded to a month")
    policy = object_keys(manifest["policy"], {"decision_interval_s", "hold_s", "latency_s", "entry_timeout_s", "exit_timeout_s", "max_observation_age_s", "max_quote_receive_delay_s", "paper_size_quote", "max_open_positions_per_symbol", "candidate", "baseline"}, "policy")
    if policy["decision_interval_s"] != 3600 or policy["hold_s"] not in (3600, 14400) or policy["max_open_positions_per_symbol"] != 1:
        raise TrialError("v1 has hourly long/flat decisions and a frozen 1h/4h hold")
    integer(policy["latency_s"], "latency", low=1, high=60)
    integer(policy["entry_timeout_s"], "entry timeout", low=1, high=300)
    integer(policy["exit_timeout_s"], "exit timeout", low=1, high=300)
    integer(policy["max_observation_age_s"], "observation age", low=1, high=3600)
    integer(policy["max_quote_receive_delay_s"], "quote receive delay", low=1, high=30)
    number(policy["paper_size_quote"], "paper size", low=1, high=1000)
    candidate = object_keys(policy["candidate"], {"intercept_bps", "flow_weight_bps", "depletion_weight_bps", "momentum_weight_bps", "min_flow", "min_depletion"}, "candidate")
    for key in ("intercept_bps", "flow_weight_bps", "depletion_weight_bps", "momentum_weight_bps"):
        number(candidate[key], f"candidate.{key}", low=-1000, high=1000)
    number(candidate["min_flow"], "candidate.min_flow", low=-1, high=1)
    number(candidate["min_depletion"], "candidate.min_depletion", low=0, high=1)
    baseline = object_keys(policy["baseline"], {"intercept_bps", "momentum_weight_bps"}, "baseline")
    for key in baseline:
        number(baseline[key], f"baseline.{key}", low=-1000, high=1000)
    cost = object_keys(manifest["cost"], {"fee_leg_bps", "slippage_leg_bps", "double_multiplier", "fee_source_url"}, "cost")
    number(cost["fee_leg_bps"], "fee leg", low=0, high=100)
    number(cost["slippage_leg_bps"], "slippage leg", low=0, high=100)
    if cost["double_multiplier"] != 2 or not isinstance(cost["fee_source_url"], str) or not cost["fee_source_url"].startswith("https://"):
        raise TrialError("cost sensitivity or fee-source declaration differs")
    if source["venue"] == "binance_spot_public" and (
        cost["fee_leg_bps"] < 10 or cost["fee_source_url"] != "https://www.binance.com/en/support/faq/detail/115000429332"
    ):
        raise TrialError("ordinary Binance reference fee floor is unbound")
    gates = object_keys(manifest["gates"], {"min_valid_forward_days", "min_valid_decision_fraction_per_day", "min_fillable_candidate", "min_fillable_days", "min_incremental_net_bps_per_schedule"}, "gates")
    integer(gates["min_valid_forward_days"], "valid-day gate", low=10, high=31)
    number(gates["min_valid_decision_fraction_per_day"], "daily source coverage", low=0.5, high=1)
    integer(gates["min_fillable_candidate"], "fillable gate", low=10, high=1000)
    integer(gates["min_fillable_days"], "fillable-day gate", low=5, high=31)
    number(gates["min_incremental_net_bps_per_schedule"], "incremental net gate", low=0, high=1000)
    return manifest


def validate_capture(value: Any, manifest: dict, observations: bytes, quotes: bytes) -> dict:
    receipt = object_keys(value, {"schema", "trial_id", "source_id", "collector_source_sha256", "observations_sha256", "quotes_sha256", "capture_started_at", "capture_sealed_at", "chain_root_sha256"}, "capture receipt")
    if receipt["schema"] != CAPTURE_SCHEMA or receipt["trial_id"] != manifest["trial_id"] or receipt["source_id"] != manifest["source"]["source_id"]:
        raise TrialError("capture receipt does not bind registered trial/source")
    for key in ("collector_source_sha256", "observations_sha256", "quotes_sha256", "chain_root_sha256"):
        _digest(receipt[key], f"capture.{key}")
    if receipt["collector_source_sha256"] != manifest["source"]["collector_source_sha256"] or receipt["observations_sha256"] != sha256(observations) or receipt["quotes_sha256"] != sha256(quotes):
        raise TrialError("capture receipt differs from exact source or bytes")
    if not utc(receipt["capture_started_at"], "capture start") <= utc(manifest["split"]["forward_start"], "forward start") < utc(receipt["capture_sealed_at"], "capture seal"):
        raise TrialError("capture period cannot establish prospective forward observation")
    return receipt


def validate_observation(row: Any, manifest: dict) -> dict:
    row = object_keys(row, {"schema", "observation_id", "source_id", "symbol", "decision_at", "timestamp_basis", "venue_event_at", "request_started_at", "received_at", "available_at", "raw_sha256", "book_valid", "sequence_valid", "bid", "ask", "flow_imbalance", "ask_depletion", "momentum_bps"}, "observation")
    if row["schema"] != OBS_SCHEMA or row["source_id"] != manifest["source"]["source_id"] or row["symbol"] not in manifest["source"]["symbols"]:
        raise TrialError("observation source/symbol is unregistered")
    _id(row["observation_id"], "observation ID")
    _digest(row["raw_sha256"], "observation raw frame")
    decision = utc(row["decision_at"], "decision")
    request_started = utc(row["request_started_at"], "observation request start")
    received = utc(row["received_at"], "observation received")
    available = utc(row["available_at"], "observation available")
    if row["timestamp_basis"] != "local_http_snapshot" or row["venue_event_at"] is not None:
        raise TrialError("REST book observation must not invent a venue event time")
    if not (request_started <= received <= available <= decision):
        raise TrialError("observation is not available as of decision")
    if type(row["book_valid"]) is not bool or type(row["sequence_valid"]) is not bool:
        raise TrialError("observation book/gap proof is malformed")
    bid = number(row["bid"], "observation bid", low=0.000001, high=1e9)
    ask = number(row["ask"], "observation ask", low=0.000001, high=1e9)
    if bid >= ask:
        raise TrialError("observation has no positive spread")
    number(row["flow_imbalance"], "flow", low=-1, high=1)
    number(row["ask_depletion"], "ask depletion", low=0, high=1)
    number(row["momentum_bps"], "momentum", low=-10000, high=10000)
    return row


def validate_quote(row: Any, manifest: dict) -> dict:
    row = object_keys(row, {"schema", "quote_id", "source_id", "symbol", "timestamp_basis", "venue_event_at", "request_started_at", "received_at", "available_at", "raw_sha256", "book_valid", "sequence_valid", "bid", "ask", "bid_size_base", "ask_size_base"}, "quote")
    if row["schema"] != QUOTE_SCHEMA or row["source_id"] != manifest["source"]["source_id"] or row["symbol"] not in manifest["source"]["symbols"]:
        raise TrialError("quote source/symbol is unregistered")
    _id(row["quote_id"], "quote ID")
    _digest(row["raw_sha256"], "quote raw frame")
    request_started = utc(row["request_started_at"], "quote request start")
    received = utc(row["received_at"], "quote received")
    available = utc(row["available_at"], "quote available")
    if row["timestamp_basis"] != "local_http_snapshot" or row["venue_event_at"] is not None:
        raise TrialError("REST book quote must not invent a venue event time")
    if not request_started <= received <= available:
        raise TrialError("quote chronology is impossible")
    if type(row["book_valid"]) is not bool or type(row["sequence_valid"]) is not bool:
        raise TrialError("quote book/gap proof is malformed")
    bid = number(row["bid"], "quote bid", low=0.000001, high=1e9)
    ask = number(row["ask"], "quote ask", low=0.000001, high=1e9)
    if bid >= ask:
        raise TrialError("quote has no positive spread")
    number(row["bid_size_base"], "quote bid depth", low=0, high=1e9)
    number(row["ask_size_base"], "quote ask depth", low=0, high=1e9)
    return row


def load_trial(trial_dir: Path) -> tuple[dict, dict, list[dict], list[dict], dict[str, str]]:
    raw = {name: read_fixed(trial_dir, name) for name in FILE_LIMITS}
    manifest = validate_manifest(strict_json(raw["manifest.json"], "manifest"))
    observations = read_jsonl(raw["observations.jsonl"], "observations")
    quotes = read_jsonl(raw["quotes.jsonl"], "quotes")
    capture = validate_capture(
        strict_json(raw["capture-receipt.json"], "capture receipt"),
        manifest,
        raw["observations.jsonl"],
        raw["quotes.jsonl"],
    )
    seen_obs: set[str] = set()
    capture_start = utc(capture["capture_started_at"], "capture start")
    capture_seal = utc(capture["capture_sealed_at"], "capture seal")
    for row in observations:
        validate_observation(row, manifest)
        if not capture_start <= utc(row["received_at"], "observation received") <= capture_seal:
            raise TrialError("observation receipt is outside capture lifecycle")
        if row["observation_id"] in seen_obs:
            raise TrialError("duplicate observation ID")
        seen_obs.add(row["observation_id"])
    seen_quotes: set[str] = set()
    for row in quotes:
        validate_quote(row, manifest)
        if not capture_start <= utc(row["received_at"], "quote received") <= capture_seal:
            raise TrialError("quote receipt is outside capture lifecycle")
        if row["quote_id"] in seen_quotes:
            raise TrialError("duplicate quote ID")
        seen_quotes.add(row["quote_id"])
    return manifest, capture, observations, quotes, {name: sha256(data) for name, data in raw.items()}
