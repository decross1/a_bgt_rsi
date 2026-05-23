"""§11.3 Week-2 unlock prerequisites — all five sections.

See ui_plan.md §11.3 and backend/unlock.py.
"""
import json

from backend.unlock import (
    compute_unlock_status,
    read_hard_gate_pending,
    read_soft_gate_queue,
    verify_run_log_integrity,
)


def _write_jsonl(path, records):
    path.write_text("".join(json.dumps(r) + "\n" for r in records),
                    encoding="utf-8")


def _ok_entry(task_id="t1", day="day_1", ts="2026-05-20T00:00:00Z"):
    return {"timestamp": ts, "day_id": day, "task_id": task_id,
            "status": "passed", "observable_actual": "x",
            "observable_expected": "x", "duration_ms": 0}


# ── prerequisite 1: run-log integrity ─────────────────────────────────

def test_run_log_integrity_clean_file(tmp_path):
    path = tmp_path / "run.jsonl"
    _write_jsonl(path, [_ok_entry("a"), _ok_entry("b"), _ok_entry("c")])
    result = verify_run_log_integrity(path)
    assert result["available"] is True
    assert result["ok"] is True
    assert result["total_lines"] == 3
    assert result["malformed_lines"] == []


def test_run_log_integrity_flags_missing_field(tmp_path):
    path = tmp_path / "run.jsonl"
    broken = _ok_entry("b")
    broken.pop("duration_ms")
    _write_jsonl(path, [_ok_entry("a"), broken, _ok_entry("c")])
    result = verify_run_log_integrity(path)
    assert result["ok"] is False
    assert result["malformed_lines"] == [2]


def test_run_log_integrity_flags_unparseable_line(tmp_path):
    path = tmp_path / "run.jsonl"
    path.write_text(
        json.dumps(_ok_entry("a")) + "\n"
        + "{not json\n"
        + json.dumps(_ok_entry("c")) + "\n",
        encoding="utf-8")
    result = verify_run_log_integrity(path)
    assert result["ok"] is False
    assert result["malformed_lines"] == [2]


def test_run_log_integrity_rolling_window(tmp_path):
    path = tmp_path / "run.jsonl"
    _write_jsonl(path, [
        _ok_entry("old", ts="2026-05-01T00:00:00Z"),
        _ok_entry("recent", ts="2026-05-22T00:00:00Z"),
    ])
    result = verify_run_log_integrity(
        path, rolling_window_days=7, now_iso="2026-05-23T00:00:00Z")
    assert result["total_lines"] == 2
    assert result["rolling_count"] == 1


def test_run_log_integrity_absent_file(tmp_path):
    result = verify_run_log_integrity(tmp_path / "absent.jsonl")
    assert result["available"] is False
    assert result["ok"] is None


# ── prerequisite 2: soft-gate attestation queue ───────────────────────

def test_soft_gate_queue_returns_pending_with_rollback_command(tmp_path):
    path = tmp_path / "attestations.jsonl"
    _write_jsonl(path, [
        {"_schema_comment": "header — should be skipped"},
        {"kind": "request", "task_id": "t1", "agent_id": "claude-track-c",
         "summary": "claim X", "ts": "2026-05-22T10:00:00Z",
         "expected_observable": "e", "observed_actual": "a", "sla_hours": 48},
        {"kind": "request", "task_id": "t2", "agent_id": "claude-track-b",
         "summary": "claim Y", "ts": "2026-05-22T11:00:00Z",
         "expected_observable": "e", "observed_actual": "a", "sla_hours": 48},
        {"kind": "approved", "task_id": "t1"},
    ])
    result = read_soft_gate_queue(path)
    assert result["available"] is True
    assert [p["task_id"] for p in result["pending"]] == ["t2"]
    assert result["pending"][0]["rollback_command"].endswith("--task-id t2")


def test_soft_gate_queue_absent_file_degrades_gracefully(tmp_path):
    result = read_soft_gate_queue(tmp_path / "absent.jsonl")
    assert result == {"available": False, "pending": []}


def test_soft_gate_queue_no_objection_closes_request(tmp_path):
    path = tmp_path / "attestations.jsonl"
    _write_jsonl(path, [
        {"kind": "request", "task_id": "t3", "ts": "2026-05-21T09:00:00Z"},
        {"kind": "no_objection", "task_id": "t3"},
    ])
    assert read_soft_gate_queue(path)["pending"] == []


# ── prerequisite 3: hard-gate pending list ────────────────────────────

def test_hard_gate_pending_string_entries():
    state = {"human_gates_pending": ["day7_publication_review_gate"]}
    result = read_hard_gate_pending(state)
    assert result["pending"][0]["task_id"] == "day7_publication_review_gate"
    assert result["pending"][0]["attest_command"].endswith(
        "--task-id day7_publication_review_gate")


def test_hard_gate_pending_dict_entries_preserved():
    state = {"human_gates_pending": [
        {"task_id": "gate_x", "reason": "novel-finding eval pending"}
    ]}
    result = read_hard_gate_pending(state)
    assert result["pending"][0]["reason"] == "novel-finding eval pending"
    assert result["pending"][0]["attest_command"].endswith("--task-id gate_x")


def test_hard_gate_pending_empty():
    assert read_hard_gate_pending({})["pending"] == []
    assert read_hard_gate_pending({"human_gates_pending": []})["pending"] == []


# ── prerequisites 4 + 5 + integration: compute_unlock_status ──────────

def test_compute_unlock_status_consolidates_all_five_sections(tmp_path):
    state_file = tmp_path / "state.json"
    run_log = tmp_path / "run.jsonl"
    attestations = tmp_path / "attestations.jsonl"
    state_file.write_text(json.dumps({
        "current_day": "day_7",
        "human_gates_pending": ["day7_publication_review_gate"],
        "metric_log": {"day1_tokens_per_sec": 32.03,
                       "day6_orchestrator_5_of_5": 5},
        "fallbacks_taken": {"day5_ml_intern": "direct_api"},
    }), encoding="utf-8")
    _write_jsonl(run_log, [_ok_entry("a"), _ok_entry("b")])
    _write_jsonl(attestations, [
        {"_schema_comment": "header"},
        {"kind": "request", "task_id": "pending_one",
         "ts": "2026-05-22T10:00:00Z"},
    ])

    result = compute_unlock_status(state_file, run_log, attestations,
                                   now_iso="2026-05-23T00:00:00Z")
    assert result["milestone"] == "ui_v1_week2_unlock"
    assert result["current_day"] == "day_7"
    # 1. run-log integrity
    assert result["run_log_integrity"]["ok"] is True
    # 2. soft-gate queue
    assert [p["task_id"] for p in result["soft_gate_queue"]["pending"]] \
        == ["pending_one"]
    # 3. hard-gate pending
    assert result["hard_gates_pending"]["pending"][0]["task_id"] \
        == "day7_publication_review_gate"
    # 4. metric_log
    assert result["metric_log"]["day1_tokens_per_sec"] == 32.03
    assert result["metric_log"]["day6_orchestrator_5_of_5"] == 5
    # 5. fallbacks_taken
    assert result["fallbacks_taken"]["day5_ml_intern"] == "direct_api"


def test_compute_unlock_status_degrades_when_files_absent(tmp_path):
    # All inputs missing — endpoint still returns a usable shape.
    result = compute_unlock_status(
        tmp_path / "no_state.json",
        tmp_path / "no_run.jsonl",
        tmp_path / "no_attest.jsonl",
        now_iso="2026-05-23T00:00:00Z")
    assert result["run_log_integrity"]["available"] is False
    assert result["soft_gate_queue"]["available"] is False
    assert result["hard_gates_pending"] == {"available": True, "pending": []}
    assert result["metric_log"] == {}
    assert result["fallbacks_taken"] == {}
