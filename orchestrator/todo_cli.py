"""Human write-back CLI — bubble acks + dev-session deferrals (D-046).

Two append-only ledgers, one writer each:

- `memory/coordinator_acks.jsonl` — acknowledgements of coordinator
  bubbles. The UI's human-TODO join (ui/backend/human_todo.py) keys on
  `bubble_run_id`; an acked bubble leaves the queue.
- `memory/dev_session_queue.jsonl` — "defer to dev session" attestations:
  the human routes a TODO item (any kind, incl. technical ones like a
  stale active_run) to the next Claude+human primary session instead of
  resolving it inline. The primary session triages open entries at
  startup (CLAUDE.md "How to start a primary session").

Mirrors orchestrator/gate_cli.py: validate-then-append, append-only open
mode, out-of-enum values REJECTED with nonzero exit — never coerced
(CLAUDE.md inviolate rule 4). Every subcommand prints the appended row as
JSON so a calling UI can surface it verbatim.
"""
from __future__ import annotations

import argparse

TODO_CLI_SCHEMA_VERSION = "todo_cli/1.0 (D-046)"
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ACKS_PATH = REPO_ROOT / "memory" / "coordinator_acks.jsonl"
QUEUE_PATH = REPO_ROOT / "memory" / "dev_session_queue.jsonl"

# The human-TODO item kinds (ui/backend/human_todo.py) a deferral may name.
DEFER_KINDS = (
    "gate_verdict",
    "finding_review",
    "bubble_ack",
    "stale_active_run",
    "state_gate",
)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _append(path: Path, row: dict) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def _read_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue  # malformed line: skip on read, never rewrite
        if isinstance(row, dict):
            rows.append(row)
    return rows


def ack(
    bubble_run_id: str,
    note: str = "",
    by: str = "human",
    *,
    path: Path | None = None,
    clock_iso: str | None = None,
) -> dict:
    """Append one bubble acknowledgement. Returns the row.

    path=None resolves to ACKS_PATH at call time (not def time) so tests
    can monkeypatch the module attribute.
    """
    path = Path(path) if path is not None else ACKS_PATH
    if not bubble_run_id.strip():
        raise ValueError("bubble_run_id must be non-empty")
    return _append(Path(path), {
        "bubble_run_id": bubble_run_id,
        "ack_by": by,
        "acked_at": clock_iso or _utcnow_iso(),
        "note": note,
    })


def defer(
    kind: str,
    ref_id: str,
    note: str,
    by: str = "human",
    *,
    path: Path | None = None,
    clock_iso: str | None = None,
) -> dict:
    """Append one open dev-session deferral. Returns the row.

    `note` is REQUIRED non-empty: the why is what the next session
    triages on. path=None resolves to QUEUE_PATH at call time.
    """
    path = Path(path) if path is not None else QUEUE_PATH
    if kind not in DEFER_KINDS:
        raise ValueError(f"kind {kind!r} is not one of {list(DEFER_KINDS)}")
    if not ref_id.strip():
        raise ValueError("ref_id must be non-empty")
    if not note.strip():
        raise ValueError("note is required — say why this needs a dev session")
    return _append(Path(path), {
        "ref_id": ref_id,
        "kind": kind,
        "note": note,
        "status": "open",
        "attested_by": by,
        "deferred_at": clock_iso or _utcnow_iso(),
    })


def close(
    ref_id: str,
    note: str = "",
    by: str = "human",
    *,
    path: Path | None = None,
    clock_iso: str | None = None,
) -> dict:
    """Append a closing row for an OPEN deferral. Append-only — the open
    row is never edited; readers fold by ref_id, last status wins.
    Closing a ref_id that is not currently open is an error (rule 4:
    a close that matches nothing must not look like it worked).
    path=None resolves to QUEUE_PATH at call time."""
    path = Path(path) if path is not None else QUEUE_PATH
    if ref_id not in {r["ref_id"] for r in list_deferred(path=path)}:
        raise ValueError(f"no open deferral with ref_id {ref_id!r}")
    return _append(Path(path), {
        "ref_id": ref_id,
        "status": "closed",
        "note": note,
        "closed_by": by,
        "closed_at": clock_iso or _utcnow_iso(),
    })


def list_deferred(*, path: Path | None = None) -> list[dict]:
    """Open deferrals, oldest-first: fold rows by ref_id, last status wins.
    path=None resolves to QUEUE_PATH at call time."""
    path = Path(path) if path is not None else QUEUE_PATH
    folded: dict[str, dict] = {}
    for row in _read_rows(Path(path)):
        ref = row.get("ref_id")
        if not ref:
            continue
        if row.get("status") == "closed":
            folded.pop(ref, None)
        elif row.get("status") == "open":
            folded[ref] = row  # last open row wins (freshest note)
    return list(folded.values())


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        import sys as _sys
        argv = _sys.argv[1:]
    if argv and argv[0] == "--version":
        print(TODO_CLI_SCHEMA_VERSION)
        return 0
    p = argparse.ArgumentParser(
        description="Bubble acks + dev-session deferrals (D-046).")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_ack = sub.add_parser("ack", help="acknowledge a coordinator bubble")
    p_ack.add_argument("--bubble-run-id", required=True)
    p_ack.add_argument("--note", default="")
    p_ack.add_argument("--by", default="human")

    p_def = sub.add_parser("defer", help="defer a TODO item to a dev session")
    p_def.add_argument("--kind", required=True, choices=DEFER_KINDS)
    p_def.add_argument("--ref-id", required=True)
    p_def.add_argument("--note", required=True)
    p_def.add_argument("--by", default="human")

    p_close = sub.add_parser("close", help="close an open deferral")
    p_close.add_argument("--ref-id", required=True)
    p_close.add_argument("--note", default="")
    p_close.add_argument("--by", default="human")

    sub.add_parser("list-deferred", help="print open deferrals, oldest-first")

    args = p.parse_args(argv)
    try:
        if args.cmd == "ack":
            out: object = ack(args.bubble_run_id, args.note, args.by)
        elif args.cmd == "defer":
            out = defer(args.kind, args.ref_id, args.note, args.by)
        elif args.cmd == "close":
            out = close(args.ref_id, args.note, args.by)
        else:  # list-deferred
            out = list_deferred()
    except ValueError as exc:
        print(f"rejected: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
