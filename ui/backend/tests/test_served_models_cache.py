"""GET /api/served_models TTL cache + parallel probing (perf, 2026-08-18).

The endpoint used to probe both vLLM servers SERIALLY inside every request
(2 s timeout each → ~4 s of blocked backend thread per poll when both are
down). These tests pin the replacement:

- within the TTL a repeat request is answered from cache — the upstream
  opener is NOT called again, and the cached response carries the ORIGINAL
  ``probed_at`` so its age is always computable (honest staleness, never a
  fake-fresh timestamp);
- past the TTL the endpoint re-probes and re-stamps;
- every role is probed and stamped on a fresh round.
"""
from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.served_models import register


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _counting_opener(mapping, calls):
    def _open(url, timeout=None):
        calls.append(url)
        if url not in mapping:
            raise OSError(f"connection refused: {url}")
        return _Resp(mapping[url])

    return _open


class _Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


ENDPOINTS = {"gemma": "http://g:8000", "qwen": "http://q:8001"}
PAYLOADS = {
    "http://g:8000/v1/models": {"data": [{"id": "gemma-4-26b-a4b"}]},
    "http://q:8001/v1/models": {"data": [{"id": "qwen3.8-27b-nvfp4-mtp"}]},
}


def _client(calls, clock, ttl_s=8.0):
    app = FastAPI()
    register(app, endpoints=ENDPOINTS,
             opener=_counting_opener(PAYLOADS, calls),
             ttl_s=ttl_s, clock=clock)
    return TestClient(app)


def test_within_ttl_serves_cache_without_reprobing():
    calls, clock = [], _Clock()
    client = _client(calls, clock)
    first = client.get("/api/served_models").json()
    assert len(calls) == 2  # one probe per role
    clock.t += 3.0  # inside the 8 s TTL
    second = client.get("/api/served_models").json()
    assert len(calls) == 2  # NO new probes
    # The cached answer is byte-identical — including probed_at, so the
    # reader can compute the true age instead of being told "fresh".
    assert second == first
    assert second["gemma"]["probed_at"] == first["gemma"]["probed_at"]


def test_past_ttl_reprobes():
    calls, clock = [], _Clock()
    client = _client(calls, clock)
    client.get("/api/served_models")
    assert len(calls) == 2
    clock.t += 9.0  # past the TTL
    resp = client.get("/api/served_models").json()
    assert len(calls) == 4  # re-probed both roles
    assert resp["gemma"]["model"] == "gemma-4-26b-a4b"
    assert resp["qwen"]["model"] == "qwen3.8-27b-nvfp4-mtp"


def test_every_role_is_probed_and_stamped():
    calls, clock = [], _Clock()
    client = _client(calls, clock)
    body = client.get("/api/served_models").json()
    assert set(body) == {"gemma", "qwen"}
    assert sorted(calls) == sorted(
        ["http://g:8000/v1/models", "http://q:8001/v1/models"])
    for role in ("gemma", "qwen"):
        assert body[role]["error"] is None
        assert isinstance(body[role]["probed_at"], str)
        assert body[role]["probed_at"].endswith("Z")


def test_failed_probe_is_cached_honestly_not_retried_in_ttl():
    calls, clock = [], _Clock()
    app = FastAPI()
    register(app, endpoints=ENDPOINTS,
             opener=_counting_opener(
                 {"http://g:8000/v1/models": PAYLOADS["http://g:8000/v1/models"]},
                 calls),
             ttl_s=8.0, clock=clock)
    client = TestClient(app)
    body = client.get("/api/served_models").json()
    assert body["qwen"]["model"] is None
    assert "connection refused" in body["qwen"]["error"]
    n = len(calls)
    clock.t += 2.0
    again = client.get("/api/served_models").json()
    assert len(calls) == n  # the failure is cached too — no probe storm
    assert again["qwen"]["model"] is None
