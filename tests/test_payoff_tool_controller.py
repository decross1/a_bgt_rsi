"""Host-free checks of the registered resident payoff-tool controller."""
from __future__ import annotations

import json
import shutil
import sys
import threading
import time
from pathlib import Path

import pytest

from bench.payoff_tool_study import controller as c

ARCHIVED_RESIDENT = Path(
    "/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-15/lab-eight-hour/"
    "model-windows/qfn-ab-lab-primary-20260915-b.resident"
)


@pytest.fixture
def prepared(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(c, "OUTPUT_ROOT", tmp_path)
    path = c.prepare("qfn-followon-payoff-tool-testfixture-a")
    return path


def test_real_plan_constructor_and_controller_load_have_eighteen_slots(prepared):
    window, plan = c.load_window(prepared)
    assert window["schema"] == c.WINDOW_SCHEMA
    assert window["cohort"] == "resident"
    assert window["runtime_certificate"] == c._resident_certificate()
    assert len(plan["declared_pairs"]) == 6
    assert len(plan["declared_slots"]) == 18
    assert plan["runtime_certificate"]["endpoint_name"] == "resident_gemma"
    assert plan["source_sha256"]["bench/agentic_game_theory/calibration.py"]
    assert plan["source_sha256"]["experiments/payoff_tool_arithmetic/PREREGISTRATION.md"]


def test_plan_byte_drift_refuses_before_resident_mutation(prepared):
    plan = prepared.parent / "plan.json"
    plan.write_bytes(plan.read_bytes() + b" ")
    with pytest.raises(c.PayoffToolControllerError, match="plan raw bytes"):
        c.load_window(prepared)


def test_controller_source_drift_refuses_before_resident_mutation(prepared, monkeypatch):
    original = c._sources

    def drift():
        rows = original()
        rows["bench/payoff_tool_study/controller.py"] = {
            **rows["bench/payoff_tool_study/controller.py"], "sha256": "0" * 64,
        }
        return rows

    monkeypatch.setattr(c, "_sources", drift)
    with pytest.raises(c.PayoffToolControllerError, match="source, budget"):
        c.load_window(prepared)


def test_evaluator_gate_binds_live_resident_and_monitor_receipts(prepared, monkeypatch):
    window, _plan = c.load_window(prepared)
    output = prepared.parent
    observed = {"nara": {"ActiveState": "inactive"}, "residents_by_name": {}}
    monkeypatch.setattr(c.resident, "_read_exact_residents", lambda *_a, **_k: observed)
    state = {
        "initial": {"residents_by_name": {}}, "phase": "preflight",
        "worker_pid": 701, "worker_start_ticks": 17,
        "boot_id": "test-boot", "watchdog_sentinel_id": "test-sentinel",
    }

    class Monitor:
        phase = "evaluation"
        ops = object()
        samples = 3
        cancel_event = threading.Event()

        def check(self):
            assert not self.cancel_event.is_set()

    captured = {}

    def fake_run(**kwargs):
        captured.update(kwargs)
        return {"status": "complete", "accounted_slots": 18}

    monkeypatch.setattr(c.runner, "run", fake_run)
    result = c._executor(window, None, output, Monitor(), state, time.monotonic() + 650)
    assert result == {"status": "complete", "accounted_slots": 18}
    gate = captured["admission_gate"]
    assert gate["admitted"] is True
    assert gate["runtime_certificate"] == window["runtime_certificate"]
    assert gate["window_sha256"] == c._sha(c._raw(prepared))
    assert gate["ready_proof_sha256"] == c._sha(c._raw(output / "ready-proof.json"))
    assert gate["monitor_arm_sha256"] == c._sha(c._raw(output / "monitor-arm.json"))
    assert captured["absolute_cutoff_monotonic"] - time.monotonic() <= 600
    assert len(json.loads((output / "ready-proof.json").read_text())["resident_observation"]) == 2


def test_short_setup_budget_never_starts_runner(prepared, monkeypatch):
    window, _plan = c.load_window(prepared)
    called = []
    monkeypatch.setattr(c.runner, "run", lambda **_kwargs: called.append(True))
    with pytest.raises(c.PayoffToolControllerError, match="evaluator budget"):
        c._executor(window, None, prepared.parent, object(), {}, time.monotonic() + 599)
    assert called == []


def test_aborted_terminal_receipts_never_replay_or_admit(prepared, monkeypatch):
    output = prepared.parent
    for name in (
        "state.json", "result.json", "supervision.json",
        "supervision-start.json", "supervision-reservation.json",
        "ready-proof.json", "monitor-arm.json",
    ):
        (output / name).write_bytes(b"{}\n")
    (output / "memory.jsonl").write_bytes(b"")
    called = []
    monkeypatch.setattr(c.runner, "replay_run", lambda *_args: called.append(True))
    with pytest.raises(c.PayoffToolControllerError, match="clean terminal"):
        c.validate_completed(prepared)
    assert called == []


def _archived_terminal_fixture(prepared: Path) -> Path:
    """Reuse actual public resident monitor rows, with synthetic controller refs."""
    if not (ARCHIVED_RESIDENT / "memory.jsonl").is_file():
        pytest.skip("archived admitted resident safety metadata is unavailable")
    output = prepared.parent
    archive_state = json.loads((ARCHIVED_RESIDENT / "state.json").read_bytes())
    archive_result = json.loads((ARCHIVED_RESIDENT / "result.json").read_bytes())
    quiet = json.loads((ARCHIVED_RESIDENT / "admission-ready-proof.json").read_bytes())
    window, _plan = c.load_window(prepared)
    window_sha = c._sha(c._raw(prepared))
    plan_sha = c._sha(c._raw(output / "plan.json"))
    state = {**archive_state, "window_sha256": window_sha, "phase": "complete"}
    (output / "state.json").write_bytes(c.q.canonical_json(state) + b"\n")
    arm = {
        "schema": "payoff-tool-resident-monitor-arm/v1",
        "window_sha256": window_sha, "worker_pid": state["worker_pid"],
        "worker_start_ticks": state["worker_start_ticks"], "boot_id": state["boot_id"],
        "monitor_phase": "evaluation", "watchdog_sentinel_id": state["watchdog_sentinel_id"],
    }
    (output / "monitor-arm.json").write_bytes(c.q.canonical_json(arm) + b"\n")
    ready = {
        "schema": "payoff-tool-resident-ready-proof/v1",
        "window_sha256": window_sha, "plan_sha256": plan_sha,
        "runtime_certificate": window["runtime_certificate"],
        "resident_observation": quiet,
        "monitor_arm_sha256": c._sha(c._raw(output / "monitor-arm.json")),
    }
    (output / "ready-proof.json").write_bytes(c.q.canonical_json(ready) + b"\n")
    gate = {
        "admitted": True, "runtime_certificate": window["runtime_certificate"],
        "window_id": window["window_id"], "window_sha256": window_sha,
        "ready_proof_sha256": c._sha(c._raw(output / "ready-proof.json")),
        "monitor_arm_sha256": ready["monitor_arm_sha256"],
    }
    evaluation = output / "evaluation"
    evaluation.mkdir()
    (evaluation / "run.json").write_bytes(c.q.canonical_json({"controller_admission": gate}) + b"\n")
    result = {
        **archive_result, "window_id": window["window_id"], "window_sha256": window_sha,
        "evaluation_run_sha256": c._sha(c._raw(evaluation / "run.json")),
    }
    (output / "result.json").write_bytes(c.q.canonical_json(result) + b"\n")
    supervision = {
        "schema": c.SUPERVISION_SCHEMA, "window_sha256": window_sha,
        "returncode": 0, "interrupted": None,
        "terminated_at_cutoff": False, "emergency_restoration": None,
    }
    (output / "supervision.json").write_bytes(c.q.canonical_json(supervision) + b"\n")
    start = {
        "window_sha256": window_sha, "pid": state["worker_pid"],
        "worker_pid": state["worker_pid"], "worker_start_ticks": state["worker_start_ticks"],
        "boot_id": state["boot_id"],
        "argv": [sys.executable, "-m", "bench.payoff_tool_study.controller",
                 "--worker", "--window", str(prepared)],
    }
    (output / "supervision-start.json").write_bytes(c.q.canonical_json(start) + b"\n")
    (output / "supervision-reservation.json").write_bytes(
        c.q.canonical_json({"window_sha256": window_sha}) + b"\n",
    )
    shutil.copyfile(ARCHIVED_RESIDENT / "memory.jsonl", output / "memory.jsonl")
    return output


def test_actual_archived_resident_safety_shape_reaches_private_replay(prepared, monkeypatch):
    output = _archived_terminal_fixture(prepared)
    called = []

    def replay(*_args):
        called.append(True)
        return {
            "admitted": True, "status": "passed",
            "raw_sse_replay_passed": True, "grade_replay_passed": True,
            "run_raw_sha256": c._sha(c._raw(output / "evaluation/run.json")),
            "declared_pairs": 6, "declared_conditions": 12,
            "declared_slots": 18, "issued_calls": 18,
        }

    monkeypatch.setattr(c.runner, "replay_run", replay)
    admitted = c.validate_completed(prepared)
    assert admitted["admitted"] is True
    assert admitted["raw_refs"]["memory.jsonl"] == c._sha(c._raw(output / "memory.jsonl"))
    assert called == [True]


def test_terminal_replay_without_raw_sse_proof_is_withheld(prepared, monkeypatch):
    output = _archived_terminal_fixture(prepared)
    monkeypatch.setattr(c.runner, "replay_run", lambda *_args: {
        "admitted": True, "status": "passed", "grade_replay_passed": True,
        "raw_sse_replay_passed": False,
        "run_raw_sha256": c._sha(c._raw(output / "evaluation/run.json")),
        "declared_pairs": 6, "declared_conditions": 12,
        "declared_slots": 18, "issued_calls": 18,
    })
    with pytest.raises(c.PayoffToolControllerError, match="raw SSE"):
        c.validate_completed(prepared)


def test_archived_resident_oom_counter_drift_rejects_before_private_replay(prepared, monkeypatch):
    output = _archived_terminal_fixture(prepared)
    rows = (output / "memory.jsonl").read_bytes().splitlines()
    first = json.loads(rows[0])
    name = next(iter(first["incumbent_cgroups"]))
    first["incumbent_cgroups"][name]["memory_events_oom"] += 1
    rows[0] = c.q.canonical_json(first)
    (output / "memory.jsonl").write_bytes(b"\n".join(rows) + b"\n")
    called = []
    monkeypatch.setattr(c.runner, "replay_run", lambda *_args: called.append(True))
    with pytest.raises((c.PayoffToolControllerError, c.resident_admission.ResidentAdmissionError)):
        c.validate_completed(prepared)
    assert called == []
