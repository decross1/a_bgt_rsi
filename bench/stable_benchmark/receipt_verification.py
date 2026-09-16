"""Pure verification of preregistered stable-benchmark receipt chains.

This module is a read-only trust boundary for the UI.  It never grades a
response, imports generated code, calls a model, or compares an historical run
with the source files in the current checkout.  Instead, a source-controlled
registration freezes the expected definition, arm order, receipt locations,
and source maps before execution.  The verifier then checks the bounded public
receipt chain against that registration.  Resource evidence is verified as a
source-bound supervisor attestation: the verifier binds the monitor log bytes,
sample count, process identity, and terminal timeline, but does not replay host
monitoring syscalls during an HTTP read.

``receipt_verification.py`` is intentionally absent from the causal execution
source bundle.  Editing a read model must not relabel the benchmark harness.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from .manifest import LoadedDocument, canonical_json


REGISTRATION_SCHEMA = "stable-benchmark-comparison-registration/v1"
RUN_SCHEMA = "stable-benchmark-run-receipt/v1"
REPLAY_SCHEMA = "stable-benchmark-replay-receipt/v1"
ADMISSION_SCHEMA = "stable-benchmark-admission-receipt/v1"
SUPERVISOR_FINAL_SCHEMA = "stable-benchmark-supervisor-final/v1"
WINDOW_SCHEMA = "stable-benchmark-supervised-window-plan/v1"
PROCESS_SCHEMA = "stable-benchmark-supervised-process/v1"
STATE_SCHEMA = "stable-benchmark-supervised-window-state/v1"
RESULT_SCHEMA = "stable-benchmark-supervised-window-result/v1"
SUPERVISION_SCHEMA = "stable-benchmark-supervision/v1"
ENDPOINT_BINDINGS_SCHEMA = "stable-benchmark-endpoint-bindings/v1"
SUPERVISION_READY_SCHEMA = "stable-benchmark-supervision-ready/v1"
RESOURCE_GUARD_SCHEMA = "stable-benchmark-resource-guard/v1"

SHA256 = re.compile(r"[0-9a-f]{64}\Z")
SAFE_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,95}\Z")
MAX_REGISTRATION_BYTES = 1_000_000
MAX_RECEIPT_BYTES = 8_000_000
MAX_MEMORY_LOG_BYTES = 64_000_000
MAX_SOURCE_BYTES = 16_000_000
MAX_SOURCES = 128


class ReceiptVerificationError(ValueError):
    """A registration or its public receipt chain is malformed or mismatched."""


@dataclass(frozen=True)
class LoadedRegistration:
    document: dict[str, Any]
    raw_sha256: str
    path: Path


@dataclass(frozen=True)
class VerifiedArm:
    comparison_id: str
    arm_id: str
    role: str
    terminal_status: str
    admission_status: str
    admitted: bool
    manifest: dict[str, Any]
    manifest_sha256: str
    run: dict[str, Any]
    run_sha256: str
    replay: dict[str, Any] | None
    replay_sha256: str | None
    admission: dict[str, Any] | None
    admission_sha256: str | None
    lifecycle_plan: dict[str, Any] | None
    lifecycle_plan_sha256: str | None
    source_files_verified: bool
    resource_evidence_level: str | None


REGISTRATION_FIELDS = {
    "schema_version", "suite_id", "release", "comparison_id",
    "registered_at", "definition", "arms",
}
ARM_FIELDS = {
    "arm_id", "role", "manifest", "run_receipt_directory",
    "execution_source_sha256", "replay_source_sha256",
    "admission_source_sha256", "lifecycle",
}
FILE_BINDING_FIELDS = {"path", "sha256"}
LIFECYCLE_FIELDS = {
    "window_id", "window_plan_sha256", "controller_source_sha256",
    "worker_argv_sha256", "receipt_directory",
}
MANIFEST_FIELDS = {
    "schema_version", "suite_id", "release", "definition_sha256",
    "comparison_id", "arm", "harness_identity", "task_ids",
    "resource_envelope", "ordering", "admission_authorized",
}
RUN_FIELDS = {
    "schema_version", "run_id", "terminal_status", "started_at",
    "finished_at", "elapsed_s", "definition_sha256",
    "run_manifest_sha256", "execution_gate_sha256",
    "execution_source_sha256", "arm_id", "comparison_id", "outcomes",
    "summary", "replay_status", "admission_status",
    "promotion_authorized",
}
REPLAY_FIELDS = {
    "schema_version", "generated_at", "terminal_status", "verified",
    "arm_id", "comparison_id", "run_receipt_sha256",
    "raw_evidence_log_sha256", "definition_sha256",
    "run_manifest_sha256", "replay_source_sha256", "outcomes",
    "mismatches", "admission_authorized",
}
ADMISSION_FIELDS = {
    "schema_version", "generated_at", "admission_status", "admitted",
    "reasons", "definition_sha256", "run_manifest_sha256",
    "run_receipt_sha256", "replay_receipt_sha256",
    "supervisor_final_receipt_sha256", "admission_source_sha256",
    "arm_id", "comparison_id", "promotion_authorized",
}
SUPERVISOR_FINAL_FIELDS = {
    "schema_version", "terminal_status", "definition_sha256",
    "run_manifest_sha256", "run_receipt_sha256",
    "replay_receipt_sha256", "execution_gate_sha256",
    "monitor_end_passed", "no_guard_breach", "restoration_passed",
    "controller_source_sha256", "finished_at",
}
GATE_FIELDS = {
    "admitted", "definition_sha256", "run_manifest_sha256",
    "route_runtime_identities", "endpoint_bindings_sha256",
    "supervision_receipt_sha256", "resource_guard_sha256",
}
ENDPOINT_FIELDS = {
    "schema_version", "window_id", "definition_sha256",
    "run_manifest_sha256", "routes", "raw_ports_exposed", "frozen_at",
}
ENDPOINT_ROUTE_FIELDS = {
    "endpoint_name", "backend", "served_model", "profile",
    "expected_policy", "runtime_identity", "container_name",
    "container_id", "container_image_id", "endpoint_spec",
}
READY_FIELDS = {
    "schema_version", "window_id", "plan_sha256", "worker_pid",
    "worker_start_ticks", "boot_id", "definition_sha256",
    "run_manifest_sha256", "controller_source_sha256",
    "resident_qualification", "endpoint_bindings_sha256",
    "quiet_observation_sha256", "nara_active_state",
    "watchdog_sentinel_id", "restoration_owner", "ready_at",
}
RESOURCE_FIELDS = {
    "schema_version", "window_id", "monitor_phase",
    "minimum_mem_available_gib", "maximum_sample_gap_seconds",
    "start_sample", "cancel_sentinel", "checks", "armed_at",
}
WINDOW_FIELDS = {
    "schema_version", "window_id", "pair_id", "execution_mode",
    "code_root", "git_head", "window_dir", "run_dir", "definition_path",
    "definition_sha256", "run_manifest_path", "run_manifest_sha256",
    "arm_id", "comparison_id", "resource_envelope",
    "window_deadline_seconds", "restoration_reserve_seconds",
    "runner_deadline_seconds", "preflight_min_mem_available_gib",
    "monitor_min_mem_available_gib", "monitor_max_sample_gap_seconds",
    "nara_service", "nara_isolation", "resident_container_action",
    "watchdog_sentinel_name", "launcher_python_path",
    "resident_qualification", "controller_source_sha256",
    "controller_source_bundle_sha256", "paid_api_allowed",
    "production_change_authorized", "candidate_startup_supported",
}
PROCESS_FIELDS = {
    "schema_version", "window_id", "plan_sha256", "pid", "pgid",
    "worker_start_ticks", "boot_id", "argv_sha256", "started_at",
}
RESULT_FIELDS = {
    "schema_version", "window_id", "status", "plan_sha256",
    "definition_sha256", "run_manifest_sha256", "run_receipt_sha256",
    "execution_gate_sha256", "preflight", "initial_observation",
    "quiet_observation", "final_observation", "monitor_end_passed",
    "no_guard_breach", "restoration_passed", "restoration",
    "memory_samples", "min_mem_available_gib", "memory_log_sha256",
    "nara_downtime_seconds", "error", "failure_stage", "paid_api_calls",
    "production_change_authorized", "finished_at",
}
SUPERVISION_FIELDS = {
    "schema_version", "window_id", "plan_sha256", "command_sha256",
    "argv", "pid", "worker_start_ticks", "boot_id", "started_at",
    "hard_deadline_at", "returncode", "complete",
    "terminated_at_work_cutoff", "force_killed", "emergency_recovery",
    "lifecycle_result_sha256", "replay_terminal_status",
    "admission_status", "finalization_error", "elapsed_seconds",
    "finished_at",
}


def _fail(message: str) -> None:
    raise ReceiptVerificationError(message)


def _digest(value: Any, where: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        _fail(f"{where} must be a lowercase SHA-256 digest")
    return value


def _identifier(value: Any, where: str) -> str:
    if not isinstance(value, str) or SAFE_ID.fullmatch(value) is None:
        _fail(f"{where} is not a safe identifier")
    return value


def _utc(value: Any, where: str) -> datetime:
    if not isinstance(value, str) or len(value) > 40 or not value.endswith("Z"):
        _fail(f"{where} must be a bounded RFC3339 UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ReceiptVerificationError(f"{where} is not a timestamp") from exc
    if parsed.tzinfo != timezone.utc:
        _fail(f"{where} must be UTC")
    return parsed


def _timestamp(value: Any, where: str) -> datetime:
    if not isinstance(value, str) or not value or len(value) > 40:
        _fail(f"{where} must be a bounded timezone-aware timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReceiptVerificationError(f"{where} is not a timestamp") from exc
    if parsed.tzinfo is None:
        _fail(f"{where} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _positive_int(value: Any, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        _fail(f"{where} must be a positive integer")
    return value


def _absolute_path(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 1024 or "\x00" in value:
        _fail(f"{where} must be a bounded absolute path")
    path = Path(value)
    if not path.is_absolute() or os.path.normpath(value) != value:
        _fail(f"{where} must be an absolute normalized path")
    return value


def _source_map(value: Any, where: str) -> dict[str, str]:
    if not isinstance(value, dict) or not value or len(value) > MAX_SOURCES:
        _fail(f"{where} must be a nonempty bounded source map")
    result: dict[str, str] = {}
    for path, digest in value.items():
        if not isinstance(path, str) or not path or len(path) > 320:
            _fail(f"{where} contains an invalid source path")
        pure = PurePosixPath(path)
        if pure.is_absolute() or ".." in pure.parts or str(pure) != path:
            _fail(f"{where} contains a non-normalized source path")
        result[path] = _digest(digest, f"{where}[{path!r}]")
    return result


def _bound_shape(value: Any, *, max_depth: int = 32, max_nodes: int = 50_000) -> None:
    pending = [(value, 0)]
    nodes = 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if depth > max_depth or nodes > max_nodes:
            _fail("JSON document exceeds structural bounds")
        if isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
        elif isinstance(item, float) and not math.isfinite(item):
            _fail("JSON document contains a non-finite number")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _safe_read(path: Path, *, limit: int) -> tuple[bytes, str]:
    target = path.absolute()
    try:
        if target.resolve(strict=True) != target:
            _fail(f"artifact path is redirected: {target}")
        before = target.lstat()
    except OSError as exc:
        raise ReceiptVerificationError(f"cannot stat {target}: {exc}") from exc
    if not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode):
        _fail(f"artifact is not a regular non-symlink file: {target}")
    if before.st_size > limit:
        _fail(f"artifact exceeds {limit} bytes: {target}")
    descriptor = os.open(
        target,
        os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            _fail(f"artifact identity changed during open: {target}")
        chunks: list[bytes] = []
        remaining = limit + 1
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
    finally:
        os.close(descriptor)
    if len(raw) != before.st_size or len(raw) > limit:
        _fail(f"artifact size changed or exceeded its bound: {target}")
    return raw, hashlib.sha256(raw).hexdigest()


def _read_document(path: Path, *, limit: int = MAX_RECEIPT_BYTES) -> tuple[dict[str, Any], str]:
    raw, digest = _safe_read(path, limit=limit)
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_unique_object,
            parse_constant=lambda item: (_ for _ in ()).throw(
                ReceiptVerificationError(f"non-finite JSON constant {item}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReceiptVerificationError(f"cannot decode {path}: {exc}") from exc
    if not isinstance(value, dict):
        _fail(f"artifact is not an object: {path}")
    _bound_shape(value)
    return value, digest


def validate_registration(
    document: Any,
    definition: LoadedDocument | None = None,
) -> dict[str, Any]:
    """Validate one source-controlled comparison registration."""
    if not isinstance(document, dict) or set(document) != REGISTRATION_FIELDS:
        _fail("registration top-level fields differ")
    if document["schema_version"] != REGISTRATION_SCHEMA:
        _fail("registration schema differs")
    suite_id = _identifier(document["suite_id"], "suite_id")
    comparison_id = _identifier(document["comparison_id"], "comparison_id")
    release = document["release"]
    if not isinstance(release, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", release):
        _fail("release must be a semantic version")
    registered_at = _utc(document["registered_at"], "registered_at")
    definition_binding = document["definition"]
    if not isinstance(definition_binding, dict) or set(definition_binding) != FILE_BINDING_FIELDS:
        _fail("definition binding fields differ")
    _absolute_path(definition_binding["path"], "definition.path")
    _digest(definition_binding["sha256"], "definition.sha256")
    arms = document["arms"]
    if not isinstance(arms, list) or len(arms) != 2:
        _fail("registration must contain ordered reference and candidate arms")
    if [arm.get("role") if isinstance(arm, dict) else None for arm in arms] != [
        "reference", "candidate"
    ]:
        _fail("arm order must be reference then candidate")
    arm_ids: list[str] = []
    for index, arm in enumerate(arms):
        where = f"arms[{index}]"
        if not isinstance(arm, dict) or set(arm) != ARM_FIELDS:
            _fail(f"{where} fields differ")
        arm_id = _identifier(arm["arm_id"], f"{where}.arm_id")
        arm_ids.append(arm_id)
        manifest = arm["manifest"]
        if not isinstance(manifest, dict) or set(manifest) != FILE_BINDING_FIELDS:
            _fail(f"{where}.manifest fields differ")
        _absolute_path(manifest["path"], f"{where}.manifest.path")
        _digest(manifest["sha256"], f"{where}.manifest.sha256")
        _absolute_path(arm["run_receipt_directory"], f"{where}.run_receipt_directory")
        for key in (
            "execution_source_sha256", "replay_source_sha256",
            "admission_source_sha256",
        ):
            _source_map(arm[key], f"{where}.{key}")
        lifecycle = arm["lifecycle"]
        if lifecycle is None:
            if arm["role"] != "candidate":
                _fail("only the candidate arm may be preregistered as unissued")
            continue
        if not isinstance(lifecycle, dict) or set(lifecycle) != LIFECYCLE_FIELDS:
            _fail(f"{where}.lifecycle fields differ")
        _identifier(lifecycle["window_id"], f"{where}.lifecycle.window_id")
        _digest(lifecycle["window_plan_sha256"], f"{where}.lifecycle.window_plan_sha256")
        _digest(lifecycle["worker_argv_sha256"], f"{where}.lifecycle.worker_argv_sha256")
        _source_map(
            lifecycle["controller_source_sha256"],
            f"{where}.lifecycle.controller_source_sha256",
        )
        _absolute_path(
            lifecycle["receipt_directory"],
            f"{where}.lifecycle.receipt_directory",
        )
    if len(set(arm_ids)) != 2:
        _fail("registered arm IDs must be unique")
    if definition is not None:
        if (
            definition.raw_sha256 != definition_binding["sha256"]
            or definition.document.get("suite_id") != suite_id
            or definition.document.get("release") != release
        ):
            _fail("registration binds a different definition")
        published_at = definition.document.get("freeze", {}).get("published_at")
        if published_at is None or _utc(published_at, "definition.freeze.published_at") > registered_at:
            _fail("registration predates definition publication")
    canonical_json(document)
    return document


def load_registration(
    path: Path | str,
    definition: LoadedDocument | None = None,
) -> LoadedRegistration:
    """Load a bounded, non-redirected registration from the checked-out repo."""
    target = Path(path).absolute()
    document, digest = _read_document(target, limit=MAX_REGISTRATION_BYTES)
    validate_registration(document, definition)
    return LoadedRegistration(document=document, raw_sha256=digest, path=target)


def _exact_fields(document: dict[str, Any], expected: set[str], where: str) -> None:
    if set(document) != expected:
        _fail(f"{where} fields differ")


def _arm_entry(registration: LoadedRegistration, arm_id: str) -> dict[str, Any]:
    matches = [arm for arm in registration.document["arms"] if arm["arm_id"] == arm_id]
    if len(matches) != 1:
        _fail(f"arm {arm_id!r} is not uniquely registered")
    return matches[0]


def _check_file_binding(binding: dict[str, Any], where: str) -> tuple[dict[str, Any], str]:
    document, digest = _read_document(Path(binding["path"]))
    if digest != binding["sha256"]:
        _fail(f"{where} bytes differ from the registration")
    return document, digest


def _check_snapshot(path: Path, expected_sha: str, where: str) -> None:
    _, digest = _safe_read(path, limit=MAX_RECEIPT_BYTES)
    if digest != expected_sha:
        _fail(f"{where} snapshot bytes differ")


def _registration_time(registration: LoadedRegistration) -> datetime:
    return _utc(registration.document["registered_at"], "registered_at")


def _validate_manifest(
    manifest: dict[str, Any],
    *,
    manifest_sha: str,
    registration: LoadedRegistration,
    arm: dict[str, Any],
    definition: LoadedDocument,
) -> None:
    _exact_fields(manifest, MANIFEST_FIELDS, "run manifest")
    if manifest.get("schema_version") != "stable-benchmark-run-manifest/v1":
        _fail("run manifest schema differs")
    expected = {
        "suite_id": registration.document["suite_id"],
        "release": registration.document["release"],
        "definition_sha256": definition.raw_sha256,
        "comparison_id": registration.document["comparison_id"],
    }
    if any(manifest.get(key) != value for key, value in expected.items()):
        _fail("run manifest identity differs from the registration")
    if manifest.get("arm", {}).get("id") != arm["arm_id"]:
        _fail("run manifest arm differs from the registration")
    if manifest_sha != arm["manifest"]["sha256"]:
        _fail("run manifest digest differs")
    if manifest.get("harness_identity", {}).get("source_sha256") != arm["execution_source_sha256"]:
        _fail("manifest harness sources differ from the preregistered execution map")
    if manifest.get("task_ids") != [task["id"] for task in definition.document["tasks"]]:
        _fail("run manifest task order differs from the definition")
    if manifest.get("resource_envelope") != definition.document["resource_envelope"]:
        _fail("run manifest resource envelope differs")
    if manifest.get("ordering") != "frozen_definition_order" or manifest.get("admission_authorized") is not False:
        _fail("run manifest ordering or authority differs")


def _validate_run_common(
    run: dict[str, Any],
    *,
    registration: LoadedRegistration,
    arm: dict[str, Any],
    definition: LoadedDocument,
) -> None:
    _exact_fields(run, RUN_FIELDS, "run receipt")
    if run.get("schema_version") != RUN_SCHEMA:
        _fail("run receipt schema differs")
    expected = {
        "definition_sha256": definition.raw_sha256,
        "run_manifest_sha256": arm["manifest"]["sha256"],
        "execution_source_sha256": arm["execution_source_sha256"],
        "arm_id": arm["arm_id"],
        "comparison_id": registration.document["comparison_id"],
        "promotion_authorized": False,
    }
    if any(run.get(key) != value for key, value in expected.items()):
        _fail("run receipt differs from the preregistered identity or source map")
    outcomes = run.get("outcomes")
    task_ids = [task["id"] for task in definition.document["tasks"]]
    if (
        not isinstance(outcomes, list)
        or len(outcomes) != len(task_ids)
        or [row.get("task_id") if isinstance(row, dict) else None for row in outcomes] != task_ids
    ):
        _fail("run receipt does not contain the exact ordered task set")
    finished = _utc(run.get("finished_at"), "run.finished_at")
    if finished < _registration_time(registration):
        _fail("run finished before preregistration")
    if run.get("started_at") is not None:
        started = _utc(run["started_at"], "run.started_at")
        if started < _registration_time(registration) or finished < started:
            _fail("run timing is inconsistent with preregistration")


def _validate_unissued(
    directory: Path,
    run: dict[str, Any],
    definition: LoadedDocument,
) -> None:
    if (
        run.get("terminal_status") != "unissued"
        or run.get("started_at") is not None
        or run.get("elapsed_s") != 0.0
        or run.get("execution_gate_sha256") is not None
        or run.get("replay_status") != "not_applicable"
        or run.get("admission_status") != "withheld_unissued"
    ):
        _fail("unissued run terminal contract differs")
    for row in run["outcomes"]:
        if (
            not isinstance(row, dict)
            or row.get("cell_status") != "unissued"
            or type(row.get("model_calls")) is not int
            or row["model_calls"] != 0
            or row.get("model_calls_exact") is not True
            or row.get("score_credit") is not False
        ):
            _fail("unissued run contains a scored or attempted task")
    if run.get("summary", {}).get("model_calls") != 0:
        _fail("unissued run summary contains model calls")
    forbidden = (
        "execution-gate.snapshot.json", "endpoint-bindings.json",
        "supervision-ready.json", "resource-guard.json", "replay.json",
        "supervisor-final.json", "admission.json",
    )
    if any((directory / name).exists() or (directory / name).is_symlink() for name in forbidden):
        _fail("unissued arm contains lifecycle, replay, or admission artifacts")
    expected_ids = [task["id"] for task in definition.document["tasks"]]
    if [row["task_id"] for row in run["outcomes"]] != expected_ids:
        _fail("unissued task accounting differs from the definition")


def _validate_endpoint_routes(endpoint: dict[str, Any], manifest: dict[str, Any]) -> None:
    routes = endpoint.get("routes")
    expected_routes = manifest.get("arm", {}).get("routes", {})
    if not isinstance(routes, dict) or set(routes) != set(expected_routes):
        _fail("endpoint bindings do not contain the registered routes")
    for route_id, binding in routes.items():
        if not isinstance(binding, dict) or set(binding) != ENDPOINT_ROUTE_FIELDS:
            _fail(f"endpoint binding {route_id!r} fields differ")
        expected = expected_routes[route_id]
        checks = {
            "backend": expected["backend"],
            "served_model": expected["model"],
            "profile": expected["profile"],
            "expected_policy": expected["expected_policy"],
            "runtime_identity": expected["runtime_identity"],
        }
        if any(binding.get(key) != value for key, value in checks.items()):
            _fail(f"endpoint binding {route_id!r} differs from its manifest route")
        for key in ("endpoint_name", "container_name", "container_id", "container_image_id"):
            if not isinstance(binding.get(key), str) or not binding[key] or len(binding[key]) > 512:
                _fail(f"endpoint binding {route_id!r} has invalid {key}")
        if binding.get("endpoint_spec") != {
            "transport": "openai_chat_completions",
            "network_scope": "controller_fixed_loopback",
            "qualification": "registered_container_identity_plus_health_probe",
        }:
            _fail(f"endpoint binding {route_id!r} has an unexpected endpoint spec")


def _verify_source_tree(
    plan: dict[str, Any],
    arm: dict[str, Any],
    *,
    allowed_code_roots: Iterable[Path | str],
) -> bool:
    roots = tuple(Path(root).absolute() for root in allowed_code_roots)
    if not roots:
        return False
    code_root = Path(plan.get("code_root", "")).absolute()
    if code_root not in roots:
        _fail("lifecycle code root is not an allowed frozen worktree")
    try:
        if code_root.resolve(strict=True) != code_root or not code_root.is_dir():
            _fail("lifecycle code root is redirected or absent")
    except OSError as exc:
        raise ReceiptVerificationError(f"cannot verify lifecycle code root: {exc}") from exc
    combined: dict[str, str] = {}
    maps = [
        arm["execution_source_sha256"], arm["replay_source_sha256"],
        arm["admission_source_sha256"],
        arm["lifecycle"]["controller_source_sha256"],
    ]
    for source_map in maps:
        for relative, expected in source_map.items():
            if relative in combined and combined[relative] != expected:
                _fail(f"registered source maps disagree for {relative}")
            combined[relative] = expected
    for relative, expected in combined.items():
        _, observed = _safe_read(code_root / relative, limit=MAX_SOURCE_BYTES)
        if observed != expected:
            _fail(f"frozen source file differs: {relative}")
    return True


def _validate_lifecycle(
    registration: LoadedRegistration,
    arm: dict[str, Any],
    definition: LoadedDocument,
    manifest: dict[str, Any],
    run: dict[str, Any],
    run_sha: str,
    run_directory: Path,
    *,
    allowed_code_roots: Iterable[Path | str],
) -> tuple[
    dict[str, Any], str, dict[str, Any], str, dict[str, Any], str, bool,
    dict[str, datetime],
]:
    lifecycle = arm["lifecycle"]
    assert isinstance(lifecycle, dict)
    lifecycle_dir = Path(lifecycle["receipt_directory"])
    window, window_sha = _read_document(lifecycle_dir / "window.json", limit=2_000_000)
    _exact_fields(window, WINDOW_FIELDS, "lifecycle window plan")
    if window.get("schema_version") != WINDOW_SCHEMA or window_sha != lifecycle["window_plan_sha256"]:
        _fail("lifecycle window plan schema or digest differs")
    expected_window = {
        "window_id": lifecycle["window_id"],
        "window_dir": str(lifecycle_dir),
        "run_dir": str(run_directory),
        "definition_path": registration.document["definition"]["path"],
        "definition_sha256": definition.raw_sha256,
        "run_manifest_path": arm["manifest"]["path"],
        "run_manifest_sha256": arm["manifest"]["sha256"],
        "arm_id": arm["arm_id"],
        "comparison_id": registration.document["comparison_id"],
        "resource_envelope": definition.document["resource_envelope"],
        "controller_source_sha256": lifecycle["controller_source_sha256"],
        "controller_source_bundle_sha256": hashlib.sha256(
            canonical_json(lifecycle["controller_source_sha256"])
        ).hexdigest(),
        "paid_api_allowed": False,
        "production_change_authorized": False,
    }
    if any(window.get(key) != value for key, value in expected_window.items()):
        _fail("lifecycle window plan differs from the preregistration")
    worker_argv = [
        window["launcher_python_path"],
        "-m",
        "bench.stable_benchmark.supervised_window",
        "--worker",
        "--window-id",
        lifecycle["window_id"],
        "--run-manifest",
        arm["manifest"]["path"],
    ]
    worker_argv_sha = hashlib.sha256(canonical_json(worker_argv)).hexdigest()
    if worker_argv_sha != lifecycle["worker_argv_sha256"]:
        _fail("registered worker argv digest differs from the window plan")
    source_files_verified = _verify_source_tree(
        window, arm, allowed_code_roots=allowed_code_roots
    )

    process, _ = _read_document(lifecycle_dir / "process.json", limit=2_000_000)
    _exact_fields(process, PROCESS_FIELDS, "lifecycle process receipt")
    if (
        process.get("schema_version") != PROCESS_SCHEMA
        or process.get("window_id") != lifecycle["window_id"]
        or process.get("plan_sha256") != window_sha
        or process.get("argv_sha256") != lifecycle["worker_argv_sha256"]
    ):
        _fail("lifecycle process receipt differs from the window plan")

    state, _ = _read_document(lifecycle_dir / "state.json", limit=4_000_000)
    if (
        state.get("schema_version") != STATE_SCHEMA
        or state.get("window_id") != lifecycle["window_id"]
        or state.get("plan_sha256") != window_sha
        or state.get("definition_sha256") != definition.raw_sha256
        or state.get("run_manifest_sha256") != arm["manifest"]["sha256"]
        or state.get("phase") != "complete"
        or state.get("result_status") != "complete"
        or state.get("execution_gate_sha256") != run.get("execution_gate_sha256")
        or state.get("restoration", {}).get("status") != "verified"
    ):
        _fail("terminal lifecycle state does not bind a complete restored run")

    result, result_sha = _read_document(lifecycle_dir / "result.json")
    _exact_fields(result, RESULT_FIELDS, "lifecycle result")
    expected_result = {
        "schema_version": RESULT_SCHEMA,
        "window_id": lifecycle["window_id"],
        "status": "complete",
        "plan_sha256": window_sha,
        "definition_sha256": definition.raw_sha256,
        "run_manifest_sha256": arm["manifest"]["sha256"],
        "run_receipt_sha256": run_sha,
        "execution_gate_sha256": run["execution_gate_sha256"],
        "monitor_end_passed": True,
        "no_guard_breach": True,
        "restoration_passed": True,
        "error": None,
        "failure_stage": None,
        "paid_api_calls": 0,
        "production_change_authorized": False,
    }
    if any(result.get(key) != value for key, value in expected_result.items()):
        _fail("lifecycle result is not a complete admitted execution")
    restoration = result.get("restoration")
    if (
        not isinstance(restoration, dict)
        or restoration.get("status") != "verified"
        or restoration.get("errors") != []
        or restoration.get("sentinel_retained") is not False
        or isinstance(result.get("memory_samples"), bool)
        or not isinstance(result.get("memory_samples"), int)
        or result["memory_samples"] <= 0
        or type(result.get("min_mem_available_gib")) not in {int, float}
        or not math.isfinite(result["min_mem_available_gib"])
        or result["min_mem_available_gib"] < window["monitor_min_mem_available_gib"]
    ):
        _fail("lifecycle restoration or resource-monitor result differs")
    memory_log, memory_log_sha = _safe_read(
        lifecycle_dir / "resident-memory.jsonl", limit=MAX_MEMORY_LOG_BYTES
    )
    if (
        memory_log_sha != _digest(
            result.get("memory_log_sha256"), "result.memory_log_sha256"
        )
        or not memory_log.endswith(b"\n")
        or memory_log.count(b"\n") != result["memory_samples"]
    ):
        _fail("resource-monitor log digest or sample count differs")

    supervision, _ = _read_document(lifecycle_dir / "supervision.json", limit=2_000_000)
    _exact_fields(supervision, SUPERVISION_FIELDS, "parent supervision receipt")
    expected_supervision = {
        "schema_version": SUPERVISION_SCHEMA,
        "window_id": lifecycle["window_id"],
        "plan_sha256": window_sha,
        "command_sha256": lifecycle["worker_argv_sha256"],
        "argv": worker_argv,
        "returncode": 0,
        "complete": True,
        "terminated_at_work_cutoff": False,
        "force_killed": False,
        "emergency_recovery": None,
        "lifecycle_result_sha256": result_sha,
        "replay_terminal_status": "verified",
        "admission_status": "admitted",
        "finalization_error": None,
    }
    if any(supervision.get(key) != value for key, value in expected_supervision.items()):
        _fail("parent supervision receipt is not a complete admitted lifecycle")

    gate, gate_sha = _read_document(run_directory / "execution-gate.snapshot.json", limit=2_000_000)
    _exact_fields(gate, GATE_FIELDS, "execution gate")
    expected_gate = {
        "admitted": True,
        "definition_sha256": definition.raw_sha256,
        "run_manifest_sha256": arm["manifest"]["sha256"],
        "route_runtime_identities": {
            route_id: route["runtime_identity"]
            for route_id, route in manifest["arm"]["routes"].items()
        },
    }
    if any(gate.get(key) != value for key, value in expected_gate.items()):
        _fail("execution gate differs from the registered manifests and routes")
    if gate_sha != run.get("execution_gate_sha256"):
        _fail("execution gate digest differs from the run receipt")

    receipt_specs = (
        ("endpoint-bindings.json", "endpoint_bindings_sha256", ENDPOINT_BINDINGS_SCHEMA, ENDPOINT_FIELDS),
        ("supervision-ready.json", "supervision_receipt_sha256", SUPERVISION_READY_SCHEMA, READY_FIELDS),
        ("resource-guard.json", "resource_guard_sha256", RESOURCE_GUARD_SCHEMA, RESOURCE_FIELDS),
    )
    gate_receipts: dict[str, dict[str, Any]] = {}
    for filename, gate_key, schema, fields in receipt_specs:
        lifecycle_document, lifecycle_sha = _read_document(lifecycle_dir / filename, limit=2_000_000)
        run_document, run_copy_sha = _read_document(run_directory / filename, limit=2_000_000)
        _exact_fields(lifecycle_document, fields, filename)
        if lifecycle_document != run_document or lifecycle_sha != run_copy_sha:
            _fail(f"run and lifecycle copies differ for {filename}")
        if lifecycle_document.get("schema_version") != schema:
            _fail(f"{filename} schema differs")
        if lifecycle_sha != gate.get(gate_key):
            _fail(f"{filename} digest differs from the execution gate")
        if lifecycle_document.get("window_id") != lifecycle["window_id"]:
            _fail(f"{filename} binds a different lifecycle window")
        gate_receipts[filename] = lifecycle_document

    endpoint = gate_receipts["endpoint-bindings.json"]
    if (
        endpoint.get("definition_sha256") != definition.raw_sha256
        or endpoint.get("run_manifest_sha256") != arm["manifest"]["sha256"]
        or endpoint.get("raw_ports_exposed") is not False
    ):
        _fail("endpoint receipt differs from the registered manifests")
    _validate_endpoint_routes(endpoint, manifest)
    ready = gate_receipts["supervision-ready.json"]
    if (
        ready.get("plan_sha256") != window_sha
        or ready.get("definition_sha256") != definition.raw_sha256
        or ready.get("run_manifest_sha256") != arm["manifest"]["sha256"]
        or ready.get("controller_source_sha256") != lifecycle["controller_source_sha256"]
        or ready.get("endpoint_bindings_sha256") != gate["endpoint_bindings_sha256"]
        or ready.get("resident_qualification") != window["resident_qualification"]
    ):
        _fail("supervision-ready receipt differs from the preregistered plan")
    guard = gate_receipts["resource-guard.json"]
    if (
        guard.get("monitor_phase") != "evaluation"
        or guard.get("minimum_mem_available_gib") != window["monitor_min_mem_available_gib"]
        or guard.get("maximum_sample_gap_seconds") != window["monitor_max_sample_gap_seconds"]
        or guard.get("checks") != "before_and_after_every_model_request_plus_background_sampling"
    ):
        _fail("resource guard differs from the registered lifecycle policy")

    worker_pid = _positive_int(process.get("pid"), "process.pid")
    _positive_int(process.get("pgid"), "process.pgid")
    worker_ticks = _positive_int(
        process.get("worker_start_ticks"), "process.worker_start_ticks"
    )
    boot_id = process.get("boot_id")
    if not isinstance(boot_id, str) or not boot_id or len(boot_id) > 128:
        _fail("process.boot_id must be bounded nonempty text")
    worker_identity = (worker_pid, worker_ticks, boot_id)
    for where, document, pid_key in (
        ("terminal state", state, "worker_pid"),
        ("supervision-ready", ready, "worker_pid"),
        ("parent supervision", supervision, "pid"),
    ):
        observed = (
            _positive_int(document.get(pid_key), f"{where}.{pid_key}"),
            _positive_int(
                document.get("worker_start_ticks"), f"{where}.worker_start_ticks"
            ),
            document.get("boot_id"),
        )
        if observed != worker_identity:
            _fail(f"{where} binds a different worker process identity")

    registered_at = _registration_time(registration)
    process_started = _timestamp(process.get("started_at"), "process.started_at")
    supervision_started = _timestamp(
        supervision.get("started_at"), "supervision.started_at"
    )
    hard_deadline = _timestamp(
        supervision.get("hard_deadline_at"), "supervision.hard_deadline_at"
    )
    expected_deadline = supervision_started + timedelta(
        seconds=window["window_deadline_seconds"]
    )
    if process_started != supervision_started or hard_deadline != expected_deadline:
        _fail("parent supervision timing differs from its worker process or window deadline")
    elapsed_seconds = supervision.get("elapsed_seconds")
    if (
        type(elapsed_seconds) not in {int, float}
        or not math.isfinite(elapsed_seconds)
        or elapsed_seconds < 0
        or elapsed_seconds > window["window_deadline_seconds"]
    ):
        _fail("parent supervision elapsed time differs from the window deadline")
    timeline = {
        "registered": registered_at,
        "process_started": process_started,
        "state_started": _timestamp(state.get("started_at"), "state.started_at"),
        "endpoint_frozen": _timestamp(endpoint.get("frozen_at"), "endpoint.frozen_at"),
        "supervision_ready": _timestamp(ready.get("ready_at"), "ready.ready_at"),
        "resource_guard_armed": _timestamp(guard.get("armed_at"), "guard.armed_at"),
        "run_started": _timestamp(run.get("started_at"), "run.started_at"),
        "run_finished": _timestamp(run.get("finished_at"), "run.finished_at"),
        "result_finished": _timestamp(result.get("finished_at"), "result.finished_at"),
        "supervision_finished": _timestamp(
            supervision.get("finished_at"), "supervision.finished_at"
        ),
        "hard_deadline": hard_deadline,
    }
    ordered = (
        "registered", "process_started", "state_started", "endpoint_frozen",
        "supervision_ready", "resource_guard_armed", "run_started",
        "run_finished", "result_finished",
    )
    if any(
        timeline[left] > timeline[right]
        for left, right in zip(ordered, ordered[1:])
    ):
        _fail("lifecycle timestamps are out of execution order")
    if (
        timeline["result_finished"] > timeline["supervision_finished"]
        or timeline["supervision_finished"] > hard_deadline
    ):
        _fail("terminal lifecycle timestamps exceed supervision bounds")
    return (
        window, window_sha, gate, gate_sha, result, result_sha,
        source_files_verified, timeline,
    )


def _validate_terminal_timeline(
    timeline: dict[str, datetime],
    replay: dict[str, Any],
    supervisor: dict[str, Any],
    admission: dict[str, Any],
) -> None:
    terminal = (
        ("result", timeline["result_finished"]),
        ("replay", _timestamp(replay.get("generated_at"), "replay.generated_at")),
        (
            "supervisor-final",
            _timestamp(supervisor.get("finished_at"), "supervisor-final.finished_at"),
        ),
        (
            "admission",
            _timestamp(admission.get("generated_at"), "admission.generated_at"),
        ),
        ("supervision", timeline["supervision_finished"]),
    )
    if any(left[1] > right[1] for left, right in zip(terminal, terminal[1:])):
        _fail("terminal receipt timestamps are out of finalization order")
    if any(
        stamp < timeline["registered"] or stamp > timeline["hard_deadline"]
        for _, stamp in terminal
    ):
        _fail("terminal receipt timestamp falls outside the registered lifecycle")


def verify_registered_arm(
    registration: LoadedRegistration,
    arm_id: str,
    *,
    definition: LoadedDocument,
    allowed_code_roots: Iterable[Path | str] = (),
) -> VerifiedArm:
    """Verify one arm without reading private responses or running a grader."""
    validate_registration(registration.document, definition)
    arm = _arm_entry(registration, arm_id)
    registered_definition, definition_sha = _check_file_binding(
        registration.document["definition"], "definition"
    )
    if definition_sha != definition.raw_sha256 or registered_definition != definition.document:
        _fail("registered definition file differs from the loaded definition")
    manifest, manifest_sha = _check_file_binding(arm["manifest"], "run manifest")
    _validate_manifest(
        manifest,
        manifest_sha=manifest_sha,
        registration=registration,
        arm=arm,
        definition=definition,
    )
    run_directory = Path(arm["run_receipt_directory"])
    if run_directory.resolve(strict=True) != run_directory.absolute() or not run_directory.is_dir():
        _fail("run receipt directory is absent or redirected")
    _check_snapshot(
        run_directory / "definition.snapshot.json", definition.raw_sha256, "definition"
    )
    _check_snapshot(
        run_directory / "run-manifest.snapshot.json", manifest_sha, "run manifest"
    )
    run, run_sha = _read_document(run_directory / "run.json")
    _validate_run_common(
        run,
        registration=registration,
        arm=arm,
        definition=definition,
    )
    if arm["lifecycle"] is None:
        _validate_unissued(run_directory, run, definition)
        return VerifiedArm(
            comparison_id=registration.document["comparison_id"],
            arm_id=arm_id,
            role=arm["role"],
            terminal_status="unissued",
            admission_status="withheld_unissued",
            admitted=False,
            manifest=manifest,
            manifest_sha256=manifest_sha,
            run=run,
            run_sha256=run_sha,
            replay=None,
            replay_sha256=None,
            admission=None,
            admission_sha256=None,
            lifecycle_plan=None,
            lifecycle_plan_sha256=None,
            source_files_verified=False,
            resource_evidence_level=None,
        )
    if run.get("terminal_status") != "complete":
        _fail("an executed registered arm is not terminal complete")
    (
        window, window_sha, gate, gate_sha, result, result_sha,
        source_verified, timeline,
    ) = _validate_lifecycle(
        registration,
        arm,
        definition,
        manifest,
        run,
        run_sha,
        run_directory,
        allowed_code_roots=allowed_code_roots,
    )

    replay, replay_sha = _read_document(run_directory / "replay.json")
    _exact_fields(replay, REPLAY_FIELDS, "replay receipt")
    replay_expected = {
        "schema_version": REPLAY_SCHEMA,
        "terminal_status": "verified",
        "verified": True,
        "arm_id": arm_id,
        "comparison_id": registration.document["comparison_id"],
        "run_receipt_sha256": run_sha,
        "definition_sha256": definition.raw_sha256,
        "run_manifest_sha256": manifest_sha,
        "replay_source_sha256": arm["replay_source_sha256"],
        "mismatches": [],
        "admission_authorized": False,
    }
    if any(replay.get(key) != value for key, value in replay_expected.items()):
        _fail("replay receipt differs from the preregistered verified chain")
    task_ids = [task["id"] for task in definition.document["tasks"]]
    replay_outcomes = replay.get("outcomes")
    if (
        not isinstance(replay_outcomes, list)
        or [row.get("task_id") if isinstance(row, dict) else None for row in replay_outcomes] != task_ids
        or any(row.get("verified") is not True for row in replay_outcomes)
    ):
        _fail("replay receipt does not verify the exact ordered task set")

    supervisor, supervisor_sha = _read_document(run_directory / "supervisor-final.json", limit=2_000_000)
    _exact_fields(supervisor, SUPERVISOR_FINAL_FIELDS, "supervisor-final receipt")
    supervisor_expected = {
        "schema_version": SUPERVISOR_FINAL_SCHEMA,
        "terminal_status": "complete",
        "definition_sha256": definition.raw_sha256,
        "run_manifest_sha256": manifest_sha,
        "run_receipt_sha256": run_sha,
        "replay_receipt_sha256": replay_sha,
        "execution_gate_sha256": gate_sha,
        "monitor_end_passed": True,
        "no_guard_breach": True,
        "restoration_passed": True,
        "controller_source_sha256": arm["lifecycle"]["controller_source_sha256"],
    }
    if any(supervisor.get(key) != value for key, value in supervisor_expected.items()):
        _fail("supervisor-final receipt differs from the registered lifecycle")

    admission, admission_sha = _read_document(run_directory / "admission.json", limit=2_000_000)
    _exact_fields(admission, ADMISSION_FIELDS, "admission receipt")
    admission_expected = {
        "schema_version": ADMISSION_SCHEMA,
        "admission_status": "admitted",
        "admitted": True,
        "reasons": [],
        "definition_sha256": definition.raw_sha256,
        "run_manifest_sha256": manifest_sha,
        "run_receipt_sha256": run_sha,
        "replay_receipt_sha256": replay_sha,
        "supervisor_final_receipt_sha256": supervisor_sha,
        "admission_source_sha256": arm["admission_source_sha256"],
        "arm_id": arm_id,
        "comparison_id": registration.document["comparison_id"],
        "promotion_authorized": False,
    }
    if any(admission.get(key) != value for key, value in admission_expected.items()):
        _fail("admission receipt differs from the preregistered chain")
    _validate_terminal_timeline(timeline, replay, supervisor, admission)
    return VerifiedArm(
        comparison_id=registration.document["comparison_id"],
        arm_id=arm_id,
        role=arm["role"],
        terminal_status=run["terminal_status"],
        admission_status=admission["admission_status"],
        admitted=True,
        manifest=manifest,
        manifest_sha256=manifest_sha,
        run=run,
        run_sha256=run_sha,
        replay=replay,
        replay_sha256=replay_sha,
        admission=admission,
        admission_sha256=admission_sha,
        lifecycle_plan=window,
        lifecycle_plan_sha256=window_sha,
        source_files_verified=source_verified,
        resource_evidence_level=(
            "source_bound_supervisor_attestation_with_bounded_monitor_log_digest"
        ),
    )


def verify_registered_comparison(
    registration: LoadedRegistration,
    *,
    definition: LoadedDocument,
    allowed_code_roots: Iterable[Path | str] = (),
) -> tuple[VerifiedArm, VerifiedArm]:
    """Verify both arms in their preregistered reference/candidate order."""
    arms = tuple(
        verify_registered_arm(
            registration,
            arm["arm_id"],
            definition=definition,
            allowed_code_roots=allowed_code_roots,
        )
        for arm in registration.document["arms"]
    )
    return arms  # type: ignore[return-value]


__all__ = [
    "LoadedRegistration",
    "ReceiptVerificationError",
    "VerifiedArm",
    "load_registration",
    "validate_registration",
    "verify_registered_arm",
    "verify_registered_comparison",
]
