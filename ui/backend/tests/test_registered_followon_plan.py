"""Canonical UI import and frozen follow-on source path regression tests.

These tests are prepared off-tree and must run only after the live Flash window
restores. They launch no model or endpoint request.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend import model_runtime as mr
from backend import model_runtime_followon as flash
from backend import registered_followon_plan as registered

RESEARCH_ROOT = Path(
    "/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-14/"
    "qwen-flash-next-research"
)
WINDOW_ID = "qfn-followon-c0-pilot-20260915-a"


def _source(cohort: str) -> Path:
    return (RESEARCH_ROOT / "evaluation/followon-window-plans" /
            f"{WINDOW_ID}.{cohort}.json")


def _output(cohort: str) -> Path:
    return (RESEARCH_ROOT / "evaluation/followon-runs" /
            f"{WINDOW_ID}.{cohort}")


def test_canonical_import_path_drift_fails_direct_plan_but_registered_worker_passes(
    monkeypatch,
):
    """Exact frozen Flash block paths are worktree paths, not canonical paths."""
    from bench.flash_next_ab import followon_plans as plans
    from bench.flash_next_ab import followon_thinking as thinking

    canonical_root = Path("/home/decross1/projects/a_bgt_rsi")
    monkeypatch.setattr(thinking, "REPO_ROOT", canonical_root)
    monkeypatch.setattr(
        thinking, "SOURCE_MANIFEST",
        canonical_root / "experiments/weekly_role_effort_v1_2026-09-14.json",
    )
    with pytest.raises(ValueError, match="source|policies|bindings"):
        plans.load_execution(_source("flash"), cohort="flash")

    # The isolated worker imports from the exact registered worktree and
    # checks the same source without touching backend sys.path/module globals.
    admitted = registered.registered_expected(
        _source("flash"), _output("flash"), cohort="flash",
    )
    raw = _source("flash").read_bytes()
    frozen = json.loads(raw)
    assert admitted["source_sha256"] == mr._sha256(raw)
    assert admitted["document"] == frozen
    assert admitted["plan"]["output_dir"] == str(_output("flash"))
    assert admitted["plan"]["controller_source_bundle"] == frozen[
        "followon_source_bundle"
    ]


def test_registered_worker_rejects_block_raw_sha_drift_before_cache_lookup(
    monkeypatch,
):
    """A previously cached plan never masks changed frozen block bytes."""
    frozen = json.loads(_source("resident").read_bytes())
    target = Path(frozen["blocks"][0]["plan_path"])
    original = mr._read_path

    def changed(path, *, maximum, label):
        if Path(path) == target:
            return b"{}"
        return original(path, maximum=maximum, label=label)

    monkeypatch.setattr(mr, "_read_path", changed)
    with pytest.raises(mr.RuntimeSourceError, match="block source bytes changed"):
        registered.registered_expected(
            _source("resident"), _output("resident"), cohort="resident",
        )


def test_registered_worker_rejects_prior_qualification_drift_before_cache_lookup(
    monkeypatch,
):
    """A cached live plan cannot mask changed qualified parent bytes."""
    frozen = json.loads(_source("flash").read_bytes())
    parent = json.loads(Path(
        frozen["qualified_parent_window"]["path"]
    ).read_bytes())
    target = Path(parent["qualification"]["receipt"]["path"])
    original = mr._read_path

    def changed(path, *, maximum, label):
        if Path(path) == target:
            return b"{}"
        return original(path, maximum=maximum, label=label)

    monkeypatch.setattr(mr, "_read_path", changed)
    with pytest.raises(mr.RuntimeSourceError,
                       match="qualified receipt bytes changed"):
        registered.registered_expected(
            _source("flash"), _output("flash"), cohort="flash",
        )


def test_registered_worker_rejects_bundle_drift_before_cache_lookup(monkeypatch):
    from bench.flash_next_ab import followon_dispatch as grouped

    original = grouped.frozen_followon_source_bundle

    def changed():
        bundle = original()
        first = next(iter(bundle))
        bundle[first] = dict(bundle[first], sha256="0" * 64)
        return bundle

    monkeypatch.setattr(grouped, "frozen_followon_source_bundle", changed)
    with pytest.raises(mr.RuntimeSourceError, match="registered follow-on source bytes differ"):
        registered.registered_expected(
            _source("flash"), _output("flash"), cohort="flash",
        )


def test_canonical_backend_projects_captured_flash_evaluation_with_exact_bind(
    monkeypatch, tmp_path,
):
    """A real sample → bind event → armed sample admits the live Mia viewport."""
    fixture = Path("/tmp/flash-resident-runtime-20260915")
    run_path = _output("flash")
    run_id = run_path.name
    state_raw = (fixture / "flash-active-state.snapshot.json").read_bytes()
    state = json.loads(state_raw)
    memory_raw = (
        fixture / "flash-producer-shaped-memory.snapshot.jsonl"
    ).read_bytes()
    latest = json.loads(memory_raw.splitlines()[-1])
    observed = datetime.fromisoformat(latest["observed_at"]).astimezone(
        timezone.utc
    )
    read_original = mr._read_fd

    def frozen_read(fd, name, *, maximum, label):
        if name == "state.json":
            return state_raw
        if name == "memory.jsonl":
            return memory_raw
        return read_original(fd, name, maximum=maximum, label=label)

    def frozen_open(_root, *, namespace):
        assert namespace == flash.FOLLOWON_FLASH_RUN_ID
        return os.open(run_path, os.O_RDONLY | os.O_DIRECTORY), run_id, state_raw

    monkeypatch.setattr(mr, "_read_fd", frozen_read)
    monkeypatch.setattr(mr, "_open_latest_run", frozen_open)
    boot = tmp_path / "boot"
    boot.write_text(state["boot_id"])
    process = tmp_path / "proc" / str(state["worker_pid"])
    process.mkdir(parents=True)
    (process / "stat").write_text(
        f"{state['worker_pid']} (Flash worker) R "
        + " ".join(["0"] * 18 + [str(state["worker_start_ticks"]), "0"])
    )
    plan = json.loads((fixture / "flash-active-plan.snapshot.json").read_text())
    command = [
        plan["launcher_python_path"], "-m",
        "bench.flash_next_ab.extended_lifecycle", "--worker",
        "--eval-plan", str(_source("flash")),
        "--output-dir", str(run_path),
    ]
    (process / "cmdline").write_bytes("\0".join(command).encode() + b"\0")
    projected = flash.project_followon_runtime(
        _output("flash").parent, proc_root=tmp_path / "proc",
        boot_id_path=boot, observed=observed,
    )
    assert projected["mode"] == "candidate_research"
    assert projected["phase"] == "evaluation"
    assert projected["resident_services_expected"] == "stopped"
    assert projected["nara_service_expected"] == "paused"
    assert projected["candidate_variant"]["spec_id"] == (
        "mia-925d7be6-c0-s1"
    )
