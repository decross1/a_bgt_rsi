"""LOOP_V1 P0 loop-health detectors + alert flag (A8 — non-spine).

The 06-18..06-25 runway showed the loop can run 2x/day and still STARVE
(promote 0, ledger silent) with nothing waving a flag. This module is the
honest-telemetry answer: three PURE detectors plus a tiny alert-flag writer
the cockpit / cron can poll.

  - staleness_gap(loop_memory_rows, now)  — "loop has not iterated in N days"
    (STALE_DAYS=2). Clock is INJECTED; the function never reads wall time.
  - ladder_gaps(ledger_state)             — "k open cluster(s) at Lx awaiting
    <next test owed>" over the idea-ledger state (workers/idea_ledger.py
    load_state shape). Only status=="open" clusters are gaps; L5 is terminal.
  - detect_stall(report, ledger_events_this_cycle) — a coordinator cycle with
    0 run_loop_iteration dispatches AND 0 promotions AND 0 ledger events is a
    stalled loop -> {"signal": "loop_stalled", "severity": "stalled", ...}.
    Any activity on any axis -> None (conservative: no false red).
  - write_alert_flag(path, level, reasons) — run_state/loop_alert.json
    {"level": "red"|"amber"|"ok", "reasons": [...], "updated_at": iso}.
    Path is injectable (tests use tmp_path); write is atomic (tmp+replace)
    because the cockpit polls the file.

CLI (cron/MAILTO-able):
    .venv-chroma/bin/python -m orchestrator.loop_health --check [--flag PATH]
exits 2 on red, 1 on amber, 0 on ok. A missing/unreadable/malformed flag file
exits 2 with a stderr message — fail LOUD, never a silent green (rule 4: an
absent signal is not a pass).

Pure Python, no LLM calls, no spine imports. Detectors never write; only
write_alert_flag touches disk, and only at the path it is handed.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any

# Loop cadence bar: more than this many days without a completed iteration is
# a staleness gap (LOOP_V1 P0; the D-049 runway target is 2 iterations/day).
STALE_DAYS = 2

# What each rung owes next (mirrors the workers/evidence_ladder.py contract;
# kept as local strings — this module must stay import-disjoint from the
# parallel-built workers). L5 is terminal: never a gap.
_NEXT_TEST = {
    "L0": "literature grounding (relevance + novel + critique survives) for L1",
    "L1": "experiment_outcome with trials >= 30 for L2",
    "L2": "cross-tier replication evidence for L3",
    "L3": "adversarial battery (vote survived + redteam proceed) for L4",
    "L4": "human validity verdict for L5",
}

_LEVELS = ("red", "amber", "ok")


def _parse_ts(value: Any) -> datetime | None:
    """ISO-8601 string -> aware UTC datetime, else None. Accepts 'Z' suffix
    and naive stamps (assumed UTC). Never raises on junk — the CALLER reports
    the no-parseable-timestamp case explicitly."""
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def staleness_gap(loop_memory_rows: list, now: datetime) -> str | None:
    """Return a human-readable staleness message, or None when fresh.

    Reads each row's ended_at (falling back to started_at) and compares the
    LATEST against the injected `now`. Three honest outcomes:
      - no rows at all            -> "loop has never iterated"
      - rows but no parseable ts  -> reported as such (not coerced to fresh)
      - gap >= STALE_DAYS days    -> "loop has not iterated in N days"
    A gap under the bar returns None.
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    rows = [r for r in (loop_memory_rows or []) if isinstance(r, dict)]
    if not rows:
        return "loop has never iterated (0 loop_memory rows)"

    latest_ts: datetime | None = None
    latest_id = None
    for row in rows:
        ts = _parse_ts(row.get("ended_at")) or _parse_ts(row.get("started_at"))
        if ts is not None and (latest_ts is None or ts > latest_ts):
            latest_ts = ts
            latest_id = row.get("iteration_id")
    if latest_ts is None:
        return (
            f"loop_memory has {len(rows)} row(s) but none carry a parseable "
            f"ended_at/started_at timestamp — staleness cannot be assessed"
        )

    gap_days = (now - latest_ts).total_seconds() / 86400.0
    if gap_days >= STALE_DAYS:
        return (
            f"loop has not iterated in {int(gap_days)} days "
            f"(last iteration {latest_id or 'unknown'} at "
            f"{latest_ts.isoformat()}; bar STALE_DAYS={STALE_DAYS})"
        )
    return None


def ladder_gaps(ledger_state: dict) -> list[str]:
    """One message per evidence level with OPEN clusters parked on it, e.g.
    "3 open cluster(s) at L3 awaiting adversarial battery (...)". Killed and
    surfaced clusters are not waiting on anything; L5 is terminal. Ordered
    L0..L4. Unknown/missing evidence_level is reported explicitly."""
    counts: dict[str, int] = {}
    unknown = 0
    for cluster in (ledger_state or {}).values():
        if not isinstance(cluster, dict) or cluster.get("status") != "open":
            continue
        level = cluster.get("evidence_level")
        if level in _NEXT_TEST:
            counts[level] = counts.get(level, 0) + 1
        elif level == "L5":
            continue  # terminal — nothing owed
        else:
            unknown += 1
    gaps = [
        f"{counts[level]} open cluster(s) at {level} awaiting {_NEXT_TEST[level]}"
        for level in sorted(counts)
    ]
    if unknown:
        gaps.append(
            f"{unknown} open cluster(s) with missing/unknown evidence_level "
            f"— ladder position cannot be assessed"
        )
    return gaps


def detect_stall(report: dict, ledger_events_this_cycle: int) -> dict | None:
    """A cycle that dispatched no iteration, PROMOTED nothing, and advanced
    no ledger cluster is a stalled loop.

    Promotions are counted by ACTUAL promoted findings, never by the
    promote_findings action having merely executed — the 2026-08-05..14
    zombie ran promote_findings every cycle, "passed" every time, and
    promoted zero. An empty-pool promote pass is NOT activity.
    run_loop_iteration counts on execution (any status: an attempt is
    activity)."""
    executed = [
        row for row in (report or {}).get("executed", [])
        if isinstance(row, dict)
    ]
    iteration_dispatches = sum(
        1 for row in executed if row.get("action") == "run_loop_iteration"
    )
    promotions = 0
    for row in executed:
        if row.get("action") != "promote_findings":
            continue
        result = row.get("result")
        if isinstance(result, dict):
            promoted = result.get("promoted")
            if isinstance(promoted, list):
                promotions += len(promoted)
    # Any other substantive executed action IS activity — run_experiment,
    # forecast_markets, mine_paper_gap, bubble_up are exactly what the D-059
    # planner prompt orders for ladder gaps; flagging such a cycle RED would
    # be a false alarm that trains alarm fatigue. Only noop and an
    # empty-pool promote pass are non-activity.
    other_actions = sum(
        1 for row in executed
        if row.get("action") not in (None, "noop", "promote_findings",
                                     "run_loop_iteration")
    )
    if (iteration_dispatches or promotions or other_actions
            or ledger_events_this_cycle):
        return None
    return {
        "signal": "loop_stalled",
        "severity": "stalled",
        "detail": (
            "coordinator cycle "
            f"{(report or {}).get('run_id', 'unknown')} dispatched 0 "
            "run_loop_iteration actions, promoted 0 findings, executed no "
            "other substantive action, and the idea ledger recorded 0 "
            "events this cycle — the loop did not move"
        ),
    }


def write_alert_flag(path, level: str, reasons: list[str]) -> None:
    """Write {"level", "reasons", "updated_at"} JSON to `path` atomically.
    level must be one of red|amber|ok and reasons a list of strings —
    anything else raises ValueError (never coerced)."""
    if level not in _LEVELS:
        raise ValueError(f"level must be one of {_LEVELS}, got {level!r}")
    if not isinstance(reasons, list) or not all(
        isinstance(r, str) for r in reasons
    ):
        raise ValueError("reasons must be a list of strings")
    payload = {
        "level": level,
        "reasons": reasons,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    path = os.fspath(path)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


# ── CLI ──────────────────────────────────────────────────────────────────

_DEFAULT_FLAG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "run_state", "loop_alert.json",
)

_EXIT_BY_LEVEL = {"ok": 0, "amber": 1, "red": 2}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Loop-health alert flag check (exit 0 ok / 1 amber / 2 red)."
    )
    p.add_argument("--check", action="store_true",
                   help="Read the alert flag and exit by level (cron-able).")
    p.add_argument("--flag", default=_DEFAULT_FLAG,
                   help="Path to loop_alert.json (default: run_state/).")
    args = p.parse_args(argv)
    if not args.check:
        p.print_help(sys.stderr)
        return 2
    try:
        with open(args.flag, encoding="utf-8") as fh:
            flag = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        # Missing/unreadable flag is NOT green — fail loud, exit red.
        print(f"loop_health --check: cannot read flag {args.flag}: {exc}",
              file=sys.stderr)
        return 2
    level = flag.get("level") if isinstance(flag, dict) else None
    if level not in _EXIT_BY_LEVEL:
        print(f"loop_health --check: flag {args.flag} has invalid level "
              f"{level!r} (want one of {_LEVELS})", file=sys.stderr)
        return 2
    print(f"loop_health: level={level} "
          f"reasons={len(flag.get('reasons', []))} "
          f"updated_at={flag.get('updated_at')}")
    return _EXIT_BY_LEVEL[level]


if __name__ == "__main__":
    raise SystemExit(main())
