"""Offline raw-evidence replay for stable benchmark arm receipts.

Replay is intentionally explicit and potentially expensive for code tasks.  It
is an operator action, never an HTTP request side effect.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .graders import GradeResult, grade_task
from .manifest import LoadedDocument, ManifestError, canonical_json, validate_definition, validate_run_manifest
from .runner import (
    RUN_SCHEMA,
    _status_for_grade,
    _validate_record,
    execution_source_hashes,
    strict_json_object,
)


REPLAY_SCHEMA = "stable-benchmark-replay-receipt/v1"
SOURCE_FILES = tuple(Path(__file__).with_name(name) for name in (
    "__init__.py", "fixtures.py", "graders.py", "manifest.py", "runner.py", "replay.py",
)) + (
    Path(__file__).resolve().parents[2] / "bench/weekly_upgrade_portfolio/code_sandbox.py",
)


class ReplayError(ValueError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def replay_source_hashes() -> dict[str, str]:
    root = Path(__file__).resolve().parents[2]
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in SOURCE_FILES
    }


def _read_regular(path: Path, limit: int) -> bytes:
    target = path.absolute()
    before = target.lstat()
    if not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode) or before.st_size > limit:
        raise ReplayError(f"unsafe or oversized replay input: {target}")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(target, flags)
    try:
        observed = os.fstat(descriptor)
        if (observed.st_dev, observed.st_ino) != (before.st_dev, before.st_ino):
            raise ReplayError("replay input identity changed during open")
        raw = b""
        while len(raw) <= limit:
            chunk = os.read(descriptor, min(65536, limit + 1 - len(raw)))
            if not chunk:
                break
            raw += chunk
    finally:
        os.close(descriptor)
    if len(raw) != before.st_size or len(raw) > limit:
        raise ReplayError("replay input size changed or exceeded its limit")
    return raw


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReplayError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _decode(raw: bytes, where: str) -> Any:
    try:
        return json.loads(
            raw,
            object_pairs_hook=_unique_object,
            parse_constant=lambda value: (_ for _ in ()).throw(ReplayError(f"non-finite {value}")),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ReplayError) as exc:
        raise ReplayError(f"cannot decode {where}: {exc}") from exc


def load_run_receipt(path: Path | str) -> tuple[dict[str, Any], str]:
    target = Path(path).absolute()
    raw = _read_regular(target, 4_000_000)
    receipt = _decode(raw, str(target))
    if not isinstance(receipt, dict) or receipt.get("schema_version") != RUN_SCHEMA:
        raise ReplayError("run receipt schema differs")
    return receipt, hashlib.sha256(raw).hexdigest()


def _raw_rows(path: Path) -> tuple[list[dict[str, Any]], str]:
    raw = _read_regular(path, 64_000_000)
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(raw.splitlines(), 1):
        if len(line) > 12_000_000:
            raise ReplayError(f"raw evidence line {line_number} exceeds its bound")
        row = _decode(line, f"raw evidence line {line_number}")
        if not isinstance(row, dict):
            raise ReplayError(f"raw evidence line {line_number} is not an object")
        rows.append(row)
    return rows, hashlib.sha256(raw).hexdigest()


def _role(task: dict[str, Any], record_index: int) -> str:
    if task["mode"] != "system_mission":
        return "capability"
    return "system_actor" if record_index == 0 else "system_critic"


def _regrade(task: dict[str, Any], row: dict[str, Any], arm: dict[str, Any]) -> dict[str, Any]:
    stored_sha = row.get("raw_evidence_sha256")
    if not isinstance(stored_sha, str):
        raise ReplayError(f"{task['id']} raw evidence digest is missing")
    body = {key: value for key, value in row.items() if key != "raw_evidence_sha256"}
    if hashlib.sha256(canonical_json(body)).hexdigest() != stored_sha:
        raise ReplayError(f"{task['id']} raw evidence digest differs")
    if row.get("task_id") != task["id"]:
        raise ReplayError(f"raw evidence task order differs at {task['id']}")
    status = row.get("status")
    if status in {"timeout", "transport_error"}:
        attempts = row.get("attempt_count")
        exact = row.get("attempt_count_exact")
        if (
            isinstance(attempts, bool)
            or not isinstance(attempts, int)
            or attempts < 1
            or attempts > task["resource"]["max_model_calls"]
        ):
            raise ReplayError(f"{task['id']} failure attempt ledger is invalid")
        if not isinstance(exact, bool):
            raise ReplayError(f"{task['id']} failure attempt exactness is missing")
        return {
            "task_id": task["id"], "cell_status": status, "score_credit": False,
            "failure_code": status, "model_calls": attempts, "model_calls_exact": exact,
            "metrics": {},
            "raw_evidence_sha256": stored_sha,
        }
    if status != "returned" or not isinstance(row.get("records"), list) or not isinstance(row.get("tool_trace"), list):
        raise ReplayError(f"{task['id']} raw evidence status or arrays differ")
    records = row["records"]
    attempts = row.get("attempt_count")
    if (
        isinstance(attempts, bool)
        or not isinstance(attempts, int)
        or attempts < len(records)
        or attempts < 1
        or attempts > task["resource"]["max_model_calls"]
        or row.get("attempt_count_exact") is not True
    ):
        grade = GradeResult(False, "model-call ceiling exceeded", "grader_invalid")
    else:
        drift = None
        for index, record in enumerate(records):
            if not isinstance(record, dict):
                drift = "runtime record is not an object"
                break
            drift = drift or _validate_record(record, task, arm, _role(task, index))
        if drift:
            grade = GradeResult(False, drift, "grader_invalid")
        elif row.get("failure_code"):
            grade = GradeResult(False, row.get("failure_detail") or row["failure_code"], "invalid_output")
        else:
            payload, parse_error = strict_json_object(row.get("completion"))
            grade = (
                GradeResult(False, parse_error or "invalid completion", "invalid_output")
                if payload is None
                else grade_task(task, payload, tool_trace=row["tool_trace"])
            )
    deadline_phase = row.get("deadline_phase")
    if deadline_phase == "inference":
        status = "timeout"
    elif deadline_phase == "grading":
        grade = GradeResult(False, "trusted grading exceeded the episode deadline", "grader_invalid")
        status = "invalid"
    else:
        status = _status_for_grade(grade)
    return {
        "task_id": task["id"], "cell_status": status,
        "score_credit": False if status == "timeout" else grade.passed,
        "failure_code": "timeout" if status == "timeout" else grade.failure_code,
        "model_calls": attempts, "model_calls_exact": True,
        "metrics": {} if status == "timeout" else grade.metrics,
        "raw_evidence_sha256": stored_sha,
    }


def _write_exclusive(path: Path, value: dict[str, Any]) -> str:
    raw = canonical_json(value) + b"\n"
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(raw).hexdigest()


def replay_run(
    definition: LoadedDocument,
    run_manifest: LoadedDocument,
    *,
    run_dir: Path | str,
) -> dict[str, Any]:
    """Re-execute objective graders from private raw evidence and write replay.json."""
    validate_definition(definition.document, require_published=True)
    validate_run_manifest(run_manifest.document, definition)
    directory = Path(run_dir).absolute()
    receipt, run_sha = load_run_receipt(directory / "run.json")
    if receipt.get("terminal_status") == "unissued":
        raise ReplayError("an unissued arm has no raw evidence to replay")
    if receipt.get("definition_sha256") != definition.raw_sha256 or receipt.get("run_manifest_sha256") != run_manifest.raw_sha256:
        raise ReplayError("run receipt binds different definition or manifest bytes")
    if receipt.get("execution_source_sha256") != execution_source_hashes():
        raise ReplayError("run-time source bundle differs from the current replay input")
    public = receipt.get("outcomes")
    if not isinstance(public, list) or len(public) != len(definition.document["tasks"]):
        raise ReplayError("run receipt does not account for all independent units")
    public_by_id = {row.get("task_id"): row for row in public if isinstance(row, dict)}
    if len(public_by_id) != len(public):
        raise ReplayError("run receipt has duplicate or malformed task outcomes")
    rows, raw_log_sha = _raw_rows(directory / "private/raw-attempts.jsonl")
    raw_by_id = {row.get("task_id"): row for row in rows}
    if len(raw_by_id) != len(rows):
        raise ReplayError("raw evidence has duplicate task rows")

    replayed: list[dict[str, Any]] = []
    mismatches: list[str] = []
    for task in definition.document["tasks"]:
        public_row = public_by_id.get(task["id"])
        if public_row is None:
            mismatches.append(f"{task['id']}: public outcome missing")
            continue
        if public_row.get("cell_status") in {"skipped_budget", "unissued"}:
            if task["id"] in raw_by_id:
                mismatches.append(f"{task['id']}: terminal no-call unit unexpectedly has raw evidence")
            replayed.append({
                "task_id": task["id"], "verified": True,
                "cell_status": public_row["cell_status"], "score_credit": False,
                "model_calls": 0, "model_calls_exact": True,
                "metrics": {}, "raw_evidence_sha256": None,
            })
            continue
        raw_row = raw_by_id.get(task["id"])
        if raw_row is None:
            mismatches.append(f"{task['id']}: raw evidence missing")
            continue
        try:
            observed = _regrade(task, raw_row, run_manifest.document["arm"])
        except Exception as exc:  # the invalid replay remains an artifact
            mismatches.append(f"{task['id']}: {type(exc).__name__}: {exc}")
            continue
        keys = (
            "cell_status", "score_credit", "failure_code", "model_calls",
            "model_calls_exact", "metrics", "raw_evidence_sha256",
        )
        different = [key for key in keys if public_row.get(key) != observed.get(key)]
        if different:
            mismatches.append(f"{task['id']}: public/replay mismatch in {','.join(different)}")
        replayed.append({**observed, "verified": not different})
    extra_raw = sorted(set(raw_by_id) - {task["id"] for task in definition.document["tasks"]})
    if extra_raw:
        mismatches.append(f"unexpected raw task IDs: {extra_raw}")
    total_calls = sum(row.get("model_calls", 0) for row in replayed)
    if total_calls > definition.document["resource_envelope"]["max_model_calls_per_arm"]:
        mismatches.append("arm model-call ceiling exceeded")
    verified = not mismatches and len(replayed) == len(definition.document["tasks"])
    replay = {
        "schema_version": REPLAY_SCHEMA,
        "generated_at": _utc_now(),
        "terminal_status": "verified" if verified else "invalid",
        "verified": verified,
        "arm_id": run_manifest.document["arm"]["id"],
        "comparison_id": run_manifest.document["comparison_id"],
        "run_receipt_sha256": run_sha,
        "raw_evidence_log_sha256": raw_log_sha,
        "definition_sha256": definition.raw_sha256,
        "run_manifest_sha256": run_manifest.raw_sha256,
        "replay_source_sha256": replay_source_hashes(),
        "outcomes": replayed,
        "mismatches": mismatches,
        "admission_authorized": False,
    }
    _write_exclusive(directory / "replay.json", replay)
    return replay


__all__ = ["ReplayError", "load_run_receipt", "replay_run", "replay_source_hashes"]
