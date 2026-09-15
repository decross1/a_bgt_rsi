"""Lab operating-mode claims require source and process identity, not task flags."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend import model_runtime_lab as lab
from backend.model_runtime import RuntimeSourceError


def _process(tmp_path: Path, ticks: int = 12345):
    proc = tmp_path / "proc"
    process = proc / "4321"
    process.mkdir(parents=True)
    stat = "4321 (python) " + " ".join(["S"] + ["0"] * 18 + [str(ticks)])
    (process / "stat").write_text(stat)
    window = tmp_path / "qfn-ab-lab.flash" / "window.json"
    window.parent.mkdir()
    argv = ["/registered/venv/python", "-m", "bench.flash_next_ab.lab_window",
            "--worker", "--window", str(window)]
    (process / "cmdline").write_bytes("\0".join(argv).encode() + b"\0")
    (process / "cwd").symlink_to(lab.CODE_ROOT, target_is_directory=True)
    boot = tmp_path / "boot_id"
    boot.write_text("boot-1\n")
    state = {"worker_pid": 4321, "worker_start_ticks": ticks,
             "boot_id": "boot-1", "window_sha256": "a" * 64}
    start = {"pid": 4321, "worker_pid": 4321, "worker_start_ticks": ticks,
             "boot_id": "boot-1", "window_sha256": "a" * 64, "argv": argv}
    return proc, boot, window, state, start


def test_worker_requires_live_start_ticks_boot_and_exact_command(tmp_path: Path):
    proc, boot, window, state, start = _process(tmp_path)
    lab._worker(state, start, window, proc, boot)
    state["worker_start_ticks"] += 1
    with pytest.raises(RuntimeSourceError):
        lab._worker(state, start, window, proc, boot)
    state["worker_start_ticks"] -= 1
    (proc / "4321" / "cmdline").write_bytes(b"python\0unbound\0")
    with pytest.raises(RuntimeSourceError):
        lab._worker(state, start, window, proc, boot)


def test_candidate_process_must_still_be_in_exact_cgroup(tmp_path: Path):
    proc, _, _, _, _ = _process(tmp_path)
    group = "/system.slice/docker-" + "a" * 64 + ".scope"
    (proc / "4321" / "cgroup").write_text("0::" + group + "\n")
    lab._candidate_process(4321, 12345, group, proc)
    (proc / "4321" / "cgroup").write_text("0::/wrong\n")
    with pytest.raises(RuntimeSourceError):
        lab._candidate_process(4321, 12345, group, proc)


def test_evaluator_bundle_is_exact_and_rehashed(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(lab, "CODE_ROOT", tmp_path)
    refs = {}
    for name in lab.PRIMARY_EVALUATOR_FILES:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(name.encode())
        refs[name] = hashlib.sha256(name.encode()).hexdigest()
    plan = {"evaluator_source_bundle": refs}
    lab._evaluator_sources(plan, "primary")
    with pytest.raises(RuntimeSourceError):
        lab._evaluator_sources({"evaluator_source_bundle": dict(list(refs.items())[:-1])}, "primary")
    path = tmp_path / next(iter(refs))
    path.write_bytes(b"changed source")
    with pytest.raises(RuntimeSourceError):
        lab._evaluator_sources(plan, "primary")


def test_invalid_newest_lab_state_is_not_skipped(tmp_path: Path):
    older = tmp_path / "qfn-ab-older.flash"
    newer = tmp_path / "qfn-ab-newer.resident"
    older.mkdir(); newer.mkdir()
    (older / "state.json").write_text("{}")
    (newer / "state.json").write_text("not JSON")
    assert lab._slot(tmp_path) is not None
    assert lab._slot(tmp_path) >= (newer / "state.json").stat().st_mtime_ns


def test_prepared_unsupervised_window_does_not_replace_live_residents(tmp_path: Path):
    child = tmp_path / "qfn-ab-prepared.flash"
    child.mkdir()
    (child / "window.json").write_text("{}")
    assert lab._slot(tmp_path) is None
    (child / "supervision-start.json").write_text("untrusted")
    assert lab._slot(tmp_path) is not None


def test_producer_shaped_preflight_requires_bound_window_plan_and_worker(tmp_path: Path, monkeypatch):
    artifact = tmp_path / "artifacts"
    root = artifact / "model-windows"
    run = root / "qfn-ab-lab-primary-20260915-a.flash"
    run.mkdir(parents=True)
    plan_path = artifact / "plans" / "plan.json"
    plan_path.parent.mkdir()
    plan_path.write_text(json.dumps({"schema_version": "lab-model-eval-plan/v1",
                                     "evaluator_source_bundle": {}}))
    monkeypatch.setattr(lab, "ARTIFACT_ROOT", artifact)
    monkeypatch.setattr(lab, "WINDOW_ROOT", root)
    monkeypatch.setattr(lab, "_sources", lambda _: "b" * 64)
    monkeypatch.setattr(lab, "_evaluator_sources", lambda *_: "c" * 64)
    parent_sha = hashlib.sha256(lab.PARENT_PATH.read_bytes()).hexdigest()
    window = {
        "schema": "lab-model-window/v1", "window_id": "qfn-ab-lab-primary-20260915-a",
        "cohort": "flash", "evaluation_kind": "primary", "output_dir": str(run),
        "code_root": str(lab.CODE_ROOT), "runtime_certificate": {
            "path": str(lab.PARENT_PATH), "sha256": parent_sha},
        "candidate_spec_id": lab.SPEC_ID, "candidate_spec_sha256": lab.SPEC_SHA,
        "restoration_reserve_s": 600, "minimum_mem_available_gib": 20,
        "runtime_budget_s": 7200, "wall_s": 10000, "promotion_authorized": False,
        "evaluation_plan": {"path": str(plan_path),
                            "sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest()},
        "controller_sources": {},
    }
    window_path = run / "window.json"
    window_path.write_text(json.dumps(window))
    window_sha = hashlib.sha256(window_path.read_bytes()).hexdigest()
    proc, boot, _, state, start = _process(tmp_path)
    # The worker command is for this exact immutable registered window.
    argv = ["/registered/venv/python", "-m", "bench.flash_next_ab.lab_window",
            "--worker", "--window", str(window_path)]
    (proc / "4321" / "cmdline").write_bytes("\0".join(argv).encode() + b"\0")
    state.update(phase="preflight", started_at=datetime.now(timezone.utc).isoformat(),
                 window_sha256=window_sha)
    start.update(argv=argv, window_sha256=window_sha,
                 started_at=datetime.now(timezone.utc).isoformat())
    (run / "state.json").write_text(json.dumps(state))
    (run / "supervision-start.json").write_text(json.dumps(start))
    projected = lab.project_lab_runtime(root, proc_root=proc, boot_id_path=boot,
                                         observed=datetime.now(timezone.utc))
    assert projected["mode"] == "transitioning"
    assert projected["mode_source"] == "lab_evaluation_state"
    assert projected["phase"] == "preflight"
    assert projected["source_error"] is None
    window["evaluation_plan"]["sha256"] = "d" * 64
    window_path.write_text(json.dumps(window))
    projected = lab.project_lab_runtime(root, proc_root=proc, boot_id_path=boot,
                                         observed=datetime.now(timezone.utc))
    assert projected["mode"] == "unknown"
    assert projected["mode_source_sha256"] is None

    # A fully re-sealed context plan cannot borrow the primary window's
    # larger call budget. The controller's context cap is 6,000 seconds.
    plan_path.write_text(json.dumps({"schema_version": "lab-model-context-plan/v1",
                                     "evaluator_source_bundle": {}}))
    window["evaluation_kind"] = "context"
    window["runtime_budget_s"] = 6000
    window["evaluation_plan"]["sha256"] = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    window_path.write_text(json.dumps(window))
    resealed = hashlib.sha256(window_path.read_bytes()).hexdigest()
    state["window_sha256"] = resealed
    start["window_sha256"] = resealed
    (run / "state.json").write_text(json.dumps(state))
    (run / "supervision-start.json").write_text(json.dumps(start))
    projected = lab.project_lab_runtime(root, proc_root=proc, boot_id_path=boot,
                                         observed=datetime.now(timezone.utc))
    assert projected["mode"] == "transitioning"
    window["runtime_budget_s"] = 6001
    window_path.write_text(json.dumps(window))
    resealed = hashlib.sha256(window_path.read_bytes()).hexdigest()
    state["window_sha256"] = resealed
    start["window_sha256"] = resealed
    (run / "state.json").write_text(json.dumps(state))
    (run / "supervision-start.json").write_text(json.dumps(start))
    projected = lab.project_lab_runtime(root, proc_root=proc, boot_id_path=boot,
                                         observed=datetime.now(timezone.utc))
    assert projected["mode"] == "unknown"
