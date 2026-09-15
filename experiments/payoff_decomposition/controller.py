"""Supervise one finite resident-only payoff instrument without benchmark claims.

The stable resident lifecycle owns container identity, watchdog, Nara restoration,
and memory checks. This controller freezes a separate task/model/source window.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import signal
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from bench.flash_next_ab import qualification as q
from bench.flash_next_ab import resident_admission as resident_gate
from bench.flash_next_ab import resident_evaluation_window as resident
from experiments.known_opponent_utility import resident_controller as stable
from experiments.payoff_decomposition import admission, runner, study
from orchestrator.weekly_upgrade_trial import (
    TrialError,
    canonical_root,
    resource_lease,
    resource_probe,
)

CODE_ROOT = Path(__file__).resolve().parents[2]
CANONICAL_ROOT = Path("/home/decross1/projects/a_bgt_rsi")
OUTPUT_ROOT = stable.ARTIFACT_ROOT / "payoff-decomposition"
WINDOW_SCHEMA = "known-opponent-payoff-resident-window/v1"
STATE_SCHEMA = "known-opponent-payoff-resident-state/v1"
RESULT_SCHEMA = "known-opponent-payoff-resident-result/v1"
SUPERVISION_SCHEMA = "known-opponent-payoff-resident-supervision/v1"
ADMISSION_SCHEMA = "known-opponent-payoff-resident-admission/v1"
WALL_S = 1500
STUDY_S = 900
RESTORE_S = 300


def _must(ok: bool, reason: str) -> None:
    if not ok:
        raise ValueError(reason)


def _raw(path: Path, limit: int = 2_000_000) -> bytes:
    return stable._raw(path, limit)


def _sha(raw: bytes) -> str:
    return study.sha(raw)


def _new(path: Path, value: dict) -> None:
    stable._new(path, value)


@contextmanager
def _lease_or_no_call_refusal(root: Path):
    """Make a lease race a durable pre-mutation refusal when it is known busy."""
    lease = resource_lease(root)
    try:
        lease.__enter__()
    except TrialError:
        yield False
        return
    try:
        yield True
    finally:
        lease.__exit__(None, None, None)


def _attempt_name(job_id: str, attempt_index: int) -> str:
    _must(type(attempt_index) is int and attempt_index in (0, 1),
          "payoff execution permits only an initial and one proven zero-call retry")
    return job_id if attempt_index == 0 else job_id + "-r1"


def prepare(*, job_id: str, panel_id: str, seed_base: int,
            attempt_index: int = 0, prior_refusal: dict | None = None) -> Path:
    """Freeze integrated canonical source and qualified resident identity once."""
    _must(CODE_ROOT == CANONICAL_ROOT and Path(study.__file__).resolve().is_relative_to(CODE_ROOT),
          "payoff study must prepare from integrated canonical source")
    _must(job_id in {"payoff-representation-a", "payoff-representation-b"}
          and panel_id == job_id, "unregistered payoff job/panel")
    launcher = Path(sys.executable)
    expected_launcher = CODE_ROOT / ".venv-chroma/bin/python"
    _must(launcher.is_absolute() and launcher.is_relative_to(CODE_ROOT)
          and launcher.resolve(strict=True) == expected_launcher.resolve(strict=True),
          "payoff launcher must use integrated canonical project interpreter")
    summary = stable._qualification()
    endpoint = stable._endpoint(summary)
    manifest = study.freeze_manifest(source_root=CODE_ROOT, endpoint=endpoint,
                                     registered_admission=summary,
                                     panel_id=panel_id, seed_base=seed_base)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    _must(OUTPUT_ROOT.resolve() == OUTPUT_ROOT, "payoff output root is redirected")
    attempt_name = _attempt_name(job_id, attempt_index)
    if attempt_index == 0:
        _must(prior_refusal is None, "initial payoff window cannot cite a retry refusal")
    else:
        _must(isinstance(prior_refusal, dict)
              and prior_refusal.get("schema") == "known-opponent-payoff-zero-call-refusal/v1"
              and prior_refusal.get("job_id") == job_id
              and prior_refusal.get("retry_allowed") is True,
              "r1 payoff window requires exact prior zero-call refusal proof")
    output = OUTPUT_ROOT / attempt_name
    output.mkdir(mode=0o700)
    _new(output / "manifest.snapshot.json", manifest)
    if prior_refusal is not None:
        _new(output / "prior-refusal.snapshot.json", prior_refusal)
    snapshot_raw = _raw(output / "manifest.snapshot.json")
    document = {"schema": WINDOW_SCHEMA, "job_id": job_id,
                "attempt_index": attempt_index,
                "window_id": "qfn-followon-" + attempt_name,
                "created_at": q.utc_now(), "code_root": str(CODE_ROOT),
                "launcher_python": str(launcher),
                "launcher_python_sha256": _sha(launcher.read_bytes()),
                "output_dir": str(output), "panel_id": panel_id,
                "manifest": {"path": str(output / "manifest.snapshot.json"),
                             "sha256": _sha(snapshot_raw)},
                "prior_zero_call_refusal": (
                    {"path": str(output / "prior-refusal.snapshot.json"),
                     "sha256": _sha(_raw(output / "prior-refusal.snapshot.json"))}
                    if prior_refusal is not None else None),
                "qualification": {
                    "receipt_path": str(stable.RESIDENT_RECEIPT),
                    "receipt_sha256": _sha(_raw(stable.RESIDENT_RECEIPT)),
                    "inventory_path": str(stable.RESIDENT_INVENTORY),
                    "inventory_sha256": _sha(_raw(stable.RESIDENT_INVENTORY)),
                    "summary_sha256": _sha(stable._json(summary))},
                "controller_sources": study.source_bundle(CODE_ROOT),
                "endpoint": endpoint.__dict__, "policy": study.POLICY,
                "wall_s": WALL_S, "study_s": STUDY_S,
                "restoration_reserve_s": RESTORE_S,
                "comparison_eligible": False,
                "promotion_authorized": False, "trading_claim_authorized": False}
    _new(output / "window.json", document)
    return output / "window.json"


def load_window(path: Path) -> tuple[dict, dict]:
    document = json.loads(_raw(path))
    job_id = document.get("job_id") if isinstance(document, dict) else None
    attempt_index = document.get("attempt_index") if isinstance(document, dict) else None
    _must(job_id in {"payoff-representation-a", "payoff-representation-b"}
          and type(attempt_index) is int and attempt_index in (0, 1),
          "unregistered payoff job or retry index")
    attempt_name = _attempt_name(job_id, attempt_index)
    _must(isinstance(document, dict) and document.get("schema") == WINDOW_SCHEMA
          and document.get("job_id") == job_id
          and document.get("panel_id") == document["job_id"]
          and document.get("window_id") == "qfn-followon-" + attempt_name
          and document.get("code_root") == str(CODE_ROOT)
          and isinstance(document.get("launcher_python"), str)
          and Path(document["launcher_python"]).is_relative_to(CODE_ROOT)
          and Path(document["launcher_python"]).resolve(strict=True)
          == (CODE_ROOT / ".venv-chroma/bin/python").resolve(strict=True)
          and document.get("launcher_python_sha256")
          == _sha(Path(document["launcher_python"]).read_bytes())
          and document.get("output_dir") == str(OUTPUT_ROOT / attempt_name)
          and path == OUTPUT_ROOT / attempt_name / "window.json"
          and document.get("wall_s") == WALL_S
          and document.get("study_s") == STUDY_S
          and document.get("restoration_reserve_s") == RESTORE_S
          and document.get("comparison_eligible") is False
          and document.get("promotion_authorized") is False
          and document.get("trading_claim_authorized") is False,
          "payoff window identity or finite caps drifted")
    _must(document.get("controller_sources") == study.source_bundle(CODE_ROOT),
          "payoff controller/task source bundle drifted")
    output = Path(document["output_dir"])
    snapshot_path = output / "manifest.snapshot.json"
    _must(document.get("manifest") == {"path": str(snapshot_path),
                                       "sha256": _sha(_raw(snapshot_path))},
          "payoff manifest snapshot differs from immutable window")
    manifest = json.loads(_raw(snapshot_path))
    study.validate_manifest(manifest)
    if attempt_index == 0:
        _must(document.get("prior_zero_call_refusal") is None,
              "initial window cannot claim a prior refusal")
    else:
        from experiments.payoff_decomposition import queue  # local import avoids cycle

        prior_path = output / "prior-refusal.snapshot.json"
        prior_raw = _raw(prior_path)
        _must(document.get("prior_zero_call_refusal") == {
                  "path": str(prior_path), "sha256": _sha(prior_raw)}
              and prior_raw == stable._json(queue.validate_zero_call_refusal(job_id)),
              "r1 window does not bind the independently replayed no-call refusal")
    summary = stable._qualification()
    _must(document.get("qualification") == {
              "receipt_path": str(stable.RESIDENT_RECEIPT),
              "receipt_sha256": _sha(_raw(stable.RESIDENT_RECEIPT)),
              "inventory_path": str(stable.RESIDENT_INVENTORY),
              "inventory_sha256": _sha(_raw(stable.RESIDENT_INVENTORY)),
              "summary_sha256": _sha(stable._json(summary))}
          and manifest["registered_admission"] == summary
          and document.get("endpoint") == stable._endpoint(summary).__dict__
          and manifest["endpoint"] == document["endpoint"]
          and document.get("policy") == study.POLICY
          and manifest["policy"] == study.POLICY,
          "resident qualification/model/policy differs before payoff calls")
    return document, manifest


def worker(path: Path, *, ops=None, run_fn=runner.run_study) -> dict:
    """Run under canonical resource lease and always attempt exact restoration."""
    document, manifest = load_window(path)
    output = Path(document["output_dir"])
    ops = ops or q.HostOps()
    deadline = time.monotonic() + WALL_S
    cutoff = deadline - RESTORE_S
    state = {"schema": STATE_SCHEMA, "phase": "preflight",
             "window_sha256": _sha(_raw(path)), "started_at": q.utc_now(),
             "preflight_failure_code": None,
             "initial": None, "watchdog_sentinel_id": None,
             "sentinel_absent_before_create": False, "nara_stop_attempted": False,
             "worker": stable._identity(os.getpid())}
    q._atomic_write(output / "state.json", state)
    run, error, monitor = None, None, None
    with _lease_or_no_call_refusal(canonical_root(CODE_ROOT)) as lease_acquired:
        try:
            if not lease_acquired:
                state["preflight_failure_code"] = "resource_lease_busy"
                q._atomic_write(output / "state.json", state)
                raise ValueError("payoff resource lease became occupied before mutation")
            resource_probe(canonical_root(CODE_ROOT), idle=True)
            state["initial"] = resident._read_exact_residents(ops)
            q._atomic_write(output / "state.json", state)
            monitor = resident.ResidentSafetyMonitor(output / "resident-memory.jsonl", ops,
                                                     state["initial"], deadline=deadline)
            with monitor:
                try:
                    _must(resident._inspect_container(ops, resident._sentinel_name(document["window_id"]))
                          is None, "pre-existing payoff watchdog")
                    state["sentinel_absent_before_create"] = True
                    q._atomic_write(output / "state.json", state)
                    sid = resident._create_sentinel(ops, document["window_id"])
                    state["watchdog_sentinel_id"] = sid
                    q._atomic_write(output / "state.json", state)
                    monitor.bind_sentinel(sid)
                    monitor.transition("quiescing")
                    if state["initial"]["nara"]["ActiveState"] == "active":
                        state["nara_stop_attempted"] = True
                        q._atomic_write(output / "state.json", state)
                        ops.run(["systemctl", "--user", "stop", q.NARA_SERVICE], timeout=30)
                    quiet = resident._read_exact_residents(ops, state["initial"], nara_transition=True)
                    monitor.transition("evaluation", cohort_initial=quiet)

                    def admit():
                        monitor.check()
                        _must(time.monotonic() < cutoff, "payoff cutoff before model admission")
                        live = resident._read_exact_residents(ops, state["initial"], nara_transition=True)
                        _must(live["nara"]["ActiveState"] == "inactive"
                              and state["watchdog_sentinel_id"] == sid,
                              "resident isolation differs before payoff calls")
                        summary = stable._qualification()
                        _must(summary == manifest["registered_admission"],
                              "registered resident model admission drifted")
                        q._atomic_write(output / "admission-ready-proof.json", live)
                        return summary

                    state["phase"] = "study"
                    q._atomic_write(output / "state.json", state)
                    run = run_fn(manifest, output=output / "study", admission_gate=admit,
                                 safety_check=lambda: (monitor.check(),
                                                       _must(time.monotonic() < cutoff,
                                                             "payoff work cutoff reached")),
                                 cancel_event=monitor.cancel_event)
                    monitor.check()
                except BaseException as exc:  # noqa: BLE001 - restoration owns signals too
                    error = f"{type(exc).__name__}: {exc}"
                finally:
                    state["phase"] = "restoration"
                    q._atomic_write(output / "state.json", state)
                    try:
                        monitor.transition("restoration")
                    finally:
                        state["restoration"] = stable._restore(
                            ops, state, document, output, deadline=deadline,
                            monitor=monitor if monitor.phase == "restoration" else None)
                        q._atomic_write(output / "state.json", state)
        except BaseException as exc:  # noqa: BLE001 - premonitor recovery still audited
            error = error or f"{type(exc).__name__}: {exc}"
            if state.get("restoration") is None:
                state["restoration"] = stable._restore(ops, state, document, output,
                                                        deadline=deadline)
                q._atomic_write(output / "state.json", state)
    restored = state.get("restoration", {}).get("status") == "verified"
    observed = run is not None and run.get("status") == "complete"
    status = ("observed_restored" if observed and restored and error is None
              and not (monitor and monitor.failure) else "incomplete")
    state["phase"] = status
    q._atomic_write(output / "state.json", state)
    result = {"schema": RESULT_SCHEMA, "window_id": document["window_id"],
              "window_sha256": _sha(_raw(path)), "started_at": state["started_at"],
              "preflight_failure_code": state["preflight_failure_code"],
              "finished_at": q.utc_now(), "status": status,
              "error": error or (monitor.failure if monitor else None),
              "restoration": state.get("restoration"),
              "minimum_mem_available_gib": (monitor.minimum_observed_gib
                                             if monitor and math.isfinite(monitor.minimum_observed_gib)
                                             else None),
              "memory_samples": monitor.samples if monitor else 0,
              "memory_log_sha256": (_sha(_raw(output / "resident-memory.jsonl", 64 * 1024 * 1024))
                                    if (output / "resident-memory.jsonl").is_file() else None),
              "watchdog_sentinel_id": state.get("watchdog_sentinel_id"),
              "admission_ready_proof_sha256": (
                  _sha(_raw(output / "admission-ready-proof.json"))
                  if (output / "admission-ready-proof.json").is_file() else None),
              "study_run_sha256": (_sha(_raw(output / "study/run.json", 1_000_000))
                                   if (output / "study/run.json").is_file() else None),
              "comparison_eligible": False, "promotion_authorized": False,
              "trading_claim_authorized": False}
    _new(output / "result.json", result)
    return result


def supervise(path: Path) -> int:
    document, _ = load_window(path)
    output = Path(document["output_dir"])
    _must(not (output / "supervision-reservation.json").exists(),
          "payoff study already supervised")
    _new(output / "supervision-reservation.json", {
        "window_sha256": _sha(_raw(path)), "reserved_at": q.utc_now(),
        "parent": stable._identity(os.getpid())})
    started = time.monotonic()
    command = [document["launcher_python"], "-m", "experiments.payoff_decomposition.controller",
               "--worker", "--window", str(path)]
    with (output / "controller.log").open("xb") as log:
        child = subprocess.Popen(command, cwd=CODE_ROOT, stdout=log,
                                 stderr=subprocess.STDOUT, start_new_session=True)
        terminated, interrupted = False, None
        try:
            _new(output / "supervision-start.json", {
                "window_sha256": _sha(_raw(path)), "argv": command,
                "started_at": q.utc_now(), "worker": stable._identity(child.pid)})
            while child.poll() is None:
                elapsed = time.monotonic() - started
                if elapsed >= WALL_S - RESTORE_S and not terminated:
                    child.send_signal(signal.SIGTERM)
                    terminated = True
                if elapsed >= WALL_S:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait(timeout=30)
                    break
                time.sleep(1)
        except BaseException as exc:  # noqa: BLE001 - parent recovers interrupted worker
            interrupted = type(exc).__name__
            if child.poll() is None:
                child.send_signal(signal.SIGTERM)
                terminated = True
                try:
                    child.wait(timeout=RESTORE_S)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait(timeout=30)
    result = json.loads(_raw(output / "result.json")) if (output / "result.json").is_file() else {}
    recovery = None
    if result.get("restoration", {}).get("status") != "verified" and (output / "state.json").is_file():
        state = json.loads(_raw(output / "state.json"))
        _must(state.get("window_sha256") == _sha(_raw(path)),
              "payoff recovery state belongs elsewhere")
        with resource_lease(canonical_root(CODE_ROOT)):
            recovery = stable._restore(q.HostOps(), state, document, output,
                                       deadline=time.monotonic() + RESTORE_S)
    _new(output / "supervision.json", {"schema": SUPERVISION_SCHEMA,
         "window_sha256": _sha(_raw(path)), "returncode": child.returncode,
         "elapsed_s": time.monotonic() - started,
         "terminated_at_cutoff": terminated, "interrupted": interrupted,
         "emergency_restoration": recovery, "finished_at": q.utc_now()})
    return 0 if (child.returncode == 0 and result.get("status") == "observed_restored"
                 and interrupted is None and not terminated) else 1


def validate_completed(path: Path) -> dict:
    """Replay terminal safety and raw responses; no model or host mutation."""
    document, _ = load_window(path)
    output = Path(document["output_dir"])
    result = json.loads(_raw(output / "result.json"))
    state = json.loads(_raw(output / "state.json"))
    supervision = json.loads(_raw(output / "supervision.json"))
    supervision_start = json.loads(_raw(output / "supervision-start.json"))
    supervision_reservation = json.loads(_raw(output / "supervision-reservation.json"))
    _must(result.get("schema") == RESULT_SCHEMA
          and result.get("status") == "observed_restored"
          and result.get("window_sha256") == _sha(_raw(path))
          and result.get("restoration", {}).get("status") == "verified"
          and result.get("restoration", {}).get("sentinel_retained") is False
          and result.get("error") is None
          and result.get("comparison_eligible") is False
          and result.get("promotion_authorized") is False
          and result.get("trading_claim_authorized") is False
          and state.get("phase") == "observed_restored"
          and state.get("window_sha256") == _sha(_raw(path))
          and state.get("restoration") == result["restoration"]
          and state.get("started_at") == result.get("started_at")
          and result["restoration"].get("errors") == []
          and isinstance(result["restoration"].get("verified_at"), str)
          and supervision.get("schema") == SUPERVISION_SCHEMA
          and supervision.get("window_sha256") == _sha(_raw(path))
          and supervision.get("returncode") == 0
          and supervision.get("terminated_at_cutoff") is False
          and supervision.get("interrupted") is None
          and supervision.get("emergency_restoration") is None,
          "payoff terminal supervision or restoration is incomplete")
    _must(supervision_start.get("window_sha256") == _sha(_raw(path))
          and supervision_start.get("argv") == [
              document["launcher_python"], "-m", "experiments.payoff_decomposition.controller",
              "--worker", "--window", str(path)]
          and state.get("worker") == supervision_start.get("worker")
          and isinstance(state["worker"], dict)
          and type(state["worker"].get("pid")) is int
          and state["worker"]["pid"] > 0
          and type(state["worker"].get("start_ticks")) is int
          and state["worker"]["start_ticks"] > 0
          and isinstance(state["worker"].get("boot_id"), str)
          and len(state["worker"]["boot_id"]) == 36
          and supervision_reservation.get("window_sha256") == _sha(_raw(path))
          and isinstance(supervision_reservation.get("parent"), dict),
          "payoff worker/launcher reservation identity drifted")
    ready_raw = _raw(output / "admission-ready-proof.json")
    ready = json.loads(ready_raw)
    _must(result.get("admission_ready_proof_sha256") == _sha(ready_raw)
          and state.get("watchdog_sentinel_id") == result.get("watchdog_sentinel_id")
          and ready.get("nara", {}).get("ActiveState") == "inactive"
          and ready.get("residents_by_name") == state.get("initial", {}).get("residents_by_name"),
          "payoff resident/Nara live proof differs")
    resident_gate._memory(
        output,
        {"memory_log_sha256": result.get("memory_log_sha256"),
         "memory_samples": result.get("memory_samples"),
         "watchdog_sentinel_id": result.get("watchdog_sentinel_id"),
         "min_mem_available_gib": result.get("minimum_mem_available_gib")},
        state["initial"], ready, result["restoration"]["final_observation"],
    )
    replay = admission.validate_study(output / "study")
    _must(result.get("study_run_sha256") == _sha(_raw(output / "study/run.json", 1_000_000))
          and replay["admission_eligible"] is True,
          "payoff panel was partial or raw replay differed")
    return {"schema": ADMISSION_SCHEMA, "window_id": document["window_id"],
            "window_sha256": _sha(_raw(path)),
            "result_sha256": _sha(_raw(output / "result.json")),
            "supervision_sha256": _sha(_raw(output / "supervision.json")),
            "supervision_start_sha256": _sha(_raw(output / "supervision-start.json")),
            "supervision_reservation_sha256": _sha(_raw(output / "supervision-reservation.json")),
            "study_run_sha256": result["study_run_sha256"],
            "study_validation": replay, "comparison_eligible": False,
            "promotion_authorized": False, "trading_claim_authorized": False}


def publish_admission(path: Path) -> Path:
    receipt = validate_completed(path)
    output = Path(load_window(path)[0]["output_dir"])
    destination = output / "admission.json"
    _new(destination, receipt)
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--worker", action="store_true")
    mode.add_argument("--validate", action="store_true")
    parser.add_argument("--window", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.validate:
        print(publish_admission(args.window))
        return 0
    _must(not os.environ.get("MOCK_LLM"), "payoff worker refuses mocked model route")
    previous = q._signal_guard()
    try:
        if args.run:
            return supervise(args.window)
        result = worker(args.window)
        return 0 if result["status"] == "observed_restored" else 1
    finally:
        q._restore_signals(previous)


if __name__ == "__main__":
    raise SystemExit(main())
