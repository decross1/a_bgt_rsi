"""Offline tests for the generalized active-run state helper.

The module's ACTIVE_RUN_PATH constant is monkeypatched onto a tmp path so
nothing touches the real run_state/. No network, MOCK_LLM-friendly.
"""
import json

import jsonschema
import pytest

from orchestrator import active_run


@pytest.fixture
def tmp_active_run(tmp_path, monkeypatch):
    p = tmp_path / "run_state" / "active_run.json"
    monkeypatch.setattr(active_run, "ACTIVE_RUN_PATH", p)
    return p


def _schema():
    return json.loads(active_run.SCHEMA_PATH.read_text())


def test_write_then_read_back(tmp_active_run):
    active_run.write_active_run(
        "exp003", "experiment", "Vickrey rediscovery", total=50, unit="trials", model="gemma-4-26b-a4b"
    )
    doc = json.loads(tmp_active_run.read_text())
    assert doc["run_id"] == "exp003"
    assert doc["kind"] == "experiment"
    assert doc["label"] == "Vickrey rediscovery"
    assert doc["model"] == "gemma-4-26b-a4b"
    assert doc["progress"] == {"done": 0, "total": 50, "unit": "trials"}
    assert "started_at" in doc
    jsonschema.validate(doc, _schema())


def test_write_no_progress_when_total_and_unit_absent(tmp_active_run):
    active_run.write_active_run("r1", "ad_hoc", "quick run")
    doc = json.loads(tmp_active_run.read_text())
    assert "progress" not in doc
    assert "model" not in doc


def test_bad_kind_rejected(tmp_active_run):
    with pytest.raises(ValueError):
        active_run.write_active_run("r1", "not_a_kind", "label")
    assert not tmp_active_run.exists()


def test_update_merges_done_and_step_and_recomputes_progress(tmp_active_run):
    active_run.write_active_run("exp003", "experiment", "Vickrey", total=50, unit="trials")
    active_run.update_active_run(done=12, current_step="scoring", narration="halfway")
    doc = json.loads(tmp_active_run.read_text())
    assert doc["progress"] == {"done": 12, "total": 50, "unit": "trials"}
    assert doc["current_step"] == "scoring"
    assert doc["narration"] == "halfway"
    # untouched fields survive
    assert doc["run_id"] == "exp003"
    jsonschema.validate(doc, _schema())


def test_update_n_err_and_step_started_at(tmp_active_run):
    active_run.write_active_run("r1", "loop_v0", "iter-2026-06-06-001")
    active_run.update_active_run(n_err=3, step_started_at="2026-06-06T00:00:00Z")
    doc = json.loads(tmp_active_run.read_text())
    assert doc["n_err"] == 3
    assert doc["step_started_at"] == "2026-06-06T00:00:00Z"


def test_update_missing_file_noop_creates(tmp_active_run):
    assert not tmp_active_run.exists()
    doc = active_run.update_active_run(done=1, current_step="x")
    assert tmp_active_run.exists()
    assert doc["kind"] == "ad_hoc"
    assert doc["current_step"] == "x"
    assert doc["progress"]["done"] == 1
    jsonschema.validate(doc, _schema())


def test_clear_removes_file_idempotent(tmp_active_run):
    active_run.write_active_run("r1", "experiment", "x")
    assert tmp_active_run.exists()
    active_run.clear_active_run()
    assert not tmp_active_run.exists()
    # idempotent: second clear on absent file does not raise
    active_run.clear_active_run()
    assert not tmp_active_run.exists()


def test_write_is_atomic_no_tmp_left_behind(tmp_active_run):
    active_run.write_active_run("r1", "autoresearch", "sweep", total=10, unit="runs")
    active_run.update_active_run(done=5)
    tmp = tmp_active_run.with_suffix(tmp_active_run.suffix + ".tmp")
    assert not tmp.exists()
    assert tmp_active_run.exists()


def test_full_lifecycle_schema_valid(tmp_active_run):
    schema = _schema()
    active_run.write_active_run("exp004", "experiment", "lifecycle", total=3, unit="trials", model="m")
    jsonschema.validate(json.loads(tmp_active_run.read_text()), schema)
    active_run.update_active_run(done=1, current_step="step1", narration="go", n_err=0)
    jsonschema.validate(json.loads(tmp_active_run.read_text()), schema)
    active_run.clear_active_run()
    assert not tmp_active_run.exists()
