"""Two finite, preregistered payoff jobs; no dynamic study generation.

Preparing a job freezes its source/model/task bytes. At most one issued model
panel is allowed. One zero-call/no-mutation preflight refusal may create an
immutable r1 attempt window; a partial issued panel is never retried.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bench.flash_next_ab import qualification as q
from experiments.known_opponent_utility import admission as raw_gate
from experiments.payoff_decomposition import controller, study
from orchestrator.weekly_upgrade_trial import (
    TrialError,
    canonical_root,
    resource_lease,
    resource_probe,
)

SCHEMA = "known-opponent-payoff-job-dispatch/v1"
MAX_SERVICE_S = 1860  # outer worker + bounded emergency restore/wait + margin
PRECLAIM_MARGIN_S = 30  # source/qualification/probe before durable reservation
MAX_AVAILABILITY_REFUSALS = 24
JOBS = {
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


def _job(job_id: str) -> dict:
    if job_id not in JOBS:
        raise ValueError("unregistered empirical job ID")
    return JOBS[job_id]


def _window(job_id: str, attempt_index: int = 0) -> Path:
    return controller.OUTPUT_ROOT / controller._attempt_name(job_id, attempt_index) / "window.json"


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo != timezone.utc:
        raise ValueError("job time must be exact UTC")
    return parsed


def prepare(job_id: str) -> Path:
    job = _job(job_id)
    return controller.prepare(job_id=job_id, panel_id=job["panel_id"],
                              seed_base=job["seed_base"])


def validate_zero_call_refusal(job_id: str) -> dict:
    """Permit r1 only after full source/worker/no-call/no-mutation proof."""
    path = _window(job_id)
    document, manifest = controller.load_window(path)
    output = path.parent
    reservation_raw = raw_gate._read(output, "dispatch-reservation.json", 128_000)
    reservation = raw_gate._object(reservation_raw)
    start_raw = raw_gate._read(output, "supervision-start.json", 128_000)
    start = raw_gate._object(start_raw)
    state_raw = raw_gate._read(output, "state.json", 128_000)
    state = raw_gate._object(state_raw)
    result_raw = raw_gate._read(output, "result.json", 128_000)
    result = raw_gate._object(result_raw)
    supervisor_raw = raw_gate._read(output, "supervision.json", 128_000)
    supervisor = raw_gate._object(supervisor_raw)
    dispatch_raw = raw_gate._read(output, "dispatch-result.json", 128_000)
    final = raw_gate._object(dispatch_raw)
    window_sha = study.sha(controller._raw(path))
    expected_reservation = {
        "schema": SCHEMA, "job_id": job_id, "attempt_index": 0,
        "job_source_sha256": study.sha(Path(__file__).read_bytes()),
        "source_bundle_sha256": study.sha(study.raw_json(manifest["source_sha256"])),
        "window_sha256": window_sha,
        "manifest_sha256": manifest["manifest_sha256"],
        "qualification_receipt_sha256": document["qualification"]["receipt_sha256"],
        "reserved_at": reservation.get("reserved_at"),
        "not_before": JOBS[job_id]["not_before"],
        "expires_at": JOBS[job_id]["expires_at"],
        "prior_zero_call_refusal_sha256": None,
        "one_issued_study_attempt_only": True, "comparison_eligible": False,
    }
    reserved_time = _time(reservation.get("reserved_at", ""))
    if (reservation != expected_reservation
            or not _time(JOBS[job_id]["not_before"]) <= reserved_time
            or reserved_time + timedelta(seconds=MAX_SERVICE_S)
            > _time(JOBS[job_id]["expires_at"])
            or start.get("window_sha256") != window_sha
            or start.get("argv") != [
                document["launcher_python"], "-m", "experiments.payoff_decomposition.controller",
                "--worker", "--window", str(path)]
            or not isinstance(start.get("worker"), dict)
            or type(start["worker"].get("pid")) is not int
            or start["worker"]["pid"] <= 0
            or type(start["worker"].get("start_ticks")) is not int
            or start["worker"]["start_ticks"] <= 0
            or not isinstance(start["worker"].get("boot_id"), str)
            or len(start["worker"]["boot_id"]) != 36
            or state.get("worker") != start["worker"]
            or state.get("schema") != controller.STATE_SCHEMA
            or state.get("window_sha256") != window_sha
            or state.get("phase") != "incomplete"
            or state.get("preflight_failure_code") != "resource_lease_busy"
            or state.get("initial") is not None
            or state.get("watchdog_sentinel_id") is not None
            or state.get("sentinel_absent_before_create") is not False
            or state.get("nara_stop_attempted") is not False
            or result.get("schema") != controller.RESULT_SCHEMA
            or result.get("window_sha256") != window_sha
            or result.get("status") != "incomplete"
            or result.get("preflight_failure_code") != "resource_lease_busy"
            or result.get("study_run_sha256") is not None
            or result.get("admission_ready_proof_sha256") is not None
            or result.get("memory_samples") != 0
            or result.get("restoration") != state.get("restoration")
            or result.get("restoration", {}).get("status") != "verified"
            or result["restoration"].get("errors") != []
            or result["restoration"].get("sentinel_retained") is not False
            or result["restoration"].get("no_mutation_verified") is not True
            or supervisor.get("schema") != controller.SUPERVISION_SCHEMA
            or supervisor.get("window_sha256") != window_sha
            or supervisor.get("returncode") != 1
            or supervisor.get("terminated_at_cutoff") is not False
            or supervisor.get("interrupted") is not None
            or supervisor.get("emergency_restoration") is not None
            or final.get("schema") != "known-opponent-payoff-job-dispatch-result/v1"
            or final.get("job_id") != job_id
            or final.get("attempt_index") != 0
            or final.get("window_sha256") != window_sha
            or final.get("reservation_sha256") != study.sha(reservation_raw)
            or final.get("supervisor_returncode") != 1
            or final.get("admission_receipt_sha256") is not None
            or final.get("status") != "observed_unadmitted"
            or (output / "study").exists()
            or (output / "resident-memory.jsonl").exists()
            or (output / "admission-ready-proof.json").exists()
            or (output / "admission.json").exists()):
        raise ValueError("prior attempt lacks zero-call/no-mutation refusal proof")
    return {"schema": "known-opponent-payoff-zero-call-refusal/v1",
            "job_id": job_id, "window_sha256": window_sha,
            "reservation_sha256": study.sha(reservation_raw),
            "state_sha256": study.sha(state_raw),
            "result_sha256": study.sha(result_raw),
            "supervision_sha256": study.sha(supervisor_raw),
            "dispatch_result_sha256": study.sha(dispatch_raw),
            "model_calls_issued": 0, "no_mutation_verified": True,
            "retry_allowed": True, "comparison_eligible": False}


def _selected_path(job_id: str) -> tuple[Path, dict | None]:
    first = _window(job_id)
    if not (first.parent / "dispatch-reservation.json").exists():
        return first, None
    if (first.parent / "job-admission.json").exists():
        return first, None
    refusal = validate_zero_call_refusal(job_id)
    second = _window(job_id, 1)
    if not second.exists():
        job = _job(job_id)
        controller.prepare(job_id=job_id, panel_id=job["panel_id"],
                           seed_base=job["seed_base"], attempt_index=1,
                           prior_refusal=refusal)
    return second, refusal


def _record_availability_refusal(path: Path, document: dict, manifest: dict,
                                 code: str) -> Path:
    if code not in {"resource_lease_busy", "resource_probe_blocked",
                    "availability_unknown"}:
        raise ValueError("unclosed availability refusal code")
    output = path.parent
    receipt = {"schema": "known-opponent-payoff-availability-refusal/v1",
               "job_id": document["job_id"],
               "attempt_index": document["attempt_index"],
               "window_sha256": study.sha(controller._raw(path)),
               "source_bundle_sha256": study.sha(study.raw_json(manifest["source_sha256"])),
               "refused_at": q.utc_now(), "failure_code": code,
               "dispatch_claim_written": False, "model_calls_issued": 0,
               "comparison_eligible": False}
    for ordinal in range(MAX_AVAILABILITY_REFUSALS):
        destination = output / f"availability-refusal-{ordinal:02d}.json"
        if not destination.exists():
            controller._new(destination, receipt)
            return destination
    raise ValueError("bounded availability refusal journal is full")


def _last_availability_refusal(path: Path) -> dict | None:
    output = path.parent
    for ordinal in reversed(range(MAX_AVAILABILITY_REFUSALS)):
        name = f"availability-refusal-{ordinal:02d}.json"
        if (output / name).exists():
            try:
                document, manifest = controller.load_window(path)
                raw = raw_gate._read(output, name, 128_000)
                receipt = raw_gate._object(raw)
                if (receipt.get("schema") == "known-opponent-payoff-availability-refusal/v1"
                        and receipt.get("job_id") == document["job_id"]
                        and receipt.get("attempt_index") == document["attempt_index"]
                        and receipt.get("window_sha256") == study.sha(controller._raw(path))
                        and receipt.get("source_bundle_sha256")
                        == study.sha(study.raw_json(manifest["source_sha256"]))
                        and _time(JOBS[document["job_id"]]["not_before"])
                        <= _time(receipt.get("refused_at", ""))
                        and _time(receipt["refused_at"]) + timedelta(seconds=MAX_SERVICE_S)
                        <= _time(JOBS[document["job_id"]]["expires_at"])
                        and receipt.get("failure_code") in {
                            "resource_lease_busy", "resource_probe_blocked",
                            "availability_unknown"}
                        and receipt.get("dispatch_claim_written") is False
                        and type(receipt.get("model_calls_issued")) is int
                        and receipt["model_calls_issued"] == 0):
                    return {"failure_code": receipt["failure_code"],
                            "refused_at": receipt.get("refused_at"),
                            "receipt_sha256": study.sha(raw)}
            except Exception:  # noqa: BLE001 - unknown receipt never becomes trusted status
                return {"status": "receipt_present_unverified"}
            return {"status": "receipt_present_unverified"}
    return None


def status(job_id: str, *, now: datetime | None = None) -> dict:
    job = _job(job_id)
    now = now or datetime.now(timezone.utc)
    second = _window(job_id, 1)
    path = second if second.exists() else _window(job_id)
    output = path.parent
    if (output / "job-admission.json").exists():
        try:
            recorded = raw_gate._object(raw_gate._read(output, "job-admission.json", 128_000))
            state = ("admitted_attempt_verified" if recorded == validate_dispatch(job_id)
                     else "admission_receipt_present_unverified")
        except Exception:  # noqa: BLE001 - unreadable/current-source drift stays unknown
            state = "admission_receipt_present_unverified"
    elif (output / "admission.json").exists():
        state = "admission_receipt_present_unverified"
    elif (_window(job_id).parent / "dispatch-reservation.json").exists() and not (
            second.parent / "dispatch-reservation.json").exists():
        try:
            validate_zero_call_refusal(job_id)
            if now + timedelta(seconds=MAX_SERVICE_S + PRECLAIM_MARGIN_S) > _time(job["expires_at"]):
                state = "expired_after_zero_call_refusal"
            elif second.exists():
                controller.load_window(second)
                state = "zero_call_refusal_retry_prepared"
            else:
                state = "zero_call_refusal_retry_eligible"
        except Exception:  # noqa: BLE001 - issued/unknown attempts never become eligible
            state = "attempt_reserved_or_recorded"
    elif (output / "dispatch-reservation.json").exists():
        state = "attempt_reserved_or_recorded"
    elif now >= _time(job["expires_at"]):
        state = "expired_unattempted"
    elif now < _time(job["not_before"]):
        state = "not_due"
    elif path.exists():
        try:
            controller.load_window(path)
            state = "eligible_prepared"
        except Exception:  # noqa: BLE001 - file existence does not certify source/plan
            state = "prepared_unverified"
    else:
        state = "eligible_unprepared"
    return {"schema": "known-opponent-payoff-job-status/v1", "job_id": job_id,
            "panel_id": job["panel_id"], "not_before": job["not_before"],
            "expires_at": job["expires_at"], "role": job["role"],
            "state": state, "attempt_index": 1 if path == second else 0,
            "window_path": str(path) if path.is_file() else None,
            "last_availability_refusal": (_last_availability_refusal(path)
                                          if path.is_file() else None),
            "comparison_eligible": False}


def dispatch(job_id: str, *, now: datetime | None = None) -> int:
    """Reserve one exact eligible attempt, then invoke supervised controller."""
    job = _job(job_id)
    now = now or datetime.now(timezone.utc)
    if (not _time(job["not_before"]) <= now
            or now + timedelta(seconds=MAX_SERVICE_S + PRECLAIM_MARGIN_S)
            > _time(job["expires_at"])):
        raise ValueError("empirical job is outside preregistered execution interval")
    first = _window(job_id)
    second = _window(job_id, 1)
    admitted_path = (second if (second.parent / "job-admission.json").exists()
                     else first if (first.parent / "job-admission.json").exists() else None)
    if admitted_path is not None:
        if validate_dispatch(job_id) == raw_gate._object(raw_gate._read(
                admitted_path.parent, "job-admission.json", 128_000)):
            return 0  # A later bounded timer tick does not issue another call.
        raise ValueError("recorded job admission does not replay")
    if (second.parent / "admission.json").exists() or (first.parent / "admission.json").exists():
        publish_job_receipt(job_id)  # Recover publication only; never issue another call.
        return 0
    path, prior_refusal = _selected_path(job_id)
    document, manifest = controller.load_window(path)
    if document["job_id"] != job_id or manifest["seed_base"] != job["seed_base"]:
        raise ValueError("prepared empirical job differs from source registry")
    output = path.parent
    if (output / "dispatch-reservation.json").exists():
        raise ValueError("empirical job already had its one admitted attempt")
    # A busy coordinator/model lease leaves the job eligible and unreserved.
    # The worker repeats this probe under its own lease; a race is recorded as
    # an incomplete single attempt rather than silently reused.
    stage = "lease"
    try:
        with resource_lease(canonical_root(controller.CODE_ROOT)):
            stage = "probe"
            resource_probe(canonical_root(controller.CODE_ROOT), idle=True)
    except Exception as exc:  # no claim/call; retain bounded refusal
        code = ("resource_lease_busy" if stage == "lease" and isinstance(exc, TrialError) else
                "resource_probe_blocked" if stage == "probe" and isinstance(exc, TrialError)
                else "availability_unknown")
        _record_availability_refusal(path, document, manifest, code)
        raise
    reservation = {"schema": SCHEMA, "job_id": job_id,
                   "attempt_index": document["attempt_index"],
                   "job_source_sha256": study.sha(Path(__file__).read_bytes()),
                   "source_bundle_sha256": study.sha(study.raw_json(manifest["source_sha256"])),
                   "window_sha256": study.sha(controller._raw(path)),
                   "manifest_sha256": manifest["manifest_sha256"],
                   "qualification_receipt_sha256": document["qualification"]["receipt_sha256"],
                   "reserved_at": q.utc_now(), "not_before": job["not_before"],
                   "expires_at": job["expires_at"],
                   "prior_zero_call_refusal_sha256": (
                       study.sha(study.raw_json(prior_refusal)) if prior_refusal else None),
                   "one_issued_study_attempt_only": True,
                   "comparison_eligible": False}
    controller._new(output / "dispatch-reservation.json", reservation)
    rc = controller.supervise(path)
    admission_path = None
    admission_error = None
    if rc == 0:
        try:
            admission_path = controller.publish_admission(path)
        except Exception as exc:  # noqa: BLE001 - closed failed gate remains visible
            admission_error = type(exc).__name__
    final = {"schema": "known-opponent-payoff-job-dispatch-result/v1",
             "job_id": job_id, "attempt_index": document["attempt_index"],
             "window_sha256": reservation["window_sha256"],
             "reservation_sha256": study.sha(controller._raw(output / "dispatch-reservation.json")),
             "supervisor_returncode": rc,
             "admission_receipt_sha256": (study.sha(controller._raw(admission_path))
                                           if admission_path else None),
             "admission_error_code": admission_error,
             "status": "admitted_diagnostic" if admission_path else "observed_unadmitted",
             "finished_at": q.utc_now(), "comparison_eligible": False}
    controller._new(output / "dispatch-result.json", final)
    if admission_path:
        publish_job_receipt(job_id)
    return 0 if admission_path else 1


def validate_dispatch(job_id: str) -> dict:
    """Read-only replay of one reserved, completed, source-bound job attempt."""
    job = _job(job_id)
    second = _window(job_id, 1)
    path = second if (second.parent / "dispatch-reservation.json").exists() else _window(job_id)
    document, manifest = controller.load_window(path)
    prior_refusal = validate_zero_call_refusal(job_id) if document["attempt_index"] == 1 else None
    output = path.parent
    reservation_raw = raw_gate._read(output, "dispatch-reservation.json", 128_000)
    reservation = raw_gate._object(reservation_raw)
    dispatch_raw = raw_gate._read(output, "dispatch-result.json", 128_000)
    final = raw_gate._object(dispatch_raw)
    reserved_time = _time(reservation.get("reserved_at", ""))
    if (reservation != {
            "schema": SCHEMA, "job_id": job_id,
            "attempt_index": document["attempt_index"],
            "job_source_sha256": study.sha(Path(__file__).read_bytes()),
            "source_bundle_sha256": study.sha(study.raw_json(manifest["source_sha256"])),
            "window_sha256": study.sha(controller._raw(path)),
            "manifest_sha256": manifest["manifest_sha256"],
            "qualification_receipt_sha256": document["qualification"]["receipt_sha256"],
            "reserved_at": reservation["reserved_at"],
            "not_before": job["not_before"], "expires_at": job["expires_at"],
            "prior_zero_call_refusal_sha256": (
                study.sha(study.raw_json(prior_refusal)) if prior_refusal else None),
            "one_issued_study_attempt_only": True, "comparison_eligible": False}
            or not _time(job["not_before"]) <= reserved_time
            or reserved_time + timedelta(seconds=MAX_SERVICE_S) > _time(job["expires_at"])):
        raise ValueError("empirical dispatch reservation/source/time drifted")
    admission = controller.validate_completed(path)
    admission_raw = raw_gate._read(output, "admission.json", 128_000)
    if (raw_gate._object(admission_raw) != admission
            or admission_raw != controller.stable._json(admission)):
        raise ValueError("recorded payoff admission differs from independent replay")
    if (final.get("schema") != "known-opponent-payoff-job-dispatch-result/v1"
            or final.get("job_id") != job_id
            or final.get("attempt_index") != document["attempt_index"]
            or final.get("window_sha256") != reservation["window_sha256"]
            or final.get("reservation_sha256") != study.sha(reservation_raw)
            or final.get("supervisor_returncode") != 0
            or final.get("admission_receipt_sha256") != study.sha(admission_raw)
            or final.get("admission_error_code") is not None
            or final.get("status") != "admitted_diagnostic"
            or final.get("comparison_eligible") is not False):
        raise ValueError("job dispatch result differs from admitted raw receipts")
    return {"schema": "known-opponent-payoff-job-validation/v1",
            "job_id": job_id, "panel_id": job["panel_id"],
            "attempt_index": document["attempt_index"],
            "prior_zero_call_refusal_sha256": reservation["prior_zero_call_refusal_sha256"],
            "reservation_sha256": study.sha(reservation_raw),
            "dispatch_result_sha256": study.sha(dispatch_raw),
            "window_sha256": reservation["window_sha256"],
            "admission_receipt_sha256": study.sha(admission_raw),
            "attempted_calls": admission["study_validation"]["attempted_calls"],
            "summary": admission["study_validation"]["summary"],
            "by_view": admission["study_validation"]["by_view"],
            "by_seat": admission["study_validation"]["by_seat"],
            "status": "admitted_diagnostic", "comparison_eligible": False,
            "scientific_novelty_claimed": False}


def publish_job_receipt(job_id: str) -> Path:
    value = validate_dispatch(job_id)
    destination = _window(job_id, value["attempt_index"]).parent / "job-admission.json"
    controller._new(destination, value)
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--status", action="store_true")
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--dispatch", action="store_true")
    mode.add_argument("--validate", action="store_true")
    parser.add_argument("--job-id", required=True, choices=tuple(JOBS))
    args = parser.parse_args(argv)
    if args.status:
        print(json.dumps(status(args.job_id), sort_keys=True))
        return 0
    if args.prepare:
        print(prepare(args.job_id))
        return 0
    if args.validate:
        print(publish_job_receipt(args.job_id))
        return 0
    return dispatch(args.job_id)


if __name__ == "__main__":
    raise SystemExit(main())
