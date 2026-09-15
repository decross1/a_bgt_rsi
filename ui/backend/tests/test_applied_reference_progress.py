"""Off-tree publisher-shaped baseline proof and private-drift checks.

Run only after the model measurement window restores and the publication
producer's exact schema has passed its own tests.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

from backend.applied_reference_progress import (
    GATE,
    PUBLICATION,
    project_applied_reference,
)


def _new_json(path: Path, value: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _source_days() -> list[dict]:
    first = date(2026, 7, 17)
    return [{"day": (first + timedelta(days=ordinal)).isoformat(),
             "hourly_rows": 24, "missing_hours": 0,
             "fetch_receipt_sha256": "a" * 64,
             "source_receipt_sha256": "b" * 64,
             "hourly_flow_sha256": "c" * 64,
             "zip_sha256": "d" * 64,
             "checksum_raw_sha256": "e" * 64}
            for ordinal in range(60)]


def _score(horizon: int) -> dict:
    return {"horizon_hours": horizon,
            "development_train_rows": 960 - 5 - horizon,
            "validation_eligible_rows": 480 - 3 - horizon,
            "validation_scored_rows": 480 - 3 - horizon,
            "validation_coverage": 1.0,
            "embargo_hours": 4,
            "end_horizon_excluded_hours": horizon,
            "baseline_mse_bps2": 100.0,
            "flow_model_mse_bps2": 90.0,
            "mse_improvement_bps2": 10.0,
            "day_cluster_mse_improvement_95ci": [1.0, 20.0],
            "baseline_directional_accuracy": 0.5,
            "flow_model_directional_accuracy": 0.6,
            "directional_improvement": 0.1,
            "day_cluster_directional_improvement_95ci": [-0.1, 0.2],
            "reference_cost": {
                "fee_leg_bps": 10.0,
                "slippage_leg_bps_assumed": 5.0,
                "roundtrip_bps_assumed": 30.0,
                "doubled_roundtrip_bps_assumed": 60.0,
                "historical_executable_L2_or_fill_proven": False,
            },
            "reference_net_bps_per_eligible_hour": {
                "no_trade": 0.0, "baseline": -1.0,
                "flow_model": 1.0, "baseline_doubled": -2.0,
                "flow_model_doubled": -1.0,
            },
            "reference_only_no_trading_edge_claim": True}


def _archive(tmp_path: Path, child_name: str =
             "BTCUSDT-fixed60-20260915-a") -> tuple[Path, Path]:
    root = tmp_path / "applied-trading-public-data"
    result_path = f"reference-results/{child_name}/result.json"
    private_path = (
        f"reference-results/{child_name}/private/"
        "validation-predictions.jsonl"
    )
    private = root / private_path
    private.parent.mkdir(parents=True)
    private.write_bytes(b"private validation prediction\n" * 949)
    private_sha = hashlib.sha256(private.read_bytes()).hexdigest()
    runner_sha = "f" * 64
    adapter_sha = "1" * 64
    days = _source_days()
    result_sha = _new_json(root / result_path, {
        "schema": "applied-trial-trade-only-reference-baseline/v1",
        "status": "complete_trade_only_reference",
        "symbol": "BTCUSDT", "calendar_start": "2026-07-17",
        "calendar_end": "2026-09-14", "development_days": 40,
        "validation_days": 20, "daily_sources_count": 60,
        "hourly_source_rows": 1440, "daily_source_receipts": days,
        "horizons_hours": [1, 4], "scores": [_score(1), _score(4)],
        "validation_predictions_private_sha256": private_sha,
        "model_source_sha256": runner_sha,
        "source_scope": "historical_trade_only",
        "use": "chronological_development_validation_reference_only",
        "historical_executable_quote_or_L2_proven": False,
        "paper_forward_result": "not_tested", "orders_placed": 0,
        "hyperparameter_search": False,
        "private_model_completion": "never exported",
    })
    gate_sha = _new_json(root / GATE, {
        "schema": "applied-trading-complete-60-day-source-gate/v1",
        "status": "admitted", "symbol": "BTCUSDT",
        "calendar_start": "2026-07-17", "calendar_end": "2026-09-14",
        "daily_sources_count": 60, "hourly_source_rows": 1440,
        "daily_source_receipts": days,
        "source_replay": "full_60_day_rehash_at_publication",
        "grade_replay":
            "deterministic_two_horizon_scores_and_private_predictions",
        "reference_only": True,
        "historical_executable_quotes_proven": False,
        "paper_forward_result": "not_tested",
        "result_relpath": result_path, "result_raw_sha256": result_sha,
        "private_predictions_relpath": private_path,
        "private_predictions_raw_sha256": private_sha,
        "baseline_runner_source_sha256": runner_sha,
        "archive_adapter_source_sha256": adapter_sha,
        "gate_builder_source_sha256": "2" * 64,
    })
    _new_json(root / PUBLICATION, {
        "schema": "applied-trading-publication/v1",
        "kind": "fixed60_baseline", "status": "admitted",
        "symbol": "BTCUSDT", "reference_only": True,
        "gate_relpath": GATE, "gate_raw_sha256": gate_sha,
        "result_relpath": result_path, "result_raw_sha256": result_sha,
        "private_predictions_relpath": private_path,
        "private_predictions_raw_sha256": private_sha,
        "baseline_runner_source_sha256": runner_sha,
        "archive_adapter_source_sha256": adapter_sha,
    })
    return root, private


def test_archived_reference_projects_only_numeric_historical_horizons(tmp_path):
    root, _ = _archive(tmp_path)
    data = project_applied_reference(root)
    historical = data["historical_trade_only"]
    assert historical["status"] == "recorded_reference_only"
    assert [row["validation_scored_rows"] for row in historical["horizons"]] == [476, 473]
    assert historical["current_source_replay"] == "not_performed"
    assert historical["paper_forward_result"] == "not_tested"
    assert "private_model_completion" not in str(data)


def test_private_validation_drift_withholds_historical_numbers(tmp_path):
    root, private = _archive(tmp_path)
    private.write_bytes(b"changed private bytes\n")
    data = project_applied_reference(root)
    assert data["historical_trade_only"]["status"] == "source_unavailable"
    assert data["historical_trade_only"]["horizons"] == []


def test_registered_later_baseline_child_retains_archived_numbers(tmp_path):
    root, _ = _archive(tmp_path, "BTCUSDT-fixed60-20260916-b")
    data = project_applied_reference(root)
    assert data["historical_trade_only"]["status"] == "recorded_reference_only"
    assert len(data["historical_trade_only"]["horizons"]) == 2


def test_redirected_reference_root_withholds_historical_and_forward_scores(tmp_path):
    root, _ = _archive(tmp_path)
    redirect = tmp_path / "redirect"
    redirect.symlink_to(root, target_is_directory=True)
    data = project_applied_reference(redirect)
    assert data["historical_trade_only"]["status"] == "source_unavailable"
    assert data["historical_trade_only"]["horizons"] == []
    assert data["forward_h1"]["status"] == "source_unavailable"


def test_missing_publication_keeps_history_and_forward_paper_pending(tmp_path):
    data = project_applied_reference(tmp_path)
    assert data["historical_trade_only"]["status"] == "not_recorded"
    assert data["forward_h1"]["strict_paper_study_registered"] is False


def _h1_plan(root: Path) -> tuple[str, str, dict]:
    study_id = "h1-btcusdt-rest-20260915-abc"
    child = f"prospective-studies/{study_id}"
    topic_sha = _new_json(root / child / "topic-transfer.raw.json", {
        "schema": "design-only-topic-transfer/v1",
    })
    plan = {
        "schema": "applied-h1-rest-reference-plan/v1",
        "study_id": study_id, "symbol": "BTCUSDT",
        "rule_origin": "fixed_unfitted_engineering_preset/v1",
        "topic_transfer_sha256": topic_sha,
        "source": {
            "source_id": "binance-spot-public",
            "collector_source_sha256": "a" * 64,
            "feature_builder_source_sha256": "b" * 64,
        },
        "policy": {
            "hold_s": 3600, "latency_s": 30,
            "entry_timeout_s": 600, "exit_timeout_s": 600,
            "max_quote_receive_delay_s": 30,
            "max_observation_age_s": 300,
            "paper_size_quote": 100,
            "candidate": {
                "intercept_bps": 0, "momentum_weight_bps": 1,
                "flow_weight_bps": 60, "depletion_weight_bps": 80,
                "min_flow": 0.1, "min_depletion": 0.1,
            },
            "baseline": {
                "intercept_bps": 0, "momentum_weight_bps": 1,
            },
        },
        "cost": {
            "fee_leg_bps": 10, "slippage_leg_bps": 5,
            "double_multiplier": 2,
        },
        "split": {
            "frozen_at": "2026-09-15T11:20:00Z",
            "forward_start": "2026-09-15T12:00:00Z",
            "forward_end": "2026-09-15T15:00:00Z",
        },
    }
    plan_sha = _new_json(root / child / "plan.raw.json", plan)
    publication = f"publications/h1-rest-{study_id}.plan.json"
    pub_sha = _new_json(root / publication, {
        "schema": "applied-trading-publication/v1",
        "kind": "h1_rest_pilot_plan",
        "status": "published_local_prestart",
        "study_id": study_id,
        "published_at": "2026-09-15T11:30:00Z",
        "forward_start": "2026-09-15T12:00:00Z",
        "forward_end": "2026-09-15T15:00:00Z",
        "plan_relpath": f"{child}/plan.raw.json",
        "plan_raw_sha256": plan_sha,
        "topic_transfer_relpath": f"{child}/topic-transfer.raw.json",
        "topic_transfer_raw_sha256": topic_sha,
        "collector_source_sha256": "a" * 64,
        "feature_builder_source_sha256": "b" * 64,
        "driver_source_sha256": "c" * 64,
        "lifecycle_source_sha256": "d" * 64,
        "capture_tick_source_sha256": "e" * 64,
        "freeze_proof": "local_exclusive_write_only",
        "external_plan_freeze_proof": "unverified",
        "nonexecutable_reference_only": True,
        "paper_supported": False,
        "science_ladder_changed": False,
        "orders_placed": 0,
    })
    return study_id, pub_sha, plan


def test_h1_local_prestart_plan_is_status_only(tmp_path):
    root = tmp_path / "applied-trading-public-data"
    _h1_plan(root)
    data = project_applied_reference(root)
    forward = data["forward_h1"]
    assert forward["status"] == "rest_plan_published_local"
    assert forward["scheduled_cells"] == 3
    assert forward["all_scheduled_reference_net_bps"] is None
    assert forward["external_plan_freeze_proof"] == "unverified"
    assert forward["paper_supported"] is False


def test_h1_closed_missing_source_keeps_all_scheduled_returns_null(tmp_path):
    root = tmp_path / "applied-trading-public-data"
    study_id, plan_publication_sha, _ = _h1_plan(root)
    _new_json(root / f"publications/h1-rest-{study_id}.result.json", {
        "schema": "applied-trading-publication/v1",
        "kind": "h1_rest_pilot_result",
        "status": "closed_missing_source",
        "study_id": study_id,
        "published_at": "2026-09-15T15:45:00Z",
        "plan_publication_relpath":
            f"publications/h1-rest-{study_id}.plan.json",
        "plan_publication_raw_sha256": plan_publication_sha,
        "scheduled_cells": 3, "unknown_scheduled_cells": 3,
        "result_relpath": None, "result_raw_sha256": None,
        "private_cells_relpath": None,
        "private_cells_raw_sha256": None,
        "candidate_net_bps_per_all_scheduled": None,
        "baseline_net_bps_per_all_scheduled": None,
        "nonexecutable_reference_only": True,
        "paper_supported": False, "sequence_valid": False,
        "external_plan_freeze_proof": "unverified",
        "science_ladder_changed": False, "orders_placed": 0,
    })
    data = project_applied_reference(root)
    forward = data["forward_h1"]
    assert forward["status"] == "closed_missing_source"
    assert forward["unknown_outcome_cells"] == 3
    assert forward["all_scheduled_reference_net_bps"] is None


def test_h1_due_reference_scores_require_exact_plan_private_and_batch_bytes(tmp_path):
    root = tmp_path / "applied-trading-public-data"
    study_id, plan_pub_sha, _ = _h1_plan(root)
    child = f"prospective-studies/{study_id}"
    plan_sha = hashlib.sha256(
        (root / child / "plan.raw.json").read_bytes()).hexdigest()
    private_path = root / child / "reference-result/reference-cells.jsonl"
    private_path.parent.mkdir(parents=True, exist_ok=True)
    private_path.write_bytes(b"private reference cell\n" * 3)
    private_sha = hashlib.sha256(private_path.read_bytes()).hexdigest()
    batch_path = "captures/spot-BTCUSDT-20260915T120000Z"
    batch_sha = _new_json(root / batch_path / "capture-batch.json", {
        "schema": "public-sealed-capture-batch/v1",
    })
    result_path = f"{child}/reference-result/result.json"
    result_sha = _new_json(root / result_path, {
        "schema": "applied-h1-rest-reference-result/v1",
        "study_id": study_id, "status": "complete_reference_review",
        "temporal_window_closed": True, "coverage_complete": True,
        "plan_sha256": plan_sha, "private_cells_sha256": private_sha,
        "driver_source_sha256": "c" * 64,
        "scheduled_cells": 3, "source_valid_cells": 2,
        "batch_capture_sha256s": [batch_sha],
        "candidate": {
            "unknown_outcome_cells": 0,
            "all_scheduled_return_identified": True,
            "net_bps_per_all_scheduled": 1.25,
        },
        "matched_momentum_baseline": {
            "unknown_outcome_cells": 0,
            "all_scheduled_return_identified": True,
            "net_bps_per_all_scheduled": -0.5,
        },
        "nonexecutable_reference_only": True,
        "paper_supported": False, "sequence_valid": False,
        "external_plan_freeze_proof": "unverified",
        "science_ladder_changed": False, "orders_placed": 0,
        "private_model_reasoning": "MUST NOT BE EXPORTED",
    })
    _new_json(root / f"publications/h1-rest-{study_id}.result.json", {
        "schema": "applied-trading-publication/v1",
        "kind": "h1_rest_pilot_result",
        "status": "admitted_reference_result",
        "study_id": study_id,
        "published_at": "2026-09-15T15:45:00Z",
        "plan_publication_relpath":
            f"publications/h1-rest-{study_id}.plan.json",
        "plan_publication_raw_sha256": plan_pub_sha,
        "scheduled_cells": 3, "source_valid_cells": 2,
        "selected_batch_relpaths": [batch_path],
        "selected_batches_count": 1,
        "result_relpath": result_path, "result_raw_sha256": result_sha,
        "private_cells_relpath":
            f"{child}/reference-result/reference-cells.jsonl",
        "private_cells_raw_sha256": private_sha,
        "driver_source_sha256": "c" * 64,
        "grade_replay": "deterministic_rest_reference_result_and_private_cells",
        "candidate_unknown_outcome_cells": 0,
        "baseline_unknown_outcome_cells": 0,
        "candidate_net_bps_per_all_scheduled": 1.25,
        "baseline_net_bps_per_all_scheduled": -0.5,
        "nonexecutable_reference_only": True,
        "paper_supported": False, "sequence_valid": False,
        "external_plan_freeze_proof": "unverified",
        "science_ladder_changed": False, "orders_placed": 0,
    })
    projected = project_applied_reference(root)["forward_h1"]
    assert projected["status"] == "rest_reference_recorded"
    assert projected["all_scheduled_reference_net_bps"] == {
        "candidate": 1.25, "baseline": -0.5,
    }
    assert "private_model_reasoning" not in str(projected)
    (root / batch_path / "capture-batch.json").write_bytes(b"changed capture")
    assert project_applied_reference(root)["forward_h1"]["status"] == (
        "source_unavailable")
    _new_json(root / batch_path / "capture-batch.json", {
        "schema": "public-sealed-capture-batch/v1",
    })
    private_path.write_bytes(b"tampered private cell\n")
    invalid = project_applied_reference(root)["forward_h1"]
    assert invalid["status"] == "source_unavailable"
    assert invalid.get("all_scheduled_reference_net_bps") is None
    private_path.write_bytes(b"private reference cell\n" * 3)
    receipt_path = root / f"publications/h1-rest-{study_id}.result.json"
    receipt = json.loads(receipt_path.read_bytes())
    receipt.pop("grade_replay")
    _new_json(receipt_path, receipt)
    assert project_applied_reference(root)["forward_h1"]["status"] == (
        "source_unavailable")


def test_h1_result_publication_without_exact_prestart_sha_is_withheld(tmp_path):
    root = tmp_path / "applied-trading-public-data"
    study_id, _, _ = _h1_plan(root)
    _new_json(root / f"publications/h1-rest-{study_id}.result.json", {
        "schema": "applied-trading-publication/v1",
        "kind": "h1_rest_pilot_result",
        "status": "closed_missing_source", "study_id": study_id,
        "published_at": "2026-09-15T15:45:00Z",
        "plan_publication_relpath":
            f"publications/h1-rest-{study_id}.plan.json",
        "plan_publication_raw_sha256": "f" * 64,
        "scheduled_cells": 3,
        "nonexecutable_reference_only": True,
        "paper_supported": False, "sequence_valid": False,
        "external_plan_freeze_proof": "unverified",
        "science_ladder_changed": False, "orders_placed": 0,
    })
    data = project_applied_reference(root)
    assert data["forward_h1"]["status"] == "source_unavailable"
    assert data["forward_h1"].get("all_scheduled_reference_net_bps") is None
