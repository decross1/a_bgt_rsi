"""Day-4 readers: events.jsonl and day4_robust.jsonl.

These two files are not part of the call log proper, so they are read
outside the LogStore index:

- events.jsonl (Day 3.5): event_type-tagged records, currently two known
  types -- human_intervention and calibration_entry. The schema has not
  been committed by Track A yet, so this reader stays generic: it
  enforces only `event_type` (so the UI can filter) and passes the rest
  through as opaque fields. Missing-file degrades to an empty list.

- day4_robust.jsonl: per-trial outcomes from a robustness sweep. The
  reader computes the dashboard panel's invocation rate, per-trial
  outcomes, and median latency.
"""
import json
import statistics
from pathlib import Path


def read_events(events_file, limit=200):
    """Return parsed events from events.jsonl, newest last.

    Truncates to the last `limit` records to bound the response size. A
    record without `event_type` is dropped (we never invented an event
    type for it). Empty list when the file does not exist.
    """
    path = Path(events_file)
    if not path.exists():
        return {"events": [], "available": False}
    events = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict) or "event_type" not in record:
                    continue
                events.append(record)
    except OSError:
        return {"events": [], "available": False}
    if limit and len(events) > limit:
        events = events[-limit:]
    return {"events": events, "available": True}


def read_robustness(robust_file):
    """Compute invocation rate, per-trial outcomes, and median latency.

    The shape mirrors day4_robust.jsonl: one record per trial with
    `invoked` (bool) and optional `latency_ms`/`outcome`. Median latency
    is over invocations that produced a numeric latency.
    """
    path = Path(robust_file)
    if not path.exists():
        return {"available": False, "trials": [], "invocations": 0,
                "trial_count": 0, "invocation_rate": None,
                "median_latency_ms": None, "outcomes": {}}
    trials = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    trials.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return {"available": False, "trials": [], "invocations": 0,
                "trial_count": 0, "invocation_rate": None,
                "median_latency_ms": None, "outcomes": {}}

    trial_count = len(trials)
    invocations = sum(1 for t in trials if t.get("invoked"))
    latencies = [t["latency_ms"] for t in trials
                 if t.get("invoked")
                 and isinstance(t.get("latency_ms"), (int, float))]
    median = statistics.median(latencies) if latencies else None

    outcomes = {}
    for trial in trials:
        outcome = trial.get("outcome") or "unspecified"
        outcomes[outcome] = outcomes.get(outcome, 0) + 1

    return {
        "available": True,
        "trials": trials,
        "trial_count": trial_count,
        "invocations": invocations,
        "invocation_rate": round(invocations / trial_count, 3) if trial_count else None,
        "median_latency_ms": median,
        "outcomes": outcomes,
    }
