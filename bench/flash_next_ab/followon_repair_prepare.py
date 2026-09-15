"""Freeze one fresh selected-repair pair after a distinct v5 profile qualifies.

This is a CPU-only source publisher. The existing supervisors later execute
each arm under its own monitoring and exact restoration contract.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from . import followon_context as context
from . import followon_dispatch as grouped
from . import followon_prepare as first
from . import followon_selected_repair as repair
from .followon_profiles import MIA_CTX69632
from .followon_v5_parent import V5Parent, load_parent

STUDY = "selected-profile-repair-v1"


def _routes(parent: V5Parent) -> dict:
    original = first._routes(first._parents(first.PARENT_ID))
    summary = parent.qualification_summary
    original["flash_next_mia"] = {
        "served_model": summary["served_model"],
        "artifact_sha256": summary["model_artifact_sha256"],
        "runtime_sha256": summary["runtime_sha256"],
        "qualification_receipt_sha256": summary["qualification_receipt_sha256"],
        "max_model_len": summary["max_model_len"],
    }
    return original


def prepare(window_id: str, *, cohort: str,
            v5_parent_path: Path) -> Path:
    first._require(grouped.WINDOW_ID.fullmatch(window_id) is not None
                   and cohort in {"flash", "resident"},
                   "selected repair source ID/cohort is invalid")
    parent = load_parent(Path(v5_parent_path))
    root = grouped.RESEARCH_ROOT
    first._require(root.is_dir() and root.resolve() == root
                   and not root.is_symlink(),
                   "registered selected repair research root is unavailable")
    source = grouped._plan_path(window_id, cohort, root)
    output = grouped._output_path(window_id, cohort, root)
    first._require(not source.exists() and not source.is_symlink()
                   and not output.exists() and not output.is_symlink(),
                   "selected repair source/output already exists")
    original = first._parents(first.PARENT_ID)[cohort]
    routes = _routes(parent)
    plan = repair.freeze_plan(
        {key: first._public_route(routes[key])
         for key in ("resident_gemma", "flash_next_mia")},
        candidate_variant_id=parent.spec.spec_id,
    )
    block_id = (
        "followon-" + hashlib.sha256(
            f"{window_id}:{cohort}:selected-repair".encode()
        ).hexdigest()[:12] + "-0-selected_repair"
    )
    block_path = root / "evaluation/followon-block-plans" / f"{block_id}.json"
    first._require(not block_path.exists() and not block_path.is_symlink(),
                   "selected repair block plan already exists")
    ceiling = (grouped.SELECTED_REPAIR_FLASH_CEILING if cohort == "flash"
               else grouped.SELECTED_REPAIR_RESIDENT_CEILING)
    block = {
        "ordinal": 0, "block_id": block_id,
        "kind": "selected_repair", "plan_path": str(block_path),
        "plan_raw_sha256": hashlib.sha256(first._raw(plan)).hexdigest(),
        "endpoint_name": ("flash_next_mia" if cohort == "flash"
                          else "resident_gemma"),
        "seed_block": None, "target_block": None,
        "wall_ceiling_seconds": ceiling,
        "output_relative": f"blocks/00-{block_id}",
    }
    bundle = grouped.frozen_followon_source_bundle()
    original_ref = {"path": str(original.source_path),
                    "sha256": original.source_sha256}
    parent_ref = {"path": str(parent.source_path),
                  "sha256": parent.source_sha256}
    binding_keys = (("flash_next_mia",) if cohort == "flash"
                    else ("resident_gemma", "resident_qwen"))
    window = {
        "schema_version": (grouped.V5_WINDOW_SCHEMA if cohort == "flash"
                           else grouped.WINDOW_SCHEMA),
        "window_id": window_id, "study_id": STUDY,
        "cohort": cohort, "output_dir": str(output),
        "candidate_variant_id": (parent.spec.spec_id if cohort == "flash"
                                 else None),
        "route_bindings": {key: routes[key] for key in binding_keys},
        "blocks": [block], "qualified_parent_window": original_ref,
        "registered_code_root": str(grouped.FOLLOWON_CODE_ROOT),
        "followon_source_bundle": bundle,
        "followon_source_bundle_sha256": grouped._canonical_sha(bundle),
        "deadline_seconds": grouped.OUTER_DEADLINE,
        "restoration_reserve_seconds": grouped.RESTORE_RESERVE,
        "block_budget_total_seconds": ceiling,
        "promotion_authorized": False,
    }
    if cohort == "flash":
        window["v5_qualified_parent"] = parent_ref
    first._require(grouped._shape(STUDY, cohort, [block]),
                   "selected repair block form changed")
    first._require(first._new_json(block_path, plan)
                   == block["plan_raw_sha256"],
                   "published selected repair block bytes differ")
    first._new_json(source, window)
    checked = grouped.load_window(window_id, cohort)
    first._require(checked.path == source and checked.document == window,
                   "selected repair window did not replay after publication")
    return source


def prepare_native_context(window_id: str, *,
                           v5_parent_path: Path) -> Path:
    """Freeze 12 public packets each at 32K and 65,536 input tokens."""
    first._require(grouped.WINDOW_ID.fullmatch(window_id) is not None,
                   "native context source ID is invalid")
    parent = load_parent(Path(v5_parent_path))
    first._require(parent.spec is MIA_CTX69632
                   and parent.qualification_summary["max_model_len"] == 69632,
                   "context stress requires the separately passed native profile")
    root = grouped.RESEARCH_ROOT
    first._require(root.is_dir() and not root.is_symlink()
                   and root.resolve() == root,
                   "registered native context root is unavailable")
    source = grouped._plan_path(window_id, "flash", root)
    output = grouped._output_path(window_id, "flash", root)
    first._require(not source.exists() and not source.is_symlink()
                   and not output.exists() and not output.is_symlink(),
                   "native context source/output already exists")
    original = first._parents(first.PARENT_ID)["flash"]
    routes = _routes(parent)
    plan = context.freeze_plan("flash_next_mia", routes["flash_next_mia"])
    tokenized = context._retokenize(plan, context.validate_plan(plan))
    for band in (32768, 65536):
        selected = [row for row in plan["declared_cells"]
                    if row["target_input_tokens"] == band]
        by_id = {row.cell_id: row for row in tokenized}
        first._require(len(selected) == 12
                       and all(by_id[row["cell_id"]].supported
                               for row in selected),
                       "native context band has unsupported frozen packets")
    namespace = hashlib.sha256(f"{window_id}:native-context".encode()
                                ).hexdigest()[:12]
    blocks = []
    planned = []
    for ordinal, band in enumerate((32768, 65536)):
        block_id = f"followon-{namespace}-{ordinal}-context"
        block_path = (root / "evaluation/followon-block-plans" /
                      f"{block_id}.json")
        first._require(not block_path.exists() and not block_path.is_symlink(),
                       "native context block source already exists")
        planned.append(block_path)
        blocks.append({
            "ordinal": ordinal, "block_id": block_id,
            "kind": "context", "plan_path": str(block_path),
            "plan_raw_sha256": hashlib.sha256(first._raw(plan)).hexdigest(),
            "endpoint_name": "flash_next_mia", "seed_block": None,
            "target_block": band,
            "wall_ceiling_seconds": grouped.CONTEXT_CEILINGS[band],
            "output_relative": f"blocks/{ordinal:02d}-{block_id}",
        })
    bundle = grouped.frozen_followon_source_bundle()
    window = {
        "schema_version": grouped.V5_WINDOW_SCHEMA,
        "window_id": window_id,
        "study_id": "selected-native-context-stress-v1",
        "cohort": "flash", "output_dir": str(output),
        "candidate_variant_id": parent.spec.spec_id,
        "route_bindings": {"flash_next_mia": routes["flash_next_mia"]},
        "blocks": blocks,
        "qualified_parent_window": {
            "path": str(original.source_path),
            "sha256": original.source_sha256,
        },
        "v5_qualified_parent": {
            "path": str(parent.source_path),
            "sha256": parent.source_sha256,
        },
        "registered_code_root": str(grouped.FOLLOWON_CODE_ROOT),
        "followon_source_bundle": bundle,
        "followon_source_bundle_sha256": grouped._canonical_sha(bundle),
        "deadline_seconds": grouped.OUTER_DEADLINE,
        "restoration_reserve_seconds": grouped.RESTORE_RESERVE,
        "block_budget_total_seconds": sum(
            block["wall_ceiling_seconds"] for block in blocks
        ),
        "promotion_authorized": False,
    }
    first._require(grouped._shape(window["study_id"], "flash", blocks),
                   "native stress source differs from registered 32K/64K order")
    for path in planned:
        first._require(first._new_json(path, plan)
                       == blocks[planned.index(path)]["plan_raw_sha256"],
                       "native context block raw bytes differ")
    first._new_json(source, window)
    checked = grouped.load_window(window_id, "flash")
    first._require(checked.path == source and checked.document == window,
                   "native context stress source did not replay")
    return source


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window-id", required=True)
    parser.add_argument("--cohort", required=True, choices=("flash", "resident"))
    parser.add_argument("--v5-parent", required=True, type=Path)
    parser.add_argument("--kind", choices=("selected_repair", "native_context"),
                        default="selected_repair")
    args = parser.parse_args(argv)
    if args.kind == "native_context":
        first._require(args.cohort == "flash",
                       "native context can only use qualified Flash")
        source = prepare_native_context(
            args.window_id, v5_parent_path=args.v5_parent
        )
    else:
        source = prepare(
            args.window_id, cohort=args.cohort,
            v5_parent_path=args.v5_parent,
        )
    print(source)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
