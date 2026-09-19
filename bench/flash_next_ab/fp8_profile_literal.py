"""Immutable QSA FP8 overlay for the reduced-vocabulary Mia runtime.

The child image was built as a CPU-only two-file COPY overlay.  Its build
receipt binds the exact parent image, source generator, generated modules and
resulting image ID.  Importing this module has no Docker, model or service
effects.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from .candidate_registry import CandidateSpec

FP8_QSA_CHILD_IMAGE_ID = (
    "sha256:ba65a549de4dce8cab70f27c200e408b28470ea175fc8c301e27b4deb154fbed"
)
FP8_QSA_PARENT_IMAGE_ID = (
    "sha256:29eab5a29b765eef8b6405bbe0f2d385fc1e7b5e3c7ae18ae70382a68a0a2201"
)
FP8_QSA_BUILD_RECEIPT = Path(
    "/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-18/"
    "flash-personal-recovery/fp8-runtime-build/build-receipt.json"
)
FP8_QSA_BUILD_RECEIPT_SHA256 = (
    "3a75a795ec167885794a55de29e1a39e537fb0e953508ea9475cfce450e36ebc"
)
FP8_QSA_BUILD_RECEIPT_BYTES = 4_656
FP8_QSA_CONTRACT = FP8_QSA_BUILD_RECEIPT.parent / (
    "launch-contract.mia-mtp3-reduced47k-fp8qsa.json"
)


def make_fp8_qsa_spec(base: CandidateSpec) -> CandidateSpec:
    """Return the one registered FP8-QSA overlay of the optimized parent."""
    if (
        base.spec_id != "mia-925d7be6-mtp3-reduced47k-v2opt-v1"
        or base.image_id != FP8_QSA_PARENT_IMAGE_ID
        or base.mtp_speculative_tokens != 3
        or base.draft_vocab_id_count != 47_149
        or base.v2_model_runner_pin is not True
    ):
        raise ValueError("FP8 QSA child requires the exact optimized parent")
    return replace(
        base,
        spec_id="mia-925d7be6-mtp3-reduced47k-v2opt-fp8qsa-v1",
        contract_id="qwen38-flash-next-mia-mtp3-reduced47k-fp8qsa-20260918",
        profile="MIA-MTP3-REDUCED47K-V2-FULL4-FP8QSA-OVERLAY-32K",
        image_id=FP8_QSA_CHILD_IMAGE_ID,
        image_build_receipt_path=FP8_QSA_BUILD_RECEIPT,
        image_build_receipt_sha256=FP8_QSA_BUILD_RECEIPT_SHA256,
        image_build_receipt_bytes=FP8_QSA_BUILD_RECEIPT_BYTES,
        container_name="vllm-qwen-ab-flash-mia-mtp3-reduced47k-fp8qsa-20260918",
        compile_cache=(
            base.compile_cache.parent / "qwen38-flash-next-mia-mtp3-reduced47k-fp8qsa-v1"
        ),
        contract_path=FP8_QSA_CONTRACT,
        run_id_prefix="qfn-mia-mtp3-red47k-fp8qsa-",
        qualification_probe_set="flash-next-mtp-reduced47k-fp8qsa-v1",
    )
