"""Freeze a CPU-only grouped research window from the admitted first pair.

Run this only from the distinct registered follow-on checkout, after the first
126-cell pair closes. It does not call a model, alter services or publish a
result. All block sources are written before the window source, so a partial
preparation cannot be launched as a complete plan.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import uuid
from pathlib import Path

from bench.flash_next_ab import evaluation_window as ew
from bench.flash_next_ab import followon_context as context
from bench.flash_next_ab import followon_dispatch as grouped
from bench.flash_next_ab import followon_market_canaries as market
from bench.flash_next_ab import followon_plans as plans
from bench.flash_next_ab import followon_thinking as thinking
from bench.flash_next_ab import mtp0_controls, mtp_decode_diagnostic

PARENT_ID = "qfn-ab-mia-c0-20260915-a"
STUDY = "thinking-market-diagnostics-v1"
CONTEXT_ORDER = (2048, 8192, 16384)


def _require(ok: bool, reason: str) -> None:
    if not ok:
        raise ValueError(reason)


def _raw(value: dict) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, allow_nan=False) + "\n").encode()


def _new_json(path: Path, value: dict) -> str:
    """Publish one immutable raw source with an atomic no-overwrite link."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _require(path.parent.is_dir() and not path.parent.is_symlink()
             and path.parent.resolve() == path.parent,
             "registered source parent is redirected")
    data = _raw(value)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                 getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path, follow_symlinks=False)
        parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    finally:
        temporary.unlink(missing_ok=True)
    return hashlib.sha256(data).hexdigest()


def _qualified_cap(flash_parent) -> int:
    launch = (flash_parent.qualification_plan.get("docker_create_argv")
              if isinstance(flash_parent.qualification_plan, dict) else None)
    _require(isinstance(launch, list) and launch.count("--max-model-len") == 1,
             "qualified Flash launch does not declare one context ceiling")
    index = launch.index("--max-model-len") + 1
    _require(index < len(launch) and launch[index] == "32768",
             "first C0 Mia parent has a different frozen context lane")
    return int(launch[index])


def _parents(parent_id: str):
    _require(parent_id == PARENT_ID, "only the immutable first pair is a source")
    root = grouped.RESEARCH_ROOT / "evaluation/window-plans"
    return {
        cohort: ew.load_evaluation_window(
            root / f"{parent_id}.{cohort}.window.json",
            expected_cohort=cohort,
        ) for cohort in ("flash", "resident")
    }


def _routes(parents: dict) -> dict:
    flash = parents["flash"]
    resident = parents["resident"]
    fs = flash.qualification_summary
    rs = resident.qualification_summary
    _require(fs.get("admission_eligible") is True
             and fs.get("variant_id") == "mia-925d7be6-c0-s1"
             and rs.get("admission_eligible") is True,
             "both parent qualifications must be admitted")
    routes = {
        "flash_next_mia": {
            "served_model": fs["served_model"],
            "artifact_sha256": fs["model_artifact_sha256"],
            "runtime_sha256": fs["runtime_sha256"],
            "qualification_receipt_sha256": fs["qualification_receipt_sha256"],
            "max_model_len": _qualified_cap(flash),
        },
    }
    for endpoint, model in (("resident_qwen", "qwen3.8-27b-nvfp4-mtp"),
                            ("resident_gemma", "gemma-4-26b-a4b")):
        routes[endpoint] = {
            "served_model": model,
            "artifact_sha256": rs["artifact_sha256_by_endpoint"][endpoint],
            "runtime_sha256": rs["runtime_sha256_by_endpoint"][endpoint],
            "qualification_receipt_sha256": rs["qualification_receipt_sha256"],
            "max_model_len": plans.REGISTERED_CONTEXT_CAPS[endpoint],
        }
    return routes


def _public_route(route: dict) -> dict:
    return {key: value for key, value in route.items()
            if key != "max_model_len"}


def _forms(cohort: str, bands: tuple[int, ...]) -> list[tuple[str, str, int | None,
                                                                int | None, int, dict]]:
    parents = _parents(PARENT_ID)
    routes = _routes(parents)
    mia = _public_route(routes["flash_next_mia"])
    qwen = _public_route(routes["resident_qwen"])
    both = {"resident_qwen": qwen, "flash_next_mia": mia}
    endpoint = "flash_next_mia" if cohort == "flash" else "resident_qwen"
    forms = [
        ("thinking", endpoint, 71, None, grouped.THINKING_CEILING,
         thinking.freeze_plan(thinking.PILOT_ID, both)),
        ("market_canaries", endpoint, 107, None, grouped.MARKET_CEILING,
         market.build_plan(both)),
    ]
    if cohort == "flash":
        forms.extend([
            ("mtp0_controls", endpoint, 17, None, grouped.MTP0_CEILING,
             mtp0_controls.freeze_plan(mia)),
            ("mtp_decode_timing", endpoint, 17, None,
             grouped.MTP_DECODE_CEILING,
             mtp_decode_diagnostic.freeze_plan(
                 "mia-925d7be6-c0-s1", mia)),
        ])
    for band in bands:
        selected = ("resident_gemma" if cohort == "resident" and band == 16384
                    else endpoint)
        forms.append(("context", selected, None, band,
                      grouped.CONTEXT_CEILINGS[band],
                      context.freeze_plan(selected, routes[selected])))
    return forms


def prepare(window_id: str, *, cohort: str,
            context_bands: tuple[int, ...] = ()) -> Path:
    """Freeze the exact ordered core, optionally followed by a context prefix."""
    _require(grouped.WINDOW_ID.fullmatch(window_id) is not None
             and cohort in {"flash", "resident"}
             and context_bands == CONTEXT_ORDER[:len(context_bands)],
             "window, cohort or ordered context prefix is unregistered")
    root = grouped.RESEARCH_ROOT
    _require(root.is_dir() and not root.is_symlink()
             and root.resolve() == root,
             "registered research root is unavailable")
    source_path = grouped._plan_path(window_id, cohort, root)
    output = grouped._output_path(window_id, cohort, root)
    _require(not source_path.exists() and not output.exists()
             and not source_path.is_symlink() and not output.is_symlink(),
             "follow-on source or output already exists")
    parents = _parents(PARENT_ID)
    routes = _routes(parents)
    forms = _forms(cohort, context_bands)
    total = sum(item[4] for item in forms)
    _require(total + grouped.RESTORE_RESERVE < grouped.OUTER_DEADLINE,
             "group leaves no cold-start or restoration headroom")
    bundle = grouped.frozen_followon_source_bundle()
    block_docs = []
    planned_files = []
    namespace = hashlib.sha256(f"{window_id}:{cohort}".encode()).hexdigest()[:12]
    for ordinal, (kind, endpoint, seed, target, ceiling, plan) in enumerate(forms):
        block_id = f"followon-{namespace}-{ordinal}-{kind}"
        path = root / "evaluation/followon-block-plans" / f"{block_id}.json"
        _require(not path.exists() and not path.is_symlink(),
                 "declared block source already exists")
        planned_files.append((path, plan))
        block_docs.append({"ordinal": ordinal, "block_id": block_id,
                           "kind": kind, "plan_path": str(path),
                           "plan_raw_sha256": hashlib.sha256(_raw(plan)).hexdigest(),
                           "endpoint_name": endpoint, "seed_block": seed,
                           "target_block": target,
                           "wall_ceiling_seconds": ceiling,
                           "output_relative": f"blocks/{ordinal:02d}-{block_id}"})
    parent = parents[cohort]
    parent_ref = {"path": str(parent.source_path),
                  "sha256": parent.source_sha256}
    binding_names = ({"flash_next_mia"} if cohort == "flash"
                     else {"resident_qwen", "resident_gemma"})
    window = {
        "schema_version": grouped.WINDOW_SCHEMA,
        "window_id": window_id, "study_id": STUDY, "cohort": cohort,
        "output_dir": str(output),
        "candidate_variant_id": "mia-925d7be6-c0-s1" if cohort == "flash" else None,
        "route_bindings": {name: routes[name] for name in binding_names},
        "blocks": block_docs, "qualified_parent_window": parent_ref,
        "registered_code_root": str(grouped.FOLLOWON_CODE_ROOT),
        "followon_source_bundle": bundle,
        "followon_source_bundle_sha256": grouped._canonical_sha(bundle),
        "deadline_seconds": grouped.OUTER_DEADLINE,
        "restoration_reserve_seconds": grouped.RESTORE_RESERVE,
        "block_budget_total_seconds": total,
        "promotion_authorized": False,
    }
    _require(grouped._shape(STUDY, cohort, block_docs),
             "prepared blocks do not match the exact study order")
    for path, plan in planned_files:
        _require(_new_json(path, plan) == next(
            block["plan_raw_sha256"] for block in block_docs
            if block["plan_path"] == str(path)),
            "prepared block raw digest differs")
    _new_json(source_path, window)  # Last publication is the launchable source.
    checked = grouped.load_window(window_id, cohort)
    _require(checked.path == source_path and checked.document == window,
             "published follow-on window did not replay")
    return source_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window-id", required=True)
    parser.add_argument("--cohort", choices=("flash", "resident"), required=True)
    parser.add_argument("--parent-pair", default=PARENT_ID)
    parser.add_argument("--context-bands", default="",
                        help="ordered prefix: empty, 2048, 2048,8192, or 2048,8192,16384")
    args = parser.parse_args(argv)
    _require(args.parent_pair == PARENT_ID,
             "only the immutable qualified first pair is available")
    bands = tuple(int(item) for item in args.context_bands.split(",") if item)
    source = prepare(args.window_id, cohort=args.cohort, context_bands=bands)
    print(source)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
