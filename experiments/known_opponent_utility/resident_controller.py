"""Supervise one registered resident Gemma utility-response pilot.

This study has its own receipts and never claims benchmark or trading authority.
The worker owns the canonical lease, continuous incumbent monitor, temporary
Nara quiescence, and exact watchdog/Nara restoration. The parent recovers a
crashed worker from the durable state without recreating resident containers.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

from bench.flash_next_ab import harness
from bench.flash_next_ab import qualification as q
from bench.flash_next_ab import resident_admission as resident_gate
from bench.flash_next_ab import resident_evaluation_window as resident
from bench.flash_next_ab.transport import LocalEndpoint
from experiments.known_opponent_utility import admission, pilot
from orchestrator.weekly_upgrade_trial import (
    canonical_root,
    resource_lease,
    resource_probe,
)

CODE_ROOT = Path(__file__).resolve().parents[2]
CANONICAL_ROOT = Path("/home/decross1/projects/a_bgt_rsi")
ARTIFACT_ROOT = Path("/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-15/lab-eight-hour")
OUTPUT_ROOT = ARTIFACT_ROOT / "known-opponent-utility"
RESEARCH_ROOT = Path("/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-14/qwen-flash-next-research")
RESIDENT_RECEIPT = RESEARCH_ROOT / "runtime/resident-qualification-v2.json"
RESIDENT_INVENTORY = RESEARCH_ROOT / "runtime/resident-model-artifacts.json"
SCHEMA = "known-opponent-resident-study-window/v1"
RESULT_SCHEMA = "known-opponent-resident-study-result/v1"
SUPERVISION_SCHEMA = "known-opponent-resident-study-supervision/v1"
WALL_S = 1500
PILOT_S = 900
RESTORE_S = 300
POLICY = {"temperature": 0.0, "top_p": 1.0, "top_k": 64, "enable_thinking": False}
SOURCE_FILES = (
    "experiments/known_opponent_utility/resident_controller.py",
    "experiments/known_opponent_utility/pilot.py",
    "experiments/known_opponent_utility/admission.py",
    "experiments/known_opponent_utility/manifest.schema.json",
    "experiments/PREREG_known_opponent_utility_response_2026-09-15.md",
    "bench/agentic_game_theory/optimal_control.py",
    "bench/agentic_game_theory/calibration.py",
    "bench/flash_next_ab/transport.py",
    "bench/flash_next_ab/harness.py",
    "bench/flash_next_ab/qualification.py",
    "bench/flash_next_ab/resident_evaluation_window.py",
    "bench/flash_next_ab/resident_admission.py",
    "orchestrator/weekly_upgrade_trial.py",
)


def _must(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def _raw(path: Path, limit: int = 2_000_000) -> bytes:
    _must(path.is_file() and not path.is_symlink() and path.resolve() == path
          and path.stat().st_size <= limit, "study input is missing, redirected, or oversized")
    return path.read_bytes()


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json(value: dict) -> bytes:
    return pilot._raw_json(value) + b"\n"


def _new(path: Path, value: dict) -> None:
    with path.open("xb") as stream:
        stream.write(_json(value))
        stream.flush()
        os.fsync(stream.fileno())


def _sources() -> dict:
    return {name: {"path": str(CODE_ROOT / name), "sha256": _sha(_raw(CODE_ROOT / name))}
            for name in SOURCE_FILES}


def _identity(pid: int) -> dict:
    return {"pid": pid, "start_ticks": q._process_start_ticks(pid),
            "boot_id": _raw(Path("/proc/sys/kernel/random/boot_id"), 128).decode().strip()}


def _qualification() -> dict:
    return harness.validate_resident_qualification_files(
        RESIDENT_RECEIPT, RESIDENT_INVENTORY, require_passed=True)


def _endpoint(summary: dict) -> LocalEndpoint:
    endpoint = LocalEndpoint("resident_gemma", "http://127.0.0.1:8000",
                             "gemma-4-26b-a4b", summary["artifact_sha256_by_endpoint"]["resident_gemma"])
    endpoint.validate()
    return endpoint


def prepare(*, window_id: str, seed: int, per_call_timeout_s: float = 30.0,
            max_tokens: int = 64) -> Path:
    """Freeze the exact resident identity, request policy, study, and controller."""
    _must(CODE_ROOT == CANONICAL_ROOT and Path(pilot.__file__).resolve().is_relative_to(CODE_ROOT),
          "study must prepare from the integrated canonical checkout")
    _must(re.fullmatch(r"qfn-followon-known-opponent-[a-z0-9][a-z0-9._-]{0,47}", window_id) is not None,
          "unregistered study window ID")
    summary = _qualification()
    endpoint = _endpoint(summary)
    manifest = pilot.freeze_manifest(
        source_root=CODE_ROOT, endpoint=endpoint, registered_admission=summary,
        policy=POLICY, seed=seed, max_tokens=max_tokens,
        per_call_timeout_s=per_call_timeout_s)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    _must(OUTPUT_ROOT.resolve() == OUTPUT_ROOT, "study output root is redirected")
    output = OUTPUT_ROOT / window_id
    output.mkdir(mode=0o700)
    _new(output / "manifest.snapshot.json", manifest)
    document = {
        "schema": SCHEMA, "window_id": window_id, "created_at": q.utc_now(),
        "code_root": str(CODE_ROOT), "output_dir": str(output),
        "manifest": {"path": str(output / "manifest.snapshot.json"),
                     "sha256": _sha(_raw(output / "manifest.snapshot.json"))},
        "qualification": {"receipt_path": str(RESIDENT_RECEIPT),
                          "receipt_sha256": _sha(_raw(RESIDENT_RECEIPT)),
                          "inventory_path": str(RESIDENT_INVENTORY),
                          "inventory_sha256": _sha(_raw(RESIDENT_INVENTORY)),
                          "summary_sha256": _sha(_json(summary))},
        "controller_sources": _sources(), "policy": POLICY,
        "endpoint": endpoint.__dict__, "wall_s": WALL_S,
        "pilot_s": PILOT_S, "restoration_reserve_s": RESTORE_S,
        "minimum_mem_available_gib": 20,
        "comparison_eligible": False, "promotion_authorized": False,
        "trading_claim_authorized": False,
    }
    _new(output / "window.json", document)
    return output / "window.json"


def load_window(path: Path) -> tuple[dict, dict]:
    """Reconstruct all frozen bytes without an endpoint or service call."""
    _must(CODE_ROOT == CANONICAL_ROOT and Path(pilot.__file__).resolve().is_relative_to(CODE_ROOT),
          "study controller is outside the integrated canonical checkout")
    path = path.absolute()
    document = json.loads(_raw(path))
    _must(set(document) == {"schema", "window_id", "created_at", "code_root", "output_dir",
                            "manifest", "qualification", "controller_sources", "policy", "endpoint",
                            "wall_s", "pilot_s", "restoration_reserve_s", "minimum_mem_available_gib",
                            "comparison_eligible", "promotion_authorized", "trading_claim_authorized"}
          and document["schema"] == SCHEMA, "study window schema differs")
    output = OUTPUT_ROOT / document["window_id"]
    _must(re.fullmatch(r"qfn-followon-known-opponent-[a-z0-9][a-z0-9._-]{0,47}",
                       document["window_id"]) is not None
          and path == output / "window.json" and output.resolve() == output
          and document["output_dir"] == str(output), "study output identity differs")
    _must(document["code_root"] == str(CODE_ROOT)
          and document["controller_sources"] == _sources()
          and document["wall_s"] == WALL_S and document["pilot_s"] == PILOT_S
          and document["restoration_reserve_s"] == RESTORE_S
          and document["minimum_mem_available_gib"] == 20
          and document["comparison_eligible"] is False
          and document["promotion_authorized"] is False
          and document["trading_claim_authorized"] is False, "study source or authority differs")
    manifest_path = output / "manifest.snapshot.json"
    _must(document["manifest"] == {"path": str(manifest_path), "sha256": _sha(_raw(manifest_path))},
          "study manifest path or bytes differ")
    manifest = json.loads(_raw(manifest_path))
    pilot._check_manifest(manifest)
    summary = _qualification()
    _must(document["qualification"] == {
        "receipt_path": str(RESIDENT_RECEIPT), "receipt_sha256": _sha(_raw(RESIDENT_RECEIPT)),
        "inventory_path": str(RESIDENT_INVENTORY), "inventory_sha256": _sha(_raw(RESIDENT_INVENTORY)),
        "summary_sha256": _sha(_json(summary))}
          and manifest["registered_admission"] == summary
          and document["endpoint"] == _endpoint(summary).__dict__
          and manifest["endpoint"] == document["endpoint"]
          and document["policy"] == POLICY and manifest["policy"] == POLICY,
          "resident qualification, model, or policy drifted")
    return document, manifest


def _restore(ops, state: dict, document: dict, output: Path, *, deadline: float, monitor=None) -> dict:
    """Bind only our exact stopped sentinel across create-to-ID crash recovery."""
    if (isinstance(state.get("initial"), dict) and state.get("watchdog_sentinel_id") is None
            and state.get("sentinel_absent_before_create") is True):
        try:
            row = resident._inspect_container(ops, resident._sentinel_name(document["window_id"]))
            if row is not None:
                resident._verify_sentinel(ops, document["window_id"], row["id"])
                state["watchdog_sentinel_id"] = row["id"]
                q._atomic_write(output / "state.json", state)
        except Exception as exc:  # noqa: BLE001 - unknown sentinel must stay visible
            state["sentinel_recovery_error"] = f"{type(exc).__name__}: {exc}"
    return resident.restore_resident_window(
        ops, state, {"pair_id": document["window_id"]}, deadline=deadline, monitor=monitor)


def worker(path: Path, *, ops=None, run_fn=pilot.run_pilot) -> dict:
    document, manifest = load_window(path)
    output = Path(document["output_dir"])
    ops = ops or q.HostOps()
    deadline = time.monotonic() + WALL_S
    cutoff = deadline - RESTORE_S
    state = {"schema": "known-opponent-resident-study-state/v1", "phase": "preflight",
             "window_sha256": _sha(_raw(path)), "started_at": q.utc_now(),
             "initial": None, "watchdog_sentinel_id": None,
             "sentinel_absent_before_create": False, "nara_stop_attempted": False,
             "worker": _identity(os.getpid())}
    q._atomic_write(output / "state.json", state)
    run, error, monitor = None, None, None
    with resource_lease(canonical_root(CODE_ROOT)):
        try:
            resource_probe(canonical_root(CODE_ROOT), idle=True)
            state["initial"] = resident._read_exact_residents(ops)
            q._atomic_write(output / "state.json", state)
            monitor = resident.ResidentSafetyMonitor(output / "resident-memory.jsonl", ops,
                                                     state["initial"], deadline=deadline)
            with monitor:
                try:
                    _must(resident._inspect_container(ops, resident._sentinel_name(document["window_id"]))
                          is None, "pre-existing study watchdog")
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
                        _must(time.monotonic() < cutoff, "pilot cutoff reached before admission")
                        live = resident._read_exact_residents(ops, state["initial"], nara_transition=True)
                        _must(live["nara"]["ActiveState"] == "inactive"
                              and state["watchdog_sentinel_id"] == sid,
                              "resident isolation differs before model admission")
                        summary = _qualification()
                        _must(summary == manifest["registered_admission"],
                              "registered resident admission changed before calls")
                        q._atomic_write(output / "admission-ready-proof.json", live)
                        return summary

                    state["phase"] = "pilot"
                    q._atomic_write(output / "state.json", state)
                    run = run_fn(manifest, output=output / "pilot", admission_gate=admit,
                                 safety_check=lambda: (monitor.check(),
                                                       _must(time.monotonic() < cutoff,
                                                             "pilot work cutoff reached")),
                                 cancel_event=monitor.cancel_event)
                    monitor.check()
                except BaseException as exc:  # noqa: BLE001 - signals must restore Nara/sentinel
                    error = f"{type(exc).__name__}: {exc}"
                finally:
                    state["phase"] = "restoration"
                    q._atomic_write(output / "state.json", state)
                    try:
                        monitor.transition("restoration")
                    finally:
                        state["restoration"] = _restore(
                            ops, state, document, output, deadline=deadline,
                            monitor=monitor if monitor.phase == "restoration" else None)
                        q._atomic_write(output / "state.json", state)
        except BaseException as exc:  # noqa: BLE001 - premonitor failures still require exact audit
            error = error or f"{type(exc).__name__}: {exc}"
            if state.get("restoration") is None:
                state["restoration"] = _restore(ops, state, document, output, deadline=deadline)
                q._atomic_write(output / "state.json", state)
    observed = run is not None and run.get("status") in {
        "complete", "completed_schedule_with_unknown_actions"}
    restored = state.get("restoration", {}).get("status") == "verified"
    status = "observed_restored" if observed and restored and error is None and not (monitor and monitor.failure) else "incomplete"
    state["phase"] = status
    q._atomic_write(output / "state.json", state)
    result = {"schema": RESULT_SCHEMA, "window_id": document["window_id"],
              "window_sha256": _sha(_raw(path)), "status": status,
              "finished_at": q.utc_now(), "error": error or (monitor.failure if monitor else None),
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
              "pilot_run_sha256": (_sha(_raw(output / "pilot/run.json", 1_000_000))
                                   if (output / "pilot/run.json").is_file() else None),
              "comparison_eligible": False, "promotion_authorized": False,
              "trading_claim_authorized": False}
    _new(output / "result.json", result)
    return result


def supervise(path: Path) -> int:
    document, _ = load_window(path)
    output = Path(document["output_dir"])
    _must(not (output / "supervision-start.json").exists()
          and not (output / "supervision.json").exists(), "study already supervised")
    _new(output / "supervision-reservation.json", {"window_sha256": _sha(_raw(path)),
         "reserved_at": q.utc_now(), "parent": _identity(os.getpid())})
    started = time.monotonic()
    command = [sys.executable, "-m", "experiments.known_opponent_utility.resident_controller",
               "--worker", "--window", str(path)]
    with (output / "controller.log").open("xb") as log:
        child = subprocess.Popen(command, cwd=CODE_ROOT, stdout=log,
                                 stderr=subprocess.STDOUT, start_new_session=True)
        terminated, interrupted = False, None
        try:
            _new(output / "supervision-start.json", {"window_sha256": _sha(_raw(path)),
                 "argv": command, "started_at": q.utc_now(), "worker": _identity(child.pid)})
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
        except BaseException as exc:  # noqa: BLE001 - interrupted parent still recovers
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
        _must(state.get("window_sha256") == _sha(_raw(path)), "study recovery state belongs elsewhere")
        with resource_lease(canonical_root(CODE_ROOT)):
            recovery = _restore(q.HostOps(), state, document, output,
                                deadline=time.monotonic() + RESTORE_S)
    _new(output / "supervision.json", {"schema": SUPERVISION_SCHEMA,
         "window_sha256": _sha(_raw(path)), "returncode": child.returncode,
         "elapsed_s": time.monotonic() - started, "terminated_at_cutoff": terminated,
         "interrupted": interrupted, "emergency_restoration": recovery,
         "finished_at": q.utc_now()})
    return 0 if (child.returncode == 0 and result.get("status") == "observed_restored"
                 and interrupted is None and not terminated) else 1


def validate_completed(path: Path) -> dict:
    """Independent read-only terminal window + pilot replay admission."""
    document, _ = load_window(path)
    output = Path(document["output_dir"])
    result = json.loads(_raw(output / "result.json"))
    state = json.loads(_raw(output / "state.json"))
    supervision = json.loads(_raw(output / "supervision.json"))
    _must(result.get("schema") == RESULT_SCHEMA and result.get("status") == "observed_restored"
          and result.get("window_sha256") == _sha(_raw(path))
          and result.get("restoration", {}).get("status") == "verified"
          and result.get("restoration", {}).get("sentinel_retained") is False
          and result.get("error") is None
          and state.get("restoration") == result["restoration"]
          and state.get("phase") == "observed_restored"
          and supervision.get("schema") == SUPERVISION_SCHEMA
          and supervision.get("window_sha256") == _sha(_raw(path))
          and supervision.get("returncode") == 0
          and supervision.get("terminated_at_cutoff") is False
          and supervision.get("interrupted") is None
          and supervision.get("emergency_restoration") is None,
          "study terminal supervision or restoration is incomplete")
    ready_raw = _raw(output / "admission-ready-proof.json")
    ready = json.loads(ready_raw)
    _must(result.get("admission_ready_proof_sha256") == _sha(ready_raw)
          and state.get("watchdog_sentinel_id") == result.get("watchdog_sentinel_id")
          and ready.get("nara", {}).get("ActiveState") == "inactive"
          and ready.get("residents_by_name") == state.get("initial", {}).get("residents_by_name"),
          "study live resident/Nara admission proof differs")
    resident_gate._memory(
        output,
        {"memory_log_sha256": result.get("memory_log_sha256"),
         "memory_samples": result.get("memory_samples"),
         "watchdog_sentinel_id": result.get("watchdog_sentinel_id"),
         "min_mem_available_gib": result.get("minimum_mem_available_gib")},
        state["initial"], ready, result["restoration"]["final_observation"],
    )
    replay = admission.validate_pilot(output / "pilot")
    _must(result["pilot_run_sha256"] == _sha(_raw(output / "pilot/run.json", 1_000_000))
          and replay["admission_eligible"] is True,
          "study pilot is partial or private replay differed")
    return {"schema": "known-opponent-resident-study-admission/v1",
            "window_id": document["window_id"], "window_sha256": _sha(_raw(path)),
            "result_sha256": _sha(_raw(output / "result.json")),
            "supervision_sha256": _sha(_raw(output / "supervision.json")),
            "pilot_run_sha256": result["pilot_run_sha256"],
            "pilot_validation": replay, "comparison_eligible": False,
            "promotion_authorized": False, "trading_claim_authorized": False}


def publish_admission(path: Path) -> Path:
    """Seal the independent terminal check once, after the supervisor closes."""
    receipt = validate_completed(path)
    output = Path(load_window(path)[0]["output_dir"])
    destination = output / "admission.json"
    _new(destination, receipt)
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--worker", action="store_true")
    mode.add_argument("--validate", action="store_true")
    parser.add_argument("--window", type=Path)
    parser.add_argument("--window-id")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--per-call-timeout-s", type=float, default=30.0)
    parser.add_argument("--max-tokens", type=int, default=64)
    args = parser.parse_args(argv)
    if args.prepare:
        print(prepare(window_id=args.window_id, seed=args.seed,
                      per_call_timeout_s=args.per_call_timeout_s,
                      max_tokens=args.max_tokens))
        return 0
    _must(args.window is not None, "registered study window path is required")
    if args.validate:
        print(publish_admission(args.window))
        return 0
    _must(not os.environ.get("MOCK_LLM"), "study worker refuses mocked model route")
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
