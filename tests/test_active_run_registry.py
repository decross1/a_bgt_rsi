"""Offline tests for the multi-run active-run registry (D-047).

ACTIVE_RUN_PATH and RUNS_DIR are monkeypatched onto a tmp path in every
test so nothing touches the real run_state/. The module contextvar is
reset around each test. No network, MOCK_LLM-friendly.
"""
import contextvars
import json

import jsonschema
import pytest

from orchestrator import active_run


@pytest.fixture
def tmp_registry(tmp_path, monkeypatch):
    mirror = tmp_path / "run_state" / "active_run.json"
    runs_dir = tmp_path / "run_state" / "active_runs"
    monkeypatch.setattr(active_run, "ACTIVE_RUN_PATH", mirror)
    monkeypatch.setattr(active_run, "RUNS_DIR", runs_dir)
    token = active_run._active_run_stack.set(())  # isolate the ownership stack
    yield mirror, runs_dir
    active_run._active_run_stack.reset(token)


def _schema():
    return json.loads(active_run.SCHEMA_PATH.read_text())


def test_write_creates_per_run_file_and_mirror(tmp_registry):
    mirror, runs_dir = tmp_registry
    doc = active_run.write_active_run(
        "expA", "experiment", "limb A", total=5, unit="trials", model="m"
    )
    per_run = json.loads((runs_dir / "expA.json").read_text())
    assert per_run == json.loads(mirror.read_text()) == doc
    assert doc["heartbeat_at"] == doc["started_at"]
    assert active_run._current_run_id() == "expA"
    jsonschema.validate(doc, _schema())


def test_two_writers_distinct_contexts(tmp_registry):
    mirror, runs_dir = tmp_registry
    ctx_a = contextvars.copy_context()
    ctx_b = contextvars.copy_context()
    ctx_a.run(active_run.write_active_run, "runA", "experiment", "A")
    ctx_b.run(active_run.write_active_run, "runB", "loop_v0", "B")
    assert (runs_dir / "runA.json").exists()
    assert (runs_dir / "runB.json").exists()
    assert json.loads(mirror.read_text())["run_id"] == "runB"  # last writer
    ctx_a.run(active_run.clear_active_run)
    assert not (runs_dir / "runA.json").exists()
    assert (runs_dir / "runB.json").exists()  # B's registration survives
    # only-owner-clears: A's clear must not take down B's mirror
    assert json.loads(mirror.read_text())["run_id"] == "runB"
    ctx_b.run(active_run.clear_active_run)
    assert not mirror.exists()
    assert list(runs_dir.iterdir()) == []


def test_update_refreshes_heartbeat_and_merges(tmp_registry, monkeypatch):
    mirror, runs_dir = tmp_registry
    clock = {"now": "2026-06-10T00:00:00Z"}
    monkeypatch.setattr(active_run, "_utcnow_iso", lambda: clock["now"])
    active_run.write_active_run("expC", "experiment", "C", total=4, unit="steps")
    clock["now"] = "2026-06-10T00:05:00Z"
    doc = active_run.update_active_run(done=2, current_step="score", narration="mid")
    assert doc["started_at"] == "2026-06-10T00:00:00Z"
    assert doc["heartbeat_at"] == "2026-06-10T00:05:00Z"
    assert doc["progress"] == {"done": 2, "total": 4, "unit": "steps"}
    assert doc["current_step"] == "score"
    assert doc["narration"] == "mid"
    for path in (runs_dir / "expC.json", mirror):
        assert json.loads(path.read_text())["heartbeat_at"] == "2026-06-10T00:05:00Z"


def test_update_leaves_foreign_mirror_untouched(tmp_registry):
    mirror, runs_dir = tmp_registry
    ctx_a = contextvars.copy_context()
    ctx_b = contextvars.copy_context()
    ctx_a.run(active_run.write_active_run, "mine", "experiment", "M")
    ctx_b.run(active_run.write_active_run, "theirs", "loop_v0", "T")  # takes mirror
    doc = ctx_a.run(active_run.update_active_run, current_step="s2", narration="go")
    assert doc["run_id"] == "mine"
    assert json.loads((runs_dir / "mine.json").read_text())["current_step"] == "s2"
    foreign = json.loads(mirror.read_text())
    assert foreign["run_id"] == "theirs"
    assert "current_step" not in foreign


def test_legacy_clear_removes_mirror_and_twin(tmp_registry):
    mirror, runs_dir = tmp_registry
    ctx = contextvars.copy_context()
    ctx.run(active_run.write_active_run, "solo", "ad_hoc", "S")
    assert (runs_dir / "solo.json").exists() and mirror.exists()
    assert active_run._current_run_id() is None  # outer context never wrote
    active_run.clear_active_run()
    assert not mirror.exists()
    assert not (runs_dir / "solo.json").exists()
    active_run.clear_active_run()  # idempotent


def test_run_id_sanitized_for_filename(tmp_registry):
    mirror, runs_dir = tmp_registry
    doc = active_run.write_active_run("exp/iter:2026-06-10T00:00:00Z", "loop_v0", "w")
    assert doc["run_id"] == "exp/iter:2026-06-10T00:00:00Z"  # doc keeps raw id
    safe = runs_dir / "exp_iter_2026-06-10T00_00_00Z.json"
    assert safe.exists()
    active_run.clear_active_run()
    assert not safe.exists()
    assert not mirror.exists()


def test_update_recreates_missing_per_run_file(tmp_registry):
    mirror, runs_dir = tmp_registry
    ctx = contextvars.copy_context()
    ctx.run(active_run.write_active_run, "ghost", "experiment", "G")
    (runs_dir / "ghost.json").unlink()
    doc = ctx.run(active_run.update_active_run, narration="back")
    assert doc["run_id"] == "ghost"
    assert doc["kind"] == "ad_hoc"  # minimal recreate, update not dropped
    assert json.loads((runs_dir / "ghost.json").read_text())["narration"] == "back"
    jsonschema.validate(doc, _schema())


def test_nested_registration_restores_parent(tmp_registry):
    """The coordinator registers, then runs an iteration IN-PROCESS in the
    same context. The iteration's clear must pop ownership back to the
    coordinator — not wipe it and orphan the coordinator's registry file
    (the 2026-06-10 review's blocking finding B2)."""
    mirror, runs_dir = tmp_registry

    def scenario():
        active_run.write_active_run("coord_1", "coordinator", "cycle")
        active_run.write_active_run("iter-2099-01-01-001", "loop_v0", "iter")
        assert json.loads(mirror.read_text())["run_id"] == "iter-2099-01-01-001"
        active_run.clear_active_run()  # iteration finishes
        # The parent is the foreground again; its registration is intact.
        assert json.loads(mirror.read_text())["run_id"] == "coord_1"
        assert (runs_dir / "coord_1.json").exists()
        assert not (runs_dir / "iter-2099-01-01-001.json").exists()
        active_run.clear_active_run()  # coordinator finishes
        assert not mirror.exists()
        assert list(runs_dir.iterdir()) == []

    contextvars.copy_context().run(scenario)


def test_legacy_adopt_update_never_touches_registry(tmp_registry):
    """A no-context update adopts the mirror for merging but must NOT
    rewrite the foreign run's registry file (a heartbeat refresh there
    would mask a dead run as alive)."""
    mirror, runs_dir = tmp_registry
    ctx = contextvars.copy_context()
    ctx.run(active_run.write_active_run, "owned", "experiment", "O")
    before = (runs_dir / "owned.json").read_text()
    doc = active_run.update_active_run(narration="legacy touch")  # no context
    assert doc["run_id"] == "owned"  # adopted for the merge
    assert (runs_dir / "owned.json").read_text() == before  # registry untouched
    assert json.loads(mirror.read_text())["narration"] == "legacy touch"


def test_malformed_mirror_never_raises(tmp_registry):
    mirror, runs_dir = tmp_registry
    mirror.parent.mkdir(parents=True, exist_ok=True)
    mirror.write_text("{not json")
    doc = active_run.update_active_run(done=1)  # legacy path, malformed mirror
    assert doc["run_id"] == "unknown"
    assert not (runs_dir / "unknown.json").exists()  # unknown never registered
    mirror.write_text("{not json")  # malform it again
    active_run.clear_active_run()  # legacy clear tolerates malformed
    assert not mirror.exists()
