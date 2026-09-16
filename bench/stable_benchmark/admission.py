"""Independent admission boundary for replayed stable benchmark runs."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .manifest import LoadedDocument, canonical_json, validate_definition, validate_run_manifest
from .replay import REPLAY_SCHEMA, load_run_receipt, replay_source_hashes
from .runner import CELL_STATUSES, execution_source_hashes


ADMISSION_SCHEMA = "stable-benchmark-admission-receipt/v1"
SUPERVISOR_FINAL_SCHEMA = "stable-benchmark-supervisor-final/v1"
EXECUTION_GATE_FIELDS = {
    "admitted", "definition_sha256", "run_manifest_sha256", "route_runtime_identities",
    "endpoint_bindings_sha256", "supervision_receipt_sha256", "resource_guard_sha256",
}


class AdmissionError(ValueError):
    pass


def admission_source_hashes() -> dict[str, str]:
    root = Path(__file__).resolve().parents[2]
    files = tuple(Path(__file__).with_name(name) for name in (
        "__init__.py", "fixtures.py", "graders.py", "manifest.py", "runner.py",
        "replay.py", "admission.py",
    )) + (root / "bench/weekly_upgrade_portfolio/code_sandbox.py",)
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in files
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_regular(path: Path, limit: int) -> tuple[bytes, str]:
    target = path.absolute()
    before = target.lstat()
    if not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode) or before.st_size > limit:
        raise AdmissionError(f"unsafe or oversized admission input: {target}")
    descriptor = os.open(
        target,
        os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        observed = os.fstat(descriptor)
        if (observed.st_dev, observed.st_ino) != (before.st_dev, before.st_ino):
            raise AdmissionError("admission input identity changed during open")
        raw = b""
        while len(raw) <= limit:
            chunk = os.read(descriptor, min(65536, limit + 1 - len(raw)))
            if not chunk:
                break
            raw += chunk
    finally:
        os.close(descriptor)
    if len(raw) != before.st_size or len(raw) > limit:
        raise AdmissionError("admission input size changed or exceeded its limit")
    return raw, hashlib.sha256(raw).hexdigest()


def _decode(raw: bytes, where: str) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise AdmissionError(f"duplicate key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw,
            object_pairs_hook=unique,
            parse_constant=lambda item: (_ for _ in ()).throw(AdmissionError(f"non-finite {item}")),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, AdmissionError) as exc:
        raise AdmissionError(f"cannot decode {where}: {exc}") from exc
    if not isinstance(value, dict):
        raise AdmissionError(f"{where} is not an object")
    return value


def _digest(value: Any, where: str) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise AdmissionError(f"{where} is not a SHA-256 digest")


def _load_replay(path: Path) -> tuple[dict[str, Any], str]:
    raw, digest = _read_regular(path, 8_000_000)
    replay = _decode(raw, str(path))
    if replay.get("schema_version") != REPLAY_SCHEMA:
        raise AdmissionError("replay schema differs")
    return replay, digest


def _load_supervisor(path: Path) -> tuple[dict[str, Any], str]:
    raw, digest = _read_regular(path, 2_000_000)
    receipt = _decode(raw, str(path))
    required = {
        "schema_version", "terminal_status", "definition_sha256", "run_manifest_sha256",
        "run_receipt_sha256", "replay_receipt_sha256", "execution_gate_sha256",
        "monitor_end_passed", "no_guard_breach", "restoration_passed",
        "controller_source_sha256", "finished_at",
    }
    if set(receipt) != required or receipt.get("schema_version") != SUPERVISOR_FINAL_SCHEMA:
        raise AdmissionError("supervisor-final receipt fields or schema differ")
    for key in (
        "definition_sha256", "run_manifest_sha256", "run_receipt_sha256",
        "replay_receipt_sha256", "execution_gate_sha256",
    ):
        _digest(receipt[key], f"supervisor.{key}")
    sources = receipt["controller_source_sha256"]
    if not isinstance(sources, dict) or not sources:
        raise AdmissionError("supervisor controller source bundle is empty")
    for key, value in sources.items():
        if not isinstance(key, str) or not key:
            raise AdmissionError("supervisor source path is invalid")
        _digest(value, f"supervisor.controller_source_sha256[{key!r}]")
    return receipt, digest


def _write_exclusive(path: Path, value: dict[str, Any]) -> str:
    raw = canonical_json(value) + b"\n"
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(raw).hexdigest()


def admit_replay(
    definition: LoadedDocument,
    run_manifest: LoadedDocument,
    *,
    run_dir: Path | str,
    supervisor_final_path: Path | str,
) -> dict[str, Any]:
    """Write admission.json after replay and external restoration evidence exist."""
    validate_definition(definition.document, require_published=True)
    validate_run_manifest(run_manifest.document, definition)
    directory = Path(run_dir).absolute()
    run, run_sha = load_run_receipt(directory / "run.json")
    replay, replay_sha = _load_replay(directory / "replay.json")
    supervisor, supervisor_sha = _load_supervisor(Path(supervisor_final_path))
    reasons: list[str] = []
    try:
        gate_raw, gate_sha = _read_regular(directory / "execution-gate.snapshot.json", 2_000_000)
        gate = _decode(gate_raw, "execution-gate.snapshot.json")
    except (OSError, AdmissionError) as exc:
        gate, gate_sha = {}, None
        reasons.append(f"execution gate cannot be verified: {exc}")
    if run.get("terminal_status") != "complete":
        reasons.append(f"run terminal status is {run.get('terminal_status')!r}")
    if run.get("definition_sha256") != definition.raw_sha256 or run.get("run_manifest_sha256") != run_manifest.raw_sha256:
        reasons.append("run binds different definition or manifest bytes")
    if (
        run.get("arm_id") != run_manifest.document["arm"]["id"]
        or run.get("comparison_id") != run_manifest.document["comparison_id"]
    ):
        reasons.append("run arm or comparison differs from the run manifest")
    if run.get("execution_source_sha256") != execution_source_hashes():
        reasons.append("run execution sources differ from the admitted source bundle")
    if replay.get("verified") is not True or replay.get("terminal_status") != "verified":
        reasons.append("raw replay is not verified")
    if replay.get("definition_sha256") != definition.raw_sha256:
        reasons.append("replay binds a different definition")
    if replay.get("run_manifest_sha256") != run_manifest.raw_sha256:
        reasons.append("replay binds a different run manifest")
    if replay.get("run_receipt_sha256") != run_sha:
        reasons.append("replay binds a different run receipt")
    if (
        replay.get("arm_id") != run_manifest.document["arm"]["id"]
        or replay.get("comparison_id") != run_manifest.document["comparison_id"]
    ):
        reasons.append("replay arm or comparison differs from the run manifest")
    if replay.get("replay_source_sha256") != replay_source_hashes():
        reasons.append("replay sources differ from the admitted source bundle")
    if replay.get("mismatches") != []:
        reasons.append("replay contains mismatches")
    task_ids = [task["id"] for task in definition.document["tasks"]]
    tasks = {task["id"]: task for task in definition.document["tasks"]}
    run_outcomes = run.get("outcomes")
    replay_outcomes = replay.get("outcomes")
    if (
        not isinstance(run_outcomes, list)
        or [row.get("task_id") for row in run_outcomes if isinstance(row, dict)] != task_ids
        or len(run_outcomes) != len(task_ids)
    ):
        reasons.append("run does not contain the exact ordered task set")
        run_outcomes = []
    if (
        not isinstance(replay_outcomes, list)
        or [row.get("task_id") for row in replay_outcomes if isinstance(row, dict)] != task_ids
        or len(replay_outcomes) != len(task_ids)
    ):
        reasons.append("replay does not contain the exact ordered task set")
        replay_outcomes = []
    replay_by_id = {row.get("task_id"): row for row in replay_outcomes if isinstance(row, dict)}
    total_calls = 0
    for row in run_outcomes:
        task_id = row.get("task_id")
        task = tasks.get(task_id)
        if task is None:
            reasons.append(f"{task_id}: task is absent from the definition")
            continue
        status = row.get("cell_status")
        calls = row.get("model_calls")
        if any(row.get(key) != task[key] for key in ("panel", "domain", "construct")):
            reasons.append(f"{task_id}: public task metadata differs from the definition")
        if not isinstance(row.get("score_credit"), bool):
            reasons.append(f"{task_id}: score credit is not boolean")
        if status not in CELL_STATUSES:
            reasons.append(f"{task_id}: unsupported cell status")
        if (
            isinstance(calls, bool) or not isinstance(calls, int) or calls < 0
            or calls > task["resource"]["max_model_calls"]
        ):
            reasons.append(f"{task_id}: model-call count is outside its bound")
        else:
            total_calls += calls
        if row.get("model_calls_exact") is not True:
            reasons.append(f"{task_id}: model-call count is not exact")
        replay_row = replay_by_id.get(task_id)
        for key in (
            "cell_status", "score_credit", "failure_code", "model_calls",
            "model_calls_exact", "metrics", "raw_evidence_sha256",
        ):
            if not isinstance(replay_row, dict) or replay_row.get(key) != row.get(key):
                reasons.append(f"{task_id}: replay differs in {key}")
                break
        if not isinstance(replay_row, dict) or replay_row.get("verified") is not True:
            reasons.append(f"{task_id}: replay row is not verified")
    if total_calls > definition.document["resource_envelope"]["max_model_calls_per_arm"]:
        reasons.append("run exceeds the arm model-call ceiling")
    replay_calls = sum(
        row.get("model_calls", 0)
        for row in replay_outcomes
        if isinstance(row, dict) and isinstance(row.get("model_calls"), int)
        and not isinstance(row.get("model_calls"), bool)
    )
    if replay_outcomes and replay_calls != total_calls:
        reasons.append("replay and run model-call totals differ")
    summary = run.get("summary")
    if not isinstance(summary, dict) or summary.get("model_calls") != total_calls:
        reasons.append("run summary model-call count differs from outcomes")
    if gate_sha != run.get("execution_gate_sha256"):
        reasons.append("execution gate snapshot hash differs from run receipt")
    expected_route_identities = {
        route_id: route["runtime_identity"]
        for route_id, route in run_manifest.document["arm"]["routes"].items()
    }
    if (
        set(gate) != EXECUTION_GATE_FIELDS
        or gate.get("admitted") is not True
        or gate.get("definition_sha256") != definition.raw_sha256
        or gate.get("run_manifest_sha256") != run_manifest.raw_sha256
        or gate.get("route_runtime_identities") != expected_route_identities
    ):
        reasons.append("execution gate snapshot does not bind the admitted manifests and routes")
    for key in ("endpoint_bindings_sha256", "supervision_receipt_sha256", "resource_guard_sha256"):
        try:
            _digest(gate.get(key), f"execution_gate.{key}")
        except AdmissionError as exc:
            reasons.append(str(exc))
    expected_supervisor = {
        "definition_sha256": definition.raw_sha256,
        "run_manifest_sha256": run_manifest.raw_sha256,
        "run_receipt_sha256": run_sha,
        "replay_receipt_sha256": replay_sha,
        "execution_gate_sha256": gate_sha,
    }
    for key, expected in expected_supervisor.items():
        if supervisor.get(key) != expected:
            reasons.append(f"supervisor {key} differs")
    if supervisor.get("terminal_status") != "complete":
        reasons.append("supervisor terminal status is not complete")
    for key in ("monitor_end_passed", "no_guard_breach", "restoration_passed"):
        if supervisor.get(key) is not True:
            reasons.append(f"supervisor {key} is not true")
    invalid_cells = [
        row.get("task_id") for row in run_outcomes
        if row.get("cell_status") in {"invalid", "skipped_budget", "unissued"}
    ]
    if invalid_cells:
        reasons.append(f"non-admissible cell states: {invalid_cells}")
    admitted = not reasons
    receipt = {
        "schema_version": ADMISSION_SCHEMA,
        "generated_at": _utc_now(),
        "admission_status": "admitted" if admitted else "withheld",
        "admitted": admitted,
        "reasons": reasons,
        "definition_sha256": definition.raw_sha256,
        "run_manifest_sha256": run_manifest.raw_sha256,
        "run_receipt_sha256": run_sha,
        "replay_receipt_sha256": replay_sha,
        "supervisor_final_receipt_sha256": supervisor_sha,
        "admission_source_sha256": admission_source_hashes(),
        "arm_id": run_manifest.document["arm"]["id"],
        "comparison_id": run_manifest.document["comparison_id"],
        "promotion_authorized": False,
    }
    _write_exclusive(directory / "admission.json", receipt)
    return receipt


def load_admission_receipt(path: Path | str) -> tuple[dict[str, Any], str]:
    target = Path(path).absolute()
    raw, digest = _read_regular(target, 2_000_000)
    receipt = _decode(raw, str(target))
    if receipt.get("schema_version") != ADMISSION_SCHEMA:
        raise AdmissionError("admission schema differs")
    return receipt, digest


__all__ = ["AdmissionError", "admission_source_hashes", "admit_replay", "load_admission_receipt"]
