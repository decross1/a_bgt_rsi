"""Exercise restoration after failures with host effects injected."""
from __future__ import annotations

import json
import signal
import threading
import time
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from test_followon_v5_producer import FakeHost

from bench.flash_next_ab import lab_window as window
from bench.flash_next_ab.followon_profiles import MIA_MTP3_REDUCED47K_OPT


class Monitor:
    failure = None
    samples = 1
    minimum_observed_gib = 39.0
    emergency_stop_at = None

    def __init__(self, _path, ops, **_kwargs):
        self.ops = ops
        self.cancel_event = threading.Event()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def check(self):
        if self.cancel_event.is_set():
            raise RuntimeError("monitor cancelled")

    def require_setup_quiescence(self, **_kwargs):
        pass

    def begin_mutation_window(self):
        pass

    def arm(self, _cid):
        pass

    def disarm(self):
        pass

    def require_ready_quiescence(self, **_kwargs):
        pass

    def _sample_once(self):
        pass

    def begin_evaluation(self):
        pass

    def begin_restoration(self):
        pass


@pytest.fixture
def injected(monkeypatch, tmp_path):
    spec = MIA_MTP3_REDUCED47K_OPT
    host = FakeHost(spec)
    document = {"window_id": "qfn-ab-lab-test", "cohort": "flash"}
    (tmp_path / "window.json").write_text(json.dumps(document))
    contract_path = tmp_path / "contract.json"
    contract_path.write_text('{"safety":{"probe_timeout_seconds":30}}')
    parent = SimpleNamespace(spec=spec, document={"source_refs": {
        "launch-contract.snapshot.json": {"path": str(contract_path)}}},
        qualification_plan={"docker_create_argv": window.q.launch_argv(spec)})
    monkeypatch.setattr(window.q, "HostOps", lambda: host)
    monkeypatch.setattr(window.q, "MemoryMonitor", Monitor)
    monkeypatch.setattr(window, "resource_lease", lambda _root: nullcontext())
    monkeypatch.setattr(window, "resource_probe", lambda *_a, **_kw: {
        "mem_available_gib": 39,
        "runtime_identity": [{"id": row["id"]} for row in window.q.RESIDENTS]})
    monkeypatch.setattr(window.q, "verify_model", lambda *_a, **_kw: {"verified": True})
    monkeypatch.setattr(window.q, "_assert_port_free", lambda *_a: None)
    monkeypatch.setattr(window.q, "_ensure_compile_cache", lambda *_a: None)
    monkeypatch.setattr(window.q, "_run_probes", lambda *_a, **_kw: [])
    monkeypatch.setattr(window, "run_profile_canary", lambda *_a, **_kw: {"status": "passed"})
    return tmp_path, host, parent, document


@pytest.mark.parametrize("failure", [RuntimeError("grader failed"), KeyboardInterrupt()])
def test_flash_evaluator_fault_restores_exact_residents_and_nara(injected, monkeypatch, failure):
    output, host, parent, document = injected

    def fail(*_a, **_kw):
        raise failure

    monkeypatch.setattr(window, "_run_evaluator", fail)
    result = window._flash(document, parent, output, time.monotonic() + 900)
    assert result["status"] == "aborted"
    assert result["restoration"]["status"] == "verified"
    assert host.nara_active is True
    assert parent.spec.container_name not in host.rows
    for expected in window.q.RESIDENTS:
        assert host.rows[expected["name"]]["id"] == expected["id"]
        assert host.rows[expected["name"]]["running"] is True


def test_canary_failure_cannot_reach_evaluator(injected, monkeypatch):
    output, host, parent, document = injected
    monkeypatch.setattr(window, "run_profile_canary", lambda *_a, **_kw: {"status": "failed"})
    monkeypatch.setattr(window, "_run_evaluator", lambda *_a, **_kw: pytest.fail("failed canary admitted"))
    result = window._flash(document, parent, output, time.monotonic() + 900)
    assert result["status"] == "aborted" and "canaries failed" in result["error"]
    assert result["restoration"]["status"] == "verified" and host.nara_active


def test_model_verification_failure_does_not_stop_residents(injected, monkeypatch):
    output, host, parent, document = injected

    def corrupt(*_a, **_kw):
        raise ValueError("artifact changed")

    monkeypatch.setattr(window.q, "verify_model", corrupt)
    result = window._flash(document, parent, output, time.monotonic() + 900)
    assert result["status"] == "aborted"
    assert not any(action[:2] == ("docker", "stop") for action in host.actions)
    assert result["restoration"]["no_mutation_verified"] is True


def test_live_window_rejects_mock_mode_before_loading(monkeypatch):
    monkeypatch.setenv("MOCK_LLM", "1")
    with pytest.raises(ValueError, match="refuses MOCK_LLM"):
        window.main(["--run", "--window", "/unissued.json"])


@pytest.mark.parametrize("kind,budget", [("primary", 10431), ("context", 6001), ("fresh", 1801)])
def test_prepare_rejects_runner_specific_oversized_budget_before_registration(monkeypatch, kind, budget):
    monkeypatch.setattr(window, "_evaluator", lambda _kind: SimpleNamespace(load_plan=lambda _path: None))
    monkeypatch.setattr(window, "load_parent", lambda _path: pytest.fail("invalid budget reached runtime registration"))
    with pytest.raises(ValueError, match="invalid harness budget"):
        window.prepare(window.ARTIFACT_ROOT / "unissued.plan.json", cohort="flash",
                       window_id="qfn-ab-budget-test", runtime_budget_s=budget, wall_s=14400, kind=kind)


@pytest.mark.parametrize("fault", ["parent_interrupt", "start_receipt_error"])
def test_supervisor_fault_stops_worker_and_performs_exact_recovery(monkeypatch, tmp_path, fault):
    path = tmp_path / "window.json"
    path.write_text("{}")
    document = {"output_dir": str(tmp_path), "cohort": "flash", "wall_s": 900}
    parent = SimpleNamespace(spec=object())
    monkeypatch.setattr(window, "load_window", lambda _p: (document, parent))
    monkeypatch.setattr(window, "canonical_root", lambda _root: tmp_path)
    monkeypatch.setattr(window, "_process_identity", lambda pid: {
        "worker_pid": pid, "worker_start_ticks": 1, "boot_id": "test-boot"})
    monkeypatch.setattr(window, "resource_lease", lambda _root: nullcontext())
    signals, recoveries = [], []

    class Worker:
        pid = 789
        returncode = None

        def poll(self):
            return self.returncode

        def send_signal(self, value):
            signals.append(value)

        def wait(self, *, timeout):
            assert timeout == window.RESTORE_S
            self.returncode = -15
            return self.returncode

    def launch(*_a, **_kw):
        (tmp_path / "state.json").write_text(json.dumps({
            "window_sha256": window._sha(path.read_bytes()),
            "initial": {"nara_was_active": True}, "candidate_id": "bound-id"}))
        return Worker()

    def recover(_ops, state, **kwargs):
        recoveries.append((state, kwargs))
        return {"status": "verified"}

    def interrupt(_duration):
        raise KeyboardInterrupt()

    monkeypatch.setattr(window.subprocess, "Popen", launch)
    monkeypatch.setattr(window.q, "restore_exact", recover)
    monkeypatch.setattr(window.time, "sleep", interrupt)
    if fault == "start_receipt_error":
        original_new = window._new

        def fail_start(target, value):
            if target.name == "supervision-start.json":
                raise OSError("receipt write failed")
            return original_new(target, value)

        monkeypatch.setattr(window, "_new", fail_start)
    assert window.supervise(path) == 1
    assert signals == [signal.SIGTERM]
    assert len(recoveries) == 1 and recoveries[0][1]["spec"] is parent.spec
    supervision = json.loads((tmp_path / "supervision.json").read_text())
    assert supervision["interrupted"] == ("KeyboardInterrupt" if fault == "parent_interrupt" else "OSError")
    assert supervision["emergency_restoration"]["status"] == "verified"
    assert supervision["returncode"] == -15


def test_supervisor_exclusive_reservation_prevents_duplicate_worker(monkeypatch, tmp_path):
    path = tmp_path / "window.json"
    path.write_text("{}")
    (tmp_path / "supervision-reservation.json").write_text("{}")
    monkeypatch.setattr(window, "load_window", lambda _p: ({"output_dir": str(tmp_path)}, None))
    monkeypatch.setattr(window.subprocess, "Popen", lambda *_a, **_kw: pytest.fail("duplicate worker launched"))
    with pytest.raises(FileExistsError):
        window.supervise(path)


@pytest.mark.parametrize("absent,correct_image,bound", [(True, True, True), (False, True, False),
                                                        (True, False, False)])
def test_resident_recovery_binds_only_exact_sentinel_created_after_proven_absence(
        monkeypatch, tmp_path, absent, correct_image, bound):
    document = {"window_id": "qfn-ab-lab-gap"}
    sentinel_id = "f" * 64
    row = {"id": sentinel_id,
           "name": window.resident._sentinel_name(document["window_id"]),
           "image": window.resident.IMAGE_ID if correct_image else "wrong-image",
           "running": False, "oom_killed": False, "state_error": "", "restart_policy": "no"}
    state = {"initial": {"nara": {"ActiveState": "active"}}, "watchdog_sentinel_id": None,
             "sentinel_absent_before_create": absent}
    monkeypatch.setattr(window.resident, "_inspect_container", lambda *_a: row)
    calls = []

    def restore(_ops, captured, _plan, **_kw):
        calls.append(captured.copy())
        if bound:
            assert json.loads((tmp_path / "state.json").read_text())["watchdog_sentinel_id"] == sentinel_id
        return {"status": "verified" if bound else "unknown"}

    monkeypatch.setattr(window.resident, "restore_resident_window", restore)
    result = window._restore_resident(None, state, document, tmp_path, deadline=time.monotonic() + 30)
    assert len(calls) == 1
    assert calls[0]["watchdog_sentinel_id"] == (sentinel_id if bound else None)
    assert result["status"] == ("verified" if bound else "unknown")
