"""Thin read-only API adapter for the registered research-operations projection."""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from collections import Counter
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException

DEFAULT_REPO = Path("/home/decross1/projects/a_bgt_rsi")
PILOT_ROOT = Path("/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-15/"
                  "lab-eight-hour/known-opponent-utility")
PILOT_ID = "qfn-followon-known-opponent-lab8h-a"
BEHAVIOR_SCHEMA = "known-opponent-pilot-behavior/v1"
SHA = re.compile(r"[0-9a-f]{64}\Z")
REGRET = re.compile(r"[0-9]{1,9}\Z")
PAYOFF_SCHEMA = "registered-payoff-jobs-observation/v1"
PAYOFF_QUEUE_SOURCE_SHA256 = (
    "15d52ddb0683e9c3d0a0cddc1a79a794e26d4621e01e2009b97d9250b6d5c033"
)
PAYOFF_ROOT = Path("/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-15/"
                   "lab-eight-hour/payoff-decomposition")
PAYOFF_JOBS = {
    "payoff-representation-a": {
        "panel_id": "payoff-representation-a", "seed_base": 17,
        "not_before": "2026-09-15T19:00:00+00:00",
        "expires_at": "2026-09-16T00:00:00+00:00",
        "role": "first_fresh_payoff_representation_diagnostic",
    },
    "payoff-representation-b": {
        "panel_id": "payoff-representation-b", "seed_base": 29,
        "not_before": "2026-09-16T03:30:00+00:00",
        "expires_at": "2026-09-16T08:00:00+00:00",
        "role": "fresh_input_followup_not_same_prompt_reseed",
    },
}
PAYOFF_STATES = frozenset({
    "not_due", "eligible_unprepared", "eligible_prepared", "prepared_unverified",
    "attempt_reserved_or_recorded", "zero_call_refusal_retry_eligible",
    "zero_call_refusal_retry_prepared", "expired_after_zero_call_refusal",
    "expired_unattempted", "admission_receipt_present_unverified",
    "admitted_attempt_verified",
})
PAYOFF_REFUSAL_CODES = frozenset({
    "resource_lease_busy", "resource_probe_blocked", "availability_unknown",
})
_PAYOFF_CACHE_LOCK = threading.Lock()
_PAYOFF_CACHE: tuple[tuple, float, dict] | None = None


def _read(path: Path, maximum: int) -> tuple[dict, str]:
    from . import model_runtime as mr

    raw = mr._read_path(path, maximum=maximum, label="pilot public receipt")
    return mr._strict_object(raw, "pilot public receipt"), hashlib.sha256(raw).hexdigest()


def _count(value: object, maximum: int) -> bool:
    return type(value) is int and 0 <= value <= maximum


def _pilot_behavior(view: dict, root: Path, repo_root: Path) -> dict | None:
    """Extend the strict producer's recorded admission with bounded public counts."""
    empirical = view.get("empirical_pilot")
    if (view.get("schema") != "research-ops-status/v1" or
            not isinstance(empirical, dict) or
            empirical.get("status") != "recorded_admitted" or
            empirical.get("window_id") != PILOT_ID or
            empirical.get("current_source_replay") != "not_performed" or
            not SHA.fullmatch(str(empirical.get("admission_receipt_sha256", ""))) or
            not SHA.fullmatch(str(empirical.get("pilot_run_sha256", "")))):
        return None
    child = root / PILOT_ID
    try:
        admission, admission_sha = _read(child / "admission.json", 16_384)
        window, window_sha = _read(child / "window.json", 2_000_000)
        result, result_sha = _read(child / "result.json", 16_384)
        supervision, supervision_sha = _read(child / "supervision.json", 16_384)
        manifest, manifest_sha = _read(child / "manifest.snapshot.json", 1_000_000)
        run, run_sha = _read(child / "pilot/run.json", 1_000_000)
        validation = admission.get("pilot_validation")
        if (not isinstance(validation, dict) or
                admission_sha != empirical["admission_receipt_sha256"] or
                run_sha != empirical["pilot_run_sha256"] or
                admission.get("schema") != "known-opponent-resident-study-admission/v1" or
                admission.get("window_id") != PILOT_ID or
                admission.get("window_sha256") != window_sha or
                admission.get("result_sha256") != result_sha or
                admission.get("supervision_sha256") != supervision_sha or
                admission.get("pilot_run_sha256") != run_sha or
                admission.get("comparison_eligible") is not False or
                admission.get("promotion_authorized") is not False or
                admission.get("trading_claim_authorized") is not False or
                window.get("schema") != "known-opponent-resident-study-window/v1" or
                window.get("window_id") != PILOT_ID or
                window.get("output_dir") != str(child) or
                window.get("code_root") != str(repo_root) or
                window.get("manifest") != {"path": str(child / "manifest.snapshot.json"),
                                          "sha256": manifest_sha} or
                result.get("schema") != "known-opponent-resident-study-result/v1" or
                result.get("status") != "observed_restored" or
                result.get("window_sha256") != window_sha or
                result.get("pilot_run_sha256") != run_sha or
                result.get("error") is not None or
                not isinstance(result.get("restoration"), dict) or
                result["restoration"].get("status") != "verified" or
                result["restoration"].get("errors") != [] or
                result["restoration"].get("sentinel_retained") is not False or
                supervision.get("schema") != "known-opponent-resident-study-supervision/v1" or
                supervision.get("window_sha256") != window_sha or
                supervision.get("returncode") != 0 or
                supervision.get("interrupted") is not None or
                supervision.get("terminated_at_cutoff") is not False or
                supervision.get("emergency_restoration") is not None or
                manifest.get("schema") != "known-opponent-utility-response-pilot/v1" or
                manifest.get("study_id") != "known-opponent-utility-response-pilot-v1" or
                manifest.get("source_root") != str(repo_root) or
                manifest.get("max_calls") != 108 or manifest.get("horizon") != 8 or
                manifest.get("comprehension_feedback") != "none" or
                run.get("schema") != "known-opponent-utility-response-pilot-run/v1" or
                run.get("status") not in ("complete", "completed_schedule_with_unknown_actions") or
                run.get("scheduled_calls") != 108 or
                run.get("manifest_sha256") != manifest.get("manifest_sha256") or
                validation.get("schema") != "known-opponent-utility-response-validation/v1" or
                validation.get("status") != "admitted_empirical_pilot" or
                validation.get("admission_eligible") is not True or
                validation.get("run_sha256") != run_sha or
                validation.get("manifest_sha256") != manifest.get("manifest_sha256") or
                validation.get("comparison_eligible") is not False or
                validation.get("private_content_exported") is not False or
                validation.get("scientific_novelty_claimed") is not False):
            return None
        attempted = validation.get("attempted_calls")
        complete = validation.get("complete_episodes")
        valid = validation.get("valid_action_calls")
        zero = validation.get("zero_regret_complete_episodes")
        comprehension = validation.get("comprehension_passed")
        if (not _count(attempted, 108) or attempted != empirical.get("attempted_calls") or
                attempted != run.get("attempted_calls") or not _count(complete, 12) or
                complete != empirical.get("complete_episodes") or
                validation.get("scheduled_action_calls") != 96 or
                validation.get("scheduled_episodes") != 12 or
                not _count(valid, 96) or valid > attempted or
                not _count(zero, 12) or zero > complete or
                not _count(comprehension, 12) or comprehension > complete):
            return None
        schedule, tasks, cells = manifest.get("schedule"), manifest.get("tasks"), run.get("cells")
        if (not all(isinstance(rows, list) and len(rows) == 12
                    for rows in (schedule, tasks, cells)) or
                not all(isinstance(row, dict) for rows in (schedule, tasks, cells) for row in rows)):
            return None
        forms: Counter[str] = Counter()
        by_rule = {"own_payoff": {"complete": 0, "zero_regret": 0},
                   "joint_payoff": {"complete": 0, "zero_regret": 0}}
        prefix_valid, scheduled_actions, comprehension_replayed = 0, 0, 0
        for expected, task, cell in zip(schedule, tasks, cells, strict=True):
            if task.get("cell") != expected or cell.get("cell") != expected:
                return None
            messages = task.get("comprehension_messages")
            if not isinstance(messages, list) or not messages:
                return None
            form = hashlib.sha256(json.dumps(messages, sort_keys=True, ensure_ascii=False,
                                             separators=(",", ":")).encode("utf-8")).hexdigest()
            forms[form] += 1
            objective = expected.get("objective")
            if (objective not in by_rule or
                    not _count(cell.get("valid_prefix_actions"), 8) or
                    cell.get("scheduled_actions") != 8 or
                    cell.get("comprehension") not in ("passed", "failed", "unknown")):
                return None
            prefix_valid += cell["valid_prefix_actions"]
            scheduled_actions += cell["scheduled_actions"]
            comprehension_replayed += cell["comprehension"] == "passed"
            episode = cell.get("full_episode")
            if episode is not None:
                if not isinstance(episode, dict) or not REGRET.fullmatch(
                        str(episode.get("episode_regret", ""))):
                    return None
                by_rule[objective]["complete"] += 1
                by_rule[objective]["zero_regret"] += episode["episode_regret"] == "0"
        if (sorted(forms.values()) != [6, 6] or prefix_valid != valid or
                scheduled_actions != 96 or comprehension_replayed != comprehension or
                sum(row["complete"] for row in by_rule.values()) != complete or
                sum(row["zero_regret"] for row in by_rule.values()) != zero):
            return None
        return {"schema_version": BEHAVIOR_SCHEMA,
                "admission_receipt_sha256": admission_sha, "pilot_run_sha256": run_sha,
                "manifest_raw_sha256": manifest_sha,
                "scheduled_action_calls": 96, "valid_action_calls": valid,
                "complete_episodes": complete, "zero_regret_complete_episodes": zero,
                "comprehension_passed": comprehension, "comprehension_scheduled_episodes": 12,
                "comprehension_prompt_forms": 2, "form_repetitions_each": 6,
                "by_utility": by_rule, "current_source_replay": "not_performed",
                "theory_accepted": False, "strategy_causal_claim": False}
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, AttributeError):
        return None


def _enrich(view: dict, root: Path, repo_root: Path) -> dict:
    behavior = _pilot_behavior(view, root, repo_root)
    if behavior is None:
        return view
    empirical = view["empirical_pilot"]
    return {**view, "empirical_pilot": {**empirical, "behavior_summary": behavior}}


def _payoff_unknown(source_status: str, checked_at: str) -> dict:
    return {"schema_version": PAYOFF_SCHEMA, "source_status": source_status,
            "checked_at": checked_at, "queue_source_sha256": None,
            "jobs": None, "timer_activation": "not_verified",
            "comparison_eligible": False}


def _payoff_fingerprint(root: Path) -> tuple:
    """Hash only the small public refs whose changes alter queue.status."""
    from . import model_runtime as mr

    fingerprints = []
    for job_id in PAYOFF_JOBS:
        for attempt in (job_id, job_id + "-r1"):
            names = ("window.json", "manifest.snapshot.json",
                     "dispatch-reservation.json", "state.json", "result.json",
                     "supervision.json", "admission.json", "job-admission.json",
                     "dispatch-result.json", "study/run.json")
            names += tuple(f"availability-refusal-{ordinal:02d}.json"
                           for ordinal in range(24))
            for name in names:
                path = root / attempt / name
                try:
                    os.lstat(path)
                except FileNotFoundError:
                    fingerprints.append((attempt, name, None))
                    continue
                raw = mr._read_path(path, maximum=2_000_000 if name in (
                    "manifest.snapshot.json", "study/run.json") else 128_000,
                                    label="registered payoff public receipt")
                fingerprints.append((attempt, name, hashlib.sha256(raw).hexdigest()))
    return tuple(fingerprints)


def _payoff_refusal(value: object, *, attempt: str, registered: dict,
                    fingerprint: tuple, observed: datetime) -> dict | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise TypeError("payoff availability receipt is invalid")
    if value == {"status": "receipt_present_unverified"}:
        return {"status": "receipt_present_unverified"}
    if (set(value) != {"failure_code", "refused_at", "receipt_sha256"} or
            value["failure_code"] not in PAYOFF_REFUSAL_CODES or
            not SHA.fullmatch(str(value["receipt_sha256"])) or
            not isinstance(value["refused_at"], str)):
        raise ValueError("payoff availability receipt is unbound")
    refused = datetime.fromisoformat(value["refused_at"].replace("Z", "+00:00"))
    if (refused.tzinfo != timezone.utc or
            not datetime.fromisoformat(registered["not_before"]) <= refused <= observed or
            refused >= datetime.fromisoformat(registered["expires_at"]) or
            not any(row_attempt == attempt and name.startswith("availability-refusal-")
                    and receipt_sha == value["receipt_sha256"]
                    for row_attempt, name, receipt_sha in fingerprint)):
        raise ValueError("payoff availability receipt does not bind current attempt")
    return {"failure_code": value["failure_code"], "refused_at": value["refused_at"],
            "receipt_sha256": value["receipt_sha256"]}


def _payoff_jobs(repo_root: Path, *, payoff_root: Path = PAYOFF_ROOT,
                 now: datetime | None = None, queue_module=None,
                 expected_source_sha256: str | None = PAYOFF_QUEUE_SOURCE_SHA256) -> dict:
    """Read the two code-owned jobs; preparation never proves timer activation."""
    from . import model_runtime as mr

    observed = now or datetime.now(timezone.utc)
    if observed.tzinfo is None:
        return _payoff_unknown("source_unknown", datetime.now(timezone.utc).isoformat())
    checked_at = observed.astimezone(timezone.utc).isoformat()
    source_path = repo_root / "experiments/payoff_decomposition/queue.py"
    try:
        source_raw = mr._read_path(source_path, maximum=1_000_000,
                                   label="registered payoff queue source")
    except (OSError, RuntimeError, ValueError):
        return _payoff_unknown("package_unavailable" if not source_path.exists()
                               else "source_unknown", checked_at)
    source_sha = hashlib.sha256(source_raw).hexdigest()
    if expected_source_sha256 is not None and source_sha != expected_source_sha256:
        return _payoff_unknown("source_unknown", checked_at)
    try:
        if queue_module is None:
            from experiments.payoff_decomposition import queue as queue_module
        if (Path(queue_module.__file__).resolve(strict=True) != source_path.resolve(strict=True)
                or queue_module.JOBS != PAYOFF_JOBS
                or queue_module.MAX_AVAILABILITY_REFUSALS != 24
                or Path(queue_module.controller.OUTPUT_ROOT) != payoff_root):
            return _payoff_unknown("source_unknown", checked_at)
        fingerprint = _payoff_fingerprint(payoff_root)
        # Time thresholds are part of status semantics even when no file changes.
        thresholds = tuple(
            (observed >= datetime.fromisoformat(job["not_before"]),
             observed >= datetime.fromisoformat(job["expires_at"]),
             observed.timestamp() + 1890 >= datetime.fromisoformat(job["expires_at"]).timestamp())
            for job in PAYOFF_JOBS.values())
        cache_key = (str(repo_root), str(payoff_root), source_sha, fingerprint, thresholds)
        global _PAYOFF_CACHE
        with _PAYOFF_CACHE_LOCK:
            cached = _PAYOFF_CACHE
            if cached is not None and cached[0] == cache_key and time.monotonic() < cached[1]:
                return cached[2]
            rows = []
            for job_id, registered in PAYOFF_JOBS.items():
                row = queue_module.status(job_id, now=observed)
                expected_path = payoff_root / (
                    job_id if row.get("attempt_index") == 0 else job_id + "-r1") / "window.json"
                if (not isinstance(row, dict) or
                        row.get("schema") != "known-opponent-payoff-job-status/v1" or
                        row.get("job_id") != job_id or
                        row.get("panel_id") != registered["panel_id"] or
                        row.get("not_before") != registered["not_before"] or
                        row.get("expires_at") != registered["expires_at"] or
                        row.get("role") != registered["role"] or
                        row.get("state") not in PAYOFF_STATES or
                        type(row.get("attempt_index")) is not int or
                        row["attempt_index"] not in (0, 1) or
                        row.get("window_path") not in (None, str(expected_path)) or
                        row.get("comparison_eligible") is not False):
                    return _payoff_unknown("source_unknown", checked_at)
                attempt = job_id if row["attempt_index"] == 0 else job_id + "-r1"
                refusal = _payoff_refusal(row.get("last_availability_refusal"),
                                          attempt=attempt, registered=registered,
                                          fingerprint=fingerprint, observed=observed)
                if refusal is not None and row["window_path"] is None:
                    return _payoff_unknown("source_unknown", checked_at)
                rows.append({"job_id": job_id, "panel_id": registered["panel_id"],
                             "not_before": registered["not_before"],
                             "expires_at": registered["expires_at"], "role": registered["role"],
                             "state": row["state"], "attempt_index": row["attempt_index"],
                             "prepared_window_present": row["window_path"] is not None,
                             "last_availability_refusal": refusal,
                             "comparison_eligible": False})
            projection = {"schema_version": PAYOFF_SCHEMA, "source_status": "available",
                          "checked_at": checked_at, "queue_source_sha256": source_sha,
                          "jobs": rows, "timer_activation": "not_verified",
                          "comparison_eligible": False}
            _PAYOFF_CACHE = (cache_key, time.monotonic() + 300.0, projection)
            return projection
    except (ImportError, OSError, RuntimeError, ValueError, TypeError, KeyError, AttributeError):
        return _payoff_unknown("source_unknown", checked_at)


def register(app, *, repo_root: Path = DEFAULT_REPO,
             ingestion_root: Path | None = None,
             pilot_root: Path = PILOT_ROOT,
             projector: Callable[..., dict] | None = None) -> None:
    router = APIRouter()

    @router.get("/api/research_ops_status")
    def research_ops_status():
        producer = projector
        if producer is None:
            try:
                from orchestrator.research_ops_status import project_research_ops_status
            except ImportError as exc:
                raise HTTPException(status_code=503,
                                    detail="research status source unavailable") from exc
            producer = project_research_ops_status
        view = producer(repo_root=repo_root, ingestion_root=ingestion_root)
        if projector is not None:
            return view
        enriched = _enrich(view, pilot_root, repo_root)
        return {**enriched, "payoff_jobs": _payoff_jobs(repo_root)}

    app.include_router(router)
