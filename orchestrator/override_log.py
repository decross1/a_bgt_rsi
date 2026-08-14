"""Human-override ledger appender for LOOP_V1.

When a human overrides an apparatus decision (skipping a gate outcome,
forcing an action the coordinator declined, etc.), the override is
recorded here — append-only, with its why. Overrides are human-only by
definition: a non-`human:` actor RAISES rather than being coerced
(CLAUDE.md inviolate rule 4).

Mirrors orchestrator/gate_cli.py: validate-then-append, append-only
open mode, injectable path for tests.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT = REPO_ROOT / "run_state" / "overrides.jsonl"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def record_override(
    *,
    actor: str,
    packet_id: str | None,
    action: str,
    rationale: str,
    path: Path = DEFAULT,
) -> dict:
    """Validate and append one override row. Returns the row.

    Rule: every override carries its why. Raises ValueError on an
    empty actor/action/rationale or a non-human actor — nothing is
    written in that case.
    """
    if not actor or not actor.startswith("human:"):
        raise ValueError(
            f"actor {actor!r} must start with 'human:' — overrides are "
            "human-only by definition"
        )
    if not action:
        raise ValueError("action must be non-empty")
    if not rationale:
        raise ValueError("rationale must be non-empty — every override carries its why")
    row = {
        "timestamp": _utcnow_iso(),
        "actor": actor,
        "packet_id": packet_id,
        "action": action,
        "rationale": rationale,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--actor", required=True)
    parser.add_argument("--action", required=True)
    parser.add_argument("--rationale", required=True)
    parser.add_argument("--packet-id", default=None)
    parser.add_argument("--path", type=Path, default=DEFAULT)
    args = parser.parse_args(argv)
    try:
        row = record_override(
            actor=args.actor,
            packet_id=args.packet_id,
            action=args.action,
            rationale=args.rationale,
            path=args.path,
        )
    except ValueError as exc:
        print(f"REJECTED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(row, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
