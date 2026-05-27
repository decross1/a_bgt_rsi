"""Backend registry surface.

Verifies the additive multi-backend substrate: vllm-gemma stays the default,
ollama-coder is registered, unknown names raise KeyError, and the vllm-gemma
backend reads `wrapper._sync_client` lazily so existing `patch.object`-style
mocks continue to flow through.
"""
from unittest.mock import MagicMock, patch

import pytest

from agent_wrapper import wrapper as W
from agent_wrapper.backends import get_backend, list_backends
from agent_wrapper.backends.ollama_openai import OllamaBackend
from agent_wrapper.backends.vllm_openai import VLLMBackend


class TestRegistry:
    def test_vllm_gemma_registered_by_default(self):
        assert "vllm-gemma" in list_backends()
        be = get_backend("vllm-gemma")
        assert isinstance(be, VLLMBackend)

    def test_ollama_coder_registered_by_default(self):
        assert "ollama-coder" in list_backends()
        assert isinstance(get_backend("ollama-coder"), OllamaBackend)

    def test_unknown_backend_raises(self):
        with pytest.raises(KeyError, match="unknown backend"):
            get_backend("does-not-exist")

    def test_default_backend_constant_is_vllm_gemma(self):
        # Sanity: env-overridable, but the unset default must stay
        # vllm-gemma so existing callers don't change behavior.
        assert W.DEFAULT_BACKEND == "vllm-gemma"


class TestVLLMBackendLazyLookup:
    """The vllm-gemma backend must resolve `wrapper._sync_client` at call
    time, not at construction time, so tests that patch the client through
    `patch.object(wrapper, "_sync_client", MagicMock())` keep working."""

    def test_create_chat_routes_to_patched_sync_client(self):
        be = VLLMBackend()
        with patch.object(W, "_sync_client", MagicMock()) as mock_client:
            mock_client.chat.completions.create.return_value = "sentinel"
            result = be.create_chat(model="m", messages=[], max_tokens=8)
            assert result == "sentinel"
            mock_client.chat.completions.create.assert_called_once()

    def test_provenance_reads_module_constants(self):
        be = VLLMBackend()
        assert be.default_model == W.MODEL
        assert be.model_version == W.MODEL_VERSION
        assert be.host_metadata == W.HOST_METADATA
        # Independent dict; mutating return doesn't poison the module const.
        be.host_metadata["x"] = 1
        assert "x" not in W.HOST_METADATA


class TestCallSyncBackendKwarg:
    """call_sync routes through the named backend and stamps that backend's
    model_version + host_metadata into the record."""

    def test_default_backend_path_stamps_module_provenance(self):
        with patch.object(W, "_sync_client", MagicMock()) as mc:
            mc.chat.completions.create.return_value = MagicMock(
                model="gemma-served",
                choices=[MagicMock(message=MagicMock(content="ok"))],
                usage=MagicMock(prompt_tokens=1, completion_tokens=2),
            )
            rec = W.call_sync([{"role": "user", "content": "hi"}],
                              caller_tag="t", log_path=None)
            assert rec["model_version"] == W.MODEL_VERSION
            assert rec["host_metadata"] == W.HOST_METADATA

    def test_unknown_backend_kwarg_raises(self):
        with pytest.raises(KeyError):
            W.call_sync([{"role": "user", "content": "hi"}],
                        backend="does-not-exist", log_path=None)
