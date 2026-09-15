"""A research mode requires a live, hash-bound controller state."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.model_runtime import project_model_runtime
from backend.served_models import register
from bench.flash_next_ab import qualification as q

NOW = datetime(2026, 9, 15, 3, 0, tzinfo=timezone.utc)
RUN_ID = "qfn-c0-runtime-fixture"
PID = 4242
TICKS = 987654
CONTAINER = "c" * 64
GEMMA_ID = "fc61a80d6c2d07b551c5afdd566a7c82ee05ad40c014d69c428e299e49101374"
QWEN_ID = "bcb6cd87757279ff77f1460cab2f8ad6cf1a2e46d19dad165b07dccecfa509bb"


def canonical_sha(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def initial():
    return {
        "nara_was_active": True,
        "residents": [
            {"name": "vllm-gemma4", "id": GEMMA_ID, "running": True},
            {"name": "vllm-qwen", "id": QWEN_ID, "running": True},
        ],
    }


def fixture(
    tmp_path,
    *,
    phase="readiness",
    memory_age_s=1,
    memory_available_gib=31,
    memory_floor_gib=20,
    schema=None,
    monitor_phase=None,
):
    root = tmp_path / "qualification-runs"
    run = root / RUN_ID
    run.mkdir(parents=True)
    plan = {
        "invocation_deadline_seconds": 3600,
        "min_mem_available_gib": memory_floor_gib,
        "ready_quiescence_seconds": 60,
        "paging_policy": q.PAGING_POLICY,
    }
    contract_raw = b'{"fixed":"contract"}'
    (run / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    (run / "launch-contract.raw.json").write_bytes(contract_raw)
    phase_monitors = {
        "preflight": "setup",
        "model_verification": "setup",
        "setup_quiescence": "setup",
        "sentinel_create": "load",
        "resident_stop": "load",
        "candidate_start": "load",
        "readiness": "load",
        "ready_stabilization": "ready",
        "probes": "probes",
        "qualification_passed": "probes",
        "restoring": "restoration",
        "complete": "restoration",
    }
    candidate_phase = phase in {
        "readiness", "ready_stabilization", "probes", "qualification_passed"
    }
    started_at = NOW - timedelta(minutes=5)
    state = {
        "schema": schema or "qwen-flash-next-qualification-state/v3",
        "run_id": RUN_ID,
        "phase": phase,
        "plan_sha256": canonical_sha(plan),
        "contract_sha256": hashlib.sha256(contract_raw).hexdigest(),
        "boot_id": "boot-fixture",
        "worker_pid": PID,
        "worker_start_ticks": TICKS,
        "started_at": started_at.isoformat(),
        "updated_at": NOW.isoformat(),
        "invocation_deadline_at": (
            started_at + timedelta(seconds=3600)
        ).isoformat(),
        "memory_log_relpath": "memory.jsonl",
        "monitor_phase": monitor_phase or phase_monitors[phase],
        "paging_policy": q.PAGING_POLICY,
        "candidate_id": CONTAINER if candidate_phase else None,
        "candidate_cgroup_path": (
            f"/system.slice/docker-{CONTAINER}.scope" if candidate_phase else None
        ),
        "candidate_cgroup_pid": 300 if candidate_phase else None,
        "candidate_cgroup_start_ticks": 4444 if candidate_phase else None,
        "ready_quiescence": (
            {
                "required_seconds": 60,
                "passed": True,
                "started_at": (NOW - timedelta(seconds=61)).isoformat(),
                "completed_at": (NOW - timedelta(seconds=1)).isoformat(),
                "duration_seconds": 60.0,
                "initial_pswpout_pages": 10,
                "final_pswpout_pages": 10,
                "samples": 61,
                "epoch": 1,
            }
            if phase in {"probes", "qualification_passed"}
            else {"status": "not_started"}
        ),
        "initial": initial(),
        "restoration": {"status": "not_started"},
    }
    write_json(run / "state.json", state)
    memory = {
        "schema": "qwen-flash-next-memory-sample/v3",
        "observed_at": (NOW - timedelta(seconds=memory_age_s)).isoformat(),
        "elapsed_monotonic_seconds": 10.0,
        "sample_gap_seconds": 1.0,
        "monitor_phase": monitor_phase or phase_monitors[phase],
        "setup_quiescence_active": phase == "setup_quiescence",
        "ready_quiescence_active": phase == "ready_stabilization",
        "ready_quiescence_epoch": 1 if phase == "ready_stabilization" else None,
        "mem_available_gib": memory_available_gib,
        "host_page_size_bytes": 4096,
        "pswpout_pages": 10,
        "pswpout_delta_pages": 0,
        "paging_gate": {
            "setup": "setup",
            "load": "startup",
            "ready": "startup",
            "probes": "serving",
            "restoration": "restoration",
        }[monitor_phase or phase_monitors[phase]],
        "gate_initial_pswpout_pages": 10,
        "gate_pswpout_delta_pages": 0,
        "gate_pswpout_delta_bytes": 0,
        "phase_initial_pswpout_pages": 10,
        "phase_pswpout_delta_pages": 0,
        "phase_pswpout_delta_bytes": 0,
        "host_swap_5s_bytes": 0,
        "host_swap_60s_bytes": 0,
        "transition_to": None,
    }
    if candidate_phase:
        memory["candidate"] = {
            "id": CONTAINER,
            "armed": True,
            "running": True,
            "oom_killed": False,
            "restart_count": 0,
            "pid": 300,
            "cgroup": {
                "path": f"/system.slice/docker-{CONTAINER}.scope",
                "process_start_ticks": 4444,
                "memory_swap_current_bytes": 0,
                "memory_events_oom": 0,
                "memory_events_oom_kill": 0,
            },
        }
    (run / "memory.jsonl").write_text(json.dumps(memory) + "\n", encoding="utf-8")

    proc = tmp_path / "proc"
    boot = proc / "sys/kernel/random/boot_id"
    boot.parent.mkdir(parents=True)
    boot.write_text("boot-fixture\n", encoding="ascii")
    process = proc / str(PID)
    process.mkdir(parents=True)
    # Tokens after the closing parenthesis are Linux stat fields 3 onward;
    # index 19 is field 22 (starttime).
    stat_fields = ["S", *(["0"] * 18), str(TICKS)]
    (process / "stat").write_text(
        f"{PID} (python worker) " + " ".join(stat_fields), encoding="utf-8"
    )
    from bench.flash_next_ab.qualification import CONTRACT_PATH

    command = [
        "/usr/bin/python3",
        "-m",
        "bench.flash_next_ab.qualification",
        "--worker",
        "--contract",
        str(CONTRACT_PATH),
        "--output-dir",
        str(run),
    ]
    (process / "cmdline").write_bytes(b"\0".join(p.encode() for p in command) + b"\0")
    return root, run, proc, boot, state, plan


def project(root, proc, boot, **kwargs):
    terminal_validator = kwargs.pop("terminal_validator", lambda _path: None)
    return project_model_runtime(
        root,
        proc_root=proc,
        boot_id_path=boot,
        now=lambda: NOW,
        plan_validator=lambda *_args: None,
        terminal_validator=terminal_validator,
        **kwargs,
    )


def test_live_candidate_phase_reports_authorized_research_expectations(tmp_path):
    root, _run, proc, boot, _state, _plan = fixture(tmp_path)
    row = project(root, proc, boot)
    assert row["schema_version"] == "model-runtime/v1"
    assert row["mode"] == "candidate_research"
    assert row["resident_services_expected"] == "stopped"
    assert row["nara_service_expected"] == "paused"
    assert row["mode_source"] == "qualification_state"
    assert len(row["mode_source_sha256"]) == 64
    assert row["run_id"] == RUN_ID
    assert row["phase"] == "readiness"
    assert row["source_error"] is None


def test_setup_and_stop_restore_phases_are_transitions(tmp_path):
    for index, phase in enumerate(
        ("setup_quiescence", "resident_stop", "candidate_start", "restoring")
    ):
        case = tmp_path / str(index)
        root, _run, proc, boot, _state, _plan = fixture(case, phase=phase)
        row = project(root, proc, boot)
        assert row["mode"] == "transitioning"
        assert row["resident_services_expected"] == "unknown"
        assert row["nara_service_expected"] == "unknown"


def test_ready_stabilization_is_a_bound_candidate_phase(tmp_path):
    root, _run, proc, boot, _state, _plan = fixture(
        tmp_path, phase="ready_stabilization"
    )
    row = project(root, proc, boot)
    assert row["mode"] == "candidate_research"
    assert row["phase"] == "ready_stabilization"


def test_stale_memory_or_reused_pid_fails_unknown(tmp_path):
    root, _run, proc, boot, _state, _plan = fixture(tmp_path, memory_age_s=6)
    assert project(root, proc, boot)["mode"] == "unknown"

    root, _run, proc, boot, _state, _plan = fixture(tmp_path / "pid")
    stat_path = proc / str(PID) / "stat"
    stat_path.write_text(stat_path.read_text().replace(str(TICKS), "123"))
    assert project(root, proc, boot)["mode"] == "unknown"


def test_memory_gate_uses_the_registered_plan_floor(tmp_path):
    root, _run, proc, boot, _state, _plan = fixture(
        tmp_path / "at-floor", memory_available_gib=20
    )
    assert project(root, proc, boot)["mode"] == "candidate_research"

    root, _run, proc, boot, _state, _plan = fixture(
        tmp_path / "below-floor", memory_available_gib=19.999
    )
    assert project(root, proc, boot)["mode"] == "unknown"

    root, _run, proc, boot, _state, _plan = fixture(
        tmp_path / "bad-floor", memory_floor_gib=float("inf")
    )
    assert project(root, proc, boot)["mode"] == "unknown"


def test_wrong_boot_command_or_expired_deadline_fails_unknown(tmp_path):
    root, _run, proc, boot, _state, _plan = fixture(tmp_path / "boot")
    boot.write_text("different-boot\n")
    assert project(root, proc, boot)["mode"] == "unknown"

    root, _run, proc, boot, _state, _plan = fixture(tmp_path / "command")
    (proc / str(PID) / "cmdline").write_bytes(b"/usr/bin/python3\0-c\0bad\0")
    assert project(root, proc, boot)["mode"] == "unknown"

    root, run, proc, boot, state, _plan = fixture(tmp_path / "expired")
    state["started_at"] = (NOW - timedelta(hours=2)).isoformat()
    state["updated_at"] = (NOW - timedelta(hours=2)).isoformat()
    state["invocation_deadline_at"] = (NOW - timedelta(hours=1)).isoformat()
    write_json(run / "state.json", state)
    assert project(root, proc, boot)["mode"] == "unknown"


@pytest.mark.parametrize(
    "schema",
    [
        "qwen-flash-next-qualification-state/v1",
        "qwen-flash-next-qualification-state/v2",
    ],
)
def test_legacy_state_or_hash_drift_never_claims_a_mode(tmp_path, schema):
    root, _run, proc, boot, _state, _plan = fixture(tmp_path / schema[-2:], schema=schema)
    assert project(root, proc, boot)["mode"] == "unknown"

    root, run, proc, boot, state, _plan = fixture(tmp_path / "hash")
    state["plan_sha256"] = "0" * 64
    write_json(run / "state.json", state)
    assert project(root, proc, boot)["mode"] == "unknown"


def test_verified_terminal_receipt_returns_resident_mode_without_live_pid(tmp_path):
    root, run, proc, boot, state, plan = fixture(tmp_path, phase="complete")
    restoration = {
        "status": "verified",
        "errors": [],
        "sentinel_retained": False,
        "verified_at": NOW.isoformat(),
    }
    state["restoration"] = restoration
    state["result_status"] = "failed"
    write_json(run / "state.json", state)
    write_json(run / "result.json", {
        "schema": "qwen-flash-next-qualification-result/v3",
        "run_id": RUN_ID,
        "contract_sha256": state["contract_sha256"],
        "plan_sha256": canonical_sha(plan),
        "restoration": restoration,
    })
    os.remove(proc / str(PID) / "stat")
    row = project(root, proc, boot)
    assert row["mode"] == "resident"
    assert row["resident_services_expected"] == "online"
    assert row["nara_service_expected"] == "running"


def test_terminal_status_string_cannot_hide_restore_errors(tmp_path):
    root, run, proc, boot, state, plan = fixture(tmp_path, phase="complete")
    restoration = {
        "status": "verified",
        "errors": ["resident health was not observed"],
        "sentinel_retained": False,
        "verified_at": NOW.isoformat(),
    }
    state["restoration"] = restoration
    write_json(run / "state.json", state)
    write_json(run / "result.json", {
        "schema": "qwen-flash-next-qualification-result/v3",
        "run_id": RUN_ID,
        "contract_sha256": state["contract_sha256"],
        "plan_sha256": canonical_sha(plan),
        "restoration": restoration,
    })
    assert project(root, proc, boot)["mode"] == "unknown"


def test_newest_untrusted_state_blocks_fallback_to_an_old_resident_receipt(tmp_path):
    root, run, proc, boot, state, plan = fixture(tmp_path, phase="complete")
    restoration = {
        "status": "verified",
        "errors": [],
        "sentinel_retained": False,
        "verified_at": NOW.isoformat(),
    }
    state["restoration"] = restoration
    write_json(run / "state.json", state)
    write_json(run / "result.json", {
        "schema": "qwen-flash-next-qualification-result/v3",
        "run_id": RUN_ID,
        "contract_sha256": state["contract_sha256"],
        "plan_sha256": canonical_sha(plan),
        "restoration": restoration,
    })
    old = NOW.timestamp() - 60
    os.utime(run / "state.json", (old, old))

    newer = root / "qfn-c0-newer-invalid"
    newer.mkdir()
    (newer / "state.json").write_text("not-json")
    future = NOW.timestamp() + 60
    os.utime(newer / "state.json", (future, future))
    assert project(root, proc, boot)["mode"] == "unknown"


def test_candidate_mode_requires_matching_live_cgroup_evidence(tmp_path):
    root, run, proc, boot, state, _plan = fixture(tmp_path / "state")
    state["candidate_cgroup_pid"] += 1
    write_json(run / "state.json", state)
    assert project(root, proc, boot)["mode"] == "unknown"

    root, run, proc, boot, _state, _plan = fixture(tmp_path / "memory")
    memory_path = run / "memory.jsonl"
    memory = json.loads(memory_path.read_text())
    memory["candidate"]["cgroup"]["memory_swap_current_bytes"] = 4096
    memory_path.write_text(json.dumps(memory) + "\n")
    assert project(root, proc, boot)["mode"] == "unknown"

    root, run, proc, boot, _state, _plan = fixture(tmp_path / "unarmed")
    memory_path = run / "memory.jsonl"
    memory = json.loads(memory_path.read_text())
    memory["candidate"]["armed"] = False
    memory["candidate"]["cgroup"] = None
    memory_path.write_text(json.dumps(memory) + "\n")
    assert project(root, proc, boot)["mode"] == "unknown"


def test_candidate_mode_rejects_lifecycle_or_paging_drift(tmp_path):
    root, _run, proc, boot, _state, _plan = fixture(
        tmp_path / "phase", monitor_phase="ready"
    )
    assert project(root, proc, boot)["mode"] == "unknown"

    root, run, proc, boot, _state, _plan = fixture(tmp_path / "threshold")
    memory_path = run / "memory.jsonl"
    memory = json.loads(memory_path.read_text())
    delta_pages = q.PAGING_POLICY["load"]["window_5s_breach_bytes"] // 4096
    memory.update(
        pswpout_pages=10 + delta_pages,
        gate_pswpout_delta_pages=delta_pages,
        gate_pswpout_delta_bytes=delta_pages * 4096,
        phase_pswpout_delta_pages=delta_pages,
        phase_pswpout_delta_bytes=delta_pages * 4096,
        host_swap_5s_bytes=delta_pages * 4096,
        host_swap_60s_bytes=delta_pages * 4096,
    )
    memory_path.write_text(json.dumps(memory) + "\n")
    assert project(root, proc, boot)["mode"] == "unknown"

    root, run, proc, boot, _state, _plan = fixture(tmp_path / "sample-gap")
    memory_path = run / "memory.jsonl"
    memory = json.loads(memory_path.read_text())
    memory["sample_gap_seconds"] = q.PAGING_POLICY["max_sample_gap_seconds"] + 0.001
    memory_path.write_text(json.dumps(memory) + "\n")
    assert project(root, proc, boot)["mode"] == "unknown"

    root, run, proc, boot, _state, _plan = fixture(
        tmp_path / "wrong-gate", phase="ready_stabilization"
    )
    memory_path = run / "memory.jsonl"
    memory = json.loads(memory_path.read_text())
    memory["paging_gate"] = "serving"
    memory_path.write_text(json.dumps(memory) + "\n")
    assert project(root, proc, boot)["mode"] == "unknown"


def test_ready_phase_uses_cumulative_startup_gate_for_windows_and_total(tmp_path):
    root, run, proc, boot, _state, _plan = fixture(
        tmp_path / "within", phase="ready_stabilization"
    )
    memory_path = run / "memory.jsonl"
    memory = json.loads(memory_path.read_text())
    memory.update(
        pswpout_pages=12,
        pswpout_delta_pages=2,
        gate_initial_pswpout_pages=10,
        gate_pswpout_delta_pages=2,
        gate_pswpout_delta_bytes=8192,
        phase_initial_pswpout_pages=12,
        phase_pswpout_delta_pages=0,
        phase_pswpout_delta_bytes=0,
        host_swap_5s_bytes=4096,
        host_swap_60s_bytes=8192,
    )
    memory_path.write_text(json.dumps(memory) + "\n")
    assert project(root, proc, boot)["mode"] == "candidate_research"

    root, run, proc, boot, _state, _plan = fixture(
        tmp_path / "breach", phase="ready_stabilization"
    )
    memory_path = run / "memory.jsonl"
    memory = json.loads(memory_path.read_text())
    delta_pages = q.PAGING_POLICY["load"]["phase_total_breach_bytes"] // 4096
    current_pages = 10 + delta_pages
    memory.update(
        pswpout_pages=current_pages,
        pswpout_delta_pages=delta_pages,
        gate_initial_pswpout_pages=10,
        gate_pswpout_delta_pages=delta_pages,
        gate_pswpout_delta_bytes=delta_pages * 4096,
        phase_initial_pswpout_pages=current_pages,
        phase_pswpout_delta_pages=0,
        phase_pswpout_delta_bytes=0,
    )
    memory_path.write_text(json.dumps(memory) + "\n")
    assert project(root, proc, boot)["mode"] == "unknown"


def test_probe_phase_requires_completed_ready_quiescence(tmp_path):
    root, run, proc, boot, state, _plan = fixture(tmp_path, phase="probes")
    state["ready_quiescence"] = {"status": "not_started"}
    write_json(run / "state.json", state)
    assert project(root, proc, boot)["mode"] == "unknown"


def test_model_runtime_api_caches_the_original_observation():
    calls = []

    def projector():
        calls.append(1)
        return {
            "schema_version": "model-runtime/v1",
            "observed_at": "2026-09-15T03:00:00+00:00",
            "mode": "unknown",
            "mode_source": "none",
            "mode_source_sha256": None,
            "resident_services_expected": "unknown",
            "nara_service_expected": "unknown",
            "run_id": None,
            "phase": None,
            "source_error": "fixture",
        }

    app = FastAPI()
    register(app, endpoints={"flash": "http://f:8012"}, opener=lambda *_a, **_k: None,
             runtime_projector=projector, runtime_ttl_s=60)
    client = TestClient(app)
    first = client.get("/api/model_runtime").json()
    second = client.get("/api/model_runtime").json()
    assert first == second
    assert calls == [1]
