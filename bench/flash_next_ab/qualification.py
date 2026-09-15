"""Fail-closed qualification window for the pinned Flash-Next C0 runtime.

The public ``--plan`` mode is side-effect free.  ``--run`` first emits the
same immutable plan, then supervises a worker in a separate process group.
Only fixed argv vectors are executed; the external contract can reduce time
limits but cannot select another image, model, endpoint, service, or command.

Local model research was explicitly exempted from the weekly maintenance
budget on 2026-09-15.  This module therefore uses the canonical GPU/resource
lease but never constructs or writes ``BudgetLedger``.  It writes actual use
to a separate append-only research journal.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
import re
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from .candidate_registry import CandidateSpec

from orchestrator.weekly_upgrade_trial import canonical_root, resource_lease

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = Path(
    "/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-14/"
    "qwen-flash-next-research/runtime/launch-contract.c0.json"
)
OUTPUT_ROOT = Path(
    "/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-14/"
    "qwen-flash-next-research/qualification-runs"
)
RESEARCH_LEDGER = Path(
    "/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-14/"
    "qwen-flash-next-research/runtime/research-usage.jsonl"
)
WEEKLY_LEDGER_BASENAME = "weekly_upgrade_budget.jsonl"

IMAGE_ID = "sha256:345bea72ff3bb548594d88f6a7661636c07cd3e7367f8e54b0e4a98494e5a48d"
MODEL_PATH = Path("/mnt/models/qwen3.8-flash-next-nvfp4-fc694b54")
MODEL_REVISION = "fc694b54fb0174e0913e6adf86691ef85a4ead47"
MODEL_REPOSITORY = "nvidia/Qwen3.8-Flash-Next-NVFP4"
SERVED_MODEL = "qwen3.8-flash-next"
CONTAINER_NAME = "vllm-qwen-ab-flash-20260915"
COMPILE_CACHE_PARENT = Path(
    "/home/decross1/projects/a_bgt_rsi_runtime_candidates/"
    "flash-next-20260914/compile-cache-c0"
)
COMPILE_CACHE = COMPILE_CACHE_PARENT / "qwen38-flash-next-d453-c0"
NARA_SERVICE = "nara-daemon.service"
MIN_MEMORY_GIB = 20
MAX_INVOCATION_SECONDS = 3600
DEFAULT_RESTORE_RESERVE_SECONDS = 600
SETUP_QUIESCENCE_SECONDS = 60
READY_QUIESCENCE_SECONDS = 60
MAX_SAMPLE_GAP_SECONDS = 10
HOST_PORT = 8012
HOST_PAGE_SIZE_BYTES = 4096
MAX_MODEL_LEN = 32768
KV_CACHE_MEMORY_BYTES = 2 * 1024**3
# The container owns at most 96 GiB of charged RAM and zero swap. This is a
# registered diagnostic profile; actual full-load fit still needs a new C0.
DOCKER_MEMORY_LIMIT_BYTES = 96 * 1024**3
DOCKER_MEMORY_SWAP_TOTAL_BYTES = DOCKER_MEMORY_LIMIT_BYTES
# Exploratory cold-load pageout guardrails, distinct from a hardware-fit claim.
# Candidate-attributed swap remains exactly zero, the host floor remains 20 GiB,
# and ready/serving gates remain unchanged from the observed S0 failure.
LOAD_SWAP_5S_BREACH_BYTES = 512 * 1024**2
LOAD_SWAP_60S_BREACH_BYTES = 2 * 1024**3
LOAD_SWAP_TOTAL_BREACH_BYTES = 4 * 1024**3
SERVING_SWAP_5S_BREACH_BYTES = 32 * 1024**2
SERVING_SWAP_60S_BREACH_BYTES = 64 * 1024**2
SERVING_SWAP_TOTAL_BREACH_BYTES = 128 * 1024**2
PAGING_POLICY = {
    "host_page_size_bytes": HOST_PAGE_SIZE_BYTES,
    "startup_gate_phases": ["load", "ready"],
    "load": {
        "window_5s_breach_bytes": LOAD_SWAP_5S_BREACH_BYTES,
        "window_60s_breach_bytes": LOAD_SWAP_60S_BREACH_BYTES,
        "phase_total_breach_bytes": LOAD_SWAP_TOTAL_BREACH_BYTES,
    },
    "serving": {
        "window_5s_breach_bytes": SERVING_SWAP_5S_BREACH_BYTES,
        "window_60s_breach_bytes": SERVING_SWAP_60S_BREACH_BYTES,
        "phase_total_breach_bytes": SERVING_SWAP_TOTAL_BREACH_BYTES,
    },
    "candidate_cgroup_swap_max_bytes": 0,
    "candidate_cgroup_oom_initial_max": 0,
    "candidate_cgroup_oom_max_delta": 0,
    "candidate_cgroup_oom_kill_initial_max": 0,
    "candidate_cgroup_oom_kill_max_delta": 0,
    "ready_quiescence_seconds": READY_QUIESCENCE_SECONDS,
    "max_sample_gap_seconds": MAX_SAMPLE_GAP_SECONDS,
    "restoration_host_swap_action": "diagnostic_only",
}
FAILURE_STAGES = frozenset(
    {"setup", "candidate_start", "readiness", "probes", "evaluation", "restoration", "unknown"}
)


def _failure_class(
    status: str, error: str | None, restoration: dict[str, Any], monitor: Any
) -> str | None:
    if status == "passed":
        return None
    if status == "complete":
        return None
    if status == "unknown":
        return "restoration_unknown"
    first = getattr(monitor, "failure", None)
    only_startup_guard = (
        isinstance(first, str)
        and first.startswith("startup host swap reached the ")
        and isinstance(error, str)
        and error.endswith(first)
        and restoration.get("status") == "verified"
        and getattr(monitor, "emergency_stop_at", None) is not None
        and getattr(monitor, "candidate_cgroup_samples", 0) > 0
        and getattr(monitor, "candidate_cgroup_swap_peak_bytes", None) == 0
        and getattr(monitor, "candidate_cgroup_oom_initial", None) == 0
        and getattr(monitor, "candidate_cgroup_oom_final", None) == 0
        and getattr(monitor, "candidate_cgroup_oom_kill_initial", None) == 0
        and getattr(monitor, "candidate_cgroup_oom_kill_final", None) == 0
        and getattr(monitor, "minimum_observed_gib", 0) >= MIN_MEMORY_GIB
        and all(
            isinstance(reason, str)
            and (
                reason.startswith("startup host swap reached the ")
                or reason == "candidate disappeared or stopped while qualified runtime was armed"
            )
            for reason in getattr(monitor, "violations", [])
        )
    )
    extended_host_guard = (
        isinstance(first, str)
        and first.startswith("extended_serving host swap reached the ")
        and isinstance(error, str) and error.endswith(first)
        and restoration.get("status") == "verified"
        and getattr(monitor, "candidate_cgroup_swap_peak_bytes", None) == 0
        and getattr(monitor, "candidate_cgroup_oom_initial", None) == 0
        and getattr(monitor, "candidate_cgroup_oom_final", None) == 0
        and getattr(monitor, "candidate_cgroup_oom_kill_initial", None) == 0
        and getattr(monitor, "candidate_cgroup_oom_kill_final", None) == 0
        and getattr(monitor, "minimum_observed_gib", 0) >= MIN_MEMORY_GIB
    )
    ui_operational_abort = (
        isinstance(first, str)
        and first.startswith(("two UI health failures within 30 seconds", "UI observer failed:",
                              "UI observer thread did not terminate"))
        and restoration.get("status") == "verified"
    )
    return (
        "experimental_startup_host_pageout_guardrail_abort"
        if only_startup_guard else
        "experimental_extended_host_pageout_guardrail_abort"
        if extended_host_guard else
        "operational_ui_responsiveness_abort"
        if ui_operational_abort else "other_qualification_failure"
    )

WEIGHT_FILES: dict[str, tuple[int, str]] = {
    "model-00001-of-00010.safetensors": (3115991696, "63fde954be6f08b49b876f4f70a0ad0bcfee71aff7b1faa33779b6b32feca2a2"),
    "model-00002-of-00010.safetensors": (10005510304, "4dafaef62a908e49e0d92c7c2a3fa99f4d9651fdeeb0ca09f09a9b40095af4e0"),
    "model-00003-of-00010.safetensors": (10005364728, "3218ddc129258e91a721a8e81329ca8f00588332ec721bd8d2cf7d20e324bf47"),
    "model-00004-of-00010.safetensors": (10006060112, "55e2bdf6a3a1f6e65270787f65c63b2a2a56b308b54eb1fb318dfabc9b48b141"),
    "model-00005-of-00010.safetensors": (10005362392, "d3c169d3694bfba846455d01e48f047d770f78d071c5a4d22f129389411d686e"),
    "model-00006-of-00010.safetensors": (10005375328, "38f65a9d11090428e139cc60d0587e8e5433ea2ce79820883c583d7cfcc53130"),
    "model-00007-of-00010.safetensors": (10005956544, "8cf3fa05c04cb2e060963b69bb01f7a7b9f43c58435fbe380836a0457a19cd3e"),
    "model-00008-of-00010.safetensors": (10005375200, "53d1f80746aa0cc0a7c2f4836587002a8a4dd72c827432cd2e43abae3c3899e4"),
    "model-00009-of-00010.safetensors": (5679113808, "eaff6a87ece6fbfd6ad0fbaa0a5cf9ff542f8076acba38e62410b1ed55e12cc3"),
    "model-00010-of-00010.safetensors": (128587536, "0d49b0cf7c15bf9b5bd1e17403b36727315860a8f2a2e0f5a53655547084f640"),
    "model-fp8-mtp-ple.safetensors": (53717551730, "3525520c8602d850003eb1960aec0b64291dae33b83f8b65dd639a451df78823"),
}
CONTROL_FILES: dict[str, tuple[int, str]] = {
    ".gitattributes": (1635, "fe81d528e7ee055bbcf6a310afe0f2808423a4a16d45225f29c285926abef08d"),
    "README.md": (12109, "e3ed0cb89950ef0f41e8df344ba1cc15c67e1baf91e1cb5305a7344e58a8d975"),
    "generation_config.json": (202, "e70c136c1b78ddc1fb0905bac8e733a4dc448d4f852a5dd75143fffc70be550e"),
    "merges.txt": (3353259, "a9d356d7bdf1ef4949e3e748e95b8e10ad9d4e2e838eddc38a0a7b6b94d1db8d"),
    "model.safetensors.index.json": (31275518, "660414e8300728ba80062e6a3c81cb76a65e2ab136ac9e9ceb450ba0c51c3c0d"),
    "config.json": (30820, "deef67a61f3311faf051b23dc4192f442c7fee4f9cd2f38cbcbe4da55c763a80"),
    "hf_quant_config.json": (23001, "331ad11d57c8bc374554579977198084e0d4d0933d5b3558f125f6f670aba0e8"),
    "preprocessor_config.json": (390, "27225450ac9c6529872ee1924fcb0962ff5634834f817040f444118116f4e516"),
    "processor_config.json": (1191, "d89ef49ce9cd37fbf510158e13c1ef063d9286411c1ec9049932dbe0487143b1"),
    "tokenizer.json": (12809320, "0997f410c57a1f4e53b09e4be8f4a172d90edd9564368fb0847030937229b9f3"),
    "tokenizer_config.json": (17928, "b11349aafa7cdc6a320767cf7ceb29ed82f7eda5d65e8e0819e76f0ce947bf27"),
    "chat_template.jinja": (8952, "c3cf9e34abf4f9e36c2d72165aa9c132d3e2a725b6c2586aaa3a8af9d7a81041"),
    "video_preprocessor_config.json": (385, "7768af27c1fafa9cc9011c1dc20067e03f8915e03b63504550e11d5066986d13"),
    "vocab.json": (6722759, "ce99b4cb2983d118806ce0a8b777a35b093e2000a503ebde25853284c9dfa003"),
}
MODEL_TOTAL_BYTES = 132680249378
MODEL_TENSOR_BYTES = 132639846394
MODEL_REPOSITORY_BYTES = 132734506847

RESIDENTS = (
    {
        "name": "vllm-gemma4",
        "id": "fc61a80d6c2d07b551c5afdd566a7c82ee05ad40c014d69c428e299e49101374",
        "image_id": "sha256:f023269abe06db3a1a7cd9e170a0f5bd2b333a19ef9cb99ed8df97a70345bc25",
        "health_url": "http://127.0.0.1:8000/health",
    },
    {
        "name": "vllm-qwen",
        "id": "bcb6cd87757279ff77f1460cab2f8ad6cf1a2e46d19dad165b07dccecfa509bb",
        "image_id": "sha256:f023269abe06db3a1a7cd9e170a0f5bd2b333a19ef9cb99ed8df97a70345bc25",
        "health_url": "http://127.0.0.1:8001/health",
    },
)

SPLITTING_OPS = [
    "vllm::unified_attention_with_output",
    "vllm::unified_mla_attention_with_output",
    "vllm::mamba_mixer2",
    "vllm::mamba_mixer",
    "vllm::short_conv",
    "vllm::qwen4_exp_compute_ple_ngram_ids",
    "vllm::qwen4_exp_ple_short_conv",
    "vllm::qwen4_exp_qsa_with_output",
    "vllm::linear_attention",
    "vllm::qwen_gdn_attention_core",
    "vllm::qwen_gdn_attention_core_fused_norm_packed",
    "vllm::sparse_attn_indexer",
    "vllm::ple_mmap_lookup_ids",
]
COMPILATION_CONFIG = json.dumps(
    {"cudagraph_mode": "PIECEWISE", "splitting_ops": SPLITTING_OPS},
    separators=(",", ":"),
)

FIXED_ENV = (
    ("HF_HUB_OFFLINE", "1"),
    ("TRANSFORMERS_OFFLINE", "1"),
    ("VLLM_ENGINE_READY_TIMEOUT_S", "3600"),
    ("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True"),
    ("CUTE_DSL_ARCH", "sm_121a"),
    ("TORCH_CUDA_ARCH_LIST", "12.1a"),
    ("FLASHINFER_CUDA_ARCH_LIST", "12.1a"),
    ("FLASHINFER_DISABLE_VERSION_CHECK", "1"),
    ("VLLM_USE_DEEP_GEMM", "0"),
    ("VLLM_USE_V2_MODEL_RUNNER", "1"),
    ("VLLM_PLE_MMAP", "1"),
    ("VLLM_PLE_MMAP_DIR", "/models/qwen"),
    ("VLLM_PLE_MMAP_WORKERS", "32"),
    ("VLLM_PLE_MMAP_PREWARM", "0"),
    ("VLLM_PLE_MMAP_MADVISE", "random"),
    ("VLLM_QSA_EXACT_TOPK", "1"),
    ("VLLM_QSA_DET_TOPK", "0"),
    ("PROMETHEUS_MULTIPROC_DIR", "/tmp/vllm-prometheus"),
)


@dataclass(frozen=True, slots=True)
class _RuntimeIdentity:
    image_id: str
    model_path: Path
    model_revision: str
    model_repository: str
    served_model: str
    container_name: str
    compile_cache: Path
    compile_cache_parent: Path
    host_port: int
    model_repository_bytes: int
    model_index_total_bytes: int
    weight_files: frozenset[str]
    indexed_weight_files: frozenset[str]
    cache_metadata_required: bool
    memory_limit_bytes: int
    min_memory_gib: int
    model_artifact_sha256: str
    packed_ple_path: Path | None = None
    packed_ple_bytes: int | None = None
    packed_ple_sha256: str | None = None


def _runtime_identity(spec: CandidateSpec | None = None) -> _RuntimeIdentity:
    """Build a local immutable view; never switch module globals or thread state."""
    if spec is None:
        return _RuntimeIdentity(
            IMAGE_ID, MODEL_PATH, MODEL_REVISION, MODEL_REPOSITORY, SERVED_MODEL,
            CONTAINER_NAME, COMPILE_CACHE, COMPILE_CACHE_PARENT, HOST_PORT,
            MODEL_REPOSITORY_BYTES, MODEL_TENSOR_BYTES,
            frozenset(WEIGHT_FILES), frozenset(WEIGHT_FILES), True,
            DOCKER_MEMORY_LIMIT_BYTES, MIN_MEMORY_GIB, model_artifact_sha256(),
        )
    from .followon_profiles import is_registered_spec
    if not is_registered_spec(spec):
        raise QualificationError("candidate spec is outside the code-owned Mia registry")
    return _RuntimeIdentity(
        spec.image_id, spec.model_path, spec.revision, spec.repository,
        spec.served_name, spec.container_name, spec.compile_cache,
        spec.compile_cache.parent, spec.host_port, spec.repository_total_bytes,
        spec.indexed_total_size_bytes, frozenset(spec.weight_files),
        frozenset(spec.indexed_weight_files), False,
        spec.docker_memory_limit_bytes, spec.min_mem_available_gib,
        spec.model_artifact_sha256(), spec.packed_ple_path, spec.packed_ple_bytes,
        spec.packed_ple_sha256,
    )


def _mia_standard_schema(kind: str, spec: CandidateSpec) -> str:
    """Only the original singleton retains v4; new literal profiles use v5."""
    from .followon_profiles import MIA, is_registered_spec
    if kind not in ("state", "result") or not is_registered_spec(spec):
        raise QualificationError("unregistered Mia schema kind/spec")
    return f"qwen-flash-next-qualification-{kind}/" + ("v4" if spec is MIA else "v5")


class QualificationError(RuntimeError):
    """A fail-closed qualification or restoration error."""


class QualificationInterrupted(QualificationError):
    """The supervisor asked the worker to restore and exit."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _self_start_ticks() -> int:
    """Return this process's Linux start time from /proc/self/stat field 22."""
    raw = Path("/proc/self/stat").read_text()
    closing = raw.rfind(")")
    if closing < 0:
        raise QualificationError("worker process start identity is unavailable")
    fields_from_three = raw[closing + 1 :].split()
    try:
        value = int(fields_from_three[19])
    except (IndexError, ValueError) as exc:
        raise QualificationError("worker process start identity is malformed") from exc
    if value <= 0:
        raise QualificationError("worker process start identity is invalid")
    return value


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def sha256(value: Any) -> str:
    return hashlib.sha256(value if isinstance(value, bytes) else canonical_json(value)).hexdigest()


def _strict_json(
    raw: bytes, *, source: str, max_bytes: int = 2_000_000
) -> dict[str, Any]:
    if len(raw) > max_bytes:
        raise QualificationError(f"oversized JSON: {source}")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise QualificationError(f"duplicate JSON key in {source}: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw,
            object_pairs_hook=unique,
            parse_constant=lambda item: (_ for _ in ()).throw(
                QualificationError(f"non-finite JSON in {source}: {item}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError(f"invalid JSON: {source}") from exc
    if not isinstance(value, dict):
        raise QualificationError(f"expected a JSON object: {source}")
    return value


def _atomic_write(path: Path, value: dict[str, Any]) -> None:
    raw = json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n"
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temporary.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _atomic_write_bytes(path: Path, raw: bytes) -> None:
    if len(raw) > 2_000_000:
        raise QualificationError(f"bounded artifact is too large: {path.name}")
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temporary.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _exact_keys(value: dict[str, Any], expected: set[str], where: str) -> None:
    if set(value) != expected:
        raise QualificationError(f"{where} fields differ from the registered contract")


def _bounded_int(value: Any, name: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise QualificationError(f"{name} must be an integer in {low}..{high}")
    return value


def expected_model_files(spec: CandidateSpec | None = None) -> dict[str, dict[str, Any]]:
    if spec is not None:
        return spec.expected_model_files()
    return {
        name: {"bytes": size, "sha256": digest}
        for name, (size, digest) in {**WEIGHT_FILES, **CONTROL_FILES}.items()
    }


def model_artifact_sha256(spec: CandidateSpec | None = None) -> str:
    if spec is not None:
        return spec.model_artifact_sha256()
    return sha256(
        {
            "repository": MODEL_REPOSITORY,
            "revision": MODEL_REVISION,
            "files": expected_model_files(),
        }
    )


def validate_contract(value: dict[str, Any], *, spec: CandidateSpec | None = None) -> dict[str, Any]:
    """Validate all mutable input against the code-reviewed allowlist."""
    if spec is not None:
        _runtime_identity(spec)
        from .mia_candidate_integration import (
            MiaRegistrationError,
            validate_mia_contract,
        )
        try:
            return validate_mia_contract(value, sys.modules[__name__])
        except MiaRegistrationError as exc:
            raise QualificationError(str(exc)) from exc
    _exact_keys(
        value,
        {"schema", "contract_id", "profile", "image", "model", "runtime", "safety", "accounting", "probe_set"},
        "contract",
    )
    if (
        value["schema"] != "qwen-flash-next-qualification/v3"
        or value["contract_id"] != "qwen38-flash-next-c0-s1-20260915"
        or value["profile"] != "C0-S1"
        or value["probe_set"] != "flash-next-minimal-v1"
    ):
        raise QualificationError("contract identity is not registered")

    expected_image = {"id": IMAGE_ID, "architecture": "arm64"}
    if value["image"] != expected_image:
        raise QualificationError("container image differs from the allowlist")

    expected_model = {
        "repository": MODEL_REPOSITORY,
        "revision": MODEL_REVISION,
        "host_path": str(MODEL_PATH),
        "container_path": "/models/qwen",
        "served_name": SERVED_MODEL,
        "safetensors_total_bytes": MODEL_TOTAL_BYTES,
        "tensor_payload_bytes": MODEL_TENSOR_BYTES,
        "repository_total_bytes": MODEL_REPOSITORY_BYTES,
        "artifact_sha256": model_artifact_sha256(),
        "files": expected_model_files(),
        "full_sha256_before_mutation": True,
    }
    if value["model"] != expected_model:
        raise QualificationError("model identity or content manifest differs from the allowlist")

    expected_runtime = {
        "container_name": CONTAINER_NAME,
        "host_address": "127.0.0.1",
        "host_port": HOST_PORT,
        "container_port": 8000,
        "compile_cache_path": str(COMPILE_CACHE),
        "max_model_len": MAX_MODEL_LEN,
        "max_num_seqs": 1,
        "gpu_memory_utilization": 0.75,
        "kv_cache_memory_bytes": KV_CACHE_MEMORY_BYTES,
        "max_num_batched_tokens": 4096,
        "kv_cache_dtype": "auto",
        "mamba_ssm_cache_dtype": "float32",
        "mtp_speculative_tokens": 0,
        "prefix_caching": False,
        "async_scheduling": False,
        "qsa_exact_topk": True,
        "language_model_only": True,
        "docker_memory_limit_bytes": DOCKER_MEMORY_LIMIT_BYTES,
        "docker_memory_swap_total_bytes": DOCKER_MEMORY_SWAP_TOTAL_BYTES,
    }
    if value["runtime"] != expected_runtime:
        raise QualificationError("runtime profile differs from the C0 allowlist")

    safety = value["safety"]
    _exact_keys(
        safety,
        {
            "resident_containers",
            "nara_service",
            "min_mem_available_gib",
            "invocation_deadline_seconds",
            "readiness_deadline_seconds",
            "restoration_reserve_seconds",
            "setup_quiescence_seconds",
            "ready_quiescence_seconds",
            "memory_poll_seconds",
            "probe_timeout_seconds",
            "paging_policy",
        },
        "safety",
    )
    expected_residents = [
        {key: row[key] for key in ("name", "id", "image_id", "health_url")}
        for row in RESIDENTS
    ]
    if (
        safety["resident_containers"] != expected_residents
        or safety["nara_service"] != NARA_SERVICE
        or safety["min_mem_available_gib"] != MIN_MEMORY_GIB
        or safety["setup_quiescence_seconds"] != SETUP_QUIESCENCE_SECONDS
        or safety["ready_quiescence_seconds"] != READY_QUIESCENCE_SECONDS
        or safety["memory_poll_seconds"] != 1
        or safety["paging_policy"] != PAGING_POLICY
    ):
        raise QualificationError(
            "safety identity, paging policy, or 20 GiB gate differs from the allowlist"
        )
    deadline = _bounded_int(
        safety["invocation_deadline_seconds"],
        "invocation_deadline_seconds",
        900,
        MAX_INVOCATION_SECONDS,
    )
    readiness = _bounded_int(
        safety["readiness_deadline_seconds"], "readiness_deadline_seconds", 60, 1200
    )
    reserve = _bounded_int(
        safety["restoration_reserve_seconds"], "restoration_reserve_seconds", 300, 900
    )
    _bounded_int(safety["probe_timeout_seconds"], "probe_timeout_seconds", 5, 120)
    if readiness + reserve >= deadline:
        raise QualificationError("readiness and restoration reserves exhaust the invocation")

    expected_accounting = {
        "class": "uncapped-local-model-research",
        "weekly_budget_debit": False,
        "paid_api_allowed": False,
        "journal_path": str(RESEARCH_LEDGER),
    }
    if value["accounting"] != expected_accounting:
        raise QualificationError("research accounting differs from the allowlist")
    return json.loads(canonical_json(value))


def load_contract(path: Path = CONTRACT_PATH) -> tuple[dict[str, Any], str]:
    path = path.absolute()
    if path != CONTRACT_PATH or path.is_symlink() or path.resolve() != CONTRACT_PATH:
        raise QualificationError("contract must be the fixed external regular file")
    if not path.is_file():
        raise QualificationError("external launch contract is absent")
    raw = path.read_bytes()
    return validate_contract(_strict_json(raw, source=str(path))), sha256(raw)


def _verified_contract_raw(
    contract: dict[str, Any], contract_sha: str, path: Path | None = None,
    *, spec: CandidateSpec | None = None,
) -> bytes:
    """Re-read and bind the exact external bytes copied into a run receipt."""
    if spec is not None:
        _runtime_identity(spec)
        from .mia_candidate_integration import read_mia_contract
        observed, raw_sha, raw = read_mia_contract(path or spec.contract_path,
                                                   sys.modules[__name__])
        if raw_sha != contract_sha or observed != contract:
            raise QualificationError("Mia external contract changed after planning")
        return raw
    path = path or CONTRACT_PATH
    if path != CONTRACT_PATH or path.is_symlink() or path.resolve() != CONTRACT_PATH:
        raise QualificationError("raw contract source is not the fixed external file")
    raw = path.read_bytes()
    if sha256(raw) != contract_sha:
        raise QualificationError("external contract bytes changed after planning")
    observed = validate_contract(_strict_json(raw, source=str(path)))
    if observed != contract:
        raise QualificationError("external contract content changed after planning")
    return raw


def launch_argv(spec: CandidateSpec | None = None) -> list[str]:
    if spec is not None:
        return spec.launch_argv(compilation_config=COMPILATION_CONFIG)
    command = [
        "docker", "create",
        "--name", CONTAINER_NAME,
        "--restart=no",
        "--gpus", "all",
        "--memory", str(DOCKER_MEMORY_LIMIT_BYTES),
        "--memory-swap", str(DOCKER_MEMORY_SWAP_TOTAL_BYTES),
        "--ipc=host",
        "-p", "127.0.0.1:8012:8000",
        "--tmpfs", "/tmp/vllm-prometheus:rw,size=256m",
        "-v", f"{MODEL_PATH}:/models/qwen:ro",
        "-v", f"{COMPILE_CACHE}:/root/.cache:rw",
    ]
    for name, value in FIXED_ENV:
        command.extend(["-e", f"{name}={value}"])
    command.extend(
        [
            IMAGE_ID,
            "/models/qwen",
            "--served-model-name", SERVED_MODEL,
            "--host", "0.0.0.0",
            "--port", "8000",
            "--load-format", "safetensors",
            "--trust-remote-code",
            "--quantization", "modelopt",
            "--tensor-parallel-size", "1",
            "--max-model-len", str(MAX_MODEL_LEN),
            "--max-num-seqs", "1",
            "--language-model-only",
            "--gpu-memory-utilization", "0.75",
            "--kv-cache-memory-bytes", str(KV_CACHE_MEMORY_BYTES),
            "--no-enable-prefix-caching",
            "--enable-chunked-prefill",
            "--max-num-batched-tokens", "4096",
            "--compilation-config", COMPILATION_CONFIG,
            "--no-enable-flashinfer-autotune",
            "--kv-cache-dtype", "auto",
            "--mamba-ssm-cache-dtype", "float32",
            "--no-async-scheduling",
            "--reasoning-parser", "qwen3",
            "--enable-auto-tool-choice",
            "--tool-call-parser", "qwen3_coder",
        ]
    )
    return command


def _validate_output(
    output: Path, *, must_be_absent: bool, spec: CandidateSpec | None = None
) -> Path:
    if spec is not None:
        _runtime_identity(spec)
        from .mia_candidate_integration import MiaRegistrationError, validate_output
        try:
            return validate_output(output, spec, must_be_absent=must_be_absent)
        except MiaRegistrationError as exc:
            raise QualificationError(str(exc)) from exc
    output = output.absolute()
    if not re.fullmatch(r"qfn-c0-[A-Za-z0-9][A-Za-z0-9._-]{0,79}", output.name):
        raise QualificationError("output directory name is not a bounded C0 run id")
    if OUTPUT_ROOT.is_symlink() or not OUTPUT_ROOT.is_dir() or OUTPUT_ROOT.resolve() != OUTPUT_ROOT:
        raise QualificationError("qualification output root is absent or redirected")
    if output.parent.resolve() != OUTPUT_ROOT:
        raise QualificationError("output must be a direct child of the isolated run root")
    if must_be_absent and output.exists():
        raise QualificationError("qualification output already exists")
    if output.exists() and (output.is_symlink() or not output.is_dir()):
        raise QualificationError("qualification output is redirected")
    return output


def plan_qualification(
    contract: dict[str, Any], contract_sha256: str, output: Path,
    *, spec: CandidateSpec | None = None,
) -> dict[str, Any]:
    if spec is not None:
        _runtime_identity(spec)
        from .mia_candidate_integration import (
            MiaRegistrationError,
            plan_mia_qualification,
        )
        try:
            return plan_mia_qualification(contract, contract_sha256, output,
                                          sys.modules[__name__])
        except MiaRegistrationError as exc:
            raise QualificationError(str(exc)) from exc
    contract = validate_contract(contract)
    output = _validate_output(output, must_be_absent=False)
    command = launch_argv()
    return {
        "schema": "qwen-flash-next-qualification-plan/v3",
        "contract_id": contract["contract_id"],
        "contract_sha256": contract_sha256,
        "profile": "C0-S1",
        "image_id": IMAGE_ID,
        "model_artifact_sha256": model_artifact_sha256(),
        "model_path": str(MODEL_PATH),
        "served_model": SERVED_MODEL,
        "output_dir": str(output),
        "container_name": CONTAINER_NAME,
        "endpoint": "http://127.0.0.1:8012/v1",
        "docker_create_argv": command,
        "docker_create_argv_sha256": sha256(command),
        "probe_set": "flash-next-minimal-v1",
        "resident_ids": [row["id"] for row in RESIDENTS],
        "resource_locks": [
            ".weekly-upgrade-execution.lock",
            ".coordinator-cron.lock",
            ".weekly-upgrade-gpu.lock",
        ],
        "min_mem_available_gib": MIN_MEMORY_GIB,
        "invocation_deadline_seconds": contract["safety"]["invocation_deadline_seconds"],
        "readiness_deadline_seconds": contract["safety"]["readiness_deadline_seconds"],
        "restoration_reserve_seconds": contract["safety"]["restoration_reserve_seconds"],
        "setup_quiescence_seconds": contract["safety"]["setup_quiescence_seconds"],
        "ready_quiescence_seconds": contract["safety"]["ready_quiescence_seconds"],
        "paging_policy": contract["safety"]["paging_policy"],
        "research_usage_journal": str(RESEARCH_LEDGER),
        "weekly_budget_debit": False,
        "paid_api_allowed": False,
        "production_change_authorized": False,
        "actions": [
            "verify all model bytes and exact image before mutations",
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


@dataclass
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise QualificationError("local endpoint attempted an HTTP redirect")


class HostOps:
    """Narrow host interface; every subprocess receives a fixed argv list."""

    def run(self, argv: list[str], *, timeout: float, check: bool = True) -> CommandResult:
        if not argv or any(not isinstance(item, str) for item in argv):
            raise QualificationError("invalid argv")
        try:
            completed = subprocess.run(
                argv,
                text=True,
                capture_output=True,
                timeout=max(0.1, timeout),
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise QualificationError(f"bounded command timed out: {argv[0]}") from exc
        if len(completed.stdout) > 2_000_000 or len(completed.stderr) > 2_000_000:
            raise QualificationError(f"command output exceeded ceiling: {argv[0]}")
        result = CommandResult(completed.returncode, completed.stdout, completed.stderr)
        if check and result.returncode != 0:
            detail = result.stderr.strip().splitlines()[-1:] or ["no diagnostic"]
            raise QualificationError(f"command failed ({argv[0]}): {detail[0][:500]}")
        return result

    def http_bytes(self, url: str, *, timeout: float) -> bytes:
        if url not in {
            "http://127.0.0.1:8012/health",
            "http://127.0.0.1:8012/v1/models",
            "http://127.0.0.1:8000/health",
            "http://127.0.0.1:8001/health",
        }:
            raise QualificationError("HTTP target is outside the loopback allowlist")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open(url, timeout=max(0.1, timeout)) as response:
            raw = response.read(1_000_001)
            if response.status != 200 or len(raw) > 1_000_000:
                raise QualificationError("local health response is invalid")
            return raw

    def complete(self, endpoint, messages, **kwargs):
        from bench.flash_next_ab.transport import complete

        return complete(endpoint, messages, **kwargs)


def _inspect_container(ops: HostOps, identity: str) -> dict[str, Any] | None:
    fields = (
        '{"id":{{json .Id}},"name":{{json .Name}},"image":{{json .Image}},'
        '"running":{{json .State.Running}},"pid":{{json .State.Pid}},'
        '"started_at":{{json .State.StartedAt}},"finished_at":{{json .State.FinishedAt}},'
        '"oom_killed":{{json .State.OOMKilled}},"state_error":{{json .State.Error}},'
        '"restart_count":{{json .RestartCount}},'
        '"memory_limit_bytes":{{json .HostConfig.Memory}},'
        '"memory_swap_total_bytes":{{json .HostConfig.MemorySwap}},'
        '"restart_policy":{{json .HostConfig.RestartPolicy.Name}}}'
    )
    result = ops.run(
        ["docker", "inspect", "--format", fields, identity], timeout=5, check=False
    )
    if result.returncode != 0:
        diagnostic = (result.stderr + "\n" + result.stdout).lower()
        if "no such object" in diagnostic or "no such container" in diagnostic:
            return None
        raise QualificationError(f"Docker could not verify container identity: {identity}")
    row = _strict_json(result.stdout.encode(), source=f"docker inspect {identity}")
    row["name"] = str(row.get("name", "")).removeprefix("/")
    return row


def _service_state(ops: HostOps, *, timeout: float = 5) -> dict[str, str]:
    result = ops.run(
        [
            "systemctl", "--user", "show", NARA_SERVICE,
            "--property=ActiveState", "--property=SubState", "--property=MainPID",
            "--no-pager",
        ],
        timeout=timeout,
    )
    values = {}
    for line in result.stdout.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            values[key] = value
    if set(values) != {"ActiveState", "SubState", "MainPID"}:
        raise QualificationError("Nara service state is incomplete")
    if values["ActiveState"] not in {"active", "inactive", "failed"}:
        raise QualificationError("Nara service is transitioning")
    return values


def _available_gib() -> float:
    match = re.search(
        r"^MemAvailable:\s+(\d+) kB$", Path("/proc/meminfo").read_text(), re.MULTILINE
    )
    if not match:
        raise QualificationError("MemAvailable is unavailable")
    return int(match[1]) / 1024**2


def _host_meminfo_diagnostics() -> dict[str, int]:
    """Raw host observations for attribution; safety still uses MemAvailable."""
    raw = Path("/proc/meminfo").read_text()
    values: dict[str, int] = {}
    fields = ("MemFree", "Cached", "SwapCached", "AnonPages", "SwapFree", "MemAvailable")
    for name in fields:
        match = re.search(rf"^{name}:\s+(\d+) kB$", raw, re.MULTILINE)
        if match is None:
            raise QualificationError(f"host meminfo diagnostic {name} is unavailable")
        values[name] = int(match[1])
    return values


def _pswpout_pages() -> int:
    match = re.search(
        r"^pswpout\s+(\d+)$", Path("/proc/vmstat").read_text(), re.MULTILINE
    )
    if not match:
        raise QualificationError("host pswpout is unavailable")
    return int(match[1])


def _pswpin_pages() -> int:
    match = re.search(
        r"^pswpin\s+(\d+)$", Path("/proc/vmstat").read_text(), re.MULTILINE
    )
    if not match:
        raise QualificationError("host pswpin is unavailable")
    return int(match[1])


def _host_memory_psi_totals() -> dict[str, int]:
    """Kernel stall microseconds: diagnostic evidence, no arbitrary PSI gate."""
    raw = _bounded_nofollow_bytes(Path("/proc/pressure/memory"), max_bytes=1024)
    try:
        lines = raw.decode("ascii").splitlines()
    except UnicodeDecodeError as exc:
        raise QualificationError("host memory PSI is malformed") from exc
    totals: dict[str, int] = {}
    pattern = re.compile(
        r"^(some|full) avg10=\d+\.\d{2} avg60=\d+\.\d{2} "
        r"avg300=\d+\.\d{2} total=(\d+)$"
    )
    for line in lines:
        match = pattern.fullmatch(line)
        if match is None or match[1] in totals:
            raise QualificationError("host memory PSI has an unexpected shape")
        totals[match[1]] = int(match[2])
    if set(totals) != {"some", "full"}:
        raise QualificationError("host memory PSI stall counters are incomplete")
    return totals


def _bounded_nofollow_bytes(
    path: Path, *, max_bytes: int, dir_fd: int | None = None
) -> bytes:
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, dir_fd=dir_fd)
    try:
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode):
            raise QualificationError(f"runtime evidence is not regular: {path}")
        raw = os.read(descriptor, max_bytes + 1)
        if len(raw) > max_bytes:
            raise QualificationError(f"runtime evidence exceeded its bound: {path}")
        return raw
    finally:
        os.close(descriptor)


def _nonnegative_decimal(raw: bytes, *, label: str) -> int:
    try:
        text = raw.decode("ascii").strip()
        value = int(text)
    except (UnicodeDecodeError, ValueError) as exc:
        raise QualificationError(f"{label} is malformed") from exc
    if not text.isdecimal() or value < 0:
        raise QualificationError(f"{label} is malformed")
    return value


def _memory_events(raw: bytes) -> dict[str, int]:
    events: dict[str, int] = {}
    try:
        lines = raw.decode("ascii").splitlines()
    except UnicodeDecodeError as exc:
        raise QualificationError("candidate cgroup memory.events is malformed") from exc
    for line in lines:
        fields = line.split()
        if len(fields) != 2 or fields[0] in events:
            raise QualificationError("candidate cgroup memory.events is malformed")
        events[fields[0]] = _nonnegative_decimal(
            fields[1].encode(), label=f"candidate cgroup memory.events {fields[0]}"
        )
    if not {"oom", "oom_kill"}.issubset(events):
        raise QualificationError("candidate cgroup OOM counters are absent")
    return events


def _process_start_ticks(pid: int) -> int:
    raw = _bounded_nofollow_bytes(Path(f"/proc/{pid}/stat"), max_bytes=4096)
    closing = raw.rfind(b")")
    if closing < 0:
        raise QualificationError("candidate process start identity is unavailable")
    fields_from_three = raw[closing + 1 :].split()
    try:
        value = int(fields_from_three[19])
    except (IndexError, ValueError) as exc:
        raise QualificationError("candidate process start identity is malformed") from exc
    if value <= 0:
        raise QualificationError("candidate process start identity is invalid")
    return value


def _candidate_cgroup_snapshot(candidate_id: str, pid: int) -> dict[str, Any]:
    """Bind one live Docker PID to its exact cgroup-v2 memory counters."""
    if (
        not re.fullmatch(r"[0-9a-f]{64}", candidate_id)
        or isinstance(pid, bool)
        or not isinstance(pid, int)
        or pid <= 0
    ):
        raise QualificationError("candidate cgroup identity is malformed")
    process_start_ticks = _process_start_ticks(pid)
    expected_relpath = f"/system.slice/docker-{candidate_id}.scope"
    raw_cgroup = _bounded_nofollow_bytes(
        Path(f"/proc/{pid}/cgroup"), max_bytes=4096
    )
    try:
        lines = raw_cgroup.decode("ascii").splitlines()
    except UnicodeDecodeError as exc:
        raise QualificationError("candidate process cgroup is malformed") from exc
    if lines != [f"0::{expected_relpath}"]:
        raise QualificationError("candidate process is outside its exact cgroup-v2 scope")

    cgroup_path = Path("/sys/fs/cgroup") / expected_relpath.removeprefix("/")
    directory = os.open(
        cgroup_path,
        os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        memory_max_bytes = _nonnegative_decimal(
            _bounded_nofollow_bytes(Path("memory.max"), max_bytes=128, dir_fd=directory),
            label="candidate cgroup memory.max",
        )
        memory_swap_max_bytes = _nonnegative_decimal(
            _bounded_nofollow_bytes(Path("memory.swap.max"), max_bytes=128, dir_fd=directory),
            label="candidate cgroup memory.swap.max",
        )
        memory_current_bytes = _nonnegative_decimal(
            _bounded_nofollow_bytes(Path("memory.current"), max_bytes=128, dir_fd=directory),
            label="candidate cgroup memory.current",
        )
        raw_stat = _bounded_nofollow_bytes(
            Path("memory.stat"), max_bytes=8192, dir_fd=directory
        )
        try:
            stat_lines = raw_stat.decode("ascii").splitlines()
        except UnicodeDecodeError as exc:
            raise QualificationError("candidate cgroup memory.stat is malformed") from exc
        selected_stats: dict[str, int] = {}
        tracked = {"anon", "file", "shmem", "active_file", "inactive_file", "pgscan", "pgsteal"}
        for line in stat_lines:
            fields = line.split()
            if len(fields) != 2:
                raise QualificationError("candidate cgroup memory.stat is malformed")
            if fields[0] in tracked:
                if fields[0] in selected_stats:
                    raise QualificationError("candidate cgroup memory.stat has duplicates")
                selected_stats[fields[0]] = _nonnegative_decimal(
                    fields[1].encode(), label=f"candidate memory.stat {fields[0]}"
                )
        if set(selected_stats) != tracked:
            raise QualificationError("candidate cgroup memory.stat lacks required counters")
        raw_pressure = _bounded_nofollow_bytes(
            Path("memory.pressure"), max_bytes=1024, dir_fd=directory
        )
        try:
            memory_pressure = raw_pressure.decode("ascii").strip()
        except UnicodeDecodeError as exc:
            raise QualificationError("candidate cgroup memory.pressure is malformed") from exc
        if len(memory_pressure.splitlines()) != 2:
            raise QualificationError("candidate cgroup memory.pressure is incomplete")
        swap_current = _nonnegative_decimal(
            _bounded_nofollow_bytes(
                Path("memory.swap.current"), max_bytes=128, dir_fd=directory
            ),
            label="candidate cgroup memory.swap.current",
        )
        events = _memory_events(
            _bounded_nofollow_bytes(
                Path("memory.events.local"), max_bytes=4096, dir_fd=directory
            )
        )
    finally:
        os.close(directory)
    if (
        _bounded_nofollow_bytes(Path(f"/proc/{pid}/cgroup"), max_bytes=4096)
        != raw_cgroup
    ):
        raise QualificationError("candidate cgroup changed during counter sampling")
    if _process_start_ticks(pid) != process_start_ticks:
        raise QualificationError("candidate process changed during cgroup sampling")
    return {
        "path": expected_relpath,
        "process_start_ticks": process_start_ticks,
        "memory_max_bytes": memory_max_bytes,
        "memory_swap_max_bytes": memory_swap_max_bytes,
        "memory_current_bytes": memory_current_bytes,
        "selected_memory_stat": selected_stats,
        "memory_pressure": memory_pressure,
        "memory_events_local": events,
        "memory_swap_current_bytes": swap_current,
        "memory_events_oom": events["oom"],
        "memory_events_oom_kill": events["oom_kill"],
    }


class MemoryMonitor:
    """One-second memory, cgroup, and phase-attributed paging gate."""

    _TRANSITIONS: ClassVar[dict[str, set[str]]] = {
        "setup": {"load", "restoration"},
        "load": {"ready", "restoration"},
        "ready": {"probes", "restoration"},
        "probes": {"evaluation", "restoration"},
        "evaluation": {"restoration"},
        "restoration": set(),
    }

    def __init__(
        self,
        path: Path,
        ops: HostOps,
        *,
        minimum_gib: float = MIN_MEMORY_GIB,
        interval_s: float = 1,
        reader: Callable[[], float] = _available_gib,
        swap_reader: Callable[[], int] = _pswpout_pages,
        swapin_reader: Callable[[], int] = _pswpin_pages,
        psi_reader: Callable[[], dict[str, int]] = _host_memory_psi_totals,
        cgroup_reader: Callable[[str, int], dict[str, Any]] = _candidate_cgroup_snapshot,
        paging_policy: dict[str, Any] | None = None,
        clock: Callable[[], float] | None = None,
        candidate_spec: CandidateSpec | None = None,
        extended_serving_profile: dict[str, Any] | None = None,
    ):
        self.path = path
        self.ops = ops
        self.candidate_spec = candidate_spec
        self.runtime = _runtime_identity(candidate_spec)
        self.minimum_gib = minimum_gib
        self.interval_s = interval_s
        self.reader = reader
        self.swap_reader = swap_reader
        self.swapin_reader = swapin_reader
        self.psi_reader = psi_reader
        self.cgroup_reader = cgroup_reader
        expected_policy = (candidate_spec.paging_policy() if candidate_spec is not None
                           else PAGING_POLICY)
        self.paging_policy = json.loads(
            canonical_json(paging_policy if paging_policy is not None else expected_policy)
        )
        if self.paging_policy != expected_policy:
            raise QualificationError("memory monitor paging policy differs from the allowlist")
        self.extended_serving_profile = None
        if extended_serving_profile is not None:
            from .evaluation_window import EXTENDED_SERVING_PROFILE

            if extended_serving_profile != EXTENDED_SERVING_PROFILE:
                raise QualificationError("extended serving profile is not registered")
            self.extended_serving_profile = json.loads(canonical_json(
                EXTENDED_SERVING_PROFILE
            ))
        if os.sysconf("SC_PAGE_SIZE") != self.paging_policy["host_page_size_bytes"]:
            raise QualificationError("host page size differs from the paging contract")
        self.clock = clock or time.monotonic
        self.cancel_event = threading.Event()
        self._done = threading.Event()
        self._candidate_id: str | None = None
        self._candidate_pid: int | None = None
        self._candidate_cgroup_path: str | None = None
        self._candidate_start_ticks: int | None = None
        self.candidate_cgroup_bound_path: str | None = None
        self.candidate_cgroup_bound_pid: int | None = None
        self.candidate_cgroup_start_ticks: int | None = None
        self._lock = threading.Lock()
        self._sample_lock = threading.Lock()
        self._record_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._monitor_started_mono: float | None = None
        self._last_sample_mono: float | None = None
        self._phase = "setup"
        self._phase_initial_pswpout: int | None = None
        self._phase_started_at: str | None = None
        self._phase_started_mono: float | None = None
        self._paging_gate = "setup"
        self._gate_initial_pswpout: int | None = None
        # Rolling host-paging windows belong to a policy gate.  In particular,
        # load and ready share the startup history across their phase boundary.
        self._phase_history: deque[tuple[float, int]] = deque()
        self.phase_summaries: dict[str, dict[str, Any]] = {}
        self.minimum_observed_gib = math.inf
        self.failure: str | None = None
        self.violations: list[str] = []
        self.emergency_stop_at: float | None = None
        self.samples = 0
        self.initial_pswpout: int | None = None
        self.final_pswpout: int | None = None
        self.initial_pswpin: int | None = None
        self.final_pswpin: int | None = None
        self.initial_host_psi_totals: dict[str, int] | None = None
        self.final_host_psi_totals: dict[str, int] | None = None
        self.mutation_initial_pswpout: int | None = None
        self.mutation_final_pswpout: int | None = None
        self.mutation_window_started_at: str | None = None
        self.mutation_final_sample_at: str | None = None
        self.startup_initial_pswpout: int | None = None
        self.startup_final_pswpout: int | None = None
        self.setup_quiescence_started_at: str | None = None
        self.setup_quiescence_completed_at: str | None = None
        self.setup_quiescence_duration_seconds: float | None = None
        self.setup_quiescence_initial_pswpout: int | None = None
        self.setup_quiescence_final_pswpout: int | None = None
        self.setup_quiescence_samples = 0
        self.setup_quiescence_passed = False
        self._setup_quiescence_active = False
        self.ready_quiescence_started_at: str | None = None
        self.ready_quiescence_completed_at: str | None = None
        self.ready_quiescence_duration_seconds: float | None = None
        self.ready_quiescence_initial_pswpout: int | None = None
        self.ready_quiescence_final_pswpout: int | None = None
        self.ready_quiescence_samples = 0
        self.ready_quiescence_epoch = 0
        self.ready_quiescence_passed = False
        self._ready_quiescence_active = False
        self._ready_epoch_started_mono: float | None = None
        self.candidate_cgroup_samples = 0
        self.candidate_cgroup_swap_peak_bytes = 0
        self.candidate_cgroup_oom_initial: int | None = None
        self.candidate_cgroup_oom_final: int | None = None
        self.candidate_cgroup_oom_kill_initial: int | None = None
        self.candidate_cgroup_oom_kill_final: int | None = None

    def __enter__(self):
        self._stream = self.path.open("xb")
        self._sample_once()
        self._thread = threading.Thread(
            target=self._loop, name="flash-next-mem-gate", daemon=True
        )
        self._thread.start()
        return self

    def arm(self, candidate_id: str) -> None:
        # Do not publish the armed identity until its clean cgroup binding is
        # durable.  Otherwise the background sampler can emit an armed sample
        # before the binding row needed to interpret it.
        with self._sample_lock:
            with self._lock:
                if self._candidate_id is not None:
                    raise QualificationError("candidate cgroup was already armed")
                if self._phase != "load" or self.mutation_initial_pswpout is None:
                    raise QualificationError(
                        "candidate cgroup binding requires a load-phase sample"
                    )
            candidate = _inspect_container(self.ops, candidate_id)
            if (
                candidate is None
                or candidate.get("id") != candidate_id
                or candidate.get("name") != self.runtime.container_name
                or candidate.get("image") != self.runtime.image_id
                or candidate.get("running") is not True
                or candidate.get("oom_killed") is not False
                or candidate.get("restart_count") != 0
                or candidate.get("memory_limit_bytes") != self.runtime.memory_limit_bytes
                or candidate.get("memory_swap_total_bytes")
                != self.runtime.memory_limit_bytes
                or isinstance(candidate.get("pid"), bool)
                or not isinstance(candidate.get("pid"), int)
                or candidate["pid"] <= 0
            ):
                raise QualificationError("candidate cannot be bound to a live cgroup")
            snapshot = self.cgroup_reader(candidate_id, candidate["pid"])
            if not isinstance(snapshot, dict):
                raise QualificationError("candidate cgroup snapshot is malformed")
            numeric_snapshot = (
                snapshot.get("process_start_ticks"),
                snapshot.get("memory_swap_current_bytes"),
                snapshot.get("memory_max_bytes"),
                snapshot.get("memory_swap_max_bytes"),
                snapshot.get("memory_events_oom"),
                snapshot.get("memory_events_oom_kill"),
            )
            if (
                any(
                    isinstance(value, bool)
                    or not isinstance(value, int)
                    or value < 0
                    for value in numeric_snapshot
                )
                or snapshot.get("process_start_ticks") == 0
                or snapshot.get("memory_swap_current_bytes")
                != self.paging_policy["candidate_cgroup_swap_max_bytes"]
                or snapshot.get("memory_max_bytes") != self.runtime.memory_limit_bytes
                or snapshot.get("memory_swap_max_bytes") != 0
                or snapshot.get("memory_events_oom")
                > self.paging_policy["candidate_cgroup_oom_initial_max"]
                or snapshot.get("memory_events_oom_kill")
                > self.paging_policy["candidate_cgroup_oom_kill_initial_max"]
                or snapshot.get("path")
                != f"/system.slice/docker-{candidate_id}.scope"
            ):
                raise QualificationError("candidate cgroup was not clean at bind time")
            bind_receipt = {
                "schema": "qwen-flash-next-cgroup-bind/v1",
                "observed_at": utc_now(),
                "candidate_id": candidate_id,
                "pid": candidate["pid"],
                "cgroup": snapshot,
            }
            if self.candidate_spec is not None:
                bind_receipt["candidate_spec"] = {
                    "id": self.candidate_spec.spec_id,
                    "spec_sha256": self.candidate_spec.identity_sha256(),
                }
                bind_receipt["container_inspect"] = {
                    key: candidate[key] for key in (
                        "id", "name", "image", "running", "oom_killed",
                        "restart_count", "pid", "memory_limit_bytes",
                        "memory_swap_total_bytes",
                    )
                }
            self._record(bind_receipt)
            with self._lock:
                # Phase changes also use _sample_lock.  Recheck the candidate
                # slot in case an explicit disarm raced the inspection.
                if self._candidate_id is not None or self._phase != "load":
                    raise QualificationError("candidate cgroup bind state changed")
                self._candidate_id = candidate_id
                self._candidate_pid = candidate["pid"]
                self._candidate_cgroup_path = snapshot["path"]
                self._candidate_start_ticks = snapshot["process_start_ticks"]
                self.candidate_cgroup_bound_path = snapshot["path"]
                self.candidate_cgroup_bound_pid = candidate["pid"]
                self.candidate_cgroup_start_ticks = snapshot["process_start_ticks"]
                self.candidate_cgroup_oom_initial = snapshot["memory_events_oom"]
                self.candidate_cgroup_oom_final = snapshot["memory_events_oom"]
                self.candidate_cgroup_oom_kill_initial = snapshot[
                    "memory_events_oom_kill"
                ]
                self.candidate_cgroup_oom_kill_final = snapshot[
                    "memory_events_oom_kill"
                ]
        try:
            self._sample_once()
        except BaseException as exc:  # noqa: BLE001 - an unobservable live candidate is unsafe
            self._breach(f"candidate cgroup monitor failed: {type(exc).__name__}: {exc}")
        self.check()

    def disarm(self) -> None:
        with self._lock:
            self._candidate_id = None
            self._candidate_pid = None
            self._candidate_cgroup_path = None
            self._candidate_start_ticks = None

    def _record(self, row: dict[str, Any]) -> None:
        with self._record_lock:
            self._stream.write(canonical_json(row) + b"\n")
            self._stream.flush()

    def _breach(self, reason: str) -> None:
        with self._lock:
            if reason not in self.violations:
                self.violations.append(reason)
            if self.cancel_event.is_set():
                return
            self.failure = reason
            self.cancel_event.set()
            candidate_id = self._candidate_id
        if candidate_id:
            result = self.ops.run(
                ["docker", "stop", "--time", "10", candidate_id],
                timeout=20,
                check=False,
            )
            self.emergency_stop_at = self.clock()
            self._record(
                {
                    "observed_at": utc_now(),
                    "event": "emergency_candidate_stop",
                    "candidate_id": candidate_id,
                    "returncode": result.returncode,
                }
            )

    def report_external_breach(self, reason: str) -> None:
        """A registered independent operational observer can stop this exact ID."""
        if self.extended_serving_profile is None or not isinstance(reason, str) or not reason:
            raise QualificationError("external operational breach is not an extended window")
        self._breach(reason)

    @staticmethod
    def _window_delta_pages(
        history: deque[tuple[float, int]], now: float, seconds: float
    ) -> int:
        if not history:
            return 0
        boundary = now - seconds
        anchor = history[0][1]
        for observed, pages in history:
            if observed > boundary:
                break
            anchor = pages
        return history[-1][1] - anchor

    @staticmethod
    def _paging_gate_for_phase(phase: str) -> str:
        if phase in {"load", "ready"}:
            return "startup"
        if phase == "probes":
            return "serving"
        if phase == "evaluation":
            return "extended_serving"
        return phase

    def _gate_limits(self, gate: str) -> dict[str, int] | None:
        if gate == "startup":
            return self.paging_policy["load"]
        if gate == "serving":
            return self.paging_policy["serving"]
        if gate == "extended_serving" and self.extended_serving_profile is not None:
            return {
                "window_5s_breach_bytes": self.extended_serving_profile[
                    "host_pswpout_5s_burst_bytes"
                ],
                "window_60s_breach_bytes": self.extended_serving_profile[
                    "host_pswpout_60s_burst_bytes"
                ],
            }
        return None

    def _start_phase_locked(
        self, phase: str, *, pages: int, observed_at: str, observed_mono: float
    ) -> None:
        if phase not in self._TRANSITIONS.get(self._phase, set()):
            raise QualificationError(
                f"memory monitor phase transition {self._phase}->{phase} is invalid"
            )
        if phase == "evaluation" and self.extended_serving_profile is None:
            raise QualificationError("C0 memory monitor cannot enter an extended window")
        self._phase = phase
        self._phase_initial_pswpout = pages
        self._phase_started_at = observed_at
        self._phase_started_mono = observed_mono
        next_gate = self._paging_gate_for_phase(phase)
        if next_gate != self._paging_gate:
            self._paging_gate = next_gate
            self._gate_initial_pswpout = pages
            self._phase_history = deque([(observed_mono, pages)])
        self.phase_summaries[phase] = {
            "started_at": observed_at,
            "completed_at": observed_at,
            "initial_pswpout_pages": pages,
            "final_pswpout_pages": pages,
            "pswpout_delta_pages": 0,
            "pswpout_delta_bytes": 0,
            "max_window_5s_bytes": 0,
            "max_window_60s_bytes": 0,
            "samples": 0,
            "threshold_breached": False,
        }
        if phase == "load":
            self.mutation_initial_pswpout = pages
            self.mutation_final_pswpout = pages
            self.mutation_window_started_at = observed_at
            self.startup_initial_pswpout = pages
            self.startup_final_pswpout = pages
        elif phase == "ready":
            self._ready_quiescence_active = True
            self.ready_quiescence_epoch = 1
            self._ready_epoch_started_mono = observed_mono
            self.ready_quiescence_started_at = observed_at
            self.ready_quiescence_initial_pswpout = pages
            self.ready_quiescence_samples = 0
        elif phase == "restoration":
            self._ready_quiescence_active = False

    def _restart_ready_epoch_locked(
        self, *, pages: int, observed_at: str, observed_mono: float
    ) -> None:
        if self._phase != "ready" or not self._ready_quiescence_active:
            raise QualificationError("ready quiescence epoch is outside the ready phase")
        self.ready_quiescence_epoch += 1
        self._ready_epoch_started_mono = observed_mono
        self.ready_quiescence_started_at = observed_at
        self.ready_quiescence_initial_pswpout = pages
        self.ready_quiescence_samples = 0

    def _complete_ready_locked(
        self, *, pages: int, observed_at: str, observed_mono: float
    ) -> None:
        if (
            self._phase != "ready"
            or not self._ready_quiescence_active
            or self._ready_epoch_started_mono is None
            or self.ready_quiescence_initial_pswpout != pages
            or observed_mono - self._ready_epoch_started_mono
            < READY_QUIESCENCE_SECONDS
        ):
            raise QualificationError("ready quiescence proof is incomplete")
        self._ready_quiescence_active = False
        self.ready_quiescence_completed_at = observed_at
        self.ready_quiescence_final_pswpout = pages
        self.ready_quiescence_duration_seconds = (
            observed_mono - self._ready_epoch_started_mono
        )
        self.ready_quiescence_passed = True
        self._start_phase_locked(
            "probes", pages=pages, observed_at=observed_at, observed_mono=observed_mono
        )

    def _sample_once(
        self,
        *,
        begin_phase: str | None = None,
        begin_quiescence: bool = False,
        end_quiescence: bool = False,
        restart_ready_epoch: bool = False,
        finish_ready: bool = False,
    ) -> dict[str, Any]:
        with self._sample_lock:
            if begin_quiescence and end_quiescence:
                raise QualificationError("setup quiescence markers overlap")
            available = float(self.reader())
            if not math.isfinite(available) or available < 0:
                raise ValueError("invalid MemAvailable")
            pswpout = self.swap_reader()
            if isinstance(pswpout, bool) or not isinstance(pswpout, int) or pswpout < 0:
                raise ValueError("invalid pswpout")
            pswpin = self.swapin_reader()
            if isinstance(pswpin, bool) or not isinstance(pswpin, int) or pswpin < 0:
                raise ValueError("invalid pswpin")
            host_psi = self.psi_reader()
            if (
                not isinstance(host_psi, dict)
                or set(host_psi) != {"some", "full"}
                or any(type(value) is not int or value < 0 for value in host_psi.values())
            ):
                raise ValueError("invalid host memory PSI totals")
            raw_mono = self.clock()
            if (
                isinstance(raw_mono, bool)
                or not isinstance(raw_mono, (int, float))
                or not math.isfinite(float(raw_mono))
                or raw_mono < 0
            ):
                raise ValueError("invalid monotonic sample time")
            observed_mono = float(raw_mono)
            sample_gap_seconds = (
                observed_mono - self._last_sample_mono
                if self._last_sample_mono is not None
                else 0.0
            )
            if sample_gap_seconds < 0:
                raise ValueError("monotonic sample time decreased")
            self._last_sample_mono = observed_mono
            observed_at = utc_now()
            if self._monitor_started_mono is None:
                self._monitor_started_mono = observed_mono

            with self._lock:
                if self.initial_pswpout is None:
                    self.initial_pswpout = pswpout
                    self.final_pswpout = pswpout
                    self.initial_pswpin = pswpin
                    self.final_pswpin = pswpin
                    self.initial_host_psi_totals = dict(host_psi)
                    self.final_host_psi_totals = dict(host_psi)
                    self._phase_initial_pswpout = pswpout
                    self._phase_started_at = observed_at
                    self._phase_started_mono = observed_mono
                    self._paging_gate = "setup"
                    self._gate_initial_pswpout = pswpout
                    self._phase_history = deque([(observed_mono, pswpout)])
                    self.phase_summaries["setup"] = {
                        "started_at": observed_at,
                        "completed_at": observed_at,
                        "initial_pswpout_pages": pswpout,
                        "final_pswpout_pages": pswpout,
                        "pswpout_delta_pages": 0,
                        "pswpout_delta_bytes": 0,
                        "max_window_5s_bytes": 0,
                        "max_window_60s_bytes": 0,
                        "samples": 0,
                        "threshold_breached": False,
                    }
                previous_pswpout = self.final_pswpout
                if previous_pswpout is None:
                    raise QualificationError("memory monitor prior counter is absent")
                if pswpout < previous_pswpout:
                    raise ValueError("pswpout decreased during one boot")
                if (
                    self.final_pswpin is None
                    or self.final_host_psi_totals is None
                    or pswpin < self.final_pswpin
                    or any(
                        host_psi[key] < self.final_host_psi_totals[key]
                        for key in ("some", "full")
                    )
                ):
                    raise ValueError("host pswpin or memory PSI counter decreased")
                if begin_phase is not None:
                    if begin_phase == "load" and (
                        not self.setup_quiescence_passed
                        or self.setup_quiescence_final_pswpout is None
                        or pswpout != self.setup_quiescence_final_pswpout
                    ):
                        raise QualificationError(
                            "host pswpout changed after setup quiescence"
                        )
                    prior_pages = self.final_pswpout
                    if prior_pages is None:
                        raise QualificationError("memory phase has no prior sample")
                    self._start_phase_locked(
                        begin_phase,
                        pages=prior_pages,
                        observed_at=observed_at,
                        observed_mono=observed_mono,
                    )
                    if begin_phase == "ready":
                        # Attribute any transition-gap pages to the ready phase,
                        # while beginning the quiet epoch at this observed raw
                        # counter rather than forgiving later growth.
                        self.ready_quiescence_initial_pswpout = pswpout
                if begin_quiescence:
                    if self._setup_quiescence_active or self._phase != "setup":
                        raise QualificationError("setup quiescence was already active")
                    self._setup_quiescence_active = True
                if restart_ready_epoch:
                    self._restart_ready_epoch_locked(
                        pages=pswpout,
                        observed_at=observed_at,
                        observed_mono=observed_mono,
                    )
                phase = self._phase
                phase_initial = self._phase_initial_pswpout
                phase_started_mono = self._phase_started_mono
                paging_gate = self._paging_gate
                gate_initial = self._gate_initial_pswpout
                setup_active = self._setup_quiescence_active
                ready_active = self._ready_quiescence_active
                ready_epoch = self.ready_quiescence_epoch
                candidate_id = self._candidate_id
                candidate_pid = self._candidate_pid
                candidate_cgroup_path = self._candidate_cgroup_path
                candidate_start_ticks = self._candidate_start_ticks

            if (
                phase_initial is None
                or phase_started_mono is None
                or gate_initial is None
            ):
                raise QualificationError("memory phase or paging-gate baseline is absent")
            self.samples += 1
            self.minimum_observed_gib = min(self.minimum_observed_gib, available)
            self.final_pswpout = pswpout
            self.final_pswpin = pswpin
            self.final_host_psi_totals = dict(host_psi)
            if self.mutation_initial_pswpout is not None:
                self.mutation_final_pswpout = pswpout
                self.mutation_final_sample_at = observed_at
            if paging_gate == "startup":
                self.startup_final_pswpout = pswpout
            if setup_active:
                self.setup_quiescence_samples += 1
            if ready_active:
                self.ready_quiescence_samples += 1

            self._phase_history.append((observed_mono, pswpout))
            while (
                len(self._phase_history) > 1
                and self._phase_history[1][0] <= observed_mono - 60
            ):
                self._phase_history.popleft()
            delta_5_pages = self._window_delta_pages(
                self._phase_history, observed_mono, 5
            )
            delta_60_pages = self._window_delta_pages(
                self._phase_history, observed_mono, 60
            )
            phase_delta_pages = pswpout - phase_initial
            gate_delta_pages = pswpout - gate_initial
            if min(
                delta_5_pages,
                delta_60_pages,
                phase_delta_pages,
                gate_delta_pages,
            ) < 0:
                raise ValueError("phase or paging-gate pswpout delta became negative")
            page_size = self.paging_policy["host_page_size_bytes"]
            delta_5_bytes = delta_5_pages * page_size
            delta_60_bytes = delta_60_pages * page_size
            phase_delta_bytes = phase_delta_pages * page_size
            gate_delta_bytes = gate_delta_pages * page_size
            summary = self.phase_summaries[phase]
            summary.update(
                {
                    "completed_at": observed_at,
                    "final_pswpout_pages": pswpout,
                    "pswpout_delta_pages": phase_delta_pages,
                    "pswpout_delta_bytes": phase_delta_bytes,
                    "max_window_5s_bytes": max(
                        summary["max_window_5s_bytes"], delta_5_bytes
                    ),
                    "max_window_60s_bytes": max(
                        summary["max_window_60s_bytes"], delta_60_bytes
                    ),
                    "samples": summary["samples"] + 1,
                }
            )

            row: dict[str, Any] = {
                "schema": "qwen-flash-next-memory-sample/v3",
                "observed_at": observed_at,
                "elapsed_monotonic_seconds": observed_mono
                - self._monitor_started_mono,
                "sample_gap_seconds": sample_gap_seconds,
                "monitor_phase": phase,
                "paging_gate": paging_gate,
                "setup_quiescence_active": setup_active,
                "ready_quiescence_active": ready_active,
                "ready_quiescence_epoch": ready_epoch if ready_active else None,
                "mem_available_gib": available,
                "host_meminfo_kib": _host_meminfo_diagnostics(),
                "host_page_size_bytes": page_size,
                "pswpout_pages": pswpout,
                "pswpout_delta_pages": pswpout - self.initial_pswpout,
                "pswpin_pages": pswpin,
                "pswpin_delta_pages": pswpin - self.initial_pswpin,
                "host_memory_psi_total_us": dict(host_psi),
                "host_memory_psi_delta_us": {
                    key: host_psi[key] - self.initial_host_psi_totals[key]
                    for key in ("some", "full")
                },
                "phase_initial_pswpout_pages": phase_initial,
                "phase_pswpout_delta_pages": phase_delta_pages,
                "phase_pswpout_delta_bytes": phase_delta_bytes,
                "gate_initial_pswpout_pages": gate_initial,
                "gate_pswpout_delta_pages": gate_delta_pages,
                "gate_pswpout_delta_bytes": gate_delta_bytes,
                "host_swap_5s_bytes": delta_5_bytes,
                "host_swap_60s_bytes": delta_60_bytes,
                "transition_to": None,
            }
            breach_reasons: list[str] = []
            if sample_gap_seconds > self.paging_policy["max_sample_gap_seconds"]:
                breach_reasons.append("memory monitor exceeded the sample-gap limit")
            if candidate_id:
                candidate = _inspect_container(self.ops, candidate_id)
                candidate_row: dict[str, Any] = {
                    "id": candidate_id,
                    "armed": None,
                    "running": candidate.get("running") if candidate else None,
                    "oom_killed": candidate.get("oom_killed") if candidate else None,
                    "restart_count": candidate.get("restart_count") if candidate else None,
                    "pid": candidate.get("pid") if candidate else None,
                    "cgroup": None,
                }
                if self.candidate_spec is not None:
                    candidate_row.update({
                        "name": candidate.get("name") if candidate else None,
                        "image": candidate.get("image") if candidate else None,
                        "memory_limit_bytes": candidate.get("memory_limit_bytes") if candidate else None,
                        "memory_swap_total_bytes": candidate.get("memory_swap_total_bytes") if candidate else None,
                    })
                with self._lock:
                    still_armed = self._candidate_id == candidate_id
                candidate_row["armed"] = still_armed
                if still_armed:
                    if self.candidate_spec is not None and (
                        candidate is None
                        or candidate.get("name") != self.runtime.container_name
                        or candidate.get("image") != self.runtime.image_id
                        or candidate.get("memory_limit_bytes") != self.runtime.memory_limit_bytes
                        or candidate.get("memory_swap_total_bytes") != self.runtime.memory_limit_bytes
                    ):
                        breach_reasons.append("Mia candidate name, image or Docker memory controls changed")
                    if candidate is None or not candidate.get("running"):
                        breach_reasons.append(
                            "candidate disappeared or stopped while qualified runtime was armed"
                        )
                    elif candidate.get("oom_killed"):
                        breach_reasons.append("candidate container reports OOMKilled")
                    elif candidate.get("restart_count") != 0:
                        breach_reasons.append("candidate container restart count changed")
                    elif candidate.get("pid") != candidate_pid:
                        breach_reasons.append("candidate process identity changed")
                    else:
                        try:
                            snapshot = self.cgroup_reader(candidate_id, candidate_pid)
                        except BaseException:
                            with self._lock:
                                still_armed = self._candidate_id == candidate_id
                            if still_armed:
                                raise
                            snapshot = None
                        with self._lock:
                            still_armed = self._candidate_id == candidate_id
                        candidate_row["armed"] = still_armed
                        if still_armed and snapshot is not None:
                            candidate_row["cgroup"] = snapshot
                            if snapshot.get("path") != candidate_cgroup_path:
                                breach_reasons.append("candidate cgroup identity changed")
                            if (
                                snapshot.get("process_start_ticks")
                                != candidate_start_ticks
                            ):
                                breach_reasons.append(
                                    "candidate process start identity changed"
                                )
                            if (
                                snapshot.get("memory_max_bytes")
                                != self.runtime.memory_limit_bytes
                                or snapshot.get("memory_swap_max_bytes") != 0
                            ):
                                breach_reasons.append(
                                    "candidate cgroup 96 GiB/no-swap controls changed"
                                )
                            swap_current = snapshot.get("memory_swap_current_bytes")
                            oom = snapshot.get("memory_events_oom")
                            oom_kill = snapshot.get("memory_events_oom_kill")
                            if (
                                isinstance(swap_current, bool)
                                or not isinstance(swap_current, int)
                                or swap_current < 0
                                or isinstance(oom, bool)
                                or not isinstance(oom, int)
                                or oom < 0
                                or isinstance(oom_kill, bool)
                                or not isinstance(oom_kill, int)
                                or oom_kill < 0
                            ):
                                breach_reasons.append("candidate cgroup counters are malformed")
                            else:
                                self.candidate_cgroup_samples += 1
                                self.candidate_cgroup_swap_peak_bytes = max(
                                    self.candidate_cgroup_swap_peak_bytes,
                                    swap_current,
                                )
                                self.candidate_cgroup_oom_final = oom
                                self.candidate_cgroup_oom_kill_final = oom_kill
                                if swap_current != 0:
                                    breach_reasons.append(
                                        "candidate cgroup memory.swap.current is nonzero"
                                    )
                                if (
                                    oom - self.candidate_cgroup_oom_initial
                                    > self.paging_policy[
                                        "candidate_cgroup_oom_max_delta"
                                    ]
                                ):
                                    breach_reasons.append(
                                        "candidate cgroup OOM event counter changed"
                                    )
                                if (
                                    oom_kill - self.candidate_cgroup_oom_kill_initial
                                    > self.paging_policy[
                                        "candidate_cgroup_oom_kill_max_delta"
                                    ]
                                ):
                                    breach_reasons.append(
                                        "candidate cgroup OOM-kill counter changed"
                                    )
                row["candidate"] = candidate_row

            limits = self._gate_limits(paging_gate)
            if limits is not None:
                if delta_5_bytes >= limits["window_5s_breach_bytes"]:
                    breach_reasons.append(
                        f"{paging_gate} host swap reached the 5-second byte threshold"
                    )
                if delta_60_bytes >= limits["window_60s_breach_bytes"]:
                    breach_reasons.append(
                        f"{paging_gate} host swap reached the 60-second byte threshold"
                    )
                if (paging_gate != "extended_serving" and
                    gate_delta_bytes >= limits["phase_total_breach_bytes"]):
                    breach_reasons.append(
                        f"{paging_gate} host swap reached the gate-total byte threshold"
                    )
            if breach_reasons:
                summary["threshold_breached"] = True
            if finish_ready:
                with self._lock:
                    can_finish = (
                        self._phase == "ready"
                        and self._ready_epoch_started_mono is not None
                        and self.ready_quiescence_initial_pswpout == pswpout
                        and observed_mono - self._ready_epoch_started_mono
                        >= READY_QUIESCENCE_SECONDS
                    )
                if can_finish:
                    row["transition_to"] = "probes"

            self._record(row)
            if available < self.minimum_gib:
                breach_reasons.append(
                    f"MemAvailable {available:.3f} GiB fell below {self.minimum_gib} GiB"
                )
            for reason in breach_reasons:
                self._breach(reason)
            if end_quiescence:
                with self._lock:
                    if not self._setup_quiescence_active:
                        raise QualificationError("setup quiescence was not active")
                    self._setup_quiescence_active = False
            if finish_ready and row["transition_to"] == "probes":
                with self._lock:
                    self._complete_ready_locked(
                        pages=pswpout,
                        observed_at=observed_at,
                        observed_mono=observed_mono,
                    )
            return row

    def require_setup_quiescence(self, *, duration_s: int, deadline: float) -> None:
        if duration_s != SETUP_QUIESCENCE_SECONDS:
            raise QualificationError("setup quiescence duration is not registered")
        requested_mono = self.clock()
        if requested_mono + duration_s > deadline:
            raise QualificationError("setup quiescence would consume the work deadline")
        with self._lock:
            if self.mutation_initial_pswpout is not None:
                raise QualificationError("setup quiescence began after mutation baseline")
        first: dict[str, Any] | None = None
        last: dict[str, Any] | None = None
        try:
            first = self._sample_once(begin_quiescence=True)
            self.setup_quiescence_started_at = first["observed_at"]
            self.setup_quiescence_initial_pswpout = first["pswpout_pages"]
            started_mono = self.clock()
            if started_mono + duration_s > deadline:
                raise QualificationError(
                    "setup quiescence would consume the work deadline"
                )
            end = started_mono + duration_s
            while self.clock() < end:
                self.check()
                time.sleep(min(self.interval_s, max(0.0, end - self.clock())))
                if self.clock() >= end:
                    break
                last = self._sample_once()
                if last["pswpout_pages"] != first["pswpout_pages"]:
                    raise QualificationError(
                        "host pswpout changed during the 60-second setup quiescence"
                    )
            last = self._sample_once(end_quiescence=True)
            if last["pswpout_pages"] != first["pswpout_pages"]:
                raise QualificationError(
                    "host pswpout changed during the 60-second setup quiescence"
                )
            self.check()
            self.setup_quiescence_completed_at = last["observed_at"]
            self.setup_quiescence_final_pswpout = last["pswpout_pages"]
            self.setup_quiescence_duration_seconds = max(
                0.0, self.clock() - started_mono
            )
            self.setup_quiescence_passed = (
                self.setup_quiescence_duration_seconds >= duration_s
                and self.setup_quiescence_initial_pswpout
                == self.setup_quiescence_final_pswpout
            )
            if not self.setup_quiescence_passed:
                raise QualificationError("setup quiescence proof is incomplete")
        finally:
            if last is not None and self.setup_quiescence_completed_at is None:
                self.setup_quiescence_completed_at = last["observed_at"]
                self.setup_quiescence_final_pswpout = last["pswpout_pages"]
                self.setup_quiescence_duration_seconds = max(
                    0.0, self.clock() - requested_mono
                )
            with self._lock:
                self._setup_quiescence_active = False

    def begin_mutation_window(self) -> None:
        if not self.setup_quiescence_passed:
            raise QualificationError("mutation baseline requires setup quiescence proof")
        self.check()
        self._sample_once(begin_phase="load")
        self.check()

    def require_ready_quiescence(self, *, duration_s: int, deadline: float) -> None:
        """Find one contiguous post-/models interval with zero host swap growth."""
        if duration_s != READY_QUIESCENCE_SECONDS:
            raise QualificationError("ready quiescence duration is not registered")
        first = self._sample_once(begin_phase="ready")
        baseline_pages = first["pswpout_pages"]
        while self.clock() < deadline:
            self.check()
            remaining = deadline - self.clock()
            if remaining <= 0:
                break
            time.sleep(min(self.interval_s, remaining))
            finish = (
                self._ready_epoch_started_mono is not None
                and self.clock() - self._ready_epoch_started_mono >= duration_s
            )
            row = self._sample_once(finish_ready=finish)
            self.check()
            if self._phase == "probes":
                return
            if row["pswpout_pages"] != baseline_pages:
                row = self._sample_once(restart_ready_epoch=True)
                baseline_pages = row["pswpout_pages"]
        raise QualificationError(
            "no contiguous 60-second zero-swap interval fit before the readiness deadline"
        )

    def begin_restoration(self) -> None:
        with self._lock:
            if self._phase == "restoration":
                return
        self._sample_once(begin_phase="restoration")

    def begin_evaluation(self) -> None:
        """Start the separately registered long-serving rate gate after probes."""
        with self._lock:
            if self._phase != "probes" or self.extended_serving_profile is None:
                raise QualificationError("long-serving phase requires validated probes")
        if not self.ready_quiescence_passed:
            raise QualificationError("long-serving phase lacks the fresh ready quiet proof")
        self.check()
        self._sample_once(begin_phase="evaluation")
        self.check()

    def _loop(self) -> None:
        while not self._done.is_set():
            try:
                self._sample_once()
            except BaseException as exc:  # noqa: BLE001 - any monitor fault must stop the candidate
                self._breach(f"memory monitor failed: {type(exc).__name__}: {exc}")
            self._done.wait(self.interval_s)

    def check(self) -> None:
        raw_mono = self.clock()
        if (
            isinstance(raw_mono, bool)
            or not isinstance(raw_mono, (int, float))
            or not math.isfinite(float(raw_mono))
            or raw_mono < 0
        ):
            self._breach("memory monitor clock is invalid")
        elif self._last_sample_mono is not None:
            if float(raw_mono) < self._last_sample_mono:
                self._breach("memory monitor clock decreased")
            elif (
                float(raw_mono) - self._last_sample_mono
                > self.paging_policy["max_sample_gap_seconds"]
            ):
                self._breach("memory monitor is stale beyond the sample-gap limit")
        if self.cancel_event.is_set():
            raise QualificationError(self.failure or "memory gate canceled the qualification")

    def __exit__(self, exc_type, exc, traceback):
        self._done.set()
        if self._thread is not None:
            self._thread.join(timeout=max(2, self.interval_s + 1))
        try:
            if self._phase != "restoration":
                self.begin_restoration()
            self._sample_once()
        except BaseException as monitor_exc:  # noqa: BLE001 - final evidence is fail-closed
            self._breach(
                f"memory monitor failed: {type(monitor_exc).__name__}: {monitor_exc}"
            )
        self._stream.flush()
        os.fsync(self._stream.fileno())
        self._stream.close()


def _open_nofollow_regular(path: Path) -> int:
    """Open a fixed absolute path through stable nofollow directory FDs."""
    if not path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts[1:]):
        raise QualificationError("regular-file path is not fixed and absolute")
    parent = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in path.parts[1:-1]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=parent)
            os.close(parent)
            parent = child
        return os.open(path.name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW,
                       dir_fd=parent)
    finally:
        os.close(parent)


def _hash_regular_file(path: Path, expected_size: int, monitor=None) -> str:
    descriptor = _open_nofollow_regular(path)
    try:
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode) or details.st_size != expected_size:
            raise QualificationError(f"model file size/type mismatch: {path.name}")
        digest = hashlib.sha256()
        while True:
            chunk = os.read(descriptor, 16 * 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            if monitor is not None:
                monitor.check()
        final = os.fstat(descriptor)
        if (not stat.S_ISREG(final.st_mode) or final.st_size != details.st_size
            or final.st_mtime_ns != details.st_mtime_ns or final.st_ino != details.st_ino):
            raise QualificationError(f"model file changed during hashing: {path.name}")
        if hasattr(os, "posix_fadvise") and hasattr(os, "POSIX_FADV_DONTNEED"):
            try:
                os.posix_fadvise(descriptor, 0, 0, os.POSIX_FADV_DONTNEED)
            except OSError:
                pass
        return digest.hexdigest()
    finally:
        os.close(descriptor)


def _verify_small_source_receipt(
    path: Path, expected_sha256: str, expected_bytes: int, monitor=None
) -> dict[str, Any]:
    descriptor = _open_nofollow_regular(path)
    try:
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode) or details.st_size != expected_bytes:
            raise QualificationError(f"candidate source receipt is not bounded: {path.name}")
        raw = os.read(descriptor, details.st_size + 1)
        final = os.fstat(descriptor)
        if (len(raw) != details.st_size or final.st_size != details.st_size
            or final.st_mtime_ns != details.st_mtime_ns):
            raise QualificationError(f"candidate source receipt changed: {path.name}")
        if sha256(raw) != expected_sha256:
            raise QualificationError(f"candidate source receipt SHA differs: {path.name}")
        _strict_json(raw, source=f"candidate source receipt {path.name}")
        if monitor is not None:
            monitor.check()
        return {"path": str(path), "sha256": expected_sha256, "bytes": len(raw)}
    finally:
        os.close(descriptor)


def verify_model(
    contract: dict[str, Any], monitor=None, *, spec: CandidateSpec | None = None
) -> dict[str, Any]:
    runtime = _runtime_identity(spec)
    path = Path(contract["model"]["host_path"])
    if path.is_symlink() or not path.is_dir() or path.resolve() != runtime.model_path:
        raise QualificationError("model directory is absent or redirected")
    if list(path.rglob("*.incomplete")):
        raise QualificationError("model download contains incomplete files")
    top_level = list(path.iterdir())
    if any(item.is_symlink() for item in top_level):
        raise QualificationError("model directory contains a redirected top-level entry")
    actual_files = {item.name for item in top_level if item.is_file()}
    actual_directories = {item.name for item in top_level if item.is_dir()}
    expected_directories = {".cache"} if runtime.cache_metadata_required else set()
    if actual_files != set(contract["model"]["files"]) or actual_directories != expected_directories:
        raise QualificationError("model repository file set differs from the exact revision")
    if sum(item["bytes"] for item in contract["model"]["files"].values()) != runtime.model_repository_bytes:
        raise QualificationError("model repository byte total differs from the manifest")
    actual_weights = {item.name for item in path.glob("*.safetensors")}
    if actual_weights != runtime.weight_files:
        raise QualificationError("safetensor file set differs from the manifest")
    verified = {}
    for name, item in contract["model"]["files"].items():
        digest = _hash_regular_file(path / name, item["bytes"], monitor)
        if digest != item["sha256"]:
            raise QualificationError(f"model content digest mismatch: {name}")
        verified[name] = {"bytes": item["bytes"], "sha256": digest}
        if runtime.cache_metadata_required:
            metadata = path / ".cache" / "huggingface" / "download" / f"{name}.metadata"
            if not metadata.is_file() or metadata.is_symlink():
                raise QualificationError(f"download metadata absent: {name}")
            lines = metadata.read_text().splitlines()
            if not lines or lines[0] != runtime.model_revision:
                raise QualificationError(f"download revision mismatch: {name}")
            if name in runtime.weight_files and (len(lines) < 2 or lines[1] != item["sha256"]):
                raise QualificationError(f"download content id mismatch: {name}")
    index_item = verified["model.safetensors.index.json"]
    descriptor = _open_nofollow_regular(path / "model.safetensors.index.json")
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size != index_item["bytes"]:
            raise QualificationError("model index changed after verification")
        index_raw = os.read(descriptor, info.st_size + 1)
        if len(index_raw) != info.st_size or sha256(index_raw) != index_item["sha256"]:
            raise QualificationError("model index bytes changed after verification")
    finally:
        os.close(descriptor)
    index = _strict_json(index_raw, source="model index", max_bytes=40_000_000)
    if set(index) != {"metadata", "weight_map"}:
        raise QualificationError("model index shape differs")
    if index["metadata"] != {"total_size": runtime.model_index_total_bytes}:
        raise QualificationError("model tensor payload size differs")
    weight_map = index["weight_map"]
    if not isinstance(weight_map, dict) or set(weight_map.values()) != runtime.indexed_weight_files:
        raise QualificationError("model index shard mapping differs")
    receipt = {
        "artifact_sha256": runtime.model_artifact_sha256,
        "safetensors_total_bytes": sum(item["bytes"] for name, item in verified.items()
                                           if name in runtime.weight_files),
        "verified_files": verified,
        "verified_at": utc_now(),
        "full_sha256": True,
    }
    if spec is not None:
        proofs = {}
        for name, proof_path, proof_sha, proof_bytes in (
            ("acquisition", spec.acquisition_receipt_path,
             spec.acquisition_receipt_sha256, spec.acquisition_receipt_bytes),
            ("image_build", spec.image_build_receipt_path,
             spec.image_build_receipt_sha256, spec.image_build_receipt_bytes),
            ("ple_build", spec.ple_build_receipt_path,
             spec.ple_build_receipt_sha256, spec.ple_build_receipt_bytes),
        ):
            proofs[name] = _verify_small_source_receipt(
                proof_path, proof_sha, proof_bytes, monitor
            )
        if (runtime.packed_ple_path is None or runtime.packed_ple_bytes is None
            or runtime.packed_ple_sha256 is None):
            raise QualificationError("registered packed PLE is absent")
        packed_sha = _hash_regular_file(runtime.packed_ple_path,
                                        runtime.packed_ple_bytes, monitor)
        if packed_sha != runtime.packed_ple_sha256:
            raise QualificationError("registered packed PLE content differs")
        receipt["candidate"] = {"id": spec.spec_id,
                                "spec_sha256": spec.identity_sha256()}
        receipt["proof_receipts"] = proofs
        receipt["packed_ple"] = {"path": str(runtime.packed_ple_path),
                                 "bytes": runtime.packed_ple_bytes,
                                 "sha256": packed_sha}
        if spec.draft_vocab_path is not None:
            draft_sha = _hash_regular_file(
                spec.draft_vocab_path, spec.draft_vocab_bytes, monitor
            )
            if draft_sha != spec.draft_vocab_sha256:
                raise QualificationError("registered reduced draft vocabulary content differs")
            receipt["reduced_draft_vocab"] = {
                "path": str(spec.draft_vocab_path), "bytes": spec.draft_vocab_bytes,
                "sha256": draft_sha, "id_count": spec.draft_vocab_id_count,
            }
    return receipt


def _append_research_usage(row: dict[str, Any], ledger: Path = RESEARCH_LEDGER) -> None:
    if ledger.name == WEEKLY_LEDGER_BASENAME or ledger != RESEARCH_LEDGER:
        raise QualificationError("research usage cannot target the weekly budget ledger")
    if ledger.parent.is_symlink() or not ledger.parent.is_dir():
        raise QualificationError("research journal parent is absent or redirected")
    if ledger.exists() and (ledger.is_symlink() or not ledger.is_file()):
        raise QualificationError("research journal is redirected")
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(ledger, flags, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        os.write(descriptor, canonical_json(row) + b"\n")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _ensure_compile_cache(spec: CandidateSpec | None = None) -> None:
    runtime = _runtime_identity(spec)
    parent = runtime.compile_cache.parent
    if parent != runtime.compile_cache_parent:
        raise QualificationError("compile-cache parent is outside the allowlist")
    if (
        not parent.exists()
        or parent.is_symlink()
        or not parent.is_dir()
        or parent.resolve() != parent
    ):
        raise QualificationError("compile-cache parent is absent or redirected")
    if parent.stat().st_uid != os.getuid():
        raise QualificationError("compile-cache parent is not owned by the invoking account")
    if runtime.compile_cache.exists() and (runtime.compile_cache.is_symlink()
                                           or not runtime.compile_cache.is_dir()):
        raise QualificationError("compile-cache path is redirected")
    runtime.compile_cache.mkdir(mode=0o755, exist_ok=True)


def _assert_port_free(spec: CandidateSpec | None = None) -> None:
    runtime = _runtime_identity(spec)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", runtime.host_port))
        except OSError as exc:
            raise QualificationError("candidate loopback port is occupied") from exc


def _capture_initial_state(ops: HostOps, preflight: dict[str, Any]) -> dict[str, Any]:
    expected_runtime = {row["id"]: row for row in preflight.get("runtime_identity", [])}
    residents = []
    for expected in RESIDENTS:
        row = _inspect_container(ops, expected["name"])
        if row is None:
            raise QualificationError(f"resident container is absent: {expected['name']}")
        if (
            row["id"] != expected["id"]
            or row["image"] != expected["image_id"]
            or row["name"] != expected["name"]
            or row["restart_policy"] != "unless-stopped"
            or row.get("running") is not True
            or row.get("oom_killed") is not False
            or row.get("state_error") != ""
            or isinstance(row.get("restart_count"), bool)
            or not isinstance(row.get("restart_count"), int)
            or row["restart_count"] < 0
            or row["id"] not in expected_runtime
        ):
            raise QualificationError(f"resident identity/state drift: {expected['name']}")
        residents.append(row)
    nara = _service_state(ops)
    return {
        "captured_at": utc_now(),
        "residents": residents,
        "nara": nara,
        "nara_was_active": nara["ActiveState"] == "active",
    }


def _wait_candidate_ready(
    ops: HostOps, monitor: MemoryMonitor, *, deadline: float,
    spec: CandidateSpec | None = None,
) -> dict[str, Any]:
    runtime = _runtime_identity(spec)
    last_error = "not probed"
    while time.monotonic() < deadline:
        monitor.check()
        row = _inspect_container(ops, runtime.container_name)
        if (
            row is None
            or not row.get("running")
            or row.get("oom_killed")
            or row.get("restart_count") != 0
        ):
            raise QualificationError("candidate stopped, restarted, or OOM-killed before readiness")
        try:
            ops.http_bytes(f"http://127.0.0.1:{runtime.host_port}/health", timeout=2)
            raw = ops.http_bytes(f"http://127.0.0.1:{runtime.host_port}/v1/models", timeout=2)
            models = _strict_json(raw, source="candidate /v1/models")
            data = models.get("data")
            identifiers = [item.get("id") for item in data] if isinstance(data, list) else []
            if identifiers != [runtime.served_model]:
                raise QualificationError("candidate model list is not the exact served identity")
            return {"ready_at": utc_now(), "models": identifiers, "container": row}
        except Exception as exc:  # noqa: BLE001 - bounded readiness poll records its final error
            last_error = f"{type(exc).__name__}: {exc}"
        time.sleep(min(2, max(0, deadline - time.monotonic())))
    raise QualificationError(f"candidate readiness deadline expired ({last_error})")


def _probe_private_response(
    output: Path, probe_id: str, evidence: dict[str, Any]
) -> dict[str, Any]:
    """Keep the bounded SSE bytes private and expose only their digest."""
    from bench.flash_next_ab.transport import MAX_RESPONSE_BYTES

    raw = evidence.get("raw_response_stream")
    if not isinstance(raw, bytes) or len(raw) > MAX_RESPONSE_BYTES:
        raise QualificationError(f"private probe stream is malformed: {probe_id}")
    if evidence.get("response_stream_sha256") != sha256(raw):
        raise QualificationError(f"private probe stream digest differs: {probe_id}")
    private = output / "private-probes"
    private.mkdir(mode=0o700, exist_ok=True)
    if private.is_symlink() or private.stat().st_mode & 0o077:
        raise QualificationError("private probe directory permissions differ")
    path = private / f"{probe_id}.sse"
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(private, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return {
        "response_stream_sha256": sha256(raw),
        "response_stream_bytes": len(raw),
        "private_stream_relpath": f"private-probes/{probe_id}.sse",
    }


def _run_probes(
    ops: HostOps, monitor: MemoryMonitor, *, timeout_s: int, output: Path,
    spec: CandidateSpec | None = None,
) -> list[dict[str, Any]]:
    runtime = _runtime_identity(spec)
    from bench.flash_next_ab.transport import LocalEndpoint
    probe_set = spec.qualification_probe_set if spec is not None else "flash-next-minimal-v1"

    endpoint = LocalEndpoint(
        spec.endpoint_name if spec is not None else "flash_next",
        f"http://127.0.0.1:{runtime.host_port}/v1",
        runtime.served_model, runtime.model_artifact_sha256,
    )
    policy = {"temperature": 0, "top_p": 1, "enable_thinking": False}
    specifications = [
        {
            "id": "exact_literal",
            "messages": [{"role": "user", "content": "Reply with exactly FLASH_NEXT_OK_17 and nothing else."}],
            "max_tokens": 32,
            "expected": "FLASH_NEXT_OK_17",
        },
        {
            "id": "exact_arithmetic",
            "messages": [{"role": "user", "content": "Return only the integer result of 37 * 19."}],
            "max_tokens": 32,
            "expected": "703",
        },
    ]
    results: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []

    def attempt(probe_id: str, messages: list[dict[str, str]], max_tokens: int,
                seed: int, tools: list[dict[str, Any]] | None = None
                ) -> dict[str, Any]:
        row: dict[str, Any] = {
            "probe_id": probe_id, "status": "started", "started_at": utc_now()
        }
        attempts.append(row)
        _atomic_write(output / "probe-attempts.json", {
            "schema": "qwen-flash-next-probe-attempts/v1",
            "probe_set": probe_set, "results": attempts,
        })
        try:
            monitor.check()
            result = ops.complete(
                endpoint, messages, policy=policy, max_tokens=max_tokens,
                timeout_s=timeout_s, seed=seed, tools=tools,
                cancel_event=monitor.cancel_event,
            )
        except Exception as exc:  # every attempted probe has a durable outcome
            attached = getattr(exc, "private_evidence", None)
            if isinstance(attached, dict):
                row["private_response"] = _probe_private_response(
                    output, probe_id, attached
                )
            row.update({"status": "transport_error", "error_type": type(exc).__name__,
                        "finished_at": utc_now()})
            _atomic_write(output / "probe-attempts.json", {
                "schema": "qwen-flash-next-probe-attempts/v1",
                "probe_set": probe_set, "results": attempts,
            })
            raise
        if not isinstance(result, dict):
            row.update({"status": "malformed_response", "finished_at": utc_now()})
            _atomic_write(output / "probe-attempts.json", {
                "schema": "qwen-flash-next-probe-attempts/v1",
                "probe_set": probe_set, "results": attempts,
            })
            raise QualificationError(f"fixed probe response is malformed: {probe_id}")
        evidence = result.get("private_evidence")
        if evidence is not None:
            if not isinstance(evidence, dict):
                raise QualificationError(f"private probe evidence is malformed: {probe_id}")
            row["private_response"] = _probe_private_response(output, probe_id, evidence)
            if result.get("response_stream_sha256") != row["private_response"]["response_stream_sha256"]:
                raise QualificationError(f"public and private probe stream digests differ: {probe_id}")
            result = {key: value for key, value in result.items() if key != "private_evidence"}
        public = {"probe_id": probe_id, **result}
        row["response"] = public
        row["finished_at"] = utc_now()
        return public

    def record(status: str) -> None:
        attempts[-1]["status"] = status
        _atomic_write(output / "probe-attempts.json", {
            "schema": "qwen-flash-next-probe-attempts/v1",
            "probe_set": probe_set, "results": attempts,
        })

    for ordinal, request_spec in enumerate(specifications):
        result = attempt(request_spec["id"], request_spec["messages"], request_spec["max_tokens"], 17 + ordinal)
        valid = (
            result.get("response_model") == runtime.served_model
            and isinstance(result.get("content"), str)
            and result["content"].strip() == request_spec["expected"]
            and not result.get("tool_calls")
            and result.get("finish_reason") == "stop"
        )
        record("passed" if valid else "failed")
        if not valid:
            raise QualificationError(f"fixed probe failed: {request_spec['id']}")
        results.append(result)

    tools = [{
        "type": "function",
        "function": {
            "name": "record_probe",
            "description": "Record the fixed local qualification value.",
            "parameters": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "value": {"type": "integer"},
                },
                "required": ["label", "value"],
                "additionalProperties": False,
            },
        },
    }]
    result = attempt(
        "exact_tool_call",
        [{"role": "user", "content": "Call record_probe exactly once with label flash-next and value 703. Do not answer in text."}],
        128, 19, tools,
    )
    calls = result.get("tool_calls")
    valid = False
    if isinstance(calls, list) and len(calls) == 1:
        function = calls[0].get("function", {})
        try:
            arguments = json.loads(function.get("arguments", ""))
        except (TypeError, json.JSONDecodeError):
            arguments = None
        valid = (
            function.get("name") == "record_probe"
            and arguments == {"label": "flash-next", "value": 703}
            and isinstance(result.get("content"), str)
            and not result["content"].strip()
            and result.get("finish_reason") == "tool_calls"
            and result.get("response_model") == runtime.served_model
        )
    record("passed" if valid else "failed")
    if not valid:
        raise QualificationError("fixed tool-call probe failed")
    results.append(result)
    return results


def _verify_exact_resident_state(
    ops: HostOps, expected: dict[str, Any]
) -> dict[str, Any]:
    row = _inspect_container(ops, expected["id"])
    if (
        row is None
        or row.get("id") != expected["id"]
        or row.get("name") != expected["name"]
        or row.get("image") != expected["image"]
        or row.get("restart_policy") != expected["restart_policy"]
        or row.get("running") is not True
        or row.get("oom_killed") is not False
        or row.get("restart_count") != expected["restart_count"]
    ):
        raise QualificationError(
            f"resident final state differs from its capture: {expected['name']}"
        )
    return row


def _wait_resident_restore(ops: HostOps, initial: dict[str, Any], deadline: float) -> None:
    pending = {row["name"]: row for row in initial["residents"]}
    if not pending or any(row.get("running") is not True for row in pending.values()):
        raise QualificationError("resident capture does not prove an initially running state")
    last_error = "not probed"
    while pending and time.monotonic() < deadline:
        for expected in list(pending.values()):
            row = _inspect_container(ops, expected["id"])
            if row is None or row.get("id") != expected["id"] or row.get("name") != expected["name"]:
                raise QualificationError(f"resident identity disappeared: {expected['name']}")
            if not row.get("running"):
                continue
            health = next(item["health_url"] for item in RESIDENTS if item["name"] == expected["name"])
            try:
                ops.http_bytes(health, timeout=min(2, max(0.1, deadline - time.monotonic())))
            except Exception as exc:  # noqa: BLE001 - bounded health poll records its final error
                last_error = f"{type(exc).__name__}: {exc}"
                continue
            _verify_exact_resident_state(ops, expected)
            pending.pop(expected["name"])
        if pending:
            time.sleep(min(2, max(0, deadline - time.monotonic())))
    if pending:
        raise QualificationError(
            f"resident readiness unverified for {sorted(pending)} ({last_error})"
        )


def _remaining_timeout(deadline: float, ceiling: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise QualificationError("restoration deadline exhausted")
    return min(ceiling, remaining)


def restore_exact(
    ops: HostOps,
    state: dict[str, Any],
    *,
    deadline: float,
    monitor: MemoryMonitor | None = None,
    diagnostic_path: Path | None = None,
    spec: CandidateSpec | None = None,
    extended_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Best-effort exact-ID restoration; never re-create a resident."""
    runtime = _runtime_identity(spec)
    errors: list[str] = []
    diagnostic_errors: list[str] = []
    candidate_id = state.get("candidate_id")
    initial = state.get("initial")
    candidate_safe = True
    candidate_stopped_monotonic: float | None = None
    restored_expectations: list[dict[str, Any]] = []
    if candidate_id is None and not isinstance(initial, dict):
        unexpected = _inspect_container(ops, runtime.container_name)
        if unexpected is None:
            return {
                "status": "verified",
                "verified_at": utc_now(),
                "errors": [],
                "diagnostic_errors": [],
                "sentinel_retained": False,
                "no_mutation_verified": True,
                "candidate_stopped_monotonic": None,
                "restoration_completed_monotonic": time.monotonic(),
                "resident_restart_baselines": {},
            }
        return {
            "status": "unknown",
            "verified_at": None,
            "errors": ["unexpected A/B sentinel exists without a captured initial state"],
            "diagnostic_errors": [],
            "sentinel_retained": True,
            "no_mutation_verified": False,
            "candidate_stopped_monotonic": None,
            "restoration_completed_monotonic": time.monotonic(),
            "resident_restart_baselines": {},
        }
    if candidate_id:
        try:
            row = _inspect_container(ops, candidate_id)
            by_name = _inspect_container(ops, runtime.container_name)
            if by_name is not None and by_name.get("id") != candidate_id:
                raise QualificationError("A/B sentinel name now belongs to another container")
            if row is not None:
                if (
                    row.get("id") != candidate_id
                    or row.get("name") != runtime.container_name
                    or row.get("image") != runtime.image_id
                ):
                    raise QualificationError("candidate identity changed during restoration")
                if diagnostic_path is not None:
                    try:
                        logs = ops.run(
                            ["docker", "logs", "--timestamps", "--tail", "400", candidate_id],
                            timeout=_remaining_timeout(deadline, 10),
                            check=False,
                        )
                        _atomic_write_bytes(
                            diagnostic_path,
                            (logs.stdout + ("\n[stderr]\n" + logs.stderr if logs.stderr else "")).encode(),
                        )
                    except Exception as exc:  # noqa: BLE001 - diagnostics cannot block restoration
                        diagnostic_errors.append(
                            f"candidate log capture: {type(exc).__name__}: {exc}"
                        )
                if monitor is not None:
                    monitor.disarm()
                if row.get("running"):
                    ops.run(
                        ["docker", "stop", "--time", "20", candidate_id],
                        timeout=_remaining_timeout(deadline, 30),
                    )
                row = _inspect_container(ops, candidate_id)
                if row is not None and row.get("running"):
                    raise QualificationError("candidate stop could not be verified")
            candidate_stopped_monotonic = (
                monitor.emergency_stop_at
                if monitor is not None and monitor.emergency_stop_at is not None
                else time.monotonic()
            )
        except Exception as exc:  # noqa: BLE001 - restoration must record stop uncertainty
            candidate_safe = False
            errors.append(f"candidate stop: {type(exc).__name__}: {exc}")
    elif isinstance(initial, dict):
        unexpected = _inspect_container(ops, runtime.container_name)
        if unexpected is not None:
            candidate_safe = False
            errors.append("A/B sentinel exists but its exact candidate ID was not captured")

    if not isinstance(initial, dict):
        errors.append("initial state receipt is absent")
    elif not candidate_safe:
        errors.append(
            "resident and Nara restoration withheld because candidate stop is unverified"
        )
    else:
        initial_by_name = {
            row.get("name"): row
            for row in initial.get("residents", [])
            if isinstance(row, dict)
        }
        pending = []
        # Validate every identity before starting either resident. Then restore
        # one model at a time so each vLLM memory profile sees a stable peer.
        for registered in RESIDENTS:
            expected = initial_by_name.get(registered["name"])
            if not isinstance(expected, dict):
                errors.append(f"resident {registered['name']}: initial identity is absent")
                break
            if expected.get("running") is not True:
                errors.append(
                    f"resident {registered['name']}: capture does not prove it was running"
                )
                break
            try:
                row = _inspect_container(ops, expected["name"])
                if row is None or row.get("id") != expected["id"] or row.get("image") != expected["image"]:
                    raise QualificationError("exact resident identity is unavailable")
                pending.append((expected, row))
            except Exception as exc:  # noqa: BLE001 - validate all identities before any start
                errors.append(f"resident {expected.get('name')}: {type(exc).__name__}: {exc}")
                break

        if not errors:
            for expected, observed in pending:
                try:
                    restored_expected = expected
                    if not observed.get("running"):
                        ops.run(
                            ["docker", "start", expected["id"]],
                            timeout=_remaining_timeout(deadline, 30),
                        )
                        post_start = _inspect_container(ops, expected["id"])
                        restart_count = (
                            post_start.get("restart_count")
                            if isinstance(post_start, dict)
                            else None
                        )
                        if (
                            isinstance(restart_count, bool)
                            or not isinstance(restart_count, int)
                            or restart_count < 0
                        ):
                            raise QualificationError(
                                "post-start restart baseline is unavailable"
                            )
                        # Docker may reset a historical RestartCount on an
                        # explicit stop/start.  The relevant safety proof is
                        # that it does not change after this exact start.
                        restored_expected = dict(
                            expected, restart_count=restart_count
                        )
                        _verify_exact_resident_state(ops, restored_expected)
                    _wait_resident_restore(
                        ops,
                        {"residents": [restored_expected]},
                        deadline,
                    )
                    restored_expectations.append(restored_expected)
                except Exception as exc:  # noqa: BLE001 - stop the sequential restore on any fault
                    errors.append(
                        f"resident {expected.get('name')}: {type(exc).__name__}: {exc}"
                    )
                    break

        # Health alone is not sufficient: an unless-stopped resident may OOM,
        # restart, and answer between polls.  Recheck both residents before
        # bringing Nara back into the restored runtime.
        if not errors:
            for expected in restored_expectations:
                try:
                    _verify_exact_resident_state(ops, expected)
                except Exception as exc:  # noqa: BLE001 - preserve exact final-state failure
                    errors.append(
                        f"resident {expected.get('name')}: {type(exc).__name__}: {exc}"
                    )
                    break

        if not errors:
            try:
                service = _service_state(
                    ops, timeout=_remaining_timeout(deadline, 5)
                )
                if initial.get("nara_was_active"):
                    if service["ActiveState"] != "active":
                        ops.run(
                            ["systemctl", "--user", "start", NARA_SERVICE],
                            timeout=_remaining_timeout(deadline, 30),
                        )
                        service = _service_state(
                            ops, timeout=_remaining_timeout(deadline, 5)
                        )
                    if service["ActiveState"] != "active":
                        raise QualificationError("Nara active state was not restored")
                elif service["ActiveState"] == "active":
                    raise QualificationError("Nara became active despite an initially inactive state")
            except Exception as exc:  # noqa: BLE001 - preserve unknown service restoration
                errors.append(f"Nara: {type(exc).__name__}: {exc}")
        elif initial.get("nara_was_active"):
            errors.append("Nara restoration withheld until resident health is verified")

        # Bind the final resident state after the Nara transition to the exact
        # pre-window image, restart policy, OOM flag, and restart count before
        # declaring restoration verified or removing the watchdog sentinel.
        if not errors:
            for expected in restored_expectations:
                try:
                    _verify_exact_resident_state(ops, expected)
                except Exception as exc:  # noqa: BLE001 - preserve exact final-state failure
                    errors.append(
                        f"resident {expected.get('name')}: {type(exc).__name__}: {exc}"
                    )
                    break

    # The stopped candidate is also the watchdog sentinel.  Remove it only
    # after every pre-existing runtime and Nara state is positively verified.
    if not errors and candidate_id:
        try:
            by_name = _inspect_container(ops, runtime.container_name)
            by_id = _inspect_container(ops, candidate_id)
            if by_name is None and by_id is None:
                pass
            elif (
                by_name is None
                or by_id is None
                or by_name.get("id") != candidate_id
                or by_id.get("id") != candidate_id
                or by_id.get("name") != runtime.container_name
                or by_id.get("image") != runtime.image_id
            ):
                raise QualificationError("candidate sentinel identity changed")
            else:
                ops.run(
                    ["docker", "rm", candidate_id],
                    timeout=_remaining_timeout(deadline, 20),
                )
                if (
                    _inspect_container(ops, runtime.container_name) is not None
                    or _inspect_container(ops, candidate_id) is not None
                ):
                    raise QualificationError(
                        "candidate sentinel removal was not verified"
                    )
        except Exception as exc:  # noqa: BLE001 - retain the sentinel on any removal uncertainty
            errors.append(f"sentinel removal: {type(exc).__name__}: {exc}")
    retained = _inspect_container(ops, runtime.container_name) is not None
    final_observation = None
    if not errors and extended_plan is not None and candidate_id is not None:
        try:
            if len(restored_expectations) != len(RESIDENTS):
                raise QualificationError("extended restoration has incomplete resident baselines")
            final_residents = []
            resident_health = []
            for expected in restored_expectations:
                _verify_exact_resident_state(ops, expected)
                row = _inspect_container(ops, expected["id"])
                if row is None:
                    raise QualificationError("extended final resident disappeared")
                final_residents.append(row)
                health = next(
                    item["health_url"] for item in RESIDENTS
                    if item["name"] == expected["name"]
                )
                ops.http_bytes(health, timeout=_remaining_timeout(deadline, 2))
                resident_health.append({"name": expected["name"], "healthy": True})
            final_nara = _service_state(ops, timeout=_remaining_timeout(deadline, 5))
            if final_nara["ActiveState"] != (
                "active" if initial.get("nara_was_active") else "inactive"
            ):
                raise QualificationError("extended final Nara service changed")
            sentinel_name = _inspect_container(ops, runtime.container_name)
            sentinel_id = _inspect_container(ops, candidate_id)
            if sentinel_name is not None or sentinel_id is not None:
                raise QualificationError("extended candidate sentinel reappeared after removal")
            final_observation = {
                "observed_at": utc_now(),
                "residents": final_residents,
                "resident_health": resident_health,
                "nara": final_nara,
                "sentinel_by_name": sentinel_name,
                "sentinel_by_id": sentinel_id,
            }
        except BaseException as exc:  # noqa: BLE001 - final exact proof is admission-critical
            errors.append(f"extended final observation: {type(exc).__name__}: {exc}")
    receipt = {
        "status": "verified" if not errors else "unknown",
        "verified_at": utc_now() if not errors else None,
        "errors": errors,
        "diagnostic_errors": diagnostic_errors,
        "sentinel_retained": retained,
        "no_mutation_verified": False,
        "candidate_stopped_monotonic": candidate_stopped_monotonic,
        "restoration_completed_monotonic": time.monotonic(),
        "resident_restart_baselines": {
            expected["name"]: expected["restart_count"]
            for expected in restored_expectations
        },
    }
    if extended_plan is not None:
        receipt["final_observation"] = final_observation
    return receipt


def _signal_guard():
    previous = {}

    def handler(signum, frame):
        raise QualificationInterrupted(f"received signal {signum}; entering restoration")

    for name in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        previous[name] = signal.signal(name, handler)
    return previous


def _restore_signals(previous) -> None:
    for name, handler in previous.items():
        signal.signal(name, handler)


def execute_worker(
    plan: dict[str, Any],
    contract: dict[str, Any],
    output: Path,
    *,
    ops: HostOps | None = None,
    preflight_probe: Callable[..., dict[str, Any]] | None = None,
    monitor_factory=MemoryMonitor,
    ledger: Path = RESEARCH_LEDGER,
    spec: CandidateSpec | None = None,
    evaluation_context: tuple[Any, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Execute one already-supervised window.  Tests inject all host effects."""
    evaluation_window: Any = None
    extended_plan: dict[str, Any] | None = None
    followon_kind = False
    from .followon_profiles import MIA_CTX69632, requires_profile_canary

    profile_canary_required = requires_profile_canary(spec)
    native_packet_factory = None
    profile_canary_summary: dict[str, Any] | None = None
    if evaluation_context is not None:
        from .evaluation_window import (
            EXTENDED_SERVING_PROFILE,
            REGISTERED_CODE_ROOT,
            FrozenEvaluationWindow,
            build_extended_evaluation_plan,
            extended_plan_sha256,
            frozen_controller_source_bundle,
            load_evaluation_window,
        )

        if not isinstance(evaluation_context, tuple) or len(evaluation_context) != 2:
            raise QualificationError("extended evaluation inputs are not frozen")
        evaluation_window, extended_plan = evaluation_context
        followon_kind = (isinstance(extended_plan, dict)
                         and extended_plan.get("evaluation_kind") == "followon")
        if followon_kind:
            from .followon_dispatch import (
                FOLLOWON_CODE_ROOT,
                frozen_followon_source_bundle,
            )
            from .followon_plans import FollowonExecution, flash_plan, load_execution

            if (ROOT != FOLLOWON_CODE_ROOT
                or not isinstance(evaluation_window, FollowonExecution)
                or evaluation_window.cohort != "flash"
                or load_execution(evaluation_window.source_path, cohort="flash")
                   != evaluation_window
                or flash_plan(evaluation_window, output) != extended_plan
                or extended_plan.get("schema_version")
                   != ("flash-followon-flash-plan/v2"
                       if evaluation_window.v5_parent is not None
                       else "flash-followon-flash-plan/v1")
                or (evaluation_window.v5_parent is not None and
                    extended_plan.get("v5_qualified_parent")
                    != evaluation_window.document.get("v5_qualified_parent"))
                or plan != evaluation_window.qualification_plan
                or extended_plan["controller_source_bundle"]
                   != frozen_followon_source_bundle()
                or extended_plan["registered_code_root"] != str(FOLLOWON_CODE_ROOT)
            ):
                raise QualificationError("follow-on worker/source differs from registration")
            # The old portfolio helper enforces the old exact plan key tuple.
            # q's canonical hash has the same byte convention for this closed
            # new plan, while the old branch keeps its original helper.
            extended_plan_sha256 = sha256
        else:
            if ROOT != REGISTERED_CODE_ROOT:
                raise QualificationError("extended worker was imported outside the registered worktree")
            if (not isinstance(evaluation_window, FrozenEvaluationWindow)
                or not isinstance(extended_plan, dict)
                or evaluation_window.cohort != "flash"
                or load_evaluation_window(
                    evaluation_window.source_path, expected_cohort="flash"
                ) != evaluation_window
                or build_extended_evaluation_plan(evaluation_window, output) != extended_plan
                or plan != evaluation_window.qualification_plan
                or extended_plan["controller_source_bundle"]
                   != frozen_controller_source_bundle()
            ):
                raise QualificationError("extended runtime differs from the qualified candidate")
        if followon_kind:
            from .followon_dispatch import OUTER_DEADLINE
            expected_extended_deadline = OUTER_DEADLINE
        else:
            expected_extended_deadline = 14_400
        if (expected_extended_deadline
                != (4_200 if followon_kind else 14_400)
            or extended_plan["extended_serving_profile"] != EXTENDED_SERVING_PROFILE
            or extended_plan["candidate_spec_sha256"]
               != (spec.identity_sha256() if spec is not None else None)
            or extended_plan["candidate_variant_id"]
               != (spec.spec_id if spec is not None else "nvidia-nvfp4-fc694b54")
            or extended_plan["docker_create_argv"] != launch_argv(spec)
            or extended_plan["image_id"] != _runtime_identity(spec).image_id
            or extended_plan["model_artifact_sha256"]
               != _runtime_identity(spec).model_artifact_sha256
            or extended_plan["paging_policy"]
               != (spec.paging_policy() if spec is not None else PAGING_POLICY)
            or extended_plan["effective_invocation_deadline_seconds"]
               != expected_extended_deadline
            or extended_plan["work_cutoff_seconds"]
               != expected_extended_deadline - 600
            or extended_plan["restoration_reserve_seconds"] != 600
            or extended_plan["controller_source_bundle_sha256"]
               != sha256(extended_plan["controller_source_bundle"])
        ):
            raise QualificationError("extended runtime differs from the qualified candidate")
        _verified_contract_raw(contract, plan["contract_sha256"], spec=spec)
    if spec is not None:
        validate_contract(contract, spec=spec)
        historical_v5_followon = False
        if followon_kind and evaluation_window.v5_parent is not None:
            from .historical_v5_parent_bridge import (
                OLD_ROOT,
                OLD_SOURCE_BUNDLE_SHA256,
                PARENT_PATH,
                PARENT_SHA256,
                QUALIFICATION_RUN_ID,
            )
            historical_v5_followon = (
                evaluation_window.document.get("study_id")
                    == "coding-temp1-medium-and-decode-v1"
                and evaluation_window.document.get("v5_qualified_parent")
                    == {"path": str(PARENT_PATH), "sha256": PARENT_SHA256}
                and evaluation_window.v5_parent.pair_id == QUALIFICATION_RUN_ID
                and evaluation_window.v5_parent.source_sha256 == PARENT_SHA256
                and plan == evaluation_window.v5_parent.qualification_plan
                and plan.get("registered_code_root") == str(OLD_ROOT)
                and plan.get("followon_source_bundle_sha256")
                    == OLD_SOURCE_BUNDLE_SHA256
            )
            if not historical_v5_followon:
                raise QualificationError("historical v5 follow-on parent differs")
        if not historical_v5_followon:
            expected_plan = plan_qualification(
                contract, plan["contract_sha256"],
                Path(plan["output_dir"]) if extended_plan is not None else output,
                spec=spec,
            )
            if plan != expected_plan:
                raise QualificationError("Mia worker plan differs from immutable registration")
            if spec.contract_schema.endswith("/v5"):
                from .followon_dispatch import (
                    FOLLOWON_CODE_ROOT,
                    frozen_followon_source_bundle,
                )
                if (ROOT != FOLLOWON_CODE_ROOT
                    or plan.get("registered_code_root") != str(FOLLOWON_CODE_ROOT)
                    or plan.get("followon_source_bundle") != frozen_followon_source_bundle()
                    or plan.get("followon_source_bundle_sha256") != sha256(plan["followon_source_bundle"])):
                    raise QualificationError("v5 worker source root or module bytes differ")
    ops = ops or HostOps()
    runtime = _runtime_identity(spec)
    if os.environ.get("MOCK_LLM"):
        raise QualificationError("live qualification refuses MOCK_LLM")
    if preflight_probe is None:
        from orchestrator.weekly_upgrade_trial import resource_probe as preflight_probe

    root = canonical_root(ROOT)
    deadline_seconds = (
        extended_plan["effective_invocation_deadline_seconds"] if extended_plan
        is not None else contract["safety"]["invocation_deadline_seconds"]
    )
    restore_reserve = (
        extended_plan["restoration_reserve_seconds"] if extended_plan
        is not None else contract["safety"]["restoration_reserve_seconds"]
    )
    started_mono = time.monotonic()
    hard_deadline = started_mono + deadline_seconds
    work_deadline = hard_deadline - restore_reserve
    started_wall = datetime.now(timezone.utc)
    run_id = output.name
    state: dict[str, Any] = {
        "schema": ("flash-followon-flash-state/v1" if followon_kind
                   else "flash-next-extended-evaluation-state/v2"
                   if extended_plan is not None
                   else _mia_standard_schema("state", spec) if spec is not None
                   else "qwen-flash-next-qualification-state/v3"),
        "run_id": run_id,
        "phase": "preflight",
        "plan_sha256": sha256(plan),
        "contract_sha256": plan["contract_sha256"],
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "worker_pid": os.getpid(),
        "worker_start_ticks": _self_start_ticks(),
        "started_at": started_wall.isoformat(),
        "updated_at": started_wall.isoformat(),
        "invocation_deadline_at": (
            started_wall + timedelta(seconds=deadline_seconds)
        ).isoformat(),
        "memory_log_relpath": "memory.jsonl",
        "monitor_phase": "setup",
        "paging_policy": contract["safety"]["paging_policy"],
        "candidate_id": None,
        "candidate_cgroup_path": None,
        "candidate_cgroup_pid": None,
        "candidate_cgroup_start_ticks": None,
        "ready_quiescence": {"status": "not_started"},
        "initial": None,
        "restoration": {"status": "not_started"},
    }
    if spec is not None:
        state["candidate"] = plan["candidate"]
        state["model_artifact_sha256"] = runtime.model_artifact_sha256
        if spec.contract_schema.endswith("/v5"):
            state["followon_source_bundle_sha256"] = plan["followon_source_bundle_sha256"]
    if profile_canary_required:
        state["profile_canary_status"] = "not_started"
        state["profile_canary_protocol_sha256"] = None
    if extended_plan is not None:
        state.update(
            pair_id=evaluation_window.pair_id,
            window_plan_path=str(evaluation_window.source_path),
            window_plan_sha256=evaluation_window.source_sha256,
            extended_plan_sha256=extended_plan_sha256(extended_plan),
            prior_qualification_receipt_sha256=extended_plan[
                "prior_qualification_receipt_sha256"
            ],
            extended_serving_profile=extended_plan["extended_serving_profile"],
            extended_serving_profile_sha256=extended_plan[
                "extended_serving_profile_sha256"
            ],
            controller_source_bundle_sha256=extended_plan[
                "controller_source_bundle_sha256"
            ],
        )
        if followon_kind:
            state["evaluation_kind"] = "followon"
            state["qualified_parent_window"] = extended_plan[
                "qualified_parent_window"]
            state["followon_blocks"] = extended_plan["followon_blocks"]
            if evaluation_window.v5_parent is not None:
                state["v5_qualified_parent"] = extended_plan[
                    "v5_qualified_parent"]
    state_path = output / "state.json"

    def write_state() -> None:
        state["updated_at"] = utc_now()
        _atomic_write(state_path, state)

    write_state()
    started_usage = {
        "schema": "local-model-research-usage/v1",
        "event": "extended_started" if extended_plan is not None else "started",
        "run_id": run_id,
        "observed_at": utc_now(),
        "contract_sha256": plan["contract_sha256"],
        "invocation_ceiling_seconds": deadline_seconds,
        "weekly_budget_debit": False,
        "paid_api_calls": 0,
    }
    if extended_plan is not None:
        started_usage["extended_plan_sha256"] = extended_plan_sha256(extended_plan)
    _append_research_usage(started_usage, ledger)

    qualification_error: str | None = None
    failure_stage: str | None = None
    active_stage = "setup"
    probes: list[dict[str, Any]] = []
    evaluation_attempt: dict[str, Any] | None = None
    ui_observer: Any = None
    ui_observer_summary: dict[str, Any] | None = None
    model_receipt: dict[str, Any] | None = None
    candidate_started_mono: float | None = None
    candidate_stopped_mono: float | None = None
    resident_stopped_mono: float | None = None
    restoration_completed_mono: float | None = None
    monitor_args = {
        "minimum_gib": runtime.min_memory_gib,
        "interval_s": contract["safety"]["memory_poll_seconds"],
        "paging_policy": contract["safety"]["paging_policy"],
    }
    if spec is not None:
        monitor_args["candidate_spec"] = spec
    if extended_plan is not None:
        monitor_args["extended_serving_profile"] = extended_plan[
            "extended_serving_profile"
        ]
    monitor = monitor_factory(output / "memory.jsonl", ops, **monitor_args)
    previous_signals = _signal_guard()
    restoration: dict[str, Any] = {
        "status": "verified",
        "verified_at": utc_now(),
        "errors": [],
        "sentinel_retained": False,
    }
    try:
        with resource_lease(root), monitor:
            if extended_plan is not None:
                from .extended_observer import UIObserver

                ui_observer = UIObserver(
                    output, monitor=monitor, pair_id=evaluation_window.pair_id,
                    extended_plan_sha256=sha256(extended_plan),
                    profile=extended_plan["extended_serving_profile"],
                )
                ui_observer.start()
            try:
                preflight = preflight_probe(root, idle=True)
                if float(preflight.get("mem_available_gib", 0)) < runtime.min_memory_gib:
                    raise QualificationError("preflight did not preserve the 20 GiB memory gate")
                if spec is MIA_CTX69632:
                    from .followon_native_packet import prepared_factory

                    # A real locally retokenized 65K packet must exist before
                    # any Nara/resident/container mutation. No hand-declared
                    # model context length substitutes for source evidence.
                    native_packet_factory = prepared_factory()
                if _inspect_container(ops, runtime.container_name) is not None:
                    raise QualificationError("A/B sentinel name already exists")
                if spec is not None and _inspect_container(ops, CONTAINER_NAME) is not None:
                    raise QualificationError("NVIDIA A/B sentinel still exists before Mia window")
                _assert_port_free(spec) if spec is not None else _assert_port_free()

                state["phase"] = "model_verification"
                write_state()
                model_receipt = (
                    verify_model(contract, monitor, spec=spec) if spec is not None
                    else verify_model(contract, monitor)
                )
                _atomic_write(output / "model-verification.json", model_receipt)
                image = ops.run(
                    ["docker", "image", "inspect", "--format", "{{.Id}} {{.Architecture}}", runtime.image_id],
                    timeout=10,
                ).stdout.strip().split()
                if image != [runtime.image_id, "arm64"]:
                    raise QualificationError("installed image identity or architecture differs")
                _ensure_compile_cache(spec) if spec is not None else _ensure_compile_cache()
                monitor.check()

                state["phase"] = "setup_quiescence"
                write_state()
                monitor.require_setup_quiescence(
                    duration_s=contract["safety"]["setup_quiescence_seconds"],
                    deadline=work_deadline,
                )

                # Hashing 123.6 GiB can span more than one scheduling instant.
                # Re-probe idle queues and capture identities immediately before
                # the first mutation while the canonical lease is still held.
                preflight = preflight_probe(root, idle=True)
                if float(preflight.get("mem_available_gib", 0)) < runtime.min_memory_gib:
                    raise QualificationError("pre-mutation memory gate failed")
                initial = _capture_initial_state(ops, preflight)
                state["initial"] = initial
                write_state()

                monitor.begin_mutation_window()
                state["mutation_window_started_at"] = monitor.mutation_window_started_at
                state["monitor_phase"] = "load"
                state["phase"] = "sentinel_create"
                write_state()
                monitor.check()
                created = ops.run(plan["docker_create_argv"], timeout=30).stdout.strip()
                if re.fullmatch(r"[0-9a-f]{64}", created):
                    state["candidate_id"] = created
                    write_state()
                else:
                    # A created sentinel must remain recoverable even if Docker's
                    # stdout was malformed or unexpectedly decorated.
                    recovered = _inspect_container(ops, runtime.container_name)
                    if recovered is not None and re.fullmatch(
                        r"[0-9a-f]{64}", str(recovered.get("id", ""))
                    ):
                        state["candidate_id"] = recovered["id"]
                        write_state()
                    raise QualificationError("docker create did not return an exact container ID")
                candidate = _inspect_container(ops, runtime.container_name)
                if (
                    candidate is None
                    or candidate.get("id") != created
                    or candidate.get("image") != runtime.image_id
                    or candidate.get("running")
                    or candidate.get("restart_policy") not in {"", "no"}
                    or candidate.get("memory_limit_bytes") != runtime.memory_limit_bytes
                    or candidate.get("memory_swap_total_bytes")
                    != runtime.memory_limit_bytes
                ):
                    raise QualificationError("created candidate differs from the launch contract")

                if initial["nara_was_active"]:
                    ops.run(["systemctl", "--user", "stop", NARA_SERVICE], timeout=30)
                    if _service_state(ops)["ActiveState"] == "active":
                        raise QualificationError("Nara stop was not verified")

                state["phase"] = "resident_stop"
                write_state()
                resident_stopped_mono = time.monotonic()
                for resident in initial["residents"]:
                    if resident["running"]:
                        ops.run(["docker", "stop", "--time", "30", resident["id"]], timeout=45)
                        observed = _inspect_container(ops, resident["name"])
                        if observed is None or observed["id"] != resident["id"] or observed["running"]:
                            raise QualificationError(f"resident stop unverified: {resident['name']}")
                monitor.check()
                if float(monitor.reader()) < runtime.min_memory_gib:
                    raise QualificationError("20 GiB is unavailable after resident stop")

                state["phase"] = "candidate_start"
                active_stage = "candidate_start"
                write_state()
                monitor.check()
                candidate_started_mono = time.monotonic()
                state["candidate_gpu_start_attempt_monotonic"] = candidate_started_mono
                write_state()
                ops.run(["docker", "start", created], timeout=30)
                monitor.arm(created)
                state["candidate_cgroup_path"] = getattr(
                    monitor, "candidate_cgroup_bound_path", None
                )
                state["candidate_cgroup_pid"] = getattr(
                    monitor, "candidate_cgroup_bound_pid", None
                )
                state["candidate_cgroup_start_ticks"] = getattr(
                    monitor, "candidate_cgroup_start_ticks", None
                )
                monitor.check()
                state["candidate_gpu_started_monotonic_upper_bound"] = candidate_started_mono
                state["phase"] = "readiness"
                active_stage = "readiness"
                write_state()
                readiness_deadline = min(
                    work_deadline,
                    time.monotonic() + contract["safety"]["readiness_deadline_seconds"],
                )
                ready = _wait_candidate_ready(
                    ops, monitor, deadline=readiness_deadline,
                    **({"spec": spec} if spec is not None else {}),
                )
                state["phase"] = "ready_stabilization"
                state["monitor_phase"] = "ready"
                write_state()
                monitor.require_ready_quiescence(
                    duration_s=contract["safety"]["ready_quiescence_seconds"],
                    deadline=readiness_deadline,
                )
                ready["stabilization"] = {
                    "required_seconds": contract["safety"][
                        "ready_quiescence_seconds"
                    ],
                    "passed": monitor.ready_quiescence_passed,
                    "started_at": monitor.ready_quiescence_started_at,
                    "completed_at": monitor.ready_quiescence_completed_at,
                    "duration_seconds": monitor.ready_quiescence_duration_seconds,
                    "initial_pswpout_pages": monitor.ready_quiescence_initial_pswpout,
                    "final_pswpout_pages": monitor.ready_quiescence_final_pswpout,
                    "samples": monitor.ready_quiescence_samples,
                    "epoch": monitor.ready_quiescence_epoch,
                }
                _atomic_write(output / "readiness.json", ready)
                state["ready_quiescence"] = ready["stabilization"]
                if time.monotonic() >= work_deadline:
                    raise QualificationError("work deadline reached before probes")

                state["phase"] = "probes"
                state["monitor_phase"] = "probes"
                active_stage = "probes"
                write_state()
                # Three fixed probes may complete before the next background
                # poll.  Persist one attributed serving-phase observation so
                # sidecar and offline admission do not depend on timing.
                monitor._sample_once()
                monitor.check()
                probes = _run_probes(
                    ops,
                    monitor,
                    timeout_s=contract["safety"]["probe_timeout_seconds"],
                    output=output,
                    **({"spec": spec} if spec is not None else {}),
                )
                _atomic_write(output / "probes.json", {"probe_set": plan["probe_set"], "results": probes})
                monitor.check()
                final_candidate = _inspect_container(ops, created)
                if (
                    final_candidate is None
                    or not final_candidate.get("running")
                    or final_candidate.get("oom_killed")
                    or final_candidate.get("restart_count") != 0
                ):
                    raise QualificationError("candidate OOM/restart/running-state gate failed")
                if profile_canary_required:
                    from .followon_canaries import run_profile_canary

                    state["profile_canary_status"] = "started"
                    write_state()
                    profile_canary_summary = run_profile_canary(
                        ops, monitor, spec=spec, output=output,
                        timeout_s=spec.profile_canary_timeout_seconds,
                        work_deadline=work_deadline,
                        atomic_write=_atomic_write,
                        record_private=_probe_private_response,
                        native_context_packet_factory=native_packet_factory,
                    )
                    if profile_canary_summary.get("status") != "passed":
                        raise QualificationError("registered profile canary failed")
                    state["profile_canary_status"] = "passed"
                    state["profile_canary_protocol_sha256"] = (
                        profile_canary_summary["protocol_sha256"]
                    )
                    write_state()
                if extended_plan is not None:
                    monitor.begin_evaluation()
                    state["phase"] = "evaluation"
                    state["monitor_phase"] = "evaluation"
                    active_stage = "evaluation"
                    write_state()
                    if followon_kind:
                        from .followon_admission import flash_callbacks
                        from .followon_dispatch import run_group

                        callbacks = flash_callbacks(
                            evaluation_window, state, monitor, final_candidate,
                            cutoff=work_deadline,
                        )
                        evaluation_attempt = run_group(
                            evaluation_window.frozen,
                            controller_callbacks=callbacks,
                            work_cutoff_s=work_deadline,
                            cancel_event=monitor.cancel_event,
                        )
                    else:
                        from .evaluation_window import run_flash_after_probes

                        evaluation_attempt = run_flash_after_probes(
                            evaluation_window,
                            execution_plan=extended_plan,
                            evaluation_output=output,
                            work_deadline=work_deadline,
                            monitor=monitor,
                        )
                    monitor.check()
                    required_attempt_status = (
                        "blocks_complete_pending_restoration" if followon_kind
                        else "harness_complete_pending_restoration"
                    )
                    if evaluation_attempt.get("status") != required_attempt_status:
                        raise QualificationError("registered evaluation did not finish before restoration")
                    state["phase"] = "evaluation_complete_pending_restoration"
                else:
                    state["phase"] = "qualification_passed"
                write_state()
            except BaseException as exc:  # noqa: BLE001 - signals and faults must enter finally
                qualification_error = f"{type(exc).__name__}: {exc}"
                failure_stage = active_stage if active_stage in FAILURE_STAGES else "unknown"
            finally:
                try:
                    active_stage = "restoration"
                    try:
                        monitor.begin_restoration()
                    except BaseException as phase_exc:  # noqa: BLE001 - restoration must continue
                        if qualification_error is None:
                            qualification_error = (
                                f"{type(phase_exc).__name__}: {phase_exc}"
                            )
                        if failure_stage is None:
                            failure_stage = "restoration"
                    state["phase"] = "restoring"
                    state["monitor_phase"] = "restoration"
                    write_state()
                    restoration = restore_exact(
                        ops,
                        state,
                        deadline=hard_deadline,
                        monitor=monitor,
                        diagnostic_path=output / "candidate.log",
                        **({"extended_plan": extended_plan} if extended_plan is not None else {}),
                        **({"spec": spec} if spec is not None else {}),
                    )
                    candidate_stopped_mono = restoration.get("candidate_stopped_monotonic")
                    restoration_completed_mono = restoration.get(
                        "restoration_completed_monotonic"
                    )
                    if extended_plan is not None and restoration["status"] == "verified":
                        # The completed-window reader binds a raw sample at
                        # or after the exact restore timestamp, regardless
                        # of the background thread's one-second scheduling.
                        monitor._sample_once()
                        monitor.check()
                except BaseException as exc:  # noqa: BLE001 - restoration failures become durable unknown
                    if failure_stage is None:
                        failure_stage = "restoration"
                    restoration_completed_mono = time.monotonic()
                    restoration = {
                        "status": "unknown",
                        "verified_at": None,
                        "errors": [f"restoration crashed: {type(exc).__name__}: {exc}"],
                        "sentinel_retained": bool(state.get("candidate_id")),
                        "restoration_completed_monotonic": restoration_completed_mono,
                    }
                finally:
                    if ui_observer is not None:
                        try:
                            ui_observer_summary = ui_observer.stop()
                            _atomic_write(output / "ui-observer-summary.json", ui_observer_summary)
                            if ui_observer_summary["failed"]:
                                qualification_error = qualification_error or (
                                    "QualificationError: independent UI responsiveness failed"
                                )
                                failure_stage = failure_stage or "evaluation"
                        except BaseException as observer_exc:  # noqa: BLE001 - exact restoration remains the priority
                            qualification_error = qualification_error or (
                                f"UI observer recovery failed: {type(observer_exc).__name__}"
                            )
                            failure_stage = failure_stage or "restoration"
    except BaseException as exc:  # noqa: BLE001 - lease/monitor failures must remain fail-closed
        if qualification_error is None:
            qualification_error = f"{type(exc).__name__}: {exc}"
        if failure_stage is None:
            failure_stage = active_stage if active_stage in FAILURE_STAGES else "unknown"
        if state.get("candidate_id") or state.get("initial"):
            restoration_completed_mono = time.monotonic()
            restoration = {
                "status": "unknown",
                "verified_at": None,
                "errors": ["resource lease/monitor exited before restoration could be verified"],
                "sentinel_retained": bool(state.get("candidate_id")),
                "restoration_completed_monotonic": restoration_completed_mono,
            }
    finally:
        _restore_signals(previous_signals)

    if restoration.get("status") != "verified" and failure_stage is None:
        failure_stage = "restoration"
    if monitor.failure and failure_stage is None:
        failure_stage = active_stage if active_stage in FAILURE_STAGES else "unknown"

    elapsed = max(0.0, time.monotonic() - started_mono)
    gpu_seconds = (
        max(0.0, candidate_stopped_mono - candidate_started_mono)
        if candidate_started_mono is not None and candidate_stopped_mono is not None
        else 0.0
    )
    resident_downtime = (
        max(0.0, restoration_completed_mono - resident_stopped_mono)
        if resident_stopped_mono is not None and restoration_completed_mono is not None
        else 0.0
    )
    paging_proof_complete = bool(
        getattr(monitor, "ready_quiescence_passed", False)
        and len(probes) == 3
        and getattr(monitor, "candidate_cgroup_bound_path", None)
        == f"/system.slice/docker-{state.get('candidate_id')}.scope"
        and isinstance(getattr(monitor, "candidate_cgroup_bound_pid", None), int)
        and getattr(monitor, "candidate_cgroup_bound_pid", 0) > 0
        and isinstance(getattr(monitor, "candidate_cgroup_start_ticks", None), int)
        and getattr(monitor, "candidate_cgroup_start_ticks", 0) > 0
        and getattr(monitor, "candidate_cgroup_samples", 0) > 0
        and getattr(monitor, "candidate_cgroup_swap_peak_bytes", None) == 0
        and getattr(monitor, "candidate_cgroup_oom_initial", None) == 0
        and getattr(monitor, "candidate_cgroup_oom_final", None) == 0
        and getattr(monitor, "candidate_cgroup_oom_kill_initial", None) == 0
        and getattr(monitor, "candidate_cgroup_oom_kill_final", None) == 0
        and isinstance(getattr(monitor, "startup_initial_pswpout", None), int)
        and isinstance(getattr(monitor, "startup_final_pswpout", None), int)
        and monitor.startup_final_pswpout >= monitor.startup_initial_pswpout
        and not getattr(monitor, "violations", [])
        and all(
            phase in getattr(monitor, "phase_summaries", {})
            for phase in (
                ("load", "ready", "probes", "evaluation", "restoration")
                if extended_plan is not None else
                ("load", "ready", "probes", "restoration")
            )
        )
        and not any(
            summary.get("threshold_breached") is True
            for summary in getattr(monitor, "phase_summaries", {}).values()
        )
    )
    if (
        qualification_error is None
        and restoration["status"] == "verified"
        and not monitor.failure
        and not paging_proof_complete
    ):
        qualification_error = "QualificationError: candidate paging proof is incomplete"
        failure_stage = failure_stage or "probes"
    status = (
        ("complete" if extended_plan is not None else "passed")
        if qualification_error is None
        and restoration["status"] == "verified"
        and not monitor.failure
        and paging_proof_complete
        and (not profile_canary_required or profile_canary_summary is not None
             and profile_canary_summary.get("status") == "passed")
        and (extended_plan is None or ui_observer_summary is not None and
             ui_observer_summary.get("joined") is True and
             ui_observer_summary.get("failed") is False and
             ui_observer_summary.get("ticks", 0) >= 2)
        and (extended_plan is None or evaluation_attempt is not None and
             evaluation_attempt.get("status") == (
                 "blocks_complete_pending_restoration" if followon_kind
                 else "harness_complete_pending_restoration"))
        else "failed"
        if restoration["status"] == "verified"
        else "unknown"
    )
    result = {
        "schema": ("flash-followon-flash-result/v1" if followon_kind
                   else "flash-next-extended-evaluation-result/v2"
                   if extended_plan is not None
                   else _mia_standard_schema("result", spec) if spec is not None
                   else "qwen-flash-next-qualification-result/v3"),
        "run_id": run_id,
        "status": status,
        "failure_stage": failure_stage,
        "qualification_error": qualification_error or monitor.failure,
        "failure_class": _failure_class(
            status, qualification_error or monitor.failure, restoration, monitor
        ),
        "restoration": restoration,
        "contract_sha256": plan["contract_sha256"],
        "plan_sha256": sha256(plan),
        "model_artifact_sha256": runtime.model_artifact_sha256,
        "started_at": state["started_at"],
        "elapsed_seconds": elapsed,
        "challenger_gpu_seconds": gpu_seconds,
        "all_gpu_research_seconds": gpu_seconds,
        "challenger_gpu_seconds_basis": (
            "monotonic_start_attempt_to_emergency_stop_confirmation_upper_bound"
            if monitor.emergency_stop_at is not None and candidate_started_mono is not None
            else "monotonic_start_attempt_to_stop_confirmation_upper_bound"
            if candidate_started_mono is not None
            else "not_started"
        ),
        "resident_downtime_seconds": resident_downtime,
        "resident_downtime_seconds_basis": (
            "monotonic_resident_stop_to_restoration_completion_upper_bound"
            if resident_stopped_mono is not None and restoration_completed_mono is not None
            else "not_stopped"
        ),
        "memory_samples": monitor.samples,
        "min_mem_available_gib": (
            monitor.minimum_observed_gib if math.isfinite(monitor.minimum_observed_gib) else None
        ),
        "pswpout_initial_pages": getattr(monitor, "initial_pswpout", None),
        "pswpout_final_pages": getattr(monitor, "final_pswpout", None),
        "pswpout_delta_pages": (
            monitor.final_pswpout - monitor.initial_pswpout
            if getattr(monitor, "initial_pswpout", None) is not None
            and getattr(monitor, "final_pswpout", None) is not None
            else None
        ),
        "pswpin_initial_pages": getattr(monitor, "initial_pswpin", None),
        "pswpin_final_pages": getattr(monitor, "final_pswpin", None),
        "pswpin_delta_pages": (
            monitor.final_pswpin - monitor.initial_pswpin
            if getattr(monitor, "initial_pswpin", None) is not None
            and getattr(monitor, "final_pswpin", None) is not None
            else None
        ),
        "host_memory_psi_initial_us": getattr(
            monitor, "initial_host_psi_totals", None
        ),
        "host_memory_psi_final_us": getattr(
            monitor, "final_host_psi_totals", None
        ),
        "host_memory_psi_delta_us": (
            {
                key: monitor.final_host_psi_totals[key]
                - monitor.initial_host_psi_totals[key]
                for key in ("some", "full")
            }
            if getattr(monitor, "initial_host_psi_totals", None) is not None
            and getattr(monitor, "final_host_psi_totals", None) is not None
            else None
        ),
        "setup_pswpout_initial_pages": getattr(monitor, "initial_pswpout", None),
        "setup_pswpout_final_pages": (
            monitor.mutation_initial_pswpout
            if getattr(monitor, "mutation_initial_pswpout", None) is not None
            else getattr(monitor, "final_pswpout", None)
        ),
        "setup_pswpout_delta_pages": (
            (
                monitor.mutation_initial_pswpout
                if getattr(monitor, "mutation_initial_pswpout", None) is not None
                else monitor.final_pswpout
            )
            - monitor.initial_pswpout
            if getattr(monitor, "initial_pswpout", None) is not None
            and getattr(monitor, "final_pswpout", None) is not None
            else None
        ),
        "setup_quiescence_required_seconds": contract["safety"][
            "setup_quiescence_seconds"
        ],
        "setup_quiescence_passed": getattr(
            monitor, "setup_quiescence_passed", False
        ),
        "setup_quiescence_started_at": getattr(
            monitor, "setup_quiescence_started_at", None
        ),
        "setup_quiescence_completed_at": getattr(
            monitor, "setup_quiescence_completed_at", None
        ),
        "setup_quiescence_duration_seconds": getattr(
            monitor, "setup_quiescence_duration_seconds", None
        ),
        "setup_quiescence_initial_pswpout_pages": getattr(
            monitor, "setup_quiescence_initial_pswpout", None
        ),
        "setup_quiescence_final_pswpout_pages": getattr(
            monitor, "setup_quiescence_final_pswpout", None
        ),
        "setup_quiescence_samples": getattr(
            monitor, "setup_quiescence_samples", 0
        ),
        "mutation_window_started_at": getattr(
            monitor, "mutation_window_started_at", None
        ),
        "mutation_pswpout_initial_pages": getattr(
            monitor, "mutation_initial_pswpout", None
        ),
        "mutation_pswpout_final_pages": getattr(
            monitor, "mutation_final_pswpout", None
        ),
        "mutation_pswpout_delta_pages": (
            monitor.mutation_final_pswpout - monitor.mutation_initial_pswpout
            if getattr(monitor, "mutation_initial_pswpout", None) is not None
            and getattr(monitor, "mutation_final_pswpout", None) is not None
            else None
        ),
        "mutation_final_sample_at": getattr(
            monitor, "mutation_final_sample_at", None
        ),
        "startup_pswpout_initial_pages": getattr(
            monitor, "startup_initial_pswpout", None
        ),
        "startup_pswpout_final_pages": getattr(
            monitor, "startup_final_pswpout", None
        ),
        "startup_pswpout_delta_pages": (
            monitor.startup_final_pswpout - monitor.startup_initial_pswpout
            if getattr(monitor, "startup_initial_pswpout", None) is not None
            and getattr(monitor, "startup_final_pswpout", None) is not None
            else None
        ),
        "startup_pswpout_delta_bytes": (
            (monitor.startup_final_pswpout - monitor.startup_initial_pswpout)
            * contract["safety"]["paging_policy"]["host_page_size_bytes"]
            if getattr(monitor, "startup_initial_pswpout", None) is not None
            and getattr(monitor, "startup_final_pswpout", None) is not None
            else None
        ),
        "paging_policy": contract["safety"]["paging_policy"],
        "paging_phase_summaries": getattr(monitor, "phase_summaries", {}),
        "paging_violations": getattr(monitor, "violations", []),
        "paging_warning_phases": [
            phase
            for phase, summary in getattr(monitor, "phase_summaries", {}).items()
            if summary.get("pswpout_delta_bytes", 0) > 0
            and not summary.get("threshold_breached", False)
        ],
        "ready_quiescence_required_seconds": contract["safety"][
            "ready_quiescence_seconds"
        ],
        "ready_quiescence_passed": getattr(
            monitor, "ready_quiescence_passed", False
        ),
        "ready_quiescence_started_at": getattr(
            monitor, "ready_quiescence_started_at", None
        ),
        "ready_quiescence_completed_at": getattr(
            monitor, "ready_quiescence_completed_at", None
        ),
        "ready_quiescence_duration_seconds": getattr(
            monitor, "ready_quiescence_duration_seconds", None
        ),
        "ready_quiescence_initial_pswpout_pages": getattr(
            monitor, "ready_quiescence_initial_pswpout", None
        ),
        "ready_quiescence_final_pswpout_pages": getattr(
            monitor, "ready_quiescence_final_pswpout", None
        ),
        "ready_quiescence_samples": getattr(
            monitor, "ready_quiescence_samples", 0
        ),
        "ready_quiescence_epoch": getattr(
            monitor, "ready_quiescence_epoch", 0
        ),
        "candidate_cgroup_path": getattr(
            monitor, "candidate_cgroup_bound_path", None
        ),
        "candidate_cgroup_pid": getattr(
            monitor, "candidate_cgroup_bound_pid", None
        ),
        "candidate_cgroup_start_ticks": getattr(
            monitor, "candidate_cgroup_start_ticks", None
        ),
        "candidate_cgroup_samples": getattr(
            monitor, "candidate_cgroup_samples", 0
        ),
        "candidate_cgroup_swap_peak_bytes": getattr(
            monitor, "candidate_cgroup_swap_peak_bytes", 0
        ),
        "candidate_cgroup_oom_initial": getattr(
            monitor, "candidate_cgroup_oom_initial", None
        ),
        "candidate_cgroup_oom_final": getattr(
            monitor, "candidate_cgroup_oom_final", None
        ),
        "candidate_cgroup_oom_kill_initial": getattr(
            monitor, "candidate_cgroup_oom_kill_initial", None
        ),
        "candidate_cgroup_oom_kill_final": getattr(
            monitor, "candidate_cgroup_oom_kill_final", None
        ),
        "probe_count": len(probes),
        "weekly_budget_debit": False,
        "paid_api_calls": 0,
        "production_change_authorized": False,
    }
    diagnostic_sha256, memory_log_sha256 = _write_cgroup_diagnostics(
        output, state.get("candidate_id"), required=status in {"passed", "complete"},
        extended_plan=extended_plan,
        **({"spec": spec} if spec is not None else {}),
    )
    result.update(
        profile=spec.profile if spec is not None else "C0-S1",
        docker_memory_limit_bytes=runtime.memory_limit_bytes,
        docker_memory_swap_total_bytes=runtime.memory_limit_bytes,
        cgroup_diagnostics_sha256=diagnostic_sha256,
        memory_log_sha256=memory_log_sha256,
    )
    if spec is not None:
        result["candidate"] = plan["candidate"]
        if spec.contract_schema.endswith("/v5"):
            result["followon_source_bundle_sha256"] = plan["followon_source_bundle_sha256"]
        result["proof_receipts"] = plan["proof_receipts"]
        result["packed_ple"] = plan["packed_ple"] if model_receipt is not None else None
        result["model_verification_sha256"] = (
            sha256(model_receipt) if model_receipt is not None else None
        )
    if profile_canary_required:
        from .harness import _read_regular_file

        canary_file = output / "profile-canary.json"
        attempts_file = output / "profile-canary-attempts.json"
        canary_raw = attempts_raw = None
        for source in (canary_file, attempts_file):
            if source.exists():
                raw, observed = _read_regular_file(
                    source, label="registered profile canary", max_bytes=2_000_000
                )
                if observed != source.absolute():
                    raise QualificationError("registered profile canary redirected")
                if source == canary_file:
                    canary_raw = raw
                else:
                    attempts_raw = raw
        if status in {"passed", "complete"} and (
            canary_raw is None or attempts_raw is None
            or profile_canary_summary is None
        ):
            raise QualificationError("passed profile omitted durable canary proof")
        result.update(
            profile_canary_timeout_seconds=spec.profile_canary_timeout_seconds,
            profile_canary_status=(profile_canary_summary.get("status")
                                   if profile_canary_summary is not None
                                   else "unknown"),
            profile_canary_sha256=sha256(canary_raw) if canary_raw else None,
            profile_canary_attempts_sha256=(sha256(attempts_raw)
                                            if attempts_raw else None),
            profile_canary_protocol_sha256=(
                profile_canary_summary.get("protocol_sha256")
                if profile_canary_summary is not None else None),
            profile_canary_attempt_count=(
                profile_canary_summary.get("attempt_count")
                if profile_canary_summary is not None else None),
            profile_canary_suite=(profile_canary_summary.get("suite")
                                  if profile_canary_summary is not None else None),
        )
    if extended_plan is not None:
        result.update(
            pair_id=evaluation_window.pair_id,
            window_plan_sha256=evaluation_window.source_sha256,
            extended_plan_sha256=sha256(extended_plan),
            extended_serving_profile=extended_plan["extended_serving_profile"],
            extended_serving_profile_sha256=extended_plan[
                "extended_serving_profile_sha256"
            ],
            controller_source_bundle_sha256=extended_plan[
                "controller_source_bundle_sha256"
            ],
            candidate_variant_id=extended_plan["candidate_variant_id"],
            candidate_spec_sha256=extended_plan["candidate_spec_sha256"],
            prior_qualification_receipt_sha256=extended_plan[
                "prior_qualification_receipt_sha256"
            ],
            benchmark_plan_file_sha256=extended_plan[
                "benchmark_plan_file_sha256"
            ],
            benchmark_budget_seconds=extended_plan["benchmark_runtime_budget_seconds"],
            effective_invocation_deadline_seconds=deadline_seconds,
            ui_observer_log_sha256=(ui_observer_summary.get("observer_log_sha256")
                                    if ui_observer_summary is not None else None),
        )
        if followon_kind:
            result.update(
                evaluation_kind="followon",
                qualified_parent_window=extended_plan["qualified_parent_window"],
                group_attempt_status=(evaluation_attempt.get("status")
                                      if evaluation_attempt is not None else None),
                followon_block_count=len(extended_plan["followon_blocks"]),
                followon_block_budget_total_seconds=extended_plan[
                    "followon_block_budget_total_seconds"],
                group_attempt_sha256=None,
            )
            if evaluation_window.v5_parent is not None:
                result["v5_qualified_parent"] = extended_plan[
                    "v5_qualified_parent"]
        else:
            result.update(
                harness_attempt_status=(evaluation_attempt.get("status")
                                        if evaluation_attempt is not None else None),
                harness_run_sha256=(evaluation_attempt.get("harness_run_sha256")
                                    if evaluation_attempt is not None else None),
            )
        from .harness import _read_regular_file

        for source, key, limit in (
            (("group-attempt.json" if followon_kind else "harness-attempt.json"),
             ("group_attempt_sha256" if followon_kind else "harness_attempt_sha256"),
             2_000_000),
            ("probes.json", "probes_file_sha256", 2_000_000),
            ("probe-attempts.json", "probe_attempts_sha256", 2_000_000),
            ("readiness.json", "readiness_file_sha256", 2_000_000),
            ("model-verification.json", "model_verification_file_sha256", 2_000_000),
            ("ui-observer-summary.json", "ui_observer_summary_sha256", 2_000_000),
        ):
            path = output / source
            if path.exists():
                raw, observed = _read_regular_file(path, label=source, max_bytes=limit)
                if observed != path.absolute():
                    raise QualificationError(f"extended {source} is redirected")
                result[key] = sha256(raw)
            else:
                result[key] = None
    else:
        result["finished_at"] = utc_now()
    state["phase"] = "complete"
    state["restoration"] = restoration
    state["result_status"] = status
    write_state()
    finished_usage = {
        "schema": "local-model-research-usage/v1",
        "event": "extended_finished" if extended_plan is not None else "finished",
        "run_id": run_id,
        "observed_at": utc_now(),
        "contract_sha256": plan["contract_sha256"],
        "status": status,
        "elapsed_seconds": elapsed,
        "challenger_gpu_seconds": gpu_seconds,
        "all_gpu_research_seconds": gpu_seconds,
        "resident_downtime_seconds": resident_downtime,
        "restoration_status": restoration["status"],
        "weekly_budget_debit": False,
        "paid_api_calls": 0,
    }
    if extended_plan is not None:
        finished_usage["extended_plan_sha256"] = sha256(extended_plan)
    _append_research_usage(finished_usage, ledger)
    if extended_plan is not None:
        result["finished_at"] = utc_now()
    _atomic_write(output / "result.json", result)
    return result


def _worker_command(contract_path: Path, output: Path) -> list[str]:
    return [
        sys.executable,
        "-m",
        "bench.flash_next_ab.qualification",
        "--worker",
        "--contract",
        str(contract_path),
        "--output-dir",
        str(output),
    ]


def _read_bounded_run_json(path: Path, *, source: str) -> dict[str, Any]:
    """Read one run receipt without following any path component or FIFO."""
    from .harness import HarnessError, _read_regular_file

    try:
        raw, normalized = _read_regular_file(
            path,
            label=source,
            max_bytes=4 * 1024 * 1024,
        )
    except HarnessError as exc:
        raise QualificationError(str(exc)) from exc
    if normalized != path.absolute():
        raise QualificationError(f"{source} path changed")
    return _strict_json(raw, source=source)


def _write_cgroup_diagnostics(
    output: Path, candidate_id: str | None, *, required: bool,
    spec: CandidateSpec | None = None,
    extended_plan: dict[str, Any] | None = None,
) -> tuple[str | None, str | None]:
    """Bind phase telemetry to the raw memory stream after the monitor closes."""
    runtime = _runtime_identity(spec)
    if candidate_id is None:
        if required:
            raise QualificationError("passed no-swap attempt has no candidate ID")
        return None, None
    from .harness import _read_regular_file

    memory_file = output / "memory.jsonl"
    extended_profile = (
        extended_plan["extended_serving_profile"] if extended_plan is not None
        else None
    )
    permitted_phases = (
        {"setup", "load", "ready", "probes", "evaluation", "restoration"}
        if extended_plan is not None else
        {"setup", "load", "ready", "probes", "restoration"}
    )
    raw, observed = _read_regular_file(
        memory_file, label="extended raw memory" if extended_plan is not None
        else "C0-S1 raw memory",
        max_bytes=extended_profile["max_raw_memory_bytes"] if extended_profile
        is not None else 32 * 1024 * 1024,
    )
    if observed != memory_file.absolute():
        raise QualificationError("C0-S1 raw memory redirected")
    if extended_profile is not None and len(raw.splitlines()) > extended_profile["max_memory_rows"]:
        raise QualificationError("extended memory sampling exceeded the finite row ceiling")
    phase_rows: dict[str, dict[str, Any]] = {}
    host_phase_rows: dict[str, dict[str, Any]] = {}
    attributed = 0
    max_current = 0
    for index, line in enumerate(raw.splitlines(), 1):
        row = _strict_json(line, source=f"C0-S1 memory line {index}")
        phase = row.get("monitor_phase")
        if row.get("schema") == "qwen-flash-next-memory-sample/v3" and phase in permitted_phases:
            pswpin = row.get("pswpin_pages")
            psi = row.get("host_memory_psi_total_us")
            if (
                type(pswpin) is not int or pswpin < 0
                or not isinstance(psi, dict) or set(psi) != {"some", "full"}
                or any(type(value) is not int or value < 0 for value in psi.values())
            ):
                if required:
                    raise QualificationError("C0-S1 raw host paging/PSI diagnostic is malformed")
                continue
            host_observation = {
                "observed_at": row.get("observed_at"),
                "host_meminfo_kib": row.get("host_meminfo_kib"),
                "mem_available_gib": row.get("mem_available_gib"),
                "host_pswpout_pages": row.get("pswpout_pages"),
                "host_pswpin_pages": pswpin,
                "host_memory_psi_total_us": psi,
            }
            host_phase_rows.setdefault(phase, {"first": host_observation})[
                "last"
            ] = host_observation
        candidate = row.get("candidate")
        if not isinstance(candidate, dict) or candidate.get("armed") is not True:
            continue
        cgroup = candidate.get("cgroup")
        if not isinstance(cgroup, dict) or candidate.get("id") != candidate_id:
            if required:
                raise QualificationError("C0-S1 candidate diagnostic identity changed")
            continue
        if phase not in permitted_phases - {"setup"}:
            if required:
                raise QualificationError("C0-S1 candidate diagnostic phase changed")
            continue
        attributed += 1
        current = cgroup.get("memory_current_bytes")
        if (
            isinstance(current, bool)
            or not isinstance(current, int)
            or current < 0
        ):
            if required:
                raise QualificationError("C0-S1 candidate memory.current is malformed")
            continue
        max_current = max(max_current, current)
        evidence = {
            "observed_at": row.get("observed_at"),
            "host_meminfo_kib": row.get("host_meminfo_kib"),
            "candidate_cgroup": cgroup,
            "mem_available_gib": row.get("mem_available_gib"),
            "host_pswpout_pages": row.get("pswpout_pages"),
            "host_pswpin_pages": row.get("pswpin_pages"),
            "host_memory_psi_total_us": row.get("host_memory_psi_total_us"),
        }
        phase_rows.setdefault(phase, {"first": evidence})["last"] = evidence
    if required and (
        attributed == 0
        or not ({"load", "ready", "probes", "evaluation"}
                if extended_plan is not None else {"load", "ready", "probes"}).issubset(phase_rows)
        or not permitted_phases.issubset(
            host_phase_rows
        )
    ):
        raise QualificationError("passed no-swap attempt lacks attributed phase snapshots")
    sidecar = {
        "schema": ("flash-next-extended-cgroup-diagnostics/v1" if extended_plan
                   is not None else
                   "qwen-flash-next-c0-mia-s1-cgroup-diagnostics/v1"
                   if spec is not None and spec.contract_schema.endswith("/v4") else
                   "qwen-flash-next-mia-followon-cgroup-diagnostics/v1"
                   if spec is not None else "qwen-flash-next-c0-s1-cgroup-diagnostics/v1"),
        "candidate_id": candidate_id,
        "memory_log_sha256": sha256(raw),
        "attributed_samples": attributed,
        "maximum_memory_current_bytes": max_current,
        "registered_memory_max_bytes": runtime.memory_limit_bytes,
        "registered_swap_max_bytes": 0,
        "phase_first_last": phase_rows,
        "phase_host_first_last": host_phase_rows,
        "host_swap_action": (
            "registered_startup_and_extended_serving_rate_gates_host_total_diagnostic"
            if extended_plan is not None else
            "registered_startup_and_serving_byte_gates"
        ),
        "diagnostics_finished_at": utc_now(),
    }
    if extended_plan is not None:
        sidecar["extended_plan_sha256"] = sha256(extended_plan)
        sidecar["extended_serving_profile_sha256"] = extended_plan[
            "extended_serving_profile_sha256"
        ]
    if spec is not None:
        sidecar["candidate"] = {"id": spec.spec_id,
                                "spec_sha256": spec.identity_sha256()}
    sidecar_file = output / "cgroup-diagnostics.json"
    _atomic_write(sidecar_file, sidecar)
    sidecar_raw, observed_sidecar = _read_regular_file(
        sidecar_file, label="C0-S1 diagnostic sidecar", max_bytes=2 * 1024 * 1024
    )
    if observed_sidecar != sidecar_file.absolute():
        raise QualificationError("C0-S1 diagnostic sidecar redirected")
    return sha256(sidecar_raw), sha256(raw)


def _validated_recovery_state(
    output: Path, plan: dict[str, Any], *, spec: CandidateSpec | None = None,
    extended_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    path = output / "state.json"
    state = _read_bounded_run_json(path, source="worker recovery state")
    if (
        state.get("schema") != ("flash-followon-flash-state/v1"
                                if extended_plan is not None
                                and extended_plan.get("evaluation_kind") == "followon"
                                else "flash-next-extended-evaluation-state/v2" if extended_plan
                                is not None else _mia_standard_schema("state", spec) if spec is not None
                                else "qwen-flash-next-qualification-state/v3")
        or state.get("run_id") != output.name
        or state.get("contract_sha256") != plan["contract_sha256"]
        or state.get("plan_sha256") != sha256(plan)
        or state.get("boot_id") != Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    ):
        raise QualificationError("worker recovery state is not bound to this run and boot")
    if spec is not None and (
        state.get("candidate") != plan.get("candidate")
        or state.get("model_artifact_sha256") != spec.model_artifact_sha256()
        or plan.get("candidate") != {"id": spec.spec_id,
                                    "spec_sha256": spec.identity_sha256()}
    ):
        raise QualificationError("worker recovery Mia spec differs from plan")
    if extended_plan is not None and (
        state.get("pair_id") != extended_plan["pair_id"]
        or state.get("window_plan_path") != extended_plan["window_plan_path"]
        or state.get("window_plan_sha256") != extended_plan["window_plan_sha256"]
        or state.get("extended_plan_sha256") != sha256(extended_plan)
        or state.get("prior_qualification_receipt_sha256")
           != extended_plan["prior_qualification_receipt_sha256"]
        or state.get("extended_serving_profile")
           != extended_plan["extended_serving_profile"]
        or state.get("extended_serving_profile_sha256")
           != extended_plan["extended_serving_profile_sha256"]
        or state.get("controller_source_bundle_sha256")
           != extended_plan["controller_source_bundle_sha256"]
    ):
        raise QualificationError("extended worker recovery source/profile changed")
    if extended_plan is not None and extended_plan.get("evaluation_kind") == "followon":  # noqa: SIM102 - separate parent contract check
        if (state.get("evaluation_kind") != "followon"
            or state.get("qualified_parent_window")
               != extended_plan["qualified_parent_window"]
            or state.get("followon_blocks") != extended_plan["followon_blocks"]
            or (extended_plan.get("schema_version")
                == "flash-followon-flash-plan/v2" and
                state.get("v5_qualified_parent")
                != extended_plan.get("v5_qualified_parent"))):
            raise QualificationError("follow-on recovery group or parent changed")
    if (
        isinstance(state.get("worker_pid"), bool)
        or not isinstance(state.get("worker_pid"), int)
        or state["worker_pid"] <= 0
        or isinstance(state.get("worker_start_ticks"), bool)
        or not isinstance(state.get("worker_start_ticks"), int)
        or state["worker_start_ticks"] <= 0
        or state.get("memory_log_relpath") != "memory.jsonl"
        or state.get("paging_policy") != (spec.paging_policy() if spec is not None
                                          else PAGING_POLICY)
        or state.get("monitor_phase")
        not in ({"setup", "load", "ready", "probes", "evaluation", "restoration"}
                if extended_plan is not None else
                {"setup", "load", "ready", "probes", "restoration"})
        or not isinstance(state.get("invocation_deadline_at"), str)
        or not isinstance(state.get("updated_at"), str)
    ):
        raise QualificationError("worker recovery process identity is invalid")
    candidate_id = state.get("candidate_id")
    if candidate_id is not None and not re.fullmatch(r"[0-9a-f]{64}", str(candidate_id)):
        raise QualificationError("worker recovery candidate ID is invalid")
    candidate_cgroup_path = state.get("candidate_cgroup_path")
    candidate_cgroup_pid = state.get("candidate_cgroup_pid")
    candidate_cgroup_start_ticks = state.get("candidate_cgroup_start_ticks")
    if (
        any(
            value is not None
            for value in (
                candidate_cgroup_path,
                candidate_cgroup_pid,
                candidate_cgroup_start_ticks,
            )
        )
        and (
            candidate_id is None
            or candidate_cgroup_path
            != f"/system.slice/docker-{candidate_id}.scope"
            or isinstance(candidate_cgroup_pid, bool)
            or not isinstance(candidate_cgroup_pid, int)
            or candidate_cgroup_pid <= 0
            or isinstance(candidate_cgroup_start_ticks, bool)
            or not isinstance(candidate_cgroup_start_ticks, int)
            or candidate_cgroup_start_ticks <= 0
        )
    ):
        raise QualificationError("worker recovery candidate cgroup is invalid")
    initial = state.get("initial")
    if initial is not None:
        if not isinstance(initial, dict) or not isinstance(initial.get("nara_was_active"), bool):
            raise QualificationError("worker recovery initial state is invalid")
        residents = initial.get("residents")
        if not isinstance(residents, list) or len(residents) != len(RESIDENTS):
            raise QualificationError("worker recovery resident set is invalid")
        by_name = {row.get("name"): row for row in residents if isinstance(row, dict)}
        for expected in RESIDENTS:
            row = by_name.get(expected["name"])
            if (
                row is None
                or row.get("id") != expected["id"]
                or row.get("image") != expected["image_id"]
                or row.get("running") is not True
                or row.get("oom_killed") is not False
                or row.get("state_error") != ""
                or row.get("restart_policy") != "unless-stopped"
                or isinstance(row.get("restart_count"), bool)
                or not isinstance(row.get("restart_count"), int)
                or row["restart_count"] < 0
            ):
                raise QualificationError("worker recovery resident identity is untrusted")
    return state


def _result_has_verified_restoration(
    output: Path, plan: dict[str, Any], *, spec: CandidateSpec | None = None,
    extended_plan: dict[str, Any] | None = None,
) -> bool:
    path = output / "result.json"
    try:
        result = _read_bounded_run_json(path, source="worker result")
    except QualificationError:
        return False
    restoration = result.get("restoration")
    try:
        started_at = datetime.fromisoformat(result["started_at"])
        verified_at = datetime.fromisoformat(restoration["verified_at"])
        finished_at = datetime.fromisoformat(result["finished_at"])
        timestamps_sane = (
            started_at.tzinfo is not None
            and verified_at.tzinfo is not None
            and finished_at.tzinfo is not None
            and started_at
            <= verified_at
            <= finished_at
            <= datetime.now(timezone.utc) + timedelta(minutes=5)
        )
    except (KeyError, TypeError, ValueError):
        timestamps_sane = False
    followon_kind = (extended_plan is not None
                     and extended_plan.get("evaluation_kind") == "followon")
    attempt_complete = (
        result.get("group_attempt_status") == "blocks_complete_pending_restoration"
        and isinstance(result.get("group_attempt_sha256"), str)
        if followon_kind else
        result.get("harness_attempt_status") == "harness_complete_pending_restoration"
        and isinstance(result.get("harness_run_sha256"), str)
    )
    final_restored = (
        isinstance(restoration, dict)
        and isinstance(restoration.get("final_observation"), dict)
        and restoration["final_observation"].get("sentinel_by_name") is None
        and restoration["final_observation"].get("sentinel_by_id") is None
        and isinstance(result.get("ui_observer_log_sha256"), str)
    )
    if extended_plan is not None and (
        result.get("pair_id") != extended_plan["pair_id"]
        or result.get("window_plan_sha256") != extended_plan["window_plan_sha256"]
        or result.get("extended_plan_sha256") != sha256(extended_plan)
        or result.get("candidate_variant_id") != extended_plan["candidate_variant_id"]
        or result.get("candidate_spec_sha256")
           != extended_plan["candidate_spec_sha256"]
        or result.get("extended_serving_profile_sha256")
           != extended_plan["extended_serving_profile_sha256"]
        or result.get("controller_source_bundle_sha256")
           != extended_plan["controller_source_bundle_sha256"]
        or result.get("prior_qualification_receipt_sha256")
           != extended_plan["prior_qualification_receipt_sha256"]
        or result.get("benchmark_plan_file_sha256")
           != extended_plan["benchmark_plan_file_sha256"]
        or result.get("effective_invocation_deadline_seconds")
           != extended_plan["effective_invocation_deadline_seconds"]
        or result.get("status") not in {"complete", "failed", "unknown"}
        or (result.get("status") == "complete"
            and (not attempt_complete or not final_restored))
    ):
        return False
    return bool(
        result.get("schema") == ("flash-followon-flash-result/v1"
                                 if extended_plan is not None
                                 and extended_plan.get("evaluation_kind") == "followon"
                                 else "flash-next-extended-evaluation-result/v2" if extended_plan
                                 is not None else _mia_standard_schema("result", spec) if spec is not None
                                 else "qwen-flash-next-qualification-result/v3")
        and result.get("run_id") == output.name
        and result.get("contract_sha256") == plan["contract_sha256"]
        and result.get("plan_sha256") == sha256(plan)
        and (spec is None or result.get("candidate") == plan.get("candidate"))
        and isinstance(restoration, dict)
        and restoration.get("status") == "verified"
        and restoration.get("errors") == []
        and restoration.get("sentinel_retained") is False
        and timestamps_sane
    )


def supervisor_emergency_restore(
    output: Path,
    plan: dict[str, Any],
    *,
    deadline: float,
    ops: HostOps | None = None,
    spec: CandidateSpec | None = None,
    extended_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Recover a killed worker from its last durable exact-ID state."""
    ops = ops or HostOps()
    receipt: dict[str, Any] = {
        "schema": ("flash-followon-flash-supervisor-recovery/v1"
                   if extended_plan is not None
                   and extended_plan.get("evaluation_kind") == "followon"
                   else "flash-next-extended-supervisor-recovery/v1" if extended_plan
                   is not None else
                   "qwen-flash-next-supervisor-recovery/v2"
                   if spec is not None and spec.contract_schema.endswith("/v4") else
                   "qwen-flash-next-supervisor-recovery/v3"
                   if spec is not None else "qwen-flash-next-supervisor-recovery/v1"),
        "run_id": output.name,
        "started_at": utc_now(),
        "status": "unknown",
        "restoration": None,
        "error": None,
    }
    if spec is not None:
        receipt["candidate"] = plan["candidate"]
    if extended_plan is not None:
        receipt["extended_plan_sha256"] = sha256(extended_plan)
    try:
        state = _validated_recovery_state(output, plan, spec=spec,
                                          extended_plan=extended_plan)
        root = canonical_root(ROOT)
        with resource_lease(root):
            restoration = restore_exact(
                ops,
                state,
                deadline=deadline,
                diagnostic_path=output / "candidate.supervisor.log",
                **({"extended_plan": extended_plan} if extended_plan is not None else {}),
                **({"spec": spec} if spec is not None else {}),
            )
        receipt["restoration"] = restoration
        receipt["status"] = restoration["status"]
        state["phase"] = "supervisor_recovered" if restoration["status"] == "verified" else "recovery_unknown"
        state["restoration"] = restoration
        state["updated_at"] = utc_now()
        _atomic_write(output / "state.json", state)
    except BaseException as exc:  # noqa: BLE001 - emergency recovery always emits a receipt
        receipt["error"] = f"{type(exc).__name__}: {exc}"
    receipt["finished_at"] = utc_now()
    _atomic_write(output / "supervisor-recovery.json", receipt)
    _append_research_usage(
        {
            "schema": "local-model-research-usage/v1",
            "event": "extended_supervisor_recovery" if extended_plan is not None
            else "supervisor_recovery",
            "run_id": output.name,
            "observed_at": utc_now(),
            "contract_sha256": plan["contract_sha256"],
            "restoration_status": receipt["status"],
            **({"extended_plan_sha256": sha256(extended_plan)}
               if extended_plan is not None else {}),
            "weekly_budget_debit": False,
            "paid_api_calls": 0,
        }
    )
    return receipt


def supervise_run(
    contract: dict[str, Any], contract_sha: str, output: Path,
    *, spec: CandidateSpec | None = None,
) -> int:
    from .followon_profiles import requires_profile_canary

    v5_profile = requires_profile_canary(spec)
    output = _validate_output(output, must_be_absent=True, spec=spec)
    contract_raw = _verified_contract_raw(contract, contract_sha, spec=spec)
    output.mkdir(mode=0o700)
    plan = plan_qualification(contract, contract_sha, output, spec=spec)
    _atomic_write_bytes(output / "launch-contract.raw.json", contract_raw)
    _atomic_write(output / "launch-contract.snapshot.json", contract)
    _atomic_write(output / "plan.json", plan)
    env = dict(os.environ)
    for name in (
        "MOCK_LLM",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "VLLM_API_KEY",
        "WRAPPER_PROFILE_OVERRIDES",
    ):
        env.pop(name, None)
    command = _worker_command(spec.contract_path if spec is not None else CONTRACT_PATH, output)
    start = time.monotonic()
    deadline = start + contract["safety"]["invocation_deadline_seconds"]
    work_cutoff = deadline - contract["safety"]["restoration_reserve_seconds"]
    terminated = False
    killed = False
    v5_boot_id = None
    v5_worker_start_ticks = None
    with (output / "controller.log").open("xb") as stream:
        proc = subprocess.Popen(
            command,
            cwd=ROOT,
            env=env,
            stdout=stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        if v5_profile:
            # These are observation receipts, not admission shortcuts. If
            # the process disappears before capture, keep restoration active
            # and publish an ineligible v5 supervision receipt.
            try:
                v5_worker_start_ticks = _process_start_ticks(proc.pid)
                v5_boot_id = Path(
                    "/proc/sys/kernel/random/boot_id"
                ).read_text().strip()
            except (OSError, QualificationError, ValueError):
                v5_worker_start_ticks = None
                v5_boot_id = None
        while proc.poll() is None and time.monotonic() < work_cutoff:
            time.sleep(min(1, max(0, work_cutoff - time.monotonic())))
        if proc.poll() is None:
            terminated = True
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        # If the worker ignores TERM, retain half of the restoration reserve
        # for a fresh supervisor-owned exact-ID recovery attempt.
        emergency_reserve = min(
            300, contract["safety"]["restoration_reserve_seconds"] / 2
        )
        force_cutoff = max(time.monotonic(), deadline - emergency_reserve)
        while proc.poll() is None and time.monotonic() < force_cutoff:
            time.sleep(min(1, max(0, force_cutoff - time.monotonic())))
        if proc.poll() is None:
            killed = True
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            proc.wait(timeout=max(0.1, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            killed = True
    emergency = None
    if not _result_has_verified_restoration(output, plan, spec=spec):
        emergency = supervisor_emergency_restore(output, plan, deadline=deadline,
                                                 **({"spec": spec} if spec is not None else {}))
    supervision = {
        "schema": "qwen-flash-next-supervision/v1",
        "argv": command,
        "argv_sha256": sha256(command),
        "pid": proc.pid,
        "returncode": proc.returncode,
        "terminated_at_work_cutoff": terminated,
        "force_killed": killed,
        "emergency_recovery": emergency,
        "elapsed_seconds": time.monotonic() - start,
        "hard_deadline_seconds": contract["safety"]["invocation_deadline_seconds"],
        "finished_at": utc_now(),
    }
    if v5_profile:
        supervision["boot_id"] = v5_boot_id
        supervision["worker_start_ticks"] = v5_worker_start_ticks
    _atomic_write(output / "supervision.json", supervision)
    return 0 if (
        proc.returncode == 0
        and not killed
        and _result_has_verified_restoration(output, plan, spec=spec)
    ) else 1


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true")
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def _mia_main(args: argparse.Namespace) -> int:
    """Dispatch one registered Mia v4/v5 spec without module-global switching."""
    from .candidate_registry import select_candidate
    from .mia_candidate_integration import (
        MiaRegistrationError,
        load_mia_contract,
        plan_mia_qualification,
        validate_output,
    )
    try:
        contract, contract_sha = load_mia_contract(args.contract, sys.modules[__name__])
        spec = select_candidate(contract)
        if spec is None:
            raise MiaRegistrationError("Mia contract selected legacy NVIDIA")
        output = validate_output(args.output_dir, spec, must_be_absent=args.run)
        plan = plan_mia_qualification(contract, contract_sha, output, sys.modules[__name__])
    except MiaRegistrationError as exc:
        raise QualificationError(str(exc)) from exc
    if args.plan:
        print(json.dumps(plan, sort_keys=True, indent=2, allow_nan=False))
        return 0
    if args.run:
        return supervise_run(contract, contract_sha, output, spec=spec)
    if not output.is_dir() or not (output / "plan.json").is_file():
        raise QualificationError("Mia worker output has no supervisor plan")
    recorded = _read_bounded_run_json(output / "plan.json", source="Mia supervisor plan")
    if recorded != plan:
        raise QualificationError("Mia worker plan differs from supervisor plan")
    result = execute_worker(plan, contract, output, spec=spec)
    return 0 if result["status"] == "passed" else 1


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    # Preserve the NVIDIA v3 execution path without importing Mia data at all.
    mia_contract_parent = Path(
        "/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-14/"
        "qwen-flash-next-research/runtime"
    )
    mia_contract_names = frozenset({
        "launch-contract.mia-c0.json",
        "launch-contract.mia-mtp1-fullvocab.json",
        "launch-contract.mia-mtp2-fullvocab.json",
        "launch-contract.mia-mtp3-fullvocab.json",
            "launch-contract.mia-mtp3-reduced47k-v2full4.json",
        "launch-contract.mia-native69632-bf16kv3g.json",
    })
    if args.contract.absolute().parent == mia_contract_parent and args.contract.name in mia_contract_names:
        return _mia_main(args)
    contract, contract_sha = load_contract(args.contract)
    output = _validate_output(args.output_dir, must_be_absent=args.run)
    plan = plan_qualification(contract, contract_sha, output)
    if args.plan:
        print(json.dumps(plan, sort_keys=True, indent=2, allow_nan=False))
        return 0
    if args.run:
        return supervise_run(contract, contract_sha, output)
    if not output.is_dir() or not (output / "plan.json").is_file():
        raise QualificationError("worker output has no supervisor plan")
    recorded = _strict_json((output / "plan.json").read_bytes(), source="supervisor plan")
    if recorded != plan:
        raise QualificationError("worker plan differs from the supervisor plan")
    result = execute_worker(plan, contract, output)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except QualificationError as exc:
        print(f"qualification refused: {exc}", file=sys.stderr)
        raise SystemExit(2)
