"""CPU-only contract tests for the registered Mia research candidate."""
from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from bench.flash_next_ab import harness as h
from bench.flash_next_ab import qualification as q
from bench.flash_next_ab.candidate_registry import MIA, select_candidate
from bench.flash_next_ab.mia_candidate_integration import (
    MiaRegistrationError,
    plan_mia_qualification,
    validate_mia_contract,
)
from bench.flash_next_ab.transport import LocalEndpoint, request_body

HERE = Path(__file__).parent
MIA_CONTRACT = json.loads((HERE / "fixtures" / "flash_next_mia_contract_v4_s1.json").read_text())
NVIDIA_S1_RAW = (HERE / "fixtures" / "flash_next_nvidia_contract_v3_s1.json").read_bytes()


def _nvidia_s1_contract() -> tuple[dict, str]:
    """Use the exact frozen S1 bytes; the live external path can advance."""
    return q.validate_contract(json.loads(NVIDIA_S1_RAW)), q.sha256(NVIDIA_S1_RAW)


class CandidateRegistryTests(unittest.TestCase):
    def test_mia_transport_route_is_literal_and_bound_to_checkpoint(self):
        endpoint = LocalEndpoint(
            MIA.endpoint_name, "http://127.0.0.1:8012/v1",
            MIA.served_name, MIA.model_artifact_sha256(),
        )
        self.assertEqual(endpoint.validate(), 8012)
        body = request_body(
            endpoint, [{"role": "user", "content": "fixed canary"}],
            {"temperature": 0, "top_p": 1, "enable_thinking": False},
            32, 17,
        )
        self.assertEqual(body["model"], MIA.served_name)
        self.assertEqual(body["chat_template_kwargs"], {"enable_thinking": False})
        for changed in (
            LocalEndpoint(MIA.endpoint_name, "http://127.0.0.1:8001/v1",
                          MIA.served_name, MIA.model_artifact_sha256()),
            LocalEndpoint(MIA.endpoint_name, "http://127.0.0.1:8012/v1",
                          MIA.served_name, "0" * 64),
            LocalEndpoint(MIA.endpoint_name, "http://127.0.0.1:8012/v1",
                          "qwen3.8-flash-next", MIA.model_artifact_sha256()),
        ):
            with self.assertRaises(ValueError):
                changed.validate()

    def test_mia_probe_recorder_and_private_stream_binding(self):
        class Monitor:
            cancel_event = threading.Event()

            def check(self):
                pass

        class Ops:
            calls = 0

            def complete(self, endpoint, messages, **kwargs):
                body = request_body(
                    endpoint, messages, kwargs["policy"], kwargs["max_tokens"],
                    kwargs["seed"], kwargs.get("tools"),
                )
                self.assert_model(body, endpoint)
                ordinal = self.calls
                self.calls += 1
                raw = f"data: mia-probe-{ordinal}\\n\\n".encode()
                content = ("FLASH_NEXT_OK_17" if ordinal == 0 else
                           "703" if ordinal == 1 else "")
                tools = ([{"function": {"name": "record_probe",
                           "arguments": '{"label":"flash-next","value":703}'}}]
                         if ordinal == 2 else [])
                return {
                    "endpoint": {"name": endpoint.name,
                                 "served_model": endpoint.served_model,
                                 "artifact_sha256": endpoint.artifact_sha256},
                    "response_model": endpoint.served_model,
                    "content": content, "tool_calls": tools,
                    "finish_reason": "tool_calls" if ordinal == 2 else "stop",
                    "response_stream_sha256": hashlib.sha256(raw).hexdigest(),
                    "private_evidence": {
                        "raw_response_stream": raw,
                        "response_stream_sha256": hashlib.sha256(raw).hexdigest(),
                    },
                }

            def assert_model(self, body, endpoint):
                if body["model"] != MIA.served_name or endpoint.name != MIA.endpoint_name:
                    raise AssertionError("Mia probe routed to another endpoint")

        with tempfile.TemporaryDirectory(prefix="qfn-mia-c0-probe-") as run_name:
            run = Path(run_name)
            rows = q._run_probes(Ops(), Monitor(), timeout_s=5, output=run, spec=MIA)
            self.assertEqual([row["probe_id"] for row in rows], [
                "exact_literal", "exact_arithmetic", "exact_tool_call",
            ])
            probes = {"probe_set": "flash-next-minimal-v1", "results": rows}
            h._validate_flash_probes(
                probes, probe_set="flash-next-minimal-v1",
                served_model=MIA.served_name,
                artifact_sha256=MIA.model_artifact_sha256(),
                endpoint_name=MIA.endpoint_name,
            )
            h._validate_mia_probe_attempts(run, probes)
            attempts = json.loads((run / "probe-attempts.json").read_bytes())
            self.assertEqual([row["status"] for row in attempts["results"]], ["passed"] * 3)
            stream = run / "private-probes" / "exact_arithmetic.sse"
            stream.write_bytes(b"data: mia-probe-X\\n\\n")
            with self.assertRaises(h.HarnessError):
                h._validate_mia_probe_attempts(run, probes)
    def test_exact_51_file_identity(self):
        self.assertEqual(len(MIA.files), 51)
        self.assertEqual(MIA.repository_total_bytes, 105935744618)
        self.assertEqual(MIA.model_artifact_sha256(),
                         "a40ce50173dd3aff54da88503894967e5248bbb927f9e4a91eff5a6a7270c168")
        self.assertEqual(MIA.packed_ple_bytes, 28800138240)
        self.assertEqual(MIA.image_id,
                         "sha256:da68dd27a8ef1dadd0f380178a51f0a0671dc4235933ea1ae89fdaf66295ec72")

    def test_exact_v4_select_and_v3_remains_legacy(self):
        self.assertIs(select_candidate(MIA_CONTRACT), MIA)
        nvidia, _ = _nvidia_s1_contract()
        self.assertIsNone(select_candidate(nvidia))
        with self.assertRaises(ValueError):
            select_candidate({**nvidia, "candidate": MIA_CONTRACT["candidate"]})

    def test_model_response_or_timestamp_cannot_select_variant(self):
        for key, value in [("contract_id", "qwen38-flash-next-c0-s0-20260915"),
                           ("candidate", {"id": MIA.spec_id, "spec_sha256": "0" * 64}),
                           ("schema", "qwen-flash-next-qualification/v3")]:
            tampered = copy.deepcopy(MIA_CONTRACT)
            tampered[key] = value
            with self.assertRaises((MiaRegistrationError, ValueError)):
                validate_mia_contract(tampered, q)

    def test_image_model_path_and_ple_are_code_owned(self):
        cases = [
            ("image", "id", "sha256:" + "0" * 64),
            ("model", "host_path", "/tmp/model"),
            ("model", "files", {}),
            ("runtime", "packed_ple_sha256", "0" * 64),
            ("runtime", "host_port", 8000),
            ("runtime", "docker_memory_limit_bytes", 128 * 1024**3),
        ]
        for section, key, value in cases:
            with self.subTest(section=section, key=key):
                tampered = copy.deepcopy(MIA_CONTRACT)
                tampered[section][key] = value
                with self.assertRaises(MiaRegistrationError):
                    validate_mia_contract(tampered, q)

    def test_safety_and_accounting_fail_closed(self):
        for section, key, value in [
            ("safety", "min_mem_available_gib", 12),
            ("safety", "paging_policy", {}),
            ("safety", "resident_containers", []),
            ("accounting", "paid_api_allowed", True),
        ]:
            tampered = copy.deepcopy(MIA_CONTRACT)
            tampered[section][key] = value
            with self.assertRaises(MiaRegistrationError):
                validate_mia_contract(tampered, q)

    def test_mia_plan_crossbinds_exact_argv(self):
        plan = plan_mia_qualification(MIA_CONTRACT, "a" * 64,
                                      q.OUTPUT_ROOT / "qfn-mia-c0-unit", q)
        argv = plan["docker_create_argv"]
        self.assertEqual(argv[argv.index("--memory") + 1], str(96 * 1024**3))
        self.assertEqual(argv[argv.index("--memory-swap") + 1], str(96 * 1024**3))
        self.assertEqual(argv[argv.index("--max-model-len") + 1], "32768")
        self.assertEqual(argv[argv.index("--kv-cache-memory-bytes") + 1], "2147483648")
        self.assertIn("VLLM_PLE_CPU_OFFLOAD=1", argv)
        self.assertIn("VLLM_PLE_PACKED_TABLE_DIR=/models/ple", argv)
        self.assertIn("VLLM_QSA_EXACT_TOPK=1", argv)
        self.assertIn(MIA.image_id, argv)
        self.assertEqual(plan["docker_create_argv_sha256"], q.sha256(argv))
        self.assertEqual(plan["candidate"]["spec_sha256"], MIA.identity_sha256())

    def test_existing_nvidia_plan_bytes_unchanged_by_pure_mia_use(self):
        nvidia, raw_sha = _nvidia_s1_contract()
        output = q.OUTPUT_ROOT / "qfn-c0-unit-byte-equivalence"
        before = q.canonical_json(q.plan_qualification(nvidia, raw_sha, output))
        q_globals = (q.IMAGE_ID, q.MODEL_PATH, q.MIN_MEMORY_GIB,
                     q.PAGING_POLICY, q.DOCKER_MEMORY_LIMIT_BYTES)
        validate_mia_contract(MIA_CONTRACT, q)
        plan_mia_qualification(MIA_CONTRACT, "a" * 64,
                               q.OUTPUT_ROOT / "qfn-mia-c0-unit", q)
        self.assertEqual(q.canonical_json(q.plan_qualification(nvidia, raw_sha, output)), before)
        self.assertEqual((q.IMAGE_ID, q.MODEL_PATH, q.MIN_MEMORY_GIB,
                          q.PAGING_POLICY, q.DOCKER_MEMORY_LIMIT_BYTES), q_globals)

    def test_harness_reconstructs_and_rejects_plan_drift(self):
        plan = plan_mia_qualification(MIA_CONTRACT, "a" * 64,
                                      q.OUTPUT_ROOT / "qfn-mia-c0-unit", q)
        identity = h._validate_registered_mia_plan(
            MIA_CONTRACT, "a" * 64, plan, q.OUTPUT_ROOT / "qfn-mia-c0-unit")
        self.assertEqual(identity["model_artifact_sha256"], MIA.model_artifact_sha256())
        drifted = copy.deepcopy(plan)
        drifted["docker_create_argv"][-1] = "untrusted-tool-parser"
        with self.assertRaises(h.HarnessError):
            h._validate_registered_mia_plan(
                MIA_CONTRACT, "a" * 64, drifted, q.OUTPUT_ROOT / "qfn-mia-c0-unit")

    def test_self_consistent_claim_without_raw_phase_evidence_cannot_admit(self):
        raw_contract = (HERE / "fixtures" / "flash_next_mia_contract_v4_s1.json").read_bytes()
        raw_sha = q.sha256(raw_contract)
        with tempfile.TemporaryDirectory(dir=q.OUTPUT_ROOT,
                                         prefix="qfn-mia-c0-test-") as run_name:
            run = Path(run_name)
            plan = plan_mia_qualification(MIA_CONTRACT, raw_sha, run, q)
            now = datetime.now(timezone.utc).isoformat()
            result = {
                "schema": "qwen-flash-next-qualification-result/v4",
                "run_id": run.name, "status": "passed", "profile": MIA.profile,
                "started_at": now, "finished_at": now,
                "contract_sha256": raw_sha, "plan_sha256": q.sha256(plan),
                "model_artifact_sha256": MIA.model_artifact_sha256(),
                "candidate": plan["candidate"],
                "proof_receipts": plan["proof_receipts"],
                "paging_policy": MIA.paging_policy(),
                "restoration": {"status": "verified", "verified_at": now,
                                "errors": [], "sentinel_retained": False},
                "qualification_error": None, "failure_stage": None,
                "weekly_budget_debit": False, "paid_api_calls": 0,
                "production_change_authorized": False,
                "min_mem_available_gib": 40.0, "probe_count": 3,
                "elapsed_seconds": 0.0, "challenger_gpu_seconds": 0.0,
                "all_gpu_research_seconds": 0.0, "resident_downtime_seconds": 0.0,
            }
            def write(path, value):
                path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")
            write(run / "plan.json", plan)
            write(run / "launch-contract.snapshot.json", MIA_CONTRACT)
            (run / "launch-contract.raw.json").write_bytes(raw_contract)
            write(run / "result.json", result)
            # The controller's direct restoration guard must work before
            # supervision.json exists; final consumer admission remains closed.
            self.assertTrue(q._result_has_verified_restoration(run, plan, spec=MIA))
            summary = h.validate_flash_qualification_files(
                run / "result.json", run / "plan.json",
                run / "launch-contract.snapshot.json")
            self.assertFalse(summary["admission_eligible"])
            with self.assertRaises(h.HarnessError):
                h.validate_flash_qualification_files(
                    run / "result.json", run / "plan.json",
                    run / "launch-contract.snapshot.json", require_passed=True)

    def test_mia_worker_rejects_drift_before_any_host_effect(self):
        plan = plan_mia_qualification(MIA_CONTRACT, "a" * 64,
                                      q.OUTPUT_ROOT / "qfn-mia-c0-unit", q)
        plan["image_id"] = "sha256:" + "0" * 64
        with self.assertRaises(q.QualificationError):
            q.execute_worker(plan, MIA_CONTRACT,
                             q.OUTPUT_ROOT / "qfn-mia-c0-unit", spec=MIA)

    def test_mia_monitor_binds_registered_identity_without_running(self):
        monitor = q.MemoryMonitor(
            Path("/tmp/mia-offtree-monitor-unopened.jsonl"), q.HostOps(),
            candidate_spec=MIA, reader=lambda: 40.0, swap_reader=lambda: 0,
        )
        self.assertEqual(monitor.runtime.image_id, MIA.image_id)
        self.assertEqual(monitor.runtime.container_name, MIA.container_name)
        self.assertEqual(monitor.paging_policy, MIA.paging_policy())

    def test_mia_verifier_accepts_exact_auxiliary_shard_taxonomy(self):
        files = MIA.expected_model_files()
        def static_hash(path, size, monitor=None):
            if path == MIA.packed_ple_path:
                self.assertEqual(size, MIA.packed_ple_bytes)
                return MIA.packed_ple_sha256
            self.assertEqual(size, files[path.name]["bytes"])
            return files[path.name]["sha256"]
        def static_proof(path, sha, size, monitor=None):
            return {"path": str(path), "sha256": sha, "bytes": size}
        with patch.object(q, "_hash_regular_file", side_effect=static_hash), \
             patch.object(q, "_verify_small_source_receipt", side_effect=static_proof):
            receipt = q.verify_model(MIA_CONTRACT, spec=MIA)
        self.assertEqual(len(receipt["verified_files"]), 51)
        self.assertEqual(receipt["safetensors_total_bytes"], MIA.safetensors_total_bytes)
        self.assertEqual(receipt["packed_ple"]["sha256"], MIA.packed_ple_sha256)
        self.assertEqual(set(receipt["proof_receipts"]),
                         {"acquisition", "image_build", "ple_build"})

    def test_mia_restoration_refuses_exact_name_with_wrong_image(self):
        candidate_id = "c" * 64

        class CandidateOps(q.HostOps):
            def __init__(self, image):
                self.image = image
                self.stops = []
                self.running = True

            def run(self, argv, *, timeout, check=True):
                if argv[:2] == ["docker", "inspect"]:
                    row = {
                        "id": candidate_id, "name": MIA.container_name,
                        "image": self.image, "running": self.running,
                        "oom_killed": False, "restart_policy": "no",
                        "restart_count": 0,
                    }
                    if argv[-1] in {candidate_id, MIA.container_name}:
                        return q.CommandResult(0, json.dumps(row) + "\n", "")
                    return q.CommandResult(1, "", "No such object")
                if argv[:2] == ["docker", "stop"]:
                    self.stops.append(tuple(argv))
                    self.running = False
                    return q.CommandResult(0, candidate_id + "\n", "")
                raise AssertionError(f"unexpected host command: {argv}")

        untrusted = CandidateOps("sha256:" + "0" * 64)
        unsafe = q.restore_exact(
            untrusted, {"candidate_id": candidate_id, "initial": None},
            deadline=time.monotonic() + 30, spec=MIA,
        )
        self.assertEqual(unsafe["status"], "unknown")
        self.assertTrue(unsafe["sentinel_retained"])
        self.assertEqual(untrusted.stops, [])
        self.assertTrue(any("candidate stop" in error for error in unsafe["errors"]))

        trusted = CandidateOps(MIA.image_id)
        incomplete = q.restore_exact(
            trusted, {"candidate_id": candidate_id, "initial": None},
            deadline=time.monotonic() + 30, spec=MIA,
        )
        self.assertEqual(incomplete["status"], "unknown")
        self.assertEqual(trusted.stops, [("docker", "stop", "--time", "20", candidate_id)])
        self.assertTrue(any("initial state receipt is absent" in error
                            for error in incomplete["errors"]))

    def test_malformed_mia_create_stdout_restores_only_exact_image(self):
        candidate_id = "c" * 64

        class EarlyMonitor:
            failure = None
            emergency_stop_at = None
            samples = 1
            minimum_observed_gib = 42.0
            initial_pswpout = final_pswpout = 10
            initial_pswpin = final_pswpin = 0
            def __init__(self, path, ops, **kwargs):
                self.path = path
                self.cancel_event = threading.Event()
                self.initial_host_psi_totals = {"some": 0, "full": 0}
                self.final_host_psi_totals = {"some": 0, "full": 0}
                self.violations = []
                self.phase_summaries = {"setup": {"pswpout_delta_bytes": 0,
                                                  "threshold_breached": False}}
                self.mutation_initial_pswpout = None
                self.mutation_final_pswpout = None
                self.startup_initial_pswpout = None
                self.startup_final_pswpout = None

            def __enter__(self):
                self.path.write_text("")
                return self

            def __exit__(self, *args):
                return False

            def check(self):
                return None

            def reader(self):
                return 42.0

            def require_setup_quiescence(self, *, duration_s, deadline):
                self.setup_quiescence_passed = True
                self.setup_quiescence_final_pswpout = 10

            def begin_mutation_window(self):
                self.mutation_initial_pswpout = self.mutation_final_pswpout = 10
                self.mutation_window_started_at = datetime.now(timezone.utc).isoformat()
                self.startup_initial_pswpout = self.startup_final_pswpout = 10

            def begin_restoration(self):
                return None

            def disarm(self):
                return None

        class MalformedCreateOps(q.HostOps):
            def __init__(self, candidate_image):
                self.candidate_image = candidate_image
                self.log = []
                self.containers = {
                    row["name"]: {
                        "id": row["id"], "name": row["name"],
                        "image": row["image_id"], "running": True,
                        "pid": 100, "started_at": "before", "finished_at": "",
                        "oom_killed": False, "state_error": "", "restart_count": 0,
                        "restart_policy": "unless-stopped",
                    }
                    for row in q.RESIDENTS
                }

            def find(self, identity):
                return next((row for row in self.containers.values()
                             if identity in {row["id"], row["name"]}), None)

            def run(self, argv, *, timeout, check=True):
                self.log.append(tuple(argv))
                if argv[:3] == ["docker", "image", "inspect"]:
                    return q.CommandResult(0, f"{MIA.image_id} arm64\n", "")
                if argv[:2] == ["docker", "create"]:
                    self.containers[MIA.container_name] = {
                        "id": candidate_id, "name": MIA.container_name,
                        "image": self.candidate_image, "running": False,
                        "pid": 0, "started_at": "", "finished_at": "",
                        "oom_killed": False, "state_error": "", "restart_count": 0,
                        "restart_policy": "no",
                        "memory_limit_bytes": MIA.docker_memory_limit_bytes,
                        "memory_swap_total_bytes": MIA.docker_memory_limit_bytes,
                    }
                    return q.CommandResult(0, f"created:{candidate_id}\n", "")
                if argv[:2] == ["docker", "inspect"]:
                    row = self.find(argv[-1])
                    return (q.CommandResult(0, json.dumps(row) + "\n", "") if row
                            else q.CommandResult(1, "", "No such object"))
                if argv[:2] == ["docker", "rm"]:
                    row = self.find(argv[-1])
                    if row:
                        self.containers.pop(row["name"])
                    return q.CommandResult(0, candidate_id + "\n", "")
                if argv[:2] == ["docker", "stop"]:
                    row = self.find(argv[-1])
                    if row:
                        row["running"] = False
                    return q.CommandResult(0, (row or {}).get("id", "") + "\n", "")
                if argv[:3] == ["systemctl", "--user", "show"]:
                    return q.CommandResult(0,
                        "ActiveState=inactive\nSubState=dead\nMainPID=0\n", "")
                raise AssertionError(f"unexpected host command: {argv}")

            def http_bytes(self, url, *, timeout):
                return b"OK"

        @contextmanager
        def lease(root):
            yield (1, 2, 3)

        def preflight(root, *, idle):
            self.assertTrue(idle)
            return {"mem_available_gib": 42.0,
                    "runtime_identity": [{"id": row["id"]} for row in q.RESIDENTS]}

        raw = (HERE / "fixtures" / "flash_next_mia_contract_v4_s1.json").read_bytes()
        for image, expected_restore in [(MIA.image_id, "verified"),
                                        ("sha256:" + "0" * 64, "unknown")]:
            with self.subTest(image=image), tempfile.TemporaryDirectory(
                dir=q.OUTPUT_ROOT, prefix="qfn-mia-c0-test-"
            ) as run_name:
                run = Path(run_name)
                ops = MalformedCreateOps(image)
                plan = plan_mia_qualification(MIA_CONTRACT, q.sha256(raw), run, q)
                with (
                    patch.object(q, "canonical_root", return_value=run),
                    patch.object(q, "resource_lease", lease),
                    patch.object(q, "verify_model", return_value={"full_sha256": True}),
                    patch.object(q, "_ensure_compile_cache", return_value=None),
                    patch.object(q, "_assert_port_free", return_value=None),
                    patch.object(q, "_write_cgroup_diagnostics", return_value=(None, None)),
                    patch.object(q, "_append_research_usage", return_value=None),
                    patch.object(q, "_signal_guard", return_value={}),
                    patch.object(q, "_restore_signals", return_value=None),
                ):
                    result = q.execute_worker(
                        plan, MIA_CONTRACT, run, ops=ops,
                        preflight_probe=preflight, monitor_factory=EarlyMonitor,
                        spec=MIA,
                    )
                self.assertEqual(result["restoration"]["status"], expected_restore)
                self.assertNotEqual(result["status"], "passed")
                self.assertTrue(all(ops.containers[row["name"]]["running"]
                                    for row in q.RESIDENTS))
                self.assertFalse(any(argv[:2] == ("docker", "stop")
                                     and argv[-1] in {row["id"] for row in q.RESIDENTS}
                                     for argv in ops.log))
                if expected_restore == "verified":
                    self.assertNotIn(MIA.container_name, ops.containers)
                    self.assertFalse(result["restoration"]["sentinel_retained"])
                    self.assertTrue(any(argv[:2] == ("docker", "rm")
                                        for argv in ops.log))
                else:
                    self.assertIn(MIA.container_name, ops.containers)
                    self.assertTrue(result["restoration"]["sentinel_retained"])
                    self.assertFalse(any(argv[:2] == ("docker", "rm")
                                         for argv in ops.log))


if __name__ == "__main__":
    unittest.main()
