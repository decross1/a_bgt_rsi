"""SGLang metrics retain their actual token and cache semantics."""
import pytest

from sampler.sources.vllm_metrics import VllmMetricsAccumulator


def snapshot(decode, *, prefill=1000):
    return (
        'sglang:num_running_reqs{model_name="nvidia/Flash"} 1\n'
        'sglang:num_queue_reqs{model_name="nvidia/Flash"} 0\n'
        'sglang:full_token_usage{model_name="nvidia/Flash"} 0.25\n'
        'sglang:token_usage{model_name="nvidia/Flash"} 0.9\n'
        f'sglang:realtime_tokens_total{{mode="prefill",model_name="nvidia/Flash"}} {prefill}\n'
        f'sglang:realtime_tokens_total{{model_name="nvidia/Flash",mode="decode"}} {decode}\n'
        'sglang:spec_accept_rate{model_name="nvidia/Flash"} 0.6\n'
        'sglang:spec_accept_length{model_name="nvidia/Flash"} 2.8\n'
        'sglang:cache_hit_rate{model_name="nvidia/Flash"} 0.4\n'
    )


def test_decode_excludes_prefill_and_cache_excludes_mamba_pressure():
    metrics = VllmMetricsAccumulator(backend="sglang")
    first, error = metrics.observe(snapshot(100), now=10)
    assert error is None
    assert first["tokens_per_sec_decode"] is None
    second, error = metrics.observe(snapshot(140, prefill=10000), now=12)
    assert error is None
    assert second == {
        "running_requests": 1,
        "waiting_requests": 0,
        "gpu_cache_usage_pct": 25,
        "gpu_prefix_cache_hit_rate": 0.4,
        "tokens_per_sec_decode": 20,
        "mtp_acceptance_rate": 0.6,
        "mtp_draft_tokens": None,
        "mtp_accepted_tokens": None,
    }


@pytest.mark.parametrize("invalid", ["NaN", "-1", "+Inf"])
def test_bad_decode_samples_break_the_interval(invalid):
    metrics = VllmMetricsAccumulator(backend="sglang")
    metrics.observe(snapshot(100), now=1)
    sample, _ = metrics.observe(snapshot(invalid), now=2)
    assert sample["tokens_per_sec_decode"] is None
    sample, _ = metrics.observe(snapshot(200), now=3)
    assert sample["tokens_per_sec_decode"] is None


def test_reset_and_ambiguous_scheduler_series_are_not_a_speed_gain():
    metrics = VllmMetricsAccumulator(backend="sglang")
    metrics.observe(snapshot(100), now=1)
    sample, _ = metrics.observe(snapshot(0), now=2)
    assert sample["tokens_per_sec_decode"] is None
    extra = 'sglang:realtime_tokens_total{mode="decode",scheduler="another"} 300\n'
    sample, _ = metrics.observe(snapshot(20) + extra, now=3)
    assert sample["tokens_per_sec_decode"] is None


def test_invalid_full_kv_fraction_is_rejected():
    metrics = VllmMetricsAccumulator(backend="sglang")
    sample, error = metrics.observe(snapshot(10).replace('} 0.25', '} 1.25'), now=1)
    assert sample is None
    assert "invalid core gauges" in error


def test_backend_must_be_code_owned():
    with pytest.raises(ValueError, match="unsupported metrics backend"):
        VllmMetricsAccumulator(backend="arbitrary")
