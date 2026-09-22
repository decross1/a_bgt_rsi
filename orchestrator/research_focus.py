"""Source-bound research priority, separate from study or execution authority.

A focus is an immutable operator selection receipt plus an atomic pointer. It
can stop discovery churn, but cannot register an experiment or earn a rung.
Historical seeds retain their source quality and campaign instead of appearing
as new-campaign findings. No model, network, or scientific-ledger writes here.

A focus ends through an immutable closure receipt (D-084): `killed` or
`graduated`, with its reason, reopening conditions, evidence and authority. The
closure is written first and the pointer removed second, so a closed focus reads
as "none" (the intake hold lifts) while both receipts stay as negative knowledge.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "research-focus/v1"
POINTER = "run_state/active_research_focus.json"
DIRECTORY = "run_state/research_focus"
SHA = re.compile(r"[0-9a-f]{64}\Z")
IDENTITY = re.compile(r"[a-z0-9][a-z0-9-]{2,95}\Z")
STAGES = {"needs_clean_refinement", "blocked"}
CLOSURE_SCHEMA = "research-focus-closure/v1"
CLOSURES = f"{DIRECTORY}/closures"
DISPOSITIONS = {"killed", "graduated"}  # terminal focus states (D-084)
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
    "stage",
    "next_action",
    "next_gate",
    "blockers",
    "intake_policy",
    "execution_authorized",
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
            none["last_closure"] = max(closures, key=lambda c: c["closed_at"])
        return none
    except (OSError, ValueError, RuntimeError) as exc:
        return {
            "status": "source_invalid",
            "reason": type(exc).__name__,
            "execution_authorized": False,
        }
    try:
        pointer = _object(raw)
        if (
            set(pointer) != {"schema_version", "receipt_sha256"}
            or pointer["schema_version"] != SCHEMA
        ):
            raise FocusError("invalid focus pointer")
        sha = pointer["receipt_sha256"]
        if not isinstance(sha, str) or not SHA.fullmatch(sha):
            raise FocusError("invalid focus receipt hash")
        receipt_raw = _read(root, f"{DIRECTORY}/{sha}.json", 16384)
        if hashlib.sha256(receipt_raw).hexdigest() != sha:
            raise FocusError("focus receipt hash differs")
        receipt = _object(receipt_raw)
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
    stage: str = "needs_clean_refinement",
    intake_policy: str = "focus_before_new_topics",
    expected_previous_sha256: str | None = None,
) -> dict:
    """Explicit operator action with compare-and-swap; never called by a model."""
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
            raise FocusError("focus changed since operator review")
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
        with (directory / f"{sha}.json").open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        _fsync_directory(directory)
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
    found = []
    for path in sorted(directory.glob("*.json")):
        raw = _read(root, f"{CLOSURES}/{path.name}", 16384)
        if hashlib.sha256(raw).hexdigest() != path.stem:
            raise FocusError("focus closure hash differs")
        closure = _object(raw)
        if closure.get("schema_version") != CLOSURE_SCHEMA:
            raise FocusError("unsupported focus closure")
        found.append({**closure, "closure_sha256": path.stem})
    return found


def _strings(value, maximum_items: int, maximum_length: int, *, required: bool) -> bool:
    return (isinstance(value, list) and len(value) <= maximum_items and (bool(value) or not required)
            and all(isinstance(v, str) and v.strip() and len(v) <= maximum_length for v in value))


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
        if not any(c.get("focus_receipt_sha256") == expected_receipt_sha256 for c in _closures(root)):
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
            }
            raw = canonical(closure) + b"\n"
            with (directory / f"{hashlib.sha256(raw).hexdigest()}.json").open("xb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            _fsync_directory(directory)
        os.unlink(root / POINTER)
        _fsync_directory((root / POINTER).parent)
        return project_focus(root)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Research focus status and closure (D-084).")
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
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    try:
        if args.command == "status":
            result = project_focus(root)
        else:
            result = close_focus(root, disposition=args.disposition, reason=args.reason,
                                 reopening_conditions=args.reopen, evidence_refs=args.evidence,
                                 closed_by=args.closed_by, authority=args.authority,
                                 expected_receipt_sha256=args.expected_receipt)
    except FocusError as exc:
        print(f"research_focus: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
