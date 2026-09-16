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
