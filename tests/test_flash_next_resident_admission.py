"""CPU-only off-tree contract checks; no containers or endpoints are touched."""
from __future__ import annotations

import hashlib
import importlib
import json
import time
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest


def draft_module():
    return importlib.import_module("bench.flash_next_ab.resident_admission")


def write_json(path: Path, row: dict) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = (json.dumps(row, sort_keys=True) + "\n").encode()
    path.write_bytes(content)
    return content


def fixture(tmp_path, monkeypatch):
    gate = draft_module()
    pair = "qfn-ab-local-fixture"
    output = tmp_path / (pair + ".resident")
    output.mkdir()
    journal = tmp_path / "usage.jsonl"
    monkeypatch.setattr(gate, "RESEARCH_LEDGER", journal)
    benchmark = {"frozen": "126 cells in real source; fixture comparator is injected"}
    window = SimpleNamespace(
        pair_id=pair, source_path=tmp_path / (pair + ".resident.window.json"),
        source_sha256="a" * 64, benchmark_plan_file_sha256="b" * 64,
        qualification_summary={"qualification_receipt_sha256": "c" * 64},
        benchmark_plan=benchmark, runtime_budget_seconds=10_430,
    )
    monkeypatch.setattr(gate, "load_evaluation_window", lambda path, expected_cohort: window)
    monkeypatch.setattr(gate, "_registered_output", lambda pair_id, output_dir, absent: output)
    # The real compare.validate_run validates every immutable cell and call;
    # this isolated test verifies only the surrounding restoration gate.
    monkeypatch.setattr(gate, "validate_run", lambda run, cohort: None)
    monkeypatch.setattr(gate, "validate_private_evidence", lambda run, output: None)
    plan = gate._resident_plan(window, output)
    write_json(output / "plan.json", plan)
    residents = []
    cgroups = {}
    for pid, registered in zip((200, 201), gate.RESIDENTS, strict=True):
        residents.append({
            "id": registered["id"], "name": registered["name"],
            "image": registered["image_id"], "restart_policy": "unless-stopped",
            "restart_count": 0, "pid": pid, "started_at": "2026-09-15T00:00:00+00:00",
            "running": True, "oom_killed": False, "state_error": "",
        })
        cgroups[registered["name"]] = {
            "path": f"/system.slice/docker-{registered['id']}.scope",
            "process_start_ticks": pid * 100, "memory_max_bytes": "max",
            "memory_swap_max_bytes": "max", "memory_current_bytes": 30_000_000,
            "memory_swap_current_bytes": 1024, "memory_events_oom": 0,
            "memory_events_oom_kill": 0,
        }
    nara = {"ActiveState": "active", "SubState": "running", "MainPID": "300"}
    initial = {
        "observed_at": "2026-09-15T00:00:00+00:00", "residents": residents,
        "residents_by_name": {item["name"]: item for item in residents},
        "cgroups_by_name": cgroups, "nara": nara,
    }
    quiet = {**initial, "observed_at": "2026-09-15T00:00:06+00:00",
             "nara": {"ActiveState": "inactive", "SubState": "dead", "MainPID": "0"}}
    final = {**initial, "observed_at": "2026-09-15T00:00:13+00:00",
             "nara": {"ActiveState": "active", "SubState": "running", "MainPID": "301"},
             "watchdog_sentinel_by_name": None, "watchdog_sentinel_by_id": None}
    sentinel_id = "e" * 64
    memory = []
    for ordinal, (seconds, observed_at, phase) in enumerate(zip(
        (101, 104, 108, 112), ("01", "05", "07", "12"),
        ("setup", "quiescing", "evaluation", "restoration"), strict=True
    ), 1):
        memory.append({
            "schema": "flash-next-resident-research-memory-sample/v1",
            "observed_at": f"2026-09-15T00:00:{observed_at}+00:00",
            "monitor_phase": phase,
            "watchdog_sentinel_id": None if phase == "setup" else sentinel_id,
            "observed_monotonic": seconds, "mem_available_gib": 33.0,
            "host_pswpout_pages": 22 + ordinal,
            "incumbent_ids": [item["id"] for item in residents],
            "incumbent_restart_counts": {item["name"]: 0 for item in residents},
            "incumbent_pids": {item["name"]: item["pid"] for item in residents},
            "incumbent_containers": residents, "incumbent_cgroups": cgroups,
            "incumbent_cgroup_swap_bytes": {name: 1024 for name in cgroups},
            "nara": (nara if phase == "setup" else final["nara"]
                     if phase == "restoration" else quiet["nara"]),
            "cgroup_swap_capture_status": "exact_incumbent_pid_cgroup_bound",
        })
    raw_memory = b"".join((json.dumps(row, sort_keys=True) + "\n").encode() for row in memory)
    (output / "resident-memory.jsonl").write_bytes(raw_memory)
    run = {
        "schema_version": "flash-next-ab-run/v1", "run_id": f"{pair}-resident",
        "status": "complete", "promotion_authorized": False,
        "elapsed_s": 100, "plan": benchmark,
    }
    raw_run = write_json(output / "harness" / "run.json", run)
    result = {
        "schema": "flash-next-resident-evaluation-result/v2", "pair_id": pair,
        "status": "complete", "error": None, "exact_final_verification": True,
        "plan_sha256": gate.sha256(plan), "window_plan_sha256": window.source_sha256,
        "benchmark_plan_file_sha256": window.benchmark_plan_file_sha256,
        "resident_qualification_receipt_sha256": plan["resident_qualification_receipt_sha256"],
        "host_swap_action": "diagnostic_only",
        "candidate_cgroup_zero_swap_action": "not_applicable_to_incumbents",
        "weekly_budget_debit": False, "paid_api_calls": 0,
        "production_change_authorized": False,
        "initial_observation": initial, "quiet_observation": quiet,
        "final_observation": final,
        "watchdog_sentinel_id": sentinel_id,
        "restoration": {"status": "verified", "verified_at": "2026-09-15T00:00:13+00:00",
                        "errors": [], "sentinel_retained": False,
                        "original_nara_activity": "active", "final_observation": final,
                        "no_mutation_verified": False},
        "memory_samples": len(memory), "memory_log_sha256": hashlib.sha256(raw_memory).hexdigest(),
        "min_mem_available_gib": 33.0,
        "harness_run_sha256": hashlib.sha256(raw_run).hexdigest(),
        "finished_at": "2026-09-15T00:00:14+00:00",
    }
    write_json(output / "result.json", result)
    state = {
        "schema": "flash-next-resident-evaluation-state/v2", "pair_id": pair,
        "plan_sha256": gate.sha256(plan), "window_plan_sha256": window.source_sha256,
        "phase": "complete", "result_status": "complete", "worker_pid": 100,
        "worker_start_ticks": 123, "initial": initial,
        "quiet_observation": quiet, "final_observation": final,
        "watchdog_sentinel_id": sentinel_id,
        "nara_stop_attempted": True, "restoration": result["restoration"],
        "boot_id": "00000000-0000-0000-0000-000000000000",
        "started_at": "2026-09-15T00:00:00+00:00",
        "monitor_memory_log_relpath": "resident-memory.jsonl",
        "invocation_deadline_at": "2026-09-15T04:00:00+00:00",
    }
    write_json(output / "state.json", state)
    command = [plan["launcher_python_path"], "-m", "bench.flash_next_ab.resident_evaluation_window",
               "--worker", "--eval-plan", str(window.source_path), "--output-dir", str(output)]
    supervisor = {
        "schema": "flash-next-resident-supervision/v1", "pair_id": pair,
        "plan_sha256": gate.sha256(plan), "command_sha256": gate.sha256(command),
        "argv": command, "worker_start_ticks": 123,
        "boot_id": "00000000-0000-0000-0000-000000000000",
        "started_at": "2026-09-15T00:00:00+00:00",
        "hard_deadline_at": "2026-09-15T04:00:00+00:00",
        "pid": 100, "returncode": 0, "complete": True,
        "elapsed_seconds": 15,
        "terminated_at_work_cutoff": False, "force_killed": False,
        "emergency_recovery": None,
        "finished_at": "2026-09-15T00:00:15+00:00",
    }
    write_json(output / "supervision.json", supervisor)
    journal.write_bytes(b"".join((json.dumps(row) + "\n").encode() for row in (
        {"event": "resident_evaluation_started", "pair_id": pair,
         "plan_sha256": gate.sha256(plan), "observed_at": "2026-09-15T00:00:00+00:00",
         "weekly_budget_debit": False, "paid_api_calls": 0},
        {"event": "resident_evaluation_finished", "pair_id": pair,
         "plan_sha256": gate.sha256(plan), "status": "complete",
         "observed_at": "2026-09-15T00:00:14+00:00",
         "weekly_budget_debit": False, "paid_api_calls": 0},
    )))
    return gate, window, output, result, state, supervisor, memory


def test_registered_resident_can_have_existing_swap_and_unlimited_cgroup(tmp_path, monkeypatch):
    gate, window, output, *_ = fixture(tmp_path, monkeypatch)
    receipt = gate.validate_completed_resident_window(window.source_path, output)
    assert receipt["restoration_verified"] is True
    assert receipt["benchmark_plan_file_sha256"] == window.benchmark_plan_file_sha256


def test_real_resident_monitor_produces_bound_phase_rows_without_host_mutation(
    tmp_path, monkeypatch
):
    _gate, _window, _output, result, *_ = fixture(tmp_path, monkeypatch)
    resident = importlib.import_module("bench.flash_next_ab.resident_evaluation_window")
    initial = result["initial_observation"]
    quiet = result["quiet_observation"]
    final = result["final_observation"]
    monkeypatch.setattr(resident, "_available_gib", lambda: 33.0)
    monkeypatch.setattr(resident, "_pswpout_pages", lambda: 22)
    active_monitor = [None]

    def observation(_ops, _initial, *, nara_transition=False):
        phase = active_monitor[0].phase
        assert nara_transition == (phase in {"quiescing", "restoration"})
        return initial if phase == "setup" else final if phase == "restoration" else quiet

    monkeypatch.setattr(resident, "_read_exact_residents", observation)
    path = tmp_path / "real-monitor-only.jsonl"
    monitor = resident.ResidentSafetyMonitor(
        path, object(), initial, deadline=resident.time.monotonic() + 90
    )
    active_monitor[0] = monitor
    monitor._stream = path.open("xb")
    monitor.sample()
    monitor.bind_sentinel(result["watchdog_sentinel_id"])
    monitor.transition("quiescing")
    monitor.transition("evaluation", cohort_initial=quiet)
    monitor.transition("restoration")
    monitor._stream.close()
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert [row["monitor_phase"] for row in rows] == [
        "setup", "setup", "quiescing", "evaluation", "restoration",
    ]
    assert rows[0]["watchdog_sentinel_id"] is None
    assert all(row["watchdog_sentinel_id"] == result["watchdog_sentinel_id"]
               for row in rows[1:])
    assert rows[3]["nara"]["ActiveState"] == "inactive"
    assert rows[4]["nara"]["ActiveState"] == "active"
    assert all(row["incumbent_ids"] == [r["id"] for r in initial["residents"]]
               for row in rows)


@pytest.mark.parametrize("unsafe", ("clean", "resident_unhealthy", "untrusted_state"))
def test_supervisor_recovers_only_trusted_models_then_original_nara(
    tmp_path, monkeypatch, unsafe
):
    gate, window, output, result, *_ = fixture(tmp_path, monkeypatch)
    resident = importlib.import_module("bench.flash_next_ab.resident_evaluation_window")
    state = json.loads((output / "state.json").read_text())
    state["boot_id"] = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    state["phase"] = "evaluation"
    if unsafe == "untrusted_state":
        state["initial"]["residents"][0]["running"] = False
    write_json(output / "state.json", state)
    quiet = result["quiet_observation"]
    final = result["final_observation"]
    sentinel = result["watchdog_sentinel_id"]
    ops_log = []

    class RecoveryOps:
        nara_active = False
        sentinel_present = True

        def run(self, argv, *, timeout, check=True):
            ops_log.append(tuple(argv))
            if argv[:3] == ["systemctl", "--user", "start"]:
                self.nara_active = True
            elif argv[:2] == ["docker", "rm"]:
                assert self.nara_active is True
                self.sentinel_present = False
            else:
                raise AssertionError(argv)
            return SimpleNamespace(stdout="", returncode=0)

    ops = RecoveryOps()
    sentinel_row = {
        "id": sentinel, "name": resident._sentinel_name(window.pair_id),
        "image": resident.IMAGE_ID, "running": False, "oom_killed": False,
        "state_error": "", "restart_policy": "no",
    }

    def inspect(_ops, identity):
        if identity in {sentinel, sentinel_row["name"]} and ops.sentinel_present:
            return sentinel_row
        return None

    def models(_ops, _initial, *, nara_transition=False):
        ops_log.append(("models_verified",))
        if unsafe == "resident_unhealthy":
            raise resident.EvaluationWindowError("fixed model health failed")
        assert nara_transition is True
        return final if ops.nara_active else quiet

    def service(_ops, *, transitioning=False):
        return (
            {"ActiveState": "active", "SubState": "running", "MainPID": "301"}
            if ops.nara_active else
            {"ActiveState": "inactive", "SubState": "dead", "MainPID": "0"}
        )

    monkeypatch.setattr(resident, "_inspect_container", inspect)
    monkeypatch.setattr(resident, "_read_exact_residents", models)
    monkeypatch.setattr(resident, "_service_observation", service)
    monkeypatch.setattr(resident, "_service_state", service)
    monkeypatch.setattr(resident, "resource_lease", lambda _root: nullcontext())
    monkeypatch.setattr(resident, "canonical_root", lambda _root: tmp_path)
    usage = []
    monkeypatch.setattr(resident, "_append_usage", usage.append)
    receipt = resident.supervisor_emergency_resident_restore(
        output, gate._resident_plan(window, output),
        deadline=time.monotonic() + 60, ops=ops,
    )
    if unsafe == "clean":
        assert receipt["status"] == "verified"
        health = next(i for i, row in enumerate(ops_log) if row == ("models_verified",))
        start = next(i for i, row in enumerate(ops_log)
                     if row[:3] == ("systemctl", "--user", "start"))
        remove = next(i for i, row in enumerate(ops_log)
                      if row[:2] == ("docker", "rm"))
        assert health < start < remove
        assert ops.nara_active and not ops.sentinel_present
        assert json.loads((output / "state.json").read_text())["phase"] == "supervisor_recovered"
    else:
        assert receipt["status"] == "unknown"
        assert ops.nara_active is False and ops.sentinel_present is True
        assert not any(row[:3] == ("systemctl", "--user", "start") for row in ops_log)
    assert usage[0]["event"] == "resident_supervisor_recovery"


@pytest.mark.parametrize("change,file,description", (
    (lambda row: row.update(complete=False), "supervision.json", "supervisor"),
    (lambda row: row["final_observation"]["residents"][0].update(pid=202), "result.json", "incomplete"),
    (lambda row: row.update(memory_log_sha256="0" * 64), "result.json", "raw safety evidence"),
    (lambda row: row.update(harness_run_sha256="0" * 64), "result.json", "harness run"),
))
def test_ended_harness_cannot_override_failed_final_proofs(tmp_path, monkeypatch, change, file, description):
    gate, window, output, *_ = fixture(tmp_path, monkeypatch)
    row = json.loads((output / file).read_text())
    change(row)
    write_json(output / file, row)
    with pytest.raises(gate.ResidentAdmissionError, match=description):
        gate.validate_completed_resident_window(window.source_path, output)


def test_resealed_memory_with_blind_interval_or_oom_is_rejected(tmp_path, monkeypatch):
    gate, window, output, result, *_ = fixture(tmp_path, monkeypatch)
    rows = [json.loads(line) for line in (output / "resident-memory.jsonl").read_text().splitlines()]
    rows[1]["observed_monotonic"] = rows[0]["observed_monotonic"] + 11
    content = b"".join((json.dumps(row) + "\n").encode() for row in rows)
    (output / "resident-memory.jsonl").write_bytes(content)
    result["memory_log_sha256"] = hashlib.sha256(content).hexdigest()
    write_json(output / "result.json", result)
    with pytest.raises(gate.ResidentAdmissionError, match="sampling cadence"):
        gate.validate_completed_resident_window(window.source_path, output)


def test_last_raw_sample_must_cover_final_incumbent_state(tmp_path, monkeypatch):
    gate, window, output, result, *_ = fixture(tmp_path, monkeypatch)
    result["final_observation"]["observed_at"] = "2026-09-15T00:00:25+00:00"
    result["restoration"]["final_observation"] = result["final_observation"]
    result["finished_at"] = "2026-09-15T00:00:26+00:00"
    write_json(output / "result.json", result)
    state = json.loads((output / "state.json").read_text())
    state["final_observation"] = result["final_observation"]
    state["restoration"] = result["restoration"]
    write_json(output / "state.json", state)
    supervisor = json.loads((output / "supervision.json").read_text())
    supervisor["finished_at"] = "2026-09-15T00:00:27+00:00"
    write_json(output / "supervision.json", supervisor)
    with pytest.raises(gate.ResidentAdmissionError, match="monitoring stopped"):
        gate.validate_completed_resident_window(window.source_path, output)
