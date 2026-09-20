"""Versioned payoff/tool diagnostic for the already-running Flash service.

The module never starts, stops, or reconfigures a model service.  It freezes a
plan, runs the old payoff/tool fixtures against the registered warm Flash
endpoint, and independently replays the private raw SSE evidence.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import re
import signal
import stat
import threading
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_wrapper.deployment import load_model_deployment
from bench.flash_next_ab import harness, private_evidence, transport
from bench.payoff_tool_study import runner as legacy
from orchestrator import flash_resident
from orchestrator.weekly_upgrade_trial import resource_lease

CODE_ROOT = Path(__file__).resolve().parents[2]
CANONICAL_ROOT = Path("/home/decross1/projects/a_bgt_rsi")
ARTIFACT_ROOT = Path(
    "/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-20/"
    "flash-payoff-diagnostic"
)
PLAN_SCHEMA = "flash-payoff-diagnostic-plan/v1"
RUN_SCHEMA = "flash-payoff-diagnostic-run/v1"
VALIDATION_SCHEMA = "flash-payoff-diagnostic-validation/v1"
PRIVATE_SCHEMA = "flash-payoff-diagnostic-private-call/v1"
POLICY_ID = "payoff_deterministic_no_thinking"
POLICY = copy.deepcopy(legacy.POLICY)
MAX_TOKENS = 256
CALL_TIMEOUT_S = 90.0
EVALUATOR_BUDGET_S = 900.0
MEMORY_FLOOR_GIB = 20.0
DECLARED_CONDITIONS = 12
DECLARED_SLOTS = 18
MODEL_REVISION = "fc694b54fb0174e0913e6adf86691ef85a4ead47"
RUNTIME_IMAGE_ID = "sha256:2ee545cf877ae8497c123637e061b6e6313c624e30018f975969b1d554e27f56"
SERVING_PROFILE_SHA256 = "2d84e1dc107a48b9ef5967ebd4c7a9c288ec54ac6d5e8ae8d0d973fe82e1c84b"
CLAIM_LIMIT = (
    "arithmetic and native tool-interface diagnostic only; no L2, strategy, "
    "production, or model-upgrade claim"
)
RESEARCH_CONTEXT = {
    "source_iteration_id": "iter-2026-09-15-007",
    "source_campaign": "v2-utility-mechanism-followon-20260915",
    "relationship": "motivation_only",
    "claim_binding": False,
    "diagnostic_stage": "preparatory_interface_diagnostic",
}
ENDPOINT = transport.LocalEndpoint(
    "flash_next_sglang",
    "http://127.0.0.1:30080/v1",
    "nvidia/Qwen3.8-Flash-Next-NVFP4",
    transport.NVIDIA_ARTIFACT_SHA256,
)
SOURCE_PATHS = (
    "experiments/payoff_tool_arithmetic/flash_resident.py",
    "experiments/payoff_tool_arithmetic/FLASH_PREREGISTRATION.md",
    "bench/payoff_tool_study/runner.py",
    "bench/agentic_game_theory/calibration.py",
    "bench/flash_next_ab/adapters.py",
    "bench/flash_next_ab/harness.py",
    "bench/flash_next_ab/transport.py",
    "bench/flash_next_ab/private_evidence.py",
    "bench/flash_next_ab/manifest.py",
    "bench/flash_next_ab/qualification.py",
    "agent_wrapper/deployment.py",
    "orchestrator/flash_resident.py",
    "orchestrator/weekly_upgrade_trial.py",
)


class FlashPayoffError(ValueError):
    """A frozen diagnostic contract or evidence bundle is invalid."""


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise FlashPayoffError(reason)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def _digest(value: Any, *, length: int = 64) -> bool:
    return (
        isinstance(value, str)
        and len(value) == length
        and all(character in "0123456789abcdef" for character in value)
    )


def _source_hashes() -> dict[str, str]:
    return {relative: _sha((CODE_ROOT / relative).read_bytes()) for relative in SOURCE_PATHS}


def _inside_git_checkout(path: Path) -> bool:
    candidate = path.resolve(strict=False)
    for parent in (candidate, *candidate.parents):
        marker = parent / ".git"
        if marker.is_file():
            return True
        if marker.is_dir() and (
            (marker / "HEAD").is_file() or (marker / "config").is_file()
        ):
            return True
    return False


def _artifact_path(path: Path, root: Path, *, label: str) -> Path:
    resolved = path.resolve(strict=False)
    artifact_root = root.resolve(strict=False)
    _require(
        artifact_root.is_absolute()
        and resolved != artifact_root
        and resolved.is_relative_to(artifact_root),
        f"{label} must be a child of the plan-bound private artifact root",
    )
    _require(
        not _inside_git_checkout(artifact_root)
        and not _inside_git_checkout(resolved),
        f"{label} must be outside every Git checkout",
    )
    return resolved


def _read_object(path: Path, *, label: str, ceiling: int = 1_000_000) -> tuple[dict[str, Any], bytes]:
    try:
        info = path.lstat()
    except OSError as exc:
        raise FlashPayoffError(f"{label} is unavailable") from exc
    _require(stat.S_ISREG(info.st_mode) and not path.is_symlink(), f"{label} is not a regular file")
    _require(0 < info.st_size <= ceiling, f"{label} has an invalid size")
    raw = path.read_bytes()
    _require(len(raw) == info.st_size, f"{label} changed while being read")
    try:
        value = harness._strict_object(raw, label)
    except (UnicodeDecodeError, json.JSONDecodeError, harness.HarnessError) as exc:
        raise FlashPayoffError(f"{label} is not strict JSON") from exc
    return value, raw


def _live_runtime_binding(root: Path = CANONICAL_ROOT) -> dict[str, Any]:
    """Capture static deployment identity plus this live supervisor/container."""
    deployment_path = root / "config/model_deployment.json"
    deployment = load_model_deployment(deployment_path)
    _require(deployment is not None, "Flash deployment is missing")
    ENDPOINT.validate()
    _require(
        deployment.model == ENDPOINT.served_model
        and deployment.base_url == ENDPOINT.base_url
        and deployment.model_revision == MODEL_REVISION
        and deployment.image_id == RUNTIME_IMAGE_ID
        and deployment.profile_sha256 == SERVING_PROFILE_SHA256,
        "deployed Flash model, endpoint, or runtime image differs",
    )
    state, _state_raw = _read_object(
        root / "run_state/flash_resident.json", label="Flash resident state"
    )
    boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    _require(
        state.get("phase") == "ready"
        and state.get("boot_id") == boot_id
        and state.get("model") == ENDPOINT.served_model
        and state.get("backend") == deployment.backend
        and state.get("endpoint") == ENDPOINT.base_url
        and state.get("image_id") == deployment.image_id,
        "live Flash identity differs from the selected deployment",
    )
    pid = state.get("pid")
    start_ticks = state.get("process_start_ticks")
    _require(type(pid) is int and pid > 0 and type(start_ticks) is int and start_ticks > 0,
             "Flash supervisor process identity is malformed")
    try:
        observed_ticks = int(
            Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
        )
    except (OSError, ValueError, IndexError) as exc:
        raise FlashPayoffError(
            "Flash supervisor process cannot be verified in this PID namespace; "
            "prepare/run must execute in host context"
        ) from exc
    _require(observed_ticks == start_ticks, "Flash supervisor process identity changed")
    live_keys = (
        "boot_id", "pid", "process_start_ticks", "guard_pid", "guard_start_ticks",
        "container_id", "image_id", "artifact_dir",
    )
    live = {key: state.get(key) for key in live_keys}
    _require(_digest(live["container_id"]), "Flash container identity is malformed")
    return {
        "endpoint": {
            "name": ENDPOINT.name,
            "base_url": ENDPOINT.base_url,
            "served_model": ENDPOINT.served_model,
            "checkpoint_artifact_sha256": ENDPOINT.artifact_sha256,
        },
        "checkpoint": {
            "model_revision": deployment.model_revision,
            "artifact_sha256": ENDPOINT.artifact_sha256,
        },
        "runtime": {
            "backend": deployment.backend,
            "image_id": deployment.image_id,
            "profile_sha256": deployment.profile_sha256,
            "context_length": deployment.context_length,
            "max_running_requests": deployment.max_running_requests,
            "host_reserve_gib": deployment.host_reserve_gib,
        },
        "deployment": {
            "path": str(deployment_path),
            "config_sha256": deployment.config_sha256,
            "selected_at": deployment.selected_at,
        },
        "live": live,
        # The supervisor rewrites heartbeat fields every ten seconds.  Bind
        # the stable process/container identity rather than the mutable file.
        "live_identity_sha256": _sha(_canonical(live)),
    }


def _validate_runtime_binding(binding: Any) -> None:
    _require(isinstance(binding, dict), "runtime binding is missing")
    _require(
        set(binding) == {
            "endpoint", "checkpoint", "runtime", "deployment", "live",
            "live_identity_sha256",
        },
        "runtime binding shape differs",
    )
    endpoint = binding.get("endpoint")
    checkpoint = binding.get("checkpoint")
    runtime = binding.get("runtime")
    deployment = binding.get("deployment")
    live = binding.get("live")
    _require(
        endpoint == {
            "name": ENDPOINT.name,
            "base_url": ENDPOINT.base_url,
            "served_model": ENDPOINT.served_model,
            "checkpoint_artifact_sha256": ENDPOINT.artifact_sha256,
        },
        "runtime endpoint binding differs",
    )
    _require(
        isinstance(checkpoint, dict)
        and set(checkpoint) == {"model_revision", "artifact_sha256"}
        and checkpoint.get("model_revision") == MODEL_REVISION
        and checkpoint.get("artifact_sha256") == ENDPOINT.artifact_sha256,
        "checkpoint binding is malformed",
    )
    _require(
        isinstance(runtime, dict)
        and set(runtime) == {
            "backend", "image_id", "profile_sha256", "context_length",
            "max_running_requests", "host_reserve_gib",
        }
        and runtime.get("backend") == "sglang-flash"
        and runtime.get("image_id") == RUNTIME_IMAGE_ID
        and runtime.get("profile_sha256") == SERVING_PROFILE_SHA256
        and runtime.get("context_length") == 32768
        and runtime.get("max_running_requests") == 1
        and runtime.get("host_reserve_gib") == 20,
        "runtime image/profile binding is malformed",
    )
    _require(
        isinstance(deployment, dict)
        and set(deployment) == {"path", "config_sha256", "selected_at"}
        and deployment.get("path") == str(CANONICAL_ROOT / "config/model_deployment.json")
        and _digest(deployment.get("config_sha256"))
        and isinstance(deployment.get("selected_at"), str),
        "deployment binding is malformed",
    )
    _require(
        isinstance(live, dict)
        and set(live) == {
            "boot_id", "pid", "process_start_ticks", "guard_pid",
            "guard_start_ticks", "container_id", "image_id", "artifact_dir",
        }
        and isinstance(live.get("boot_id"), str)
        and re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            live["boot_id"],
        ) is not None
        and type(live.get("pid")) is int
        and live["pid"] > 0
        and type(live.get("process_start_ticks")) is int
        and live["process_start_ticks"] > 0
        and type(live.get("guard_pid")) is int
        and live["guard_pid"] > 0
        and type(live.get("guard_start_ticks")) is int
        and live["guard_start_ticks"] > 0
        and _digest(live.get("container_id"))
        and live.get("image_id") == runtime.get("image_id")
        and isinstance(live.get("artifact_dir"), str)
        and Path(live["artifact_dir"]).is_absolute()
        and binding.get("live_identity_sha256") == _sha(_canonical(live)),
        "live Flash identity binding is malformed",
    )


def _ready(root: Path = CANONICAL_ROOT) -> bool:
    return flash_resident.selected(root) and flash_resident.check_ready(root)


def _available_gib() -> float:
    return flash_resident.mem_available_gib()


def _endpoint_idle_probe() -> dict[str, Any]:
    """One-shot SGLang queue observation; direct HTTP clients can bypass locks."""
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), flash_resident.NoRedirect()
    )
    try:
        with opener.open("http://127.0.0.1:30080/metrics", timeout=3) as response:
            raw = response.read(2_000_001)
            status = response.status
    except OSError as exc:
        raise FlashPayoffError("Flash idle metrics are unavailable") from exc
    _require(status == 200 and len(raw) <= 2_000_000, "Flash idle metrics response differs")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise FlashPayoffError("Flash idle metrics are not UTF-8") from exc
    values: dict[str, float] = {}
    for metric in ("sglang:num_running_reqs", "sglang:num_queue_reqs"):
        try:
            rows = [
                float(line.split()[-1])
                for line in text.splitlines()
                if line.startswith((metric + "{", metric + " "))
            ]
        except (ValueError, IndexError) as exc:
            raise FlashPayoffError("Flash idle queue gauge is malformed") from exc
        _require(
            bool(rows) and all(math.isfinite(value) and value >= 0 for value in rows),
            "Flash idle queue gauge is absent or invalid",
        )
        values[metric] = sum(rows)
    return {
        "schema_version": "flash-payoff-idle-probe/v1",
        "endpoint_name": ENDPOINT.name,
        "running_requests": values["sglang:num_running_reqs"],
        "waiting_requests": values["sglang:num_queue_reqs"],
        "metrics_sha256": _sha(raw),
        "metrics_bytes": len(raw),
        "observed_idle": not any(values.values()),
        "cooperative_exclusion_only": True,
        "direct_http_clients_excluded": False,
        "isolated_latency_claim": False,
    }


def _validate_idle_observation(value: Any) -> None:
    _require(
        isinstance(value, dict)
        and set(value) == {
            "schema_version", "endpoint_name", "running_requests",
            "waiting_requests", "metrics_sha256", "metrics_bytes",
            "observed_idle", "cooperative_exclusion_only",
            "direct_http_clients_excluded", "isolated_latency_claim",
        }
        and value.get("schema_version") == "flash-payoff-idle-probe/v1"
        and value.get("endpoint_name") == ENDPOINT.name
        and type(value.get("running_requests")) in {int, float}
        and math.isfinite(float(value["running_requests"]))
        and float(value["running_requests"]) >= 0
        and type(value.get("waiting_requests")) in {int, float}
        and math.isfinite(float(value["waiting_requests"]))
        and float(value["waiting_requests"]) >= 0
        and _digest(value.get("metrics_sha256"))
        and type(value.get("metrics_bytes")) is int
        and 0 < value["metrics_bytes"] <= 2_000_000
        and type(value.get("observed_idle")) is bool
        and value["observed_idle"]
        == (not value["running_requests"] and not value["waiting_requests"])
        and value.get("cooperative_exclusion_only") is True
        and value.get("direct_http_clients_excluded") is False
        and value.get("isolated_latency_claim") is False,
        "Flash endpoint contention observation is malformed",
    )


def make_plan(
    plan_path: str | Path,
    *,
    diagnostic_id: str,
    artifact_root: str | Path = ARTIFACT_ROOT,
    runtime_snapshot_fn: Callable[[], dict[str, Any]] | None = None,
    ready_fn: Callable[[], bool] | None = None,
    memory_fn: Callable[[], float] | None = None,
) -> dict[str, Any]:
    """Freeze a fresh exact-runtime plan without issuing a model request."""
    _require(
        re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}", diagnostic_id) is not None,
        "diagnostic ID is malformed",
    )
    snapshot = runtime_snapshot_fn or _live_runtime_binding
    is_ready = ready_fn or _ready
    available = memory_fn or _available_gib
    runtime_binding = snapshot()
    _validate_runtime_binding(runtime_binding)
    _require(is_ready(), "permanent Flash is not ready")
    _require(float(available()) >= MEMORY_FLOOR_GIB, "20 GiB memory floor is unavailable")
    fixtures = copy.deepcopy(legacy._fixtures())
    private_root = Path(artifact_root).resolve(strict=False)
    path = _artifact_path(Path(plan_path), private_root, label="diagnostic plan")
    plan = {
        "schema_version": PLAN_SCHEMA,
        "diagnostic_id": diagnostic_id,
        "code_root": str(CODE_ROOT),
        "runtime_binding": runtime_binding,
        "source_sha256": _source_hashes(),
        "fixtures": fixtures,
        "fixture_bundle_sha256": _sha(_canonical(fixtures)),
        "declared_pairs": [fixture["pair_id"] for fixture in fixtures],
        "declared_conditions": [
            f"{fixture['pair_id']}/{arm}"
            for fixture in fixtures
            for arm in fixture["arm_order"]
        ],
        "declared_slots": legacy._slots(fixtures),
        "policy_id": POLICY_ID,
        "policy": copy.deepcopy(POLICY),
        "tool_spec": copy.deepcopy(legacy.TOOL_SPEC),
        "limits": {
            "max_tokens": MAX_TOKENS,
            "call_timeout_s": CALL_TIMEOUT_S,
            "evaluator_budget_s": EVALUATOR_BUDGET_S,
            "memory_floor_gib": MEMORY_FLOOR_GIB,
            "max_calls": DECLARED_SLOTS,
        },
        "coordination": {
            "locks": [
                str(CANONICAL_ROOT / "run_state/.weekly-upgrade-execution.lock"),
                str(CANONICAL_ROOT / "run_state/.coordinator-cron.lock"),
                str(CANONICAL_ROOT / "run_state/.weekly-upgrade-gpu.lock"),
            ],
            "mode": "exclusive_nonblocking_once",
            "serving_lifetime_lease_acquired": False,
            "cooperative_exclusion_only": True,
            "direct_http_clients_excluded": False,
            "isolated_latency_claim": False,
        },
        "budget": {
            "weekly_two_hour_debit": False,
            "authorization": "owner-authorized-current-local-research-session",
        },
        "artifact_policy": {
            "private_root": str(private_root),
            "outside_git_required": True,
            "directory_mode": "0700",
        },
        "research_context": copy.deepcopy(RESEARCH_CONTEXT),
        "claim_limit": CLAIM_LIMIT,
        "promotion_authorized": False,
    }
    _require(len(fixtures) == 6, "fixture pair denominator drift")
    _require(len(plan["declared_conditions"]) == DECLARED_CONDITIONS, "condition denominator drift")
    _require(len(plan["declared_slots"]) == DECLARED_SLOTS, "slot denominator drift")
    private_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    private_root.chmod(0o700)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(_canonical(plan) + b"\n")
    return plan


def load_plan(plan_path: str | Path) -> tuple[dict[str, Any], str]:
    path = Path(plan_path)
    plan, raw = _read_object(path, label="Flash payoff diagnostic plan")
    _require(set(plan) == {
        "schema_version", "diagnostic_id", "code_root", "runtime_binding",
        "source_sha256", "fixtures", "fixture_bundle_sha256",
        "declared_pairs", "declared_conditions", "declared_slots",
        "policy_id", "policy", "tool_spec", "limits", "coordination",
        "budget", "artifact_policy", "research_context", "claim_limit",
        "promotion_authorized",
    }, "plan shape differs")
    _require(plan.get("schema_version") == PLAN_SCHEMA, "plan schema differs")
    _require(
        isinstance(plan.get("diagnostic_id"), str)
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}", plan["diagnostic_id"]),
        "diagnostic ID is malformed",
    )
    origin_root = plan.get("code_root")
    _require(
        isinstance(origin_root, str) and Path(origin_root).is_absolute(),
        "plan origin code root is not an absolute provenance path",
    )
    # A byte-identical reviewed worktree may be landed into the canonical
    # checkout before offline replay.  Source hashes, rather than checkout
    # location, are the executable evaluator identity.
    _require(plan.get("source_sha256") == _source_hashes(), "evaluator source drift")
    fixtures = legacy._fixtures()
    _require(plan.get("fixtures") == fixtures, "frozen fixtures drift")
    _require(plan.get("fixture_bundle_sha256") == _sha(_canonical(fixtures)), "fixture digest drift")
    _require(plan.get("declared_pairs") == [f["pair_id"] for f in fixtures], "pair denominator drift")
    expected_conditions = [
        f"{fixture['pair_id']}/{arm}"
        for fixture in fixtures
        for arm in fixture["arm_order"]
    ]
    _require(plan.get("declared_conditions") == expected_conditions, "condition denominator drift")
    _require(plan.get("declared_slots") == legacy._slots(fixtures), "slot denominator drift")
    _require(plan.get("policy_id") == POLICY_ID and plan.get("policy") == POLICY,
             "inference policy drift")
    _require(plan.get("tool_spec") == legacy.TOOL_SPEC, "native tool contract drift")
    _require(plan.get("limits") == {
        "max_tokens": MAX_TOKENS,
        "call_timeout_s": CALL_TIMEOUT_S,
        "evaluator_budget_s": EVALUATOR_BUDGET_S,
        "memory_floor_gib": MEMORY_FLOOR_GIB,
        "max_calls": DECLARED_SLOTS,
    }, "diagnostic limits drift")
    _require(plan.get("coordination") == {
        "locks": [
            str(CANONICAL_ROOT / "run_state/.weekly-upgrade-execution.lock"),
            str(CANONICAL_ROOT / "run_state/.coordinator-cron.lock"),
            str(CANONICAL_ROOT / "run_state/.weekly-upgrade-gpu.lock"),
        ],
        "mode": "exclusive_nonblocking_once",
        "serving_lifetime_lease_acquired": False,
        "cooperative_exclusion_only": True,
        "direct_http_clients_excluded": False,
        "isolated_latency_claim": False,
    }, "coordination contract drift")
    _require(plan.get("budget") == {
        "weekly_two_hour_debit": False,
        "authorization": "owner-authorized-current-local-research-session",
    }, "budget attribution drift")
    artifact_policy = plan.get("artifact_policy")
    _require(
        isinstance(artifact_policy, dict)
        and set(artifact_policy) == {
            "private_root", "outside_git_required", "directory_mode"
        }
        and artifact_policy.get("outside_git_required") is True
        and artifact_policy.get("directory_mode") == "0700"
        and isinstance(artifact_policy.get("private_root"), str)
        and Path(artifact_policy["private_root"]).is_absolute(),
        "private artifact policy differs",
    )
    _artifact_path(path, Path(artifact_policy["private_root"]), label="diagnostic plan")
    _require(plan.get("research_context") == RESEARCH_CONTEXT,
             "research motivation context drift")
    _require(plan.get("claim_limit") == CLAIM_LIMIT and plan.get("promotion_authorized") is False,
             "claim boundary drift")
    _validate_runtime_binding(plan.get("runtime_binding"))
    return plan, _sha(raw)


@dataclass(frozen=True)
class _Call:
    status: str
    dispatch_state: str
    content: str | None
    tool_calls: tuple[dict[str, Any], ...]
    receipt: dict[str, Any]
    descriptor: dict[str, Any]


def _call_status(exc: BaseException) -> tuple[str, str]:
    if isinstance(exc, transport.TransportCancelled):
        return "cancelled", "transport_cancelled"
    if isinstance(exc, TimeoutError):
        return "timeout", "transport_timeout"
    if isinstance(exc, transport.TransportError):
        return "error", "transport_error"
    return "error", "unexpected_transport_error"


def _invoke(
    *,
    output: Path,
    ordinal: int,
    diagnostic_id: str,
    slot_id: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    seed: int,
    cancel_event: Any,
    invoke_fn: Callable[..., dict[str, Any]],
    monotonic: Callable[[], float],
) -> _Call:
    call_id = f"{diagnostic_id}/{slot_id}"
    body = transport.request_body(
        ENDPOINT, messages, POLICY, MAX_TOKENS, seed, tools or None
    )
    request_sha256 = _sha(transport.canonical(body))
    base = {
        "call_index": ordinal,
        "call_id": call_id,
        "role": "arithmetic",
        "endpoint_name": ENDPOINT.name,
        "served_model": ENDPOINT.served_model,
        "artifact_sha256": ENDPOINT.artifact_sha256,
        "policy_id": POLICY_ID,
        "resolved_policy_sha256": _sha(_canonical(POLICY)),
        "seed": seed,
        "max_tokens": MAX_TOKENS,
        "timeout_s": CALL_TIMEOUT_S,
        "messages_sha256": _sha(_canonical(messages)),
        "tools_sha256": _sha(_canonical(tools)),
        "request_sha256": request_sha256,
    }
    started = monotonic()
    private_response = None
    returned = None
    try:
        returned = invoke_fn(
            ENDPOINT,
            copy.deepcopy(messages),
            policy=copy.deepcopy(POLICY),
            max_tokens=MAX_TOKENS,
            timeout_s=CALL_TIMEOUT_S,
            seed=seed,
            tools=copy.deepcopy(tools) or None,
            cancel_event=cancel_event,
        )
        _require(isinstance(returned, dict), "transport result is not an object")
        # Preserve a structurally valid raw stream even when a later public
        # receipt check rejects the transport result.
        private_response = harness._private_response(
            returned.get("private_evidence"), returned=None
        )
        _require(returned.get("request_sha256") == request_sha256, "transport request digest differs")
        _require(returned.get("response_model") == ENDPOINT.served_model, "returned model differs")
        _require(isinstance(returned.get("content"), str), "returned final channel is malformed")
        _require(isinstance(returned.get("reasoning_content"), str), "returned reasoning channel is malformed")
        _require(isinstance(returned.get("tool_calls"), list), "returned tool channel is malformed")
        _require(isinstance(returned.get("finish_reason"), str), "returned finish reason is missing")
        _require(isinstance(returned.get("usage"), dict), "returned usage is missing")
        private_response = harness._private_response(
            returned.get("private_evidence"), returned=returned
        )
        status, dispatch_state = "returned", "confirmed_dispatched"
        failure_code, error = None, None
        receipt = {
            **base,
            "status": status,
            "dispatch_state": dispatch_state,
            "wall_s": max(0.0, monotonic() - started),
            "response_stream_sha256": returned["response_stream_sha256"],
            "response_id": returned["response_id"],
            "response_model": returned["response_model"],
            "finish_reason": returned["finish_reason"],
            "usage": copy.deepcopy(returned["usage"]),
            "failure_code": None,
            "error": None,
        }
        content = returned["content"]
        tool_calls = tuple(copy.deepcopy(returned["tool_calls"]))
    except Exception as exc:  # noqa: BLE001 - failures remain denominator cells
        status, failure_code = _call_status(exc)
        error = f"{type(exc).__name__}: {exc}"
        attached = getattr(exc, "private_evidence", None)
        if attached is not None:
            private_response = harness._private_response(attached, returned=None)
        if private_response is None:
            dispatch_state = "prewire_failure"
        elif private_response["raw_response_stream"]:
            dispatch_state = "confirmed_dispatched"
        elif isinstance(
            exc, (transport.TransportCancelled, TimeoutError, transport.TransportError)
        ):
            dispatch_state = "wire_unknown"
        else:
            dispatch_state = "prewire_failure"
        receipt = {
            **base,
            "status": status,
            "dispatch_state": dispatch_state,
            "wall_s": max(0.0, monotonic() - started),
            "response_stream_sha256": None,
            "response_id": None,
            "response_model": None,
            "finish_reason": None,
            "usage": None,
            "failure_code": failure_code,
            "error": error,
        }
        content = None
        tool_calls = ()
    response = {
        "content": private_response["content"] if private_response else None,
        "reasoning_content": private_response["reasoning_content"] if private_response else None,
        "tool_calls": private_response["tool_calls"] if private_response else [],
        "response_id": private_response["response_id"] if private_response else None,
        "response_model": private_response["response_model"] if private_response else None,
        "finish_reason": private_response["finish_reason"] if private_response else None,
        "usage": private_response["usage"] if private_response else None,
        "response_stream_sha256": (
            private_response["response_stream_sha256"] if private_response else None
        ),
    }
    evidence = {
        "schema_version": PRIVATE_SCHEMA,
        "call_id": call_id,
        "call_index": ordinal,
        "role": "arithmetic",
        "status": status,
        "dispatch_state": dispatch_state,
        "request": {
            "endpoint_name": ENDPOINT.name,
            "served_model": ENDPOINT.served_model,
            "artifact_sha256": ENDPOINT.artifact_sha256,
            "policy_id": POLICY_ID,
            "resolved_policy": copy.deepcopy(POLICY),
            "seed": seed,
            "max_tokens": MAX_TOKENS,
            "timeout_s": CALL_TIMEOUT_S,
            "messages": copy.deepcopy(messages),
            "tools": copy.deepcopy(tools),
            "request_sha256": request_sha256,
        },
        "response": response,
        "failure_code": failure_code,
        "error": error,
        "_raw_response_stream": (
            private_response["raw_response_stream"] if private_response else None
        ),
    }
    descriptor = harness._persist_private_call(output, ordinal=ordinal, evidence=evidence)
    return _Call(status, dispatch_state, content, tool_calls, receipt, descriptor)


def _slot(call: _Call, slot_id: str) -> dict[str, Any]:
    return {
        "slot_id": slot_id,
        "disposition": "returned" if call.status == "returned" else "failed",
        "status": call.status,
        "failure_code": call.receipt["failure_code"],
        "call": call.receipt,
        "private_descriptor": call.descriptor,
    }


def _unissued(slot_id: str, disposition: str, failure_code: str) -> dict[str, Any]:
    _require(disposition in {"skipped_unissued", "unissued_after_abort"}, "invalid unissued disposition")
    return {
        "slot_id": slot_id,
        "disposition": disposition,
        "status": "skipped" if disposition == "skipped_unissued" else "not_run",
        "failure_code": failure_code,
        "call": None,
        "private_descriptor": None,
    }


def _account(slots: list[dict[str, Any]]) -> dict[str, int]:
    counts = {
        "declared_slots": len(slots),
        "attempted_calls": 0,
        "confirmed_dispatched_calls": 0,
        "wire_unknown_attempts": 0,
        "prewire_failures": 0,
        "returned_calls": 0,
        "failed_calls": 0,
        "skipped_unissued": 0,
        "unissued_after_abort": 0,
    }
    for slot in slots:
        disposition = slot["disposition"]
        if disposition in {"returned", "failed"}:
            counts["attempted_calls"] += 1
            counts["returned_calls" if disposition == "returned" else "failed_calls"] += 1
            dispatch_state = slot["call"].get("dispatch_state")
            if dispatch_state == "confirmed_dispatched":
                counts["confirmed_dispatched_calls"] += 1
            elif dispatch_state == "wire_unknown":
                counts["wire_unknown_attempts"] += 1
            elif dispatch_state == "prewire_failure":
                counts["prewire_failures"] += 1
            else:
                raise FlashPayoffError("attempt dispatch state is invalid")
        else:
            counts[disposition] += 1
    _require(
        counts["confirmed_dispatched_calls"] + counts["wire_unknown_attempts"]
        + counts["prewire_failures"] == counts["attempted_calls"],
        "attempt dispatch accounting is not exhaustive",
    )
    _require(
        counts["returned_calls"] <= counts["confirmed_dispatched_calls"],
        "returned calls exceed confirmed dispatches",
    )
    _require(
        counts["returned_calls"] + counts["failed_calls"]
        + counts["skipped_unissued"] + counts["unissued_after_abort"]
        == counts["declared_slots"],
        "slot accounting is not exhaustive",
    )
    return counts


def run(
    plan_path: str | Path,
    output_dir: str | Path,
    *,
    cancel_event: Any,
    invoke_fn: Callable[..., dict[str, Any]] = transport.complete,
    runtime_snapshot_fn: Callable[[], dict[str, Any]] | None = None,
    ready_fn: Callable[[], bool] | None = None,
    memory_fn: Callable[[], float] | None = None,
    idle_probe_fn: Callable[[], dict[str, Any]] | None = None,
    lock_factory: Callable[[Path], Any] = resource_lease,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Run the frozen diagnostic against the warm service, without lifecycle work."""
    plan, plan_sha = load_plan(plan_path)
    _require(callable(getattr(cancel_event, "is_set", None)), "cancel event is missing")
    artifact_root = Path(plan["artifact_policy"]["private_root"])
    output = _artifact_path(Path(output_dir), artifact_root, label="diagnostic output")
    _require(not output.exists(), "diagnostic output already exists")
    snapshot = runtime_snapshot_fn or _live_runtime_binding
    is_ready = ready_fn or _ready
    available = memory_fn or _available_gib
    idle_probe = idle_probe_fn or _endpoint_idle_probe
    start = monotonic()
    deadline = start + EVALUATOR_BUDGET_S
    slots: dict[str, dict[str, Any]] = {}
    outcomes: list[dict[str, Any]] = []
    ordinal = 0
    abort_reason: str | None = None

    def can_issue() -> bool:
        nonlocal abort_reason
        if abort_reason is not None:
            return False
        if cancel_event.is_set():
            abort_reason = "cancelled_before_next_call"
        elif deadline - monotonic() < CALL_TIMEOUT_S + 0.05:
            abort_reason = "evaluator_budget_before_next_call"
        else:
            try:
                available_now = float(available())
                ready_now = is_ready()
                current = snapshot() if ready_now else None
            except Exception as exc:  # noqa: BLE001 - abort without another request
                abort_reason = f"runtime_probe_failed:{type(exc).__name__}"
            else:
                if available_now < MEMORY_FLOOR_GIB:
                    abort_reason = "memory_floor_before_next_call"
                elif not ready_now:
                    abort_reason = "Flash_not_ready_before_next_call"
                elif current != plan["runtime_binding"]:
                    abort_reason = "runtime_identity_changed_before_next_call"
                elif cancel_event.is_set():
                    abort_reason = "cancelled_after_pre_call_probes"
                elif deadline - monotonic() < CALL_TIMEOUT_S + 0.05:
                    abort_reason = "evaluator_budget_after_pre_call_probes"
        return abort_reason is None

    with lock_factory(CANONICAL_ROOT):
        _require(not output.exists(), "diagnostic output appeared after lock acquisition")
        _require(plan["source_sha256"] == _source_hashes(),
                 "evaluator source changed after plan admission")
        _require(is_ready(), "permanent Flash is not ready")
        _require(float(available()) >= MEMORY_FLOOR_GIB, "20 GiB memory floor is unavailable")
        _require(snapshot() == plan["runtime_binding"], "live Flash identity changed after preparation")
        contention_observation = idle_probe()
        _validate_idle_observation(contention_observation)
        _require(contention_observation["observed_idle"] is True,
                 "Flash endpoint is busy before diagnostic start")
        _require(not cancel_event.is_set(), "diagnostic cancelled during admission probes")
        _require(deadline - monotonic() >= CALL_TIMEOUT_S + 0.05,
                 "evaluator budget elapsed during admission probes")
        output.mkdir(mode=0o700, parents=True)
        output.chmod(0o700)
        for fixture in plan["fixtures"]:
            pair_id = fixture["pair_id"]
            for arm_name in fixture["arm_order"]:
                calls: list[dict[str, Any]] = []
                descriptors: list[dict[str, Any]] = []
                if arm_name == "direct":
                    slot_id = f"{pair_id}/direct"
                    if can_issue():
                        call = _invoke(
                            output=output, ordinal=ordinal,
                            diagnostic_id=plan["diagnostic_id"], slot_id=slot_id,
                            messages=legacy._messages(fixture, tool_first=False), tools=[],
                            seed=fixture["seed"], cancel_event=cancel_event,
                            invoke_fn=invoke_fn, monotonic=monotonic,
                        )
                        ordinal += 1
                        slots[slot_id] = _slot(call, slot_id)
                        calls.append(call.receipt)
                        descriptors.append(call.descriptor)
                        grade = legacy._grade_final(
                            call.content, call.status, fixture,
                            finish_reason=call.receipt.get("finish_reason"),
                            tool_calls=call.tool_calls,
                        )
                        if call.dispatch_state == "prewire_failure":
                            abort_reason = f"prewire_failure:{slot_id}"
                        elif call.status == "cancelled":
                            abort_reason = "transport_cancelled"
                    else:
                        slots[slot_id] = _unissued(
                            slot_id, "unissued_after_abort", abort_reason or "aborted"
                        )
                        grade = legacy._grade_final(None, "not_run", fixture)
                    outcomes.append({
                        "pair_id": pair_id,
                        "arm": "direct",
                        "calls": calls,
                        "grade": {"details": {**grade, "_private_call_evidence": {
                            "schema_version": harness.PRIVATE_INDEX_SCHEMA,
                            "artifacts": descriptors,
                        }}},
                    })
                    continue

                first_id = f"{pair_id}/tool_first"
                final_id = f"{pair_id}/tool_final"
                if not can_issue():
                    slots[first_id] = _unissued(
                        first_id, "unissued_after_abort", abort_reason or "aborted"
                    )
                    slots[final_id] = _unissued(
                        final_id, "unissued_after_abort", abort_reason or "aborted"
                    )
                    tool_grade = legacy._grade_tool("not_run", None, (), None, fixture)
                    final_grade = legacy._grade_final(None, "not_run", fixture)
                else:
                    first = _invoke(
                        output=output, ordinal=ordinal,
                        diagnostic_id=plan["diagnostic_id"], slot_id=first_id,
                        messages=legacy._messages(fixture, tool_first=True),
                        tools=[copy.deepcopy(legacy.TOOL_SPEC)], seed=fixture["seed"],
                        cancel_event=cancel_event, invoke_fn=invoke_fn, monotonic=monotonic,
                    )
                    ordinal += 1
                    slots[first_id] = _slot(first, first_id)
                    calls.append(first.receipt)
                    descriptors.append(first.descriptor)
                    tool_grade = legacy._grade_tool(
                        first.status, first.receipt, first.tool_calls, first.content, fixture
                    )
                    final_grade = legacy._grade_final(None, "skipped", fixture)
                    if first.dispatch_state == "prewire_failure":
                        abort_reason = f"prewire_failure:{first_id}"
                    elif first.status == "cancelled":
                        abort_reason = "transport_cancelled"
                    if tool_grade["tool_executed"]:
                        if can_issue():
                            final = _invoke(
                                output=output, ordinal=ordinal,
                                diagnostic_id=plan["diagnostic_id"], slot_id=final_id,
                                messages=legacy._final_messages(
                                    fixture, first.tool_calls[0], first.content or ""
                                ),
                                tools=[], seed=fixture["seed"], cancel_event=cancel_event,
                                invoke_fn=invoke_fn, monotonic=monotonic,
                            )
                            ordinal += 1
                            slots[final_id] = _slot(final, final_id)
                            calls.append(final.receipt)
                            descriptors.append(final.descriptor)
                            final_grade = legacy._grade_final(
                                final.content, final.status, fixture,
                                finish_reason=final.receipt.get("finish_reason"),
                                tool_calls=final.tool_calls,
                            )
                            if final.dispatch_state == "prewire_failure":
                                abort_reason = f"prewire_failure:{final_id}"
                            elif final.status == "cancelled":
                                abort_reason = "transport_cancelled"
                        else:
                            slots[final_id] = _unissued(
                                final_id, "unissued_after_abort", abort_reason or "aborted"
                            )
                            final_grade = legacy._grade_final(None, "not_run", fixture)
                    else:
                        if abort_reason is not None:
                            slots[final_id] = _unissued(
                                final_id, "unissued_after_abort", abort_reason
                            )
                            final_grade = legacy._grade_final(None, "not_run", fixture)
                        else:
                            slots[final_id] = _unissued(
                                final_id, "skipped_unissued",
                                tool_grade["failure_code"] or "tool_not_executed",
                            )
                outcomes.append({
                    "pair_id": pair_id,
                    "arm": "tool",
                    "calls": calls,
                    "grade": {"details": {
                        **final_grade,
                        "tool": tool_grade,
                        "_private_call_evidence": {
                            "schema_version": harness.PRIVATE_INDEX_SCHEMA,
                            "artifacts": descriptors,
                        },
                    }},
                })

        ordered_slots = [slots[slot_id] for slot_id in plan["declared_slots"]]
        accounting = _account(ordered_slots)
        _require(accounting["attempted_calls"] == ordinal, "attempt accounting differs")
        if accounting["returned_calls"] == 0 and abort_reason is None:
            abort_reason = "no_returned_model_responses"
        status = (
            "aborted"
            if abort_reason is not None or accounting["unissued_after_abort"]
            else "complete"
        )
        result = {
            "schema_version": RUN_SCHEMA,
            "status": status,
            "diagnostic_id": plan["diagnostic_id"],
            "plan_raw_sha256": plan_sha,
            "runtime_binding": copy.deepcopy(plan["runtime_binding"]),
            "research_context": copy.deepcopy(RESEARCH_CONTEXT),
            "declared_pairs": plan["declared_pairs"],
            "declared_conditions": plan["declared_conditions"],
            "declared_slots": plan["declared_slots"],
            "slots": ordered_slots,
            "outcomes": outcomes,
            "accounting": accounting,
            "contention_observation": contention_observation,
            "abort_reason": abort_reason,
            "elapsed_s": max(0.0, monotonic() - start),
            "weekly_two_hour_debit": False,
            "production_change_authorized": False,
            "promotion_authorized": False,
            "claim_limit": CLAIM_LIMIT,
            "private_content_exported": False,
        }
        with (output / "run.json").open("xb") as stream:
            stream.write(_canonical(result) + b"\n")
        return result


def _private_metadata(
    output: Path, descriptor: dict[str, Any], call: dict[str, Any]
) -> tuple[dict[str, Any], bytes | None]:
    _require(isinstance(descriptor, dict), "private call descriptor is missing")
    expected_keys = {
        "call_id", "status", "metadata_path", "metadata_sha256",
        "metadata_bytes", "raw_stream",
    }
    _require(set(descriptor) == expected_keys, "private descriptor shape differs")
    _require(descriptor["call_id"] == call["call_id"] and descriptor["status"] == call["status"],
             "public/private call identity differs")
    metadata_path = descriptor.get("metadata_path")
    _require(
        isinstance(metadata_path, str)
        and re.fullmatch(r"private/calls/[0-9]{4}-[0-9a-f]{16}\.json", metadata_path),
        "private metadata path is invalid",
    )
    raw, _ = harness._read_regular_file(
        output / metadata_path, label="private Flash payoff call", max_bytes=64 * 1024 * 1024
    )
    _require(_sha(raw) == descriptor["metadata_sha256"] and len(raw) == descriptor["metadata_bytes"],
             "private metadata bytes differ")
    metadata = harness._strict_object(raw, "private Flash payoff call")
    _require(
        set(metadata) == {
            "schema_version", "call_id", "call_index", "role", "status",
            "dispatch_state", "request", "response", "failure_code", "error",
        }
        and metadata.get("schema_version") == PRIVATE_SCHEMA,
        "private metadata schema or shape differs",
    )
    stream_descriptor = descriptor.get("raw_stream")
    stream = None
    if stream_descriptor is not None:
        _require(
            isinstance(stream_descriptor, dict)
            and set(stream_descriptor) == {"path", "sha256", "bytes"}
            and isinstance(stream_descriptor.get("path"), str)
            and re.fullmatch(
                r"private/streams/[0-9]{4}-[0-9a-f]{16}\.sse",
                stream_descriptor["path"],
            ),
            "private SSE descriptor is invalid",
        )
        metadata_stem = Path(metadata_path).stem
        _require(
            Path(stream_descriptor["path"]).stem == metadata_stem,
            "private metadata/SSE identity differs",
        )
        try:
            stream = private_evidence._recorded(
                output / stream_descriptor["path"],
                label="private Flash payoff SSE",
                ceiling=transport.MAX_RESPONSE_BYTES,
                digest=stream_descriptor["sha256"],
                count=stream_descriptor["bytes"],
                allow_empty_transport=True,
            )
        except private_evidence.PrivateEvidenceError as exc:
            raise FlashPayoffError(f"private SSE bytes differ: {exc}") from exc
    return metadata, stream


def validate(plan_path: str | Path, output_dir: str | Path) -> dict[str, Any]:
    """Replay exact raw evidence and recompute every objective grade."""
    plan, plan_sha = load_plan(plan_path)
    output = _artifact_path(
        Path(output_dir), Path(plan["artifact_policy"]["private_root"]),
        label="diagnostic output",
    )
    run, run_raw = _read_object(output / "run.json", label="Flash payoff run", ceiling=4_000_000)
    _require(set(run) == {
        "schema_version", "status", "diagnostic_id", "plan_raw_sha256",
        "runtime_binding", "research_context", "declared_pairs",
        "declared_conditions", "declared_slots", "slots", "outcomes",
        "accounting", "contention_observation", "abort_reason", "elapsed_s",
        "weekly_two_hour_debit", "production_change_authorized",
        "promotion_authorized", "claim_limit", "private_content_exported",
    }, "run shape differs")
    _require(run.get("schema_version") == RUN_SCHEMA and run.get("status") == "complete",
             "diagnostic run is not complete")
    _require(
        run.get("abort_reason") is None
        and type(run.get("elapsed_s")) in {int, float}
        and math.isfinite(float(run["elapsed_s"]))
        and 0 <= float(run["elapsed_s"]) <= EVALUATOR_BUDGET_S + 5,
        "complete run termination or elapsed time differs",
    )
    _validate_idle_observation(run.get("contention_observation"))
    _require(run["contention_observation"]["observed_idle"] is True,
             "diagnostic did not begin from an observed-idle endpoint")
    _require(run.get("diagnostic_id") == plan["diagnostic_id"], "diagnostic identity differs")
    _require(run.get("plan_raw_sha256") == plan_sha, "plan digest differs")
    _require(run.get("runtime_binding") == plan["runtime_binding"], "runtime binding differs")
    _require(
        run.get("research_context") == plan["research_context"] == RESEARCH_CONTEXT,
        "research motivation context differs",
    )
    _require(
        run.get("declared_pairs") == plan["declared_pairs"]
        and run.get("declared_conditions") == plan["declared_conditions"]
        and run.get("declared_slots") == plan["declared_slots"],
        "declared denominator differs",
    )
    _require(
        run.get("weekly_two_hour_debit") is False
        and run.get("production_change_authorized") is False
        and run.get("promotion_authorized") is False
        and run.get("claim_limit") == CLAIM_LIMIT
        and run.get("private_content_exported") is False,
        "authority or claim boundary differs",
    )
    slots = run.get("slots")
    outcomes = run.get("outcomes")
    _require(
        isinstance(slots, list)
        and all(
            isinstance(slot, dict)
            and set(slot) == {
                "slot_id", "disposition", "status", "failure_code", "call",
                "private_descriptor",
            }
            for slot in slots
        )
        and [slot.get("slot_id") for slot in slots if isinstance(slot, dict)]
        == plan["declared_slots"],
        "slot order or denominator differs",
    )
    _require(isinstance(outcomes, list) and len(outcomes) == DECLARED_CONDITIONS,
             "condition denominator differs")
    _require(
        all(
            isinstance(outcome, dict)
            and set(outcome) == {"pair_id", "arm", "calls", "grade"}
            and isinstance(outcome.get("grade"), dict)
            and set(outcome["grade"]) == {"details"}
            for outcome in outcomes
        ),
        "condition shape differs",
    )
    expected_order = [
        (fixture["pair_id"], arm)
        for fixture in plan["fixtures"]
        for arm in fixture["arm_order"]
    ]
    _require(
        [(outcome.get("pair_id"), outcome.get("arm")) for outcome in outcomes
         if isinstance(outcome, dict)] == expected_order,
        "condition order differs",
    )
    accounting = _account(slots)
    _require(accounting == run.get("accounting") and accounting["unissued_after_abort"] == 0,
             "slot accounting differs")
    _require(
        accounting["returned_calls"] > 0,
        "complete diagnostic has no returned model response",
    )
    _require(
        accounting["prewire_failures"] == 0,
        "complete diagnostic contains a pre-wire failure",
    )
    chronological_indexes = [
        call.get("call_index")
        for outcome in outcomes
        for call in outcome.get("calls", [])
        if isinstance(call, dict)
    ]
    _require(
        chronological_indexes == list(range(accounting["attempted_calls"])),
        "call chronology differs",
    )
    by_slot = {slot["slot_id"]: slot for slot in slots}
    call_indexes: list[int] = []
    returned_streams = 0

    def audit_call(
        call: dict[str, Any], descriptor: dict[str, Any],
        fixture: dict[str, Any], slot_id: str,
        expected_messages: list[dict[str, Any]], expected_tools: list[dict[str, Any]],
    ) -> dict[str, Any]:
        nonlocal returned_streams
        metadata, raw_stream = _private_metadata(output, descriptor, call)
        _require(
            set(call) == {
                "call_index", "call_id", "role", "endpoint_name", "served_model",
                "artifact_sha256", "policy_id", "resolved_policy_sha256", "seed",
                "max_tokens", "timeout_s", "messages_sha256", "tools_sha256",
                "request_sha256", "status", "wall_s", "response_stream_sha256",
                "response_id", "response_model", "finish_reason", "usage",
                "failure_code", "error", "dispatch_state",
            },
            "public call receipt shape differs",
        )
        _require(
            type(call.get("call_index")) is int
            and call["call_index"] >= 0
            and type(call.get("wall_s")) in {int, float}
            and math.isfinite(float(call["wall_s"]))
            and 0 <= float(call["wall_s"]) <= CALL_TIMEOUT_S + 5,
            "public call chronology or elapsed time is malformed",
        )
        request = metadata.get("request")
        response = metadata.get("response")
        _require(
            isinstance(request, dict)
            and isinstance(response, dict)
            and set(response) == {
                "content", "reasoning_content", "tool_calls", "response_id",
                "response_model", "finish_reason", "usage",
                "response_stream_sha256", "raw_stream_artifact",
            },
            "private call payload is missing or has extra fields",
        )
        expected_body = transport.request_body(
            ENDPOINT, expected_messages, POLICY, MAX_TOKENS, fixture["seed"],
            expected_tools or None,
        )
        expected_request_sha = _sha(transport.canonical(expected_body))
        _require(
            request == {
                "endpoint_name": ENDPOINT.name,
                "served_model": ENDPOINT.served_model,
                "artifact_sha256": ENDPOINT.artifact_sha256,
                "policy_id": POLICY_ID,
                "resolved_policy": POLICY,
                "seed": fixture["seed"],
                "max_tokens": MAX_TOKENS,
                "timeout_s": CALL_TIMEOUT_S,
                "messages": expected_messages,
                "tools": expected_tools,
                "request_sha256": expected_request_sha,
            },
            "private request differs from frozen fixture",
        )
        expected_public = {
            "call_id": metadata.get("call_id"),
            "call_index": metadata.get("call_index"),
            "role": metadata.get("role"),
            "status": metadata.get("status"),
            "dispatch_state": metadata.get("dispatch_state"),
            "failure_code": metadata.get("failure_code"),
            "error": metadata.get("error"),
        }
        _require(
            all(call.get(key) == value for key, value in expected_public.items())
            and metadata.get("call_id") == f"{plan['diagnostic_id']}/{slot_id}"
            and metadata.get("role") == "arithmetic",
            "public/private receipt differs",
        )
        _require(
            call.get("endpoint_name") == ENDPOINT.name
            and call.get("served_model") == ENDPOINT.served_model
            and call.get("artifact_sha256") == ENDPOINT.artifact_sha256
            and call.get("policy_id") == POLICY_ID
            and call.get("resolved_policy_sha256") == _sha(_canonical(POLICY))
            and call.get("seed") == fixture["seed"]
            and call.get("max_tokens") == MAX_TOKENS
            and call.get("timeout_s") == CALL_TIMEOUT_S
            and call.get("messages_sha256") == _sha(_canonical(expected_messages))
            and call.get("tools_sha256") == _sha(_canonical(expected_tools))
            and call.get("request_sha256") == expected_request_sha,
            "public call request receipt differs",
        )
        response_receipt_keys = (
            "response_stream_sha256", "response_id", "response_model",
            "finish_reason", "usage",
        )
        if call["status"] == "returned":
            _require(
                all(response.get(key) == call.get(key) for key in response_receipt_keys)
                and call.get("dispatch_state") == "confirmed_dispatched"
                and call.get("failure_code") is None
                and call.get("error") is None,
                "returned public/private response receipt differs",
            )
        else:
            _require(
                all(call.get(key) is None for key in response_receipt_keys)
                and call.get("dispatch_state")
                in {"confirmed_dispatched", "wire_unknown", "prewire_failure"}
                and isinstance(call.get("failure_code"), str)
                and isinstance(call.get("error"), str),
                "failed public response receipt differs",
            )
        slot = by_slot.get(slot_id)
        _require(
            isinstance(slot, dict)
            and slot.get("call") == call
            and slot.get("private_descriptor") == descriptor
            and slot.get("status") == call.get("status")
            and slot.get("failure_code") == call.get("failure_code"),
            "slot/call receipt binding differs",
        )
        _require(
            response.get("raw_stream_artifact") == descriptor.get("raw_stream"),
            "private response/stream descriptor differs",
        )
        stream_descriptor = descriptor.get("raw_stream")
        if call["dispatch_state"] == "confirmed_dispatched":
            _require(
                call["status"] == "returned"
                or (
                    isinstance(stream_descriptor, dict)
                    and stream_descriptor.get("bytes", 0) > 0
                ),
                "confirmed dispatch lacks response-stream evidence",
            )
        elif call["dispatch_state"] == "wire_unknown":
            _require(
                isinstance(stream_descriptor, dict)
                and stream_descriptor.get("bytes") == 0
                and stream_descriptor.get("sha256") == _sha(b""),
                "wire-unknown attempt lacks empty transport evidence",
            )
        else:
            _require(stream_descriptor is None, "pre-wire failure has transport evidence")
        if call["status"] == "returned":
            _require(raw_stream is not None, "returned call has no raw SSE")
            _require(
                response.get("raw_stream_artifact") == descriptor["raw_stream"]
                and call.get("response_stream_sha256") == descriptor["raw_stream"]["sha256"],
                "returned stream binding differs",
            )
            private_evidence._response_matches_raw(raw_stream, response, call)
            returned_streams += 1
        else:
            if stream_descriptor is not None:
                _require(
                    response.get("raw_stream_artifact") == stream_descriptor,
                    "failed stream binding differs",
                )
        call_indexes.append(call["call_index"])
        return metadata

    by_outcome = {(outcome["pair_id"], outcome["arm"]): outcome for outcome in outcomes}
    _require(len(by_outcome) == DECLARED_CONDITIONS, "duplicate condition")
    replayed_direct: dict[str, dict[str, Any]] = {}
    replayed_tool_invocation: dict[str, dict[str, Any]] = {}
    replayed_tool_final: dict[str, dict[str, Any]] = {}
    ragged_tool_conditions: list[str] = []
    for fixture in plan["fixtures"]:
        for arm_name in ("direct", "tool"):
            outcome = by_outcome[(fixture["pair_id"], arm_name)]
            calls = outcome.get("calls")
            details = outcome.get("grade", {}).get("details")
            _require(isinstance(calls, list) and isinstance(details, dict), "condition evidence is missing")
            expected_detail_keys = {
                "strict_shape", "focal_correct", "total_correct", "both_correct",
                "failure_code", "_private_call_evidence",
            }
            if arm_name == "tool":
                expected_detail_keys.add("tool")
            _require(set(details) == expected_detail_keys, "condition grade shape differs")
            private_index = details.get("_private_call_evidence")
            _require(
                isinstance(private_index, dict)
                and set(private_index) == {"schema_version", "artifacts"}
                and private_index.get("schema_version") == harness.PRIVATE_INDEX_SCHEMA
                and isinstance(private_index.get("artifacts"), list)
                and len(private_index["artifacts"]) == len(calls),
                "condition private evidence index differs",
            )
            metadata: list[dict[str, Any]] = []
            if arm_name == "direct":
                slot_id = f"{fixture['pair_id']}/direct"
                _require(len(calls) == 1, "direct condition call count differs")
                metadata.append(audit_call(
                    calls[0], private_index["artifacts"][0], fixture, slot_id,
                    legacy._messages(fixture, tool_first=False), [],
                ))
                grade = legacy._grade_final(
                    metadata[0]["response"]["content"], calls[0]["status"], fixture,
                    finish_reason=calls[0].get("finish_reason"),
                    tool_calls=metadata[0]["response"]["tool_calls"],
                )
                stored = {key: value for key, value in details.items()
                          if key != "_private_call_evidence"}
                _require(grade == stored, "direct objective grade differs on replay")
                replayed_direct[slot_id] = grade
                continue

            first_id = f"{fixture['pair_id']}/tool_first"
            final_id = f"{fixture['pair_id']}/tool_final"
            _require(len(calls) in (1, 2), "tool condition call count differs")
            metadata.append(audit_call(
                calls[0], private_index["artifacts"][0], fixture, first_id,
                legacy._messages(fixture, tool_first=True),
                [copy.deepcopy(legacy.TOOL_SPEC)],
            ))
            tool_grade = legacy._grade_tool(
                calls[0]["status"], calls[0], metadata[0]["response"]["tool_calls"],
                metadata[0]["response"]["content"], fixture,
            )
            _require(tool_grade == details.get("tool"), "native tool grade differs on replay")
            replayed_tool_invocation[first_id] = tool_grade
            if tool_grade["tool_executed"]:
                _require(len(calls) == 2, "executed tool has no final call")
                final_messages = legacy._final_messages(
                    fixture, metadata[0]["response"]["tool_calls"][0],
                    metadata[0]["response"]["content"] or "",
                )
                metadata.append(audit_call(
                    calls[1], private_index["artifacts"][1], fixture, final_id,
                    final_messages, [],
                ))
                grade = legacy._grade_final(
                    metadata[1]["response"]["content"], calls[1]["status"], fixture,
                    finish_reason=calls[1].get("finish_reason"),
                    tool_calls=metadata[1]["response"]["tool_calls"],
                )
            else:
                ragged_tool_conditions.append(f"{fixture['pair_id']}/tool")
                _require(
                    len(calls) == 1
                    and by_slot[final_id]["disposition"] == "skipped_unissued"
                    and by_slot[final_id]["failure_code"] == tool_grade["failure_code"],
                    "invalid tool call did not causally skip its final slot",
                )
                grade = legacy._grade_final(None, "skipped", fixture)
            stored = {key: value for key, value in details.items()
                      if key not in {"tool", "_private_call_evidence"}}
            _require(grade == stored, "tool-final objective grade differs on replay")
            replayed_tool_final[final_id] = grade

    _require(
        sorted(call_indexes) == list(range(accounting["attempted_calls"])),
        "audited call coverage differs",
    )
    _require(returned_streams == accounting["returned_calls"], "returned SSE denominator differs")

    expected_direct = {f"{fixture['pair_id']}/direct" for fixture in plan["fixtures"]}
    expected_tool_first = {f"{fixture['pair_id']}/tool_first" for fixture in plan["fixtures"]}
    expected_tool_final = {f"{fixture['pair_id']}/tool_final" for fixture in plan["fixtures"]}

    def stage_summary(
        expected: set[str], grades: dict[str, dict[str, Any]],
        success_key: str, score_label: str,
    ) -> dict[str, Any]:
        missing = sorted(expected - set(grades))
        failed = sorted(
            cell_id for cell_id, grade in grades.items()
            if grade.get(success_key) is not True
        )
        categories: dict[str, int] = {}
        for cell_id in failed:
            code = grades[cell_id].get("failure_code")
            category = code if isinstance(code, str) and code else "unknown_failure"
            categories[category] = categories.get(category, 0) + 1
        return {
            score_label: sum(
                grade.get(success_key) is True for grade in grades.values()
            ),
            "denominator": len(expected),
            "missing_cells": missing,
            "failed_cells": failed,
            "failure_categories": dict(sorted(categories.items())),
        }

    direct_summary = stage_summary(
        expected_direct, replayed_direct, "both_correct", "correct"
    )
    invocation_summary = stage_summary(
        expected_tool_first, replayed_tool_invocation, "tool_executed", "exact"
    )
    final_summary = stage_summary(
        expected_tool_final, replayed_tool_final, "both_correct", "correct"
    )
    missing_cells = sorted(
        set(direct_summary["missing_cells"])
        | set(invocation_summary["missing_cells"])
        | set(final_summary["missing_cells"])
    )
    failed_cells = sorted(
        set(direct_summary["failed_cells"])
        | set(invocation_summary["failed_cells"])
        | set(final_summary["failed_cells"])
    )
    objective_summary = {
        "derived_from_independent_replay": True,
        "denominators": {
            "pairs": 6,
            "conditions": DECLARED_CONDITIONS,
            "max_call_slots": DECLARED_SLOTS,
            "direct_cells": 6,
            "tool_invocation_cells": 6,
            "tool_final_cells": 6,
            **accounting,
        },
        "direct": direct_summary,
        "tool_invocation": invocation_summary,
        "tool_final": final_summary,
        "missing_cells": missing_cells,
        "ragged_conditions": sorted(ragged_tool_conditions),
        "failed_cells": failed_cells,
    }
    return {
        "schema_version": VALIDATION_SCHEMA,
        "status": "passed",
        "diagnostic_id": plan["diagnostic_id"],
        "plan_raw_sha256": plan_sha,
        "run_raw_sha256": _sha(run_raw),
        "raw_sse_replay_passed": True,
        "grade_replay_passed": True,
        "declared_pairs": 6,
        "declared_conditions": DECLARED_CONDITIONS,
        "declared_slots": DECLARED_SLOTS,
        "accounting": accounting,
        "objective_summary": objective_summary,
        "contention_observation": copy.deepcopy(run["contention_observation"]),
        "returned_streams_replayed": returned_streams,
        "private_content_exported": False,
        "production_change_authorized": False,
        "promotion_authorized": False,
        "research_context": copy.deepcopy(RESEARCH_CONTEXT),
        "claim_limit": CLAIM_LIMIT,
    }


def _cancel_event() -> threading.Event:
    event = threading.Event()
    for number in (signal.SIGINT, signal.SIGTERM):
        signal.signal(number, lambda *_args, target=event: target.set())
    return event


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--prepare", metavar="PLAN")
    action.add_argument("--run", metavar="PLAN")
    action.add_argument("--validate", metavar="PLAN")
    parser.add_argument("--output")
    parser.add_argument("--diagnostic-id")
    args = parser.parse_args(argv)
    if args.prepare:
        _require(args.output is None, "--prepare does not accept --output")
        _require(bool(args.diagnostic_id), "--prepare requires --diagnostic-id")
        result = make_plan(args.prepare, diagnostic_id=args.diagnostic_id)
    elif args.run:
        _require(bool(args.output), "--run requires --output")
        _require(args.diagnostic_id is None, "--run reads diagnostic ID from the plan")
        result = run(args.run, args.output, cancel_event=_cancel_event())
    else:
        _require(bool(args.output), "--validate requires --output")
        _require(args.diagnostic_id is None, "--validate reads diagnostic ID from the plan")
        result = validate(args.validate, args.output)
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
