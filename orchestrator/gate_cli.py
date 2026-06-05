"""Step-8 human-gate feedback edge for LOOP_V0.

A human reviews a finished iteration and records a verdict. This CLI
validates the verdict against the frozen schema enum and appends one
row to memory/loop_feedback.jsonl. An invalid verdict is REJECTED with
a nonzero exit — never coerced to a neighbouring value (CLAUDE.md §4).

Mirrors orchestrator/journal_stub.py:finalize_iteration_record:
validate-then-append, append-only open mode.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import jsonschema

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "schema" / "loop_feedback.schema.json"
DEFAULT = REPO_ROOT / "memory" / "loop_feedback.jsonl"

_SCHEMA = json.loads(SCHEMA_PATH.read_text())
_VALIDATOR = jsonschema.Draft7Validator(_SCHEMA)
_VERDICTS = _SCHEMA["properties"]["verdict"]["enum"]


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def append_feedback(
    iteration_id: str,
    verdict: str,
    note: str = "",
    gated_by: str = "human",
    *,
    path: Path = DEFAULT,
    clock_iso: str | None = None,
) -> dict:
    """Build, schema-validate, and append one feedback row. Returns it.

    Raises jsonschema.ValidationError if the row (incl. an out-of-enum
    verdict) is malformed — nothing is written in that case.
    """
    if verdict not in _VERDICTS:
        raise jsonschema.ValidationError(
            f"verdict {verdict!r} is not one of {_VERDICTS}"
        )
    row = {
        "iteration_id": iteration_id,
        "verdict": verdict,
        "note": note,
        "gated_at": clock_iso or _utcnow_iso(),
        "gated_by": gated_by,
    }
    errs = list(_VALIDATOR.iter_errors(row))
    if errs:
        raise jsonschema.ValidationError(
            f"loop_feedback row invalid: {errs[0].message} "
            f"(path: {list(errs[0].absolute_path)})"
        )
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Record a Step-8 human-gate verdict.")
    p.add_argument("--iteration-id", required=True)
    p.add_argument("--verdict", required=True)
    p.add_argument("--note", default="")
    p.add_argument("--gated-by", default="human")
    args = p.parse_args(argv)

    if args.verdict not in _VERDICTS:
        p.error(
            f"verdict {args.verdict!r} is not one of {_VERDICTS} "
            f"(verdicts are never coerced)"
        )
    try:
        row = append_feedback(
            args.iteration_id, args.verdict, args.note, args.gated_by, path=DEFAULT
        )
    except jsonschema.ValidationError as exc:
        print(f"rejected: {exc.message}", file=sys.stderr)
        return 1
    print(json.dumps(row, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
