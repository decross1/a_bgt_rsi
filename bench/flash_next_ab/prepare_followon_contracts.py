"""Prepare distinct immutable Mia follow-on contracts with O_EXCL.

The authentic Mia C0 contract is read as a source and never rewritten.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path

from bench.flash_next_ab import qualification as q
from bench.flash_next_ab.candidate_registry import MIA, CandidateSpec
from bench.flash_next_ab.followon_profiles import (
    MIA_CTX69632,
    MIA_MTP1,
    MIA_MTP2,
    MIA_MTP3,
    MIA_MTP3_REDUCED47K_FP8_QSA,
    MIA_MTP3_REDUCED47K_OPT,
    is_registered_spec,
)
from bench.flash_next_ab.mia_candidate_integration import (
    read_mia_contract,
    validate_mia_contract,
)

PROFILES = (MIA_MTP1, MIA_MTP2, MIA_MTP3, MIA_CTX69632,
            MIA_MTP3_REDUCED47K_OPT, MIA_MTP3_REDUCED47K_FP8_QSA)


def build_contract(original: dict, spec: CandidateSpec) -> dict:
    if spec not in PROFILES or not is_registered_spec(spec):
        raise ValueError("cannot prepare an unregistered or original C0 profile")
    if original.get("candidate") != {"id": MIA.spec_id,
                                     "spec_sha256": MIA.identity_sha256()}:
        raise ValueError("original Mia C0 contract identity differs")
    value = copy.deepcopy(original)
    value["schema"] = spec.contract_schema
    value["contract_id"] = spec.contract_id
    value["profile"] = spec.profile
    value["candidate"] = {"id": spec.spec_id,
                          "spec_sha256": spec.identity_sha256()}
    value["image"] = {"id": spec.image_id, "architecture": "arm64"}
    value["model"] = spec.expected_model_section()
    value["runtime"] = spec.expected_runtime_section()
    value["probe_set"] = spec.qualification_probe_set
    value["safety"]["min_mem_available_gib"] = spec.min_mem_available_gib
    value["safety"]["paging_policy"] = spec.paging_policy()
    value["safety"]["profile_canary_timeout_seconds"] = (
        spec.profile_canary_timeout_seconds
    )
    return validate_mia_contract(value, q)


def prepare(spec: CandidateSpec) -> dict[str, str]:
    if spec not in PROFILES or not is_registered_spec(spec):
        raise ValueError("only one literal new profile may be prepared")
    original, original_raw_sha, _ = read_mia_contract(MIA.contract_path, q)
    if not MIA.contract_path.is_file():
        raise ValueError("original immutable Mia C0 contract is missing")
    value = build_contract(original, spec)
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                     allow_nan=False).encode() + b"\n"
    path: Path = spec.contract_path
    if not path.parent.is_dir() or path.parent.is_symlink() or path.exists():
        raise ValueError("follow-on contract parent differs or path already exists")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return {
        "spec_id": spec.spec_id, "contract_path": str(path),
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "original_c0_raw_sha256": original_raw_sha,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile-id", choices=[row.spec_id for row in PROFILES],
                        required=True)
    args = parser.parse_args()
    selected = next(row for row in PROFILES if row.spec_id == args.profile_id)
    print(json.dumps(prepare(selected), sort_keys=True, indent=2))
