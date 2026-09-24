"""Plan 2026-09-24 (G7.2, the uptime/cycle-cadence question the owner was asked at
mailbox oracle-acd9d1f742e36e83 seq 213 and withdrawn at seq 224): the daily loop must
be able to say how long a cycle takes.

Why this exists, and why it is a measurement rather than a report. This morning's plan
named "a 498-second gap in the 300s loop cadence, unexplained" as bottleneck 1; that
claim was wrong and I withdrew it in seq 213 - the two timer units in the comparison
stopped existing at 06:13:12Z when oracle-daily-planning.timer was replaced by
oracle-loop-cycle.timer. What is true, measured by hand out of the live journal, is that
24 cycles started in six hours with a median gap of 330s and a max of 2,820s, and the
timer is OnUnitInactiveSec=5min, so a long cycle IS the next gap. Cycle duration itself
was computed nowhere in the lab, so the six cycles over 1,200s - the longest 2,502s -
could not be told apart from a 60s one by any code. Review claude-7132f8f7704f440d
(seq 229) found the first version of this function returned ZERO cycles on real journal
data, because its matcher needed a leading space that only a hand-written fixture has.
Every case below is therefore fed strings copied verbatim from
`journalctl --user -u oracle-loop-cycle.service -o json`.

Seven cases, all red on main 025537c (the function does not exist there):

  1  a real Starting/Finished pair from the journal becomes one cycle
  2  percentiles: median, max, and an over-threshold count against the 1,200s line
  3  p95 is the nearest-rank percentile; on ten cycles of 100..1000s it is 1,000s, not
     the 900s that int(q*n)-1 returns (that index is the p90)
  4  a p95 over a mostly-short window with one long cycle is the long one, and a p95 on
     [60, 2500] is never below the median
  5  a failed or timed-out cycle is counted, closed, and reported in `failed`
  6  an open cycle with no close is discarded, never guessed at as infinite
  7  an orphan close, an untimestamped row, a row outside the window, no rows and an
     unparseable `now` all return zeros (the caller polls the journal)

Acceptance (plan 2026-09-24, the cadence bottleneck; review seq 229):
  .venv-chroma/bin/python -m pytest tests/test_loop_cycle_duration.py -q   -> 7 passed
  the same file against main's loop_health.py                              -> 7 failed
"""
from __future__ import annotations

# Verbatim from `journalctl --user -u oracle-loop-cycle.service -o json`, MESSAGE field,
# 2026-09-24. systemd writes the field from the word, with no leading space.
STARTING = ("Starting oracle-loop-cycle.service - Oracle cycle on local Flash: plan "
            "today if unplanned, else one work phase...")
FINISHED = ("Finished oracle-loop-cycle.service - Oracle cycle on local Flash: plan "
            "today if unplanned, else one work phase.")


def _rows(*pairs):
    """Journal-shaped rows: one Starting/Finished pair per (start_s, duration_s)."""
    def fmt(t: float) -> str:
        return f"{int(t) // 3600:02d}:{int(t) % 3600 // 60:02d}:{int(t) % 60:02d}"

    out = []
    for start_s, dur in pairs:
        out.append({"ts": f"2026-09-24T{fmt(start_s)}+00:00", "message": STARTING})
        out.append({"ts": f"2026-09-24T{fmt(start_s + dur)}+00:00", "message": FINISHED})
    return out


def test_a_real_journal_start_finish_pair_is_one_cycle():
    """seq 229 amendment 1, red-first: the two MESSAGE strings copied out of the live
    journal must produce one cycle. On 5dbd2ab this fails with cycles == 0, because the
    matcher looked for ' Starting ' and the journal's field starts at 'Starting'."""
    from orchestrator.loop_health import cycle_durations

    rows = [{"ts": "2026-09-24T07:00:30+00:00", "message": STARTING},
            {"ts": "2026-09-24T07:33:25+00:00", "message": FINISHED}]
    got = cycle_durations(rows, 24, "2026-09-24T12:00:00+00:00")

    assert got["cycles"] == 1, got
    assert got["median_s"] == 1975.0, got


def test_cycle_durations_reports_the_percentiles_the_timer_cannot():
    from orchestrator.loop_health import cycle_durations

    rows = _rows((7 * 3600 + 30, 1975), (7 * 3600 + 2311, 0), (8 * 3600 + 1951, 2463))
    got = cycle_durations(rows, 24, "2026-09-24T12:00:00+00:00")

    assert got["cycles"] == 3, got
    assert got["median_s"] == 1975.0, got
    assert got["max_s"] == 2463.0, got
    assert got["over_1200s"] == 2, got


def test_p95_is_the_nearest_rank_percentile_not_one_rank_low():
    """seq 229 amendment 2. On ten cycles of 100..1000s the nearest-rank p95 is 1,000s;
    int(q*n)-1 returns 900s, which is the p90, and the acceptance line 'p95 < 1,200s'
    would then be judged on a statistic that flatters the loop by one rank."""
    from orchestrator.loop_health import cycle_durations

    ten = _rows(*[(7 * 3600 + i * 600, (i + 1) * 100) for i in range(10)])
    got = cycle_durations(ten, 24, "2026-09-24T12:00:00+00:00")

    assert got["cycles"] == 10, got
    assert got["p95_s"] == 1000.0, got
    assert got["max_s"] == 1000.0, got
    assert got["median_s"] == 550.0, got


def test_p95_never_sits_below_the_median_and_sees_one_long_cycle_in_a_short_window():
    """seq 229 amendment 2, second half: on 5dbd2ab the two-sample case returns 60.0,
    below the median of the same sample, and a single 2,500s cycle among twenty
    disappears from the statistic the gate is written against."""
    from orchestrator.loop_health import cycle_durations

    two = _rows((7 * 3600, 60), (8 * 3600, 2500))
    got_two = cycle_durations(two, 24, "2026-09-24T12:00:00+00:00")
    assert got_two["cycles"] == 2, got_two
    assert got_two["p95_s"] == 2500.0, got_two
    assert got_two["p95_s"] >= got_two["median_s"], got_two

    mostly_short = _rows(*[(7 * 3600 + i * 600, 60) for i in range(19)]
                        + [(8 * 3600 + 19 * 600, 2500)])
    got_many = cycle_durations(mostly_short, 24, "2026-09-24T12:00:00+00:00")
    assert got_many["cycles"] == 20, got_many
    assert got_many["p95_s"] == 60.0, got_many       # 19 of 20 are 60s: p95 is 60s
    assert got_many["max_s"] == 2500.0, got_many


def test_a_failed_or_timed_out_cycle_is_counted_not_dropped():
    """seq 229 amendment 3. The installed unit has TimeoutStartSec=7200, so the cycles
    that never finish are the LONGEST ones. On 5dbd2ab the Failed row was not a close,
    the next Starting overwrote the open, and the 100-minute cycle vanished: cycles 1,
    max 60.0."""
    from orchestrator.loop_health import cycle_durations

    rows = [{"ts": "2026-09-24T07:00:00+00:00", "message": STARTING},
            {"ts": "2026-09-24T08:40:00+00:00",
             "message": "oracle-loop-cycle.service: Failed with result 'timeout'."},
            {"ts": "2026-09-24T08:45:00+00:00", "message": STARTING},
            {"ts": "2026-09-24T08:46:00+00:00", "message": FINISHED}]
    got = cycle_durations(rows, 24, "2026-09-24T12:00:00+00:00")

    assert got["cycles"] == 2, got
    assert got["max_s"] == 6000.0, got
    assert got["over_1200s"] == 1, got
    assert got["failed"] == 1, got


def test_a_cycle_still_running_is_discarded_never_guessed_at_as_infinite():
    from orchestrator.loop_health import cycle_durations

    rows = _rows((7 * 3600 + 30, 600))
    rows.append({"ts": "2026-09-24T11:00:00+00:00", "message": STARTING})
    got = cycle_durations(rows, 24, "2026-09-24T12:00:00+00:00")

    assert got["cycles"] == 1, got
    assert got["max_s"] == 600.0, got


def test_the_function_returns_zeros_instead_of_guessing_or_raising():
    from orchestrator.loop_health import cycle_durations

    junk = cycle_durations([
        {"ts": "2026-09-24T07:00:00+00:00", "message": FINISHED},      # no open cycle
        {"message": STARTING},                                          # no timestamp
        {"ts": "2026-09-24T00:00:00+00:00", "message": STARTING},      # outside window
        {"ts": "2026-09-24T00:01:00+00:00", "message": FINISHED},
        {"ts": "2026-09-24T07:00:30+00:00", "message": STARTING},
        {"ts": "2026-09-24T07:01:30+00:00", "message": FINISHED},
    ], 6, "2026-09-24T12:00:00+00:00")
    assert junk == {"cycles": 1, "median_s": 60.0, "p95_s": 60.0, "max_s": 60.0,
                    "over_1200s": 0, "failed": 0}, junk

    zeros = {"cycles": 0, "median_s": 0.0, "p95_s": 0.0, "max_s": 0.0,
             "over_1200s": 0, "failed": 0}
    assert cycle_durations([], 24, "2026-09-24T12:00:00+00:00") == zeros
    assert cycle_durations(_rows((3600, 60)), 24, "not-a-time") == zeros
