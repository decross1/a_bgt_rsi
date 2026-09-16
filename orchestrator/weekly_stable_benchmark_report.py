"""Bounded stable-benchmark summary for the existing weekly review.

This module only projects already-written public receipts.  It does not start a
runtime, replay private responses, grade an answer, create a registration, or
schedule a future run.  The weekly report deliberately carries a small subset
of the generic benchmark-program read model so operator reports remain useful
without becoming another benchmark UI or result lineage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

SCHEMA_VERSION = "weekly-stable-benchmark-snapshot/v1"
MAX_ARMS = 8
MAX_RESULT_ROWS = 16
MAX_MATCHED_ROWS = 16
MAX_MATCHED_HISTORY_ROWS = 256
MAX_WARNINGS = 8
MAX_TEXT = 500
MAX_REVIEW_BYTES = 16 * 1024 * 1024
SUNDAY_REPORT_SCHEMA = "weekly-stable-benchmark-sunday-report/v1"


class WeeklyBenchmarkProjectionError(ValueError):
    """The public benchmark projection cannot be safely summarized."""


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise WeeklyBenchmarkProjectionError("weekly report is not canonical JSON") from exc


def _sha(value: Any) -> str:
    return hashlib.sha256(value if isinstance(value, bytes) else _canonical(value)).hexdigest()


def _strict_object(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.resolve() != path.absolute():
        raise WeeklyBenchmarkProjectionError(f"weekly artifact is absent or redirected: {path.name}")
    size = path.stat().st_size
    if size > MAX_REVIEW_BYTES:
        raise WeeklyBenchmarkProjectionError(f"weekly artifact exceeds the read bound: {path.name}")

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key {key}")
            result[key] = value
        return result

    try:
        raw = path.read_bytes()
        if len(raw) != size:
            raise ValueError("artifact changed during read")
        value = json.loads(
            raw, object_pairs_hook=unique,
            parse_constant=lambda token: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON number {token}")
            ),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise WeeklyBenchmarkProjectionError(f"weekly artifact is malformed: {path.name}") from exc
    if not isinstance(value, dict):
        raise WeeklyBenchmarkProjectionError(f"weekly artifact is not an object: {path.name}")
    return value


def _review_context_empty(*, week_id: str, status: str, reason: str) -> dict[str, Any]:
    return {
        "status": status,
        "week_id": week_id,
        "cycle_status": None,
        "review_status": None,
        "reviewed_at": None,
        "plan_repo_root": None,
        "plan_repo_head": None,
        "cycle_plan_sha256": None,
        "weekly_report_sha256": None,
        "reason": reason,
        "recovery": None,
        "frontier_calls_repeated": False,
    }


def inspect_weekly_review_context(week_dir: Path, *, week_id: str) -> dict[str, Any]:
    """Verify whether a prior same-week provider review is terminal and immutable."""
    week_dir = Path(week_dir).absolute()
    paths = {
        "plan": week_dir / "cycle_plan.json",
        "cycle": week_dir / "cycle_report.json",
        "report": week_dir / "review/weekly_report.json",
        "manifest": week_dir / "review/run_manifest.json",
    }
    present = {name: path.exists() or path.is_symlink() for name, path in paths.items()}
    if not any(present.values()):
        return _review_context_empty(
            week_id=week_id, status="no_prior_review",
            reason="No immutable provider review exists for this UTC ISO week.",
        )

    plan: dict[str, Any] | None = None
    try:
        plan = _strict_object(paths["plan"])
        if not all(present.values()):
            raise WeeklyBenchmarkProjectionError("weekly terminal artifact set is incomplete")
        cycle = _strict_object(paths["cycle"])
        report = _strict_object(paths["report"])
        manifest = _strict_object(paths["manifest"])

        # Reuse the closed review schemas lazily; importing this module from
        # weekly_upgrade remains safe because this function runs after imports.
        from orchestrator import weekly_upgrade as review

        review._validate("report", report)
        review._validate_manifest(manifest)
        if (
            plan.get("schema_version") != "weekly-upgrade-cycle-plan/v1"
            or plan.get("week_id") != week_id
            or cycle.get("schema_version") != "weekly-upgrade-cycle/v1"
            or cycle.get("week_id") != week_id
            or cycle.get("cycle_plan_sha256") != _sha(plan)
            or report.get("week_id") != week_id
            or manifest.get("week_id") != week_id
            or report.get("run_id") != manifest.get("run_id")
            or report.get("snapshot_sha256") != manifest.get("snapshot_sha256")
            or report.get("run_manifest_sha256") != _sha(manifest)
            or cycle.get("status") != "REVIEW_COMPLETE"
            or cycle.get("trial") is not None
            or cycle.get("production_change_authorized") is not False
            or cycle.get("promotion_authorized") is not False
            or report.get("status") not in {"NO_CHANGE", "REVISION_REQUIRED"}
            or report.get("experiment_card") is not None
        ):
            raise WeeklyBenchmarkProjectionError("weekly terminal bindings differ")
        cycle_review = cycle.get("review")
        if not isinstance(cycle_review, dict) or any((
            cycle_review.get("status") != report.get("status"),
            cycle_review.get("run_id") != report.get("run_id"),
            cycle_review.get("snapshot_sha256") != report.get("snapshot_sha256"),
            cycle_review.get("proposal_sha256") != report.get("proposal_sha256"),
            cycle_review.get("frontier_calls_used") != report.get("frontier_calls_used"),
            cycle_review.get("experiment_card_sha256") is not None,
        )):
            raise WeeklyBenchmarkProjectionError("weekly cycle/review cross-binding differs")
        receipt_dir = week_dir / "review/receipts"
        receipts = sorted(receipt_dir.glob("*.json")) if receipt_dir.is_dir() else []
        if len(receipts) != report.get("frontier_calls_used") or len(receipts) > 2:
            raise WeeklyBenchmarkProjectionError("weekly provider receipt count differs")
        for ordinal, receipt_path in enumerate(receipts, 1):
            receipt = _strict_object(receipt_path)
            if (receipt.get("ordinal") != ordinal or receipt.get("status") != "completed"
                    or receipt.get("vendor") not in {"codex", "claude"}):
                raise WeeklyBenchmarkProjectionError("weekly provider receipt is not terminal")
        repo_root = _text(plan.get("repo_root"), label="prior review repo root", maximum=500)
        repo_head = _text(plan.get("repo_head"), label="prior review repo head", maximum=64)
        return {
            "status": "terminal_immutable_review",
            "week_id": week_id,
            "cycle_status": cycle["status"],
            "review_status": report["status"],
            "reviewed_at": _text(report.get("reviewed_at"), label="reviewed at", maximum=64),
            "plan_repo_root": repo_root,
            "plan_repo_head": repo_head,
            "cycle_plan_sha256": _sha(plan),
            "weekly_report_sha256": _sha(paths["report"].read_bytes()),
            "reason": (
                "The provider review is terminal under its original repository context; "
                "the Sunday owner must not repeat its calls."
            ),
            "recovery": None,
            "frontier_calls_repeated": False,
        }
    except (OSError, ValueError, TypeError, KeyError, WeeklyBenchmarkProjectionError) as exc:
        repo_root = plan.get("repo_root") if isinstance(plan, dict) else None
        repo_head = plan.get("repo_head") if isinstance(plan, dict) else None
        bounded_root = repo_root if isinstance(repo_root, str) and len(repo_root) <= 500 else None
        bounded_head = repo_head if isinstance(repo_head, str) and len(repo_head) <= 64 else None
        result = _review_context_empty(
            week_id=week_id, status="incomplete_original_context_required",
            reason=f"Existing same-week review artifacts are not a verified terminal set: {type(exc).__name__}.",
        )
        result.update(
            plan_repo_root=bounded_root,
            plan_repo_head=bounded_head,
            recovery=(
                "Resume only from the repository root and commit bound by cycle_plan.json "
                "with the same output root and owner claim, or wait for the next UTC ISO week. "
                "Do not retry reserved or completed provider calls."
            ),
        )
        return result


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _text(value: Any, *, label: str, maximum: int = MAX_TEXT) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise WeeklyBenchmarkProjectionError(f"{label} is not a bounded string")
    return value


def _optional_text(value: Any, *, label: str, maximum: int = MAX_TEXT) -> str | None:
    if value is None:
        return None
    return _text(value, label=label, maximum=maximum)


def _count(value: Any, *, label: str) -> int | None:
    if value is None:
        return None
    if type(value) is not int or not 0 <= value <= 1_000_000:
        raise WeeklyBenchmarkProjectionError(f"{label} is not a bounded count")
    return value


def _number(value: Any, *, label: str) -> float | None:
    if value is None:
        return None
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(float(value)) or not 0 <= float(value) <= 1_000_000_000):
        raise WeeklyBenchmarkProjectionError(f"{label} is not a bounded number")
    return float(value)


def _load_projection(
    *, repo: Path, program_root: Path | None, observed_at: datetime,
) -> dict[str, Any]:
    # Import lazily so an offline plan that has no stable release still imports.
    from ui.backend.benchmark_program import compose_program

    return compose_program(
        repo=repo, root=program_root, now=observed_at, include_runtime=False,
    )


def _result_row(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise WeeklyBenchmarkProjectionError("benchmark result row is not an object")
    result = {
        "construct": _text(value.get("construct"), label="result construct", maximum=120),
        "domain": _text(value.get("domain"), label="result domain", maximum=120),
        "panel": _text(value.get("panel"), label="result panel", maximum=120),
        "successful_units": _count(value.get("successful_units"), label="successful units"),
        "planned_units": _count(value.get("planned_units"), label="planned units"),
        "metric": _text(value.get("metric"), label="result metric", maximum=120),
        "unit": _text(value.get("unit"), label="result unit", maximum=40),
        "value": _number(value.get("value"), label="result value"),
    }
    if (result["successful_units"] is None or result["planned_units"] is None
            or result["value"] is None):
        raise WeeklyBenchmarkProjectionError("benchmark result metric is incomplete")
    if result["successful_units"] > result["planned_units"]:
        raise WeeklyBenchmarkProjectionError("benchmark successful count exceeds denominator")
    return result


def _arm(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise WeeklyBenchmarkProjectionError("benchmark arm is not an object")
    rows = value.get("results")
    if not isinstance(rows, list) or len(rows) > MAX_RESULT_ROWS:
        raise WeeklyBenchmarkProjectionError("benchmark arm results exceed the row bound")
    result = {
        "arm_id": _text(value.get("arm_id"), label="arm id", maximum=160),
        "label": _text(value.get("label"), label="arm label", maximum=240),
        "role": _optional_text(value.get("role"), label="arm role", maximum=40),
        "receipt_admission_status": _text(
            value.get("admission_status"), label="arm admission status", maximum=80,
        ),
        "terminal_status": _text(
            value.get("observed_terminal_status"), label="arm terminal status", maximum=80,
        ),
        "replay_status": _text(
            value.get("replay_status"), label="arm replay status", maximum=80,
        ),
        "run_id": _optional_text(value.get("run_id"), label="run id", maximum=200),
        "registered_at": _optional_text(
            value.get("registered_at"), label="registration time", maximum=64,
        ),
        "started_at": _optional_text(value.get("started_at"), label="start time", maximum=64),
        "finished_at": _optional_text(value.get("finished_at"), label="finish time", maximum=64),
        "completed_units": _count(value.get("completed_units"), label="completed units"),
        "model_calls": _count(value.get("model_calls"), label="model calls"),
        "wall_seconds": _number(value.get("wall_seconds"), label="wall seconds"),
        "results": [_result_row(row) for row in rows],
        "result_interpretation": (
            "receipt_verified_grader_output_only"
            if value.get("admission_status") == "admitted" and rows else "not_scored"
        ),
    }
    return result


def _matched_row(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise WeeklyBenchmarkProjectionError("matched result is not an object")
    discordant = value.get("discordant_counts")
    if not isinstance(discordant, dict):
        raise WeeklyBenchmarkProjectionError("matched result discordance is absent")
    result = {
        "domain": _text(value.get("domain"), label="matched domain", maximum=120),
        "mechanism": _text(value.get("mechanism"), label="matched mechanism", maximum=120),
        "panel": _text(value.get("panel"), label="matched panel", maximum=120),
        "baseline_arm": _text(value.get("baseline_arm"), label="baseline arm", maximum=240),
        "candidate_arm": _text(value.get("candidate_arm"), label="candidate arm", maximum=240),
        "baseline_value": _number(value.get("baseline_value"), label="baseline value"),
        "candidate_value": _number(value.get("candidate_value"), label="candidate value"),
        "delta": _signed_number(value.get("delta"), label="matched delta"),
        "metric": _text(value.get("metric"), label="matched metric", maximum=120),
        "unit": _text(value.get("unit"), label="matched unit", maximum=40),
        "n_pairs": _count(value.get("n_pairs"), label="matched pair count"),
        "baseline_only": _count(discordant.get("baseline_only"), label="baseline-only count"),
        "candidate_only": _count(discordant.get("candidate_only"), label="candidate-only count"),
        "status": _text(value.get("status"), label="matched status", maximum=80),
    }
    if (result["baseline_value"] is None or result["candidate_value"] is None
            or result["n_pairs"] is None or result["baseline_only"] is None
            or result["candidate_only"] is None):
        raise WeeklyBenchmarkProjectionError("matched result metric is incomplete")
    return result


def _signed_number(value: Any, *, label: str) -> float:
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(float(value)) or abs(float(value)) > 1_000_000_000):
        raise WeeklyBenchmarkProjectionError(f"{label} is not a bounded number")
    return float(value)


def _measurement_review(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise WeeklyBenchmarkProjectionError("measurement review is not an object")
    status = _text(value.get("status"), label="measurement review status", maximum=40)
    if status not in {"commissioning_only", "unavailable"}:
        raise WeeklyBenchmarkProjectionError("measurement review status is unknown")
    if value.get("comparative_quality_allowed") is not False:
        raise WeeklyBenchmarkProjectionError("measurement review permits an unsupported quality claim")
    task_ids = value.get("affected_task_ids")
    if (not isinstance(task_ids, list) or len(task_ids) > 64
            or any(not isinstance(item, str) or not item or len(item) > 160 for item in task_ids)
            or len(set(task_ids)) != len(task_ids)):
        raise WeeklyBenchmarkProjectionError("measurement review task IDs are malformed")
    source_sha = value.get("source_sha256")
    if source_sha is not None:
        source_sha = _text(source_sha, label="measurement review hash", maximum=64)
        if len(source_sha) != 64 or any(char not in "0123456789abcdef" for char in source_sha):
            raise WeeklyBenchmarkProjectionError("measurement review hash is malformed")
    if status == "commissioning_only" and source_sha is None:
        raise WeeklyBenchmarkProjectionError("verified measurement review lacks its source hash")
    return {
        "status": status,
        "title": _text(value.get("title"), label="measurement review title", maximum=500),
        "summary": _text(value.get("summary"), label="measurement review summary", maximum=2_000),
        "affected_task_ids": list(task_ids),
        "comparative_quality_allowed": False,
        "source_sha256": source_sha,
    }


def _unavailable(observed_at: datetime, warning: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "observed_at": _iso(observed_at),
        "status": "unavailable",
        "release": None,
        "measurement_review": None,
        "current_cohort": None,
        "next_run_preregistration": {
            "mode": "manual_source_controlled_preregistration",
            "eligibility": "release_evidence_unavailable",
            "automatic_execution": False,
            "automatic_scheduling": False,
            "paid_api_calls": 0,
            "definition_sha256": None,
            "registration_path_template": "docs/benchmarks/registrations/<comparison_id>.json",
            "required_sequence": [],
        },
        "scope": _scope("projection_unavailable"),
        "warnings": [warning[:MAX_TEXT]],
    }


def _scope(measurement_validity: str) -> dict[str, Any]:
    return {
        "claim": "small fixed regression canary with separate model and harness rows",
        "omnibus_score": False,
        "full_orchestrator_claim": False,
        "external_rotations_included": False,
        "external_rotation_cadence": "monthly_or_preregistered_trigger",
        "external_rotation_rule": (
            "Public benchmark rotations require their own pinned version, license, "
            "oracle validation, resource pilot, and result lineage."
        ),
        "receipt_admission_meaning": (
            "Admission verifies the registered receipt, replay, supervision, and resource chain; "
            "it does not establish fixture-contract validity or authorize promotion."
        ),
        "measurement_validity": measurement_validity,
        "promotion_authorized": False,
    }


def build_weekly_benchmark_snapshot(
    *,
    repo: Path,
    program_root: Path | None = None,
    observed_at: datetime,
    projection_loader: Callable[..., dict[str, Any]] = _load_projection,
) -> dict[str, Any]:
    """Return a bounded weekly summary of one already-published release."""
    if not isinstance(observed_at, datetime) or observed_at.tzinfo is None:
        raise WeeklyBenchmarkProjectionError("weekly benchmark clock must be timezone aware")
    observed_at = observed_at.astimezone(timezone.utc)
    try:
        repo = Path(repo).absolute()
        registration_root = repo / "docs/benchmarks/registrations"
        if (registration_root.is_symlink() or not registration_root.is_dir()
                or not any(path.is_file() and not path.is_symlink()
                           for path in registration_root.glob("*.json"))):
            return _unavailable(
                observed_at,
                "source-controlled stable benchmark registration is unavailable",
            )
        projection = projection_loader(
            repo=repo,
            program_root=(Path(program_root) if program_root is not None else None),
            observed_at=observed_at,
        )
        if not isinstance(projection, dict) or projection.get("schema_version") != "benchmark-program/v1":
            raise WeeklyBenchmarkProjectionError("benchmark read model has an unknown schema")
        release = projection.get("release")
        if not isinstance(release, dict):
            warnings = projection.get("warnings")
            detail = (warnings[0] if isinstance(warnings, list) and warnings
                      and isinstance(warnings[0], str) else "published release is unavailable")
            return _unavailable(observed_at, detail)

        release_status = _text(release.get("status"), label="release status", maximum=40)
        definition_sha = _text(
            release.get("definition_sha256"), label="definition hash", maximum=64,
        )
        if len(definition_sha) != 64 or any(char not in "0123456789abcdef" for char in definition_sha):
            raise WeeklyBenchmarkProjectionError("definition hash is malformed")
        release_summary = {
            "suite_id": _text(release.get("suite_id"), label="suite id", maximum=160),
            "version": _text(release.get("version"), label="release version", maximum=40),
            "status": release_status,
            "published_at": _optional_text(
                release.get("published_at"), label="publication time", maximum=64,
            ),
            "expires_at": _text(release.get("expires_at"), label="review time", maximum=64),
            "definition_sha256": definition_sha,
        }
        measurement_review = _measurement_review(projection.get("measurement_review"))

        progress = projection.get("progress")
        comparison = projection.get("comparison")
        if not isinstance(progress, dict) or not isinstance(comparison, dict):
            raise WeeklyBenchmarkProjectionError("benchmark progress is absent")
        comparison_id = _optional_text(
            progress.get("comparison_id"), label="comparison id", maximum=160,
        )
        history = comparison.get("history")
        matched = comparison.get("matched_results")
        if not isinstance(history, list) or len(history) > 32:
            raise WeeklyBenchmarkProjectionError("benchmark history exceeds the read bound")
        if not isinstance(matched, list) or len(matched) > MAX_MATCHED_HISTORY_ROWS:
            raise WeeklyBenchmarkProjectionError("matched results exceed the row bound")
        cohort_rows = [row for row in history if isinstance(row, dict)
                       and row.get("comparison_id") == comparison_id]
        if len(cohort_rows) > MAX_ARMS:
            raise WeeklyBenchmarkProjectionError("current cohort exceeds the arm bound")
        current_matched = [row for row in matched if isinstance(row, dict)
                           and row.get("comparison_id") == comparison_id]
        if len(current_matched) > MAX_MATCHED_ROWS:
            raise WeeklyBenchmarkProjectionError("current matched results exceed the row bound")
        arms = [_arm(row) for row in cohort_rows]
        matched_rows = [_matched_row(row) for row in current_matched]
        admitted = sum(arm["receipt_admission_status"] == "admitted" for arm in arms)
        unissued = sum(arm["terminal_status"] == "unissued" for arm in arms)
        cohort = {
            "comparison_id": comparison_id,
            "comparison_status": _text(
                comparison.get("status"), label="comparison status", maximum=80,
            ),
            "progress_status": _text(
                progress.get("status"), label="progress status", maximum=80,
            ),
            "completed_units": _count(progress.get("completed_units"), label="completed units"),
            "total_units": _count(progress.get("total_units"), label="total units"),
            "completed_calls": _count(progress.get("completed_calls"), label="completed calls"),
            "total_call_ceiling": _count(progress.get("total_calls"), label="call ceiling"),
            "receipt_admitted_arms": admitted,
            "unissued_arms": unissued,
            "paired_comparison_available": bool(matched_rows),
            "arms": arms,
            "matched_results": matched_rows,
        }

        if release_status != "frozen":
            eligibility = "explicit_release_review_required"
        elif measurement_review is None:
            eligibility = "manual_preregistration_required"
        elif measurement_review["status"] == "unavailable":
            eligibility = "measurement_review_required"
        else:
            eligibility = "corrected_release_required"
        sequence = [
            "Choose a new comparison_id and fixed role-specific arm manifests.",
            "Commit a registration binding definition, manifests, source maps, receipt directories, and any lifecycle plan before inference.",
            "Run only manually admitted arms under the supervised resource and restoration gates.",
            "Retain run, replay, supervision, admission, and unissued receipts under the same comparison cohort.",
            "Read results from the verified generic benchmark projection; do not rebase historical development runs.",
        ]
        if release_status != "frozen":
            sequence.insert(
                0,
                "Record an explicit unchanged-definition extension or publish a new semantic release before inference.",
            )
        elif eligibility == "corrected_release_required":
            sequence.insert(
                0,
                "Publish the prospectively corrected semantic release named by the measurement review before inference.",
            )
        elif eligibility == "measurement_review_required":
            sequence.insert(
                0,
                "Resolve the source-controlled measurement review before choosing another run.",
            )
        raw_warnings = projection.get("warnings")
        if not isinstance(raw_warnings, list):
            raise WeeklyBenchmarkProjectionError("benchmark warnings are malformed")
        warnings = [item[:MAX_TEXT] for item in raw_warnings[:MAX_WARNINGS]
                    if isinstance(item, str) and item]
        return {
            "schema_version": SCHEMA_VERSION,
            "observed_at": _iso(observed_at),
            "status": "available",
            "release": release_summary,
            "measurement_review": measurement_review,
            "current_cohort": cohort,
            "next_run_preregistration": {
                "mode": "manual_source_controlled_preregistration",
                "eligibility": eligibility,
                "automatic_execution": False,
                "automatic_scheduling": False,
                "paid_api_calls": 0,
                "definition_sha256": definition_sha,
                "registration_path_template": "docs/benchmarks/registrations/<comparison_id>.json",
                "required_sequence": sequence,
            },
            "scope": _scope(
                ("unreviewed_claims_withheld" if measurement_review is None
                 else "review_unavailable_claims_withheld"
                 if measurement_review["status"] == "unavailable"
                 else "commissioning_only")
            ),
            "warnings": warnings,
        }
    except (ImportError, OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError) as exc:
        return _unavailable(
            observed_at,
            f"stable benchmark projection unavailable: {type(exc).__name__}",
        )


def _safe_report_directory(output_root: Path, week_id: str) -> Path:
    root = Path(output_root).expanduser().absolute()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise WeeklyBenchmarkProjectionError("weekly output root cannot be created") from exc
    if root.is_symlink() or not root.is_dir() or root.resolve() != root:
        raise WeeklyBenchmarkProjectionError("weekly output root is redirected")
    week_dir = root / week_id
    try:
        week_dir.mkdir(exist_ok=True)
    except OSError as exc:
        raise WeeklyBenchmarkProjectionError("weekly output directory cannot be created") from exc
    if week_dir.is_symlink() or not week_dir.is_dir() or week_dir.resolve() != week_dir:
        raise WeeklyBenchmarkProjectionError("weekly output directory is redirected")
    return week_dir


def _atomic_report(path: Path, value: dict[str, Any]) -> None:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise WeeklyBenchmarkProjectionError("weekly snapshot target is redirected or non-regular")
    raw = _canonical(value) + b"\n"
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    descriptor: int | None = None
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            descriptor = None
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise WeeklyBenchmarkProjectionError("weekly snapshot target changed during write")
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError as exc:
        raise WeeklyBenchmarkProjectionError("weekly snapshot cannot be written") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def write_sunday_benchmark_report(
    *,
    repo: Path,
    output_root: Path,
    observed_at: datetime | None = None,
    program_root: Path | None = None,
    projection_loader: Callable[..., dict[str, Any]] = _load_projection,
) -> tuple[Path, dict[str, Any]]:
    """Atomically refresh the rolling, non-evidentiary Sunday projection."""
    moment = observed_at or datetime.now(timezone.utc)
    if not isinstance(moment, datetime) or moment.tzinfo is None:
        raise WeeklyBenchmarkProjectionError("Sunday report clock must be timezone aware")
    moment = moment.astimezone(timezone.utc)
    iso_year, iso_week, _ = moment.isocalendar()
    week_id = f"{iso_year:04d}-W{iso_week:02d}"
    week_dir = _safe_report_directory(output_root, week_id)
    stable = build_weekly_benchmark_snapshot(
        repo=Path(repo), program_root=program_root, observed_at=moment,
        projection_loader=projection_loader,
    )
    report = {
        "schema_version": SUNDAY_REPORT_SCHEMA,
        "week_id": week_id,
        "recorded_at": _iso(moment),
        "projection_role": "rolling_read_only_non_evidentiary",
        "weekly_review_context": inspect_weekly_review_context(
            week_dir, week_id=week_id,
        ),
        "stable_benchmark": stable,
        "automatic_execution": False,
        "automatic_scheduling": False,
        "paid_api_calls": 0,
        "promotion_authorized": False,
    }
    target = week_dir / "stable_benchmark_snapshot.json"
    _atomic_report(target, report)
    return target, report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--program-root", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        path, report = write_sunday_benchmark_report(
            repo=args.repo_root, output_root=args.output_root,
            program_root=args.program_root,
        )
        print(json.dumps({
            "path": str(path), "week_id": report["week_id"],
            "benchmark_status": report["stable_benchmark"]["status"],
            "weekly_review_context": report["weekly_review_context"]["status"],
            "automatic_execution": False,
        }, sort_keys=True))
        return 0
    except (OSError, ValueError, TypeError, WeeklyBenchmarkProjectionError) as exc:
        print(f"weekly-stable-benchmark-report: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
