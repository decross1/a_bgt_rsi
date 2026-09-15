"""Counter rates are finite, interval-local, and reset-safe."""
from sampler.sources.vllm_metrics import VllmMetricsAccumulator


def snapshot(generation, *, prefix="", spec=""):
    return (
        "vllm:num_requests_running 0\n"
        "vllm:num_requests_waiting 0\n"
        "vllm:kv_cache_usage_perc 0.25\n"
        f"vllm:generation_tokens_total {generation}\n"
        f"{prefix}{spec}"
    )


def test_decode_rate_primes_resets_and_does_not_bridge_a_malformed_gap():
    accumulator = VllmMetricsAccumulator()
    first, error = accumulator.observe(snapshot(100), now=10)
    assert error is None
    assert first["tokens_per_sec_decode"] is None

    second, _ = accumulator.observe(snapshot(120), now=12)
    assert second["tokens_per_sec_decode"] == 10

    malformed, _ = accumulator.observe(snapshot("NaN"), now=13)
    assert malformed["tokens_per_sec_decode"] is None
    after_gap, _ = accumulator.observe(snapshot(140), now=14)
    assert after_gap["tokens_per_sec_decode"] is None

    reset, _ = accumulator.observe(snapshot(130), now=15)
    assert reset["tokens_per_sec_decode"] is None
    recovered, _ = accumulator.observe(snapshot(150), now=17)
    assert recovered["tokens_per_sec_decode"] == 10


def test_invalid_optional_fractions_and_counters_are_withheld():
    accumulator = VllmMetricsAccumulator()
    sample, error = accumulator.observe(
        snapshot(
            1,
            prefix="vllm:gpu_prefix_cache_hit_rate +Inf\n",
            spec=(
                "vllm:spec_decode_draft_acceptance_rate -1\n"
                "vllm:spec_decode_num_draft_tokens_total NaN\n"
                "vllm:spec_decode_num_accepted_tokens_total +Inf\n"
            ),
        ),
        now=1,
    )
    assert error is None
    assert sample["gpu_prefix_cache_hit_rate"] is None
    assert sample["mtp_acceptance_rate"] is None
    assert sample["mtp_draft_tokens"] is None
    assert sample["mtp_accepted_tokens"] is None


def test_invalid_core_gauge_rejects_only_that_metrics_snapshot():
    accumulator = VllmMetricsAccumulator()
    sample, error = accumulator.observe(
        snapshot(1).replace("vllm:num_requests_running 0", "vllm:num_requests_running -1"),
        now=1,
    )
    assert sample is None
    assert error == "vllm /metrics has invalid core gauges"
