"""Host-free checks for the prospective qualified Mia game-pilot wrapper."""
from __future__ import annotations

import contextlib
import json
import signal
import time
from types import SimpleNamespace

import pytest

from experiments.known_opponent_utility import mia_controller as c


@pytest.mark.canonical_corpus(
    c.PARENT_PATH,
    c.GEMMA_ROOT / "admission.json",
    c.GEMMA_ROOT / "manifest.snapshot.json",
    c.GEMMA_ROOT / "pilot/run.json",
    c.GEMMA_ROOT / "window.json",
    c.GEMMA_ROOT / "result.json",
    c.GEMMA_ROOT / "supervision.json",
)
def test_real_parent_preparation_roundtrips_exact_gemma_fixture_and_source(monkeypatch, tmp_path):
    """This is a read-only parent replay and plan freeze; it contacts no model."""
    monkeypatch.setenv("MOCK_LLM", "1")
    monkeypatch.setattr(c, "REGISTERED_ROOT", c.CODE_ROOT)
    monkeypatch.setattr(c, "OUTPUT_ROOT", tmp_path / "mia")
    path = c.prepare(window_id="qfn-followon-known-opponent-mia-test-a", seed=301)
    window, manifest, parent = c.load_window(path)
    assert window["qualified_parent"]["candidate_spec_id"] == c.PROFILE_ID
    assert manifest["schedule"] == c._gemma_reference()[1]["schedule"]
    assert manifest["tasks"] == c._gemma_reference()[1]["tasks"]
    assert manifest["policy"] == c.POLICY
    assert parent.spec.image_id == c.PROFILE_IMAGE_ID
    tampered = json.loads(path.read_text())
    tampered["policy"] = {**c.POLICY, "temperature": 0.2}
    path.write_bytes(c.pilot._raw_json(tampered) + b"\n")
    with pytest.raises(c.MiaStudyError, match="model, admission or sampling differs"):
        c.load_window(path)


def test_prepare_rejects_unregistered_root_before_parent_replay(monkeypatch):
    monkeypatch.setattr(c, "REGISTERED_ROOT", c.CODE_ROOT / "unregistered")
    monkeypatch.setattr(c, "load_parent", lambda _path: pytest.fail(
        "unregistered root reached external parent replay"))
    with pytest.raises(c.MiaStudyError, match="root or ID is not registered"):
        c.prepare(window_id="qfn-followon-known-opponent-mia-test-root")


def _executor_fixture(monkeypatch, tmp_path, *, candidate_image: str):
    output = tmp_path / "window"
    output.mkdir()
    for name in ("window.json", "readiness.json", "probes.json", "manifest.snapshot.json"):
        (output / name).write_text("{}\n")
    state = {"phase": "probes", "candidate_id": "f" * 64,
             "initial": {"residents": []}, "canaries": {"status": "passed"}}
    parent = SimpleNamespace(
        spec=SimpleNamespace(container_name="candidate", image_id=c.PROFILE_IMAGE_ID),
        source_sha256="a" * 64,
        qualification_summary={"schema_version": "flash-next-qualification-validation/v3"},
    )
    window = {"manifest": {"path": str(output / "manifest.snapshot.json")}}
    monitor = SimpleNamespace(ops=object(), check=lambda: None,
                              cancel_event=SimpleNamespace(is_set=lambda: False))
    monkeypatch.setattr(c.q, "_inspect_container", lambda *_args: {
        "id": "f" * 64, "image": candidate_image, "running": True,
        "oom_killed": False, "restart_count": 0,
    })
    monkeypatch.setattr(c.q, "_service_state", lambda *_args: {"ActiveState": "inactive"})
    return window, parent, output, monitor, state


def test_bad_live_candidate_blocks_pilot_before_first_model_call(monkeypatch, tmp_path):
    window, parent, output, monitor, state = _executor_fixture(
        monkeypatch, tmp_path, candidate_image="wrong-image")
    invoked = []
    monkeypatch.setattr(c.pilot, "run_pilot", lambda *_args, **_kw: invoked.append(1))
    with pytest.raises(c.MiaStudyError, match="candidate, Nara or canary"):
        c._pilot_executor(window, parent, output, monitor, state,
                          time.monotonic() + 60)
    assert not invoked
    assert not (output / "evaluation").exists()


def test_full_schedule_with_unknown_actions_is_not_falsely_aborted(monkeypatch, tmp_path):
    window, parent, output, monitor, state = _executor_fixture(
        monkeypatch, tmp_path, candidate_image=c.PROFILE_IMAGE_ID)
    observed = []

    def fake_run(_manifest, **kwargs):
        observed.append(kwargs["admission_gate"]())
        kwargs["safety_check"]()
        return {"status": "completed_schedule_with_unknown_actions",
                "completed_cell_records": 12, "failure": None}

    monkeypatch.setattr(c.pilot, "run_pilot", fake_run)
    result = c._pilot_executor(window, parent, output, monitor, state,
                               time.monotonic() + 60)
    assert result == {"status": "complete", "pilot_status":
                      "completed_schedule_with_unknown_actions", "recorded_cells": 12}
    assert observed == [parent.qualification_summary]
    assert state["pilot_ready_proof_sha256"] == c._sha(
        (output / "admission-ready-proof.json").read_bytes())


def test_parent_interruption_restores_exact_candidate(monkeypatch, tmp_path):
    output = tmp_path / "window"
    output.mkdir()
    path = output / "window.json"
    path.write_text("{}\n")
    window = {"window_id": "qfn-followon-known-opponent-mia-test-b",
              "output_dir": str(output)}
    parent = SimpleNamespace(spec=SimpleNamespace(image_id=c.PROFILE_IMAGE_ID))
    monkeypatch.setattr(c, "load_window", lambda _path: (window, {}, parent))
    monkeypatch.setattr(c, "CODE_ROOT", tmp_path)
    monkeypatch.setattr(c, "canonical_root", lambda _root: tmp_path)
    monkeypatch.setattr(c, "resource_lease", lambda _root: contextlib.nullcontext())
    monkeypatch.setattr(c, "_identity", lambda pid: {
        "worker_pid": pid, "worker_start_ticks": 1, "boot_id": "test"})
    c.q._atomic_write(output / "state.json", {
        "window_sha256": c._sha(path.read_bytes()), "phase": "candidate_start"})
    stopped = []

    class Child:
        pid = 1234
        returncode = 1

        def poll(self):
            return None if not stopped else self.returncode

        def send_signal(self, signo):
            stopped.append(signo)

        def wait(self, **_kwargs):
            return self.returncode

    monkeypatch.setattr(c.subprocess, "Popen", lambda *_a, **_kw: Child())
    original = c._new

    def fail_start_receipt(destination, value):
        if destination.name == "supervision-start.json":
            raise OSError("fault while sealing child start")
        return original(destination, value)

    monkeypatch.setattr(c, "_new", fail_start_receipt)
    recovered = []
    monkeypatch.setattr(c.q, "restore_exact", lambda *_a, **_kw:
                        recovered.append(1) or {"status": "verified"})
    assert c.supervise(path) == 1
    assert stopped == [signal.SIGTERM]
    assert recovered == [1]
    sealed = json.loads((output / "supervision.json").read_text())
    assert sealed["interrupted"] == "OSError"
    assert sealed["emergency_restoration"] == {"status": "verified"}


def test_memory_arm_and_evaluation_cgroup_are_raw_bound(tmp_path):
    output = tmp_path
    state = {"candidate_id": "f" * 64, "candidate_cgroup_pid": 55,
             "candidate_cgroup_start_ticks": 77,
             "candidate_cgroup_path": "/system.slice/docker-test.scope"}
    parent = SimpleNamespace(spec=SimpleNamespace(image_id=c.PROFILE_IMAGE_ID,
                                                  docker_memory_limit_bytes=4096))
    arm = {"schema": "qwen-flash-next-cgroup-bind/v1",
           "candidate_id": state["candidate_id"],
           "candidate_spec": {"id": c.PROFILE_ID, "spec_sha256": c.PROFILE_SHA256},
           "container_inspect": {"id": state["candidate_id"], "image": c.PROFILE_IMAGE_ID,
                                 "pid": 55, "running": True, "oom_killed": False,
                                 "restart_count": 0, "memory_limit_bytes": 4096,
                                 "memory_swap_total_bytes": 4096},
           "cgroup": {"path": state["candidate_cgroup_path"],
                      "process_start_ticks": 77, "memory_swap_current_bytes": 0,
                      "memory_max_bytes": 4096, "memory_swap_max_bytes": 0,
                      "memory_events_oom": 0, "memory_events_oom_kill": 0}}
    sample = {"schema": "qwen-flash-next-memory-sample/v3",
              "monitor_phase": "evaluation", "mem_available_gib": 30.0,
              "sample_gap_seconds": 1.0, "host_swap_5s_bytes": 0,
              "host_swap_60s_bytes": 0,
              "candidate": {"armed": True, "id": state["candidate_id"],
                            "image": c.PROFILE_IMAGE_ID, "pid": 55,
                            "oom_killed": False, "restart_count": 0,
                            "memory_limit_bytes": 4096,
                            "memory_swap_total_bytes": 4096,
                            "cgroup": arm["cgroup"]}}
    result = {"memory_samples": 1, "minimum_mem_available_gib": 30.0}

    def write(rows):
        (output / "memory.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in rows))

    write([arm, sample])
    assert c._memory(output, result, state, parent)["evaluation_samples"] == 1
    write([arm, {**sample, "host_swap_5s_bytes": 4096}])
    with pytest.raises(c.MiaStudyError, match="OOM, paging"):
        c._memory(output, result, state, parent)
