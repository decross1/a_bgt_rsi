import pytest

from bench.flash_next_ab.followon_timing import TimingRecorder, validate_timings


def _call(status="returned"):
    return {"call_id": "cell#0", "request_sha256": "a" * 64,
            "response_stream_sha256": "b" * 64 if status == "returned" else None,
            "status": status, "wall_s": 2.01,
            "usage": {"prompt_tokens": 100, "completion_tokens": 11}}


def test_timing_preserved_and_exact_rate_recomputed():
    recorder = TimingRecorder()
    call = _call()
    raw = {**call, "latency_s": 2.0, "ttft_s": 1.0}
    assert recorder.wrap(lambda: raw)() is raw
    rows = recorder.for_calls([call])
    assert rows[0]["ttft_s"] == 1.0
    assert rows[0]["request_completion_tokens_per_second"] == 5.5
    assert rows[0]["approximate_decode_tokens_per_second"] == 10
    validate_timings([call], rows)
    rows[0]["approximate_decode_tokens_per_second"] = 100
    with pytest.raises(ValueError):
        validate_timings([call], rows)


def test_failed_or_missing_timing_never_becomes_a_speed_score():
    recorder = TimingRecorder()
    calls = [_call("timeout"), _call()]
    rows = recorder.for_calls(calls)
    assert [row["status"] for row in rows] == ["unavailable", "unavailable"]
    assert all(row["latency_s"] is None for row in rows)
    validate_timings(calls, rows)


def test_invalid_first_token_or_identity_is_withheld():
    call = _call()
    recorder = TimingRecorder()
    recorder.wrap(lambda: {**call, "latency_s": 2.0, "ttft_s": 3.0})()
    rows = recorder.for_calls([call])
    assert rows[0]["status"] == "unavailable"
    assert rows[0]["reason"] == "timing_or_usage_binding_invalid"
    validate_timings([call], rows)


def test_repeated_identical_requests_consume_distinct_observations():
    call = _call()
    recorder = TimingRecorder()
    for first in (0.5, 0.7):
        recorder.wrap(lambda first=first: {**call, "latency_s": 2.0, "ttft_s": first})()
    rows = recorder.for_calls([call, call])
    assert [row["ttft_s"] for row in rows] == [0.5, 0.7]
