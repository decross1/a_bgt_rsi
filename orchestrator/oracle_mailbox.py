"""Two-way Oracle <-> Nara mailbox (owner direction 2026-09-22, D-082).

Oracle sets the plan; Nara implements it and reports. One append-only JSONL
log under a file lock; every row names its actor and kind. Attribution is
honest but not authenticated (the D-067 lesson): the hash chain shows order
and detects in-place edits; it does not prove identity. The mailbox never carries approvals; owner
authority is D-082's standing mandate plus the owner's own channels.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import re
import sys
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
KINDS = {
    "plan_item": {"oracle"},        # Oracle -> Nara work order
    "withdraw": {"oracle"},         # Oracle cancels an open plan item
    "receipt": {"nara"},            # Nara -> Oracle progress / outcome
    "question": CONVERSANTS,
    "answer": CONVERSANTS,
    "note": AGENTS,
}
HUMAN_KINDS = {"question", "answer", "note"}
RECIPIENTS = {"oracle", "nara", "claude", "codex", "owner", "all"}
RECEIPT_STATES = {"held", "claimed", "validated", "failed", "withdrawn"}
TERMINAL = {"validated", "failed", "withdrawn"}
TASK_CLASSES = {"documentation", "tests", "tooling", "experiment_code", "lab_organization"}


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


def post(actor: str, kind: str, body: dict, *, to: str, in_reply_to: str | None = None,
         expires_hours: float | None = None, path: Path = PATH) -> dict:
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
    if kind in {"receipt", "withdraw", "answer"} and not in_reply_to:
        raise MailboxError(f"{kind} must reply to a message")
    path.parent.mkdir(parents=True, exist_ok=True)
    with (path.parent / ".oracle_nara_mailbox.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        rows = read(path)
        ids = {r["msg_id"] for r in rows}
        if in_reply_to and in_reply_to not in ids:
            raise MailboxError(f"in_reply_to {in_reply_to} is not in the mailbox")
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
                summary = r["body"].get("title") or r["body"].get("state") or r["body"].get("text", "")[:80]
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
