"""Offline, nonexecutable H1 displayed-quote diagnostic for public Spot REST frames.

This is intentionally separate from applied_trial/v1: REST L5 has no depth-event
sequence proof, and no result from this module can become paper_supported.
Inputs are sealed public capture batches and the unchanged hourly feature builder.
There is no HTTP client, order connector, account, wallet, or model call here.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bench.applied_trading import prospective_hourly_features, public_spot_capture
from bench.applied_trading.collection_projection import _read_relative
from bench.applied_trading.prospective_hourly_features import (
    _canon,
    _sha,
    _source_batches,
    derive,
)
from bench.applied_trading.public_spot_capture import CaptureError, strict_json

PLAN_SCHEMA = "applied-h1-rest-reference-plan/v1"
RESULT_SCHEMA = "applied-h1-rest-reference-result/v1"
CELL_SCHEMA = "applied-h1-rest-reference-cell/v1"
# The unchanged feature builder accepts at most 96 sealed batches. At a
# five-minute cadence, one prior-hour witness and one-hour-plus exit reserve
# leave room for only a small pilot block. A month-wide result needs a
# separately bound aggregation of ordered blocks, not a larger unchecked read.
MAX_CELLS = 5
MAX_BATCHES = 96
MAX_FEATURE_BYTES = 2_000_000
FEE_URL = "https://www.binance.com/en/support/faq/detail/115000429332"
RULE_ORIGIN = "fixed_unfitted_engineering_preset/v1"
ENGINEERING_CANDIDATE = {
    "intercept_bps": 0, "momentum_weight_bps": 1,
    "flow_weight_bps": 60, "depletion_weight_bps": 80,
    "min_flow": 0.1, "min_depletion": 0.1,
}
ENGINEERING_BASELINE = {"intercept_bps": 0, "momentum_weight_bps": 1}


def _must(ok: bool, reason: str) -> None:
    if not ok:
        raise CaptureError(reason)


def _utc(raw: str, label: str) -> datetime:
    _must(isinstance(raw, str), f"{label} is not a timestamp")
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CaptureError(f"{label} is malformed") from exc
    _must(value.tzinfo is not None, f"{label} is timezone-naive")
    return value.astimezone(timezone.utc)


def _digest(value: object, label: str) -> str:
    _must(isinstance(value, str) and len(value) == 64
          and all(char in "0123456789abcdef" for char in value),
          f"{label} is not a SHA256 digest")
    return value


def _finite(value: object, label: str, lower: float, upper: float) -> float:
    _must(type(value) in (int, float), f"{label} is not numeric")
    numeric = float(value)
    _must(math.isfinite(numeric) and lower <= numeric <= upper,
          f"{label} is nonfinite or out of range")
    return numeric


def _integer(value: object, label: str, lower: int, upper: int) -> int:
    _must(type(value) is int and lower <= value <= upper,
          f"{label} is not a bounded integer")
    return value


def _source_sha(path: Path) -> str:
    return _sha(_read_relative(path.parent, path.name, 1_000_000))


def validate_plan(plan: dict, *, collector_source: Path,
                  feature_builder_source: Path) -> tuple[datetime, datetime, datetime]:
    _must(isinstance(plan, dict) and set(plan) == {
        "schema", "study_id", "symbol", "rule_origin",
        "topic_transfer_sha256", "source", "split", "policy", "cost",
    }, "REST reference plan has unknown or missing fields")
    _must(plan["schema"] == PLAN_SCHEMA and plan["symbol"] == "BTCUSDT"
          and plan["rule_origin"] == RULE_ORIGIN,
          "REST reference v1 is the fixed BTCUSDT H1 lane")
    _must(isinstance(plan["study_id"], str) and 3 <= len(plan["study_id"]) <= 80
          and all(c.isalnum() or c in "_-" for c in plan["study_id"]),
          "study ID is malformed")
    _digest(plan["topic_transfer_sha256"], "topic transfer SHA")
    source = plan["source"]
    _must(isinstance(source, dict) and set(source) == {
        "source_id", "collector_source_sha256", "feature_builder_source_sha256",
    } and source["source_id"] == "binance-spot-public",
          "REST source registration differs")
    _must(_digest(source["collector_source_sha256"], "collector SHA")
          == _source_sha(collector_source), "collector implementation changed")
    _must(_digest(source["feature_builder_source_sha256"], "builder SHA")
          == _source_sha(feature_builder_source), "feature implementation changed")
    split = plan["split"]
    _must(isinstance(split, dict) and set(split) == {
        "frozen_at", "forward_start", "forward_end",
    }, "forward split differs")
    frozen, start, end = (_utc(split[key], key) for key in (
        "frozen_at", "forward_start", "forward_end"))
    _must(frozen < start < end and start.minute == end.minute == 5
          and start.second == end.second == 0
          and start.microsecond == end.microsecond == 0
          and (end - start).total_seconds() % 3600 == 0
          and 2 <= (end - start).total_seconds() / 3600 <= MAX_CELLS,
          "forward 2–5h HH:05 pilot grid is unregistered or unfrozen")
    policy = plan["policy"]
    _must(isinstance(policy, dict) and set(policy) == {
        "hold_s", "latency_s", "entry_timeout_s", "exit_timeout_s",
        "max_quote_receive_delay_s", "max_observation_age_s",
        "paper_size_quote", "candidate", "baseline",
    }, "reference policy differs")
    _must(policy["hold_s"] == 3600, "H1 reference hold must be one hour")
    for key, lo, hi in (
        ("latency_s", 1, 60), ("entry_timeout_s", 60, 900),
        ("exit_timeout_s", 60, 900), ("max_quote_receive_delay_s", 1, 30),
        ("max_observation_age_s", 1, 300),
    ):
        _integer(policy[key], key, lo, hi)
    _finite(policy["paper_size_quote"], "reference size quote", 1, 1000)
    candidate, baseline = policy["candidate"], policy["baseline"]
    _must(isinstance(candidate, dict) and set(candidate) == {
        "intercept_bps", "momentum_weight_bps", "flow_weight_bps",
        "depletion_weight_bps", "min_flow", "min_depletion",
    } and isinstance(baseline, dict) and set(baseline) == {
        "intercept_bps", "momentum_weight_bps",
    }, "fixed signal arms differ")
    for key in ("intercept_bps", "momentum_weight_bps"):
        _finite(candidate[key], f"candidate {key}", -1000, 1000)
        _finite(baseline[key], f"baseline {key}", -1000, 1000)
        _must(candidate[key] == baseline[key],
              "momentum baseline does not match candidate intercept/weight")
    for key in ("flow_weight_bps", "depletion_weight_bps"):
        _finite(candidate[key], key, -1000, 1000)
    _finite(candidate["min_flow"], "minimum flow", -1, 1)
    _finite(candidate["min_depletion"], "minimum depletion", 0, 1)
    _must(candidate == ENGINEERING_CANDIDATE
          and baseline == ENGINEERING_BASELINE,
          "pilot signal differs from its unfitted engineering preset")
    cost = plan["cost"]
    _must(isinstance(cost, dict) and set(cost) == {
        "fee_leg_bps", "slippage_leg_bps", "double_multiplier",
        "fee_source_url",
    } and cost["double_multiplier"] == 2
          and cost["fee_source_url"] == FEE_URL,
          "ordinary reference cost source differs")
    _finite(cost["fee_leg_bps"], "fee per leg", 10, 100)
    _finite(cost["slippage_leg_bps"], "slippage per leg", 0, 100)
    return frozen, start, end


def _quote_receipt(depth: dict, batch_paths: list[Path]) -> dict:
    """Preserve raw GET identity and all five displayed levels; no sequence claim."""
    batch = batch_paths[depth["batch_index"]]
    journal = _read_relative(batch, "attempts.jsonl", 128_000).splitlines()
    row = strict_json(journal[depth["attempt_index"]])
    raw = _read_relative(batch, row["raw_relpath"], 16_384)
    _must(row["kind"] == "depth" and row["attempt_status"] == "succeeded"
          and row["http_status"] == 200 and row["raw_sha256"] == _sha(raw)
          and depth["raw_sha256"] == _sha(raw)
          and _utc(row["request_started_at"], "quote GET start") == depth["started"]
          and _utc(row["response_received_at"], "quote GET receipt") == depth["received"],
          "reference quote differs from sealed public GET")
    book = strict_json(raw)
    _must(book == depth["payload"] and type(book["lastUpdateId"]) is int
          and book["lastUpdateId"] >= 0, "REST book update ID differs")
    return {
        "quote_id": f"{depth['batch_index']:03d}-{depth['attempt_index']:03d}",
        "batch_capture_sha256": _sha(_read_relative(batch, "capture-batch.json", 32_000)),
        "source_kind": "rest_l5_displayed_quote",
        "url": row["url"], "http_status": 200,
        "request_started_at": row["request_started_at"],
        "response_received_at": row["response_received_at"],
        "raw_relpath": row["raw_relpath"], "raw_sha256": _sha(raw),
        "lastUpdateId": book["lastUpdateId"],
        "bids": book["bids"], "asks": book["asks"],
        "bid": depth["bid"], "ask": depth["ask"],
        "bid_size_base": float(book["bids"][0][1]),
        "ask_size_base": float(book["asks"][0][1]),
        "venue_event_at": None, "sequence_valid": False,
    }


def _first_reference_quote(depths: list[dict], batches: list[Path],
                           earliest: datetime, latest: datetime,
                           max_delay: int, *, side: str,
                           paper_size_quote: float,
                           entry_ask: float | None = None) -> dict | None:
    for frame in depths:
        if frame["received"] < earliest:
            continue
        if frame["received"] > latest:
            break
        if frame["started"] < earliest or (
            frame["received"] - frame["started"]
        ).total_seconds() > max_delay:
            continue
        receipt = _quote_receipt(frame, batches)
        if side == "entry" and (
            receipt["ask_size_base"] * receipt["ask"] >= paper_size_quote
        ):
            return receipt
        if side == "exit" and entry_ask is not None and (
            receipt["bid_size_base"] >= paper_size_quote / entry_ask
        ):
            return receipt
    return None


def _signal(feature: dict, policy: dict, arm: str, cost_floor: float) -> dict:
    candidate = policy["candidate"]
    base = policy["baseline"]
    momentum = _finite(feature["momentum_bps"], "feature momentum", -100_000, 100_000)
    predicted = base["intercept_bps"] + base["momentum_weight_bps"] * momentum
    if arm == "candidate":
        flow = _finite(feature["flow_imbalance"], "feature flow", -1, 1)
        depletion = _finite(feature["ask_depletion"], "visible size contraction", 0, 1)
        predicted += candidate["flow_weight_bps"] * flow
        predicted += candidate["depletion_weight_bps"] * depletion
        gate = flow >= candidate["min_flow"] and depletion >= candidate["min_depletion"]
    else:
        gate = True
    _must(math.isfinite(predicted), "reference predicted move is nonfinite")
    return {"predicted_move_bps": predicted,
            "intent": bool(gate and predicted > cost_floor),
            "signal_gate": bool(gate)}


def _forecast_square_error(predicted: float, realized_mid: float) -> float:
    squared = (predicted - realized_mid) ** 2
    _must(math.isfinite(squared), "reference forecast error is nonfinite")
    return squared


def evaluate(plan: dict, *, batch_paths: list[Path], feature_dir: Path,
             collector_source: Path, feature_builder_source: Path,
             plan_raw: bytes, topic_raw: bytes) -> tuple[dict, list[dict]]:
    _must(strict_json(plan_raw) == plan,
          "evaluated settings differ from hash-bound raw plan")
    _must(_sha(topic_raw) == plan["topic_transfer_sha256"],
          "evaluated H1 topic differs from hash-bound transfer artifact")
    topic = strict_json(topic_raw)
    _must(isinstance(topic, dict)
          and topic.get("schema") == "applied-topic-transfer-draft/v1"
          and topic.get("application_id") == "h1-btcusdt-strategic-liquidity-paper"
          and topic.get("primary_horizon_hours") == 1
          and isinstance(topic.get("prior"), dict)
          and topic["prior"].get("classification") == "known_prior"
          and isinstance(topic["prior"].get("mechanism_url"), str)
          and topic["prior"]["mechanism_url"].startswith("https://")
          and isinstance(topic.get("pipeline_action"), dict)
          and topic["pipeline_action"].get("science_ladder_changed") is False
          and topic["pipeline_action"].get("source_campaign_link") is None
          and topic["pipeline_action"].get("orders_authorized") is False,
          "H1 topic is not the known-prior independent paper application")
    _frozen, start, end = validate_plan(
        plan, collector_source=collector_source,
        feature_builder_source=feature_builder_source)
    _must(1 <= len(batch_paths) <= MAX_BATCHES
          and len(batch_paths) == len(set(batch_paths)),
          "REST source batch list is unbounded/duplicated")
    source_raw = _read_relative(feature_dir, "feature-source.json", 128_000)
    features_raw = _read_relative(feature_dir, "features.jsonl", MAX_FEATURE_BYTES)
    source = strict_json(source_raw)
    _must(isinstance(source, dict) and source["schema"] ==
          "applied-trial-prospective-h1-feature-source/v1"
          and source["symbol"] == plan["symbol"]
          and source["collector_source_sha256"] ==
          plan["source"]["collector_source_sha256"]
          and source["feature_builder_source_sha256"] ==
          plan["source"]["feature_builder_source_sha256"]
          and source["features_sha256"] == _sha(features_raw),
          "stored feature source differs from registered implementation/rows")
    recomputed_source, recomputed_features = derive(
        batch_paths, collector_sha256=plan["source"]["collector_source_sha256"],
        symbol=plan["symbol"])
    recomputed_feature_raw = b"".join(_canon(row) for row in recomputed_features)
    _must(recomputed_feature_raw == features_raw and all(
        source[key] == recomputed_source[key] for key in recomputed_source),
          "stored as-of feature rows/receipts differ from sealed raw batches")
    for prior, current in zip(source["batch_receipts"],
                              source["batch_receipts"][1:]):
        gap = (_utc(current["started_at"], "batch start")
               - _utc(prior["sealed_at"], "prior batch seal")).total_seconds()
        _must(0 <= gap <= 900,
              "REST feature input crosses an unobserved or new-lineage interval")
    _batch_receipts, depths, _trades = _source_batches(
        batch_paths, plan["source"]["collector_source_sha256"], plan["symbol"])
    depths.sort(key=lambda frame: (frame["received"], frame["batch_index"],
                                   frame["attempt_index"]))
    sealed_at = max(_utc(row["sealed_at"], "batch seal")
                    for row in source["batch_receipts"])
    policy = plan["policy"]
    reserve = timedelta(seconds=policy["hold_s"] + policy["exit_timeout_s"])
    complete = sealed_at >= end + reserve
    feature_by_decision: dict[datetime, dict] = {}
    for feature in recomputed_features:
        at = _utc(feature["decision_at"], "feature decision")
        _must(at not in feature_by_decision, "ambiguous feature at one decision")
        feature_by_decision[at] = feature
    scheduled = int((end - start).total_seconds() / 3600)
    cost = plan["cost"]
    legs = 2 * (cost["fee_leg_bps"] + cost["slippage_leg_bps"])
    ledger: list[dict] = []
    busy_until: dict[str, datetime | None] = {"candidate": None, "baseline": None}
    for index in range(scheduled):
        at = start + timedelta(hours=index)
        feature = feature_by_decision.get(at)
        state = "source_valid"
        if at > sealed_at:
            state = "future_unissued"
        elif feature is None:
            state = "missing_feature"
        elif (not feature["usable_for_paper_observation"]
              or feature["rest_depth_has_diff_sequence_proof"] is not False
              or _utc(feature["hour_end"], "closed source hour")
              != at - timedelta(minutes=5)
              or _utc(feature["available_at"], "feature available") > at
              or (at - _utc(feature["book_snapshot_available_at"],
                            "feature book receipt")).total_seconds()
              > policy["max_observation_age_s"]):
            state = "invalid_or_stale_feature"
        signal = {}
        entry = exit_quote = None
        gross = net = doubled = realized_mid = None
        if state == "source_valid":
            floor = legs + feature["spread_bps"]
            for arm in ("candidate", "baseline"):
                signal[arm] = _signal(feature, policy, arm, floor)
            entry = _first_reference_quote(
                depths, batch_paths, at + timedelta(seconds=policy["latency_s"]),
                at + timedelta(seconds=policy["entry_timeout_s"]),
                policy["max_quote_receive_delay_s"], side="entry",
                paper_size_quote=policy["paper_size_quote"])
            if entry is not None:
                entry_at = _utc(entry["response_received_at"], "entry receipt")
                exit_quote = _first_reference_quote(
                    depths, batch_paths, entry_at + timedelta(seconds=policy["hold_s"]),
                    entry_at + timedelta(seconds=policy["hold_s"]
                                                + policy["exit_timeout_s"]),
                    policy["max_quote_receive_delay_s"], side="exit",
                    paper_size_quote=policy["paper_size_quote"],
                    entry_ask=entry["ask"])
                if exit_quote is not None:
                    gross = 10_000 * (exit_quote["bid"] / entry["ask"] - 1)
                    net, doubled = gross - legs, gross - 2 * legs
                    entry_mid = (entry["bid"] + entry["ask"]) / 2
                    exit_mid = (exit_quote["bid"] + exit_quote["ask"]) / 2
                    realized_mid = 10_000 * (exit_mid / entry_mid - 1)
                    _must(all(math.isfinite(x) for x in (
                        gross, net, doubled, realized_mid)),
                          "reference quote score is nonfinite")
        arms = {}
        for arm in ("candidate", "baseline"):
            if state != "source_valid":
                status, reason = "not_run", state
            elif not signal[arm]["intent"]:
                status, reason = "no_intent", "frozen_signal_or_cost_gate"
            elif busy_until[arm] is not None and at < busy_until[arm]:
                status, reason = "not_run", "same_slot_exposure_cap"
            elif entry is None:
                status, reason = "unavailable", "no_postdecision_rest_ask"
            elif exit_quote is None:
                status, reason = "unavailable", "no_later_rest_bid"
                busy_until[arm] = end + reserve
            else:
                status, reason = "reference_quote_pair_observed", "rest_book_display_only"
                busy_until[arm] = _utc(exit_quote["response_received_at"], "exit receipt")
            arms[arm] = {
                "status": status, "reason": reason,
                "predicted_move_bps": signal[arm]["predicted_move_bps"]
                if state == "source_valid" else None,
                "intent": signal[arm]["intent"] if state == "source_valid" else None,
                "reference_net_bps": net if status == "reference_quote_pair_observed" else None,
                "reference_net_doubled_cost_bps": doubled
                if status == "reference_quote_pair_observed" else None,
                "forecast_squared_error_bps2": (
                    _forecast_square_error(signal[arm]["predicted_move_bps"], realized_mid)
                    if state == "source_valid" and realized_mid is not None else None),
                "forecast_direction_correct": (
                    (signal[arm]["predicted_move_bps"] > 0) == (realized_mid > 0)
                    if state == "source_valid" and realized_mid is not None else None),
            }
        ledger.append({
            "schema": CELL_SCHEMA, "cell_id": f"{plan['study_id']}.{index:04d}",
            "decision_at": at.isoformat(), "source_status": state,
            "feature": feature if state == "source_valid" else None,
            "entry_rest_quote": entry, "exit_rest_quote": exit_quote,
            "reference_gross_bps": gross,
            "reference_realized_mid_move_bps": realized_mid,
            "candidate": arms["candidate"], "matched_momentum_baseline": arms["baseline"],
            "no_trade_reference_net_bps": 0.0,
        })
    def metrics(name: str) -> dict:
        rows = [cell[name] for cell in ledger]
        observed = [row for row in rows
                    if row["status"] == "reference_quote_pair_observed"]
        forecast_observed = [row for row in rows
                             if row["forecast_squared_error_bps2"] is not None]
        unknown = sum(
            cell["source_status"] != "source_valid"
            or cell[name]["status"] == "unavailable" for cell in ledger)
        known_zero = sum(
            cell["source_status"] == "source_valid"
            and cell[name]["status"] in {"no_intent", "not_run"}
            for cell in ledger)
        return_is_identified = complete and unknown == 0
        return {
            "intents": sum(row["intent"] is True for row in rows),
            "observed_reference_quote_pairs": len(observed),
            "observed_return_denominator": len(observed),
            "forecast_midquote_observed_denominator": len(forecast_observed),
            "forecast_midquote_mse_bps2_observed": (
                sum(row["forecast_squared_error_bps2"]
                    for row in forecast_observed) / len(forecast_observed)
                if forecast_observed else None),
            "forecast_midquote_direction_fraction_observed": (
                sum(row["forecast_direction_correct"] is True
                    for row in forecast_observed) / len(forecast_observed)
                if forecast_observed else None),
            "known_zero_abstention_or_exposure_cells": known_zero,
            "unknown_outcome_cells": unknown,
            "all_scheduled_return_identified": return_is_identified,
            "unavailable": sum(row["status"] == "unavailable" for row in rows),
            "not_run": sum(row["status"] == "not_run" for row in rows),
            "net_bps_sum": sum(row["reference_net_bps"] for row in observed),
            "net_doubled_cost_bps_sum": sum(
                row["reference_net_doubled_cost_bps"] for row in observed),
            "net_bps_per_all_scheduled": (
                sum(row["reference_net_bps"] for row in observed) / scheduled
                if return_is_identified else None),
            "net_doubled_cost_bps_per_all_scheduled": (
                sum(row["reference_net_doubled_cost_bps"] for row in observed)
                / scheduled if return_is_identified else None),
        }
    candidate_metrics = metrics("candidate")
    baseline_metrics = metrics("matched_momentum_baseline")
    coverage_complete = (
        candidate_metrics["all_scheduled_return_identified"]
        and baseline_metrics["all_scheduled_return_identified"])
    result = {
        "schema": RESULT_SCHEMA, "study_id": plan["study_id"],
        "status": ("complete_reference_review" if coverage_complete else
                   "closed_with_missing_evidence" if complete else "incomplete"),
        "temporal_window_closed": complete,
        "coverage_complete": coverage_complete,
        "scope": "bounded_2_to_5_hour_pilot_block_not_month_result",
        "source_proof": "sealed_public_REST_GET_no_diff_depth_sequence",
        "rule_origin": RULE_ORIGIN,
        "arm_exposure_comparison": "same_one_position_hold_cap_not_identical_realized_intents",
        "plan_sha256": _sha(plan_raw),
        "plan_archive_relpath": "plan.raw.json",
        "topic_transfer_sha256": _sha(topic_raw),
        "topic_transfer_archive_relpath": "topic-transfer.raw.json",
        "science_ladder_changed": False,
        "application_lane": "independent_known_prior_empirical_diagnostic",
        "driver_source_sha256": _source_sha(Path(__file__)),
        "driver_source_archive_relpath": "driver-source.py",
        "feature_source_sha256": _sha(source_raw),
        "features_sha256": _sha(features_raw),
        "batch_capture_sha256s": [row["sha256"] for row in source["batch_receipts"]],
        "forward_start": plan["split"]["forward_start"],
        "forward_end": plan["split"]["forward_end"],
        "source_sealed_at": sealed_at.isoformat(),
        "scheduled_cells": scheduled,
        "source_valid_cells": sum(cell["source_status"] == "source_valid"
                                  for cell in ledger),
        "missing_feature_cells": sum(cell["source_status"] == "missing_feature"
                                     for cell in ledger),
        "invalid_or_stale_feature_cells": sum(
            cell["source_status"] == "invalid_or_stale_feature" for cell in ledger),
        "future_unissued_cells": sum(cell["source_status"] == "future_unissued"
                                     for cell in ledger),
        "candidate": candidate_metrics,
        "matched_momentum_baseline": baseline_metrics,
        "no_trade_reference_net_bps_per_all_scheduled": 0.0,
        "negative_controls": "not_tested",
        "day_cluster_uncertainty": "not_tested",
        "disposition": "diagnostic_only_not_trade_evidence",
        "external_plan_freeze_proof": "unverified",
        "nonexecutable_reference_only": True,
        "paper_supported": False,
        "sequence_valid": False,
        "orders_placed": 0,
        "credentials_used": False,
    }
    return result, ledger


def _write_new(path: Path, raw: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    try:
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(fd)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--topic-transfer", type=Path, required=True)
    parser.add_argument("--batch", type=Path, action="append", required=True)
    parser.add_argument("--feature-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    plan_raw = _read_relative(args.plan.parent, args.plan.name, 64_000)
    topic_raw = _read_relative(args.topic_transfer.parent,
                               args.topic_transfer.name, 64_000)
    driver_raw = _read_relative(Path(__file__).parent, Path(__file__).name,
                                1_000_000)
    plan = strict_json(plan_raw)
    result, ledger = evaluate(
        plan, batch_paths=[path.absolute() for path in args.batch],
        feature_dir=args.feature_dir.absolute(),
        collector_source=Path(public_spot_capture.__file__),
        feature_builder_source=Path(prospective_hourly_features.__file__),
        plan_raw=plan_raw, topic_raw=topic_raw)
    _must(result["driver_source_sha256"] == _sha(driver_raw),
          "driver implementation changed between evaluation and archiving")
    output = args.output_dir.absolute()
    _must(not output.exists() and output.parent.is_dir()
          and not output.parent.is_symlink(),
          "reference output must be a new direct child")
    output.mkdir(mode=0o700)
    _write_new(output / "plan.raw.json", plan_raw)
    _write_new(output / "topic-transfer.raw.json", topic_raw)
    _write_new(output / "driver-source.py", driver_raw)
    _write_new(output / "reference-cells.jsonl",
               b"".join(_canon(row) for row in ledger))
    result["private_cells_sha256"] = _sha(_read_relative(
        output, "reference-cells.jsonl", 64_000_000))
    _write_new(output / "result.json", _canon(result))
    print(json.dumps({"result_path": str(output / "result.json"),
                      "status": result["status"],
                      "scheduled_cells": result["scheduled_cells"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
