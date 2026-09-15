"""Read-only, bounded projection for weekly upgrade benchmark progress.

The weekly-upgrade producers intentionally keep detailed prompts, model
responses, grading notes, and machine-local paths in operator artifacts.  The
dashboard needs none of that.  This module projects the small, canonical
receipts into a closed public shape and verifies every external artifact before
using its numeric summary.

``GET /api/weekly_upgrade/progress`` never runs a model, invokes a subprocess,
or writes a lock/cache.  Missing or damaged sources degrade to explicit
warnings.  Operator-recorded summaries remain labelled as such and can never
become a scientific-upgrade claim in this projection.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import sys
from collections import defaultdict
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(_REPOSITORY_ROOT) not in sys.path:
    # The deployed uvicorn process starts in ``ui/``.  Add the repository
    # package root once so this read-only projection uses the same evidence
    # ladder implementation as the research loop.
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from orchestrator.research_pipeline_progress import project_research_pipeline

from .local_model_research import DEFAULT_RESEARCH_ROOT, project_local_research

DEFAULT_CANONICAL_ROOT = Path("/home/decross1/projects/a_bgt_rsi")
DEFAULT_UPGRADE_RUNS_ROOT = Path("/home/decross1/projects/a_bgt_rsi_upgrade_runs")
DEFAULT_REVIEW_RUNS_ROOT = Path(
    "/home/decross1/projects/a_bgt_rsi_weekly_upgrade_runs"
)

SCHEMA_VERSION = "weekly-upgrade-progress/v1"
WEEKLY_LIMIT_SECONDS = 7_200.0
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_BUDGET_BYTES = 64 * 1024 * 1024
MAX_SOURCE_FILES = 512
MAX_WARNINGS = 64

_WEEK_RE = re.compile(r"[0-9]{4}-W[0-9]{2}\Z")
_TRIAL_ID_RE = re.compile(r"[0-9]{4}-W[0-9]{2}-[A-Za-z0-9._:-]{1,96}\Z")
_SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_DATE_SUFFIX_RE = re.compile(r"_[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
_SEED_FILE_RE = re.compile(r"seed_[0-9]+\.json\Z")

_OBSERVATION_FIELDS = {
    "fixed_attempts_expected",
    "fixed_attempts_returned",
    "fixed_attempts_protocol_valid",
    "objective_cases_passed",
    "objective_cases_total",
    "repair_cases_passed",
    "repair_cases_total",
    "annotation_disagreements",
}

_KNOWN_RUN_SCHEMAS = {
    "weekly-upgrade-eval-run/v1",
    "weekly-upgrade-game-science-run/v1",
    "weekly-upgrade-diversity-selection-run/v1",
    "weekly-upgrade-role-effort-run/v1",
    "weekly-upgrade-historical-repair-run/v1",
    "topic-scope-run/v1",
}

_PLAN_ARM_COUNTS = {
    "objective": 2,
    "diversity": 2,
    "portfolio": 2,
    "topic_scope": 2,
    "role_effort": 3,
    "historical_repair": 1,
}

_LABELS = {
    "weekly_qwen_effort_pilot": "Qwen reasoning effort",
    "weekly_context_capability_v1": "Resident context capability",
    "weekly_upgrade_game_science_dev_v0": "Game, science & coding portfolio",
    "diversity_selection_dev_v0": "Diversity + selection",
    "weekly_role_effort_v1": "Role-aware reasoning effort",
    "weekly_historical_coding_panel_v2": "Public historical repair baseline",
    "topic_scope_repair": "Topic scope repair",
    "topic_scope_repair_v2": "Topic scope repair v2",
}


class ProjectionError(RuntimeError):
    """A source cannot be trusted for the dashboard projection."""


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _sha(value: Any) -> str:
    raw = value if isinstance(value, bytes) else _canonical(value)
    return hashlib.sha256(raw).hexdigest()


def _strict_object(raw: bytes, *, label: str) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ProjectionError(f"{label} has a duplicate JSON key")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw,
            object_pairs_hook=unique,
            parse_constant=lambda token: (_ for _ in ()).throw(
                ValueError(f"non-finite number {token}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ProjectionError(f"{label} is malformed JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ProjectionError(f"{label} root is not an object")
    return value


def _root(path: Path, *, label: str, required: bool = False) -> Path | None:
    lexical = path.expanduser().absolute()
    if not lexical.exists():
        if required:
            raise ProjectionError(f"{label} is missing")
        return None
    if lexical.is_symlink() or not lexical.is_dir() or lexical.resolve() != lexical:
        raise ProjectionError(f"{label} is redirected or not a directory")
    return lexical


def _safe_file(
    path: Path,
    *,
    root: Path,
    label: str,
    maximum: int = MAX_JSON_BYTES,
) -> tuple[dict[str, Any], bytes]:
    """Read one bounded regular file beneath ``root`` from a single fd."""
    trusted_root = _root(root, label=f"{label} root", required=True)
    assert trusted_root is not None
    lexical = path.expanduser().absolute()
    try:
        relative = lexical.relative_to(trusted_root)
    except ValueError as exc:
        raise ProjectionError(f"{label} escapes its allowed root") from exc
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise ProjectionError(f"{label} has an invalid relative path")
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    cloexec = getattr(os, "O_CLOEXEC", 0)
    directory_flags = os.O_RDONLY | cloexec | nofollow | os.O_DIRECTORY
    directories: list[int] = []
    file_descriptor: int | None = None
    try:
        directory = os.open(trusted_root, directory_flags)
        directories.append(directory)
        for part in relative.parts[:-1]:
            directory = os.open(part, directory_flags, dir_fd=directory)
            directories.append(directory)
        file_descriptor = os.open(
            relative.parts[-1], os.O_RDONLY | cloexec | nofollow,
            dir_fd=directory,
        )
        size = os.fstat(file_descriptor).st_size
        if not stat.S_ISREG(os.fstat(file_descriptor).st_mode):
            raise ProjectionError(f"{label} is not a regular file")
        if size > maximum:
            raise ProjectionError(f"{label} exceeds the read bound")
        chunks: list[bytes] = []
        remaining = maximum + 1
        while remaining > 0:
            chunk = os.read(file_descriptor, min(remaining, 1024 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) > maximum or os.fstat(file_descriptor).st_size != size:
            raise ProjectionError(f"{label} changed or exceeded the read bound")
    except OSError as exc:
        raise ProjectionError(f"{label} is unreadable") from exc
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)
        for descriptor in reversed(directories):
            os.close(descriptor)
    return _strict_object(raw, label=label), raw


def _safe_children(root: Path, pattern: re.Pattern[str], *, label: str) -> list[Path]:
    directory = _root(root, label=label)
    if directory is None:
        return []
    try:
        children = sorted(directory.iterdir(), key=lambda path: path.name)
    except OSError as exc:
        raise ProjectionError(f"{label} is unreadable") from exc
    if len(children) > MAX_SOURCE_FILES:
        raise ProjectionError(f"{label} exceeds the file-count bound")
    return [path for path in children if pattern.fullmatch(path.name)]


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) and result >= 0 else None


def _count(value: Any) -> int | None:
    if type(value) is int and 0 <= value <= 1_000_000:
        return value
    return None


def _iso_week(now: datetime) -> str:
    year, week, _ = now.astimezone(timezone.utc).isocalendar()
    return f"{year}-W{week:02d}"


def _now(value: Callable[[], datetime] | datetime | None) -> datetime:
    current = value() if callable(value) else value
    if current is None:
        current = datetime.now(timezone.utc)
    if not isinstance(current, datetime) or current.tzinfo is None:
        raise ProjectionError("projection clock must be timezone-aware")
    return current.astimezone(timezone.utc)


def _warning(warnings: list[dict[str, str]], code: str, scope: str, detail: str) -> None:
    if len(warnings) < MAX_WARNINGS:
        warnings.append({"code": code, "scope": scope, "detail": detail})


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _week_bounds(value: datetime) -> tuple[str, datetime, datetime]:
    utc = value.astimezone(timezone.utc)
    start = datetime(utc.year, utc.month, utc.day, tzinfo=timezone.utc) - timedelta(
        days=utc.weekday()
    )
    return _iso_week(utc), start, start + timedelta(days=7)


def _validate_budget(path: Path) -> tuple[dict[str, dict[str, Any]], str | None]:
    """Read and validate the producer's hash-chained ledger without locking it.

    ``BudgetLedger.snapshot`` takes a lock and may create a lock file.  The UI
    has a stricter no-write contract, so this mirrors the producer's closed v1
    validation while performing only one bounded read.
    """
    root = _root(path.parent, label="budget directory", required=True)
    assert root is not None
    lexical = path.absolute()
    if lexical.is_symlink() or not lexical.is_file() or lexical.resolve() != lexical:
        raise ProjectionError("budget journal is missing or redirected")
    try:
        with lexical.open("rb") as stream:
            raw = stream.read(MAX_BUDGET_BYTES + 1)
    except OSError as exc:
        raise ProjectionError("budget journal is unreadable") from exc
    if not raw or len(raw) > MAX_BUDGET_BYTES or not raw.endswith(b"\n"):
        raise ProjectionError("budget journal is empty, oversized, or partial")

    previous: str | None = None
    events: list[dict[str, Any]] = []
    common = {
        "schema_version", "sequence", "event", "event_at", "week_id",
        "run_id", "manifest_sha256", "previous_event_sha256", "event_sha256",
    }
    for line_number, line in enumerate(raw.splitlines(), start=1):
        if not line:
            raise ProjectionError("budget journal contains a blank row")
        row = _strict_object(line, label=f"budget row {line_number}")
        event = row.get("event")
        expected = common | (
            {"reserved_s"} if event == "reserve" else
            {"reserved_s", "elapsed_s", "charged_s", "status"}
            if event == "finish" else
            {"elapsed_s", "charged_s", "status"} if event == "debit" else set()
        )
        if not expected or set(row) != expected:
            raise ProjectionError(f"budget row {line_number} has invalid fields")
        if (
            row.get("schema_version") != "weekly-upgrade-budget-v1"
            or type(row.get("sequence")) is not int
            or row["sequence"] != line_number
            or row.get("previous_event_sha256") != previous
            or not isinstance(row.get("event_sha256"), str)
            or row["event_sha256"] != _sha(
                {key: value for key, value in row.items() if key != "event_sha256"}
            )
            or not isinstance(row.get("run_id"), str)
            or not _SAFE_ID_RE.fullmatch(row["run_id"])
            or not isinstance(row.get("manifest_sha256"), str)
            or not _SHA_RE.fullmatch(row["manifest_sha256"])
            or not isinstance(row.get("week_id"), str)
            or not _WEEK_RE.fullmatch(row["week_id"])
        ):
            raise ProjectionError(f"budget row {line_number} fails its binding")
        at = _parse_time(row.get("event_at"))
        if at is None:
            raise ProjectionError(f"budget row {line_number} has invalid time")
        event_week, _, _ = _week_bounds(at)
        if event in {"reserve", "debit"} and event_week != row["week_id"]:
            raise ProjectionError(f"budget row {line_number} has wrong week")
        for field in ("reserved_s", "elapsed_s", "charged_s"):
            if field in row and _finite_number(row[field]) is None:
                raise ProjectionError(f"budget row {line_number} has invalid {field}")
        if event == "finish" and row.get("status") not in {
            "completed", "failed", "cancelled", "interrupted", "unknown",
        }:
            raise ProjectionError(f"budget row {line_number} has invalid status")
        if event == "debit" and row.get("status") != "imported":
            raise ProjectionError(f"budget row {line_number} has invalid debit")
        previous = row["event_sha256"]
        events.append(row)

    states: dict[str, dict[str, Any]] = {}
    for row in events:
        run_id = row["run_id"]
        event = row["event"]
        if event in {"reserve", "debit"} and run_id in states:
            raise ProjectionError("budget journal reuses a run id")
        if event == "reserve":
            reserved = float(row["reserved_s"])
            _, _, week_end = _week_bounds(_parse_time(row["event_at"]) or datetime.now(timezone.utc))
            event_at = _parse_time(row["event_at"])
            assert event_at is not None
            if event_at + timedelta(seconds=reserved) > week_end:
                raise ProjectionError("budget reservation crosses a week boundary")
            charged_before = sum(
                item["charged_s"] for item in states.values()
                if item["week_id"] == row["week_id"]
            )
            if charged_before + reserved > WEEKLY_LIMIT_SECONDS:
                raise ProjectionError("budget reservation exceeds the weekly limit")
            states[run_id] = {
                "week_id": row["week_id"], "reserved_s": reserved,
                "charged_s": reserved, "elapsed_s": None, "state": "reserved",
                "status": None, "manifest_sha256": row["manifest_sha256"],
                "reserved_at": row["event_at"],
            }
        elif event == "debit":
            if float(row["elapsed_s"]) != float(row["charged_s"]):
                raise ProjectionError("budget debit elapsed and charge differ")
            states[run_id] = {
                "week_id": row["week_id"], "reserved_s": 0.0,
                "charged_s": float(row["charged_s"]),
                "elapsed_s": float(row["elapsed_s"]), "state": "finished",
                "status": "imported", "manifest_sha256": row["manifest_sha256"],
                "reserved_at": None,
            }
        else:
            state = states.get(run_id)
            if state is None or state["state"] != "reserved":
                raise ProjectionError("budget finish has no active reservation")
            if (
                state["week_id"] != row["week_id"]
                or state["manifest_sha256"] != row["manifest_sha256"]
                or state["reserved_s"] != float(row["reserved_s"])
            ):
                raise ProjectionError("budget finish differs from its reservation")
            elapsed = float(row["elapsed_s"])
            charge = (
                max(state["reserved_s"], elapsed)
                if row["status"] in {"interrupted", "unknown"} else elapsed
            )
            if float(row["charged_s"]) != charge:
                raise ProjectionError("budget finish charge is inconsistent")
            reserved_at = _parse_time(state["reserved_at"])
            finished_at = _parse_time(row["event_at"])
            if reserved_at is None or finished_at is None or finished_at < reserved_at:
                raise ProjectionError("budget finish predates its reservation")
            state.update(
                elapsed_s=elapsed, charged_s=charge, state="finished",
                status=row["status"],
            )
    return states, previous


def _budget_rows(states: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_week: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for state in states.values():
        by_week[state["week_id"]].append(state)
    result: dict[str, dict[str, Any]] = {}
    for week, items in by_week.items():
        prior = sum(item["charged_s"] for item in items if item["status"] == "imported")
        measured = sum(
            item["charged_s"] for item in items
            if item["state"] == "finished" and item["status"] != "imported"
        )
        reserved = sum(
            item["charged_s"] for item in items if item["state"] == "reserved"
        )
        charged = prior + measured + reserved
        result[week] = {
            "limit_minutes": WEEKLY_LIMIT_SECONDS / 60,
            "charged_minutes": charged / 60,
            "trial_charge_minutes": measured / 60,
            "prior_import_minutes": prior / 60,
            "remaining_minutes": max(0.0, WEEKLY_LIMIT_SECONDS - charged) / 60,
            "overrun_minutes": max(0.0, charged - WEEKLY_LIMIT_SECONDS) / 60,
            "active_reservations": sum(item["state"] == "reserved" for item in items),
            "accounting_note": (
                "Charged time includes a prior-use accounting debit."
                if prior else None
            ),
        }
    return result


def _relative_manifest(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 512:
        raise ProjectionError("trial manifest path is invalid")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] != "experiments":
        raise ProjectionError("trial manifest path escapes experiments")
    return value


def _validate_plan_contract(plan: dict[str, Any]) -> None:
    kind = plan.get("kind")
    arm_ids = plan.get("arm_ids")
    fixtures = plan.get("fixture_ids")
    seeds = plan.get("seeds")
    expected_arm_count = _PLAN_ARM_COUNTS.get(kind) if isinstance(kind, str) else None
    if (
        not isinstance(kind, str) or expected_arm_count is None
        or not isinstance(arm_ids, list) or len(arm_ids) != expected_arm_count
        or any(not isinstance(item, str) or not _SAFE_ID_RE.fullmatch(item) for item in arm_ids)
        or len(set(arm_ids)) != len(arm_ids)
        or kind == "role_effort" and arm_ids != ["xhigh", "medium", "adaptive"]
        or not isinstance(fixtures, list) or not 1 <= len(fixtures) <= 1_000
        or any(not isinstance(item, str) or not _SAFE_ID_RE.fullmatch(item) for item in fixtures)
        or len(set(fixtures)) != len(fixtures)
        or not isinstance(seeds, list) or not 1 <= len(seeds) <= 64
        or any(type(seed) is not int or not 0 <= seed <= 2**32 - 1 for seed in seeds)
    ):
        raise ProjectionError("trial plan has invalid kind, arms, fixtures, or seeds")
    for field in ("manifest_sha256", "manifest_configuration_sha256"):
        if not isinstance(plan.get(field), str) or not _SHA_RE.fullmatch(plan[field]):
            raise ProjectionError(f"trial plan has invalid {field}")
    for field in ("expected_input_sha256", "expected_grader_sha256"):
        mapping = plan.get(field)
        if not isinstance(mapping, dict) or (
            mapping and set(mapping) != set(fixtures)
        ) or any(
            not isinstance(key, str) or not isinstance(value, str)
            or not _SHA_RE.fullmatch(value)
            for key, value in mapping.items()
        ):
            raise ProjectionError(f"trial plan has invalid {field}")
    declared = _count(plan.get("declared_attempts"))
    payload = _finite_number(plan.get("payload_budget_s"))
    reservation = _finite_number(plan.get("reservation_s"))
    if (
        declared is None or declared < 1
        or payload is None or payload <= 0
        or reservation is None or reservation <= 0
        or payload > reservation or reservation > WEEKLY_LIMIT_SECONDS
        or plan.get("production_change_authorized") is not False
    ):
        raise ProjectionError("trial plan has invalid attempts, budget, or authority")


def _validate_trial(
    path: Path,
    *,
    trials_root: Path,
    upgrade_runs_root: Path,
) -> dict[str, Any]:
    journal, raw = _safe_file(path, root=trials_root, label=f"trial/{path.name}")
    plan = journal.get("plan")
    result = journal.get("result")
    if not isinstance(plan, dict) or not isinstance(result, dict):
        raise ProjectionError("trial has no terminal plan/result")
    trial_id = path.stem
    week = plan.get("week_id")
    if (
        not _TRIAL_ID_RE.fullmatch(trial_id)
        or plan.get("trial_id") != trial_id
        or result.get("trial_id") != trial_id
        or not isinstance(week, str)
        or not _WEEK_RE.fullmatch(week)
        or not trial_id.startswith(f"{week}-")
        or journal.get("phase") != "finished"
        or plan.get("schema_version") != "weekly-upgrade-trial-plan/v1"
        or result.get("schema_version") != "weekly-upgrade-trial-result/v1"
    ):
        raise ProjectionError("trial identity/schema/phase is invalid")
    manifest_path = _relative_manifest(plan.get("manifest_path"))
    _validate_plan_contract(plan)
    output_value = journal.get("output")
    if not isinstance(output_value, str):
        raise ProjectionError("trial output is not a path")
    output = Path(output_value).absolute()
    expected_week_root = upgrade_runs_root.absolute() / week
    trusted_week_root = _root(expected_week_root, label=f"upgrade runs/{week}", required=True)
    assert trusted_week_root is not None
    try:
        output.relative_to(trusted_week_root)
    except ValueError as exc:
        raise ProjectionError("trial output escapes its week root") from exc
    if output.is_symlink() or not output.is_dir() or output.resolve() != output:
        raise ProjectionError("trial output is missing or redirected")
    if journal.get("binding_sha256") != _sha({"plan": plan, "output": output_value}):
        raise ProjectionError("trial journal binding does not match")
    if result.get("plan_sha256") != _sha(plan):
        raise ProjectionError("trial result does not bind its plan")
    result_bytes = json.dumps(result, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n"
    result_copy = output / "trial_result.json"
    if result_copy.exists():
        copied, copied_raw = _safe_file(
            result_copy, root=trusted_week_root, label=f"trial result/{trial_id}"
        )
        if copied != result or copied_raw != result_bytes:
            raise ProjectionError("trial result copy differs from canonical journal")
    budget = result.get("budget_receipt")
    if not isinstance(budget, dict) or (
        budget.get("run_id") != trial_id
        or budget.get("week_id") != week
        or budget.get("status") != result.get("status")
        or _finite_number(budget.get("charged_s")) is None
    ):
        raise ProjectionError("trial budget receipt is invalid")
    evaluation = result.get("evaluation")
    run: dict[str, Any] | None = None
    run_warning: str | None = None
    manifest_snapshot: dict[str, Any] | None = None
    if isinstance(evaluation, dict):
        evaluation_path = evaluation.get("path")
        evaluation_sha = evaluation.get("sha256")
        if not isinstance(evaluation_path, str) or not isinstance(evaluation_sha, str):
            run_warning = "evaluation receipt has no safe artifact binding"
        else:
            candidate = Path(evaluation_path).absolute()
            expected = output / "evaluation" / "run.json"
            if candidate != expected:
                run_warning = "evaluation path differs from the registered trial output"
            else:
                try:
                    run, run_raw = _safe_file(
                        candidate, root=trusted_week_root,
                        label=f"evaluation run/{trial_id}",
                    )
                    if not _SHA_RE.fullmatch(evaluation_sha) or _sha(run_raw) != evaluation_sha:
                        raise ProjectionError("evaluation run hash differs from its receipt")
                    if run.get("schema_version") not in _KNOWN_RUN_SCHEMAS:
                        raise ProjectionError("evaluation run schema is unsupported")
                    run_schema = run["schema_version"]
                    if not isinstance(run.get("outcomes"), list) or (
                        run_schema != "topic-scope-run/v1"
                        and not isinstance(run.get("summary"), dict)
                    ):
                        raise ProjectionError("evaluation run has malformed summary/outcomes")
                    artifact_hashes = evaluation.get("artifact_sha256")
                    if not isinstance(artifact_hashes, dict) or artifact_hashes.get("run.json") != evaluation_sha:
                        raise ProjectionError("evaluation artifact map does not bind run.json")
                    snapshot_hash = artifact_hashes.get("manifest.snapshot.json")
                    snapshot_path = candidate.parent / "manifest.snapshot.json"
                    if isinstance(snapshot_hash, str) and _SHA_RE.fullmatch(snapshot_hash):
                        if snapshot_hash != plan.get("manifest_sha256"):
                            raise ProjectionError(
                                "manifest snapshot differs from the registered trial plan"
                            )
                        manifest_snapshot, snapshot_raw = _safe_file(
                            snapshot_path, root=trusted_week_root,
                            label=f"manifest snapshot/{trial_id}",
                        )
                        if _sha(snapshot_raw) != snapshot_hash:
                            raise ProjectionError("manifest snapshot hash differs from its receipt")
                except ProjectionError as exc:
                    run = None
                    manifest_snapshot = None
                    run_warning = str(exc)
    return {
        "trial_id": trial_id,
        "week": week,
        "manifest_path": manifest_path,
        "binding_sha256": journal["binding_sha256"],
        "plan": plan,
        "result": result,
        "journal_sha256": _sha(raw),
        "trial_result_sha256": _sha(result_bytes),
        "transport_evaluation_sha256": (
            evaluation.get("sha256") if isinstance(evaluation, dict) else None
        ),
        "run": run,
        "manifest_snapshot": manifest_snapshot,
        "run_warning": run_warning,
    }


def _validated_observation(value: Any, *, arm: bool) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProjectionError("evaluation observation is not an object")
    expected = _OBSERVATION_FIELDS | ({"arm"} if arm else {"failure_categories"})
    if set(value) != expected:
        raise ProjectionError("evaluation observation has unexpected fields")
    result = {key: _count(value.get(key)) for key in _OBSERVATION_FIELDS}
    if any(value.get(key) is not None and result[key] is None for key in _OBSERVATION_FIELDS):
        raise ProjectionError("evaluation observation has an invalid count")
    for passed, total in (
        ("fixed_attempts_returned", "fixed_attempts_expected"),
        ("fixed_attempts_protocol_valid", "fixed_attempts_returned"),
        ("objective_cases_passed", "objective_cases_total"),
        ("repair_cases_passed", "repair_cases_total"),
    ):
        if result[passed] is not None and (
            result[total] is None or result[passed] > result[total]
        ):
            raise ProjectionError(f"evaluation observation {passed} exceeds {total}")
    for passed, total in (
        ("objective_cases_passed", "objective_cases_total"),
        ("repair_cases_passed", "repair_cases_total"),
    ):
        if (result[passed] is None) != (result[total] is None):
            raise ProjectionError(f"evaluation observation {passed}/{total} is only partially recorded")
    if arm:
        arm_id = value.get("arm")
        if not isinstance(arm_id, str) or not _SAFE_ID_RE.fullmatch(arm_id):
            raise ProjectionError("evaluation observation has an invalid arm")
        return {"arm": arm_id, **result}
    failures = value.get("failure_categories")
    if not isinstance(failures, list) or len(failures) > 32:
        raise ProjectionError("evaluation failure categories are invalid")
    clean_failures = []
    seen: set[str] = set()
    for item in failures:
        if not isinstance(item, dict) or set(item) != {"code", "count"}:
            raise ProjectionError("evaluation failure category is malformed")
        code = item.get("code")
        count = _count(item.get("count"))
        if (
            not isinstance(code, str)
            or not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,63}", code)
            or code in seen
            or count is None
        ):
            raise ProjectionError("evaluation failure category is invalid")
        seen.add(code)
        clean_failures.append({"code": code, "count": count})
    return {**result, "failure_categories": clean_failures}


def _validate_evaluation(
    path: Path,
    *,
    evaluations_root: Path,
    trial: dict[str, Any],
) -> dict[str, Any]:
    value, raw = _safe_file(
        path, root=evaluations_root, label=f"evaluation summary/{path.name}"
    )
    expected = {
        "schema_version", "trial_id", "recorded_at", "provenance",
        "trial_journal_sha256", "trial_result_sha256",
        "transport_evaluation_sha256", "summary_artifact_sha256",
        "annotation_artifacts", "observations", "arm_observations",
    }
    if set(value) != expected or value.get("schema_version") != "weekly-upgrade-evaluation-summary/v1":
        raise ProjectionError("evaluation summary is not the closed v1 schema")
    if (
        value.get("trial_id") != trial["trial_id"]
        or path.stem != trial["trial_id"]
        or value.get("provenance") != "operator_recorded"
        or _parse_time(value.get("recorded_at")) is None
        or value.get("trial_journal_sha256") != trial["journal_sha256"]
        or value.get("trial_result_sha256") != trial["trial_result_sha256"]
        or value.get("transport_evaluation_sha256")
        != trial["transport_evaluation_sha256"]
    ):
        raise ProjectionError("evaluation summary is not bound to its trial")
    for field in ("trial_journal_sha256", "trial_result_sha256", "summary_artifact_sha256"):
        if not isinstance(value.get(field), str) or not _SHA_RE.fullmatch(value[field]):
            raise ProjectionError(f"evaluation summary has invalid {field}")
    annotations = value.get("annotation_artifacts")
    if not isinstance(annotations, list) or len(annotations) > 4:
        raise ProjectionError("evaluation annotations are unbounded")
    for annotation in annotations:
        if not isinstance(annotation, dict) or annotation.get("provenance") != "independent_subscription_annotation":
            raise ProjectionError("evaluation annotation provenance is invalid")
        for field in ("artifact_sha256", "transport_receipt_sha256"):
            if not isinstance(annotation.get(field), str) or not _SHA_RE.fullmatch(annotation[field]):
                raise ProjectionError("evaluation annotation hash is invalid")
        models = annotation.get("model_ids")
        if not isinstance(models, list) or not 1 <= len(models) <= 8 or any(
            not isinstance(model, str) or not 1 <= len(model) <= 128 for model in models
        ):
            raise ProjectionError("evaluation annotation model ids are invalid")
    observations = _validated_observation(value.get("observations"), arm=False)
    if observations["fixed_attempts_expected"] != trial["plan"]["declared_attempts"]:
        raise ProjectionError(
            "evaluation transport denominator differs from the trial plan"
        )
    raw_arms = value.get("arm_observations")
    if not isinstance(raw_arms, list) or len(raw_arms) > 8:
        raise ProjectionError("evaluation arms are unbounded")
    arms = [_validated_observation(item, arm=True) for item in raw_arms]
    if len({item["arm"] for item in arms}) != len(arms):
        raise ProjectionError("evaluation arms are duplicated")
    plan_arms = trial["plan"].get("arm_ids")
    if not isinstance(plan_arms, list) or {item["arm"] for item in arms} != set(plan_arms):
        raise ProjectionError("evaluation arms differ from the trial plan")
    for field in _OBSERVATION_FIELDS:
        arm_values = [item[field] for item in arms]
        overall = observations[field]
        if overall is not None and all(item is not None for item in arm_values) and sum(arm_values) != overall:
            raise ProjectionError(f"evaluation arm totals differ for {field}")
    return {
        "recorded_at": value["recorded_at"],
        "observations": observations,
        "arms": arms,
        "summary_sha256": value["summary_artifact_sha256"],
        "record_sha256": _sha(raw),
        "evidence_class": "UNVERIFIED_OPERATOR_SUMMARY",
        "candidate_benefit_verified": False,
    }


def _suite_lineage(manifest_path: str, kind: Any) -> tuple[str, str]:
    path = Path(manifest_path)
    name = path.parent.name if _SEED_FILE_RE.fullmatch(path.name) else path.stem
    name = _DATE_SUFFIX_RE.sub("", name)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_") or "unknown"
    family_id = f"{kind if isinstance(kind, str) else 'unknown'}:{safe}"
    label = _LABELS.get(safe, safe.replace("_", " ").title())
    return family_id, label


def _arm_definitions(trial: dict[str, Any]) -> list[dict[str, Any]]:
    snapshot = trial.get("manifest_snapshot")
    plan_arms = trial["plan"].get("arm_ids")
    if not isinstance(snapshot, dict) or not isinstance(plan_arms, list):
        return []
    definitions = snapshot.get("arms")
    if definitions is None:
        definitions = snapshot.get("conditions")
    if definitions is None and isinstance(snapshot.get("arm"), dict):
        # Historical-repair manifests are deliberately single-arm.  Preserve
        # that explicit arm identity instead of projecting an anonymous row.
        definitions = [snapshot["arm"]]
    if not isinstance(definitions, list):
        return []
    by_id = {
        item.get("id"): item for item in definitions
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    safe_definitions: list[dict[str, Any]] = []

    def safe_text(value: Any, *, identifier: bool = False) -> str | None:
        if not isinstance(value, str):
            return None
        flat = " ".join(value.split())
        if not 1 <= len(flat) <= 160 or any(ord(char) < 32 for char in flat):
            return None
        if identifier and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/+-]{0,159}", flat):
            return None
        return flat

    for arm_id in plan_arms:
        source = by_id.get(arm_id, {})
        expected_policy = source.get("expected_policy")
        safe_policy = None
        if isinstance(expected_policy, dict):
            safe_policy = {}
            for key in ("temperature", "top_p"):
                number = _finite_number(expected_policy.get(key))
                if number is not None and number <= 2:
                    safe_policy[key] = number
            effort = safe_text(expected_policy.get("reasoning_effort"), identifier=True)
            if effort is not None:
                safe_policy["reasoning_effort"] = effort
        safe_definitions.append({
            "id": arm_id,
            "label": safe_text(source.get("label")),
            "backend": safe_text(source.get("backend"), identifier=True),
            "model": safe_text(source.get("model"), identifier=True),
            "profile": (
                safe_text(source.get("profile"), identifier=True)
                or safe_text(source.get("generation_profile"), identifier=True)
            ),
            "max_tokens": _count(source.get("max_tokens")) or _count(source.get("max_tokens_per_call")),
            "request_timeout_s": _finite_number(source.get("request_timeout_s")) or _finite_number(source.get("timeout_s_per_call")),
            "expected_policy": safe_policy,
            "source_commit": (
                source.get("source_commit")
                if isinstance(source.get("source_commit"), str)
                and re.fullmatch(r"[0-9a-f]{40}", source["source_commit"])
                else None
            ),
        })
    return safe_definitions


def _configuration_label(definition: dict[str, Any]) -> str | None:
    if definition.get("label"):
        return definition["label"]
    parts = [definition.get("model"), definition.get("profile")]
    return " · ".join(part for part in parts if part) or None


def _run_arm_timings(
    trial: dict[str, Any],
) -> dict[str, dict[str, float | int | None]] | None:
    run = trial.get("run")
    if not isinstance(run, dict):
        return None
    arm_ids = trial["plan"].get("arm_ids")
    if not isinstance(arm_ids, list):
        return None
    timings: dict[str, dict[str, float | int | None]] = {
        arm: {"wall": None, "timeouts": 0, "rows": 0} for arm in arm_ids
    }
    summary = run.get("summary")
    if isinstance(summary, dict) and isinstance(summary.get("arms"), dict):
        run_schema = run.get("schema_version")
        for arm in arm_ids:
            row = summary["arms"].get(arm)
            if not isinstance(row, dict):
                return None
            wall = _finite_number(
                row.get("wall_s")
                if run_schema == "weekly-upgrade-role-effort-run/v1"
                else row.get("charged_wall_s_including_failures")
            )
            if wall is None:
                return None
            timings[arm]["wall"] = wall
    else:
        outcomes = run.get("outcomes")
        if not isinstance(outcomes, list):
            return None
        for outcome in outcomes:
            if not isinstance(outcome, dict):
                return None
            arm = outcome.get("arm_id", outcome.get("arm", outcome.get("condition")))
            if arm not in timings:
                continue
            duration = _finite_number(outcome.get("duration_s"))
            if duration is None:
                return None
            current_wall = timings[arm]["wall"]
            timings[arm]["wall"] = (
                (float(current_wall) if current_wall is not None else 0.0)
                + duration
            )
            timings[arm]["rows"] = int(timings[arm]["rows"]) + 1
    outcomes = run.get("outcomes")
    if isinstance(outcomes, list):
        for outcome in outcomes:
            if not isinstance(outcome, dict):
                continue
            arm = outcome.get("arm_id", outcome.get("arm", outcome.get("condition")))
            if arm not in timings:
                continue
            status = str(outcome.get("status", "")).lower()
            failure = str(outcome.get("failure_code", "")).lower()
            if "timeout" in status or "timeout" in failure:
                timings[arm]["timeouts"] = int(timings[arm]["timeouts"]) + 1
    return timings


def _sum_nullable(values: Iterable[int | None]) -> int | None:
    material = list(values)
    return sum(value for value in material if value is not None) if material and all(
        value is not None for value in material
    ) else None


def _aggregate_arm(arm_id: str, trials: list[dict[str, Any]]) -> dict[str, Any]:
    observations = [
        arm for trial in trials for arm in (trial.get("evaluation") or {}).get("arms", [])
        if arm.get("arm") == arm_id
    ]
    observations_complete = len(observations) == len(trials)
    if not observations_complete:
        observations = []
    attempted = _sum_nullable(item.get("fixed_attempts_expected") for item in observations)
    completed = _sum_nullable(item.get("fixed_attempts_returned") for item in observations)
    protocol = _sum_nullable(item.get("fixed_attempts_protocol_valid") for item in observations)
    objective_passed = _sum_nullable(item.get("objective_cases_passed") for item in observations)
    objective_total = _sum_nullable(item.get("objective_cases_total") for item in observations)
    repair_passed = _sum_nullable(item.get("repair_cases_passed") for item in observations)
    repair_total = _sum_nullable(item.get("repair_cases_total") for item in observations)
    disagreements = _sum_nullable(item.get("annotation_disagreements") for item in observations)

    timing_rows = [_run_arm_timings(trial) for trial in trials]
    timings_complete = all(row is not None and arm_id in row for row in timing_rows)
    walls_complete = timings_complete and all(
        row is not None and row[arm_id]["wall"] is not None for row in timing_rows
    )
    charged_wall = (
        sum(float(row[arm_id]["wall"]) for row in timing_rows if row is not None)
        if walls_complete else None
    )
    timeouts = (
        sum(int(row[arm_id]["timeouts"]) for row in timing_rows if row is not None)
        if timings_complete else None
    )
    successful = objective_passed if objective_total is not None else repair_passed
    denominator = objective_total if objective_total is not None else repair_total
    success_rate = successful / denominator if successful is not None and denominator else None
    definitions = [
        definition for trial in trials for definition in _arm_definitions(trial)
        if definition.get("id") == arm_id
    ]
    configuration_values = {
        _configuration_label(item) for item in definitions if _configuration_label(item)
    }
    configuration = (
        next(iter(configuration_values)) if len(configuration_values) == 1
        else "Multiple recorded configurations" if configuration_values else None
    )
    label_values = {item.get("label") for item in definitions if item.get("label")}
    label = next(iter(label_values)) if len(label_values) == 1 else (
        "Control" if arm_id == "control" else
        "Diverse + select" if arm_id == "diverse_select" else
        f"Arm {arm_id}"
    )
    ctt = (
        objective_passed * 3600 / charged_wall
        if objective_passed is not None and charged_wall and charged_wall > 0 else None
    )
    return {
        "id": arm_id,
        "label": label,
        "configuration": configuration,
        "transport_expected": attempted,
        "transport_returned": completed,
        "objective_successes": objective_passed,
        "objective_total": objective_total,
        "repair_successes": repair_passed,
        "repair_total": repair_total,
        "timeouts": timeouts,
        "metrics": {
            "success_rate": success_rate,
            "ctt_per_hour": ctt,
            "rsr_2of3": None,
            "recorded_wall_seconds": charged_wall,
            "mean_recorded_seconds_per_transport_attempt": (
                charged_wall / attempted if charged_wall is not None and attempted else None
            ),
            "repair_rate": (
                repair_passed / repair_total
                if repair_passed is not None and repair_total else None
            ),
            "protocol_valid_rate": (
                protocol / attempted if protocol is not None and attempted else None
            ),
            "annotation_disagreements": disagreements,
        },
    }


def _add_rsr(
    arms: list[dict[str, Any]], trials: list[dict[str, Any]], *, contract_bound: bool,
) -> None:
    """Derive RSR_2of3 only from three hash-bound standard paired runs."""
    if not contract_bound or len(trials) != 3 or any(
        (trial.get("run") or {}).get("schema_version") != "weekly-upgrade-eval-run/v1"
        for trial in trials
    ):
        return
    plan_arms = trials[0]["plan"].get("arm_ids")
    if not isinstance(plan_arms, list) or len(plan_arms) != 2:
        return
    results: dict[str, dict[str, list[bool]]] = {
        arm: defaultdict(list) for arm in plan_arms
    }
    expected_tasks = set(trials[0]["plan"].get("fixture_ids") or [])
    if not expected_tasks:
        return
    for trial in trials:
        summary = trial["run"].get("summary")
        if not isinstance(summary, dict):
            return
        pairs = summary.get("pairs")
        if not isinstance(pairs, list):
            return
        seen: set[str] = set()
        for pair in pairs:
            if not isinstance(pair, dict) or not isinstance(pair.get("task_id"), str):
                return
            task = pair["task_id"]
            if task in seen:
                return
            seen.add(task)
            results[plan_arms[0]][task].append(pair.get("a_status") == "passed")
            results[plan_arms[1]][task].append(pair.get("b_status") == "passed")
        if seen != expected_tasks:
            return
    for arm in arms:
        tasks = results.get(arm["id"], {})
        if tasks and all(len(runs) == 3 for runs in tasks.values()):
            arm["metrics"]["rsr_2of3"] = sum(sum(runs) >= 2 for runs in tasks.values()) / len(tasks)


def _baseline_roles(trials: list[dict[str, Any]]) -> tuple[str | None, str | None, dict[str, Any] | None]:
    plan_arms = trials[0]["plan"].get("arm_ids")
    if not isinstance(plan_arms, list) or len(plan_arms) != 2:
        return None, None, None
    if plan_arms[0] == "control":
        definitions = _arm_definitions(trials[0])
        baseline = next((item for item in definitions if item["id"] == "control"), {"id": "control"})
        return "control", plan_arms[1], baseline
    definitions = _arm_definitions(trials[0])
    first = next((item for item in definitions if item["id"] == plan_arms[0]), None)
    if first and isinstance(first.get("label"), str) and re.search(
        r"\b(current|baseline)\b", first["label"], re.IGNORECASE
    ):
        return plan_arms[0], plan_arms[1], first
    return None, None, None


def _execution_identity(run: Any) -> str | None:
    if not isinstance(run, dict):
        return None
    value = run.get("execution_source_sha256")
    if value is None and isinstance(run.get("provenance"), dict):
        value = run["provenance"].get("harness_file_sha256")
    if isinstance(value, str) and _SHA_RE.fullmatch(value):
        return value
    if isinstance(value, dict) and value and all(
        isinstance(key, str) and isinstance(digest, str) and _SHA_RE.fullmatch(digest)
        for key, digest in value.items()
    ):
        return _sha({key: value[key] for key in sorted(value)})
    return None


def _semantic_denominators(
    trial: dict[str, Any], arm_ids: list[str],
) -> list[dict[str, Any]] | None:
    """Return the ordered denominator contract used by displayed success rates.

    These fields come from a hash-bound operator receipt and remain explicitly
    unverified evidence.  They are still required for longitudinal linkage: a
    series must never compare objective and repair rates, or rates calculated
    over different case counts, merely because its transport plan is stable.
    """
    evaluation = trial.get("evaluation")
    if not isinstance(evaluation, dict):
        return None
    observations = evaluation.get("arms")
    if not isinstance(observations, list):
        return None
    by_arm = {
        item.get("arm"): item
        for item in observations
        if isinstance(item, dict) and isinstance(item.get("arm"), str)
    }
    if set(by_arm) != set(arm_ids):
        return None
    contract: list[dict[str, Any]] = []
    for arm_id in arm_ids:
        row = by_arm[arm_id]
        objective_total = _count(row.get("objective_cases_total"))
        objective_successes = _count(row.get("objective_cases_passed"))
        repair_total = _count(row.get("repair_cases_total"))
        repair_successes = _count(row.get("repair_cases_passed"))
        if objective_total is not None and objective_successes is not None:
            kind = "objective"
            total = objective_total
        elif repair_total is not None and repair_successes is not None:
            kind = "repair"
            total = repair_total
        else:
            return None
        if total < 1:
            return None
        contract.append({"arm_id": arm_id, "kind": kind, "total": total})
    return contract


def _comparison_contract(
    family_id: str,
    trials: list[dict[str, Any]],
) -> tuple[str | None, list[str], list[str], str | None, str | None]:
    reasons: list[str] = []
    first = trials[0]["plan"]
    baseline_id, candidate_id, baseline_definition = _baseline_roles(trials)
    fixtures = first.get("fixture_ids")
    inputs = first.get("expected_input_sha256")
    graders = first.get("expected_grader_sha256")
    arm_ids = first.get("arm_ids")
    required_maps = (
        isinstance(fixtures, list) and bool(fixtures)
        and all(isinstance(item, str) and _SAFE_ID_RE.fullmatch(item) for item in fixtures)
        and isinstance(inputs, dict) and set(inputs) == set(fixtures)
        and isinstance(graders, dict) and set(graders) == set(fixtures)
        and all(isinstance(value, str) and _SHA_RE.fullmatch(value) for value in inputs.values())
        and all(isinstance(value, str) and _SHA_RE.fullmatch(value) for value in graders.values())
    )
    if not required_maps:
        reasons.append("Fixture input/grader bindings are incomplete")
    if baseline_id is None or candidate_id is None or baseline_definition is None:
        reasons.append("Stable baseline and candidate roles are not producer-identifiable")
    def binding(definition: dict[str, Any] | None) -> dict[str, Any] | None:
        if definition is None:
            return None
        return {
            key: definition.get(key)
            for key in (
                "id", "label", "backend", "model", "profile", "max_tokens",
                "request_timeout_s", "expected_policy", "source_commit",
            )
        }

    expected_fixtures = set(fixtures) if isinstance(fixtures, list) else set()
    expected_baseline = binding(baseline_definition)
    first_definitions = {item["id"]: item for item in _arm_definitions(trials[0])}
    expected_candidate = binding(first_definitions.get(candidate_id)) if candidate_id else None
    expected_denominators = (
        _semantic_denominators(trials[0], arm_ids)
        if isinstance(arm_ids, list) else None
    )
    if expected_denominators is None:
        reasons.append(
            "Recorded per-arm success denominators are incomplete or unavailable"
        )
    for repeat in trials[1:]:
        repeat_plan = repeat["plan"]
        repeat_baseline_id, repeat_candidate_id, repeat_baseline = _baseline_roles([repeat])
        repeat_definitions = {item["id"]: item for item in _arm_definitions(repeat)}
        if (
            set(repeat_plan.get("fixture_ids") or []) != expected_fixtures
            or repeat_plan.get("expected_input_sha256") != inputs
            or repeat_plan.get("expected_grader_sha256") != graders
            or repeat_plan.get("arm_ids") != arm_ids
        ):
            reasons.append("Fixture, grader, input, or arm bindings differ across repeats")
            break
        if (
            repeat_baseline_id != baseline_id
            or repeat_candidate_id != candidate_id
            or binding(repeat_baseline) != expected_baseline
            or binding(repeat_definitions.get(candidate_id)) != expected_candidate
        ):
            reasons.append("Arm roles or configurations differ across repeats")
            break
        if _semantic_denominators(repeat, arm_ids) != expected_denominators:
            reasons.append("Success denominator kinds or totals differ across repeats")
            break
    scalar_fields = ("declared_attempts", "payload_budget_s", "reservation_s")
    for field in scalar_fields:
        values = [_finite_number(trial["plan"].get(field)) for trial in trials]
        if any(value is None for value in values) or len(set(values)) != 1:
            reasons.append(f"{field} is absent or inconsistent across repeats")
    if not isinstance(arm_ids, list) or len(arm_ids) != 2:
        reasons.append("The paired arm contract is unavailable")
    source_schemas = {
        (trial.get("run") or {}).get("schema_version") for trial in trials
    }
    execution_sources = {_execution_identity(trial.get("run")) for trial in trials}
    if None in source_schemas or len(source_schemas) != 1:
        reasons.append("The evaluation controller schema is unavailable or inconsistent")
    if None in execution_sources or len(execution_sources) != 1:
        reasons.append("The evaluation controller identity is unavailable or inconsistent")
    all_seeds = sorted(
        seed for trial in trials for seed in (trial["plan"].get("seeds") or [])
        if type(seed) is int
    )
    if len(all_seeds) != sum(len(trial["plan"].get("seeds") or []) for trial in trials):
        reasons.append("The exact seed cohort is unavailable")
    basis = [
        "same normalized suite lineage",
        "same fixture input and grader hashes",
        "same declared denominator and time budgets",
        "same exact seed cohort and repeat count",
        "same evaluation controller identity",
        "stable producer-identifiable baseline role",
    ]
    if reasons:
        return None, basis, reasons, baseline_id, candidate_id
    assert baseline_definition is not None
    baseline_binding = binding(baseline_definition)
    contract = {
        "version": 1,
        "lineage": family_id,
        "kind": first.get("kind"),
        "fixtures": sorted(fixtures),
        "inputs": {key: inputs[key] for key in sorted(inputs)},
        "graders": {key: graders[key] for key in sorted(graders)},
        "arm_ids": arm_ids,
        "baseline": baseline_binding,
        "semantic_denominators": expected_denominators,
        "declared_attempts_per_repeat": first["declared_attempts"],
        "payload_budget_s_per_repeat": first["payload_budget_s"],
        "reservation_s_per_repeat": first["reservation_s"],
        "seeds": all_seeds,
        "repeat_count": len(trials),
        "run_schema": next(iter(source_schemas)),
        "execution_source_sha256": next(iter(execution_sources)),
    }
    return _sha(contract), basis, [], baseline_id, candidate_id


def _family(week: str, family_id: str, label: str, trials: list[dict[str, Any]]) -> dict[str, Any]:
    trials.sort(key=lambda row: row["trial_id"])
    plan_arms = trials[0]["plan"].get("arm_ids")
    arm_ids = plan_arms if isinstance(plan_arms, list) else []
    arms = [_aggregate_arm(arm_id, trials) for arm_id in arm_ids]
    fingerprint, basis, break_reasons, baseline_id, candidate_id = _comparison_contract(
        family_id, trials
    )
    context_claim_limit = "weekly_context_capability" in family_id
    role_effort_claim_limit = trials[0]["plan"].get("kind") == "role_effort"
    historical_claim_limit = trials[0]["plan"].get("kind") == "historical_repair"
    if context_claim_limit:
        break_reasons.append(
            "Arms differ in model, context lane, and reasoning mode; results are descriptive, not a causal model comparison"
        )
        fingerprint = None
    _add_rsr(arms, trials, contract_bound=fingerprint is not None)
    execution_states = []
    for trial in trials:
        transport = trial["result"].get("evaluation")
        execution_states.append(
            "complete"
            if isinstance(transport, dict) and transport.get("execution_complete") is True
            else "incomplete"
            if trial["result"].get("status") in {"failed", "cancelled", "interrupted"}
            else "unknown"
        )
    execution_status = (
        execution_states[0] if len(set(execution_states)) == 1 else "mixed"
    )
    evaluation_count = sum(isinstance(trial.get("evaluation"), dict) for trial in trials)
    invalid_evaluation_count = sum(trial.get("evaluation_invalid") is True for trial in trials)
    evaluation_status = (
        "recorded" if evaluation_count == len(trials) else
        "partial" if evaluation_count else
        "invalid" if invalid_evaluation_count else "missing"
    )
    status = (
        "complete" if execution_status == "complete" and evaluation_status == "recorded" else
        "mixed" if execution_status == "mixed" else
        "incomplete" if execution_status == "incomplete" else
        "awaiting_annotation" if execution_status == "complete" else "unknown"
    )
    expected = _sum_nullable(
        (trial.get("evaluation") or {}).get("observations", {}).get("fixed_attempts_expected")
        for trial in trials
    )
    returned = _sum_nullable(
        (trial.get("evaluation") or {}).get("observations", {}).get("fixed_attempts_returned")
        for trial in trials
    )
    protocol = _sum_nullable(
        (trial.get("evaluation") or {}).get("observations", {}).get("fixed_attempts_protocol_valid")
        for trial in trials
    )
    timeouts = None
    timing_rows = [_run_arm_timings(trial) for trial in trials]
    if all(row is not None for row in timing_rows):
        timeouts = sum(
            int(arm["timeouts"])
            for row in timing_rows if row is not None for arm in row.values()
        )
    uncertainty = {
        "kind": "none", "metric": None, "low": None, "high": None, "n": None,
    }
    if (
        baseline_id is not None and candidate_id is not None
        and len(trials) == 1 and isinstance(trials[0].get("run"), dict)
    ):
        summary = trials[0]["run"].get("summary")
        paired = (
            summary.get("paired_failure_inclusive")
            if isinstance(summary, dict) else None
        )
        if isinstance(paired, dict):
            interval = paired.get("ci95")
            n = _count(paired.get("n_task_templates"))
            if (
                isinstance(interval, list) and len(interval) == 2
                and all(
                    isinstance(value, (int, float)) and not isinstance(value, bool)
                    and math.isfinite(value) and -1 <= value <= 1
                    for value in interval
                )
                and float(interval[0]) <= float(interval[1])
                and n is not None
            ):
                uncertainty = {
                    "kind": "bootstrap_95",
                    "metric": "failure_inclusive_delta_candidate_minus_baseline",
                    "low": float(interval[0]),
                    "high": float(interval[1]), "n": n,
                }
    manifests = sorted({trial["plan"].get("manifest_sha256") for trial in trials if isinstance(trial["plan"].get("manifest_sha256"), str)})
    source_commits = sorted({
        definition["source_commit"] for trial in trials for definition in _arm_definitions(trial)
        if definition.get("source_commit")
    })
    all_evaluated = evaluation_count == len(trials) and evaluation_count > 0
    candidate_verified = False if all_evaluated else None
    result = {
        "id": family_id,
        "label": label,
        "kind": str(trials[0]["plan"].get("kind", "unknown")),
        "status": status,
        "execution_status": execution_status,
        "evaluation_status": evaluation_status,
        "semantic_verdict": (
            "candidate_benefit_not_verified" if all_evaluated else "unknown"
        ),
        "evidence": {
            "class": "UNVERIFIED_OPERATOR_SUMMARY" if all_evaluated else "NONE",
            "candidate_benefit_verified": candidate_verified,
        },
        "completeness": {
            "expected": expected, "returned": returned,
            "protocol_valid": protocol, "timeouts": timeouts,
        },
        "comparison": {
            "eligible": False,
            "explanation": "Comparison history has not been linked yet.",
            "history_points": 0,
            "fingerprint": fingerprint,
            "basis": basis,
            "break_reasons": break_reasons,
            "points": [],
            "baseline_arm_id": baseline_id,
            "candidate_arm_id": candidate_id,
        },
        "arms": arms,
        "uncertainty": uncertainty,
        "provenance": {
            "trial_ids": [trial["trial_id"] for trial in trials],
            "manifest_sha256": manifests,
            "run_sha256": sorted({trial["transport_evaluation_sha256"] for trial in trials if isinstance(trial["transport_evaluation_sha256"], str)}),
            "evaluation_sha256": sorted({
                trial["evaluation"]["record_sha256"] for trial in trials
                if isinstance(trial.get("evaluation"), dict)
            }),
            "summary_sha256": sorted({
                trial["evaluation"]["summary_sha256"] for trial in trials
                if isinstance(trial.get("evaluation"), dict)
            }),
            "source_commits": source_commits,
        },
        "details": {
            "fixture_count": len(trials[0]["plan"].get("fixture_ids") or []) or None,
            "repeat_count": len(trials),
            "grader_bound": bool(
                isinstance(trials[0]["plan"].get("expected_grader_sha256"), dict)
                and trials[0]["plan"].get("expected_grader_sha256")
            ),
            "note": (
                "Counts come from operator-recorded summaries and do not establish scientific benefit."
            ),
        },
        "interpretation_note": (
            "Descriptive capability check only: the arms differ in model, maximum context lane, and reasoning mode. Scores and timing cannot identify a causal model advantage."
            if context_claim_limit else
            "Descriptive three-arm pilot only: xhigh, medium, and adaptive effort are shown independently. Planned attempts are task-arm slots; retries or escalations can produce more model calls. No two-arm upgrade comparison or production recommendation is inferred."
            if role_effort_claim_limit else
            "Public historical single-arm repair baseline. Tasks and historical fixes are public, so this result is not contamination-resistant and cannot establish an upgrade."
            if historical_claim_limit else
            "Operator-recorded counts preserve failures in their declared denominators; they do not verify a candidate benefit."
        ),
        "_week": week,
    }
    return result


def _comparison_point(family: dict[str, Any]) -> dict[str, Any]:
    arm_by_id = {arm["id"]: arm for arm in family["arms"]}
    baseline = arm_by_id.get(family["comparison"]["baseline_arm_id"])
    candidate = arm_by_id.get(family["comparison"]["candidate_arm_id"])

    def point_arm(arm: dict[str, Any] | None) -> dict[str, Any]:
        return {
            "arm_id": arm.get("id") if arm else "unknown",
            "success_rate": arm["metrics"]["success_rate"] if arm else None,
            "successes": (
                arm.get("objective_successes")
                if arm and arm.get("objective_total") is not None
                else arm.get("repair_successes") if arm else None
            ),
            "success_denominator": (
                arm.get("objective_total")
                if arm and arm.get("objective_total") is not None
                else arm.get("repair_total") if arm else None
            ),
        }

    baseline_point = point_arm(baseline)
    candidate_point = point_arm(candidate)
    delta = None
    if baseline and candidate:
        first = baseline["metrics"]["success_rate"]
        second = candidate["metrics"]["success_rate"]
        if first is not None and second is not None:
            delta = second - first
    return {
        "week": family["_week"],
        "status": family["status"],
        "baseline": baseline_point,
        "candidate": candidate_point,
        "delta_success_rate": delta,
        "trial_count": family["details"]["repeat_count"],
    }


def _attach_comparisons(families: list[dict[str, Any]]) -> None:
    by_fingerprint: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_lineage: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for family in families:
        by_lineage[family["id"]].append(family)
        fingerprint = family["comparison"]["fingerprint"]
        if fingerprint:
            by_fingerprint[fingerprint].append(family)
    for family in families:
        comparison = family["comparison"]
        fingerprint = comparison["fingerprint"]
        peers = sorted(by_fingerprint.get(fingerprint, []), key=lambda item: item["_week"])
        comparison["points"] = [_comparison_point(peer) for peer in peers]
        comparison["history_points"] = len(peers)
        if comparison["break_reasons"]:
            comparison["eligible"] = False
            comparison["explanation"] = "; ".join(comparison["break_reasons"])
        elif len(peers) < 2:
            comparison["eligible"] = False
            lineage_peers = by_lineage[family["id"]]
            comparison["explanation"] = (
                "A prior suite run exists, but its cohort contract changed."
                if len(lineage_peers) > 1 else
                "No prior comparable cohort has been recorded."
            )
        else:
            comparison["eligible"] = True
            comparison["explanation"] = (
                f"{len(peers)} weeks share the frozen cohort contract; trend uses within-week candidate-minus-baseline effects."
            )
    for family in families:
        family["comparison"].pop("baseline_arm_id", None)
        family["comparison"].pop("candidate_arm_id", None)
        family.pop("_week", None)


def _read_reviews(review_root: Path, warnings: list[dict[str, str]]) -> tuple[dict[str, dict[str, Any]], bool]:
    try:
        root = _root(review_root, label="weekly review root")
    except ProjectionError as exc:
        _warning(warnings, "review_root_invalid", "reviews", str(exc))
        return {}, False
    if root is None:
        _warning(warnings, "review_root_missing", "reviews", "No weekly review history is available.")
        return {}, False
    try:
        directories = [
            path for path in root.iterdir()
            if _WEEK_RE.fullmatch(path.name) and path.is_dir() and not path.is_symlink()
            and path.resolve() == path.absolute()
        ]
    except OSError as exc:
        _warning(warnings, "review_root_unreadable", "reviews", str(exc))
        return {}, False
    if len(directories) > MAX_SOURCE_FILES:
        _warning(warnings, "review_root_unbounded", "reviews", "Review week count exceeds the bound.")
        return {}, False
    reviews: dict[str, dict[str, Any]] = {}
    for directory in sorted(directories, key=lambda item: item.name):
        week = directory.name
        cycle_path = directory / "cycle_report.json"
        report_path = directory / "review" / "weekly_report.json"
        try:
            cycle, _ = _safe_file(cycle_path, root=root, label=f"review/{week}/cycle_report")
            report, _ = _safe_file(report_path, root=root, label=f"review/{week}/weekly_report")
            if (
                cycle.get("schema_version") != "weekly-upgrade-cycle/v1"
                or report.get("schema_version") != "weekly-upgrade-report-v1"
                or cycle.get("week_id") != week
                or report.get("week_id") != week
            ):
                raise ProjectionError("weekly review schemas or week bindings differ")
            proposal = report.get("proposal")
            card = report.get("experiment_card")
            report_status = report.get("status")
            cycle_review = cycle.get("review")
            if not isinstance(cycle_review, dict) or any((
                cycle_review.get("status") != report_status,
                cycle_review.get("run_id") != report.get("run_id"),
                cycle_review.get("proposal_sha256") != report.get("proposal_sha256"),
                cycle_review.get("snapshot_sha256") != report.get("snapshot_sha256"),
                cycle_review.get("frontier_calls_used") != report.get("frontier_calls_used"),
                report.get("proposal_sha256") != (
                    _sha(proposal) if isinstance(proposal, dict) else None
                ),
                cycle_review.get("experiment_card_sha256") != (
                    _sha(card) if isinstance(card, dict) else None
                ),
            )):
                raise ProjectionError("weekly cycle and review receipts are not cross-bound")
            decision = (
                "admitted" if isinstance(card, dict) else
                "revision_required" if report_status == "REVISION_REQUIRED" else
                "rejected" if report_status in {"REJECTED", "INVALID_REPORT"} else
                "no_card"
            )
            source = cycle.get("source") if isinstance(cycle.get("source"), dict) else {}
            source_summary = source.get("summary") if isinstance(source.get("summary"), dict) else {}
            reviews[week] = {
                "status": str(cycle.get("status")) if cycle.get("status") is not None else None,
                "decision": decision,
                "experiment_proposals": int(isinstance(proposal, dict)),
                "source_count": _count(source_summary.get("fetched")),
                "frontier_calls": _count(report.get("frontier_calls_used")),
            }
        except ProjectionError as exc:
            _warning(warnings, "review_invalid", f"reviews/{week}", str(exc))
    return reviews, True


def _read_receipt(path: Path, *, root: Path, schema: str, label: str) -> dict[str, Any] | None:
    if not path.exists():
        return None
    value, _ = _safe_file(path, root=root, label=label)
    if value.get("schema_version") != schema:
        raise ProjectionError(f"{label} has an unsupported schema")
    return value


def _automation(
    state_root: Path,
    warnings: list[dict[str, str]],
) -> tuple[dict[str, Any], bool, bool, dict[str, Any] | None]:
    completion: dict[str, Any] | None = None
    activation: dict[str, Any] | None = None
    completion_ok = False
    activation_ok = False
    try:
        completion = _read_receipt(
            state_root / "completion.json", root=state_root,
            schema="weekly-upgrade-implementation-completion/v1", label="completion receipt",
        )
        completion_ok = completion is not None
    except ProjectionError as exc:
        _warning(warnings, "completion_invalid", "completion", str(exc))
    try:
        activation_dirs = _safe_children(
            state_root, re.compile(r"activation-[0-9]{4}-[0-9]{2}-[0-9]{2}"),
            label="weekly upgrade state",
        )
        for directory in reversed(activation_dirs):
            if not directory.is_dir() or directory.is_symlink() or directory.resolve() != directory.absolute():
                continue
            candidate = _read_receipt(
                directory / "activation.json", root=state_root,
                schema="weekly-upgrade-activation/v1", label="activation receipt",
            )
            if candidate is not None:
                activation = candidate
                break
        activation_ok = activation is not None
    except ProjectionError as exc:
        _warning(warnings, "activation_invalid", "activation", str(exc))
    mode = "unknown"
    status = None
    activated_at = None
    schedule = None
    promotion_enabled = None
    if activation is not None:
        status = activation.get("status") if isinstance(activation.get("status"), str) else None
        activated_at = (
            activation.get("activated_at")
            if _parse_time(activation.get("activated_at")) is not None else None
        )
        if activation.get("review_only") is True:
            mode = "review_only"
        elif activation.get("trial_manifest") is not None:
            mode = "trial_allowlisted"
        elif status and "ACTIVE" not in status:
            mode = "disabled"
        cron = activation.get("cron_line")
        if isinstance(cron, str):
            fields = cron.split()
            if len(fields) >= 5 and fields[:5] == ["30", "5", "*", "*", "0"]:
                schedule = "Sunday 05:30 UTC"
        promotion = activation.get("automatic_promotion_enabled")
        promotion_enabled = promotion if isinstance(promotion, bool) else None
    return {
        "mode": mode,
        "status": status,
        "activated_at": activated_at,
        "schedule": schedule,
        "promotion_enabled": promotion_enabled,
    }, completion_ok, activation_ok, completion


def compose_progress(
    *,
    canonical_root: Path = DEFAULT_CANONICAL_ROOT,
    upgrade_runs_root: Path = DEFAULT_UPGRADE_RUNS_ROOT,
    review_runs_root: Path = DEFAULT_REVIEW_RUNS_ROOT,
    local_research_root: Path | None = None,
    now: Callable[[], datetime] | datetime | None = None,
) -> dict[str, Any]:
    current = _now(now)
    current_week = _iso_week(current)
    warnings: list[dict[str, str]] = []
    canonical = canonical_root.absolute()
    state_root = canonical / "run_state" / "weekly_upgrade"
    trials_root = state_root / "trials"
    evaluations_root = state_root / "evaluations"

    automation, completion_ok, activation_ok, _completion = _automation(
        state_root, warnings
    ) if state_root.exists() else (
        {"mode": "unknown", "status": None, "activated_at": None,
         "schedule": None, "promotion_enabled": None}, False, False, None
    )

    trials: list[dict[str, Any]] = []
    trials_available = False
    try:
        trial_paths = _safe_children(trials_root, re.compile(r".+\.json"), label="trial journals")
        trials_available = _root(trials_root, label="trial journals") is not None
        for path in trial_paths:
            if not _TRIAL_ID_RE.fullmatch(path.stem):
                _warning(warnings, "trial_name_invalid", "trials", f"Ignored unsafe trial name {path.name!r}.")
                continue
            try:
                trial = _validate_trial(
                    path, trials_root=trials_root,
                    upgrade_runs_root=upgrade_runs_root,
                )
                trials.append(trial)
                if trial.get("run_warning"):
                    _warning(
                        warnings, "trial_artifact_invalid", f"trials/{trial['trial_id']}",
                        str(trial["run_warning"]),
                    )
            except ProjectionError as exc:
                _warning(warnings, "trial_invalid", f"trials/{path.stem}", str(exc))
    except ProjectionError as exc:
        _warning(warnings, "trials_unavailable", "trials", str(exc))

    evaluations_available = False
    valid_evaluations = 0
    by_trial = {trial["trial_id"]: trial for trial in trials}
    try:
        evaluation_paths = _safe_children(
            evaluations_root, re.compile(r".+\.json"), label="evaluation summaries"
        )
        evaluations_available = _root(evaluations_root, label="evaluation summaries") is not None
        seen: set[str] = set()
        for path in evaluation_paths:
            trial = by_trial.get(path.stem)
            if trial is None:
                _warning(warnings, "evaluation_orphan", "evaluations", f"Ignored unbound evaluation {path.name!r}.")
                continue
            try:
                trial["evaluation"] = _validate_evaluation(
                    path, evaluations_root=evaluations_root, trial=trial
                )
                valid_evaluations += 1
                seen.add(path.stem)
            except ProjectionError as exc:
                trial["evaluation_invalid"] = True
                _warning(warnings, "evaluation_invalid", f"evaluations/{path.stem}", str(exc))
        for trial in trials:
            if trial["trial_id"] not in seen:
                _warning(
                    warnings, "evaluation_missing", f"evaluations/{trial['trial_id']}",
                    "No bound operator summary is available.",
                )
    except ProjectionError as exc:
        _warning(warnings, "evaluations_unavailable", "evaluations", str(exc))

    budget_rows: dict[str, dict[str, Any]] = {}
    budget_states: dict[str, dict[str, Any]] = {}
    budget_available = False
    budget_path = canonical / "run_state" / "weekly_upgrade_budget.jsonl"
    try:
        if budget_path.exists():
            budget_states, _ = _validate_budget(budget_path)
            budget_rows = _budget_rows(budget_states)
            budget_available = True
            for week, budget in budget_rows.items():
                if budget["overrun_minutes"] > 0:
                    _warning(
                        warnings, "budget_overrun", f"budget/{week}",
                        "Recorded charges exceed the weekly allowance.",
                    )
        else:
            _warning(warnings, "budget_missing", "budget", "No budget journal is available.")
    except (OSError, ProjectionError) as exc:
        _warning(warnings, "budget_invalid", "budget", str(exc))

    if budget_available:
        reconciled: list[dict[str, Any]] = []
        for trial in trials:
            state = budget_states.get(trial["trial_id"])
            receipt = trial["result"].get("budget_receipt")
            fields_match = isinstance(state, dict) and isinstance(receipt, dict) and all((
                state.get("week_id") == receipt.get("week_id"),
                state.get("status") == receipt.get("status"),
                state.get("manifest_sha256") == receipt.get("manifest_sha256"),
                state.get("manifest_sha256") == trial["binding_sha256"],
                state.get("reserved_s") == _finite_number(receipt.get("reserved_s")),
                state.get("elapsed_s") == _finite_number(receipt.get("elapsed_s")),
                state.get("charged_s") == _finite_number(receipt.get("charged_s")),
                state.get("state") == "finished",
            ))
            if fields_match:
                reconciled.append(trial)
            else:
                _warning(
                    warnings, "trial_budget_mismatch", f"trials/{trial['trial_id']}",
                    "Trial receipt does not match the canonical budget ledger and was withheld.",
                )
        trials = reconciled
        valid_evaluations = sum(isinstance(trial.get("evaluation"), dict) for trial in trials)
        trial_ids = {trial["trial_id"] for trial in trials}
        for run_id, state in budget_states.items():
            if (
                state.get("state") == "finished" and state.get("status") != "imported"
                and run_id not in trial_ids
            ):
                _warning(
                    warnings, "budget_orphan", f"budget/{state['week_id']}",
                    "A terminal budget charge has no matching trusted trial journal.",
                )

    reviews, reviews_available = _read_reviews(review_runs_root, warnings)

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    labels: dict[tuple[str, str], str] = {}
    for trial in trials:
        family_id, label = _suite_lineage(
            trial["manifest_path"], trial["plan"].get("kind")
        )
        key = (trial["week"], family_id)
        grouped[key].append(trial)
        labels[key] = label
    families = [
        _family(week, family_id, labels[(week, family_id)], family_trials)
        for (week, family_id), family_trials in sorted(grouped.items())
    ]
    families_by_week: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for family in families:
        families_by_week[family["_week"]].append(family)
    _attach_comparisons(families)

    weeks_seen = set(budget_rows) | set(reviews) | {trial["week"] for trial in trials}
    weeks: list[dict[str, Any]] = []
    for week in sorted(weeks_seen, reverse=True):
        week_trials = [trial for trial in trials if trial["week"] == week]
        terminal = len(week_trials)
        recorded = sum(isinstance(trial.get("evaluation"), dict) for trial in week_trials)
        complete = sum(
            isinstance(trial["result"].get("evaluation"), dict)
            and trial["result"]["evaluation"].get("execution_complete") is True
            for trial in week_trials
        )
        if terminal:
            status = "measured" if all(
                trial["result"].get("status") == "completed" for trial in week_trials
            ) else "partial"
        elif week in reviews:
            status = "reviewed"
        else:
            status = "unavailable"
        weeks.append({
            "week": week,
            "status": status,
            "terminal_trials": terminal,
            "recorded_evaluations": recorded,
            "complete_executions": complete,
            "review": reviews.get(week),
            "budget": budget_rows.get(week),
            "families": sorted(families_by_week.get(week, []), key=lambda item: item["label"]),
        })

    comparable_transitions = sum(
        max(0, len(group) - 1) for group in {
            family["comparison"]["fingerprint"]: [
                peer for peer in families
                if peer["comparison"]["fingerprint"] == family["comparison"]["fingerprint"]
            ]
            for family in families if family["comparison"]["fingerprint"]
        }.values()
    )
    upgrade_established: bool | None = (
        False if valid_evaluations else None
    )
    headline = (
        "No candidate benefit is verified in the recorded benchmark evidence."
        if valid_evaluations else "No validated benchmark evidence is available yet."
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": current.isoformat().replace("+00:00", "Z"),
        "current_week": current_week,
        "availability": {
            "trials": trials_available,
            "evaluations": evaluations_available,
            "budget": budget_available,
            "completion": completion_ok,
            "activation": activation_ok,
            "reviews": reviews_available,
        },
        "automation": automation,
        "summary": {
            "headline": headline,
            "upgrade_established": upgrade_established,
            "weeks_seen": len(weeks),
            "latest_week": weeks[0]["week"] if weeks else None,
            "terminal_trials": len(trials),
            "recorded_evaluations": valid_evaluations,
            "complete_executions": sum(
                isinstance(trial["result"].get("evaluation"), dict)
                and trial["result"]["evaluation"].get("execution_complete") is True
                for trial in trials
            ),
            "comparable_transitions": comparable_transitions,
            "current_week_budget": budget_rows.get(current_week),
        },
        "warnings": warnings,
        "weeks": weeks,
        "research_pipeline": project_research_pipeline(
            canonical_root=canonical,
            now=current,
        ),
        "local_model_research": project_local_research(local_research_root),
    }


def register(
    app,
    *,
    canonical_root: Path = DEFAULT_CANONICAL_ROOT,
    upgrade_runs_root: Path = DEFAULT_UPGRADE_RUNS_ROOT,
    review_runs_root: Path = DEFAULT_REVIEW_RUNS_ROOT,
    local_research_root: Path | None = DEFAULT_RESEARCH_ROOT,
    now: Callable[[], datetime] | datetime | None = None,
) -> None:
    """Register the progress endpoint with fully injectable read roots."""
    router = APIRouter()

    @router.get("/api/weekly_upgrade/progress")
    def weekly_upgrade_progress():
        return compose_progress(
            canonical_root=Path(canonical_root),
            upgrade_runs_root=Path(upgrade_runs_root),
            review_runs_root=Path(review_runs_root),
            local_research_root=local_research_root,
            now=now,
        )

    app.include_router(router)
