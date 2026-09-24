"""Permanent Flash deployment parsing, transport, and wrapper routing."""

from __future__ import annotations

import asyncio
import json
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from agent_wrapper import wrapper as W
from agent_wrapper.backends import sglang_flash
from agent_wrapper.backends.sglang_flash import SGLangFlashBackend
from agent_wrapper.deployment import (
    FLASH_BACKEND,
    FLASH_BASE_URL,
    FLASH_MODEL,
    ModelDeployment,
    load_model_deployment,
)


def _manifest() -> dict:
    return {
        "schema_version": 1,
        "topology": "single_flash",
        "backend": FLASH_BACKEND,
        "model": FLASH_MODEL,
        "base_url": FLASH_BASE_URL,
        "context_length": 262144,
        "max_running_requests": 4,
        "production_authorized": True,
        "selected_at": "2026-09-19",
        "model_revision": "a" * 40,
        "image_id": f"sha256:{'b' * 64}",
        "profile_sha256": "c" * 64,
        "host_reserve_gib": 10,
        "automated_benchmarks_enabled": False,
    }


def _deployment() -> ModelDeployment:
    return ModelDeployment(
        backend=FLASH_BACKEND,
        model=FLASH_MODEL,
        base_url=FLASH_BASE_URL,
        context_length=262144,
        max_running_requests=4,
        model_revision="a" * 40,
        image_id=f"sha256:{'b' * 64}",
        profile_sha256="c" * 64,
        host_reserve_gib=10,
        selected_at="2026-09-19",
        config_sha256="d" * 64,
    )


def _response(*, model=FLASH_MODEL, content="answer", tool_calls=None,
              reasoning=None):
    return SimpleNamespace(
        model=model,
        choices=[SimpleNamespace(
            finish_reason="tool_calls" if tool_calls else "stop",
            message=SimpleNamespace(
                content=content,
                tool_calls=tool_calls,
                reasoning=reasoning,
                reasoning_content=None,
                model_extra=None,
            ),
        )],
        usage=SimpleNamespace(prompt_tokens=3, completion_tokens=5),
    )


class _CaptureBackend:
    def __init__(self, *, name=FLASH_BACKEND, model=FLASH_MODEL,
                 responses=None):
        self.name = name
        self.default_model = model
        self.model_version = f"test/{model}"
        self.host_metadata = {"backend": name}
        self.calls = []
        self.responses = list(responses or [_response(model=model)])

    def create_chat(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)

    async def create_chat_async(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


@pytest.fixture
def flash_route(monkeypatch):
    monkeypatch.delenv("WRAPPER_DEFAULT_BACKEND", raising=False)
    monkeypatch.setattr(W, "_PROJECT_DEPLOYMENT", _deployment())
    monkeypatch.setattr(W.worker_activity, "emit_worker_activity", lambda **_kw: None)
    W.MEMORY_LOG.clear()


def test_manifest_loader_binds_exact_runtime_and_content_hash(tmp_path):
    path = tmp_path / "model_deployment.json"
    raw = json.dumps(_manifest(), separators=(",", ":")).encode()
    path.write_bytes(raw)

    deployment = load_model_deployment(path)

    assert deployment.backend == FLASH_BACKEND
    assert deployment.model == FLASH_MODEL
    assert deployment.base_url == FLASH_BASE_URL
    assert deployment.model_revision == "a" * 40
    assert deployment.host_metadata["deployment_config_sha256"] == (
        __import__("hashlib").sha256(raw).hexdigest()
    )
    assert deployment.model_version.startswith(f"{FLASH_MODEL}@{'a' * 40};")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("base_url", "http://example.invalid/v1"),
        ("model", "flash-alias"),
        ("production_authorized", False),
        ("automated_benchmarks_enabled", True),
        ("context_length", 16384),
        # Only counts with a reviewed serving profile are admitted (C1/C2/C4).
        ("max_running_requests", 3),
        ("max_running_requests", 8),
        ("max_running_requests", 0),
        ("max_running_requests", True),
        ("max_running_requests", "4"),
        ("max_running_requests", 4.0),
        ("max_running_requests", None),
    ],
)
def test_manifest_loader_rejects_drifted_selection(tmp_path, field, value):
    manifest = _manifest()
    manifest[field] = value
    path = tmp_path / "model_deployment.json"
    path.write_text(json.dumps(manifest))

    with pytest.raises(ValueError, match=field):
        load_model_deployment(path)


@pytest.mark.parametrize("running", [1, 2, 4])
def test_manifest_loader_admits_each_reviewed_running_request_count(tmp_path, running):
    # C1 (helper v8), C2 (v9) and C4 (v10) load without a code edit, so a
    # rollback is a config and pin revert only. The count is the declared one.
    manifest = _manifest()
    manifest["max_running_requests"] = running
    path = tmp_path / "model_deployment.json"
    path.write_text(json.dumps(manifest))

    deployment = load_model_deployment(path)

    assert deployment.max_running_requests == running
    assert deployment.host_metadata["max_running_requests"] == running


def test_manifest_loader_rejects_missing_running_request_count(tmp_path):
    manifest = _manifest()
    del manifest["max_running_requests"]
    path = tmp_path / "model_deployment.json"
    path.write_text(json.dumps(manifest))

    with pytest.raises(ValueError, match="max_running_requests"):
        load_model_deployment(path)


def test_manifest_loader_rejects_symlinks_and_malformed_present_files(tmp_path):
    target = tmp_path / "target.json"
    target.write_text(json.dumps(_manifest()))
    link = tmp_path / "deployment.json"
    link.symlink_to(target)
    with pytest.raises(ValueError, match="non-symlink"):
        load_model_deployment(link)

    bad = tmp_path / "bad.json"
    bad.write_text("not json")
    with pytest.raises(ValueError, match="valid JSON"):
        load_model_deployment(bad, required=False)
    assert load_model_deployment(tmp_path / "missing.json", required=False) is None


def test_sglang_backend_uses_bound_endpoint_and_rejects_response_alias(
    monkeypatch,
):
    client = MagicMock()
    client.chat.completions.create.return_value = _response()
    monkeypatch.setattr(sglang_flash, "local_inference", nullcontext)
    monkeypatch.setattr(sglang_flash, "live_trace_stream_enabled", lambda: False)
    backend = SGLangFlashBackend(_deployment(), sync_client=client)

    result = backend.create_chat(model=FLASH_MODEL, messages=[], max_tokens=None)

    assert result.model == FLASH_MODEL
    assert backend.base_url == FLASH_BASE_URL
    client.chat.completions.create.assert_called_once_with(
        model=FLASH_MODEL, messages=[], max_tokens=None)

    client.chat.completions.create.return_value = _response(model="flash-alias")
    with pytest.raises(RuntimeError, match="model identity mismatch"):
        backend.create_chat(model=FLASH_MODEL, messages=[])


def test_sglang_budgeted_call_is_retryless(monkeypatch):
    client = MagicMock()
    retryless = MagicMock()
    client.with_options.return_value = retryless
    retryless.chat.completions.create.return_value = _response()
    monkeypatch.setattr(sglang_flash, "local_inference", nullcontext)
    monkeypatch.setattr(sglang_flash, "live_trace_stream_enabled", lambda: False)
    backend = SGLangFlashBackend(_deployment(), sync_client=client)

    backend.create_chat(model=FLASH_MODEL, messages=[], timeout=12.5)

    client.with_options.assert_called_once_with(max_retries=0)
    retryless.chat.completions.create.assert_called_once_with(
        model=FLASH_MODEL, messages=[], timeout=12.5)


def test_default_generator_role_routes_to_flash_with_explicit_off_policy(
    flash_route, monkeypatch,
):
    backend = _CaptureBackend()
    requested = []

    def get_backend(name):
        requested.append(name)
        return backend

    monkeypatch.setattr(W, "get_backend", get_backend)
    record = W.call_sync(
        [{"role": "user", "content": "hi"}],
        model="gemma-4-26b-a4b",
        caller_tag="test/default-flash",
        log_path=None,
    )

    assert requested == [FLASH_BACKEND]
    assert backend.calls[0] == {
        "model": FLASH_MODEL,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": None,
        "temperature": 0.7,
        "top_p": 0.8,
        "seed": None,
        "extra_body": {
            "top_k": 20,
            "min_p": 0,
            "presence_penalty": 1.5,
            "repetition_penalty": 1,
            "chat_template_kwargs": {"enable_thinking": False},
        },
    }
    assert record["backend"] == FLASH_BACKEND
    assert record["model"] == FLASH_MODEL
    assert record["reasoning_effort"] is None
    assert record["host_metadata"]["requested_backend_role"] == "vllm-gemma"
    assert record["host_metadata"]["generation_role"] == "generator"
    assert "max_tokens" not in record


def test_legacy_qwen_role_routes_to_flash_with_medium_critic_policy(
    flash_route, monkeypatch,
):
    backend = _CaptureBackend()
    monkeypatch.setattr(W, "get_backend", lambda name: backend)

    record = W.call_sync(
        [{"role": "user", "content": "review"}],
        backend="vllm-qwen",
        model="qwen3.8-27b-nvfp4-mtp",
        log_path=None,
    )

    sent = backend.calls[0]
    assert (sent["temperature"], sent["top_p"]) == (1.0, 0.95)
    assert sent["reasoning_effort"] == "medium"
    assert sent["extra_body"] == {
        "top_k": 20,
        "min_p": 0,
        "presence_penalty": 0,
        "repetition_penalty": 1,
        "chat_template_kwargs": {"enable_thinking": True},
    }
    assert record["backend"] == FLASH_BACKEND
    assert record["reasoning_effort"] == "medium"
    assert record["host_metadata"]["requested_backend_role"] == "vllm-qwen"
    assert record["host_metadata"]["generation_role"] == "critic"


def test_injected_registry_lookup_still_resolves_actual_flash_route(
    flash_route,
):
    backend = _CaptureBackend()
    requested = []

    route = W.resolve_backend_route(
        "vllm-qwen",
        backend_lookup=lambda name: requested.append(name) or backend,
    )

    assert requested == [FLASH_BACKEND]
    assert route.backend is backend
    assert route.requested_backend == "vllm-qwen"
    assert route.generation_role == "critic"
    assert route.model("qwen3.8-27b-nvfp4-mtp") == FLASH_MODEL


def test_sync_async_and_tool_paths_keep_actual_flash_identity(
    flash_route, monkeypatch,
):
    tool_call = SimpleNamespace(
        id="call-1",
        type="function",
        function=SimpleNamespace(name="identity", arguments='{"value":2}'),
    )
    backend = _CaptureBackend(responses=[
        _response(content="sync"),
        _response(content="async"),
        _response(content=None, tool_calls=[tool_call], reasoning="inspect"),
        _response(content="done"),
    ])
    monkeypatch.setattr(W, "get_backend", lambda name: backend)
    messages = [{"role": "user", "content": "go"}]
    tools = [{
        "spec": {
            "type": "function",
            "function": {
                "name": "identity",
                "parameters": {
                    "type": "object",
                    "properties": {"value": {"type": "integer"}},
                    "required": ["value"],
                },
            },
        },
        "impl": lambda value: {"value": value},
    }]

    sync_record = W.call_sync(messages, log_path=None)
    async_record = asyncio.run(W.call_async(messages, log_path=None))
    tool_records = W.call_with_tools(
        messages, tools, backend="vllm-qwen", max_depth=1, log_path=None)

    assert sync_record["backend"] == async_record["backend"] == FLASH_BACKEND
    assert all(record["backend"] == FLASH_BACKEND for record in tool_records)
    staged_assistant = backend.calls[3]["messages"][1]
    assert staged_assistant["reasoning"] == "inspect"
    assert backend.calls[2]["reasoning_effort"] == "medium"


def test_explicit_resident_and_process_env_bypass_role_aliasing(
    flash_route, monkeypatch,
):
    resident = _CaptureBackend(
        name="resident-vllm-gemma",
        model="gemma-4-26b-a4b",
        responses=[
            _response(model="gemma-4-26b-a4b"),
            _response(model="gemma-4-26b-a4b"),
        ],
    )
    requested = []

    def get_backend(name):
        requested.append(name)
        return resident

    monkeypatch.setattr(W, "get_backend", get_backend)
    explicit = W.call_sync(
        [{"role": "user", "content": "hi"}],
        backend="resident-vllm-gemma",
        log_path=None,
    )
    monkeypatch.setenv("WRAPPER_DEFAULT_BACKEND", "resident-vllm-gemma")
    env_default = W.call_sync(
        [{"role": "user", "content": "hi"}], log_path=None)

    assert requested == ["resident-vllm-gemma", "resident-vllm-gemma"]
    assert explicit["backend"] == env_default["backend"] == "resident-vllm-gemma"
    assert explicit["host_metadata"] == {"backend": "resident-vllm-gemma"}
    assert resident.calls[0]["temperature"] == resident.calls[1]["temperature"] == 0
    assert all("extra_body" not in call for call in resident.calls)


def test_unknown_model_alias_is_rejected_before_transport(
    flash_route, monkeypatch,
):
    backend = _CaptureBackend()
    monkeypatch.setattr(W, "get_backend", lambda name: backend)

    with pytest.raises(ValueError, match="serves only"):
        W.call_sync(
            [{"role": "user", "content": "hi"}],
            model="unverified/model-alias",
            log_path=None,
        )
    assert backend.calls == []
