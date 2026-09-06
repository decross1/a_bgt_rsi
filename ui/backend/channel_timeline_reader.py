"""Structured, read-only transport for the lab-channel timeline.

``orchestrator.lab_channel.timeline`` already owns the merged timeline.  Its
human-facing CLI renders rows as formatted text, which cannot preserve the
boundary between a multiline message and a following row.  This UI-owned
helper calls that same pure function and emits one versioned JSON envelope so
the backend seam never has to infer boundaries from message text.

This module does not authenticate actor labels or attest source completeness.
It only preserves the rows returned by the existing timeline reader.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from typing import Any

TIMELINE_SCHEMA = "lab-channel-timeline/v1"


def _framed_rows(value: Any) -> list[dict[str, str]]:
    """Validate the minimum transport shape and preserve row boundaries."""
    if not isinstance(value, list):
        raise ValueError("timeline() returned a non-list result")

    framed: list[dict[str, str]] = []
    for index, row in enumerate(value):
        if not isinstance(row, dict):
            raise ValueError(f"timeline row {index} is not an object")
        ts = row.get("ts")
        kind = row.get("kind")
        message = row.get("message", "")
        if not isinstance(ts, str) or not ts:
            raise ValueError(f"timeline row {index} has invalid ts")
        if not isinstance(kind, str) or not kind:
            raise ValueError(f"timeline row {index} has invalid kind")
        if not isinstance(message, str):
            raise ValueError(f"timeline row {index} has invalid message")
        framed.append({"ts": ts, "kind": kind, "message": message})
    return framed


def build_envelope(
    *,
    since: str | None = None,
    limit: int | None = None,
    timeline_fn: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Return the versioned transport envelope for the existing timeline."""
    if timeline_fn is None:
        # Keep imports side-effect free for the backend and its offline tests.
        # The helper process resolves the existing orchestrator reader only
        # when it actually services a timeline read.
        from orchestrator.lab_channel import timeline as timeline_fn
    rows = timeline_fn(since=since, limit=limit)
    return {"schema": TIMELINE_SCHEMA, "rows": _framed_rows(rows)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="channel_timeline_reader",
        description="Emit the existing lab-channel timeline as framed JSON.",
    )
    parser.add_argument("--since", default=None)
    parser.add_argument("--limit", type=int, default=None)
    return parser


def main(
    argv: list[str] | None = None,
    *,
    timeline_fn: Callable[..., Any] | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    try:
        envelope = build_envelope(
            since=args.since,
            limit=args.limit,
            timeline_fn=timeline_fn,
        )
    except (KeyError, OSError, TypeError, ValueError) as exc:
        print(f"timeline read failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(envelope, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
