"""No model calls: archived publication byte-drift and score-withholding tests."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from backend import followon_results_progress as projection
from backend.followon_results_progress import (
    SourceError,
    _coding_replay,
    _repair_replay,
    project_followon_results,
)
from backend.local_model_research import Reader


def _write(path: Path, value: dict) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    path.write_bytes(raw)
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw)}


def _publication(tmp_path: Path, *, condition: list[str] | None = None) -> tuple[Path, Path]:
    root = tmp_path / "research"
    child = "qfn-followon-c0-pilot-20260915-a.resident"
    folder = root / "evaluation/followon-reports" / child
    window_id = child.removesuffix(".resident")
    source = _write(
        root / "evaluation/followon-window-plans" / f"{child}.json",
        {"schema_version": "flash-followon-window/v1", "window_id": window_id,
         "cohort": "resident", "route_bindings": {
             "resident_qwen": {}, "resident_gemma": {},
         },
         "blocks": [{"ordinal": 0, "block_id": "thinking-71",
                     "kind": "thinking", "endpoint_name": "resident_qwen",
                     "output_relative": "blocks/thinking"}]},
    )
    result = _write(root / "evaluation/followon-runs" / child / "result.json",
                    {"pair_id": window_id})
    run = _write(root / "evaluation/followon-runs" / child /
                 "blocks" / "thinking" / "run.json", {"outcomes": []})
    bundle = "f" * 64
    proof_block = {"block_id": "thinking-71", "kind": "thinking",
                   "run_sha256": run["sha256"], "attempted": 0,
                   "passed": 0, "timeouts": 0}
    gate = _write(folder / "completed-gate.json", {
        "schema": "flash-followon-completed-window-validation/v1",
        "window_id": window_id, "cohort": "resident",
        "window_plan_sha256": source["sha256"],
        "result_sha256": result["sha256"],
        "controller_source_bundle_sha256": bundle,
        "exact_restoration_verified": True,
        "comparison_eligible": False, "promotion_authorized": False,
        "private_content_exported": False, "blocks": [proof_block],
    })
    report = _write(folder / "report.json", {
        "schema": "flash-followon-content-free-report/v1",
        "window_id": window_id, "cohort": "resident",
        "window_plan_sha256": source["sha256"],
        "result_sha256": result["sha256"],
        "controller_source_bundle_sha256": bundle,
        "exact_restoration_verified": True,
        "comparison_eligible": False, "score_claim_authorized": False,
        "promotion_authorized": False, "private_content_exported": False,
        "blocks": [{"block_id": "thinking-71", "kind": "thinking",
                    "run_sha256": run["sha256"], "attempted": 0,
                    "passed": 0, "timeouts": 0, "groups": [{
                        "condition": condition or ["off", "critic"], "declared": 0,
                        "attempted": 0, "passed": 0, "timeouts": 0,
                        "errors": 0, "supported": 0, "unsupported": 0,
                        "wall_seconds": 0, "calls": 0,
                        "recorded_timings": 0,
                        "mean_request_latency_seconds": None,
                        "mean_first_token_seconds": None,
                        "actual_input_tokens_min": None,
                        "actual_input_tokens_max": None,
                        "private_completion": "must never cross the UI boundary",
                    }]}],
    })
    _write(folder / "index.json", {
        "schema": "flash-followon-report-publication/v1",
        "kind": "independent_window", "window_id": window_id,
        "cohort": "resident", "complete": True,
        "archived_completed_gate_admitted": True,
        "comparison_eligible": False, "score_claim_authorized": False,
        "promotion_authorized": False, "private_content_exported": False,
        "recorded_controller_source_bundle_sha256": bundle,
        "current_source_replay": "verified",  # unproven index claim
        "recorded_gate_ref": gate, "report_ref": report,
        "raw_refs": {
            "window_source": source, "terminal_result": result,
            "block_runs": [{"block_id": "thinking-71", "kind": "thinking",
                            **run}],
        },
    })
    return root, Path(run["path"])


def test_archived_restored_window_shows_descriptive_counts_without_replay_claim(tmp_path):
    root, _ = _publication(tmp_path)
    projection = project_followon_results(root)
    assert projection["status"] == "available"
    assert len(projection["windows"]) == 1
    row = projection["windows"][0]
    assert row["admission_class"] == "RECORDED_COMPLETED_WINDOW_ADMISSION"
    assert row["current_source_replay"] == "not_performed"
    assert row["comparison_eligible"] is False
    assert row["routes"] == ["resident_qwen"]
    assert row["recorded_controller_source_bundle_sha256"] == "f" * 64
    assert "private_completion" not in row["blocks"][0]["groups"][0]


def test_changed_block_run_withholds_recorded_counts(tmp_path):
    root, run = _publication(tmp_path)
    run.write_text('{"outcomes":[{"passed":true}]}\n')
    projection = project_followon_results(root)
    assert projection["windows"] == []
    assert projection["status"] == "partial"
    assert "scores are withheld" in projection["warnings"][0]


def test_unindexed_partial_child_never_becomes_a_score(tmp_path):
    root = tmp_path / "research"
    (root / "evaluation/followon-reports" /
     "qfn-followon-pending-20260915-b.flash").mkdir(parents=True)
    projection = project_followon_results(root)
    assert projection["windows"] == []
    assert projection["status"] == "available"


def test_hash_bound_but_unregistered_condition_text_is_withheld(tmp_path):
    root, _ = _publication(
        tmp_path, condition=["unbounded raw model completion text"],
    )
    projection = project_followon_results(root)
    assert projection["windows"] == []
    assert projection["status"] == "partial"


def test_selected_repair_replay_projects_only_bound_numeric_counts():
    replay = {
        "schema": "flash-followon-selected-repair-grader-replay/v1",
        "run_sha256": "e" * 64,
        "replay_receipt_sha256": "f" * 64,
        "source_replay_status": "available",
        "raw_private_calls_verified": 22, "declared": 22,
        "replayed": 20, "producer_consistent": 20,
        "producer_inconsistent": 0, "grader_unavailable": 2,
        "by_lane": {"resident_native": {
            "declared": 22, "producer_passed": 8,
            "replayed": 20, "replayed_passed": 8,
            "producer_consistent": 20, "producer_inconsistent": 0,
            "grader_unavailable": 2,
        }},
        "comparison_eligible": False,
        "private_content_exported": False,
        "private_completion": "must never enter the public response",
    }
    block = {"kind": "selected_repair", "run_sha256": "e" * 64,
             "attempted": 22, "passed": 8, "grader_replay": replay}
    projected = _repair_replay(block, "resident")
    assert projected["producer_consistent"] == 20
    assert projected["grader_unavailable"] == 2
    assert "private_completion" not in projected
    assert "private_content_exported" not in projected


def test_coding_diagnostic_replay_projects_four_original_grades_only():
    families = {
        "portfolio": {"declared": 2, "producer_passed": 1,
                      "replayed": 2, "replayed_passed": 1,
                      "producer_consistent": 2,
                      "producer_inconsistent": 0, "grader_unavailable": 0},
        "historical": {"declared": 2, "producer_passed": 0,
                       "replayed": 2, "replayed_passed": 0,
                       "producer_consistent": 2,
                       "producer_inconsistent": 0, "grader_unavailable": 0},
    }
    replay = {
        "schema": "flash-followon-coding-temp1-grader-replay/v1",
        "run_sha256": "e" * 64, "replay_receipt_sha256": "f" * 64,
        "source_replay_status": "available",
        "raw_private_calls_verified": 4, "declared": 4,
        "replayed": 4, "producer_consistent": 4,
        "producer_inconsistent": 0, "grader_unavailable": 0,
        "by_family": families,
        "comparison_eligible": False, "private_content_exported": False,
        "private_completion": "must never cross the UI boundary",
    }
    block = {"kind": "coding_temp1_medium", "run_sha256": "e" * 64,
             "attempted": 4, "passed": 1, "grader_replay": replay}
    projected = _coding_replay(block, "flash")
    assert projected["producer_consistent"] == 4
    assert set(projected["by_family"]) == {"portfolio", "historical"}
    assert "private_completion" not in projected
    wrong = {**replay, "declared": 3}
    with pytest.raises(SourceError):
        _coding_replay({**block, "grader_replay": wrong}, "flash")
    with pytest.raises(SourceError):
        _coding_replay(block, "resident")


@pytest.mark.parametrize("change", [
    {"run_sha256": "a" * 64},
    {"declared": 21},
    {"source_replay_status": "verified"},
])
def test_selected_repair_replay_rejects_unbound_or_incomplete_counts(change):
    replay = {
        "schema": "flash-followon-selected-repair-grader-replay/v1",
        "run_sha256": "e" * 64, "replay_receipt_sha256": "f" * 64,
        "source_replay_status": "available",
        "raw_private_calls_verified": 22, "declared": 22,
        "replayed": 22, "producer_consistent": 22,
        "producer_inconsistent": 0, "grader_unavailable": 0,
        "by_lane": {"resident_native": {
            "declared": 22, "producer_passed": 8,
            "replayed": 22, "replayed_passed": 8,
            "producer_consistent": 22, "producer_inconsistent": 0,
            "grader_unavailable": 0,
        }},
        "comparison_eligible": False, "private_content_exported": False,
    }
    replay.update(change)
    block = {"kind": "selected_repair", "run_sha256": "e" * 64,
             "attempted": 22, "passed": 8, "grader_replay": replay}
    with pytest.raises(SourceError):
        _repair_replay(block, "resident")


def test_selected_resident_predeclared_compatibility_source_is_byte_bound(
    tmp_path, monkeypatch,
):
    root = tmp_path / "research"
    publication = (root / "evaluation/followon-reports" /
                   "qfn-followon-selected-repair-20260915-a.resident")
    publication.mkdir(parents=True)
    source = publication / "selected-resident-compat.py"
    raw = b"# archived chronology validator\n"
    source.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    monkeypatch.setattr(projection, "SELECTED_COMPAT_SHA256", digest)
    index = {"archived_reader_source_refs": {
        "selected-resident-compat.py": {
            "path": str(source), "sha256": digest, "bytes": len(raw),
        },
    }}
    gate = {"chronology_compatibility": {
        "schema": "flash-followon-selected-repair-resident-start-compatibility/v1",
        "repair": "missing_result_started_at_derived_from_exact_final_state_only",
        "original_result_bytes_preserved": True,
        "other_completed_window_checks_unchanged": True,
        "comparison_eligible": False,
        "compatibility_reader_sha256": digest,
        "state_sha256": "a" * 64, "supervision_sha256": "b" * 64,
        "memory_log_sha256": "c" * 64, "gate_source_sha256": "d" * 64,
        "final_state_started_at": "2026-09-15T12:00:00Z",
    }}
    report = {"blocks": [{"kind": "selected_repair"}]}
    args = (Reader(root), root, publication, index, gate, report,
            "qfn-followon-selected-repair-20260915-a", "resident")
    projection._selected_resident_gate(*args)
    source.write_bytes(raw + b"# drift\n")
    with pytest.raises(SourceError):
        projection._selected_resident_gate(*args)
