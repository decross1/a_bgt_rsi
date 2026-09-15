"""Real v5 producer to terminal gate, with only host/process I/O injected."""
from __future__ import annotations

import json
import os
import shutil
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from bench.flash_next_ab import (
    followon_canaries,
    harness,
    transport,
)
from bench.flash_next_ab import (
    qualification as q,
)
from bench.flash_next_ab.candidate_registry import MIA
from bench.flash_next_ab.followon_profiles import MIA_MTP3
from bench.flash_next_ab.prepare_followon_contracts import build_contract


class NoThreadMonitor(q.MemoryMonitor):
    """Use the real sample/quiet/phase methods on a virtual one-second clock."""

    def __enter__(self):
        self._stream = self.path.open("xb")
        self._sample_once()
        return self


class FakeHost(q.HostOps):
    cid = "c" * 64

    def __init__(self, spec):
        self.spec = spec
        self.actions = []
        self.nara_active = True
        self.rows = {
            resident["name"]: {
                "id": resident["id"], "name": resident["name"],
                "image": resident["image_id"], "running": True,
                "pid": 100, "started_at": "before", "finished_at": "",
                "oom_killed": False, "state_error": "", "restart_count": 0,
                "memory_limit_bytes": 0, "memory_swap_total_bytes": 0,
                "restart_policy": "unless-stopped",
            } for resident in q.RESIDENTS
        }

    def _find(self, identity):
        return next((row for row in self.rows.values()
                     if identity in {row["id"], row["name"]}), None)

    def run(self, argv, *, timeout, check=True):
        self.actions.append(tuple(argv))
        if argv[:3] == ["docker", "image", "inspect"]:
            return q.CommandResult(0, f"{self.spec.image_id} arm64\n", "")
        if argv[:2] == ["docker", "create"]:
            self.rows[self.spec.container_name] = {
                "id": self.cid, "name": self.spec.container_name,
                "image": self.spec.image_id, "running": False, "pid": 0,
                "started_at": "", "finished_at": "", "oom_killed": False,
                "state_error": "", "restart_count": 0,
                "memory_limit_bytes": self.spec.docker_memory_limit_bytes,
                "memory_swap_total_bytes": self.spec.docker_memory_limit_bytes,
                "restart_policy": "no",
            }
            return q.CommandResult(0, self.cid + "\n", "")
        if argv[:2] == ["docker", "inspect"]:
            row = self._find(argv[-1])
            return (q.CommandResult(0, json.dumps(row) + "\n", "") if row
                    else q.CommandResult(1, "", "No such object"))
        if argv[:2] in (["docker", "stop"], ["docker", "start"]):
            row = self._find(argv[-1])
            assert row is not None
            row["running"] = argv[1] == "start"
            if row["name"] == self.spec.container_name and row["running"]:
                row["pid"] = 200
            return q.CommandResult(0, row["id"] + "\n", "")
        if argv[:2] == ["docker", "rm"]:
            row = self._find(argv[-1])
            assert row is not None
            self.rows.pop(row["name"])
            return q.CommandResult(0, row["id"] + "\n", "")
        if argv[:2] == ["docker", "logs"]:
            return q.CommandResult(0, "synthetic startup log\n", "")
        if argv[:3] == ["systemctl", "--user", "show"]:
            return q.CommandResult(0, (
                "ActiveState=active\nSubState=running\nMainPID=123\n"
                if self.nara_active else
                "ActiveState=inactive\nSubState=dead\nMainPID=0\n"
            ), "")
        if argv[:3] == ["systemctl", "--user", "stop"]:
            self.nara_active = False
            return q.CommandResult(0, "", "")
        if argv[:3] == ["systemctl", "--user", "start"]:
            self.nara_active = True
            return q.CommandResult(0, "", "")
        raise AssertionError(f"unexpected host command: {argv}")

    def http_bytes(self, url, *, timeout):
        self.actions.append(("HTTP", url))
        if url.endswith("/v1/models"):
            return json.dumps({"data": [{"id": self.spec.served_name}]}).encode()
        return b"OK"

    def complete(self, endpoint, messages, **kwargs):
        text = messages[0]["content"]
        tools = kwargs.get("tools")
        if tools:
            label = "mtp-parity" if "mtp-parity" in text else "flash-next"
            delta = {"tool_calls": [{
                "index": 0, "id": "call_1", "type": "function",
                "function": {"name": "record_probe",
                             "arguments": json.dumps({"label": label, "value": 703},
                                                      separators=(",", ":"))},
            }]}
            finish = "tool_calls"
        else:
            answer = (
                "FLASH_NEXT_OK_17" if "FLASH_NEXT_OK_17" in text else
                "703" if "37 * 19" in text else
                "ALPHA17_BETA703_GAMMA29_DELTA11" if "ALPHA17_BETA703" in text else
                "1,1,1,1" if "Four players" in text else
                "def clamp01(value): return min(1.0, max(0.0, float(value)))"
            )
            delta = {"content": answer}
            finish = "stop"
        rid = f"cmpl_{len(self.actions)}"
        events = [
            {"id": rid, "model": self.spec.served_name,
             "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]},
            {"id": rid, "model": self.spec.served_name,
             "choices": [], "usage": {"prompt_tokens": 8,
                                      "completion_tokens": 8, "total_tokens": 16}},
        ]
        raw = b"".join(b"data: " + transport.canonical(row) + b"\n\n"
                       for row in events) + b"data: [DONE]\n\n"
        accumulator = transport.StreamAccumulator(self.spec.served_name)
        for line in raw.splitlines():
            data = transport._sse_data(line)
            if data is not None:
                accumulator.accept(data)
        body = transport.request_body(endpoint, messages, kwargs["policy"],
                                      kwargs["max_tokens"], kwargs["seed"], tools)
        result = accumulator.result()
        result.update({
            "endpoint": endpoint.__dict__, "resolved_request": body,
            "request_sha256": q.sha256(transport.canonical(body)),
            "response_stream_sha256": q.sha256(raw),
            "response_bytes": len(raw), "latency_s": 0.01, "ttft_s": 0.005,
            "private_evidence": transport._private_response_evidence(
                accumulator, raw, response_bytes=len(raw)),
        })
        self.actions.append(("COMPLETE", text))
        return result


@contextmanager
def fake_lease(root):
    yield (1, 2, 3)


def test_full_mtp3_worker_and_supervisor_receipt_pass_actual_v5_gate(monkeypatch):
    spec = MIA_MTP3
    old = json.loads(MIA.contract_path.read_bytes())
    contract = build_contract(old, spec)
    raw = q.canonical_json(contract) + b"\n"
    contract_sha = q.sha256(raw)
    output = spec.output_root / f"{spec.run_id_prefix}producer-{uuid.uuid4().hex}"
    host = FakeHost(spec)
    virtual = [0.0]
    base = datetime.now(timezone.utc) - timedelta(minutes=10)

    class VirtualDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            observed = base + timedelta(seconds=virtual[0])
            return observed if tz is not None else observed.replace(tzinfo=None)
    files = spec.expected_model_files()
    worker_verified = []

    def hash_source(path, size, monitor=None):
        if path == spec.packed_ple_path:
            return spec.packed_ple_sha256
        row = files.get(path.name)
        assert path.parent == spec.model_path and row["bytes"] == size
        return row["sha256"]

    cgroup = {
        "path": f"/system.slice/docker-{host.cid}.scope",
        "process_start_ticks": 12345,
        "memory_max_bytes": spec.docker_memory_limit_bytes,
        "memory_swap_max_bytes": 0, "memory_swap_current_bytes": 0,
        "memory_current_bytes": 5 * 1024**3,
        "memory_events_oom": 0, "memory_events_oom_kill": 0,
        "memory_events_local": {"oom": 0, "oom_kill": 0},
        "selected_memory_stat": {key: 0 for key in
            ("anon", "file", "shmem", "active_file", "inactive_file", "pgscan", "pgsteal")},
        "memory_pressure": "some avg10=0.00 avg60=0.00 avg300=0.00 total=0\nfull avg10=0.00 avg60=0.00 avg300=0.00 total=0",
    }

    def monitor_factory(path, ops, **kwargs):
        return NoThreadMonitor(
            path, ops, **kwargs, reader=lambda: 39.0,
            swap_reader=lambda: 10, swapin_reader=lambda: 9,
            psi_reader=lambda: {"some": 100, "full": 10},
            cgroup_reader=lambda *_: dict(cgroup), clock=lambda: virtual[0],
        )

    class InProcessPopen:
        def __init__(self, argv, **kwargs):
            assert argv[1:4] == ["-m", "bench.flash_next_ab.qualification", "--worker"]
            self.pid = os.getpid()
            plan = json.loads((output / "plan.json").read_bytes())
            result = q.execute_worker(
                plan, contract, output, ops=host,
                preflight_probe=lambda *_a, **_kw: {
                    "mem_available_gib": 42.0,
                    "runtime_identity": [{"id": row["id"]} for row in q.RESIDENTS],
                }, monitor_factory=monitor_factory, spec=spec,
            )
            worker_verified.append(q._result_has_verified_restoration(output, plan, spec=spec))
            self.returncode = 0 if result["status"] == "passed" else 1

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            return self.returncode

    def sleep(seconds):
        virtual[0] += seconds

    try:
        monkeypatch.setattr(q, "_verified_contract_raw", lambda *_a, **_kw: raw)
        monkeypatch.setattr(q, "canonical_root", lambda root: q.ROOT)
        monkeypatch.setattr(q, "_hash_regular_file", hash_source)
        monkeypatch.setattr(q, "resource_lease", fake_lease)
        monkeypatch.setattr(q, "_ensure_compile_cache", lambda *_a, **_kw: None)
        monkeypatch.setattr(q, "_assert_port_free", lambda *_a, **_kw: None)
        monkeypatch.setattr(q, "_append_research_usage", lambda *_a, **_kw: None)
        monkeypatch.setattr(q, "_signal_guard", dict)
        monkeypatch.setattr(q, "_restore_signals", lambda *_a: None)
        monkeypatch.setattr(q.subprocess, "Popen", InProcessPopen)
        monkeypatch.setattr(q.time, "monotonic", lambda: virtual[0])
        monkeypatch.setattr(q.time, "sleep", sleep)
        monkeypatch.setattr(q, "datetime", VirtualDateTime)
        monkeypatch.setattr(q, "utc_now",
                            lambda: (base + timedelta(seconds=virtual[0])).isoformat())
        monkeypatch.setattr(followon_canaries, "_now", q.utc_now)
        exitcode = q.supervise_run(contract, contract_sha, output, spec=spec)
        produced = json.loads((output / "result.json").read_bytes())
        assert exitcode == 0, (
            "worker_verified", worker_verified,
            "timestamps", (produced.get("started_at"), produced.get("finished_at")),
            "restored", produced.get("restoration", {}).get("verified_at"),
            "now", datetime.now(timezone.utc).isoformat(),
        )
        summary = harness.validate_flash_qualification_files(
            output / "result.json", output / "plan.json",
            output / "launch-contract.snapshot.json",
            contract_raw_path=output / "launch-contract.raw.json",
            require_passed=True,
        )
        assert summary["admission_eligible"] is True
        assert summary["variant_id"] == spec.spec_id
        assert host.nara_active is True
        assert spec.container_name not in host.rows
        assert all(host.rows[row["name"]]["running"] for row in q.RESIDENTS)
    finally:
        shutil.rmtree(output, ignore_errors=True)
