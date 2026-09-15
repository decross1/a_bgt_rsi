"""Serial, failure-inclusive runner for the frozen Flash-Next A/B plan."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import stat
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from itertools import pairwise
from pathlib import Path
from typing import Any

from .adapters import (
    AdapterResult,
    CallResult,
    CallSpec,
    CellDefinition,
    execute_cell,
    load_cells,
)
from .manifest import (
    REPO_ROOT,
    RUN_SCHEMA,
    canonical_json,
    plan_fingerprints,
    sha256_file,
    sha256_json,
    validate_plan,
)
from .transport import (
    MAX_RESPONSE_BYTES,
    LocalEndpoint,
    TransportCancelled,
    TransportError,
    complete,
    request_body,
)
from .transport import (
    canonical as transport_canonical,
)

CHECKPOINT_SCHEMA = "flash-next-ab-checkpoint/v1"
PRIVATE_CALL_SCHEMA = "flash-next-ab-private-call/v1"
PRIVATE_INDEX_SCHEMA = "flash-next-ab-private-evidence-index/v1"
MAX_RECEIPT_BYTES = 4 * 1024 * 1024
MAX_PRIVATE_METADATA_BYTES = 64 * 1024 * 1024
# One cohort's sum of the registered family ceilings: objective calls (2,880),
# topic (1,440), context (480), portfolio (2,160), diversity (800), role effort
# (1,800), and historical repair (870).  This is a safety bound, not a
# weekly-compute debit or a recommendation to consume the whole allowance.
MAX_RUNTIME_BUDGET_S = 10_430
_BASE_URLS = {
    "resident_gemma": "http://127.0.0.1:8000/v1",
    "resident_qwen": "http://127.0.0.1:8001/v1",
    "flash_next": "http://127.0.0.1:8012/v1",
}

RawInvokeFn = Callable[..., dict[str, Any]]
QualificationGate = Callable[[dict[str, Any], str], None]


class HarnessError(RuntimeError):
    """The run cannot start or cannot preserve its frozen contract."""


def _utc_datetime(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise HarnessError(f"{label} is not a timestamp")
    try:
        observed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise HarnessError(f"{label} is not a timestamp") from exc
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise HarnessError(f"{label} has no timezone")
    return observed.astimezone(timezone.utc)


def _strict_object(raw: bytes, source: str) -> dict[str, Any]:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise HarnessError(f"duplicate JSON key in {source}: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw,
            object_pairs_hook=unique,
            parse_constant=lambda item: (_ for _ in ()).throw(
                HarnessError(f"non-finite JSON in {source}: {item}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HarnessError(f"invalid JSON in {source}") from exc
    if not isinstance(value, dict):
        raise HarnessError(f"{source} must contain a JSON object")
    return value


def _read_regular_file(
    path: str | Path,
    *,
    label: str,
    max_bytes: int = MAX_RECEIPT_BYTES,
) -> tuple[bytes, Path]:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        raise HarnessError(f"{label} path must be absolute")
    normalized = Path(os.path.abspath(candidate))
    parts = normalized.parts[1:]
    if not parts:
        raise HarnessError(f"{label} must name a file")
    close_on_exec = getattr(os, "O_CLOEXEC", 0)
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | close_on_exec | no_follow
    directory = os.open(normalized.anchor, directory_flags)
    try:
        for part in parts[:-1]:
            try:
                child = os.open(part, directory_flags, dir_fd=directory)
            except OSError as exc:
                raise HarnessError(f"{label} parent is unavailable or redirected") from exc
            os.close(directory)
            directory = child
        file_flags = (
            os.O_RDONLY
            | close_on_exec
            | no_follow
            | getattr(os, "O_NONBLOCK", 0)
        )
        try:
            descriptor = os.open(parts[-1], file_flags, dir_fd=directory)
        except OSError as exc:
            raise HarnessError(f"{label} is unavailable or redirected") from exc
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode):
                raise HarnessError(f"{label} must be a regular file")
            if before.st_size <= 0 or before.st_size > max_bytes:
                raise HarnessError(f"{label} exceeds its bounded size")
            chunks = []
            remaining = before.st_size
            while remaining:
                chunk = os.read(descriptor, min(1024 * 1024, remaining))
                if not chunk:
                    raise HarnessError(f"{label} changed during its bounded read")
                chunks.append(chunk)
                remaining -= len(chunk)
            if os.read(descriptor, 1):
                raise HarnessError(f"{label} changed during its bounded read")
            after = os.fstat(descriptor)
            stable = (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
            ) == (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            )
            if not stable:
                raise HarnessError(f"{label} changed during its bounded read")
            raw = b"".join(chunks)
        finally:
            os.close(descriptor)
    finally:
        os.close(directory)
    return raw, normalized


def _read_json_receipt(path: str | Path, label: str) -> tuple[dict[str, Any], str, Path]:
    raw, normalized = _read_regular_file(path, label=label)
    return _strict_object(raw, label), hashlib.sha256(raw).hexdigest(), normalized


def _qualification_sha256(value: Any) -> str:
    """Match the qualification controller's canonical JSON hash exactly."""
    try:
        raw = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    except (TypeError, ValueError) as exc:
        raise HarnessError("qualification evidence is not canonical JSON") from exc
    return hashlib.sha256(raw).hexdigest()


def _finite_number(value: Any, where: str, *, minimum: float = 0.0) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) < minimum
    ):
        raise HarnessError(f"{where} must be finite and at least {minimum}")
    return float(value)


def _qualification_runtime_sha256(*, image_id: str, command_sha256: str) -> str:
    if (
        not isinstance(image_id, str)
        or not _digest(image_id.removeprefix("sha256:"))
        or not _digest(command_sha256)
    ):
        raise HarnessError("qualification runtime identity is malformed")
    return sha256_json({"image_id": image_id, "command_sha256": command_sha256})


def _digest(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _validate_flash_probes(
    probes: dict[str, Any],
    *,
    probe_set: str,
    served_model: str,
    artifact_sha256: str,
) -> None:
    if set(probes) != {"probe_set", "results"} or probes["probe_set"] != probe_set:
        raise HarnessError("Flash qualification probe bundle differs from its plan")
    rows = probes["results"]
    if not isinstance(rows, list) or [row.get("probe_id") for row in rows if isinstance(row, dict)] != [
        "exact_literal",
        "exact_arithmetic",
        "exact_tool_call",
    ]:
        raise HarnessError("Flash qualification probe identities differ")
    expected_text = ("FLASH_NEXT_OK_17", "703")
    for index, expected in enumerate(expected_text):
        row = rows[index]
        endpoint = row.get("endpoint")
        if (
            row.get("response_model") != served_model
            or str(row.get("content", "")).strip() != expected
            or row.get("tool_calls") != []
            or row.get("finish_reason") != "stop"
            or not isinstance(endpoint, dict)
            or endpoint.get("served_model") != served_model
            or endpoint.get("artifact_sha256") != artifact_sha256
        ):
            raise HarnessError(f"Flash qualification probe {row.get('probe_id')!r} differs")
    tool_row = rows[2]
    calls = tool_row.get("tool_calls")
    try:
        function = calls[0]["function"]
        arguments = json.loads(function["arguments"])
    except (IndexError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise HarnessError("Flash qualification tool probe is malformed") from exc
    endpoint = tool_row.get("endpoint")
    if (
        not isinstance(calls, list)
        or len(calls) != 1
        or function.get("name") != "record_probe"
        or arguments != {"label": "flash-next", "value": 703}
        or str(tool_row.get("content", "")).strip()
        or tool_row.get("finish_reason") != "tool_calls"
        or tool_row.get("response_model") != served_model
        or not isinstance(endpoint, dict)
        or endpoint.get("served_model") != served_model
        or endpoint.get("artifact_sha256") != artifact_sha256
    ):
        raise HarnessError("Flash qualification tool probe differs")


def _validate_memory_log(
    path: Path,
    result: dict[str, Any],
) -> None:
    raw, _ = _read_regular_file(path, label="qualification memory log")
    rows: list[dict[str, Any]] = []
    for index, line in enumerate(raw.splitlines()):
        if not line.strip():
            continue
        rows.append(_strict_object(line, f"qualification memory log line {index + 1}"))
    samples = [row for row in rows if "mem_available_gib" in row]
    if len(samples) != result.get("memory_samples") or not samples:
        raise HarnessError("qualification memory sample count differs")
    observed_min = min(
        _finite_number(row.get("mem_available_gib"), "memory MemAvailable")
        for row in samples
    )
    reported_min = _finite_number(
        result.get("min_mem_available_gib"), "reported minimum MemAvailable"
    )
    if abs(observed_min - reported_min) > 1e-9:
        raise HarnessError("qualification minimum MemAvailable differs from its log")
    for row in samples:
        delta = row.get("pswpout_delta_pages")
        pages = row.get("pswpout_pages")
        if (
            isinstance(delta, bool)
            or not isinstance(delta, int)
            or delta < 0
            or isinstance(pages, bool)
            or not isinstance(pages, int)
            or pages < 0
        ):
            raise HarnessError("qualification swap evidence is malformed")
    if (
        result.get("pswpout_initial_pages") != samples[0]["pswpout_pages"]
        or result.get("pswpout_final_pages") != samples[-1]["pswpout_pages"]
        or result.get("pswpout_delta_pages")
        != samples[-1]["pswpout_pages"] - samples[0]["pswpout_pages"]
    ):
        raise HarnessError("qualification swap summary differs from its log")
    if result.get("schema") == "qwen-flash-next-qualification-result/v1":
        return

    if result.get("schema") != "qwen-flash-next-qualification-result/v2":
        raise HarnessError("unsupported qualification memory schema")

    def nonnegative_int(value: Any, label: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise HarnessError(f"{label} is malformed")
        return value

    parsed_times: list[datetime] = []
    phases: list[str] = []
    prior_pages: int | None = None
    total_initial = nonnegative_int(
        samples[0].get("pswpout_pages"), "qualification initial pswpout"
    )
    mutation_initial: int | None = None
    for index, row in enumerate(samples):
        if row.get("schema") != "qwen-flash-next-memory-sample/v2":
            raise HarnessError("qualification v2 memory row has the wrong schema")
        phase = row.get("monitor_phase")
        if phase not in {"setup", "mutation"}:
            raise HarnessError("qualification memory phase is malformed")
        if not isinstance(row.get("setup_quiescence_active"), bool):
            raise HarnessError("qualification quiescence marker is malformed")
        pages = nonnegative_int(row.get("pswpout_pages"), "qualification pswpout")
        if prior_pages is not None and pages < prior_pages:
            raise HarnessError("qualification pswpout counter decreased")
        prior_pages = pages
        parsed_times.append(
            _utc_datetime(row.get("observed_at"), "qualification memory timestamp")
        )
        if index and parsed_times[-1] < parsed_times[-2]:
            raise HarnessError("qualification memory timestamps decreased")
        total_delta = nonnegative_int(
            row.get("pswpout_delta_pages"), "qualification total pswpout delta"
        )
        setup_delta = nonnegative_int(
            row.get("setup_pswpout_delta_pages"),
            "qualification setup pswpout delta",
        )
        if total_delta != pages - total_initial:
            raise HarnessError("qualification total pswpout delta differs from raw counter")
        if phase == "setup":
            if row.get("mutation_pswpout_delta_pages") is not None:
                raise HarnessError("setup memory row contains a mutation delta")
            if setup_delta != pages - total_initial:
                raise HarnessError("setup pswpout delta differs from raw counter")
        else:
            if mutation_initial is None:
                mutation_initial = pages
            mutation_delta = nonnegative_int(
                row.get("mutation_pswpout_delta_pages"),
                "qualification mutation pswpout delta",
            )
            if setup_delta != mutation_initial - total_initial:
                raise HarnessError("mutation row changed the setup pswpout delta")
            if mutation_delta != pages - mutation_initial:
                raise HarnessError("mutation pswpout delta differs from raw counter")
        phases.append(phase)

    mutation_indexes = [index for index, phase in enumerate(phases) if phase == "mutation"]
    if not mutation_indexes or mutation_indexes[0] == 0:
        raise HarnessError("qualification memory log lacks a setup-to-mutation boundary")
    boundary = mutation_indexes[0]
    if phases != ["setup"] * boundary + ["mutation"] * (len(phases) - boundary):
        raise HarnessError("qualification memory phases are not contiguous")
    if mutation_initial is None:
        raise HarnessError("qualification mutation baseline is absent")

    active_indexes = [
        index
        for index, row in enumerate(samples)
        if row["setup_quiescence_active"]
    ]
    if not active_indexes:
        raise HarnessError("qualification setup quiescence samples are absent")
    if active_indexes != list(range(active_indexes[0], active_indexes[-1] + 1)):
        raise HarnessError("qualification setup quiescence samples are not contiguous")
    if active_indexes[-1] >= boundary:
        raise HarnessError("qualification setup quiescence crossed the mutation boundary")
    quiet_rows = [samples[index] for index in active_indexes]
    quiet_times = [parsed_times[index] for index in active_indexes]
    quiet_pages = [row["pswpout_pages"] for row in quiet_rows]
    required = nonnegative_int(
        result.get("setup_quiescence_required_seconds"),
        "qualification setup quiescence requirement",
    )
    duration = _finite_number(
        result.get("setup_quiescence_duration_seconds"),
        "qualification setup quiescence duration",
    )
    if (
        required != 60
        or duration < required
        or result.get("setup_quiescence_passed") is not True
        or result.get("setup_quiescence_started_at") != quiet_rows[0]["observed_at"]
        or result.get("setup_quiescence_completed_at")
        != quiet_rows[-1]["observed_at"]
        or result.get("setup_quiescence_initial_pswpout_pages") != quiet_pages[0]
        or result.get("setup_quiescence_final_pswpout_pages") != quiet_pages[-1]
        or result.get("setup_quiescence_samples") != len(quiet_rows)
        or any(pages != quiet_pages[0] for pages in quiet_pages)
    ):
        raise HarnessError("qualification setup quiescence proof differs from raw samples")
    if (quiet_times[-1] - quiet_times[0]).total_seconds() < required:
        raise HarnessError("qualification setup quiescence timestamps span under 60 seconds")
    if any(
        (later - earlier).total_seconds() > 2.5
        for earlier, later in pairwise(quiet_times)
    ):
        raise HarnessError("qualification setup quiescence has a memory-sample gap")
    if mutation_initial != quiet_pages[-1]:
        raise HarnessError("qualification mutation baseline differs from quiet setup counter")

    first_mutation = samples[boundary]
    last_mutation = samples[-1]
    if (
        result.get("setup_pswpout_initial_pages") != total_initial
        or result.get("setup_pswpout_final_pages") != mutation_initial
        or result.get("setup_pswpout_delta_pages") != mutation_initial - total_initial
        or result.get("mutation_window_started_at")
        != first_mutation["observed_at"]
        or result.get("mutation_pswpout_initial_pages") != mutation_initial
        or result.get("mutation_pswpout_final_pages")
        != last_mutation["pswpout_pages"]
        or result.get("mutation_pswpout_delta_pages")
        != last_mutation["pswpout_pages"] - mutation_initial
        or result.get("mutation_final_sample_at") != last_mutation["observed_at"]
    ):
        raise HarnessError("qualification phase swap summary differs from its log")
    if any(row["mutation_pswpout_delta_pages"] != 0 for row in samples[boundary:]):
        raise HarnessError("qualification mutation window contains swap-out")
    mutation_times = parsed_times[boundary:]
    if any(
        (later - earlier).total_seconds() > 10
        for earlier, later in pairwise(mutation_times)
    ):
        raise HarnessError("qualification mutation window has a memory-sample gap")
    restoration = result.get("restoration")
    if not isinstance(restoration, dict):
        raise HarnessError("qualification restoration evidence is malformed")
    restoration_at = _utc_datetime(
        restoration.get("verified_at"), "qualification restoration timestamp"
    )
    if parsed_times[-1] < restoration_at:
        raise HarnessError("qualification final memory sample predates restoration")


def validate_flash_qualification_files(
    receipt_path: str | Path,
    qualification_plan_path: str | Path,
    contract_snapshot_path: str | Path,
    *,
    contract_raw_path: str | Path | None = None,
    require_passed: bool = False,
) -> dict[str, Any]:
    """Validate one external Flash qualification attempt without an A/B plan.

    Failed attempts remain renderable as authentic history.  They are never
    admissible: callers that authorize model requests must set
    ``require_passed=True`` or use :func:`validate_qualification_receipt`.
    """
    result, receipt_sha256, receipt_file = _read_json_receipt(
        receipt_path, "Flash qualification result"
    )
    qualification_plan, _, plan_file = _read_json_receipt(
        qualification_plan_path, "Flash qualification plan"
    )
    contract, contract_snapshot_sha256, contract_file = _read_json_receipt(
        contract_snapshot_path, "Flash qualification contract snapshot"
    )
    result_schema = result.get("schema")
    plan_schema = qualification_plan.get("schema")
    contract_schema = contract.get("schema")
    supported_bundles = {
        (
            "qwen-flash-next-qualification-result/v1",
            "qwen-flash-next-qualification-plan/v1",
            "qwen-flash-next-qualification/v1",
        ),
        (
            "qwen-flash-next-qualification-result/v2",
            "qwen-flash-next-qualification-plan/v2",
            "qwen-flash-next-qualification/v2",
        ),
    }
    if (result_schema, plan_schema, contract_schema) not in supported_bundles:
        raise HarnessError("unsupported Flash qualification result schema")
    bundle_v2 = result_schema == "qwen-flash-next-qualification-result/v2"
    if result.get("plan_sha256") != _qualification_sha256(qualification_plan):
        raise HarnessError("Flash qualification result does not bind its plan")
    # The controller binds the original byte-for-byte external contract.  Its
    # pretty JSON snapshot is useful to inspect but cannot replace those exact
    # bytes because whitespace changes the digest.
    contract_sha256 = result.get("contract_sha256")
    if (
        not _digest(contract_sha256)
        or qualification_plan.get("contract_sha256") != contract_sha256
    ):
        raise HarnessError("Flash qualification result and plan disagree on contract identity")
    raw_contract_file = None
    raw_contract_failure = None
    raw_candidate = (
        Path(contract_raw_path)
        if contract_raw_path is not None
        else receipt_file.parent / "launch-contract.raw.json"
    )
    try:
        raw_contract, raw_contract_sha256, raw_contract_file = _read_json_receipt(
            raw_candidate, "Flash qualification raw contract"
        )
    except HarnessError as exc:
        if contract_raw_path is not None:
            raise
        raw_contract_failure = str(exc)
    else:
        if raw_contract != contract or raw_contract_sha256 != contract_sha256:
            raise HarnessError(
                "Flash raw contract bytes/content differ from result and snapshot"
            )

    model = contract.get("model")
    image = contract.get("image")
    runtime = contract.get("runtime")
    safety = contract.get("safety")
    accounting = contract.get("accounting")
    if not all(isinstance(value, dict) for value in (model, image, runtime, safety, accounting)):
        raise HarnessError("Flash qualification contract sections are malformed")
    from . import qualification as registered

    artifact_sha256 = model.get("artifact_sha256")
    expected_model = {
        "repository": registered.MODEL_REPOSITORY,
        "revision": registered.MODEL_REVISION,
        "served_name": registered.SERVED_MODEL,
        "artifact_sha256": registered.model_artifact_sha256(),
        "files": registered.expected_model_files(),
        "safetensors_total_bytes": registered.MODEL_TOTAL_BYTES,
        "tensor_payload_bytes": registered.MODEL_TENSOR_BYTES,
        "repository_total_bytes": registered.MODEL_REPOSITORY_BYTES,
    }
    if any(model.get(key) != value for key, value in expected_model.items()):
        raise HarnessError("Flash qualification model differs from registered C0")
    if (
        image.get("id") != registered.IMAGE_ID
        or image.get("architecture") != "arm64"
    ):
        raise HarnessError("Flash qualification image differs from registered ARM64 C0")
    if not _digest(artifact_sha256):
        raise HarnessError("Flash qualification model artifact is malformed")
    if (
        result.get("model_artifact_sha256") != artifact_sha256
        or qualification_plan.get("model_artifact_sha256") != artifact_sha256
        or qualification_plan.get("served_model") != model.get("served_name")
        or qualification_plan.get("image_id") != image.get("id")
        or qualification_plan.get("profile") != contract.get("profile")
        or qualification_plan.get("probe_set") != contract.get("probe_set")
        or qualification_plan.get("contract_id") != contract.get("contract_id")
        or qualification_plan.get("min_mem_available_gib")
        != safety.get("min_mem_available_gib")
        or (
            bundle_v2
            and qualification_plan.get("setup_quiescence_seconds")
            != safety.get("setup_quiescence_seconds")
        )
        or qualification_plan.get("docker_create_argv_sha256")
        != _qualification_sha256(qualification_plan.get("docker_create_argv"))
    ):
        raise HarnessError("Flash qualification plan identity differs from its contract")
    if (
        accounting.get("weekly_budget_debit") is not False
        or accounting.get("paid_api_allowed") is not False
        or qualification_plan.get("weekly_budget_debit") is not False
        or qualification_plan.get("paid_api_allowed") is not False
        or qualification_plan.get("production_change_authorized") is not False
    ):
        raise HarnessError("Flash qualification contract authorizes a forbidden side effect")

    registration_failures = []
    if not bundle_v2:
        registration_failures.append(
            "legacy qualification schema is historical and cannot admit calls"
        )
    if raw_contract_failure is not None:
        registration_failures.append("exact raw external contract is absent")
    try:
        registered.validate_contract(contract)
    except registered.QualificationError as exc:
        registration_failures.append(f"contract is not current registered C0 ({exc})")
    if qualification_plan.get("docker_create_argv") != registered.launch_argv():
        registration_failures.append("launch argv is not current registered C0")
    if _finite_number(
        safety.get("min_mem_available_gib"), "contract minimum MemAvailable"
    ) < registered.MIN_MEMORY_GIB:
        registration_failures.append("contract memory floor is below registered 30 GiB")

    # The controller writes these siblings from the same bounded attempt.  A
    # failed preflight may legitimately lack later evidence; a pass may not.
    failures = list(registration_failures)
    if result.get("status") != "passed":
        failures.append(f"status={result.get('status')!r}")
    if result.get("qualification_error") is not None:
        failures.append("qualification_error is present")
    restoration = result.get("restoration")
    if not isinstance(restoration, dict) or restoration.get("status") != "verified":
        failures.append("restoration is not verified")
    else:
        if restoration.get("errors") not in (None, []):
            failures.append("restoration reports errors")
        if restoration.get("sentinel_retained") is not False:
            failures.append("qualification sentinel was retained")
    minimum_required = _finite_number(
        safety.get("min_mem_available_gib"), "contract minimum MemAvailable"
    )
    try:
        minimum_observed = _finite_number(
            result.get("min_mem_available_gib"), "qualification minimum MemAvailable"
        )
    except HarnessError:
        minimum_observed = None
        failures.append("minimum MemAvailable is absent")
    else:
        if minimum_observed < minimum_required:
            failures.append("minimum MemAvailable fell below the contract")
    if result.get("probe_count") != 3:
        failures.append("three fixed probes did not return")
    if bundle_v2:
        if result.get("mutation_pswpout_delta_pages") != 0:
            failures.append("host swap-out increased during the mutation window")
    elif result.get("pswpout_delta_pages") != 0:
        failures.append("host swap-out increased")
    if result.get("weekly_budget_debit") is not False:
        failures.append("weekly maintenance budget was debited")
    if result.get("paid_api_calls") != 0:
        failures.append("paid API calls are nonzero")
    if result.get("production_change_authorized") is not False:
        failures.append("qualification claims production authority")
    for key in (
        "elapsed_seconds",
        "challenger_gpu_seconds",
        "all_gpu_research_seconds",
        "resident_downtime_seconds",
    ):
        _finite_number(result.get(key), f"qualification {key}")

    try:
        _validate_memory_log(receipt_file.parent / "memory.jsonl", result)
    except HarnessError as exc:
        failures.append(str(exc))

    probes_path = receipt_file.parent / "probes.json"
    if probes_path.exists():
        probes, _, _ = _read_json_receipt(probes_path, "Flash qualification probes")
        _validate_flash_probes(
            probes,
            probe_set=qualification_plan["probe_set"],
            served_model=qualification_plan["served_model"],
            artifact_sha256=artifact_sha256,
        )
    else:
        failures.append("fixed probe artifact is absent")

    model_receipt_path = receipt_file.parent / "model-verification.json"
    if model_receipt_path.exists():
        model_receipt, _, _ = _read_json_receipt(
            model_receipt_path, "Flash model verification receipt"
        )
        if (
            model_receipt.get("artifact_sha256") != artifact_sha256
            or model_receipt.get("full_sha256") is not True
            or model_receipt.get("safetensors_total_bytes")
            != model.get("safetensors_total_bytes")
            or model_receipt.get("verified_files") != model.get("files")
        ):
            raise HarnessError("Flash model verification differs from the contract")
    else:
        failures.append("model verification artifact is absent")

    summary = {
        "schema_version": "flash-next-qualification-validation/v1",
        "cohort": "flash",
        "run_id": result.get("run_id"),
        "status": result.get("status"),
        "admission_eligible": not failures,
        "admission_failures": failures,
        "qualification_receipt_sha256": receipt_sha256,
        "qualification_plan_sha256": result["plan_sha256"],
        "contract_sha256": contract_sha256,
        "contract_snapshot_sha256": contract_snapshot_sha256,
        "model_artifact_sha256": artifact_sha256,
        "runtime_sha256": _qualification_runtime_sha256(
            image_id=image["id"],
            command_sha256=qualification_plan["docker_create_argv_sha256"],
        ),
        "served_model": qualification_plan["served_model"],
        "min_mem_available_gib": minimum_observed,
        "probe_count": result.get("probe_count"),
        "pswpout_delta_pages": result.get("pswpout_delta_pages"),
        "setup_pswpout_delta_pages": result.get("setup_pswpout_delta_pages"),
        "mutation_pswpout_delta_pages": result.get(
            "mutation_pswpout_delta_pages"
        ),
        "restoration_status": (
            restoration.get("status") if isinstance(restoration, dict) else None
        ),
        "receipt_path": str(receipt_file),
        "qualification_plan_path": str(plan_file),
        "contract_snapshot_path": str(contract_file),
        "contract_raw_path": (
            str(raw_contract_file) if raw_contract_file is not None else None
        ),
    }
    if require_passed and failures:
        raise HarnessError("Flash qualification is not admissible: " + "; ".join(failures))
    return summary


def validate_resident_qualification_files(
    receipt_path: str | Path,
    artifact_inventory_path: str | Path,
    *,
    require_passed: bool = False,
) -> dict[str, Any]:
    """Validate the resident literal/arithmetic transport qualification."""
    result, receipt_sha256, receipt_file = _read_json_receipt(
        receipt_path, "resident qualification result"
    )
    inventory, inventory_sha256, inventory_file = _read_json_receipt(
        artifact_inventory_path, "resident artifact inventory"
    )
    if result.get("schema_version") != "flash-next-resident-qualification/v1":
        raise HarnessError("unsupported resident qualification schema")
    if inventory.get("schema_version") != "resident-model-artifacts/v1":
        raise HarnessError("unsupported resident artifact schema")
    models = inventory.get("models")
    if not isinstance(models, dict) or set(models) != {"resident_gemma", "resident_qwen"}:
        raise HarnessError("resident artifact inventory model set differs")
    artifacts = {}
    for endpoint_name, model in models.items():
        if not isinstance(model, dict) or model.get("full_sha256") is not True:
            raise HarnessError("resident artifact inventory is incomplete")
        artifact = model.get("artifact_sha256")
        directories = model.get("directories")
        if (
            not isinstance(directories, dict)
            or not directories
            or sha256_json(directories) != artifact
        ):
            raise HarnessError("resident artifact digest does not bind its file inventory")
        for directory_name, files in directories.items():
            if not isinstance(directory_name, str) or not isinstance(files, dict) or not files:
                raise HarnessError("resident artifact directory inventory is malformed")
            for filename, file_receipt in files.items():
                if (
                    not isinstance(filename, str)
                    or not isinstance(file_receipt, dict)
                    or set(file_receipt) != {"bytes", "sha256"}
                    or isinstance(file_receipt["bytes"], bool)
                    or not isinstance(file_receipt["bytes"], int)
                    or file_receipt["bytes"] < 0
                    or not _digest(file_receipt["sha256"])
                ):
                    raise HarnessError("resident artifact file inventory is malformed")
        artifacts[endpoint_name] = artifact

    before = result.get("before")
    after = result.get("after")
    if not isinstance(before, dict) or not isinstance(after, dict):
        raise HarnessError("resident before/after evidence is malformed")
    if before.get("runtime_identity") != after.get("runtime_identity"):
        raise HarnessError("resident runtime identity changed during qualification")
    identities = before.get("runtime_identity")
    if not isinstance(identities, list) or len(identities) != 2:
        raise HarnessError("resident runtime identity set differs")
    from . import qualification as registered

    expected_ids = {
        "resident_gemma": next(
            row["id"] for row in registered.RESIDENTS if row["name"] == "vllm-gemma4"
        ),
        "resident_qwen": next(
            row["id"] for row in registered.RESIDENTS if row["name"] == "vllm-qwen"
        ),
    }
    identity_by_id = {
        identity.get("id"): identity for identity in identities if isinstance(identity, dict)
    }
    if set(identity_by_id) != set(expected_ids.values()):
        raise HarnessError("resident runtime IDs differ from the registered endpoints")
    runtime_by_endpoint = {}
    for endpoint_name, expected_id in expected_ids.items():
        identity = identity_by_id[expected_id]
        if not isinstance(identity, dict) or identity.get("running") is not True:
            raise HarnessError("resident runtime was not continuously available")
        runtime_by_endpoint[endpoint_name] = _qualification_runtime_sha256(
            image_id=identity.get("image"),
            command_sha256=identity.get("command_sha256"),
        )

    rows = result.get("results")
    expected = [
        ("resident_gemma", "literal", "RESIDENT_OK_17"),
        ("resident_gemma", "arithmetic", "703"),
        ("resident_qwen", "literal", "RESIDENT_OK_17"),
        ("resident_qwen", "arithmetic", "703"),
    ]
    if not isinstance(rows, list) or len(rows) != len(expected):
        raise HarnessError("resident qualification probe count differs")
    for row, (endpoint_name, probe, expected_content) in zip(rows, expected, strict=True):
        response = row.get("response") if isinstance(row, dict) else None
        endpoint = response.get("endpoint") if isinstance(response, dict) else None
        if (
            row.get("endpoint") != endpoint_name
            or row.get("probe") != probe
            or row.get("passed") is not True
            or not isinstance(response, dict)
            or str(response.get("content", "")).strip() != expected_content
            or response.get("tool_calls") != []
            or response.get("finish_reason") != "stop"
            or not isinstance(endpoint, dict)
            or endpoint.get("name") != endpoint_name
            or endpoint.get("artifact_sha256") != artifacts[endpoint_name]
            or endpoint.get("served_model") != response.get("response_model")
            or not _digest(response.get("request_sha256"))
            or not _digest(response.get("response_stream_sha256"))
        ):
            raise HarnessError(f"resident qualification probe {endpoint_name}/{probe} differs")

    failures = []
    if result.get("status") != "passed":
        failures.append(f"status={result.get('status')!r}")
    if result.get("weekly_budget_debit") is not False:
        failures.append("weekly maintenance budget was debited")
    if result.get("production_change_authorized") is not False:
        failures.append("resident qualification claims production authority")
    if before.get("queues") != after.get("queues"):
        failures.append("resident queue state changed during qualification")
    for snapshot_name, snapshot in (("before", before), ("after", after)):
        memory = _finite_number(
            snapshot.get("mem_available_gib"),
            f"resident {snapshot_name} MemAvailable",
        )
        if memory < 30:
            failures.append(f"resident {snapshot_name} MemAvailable is below 30 GiB")
    _finite_number(result.get("elapsed_s"), "resident qualification elapsed_s")
    summary = {
        "schema_version": "flash-next-qualification-validation/v1",
        "cohort": "resident",
        "status": result.get("status"),
        "admission_eligible": not failures,
        "admission_failures": failures,
        "qualification_receipt_sha256": receipt_sha256,
        "artifact_inventory_sha256": inventory_sha256,
        "artifact_sha256_by_endpoint": artifacts,
        "runtime_sha256_by_endpoint": runtime_by_endpoint,
        "probe_count": len(rows),
        "probe_scope": "fixed_literal_and_arithmetic_only",
        "paid_api_calls": "not_recorded_by_resident_v1",
        "receipt_path": str(receipt_file),
        "artifact_inventory_path": str(inventory_file),
    }
    if require_passed and failures:
        raise HarnessError("resident qualification is not admissible: " + "; ".join(failures))
    return summary


def validate_qualification_receipt(
    evaluation_plan: dict[str, Any],
    cohort: str,
    *,
    receipt_path: str | Path,
    qualification_plan_path: str | Path | None = None,
    contract_snapshot_path: str | Path | None = None,
    contract_raw_path: str | Path | None = None,
    resident_artifacts_path: str | Path | None = None,
) -> dict[str, Any]:
    """Cross-bind an admissible qualification bundle to one evaluation arm."""
    validate_plan(evaluation_plan)
    if cohort not in {"resident", "flash"}:
        raise HarnessError("cohort must be resident or flash")
    arm = _arm(evaluation_plan, cohort)
    routes = {route["role"]: route for route in arm["routes"]}
    if cohort == "flash":
        if qualification_plan_path is None or contract_snapshot_path is None:
            raise HarnessError("Flash admission requires qualification plan and contract files")
        summary = validate_flash_qualification_files(
            receipt_path,
            qualification_plan_path,
            contract_snapshot_path,
            contract_raw_path=contract_raw_path,
            require_passed=True,
        )
        if summary["qualification_receipt_sha256"] != arm["qualification_receipt_sha256"]:
            raise HarnessError("Flash arm does not bind the qualification result file")
        for route in routes.values():
            if (
                route["served_model"] != summary["served_model"]
                or route["artifact_sha256"] != summary["model_artifact_sha256"]
                or route["runtime_sha256"] != summary["runtime_sha256"]
            ):
                raise HarnessError("Flash route differs from the qualified runtime")
        return summary

    if resident_artifacts_path is None:
        raise HarnessError("resident admission requires the artifact inventory")
    summary = validate_resident_qualification_files(
        receipt_path,
        resident_artifacts_path,
        require_passed=True,
    )
    if summary["qualification_receipt_sha256"] != arm["qualification_receipt_sha256"]:
        raise HarnessError("resident arm does not bind the qualification result file")
    endpoint_by_role = {
        role: "resident_qwen" if role == "critic" else "resident_gemma"
        for role in routes
    }
    for role, route in routes.items():
        endpoint_name = endpoint_by_role[role]
        if (
            route["endpoint_name"] != endpoint_name
            or route["artifact_sha256"]
            != summary["artifact_sha256_by_endpoint"][endpoint_name]
            or route["runtime_sha256"]
            != summary["runtime_sha256_by_endpoint"][endpoint_name]
        ):
            raise HarnessError("resident route differs from the qualified runtime")
    return summary


def _output_dir(path: str | Path) -> Path:
    output = Path(path).expanduser().resolve()
    if output == REPO_ROOT or REPO_ROOT in output.parents:
        raise HarnessError("evaluation output must be outside the source worktree")
    if output.exists():
        raise FileExistsError("evaluation output directory already exists")
    return output


def _write_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(canonical_json(value) + b"\n")
    temporary.replace(path)


def _write_private_bytes(path: Path, raw: bytes, *, max_bytes: int) -> None:
    if len(raw) > max_bytes:
        raise HarnessError(f"private evidence exceeds {max_bytes} bytes")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise HarnessError("private evidence write made no progress")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)


def _private_response(value: Any, *, returned: dict[str, Any] | None) -> dict[str, Any]:
    expected = {
        "content",
        "reasoning_content",
        "tool_calls",
        "response_id",
        "response_model",
        "finish_reason",
        "usage",
        "stream_events",
        "response_bytes",
        "response_stream_sha256",
        "raw_response_stream",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise HarnessError("transport private response evidence is malformed")
    raw_stream = value["raw_response_stream"]
    if not isinstance(raw_stream, bytes) or len(raw_stream) > MAX_RESPONSE_BYTES:
        raise HarnessError("transport private response stream is malformed")
    if value["response_bytes"] != len(raw_stream):
        raise HarnessError("private response byte count differs")
    if value["response_stream_sha256"] != hashlib.sha256(raw_stream).hexdigest():
        raise HarnessError("private response stream digest differs")
    if not isinstance(value["content"], str) or not isinstance(
        value["reasoning_content"], str
    ):
        raise HarnessError("private response text channels are malformed")
    if not isinstance(value["tool_calls"], list):
        raise HarnessError("private response tool channel is malformed")
    if returned is not None:
        for key in (
            "content",
            "reasoning_content",
            "tool_calls",
            "response_id",
            "response_model",
            "finish_reason",
            "usage",
            "response_stream_sha256",
        ):
            if value[key] != returned[key]:
                raise HarnessError(f"private response {key} differs from transport result")
    return copy.deepcopy(value)


def _persist_private_call(
    output: Path,
    *,
    ordinal: int,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    private = output / "private"
    private.mkdir(mode=0o700, exist_ok=True)
    private.chmod(0o700)
    identity = hashlib.sha256(evidence["call_id"].encode()).hexdigest()[:16]
    stem = f"{ordinal:04d}-{identity}"
    raw_stream = evidence.pop("_raw_response_stream")
    raw_descriptor = None
    if raw_stream is not None:
        raw_path = private / "streams" / f"{stem}.sse"
        _write_private_bytes(raw_path, raw_stream, max_bytes=MAX_RESPONSE_BYTES)
        raw_descriptor = {
            "path": raw_path.relative_to(output).as_posix(),
            "sha256": hashlib.sha256(raw_stream).hexdigest(),
            "bytes": len(raw_stream),
        }
    evidence["response"]["raw_stream_artifact"] = raw_descriptor
    metadata_raw = canonical_json(evidence) + b"\n"
    metadata_path = private / "calls" / f"{stem}.json"
    _write_private_bytes(
        metadata_path,
        metadata_raw,
        max_bytes=MAX_PRIVATE_METADATA_BYTES,
    )
    return {
        "call_id": evidence["call_id"],
        "status": evidence["status"],
        "metadata_path": metadata_path.relative_to(output).as_posix(),
        "metadata_sha256": hashlib.sha256(metadata_raw).hexdigest(),
        "metadata_bytes": len(metadata_raw),
        "raw_stream": raw_descriptor,
    }


def _arm(plan: dict[str, Any], cohort: str) -> dict[str, Any]:
    try:
        return next(arm for arm in plan["arms"] if arm["cohort"] == cohort)
    except StopIteration as exc:
        raise HarnessError(f"plan has no {cohort!r} arm") from exc


def _route(arm: dict[str, Any], role: str) -> dict[str, Any]:
    try:
        return next(route for route in arm["routes"] if route["role"] == role)
    except StopIteration as exc:
        raise HarnessError(f"arm has no route for role {role!r}") from exc


def _reload_definitions(plan: dict[str, Any]) -> dict[str, CellDefinition]:
    families = []
    for cell_id in plan["declared_cells"]:
        family = plan["cell_receipts"][cell_id]["family"]
        if family not in families:
            families.append(family)
    available = {cell.cell_id: cell for cell in load_cells(families=families)}
    result = {}
    for cell_id in plan["declared_cells"]:
        cell = available.get(cell_id)
        if cell is None:
            raise HarnessError(f"declared cell is unavailable: {cell_id}")
        if cell.receipt() != plan["cell_receipts"][cell_id]:
            raise HarnessError(f"source, adapter, grader, or call plan drift: {cell_id}")
        result[cell_id] = cell
    expected_sources: dict[tuple[str, str], dict[str, Any]] = {}
    expected_adapters: dict[tuple[str, str], dict[str, Any]] = {}
    for cell in result.values():
        source = {
            key: cell.source[key]
            for key in ("family", "suite_id", "manifest_path", "manifest_sha256")
        }
        expected_sources[(source["family"], source["manifest_path"])] = source
        adapter = dict(cell.adapter)
        expected_adapters[(adapter["id"], adapter["source_path"])] = adapter
    for adapter_id, source_path in (
        ("flash-next-plan/v1", "bench/flash_next_ab/manifest.py"),
        ("flash-next-harness/v1", "bench/flash_next_ab/harness.py"),
        ("flash-next-transport/v1", "bench/flash_next_ab/transport.py"),
    ):
        expected_adapters[(adapter_id, source_path)] = {
            "id": adapter_id,
            "source_path": source_path,
            "source_sha256": sha256_file(REPO_ROOT / source_path),
        }
    if list(expected_sources.values()) != plan["sources"]:
        raise HarnessError("plan source bundle drifted")
    if list(expected_adapters.values()) != plan["adapter_bundle"]:
        raise HarnessError("plan adapter bundle drifted")
    return result


def _usage(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return copy.deepcopy(value)


def _call_status(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, TransportCancelled):
        return "cancelled", "transport_cancelled"
    if isinstance(exc, TimeoutError):
        return "timeout", "transport_timeout"
    if isinstance(exc, TransportError):
        return "error", "transport_error"
    return "error", "invoke_error"


def _validate_transport_result(
    result: Any,
    endpoint: LocalEndpoint,
) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise TransportError("transport result is not an object")
    for key in ("request_sha256", "response_stream_sha256"):
        if not _digest(result.get(key)):
            raise TransportError(f"transport result lacks {key}")
    if result.get("response_model") != endpoint.served_model:
        raise TransportError("transport result model differs from the route")
    if not isinstance(result.get("response_id"), str) or not result["response_id"]:
        raise TransportError("transport result lacks response id")
    if not isinstance(result.get("content"), str):
        raise TransportError("transport result lacks visible content")
    if not isinstance(result.get("reasoning_content"), str):
        raise TransportError("transport result reasoning channel is malformed")
    if not isinstance(result.get("tool_calls"), list):
        raise TransportError("transport result tool calls are malformed")
    if not isinstance(result.get("usage"), dict):
        raise TransportError("transport result usage is malformed")
    if not isinstance(result.get("finish_reason"), str):
        raise TransportError("transport result finish reason is malformed")
    try:
        _private_response(result.get("private_evidence"), returned=result)
    except HarnessError as exc:
        raise TransportError(str(exc)) from exc
    return result


def _invoke_call(
    spec: CallSpec,
    *,
    arm: dict[str, Any],
    deadline: float,
    invoke_fn: RawInvokeFn,
    cancel_event: Any,
    monotonic: Callable[[], float],
    evidence_sink: Callable[[dict[str, Any]], None],
) -> CallResult:
    if spec.messages is None:
        raise HarnessError(f"dynamic call {spec.call_id} has no rendered messages")
    route = _route(arm, spec.role)
    policies = route["policies"]
    if spec.policy_id not in policies:
        raise HarnessError(
            f"route {spec.role!r} does not define policy {spec.policy_id!r}"
        )
    policy = policies[spec.policy_id]
    remaining = deadline - monotonic()
    timeout_s = min(spec.timeout_s, remaining)
    if timeout_s <= 0:
        raise TimeoutError("run budget exhausted before call")
    endpoint = LocalEndpoint(
        route["endpoint_name"],
        _BASE_URLS[route["endpoint_name"]],
        route["served_model"],
        route["artifact_sha256"],
    )
    messages = list(spec.messages)
    tools = list(spec.tools)
    expected_body = request_body(
        endpoint,
        messages,
        policy,
        spec.max_tokens,
        spec.seed,
        tools or None,
    )
    expected_request_sha256 = hashlib.sha256(
        transport_canonical(expected_body)
    ).hexdigest()
    base = {
        "call_index": spec.call_index,
        "call_id": spec.call_id,
        "role": spec.role,
        "endpoint_name": route["endpoint_name"],
        "served_model": route["served_model"],
        "artifact_sha256": route["artifact_sha256"],
        "policy_id": spec.policy_id,
        "resolved_policy_sha256": sha256_json(policy),
        "seed": spec.seed,
        "max_tokens": spec.max_tokens,
        "timeout_s": timeout_s,
        "messages_sha256": sha256_json(messages),
        "tools_sha256": sha256_json(tools),
        "request_sha256": expected_request_sha256,
    }
    before = monotonic()
    private_response = None
    try:
        raw = invoke_fn(
            endpoint,
            messages,
            policy=copy.deepcopy(policy),
            max_tokens=spec.max_tokens,
            timeout_s=timeout_s,
            seed=spec.seed,
            tools=tools or None,
            cancel_event=cancel_event,
        )
        raw = _validate_transport_result(raw, endpoint)
        if raw["request_sha256"] != expected_request_sha256:
            raise TransportError("transport request receipt differs from rendered request")
    except Exception as exc:  # noqa: BLE001 - each call becomes a denominator receipt
        status, failure_code = _call_status(exc)
        attached = getattr(exc, "private_evidence", None)
        if attached is not None:
            private_response = _private_response(attached, returned=None)
        receipt = {
            **base,
            "status": status,
            "wall_s": max(0.0, monotonic() - before),
            "response_stream_sha256": None,
            "response_id": None,
            "response_model": None,
            "finish_reason": None,
            "usage": None,
            "failure_code": failure_code,
            "error": f"{type(exc).__name__}: {exc}",
        }
        evidence_sink(
            {
                "schema_version": PRIVATE_CALL_SCHEMA,
                "call_id": spec.call_id,
                "call_index": spec.call_index,
                "role": spec.role,
                "status": status,
                "request": {
                    "endpoint_name": route["endpoint_name"],
                    "served_model": route["served_model"],
                    "artifact_sha256": route["artifact_sha256"],
                    "policy_id": spec.policy_id,
                    "resolved_policy": copy.deepcopy(policy),
                    "seed": spec.seed,
                    "max_tokens": spec.max_tokens,
                    "timeout_s": timeout_s,
                    "messages": copy.deepcopy(messages),
                    "tools": copy.deepcopy(tools),
                    "request_sha256": expected_request_sha256,
                },
                "response": {
                    "content": private_response["content"] if private_response else None,
                    "reasoning_content": (
                        private_response["reasoning_content"] if private_response else None
                    ),
                    "tool_calls": private_response["tool_calls"] if private_response else [],
                    "response_id": private_response["response_id"] if private_response else None,
                    "response_model": (
                        private_response["response_model"] if private_response else None
                    ),
                    "finish_reason": (
                        private_response["finish_reason"] if private_response else None
                    ),
                    "usage": private_response["usage"] if private_response else None,
                    "response_stream_sha256": (
                        private_response["response_stream_sha256"]
                        if private_response
                        else None
                    ),
                },
                "failure_code": failure_code,
                "error": receipt["error"],
                "_raw_response_stream": (
                    private_response["raw_response_stream"] if private_response else None
                ),
            }
        )
        return CallResult(spec, status, None, (), receipt)
    private_response = _private_response(raw["private_evidence"], returned=raw)
    receipt = {
        **base,
        "status": "returned",
        "wall_s": max(0.0, monotonic() - before),
        "response_stream_sha256": raw["response_stream_sha256"],
        "response_id": raw["response_id"],
        "response_model": raw["response_model"],
        "finish_reason": raw["finish_reason"],
        "usage": _usage(raw["usage"]),
        "failure_code": None,
        "error": None,
    }
    evidence_sink(
        {
            "schema_version": PRIVATE_CALL_SCHEMA,
            "call_id": spec.call_id,
            "call_index": spec.call_index,
            "role": spec.role,
            "status": "returned",
            "request": {
                "endpoint_name": route["endpoint_name"],
                "served_model": route["served_model"],
                "artifact_sha256": route["artifact_sha256"],
                "policy_id": spec.policy_id,
                "resolved_policy": copy.deepcopy(policy),
                "seed": spec.seed,
                "max_tokens": spec.max_tokens,
                "timeout_s": timeout_s,
                "messages": copy.deepcopy(messages),
                "tools": copy.deepcopy(tools),
                "request_sha256": expected_request_sha256,
            },
            "response": {
                "content": private_response["content"],
                "reasoning_content": private_response["reasoning_content"],
                "tool_calls": private_response["tool_calls"],
                "response_id": private_response["response_id"],
                "response_model": private_response["response_model"],
                "finish_reason": private_response["finish_reason"],
                "usage": private_response["usage"],
                "response_stream_sha256": private_response[
                    "response_stream_sha256"
                ],
            },
            "failure_code": None,
            "error": None,
            "_raw_response_stream": private_response["raw_response_stream"],
        }
    )
    return CallResult(
        spec,
        "returned",
        raw["content"],
        tuple(copy.deepcopy(raw["tool_calls"])),
        receipt,
    )


def _outcome_status(calls: list[CallResult], *, adapter_error: bool) -> str:
    if not calls:
        return "not_run"
    statuses = {call.status for call in calls}
    if "cancelled" in statuses:
        return "cancelled"
    if "timeout" in statuses:
        return "timeout"
    if "error" in statuses or adapter_error:
        return "error"
    return "returned"


def _not_run_outcome(
    cell: CellDefinition,
    cohort: str,
    *,
    failure_code: str,
    error: str,
) -> dict[str, Any]:
    return {
        "cell_id": cell.cell_id,
        "cohort": cohort,
        "task_id": cell.task_id,
        "family": cell.family,
        "condition": cell.condition,
        "seed": cell.seed,
        "status": "not_run",
        "passed": False,
        "wall_s": 0.0,
        "source": copy.deepcopy(cell.source),
        "adapter": copy.deepcopy(cell.adapter),
        "grader": copy.deepcopy(cell.grader),
        "calls": [],
        "grade": {
            "grader_id": cell.grader["id"],
            "passed": False,
            "failure_code": failure_code,
            "details": {},
        },
        "failure_code": failure_code,
        "error": error,
    }


def _execute_outcome(
    cell: CellDefinition,
    cohort: str,
    *,
    arm: dict[str, Any],
    deadline: float,
    invoke_fn: RawInvokeFn,
    cancel_event: Any,
    monotonic: Callable[[], float],
    persist_evidence: Callable[[CellDefinition, dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    start = monotonic()
    observed: list[CallResult] = []
    private_calls: list[dict[str, Any]] = []

    def invoke(spec: CallSpec) -> CallResult:
        result = _invoke_call(
            spec,
            arm=arm,
            deadline=deadline,
            invoke_fn=invoke_fn,
            cancel_event=cancel_event,
            monotonic=monotonic,
            evidence_sink=private_calls.append,
        )
        observed.append(result)
        return result

    adapter_error = False
    try:
        result = execute_cell(cell, invoke)
        if list(result.calls) != observed:
            raise HarnessError("adapter call receipt sequence differs from invocation order")
    except Exception as exc:  # noqa: BLE001 - grader faults remain explicit outcomes
        adapter_error = True
        result = AdapterResult(
            tuple(observed),
            False,
            "grader_error",
            {"exception_type": type(exc).__name__},
        )
        error = f"{type(exc).__name__}: {exc}"
    else:
        error = None
    if len(private_calls) != len(observed):
        raise HarnessError("private evidence sequence differs from invoked calls")
    for private, call in zip(private_calls, observed, strict=True):
        if private["call_id"] != call.spec.call_id or private["status"] != call.status:
            raise HarnessError("private evidence identity differs from its call receipt")
    private_index = [persist_evidence(cell, private) for private in private_calls]
    status = _outcome_status(observed, adapter_error=adapter_error)
    passed = bool(result.passed and status == "returned")
    failure_code = None if passed else (result.failure_code or f"outcome_{status}")
    if status != "returned" and error is None:
        error = next(
            (call.receipt["error"] for call in observed if call.status != "returned"),
            status,
        )
    grade_details = copy.deepcopy(result.details)
    if "_private_call_evidence" in grade_details:
        raise HarnessError("adapter details collide with the private evidence namespace")
    grade_details["_private_call_evidence"] = {
        "schema_version": PRIVATE_INDEX_SCHEMA,
        "artifacts": private_index,
    }
    return {
        "cell_id": cell.cell_id,
        "cohort": cohort,
        "task_id": cell.task_id,
        "family": cell.family,
        "condition": cell.condition,
        "seed": cell.seed,
        "status": status,
        "passed": passed,
        "wall_s": max(0.0, monotonic() - start),
        "source": copy.deepcopy(cell.source),
        "adapter": copy.deepcopy(cell.adapter),
        "grader": copy.deepcopy(cell.grader),
        "calls": [copy.deepcopy(call.receipt) for call in observed],
        "grade": {
            "grader_id": cell.grader["id"],
            "passed": passed,
            "failure_code": failure_code,
            "details": grade_details,
        },
        "failure_code": failure_code,
        "error": error,
    }


def run_harness(
    plan: dict[str, Any],
    *,
    cohort: str,
    output_dir: str | Path,
    runtime_budget_s: float,
    qualification_gate: QualificationGate,
    invoke_fn: RawInvokeFn = complete,
    cancel_event: Any = None,
    monotonic: Callable[[], float] = time.monotonic,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Run every declared cell serially and preserve failures in denominators.

    ``qualification_gate`` must validate the external runtime receipt before
    this function creates an output directory or invokes an endpoint.
    """
    validate_plan(plan)
    if cohort not in {"resident", "flash"}:
        raise HarnessError("cohort must be resident or flash")
    if (
        isinstance(runtime_budget_s, bool)
        or not isinstance(runtime_budget_s, (int, float))
        or not math.isfinite(float(runtime_budget_s))
        or not 0 < float(runtime_budget_s) <= MAX_RUNTIME_BUDGET_S
    ):
        raise HarnessError("runtime budget is outside the bounded positive range")
    if not callable(qualification_gate):
        raise HarnessError("a qualification receipt gate is required")
    if not callable(invoke_fn):
        raise HarnessError("invoke_fn must be callable")
    if cancel_event is not None and not callable(getattr(cancel_event, "is_set", None)):
        raise HarnessError("cancel_event must expose is_set()")
    # Fail before filesystem writes and before any model request.
    qualification_gate(plan, cohort)
    definitions = _reload_definitions(plan)
    output = _output_dir(output_dir)
    output.mkdir(parents=True)
    arm = _arm(plan, cohort)
    fingerprints = plan_fingerprints(plan)
    manifest_sha256 = sha256_json(plan)
    run_id = run_id or f"flash-next-ab-{cohort}-{uuid.uuid4()}"
    if not isinstance(run_id, str) or not run_id.strip():
        raise HarnessError("run_id must be non-empty")
    start = monotonic()
    deadline = start + float(runtime_budget_s)
    outcomes: list[dict[str, Any]] = []
    aborted = False
    evidence_ordinal = 0

    def persist_evidence(
        cell: CellDefinition,
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        nonlocal evidence_ordinal
        complete_evidence = {
            "schema_version": evidence.pop("schema_version"),
            "run_id": run_id,
            "cohort": cohort,
            "cell_id": cell.cell_id,
            **evidence,
        }
        descriptor = _persist_private_call(
            output,
            ordinal=evidence_ordinal,
            evidence=complete_evidence,
        )
        evidence_ordinal += 1
        return descriptor

    def checkpoint() -> None:
        _write_json(
            output / "checkpoint.json",
            {
                "schema_version": CHECKPOINT_SCHEMA,
                "run_id": run_id,
                "cohort": cohort,
                "manifest_sha256": manifest_sha256,
                "recorded_cells": [row["cell_id"] for row in outcomes],
                "elapsed_s": max(0.0, monotonic() - start),
                "promotion_authorized": False,
            },
        )

    checkpoint()
    for index, cell_id in enumerate(plan["declared_cells"]):
        cell = definitions[cell_id]
        cancelled = cancel_event is not None and bool(cancel_event.is_set())
        if aborted or cancelled or monotonic() >= deadline:
            aborted = True
            reason = "cancelled_before_call" if cancelled else "runtime_budget_exhausted"
            outcomes.append(
                _not_run_outcome(cell, cohort, failure_code=reason, error=reason)
            )
            checkpoint()
            continue
        outcome = _execute_outcome(
            cell,
            cohort,
            arm=arm,
            deadline=deadline,
            invoke_fn=invoke_fn,
            cancel_event=cancel_event,
            monotonic=monotonic,
            persist_evidence=persist_evidence,
        )
        outcomes.append(outcome)
        if outcome["status"] == "cancelled":
            aborted = True
        checkpoint()

    if any(row["status"] == "not_run" for row in outcomes):
        aborted = True
    result = {
        "schema_version": RUN_SCHEMA,
        "run_id": run_id,
        "cohort": cohort,
        "status": "aborted" if aborted else "complete",
        "manifest_sha256": manifest_sha256,
        "plan": copy.deepcopy(plan),
        "plan_fingerprints": fingerprints,
        "arms": copy.deepcopy(plan["arms"]),
        "declared_cells": list(plan["declared_cells"]),
        "elapsed_s": max(0.0, monotonic() - start),
        "outcomes": outcomes,
        "promotion_authorized": False,
    }
    _write_json(output / "run.json", result)
    (output / "checkpoint.json").unlink(missing_ok=True)
    return result


__all__ = [
    "CHECKPOINT_SCHEMA",
    "MAX_RUNTIME_BUDGET_S",
    "PRIVATE_CALL_SCHEMA",
    "PRIVATE_INDEX_SCHEMA",
    "HarnessError",
    "run_harness",
    "validate_flash_qualification_files",
    "validate_qualification_receipt",
    "validate_resident_qualification_files",
]
