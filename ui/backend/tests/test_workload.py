"""Workload-shape hint (ui_plan.md r10).

See backend/workload.py. The hint contextualizes the decode-tok/s tile
so a short-completion workload (PD experiment, 2 tok/call) doesn't read
as a regression against the day-1 band measured at 256 tok/call.
"""
import json

from backend.workload import compute_workload_hint


def _write_call(path, ts, output_tokens, completion="C"):
    """Append one wrapper-call record in the day-2-onward shape."""
    record = {
        "timestamp": ts,
        "request_id": f"r-{ts}",
        "parent_request_id": None,
        "model": "gemma-4-26b-a4b",
        "temperature": 0.0,
        "prompt_messages": [{"role": "user", "content": "..."}],
        "completion": completion,
        "usage": {"input_tokens": 196, "output_tokens": output_tokens},
        "latency_ms": 200.0,
        "caller_tag": "pd",
    }
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def test_short_completion_workload_is_labelled(tmp_path):
    log = tmp_path / "exp001.jsonl"
    # 50 calls spread over ~10s (5 calls/s) — matches the Day-7 PD shape
    # (600 calls / 114s ≈ 5.3 calls/s).
    for i in range(50):
        _write_call(log, f"2026-05-23T09:00:{i // 5:02d}.{(i % 5) * 200:03d}Z",
                    output_tokens=2)
    hint = compute_workload_hint(tmp_path, sample_size=200)
    assert hint["available"] is True
    assert hint["regime"] == "short_completion"
    assert hint["median_output_tokens"] == 2
    # ~5 calls/s × 2 tok = ~10 tok/s expected — matches the user's
    # observed 11 tok/s during the PD experiment. The labelled band is
    # workload-derived, NOT the day-1 [80,130].
    assert hint["calls_per_s"] is not None
    assert 1 <= hint["calls_per_s"] <= 50
    assert hint["expected_decode_tok_s_upper"] < 80
    assert "Day-1 band" in hint["note"] and "does not apply" in hint["note"]


def test_decode_bound_workload_uses_day1_band(tmp_path):
    log = tmp_path / "day2.jsonl"
    for i in range(60):
        # Spread across ~60s: long completions, ~1 call/s — typical bench shape.
        _write_call(log, f"2026-05-18T10:00:{i:02d}.000Z", output_tokens=256)
    hint = compute_workload_hint(tmp_path, sample_size=200)
    assert hint["regime"] == "decode_bound"
    assert hint["expected_decode_tok_s_lower"] == 80
    assert hint["expected_decode_tok_s_upper"] == 130


def test_mixed_workload_regime(tmp_path):
    log = tmp_path / "day5.jsonl"
    values = [16, 24, 32, 48, 16, 24, 32, 48, 16, 24]
    for i, n in enumerate(values):
        _write_call(log, f"2026-05-22T00:00:{i:02d}.000Z", output_tokens=n)
    hint = compute_workload_hint(tmp_path, sample_size=200)
    assert hint["regime"] == "mixed"
    assert "mixed" in hint["note"]


def test_no_logs_returns_idle(tmp_path):
    hint = compute_workload_hint(tmp_path)
    assert hint["available"] is False
    assert hint["regime"] == "idle"
    assert hint["calls_per_s"] is None


def test_legacy_completion_tokens_field_is_read(tmp_path):
    """Older Day-2 records used usage.completion_tokens; newer use output_tokens."""
    log = tmp_path / "day2.jsonl"
    with open(log, "a", encoding="utf-8") as fh:
        for i in range(30):
            fh.write(json.dumps({
                "timestamp": f"2026-05-18T10:00:{i:02d}.000Z",
                "request_id": f"r-{i}",
                "usage": {"completion_tokens": 4},   # legacy field
                "latency_ms": 200.0,
            }) + "\n")
    hint = compute_workload_hint(tmp_path, sample_size=200)
    assert hint["median_output_tokens"] == 4
    assert hint["regime"] == "short_completion"
