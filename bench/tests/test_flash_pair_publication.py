"""Synthetic publication checks; no registered pair or endpoint is touched."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from bench.flash_next_ab.pair_publication import (
    PublicationError,
    prepare_pair,
    publish_pair,
)

PAIR_ID = "qfn-ab-mia-c0-20260915-a"


def write(root: Path, relative: str, value: dict) -> str:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, sort_keys=True).encode() + b"\n"
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def sources(tmp_path: Path):
    root = tmp_path / "research"
    root.mkdir()
    gate = {
        "schema": "flash-next-supervised-pair-validation/v1",
        "pair_id": PAIR_ID, "promotion_authorized": False,
    }
    for cohort in ("resident", "flash"):
        prefix = f"evaluation/runs/{PAIR_ID}.{cohort}"
        qualification = {}
        names = (
            ("receipt", "qualification_plan", "contract_snapshot", "contract_raw")
            if cohort == "flash" else ("receipt", "resident_artifacts")
        )
        for name in names:
            folder = "qualification-runs" if cohort == "flash" else "runtime"
            path = f"{folder}/{cohort}/{name}.json"
            digest = write(root, path, {"source": name, "cohort": cohort})
            qualification[name] = {"path": str(root / path), "sha256": digest}
        window = {
            "schema_version": "flash-next-evaluation-window/v1",
            "pair_id": PAIR_ID, "cohort": cohort,
            "qualification": qualification,
        }
        window_sha = write(
            root, f"evaluation/window-plans/{PAIR_ID}.{cohort}.window.json", window
        )
        result_sha = write(
            root, f"{prefix}/result.json", {
                "status": "complete", "pair_id": PAIR_ID,
                "window_plan_sha256": window_sha,
            }
        )
        run_sha = write(
            root, f"{prefix}/harness/run.json",
            {"status": "complete", "cohort": cohort,
             "promotion_authorized": False, "manifest_sha256": "f" * 64,
             "declared_cells": ["objective/a", "objective/b"],
             "outcomes": [
                 {"cell_id": "objective/a", "family": "objective", "status": "returned",
                  "passed": True, "wall_s": 5.0, "source": {"suite_id": "synthetic",
                   "manifest_sha256": "1" * 64, "task_sha256": "a" * 64}},
                 {"cell_id": "objective/b", "family": "objective", "status": "timeout",
                  "passed": False, "wall_s": 7.0, "source": {"suite_id": "synthetic",
                   "manifest_sha256": "1" * 64, "task_sha256": "b" * 64}},
             ],
             "secret_completion": "PRIVATE MODEL TEXT MUST NOT BE EXPORTED"},
        )
        gate[cohort] = {
            "cohort": cohort, "pair_id": PAIR_ID,
            "restoration_verified": True,
            "weekly_budget_debit": False, "paid_api_calls": 0,
            "production_change_authorized": False,
            "result_sha256": result_sha,
            "harness_run_sha256": run_sha,
            "benchmark_plan_file_sha256": "b" * 64,
        }
        if cohort == "flash":
            gate[cohort]["window_plan_sha256"] = window_sha
    write(root, f"evaluation/runs/{PAIR_ID}.flash/extended-plan.json", {
        "pair_id": PAIR_ID,
        "controller_source_bundle_sha256": "c" * 64,
        "candidate_variant_id": "mia-925d7be6-c0-s1",
        "candidate_spec_sha256": "d" * 64,
        "model_artifact_sha256": "e" * 64,
    })
    return root, gate


def summary_fn(_resident, _flash):
    arm = {
        "declared": 2, "attempted": 2, "passed": 1,
        "success_rate": .5, "wall_s_including_failures": 12.0,
        "successful_task_runs_per_hour": 300.0,
    }
    return {
        "schema_version": "flash-next-ab-comparison/v1",
        "status": "complete", "comparison_eligible": True,
        "promotion_authorized": False, "causal_attribution": None,
        "manifest_sha256": "f" * 64,
        "families": {"objective": {
            "cohorts": {"resident": arm, "flash": arm},
            "task_runs": 2, "resampling_units": 2,
            "paired_success_delta": 0.0,
            "equal_source_task_success_delta": 0.0,
            "source_task_cluster_resampling_95_interval": [0.0, 0.0],
            "both_passed_task_runs": 1,
            "resident_only_passed_task_runs": 0,
            "flash_only_passed_task_runs": 0,
            "neither_passed_task_runs": 1,
        }},
        "elapsed_s": {"resident": 12.0, "flash": 12.0},
        "bootstrap_samples": 2000, "bootstrap_seed": 1701,
    }


def test_prepare_is_read_only_and_exports_no_private_outcomes(tmp_path):
    root, gate = sources(tmp_path)
    prepared = prepare_pair(root, PAIR_ID, gate_fn=lambda *_: gate,
                            summarize_fn=summary_fn)
    assert not (root / prepared.aggregate_path).exists()
    assert not (root / prepared.proof_path).exists()
    assert not (root / "evaluation/dashboard-index.json").exists()
    assert b"PRIVATE MODEL TEXT" not in prepared.aggregate_raw
    assert b"PRIVATE MODEL TEXT" not in prepared.proof_raw
    aggregate = json.loads(prepared.aggregate_raw)
    assert aggregate["admission_class"] == "RECORDED_COMPLETED_PAIR_ADMISSION"
    assert aggregate["families"]["objective"]["cohorts"]["flash"]["declared"] == 2
    assert aggregate["causal_attribution"] is None


def test_publish_appends_without_changing_old_entries_and_is_idempotent(tmp_path):
    root, gate = sources(tmp_path)
    old = {"id": "qfn-ab-older", "note": "historical entry retained byte-for-byte"}
    write(root, "evaluation/dashboard-index.json", {
        "schema_version": "flash-next-dashboard-index/v1", "comparisons": [old]
    })
    prepared = publish_pair(root, PAIR_ID, gate_fn=lambda *_: gate,
                            summarize_fn=summary_fn, test_root_allowed=True)
    index = json.loads((root / "evaluation/dashboard-index.json").read_text())
    assert index["comparisons"] == [old, prepared.index_entry]
    assert (root / prepared.aggregate_path).read_bytes() == prepared.aggregate_raw
    assert (root / prepared.proof_path).read_bytes() == prepared.proof_raw
    again = publish_pair(root, PAIR_ID, gate_fn=lambda *_: gate,
                         summarize_fn=summary_fn, test_root_allowed=True)
    assert again == prepared
    assert json.loads((root / "evaluation/dashboard-index.json").read_text())[
        "comparisons"
    ] == [old, prepared.index_entry]


def test_failed_or_incomplete_gate_never_adds_a_comparison(tmp_path):
    root, gate = sources(tmp_path)
    before = {"schema_version": "flash-next-dashboard-index/v1", "comparisons": []}
    write(root, "evaluation/dashboard-index.json", before)
    bad = dict(gate, flash=dict(gate["flash"], restoration_verified=False))
    with pytest.raises(PublicationError, match="not admitted"):
        publish_pair(root, PAIR_ID, gate_fn=lambda *_: bad,
                     summarize_fn=summary_fn, test_root_allowed=True)
    assert json.loads((root / "evaluation/dashboard-index.json").read_text()) == before
    assert not (root / f"evaluation/aggregate-summaries/{PAIR_ID}.json").exists()


def test_source_drift_after_gate_is_rejected(tmp_path):
    root, gate = sources(tmp_path)
    result = root / f"evaluation/runs/{PAIR_ID}.flash/result.json"
    result.write_text('{"status":"complete","tampered":true}\n')
    with pytest.raises(PublicationError, match="source hash changed"):
        prepare_pair(root, PAIR_ID, gate_fn=lambda *_: gate,
                     summarize_fn=summary_fn)
    assert not (root / "evaluation/dashboard-index.json").exists()


def test_real_projection_reads_published_proof_and_failure_denominators(tmp_path, monkeypatch):
    from backend import local_model_pair_proof as proof
    from backend.local_model_research import project_local_research

    root, gate = sources(tmp_path)
    publish_pair(root, PAIR_ID, gate_fn=lambda *_: gate,
                 summarize_fn=summary_fn, test_root_allowed=True)
    monkeypatch.setattr(proof, "_source_replay", lambda *_: "unavailable")
    data = project_local_research(root)
    comparison = data["comparisons"][0]
    assert comparison["comparison_eligible_at_recording"] is True
    assert comparison["current_source_replay"] == "unavailable"
    arm = comparison["families"][0]["cohorts"]["flash"]
    assert arm == {"declared": 2, "attempted": 2, "passed": 1,
                   "success_rate": 0.5, "wall_s_including_failures": 12.0,
                   "successful_task_runs_per_hour": 300.0}
    assert "PRIVATE MODEL TEXT" not in json.dumps(data)


def test_projection_withholds_scores_after_raw_run_changes(tmp_path, monkeypatch):
    from backend import local_model_pair_proof as proof
    from backend.local_model_research import project_local_research

    root, gate = sources(tmp_path)
    publish_pair(root, PAIR_ID, gate_fn=lambda *_: gate,
                 summarize_fn=summary_fn, test_root_allowed=True)
    monkeypatch.setattr(proof, "_source_replay", lambda *_: "unavailable")
    run = root / f"evaluation/runs/{PAIR_ID}.flash/harness/run.json"
    run.write_bytes(run.read_bytes() + b" ")
    data = project_local_research(root)
    assert data["comparisons"] == []
    assert any("scores are withheld" in message for message in data["warnings"])


def test_recount_rejects_rehashed_aggregate_with_inflated_success(tmp_path, monkeypatch):
    from backend import local_model_pair_proof as proof
    from backend.local_model_research import project_local_research

    root, gate = sources(tmp_path)
    prepared = publish_pair(root, PAIR_ID, gate_fn=lambda *_: gate,
                            summarize_fn=summary_fn, test_root_allowed=True)
    aggregate = json.loads(prepared.aggregate_raw)
    arm = aggregate["families"]["objective"]["cohorts"]["flash"]
    arm.update(passed=2, success_rate=1.0, successful_task_runs_per_hour=600.0)
    new_aggregate_sha = write(root, prepared.aggregate_path, aggregate)
    changed_proof = json.loads(prepared.proof_raw)
    changed_proof["aggregate"]["sha256"] = new_aggregate_sha
    new_proof_sha = write(root, prepared.proof_path, changed_proof)
    entry = prepared.index_entry
    entry["aggregate"]["sha256"] = new_aggregate_sha
    entry["admission"]["sha256"] = new_proof_sha
    write(root, "evaluation/dashboard-index.json", {
        "schema_version": "flash-next-dashboard-index/v1", "comparisons": [entry],
    })
    monkeypatch.setattr(proof, "_source_replay", lambda *_: "unavailable")
    assert project_local_research(root)["comparisons"] == []


def test_failed_replay_with_unchanged_sources_withholds_scores(tmp_path, monkeypatch):
    from backend import local_model_pair_proof as proof
    from backend.local_model_research import project_local_research

    root, gate = sources(tmp_path)
    publish_pair(root, PAIR_ID, gate_fn=lambda *_: gate,
                 summarize_fn=summary_fn, test_root_allowed=True)

    def failed_replay(*_):
        raise proof.ProofError("unchanged controller cannot replay admission")

    monkeypatch.setattr(proof, "_source_replay", failed_replay)
    assert project_local_research(root)["comparisons"] == []
