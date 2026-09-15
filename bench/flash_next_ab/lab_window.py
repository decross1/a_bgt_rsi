"""Source-bound lab evaluations using existing qualified lifecycle primitives.

The historical runtime certificate and this evaluator/controller have separate
identities. No old source, qualification, score, or launch contract is rewritten.
Only the already qualified reduced-MTP3 profile and exact resident containers
are supported. The parent supervisor reserves ten minutes for restoration.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

from orchestrator.weekly_upgrade_trial import (
    canonical_root,
    resource_lease,
    resource_probe,
)

from . import qualification as q
from . import resident_evaluation_window as resident
from .evaluation_window import EXTENDED_SERVING_PROFILE
from .followon_canaries import run_profile_canary
from .followon_dispatch import FOLLOWON_SOURCE_MODULES
from .followon_v5_parent import load_parent

CODE_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_ROOT = Path("/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-15/lab-eight-hour")
WINDOW_ROOT = ARTIFACT_ROOT / "model-windows"
PARENT_PATH = Path("/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-14/"
                   "qwen-flash-next-research/evaluation/followon-qualified-parents/"
                   "qfn-mia-mtp3-red47k-20260915-a.json")
SCHEMA = "lab-model-window/v1"
RESTORE_S = 600
EVALUATORS = {
    "primary": ("lab_eval_plan", "lab_eval_runner"),
    "context": ("lab_eval_context", "lab_eval_context"),
    "fresh": ("lab_eval_fresh", "lab_eval_fresh"),
    "diversity_cap": ("lab_eval_diversity_cap", "lab_eval_diversity_cap"),
}
MAX_EVALUATOR_BUDGET_S = {"primary": 10_430, "context": 6000, "fresh": 1800,
                          "diversity_cap": 2200}


def _evaluator(kind: str, *, runner: bool = False):
    _must(kind in EVALUATORS, "unregistered evaluator kind")
    module = EVALUATORS[kind][int(runner)]
    return importlib.import_module("bench.flash_next_ab." + module)


def _must(value: bool, message: str) -> None:
    if not value:
        raise ValueError(message)


def _raw(path: Path) -> bytes:
    _must(path.is_file() and not path.is_symlink() and path.resolve() == path,
          "source is missing or redirected")
    _must(path.stat().st_size <= 8 * 1024**2, "source exceeds size limit")
    return path.read_bytes()


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _new(path: Path, value: dict) -> None:
    raw = q.canonical_json(value) + b"\n"
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _process_identity(pid: int) -> dict:
    return {"worker_pid": pid, "worker_start_ticks": q._process_start_ticks(pid),
            "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip()}


def _source_bundle() -> dict:
    names = {"bench/flash_next_ab/" + name for name in FOLLOWON_SOURCE_MODULES}
    names |= {"bench/flash_next_ab/lab_window.py",
              "bench/flash_next_ab/lab_eval_diversity_cap.py",
              "bench/flash_next_ab/lab_eval_plan.py",
              "bench/flash_next_ab/lab_eval_runner.py",
              "bench/flash_next_ab/lab_eval_replay.py",
              "orchestrator/weekly_upgrade_trial.py"}
    return {name: {"path": str(CODE_ROOT / name),
                   "sha256": _sha(_raw(CODE_ROOT / name))}
            for name in sorted(names)}


def prepare(plan_path: Path, *, cohort: str, window_id: str,
            runtime_budget_s: int, wall_s: int, kind: str = "primary") -> Path:
    plan_path = plan_path.absolute()
    _evaluator(kind).load_plan(plan_path)
    if kind == "diversity_cap":
        _must(cohort == "flash" and runtime_budget_s == 2200 and wall_s == 4500,
              "prospective diversity-cap window uses the exact Flash budget")
    _must(plan_path.is_relative_to(ARTIFACT_ROOT), "evaluation plan is outside lab artifacts")
    _must(cohort in {"resident", "flash"}, "unknown cohort")
    _must(re.fullmatch(r"qfn-ab-[a-z0-9][a-z0-9._-]{0,63}", window_id) is not None,
          "invalid window ID")
    _must(type(runtime_budget_s) is int and 60 <= runtime_budget_s <= MAX_EVALUATOR_BUDGET_S[kind],
          "invalid harness budget")
    minimum_setup = 1500 if cohort == "flash" else 60
    _must(runtime_budget_s + RESTORE_S + minimum_setup <= wall_s <= 14_400,
          "window does not reserve setup and restoration")
    parent = load_parent(PARENT_PATH)
    WINDOW_ROOT.mkdir(exist_ok=True)
    _must(WINDOW_ROOT.resolve() == WINDOW_ROOT, "window root is redirected")
    output = WINDOW_ROOT / f"{window_id}.{cohort}"
    output.mkdir(mode=0o700)
    document = {
        "schema": SCHEMA, "window_id": window_id, "cohort": cohort, "evaluation_kind": kind,
        "created_at": q.utc_now(), "output_dir": str(output),
        "evaluation_plan": {"path": str(plan_path), "sha256": _sha(_raw(plan_path))},
        "runtime_certificate": {"path": str(PARENT_PATH), "sha256": parent.source_sha256},
        "candidate_spec_id": parent.spec.spec_id,
        "candidate_spec_sha256": parent.spec.identity_sha256(),
        "controller_sources": _source_bundle(), "code_root": str(CODE_ROOT),
        "runtime_budget_s": runtime_budget_s, "wall_s": wall_s,
        "restoration_reserve_s": RESTORE_S,
        "minimum_mem_available_gib": 20, "promotion_authorized": False,
    }
    _new(output / "window.json", document)
    return output / "window.json"


def load_window(path: Path) -> tuple[dict, object]:
    path = path.absolute()
    document = json.loads(_raw(path))
    _must(set(document) == {"schema", "window_id", "cohort", "created_at", "output_dir",
          "evaluation_plan", "runtime_certificate", "candidate_spec_id", "candidate_spec_sha256",
          "controller_sources", "code_root", "runtime_budget_s", "wall_s",
          "restoration_reserve_s", "minimum_mem_available_gib", "promotion_authorized", "evaluation_kind"},
          "window fields differ")
    _must(document.get("schema") == SCHEMA and document.get("cohort") in {"resident", "flash"},
          "invalid window schema or cohort")
    _must(re.fullmatch(r"qfn-ab-[a-z0-9][a-z0-9._-]{0,63}", document["window_id"]) is not None,
          "invalid persisted window ID")
    output = Path(document["output_dir"])
    _must(output.parent == WINDOW_ROOT and path == output / "window.json"
          and output.name == f"{document['window_id']}.{document['cohort']}"
          and output.resolve() == output, "window identity or output changed")
    _must(document["code_root"] == str(CODE_ROOT)
          and document["controller_sources"] == _source_bundle(), "controller source drift")
    plan_path = Path(document["evaluation_plan"]["path"])
    _must(plan_path.is_relative_to(ARTIFACT_ROOT), "persisted plan is outside lab artifacts")
    _must(_sha(_raw(plan_path)) == document["evaluation_plan"]["sha256"], "evaluation plan drift")
    _evaluator(document["evaluation_kind"]).load_plan(plan_path)
    parent = load_parent(PARENT_PATH)
    _must(document["runtime_certificate"] == {"path": str(PARENT_PATH), "sha256": parent.source_sha256}
          and document["candidate_spec_id"] == parent.spec.spec_id
          and document["candidate_spec_sha256"] == parent.spec.identity_sha256(),
          "qualified runtime identity drift")
    _must(document["restoration_reserve_s"] == RESTORE_S
          and document["minimum_mem_available_gib"] == 20
          and document["promotion_authorized"] is False, "window authority changed")
    if document["evaluation_kind"] == "diversity_cap":
        _must(document["cohort"] == "flash" and document["runtime_budget_s"] == 2200
              and document["wall_s"] == 4500, "diversity-cap window budget changed")
    minimum_setup = 1500 if document["cohort"] == "flash" else 60
    _must(type(document["runtime_budget_s"]) is int
          and 60 <= document["runtime_budget_s"] <= MAX_EVALUATOR_BUDGET_S[document["evaluation_kind"]]
          and type(document["wall_s"]) is int
          and document["runtime_budget_s"] + RESTORE_S + minimum_setup <= document["wall_s"] <= 14_400,
          "window budget or restoration reserve is invalid")
    return document, parent


def _run_evaluator(document: dict, parent, output: Path, monitor, state: dict, cutoff: float):
    budget = min(document["runtime_budget_s"], int(cutoff - time.monotonic()))
    _must(budget >= 60, "no evaluation time remains before restoration")

    def admission(plan, cohort):
        from .manifest import sha256_json

        monitor.check()
        _must(cohort == document["cohort"] and state["phase"] == "evaluation",
              "evaluator escaped its admitted runtime window")
        names = {name for routes in plan["call_routes"][cohort].values() for name in routes}
        if cohort == "flash":
            observed = q._inspect_container(monitor.ops, parent.spec.container_name)
            _must(observed is not None and observed["id"] == state["candidate_id"]
                  and observed["image"] == parent.spec.image_id and observed["running"]
                  and not observed["oom_killed"] and observed["restart_count"] == 0,
                  "candidate identity changed before evaluator admission")
            _must(names == {"flash_next_mia"} and state["canaries"]["status"] == "passed",
                  "candidate routing or canary proof differs")
            proof = {"candidate": observed, "readiness_sha256": _sha(_raw(output / "readiness.json")),
                     "probes_sha256": _sha(_raw(output / "probes.json")), "canaries": state["canaries"]}
        else:
            proof = resident._read_exact_residents(monitor.ops, state["initial"], nara_transition=True)
            _must(names <= {"resident_gemma", "resident_qwen"}
                  and proof["nara"]["ActiveState"] == "inactive", "resident routing or isolation changed")
        q._atomic_write(output / "admission-ready-proof.json", proof)
        certificate = plan["runtime_certificates"][cohort]
        return {"schema_version": "lab-model-eval-admission/v1", "admitted": True,
                "cohort": cohort, "window_id": document["window_id"],
                "plan_sha256": sha256_json(plan),
                "certificate_sha256": (parent.source_sha256 if cohort == "flash"
                                        else certificate["receipt_sha256"]),
                "endpoint_identities": {name: {key: plan["endpoints"][name][key]
                    for key in ("served_model", "artifact_sha256", "runtime_sha256")} for name in names},
                "candidate_spec_sha256": parent.spec.identity_sha256() if cohort == "flash" else None,
                "monitor_armed": True,
                "controller_source_bundle_sha256": q.sha256(document["controller_sources"]),
                "ready_proof_sha256": _sha(_raw(output / "admission-ready-proof.json")),
                "window_sha256": _sha(_raw(output / "window.json")),
                "observed_at": q.utc_now()}

    state["phase"] = "evaluation"
    q._atomic_write(output / "state.json", state)
    result = _evaluator(document["evaluation_kind"], runner=True).run(
                 Path(document["evaluation_plan"]["path"]), cohort=document["cohort"],
                 output_dir=output / "evaluation", runtime_budget_s=budget,
                 admission_gate=admission, cancel_event=monitor.cancel_event)
    monitor.check()
    return result


def _flash(document: dict, parent, output: Path, deadline: float, *, executor=None) -> dict:
    spec, ops = parent.spec, q.HostOps()
    contract = json.loads(_raw(Path(parent.document["source_refs"]["launch-contract.snapshot.json"]["path"])))
    cutoff = deadline - RESTORE_S
    state = {"phase": "preflight", "initial": None, "candidate_id": None,
             "window_sha256": _sha(_raw(output / "window.json")), "started_at": q.utc_now(),
             **_process_identity(os.getpid())}
    q._atomic_write(output / "state.json", state)
    result, error = None, None
    monitor = q.MemoryMonitor(output / "memory.jsonl", ops, minimum_gib=20,
                              candidate_spec=spec, extended_serving_profile=EXTENDED_SERVING_PROFILE)
    with resource_lease(canonical_root(CODE_ROOT)), monitor:
        try:
            preflight = resource_probe(canonical_root(CODE_ROOT), idle=True)
            _must(q._inspect_container(ops, spec.container_name) is None, "candidate already exists")
            q._assert_port_free(spec)
            q._atomic_write(output / "model-verification.json", q.verify_model(contract, monitor, spec=spec))
            image = ops.run(["docker", "image", "inspect", "--format", "{{.Id}} {{.Architecture}}",
                             spec.image_id], timeout=10).stdout.strip().split()
            _must(image == [spec.image_id, "arm64"], "image identity differs")
            _must(q.launch_argv(spec) == parent.qualification_plan["docker_create_argv"],
                  "current launch differs from qualified argv")
            q._ensure_compile_cache(spec)
            monitor.require_setup_quiescence(duration_s=60, deadline=cutoff)
            preflight = resource_probe(canonical_root(CODE_ROOT), idle=True)
            state["initial"] = q._capture_initial_state(ops, preflight)
            state["phase"] = "candidate_create"
            q._atomic_write(output / "state.json", state)
            monitor.begin_mutation_window()
            created = ops.run(q.launch_argv(spec), timeout=30).stdout.strip()
            observed = q._inspect_container(ops, spec.container_name)
            if observed is not None:
                state["candidate_id"] = observed["id"]
                q._atomic_write(output / "state.json", state)
            _must(re.fullmatch(r"[0-9a-f]{64}", created) is not None
                  and observed is not None and observed["id"] == created
                  and observed["image"] == spec.image_id and not observed["running"]
                  and observed["memory_limit_bytes"] == spec.docker_memory_limit_bytes
                  and observed["memory_swap_total_bytes"] == spec.docker_memory_limit_bytes
                  and observed["restart_policy"] in {"", "no"}, "candidate create differs")
            if state["initial"]["nara_was_active"]:
                ops.run(["systemctl", "--user", "stop", q.NARA_SERVICE], timeout=30)
            _must(q._service_state(ops)["ActiveState"] == "inactive", "Nara did not quiesce")
            state["phase"] = "resident_stop"
            q._atomic_write(output / "state.json", state)
            for item in state["initial"]["residents"]:
                ops.run(["docker", "stop", "--time", "30", item["id"]], timeout=45)
                after = q._inspect_container(ops, item["id"])
                _must(after is not None and not after["running"], "resident stop unverified")
            monitor.check()
            state["phase"] = "candidate_start"
            q._atomic_write(output / "state.json", state)
            ops.run(["docker", "start", created], timeout=30)
            monitor.arm(created)
            state.update({
                "candidate_cgroup_path": getattr(monitor, "candidate_cgroup_bound_path", None),
                "candidate_cgroup_pid": getattr(monitor, "candidate_cgroup_bound_pid", None),
                "candidate_cgroup_start_ticks": getattr(monitor, "candidate_cgroup_start_ticks", None),
            })
            q._atomic_write(output / "state.json", state)
            ready = q._wait_candidate_ready(ops, monitor, deadline=min(cutoff, time.monotonic() + 1500), spec=spec)
            monitor.require_ready_quiescence(duration_s=60, deadline=cutoff)
            q._atomic_write(output / "readiness.json", ready)
            state["phase"] = "probes"
            q._atomic_write(output / "state.json", state)
            monitor._sample_once()
            probes = q._run_probes(ops, monitor, timeout_s=contract["safety"]["probe_timeout_seconds"],
                                   output=output, spec=spec)
            q._atomic_write(output / "probes.json", {"results": probes})
            canaries = run_profile_canary(ops, monitor, spec=spec, output=output,
                                         timeout_s=spec.profile_canary_timeout_seconds,
                                         work_deadline=cutoff, atomic_write=q._atomic_write,
                                         record_private=q._probe_private_response,
                                         native_context_packet_factory=None)
            _must(canaries.get("status") == "passed", "profile canaries failed")
            state["canaries"] = canaries
            monitor.begin_evaluation()
            result = (executor or _run_evaluator)(document, parent, output, monitor, state, cutoff)
        except BaseException as exc:  # noqa: BLE001 - signals must enter exact restoration
            error = f"{type(exc).__name__}: {exc}"
        finally:
            state["phase"] = "restoration"
            q._atomic_write(output / "state.json", state)
            try:
                monitor.begin_restoration()
            finally:
                state["restoration"] = q.restore_exact(ops, state, deadline=deadline,
                    monitor=monitor, spec=spec, diagnostic_path=output / "candidate.log")
                q._atomic_write(output / "state.json", state)
    return _finish(document, output, state, result, error, monitor)


def _restore_resident(ops, state: dict, document: dict, output: Path, *, deadline: float,
                      monitor=None) -> dict:
    # Recover the small create→durable-ID gap, but only when this worker proved
    # the fixed name absent before creating it. Never adopt a pre-existing one.
    if (isinstance(state.get("initial"), dict)
            and state.get("watchdog_sentinel_id") is None
            and state.get("sentinel_absent_before_create") is True):
        try:
            observed = resident._inspect_container(ops, resident._sentinel_name(document["window_id"]))
            if observed is not None:
                resident._verify_sentinel(ops, document["window_id"], observed["id"])
                state["watchdog_sentinel_id"] = observed["id"]
                q._atomic_write(output / "state.json", state)
        except Exception as exc:  # noqa: BLE001 - retain unknown sentinel, still try service restore
            state["sentinel_recovery_error"] = f"{type(exc).__name__}: {exc}"
    return resident.restore_resident_window(ops, state, {"pair_id": document["window_id"]},
                                             deadline=deadline, monitor=monitor)


def _resident(document: dict, parent, output: Path, deadline: float, *, executor=None) -> dict:
    ops, result, error = q.HostOps(), None, None
    cutoff = deadline - RESTORE_S
    state = {"phase": "preflight", "initial": None, "watchdog_sentinel_id": None,
             "sentinel_absent_before_create": False,
             "nara_stop_attempted": False, "started_at": q.utc_now(),
             "window_sha256": _sha(_raw(output / "window.json")), **_process_identity(os.getpid())}
    q._atomic_write(output / "state.json", state)
    with resource_lease(canonical_root(CODE_ROOT)):
        resource_probe(canonical_root(CODE_ROOT), idle=True)
        state["initial"] = resident._read_exact_residents(ops)
        q._atomic_write(output / "state.json", state)
        monitor = resident.ResidentSafetyMonitor(output / "memory.jsonl", ops, state["initial"], deadline=deadline)
        with monitor:
            try:
                _must(resident._inspect_container(ops, resident._sentinel_name(document["window_id"]))
                      is None, "resident watchdog sentinel already exists")
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
                result = (executor or _run_evaluator)(document, parent, output, monitor, state, cutoff)
            except BaseException as exc:  # noqa: BLE001 - signals must enter exact restoration
                error = f"{type(exc).__name__}: {exc}"
            finally:
                state["phase"] = "restoration"
                q._atomic_write(output / "state.json", state)
                try:
                    monitor.transition("restoration")
                finally:
                    state["restoration"] = _restore_resident(
                        ops, state, document, output, deadline=deadline,
                        monitor=monitor if monitor.phase == "restoration" else None)
                    q._atomic_write(output / "state.json", state)
    return _finish(document, output, state, result, error, monitor)


def _finish(document, output, state, result, error, monitor) -> dict:
    complete = (result is not None and result.get("status") == "complete"
                and state.get("restoration", {}).get("status") == "verified"
                and error is None and monitor.failure is None)
    receipt = {"schema": "lab-model-window-result/v1", "window_id": document["window_id"],
               "cohort": document["cohort"], "status": "complete" if complete else "aborted",
               "window_sha256": _sha(_raw(output / "window.json")),
               "finished_at": q.utc_now(), "error": error or monitor.failure,
               "restoration": state.get("restoration"),
               "minimum_mem_available_gib": monitor.minimum_observed_gib,
               "memory_samples": monitor.samples, "promotion_authorized": False,
               "evaluation_run_sha256": (_sha(_raw(output / "evaluation/run.json"))
                                           if (output / "evaluation/run.json").is_file() else None)}
    state["phase"] = "complete" if complete else "aborted"
    q._atomic_write(output / "state.json", state)
    _new(output / "result.json", receipt)
    return receipt


def supervise(path: Path) -> int:
    document, parent = load_window(path)
    output = Path(document["output_dir"])
    _must(not (output / "supervision.json").exists()
          and not (output / "supervision-start.json").exists(), "window has already been supervised")
    _new(output / "supervision-reservation.json", {"reserved_at": q.utc_now(),
         "window_sha256": _sha(_raw(path)), **_process_identity(os.getpid())})
    started = time.monotonic()
    command = [sys.executable, "-m", "bench.flash_next_ab.lab_window", "--worker", "--window", str(path)]
    with (output / "controller.log").open("xb") as log:
        child = subprocess.Popen(command, cwd=CODE_ROOT, stdout=log, stderr=subprocess.STDOUT,
                                 start_new_session=True)
        terminated = False
        interrupted = None
        try:
            _new(output / "supervision-start.json", {"pid": child.pid, "started_at": q.utc_now(),
                 "argv": command, "window_sha256": _sha(_raw(path)), **_process_identity(child.pid)})
            while child.poll() is None:
                elapsed = time.monotonic() - started
                if elapsed >= document["wall_s"] - RESTORE_S and not terminated:
                    child.send_signal(signal.SIGTERM)
                    terminated = True
                if elapsed >= document["wall_s"]:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait(timeout=30)
                    break
                time.sleep(1)
        except BaseException as exc:  # noqa: BLE001 - an interrupted supervisor must still recover
            interrupted = type(exc).__name__
            if child.poll() is None:
                child.send_signal(signal.SIGTERM)
                terminated = True
                try:
                    child.wait(timeout=RESTORE_S)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait(timeout=30)
    recovery = None
    result_path = output / "result.json"
    result = json.loads(_raw(result_path)) if result_path.exists() else {}
    if (result.get("restoration") or {}).get("status") != "verified" and (output / "state.json").exists():
        state = json.loads(_raw(output / "state.json"))
        _must(state.get("window_sha256") == _sha(_raw(path)), "recovery state belongs to another window")
        with resource_lease(canonical_root(CODE_ROOT)):
            if document["cohort"] == "flash":
                recovery = q.restore_exact(q.HostOps(), state, deadline=time.monotonic() + RESTORE_S,
                                           spec=parent.spec, diagnostic_path=output / "recovery-candidate.log")
            else:
                recovery = _restore_resident(q.HostOps(), state, document, output,
                                             deadline=time.monotonic() + RESTORE_S)
    _new(output / "supervision.json", {"schema": "lab-model-supervision/v1",
        "window_sha256": _sha(_raw(path)), "returncode": child.returncode,
        "elapsed_s": time.monotonic() - started, "terminated_at_cutoff": terminated,
        "interrupted": interrupted, "emergency_restoration": recovery, "finished_at": q.utc_now()})
    return 0 if (child.returncode == 0 and result.get("status") == "complete"
                 and interrupted is None and not terminated) else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--worker", action="store_true")
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--window", type=Path)
    parser.add_argument("--window-id")
    parser.add_argument("--cohort", choices=("resident", "flash"))
    parser.add_argument("--kind", choices=tuple(EVALUATORS), default="primary")
    parser.add_argument("--budget-s", type=int)
    parser.add_argument("--wall-s", type=int)
    args = parser.parse_args(argv)
    if args.prepare:
        print(prepare(args.plan, cohort=args.cohort, window_id=args.window_id,
                      runtime_budget_s=args.budget_s, wall_s=args.wall_s, kind=args.kind))
        return 0
    _must(not os.environ.get("MOCK_LLM"), "live window refuses MOCK_LLM")
    previous = q._signal_guard()
    try:
        if args.run:
            return supervise(args.window.absolute())
        document, parent = load_window(args.window)
        callback = _flash if document["cohort"] == "flash" else _resident
        result = callback(document, parent, Path(document["output_dir"]),
                          time.monotonic() + document["wall_s"])
        return 0 if result["status"] == "complete" else 1
    finally:
        q._restore_signals(previous)


if __name__ == "__main__":
    raise SystemExit(main())
