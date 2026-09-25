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
import fcntl
import hashlib
import json
import re
import sys
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "run_state/oracle_nara_mailbox.jsonl"
SCHEMA = "oracle-nara-mailbox/v1"
MAX_ROW_BYTES = 16 * 1024
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


class MailboxError(ValueError):
    pass


def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _actor_ok(actor: str) -> bool:
    return actor in AGENTS or bool(re.fullmatch(r"human:[a-z0-9_.-]{1,40}", actor))


def validate_plan_item(body: dict) -> None:
    """Structure only; the lane applies admission policy."""
    need = {"title", "objective", "task_class", "allowed_write_paths", "acceptance"}
    missing = need - set(body)
    if missing:
        raise MailboxError(f"plan_item missing {sorted(missing)}")
    if body["task_class"] not in TASK_CLASSES:
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
    if body["disposition"] not in QUESTION_RESOLUTIONS:
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
    """One direct human answer or one uncontested valid resolution is terminal."""
    if question.get("kind") != "question":
        return False
    return any(
        is_valid_question_resolution(question, row, rows)
        or (row.get("in_reply_to") == question.get("msg_id") and row.get("kind") == "answer"
            and isinstance(row.get("actor"), str) and row["actor"].startswith("human:"))
        for row in rows)


def read(path: Path = PATH) -> list[dict]:
    """All rows, with the hash chain verified; a break raises. The chain detects edits in place;
    it cannot detect a truncated tail or a chain re-hashed from the edit onward."""
    if not path.exists():
        return []
    rows, prev = [], None
    for number, line in enumerate(path.read_text().splitlines(), 1):
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


def _validate_post(actor: str, kind: str, body: dict, to: str, in_reply_to: str | None) -> None:
    if not _actor_ok(actor):
        raise MailboxError(f"unknown actor {actor!r}")
    if kind not in KINDS or not (actor in KINDS[kind] or (actor.startswith("human:") and kind in HUMAN_KINDS)):
        raise MailboxError(f"{actor} may not post {kind}")
    if to not in RECIPIENTS:
        raise MailboxError(f"to must be one of {sorted(RECIPIENTS)}")
    if not isinstance(body, dict):
        raise MailboxError("body must be an object")
    if kind == "plan_item":
        validate_plan_item(body)
    if kind == "receipt" and body.get("state") not in RECEIPT_STATES:
        raise MailboxError(f"receipt state must be one of {sorted(RECEIPT_STATES)}")
    if kind == "review" and body.get("verdict") not in VERDICTS:
        raise MailboxError(f"review verdict must be one of {sorted(VERDICTS)}")
    if kind in {"receipt", "withdraw", "answer", "review", "question_resolution"} and not in_reply_to:
        raise MailboxError(f"{kind} must reply to a message")
    if kind == "question_resolution":
        validate_question_resolution(body)
    if "provenance_contestation" in body:
        if kind != "note":
            raise MailboxError("provenance_contestation is valid only on a note")
        validate_provenance_contestation(body)


def _append_locked(actor: str, kind: str, body: dict, *, to: str, in_reply_to: str | None,
                   expires_hours: float | None, path: Path, rows: list[dict]) -> dict:
    """Validate prefix-dependent constraints and append while holding the writer lock."""
    ids = {r["msg_id"] for r in rows}
    if in_reply_to and in_reply_to not in ids:
        raise MailboxError(f"in_reply_to {in_reply_to} is not in the mailbox")
    if kind == "question_resolution":
        evidence = body.get("evidence_msg_ids") or []
        if any(value not in ids for value in evidence):
            raise MailboxError("question_resolution evidence_msg_ids must name preceding mailbox rows")
        original = next(row for row in rows if row["msg_id"] == in_reply_to)
        if original.get("kind") != "question":
            raise MailboxError("question_resolution must reply to a question")
        if not (actor.startswith("human:") or actor == original.get("actor")):
            raise MailboxError("question_resolution must be posted by the question asker or a human")
        if is_question_closed(original, rows):
            raise MailboxError("question is no longer open")
    if kind == "answer" and actor.startswith("human:"):
        original = next((row for row in rows if row.get("msg_id") == in_reply_to), None)
        if (original is not None and original.get("kind") == "question"
                and is_question_closed(original, rows)):
            raise MailboxError("question is no longer open")
    now = datetime.now(timezone.utc)
    row = {
        "schema": SCHEMA, "seq": len(rows) + 1, "ts": now.isoformat(), "actor": actor, "to": to,
        "kind": kind, "in_reply_to": in_reply_to, "body": body,
        "expires_at": (now + timedelta(hours=expires_hours)).isoformat() if expires_hours else None,
        "prev_sha256": rows[-1]["row_sha256"] if rows else None,
    }
    row["msg_id"] = f"{actor.split(':')[0]}-{hashlib.sha256(_canonical(row)).hexdigest()[:16]}"
    row["row_sha256"] = hashlib.sha256(_canonical(row)).hexdigest()
    line = json.dumps(row, ensure_ascii=False)
    if len(line.encode()) > MAX_ROW_BYTES:
        raise MailboxError(f"row exceeds {MAX_ROW_BYTES} bytes")
    with path.open("a") as handle:
        handle.write(line + "\n")
    return row


def post(actor: str, kind: str, body: dict, *, to: str, in_reply_to: str | None = None,
         expires_hours: float | None = None, path: Path = PATH) -> dict:
    _validate_post(actor, kind, body, to, in_reply_to)
    path.parent.mkdir(parents=True, exist_ok=True)
    with (path.parent / ".oracle_nara_mailbox.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _append_locked(actor, kind, body, to=to, in_reply_to=in_reply_to,
                              expires_hours=expires_hours, path=path, rows=read(path))


def post_once(actor: str, kind: str, body: dict, *, to: str, in_reply_to: str | None = None,
              idempotency_key: str, require_open_question: bool = False,
              expires_hours: float | None = None, path: Path = PATH,
              linearization_check: Callable[[], None] | None = None) -> tuple[dict, bool]:
    """Atomically append one owner-UI request and return a durable retry receipt.

    ``linearization_check`` runs under the writer lock immediately before a
    new append.  A caller may bind acceptance to mutable external state at
    that instant; durable retries return their existing row before the check.
    """
    _validate_post(actor, kind, body, to, in_reply_to)
    if not isinstance(idempotency_key, str) or not idempotency_key:
        raise MailboxError("idempotency_key must be a non-empty string")
    if body.get("request_id") != idempotency_key:
        raise MailboxError("body.request_id must equal idempotency_key")
    path.parent.mkdir(parents=True, exist_ok=True)
    with (path.parent / ".oracle_nara_mailbox.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        rows = read(path)
        existing = [row for row in rows if isinstance(row.get("body"), dict)
                    and row["body"].get("request_id") == idempotency_key]
        if existing:
            row = existing[-1]
            if (row.get("actor"), row.get("kind"), row.get("to"), row.get("in_reply_to"), row.get("body")) != (
                    actor, kind, to, in_reply_to, body):
                raise MailboxError("idempotency_key was already used for a different request")
            return row, True
        if require_open_question:
            question = next((row for row in rows if row.get("msg_id") == in_reply_to
                             and row.get("kind") == "question" and row.get("to") == "owner"), None)
            if question is None:
                raise MailboxError("owner question is no longer open")
            if is_question_closed(question, rows):
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
    path.parent.mkdir(parents=True, exist_ok=True)
    with (path.parent / ".oracle_nara_mailbox.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        existing = [row for row in read(path) if isinstance(row.get("body"), dict)
                    and row["body"].get("request_id") == idempotency_key]
        return existing[-1] if existing else None


def fold(rows: list[dict], now: datetime | None = None) -> dict:
    """Plan items with their latest state and full receipt history."""
    now = now or datetime.now(timezone.utc)
    items = {}
    for row in rows:
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
        elif args.command == "list":
            rows = [r for r in read() if (not args.to or r["to"] in {args.to, "all"})
                    and (not args.kind or r["kind"] == args.kind)]  # an inbox includes broadcasts
            for r in rows[-args.last:]:
                summary = (r["body"].get("title") or r["body"].get("state") or r["body"].get("verdict")
                           or r["body"].get("text", "")[:80])
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
