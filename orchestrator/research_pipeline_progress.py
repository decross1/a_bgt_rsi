"""Bounded, read-only research-campaign follow-through projection.

The projection answers a narrow operational question: have records explicitly
bound to the selected V2 campaign advanced through dispatch, an iteration,
explicit scope evidence, the existing evidence ladder, the promotion skeptic,
and L4/L5?  The durable Nara restart remains an independent runtime boundary;
its timestamp never makes an unlinked record a member of the campaign.

All joins use recorded identifiers.  The selected manifest's research question
is intentionally public; private source-ledger topic and hypothesis text is
never emitted or used to guess lineage.  A zero downstream count means zero
only when the required source was complete; missing linkage and unavailable or
incomplete sources remain explicit.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from orchestrator.experiment_admission import derive_verified_level
from orchestrator.research_campaign import (
    DEFAULT_CAMPAIGN_ID,
    CampaignError,
    classify_record,
    load_campaign,
)

SCHEMA_VERSION = "research-pipeline-progress/v1"
DEFAULT_CUTOFF = Path(
    "run_state/weekly_upgrade/activation-2026-09-14/activation.json"
)
CAMPAIGN_ACTIVATION = Path("run_state/active_research_campaign.json")
CAMPAIGN_CLOSURE_DIR = Path("run_state/research_campaign_closures")
SOURCE_FILES = {
    "coordinator_cycles": Path("run_state/coordinator_cycles.jsonl"),
    "loop_memory": Path("memory/loop_memory.jsonl"),
    "promotion_near_misses": Path("memory/promotion_near_misses.jsonl"),
    "surfaced_findings": Path("memory/surfaced_findings.jsonl"),
    "loop_feedback": Path("memory/loop_feedback.jsonl"),
    "health_signals": Path("run_state/health_signals.jsonl"),
}
MAX_SOURCE_BYTES = 16 * 1024 * 1024
MAX_SOURCE_ROWS = 50_000
MAX_RECORDS = 200
MAX_OBJECT_BYTES = 1024 * 1024

_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,159}\Z")
_SHA_RE = re.compile(r"[0-9a-f]{40,64}\Z")
_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SCOPE_VALUES = {"on", "off", "off_independent", "unsure"}
_LEVELS = ("L0", "L1", "L2", "L3", "L4", "L5")


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if result.tzinfo is None:
        return None
    return result.astimezone(timezone.utc)


def _now(value: datetime | None) -> datetime:
    result = value or datetime.now(timezone.utc)
    if not isinstance(result, datetime) or result.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return result.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _week(value: datetime) -> tuple[str, datetime, datetime]:
    value = value.astimezone(timezone.utc)
    start = datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    start -= timedelta(days=value.weekday())
    year, number, _ = value.isocalendar()
    return f"{year}-W{number:02d}", start, start + timedelta(days=7)


def _strict_json(raw: bytes) -> Any:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in pairs:
            if key in out:
                raise ValueError("duplicate key")
            out[key] = value
        return out

    return json.loads(
        raw,
        object_pairs_hook=unique,
        parse_constant=lambda token: (_ for _ in ()).throw(
            ValueError(f"non-finite {token}")
        ),
    )


def _open_regular_source(root: Path, relative: Path) -> tuple[int, int]:
    """Open one repository-relative regular file without following symlinks.

    Opening each path component relative to an already-open directory prevents
    a check/open replacement from redirecting the projection outside its
    declared root.  The returned size and all later reads refer to the same
    descriptor.
    """
    if relative.is_absolute() or not relative.parts or any(
        part in {"", ".", ".."} for part in relative.parts
    ):
        raise OSError("source path must be a bounded repository-relative path")
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    cloexec = getattr(os, "O_CLOEXEC", 0)
    directory_flags = os.O_RDONLY | cloexec | nofollow | os.O_DIRECTORY
    opened_directories: list[int] = []
    file_descriptor: int | None = None
    try:
        directory = os.open(root.expanduser().absolute(), directory_flags)
        opened_directories.append(directory)
        for part in relative.parts[:-1]:
            directory = os.open(part, directory_flags, dir_fd=directory)
            opened_directories.append(directory)
        file_descriptor = os.open(
            relative.parts[-1], os.O_RDONLY | cloexec | nofollow,
            dir_fd=directory,
        )
        metadata = os.fstat(file_descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise OSError("source is not a regular file")
        return file_descriptor, metadata.st_size
    except Exception:
        if file_descriptor is not None:
            os.close(file_descriptor)
        raise
    finally:
        for descriptor in reversed(opened_directories):
            os.close(descriptor)


def _read_at_most(file_descriptor: int, limit: int) -> bytes:
    chunks: list[bytes] = []
    remaining = limit
    while remaining > 0:
        chunk = os.read(file_descriptor, min(remaining, 1024 * 1024))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _read_object(
    root: Path, relative: Path, *, source_id: str = "cutoff_activation",
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    provenance = {
        "id": source_id,
        "available": False,
        "window_sha256": None,
        "bytes_read": 0,
        "total_bytes": None,
        "truncated_before": False,
        "parsed_rows": 0,
        "malformed_rows": 0,
    }
    file_descriptor: int | None = None
    try:
        file_descriptor, size = _open_regular_source(root, relative)
        provenance["total_bytes"] = size
        if size > MAX_OBJECT_BYTES:
            provenance["truncated_before"] = True
            return None, provenance
        raw = _read_at_most(file_descriptor, MAX_OBJECT_BYTES + 1)
        final_size = os.fstat(file_descriptor).st_size
        provenance["total_bytes"] = final_size
        if len(raw) > MAX_OBJECT_BYTES or final_size != size:
            provenance["truncated_before"] = True
            return None, provenance
        value = _strict_json(raw)
    except FileNotFoundError:
        return None, provenance
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        provenance["malformed_rows"] = 1
        return None, provenance
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)
    provenance.update(
        available=True,
        window_sha256=hashlib.sha256(raw).hexdigest(),
        bytes_read=len(raw),
        total_bytes=final_size,
        parsed_rows=1 if isinstance(value, dict) else 0,
        malformed_rows=0 if isinstance(value, dict) else 1,
    )
    return (value if isinstance(value, dict) else None), provenance


def _read_jsonl(root: Path, source_id: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    relative = SOURCE_FILES[source_id]
    provenance = {
        "id": source_id,
        "available": False,
        "window_sha256": None,
        "bytes_read": 0,
        "total_bytes": None,
        "truncated_before": False,
        "parsed_rows": 0,
        "malformed_rows": 0,
    }
    file_descriptor: int | None = None
    try:
        file_descriptor, size = _open_regular_source(root, relative)
        start = max(0, size - MAX_SOURCE_BYTES)
        os.lseek(file_descriptor, start, os.SEEK_SET)
        raw = _read_at_most(file_descriptor, MAX_SOURCE_BYTES)
        final_size = os.fstat(file_descriptor).st_size
    except OSError:
        return [], provenance
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)
    changed_during_read = final_size != size
    if start:
        boundary = raw.find(b"\n")
        raw = raw[boundary + 1 :] if boundary >= 0 else b""
    rows: list[dict[str, Any]] = []
    malformed = 0
    for line in raw.splitlines():
        if not line:
            continue
        try:
            value = _strict_json(line)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            malformed += 1
            continue
        if isinstance(value, dict):
            rows.append(value)
        else:
            malformed += 1
    rows_truncated = len(rows) > MAX_SOURCE_ROWS
    if rows_truncated:
        rows = rows[-MAX_SOURCE_ROWS:]
    provenance.update(
        available=True,
        window_sha256=hashlib.sha256(raw).hexdigest(),
        bytes_read=len(raw),
        total_bytes=final_size,
        truncated_before=start > 0 or rows_truncated or changed_during_read,
        parsed_rows=len(rows),
        malformed_rows=malformed,
    )
    return rows, provenance


def _request_digest(request: dict[str, Any]) -> str | None:
    try:
        raw = json.dumps(
            request, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        return None
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _valid_id(value: Any) -> str | None:
    return value if isinstance(value, str) and _ID_RE.fullmatch(value) else None


def _row_time(row: dict[str, Any], *keys: str) -> datetime | None:
    for key in keys:
        parsed = _parse_time(row.get(key))
        if parsed is not None:
            return parsed
    return None


def _in_window(value: datetime | None, start: datetime, end: datetime) -> bool:
    return value is not None and start <= value <= end


def _latest(rows: list[dict[str, Any]], *time_keys: str) -> dict[str, Any] | None:
    timed = [(_row_time(row, *time_keys), index, row) for index, row in enumerate(rows)]
    timed = [item for item in timed if item[0] is not None]
    return max(timed, key=lambda item: (item[0], item[1]))[2] if timed else None


def _scope_status(row: dict[str, Any]) -> str:
    retrieval = row.get("retrieval")
    relevance = retrieval.get("relevance") if isinstance(retrieval, dict) else None
    if not isinstance(relevance, dict):
        return "not_assessed"
    if isinstance(relevance.get("domain_anchor_term"), str):
        return "in_scope_program_anchor"
    topicality = relevance.get("topicality")
    category = relevance.get("category")
    if topicality == "on":
        return "in_scope"
    if topicality in {"off", "off_independent"} or category == "off_domain":
        return "off_domain"
    if topicality == "unsure":
        return "uncertain"
    return "not_assessed"


def _rate(covered: int, total: int) -> float | None:
    return covered / total if total > 0 else None


def _campaign_lifecycle(
    root: Path, campaign: dict[str, Any], current: datetime,
) -> tuple[dict[str, Any], datetime | None, datetime | None, list[dict[str, Any]], list[dict[str, str]]]:
    """Project separately recorded activation and closure receipts."""
    activation, activation_provenance = _read_object(
        root, CAMPAIGN_ACTIVATION, source_id="campaign_activation",
    )
    closure_path = CAMPAIGN_CLOSURE_DIR / f"{campaign['campaign_id']}.json"
    closure, closure_provenance = _read_object(
        root, closure_path, source_id="campaign_closure",
    )
    sources = [activation_provenance, closure_provenance]
    qualifications: list[dict[str, str]] = []
    base = {
        "status": "inactive",
        "activated_at": None,
        "activation_sha256": None,
        "closed_at": None,
        "closure_sha256": None,
    }

    def absent(provenance: dict[str, Any]) -> bool:
        return (
            not provenance["available"]
            and provenance["total_bytes"] is None
            and provenance["malformed_rows"] == 0
            and not provenance["truncated_before"]
        )

    activation_fields = {
        "schema_version", "campaign_id", "campaign_manifest_sha256",
        "activated_at", "activated_by",
    }
    if activation is None:
        if not absent(activation_provenance):
            base["status"] = "invalid"
            qualifications.append({
                "code": "campaign_activation_invalid",
                "detail": "The campaign activation pointer is malformed, redirected, changing, or over its read bound.",
            })
        elif closure is not None or not absent(closure_provenance):
            base["status"] = "invalid"
            qualifications.append({
                "code": "campaign_closure_without_activation",
                "detail": "A campaign closure cannot be validated without its exact activation receipt.",
            })
        else:
            qualifications.append({
                "code": "campaign_not_activated",
                "detail": "The campaign declaration is prepared, but no runtime activation pointer is recorded.",
            })
        return base, None, None, sources, qualifications

    activated_at = _parse_time(activation.get("activated_at"))
    activation_shape_valid = (
        set(activation) == activation_fields
        and activation.get("schema_version") == "research-campaign-activation/v1"
        and _valid_id(activation.get("campaign_id")) is not None
        and isinstance(activation.get("campaign_manifest_sha256"), str)
        and _SHA_RE.fullmatch(activation["campaign_manifest_sha256"]) is not None
        and isinstance(activation.get("activated_by"), str)
        and 1 <= len(activation["activated_by"]) <= 120
        and activated_at is not None
        and activated_at <= current + timedelta(minutes=5)
    )
    if not activation_shape_valid:
        base["status"] = "invalid"
        qualifications.append({
            "code": "campaign_activation_invalid",
            "detail": "The campaign activation pointer fails its closed shape, identity, or chronology contract.",
        })
        return base, None, None, sources, qualifications
    if activation["campaign_id"] != campaign["campaign_id"]:
        qualifications.append({
            "code": "different_campaign_active",
            "detail": "The selected declaration is not the campaign named by the runtime pointer.",
        })
        return base, None, None, sources, qualifications
    opened_at = _parse_time(campaign.get("opened_at"))
    if (
        activation["campaign_manifest_sha256"] != campaign["_manifest_sha256"]
        or opened_at is None or activated_at < opened_at
    ):
        base["status"] = "invalid"
        qualifications.append({
            "code": "campaign_activation_mismatch",
            "detail": "The activation pointer does not bind this exact immutable campaign declaration.",
        })
        return base, None, None, sources, qualifications
    base.update(
        status="active",
        activated_at=_iso(activated_at),
        activation_sha256=activation_provenance["window_sha256"],
    )

    if closure is None:
        if not absent(closure_provenance):
            base["status"] = "invalid"
            qualifications.append({
                "code": "campaign_closure_invalid",
                "detail": "The campaign closure receipt is malformed, redirected, changing, or over its read bound.",
            })
        return base, activated_at, None, sources, qualifications

    closure_fields = {
        "schema_version", "campaign_id", "campaign_manifest_sha256",
        "closed_at", "closed_by",
    }
    closed_at = _parse_time(closure.get("closed_at"))
    closure_valid = (
        set(closure) == closure_fields
        and closure.get("schema_version") == "research-campaign-closure/v1"
        and closure.get("campaign_id") == campaign["campaign_id"]
        and closure.get("campaign_manifest_sha256") == campaign["_manifest_sha256"]
        and isinstance(closure.get("closed_by"), str)
        and 1 <= len(closure["closed_by"]) <= 120
        and closed_at is not None
        and closed_at >= activated_at
        and closed_at <= current + timedelta(minutes=5)
    )
    if not closure_valid:
        base["status"] = "invalid"
        qualifications.append({
            "code": "campaign_closure_invalid",
            "detail": "The campaign closure receipt fails its exact identity or chronology contract.",
        })
        return base, activated_at, None, sources, qualifications
    base.update(
        status="closed",
        closed_at=_iso(closed_at),
        closure_sha256=closure_provenance["window_sha256"],
    )
    return base, activated_at, closed_at, sources, qualifications


def _campaign_projection(
    campaign: dict[str, Any], lifecycle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Expose the public campaign identity and only registered evidence facts."""
    question = campaign["research_question"]
    studies = campaign.get("study_manifests", [])
    cpu_registered = any(
        isinstance(study, dict) and study.get("phase") == "cpu_calibration"
        for study in studies
    )
    model_registered = any(
        isinstance(study, dict) and study.get("phase") in {"llm_pilot", "confirmatory"}
        for study in studies
    )
    return {
        "campaign_id": campaign["campaign_id"],
        "title": campaign["title"],
        "status": campaign["status"],
        "opened_at": campaign["opened_at"],
        "manifest_sha256": campaign["_manifest_sha256"],
        "runtime": lifecycle or {
            "status": "unknown", "activated_at": None,
            "activation_sha256": None, "closed_at": None,
            "closure_sha256": None,
        },
        "research_question": {
            "question_id": question["question_id"],
            "text": question["text"],
            "text_sha256": question["text_sha256"],
        },
        "evidence": {
            "cpu_calibration_registered": cpu_registered,
            "cpu_calibration_verified": None,
            "model_trial_status": (
                "registered_no_bound_result" if model_registered
                else "not_registered"
            ),
        },
    }


def _lineage_counts(rows: list[dict[str, Any]], campaign: dict[str, Any]) -> dict[str, int]:
    counts = Counter(classify_record(row, campaign) for row in rows)
    return {
        name: counts.get(name, 0)
        for name in (
            "explicit_match", "unlinked_legacy", "malformed_campaign_link",
            "different_campaign", "campaign_link_mismatch", "malformed_record",
        )
    }


def _same_campaign_link(left: Any, right: Any) -> bool:
    return isinstance(left, dict) and isinstance(right, dict) and left == right


def _stage(
    stage_id: str,
    label: str,
    count: int | None,
    *,
    observed: bool,
    available: bool = True,
) -> dict[str, Any]:
    return {
        "id": stage_id,
        "label": label,
        "count": count,
        "status": (
            "unavailable" if not available else
            "recorded" if observed else "not_yet_observed"
        ),
    }


def _unavailable(
    now: datetime,
    cutoff_provenance: dict[str, Any],
    *,
    campaign: dict[str, Any] | None = None,
    lifecycle: dict[str, Any] | None = None,
    reason: str = "cutoff",
    source_provenance: list[dict[str, Any]] | None = None,
    qualifications: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    week_id, week_start, week_end = _week(now)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _iso(now),
        "status": "unavailable",
        "headline": (
            "Research campaign declaration is unavailable."
            if reason == "campaign" else
            "Research campaign lifecycle evidence is invalid."
            if reason == "lifecycle" else
            "Research pipeline cutoff evidence is unavailable."
        ),
        "campaign": (
            _campaign_projection(campaign, lifecycle)
            if campaign is not None else None
        ),
        "scope": {
            "id": "game_theory",
            "label": "Game theory, behavioral game theory, and learning in games",
            "assessment_basis": "Recorded retrieval.relevance topicality fields",
        },
        "cohort": None,
        "window": {
            "week": week_id, "start_at": _iso(week_start),
            "end_at": _iso(min(now, week_end)), "complete": now >= week_end,
        },
        "counts": None,
        "stages": [],
        "coverage": [],
        "bottleneck": {
            "stage": "source_coverage", "status": "unavailable",
            "explanation": (
                "The campaign manifest could not be validated, so no record is counted as campaign progress."
                if reason == "campaign" else
                "The runtime activation or closure receipt is invalid, so campaign progression cannot be bounded safely."
                if reason == "lifecycle" else
                "The restart receipt cannot establish the post-fix observation boundary."
            ),
        },
        "records": [],
        "records_window": {"displayed": 0, "total": None, "truncated": False},
        "qualifications": qualifications or [{
            "code": f"{reason}_unavailable",
            "detail": (
                "No downstream result is inferred without a valid campaign manifest."
                if reason == "campaign" else
                "No downstream result is inferred from an invalid campaign lifecycle receipt."
                if reason == "lifecycle" else
                "No downstream result is inferred without a valid activation receipt."
            ),
        }],
        "provenance": {"sources": source_provenance or [cutoff_provenance]},
    }


def project_research_pipeline(
    *, canonical_root: Path, now: datetime | None = None,
    cutoff_receipt: Path = DEFAULT_CUTOFF,
    campaign_id: str = DEFAULT_CAMPAIGN_ID,
) -> dict[str, Any]:
    """Project one cumulative campaign cohort without writing or invoking models."""
    current = _now(now)
    root = Path(canonical_root)
    try:
        campaign = load_campaign(campaign_id, repo_root=root)
    except (CampaignError, KeyError, TypeError, ValueError):
        return _unavailable(
            current,
            {
                "id": "cutoff_activation", "available": False,
                "window_sha256": None, "bytes_read": 0, "total_bytes": None,
                "truncated_before": False, "parsed_rows": 0, "malformed_rows": 0,
            },
            reason="campaign",
        )
    lifecycle, activated_at, closed_at, lifecycle_sources, lifecycle_qualifications = (
        _campaign_lifecycle(root, campaign, current)
    )
    cutoff, cutoff_provenance = _read_object(root, Path(cutoff_receipt))
    if lifecycle["status"] == "invalid":
        return _unavailable(
            current, cutoff_provenance, campaign=campaign, lifecycle=lifecycle,
            reason="lifecycle",
            source_provenance=[cutoff_provenance, *lifecycle_sources],
            qualifications=lifecycle_qualifications,
        )
    if not isinstance(cutoff, dict):
        return _unavailable(
            current, cutoff_provenance, campaign=campaign, lifecycle=lifecycle,
            source_provenance=[cutoff_provenance, *lifecycle_sources],
            qualifications=[*lifecycle_qualifications, {
                "code": "cutoff_unavailable",
                "detail": "No downstream result is inferred without a valid activation receipt.",
            }],
        )
    cutoff_at = _parse_time(cutoff.get("activated_at"))
    canonical_head = cutoff.get("canonical_head")
    service = cutoff.get("service")
    if (
        cutoff.get("schema_version") != "weekly-upgrade-activation/v1"
        or cutoff.get("startup_verified") is not True
        or cutoff_at is None
        or cutoff_at > current
        or not isinstance(canonical_head, str)
        or not _SHA_RE.fullmatch(canonical_head)
        or not isinstance(service, dict)
        or service.get("ActiveState") != "active"
        or service.get("SubState") != "running"
    ):
        return _unavailable(
            current, cutoff_provenance, campaign=campaign, lifecycle=lifecycle,
            source_provenance=[cutoff_provenance, *lifecycle_sources],
            qualifications=[*lifecycle_qualifications, {
                "code": "cutoff_unavailable",
                "detail": "No downstream result is inferred without a valid activation receipt.",
            }],
        )

    week_id, _week_start, _week_end = _week(current)
    campaign_opened_at = _parse_time(campaign.get("opened_at"))
    if campaign_opened_at is None or campaign_opened_at > current:
        return _unavailable(
            current, cutoff_provenance, campaign=campaign, lifecycle=lifecycle,
            reason="campaign",
            source_provenance=[cutoff_provenance, *lifecycle_sources],
            qualifications=lifecycle_qualifications,
        )
    # Campaign progression is cumulative. Weekly reset would orphan a Sunday
    # dispatch from a Monday promotion or human verdict.
    window_start = max(
        cutoff_at, campaign_opened_at,
        activated_at if activated_at is not None else campaign_opened_at,
    )
    # Closure ends new campaign dispatches.  It does not erase later evidence,
    # skeptic, or human receipts for an iteration dispatched before closure.
    dispatch_window_end = min(current, closed_at) if closed_at else current
    observation_window_end = current
    source_rows: dict[str, list[dict[str, Any]]] = {}
    source_provenance = [cutoff_provenance, *lifecycle_sources]
    qualifications: list[dict[str, str]] = [*lifecycle_qualifications]
    for source_id in SOURCE_FILES:
        rows, provenance = _read_jsonl(root, source_id)
        source_rows[source_id] = rows
        source_provenance.append(provenance)
        if not provenance["available"]:
            qualifications.append({
                "code": f"{source_id}_unavailable",
                "detail": f"The {source_id.replace('_', ' ')} source is unavailable.",
            })
        elif provenance["truncated_before"]:
            qualifications.append({
                "code": f"{source_id}_bounded_tail",
                "detail": (
                    f"The {source_id.replace('_', ' ')} source uses a bounded "
                    "recent tail; dependent counts are withheld."
                ),
            })
        if provenance["malformed_rows"]:
            qualifications.append({
                "code": f"{source_id}_malformed_rows",
                "detail": (
                    f"Malformed {source_id.replace('_', ' ')} rows were withheld; "
                    "dependent counts are unavailable."
                ),
            })

    source_complete = {
        source["id"]: (
            source["available"]
            and not source["truncated_before"]
            and source["malformed_rows"] == 0
        )
        for source in source_provenance
    }
    cycle_source_ok = source_complete["coordinator_cycles"]
    loop_source_ok = source_complete["loop_memory"]
    near_source_ok = source_complete["promotion_near_misses"]
    surfaced_source_ok = source_complete["surfaced_findings"]
    feedback_source_ok = source_complete["loop_feedback"]
    health_source_ok = source_complete["health_signals"]
    # Classify lineage before applying the display window.  Time may bound an
    # already explicit campaign member, but can never manufacture membership.
    cycle_classes = [
        (row, classify_record(row, campaign))
        for row in source_rows["coordinator_cycles"]
    ]
    iteration_classes = [
        (row, classify_record(row, campaign)) for row in source_rows["loop_memory"]
    ]
    surfaced_classes = [
        (row, classify_record(row, campaign))
        for row in source_rows["surfaced_findings"]
    ]
    # Identity uniqueness is global to each complete source, not merely the
    # selected campaign rows.  Legacy or other-campaign collisions would make
    # later unscoped feedback/near-miss joins ambiguous.
    global_cycle_identity_counts = Counter(
        cycle_id for row, _classification in cycle_classes
        if (cycle_id := _valid_id(row.get("run_id"))) is not None
    )
    global_iteration_identity_counts = Counter(
        iteration_id for row, _classification in iteration_classes
        if (iteration_id := _valid_id(row.get("iteration_id"))) is not None
    )
    global_finding_identity_counts = Counter(
        finding_id for row, _classification in surfaced_classes
        if (finding_id := _valid_id(row.get("finding_id"))) is not None
    )
    selected_cycles = [
        row for row, classification in cycle_classes
        if cycle_source_ok
        and lifecycle["status"] in {"active", "closed"}
        and classification == "explicit_match"
        and window_start <= dispatch_window_end
        and _in_window(
            _row_time(row, "timestamp"), window_start, dispatch_window_end,
        )
    ]
    lineage = {
        "coordinator_cycles": _lineage_counts(
            [row for row, _classification in cycle_classes], campaign,
        ),
        "loop_memory": _lineage_counts(
            [row for row, _classification in iteration_classes], campaign,
        ),
        "surfaced_findings": _lineage_counts(
            [row for row, _classification in surfaced_classes], campaign,
        ),
    }
    lineage_complete = {
        "coordinator_cycles": cycle_source_ok,
        "loop_memory": loop_source_ok,
        "surfaced_findings": surfaced_source_ok,
    }
    for source_id, complete in lineage_complete.items():
        if not complete:
            lineage[source_id] = {
                classification: None for classification in lineage[source_id]
            }
    for source_id, values in lineage.items():
        excluded = sum(
            count for classification, count in values.items()
            if classification != "explicit_match" and isinstance(count, int)
        )
        if excluded:
            detail = ", ".join(
                f"{count} {classification.replace('_', ' ')}"
                for classification, count in values.items()
                if classification != "explicit_match" and isinstance(count, int)
                and count
            )
            qualifications.append({
                "code": f"{source_id}_campaign_rows_excluded",
                "detail": (
                    f"{excluded} {source_id.replace('_', ' ')} rows were excluded "
                    f"from this campaign projection ({detail})."
                ),
            })

    attempts: list[dict[str, Any]] = []
    for cycle in selected_cycles:
        # Planned/dry-run cycles are proposals, not topic attempts.  The
        # canonical cycle projection records ``executed`` only after dispatch.
        if cycle.get("status") != "executed":
            continue
        cycle_id = _valid_id(cycle.get("run_id"))
        plan = cycle.get("plan") if isinstance(cycle.get("plan"), list) else []
        outcomes = cycle.get("outcomes") if isinstance(cycle.get("outcomes"), list) else []
        loop_steps = [
            step for step in plan
            if isinstance(step, dict) and step.get("action") == "run_loop_iteration"
        ]
        for index, step in enumerate(loop_steps):
            step_id = _valid_id(step.get("step_id"))
            digest = step.get("request_digest")
            request = {"action": "run_loop_iteration", "args": step.get("args")}
            identity_valid = (
                cycle_id is not None and step_id is not None and isinstance(digest, str)
                and _DIGEST_RE.fullmatch(digest) is not None
                and _request_digest(request) == digest
            )
            matches = [
                outcome for outcome in outcomes
                if isinstance(outcome, dict) and outcome.get("step_id") == step_id
            ] if identity_valid else []
            exact = len(matches) == 1
            outcome = matches[0] if exact else None
            if outcome is not None:
                exact = all((
                    outcome.get("action") == "run_loop_iteration",
                    outcome.get("request_digest") == digest,
                    outcome.get("request") == request,
                ))
            passed = exact and outcome is not None and outcome.get("status") == "passed"
            iteration_id = (
                _valid_id(cycle.get("dispatched_iteration_id"))
                if passed and len(loop_steps) == 1 else None
            )
            status = (
                "completed" if iteration_id else
                "missing_linkage" if passed else
                "failed" if exact else "ambiguous"
            )
            attempts.append({
                "attempt_id": step_id,
                "cycle_run_id": cycle_id,
                "recorded_at": cycle.get("timestamp") if _row_time(cycle, "timestamp") else None,
                "topic_source": cycle.get("topic_source") if cycle.get("topic_source") in {
                    "agenda", "finding_followup", "coordinator_propose", "arxiv_pick",
                    "campaign_preregistered",
                } else "unknown",
                "dispatch_status": status,
                "iteration_id": iteration_id,
                "campaign_id": campaign["campaign_id"],
                "topic_id": cycle["campaign"]["topic_id"],
                "_campaign_link": cycle["campaign"],
                "_index": index,
            })

    duplicated_steps = {
        attempt_id for attempt_id, count in Counter(
            attempt["attempt_id"] for attempt in attempts if attempt["attempt_id"]
        ).items() if count > 1
    }
    duplicated_cycles = {
        cycle_id for cycle_id, count in Counter(
            attempt["cycle_run_id"] for attempt in attempts
            if attempt["cycle_run_id"]
        ).items() if count > 1
    } | {
        cycle_id for cycle_id, count in global_cycle_identity_counts.items()
        if count > 1
    }
    if duplicated_steps or duplicated_cycles:
        qualifications.append({
            "code": "duplicate_dispatch_identity",
            "detail": "Repeated cycle or dispatch identifiers were treated as ambiguous.",
        })
        for attempt in attempts:
            if (
                attempt["attempt_id"] in duplicated_steps
                or attempt["cycle_run_id"] in duplicated_cycles
            ):
                attempt["dispatch_status"] = "ambiguous"
                attempt["iteration_id"] = None

    iterations_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row, classification in iteration_classes:
        iteration_id = _valid_id(row.get("iteration_id"))
        if loop_source_ok and classification == "explicit_match" and iteration_id and _in_window(
            _row_time(row, "started_at", "ended_at"),
            window_start, observation_window_end,
        ):
            iterations_by_id[iteration_id].append(row)
    duplicate_iterations = {
        iteration_id for iteration_id, rows in iterations_by_id.items() if len(rows) > 1
    } | {
        iteration_id for iteration_id, count in global_iteration_identity_counts.items()
        if count > 1
    }
    if duplicate_iterations:
        qualifications.append({
            "code": "duplicate_iteration_identity",
            "detail": "Conflicting repeated iteration identifiers were withheld from joins.",
        })

    linked_ids = {
        attempt["iteration_id"] for attempt in attempts
        if attempt["dispatch_status"] == "completed" and attempt["iteration_id"]
    }
    attempt_links_by_iteration: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for attempt in attempts:
        if attempt["dispatch_status"] == "completed" and attempt["iteration_id"]:
            attempt_links_by_iteration[attempt["iteration_id"]].append(
                attempt["_campaign_link"]
            )
    joined_ids = set()
    campaign_link_mismatch_ids = set()
    for iteration_id in linked_ids:
        rows = iterations_by_id.get(iteration_id, [])
        if len(rows) != 1 or iteration_id in duplicate_iterations:
            continue
        iteration_link = rows[0].get("campaign")
        if all(
            _same_campaign_link(iteration_link, link)
            for link in attempt_links_by_iteration[iteration_id]
        ):
            joined_ids.add(iteration_id)
        else:
            campaign_link_mismatch_ids.add(iteration_id)
    if campaign_link_mismatch_ids:
        qualifications.append({
            "code": "dispatch_iteration_campaign_link_mismatch",
            "detail": (
                "At least one explicit campaign dispatch and iteration disagreed "
                "on their exact campaign/topic link and was withheld from joins."
            ),
        })
    unlinked_iteration_ids = {
        iteration_id for iteration_id, rows in iterations_by_id.items()
        if iteration_id not in linked_ids and any(
            _in_window(
                _row_time(row, "started_at", "ended_at"),
                window_start, observation_window_end,
            )
            for row in rows
        )
    }

    feedback_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    near_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    surfaced_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in source_rows["loop_feedback"]:
        iteration_id = _valid_id(row.get("iteration_id"))
        recorded_at = _row_time(row, "gated_at", "timestamp")
        if feedback_source_ok and iteration_id and _in_window(
            recorded_at, window_start, observation_window_end,
        ):
            feedback_by_id[iteration_id].append(row)
    for row in source_rows["promotion_near_misses"]:
        iteration_id = _valid_id(row.get("source_iteration_id"))
        recorded_at = _row_time(row, "timestamp")
        if near_source_ok and iteration_id and _in_window(
            recorded_at, window_start, observation_window_end,
        ):
            near_by_id[iteration_id].append(row)
    for row, classification in surfaced_classes:
        iteration_id = _valid_id(row.get("source_iteration_id"))
        finding_id = _valid_id(row.get("finding_id"))
        recorded_at = _row_time(row, "promoted_at", "timestamp")
        if (
            surfaced_source_ok
            and classification == "explicit_match"
            and iteration_id and finding_id == f"sf-{iteration_id}"
            and global_finding_identity_counts[finding_id] == 1
            and _in_window(recorded_at, window_start, observation_window_end)
        ):
            surfaced_by_id[iteration_id].append(row)
    duplicate_finding_ids = {
        finding_id for finding_id, count in global_finding_identity_counts.items()
        if count > 1
    }
    if duplicate_finding_ids:
        qualifications.append({
            "code": "duplicate_finding_identity",
            "detail": (
                "Conflicting repeated finding identifiers were withheld from "
                "promotion and human-review joins."
            ),
        })

    health_rows = [
        row for row in source_rows["health_signals"]
        if health_source_ok
        and _in_window(
            _row_time(row, "timestamp"), window_start, observation_window_end,
        )
    ]
    per_iteration: dict[str, dict[str, Any]] = {}
    level_counts = {level: 0 for level in _LEVELS}
    for iteration_id in sorted(joined_ids):
        row = iterations_by_id[iteration_id][0]
        feedback = _latest(feedback_by_id[iteration_id], "gated_at", "timestamp")
        surfaced_candidates = [
            item for item in surfaced_by_id[iteration_id]
            if _same_campaign_link(item.get("campaign"), row.get("campaign"))
        ]
        surfaced = _latest(surfaced_candidates, "promoted_at", "timestamp")
        near = _latest(near_by_id[iteration_id], "timestamp")
        adversarial = surfaced.get("adversarial") if isinstance(surfaced, dict) else None
        derived = derive_verified_level(
            row, feedback, adversarial if isinstance(adversarial, dict) else None,
            health_rows, repo_root=root,
        )
        level = derived["level"] if derived.get("level") in _LEVELS else "L0"
        level_counts[level] += 1
        scope_status = _scope_status(row)
        if surfaced is not None and level in {"L4", "L5"}:
            promotion_status = "validated"
            skeptic_status = "validated"
        elif near is not None:
            promotion_status = "rejected"
            skeptic_status = (
                "rejected" if near.get("stage") == "adversarial" else "not_reached"
            )
        else:
            promotion_status = "not_yet_observed"
            skeptic_status = "not_yet_observed" if level == "L3" else "not_reached"
        verdict = feedback.get("verdict") if isinstance(feedback, dict) else None
        human_status = (
            "validated" if verdict == "valid" and level == "L5" else
            "rejected" if verdict == "invalid" else
            "needs_revision" if verdict == "needs_revision" else
            "recorded_but_not_l5" if verdict == "valid" else "not_yet_observed"
        )
        per_iteration[iteration_id] = {
            "scope_status": scope_status,
            "evidence_level": level,
            "evidence_provisional": (
                sorted(
                    value for value in derived.get("provisional", [])
                    if isinstance(value, str)
                )
                if health_source_ok else None
            ),
            "skeptic_status": skeptic_status,
            "promotion_status": promotion_status,
            "human_validation_status": human_status,
            "promotion_review_attempts": len(near_by_id[iteration_id]) + len(surfaced_candidates),
        }

    ordered_attempts = sorted(
        enumerate(attempts),
        key=lambda item: (
            _parse_time(item[1].get("recorded_at"))
            or datetime.min.replace(tzinfo=timezone.utc),
            item[0],
        ),
    )
    displayed_attempts = [attempt for _index, attempt in ordered_attempts[-MAX_RECORDS:]]
    records_truncated = len(attempts) > len(displayed_attempts)
    if records_truncated:
        qualifications.append({
            "code": "records_display_truncated",
            "detail": (
                f"The attempt table shows {len(displayed_attempts)} of "
                f"{len(attempts)} campaign receipts; aggregate counts use all."
            ),
        })
    public_records: list[dict[str, Any]] = []
    for attempt in displayed_attempts:
        iteration_id = attempt["iteration_id"]
        joined = per_iteration.get(iteration_id) if iteration_id else None
        skeptic_known = near_source_ok and surfaced_source_ok
        human_known = feedback_source_ok and surfaced_source_ok
        full_ladder_known = surfaced_source_ok and feedback_source_ok
        public_records.append({
            key: value for key, value in {
                "attempt_id": attempt["attempt_id"],
                "cycle_run_id": attempt["cycle_run_id"],
                "recorded_at": attempt["recorded_at"],
                "topic_source": attempt["topic_source"],
                "campaign_id": attempt["campaign_id"],
                "topic_id": attempt["topic_id"],
                "dispatch_status": attempt["dispatch_status"],
                "iteration_id": iteration_id,
                "iteration_status": (
                    "recorded" if joined else
                    "source_unavailable" if iteration_id and not loop_source_ok else
                    "missing_record" if iteration_id else
                    "missing_linkage" if attempt["dispatch_status"] == "missing_linkage"
                    else "not_linked"
                ),
                "scope_status": joined["scope_status"] if joined else "source_unavailable" if not loop_source_ok else "not_yet_observed",
                "evidence_level": (
                    joined["evidence_level"]
                    if joined and loop_source_ok and full_ladder_known else None
                ),
                "evidence_provisional": (
                    joined["evidence_provisional"]
                    if joined and full_ladder_known else None
                ),
                "skeptic_status": joined["skeptic_status"] if joined and skeptic_known else "source_unavailable" if not skeptic_known else "not_yet_observed",
                "promotion_status": joined["promotion_status"] if joined and skeptic_known else "source_unavailable" if not skeptic_known else "not_yet_observed",
                "human_validation_status": joined["human_validation_status"] if joined and human_known else "source_unavailable" if not human_known else "not_yet_observed",
                "promotion_review_attempts": joined["promotion_review_attempts"] if joined and skeptic_known else None,
            }.items()
        })

    values = list(per_iteration.values())
    completed_attempts = sum(a["dispatch_status"] == "completed" for a in attempts)
    scope_assessed = sum(v["scope_status"] != "not_assessed" for v in values)
    in_scope = sum(v["scope_status"] in {"in_scope", "in_scope_program_anchor"} for v in values)
    off_domain = sum(v["scope_status"] == "off_domain" for v in values)
    l1_plus = sum(v["evidence_level"] in {"L1", "L2", "L3", "L4", "L5"} for v in values)
    l3_plus = sum(v["evidence_level"] in {"L3", "L4", "L5"} for v in values)
    skeptic_reviewed = sum(v["skeptic_status"] in {"rejected", "validated"} for v in values)
    rejected = sum(v["promotion_status"] == "rejected" for v in values)
    promoted = sum(v["promotion_status"] == "validated" for v in values)
    l4_plus = sum(v["evidence_level"] in {"L4", "L5"} for v in values)
    l5 = sum(v["evidence_level"] == "L5" for v in values)
    human_recorded = sum(v["human_validation_status"] != "not_yet_observed" for v in values)
    counts = {
        "topic_attempts": len(attempts),
        "dispatch_completions": completed_attempts,
        "dispatch_failures": sum(a["dispatch_status"] == "failed" for a in attempts),
        "ambiguous_dispatches": sum(a["dispatch_status"] == "ambiguous" for a in attempts),
        "missing_dispatch_iteration_links": sum(a["dispatch_status"] == "missing_linkage" for a in attempts),
        "distinct_dispatched_iterations": len(linked_ids),
        "iterations_recorded": len(joined_ids),
        "missing_iteration_records": len(linked_ids - joined_ids),
        "unlinked_iteration_records": len(unlinked_iteration_ids),
        "campaign_link_mismatch_records": len(campaign_link_mismatch_ids),
        "scope_assessed": scope_assessed,
        "in_scope": in_scope,
        "off_domain": off_domain,
        "scope_uncertain": sum(v["scope_status"] == "uncertain" for v in values),
        "evidence_assessed": len(values),
        "l1_or_higher": l1_plus,
        "l3_ready_for_skeptic": l3_plus,
        "skeptic_reviews_recorded": skeptic_reviewed,
        "promotion_rejections": rejected,
        "promotion_validations": promoted,
        "l4_validated": l4_plus,
        "human_verdicts_recorded": human_recorded,
        "l5_human_validated": l5,
        "evidence_levels": level_counts,
    }

    # A missing source is never represented as an observed zero.  Preserve the
    # upstream dispatch counts that remain knowable, and withhold only the
    # dependent portion of the funnel.
    loop_dependent = (
        "iterations_recorded", "missing_iteration_records",
        "unlinked_iteration_records", "campaign_link_mismatch_records",
        "scope_assessed", "in_scope",
        "off_domain", "scope_uncertain", "evidence_assessed",
        "l1_or_higher", "l3_ready_for_skeptic",
        "skeptic_reviews_recorded", "promotion_rejections",
        "promotion_validations", "l4_validated",
        "human_verdicts_recorded", "l5_human_validated",
    )
    if not loop_source_ok:
        for key in loop_dependent:
            counts[key] = None
        counts["evidence_levels"] = {level: None for level in _LEVELS}
    if not (near_source_ok and surfaced_source_ok):
        counts["skeptic_reviews_recorded"] = None
    if not near_source_ok:
        counts["promotion_rejections"] = None
    if not surfaced_source_ok:
        counts["promotion_validations"] = None
        counts["l4_validated"] = None
    if not feedback_source_ok or not surfaced_source_ok:
        counts["human_verdicts_recorded"] = None
        counts["l5_human_validated"] = None
        counts["evidence_levels"] = {level: None for level in _LEVELS}
    if not cycle_source_ok:
        for key in counts:
            counts[key] = (
                {level: None for level in _LEVELS}
                if key == "evidence_levels" else None
            )

    stages = [
        _stage("topic", "Campaign topics attempted", counts["topic_attempts"], observed=bool(attempts), available=cycle_source_ok),
        _stage("dispatch", "Dispatches completed", counts["dispatch_completions"], observed=bool(attempts), available=cycle_source_ok),
        _stage("iteration", "Iterations recorded", counts["iterations_recorded"], observed=bool(attempts), available=cycle_source_ok and loop_source_ok),
        _stage("scope", "In-scope hypotheses", counts["in_scope"], observed=bool(values), available=cycle_source_ok and loop_source_ok),
        _stage("evidence", "L1+ evidence", counts["l1_or_higher"], observed=bool(values), available=cycle_source_ok and loop_source_ok),
        _stage("skeptic", "Promotion skeptic reviews", counts["skeptic_reviews_recorded"], observed=bool(l3_plus), available=cycle_source_ok and loop_source_ok and near_source_ok and surfaced_source_ok),
        _stage("l4", "L4 validated", counts["l4_validated"], observed=bool(skeptic_reviewed), available=cycle_source_ok and loop_source_ok and surfaced_source_ok),
        _stage("l5", "L5 human validated", counts["l5_human_validated"], observed=bool(l4_plus), available=cycle_source_ok and loop_source_ok and surfaced_source_ok and feedback_source_ok),
    ]
    coverage = [
        {"id": "dispatch_completion", "label": "Attempt to completed dispatch", "covered": completed_attempts, "total": len(attempts), "rate": _rate(completed_attempts, len(attempts))},
        {"id": "iteration_linkage", "label": "Dispatch to iteration record", "covered": len(joined_ids), "total": len(linked_ids), "rate": _rate(len(joined_ids), len(linked_ids))},
        {"id": "scope_assessment", "label": "Iteration with explicit scope signal", "covered": scope_assessed, "total": len(values), "rate": _rate(scope_assessed, len(values))},
        {"id": "promotion_disposition", "label": "Iteration with promotion disposition", "covered": rejected + promoted, "total": len(values), "rate": _rate(rejected + promoted, len(values))},
        {"id": "skeptic_review", "label": "L3+ evidence with skeptic review", "covered": skeptic_reviewed, "total": l3_plus, "rate": _rate(skeptic_reviewed, l3_plus)},
        {"id": "human_review", "label": "L4+ evidence with human verdict", "covered": sum(v["evidence_level"] in {"L4", "L5"} and v["human_validation_status"] != "not_yet_observed" for v in values), "total": l4_plus, "rate": _rate(sum(v["evidence_level"] in {"L4", "L5"} and v["human_validation_status"] != "not_yet_observed" for v in values), l4_plus)},
    ]
    coverage_requirements = {
        "dispatch_completion": cycle_source_ok,
        "iteration_linkage": cycle_source_ok and loop_source_ok,
        "scope_assessment": cycle_source_ok and loop_source_ok,
        "promotion_disposition": cycle_source_ok and loop_source_ok and near_source_ok and surfaced_source_ok,
        "skeptic_review": cycle_source_ok and loop_source_ok and near_source_ok and surfaced_source_ok,
        "human_review": cycle_source_ok and loop_source_ok and surfaced_source_ok and feedback_source_ok,
    }
    for item in coverage:
        if not coverage_requirements[item["id"]]:
            item.update(covered=None, total=None, rate=None, status="unavailable")
        else:
            item["status"] = "recorded" if item["total"] else "not_yet_observed"

    if not cycle_source_ok:
        status = "unavailable"
        bottleneck = {"stage": "source_coverage", "status": "unavailable", "explanation": "Coordinator cycle receipts are unavailable, so dispatch follow-through cannot be measured."}
    elif not loop_source_ok:
        status = "partial"
        bottleneck = {"stage": "source_coverage", "status": "unavailable", "explanation": "Loop-memory receipts are unavailable, so completed dispatches cannot be followed into research evidence."}
    elif lifecycle["status"] == "inactive":
        status = "not_yet_observed"
        bottleneck = {"stage": "activation", "status": "not_yet_observed", "explanation": "The selected campaign declaration has no exact recorded runtime activation, so no campaign execution is counted."}
    elif not attempts:
        status = "not_yet_observed"
        bottleneck = {"stage": "dispatch", "status": "not_yet_observed", "explanation": "No explicitly linked campaign dispatch has been recorded; downstream conversion cannot yet be evaluated."}
        qualifications.append({"code": "no_campaign_dispatch", "detail": "Selected-campaign progression is not yet observed, rather than failed or passed."})
    elif completed_attempts < len(attempts):
        status = "partial"
        bottleneck = {"stage": "dispatch", "status": "partial", "explanation": "At least one research dispatch lacks an exact completed receipt and iteration link."}
    elif len(joined_ids) < len(linked_ids):
        status = "partial"
        bottleneck = {"stage": "iteration_linkage", "status": "partial", "explanation": "At least one completed dispatch has no unique loop-memory record."}
    elif scope_assessed < len(values):
        status = "partial"
        bottleneck = {"stage": "scope", "status": "partial", "explanation": "At least one recorded iteration lacks an explicit structured scope assessment."}
    elif in_scope < len(values):
        status = "observed"
        bottleneck = {"stage": "scope", "status": "rejected", "explanation": "At least one generated hypothesis was explicitly assessed outside the game-theory research scope."}
    elif l1_plus < in_scope:
        status = "observed"
        bottleneck = {"stage": "evidence", "status": "rejected", "explanation": "At least one in-scope iteration did not earn L1 literature-consistent evidence."}
    elif l3_plus and not (near_source_ok and surfaced_source_ok):
        status = "partial"
        bottleneck = {"stage": "source_coverage", "status": "unavailable", "explanation": "Promotion disposition sources are incomplete, so L3 evidence cannot be classified as awaiting, rejected, or validated."}
    elif skeptic_reviewed < l3_plus:
        status = "observed"
        bottleneck = {"stage": "skeptic", "status": "not_yet_observed", "explanation": "L3 evidence exists without a recorded promotion-skeptic disposition."}
    elif l4_plus < l3_plus:
        status = "observed"
        bottleneck = {"stage": "l4", "status": "rejected", "explanation": "A promotion-skeptic review was recorded, but the evidence did not earn L4."}
    elif l4_plus and not feedback_source_ok:
        status = "partial"
        bottleneck = {"stage": "source_coverage", "status": "unavailable", "explanation": "Human-feedback receipts are incomplete, so L4 evidence cannot be classified as awaiting, rejected, revised, or L5 validated."}
    elif l5 < l4_plus:
        status = "observed"
        bottleneck = {"stage": "l5", "status": "not_yet_observed", "explanation": "L4 evidence awaits an explicit valid human verdict before it can earn L5."}
    else:
        status = "observed"
        bottleneck = {"stage": "none", "status": "validated", "explanation": "Every recorded stage in this bounded cohort has an exact validated link."}

    cutoff_hash = cutoff_provenance["window_sha256"]
    campaign_hash = campaign["_manifest_sha256"]
    cohort_id = hashlib.sha256(
        f"{campaign_hash}:{cutoff_hash}:{_iso(window_start)}".encode()
    ).hexdigest()
    headline = (
        "No explicitly linked campaign research dispatch has been observed yet."
        if status == "not_yet_observed" else
        "Research-pipeline evidence is unavailable."
        if status == "unavailable" else
        "Campaign research follow-through is partially linked."
        if status == "partial" else
        "Campaign research follow-through is recorded."
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _iso(current),
        "status": status,
        "headline": headline,
        "campaign": _campaign_projection(campaign, lifecycle),
        "scope": {
            "id": "game_theory",
            "label": "Game theory, behavioral game theory, and learning in games",
            "assessment_basis": "Recorded retrieval.relevance topicality fields",
        },
        "cohort": {
            "id": cohort_id,
            "label": "Explicit campaign records after the corrected runtime restart",
            "cutoff_at": _iso(cutoff_at),
            "cutoff_reason": "Nara restart receipt after canonical adoption of stale-topic and scope fixes",
            "cutoff_receipt_sha256": cutoff_hash,
            "canonical_head": canonical_head,
            "campaign_manifest_sha256": campaign_hash,
            "membership_rule": "Exact research-campaign-link/v1 only; timestamps and topic text do not confer membership",
        },
        "window": {
            "week": week_id,
            "mode": "campaign_to_date",
            "start_at": _iso(window_start),
            "end_at": _iso(observation_window_end),
            "dispatch_end_at": _iso(dispatch_window_end),
            "dispatch_closed": closed_at is not None and current >= closed_at,
            # A closure stops new dispatches; no separate watermark currently
            # proves that all downstream evidence/human receipts have arrived.
            "complete": False,
        },
        "counts": counts,
        "stages": stages,
        "coverage": coverage,
        "bottleneck": bottleneck,
        "records": public_records,
        "records_window": {
            "displayed": len(public_records),
            "total": len(attempts) if cycle_source_ok else None,
            "truncated": records_truncated,
        },
        "qualifications": qualifications,
        "provenance": {
            "join_contract": [
                "record.campaign = one exact registered research-campaign-link/v1",
                "cycle step_id + request_digest within one coordinator receipt",
                "dispatched_iteration_id = loop_memory.iteration_id",
                "cycle.campaign = loop_memory.campaign = surfaced_finding.campaign",
                "source_iteration_id = iteration_id",
                "near_miss/feedback.iteration_id joins only through an explicit-match iteration",
            ],
            "campaign_lineage": lineage,
            "sources": source_provenance,
        },
    }
