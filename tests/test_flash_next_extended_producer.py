"""CPU-only Flash controller -> real SSE harness -> completed-window admission.

All Docker, service, endpoint, cgroup, UI, time, and model reads are injected.
The actual worker, memory monitor, evidence writers, and offline gate run.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import time
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from bench.flash_next_ab import evaluation_window as ew
from bench.flash_next_ab import extended_admission as admission
from bench.flash_next_ab import extended_lifecycle as lifecycle
from bench.flash_next_ab import extended_observer as observer
from bench.flash_next_ab import harness, transport
from bench.flash_next_ab import qualification as q
from bench.flash_next_ab import resident_evaluation_window as resident_controller
from bench.flash_next_ab.candidate_registry import MIA
from bench.flash_next_ab.manifest import build_plan, make_arm_receipt


class Clock:
    def __init__(self):
        self.current = time.monotonic()
        self.begin = self.current
        self.wall = datetime.now(timezone.utc)
        self.observed_ui = None

    def now(self):
        return self.current

    def utc(self):
        return (self.wall + timedelta(seconds=self.current - self.begin)).isoformat()

    def sleep(self, duration):
        assert 0 <= duration <= 2
        self.current += duration
        if self.observed_ui is not None and self.current - self.observed_ui[1] >= 5:
            self.observed_ui[0]()
            self.observed_ui = (self.observed_ui[0], self.current)


class Host:
    candidate_id = "c" * 64

    def __init__(self):
        self.nara_active = True
        self.residents = {}
        self.containers = {}
        self.commands = []
        self.probes = 0
        for number, expected in enumerate(q.RESIDENTS):
            row = {
                "id": expected["id"], "name": expected["name"],
                "image": expected["image_id"], "running": True,
                "pid": number + 100, "oom_killed": False,
                "started_at": "before", "finished_at": "",
                "state_error": "", "restart_count": 0,
                "restart_policy": "unless-stopped", "memory_limit_bytes": 0,
                "memory_swap_total_bytes": 0,
            }
            self.residents[row["name"]] = row
            self.containers[row["name"]] = row

    def inspect(self, identity):
        return next((copy.deepcopy(row) for row in self.containers.values()
                     if identity in {row["id"], row["name"]}), None)

    def run(self, argv, *, timeout, check=True):
        self.commands.append(tuple(argv))
        if argv[:3] == ["docker", "image", "inspect"]:
            return q.CommandResult(0, MIA.image_id + " arm64\n", "")
        if argv[:2] == ["docker", "inspect"]:
            row = self.inspect(argv[-1])
            return (q.CommandResult(0, json.dumps(row) + "\n", "") if row else
                    q.CommandResult(1, "", "Error: No such object"))
        if argv[:2] == ["docker", "create"]:
            assert argv == q.launch_argv(MIA) and MIA.container_name not in self.containers
            self.containers[MIA.container_name] = {
                "id": self.candidate_id, "name": MIA.container_name,
                "image": MIA.image_id, "running": False, "pid": 0,
                "started_at": "", "finished_at": "",
                "oom_killed": False, "state_error": "", "restart_count": 0,
                "restart_policy": "no", "memory_limit_bytes": MIA.docker_memory_limit_bytes,
                "memory_swap_total_bytes": MIA.docker_memory_limit_bytes,
            }
            return q.CommandResult(0, self.candidate_id + "\n", "")
        if argv[:2] in (["docker", "start"], ["docker", "stop"]):
            row = next(row for row in self.containers.values()
                       if argv[-1] in {row["id"], row["name"]})
            row["running"] = argv[1] == "start"
            if row["name"] == MIA.container_name and row["running"]:
                row["pid"] = 200
            return q.CommandResult(0, row["id"] + "\n", "")
        if argv[:2] == ["docker", "logs"]:
            return q.CommandResult(0, "local fake log\n", "")
        if argv[:2] == ["docker", "rm"]:
            candidate = self.containers.pop(MIA.container_name)
            assert argv[-1] == candidate["id"] and candidate["running"] is False
            return q.CommandResult(0, candidate["id"] + "\n", "")
        if argv[:3] == ["systemctl", "--user", "show"]:
            status = "active" if self.nara_active else "inactive"
            return q.CommandResult(0, f"ActiveState={status}\n"
                                   f"SubState={'running' if self.nara_active else 'dead'}\n"
                                   f"MainPID={'123' if self.nara_active else '0'}\n", "")
        if argv[:3] == ["systemctl", "--user", "stop"]:
            self.nara_active = False
            return q.CommandResult(0, "", "")
        if argv[:3] == ["systemctl", "--user", "start"]:
            self.nara_active = True
            return q.CommandResult(0, "", "")
        raise AssertionError(f"unexpected host mutation: {argv}")

    def http_bytes(self, url, *, timeout):
        assert timeout <= 5 and url.startswith("http://127.0.0.1:")
        return (json.dumps({"object": "list", "data": [{"id": MIA.served_name}]}).encode()
                if url.endswith("/v1/models") else b"OK")

    def complete(self, endpoint, messages, **kwargs):
        self.probes += 1
        assert self.probes <= 3 and endpoint.name == MIA.endpoint_name
        prompt = messages[0]["content"]
        content = ("703" if "37 * 19" in prompt else
                   "FLASH_NEXT_OK_17" if not kwargs.get("tools") else "")
        tools = ([{"id": "call1", "type": "function", "function":
                   {"name": "record_probe", "arguments":
                    '{"label":"flash-next","value":703}'}}]
                 if kwargs.get("tools") else [])
        return streaming(endpoint, messages, kwargs, content, tools)


def streaming(endpoint, messages, arguments, content, tool_calls=None):
    tool_calls = tool_calls or []
    body = transport.request_body(endpoint, messages, arguments["policy"],
                                  arguments["max_tokens"], arguments["seed"],
                                  arguments.get("tools"))
    accumulator = transport.StreamAccumulator(endpoint.served_model)
    finish = "tool_calls" if tool_calls else "stop"
    delta = {"content": content}
    if tool_calls:
        delta["tool_calls"] = [{"index": 0, **tool_calls[0]}]
    chunks = [
        {"id": "fake-response", "model": endpoint.served_model,
         "choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
        {"id": "fake-response", "model": endpoint.served_model,
         "choices": [{"index": 0, "delta": {}, "finish_reason": finish}]},
        {"id": "fake-response", "model": endpoint.served_model, "choices": [],
         "usage": {"prompt_tokens": 10, "completion_tokens": 1,
                   "total_tokens": 11}},
    ]
    payloads = [json.dumps(chunk, sort_keys=True) for chunk in chunks] + ["[DONE]"]
    raw = b"".join(("data: " + payload + "\n\n").encode() for payload in payloads)
    for payload in payloads:
        accumulator.accept(payload)
    result = accumulator.result()
    result.update({
        "endpoint": endpoint.__dict__,
        "request_sha256": hashlib.sha256(transport.canonical(body)).hexdigest(),
        "response_stream_sha256": hashlib.sha256(raw).hexdigest(),
        "response_id": accumulator.response_id,
        "response_model": endpoint.served_model, "latency_s": 0.01,
        "ttft_s": 0.005,
        "private_evidence": transport._private_response_evidence(
            accumulator, raw, response_bytes=len(raw)
        ),
    })
    return result


def frozen_inputs(tmp_path, monkeypatch):
    root = ew.RESEARCH_ROOT
    mia = root / "qualification-runs" / "qfn-mia-c0-20260915-0602"
    resident = root / "runtime" / "resident-qualification-v2.json"
    artifacts = root / "runtime" / "resident-model-artifacts.json"
    summary = harness.validate_flash_qualification_files(
        mia / "result.json", mia / "plan.json", mia / "launch-contract.snapshot.json",
        contract_raw_path=mia / "launch-contract.raw.json", require_passed=True,
    )
    incumbent = harness.validate_resident_qualification_files(
        resident, artifacts, require_passed=True
    )
    flash = make_arm_receipt(
        "flash", qualification_receipt_sha256=summary["qualification_receipt_sha256"],
        artifact_sha256_by_endpoint={"flash_next_mia": summary["model_artifact_sha256"]},
        runtime_sha256_by_endpoint={"flash_next_mia": summary["runtime_sha256"]},
        flash_endpoint_name="flash_next_mia",
    )
    baseline = make_arm_receipt(
        "resident", qualification_receipt_sha256=incumbent["qualification_receipt_sha256"],
        artifact_sha256_by_endpoint=incumbent["artifact_sha256_by_endpoint"],
        runtime_sha256_by_endpoint=incumbent["runtime_sha256_by_endpoint"],
    )
    benchmark, _ = build_plan([baseline, flash])
    assert len(benchmark["declared_cells"]) == 126
    plan_root = tmp_path / "window-plans"
    plan_root.mkdir()
    run_root = tmp_path / "runs"
    run_root.mkdir()
    journal = tmp_path / "research-usage.jsonl"
    monkeypatch.setattr(ew, "WINDOW_PLAN_ROOT", plan_root)
    monkeypatch.setattr(ew, "WINDOW_RUN_ROOT", run_root)
    monkeypatch.setattr(ew, "RESEARCH_LEDGER", journal)
    monkeypatch.setattr(admission, "RESEARCH_LEDGER", journal)
    pair = "qfn-ab-cpu-producer-mia"
    benchmark_path = plan_root / f"{pair}.benchmark.json"
    # Manifest's declared-cell chronology binds cell_receipts insertion order.
    benchmark_path.write_text(json.dumps(benchmark) + "\n")

    def ref(path):
        return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    document = {
        "schema_version": ew.WINDOW_SCHEMA, "pair_id": pair, "cohort": "flash",
        "benchmark": {"plan_path": str(benchmark_path),
                      "plan_file_sha256": ref(benchmark_path)["sha256"],
                      "runtime_budget_seconds": ew.FULL_COHORT_BUDGET_SECONDS},
        "qualification": {
            "receipt": ref(mia / "result.json"),
            "qualification_plan": ref(mia / "plan.json"),
            "contract_snapshot": ref(mia / "launch-contract.snapshot.json"),
            "contract_raw": ref(mia / "launch-contract.raw.json"),
            "resident_artifacts": None,
        },
        "safety": {"window_deadline_seconds": 14_400,
                   "restoration_reserve_seconds": 600,
                   "min_mem_available_gib": 20, "memory_poll_seconds": 1},
        "accounting": {"class": "uncapped-local-model-research",
                       "weekly_budget_debit": False, "paid_api_allowed": False,
                       "journal_path": str(journal)},
        "promotion_authorized": False,
    }
    window_path = plan_root / f"{pair}.flash.window.json"
    window_path.write_text(json.dumps(document, sort_keys=True) + "\n")
    window = ew.load_evaluation_window(window_path, expected_cohort="flash")
    assert window.qualification_summary["variant_id"] == MIA.spec_id
    output = run_root / f"{pair}.flash"
    extended_plan = ew.build_extended_evaluation_plan(window, output)
    return window, extended_plan, output, journal


def test_canonical_checkout_offline_consumer_pins_worktree_and_cannot_execute(
    tmp_path, monkeypatch
):
    window, extended_plan, output, _journal = frozen_inputs(tmp_path, monkeypatch)
    frozen = ew.frozen_controller_source_bundle()
    assert all(row["path"].startswith(str(ew.REGISTERED_CODE_ROOT) + "/")
               for row in frozen.values())
    canonical_checkout = Path("/home/decross1/projects/a_bgt_rsi")
    monkeypatch.setattr(q, "ROOT", canonical_checkout)
    monkeypatch.setattr(resident_controller, "ROOT", canonical_checkout)
    monkeypatch.setattr(lifecycle, "ROOT", canonical_checkout)
    assert ew.frozen_controller_source_bundle() == frozen
    assert ew.build_extended_evaluation_plan(window, output) == extended_plan
    assert extended_plan["launcher_python_path"].startswith(str(ew.REGISTERED_CODE_ROOT))
    prior_contract = json.loads((ew.QUALIFICATION_ROOT / "qfn-mia-c0-20260915-0602" /
                                 "launch-contract.raw.json").read_text())
    with pytest.raises(q.QualificationError, match="outside the registered worktree"):
        q.execute_worker(window.qualification_plan, prior_contract, output,
                         spec=MIA, evaluation_context=(window, extended_plan))
    with pytest.raises(ew.EvaluationWindowError, match="outside the registered worktree"):
        lifecycle.supervise(window, extended_plan, window.qualification_plan,
                            prior_contract, b"{}", output, MIA)
    resident_window = SimpleNamespace(
        pair_id=window.pair_id, source_path=tmp_path / "resident.window.json",
        source_sha256="d" * 64, benchmark_plan_file_sha256=window.benchmark_plan_file_sha256,
        qualification_summary={"qualification_receipt_sha256": "a" * 64},
    )
    resident_output = tmp_path / "resident-output"
    resident_plan = resident_controller._resident_plan(resident_window, resident_output)
    assert resident_plan["controller_source_bundle"] == frozen
    assert resident_plan["launcher_python_path"].startswith(str(ew.REGISTERED_CODE_ROOT))
    with pytest.raises(ew.EvaluationWindowError, match="outside the registered worktree"):
        resident_controller._worker(resident_window, resident_plan, resident_output)
    with pytest.raises(ew.EvaluationWindowError, match="outside the registered worktree"):
        resident_controller._supervise(resident_window, resident_plan, resident_output)
    assert not output.exists() and not resident_output.exists()


@pytest.mark.parametrize("timeout_first_harness_call", [False, True])
def test_real_mia_flash_controller_harness_and_completion_gate(
    tmp_path, monkeypatch, timeout_first_harness_call
):
    """126 real frozen cells; a first-byte timeout remains a denominator failure."""
    window, extended_plan, output, journal = frozen_inputs(tmp_path, monkeypatch)
    clock = Clock()
    # Worker started_at comes from actual wall time; place synthetic observed
    # wall instants just after it, preserving the 120s virtual quiet proof.
    clock.wall = datetime.now(timezone.utc) + timedelta(seconds=0.5)
    host = Host()
    previous_monotonic, previous_sleep = time.monotonic, time.sleep
    monkeypatch.setattr(q.time, "monotonic", clock.now)
    monkeypatch.setattr(q.time, "sleep", clock.sleep)
    monkeypatch.setattr(q, "utc_now", clock.utc)
    monkeypatch.setattr(lifecycle, "utc_now", clock.utc)
    monkeypatch.setattr(observer, "_utc_now", clock.utc)
    monkeypatch.setattr(q, "canonical_root", lambda root: tmp_path)
    monkeypatch.setattr(q, "resource_lease", lambda root: nullcontext())
    def private_journal(row, ledger):
        assert ledger == journal and ledger.name != q.WEEKLY_LEDGER_BASENAME
        with ledger.open("a") as stream:
            stream.write(json.dumps(row, sort_keys=True) + "\n")

    monkeypatch.setattr(q, "_append_research_usage", private_journal)
    monkeypatch.setattr(q, "_assert_port_free", lambda spec=None: None)
    monkeypatch.setattr(q, "_ensure_compile_cache", lambda spec=None: None)
    monkeypatch.setattr(q, "verify_model", lambda *a, **k: json.loads(
        (ew.QUALIFICATION_ROOT / "qfn-mia-c0-20260915-0602" /
         "model-verification.json").read_text()))
    monkeypatch.setattr(q, "_host_meminfo_diagnostics", lambda: {
        "MemFree": 40000000, "Cached": 20000000, "SwapFree": 20000000,
    })
    monkeypatch.setattr(q.MemoryMonitor, "_loop", lambda self: self._done.wait())

    def cgroup(identity, pid):
        assert identity == host.candidate_id and pid == 200
        return {
            "path": f"/system.slice/docker-{identity}.scope",
            "process_start_ticks": 12345,
            "memory_max_bytes": MIA.docker_memory_limit_bytes,
            "memory_swap_max_bytes": 0, "memory_current_bytes": 1_024,
            "selected_memory_stat": {
                "anon": 512, "file": 512, "shmem": 0,
                "active_file": 0, "inactive_file": 0,
                "pgscan": 0, "pgsteal": 0,
            },
            "memory_pressure": "some avg10=0.00 total=0\nfull avg10=0.00 total=0",
            "memory_events_local": {"oom": 0, "oom_kill": 0},
            "memory_swap_current_bytes": 0,
            "memory_events_oom": 0, "memory_events_oom_kill": 0,
        }

    def monitor(path, ops, **kwargs):
        return q.MemoryMonitor(
            path, ops, reader=lambda: 44.0, swap_reader=lambda: 42,
            swapin_reader=lambda: 24,
            psi_reader=lambda: {"some": 0, "full": 0},
            cgroup_reader=cgroup, clock=clock.now, **kwargs,
        )

    monkeypatch.setattr(q, "_candidate_cgroup_snapshot", cgroup)

    def ui_tick(active):
        assert active.path.exists() and not active.done.is_set()
        active.ticks += 1
        active.first_tick_at = active.first_tick_at or clock.utc()
        active.last_tick_at = clock.utc()
        active.last_tick_mono = clock.now()
        active._origin_mono = active._origin_mono or clock.now()
        for url in observer.URLS:
            assert url.startswith("http://127.0.0.1:")
            active._record({"schema": "flash-next-ui-observer/v1",
                            "event": "probe", "url": url,
                            "http_status": 200, "elapsed_seconds": 0.01})
            active.probes += 1
        active._record({"schema": "flash-next-ui-observer/v1",
                        "event": "tick", "failed": False, "tick": active.ticks,
                        "elapsed_monotonic_seconds": clock.now() - active._origin_mono})

    real_start = observer.UIObserver.start

    def start(active):
        real_start(active)
        active.thread.join(timeout=1)
        ui_tick(active)
        clock.observed_ui = (lambda: ui_tick(active), clock.now())

    monkeypatch.setattr(observer.UIObserver, "_loop", lambda self: None)
    monkeypatch.setattr(observer.UIObserver, "start", start)

    calls = [0]

    def invoke(endpoint, messages, **arguments):
        assert host.nara_active is False and endpoint.name == MIA.endpoint_name
        assert host.inspect(host.candidate_id)["running"] is True
        calls[0] += 1
        if timeout_first_harness_call and calls[0] == 1:
            accumulator = transport.StreamAccumulator(endpoint.served_model)
            error = TimeoutError("fake first-byte timeout")
            transport._attach_private_evidence(error, accumulator, b"", response_bytes=0)
            raise error
        return streaming(endpoint, messages, arguments, "{}")

    monkeypatch.setattr(ew, "run_harness", lambda *a, **k: harness.run_harness(
        *a, invoke_fn=invoke, **k))
    monkeypatch.setattr(q, "_assert_port_free", lambda spec=None: None)
    # The actual extended lifecycle freezes parent artifacts and supervises
    # the worker; only the Popen boundary executes this same Python worker.
    monkeypatch.setattr(lifecycle, "_process_start_ticks", lambda pid: q._self_start_ticks())
    monkeypatch.setattr(lifecycle, "_registered", lambda *args, **kwargs:
                        (window, extended_plan, window.qualification_plan,
                         json.loads((ew.QUALIFICATION_ROOT / "qfn-mia-c0-20260915-0602" /
                                     "launch-contract.raw.json").read_text()),
                         (ew.QUALIFICATION_ROOT / "qfn-mia-c0-20260915-0602" /
                          "launch-contract.raw.json").read_bytes(), output, MIA))

    class InProcessWorker:
        def __init__(self, command, **kwargs):
            assert "--worker" in command and kwargs["start_new_session"] is True
            self.pid = os.getpid()
            contract = json.loads((output / "launch-contract.raw.json").read_text())
            self.returncode = (0 if q.execute_worker(
                window.qualification_plan, contract, output, ops=host,
                preflight_probe=lambda root, idle: {
                    "mem_available_gib": 44.0,
                    "runtime_identity": [{"id": resident["id"]}
                                         for resident in q.RESIDENTS],
                },
                monitor_factory=monitor, ledger=journal, spec=MIA,
                evaluation_context=(window, extended_plan),
            )["status"] == "complete" else 1)

        def poll(self):
            return self.returncode

        def wait(self, **kwargs):
            return self.returncode

    real_popen = lifecycle.subprocess.Popen

    def supervised_worker_only(command, **kwargs):
        if "--worker" in command:
            return InProcessWorker(command, **kwargs)
        assert command[0] == "git" and command[1] in {
            "rev-parse", "cat-file", "ls-tree", "show",
        }
        return real_popen(command, **kwargs)

    monkeypatch.setattr(lifecycle.subprocess, "Popen", supervised_worker_only)
    real_signal = q._signal_guard
    monkeypatch.setattr(q, "_signal_guard", lambda: None)
    monkeypatch.setattr(q, "_restore_signals", lambda previous: None)
    try:
        # The plan must be constructed from the actual passed Mia C0 paths.
        assert lifecycle.supervise(
            window, extended_plan, window.qualification_plan,
            json.loads((ew.QUALIFICATION_ROOT / "qfn-mia-c0-20260915-0602" /
                        "launch-contract.raw.json").read_text()),
            (ew.QUALIFICATION_ROOT / "qfn-mia-c0-20260915-0602" /
             "launch-contract.raw.json").read_bytes(), output, MIA,
        ) == 0
    finally:
        monkeypatch.setattr(q, "_signal_guard", real_signal)
        monkeypatch.setattr(q.time, "monotonic", previous_monotonic)
        monkeypatch.setattr(q.time, "sleep", previous_sleep)
    assert json.loads((output / "result.json").read_text())["status"] == "complete"
    proof = admission.validate_completed_flash_window(window.source_path, output)
    assert proof["restoration_verified"] and proof["pair_id"] == window.pair_id
    run = json.loads((output / "harness" / "run.json").read_text())
    assert run["status"] == "complete" and len(run["outcomes"]) == 126
    assert host.nara_active and MIA.container_name not in host.containers
    assert all(row["running"] for row in host.residents.values())
    assert calls[0] == sum(len(outcome["calls"]) for outcome in run["outcomes"])
    assert calls[0] > 126  # dynamic fixture receives every planned call
    if timeout_first_harness_call:
        assert run["outcomes"][0]["calls"][0]["status"] == "timeout"
