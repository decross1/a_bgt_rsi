"""Plan 2026-09-24 (G7.2): the daily loop must be able to say how long a cycle takes.

Why this exists, and why it is a gate rather than a report. This morning I reported
"a 498-second gap in the 300s loop cadence, unexplained" (plan 2026-09-24, bottleneck
1; withdrawn in mailbox oracle-acd9d1f742e36e83 to the owner). The gap as framed did not
exist — it compared two different timer units across today's 06:13Z redesign. What IS
true, and was measured afterwards by hand out of the journal (run_state/gap_scan_2026-09-24.sh):
six of the last 23 cycles ran over 20 minutes, the longest 2,502s, on a timer whose
OnUnitInactiveSec=5min means a long cycle IS the next gap. The owner decision at
oracle-acd9d1f742e36e83 (options A/B/C) needs that number and its history, and the same
number is what tells a cycle that got its work done in 60s from one that ground for
41 minutes — which today nothing in the lab could compute (red on main: the function
does not exist there).

Four cases, all red on main 025537c:

  1  a start/finish pair from journal-shaped rows becomes a duration; percentiles, the
     max, and an over-threshold count come back
  2  an open cycle with no close is DISCARDED, never guessed at as infinite — the
     journal of a running loop always ends mid-cycle
  3  an orphan close, a row with no timestamp, a row outside the window, an empty list
     and an unparseable `now` all return zeros; the caller is the cockpit poller, which
     must not die on a bad argument
  4  the p95 is a real order statistic, not the median relabelled

Acceptance (plan 2026-09-24, the uptime decision item):
  .venv-chroma/bin/python -m pytest tests/test_loop_cycle_duration.py -q   -> 4 passed
  the same file against main's loop_health.py                              -> 4 failed (ImportError)
"""
from __future__ import annotations


def _rows(*pairs):
    """Journal-shaped rows: one Starting/Finished pair per (start_s, duration_s)."""
    def fmt(t: float) -> str:
        return f"{int(t) // 3600:02d}:{int(t) % 3600 // 60:02d}:{int(t) % 60:02d}"

    out = []
    for start_s, dur in pairs:
        out.append({"ts": f"2026-09-24T{fmt(start_s)}+00:00",
                    "message": " Starting oracle-loop-cycle.service ..."})
        out.append({"ts": f"2026-09-24T{fmt(start_s + dur)}+00:00",
                    "message": " Finished oracle-loop-cycle.service ..."})
    return out


def test_cycle_durations_turns_journal_pairs_into_durations():
    from orchestrator.loop_health import cycle_durations

    rows = _rows((7 * 3600 + 30, 1975), (7 * 3600 + 2311, 0), (8 * 3600 + 1951, 2463))
    got = cycle_durations(rows, 6, "2026-09-24T12:00:00+00:00")

    assert got["cycles"] == 3, got
    assert got["median_s"] == 1975.0, got
    assert got["max_s"] == 2463.0, got
    assert got["over_1200s"] == 2, got          # the uptime-line counter


def test_cycle_durations_discards_a_cycle_still_running():
    from orchestrator.loop_health import cycle_durations

    rows = _rows((7 * 3600 + 30, 600))
    rows.append({"ts": "2026-09-24T11:00:00+00:00",
                 "message": " Starting oracle-loop-cycle.service ..."})
    got = cycle_durations(rows, 24, "2026-09-24T12:00:00+00:00")

    assert got["cycles"] == 1, got               # the dangling open is not counted
    assert got["max_s"] == 600.0, got


def test_cycle_durations_returns_zeros_instead_of_guessing_or_raising():
    from orchestrator.loop_health import cycle_durations

    junk = cycle_durations([
        {"ts": "2026-09-24T07:00:00+00:00", "message": " Finished orphan"},
        {"message": " Starting with no timestamp"},
        {"ts": "2026-09-24T00:00:00+00:00", "message": " Starting outside the window"},
        {"ts": "2026-09-24T07:00:30+00:00", "message": " Starting y"},
        {"ts": "2026-09-24T07:01:30+00:00", "message": " Finished y"},
    ], 6, "2026-09-24T12:00:00+00:00")
    assert junk == {"cycles": 1, "median_s": 60.0, "p95_s": 60.0, "max_s": 60.0,
                    "over_1200s": 0}, junk

    zeros = {"cycles": 0, "median_s": 0.0, "p95_s": 0.0, "max_s": 0.0,
             "over_1200s": 0}
    assert cycle_durations([], 24, "2026-09-24T12:00:00+00:00") == zeros
    assert cycle_durations(_rows((3600, 60)), 24, "not-a-time") == zeros


def test_cycle_durations_p95_is_an_order_statistic_not_the_median():
    from orchestrator.loop_health import cycle_durations

    ten = _rows(*[(7 * 3600 + i * 600, (i + 1) * 100) for i in range(10)])
    got = cycle_durations(ten, 24, "2026-09-24T12:00:00+00:00")

    assert got["cycles"] == 10, got
    assert got["p95_s"] == 900.0, got
    assert got["max_s"] == 1000.0, got
    assert got["median_s"] == 550.0, got
