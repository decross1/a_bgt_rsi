"""Serial registered diagnostics inside one supervised model window.

The existing Flash/resident controller starts, monitors and restores services.
This module only validates closed block declarations and calls two code-owned
runners after that controller has established its current admission callbacks.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import math
import os
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bench.flash_next_ab.evaluation_window import (
    REGISTERED_CODE_ROOT,
    SOURCE_BUNDLE_MODULES,
)
from bench.flash_next_ab.harness import _read_regular_file, _strict_object

RESEARCH_ROOT = Path(
    "/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-14/"
    "qwen-flash-next-research"
)
FOLLOWON_CODE_ROOT = Path(
    "/home/decross1/projects/a_bgt_rsi_worktrees/flash-coding-temp1-20260915"
)
# Keep frozen_controller_source_bundle() and its original registered root
# untouched. Follow-on plans bind these files in a different code checkout.
FOLLOWON_SOURCE_MODULES = tuple(SOURCE_BUNDLE_MODULES) + (
    "followon_dispatch.py", "followon_selection.py",
    "followon_prepare.py",
    "followon_plans.py", "followon_admission.py",
    "followon_completed_window_admission.py",
    "followon_thinking.py", "followon_context.py",
    "followon_context_packs.py", "followon_market_canaries.py",
    "followon_profiles.py", "followon_canaries.py",
    "followon_native_packet.py", "mtp0_controls.py",
    "followon_timing.py", "mtp_decode_diagnostic.py",
    "MTP_DECODE_TIMING_PROTOCOL.json",
    "followon_qualification_admission.py", "MTP_PARITY_PROTOCOL.json",
    "followon_v5_parent.py", "reduced_profile_literal.py",
    "followon_selected_repair.py",
    "followon_repair_prepare.py",
    "followon_coding_temp1.py", "CODING_TEMP1_PROTOCOL.json",
    "historical_v5_parent_bridge.py",
)
WINDOW_SCHEMA = "flash-followon-window/v1"
V5_WINDOW_SCHEMA = "flash-followon-window/v2"
ATTEMPT_SCHEMA = "flash-followon-group-attempt/v1"
WINDOW_ID = re.compile(r"qfn-followon-[a-z0-9][a-z0-9._-]{0,63}\Z")
BLOCK_ID = re.compile(r"followon-[a-z0-9][a-z0-9._-]{0,63}\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
WINDOW_KEYS = frozenset({
    "schema_version", "window_id", "study_id", "cohort", "output_dir",
    "candidate_variant_id", "route_bindings", "blocks",
    "qualified_parent_window",
    "registered_code_root", "followon_source_bundle",
    "followon_source_bundle_sha256",
    "deadline_seconds", "restoration_reserve_seconds",
    "block_budget_total_seconds", "promotion_authorized",
})
V5_WINDOW_KEYS = WINDOW_KEYS | {"v5_qualified_parent"}
BLOCK_KEYS = frozenset({
    "ordinal", "block_id", "kind", "plan_path", "plan_raw_sha256",
    "endpoint_name", "seed_block", "target_block", "wall_ceiling_seconds",
    "output_relative",
})
ROUTE_KEYS = frozenset({
    "served_model", "artifact_sha256", "runtime_sha256",
    "qualification_receipt_sha256", "max_model_len",
})
RUNNER_MODULES = {
    "thinking": "bench.flash_next_ab.followon_thinking",
    "context": "bench.flash_next_ab.followon_context",
    "market_canaries": "bench.flash_next_ab.followon_market_canaries",
    "mtp0_controls": "bench.flash_next_ab.mtp0_controls",
    "mtp_decode_timing": "bench.flash_next_ab.mtp_decode_diagnostic",
    "selected_repair": "bench.flash_next_ab.followon_selected_repair",
    "coding_temp1_medium": "bench.flash_next_ab.followon_coding_temp1",
}
THINKING_CEILING = 2700
MARKET_CEILING = 2220
MTP0_CEILING = 720
MTP_DECODE_CEILING = 360
SELECTED_REPAIR_FLASH_CEILING = 4500
SELECTED_REPAIR_RESIDENT_CEILING = 2500
CODING_TEMP1_CEILING = 1560
CONTEXT_CEILINGS = {
    2048: 1440, 8192: 2160, 16384: 2880,
    32768: 4320, 65536: 5760,
}
OUTER_DEADLINE = 4_200
RESTORE_RESERVE = 600


class FollowonError(ValueError):
    pass


@dataclass(frozen=True)
class FrozenWindow:
    path: Path
    raw_sha256: str
    document: dict[str, Any]
    block_plans: tuple[dict[str, Any], ...]


def _require(valid: bool, reason: str) -> None:
    if not valid:
        raise FollowonError(reason)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_sha(value: Any) -> str:
    return _sha(json.dumps(value, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, allow_nan=False).encode())


def frozen_followon_source_bundle(*, code_root: Path | None = None) -> dict:
    """Bind only the separate follow-on checkout; never rederive old pair bytes."""
    code_root = (code_root or FOLLOWON_CODE_ROOT).absolute()
    _require(code_root.is_dir() and not code_root.is_symlink()
             and code_root.resolve() == code_root
             and code_root != REGISTERED_CODE_ROOT,
             "registered follow-on code root is unavailable")
    module_root = code_root / "bench/flash_next_ab"
    observed = {}
    for name in FOLLOWON_SOURCE_MODULES:
        source = module_root / name
        raw, actual = _read_regular_file(
            source, label="registered follow-on code", max_bytes=2_000_000,
        )
        _require(actual == source.absolute(),
                 "follow-on code source changed path")
        observed[name] = {"path": str(source), "sha256": _sha(raw),
                          "bytes": len(raw)}
    return observed


def _read(path: Path, maximum: int = 8 * 1024 * 1024) -> tuple[dict, str]:
    raw, actual = _read_regular_file(path, label="frozen follow-on source",
                                     max_bytes=maximum)
    _require(actual == path.absolute(), "follow-on source changed path")
    try:
        value = _strict_object(raw, "frozen follow-on source")
    except (UnicodeError, ValueError) as exc:
        raise FollowonError("follow-on source is malformed") from exc
    _require(isinstance(value, dict), "follow-on source is not an object")
    return value, _sha(raw)


def _plan_path(window_id: str, cohort: str, root: Path) -> Path:
    return root / "evaluation/followon-window-plans" / f"{window_id}.{cohort}.json"


def _output_path(window_id: str, cohort: str, root: Path) -> Path:
    return root / "evaluation/followon-runs" / f"{window_id}.{cohort}"


def _shape(study_id: str, cohort: str, blocks: list[dict]) -> bool:
    described = [(b["kind"], b["endpoint_name"], b["seed_block"],
                  b["target_block"]) for b in blocks]
    if study_id == "selected-profile-repair-v1" and len(described) == 1:
        endpoint = "flash_next_mia" if cohort == "flash" else "resident_gemma"
        return described == [("selected_repair", endpoint, None, None)]
    if study_id == "selected-native-context-stress-v1" and cohort == "flash":
        return described == [
            ("context", "flash_next_mia", None, 32768),
            ("context", "flash_next_mia", None, 65536),
        ]
    if study_id == "selected-profile-quality-v1" and cohort == "flash":
        required = [
            ("thinking", "flash_next_mia", 71, None),
            ("market_canaries", "flash_next_mia", 107, None),
            ("mtp_decode_timing", "flash_next_mia", 17, None),
        ]
        optional = [("context", "flash_next_mia", None, band)
                    for band in (2048, 8192, 16384)]
        return any(described == required + optional[:count]
                   for count in range(len(optional) + 1))
    if study_id == "coding-temp1-medium-and-decode-v1" and cohort == "flash":
        return described == [
            ("coding_temp1_medium", "flash_next_mia", None, None),
            ("mtp_decode_timing", "flash_next_mia", 17, None),
        ]
    if study_id == "thinking-market-diagnostics-v1":
        if cohort == "flash":
            required = [
                ("thinking", "flash_next_mia", 71, None),
                ("market_canaries", "flash_next_mia", 107, None),
                ("mtp0_controls", "flash_next_mia", 17, None),
                ("mtp_decode_timing", "flash_next_mia", 17, None),
            ]
            optional = [
                ("context", "flash_next_mia", None, band)
                for band in (2048, 8192, 16384)
            ]
        else:
            required = [
                ("thinking", "resident_qwen", 71, None),
                ("market_canaries", "resident_qwen", 107, None),
            ]
            optional = [
                ("context", "resident_qwen", None, 2048),
                ("context", "resident_qwen", None, 8192),
                ("context", "resident_gemma", None, 16384),
            ]
        return any(described == required + optional[:count]
                   for count in range(len(optional) + 1))
    if study_id == "thinking-context-pilot-v1":
        optional_market = (
            len(described) == 5
            and described[-1][0] == "market_canaries"
            and described[-1][2] in {107, 509}
            and described[-1][3] is None
            and described[-1][1]
                == (blocks[0]["endpoint_name"] if cohort == "flash"
                    else "resident_qwen")
        )
        if optional_market:
            if cohort == "flash" and blocks[0]["endpoint_name"] != "flash_next_mia":
                return False
            described = described[:-1]
        if cohort == "flash":
            endpoint = blocks[0]["endpoint_name"]
            return described == [
                ("thinking", endpoint, 71, None),
                ("context", endpoint, None, 2048),
                ("context", endpoint, None, 8192),
                ("context", endpoint, None, 16384),
            ] and endpoint in {"flash_next_mia", "flash_next"}
        return described == [
            ("thinking", "resident_qwen", 71, None),
            ("context", "resident_qwen", None, 2048),
            ("context", "resident_qwen", None, 8192),
            ("context", "resident_gemma", None, 16384),
        ]
    if study_id == "thinking-repeat-v1":
        endpoint = (blocks[0]["endpoint_name"] if cohort == "flash"
                    else "resident_qwen")
        return described == [
            ("thinking", endpoint, seed, None) for seed in (173, 271, 419)
        ] and (cohort != "flash" or endpoint in {"flash_next_mia", "flash_next"})
    if study_id == "market-canary-only-v1" and len(described) == 1:
        return described[0] in {
            ("market_canaries", "flash_next_mia", 107, None),
            ("market_canaries", "flash_next_mia", 509, None),
            ("market_canaries", "resident_qwen", 107, None),
            ("market_canaries", "resident_qwen", 509, None),
        } and (cohort == "flash") == (described[0][1] == "flash_next_mia")
    if study_id == "mtp0-control-panel-v1" and len(described) == 1:
        return (cohort == "flash"
                and described[0]
                   == ("mtp0_controls", "flash_next_mia", 17, None))
    if study_id == "mtp0-control-and-decode-v1" and len(described) == 2:
        return (cohort == "flash" and described == [
            ("mtp0_controls", "flash_next_mia", 17, None),
            ("mtp_decode_timing", "flash_next_mia", 17, None),
        ])
    return False


def load_window(window_id: str, cohort: str, *, root: Path = RESEARCH_ROOT) -> FrozenWindow:
    """Read everything before mutation; repeat before each declared block."""
    _require(WINDOW_ID.fullmatch(window_id) is not None
             and cohort in {"flash", "resident"}, "follow-on window ID is invalid")
    root = root.absolute()
    _require(root.is_dir() and not root.is_symlink() and root.resolve() == root,
             "registered research root is unavailable")
    path = _plan_path(window_id, cohort, root)
    value, digest = _read(path, maximum=1_000_000)
    v5_window = value.get("schema_version") == V5_WINDOW_SCHEMA
    blocks = value.get("blocks")
    _require(isinstance(blocks, list) and 1 <= len(blocks) <= 7
             and all(isinstance(block, dict) for block in blocks),
             "follow-on block list is absent")
    _require(set(value) == (V5_WINDOW_KEYS if v5_window else WINDOW_KEYS)
             and value["schema_version"]
                 == (V5_WINDOW_SCHEMA if v5_window else WINDOW_SCHEMA)
             and value["window_id"] == window_id
             and value["cohort"] == cohort
             and value["output_dir"] == str(_output_path(window_id, cohort, root))
             and value["deadline_seconds"] == OUTER_DEADLINE
             and value["restoration_reserve_seconds"] == RESTORE_RESERVE
             and value["promotion_authorized"] is False,
             "follow-on window identity or safety ceiling differs")
    _require(value["registered_code_root"] == str(FOLLOWON_CODE_ROOT)
             and value["followon_source_bundle"]
                 == frozen_followon_source_bundle()
             and value["followon_source_bundle_sha256"]
                 == _canonical_sha(value["followon_source_bundle"]),
             "follow-on source root or bytes changed")
    parent = value["qualified_parent_window"]
    _require(isinstance(parent, dict)
             and set(parent) == {"path", "sha256"}
             and isinstance(parent["sha256"], str)
             and SHA.fullmatch(parent["sha256"]) is not None
             and isinstance(parent["path"], str),
             "qualified parent source binding is absent")
    parent_source = Path(parent["path"])
    _require(parent_source.parent == root / "evaluation/window-plans"
             and parent_source.name.endswith(f".{cohort}.window.json"),
             "qualified parent is outside the original window namespace")
    parent_doc, parent_sha = _read(parent_source, maximum=1_000_000)
    _require(parent_sha == parent["sha256"]
             and parent_doc.get("schema_version")
                 == "flash-next-evaluation-window/v1"
             and parent_doc.get("cohort") == cohort
             and parent_doc.get("promotion_authorized") is False,
             "qualified original parent changed")
    v5_parent = None
    if v5_window:
        from .followon_v5_parent import ROOT as V5_PARENT_ROOT
        from .followon_v5_parent import load_parent

        reference = value["v5_qualified_parent"]
        _require(cohort == "flash" and isinstance(reference, dict)
                 and set(reference) == {"path", "sha256"}
                 and isinstance(reference["path"], str)
                 and Path(reference["path"]).parent == V5_PARENT_ROOT
                 and isinstance(reference["sha256"], str)
                 and SHA.fullmatch(reference["sha256"]) is not None,
                 "v5 parent source reference is unregistered")
        v5_parent = load_parent(Path(reference["path"]))
        _require(v5_parent.source_sha256 == reference["sha256"]
                 and v5_parent.qualification_summary["admission_eligible"] is True,
                 "v5 parent source or qualification admission changed")
        if value["study_id"] == "selected-native-context-stress-v1":
            from .followon_profiles import MIA_CTX69632

            _require(v5_parent.spec is MIA_CTX69632
                     and v5_parent.spec.max_model_len == 69632,
                     "native 32K/64K packets require their own passed 69K profile")
    bindings = value["route_bindings"]
    expected_routes = (
        {"resident_qwen", "resident_gemma"} if cohort == "resident"
        else {blocks[0].get("endpoint_name")}
    )
    _require(isinstance(bindings, dict) and set(bindings) == expected_routes
             and all(isinstance(row, dict) and set(row) == ROUTE_KEYS
                     and all(isinstance(row[key], str)
                             and SHA.fullmatch(row[key]) is not None
                             for key in ("artifact_sha256", "runtime_sha256",
                                         "qualification_receipt_sha256"))
                     and isinstance(row["served_model"], str)
                     and type(row["max_model_len"]) is int
                     and row["max_model_len"] > 0
                     for row in bindings.values()),
             "follow-on route bindings are incomplete")
    if cohort == "flash":
        if v5_window:
            route = bindings.get(v5_parent.spec.endpoint_name)
            summary = v5_parent.qualification_summary
            _require(value["candidate_variant_id"] == v5_parent.spec.spec_id
                     and set(bindings) == {v5_parent.spec.endpoint_name}
                     and route is not None
                     and route["served_model"] == summary["served_model"]
                     and route["artifact_sha256"]
                         == summary["model_artifact_sha256"]
                     and route["runtime_sha256"] == summary["runtime_sha256"]
                     and route["qualification_receipt_sha256"]
                         == summary["qualification_receipt_sha256"]
                     and route["max_model_len"] == summary["max_model_len"],
                     "v5 Flash route differs from its own passed qualification")
        else:
            _require(value["candidate_variant_id"]
                     == ("mia-925d7be6-c0-s1" if "flash_next_mia" in bindings
                         else "nvidia-nvfp4-fc694b54"),
                     "one Flash window must bind one qualified variant")
    else:
        _require(value["candidate_variant_id"] is None,
                 "resident follow-on must not register a Flash candidate")
    ids = set()
    plans = []
    total = 0
    for ordinal, block in enumerate(blocks):
        _require(set(block) == BLOCK_KEYS
                 and type(block["ordinal"]) is int
                 and block["ordinal"] == ordinal
                 and isinstance(block["block_id"], str)
                 and BLOCK_ID.fullmatch(block["block_id"]) is not None
                 and block["block_id"] not in ids
                 and block["kind"] in RUNNER_MODULES
                 and block["endpoint_name"] in bindings
                 and isinstance(block["plan_raw_sha256"], str)
                 and SHA.fullmatch(block["plan_raw_sha256"]) is not None
                 and block["output_relative"]
                    == f"blocks/{ordinal:02d}-{block['block_id']}",
                 "follow-on block identity/order is invalid")
        ids.add(block["block_id"])
        expected_source = root / "evaluation/followon-block-plans" / (
            block["block_id"] + ".json"
        )
        _require(block["plan_path"] == str(expected_source),
                 "follow-on block plan path differs")
        plan, source_sha = _read(expected_source)
        _require(source_sha == block["plan_raw_sha256"],
                 "frozen follow-on block bytes changed")
        route = bindings[block["endpoint_name"]]
        if block["kind"] == "thinking":
            selected = plan.get("routes", {}).get(block["endpoint_name"])
            _require(isinstance(selected, dict)
                     and selected == {key: route[key] for key in ROUTE_KEYS
                                     if key != "max_model_len"},
                     "thinking block route differs from qualified window")
        elif block["kind"] in {"mtp0_controls", "mtp_decode_timing"}:
            _require(cohort == "flash"
                     and (block["kind"] != "mtp0_controls" or not v5_window)
                     and (v5_window or value["candidate_variant_id"]
                          == "mia-925d7be6-c0-s1")
                     and (block["kind"] != "mtp_decode_timing"
                          or plan.get("spec_id") == value["candidate_variant_id"])
                     and plan.get("route")
                        == {key: route[key] for key in ROUTE_KEYS
                            if key != "max_model_len"},
                     "MTP diagnostic requires its exact passed profile route")
        elif block["kind"] == "market_canaries":
            selected = plan.get("routes", {}).get(block["endpoint_name"])
            _require(isinstance(selected, dict)
                     and selected == {key: route[key] for key in ROUTE_KEYS
                                     if key != "max_model_len"},
                     "market canary route differs from qualified window")
        elif block["kind"] == "selected_repair":
            selected = plan.get("routes", {}).get(block["endpoint_name"])
            _require(isinstance(selected, dict)
                     and selected == {key: route[key] for key in ROUTE_KEYS
                                     if key != "max_model_len"}
                     and (cohort != "flash"
                          or plan.get("candidate_variant_id")
                             == value["candidate_variant_id"]),
                     "selected repair route differs from the admitted model")
        elif block["kind"] == "coding_temp1_medium":
            _require(cohort == "flash" and v5_window
                     and plan.get("route")
                        == {key: route[key] for key in ROUTE_KEYS
                            if key != "max_model_len"}
                     and plan.get("candidate_variant_id")
                        == value["candidate_variant_id"],
                     "registered coding diagnostic route/profile differs")
        else:
            _require(plan.get("route") == route,
                     "context block route differs from qualified window")
        # The code-owned runner rederives its fixed tasks/packets, source-file
        # hashes and policy caps here, before the controller mutates services.
        runner = importlib.import_module(RUNNER_MODULES[block["kind"]])
        checked_source = runner.validate_plan(plan)
        ceiling = (THINKING_CEILING if block["kind"] == "thinking"
                   else MARKET_CEILING if block["kind"] == "market_canaries"
                   else MTP0_CEILING if block["kind"] == "mtp0_controls"
                   else MTP_DECODE_CEILING if block["kind"] == "mtp_decode_timing"
                   else CODING_TEMP1_CEILING
                   if block["kind"] == "coding_temp1_medium"
                   else (SELECTED_REPAIR_FLASH_CEILING if cohort == "flash"
                         else SELECTED_REPAIR_RESIDENT_CEILING)
                   if block["kind"] == "selected_repair"
                   else CONTEXT_CEILINGS.get(block["target_block"]))
        _require(type(ceiling) is int and block["wall_ceiling_seconds"] == ceiling
                 and (block["kind"] != "thinking"
                      or (block["target_block"] is None
                          and type(block["seed_block"]) is int))
                 and (block["kind"] != "context"
                      or block["seed_block"] is None)
                 and (block["kind"] != "market_canaries"
                      or (block["target_block"] is None
                          and block["seed_block"] in {107, 509}))
                 and (block["kind"] != "mtp0_controls"
                      or (block["target_block"] is None
                          and block["seed_block"] == 17))
                 and (block["kind"] != "mtp_decode_timing"
                      or (block["target_block"] is None
                          and block["seed_block"] == 17
                          and plan.get("spec_id") == value["candidate_variant_id"]))
                 and (block["kind"] != "selected_repair"
                     or block["target_block"] is None
                         and block["seed_block"] is None)
                 and (block["kind"] != "coding_temp1_medium"
                     or block["target_block"] is None
                        and block["seed_block"] is None),
                 "follow-on block ceiling or seed differs")
        if block["kind"] == "context":
            required = {
                2048: 8192, 8192: 16384, 16384: 32768,
                32768: 34816, 65536: 67629,
            }[
                block["target_block"]
            ]
            _require(bindings[block["endpoint_name"]]["max_model_len"] >= required,
                     "context band has no qualified server capacity")
            selected = [cell for cell in plan.get("declared_cells", [])
                        if isinstance(cell, dict)
                        and cell.get("target_input_tokens")
                            == block["target_block"]]
            tokenized = runner._retokenize(plan, checked_source)
            by_id = {row.cell_id: row for row in tokenized}
            _require(len(selected) == 12
                     and all(cell["cell_id"] in by_id
                             and by_id[cell["cell_id"]].supported
                             for cell in selected),
                     "context block has fewer than twelve supported packets")
        _require(plan.get("endpoint_name", block["endpoint_name"])
                 == block["endpoint_name"],
                 "block endpoint differs from frozen plan")
        plans.append(plan)
        total += ceiling
    _require(_shape(value["study_id"], cohort, blocks),
             "window is outside preregistered pilot/repeat forms")
    _require(not v5_window or value["study_id"] in {
        "selected-profile-quality-v1", "selected-profile-repair-v1",
        "selected-native-context-stress-v1",
        "coding-temp1-medium-and-decode-v1",
    },
             "v5 window has no separate selected-profile study form")
    _require(value["block_budget_total_seconds"] == total
             and total <= OUTER_DEADLINE - RESTORE_RESERVE,
             "group wall ceiling does not leave restoration reserve")
    return FrozenWindow(path, digest, value, tuple(plans))


def _write_json(path: Path, value: dict) -> None:
    raw = (json.dumps(value, sort_keys=True, allow_nan=False) + "\n").encode()
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temporary.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)


def _thinking_block_complete(result: dict, plan: dict, endpoint: str,
                             seed_block: int) -> bool:
    from bench.flash_next_ab import followon_thinking as runner
    from bench.flash_next_ab.followon_timing import validate_timings
    from bench.flash_next_ab.manifest import sha256_json
    from bench.weekly_upgrade_effort import manifest as effort_manifest
    from bench.weekly_upgrade_effort import runner as effort_runner

    source = effort_manifest.load_manifest(runner.SOURCE_MANIFEST)
    tasks = {task["id"]: task for task in source["tasks"]}

    def bound(declared: dict, row: dict, route: dict) -> bool:
        calls = row.get("calls")
        task = tasks.get(declared.get("task_id"))
        if not isinstance(calls, list) or not 1 <= len(calls) <= 2 or task is None:
            return False
        adaptive = declared["condition"] == "adaptive"
        bounded_first = adaptive and declared["role"] != "critic"
        first = ("xhigh" if adaptive and declared["role"] == "critic"
                 else "medium" if adaptive else declared["condition"])
        if len(calls) == 2 and not bounded_first:
            return False
        for index, call in enumerate(calls):
            if not isinstance(call, dict):
                return False
            if index == 0:
                condition, seed = first, declared["seed"]
                cap = runner.TOTAL_TOKENS // 2 if bounded_first else runner.TOTAL_TOKENS
                timeout_ceiling = runner.CELL_TIMEOUT_S / 2 if bounded_first else runner.CELL_TIMEOUT_S
            else:
                first_usage = calls[0].get("usage")
                used = first_usage.get("completion_tokens") if isinstance(first_usage, dict) else None
                if (calls[0].get("status") != "returned" or type(used) is not int
                        or not 0 <= used <= runner.TOTAL_TOKENS // 2):
                    return False
                condition, seed = "xhigh", declared["seed"] + 1
                cap = runner.TOTAL_TOKENS - used
                timeout_ceiling = runner.CELL_TIMEOUT_S
            messages = effort_runner.messages(task, retry=index == 1)
            if not (call.get("call_index") == index
                    and call.get("call_id") == f"{declared['cell_id']}#{index}"
                    and call.get("role") == declared["role"]
                    and call.get("endpoint_name") == endpoint
                    and call.get("served_model") == route["served_model"]
                    and call.get("artifact_sha256") == route["artifact_sha256"]
                    and call.get("policy_id") == condition
                    and call.get("resolved_policy_sha256")
                        == sha256_json(plan["policies"][condition])
                    and call.get("messages_sha256") == sha256_json(messages)
                    and call.get("tools_sha256") == sha256_json([])
                    and call.get("seed") == seed
                    and call.get("max_tokens") == cap
                    and type(call.get("timeout_s")) in {int, float}
                    and math.isfinite(call["timeout_s"])
                    and 0 < call["timeout_s"] <= timeout_ceiling
                    and call.get("status") in {"returned", "timeout", "error"}
                    and (call.get("response_model") == route["served_model"]
                         if call.get("status") == "returned" else True)):
                return False
        try:
            validate_timings(calls, row.get("transport_timings"))
        except (TypeError, ValueError):
            return False
        return row.get("escalated") is (len(calls) == 2)

    expected = [row for row in plan.get("declared_cells", [])
                if isinstance(row, dict) and row.get("seed") == seed_block]
    outcomes = result.get("outcomes")
    route = plan.get("routes", {}).get(endpoint)
    return bool(
        result.get("schema_version") == "flash-thinking-role-effort-run/v1"
        and result.get("status") == "complete"
        and result.get("endpoint_name") == endpoint
        and result.get("seed_block") == seed_block
        and result.get("plan") == plan
        and result.get("plan_sha256") == plan.get("plan_sha256")
        and isinstance(route, dict)
        and result.get("qualification_receipt_sha256")
            == route.get("qualification_receipt_sha256")
        and result.get("declared_cells") == 30
        and len(expected) == 30
        and isinstance(outcomes, list)
        and len(outcomes) == 30
        and [row.get("cell_id") for row in outcomes if isinstance(row, dict)]
            == [row["cell_id"] for row in expected]
        and all(isinstance(row, dict)
                and row.get("status") in {"returned", "timeout", "error"}
                and row.get("execution_error_type") is None
                and row.get("returned_usage_valid") is True
                and isinstance(row.get("calls"), list) and row["calls"]
                and isinstance(row.get("private_call_evidence"), list)
                and len(row["calls"]) == len(row["private_call_evidence"])
                and all(row.get(key) == declared.get(key) for key in (
                    "task_id", "role", "condition", "seed", "input_sha256",
                    "grader_sha256",
                ))
                and row.get("endpoint_name") == endpoint
                and row.get("served_model") == route.get("served_model")
                and row.get("artifact_sha256") == route.get("artifact_sha256")
                and row.get("runtime_sha256") == route.get("runtime_sha256")
                and bound(declared, row, route)
                for declared, row in zip(expected, outcomes, strict=True))
        and result.get("promotion_authorized") is False
    )


def _market_block_complete(result: dict, plan: dict, endpoint: str,
                           seed_block: int) -> bool:
    from bench.flash_next_ab import followon_market_canaries as runner
    from bench.flash_next_ab.followon_timing import validate_timings
    from bench.flash_next_ab.manifest import sha256_json

    source, _ = runner._source()
    tasks = {task["task_id"]: task for task in source["tasks"]}

    def bound(declared: dict, row: dict, route: dict) -> bool:
        task = tasks.get(declared.get("task_id"))
        calls = row.get("calls")
        if task is None or not isinstance(calls, list) or len(calls) != 1:
            return False
        call = calls[0]
        if not isinstance(call, dict):
            return False
        expected_messages = [{"role": "user", "content": task["prompt"]}]
        if not (all(row.get(key) == declared.get(key) for key in
                    ("cell_id", "task_id", "role", "condition", "seed"))
                and call.get("call_index") == 0
                and call.get("call_id") == f"{declared['cell_id']}#0"
                and call.get("role") == declared["role"]
                and call.get("endpoint_name") == endpoint
                and call.get("served_model") == route["served_model"]
                and call.get("artifact_sha256") == route["artifact_sha256"]
                and call.get("policy_id") == declared["condition"]
                and call.get("resolved_policy_sha256")
                    == sha256_json(plan["policies"][declared["condition"]])
                and call.get("messages_sha256") == sha256_json(expected_messages)
                and call.get("tools_sha256") == sha256_json([])
                and call.get("seed") == declared["seed"]
                and call.get("max_tokens") == plan["max_tokens"]
                and type(call.get("timeout_s")) in {int, float}
                and math.isfinite(call["timeout_s"])
                and 0 < call["timeout_s"] <= plan["cell_timeout_s"]
                and call.get("status") == row.get("status")
                and (call.get("response_model") == route["served_model"]
                     if call.get("status") == "returned" else True)):
            return False
        try:
            validate_timings(calls, row.get("transport_timings"))
        except (TypeError, ValueError):
            return False
        return True

    expected = [cell for cell in plan.get("declared_cells", [])
                if isinstance(cell, dict) and cell.get("seed") == seed_block]
    outcomes = result.get("outcomes")
    route = plan.get("routes", {}).get(endpoint)
    return bool(
        result.get("schema_version") == "flash-fresh-market-canary-run/v1"
        and result.get("status") == "complete"
        and result.get("endpoint_name") == endpoint
        and result.get("seed_block") == seed_block
        and result.get("source") == plan.get("source")
        and result.get("route") == route
        and result.get("plan") == plan
        and result.get("plan_sha256") == plan.get("plan_sha256")
        and result.get("declared_cells") == 24
        and len(expected) == 24 and isinstance(outcomes, list)
        and len(outcomes) == 24
        and [row.get("cell_id") for row in outcomes if isinstance(row, dict)]
            == [row["cell_id"] for row in expected]
        and all(isinstance(row, dict)
                and row.get("status") in {"returned", "timeout", "error"}
                and isinstance(row.get("calls"), list) and len(row["calls"]) == 1
                and isinstance(row.get("private_call_evidence"), list)
                and len(row["private_call_evidence"]) == 1
                and row.get("grade", {}).get("details", {}).get(
                    "_private_call_evidence", {}).get("artifacts")
                    == row["private_call_evidence"]
                and bound(declared, row, route)
                for declared, row in zip(expected, outcomes, strict=True))
        and result.get("comparison_eligible") is False
        and result.get("promotion_authorized") is False
    )


def _mtp0_block_complete(result: dict, plan: dict, endpoint: str) -> bool:
    from bench.flash_next_ab import mtp0_controls

    try:
        mtp0_controls.validate_run(result, plan)
    except (TypeError, ValueError):
        return False
    outcomes = result.get("outcomes")
    return bool(
        endpoint == "flash_next_mia"
        and isinstance(outcomes, list) and len(outcomes) == 12
        and result.get("summary", {}).get("attempted") == 12
        and all(isinstance(row, dict)
                and row.get("status") in {"returned", "timeout", "error"}
                and isinstance(row.get("calls"), list)
                and len(row["calls"]) == 1
                and isinstance(row.get("private_call_evidence"), list)
                and len(row["private_call_evidence"]) == 1
                for row in outcomes)
        and result.get("comparison_eligible") is False
        and result.get("promotion_authorized") is False
    )


def _mtp_decode_block_complete(result: dict, plan: dict,
                               endpoint: str) -> bool:
    from bench.flash_next_ab import mtp_decode_diagnostic as runner

    try:
        runner.validate_run(result, plan)
    except (TypeError, ValueError):
        return False
    outcomes = result.get("outcomes")
    return bool(
        endpoint == "flash_next_mia"
        and result.get("status") == "block_complete"
        and result.get("summary", {}).get("attempted") == 3
        and isinstance(outcomes, list) and len(outcomes) == 3
        and all(isinstance(row, dict)
                and row.get("status") in {"returned", "timeout", "error"}
                and isinstance(row.get("calls"), list) and len(row["calls"]) == 1
                and isinstance(row.get("private_call_evidence"), list)
                and len(row["private_call_evidence"]) == 1
                for row in outcomes)
        and result.get("comparison_eligible") is False
        and result.get("promotion_authorized") is False
    )


def run_group(frozen: FrozenWindow, *, controller_callbacks: Any,
              work_cutoff_s: float, cancel_event: Any) -> dict:
    """Call only the two code-owned runners, serially and under one cutoff."""
    document = frozen.document
    output = Path(document["output_dir"])
    _require(output.is_dir() and not output.is_symlink()
             and output.resolve() == output,
             "supervisor has not registered a direct-child output")
    _require(type(work_cutoff_s) in {float, int} and math.isfinite(work_cutoff_s)
             and callable(getattr(cancel_event, "is_set", None)),
             "controller cutoff/cancellation is unavailable")
    required = (
        "admit_thinking", "admit_context", "check_thinking", "check_context",
    )
    _require(all(callable(getattr(controller_callbacks, name, None))
                 for name in required),
             "controller admission or monitor callbacks are unavailable")
    _require(time.monotonic() + document["block_budget_total_seconds"]
             <= work_cutoff_s,
             "whole group no longer fits before exact restoration")
    records = []
    abort_reason = None
    for ordinal, block in enumerate(document["blocks"]):
        if abort_reason is not None:
            records.append({"ordinal": ordinal, "block_id": block["block_id"],
                            "kind": block["kind"], "status": "not_run",
                            "reason_code": abort_reason, "run_sha256": None,
                            "attempted": 0, "passed": None, "timeouts": None})
            continue
        child = None
        try:
            current = load_window(document["window_id"], document["cohort"],
                                  root=frozen.path.parents[2])
            _require(current.raw_sha256 == frozen.raw_sha256
                     and current.document == document
                     and current.block_plans == frozen.block_plans,
                     "group source changed between blocks")
            remaining = sum(item["wall_ceiling_seconds"]
                            for item in document["blocks"][ordinal:])
            _require(time.monotonic() + remaining <= work_cutoff_s,
                     "remaining blocks no longer fit before restoration")
            _require(not cancel_event.is_set(), "controller canceled the group")
            runner = importlib.import_module(RUNNER_MODULES[block["kind"]])
            plan = frozen.block_plans[ordinal]
            child = output / block["output_relative"]
            block_root = output / "blocks"
            _require(not block_root.exists()
                     or (block_root.is_dir() and not block_root.is_symlink()
                         and block_root.resolve() == block_root),
                     "follow-on block output parent is redirected")
            _require(not child.exists() and not child.is_symlink(),
                     "follow-on block output already exists")
            if block["kind"] == "thinking":
                result = runner.run_model(
                    plan, endpoint_name=block["endpoint_name"],
                    seed_block=block["seed_block"], output_dir=child,
                    runtime_budget_s=block["wall_ceiling_seconds"],
                    admission_gate=controller_callbacks.admit_thinking,
                    safety_check=controller_callbacks.check_thinking,
                    work_cutoff_s=work_cutoff_s, cancel_event=cancel_event,
                )
                complete = _thinking_block_complete(
                    result, plan, block["endpoint_name"], block["seed_block"]
                )
            elif block["kind"] in {"market_canaries", "mtp0_controls",
                                    "mtp_decode_timing", "selected_repair",
                                    "coding_temp1_medium"}:
                result = runner.run_model(
                    plan, endpoint_name=block["endpoint_name"],
                    seed_block=block["seed_block"], output_dir=child,
                    runtime_budget_s=block["wall_ceiling_seconds"],
                    admission_gate=controller_callbacks.admit_thinking,
                    safety_check=controller_callbacks.check_thinking,
                    work_cutoff_s=work_cutoff_s, cancel_event=cancel_event,
                )
                complete = (
                    _market_block_complete(
                        result, plan, block["endpoint_name"], block["seed_block"]
                    ) if block["kind"] == "market_canaries"
                    else _mtp0_block_complete(
                        result, plan, block["endpoint_name"]
                    ) if block["kind"] == "mtp0_controls"
                    else result.get("status") == "complete"
                         and result.get("abort_reason") is None
                         and result.get("summary", {}).get("attempted")
                            == (4 if block["kind"] == "coding_temp1_medium"
                                else 44 if block["endpoint_name"] == "flash_next_mia"
                                else 22)
                         and runner.validate_run(
                             result, plan, block["endpoint_name"]
                         ) is None
                    if block["kind"] in {"selected_repair", "coding_temp1_medium"}
                    else _mtp_decode_block_complete(
                        result, plan, block["endpoint_name"]
                    )
                )
            else:
                result = runner.run_model(
                    plan, output_dir=child,
                    runtime_budget_s=block["wall_ceiling_seconds"],
                    admission_gate=controller_callbacks.admit_context,
                    safety_check=controller_callbacks.check_context,
                    work_cutoff_s=work_cutoff_s,
                    target_block=block["target_block"],
                    cancel_event=cancel_event,
                )
                runner.validate_run(result)
                complete = (result.get("schema_version")
                            == "flash-context-placement-run/v1"
                            and result.get("status") == "block_complete"
                            and result.get("summary", {}).get("attempted") == 12)
            raw, actual = _read_regular_file(child / "run.json",
                                             label="finished follow-on block",
                                             max_bytes=8 * 1024 * 1024)
            _require(actual == (child / "run.json").absolute()
                     and _strict_object(raw, "finished follow-on block") == result
                     and result.get("promotion_authorized") is False,
                     "block public result changed path or authority")
            if block["kind"] in {"thinking", "market_canaries",
                                 "selected_repair", "coding_temp1_medium"}:
                outcomes = result.get("outcomes", [])
                attempted = sum(row.get("status") != "not_run" for row in outcomes)
                passed = sum(row.get("passed") is True for row in outcomes)
                timeouts = sum(row.get("status") == "timeout" for row in outcomes)
            elif block["kind"] == "mtp0_controls":
                summary = result.get("summary", {})
                attempted = summary.get("attempted")
                passed = summary.get("passed")
                timeouts = summary.get("timeout")
            elif block["kind"] == "mtp_decode_timing":
                summary = result.get("summary", {})
                attempted = summary.get("attempted")
                passed = None  # The block measures decode, not task accuracy.
                timeouts = summary.get("timeout")
            else:
                summary = result.get("summary", {})
                attempted = summary.get("attempted")
                passed = summary.get("passed")
                timeouts = summary.get("timeout")
            records.append({"ordinal": ordinal, "block_id": block["block_id"],
                            "kind": block["kind"],
                            "status": "complete_pending_restoration" if complete
                                      else "incomplete_pending_restoration",
                            "reason_code": None if complete else "block_incomplete",
                            "run_sha256": _sha(raw),
                            "attempted": attempted, "passed": passed,
                            "timeouts": timeouts})
            if not complete:
                abort_reason = "block_incomplete"
        except Exception:  # noqa: BLE001 - any runner fault requires controller restoration
            abort_reason = "block_or_monitor_failed"
            issued = child is not None and child.exists()
            records.append({"ordinal": ordinal, "block_id": block["block_id"],
                            "kind": block["kind"],
                            "status": "incomplete" if issued else "not_run",
                            "reason_code": abort_reason, "run_sha256": None,
                            "attempted": None if issued else 0,
                            "passed": None, "timeouts": None})
    attempt = {
        "schema_version": ATTEMPT_SCHEMA,
        "window_id": document["window_id"],
        "cohort": document["cohort"],
        "study_id": document["study_id"],
        "window_plan_sha256": frozen.raw_sha256,
        "followon_source_bundle_sha256": document[
            "followon_source_bundle_sha256"
        ],
        "status": ("blocks_complete_pending_restoration"
                   if abort_reason is None else "blocks_incomplete_pending_restoration"),
        "abort_reason": abort_reason,
        "blocks": records,
        "restoration_required": True,
        "comparison_eligible": False,
        "promotion_authorized": False,
    }
    _write_json(output / "group-attempt.json", attempt)
    return attempt
