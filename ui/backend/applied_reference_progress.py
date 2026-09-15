"""Off-tree bounded view of archived trade-only and H1 reference receipts.

No source acquisition, model request, order, ZIP rehash, private prediction
serialization or live trading is performed by this projector. Install only
after the package owner's append-only publication contract is frozen and the
model measurement window restores.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
import stat
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .local_model_research import Reader, SourceError

ROOT = Path(
    "/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-15/"
    "applied-trading-public-data"
)
SCHEMA = "applied-reference-progress/v1"
PUBLICATION = "publications/fixed60-BTCUSDT-v1.json"
GATE = "publications/source-gate-BTCUSDT-fixed60-v1.json"
RESULT = "reference-results/BTCUSDT-fixed60-20260915-a/result.json"
PRIVATE = (
    "reference-results/BTCUSDT-fixed60-20260915-a/private/"
    "validation-predictions.jsonl"
)
BASELINE_CHILD = re.compile(r"BTCUSDT-fixed60-[A-Za-z0-9_-]{1,60}\Z")
H1_ID = re.compile(r"h1-btcusdt-rest-[0-9]{8}-[a-z0-9]{3,16}\Z")
H1_PLAN_NAME = re.compile(
    r"h1-rest-(h1-btcusdt-rest-[0-9]{8}-[a-z0-9]{3,16})\.plan\.json\Z"
)
H1_CAPTURE = re.compile(
    r"captures/spot-BTCUSDT-[0-9]{8}T[0-9]{6}Z\Z"
)
H1_PLAN_SCHEMA = "applied-h1-rest-reference-plan/v1"
H1_RESULT_SCHEMA = "applied-h1-rest-reference-result/v1"
SHA = re.compile(r"[0-9a-f]{64}\Z")
GATE_SCHEMA = "applied-trading-complete-60-day-source-gate/v1"
PUBLICATION_SCHEMA = "applied-trading-publication/v1"
RESULT_SCHEMA = "applied-trial-trade-only-reference-baseline/v1"
MAX_PRIVATE_BYTES = 8 * 1024 * 1024
FIRST_DAY = date(2026, 7, 17)
LAST_DAY = date(2026, 9, 14)


def _require(ok: bool, why: str) -> None:
    if not ok:
        raise SourceError(why)


def _sha(value: object) -> bool:
    return isinstance(value, str) and SHA.fullmatch(value) is not None


def _number(value: object, *, lower: float | None = None,
            upper: float | None = None) -> float:
    _require(type(value) in {float, int}, "historical score is not numeric")
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise SourceError("historical score is not finite") from exc
    _require(math.isfinite(number), "historical score is not finite")
    _require((lower is None or number >= lower)
             and (upper is None or number <= upper),
             "historical score is outside its domain")
    return number


def _ci(value: object, *, lower: float | None = None,
        upper: float | None = None) -> list[float]:
    _require(isinstance(value, list) and len(value) == 2,
             "historical confidence interval is malformed")
    left, right = (_number(item, lower=lower, upper=upper) for item in value)
    _require(left <= right, "historical confidence interval is reversed")
    return [left, right]


def _private_hash(root: Path, relative: str) -> tuple[str, int]:
    """Stream only the raw SHA of a bounded private validation source."""
    components = Path(relative).parts
    _require(
        len(components) == 4
        and (
            (components[0] == "reference-results"
             and BASELINE_CHILD.fullmatch(components[1]) is not None
             and components[2:] == (
                 "private", "validation-predictions.jsonl"))
            or
            (components[0] == "prospective-studies"
             and H1_ID.fullmatch(components[1]) is not None
             and components[2:] == (
                 "reference-result", "reference-cells.jsonl"))
        ),
        "private reference source path is unregistered",
    )
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
    descriptors = []
    try:
        descriptor = os.open(root, flags | os.O_DIRECTORY)
        descriptors.append(descriptor)
        for part in components[:-1]:
            descriptor = os.open(part, flags | os.O_DIRECTORY,
                                 dir_fd=descriptor)
            descriptors.append(descriptor)
        descriptor = os.open(components[-1], flags, dir_fd=descriptor)
        descriptors.append(descriptor)
        before = os.fstat(descriptor)
        _require(stat.S_ISREG(before.st_mode)
                 and 0 < before.st_size <= MAX_PRIVATE_BYTES,
                 "private validation source is absent or oversized")
        digest = hashlib.sha256()
        count = 0
        newline_count = 0
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            count += len(chunk)
            _require(count <= MAX_PRIVATE_BYTES,
                     "private validation source exceeded its read bound")
            digest.update(chunk)
            newline_count += chunk.count(b"\n")
        after = os.fstat(descriptor)
        _require(count == before.st_size == after.st_size
                 and before.st_mtime_ns == after.st_mtime_ns,
                 "private validation source changed while read")
        return digest.hexdigest(), newline_count
    except OSError as exc:
        raise SourceError("private validation source is unreadable") from exc
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _daily_sources(rows: object) -> None:
    _require(isinstance(rows, list) and len(rows) == 60,
             "fixed source-day coverage differs")
    for ordinal, row in enumerate(rows):
        expected = (FIRST_DAY + timedelta(days=ordinal)).isoformat()
        _require(isinstance(row, dict) and row.get("day") == expected
                 and row.get("hourly_rows") == 24
                 and row.get("missing_hours") == 0
                 and all(_sha(row.get(key)) for key in (
                     "fetch_receipt_sha256", "source_receipt_sha256",
                     "hourly_flow_sha256", "zip_sha256",
                     "checksum_raw_sha256",
                 )), "one historical source day is absent or malformed")


def _horizon(row: object, expected: int) -> dict:
    _require(isinstance(row, dict) and row.get("horizon_hours") == expected
             and row.get("development_train_rows") == 960 - 5 - expected
             and row.get("validation_eligible_rows") == 480 - 3 - expected
             and row.get("validation_scored_rows") == 480 - 3 - expected
             and row.get("validation_coverage") == 1.0
             and row.get("embargo_hours") == 4
             and row.get("end_horizon_excluded_hours") == expected
             and row.get("reference_only_no_trading_edge_claim") is True,
             "fixed historical score denominator differs")
    baseline_mse = _number(row.get("baseline_mse_bps2"), lower=0)
    flow_mse = _number(row.get("flow_model_mse_bps2"), lower=0)
    mse_delta = _number(row.get("mse_improvement_bps2"))
    baseline_direction = _number(row.get("baseline_directional_accuracy"),
                                 lower=0, upper=1)
    flow_direction = _number(row.get("flow_model_directional_accuracy"),
                             lower=0, upper=1)
    direction_delta = _number(row.get("directional_improvement"),
                              lower=-1, upper=1)
    _require(abs((baseline_mse - flow_mse) - mse_delta)
             <= 1e-6 * max(1.0, abs(mse_delta))
             and abs((flow_direction - baseline_direction) - direction_delta)
             <= 1e-9,
             "fixed historical paired score arithmetic differs")
    reference_cost = row.get("reference_cost")
    net = row.get("reference_net_bps_per_eligible_hour")
    _require(isinstance(reference_cost, dict)
             and reference_cost.get("fee_leg_bps") == 10.0
             and reference_cost.get("slippage_leg_bps_assumed") == 5.0
             and reference_cost.get("roundtrip_bps_assumed") == 30.0
             and reference_cost.get("doubled_roundtrip_bps_assumed") == 60.0
             and reference_cost.get("historical_executable_L2_or_fill_proven")
                is False
             and isinstance(net, dict) and set(net) == {
                 "no_trade", "baseline", "flow_model",
                 "baseline_doubled", "flow_model_doubled",
             } and net.get("no_trade") == 0.0,
             "historical reference-cost scenario differs")
    return {
        "horizon_hours": expected,
        "validation_scored_rows": row["validation_scored_rows"],
        "baseline_mse_bps2": baseline_mse,
        "flow_model_mse_bps2": flow_mse,
        "mse_improvement_bps2": mse_delta,
        "mse_improvement_95ci": _ci(
            row.get("day_cluster_mse_improvement_95ci"),
        ),
        "baseline_directional_accuracy": baseline_direction,
        "flow_model_directional_accuracy": flow_direction,
        "directional_improvement": direction_delta,
        "directional_improvement_95ci": _ci(
            row.get("day_cluster_directional_improvement_95ci"),
            lower=-1, upper=1,
        ),
        "baseline_reference_net_bps_per_eligible_hour":
            _number(net["baseline"]),
        "flow_reference_net_bps_per_eligible_hour":
            _number(net["flow_model"]),
        "baseline_doubled_reference_net_bps_per_eligible_hour":
            _number(net["baseline_doubled"]),
        "flow_doubled_reference_net_bps_per_eligible_hour":
            _number(net["flow_model_doubled"]),
    }


def _fixed(reader: Reader, root: Path) -> dict:
    pub, publication_sha = reader.read(PUBLICATION)
    result_path = pub.get("result_relpath")
    private_path = pub.get("private_predictions_relpath")
    _require(isinstance(result_path, str)
             and isinstance(private_path, str)
             and len(result_path) <= 130
             and len(private_path) <= 170,
             "fixed historical result paths are absent")
    result_parts = Path(result_path).parts
    _require(len(result_parts) == 3
             and result_parts[0] == "reference-results"
             and BASELINE_CHILD.fullmatch(result_parts[1]) is not None
             and result_parts[2] == "result.json"
             and private_path == (
                 f"reference-results/{result_parts[1]}/private/"
                 "validation-predictions.jsonl"),
             "fixed historical result is outside the registered child")
    _require(pub.get("schema") == PUBLICATION_SCHEMA
             and pub.get("kind") == "fixed60_baseline"
             and pub.get("status") == "admitted"
             and pub.get("symbol") == "BTCUSDT"
             and pub.get("gate_relpath") == GATE
             and pub.get("result_relpath") == result_path
             and pub.get("private_predictions_relpath") == private_path
             and pub.get("reference_only") is True
             and all(_sha(pub.get(key)) for key in (
                 "gate_raw_sha256", "result_raw_sha256",
                 "private_predictions_raw_sha256",
                 "baseline_runner_source_sha256",
                 "archive_adapter_source_sha256",
             )), "fixed historical publication is unregistered")
    gate, gate_sha = reader.read(GATE, digest=pub["gate_raw_sha256"])
    result, result_sha = reader.read(result_path,
                                    digest=pub["result_raw_sha256"])
    private_sha, private_rows = _private_hash(root, private_path)
    _require(private_sha == pub["private_predictions_raw_sha256"],
             "private validation prediction bytes differ")
    _require(private_rows == 949,
             "private validation prediction row denominator differs")
    _require(gate.get("schema") == GATE_SCHEMA
             and gate.get("status") == "admitted"
             and gate.get("symbol") == "BTCUSDT"
             and gate.get("calendar_start") == FIRST_DAY.isoformat()
             and gate.get("calendar_end") == LAST_DAY.isoformat()
             and gate.get("daily_sources_count") == 60
             and gate.get("hourly_source_rows") == 1440
             and gate.get("source_replay")
                == "full_60_day_rehash_at_publication"
             and gate.get("grade_replay")
                == "deterministic_two_horizon_scores_and_private_predictions"
             and gate.get("reference_only") is True
             and gate.get("historical_executable_quotes_proven") is False
             and gate.get("paper_forward_result") == "not_tested"
             and gate.get("result_relpath") == result_path
             and gate.get("result_raw_sha256") == result_sha
             and gate.get("private_predictions_relpath") == private_path
             and gate.get("private_predictions_raw_sha256") == private_sha
             and gate.get("baseline_runner_source_sha256")
                == pub["baseline_runner_source_sha256"]
             and gate.get("archive_adapter_source_sha256")
                == pub["archive_adapter_source_sha256"]
             and _sha(gate.get("gate_builder_source_sha256")),
             "complete 60-day source gate differs from publication")
    _daily_sources(gate.get("daily_source_receipts"))
    _require(result.get("schema") == RESULT_SCHEMA
             and result.get("status") == "complete_trade_only_reference"
             and result.get("symbol") == "BTCUSDT"
             and result.get("calendar_start") == FIRST_DAY.isoformat()
             and result.get("calendar_end") == LAST_DAY.isoformat()
             and result.get("development_days") == 40
             and result.get("validation_days") == 20
             and result.get("daily_sources_count") == 60
             and result.get("hourly_source_rows") == 1440
             and result.get("daily_source_receipts")
                == gate["daily_source_receipts"]
             and result.get("horizons_hours") == [1, 4]
             and result.get("validation_predictions_private_sha256")
                == private_sha
             and result.get("model_source_sha256")
                == gate["baseline_runner_source_sha256"]
             and result.get("source_scope") == "historical_trade_only"
             and result.get("use")
                == "chronological_development_validation_reference_only"
             and result.get("historical_executable_quote_or_L2_proven")
                is False
             and result.get("paper_forward_result") == "not_tested"
             and result.get("orders_placed") == 0
             and result.get("hyperparameter_search") is False,
             "historical result differs from accepted source gate")
    scores = result.get("scores")
    _require(isinstance(scores, list) and len(scores) == 2,
             "historical result has an incomplete horizon set")
    return {
        "status": "recorded_reference_only", "symbol": "BTCUSDT",
        "calendar_start": FIRST_DAY.isoformat(),
        "calendar_end": LAST_DAY.isoformat(),
        "source_days": 60, "source_hours": 1440,
        "source_rehash_at_publication": True,
        "score_replay_at_publication": True,
        "current_source_replay": "not_performed",
        "reference_roundtrip_cost_bps": 30.0,
        "reference_doubled_roundtrip_cost_bps": 60.0,
        "horizons": [_horizon(scores[0], 1), _horizon(scores[1], 4)],
        "publication_sha256": publication_sha,
        "gate_sha256": gate_sha,
        "result_sha256": result_sha,
        "private_predictions_sha256": private_sha,
        "runner_source_sha256": gate["baseline_runner_source_sha256"],
        "archive_adapter_source_sha256":
            gate["archive_adapter_source_sha256"],
        "historical_executable_quotes_proven": False,
        "paper_forward_result": "not_tested", "orders_placed": 0,
    }


def _utc(value: object) -> datetime:
    _require(isinstance(value, str) and len(value) <= 48,
             "forward study time is malformed")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SourceError("forward study time is malformed") from exc
    _require(parsed.tzinfo is not None
             and parsed.utcoffset() == timedelta(0),
             "forward study time is not UTC")
    return parsed.astimezone(timezone.utc)


def _forward_one(reader: Reader, root: Path, study_id: str) -> dict:
    _require(H1_ID.fullmatch(study_id) is not None,
             "forward study ID is unregistered")
    prefix = f"prospective-studies/{study_id}"
    plan_publication = f"publications/h1-rest-{study_id}.plan.json"
    result_publication = f"publications/h1-rest-{study_id}.result.json"
    plan_path = f"{prefix}/plan.raw.json"
    topic_path = f"{prefix}/topic-transfer.raw.json"
    plan_pub, plan_pub_sha = reader.read(plan_publication)
    _require(plan_pub.get("schema") == PUBLICATION_SCHEMA
             and plan_pub.get("kind") == "h1_rest_pilot_plan"
             and plan_pub.get("status") == "published_local_prestart"
             and plan_pub.get("study_id") == study_id
             and plan_pub.get("plan_relpath") == plan_path
             and plan_pub.get("topic_transfer_relpath") == topic_path
             and plan_pub.get("freeze_proof") == "local_exclusive_write_only"
             and plan_pub.get("external_plan_freeze_proof") == "unverified"
             and plan_pub.get("nonexecutable_reference_only") is True
             and plan_pub.get("paper_supported") is False
             and plan_pub.get("science_ladder_changed") is False
             and plan_pub.get("orders_placed") == 0
             and all(_sha(plan_pub.get(key)) for key in (
                 "plan_raw_sha256", "topic_transfer_raw_sha256",
                 "collector_source_sha256", "feature_builder_source_sha256",
                 "driver_source_sha256", "lifecycle_source_sha256",
                 "capture_tick_source_sha256",
             )), "forward plan publication fails recorded admission")
    plan, plan_sha = reader.read(plan_path,
                                 digest=plan_pub["plan_raw_sha256"])
    _topic, topic_sha = reader.read(
        topic_path, digest=plan_pub["topic_transfer_raw_sha256"])
    _require(plan.get("schema") == H1_PLAN_SCHEMA
             and plan.get("study_id") == study_id
             and plan.get("symbol") == "BTCUSDT"
             and plan.get("rule_origin")
                == "fixed_unfitted_engineering_preset/v1"
             and plan.get("topic_transfer_sha256") == topic_sha
             and isinstance(plan.get("split"), dict)
             and isinstance(plan.get("source"), dict)
             and plan["source"].get("source_id") == "binance-spot-public"
             and plan["source"].get("collector_source_sha256")
                == plan_pub["collector_source_sha256"]
             and plan["source"].get("feature_builder_source_sha256")
                == plan_pub["feature_builder_source_sha256"]
             and isinstance(plan.get("policy"), dict)
             and plan["policy"].get("hold_s") == 3600
             and plan["policy"].get("latency_s") == 30
             and plan["policy"].get("entry_timeout_s") == 600
             and plan["policy"].get("exit_timeout_s") == 600
             and plan["policy"].get("max_quote_receive_delay_s") == 30
             and plan["policy"].get("max_observation_age_s") == 300
             and plan["policy"].get("paper_size_quote") == 100
             and plan["policy"].get("candidate") == {
                 "intercept_bps": 0, "momentum_weight_bps": 1,
                 "flow_weight_bps": 60, "depletion_weight_bps": 80,
                 "min_flow": 0.1, "min_depletion": 0.1}
             and plan["policy"].get("baseline") == {
                 "intercept_bps": 0, "momentum_weight_bps": 1}
             and isinstance(plan.get("cost"), dict)
             and plan["cost"].get("fee_leg_bps") == 10
             and plan["cost"].get("slippage_leg_bps") == 5
             and plan["cost"].get("double_multiplier") == 2,
             "forward plan/topic differ from publication")
    start = _utc(plan["split"].get("forward_start"))
    end = _utc(plan["split"].get("forward_end"))
    frozen = _utc(plan["split"].get("frozen_at"))
    published = _utc(plan_pub.get("published_at"))
    _require(frozen <= published < start < end
             and end - start in {timedelta(hours=hours)
                                 for hours in (2, 3, 4, 5)}
             and plan_pub.get("forward_start") == plan["split"]["forward_start"]
             and plan_pub.get("forward_end") == plan["split"]["forward_end"],
             "forward local publication was late or has a changed window")
    base = {
        "status": "rest_plan_published_local",
        "primary_horizon_hours": 1, "secondary_horizon_hours": 4,
        "rest_reference_plan_published": True,
        "rest_reference_result_published": False,
        "strict_paper_study_registered": False,
        "paper_supported": False, "orders_placed": 0,
        "study_id": study_id, "scheduled_cells": int(
            (end - start).total_seconds() // 3600),
        "source_valid_cells": None, "unknown_outcome_cells": None,
        "all_scheduled_reference_net_bps": None,
        "plan_publication_sha256": plan_pub_sha,
        "plan_sha256": plan_sha, "topic_sha256": topic_sha,
        "current_source_replay": "not_performed",
        "external_plan_freeze_proof": "unverified",
        "nonexecutable_reference_only": True,
    }
    if not (root / result_publication).exists() and not (
            root / result_publication).is_symlink():
        return base
    result_pub, result_pub_sha = reader.read(result_publication)
    _require(result_pub.get("schema") == PUBLICATION_SCHEMA
             and result_pub.get("kind") == "h1_rest_pilot_result"
             and result_pub.get("study_id") == study_id
             and result_pub.get("status") in {
                 "admitted_reference_result", "closed_missing_source"}
             and result_pub.get("plan_publication_relpath")
                == plan_publication
             and result_pub.get("plan_publication_raw_sha256")
                == plan_pub_sha
             and _utc(result_pub.get("published_at")) >= end
             and result_pub.get("scheduled_cells") == base["scheduled_cells"]
             and result_pub.get("nonexecutable_reference_only") is True
             and result_pub.get("paper_supported") is False
             and result_pub.get("sequence_valid") is False
             and result_pub.get("external_plan_freeze_proof") == "unverified"
             and result_pub.get("science_ladder_changed") is False
             and result_pub.get("orders_placed") == 0,
             "forward result publication is not bound to its prestart plan")
    base["rest_reference_result_published"] = True
    base["result_publication_sha256"] = result_pub_sha
    if result_pub["status"] == "closed_missing_source":
        _require(result_pub.get("result_relpath") is None
                 and result_pub.get("result_raw_sha256") is None
                 and result_pub.get("private_cells_relpath") is None
                 and result_pub.get("private_cells_raw_sha256") is None
                 and result_pub.get("unknown_scheduled_cells")
                    == base["scheduled_cells"]
                 and result_pub.get("candidate_net_bps_per_all_scheduled")
                    is None
                 and result_pub.get("baseline_net_bps_per_all_scheduled")
                    is None,
                 "missing-source closure fabricates a score")
        base["status"] = "closed_missing_source"
        base["unknown_outcome_cells"] = base["scheduled_cells"]
        return base
    result_path = f"{prefix}/reference-result/result.json"
    private_path = f"{prefix}/reference-result/reference-cells.jsonl"
    _require(result_pub.get("result_relpath") == result_path
             and result_pub.get("private_cells_relpath") == private_path
             and result_pub.get("grade_replay")
                == "deterministic_rest_reference_result_and_private_cells"
             and _sha(result_pub.get("result_raw_sha256"))
             and _sha(result_pub.get("private_cells_raw_sha256"))
             and result_pub.get("driver_source_sha256")
                == plan_pub["driver_source_sha256"],
             "forward result/private paths are not registered")
    result, result_sha = reader.read(
        result_path, digest=result_pub["result_raw_sha256"])
    private_sha, private_rows = _private_hash(root, private_path)
    _require(private_sha == result_pub["private_cells_raw_sha256"]
             and result.get("schema") == H1_RESULT_SCHEMA
             and result.get("study_id") == study_id
             and result.get("status") in {
                 "complete_reference_review", "closed_with_missing_evidence"}
             and result.get("temporal_window_closed") is True
             and result.get("plan_sha256") == plan_sha
             and result.get("private_cells_sha256") == private_sha
             and result.get("driver_source_sha256")
                == plan_pub["driver_source_sha256"]
             and result.get("scheduled_cells") == base["scheduled_cells"]
             and result.get("nonexecutable_reference_only") is True
             and result.get("paper_supported") is False
             and result.get("sequence_valid") is False
             and result.get("external_plan_freeze_proof") == "unverified"
             and result.get("science_ladder_changed") is False
             and result.get("orders_placed") == 0,
             "forward due result differs from recorded plan/private source")
    _require(private_rows == base["scheduled_cells"],
             "forward private cell row denominator differs")
    batches = result_pub.get("selected_batch_relpaths")
    hashes = result.get("batch_capture_sha256s")
    _require(isinstance(batches, list) and isinstance(hashes, list)
             and len(batches) == len(hashes)
             and len(batches) == result_pub.get("selected_batches_count")
             and 1 <= len(batches) <= 96,
             "forward selected source batches are incomplete")
    for batch_path, batch_sha in zip(batches, hashes):
        _require(isinstance(batch_path, str)
                 and H1_CAPTURE.fullmatch(batch_path) is not None
                 and _sha(batch_sha),
                 "forward source batch path is unregistered")
        reader.read(f"{batch_path}/capture-batch.json", digest=batch_sha)
    scheduled = base["scheduled_cells"]
    source_valid = result.get("source_valid_cells")
    _require(type(source_valid) is int and 0 <= source_valid <= scheduled
             and result_pub.get("source_valid_cells") == source_valid,
             "forward source-valid denominator differs")
    base["source_valid_cells"] = source_valid
    base["result_sha256"] = result_sha
    base["private_cells_sha256"] = private_sha
    base["score_replay_at_publication"] = True
    base["status"] = (
        "rest_reference_recorded"
        if result["status"] == "complete_reference_review"
        else "closed_missing_source"
    )
    candidate = result.get("candidate")
    baseline = result.get("matched_momentum_baseline")
    _require(isinstance(candidate, dict) and isinstance(baseline, dict),
             "forward matched reference arms are absent")
    unknown = max(candidate.get("unknown_outcome_cells", 0),
                  baseline.get("unknown_outcome_cells", 0))
    _require(type(unknown) is int and 0 <= unknown <= scheduled
             and result_pub.get("candidate_unknown_outcome_cells")
                == candidate.get("unknown_outcome_cells")
             and result_pub.get("baseline_unknown_outcome_cells")
                == baseline.get("unknown_outcome_cells"),
             "forward unknown outcomes differ")
    base["unknown_outcome_cells"] = unknown
    if base["status"] == "rest_reference_recorded":
        _require(source_valid > 0
                 and unknown == 0 and result.get("coverage_complete") is True
                 and candidate.get("all_scheduled_return_identified") is True
                 and baseline.get("all_scheduled_return_identified") is True,
                 "forward all-scheduled return is incomplete")
        candidate_net = _number(
            result_pub.get("candidate_net_bps_per_all_scheduled"))
        baseline_net = _number(
            result_pub.get("baseline_net_bps_per_all_scheduled"))
        _require(candidate_net ==
                    _number(candidate.get("net_bps_per_all_scheduled"))
                 and baseline_net ==
                    _number(baseline.get("net_bps_per_all_scheduled")),
                 "forward matched return differs from due result")
        base["all_scheduled_reference_net_bps"] = {
            "candidate": candidate_net, "baseline": baseline_net}
    else:
        _require(result_pub.get("candidate_net_bps_per_all_scheduled") is None
                 and result_pub.get("baseline_net_bps_per_all_scheduled") is None,
                 "forward missing-evidence result manufactures a return")
    return base


def _forward(reader: Reader, root: Path) -> dict | None:
    publication_dir = root / "publications"
    if not publication_dir.is_dir() or publication_dir.is_symlink():
        return None
    names = []
    with os.scandir(publication_dir) as rows:
        for ordinal, row in enumerate(rows):
            _require(ordinal < 128, "forward publication inventory is unbounded")
            _require(row.is_file(follow_symlinks=False),
                     "forward publication child is redirected or irregular")
            match = H1_PLAN_NAME.fullmatch(row.name)
            if match:
                names.append(match.group(1))
    if not names:
        return None
    return _forward_one(reader, root, max(names))


def project_applied_reference(root: Path = ROOT) -> dict:
    """Project archived references from independent append-only receipts."""
    status = {"schema_version": SCHEMA, "historical_trade_only": {
        "status": "not_recorded", "horizons": [],
        "historical_executable_quotes_proven": False,
        "paper_forward_result": "not_tested", "orders_placed": 0,
    }, "forward_h1": {
        "status": "topic_design_only", "primary_horizon_hours": 1,
        "secondary_horizon_hours": 4,
        "rest_reference_plan_published": False,
        "rest_reference_result_published": False,
        "strict_paper_study_registered": False,
        "paper_supported": False, "orders_placed": 0,
    }, "warnings": []}
    root = Path(root).absolute()
    publication = root / PUBLICATION
    if not root.exists() and not root.is_symlink():
        return status
    if not root.is_dir() or root.is_symlink():
        status["historical_trade_only"]["status"] = "source_unavailable"
        status["forward_h1"]["status"] = "source_unavailable"
        status["warnings"].append(
            "The applied reference receipt directory is unavailable."
        )
        return status
    try:
        reader = Reader(root)
        if publication.exists() or publication.is_symlink():
            try:
                status["historical_trade_only"] = _fixed(reader, root)
            except (SourceError, OSError, TypeError, KeyError, ValueError,
                    OverflowError, RecursionError):
                status["historical_trade_only"] = {
                    "status": "source_unavailable", "horizons": [],
                    "historical_executable_quotes_proven": False,
                    "paper_forward_result": "not_tested", "orders_placed": 0,
                }
                status["warnings"].append(
                    "The fixed historical reference publication failed source validation; scores are withheld."
                )
        try:
            forward = _forward(reader, root)
            if forward is not None:
                status["forward_h1"] = forward
        except (SourceError, OSError, TypeError, KeyError, ValueError,
                OverflowError, RecursionError):
            status["forward_h1"] = {
                "status": "source_unavailable",
                "primary_horizon_hours": 1,
                "secondary_horizon_hours": 4,
                "rest_reference_plan_published": False,
                "rest_reference_result_published": False,
                "strict_paper_study_registered": False,
                "paper_supported": False, "orders_placed": 0,
            }
            status["warnings"].append(
                "The forward REST publication failed recorded source validation; return numbers are withheld."
            )
    except (SourceError, OSError, TypeError, KeyError, ValueError,
            OverflowError, RecursionError):
        status["historical_trade_only"]["status"] = "source_unavailable"
        status["forward_h1"]["status"] = "source_unavailable"
        status["warnings"].append(
            "The applied reference receipt directory is unavailable."
        )
    return status
