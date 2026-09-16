"""Tests for the read-only stable canary section in Sunday reports."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from bench.stable_benchmark.manifest import make_draft, publish_definition, write_document
from orchestrator import weekly_upgrade as wu
from orchestrator.weekly_stable_benchmark_report import (
    build_weekly_benchmark_snapshot,
    inspect_weekly_review_context,
    write_sunday_benchmark_report,
)
from ui.backend import benchmark_program

NOW = datetime(2026, 9, 20, 5, 30, tzinfo=timezone.utc)
SHA = "a" * 64
REAL_W38 = Path("/home/decross1/projects/a_bgt_rsi_weekly_upgrade_runs/2026-W38")


def _repo_markers(root: Path) -> None:
    release = root / "docs/benchmarks/releases/stable-lab-v1/definition.published.json"
    release.parent.mkdir(parents=True)
    release.write_text("{}", encoding="utf-8")
    registration = root / "docs/benchmarks/registrations/comparison-a.json"
    registration.parent.mkdir(parents=True)
    registration.write_text("{}", encoding="utf-8")


def _projection(*, status: str = "frozen") -> dict:
    return {
        "schema_version": "benchmark-program/v1",
        "release": {
            "suite_id": "a-bgt-rsi-stable-1.0.0", "version": "1.0.0",
            "status": status, "published_at": "2026-09-16T05:22:36Z",
            "expires_at": "2026-10-14T00:00:00Z", "definition_sha256": SHA,
        },
        "measurement_review": {
            "status": "commissioning_only",
            "title": "Commissioning run",
            "summary": "Four task contracts require a prospective correction.",
            "affected_task_ids": ["EVID-SUPPORT-001", "CODE-MERGE-001"],
            "comparative_quality_allowed": False,
            "source_path": "docs/benchmarks/measurement_reviews/review.json",
            "source_sha256": "b" * 64,
            "interpretation": "must not leak into the weekly report",
        },
        "progress": {
            "comparison_id": "comparison-a", "status": "partial",
            "completed_units": 21, "total_units": 42,
            "completed_calls": 27, "total_calls": 58,
        },
        "comparison": {
            "status": "baseline_available",
            "history": [
                {
                    "comparison_id": "comparison-a", "arm_id": "candidate-unissued",
                    "label": "Candidate unissued", "role": "candidate",
                    "admission_status": "not_evaluated", "observed_terminal_status": "unissued",
                    "replay_status": "not_run", "run_id": "unissued-run",
                    "registered_at": "2026-09-16T05:22:36Z", "started_at": None,
                    "finished_at": "2026-09-16T05:30:57Z", "completed_units": None,
                    "model_calls": 0, "wall_seconds": None, "results": [],
                    "policy": {"must_not": "leak"},
                },
                {
                    "comparison_id": "comparison-a", "arm_id": "resident",
                    "label": "Resident stack", "role": "reference",
                    "admission_status": "admitted", "observed_terminal_status": "complete",
                    "replay_status": "verified", "run_id": "resident-run",
                    "registered_at": "2026-09-16T05:22:36Z",
                    "started_at": "2026-09-16T05:44:36Z",
                    "finished_at": "2026-09-16T05:46:56Z", "completed_units": 21,
                    "model_calls": 27, "wall_seconds": 139.95,
                    "results": [{
                        "construct": "functional_code_repair",
                        "domain": "functional_code_repair", "panel": "model_capability",
                        "successful_units": 2, "planned_units": 4,
                        "metric": "objective_success", "unit": "percent", "value": 50.0,
                    }],
                    "policy": {"must_not": "leak"},
                },
            ],
            "matched_results": [],
        },
        "warnings": [],
    }


def _validate_snapshot(value: dict) -> None:
    root = json.loads(wu.SCHEMA_PATH.read_text(encoding="utf-8"))
    schema = {
        "$schema": root["$schema"], "$defs": root["$defs"],
        "$ref": "#/$defs/stable_benchmark_snapshot",
    }
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)


def test_multiple_weeks_of_comparisons_do_not_overflow_current_week_summary(tmp_path):
    _repo_markers(tmp_path)
    projection = _projection()
    projection["measurement_review"] = None
    row = {
        "domain": "science_evidence", "mechanism": "none", "panel": "model_capability",
        "baseline_arm": "resident", "candidate_arm": "candidate",
        "baseline_value": 50, "candidate_value": 75, "delta": 25,
        "metric": "objective_success", "unit": "percent", "n_pairs": 4,
        "discordant_counts": {"baseline_only": 0, "candidate_only": 1}, "status": "comparable",
    }
    projection["comparison"]["matched_results"] = [
        {**row, "comparison_id": comparison}
        for comparison in ("older-week-a", "older-week-b", "comparison-a")
        for _ in range(8)
    ]
    result = build_weekly_benchmark_snapshot(
        repo=tmp_path, observed_at=NOW, projection_loader=lambda **_: projection,
    )
    assert result["status"] == "available"
    assert len(result["current_cohort"]["matched_results"]) == 8
    _validate_snapshot(result)


def _validate_sunday_report(value: dict) -> None:
    root = json.loads(wu.SCHEMA_PATH.read_text(encoding="utf-8"))
    schema = {
        "$schema": root["$schema"], "$defs": root["$defs"],
        "$ref": "#/$defs/stable_benchmark_sunday_report",
    }
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)


def _terminal_review(output: Path, *, week_id: str = "2026-W38") -> Path:
    week_dir = output / week_id
    review_dir = week_dir / "review"
    review_dir.mkdir(parents=True)
    snapshot = {"week_id": week_id, "week_key_sha256": "c" * 64}
    manifest = {
        "schema_version": "weekly-upgrade-run-v1",
        "run_id": f"{week_id}-{'c' * 12}", "week_id": week_id,
        "snapshot_sha256": wu._sha(snapshot), "snapshot": snapshot,
        "source_packet_sha256": "d" * 64,
        "providers": [
            {"ordinal": 1, "vendor": "codex", "role": "upgrade_proposer"},
            {"ordinal": 2, "vendor": "claude", "role": "upgrade_adversary"},
        ],
        "budget": {
            "frontier_calls": 2, "total_deadline_s": 600,
            "max_gpu_minutes": 120, "call_timeout_s": 300,
            "started_at": "2026-09-14T05:30:00Z",
            "deadline_at": "2026-09-14T05:40:00Z",
        },
    }
    wu._validate_manifest(manifest)
    report = wu._make_report(
        manifest, status="NO_CHANGE", reason="No inert trial survived review.",
    )
    (review_dir / "run_manifest.json").write_bytes(wu._canonical(manifest) + b"\n")
    (review_dir / "weekly_report.json").write_bytes(wu._canonical(report) + b"\n")
    plan = {
        "schema_version": "weekly-upgrade-cycle-plan/v1", "week_id": week_id,
        "repo_root": "/frozen/original/repo", "repo_head": "e" * 40,
    }
    (week_dir / "cycle_plan.json").write_bytes(wu._canonical(plan) + b"\n")
    cycle_report = {
        "schema_version": "weekly-upgrade-cycle/v1", "week_id": week_id,
        "cycle_plan_sha256": wu._sha(plan), "status": "REVIEW_COMPLETE",
        "review": {
            "status": report["status"], "run_id": report["run_id"],
            "snapshot_sha256": report["snapshot_sha256"],
            "proposal_sha256": None, "frontier_calls_used": 0,
            "experiment_card_sha256": None,
        },
        "trial": None, "production_change_authorized": False,
        "promotion_authorized": False,
    }
    (week_dir / "cycle_report.json").write_bytes(wu._canonical(cycle_report) + b"\n")
    return week_dir


def test_weekly_snapshot_whitelists_receipt_evidence_and_preregistration(tmp_path):
    repo = tmp_path / "repo"
    _repo_markers(repo)
    observed = {}

    def load(**kwargs):
        observed.update(kwargs)
        return _projection()

    result = build_weekly_benchmark_snapshot(
        repo=repo, program_root=tmp_path / "program", observed_at=NOW,
        projection_loader=load,
    )

    _validate_snapshot(result)
    assert observed["observed_at"] == NOW
    assert result["release"]["definition_sha256"] == SHA
    assert result["current_cohort"]["receipt_admitted_arms"] == 1
    assert result["current_cohort"]["unissued_arms"] == 1
    assert result["current_cohort"]["paired_comparison_available"] is False
    reference = next(row for row in result["current_cohort"]["arms"]
                     if row["role"] == "reference")
    assert reference["result_interpretation"] == "receipt_verified_grader_output_only"
    assert result["scope"]["measurement_validity"] == "commissioning_only"
    assert result["scope"]["promotion_authorized"] is False
    assert result["measurement_review"] == {
        "status": "commissioning_only",
        "title": "Commissioning run",
        "summary": "Four task contracts require a prospective correction.",
        "affected_task_ids": ["EVID-SUPPORT-001", "CODE-MERGE-001"],
        "comparative_quality_allowed": False,
        "source_sha256": "b" * 64,
    }
    recipe = result["next_run_preregistration"]
    assert recipe["automatic_execution"] is False
    assert recipe["automatic_scheduling"] is False
    assert recipe["paid_api_calls"] == 0
    assert recipe["eligibility"] == "corrected_release_required"
    rendered = json.dumps(result)
    assert "must_not" not in rendered
    assert "source_path" not in rendered
    assert '"policy"' not in rendered
    assert "omnibus" in rendered


def test_release_expiry_changes_recipe_without_creating_a_run(tmp_path):
    repo = tmp_path / "repo"
    _repo_markers(repo)
    result = build_weekly_benchmark_snapshot(
        repo=repo, program_root=tmp_path / "program", observed_at=NOW,
        projection_loader=lambda **_: _projection(status="review_required"),
    )
    _validate_snapshot(result)
    recipe = result["next_run_preregistration"]
    assert recipe["eligibility"] == "explicit_release_review_required"
    assert recipe["required_sequence"][0].startswith("Record an explicit")
    assert recipe["automatic_execution"] is False


def test_absent_measurement_review_withholds_next_run_claims(tmp_path):
    repo = tmp_path / "repo"
    _repo_markers(repo)
    projection = _projection()
    projection["measurement_review"] = None
    result = build_weekly_benchmark_snapshot(
        repo=repo, program_root=tmp_path / "program", observed_at=NOW,
        projection_loader=lambda **_: projection,
    )
    _validate_snapshot(result)
    assert result["measurement_review"] is None
    assert result["scope"]["measurement_validity"] == "unreviewed_claims_withheld"
    assert result["next_run_preregistration"]["eligibility"] == "manual_preregistration_required"


def test_unavailable_measurement_review_blocks_comparative_recipe(tmp_path):
    repo = tmp_path / "repo"
    _repo_markers(repo)
    projection = _projection()
    projection["measurement_review"] = {
        "status": "unavailable", "title": "Measurement review unavailable",
        "summary": "The checked-in review could not be verified.",
        "affected_task_ids": [], "comparative_quality_allowed": False,
        "source_path": "docs/benchmarks/measurement_reviews/review.json",
        "source_sha256": None,
    }
    result = build_weekly_benchmark_snapshot(
        repo=repo, program_root=tmp_path / "program", observed_at=NOW,
        projection_loader=lambda **_: projection,
    )
    _validate_snapshot(result)
    assert result["scope"]["measurement_validity"] == "review_unavailable_claims_withheld"
    assert result["next_run_preregistration"]["eligibility"] == "measurement_review_required"
    assert result["measurement_review"]["comparative_quality_allowed"] is False


def test_missing_repository_witness_is_reported_without_loading_projection(tmp_path):
    calls = []
    result = build_weekly_benchmark_snapshot(
        repo=tmp_path, program_root=tmp_path / "program", observed_at=NOW,
        projection_loader=lambda **kwargs: calls.append(kwargs),
    )
    _validate_snapshot(result)
    assert result["status"] == "unavailable"
    assert result["release"] is None
    assert result["current_cohort"] is None
    assert calls == []


def test_malformed_or_nonfinite_projection_fails_closed(tmp_path):
    repo = tmp_path / "repo"
    _repo_markers(repo)
    projection = _projection()
    projection["comparison"]["history"][1]["wall_seconds"] = float("nan")
    result = build_weekly_benchmark_snapshot(
        repo=repo, program_root=tmp_path / "program", observed_at=NOW,
        projection_loader=lambda **_: projection,
    )
    _validate_snapshot(result)
    assert result["status"] == "unavailable"
    assert result["current_cohort"] is None


def test_compose_program_weekly_mode_skips_active_runtime_projection(tmp_path, monkeypatch):
    definition = publish_definition(
        make_draft(), published_at="2026-09-16T05:22:36Z",
        witness={"kind": "git_commit", "ref": "https://example.test/commit/a", "sha256": SHA},
    )
    tmp_path.mkdir(exist_ok=True)
    write_document(tmp_path / "definition.published.json", definition)

    def fail_runtime(*args, **kwargs):
        raise AssertionError("weekly snapshot must not inspect active runtime")

    monkeypatch.setattr(benchmark_program, "_attach_active_window", fail_runtime)
    result = benchmark_program.compose_program(
        root=tmp_path, repo=tmp_path, now=NOW, include_runtime=False,
    )
    assert result["release"]["status"] == "frozen"


def test_sunday_report_refreshes_without_mutating_terminal_week(tmp_path):
    repo = tmp_path / "repo"
    _repo_markers(repo)
    output = tmp_path / "output"
    week_dir = _terminal_review(output)
    before = {
        path.relative_to(week_dir): path.read_bytes()
        for path in week_dir.rglob("*.json")
    }
    path, report = write_sunday_benchmark_report(
        repo=repo, output_root=output, observed_at=NOW,
        program_root=tmp_path / "program",
        projection_loader=lambda **_: _projection(),
    )
    _validate_sunday_report(report)
    assert path == week_dir / "stable_benchmark_snapshot.json"
    assert report["weekly_review_context"]["status"] == "terminal_immutable_review"
    assert report["weekly_review_context"]["frontier_calls_repeated"] is False
    assert report["stable_benchmark"]["measurement_review"]["status"] == "commissioning_only"
    after = {
        path.relative_to(week_dir): path.read_bytes()
        for path in week_dir.rglob("*.json")
        if path.name != "stable_benchmark_snapshot.json"
    }
    assert after == before
    assert json.loads(path.read_text()) == report


def test_corrupt_terminal_context_gives_bounded_original_context_recovery(tmp_path):
    week_dir = _terminal_review(tmp_path / "output")
    cycle = json.loads((week_dir / "cycle_report.json").read_text())
    cycle["cycle_plan_sha256"] = "0" * 64
    (week_dir / "cycle_report.json").write_text(json.dumps(cycle))
    context = inspect_weekly_review_context(week_dir, week_id="2026-W38")
    assert context["status"] == "incomplete_original_context_required"
    assert context["plan_repo_root"] == "/frozen/original/repo"
    assert context["plan_repo_head"] == "e" * 40
    assert "Do not retry" in context["recovery"]


@pytest.mark.canonical_corpus(
    REAL_W38 / "cycle_plan.json",
    REAL_W38 / "cycle_report.json",
    REAL_W38 / "review/run_manifest.json",
    REAL_W38 / "review/weekly_report.json",
)
def test_operator_w38_terminal_review_is_verified_without_replay():
    context = inspect_weekly_review_context(REAL_W38, week_id="2026-W38")
    assert context == {
        "status": "terminal_immutable_review",
        "week_id": "2026-W38",
        "cycle_status": "REVIEW_COMPLETE",
        "review_status": "REVISION_REQUIRED",
        "reviewed_at": "2026-09-14T08:57:53.785212Z",
        "plan_repo_root": "/home/decross1/projects/a_bgt_rsi_worktrees/weekly-upgrade-cycle-measurement-20260914",
        "plan_repo_head": "0e498f9e2a9165fd2a7d55110629fd3a4f868b54",
        "cycle_plan_sha256": "fef1a04c18dbb7c8c0f0c5a8d1fd540466f718338a577bb17362ec653f47eb08",
        "weekly_report_sha256": "e80a39c7ea088156cd5e3ddd42d9a9b877962e48b3e4cac8e8be53669b4b26a0",
        "reason": (
            "The provider review is terminal under its original repository context; "
            "the Sunday owner must not repeat its calls."
        ),
        "recovery": None,
        "frontier_calls_repeated": False,
    }


def test_weekly_report_embeds_the_frozen_summary(tmp_path, monkeypatch):
    from tests.test_weekly_upgrade import FakeFrontier, _repo, _run

    summary = build_weekly_benchmark_snapshot(
        repo=(repo := tmp_path / "markers"), program_root=tmp_path / "program",
        observed_at=NOW,
    )
    # The fixture above intentionally has no source-controlled release, yielding
    # a valid unavailable summary; this test covers report binding, not history.
    monkeypatch.setattr(wu, "build_weekly_benchmark_snapshot", lambda **_: summary)
    report = _run(_repo(tmp_path), tmp_path / "out", FakeFrontier())
    assert report["stable_benchmark"] == summary
    wu._validate("report", report)
    prompt = FakeFrontier()
    _run(_repo(tmp_path / "second"), tmp_path / "out-second", prompt)
    assert "read-only canary report" in prompt.calls[0]["prompt"]
