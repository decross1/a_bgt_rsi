"""Observe request timing without changing the frozen legacy call schema.

Timing is measured by the streaming transport. First-token latency includes
reasoning/tool output when that is the first generated channel. Derived decode
rate is approximate: an SSE chunk can contain more than one token and transport
completion includes final framing. Failed requests never receive a speed score.
"""
from __future__ import annotations

import math
import re
from collections.abc import Callable

SCHEMA = "flash-followon-call-timing/v1"
SHA = re.compile(r"[0-9a-f]{64}\Z")


def _finite(value):
    if type(value) not in (float, int):
        return False
    try:
        return math.isfinite(value) and value >= 0
    except (OverflowError, ValueError):
        return False


class TimingRecorder:
    """One recorder belongs to one runner block; pending events are consumed."""

    def __init__(self):
        self._pending = []

    def wrap(self, invoke_fn: Callable) -> Callable:
        def measured(*args, **kwargs):
            result = invoke_fn(*args, **kwargs)
            if isinstance(result, dict):
                usage = result.get("usage")
                self._pending.append({
                    "request_sha256": result.get("request_sha256"),
                    "response_stream_sha256": result.get("response_stream_sha256"),
                    "latency_s": result.get("latency_s"),
                    "ttft_s": result.get("ttft_s"),
                    "completion_tokens": usage.get("completion_tokens")
                        if isinstance(usage, dict) else None,
                    "prompt_tokens": usage.get("prompt_tokens")
                        if isinstance(usage, dict) else None,
                })
            return result
        return measured

    def for_calls(self, calls: list[dict]) -> list[dict]:
        timings = []
        for call in calls:
            base = {
                "schema_version": SCHEMA, "call_id": call.get("call_id"),
                "request_sha256": call.get("request_sha256"),
                "response_stream_sha256": call.get("response_stream_sha256"),
                "status": "unavailable", "reason": "transport_timing_not_recorded",
                "ttft_s": None, "latency_s": None,
                "prompt_tokens": None, "completion_tokens": None,
                "request_completion_tokens_per_second": None,
                "approximate_decode_tokens_per_second": None,
            }
            match = next((i for i, row in enumerate(self._pending)
                          if row["request_sha256"] == call.get("request_sha256")
                          and row["response_stream_sha256"] == call.get("response_stream_sha256")), None)
            observed = self._pending.pop(match) if match is not None else None
            if call.get("status") != "returned":
                base["reason"] = "request_not_returned"
            elif observed is not None:
                latency, first = observed["latency_s"], observed["ttft_s"]
                tokens, prompt = observed["completion_tokens"], observed["prompt_tokens"]
                usage = call.get("usage")
                valid = (
                    all(isinstance(base[key], str) and SHA.fullmatch(base[key])
                        for key in ("request_sha256", "response_stream_sha256"))
                    and _finite(latency) and latency > 0
                    and (first is None or _finite(first) and first <= latency)
                    and type(tokens) is int and tokens >= 0
                    and type(prompt) is int and prompt >= 0
                    and isinstance(usage, dict)
                    and usage.get("completion_tokens") == tokens
                    and usage.get("prompt_tokens") == prompt
                    and _finite(call.get("wall_s"))
                    and latency <= call["wall_s"] + 0.01
                )
                if valid:
                    base.update({
                        "status": "recorded", "reason": None,
                        "ttft_s": first, "latency_s": latency,
                        "prompt_tokens": prompt, "completion_tokens": tokens,
                        "request_completion_tokens_per_second": tokens / latency,
                        "approximate_decode_tokens_per_second":
                            (tokens - 1) / (latency - first)
                            if first is not None and tokens > 1 and latency > first else None,
                    })
                else:
                    base["reason"] = "timing_or_usage_binding_invalid"
            timings.append(base)
        return timings


def validate_timings(calls: list[dict], rows: list[dict]) -> None:
    """Validate saved public timings against their exact successful call."""
    if not isinstance(rows, list) or len(rows) != len(calls):
        raise ValueError("transport timing coverage differs from calls")
    for call, row in zip(calls, rows, strict=True):
        if (not isinstance(row, dict) or row.get("schema_version") != SCHEMA
                or any(row.get(key) != call.get(key) for key in
                       ("call_id", "request_sha256", "response_stream_sha256"))):
            raise ValueError("transport timing identity differs from call")
        if row.get("status") == "recorded":
            recorder = TimingRecorder()
            recorder._pending.append({key: row.get(key) for key in (
                "request_sha256", "response_stream_sha256", "latency_s", "ttft_s",
                "completion_tokens", "prompt_tokens",
            )})
            if recorder.for_calls([call])[0] != row:
                raise ValueError("saved timing or rate cannot be reproduced")
        elif (row.get("status") != "unavailable"
              or row.get("reason") not in {"request_not_returned", "transport_timing_not_recorded",
                                           "timing_or_usage_binding_invalid"}
              or any(row.get(key) is not None for key in (
                  "ttft_s", "latency_s", "prompt_tokens", "completion_tokens",
                  "request_completion_tokens_per_second", "approximate_decode_tokens_per_second"))):
            raise ValueError("unavailable timing cannot claim a rate")
