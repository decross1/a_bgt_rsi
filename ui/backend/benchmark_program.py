"""Small benchmark-program read model; historical scores are never rebased.

Only the declared definition is projected here. Execution data enter through
the stable benchmark's replay/admission projection, never from a loose score
file or an old development panel. This endpoint performs no model calls,
subprocesses, grading, scheduling or publication.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter

SCHEMA = "benchmark-program/v1"
REPO = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = Path("/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-16/"
                    "ui-benchmark-eight-hour/stable-benchmark")
MAX_DEFINITION_BYTES = 1_048_576
DOMAIN_LABELS = {
    "science_evidence": "Scientific reasoning and evidence",
    "functional_code_repair": "Functional coding repairs",
    "deterministic_tool_use": "Tool selection and execution",
    "strategic_behavior": "Strategic behavior by mechanism",
}
ARCHIVE_LINKS = [
    {"id": "flash", "label": "Flash qualification and historical comparisons",
     "href": "/benchmarks?view=evidence#models", "role": "development_diagnostic"},
    {"id": "context", "label": "Context, reasoning and output-cap diagnostics",
     "href": "/benchmarks?view=evidence#diagnostics", "role": "development_diagnostic"},
    {"id": "weekly", "label": "Earlier weekly evaluation families",
     "href": "/benchmarks?view=evidence#weekly", "role": "historical_development"},
    {"id": "applied", "label": "Applied research and historical experiments",
     "href": "/experiments?research_scope=all", "role": "empirical_study"},
]


def _read_definition(path: Path):
    from bench.stable_benchmark.manifest import (
        LoadedDocument, _unique_object, validate_definition,
    )
    if path.is_symlink() or path.resolve() != path.absolute():
        raise ValueError("definition path redirected")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise ValueError("definition is not a regular file")
        raw = handle.read(MAX_DEFINITION_BYTES + 1)
    if len(raw) > MAX_DEFINITION_BYTES:
        raise ValueError("definition read exceeds bound")
    value = json.loads(raw, object_pairs_hook=_unique_object)
    validate_definition(value)
    from .iteration_journey import _encoder_safe
    if not _encoder_safe(value):
        raise ValueError("definition is not safely representable")
    return LoadedDocument(value, hashlib.sha256(raw).hexdigest(), path)


def _empty_projection(now: datetime) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA,
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "release": None, "design": None,
        "progress": {"status": "unavailable", "completed_units": None,
                     "total_units": None, "completed_calls": None,
                     "total_calls": None, "blockers": [], "next_action": None},
        "comparison": {"status": "not_started", "baseline": None,
                       "arms": [], "matched_results": [], "history": []},
        "layers": {
            "model": {"status": "not_started", "summary": "Capability results require a prospective admitted run."},
            "system": {"status": "not_started", "summary": "Actor–tool–critic harness workflows are separate from capability tasks and full research-pipeline outcomes."},
            "runtime": {"status": "separate_evidence", "summary": "Readiness, memory, recovery and context remain independent qualification gates."},
            "applied": {"status": "separate_research", "summary": "Thesis support and market studies belong to Research, outside the model score."},
        },
        "archive_links": ARCHIVE_LINKS,
        "warnings": [],
    }


def compose_program(*, root: Path = DEFAULT_ROOT, repo: Path = REPO,
                    now: datetime | None = None) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("benchmark projection clock must be timezone-aware")
    current = current.astimezone(timezone.utc)
    result = _empty_projection(current)
    published_path = root / "definition.published.json"
    draft_path = repo / "bench/stable_benchmark/definition.draft.json"
    try:
        # A redirected or invalid published artifact must not fall back to a
        # reassuring draft or an older result.
        if published_path.exists() or published_path.is_symlink():
            loaded = _read_definition(published_path)
            if loaded.document["freeze"]["status"] != "published":
                raise ValueError("published definition contains a draft")
        elif draft_path.exists() or draft_path.is_symlink():
            loaded = _read_definition(draft_path)
        else:
            from bench.stable_benchmark.manifest import (
                LoadedDocument, canonical_json, make_draft,
            )
            draft = make_draft()
            loaded = LoadedDocument(draft, hashlib.sha256(canonical_json(draft)).hexdigest())
        definition = loaded.document
        freeze = definition["freeze"]
        if (freeze["published_at"] is not None and
                datetime.fromisoformat(freeze["published_at"].replace("Z", "+00:00")) > current):
            raise ValueError("publication witness is in the future")
        expires = datetime.fromisoformat(freeze["review_at"].replace("Z", "+00:00"))
        status = ("review_required" if current >= expires
                  else "frozen" if freeze["status"] == "published" else "draft")
        witness = freeze["witness"]
        result["release"] = {
            "suite_id": definition["suite_id"], "version": definition["release"],
            "status": status, "published_at": freeze["published_at"],
            "frozen_at": freeze["published_at"], "expires_at": freeze["review_at"],
            "definition_sha256": loaded.raw_sha256,
            "public_witness": ({"status": "recorded", "uri": witness["ref"],
                                "sha256": witness["sha256"], "verified_at": None}
                               if witness else None),
            "historical_comparability": definition["historical_comparability"],
        }
        model_tasks = [task for task in definition["tasks"] if task["panel"] == "model_capability"]
        system_tasks = [task for task in definition["tasks"] if task["mode"] == "system_mission"]
        domains = Counter(task["domain"] for task in model_tasks)
        envelope = definition["resource_envelope"]
        result["design"] = {
            "capability_units_per_arm": len(model_tasks),
            "system_missions_per_arm": len(system_tasks),
            "model_calls_per_arm": envelope["max_model_calls_per_arm"],
            "paired_model_call_cap": envelope["max_model_calls_paired"],
            "episode_seconds_per_arm": envelope["max_episode_runtime_s_per_arm"],
            "categories": [{"id": domain, "label": DOMAIN_LABELS.get(domain, domain),
                            "units": count,
                            "mechanisms": ([{"id": mechanism, "units": units}
                                            for mechanism, units in Counter(
                                                task["construct"] for task in model_tasks
                                                if task["domain"] == "strategic_behavior").items()]
                                           if domain == "strategic_behavior" else []),
                            "metrics": (definition["reporting"]["strategic_metrics"]
                                        if domain == "strategic_behavior"
                                        else ["objective task success", "wall-clock time"])}
                           for domain, count in domains.items()],
            "panels": definition["panels"],
            "no_omnibus_score": True,
            "uncertainty": definition["reporting"]["uncertainty"],
            "public_benchmarks_included": definition["external_rotations"]["included_in_release"],
        }
        result["progress"].update(
            status="awaiting_baseline" if status == "frozen" else status,
            blockers=(["Publish the definition before any scored execution."] if status == "draft"
                      else ["Review or explicitly extend the release before another run."]
                      if status == "review_required" else []),
            next_action=("Publish and bind the first prospective comparison." if status == "draft"
                         else "Run the frozen panel under its registered resource window."
                         if status == "frozen" else "Review benchmark validity and publish a new decision."),
        )
        if freeze["status"] == "published":
            _attach_history(result, root, loaded, current, repo=repo)
            _attach_active_window(result, root=root, repo=repo, now=current)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
        result["warnings"].append("Benchmark definition is unavailable or invalid; scores are withheld.")
        result["comparison"]["status"] = "withheld_invalid_definition"
    return result


def _attach_active_window(result: dict, *, root: Path, repo: Path, now: datetime) -> None:
    from .model_runtime_stable import project_active_stable_runtime
    from .model_runtime import BOOT_ID_PATH, PROC_ROOT

    runtime = project_active_stable_runtime(
        repo=repo, program_root=root, proc_root=PROC_ROOT,
        boot_id_path=BOOT_ID_PATH, observed=now,
    )
    if runtime is None:
        return
    # Runtime evidence must belong to the cohort whose coverage is shown. An
    # older window (or an unidentified broken registration) must never relabel
    # the newest registered comparison as running.
    comparison_id = result["progress"].get("comparison_id")
    if not comparison_id or runtime.get("comparison_id") != comparison_id:
        result["warnings"].append(
            "A benchmark window's live state does not match the displayed comparison; inspect Operations.")
        return
    result["progress"].update(run_id=runtime.get("run_id"), phase=runtime.get("phase"))
    if runtime.get("mode") == "unknown":
        result["progress"].update(status="unavailable", next_action="Inspect the registered window's lifecycle and recovery receipts.")
        result["progress"]["blockers"].append("The latest benchmark window's live state is unverified.")
        return
    result["progress"].update(
        status="running", completed_calls=None,
        next_action="Wait for terminal replay and restoration admission before interpreting scores.",
    )


def _attach_history(result: dict, root: Path, definition, now: datetime, *, repo: Path) -> None:
    from .benchmark_history import load_history, matched_results
    try:
        history = load_history(root, definition, repo=repo, now=now)
        rows, eligible = history["history"], history["eligible"]
        result["warnings"].extend(history["warnings"])
        comparison = result["comparison"]
        comparison["history"] = rows
        comparison["arms"] = [{key: row.get(key) for key in
                               ("comparison_id", "arm_id", "label", "admission_status")}
                              for row in rows]
        comparison["matched_results"] = matched_results(
            eligible, {task["id"]: task for task in definition.document["tasks"]})
        references = [row for row, _ in eligible if row.get("role") == "reference"]
        comparison["baseline"] = references[0] if references else None
        comparison["status"] = ("matched_results_available" if comparison["matched_results"]
                                else "baseline_available" if references
                                else "awaiting_reference" if eligible
                                else "awaiting_admission" if rows else "not_started")
        if eligible:
            for layer in ("model", "system"):
                result["layers"][layer]["status"] = "baseline_available" if references else "awaiting_reference"
        if rows:
            # Coverage describes the latest cohort, not every historical week.
            # Unissued units remain absent from completed coverage, not losses.
            latest_cohort = rows[-1]["comparison_id"]
            cohort = [row for row in rows if row["comparison_id"] == latest_cohort]
            admitted = [row for row in cohort if row["admission_status"] == "admitted"]
            complete = len(admitted) == len(cohort)
            result["progress"].update(
                comparison_id=latest_cohort,
                completed_units=sum(row["completed_units"] for row in admitted),
                total_units=len(definition.document["tasks"]) * len(cohort),
                completed_calls=(sum(row["model_calls"] for row in cohort)
                                 if all(row["model_calls"] is not None for row in cohort) else None),
                total_calls=definition.document["resource_envelope"]["max_model_calls_per_arm"] * len(cohort))
            if result["release"]["status"] == "frozen":
                result["progress"].update(
                    status="complete" if complete else "partial" if admitted else "awaiting_admission",
                    next_action=("Use this frozen reference for a preregistered system change; retain each week's receipts."
                                 if complete else "Inspect the unissued or withheld arm before planning another qualified comparison."))
            if not complete:
                result["progress"]["blockers"].append(
                    "The latest cohort contains an unissued, pending or withheld arm; no paired win is established.")
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        result["comparison"]["status"] = "withheld_invalid_history"
        result["warnings"].append("Run-history artifacts are unavailable or invalid; no new scores are admitted.")


def register(app, *, root: Path = DEFAULT_ROOT, repo: Path = REPO) -> None:
    router = APIRouter()

    @router.get("/api/benchmark_program")
    def benchmark_program():
        return compose_program(root=root, repo=repo)

    app.include_router(router)
