"""Offline test for orchestrator/exp_orchestrator_rows.emit_task_triple."""
import json

from orchestrator.exp_orchestrator_rows import emit_task_triple

# Fields OrchestratorClient._entry emits for every row (no duration_ms).
_BASE_FIELDS = {
    "timestamp", "request_id", "parent_request_id", "stage", "task_id",
    "task_type", "status", "detail",
}


def _read_rows(path):
    with open(path) as fh:
        return [json.loads(line) for line in fh if line.strip()]


def test_emits_exactly_three_rows(tmp_path):
    log = tmp_path / "orchestrator.jsonl"
    emit_task_triple(task_id="exp003-t1", task_type="run_experiment",
                     status="ok", duration_ms=12.5, log_path=log)
    assert len(_read_rows(log)) == 3


def test_stages_and_parent_chain(tmp_path):
    log = tmp_path / "orchestrator.jsonl"
    emit_task_triple(task_id="exp003-t1", task_type="run_experiment",
                     status="ok", duration_ms=12.5, run_id="run-abc",
                     log_path=log)
    dispatch, invocation, receipt = _read_rows(log)

    assert dispatch["stage"] == "orchestrator_dispatch"
    assert invocation["stage"] == "worker_invocation"
    assert receipt["stage"] == "orchestrator_receipt"

    # dispatch parent = run_id; invocation parent = dispatch.request_id;
    # receipt parent = invocation.request_id.
    assert dispatch["parent_request_id"] == "run-abc"
    assert invocation["parent_request_id"] == dispatch["request_id"]
    assert receipt["parent_request_id"] == invocation["request_id"]

    # request_ids are distinct.
    ids = {dispatch["request_id"], invocation["request_id"],
           receipt["request_id"]}
    assert len(ids) == 3


def test_matching_task_id_and_type(tmp_path):
    log = tmp_path / "orchestrator.jsonl"
    emit_task_triple(task_id="exp003-t1", task_type="run_experiment",
                     status="ok", duration_ms=12.5, log_path=log)
    for row in _read_rows(log):
        assert row["task_id"] == "exp003-t1"
        assert row["task_type"] == "run_experiment"


def test_field_shape_matches_openclaw_runner(tmp_path):
    log = tmp_path / "orchestrator.jsonl"
    emit_task_triple(task_id="exp003-t1", task_type="run_experiment",
                     status="ok", duration_ms=12.5, log_path=log)
    dispatch, invocation, receipt = _read_rows(log)

    # dispatch + invocation: base fields exactly (no duration_ms).
    assert set(dispatch) == _BASE_FIELDS
    assert set(invocation) == _BASE_FIELDS
    # receipt carries duration_ms.
    assert set(receipt) == _BASE_FIELDS | {"duration_ms"}
    assert receipt["duration_ms"] == 12.5
    # status applies to the receipt (the terminal row).
    assert receipt["status"] == "ok"


def test_default_run_id_is_none(tmp_path):
    log = tmp_path / "orchestrator.jsonl"
    emit_task_triple(task_id="exp003-t1", task_type="run_experiment",
                     status="ok", duration_ms=1.0, log_path=log)
    dispatch = _read_rows(log)[0]
    assert dispatch["parent_request_id"] is None


def test_appends_does_not_truncate(tmp_path):
    log = tmp_path / "orchestrator.jsonl"
    emit_task_triple(task_id="a", task_type="run_experiment", status="ok",
                     duration_ms=1.0, log_path=log)
    emit_task_triple(task_id="b", task_type="run_experiment", status="ok",
                     duration_ms=1.0, log_path=log)
    assert len(_read_rows(log)) == 6


def test_never_raises_on_bad_path(tmp_path):
    # Directory where a file is expected -> open() would fail; must swallow.
    bad = tmp_path / "adir"
    bad.mkdir()
    emit_task_triple(task_id="a", task_type="run_experiment", status="ok",
                     duration_ms=1.0, log_path=bad)  # no exception
