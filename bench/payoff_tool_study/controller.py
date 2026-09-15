"""Source-bound, one-shot resident controller for the payoff-tool diagnostic.

The existing resident lifecycle owns Nara isolation, watchdog sampling, and
exact restoration. This wrapper only registers the new instrument and gives
its evaluator a finite, independently replayed window. It does not change the
older payoff studies or the lab model controller.
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
from datetime import timedelta
from pathlib import Path

from bench.flash_next_ab import harness, resident_admission, transport
from bench.flash_next_ab import lab_window as lifecycle
from bench.flash_next_ab import qualification as q
from bench.flash_next_ab import resident_evaluation_window as resident
from orchestrator.weekly_upgrade_trial import canonical_root, resource_lease

from . import runner

CODE_ROOT = Path(__file__).resolve().parents[2]
REGISTERED_ROOT = Path("/home/decross1/projects/a_bgt_rsi_worktrees/lab-payoff-tool-20260915")
ARTIFACT_ROOT = Path("/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-15/lab-eight-hour")
OUTPUT_ROOT = ARTIFACT_ROOT / "payoff-tool-study"
RESEARCH_ROOT = Path("/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-14/qwen-flash-next-research")
RESIDENT_RECEIPT = RESEARCH_ROOT / "runtime/resident-qualification-v2.json"
RESIDENT_INVENTORY = RESEARCH_ROOT / "runtime/resident-model-artifacts.json"
WINDOW_SCHEMA = "payoff-tool-study-window/v1"
SUPERVISION_SCHEMA = "payoff-tool-study-supervision/v1"
WINDOW_ID = re.compile(r"qfn-followon-payoff-tool-[a-z0-9][a-z0-9._-]{0,47}\Z")
WALL_S = 1500
EVALUATOR_S = 600
WORKER_RESTORE_S = lifecycle.RESTORE_S  # 600: never relabel the unchanged worker reserve.
PARENT_SOFT_S = 1470  # The parent leaves almost all of worker's nominal600s restore.
PARENT_EMERGENCY_S = 300
SOURCE_FILES = (
    "bench/payoff_tool_study/controller.py",
    "bench/payoff_tool_study/runner.py",
    "bench/flash_next_ab/adapters.py",
    "bench/flash_next_ab/manifest.py",
    "bench/flash_next_ab/qualification.py",
    "bench/agentic_game_theory/calibration.py",
    "experiments/payoff_tool_arithmetic/PREREGISTRATION.md",
    "bench/flash_next_ab/harness.py",
    "bench/flash_next_ab/transport.py",
    "bench/flash_next_ab/private_evidence.py",
)


class PayoffToolControllerError(ValueError):
    pass


def _must(ok: bool, message: str) -> None:
    if not ok:
        raise PayoffToolControllerError(message)


def _raw(path: Path, limit: int = 8_000_000) -> bytes:
    _must(path.is_file() and not path.is_symlink() and path.resolve() == path
          and path.stat().st_size <= limit, "registered evidence is absent or redirected")
    return path.read_bytes()


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _new(path: Path, row: dict) -> None:
    raw = q.canonical_json(row) + b"\n"
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _sources() -> dict:
    refs = lifecycle._source_bundle()
    for name in SOURCE_FILES:
        path = CODE_ROOT / name
        refs[name] = {"path": str(path), "sha256": _sha(_raw(path))}
    return dict(sorted(refs.items()))


def _resident_certificate() -> dict:
    resident_gate = harness.validate_resident_qualification_files(
        RESIDENT_RECEIPT, RESIDENT_INVENTORY, require_passed=True,
    )
    gemma = {
        "endpoint_name": "resident_gemma",
        "served_model": "gemma-4-26b-a4b",
        "artifact_sha256": resident_gate["artifact_sha256_by_endpoint"]["resident_gemma"],
        "runtime_sha256": resident_gate["runtime_sha256_by_endpoint"]["resident_gemma"],
        "max_model_len": 32768,
    }
    _must(gemma["artifact_sha256"] == "c63860e164ed838e0b829de106bfe5ed5f8cd82a7db391c752954c69862ee0af",
          "resident Gemma artifact is not the admitted model")
    return {
        "schema": "payoff-tool-resident-runtime-certificate/v1",
        **gemma,
        "qualification_receipt": {"path": str(RESIDENT_RECEIPT),
                                  "sha256": resident_gate["qualification_receipt_sha256"]},
        "artifact_inventory": {"path": str(RESIDENT_INVENTORY),
                               "sha256": resident_gate["artifact_inventory_sha256"]},
        "probe_scope": resident_gate["probe_scope"],
    }


def _plan_at(output: Path) -> Path:
    return output / "plan.json"


def prepare(window_id: str) -> Path:
    """Freeze plan, exact sources, and the one-shot window before any model call."""
    _must(CODE_ROOT == REGISTERED_ROOT and WINDOW_ID.fullmatch(window_id) is not None,
          "payoff-tool code root or window ID is unregistered")
    _must(WORKER_RESTORE_S == 600 and EVALUATOR_S == 600
          and PARENT_SOFT_S == 1470 and WALL_S == 1500 and PARENT_EMERGENCY_S == 300,
          "finite worker or recovery budget changed")
    certificate = _resident_certificate()
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    _must(OUTPUT_ROOT.resolve() == OUTPUT_ROOT, "payoff-tool output root redirected")
    output = OUTPUT_ROOT / window_id
    output.mkdir(mode=0o700)
    plan_path = _plan_at(output)
    runner.make_plan(certificate, plan_path)
    plan, _raw_sha = runner.load_plan(plan_path)
    _must(plan["runtime_certificate"] == certificate,
          "payoff-tool plan uses another runtime certificate")
    window = {
        "schema": WINDOW_SCHEMA, "window_id": window_id, "cohort": "resident",
        "created_at": q.utc_now(), "code_root": str(CODE_ROOT), "output_dir": str(output),
        "plan": {"path": str(plan_path), "sha256": _sha(_raw(plan_path))},
        "runtime_certificate": certificate, "controller_sources": _sources(),
        "wall_s": WALL_S, "evaluator_s": EVALUATOR_S,
        "worker_restoration_reserve_s": WORKER_RESTORE_S,
        "parent_soft_signal_s": PARENT_SOFT_S,
        "parent_emergency_restoration_s": PARENT_EMERGENCY_S,
        "comparison_eligible": False, "promotion_authorized": False,
        "trading_claim_authorized": False,
    }
    _new(output / "window.json", window)
    return output / "window.json"


def load_window(path: Path) -> tuple[dict, dict]:
    """Reconstruct all source and certificate bytes before resident mutation."""
    _must(CODE_ROOT == REGISTERED_ROOT, "controller is outside registered worktree")
    path = path.absolute()
    window = json.loads(_raw(path))
    _must(set(window) == {
        "schema", "window_id", "cohort", "created_at", "code_root", "output_dir",
        "plan", "runtime_certificate", "controller_sources", "wall_s", "evaluator_s",
        "worker_restoration_reserve_s", "parent_soft_signal_s",
        "parent_emergency_restoration_s", "comparison_eligible",
        "promotion_authorized", "trading_claim_authorized",
    } and window.get("schema") == WINDOW_SCHEMA
          and WINDOW_ID.fullmatch(window.get("window_id", "")) is not None,
          "unregistered payoff-tool window fields or ID")
    output = OUTPUT_ROOT / window["window_id"]
    _must(path == output / "window.json" and output.resolve() == output
          and window["output_dir"] == str(output) and window["code_root"] == str(CODE_ROOT)
          and window["cohort"] == "resident" and window["controller_sources"] == _sources()
          and window["wall_s"] == WALL_S and window["evaluator_s"] == EVALUATOR_S
          and window["worker_restoration_reserve_s"] == WORKER_RESTORE_S
          and window["parent_soft_signal_s"] == PARENT_SOFT_S
          and window["parent_emergency_restoration_s"] == PARENT_EMERGENCY_S
          and window["comparison_eligible"] is False
          and window["promotion_authorized"] is False
          and window["trading_claim_authorized"] is False,
          "source, budget, cohort or authority drifted")
    certificate = _resident_certificate()
    _must(window["runtime_certificate"] == certificate,
          "resident qualification, model or inventory changed")
    plan_path = _plan_at(output)
    _must(window["plan"] == {"path": str(plan_path), "sha256": _sha(_raw(plan_path))},
          "payoff-tool plan raw bytes or path changed")
    plan, _raw_sha = runner.load_plan(plan_path)
    _must(plan["runtime_certificate"] == certificate,
          "payoff-tool plan certificate differs from registered resident")
    return window, plan


class _CutoffCancel:
    def __init__(self, original, cutoff: float):
        self.original, self.cutoff = original, cutoff

    def is_set(self) -> bool:
        return self.original.is_set() or time.monotonic() >= self.cutoff


def _executor(window: dict, _parent, output: Path, monitor, state: dict,
              cutoff: float) -> dict:
    plan_path = _plan_at(output)
    _plan, _raw_sha = runner.load_plan(plan_path)
    _must(cutoff - time.monotonic() >= EVALUATOR_S,
          "resident setup did not leave the predeclared evaluator budget")
    monitor.check()
    _must(monitor.phase == "evaluation" and state.get("initial") is not None,
          "resident isolation is not armed")
    observed = resident._read_exact_residents(
        monitor.ops, state["initial"], nara_transition=True,
    )
    _must(observed["nara"]["ActiveState"] == "inactive"
          and observed["residents_by_name"] == state["initial"]["residents_by_name"],
          "Nara or resident identity differs at evaluator admission")
    state["phase"] = "evaluation"
    q._atomic_write(output / "state.json", state)
    arm = {
        "schema": "payoff-tool-resident-monitor-arm/v1",
        "window_sha256": _sha(_raw(output / "window.json")),
        "worker_pid": state["worker_pid"],
        "worker_start_ticks": state["worker_start_ticks"],
        "boot_id": state["boot_id"],
        "monitor_phase": monitor.phase, "samples_at_arm": monitor.samples,
        "watchdog_sentinel_id": state["watchdog_sentinel_id"],
        "observed_at": q.utc_now(),
    }
    _new(output / "monitor-arm.json", arm)
    ready = {
        "schema": "payoff-tool-resident-ready-proof/v1",
        "window_sha256": arm["window_sha256"],
        "plan_sha256": _sha(_raw(plan_path)),
        "runtime_certificate": window["runtime_certificate"],
        "resident_observation": observed,
        "monitor_arm_sha256": _sha(_raw(output / "monitor-arm.json")),
        "observed_at": q.utc_now(),
    }
    _new(output / "ready-proof.json", ready)
    gate = {
        "admitted": True,
        "runtime_certificate": window["runtime_certificate"],
        "window_id": window["window_id"],
        "window_sha256": arm["window_sha256"],
        "ready_proof_sha256": _sha(_raw(output / "ready-proof.json")),
        "monitor_arm_sha256": ready["monitor_arm_sha256"],
    }
    run_deadline = min(cutoff, time.monotonic() + EVALUATOR_S)
    cancel = _CutoffCancel(monitor.cancel_event, run_deadline)

    def invoke(*args, **kwargs):
        monitor.check()
        _must(not cancel.is_set(), "resident payoff-tool work cutoff reached")
        current = resident._read_exact_residents(
            monitor.ops, state["initial"], nara_transition=True,
        )
        _must(current["nara"]["ActiveState"] == "inactive",
              "Nara became active before a tool-study request")
        response = transport.complete(*args, **kwargs)
        monitor.check()
        return response

    run = runner.run(
        plan_path=plan_path, output_dir=output / "evaluation", admission_gate=gate,
        cancel_event=cancel, absolute_cutoff_monotonic=run_deadline, invoke_fn=invoke,
    )
    monitor.check()
    return {"status": "complete" if run.get("status") == "complete" else "aborted",
            "accounted_slots": run.get("accounted_slots")}


def worker(path: Path) -> dict:
    window, _plan = load_window(path)
    return lifecycle._resident(window, None, Path(window["output_dir"]),
                               time.monotonic() + WALL_S, executor=_executor)


def _identity(pid: int) -> dict:
    return lifecycle._process_identity(pid)


def supervise(path: Path) -> int:
    window, _plan = load_window(path)
    output = Path(window["output_dir"])
    _must(not (output / "supervision.json").exists()
          and not (output / "supervision-start.json").exists()
          and not (output / "supervision-reservation.json").exists(),
          "one-shot payoff-tool window was already supervised")
    window_sha = _sha(_raw(path))
    _new(output / "supervision-reservation.json", {
        "reserved_at": q.utc_now(), "window_sha256": window_sha,
        **_identity(os.getpid()),
    })
    command = [sys.executable, "-m", "bench.payoff_tool_study.controller",
               "--worker", "--window", str(path)]
    started = time.monotonic()
    with (output / "controller.log").open("xb") as log:
        child = subprocess.Popen(command, cwd=CODE_ROOT, stdout=log,
                                 stderr=subprocess.STDOUT, start_new_session=True)
        terminated, interrupted = False, None
        try:
            _new(output / "supervision-start.json", {
                "pid": child.pid, "started_at": q.utc_now(), "argv": command,
                "window_sha256": window_sha, **_identity(child.pid),
            })
            while child.poll() is None:
                elapsed = time.monotonic() - started
                if elapsed >= PARENT_SOFT_S and not terminated:
                    child.send_signal(signal.SIGTERM)
                    terminated = True
                if elapsed >= WALL_S:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait(timeout=30)
                    break
                time.sleep(1)
        except BaseException as exc:  # noqa: BLE001 - parent must still attempt exact recovery
            interrupted = type(exc).__name__
            if child.poll() is None:
                child.send_signal(signal.SIGTERM)
                terminated = True
                try:
                    child.wait(timeout=PARENT_EMERGENCY_S)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait(timeout=30)
    try:
        result = json.loads(_raw(output / "result.json"))
        state = json.loads(_raw(output / "state.json"))
    except (PayoffToolControllerError, ValueError, UnicodeError):
        result, state = {}, {}
    restored = (result.get("restoration", {}).get("status") == "verified"
                and state.get("restoration") == result.get("restoration")
                and state.get("phase") in {"complete", "aborted"})
    emergency = None
    if not restored:
        if state.get("window_sha256") != window_sha:
            emergency = {"status": "unknown", "failure_code": "recovery_state_unavailable_or_drifted"}
        else:
            try:
                with resource_lease(canonical_root(CODE_ROOT)):
                    emergency = lifecycle._restore_resident(
                        q.HostOps(), state, window, output,
                        deadline=time.monotonic() + PARENT_EMERGENCY_S,
                    )
            except BaseException as exc:  # noqa: BLE001 - exact recovery uncertainty is visible
                emergency = {"status": "unknown", "failure_code": "emergency_restoration_failed",
                             "error_type": type(exc).__name__}
    _new(output / "supervision.json", {
        "schema": SUPERVISION_SCHEMA, "window_sha256": window_sha,
        "returncode": child.returncode, "elapsed_s": time.monotonic() - started,
        "terminated_at_cutoff": terminated, "interrupted": interrupted,
        "emergency_restoration": emergency, "finished_at": q.utc_now(),
    })
    return 0 if (child.returncode == 0 and result.get("status") == "complete"
                 and interrupted is None and not terminated and emergency is None) else 1


def validate_completed(path: Path) -> dict:
    """Read-only terminal gate; no score is admitted without raw grade replay."""
    window, _plan = load_window(path)
    output = Path(window["output_dir"])
    raw = {name: _raw(output / name) for name in (
        "state.json", "result.json", "supervision.json",
        "supervision-start.json", "supervision-reservation.json",
        "ready-proof.json", "monitor-arm.json", "memory.jsonl",
    )}
    state, result, supervision = (json.loads(raw[name]) for name in
                                  ("state.json", "result.json", "supervision.json"))
    start = json.loads(raw["supervision-start.json"])
    reservation = json.loads(raw["supervision-reservation.json"])
    ready = json.loads(raw["ready-proof.json"])
    arm = json.loads(raw["monitor-arm.json"])
    window_sha = _sha(_raw(path))
    restore = result.get("restoration", {})
    _must(result.get("schema") == "lab-model-window-result/v1"
          and result.get("window_id") == window["window_id"]
          and result.get("window_sha256") == window_sha
          and result.get("cohort") == "resident"
          and result.get("status") == "complete" and result.get("error") is None
          and restore.get("status") == "verified" and restore.get("errors") == []
          and restore.get("sentinel_retained") is False
          and restore.get("final_observation", {}).get("watchdog_sentinel_by_name") is None
          and restore.get("final_observation", {}).get("watchdog_sentinel_by_id") is None
          and state.get("phase") == "complete" and state.get("window_sha256") == window_sha
          and state.get("restoration") == restore
          and state.get("sentinel_absent_before_create") is True
          and isinstance(state.get("watchdog_sentinel_id"), str)
          and bool(state["watchdog_sentinel_id"])
          and supervision.get("schema") == SUPERVISION_SCHEMA
          and supervision.get("window_sha256") == window_sha
          and supervision.get("returncode") == 0 and supervision.get("interrupted") is None
          and supervision.get("terminated_at_cutoff") is False
          and supervision.get("emergency_restoration") is None,
          "payoff-tool window lacks clean terminal resident restoration")
    _must(reservation.get("window_sha256") == window_sha
          and start.get("window_sha256") == window_sha
          and start.get("pid") == start.get("worker_pid") == state.get("worker_pid")
          and start.get("worker_start_ticks") == state.get("worker_start_ticks")
          and start.get("boot_id") == state.get("boot_id")
          and start.get("argv") == [sys.executable, "-m", "bench.payoff_tool_study.controller",
                                    "--worker", "--window", str(path)],
          "payoff-tool worker identity or command differs")
    _must(ready.get("window_sha256") == window_sha
          and ready.get("plan_sha256") == _sha(_raw(_plan_at(output)))
          and ready.get("runtime_certificate") == window["runtime_certificate"]
          and ready.get("monitor_arm_sha256") == _sha(raw["monitor-arm.json"])
          and arm.get("window_sha256") == window_sha
          and arm.get("monitor_phase") == "evaluation"
          and arm.get("watchdog_sentinel_id") == state.get("watchdog_sentinel_id")
          and arm.get("worker_pid") == state.get("worker_pid")
          and arm.get("worker_start_ticks") == state.get("worker_start_ticks")
          and arm.get("boot_id") == state.get("boot_id"),
          "payoff-tool ready/monitor arm source differs")
    initial = state.get("initial")
    quiet = ready.get("resident_observation")
    final = restore.get("final_observation")
    resident_admission._identity(initial, quiet, final)
    rows = [json.loads(line) for line in raw["memory.jsonl"].splitlines()]
    _must(rows and len(rows) == result.get("memory_samples") and len(rows) <= 6000,
          "resident monitor raw sample count differs")
    values = [row.get("mem_available_gib") for row in rows]
    _must(all(type(value) in {int, float} and math.isfinite(value) and value >= 20
              for value in values)
          and min(values) == result.get("minimum_mem_available_gib")
          and any(row.get("monitor_phase") == "evaluation" for row in rows),
          "resident memory/evaluation proof is absent or drifted")
    expected_phases = ("setup", "quiescing", "evaluation", "restoration")
    phases: list[str] = []
    prior_mono, prior_pages = None, None
    initial_at = harness._utc_datetime(initial.get("observed_at"), "initial resident observation")
    final_at = harness._utc_datetime(final.get("observed_at"), "restored resident observation")
    prior_at = initial_at
    sentinel = state.get("watchdog_sentinel_id")
    for row in rows:
        phase = row.get("monitor_phase")
        seconds, pages = row.get("observed_monotonic"), row.get("host_pswpout_pages")
        observed_at = harness._utc_datetime(row.get("observed_at"), "resident safety sample")
        _must(row.get("schema") == "flash-next-resident-research-memory-sample/v1"
              and phase in expected_phases
              and (not phases or phase == phases[-1]
                   or expected_phases.index(phase) == expected_phases.index(phases[-1]) + 1)
              and type(seconds) in {int, float} and math.isfinite(seconds)
              and (prior_mono is None or 0 < seconds - prior_mono <= 10)
              and type(pages) is int and pages >= 0
              and (prior_pages is None or pages >= prior_pages)
              and prior_at <= observed_at <= final_at
              and row.get("watchdog_sentinel_id") in {None, sentinel}
              and (phase == "setup" or row.get("watchdog_sentinel_id") == sentinel)
              and row.get("cgroup_swap_capture_status") == "exact_incumbent_pid_cgroup_bound"
              and row.get("incumbent_ids") == [item["id"] for item in initial["residents"]]
              and row.get("incumbent_containers") == initial["residents"]
              and row.get("incumbent_restart_counts")
                  == {item["name"]: item["restart_count"] for item in initial["residents"]}
              and row.get("incumbent_pids")
                  == {item["name"]: item["pid"] for item in initial["residents"]}
              and isinstance(row.get("incumbent_cgroups"), dict)
              and set(row["incumbent_cgroups"]) == set(initial["cgroups_by_name"])
              and row.get("incumbent_cgroup_swap_bytes")
                  == {name: value.get("memory_swap_current_bytes")
                      for name, value in row["incumbent_cgroups"].items()},
              "resident raw safety cadence, host paging, sentinel, or identity drifted")
        for registered in q.RESIDENTS:
            name = registered["name"]
            snapshot = row["incumbent_cgroups"][name]
            baseline = initial["cgroups_by_name"][name]
            resident_admission._cgroup(snapshot, registered["id"])
            _must(all(snapshot[key] == baseline[key] for key in (
                "path", "process_start_ticks", "memory_max_bytes",
                "memory_swap_max_bytes", "memory_events_oom", "memory_events_oom_kill",
            )), "resident cgroup limit, PID, or OOM counter changed")
        if phase == "evaluation":
            _must(row.get("nara") == quiet["nara"],
                  "Nara was not quiescent during a tool-study safety sample")
        if phase == "setup":
            _must(row.get("nara") == initial["nara"],
                  "setup safety sample differs from the captured Nara state")
        phases.append(phase)
        prior_mono, prior_pages = seconds, pages
        prior_at = observed_at
    _must(phases[0] == "setup" and phases[-1] == "restoration"
          and all(phase in phases for phase in expected_phases)
          and rows[-1].get("nara", {}).get("ActiveState") == initial["nara"]["ActiveState"]
          and harness._utc_datetime(rows[0].get("observed_at"), "first safety sample")
              <= initial_at + timedelta(seconds=10)
          and final_at <= prior_at + timedelta(seconds=10),
          "resident quiescence/evaluation/restoration chronology incomplete")
    run_raw = _raw(output / "evaluation/run.json")
    _must(result.get("evaluation_run_sha256") == _sha(run_raw),
          "payoff-tool terminal run source differs")
    run_record = json.loads(run_raw)
    _must(run_record.get("controller_admission") == {
        "admitted": True, "runtime_certificate": window["runtime_certificate"],
        "window_id": window["window_id"], "window_sha256": window_sha,
        "ready_proof_sha256": _sha(raw["ready-proof.json"]),
        "monitor_arm_sha256": _sha(raw["monitor-arm.json"]),
    }, "run's ready/monitor admission differs from exact resident window")
    replay = runner.replay_run(_plan_at(output), output / "evaluation")
    _must(replay.get("admitted") is True and replay.get("status") == "passed"
          and replay.get("raw_sse_replay_passed") is True
          and replay.get("grade_replay_passed") is True
          and replay.get("run_raw_sha256") == result["evaluation_run_sha256"]
          and replay.get("declared_pairs") == 6
          and replay.get("declared_conditions") == 12
          and replay.get("declared_slots") == 18
          and type(replay.get("issued_calls")) is int
          and 0 <= replay["issued_calls"] <= 18,
          "payoff-tool raw SSE and grade replay unavailable")
    return {
        "schema": "payoff-tool-study-completed-admission/v1",
        "window_id": window["window_id"], "window_sha256": window_sha,
        "raw_refs": {name: _sha(value) for name, value in raw.items()},
        "plan_sha256": _sha(_raw(_plan_at(output))),
        "pilot_run_sha256": result["evaluation_run_sha256"],
        "replay": replay, "admitted": True,
        "comparison_eligible": False, "promotion_authorized": False,
        "trading_claim_authorized": False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--worker", action="store_true")
    mode.add_argument("--validate", action="store_true")
    parser.add_argument("--window-id")
    parser.add_argument("--window", type=Path)
    args = parser.parse_args(argv)
    if args.prepare:
        print(prepare(args.window_id))
        return 0
    if args.validate:
        print(json.dumps(validate_completed(args.window), sort_keys=True))
        return 0
    _must(not os.environ.get("MOCK_LLM"), "live payoff-tool window refuses mock transport")
    if args.worker:
        return 0 if worker(args.window).get("status") == "complete" else 1
    return supervise(args.window)


if __name__ == "__main__":
    raise SystemExit(main())
