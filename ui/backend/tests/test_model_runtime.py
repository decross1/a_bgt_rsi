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


def result_receipt(state, plan, restoration):
    return {
        "schema": "qwen-flash-next-qualification-result/v3",
        "run_id": RUN_ID,
        "contract_sha256": state["contract_sha256"],
        "plan_sha256": canonical_sha(plan),
        "status": "failed",
        "profile": "C0-S1",
        "docker_memory_limit_bytes": q.DOCKER_MEMORY_LIMIT_BYTES,
        "docker_memory_swap_total_bytes": q.DOCKER_MEMORY_SWAP_TOTAL_BYTES,
        "cgroup_diagnostics_sha256": None,
        "memory_log_sha256": None,
        "failure_class": "other_qualification_failure",
        "pswpin_initial_pages": 7,
        "pswpin_final_pages": 7,
        "pswpin_delta_pages": 0,
        "host_memory_psi_initial_us": {"some": 100, "full": 10},
        "host_memory_psi_final_us": {"some": 100, "full": 10},
        "host_memory_psi_delta_us": {"some": 0, "full": 0},
        "restoration": restoration,
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
        "profile": "C0-S1",
        "invocation_deadline_seconds": 3600,
        "min_mem_available_gib": memory_floor_gib,
        "ready_quiescence_seconds": 60,
        "paging_policy": q.PAGING_POLICY,
    }
    contract_raw = json.dumps({
        "profile": "C0-S1",
        "runtime": {
            "docker_memory_limit_bytes": q.DOCKER_MEMORY_LIMIT_BYTES,
            "docker_memory_swap_total_bytes": q.DOCKER_MEMORY_SWAP_TOTAL_BYTES,
        },
    }).encode()
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
        "host_meminfo_kib": {
            "MemFree": 1_000_000,
            "Cached": 2_000_000,
            "SwapCached": 0,
            "AnonPages": 1_000_000,
            "SwapFree": 500_000,
            "MemAvailable": 3_000_000,
        },
        "host_page_size_bytes": 4096,
        "pswpout_pages": 10,
        "pswpout_delta_pages": 0,
        "pswpin_pages": 7,
        "pswpin_delta_pages": 0,
        "host_memory_psi_total_us": {"some": 100, "full": 10},
        "host_memory_psi_delta_us": {"some": 0, "full": 0},
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
                "memory_max_bytes": q.DOCKER_MEMORY_LIMIT_BYTES,
                "memory_swap_max_bytes": 0,
                "memory_current_bytes": 1024,
                "selected_memory_stat": {
                    "anon": 512, "file": 512, "shmem": 0,
                    "active_file": 0, "inactive_file": 0,
                    "pgscan": 0, "pgsteal": 0,
                },
                "memory_pressure": (
                    "some avg10=0.00 total=0\nfull avg10=0.00 total=0"
                ),
                "memory_events_local": {"oom": 0, "oom_kill": 0},
                "memory_swap_current_bytes": 0,
                "memory_events_oom": 0,
                "memory_events_oom_kill": 0,
            },
        }
    if candidate_phase:
        # Producer order: one unarmed load sample, durable cgroup-bind event,
        # then the armed sample. The event has no pswpin/PSI sample counters.
        observed = datetime.fromisoformat(memory["observed_at"])
        before = dict(memory)
        before.pop("candidate")
        before["observed_at"] = (observed - timedelta(seconds=0.5)).isoformat()
        before["monitor_phase"] = "load"
        before["paging_gate"] = "startup"
        before["ready_quiescence_active"] = False
        before["ready_quiescence_epoch"] = None
        bind = {
            "schema": "qwen-flash-next-cgroup-bind/v1",
            "observed_at": (observed - timedelta(seconds=0.25)).isoformat(),
            "candidate_id": CONTAINER,
            "pid": 300,
            "cgroup": memory["candidate"]["cgroup"],
        }
        memory_rows = [before, bind, memory]
    else:
        memory_rows = [memory]
    (run / "memory.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in memory_rows), encoding="utf-8"
    )

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


def memory_rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def write_memory_rows(path, rows):
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )


def last_memory_sample(path):
    return memory_rows(path)[-1]


def write_last_memory_sample(path, sample):
    rows = memory_rows(path)
    rows[-1] = sample
    write_memory_rows(path, rows)


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


@pytest.mark.parametrize(
    "mutation",
    ["missing", "duplicate", "wrong_id", "wrong_pid", "wrong_ticks", "wrong_phase", "emergency"],
)
def test_live_candidate_requires_one_exact_durable_bind_event(tmp_path, mutation):
    root, run, proc, boot, _state, _plan = fixture(tmp_path)
    source = run / "memory.jsonl"
    rows = [json.loads(line) for line in source.read_text().splitlines()]
    assert [row["schema"] for row in rows] == [
        "qwen-flash-next-memory-sample/v3",
        "qwen-flash-next-cgroup-bind/v1",
        "qwen-flash-next-memory-sample/v3",
    ]
    if mutation == "missing":
        del rows[1]
    elif mutation == "duplicate":
        rows.insert(2, dict(rows[1]))
    elif mutation == "wrong_id":
        rows[1]["candidate_id"] = "d" * 64
    elif mutation == "wrong_pid":
        rows[1]["pid"] = 301
    elif mutation == "wrong_ticks":
        rows[1]["cgroup"]["process_start_ticks"] = 4445
    elif mutation == "wrong_phase":
        rows[0]["monitor_phase"] = "setup"
    else:
        rows.append({
            "observed_at": NOW.isoformat(), "event": "emergency_candidate_stop",
            "candidate_id": CONTAINER, "returncode": 0,
        })
    source.write_text("".join(json.dumps(row) + "\n" for row in rows))
    projected = project(root, proc, boot)
    assert projected["mode"] == "unknown"
    assert projected["mode_source"] == "none"


def test_transition_before_arm_does_not_claim_candidate_research(tmp_path):
    root, _run, proc, boot, _state, _plan = fixture(
        tmp_path, phase="candidate_start"
    )
    projected = project(root, proc, boot)
    assert projected["mode"] == "transitioning"
    assert projected["resident_services_expected"] == "unknown"


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
    write_json(run / "result.json", result_receipt(state, plan, restoration))
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
    write_json(run / "result.json", result_receipt(state, plan, restoration))
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
    write_json(run / "result.json", result_receipt(state, plan, restoration))
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
    memory = last_memory_sample(memory_path)
    memory["candidate"]["cgroup"]["memory_swap_current_bytes"] = 4096
    write_last_memory_sample(memory_path, memory)
    assert project(root, proc, boot)["mode"] == "unknown"

    root, run, proc, boot, _state, _plan = fixture(tmp_path / "unarmed")
    memory_path = run / "memory.jsonl"
    memory = last_memory_sample(memory_path)
    memory["candidate"]["armed"] = False
    memory["candidate"]["cgroup"] = None
    write_last_memory_sample(memory_path, memory)
    assert project(root, proc, boot)["mode"] == "unknown"


def test_registered_c0_s1_profile_and_docker_swap_controls_are_required(tmp_path):
    root, run, proc, boot, state, plan = fixture(tmp_path / "plan")
    plan["profile"] = "C0-legacy"
    write_json(run / "plan.json", plan)
    state["plan_sha256"] = canonical_sha(plan)
    write_json(run / "state.json", state)
    assert project(root, proc, boot)["mode"] == "unknown"

    for field in (
        "docker_memory_limit_bytes", "docker_memory_swap_total_bytes"
    ):
        root, run, proc, boot, state, _plan = fixture(tmp_path / field)
        contract_path = run / "launch-contract.raw.json"
        contract = json.loads(contract_path.read_text())
        contract["runtime"][field] += 4096
        contract_path.write_text(json.dumps(contract), encoding="utf-8")
        state["contract_sha256"] = hashlib.sha256(
            contract_path.read_bytes()
        ).hexdigest()
        write_json(run / "state.json", state)
        assert project(root, proc, boot)["mode"] == "unknown"


@pytest.mark.parametrize(
    "field,value",
    [
        ("cgroup_memory_max", 0),
        ("cgroup_swap_max", 4096),
        ("cgroup_memory_current", -1),
        ("cgroup_stat_missing", None),
        ("cgroup_pressure_missing", None),
        ("cgroup_local_events_drift", 1),
        ("host_meminfo_missing", None),
    ],
)
def test_candidate_mode_rejects_missing_or_drifted_no_swap_diagnostics(
    tmp_path, field, value
):
    root, run, proc, boot, _state, _plan = fixture(tmp_path)
    memory_path = run / "memory.jsonl"
    memory = last_memory_sample(memory_path)
    candidate = memory["candidate"]
    cgroup = candidate["cgroup"]
    if field == "cgroup_memory_max":
        cgroup["memory_max_bytes"] = value
    elif field == "cgroup_swap_max":
        cgroup["memory_swap_max_bytes"] = value
    elif field == "cgroup_memory_current":
        cgroup["memory_current_bytes"] = value
    elif field == "cgroup_stat_missing":
        del cgroup["selected_memory_stat"]["anon"]
    elif field == "cgroup_pressure_missing":
        del cgroup["memory_pressure"]
    elif field == "cgroup_local_events_drift":
        cgroup["memory_events_local"]["oom"] = value
    elif field == "host_meminfo_missing":
        del memory["host_meminfo_kib"]["SwapFree"]
    write_last_memory_sample(memory_path, memory)
    assert project(root, proc, boot)["mode"] == "unknown"


def test_registered_v3_memory_reader_accepts_more_than_legacy_four_megabytes(tmp_path):
    root, run, proc, boot, _state, _plan = fixture(tmp_path)
    memory_path = run / "memory.jsonl"
    rows = memory_rows(memory_path)
    one_sample = (json.dumps(rows[-1]) + "\n").encode()
    copies = (5 * 1024 * 1024 // len(one_sample)) + 1
    memory_path.write_bytes(
        "".join(json.dumps(row) + "\n" for row in rows[:-1]).encode()
        + one_sample * copies
    )
    assert 4 * 1024 * 1024 < memory_path.stat().st_size < 32 * 1024 * 1024
    assert project(root, proc, boot)["mode"] == "candidate_research"


@pytest.mark.parametrize(
    "field",
    [
        "pswpin_pages", "pswpin_delta_pages",
        "host_memory_psi_total_us", "host_memory_psi_delta_us",
    ],
)
def test_s1_raw_pagein_and_pressure_diagnostics_are_required(tmp_path, field):
    root, run, proc, boot, _state, _plan = fixture(tmp_path)
    memory_path = run / "memory.jsonl"
    sample = last_memory_sample(memory_path)
    del sample[field]
    write_last_memory_sample(memory_path, sample)
    assert project(root, proc, boot)["mode"] == "unknown"


def test_s1_pagein_and_pressure_are_monotonic_across_the_full_bounded_log(tmp_path):
    root, run, proc, boot, _state, _plan = fixture(tmp_path)
    memory_path = run / "memory.jsonl"
    prefix = memory_rows(memory_path)[:-1]
    final = last_memory_sample(memory_path)
    earlier = json.loads(json.dumps(final))
    earlier["pswpin_pages"] = 8
    earlier["pswpin_delta_pages"] = 1
    earlier["host_memory_psi_total_us"]["some"] = 101
    earlier["host_memory_psi_delta_us"]["some"] = 1
    write_memory_rows(memory_path, [*prefix, earlier, final])
    assert project(root, proc, boot)["mode"] == "unknown"

    earlier = json.loads(json.dumps(final))
    later = json.loads(json.dumps(final))
    later["pswpin_pages"] = 8
    later["pswpin_delta_pages"] = 0  # Raw counter rose without its delta.
    write_memory_rows(memory_path, [*prefix, earlier, later])
    assert project(root, proc, boot)["mode"] == "unknown"

    memory_path.write_text(
        "".join(json.dumps(row) + "\n" for row in prefix)
        + "{malformed}\n" + json.dumps(final) + "\n"
    )
    assert project(root, proc, boot)["mode"] == "unknown"


def test_s1_pagein_and_pressure_magnitude_is_diagnostic_not_a_new_hard_gate(
    tmp_path,
):
    root, run, proc, boot, _state, _plan = fixture(tmp_path)
    memory_path = run / "memory.jsonl"
    prefix = memory_rows(memory_path)[:-1]
    first = last_memory_sample(memory_path)
    later = json.loads(json.dumps(first))
    later["pswpin_pages"] = 100_000
    later["pswpin_delta_pages"] = 100_000 - first["pswpin_pages"]
    later["host_memory_psi_total_us"] = {"some": 1_000_000, "full": 100_000}
    later["host_memory_psi_delta_us"] = {
        "some": 1_000_000 - first["host_memory_psi_total_us"]["some"],
        "full": 100_000 - first["host_memory_psi_total_us"]["full"],
    }
    write_memory_rows(memory_path, [*prefix, later])
    assert project(root, proc, boot)["mode"] == "candidate_research"


@pytest.mark.parametrize(
    "field", ["profile", "docker_memory_limit_bytes", "memory_log_sha256"]
)
def test_terminal_c0_s1_receipt_profile_and_paired_hashes_are_bound(tmp_path, field):
    root, run, proc, boot, state, plan = fixture(tmp_path, phase="complete")
    restoration = {
        "status": "verified", "errors": [], "sentinel_retained": False,
        "verified_at": NOW.isoformat(),
    }
    state["restoration"] = restoration
    write_json(run / "state.json", state)
    receipt = result_receipt(state, plan, restoration)
    if field == "profile":
        receipt[field] = "C0-legacy"
    elif field == "docker_memory_limit_bytes":
        receipt[field] += 4096
    else:
        receipt[field] = "d" * 64  # One diagnostic hash without its memory partner.
    write_json(run / "result.json", receipt)
    assert project(root, proc, boot)["mode"] == "unknown"


@pytest.mark.parametrize(
    "field",
    ["failure_class", "pswpin_delta_pages", "host_memory_psi_delta_us"],
)
def test_terminal_s1_failure_class_and_raw_channel_identities_are_bound(
    tmp_path, field
):
    root, run, proc, boot, state, plan = fixture(tmp_path, phase="complete")
    restoration = {
        "status": "verified", "errors": [], "sentinel_retained": False,
        "verified_at": NOW.isoformat(),
    }
    state["restoration"] = restoration
    write_json(run / "state.json", state)
    receipt = result_receipt(state, plan, restoration)
    if field == "failure_class":
        receipt[field] = "model_fitness_rejected"  # Not a registered claim.
    elif field == "pswpin_delta_pages":
        receipt[field] = 1
    else:
        receipt[field]["some"] = 1
    write_json(run / "result.json", receipt)
    assert project(root, proc, boot)["mode"] == "unknown"


def test_candidate_mode_rejects_lifecycle_or_paging_drift(tmp_path):
    root, _run, proc, boot, _state, _plan = fixture(
        tmp_path / "phase", monitor_phase="ready"
    )
    assert project(root, proc, boot)["mode"] == "unknown"

    root, run, proc, boot, _state, _plan = fixture(tmp_path / "threshold")
    memory_path = run / "memory.jsonl"
    memory = last_memory_sample(memory_path)
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
    write_last_memory_sample(memory_path, memory)
    assert project(root, proc, boot)["mode"] == "unknown"

    root, run, proc, boot, _state, _plan = fixture(tmp_path / "sample-gap")
    memory_path = run / "memory.jsonl"
    memory = last_memory_sample(memory_path)
    memory["sample_gap_seconds"] = q.PAGING_POLICY["max_sample_gap_seconds"] + 0.001
    write_last_memory_sample(memory_path, memory)
    assert project(root, proc, boot)["mode"] == "unknown"

    root, run, proc, boot, _state, _plan = fixture(
        tmp_path / "wrong-gate", phase="ready_stabilization"
    )
    memory_path = run / "memory.jsonl"
    memory = last_memory_sample(memory_path)
    memory["paging_gate"] = "serving"
    write_last_memory_sample(memory_path, memory)
    assert project(root, proc, boot)["mode"] == "unknown"


def test_ready_phase_uses_cumulative_startup_gate_for_windows_and_total(tmp_path):
    root, run, proc, boot, _state, _plan = fixture(
        tmp_path / "within", phase="ready_stabilization"
    )
    memory_path = run / "memory.jsonl"
    memory = last_memory_sample(memory_path)
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
    write_last_memory_sample(memory_path, memory)
    assert project(root, proc, boot)["mode"] == "candidate_research"

    root, run, proc, boot, _state, _plan = fixture(
        tmp_path / "breach", phase="ready_stabilization"
    )
    memory_path = run / "memory.jsonl"
    memory = last_memory_sample(memory_path)
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
    write_last_memory_sample(memory_path, memory)
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


def mia_fixture(tmp_path, monkeypatch):
    """Producer-shaped v4 bind/sample proof with registered Mia identity.

    The closed plan/contract validator is isolated here; these cases exercise
    the live mode reader's raw image, Docker-limit, and cgroup bindings.
    """
    from backend import model_runtime as module
    from bench.flash_next_ab.candidate_registry import MIA

    root, run, proc, boot, state, plan = fixture(tmp_path)
    mia_run = root / "qfn-mia-c0-runtime-fixture"
    run.rename(mia_run)
    plan["profile"] = MIA.profile
    plan["paging_policy"] = MIA.paging_policy()
    plan["min_mem_available_gib"] = MIA.min_mem_available_gib
    write_json(mia_run / "plan.json", plan)
    contract = {
        "profile": MIA.profile,
        "runtime": {
            "docker_memory_limit_bytes": MIA.docker_memory_limit_bytes,
            "docker_memory_swap_total_bytes": MIA.docker_memory_limit_bytes,
        },
    }
    contract_raw = json.dumps(contract).encode()
    (mia_run / "launch-contract.raw.json").write_bytes(contract_raw)
    state.update(
        schema="qwen-flash-next-qualification-state/v4",
        run_id=mia_run.name,
        plan_sha256=canonical_sha(plan),
        contract_sha256=hashlib.sha256(contract_raw).hexdigest(),
        paging_policy=MIA.paging_policy(),
        candidate={"id": MIA.spec_id, "spec_sha256": MIA.identity_sha256()},
        model_artifact_sha256=MIA.model_artifact_sha256(),
    )
    write_json(mia_run / "state.json", state)

    rows = memory_rows(mia_run / "memory.jsonl")
    rows[1]["candidate_spec"] = state["candidate"]
    rows[1]["container_inspect"] = {
        "id": CONTAINER, "name": MIA.container_name, "image": MIA.image_id,
        "running": True, "oom_killed": False, "restart_count": 0,
        "pid": 300, "memory_limit_bytes": MIA.docker_memory_limit_bytes,
        "memory_swap_total_bytes": MIA.docker_memory_limit_bytes,
    }
    rows[2]["candidate"].update(
        name=MIA.container_name, image=MIA.image_id,
        memory_limit_bytes=MIA.docker_memory_limit_bytes,
        memory_swap_total_bytes=MIA.docker_memory_limit_bytes,
    )
    write_memory_rows(mia_run / "memory.jsonl", rows)
    process = proc / str(PID)
    command = [
        "/usr/bin/python3", "-m", "bench.flash_next_ab.qualification",
        "--worker", "--contract", str(MIA.contract_path),
        "--output-dir", str(mia_run),
    ]
    (process / "cmdline").write_bytes(
        b"\0".join(value.encode() for value in command) + b"\0"
    )
    monkeypatch.setattr(module, "_validate_registered_mia_plan", lambda *_args: None)
    return root, mia_run, proc, boot, MIA


def test_mia_live_mode_exposes_exact_variant_and_observed_image(tmp_path, monkeypatch):
    root, _run, proc, boot, spec = mia_fixture(tmp_path, monkeypatch)
    row = project(root, proc, boot)
    assert row["mode"] == "candidate_research"
    assert row["candidate_variant"] == {
        "spec_id": spec.spec_id,
        "spec_sha256": spec.identity_sha256(),
        "repository": spec.repository,
        "revision": spec.revision,
        "served_model": spec.served_name,
        "image_id": spec.image_id,
        "model_artifact_sha256": spec.model_artifact_sha256(),
        "profile": spec.profile,
        "configured_max_context_tokens": spec.max_model_len,
        "configured_mtp_speculative_tokens": 0,
        "configured_kv_cache_memory_bytes": spec.kv_cache_memory_bytes,
        "source": "registered_plan_and_controller_state",
        "image_evidence": "bound_live_container",
        "promotion_authorized": False,
    }


@pytest.mark.parametrize(
    "mutation",
    ["spec_hash", "bind_image", "bind_name", "bind_memory", "sample_image", "sample_name", "sample_memory"],
)
def test_mia_variant_drift_withholds_active_research_mode(tmp_path, monkeypatch, mutation):
    root, run, proc, boot, _spec = mia_fixture(tmp_path, monkeypatch)
    source = run / "memory.jsonl"
    rows = memory_rows(source)
    target = rows[1] if mutation.startswith("bind") or mutation == "spec_hash" else rows[2]["candidate"]
    if mutation == "spec_hash":
        target["candidate_spec"]["spec_sha256"] = "0" * 64
    elif mutation == "bind_image":
        target["container_inspect"]["image"] = "sha256:" + "0" * 64
    elif mutation == "bind_name":
        target["container_inspect"]["name"] = "unregistered-mia"
    elif mutation == "bind_memory":
        target["container_inspect"]["memory_limit_bytes"] -= 1
    elif mutation == "sample_image":
        target["image"] = "sha256:" + "0" * 64
    elif mutation == "sample_name":
        target["name"] = "unregistered-mia"
    else:
        target["memory_limit_bytes"] -= 1
    write_memory_rows(source, rows)
    row = project(root, proc, boot)
    assert row["mode"] == "unknown"
    assert row["candidate_variant"] is None


def test_newer_invalid_mia_state_blocks_fallback_to_older_nvidia_state(tmp_path):
    root, _run, proc, boot, _state, _plan = fixture(tmp_path)
    newest = root / "qfn-mia-c0-invalid-newest"
    newest.mkdir()
    (newest / "state.json").write_bytes(b"{invalid JSON")
    row = project(root, proc, boot)
    assert row["mode"] == "unknown"
    assert row["run_id"] is None
    assert row["candidate_variant"] is None
