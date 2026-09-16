from __future__ import annotations

import copy
import hashlib
import json
import os
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from backend import model_runtime_stable as stable
from bench.stable_benchmark import receipt_verification as rv

NOW = datetime(2026, 9, 16, 6, 30, tzinfo=timezone.utc)
PID = 4242
TICKS = 987654
BOOT_ID = "stable-test-boot"
GEMMA_ID = "fc61a80d6c2d07b551c5afdd566a7c82ee05ad40c014d69c428e299e49101374"
QWEN_ID = "bcb6cd87757279ff77f1460cab2f8ad6cf1a2e46d19dad165b07dccecfa509bb"
ZERO = "0" * 64


def _canonical(value: Any, *, newline: bool = False) -> bytes:
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    return raw + (b"\n" if newline else b"")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _write(path: Path, value: Any, *, newline: bool = True) -> str:
    raw = _canonical(value, newline=newline)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return _sha(raw)


def _resident(name: str, identity: str, pid: int) -> dict[str, Any]:
    return {
        "name": name,
        "id": identity,
        "image": "sha256:" + ("a" if name == "vllm-gemma4" else "b") * 64,
        "running": True,
        "oom_killed": False,
        "state_error": "",
        "restart_policy": "unless-stopped",
        "restart_count": 0,
        "pid": pid,
        "started_at": "2026-09-15T00:00:00Z",
    }


def _cgroup(identity: str, pid: int) -> dict[str, Any]:
    return {
        "path": f"/system.slice/docker-{identity}.scope",
        "process_start_ticks": pid * 100,
        "memory_max_bytes": "max",
        "memory_swap_max_bytes": "max",
        "memory_current_bytes": 1024,
        "memory_swap_current_bytes": 0,
        "memory_events_local": {"oom": 0, "oom_kill": 0},
        "memory_events_oom": 0,
        "memory_events_oom_kill": 0,
    }


def _observation(*, nara: str) -> dict[str, Any]:
    residents = [
        _resident("vllm-gemma4", GEMMA_ID, 111),
        _resident("vllm-qwen", QWEN_ID, 222),
    ]
    return {
        "observed_at": (NOW - timedelta(minutes=5)).isoformat(),
        "residents": residents,
        "residents_by_name": {row["name"]: row for row in residents},
        "cgroups_by_name": {
            "vllm-gemma4": _cgroup(GEMMA_ID, 111),
            "vllm-qwen": _cgroup(QWEN_ID, 222),
        },
        "nara": {
            "ActiveState": nara,
            "SubState": "running" if nara == "active" else "dead",
            "MainPID": "333" if nara == "active" else "0",
        },
    }


def _source_map(code_root: Path) -> dict[str, str]:
    source = code_root / "bench/stable_benchmark/supervised_window.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("# frozen controller fixture\n", encoding="utf-8")
    return {str(source.relative_to(code_root)): _sha(source.read_bytes())}


def _registration_arm(
    *, arm_id: str, role: str, manifest: Path, run_dir: Path, lifecycle: Any
) -> dict[str, Any]:
    source = {"bench/stable_benchmark/runner.py": ZERO}
    return {
        "arm_id": arm_id,
        "role": role,
        "manifest": {"path": str(manifest), "sha256": _sha(manifest.read_bytes())},
        "run_receipt_directory": str(run_dir),
        "execution_source_sha256": source,
        "replay_source_sha256": source,
        "admission_source_sha256": source,
        "lifecycle": lifecycle,
    }


def _fake_proc(proc_root: Path, code_root: Path, argv: list[str]) -> tuple[Path, Path]:
    boot = proc_root / "boot_id"
    boot.parent.mkdir(parents=True, exist_ok=True)
    boot.write_text(BOOT_ID + "\n", encoding="ascii")
    process = proc_root / str(PID)
    process.mkdir(parents=True, exist_ok=True)
    # Tokens after ')' begin at Linux proc stat field 3. Index 19 is field 22.
    fields = ["S", *("0" for _ in range(18)), str(TICKS), "0", "0"]
    (process / "stat").write_text(
        f"{PID} (python worker) {' '.join(fields)}\n", encoding="ascii"
    )
    (process / "cmdline").write_bytes(
        b"\0".join(item.encode() for item in argv) + b"\0"
    )
    cwd = process / "cwd"
    cwd.unlink(missing_ok=True)
    cwd.symlink_to(code_root, target_is_directory=True)
    return proc_root, boot


def _memory(
    *, phase: str, initial: dict[str, Any], state: dict[str, Any], age_s: float = 1
) -> dict[str, Any]:
    nara = (
        "inactive"
        if phase in {"nara_quiescing", "evaluation", "restoration"}
        else "active"
    )
    current = copy.deepcopy(initial)
    current["nara"] = {
        "ActiveState": nara,
        "SubState": "dead" if nara == "inactive" else "running",
        "MainPID": "0" if nara == "inactive" else "333",
    }
    return {
        "schema": "flash-next-resident-research-memory-sample/v1",
        "monitor_phase": stable.MONITOR_PHASE[phase],
        "watchdog_sentinel_id": state["watchdog_sentinel_id"],
        "observed_at": (NOW - timedelta(seconds=age_s)).isoformat(),
        "observed_monotonic": 123.0,
        "mem_available_gib": 31.0,
        "host_pswpout_pages": 10,
        "incumbent_ids": [item["id"] for item in current["residents"]],
        "incumbent_restart_counts": {
            item["name"]: item["restart_count"] for item in current["residents"]
        },
        "incumbent_pids": {item["name"]: item["pid"] for item in current["residents"]},
        "incumbent_containers": current["residents"],
        "incumbent_cgroups": current["cgroups_by_name"],
        "nara": current["nara"],
        "incumbent_cgroup_swap_bytes": {
            name: row["memory_swap_current_bytes"]
            for name, row in current["cgroups_by_name"].items()
        },
        "cgroup_swap_capture_status": "exact_incumbent_pid_cgroup_bound",
    }


def _terminal_receipts(
    receipt_dir: Path,
    *,
    state: dict[str, Any],
    plan: dict[str, Any],
    argv: list[str],
) -> None:
    initial = state["initial"]
    final = copy.deepcopy(initial)
    final["watchdog_sentinel_by_name"] = None
    final["watchdog_sentinel_by_id"] = None
    restoration = {
        "status": "verified",
        "errors": [],
        "sentinel_retained": False,
        "final_observation": final,
        "verified_at": NOW.isoformat(),
        "no_mutation_verified": True,
    }
    state.update(phase="failed", result_status="failed", restoration=restoration)
    _write(receipt_dir / "state.json", state)
    result = {key: None for key in rv.RESULT_FIELDS}
    result.update(
        {
            "schema_version": rv.RESULT_SCHEMA,
            "window_id": plan["window_id"],
            "status": "failed",
            "plan_sha256": _sha((receipt_dir / "window.json").read_bytes()),
            "definition_sha256": plan["definition_sha256"],
            "run_manifest_sha256": plan["run_manifest_sha256"],
            "restoration_passed": True,
            "restoration": restoration,
            "production_change_authorized": False,
            "paid_api_calls": 0,
        }
    )
    result_sha = _write(receipt_dir / "result.json", result)
    supervision = {key: None for key in rv.SUPERVISION_FIELDS}
    supervision.update(
        {
            "schema_version": rv.SUPERVISION_SCHEMA,
            "window_id": plan["window_id"],
            "plan_sha256": result["plan_sha256"],
            "command_sha256": _sha(_canonical(argv)),
            "argv": argv,
            "pid": PID,
            "worker_start_ticks": TICKS,
            "boot_id": BOOT_ID,
            "complete": False,
            "emergency_recovery": None,
            "lifecycle_result_sha256": result_sha,
        }
    )
    _write(receipt_dir / "supervision.json", supervision)


def _recovery_receipts(
    receipt_dir: Path,
    *,
    state: dict[str, Any],
    plan: dict[str, Any],
    argv: list[str],
) -> None:
    final = copy.deepcopy(state["initial"])
    final["watchdog_sentinel_by_name"] = None
    final["watchdog_sentinel_by_id"] = None
    restoration = {
        "status": "verified",
        "errors": [],
        "sentinel_retained": False,
        "final_observation": final,
        "verified_at": NOW.isoformat(),
        "no_mutation_verified": False,
    }
    state.update(phase="supervisor_recovered", restoration=restoration)
    _write(receipt_dir / "state.json", state)
    recovery = {
        "schema_version": stable.RECOVERY_SCHEMA,
        "window_id": plan["window_id"],
        "started_at": (NOW - timedelta(seconds=2)).isoformat(),
        "status": "verified",
        "restoration": restoration,
        "error": None,
        "finished_at": (NOW - timedelta(seconds=1)).isoformat(),
    }
    _write(receipt_dir / "supervisor-recovery.json", recovery)
    supervision = {key: None for key in rv.SUPERVISION_FIELDS}
    supervision.update(
        {
            "schema_version": rv.SUPERVISION_SCHEMA,
            "window_id": plan["window_id"],
            "plan_sha256": state["plan_sha256"],
            "command_sha256": _sha(_canonical(argv)),
            "argv": argv,
            "pid": PID,
            "worker_start_ticks": TICKS,
            "boot_id": BOOT_ID,
            "complete": False,
            "emergency_recovery": recovery,
        }
    )
    _write(receipt_dir / "supervision.json", supervision)


def _fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    comparison_id: str = "stable-comparison-a",
    window_id: str = "stable-benchmark-20260916-a.resident",
    registered_at: str = "2026-09-16T06:00:00Z",
    phase: str = "evaluation",
    attempt: bool = True,
    terminal: bool = False,
    memory_age_s: float = 1,
) -> dict[str, Any]:
    repo = tmp_path / "repo"
    program = tmp_path / "program"
    worktrees = tmp_path / "worktrees"
    window_root = tmp_path / "windows"
    code_root = worktrees / f"frozen-{window_id}"
    monkeypatch.setattr(stable, "WINDOW_ROOT", window_root)
    monkeypatch.setattr(stable, "FROZEN_WORKTREE_ROOT", worktrees)

    definition = program / "definition.published.json"
    reference_manifest = (
        program / "manifests" / f"{comparison_id}.resident-stack-v1.json"
    )
    candidate_manifest = program / "manifests" / f"{comparison_id}.flash-stack-v1.json"
    _write(definition, {"fixture": "definition"})
    _write(reference_manifest, {"fixture": "reference"})
    _write(candidate_manifest, {"fixture": "candidate"})
    reference_run = program / "runs" / comparison_id / "resident-stack-v1"
    candidate_run = program / "runs" / comparison_id / "flash-stack-v1"
    receipt_dir = window_root / window_id
    sources = _source_map(code_root)
    launcher = str(code_root / ".venv-chroma/bin/python")
    argv = [
        launcher,
        "-m",
        "bench.stable_benchmark.supervised_window",
        "--worker",
        "--window-id",
        window_id,
        "--run-manifest",
        str(reference_manifest),
    ]
    lifecycle = {
        "window_id": window_id,
        "window_plan_sha256": ZERO,
        "controller_source_sha256": sources,
        "worker_argv_sha256": _sha(_canonical(argv)),
        "receipt_directory": str(receipt_dir),
    }
    registration = {
        "schema_version": rv.REGISTRATION_SCHEMA,
        "suite_id": "stable-benchmark-v1",
        "release": "1.0.0",
        "comparison_id": comparison_id,
        "registered_at": registered_at,
        "definition": {
            "path": str(definition),
            "sha256": _sha(definition.read_bytes()),
        },
        "arms": [
            _registration_arm(
                arm_id="resident-stack-v1",
                role="reference",
                manifest=reference_manifest,
                run_dir=reference_run,
                lifecycle=lifecycle,
            ),
            _registration_arm(
                arm_id="flash-stack-v1",
                role="candidate",
                manifest=candidate_manifest,
                run_dir=candidate_run,
                lifecycle=None,
            ),
        ],
    }
    registration_path = (
        repo / stable.REGISTRATION_ROOT_RELATIVE / f"{comparison_id}.json"
    )

    if attempt:
        initial = _observation(nara="active")
        quiet = _observation(nara="inactive") if phase == "evaluation" else None
        sentinel = "f" * 64 if phase != "preflight" else None
        state = {
            "schema_version": rv.STATE_SCHEMA,
            "window_id": window_id,
            "pair_id": f"qfn-ab-{window_id}",
            "phase": phase,
            "plan_sha256": ZERO,
            "definition_sha256": _sha(definition.read_bytes()),
            "run_manifest_sha256": _sha(reference_manifest.read_bytes()),
            "boot_id": BOOT_ID,
            "worker_pid": PID,
            "worker_start_ticks": TICKS,
            "started_at": (NOW - timedelta(minutes=5)).isoformat(),
            "initial": initial,
            "quiet_observation": quiet,
            "watchdog_sentinel_id": sentinel,
            "nara_stop_attempted": phase
            in {"nara_quiescing", "evaluation", "restoration"},
            "execution_gate_sha256": ZERO if phase == "evaluation" else None,
            "restoration": {"status": "not_started"},
        }
        plan = {
            "schema_version": rv.WINDOW_SCHEMA,
            "window_id": window_id,
            "pair_id": f"qfn-ab-{window_id}",
            "execution_mode": "resident_only",
            "code_root": str(code_root),
            "git_head": "a" * 40,
            "window_dir": str(receipt_dir),
            "run_dir": str(reference_run),
            "definition_path": str(definition),
            "definition_sha256": _sha(definition.read_bytes()),
            "run_manifest_path": str(reference_manifest),
            "run_manifest_sha256": _sha(reference_manifest.read_bytes()),
            "arm_id": "resident-stack-v1",
            "comparison_id": comparison_id,
            "resource_envelope": {"max_supervised_window_s": 7200},
            "window_deadline_seconds": 3600,
            "restoration_reserve_seconds": 600,
            "runner_deadline_seconds": 1800,
            "preflight_min_mem_available_gib": 30,
            "monitor_min_mem_available_gib": 20,
            "monitor_max_sample_gap_seconds": 10,
            "nara_service": "nara-daemon.service",
            "nara_isolation": "stop_if_initially_active_then_restore",
            "resident_container_action": "read_and_verify_only",
            "watchdog_sentinel_name": f"qfn-ab-{window_id}-watchdog",
            "launcher_python_path": launcher,
            "resident_qualification": {"fixture": "qualified"},
            "controller_source_sha256": sources,
            "controller_source_bundle_sha256": _sha(_canonical(sources)),
            "paid_api_allowed": False,
            "production_change_authorized": False,
            "candidate_startup_supported": False,
        }
        plan_sha = _write(receipt_dir / "window.json", plan)
        lifecycle["window_plan_sha256"] = plan_sha
        state["plan_sha256"] = plan_sha
        process = {
            "schema_version": rv.PROCESS_SCHEMA,
            "window_id": window_id,
            "plan_sha256": plan_sha,
            "pid": PID,
            "pgid": PID,
            "worker_start_ticks": TICKS,
            "boot_id": BOOT_ID,
            "argv_sha256": lifecycle["worker_argv_sha256"],
            "started_at": (NOW - timedelta(minutes=5, seconds=1)).isoformat(),
        }
        _write(receipt_dir / "process.json", process)
        _write(receipt_dir / "state.json", state)
        _write(
            receipt_dir / "resident-memory.jsonl",
            _memory(phase=phase, initial=initial, state=state, age_s=memory_age_s),
        )
        proc_root, boot = _fake_proc(tmp_path / "proc", code_root, argv)
        if terminal:
            _terminal_receipts(receipt_dir, state=state, plan=plan, argv=argv)
    else:
        plan = state = None
        proc_root = tmp_path / "proc"
        boot = proc_root / "boot_id"

    # Registration is written last because its lifecycle binds the final plan digest.
    _write(registration_path, registration)
    return {
        "repo": repo,
        "program": program,
        "receipt_dir": receipt_dir,
        "code_root": code_root,
        "registration": registration_path,
        "proc_root": proc_root,
        "boot": boot,
        "plan": plan,
        "state": state,
        "argv": argv,
    }


def _project(fixture: dict[str, Any]) -> dict[str, Any] | None:
    return stable.project_active_stable_runtime(
        repo=fixture["repo"],
        program_root=fixture["program"],
        proc_root=fixture["proc_root"],
        boot_id_path=fixture["boot"],
        observed=NOW,
    )


def test_no_attempted_registered_lifecycle_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    fixture = _fixture(tmp_path, monkeypatch, attempt=False)
    assert _project(fixture) is None


def test_unavailable_catalog_retains_benchmark_unknown_identity(monkeypatch):
    from backend import benchmark_catalog, model_runtime

    def unavailable(_repo):
        raise ValueError("catalog missing")

    monkeypatch.setattr(benchmark_catalog, "read_catalog", unavailable)
    result = model_runtime.project_model_runtime(now=lambda: NOW)
    assert result["mode"] == "unknown"
    assert result["mode_source"] == "stable_benchmark_state"
    assert result["comparison_id"] is None
    assert "catalog" in result["source_error"]


@pytest.mark.parametrize("active_unresolved", [False, True])
def test_switching_release_does_not_hide_unresolved_historical_runtime(monkeypatch, tmp_path, active_unresolved):
    from backend import benchmark_catalog, model_runtime

    roots = {"1.0.0": tmp_path / "old", "1.1.0": tmp_path / "new"}
    monkeypatch.setattr(benchmark_catalog, "read_catalog", lambda _repo: {
        "active_release": "1.1.0",
        "releases": [{"version": version, "root": str(root)} for version, root in roots.items()],
    })

    def project(**kwargs):
        if kwargs["program_root"] == roots["1.0.0"]:
            return stable._unknown(NOW, "Historical restoration is unverified", comparison_id="old-comparison")
        return stable._unknown(NOW, "Current restoration is unverified") if active_unresolved else None

    monkeypatch.setattr(stable, "project_active_stable_runtime", project)
    result = model_runtime.project_model_runtime(now=lambda: NOW)
    assert result["mode"] == "unknown"
    assert result["mode_source"] == "stable_benchmark_state"
    if active_unresolved:
        assert "Multiple" in result["source_error"]
    else:
        assert result["comparison_id"] == "old-comparison"


def test_other_release_registration_does_not_hide_active_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    fixture = _fixture(tmp_path, monkeypatch, phase="evaluation")
    historical = json.loads(fixture["registration"].read_text())
    historical["comparison_id"] = "historical-release"
    historical["registered_at"] = NOW.isoformat().replace("+00:00", "Z")
    historical["definition"] = {
        "path": str(tmp_path / "historical" / "definition.published.json"),
        "sha256": "d" * 64,
    }
    _write(fixture["registration"].with_name("historical-release.json"), historical)
    projected = _project(fixture)
    assert projected is not None
    assert projected["mode"] == "resident", projected.get("source_error")
    assert projected["comparison_id"] == "stable-comparison-a"


def test_selected_definition_registered_at_wrong_path_remains_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    fixture = _fixture(tmp_path, monkeypatch, phase="evaluation")
    misplaced = json.loads(fixture["registration"].read_text())
    misplaced["comparison_id"] = "misplaced-selected-release"
    misplaced["definition"]["path"] = str(tmp_path / "wrong" / "definition.published.json")
    _write(fixture["registration"].with_name("misplaced-selected-release.json"), misplaced)
    projected = _project(fixture)
    assert projected is not None
    assert projected["mode"] == "unknown"


@pytest.mark.parametrize(
    ("phase", "nara"), (("preflight", "running"), ("evaluation", "paused"))
)
def test_live_registered_window_projects_resident_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str, nara: str
):
    fixture = _fixture(tmp_path, monkeypatch, phase=phase)
    projected = _project(fixture)
    assert projected is not None
    assert projected["schema_version"] == "model-runtime/v1"
    assert projected["mode_source"] == "stable_benchmark_state"
    assert projected["mode"] == "resident"
    assert projected["resident_services_expected"] == "online"
    assert projected["nara_service_expected"] == nara
    assert projected["comparison_id"] == "stable-comparison-a"
    assert projected["run_id"] == "stable-benchmark-20260916-a.resident"
    assert projected["phase"] == phase
    assert len(projected["mode_source_sha256"]) == 64


@pytest.mark.parametrize(
    "break_evidence",
    (
        lambda fixture: (
            fixture["code_root"] / "bench/stable_benchmark/supervised_window.py"
        ).write_text("drift\n"),
        lambda fixture: (fixture["proc_root"] / str(PID) / "stat").unlink(),
        lambda fixture: (fixture["proc_root"] / str(PID) / "cmdline").write_bytes(
            b"wrong\0"
        ),
        lambda fixture: (
            (fixture["proc_root"] / str(PID) / "cwd").unlink(),
            (fixture["proc_root"] / str(PID) / "cwd").symlink_to(
                fixture["repo"], target_is_directory=True
            ),
        ),
        lambda fixture: (
            os.utime(
                fixture["receipt_dir"] / "resident-memory.jsonl",
                None,
            )
            or (fixture["receipt_dir"] / "resident-memory.jsonl").write_bytes(
                _canonical(
                    _memory(
                        phase="evaluation",
                        initial=fixture["state"]["initial"],
                        state=fixture["state"],
                        age_s=30,
                    ),
                    newline=True,
                )
            )
        ),
    ),
    ids=("source-drift", "dead-worker", "argv-drift", "cwd-drift", "stale-monitor"),
)
def test_active_window_identity_or_freshness_failure_is_unknown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    break_evidence: Callable[[dict[str, Any]], Any],
):
    fixture = _fixture(tmp_path, monkeypatch)
    break_evidence(fixture)
    projected = _project(fixture)
    assert projected is not None
    assert projected["mode"] == "unknown"
    assert projected["mode_source"] == "stable_benchmark_state"
    assert projected["nara_service_expected"] == "unknown"


def test_newer_invalid_attempt_blocks_older_live_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    older = _fixture(
        tmp_path,
        monkeypatch,
        comparison_id="stable-comparison-a",
        window_id="stable-benchmark-20260916-a.resident",
        registered_at="2026-09-16T05:00:00Z",
    )
    newer = _fixture(
        tmp_path,
        monkeypatch,
        comparison_id="stable-comparison-b",
        window_id="stable-benchmark-20260916-b.resident",
        registered_at="2026-09-16T06:00:00Z",
    )
    (newer["receipt_dir"] / "state.json").unlink()
    future = NOW.timestamp() + 10
    os.utime(newer["receipt_dir"], (future, future))
    projected = _project(older)
    assert projected is not None
    assert projected["mode"] == "unknown"
    assert projected["comparison_id"] == "stable-comparison-b"
    assert projected["run_id"] == "stable-benchmark-20260916-b.resident"


def test_old_directory_touch_cannot_outrank_newer_registered_live_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    older = _fixture(
        tmp_path,
        monkeypatch,
        comparison_id="stable-comparison-a",
        window_id="stable-benchmark-20260916-a.resident",
        registered_at="2026-09-16T05:00:00Z",
    )
    newer = _fixture(
        tmp_path,
        monkeypatch,
        comparison_id="stable-comparison-b",
        window_id="stable-benchmark-20260916-b.resident",
        registered_at="2026-09-16T06:00:00Z",
    )
    future = NOW.timestamp() + 60
    os.utime(older["receipt_dir"], (future, future))
    os.utime(older["receipt_dir"] / "state.json", (future, future))

    projected = _project(newer)
    assert projected is not None
    assert projected["mode"] == "resident"
    assert projected["comparison_id"] == "stable-comparison-b"
    assert projected["run_id"] == "stable-benchmark-20260916-b.resident"


def test_verified_terminal_restoration_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    fixture = _fixture(tmp_path, monkeypatch, terminal=True)
    assert _project(fixture) is None


def test_verified_parent_recovery_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    fixture = _fixture(tmp_path, monkeypatch)
    _recovery_receipts(
        fixture["receipt_dir"],
        state=fixture["state"],
        plan=fixture["plan"],
        argv=fixture["argv"],
    )
    assert _project(fixture) is None


def test_unverified_recovery_remains_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    fixture = _fixture(tmp_path, monkeypatch)
    state = fixture["state"]
    state["phase"] = "recovery_unknown"
    state["restoration"] = {"status": "unknown"}
    _write(fixture["receipt_dir"] / "state.json", state)
    projected = _project(fixture)
    assert projected is not None
    assert projected["mode"] == "unknown"
    assert projected["phase"] == "recovery_unknown"
