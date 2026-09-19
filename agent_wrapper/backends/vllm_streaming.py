"""Opt-in streaming adapter for local OpenAI-compatible model backends.

The ordinary backend contract returns one OpenAI ``ChatCompletion`` object.
When explicitly enabled, this module consumes the SDK's chunk stream while
holding the local-inference lease, publishes bounded UI snapshots, and
reconstructs that same completion object for existing callers.

The disabled path lives in each backend and never calls this module's request
helpers, so legacy request kwargs remain unchanged.

The opt-in path deliberately supports the wrapper's current local-call shape:
one text/tool choice without streamed logprobs or refusals. It fails closed on
those unsupported response shapes instead of returning a lossy completion.
Backends leave valid requests outside that shape on their original nonstreaming
path, so enabling telemetry does not make an existing call invalid.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import time
from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from contextlib import AbstractContextManager
from typing import Any

from openai.types.chat import ChatCompletion
from pydantic import ValidationError

from agent_wrapper.live_trace import WRITE_INTERVAL_S, start_trace

_FINISH_REASONS = frozenset({"stop", "length", "tool_calls", "content_filter"})


class StreamProtocolError(RuntimeError):
    """A local vLLM stream ended without one complete, attributable result."""


def live_trace_stream_enabled() -> bool:
    """Require two explicit switches because streaming changes request wire."""

    return (
        os.environ.get("WRAPPER_LIVE_TRACE_STREAM") == "1"
        and bool(os.environ.get("LOCAL_MODEL_TRACE_DIR"))
    )


def live_trace_request_supported(kwargs: Mapping[str, Any]) -> bool:
    """Whether a request can be reconstructed without changing its contract."""

    if "stream" in kwargs or "stream_options" in kwargs:
        return False
    n = kwargs.get("n", 1)
    if n is not None and (isinstance(n, bool) or not isinstance(n, int) or n != 1):
        return False
    return (
        kwargs.get("logprobs") in (None, False)
        and kwargs.get("top_logprobs") is None
    )


def _value(obj: Any, name: str) -> Any:
    value = getattr(obj, name, None)
    if value is not None:
        return value
    extra = getattr(obj, "model_extra", None)
    return extra.get(name) if isinstance(extra, Mapping) else None


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        result = dump(mode="json", exclude_none=True)
        if isinstance(result, dict):
            return result
    raise StreamProtocolError("stream usage is not an object")


class _Accumulator:
    def __init__(self, expected_model: str) -> None:
        self.expected_model = expected_model
        self.response_id: str | None = None
        self.created: int | None = None
        self.system_fingerprint: str | None = None
        self.service_tier: str | None = None
        self.content: list[str] = []
        self.reasoning: list[str] = []
        self.saw_content = False
        self.saw_answer_text = False
        self.saw_reasoning = False
        self.tools: dict[int, dict[str, Any]] = {}
        self.finish_reason: str | None = None
        self.usage: dict[str, Any] | None = None
        self.events = 0

    def _identity(self, chunk: Any) -> None:
        response_id = getattr(chunk, "id", None)
        model = getattr(chunk, "model", None)
        created = getattr(chunk, "created", None)
        if not isinstance(response_id, str) or not response_id:
            raise StreamProtocolError("stream response id is absent")
        if model != self.expected_model:
            raise StreamProtocolError("stream response model identity drift")
        if isinstance(created, bool) or not isinstance(created, int) or created < 0:
            raise StreamProtocolError("stream creation time is invalid")
        if self.response_id is not None and response_id != self.response_id:
            raise StreamProtocolError("stream response id changed")
        if self.created is not None and created != self.created:
            raise StreamProtocolError("stream creation time changed")
        self.response_id = response_id
        self.created = created

        for name in ("system_fingerprint", "service_tier"):
            value = getattr(chunk, name, None)
            if value is not None and not isinstance(value, str):
                raise StreamProtocolError(f"stream {name} is invalid")
            previous = getattr(self, name)
            if previous is not None and value is not None and value != previous:
                raise StreamProtocolError(f"stream {name} changed")
            if previous is None and value is not None:
                setattr(self, name, value)

    def _tool_delta(self, call: Any) -> None:
        index = getattr(call, "index", None)
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < 64:
            raise StreamProtocolError("stream tool-call index is invalid")
        target = self.tools.setdefault(
            index,
            {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
        )
        call_type = getattr(call, "type", None)
        if call_type is not None and call_type != "function":
            raise StreamProtocolError("stream tool-call type is unsupported")
        call_id = getattr(call, "id", None)
        if call_id is not None:
            if not isinstance(call_id, str) or not call_id:
                raise StreamProtocolError("stream tool-call id is invalid")
            if target["id"] and target["id"] != call_id:
                raise StreamProtocolError("stream tool-call id changed")
            target["id"] = call_id
        function = getattr(call, "function", None)
        if function is None:
            return
        for name in ("name", "arguments"):
            piece = getattr(function, name, None)
            if piece is not None:
                if not isinstance(piece, str):
                    raise StreamProtocolError(f"stream tool-call {name} is not text")
                target["function"][name] += piece

    def _choice(self, choice: Any) -> None:
        if getattr(choice, "index", None) != 0:
            raise StreamProtocolError("stream choice index is invalid")
        if self.finish_reason is not None:
            raise StreamProtocolError("choice data followed a terminal choice")
        delta = getattr(choice, "delta", None)
        if delta is None:
            raise StreamProtocolError("stream choice delta is absent")
        role = getattr(delta, "role", None)
        if role is not None and role != "assistant":
            raise StreamProtocolError("stream emitted a non-assistant role")
        if getattr(delta, "function_call", None) is not None:
            raise StreamProtocolError("legacy function_call stream is unsupported")
        if getattr(delta, "refusal", None) is not None:
            raise StreamProtocolError("refusal stream is unsupported")
        if getattr(choice, "logprobs", None) is not None:
            raise StreamProtocolError("stream logprobs are unsupported")

        content = getattr(delta, "content", None)
        if content is not None:
            if not isinstance(content, str):
                raise StreamProtocolError("stream content delta is not text")
            self.saw_content = True
            self.saw_answer_text |= bool(content.strip())
            self.content.append(content)
        reasoning = _value(delta, "reasoning")
        reasoning_content = _value(delta, "reasoning_content")
        if reasoning is not None and reasoning_content is not None:
            raise StreamProtocolError("stream has ambiguous reasoning fields")
        reasoning_piece = reasoning if reasoning is not None else reasoning_content
        if reasoning_piece is not None:
            if not isinstance(reasoning_piece, str):
                raise StreamProtocolError("stream reasoning delta is not text")
            self.saw_reasoning = True
            self.reasoning.append(reasoning_piece)

        tool_calls = getattr(delta, "tool_calls", None)
        if tool_calls is not None:
            if not isinstance(tool_calls, list):
                raise StreamProtocolError("stream tool-call collection is invalid")
            for call in tool_calls:
                self._tool_delta(call)

        finish_reason = getattr(choice, "finish_reason", None)
        if finish_reason is not None:
            if finish_reason not in _FINISH_REASONS:
                raise StreamProtocolError("stream finish reason is unsupported")
            self.finish_reason = finish_reason

    def _accept_usage(self, value: Any) -> None:
        if self.usage is not None:
            raise StreamProtocolError("stream usage was repeated")
        if self.finish_reason is None:
            raise StreamProtocolError("stream usage arrived before a terminal choice")
        usage = _as_dict(value)
        for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
            count = usage.get(name)
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                raise StreamProtocolError(f"stream {name} is invalid")
        if usage["total_tokens"] != usage["prompt_tokens"] + usage["completion_tokens"]:
            raise StreamProtocolError("stream token usage is inconsistent")
        self.usage = usage

    def accept(self, chunk: Any) -> None:
        if self.usage is not None:
            raise StreamProtocolError("data followed terminal stream usage")
        self._identity(chunk)
        choices = getattr(chunk, "choices", None)
        if not isinstance(choices, list) or len(choices) > 1:
            raise StreamProtocolError("stream must carry zero or one choice")
        for choice in choices:
            self._choice(choice)
        usage = getattr(chunk, "usage", None)
        if usage is not None:
            self._accept_usage(usage)
        if not choices and usage is None:
            raise StreamProtocolError("empty stream event has no usage")
        self.events += 1

    def tool_calls(self, *, complete: bool) -> list[dict[str, Any]]:
        if complete and self.tools and sorted(self.tools) != list(range(len(self.tools))):
            raise StreamProtocolError("stream tool-call indexes are not contiguous")
        result = [self.tools[index] for index in sorted(self.tools)]
        if complete:
            for call in result:
                if not call["id"] or not call["function"]["name"]:
                    raise StreamProtocolError("stream tool call is incomplete")
        return result

    def trace_fields(self) -> dict[str, Any]:
        return {
            "reasoning_content": "".join(self.reasoning),
            "content": "".join(self.content),
            "tool_calls": self.tool_calls(complete=False),
            "usage": self.usage,
            "finish_reason": self.finish_reason,
        }

    def response(self) -> ChatCompletion:
        if (
            self.events == 0
            or self.response_id is None
            or self.created is None
            or self.finish_reason is None
            or self.usage is None
        ):
            raise StreamProtocolError("stream ended without terminal choice and usage")
        tools = self.tool_calls(complete=True)
        message: dict[str, Any] = {
            "role": "assistant",
            "content": "".join(self.content) if self.saw_content else None,
            "tool_calls": tools or None,
        }
        if self.saw_reasoning:
            message["reasoning_content"] = "".join(self.reasoning)
        payload: dict[str, Any] = {
            "id": self.response_id,
            "choices": [{
                "finish_reason": self.finish_reason,
                "index": 0,
                "message": message,
            }],
            "created": self.created,
            "model": self.expected_model,
            "object": "chat.completion",
            "usage": self.usage,
        }
        if self.system_fingerprint is not None:
            payload["system_fingerprint"] = self.system_fingerprint
        if self.service_tier is not None:
            payload["service_tier"] = self.service_tier
        try:
            return ChatCompletion.model_validate(payload)
        except ValidationError as exc:
            raise StreamProtocolError("reconstructed completion is invalid") from exc


def _request_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    if "stream" in kwargs or "stream_options" in kwargs:
        raise StreamProtocolError("caller-controlled streaming kwargs are unsupported")
    n = kwargs.get("n", 1)
    if n is not None and (isinstance(n, bool) or not isinstance(n, int) or n != 1):
        raise StreamProtocolError("streaming adapter supports exactly one choice")
    if (
        kwargs.get("logprobs") not in (None, False)
        or kwargs.get("top_logprobs") is not None
    ):
        raise StreamProtocolError("streaming adapter does not support requested logprobs")
    return {
        **kwargs,
        "stream": True,
        "stream_options": {"include_usage": True},
    }


def _terminal_status(accumulator: _Accumulator) -> str:
    if accumulator.finish_reason == "stop":
        return "completed" if accumulator.saw_answer_text else "no_final"
    return {
        "tool_calls": "tool_call",
        "length": "exhausted",
        "content_filter": "no_final",
    }.get(accumulator.finish_reason, "parser_error")


def _error_text(exc: BaseException) -> str:
    return str(exc) or type(exc).__name__


def _begin_trace(*, model: str, backend: str, messages: list[Any]) -> Any:
    try:
        return start_trace(
            model=model,
            backend=backend,
            source="local-vllm-backend",
            messages=messages,
        )
    except Exception:  # noqa: BLE001 - tracing cannot block model inference
        return None


class _TracePublisher:
    """Rate-limit before joining accumulated text into a trace snapshot."""

    def __init__(self, trace: Any, *, clock: Callable[[], float] = time.monotonic) -> None:
        self.trace = trace
        self.clock = clock
        # ``start_trace`` has already written the initial empty snapshot.
        self.last_snapshot_at = clock() if trace is not None else 0.0

    def publish(
        self,
        accumulator: _Accumulator,
        *,
        status: str = "streaming",
        error: str | None = None,
        force: bool = False,
    ) -> None:
        if self.trace is None:
            return
        now = self.clock()
        if not force and now - self.last_snapshot_at < WRITE_INTERVAL_S:
            return
        self.last_snapshot_at = now
        try:
            self.trace.update(
                **accumulator.trace_fields(),
                status=status,
                error=error,
                force=force,
            )
        except Exception:  # noqa: BLE001 - telemetry cannot fail inference
            return


def complete_sync(
    client: Any,
    kwargs: dict[str, Any],
    *,
    backend_name: str,
    lease_factory: Callable[[], AbstractContextManager[Any]],
) -> ChatCompletion:
    expected_model = kwargs.get("model")
    messages = kwargs.get("messages")
    if not isinstance(expected_model, str) or not expected_model:
        raise StreamProtocolError("stream request model is absent")
    if not isinstance(messages, list):
        raise StreamProtocolError("stream request messages are invalid")
    trace = _begin_trace(model=expected_model, backend=backend_name, messages=messages)
    accumulator = _Accumulator(expected_model)
    publisher = _TracePublisher(trace)
    try:
        with lease_factory():
            stream = client.chat.completions.create(**_request_kwargs(kwargs))
            primary_error: BaseException | None = None
            try:
                if not isinstance(stream, Iterator):
                    raise StreamProtocolError("sync backend did not return a stream")
                for chunk in stream:
                    accumulator.accept(chunk)
                    publisher.publish(accumulator)
            except BaseException as exc:
                primary_error = exc
                raise
            finally:
                close = getattr(stream, "close", None)
                if callable(close):
                    try:
                        close()
                    except BaseException:
                        if primary_error is None:
                            raise
        response = accumulator.response()
        publisher.publish(
            accumulator,
            status=_terminal_status(accumulator),
            force=True,
        )
        return response
    except StreamProtocolError as exc:
        publisher.publish(
            accumulator, status="parser_error", error=_error_text(exc), force=True,
        )
        raise
    except (KeyboardInterrupt, SystemExit) as exc:
        publisher.publish(
            accumulator, status="interrupted", error=_error_text(exc), force=True,
        )
        raise
    except Exception as exc:
        publisher.publish(
            accumulator, status="transport_error", error=_error_text(exc), force=True,
        )
        raise


async def _close_async(stream: Any) -> None:
    close = getattr(stream, "close", None)
    if not callable(close):
        return
    result = close()
    if inspect.isawaitable(result):
        await result


async def complete_async(
    client: Any,
    kwargs: dict[str, Any],
    *,
    backend_name: str,
    lease_factory: Callable[[], AbstractContextManager[Any]],
) -> ChatCompletion:
    expected_model = kwargs.get("model")
    messages = kwargs.get("messages")
    if not isinstance(expected_model, str) or not expected_model:
        raise StreamProtocolError("stream request model is absent")
    if not isinstance(messages, list):
        raise StreamProtocolError("stream request messages are invalid")
    trace = _begin_trace(model=expected_model, backend=backend_name, messages=messages)
    accumulator = _Accumulator(expected_model)
    publisher = _TracePublisher(trace)
    try:
        with lease_factory():
            stream = await client.chat.completions.create(**_request_kwargs(kwargs))
            primary_error: BaseException | None = None
            try:
                if not isinstance(stream, AsyncIterator):
                    raise StreamProtocolError("async backend did not return a stream")
                async for chunk in stream:
                    accumulator.accept(chunk)
                    publisher.publish(accumulator)
            except BaseException as exc:
                primary_error = exc
                raise
            finally:
                try:
                    await _close_async(stream)
                except BaseException:
                    if primary_error is None:
                        raise
        response = accumulator.response()
        publisher.publish(
            accumulator,
            status=_terminal_status(accumulator),
            force=True,
        )
        return response
    except StreamProtocolError as exc:
        publisher.publish(
            accumulator, status="parser_error", error=_error_text(exc), force=True,
        )
        raise
    except asyncio.CancelledError as exc:
        publisher.publish(
            accumulator, status="interrupted", error=_error_text(exc), force=True,
        )
        raise
    except (KeyboardInterrupt, SystemExit) as exc:
        publisher.publish(
            accumulator, status="interrupted", error=_error_text(exc), force=True,
        )
        raise
    except Exception as exc:
        publisher.publish(
            accumulator, status="transport_error", error=_error_text(exc), force=True,
        )
        raise


__all__ = [
    "StreamProtocolError",
    "complete_async",
    "complete_sync",
    "live_trace_request_supported",
    "live_trace_stream_enabled",
]
