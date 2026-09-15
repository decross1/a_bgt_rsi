"""The newest bound controller state owns Pulse mode during a Flash pair run."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend import model_runtime as mr
from backend import model_runtime_extended as extended
from bench.flash_next_ab import evaluation_window as ew
from bench.flash_next_ab.candidate_registry import MIA

NOW = datetime(2026, 9, 15, 7, 0, tzinfo=timezone.utc)


def state_slot(root: Path, run_id: str, recorded_ns: int, *, raw: bytes = b"{}") -> Path:
    run = root / run_id
    run.mkdir(parents=True)
    state = run / "state.json"
    state.write_bytes(raw)
    os.utime(state, ns=(recorded_ns, recorded_ns))
    os.utime(run, ns=(recorded_ns, recorded_ns))
    return state


def selected(qualification_root: Path, evaluation_root: Path):
    return extended.maybe_project_extended(
        qualification_root, evaluation_root,
        proc_root=Path("/proc"), boot_id_path=Path("/proc/boot-fixture"),
        observed=NOW,
    )


def test_newer_registered_pair_state_selects_extended_window(tmp_path, monkeypatch):
    qroot, eroot = tmp_path / "qualification-runs", tmp_path / "evaluation-runs"
    state_slot(qroot, "qfn-mia-c0-old", 100)
    state_slot(eroot, "qfn-ab-first-pair.flash", 200)
    called = []

    def projector(root, **kwargs):
        called.append(root)
        return {"mode": "candidate_research", "mode_source": "extended_evaluation_state"}

    monkeypatch.setattr(extended, "project_extended_runtime", projector)
    assert selected(qroot, eroot)["mode_source"] == "extended_evaluation_state"
    assert called == [eroot]


def test_older_extended_history_does_not_replace_new_qualification(tmp_path, monkeypatch):
    qroot, eroot = tmp_path / "qualification-runs", tmp_path / "evaluation-runs"
    state_slot(qroot, "qfn-mia-c0-new", 300)
    state_slot(eroot, "qfn-ab-earlier.flash", 200)
    monkeypatch.setattr(
        extended, "project_extended_runtime",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("older source selected")),
    )
    assert selected(qroot, eroot) is None


def test_older_pair_sidecar_does_not_make_its_state_current(tmp_path, monkeypatch):
    qroot, eroot = tmp_path / "qualification-runs", tmp_path / "evaluation-runs"
    state_slot(qroot, "qfn-mia-c0-new", 300)
    old_state = state_slot(eroot, "qfn-ab-earlier.flash", 200)
    (old_state.parent / "observer-summary.json").write_text("{}")
    os.utime(old_state.parent, ns=(400, 400))
    monkeypatch.setattr(
        extended, "project_extended_runtime",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("old pair selected")),
    )
    assert selected(qroot, eroot) is None


def test_newer_malformed_pair_state_blocks_old_resident_fallback(tmp_path):
    qroot, eroot = tmp_path / "qualification-runs", tmp_path / "evaluation-runs"
    state_slot(qroot, "qfn-mia-c0-old", 100)
    state_slot(eroot, "qfn-ab-newer.flash", 200, raw=b"{bad JSON")
    projection = selected(qroot, eroot)
    assert projection["mode"] == "unknown"
    assert projection["mode_source"] == "none"
    assert projection["resident_services_expected"] == "unknown"


def test_state_order_change_during_admission_fails_closed(tmp_path, monkeypatch):
    qroot, eroot = tmp_path / "qualification-runs", tmp_path / "evaluation-runs"
    old = state_slot(qroot, "qfn-mia-c0-old", 100)
    state_slot(eroot, "qfn-ab-running.flash", 200)

    def projector(*args, **kwargs):
        os.utime(old, ns=(300, 300))
        os.utime(old.parent, ns=(300, 300))
        return {"mode": "candidate_research", "mode_source": "extended_evaluation_state"}

    monkeypatch.setattr(extended, "project_extended_runtime", projector)
    projection = selected(qroot, eroot)
    assert projection["mode"] == "unknown"
    assert projection["mode_source"] == "none"


def test_redirected_registered_pair_child_is_untrusted(tmp_path):
    qroot, eroot = tmp_path / "qualification-runs", tmp_path / "evaluation-runs"
    state_slot(qroot, "qfn-mia-c0-old", 100)
    eroot.mkdir()
    (eroot / "qfn-ab-redirect.flash").symlink_to(qroot / "qfn-mia-c0-old")
    projection = selected(qroot, eroot)
    assert projection["mode"] == "unknown"
    assert projection["mode_source"] == "none"


def active_sources(tmp_path, monkeypatch, *, mutate=None):
    pair_id = "qfn-ab-mia-bound"
    run_id = pair_id + ".flash"
    root = tmp_path / "evaluation-runs"
    run = root / run_id
    run.mkdir(parents=True)
    window_root = tmp_path / "window-plans"
    window_root.mkdir()
    monkeypatch.setattr(ew, "WINDOW_PLAN_ROOT", window_root)
    window_path = window_root / f"{pair_id}.flash.window.json"
    window = SimpleNamespace(
        pair_id=pair_id, cohort="flash", source_path=window_path,
        source_sha256="a" * 64,
        qualification_plan={
            "paging_policy": MIA.paging_policy(), "ready_quiescence_seconds": 60,
            "docker_memory_limit_bytes": MIA.docker_memory_limit_bytes,
            "image_id": MIA.image_id,
        },
    )
    prior = window.qualification_plan
    contract = {"profile": MIA.profile, "runtime": {"memory": MIA.docker_memory_limit_bytes}}
    contract_raw = json.dumps(contract).encode()
    contract_sha = hashlib.sha256(contract_raw).hexdigest()
    profile = ew.EXTENDED_SERVING_PROFILE
    plan = {
        "schema_version": extended.EXTENDED_PLAN_SCHEMA,
        "pair_id": pair_id, "candidate_variant_id": MIA.spec_id,
        "candidate_spec_sha256": MIA.identity_sha256(),
        "model_artifact_sha256": MIA.model_artifact_sha256(),
        "window_plan_sha256": window.source_sha256,
        "prior_qualification_receipt_sha256": "d" * 64,
        "controller_source_bundle_sha256": "b" * 64,
        "contract_sha256": contract_sha,
        "extended_serving_profile": profile,
        "extended_serving_profile_sha256": mr._canonical_sha256(profile),
        "effective_invocation_deadline_seconds": ew.WINDOW_DEADLINE_SECONDS,
        "launcher_python_path": "/usr/bin/python3.12",
    }
    if mutate == "variant_plan":
        plan["candidate_spec_sha256"] = "0" * 64
    started = NOW.replace(hour=6, minute=55)
    state = {
        "schema": extended.EXTENDED_STATE_SCHEMA, "run_id": run_id,
        "pair_id": pair_id, "phase": "evaluation", "memory_log_relpath": "memory.jsonl",
        "plan_sha256": mr._canonical_sha256(prior),
        "extended_plan_sha256": mr._canonical_sha256(plan),
        "window_plan_path": str(window_path),
        "window_plan_sha256": window.source_sha256,
        "prior_qualification_receipt_sha256": plan["prior_qualification_receipt_sha256"],
        "controller_source_bundle_sha256": plan["controller_source_bundle_sha256"],
        "extended_serving_profile": profile,
        "extended_serving_profile_sha256": plan["extended_serving_profile_sha256"],
        "contract_sha256": contract_sha,
        "candidate": {"id": MIA.spec_id, "spec_sha256": MIA.identity_sha256()},
        "boot_id": "boot-fixture" if mutate != "old_boot" else "other-boot",
        "started_at": started.isoformat(), "updated_at": NOW.isoformat(),
        "invocation_deadline_at": (
            started + timedelta(seconds=ew.WINDOW_DEADLINE_SECONDS)
        ).isoformat(),
        "worker_pid": 4242, "worker_start_ticks": 987654,
        "monitor_phase": "evaluation",
        "paging_policy": MIA.paging_policy(),
        "candidate_id": "c" * 64,
        "candidate_cgroup_path": f"/system.slice/docker-{'c' * 64}.scope",
        "candidate_cgroup_pid": 300, "candidate_cgroup_start_ticks": 4444,
        "initial": {"nara_was_active": True, "residents": [
            {"name": "vllm-gemma4", "id": "fc61a80d6c2d07b551c5afdd566a7c82ee05ad40c014d69c428e299e49101374", "running": True},
            {"name": "vllm-qwen", "id": "bcb6cd87757279ff77f1460cab2f8ad6cf1a2e46d19dad165b07dccecfa509bb", "running": True},
        ]},
        "ready_quiescence": {
            "required_seconds": 60, "passed": True,
            "started_at": NOW.replace(minute=58, hour=6, second=59).isoformat(),
            "completed_at": NOW.replace(minute=59, hour=6, second=59).isoformat(),
            "duration_seconds": 60.0,
            "initial_pswpout_pages": 10, "final_pswpout_pages": 10,
            "samples": 61, "epoch": 1,
        },
    }
    if mutate == "plan_state":
        state["extended_plan_sha256"] = "0" * 64
    for name, value in (
        ("state.json", state), ("extended-plan.json", plan),
        ("prior-c0-plan.snapshot.json", prior),
        ("launch-contract.snapshot.json", contract),
    ):
        (run / name).write_text(json.dumps(value))
    (run / "launch-contract.raw.json").write_bytes(contract_raw)
    boot = tmp_path / "boot-id"
    boot.write_text("boot-fixture\n")
    monkeypatch.setattr(ew, "load_evaluation_window", lambda path, **kwargs: window)
    monkeypatch.setattr(ew, "build_extended_evaluation_plan", lambda source, path: plan)
    monkeypatch.setattr(extended, "_validate_worker", lambda *args: None)
    if mutate == "stale_memory":
        monkeypatch.setattr(
            mr, "_latest_memory", lambda *args, **kwargs: (_ for _ in ()).throw(
                mr.RuntimeSourceError("memory source stale")),
        )
    else:
        monkeypatch.setattr(mr, "_latest_memory", lambda *args, **kwargs: ({}, "e" * 64))
    return root, boot


@pytest.mark.parametrize("mutation,expected", [
    (None, "candidate_research"), ("variant_plan", "unknown"),
    ("plan_state", "unknown"), ("old_boot", "unknown"),
    ("stale_memory", "unknown"),
])
def test_extended_active_mode_requires_registered_sources_and_fresh_memory(
    tmp_path, monkeypatch, mutation, expected,
):
    root, boot = active_sources(tmp_path, monkeypatch, mutate=mutation)
    row = extended.project_extended_runtime(
        root, proc_root=tmp_path / "proc", boot_id_path=boot, observed=NOW,
    )
    assert row["mode"] == expected
    if expected == "candidate_research":
        assert row["mode_source"] == "extended_evaluation_state"
        assert row["phase"] == "evaluation"
        assert row["candidate_variant"]["spec_id"] == MIA.spec_id
        assert row["candidate_variant"]["image_evidence"] == "bound_live_container"
        assert row["resident_services_expected"] == "stopped"
    else:
        assert row["mode_source"] == "none"
        assert row["candidate_variant"] is None
