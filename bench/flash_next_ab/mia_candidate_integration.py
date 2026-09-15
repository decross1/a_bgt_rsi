"""Validate the fixed Mia v4 contract and build its immutable C0 plan.

This parser and planner have no subprocess, endpoint, lease, service or GPU
effects. The controller runs the selected candidate under its normal bounded
qualification and exact-restoration lifecycle; no production change is implied.
"""
from __future__ import annotations

import json
import os
import re
import stat
from pathlib import Path
from typing import Any

from .candidate_registry import MIA, CandidateSpec, select_candidate


class MiaRegistrationError(ValueError):
    pass


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise MiaRegistrationError(reason)


def validate_mia_contract(value: dict[str, Any], registered) -> dict[str, Any]:
    """Validate Mia v4 against the exact immutable spec and existing safety.

    `registered` is the current qualification module, supplied explicitly.
    Neither the contract nor a model response can replace a spec field.
    """
    try:
        spec = select_candidate(value)
    except (TypeError, ValueError) as exc:
        raise MiaRegistrationError(str(exc)) from exc
    _require(spec is MIA, "Mia v4 candidate was not selected")
    _require(set(value) == {
        "schema", "contract_id", "profile", "candidate", "image", "model",
        "runtime", "safety", "accounting", "probe_set",
    }, "Mia contract fields differ")
    _require(value["image"] == {"id": spec.image_id, "architecture": "arm64"},
             "Mia image differs")
    _require(value["model"] == spec.expected_model_section(), "Mia model differs")
    _require(value["runtime"] == spec.expected_runtime_section(), "Mia runtime differs")
    _require(value["probe_set"] == "flash-next-minimal-v1", "Mia probe set differs")

    safety = value["safety"]
    _require(isinstance(safety, dict), "Mia safety is not an object")
    _require(set(safety) == {
        "resident_containers", "nara_service", "min_mem_available_gib",
        "invocation_deadline_seconds", "readiness_deadline_seconds",
        "restoration_reserve_seconds", "setup_quiescence_seconds",
        "ready_quiescence_seconds", "memory_poll_seconds", "probe_timeout_seconds",
        "paging_policy",
    }, "Mia safety fields differ")
    residents = [{k: row[k] for k in ("name", "id", "image_id", "health_url")}
                 for row in registered.RESIDENTS]
    _require(safety["resident_containers"] == residents, "Mia residents differ")
    _require(safety["nara_service"] == registered.NARA_SERVICE, "Mia Nara differs")
    _require(safety["min_mem_available_gib"] == spec.min_mem_available_gib,
             "Mia memory floor differs")
    _require(safety["paging_policy"] == spec.paging_policy(),
             "Mia paging policy differs")
    _require(safety["setup_quiescence_seconds"] == registered.SETUP_QUIESCENCE_SECONDS,
             "Mia setup quiescence differs")
    _require(safety["ready_quiescence_seconds"] == registered.READY_QUIESCENCE_SECONDS,
             "Mia ready quiescence differs")
    _require(safety["memory_poll_seconds"] == 1, "Mia memory poll differs")
    deadline = registered._bounded_int(safety["invocation_deadline_seconds"],
                                       "Mia invocation deadline", 900,
                                       registered.MAX_INVOCATION_SECONDS)
    readiness = registered._bounded_int(safety["readiness_deadline_seconds"],
                                        "Mia readiness deadline", 60, 1200)
    reserve = registered._bounded_int(safety["restoration_reserve_seconds"],
                                      "Mia restoration reserve", 300, 900)
    registered._bounded_int(safety["probe_timeout_seconds"],
                            "Mia probe timeout", 5, 120)
    _require(readiness + reserve < deadline,
             "Mia readiness plus restoration exhausts deadline")
    _require(value["accounting"] == {
        "class": "uncapped-local-model-research", "weekly_budget_debit": False,
        "paid_api_allowed": False, "journal_path": str(registered.RESEARCH_LEDGER),
    }, "Mia accounting differs")
    return json.loads(registered.canonical_json(value))


def read_mia_contract(path: Path, registered) -> tuple[dict[str, Any], str, bytes]:
    """Read only the fixed Mia contract through stable nofollow parents."""
    path = path.absolute()
    _require(path == MIA.contract_path and not path.is_symlink(),
             "Mia contract path differs from the fixed external file")
    try:
        parent = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        try:
            for part in path.parts[1:-1]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=parent)
                os.close(parent)
                parent = child
            fd = os.open(path.name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW,
                         dir_fd=parent)
        finally:
            os.close(parent)
        try:
            info = os.fstat(fd)
            _require(stat.S_ISREG(info.st_mode) and 0 < info.st_size <= 2_000_000,
                     "Mia contract is not a bounded regular file")
            raw = os.read(fd, info.st_size + 1)
            _require(len(raw) == info.st_size, "Mia contract changed during read")
            _require(os.fstat(fd).st_size == info.st_size,
                     "Mia contract size changed during read")
            _require(os.fstat(fd).st_mtime_ns == info.st_mtime_ns,
                     "Mia contract modification time changed during read")
        finally:
            os.close(fd)
    except OSError as exc:
        raise MiaRegistrationError(f"Mia contract read failed: {exc}") from exc
    observed = registered._strict_json(raw, source="Mia fixed external contract")
    return validate_mia_contract(observed, registered), registered.sha256(raw), raw


def load_mia_contract(path: Path, registered) -> tuple[dict[str, Any], str]:
    contract, raw_sha, _ = read_mia_contract(path, registered)
    return contract, raw_sha


def validate_output(output: Path, spec: CandidateSpec = MIA, *, must_be_absent: bool = False) -> Path:
    output = output.absolute()
    _require(bool(re.fullmatch(r"qfn-mia-c0-[A-Za-z0-9][A-Za-z0-9._-]{0,79}",
                               output.name)), "Mia output run ID differs")
    _require(spec.output_root.is_dir() and not spec.output_root.is_symlink()
             and spec.output_root.resolve() == spec.output_root,
             "Mia output root is absent or redirected")
    _require(output.parent.resolve() == spec.output_root, "Mia output is outside run root")
    _require(not (must_be_absent and output.exists()), "Mia output already exists")
    _require(not (output.exists() and (output.is_symlink() or not output.is_dir())),
             "Mia output is redirected")
    return output


def plan_mia_qualification(value: dict[str, Any], raw_contract_sha256: str,
                           output: Path, registered) -> dict[str, Any]:
    value = validate_mia_contract(value, registered)
    output = validate_output(output)
    spec = MIA
    command = spec.launch_argv(compilation_config=registered.COMPILATION_CONFIG)
    _require(len(raw_contract_sha256) == 64 and all(c in "0123456789abcdef" for c in raw_contract_sha256),
             "Mia raw contract SHA is malformed")
    return {
        "schema": "qwen-flash-next-qualification-plan/v4",
        "contract_id": spec.contract_id,
        "contract_sha256": raw_contract_sha256,
        "profile": spec.profile,
        "candidate": {"id": spec.spec_id, "spec_sha256": spec.identity_sha256()},
        "image_id": spec.image_id,
        "model_artifact_sha256": spec.model_artifact_sha256(),
        "model_path": str(spec.model_path),
        "served_model": spec.served_name,
        "output_dir": str(output),
        "container_name": spec.container_name,
        "endpoint": f"http://127.0.0.1:{spec.host_port}/v1",
        "docker_create_argv": command,
        "docker_create_argv_sha256": registered.sha256(command),
        "packed_ple": {"path": str(spec.packed_ple_path),
                       "bytes": spec.packed_ple_bytes,
                       "sha256": spec.packed_ple_sha256},
        "proof_receipts": spec.identity_snapshot()["proof_receipts"],
        "probe_set": "flash-next-minimal-v1",
        "resident_ids": [row["id"] for row in registered.RESIDENTS],
        "resource_locks": [".weekly-upgrade-execution.lock",
                           ".coordinator-cron.lock", ".weekly-upgrade-gpu.lock"],
        "min_mem_available_gib": spec.min_mem_available_gib,
        "invocation_deadline_seconds": value["safety"]["invocation_deadline_seconds"],
        "readiness_deadline_seconds": value["safety"]["readiness_deadline_seconds"],
        "restoration_reserve_seconds": value["safety"]["restoration_reserve_seconds"],
        "setup_quiescence_seconds": value["safety"]["setup_quiescence_seconds"],
        "ready_quiescence_seconds": value["safety"]["ready_quiescence_seconds"],
        "paging_policy": value["safety"]["paging_policy"],
        "research_usage_journal": str(registered.RESEARCH_LEDGER),
        "weekly_budget_debit": False, "paid_api_allowed": False,
        "production_change_authorized": False,
        "actions": [
            "verify all model bytes, packed PLE bytes, and exact image before mutations",
            "require 60 seconds of unchanged setup pswpout before the mutation baseline",
            "acquire canonical resource lease and require idle resident queues",
            "create stopped A/B sentinel before any resident stop",
            "stop Nara only when initially active",
            "stop exact captured resident IDs without removal or recreation",
            "start candidate and continuously enforce 20 GiB MemAvailable",
            "hard-gate exact candidate cgroup swap, OOM events, restart, and exit",
            "enforce Docker 96 GiB charged-RAM cap and zero candidate swap",
            "bound host swap by registered load and serving byte-rate limits",
            "require 60 seconds of zero host and candidate swap after /v1/models",
            "qualify three fixed probes under the serving paging gate",
            "stop candidate, restore exact resident IDs and Nara state, then remove sentinel",
        ],
    }
