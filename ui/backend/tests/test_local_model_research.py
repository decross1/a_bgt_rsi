"""Local R&D is independently sourced; incomplete/invalid work cannot be a win."""
import hashlib
import json
import os

import pytest

from backend.local_model_research import Reader, SourceError, project_local_research


def write(root, path, value):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value).encode()
    target.write_bytes(raw)
    return {"path": path, "sha256": hashlib.sha256(raw).hexdigest()}


def qualification(root, *, status="passed", restoration="verified"):
    name = "qfn-c0-fixture"
    return write(root, f"qualification-runs/{name}/result.json", {
        "schema": "qwen-flash-next-qualification-result/v1", "run_id": name,
        "status": status, "restoration": {"status": restoration},
        "weekly_budget_debit": False, "production_change_authorized": False,
        "challenger_gpu_seconds": 120, "min_mem_available_gib": 35,
        "probe_count": 3, "finished_at": "2026-09-15T01:00:00+00:00",
        "qualification_error": "PRIVATE MODEL TEXT SHOULD NEVER REACH UI",
    })


def pair(root, monkeypatch, *, flash_status="complete"):
    # Receipt semantic validation belongs to compare.validate_run's independent
    # adversarial suite. This seam tests projection, hash binding and denominators.
    from bench.flash_next_ab import compare, harness

    monkeypatch.setattr(compare, "validate_run", lambda run, cohort: {row["cell_id"]: row for row in run["outcomes"]})
    monkeypatch.setattr(harness, "validate_qualification_receipt", lambda *args, **kwargs: {})
    def comparison_summary(resident, flash):
        eligible = resident["status"] == flash["status"] == "complete"
        arms = {cohort: {"declared": 1, "attempted": 1, "passed": passed,
                        "success_rate": float(passed) if eligible else None,
                        "successful_task_runs_per_hour": passed * 30 if eligible else None}
                for cohort, passed in (("resident", 0), ("flash", 1))}
        return {"status": "complete" if eligible else "incomplete", "comparison_eligible": eligible,
                "manifest_sha256": "a" * 64, "families": {"historical": {
                    "comparison_eligible": eligible, "cohorts": arms,
                    "paired_success_delta": 1 if eligible else None,
                    "equal_source_task_success_delta": 1 if eligible else None,
                    "source_task_cluster_resampling_95_interval": None}}}
    monkeypatch.setattr(compare, "summarize_pair", comparison_summary)
    refs = {}
    for cohort, passed in (("resident", False), ("flash", True)):
        row = {"manifest_sha256": "a" * 64, "declared_cells": ["one"], "plan": {},
               "status": flash_status if cohort == "flash" else "complete",
               "outcomes": [{"cell_id": "one", "family": "historical", "status": "returned", "wall_s": 120, "passed": passed}]}
        refs[cohort] = write(root, f"evaluation/{cohort}.json", row)
    write(root, "runtime/proof.json", {})
    qualifications = {"resident": {"receipt": "runtime/proof.json", "artifacts": "runtime/proof.json"},
                      "flash": {"receipt": "runtime/proof.json", "plan": "runtime/proof.json", "contract": "runtime/proof.json"}}
    write(root, "evaluation/dashboard-index.json", {
        "schema_version": "flash-next-dashboard-index/v1", "comparisons": [{"id": "fixture", **refs, "qualifications": qualifications}],
    })


def test_empty_is_pending_and_not_a_zero_score(tmp_path):
    data = project_local_research(tmp_path)
    assert data["status"] == "available"
    assert data["qualification_runs"] == data["comparisons"] == []
    assert data["promotion_authorized"] is False
    assert "outside the weekly" in data["accounting"]


def test_absent_root_is_unavailable(tmp_path):
    assert project_local_research(tmp_path / "absent")["status"] == "unavailable"


def test_qualification_is_recorded_separately_and_hides_private_text(tmp_path, monkeypatch):
    from bench.flash_next_ab import harness

    qualification(tmp_path, status="failed")
    for name in ("plan.json", "launch-contract.snapshot.json"):
        write(tmp_path, f"qualification-runs/qfn-c0-fixture/{name}", {})
    calls = []
    def validate(**kwargs):
        calls.append(kwargs["require_passed"])
        return {"qualification_receipt_sha256": hashlib.sha256(kwargs["receipt_path"].read_bytes()).hexdigest()}
    monkeypatch.setattr(harness, "validate_flash_qualification_files", validate)
    data = project_local_research(tmp_path)
    assert data["qualification_runs"][0]["candidate_window_minutes"] == 2
    assert data["comparisons"] == []
    assert "PRIVATE" not in json.dumps(data)
    assert "weekly_budget" not in data
    assert calls == [False]


def test_weak_passing_qualification_has_no_proof_and_is_withheld(tmp_path):
    qualification(tmp_path)
    data = project_local_research(tmp_path)
    assert data["qualification_runs"] == []
    assert data["warnings"]


def test_passing_qualification_with_bad_restore_is_withheld(tmp_path):
    qualification(tmp_path, restoration="unknown")
    data = project_local_research(tmp_path)
    assert data["qualification_runs"] == []
    assert data["status"] == "partial"


def test_orphan_state_does_not_claim_running(tmp_path):
    write(tmp_path, "qualification-runs/qfn-c0-old/state.json", {
        "schema": "qwen-flash-next-qualification-state/v1", "run_id": "qfn-c0-old", "phase": "readiness",
    })
    row = project_local_research(tmp_path)["qualification_runs"][0]
    assert row["status"] == "unfinished_receipt"
    assert row["restoration"] == "unverified"


def test_hash_bound_pair_counts_failures_and_elapsed(tmp_path, monkeypatch):
    pair(tmp_path, monkeypatch)
    row = project_local_research(tmp_path)["comparisons"][0]["families"][0]
    assert row["cohorts"]["resident"]["passed"] == 0
    assert row["cohorts"]["flash"]["successful_task_runs_per_hour"] == 30
    assert row["paired_success_delta"] == 1


def test_aborted_pair_has_no_comparative_gain(tmp_path, monkeypatch):
    pair(tmp_path, monkeypatch, flash_status="aborted")
    row = project_local_research(tmp_path)["comparisons"][0]["families"][0]
    assert row["paired_success_delta"] is None
    assert all(arm["success_rate"] is None and arm["successful_task_runs_per_hour"] is None for arm in row["cohorts"].values())


def test_rewritten_run_rejected_even_if_json_is_valid(tmp_path, monkeypatch):
    pair(tmp_path, monkeypatch)
    (tmp_path / "evaluation/flash.json").write_text("{}")
    data = project_local_research(tmp_path)
    assert data["comparisons"] == []
    assert data["warnings"]


def test_pair_cannot_bypass_qualification_validator(tmp_path, monkeypatch):
    from bench.flash_next_ab import harness

    pair(tmp_path, monkeypatch)
    def reject(*args, **kwargs):
        raise ValueError("qualification hash mismatch")
    monkeypatch.setattr(harness, "validate_qualification_receipt", reject)
    assert project_local_research(tmp_path)["comparisons"] == []


def test_pair_cannot_bypass_canonical_comparison_admission(tmp_path, monkeypatch):
    from bench.flash_next_ab import compare

    pair(tmp_path, monkeypatch)
    def reject(*args, **kwargs):
        raise compare.ComparisonError("same run id")
    monkeypatch.setattr(compare, "summarize_pair", reject)
    assert project_local_research(tmp_path)["comparisons"] == []


def test_pair_with_unknown_family_cannot_expose_free_text(tmp_path, monkeypatch):
    pair(tmp_path, monkeypatch)
    path = tmp_path / "evaluation/resident.json"
    row = json.loads(path.read_text())
    row["outcomes"][0]["family"] = "PRIVATE MODEL OUTPUT"
    ref = write(tmp_path, "evaluation/resident.json", row)
    index = json.loads((tmp_path / "evaluation/dashboard-index.json").read_text())
    index["comparisons"][0]["resident"] = ref
    write(tmp_path, "evaluation/dashboard-index.json", index)
    data = project_local_research(tmp_path)
    assert data["comparisons"] == []
    assert "PRIVATE" not in json.dumps(data)


@pytest.mark.parametrize("raw", ['{"x":1,"x":2}', '{"x":NaN}', '[]'])
def test_strict_json(tmp_path, raw):
    (tmp_path / "bad.json").write_text(raw)
    with pytest.raises(SourceError):
        Reader(tmp_path).read("bad.json")


def test_symlink_and_fifo_sources_do_not_get_followed_or_block(tmp_path):
    (tmp_path / "real.json").write_text("{}")
    (tmp_path / "link.json").symlink_to(tmp_path / "real.json")
    os.mkfifo(tmp_path / "pipe.json")
    for path in ("link.json", "pipe.json", "../real.json", "/tmp/real.json"):
        with pytest.raises(SourceError):
            Reader(tmp_path).read(path)


def test_symlink_parent_is_rejected(tmp_path):
    (tmp_path / "real").mkdir()
    (tmp_path / "real/row.json").write_text("{}")
    (tmp_path / "link").symlink_to(tmp_path / "real", target_is_directory=True)
    with pytest.raises(SourceError):
        Reader(tmp_path).read("link/row.json")


def test_failed_qualification_without_source_proof_is_withheld(tmp_path):
    qualification(tmp_path, status="failed")
    data = project_local_research(tmp_path)
    assert data["qualification_runs"] == []
    assert data["warnings"]


def test_qualification_changed_between_projection_and_validation_is_withheld(tmp_path, monkeypatch):
    from bench.flash_next_ab import harness

    qualification(tmp_path, status="failed")
    for name in ("plan.json", "launch-contract.snapshot.json"):
        write(tmp_path, f"qualification-runs/qfn-c0-fixture/{name}", {})
    monkeypatch.setattr(harness, "validate_flash_qualification_files", lambda **kwargs: {
        "qualification_receipt_sha256": "0" * 64,
    })
    assert project_local_research(tmp_path)["qualification_runs"] == []
