"""Small public projection seam for registered Mia v5 trial history.

It accepts only a direct-child registered run and delegates
admission to the completed shared v5 qualification validator. Until that gate
exists or succeeds, its public mode remains unknown/ineligible. No private
SSE, prompt, market record, Docker state, or model endpoint is read here.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from bench.flash_next_ab import harness
from bench.flash_next_ab.candidate_registry import CandidateSpec
from bench.flash_next_ab.followon_profiles import (
    MIA_CTX69632,
    MIA_MTP1,
    MIA_MTP2,
    MIA_MTP3,
    MIA_MTP3_REDUCED47K_OPT,
)

FOLLOWON_SPECS: tuple[CandidateSpec, ...] = (
    MIA_MTP1, MIA_MTP2, MIA_MTP3, MIA_CTX69632,
    MIA_MTP3_REDUCED47K_OPT,
)


def spec_for_run_name(name: str) -> CandidateSpec | None:
    if not isinstance(name, str):
        return None
    # The reduced run prefix extends the full-vocabulary MTP3 prefix.
    for spec in sorted(FOLLOWON_SPECS,
                       key=lambda row: len(row.run_id_prefix), reverse=True):
        if re.fullmatch(re.escape(spec.run_id_prefix) +
                        r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", name):
            return spec
    return None


def public_followon_trial(
    run_dir: str | Path, *,
    validator: Callable[..., dict[str, Any]] = harness.validate_flash_qualification_files,
) -> dict[str, Any]:
    directory = Path(run_dir).absolute()
    spec = spec_for_run_name(directory.name)
    if spec is None or directory.parent != spec.output_root:
        raise ValueError("trial is not a direct-child registered follow-on run")
    if directory.is_symlink() or not directory.is_dir() or directory.resolve() != directory:
        raise ValueError("registered trial directory is missing or redirected")
    names = ("result.json", "plan.json", "launch-contract.snapshot.json",
             "launch-contract.raw.json")
    paths = [directory / name for name in names]
    trial = {
        "schema": "flash-next-mia-followon-public-trial/v1",
        "run_id": directory.name, "spec_id": spec.spec_id,
        "profile": spec.profile, "max_model_len": spec.max_model_len,
        "kv_cache_memory_bytes": spec.kv_cache_memory_bytes,
        "mtp_speculative_tokens": spec.mtp_speculative_tokens,
        "status": "unknown", "admission_eligible": False,
        "source_error": None, "qualification_receipt_sha256": None,
        "minimum_mem_available_gib": None, "probe_count": None,
        "restoration_status": None, "comparison_eligible": False,
        "promotion_authorized": False,
    }
    if any(not path.is_file() or path.is_symlink() for path in paths):
        trial["source_error"] = "registered_receipt_bundle_missing"
        return trial
    try:
        summary = validator(paths[0], paths[1], paths[2],
                            contract_raw_path=paths[3], require_passed=False)
        if (not isinstance(summary, dict)
                or summary.get("schema_version") != "flash-next-qualification-validation/v3"
                or summary.get("variant_id") != spec.spec_id
                or summary.get("run_id") != directory.name
                or summary.get("model_artifact_sha256") != spec.model_artifact_sha256()
                or summary.get("served_model") != spec.served_name
                or summary.get("endpoint_name") != spec.endpoint_name):
            raise ValueError("v5 shared gate summary does not bind the literal profile")
        admitted = summary.get("admission_eligible") is True and summary.get("status") == "passed"
        trial.update({
            "status": summary.get("status") if summary.get("status") in
                      {"passed", "failed", "unknown"} else "unknown",
            "admission_eligible": admitted,
            "qualification_receipt_sha256": summary.get("qualification_receipt_sha256"),
            "minimum_mem_available_gib": summary.get("min_mem_available_gib"),
            "probe_count": summary.get("probe_count"),
            "restoration_status": summary.get("restoration_status"),
        })
    except Exception:  # noqa: BLE001 - public projection must fail closed on malformed source
        trial["source_error"] = "v5_shared_admission_unavailable_or_rejected"
    return trial
