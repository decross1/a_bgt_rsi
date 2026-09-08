# Source: oracle_system/oracle_harness/apparatus_audit.py
# Inspected source SHA256: d7e4e35001b846ba66c69e18e7225503803ab8e22da48d97b9b261a6f1492040
# Lab-owned candidate copy; no Oracle runtime dependency. Source behavior retained.
"""Read-only consistency audits for claim-to-wrapper-argument binding.

This module intentionally does not import code from ``a_bgt_rsi``.  It treats
the two JSONL files as inert evidence, joins records only through the exact
``wrapper_call_ids`` stored by a canonical iteration, and accepts only JSON
array tool-call completions.  It does not attempt semantic similarity.

A pass establishes consistency between the two caller-selected readable JSONL
inputs at the reported byte snapshots.  This module does not authenticate Nara,
the files' historical provenance, their authors, or the caller-supplied prefix
hashes, and it grants no authority.

Exit policy is implemented by the CLI: both ``mismatch`` and ``unverifiable``
are fail-closed audit failures (exit 1); malformed JSONL is an input-integrity
failure (exit 2).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import stat
from typing import Any, Callable


AUDIT_SCHEMA = "https://oracle.local/schema/apparatus-claim-binding-audit/v1"
DOWNSTREAM_STAGES = (
    "retrieve_literature",
    "novelty_classify",
    "critic_loop_v0",
)
EXPECTED_CALLER_TAG = "nara.run_iteration"
MAX_JSONL_ROW_BYTES = 4 * 1024 * 1024


class ApparatusAuditInputError(ValueError):
    """Raised when an input cannot be treated as well-formed JSONL evidence."""


class _DuplicateJsonKey(ValueError):
    """Raised when JSON has parser-ambiguous duplicate object members."""

    def __init__(self, key: str) -> None:
        super().__init__(f"duplicate object key: {key!r}")
        self.key = key


class _InvalidJsonConstant(ValueError):
    """Raised when Python's JSON extension accepts a non-JSON number."""


class _InvalidUnicodeScalar(ValueError):
    """Raised when decoded JSON contains an unpaired surrogate code point."""


class _JsonDecoderLimit(ValueError):
    """Raised when the decoder rejects otherwise tokenizable JSON by a limit."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise _DuplicateJsonKey(key)
        value[key] = item
    return value


def _reject_json_constant(value: str) -> None:
    raise _InvalidJsonConstant(f"non-JSON numeric constant: {value}")


def _require_unicode_scalars(value: Any, label: str = "$") -> None:
    if isinstance(value, str):
        if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
            raise _InvalidUnicodeScalar(
                f"decoded string contains a surrogate code point at {label}"
            )
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _require_unicode_scalars(item, f"{label}[{index}]")
    elif isinstance(value, dict):
        for key, item in value.items():
            _require_unicode_scalars(key, f"{label}.<key>")
            _require_unicode_scalars(item, f"{label}.{key}")
    elif isinstance(value, float) and not math.isfinite(value):
        raise _InvalidJsonConstant(
            f"decoded number is not finite at {label}"
        )


def _loads_unambiguous_json(value: str) -> Any:
    try:
        decoded = json.loads(
            value,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except (
        json.JSONDecodeError,
        _DuplicateJsonKey,
        _InvalidJsonConstant,
    ):
        raise
    except (ValueError, OverflowError, RecursionError) as exc:
        raise _JsonDecoderLimit(f"JSON decoder limit: {exc}") from exc
    _require_unicode_scalars(decoded)
    return decoded


@dataclass(frozen=True)
class _JsonlRow:
    line: int
    raw_sha256: str
    value: dict[str, Any]


def _digest_text(value: str) -> str:
    return "sha256:" + sha256(value.encode("utf-8")).hexdigest()


def _digest_bytes(value: bytes) -> str:
    return "sha256:" + sha256(value).hexdigest()


def _fingerprint(stat_result: os.stat_result) -> dict[str, int]:
    return {
        "device": stat_result.st_dev,
        "inode": stat_result.st_ino,
        "size": stat_result.st_size,
        "mtime_ns": stat_result.st_mtime_ns,
        "ctime_ns": stat_result.st_ctime_ns,
    }


def _path_fingerprint(path: Path, label: str, phase: str) -> dict[str, int]:
    try:
        stat_result = path.lstat()
    except OSError as exc:
        raise ApparatusAuditInputError(
            f"unable to stat {label} {path} {phase}: {exc.strerror or exc}"
        ) from exc
    if not stat.S_ISREG(stat_result.st_mode):
        raise ApparatusAuditInputError(
            f"{label} {path} must be a non-symlink regular file ({phase})"
        )
    return _fingerprint(stat_result)


def _require_same_fingerprint(
    expected: dict[str, int],
    actual: dict[str, int],
    path: Path,
    label: str,
    phase: str,
) -> None:
    if actual != expected:
        raise ApparatusAuditInputError(
            f"{label} {path} changed during apparatus audit ({phase}); "
            f"before={expected!r}, after={actual!r}"
        )


def _read_jsonl(
    path: Path,
    label: str,
    *,
    keep: Callable[[dict[str, Any]], bool] | None = None,
    byte_limit: int | None = None,
    expected_sha256: str | None = None,
    initial_fingerprint: dict[str, int] | None = None,
) -> tuple[list[_JsonlRow], dict[str, Any]]:
    """Read and hash a JSONL source without opening it for writing."""

    observed_initial_fingerprint = _path_fingerprint(path, label, "before read")
    if initial_fingerprint is None:
        initial_fingerprint = observed_initial_fingerprint
    else:
        _require_same_fingerprint(
            initial_fingerprint,
            observed_initial_fingerprint,
            path,
            label,
            "pre-captured snapshot check",
        )
    digest = sha256()
    kept: list[_JsonlRow] = []
    byte_count = 0
    record_count = 0
    if byte_limit is not None and (type(byte_limit) is not int or byte_limit < 1):
        raise ApparatusAuditInputError(f"{label} byte limit must be a positive integer")
    if expected_sha256 is not None:
        normalized_expected = expected_sha256.removeprefix("sha256:")
        if (
            len(normalized_expected) != 64
            or any(character not in "0123456789abcdef" for character in normalized_expected)
        ):
            raise ApparatusAuditInputError(
                f"{label} expected SHA-256 must be lowercase hexadecimal"
            )
    else:
        normalized_expected = None
    try:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        source = os.fdopen(descriptor, "rb")
    except OSError as exc:
        raise ApparatusAuditInputError(
            f"unable to read {label} {path}: {exc.strerror or exc}"
        ) from exc

    with source:
        _require_same_fingerprint(
            initial_fingerprint,
            _fingerprint(os.fstat(source.fileno())),
            path,
            label,
            "path-to-open check",
        )
        line_number = 0
        while byte_limit is None or byte_count < byte_limit:
            read_limit = MAX_JSONL_ROW_BYTES + 1
            if byte_limit is not None:
                read_limit = min(read_limit, byte_limit - byte_count + 1)
            raw_line = source.readline(read_limit)
            if not raw_line:
                break
            line_number += 1
            if len(raw_line) > MAX_JSONL_ROW_BYTES:
                raise ApparatusAuditInputError(
                    f"invalid {label} row {line_number} in {path}: "
                    f"row exceeds {MAX_JSONL_ROW_BYTES} bytes"
                )
            if byte_limit is not None and byte_count + len(raw_line) > byte_limit:
                raise ApparatusAuditInputError(
                    f"{label} byte limit does not end on a JSONL row boundary"
                )
            digest.update(raw_line)
            byte_count += len(raw_line)
            if not raw_line.strip():
                raise ApparatusAuditInputError(
                    f"invalid {label} row {line_number} in {path}: blank JSONL row"
                )
            try:
                text = raw_line.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ApparatusAuditInputError(
                    f"invalid {label} row {line_number} in {path}: invalid UTF-8"
                ) from exc
            try:
                value = _loads_unambiguous_json(text)
            except (
                json.JSONDecodeError,
                _DuplicateJsonKey,
                _InvalidJsonConstant,
                _InvalidUnicodeScalar,
                _JsonDecoderLimit,
            ) as exc:
                detail = (
                    f"JSON decode error at column {exc.colno}"
                    if isinstance(exc, json.JSONDecodeError)
                    else str(exc)
                )
                raise ApparatusAuditInputError(
                    f"invalid {label} row {line_number} in {path}: {detail}"
                ) from exc
            if not isinstance(value, dict):
                raise ApparatusAuditInputError(
                    f"invalid {label} row {line_number} in {path}: "
                    "top-level value must be an object"
                )
            record_count += 1
            if keep is None or keep(value):
                kept.append(
                    _JsonlRow(
                        line=line_number,
                        raw_sha256=_digest_bytes(raw_line),
                        value=value,
                    )
                )
        if byte_limit is not None and byte_count != byte_limit:
            raise ApparatusAuditInputError(
                f"{label} ended at {byte_count} bytes before byte limit {byte_limit}"
            )
        _require_same_fingerprint(
            initial_fingerprint,
            _fingerprint(os.fstat(source.fileno())),
            path,
            label,
            "descriptor post-read check",
        )

    observed_sha256 = digest.hexdigest()
    if normalized_expected is not None and observed_sha256 != normalized_expected:
        raise ApparatusAuditInputError(
            f"{label} prefix SHA-256 mismatch: expected {normalized_expected}, "
            f"observed {observed_sha256}"
        )
    return kept, {
        "path": str(path),
        "sha256": "sha256:" + observed_sha256,
        "bytes": byte_count,
        "records": record_count,
        "prefix_mode": byte_limit is not None,
        "fingerprint": initial_fingerprint,
    }


def _canonical_iteration(row: _JsonlRow) -> dict[str, Any]:
    iteration_id = row.value.get("iteration_id")
    if not isinstance(iteration_id, str) or not iteration_id:
        raise ApparatusAuditInputError(
            f"invalid loop-memory row {row.line}: iteration_id must be a non-empty string"
        )

    hypothesis = row.value.get("hypothesis")
    hypothesis_text = hypothesis.get("text") if isinstance(hypothesis, dict) else None
    if not isinstance(hypothesis_text, str) or not hypothesis_text:
        hypothesis_text = None

    raw_ids = row.value.get("wrapper_call_ids")
    wrapper_ids: list[str] = []
    link_issues: list[str] = []
    if not isinstance(raw_ids, list):
        link_issues.append("wrapper_call_ids_missing_or_not_array")
    else:
        for index, value in enumerate(raw_ids):
            if isinstance(value, str) and value:
                wrapper_ids.append(value)
            else:
                link_issues.append(f"wrapper_call_ids[{index}]_invalid")
        if len(wrapper_ids) != len(set(wrapper_ids)):
            link_issues.append("wrapper_call_ids_not_unique")

    return {
        "iteration_id": iteration_id,
        "loop_memory_line": row.line,
        "loop_memory_record_sha256": row.raw_sha256,
        "hypothesis_text": hypothesis_text,
        "wrapper_call_ids": wrapper_ids,
        "link_issues": link_issues,
    }


def _tool_evidence(
    row: _JsonlRow,
    request_id: str,
    expected_run_id: str,
    expected_parent_request_id: str,
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    record = row.value
    completion = record.get("completion")
    run_id = record.get("run_id")
    caller_tag = record.get("caller_tag")
    parent_request_id = record.get("parent_request_id")
    diagnostic: dict[str, Any] = {
        "request_id": request_id,
        "call_log_line": row.line,
        "call_record_sha256": row.raw_sha256,
        "run_id": run_id if isinstance(run_id, str) else None,
        "caller_tag": caller_tag if isinstance(caller_tag, str) else None,
        "parent_request_id": (
            parent_request_id if isinstance(parent_request_id, str) else None
        ),
    }
    evidence: dict[str, list[dict[str, Any]]] = {
        stage: [] for stage in DOWNSTREAM_STAGES
    }

    if not isinstance(run_id, str) or run_id != expected_run_id:
        diagnostic["status"] = "run_id_missing_or_mismatch"
        diagnostic["expected_run_id"] = expected_run_id
        return diagnostic, evidence

    if caller_tag != EXPECTED_CALLER_TAG:
        diagnostic["status"] = "caller_tag_missing_or_mismatch"
        diagnostic["expected_caller_tag"] = EXPECTED_CALLER_TAG
        return diagnostic, evidence

    if parent_request_id != expected_parent_request_id:
        diagnostic["status"] = "parent_request_id_missing_or_mismatch"
        diagnostic["expected_parent_request_id"] = expected_parent_request_id
        return diagnostic, evidence

    if not isinstance(completion, str):
        diagnostic["status"] = "completion_missing_or_not_string"
        return diagnostic, evidence

    diagnostic["completion_sha256"] = _digest_text(completion)
    try:
        tool_calls = _loads_unambiguous_json(completion)
    except json.JSONDecodeError:
        diagnostic["status"] = "completion_not_json"
        return diagnostic, evidence
    except _DuplicateJsonKey as exc:
        diagnostic["status"] = "completion_duplicate_object_key"
        diagnostic["duplicate_key"] = exc.key
        return diagnostic, evidence
    except _InvalidJsonConstant as exc:
        diagnostic["status"] = "completion_non_json_numeric_constant"
        diagnostic["invalid_json"] = str(exc)
        return diagnostic, evidence
    except _InvalidUnicodeScalar as exc:
        diagnostic["status"] = "completion_invalid_unicode_scalar"
        diagnostic["invalid_json"] = str(exc)
        return diagnostic, evidence
    except _JsonDecoderLimit as exc:
        diagnostic["status"] = "completion_decoder_limit"
        diagnostic["invalid_json"] = str(exc)
        return diagnostic, evidence
    if not isinstance(tool_calls, list):
        diagnostic["status"] = "completion_not_json_array"
        return diagnostic, evidence

    diagnostic["array_items"] = len(tool_calls)
    recognized = 0
    malformed_items = 0
    seen_tool_call_ids: set[str] = set()
    duplicate_tool_call_ids = 0
    downstream_stage_counts: Counter[str] = Counter()
    for tool_call_index, tool_call in enumerate(tool_calls):
        if not isinstance(tool_call, dict):
            malformed_items += 1
            continue
        tool_call_id = tool_call.get("id")
        if (
            not isinstance(tool_call_id, str)
            or not tool_call_id
            or tool_call.get("type") != "function"
        ):
            malformed_items += 1
            continue
        if tool_call_id in seen_tool_call_ids:
            malformed_items += 1
            duplicate_tool_call_ids += 1
            continue
        seen_tool_call_ids.add(tool_call_id)
        function = tool_call.get("function")
        if not isinstance(function, dict):
            malformed_items += 1
            continue
        name = function.get("name")
        arguments = function.get("arguments")
        if not isinstance(name, str) or not name or not isinstance(arguments, str):
            malformed_items += 1
            continue
        if name not in DOWNSTREAM_STAGES:
            continue
        recognized += 1
        downstream_stage_counts[name] += 1
        item: dict[str, Any] = {
            "request_id": request_id,
            "call_log_line": row.line,
            "call_record_sha256": row.raw_sha256,
            "tool_call_index": tool_call_index,
            "completion_sha256": diagnostic["completion_sha256"],
            "run_id": diagnostic["run_id"],
        }
        item["arguments_sha256"] = _digest_text(arguments)
        try:
            parsed_arguments = _loads_unambiguous_json(arguments)
        except json.JSONDecodeError:
            item["extraction"] = "arguments_not_json"
            evidence[name].append(item)
            continue
        except _DuplicateJsonKey as exc:
            item["extraction"] = "arguments_duplicate_object_key"
            item["duplicate_key"] = exc.key
            evidence[name].append(item)
            continue
        except _InvalidJsonConstant as exc:
            item["extraction"] = "arguments_non_json_numeric_constant"
            item["invalid_json"] = str(exc)
            evidence[name].append(item)
            continue
        except _InvalidUnicodeScalar as exc:
            item["extraction"] = "arguments_invalid_unicode_scalar"
            item["invalid_json"] = str(exc)
            evidence[name].append(item)
            continue
        except _JsonDecoderLimit as exc:
            item["extraction"] = "arguments_decoder_limit"
            item["invalid_json"] = str(exc)
            evidence[name].append(item)
            continue
        if not isinstance(parsed_arguments, dict):
            item["extraction"] = "arguments_not_object"
            evidence[name].append(item)
            continue
        hypothesis_text = parsed_arguments.get("hypothesis_text")
        if not isinstance(hypothesis_text, str):
            item["extraction"] = "hypothesis_text_missing_or_not_string"
            evidence[name].append(item)
            continue
        item["extraction"] = "extracted"
        item["hypothesis_text_sha256"] = _digest_text(hypothesis_text)
        item["hypothesis_text_bytes"] = len(hypothesis_text.encode("utf-8"))
        item["_hypothesis_text"] = hypothesis_text
        evidence[name].append(item)

    diagnostic["recognized_downstream_calls"] = recognized
    duplicate_downstream_stages = sorted(
        stage for stage, count in downstream_stage_counts.items() if count > 1
    )
    if malformed_items:
        diagnostic["malformed_array_items"] = malformed_items
    if duplicate_tool_call_ids:
        diagnostic["duplicate_tool_call_ids"] = duplicate_tool_call_ids
    if duplicate_downstream_stages:
        diagnostic["duplicate_downstream_stages"] = duplicate_downstream_stages
    diagnostic["status"] = (
        "structured_json_array_ambiguous"
        if malformed_items or duplicate_downstream_stages
        else "structured_json_array"
    )
    return diagnostic, evidence


def _stage_result(
    stage_evidence: list[dict[str, Any]],
    canonical_text: str | None,
    link_issues: list[str],
) -> dict[str, Any]:
    public_evidence: list[dict[str, Any]] = []
    mismatch = False
    extraction_failure = False
    for item in stage_evidence:
        public_item = {key: value for key, value in item.items() if key != "_hypothesis_text"}
        if item.get("extraction") == "extracted" and canonical_text is not None:
            comparison = (
                "exact_match"
                if item["_hypothesis_text"] == canonical_text
                else "exact_mismatch"
            )
            public_item["comparison"] = comparison
            mismatch = mismatch or comparison == "exact_mismatch"
        else:
            extraction_failure = True
        public_evidence.append(public_item)

    if mismatch:
        status = "mismatch"
        reason = "at_least_one_exact_hypothesis_text_mismatch"
    elif canonical_text is None:
        status = "unverifiable"
        reason = "canonical_hypothesis_text_missing_or_invalid"
    elif link_issues:
        status = "unverifiable"
        reason = "wrapper_link_incomplete_or_ambiguous"
    elif extraction_failure:
        status = "unverifiable"
        reason = "target_tool_arguments_unverifiable"
    elif not stage_evidence:
        status = "unverifiable"
        reason = "no_structured_target_tool_call_in_exact_wrapper_records"
    else:
        status = "bound"
        reason = "all_extracted_hypothesis_text_values_exactly_match"

    return {
        "status": status,
        "reason": reason,
        "evidence": public_evidence,
    }


def audit_claim_bindings(
    loop_memory_path: str | Path,
    call_log_path: str | Path,
    *,
    loop_memory_bytes: int | None = None,
    call_log_bytes: int | None = None,
    expected_loop_memory_sha256: str | None = None,
    expected_call_log_sha256: str | None = None,
) -> dict[str, Any]:
    """Audit canonical LOOP hypotheses against their exact linked tool calls.

    The function only reads its inputs.  ``passed`` is true only when every
    required stage of every iteration is ``bound``.  One or more attributable
    calls per target stage are allowed across the exact linked wrapper records;
    every extracted value must match and every linked completion must be a
    valid tool-call array. Undecodable or non-array completions fail closed,
    including terminal prose without a verifiable envelope. Prefix replay
    requires both byte limits and both expected hashes.
    """

    prefix_values = (
        loop_memory_bytes,
        call_log_bytes,
        expected_loop_memory_sha256,
        expected_call_log_sha256,
    )
    if any(value is not None for value in prefix_values) and not all(
        value is not None for value in prefix_values
    ):
        raise ApparatusAuditInputError(
            "apparatus audit prefix replay requires both byte limits and both hashes"
        )

    loop_path = Path(loop_memory_path)
    calls_path = Path(call_log_path)
    loop_initial_fingerprint = _path_fingerprint(
        loop_path, "loop-memory", "snapshot capture"
    )
    call_initial_fingerprint = _path_fingerprint(
        calls_path, "call-log", "snapshot capture"
    )
    loop_rows, loop_source = _read_jsonl(
        loop_path,
        "loop-memory",
        byte_limit=loop_memory_bytes,
        expected_sha256=expected_loop_memory_sha256,
        initial_fingerprint=loop_initial_fingerprint,
    )
    if not loop_rows:
        raise ApparatusAuditInputError(f"loop-memory {loop_path} contains no records")

    iterations: list[dict[str, Any]] = []
    seen_iteration_ids: dict[str, int] = {}
    wrapper_owners: dict[str, list[str]] = defaultdict(list)
    for row in loop_rows:
        iteration = _canonical_iteration(row)
        iteration_id = iteration["iteration_id"]
        if iteration_id in seen_iteration_ids:
            raise ApparatusAuditInputError(
                f"duplicate iteration_id {iteration_id!r} at loop-memory rows "
                f"{seen_iteration_ids[iteration_id]} and {row.line}"
            )
        seen_iteration_ids[iteration_id] = row.line
        iterations.append(iteration)
        for request_id in dict.fromkeys(iteration["wrapper_call_ids"]):
            wrapper_owners[request_id].append(iteration_id)

    referenced_ids = set(wrapper_owners)

    def referenced_call(value: dict[str, Any]) -> bool:
        request_id = value.get("request_id")
        return isinstance(request_id, str) and request_id in referenced_ids

    call_rows, call_source = _read_jsonl(
        calls_path,
        "call-log",
        keep=referenced_call,
        byte_limit=call_log_bytes,
        expected_sha256=expected_call_log_sha256,
        initial_fingerprint=call_initial_fingerprint,
    )
    _require_same_fingerprint(
        loop_source["fingerprint"],
        _path_fingerprint(loop_path, "loop-memory", "after both reads"),
        loop_path,
        "loop-memory",
        "final post-read check",
    )
    _require_same_fingerprint(
        call_source["fingerprint"],
        _path_fingerprint(calls_path, "call-log", "after both reads"),
        calls_path,
        "call-log",
        "final post-read check",
    )
    calls_by_id: dict[str, list[_JsonlRow]] = defaultdict(list)
    for row in call_rows:
        calls_by_id[row.value["request_id"]].append(row)

    output_iterations: list[dict[str, Any]] = []
    stage_counts: Counter[str] = Counter()
    stage_counts_by_name: dict[str, Counter[str]] = {
        stage: Counter() for stage in DOWNSTREAM_STAGES
    }
    iteration_counts: Counter[str] = Counter()
    for iteration in iterations:
        iteration_id = iteration["iteration_id"]
        canonical_text = iteration["hypothesis_text"]
        link_issues = list(iteration["link_issues"])
        stage_evidence: dict[str, list[dict[str, Any]]] = {
            stage: [] for stage in DOWNSTREAM_STAGES
        }
        diagnostics: list[dict[str, Any]] = []

        ordered_request_ids = list(dict.fromkeys(iteration["wrapper_call_ids"]))
        for index, request_id in enumerate(ordered_request_ids):
            owners = wrapper_owners[request_id]
            if len(owners) > 1:
                link_issues.append(f"wrapper_call_id_shared:{request_id}")
            rows = calls_by_id.get(request_id, [])
            if not rows:
                link_issues.append(f"wrapper_call_id_missing:{request_id}")
                diagnostics.append({"request_id": request_id, "status": "missing"})
                continue
            if len(rows) > 1:
                link_issues.append(f"wrapper_call_id_duplicated_in_call_log:{request_id}")
                diagnostics.append(
                    {
                        "request_id": request_id,
                        "status": "duplicated_in_call_log",
                        "call_log_lines": [row.line for row in rows],
                        "call_record_sha256": [row.raw_sha256 for row in rows],
                    }
                )
                continue
            diagnostic, extracted = _tool_evidence(
                rows[0],
                request_id,
                iteration_id,
                (
                    iteration_id
                    if index == 0
                    else ordered_request_ids[index - 1]
                ),
            )
            diagnostics.append(diagnostic)
            if diagnostic["status"] == "run_id_missing_or_mismatch":
                link_issues.append(
                    f"wrapper_call_run_id_missing_or_mismatch:{request_id}"
                )
            elif diagnostic["status"] == "caller_tag_missing_or_mismatch":
                link_issues.append(
                    f"wrapper_call_caller_tag_missing_or_mismatch:{request_id}"
                )
            elif diagnostic["status"] == (
                "parent_request_id_missing_or_mismatch"
            ):
                link_issues.append(
                    "wrapper_call_parent_request_id_missing_or_mismatch:"
                    f"{request_id}"
                )
            elif diagnostic["status"] == "structured_json_array_ambiguous":
                link_issues.append(
                    f"wrapper_call_completion_ambiguous:{request_id}"
                )
            elif diagnostic["status"] != "structured_json_array":
                link_issues.append(
                    f"wrapper_call_completion_unverifiable:{request_id}"
                )
            for stage in DOWNSTREAM_STAGES:
                stage_evidence[stage].extend(extracted[stage])

        stages = {
            stage: _stage_result(stage_evidence[stage], canonical_text, link_issues)
            for stage in DOWNSTREAM_STAGES
        }
        for stage, result in stages.items():
            stage_counts[result["status"]] += 1
            stage_counts_by_name[stage][result["status"]] += 1
        statuses = {result["status"] for result in stages.values()}
        if "mismatch" in statuses:
            overall = "mismatch"
        elif "unverifiable" in statuses:
            overall = "unverifiable"
        else:
            overall = "bound"
        iteration_counts[overall] += 1

        output_iterations.append(
            {
                "iteration_id": iteration_id,
                "status": overall,
                "loop_memory_line": iteration["loop_memory_line"],
                "loop_memory_record_sha256": iteration[
                    "loop_memory_record_sha256"
                ],
                "canonical_hypothesis": (
                    {
                        "sha256": _digest_text(canonical_text),
                        "bytes": len(canonical_text.encode("utf-8")),
                    }
                    if canonical_text is not None
                    else None
                ),
                "wrapper_call_ids": iteration["wrapper_call_ids"],
                "link_issues": link_issues,
                "linked_call_diagnostics": diagnostics,
                "stages": stages,
            }
        )

    aggregate = {
        "iterations": len(output_iterations),
        "iteration_status": {
            status: iteration_counts[status]
            for status in ("bound", "mismatch", "unverifiable")
        },
        "stage_status": {
            status: stage_counts[status]
            for status in ("bound", "mismatch", "unverifiable")
        },
        "stage_status_by_name": {
            stage: {
                status: stage_counts_by_name[stage][status]
                for status in ("bound", "mismatch", "unverifiable")
            }
            for stage in DOWNSTREAM_STAGES
        },
    }
    passed = stage_counts["mismatch"] == 0 and stage_counts["unverifiable"] == 0
    return {
        "schema": AUDIT_SCHEMA,
        "classification": "observed",
        "audit": "exact_claim_wrapper_argument_binding",
        "policy": {
            "authority_effect": "none",
            "source_authentication": (
                "not_provided; pass proves consistency of caller-selected inputs only"
            ),
            "join": "exact_wrapper_call_ids_with_run_and_parent_chain",
            "required_caller_tag": EXPECTED_CALLER_TAG,
            "run_identity": "call_run_id_must_equal_iteration_id",
            "completion_format": "json_array_tool_calls_only",
            "linked_completion_policy": "every_link_requires_valid_tool_call_array",
            "tool_envelope": "nonempty_id_and_type_function_required",
            "comparison": "exact_unicode_string_equality",
            "target_stage_cardinality": (
                "one_or_more_attributable_calls; every extracted value must match"
            ),
            "dispatch_or_execution_proof": False,
            "unverifiable_is_failure": True,
            "exit_codes": {
                "all_bound": 0,
                "mismatch_or_unverifiable": 1,
                "malformed_input": 2,
            },
        },
        "sources": {
            "loop_memory": loop_source,
            "call_log": call_source,
        },
        "aggregate": aggregate,
        "passed": passed,
        "iterations": output_iterations,
    }
