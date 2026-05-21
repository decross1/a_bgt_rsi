"""Day-4 readers: events.jsonl and day4_robust.jsonl.

These two files are read outside the LogStore call-log index:

- events.jsonl (Day 3.5): event_type-tagged records -- human_intervention
  and calibration_entry. read_events stays schema-light: it enforces only
  `event_type` (so the UI can filter) and passes the rest through as
  opaque fields. The frontend EventsViewer renders each type from the
  committed schema/events.jsonl.schema.json. A missing file degrades to
  available=False.

- day4_robust.jsonl: a CHAINED CALL LOG from a tool-call robustness sweep
  -- not a per-trial summary. Track A logs every call (the same record
  shape as logs/day4_e2e.jsonl). Each robustness run is a wrapper-root
  call (parent_request_id null, caller_tag test_tool_call_robustness/
  run<N>) whose `completion` carries the model's tool call, optionally
  followed by a child call. read_robustness derives the invocation rate
  from whether each run's root completion parses as a tool call.
"""
import json
import statistics
from pathlib import Path

from .chain import parse_completion_tool_calls, tool_call_name


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


def _empty_robustness(available):
    return {"available": available, "trials": [], "trial_count": 0,
            "invocations": 0, "invocation_rate": None,
            "median_latency_ms": None, "outcomes": {}}


def _first_tool_name(tool_calls):
    """Name of the first parsed tool call in a completion, or None."""
    for call in tool_calls:
        name = tool_call_name(call)
        if name:
            return name
    return None


def read_robustness(robust_file):
    """Summarise a tool-call robustness sweep from a chained call log.

    day4_robust.jsonl is a chained call log, not a per-trial summary (see
    the module docstring). One "run" is a wrapper-root call: a record with
    parent_request_id null, tagged test_tool_call_robustness/run<N>. A run
    "invoked" the tool when its root `completion` parses as an OpenAI-style
    tool-call array (parse_completion_tool_calls); a root whose completion
    is ordinary text "missed", and one that opens like a tool-call array
    but does not parse is "malformed" -- flagged, never silently repaired.

    Child records (parent_request_id set -- the call carrying the tool
    result and final answer) are not runs and are not counted as trials.

    Returns {available, trials, trial_count, invocations, invocation_rate,
    median_latency_ms, outcomes}. invocation_rate is invocations/trial_count;
    median_latency_ms is the median root-call latency over runs that
    invoked. Latencies are rounded to 0.1 ms -- the source logs carry
    sub-microsecond float latencies.
    """
    path = Path(robust_file)
    if not path.exists():
        return _empty_robustness(False)
    records = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return _empty_robustness(False)

    trials = []
    for record in records:
        if not isinstance(record, dict):
            continue
        if record.get("parent_request_id") is not None:
            continue                              # a child call, not a run root
        tool_calls, malformed = parse_completion_tool_calls(
            record.get("completion"))
        invoked = bool(tool_calls)
        outcome = "ok" if invoked else ("malformed" if malformed else "missed")
        latency = record.get("latency_ms")
        trials.append({
            "trial_id": len(trials) + 1,
            "caller_tag": record.get("caller_tag"),
            "request_id": record.get("request_id"),
            "invoked": invoked,
            "outcome": outcome,
            "tool_name": _first_tool_name(tool_calls),
            "latency_ms": (round(latency, 1)
                           if isinstance(latency, (int, float)) else None),
        })

    trial_count = len(trials)
    invocations = sum(1 for t in trials if t["invoked"])
    latencies = [t["latency_ms"] for t in trials
                 if t["invoked"] and isinstance(t["latency_ms"], (int, float))]
    median = statistics.median(latencies) if latencies else None

    outcomes = {}
    for trial in trials:
        outcomes[trial["outcome"]] = outcomes.get(trial["outcome"], 0) + 1

    return {
        "available": True,
        "trials": trials,
        "trial_count": trial_count,
        "invocations": invocations,
        "invocation_rate": (round(invocations / trial_count, 3)
                            if trial_count else None),
        "median_latency_ms": median,
        "outcomes": outcomes,
    }
