"""Operational mode for a registered lab window; no benchmark score admission."""
from __future__ import annotations

import os
import re
import stat
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from . import model_runtime as mr

CODE_ROOT = Path("/home/decross1/projects/a_bgt_rsi_worktrees/lab-eight-hour-20260915")
ARTIFACT_ROOT = Path("/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-15/lab-eight-hour")
WINDOW_ROOT = ARTIFACT_ROOT / "model-windows"
PARENT_PATH = Path("/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-14/"
                   "qwen-flash-next-research/evaluation/followon-qualified-parents/"
                   "qfn-mia-mtp3-red47k-20260915-a.json")
RUN_ID = re.compile(r"qfn-ab-[a-z0-9][a-z0-9._-]{0,63}\.(?:resident|flash)\Z")
SPEC_ID = "mia-925d7be6-mtp3-reduced47k-v2opt-v1"
SPEC_SHA = "e71d3134f407cad3c288c21f9485c27352676dbb7de647c5b567777256702a50"
PREPARING = frozenset({"preflight", "candidate_create", "resident_stop", "candidate_start", "restoration"})
ACTIVE = frozenset({"probes", "evaluation"})
TERMINAL = frozenset({"complete", "aborted"})
PHASES = PREPARING | ACTIVE | TERMINAL
RESIDENT_PHASES = frozenset({"preflight", "evaluation", "restoration", "complete", "aborted"})
PLAN_SCHEMAS = {"primary": "lab-model-eval-plan/v1",
                "context": "lab-model-context-plan/v1",
                "fresh": "lab-model-fresh-plan/v1"}
KIND_BUDGET_CAPS = {"primary": 10_430, "context": 6_000, "fresh": 1_800}
PRIMARY_EVALUATOR_FILES = frozenset({
    "bench/flash_next_ab/lab_eval_plan.py", "bench/flash_next_ab/lab_eval_runner.py",
    "bench/flash_next_ab/lab_eval_replay.py", "bench/flash_next_ab/adapters.py",
    "bench/flash_next_ab/harness.py", "bench/flash_next_ab/manifest.py",
    "bench/flash_next_ab/transport.py", "bench/flash_next_ab/private_evidence.py",
})
CONTEXT_EVALUATOR_FILES = frozenset({
    "bench/flash_next_ab/lab_eval_context.py",
    "bench/flash_next_ab/lab_eval_context_packs.py",
    "bench/flash_next_ab/lab_eval_plan.py",
    "bench/flash_next_ab/lab_eval_runner.py",
    "bench/flash_next_ab/followon_context.py",
    "bench/flash_next_ab/followon_context_packs.py",
    "bench/flash_next_ab/harness.py",
    "bench/flash_next_ab/manifest.py",
    "bench/flash_next_ab/transport.py",
    "bench/flash_next_ab/private_evidence.py",
    "bench/weekly_upgrade_eval/runner.py",
})
FRESH_EVALUATOR_FILES = frozenset({
    "bench/flash_next_ab/lab_eval_fresh.py",
    "bench/flash_next_ab/lab_eval_plan.py",
    "bench/flash_next_ab/lab_eval_runner.py",
    "bench/flash_next_ab/lab_eval_replay.py",
    "bench/flash_next_ab/harness.py",
    "bench/flash_next_ab/manifest.py",
    "bench/flash_next_ab/transport.py",
    "bench/flash_next_ab/private_evidence.py",
    "bench/weekly_upgrade_eval/runner.py",
    "bench/weekly_upgrade_eval/manifest.py",
    "bench/weekly_upgrade_historical/runner.py",
    "bench/weekly_upgrade_historical/manifest.py",
    "bench/weekly_upgrade_historical/sandbox.py",
})
EVALUATOR_FILES = {"primary": PRIMARY_EVALUATOR_FILES,
                   "context": CONTEXT_EVALUATOR_FILES,
                   "fresh": FRESH_EVALUATOR_FILES}
CAP_RUN_ID = "qfn-ab-lab-diversity-cap-20260915-a.flash"
CAP_AUDIT_PATH = ARTIFACT_ROOT / "mia-diversity-cap-paired-v1.failure-audit.json"
CAP_AUDIT_SHA = "4a94d553dc47b7a55f297634b2e077ad3f7b8a5b9a485baf12a503bf1a8be1f0"
CAP_AUDIT_SOURCE_PATH = ARTIFACT_ROOT / "mia-diversity-cap-paired-v1.failure-audit-source.py"
CAP_AUDIT_SOURCE_SHA = "6cdb209f7da93c090757e41064a87b0fa3f5d433655f751edea53ce1417788b8"


def _need(ok: bool, reason: str) -> None:
    if not ok:
        raise mr.RuntimeSourceError(reason)


def _slot(root: Path = WINDOW_ROOT) -> int | None:
    """Preserve an invalid newest lab state as a precedence candidate."""
    try:
        fd = os.open(root, mr._flags(directory=True))
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise mr.RuntimeSourceError("lab window root unavailable") from exc
    try:
        times = []
        with os.scandir(fd) as entries:
            for n, entry in enumerate(entries):
                _need(n < mr.MAX_RUNS, "lab window root scan bound exceeded")
                if not RUN_ID.fullmatch(entry.name):
                    continue
                child = os.open(entry.name, mr._flags(directory=True), dir_fd=fd)
                try:
                    directory = os.fstat(child)
                    try:
                        state = os.stat("state.json", dir_fd=child, follow_symlinks=False)
                        times.append(state.st_mtime_ns if stat.S_ISREG(state.st_mode)
                                     else max(directory.st_mtime_ns, state.st_mtime_ns))
                    except OSError:
                        # A prepared but unsupervised window has not changed
                        # the operating mode. Once the supervisor starts, a
                        # missing state must block older-mode fallback.
                        try:
                            start = os.stat("supervision-start.json", dir_fd=child,
                                            follow_symlinks=False)
                        except OSError:
                            continue
                        times.append(max(directory.st_mtime_ns, start.st_mtime_ns))
                finally:
                    os.close(child)
        return max(times) if times else None
    finally:
        os.close(fd)


def _sources(window: dict) -> str:
    from bench.flash_next_ab.followon_dispatch import FOLLOWON_SOURCE_MODULES

    expected = {"bench/flash_next_ab/" + name for name in FOLLOWON_SOURCE_MODULES}
    expected |= {"bench/flash_next_ab/lab_window.py", "orchestrator/weekly_upgrade_trial.py"}
    refs = window.get("controller_sources")
    _need(isinstance(refs, dict) and set(refs) == expected,
          "lab controller source tuple incomplete")
    for name, ref in refs.items():
        _need(isinstance(name, str) and not Path(name).is_absolute() and
              ".." not in Path(name).parts and isinstance(ref, dict) and
              ref.get("path") == str(CODE_ROOT / name) and mr.SHA256.fullmatch(str(ref.get("sha256", ""))),
              "lab controller source reference invalid")
        raw = mr._read_path(CODE_ROOT / name, maximum=8 * 1024 * 1024,
                            label="lab controller source")
        _need(mr._sha256(raw) == ref["sha256"], "lab controller source drift")
    return mr._canonical_sha256(refs)


def _evaluator_sources(plan: dict, kind: str) -> str:
    refs = plan.get("evaluator_source_bundle")
    _need(kind in EVALUATOR_FILES and isinstance(refs, dict) and
          set(refs) == EVALUATOR_FILES[kind],
          "lab evaluator source tuple incomplete")
    for name, digest in refs.items():
        _need(isinstance(digest, str) and mr.SHA256.fullmatch(digest),
              "lab evaluator source SHA invalid")
        raw = mr._read_path(CODE_ROOT / name, maximum=8 * 1024 * 1024,
                            label="lab evaluator source")
        _need(mr._sha256(raw) == digest, "lab evaluator source drift")
    return mr._canonical_sha256(refs)


def _worker(state: dict, start: dict, window_path: Path, proc_root: Path,
            boot_id_path: Path) -> None:
    pid = mr._nonnegative_integer(state.get("worker_pid"), "lab worker PID", positive=True)
    ticks = mr._nonnegative_integer(state.get("worker_start_ticks"), "lab worker ticks", positive=True)
    boot = mr._read_path(boot_id_path, maximum=256, label="current boot ID").decode("ascii").strip()
    _need(state.get("boot_id") == start.get("boot_id") == boot and
          start.get("worker_pid") == start.get("pid") == pid and
          start.get("worker_start_ticks") == ticks and
          start.get("window_sha256") == state.get("window_sha256"),
          "lab worker start receipt differs")
    argv = start.get("argv")
    _need(isinstance(argv, list) and len(argv) == 6 and
          argv[1:] == ["-m", "bench.flash_next_ab.lab_window", "--worker", "--window", str(window_path)] and
          isinstance(argv[0], str) and Path(argv[0]).is_absolute(),
          "lab worker invocation unregistered")
    stat_raw = mr._read_path(proc_root / str(pid) / "stat", maximum=mr.MAX_PROC_BYTES,
                             label="lab worker process stat")
    try:
        text = stat_raw.decode("utf-8")
        close = text.rfind(")")
        observed_ticks = int(text[close + 1:].split()[19])
    except (UnicodeError, ValueError, IndexError) as exc:
        raise mr.RuntimeSourceError("lab worker process stat invalid") from exc
    _need(close >= 0 and observed_ticks == ticks, "lab worker process identity changed")
    cmd_raw = mr._read_path(proc_root / str(pid) / "cmdline", maximum=mr.MAX_PROC_BYTES,
                            label="lab worker command")
    try:
        cmd = [item.decode("utf-8") for item in cmd_raw.rstrip(b"\0").split(b"\0")]
    except UnicodeError as exc:
        raise mr.RuntimeSourceError("lab worker command invalid") from exc
    _need(cmd == argv, "lab worker command differs from supervision")
    try:
        cwd = os.readlink(proc_root / str(pid) / "cwd")
    except OSError as exc:
        raise mr.RuntimeSourceError("lab worker source cwd unavailable") from exc
    _need(cwd == str(CODE_ROOT), "lab worker runs outside registered code root")


def _candidate_process(pid: int, ticks: int, cgroup_path: str, proc_root: Path) -> None:
    stat_raw = mr._read_path(proc_root / str(pid) / "stat", maximum=mr.MAX_PROC_BYTES,
                             label="lab candidate process stat")
    try:
        text = stat_raw.decode("utf-8")
        closing = text.rfind(")")
        observed = int(text[closing + 1:].split()[19])
    except (UnicodeError, ValueError, IndexError) as exc:
        raise mr.RuntimeSourceError("lab candidate process stat invalid") from exc
    _need(closing >= 0 and observed == ticks, "lab candidate process identity changed")
    membership = mr._read_path(proc_root / str(pid) / "cgroup", maximum=mr.MAX_PROC_BYTES,
                               label="lab candidate cgroup membership")
    _need(membership.decode("ascii").strip() == "0::" + cgroup_path,
          "lab candidate cgroup membership changed")


def _live_restored(state: dict, cohort: str) -> str:
    """Check present incumbents and Nara; old restoration bytes are not live health."""
    from bench.flash_next_ab import qualification as q

    ops = q.HostOps()
    initial = state.get("initial")
    _need(isinstance(initial, dict), "lab initial resident observation absent")
    if cohort == "resident":
        from bench.flash_next_ab import resident_evaluation_window as resident
        current = resident._read_exact_residents(ops, initial)
        return "running" if current["nara"]["ActiveState"] == "active" else "paused"
    mr._validate_initial(state)
    for before in initial["residents"]:
        q._verify_exact_resident_state(ops, before)
        health = next(item["health_url"] for item in q.RESIDENTS if item["name"] == before["name"])
        ops.http_bytes(health, timeout=2)
    service = q._service_state(ops)
    wanted = "active" if initial["nara_was_active"] else "inactive"
    _need(service.get("ActiveState") == wanted, "lab Nara restoration no longer current")
    return "running" if wanted == "active" else "paused"


def _cap_terminal_runtime(run_fd: int, run_path: Path, window_raw: bytes,
                          state_raw: bytes, observed: datetime) -> dict[str, Any]:
    """Only the frozen restored startup abort can report current residents."""
    from bench.flash_next_ab import qualification as q
    from bench.flash_next_ab.followon_profiles import MIA_MTP3_REDUCED47K_OPT as spec

    from . import lab_diversity_cap_progress as cap

    window = mr._strict_object(window_raw, "cap window")
    state = mr._strict_object(state_raw, "cap state")
    plan_raw = mr._read_path(cap.PLAN, maximum=2 * 1024 * 1024, label="cap plan")
    plan = mr._strict_object(plan_raw, "cap plan")
    _need(run_path == cap.OUTPUT and mr._sha256(window_raw) == cap.WINDOW_SHA and
          mr._sha256(plan_raw) == cap.PLAN_SHA and
          window.get("evaluation_plan") == {"path": str(cap.PLAN), "sha256": cap.PLAN_SHA} and
          window.get("runtime_certificate") == {"path": str(PARENT_PATH),
              "sha256": mr._sha256(mr._read_path(PARENT_PATH, maximum=8192,
                                               label="cap qualified parent"))} and
          window.get("candidate_spec_sha256") == SPEC_SHA == spec.identity_sha256(),
          "cap exact plan, window, or parent changed")
    cap._registered(plan, window)
    controller = window["controller_sources"]
    evaluator = plan["evaluator_source_bundle"]
    _need(len(controller) == 45 and len(evaluator) == 16,
          "cap source tuple length changed")
    for name, ref in controller.items():
        _need(isinstance(name, str) and not Path(name).is_absolute() and
              ".." not in Path(name).parts and isinstance(ref, dict) and
              ref == {"path": str(cap.CODE_ROOT / name), "sha256": ref.get("sha256")} and
              mr.SHA256.fullmatch(str(ref.get("sha256", ""))),
              "cap controller source reference changed")
        raw = mr._read_path(cap.CODE_ROOT / name, maximum=8 * 1024 * 1024,
                            label="cap controller source")
        _need(mr._sha256(raw) == ref["sha256"], "cap controller source drift")
    for name, digest in evaluator.items():
        _need(isinstance(name, str) and not Path(name).is_absolute() and
              ".." not in Path(name).parts and mr.SHA256.fullmatch(str(digest)),
              "cap evaluator source reference changed")
        raw = mr._read_path(cap.CODE_ROOT / name, maximum=8 * 1024 * 1024,
                            label="cap evaluator source")
        _need(mr._sha256(raw) == digest, "cap evaluator source drift")
    audit_raw = mr._read_path(CAP_AUDIT_PATH, maximum=2 * 1024 * 1024,
                              label="cap failure audit")
    audit = mr._strict_object(audit_raw, "cap failure audit")
    source_raw = mr._read_path(CAP_AUDIT_SOURCE_PATH, maximum=32 * 1024,
                               label="cap failure audit source")
    _need(mr._sha256(audit_raw) == CAP_AUDIT_SHA and
          mr._sha256(source_raw) == CAP_AUDIT_SOURCE_SHA and
          audit.get("schema") == "lab-mia-diversity-cap-startup-failure-audit/v1" and
          audit.get("window_id") == window["window_id"] and
          audit.get("status") == "closed_aborted_restored_no_evaluation" and
          audit.get("audit_source") == {"path": str(CAP_AUDIT_SOURCE_PATH),
              "sha256": CAP_AUDIT_SOURCE_SHA, "bytes": len(source_raw)} and
          audit.get("registered", {}).get("controller_source_bundle_sha256") ==
              mr._canonical_sha256(controller) and
          audit.get("registered", {}).get("evaluator_source_bundle_sha256") ==
              mr._canonical_sha256(evaluator) and
          audit.get("evaluation", {}).get("issued_calls") == 0 and
          audit.get("evaluation", {}).get("evaluation_run_present") is False and
          audit.get("evaluation", {}).get("evaluation_directory_present") is False and
          audit.get("terminal", {}).get("result_error_code") == "startup_host_swap_5s" and
          audit.get("private_content_exported") is False and
          cap._known_startup_failure() == "startup_host_swap_5s",
          "cap archived no-evaluation abort proof changed")
    for key, expected in (("result", cap.FAILED_RESULT_SHA),
                          ("state", cap.FAILED_STATE_SHA),
                          ("supervision", cap.FAILED_SUPERVISION_SHA),
                          ("memory", cap.FAILED_MEMORY_SHA)):
        ref = audit["raw_refs"][key]
        _need(ref.get("sha256") == expected, "cap terminal audit raw ref differs")
    result_raw = mr._read_fd(run_fd, "result.json", maximum=mr.MAX_RESULT_BYTES,
                             label="cap result")
    supervision_raw = mr._read_fd(run_fd, "supervision.json", maximum=mr.MAX_RESULT_BYTES,
                                  label="cap supervision")
    _need(mr._sha256(result_raw) == cap.FAILED_RESULT_SHA and
          mr._sha256(state_raw) == cap.FAILED_STATE_SHA and
          mr._sha256(supervision_raw) == cap.FAILED_SUPERVISION_SHA and
          state.get("phase") == "aborted" and
          state.get("restoration") == mr._strict_object(result_raw, "cap result").get("restoration") and
          mr._parse_time(state.get("started_at"), "cap state start") <=
              observed + timedelta(seconds=mr.MAX_CLOCK_SKEW_SECONDS),
          "cap terminal state changed")
    _need(mr.SHA256.fullmatch(str(state.get("candidate_id", ""))) and
          _live_restored(state, "flash") == "running", "cap residents or Nara not live")
    ops = q.HostOps()
    _need(q._inspect_container(ops, state["candidate_id"]) is None and
          q._inspect_container(ops, spec.container_name) is None,
          "cap candidate sentinel currently present")
    _need(mr._read_fd(run_fd, "state.json", maximum=mr.MAX_STATE_BYTES,
                      label="cap state recheck") == state_raw,
          "cap state changed during projection")
    source_sha = mr._composite_sha256(window=cap.WINDOW_SHA, plan=cap.PLAN_SHA,
        state=cap.FAILED_STATE_SHA, result=cap.FAILED_RESULT_SHA,
        supervision=cap.FAILED_SUPERVISION_SHA, memory=cap.FAILED_MEMORY_SHA,
        controller=mr._canonical_sha256(controller),
        evaluator=mr._canonical_sha256(evaluator), audit=CAP_AUDIT_SHA,
        audit_source=CAP_AUDIT_SOURCE_SHA)
    return {"schema_version": mr.SCHEMA_VERSION, "observed_at": observed.isoformat(),
            "mode": "resident", "mode_source": "lab_evaluation_state",
            "mode_source_sha256": source_sha, "resident_services_expected": "online",
            "nara_service_expected": "running", "run_id": CAP_RUN_ID,
            "phase": "aborted", "candidate_variant": mr._variant_projection(spec),
            "source_error": None}


def project_lab_runtime(root: Path = WINDOW_ROOT, *, proc_root: Path = mr.PROC_ROOT,
                        boot_id_path: Path = mr.BOOT_ID_PATH,
                        observed: datetime) -> dict[str, Any]:
    run_fd = None
    try:
        run_fd, run_id, state_raw = mr._open_latest_run(root, namespace=RUN_ID)
        run_path = root / run_id
        window_path = run_path / "window.json"
        window_raw = mr._read_fd(run_fd, "window.json", maximum=2 * 1024 * 1024,
                                 label="lab window registration")
        window = mr._strict_object(window_raw, "lab window registration")
        state = mr._strict_object(state_raw, "lab runtime state")
        cohort = "flash" if run_id.endswith(".flash") else "resident"
        if run_id == CAP_RUN_ID:
            return _cap_terminal_runtime(run_fd, run_path, window_raw, state_raw, observed)
        parent_raw = mr._read_path(PARENT_PATH, maximum=8192,
                                    label="lab runtime certificate")
        parent = mr._strict_object(parent_raw, "lab runtime certificate")
        _need(window.get("schema") == "lab-model-window/v1" and
              window.get("output_dir") == str(run_path) and
              window.get("window_id") + "." + cohort == run_id and
              window.get("cohort") == cohort and window.get("evaluation_kind") in PLAN_SCHEMAS and
              window.get("code_root") == str(CODE_ROOT) and
              window.get("runtime_certificate") == {"path": str(PARENT_PATH),
                  "sha256": mr._sha256(parent_raw)} and
              parent.get("schema_version") == "flash-followon-qualified-v5-parent/v1" and
              parent.get("candidate_spec_id") == SPEC_ID and
              parent.get("candidate_spec_sha256") == SPEC_SHA and
              parent.get("promotion_authorized") is False and
              window.get("candidate_spec_id") == SPEC_ID and
              window.get("candidate_spec_sha256") == SPEC_SHA and
              window.get("restoration_reserve_s") == 600 and
              window.get("minimum_mem_available_gib") == 20 and
              type(window.get("runtime_budget_s")) is int and
              60 <= window["runtime_budget_s"] <= KIND_BUDGET_CAPS[window["evaluation_kind"]] and
              type(window.get("wall_s")) is int and
              window["runtime_budget_s"] + 600 + (1500 if cohort == "flash" else 60)
              <= window["wall_s"] <= 14400 and
              window.get("promotion_authorized") is False,
              "lab window registration or runtime certificate differs")
        bundle_sha = _sources(window)
        plan_ref = window.get("evaluation_plan")
        _need(isinstance(plan_ref, dict) and isinstance(plan_ref.get("path"), str)
              and Path(plan_ref["path"]).is_relative_to(ARTIFACT_ROOT),
              "lab evaluation plan path unregistered")
        plan_raw = mr._read_path(Path(plan_ref["path"]), maximum=2 * 1024 * 1024,
                                 label="lab evaluation plan")
        plan = mr._strict_object(plan_raw, "lab evaluation plan")
        _need(mr._sha256(plan_raw) == plan_ref.get("sha256") and
              plan.get("schema_version") == PLAN_SCHEMAS[window["evaluation_kind"]],
              "lab evaluation plan source differs")
        evaluator_sha = _evaluator_sources(plan, window["evaluation_kind"])
        phase = state.get("phase")
        _need(phase in (PHASES if cohort == "flash" else RESIDENT_PHASES) and
              state.get("window_sha256") == mr._sha256(window_raw) and
              mr._parse_time(state.get("started_at"), "lab state start") <=
              observed + timedelta(seconds=mr.MAX_CLOCK_SKEW_SECONDS),
              "lab state identity or chronology differs")
        memory_sha = None
        terminal_sha = None
        image_observed = False
        if phase in TERMINAL:
            result_raw = mr._read_fd(run_fd, "result.json", maximum=mr.MAX_RESULT_BYTES,
                                     label="lab terminal result")
            result = mr._strict_object(result_raw, "lab terminal result")
            supervision_raw = mr._read_fd(run_fd, "supervision.json", maximum=mr.MAX_RESULT_BYTES,
                                          label="lab terminal supervision")
            supervision = mr._strict_object(supervision_raw, "lab terminal supervision")
            _need(result.get("schema") == "lab-model-window-result/v1" and
                  result.get("window_id") == window["window_id"] and result.get("cohort") == cohort and
                  result.get("window_sha256") == state["window_sha256"] and
                  result.get("restoration") == state.get("restoration") and
                  isinstance(result.get("restoration"), dict) and
                  result["restoration"].get("status") == "verified" and
                  supervision.get("schema") == "lab-model-supervision/v1" and
                  supervision.get("window_sha256") == state["window_sha256"] and
                  supervision.get("emergency_restoration") is None and
                  ((phase == "complete" and result.get("status") == "complete" and
                    supervision.get("returncode") == 0 and
                    supervision.get("interrupted") is None and
                    supervision.get("terminated_at_cutoff") is False) or
                   (phase == "aborted" and result.get("status") == "aborted")),
                  "lab terminal restoration is unverified")
            terminal_sha = mr._composite_sha256(result=mr._sha256(result_raw),
                                                 supervision=mr._sha256(supervision_raw))
            nara = _live_restored(state, cohort)
            mode, residents = "resident", "online"
        else:
            start_raw = mr._read_fd(run_fd, "supervision-start.json", maximum=8192,
                                    label="lab worker supervision start")
            start = mr._strict_object(start_raw, "lab worker supervision start")
            _worker(state, start, window_path, proc_root, boot_id_path)
            if (observed - mr._parse_time(start.get("started_at"), "lab worker start")
                    > timedelta(seconds=window["wall_s"])):
                raise mr.RuntimeSourceError("lab window wall deadline expired")
            if phase in ACTIVE:
                if cohort == "resident":
                    from .model_runtime_resident_followon import _last_memory
                    _last_memory(run_path / "memory.jsonl", observed, state)
                    mode, residents, nara = "resident", "online", "paused"
                else:
                    from bench.flash_next_ab.evaluation_window import (
                        EXTENDED_SERVING_PROFILE,
                    )
                    from bench.flash_next_ab.followon_profiles import (
                        MIA_MTP3_REDUCED47K_OPT as spec,
                    )
                    candidate_id = state.get("candidate_id")
                    pid = mr._nonnegative_integer(state.get("candidate_cgroup_pid"),
                                                   "lab candidate PID", positive=True)
                    ticks = mr._nonnegative_integer(state.get("candidate_cgroup_start_ticks"),
                                                     "lab candidate ticks", positive=True)
                    _need(mr.CONTAINER_ID.fullmatch(str(candidate_id)) and
                          state.get("candidate_cgroup_path") ==
                          f"/system.slice/docker-{candidate_id}.scope" and
                          spec.identity_sha256() == SPEC_SHA,
                          "lab candidate cgroup or variant unbound")
                    qual_ref = parent.get("source_refs", {}).get("plan.json", {})
                    qual_raw = mr._read_path(Path(qual_ref["path"]), maximum=mr.MAX_PLAN_BYTES,
                                              label="lab qualification paging plan")
                    _need(mr._sha256(qual_raw) == qual_ref.get("sha256"),
                          "lab qualification paging plan drift")
                    _candidate_process(pid, ticks, state["candidate_cgroup_path"], proc_root)
                    qual_plan = mr._strict_object(qual_raw, "lab qualification paging plan")
                    _, memory_sha = mr._latest_memory(run_fd, observed, floor_gib=20,
                        expected_phase="probes" if phase == "probes" else "evaluation",
                        paging_policy=qual_plan["paging_policy"],
                        candidate_identity=(candidate_id, state["candidate_cgroup_path"], pid, ticks),
                        memory_limit_bytes=spec.docker_memory_limit_bytes, spec=spec,
                        maximum_bytes=64 * 1024 * 1024, maximum_rows=20_000,
                        maximum_age_seconds=10, extended_serving_profile=EXTENDED_SERVING_PROFILE)
                    image_observed = True
                    mode, residents, nara = "candidate_research", "stopped", "paused"
            else:
                mode, residents, nara = "transitioning", "unknown", "unknown"
        source_sha = mr._composite_sha256(window=mr._sha256(window_raw),
            state=mr._sha256(state_raw), plan=mr._sha256(plan_raw),
            controller=bundle_sha, evaluator=evaluator_sha,
            memory=memory_sha or "", terminal=terminal_sha or "")
        _need(mr._read_fd(run_fd, "state.json", maximum=mr.MAX_STATE_BYTES,
                          label="lab state recheck") == state_raw,
              "lab state changed during projection")
        if cohort == "flash":
            from bench.flash_next_ab.followon_profiles import (
                MIA_MTP3_REDUCED47K_OPT as spec,
            )
            variant = mr._variant_projection(spec, image_observed=image_observed)
        else:
            variant = None
        return {"schema_version": mr.SCHEMA_VERSION, "observed_at": observed.isoformat(),
                "mode": mode, "mode_source": "lab_evaluation_state",
                "mode_source_sha256": source_sha,
                "resident_services_expected": residents, "nara_service_expected": nara,
                "run_id": run_id, "phase": phase, "candidate_variant": variant,
                "source_error": None}
    except (OSError, ValueError, TypeError, KeyError, AttributeError,
            ImportError, UnicodeError, RuntimeError, mr.RuntimeSourceError):
        return mr._unknown(observed.isoformat(), "lab operating state absent, stale, or untrusted")
    finally:
        if run_fd is not None:
            os.close(run_fd)


def maybe_project_lab(qualification_root: Path, evaluation_root: Path,
                      followon_root: Path, *, lab_root: Path = WINDOW_ROOT,
                      proc_root: Path, boot_id_path: Path,
                      observed: datetime) -> dict[str, Any] | None:
    """A newer invalid lab state blocks fallback to an old completed window."""
    try:
        from .model_runtime_extended import _latest_slot_mtime as old_slot
        from .model_runtime_followon import _latest_slot_mtime as followon_flash_slot
        from .model_runtime_resident_followon import (
            latest_slot_mtime as followon_resident_slot,
        )

        lab = _slot(lab_root)
        older = max((x for x in (
            old_slot(qualification_root, extended=False),
            old_slot(evaluation_root, extended=True),
            followon_flash_slot(followon_root),
            followon_resident_slot(followon_root),
        ) if x is not None), default=None)
        if lab is None or (older is not None and lab < older):
            return None
        if older is not None and lab == older:
            return mr._unknown(observed.isoformat(), "lab and historical runtime order is ambiguous")
        result = project_lab_runtime(lab_root, proc_root=proc_root,
                                     boot_id_path=boot_id_path, observed=observed)
        lab_after = _slot(lab_root)
        older_after = max((x for x in (
            old_slot(qualification_root, extended=False),
            old_slot(evaluation_root, extended=True),
            followon_flash_slot(followon_root),
            followon_resident_slot(followon_root),
        ) if x is not None), default=None)
        if lab_after != lab or older_after != older:
            return mr._unknown(observed.isoformat(), "lab runtime source order changed")
        return result
    except (OSError, mr.RuntimeSourceError):
        return mr._unknown(observed.isoformat(), "lab runtime source order unavailable")
