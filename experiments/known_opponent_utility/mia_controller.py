"""Prospective Mia arm of the frozen known-opponent utility pilot.

This wrapper uses the reviewed Flash lifecycle, unchanged pilot and unchanged
independent game grader. It records a separate model arm, not a benchmark run.
No model call occurs before the qualified parent and live container gate pass.
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

from bench.flash_next_ab import lab_window as lifecycle
from bench.flash_next_ab import qualification as q
from bench.flash_next_ab import transport
from bench.flash_next_ab.followon_qualification_admission import (
    _validate_profile_canary,
)
from bench.flash_next_ab.followon_v5_parent import load_parent
from experiments.known_opponent_utility import admission, pilot
from orchestrator.weekly_upgrade_trial import canonical_root, resource_lease

CODE_ROOT = Path(__file__).resolve().parents[2]
REGISTERED_ROOT = Path("/home/decross1/projects/a_bgt_rsi_worktrees/lab-mia-known-opponent-20260915")
ARTIFACT_ROOT = Path("/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-15/lab-eight-hour")
OUTPUT_ROOT = ARTIFACT_ROOT / "known-opponent-utility-mia"
GEMMA_ROOT = ARTIFACT_ROOT / "known-opponent-utility/qfn-followon-known-opponent-lab8h-a"
GEMMA_ADMISSION_SHA256 = "824403c23c6969eeb1e2cbc11c4ec2c5222cf7ff2123cbc867427868042bcee1"
GEMMA_MANIFEST_SHA256 = "b68d84921eded4310a78b89d35d24bd6056885e051ad4dc3328b704c0ca00d89"
GEMMA_RUN_SHA256 = "70763bd0c9a685722a3d01a5412abfbed1bebcf2eb0c7707578709115521c4be"
GEMMA_ARTIFACT_SHA256 = "c63860e164ed838e0b829de106bfe5ed5f8cd82a7db391c752954c69862ee0af"
PARENT_PATH = Path(
    "/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-14/"
    "qwen-flash-next-research/evaluation/followon-qualified-parents/"
    "qfn-mia-mtp3-red47k-20260915-a.json"
)
WINDOW_SCHEMA = "known-opponent-mia-study-window/v1"
SUPERVISION_SCHEMA = "known-opponent-mia-study-supervision/v1"
ADMISSION_SCHEMA = "known-opponent-mia-study-admission/v1"
WINDOW_ID = re.compile(r"qfn-followon-known-opponent-mia-[a-z0-9][a-z0-9._-]{0,47}\Z")
WALL_S = 3000
PILOT_S = 900
RESTORE_S = 600
PARENT_RECOVERY_S = 600
POLICY = {"temperature": 0.0, "top_p": 1.0, "top_k": 64, "enable_thinking": False}
PROFILE_ID = "mia-925d7be6-mtp3-reduced47k-v2opt-v1"
PROFILE_SHA256 = "e71d3134f407cad3c288c21f9485c27352676dbb7de647c5b567777256702a50"
PROFILE_IMAGE_ID = "sha256:29eab5a29b765eef8b6405bbe0f2d385fc1e7b5e3c7ae18ae70382a68a0a2201"
PROFILE_RUNTIME_SHA256 = "cd2568e650bfd9fab72f573e81db15eb5f10c2822999b578b0e570615978931b"
PROFILE_ARTIFACT_SHA256 = "a40ce50173dd3aff54da88503894967e5248bbb927f9e4a91eff5a6a7270c168"
EXTRA_SOURCE_FILES = (
    "experiments/known_opponent_utility/mia_controller.py",
    "experiments/known_opponent_utility/pilot.py",
    "experiments/known_opponent_utility/admission.py",
    "experiments/known_opponent_utility/manifest.schema.json",
    "experiments/PREREG_known_opponent_utility_response_2026-09-15.md",
    "experiments/PREREG_known_opponent_utility_mia_2026-09-15.md",
    "bench/agentic_game_theory/optimal_control.py",
    "bench/agentic_game_theory/calibration.py",
)


class MiaStudyError(ValueError):
    pass


def _must(value: bool, reason: str) -> None:
    if not value:
        raise MiaStudyError(reason)


def _raw(path: Path, limit: int = 2_000_000) -> bytes:
    _must(path.is_file() and not path.is_symlink() and path.resolve() == path
          and path.stat().st_size <= limit, "study evidence is missing or redirected")
    return path.read_bytes()


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _new(path: Path, value: dict) -> None:
    raw = pilot._raw_json(value) + b"\n"
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _sources() -> dict:
    source = lifecycle._source_bundle()
    for name in EXTRA_SOURCE_FILES:
        path = CODE_ROOT / name
        source[name] = {"path": str(path), "sha256": _sha(_raw(path))}
    return dict(sorted(source.items()))


def _identity(pid: int) -> dict:
    return lifecycle._process_identity(pid)


def _endpoint(parent) -> transport.LocalEndpoint:
    spec = parent.spec
    endpoint = transport.LocalEndpoint(
        spec.endpoint_name, "http://127.0.0.1:8012", spec.served_name,
        spec.model_artifact_sha256(),
    )
    endpoint.validate()
    _must(parent.qualification_summary["endpoint_name"] == endpoint.name
          and parent.qualification_summary["served_model"] == endpoint.served_model
          and parent.qualification_summary["model_artifact_sha256"] == endpoint.artifact_sha256,
          "qualified parent is not the exact Mia endpoint")
    return endpoint


def _parent_literal(parent) -> None:
    document = parent.document
    _must(document["candidate_spec_id"] == PROFILE_ID
          and document["candidate_spec_sha256"] == PROFILE_SHA256
          and parent.spec.identity_sha256() == PROFILE_SHA256
          and parent.spec.image_id == PROFILE_IMAGE_ID
          and document["runtime_sha256"] == PROFILE_RUNTIME_SHA256
          and document["model_artifact_sha256"] == PROFILE_ARTIFACT_SHA256
          and document["max_model_len"] == 32768
          and document["mtp_speculative_tokens"] == 3
          and parent.qualification_summary["admission_eligible"] is True
          and parent.qualification_summary["status"] == "passed",
          "Mia study requires the literal qualified reduced MTP3 profile")


def _gemma_reference() -> tuple[dict, dict]:
    admission_path = GEMMA_ROOT / "admission.json"
    manifest_path = GEMMA_ROOT / "manifest.snapshot.json"
    run_path = GEMMA_ROOT / "pilot/run.json"
    window_path = GEMMA_ROOT / "window.json"
    result_path = GEMMA_ROOT / "result.json"
    supervision_path = GEMMA_ROOT / "supervision.json"
    admission_raw, manifest_raw, run_raw = (
        _raw(admission_path), _raw(manifest_path), _raw(run_path)
    )
    _must(_sha(admission_raw) == GEMMA_ADMISSION_SHA256
          and _sha(manifest_raw) == GEMMA_MANIFEST_SHA256
          and _sha(run_raw) == GEMMA_RUN_SHA256,
          "actual admitted Gemma pilot source bytes differ")
    receipt = json.loads(admission_raw)
    gemma = json.loads(manifest_raw)
    _must(receipt.get("schema") == "known-opponent-resident-study-admission/v1"
          and receipt.get("pilot_validation", {}).get("admission_eligible") is True
          and receipt["pilot_validation"].get("run_sha256") == GEMMA_RUN_SHA256
          and receipt.get("pilot_run_sha256") == GEMMA_RUN_SHA256
          and receipt.get("window_sha256") == _sha(_raw(window_path))
          and receipt.get("result_sha256") == _sha(_raw(result_path))
          and receipt.get("supervision_sha256") == _sha(_raw(supervision_path))
          and gemma.get("endpoint", {}).get("name") == "resident_gemma"
          and gemma["endpoint"].get("served_model") == "gemma-4-26b-a4b"
          and gemma["endpoint"].get("artifact_sha256") == GEMMA_ARTIFACT_SHA256,
          "Gemma comparator is not its admitted immutable pilot")
    return {
        "admission_path": str(admission_path), "admission_sha256": GEMMA_ADMISSION_SHA256,
        "manifest_path": str(manifest_path), "manifest_sha256": GEMMA_MANIFEST_SHA256,
        "run_path": str(run_path), "run_sha256": GEMMA_RUN_SHA256,
        "window_path": str(window_path), "window_sha256": receipt["window_sha256"],
        "result_path": str(result_path), "result_sha256": receipt["result_sha256"],
        "supervision_path": str(supervision_path),
        "supervision_sha256": receipt["supervision_sha256"],
    }, gemma


def _matched(manifest: dict, gemma: dict) -> None:
    fields = ("schedule", "tasks", "policy", "seed_base", "max_tokens",
              "per_call_timeout_s", "max_window_s", "max_calls", "horizon")
    _must(all(manifest.get(key) == gemma.get(key) for key in fields)
          and manifest["policy"] == POLICY
          and manifest["max_calls"] == 108
          and manifest["max_window_s"] == PILOT_S,
          "Mia game fixture, sampling or call ceiling differs from Gemma")


def prepare(*, window_id: str, seed: int = 301, per_call_timeout_s: float = 30.0,
            max_tokens: int = 64) -> Path:
    """Freeze the model, original fixture, source and supervised window once."""
    _must(CODE_ROOT == REGISTERED_ROOT and WINDOW_ID.fullmatch(window_id) is not None,
          "Mia study root or ID is not registered")
    parent = load_parent(PARENT_PATH)
    _parent_literal(parent)
    endpoint = _endpoint(parent)
    manifest = pilot.freeze_manifest(
        source_root=CODE_ROOT, endpoint=endpoint,
        registered_admission=parent.qualification_summary,
        policy=POLICY, seed=seed, max_tokens=max_tokens,
        per_call_timeout_s=per_call_timeout_s,
    )
    gemma_ref, gemma = _gemma_reference()
    _matched(manifest, gemma)
    _must(PILOT_S + 1500 + RESTORE_S == WALL_S,
          "Mia startup, pilot and restoration budget changed")
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    _must(OUTPUT_ROOT.resolve() == OUTPUT_ROOT, "Mia output root is redirected")
    output = OUTPUT_ROOT / window_id
    output.mkdir(mode=0o700)
    _new(output / "manifest.snapshot.json", manifest)
    window = {
        "schema": WINDOW_SCHEMA, "window_id": window_id,
        "created_at": q.utc_now(), "code_root": str(CODE_ROOT),
        "output_dir": str(output), "cohort": "flash",
        "manifest": {"path": str(output / "manifest.snapshot.json"),
                     "sha256": _sha(_raw(output / "manifest.snapshot.json"))},
        "qualified_parent": {"path": str(PARENT_PATH), "sha256": parent.source_sha256,
                             "candidate_spec_id": parent.spec.spec_id,
                             "candidate_spec_sha256": parent.spec.identity_sha256()},
        "matched_gemma": gemma_ref,
        "controller_sources": _sources(), "endpoint": endpoint.__dict__,
        "policy": POLICY, "wall_s": WALL_S, "pilot_s": PILOT_S,
        "restoration_reserve_s": RESTORE_S, "minimum_mem_available_gib": 20,
        "comparison_eligible": False, "promotion_authorized": False,
        "trading_claim_authorized": False,
    }
    _new(output / "window.json", window)
    return output / "window.json"


def load_window(path: Path) -> tuple[dict, dict, object]:
    """Reconstruct the registered snapshot before any service mutation."""
    _must(CODE_ROOT == REGISTERED_ROOT, "Mia controller is outside its registered root")
    path = path.absolute()
    window = json.loads(_raw(path))
    _must(set(window) == {
        "schema", "window_id", "created_at", "code_root", "output_dir", "cohort",
        "manifest", "qualified_parent", "matched_gemma", "controller_sources",
        "endpoint", "policy", "wall_s", "pilot_s", "restoration_reserve_s",
        "minimum_mem_available_gib", "comparison_eligible", "promotion_authorized",
        "trading_claim_authorized",
    } and window["schema"] == WINDOW_SCHEMA
       and WINDOW_ID.fullmatch(window["window_id"]) is not None,
          "Mia study window schema or ID differs")
    output = OUTPUT_ROOT / window["window_id"]
    _must(path == output / "window.json" and output.resolve() == output
          and window["output_dir"] == str(output) and window["code_root"] == str(CODE_ROOT)
          and window["cohort"] == "flash" and window["controller_sources"] == _sources()
          and window["wall_s"] == WALL_S and window["pilot_s"] == PILOT_S
          and window["restoration_reserve_s"] == RESTORE_S
          and window["minimum_mem_available_gib"] == 20
          and window["comparison_eligible"] is False
          and window["promotion_authorized"] is False
          and window["trading_claim_authorized"] is False,
          "Mia window source, safety budget or authority differs")
    parent = load_parent(PARENT_PATH)
    _parent_literal(parent)
    _must(window["qualified_parent"] == {
        "path": str(PARENT_PATH), "sha256": parent.source_sha256,
        "candidate_spec_id": parent.spec.spec_id,
        "candidate_spec_sha256": parent.spec.identity_sha256(),
    }, "Mia qualified parent differs from frozen window")
    gemma_ref, gemma = _gemma_reference()
    _must(window["matched_gemma"] == gemma_ref,
          "admitted Gemma comparator bytes changed")
    manifest_path = output / "manifest.snapshot.json"
    _must(window["manifest"] == {"path": str(manifest_path),
                                 "sha256": _sha(_raw(manifest_path))},
          "Mia study manifest bytes or path changed")
    manifest = json.loads(_raw(manifest_path))
    pilot._check_manifest(manifest)
    _matched(manifest, gemma)
    _must(window["endpoint"] == _endpoint(parent).__dict__
          and manifest["endpoint"] == window["endpoint"]
          and manifest["registered_admission"] == parent.qualification_summary
          and window["policy"] == POLICY,
          "Mia model, admission or sampling differs")
    return window, manifest, parent


class _DeadlineCancel:
    def __init__(self, original, cutoff: float):
        self.original, self.cutoff = original, cutoff

    def is_set(self) -> bool:
        return self.original.is_set() or time.monotonic() >= self.cutoff


def _pilot_executor(window: dict, parent, output: Path, monitor, state: dict,
                    cutoff: float) -> dict:
    manifest = json.loads(_raw(Path(window["manifest"]["path"])))
    spec = parent.spec
    cancel = _DeadlineCancel(monitor.cancel_event, cutoff)

    def live() -> dict:
        monitor.check()
        _must(not cancel.is_set() and state.get("phase") == "evaluation",
              "Mia pilot left its finite evaluation window")
        candidate = q._inspect_container(monitor.ops, spec.container_name)
        _must(candidate is not None and candidate["id"] == state["candidate_id"]
              and candidate["image"] == spec.image_id and candidate["running"]
              and not candidate["oom_killed"] and candidate["restart_count"] == 0
              and q._service_state(monitor.ops)["ActiveState"] == "inactive"
              and state.get("canaries", {}).get("status") == "passed",
              "Mia candidate, Nara or canary differs from live admission")
        for resident in state["initial"]["residents"]:
            observed = q._inspect_container(monitor.ops, resident["id"])
            _must(observed is not None and not observed["running"],
                  "resident restarted inside Mia pilot")
        return candidate

    state["phase"] = "evaluation"
    q._atomic_write(output / "state.json", state)
    candidate = live()
    proof = {
        "schema": "known-opponent-mia-ready-proof/v1",
        "window_sha256": _sha(_raw(output / "window.json")),
        "candidate_id": candidate["id"], "candidate_image": candidate["image"],
        "readiness_sha256": _sha(_raw(output / "readiness.json")),
        "probes_sha256": _sha(_raw(output / "probes.json")),
        "canaries": state["canaries"], "qualified_parent_sha256": parent.source_sha256,
    }
    _new(output / "admission-ready-proof.json", proof)
    state["pilot_ready_proof_sha256"] = _sha(_raw(output / "admission-ready-proof.json"))
    q._atomic_write(output / "state.json", state)

    def invoke(endpoint, messages, *, policy, max_tokens, timeout_s, seed,
               cancel_event):
        live()
        remaining = cutoff - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Mia pilot work cutoff")
        return transport.complete(
            endpoint, messages, policy=policy, max_tokens=max_tokens,
            timeout_s=min(timeout_s, remaining), seed=seed,
            cancel_event=cancel_event,
        )

    run = pilot.run_pilot(
        manifest, output=output / "evaluation",
        admission_gate=lambda: parent.qualification_summary if live() else None,
        safety_check=live, cancel_event=cancel, invoke_fn=invoke,
    )
    full_schedule = (run["status"] in {"complete", "completed_schedule_with_unknown_actions"}
                     and run["completed_cell_records"] == 12 and run["failure"] is None)
    return {"status": "complete" if full_schedule else "aborted",
            "pilot_status": run["status"], "recorded_cells": run["completed_cell_records"]}


def worker(path: Path) -> dict:
    window, _manifest, parent = load_window(path)
    output = Path(window["output_dir"])
    return lifecycle._flash(
        window, parent, output, time.monotonic() + WALL_S,
        executor=_pilot_executor,
    )


def supervise(path: Path) -> int:
    window, _manifest, parent = load_window(path)
    output = Path(window["output_dir"])
    _must(not (output / "supervision.json").exists()
          and not (output / "supervision-start.json").exists(),
          "Mia pilot window has already been supervised")
    _new(output / "supervision-reservation.json", {
        "reserved_at": q.utc_now(), "window_sha256": _sha(_raw(path)),
        **_identity(os.getpid()),
    })
    command = [sys.executable, "-m", "experiments.known_opponent_utility.mia_controller",
               "--worker", "--window", str(path)]
    started = time.monotonic()
    with (output / "controller.log").open("xb") as log:
        child = subprocess.Popen(command, cwd=CODE_ROOT, stdout=log,
                                 stderr=subprocess.STDOUT, start_new_session=True)
        terminated, interrupted = False, None
        try:
            _new(output / "supervision-start.json", {
                "pid": child.pid, "started_at": q.utc_now(), "argv": command,
                "window_sha256": _sha(_raw(path)), **_identity(child.pid),
            })
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
        except BaseException as exc:  # noqa: BLE001 - interrupted parent must recover
            interrupted = type(exc).__name__
            if child.poll() is None:
                child.send_signal(signal.SIGTERM)
                terminated = True
                try:
                    child.wait(timeout=RESTORE_S)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait(timeout=30)
    result_path = output / "result.json"
    try:
        result = json.loads(_raw(result_path)) if result_path.exists() else {}
    except (MiaStudyError, ValueError, UnicodeError):
        result = {}
    recovery = None
    state_path = output / "state.json"
    try:
        state = json.loads(_raw(state_path)) if state_path.exists() else {}
    except (MiaStudyError, ValueError, UnicodeError):
        state = {}
    restored = (result.get("restoration", {}).get("status") == "verified"
                and state.get("restoration") == result["restoration"]
                and state.get("phase") == "complete")
    if not restored:
        if state.get("window_sha256") != _sha(_raw(path)):
            recovery = {"status": "unknown", "failure_code": "recovery_state_unavailable_or_drifted"}
        else:
            try:
                with resource_lease(canonical_root(CODE_ROOT)):
                    recovery = q.restore_exact(
                        q.HostOps(), state, deadline=time.monotonic() + PARENT_RECOVERY_S,
                        spec=parent.spec, diagnostic_path=output / "recovery-candidate.log",
                    )
            except BaseException as exc:  # noqa: BLE001 - unknown host restore is not admission
                recovery = {"status": "unknown", "failure_code": "emergency_restoration_failed",
                            "error_type": type(exc).__name__}
    _new(output / "supervision.json", {
        "schema": SUPERVISION_SCHEMA, "window_sha256": _sha(_raw(path)),
        "returncode": child.returncode, "elapsed_s": time.monotonic() - started,
        "terminated_at_cutoff": terminated, "interrupted": interrupted,
        "emergency_restoration": recovery, "finished_at": q.utc_now(),
    })
    return 0 if (child.returncode == 0 and result.get("status") == "complete"
                 and interrupted is None and not terminated) else 1


def _memory(output: Path, result: dict, state: dict, parent) -> dict:
    raw = _raw(output / "memory.jsonl", 8_000_000)
    rows = [json.loads(line) for line in raw.splitlines()]
    arm = [row for row in rows if row.get("schema") == "qwen-flash-next-cgroup-bind/v1"]
    _must(len(arm) == 1, "Mia pilot lacks one exact candidate cgroup arm receipt")
    bound = arm[0]
    bound_inspect, bound_cgroup = bound.get("container_inspect"), bound.get("cgroup")
    _must(bound.get("candidate_id") == state.get("candidate_id")
          and bound.get("candidate_spec") == {
              "id": PROFILE_ID, "spec_sha256": PROFILE_SHA256}
          and isinstance(bound_inspect, dict)
          and bound_inspect.get("id") == state.get("candidate_id")
          and bound_inspect.get("image") == PROFILE_IMAGE_ID
          and bound_inspect.get("pid") == state.get("candidate_cgroup_pid")
          and bound_inspect.get("memory_limit_bytes")
              == parent.spec.docker_memory_limit_bytes
          and bound_inspect.get("memory_swap_total_bytes")
              == parent.spec.docker_memory_limit_bytes
          and bound_inspect.get("running") is True
          and bound_inspect.get("oom_killed") is False
          and bound_inspect.get("restart_count") == 0
          and isinstance(bound_cgroup, dict)
          and bound_cgroup.get("path") == state.get("candidate_cgroup_path")
          and bound_cgroup.get("process_start_ticks") == state.get("candidate_cgroup_start_ticks")
          and bound_cgroup.get("memory_max_bytes")
              == parent.spec.docker_memory_limit_bytes
          and bound_cgroup.get("memory_swap_max_bytes") == 0
          and bound_cgroup.get("memory_swap_current_bytes") == 0
          and bound_cgroup.get("memory_events_oom") == 0
          and bound_cgroup.get("memory_events_oom_kill") == 0,
          "Mia candidate cgroup arm receipt differs from durable worker identity")
    samples = [row for row in rows if "mem_available_gib" in row]
    _must(samples and len(samples) == result.get("memory_samples")
          and len(rows) <= 6000, "Mia monitor sample count differs")
    values = [row["mem_available_gib"] for row in samples]
    _must(all(type(value) in {int, float} and math.isfinite(value) and value >= 20
              for value in values)
          and min(values) == result.get("minimum_mem_available_gib"),
          "Mia raw memory reserve differs from terminal result")
    _must(all(type(row.get("sample_gap_seconds")) in {int, float}
              and 0 <= row["sample_gap_seconds"] <= 10
              for row in samples), "Mia monitor had a blind sample gap")
    evaluation = [row for row in samples if row.get("monitor_phase") == "evaluation"]
    _must(evaluation, "Mia pilot has no armed evaluation memory samples")
    for row in evaluation:
        candidate = row.get("candidate")
        cgroup = candidate.get("cgroup") if isinstance(candidate, dict) else None
        _must(isinstance(candidate, dict) and candidate.get("armed") is True
              and candidate.get("id") == state.get("candidate_id")
              and candidate.get("image") == parent.spec.image_id
              and candidate.get("pid") == state.get("candidate_cgroup_pid")
              and candidate.get("memory_limit_bytes")
                  == parent.spec.docker_memory_limit_bytes
              and candidate.get("memory_swap_total_bytes")
                  == parent.spec.docker_memory_limit_bytes
              and candidate.get("oom_killed") is False
              and candidate.get("restart_count") == 0
              and isinstance(cgroup, dict)
              and cgroup.get("path") == state.get("candidate_cgroup_path")
              and cgroup.get("process_start_ticks") == state.get("candidate_cgroup_start_ticks")
              and cgroup.get("memory_max_bytes")
                  == parent.spec.docker_memory_limit_bytes
              and cgroup.get("memory_swap_max_bytes") == 0
              and cgroup.get("memory_swap_current_bytes") == 0
              and cgroup.get("memory_events_oom") == 0
              and cgroup.get("memory_events_oom_kill") == 0
              and row.get("host_swap_5s_bytes") == 0
              and row.get("host_swap_60s_bytes") == 0,
              "Mia evaluation cgroup, OOM, paging or candidate identity drifted")
    return {"raw_sha256": _sha(raw), "samples": len(samples),
            "evaluation_samples": len(evaluation),
            "minimum_mem_available_gib": min(values)}


def validate_completed(path: Path) -> dict:
    """Admit only the closed restored window and independently replayed game."""
    window, manifest, parent = load_window(path)
    output = Path(window["output_dir"])
    result_raw = _raw(output / "result.json")
    state_raw = _raw(output / "state.json")
    supervision_raw = _raw(output / "supervision.json")
    start_raw = _raw(output / "supervision-start.json")
    reservation_raw = _raw(output / "supervision-reservation.json")
    result, state, supervision = (json.loads(value) for value in
                                  (result_raw, state_raw, supervision_raw))
    start, reservation = json.loads(start_raw), json.loads(reservation_raw)
    window_sha = _sha(_raw(path))
    _must(result.get("schema") == "lab-model-window-result/v1"
          and result.get("cohort") == "flash" and result.get("status") == "complete"
          and result.get("window_id") == window["window_id"]
          and result.get("window_sha256") == window_sha
          and result.get("error") is None
          and result.get("restoration", {}).get("status") == "verified"
          and result["restoration"].get("errors") == []
          and result["restoration"].get("sentinel_retained") is False
          and state.get("phase") == "complete"
          and state.get("window_sha256") == window_sha
          and state.get("restoration") == result["restoration"]
          and state.get("canaries", {}).get("status") == "passed"
          and supervision.get("schema") == SUPERVISION_SCHEMA
          and supervision.get("window_sha256") == window_sha
          and supervision.get("returncode") == 0
          and supervision.get("interrupted") is None
          and supervision.get("terminated_at_cutoff") is False
          and supervision.get("emergency_restoration") is None,
          "Mia pilot lacks exact terminal supervision/restoration/canary proof")
    argv = start.get("argv")
    _must(reservation.get("window_sha256") == window_sha
          and start.get("window_sha256") == window_sha
          and type(start.get("pid")) is int
          and start["pid"] == start.get("worker_pid") == state.get("worker_pid")
          and start.get("worker_start_ticks") == state.get("worker_start_ticks")
          and start.get("boot_id") == state.get("boot_id")
          and isinstance(argv, list) and len(argv) == 6
          and argv[0] == sys.executable and Path(argv[0]).is_absolute()
          and argv[1:] == ["-m", "experiments.known_opponent_utility.mia_controller",
                           "--worker", "--window", str(path)],
          "Mia worker PID, start ticks or supervised command differs")
    _must(type(state.get("candidate_cgroup_pid")) is int
          and type(state.get("candidate_cgroup_start_ticks")) is int
          and isinstance(state.get("candidate_cgroup_path"), str)
          and state["candidate_cgroup_path"].startswith("/system.slice/docker-"),
          "Mia worker has no durable cgroup process identity")
    proof_raw = _raw(output / "admission-ready-proof.json")
    proof = json.loads(proof_raw)
    _must(state.get("pilot_ready_proof_sha256") == _sha(proof_raw)
          and proof.get("schema") == "known-opponent-mia-ready-proof/v1"
          and proof.get("window_sha256") == window_sha
          and proof.get("candidate_id") == state.get("candidate_id")
          and proof.get("candidate_image") == parent.spec.image_id
          and proof.get("qualified_parent_sha256") == parent.source_sha256
          and proof.get("canaries") == state["canaries"]
          and proof.get("readiness_sha256") == _sha(_raw(output / "readiness.json"))
          and proof.get("probes_sha256") == _sha(_raw(output / "probes.json")),
          "Mia ready proof is not its admitted candidate/probes")
    canary_raw = _raw(output / "profile-canary.json")
    attempts_raw = _raw(output / "profile-canary-attempts.json")
    canary = json.loads(canary_raw)
    _must(state["canaries"] == canary,
          "Mia boot-specific canary summary differs from worker state")
    _validate_profile_canary(output, {
        "profile_canary_status": canary["status"],
        "profile_canary_sha256": _sha(canary_raw),
        "profile_canary_attempts_sha256": _sha(attempts_raw),
        "profile_canary_protocol_sha256": canary["protocol_sha256"],
        "profile_canary_suite": canary["suite"],
        "profile_canary_attempt_count": canary["attempt_count"],
        "profile_canary_timeout_seconds": parent.spec.profile_canary_timeout_seconds,
        "started_at": state["started_at"],
        "restoration": result["restoration"],
    }, parent.spec)
    run_raw = _raw(output / "evaluation/run.json")
    _must(result.get("evaluation_run_sha256") == _sha(run_raw),
          "Mia pilot run bytes differ from terminal result")
    replay = admission.validate_pilot(output / "evaluation")
    _must(replay["admission_eligible"] is True
          and replay["manifest_sha256"] == manifest["manifest_sha256"]
          and replay["run_sha256"] == _sha(run_raw)
          and replay["recorded_episodes"] == 12,
          "Mia pilot schedule or raw-response grade replay is incomplete")
    memory = _memory(output, result, state, parent)
    return {
        "schema": ADMISSION_SCHEMA, "window_id": window["window_id"],
        "window_sha256": window_sha, "result_sha256": _sha(result_raw),
        "state_sha256": _sha(state_raw), "supervision_sha256": _sha(supervision_raw),
        "supervision_start_sha256": _sha(start_raw),
        "supervision_reservation_sha256": _sha(reservation_raw),
        "ready_proof_sha256": _sha(proof_raw),
        "profile_canary_sha256": _sha(canary_raw),
        "profile_canary_attempts_sha256": _sha(attempts_raw),
        "qualified_parent_sha256": parent.source_sha256,
        "matched_gemma_admission_sha256": window["matched_gemma"]["admission_sha256"],
        "memory": memory, "pilot_run_sha256": _sha(run_raw),
        "pilot_validation": replay, "comparison_eligible": False,
        "promotion_authorized": False, "trading_claim_authorized": False,
    }


def publish_admission(path: Path) -> Path:
    receipt = validate_completed(path)
    output = Path(load_window(path)[0]["output_dir"])
    destination = output / "admission.json"
    _new(destination, receipt)
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    for name in ("prepare", "run", "worker", "validate"):
        mode.add_argument("--" + name, action="store_true")
    parser.add_argument("--window", type=Path)
    parser.add_argument("--window-id")
    parser.add_argument("--seed", type=int, default=301)
    parser.add_argument("--per-call-timeout-s", type=float, default=30.0)
    parser.add_argument("--max-tokens", type=int, default=64)
    args = parser.parse_args(argv)
    if args.prepare:
        print(prepare(window_id=args.window_id, seed=args.seed,
                      per_call_timeout_s=args.per_call_timeout_s,
                      max_tokens=args.max_tokens))
        return 0
    if args.validate:
        print(publish_admission(args.window.absolute()))
        return 0
    _must(not os.environ.get("MOCK_LLM"), "live Mia pilot refuses MOCK_LLM")
    previous = q._signal_guard()
    try:
        if args.run:
            return supervise(args.window.absolute())
        result = worker(args.window.absolute())
        return 0 if result["status"] == "complete" else 1
    finally:
        q._restore_signals(previous)


if __name__ == "__main__":
    raise SystemExit(main())
