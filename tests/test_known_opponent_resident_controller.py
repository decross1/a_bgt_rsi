"""Small host-free tests for the registered resident utility study supervisor."""
from __future__ import annotations

import contextlib
import json
import signal
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from bench.flash_next_ab import transport
from experiments.known_opponent_utility import pilot
from experiments.known_opponent_utility import resident_controller as controller


def _manifest():
    endpoint = transport.LocalEndpoint("resident_gemma", "http://127.0.0.1:8000",
                                       "gemma-4-26b-a4b", "a" * 64)
    receipt = {"schema_version": "flash-next-qualification-validation/v1",
               "cohort": "resident", "status": "passed", "admission_eligible": True,
               "qualification_receipt_sha256": "b" * 64,
               "artifact_sha256_by_endpoint": {"resident_gemma": "a" * 64}}
    return pilot.freeze_manifest(
        source_root=Path(pilot.__file__).resolve().parents[2], endpoint=endpoint,
        registered_admission=receipt, policy=controller.POLICY,
        seed=101, max_tokens=64, per_call_timeout_s=10), receipt


def test_controller_produced_window_roundtrips_exact_sources_and_policy(monkeypatch, tmp_path):
    _, receipt = _manifest()
    monkeypatch.setattr(controller, "CANONICAL_ROOT", controller.CODE_ROOT)
    monkeypatch.setattr(controller, "OUTPUT_ROOT", tmp_path / "study")
    monkeypatch.setattr(controller, "RESIDENT_RECEIPT", tmp_path / "resident-receipt.json")
    monkeypatch.setattr(controller, "RESIDENT_INVENTORY", tmp_path / "resident-inventory.json")
    controller.RESIDENT_RECEIPT.write_text("{}\n")
    controller.RESIDENT_INVENTORY.write_text("{}\n")
    monkeypatch.setattr(controller, "_qualification", lambda: receipt)
    path = controller.prepare(window_id="qfn-followon-known-opponent-roundtrip",
                              seed=101, per_call_timeout_s=10)
    document, manifest = controller.load_window(path)
    assert document["policy"] == controller.POLICY
    assert manifest["registered_admission"] == receipt
    assert document["controller_sources"][
        "experiments/known_opponent_utility/resident_controller.py"]["sha256"] == controller._sha(
            controller._raw(Path(controller.__file__)))
    tampered = json.loads(path.read_text())
    tampered["policy"] = {**controller.POLICY, "temperature": 0.2}
    path.write_bytes(controller._json(tampered))
    with pytest.raises(ValueError, match="resident qualification, model, or policy drifted"):
        controller.load_window(path)


@pytest.mark.parametrize("proven_absent,correct_image,expected_bound", [
    (True, True, True), (False, True, False), (True, False, False),
])
def test_restore_only_adopts_exact_own_stopped_watchdog(
        monkeypatch, tmp_path, proven_absent, correct_image, expected_bound):
    window_id = "qfn-followon-known-opponent-test"
    sid = "f" * 64
    row = {"id": sid, "name": controller.resident._sentinel_name(window_id),
           "image": controller.resident.IMAGE_ID if correct_image else "wrong",
           "running": False, "oom_killed": False, "state_error": "", "restart_policy": "no"}
    state = {"initial": {"nara": {"ActiveState": "active"}},
             "watchdog_sentinel_id": None,
             "sentinel_absent_before_create": proven_absent}
    monkeypatch.setattr(controller.resident, "_inspect_container", lambda *_args: row)
    seen = []

    def restore(_ops, captured, _plan, **_kwargs):
        seen.append(captured.copy())
        return {"status": "verified" if expected_bound else "unknown"}

    monkeypatch.setattr(controller.resident, "restore_resident_window", restore)
    proof = controller._restore(None, state, {"window_id": window_id}, tmp_path,
                                deadline=time.monotonic() + 30)
    assert seen[0]["watchdog_sentinel_id"] == (sid if expected_bound else None)
    assert proof["status"] == ("verified" if expected_bound else "unknown")
    if expected_bound:
        assert json.loads((tmp_path / "state.json").read_text())["watchdog_sentinel_id"] == sid


def test_failed_live_admission_makes_no_model_call_and_restores(monkeypatch, tmp_path):
    manifest, receipt = _manifest()
    output = tmp_path / "qfn-followon-known-opponent-test"
    output.mkdir()
    path = output / "window.json"
    path.write_text("{}\n")
    document = {"window_id": output.name, "output_dir": str(output)}
    monkeypatch.setattr(controller, "load_window", lambda _path: (document, manifest))
    monkeypatch.setattr(controller, "canonical_root", lambda _root: tmp_path)
    monkeypatch.setattr(controller, "resource_lease", lambda _root: contextlib.nullcontext())
    monkeypatch.setattr(controller, "resource_probe", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(controller, "_identity", lambda _pid: {"pid": 1, "start_ticks": 1, "boot_id": "test"})
    monkeypatch.setattr(controller.resident, "_inspect_container", lambda *_args: None)
    monkeypatch.setattr(controller.resident, "_create_sentinel", lambda *_args: "f" * 64)
    transitions = []

    class Monitor:
        def __init__(self, *_args, **_kwargs):
            self.phase = "setup"
            self.cancel_event = SimpleNamespace(is_set=lambda: False)
            self.minimum_observed_gib = 30.0
            self.samples = 4
            self.failure = None

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def bind_sentinel(self, _sid):
            return None

        def transition(self, phase, **_kwargs):
            transitions.append(phase)
            self.phase = phase

        def check(self):
            return None

    monkeypatch.setattr(controller.resident, "ResidentSafetyMonitor", Monitor)
    calls = []
    ops = SimpleNamespace(run=lambda argv, **_kwargs: calls.append(argv))

    def residents(_ops, _initial=None, *, nara_transition=False):
        state = "inactive" if nara_transition else "active"
        return {"nara": {"ActiveState": state}, "residents_by_name": {},
                "cgroups_by_name": {}}

    monkeypatch.setattr(controller.resident, "_read_exact_residents", residents)
    restored = []

    def restore(_ops, state, _document, _output, **_kwargs):
        restored.append(state.copy())
        return {"status": "verified", "sentinel_retained": False}

    monkeypatch.setattr(controller, "_restore", restore)
    monkeypatch.setattr(controller, "_qualification", lambda: {**receipt, "qualification_receipt_sha256": "c" * 64})
    invoked = []

    def run(manifest, **kwargs):
        return pilot.run_pilot(manifest, **kwargs,
                               invoke_fn=lambda *_args, **_kw: invoked.append(1))

    result = controller.worker(path, ops=ops, run_fn=run)
    assert result["status"] == "incomplete"
    assert "registered resident admission changed" in result["error"]
    assert not invoked
    assert restored and restored[0]["watchdog_sentinel_id"] == "f" * 64
    assert ["systemctl", "--user", "stop", controller.q.NARA_SERVICE] in calls
    assert transitions == ["quiescing", "evaluation", "restoration"]


def test_parent_start_receipt_interruption_stops_child_and_recovers(monkeypatch, tmp_path):
    output = tmp_path / "qfn-followon-known-opponent-test"
    output.mkdir()
    path = output / "window.json"
    path.write_text("{}\n")
    document = {"window_id": output.name, "output_dir": str(output)}
    monkeypatch.setattr(controller, "load_window", lambda _path: (document, {}))
    monkeypatch.setattr(controller, "CODE_ROOT", tmp_path)
    monkeypatch.setattr(controller, "canonical_root", lambda _root: tmp_path)
    monkeypatch.setattr(controller, "resource_lease", lambda _root: contextlib.nullcontext())
    monkeypatch.setattr(controller, "_identity", lambda pid: {"pid": pid, "start_ticks": 1, "boot_id": "test"})
    controller.q._atomic_write(output / "state.json", {"window_sha256": controller._sha(controller._raw(path))})
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

    monkeypatch.setattr(controller.subprocess, "Popen", lambda *_args, **_kwargs: Child())
    original = controller._new

    def start_receipt_fault(destination, value):
        if destination.name == "supervision-start.json":
            raise OSError("test receipt fault")
        return original(destination, value)

    monkeypatch.setattr(controller, "_new", start_receipt_fault)
    recovered = []
    monkeypatch.setattr(controller, "_restore", lambda *_args, **_kwargs: recovered.append(1) or
                        {"status": "verified", "sentinel_retained": False})
    assert controller.supervise(path) == 1
    assert stopped == [signal.SIGTERM]
    assert recovered == [1]
    sealed = json.loads((output / "supervision.json").read_text())
    assert sealed["interrupted"] == "OSError"
    assert sealed["emergency_restoration"]["status"] == "verified"
