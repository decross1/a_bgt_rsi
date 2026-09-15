"""A distinct, admitted v5 Mia parent for grouped windows.

This descriptor is published only after a selected literal v5 profile has
passed its own qualification, canary, supervision and exact restoration gate.
It never treats the old C0 qualification as authority for a new image/route.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bench.flash_next_ab import followon_dispatch as grouped
from bench.flash_next_ab import harness as h
from bench.flash_next_ab.followon_profiles import (
    SPECS_BY_ID,
    is_registered_spec,
    requires_profile_canary,
)
from bench.flash_next_ab.followon_qualification_admission import (
    validate_mia_v5_bundle,
)

SCHEMA = "flash-followon-qualified-v5-parent/v1"
ROOT = grouped.RESEARCH_ROOT / "evaluation/followon-qualified-parents"
QUALIFICATION_ROOT = grouped.RESEARCH_ROOT / "qualification-runs"
RUN_ID = re.compile(r"qfn-mia-[a-z0-9][a-z0-9._-]{0,79}\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
SOURCE_NAMES = (
    "result.json", "plan.json", "launch-contract.snapshot.json",
    "launch-contract.raw.json", "state.json", "supervision.json",
)


class V5ParentError(ValueError):
    pass


@dataclass(frozen=True)
class V5Parent:
    source_path: Path
    source_sha256: str
    document: dict[str, Any]
    spec: Any
    qualification_plan: dict[str, Any]
    qualification_summary: dict[str, Any]

    @property
    def cohort(self) -> str:
        return "flash"

    @property
    def pair_id(self) -> str:
        # This is a qualification run ID, not an A/B pair ID.
        return self.document["qualification_run_id"]


def _require(ok: bool, reason: str) -> None:
    if not ok:
        raise V5ParentError(reason)


def _raw(path: Path, maximum: int = 8 * 1024 * 1024) -> tuple[bytes, str]:
    raw, actual = h._read_regular_file(
        path, label="v5 parent source", max_bytes=maximum,
    )
    _require(actual == path.absolute(), "v5 parent path changed")
    return raw, hashlib.sha256(raw).hexdigest()


def _json(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeError, ValueError, TypeError) as exc:
        raise V5ParentError("v5 parent source is malformed") from exc
    _require(isinstance(value, dict), "v5 parent is not a JSON object")
    return value


def _siblings(run_id: str) -> dict[str, Path]:
    _require(RUN_ID.fullmatch(run_id) is not None,
             "v5 qualification run ID is invalid")
    base = QUALIFICATION_ROOT / run_id
    _require(base.is_dir() and not base.is_symlink()
             and base.resolve() == base,
             "v5 qualification run is not a registered direct child")
    return {name: base / name for name in SOURCE_NAMES}


def _admit(sources: dict[str, Path], raw: dict[str, bytes],
           spec: Any) -> dict[str, Any]:
    result = _json(raw["result.json"])
    plan = _json(raw["plan.json"])
    snapshot = _json(raw["launch-contract.snapshot.json"])
    from .historical_v5_parent_bridge import (
        OLD_ROOT, QUALIFICATION_RUN_ID, replay_reduced_parent,
    )
    if (sources["result.json"].parent.name == QUALIFICATION_RUN_ID
            and plan.get("registered_code_root") == str(OLD_ROOT)):
        summary = replay_reduced_parent(raw, sources, plan, spec)
    else:
        summary = validate_mia_v5_bundle(
            result, hashlib.sha256(raw["result.json"]).hexdigest(),
            sources["result.json"], plan, sources["plan.json"], snapshot,
            hashlib.sha256(raw["launch-contract.snapshot.json"]).hexdigest(),
            sources["launch-contract.snapshot.json"],
            contract_raw_path=sources["launch-contract.raw.json"],
            require_passed=True,
        )
    _require(summary["admission_eligible"] is True
             and summary["variant_id"] == spec.spec_id
             and summary["status"] == "passed"
             and summary["qualification_plan_sha256"]
                == h._qualification_sha256(plan),
             "v5 qualification did not admit this code-owned profile")
    return summary


def build_parent_document(run_id: str) -> dict[str, Any]:
    """Construct, but never publish, a closed descriptor from passed receipts."""
    sources = _siblings(run_id)
    raw = {name: _raw(path)[0] for name, path in sources.items()}
    contract = _json(raw["launch-contract.snapshot.json"])
    candidate = contract.get("candidate")
    spec_id = candidate.get("id") if isinstance(candidate, dict) else None
    spec = SPECS_BY_ID.get(spec_id)
    _require(spec is not None and is_registered_spec(spec)
             and requires_profile_canary(spec)
             and run_id.startswith(spec.run_id_prefix),
             "v5 parent does not select one registered canary profile")
    summary = _admit(sources, raw, spec)
    return {
        "schema_version": SCHEMA,
        "qualification_run_id": run_id,
        "candidate_spec_id": spec.spec_id,
        "candidate_spec_sha256": spec.identity_sha256(),
        "profile": spec.profile,
        "source_refs": {
            name: {"path": str(path),
                   "sha256": hashlib.sha256(raw[name]).hexdigest()}
            for name, path in sources.items()
        },
        "qualification_receipt_sha256": summary["qualification_receipt_sha256"],
        "qualification_plan_sha256": summary["qualification_plan_sha256"],
        "runtime_sha256": summary["runtime_sha256"],
        "model_artifact_sha256": summary["model_artifact_sha256"],
        "served_model": summary["served_model"],
        "max_model_len": summary["max_model_len"],
        "mtp_speculative_tokens": summary["mtp_speculative_tokens"],
        "kv_cache_memory_bytes": summary["kv_cache_memory_bytes"],
        "promotion_authorized": False,
    }


def load_parent(source_path: Path) -> V5Parent:
    source = Path(source_path).absolute()
    _require(source.parent == ROOT and source.name.endswith(".json"),
             "v5 parent descriptor is outside its registered root")
    run_id = source.name.removesuffix(".json")
    _require(RUN_ID.fullmatch(run_id) is not None,
             "v5 parent descriptor name differs from a qualification run")
    parent_raw, parent_sha = _raw(source, maximum=1_000_000)
    document = _json(parent_raw)
    _require(set(document) == {
        "schema_version", "qualification_run_id", "candidate_spec_id",
        "candidate_spec_sha256", "profile", "source_refs",
        "qualification_receipt_sha256", "qualification_plan_sha256",
        "runtime_sha256", "model_artifact_sha256", "served_model",
        "max_model_len", "mtp_speculative_tokens", "kv_cache_memory_bytes",
        "promotion_authorized",
    } and document["schema_version"] == SCHEMA
       and document["qualification_run_id"] == run_id
       and document["promotion_authorized"] is False,
       "v5 parent descriptor shape differs")
    sources = _siblings(run_id)
    refs = document["source_refs"]
    _require(isinstance(refs, dict) and set(refs) == set(SOURCE_NAMES),
             "v5 parent source references are incomplete")
    raw = {}
    for name, path in sources.items():
        ref = refs[name]
        _require(isinstance(ref, dict) and set(ref) == {"path", "sha256"}
                 and ref["path"] == str(path)
                 and isinstance(ref["sha256"], str)
                 and SHA.fullmatch(ref["sha256"]) is not None,
                 "v5 parent reference path or hash differs")
        raw[name], digest = _raw(path)
        _require(digest == ref["sha256"],
                 "v5 parent source bytes changed after registration")
    spec = SPECS_BY_ID.get(document["candidate_spec_id"])
    _require(spec is not None and is_registered_spec(spec)
             and requires_profile_canary(spec)
             and run_id.startswith(spec.run_id_prefix)
             and document["candidate_spec_sha256"] == spec.identity_sha256()
             and document["profile"] == spec.profile,
             "v5 parent candidate is not the literal registered profile")
    summary = _admit(sources, raw, spec)
    _require(document == build_parent_document(run_id),
             "v5 parent descriptor differs from current admitted receipts")
    return V5Parent(source, parent_sha, document, spec,
                    _json(raw["plan.json"]), summary)


def publish_parent(run_id: str) -> Path:
    """Write one admitted profile descriptor without replacing any old source."""
    from bench.flash_next_ab.followon_prepare import _new_json

    document = build_parent_document(run_id)
    _require(ROOT.parent.is_dir() and not ROOT.parent.is_symlink()
             and ROOT.parent.resolve() == ROOT.parent,
             "v5 parent registered root was redirected")
    source = ROOT / f"{run_id}.json"
    _new_json(source, document)
    admitted = load_parent(source)
    _require(admitted.document == document,
             "new v5 parent did not replay its admitted sources")
    return source


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qualification-run", required=True)
    args = parser.parse_args(argv)
    print(publish_parent(args.qualification_run))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
