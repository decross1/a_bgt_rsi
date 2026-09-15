"""Additive live model inventory, including the fixed Flash candidate."""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sampler.sources.vllm_metrics import VllmMetricsAccumulator

from backend.served_models import (
    DEFAULT_ENDPOINTS,
    REGISTERED_MODELS,
    _probe_metrics,
    register,
)


class Response:
    def __init__(self, value, *, status=200, final_url=None):
        self.value = value
        self.status = status
        self.final_url = final_url

    def read(self, limit=None):
        raw = (
            self.value.encode("utf-8")
            if isinstance(self.value, str)
            else json.dumps(self.value).encode("utf-8")
            if not isinstance(self.value, bytes)
            else self.value
        )
        return raw if limit is None else raw[:limit]

    def geturl(self):
        return self.final_url

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def opener_for(mapping):
    def open_url(url, timeout=None):
        del timeout
        if url not in mapping:
            raise OSError(f"connection refused: {url}")
        value = mapping[url]
        if isinstance(value, Exception):
            raise value
        response = value if isinstance(value, Response) else Response(value)
        if response.final_url is None:
            response.final_url = url
        return response

    return open_url


def metrics(*, running=0, waiting=0, cache=0.25, extra=""):
    return (
        f"vllm:num_requests_running {running}\n"
        f"vllm:num_requests_waiting {waiting}\n"
        f"vllm:kv_cache_usage_perc {cache}\n"
        f"{extra}"
    )


def client(mapping, endpoints=None):
    app = FastAPI()
    register(
        app,
        endpoints=endpoints or {
            "gemma": "http://g:8000",
            "qwen": "http://q:8001",
            "flash": "http://f:8012",
        },
        opener=opener_for(mapping),
    )
    return TestClient(app)


def test_fixed_registry_has_two_residents_and_one_unpromoted_candidate():
    assert DEFAULT_ENDPOINTS == {
        "gemma": "http://127.0.0.1:8000",
        "qwen": "http://127.0.0.1:8001",
        "flash": "http://127.0.0.1:8012",
    }
    assert REGISTERED_MODELS["flash"] == {
        "url": "http://127.0.0.1:8012",
        "configured_model": "qwen3.8-flash-next",
        "configured_max_context_tokens": 32_768,
        "deployment_role": "research_candidate",
        "benchmark_cohort": "flash",
    }


def test_inventory_preserves_legacy_fields_and_separates_idle_from_offline():
    body = client({
        "http://g:8000/v1/models": {
            "data": [{"id": "gemma-4-26b-a4b", "max_model_len": 32768}]
        },
        "http://g:8000/metrics": metrics(running=0),
        "http://q:8001/v1/models": {"data": [{"id": "qwen3.8-27b-nvfp4-mtp"}]},
        "http://q:8001/metrics": metrics(running=2, waiting=1, cache=0.5),
        # Flash absent between research windows.
    }).get("/api/served_models").json()

    assert set(body) == {"gemma", "qwen", "flash"}
    assert {key: body["gemma"][key] for key in ("url", "model", "error")} == {
        "url": "http://g:8000", "model": "gemma-4-26b-a4b", "error": None,
    }
    assert body["gemma"]["service_status"] == "online"
    assert body["gemma"]["identity_status"] == "match"
    assert body["gemma"]["configured_max_context_tokens"] == 32768
    assert body["gemma"]["observed_max_context_tokens"] == 32768
    assert body["gemma"]["activity_status"] == "idle"
    assert body["qwen"]["activity_status"] == "busy"
    assert body["qwen"]["metrics"]["gpu_cache_usage_pct"] == 50
    assert body["flash"]["service_status"] == "offline"
    assert body["flash"]["configured_max_context_tokens"] == 32768
    assert body["flash"]["observed_max_context_tokens"] is None
    assert body["flash"]["activity_status"] == "unknown"
    assert body["flash"]["metrics"] is None
    assert body["flash"]["deployment_role"] == "research_candidate"
    assert body["flash"]["promotion_authorized"] is False


def test_wrong_model_is_online_but_identity_mismatch():
    one = {"flash": "http://f:8012"}
    body = client({
        "http://f:8012/v1/models": {"data": [{"id": "other-model"}]},
        "http://f:8012/metrics": metrics(),
    }, endpoints=one).get("/api/served_models").json()["flash"]
    assert body["models_endpoint_status"] == "available"
    assert body["service_status"] == "online"
    assert body["identity_status"] == "mismatch"
    assert body["model"] == "other-model"


def test_metrics_failure_does_not_turn_a_serving_model_offline():
    one = {"flash": "http://f:8012"}
    body = client({
        "http://f:8012/v1/models": {
            "data": [{"id": "qwen3.8-flash-next", "max_model_len": 16384}]
        },
        "http://f:8012/metrics": "not prometheus core gauges\n",
    }, endpoints=one).get("/api/served_models").json()["flash"]
    assert body["service_status"] == "online"
    assert body["identity_status"] == "match"
    assert body["configured_max_context_tokens"] == 32768
    assert body["observed_max_context_tokens"] == 16384
    assert body["metrics_endpoint_status"] == "invalid_response"
    assert body["activity_status"] == "unknown"
    assert body["metrics"] is None
    assert "missing core gauges" in body["metrics_error"]


@pytest.mark.parametrize("failure", [OSError("offline"), b"\xff", b"x" * 2_000_001])
def test_inventory_metrics_reprime_after_transport_or_encoding_failure(failure):
    url = "http://f:8012"
    accumulator = VllmMetricsAccumulator()

    def read(value, now):
        return _probe_metrics(
            url, timeout=0.1, opener=opener_for({url + "/metrics": value}),
            accumulator=accumulator, metric_clock=lambda: now,
        )

    def sample(count):
        return metrics(extra=f"vllm:generation_tokens_total {count}\n")

    read(sample(10), 1)
    assert read(sample(20), 2)["metrics"]["tokens_per_sec_decode"] == 10
    assert read(failure, 3)["metrics"] is None
    assert read(sample(40), 4)["metrics"]["tokens_per_sec_decode"] is None
    assert read(sample(50), 5)["metrics"]["tokens_per_sec_decode"] == 10


def test_nonfinite_optional_metrics_are_withheld_without_breaking_json():
    one = {"flash": "http://f:8012"}
    malformed_optional = metrics(extra=(
        "vllm:generation_tokens_total NaN\n"
        "vllm:gpu_prefix_cache_hit_rate +Inf\n"
        "vllm:spec_decode_draft_acceptance_rate -1\n"
        "vllm:spec_decode_num_draft_tokens_total +Inf\n"
    ))
    response = client({
        "http://f:8012/v1/models": {"data": [{"id": "qwen3.8-flash-next"}]},
        "http://f:8012/metrics": malformed_optional,
    }, endpoints=one).get("/api/served_models")
    assert response.status_code == 200
    sample = response.json()["flash"]["metrics"]
    assert sample["tokens_per_sec_decode"] is None
    assert sample["gpu_prefix_cache_hit_rate"] is None
    assert sample["mtp_acceptance_rate"] is None
    assert sample["mtp_draft_tokens"] is None


def test_redirect_and_oversize_are_invalid_and_never_followed():
    one = {"flash": "http://f:8012"}
    body = client({
        "http://f:8012/v1/models": Response(
            {"data": [{"id": "qwen3.8-flash-next"}]},
            final_url="http://elsewhere/v1/models",
        ),
        "http://f:8012/metrics": b"x" * 2_000_001,
    }, endpoints=one).get("/api/served_models").json()["flash"]
    assert body["models_endpoint_status"] == "invalid_response"
    assert body["service_status"] == "unknown"
    assert body["metrics_endpoint_status"] == "invalid_response"


def test_endpoint_injection_cannot_add_an_unregistered_role():
    with pytest.raises(ValueError, match="registered roles"):
        register(FastAPI(), endpoints={"attacker": "http://example.com"})
