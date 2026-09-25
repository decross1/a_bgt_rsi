"""Two-way Oracle <-> Nara mailbox (owner direction 2026-09-22, D-082).

Oracle sets the plan; Nara implements it and reports. One append-only JSONL
log under a file lock; every row names its actor and kind. Attribution is
honest but not authenticated (the D-067 lesson): the hash chain shows order
and detects in-place edits; it does not prove identity. The mailbox never carries owner approvals; owner
authority is D-082's standing mandate plus the owner's own channels. A `review` is the meta-oracle's
verdict (owner direction 2026-09-22): the lane's gate on plan items, not an owner approval.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import math
import os
import re
import stat
import subprocess
import sys
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "run_state/oracle_nara_mailbox.jsonl"
SCHEMA = "oracle-nara-mailbox/v1"
MAX_ROW_BYTES = 16 * 1024
MAX_PLAN_BYTES = 262_144
MAX_STATE_PACKET_BYTES = 1_048_576
GIT_TIMEOUT_S = 5
# Shared coordination state for every participant (owner, 2026-09-22). Anyone
# may post notes, questions and answers under their own name (humans as
# human:<id>); only Oracle issues plan items and only Nara posts receipts.
AGENTS = {"oracle", "nara", "claude", "codex", "system"}
CONVERSANTS = {"oracle", "nara", "claude", "codex"}
REVIEWERS = {"claude", "codex"}  # frontier meta-oracle; veto or annotate only (D-061)
KINDS = {
    "plan_item": {"oracle"},        # Oracle -> Nara work order
    "withdraw": {"oracle"},         # Oracle cancels an open plan item
    "receipt": {"nara"},            # Nara -> Oracle progress / outcome
    "review": REVIEWERS,            # meta-oracle verdict on a plan, plan item or branch
    "question": CONVERSANTS,
    "answer": CONVERSANTS,
    # This is an explicit non-answer disposition. Only the original asker or
    # a human may append one, so a relay/reviewer cannot hide an owner card.
    "question_resolution": AGENTS,
    "note": AGENTS,
}
HUMAN_KINDS = {"question", "answer", "note", "question_resolution"}
RECIPIENTS = {"oracle", "nara", "claude", "codex", "owner", "all"}
RECEIPT_STATES = {"held", "claimed", "validated", "failed", "withdrawn"}
TERMINAL = {"validated", "failed", "withdrawn"}
VERDICTS = {"accept", "amend", "reject"}
TASK_CLASSES = {"documentation", "tests", "tooling", "experiment_code", "lab_organization"}
QUESTION_RESOLUTIONS = {"withdrawn", "superseded", "prerequisite", "informational"}
PROVENANCE_CONTEST_EFFECT = "invalidate_for_projection"
PLAN_REVISION_PATH = re.compile(
    r"run_state/daily_plans/(?P<date>\d{4}-\d{2}-\d{2})-(?P<revision>r[1-9]\d*)\.json"
)
SHA256 = re.compile(r"[0-9a-f]{64}")
GIT_SHA1 = re.compile(r"[0-9a-f]{40}")
PLAN_READY_EVENT = "PLAN READY"
PLAN_READY_PROTOCOL = "oracle-plan-ready/v1"
PLAN_READY_TITLE = re.compile(
    r"^PLAN READY:\s*(?P<date>\d{4}-\d{2}-\d{2})(?:(?:\s*\((?P<paren_revision>r[1-9]\d*)\))|-(?P<dash_revision>r[1-9]\d*))?\s*$"
)


class MailboxError(ValueError):
    pass


def _git(repo_root: Path, *args: str) -> bytes:
    """Run Git against immutable objects rather than mutable worktree files."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), *args], check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=GIT_TIMEOUT_S,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        detail = (exc.stderr.decode(errors="replace").strip()
                  if isinstance(exc, subprocess.CalledProcessError) else str(exc))
        raise MailboxError(f"Git verification failed: {detail}") from None
    return result.stdout


def _lstat(path: Path, *, label: str, allow_missing: bool) -> os.stat_result | None:
    try:
        result = path.lstat()
    except FileNotFoundError:
        if allow_missing:
            return None
        raise MailboxError(f"{label} is missing: {path}") from None
    if stat.S_ISLNK(result.st_mode):
        raise MailboxError(f"{label} must not be a symlink: {path}")
    return result


def _assert_no_symlink_ancestors(path: Path, *, label: str) -> None:
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        current /= component
        result = _lstat(current, label=label, allow_missing=True)
        if result is None:
            return
        if current != absolute and not stat.S_ISDIR(result.st_mode):
            raise MailboxError(f"{label} parent is not a directory: {current}")


def _prepare_mailbox_path(path: Path) -> None:
    _assert_no_symlink_ancestors(path.parent, label="mailbox parent")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise MailboxError(f"could not create mailbox parent: {exc}") from None
    _assert_no_symlink_ancestors(path.parent, label="mailbox parent")
    parent = _lstat(path.parent, label="mailbox parent", allow_missing=False)
    if not stat.S_ISDIR(parent.st_mode):
        raise MailboxError(f"mailbox parent is not a directory: {path.parent}")
    result = _lstat(path, label="mailbox path", allow_missing=True)
    if result is not None and not stat.S_ISREG(result.st_mode):
        raise MailboxError(f"mailbox path must be a regular file: {path}")


@contextmanager
def _mailbox_lock(path: Path):
    """Use a no-follow lock only for immutable plan publication."""
    _prepare_mailbox_path(path)
    lock_path = path.parent / ".oracle_nara_mailbox.lock"
    result = _lstat(lock_path, label="mailbox lock", allow_missing=True)
    if result is not None and not stat.S_ISREG(result.st_mode):
        raise MailboxError(f"mailbox lock must be a regular file: {lock_path}")
    try:
        descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    except OSError as exc:
        raise MailboxError(f"could not open mailbox lock safely: {exc}") from None
    with os.fdopen(descriptor, "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def _repo_file_path(value: str, *, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise MailboxError(f"{label} must be a non-empty POSIX repository path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", "..", ".git"} for part in path.parts):
        raise MailboxError(f"{label} must stay inside the repository")
    return value


def _committed_blob(repo_root: Path, head_sha: str, repo_path: str, *, maximum_bytes: int) -> bytes:
    listing = _git(repo_root, "ls-tree", head_sha, "--", repo_path).decode().rstrip("\n")
    if not listing:
        raise MailboxError(f"committed path is absent: {repo_path}")
    try:
        metadata, found_path = listing.split("\t", 1)
        mode, object_type, object_sha = metadata.split()
    except ValueError:
        raise MailboxError(f"could not verify committed path: {repo_path}") from None
    if found_path != repo_path or object_type != "blob" or mode not in {"100644", "100755"}:
        raise MailboxError(f"committed path must be a regular file, not a symlink or directory: {repo_path}")
    try:
        size = int(_git(repo_root, "cat-file", "-s", object_sha).decode().strip())
    except ValueError:
        raise MailboxError(f"could not measure committed blob: {repo_path}") from None
    if size > maximum_bytes:
        raise MailboxError(f"committed blob exceeds {maximum_bytes} byte bound: {repo_path}")
    contents = _git(repo_root, "show", f"{head_sha}:{repo_path}")
    if len(contents) != size:
        raise MailboxError(f"committed blob changed during read: {repo_path}")
    return contents


def _require_sha256(value: str, *, label: str) -> None:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise MailboxError(f"{label} must be a lowercase SHA-256 hex digest")


def _frozen_body(body: dict) -> dict:
    """Detach JSON-safe payloads before lock acquisition."""
    if not isinstance(body, dict):
        raise MailboxError("body must be an object")
    try:
        frozen = json.loads(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                       ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise MailboxError(f"body must be JSON-safe: {exc}") from None
    return frozen


def _plan_ready_body(*, branch: str, head_sha: str, plan_path: str, plan_sha256: str,
                     state_packet_path: str, state_packet_sha256: str,
                     date: str, revision: str) -> dict:
    return {
        "title": f"PLAN READY: {date} ({revision})",
        "ref": {"path": plan_path, "sha256": plan_sha256},
        "event": PLAN_READY_EVENT, "protocol": PLAN_READY_PROTOCOL,
        "branch": branch, "head_sha": head_sha, "plan_path": plan_path,
        "plan_sha256": plan_sha256, "state_packet_path": state_packet_path,
        "state_packet_sha256": state_packet_sha256, "date": date, "revision": revision,
    }


def _plan_ready_duplicate_or_conflict(rows: list[dict], body: dict) -> dict | None:
    identity = (body["plan_path"], body["date"], body["revision"])
    exact: dict | None = None
    for row in rows:
        recorded = row.get("body")
        if row.get("kind") != "note" or not isinstance(recorded, dict):
            continue
        title = recorded.get("title")
        consumer_visible = isinstance(title, str) and title.lstrip().startswith("PLAN READY")
        title_match = PLAN_READY_TITLE.fullmatch(title) if isinstance(title, str) else None
        ref = recorded.get("ref") if isinstance(recorded.get("ref"), dict) else {}
        typed = recorded.get("event") == PLAN_READY_EVENT or recorded.get("protocol") == PLAN_READY_PROTOCOL
        if not typed and not consumer_visible:
            continue
        recorded_identity = (recorded.get("plan_path"), recorded.get("date"), recorded.get("revision"))
        same_path = recorded.get("plan_path") == body["plan_path"] or ref.get("path") == body["plan_path"]
        title_date = title_match.group("date") if title_match else None
        title_revision = ((title_match.group("paren_revision") or title_match.group("dash_revision"))
                          if title_match else None)
        same_date = title_date == body["date"] or recorded.get("date") == body["date"]
        same_revision = title_revision == body["revision"] or recorded.get("revision") == body["revision"]
        if not (same_path or recorded_identity == identity or (same_date and same_revision)):
            continue
        canonical_envelope = (row.get("schema") == SCHEMA and row.get("actor") == "oracle"
                              and row.get("to") == "all" and row.get("kind") == "note"
                              and row.get("in_reply_to") is None and row.get("expires_at") is None)
        if canonical_envelope and recorded == body:
            if exact is not None:
                raise MailboxError("multiple PLAN READY rows bind the same immutable revision")
            exact = row
            continue
        raise MailboxError(
            "PLAN READY revision/path is ambiguous or has a different committed binding; publish a new dated revision"
        )
    return exact


def _canonical(value) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise MailboxError("mailbox value is not canonical UTF-8 JSON") from exc


def _actor_ok(actor: object) -> bool:
    return isinstance(actor, str) and (actor in AGENTS or bool(
        re.fullmatch(r"human:[a-z0-9_.-]{1,40}", actor)
    ))


ROW_FIELDS = frozenset({
    "schema", "seq", "ts", "actor", "to", "kind", "in_reply_to", "body",
    "expires_at", "prev_sha256", "msg_id", "row_sha256",
})
_SHA256 = re.compile(r"[0-9a-f]{64}")
_OWNER_REQUEST_ID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
_PLAN_REVISION = re.compile(r"\d{4}-\d{2}-\d{2}(?:-r\d+)?")


def row_issue(row: object, position: int, previous: object = None) -> str | None:
    """Return a typed structural reason for a hash-checked row, if any.

    ``read`` preserves every hash-valid JSON object as append-only evidence.
    Consumers use this predicate to quarantine unusable rows instead of
    allowing one malformed historical record to become live coordination
    state.  This validates structure and writer-derived identity; it does not
    authenticate the actor label.
    """
    if not isinstance(row, dict) or set(row) != ROW_FIELDS:
        return "row_fields"
    if row.get("schema") != SCHEMA:
        return "schema"
    if type(row.get("seq")) is not int or row["seq"] != position + 1:
        return "sequence"
    actor, recipient, kind, body = row.get("actor"), row.get("to"), row.get("kind"), row.get("body")
    if not isinstance(actor, str) or not _actor_ok(actor):
        return "actor"
    if not isinstance(recipient, str) or recipient not in RECIPIENTS:
        return "recipient"
    if not isinstance(kind, str) or kind not in KINDS:
        return "kind"
    if not (actor in KINDS[kind] or (actor.startswith("human:") and kind in HUMAN_KINDS)):
        return "actor_kind"
    if not isinstance(body, dict):
        return "body"
    if not isinstance(row.get("msg_id"), str) or not row["msg_id"]:
        return "msg_id"
    if row.get("in_reply_to") is not None and not isinstance(row.get("in_reply_to"), str):
        return "in_reply_to"
    if kind in {"receipt", "withdraw", "answer", "review", "question_resolution"} \
            and not row.get("in_reply_to"):
        return "missing_reply"
    if row.get("expires_at") is not None and not isinstance(row.get("expires_at"), str):
        return "expires_at"
    try:
        timestamp = datetime.fromisoformat(row["ts"])
        expires = datetime.fromisoformat(row["expires_at"]) if row["expires_at"] is not None else None
    except (TypeError, ValueError):
        return "timestamp"
    if timestamp.tzinfo is None or (expires is not None and expires.tzinfo is None):
        return "timestamp_timezone"
    if expires is not None and expires <= timestamp:
        return "expiry_before_or_at_timestamp"
    try:
        if kind == "plan_item":
            validate_plan_item(body)
        elif kind == "receipt" and (not isinstance(body.get("state"), str)
                                     or body.get("state") not in RECEIPT_STATES):
            return "receipt_state"
        elif kind == "review" and (not isinstance(body.get("verdict"), str)
                                    or body.get("verdict") not in VERDICTS):
            return "review_verdict"
        elif kind == "question_resolution":
            validate_question_resolution(body)
    except (MailboxError, TypeError, ValueError, OverflowError):
        return f"{kind}_body"
    previous_sha = previous.get("row_sha256") if isinstance(previous, dict) else None
    if row.get("prev_sha256") != previous_sha:
        return "previous_hash"
    claimed = row.get("row_sha256")
    if not isinstance(claimed, str) or _SHA256.fullmatch(claimed) is None:
        return "row_hash"
    without_sha = dict(row)
    without_sha.pop("row_sha256")
    if hashlib.sha256(_canonical(without_sha)).hexdigest() != claimed:
        return "row_hash"
    msg_id = without_sha.pop("msg_id")
    expected_id = f"{actor.split(':')[0]}-{hashlib.sha256(_canonical(without_sha)).hexdigest()[:16]}"
    return None if msg_id == expected_id else "msg_id"


def quarantine(rows: list[dict]) -> list[dict]:
    """Describe hash-valid evidence omitted from live projections."""
    return [
        {"position": position + 1, "seq": row.get("seq") if isinstance(row, dict) else None,
         "msg_id": row.get("msg_id") if isinstance(row, dict) else None, "reason": issue}
        for position, row in enumerate(rows)
        if (issue := row_issue(row, position, rows[position - 1] if position else None)) is not None
    ]


def _owner_answer_binding(row: dict) -> tuple[str, str, str] | None:
    """Return an owner-UI request binding, or ``None`` for a malformed claim."""
    body = row.get("body")
    if not isinstance(body, dict) or body.get("via") != "owner-ui":
        return ("", "", "")
    request_id = body.get("request_id")
    revision = body.get("expected_plan_revision")
    if (not isinstance(request_id, str) or _OWNER_REQUEST_ID.fullmatch(request_id) is None
            or body.get("target_kind") != "question"
            or not isinstance(revision, str) or _PLAN_REVISION.fullmatch(revision) is None):
        return None
    return (str(row.get("in_reply_to")), revision,
            json.dumps(body, sort_keys=True, separators=(",", ":")))


def _relational_live_rows(rows: list[dict]) -> list[dict]:
    """Admit unique identities and only ordered, question-bound dispositions.

    A future question cannot retroactively legitimize an earlier human answer
    or resolution, and a duplicate identity cannot replace the original row.
    All answers remain evidence/context, never terminal owner authority.
    """
    admitted: list[dict] = []
    seen_ids: set[str] = set()
    questions: dict[str, dict] = {}
    owner_requests: dict[str, tuple[str, str, str]] = {}
    for row in rows:
        msg_id = row["msg_id"]
        if msg_id in seen_ids:
            continue
        seen_ids.add(msg_id)
        kind = row.get("kind")
        human_answer = (kind == "answer" and isinstance(row.get("actor"), str)
                        and row["actor"].startswith("human:"))
        if kind == "question_resolution" or human_answer:
            question = questions.get(row.get("in_reply_to"))
            if question is None:
                continue
            if kind == "question_resolution":
                actor = row.get("actor")
                if not (isinstance(actor, str)
                        and (actor == question.get("actor") or actor.startswith("human:"))):
                    continue
            else:
                binding = _owner_answer_binding(row)
                if binding is None:
                    continue
                body = row["body"]
                if body.get("via") == "owner-ui":
                    request_id = body["request_id"]
                    if request_id in owner_requests and owner_requests[request_id] != binding:
                        continue
                    owner_requests[request_id] = binding
        admitted.append(row)
        if kind == "question":
            questions[msg_id] = row
    return admitted


def live_rows(rows: list[dict]) -> list[dict]:
    """Non-mutating structurally and relationally live projection input."""
    structural = [
        row for position, row in enumerate(rows)
        if row_issue(row, position, rows[position - 1] if position else None) is None
    ]
    return _relational_live_rows(structural)


def is_live_row(rows: list[dict], row: object) -> bool:
    """Whether this exact recorded object is admitted to ``live_rows``."""
    return any(candidate is row for candidate in live_rows(rows))


def validate_plan_item(body: dict) -> None:
    """Structure only; the lane applies admission policy."""
    if not isinstance(body, dict):
        raise MailboxError("plan_item body must be an object")
    need = {"title", "objective", "task_class", "allowed_write_paths", "acceptance"}
    missing = need - set(body)
    if missing:
        raise MailboxError(f"plan_item missing {sorted(missing)}")
    if not isinstance(body["task_class"], str) or body["task_class"] not in TASK_CLASSES:
        raise MailboxError(f"task_class must be one of {sorted(TASK_CLASSES)}")
    paths = body["allowed_write_paths"]
    if not isinstance(paths, list) or not paths or not all(isinstance(p, str) and p for p in paths):
        raise MailboxError("allowed_write_paths must be a non-empty list of repo paths")
    acceptance = body["acceptance"]
    if not isinstance(acceptance, dict) or not {"test_path", "test_content", "test_argv"} <= set(acceptance):
        raise MailboxError("acceptance needs test_path, test_content and test_argv")
    if not isinstance(acceptance["test_path"], str) or not isinstance(acceptance["test_content"], str):
        raise MailboxError("acceptance.test_path and test_content must be strings")
    argv = acceptance["test_argv"]
    if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
        raise MailboxError("acceptance.test_argv must be a non-empty list of strings")
    budget = body.get("budget", {})
    if not isinstance(budget, dict) or not all(
            type(budget.get(k, 1)) is int and budget.get(k, 1) > 0 for k in ("attempts", "wall_clock_minutes")):
        raise MailboxError("budget.attempts and budget.wall_clock_minutes must be positive integers")
    if not isinstance(body["title"], str) or not isinstance(body["objective"], str):
        raise MailboxError("title and objective must be strings")
    if len(body["objective"]) > 4000 or len(body["title"]) > 200:
        raise MailboxError("title <= 200 and objective <= 4000 characters")


def validate_question_resolution(body: dict) -> None:
    """Validate an append-only, non-answer disposition of a question."""
    if not isinstance(body, dict):
        raise MailboxError("question_resolution body must be an object")
    allowed = {"disposition", "summary", "reason", "evidence_msg_ids", "replacement_msg_id", "blocking_artifact"}
    if not {"disposition", "summary", "reason"} <= set(body) or not set(body) <= allowed:
        raise MailboxError("question_resolution needs disposition, summary and reason")
    if not isinstance(body["disposition"], str) or body["disposition"] not in QUESTION_RESOLUTIONS:
        raise MailboxError(f"question_resolution disposition must be one of {sorted(QUESTION_RESOLUTIONS)}")
    if not isinstance(body["summary"], str) or not body["summary"].strip() or len(body["summary"]) > 1200:
        raise MailboxError("question_resolution summary must be non-empty and <= 1200 characters")
    if not isinstance(body["reason"], str) or not body["reason"].strip() or len(body["reason"]) > 1200:
        raise MailboxError("question_resolution reason must be non-empty and <= 1200 characters")
    evidence = body.get("evidence_msg_ids")
    if evidence is not None and (not isinstance(evidence, list) or not evidence or len(evidence) > 8
                                 or not all(isinstance(value, str) and value.strip() and len(value) <= 80
                                            for value in evidence)):
        raise MailboxError("question_resolution evidence_msg_ids must be 1-8 message ids")
    for key in ("replacement_msg_id", "blocking_artifact"):
        if key in body and (not isinstance(body[key], str) or not body[key].strip() or len(body[key]) > 240):
            raise MailboxError(f"question_resolution {key} must be a non-empty string <= 240 characters")


def validate_provenance_contestation(body: dict) -> None:
    """Validate a conservative, evidence-bound challenge to an actor label.

    This does not authenticate either named actor.  A valid contest can only
    make consumers distrust an earlier resolution; it cannot answer a question
    or confer authority.
    """
    if not isinstance(body, dict) or not isinstance(body.get("provenance_contestation"), dict):
        raise MailboxError("provenance_contestation must be an object")
    contest = body["provenance_contestation"]
    keys = {"contested_msg_id", "claimed_actor", "reported_actual_actor", "basis_msg_ids", "effect"}
    if set(contest) != keys:
        raise MailboxError(f"provenance_contestation fields must be exactly {sorted(keys)}")
    for key in ("contested_msg_id", "claimed_actor", "reported_actual_actor"):
        if not isinstance(contest[key], str) or not contest[key].strip() or len(contest[key]) > 80:
            raise MailboxError(f"provenance_contestation {key} must be a non-empty string <= 80 characters")
    if not _actor_ok(contest["claimed_actor"]) or not _actor_ok(contest["reported_actual_actor"]):
        raise MailboxError("provenance_contestation actors must use mailbox actor labels")
    if contest["claimed_actor"] == contest["reported_actual_actor"]:
        raise MailboxError("provenance_contestation must report a different actual actor")
    evidence = contest["basis_msg_ids"]
    if (not isinstance(evidence, list) or not 2 <= len(evidence) <= 8 or len(set(evidence)) != len(evidence)
            or not all(isinstance(value, str) and value.strip() and len(value) <= 80 for value in evidence)):
        raise MailboxError("provenance_contestation basis_msg_ids must be 2-8 distinct message ids")
    if contest["effect"] != PROVENANCE_CONTEST_EFFECT:
        raise MailboxError(f"provenance_contestation effect must be {PROVENANCE_CONTEST_EFFECT!r}")


def _positions(rows: list[dict]) -> dict[str, int]:
    return {str(row.get("msg_id")): position for position, row in enumerate(rows)
            if isinstance(row, dict) and isinstance(row.get("msg_id"), str)}


def _valid_question_resolution_record(question: dict, resolution: dict, rows: list[dict]) -> bool:
    """Schema/authority/order check before any later provenance contest."""
    if (not isinstance(question, dict) or not isinstance(resolution, dict)
            or question.get("kind") != "question"
            or resolution.get("kind") != "question_resolution"
            or resolution.get("in_reply_to") != question.get("msg_id")):
        return False
    try:
        validate_question_resolution(resolution.get("body"))
    except MailboxError:
        return False
    actor = resolution.get("actor")
    if not (isinstance(actor, str) and (actor == question.get("actor") or actor.startswith("human:"))):
        return False
    positions = _positions(rows)
    question_position = positions.get(str(question.get("msg_id")))
    resolution_position = positions.get(str(resolution.get("msg_id")))
    if question_position is None or resolution_position is None or question_position >= resolution_position:
        return False
    evidence = resolution["body"].get("evidence_msg_ids")
    return evidence is None or all(positions.get(value, resolution_position) < resolution_position
                                   for value in evidence)


def _structured_self_report(evidence: dict, resolution: dict, claimed_actor: str,
                            reported_actual_actor: str) -> bool:
    """Recognize the two explicit self-report shapes used as contest evidence."""
    if evidence.get("kind") != "note" or evidence.get("actor") != reported_actual_actor:
        return False
    body = evidence.get("body")
    ref = body.get("ref") if isinstance(body, dict) else None
    if not isinstance(ref, dict):
        return False
    posted = ref.get("posted_row")
    command = ref.get("command")
    exact = (isinstance(posted, str) and posted.split(" ", 1)[0] == resolution.get("msg_id")
             and isinstance(command, str) and f"--as {claimed_actor}" in command)
    fault = ref.get("self_reported_fault")
    by_seq = (isinstance(resolution.get("seq"), int) and isinstance(fault, str)
              and f"seq {resolution['seq']}" in fault and f"--as {claimed_actor}" in fault
              and "by this session" in fault)
    return exact or by_seq


def is_valid_provenance_contestation(resolution: dict, contest_row: dict, rows: list[dict]) -> bool:
    """Whether a later reviewer/human note conservatively contests one resolution.

    Mailbox actor fields remain unauthenticated.  Two ordered, structured
    self-reports make the earlier label unsafe to trust; they do not prove the
    identity asserted by the contest.
    """
    if (not isinstance(resolution, dict) or resolution.get("kind") != "question_resolution"
            or not isinstance(contest_row, dict) or contest_row.get("kind") != "note"
            or contest_row.get("in_reply_to") != resolution.get("msg_id")
            or contest_row.get("to") not in {"all", "owner"}):
        return False
    actor = contest_row.get("actor")
    if not (actor in REVIEWERS or isinstance(actor, str) and actor.startswith("human:")):
        return False
    try:
        validate_provenance_contestation(contest_row.get("body"))
    except MailboxError:
        return False
    contest = contest_row["body"]["provenance_contestation"]
    if (contest["contested_msg_id"] != resolution.get("msg_id")
            or contest["claimed_actor"] != resolution.get("actor")):
        return False
    positions = _positions(rows)
    resolution_position = positions.get(str(resolution.get("msg_id")))
    contest_position = positions.get(str(contest_row.get("msg_id")))
    if resolution_position is None or contest_position is None or resolution_position >= contest_position:
        return False
    by_id = {row.get("msg_id"): row for row in rows if isinstance(row, dict)}
    evidence = [by_id.get(value) for value in contest["basis_msg_ids"]]
    return all(isinstance(row, dict)
               and resolution_position < positions.get(str(row.get("msg_id")), -1) < contest_position
               and _structured_self_report(row, resolution, contest["claimed_actor"],
                                           contest["reported_actual_actor"])
               for row in evidence)


def latest_provenance_contest(resolution: dict, rows: list[dict]) -> dict | None:
    """Newest valid conservative contest of ``resolution``, if any."""
    for row in reversed(rows):
        if is_valid_provenance_contestation(resolution, row, rows):
            return row
    return None


def is_valid_question_resolution(question: dict, resolution: dict, rows: list[dict]) -> bool:
    """Whether a recorded resolution remains valid after later contest evidence."""
    return (_valid_question_resolution_record(question, resolution, rows)
            and latest_provenance_contest(resolution, rows) is None)


def latest_question_contest(question: dict, rows: list[dict]) -> dict | None:
    """Newest valid contest of this question's otherwise-valid resolutions."""
    found = []
    for resolution in rows:
        if _valid_question_resolution_record(question, resolution, rows):
            contest = latest_provenance_contest(resolution, rows)
            if contest is not None:
                found.append(contest)
    positions = _positions(rows)
    return max(found, key=lambda row: positions.get(str(row.get("msg_id")), -1)) if found else None


def is_question_closed(question: dict, rows: list[dict]) -> bool:
    """Only an uncontested original-asker resolution is terminal."""
    eligible = live_rows(rows)
    if not isinstance(question, dict) or question.get("kind") != "question":
        return False
    matches = [row for row in eligible if row.get("kind") == "question"
               and row.get("msg_id") == question.get("msg_id")]
    if len(matches) != 1:
        return False
    return _question_closed_in_live_rows(matches[0], eligible)


def _question_closed_in_live_rows(question: dict, rows: list[dict]) -> bool:
    """Terminal predicate for an already quarantined ordered mailbox view.

    ``human:*`` is a freely writable actor label.  It is useful attribution
    evidence, but it is not authentication and must never turn a claimed owner
    answer (or claimed human disposition) into a terminal fact.  The original
    asker may still publish a non-owner disposition, subject to the existing
    contest/reopening rules.
    """
    return any(
        (is_valid_question_resolution(question, row, rows)
         and row.get("actor") == question.get("actor"))
        for row in rows)


def _durably_sync(path: Path, handle=None) -> None:
    """Flush the append and its directory before reporting a durable receipt."""
    try:
        if handle is not None:
            os.fsync(handle.fileno())
        else:
            file_descriptor = os.open(path, os.O_RDONLY)
            try:
                os.fsync(file_descriptor)
            finally:
                os.close(file_descriptor)
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        directory = os.open(path.parent, directory_flags)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError as exc:
        raise MailboxError("mailbox durability is unconfirmed; reconcile before retrying") from exc


def _read_serialized(data: bytes) -> list[dict]:
    """Verify one complete serialized mailbox prefix without changing it."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MailboxError("mailbox is not UTF-8") from exc
    rows, prev = [], None
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise MailboxError(f"mailbox line {number} is not JSON: {exc}") from None
        if not isinstance(row, dict):
            raise MailboxError(f"mailbox line {number} is not an object")
        claimed = row.get("row_sha256")
        check = dict(row)
        check.pop("row_sha256", None)
        if row.get("prev_sha256") != prev or hashlib.sha256(_canonical(check)).hexdigest() != claimed:
            raise MailboxError(f"mailbox chain broken at line {number}")
        rows.append(row)
        prev = claimed
    return rows


def read(path: Path = PATH) -> list[dict]:
    """All rows, with the hash chain verified; a break raises. The chain detects edits in place;
    it cannot detect a truncated tail or a chain re-hashed from the edit onward."""
    if not path.exists():
        return []
    return _read_serialized(path.read_bytes())


def _recover_torn_tail_locked(path: Path) -> None:
    """Preserve a complete final row or discard only a verified incomplete tail.

    A crash or a real short write can leave bytes after the last newline.  The
    First try the whole final line: a complete hash-valid row without only its
    newline is observed evidence and gets that newline restored.  Otherwise,
    the complete prefix is hash-verified and only the invalid unterminated
    suffix is removed.  Every repair crosses the file/directory durability
    boundary; a newline-terminated corrupt row is never silently repaired.
    """
    if not path.exists():
        return
    data = path.read_bytes()
    if not data or data.endswith(b"\n"):
        return
    try:
        _read_serialized(data)
    except MailboxError:
        pass
    else:
        try:
            with path.open("r+b", buffering=0) as handle:
                handle.seek(0, os.SEEK_END)
                offset = handle.tell()
                if handle.write(b"\n") != 1:
                    handle.truncate(offset)
                    _durably_sync(path, handle)
                    raise MailboxError("mailbox final-newline repair is unconfirmed; reconcile before retrying")
                _durably_sync(path, handle)
        except OSError as exc:
            raise MailboxError("mailbox final-newline repair is unconfirmed; reconcile before retrying") from exc
        return
    boundary = data.rfind(b"\n") + 1
    prefix = data[:boundary]
    _read_serialized(prefix)
    try:
        with path.open("r+b", buffering=0) as handle:
            handle.truncate(boundary)
            _durably_sync(path, handle)
    except OSError as exc:
        raise MailboxError("mailbox torn-tail recovery is unconfirmed; reconcile before retrying") from exc


def _rollback_short_append_locked(path: Path, handle, offset: int) -> None:
    """Undo a partial append under the writer lock and persist the known prefix."""
    try:
        handle.truncate(offset)
        _durably_sync(path, handle)
    except OSError as exc:
        raise MailboxError("mailbox short-write rollback is unconfirmed; reconcile before retrying") from exc


def _validate_post(actor: str, kind: str, body: dict, to: str, in_reply_to: str | None) -> None:
    if not _actor_ok(actor):
        raise MailboxError(f"unknown actor {actor!r}")
    if not isinstance(kind, str) or kind not in KINDS or not (
            actor in KINDS[kind] or (actor.startswith("human:") and kind in HUMAN_KINDS)):
        raise MailboxError(f"{actor} may not post {kind}")
    if not isinstance(to, str) or to not in RECIPIENTS:
        raise MailboxError(f"to must be one of {sorted(RECIPIENTS)}")
    if not isinstance(body, dict):
        raise MailboxError("body must be an object")
    if in_reply_to is not None and not isinstance(in_reply_to, str):
        raise MailboxError("in_reply_to must be a string or null")
    if kind == "plan_item":
        validate_plan_item(body)
    if kind == "receipt" and (not isinstance(body.get("state"), str)
                              or body.get("state") not in RECEIPT_STATES):
        raise MailboxError(f"receipt state must be one of {sorted(RECEIPT_STATES)}")
    if kind == "review" and (not isinstance(body.get("verdict"), str)
                             or body.get("verdict") not in VERDICTS):
        raise MailboxError(f"review verdict must be one of {sorted(VERDICTS)}")
    if kind in {"receipt", "withdraw", "answer", "review", "question_resolution"} and not in_reply_to:
        raise MailboxError(f"{kind} must reply to a message")
    if kind == "question_resolution":
        validate_question_resolution(body)
    if "provenance_contestation" in body:
        if kind != "note":
            raise MailboxError("provenance_contestation is valid only on a note")
        validate_provenance_contestation(body)
    title = body.get("title")
    consumer_visible_plan_ready = isinstance(title, str) and title.lstrip().startswith("PLAN READY")
    if kind == "note" and (body.get("event") == PLAN_READY_EVENT
                           or body.get("protocol") == PLAN_READY_PROTOCOL
                           or consumer_visible_plan_ready):
        raise MailboxError("PLAN READY event/protocol/title is reserved for publish-plan-ready")


def _lease_delta(expires_hours: float | None) -> timedelta | None:
    """Reject values which cannot produce a positive, representable lease."""
    if expires_hours is None:
        return None
    if type(expires_hours) not in {int, float} or isinstance(expires_hours, bool):
        raise MailboxError("expires_hours must be a positive finite number")
    try:
        if not math.isfinite(expires_hours) or expires_hours <= 0:
            raise MailboxError("expires_hours must be a positive finite number")
        lease = timedelta(hours=expires_hours)
        if lease <= timedelta(0):
            raise MailboxError("expires_hours must be a positive representable lease")
        return lease
    except (OverflowError, ValueError):
        raise MailboxError("expires_hours must be a positive representable lease") from None


def _validate_expires_hours(expires_hours: float | None) -> None:
    _lease_delta(expires_hours)


def _absolute_expiry(expires_hours: float | None, now: datetime) -> str | None:
    lease = _lease_delta(expires_hours)
    if lease is None:
        return None
    try:
        return (now + lease).isoformat()
    except (OverflowError, ValueError):
        raise MailboxError("expires_hours exceeds the representable expiry range") from None


def _append_locked(actor: str, kind: str, body: dict, *, to: str, in_reply_to: str | None,
                   expires_hours: float | None, path: Path, rows: list[dict]) -> dict:
    """Validate prefix-dependent constraints and append while holding the writer lock."""
    eligible = live_rows(rows)
    ids = {r["msg_id"] for r in eligible}
    if in_reply_to and in_reply_to not in ids:
        raise MailboxError(f"in_reply_to {in_reply_to} is not in the mailbox")
    if kind == "question_resolution":
        evidence = body.get("evidence_msg_ids") or []
        if any(value not in ids for value in evidence):
            raise MailboxError("question_resolution evidence_msg_ids must name preceding mailbox rows")
        original = next(row for row in eligible if row["msg_id"] == in_reply_to)
        if original.get("kind") != "question":
            raise MailboxError("question_resolution must reply to a question")
        if not (actor.startswith("human:") or actor == original.get("actor")):
            raise MailboxError("question_resolution must be posted by the question asker or a human")
        if _question_closed_in_live_rows(original, eligible):
            raise MailboxError("question is no longer open")
    if kind == "answer" and actor.startswith("human:"):
        original = next((row for row in eligible if row.get("msg_id") == in_reply_to), None)
        if (original is not None and original.get("kind") == "question"
                and _question_closed_in_live_rows(original, eligible)):
            raise MailboxError("question is no longer open")
    now = datetime.now(timezone.utc)
    row = {
        "schema": SCHEMA, "seq": len(rows) + 1, "ts": now.isoformat(), "actor": actor, "to": to,
        "kind": kind, "in_reply_to": in_reply_to, "body": body,
        "expires_at": _absolute_expiry(expires_hours, now),
        "prev_sha256": rows[-1]["row_sha256"] if rows else None,
    }
    row["msg_id"] = f"{actor.split(':')[0]}-{hashlib.sha256(_canonical(row)).hexdigest()[:16]}"
    row["row_sha256"] = hashlib.sha256(_canonical(row)).hexdigest()
    try:
        line = json.dumps(row, ensure_ascii=False)
        line_bytes = line.encode()
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise MailboxError("mailbox row is not UTF-8 JSON") from exc
    if len(line_bytes) > MAX_ROW_BYTES:
        raise MailboxError(f"row exceeds {MAX_ROW_BYTES} bytes")
    payload = line_bytes + b"\n"
    try:
        with path.open("ab", buffering=0) as handle:
            offset = handle.tell()
            try:
                written = handle.write(payload)
            except OSError:
                _rollback_short_append_locked(path, handle, offset)
                raise
            if written != len(payload):
                _rollback_short_append_locked(path, handle, offset)
                raise MailboxError("mailbox append was short and rolled back; retry safely")
            _durably_sync(path, handle)
    except OSError as exc:
        raise MailboxError("mailbox durability is unconfirmed; reconcile before retrying") from exc
    return row


def publish_plan_ready(*, branch: str, head_sha: str, plan_path: str, plan_sha256: str,
                       state_packet_path: str, state_packet_sha256: str,
                       path: Path = PATH, repo_root: Path = ROOT) -> tuple[dict, bool]:
    """Publish one source-verified daily-plan revision, never mutable file bytes.

    This is deliberately separate from ``post``: plan-ready titles are
    dashboard/runner inputs, and must bind Git objects plus their hashes.
    """
    if not isinstance(branch, str) or not branch:
        raise MailboxError("branch must be a non-empty local branch name")
    _git(repo_root, "check-ref-format", "--branch", branch)
    if not isinstance(head_sha, str) or not GIT_SHA1.fullmatch(head_sha):
        raise MailboxError("head_sha must be a full lowercase Git SHA-1")
    plan_match = PLAN_REVISION_PATH.fullmatch(plan_path) if isinstance(plan_path, str) else None
    if not plan_match:
        raise MailboxError("plan_path must be an immutable run_state/daily_plans/YYYY-MM-DD-rN.json revision")
    try:
        datetime.strptime(plan_match.group("date"), "%Y-%m-%d")
    except ValueError:
        raise MailboxError("plan_path must contain a real ISO calendar date") from None
    date, revision = plan_match.group("date", "revision")
    state_packet_path = _repo_file_path(state_packet_path, label="state_packet_path")
    _require_sha256(plan_sha256, label="plan_sha256")
    _require_sha256(state_packet_sha256, label="state_packet_sha256")
    body = _plan_ready_body(
        branch=branch, head_sha=head_sha, plan_path=plan_path, plan_sha256=plan_sha256,
        state_packet_path=state_packet_path, state_packet_sha256=state_packet_sha256,
        date=date, revision=revision,
    )
    # An immutable receipt remains a valid retry even when its local branch has
    # since moved. A duplicate check occurs again under the append lock.
    with _mailbox_lock(path):
        _recover_torn_tail_locked(path)
        duplicate = _plan_ready_duplicate_or_conflict(read(path), body)
        if duplicate is not None:
            return duplicate, True
    resolved = _git(repo_root, "rev-parse", "--verify", f"refs/heads/{branch}^{{commit}}")
    if resolved.decode().strip() != head_sha:
        raise MailboxError("branch does not resolve to head_sha")
    _git(repo_root, "cat-file", "-e", f"{head_sha}^{{commit}}")
    plan_bytes = _committed_blob(repo_root, head_sha, plan_path, maximum_bytes=MAX_PLAN_BYTES)
    packet_bytes = _committed_blob(repo_root, head_sha, state_packet_path,
                                   maximum_bytes=MAX_STATE_PACKET_BYTES)
    if hashlib.sha256(plan_bytes).hexdigest() != plan_sha256:
        raise MailboxError("plan_sha256 does not match the committed plan bytes")
    if hashlib.sha256(packet_bytes).hexdigest() != state_packet_sha256:
        raise MailboxError("state_packet_sha256 does not match the committed state packet bytes")
    try:
        plan = json.loads(plan_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MailboxError(f"committed plan is not UTF-8 JSON: {exc}") from None
    if not isinstance(plan, dict):
        raise MailboxError("committed plan must be a JSON object")
    if plan.get("date") != date or plan.get("revision") != revision:
        raise MailboxError("committed plan date/revision must match its immutable revision path")
    if plan.get("state_packet_sha256") != state_packet_sha256:
        raise MailboxError("committed plan state_packet_sha256 does not bind the supplied committed packet")
    with _mailbox_lock(path):
        _recover_torn_tail_locked(path)
        rows = read(path)
        duplicate = _plan_ready_duplicate_or_conflict(rows, body)
        if duplicate is not None:
            return duplicate, True
        return _append_locked("oracle", "note", body, to="all", in_reply_to=None,
                              expires_hours=None, path=path, rows=rows), False


def post(actor: str, kind: str, body: dict, *, to: str, in_reply_to: str | None = None,
         expires_hours: float | None = None, path: Path = PATH) -> dict:
    body = _frozen_body(body)
    _validate_expires_hours(expires_hours)
    _validate_post(actor, kind, body, to, in_reply_to)
    with _mailbox_lock(path):
        _recover_torn_tail_locked(path)
        return _append_locked(actor, kind, body, to=to, in_reply_to=in_reply_to,
                              expires_hours=expires_hours, path=path, rows=read(path))


def post_if(actor: str, kind: str, body: dict, *, to: str, in_reply_to: str | None = None,
            expires_hours: float | None = None, path: Path = PATH,
            condition: Callable[[list[dict]], bool]) -> dict | None:
    """Append only if ``condition`` accepts the same locked mailbox prefix."""
    body = _frozen_body(body)
    _validate_expires_hours(expires_hours)
    _validate_post(actor, kind, body, to, in_reply_to)
    if not callable(condition):
        raise MailboxError("condition must be callable")
    with _mailbox_lock(path):
        _recover_torn_tail_locked(path)
        rows = read(path)
        if not condition(rows):
            return None
        return _append_locked(actor, kind, body, to=to, in_reply_to=in_reply_to,
                              expires_hours=expires_hours, path=path, rows=rows)


def post_once(actor: str, kind: str, body: dict, *, to: str, in_reply_to: str | None = None,
              idempotency_key: str, require_open_question: bool = False,
              expires_hours: float | None = None, path: Path = PATH,
              linearization_check: Callable[[], None] | None = None) -> tuple[dict, bool]:
    """Atomically append one owner-UI request and return a durable retry receipt.

    ``linearization_check`` runs under the writer lock immediately before a
    new append.  A caller may bind acceptance to mutable external state at
    that instant; durable retries return their existing row before the check.
    """
    body = _frozen_body(body)
    _validate_expires_hours(expires_hours)
    _validate_post(actor, kind, body, to, in_reply_to)
    if not isinstance(idempotency_key, str) or not idempotency_key:
        raise MailboxError("idempotency_key must be a non-empty string")
    if body.get("request_id") != idempotency_key:
        raise MailboxError("body.request_id must equal idempotency_key")
    with _mailbox_lock(path):
        _recover_torn_tail_locked(path)
        rows = read(path)
        eligible = live_rows(rows)
        existing = [row for row in eligible if isinstance(row.get("body"), dict)
                    and row["body"].get("request_id") == idempotency_key]
        if existing:
            row = existing[-1]
            if (row.get("actor"), row.get("kind"), row.get("to"), row.get("in_reply_to"), row.get("body")) != (
                    actor, kind, to, in_reply_to, body):
                raise MailboxError("idempotency_key was already used for a different request")
            # A prior interrupted call can have left an otherwise readable row.
            # Do not turn that into a success receipt until both the file and
            # directory are synchronized by this retry.
            _durably_sync(path)
            return row, True
        if require_open_question:
            question = next((row for row in eligible if row.get("msg_id") == in_reply_to
                             and row.get("kind") == "question" and row.get("to") == "owner"), None)
            if question is None:
                raise MailboxError("owner question is no longer open")
            if _question_closed_in_live_rows(question, eligible):
                raise MailboxError("owner question is no longer open")
        if linearization_check is not None:
            linearization_check()
        row = _append_locked(actor, kind, body, to=to, in_reply_to=in_reply_to,
                             expires_hours=expires_hours, path=path, rows=rows)
        return row, False


def find_idempotency_key(idempotency_key: str, *, path: Path = PATH) -> dict | None:
    """Look up an owner-UI request receipt while holding the mailbox lock."""
    if not isinstance(idempotency_key, str) or not idempotency_key:
        raise MailboxError("idempotency_key must be a non-empty string")
    with _mailbox_lock(path):
        _recover_torn_tail_locked(path)
        existing = [row for row in live_rows(read(path)) if isinstance(row.get("body"), dict)
                    and row["body"].get("request_id") == idempotency_key]
        if not existing:
            return None
        # This lookup feeds retry receipts in the owner route.  A readable row
        # left by an interrupted append must cross the same file+directory
        # durability boundary before it can be reported as accepted.
        _durably_sync(path)
        return existing[-1]


def fold(rows: list[dict], now: datetime | None = None, *, already_live: bool = False) -> dict:
    """Plan items with malformed evidence omitted from live state.

    UI read models which already called :func:`live_rows` pass
    ``already_live=True`` so sequence gaps left by quarantine are not mistaken
    for new malformed evidence. Raw mailbox readers keep the safe default.
    """
    now = now or datetime.now(timezone.utc)
    items = {}
    for row in rows if already_live else live_rows(rows):
        if row["kind"] == "plan_item":
            expired = bool(row.get("expires_at")) and datetime.fromisoformat(row["expires_at"]) < now
            items[row["msg_id"]] = {"item": row, "state": "expired" if expired else "open", "receipts": []}
        elif row["kind"] in {"receipt", "withdraw"} and row.get("in_reply_to") in items:
            entry = items[row["in_reply_to"]]
            entry["receipts"].append(row)
            if entry["state"] in TERMINAL:
                continue
            entry["state"] = "withdrawn" if row["kind"] == "withdraw" else row["body"]["state"]
    return items


def _list_summary(body: object) -> str:
    """Return the safe, useful one-line mailbox summary for the CLI."""
    if not isinstance(body, dict):
        return ""
    for key in ("title", "question", "summary", "state", "verdict", "text"):
        value = body.get(key)
        if isinstance(value, str) and value:
            return value[:80]
    return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("post")
    p.add_argument("--as", dest="actor", required=True)
    p.add_argument("--kind", required=True)
    p.add_argument("--to", required=True)
    p.add_argument("--body-file", type=Path)
    p.add_argument("--body")
    p.add_argument("--in-reply-to")
    p.add_argument("--expires-hours", type=float)
    ready = sub.add_parser("publish-plan-ready", help="post one verified committed PLAN READY announcement")
    ready.add_argument("--branch", required=True, help="local branch that must resolve to --head-sha")
    ready.add_argument("--head-sha", required=True, help="full committed Git SHA-1")
    ready.add_argument("--plan-path", required=True, help="run_state/daily_plans/YYYY-MM-DD-rN.json")
    ready.add_argument("--plan-sha256", required=True)
    ready.add_argument("--state-packet-path", required=True)
    ready.add_argument("--state-packet-sha256", required=True)
    lst = sub.add_parser("list")
    lst.add_argument("--to")
    lst.add_argument("--kind")
    lst.add_argument("--last", type=int, default=20)
    sub.add_parser("fold")
    sh = sub.add_parser("show")
    sh.add_argument("msg_id")
    args = parser.parse_args(argv)
    try:
        if args.command == "post":
            body = json.loads(args.body_file.read_text() if args.body_file else (args.body or "{}"))
            row = post(args.actor, args.kind, body, to=args.to, in_reply_to=args.in_reply_to,
                       expires_hours=args.expires_hours)
            print(json.dumps({"msg_id": row["msg_id"], "seq": row["seq"]}))
        elif args.command == "publish-plan-ready":
            row, duplicate = publish_plan_ready(
                branch=args.branch, head_sha=args.head_sha, plan_path=args.plan_path,
                plan_sha256=args.plan_sha256, state_packet_path=args.state_packet_path,
                state_packet_sha256=args.state_packet_sha256,
            )
            print(json.dumps({"msg_id": row["msg_id"], "seq": row["seq"], "duplicate": duplicate}))
        elif args.command == "list":
            rows = [r for r in read() if (not args.to or r["to"] in {args.to, "all"})
                    and (not args.kind or r["kind"] == args.kind)]  # an inbox includes broadcasts
            for r in rows[-args.last:]:
                summary = _list_summary(r.get("body"))
                print(json.dumps({"seq": r["seq"], "msg_id": r["msg_id"], "actor": r["actor"], "to": r["to"],
                                  "kind": r["kind"], "re": r.get("in_reply_to"), "summary": summary}))
        elif args.command == "fold":
            view = {k: {"title": v["item"]["body"]["title"], "state": v["state"],
                        "last": v["receipts"][-1]["body"] if v["receipts"] else None}
                    for k, v in fold(read()).items()}
            print(json.dumps(view, indent=2))
        else:
            match = [r for r in read() if r["msg_id"] == args.msg_id]
            print(json.dumps(match[0] if match else None, indent=2))
    except MailboxError as exc:
        print(f"mailbox: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
