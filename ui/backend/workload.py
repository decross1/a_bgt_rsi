"""Workload-shape hint for the dashboard's vLLM panel.

The decode tok/s tile reads server-wide `vllm:generation_tokens_total`
rate, which scales with *output tokens / second across all calls*. The
day-1 baseline (decode_tok_per_s band [80,130]) was measured during a
sustained 256-token-per-call sweep — that workload is decode-bound.

A prompt that asks the model for a single token (e.g. the Day-7 PD
experiment with output_tokens=2) is prefill/TTFT-bound: 600 calls × 2
output tokens / 114 s ≈ 11 server-side decode tok/s, *by construction*.
The benchmark band is then misleading — the tile reads "11" against
"[80,130]" and looks like a regression when nothing is wrong.

This module summarizes the *current workload shape* (median completion
tokens per call, calls/sec) from the most-recent N call records across
the apparatus's `logs/day*.jsonl` + `logs/exp*.jsonl` glob, so the
dashboard can annotate the decode tile: "expected ~Xs tok/s — short-
completion workload (median Y tokens/call)".

Read path mirrors the existing LogStore conventions — bounded tail of
recent records, no full-file re-read. Read-only by design (ui_plan.md §2).
"""
import json
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Day-1 benchmark band, repeated here so the workload hint can label
# decode-bound expectations alongside short-completion ones. Sourced from
# ui_plan.md §5.3 (r2) and backend/baseline.py:DOCUMENTED.
DECODE_BOUND_BAND = (80, 130)
DECODE_BOUND_FLOOR = 40


def _output_tokens(record):
    """Pull completion-token count across the schemas the wrapper has used.

    Day-2 sweep used `usage.completion_tokens`. Day-7 PD writes
    `usage.output_tokens`. Either works; the field that exists wins.
    """
    usage = record.get("usage") or {}
    for key in ("output_tokens", "completion_tokens"):
        value = usage.get(key)
        if isinstance(value, (int, float)):
            return value
    return None


def _parse_ts(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _tail_jsonl(path, max_lines):
    """Return up to `max_lines` parsed records from the end of a JSONL file.

    Reads a bounded window (similar shape to app.py:_tail_lines) so the
    cost stays low even on multi-megabyte exp001*.jsonl files.
    """
    path = Path(path)
    if not path.exists():
        return []
    try:
        size = path.stat().st_size
        window = min(size, max_lines * 4096)   # generous per-line budget
        with open(path, "rb") as fh:
            fh.seek(size - window)
            data = fh.read()
    except OSError:
        return []
    lines = data.decode("utf-8", errors="replace").splitlines()
    if window < size and lines:
        lines = lines[1:]                       # drop partial first line
    out = []
    for raw in lines[-max_lines:]:
        raw = raw.strip()
        if not raw:
            continue
        try:
            out.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return out


def compute_workload_hint(logs_dir, sample_size=200, window_s=120):
    """Summarize the workload shape from the last `sample_size` call records.

    Globs `logs/day*.jsonl` + `logs/exp*.jsonl` (the call-log union per
    ui_plan.md §4.2), tails each, merges, sorts by timestamp, keeps the
    last `sample_size`. Returns:

        {
          "available": bool,
          "sample_size": int,
          "calls_per_s": float | None,
          "median_output_tokens": int | None,
          "regime": "short_completion" | "decode_bound" | "mixed" | "idle",
          "expected_decode_tok_s_lower": float | None,
          "expected_decode_tok_s_upper": float | None,
          "note": str,
          "window_s": int,
        }

    `regime` and the expected band are conservative estimates the
    frontend uses to annotate the decode tile; they are NOT
    authoritative measurements.
    """
    logs_dir = Path(logs_dir)
    records = []
    for pattern in ("day*.jsonl", "exp*.jsonl"):
        for path in sorted(logs_dir.glob(pattern)):
            records.extend(_tail_jsonl(path, sample_size))

    if not records:
        return {"available": False, "sample_size": 0,
                "calls_per_s": None, "median_output_tokens": None,
                "regime": "idle",
                "expected_decode_tok_s_lower": None,
                "expected_decode_tok_s_upper": None,
                "window_s": window_s,
                "note": "no call records yet — no logs/day*.jsonl or logs/exp*.jsonl"}

    records.sort(key=lambda r: r.get("timestamp") or "")
    records = records[-sample_size:]

    output_tokens = [t for t in (_output_tokens(r) for r in records)
                     if t is not None]
    timestamps = [t for t in (_parse_ts(r.get("timestamp"))
                              for r in records) if t is not None]

    median_output = (int(statistics.median(output_tokens))
                     if output_tokens else None)

    calls_per_s = None
    if timestamps:
        # Calls within the last `window_s` only (so a quiet system after
        # a burst reports near-zero rather than the burst's rate).
        latest = timestamps[-1]
        if latest.tzinfo is None:
            latest = latest.replace(tzinfo=timezone.utc)
        cutoff = latest - timedelta(seconds=window_s)
        in_window = [t for t in timestamps
                     if (t.tzinfo or timezone.utc) and t >= cutoff]
        if in_window and len(in_window) >= 2:
            span = (in_window[-1] - in_window[0]).total_seconds()
            if span > 0:
                calls_per_s = round(len(in_window) / span, 2)
            else:
                calls_per_s = float(len(in_window))

    if median_output is None or calls_per_s is None:
        regime = "idle" if not output_tokens else "mixed"
        return {"available": True, "sample_size": len(records),
                "calls_per_s": calls_per_s,
                "median_output_tokens": median_output,
                "regime": regime,
                "expected_decode_tok_s_lower": None,
                "expected_decode_tok_s_upper": None,
                "window_s": window_s,
                "note": ("insufficient timestamp coverage in the sample"
                         if median_output is not None
                         else "no usage.{output,completion}_tokens fields")}

    expected_lower = round(calls_per_s * max(1, median_output) * 0.7, 1)
    expected_upper = round(calls_per_s * max(1, median_output) * 1.3, 1)

    if median_output <= 8:
        regime = "short_completion"
        note = (f"prefill/TTFT-bound: ~{calls_per_s} call/s × "
                f"~{median_output} tok/call. Day-1 band [{DECODE_BOUND_BAND[0]},"
                f"{DECODE_BOUND_BAND[1]}] does not apply — that band was "
                "measured with 256-tok completions.")
    elif median_output >= 64:
        regime = "decode_bound"
        note = (f"decode-bound: ~{median_output} tok/call. Day-1 band "
                f"[{DECODE_BOUND_BAND[0]},{DECODE_BOUND_BAND[1]}] applies.")
        expected_lower = float(DECODE_BOUND_BAND[0])
        expected_upper = float(DECODE_BOUND_BAND[1])
    else:
        regime = "mixed"
        note = (f"mixed: ~{median_output} tok/call × ~{calls_per_s} call/s. "
                "Decode tok/s scales with both — Day-1 band may or may not "
                "apply depending on prefill dominance.")

    return {"available": True, "sample_size": len(records),
            "calls_per_s": calls_per_s,
            "median_output_tokens": median_output,
            "regime": regime,
            "expected_decode_tok_s_lower": expected_lower,
            "expected_decode_tok_s_upper": expected_upper,
            "window_s": window_s,
            "note": note}
