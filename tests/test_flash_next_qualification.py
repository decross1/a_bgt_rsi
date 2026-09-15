"""CPU-only safety tests for the destructive-window controller.

Every Docker, systemd, endpoint, lease, and usage-journal effect is fake.
"""
from __future__ import annotations

import ast
import copy
import json
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

from bench.flash_next_ab import qualification as q


def contract():
    return {
        "schema": "qwen-flash-next-qualification/v3",
        "contract_id": "qwen38-flash-next-c0-20260915",
        "profile": "C0",
        "image": {"id": q.IMAGE_ID, "architecture": "arm64"},
        "model": {
            "repository": q.MODEL_REPOSITORY,
            "revision": q.MODEL_REVISION,
            "host_path": str(q.MODEL_PATH),
            "container_path": "/models/qwen",
            "served_name": q.SERVED_MODEL,
            "safetensors_total_bytes": q.MODEL_TOTAL_BYTES,
            "tensor_payload_bytes": q.MODEL_TENSOR_BYTES,
            "repository_total_bytes": q.MODEL_REPOSITORY_BYTES,
            "artifact_sha256": q.model_artifact_sha256(),
            "files": q.expected_model_files(),
            "full_sha256_before_mutation": True,
        },
        "runtime": {
            "container_name": q.CONTAINER_NAME,
            "host_address": "127.0.0.1",
            "host_port": 8012,
            "container_port": 8000,
            "compile_cache_path": str(q.COMPILE_CACHE),
            "max_model_len": 16384,
            "max_num_seqs": 1,
            "gpu_memory_utilization": 0.75,
            "kv_cache_memory_bytes": 1073741824,
            "max_num_batched_tokens": 4096,
            "kv_cache_dtype": "auto",
            "mamba_ssm_cache_dtype": "float32",
            "mtp_speculative_tokens": 0,
            "prefix_caching": False,
            "async_scheduling": False,
            "qsa_exact_topk": True,
            "language_model_only": True,
        },
        "safety": {
            "resident_containers": [dict(row) for row in q.RESIDENTS],
            "nara_service": q.NARA_SERVICE,
            "min_mem_available_gib": 20,
            "invocation_deadline_seconds": 3600,
            "readiness_deadline_seconds": 1200,
            "restoration_reserve_seconds": 600,
            "setup_quiescence_seconds": 60,
            "ready_quiescence_seconds": 60,
            "memory_poll_seconds": 1,
            "probe_timeout_seconds": 120,
            "paging_policy": copy.deepcopy(q.PAGING_POLICY),
        },
        "accounting": {
            "class": "uncapped-local-model-research",
            "weekly_budget_debit": False,
            "paid_api_allowed": False,
            "journal_path": str(q.RESEARCH_LEDGER),
        },
        "probe_set": "flash-next-minimal-v1",
    }


def plan():
    return {
        "contract_sha256": "a" * 64,
        "probe_set": "flash-next-minimal-v1",
        "docker_create_argv": q.launch_argv(),
    }


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("image", "id"), "sha256:" + "0" * 64),
        (("model", "host_path"), "/tmp/model"),
        (("model", "served_name"), "impersonated"),
        (("runtime", "container_name"), "vllm-qwen-ab-evil"),
        (("runtime", "mtp_speculative_tokens"), 2),
        (("runtime", "prefix_caching"), True),
        (("runtime", "gpu_memory_utilization"), 0.92),
        (("runtime", "kv_cache_memory_bytes"), 0),
        (("runtime", "language_model_only"), False),
        (("safety", "min_mem_available_gib"), 19),
        (("safety", "invocation_deadline_seconds"), 3601),
        (("safety", "setup_quiescence_seconds"), 59),
        (("safety", "ready_quiescence_seconds"), 59),
        (("safety", "paging_policy"), {}),
        (("accounting", "weekly_budget_debit"), True),
        (("accounting", "paid_api_allowed"), True),
    ],
)
def test_contract_drift_is_rejected(path, value):
    value_under_test = copy.deepcopy(contract())
    value_under_test[path[0]][path[1]] = value
    with pytest.raises(q.QualificationError):
        q.validate_contract(value_under_test)


def test_contract_rejects_duplicate_keys_and_accepts_a_lower_preregistered_cap():
    value = contract()
    value["safety"]["invocation_deadline_seconds"] = 1800
    value["safety"]["readiness_deadline_seconds"] = 600
    assert q.validate_contract(value)["safety"]["invocation_deadline_seconds"] == 1800
    with pytest.raises(q.QualificationError, match="duplicate"):
        q._strict_json(b'{"schema":1,"schema":2}', source="test")


def test_exact_raw_contract_bytes_are_bound_for_the_run_receipt(monkeypatch, tmp_path):
    path = tmp_path / "launch-contract.c0.json"
    raw = json.dumps(contract(), indent=3).encode() + b"\n"
    path.write_bytes(raw)
    monkeypatch.setattr(q, "CONTRACT_PATH", path)

    assert q._verified_contract_raw(contract(), q.sha256(raw)) == raw
    path.write_bytes(raw + b" ")
    with pytest.raises(q.QualificationError, match="changed after planning"):
        q._verified_contract_raw(contract(), q.sha256(raw))


def test_launch_vector_is_fixed_and_conservative():
    argv = q.launch_argv()
    assert argv[:4] == ["docker", "create", "--name", q.CONTAINER_NAME]
    assert q.IMAGE_ID in argv
    assert f"{q.MODEL_PATH}:/models/qwen:ro" in argv
    assert "127.0.0.1:8012:8000" in argv
    assert "--restart=no" in argv
    assert "--kv-cache-memory-bytes" in argv and "1073741824" in argv
    assert "--gpu-memory-utilization" in argv and "0.75" in argv
    assert "--language-model-only" in argv
    assert "--no-enable-prefix-caching" in argv
    assert "--no-async-scheduling" in argv
    assert "VLLM_QSA_EXACT_TOPK=1" in argv
    assert "VLLM_QSA_DET_TOPK=0" in argv
    assert "VLLM_PLE_MMAP_PREWARM=0" in argv
    assert "--speculative-config" not in argv
    assert all("VLLM_MTP_DRAFT_VOCAB" not in item for item in argv)
    assert "--privileged" not in argv and "--network=host" not in argv
    assert all("http://" not in item and "https://" not in item for item in argv)


def test_controller_does_not_import_or_construct_weekly_budget_ledger():
    tree = ast.parse(Path(q.__file__).read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert "orchestrator.weekly_upgrade_budget" not in imported
    calls = [
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    assert "BudgetLedger" not in calls


def test_compile_cache_is_created_only_below_owned_registered_parent(
    monkeypatch, tmp_path
):
    parent = tmp_path / "compile-cache-c0"
    child = parent / "qwen38-flash-next-d453-c0"
    monkeypatch.setattr(q, "COMPILE_CACHE_PARENT", parent)
    monkeypatch.setattr(q, "COMPILE_CACHE", child)

    with pytest.raises(q.QualificationError, match="absent or redirected"):
        q._ensure_compile_cache()

    parent.mkdir()
    q._ensure_compile_cache()
    assert child.is_dir()
    assert not child.is_symlink()


def test_compile_cache_rejects_redirected_registered_parent(monkeypatch, tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    parent = tmp_path / "compile-cache-c0"
    parent.symlink_to(target, target_is_directory=True)
    monkeypatch.setattr(q, "COMPILE_CACHE_PARENT", parent)
    monkeypatch.setattr(q, "COMPILE_CACHE", parent / "qwen38-flash-next-d453-c0")

    with pytest.raises(q.QualificationError, match="absent or redirected"):
        q._ensure_compile_cache()


class FakeMonitor:
    failure = None
    emergency_stop_at = None
    samples = 8
    minimum_observed_gib = 42.0

    def __init__(self, path, ops, **kwargs):
        self.path = path
        self.ops = ops
        self.cancel_event = threading.Event()
        self.armed = None
        self.initial_pswpout = 10
        self.final_pswpout = 10
        self.mutation_initial_pswpout = None
        self.mutation_final_pswpout = None
        self.mutation_window_started_at = None
        self.mutation_final_sample_at = None
        self.startup_initial_pswpout = None
        self.startup_final_pswpout = None
        self.setup_quiescence_passed = False
        self.setup_quiescence_started_at = None
        self.setup_quiescence_completed_at = None
        self.setup_quiescence_duration_seconds = None
        self.setup_quiescence_initial_pswpout = None
        self.setup_quiescence_final_pswpout = None
        self.setup_quiescence_samples = 0
        self.ready_quiescence_passed = False
        self.ready_quiescence_started_at = None
        self.ready_quiescence_completed_at = None
        self.ready_quiescence_duration_seconds = None
        self.ready_quiescence_initial_pswpout = None
        self.ready_quiescence_final_pswpout = None
        self.ready_quiescence_samples = 0
        self.ready_quiescence_epoch = 0
        self.candidate_cgroup_bound_path = None
        self.candidate_cgroup_bound_pid = None
        self.candidate_cgroup_start_ticks = None
        self.candidate_cgroup_samples = 0
        self.candidate_cgroup_swap_peak_bytes = 0
        self.candidate_cgroup_oom_initial = None
        self.candidate_cgroup_oom_final = None
        self.candidate_cgroup_oom_kill_initial = None
        self.candidate_cgroup_oom_kill_final = None
        self.violations = []
        self.phase_summaries = {
            "setup": {"pswpout_delta_bytes": 0, "threshold_breached": False}
        }

    def __enter__(self):
        self.path.write_text("")
        return self

    def __exit__(self, *args):
        return False

    def check(self):
        return None

    def reader(self):
        return 64.0

    def require_setup_quiescence(self, *, duration_s, deadline):
        assert duration_s == 60
        assert deadline > time.monotonic()
        self.setup_quiescence_passed = True
        self.setup_quiescence_started_at = "2026-09-15T00:00:00+00:00"
        self.setup_quiescence_completed_at = "2026-09-15T00:01:00+00:00"
        self.setup_quiescence_duration_seconds = 60.0
        self.setup_quiescence_initial_pswpout = 10
        self.setup_quiescence_final_pswpout = 10
        self.setup_quiescence_samples = 61

    def begin_mutation_window(self):
        assert self.setup_quiescence_passed
        self.mutation_initial_pswpout = 10
        self.mutation_final_pswpout = 10
        self.mutation_window_started_at = "2026-09-15T00:01:01+00:00"
        self.mutation_final_sample_at = "2026-09-15T00:02:00+00:00"
        self.startup_initial_pswpout = 10
        self.startup_final_pswpout = 10

    def arm(self, candidate_id):
        self.armed = candidate_id
        self.candidate_cgroup_bound_path = (
            f"/system.slice/docker-{candidate_id}.scope"
        )
        self.candidate_cgroup_bound_pid = 200
        self.candidate_cgroup_start_ticks = 12345
        self.candidate_cgroup_samples = 1
        self.candidate_cgroup_oom_initial = 0
        self.candidate_cgroup_oom_final = 0
        self.candidate_cgroup_oom_kill_initial = 0
        self.candidate_cgroup_oom_kill_final = 0

    def require_ready_quiescence(self, *, duration_s, deadline):
        assert duration_s == 60
        assert deadline > time.monotonic()
        self.ready_quiescence_passed = True
        self.ready_quiescence_started_at = "2026-09-15T00:02:00+00:00"
        self.ready_quiescence_completed_at = "2026-09-15T00:03:00+00:00"
        self.ready_quiescence_duration_seconds = 60.0
        self.ready_quiescence_initial_pswpout = 10
        self.ready_quiescence_final_pswpout = 10
        self.ready_quiescence_samples = 61
        self.ready_quiescence_epoch = 1
        self.phase_summaries["load"] = {
            "pswpout_delta_bytes": 0,
            "threshold_breached": False,
        }
        self.phase_summaries["ready"] = {
            "pswpout_delta_bytes": 0,
            "threshold_breached": False,
        }
        self.phase_summaries["probes"] = {
            "pswpout_delta_bytes": 0,
            "threshold_breached": False,
        }

    def begin_restoration(self):
        self.phase_summaries["restoration"] = {
            "pswpout_delta_bytes": 0,
            "threshold_breached": False,
        }

    def disarm(self):
        self.armed = None


class BreachAfterStartMonitor(FakeMonitor):
    def check(self):
        if self.armed:
            self.failure = "MemAvailable 19.000 GiB fell below 20 GiB"
            self.cancel_event.set()
            raise q.QualificationError(self.failure)


class FakeOps(q.HostOps):
    candidate_id = "c" * 64

    def __init__(self, *, nara_active=True):
        self.log = []
        self.nara_active = nara_active
        self.containers = {
            row["name"]: {
                "id": row["id"],
                "name": row["name"],
                "image": row["image_id"],
                "running": True,
                "pid": 100,
                "started_at": "before",
                "finished_at": "",
                "oom_killed": False,
                "state_error": "",
                "restart_count": 0,
                "restart_policy": "unless-stopped",
            }
            for row in q.RESIDENTS
        }

    def _container(self, identity):
        for row in self.containers.values():
            if identity in {row["id"], row["name"]}:
                return row
        return None

    def run(self, argv, *, timeout, check=True):
        self.log.append(tuple(argv))
        if argv[:3] == ["docker", "image", "inspect"]:
            return q.CommandResult(0, f"{q.IMAGE_ID} arm64\n", "")
        if argv[:2] == ["docker", "create"]:
            self.containers[q.CONTAINER_NAME] = {
                "id": self.candidate_id,
                "name": q.CONTAINER_NAME,
                "image": q.IMAGE_ID,
                "running": False,
                "pid": 0,
                "started_at": "",
                "oom_killed": False,
                "state_error": "",
                "restart_count": 0,
                "restart_policy": "no",
            }
            return q.CommandResult(0, self.candidate_id + "\n", "")
        if argv[:2] == ["docker", "inspect"]:
            row = self._container(argv[-1])
            return (
                q.CommandResult(0, json.dumps(row) + "\n", "")
                if row
                else q.CommandResult(1, "", f"Error: No such object: {argv[-1]}")
            )
        if argv[:2] == ["docker", "stop"]:
            row = self._container(argv[-1])
            if row:
                row["running"] = False
            return q.CommandResult(0, (row or {}).get("id", "") + "\n", "")
        if argv[:2] == ["docker", "start"]:
            row = self._container(argv[-1])
            if row:
                row["running"] = True
                if row["name"] == q.CONTAINER_NAME:
                    row["pid"] = 200
            return q.CommandResult(0, (row or {}).get("id", "") + "\n", "")
        if argv[:2] == ["docker", "rm"]:
            row = self._container(argv[-1])
            if row:
                self.containers.pop(row["name"])
            return q.CommandResult(0, argv[-1] + "\n", "")
        if argv[:4] == ["systemctl", "--user", "show", q.NARA_SERVICE]:
            state = "active" if self.nara_active else "inactive"
            return q.CommandResult(0, f"ActiveState={state}\nSubState={'running' if self.nara_active else 'dead'}\nMainPID={'123' if self.nara_active else '0'}\n", "")
        if argv[:4] == ["systemctl", "--user", "stop", q.NARA_SERVICE]:
            self.nara_active = False
            return q.CommandResult(0, "", "")
        if argv[:4] == ["systemctl", "--user", "start", q.NARA_SERVICE]:
            self.nara_active = True
            return q.CommandResult(0, "", "")
        raise AssertionError(argv)

    def http_bytes(self, url, *, timeout):
        self.log.append(("HTTP", url))
        if url.endswith("/v1/models"):
            return json.dumps({"object": "list", "data": [{"id": q.SERVED_MODEL}]}).encode()
        return b"OK"

    def complete(self, endpoint, messages, **kwargs):
        self.log.append(("COMPLETE", messages[0]["content"]))
        base = {
            "response_model": q.SERVED_MODEL,
            "reasoning_content": "",
            "usage": {"prompt_tokens": 4, "completion_tokens": 1, "total_tokens": 5},
            "latency_s": 0.01,
            "ttft_s": 0.005,
            "request_sha256": "1" * 64,
            "response_stream_sha256": "2" * 64,
        }
        if kwargs.get("tools"):
            return {
                **base,
                "content": "",
                "tool_calls": [{
                    "id": "call1",
                    "type": "function",
                    "function": {
                        "name": "record_probe",
                        "arguments": '{"label":"flash-next","value":703}',
                    },
                }],
                "finish_reason": "tool_calls",
            }
        answer = "703" if "37 * 19" in messages[0]["content"] else "FLASH_NEXT_OK_17"
        return {**base, "content": answer, "tool_calls": [], "finish_reason": "stop"}


def clean_cgroup(candidate_id, pid, *, swap=0, oom=0, oom_kill=0):
    assert candidate_id == FakeOps.candidate_id
    assert pid == 200
    return {
        "path": f"/system.slice/docker-{candidate_id}.scope",
        "process_start_ticks": 12345,
        "memory_swap_current_bytes": swap,
        "memory_events_oom": oom,
        "memory_events_oom_kill": oom_kill,
    }


def manual_monitor(
    tmp_path,
    ops,
    *,
    swap_reader=lambda: 10,
    cgroup_reader=clean_cgroup,
):
    monitor = q.MemoryMonitor(
        tmp_path / "memory.jsonl",
        ops,
        reader=lambda: 64.0,
        swap_reader=swap_reader,
        cgroup_reader=cgroup_reader,
    )
    monitor._stream = (tmp_path / "memory.jsonl").open("xb")
    monitor._sample_once()
    monitor.setup_quiescence_passed = True
    monitor.setup_quiescence_final_pswpout = monitor.final_pswpout
    monitor.begin_mutation_window()
    return monitor


def preflight(root, *, idle):
    assert idle is True
    return {
        "mem_available_gib": 42.0,
        "runtime_identity": [{"id": row["id"]} for row in q.RESIDENTS],
    }


@contextmanager
def fake_lease(root):
    yield (10, 11, 12)


def prepare_execution(monkeypatch, tmp_path, *, nara_active=True, monitor=FakeMonitor):
    output = tmp_path / "qfn-c0-unit"
    output.mkdir()
    ops = FakeOps(nara_active=nara_active)
    usage = []
    monkeypatch.delenv("MOCK_LLM", raising=False)
    monkeypatch.setattr(q, "canonical_root", lambda root: tmp_path)
    monkeypatch.setattr(q, "resource_lease", fake_lease)
    monkeypatch.setattr(q, "verify_model", lambda *args, **kwargs: {"full_sha256": True})
    monkeypatch.setattr(q, "_assert_port_free", lambda: None)
    monkeypatch.setattr(q, "_ensure_compile_cache", lambda: None)
    monkeypatch.setattr(q, "_append_research_usage", lambda row, ledger=q.RESEARCH_LEDGER: usage.append((ledger, row)))
    result = q.execute_worker(
        plan(), contract(), output, ops=ops, preflight_probe=preflight,
        monitor_factory=monitor,
    )
    return result, ops, usage, output


def test_success_creates_sentinel_first_and_restores_exact_ids(monkeypatch, tmp_path):
    result, ops, usage, output = prepare_execution(monkeypatch, tmp_path)
    assert result["status"] == "passed"
    assert result["restoration"]["status"] == "verified"
    assert result["probe_count"] == 3
    assert result["weekly_budget_debit"] is False
    assert result["paid_api_calls"] == 0
    assert q.CONTAINER_NAME not in ops.containers
    assert all(ops.containers[row["name"]]["running"] for row in q.RESIDENTS)
    assert ops.nara_active is True

    create = next(i for i, row in enumerate(ops.log) if row[:2] == ("docker", "create"))
    nara_stop = next(i for i, row in enumerate(ops.log) if row[:4] == ("systemctl", "--user", "stop", q.NARA_SERVICE))
    resident_stops = [
        i for i, row in enumerate(ops.log)
        if row[:4] == ("docker", "stop", "--time", "30")
    ]
    candidate_start = next(i for i, row in enumerate(ops.log) if row == ("docker", "start", ops.candidate_id))
    candidate_stop = next(i for i, row in enumerate(ops.log) if row == ("docker", "stop", "--time", "20", ops.candidate_id))
    resident_starts = [i for i, row in enumerate(ops.log) if row[:2] == ("docker", "start") and row[-1] != ops.candidate_id]
    resident_health = [
        next(
            i
            for i, action in enumerate(ops.log)
            if i > resident_starts[index]
            and action == ("HTTP", resident["health_url"])
        )
        for index, resident in enumerate(q.RESIDENTS)
    ]
    nara_start = next(i for i, row in enumerate(ops.log) if row[:4] == ("systemctl", "--user", "start", q.NARA_SERVICE))
    sentinel_rm = next(i for i, row in enumerate(ops.log) if row == ("docker", "rm", ops.candidate_id))
    assert create < nara_stop < min(resident_stops) < candidate_start
    assert candidate_start < candidate_stop < min(resident_starts) < nara_start < sentinel_rm
    assert resident_starts[0] < resident_health[0] < resident_starts[1] < resident_health[1]
    assert not any(row[:2] == ("docker", "rm") and row[-1] in {item["id"] for item in q.RESIDENTS} for row in ops.log)
    assert [item[1]["event"] for item in usage] == ["started", "finished"]
    assert all(item[0] == q.RESEARCH_LEDGER for item in usage)
    assert json.loads((output / "result.json").read_text())["status"] == "passed"
    assert result["resident_downtime_seconds"] >= result["challenger_gpu_seconds"]
    assert result["resident_downtime_seconds_basis"] == (
        "monotonic_resident_stop_to_restoration_completion_upper_bound"
    )
    assert result["failure_stage"] is None
    assert result["setup_quiescence_passed"] is True
    assert result["mutation_pswpout_delta_pages"] == 0
    state = json.loads((output / "state.json").read_text())
    assert state["schema"] == "qwen-flash-next-qualification-state/v3"
    assert state["worker_pid"] > 0 and state["worker_start_ticks"] > 0
    assert state["memory_log_relpath"] == "memory.jsonl"


def test_finished_usage_is_durable_before_result_publication(monkeypatch, tmp_path):
    output = tmp_path / "qfn-c0-ledger-fault"
    output.mkdir()
    ops = FakeOps()
    usage = []

    def append_usage(row, ledger=q.RESEARCH_LEDGER):
        usage.append((ledger, row))
        if row["event"] == "finished":
            raise OSError("injected ledger failure")

    monkeypatch.delenv("MOCK_LLM", raising=False)
    monkeypatch.setattr(q, "canonical_root", lambda root: tmp_path)
    monkeypatch.setattr(q, "resource_lease", fake_lease)
    monkeypatch.setattr(q, "verify_model", lambda *args, **kwargs: {"full_sha256": True})
    monkeypatch.setattr(q, "_assert_port_free", lambda: None)
    monkeypatch.setattr(q, "_ensure_compile_cache", lambda: None)
    monkeypatch.setattr(q, "_append_research_usage", append_usage)

    recovery_plan = plan()
    with pytest.raises(OSError, match="injected ledger failure"):
        q.execute_worker(
            recovery_plan,
            contract(),
            output,
            ops=ops,
            preflight_probe=preflight,
            monitor_factory=FakeMonitor,
        )

    assert not (output / "result.json").exists()
    assert [row[1]["event"] for row in usage] == ["started", "finished"]
    assert q.CONTAINER_NAME not in ops.containers
    assert all(ops.containers[row["name"]]["running"] for row in q.RESIDENTS)
    assert ops.nara_active is True

    recovery_usage = []
    monkeypatch.setattr(q, "_append_research_usage", lambda row: recovery_usage.append(row))
    receipt = q.supervisor_emergency_restore(
        output,
        recovery_plan,
        deadline=time.monotonic() + 30,
        ops=ops,
    )
    assert receipt["status"] == "verified"
    assert receipt["restoration"]["sentinel_retained"] is False
    assert recovery_usage[0]["event"] == "supervisor_recovery"


def test_initially_inactive_nara_is_never_stopped_or_started(monkeypatch, tmp_path):
    result, ops, _, _ = prepare_execution(monkeypatch, tmp_path, nara_active=False)
    assert result["status"] == "passed"
    service_mutations = [row for row in ops.log if row[:3] in {
        ("systemctl", "--user", "stop"), ("systemctl", "--user", "start")
    }]
    assert service_mutations == []
    assert ops.nara_active is False


def test_memory_failure_restores_and_fails_closed(monkeypatch, tmp_path):
    result, ops, _, _ = prepare_execution(
        monkeypatch, tmp_path, monitor=BreachAfterStartMonitor
    )
    assert result["status"] == "failed"
    assert "below 20 GiB" in result["qualification_error"]
    assert result["failure_stage"] == "candidate_start"
    assert result["restoration"]["status"] == "verified"
    assert q.CONTAINER_NAME not in ops.containers
    assert all(ops.containers[row["name"]]["running"] for row in q.RESIDENTS)


def test_unverified_resident_readiness_retains_watchdog_sentinel():
    ops = FakeOps()
    ops.containers[q.CONTAINER_NAME] = {
        "id": ops.candidate_id, "name": q.CONTAINER_NAME, "image": q.IMAGE_ID,
        "running": True, "pid": 200, "started_at": "now", "restart_count": 0,
        "restart_policy": "no",
    }
    initial = {
        "residents": [dict(ops.containers[row["name"]], running=True) for row in q.RESIDENTS],
        "nara_was_active": True,
    }
    for row in q.RESIDENTS:
        ops.containers[row["name"]]["running"] = False
    state = {"candidate_id": ops.candidate_id, "initial": initial}
    restored = q.restore_exact(ops, state, deadline=time.monotonic())
    assert restored["status"] == "unknown"
    assert restored["sentinel_retained"] is True
    assert q.CONTAINER_NAME in ops.containers


def test_memory_monitor_breach_stops_only_the_exact_candidate(tmp_path):
    ops = FakeOps()
    ops.containers[q.CONTAINER_NAME] = {
        "id": ops.candidate_id, "name": q.CONTAINER_NAME, "image": q.IMAGE_ID,
        "running": True, "pid": 200, "started_at": "now", "restart_count": 0,
        "oom_killed": False,
        "restart_policy": "no",
    }
    monitor = manual_monitor(tmp_path, ops)
    monitor.arm(ops.candidate_id)
    monitor._breach("MemAvailable below floor")
    monitor._stream.close()
    assert ("docker", "stop", "--time", "10", ops.candidate_id) in ops.log
    assert all(
        not (row[:2] == ("docker", "stop") and row[-1] in {item["id"] for item in q.RESIDENTS})
        for row in ops.log
    )


def test_candidate_stop_uncertainty_withholds_residents_and_nara(tmp_path):
    class StopFailure(FakeOps):
        def run(self, argv, *, timeout, check=True):
            if argv == ["docker", "stop", "--time", "20", self.candidate_id]:
                self.log.append(tuple(argv))
                raise q.QualificationError("injected stop uncertainty")
            return super().run(argv, timeout=timeout, check=check)

    ops = StopFailure()
    ops.nara_active = False
    ops.containers[q.CONTAINER_NAME] = {
        "id": ops.candidate_id, "name": q.CONTAINER_NAME, "image": q.IMAGE_ID,
        "running": True, "pid": 200, "started_at": "now", "restart_count": 0,
        "restart_policy": "no",
    }
    initial = {
        "residents": [dict(ops.containers[row["name"]], running=True) for row in q.RESIDENTS],
        "nara_was_active": True,
    }
    for row in q.RESIDENTS:
        ops.containers[row["name"]]["running"] = False
    restored = q.restore_exact(
        ops,
        {"candidate_id": ops.candidate_id, "initial": initial},
        deadline=time.monotonic() + 30,
        diagnostic_path=tmp_path / "candidate.log",
    )
    assert restored["status"] == "unknown"
    assert "withheld" in " ".join(restored["errors"])
    assert not any(row[:2] == ("docker", "start") for row in ops.log)
    assert not any(row[:3] == ("systemctl", "--user", "start") for row in ops.log)


def test_no_mutation_preflight_failure_is_verified_without_restore_actions():
    ops = FakeOps()
    restored = q.restore_exact(
        ops, {"candidate_id": None, "initial": None}, deadline=time.monotonic() + 10
    )
    assert restored["status"] == "verified"
    assert restored["no_mutation_verified"] is True
    assert not any(row[:2] in {("docker", "start"), ("docker", "stop"), ("docker", "rm")} for row in ops.log)


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("oom_killed", True, "OOMKilled"),
        ("restart_count", 1, "restart count"),
        ("pid", 201, "process identity"),
    ],
)
def test_monitor_rejects_candidate_lifecycle_drift(tmp_path, field, value, expected):
    ops = FakeOps()
    ops.containers[q.CONTAINER_NAME] = {
        "id": ops.candidate_id, "name": q.CONTAINER_NAME, "image": q.IMAGE_ID,
        "running": True, "pid": 200, "started_at": "now",
        "oom_killed": False, "restart_count": 0,
        "restart_policy": "no",
    }
    monitor = manual_monitor(tmp_path, ops)
    monitor.arm(ops.candidate_id)
    ops.containers[q.CONTAINER_NAME][field] = value
    monitor._sample_once()
    monitor._stream.close()
    assert monitor.cancel_event.is_set()
    assert expected in monitor.failure
    assert ("docker", "stop", "--time", "10", ops.candidate_id) in ops.log


@pytest.mark.parametrize(
    ("swap", "oom", "oom_kill", "expected"),
    [
        (4096, 0, 0, "memory.swap.current"),
        (0, 1, 0, "OOM event"),
        (0, 0, 1, "OOM-kill"),
    ],
)
def test_monitor_rejects_candidate_cgroup_pressure(
    tmp_path, swap, oom, oom_kill, expected
):
    ops = FakeOps()
    ops.containers[q.CONTAINER_NAME] = {
        "id": ops.candidate_id,
        "name": q.CONTAINER_NAME,
        "image": q.IMAGE_ID,
        "running": True,
        "pid": 200,
        "started_at": "now",
        "oom_killed": False,
        "restart_count": 0,
        "restart_policy": "no",
    }
    snapshots = iter(
        [
            clean_cgroup(ops.candidate_id, 200),
            clean_cgroup(ops.candidate_id, 200),
            clean_cgroup(
                ops.candidate_id,
                200,
                swap=swap,
                oom=oom,
                oom_kill=oom_kill,
            ),
        ]
    )
    monitor = manual_monitor(
        tmp_path, ops, cgroup_reader=lambda *_args: next(snapshots)
    )
    monitor.arm(ops.candidate_id)
    monitor._sample_once()
    monitor._stream.close()
    assert monitor.cancel_event.is_set()
    assert expected in monitor.failure


def test_small_host_swap_is_diagnostic_but_registered_load_threshold_stops(tmp_path):
    threshold_pages = q.LOAD_SWAP_5S_BREACH_BYTES // q.HOST_PAGE_SIZE_BYTES
    values = iter([10, 10, 11, 10 + threshold_pages])
    ops = FakeOps()
    monitor = q.MemoryMonitor(
        tmp_path / "memory.jsonl",
        ops,
        reader=lambda: 64.0,
        swap_reader=lambda: next(values),
        cgroup_reader=clean_cgroup,
    )
    monitor._stream = (tmp_path / "memory.jsonl").open("xb")
    monitor._sample_once()
    monitor.setup_quiescence_passed = True
    monitor.setup_quiescence_final_pswpout = 10
    monitor.begin_mutation_window()
    small = monitor._sample_once()
    assert small["phase_pswpout_delta_bytes"] == q.HOST_PAGE_SIZE_BYTES
    assert not monitor.cancel_event.is_set()
    monitor._sample_once()
    monitor._stream.close()
    assert monitor.cancel_event.is_set()
    assert "5-second byte threshold" in monitor.failure


def test_startup_total_gate_is_cumulative_across_load_and_ready(tmp_path):
    page_size = q.HOST_PAGE_SIZE_BYTES
    four_mib_pages = 4 * 1024**2 // page_size
    pages = [10]
    clock = [100.0]
    monitor = q.MemoryMonitor(
        tmp_path / "startup-total.jsonl",
        FakeOps(),
        reader=lambda: 64.0,
        swap_reader=lambda: pages[0],
        cgroup_reader=clean_cgroup,
        clock=lambda: clock[0],
    )
    monitor._stream = (tmp_path / "startup-total.jsonl").open("xb")
    monitor._sample_once()
    monitor.setup_quiescence_passed = True
    monitor.setup_quiescence_final_pswpout = pages[0]
    monitor.begin_mutation_window()

    for _ in range(75):
        clock[0] += 1
        pages[0] += four_mib_pages
        monitor._sample_once()
    monitor._sample_once(begin_phase="ready")
    assert monitor.phase_summaries["load"]["pswpout_delta_bytes"] == 300 * 1024**2
    assert not monitor.cancel_event.is_set()

    final = None
    for _ in range(53):
        clock[0] += 1
        pages[0] += four_mib_pages
        final = monitor._sample_once()
    monitor._stream.close()

    assert final is not None
    assert final["paging_gate"] == "startup"
    assert final["phase_pswpout_delta_bytes"] == 212 * 1024**2
    assert final["gate_pswpout_delta_bytes"] == q.LOAD_SWAP_TOTAL_BREACH_BYTES
    assert final["host_swap_60s_bytes"] < q.LOAD_SWAP_60S_BREACH_BYTES
    assert monitor.cancel_event.is_set()
    assert "startup host swap reached the gate-total" in monitor.failure


def test_startup_rolling_gate_spans_the_load_to_ready_boundary(tmp_path):
    seventy_mib_pages = 70 * 1024**2 // q.HOST_PAGE_SIZE_BYTES
    pages = [10]
    clock = [100.0]
    monitor = q.MemoryMonitor(
        tmp_path / "startup-window.jsonl",
        FakeOps(),
        reader=lambda: 64.0,
        swap_reader=lambda: pages[0],
        cgroup_reader=clean_cgroup,
        clock=lambda: clock[0],
    )
    monitor._stream = (tmp_path / "startup-window.jsonl").open("xb")
    monitor._sample_once()
    monitor.setup_quiescence_passed = True
    monitor.setup_quiescence_final_pswpout = pages[0]
    monitor.begin_mutation_window()
    clock[0] += 1
    pages[0] += seventy_mib_pages
    monitor._sample_once()
    clock[0] += 1
    pages[0] += seventy_mib_pages
    ready = monitor._sample_once(begin_phase="ready")
    monitor._stream.close()

    assert ready["paging_gate"] == "startup"
    assert ready["phase_pswpout_delta_bytes"] == 70 * 1024**2
    assert ready["gate_pswpout_delta_bytes"] == 140 * 1024**2
    assert ready["host_swap_5s_bytes"] == 140 * 1024**2
    assert monitor.cancel_event.is_set()
    assert "startup host swap reached the 5-second" in monitor.failure


def test_restoration_host_paging_is_diagnostic_and_does_not_interrupt(tmp_path):
    pages = iter([10, 10, 10 + (2 * 1024**3 // q.HOST_PAGE_SIZE_BYTES)])
    monitor = q.MemoryMonitor(
        tmp_path / "memory.jsonl",
        FakeOps(),
        reader=lambda: 64.0,
        swap_reader=lambda: next(pages),
        cgroup_reader=clean_cgroup,
    )
    monitor._stream = (tmp_path / "memory.jsonl").open("xb")
    monitor._sample_once()
    monitor.setup_quiescence_passed = True
    monitor.setup_quiescence_final_pswpout = 10
    monitor.begin_mutation_window()
    row = monitor._sample_once(begin_phase="restoration")
    monitor._stream.close()
    assert row["phase_pswpout_delta_bytes"] == 2 * 1024**3
    assert monitor.cancel_event.is_set() is False
    assert monitor.phase_summaries["restoration"]["threshold_breached"] is False


def test_monitor_records_setup_swap_but_rejects_gap_churn_before_mutation(tmp_path):
    values = iter([10, 11, 12])
    ops = FakeOps()
    monitor = q.MemoryMonitor(
        tmp_path / "setup-swap.jsonl",
        ops,
        reader=lambda: 64.0,
        swap_reader=lambda: next(values),
    )
    monitor._stream = (tmp_path / "setup-swap.jsonl").open("xb")
    monitor._sample_once()
    row = monitor._sample_once()
    assert row["monitor_phase"] == "setup"
    assert row["phase_pswpout_delta_pages"] == 1
    assert not monitor.cancel_event.is_set()
    monitor.setup_quiescence_passed = True
    monitor.setup_quiescence_final_pswpout = 11
    with pytest.raises(q.QualificationError, match="changed after setup quiescence"):
        monitor.begin_mutation_window()
    monitor._stream.close()


def test_monitor_rejects_counter_decrease_even_when_still_above_initial(tmp_path):
    values = iter([10, 12, 11])
    monitor = q.MemoryMonitor(
        tmp_path / "decrease.jsonl",
        FakeOps(),
        reader=lambda: 64.0,
        swap_reader=lambda: next(values),
        cgroup_reader=clean_cgroup,
    )
    monitor._stream = (tmp_path / "decrease.jsonl").open("xb")
    monitor._sample_once()
    monitor._sample_once()
    with pytest.raises(ValueError, match="decreased"):
        monitor._sample_once()
    monitor._stream.close()


def test_monitor_rejects_a_live_sample_gap_over_registered_limit(tmp_path):
    clock = [100.0]
    monitor = q.MemoryMonitor(
        tmp_path / "gap.jsonl",
        FakeOps(),
        reader=lambda: 64.0,
        swap_reader=lambda: 10,
        cgroup_reader=clean_cgroup,
        clock=lambda: clock[0],
    )
    monitor._stream = (tmp_path / "gap.jsonl").open("xb")
    first = monitor._sample_once()
    clock[0] += q.MAX_SAMPLE_GAP_SECONDS + 0.001
    second = monitor._sample_once()
    monitor._stream.close()
    assert first["sample_gap_seconds"] == 0
    assert second["sample_gap_seconds"] > q.MAX_SAMPLE_GAP_SECONDS
    assert monitor.cancel_event.is_set()
    assert "sample-gap" in monitor.failure


def test_check_stops_an_armed_candidate_when_monitor_sample_is_stale(tmp_path):
    clock = [100.0]
    ops = FakeOps()
    ops.containers[q.CONTAINER_NAME] = {
        "id": ops.candidate_id,
        "name": q.CONTAINER_NAME,
        "image": q.IMAGE_ID,
        "running": True,
        "pid": 200,
        "started_at": "now",
        "oom_killed": False,
        "restart_count": 0,
        "restart_policy": "no",
    }
    monitor = q.MemoryMonitor(
        tmp_path / "stale.jsonl",
        ops,
        reader=lambda: 64.0,
        swap_reader=lambda: 10,
        cgroup_reader=clean_cgroup,
        clock=lambda: clock[0],
    )
    monitor._stream = (tmp_path / "stale.jsonl").open("xb")
    monitor._sample_once()
    monitor.setup_quiescence_passed = True
    monitor.setup_quiescence_final_pswpout = 10
    monitor.begin_mutation_window()
    monitor.arm(ops.candidate_id)
    clock[0] += q.MAX_SAMPLE_GAP_SECONDS + 0.001
    with pytest.raises(q.QualificationError, match="stale"):
        monitor.check()
    monitor._stream.close()
    assert ("docker", "stop", "--time", "10", ops.candidate_id) in ops.log


def test_setup_quiescence_records_a_full_sixty_second_sample_span(
    monkeypatch, tmp_path
):
    clock = [100.0]
    monkeypatch.setattr(q.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(q.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    monitor = q.MemoryMonitor(
        tmp_path / "quiet.jsonl",
        FakeOps(),
        reader=lambda: 64.0,
        swap_reader=lambda: 10,
    )
    monitor._stream = (tmp_path / "quiet.jsonl").open("xb")
    monitor._sample_once()
    monitor.require_setup_quiescence(duration_s=60, deadline=161.0)
    monitor._stream.close()
    assert monitor.setup_quiescence_passed is True
    assert monitor.setup_quiescence_duration_seconds == 60.0
    assert monitor.setup_quiescence_samples >= 2


def test_ready_quiescence_restarts_then_proves_a_fresh_sixty_seconds(
    monkeypatch, tmp_path
):
    clock = [100.0]
    monkeypatch.setattr(q.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        q.time,
        "sleep",
        lambda seconds: clock.__setitem__(0, clock[0] + seconds),
    )
    ops = FakeOps()
    ops.containers[q.CONTAINER_NAME] = {
        "id": ops.candidate_id,
        "name": q.CONTAINER_NAME,
        "image": q.IMAGE_ID,
        "running": True,
        "pid": 200,
        "started_at": "now",
        "oom_killed": False,
        "restart_count": 0,
        "restart_policy": "no",
    }
    monitor = q.MemoryMonitor(
        tmp_path / "ready.jsonl",
        ops,
        reader=lambda: 64.0,
        swap_reader=lambda: 10 if clock[0] < 130 else 11,
        cgroup_reader=clean_cgroup,
    )
    monitor._stream = (tmp_path / "ready.jsonl").open("xb")
    monitor._sample_once()
    monitor.setup_quiescence_passed = True
    monitor.setup_quiescence_final_pswpout = 10
    monitor.begin_mutation_window()
    monitor.arm(ops.candidate_id)
    monitor.require_ready_quiescence(duration_s=60, deadline=192.0)
    monitor._stream.close()

    assert monitor.ready_quiescence_passed is True
    assert monitor.ready_quiescence_epoch == 2
    assert monitor.ready_quiescence_initial_pswpout == 11
    assert monitor.ready_quiescence_final_pswpout == 11
    assert monitor.ready_quiescence_duration_seconds >= 60
    rows = [
        json.loads(line)
        for line in (tmp_path / "ready.jsonl").read_text().splitlines()
    ]
    ready = [row for row in rows if row.get("monitor_phase") == "ready"]
    assert ready[-1]["transition_to"] == "probes"
    assert ready[-1]["elapsed_monotonic_seconds"] - next(
        row["elapsed_monotonic_seconds"]
        for row in ready
        if row.get("ready_quiescence_epoch") == 2
    ) >= 60


def test_arm_requires_clean_exact_pid_cgroup_and_preserves_binding(tmp_path):
    ops = FakeOps()
    ops.containers[q.CONTAINER_NAME] = {
        "id": ops.candidate_id,
        "name": q.CONTAINER_NAME,
        "image": q.IMAGE_ID,
        "running": True,
        "pid": 200,
        "started_at": "now",
        "oom_killed": False,
        "restart_count": 0,
        "restart_policy": "no",
    }
    monitor = manual_monitor(tmp_path, ops)
    monitor.arm(ops.candidate_id)
    monitor.disarm()
    monitor._stream.close()
    assert monitor.candidate_cgroup_bound_path == (
        f"/system.slice/docker-{ops.candidate_id}.scope"
    )
    assert monitor.candidate_cgroup_bound_pid == 200
    assert monitor.candidate_cgroup_start_ticks == 12345


def test_arm_records_binding_before_publishing_to_background_sampler(tmp_path):
    ops = FakeOps()
    ops.containers[q.CONTAINER_NAME] = {
        "id": ops.candidate_id,
        "name": q.CONTAINER_NAME,
        "image": q.IMAGE_ID,
        "running": True,
        "pid": 200,
        "started_at": "now",
        "oom_killed": False,
        "restart_count": 0,
        "restart_policy": "no",
    }
    monitor = manual_monitor(tmp_path, ops)
    original_record = monitor._record
    bind_entered = threading.Event()
    release_bind = threading.Event()
    sample_started = threading.Event()
    sample_finished = threading.Event()

    def blocked_record(row):
        if row.get("schema") == "qwen-flash-next-cgroup-bind/v1":
            bind_entered.set()
            assert release_bind.wait(2)
        original_record(row)

    monitor._record = blocked_record
    arm_thread = threading.Thread(target=monitor.arm, args=(ops.candidate_id,))
    arm_thread.start()
    assert bind_entered.wait(2)

    def sample():
        sample_started.set()
        monitor._sample_once()
        sample_finished.set()

    sample_thread = threading.Thread(target=sample)
    sample_thread.start()
    assert sample_started.wait(2)
    assert not sample_finished.wait(0.05)
    release_bind.set()
    arm_thread.join(2)
    sample_thread.join(2)
    assert not arm_thread.is_alive()
    assert not sample_thread.is_alive()
    monitor._stream.close()

    rows = [
        json.loads(line)
        for line in (tmp_path / "memory.jsonl").read_text().splitlines()
    ]
    bind_index = next(
        index
        for index, row in enumerate(rows)
        if row.get("schema") == "qwen-flash-next-cgroup-bind/v1"
    )
    armed_indexes = [
        index
        for index, row in enumerate(rows)
        if row.get("candidate", {}).get("armed") is True
    ]
    assert rows[bind_index - 1]["monitor_phase"] == "load"
    assert armed_indexes and bind_index < min(armed_indexes)


def test_arm_refuses_unavailable_or_dirty_cgroup_proof(tmp_path):
    ops = FakeOps()
    ops.containers[q.CONTAINER_NAME] = {
        "id": ops.candidate_id,
        "name": q.CONTAINER_NAME,
        "image": q.IMAGE_ID,
        "running": True,
        "pid": 200,
        "started_at": "now",
        "oom_killed": False,
        "restart_count": 0,
        "restart_policy": "no",
    }
    monitor = manual_monitor(
        tmp_path,
        ops,
        cgroup_reader=lambda *_args: {
            **clean_cgroup(ops.candidate_id, 200),
            "memory_swap_current_bytes": 4096,
        },
    )
    with pytest.raises(q.QualificationError, match="not clean"):
        monitor.arm(ops.candidate_id)
    monitor._stream.close()


def test_cgroup_snapshot_reads_local_events_between_stable_pid_checks(monkeypatch):
    ticks = iter([12345, 12345])
    reads = []

    def bounded(path, *, max_bytes, dir_fd=None):
        reads.append((str(path), max_bytes, dir_fd))
        if str(path).endswith("/cgroup"):
            return f"0::/system.slice/docker-{FakeOps.candidate_id}.scope\n".encode()
        if str(path) == "memory.swap.current":
            return b"0\n"
        if str(path) == "memory.events.local":
            return b"low 0\nhigh 0\nmax 0\noom 0\noom_kill 0\n"
        raise AssertionError(path)

    monkeypatch.setattr(q, "_process_start_ticks", lambda _pid: next(ticks))
    monkeypatch.setattr(q, "_bounded_nofollow_bytes", bounded)
    monkeypatch.setattr(q.os, "open", lambda *_args, **_kwargs: 77)
    monkeypatch.setattr(q.os, "close", lambda _descriptor: None)
    snapshot = q._candidate_cgroup_snapshot(FakeOps.candidate_id, 200)
    assert snapshot["process_start_ticks"] == 12345
    assert any(path == "memory.events.local" for path, _, _ in reads)


def test_cgroup_snapshot_rejects_pid_reuse_across_read(monkeypatch):
    ticks = iter([12345, 54321])

    def bounded(path, *, max_bytes, dir_fd=None):
        if str(path).endswith("/cgroup"):
            return f"0::/system.slice/docker-{FakeOps.candidate_id}.scope\n".encode()
        if str(path) == "memory.swap.current":
            return b"0\n"
        if str(path) == "memory.events.local":
            return b"oom 0\noom_kill 0\n"
        raise AssertionError(path)

    monkeypatch.setattr(q, "_process_start_ticks", lambda _pid: next(ticks))
    monkeypatch.setattr(q, "_bounded_nofollow_bytes", bounded)
    monkeypatch.setattr(q.os, "open", lambda *_args, **_kwargs: 77)
    monkeypatch.setattr(q.os, "close", lambda _descriptor: None)
    with pytest.raises(q.QualificationError, match="changed"):
        q._candidate_cgroup_snapshot(FakeOps.candidate_id, 200)


def test_monitor_ignores_a_stale_lifecycle_sample_after_disarm(tmp_path):
    class DisarmDuringInspect(FakeOps):
        monitor = None

        def run(self, argv, *, timeout, check=True):
            if (
                argv[:2] == ["docker", "inspect"]
                and argv[-1] == self.candidate_id
                and self.monitor._candidate_id == self.candidate_id
            ):
                self.monitor.disarm()
                self.containers[q.CONTAINER_NAME]["running"] = False
            return super().run(argv, timeout=timeout, check=check)

    ops = DisarmDuringInspect()
    ops.containers[q.CONTAINER_NAME] = {
        "id": ops.candidate_id, "name": q.CONTAINER_NAME, "image": q.IMAGE_ID,
        "running": True, "pid": 200, "started_at": "now", "restart_count": 0,
        "oom_killed": False,
        "restart_policy": "no",
    }
    monitor = q.MemoryMonitor(
        tmp_path / "race.jsonl",
        ops,
        reader=lambda: 64.0,
        swap_reader=lambda: 10,
        cgroup_reader=clean_cgroup,
    )
    ops.monitor = monitor
    monitor._stream = (tmp_path / "race.jsonl").open("xb")
    monitor._sample_once()
    monitor.setup_quiescence_passed = True
    monitor.setup_quiescence_final_pswpout = 10
    monitor.begin_mutation_window()
    monitor.arm(ops.candidate_id)
    monitor._sample_once()
    monitor._stream.close()
    assert not monitor.cancel_event.is_set()
    assert monitor.failure is None
    rows = [json.loads(line) for line in (tmp_path / "race.jsonl").read_text().splitlines()]
    candidate_rows = [row for row in rows if "candidate" in row]
    assert candidate_rows[-1]["candidate"]["armed"] is False
    assert candidate_rows[-1]["candidate"]["cgroup"] is None


def test_docker_inspect_operational_error_is_not_treated_as_absence():
    class BrokenInspect(FakeOps):
        def run(self, argv, *, timeout, check=True):
            if argv[:2] == ["docker", "inspect"]:
                return q.CommandResult(1, "", "permission denied")
            return super().run(argv, timeout=timeout, check=check)

    with pytest.raises(q.QualificationError, match="could not verify"):
        q._inspect_container(BrokenInspect(), q.CONTAINER_NAME)


def test_redirect_handler_refuses_even_another_loopback_url():
    with pytest.raises(q.QualificationError, match="redirect"):
        q.NoRedirect().redirect_request(
            None, None, 302, "Found", {}, "http://127.0.0.1:8012/v1/models"
        )


def test_supervisor_can_restore_a_killed_worker_from_durable_exact_ids(
    monkeypatch, tmp_path
):
    output = tmp_path / "qfn-c0-recovery"
    output.mkdir()
    ops = FakeOps()
    ops.nara_active = False
    ops.containers[q.CONTAINER_NAME] = {
        "id": ops.candidate_id, "name": q.CONTAINER_NAME, "image": q.IMAGE_ID,
        "running": True, "pid": 200, "started_at": "now", "restart_count": 0,
        "restart_policy": "no",
    }
    initial = {
        "residents": [dict(ops.containers[row["name"]], running=True) for row in q.RESIDENTS],
        "nara_was_active": True,
    }
    for row in q.RESIDENTS:
        ops.containers[row["name"]]["running"] = False
    recovery_plan = plan()
    state = {
        "schema": "qwen-flash-next-qualification-state/v3",
        "run_id": output.name,
        "phase": "readiness",
        "plan_sha256": q.sha256(recovery_plan),
        "contract_sha256": recovery_plan["contract_sha256"],
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "worker_pid": 123,
        "worker_start_ticks": 456,
        "started_at": "2026-09-15T00:00:00+00:00",
        "updated_at": "2026-09-15T00:00:01+00:00",
        "invocation_deadline_at": "2026-09-15T01:00:00+00:00",
        "memory_log_relpath": "memory.jsonl",
        "monitor_phase": "load",
        "paging_policy": copy.deepcopy(q.PAGING_POLICY),
        "candidate_id": ops.candidate_id,
        "candidate_cgroup_path": None,
        "candidate_cgroup_pid": None,
        "candidate_cgroup_start_ticks": None,
        "initial": initial,
    }
    q._atomic_write(output / "state.json", state)
    usage = []
    monkeypatch.setattr(q, "canonical_root", lambda root: tmp_path)
    monkeypatch.setattr(q, "resource_lease", fake_lease)
    monkeypatch.setattr(q, "_append_research_usage", lambda row: usage.append(row))
    receipt = q.supervisor_emergency_restore(
        output, recovery_plan, deadline=time.monotonic() + 30, ops=ops
    )
    assert receipt["status"] == "verified"
    assert q.CONTAINER_NAME not in ops.containers
    assert all(ops.containers[row["name"]]["running"] for row in q.RESIDENTS)
    assert ops.nara_active is True
    assert usage[0]["event"] == "supervisor_recovery"


def test_recovery_state_requires_every_captured_resident_to_be_running(tmp_path):
    output = tmp_path / "qfn-c0-recovery-stopped-capture"
    output.mkdir()
    ops = FakeOps()
    recovery_plan = plan()
    residents = [dict(ops.containers[row["name"]]) for row in q.RESIDENTS]
    residents[0]["running"] = False
    state = {
        "schema": "qwen-flash-next-qualification-state/v3",
        "run_id": output.name,
        "phase": "readiness",
        "plan_sha256": q.sha256(recovery_plan),
        "contract_sha256": recovery_plan["contract_sha256"],
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "worker_pid": 123,
        "worker_start_ticks": 456,
        "started_at": "2026-09-15T00:00:00+00:00",
        "updated_at": "2026-09-15T00:00:01+00:00",
        "invocation_deadline_at": "2026-09-15T01:00:00+00:00",
        "memory_log_relpath": "memory.jsonl",
        "monitor_phase": "load",
        "paging_policy": copy.deepcopy(q.PAGING_POLICY),
        "candidate_id": None,
        "candidate_cgroup_path": None,
        "candidate_cgroup_pid": None,
        "candidate_cgroup_start_ticks": None,
        "initial": {
            "residents": residents,
            "nara_was_active": True,
        },
    }
    q._atomic_write(output / "state.json", state)

    with pytest.raises(q.QualificationError, match="resident identity is untrusted"):
        q._validated_recovery_state(output, recovery_plan)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (lambda value: value["restoration"].update(errors=["unrestored"]), False),
        (lambda value: value["restoration"].update(sentinel_retained=True), False),
        (lambda value: value["restoration"].update(verified_at="not-a-time"), False),
        (lambda value: None, True),
    ],
)
def test_supervisor_trusts_only_a_clean_time_bound_restoration_result(
    tmp_path, mutation, expected
):
    output = tmp_path / "qfn-c0-result-restoration"
    output.mkdir()
    recovery_plan = plan()
    result = {
        "schema": "qwen-flash-next-qualification-result/v3",
        "run_id": output.name,
        "contract_sha256": recovery_plan["contract_sha256"],
        "plan_sha256": q.sha256(recovery_plan),
        "started_at": "2026-09-15T00:00:00+00:00",
        "finished_at": "2026-09-15T00:02:00+00:00",
        "restoration": {
            "status": "verified",
            "verified_at": "2026-09-15T00:01:59+00:00",
            "errors": [],
            "sentinel_retained": False,
        },
    }
    mutation(result)
    q._atomic_write(output / "result.json", result)

    assert q._result_has_verified_restoration(output, recovery_plan) is expected


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("oom_killed", True),
        ("restart_count", 1),
        ("restart_policy", "always"),
        ("image", "sha256:" + "0" * 64),
        ("running", False),
    ],
)
def test_restore_rejects_resident_drift_after_health(field, value):
    class DriftAfterHealth(FakeOps):
        def http_bytes(self, url, *, timeout):
            raw = super().http_bytes(url, timeout=timeout)
            if url == q.RESIDENTS[0]["health_url"]:
                self.containers[q.RESIDENTS[0]["name"]][field] = value
            return raw

    ops = DriftAfterHealth()
    ops.nara_active = False
    ops.containers[q.CONTAINER_NAME] = {
        "id": ops.candidate_id,
        "name": q.CONTAINER_NAME,
        "image": q.IMAGE_ID,
        "running": True,
        "pid": 200,
        "started_at": "now",
        "restart_count": 0,
        "restart_policy": "no",
    }
    initial = {
        "residents": [dict(ops.containers[row["name"]]) for row in q.RESIDENTS],
        "nara_was_active": True,
    }
    for row in q.RESIDENTS:
        ops.containers[row["name"]]["running"] = False

    restored = q.restore_exact(
        ops,
        {"candidate_id": ops.candidate_id, "initial": initial},
        deadline=time.monotonic() + 30,
    )

    assert restored["status"] == "unknown"
    assert restored["sentinel_retained"] is True
    assert "final state differs" in " ".join(restored["errors"])
    assert ops.nara_active is False


def test_restore_tracks_restart_count_from_each_explicit_start():
    class ResetCountOnExplicitStart(FakeOps):
        def run(self, argv, *, timeout, check=True):
            result = super().run(argv, timeout=timeout, check=check)
            if argv[:2] == ["docker", "start"]:
                self._container(argv[-1])["restart_count"] = 0
            return result

    ops = ResetCountOnExplicitStart(nara_active=False)
    ops.containers[q.CONTAINER_NAME] = {
        "id": ops.candidate_id,
        "name": q.CONTAINER_NAME,
        "image": q.IMAGE_ID,
        "running": True,
        "pid": 200,
        "started_at": "now",
        "restart_count": 0,
        "restart_policy": "no",
    }
    ops.containers[q.RESIDENTS[0]["name"]]["restart_count"] = 7
    initial = {
        "residents": [dict(ops.containers[row["name"]]) for row in q.RESIDENTS],
        "nara_was_active": False,
    }
    for row in q.RESIDENTS:
        ops.containers[row["name"]]["running"] = False

    restored = q.restore_exact(
        ops,
        {"candidate_id": ops.candidate_id, "initial": initial},
        deadline=time.monotonic() + 30,
    )

    assert restored["status"] == "verified"
    assert restored["resident_restart_baselines"] == {
        row["name"]: 0 for row in q.RESIDENTS
    }
