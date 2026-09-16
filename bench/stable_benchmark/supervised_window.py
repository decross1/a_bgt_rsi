"""Fail-closed resident lifecycle for one stable-benchmark arm.

The stable runner deliberately has no model lifecycle authority.  This module
provides that missing external boundary for the existing resident stack only:
it holds the canonical GPU lease, proves the exact qualified residents,
quiesces Nara, freezes the runner's three gate receipts, monitors every call,
restores the original service state, and only then replays and admits the run.

There is no candidate startup path in this controller.  A Flash arm that did
not pass its separately registered runtime gate is represented with
``--unissued`` and receives no score or comparison.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import signal
import stat
import subprocess
import time
from collections.abc import Callable
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from agent_wrapper.generation_policy import resolve_generation_policy
from bench.flash_next_ab.harness import validate_resident_qualification_files
from bench.flash_next_ab.qualification import (
    NARA_SERVICE,
    RESIDENTS,
    HostOps,
    _available_gib,
    _inspect_container,
    _process_start_ticks,
    _self_start_ticks,
    utc_now,
)
from bench.flash_next_ab.resident_evaluation_window import (
    MIN_MEMORY_GIB as MONITOR_MIN_MEMORY_GIB,
)
from bench.flash_next_ab.resident_evaluation_window import (
    ResidentSafetyMonitor,
    _create_sentinel,
    _read_exact_residents,
    _sentinel_name,
    _verify_sentinel,
    restore_resident_window,
)
from orchestrator.weekly_upgrade_trial import (
    MIN_MEMORY_GIB as PREFLIGHT_MIN_MEMORY_GIB,
)
from orchestrator.weekly_upgrade_trial import (
    canonical_root,
    resource_lease,
    resource_probe,
)

from .admission import SUPERVISOR_FINAL_SCHEMA, admit_replay
from .manifest import (
    LoadedDocument,
    canonical_json,
    load_definition,
    load_run_manifest,
)
from .replay import replay_run
from .runner import (
    InvocationRequest,
    InvocationResult,
    execution_source_hashes,
    invoke_via_wrapper,
    run_arm,
    write_unissued_receipt,
)

CODE_ROOT = Path(__file__).resolve().parents[2]
PROGRAM_ROOT = Path(
    "/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-16/"
    "ui-benchmark-eight-hour/stable-benchmark"
)
CORRECTED_PROGRAM_ROOT = Path(
    "/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-16/"
    "ui-benchmark-eight-hour/stable-benchmark-v1_1"
)
REGISTERED_PROGRAM_ROOTS = {
    "1.0.0": PROGRAM_ROOT,
    "1.1.0": CORRECTED_PROGRAM_ROOT,
}
# Legacy aliases remain for readers of the immutable 1.0 controller contract.
DEFINITION_PATH = PROGRAM_ROOT / "definition.published.json"
MANIFEST_ROOT = PROGRAM_ROOT / "manifests"
RUN_ROOT = PROGRAM_ROOT / "runs"
WINDOW_ROOT = Path(
    "/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-16/"
    "stable-benchmark/windows"
)
RESIDENT_RECEIPT = Path(
    "/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-14/"
    "qwen-flash-next-research/runtime/resident-qualification-v2.json"
)
RESIDENT_INVENTORY = Path(
    "/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-14/"
    "qwen-flash-next-research/runtime/resident-model-artifacts.json"
)

WINDOW_SCHEMA = "stable-benchmark-supervised-window-plan/v1"
STATE_SCHEMA = "stable-benchmark-supervised-window-state/v1"
RESULT_SCHEMA = "stable-benchmark-supervised-window-result/v1"
SUPERVISION_SCHEMA = "stable-benchmark-supervision/v1"
PROCESS_SCHEMA = "stable-benchmark-supervised-process/v1"
ENDPOINT_BINDINGS_SCHEMA = "stable-benchmark-endpoint-bindings/v1"
SUPERVISION_READY_SCHEMA = "stable-benchmark-supervision-ready/v1"
RESOURCE_GUARD_SCHEMA = "stable-benchmark-resource-guard/v1"
RECOVERY_SCHEMA = "stable-benchmark-supervisor-recovery/v1"

WINDOW_DEADLINE_SECONDS = 3600
RESTORATION_RESERVE_SECONDS = 600
RUNNER_DEADLINE_SECONDS = 1800
TERM_GRACE_SECONDS = 90
MAX_JSON_BYTES = 8_000_000
WINDOW_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,47}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")

# Every directly trusted lifecycle implementation is frozen with the plan.
# The runner adds its own transitive source set through execution_source_hashes.
CONTROLLER_SOURCE_PATHS = (
    "bench/stable_benchmark/supervised_window.py",
    "bench/stable_benchmark/replay.py",
    "bench/stable_benchmark/admission.py",
    "bench/flash_next_ab/resident_evaluation_window.py",
    "bench/flash_next_ab/qualification.py",
    "bench/flash_next_ab/evaluation_window.py",
    "bench/flash_next_ab/harness.py",
    "bench/flash_next_ab/adapters.py",
    "bench/flash_next_ab/compare.py",
    "bench/flash_next_ab/manifest.py",
    "bench/flash_next_ab/transport.py",
    "orchestrator/weekly_upgrade_trial.py",
    "orchestrator/weekly_upgrade_budget.py",
    "orchestrator/weekly_upgrade.py",
)


class StableWindowError(RuntimeError):
    """A lifecycle, source, routing, or restoration proof failed."""


class _SignalInterruption(BaseException):
    """Bypass runner exception accounting so a supervisor signal restores now."""


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha_file(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def _sha_json(value: Any) -> str:
    return _sha_bytes(canonical_json(value))


def _receipt_sha(value: Any) -> str:
    """Hash the exact canonical JSON file bytes, including the terminal LF."""
    return _sha_bytes(canonical_json(value) + b"\n")


def controller_source_hashes() -> dict[str, str]:
    result = {
        name: _sha_file(CODE_ROOT / name)
        for name in CONTROLLER_SOURCE_PATHS
    }
    # Preserve the runner's wider transport/policy bundle exactly rather than
    # maintaining a second, potentially incomplete copy here.
    for name, digest in execution_source_hashes().items():
        prior = result.setdefault(name, digest)
        if prior != digest:
            raise StableWindowError(f"controller source digest collision for {name}")
    return dict(sorted(result.items()))


def _write_exclusive(path: Path, value: dict[str, Any]) -> str:
    raw = canonical_json(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise StableWindowError(f"receipt destination is not regular: {path}")
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise StableWindowError(f"could not write receipt: {path}")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return _sha_bytes(raw)


def _write_atomic(path: Path, value: dict[str, Any]) -> str:
    raw = canonical_json(value) + b"\n"
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(
        temp,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise StableWindowError(f"could not write receipt: {path}")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temp, path)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return _sha_bytes(raw)


def _read_json(path: Path, *, limit: int = MAX_JSON_BYTES) -> tuple[dict[str, Any], str]:
    target = path.absolute()
    before = target.lstat()
    if (
        not stat.S_ISREG(before.st_mode)
        or stat.S_ISLNK(before.st_mode)
        or before.st_size > limit
    ):
        raise StableWindowError(f"unsafe or oversized receipt: {target}")
    descriptor = os.open(
        target,
        os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise StableWindowError(f"receipt identity changed: {target}")
        raw = b""
        while len(raw) <= limit:
            chunk = os.read(descriptor, min(65536, limit + 1 - len(raw)))
            if not chunk:
                break
            raw += chunk
    finally:
        os.close(descriptor)
    if len(raw) != before.st_size or len(raw) > limit:
        raise StableWindowError(f"receipt size changed: {target}")
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_unique_object,
            parse_constant=lambda item: (_ for _ in ()).throw(
                StableWindowError(f"non-finite JSON constant {item}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StableWindowError(f"cannot decode receipt {target}: {exc}") from exc
    if not isinstance(value, dict):
        raise StableWindowError(f"receipt is not an object: {target}")
    return value, _sha_bytes(raw)


def _copy_regular_exclusive(source: Path, destination: Path, *, limit: int) -> str:
    """Copy immutable receipt bytes without following links or rewriting JSON."""
    before = source.lstat()
    if (
        not stat.S_ISREG(before.st_mode)
        or stat.S_ISLNK(before.st_mode)
        or before.st_size > limit
    ):
        raise StableWindowError(f"unsafe gate receipt source: {source}")
    source_fd = os.open(
        source,
        os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        observed = os.fstat(source_fd)
        if (observed.st_dev, observed.st_ino) != (before.st_dev, before.st_ino):
            raise StableWindowError(f"gate receipt identity changed: {source}")
        raw = b""
        while len(raw) <= limit:
            chunk = os.read(source_fd, min(65536, limit + 1 - len(raw)))
            if not chunk:
                break
            raw += chunk
    finally:
        os.close(source_fd)
    if len(raw) != before.st_size or len(raw) > limit:
        raise StableWindowError(f"gate receipt size changed: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination_fd = os.open(
        destination,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        view = memoryview(raw)
        while view:
            written = os.write(destination_fd, view)
            if written <= 0:
                raise StableWindowError(f"could not copy gate receipt: {destination}")
            view = view[written:]
        os.fsync(destination_fd)
    finally:
        os.close(destination_fd)
    return _sha_bytes(raw)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise StableWindowError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _git_head() -> str:
    value = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=CODE_ROOT, text=True, timeout=5
    ).strip()
    if re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise StableWindowError("source checkout HEAD is unavailable")
    return value


def _registered_paths(
    definition: LoadedDocument,
    run_manifest: LoadedDocument,
) -> tuple[Path, Path, Path]:
    program_root = REGISTERED_PROGRAM_ROOTS.get(definition.document.get("release"))
    if program_root is None:
        raise StableWindowError("definition release has no registered stable-program root")
    program_root = program_root.absolute()
    definition_path = program_root / "definition.published.json"
    manifest_root = program_root / "manifests"
    run_root = program_root / "runs"
    if definition.path != definition_path:
        raise StableWindowError("definition is outside the registered stable-program path")
    arm_id = run_manifest.document["arm"]["id"]
    comparison_id = run_manifest.document["comparison_id"]
    manifest_path = manifest_root / f"{comparison_id}.{arm_id}.json"
    run_dir = run_root / comparison_id / arm_id
    if run_manifest.path != manifest_path.absolute():
        raise StableWindowError("run manifest is outside its exact registered path")
    if run_dir.exists():
        raise StableWindowError(f"stable arm output already exists: {run_dir}")
    for item in (comparison_id, arm_id):
        if re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,95}", item) is None:
            raise StableWindowError("comparison or arm ID is unsafe")
    return manifest_path, run_dir, run_root / comparison_id


def _resident_certificate() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    summary = validate_resident_qualification_files(
        RESIDENT_RECEIPT, RESIDENT_INVENTORY, require_passed=True
    )
    identities = {
        "vllm-gemma": {
            "served_model": "gemma-4-26b-a4b",
            "artifact_sha256": summary["artifact_sha256_by_endpoint"]["resident_gemma"],
            "runtime_sha256": summary["runtime_sha256_by_endpoint"]["resident_gemma"],
            "max_context_tokens": 32768,
        },
        "vllm-qwen": {
            "served_model": "qwen3.8-27b-nvfp4-mtp",
            "artifact_sha256": summary["artifact_sha256_by_endpoint"]["resident_qwen"],
            "runtime_sha256": summary["runtime_sha256_by_endpoint"]["resident_qwen"],
            "max_context_tokens": 16384,
        },
    }
    return summary, identities


def _resolved_policy(route: dict[str, Any], seed: int) -> dict[str, Any]:
    policy = resolve_generation_policy(
        route["profile"], route["backend"], route["model"], seed=seed
    )
    return {
        "temperature": policy.logged_params["temperature"],
        "top_p": policy.logged_params["top_p"],
        "reasoning_effort": policy.reasoning_effort,
        "sampling_extra": policy.sampling_extra,
    }


def validate_resident_arm(
    run_manifest: LoadedDocument,
    identities: dict[str, dict[str, Any]],
) -> None:
    arm = run_manifest.document["arm"]
    routes = arm["routes"]
    role_map = arm["role_map"]
    if set(routes) != set(role_map.values()):
        raise StableWindowError("resident arm contains an unused or missing route")
    expected_roles = {
        "capability": "vllm-gemma",
        "system_actor": "vllm-gemma",
        "system_critic": "vllm-qwen",
    }
    for role, backend in expected_roles.items():
        route = routes[role_map[role]]
        if route["backend"] != backend:
            raise StableWindowError(f"{role} is not bound to the production resident route")
    for route_id, route in routes.items():
        backend = route["backend"]
        if backend not in identities or route["runtime_identity"] != identities[backend]:
            raise StableWindowError(f"route {route_id} differs from the resident qualification")
        if route["model"] != identities[backend]["served_model"]:
            raise StableWindowError(f"route {route_id} requests a different served model")
        if route["expected_policy"] != _resolved_policy(route, arm["seed"]):
            raise StableWindowError(f"route {route_id} policy differs from the named production profile")


def build_plan(
    definition: LoadedDocument,
    run_manifest: LoadedDocument,
    *,
    window_id: str,
    git_head: str | None = None,
    sources: dict[str, str] | None = None,
    resident_certificate: tuple[dict[str, Any], dict[str, dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    if WINDOW_ID.fullmatch(window_id) is None:
        raise StableWindowError("window ID is unsafe or too long")
    pair_id = f"qfn-ab-{window_id}"
    _sentinel_name(pair_id)  # share the existing sentinel namespace validator
    _, run_dir, _ = _registered_paths(definition, run_manifest)
    window_dir = WINDOW_ROOT / window_id
    summary, identities = resident_certificate or _resident_certificate()
    validate_resident_arm(run_manifest, identities)
    envelope = definition.document["resource_envelope"]
    if envelope["max_episode_runtime_s_per_arm"] > RUNNER_DEADLINE_SECONDS:
        raise StableWindowError("registered episode ceilings exceed the runner deadline")
    if WINDOW_DEADLINE_SECONDS > envelope["max_supervised_window_s"]:
        raise StableWindowError("controller window exceeds the registered supervisor ceiling")
    launcher = CODE_ROOT / ".venv-chroma/bin/python"
    if not launcher.is_file() or launcher.resolve() != Path("/usr/bin/python3.12"):
        raise StableWindowError("registered local Python launcher is unavailable")
    controller_sources = sources or controller_source_hashes()
    if not controller_sources or any(SHA256.fullmatch(value) is None for value in controller_sources.values()):
        raise StableWindowError("controller source bundle is malformed")
    qualification = {
        "receipt_path": str(RESIDENT_RECEIPT),
        "receipt_sha256": _sha_file(RESIDENT_RECEIPT),
        "inventory_path": str(RESIDENT_INVENTORY),
        "inventory_sha256": _sha_file(RESIDENT_INVENTORY),
        "qualification_receipt_sha256": summary["qualification_receipt_sha256"],
        "artifact_inventory_sha256": summary["artifact_inventory_sha256"],
        "probe_scope": summary["probe_scope"],
        "route_runtime_identities": identities,
    }
    return {
        "schema_version": WINDOW_SCHEMA,
        "window_id": window_id,
        "pair_id": pair_id,
        "execution_mode": "resident_only",
        "code_root": str(CODE_ROOT),
        "git_head": git_head or _git_head(),
        "window_dir": str(window_dir),
        "run_dir": str(run_dir),
        "definition_path": str(definition.path),
        "definition_sha256": definition.raw_sha256,
        "run_manifest_path": str(run_manifest.path),
        "run_manifest_sha256": run_manifest.raw_sha256,
        "arm_id": run_manifest.document["arm"]["id"],
        "comparison_id": run_manifest.document["comparison_id"],
        "resource_envelope": envelope,
        "window_deadline_seconds": WINDOW_DEADLINE_SECONDS,
        "restoration_reserve_seconds": RESTORATION_RESERVE_SECONDS,
        "runner_deadline_seconds": RUNNER_DEADLINE_SECONDS,
        "preflight_min_mem_available_gib": PREFLIGHT_MIN_MEMORY_GIB,
        "monitor_min_mem_available_gib": MONITOR_MIN_MEMORY_GIB,
        "monitor_max_sample_gap_seconds": 10,
        "nara_service": NARA_SERVICE,
        "nara_isolation": "stop_if_initially_active_then_restore",
        "resident_container_action": "read_and_verify_only",
        "watchdog_sentinel_name": _sentinel_name(pair_id),
        "launcher_python_path": str(launcher),
        "resident_qualification": qualification,
        "controller_source_sha256": controller_sources,
        "controller_source_bundle_sha256": _sha_json(controller_sources),
        "paid_api_allowed": False,
        "production_change_authorized": False,
        "candidate_startup_supported": False,
    }


def _load_inputs(run_manifest_path: Path) -> tuple[LoadedDocument, LoadedDocument]:
    manifest_path = run_manifest_path.expanduser().absolute()
    if manifest_path.parent.name != "manifests":
        raise StableWindowError("run manifest is outside a registered manifest directory")
    program_root = manifest_path.parent.parent
    registered_roots = {path.absolute() for path in REGISTERED_PROGRAM_ROOTS.values()}
    if program_root not in registered_roots:
        raise StableWindowError("run manifest is outside a registered stable-program root")
    definition = load_definition(
        program_root / "definition.published.json", require_published=True
    )
    manifest = load_run_manifest(manifest_path, definition)
    _registered_paths(definition, manifest)
    return definition, manifest


def _load_plan(window_id: str, run_manifest_path: Path) -> tuple[
    LoadedDocument, LoadedDocument, dict[str, Any], Path, Path
]:
    definition, manifest = _load_inputs(run_manifest_path)
    plan = build_plan(definition, manifest, window_id=window_id)
    window_dir = Path(plan["window_dir"])
    stored, _ = _read_json(window_dir / "window.json", limit=2_000_000)
    if stored != plan:
        raise StableWindowError("worker inputs or controller sources differ from the frozen plan")
    return definition, manifest, plan, window_dir, Path(plan["run_dir"])


def _validate_plan_sources(plan: dict[str, Any]) -> None:
    sources = controller_source_hashes()
    if (
        plan.get("code_root") != str(CODE_ROOT)
        or plan.get("git_head") != _git_head()
        or plan.get("controller_source_sha256") != sources
        or plan.get("controller_source_bundle_sha256") != _sha_json(sources)
    ):
        raise StableWindowError("source checkout differs from the supervised plan")
    qualification = plan["resident_qualification"]
    if (
        qualification["receipt_sha256"] != _sha_file(RESIDENT_RECEIPT)
        or qualification["inventory_sha256"] != _sha_file(RESIDENT_INVENTORY)
    ):
        raise StableWindowError("resident qualification evidence changed")


def _route_runtime_identities(manifest: LoadedDocument) -> dict[str, dict[str, Any]]:
    return {
        route_id: route["runtime_identity"]
        for route_id, route in manifest.document["arm"]["routes"].items()
    }


def freeze_execution_gate(
    definition: LoadedDocument,
    manifest: LoadedDocument,
    *,
    plan: dict[str, Any],
    window_dir: Path,
    quiet: dict[str, Any],
    monitor: ResidentSafetyMonitor,
    start_sample: dict[str, Any],
    sentinel_id: str,
) -> dict[str, Any]:
    """Write the three immutable controller receipts and return the exact gate."""
    residents = quiet["residents_by_name"]
    backend_to_resident = {
        "vllm-gemma": RESIDENTS[0],
        "vllm-qwen": RESIDENTS[1],
    }
    bindings: dict[str, Any] = {}
    for route_id, route in manifest.document["arm"]["routes"].items():
        registered = backend_to_resident[route["backend"]]
        observed = residents[registered["name"]]
        bindings[route_id] = {
            "endpoint_name": (
                "resident_gemma" if route["backend"] == "vllm-gemma" else "resident_qwen"
            ),
            "endpoint_spec": {
                "transport": "openai_chat_completions",
                "network_scope": "controller_fixed_loopback",
                "qualification": "registered_container_identity_plus_health_probe",
            },
            "backend": route["backend"],
            "served_model": route["model"],
            "profile": route["profile"],
            "expected_policy": route["expected_policy"],
            "runtime_identity": route["runtime_identity"],
            "container_name": registered["name"],
            "container_id": observed["id"],
            "container_image_id": observed["image"],
        }
    endpoint_receipt = {
        "schema_version": ENDPOINT_BINDINGS_SCHEMA,
        "window_id": plan["window_id"],
        "definition_sha256": definition.raw_sha256,
        "run_manifest_sha256": manifest.raw_sha256,
        "routes": bindings,
        "raw_ports_exposed": False,
        "frozen_at": utc_now(),
    }
    endpoint_sha = _write_exclusive(window_dir / "endpoint-bindings.json", endpoint_receipt)
    supervision_ready = {
        "schema_version": SUPERVISION_READY_SCHEMA,
        "window_id": plan["window_id"],
        "plan_sha256": _receipt_sha(plan),
        "worker_pid": os.getpid(),
        "worker_start_ticks": _self_start_ticks(),
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "definition_sha256": definition.raw_sha256,
        "run_manifest_sha256": manifest.raw_sha256,
        "controller_source_sha256": plan["controller_source_sha256"],
        "resident_qualification": plan["resident_qualification"],
        "endpoint_bindings_sha256": endpoint_sha,
        "quiet_observation_sha256": _sha_json(quiet),
        "nara_active_state": quiet["nara"]["ActiveState"],
        "watchdog_sentinel_id": sentinel_id,
        "restoration_owner": "worker_then_parent_emergency_recovery",
        "ready_at": utc_now(),
    }
    supervision_sha = _write_exclusive(
        window_dir / "supervision-ready.json", supervision_ready
    )
    resource_guard = {
        "schema_version": RESOURCE_GUARD_SCHEMA,
        "window_id": plan["window_id"],
        "monitor_phase": monitor.phase,
        "minimum_mem_available_gib": plan["monitor_min_mem_available_gib"],
        "maximum_sample_gap_seconds": plan["monitor_max_sample_gap_seconds"],
        "start_sample": start_sample,
        "cancel_sentinel": "resident_monitor_cancel_event",
        "checks": "before_and_after_every_model_request_plus_background_sampling",
        "armed_at": utc_now(),
    }
    resource_sha = _write_exclusive(window_dir / "resource-guard.json", resource_guard)
    return {
        "admitted": True,
        "definition_sha256": definition.raw_sha256,
        "run_manifest_sha256": manifest.raw_sha256,
        "route_runtime_identities": _route_runtime_identities(manifest),
        "endpoint_bindings_sha256": endpoint_sha,
        "supervision_receipt_sha256": supervision_sha,
        "resource_guard_sha256": resource_sha,
    }


def monitored_invoke(
    monitor: ResidentSafetyMonitor,
    invoke: Callable[[InvocationRequest], InvocationResult] = invoke_via_wrapper,
) -> Callable[[InvocationRequest], InvocationResult]:
    """Wrap one injected transport with fail-closed checks on both sides."""

    def call(request: InvocationRequest) -> InvocationResult:
        try:
            monitor.check()
            monitor.sample()
        except BaseException:
            monitor.cancel_event.set()
            raise
        result: InvocationResult | None = None
        caught: BaseException | None = None
        try:
            result = invoke(request)
        except BaseException as exc:  # retain transport exception unless the guard also fails
            caught = exc
        try:
            monitor.sample()
            monitor.check()
        except BaseException:
            monitor.cancel_event.set()
            raise
        if caught is not None:
            raise caught
        assert result is not None
        return result

    return call


@contextmanager
def _signal_guard(cancel_event: Any):
    previous: dict[int, Any] = {}

    def interrupt(signum: int, _frame: Any) -> None:
        cancel_event.set()
        raise _SignalInterruption(f"received signal {signum}; restoring resident window")

    for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        previous[signum] = signal.signal(signum, interrupt)
    try:
        yield
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def _initial_state(plan: dict[str, Any], initial: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": STATE_SCHEMA,
        "window_id": plan["window_id"],
        "pair_id": plan["pair_id"],
        "phase": "preflight",
        "plan_sha256": _receipt_sha(plan),
        "definition_sha256": plan["definition_sha256"],
        "run_manifest_sha256": plan["run_manifest_sha256"],
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "worker_pid": os.getpid(),
        "worker_start_ticks": _self_start_ticks(),
        "started_at": utc_now(),
        "initial": initial,
        "quiet_observation": None,
        "watchdog_sentinel_id": None,
        "nara_stop_attempted": False,
        "execution_gate_sha256": None,
        "restoration": {"status": "not_started"},
    }


def _worker(window_id: str, run_manifest_path: Path) -> int:
    definition, manifest, plan, window_dir, run_dir = _load_plan(window_id, run_manifest_path)
    _validate_plan_sources(plan)
    hard_deadline = time.monotonic() + plan["window_deadline_seconds"]
    work_cutoff = hard_deadline - plan["restoration_reserve_seconds"]
    error: str | None = None
    failure_stage: str | None = None
    run_sha: str | None = None
    gate_sha: str | None = None
    initial: dict[str, Any] | None = None
    quiet: dict[str, Any] | None = None
    final_observation: dict[str, Any] | None = None
    monitor: ResidentSafetyMonitor | None = None
    restoration: dict[str, Any] = {"status": "not_started"}
    state: dict[str, Any] | None = None
    preflight: dict[str, Any] | None = None
    nara_stopped_mono: float | None = None
    nara_restored_mono: float | None = None
    prior_lease_fd = os.environ.get("WEEKLY_UPGRADE_GPU_LEASE_FD")

    with resource_lease(canonical_root(CODE_ROOT)) as lease_fds:
        os.environ["WEEKLY_UPGRADE_GPU_LEASE_FD"] = str(lease_fds[-1])
        ops = HostOps()
        try:
            preflight = resource_probe(canonical_root(CODE_ROOT), idle=True)
            if preflight["mem_available_gib"] < plan["preflight_min_mem_available_gib"]:
                raise StableWindowError("resident preflight is below the registered memory floor")
            initial = _read_exact_residents(ops)
            state = _initial_state(plan, initial)
            _write_exclusive(window_dir / "state.json", state)
            monitor = ResidentSafetyMonitor(
                window_dir / "resident-memory.jsonl", ops, initial, deadline=hard_deadline
            )
            with monitor:
                try:
                    sentinel_id = _create_sentinel(ops, plan["pair_id"])
                    state["watchdog_sentinel_id"] = sentinel_id
                    state["phase"] = "sentinel_created"
                    _write_atomic(window_dir / "state.json", state)
                    monitor.bind_sentinel(sentinel_id)
                    _verify_sentinel(ops, plan["pair_id"], sentinel_id)

                    state["phase"] = "nara_quiescing"
                    _write_atomic(window_dir / "state.json", state)
                    monitor.transition("quiescing")
                    if initial["nara"]["ActiveState"] == "active":
                        state["nara_stop_attempted"] = True
                        _write_atomic(window_dir / "state.json", state)
                        ops.run(
                            ["systemctl", "--user", "stop", NARA_SERVICE],
                            timeout=max(0.1, min(30, work_cutoff - time.monotonic())),
                        )
                        nara_stopped_mono = time.monotonic()
                    quiet = _read_exact_residents(ops, initial, nara_transition=True)
                    if quiet["nara"]["ActiveState"] != "inactive":
                        raise StableWindowError("Nara was not quiescent before stable evaluation")
                    state["quiet_observation"] = quiet
                    _write_atomic(window_dir / "state.json", state)
                    monitor.transition("evaluation", cohort_initial=quiet)
                    start_sample = monitor.sample()
                    monitor.check()
                    _verify_sentinel(ops, plan["pair_id"], sentinel_id)
                    if work_cutoff - time.monotonic() < plan["runner_deadline_seconds"] + 60:
                        raise StableWindowError("stable arm no longer fits before restoration cutoff")
                    gate = freeze_execution_gate(
                        definition,
                        manifest,
                        plan=plan,
                        window_dir=window_dir,
                        quiet=quiet,
                        monitor=monitor,
                        start_sample=start_sample,
                        sentinel_id=sentinel_id,
                    )
                    gate_sha = _sha_bytes(canonical_json(gate) + b"\n")
                    state["execution_gate_sha256"] = gate_sha
                    state["phase"] = "evaluation"
                    _write_atomic(window_dir / "state.json", state)
                    runner_deadline = min(
                        work_cutoff,
                        time.monotonic() + plan["runner_deadline_seconds"],
                    )
                    with _signal_guard(monitor.cancel_event):
                        run_arm(
                            definition,
                            manifest,
                            output_dir=run_dir,
                            execution_gate=gate,
                            absolute_deadline_monotonic=runner_deadline,
                            cancel_event=monitor.cancel_event,
                            invoke=monitored_invoke(monitor),
                        )
                    for filename, digest in (
                        ("endpoint-bindings.json", gate["endpoint_bindings_sha256"]),
                        ("supervision-ready.json", gate["supervision_receipt_sha256"]),
                        ("resource-guard.json", gate["resource_guard_sha256"]),
                    ):
                        copied = _copy_regular_exclusive(
                            window_dir / filename,
                            run_dir / filename,
                            limit=2_000_000,
                        )
                        if copied != digest:
                            raise StableWindowError(
                                f"run-directory gate receipt differs: {filename}"
                            )
                    monitor.check()
                    _, run_sha = _read_json(run_dir / "run.json")
                except BaseException as exc:  # restoration owns every exit after state exists
                    error = f"{type(exc).__name__}: {exc}"
                    failure_stage = state["phase"]
                finally:
                    state["phase"] = "restoration"
                    _write_atomic(window_dir / "state.json", state)
                    try:
                        if monitor.phase != "restoration":
                            monitor.transition("restoration")
                    except BaseException as exc:
                        error = error or f"monitor restoration transition: {type(exc).__name__}: {exc}"
                        failure_stage = failure_stage or "restoration"
                    restoration = restore_resident_window(
                        ops,
                        state,
                        plan,
                        deadline=hard_deadline,
                        monitor=monitor if monitor.phase == "restoration" else None,
                    )
                    state["restoration"] = restoration
                    _write_atomic(window_dir / "state.json", state)
                    final_observation = restoration.get("final_observation")
                    if nara_stopped_mono is not None and restoration.get("status") == "verified":
                        nara_restored_mono = time.monotonic()
            if monitor.failure is not None:
                error = error or f"resident safety monitor: {monitor.failure}"
                failure_stage = failure_stage or "restoration"
            if monitor.cancel_event.is_set():
                error = error or "resident safety monitor canceled the run"
                failure_stage = failure_stage or "evaluation"
            if _available_gib() < plan["monitor_min_mem_available_gib"]:
                error = error or "final resident memory reserve breached"
                failure_stage = failure_stage or "restoration"
            if time.monotonic() >= hard_deadline:
                error = error or "absolute supervised-window deadline reached"
                failure_stage = failure_stage or "restoration"
        except BaseException as exc:
            error = error or f"{type(exc).__name__}: {exc}"
            failure_stage = failure_stage or (state or {}).get("phase", "preflight")
            if state is not None and restoration.get("status") != "verified":
                try:
                    _bind_uncaptured_sentinel(ops, state, plan, window_dir)
                    restoration = restore_resident_window(
                        ops, state, plan, deadline=hard_deadline
                    )
                    state["restoration"] = restoration
                    _write_atomic(window_dir / "state.json", state)
                    final_observation = restoration.get("final_observation")
                except BaseException as restore_exc:
                    restoration = {
                        "status": "unknown",
                        "verified_at": None,
                        "errors": [f"emergency restore: {type(restore_exc).__name__}: {restore_exc}"],
                        "sentinel_retained": True,
                        "final_observation": None,
                        "no_mutation_verified": False,
                    }
        finally:
            if prior_lease_fd is None:
                os.environ.pop("WEEKLY_UPGRADE_GPU_LEASE_FD", None)
            else:
                os.environ["WEEKLY_UPGRADE_GPU_LEASE_FD"] = prior_lease_fd

    monitor_end = bool(
        monitor is not None
        and monitor.failure is None
        and not monitor.cancel_event.is_set()
        and monitor.samples > 0
        and math.isfinite(monitor.minimum_observed_gib)
        and monitor.minimum_observed_gib >= plan["monitor_min_mem_available_gib"]
    )
    restored = bool(
        restoration.get("status") == "verified"
        and restoration.get("errors") == []
        and restoration.get("sentinel_retained") is False
        and isinstance(final_observation, dict)
        and final_observation.get("watchdog_sentinel_by_name") is None
        and final_observation.get("watchdog_sentinel_by_id") is None
    )
    complete = error is None and restored and monitor_end and run_sha is not None and gate_sha is not None
    if state is not None:
        state["phase"] = "complete" if complete else "failed" if restored else "recovery_unknown"
        state["result_status"] = "complete" if complete else "failed" if restored else "unknown"
        state["restoration"] = restoration
        _write_atomic(window_dir / "state.json", state)
    downtime = (
        max(0.0, (nara_restored_mono or time.monotonic()) - nara_stopped_mono)
        if nara_stopped_mono is not None
        else 0.0
    )
    memory_path = window_dir / "resident-memory.jsonl"
    result = {
        "schema_version": RESULT_SCHEMA,
        "window_id": plan["window_id"],
        "status": "complete" if complete else "failed" if restored else "unknown",
        "plan_sha256": _receipt_sha(plan),
        "definition_sha256": definition.raw_sha256,
        "run_manifest_sha256": manifest.raw_sha256,
        "run_receipt_sha256": run_sha,
        "execution_gate_sha256": gate_sha,
        "preflight": preflight,
        "initial_observation": initial,
        "quiet_observation": quiet,
        "final_observation": final_observation,
        "monitor_end_passed": monitor_end,
        "no_guard_breach": monitor_end,
        "restoration_passed": restored,
        "restoration": restoration,
        "memory_samples": monitor.samples if monitor is not None else 0,
        "min_mem_available_gib": (
            monitor.minimum_observed_gib
            if monitor is not None and math.isfinite(monitor.minimum_observed_gib)
            else None
        ),
        "memory_log_sha256": _sha_file(memory_path) if memory_path.is_file() else None,
        "nara_downtime_seconds": downtime,
        "error": error,
        "failure_stage": failure_stage,
        "paid_api_calls": 0,
        "production_change_authorized": False,
        "finished_at": utc_now(),
    }
    _write_exclusive(window_dir / "result.json", result)
    return 0 if complete else 1


def _validate_recovery_state(state: dict[str, Any], plan: dict[str, Any]) -> None:
    if (
        state.get("schema_version") != STATE_SCHEMA
        or state.get("window_id") != plan["window_id"]
        or state.get("pair_id") != plan["pair_id"]
        or state.get("plan_sha256") != _receipt_sha(plan)
        or state.get("definition_sha256") != plan["definition_sha256"]
        or state.get("run_manifest_sha256") != plan["run_manifest_sha256"]
        or state.get("boot_id") != Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        or type(state.get("worker_pid")) is not int
        or type(state.get("worker_start_ticks")) is not int
        or not isinstance(state.get("nara_stop_attempted"), bool)
    ):
        raise StableWindowError("emergency recovery state is not bound to this worker")
    initial = state.get("initial")
    if not isinstance(initial, dict) or len(initial.get("residents", [])) != len(RESIDENTS):
        raise StableWindowError("emergency recovery lacks the exact initial residents")
    for registered, captured in zip(RESIDENTS, initial["residents"], strict=True):
        if (
            captured.get("id") != registered["id"]
            or captured.get("name") != registered["name"]
            or captured.get("image") != registered["image_id"]
            or captured.get("running") is not True
            or captured.get("oom_killed") is not False
        ):
            raise StableWindowError("emergency recovery resident identity is untrusted")


def _bind_uncaptured_sentinel(
    ops: HostOps, state: dict[str, Any], plan: dict[str, Any], window_dir: Path
) -> None:
    """Durably bind the fixed stopped sentinel if interruption hit after create."""
    if state.get("watchdog_sentinel_id") is not None:
        return
    observed = _inspect_container(ops, _sentinel_name(plan["pair_id"]))
    if observed is None:
        return
    if (
        observed.get("image") != RESIDENTS[0]["image_id"]
        or observed.get("running") is not False
        or observed.get("oom_killed") is not False
        or observed.get("restart_policy") != "no"
        or not isinstance(observed.get("id"), str)
        or re.fullmatch(r"[0-9a-f]{64}", observed["id"]) is None
    ):
        raise StableWindowError("uncaptured stable watchdog sentinel is untrusted")
    state["watchdog_sentinel_id"] = observed["id"]
    _write_atomic(window_dir / "state.json", state)


def _emergency_restore(window_dir: Path, plan: dict[str, Any], deadline: float) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "schema_version": RECOVERY_SCHEMA,
        "window_id": plan["window_id"],
        "started_at": utc_now(),
        "status": "unknown",
        "restoration": None,
        "error": None,
    }
    try:
        state, _ = _read_json(window_dir / "state.json", limit=4_000_000)
        _validate_recovery_state(state, plan)
        with resource_lease(canonical_root(CODE_ROOT)):
            ops = HostOps()
            _bind_uncaptured_sentinel(ops, state, plan, window_dir)
            restoration = restore_resident_window(
                ops, state, plan, deadline=deadline
            )
        receipt["restoration"] = restoration
        receipt["status"] = restoration["status"]
        state["phase"] = "supervisor_recovered" if restoration["status"] == "verified" else "recovery_unknown"
        state["restoration"] = restoration
        _write_atomic(window_dir / "state.json", state)
    except BaseException as exc:
        receipt["error"] = f"{type(exc).__name__}: {exc}"
    receipt["finished_at"] = utc_now()
    _write_exclusive(window_dir / "supervisor-recovery.json", receipt)
    return receipt


def _result_restored(window_dir: Path, plan: dict[str, Any]) -> bool:
    try:
        result, _ = _read_json(window_dir / "result.json")
    except (OSError, StableWindowError):
        return False
    return bool(
        result.get("schema_version") == RESULT_SCHEMA
        and result.get("window_id") == plan["window_id"]
        and result.get("plan_sha256") == _receipt_sha(plan)
        and result.get("definition_sha256") == plan["definition_sha256"]
        and result.get("run_manifest_sha256") == plan["run_manifest_sha256"]
        and result.get("restoration_passed") is True
        and result.get("restoration", {}).get("status") == "verified"
        and result.get("restoration", {}).get("errors") == []
        and result.get("restoration", {}).get("sentinel_retained") is False
    )


def _verified_result(window_dir: Path, plan: dict[str, Any]) -> tuple[bool, dict[str, Any] | None]:
    try:
        result, _ = _read_json(window_dir / "result.json")
    except (OSError, StableWindowError):
        return False, None
    valid = bool(
        result.get("status") == "complete"
        and _result_restored(window_dir, plan)
        and result.get("monitor_end_passed") is True
        and result.get("no_guard_breach") is True
        and isinstance(result.get("memory_samples"), int)
        and result["memory_samples"] > 0
        and type(result.get("min_mem_available_gib")) in {int, float}
        and math.isfinite(result["min_mem_available_gib"])
        and result["min_mem_available_gib"] >= plan["monitor_min_mem_available_gib"]
        and isinstance(result.get("run_receipt_sha256"), str)
        and SHA256.fullmatch(result["run_receipt_sha256"]) is not None
        and isinstance(result.get("execution_gate_sha256"), str)
        and SHA256.fullmatch(result["execution_gate_sha256"]) is not None
    )
    return valid, result


def finalize_run(
    definition: LoadedDocument,
    manifest: LoadedDocument,
    *,
    plan: dict[str, Any],
    window_dir: Path,
    run_dir: Path,
    lifecycle_valid: bool,
    lifecycle_result: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str | None]:
    """Replay, freeze supervisor-final in-place, and invoke admission."""
    try:
        replay = replay_run(definition, manifest, run_dir=run_dir)
        _, run_sha = _read_json(run_dir / "run.json")
        _, replay_sha = _read_json(run_dir / "replay.json")
        _, gate_sha = _read_json(run_dir / "execution-gate.snapshot.json", limit=2_000_000)
        final = {
            "schema_version": SUPERVISOR_FINAL_SCHEMA,
            "terminal_status": "complete" if lifecycle_valid else "failed",
            "definition_sha256": definition.raw_sha256,
            "run_manifest_sha256": manifest.raw_sha256,
            "run_receipt_sha256": run_sha,
            "replay_receipt_sha256": replay_sha,
            "execution_gate_sha256": gate_sha,
            "monitor_end_passed": lifecycle_result.get("monitor_end_passed") is True,
            "no_guard_breach": lifecycle_result.get("no_guard_breach") is True,
            "restoration_passed": lifecycle_result.get("restoration_passed") is True,
            "controller_source_sha256": plan["controller_source_sha256"],
            "finished_at": utc_now(),
        }
        _write_exclusive(run_dir / "supervisor-final.json", final)
        admission = admit_replay(
            definition,
            manifest,
            run_dir=run_dir,
            supervisor_final_path=run_dir / "supervisor-final.json",
        )
        return replay, admission, None
    except BaseException as exc:
        return None, None, f"{type(exc).__name__}: {exc}"


def _terminate_process_group(
    proc: subprocess.Popen[Any], *, deadline: float
) -> tuple[bool, bool]:
    if proc.poll() is not None:
        return False, False
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return False, False
    while proc.poll() is None and time.monotonic() < deadline:
        time.sleep(min(1, max(0, deadline - time.monotonic())))
    if proc.poll() is None:
        killed = True
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        return True, killed
    return True, False


def _supervise(
    definition: LoadedDocument,
    manifest: LoadedDocument,
    plan: dict[str, Any],
) -> int:
    window_dir = Path(plan["window_dir"])
    run_dir = Path(plan["run_dir"])
    if window_dir.exists() or run_dir.exists():
        raise StableWindowError("stable window or arm output already exists")
    window_dir.parent.mkdir(parents=True, exist_ok=True)
    if window_dir.parent.is_symlink() or not window_dir.parent.is_dir():
        raise StableWindowError("lifecycle window root is redirected")
    window_dir.mkdir(mode=0o700)
    _write_exclusive(window_dir / "window.json", plan)
    command = [
        plan["launcher_python_path"],
        "-m",
        "bench.stable_benchmark.supervised_window",
        "--worker",
        "--window-id",
        plan["window_id"],
        "--run-manifest",
        str(manifest.path),
    ]
    env = dict(os.environ)
    for key in (
        "MOCK_LLM",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "VLLM_API_KEY",
        "VLLM_MODEL_VERSION",
        "VLLM_QWEN_MODEL_VERSION",
        "VLLM_IMAGE_TAG",
        "VLLM_QWEN_IMAGE_TAG",
        "WRAPPER_PROFILE_OVERRIDES",
    ):
        env.pop(key, None)
    env.update({
        "VLLM_BASE_URL": "http://127.0.0.1:8000/v1",
        "VLLM_MODEL": "gemma-4-26b-a4b",
        "VLLM_QWEN_BASE_URL": "http://127.0.0.1:8001/v1",
        "VLLM_QWEN_MODEL": "qwen3.8-27b-nvfp4-mtp",
        "WRAPPER_DEFAULT_BACKEND": "vllm-gemma",
        "NO_PROXY": "127.0.0.1,localhost",
        "no_proxy": "127.0.0.1,localhost",
    })
    started = time.monotonic()
    started_wall = datetime.now(timezone.utc)
    hard_deadline = started + plan["window_deadline_seconds"]
    work_cutoff = hard_deadline - plan["restoration_reserve_seconds"]
    terminated = False
    force_killed = False
    with (window_dir / "controller.log").open("xb") as stream:
        proc = subprocess.Popen(
            command,
            cwd=CODE_ROOT,
            env=env,
            stdout=stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            worker_start_ticks = _process_start_ticks(proc.pid)
        except BaseException:
            worker_start_ticks = None
        try:
            worker_pgid = os.getpgid(proc.pid)
        except ProcessLookupError:
            worker_pgid = None
        _write_exclusive(window_dir / "process.json", {
            "schema_version": PROCESS_SCHEMA,
            "window_id": plan["window_id"],
            "plan_sha256": _receipt_sha(plan),
            "pid": proc.pid,
            "pgid": worker_pgid,
            "worker_start_ticks": worker_start_ticks,
            "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
            "argv_sha256": _sha_json(command),
            "started_at": started_wall.isoformat(),
        })
        while proc.poll() is None and time.monotonic() < work_cutoff:
            time.sleep(min(1, max(0, work_cutoff - time.monotonic())))
        if proc.poll() is None:
            terminated, force_killed = _terminate_process_group(
                proc, deadline=min(hard_deadline - 480, time.monotonic() + TERM_GRACE_SECONDS)
            )
        if proc.poll() is None:
            force_killed = True
            try:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=5)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                pass

    recovery = None
    if not _result_restored(window_dir, plan):
        if proc.poll() is None:
            recovery = {
                "schema_version": RECOVERY_SCHEMA,
                "window_id": plan["window_id"],
                "status": "unknown",
                "restoration": None,
                "error": "worker termination is not verified",
                "started_at": utc_now(),
                "finished_at": utc_now(),
            }
            _write_exclusive(window_dir / "supervisor-recovery.json", recovery)
        else:
            recovery = _emergency_restore(window_dir, plan, hard_deadline)

    lifecycle_valid, lifecycle_result = _verified_result(window_dir, plan)
    replay = admission = None
    finalization_error = None
    if run_dir.is_dir() and (run_dir / "run.json").is_file() and lifecycle_result is not None:
        replay, admission, finalization_error = finalize_run(
            definition,
            manifest,
            plan=plan,
            window_dir=window_dir,
            run_dir=run_dir,
            lifecycle_valid=(
                lifecycle_valid
                and not terminated
                and not force_killed
                and recovery is None
                and proc.returncode == 0
            ),
            lifecycle_result=lifecycle_result,
        )
    complete = bool(
        lifecycle_valid
        and not terminated
        and not force_killed
        and recovery is None
        and proc.returncode == 0
        and worker_start_ticks is not None
        and replay is not None
        and replay.get("terminal_status") == "verified"
        and replay.get("verified") is True
        and admission is not None
        and admission.get("admitted") is True
        and admission.get("admission_status") == "admitted"
        and finalization_error is None
        and time.monotonic() <= hard_deadline
    )
    supervision = {
        "schema_version": SUPERVISION_SCHEMA,
        "window_id": plan["window_id"],
        "plan_sha256": _receipt_sha(plan),
        "command_sha256": _sha_json(command),
        "argv": command,
        "pid": proc.pid,
        "worker_start_ticks": worker_start_ticks,
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "started_at": started_wall.isoformat(),
        "hard_deadline_at": (
            started_wall + timedelta(seconds=plan["window_deadline_seconds"])
        ).isoformat(),
        "returncode": proc.returncode,
        "complete": complete,
        "terminated_at_work_cutoff": terminated,
        "force_killed": force_killed,
        "emergency_recovery": recovery,
        "lifecycle_result_sha256": (
            _sha_file(window_dir / "result.json")
            if (window_dir / "result.json").is_file()
            else None
        ),
        "replay_terminal_status": replay.get("terminal_status") if replay else None,
        "admission_status": admission.get("admission_status") if admission else None,
        "finalization_error": finalization_error,
        "elapsed_seconds": max(0.0, time.monotonic() - started),
        "finished_at": utc_now(),
    }
    _write_exclusive(window_dir / "supervision.json", supervision)
    return 0 if complete else 1


def _write_unissued(manifest_path: Path, reason: str) -> int:
    definition, manifest = _load_inputs(manifest_path)
    _, run_dir, comparison_root = _registered_paths(definition, manifest)
    if not reason or len(reason) > 1000:
        raise StableWindowError("unissued reason must be bounded nonempty text")
    comparison_root.mkdir(parents=True, exist_ok=True)
    write_unissued_receipt(
        definition, manifest, output_dir=run_dir, reason=reason
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--plan", action="store_true")
    modes.add_argument("--run", action="store_true")
    modes.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    modes.add_argument("--unissued", action="store_true")
    parser.add_argument("--window-id")
    parser.add_argument("--run-manifest", required=True, type=Path)
    parser.add_argument("--reason")
    args = parser.parse_args(argv)

    if args.unissued:
        if args.window_id is not None or args.reason is None:
            parser.error("--unissued requires --reason and does not accept --window-id")
        return _write_unissued(args.run_manifest, args.reason)
    if args.reason is not None or args.window_id is None:
        parser.error("--plan/--run/--worker require --window-id and do not accept --reason")
    if args.worker:
        return _worker(args.window_id, args.run_manifest)
    definition, manifest = _load_inputs(args.run_manifest)
    plan = build_plan(definition, manifest, window_id=args.window_id)
    if args.plan:
        print(json.dumps(plan, sort_keys=True, indent=2, allow_nan=False))
        return 0
    return _supervise(definition, manifest, plan)


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "StableWindowError",
    "build_plan",
    "controller_source_hashes",
    "finalize_run",
    "freeze_execution_gate",
    "main",
    "monitored_invoke",
    "validate_resident_arm",
]
