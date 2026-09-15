"""Read a registered grouped Flash follow-on window as an operating mode.

This projection is operational evidence only. A live endpoint or an unfinished
benchmark never establishes a comparative model gain.
"""
from __future__ import annotations

import os
import re
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import model_runtime as mr

FOLLOWON_RUN_ROOT = Path(
    "/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-14/"
    "qwen-flash-next-research/evaluation/followon-runs"
)
FOLLOWON_STATE_SCHEMA = "flash-followon-flash-state/v1"
FOLLOWON_RESULT_SCHEMA = "flash-followon-flash-result/v1"
FOLLOWON_PLAN_SCHEMA = "flash-followon-flash-plan/v1"
FOLLOWON_FLASH_RUN_ID = re.compile(
    r"qfn-followon-[a-z0-9][a-z0-9._-]{0,63}\.flash\Z"
)
EXTENDED_PHASES = frozenset({
    "preflight", "model_verification", "setup_quiescence", "sentinel_create",
    "resident_stop", "candidate_start", "readiness", "ready_stabilization",
    "probes", "evaluation", "evaluation_complete_pending_restoration",
    "restoring", "complete", "supervisor_recovered", "recovery_unknown",
})
MONITOR_PHASES = {
    "preflight": "setup", "model_verification": "setup",
    "setup_quiescence": "setup", "sentinel_create": "load",
    "resident_stop": "load", "candidate_start": "load", "readiness": "load",
    "ready_stabilization": "ready", "probes": "probes",
    "evaluation": "evaluation", "evaluation_complete_pending_restoration": "evaluation",
    "restoring": "restoration",
}
ACTIVE_PHASES = frozenset({
    "readiness", "ready_stabilization", "probes", "evaluation",
    "evaluation_complete_pending_restoration",
})
TERMINAL_PHASES = frozenset({"complete", "supervisor_recovered", "recovery_unknown"})


def _latest_slot_mtime(root: Path) -> int | None:
    """Find direct-child source freshness, including an invalid newest state."""
    try:
        root_fd = os.open(root, mr._flags(directory=True))
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise mr.RuntimeSourceError("runtime state root is unavailable") from exc
    try:
        times: list[int] = []
        seen = 0
        with os.scandir(root_fd) as entries:
            for entry in entries:
                seen += 1
                if seen > mr.MAX_RUNS:
                    raise mr.RuntimeSourceError("runtime state root exceeds its scan bound")
                name = entry.name
                accepted = FOLLOWON_FLASH_RUN_ID.fullmatch(name)
                if not accepted:
                    continue
                try:
                    run_fd = os.open(name, mr._flags(directory=True), dir_fd=root_fd)
                except OSError:
                    # A redirected or unreadable named entry may be newer. Its
                    # parent entry mtime is unavailable through scandir, so
                    # fail closed rather than select an older receipt.
                    raise mr.RuntimeSourceError("runtime state child is unavailable") from None
                try:
                    directory = os.fstat(run_fd)
                    try:
                        state = os.stat("state.json", dir_fd=run_fd, follow_symlinks=False)
                        # Match _open_latest_run's ordering. A directory can
                        # gain a newer sidecar while its state remains older.
                        times.append(
                            state.st_mtime_ns if stat.S_ISREG(state.st_mode)
                            else max(directory.st_mtime_ns, state.st_mtime_ns)
                        )
                    except OSError:
                        times.append(directory.st_mtime_ns)
                finally:
                    os.close(run_fd)
        return max(times) if times else None
    finally:
        os.close(root_fd)


def _validate_worker(state: dict[str, Any], run_path: Path, window_path: Path,
                     launcher: str, proc_root: Path) -> None:
    pid = mr._nonnegative_integer(state.get("worker_pid"), "extended worker PID", positive=True)
    ticks = mr._nonnegative_integer(
        state.get("worker_start_ticks"), "extended worker start identity", positive=True
    )
    process = proc_root / str(pid)
    raw_stat = mr._read_path(
        process / "stat", maximum=mr.MAX_PROC_BYTES, label="extended worker stat"
    )
    try:
        text = raw_stat.decode("utf-8")
        closing = text.rfind(")")
        observed = int(text[closing + 1:].split()[19])
    except (UnicodeError, ValueError, IndexError) as exc:
        raise mr.RuntimeSourceError("extended worker stat is malformed") from exc
    if closing < 0 or observed != ticks:
        raise mr.RuntimeSourceError("extended worker start identity differs")
    raw_command = mr._read_path(
        process / "cmdline", maximum=mr.MAX_PROC_BYTES, label="extended worker command"
    )
    try:
        command = [part.decode("utf-8") for part in raw_command.rstrip(b"\0").split(b"\0")]
    except UnicodeError as exc:
        raise mr.RuntimeSourceError("extended worker command is malformed") from exc
    expected = [
        launcher, "-m", "bench.flash_next_ab.extended_lifecycle", "--worker",
        "--eval-plan", str(window_path), "--output-dir", str(run_path),
    ]
    if command != expected:
        raise mr.RuntimeSourceError("extended worker command differs from registration")


def _candidate_identity(state: dict[str, Any]) -> tuple[str, str, int, int] | None:
    identifier = state.get("candidate_id")
    if identifier is None:
        return None
    if not mr.CONTAINER_ID.fullmatch(str(identifier)):
        raise mr.RuntimeSourceError("extended candidate ID is invalid")
    path = f"/system.slice/docker-{identifier}.scope"
    if state.get("candidate_cgroup_path") != path:
        raise mr.RuntimeSourceError("extended candidate cgroup path differs")
    return (
        identifier, path,
        mr._nonnegative_integer(state.get("candidate_cgroup_pid"),
                                "extended candidate PID", positive=True),
        mr._nonnegative_integer(state.get("candidate_cgroup_start_ticks"),
                                "extended candidate process identity", positive=True),
    )


def project_followon_runtime(
    followon_root: Path,
    *,
    proc_root: Path,
    boot_id_path: Path,
    observed: datetime,
) -> dict[str, Any]:
    """Admit one current grouped-window phase from registered sources only."""
    observed = observed.astimezone(timezone.utc)
    observed_at = observed.isoformat()
    try:
        from bench.flash_next_ab import evaluation_window as ew
        from bench.flash_next_ab import followon_dispatch as grouped
        from bench.flash_next_ab import followon_plans as fp
        from bench.flash_next_ab.followon_profiles import SPECS_BY_ID
    except ImportError:
        return mr._unknown(observed_at, "extended runtime source is unavailable")
    run_fd = None
    try:
        run_fd, run_id, state_raw = mr._open_latest_run(
            followon_root, namespace=FOLLOWON_FLASH_RUN_ID
        )
        state = mr._strict_object(state_raw, "extended runtime state")
        pair_id = run_id.removesuffix(".flash")
        if (
            state.get("schema") != FOLLOWON_STATE_SCHEMA
            or state.get("run_id") != run_id
            or state.get("pair_id") != pair_id
            or state.get("phase") not in EXTENDED_PHASES
            or state.get("memory_log_relpath") != "memory.jsonl"
        ):
            raise mr.RuntimeSourceError("extended runtime identity differs")
        run_path = followon_root / run_id
        path_details = os.stat(run_path, follow_symlinks=False)
        fd_details = os.fstat(run_fd)
        if (
            not stat.S_ISDIR(path_details.st_mode)
            or (path_details.st_dev, path_details.st_ino)
            != (fd_details.st_dev, fd_details.st_ino)
        ):
            raise mr.RuntimeSourceError("extended run directory changed")
        registered_path = grouped.RESEARCH_ROOT / (
            f"evaluation/followon-window-plans/{pair_id}.flash.json"
        )
        window = fp.load_execution(registered_path, cohort="flash")
        expected_plan = fp.flash_plan(window, run_path)
        plan_raw = mr._read_fd(
            run_fd, "extended-plan.json", maximum=8 * 1024 * 1024,
            label="extended runtime plan",
        )
        plan = mr._strict_object(plan_raw, "extended runtime plan")
        prior_raw = mr._read_fd(
            run_fd, "prior-c0-plan.snapshot.json", maximum=mr.MAX_PLAN_BYTES,
            label="qualified prior C0 plan",
        )
        prior = mr._strict_object(prior_raw, "qualified prior C0 plan")
        contract_raw = mr._read_fd(
            run_fd, "launch-contract.raw.json", maximum=mr.MAX_CONTRACT_BYTES,
            label="extended runtime contract",
        )
        contract = mr._strict_object(contract_raw, "extended runtime contract")
        snapshot = mr._strict_object(mr._read_fd(
            run_fd, "launch-contract.snapshot.json", maximum=mr.MAX_CONTRACT_BYTES,
            label="extended contract snapshot",
        ), "extended contract snapshot")
        source_snapshot = mr._strict_object(mr._read_fd(
            run_fd, "controller-source-bundle.snapshot.json",
            maximum=8 * 1024 * 1024, label="follow-on controller source snapshot",
        ), "follow-on controller source snapshot")
        contract_sha = mr._sha256(contract_raw)
        candidate = plan.get("candidate_variant_id")
        spec = SPECS_BY_ID.get(candidate)
        if spec is None:
            raise mr.RuntimeSourceError("follow-on candidate is not a registered spec")
        if (
            plan != expected_plan
            or plan.get("schema_version")
               != (fp.V5_FLASH_PLAN_SCHEMA if window.v5_parent is not None
                   else FOLLOWON_PLAN_SCHEMA)
            or source_snapshot != plan.get("controller_source_bundle")
            or source_snapshot != window.document["followon_source_bundle"]
            or prior != window.qualification_plan
            or state.get("plan_sha256") != mr._canonical_sha256(prior)
            or state.get("extended_plan_sha256") != mr._canonical_sha256(plan)
            or state.get("window_plan_path") != str(registered_path)
            or state.get("window_plan_sha256") != window.source_sha256
            or plan.get("window_plan_sha256") != window.source_sha256
            or state.get("prior_qualification_receipt_sha256")
            != plan.get("prior_qualification_receipt_sha256")
            or state.get("evaluation_kind") != "followon"
            or state.get("qualified_parent_window")
            != window.document["qualified_parent_window"]
            or state.get("followon_blocks") != window.document["blocks"]
            or (window.v5_parent is not None
                and (plan.get("v5_qualified_parent")
                     != window.document["v5_qualified_parent"]
                     or state.get("v5_qualified_parent")
                        != window.document["v5_qualified_parent"]))
            or state.get("controller_source_bundle_sha256")
            != plan.get("controller_source_bundle_sha256")
            or state.get("extended_serving_profile")
            != plan.get("extended_serving_profile")
            or state.get("extended_serving_profile_sha256")
            != plan.get("extended_serving_profile_sha256")
            or state.get("contract_sha256") != contract_sha
            or plan.get("contract_sha256") != contract_sha
            or snapshot != contract
            or state.get("paging_policy") != prior.get("paging_policy")
            or state.get("candidate") != {"id": spec.spec_id,
                                           "spec_sha256": spec.identity_sha256()}
            or state.get("model_artifact_sha256")
            != spec.model_artifact_sha256()
            or prior.get("image_id") != spec.image_id
            or plan.get("candidate_spec_sha256") != spec.identity_sha256()
            or plan.get("model_artifact_sha256") != spec.model_artifact_sha256()
        ):
            raise mr.RuntimeSourceError("extended runtime source differs from registration")
        profile = plan.get("extended_serving_profile")
        if profile != ew.EXTENDED_SERVING_PROFILE:
            raise mr.RuntimeSourceError("extended serving policy differs")
        runtime_config = contract.get("runtime")
        if (not isinstance(runtime_config, dict)
                or runtime_config.get("max_model_len") != spec.max_model_len
                or runtime_config.get("mtp_speculative_tokens")
                    != getattr(spec, "mtp_speculative_tokens", 0)
                or runtime_config.get("kv_cache_memory_bytes")
                    != spec.kv_cache_memory_bytes):
            raise mr.RuntimeSourceError(
                "follow-on context or speculative-token profile differs"
            )
        started = mr._parse_time(state.get("started_at"), "extended started_at")
        updated = mr._parse_time(state.get("updated_at"), "extended updated_at")
        deadline = mr._parse_time(state.get("invocation_deadline_at"), "extended deadline")
        duration = plan.get("effective_invocation_deadline_seconds")
        if (
            duration != ew.WINDOW_DEADLINE_SECONDS
            or abs((deadline - started - timedelta(seconds=duration)).total_seconds()) > .001
            or updated < started
            or updated > observed + timedelta(seconds=mr.MAX_CLOCK_SKEW_SECONDS)
        ):
            raise mr.RuntimeSourceError("extended runtime clock differs")
        current_boot = mr._read_path(
            boot_id_path, maximum=256, label="current boot identity"
        ).decode("ascii").strip()
        if state.get("boot_id") != current_boot:
            raise mr.RuntimeSourceError("extended state belongs to another boot")
        phase = state["phase"]
        memory_sha = None
        terminal_sha = None
        if phase in TERMINAL_PHASES:
            # Only terminal, fully supervised source sets may attest a
            # restored resident mode. Comparative scores have a separate pair
            # gate and are never inferred from this operational projection.
            from bench.flash_next_ab.followon_completed_window_admission import (
                validate_completed_window,
            )

            proof = validate_completed_window(
                registered_path, run_path, cohort="flash"
            )
            if proof.get("window_id") != pair_id or proof.get("cohort") != "flash":
                raise mr.RuntimeSourceError("extended terminal source differs")
            mr._validate_initial(state)
            mode, residents, nara = "resident", "online", (
                "running" if state["initial"]["nara_was_active"] else "paused"
            )
            terminal_sha = mr._sha256(mr._read_fd(
                run_fd, "result.json", maximum=mr.MAX_RESULT_BYTES,
                label="extended terminal result",
            ))
            if terminal_sha != proof.get("result_sha256"):
                raise mr.RuntimeSourceError("extended terminal result changed after admission")
        else:
            if observed >= deadline:
                raise mr.RuntimeSourceError("extended authorization deadline expired")
            launcher = plan.get("launcher_python_path")
            if not isinstance(launcher, str) or not Path(launcher).is_absolute():
                raise mr.RuntimeSourceError("extended launcher path is invalid")
            _validate_worker(state, run_path, registered_path, launcher, proc_root)
            monitor_phase = MONITOR_PHASES.get(phase)
            if monitor_phase != state.get("monitor_phase"):
                raise mr.RuntimeSourceError("extended lifecycle and monitor phase differ")
            identity = _candidate_identity(state)
            candidate_active = phase in ACTIVE_PHASES or (
                phase == "candidate_start" and identity is not None
            )
            if candidate_active and identity is None:
                raise mr.RuntimeSourceError("extended candidate cgroup is not bound")
            _, memory_sha = mr._latest_memory(
                run_fd, observed,
                floor_gib=profile["minimum_mem_available_gib"],
                expected_phase=monitor_phase,
                paging_policy=prior["paging_policy"],
                candidate_identity=identity if candidate_active else None,
                memory_limit_bytes=(spec.docker_memory_limit_bytes if spec is not None
                                    else prior["docker_memory_limit_bytes"]),
                spec=spec, maximum_bytes=profile["max_raw_memory_bytes"],
                maximum_rows=profile["max_memory_rows"],
                maximum_age_seconds=10,
                extended_serving_profile=profile,
            )
            if candidate_active:
                mr._validate_initial(state)
                if phase in {"probes", "evaluation", "evaluation_complete_pending_restoration"}:
                    mr._validate_ready_quiescence(
                        state, prior, started=started, updated=updated
                    )
                mode, residents, nara = "candidate_research", "stopped", "paused"
            else:
                mode, residents, nara = "transitioning", "unknown", "unknown"
        source_sha = mr._composite_sha256(
            state=mr._sha256(state_raw), plan=mr._sha256(plan_raw),
            prior=mr._sha256(prior_raw), window=window.source_sha256,
            contract=contract_sha, memory=memory_sha or "",
            terminal=terminal_sha or "", variant=spec.identity_sha256(),
            source_bundle=mr._canonical_sha256(source_snapshot),
        )
        if mr._read_fd(
            run_fd, "state.json", maximum=mr.MAX_STATE_BYTES,
            label="extended state recheck",
        ) != state_raw:
            raise mr.RuntimeSourceError("extended state changed during admission")
        variant = mr._variant_projection(
            spec, image_observed=memory_sha is not None and candidate_active
            if phase not in TERMINAL_PHASES else False,
        )
        if variant is not None:
            variant["configured_max_context_tokens"] = spec.max_model_len
            variant["configured_mtp_speculative_tokens"] = (
                getattr(spec, "mtp_speculative_tokens", 0)
            )
            variant["configured_kv_cache_memory_bytes"] = (
                spec.kv_cache_memory_bytes
            )
        return {
            "schema_version": mr.SCHEMA_VERSION, "observed_at": observed_at,
            "mode": mode, "mode_source": "followon_evaluation_state",
            "mode_source_sha256": source_sha,
            "resident_services_expected": residents, "nara_service_expected": nara,
            "run_id": run_id, "phase": phase,
            "candidate_variant": variant,
            "source_error": None,
        }
    except (OSError, ImportError, mr.RuntimeSourceError, ew.EvaluationWindowError,
            ValueError, TypeError, AttributeError, UnicodeError, KeyError):
        return mr._unknown(observed_at, "follow-on runtime state is absent, stale, or untrusted")
    finally:
        if run_fd is not None:
            os.close(run_fd)


def maybe_project_followon(
    qualification_root: Path,
    original_evaluation_root: Path,
    followon_root: Path,
    *,
    proc_root: Path,
    boot_id_path: Path,
    observed: datetime,
) -> dict[str, Any] | None:
    """A newer invalid Flash or resident state blocks older-controller fallback."""
    try:
        from .model_runtime_extended import _latest_slot_mtime as old_slot
        from .model_runtime_resident_followon import (
            latest_slot_mtime as resident_slot,
        )
        from .model_runtime_resident_followon import (
            project_resident_runtime,
        )

        current = old_slot(qualification_root, extended=False)
        original = old_slot(original_evaluation_root, extended=True)
        flash = _latest_slot_mtime(followon_root)
        resident = resident_slot(followon_root)
        followon = max((item for item in (flash, resident) if item is not None),
                       default=None)
        older = max((item for item in (current, original) if item is not None),
                    default=None)
        if followon is None or (older is not None and followon < older):
            return None
        if ((older is not None and followon == older)
                or (flash is not None and resident is not None
                    and flash == resident)):
            return mr._unknown(observed.isoformat(), "runtime states have ambiguous order")
        projected = (
            project_resident_runtime(
                followon_root, proc_root=proc_root,
                boot_id_path=boot_id_path, observed=observed,
            ) if resident is not None and (flash is None or resident > flash)
            else project_followon_runtime(
                followon_root, proc_root=proc_root,
                boot_id_path=boot_id_path, observed=observed,
            )
        )
        current_after = old_slot(qualification_root, extended=False)
        original_after = old_slot(original_evaluation_root, extended=True)
        flash_after = _latest_slot_mtime(followon_root)
        resident_after = resident_slot(followon_root)
        followon_after = max((item for item in (flash_after, resident_after)
                              if item is not None), default=None)
        older_after = max((item for item in (current_after, original_after)
                           if item is not None), default=None)
        if (
            followon_after is None
            or (older_after is not None and followon_after <= older_after)
            or followon_after != followon
            or flash_after != flash or resident_after != resident
        ):
            return mr._unknown(observed.isoformat(), "runtime state order changed during admission")
        return projected
    except mr.RuntimeSourceError:
        return mr._unknown(observed.isoformat(), "runtime state order is unavailable")


__all__ = ["FOLLOWON_RUN_ROOT", "maybe_project_followon"]
