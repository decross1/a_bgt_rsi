"""vLLM-served Gemma backend.

Reads the client + model + provenance constants from `agent_wrapper.wrapper`
at call time. The lazy lookup is intentional: existing tests patch
`wrapper._sync_client` / `wrapper._async_client` directly with MagicMock, and
those patches must continue to flow through this backend without
modification.
"""
from typing import Any

from agent_wrapper.upgrade_lease import local_inference

from .vllm_streaming import (
    complete_async,
    complete_sync,
    live_trace_request_supported,
    live_trace_stream_enabled,
)


class VLLMBackend:
    def __init__(self, *, name: str = "vllm-gemma") -> None:
        self.name = name

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
        client = self._w()._sync_client
        if "timeout" in kwargs:
            # Budgeted eval calls must not multiply their declared timeout via
            # the SDK's automatic retries. Legacy calls keep client defaults.
            client = client.with_options(max_retries=0)
        if live_trace_stream_enabled() and live_trace_request_supported(kwargs):
            return complete_sync(
                client,
                kwargs,
                backend_name=self.name,
                lease_factory=local_inference,
            )
        with local_inference():
            return client.chat.completions.create(**kwargs)

    async def create_chat_async(self, **kwargs: Any) -> Any:
        client = self._w()._async_client
        if "timeout" in kwargs:
            client = client.with_options(max_retries=0)
        if live_trace_stream_enabled() and live_trace_request_supported(kwargs):
            return await complete_async(
                client,
                kwargs,
                backend_name=self.name,
                lease_factory=local_inference,
            )
        with local_inference():
            return await client.chat.completions.create(**kwargs)
