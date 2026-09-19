"""Pinned NVIDIA Flash model served by the local SGLang resident."""

from __future__ import annotations

from typing import Any

from openai import AsyncOpenAI, OpenAI

from agent_wrapper.deployment import ModelDeployment, load_model_deployment
from agent_wrapper.upgrade_lease import local_inference

from .vllm_streaming import (
    complete_async,
    complete_sync,
    live_trace_request_supported,
    live_trace_stream_enabled,
)


class SGLangFlashBackend:
    """OpenAI-compatible transport with config-bound runtime provenance."""

    name = "sglang-flash"

    def __init__(
        self,
        deployment: ModelDeployment | None = None,
        *,
        sync_client: Any | None = None,
        async_client: Any | None = None,
    ) -> None:
        self._deployment_override = deployment
        self._sync_override = sync_client
        self._async_override = async_client
        self._cached_deployment: ModelDeployment | None = None
        self._sync_client: Any | None = None
        self._async_client: Any | None = None

    def _deployment(self) -> ModelDeployment:
        if self._deployment_override is not None:
            return self._deployment_override
        # Load once per backend instance. The committed selection is immutable
        # for a running process; live phase/identity belong to the supervisor.
        if self._cached_deployment is None:
            self._cached_deployment = load_model_deployment()
        return self._cached_deployment

    @property
    def base_url(self) -> str:
        return self._deployment().base_url

    @property
    def default_model(self) -> str:
        return self._deployment().model

    @property
    def model_version(self) -> str:
        return self._deployment().model_version

    @property
    def host_metadata(self) -> dict[str, Any]:
        return self._deployment().host_metadata

    def _sync(self) -> Any:
        if self._sync_override is not None:
            return self._sync_override
        if self._sync_client is None:
            self._sync_client = OpenAI(base_url=self.base_url, api_key="EMPTY")
        return self._sync_client

    def _async(self) -> Any:
        if self._async_override is not None:
            return self._async_override
        if self._async_client is None:
            self._async_client = AsyncOpenAI(
                base_url=self.base_url, api_key="EMPTY")
        return self._async_client

    def _validate_response(self, response: Any) -> Any:
        observed = getattr(response, "model", None)
        if observed != self.default_model:
            raise RuntimeError(
                "SGLang response model identity mismatch: "
                f"expected {self.default_model!r}, got {observed!r}"
            )
        return response

    def create_chat(self, **kwargs: Any) -> Any:
        client = self._sync()
        if "timeout" in kwargs:
            client = client.with_options(max_retries=0)
        if live_trace_stream_enabled() and live_trace_request_supported(kwargs):
            return self._validate_response(
                complete_sync(
                    client,
                    kwargs,
                    backend_name=self.name,
                    lease_factory=local_inference,
                )
            )
        with local_inference():
            return self._validate_response(
                client.chat.completions.create(**kwargs))

    async def create_chat_async(self, **kwargs: Any) -> Any:
        client = self._async()
        if "timeout" in kwargs:
            client = client.with_options(max_retries=0)
        if live_trace_stream_enabled() and live_trace_request_supported(kwargs):
            return self._validate_response(
                await complete_async(
                    client,
                    kwargs,
                    backend_name=self.name,
                    lease_factory=local_inference,
                )
            )
        with local_inference():
            return self._validate_response(
                await client.chat.completions.create(**kwargs))


__all__ = ["SGLangFlashBackend"]
