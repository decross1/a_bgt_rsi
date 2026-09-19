"""Code-owned Mia follow-on profiles with distinct immutable runtime identities.

Definitions have no model or service effects at import.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from bench.flash_next_ab.candidate_registry import MIA, CandidateSpec
from bench.flash_next_ab.fp8_profile_literal import make_fp8_qsa_spec
from bench.flash_next_ab.reduced_profile_literal import make_reduced_spec

MTP_MODULE_SHA256 = "7735cee47d0d1e4776bebd30d907e4a62160409ce4ef2d65611559f8d58af431"
FOLLOWON_SCHEMA = "qwen-flash-next-qualification/v5"
CACHE_PARENT = MIA.compile_cache.parent
CONTRACT_PARENT = MIA.contract_path.parent


def _mtp(depth: int) -> CandidateSpec:
    if depth not in (1, 2, 3):
        raise ValueError("native full-vocabulary MTP depth must be 1, 2, or 3")
    return replace(
        MIA,
        spec_id=f"mia-925d7be6-mtp{depth}-fullvocab-v1",
        contract_schema=FOLLOWON_SCHEMA,
        contract_id=f"qwen38-flash-next-mia-mtp{depth}-fullvocab-20260915",
        profile=f"MIA-MTP{depth}-FULLVOCAB-32K",
        container_name=f"vllm-qwen-ab-flash-mia-mtp{depth}-20260915",
        compile_cache=CACHE_PARENT / f"qwen38-flash-next-mia-d038-mtp{depth}-fullvocab",
        contract_path=CONTRACT_PARENT / f"launch-contract.mia-mtp{depth}-fullvocab.json",
        run_id_prefix=f"qfn-mia-mtp{depth}-",
        mtp_speculative_tokens=depth,
        qualification_probe_set="flash-next-mtp-fullvocab-v1",
        mtp_module_sha256=MTP_MODULE_SHA256,
    )


MIA_MTP1 = _mtp(1)
MIA_MTP2 = _mtp(2)
MIA_MTP3 = _mtp(3)
MIA_CTX69632 = replace(
    MIA,
    spec_id="mia-925d7be6-ctx69632-bf16kv3g-v1",
    contract_schema=FOLLOWON_SCHEMA,
    contract_id="qwen38-flash-next-mia-native69632-bf16kv3g-20260915",
    profile="MIA-NATIVE69632-BF16KV3G-MTP0",
    container_name="vllm-qwen-ab-flash-mia-ctx69632-20260915",
    compile_cache=CACHE_PARENT / "qwen38-flash-next-mia-d038-native69632-bf16kv3g",
    contract_path=CONTRACT_PARENT / "launch-contract.mia-native69632-bf16kv3g.json",
    run_id_prefix="qfn-mia-ctx69632-",
    max_model_len=69_632,
    kv_cache_memory_bytes=3 * 1024**3,
    profile_canary_timeout_seconds=300,
    qualification_probe_set="flash-next-native69632-v1",
)

MIA_MTP3_REDUCED47K_OPT = make_reduced_spec(MIA_MTP3)
MIA_MTP3_REDUCED47K_FP8_QSA = make_fp8_qsa_spec(MIA_MTP3_REDUCED47K_OPT)

REGISTERED_MIA_SPECS: tuple[CandidateSpec, ...] = (
    MIA, MIA_MTP1, MIA_MTP2, MIA_MTP3, MIA_CTX69632,
    MIA_MTP3_REDUCED47K_OPT,
    MIA_MTP3_REDUCED47K_FP8_QSA,
)
SPECS_BY_CONTRACT_PATH: dict[Path, CandidateSpec] = {
    spec.contract_path: spec for spec in REGISTERED_MIA_SPECS
}
SPECS_BY_ID: dict[str, CandidateSpec] = {
    spec.spec_id: spec for spec in REGISTERED_MIA_SPECS
}


def is_registered_spec(candidate: CandidateSpec) -> bool:
    """Object identity prevents a contract from manufacturing a sixth variant."""
    return any(candidate is spec for spec in REGISTERED_MIA_SPECS)


def requires_profile_canary(candidate: CandidateSpec | None) -> bool:
    """Only literal v5 Mia profiles require the extra post-probe canary."""
    return any(candidate is spec for spec in
               (MIA_MTP1, MIA_MTP2, MIA_MTP3, MIA_CTX69632,
                MIA_MTP3_REDUCED47K_OPT, MIA_MTP3_REDUCED47K_FP8_QSA))


def select_mia_contract(contract: dict) -> CandidateSpec:
    """Resolve one exact schema/id/profile/spec tuple, never model prose."""
    if not isinstance(contract, dict):
        raise TypeError("Mia contract is not an object")
    candidate = contract.get("candidate")
    spec_id = candidate.get("id") if isinstance(candidate, dict) else None
    spec = SPECS_BY_ID.get(spec_id)
    if spec is None or not is_registered_spec(spec):
        raise ValueError("unregistered Mia follow-on spec")
    if (
        contract.get("schema") != spec.contract_schema
        or contract.get("contract_id") != spec.contract_id
        or contract.get("profile") != spec.profile
        or candidate != {"id": spec.spec_id, "spec_sha256": spec.identity_sha256()}
    ):
        raise ValueError("Mia profile identity differs from code-owned registration")
    return spec
