"""Source-bound research priority, separate from study or execution authority.

A focus is an immutable selection receipt plus an atomic pointer. It
can stop discovery churn, but cannot register an experiment or earn a rung. Selection
authority is D-084 section 4.1: Oracle selects after a meta review, by CLI, not by a
hand-written receipt.
Historical seeds retain their source quality and campaign instead of appearing
as new-campaign findings. No model, network, or scientific-ledger writes here.

A focus ends through an immutable closure receipt (D-084): `killed` or
`graduated`, with its reason, reopening conditions, evidence and authority. The
closure is written first and the pointer removed second, so a closed focus reads
as "none" (the intake hold lifts) while both receipts stay as negative knowledge.
"""

from __future__ import annotations

import argparse
import base64
import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from orchestrator import oracle_mailbox

SCHEMA = "research-focus/v1"
THESIS_SCHEMA = "research-focus/v2"
POINTER = "run_state/active_research_focus.json"
DIRECTORY = "run_state/research_focus"
CONVICTION_SCHEMA = "thesis-conviction/v1"
CONVICTION_LEDGER = "run_state/thesis_convictions.jsonl"
PREPARED = f"{DIRECTORY}/prepared"
PREPARED_SCHEMA = "research-focus-prepared/v1"
MAX_FOCUS_RECEIPT_BYTES = 16 * 1024
MAX_PREPARED_BYTES = 128 * 1024
MAX_PREPARED_FILES = 64
MAX_CONVICTION_LEDGER_BYTES = 2 * 1024 * 1024
SHA = re.compile(r"[0-9a-f]{64}\Z")
IDENTITY = re.compile(r"[a-z0-9][a-z0-9-]{2,95}\Z")
STAGES = {"needs_clean_refinement", "blocked"}
CLOSURE_SCHEMA = "research-focus-closure/v2"
LEGACY_CLOSURE_SCHEMA = "research-focus-closure/v1"
CLOSURES = f"{DIRECTORY}/closures"
DISPOSITIONS = {"killed", "graduated"}  # terminal focus states (D-084)
MAX_CLOSURE_FILES = 64
FIELDS = {
    "schema_version",
    "focus_id",
    "title",
    "source_iteration_id",
    "source_record_ordinal",
    "source_row_sha256",
    "source_campaign_id",
    "source_campaign_manifest_sha256",
    "selected_at",
    "selected_by",
    "selection_reason",
    "selection_authority",
    "stage",
    "next_action",
    "next_gate",
    "blockers",
    "intake_policy",
    "execution_authorized",
}

# v2 is deliberately source-agnostic: a Nara candidate set and an Oracle screen
# are receipts in their own right, rather than a synthetic loop-memory row.  This
# keeps thesis selection from minting research observations.
THESIS_FIELDS = {
    "schema_version",
    "focus_id",
    "title",
    "candidate_set_sha256",
    "screen_sha256",
    "meta_accept_sha256",
    "review_msg_id",
    "review_row_sha256",
    "proposal_msg_id",
    "proposal_row_sha256",
    "chosen_candidate_id",
    "selection_head",
    "selected_at",
    "selected_by",
    "selection_reason",
    "stage",
    "next_action",
    "next_gate",
    "blockers",
    "intake_policy",
    "execution_authorized",
    "scientific_credit",
    "mailbox_cutoff_seq",
    "mailbox_cutoff_sha256",
    "focus_generation",
    "initial_conviction_rows",
}


class FocusError(ValueError):
    pass


def canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def _object(raw: bytes) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise FocusError("duplicate JSON key")
            result[key] = value
        return result

    def invalid(_value):
        raise FocusError("non-finite JSON value")

    value = json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)
    if not isinstance(value, dict):
        raise FocusError("expected JSON object")
    return value


def _read(root: Path, relative: str, maximum: int) -> bytes:
    """Read one stable regular file without following any path component."""
    path = Path(relative)
    parts = path.parts
    if (
        path.is_absolute()
        or not parts
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise FocusError("invalid focus source path")
    opened: list[int] = []
    try:
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        opened.append(directory)
        for part in parts[:-1]:
            directory = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=directory,
            )
            opened.append(directory)
        fd = os.open(
            parts[-1],
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=directory,
        )
        opened.append(fd)
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise FocusError("non-regular focus source")
        if before.st_size > maximum:
            raise FocusError("focus source exceeds read bound")
        chunks: list[bytes] = []
        remaining = maximum + 1
        while remaining:
            chunk = os.read(fd, min(remaining, 1_048_576))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(fd)
        before_identity = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        after_identity = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        if len(raw) > maximum:
            raise FocusError("focus source exceeds read bound")
        if len(raw) != before.st_size or before_identity != after_identity:
            raise FocusError("focus source changed during read")
        return raw
    finally:
        for fd in reversed(opened):
            os.close(fd)


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _fsync_directory_chain(root: Path, directory: Path) -> None:
    """Durably establish every newly-created directory edge below ``root``."""
    try:
        parts = directory.relative_to(root).parts
    except ValueError as exc:
        raise FocusError("focus directory escapes repository") from exc
    parent = root
    for part in parts:
        child = parent / part
        _fsync_directory(parent)
        _fsync_directory(child)
        parent = child


def _fsync_file(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _source(root: Path, iteration_id: str) -> tuple[dict, dict, bytes, int]:
    from orchestrator.research_campaign import load_campaign, record_matches

    raw = _read(root, "memory/loop_memory.jsonl", 16 * 1024 * 1024)
    if raw and not raw.endswith(b"\n"):
        raise FocusError("incomplete research ledger tail")
    lines = raw[:-1].split(b"\n") if raw else []
    records = [(_object(line), line) for line in lines if line.strip()]
    matches = [
        (ordinal, row, line)
        for ordinal, (row, line) in enumerate(records, start=1)
        if row.get("iteration_id") == iteration_id
    ]
    if len(matches) != 1:
        raise FocusError("focus source identity is missing or ambiguous")
    ordinal, row, raw_line = matches[0]
    link = row.get("campaign")
    if not isinstance(link, dict) or not isinstance(link.get("campaign_id"), str):
        raise FocusError("focus source has no explicit campaign")
    campaign = load_campaign(link["campaign_id"], repo_root=root)
    if not record_matches(row, campaign):
        raise FocusError("focus source campaign binding differs")
    return row, campaign, raw_line, ordinal


def _validate(receipt: dict, root: Path) -> dict:
    if set(receipt) != FIELDS or receipt["schema_version"] != SCHEMA:
        raise FocusError("unsupported focus receipt")
    if not IDENTITY.fullmatch(str(receipt["focus_id"])):
        raise FocusError("invalid focus identity")
    bounds = {
        "title": 180,
        "source_iteration_id": 120,
        "selected_by": 120,
        "selection_reason": 1800,
        "selection_authority": 240,
        "next_action": 900,
    }
    for key, maximum in bounds.items():
        value = receipt[key]
        if not isinstance(value, str) or not value.strip() or len(value) > maximum:
            raise FocusError(f"invalid {key}")
    if receipt["stage"] not in STAGES:
        raise FocusError("unknown focus stage")
    if receipt["intake_policy"] not in {"focus_before_new_topics", "observe_only"}:
        raise FocusError("invalid focus intake policy")
    if receipt["execution_authorized"] is not False:
        raise FocusError("a focus cannot authorize execution")
    selected = datetime.fromisoformat(receipt["selected_at"].replace("Z", "+00:00"))
    if selected.tzinfo is None or selected > datetime.now(timezone.utc):
        raise FocusError("invalid focus timestamp")
    blockers = receipt["blockers"]
    if (
        not isinstance(blockers, list)
        or len(blockers) > 12
        or any(
            not isinstance(item, str) or not item.strip() or len(item) > 600
            for item in blockers
        )
    ):
        raise FocusError("invalid focus blockers")
    gate = receipt["next_gate"]
    if (
        not isinstance(gate, dict)
        or set(gate) != {"from", "to", "artifact", "status", "owner"}
        or any(
            not isinstance(value, str) or not value.strip() or len(value) > 400
            for value in gate.values()
        )
        or len(gate["from"]) > 80
        or len(gate["to"]) > 80
        or gate["status"] not in {"pending", "blocked"}
    ):
        raise FocusError("invalid next gate")
    ordinal = receipt["source_record_ordinal"]
    if isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal < 1:
        raise FocusError("invalid focus source ordinal")
    row, campaign, raw_line, actual_ordinal = _source(
        root, receipt["source_iteration_id"]
    )
    if (
        receipt["source_row_sha256"] != hashlib.sha256(raw_line).hexdigest()
        or ordinal != actual_ordinal
        or receipt["source_campaign_id"] != campaign["campaign_id"]
        or receipt["source_campaign_manifest_sha256"] != campaign["_manifest_sha256"]
    ):
        raise FocusError("focus source hash or campaign changed")
    return row


def _validate_thesis(receipt: dict) -> None:
    """Validate the bounded v2 selection receipt without granting execution."""
    if set(receipt) != THESIS_FIELDS or receipt.get("schema_version") != THESIS_SCHEMA:
        raise FocusError("unsupported thesis focus receipt")
    for key, maximum in {
        "focus_id": 96,
        "title": 180,
        "chosen_candidate_id": 96,
        "selected_by": 120,
        "selection_reason": 1800,
        "next_action": 900,
    }.items():
        value = receipt.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > maximum:
            raise FocusError(f"invalid {key}")
    if not IDENTITY.fullmatch(receipt["focus_id"]):
        raise FocusError("invalid thesis focus identity")
    if not IDENTITY.fullmatch(receipt["chosen_candidate_id"]):
        raise FocusError("invalid thesis candidate identity")
    for key in ("candidate_set_sha256", "screen_sha256", "meta_accept_sha256"):
        if not isinstance(receipt.get(key), str) or not SHA.fullmatch(receipt[key]):
            raise FocusError(f"invalid {key}")
    for key in ("review_msg_id", "proposal_msg_id"):
        value = receipt.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > 160:
            raise FocusError(f"invalid {key}")
    for key in ("review_row_sha256", "proposal_row_sha256"):
        if not isinstance(receipt.get(key), str) or not SHA.fullmatch(receipt[key]):
            raise FocusError(f"invalid {key}")
    if not isinstance(receipt.get("selection_head"), str) or not re.fullmatch(
        r"[0-9a-f]{40}", receipt["selection_head"]
    ):
        raise FocusError("invalid selection head")
    if receipt.get("selected_by") != "oracle":
        raise FocusError("thesis selection must be made by oracle")
    if receipt.get("stage") not in STAGES:
        raise FocusError("unknown focus stage")
    if receipt.get("intake_policy") not in {"focus_before_new_topics", "observe_only"}:
        raise FocusError("invalid focus intake policy")
    if receipt.get("execution_authorized") is not False:
        raise FocusError("a focus cannot authorize execution")
    if receipt.get("scientific_credit") != "none_selection_only":
        raise FocusError("selection cannot earn scientific credit")
    if type(receipt.get("mailbox_cutoff_seq")) is not int or receipt["mailbox_cutoff_seq"] < 1:
        raise FocusError("invalid mailbox cutoff sequence")
    if not isinstance(receipt.get("mailbox_cutoff_sha256"), str) or not SHA.fullmatch(receipt["mailbox_cutoff_sha256"]):
        raise FocusError("invalid mailbox cutoff hash")
    _validate_generation(receipt.get("focus_generation"))
    rows = receipt.get("initial_conviction_rows")
    if not isinstance(rows, list) or len(rows) != 3:
        raise FocusError("invalid initial conviction rows")
    forecasters = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"forecaster", "row_sha256"}:
            raise FocusError("invalid initial conviction row")
        if row["forecaster"] not in {"nara", "oracle", "claude"}:
            raise FocusError("invalid initial conviction forecaster")
        forecasters.add(row["forecaster"])
        if not isinstance(row["row_sha256"], str) or not SHA.fullmatch(row["row_sha256"]):
            raise FocusError("invalid initial conviction hash")
    if forecasters != {"nara", "oracle", "claude"} or [row["forecaster"] for row in rows] != ["nara", "oracle", "claude"]:
        raise FocusError("initial conviction forecast coverage differs")
    selected = datetime.fromisoformat(receipt["selected_at"].replace("Z", "+00:00"))
    if selected.tzinfo is None or selected > datetime.now(timezone.utc):
        raise FocusError("invalid focus timestamp")
    blockers = receipt.get("blockers")
    if not isinstance(blockers, list) or len(blockers) > 12 or any(
        not isinstance(item, str) or not item.strip() or len(item) > 600
        for item in blockers
    ):
        raise FocusError("invalid focus blockers")
    gate = receipt.get("next_gate")
    if not isinstance(gate, dict) or set(gate) != {"from", "to", "artifact", "status", "owner"}:
        raise FocusError("invalid next gate")
    if any(not isinstance(value, str) or not value.strip() or len(value) > 400 for value in gate.values()):
        raise FocusError("invalid next gate")
    if gate["status"] not in {"pending", "blocked"}:
        raise FocusError("invalid next gate")
    if len(canonical(receipt) + b"\n") > MAX_FOCUS_RECEIPT_BYTES:
        raise FocusError("thesis focus receipt exceeds projection bound")


def _validate_generation(value: object) -> dict:
    """A focus generation prevents the empty-pointer ABA after a closure."""
    if not isinstance(value, dict) or set(value) != {"active_receipt_sha256", "last_closure_sha256"}:
        raise FocusError("invalid focus generation")
    for key in ("active_receipt_sha256", "last_closure_sha256"):
        item = value[key]
        if item is not None and (not isinstance(item, str) or not SHA.fullmatch(item)):
            raise FocusError("invalid focus generation")
    if value["active_receipt_sha256"] is not None and value["last_closure_sha256"] is not None:
        raise FocusError("ambiguous focus generation")
    return value


def selection_generation(repo_root: Path) -> dict:
    """The stable generation used by a reviewed v2 selection proposal."""
    current = project_focus(Path(repo_root))
    if current.get("status") == "source_invalid":
        raise FocusError("repair invalid focus explicitly before selection")
    active = current.get("receipt_sha256") if current.get("status") == "selected" else None
    closure = current.get("last_closure", {}).get("closure_sha256") if current.get("status") == "none" else None
    generation = {"active_receipt_sha256": active, "last_closure_sha256": closure}
    return _validate_generation(generation)


def _selected_thesis_projection(receipt: dict, sha: str) -> dict:
    return {
        **receipt, "status": "selected", "receipt_sha256": sha,
        "source_evidence_level": None, "source_quality": "thesis_candidate_screen",
        "evidence_refs": [
            {"kind": "nara_candidate_set", "sha256": receipt["candidate_set_sha256"]},
            {"kind": "oracle_screen", "sha256": receipt["screen_sha256"]},
            {"kind": "meta_accept", "sha256": receipt["meta_accept_sha256"]},
            {"kind": "oracle_proposal", "msg_id": receipt["proposal_msg_id"], "row_sha256": receipt["proposal_row_sha256"]},
            {"kind": "meta_review", "msg_id": receipt["review_msg_id"], "row_sha256": receipt["review_row_sha256"]},
        ],
    }


def _prepared_focus_state(root: Path) -> dict:
    """Pointer/closure CAS state without re-projecting mutable mailbox evidence."""
    try:
        raw = _read(root, POINTER, 4096)
    except FileNotFoundError:
        closure = _closure_tip(_closures(root))
        return {"status": "none", "receipt_sha256": None,
                "generation": {"active_receipt_sha256": None,
                               "last_closure_sha256": closure["closure_sha256"] if closure else None}}
    pointer = _object(raw)
    if (set(pointer) != {"schema_version", "receipt_sha256"}
            or pointer.get("schema_version") not in {SCHEMA, THESIS_SCHEMA}
            or not isinstance(pointer.get("receipt_sha256"), str)
            or not SHA.fullmatch(pointer["receipt_sha256"])):
        raise FocusError("invalid focus pointer")
    return {"status": "selected", "receipt_sha256": pointer["receipt_sha256"],
            "generation": {"active_receipt_sha256": pointer["receipt_sha256"], "last_closure_sha256": None}}


def _write_all(fd: int, payload: bytes) -> None:
    """Finish a short write or leave a prefix that the prepared transaction resumes."""
    offset = 0
    while offset < len(payload):
        written = os.write(fd, payload[offset:])
        if not isinstance(written, int) or written <= 0:
            raise FocusError("conviction ledger write made no progress")
        offset += written


def _atomic_immutable_write(directory: Path, target: Path, raw: bytes, *, existing: Callable[[], bytes]) -> None:
    """Fsync bytes before atomically naming an immutable receipt.

    A content-addressed name is part of the integrity contract.  Never write
    directly to it: a power loss after a short write would otherwise turn the
    name into a permanent collision.  A crash may leave a private ``.tmp``
    inode, but it was never reachable through the receipt name.
    """
    temporary: Path | None = None
    for _attempt in range(3):
        candidate = directory / f".immutable-{os.getpid()}-{secrets.token_hex(8)}.tmp"
        try:
            fd = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            continue
        try:
            _write_all(fd, raw)
            os.fsync(fd)
        except BaseException:
            os.close(fd)
            try:
                candidate.unlink()
            except FileNotFoundError:
                pass
            raise
        else:
            os.close(fd)
            temporary = candidate
            break
    if temporary is None:
        raise FocusError("could not allocate immutable focus receipt")
    try:
        os.link(temporary, target, follow_symlinks=False)
        _fsync_directory(directory)
    except FileExistsError:
        if existing() != raw:
            raise FocusError("immutable focus receipt collision")
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    # Persist both the final name and removal of the private staging inode.
    _fsync_directory(directory)


def _prepared_directory(root: Path) -> Path:
    directory = root / PREPARED
    directory.mkdir(parents=True, exist_ok=True)
    if directory.resolve() != directory or not directory.is_dir():
        raise FocusError("redirected prepared thesis directory")
    # The prepared directory must itself be durable before the selection can
    # append convictions: otherwise a power loss could preserve the ledger but
    # lose the only reachable recovery journal.  Walk to the repository root
    # too: this may be the first creation of run_state/research_focus.
    _fsync_directory_chain(root, directory)
    return directory


_D087_ROW_FIELDS = {
    "thesis", "forecaster", "at", "p_pass_T", "p_pass_S", "p_pass_A",
    "p_dead_end", "interest_0_10", "reasons", "trigger",
}
_D087_REASON_FIELDS = {
    "p_pass_t", "p_pass_s", "p_pass_a", "p_dead_end", "interest_0_10",
}


def _validate_d087_row(receipt: dict, ref: dict, raw: bytes) -> None:
    """Require a receipt-referenced row to be an exact canonical D-087 record."""
    if hashlib.sha256(raw).hexdigest() != ref["row_sha256"]:
        raise FocusError("initial conviction row hash differs")
    try:
        row = _object(raw)
    except (TypeError, ValueError, UnicodeError) as exc:
        raise FocusError("initial conviction row is not canonical D-087") from exc
    if canonical(row) != raw or set(row) != _D087_ROW_FIELDS:
        raise FocusError("initial conviction row is not canonical D-087")
    if (row["thesis"] != receipt["focus_id"] or row["forecaster"] != ref["forecaster"]
            or row["at"] != receipt["selected_at"] or row["trigger"] != "selection"):
        raise FocusError("initial conviction row differs from thesis focus")
    for key in ("p_pass_T", "p_pass_S", "p_pass_A", "p_dead_end"):
        value = row[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
            raise FocusError("invalid D-087 probability")
    interest = row["interest_0_10"]
    if isinstance(interest, bool) or not isinstance(interest, (int, float)) or not 0 <= interest <= 10:
        raise FocusError("invalid D-087 interest")
    reasons = row["reasons"]
    if not isinstance(reasons, dict) or set(reasons) != _D087_REASON_FIELDS:
        raise FocusError("D-087 reasons must cover every forecast")
    for reason in reasons.values():
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 1200:
            raise FocusError("invalid D-087 reason")


def _validate_prepared_append(receipt: dict, append: bytes) -> None:
    """Prepared bytes are either no-op recovery or exactly the three receipt rows."""
    if not append:
        return
    if not append.endswith(b"\n"):
        raise FocusError("prepared ledger append is incomplete")
    rows = append[:-1].split(b"\n")
    refs = receipt["initial_conviction_rows"]
    if len(rows) != 3:
        raise FocusError("prepared ledger append must contain three D-087 rows")
    for raw, ref in zip(rows, refs):
        _validate_d087_row(receipt, ref, raw)


def _pending_conviction_append(prefix: bytes, rows: dict) -> bytes:
    """Return the all-or-none three-row append for one reviewed selection."""
    if prefix and not prefix.endswith(b"\n"):
        raise FocusError("incomplete conviction ledger tail")
    existing_hashes = {
        hashlib.sha256(line).hexdigest() for line in prefix.splitlines() if line
    }
    found = [
        name for name in ("nara", "oracle", "claude")
        if rows[name][2] in existing_hashes
    ]
    if found and len(found) != 3:
        raise FocusError("partial initial conviction rows require prepared recovery")
    return b"" if found else b"".join(
        rows[name][1] for name in ("nara", "oracle", "claude")
    )


def _require_conviction_capacity(prefix_bytes: int, append: bytes) -> None:
    """Bound the completed ledger, not merely the prefix already on disk."""
    if prefix_bytes + len(append) > MAX_CONVICTION_LEDGER_BYTES:
        raise FocusError("initial convictions would exceed conviction ledger bound")


def _prepared_value(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != {
        "schema_version", "receipt_sha256", "receipt", "expected_previous_sha256",
        "focus_generation", "ledger_prefix_bytes", "ledger_prefix_sha256",
        "ledger_append_b64", "ledger_append_sha256",
    } or value.get("schema_version") != PREPARED_SCHEMA:
        raise FocusError("invalid prepared thesis transaction")
    receipt = value["receipt"]
    _validate_thesis(receipt)
    raw = canonical(receipt) + b"\n"
    if value["receipt_sha256"] != hashlib.sha256(raw).hexdigest():
        raise FocusError("prepared thesis receipt hash differs")
    previous = value["expected_previous_sha256"]
    if previous is not None and (not isinstance(previous, str) or not SHA.fullmatch(previous)):
        raise FocusError("invalid prepared previous focus")
    if value["focus_generation"] != receipt["focus_generation"]:
        raise FocusError("prepared focus generation differs")
    _validate_generation(value["focus_generation"])
    if type(value["ledger_prefix_bytes"]) is not int or not 0 <= value["ledger_prefix_bytes"] <= MAX_CONVICTION_LEDGER_BYTES:
        raise FocusError("invalid prepared ledger prefix")
    if not isinstance(value["ledger_prefix_sha256"], str) or not SHA.fullmatch(value["ledger_prefix_sha256"]):
        raise FocusError("invalid prepared ledger prefix hash")
    if not isinstance(value["ledger_append_sha256"], str) or not SHA.fullmatch(value["ledger_append_sha256"]):
        raise FocusError("invalid prepared ledger append hash")
    try:
        append = base64.b64decode(value["ledger_append_b64"], validate=True)
    except (TypeError, ValueError) as exc:
        raise FocusError("invalid prepared ledger append") from exc
    if hashlib.sha256(append).hexdigest() != value["ledger_append_sha256"] or len(append) > 64 * 1024:
        raise FocusError("prepared ledger append differs")
    _validate_prepared_append(receipt, append)
    _require_conviction_capacity(value["ledger_prefix_bytes"], append)
    return value


def _load_prepared(root: Path, sha: str) -> dict:
    raw = _read(root, f"{PREPARED}/{sha}.json", MAX_PREPARED_BYTES)
    decoded = _object(raw)
    if canonical(decoded) + b"\n" != raw:
        # Prepared JSON is named by its receipt, not by its own digest; require
        # canonical bytes so the frozen transaction itself remains exact.
        raise FocusError("prepared thesis transaction is non-canonical")
    value = _prepared_value(decoded)
    if value["receipt_sha256"] != sha:
        raise FocusError("prepared thesis filename differs")
    return value


def _prepared_transactions(root: Path) -> list[dict]:
    """Load the entire bounded prepared journal before making any new decision."""
    directory = root / PREPARED
    if not directory.exists():
        return []
    if directory.is_symlink() or not directory.is_dir():
        raise FocusError("redirected prepared thesis directory")
    names: list[str] = []
    with os.scandir(directory) as entries:
        for entry in entries:
            if entry.name.startswith(".immutable-") and entry.name.endswith(".tmp"):
                continue
            if len(names) >= MAX_PREPARED_FILES:
                raise FocusError("prepared thesis scan exceeds file bound")
            if (not entry.is_file(follow_symlinks=False) or not entry.name.endswith(".json")
                    or not SHA.fullmatch(entry.name[:-5])):
                raise FocusError("invalid prepared thesis journal entry")
            names.append(entry.name[:-5])
    return [_load_prepared(root, name) for name in sorted(names)]


def find_prepared_thesis_focus(repo_root: Path, *, meta_accept_sha256: str) -> dict | None:
    """Find the one frozen transaction for a retry without reading the mailbox."""
    root = Path(repo_root).resolve()
    matches = [value for value in _prepared_transactions(root)
               if value["receipt"]["meta_accept_sha256"] == meta_accept_sha256]
    if len(matches) > 1:
        raise FocusError("ambiguous prepared thesis transaction")
    return matches[0] if matches else None


def _prepared_receipt_exists(root: Path, prepared: dict) -> bool:
    """A receipt retained after its closure is history, not a pending transaction."""
    sha = prepared["receipt_sha256"]
    try:
        return _read(root, f"{DIRECTORY}/{sha}.json", MAX_FOCUS_RECEIPT_BYTES) == canonical(prepared["receipt"]) + b"\n"
    except FileNotFoundError:
        return False


def pending_prepared_thesis_focuses(repo_root: Path) -> list[dict]:
    """Classify every prepared transaction, refusing stale or competing journals.

    A prepared receipt is retained as audit history.  It is pending only while the
    pointer still has the generation that it was prepared to claim.  A closure
    bound to the durable receipt makes it completed history instead.
    """
    root = Path(repo_root).resolve()
    current = _prepared_focus_state(root)
    closed = {item.get("focus_receipt_sha256") for item in _closures(root)}
    pending: list[dict] = []
    for prepared in _prepared_transactions(root):
        sha = prepared["receipt_sha256"]
        if current["status"] == "selected" and current["receipt_sha256"] == sha:
            continue
        if sha in closed and _prepared_receipt_exists(root, prepared):
            continue
        if current["status"] == "none" and current["generation"] == prepared["focus_generation"]:
            pending.append(prepared)
            continue
        raise FocusError("prepared thesis transaction conflicts with current focus state")
    if len(pending) > 1:
        raise FocusError("ambiguous pending prepared thesis transactions")
    return pending


def prepare_thesis_focus(
    repo_root: Path, receipt: dict, *, expected_previous_sha256: str | None,
    expected_generation: dict, initial_convictions: dict,
) -> dict:
    """Durably freeze a verified selection before touching ledger, receipt, or pointer."""
    _validate_thesis(receipt)
    _validate_generation(expected_generation)
    if receipt["focus_generation"] != expected_generation:
        raise FocusError("thesis focus receipt generation differs from review")
    if not isinstance(initial_convictions, dict) or set(initial_convictions) != {"nara", "oracle", "claude"}:
        raise FocusError("thesis focus install needs initial convictions")
    root = Path(repo_root).resolve()
    receipt_raw = canonical(receipt) + b"\n"
    receipt_sha = hashlib.sha256(receipt_raw).hexdigest()
    rows = _initial_conviction_rows(receipt["focus_id"], receipt["selected_at"], initial_convictions)
    refs = [{"forecaster": name, "row_sha256": rows[name][2]} for name in ("nara", "oracle", "claude")]
    if receipt["initial_conviction_rows"] != refs:
        raise FocusError("initial conviction receipt references differ from forecasts")

    # A retry may arrive after the journal was made durable and the ledger
    # append started.  The journal is the recovery authority in that case;
    # return it before a read-only preflight mistakes its partial suffix for a
    # fresh, unjournaled mutation.
    existing_preflight = find_prepared_thesis_focus(
        root, meta_accept_sha256=receipt["meta_accept_sha256"],
    )
    if existing_preflight is not None:
        if existing_preflight["receipt_sha256"] != receipt_sha:
            raise FocusError("meta review already has a different prepared focus")
        return existing_preflight

    # A deterministic over-capacity request is rejected before creating the
    # focus directory, lock files, prepared journal, receipt, or pointer.  The
    # same calculation is repeated under both transaction locks below so a
    # concurrent ledger append cannot turn this preflight into authority.
    try:
        preflight_prefix = _read(root, CONVICTION_LEDGER, MAX_CONVICTION_LEDGER_BYTES)
    except FileNotFoundError:
        preflight_prefix = b""
    preflight_append = _pending_conviction_append(preflight_prefix, rows)
    _require_conviction_capacity(len(preflight_prefix), preflight_append)

    directory = root / DIRECTORY
    directory.mkdir(parents=True, exist_ok=True)
    if directory.resolve() != directory or not directory.is_dir():
        raise FocusError("redirected focus directory")
    _fsync_directory_chain(root, directory)
    lock_fd = os.open(directory / ".selection.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_fd, "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        existing = find_prepared_thesis_focus(root, meta_accept_sha256=receipt["meta_accept_sha256"])
        if existing is not None:
            if existing["receipt_sha256"] != receipt_sha:
                raise FocusError("meta review already has a different prepared focus")
            return existing
        # Do this while holding the selection lock as well as at the public
        # selection entry point: concurrent selectors may both have observed an
        # empty journal before either had frozen its receipt.
        if pending_prepared_thesis_focuses(root):
            raise FocusError("pending prepared thesis transaction must recover before a new selection")
        current = _prepared_focus_state(root)
        if current["status"] != "none" or current["receipt_sha256"] != expected_previous_sha256:
            raise FocusError("focus changed since oracle review")
        if current["generation"] != expected_generation:
            raise FocusError("focus generation changed since oracle review")
        state = root / "run_state"
        state.mkdir(exist_ok=True)
        conviction_fd = os.open(state / ".thesis-convictions.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(conviction_fd, "a") as convictions_lock:
            fcntl.flock(convictions_lock, fcntl.LOCK_EX)
            try:
                prefix = _read(root, CONVICTION_LEDGER, MAX_CONVICTION_LEDGER_BYTES)
            except FileNotFoundError:
                prefix = b""
            append = _pending_conviction_append(prefix, rows)
            _require_conviction_capacity(len(prefix), append)
            prepared = {
                "schema_version": PREPARED_SCHEMA, "receipt_sha256": receipt_sha,
                "receipt": receipt, "expected_previous_sha256": expected_previous_sha256,
                "focus_generation": expected_generation, "ledger_prefix_bytes": len(prefix),
                "ledger_prefix_sha256": hashlib.sha256(prefix).hexdigest(),
                "ledger_append_b64": base64.b64encode(append).decode("ascii"),
                "ledger_append_sha256": hashlib.sha256(append).hexdigest(),
            }
            prepared_raw = canonical(prepared) + b"\n"
            if len(prepared_raw) > MAX_PREPARED_BYTES:
                raise FocusError("prepared thesis transaction exceeds read bound")
            prepared_dir = _prepared_directory(root)
            target = prepared_dir / f"{receipt_sha}.json"
            _atomic_immutable_write(
                prepared_dir, target, prepared_raw,
                existing=lambda: _read(root, f"{PREPARED}/{receipt_sha}.json", MAX_PREPARED_BYTES),
            )
            return prepared


def _publish_pointer_no_clobber(root: Path, directory: Path, pointer_raw: bytes) -> None:
    """Publish an already-fsynced pointer by an atomic create, never replace."""
    target = root / POINTER
    temporary = None
    for _attempt in range(3):
        candidate = directory / f".pointer-{os.getpid()}-{secrets.token_hex(8)}.tmp"
        try:
            with candidate.open("xb") as stream:
                stream.write(pointer_raw)
                stream.flush()
                os.fsync(stream.fileno())
            temporary = candidate
            break
        except FileExistsError:
            continue
    if temporary is None:
        raise FocusError("could not allocate thesis focus pointer")
    try:
        # link(2) creates the destination atomically and fails with EEXIST;
        # unlike replace(2), it cannot clobber a focus published by another
        # process that does not honor our advisory lock.
        os.link(temporary, target, follow_symlinks=False)
        _fsync_directory(target.parent)
    except FileExistsError as exc:
        raise FocusError("refuse to overwrite an active focus; close it first") from exc
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    _fsync_directory(directory)


def _fence_selected_thesis_durability(root: Path, directory: Path, receipt: dict) -> None:
    """Make every acknowledged selection edge durable before returning success."""
    verify_initial_convictions(root, receipt)
    _fsync_file(root / CONVICTION_LEDGER)
    _fsync_directory((root / CONVICTION_LEDGER).parent)
    _fsync_directory(directory)
    _fsync_directory((root / POINTER).parent)


def commit_prepared_thesis_focus(repo_root: Path, prepared: dict) -> dict:
    """Finish only the exact durable transaction; it never re-admits mailbox rows."""
    if not isinstance(prepared, dict):
        raise FocusError("invalid prepared thesis transaction")
    claimed_sha = prepared.get("receipt_sha256")
    if not isinstance(claimed_sha, str) or not SHA.fullmatch(claimed_sha):
        raise FocusError("invalid prepared thesis receipt hash")
    root = Path(repo_root).resolve()
    directory = root / DIRECTORY
    lock_fd = os.open(directory / ".selection.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_fd, "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # The invocation object is only an untrusted retry hint.  Bind it to
        # the exact fsynced journal entry while holding the transaction lock;
        # no fabricated in-memory receipt may append convictions or select.
        durable = _load_prepared(root, claimed_sha)
        if canonical(_prepared_value(prepared)) + b"\n" != canonical(durable) + b"\n":
            raise FocusError("prepared thesis transaction differs from durable journal")
        prepared = durable
        receipt = prepared["receipt"]
        sha = prepared["receipt_sha256"]
        pending = pending_prepared_thesis_focuses(root)
        if any(item["receipt_sha256"] != sha for item in pending):
            raise FocusError("pending prepared thesis transaction must recover before a new selection")
        current = _prepared_focus_state(root)
        if current["status"] == "selected":
            if current["receipt_sha256"] == sha:
                if _read(root, f"{DIRECTORY}/{sha}.json", MAX_FOCUS_RECEIPT_BYTES) != canonical(receipt) + b"\n":
                    raise FocusError("active focus receipt differs from prepared transaction")
                _fence_selected_thesis_durability(root, directory, receipt)
                return _selected_thesis_projection(receipt, sha)
            raise FocusError("refuse to overwrite an active focus; close it first")
        if (current["receipt_sha256"] != prepared["expected_previous_sha256"]
                or current["generation"] != prepared["focus_generation"]):
            raise FocusError("focus generation changed since prepared selection")
        state = root / "run_state"
        state.mkdir(exist_ok=True)
        conviction_fd = os.open(state / ".thesis-convictions.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(conviction_fd, "a") as convictions_lock:
            fcntl.flock(convictions_lock, fcntl.LOCK_EX)
            try:
                ledger = _read(root, CONVICTION_LEDGER, MAX_CONVICTION_LEDGER_BYTES)
            except FileNotFoundError:
                ledger = b""
            prefix_bytes = prepared["ledger_prefix_bytes"]
            append = base64.b64decode(prepared["ledger_append_b64"], validate=True)
            if (len(ledger) < prefix_bytes
                    or hashlib.sha256(ledger[:prefix_bytes]).hexdigest() != prepared["ledger_prefix_sha256"]):
                raise FocusError("conviction ledger differs from prepared transaction")
            suffix = ledger[prefix_bytes:]
            if not append.startswith(suffix):
                raise FocusError("conviction ledger tail differs from prepared transaction")
            _require_conviction_capacity(len(ledger), append[len(suffix):])
            append_fd = os.open(root / CONVICTION_LEDGER, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
            try:
                if len(suffix) < len(append):
                    _write_all(append_fd, append[len(suffix):])
                # A full write that raised after reaching disk has suffix ==
                # append on retry.  It still needs this durability fence.
                os.fsync(append_fd)
            finally:
                os.close(append_fd)
            _fsync_directory((root / CONVICTION_LEDGER).parent)
            # The receipt hash alone is not enough: prove that the durable
            # ledger contains its exact three canonical D-087 records before
            # publishing the pointer.
            verify_initial_convictions(root, receipt)
        raw = canonical(receipt) + b"\n"
        target = directory / f"{sha}.json"
        _atomic_immutable_write(
            directory, target, raw,
            existing=lambda: _read(root, f"{DIRECTORY}/{sha}.json", MAX_FOCUS_RECEIPT_BYTES),
        )
        pointer_raw = canonical({"schema_version": THESIS_SCHEMA, "receipt_sha256": sha}) + b"\n"
        _publish_pointer_no_clobber(root, directory, pointer_raw)
        _fence_selected_thesis_durability(root, directory, receipt)
        return _selected_thesis_projection(receipt, sha)


def install_thesis_focus(repo_root: Path, receipt: dict, *, expected_previous_sha256: str | None = None,
                         expected_generation: dict | None = None, initial_convictions: dict | None = None) -> dict:
    """Compatibility wrapper for callers that have already completed admission."""
    if expected_generation is None or initial_convictions is None:
        raise FocusError("thesis focus install needs a prepared selection basis")
    prepared = prepare_thesis_focus(repo_root, receipt, expected_previous_sha256=expected_previous_sha256,
                                    expected_generation=expected_generation, initial_convictions=initial_convictions)
    return commit_prepared_thesis_focus(repo_root, prepared)


def _initial_conviction_rows(focus_id: str, selected_at: str, forecasts: dict) -> dict[str, tuple[dict, bytes, str]]:
    """D-087's canonical, flat ledger rows; focus receipt carries provenance."""
    expected: dict[str, tuple[dict, bytes, str]] = {}
    for forecaster in ("nara", "oracle", "claude"):
        forecast = forecasts[forecaster]
        if not isinstance(forecast, dict):
            raise FocusError("invalid initial conviction forecast")
        row = {
            "thesis": focus_id,
            "forecaster": forecaster,
            "at": selected_at,
            "p_pass_T": forecast["p_pass_t"],
            "p_pass_S": forecast["p_pass_s"],
            "p_pass_A": forecast["p_pass_a"],
            "p_dead_end": forecast["p_dead_end"],
            "interest_0_10": forecast["interest_0_10"],
            "reasons": forecast["reasons"],
            "trigger": "selection",
        }
        row_raw = canonical(row)
        expected[forecaster] = (row, row_raw + b"\n", hashlib.sha256(row_raw).hexdigest())
    return expected


def project_focus(repo_root: Path) -> dict:
    """Read-only status; malformed selection is explicit, never no focus."""
    root = Path(repo_root)
    try:
        raw = _read(root, POINTER, 4096)
    except FileNotFoundError:
        none = {"status": "none", "execution_authorized": False}
        try:
            closures = _closures(root)
        except (OSError, ValueError) as exc:
            return {**none, "last_closure": {"status": "source_invalid", "reason": str(exc)[:240]}}
        if closures:
            none["last_closure"] = _closure_tip(closures)
        return none
    except (OSError, ValueError, RuntimeError) as exc:
        return {
            "status": "source_invalid",
            "reason": type(exc).__name__,
            "execution_authorized": False,
        }
    try:
        pointer = _object(raw)
        if set(pointer) != {"schema_version", "receipt_sha256"} or pointer[
            "schema_version"
        ] not in {SCHEMA, THESIS_SCHEMA}:
            raise FocusError("invalid focus pointer")
        sha = pointer["receipt_sha256"]
        if not isinstance(sha, str) or not SHA.fullmatch(sha):
            raise FocusError("invalid focus receipt hash")
        receipt_raw = _read(root, f"{DIRECTORY}/{sha}.json", 16384)
        if hashlib.sha256(receipt_raw).hexdigest() != sha:
            raise FocusError("focus receipt hash differs")
        receipt = _object(receipt_raw)
        if pointer["schema_version"] == THESIS_SCHEMA:
            _validate_thesis(receipt)
            from orchestrator.thesis_selection import verify_selection_sources

            verify_selection_sources(root, receipt)
            return {
                **receipt,
                "status": "selected",
                "receipt_sha256": sha,
                "source_evidence_level": None,
                "source_quality": "thesis_candidate_screen",
                "evidence_refs": [
                    {"kind": "nara_candidate_set", "sha256": receipt["candidate_set_sha256"]},
                    {"kind": "oracle_screen", "sha256": receipt["screen_sha256"]},
                    {"kind": "meta_accept", "sha256": receipt["meta_accept_sha256"]},
                    {"kind": "oracle_proposal", "msg_id": receipt["proposal_msg_id"], "row_sha256": receipt["proposal_row_sha256"]},
                    {"kind": "meta_review", "msg_id": receipt["review_msg_id"], "row_sha256": receipt["review_row_sha256"]},
                ],
            }
        row = _validate(receipt, root)
        from orchestrator.experiment_admission import derive_verified_level
        from workers.evidence_ladder import v2_hypothesis_failures

        hypothesis = row.get("hypothesis")
        text = hypothesis.get("text", "") if isinstance(hypothesis, dict) else ""
        hypothesis_failures = v2_hypothesis_failures(row)
        quality = (
            "missing_hypothesis"
            if not isinstance(text, str) or not text.strip()
            else "raw_structured_hypothesis"
            if hypothesis_failures
            else "plain_hypothesis"
        )
        level = (
            derive_verified_level(row, None, None, [], repo_root=root)["level"]
            if quality == "plain_hypothesis"
            else None
        )
        return {
            **receipt,
            "status": "selected",
            "receipt_sha256": sha,
            "source_evidence_level": level,
            "source_quality": quality,
            "evidence_refs": [
                {
                    "path": "memory/loop_memory.jsonl",
                    "iteration_id": receipt["source_iteration_id"],
                    "record_ordinal": receipt["source_record_ordinal"],
                    "row_sha256": receipt["source_row_sha256"],
                }
            ],
            "scientific_credit": "none_selection_only",
        }
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        RuntimeError,
        UnicodeError,
    ) as exc:
        return {
            "status": "source_invalid",
            "reason": str(exc)[:240],
            "execution_authorized": False,
        }


def verify_initial_convictions(root: Path, receipt: dict, *, expected_forecasts: dict | None = None) -> None:
    """Verify the D-087 selection rows the v2 receipt content-addresses."""
    raw = _read(root, CONVICTION_LEDGER, MAX_CONVICTION_LEDGER_BYTES)
    if not raw.endswith(b"\n"):
        raise FocusError("incomplete conviction ledger tail")
    lines = raw[:-1].split(b"\n") if raw else []
    by_hash = {hashlib.sha256(line).hexdigest(): line for line in lines if line}
    expected = (_initial_conviction_rows(receipt["focus_id"], receipt["selected_at"], expected_forecasts)
                if expected_forecasts is not None else None)
    for ref in receipt["initial_conviction_rows"]:
        raw_row = by_hash.get(ref["row_sha256"])
        if raw_row is None:
            raise FocusError("initial conviction row is absent")
        _validate_d087_row(receipt, ref, raw_row)
        row = _object(raw_row)
        if expected is not None and (ref["row_sha256"] != expected[ref["forecaster"]][2]
                                     or row != expected[ref["forecaster"]][0]):
            raise FocusError("initial conviction forecast differs from reviewed proposal")
def select_focus(
    repo_root: Path,
    *,
    iteration_id: str,
    focus_id: str,
    title: str,
    reason: str,
    selected_by: str,
    next_action: str,
    next_gate: dict,
    blockers: list[str],
    selection_authority: str,
    stage: str = "needs_clean_refinement",
    intake_policy: str = "focus_before_new_topics",
    expected_previous_sha256: str | None = None,
) -> dict:
    """Explicit selection under compare-and-swap, D-084 section 4.1.

    D-084 section 4.1 replaced the earlier operator-only rule: a selection is made
    by Oracle after a meta review (the G0.2 row), which is why the `select` CLI
    authorizing review, which _authority_binds() checks and the receipt records as
    `selection_authority`. It never authorizes execution, and it refuses to overwrite
    a live focus: succession is close_focus, generate, then select (see the lifecycle
    in D-084 section 5).
    """
    root = Path(repo_root).resolve()
    state_directory = root / "run_state"
    state_directory.mkdir(exist_ok=True)
    if state_directory.resolve() != state_directory or not state_directory.is_dir():
        raise FocusError("redirected focus state directory")
    directory = root / DIRECTORY
    directory.mkdir(exist_ok=True)
    if directory.resolve() != directory or not directory.is_dir():
        raise FocusError("redirected focus directory")
    lock_path = directory / ".selection.lock"
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        current = project_focus(root)
        if current["status"] == "source_invalid":
            raise FocusError("repair invalid focus explicitly before replacing it")
        if current.get("receipt_sha256") != expected_previous_sha256:
            raise FocusError("focus changed since the reviewed digest")
        _row, campaign, raw_line, ordinal = _source(root, iteration_id)
        receipt = {
            "schema_version": SCHEMA,
            "focus_id": focus_id,
            "title": title,
            "source_iteration_id": iteration_id,
            "source_record_ordinal": ordinal,
            "source_row_sha256": hashlib.sha256(raw_line).hexdigest(),
            "source_campaign_id": campaign["campaign_id"],
            "source_campaign_manifest_sha256": campaign["_manifest_sha256"],
            "selected_at": datetime.now(timezone.utc).isoformat(),
            "selected_by": selected_by,
            "selection_reason": reason,
            "selection_authority": selection_authority,
            "stage": stage,
            "next_action": next_action,
            "next_gate": next_gate,
            "blockers": blockers,
            "intake_policy": intake_policy,
            "execution_authorized": False,
        }
        _validate(receipt, root)
        raw = canonical(receipt) + b"\n"
        sha = hashlib.sha256(raw).hexdigest()
        _atomic_immutable_write(
            directory, directory / f"{sha}.json", raw,
            existing=lambda: _read(root, f"{DIRECTORY}/{sha}.json", MAX_FOCUS_RECEIPT_BYTES),
        )
        temporary = directory / f".pointer-{os.getpid()}.tmp"
        with temporary.open("xb") as stream:
            stream.write(
                canonical({"schema_version": SCHEMA, "receipt_sha256": sha}) + b"\n"
            )
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, root / POINTER)
        _fsync_directory(directory)
        _fsync_directory((root / POINTER).parent)
        return project_focus(root)


def _closures(root: Path) -> list[dict]:
    """Every closure receipt, each verified against its content address."""
    directory = root / CLOSURES
    if not directory.is_dir():
        return []
    names: list[str] = []
    with os.scandir(directory) as entries:
        for entry in entries:
            # An interrupted immutable write can leave only this private,
            # unlinked-from-the-protocol staging name.  It is never a receipt.
            if entry.name.startswith(".immutable-") and entry.name.endswith(".tmp"):
                continue
            if len(names) >= MAX_CLOSURE_FILES:
                raise FocusError("focus closure scan exceeds file bound")
            if (not entry.is_file(follow_symlinks=False) or not entry.name.endswith(".json")
                    or not SHA.fullmatch(entry.name[:-5])):
                raise FocusError("invalid focus closure entry")
            names.append(entry.name)
    found = []
    for name in sorted(names):
        raw = _read(root, f"{CLOSURES}/{name}", 16384)
        if hashlib.sha256(raw).hexdigest() != name[:-5]:
            raise FocusError("focus closure hash differs")
        closure = _object(raw)
        if canonical(closure) + b"\n" != raw:
            raise FocusError("focus closure is non-canonical")
        _validate_closure(closure)
        found.append({**closure, "closure_sha256": name[:-5]})
    return found


def _closure_tip(closures: list[dict]) -> dict | None:
    """Return one causally chained closure tip; timestamps never order state."""
    if not closures:
        return None
    by_sha = {closure["closure_sha256"]: closure for closure in closures}
    if len(by_sha) != len(closures):
        raise FocusError("ambiguous focus closure identities")
    referenced: set[str] = set()
    for closure in closures:
        prior = closure.get("prior_closure_sha256")
        if closure.get("schema_version") == CLOSURE_SCHEMA:
            if prior is not None and (not isinstance(prior, str) or prior not in by_sha):
                raise FocusError("focus closure causal predecessor differs")
        elif prior is not None:
            raise FocusError("legacy focus closure has causal predecessor")
        if prior is not None:
            referenced.add(prior)
    tips = [closure for closure in closures if closure["closure_sha256"] not in referenced]
    if len(tips) != 1:
        raise FocusError("focus closure history has no unique causal tip")
    tip = tips[0]
    seen: set[str] = set()
    current = tip
    while current is not None:
        digest = current["closure_sha256"]
        if digest in seen:
            raise FocusError("focus closure causal history cycles")
        seen.add(digest)
        prior = current.get("prior_closure_sha256")
        current = by_sha.get(prior) if prior is not None else None
    if len(seen) != len(closures):
        raise FocusError("focus closure history is disconnected")
    return tip


def _strings(value, maximum_items: int, maximum_length: int, *, required: bool) -> bool:
    return (isinstance(value, list) and len(value) <= maximum_items and (bool(value) or not required)
            and all(isinstance(v, str) and v.strip() and len(v) <= maximum_length for v in value))


_CLOSURE_FIELDS = {
    "schema_version", "focus_id", "focus_receipt_sha256", "title", "disposition",
    "reason", "reopening_conditions", "evidence_refs", "closed_at", "closed_by",
    "authority", "execution_authorized",
}


def _validate_closure(closure: object) -> None:
    """A closure is authority-bearing history, not merely a named JSON blob."""
    if not isinstance(closure, dict):
        raise FocusError("invalid focus closure")
    schema = closure.get("schema_version")
    required = _CLOSURE_FIELDS | ({"prior_closure_sha256"} if schema == CLOSURE_SCHEMA else set())
    if schema not in {LEGACY_CLOSURE_SCHEMA, CLOSURE_SCHEMA} or set(closure) != required:
        raise FocusError("unsupported focus closure")
    if not isinstance(closure.get("focus_id"), str) or not IDENTITY.fullmatch(closure["focus_id"]):
        raise FocusError("invalid focus closure identity")
    if not isinstance(closure.get("focus_receipt_sha256"), str) or not SHA.fullmatch(closure["focus_receipt_sha256"]):
        raise FocusError("invalid focus closure receipt")
    if closure.get("disposition") not in DISPOSITIONS:
        raise FocusError("invalid focus closure disposition")
    for key, maximum in (("title", 180), ("reason", 1800), ("closed_by", 120), ("authority", 400)):
        value = closure.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > maximum:
            raise FocusError(f"invalid focus closure {key}")
    if not _strings(closure.get("reopening_conditions"), 12, 600, required=closure["disposition"] == "killed"):
        raise FocusError("invalid focus closure reopening conditions")
    if not _strings(closure.get("evidence_refs"), 20, 400, required=True):
        raise FocusError("invalid focus closure evidence")
    try:
        closed_at = datetime.fromisoformat(str(closure.get("closed_at")).replace("Z", "+00:00"))
    except ValueError as exc:
        raise FocusError("invalid focus closure timestamp") from exc
    if closed_at.tzinfo is None or closed_at > datetime.now(timezone.utc):
        raise FocusError("invalid focus closure timestamp")
    if closure.get("execution_authorized") is not False:
        raise FocusError("focus closure cannot authorize execution")
    if schema == CLOSURE_SCHEMA:
        prior = closure["prior_closure_sha256"]
        if prior is not None and (not isinstance(prior, str) or not SHA.fullmatch(prior)):
            raise FocusError("invalid focus closure predecessor")


def close_focus(
    repo_root: Path,
    *,
    disposition: str,
    reason: str,
    reopening_conditions: list[str],
    evidence_refs: list[str],
    closed_by: str,
    authority: str,
    expected_receipt_sha256: str,
) -> dict:
    """End the selected focus by compare-and-swap (D-084); returns the new projection."""
    if disposition not in DISPOSITIONS:
        raise FocusError(f"disposition must be one of {sorted(DISPOSITIONS)}")
    for name, value, maximum in (("reason", reason, 1800), ("closed_by", closed_by, 120),
                                 ("authority", authority, 400)):
        if not isinstance(value, str) or not value.strip() or len(value) > maximum:
            raise FocusError(f"invalid {name}")
    if not _strings(reopening_conditions, 12, 600, required=disposition == "killed"):
        raise FocusError("a killed focus needs reopening conditions (at most 12)")
    if not _strings(evidence_refs, 20, 400, required=True):
        raise FocusError("a closure needs evidence references (at most 20)")
    root = Path(repo_root).resolve()
    directory = root / CLOSURES
    directory.mkdir(parents=True, exist_ok=True)
    if directory.resolve() != directory or not directory.is_dir():
        raise FocusError("redirected focus closure directory")
    _fsync_directory_chain(root, directory)
    fd = os.open(root / DIRECTORY / ".selection.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        current = project_focus(root)
        if current["status"] != "selected":
            raise FocusError("no valid selected focus to close")
        if current["receipt_sha256"] != expected_receipt_sha256:
            raise FocusError("focus changed since review")
        # A retry after a crash between the two writes finishes the removal instead of
        # recording a second closure for the same focus.
        closures = _closures(root)
        if not any(c.get("focus_receipt_sha256") == expected_receipt_sha256 for c in closures):
            prior = _closure_tip(closures)
            closure = {
                "schema_version": CLOSURE_SCHEMA,
                "focus_id": current["focus_id"],
                "focus_receipt_sha256": expected_receipt_sha256,
                "title": current["title"],
                "disposition": disposition,
                "reason": reason,
                "reopening_conditions": reopening_conditions,
                "evidence_refs": evidence_refs,
                "closed_at": datetime.now(timezone.utc).isoformat(),
                "closed_by": closed_by,
                "authority": authority,
                "execution_authorized": False,
                "prior_closure_sha256": prior["closure_sha256"] if prior is not None else None,
            }
            raw = canonical(closure) + b"\n"
            closure_sha = hashlib.sha256(raw).hexdigest()
            _atomic_immutable_write(
                directory, directory / f"{closure_sha}.json", raw,
                existing=lambda: _read(root, f"{CLOSURES}/{closure_sha}.json", 16384),
            )
        os.unlink(root / POINTER)
        _fsync_directory((root / POINTER).parent)
        return project_focus(root)


def build_parser() -> argparse.ArgumentParser:
    """The CLI, split out so a test can parse against a temp repo (main() resolves
    its repo as this package's parent, so it can only ever touch the live one)."""
    parser = argparse.ArgumentParser(description="Research focus status, closure and selection (D-084).")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    close = sub.add_parser("close")
    close.add_argument("--disposition", required=True, choices=sorted(DISPOSITIONS))
    close.add_argument("--reason", required=True)
    close.add_argument("--reopen", action="append", default=[], help="a reopening condition (repeatable)")
    close.add_argument("--evidence", action="append", default=[], help="an evidence reference (repeatable)")
    close.add_argument("--closed-by", required=True)
    close.add_argument("--authority", required=True, help="decision and review, e.g. D-084 + review msg_id")
    close.add_argument("--expected-receipt", required=True, help="sha256 of the focus being closed")
    select = sub.add_parser("select")
    select.add_argument("--iteration-id", required=True)
    select.add_argument("--focus-id", required=True)
    select.add_argument("--title", required=True)
    select.add_argument("--reason", required=True)
    select.add_argument("--next-action", required=True)
    select.add_argument("--next-gate-json", required=True, help="the next gate as a JSON object")
    select.add_argument("--blocker", action="append", default=[], help="a blocker (repeatable)")
    select.add_argument("--stage", default="needs_clean_refinement")
    select.add_argument("--selected-by", required=True, help="who is selecting, e.g. oracle")
    select.add_argument("--authority", required=True,
                        help="a meta-oracle review msg_id accepting this selection (D-084 4.1)")
    # Exactly one of these is required: a compare-and-swap digest of the focus being
    # replaced, or an explicit declaration that there is none to replace.
    receipt_group = select.add_mutually_exclusive_group(required=True)
    receipt_group.add_argument("--expected-receipt", help="sha256 of the focus being replaced")
    receipt_group.add_argument("--allow-empty-previous", action="store_true", default=False,
                               help="declare a first selection, after a kill or with no prior focus")
    return parser


def _repo_head(root: Path) -> str | None:
    """The repo's own HEAD sha, for the binding check. `git rev-parse HEAD` would
    answer from the ambient superproject whenever the root is not itself a checkout
    (a bare temp directory, or a directory inside one), which both misinforms the
    check and makes it skip silently when the root is absent - so an unresolvable
    root is refused rather than treated as "no HEAD to compare"."""
    try:
        proc = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], cwd=None,
                              capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise FocusError(f"cannot resolve the repo HEAD to bind the selection to: {exc}") from None
    if proc.returncode != 0:
        detail = (proc.stderr or "").strip().splitlines()
        raise FocusError(f"cannot resolve the repo HEAD to bind the selection to: "
                         f"{(detail[-1] if detail else f'exit {proc.returncode}')[:200]}")
    return proc.stdout.strip()


def _authority_row(root: Path, authority: str, *, focus_id: str, iteration_id: str) -> dict:
    """Resolve --authority against this repo's mailbox and bind it to THIS selection.

    A review is an accept of something, so an accept alone would let any accepting
    review in the mailbox authorize any focus, which makes D-084 §4.1's "after a meta
    review" a formality (review claude-b10f196463dc87ad, finding 1). Four things are
    checked: the row is a `review` by a reviewer with verdict=accept; the review
    replies to an oracle note or question that names this focus_id and iteration_id
    (the §5 'FOCUS SELECTION PROPOSED' note); no existing receipt was already
    authorized by it; and, on a git checkout, that note was posted at the repo's
    current HEAD (its `ref`), so one review cannot authorize a later selection.
    """
    try:
        rows = oracle_mailbox.read(root / "run_state/oracle_nara_mailbox.jsonl")
    except (oracle_mailbox.MailboxError, OSError) as exc:
        raise FocusError(f"authority cannot be read from the mailbox: {exc}") from None
    match = [r for r in rows if r.get("msg_id") == authority]
    if not match:
        raise FocusError(f"authority {authority!r} is an unknown mailbox msg_id in this repo")
    row = match[-1]
    if row.get("actor") not in oracle_mailbox.REVIEWERS:
        raise FocusError("authority must be posted by a reviewer "
                         f"({sorted(oracle_mailbox.REVIEWERS)}), not {row.get('actor')!r}")
    if row.get("kind") != "review":
        raise FocusError(f"authority must be a review row, not kind={row.get('kind')!r}")
    verdict = row.get("body", {}).get("verdict") if isinstance(row.get("body"), dict) else None
    if verdict != "accept":
        raise FocusError(f"authority review verdict must be accept, not {verdict!r}")
    parent = [r for r in rows if r.get("msg_id") == row.get("in_reply_to")]
    if not parent:
        raise FocusError(f"authority review replies to {row.get('in_reply_to')!r}, "
                         "which is not a row in this mailbox")
    proposal = parent[-1]
    if proposal.get("actor") != "oracle" or proposal.get("kind") not in ("note", "question"):
        raise FocusError("authority must reply to an oracle note or question naming the "
                         f"selection, not actor={proposal.get('actor')!r} "
                         f"kind={proposal.get('kind')!r}")
    text = json.dumps(proposal.get("body", {}))
    if focus_id not in text or iteration_id not in text:
        raise FocusError(
            "the note that the authority review replies to does not name this selection: it "
            f"must mention focus_id {focus_id!r} and iteration_id {iteration_id!r} "
            "(the §5 'FOCUS SELECTION PROPOSED' note)")
    body = proposal.get("body") if isinstance(proposal.get("body"), dict) else {}
    ref = (body.get("ref") or {}).get("head_sha") if isinstance(body.get("ref"), dict) else None
    head = _repo_head(root)
    if ref != head:
        raise FocusError(f"the selection note names head_sha {ref!r} but the repo HEAD is "
                         f"{head!r}; a review authorizes a selection only at the state it was "
                         "proposed on - re-propose at the current HEAD")
    for name in _receipt_names(root):
        try:
            prior = _object(_read(root, f"{DIRECTORY}/{name}", 16384))
        except (OSError, ValueError, RuntimeError):
            continue
        if prior.get("selection_authority") == authority:
            raise FocusError(f"authority {authority!r} already authorized focus "
                             f"{prior.get('focus_id')!r}; one review, one selection")
    return row


def _receipt_names(root: Path) -> list[str]:
    """Receipt file names in the focus directory, excluding locks and temporaries."""
    directory = root / DIRECTORY
    if not directory.is_dir():
        return []
    return sorted(p.name for p in directory.iterdir()
                  if p.suffix == ".json" and not p.name.startswith("."))


def run_select(root: Path, args: argparse.Namespace) -> dict:
    """The `select` subcommand: resolve and bind the authority, then select_focus()."""
    expected = None if args.allow_empty_previous else args.expected_receipt
    try:
        next_gate = json.loads(args.next_gate_json)
    except ValueError as exc:
        raise FocusError(f"--next-gate-json is not JSON: {exc}") from None
    if not isinstance(next_gate, dict) or not next_gate:
        raise FocusError("--next-gate-json must be a non-empty JSON object")
    current = project_focus(root)
    if current["status"] != "none":
        # A focus is ended by close_focus, which writes a disposition and its reopening
        # conditions; switching by overwrite would skip that record. There is no override:
        # --force is not defined on this subcommand, so an overwrite attempt dies at argparse.
        raise FocusError(f"a focus is already selected ({current.get('focus_id', 'unknown')}); "
                         "close it first - succession is close, generate, then select")
    row = _authority_row(root, args.authority, focus_id=args.focus_id,
                         iteration_id=args.iteration_id)
    selected = select_focus(
        root, iteration_id=args.iteration_id, focus_id=args.focus_id, title=args.title,
        reason=args.reason, selected_by=args.selected_by, next_action=args.next_action,
        next_gate=next_gate, blockers=list(args.blocker), stage=args.stage,
        selection_authority=row["msg_id"], expected_previous_sha256=expected)
    return selected


def run(args: argparse.Namespace, root: Path) -> dict:
    """Dispatch one parsed command against an explicit repo root."""
    if args.command == "status":
        return project_focus(root)
    if args.command == "close":
        return close_focus(root, disposition=args.disposition, reason=args.reason,
                            reopening_conditions=args.reopen, evidence_refs=args.evidence,
                            closed_by=args.closed_by, authority=args.authority,
                            expected_receipt_sha256=args.expected_receipt)
    return run_select(root, args)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    try:
        result = run(args, root)
    except FocusError as exc:
        print(f"research_focus: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
