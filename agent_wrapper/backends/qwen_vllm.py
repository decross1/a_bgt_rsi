"""Qwen served by the second local vLLM OpenAI-compatible endpoint.

This adapter replaces the historical reuse of ``OllamaBackend``.  Endpoint,
served model, and request transport stay unchanged; provenance now identifies
the runtime as vLLM instead of Ollama.
"""

import os
from typing import Any

from openai import AsyncOpenAI, OpenAI


class VLLMQwenBackend:
    def __init__(
        self,
        *,
        name: str = "vllm-qwen",
        base_url: str | None = None,
        model: str | None = None,
        model_version: str | None = None,
        image_tag: str | None = None,
    ):
        self.name = name
        self._base_url = base_url or os.environ.get(
            "VLLM_QWEN_BASE_URL", "http://127.0.0.1:8001/v1")
        self._model = model or os.environ.get(
            "VLLM_QWEN_MODEL", "qwen3.8-27b-nvfp4-mtp")
        self._image_tag = image_tag or os.environ.get(
            "VLLM_QWEN_IMAGE_TAG",
            os.environ.get("VLLM_IMAGE_TAG", "vllm/vllm-openai:v0.21.0"),
        )
        self._model_version = model_version or os.environ.get(
            "VLLM_QWEN_MODEL_VERSION", f"{self._image_tag}/{self._model}")
        # Keep the historical API-key value so adapter correction does not
        # alter the Authorization header sent to the unauthenticated endpoint.
        api_key = os.environ.get("VLLM_QWEN_API_KEY", "ollama")
        self._sync = OpenAI(base_url=self._base_url, api_key=api_key)
        self._async = AsyncOpenAI(base_url=self._base_url, api_key=api_key)

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def default_model(self) -> str:
        return self._model

    @property
    def model_version(self) -> str:
        return self._model_version

    @property
    def host_metadata(self) -> dict[str, Any]:
        return {
            "backend": "vllm",
            "vllm_base_url": self._base_url,
            "vllm_image_tag": self._image_tag,
            "cuda_driver": os.environ.get("CUDA_DRIVER", "13.0"),
        }

    def create_chat(self, **kwargs: Any) -> Any:
        client = self._sync
        if "timeout" in kwargs:
            client = client.with_options(max_retries=0)
        return client.chat.completions.create(**kwargs)

    async def create_chat_async(self, **kwargs: Any) -> Any:
        client = self._async
        if "timeout" in kwargs:
            client = client.with_options(max_retries=0)
        return await client.chat.completions.create(**kwargs)
