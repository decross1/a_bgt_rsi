"""Ollama-served backend (OpenAI-compatible API on :11434/v1).

Used today for the coder-tier model. The actual served model is decided by
research and pinned in `OLLAMA_MODEL` env; we don't hardcode a tag here.
"""
import os
from typing import Any

from openai import AsyncOpenAI, OpenAI


class OllamaBackend:
    def __init__(
        self,
        *,
        name: str = "ollama-coder",
        base_url: str | None = None,
        model: str | None = None,
        model_version: str | None = None,
    ):
        self.name = name
        self._base_url = base_url or os.environ.get(
            "OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1")
        self._model = model or os.environ.get("OLLAMA_MODEL", "")
        self._model_version = model_version or os.environ.get(
            "OLLAMA_MODEL_VERSION", f"ollama/{self._model}")
        # Ollama's OpenAI-compat endpoint ignores api_key but the SDK requires
        # a non-empty string.
        self._sync = OpenAI(base_url=self._base_url, api_key="ollama")
        self._async = AsyncOpenAI(base_url=self._base_url, api_key="ollama")

    @property
    def default_model(self) -> str:
        return self._model

    @property
    def model_version(self) -> str:
        return self._model_version

    @property
    def host_metadata(self) -> dict[str, Any]:
        return {"backend": "ollama", "ollama_base_url": self._base_url}

    def create_chat(self, **kwargs: Any) -> Any:
        return self._sync.chat.completions.create(**kwargs)

    async def create_chat_async(self, **kwargs: Any) -> Any:
        return await self._async.chat.completions.create(**kwargs)
