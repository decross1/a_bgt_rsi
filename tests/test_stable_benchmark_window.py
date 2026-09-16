from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path

import pytest

from bench.stable_benchmark import (
    bind_run_manifest,
    load_definition,
    load_run_manifest,
    make_draft,
    publish_definition,
    run_arm,
)
from bench.stable_benchmark.manifest import write_document
from bench.stable_benchmark.runner import (
    InvocationRequest,
    InvocationResult,
    execution_source_hashes,
)
from bench.stable_benchmark import supervised_window as window


ZERO = "0" * 64
ONE = "1" * 64


def _identities() -> dict[str, dict]:
    return {
        "vllm-gemma": {
            "served_model": "gemma-4-26b-a4b",
            "artifact_sha256": ZERO,
            "runtime_sha256": ONE,
            "max_context_tokens": 32768,
        },
        "vllm-qwen": {
            "served_model": "qwen3.8-27b-nvfp4-mtp",
            "artifact_sha256": ONE,
            "runtime_sha256": ZERO,
            "max_context_tokens": 16384,
        },
    }


def _route(backend: str, profile: str, identity: dict, effort: str | None) -> dict:
    return {
        "backend": backend,
        "model": identity["served_model"],
        "profile": profile,
        "expected_policy": {
            "temperature": 0.2,
            "top_p": 0.95,
            "reasoning_effort": effort,
            "sampling_extra": {},
        },
        "runtime_identity": identity,
    }


def _arm() -> dict:
    identities = _identities()
    return {
        "id": "resident-stack-v1",
        "label": "qualified resident Gemma actor and Qwen critic",
        "seed": 17,
        "routes": {
            "gemma": _route("vllm-gemma", "precise", identities["vllm-gemma"], None),
            "qwen": _route(
                "vllm-qwen", "critic_current", identities["vllm-qwen"], "xhigh"
            ),
        },
        "role_map": {
            "capability": "gemma",
            "system_actor": "gemma",
            "system_critic": "qwen",
        },
    }


def _registered_documents(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    program = tmp_path / "program"
    monkeypatch.setattr(window, "PROGRAM_ROOT", program)
    monkeypatch.setattr(window, "DEFINITION_PATH", program / "definition.published.json")
    monkeypatch.setattr(window, "MANIFEST_ROOT", program / "manifests")
    monkeypatch.setattr(window, "RUN_ROOT", program / "runs")
    monkeypatch.setattr(window, "WINDOW_ROOT", tmp_path / "windows")
    definition_document = publish_definition(
        make_draft(),
        published_at="2026-09-16T05:00:00Z",
        witness={"kind": "preregistration_receipt", "ref": "test", "sha256": ONE},
    )
    write_document(window.DEFINITION_PATH, definition_document)
    definition = load_definition(window.DEFINITION_PATH, require_published=True)
    manifest_document = bind_run_manifest(
        definition,
        arm=_arm(),
        comparison_id="stable-comparison-v1",
        harness_identity={
            "scaffold_id": "stable-benchmark-runner-v1",
            "transport_contract": "injected-supervised-endpoint/v1",
            "source_sha256": execution_source_hashes(),
        },
    )
    manifest_path = (
        window.MANIFEST_ROOT
        / f"{manifest_document['comparison_id']}.{manifest_document['arm']['id']}.json"
    )
    write_document(manifest_path, manifest_document)
    manifest = load_run_manifest(manifest_path, definition)
    return definition, manifest


def _certificate():
    return (
        {
            "qualification_receipt_sha256": ZERO,
            "artifact_inventory_sha256": ONE,
            "probe_scope": "fixed_literal_and_arithmetic_only",
        },
        _identities(),
    )


def test_plan_binds_registered_paths_sources_and_production_routes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    definition, manifest = _registered_documents(tmp_path, monkeypatch)
    plan = window.build_plan(
        definition,
        manifest,
        window_id="stable-resident-20260916-a",
        git_head="a" * 40,
        sources={"bench/test.py": ZERO},
        resident_certificate=_certificate(),
    )
    assert plan["execution_mode"] == "resident_only"
    assert plan["run_dir"] == str(
        window.RUN_ROOT / "stable-comparison-v1" / "resident-stack-v1"
    )
    assert plan["preflight_min_mem_available_gib"] == 30
    assert plan["monitor_min_mem_available_gib"] == 20
    assert plan["candidate_startup_supported"] is False

    bad = json.loads(json.dumps(manifest.document))
    bad["arm"]["role_map"]["system_critic"] = "gemma"
    bad_manifest = type(manifest)(bad, manifest.raw_sha256, manifest.path)
    with pytest.raises(window.StableWindowError, match="unused or missing route"):
        window.validate_resident_arm(bad_manifest, _identities())


class _FakeMonitor:
    def __init__(self, *, fail_post: bool = False):
        self.cancel_event = threading.Event()
        self.events: list[str] = []
        self.fail_post = fail_post
        self.phase = "evaluation"
        self.samples = 1

    def check(self):
        self.events.append("check")

    def sample(self):
        self.events.append("sample")
        if self.fail_post and self.events.count("sample") == 2:
            raise RuntimeError("post-call guard failed")
        return {"sample": len(self.events)}


def test_injected_transport_is_checked_before_and_after_every_request():
    monitor = _FakeMonitor()

    def invoke(_request):
        monitor.events.append("invoke")
        return InvocationResult(completion="{}", records=())

    wrapped = window.monitored_invoke(monitor, invoke)
    assert wrapped(object()).completion == "{}"
    assert monitor.events == ["check", "sample", "invoke", "sample", "check"]
    assert not monitor.cancel_event.is_set()

    failing = _FakeMonitor(fail_post=True)
    wrapped = window.monitored_invoke(
        failing, lambda _request: InvocationResult(completion="{}", records=())
    )
    with pytest.raises(RuntimeError, match="post-call guard"):
        wrapped(object())
    assert failing.cancel_event.is_set()


def test_gate_receipts_bind_routes_without_raw_ports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    definition, manifest = _registered_documents(tmp_path, monkeypatch)
    plan = window.build_plan(
        definition,
        manifest,
        window_id="stable-resident-20260916-b",
        git_head="b" * 40,
        sources={"bench/test.py": ONE},
        resident_certificate=_certificate(),
    )
    residents = {
        registered["name"]: {
            "id": registered["id"],
            "image": registered["image_id"],
        }
        for registered in window.RESIDENTS
    }
    quiet = {
        "residents_by_name": residents,
        "nara": {"ActiveState": "inactive"},
    }
    target = tmp_path / "gate"
    target.mkdir()
    monitor = _FakeMonitor()
    gate = window.freeze_execution_gate(
        definition,
        manifest,
        plan=plan,
        window_dir=target,
        quiet=quiet,
        monitor=monitor,
        start_sample={"mem_available_gib": 40.0},
        sentinel_id="f" * 64,
    )
    assert set(gate) == {
        "admitted",
        "definition_sha256",
        "run_manifest_sha256",
        "route_runtime_identities",
        "endpoint_bindings_sha256",
        "supervision_receipt_sha256",
        "resource_guard_sha256",
    }
    endpoints = json.loads((target / "endpoint-bindings.json").read_text())
    assert endpoints["raw_ports_exposed"] is False
    assert "http" not in json.dumps(endpoints)
    ready = json.loads((target / "supervision-ready.json").read_text())
    expected_plan_sha = hashlib.sha256(
        window.canonical_json(plan) + b"\n"
    ).hexdigest()
    assert ready["plan_sha256"] == expected_plan_sha
    for filename, key in (
        ("endpoint-bindings.json", "endpoint_bindings_sha256"),
        ("supervision-ready.json", "supervision_receipt_sha256"),
        ("resource-guard.json", "resource_guard_sha256"),
    ):
        assert hashlib.sha256((target / filename).read_bytes()).hexdigest() == gate[key]
        copied = tmp_path / "run-copy" / filename
        assert window._copy_regular_exclusive(
            target / filename, copied, limit=2_000_000
        ) == gate[key]
        assert copied.read_bytes() == (target / filename).read_bytes()


class _NeverCancel:
    def is_set(self) -> bool:
        return False


def test_restoration_receipt_precedes_replay_and_admission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    definition, manifest = _registered_documents(tmp_path, monkeypatch)
    run_dir = window.RUN_ROOT / "stable-comparison-v1" / "resident-stack-v1"
    arm = manifest.document["arm"]
    gate = {
        "admitted": True,
        "definition_sha256": definition.raw_sha256,
        "run_manifest_sha256": manifest.raw_sha256,
        "route_runtime_identities": {
            route_id: route["runtime_identity"] for route_id, route in arm["routes"].items()
        },
        "endpoint_bindings_sha256": "2" * 64,
        "supervision_receipt_sha256": "3" * 64,
        "resource_guard_sha256": "4" * 64,
    }

    def invoke(request: InvocationRequest) -> InvocationResult:
        role = "system_actor" if request.task["mode"] == "system_mission" else "capability"
        route = arm["routes"][arm["role_map"][role]]
        record = {
            "request_id": f"request-{request.task['id']}",
            "model": route["model"],
            "model_version": "test-runtime",
            "backend": route["backend"],
            "profile": route["profile"],
            "temperature": route["expected_policy"]["temperature"],
            "top_p": route["expected_policy"]["top_p"],
            "reasoning_effort": route["expected_policy"]["reasoning_effort"],
            "sampling_extra": route["expected_policy"]["sampling_extra"],
            "seed": arm["seed"],
            "max_tokens": request.task["resource"]["max_tokens_per_call"],
            "host_metadata": {"test": True},
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }
        return InvocationResult(
            completion="{}",
            records=(record,),
            failure_code="synthetic_invalid_output",
            failure_detail="test fixture intentionally avoids model-specific answers",
            attempt_count=1,
        )

    run_arm(
        definition,
        manifest,
        output_dir=run_dir,
        execution_gate=gate,
        absolute_deadline_monotonic=time.monotonic() + 30,
        cancel_event=_NeverCancel(),
        invoke=invoke,
    )
    plan = {
        "controller_source_sha256": {"bench/test-controller.py": "5" * 64},
    }
    replay, admission, error = window.finalize_run(
        definition,
        manifest,
        plan=plan,
        window_dir=tmp_path / "window",
        run_dir=run_dir,
        lifecycle_valid=True,
        lifecycle_result={
            "monitor_end_passed": True,
            "no_guard_breach": True,
            "restoration_passed": True,
        },
    )
    assert error is None
    assert replay["verified"] is True
    assert admission["admitted"] is True
    final_raw = (run_dir / "supervisor-final.json").read_bytes()
    assert admission["supervisor_final_receipt_sha256"] == hashlib.sha256(final_raw).hexdigest()
    assert json.loads(final_raw)["restoration_passed"] is True
