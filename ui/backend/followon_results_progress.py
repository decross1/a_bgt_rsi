"""Bounded projection of recorded, restored follow-on reports.

Each visible score
requires an immutable publication index, archived completed-window gate, and
unchanged raw window/result/block/report bytes. Current source replay is a
separate explicit operation; polling never touches private SSE or model APIs.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
import stat
from pathlib import Path

from .local_model_research import DEFAULT_RESEARCH_ROOT, Reader, SourceError

SCHEMA = "local-followon-results-progress/v1"
INDEX_SCHEMA = "flash-followon-report-publication/v1"
GATE_SCHEMA = "flash-followon-completed-window-validation/v1"
REPORT_SCHEMA = "flash-followon-content-free-report/v1"
CHILD = re.compile(r"(qfn-followon-[a-z0-9][a-z0-9._-]{0,63})\.(resident|flash)\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
KINDS = frozenset({
    "thinking", "market_canaries", "context", "selected_repair",
    "mtp0_controls", "mtp_decode_timing", "coding_temp1_medium",
})
MAX_CHILDREN = 64
MAX_WINDOWS = 6
MAX_BLOCKS = 16
MAX_GROUPS = 64
CONDITION = re.compile(r"[A-Za-z0-9_]{1,32}\Z")
SELECTED_RESIDENT_ID = "qfn-followon-selected-repair-20260915-a"
SELECTED_COMPAT_SHA256 = (
    "c701a71890e6378171321d117e3699ec8b6a08fdc42c022c2e48067280759662"
)


def _integer(value: object, *, ceiling: int = 10_000) -> bool:
    return type(value) is int and 0 <= value <= ceiling


def _seconds(value: object) -> bool:
    return type(value) in {int, float} and math.isfinite(value) and 0 <= value <= 86_400


def _optional_seconds(value: object) -> bool:
    return value is None or _seconds(value)


def _optional_tokens(value: object) -> bool:
    return value is None or _integer(value, ceiling=200_000)


def _repair_replay(block: dict, cohort: str) -> dict | None:
    """Project only bounded grader counts from one hash-bound repair run."""
    value = block.get("grader_replay")
    if value is None:
        return None
    _require(block["kind"] == "selected_repair" and isinstance(value, dict)
             and value.get("schema")
                == "flash-followon-selected-repair-grader-replay/v1"
             and value.get("run_sha256") == block["run_sha256"]
             and _sha(value.get("replay_receipt_sha256"))
             and value.get("source_replay_status")
                in {"available", "unavailable"}
             and value.get("comparison_eligible") is False
             and value.get("private_content_exported") is False,
             "published repair grader replay is unbound")
    counts = ("raw_private_calls_verified", "declared", "replayed",
              "producer_consistent", "producer_inconsistent",
              "grader_unavailable")
    _require(all(_integer(value.get(key), ceiling=44) for key in counts)
             and value["declared"] == value["raw_private_calls_verified"]
             == block["attempted"]
             and value["replayed"] + value["grader_unavailable"]
                == value["declared"]
             and value["producer_consistent"]
                + value["producer_inconsistent"] == value["replayed"],
             "published repair replay denominator is malformed")
    lanes = value.get("by_lane")
    expected = ({"flash_off", "flash_medium"}
                if cohort == "flash" else {"resident_native"})
    lane_counts = ("declared", "producer_passed", "replayed",
                   "replayed_passed", "producer_consistent",
                   "producer_inconsistent", "grader_unavailable")
    _require(isinstance(lanes, dict) and set(lanes) == expected
             and all(isinstance(row, dict)
                     and all(_integer(row.get(key), ceiling=44)
                             for key in lane_counts)
                     for row in lanes.values())
             and sum(row["declared"] for row in lanes.values())
                == value["declared"]
             and sum(row["replayed"] for row in lanes.values())
                == value["replayed"]
             and sum(row["producer_consistent"] for row in lanes.values())
                == value["producer_consistent"]
             and sum(row["producer_inconsistent"] for row in lanes.values())
                == value["producer_inconsistent"]
             and sum(row["grader_unavailable"] for row in lanes.values())
                == value["grader_unavailable"]
             and sum(row["producer_passed"] for row in lanes.values())
                == block["passed"]
             and all(row["producer_passed"] <= row["declared"]
                     and row["replayed_passed"] <= row["replayed"]
                     and row["producer_consistent"]
                        + row["producer_inconsistent"] == row["replayed"]
                     and row["replayed"] + row["grader_unavailable"]
                        == row["declared"]
                     for row in lanes.values()),
             "published repair replay lane counts are malformed")
    return {"schema": value["schema"], "run_sha256": value["run_sha256"],
            "replay_receipt_sha256": value["replay_receipt_sha256"],
            "source_replay_status": value["source_replay_status"],
            **{key: value[key] for key in counts},
            "by_lane": {lane: {key: row[key] for key in lane_counts}
                        for lane, row in sorted(lanes.items())},
            "comparison_eligible": False}


def _coding_replay(block: dict, cohort: str) -> dict | None:
    """Project the four-task diagnostic's independent grade counts only."""
    value = block.get("grader_replay")
    if value is None:
        return None
    _require(cohort == "flash" and block["kind"] == "coding_temp1_medium"
             and isinstance(value, dict)
             and value.get("schema")
                == "flash-followon-coding-temp1-grader-replay/v1"
             and value.get("run_sha256") == block["run_sha256"]
             and _sha(value.get("replay_receipt_sha256"))
             and value.get("source_replay_status") in {"available", "unavailable"}
             and value.get("comparison_eligible") is False
             and value.get("private_content_exported") is False,
             "published coding grader replay is unbound")
    counts = ("raw_private_calls_verified", "declared", "replayed",
              "producer_consistent", "producer_inconsistent",
              "grader_unavailable")
    _require(all(_integer(value.get(key), ceiling=4) for key in counts)
             and block["attempted"] == value["declared"]
                == value["raw_private_calls_verified"] == 4
             and value["replayed"] + value["grader_unavailable"] == 4
             and value["producer_consistent"]
                + value["producer_inconsistent"] == value["replayed"],
             "published coding replay denominator differs")
    family_counts = ("declared", "producer_passed", "replayed",
                     "replayed_passed", "producer_consistent",
                     "producer_inconsistent", "grader_unavailable")
    families = value.get("by_family")
    _require(isinstance(families, dict)
             and set(families) == {"portfolio", "historical"}
             and all(isinstance(row, dict)
                     and row.get("declared") == 2
                     and all(_integer(row.get(key), ceiling=2)
                             for key in family_counts)
                     and row["replayed"] + row["grader_unavailable"] == 2
                     and row["producer_consistent"]
                        + row["producer_inconsistent"] == row["replayed"]
                     and row["producer_passed"] <= 2
                     and row["replayed_passed"] <= row["replayed"]
                     for row in families.values())
             and sum(row["producer_passed"] for row in families.values())
                == block["passed"]
             and sum(row["replayed"] for row in families.values())
                == value["replayed"]
             and sum(row["producer_consistent"] for row in families.values())
                == value["producer_consistent"]
             and sum(row["producer_inconsistent"] for row in families.values())
                == value["producer_inconsistent"]
             and sum(row["grader_unavailable"] for row in families.values())
                == value["grader_unavailable"],
             "published coding replay family counts differ")
    return {"schema": value["schema"], "run_sha256": value["run_sha256"],
            "replay_receipt_sha256": value["replay_receipt_sha256"],
            "source_replay_status": value["source_replay_status"],
            **{key: value[key] for key in counts},
            "by_family": {family: {key: row[key] for key in family_counts}
                          for family, row in sorted(families.items())},
            "comparison_eligible": False}


def _public_blocks(report: dict, cohort: str) -> list[dict]:
    """Return only fixed numeric/categorical fields from a published report."""
    blocks = report.get("blocks")
    _require(isinstance(blocks, list) and 0 < len(blocks) <= MAX_BLOCKS,
             "published block count is malformed")
    projected = []
    for block in blocks:
        _require(isinstance(block, dict)
                 and isinstance(block.get("block_id"), str)
                 and len(block["block_id"]) <= 100
                 and block.get("kind") in KINDS
                 and _sha(block.get("run_sha256"))
                 and _integer(block.get("attempted"))
                 and (block.get("passed") is None
                      or _integer(block.get("passed")))
                 and _integer(block.get("timeouts")),
                 "published block counters are malformed")
        groups = block.get("groups")
        _require(isinstance(groups, list) and len(groups) <= MAX_GROUPS,
                 "published condition count is malformed")
        visible_groups = []
        for group in groups:
            _require(isinstance(group, dict)
                     and isinstance(group.get("condition"), list)
                     and 1 <= len(group["condition"]) <= 3
                     and all(isinstance(part, str)
                             and CONDITION.fullmatch(part) is not None
                             for part in group["condition"])
                     and all(_integer(group.get(key)) for key in (
                         "declared", "attempted", "passed", "timeouts",
                         "errors", "calls", "recorded_timings",
                         "supported", "unsupported",
                     ))
                     and _seconds(group.get("wall_seconds"))
                     and _optional_seconds(group.get("mean_request_latency_seconds"))
                     and _optional_seconds(group.get("mean_first_token_seconds"))
                     and _optional_tokens(group.get("actual_input_tokens_min"))
                     and _optional_tokens(group.get("actual_input_tokens_max"))
                     and group["attempted"] <= group["declared"]
                     and group["passed"] <= group["attempted"]
                     and group["timeouts"] <= group["attempted"]
                     and group["supported"] + group["unsupported"]
                         <= group["declared"]
                     and group["recorded_timings"] <= group["calls"],
                     "published condition counters are malformed")
            minimum = group["actual_input_tokens_min"]
            maximum = group["actual_input_tokens_max"]
            _require((minimum is None) == (maximum is None)
                     and (minimum is None or minimum <= maximum),
                     "published context input range is malformed")
            visible_groups.append({key: group[key] for key in (
                "condition", "declared", "attempted", "passed",
                "timeouts", "errors", "supported", "unsupported",
                "wall_seconds", "calls",
                "recorded_timings", "mean_request_latency_seconds",
                "mean_first_token_seconds", "actual_input_tokens_min",
                "actual_input_tokens_max",
            )})
        replay = (_coding_replay(block, cohort)
                  if block["kind"] == "coding_temp1_medium"
                  else _repair_replay(block, cohort))
        projected.append({key: block[key] for key in (
            "block_id", "kind", "run_sha256", "attempted", "passed",
            "timeouts",
        )} | {"groups": visible_groups,
             "grader_replay": replay})
    return projected


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SourceError(message)


def _sha(value) -> bool:
    return isinstance(value, str) and SHA256.fullmatch(value) is not None


def _ref(reader: Reader, root: Path, value: object) -> tuple[dict, str]:
    """Read only an absolute registered research child and its declared SHA."""
    _require(isinstance(value, dict) and _sha(value.get("sha256")),
             "published follow-on reference is malformed")
    text = value.get("path")
    _require(isinstance(text, str) and len(text) <= 1024,
             "published follow-on path is malformed")
    path = Path(text)
    _require(path.is_absolute() and not any(part in {".", ".."}
                                             for part in path.parts),
             "published follow-on path is not absolute and direct")
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise SourceError("published follow-on path leaves the registered root") from exc
    _require(relative.parts and relative.parts[0] == "evaluation",
             "published follow-on reference is outside evaluation")
    content, digest = reader.read(str(relative), digest=value["sha256"])
    return content, digest


def _selected_resident_gate(reader: Reader, root: Path, publication: Path,
                            index: dict, gate: dict, report: dict,
                            window_id: str, cohort: str) -> None:
    """Require the archived prelaunch start-chronology reader for this trial."""
    selected = any(isinstance(block, dict)
                   and block.get("kind") == "selected_repair"
                   for block in report.get("blocks", []))
    if not selected or cohort != "resident":
        return
    marker = gate.get("chronology_compatibility")
    refs = index.get("archived_reader_source_refs")
    ref = (refs.get("selected-resident-compat.py")
           if isinstance(refs, dict) else None)
    _require(window_id == SELECTED_RESIDENT_ID
             and isinstance(marker, dict)
             and marker.get("schema")
                == "flash-followon-selected-repair-resident-start-compatibility/v1"
             and marker.get("repair")
                == "missing_result_started_at_derived_from_exact_final_state_only"
             and marker.get("original_result_bytes_preserved") is True
             and marker.get("other_completed_window_checks_unchanged") is True
             and marker.get("comparison_eligible") is False
             and marker.get("compatibility_reader_sha256")
                == SELECTED_COMPAT_SHA256
             and all(_sha(marker.get(key)) for key in (
                 "state_sha256", "supervision_sha256", "memory_log_sha256",
                 "gate_source_sha256",
             ))
             and isinstance(marker.get("final_state_started_at"), str)
             and isinstance(ref, dict)
             and ref.get("sha256") == SELECTED_COMPAT_SHA256
             and ref.get("path")
                == str(publication / "selected-resident-compat.py")
             and _integer(ref.get("bytes"), ceiling=128_000)
             and ref["bytes"] > 0,
             "selected resident completion lacks its predeclared chronology proof")
    _read_archived_source(reader, root, ref)


def _read_archived_source(reader: Reader, root: Path, ref: dict) -> None:
    """Hash one small archived source file without parsing or serving its text."""
    relative = Path(ref["path"]).relative_to(root)
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    opened = []
    try:
        current = os.open(reader.root, flags | os.O_DIRECTORY)
        opened.append(current)
        for part in relative.parts[:-1]:
            current = os.open(part, flags | os.O_DIRECTORY, dir_fd=current)
            opened.append(current)
        current = os.open(relative.name, flags, dir_fd=current)
        opened.append(current)
        before = os.fstat(current)
        _require(stat.S_ISREG(before.st_mode)
                 and before.st_size == ref["bytes"],
                 "archived completion reader size changed")
        remaining = ref["bytes"] + 1
        chunks = []
        while remaining:
            chunk = os.read(current, min(remaining, 64 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(current)
        _require(len(raw) == ref["bytes"]
                 and before.st_size == after.st_size
                 and before.st_mtime_ns == after.st_mtime_ns
                 and hashlib.sha256(raw).hexdigest() == ref["sha256"],
                 "archived completion reader bytes drifted")
    except OSError as exc:
        raise SourceError("archived completion reader is unreadable") from exc
    finally:
        for fd in reversed(opened):
            os.close(fd)


def _raw_refs(reader: Reader, root: Path, index: dict, gate: dict,
              report: dict) -> list[str]:
    refs = index.get("raw_refs")
    _require(isinstance(refs, dict), "published source references are missing")
    _require(isinstance(refs.get("window_source"), dict)
             and isinstance(refs.get("terminal_result"), dict),
             "published window/result references are malformed")
    child = f"{index['window_id']}.{index['cohort']}"
    output = root / "evaluation/followon-runs" / child
    _require(refs["window_source"].get("path") == str(
                 root / "evaluation/followon-window-plans" / f"{child}.json"
             ) and refs["terminal_result"].get("path")
                == str(output / "result.json"),
             "published window/result paths are outside their registered children")
    source, _ = _ref(reader, root, refs.get("window_source"))
    result, _ = _ref(reader, root, refs.get("terminal_result"))
    _require(source.get("schema_version") in {
        "flash-followon-window/v1", "flash-followon-window/v2",
    } and source.get("window_id") == index["window_id"]
      and source.get("cohort") == index["cohort"]
      and result.get("pair_id") == index["window_id"],
             "published source/result identities differ")
    routes = source.get("route_bindings")
    registered_routes = ({"flash_next_mia"} if index["cohort"] == "flash"
                         else {"resident_qwen", "resident_gemma"})
    _require(isinstance(routes, dict) and 1 <= len(routes) <= 2
             and set(routes) <= registered_routes,
             "published model routes differ from their cohort")
    _require(refs["window_source"]["sha256"] == gate.get("window_plan_sha256")
             == report.get("window_plan_sha256")
             and refs["terminal_result"]["sha256"] == gate.get("result_sha256")
             == report.get("result_sha256"),
             "archived window/result hashes differ")
    block_refs = refs.get("block_runs")
    blocks = gate.get("blocks")
    reported = report.get("blocks")
    declared = source.get("blocks")
    _require(isinstance(block_refs, list) and isinstance(blocks, list)
             and isinstance(reported, list)
             and isinstance(declared, list)
             and len(block_refs) == len(blocks) == len(reported)
                == len(declared)
             and 0 < len(blocks) <= MAX_BLOCKS,
             "archived block coverage differs")
    tested_routes: set[str] = set()
    for ordinal, (ref, proof, item, frozen) in enumerate(
        zip(block_refs, blocks, reported, declared, strict=True)
    ):
        _require(isinstance(ref, dict) and isinstance(proof, dict)
                 and isinstance(item, dict) and isinstance(frozen, dict)
                 and ref.get("block_id") == proof.get("block_id")
                    == item.get("block_id") == frozen.get("block_id")
                 and ref.get("kind") == proof.get("kind")
                    == item.get("kind") == frozen.get("kind") in KINDS
                 and ref.get("sha256") == proof.get("run_sha256")
                    == item.get("run_sha256")
                 and frozen.get("ordinal") == ordinal
                 and frozen.get("endpoint_name") in routes,
                 "archived block identity or raw SHA differs")
        tested_routes.add(frozen["endpoint_name"])
        path = Path(ref.get("path", ""))
        relative = frozen.get("output_relative")
        _require(isinstance(relative, str)
                 and len(relative) <= 180
                 and Path(relative).parts
                 and Path(relative).parts[0] == "blocks"
                 and not any(part in {".", ".."}
                             for part in Path(relative).parts)
                 and path == output / relative / "run.json"
                 and path.name == "run.json"
                 and path.parent.is_relative_to(output / "blocks")
                 and path.parent != output / "blocks",
                 "published block run is outside its registered child")
        run, _ = _ref(reader, root, ref)
        _require(isinstance(run.get("outcomes"), list),
                 "archived block run has no task rows")
        groups = item.get("groups")
        _require(isinstance(groups, list) and len(groups) <= MAX_GROUPS,
                 "published group coverage is malformed")
        _require(sum(group.get("attempted", -1) for group in groups
                     if isinstance(group, dict)) == proof.get("attempted")
                 and sum(group.get("timeouts", -1) for group in groups
                         if isinstance(group, dict)) == proof.get("timeouts")
                 and (proof.get("passed") is None or
                      sum(group.get("passed", -1) for group in groups
                          if isinstance(group, dict)) == proof["passed"]),
                 "published group counts differ from archived completed gate")
    _require(tested_routes, "published window has no tested endpoint")
    return sorted(tested_routes)


def _window(reader: Reader, root: Path, child: str) -> dict:
    name = CHILD.fullmatch(child)
    _require(name is not None, "published follow-on child is unregistered")
    window_id, cohort = name.groups()
    index, _ = reader.read(f"evaluation/followon-reports/{child}/index.json")
    _require(index.get("schema") == INDEX_SCHEMA
             and index.get("kind") == "independent_window"
             and index.get("window_id") == window_id
             and index.get("cohort") == cohort
             and index.get("complete") is True
             and index.get("archived_completed_gate_admitted") is True
             and index.get("comparison_eligible") is False
             and index.get("score_claim_authorized") is False
             and index.get("promotion_authorized") is False
             and index.get("private_content_exported") is False,
             "follow-on index did not record independent admission")
    publication = root / "evaluation/followon-reports" / child
    _require(isinstance(index.get("recorded_gate_ref"), dict)
             and isinstance(index.get("report_ref"), dict)
             and index["recorded_gate_ref"].get("path")
                == str(publication / "completed-gate.json")
             and index["report_ref"].get("path")
                == str(publication / "report.json"),
             "follow-on gate/report paths are outside their final publication")
    gate, gate_sha = _ref(reader, root, index.get("recorded_gate_ref"))
    report, report_sha = _ref(reader, root, index.get("report_ref"))
    _require(gate.get("schema") == GATE_SCHEMA
             and gate.get("window_id") == window_id
             and gate.get("cohort") == cohort
             and gate.get("exact_restoration_verified") is True
             and gate.get("comparison_eligible") is False
             and gate.get("promotion_authorized") is False
             and gate.get("private_content_exported") is False,
             "archived completed gate is ineligible")
    _require(report.get("schema") == REPORT_SCHEMA
             and report.get("window_id") == window_id
             and report.get("cohort") == cohort
             and report.get("exact_restoration_verified") is True
             and report.get("comparison_eligible") is False
             and report.get("score_claim_authorized") is False
             and report.get("promotion_authorized") is False
             and report.get("private_content_exported") is False
             and report.get("controller_source_bundle_sha256")
                == gate.get("controller_source_bundle_sha256")
                == index.get("recorded_controller_source_bundle_sha256"),
             "published report does not bind the archived gate")
    _selected_resident_gate(reader, root, publication, index, gate, report,
                            window_id, cohort)
    routes = _raw_refs(reader, root, index, gate, report)
    public_blocks = _public_blocks(report, cohort)
    # The final index's replay label is not a replay receipt. Polling makes no
    # current-source assertion even if a mutable index claims verified.
    return {
        "id": child, "cohort": cohort, "status": "recorded_admitted",
        "routes": routes,
        "admission_class": "RECORDED_COMPLETED_WINDOW_ADMISSION",
        "current_source_replay": "not_performed",
        "report_schema": REPORT_SCHEMA,
        "report_sha256": report_sha, "admission_sha256": gate_sha,
        "recorded_controller_source_bundle_sha256":
            gate["controller_source_bundle_sha256"],
        "window_plan_sha256": gate["window_plan_sha256"],
        "result_sha256": gate["result_sha256"],
        "exact_restoration_verified": True,
        "comparison_eligible": False,
        "blocks": public_blocks,
    }


def project_followon_results(root: Path | None = DEFAULT_RESEARCH_ROOT) -> dict:
    result = {"schema_version": SCHEMA, "status": "unavailable",
              "windows": [], "warnings": [], "promotion_authorized": False}
    if root is None:
        return result
    root = Path(root).absolute()
    try:
        reader = Reader(root)
        report_root = root / "evaluation/followon-reports"
        if not report_root.exists():
            result["status"] = "available"
            return result
        _require(report_root.is_dir() and not report_root.is_symlink()
                 and report_root.resolve() == report_root,
                 "follow-on report directory is redirected")
        children = list(report_root.iterdir())
        _require(len(children) <= MAX_CHILDREN,
                 "follow-on publication scan bound exceeded")
        # Only the final index makes a child visible. A partial publication
        # cannot populate scores, and the newest invalid published child never
        # silently turns into an older success.
        indexed = [child for child in children
                   if CHILD.fullmatch(child.name) and
                   (child / "index.json").exists()]
        indexed.sort(key=lambda path: ((path / "index.json").lstat().st_mtime_ns,
                                       path.name),
                     reverse=True)
        for child in indexed[:MAX_WINDOWS]:
            try:
                result["windows"].append(_window(reader, root, child.name))
            except (SourceError, OSError, ValueError, TypeError, KeyError):
                result["warnings"].append(
                    "A recorded follow-on window failed source validation; its scores are withheld."
                )
        if len(indexed) > MAX_WINDOWS:
            result["warnings"].append(
                "Showing the six latest recorded follow-on windows."
            )
        result["status"] = "partial" if result["warnings"] else "available"
    except (SourceError, OSError, ValueError, TypeError):
        result["warnings"].append(
            "Follow-on publications are unavailable or invalid; scores are withheld."
        )
    return result
