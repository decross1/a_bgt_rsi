"""Frozen, bounded harness hook for a qualified Flash-Next runtime window.

This module does not launch, stop, or restore a model.  The qualification
controller owns that lifecycle and calls :func:`run_flash_after_probes` while
its canonical resource lease and continuous safety monitor are still active.
The hook accepts only a hash-bound external window plan and invokes the shared
Python harness directly; it never accepts a shell command or remote endpoint.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .compare import validate_run
from .harness import (
    MAX_RUNTIME_BUDGET_S,
    HarnessError,
    run_harness,
    validate_qualification_receipt,
)
from .harness import _read_regular_file as _harness_read_regular_file
from .manifest import validate_plan

RESEARCH_ROOT = Path(
    "/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-14/"
    "qwen-flash-next-research"
)
WINDOW_PLAN_ROOT = RESEARCH_ROOT / "evaluation" / "window-plans"
WINDOW_RUN_ROOT = RESEARCH_ROOT / "evaluation" / "runs"
QUALIFICATION_ROOT = RESEARCH_ROOT / "qualification-runs"
RUNTIME_ROOT = RESEARCH_ROOT / "runtime"
RESEARCH_LEDGER = RUNTIME_ROOT / "research-usage.jsonl"
RESIDENT_QUALIFICATION = RUNTIME_ROOT / "resident-qualification-v2.json"
RESIDENT_ARTIFACTS = RUNTIME_ROOT / "resident-model-artifacts.json"

WINDOW_SCHEMA = "flash-next-evaluation-window/v1"
EXTENDED_PLAN_SCHEMA = "flash-next-extended-evaluation-plan/v1"
ATTEMPT_SCHEMA = "flash-next-extended-evaluation-harness-attempt/v1"
RESULT_SCHEMA = "flash-next-extended-evaluation-result/v1"
FULL_COHORT_BUDGET_SECONDS = MAX_RUNTIME_BUDGET_S
WINDOW_DEADLINE_SECONDS = 14_400
RESTORATION_RESERVE_SECONDS = 600
MIN_POST_HARNESS_HEADROOM_SECONDS = 60
MIN_MEMORY_GIB = 20
MAX_WINDOW_PLAN_BYTES = 2 * 1024 * 1024
MAX_BENCHMARK_PLAN_BYTES = 8 * 1024 * 1024
MAX_EVIDENCE_BYTES = 8 * 1024 * 1024

WINDOW_KEYS = frozenset(
    {
        "schema_version",
        "pair_id",
        "cohort",
        "benchmark",
        "qualification",
        "safety",
        "accounting",
        "promotion_authorized",
    }
)
BENCHMARK_KEYS = frozenset(
    {"plan_path", "plan_file_sha256", "runtime_budget_seconds"}
)
QUALIFICATION_KEYS = frozenset(
    {
        "receipt",
        "qualification_plan",
        "contract_snapshot",
        "contract_raw",
        "resident_artifacts",
    }
)
SAFETY_KEYS = frozenset(
    {
        "window_deadline_seconds",
        "restoration_reserve_seconds",
        "min_mem_available_gib",
        "memory_poll_seconds",
    }
)
ACCOUNTING_KEYS = frozenset(
    {"class", "weekly_budget_debit", "paid_api_allowed", "journal_path"}
)
REFERENCE_KEYS = frozenset({"path", "sha256"})
EXTENDED_PLAN_KEYS = frozenset(
    {
        "schema_version",
        "pair_id",
        "cohort",
        "output_dir",
        "window_plan_path",
        "window_plan_sha256",
        "benchmark_plan_path",
        "benchmark_plan_file_sha256",
        "prior_qualification_receipt_sha256",
        "prior_qualification_plan_sha256",
        "contract_sha256",
        "runtime_sha256",
        "model_artifact_sha256",
        "served_model",
        "image_id",
        "docker_create_argv",
        "docker_create_argv_sha256",
        "probe_set",
        "effective_invocation_deadline_seconds",
        "work_cutoff_seconds",
        "benchmark_runtime_budget_seconds",
        "restoration_reserve_seconds",
        "setup_quiescence_seconds",
        "min_mem_available_gib",
        "resource_locks",
        "research_usage_journal",
        "weekly_budget_debit",
        "paid_api_allowed",
        "production_change_authorized",
    }
)


class EvaluationWindowError(RuntimeError):
    """The frozen window cannot be admitted or completed."""


@dataclass(frozen=True)
class FrozenEvaluationWindow:
    """Fully validated external inputs for one cohort window."""

    document: dict[str, Any]
    source_path: Path
    source_sha256: str
    benchmark_plan: dict[str, Any]
    benchmark_plan_file_sha256: str
    qualification_summary: dict[str, Any]
    qualification_plan: dict[str, Any] | None

    @property
    def pair_id(self) -> str:
        return self.document["pair_id"]

    @property
    def cohort(self) -> str:
        return self.document["cohort"]

    @property
    def runtime_budget_seconds(self) -> int:
        return self.document["benchmark"]["runtime_budget_seconds"]

    @property
    def effective_deadline_seconds(self) -> int:
        return self.document["safety"]["window_deadline_seconds"]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _digest(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _exact_keys(value: Any, expected: frozenset[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise EvaluationWindowError(f"{label} fields differ from the frozen schema")
    return value


def _bounded_int(value: Any, label: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise EvaluationWindowError(f"{label} must be an integer in {low}..{high}")
    return value


def _strict_object(raw: bytes, label: str) -> dict[str, Any]:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise EvaluationWindowError(f"duplicate JSON key in {label}: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw,
            object_pairs_hook=unique,
            parse_constant=lambda item: (_ for _ in ()).throw(
                EvaluationWindowError(f"non-finite JSON in {label}: {item}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvaluationWindowError(f"invalid JSON in {label}") from exc
    if not isinstance(value, dict):
        raise EvaluationWindowError(f"{label} must contain a JSON object")
    return value


def _regular_bytes(path: str | Path, *, label: str, max_bytes: int) -> tuple[bytes, Path]:
    try:
        return _harness_read_regular_file(path, label=label, max_bytes=max_bytes)
    except HarnessError as exc:
        raise EvaluationWindowError(str(exc)) from exc


def _read_reference(
    value: Any,
    *,
    label: str,
    expected_path: Path,
    max_bytes: int = MAX_EVIDENCE_BYTES,
) -> tuple[dict[str, Any], bytes, Path]:
    reference = _exact_keys(value, REFERENCE_KEYS, label)
    if not _digest(reference["sha256"]):
        raise EvaluationWindowError(f"{label}.sha256 is malformed")
    raw, path = _regular_bytes(reference["path"], label=label, max_bytes=max_bytes)
    if path != expected_path or _sha256(raw) != reference["sha256"]:
        raise EvaluationWindowError(f"{label} path or content hash differs")
    return _strict_object(raw, label), raw, path


def _none_reference(value: Any, label: str) -> None:
    if value is not None:
        raise EvaluationWindowError(f"{label} must be null for this cohort")


def _qualification_paths(
    pair_id: str,
    cohort: str,
    qualification: dict[str, Any],
) -> tuple[dict[str, Path | None], dict[str, str]]:
    del pair_id  # reserved for a future paired receipt namespace
    paths: dict[str, Path | None] = {}
    hashes: dict[str, str] = {}
    if cohort == "flash":
        receipt_ref = _exact_keys(qualification["receipt"], REFERENCE_KEYS, "receipt")
        receipt = Path(os.path.abspath(Path(receipt_ref["path"])))
        if (
            receipt.name != "result.json"
            or receipt.parent.parent != QUALIFICATION_ROOT
            or not re.fullmatch(r"qfn-c0-[A-Za-z0-9][A-Za-z0-9._-]{0,79}", receipt.parent.name)
        ):
            raise EvaluationWindowError("Flash qualification result path is outside the run root")
        expected = {
            "receipt": receipt,
            "qualification_plan": receipt.parent / "plan.json",
            "contract_snapshot": receipt.parent / "launch-contract.snapshot.json",
            "contract_raw": receipt.parent / "launch-contract.raw.json",
        }
        for name, expected_path in expected.items():
            _, raw, path = _read_reference(
                qualification[name], label=f"qualification.{name}", expected_path=expected_path
            )
            paths[name] = path
            hashes[name] = _sha256(raw)
        _none_reference(qualification["resident_artifacts"], "qualification.resident_artifacts")
        paths["resident_artifacts"] = None
        return paths, hashes

    expected = {
        "receipt": RESIDENT_QUALIFICATION,
        "resident_artifacts": RESIDENT_ARTIFACTS,
    }
    for name, expected_path in expected.items():
        _, raw, path = _read_reference(
            qualification[name], label=f"qualification.{name}", expected_path=expected_path
        )
        paths[name] = path
        hashes[name] = _sha256(raw)
    for name in ("qualification_plan", "contract_snapshot", "contract_raw"):
        _none_reference(qualification[name], f"qualification.{name}")
        paths[name] = None
    return paths, hashes


def load_evaluation_window(
    path: str | Path, *, expected_cohort: str | None = None
) -> FrozenEvaluationWindow:
    """Load, hash, and cross-bind every input before a runtime mutation."""
    raw, source = _regular_bytes(
        path, label="evaluation window plan", max_bytes=MAX_WINDOW_PLAN_BYTES
    )
    document = _exact_keys(_strict_object(raw, "evaluation window plan"), WINDOW_KEYS, "window")
    pair_id = document["pair_id"]
    cohort = document["cohort"]
    if not isinstance(pair_id, str) or not re.fullmatch(
        r"qfn-ab-[a-z0-9][a-z0-9._-]{0,63}", pair_id
    ):
        raise EvaluationWindowError("pair_id is outside the registered namespace")
    if cohort not in {"resident", "flash"} or (
        expected_cohort is not None and cohort != expected_cohort
    ):
        raise EvaluationWindowError("evaluation cohort differs from the requested window")
    expected_source = WINDOW_PLAN_ROOT / f"{pair_id}.{cohort}.window.json"
    if source != expected_source:
        raise EvaluationWindowError("evaluation window plan path is not registered")
    if document["schema_version"] != WINDOW_SCHEMA:
        raise EvaluationWindowError("unsupported evaluation window schema")
    if document["promotion_authorized"] is not False:
        raise EvaluationWindowError("an evaluation window cannot authorize promotion")

    benchmark = _exact_keys(document["benchmark"], BENCHMARK_KEYS, "benchmark")
    budget = _bounded_int(
        benchmark["runtime_budget_seconds"],
        "benchmark.runtime_budget_seconds",
        1,
        FULL_COHORT_BUDGET_SECONDS,
    )
    if budget != FULL_COHORT_BUDGET_SECONDS:
        raise EvaluationWindowError("the full frozen cohort must retain its complete runtime cap")
    benchmark_path = WINDOW_PLAN_ROOT / f"{pair_id}.benchmark.json"
    benchmark_plan, benchmark_raw, _ = _read_reference(
        {"path": benchmark["plan_path"], "sha256": benchmark["plan_file_sha256"]},
        label="benchmark plan",
        expected_path=benchmark_path,
        max_bytes=MAX_BENCHMARK_PLAN_BYTES,
    )
    try:
        validate_plan(benchmark_plan)
    except Exception as exc:
        raise EvaluationWindowError(f"benchmark plan is invalid: {exc}") from exc

    safety = _exact_keys(document["safety"], SAFETY_KEYS, "safety")
    if safety != {
        "window_deadline_seconds": WINDOW_DEADLINE_SECONDS,
        "restoration_reserve_seconds": RESTORATION_RESERVE_SECONDS,
        "min_mem_available_gib": MIN_MEMORY_GIB,
        "memory_poll_seconds": 1,
    }:
        raise EvaluationWindowError("evaluation safety envelope differs from the allowlist")
    if budget + RESTORATION_RESERVE_SECONDS >= WINDOW_DEADLINE_SECONDS:
        raise EvaluationWindowError("evaluation window leaves no setup headroom")

    accounting = _exact_keys(document["accounting"], ACCOUNTING_KEYS, "accounting")
    if accounting != {
        "class": "uncapped-local-model-research",
        "weekly_budget_debit": False,
        "paid_api_allowed": False,
        "journal_path": str(RESEARCH_LEDGER),
    }:
        raise EvaluationWindowError("evaluation accounting differs from the allowlist")

    qualification = _exact_keys(
        document["qualification"], QUALIFICATION_KEYS, "qualification"
    )
    paths, _ = _qualification_paths(pair_id, cohort, qualification)
    try:
        summary = validate_qualification_receipt(
            benchmark_plan,
            cohort,
            receipt_path=paths["receipt"],
            qualification_plan_path=paths["qualification_plan"],
            contract_snapshot_path=paths["contract_snapshot"],
            contract_raw_path=paths["contract_raw"],
            resident_artifacts_path=paths["resident_artifacts"],
        )
    except HarnessError as exc:
        raise EvaluationWindowError(f"qualification evidence is inadmissible: {exc}") from exc
    qualification_plan_document = None
    if cohort == "flash":
        qualification_plan_raw, qualification_plan_path = _regular_bytes(
            paths["qualification_plan"],
            label="qualification plan",
            max_bytes=MAX_EVIDENCE_BYTES,
        )
        if qualification_plan_path != paths["qualification_plan"]:
            raise EvaluationWindowError("qualification plan path changed")
        qualification_plan_document = _strict_object(
            qualification_plan_raw, "qualification plan"
        )

    return FrozenEvaluationWindow(
        document=json.loads(json.dumps(document, allow_nan=False)),
        source_path=source,
        source_sha256=_sha256(raw),
        benchmark_plan=json.loads(json.dumps(benchmark_plan, allow_nan=False)),
        benchmark_plan_file_sha256=_sha256(benchmark_raw),
        qualification_summary=json.loads(json.dumps(summary, allow_nan=False)),
        qualification_plan=(
            json.loads(json.dumps(qualification_plan_document, allow_nan=False))
            if qualification_plan_document is not None
            else None
        ),
    )


def _evaluation_output(
    pair_id: str, path: str | Path, *, must_be_absent: bool
) -> Path:
    output = Path(os.path.abspath(Path(path)))
    expected = WINDOW_RUN_ROOT / f"{pair_id}.flash"
    if (
        WINDOW_RUN_ROOT.is_symlink()
        or not WINDOW_RUN_ROOT.is_dir()
        or WINDOW_RUN_ROOT.resolve() != WINDOW_RUN_ROOT
        or output != expected
        or output.parent != WINDOW_RUN_ROOT
    ):
        raise EvaluationWindowError("extended evaluation output path is not registered")
    if must_be_absent and output.exists():
        raise EvaluationWindowError("extended evaluation output already exists")
    if output.exists() and (
        output.is_symlink() or not output.is_dir() or output.resolve() != output
    ):
        raise EvaluationWindowError("extended evaluation output is redirected")
    return output


def build_extended_evaluation_plan(
    window: FrozenEvaluationWindow,
    output_dir: str | Path,
    *,
    must_be_absent: bool = False,
) -> dict[str, Any]:
    """Build the distinct lifecycle plan for a post-C0 Flash window."""
    if not isinstance(window, FrozenEvaluationWindow) or window.cohort != "flash":
        raise EvaluationWindowError("an extended lifecycle plan requires a Flash window")
    output = _evaluation_output(
        window.pair_id, output_dir, must_be_absent=must_be_absent
    )
    qualification_plan = window.qualification_plan
    summary = window.qualification_summary
    qualification_plan_sha256 = (
        _sha256(
            json.dumps(
                qualification_plan,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode()
        )
        if isinstance(qualification_plan, dict)
        else None
    )
    if (
        not isinstance(qualification_plan, dict)
        or qualification_plan.get("schema")
        != "qwen-flash-next-qualification-plan/v2"
        or summary.get("admission_eligible") is not True
        or not _digest(summary.get("qualification_receipt_sha256"))
        or not _digest(summary.get("qualification_plan_sha256"))
        or not _digest(summary.get("runtime_sha256"))
        or not _digest(summary.get("model_artifact_sha256"))
        or qualification_plan_sha256 != summary.get("qualification_plan_sha256")
        or qualification_plan.get("contract_sha256")
        != summary.get("contract_sha256")
        or qualification_plan.get("model_artifact_sha256")
        != summary.get("model_artifact_sha256")
        or qualification_plan.get("served_model") != summary.get("served_model")
        or qualification_plan.get("setup_quiescence_seconds") != 60
    ):
        raise EvaluationWindowError("prior C0 qualification identity is incomplete")
    docker_argv = qualification_plan.get("docker_create_argv")
    if (
        not isinstance(docker_argv, list)
        or not all(isinstance(item, str) and item for item in docker_argv)
        or qualification_plan.get("docker_create_argv_sha256")
        != _sha256(
            json.dumps(
                docker_argv,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode()
        )
    ):
        raise EvaluationWindowError("prior C0 launch vector is malformed")
    deadline = window.effective_deadline_seconds
    reserve = window.document["safety"]["restoration_reserve_seconds"]
    plan = {
        "schema_version": EXTENDED_PLAN_SCHEMA,
        "pair_id": window.pair_id,
        "cohort": "flash",
        "output_dir": str(output),
        "window_plan_path": str(window.source_path),
        "window_plan_sha256": window.source_sha256,
        "benchmark_plan_path": window.document["benchmark"]["plan_path"],
        "benchmark_plan_file_sha256": window.benchmark_plan_file_sha256,
        "prior_qualification_receipt_sha256": summary[
            "qualification_receipt_sha256"
        ],
        "prior_qualification_plan_sha256": summary[
            "qualification_plan_sha256"
        ],
        "contract_sha256": summary["contract_sha256"],
        "runtime_sha256": summary["runtime_sha256"],
        "model_artifact_sha256": summary["model_artifact_sha256"],
        "served_model": summary["served_model"],
        "image_id": qualification_plan["image_id"],
        "docker_create_argv": docker_argv,
        "docker_create_argv_sha256": qualification_plan[
            "docker_create_argv_sha256"
        ],
        "probe_set": qualification_plan["probe_set"],
        "effective_invocation_deadline_seconds": deadline,
        "work_cutoff_seconds": deadline - reserve,
        "benchmark_runtime_budget_seconds": window.runtime_budget_seconds,
        "restoration_reserve_seconds": reserve,
        "setup_quiescence_seconds": 60,
        "min_mem_available_gib": MIN_MEMORY_GIB,
        "resource_locks": [
            ".weekly-upgrade-execution.lock",
            ".coordinator-cron.lock",
            ".weekly-upgrade-gpu.lock",
        ],
        "research_usage_journal": str(RESEARCH_LEDGER),
        "weekly_budget_debit": False,
        "paid_api_allowed": False,
        "production_change_authorized": False,
    }
    _exact_keys(plan, EXTENDED_PLAN_KEYS, "extended evaluation plan")
    return json.loads(json.dumps(plan, sort_keys=True, allow_nan=False))


def extended_plan_sha256(plan: dict[str, Any]) -> str:
    _exact_keys(plan, EXTENDED_PLAN_KEYS, "extended evaluation plan")
    return _sha256(
        json.dumps(
            plan, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    )


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    raw = json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n"
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temporary.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _append_usage(row: dict[str, Any], ledger: Path | None = None) -> None:
    ledger = ledger or RESEARCH_LEDGER
    if ledger != RESEARCH_LEDGER or ledger.name == "weekly_upgrade_budget.jsonl":
        raise EvaluationWindowError("evaluation usage cannot target the weekly ledger")
    if ledger.parent.is_symlink() or not ledger.parent.is_dir():
        raise EvaluationWindowError("research ledger parent is absent or redirected")
    if ledger.exists() and (ledger.is_symlink() or not ledger.is_file()):
        raise EvaluationWindowError("research ledger is redirected")
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(ledger, flags, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        os.write(
            descriptor,
            json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
            + b"\n",
        )
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _qualification_gate(window: FrozenEvaluationWindow):
    qualification = window.document["qualification"]

    def gate(plan: dict[str, Any], cohort: str) -> None:
        if plan != window.benchmark_plan or cohort != window.cohort:
            raise HarnessError("harness input differs from the frozen evaluation window")
        paths, _ = _qualification_paths(window.pair_id, cohort, qualification)
        validate_qualification_receipt(
            plan,
            cohort,
            receipt_path=paths["receipt"],
            qualification_plan_path=paths["qualification_plan"],
            contract_snapshot_path=paths["contract_snapshot"],
            contract_raw_path=paths["contract_raw"],
            resident_artifacts_path=paths["resident_artifacts"],
        )

    return gate


def run_flash_after_probes(
    window: FrozenEvaluationWindow,
    *,
    execution_plan: dict[str, Any],
    evaluation_output: str | Path,
    work_deadline: float,
    monitor: Any,
) -> dict[str, Any]:
    """Run the harness inside a separately planned extended lifecycle window."""
    if not isinstance(window, FrozenEvaluationWindow) or window.cohort != "flash":
        raise EvaluationWindowError("the post-probe hook requires a frozen Flash window")
    if not isinstance(work_deadline, (int, float)) or not math.isfinite(work_deadline):
        raise EvaluationWindowError("work deadline is invalid")
    if not callable(getattr(monitor, "check", None)) or not callable(
        getattr(getattr(monitor, "cancel_event", None), "is_set", None)
    ):
        raise EvaluationWindowError("the qualification safety monitor is unavailable")

    # Re-read every frozen input immediately before the harness. This detects a
    # path or byte change since supervisor planning without accepting new data.
    observed = load_evaluation_window(window.source_path, expected_cohort="flash")
    if observed.source_sha256 != window.source_sha256 or observed != window:
        raise EvaluationWindowError("evaluation window changed after planning")
    output = _evaluation_output(window.pair_id, evaluation_output, must_be_absent=False)
    expected_plan = build_extended_evaluation_plan(window, output)
    if execution_plan != expected_plan:
        raise EvaluationWindowError("extended lifecycle plan changed before the harness")
    execution_plan_sha256 = extended_plan_sha256(execution_plan)
    harness_output = output / "harness"
    receipt_path = output / "harness-attempt.json"
    if harness_output.exists() or receipt_path.exists():
        raise EvaluationWindowError("evaluation output already exists")
    remaining = work_deadline - time.monotonic()
    required = window.runtime_budget_seconds + MIN_POST_HARNESS_HEADROOM_SECONDS
    if remaining < required:
        raise EvaluationWindowError("full cohort no longer fits before the restoration cutoff")
    monitor.check()
    if monitor.cancel_event.is_set():
        raise EvaluationWindowError("safety monitor canceled before the evaluation")

    started = time.monotonic()
    started_at = _utc_now()
    _append_usage(
        {
            "schema": "local-model-research-usage/v1",
            "event": "evaluation_started",
            "pair_id": window.pair_id,
            "cohort": "flash",
            "observed_at": started_at,
            "window_plan_sha256": window.source_sha256,
            "extended_plan_sha256": execution_plan_sha256,
            "benchmark_budget_seconds": window.runtime_budget_seconds,
            "weekly_budget_debit": False,
            "paid_api_calls": 0,
        }
    )
    harness_result: dict[str, Any] | None = None
    failure: BaseException | None = None
    try:
        harness_result = run_harness(
            window.benchmark_plan,
            cohort="flash",
            output_dir=harness_output,
            runtime_budget_s=window.runtime_budget_seconds,
            qualification_gate=_qualification_gate(window),
            cancel_event=monitor.cancel_event,
            run_id=f"{window.pair_id}-flash",
        )
        validate_run(harness_result, "flash")
        monitor.check()
        if harness_result.get("status") != "complete":
            raise EvaluationWindowError("the full Flash cohort did not complete")
    except BaseException as exc:  # noqa: BLE001 - controller must restore after any hook exit
        failure = exc

    elapsed = max(0.0, time.monotonic() - started)
    run_path = harness_output / "run.json"
    run_sha256 = None
    if run_path.is_file() and not run_path.is_symlink():
        run_raw, observed_path = _regular_bytes(
            run_path, label="harness run", max_bytes=MAX_EVIDENCE_BYTES
        )
        if observed_path != run_path:
            failure = failure or EvaluationWindowError("harness run path changed")
        else:
            run_sha256 = _sha256(run_raw)
    receipt = {
        "schema_version": ATTEMPT_SCHEMA,
        "pair_id": window.pair_id,
        "cohort": "flash",
        "status": (
            "harness_complete_pending_restoration"
            if failure is None
            else "harness_failed_pending_restoration"
        ),
        "evaluation_complete": False,
        "restoration_required": True,
        "window_plan_sha256": window.source_sha256,
        "extended_plan_sha256": execution_plan_sha256,
        "benchmark_plan_file_sha256": window.benchmark_plan_file_sha256,
        "qualification_receipt_sha256": window.qualification_summary[
            "qualification_receipt_sha256"
        ],
        "harness_run_path": str(run_path) if run_sha256 else None,
        "harness_run_sha256": run_sha256,
        "benchmark_budget_seconds": window.runtime_budget_seconds,
        "harness_wall_seconds": elapsed,
        "failure_type": type(failure).__name__ if failure is not None else None,
        "started_at": started_at,
        "finished_at": _utc_now(),
        "weekly_budget_debit": False,
        "paid_api_calls": 0,
        "production_change_authorized": False,
    }
    _atomic_json(receipt_path, receipt)
    _append_usage(
        {
            "schema": "local-model-research-usage/v1",
            "event": "evaluation_finished",
            "pair_id": window.pair_id,
            "cohort": "flash",
            "observed_at": receipt["finished_at"],
            "status": receipt["status"],
            "window_plan_sha256": window.source_sha256,
            "extended_plan_sha256": execution_plan_sha256,
            "harness_wall_seconds": elapsed,
            "weekly_budget_debit": False,
            "paid_api_calls": 0,
        }
    )
    if failure is not None:
        if isinstance(failure, EvaluationWindowError):
            raise failure
        raise EvaluationWindowError(
            f"Flash cohort harness failed: {type(failure).__name__}: {failure}"
        ) from failure
    return receipt


__all__ = [
    "ATTEMPT_SCHEMA",
    "EXTENDED_PLAN_SCHEMA",
    "FULL_COHORT_BUDGET_SECONDS",
    "RESULT_SCHEMA",
    "WINDOW_DEADLINE_SECONDS",
    "WINDOW_SCHEMA",
    "EvaluationWindowError",
    "FrozenEvaluationWindow",
    "build_extended_evaluation_plan",
    "extended_plan_sha256",
    "load_evaluation_window",
    "run_flash_after_probes",
]
