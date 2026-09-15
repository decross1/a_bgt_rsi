"""No model calls: archived publication byte-drift and score-withholding tests."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from backend.followon_results_progress import project_followon_results


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
