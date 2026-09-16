"""Receipt projection checks; fixtures below are synthetic, never lab results."""
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

from backend.benchmark_program import compose_program
from backend.benchmark_history import matched_results
from bench.stable_benchmark.manifest import make_draft

NOW = datetime(2026, 9, 17, tzinfo=timezone.utc)


def _fixture(tmp_path, monkeypatch):
    from backend import model_runtime_stable
    # Runtime process/monitor verification has its own dedicated tests; this
    # fixture supplies a terminal public receipt chain without a live process.
    monkeypatch.setattr(model_runtime_stable, "project_active_stable_runtime", lambda **_: None)
    # Exercise the same complete synthetic controller/replay chain as the
    # verifier tests, rather than a hand-written self-admitted score fixture.
    path = Path(__file__).resolve().parents[3] / "tests/test_stable_benchmark_receipt_verification.py"
    spec = importlib.util.spec_from_file_location("stable_receipt_test_fixture", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    definition, registration, lifecycle = module._registration_fixture(tmp_path, monkeypatch)
    return definition.path.parent, tmp_path / "repo", registration, lifecycle


def _view(root, repo):
    return compose_program(root=root, repo=repo, now=NOW)


def test_bound_reference_is_visible_without_raw_payloads_or_omnibus(tmp_path, monkeypatch):
    root, repo, _, _ = _fixture(tmp_path, monkeypatch)
    result = _view(root, repo)
    assert result["comparison"]["status"] == "baseline_available"
    baseline = result["comparison"]["baseline"]
    assert baseline["week"] == "2026-W38"
    assert baseline["role"] == "reference"
    assert baseline["model_calls"] == 21
    assert all(row["value"] == 0 for row in baseline["results"])
    assert "outcomes" not in baseline and "score" not in baseline
    assert result["comparison"]["matched_results"] == []
    candidate = next(row for row in result["comparison"]["history"] if row["role"] == "candidate")
    assert candidate["observed_terminal_status"] == "unissued"
    assert candidate["model_calls"] == 0 and candidate["results"] == []


def test_self_reported_admission_without_registration_is_not_a_score(tmp_path, monkeypatch):
    root, repo, registration, _ = _fixture(tmp_path, monkeypatch)
    registration.unlink()
    result = _view(root, repo)
    assert result["comparison"]["baseline"] is None
    assert all(row["admission_status"] == "withheld_unregistered" and not row["results"]
               for row in result["comparison"]["history"])


def test_tampered_external_gate_receipt_cannot_inherit_admission(tmp_path, monkeypatch):
    root, repo, _, lifecycle = _fixture(tmp_path, monkeypatch)
    with (lifecycle / "endpoint-bindings.json").open("ab") as stream:
        stream.write(b" ")
    result = _view(root, repo)
    assert result["comparison"]["baseline"] is None
    reference = next(row for row in result["comparison"]["history"] if row["role"] == "reference")
    assert reference["admission_status"] == "withheld_invalid_artifacts"


def test_registered_pending_attempt_remains_visible_before_run_directory_exists(tmp_path, monkeypatch):
    root, repo, registration, _ = _fixture(tmp_path, monkeypatch)
    document = json.loads(registration.read_text())
    document["comparison_id"] = "later-pair"
    document["registered_at"] = "2026-09-16T07:00:00Z"
    for arm in document["arms"]:
        arm["run_receipt_directory"] = str(root / "runs/later-pair" / arm["arm_id"])
        arm["manifest"]["path"] = str(root / "manifests" / f"later-pair.{arm['arm_id']}.json")
    registration.with_name("later-pair.json").write_text(json.dumps(document))
    result = _view(root, repo)
    assert result["comparison"]["baseline"] is not None
    assert result["progress"]["status"] == "awaiting_admission"
    assert result["progress"]["completed_units"] == 0
    assert result["progress"]["blockers"]
    pending = [row for row in result["comparison"]["history"] if row["comparison_id"] == "later-pair"]
    assert len(pending) == 2
    assert all(row["admission_status"] == "awaiting_artifacts" for row in pending)


def test_registered_run_path_cannot_redirect_reader(tmp_path, monkeypatch):
    root, repo, registration, _ = _fixture(tmp_path, monkeypatch)
    document = json.loads(registration.read_text())
    document["arms"][0]["run_receipt_directory"] = str(tmp_path / "unrelated")
    registration.write_text(json.dumps(document))
    result = _view(root, repo)
    assert result["comparison"]["status"] == "withheld_invalid_history"
    assert result["comparison"]["baseline"] is None


def _paired_rows(*, same_cohort=True):
    tasks = {task["id"]: task for task in make_draft()["tasks"]}
    rows = []
    for role, passed, started in (("candidate", True, "2026-09-16T04:00:00Z"),
                                  ("reference", False, "2026-09-16T06:00:00Z")):
        summary = {"role": role, "comparison_id": "same" if same_cohort or role == "reference" else "other",
                   "arm_id": role, "label": role, "started_at": started, "finished_at": "2026-09-16T06:02:00Z"}
        rows.append((summary, [{"task_id": task, "score_credit": passed} for task in tasks]))
    return rows, tasks


def test_changed_cohort_cannot_become_a_paired_comparison():
    rows, tasks = _paired_rows(same_cohort=False)
    assert matched_results(rows, tasks) == []


def test_pair_order_uses_registered_roles_and_preserves_construct_denominators():
    rows, tasks = _paired_rows()
    pairs = matched_results(rows, tasks)
    assert len(pairs) == 8
    assert all(row["baseline_arm"] == "reference" and row["candidate_arm"] == "candidate" for row in pairs)
    assert all(row["delta"] == 100 and row["n_pairs"] <= 4 for row in pairs)
    assert all(row["uncertainty"]["lower"] is None for row in pairs)
