"""Only independently admitted fresh/context indexes supply public counts."""
from __future__ import annotations

import copy
from pathlib import Path

from backend import lab_model_supplement_progress as supplement


def _score(declared: int, passed: int, wall: float) -> dict:
    return {"declared": declared, "attempted": declared, "returned": declared,
            "timeout": 0, "error": 0, "cancelled": 0, "passed": passed,
            "wall_s_including_failures": wall}


def _fresh() -> dict:
    resident = {"variant_id": "resident-role-bundle", "status": "complete",
                "elapsed_s": 100.0, "raw_response_replay_passed": True,
                "scores": {"total": _score(12, 7, 120.0),
                           "by_kind": {"science": _score(6, 5, 60.0),
                                       "coding": _score(6, 2, 60.0)}},
                "configured_context_tokens_by_endpoint": {
                    "resident_qwen": 16384, "resident_gemma": 32768},
                "measured_prompt_tokens_max_by_endpoint": {
                    "resident_qwen": 400, "resident_gemma": 3000},
                "normalization_diagnostic": {
                    "coding_returned_attempted": 6,
                    "sandbox_passes_after_predeclared_transform": 3,
                    "never_replaces_primary_score": True}}
    flash = copy.deepcopy(resident)
    flash["variant_id"] = supplement.FLASH_VARIANT
    flash["scores"]["total"]["passed"] = 8
    flash["scores"]["by_kind"]["science"]["passed"] = 6
    flash["configured_context_tokens_by_endpoint"] = {"flash_next_mia": 32768}
    flash["measured_prompt_tokens_max_by_endpoint"] = {"flash_next_mia": 2700}
    return {
        "schema_version": supplement.REPORT_SCHEMA, "kind": "fresh",
        "pair_id": supplement.KINDS["fresh"]["pair_id"],
        "status": "complete_admitted_pair", "denominator_per_cohort": 12,
        "suite_id": supplement.KINDS["fresh"]["suite_id"],
        "cell_set": supplement.KINDS["fresh"]["cell_set"],
        "plan_raw_sha256": "a" * 64,
        "claim_limit": supplement.KINDS["fresh"]["claim_limit"],
        "original_scores_rebased": False, "heldout_claim": False,
        "private_content_exported": False, "promotion_authorized": False,
        "cohorts": {"resident": resident, "flash": flash},
        "raw_private_response": "must not leave the API",
    }


def _context() -> dict:
    cap = {key: _score(12, 8, 12.0) for key in ("8192", "16384", "32768")}
    placement = {"early": _score(12, 12, 12.0),
                 "middle": _score(12, 6, 12.0),
                 "late": _score(12, 6, 12.0)}
    grid = {key: {"early": _score(4, 4, 4.0),
                  "middle": _score(4, 2, 4.0),
                  "late": _score(4, 2, 4.0)}
            for key in cap}
    resident = {"variant_id": "resident-gemma", "status": "complete",
                "elapsed_s": 60.0, "raw_response_replay_passed": True,
                "scores": {"total": _score(36, 24, 36.0),
                           "by_capacity": cap, "by_placement": placement,
                           "by_capacity_placement": grid,
                           "measured_prompt_tokens_max_by_capacity": {
                               "8192": 7000, "16384": 15000, "32768": 30000}},
                "configured_context_tokens": 32768,
                "measured_prompt_tokens_max": 30000,
                "output_reserve_tokens": 2048}
    flash = copy.deepcopy(resident)
    flash["variant_id"] = supplement.FLASH_VARIANT
    return {
        "schema_version": supplement.REPORT_SCHEMA, "kind": "context",
        "pair_id": supplement.KINDS["context"]["pair_id"],
        "status": "complete_admitted_pair", "denominator_per_cohort": 36,
        "suite_id": supplement.KINDS["context"]["suite_id"],
        "cell_set": supplement.KINDS["context"]["cell_set"],
        "plan_raw_sha256": "b" * 64,
        "claim_limit": supplement.KINDS["context"]["claim_limit"],
        "original_scores_rebased": False, "heldout_claim": False,
        "private_content_exported": False, "promotion_authorized": False,
        "cohorts": {"resident": resident, "flash": flash},
    }


def _indexes(tmp_path: Path) -> Path:
    root = tmp_path / "publications"
    for kind, registered in supplement.KINDS.items():
        child = root / registered["pair_id"]
        child.mkdir(parents=True)
        (child / "index.json").write_text('{"kind":"' + kind + '"}', encoding="utf-8")
    return root


def test_independent_admitted_reports_export_only_numeric_public_fields(tmp_path):
    root = _indexes(tmp_path)
    reports = {"fresh": _fresh(), "context": _context()}
    reader = lambda path: reports["fresh" if "fresh" in str(path) else "context"]
    view = supplement.project_progress(publication_reader=reader, publication_root=root)
    assert view["schema_version"] == supplement.SCHEMA
    assert view["pairs"]["fresh"]["status"] == "complete_admitted_pair"
    assert view["pairs"]["fresh"]["cohorts"]["resident"]["scores"]["by_kind"]["science"]["passed"] == 5
    assert view["pairs"]["context"]["cohorts"]["flash"]["scores"]["by_capacity"]["32768"]["passed"] == 8
    assert view["pairs"]["context"]["cohorts"]["flash"]["scores"]["by_capacity_placement"]["32768"]["late"]["declared"] == 4
    assert "raw_private_response" not in str(view)
    assert view["promotion_authorized"] is False


def test_unpublished_or_rejected_pair_withholds_all_scores(tmp_path):
    root = tmp_path / "empty"
    root.mkdir()
    pending = supplement.project_progress(publication_root=root)
    assert {row["status"] for row in pending["pairs"].values()} == {"pending_publication"}
    assert all(row["cohorts"] is None for row in pending["pairs"].values())
    root = _indexes(tmp_path)
    fresh = _fresh()
    fresh["cohorts"]["flash"]["scores"]["total"]["passed"] = 13
    view = supplement.project_progress(
        publication_root=root,
        publication_reader=lambda path: fresh if "fresh" in str(path) else _context())
    assert view["pairs"]["fresh"]["status"] == "source_unavailable"
    assert view["pairs"]["fresh"]["cohorts"] is None
    assert view["pairs"]["context"]["status"] == "complete_admitted_pair"


def test_report_extra_text_or_claim_drift_cannot_be_projected(tmp_path):
    fresh = _fresh()
    shown = supplement._project_report(fresh, kind="fresh")
    assert "raw_private_response" not in str(shown)
    fresh["suite_id"] = "private prompt text"
    try:
        supplement._project_report(fresh, kind="fresh")
    except ValueError:
        pass
    else:
        raise AssertionError("source-registered suite identity drift was accepted")
