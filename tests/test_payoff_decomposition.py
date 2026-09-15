"""CPU-only producer, raw replay and resident recovery checks."""
from __future__ import annotations

import contextlib
import json
import signal
from pathlib import Path
from types import SimpleNamespace

import pytest

from bench.flash_next_ab import transport
from experiments.payoff_decomposition import admission, controller, queue, runner, study
from orchestrator.weekly_upgrade_trial import TrialError


def _manifest(panel_id="payoff-representation-a", seed_base=101):
    endpoint = transport.LocalEndpoint("resident_gemma", "http://127.0.0.1:8000",
                                       "gemma-4-26b-a4b", "a" * 64)
    receipt = {"schema_version": "flash-next-qualification-validation/v1",
               "cohort": "resident", "status": "passed", "admission_eligible": True,
               "qualification_receipt_sha256": "b" * 64,
               "artifact_sha256_by_endpoint": {"resident_gemma": "a" * 64}}
    manifest = study.freeze_manifest(
        source_root=Path(study.__file__).resolve().parents[2], endpoint=endpoint,
        registered_admission=receipt, panel_id=panel_id, seed_base=seed_base)
    return manifest, receipt


def _fake_sse(manifest):
    by_messages = {study.sha(study.raw_json(item["messages"])): item
                   for item in manifest["tasks"]}

    def invoke(endpoint, messages, *, policy, max_tokens, timeout_s, seed,
               cancel_event=None):
        task = by_messages[study.sha(study.raw_json(messages))]
        content = f"focal={task['expected_focal']};sum={task['expected_total']}"
        body = transport.request_body(endpoint, messages, policy, max_tokens, seed)
        chunk = {"id": f"test-{task['ordinal']}", "model": endpoint.served_model,
                 "choices": [{"index": 0, "delta": {"content": content},
                              "finish_reason": "stop"}],
                 "usage": {"prompt_tokens": 12, "completion_tokens": 8,
                           "total_tokens": 20}}
        payload = json.dumps(chunk, separators=(",", ":"))
        raw = f"data: {payload}\n\ndata: [DONE]\n\n".encode()
        accumulator = transport.StreamAccumulator(endpoint.served_model)
        accumulator.accept(payload)
        accumulator.accept("[DONE]")
        return {"content": content,
                "request_sha256": study.sha(transport.canonical(body)),
                "latency_s": 0.1, "ttft_s": 0.05, "usage": chunk["usage"],
                "private_evidence": transport._private_response_evidence(
                    accumulator, raw, response_bytes=len(raw))}

    return invoke


def test_fresh_matched_pairs_and_exact_rational_controls():
    a, _ = _manifest()
    b, _ = _manifest("payoff-representation-b")
    assert len(a["tasks"]) == len(b["tasks"]) == 12
    assert {tuple(item["actions"]) for item in a["tasks"]}.isdisjoint(
        {tuple(item["actions"]) for item in b["tasks"]})
    assert {sum(actions) for actions in study.PANELS["payoff-representation-a"]} == {1, 2, 3}
    assert {sum(actions) for actions in study.PANELS["payoff-representation-b"]} == {1, 2, 3}
    for ordinal in range(0, 12, 2):
        first, second = a["tasks"][ordinal:ordinal + 2]
        assert first["pair_id"] == second["pair_id"]
        assert {first["view"], second["view"]} == set(study.VIEWS)
        assert (first["expected_focal"], first["expected_total"]) == (
            second["expected_focal"], second["expected_total"])
        assert first["messages"] != second["messages"]
        first_prompt = first["messages"][0]["content"]
        second_prompt = second["messages"][0]["content"]
        for prompt in (first_prompt, second_prompt):
            assert "seat order" in prompt
            assert "common_return=" not in prompt and "expected_focal" not in prompt
        assert first_prompt.split("Joint actions:", 1)[0] == second_prompt.split(
            "Joint actions:", 1)[0]
        assert first_prompt.split(" For focal seat ", 1)[1] == second_prompt.split(
            " For focal seat ", 1)[1]
    assert study.oracle((1, 0, 0, 0), 0) == (study.Fraction(5, 2), study.Fraction(25))


def test_real_shaped_sse_producer_to_independent_grade_and_tamper(tmp_path):
    manifest, receipt = _manifest()
    output = tmp_path / "complete"
    run = runner.run_study(manifest, output=output, admission_gate=lambda: receipt,
                           safety_check=lambda: None, invoke_fn=_fake_sse(manifest))
    assert run["status"] == "complete" and run["attempted_calls"] == 12
    assert run["summary"] == {key: 12 for key in (
        "strict_shape_valid", "focal_correct", "total_correct", "both_correct")}
    gate = admission.validate_study(output)
    assert gate["admission_eligible"] and gate["returned_sse_verified"] == 12
    assert gate["private_content_exported"] is False
    run["summary"]["focal_correct"] = 11
    (output / "run.json").write_bytes(study.raw_json(run) + b"\n")
    with pytest.raises(ValueError, match="summary/view/seat denominators"):
        admission.validate_study(output)


def test_controller_produced_window_roundtrips_source_model_and_launcher(monkeypatch, tmp_path):
    _manifest_value, receipt = _manifest()
    monkeypatch.setattr(controller, "CANONICAL_ROOT", controller.CODE_ROOT)
    monkeypatch.setattr(controller, "OUTPUT_ROOT", tmp_path / "payoff")
    monkeypatch.setattr(controller.sys, "executable",
                        str(controller.CODE_ROOT / ".venv-chroma/bin/python"))
    monkeypatch.setattr(controller.stable, "RESIDENT_RECEIPT", tmp_path / "resident.json")
    monkeypatch.setattr(controller.stable, "RESIDENT_INVENTORY", tmp_path / "inventory.json")
    controller.stable.RESIDENT_RECEIPT.write_text("{}\n")
    controller.stable.RESIDENT_INVENTORY.write_text("{}\n")
    monkeypatch.setattr(controller.stable, "_qualification", lambda: receipt)
    path = controller.prepare(job_id="payoff-representation-a",
                              panel_id="payoff-representation-a", seed_base=101)
    document, manifest = controller.load_window(path)
    assert document["launcher_python"].startswith(str(controller.CODE_ROOT))
    assert document["controller_sources"] == manifest["source_sha256"]
    assert document["endpoint"] == manifest["endpoint"]
    assert document["policy"] == manifest["policy"] == study.POLICY
    changed = json.loads(path.read_text())
    changed["endpoint"]["served_model"] = "wrong"
    path.write_bytes(controller.stable._json(changed))
    with pytest.raises(ValueError, match="resident qualification/model/policy"):
        controller.load_window(path)


def test_failed_current_admission_makes_no_model_call_and_restores(monkeypatch, tmp_path):
    manifest, receipt = _manifest()
    output = tmp_path / "payoff-representation-a"
    output.mkdir()
    path = output / "window.json"
    path.write_text("{}\n")
    document = {"window_id": "qfn-followon-payoff-representation-a", "output_dir": str(output)}
    monkeypatch.setattr(controller, "load_window", lambda _path: (document, manifest))
    monkeypatch.setattr(controller, "canonical_root", lambda _root: tmp_path)
    monkeypatch.setattr(controller, "resource_lease", lambda _root: contextlib.nullcontext())
    monkeypatch.setattr(controller, "resource_probe", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(controller.stable, "_identity",
                        lambda _pid: {"pid": 1, "start_ticks": 1, "boot_id": "test"})
    monkeypatch.setattr(controller.resident, "_inspect_container", lambda *_args: None)
    monkeypatch.setattr(controller.resident, "_create_sentinel", lambda *_args: "f" * 64)

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
            self.phase = phase

        def check(self):
            return None

    monkeypatch.setattr(controller.resident, "ResidentSafetyMonitor", Monitor)
    calls = []
    ops = SimpleNamespace(run=lambda argv, **_kwargs: calls.append(argv))

    def residents(_ops, _initial=None, *, nara_transition=False):
        return {"nara": {"ActiveState": "inactive" if nara_transition else "active"},
                "residents_by_name": {}, "cgroups_by_name": {}}

    monkeypatch.setattr(controller.resident, "_read_exact_residents", residents)
    restored = []
    monkeypatch.setattr(controller.stable, "_restore",
                        lambda _ops, state, *_args, **_kwargs: restored.append(state.copy()) or
                        {"status": "verified", "sentinel_retained": False})
    monkeypatch.setattr(controller.stable, "_qualification",
                        lambda: {**receipt, "qualification_receipt_sha256": "c" * 64})
    invoked = []

    def run(_manifest, **kwargs):
        kwargs["admission_gate"]()
        invoked.append(1)

    result = controller.worker(path, ops=ops, run_fn=run)
    assert result["status"] == "incomplete"
    assert not invoked
    assert restored and restored[0]["watchdog_sentinel_id"] == "f" * 64
    assert ["systemctl", "--user", "stop", controller.q.NARA_SERVICE] in calls


def test_parent_start_fault_stops_worker_and_recovers(monkeypatch, tmp_path):
    output = tmp_path / "payoff-representation-a"
    output.mkdir()
    path = output / "window.json"
    path.write_text("{}\n")
    monkeypatch.setattr(controller, "load_window",
                        lambda _path: ({"window_id": "qfn-followon-payoff-representation-a",
                                        "output_dir": str(output),
                                        "launcher_python": "/home/decross1/projects/a_bgt_rsi/.venv-chroma/bin/python"}, {}))
    monkeypatch.setattr(controller, "CODE_ROOT", tmp_path)
    monkeypatch.setattr(controller, "canonical_root", lambda _root: tmp_path)
    monkeypatch.setattr(controller, "resource_lease", lambda _root: contextlib.nullcontext())
    monkeypatch.setattr(controller.stable, "_identity",
                        lambda pid: {"pid": pid, "start_ticks": 1, "boot_id": "test"})
    controller.q._atomic_write(output / "state.json", {
        "window_sha256": study.sha(controller._raw(path))})
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

    def fault(destination, value):
        if destination.name == "supervision-start.json":
            raise OSError("start receipt fault")
        return original(destination, value)

    monkeypatch.setattr(controller, "_new", fault)
    recovered = []
    monkeypatch.setattr(controller.stable, "_restore",
                        lambda *_args, **_kwargs: recovered.append(1) or
                        {"status": "verified", "sentinel_retained": False})
    assert controller.supervise(path) == 1
    assert stopped == [signal.SIGTERM]
    assert recovered == [1]
    assert json.loads((output / "supervision.json").read_text())["interrupted"] == "OSError"


def test_queue_has_one_attempt_and_future_fresh_input(monkeypatch, tmp_path):
    monkeypatch.setattr(controller, "OUTPUT_ROOT", tmp_path)
    a = queue.JOBS["payoff-representation-a"]
    b = queue.JOBS["payoff-representation-b"]
    assert queue._time(a["not_before"]) < queue._time(a["expires_at"])
    assert queue._time(b["not_before"]) > queue._time(a["expires_at"])
    assert queue.status("payoff-representation-b",
                        now=queue._time(a["not_before"]))["state"] == "not_due"
    with pytest.raises(ValueError, match="outside preregistered"):
        queue.dispatch("payoff-representation-b", now=queue._time(a["not_before"]))


def test_known_busy_lease_is_a_durable_zero_call_no_mutation_refusal(monkeypatch, tmp_path):
    manifest, _receipt = _manifest()
    output = tmp_path / "payoff-representation-a"
    output.mkdir()
    path = output / "window.json"
    path.write_text("{}\n")
    document = {"window_id": "qfn-followon-payoff-representation-a", "output_dir": str(output)}
    monkeypatch.setattr(controller, "load_window", lambda _path: (document, manifest))
    monkeypatch.setattr(controller, "canonical_root", lambda _root: tmp_path)
    monkeypatch.setattr(controller.stable, "_identity",
                        lambda _pid: {"pid": 1, "start_ticks": 1, "boot_id": "test"})

    @contextlib.contextmanager
    def busy(_root):
        raise TrialError("actual research lease occupied")
        yield

    monkeypatch.setattr(controller, "resource_lease", busy)
    inspected = []
    monkeypatch.setattr(controller.resident, "_inspect_container",
                        lambda *_args: inspected.append(1) or None)
    monkeypatch.setattr(controller.resident, "_read_exact_residents",
                        lambda *_args, **_kwargs: pytest.fail("resident mutation preflight ran"))
    monkeypatch.setattr(controller.stable, "_restore",
                        lambda *_args, **_kwargs: {
                            "status": "verified", "errors": [], "sentinel_retained": False,
                            "no_mutation_verified": True, "verified_at": "test",
                            "final_observation": None})
    invoked = []
    result = controller.worker(path, ops=SimpleNamespace(),
                               run_fn=lambda *_args, **_kwargs: invoked.append(1))
    state = json.loads((output / "state.json").read_text())
    assert result["status"] == "incomplete" and result["study_run_sha256"] is None
    assert state["initial"] is None and state["watchdog_sentinel_id"] is None
    assert state["nara_stop_attempted"] is False
    assert result["restoration"]["no_mutation_verified"] is True
    assert not invoked and not (output / "study").exists()


def test_r1_requires_exact_typed_initial_refusal_and_raw_links(monkeypatch, tmp_path):
    manifest, _ = _manifest(seed_base=queue.JOBS["payoff-representation-a"]["seed_base"])
    job_id = "payoff-representation-a"
    monkeypatch.setattr(controller, "OUTPUT_ROOT", tmp_path)
    output = tmp_path / job_id
    output.mkdir()
    path = output / "window.json"
    path.write_text("{}\n")
    qualification = {"receipt_sha256": "c" * 64}
    document = {"job_id": job_id, "attempt_index": 0,
                "qualification": qualification,
                "launcher_python": "/home/decross1/projects/a_bgt_rsi/.venv-chroma/bin/python"}
    monkeypatch.setattr(controller, "load_window", lambda _path: (document, manifest))
    window_sha = study.sha(controller._raw(path))
    worker = {"pid": 1234, "start_ticks": 91,
              "boot_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"}
    reserved_at = "2026-09-15T19:01:00+00:00"
    reservation = {"schema": queue.SCHEMA, "job_id": job_id,
                   "attempt_index": 0,
                   "job_source_sha256": study.sha(Path(queue.__file__).read_bytes()),
                   "source_bundle_sha256": study.sha(study.raw_json(manifest["source_sha256"])),
                   "window_sha256": window_sha,
                   "manifest_sha256": manifest["manifest_sha256"],
                   "qualification_receipt_sha256": qualification["receipt_sha256"],
                   "reserved_at": reserved_at,
                   "not_before": queue.JOBS[job_id]["not_before"],
                   "expires_at": queue.JOBS[job_id]["expires_at"],
                   "prior_zero_call_refusal_sha256": None,
                   "one_issued_study_attempt_only": True,
                   "comparison_eligible": False}
    controller._new(output / "dispatch-reservation.json", reservation)
    controller._new(output / "supervision-start.json", {
        "window_sha256": window_sha,
        "argv": [document["launcher_python"], "-m",
                 "experiments.payoff_decomposition.controller", "--worker", "--window", str(path)],
        "worker": worker})
    restoration = {"status": "verified", "errors": [],
                   "sentinel_retained": False, "no_mutation_verified": True,
                   "verified_at": reserved_at, "final_observation": None}
    state = {"schema": controller.STATE_SCHEMA, "window_sha256": window_sha,
             "phase": "incomplete", "preflight_failure_code": "resource_lease_busy",
             "initial": None, "watchdog_sentinel_id": None,
             "sentinel_absent_before_create": False,
             "nara_stop_attempted": False, "worker": worker,
             "restoration": restoration}
    controller.q._atomic_write(output / "state.json", state)
    controller._new(output / "result.json", {
        "schema": controller.RESULT_SCHEMA, "window_sha256": window_sha,
        "status": "incomplete", "preflight_failure_code": "resource_lease_busy",
        "study_run_sha256": None, "admission_ready_proof_sha256": None,
        "memory_samples": 0, "restoration": restoration})
    controller._new(output / "supervision.json", {
        "schema": controller.SUPERVISION_SCHEMA, "window_sha256": window_sha,
        "returncode": 1, "terminated_at_cutoff": False,
        "interrupted": None, "emergency_restoration": None})
    controller._new(output / "dispatch-result.json", {
        "schema": "known-opponent-payoff-job-dispatch-result/v1",
        "job_id": job_id, "attempt_index": 0, "window_sha256": window_sha,
        "reservation_sha256": study.sha(controller._raw(output / "dispatch-reservation.json")),
        "supervisor_returncode": 1, "admission_receipt_sha256": None,
        "status": "observed_unadmitted"})
    proof = queue.validate_zero_call_refusal(job_id)
    assert proof["retry_allowed"] and proof["model_calls_issued"] == 0
    assert proof["state_sha256"] == study.sha(controller._raw(output / "state.json"))
    state["preflight_failure_code"] = "other_preflight_failure"
    controller.q._atomic_write(output / "state.json", state)
    with pytest.raises(ValueError, match="zero-call/no-mutation"):
        queue.validate_zero_call_refusal(job_id)


def test_busy_availability_refusal_is_recorded_without_claim_or_call(monkeypatch, tmp_path):
    manifest, _ = _manifest(seed_base=queue.JOBS["payoff-representation-a"]["seed_base"])
    job_id = "payoff-representation-a"
    monkeypatch.setattr(controller, "OUTPUT_ROOT", tmp_path)
    output = tmp_path / job_id
    output.mkdir()
    path = output / "window.json"
    path.write_text("{}\n")
    document = {"job_id": job_id, "attempt_index": 0,
                "qualification": {"receipt_sha256": "c" * 64}}
    monkeypatch.setattr(controller, "load_window", lambda _path: (document, manifest))

    @contextlib.contextmanager
    def busy(_root):
        raise TrialError("resource is occupied: coordinator")
        yield

    monkeypatch.setattr(queue, "resource_lease", busy)
    monkeypatch.setattr(queue, "canonical_root", lambda _root: tmp_path)
    with pytest.raises(TrialError):
        queue.dispatch(job_id, now=queue._time("2026-09-15T19:01:00+00:00"))
    assert not (output / "dispatch-reservation.json").exists()
    assert not (output / "study").exists()
    raw = controller._raw(output / "availability-refusal-00.json")
    receipt = json.loads(raw)
    assert receipt["failure_code"] == "resource_lease_busy"
    assert receipt["model_calls_issued"] == 0
    assert receipt["window_sha256"] == study.sha(controller._raw(path))
