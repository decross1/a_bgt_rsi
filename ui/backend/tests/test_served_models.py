"""The UI must report the model that is ACTUALLY answering.

On 2026-08-16 an A/B window served Qwen 3.8 on :8001 while the dashboard kept
announcing "Qwen3.6-27B · NVFP4-MTP": the card title was a hardcoded string and
no endpoint reported the live model, so the UI could not have been right. These
tests pin the replacement — observation, and honest ignorance when the
observation fails.
"""
from __future__ import annotations

import json
from contextlib import contextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.served_models import probe, register


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _opener_for(mapping):
    @contextmanager
    def _noop():
        yield

    def _open(url, timeout=None):
        if url not in mapping:
            raise OSError(f"connection refused: {url}")
        value = mapping[url]
        if isinstance(value, Exception):
            raise value
        return _Resp(value)

    return _open


_OK = {"data": [{"id": "qwen3.8-27b-nvfp4-mtp"}]}


def test_probe_reports_the_live_model_id():
    out = probe("http://x:8001",
                opener=_opener_for({"http://x:8001/v1/models": _OK}))
    assert out == {"url": "http://x:8001",
                   "model": "qwen3.8-27b-nvfp4-mtp", "error": None}


def test_unreachable_endpoint_is_unknown_not_a_remembered_name():
    """The whole point: never fall back to a name we merely believe."""
    out = probe("http://x:8001", opener=_opener_for({}))
    assert out["model"] is None
    assert "OSError" in out["error"]


def test_malformed_payload_is_reported_not_guessed():
    for payload in ({"data": []}, {"data": "nope"}, {}, {"data": [{}]}):
        out = probe("http://x:8001",
                    opener=_opener_for({"http://x:8001/v1/models": payload}))
        assert out["model"] is None, payload
        assert out["error"]


def test_endpoint_reports_every_role_independently():
    app = FastAPI()
    register(app,
             endpoints={"gemma": "http://g:8000", "qwen": "http://q:8001"},
             opener=_opener_for({
                 "http://g:8000/v1/models": {"data": [{"id": "gemma-4-26b-a4b"}]},
                 # qwen absent -> unreachable
             }))
    body = TestClient(app).get("/api/served_models").json()
    assert body["gemma"]["model"] == "gemma-4-26b-a4b"
    assert body["qwen"]["model"] is None
    assert body["qwen"]["error"]
