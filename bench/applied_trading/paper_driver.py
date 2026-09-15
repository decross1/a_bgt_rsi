"""Deterministic, offline spot paper-intent driver for one frozen applied_trial/v1.

It has no market connector, order surface, account, wallet or model call. This
No model calls or orders are present in this paper-only driver.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .projection import project
from .trial_contract import (
    RESULT_SCHEMA,
    TrialError,
    canonical_sha256,
    load_trial,
    sha256,
    utc,
)

MAX_SCHEDULED_CELLS = 1_600
LEDGER_SCHEMA = "applied-trial-paper-cell/v1"
PROJECTION_SCHEMA = "applied-trial-paper-projection/v1"


def _rfc3339(t: datetime) -> str:
    return t.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _schedule(manifest: dict) -> list[tuple[str, datetime]]:
    split = manifest["split"]
    start = utc(split["forward_start"], "forward start")
    end = utc(split["forward_end"], "forward end")
    if start.minute or start.second or start.microsecond or end.minute or end.second or end.microsecond:
        raise TrialError("v1 decision grid starts and ends on complete UTC hours")
    interval = timedelta(seconds=manifest["policy"]["decision_interval_s"])
    cells: list[tuple[str, datetime]] = []
    at = start
    while at < end:
        for symbol in manifest["source"]["symbols"]:
            cells.append((symbol, at))
            if len(cells) > MAX_SCHEDULED_CELLS:
                raise TrialError("registered forward window exceeds schedule bound")
        at += interval
    return cells


def _index_observations(manifest: dict, observations: list[dict]) -> dict[tuple[str, datetime], dict]:
    start = utc(manifest["split"]["forward_start"], "forward start")
    end = utc(manifest["split"]["forward_end"], "forward end")
    indexed: dict[tuple[str, datetime], dict] = {}
    for row in observations:
        at = utc(row["decision_at"], "observation decision")
        if not start <= at < end or at.minute or at.second or at.microsecond:
            raise TrialError("observation is outside the frozen forward decision grid")
        key = (row["symbol"], at)
        if key in indexed:
            raise TrialError("ambiguous observation for one scheduled opportunity")
        indexed[key] = row
    return indexed


def _index_quotes(quotes: list[dict]) -> dict[str, list[dict]]:
    indexed: dict[str, list[dict]] = defaultdict(list)
    for row in quotes:
        indexed[row["symbol"]].append(row)
    for rows in indexed.values():
        rows.sort(key=lambda row: (utc(row["available_at"], "quote available"), row["quote_id"]))
    return indexed


def _valid_quote_after(
    rows: list[dict], earliest: datetime, latest: datetime, *, side: str,
    paper_size_quote: float, max_quote_receive_delay_s: int,
    entry_ask: float | None = None,
) -> dict | None:
    for row in rows:
        available = utc(row["available_at"], "quote available")
        if available < earliest:
            continue
        if available > latest:
            break
        if not row["book_valid"] or not row["sequence_valid"]:
            continue
        # REST depth provides no venue event time. The request must begin
        # after the frozen latency/hold boundary; receipt alone is insufficient.
        request_started = utc(row["request_started_at"], "quote request start")
        if request_started < earliest:
            continue
        if (available - request_started).total_seconds() > max_quote_receive_delay_s:
            continue
        if side == "entry" and row["ask_size_base"] * row["ask"] >= paper_size_quote:
            return row
        if side == "exit" and entry_ask is not None and row["bid_size_base"] >= paper_size_quote / entry_ask:
            return row
    return None


def _cost_floor_bps(obs: dict, manifest: dict) -> float:
    mid = (obs["bid"] + obs["ask"]) / 2
    spread_bps = 10_000 * (obs["ask"] - obs["bid"]) / mid
    cost = manifest["cost"]
    return spread_bps + 2 * cost["fee_leg_bps"] + 2 * cost["slippage_leg_bps"]


def _predicted_bps(obs: dict, manifest: dict, arm: str) -> float:
    policy = manifest["policy"][arm]
    if arm == "baseline":
        return policy["intercept_bps"] + policy["momentum_weight_bps"] * obs["momentum_bps"]
    return (
        policy["intercept_bps"]
        + policy["flow_weight_bps"] * obs["flow_imbalance"]
        + policy["depletion_weight_bps"] * obs["ask_depletion"]
        + policy["momentum_weight_bps"] * obs["momentum_bps"]
    )


def _paper_arm(
    *, arm: str, obs: dict, at: datetime, manifest: dict, quotes: list[dict],
    busy_until: datetime | None,
) -> tuple[dict[str, Any], datetime | None]:
    policy = manifest["policy"]
    cost_floor = _cost_floor_bps(obs, manifest)
    predicted = _predicted_bps(obs, manifest, arm)
    intent = predicted > cost_floor
    if arm == "candidate":
        candidate = policy["candidate"]
        intent = intent and obs["flow_imbalance"] >= candidate["min_flow"] and obs["ask_depletion"] >= candidate["min_depletion"]
    base = {"status": "no_intent", "reason": "cost_or_signal_gate", "predicted_move_bps": predicted, "decision_cost_floor_bps": cost_floor, "entry_quote_id": None, "exit_quote_id": None, "paper_net_bps": None, "paper_net_doubled_cost_bps": None}
    if not intent:
        return base, busy_until
    if busy_until is not None and at < busy_until:
        return {**base, "status": "not_run", "reason": "same_slot_exposure_cap"}, busy_until
    latency = timedelta(seconds=policy["latency_s"])
    entry = _valid_quote_after(
        quotes, at + latency, at + timedelta(seconds=policy["entry_timeout_s"]),
        side="entry", paper_size_quote=policy["paper_size_quote"],
        max_quote_receive_delay_s=policy["max_quote_receive_delay_s"],
    )
    if entry is None:
        return {**base, "status": "not_run", "reason": "no_later_valid_entry_quote"}, busy_until
    entry_at = utc(entry["available_at"], "entry available")
    exit_earliest = entry_at + timedelta(seconds=policy["hold_s"])
    exit_quote = _valid_quote_after(
        quotes, exit_earliest,
        exit_earliest + timedelta(seconds=policy["exit_timeout_s"]),
        side="exit", paper_size_quote=policy["paper_size_quote"],
        max_quote_receive_delay_s=policy["max_quote_receive_delay_s"],
        entry_ask=entry["ask"],
    )
    if exit_quote is None:
        # Once an entry was simulated, a missing exit is an unresolved paper
        # position. Further same-slot positions are withheld until trial close.
        trial_close = utc(manifest["split"]["forward_end"], "forward end") + timedelta(seconds=policy["hold_s"] + policy["exit_timeout_s"])
        return {**base, "status": "not_run", "reason": "no_later_valid_exit_quote", "entry_quote_id": entry["quote_id"]}, trial_close
    exit_at = utc(exit_quote["available_at"], "exit available")
    gross_bps = 10_000 * (exit_quote["bid"] / entry["ask"] - 1)
    cost = manifest["cost"]
    leg_cost = 2 * (cost["fee_leg_bps"] + cost["slippage_leg_bps"])
    net_bps = gross_bps - leg_cost
    doubled_net_bps = gross_bps - cost["double_multiplier"] * leg_cost
    if not all(math.isfinite(x) for x in (gross_bps, net_bps, doubled_net_bps)):
        raise TrialError("paper cash flow is nonfinite")
    return ({**base, "status": "filled_paper", "reason": "valid_later_bid_ask", "entry_quote_id": entry["quote_id"], "exit_quote_id": exit_quote["quote_id"], "paper_net_bps": net_bps, "paper_net_doubled_cost_bps": doubled_net_bps}, exit_at)


def evaluate(
    manifest: dict, capture: dict, observations: list[dict], quotes: list[dict], raw_sha256: dict[str, str]
) -> tuple[dict, list[dict]]:
    schedule = _schedule(manifest)
    by_observation = _index_observations(manifest, observations)
    by_quote = _index_quotes(quotes)
    capture_seal = utc(capture["capture_sealed_at"], "capture seal")
    policy = manifest["policy"]
    final_reserve = timedelta(seconds=policy["hold_s"] + policy["exit_timeout_s"])
    complete = capture_seal >= utc(manifest["split"]["forward_end"], "forward end") + final_reserve
    busy: dict[tuple[str, str], datetime | None] = defaultdict(lambda: None)
    ledger: list[dict] = []
    valid_cells_by_day: dict[str, int] = defaultdict(int)
    fillable_days: set[str] = set()
    source_missing = 0
    invalid_source = 0
    future_unissued = 0
    for index, (symbol, at) in enumerate(schedule):
        obs = by_observation.get((symbol, at))
        source_status = "valid"
        if at > capture_seal:
            source_status = "future_unissued"
            future_unissued += 1
        elif obs is None:
            source_status = "missing_observation"
            source_missing += 1
        elif (
            not obs["book_valid"] or not obs["sequence_valid"]
            or (at - utc(obs["available_at"], "observation available")).total_seconds() > policy["max_observation_age_s"]
        ):
            source_status = "invalid_or_stale_observation"
            invalid_source += 1
        if source_status == "valid":
            valid_cells_by_day[at.date().isoformat()] += 1
            candidate, busy[(symbol, "candidate")] = _paper_arm(
                arm="candidate", obs=obs, at=at, manifest=manifest,
                quotes=by_quote.get(symbol, []), busy_until=busy[(symbol, "candidate")],
            )
            baseline, busy[(symbol, "baseline")] = _paper_arm(
                arm="baseline", obs=obs, at=at, manifest=manifest,
                quotes=by_quote.get(symbol, []), busy_until=busy[(symbol, "baseline")],
            )
            if candidate["status"] == "filled_paper":
                fillable_days.add(at.date().isoformat())
        else:
            withheld = {"status": "not_run", "reason": source_status, "predicted_move_bps": None, "decision_cost_floor_bps": None, "entry_quote_id": None, "exit_quote_id": None, "paper_net_bps": None, "paper_net_doubled_cost_bps": None}
            candidate = withheld.copy()
            baseline = withheld.copy()
        ledger.append({
            "schema": LEDGER_SCHEMA,
            "cell_id": f"{manifest['trial_id']}.{index:04d}",
            "trial_id": manifest["trial_id"],
            "manifest_sha256": raw_sha256["manifest.json"],
            "symbol": symbol,
            "decision_at": _rfc3339(at),
            "source_status": source_status,
            "observation_id": obs["observation_id"] if source_status == "valid" else None,
            "observation_raw_sha256": obs["raw_sha256"] if source_status == "valid" else None,
            "candidate": candidate,
            "baseline": baseline,
            "no_trade_paper_net_bps": 0.0 if source_status == "valid" else None,
        })
    def arm_metrics(arm: str) -> dict:
        rows = [cell[arm] for cell in ledger]
        fills = [row for row in rows if row["status"] == "filled_paper"]
        base_sum = sum(row["paper_net_bps"] for row in fills)
        double_sum = sum(row["paper_net_doubled_cost_bps"] for row in fills)
        return {
            "intents": sum(row["status"] in {"filled_paper", "not_run"} and row["reason"] not in {"missing_observation", "invalid_or_stale_observation", "future_unissued"} for row in rows),
            "paper_fills": len(fills),
            "not_run": sum(row["status"] == "not_run" for row in rows),
            "paper_net_bps_sum": base_sum,
            "paper_net_bps_per_schedule": base_sum / len(schedule),
            "paper_net_bps_per_fill": base_sum / len(fills) if fills else None,
            "paper_net_doubled_cost_bps_sum": double_sum,
            "paper_net_doubled_cost_bps_per_schedule": double_sum / len(schedule),
        }
    candidate = arm_metrics("candidate")
    baseline = arm_metrics("baseline")
    gates = manifest["gates"]
    scheduled_by_day: dict[str, int] = defaultdict(int)
    for _symbol, at in schedule:
        scheduled_by_day[at.date().isoformat()] += 1
    valid_days = {
        day for day, count in valid_cells_by_day.items()
        if count / scheduled_by_day[day] >= gates["min_valid_decision_fraction_per_day"]
    }
    operational_gate = (
        len(valid_days) >= gates["min_valid_forward_days"]
        and candidate["paper_fills"] >= gates["min_fillable_candidate"]
        and len(fillable_days) >= gates["min_fillable_days"]
    )
    economic_gate = (
        candidate["paper_net_bps_per_schedule"] > gates["min_incremental_net_bps_per_schedule"]
        and candidate["paper_net_bps_per_schedule"] > baseline["paper_net_bps_per_schedule"]
        and candidate["paper_net_doubled_cost_bps_per_schedule"] > max(0, baseline["paper_net_doubled_cost_bps_per_schedule"])
    )
    # The pure scorer cannot prove that locally claimed receive times were
    # prospective or evaluate all clustered/placebo falsifications. An external
    # source/grade admission may later promote a sealed positive paper result.
    disposition = (
        "not_tested" if not complete else
        "not_tested" if not operational_gate else
        "negative" if not economic_gate else
        "needs_replication"
    )
    result = {
        "schema": RESULT_SCHEMA,
        "trial_id": manifest["trial_id"],
        "trial_type": manifest["trial_type"],
        "paper_only": True,
        "manifest_sha256": raw_sha256["manifest.json"],
        "manifest_canonical_sha256": canonical_sha256(manifest),
        "capture_receipt_sha256": raw_sha256["capture-receipt.json"],
        "observations_sha256": raw_sha256["observations.jsonl"],
        "quotes_sha256": raw_sha256["quotes.jsonl"],
        "capture_chain_root_sha256": capture["chain_root_sha256"],
        "registered_source_id": manifest["source"]["source_id"],
        "registered_venue": manifest["source"]["venue"],
        "development_archive_sha256": manifest["source"]["development_archive_sha256"],
        "training_receipt_sha256": manifest["source"]["training_receipt_sha256"],
        "validation_receipt_sha256": manifest["source"]["validation_receipt_sha256"],
        "forward_start": manifest["split"]["forward_start"],
        "forward_end": manifest["split"]["forward_end"],
        "capture_sealed_at": capture["capture_sealed_at"],
        "run_status": "complete" if complete else "incomplete",
        "disposition": disposition,
        "scheduled_cells": len(schedule),
        "valid_days": len(valid_days),
        "fillable_candidate_days": len(fillable_days),
        "missing_observation_cells": source_missing,
        "invalid_or_stale_observation_cells": invalid_source,
        "future_unissued_cells": future_unissued,
        "candidate": candidate,
        "equal_hold_exposure_baseline": baseline,
        "no_trade_paper_net_bps_per_schedule": 0.0,
        "operational_gate": operational_gate,
        "economic_gate": economic_gate,
        "capture_admission": "unverified_external_proof",
        "placebo_admission": "not_tested",
        "promotion_to_science_or_live_orders": False,
    }
    return result, ledger


def _write_new_regular(directory: Path, name: str, data: bytes) -> None:
    fd = os.open(directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb", closefd=False) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(fd)
    finally:
        os.close(fd)


def write_outputs(output_dir: Path, manifest: dict, result: dict, ledger: list[dict]) -> None:
    parent = output_dir.parent
    if parent.is_symlink() or not parent.is_dir() or output_dir.exists():
        raise TrialError("output must be a new direct child of an existing regular directory")
    output_dir.mkdir(mode=0o700)
    ledger_data = b"".join(
        json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"
        for row in ledger
    )
    result["paper_ledger_sha256"] = sha256(ledger_data)
    projection = project(manifest, result, ledger)
    _write_new_regular(output_dir, "paper-ledger.jsonl", ledger_data)
    _write_new_regular(output_dir, "trial-result.json", (json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n").encode())
    _write_new_regular(output_dir, "paper-projection.json", (json.dumps(projection, sort_keys=True, indent=2, allow_nan=False) + "\n").encode())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline, paper-only spot applied trial")
    parser.add_argument("--trial-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if not args.trial_dir.is_absolute() or not args.output_dir.is_absolute():
        raise TrialError("trial and output paths must be absolute")
    manifest, capture, observations, quotes, raw_sha256 = load_trial(args.trial_dir)
    result, ledger = evaluate(manifest, capture, observations, quotes, raw_sha256)
    write_outputs(args.output_dir, manifest, result, ledger)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
