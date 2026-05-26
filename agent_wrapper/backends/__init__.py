"""Backend registry. Each backend exposes a uniform chat-completion surface
so the same call sites in `agent_wrapper.wrapper` work for vllm-served
Gemma, Ollama-served Qwen, or the Anthropic API.

The registry is process-global; backends register themselves at import time
of `agent_wrapper.wrapper`. Callers select a backend by name via the
`backend=` kwarg on `call_sync`/`call_async`/`call_with_tools`; absent that,
`WRAPPER_DEFAULT_BACKEND` (env, defaulting to `vllm-gemma`) is used.
"""
from .base import Backend

_REGISTRY: dict[str, Backend] = {}


def register_backend(backend: Backend) -> None:
    _REGISTRY[backend.name] = backend


def get_backend(name: str) -> Backend:
    if name not in _REGISTRY:
        raise KeyError(
            f"unknown backend {name!r}; registered: {sorted(_REGISTRY)}")
    return _REGISTRY[name]


def list_backends() -> list[str]:
    return sorted(_REGISTRY)


__all__ = ["Backend", "register_backend", "get_backend", "list_backends"]
