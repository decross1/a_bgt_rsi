import json
from datetime import datetime, timezone

import pytest

from backend.benchmark_program import compose_program
from bench.stable_benchmark.manifest import make_draft, publish_definition, write_document


NOW = datetime(2026, 9, 16, 5, tzinfo=timezone.utc)


def test_draft_has_no_invented_baseline_or_historical_score(tmp_path):
    result = compose_program(root=tmp_path, now=NOW)
    assert result["release"]["status"] == "draft"
    assert result["comparison"]["baseline"] is None
    assert result["comparison"]["matched_results"] == []
    assert result["progress"]["completed_units"] is None
    assert result["design"]["capability_units_per_arm"] == 18
    assert result["design"]["system_missions_per_arm"] == 3
    assert result["design"]["paired_model_call_cap"] == 58
    public = json.dumps(result)
    assert '"grader"' not in public
    assert '"prompt"' not in public
    assert '"fixtures"' not in public


def _published(root):
    root.mkdir(exist_ok=True)
    definition = publish_definition(
        make_draft(), published_at="2026-09-16T04:30:00Z",
        witness={"kind": "git_commit", "ref": "https://example.test/commit/fixture",
                 "sha256": "a" * 64},
    )
    write_document(root / "definition.published.json", definition)


def test_freeze_expiry_requires_review_without_inventing_execution(tmp_path):
    _published(tmp_path)
    result = compose_program(root=tmp_path, now=NOW)
    assert result["release"]["status"] == "frozen"
    assert result["release"]["public_witness"]["status"] == "recorded"
    assert result["comparison"]["baseline"] is None
    expired = compose_program(root=tmp_path, now=datetime(2026, 10, 14, tzinfo=timezone.utc))
    assert expired["release"]["status"] == "review_required"
    assert expired["progress"]["blockers"]
    assert expired["comparison"]["baseline"] is None


def test_invalid_published_source_cannot_fall_back_to_reassuring_draft(tmp_path):
    (tmp_path / "definition.published.json").write_text('{"score": 100}')
    result = compose_program(root=tmp_path, now=NOW)
    assert result["release"] is None
    assert result["comparison"]["status"] == "withheld_invalid_definition"
    assert result["warnings"]


def test_future_publication_is_not_a_live_freeze(tmp_path):
    _published(tmp_path)
    result = compose_program(root=tmp_path, now=datetime(2026, 9, 16, 4, tzinfo=timezone.utc))
    assert result["release"] is None
    assert result["comparison"]["status"] == "withheld_invalid_definition"


def test_redirected_published_source_cannot_be_admitted(tmp_path):
    other = tmp_path / "other"
    _published(other)
    root = tmp_path / "registered"
    root.mkdir()
    (root / "definition.published.json").symlink_to(other / "definition.published.json")
    result = compose_program(root=root, now=NOW)
    assert result["release"] is None
    assert result["comparison"]["status"] == "withheld_invalid_definition"


@pytest.mark.parametrize("runtime_cohort", ["older-comparison", None])
def test_live_window_cannot_relabel_a_different_registered_cohort(tmp_path, monkeypatch, runtime_cohort):
    from backend.benchmark_program import _attach_active_window, _empty_projection
    from backend import model_runtime_stable
    result = _empty_projection(NOW)
    result["progress"].update(comparison_id="new-comparison", status="awaiting_admission")
    monkeypatch.setattr(model_runtime_stable, "project_active_stable_runtime", lambda **kwargs: {
        "comparison_id": runtime_cohort, "run_id": "older-window", "mode": "resident_online",
        "phase": "benchmarking",
    })
    _attach_active_window(result, root=tmp_path, repo=tmp_path, now=NOW)
    assert result["progress"]["status"] == "awaiting_admission"
    assert "run_id" not in result["progress"]
    assert result["warnings"]


def test_live_window_updates_only_its_registered_cohort(tmp_path, monkeypatch):
    from backend.benchmark_program import _attach_active_window, _empty_projection
    from backend import model_runtime_stable
    result = _empty_projection(NOW)
    result["progress"].update(comparison_id="new-comparison", status="awaiting_admission")
    monkeypatch.setattr(model_runtime_stable, "project_active_stable_runtime", lambda **kwargs: {
        "comparison_id": "new-comparison", "run_id": "new-window", "mode": "resident_online",
        "phase": "benchmarking",
    })
    _attach_active_window(result, root=tmp_path, repo=tmp_path, now=NOW)
    assert result["progress"]["status"] == "running"
    assert result["progress"]["run_id"] == "new-window"
    assert result["progress"]["completed_calls"] is None


def _measurement_review(root, repo):
    from bench.stable_benchmark.manifest import load_definition
    definition = load_definition(root / "definition.published.json")
    path = repo / "docs/benchmarks/measurement_reviews" / f"{definition.raw_sha256}.json"
    path.parent.mkdir(parents=True)
    review = {
        "schema_version": "benchmark-measurement-review/v1",
        "suite_id": definition.document["suite_id"], "release": definition.document["release"],
        "definition_sha256": definition.raw_sha256, "reviewed_at": "2026-09-16T04:45:00Z",
        "status": "commissioning_only", "title": "Contract review",
        "summary": "The prompt omitted a sandbox rule.", "affected_task_ids": ["CODE-MERGE-001"],
        "interpretation": "Keep original outcomes as diagnostics.",
        "next_action": "Publish corrected prospective contracts.",
    }
    path.write_text(json.dumps(review))
    return definition, path, review


@pytest.mark.parametrize("damage", ["missing", "changed"])
def test_expected_review_cannot_disappear_or_change_to_restore_quality_claims(tmp_path, damage):
    import hashlib
    from backend.benchmark_program import _attach_measurement_review, _empty_projection
    root, repo = tmp_path / "artifacts", tmp_path / "repo"
    _published(root)
    definition, path, _ = _measurement_review(root, repo)
    expected = hashlib.sha256(path.read_bytes()).hexdigest()
    if damage == "missing":
        path.unlink()
    else:
        path.write_text(path.read_text().replace("Contract review", "Different review"))
    result = _empty_projection(NOW)
    result["comparison"].update(status="matched_results_available", matched_results=[{"delta": 1}])
    _attach_measurement_review(result, definition, repo=repo, now=NOW, expected_sha256=expected)
    assert result["measurement_review"]["status"] == "unavailable"
    assert result["measurement_review"]["comparative_quality_allowed"] is False
    assert result["comparison"]["status"] == "measurement_review_required"
    assert result["comparison"]["matched_results"] == []


def test_measurement_review_restricts_claims_without_changing_recorded_numbers(tmp_path):
    from backend.benchmark_program import _attach_measurement_review, _empty_projection
    root, repo = tmp_path / "artifacts", tmp_path / "repo"
    _published(root)
    definition, path, review = _measurement_review(root, repo)
    result = _empty_projection(NOW)
    result["comparison"].update(baseline={"results": [{"successful_units": 2, "planned_units": 4}]},
                                matched_results=[{"delta": 50}])
    _attach_measurement_review(result, definition, repo=repo, now=NOW)
    assert result["measurement_review"]["comparative_quality_allowed"] is False
    assert result["measurement_review"]["affected_task_ids"] == review["affected_task_ids"]
    assert result["comparison"]["status"] == "measurement_review_required"
    assert result["comparison"]["matched_results"] == []
    assert result["comparison"]["baseline"]["results"][0]["successful_units"] == 2


@pytest.mark.parametrize("damage", ["wrong_definition", "future", "unknown_task", "redirect", "bad_status"])
def test_invalid_existing_review_never_restores_comparative_claims(tmp_path, damage):
    from backend.benchmark_program import _attach_measurement_review, _empty_projection
    root, repo = tmp_path / "artifacts", tmp_path / "repo"
    _published(root)
    definition, path, review = _measurement_review(root, repo)
    if damage == "wrong_definition": review["definition_sha256"] = "0" * 64
    elif damage == "future": review["reviewed_at"] = "2026-09-17T00:00:00Z"
    elif damage == "unknown_task": review["affected_task_ids"] = ["NOT-A-TASK"]
    elif damage == "bad_status": review["status"] = "quality_approved"
    if damage == "redirect":
        target = tmp_path / "redirected.json"
        target.write_text(json.dumps(review))
        path.unlink()
        path.symlink_to(target)
    else:
        path.write_text(json.dumps(review))
    result = _empty_projection(NOW)
    _attach_measurement_review(result, definition, repo=repo, now=NOW)
    assert result["measurement_review"]["status"] == "unavailable"
    assert result["measurement_review"]["comparative_quality_allowed"] is False
    assert result["comparison"]["status"] == "measurement_review_required"
