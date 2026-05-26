"""Backend protocol.

Every backend speaks OpenAI-shaped chat completions: a response object with
`.model`, `.choices[0].message.{content,tool_calls}`, `.usage.{prompt_tokens,
completion_tokens}`. Native OpenAI-compatible backends (vllm, Ollama) return
the SDK type directly; non-OpenAI backends (Anthropic) adapt their response
to the same shape inside the backend.
"""
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Backend(Protocol):
    """Uniform chat-completion surface across providers."""

    name: str  # registry key, e.g. "vllm-gemma", "ollama-qwen", "anthropic"

    @property
    def default_model(self) -> str: ...

    @property
    def model_version(self) -> str:
        """Provenance string stamped into call records."""
        ...

    @property
    def host_metadata(self) -> dict[str, Any]:
        """Per-call host_metadata mixin (vllm_image_tag, sdk version, etc.)."""
        ...

    def create_chat(self, **kwargs: Any) -> Any: ...

    async def create_chat_async(self, **kwargs: Any) -> Any: ...
