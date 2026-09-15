"""Immutable reduced-vocabulary MTP3 child profile, built after the C0 pair.

This module only depends on CandidateSpec so the profile registry can import it
without importing itself.  The CPU build receipt is verified at qualification.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from .candidate_registry import CandidateSpec

CHILD_IMAGE_ID = "sha256:29eab5a29b765eef8b6405bbe0f2d385fc1e7b5e3c7ae18ae70382a68a0a2201"
CHILD_MTP_SHA256 = "8da66d9f48bd93c935d74e2635c45483dc999c87b94bc4ce828e727eb1713349"
BUILD_RECEIPT = Path(
    "/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-14/"
    "qwen-flash-next-research/runtime/mia-reduced47k-image-build/IMAGE_BUILD_RECEIPT.json"
)
BUILD_RECEIPT_SHA256 = "96fda39432b9071b225d7da61afd35c49b121176f33b14274da548ef2dabbc6a"
VOCAB = Path(
    "/mnt/models/qwen3.8-flash-next-mia-recipe-d0380900/"
    "files/draft_vocab_en_code_47k.txt"
)


def make_reduced_spec(base: CandidateSpec) -> CandidateSpec:
    """Return one distinct, code-owned V2/FULL4/reduced-MTP3 spec."""
    if base.mtp_speculative_tokens != 3 or base.draft_vocab_path is not None:
        raise ValueError("reduced child requires the full-vocabulary MTP3 base")
    return replace(
        base,
        spec_id="mia-925d7be6-mtp3-reduced47k-v2opt-v1",
        contract_id="qwen38-flash-next-mia-mtp3-reduced47k-v2opt-20260915",
        profile="MIA-MTP3-REDUCED47K-V2-FULL4-MODE0-32K",
        image_id=CHILD_IMAGE_ID,
        image_build_receipt_path=BUILD_RECEIPT,
        image_build_receipt_sha256=BUILD_RECEIPT_SHA256,
        image_build_receipt_bytes=4218,
        container_name="vllm-qwen-ab-flash-mia-mtp3-reduced47k-20260915",
        compile_cache=base.compile_cache.parent / "qwen38-flash-next-mia-mtp3-reduced47k-v2full4",
        contract_path=base.contract_path.parent / "launch-contract.mia-mtp3-reduced47k-v2full4.json",
        run_id_prefix="qfn-mia-mtp3-red47k-",
        qualification_probe_set="flash-next-mtp-reduced47k-v2full4-v1",
        mtp_module_sha256=CHILD_MTP_SHA256,
        draft_vocab_path=VOCAB,
        draft_vocab_bytes=274_530,
        draft_vocab_sha256="20e36b6e8eae2598019298959a578ef8adc2948bbed7189e43a8da9b9d84a0b1",
        draft_vocab_id_count=47_149,
        reduced_mtp_patch_sha256="2c7d19b8021f2c439920ae7f7df6f7b008eb635256a8423ef03e168d3984911f",
        use_local_argmax_reduction=True,
        v2_model_runner_pin=True,
        optimized_compilation_config_json=(
            '{"cudagraph_capture_sizes":[4],"cudagraph_mode":"FULL_DECODE_ONLY","mode":0}'
        ),
    )
