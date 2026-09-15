"""Only one exact, independently admitted matched-24 publication supplies scores."""
from __future__ import annotations

import copy
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import lab_model_context_crossplan_progress as progress

SHA = "a" * 64


def _lane(passed: int) -> dict:
    return {
        "declared": 12, "attempted": 12, "passed": passed, "returned": 12,
        "timeout": 0, "error": 0, "cancelled": 0,
        "wall_s_including_failures": 36.0,
        "measured_prompt_tokens_max": 6000,
        "observed_2048_output_reserve_within_total_band": True,
    }


def _report() -> dict:
    row = {
        "resident_qwen": _lane(6),
        "flash_next_mia": _lane(8),
        "matched_cell_pass_categories": {
            "qwen_only": 1, "mia_only": 3, "both_pass": 5, "neither_pass": 3,
        },
    }
    return {
        "schema_version": progress.REPORT_SCHEMA,
        "publication_id": progress.PUBLICATION_ID,
        "status": "complete_cross_plan_diagnostic",
        "comparison_kind": "cross_plan_matched24_development_diagnostic",
        "same_plan_pair": False,
        "qwen_plan_flash_arm_issued_for_this_comparison": False,
        "qwen_window_id": "qfn-ab-lab-context-qwen-20260915-a",
        "mia_window_id": "qfn-ab-lab-context-20260915-a",
        "arm_identities": {
            "resident_qwen": {
                "candidate_variant_id": "resident-qwen",
                "served_model": "qwen3.8-27b-nvfp4-mtp",
                "artifact_sha256": SHA, "runtime_sha256": SHA,
                "configured_max_context_tokens": 16384,
            },
            "flash_next_mia": {
                "candidate_variant_id": progress.FLASH_VARIANT,
                "served_model": "qwen3.8-flash-next-mia",
                "artifact_sha256": SHA, "runtime_sha256": SHA,
                "configured_max_context_tokens": 32768,
            },
        },
        "qwen_plan_raw_sha256": SHA, "mia_plan_raw_sha256": SHA,
        "packet_raw_sha256": progress.PACK_SHA,
        "overlap_receipts_sha256": SHA,
        "grade_replay": progress.GRADE_REPLAY,
        "matched_cells": 24, "capacities_total_tokens": [8192, 16384],
        "output_reserve_tokens": 2048,
        "by_capacity": {"8192": copy.deepcopy(row), "16384": copy.deepcopy(row)},
        "private_response_exported": False,
        "heldout_claim": False, "promotion_authorized": False,
        "raw_private_response": "must never leave the API",
    }


def _index_root(tmp_path: Path) -> Path:
    child = tmp_path / progress.PUBLICATION_ID
    child.mkdir()
    (child / "index.json").write_text('{"sealed":true}\n', encoding="utf-8")
    return tmp_path


def test_pending_publication_does_not_import_reader_or_expose_score(tmp_path):
    view = progress.project_progress(
        publication_root=tmp_path,
        publication_reader=lambda _: (_ for _ in ()).throw(
            AssertionError("reader called without index")),
    )
    assert view["status"] == "pending_publication"
    assert view["by_capacity"] is None
    assert view["grade_replay"] == "not_available"


def test_admitted_report_exports_only_bounded_numeric_counts(tmp_path):
    root = _index_root(tmp_path)
    view = progress.project_progress(
        publication_root=root, publication_reader=lambda _: _report(),
    )
    assert view["status"] == "complete_cross_plan_diagnostic"
    assert view["by_capacity"]["8192"]["resident_qwen"]["passed"] == 6
    assert view["by_capacity"]["8192"]["flash_next_mia"]["passed"] == 8
    assert view["by_capacity"]["16384"]["matched_cell_pass_categories"]["both_pass"] == 5
    assert view["configured_total_tokens"] == {
        "resident_qwen": 16384, "flash_next_mia": 32768,
    }
    assert "raw_private_response" not in str(view)
    assert view["promotion_authorized"] is False


def test_source_or_matched_count_drift_withholds_all_scores(tmp_path):
    root = _index_root(tmp_path)
    for mutate in (
        lambda row: row.update(promotion_authorized=True),
        lambda row: row["arm_identities"]["resident_qwen"].update(
            configured_max_context_tokens=32768),
        lambda row: row["by_capacity"]["8192"]["matched_cell_pass_categories"].update(
            both_pass=6),
        lambda row: row["by_capacity"]["16384"]["resident_qwen"].update(
            measured_prompt_tokens_max=15000),
        lambda row: row.update(qwen_window_id="another-window"),
    ):
        source = _report()
        mutate(source)
        view = progress.project_progress(
            publication_root=root, publication_reader=lambda _, row=source: row,
        )
        assert view["status"] == "source_unavailable"
        assert view["by_capacity"] is None
        assert view["publication_index_raw_sha256"] is None


def test_route_exposes_read_only_pending_projection(tmp_path):
    app = FastAPI()
    progress.register(
        app, projector=lambda: progress.project_progress(publication_root=tmp_path),
    )
    response = TestClient(app).get("/api/lab_model_context_crossplan_progress")
    assert response.status_code == 200
    assert response.json()["status"] == "pending_publication"
