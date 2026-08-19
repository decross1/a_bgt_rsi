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
  - detect_stall(report, ledger_events_this_cycle) — a coordinator cycle that
    was FREE TO ACT and did nothing: 0 run_loop_iteration dispatches AND 0
    promotions AND 0 ledger events -> {"signal": "loop_stalled",
    "severity": "stalled", ...}. Any activity on any axis -> None
    (conservative: no false red).
  - gate_reason(report) / detect_gated(report) — the cycle was HELD, not
    stalled: a refusal by the daily-budget pacing gate or by the pause file.
    A held cycle is DELIBERATELY idle and emits `loop_gated:<reason>`, never
    loop_stalled. The reason set is a FROZEN ENUM (_GATE_REASONS): only a
    reason with a live producer may suppress the stall path.
  - gate_continuity(prev_flag, gate, now) — ages a CONTINUOUSLY-gated loop
    across wakes and escalates by that age (ok -> amber at 3h, -> red at
    12h). A gate that never clears IS the loop not moving; without this a
    refuse-every-cycle day writes a fresh "ok" every hour and looks perfect.
  - write_alert_flag(path, level, reasons, gate=None, now=None) —
    run_state/loop_alert.json {"level": "red"|"amber"|"ok", "reasons": [...],
    "updated_at": iso} plus, when the cycle was held, an ADDITIVE
    {"gate": {"reason", "status", "detail", "first_gated_at", "consecutive",
    "age_s"}}. Path is injectable (tests use tmp_path); write is atomic
    (tmp+replace) because the cockpit polls it.

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

# How many consecutive nonzero-exit frontier calls make a vendor "down".
# Three, because a single 429/timeout is noise and two is a coincidence.
FRONTIER_DOWN_STREAK = 3

# ── gated-vs-stalled (2026-08-19 defect fix) ─────────────────────────────
# On 2026-08-19T03:32:39Z loop_alert.json went RED "loop_stalled" while the
# loop was healthy (iterations at 02:00/02:54/03:00) and the owner was mid
# finding-session. The cycle behind that alert never ran: it was the
# coordinator's daily-budget PACING refusal (coordinator.py:1020), whose
# report carries executed=[] — and an empty `executed` is exactly the shape
# detect_stall was built to flag. A cycle that was HELD is not a cycle that
# was free to act, so it must not be judged by the stall rule at all.
#
# FROZEN ENUM of gate reasons (2026-08-19 review, NB1). A reason here BUYS
# an exemption from the loop's only red signal, so the bar to be listed is a
# LIVE PRODUCER that reaches orchestrator.coordinator_cycle_log.
# emit_health_signals — not a plausible future one:
#
#   "budget" — coordinator.py's daily executed-cycle gate (:1020). Stamps
#              gate_reason="budget" and calls emit_health_signals itself.
#   "paused" — coordinator.py's pause-file kill switch (:996). Stamps
#              gate_reason="paused" and (since this fix) calls
#              emit_health_signals too, so the reason can actually reach a
#              reader instead of dying in a `return`.
#
# DELETED here, deliberately: "lock" and "active_run". Neither had a producer
# anywhere in the repo — flock contention is resolved in bash
# (cron/run-coordinator.sh Gate 1 -> exit 0, no Python) and in-process in
# nara_daemon._run_pass (Gate 1 -> "skipped:flock"), and BOTH return before a
# report object exists. A reason that cannot fire cannot be given tests that
# pretend it does; if a future path ever constructs such a report, it lands
# here WITH its producer.
_GATE_REASONS = ("budget", "paused")

# Which gate held it, keyed off the refusal report's `status` (the
# coordinator also sets an explicit `gate_reason`, preferred when present).
_GATE_REASON_BY_STATUS = {
    "paused": "paused",
    "daily_budget_exhausted": "budget",
    "daily_budget_paced": "budget",
}

# The BASE alert level a held cycle deserves, BY REASON — they are not the
# same kind of idle. Budget pacing is the schedule working as designed
# (dozens a day; amber on each would be the alarm fatigue this fix exists to
# end), so it reads "ok" and carries the reason in the flag's additive `gate`
# block. A paused loop is a HOLD an operator should see NAMED rather than
# read as silence -> amber. Neither is ever red ON ITS OWN: red means the
# loop was free and did nothing. But see gate_continuity — a gate that never
# CLEARS escalates by AGE, because a loop held all day is a loop not moving.
_GATE_LEVEL = {
    "budget": "ok",
    "paused": "amber",
}

_GATE_DETAIL = {
    "budget": ("the daily executed-cycle budget gate refused this cycle "
               "(pacing/cap) — the loop is on its ration, not stuck"),
    "paused": ("the human kill switch is engaged (run_state/"
               "pause_coordinator) — the loop is halted on purpose"),
}

# ── gate AGE escalation (2026-08-19 review, B1) ──────────────────────────
# The false-green the gated/stalled split opened: the budget gate is the only
# gate that fires in practice, its base level is "ok", and every refusal
# rewrites the flag with a FRESH updated_at. So a coordinator that refuses
# EVERY cycle for a day — ledger wedged at the cap, a bug in
# _budget_allowance, a misread cap — renders as perfect health, and the
# banner's only cross-cycle backstop (STALE_AFTER_MS, keyed off updated_at)
# is precisely the field the refusal path keeps refreshing. Silence must not
# be the reward for being stuck.
#
# So a CONTINUOUSLY-gated loop escalates by AGE, not by level alone. The
# clock starts at the first wake gated by the current reason and resets the
# moment a real cycle executes (that write carries no `gate` block at all) or
# the reason changes.
GATE_AMBER_AFTER_S = 3 * 60 * 60    # 3h held: past any normal pacing gap
GATE_RED_AFTER_S = 12 * 60 * 60     # 12h held: half a day without a cycle

_LEVEL_RANK = {"ok": 0, "amber": 1, "red": 2}


def worse(a: str, b: str) -> str:
    """The more severe of two levels. An unknown level ranks below "ok" only
    for comparison purposes — it never silently upgrades to a pass, because
    write_alert_flag rejects it outright."""
    return a if _LEVEL_RANK.get(a, -1) >= _LEVEL_RANK.get(b, -1) else b


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


def gate_reason(report: dict) -> str | None:
    """Which gate HELD this cycle, or None when the cycle was free to act.

    Prefers an explicit `gate_reason` the refusing path stamped on its
    report; falls back to mapping the report `status`.

    The returned reason is restricted to the FROZEN ENUM `_GATE_REASONS`
    (2026-08-19 review, NB1). The previous version returned ANY truthy
    string, and since detect_stall bails on a non-None reason, one stray
    `gate_reason` key on a report would have permanently exempted that
    report from loop_stalled — the loop's only red signal, disabled by a
    typo. An UNRECOGNIZED reason is not silently honored and not silently
    dropped either (inviolate rule 4): it is logged to stderr and the report
    falls through to the normal path, where the stall detector judges it on
    its merits. A gate that wants the exemption earns it by landing in
    _GATE_REASONS with its producer."""
    if not isinstance(report, dict):
        return None
    explicit = report.get("gate_reason")
    if isinstance(explicit, str) and explicit.strip():
        reason = explicit.strip()
        if reason in _GATE_REASONS:
            return reason
        print(
            f"loop_health: report {report.get('run_id', 'unknown')} carries an "
            f"unrecognized gate_reason {reason!r} (known: "
            f"{', '.join(_GATE_REASONS)}); NOT honoring it as a gate — the "
            "cycle is judged by the normal stall path. Add the reason to "
            "_GATE_REASONS together with its producer.",
            file=sys.stderr,
        )
    return _GATE_REASON_BY_STATUS.get(str(report.get("status") or ""))


def detect_gated(report: dict) -> dict | None:
    """A cycle that a gate held -> a `loop_gated:<reason>` signal, else None.

    This is the DISTINCT signal that keeps loop_stalled honest: idle-because-
    held and idle-because-stuck look identical in the report (executed=[]),
    and conflating them is what put a RED "LOOP STALLED" on the dashboard
    while the loop was iterating hourly. Carries `level` — never red — so
    the flag writer can render "idle: <reason>" instead of an alarm."""
    reason = gate_reason(report)
    if reason is None:
        return None
    errors = [e for e in (report.get("errors") or []) if isinstance(e, str)]
    detail = _GATE_DETAIL.get(
        reason, f"the cycle was refused by the {reason} gate")
    if errors:
        detail = f"{detail}: {errors[0]}"
    return {
        "signal": f"loop_gated:{reason}",
        "severity": "gated",
        "reason": reason,
        "level": _GATE_LEVEL.get(reason, "amber"),
        "cycle_status": report.get("status"),
        "detail": (
            f"coordinator cycle {report.get('run_id', 'unknown')} was "
            f"DELIBERATELY idle — {detail}. This is not a stall: the cycle "
            "never got the chance to act, so its empty action list says "
            "nothing about the loop's health."
        ),
    }


def gate_continuity(prev_flag: dict | None, gated: dict,
                    now: datetime) -> dict:
    """Age a CONTINUOUSLY-gated loop and escalate on that age.

    `prev_flag` is the alert flag as it stood BEFORE this write (the parsed
    run_state/loop_alert.json, or None when absent/unreadable); `gated` is
    detect_gated's signal; `now` is INJECTED (this module never reads wall
    time in a detector).

    Returns the `gate` block to write:
      {reason, status, detail, first_gated_at, consecutive, age_s,
       level, escalated}
    `level` is the ESCALATED level for the flag — the gate's base level until
    the loop has been held past GATE_AMBER_AFTER_S (-> amber) and then
    GATE_RED_AFTER_S (-> red), never downgraded below the base.

    The clock carries forward only while the REASON is unchanged, and only
    from a parseable first_gated_at — an unparseable one restarts the clock
    rather than inventing an age. A cycle that actually executes writes a
    flag with NO gate block at all, so the next gated wake starts fresh:
    escalation clears the moment the loop moves, which is the whole point."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    reason = gated["reason"]
    prev_gate = None
    if isinstance(prev_flag, dict):
        candidate = prev_flag.get("gate")
        if isinstance(candidate, dict) and candidate.get("reason") == reason:
            prev_gate = candidate

    first = _parse_ts((prev_gate or {}).get("first_gated_at"))
    prev_count = (prev_gate or {}).get("consecutive")
    consecutive = prev_count if isinstance(prev_count, int) and prev_count > 0 else 0
    if first is None:
        first = now
        consecutive = 0

    age_s = max(0.0, (now - first).total_seconds())
    base = _GATE_LEVEL.get(reason, "amber")
    if age_s >= GATE_RED_AFTER_S:
        level = worse(base, "red")
    elif age_s >= GATE_AMBER_AFTER_S:
        level = worse(base, "amber")
    else:
        level = base
    return {
        "reason": reason,
        "status": gated.get("cycle_status"),
        "detail": gated["detail"],
        "first_gated_at": first.isoformat(),
        "consecutive": consecutive + 1,
        "age_s": int(age_s),
        "level": level,
        "escalated": level != base,
    }


def gate_escalation_reason(gate: dict) -> str | None:
    """The human-readable line a gate EARNS once its age has escalated it —
    the thing that says out loud what the fresh-"ok" flag used to hide. None
    while the gate is young enough to be routine."""
    if not gate.get("escalated"):
        return None
    hours = gate.get("age_s", 0) / 3600.0
    return (
        f"loop held by the {gate['reason']} gate for {hours:.1f}h across "
        f"{gate['consecutive']} consecutive wake(s) since "
        f"{gate['first_gated_at']} — NO cycle has executed in that window. A "
        "gate that never clears is the loop not moving; check the gate's own "
        "input (ledger/cap for budget, run_state/pause_coordinator for paused)"
    )


def detect_stall(report: dict, ledger_events_this_cycle: int) -> dict | None:
    """A cycle that was FREE TO ACT, dispatched no iteration, PROMOTED
    nothing, and advanced no ledger cluster is a stalled loop.

    Promotions are counted by ACTUAL promoted findings, never by the
    promote_findings action having merely executed — the 2026-08-05..14
    zombie ran promote_findings every cycle, "passed" every time, and
    promoted zero. An empty-pool promote pass is NOT activity.
    run_loop_iteration counts on execution (any status: an attempt is
    activity)."""
    # A GATED cycle is out of scope entirely: it was held (by the budget gate
    # or the pause file — see _GATE_REASONS) and never reached a planner, so its empty
    # `executed` is the gate's signature, not the loop's silence. It gets
    # detect_gated's own signal instead. The empty-pool promote pass below
    # is untouched by this — that cycle WAS free to act.
    if gate_reason(report) is not None:
        return None
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


def detect_frontier_vendor_down(frontier_rows: list) -> list[dict]:
    """A frontier vendor whose last FRONTIER_DOWN_STREAK calls ALL exited
    nonzero is down, not hesitant.

    On 2026-08-16 the codex CLI began returning HTTP 400 for the model pinned
    in the machine-global config. Every D-061 consumer kept running and kept
    reporting an "opposed jobs" review — because a dead vendor surfaces one
    layer up as `inconclusive`, which is indistinguishable from a reviewer
    declining to commit. The panel ran half-dark for six hours and nothing
    noticed. This detector is the thing that would have noticed.

    Only rows carrying an INTEGER exit_code are judged; an absent or
    non-integer code is unknown, and unknown is never scored as either a
    success or a failure (rule 4). A vendor with fewer than the streak's worth
    of judgeable rows yields no signal — too little evidence is not health."""
    by_vendor: dict[str, list[dict]] = {}
    for row in frontier_rows or []:
        if not isinstance(row, dict):
            continue
        vendor = row.get("vendor")
        code = row.get("exit_code")
        if not isinstance(vendor, str) or not isinstance(code, int):
            continue
        by_vendor.setdefault(vendor, []).append(row)

    out: list[dict] = []
    for vendor, rows in sorted(by_vendor.items()):
        recent = rows[-FRONTIER_DOWN_STREAK:]
        if len(recent) < FRONTIER_DOWN_STREAK:
            continue
        if any(r["exit_code"] == 0 for r in recent):
            continue
        last_ok = next((r.get("timestamp") for r in reversed(rows)
                        if r["exit_code"] == 0), None)
        out.append({
            "signal": f"frontier_vendor_down:{vendor}",
            "severity": "degraded",
            "detail": (
                f"the last {FRONTIER_DOWN_STREAK} {vendor} calls all exited "
                f"nonzero (codes: "
                f"{', '.join(str(r['exit_code']) for r in recent)}); last "
                f"clean call {last_ok or 'never in this ledger'}. A reviewer "
                "reported as 'inconclusive' may be a dead CLI, not a "
                "judgment — check the vendor before trusting a panel verdict"
            ),
        })
    return out


def read_alert_flag(path) -> dict | None:
    """The flag as it stands on disk, or None when absent/unreadable/not an
    object. Read-only and never raises — its ONLY caller uses it to carry a
    gate's age forward, and a lost previous flag must restart that clock, not
    crash the cycle's bookkeeping."""
    try:
        with open(os.fspath(path), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def write_alert_flag(path, level: str, reasons: list[str], *,
                     gate: dict | None = None,
                     now: datetime | None = None) -> None:
    """Write {"level", "reasons", "updated_at"} JSON to `path` atomically.
    level must be one of red|amber|ok and reasons a list of strings —
    anything else raises ValueError (never coerced).

    `gate` is the ADDITIVE 2026-08-19 field: when the cycle was held rather
    than run, {"reason", "status", "detail"} — plus gate_continuity's
    {"first_gated_at", "consecutive", "age_s"} — lands under "gate" so a
    reader can say "idle: <reason> for <age>" instead of guessing from a
    level alone. Omitted when None, so a later free-running cycle clears it
    by simply not writing it — the gate marker is never sticky, and clearing
    it is what resets the age escalation. Consumers that predate the field
    (ui/backend/loop_alert.py returns the flag verbatim; the frontend's
    LoopAlert type is open-ended) are unaffected.

    `now` pins updated_at (tests simulate a day of wakes); it defaults to
    wall time."""
    if level not in _LEVELS:
        raise ValueError(f"level must be one of {_LEVELS}, got {level!r}")
    if not isinstance(reasons, list) or not all(
        isinstance(r, str) for r in reasons
    ):
        raise ValueError("reasons must be a list of strings")
    if gate is not None and not (
        isinstance(gate, dict) and isinstance(gate.get("reason"), str)
        and gate["reason"]
    ):
        raise ValueError("gate must be a dict carrying a non-empty string "
                         "'reason'")
    stamp = now if now is not None else datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    payload = {
        "level": level,
        "reasons": reasons,
        "updated_at": stamp.isoformat(),
    }
    if gate is not None:
        payload["gate"] = gate
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
    gate = flag.get("gate")
    gate_note = ""
    if isinstance(gate, dict) and isinstance(gate.get("reason"), str):
        age = gate.get("age_s")
        age_note = (f" for {age / 3600.0:.1f}h" if isinstance(age, (int, float))
                    else "")
        gate_note = f" gated={gate['reason']}{age_note}"
    print(f"loop_health: level={level} "
          f"reasons={len(flag.get('reasons', []))}{gate_note} "
          f"updated_at={flag.get('updated_at')}")
    return _EXIT_BY_LEVEL[level]


if __name__ == "__main__":
    raise SystemExit(main())
