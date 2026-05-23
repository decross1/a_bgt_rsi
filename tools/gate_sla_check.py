#!/usr/bin/env python3
"""SLA sweeper for soft-gate attestations and hard-gate escalations.

Reads:
  - run_state/week1.state.json (state.human_gates_pending)
  - run_state/attestations.jsonl (soft-gate request entries)

Appends:
  - run_state/attestations.jsonl (no_objection entries when soft-gate SLA expires)
  - run_state/escalations.jsonl (hard_gate_sla_expired entries when 48h passes)

Track A writes to state.human_gates_pending; this tool never mutates state.json
directly. It is intended to be run on a cron (every 15 minutes) and called
ad-hoc as `python3 tools/gate_sla_check.py --dry-run` for inspection.

See agent/autonomy.md §2 for the full SLA framework.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
STATE_FILE = REPO_ROOT / "run_state" / "week1.state.json"
ATTESTATIONS = REPO_ROOT / "run_state" / "attestations.jsonl"
ESCALATIONS = REPO_ROOT / "run_state" / "escalations.jsonl"

SOFT_SLA_HOURS = 4
HARD_SLA_HOURS = 48


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _read_jsonl(path: pathlib.Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "_schema_comment" in rec:
                continue
            out.append(rec)
    return out


def _parse_ts(ts: str) -> _dt.datetime:
    return _dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))


def find_expired_soft_gates(attestations: list[dict], now: _dt.datetime) -> list[dict]:
    """Return open `request` entries whose SLA has expired."""
    by_task: dict[str, dict] = {}
    for rec in attestations:
        kind = rec.get("kind")
        task_id = rec.get("task_id")
        if not task_id:
            continue
        if kind == "request":
            by_task[task_id] = rec
        elif kind in {"approved", "rejected", "no_objection"}:
            by_task.pop(task_id, None)
    expired: list[dict] = []
    for rec in by_task.values():
        sla_hours = rec.get("sla_hours", SOFT_SLA_HOURS)
        request_ts = _parse_ts(rec["ts"])
        if (now - request_ts).total_seconds() >= sla_hours * 3600:
            expired.append(rec)
    return expired


def find_expired_hard_gates(state: dict, now: _dt.datetime) -> list[dict]:
    """Return entries in state.human_gates_pending whose 48h SLA has expired."""
    pending = state.get("human_gates_pending", [])
    if not pending:
        return []
    if pending and isinstance(pending[0], str):
        # Older format: just a list of task IDs without timestamps. We cannot
        # SLA-check those without a timestamp; report them as undated.
        return [{"task_id": t, "undated": True} for t in pending]
    expired: list[dict] = []
    for rec in pending:
        gate_ts = _parse_ts(rec.get("ts", rec.get("gate_ts", now.isoformat())))
        if (now - gate_ts).total_seconds() >= HARD_SLA_HOURS * 3600:
            expired.append(rec)
    return expired


def append_no_objection(rec: dict, now: _dt.datetime, dry_run: bool) -> None:
    entry = {
        "kind": "no_objection",
        "task_id": rec["task_id"],
        "agent_id": "tools/gate_sla_check.py",
        "original_request_ts": rec["ts"],
        "cleared_ts": now.isoformat(),
        "reason": f"soft-gate SLA ({rec.get('sla_hours', SOFT_SLA_HOURS)}h) expired without human input",
    }
    if dry_run:
        print(f"[dry-run] would append no_objection: {entry}")
        return
    with ATTESTATIONS.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def append_escalation(rec: dict, now: _dt.datetime, dry_run: bool) -> None:
    entry = {
        "kind": "hard_gate_sla_expired",
        "task_id": rec.get("task_id"),
        "gate_ts": rec.get("ts", rec.get("gate_ts")),
        "expired_at": now.isoformat(),
        "notification_sent": False,
        "ts": now.isoformat(),
    }
    if dry_run:
        print(f"[dry-run] would append escalation: {entry}")
        return
    with ESCALATIONS.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="Report findings; do not write anything.")
    args = ap.parse_args()

    now = _now()
    attestations = _read_jsonl(ATTESTATIONS)

    soft_expired = find_expired_soft_gates(attestations, now)
    print(f"Soft-gate SLA-expired requests: {len(soft_expired)}")
    for rec in soft_expired:
        append_no_objection(rec, now, args.dry_run)

    state: dict = {}
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            print(f"warning: {STATE_FILE} is not valid JSON; skipping hard-gate sweep.",
                  file=sys.stderr)

    hard_expired = find_expired_hard_gates(state, now)
    print(f"Hard-gate SLA-expired entries: {len(hard_expired)}")
    for rec in hard_expired:
        if rec.get("undated"):
            print(f"  undated hard-gate (cannot SLA-check): {rec['task_id']}")
            continue
        append_escalation(rec, now, args.dry_run)

    return 0


if __name__ == "__main__":
    sys.exit(main())
