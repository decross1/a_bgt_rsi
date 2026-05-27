"""vLLM-served Gemma backend.

Reads the client + model + provenance constants from `agent_wrapper.wrapper`
at call time. The lazy lookup is intentional: existing tests patch
`wrapper._sync_client` / `wrapper._async_client` directly with MagicMock, and
those patches must continue to flow through this backend without
modification.
"""
from typing import Any


class VLLMBackend:
    name = "vllm-gemma"

    def _w(self):
        from agent_wrapper import wrapper as W
        return W

    @property
    def default_model(self) -> str:
        return self._w().MODEL

    @property
    def model_version(self) -> str:
        return self._w().MODEL_VERSION

    @property
    def host_metadata(self) -> dict[str, Any]:
        return dict(self._w().HOST_METADATA)

    def create_chat(self, **kwargs: Any) -> Any:
        return self._w()._sync_client.chat.completions.create(**kwargs)

    async def create_chat_async(self, **kwargs: Any) -> Any:
        return await self._w()._async_client.chat.completions.create(**kwargs)
