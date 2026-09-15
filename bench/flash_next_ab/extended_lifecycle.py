"""UNAPPLIED REVIEW DRAFT. Distinct supervised post-C0 Flash cohort.

This file is deliberately outside the imported worktree while C0 is active.
It requires the companion qualification.py draft to supply a frozen
evaluation_context and extended exact-ID recovery proof. No shell callbacks.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import time
from pathlib import Path

from . import qualification as q
from .candidate_registry import MIA, CandidateSpec
from .evaluation_window import (
    EXTENDED_SERVING_PROFILE,
    REGISTERED_CODE_ROOT,
    EvaluationWindowError,
    _evaluation_output,
    build_extended_evaluation_plan,
    extended_plan_sha256,
    frozen_controller_source_bundle,
    load_evaluation_window,
)
from .harness import _read_regular_file
from .mia_candidate_integration import read_mia_contract
from .qualification import (
    CONTRACT_PATH,
    PAGING_POLICY,
    RESEARCH_LEDGER,
    ROOT,
    _atomic_write,
    _atomic_write_bytes,
    _process_start_ticks,
    _read_bounded_run_json,
    _result_has_verified_restoration,
    _runtime_identity,
    _verified_contract_raw,
    execute_worker,
    launch_argv,
    load_contract,
    sha256,
    supervisor_emergency_restore,
    utc_now,
)


def _registered(
    eval_plan_path: Path, output: Path, *, must_be_absent: bool
) -> tuple[object, dict, dict, dict, bytes, CandidateSpec | None]:
    # The frozen loader checks the registered pair/source path, all receipt
    # hashes, prior fully restored C0, benchmark plan, and weekly/paid limits.
    window = load_evaluation_window(eval_plan_path, expected_cohort="flash")
    output = _evaluation_output(window.pair_id, output, must_be_absent=must_be_absent)
    extended_plan = build_extended_evaluation_plan(window, output)
    spec: CandidateSpec | None = (
        MIA if extended_plan["candidate_variant_id"] == MIA.spec_id else None
    )
    contract, contract_sha256, raw_contract = (
        read_mia_contract(MIA.contract_path, q) if spec is not None else
        (*load_contract(CONTRACT_PATH), b"")
    )
    prior_plan = window.qualification_plan
    runtime = _runtime_identity(spec)
    if (
        not isinstance(prior_plan, dict)
        or contract_sha256 != prior_plan.get("contract_sha256")
        or extended_plan["contract_sha256"] != contract_sha256
        or prior_plan.get("image_id") != runtime.image_id
        or prior_plan.get("model_path") != str(runtime.model_path)
        or prior_plan.get("model_artifact_sha256") != runtime.model_artifact_sha256
        or prior_plan.get("docker_create_argv") != launch_argv(spec)
        or extended_plan["candidate_spec_sha256"]
           != (spec.identity_sha256() if spec is not None else None)
        or contract["safety"]["paging_policy"]
           != (spec.paging_policy() if spec is not None else PAGING_POLICY)
        or extended_plan["paging_policy"] != contract["safety"]["paging_policy"]
        or extended_plan["extended_serving_profile"] != EXTENDED_SERVING_PROFILE
        or extended_plan["effective_invocation_deadline_seconds"] != 14_400
        or extended_plan["restoration_reserve_seconds"] != 600
        or extended_plan["research_usage_journal"] != str(RESEARCH_LEDGER)
        or extended_plan["controller_source_bundle_sha256"]
           != sha256(extended_plan["controller_source_bundle"])
        or extended_plan["controller_source_bundle"]
           != frozen_controller_source_bundle()
    ):
        raise EvaluationWindowError("extended runtime does not match the qualified C0")
    verified = _verified_contract_raw(contract, contract_sha256, spec=spec)
    if spec is not None and raw_contract != verified:
        raise EvaluationWindowError("Mia contract changed during extended planning")
    return window, extended_plan, prior_plan, contract, verified, spec


def _frozen_worker_inputs(output: Path, window, extended_plan, prior_plan,
                          contract_raw, contract, spec) -> None:
    # All snapshots are written by the supervisor before spawning the worker.
    if _read_bounded_run_json(output / "extended-plan.json", source="supervisor extended plan") != extended_plan:
        raise EvaluationWindowError("worker extended plan differs from supervisor")
    if _read_bounded_run_json(output / "prior-c0-plan.snapshot.json", source="prior C0 plan") != prior_plan:
        raise EvaluationWindowError("worker prior C0 plan differs from supervisor")
    if _read_bounded_run_json(output / "launch-contract.snapshot.json", source="contract snapshot") != contract:
        raise EvaluationWindowError("worker contract snapshot changed")
    raw, observed = _read_regular_file(
        output / "launch-contract.raw.json",
        label="registered contract raw bytes",
        max_bytes=2_000_000,
    )
    if observed != (output / "launch-contract.raw.json").absolute() or raw != contract_raw:
        raise EvaluationWindowError("worker raw registered contract changed")
    if extended_plan["window_plan_sha256"] != window.source_sha256:
        raise EvaluationWindowError("worker evaluation source changed")
    if _read_bounded_run_json(
        output / "controller-source-bundle.snapshot.json", source="controller source snapshot"
    ) != extended_plan["controller_source_bundle"]:
        raise EvaluationWindowError("worker source bundle differs from supervisor")
    if frozen_controller_source_bundle() != extended_plan["controller_source_bundle"]:
        raise EvaluationWindowError("registered controller code changed before worker mutation")


def _worker_command(window, output: Path, extended_plan: dict) -> list[str]:
    return [
        extended_plan["launcher_python_path"],
        "-m",
        "bench.flash_next_ab.extended_lifecycle",
        "--worker",
        "--eval-plan",
        str(window.source_path),
        "--output-dir",
        str(output),
    ]


def supervise(window, extended_plan: dict, prior_plan: dict, contract: dict,
              contract_raw: bytes, output: Path, spec: CandidateSpec | None) -> int:
    if ROOT != REGISTERED_CODE_ROOT:
        raise EvaluationWindowError("extended supervisor was imported outside the registered worktree")
    output.mkdir(mode=0o700)
    _atomic_write_bytes(output / "launch-contract.raw.json", contract_raw)
    _atomic_write(output / "launch-contract.snapshot.json", contract)
    _atomic_write(output / "prior-c0-plan.snapshot.json", prior_plan)
    _atomic_write(output / "extended-plan.json", extended_plan)
    _atomic_write(output / "controller-source-bundle.snapshot.json",
                  extended_plan["controller_source_bundle"])
    env = dict(os.environ)
    for forbidden in (
        "MOCK_LLM", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "VLLM_API_KEY", "WRAPPER_PROFILE_OVERRIDES"
    ):
        env.pop(forbidden, None)
    command = _worker_command(window, output, extended_plan)
    started = time.monotonic()
    hard_deadline = started + extended_plan["effective_invocation_deadline_seconds"]
    work_cutoff = hard_deadline - extended_plan["restoration_reserve_seconds"]
    terminated = False
    killed = False
    with (output / "controller.log").open("xb") as stream:
        worker = subprocess.Popen(
            command, cwd=ROOT, env=env, stdout=stream,
            stderr=subprocess.STDOUT, start_new_session=True,
        )
        try:
            worker_start_ticks = _process_start_ticks(worker.pid)
        except (OSError, q.QualificationError):
            worker_start_ticks = None
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        while worker.poll() is None and time.monotonic() < work_cutoff:
            time.sleep(min(1, max(0, work_cutoff - time.monotonic())))
        if worker.poll() is None:
            terminated = True
            try:
                os.killpg(worker.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        # Reserve at least 500 seconds for an exact-ID emergency recovery;
        # two incumbent cold boots have previously taken several minutes.
        force_cutoff = min(work_cutoff + 90, hard_deadline - 500)
        while worker.poll() is None and time.monotonic() < force_cutoff:
            time.sleep(min(1, max(0, force_cutoff - time.monotonic())))
        if worker.poll() is None:
            killed = True
            try:
                os.killpg(worker.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            worker.wait(timeout=min(5, max(0.1, hard_deadline - time.monotonic())))
        except subprocess.TimeoutExpired:
            killed = True
            try:
                os.killpg(worker.pid, signal.SIGKILL)
                worker.wait(timeout=5)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                pass

    # A missing/untrusted result leaves the exact stopped candidate sentinel
    # in place until supervisor recovery verifies original IDs/Nara/health.
    restored = _result_has_verified_restoration(
        output, prior_plan, spec=spec, extended_plan=extended_plan
    )
    recovery = None
    if not restored:
        if worker.poll() is None:
            recovery = {"status": "unknown", "error": "worker termination not verified"}
            _atomic_write(output / "supervisor-recovery.json", recovery)
        else:
            recovery = supervisor_emergency_restore(
                output, prior_plan, deadline=hard_deadline,
                spec=spec, extended_plan=extended_plan,
            )
    _atomic_write(
        output / "supervision.json",
        {
            "schema": "flash-next-extended-supervision/v1",
            "pair_id": window.pair_id,
            "window_plan_sha256": window.source_sha256,
            "extended_plan_sha256": extended_plan_sha256(extended_plan),
            "candidate_variant_id": extended_plan["candidate_variant_id"],
            "candidate_spec_sha256": extended_plan["candidate_spec_sha256"],
            "controller_source_bundle_sha256": extended_plan[
                "controller_source_bundle_sha256"
            ],
            "argv": command,
            "argv_sha256": sha256(command),
            "pid": worker.pid,
            "worker_start_ticks": worker_start_ticks,
            "boot_id": boot_id,
            "returncode": worker.returncode,
            "terminated_at_work_cutoff": terminated,
            "force_killed": killed,
            "emergency_recovery": recovery,
            "elapsed_seconds": max(0, time.monotonic() - started),
            "hard_deadline_seconds": extended_plan[
                "effective_invocation_deadline_seconds"
            ],
            "finished_at": utc_now(),
        },
    )
    return 0 if (worker.returncode == 0 and worker_start_ticks is not None
                 and not killed and not terminated
                 and recovery is None and restored) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--plan", action="store_true")
    modes.add_argument("--run", action="store_true")
    modes.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--eval-plan", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    window, extended_plan, prior_plan, contract, contract_raw, spec = _registered(
        args.eval_plan, args.output_dir, must_be_absent=args.run
    )
    output = Path(extended_plan["output_dir"])
    if args.plan:
        print(json.dumps(extended_plan, sort_keys=True, indent=2, allow_nan=False))
        return 0
    if args.run:
        return supervise(window, extended_plan, prior_plan, contract, contract_raw, output, spec)
    if not output.is_dir() or output.is_symlink():
        raise EvaluationWindowError("worker output is absent or redirected")
    _frozen_worker_inputs(output, window, extended_plan, prior_plan, contract_raw,
                          contract, spec)
    result = execute_worker(
        prior_plan, contract, output,
        evaluation_context=(window, extended_plan),
        spec=spec,
    )
    return 0 if result["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
