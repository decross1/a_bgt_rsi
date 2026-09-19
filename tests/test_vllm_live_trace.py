"""CPU-only coverage for opt-in local-vLLM live stream reconstruction."""

from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call

import pytest
from openai.types.chat import ChatCompletion, ChatCompletionChunk

from agent_wrapper import wrapper as W
from agent_wrapper.backends import qwen_vllm, vllm_openai
from agent_wrapper.backends.qwen_vllm import VLLMQwenBackend
from agent_wrapper.backends.vllm_openai import VLLMBackend
from agent_wrapper.backends.vllm_streaming import StreamProtocolError
from agent_wrapper.generation_policy import reasoning_text_from_message

MODEL = "gemma-4-26b-a4b"
MESSAGES = [{"role": "user", "content": "Trace this request"}]


def _chunk(*, delta=None, finish=None, usage=None, model=MODEL, response_id="resp-1"):
    choices = [] if delta is None and finish is None else [{
        "index": 0,
        "delta": delta or {},
        "finish_reason": finish,
    }]
    return ChatCompletionChunk.model_validate({
        "id": response_id,
        "choices": choices,
        "created": 1_800_000_000,
        "model": model,
        "object": "chat.completion.chunk",
        "usage": usage,
    })


def _usage(prompt=7, completion=5):
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
        "completion_tokens_details": {"reasoning_tokens": 3},
    }


def _enable(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WRAPPER_LIVE_TRACE_STREAM", "1")
    monkeypatch.setenv("LOCAL_MODEL_TRACE_DIR", str(tmp_path))


def _trace_row(tmp_path: Path):
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    return json.loads(files[0].read_text())


def _lease(events, state):
    @contextmanager
    def hold():
        assert not state["active"]
        state["active"] = True
        events.append("lease-enter")
        try:
            yield
        finally:
            events.append("lease-exit")
            state["active"] = False

    return hold


class SyncStream:
    def __init__(self, rows, state, events):
        self.rows = iter(rows)
        self.state = state
        self.events = events
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        assert self.state["active"]
        row = next(self.rows)
        if isinstance(row, BaseException):
            raise row
        self.events.append("chunk")
        return row

    def close(self):
        assert self.state["active"]
        self.closed = True
        self.events.append("close")


class SyncCompletions:
    def __init__(self, stream, state, events):
        self.stream = stream
        self.state = state
        self.events = events
        self.calls = []

    def create(self, **kwargs):
        assert self.state["active"]
        self.calls.append(kwargs)
        self.events.append("create")
        return self.stream


class SyncCompletionQueue:
    def __init__(self, streams, state, events):
        self.streams = iter(streams)
        self.state = state
        self.events = events
        self.calls = []

    def create(self, **kwargs):
        assert self.state["active"]
        self.calls.append(kwargs)
        self.events.append("create")
        return next(self.streams)


class AsyncStream:
    def __init__(self, rows, state, events, *, block_after=False):
        self.rows = iter(rows)
        self.state = state
        self.events = events
        self.block_after = block_after
        self.waiting = asyncio.Event()
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        assert self.state["active"]
        try:
            row = next(self.rows)
        except StopIteration:
            if not self.block_after:
                raise StopAsyncIteration
            self.waiting.set()
            await asyncio.Future()
            raise AssertionError("unreachable")
        self.events.append("chunk")
        return row

    async def close(self):
        assert self.state["active"]
        self.closed = True
        self.events.append("close")


class AsyncCompletions:
    def __init__(self, stream, state, events):
        self.stream = stream
        self.state = state
        self.events = events
        self.calls = []

    async def create(self, **kwargs):
        assert self.state["active"]
        self.calls.append(kwargs)
        self.events.append("create")
        return self.stream


def test_disabled_path_preserves_exact_request_kwargs(monkeypatch, tmp_path):
    client = MagicMock()
    client.chat.completions.create.side_effect = ["directory-only", "switch-only"]
    monkeypatch.setattr(W, "_sync_client", client)
    monkeypatch.setattr(vllm_openai, "local_inference", _lease([], {"active": False}))
    backend = VLLMBackend()

    monkeypatch.setenv("LOCAL_MODEL_TRACE_DIR", str(tmp_path))
    monkeypatch.delenv("WRAPPER_LIVE_TRACE_STREAM", raising=False)
    assert backend.create_chat(model=MODEL, messages=MESSAGES, max_tokens=9) == "directory-only"

    monkeypatch.delenv("LOCAL_MODEL_TRACE_DIR")
    monkeypatch.setenv("WRAPPER_LIVE_TRACE_STREAM", "1")
    assert backend.create_chat(model=MODEL, messages=MESSAGES, max_tokens=9) == "switch-only"

    assert client.chat.completions.create.call_args_list == [
        call(model=MODEL, messages=MESSAGES, max_tokens=9),
        call(model=MODEL, messages=MESSAGES, max_tokens=9),
    ]
    assert not list(tmp_path.glob("*.json"))


def test_sync_stream_reconstructs_tools_usage_and_holds_lease(
    monkeypatch, tmp_path,
):
    _enable(monkeypatch, tmp_path)
    state = {"active": False}
    events = []
    rows = [
        _chunk(delta={"role": "assistant", "reasoning_content": "check "}),
        _chunk(delta={"reasoning_content": "premise", "content": "calling"}),
        _chunk(delta={"tool_calls": [{
            "index": 0,
            "id": "call-1",
            "type": "function",
            "function": {"name": "lookup", "arguments": '{"q":'},
        }]}),
        _chunk(delta={"tool_calls": [{
            "index": 0,
            "function": {"arguments": "1}"},
        }]}),
        _chunk(delta={}, finish="tool_calls"),
        _chunk(usage=_usage()),
    ]
    stream = SyncStream(rows, state, events)
    completions = SyncCompletions(stream, state, events)
    monkeypatch.setattr(
        W,
        "_sync_client",
        SimpleNamespace(chat=SimpleNamespace(completions=completions)),
    )
    monkeypatch.setattr(vllm_openai, "local_inference", _lease(events, state))

    response = VLLMBackend().create_chat(
        model=MODEL,
        messages=MESSAGES,
        max_tokens=32,
        temperature=0.2,
    )

    assert isinstance(response, ChatCompletion)
    assert response.model == MODEL
    assert response.choices[0].finish_reason == "tool_calls"
    assert response.choices[0].message.content == "calling"
    assert reasoning_text_from_message(response.choices[0].message) == "check premise"
    tool = response.choices[0].message.tool_calls[0]
    assert (tool.id, tool.function.name, tool.function.arguments) == (
        "call-1", "lookup", '{"q":1}',
    )
    assert response.usage.prompt_tokens == 7
    assert response.usage.completion_tokens_details.reasoning_tokens == 3
    assert completions.calls == [{
        "model": MODEL,
        "messages": MESSAGES,
        "max_tokens": 32,
        "temperature": 0.2,
        "stream": True,
        "stream_options": {"include_usage": True},
    }]
    assert stream.closed
    assert events[0:2] == ["lease-enter", "create"]
    assert events[-2:] == ["close", "lease-exit"]
    assert not state["active"]

    trace = _trace_row(tmp_path)
    assert trace["source"] == "local-vllm-backend"
    assert trace["backend"] == "vllm-gemma"
    assert trace["status"] == "tool_call"
    assert trace["reasoning_content"] == "check premise"
    assert trace["content"] == "calling"
    assert trace["tool_calls"][0]["function"]["arguments"] == '{"q":1}'
    assert trace["usage"]["completion_tokens_details"]["reasoning_tokens"] == 3


def test_async_wrapper_receives_existing_record_contract(monkeypatch, tmp_path):
    _enable(monkeypatch, tmp_path)
    state = {"active": False}
    events = []
    stream = AsyncStream([
        _chunk(delta={"role": "assistant", "reasoning_content": "think"}),
        _chunk(delta={"content": "answer"}),
        _chunk(delta={}, finish="stop"),
        _chunk(usage=_usage(prompt=4, completion=2)),
    ], state, events)
    completions = AsyncCompletions(stream, state, events)
    monkeypatch.setattr(
        W,
        "_async_client",
        SimpleNamespace(chat=SimpleNamespace(completions=completions)),
    )
    monkeypatch.setattr(vllm_openai, "local_inference", _lease(events, state))

    record = asyncio.run(W.call_async(
        MESSAGES,
        model=MODEL,
        profile="scientist",
        max_tokens=16,
        log_path=None,
    ))

    assert record["model"] == MODEL
    assert record["completion"] == "answer"
    assert record["usage"] == {"input_tokens": 4, "output_tokens": 2}
    assert record["reasoning_chars"] == 5
    assert record["finish_reason"] == "stop"
    assert stream.closed
    assert events[-2:] == ["close", "lease-exit"]
    assert _trace_row(tmp_path)["status"] == "completed"


def test_tool_loop_receives_reconstructed_turns(monkeypatch, tmp_path):
    _enable(monkeypatch, tmp_path)
    state = {"active": False}
    events = []
    first = SyncStream([
        _chunk(delta={"tool_calls": [{
            "index": 0,
            "id": "call-1",
            "type": "function",
            "function": {"name": "identity", "arguments": '{"value":2}'},
        }]}),
        _chunk(delta={}, finish="tool_calls"),
        _chunk(usage=_usage(prompt=3, completion=2)),
    ], state, events)
    second = SyncStream([
        _chunk(delta={"content": "done"}, response_id="resp-2"),
        _chunk(delta={}, finish="stop", response_id="resp-2"),
        _chunk(usage=_usage(prompt=6, completion=1), response_id="resp-2"),
    ], state, events)
    completions = SyncCompletionQueue([first, second], state, events)
    monkeypatch.setattr(
        W,
        "_sync_client",
        SimpleNamespace(chat=SimpleNamespace(completions=completions)),
    )
    monkeypatch.setattr(vllm_openai, "local_inference", _lease(events, state))
    observed = []
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
        "impl": lambda value: observed.append(value) or {"value": value},
    }]

    records = W.call_with_tools(
        MESSAGES,
        tools,
        model=MODEL,
        max_depth=1,
        log_path=None,
    )

    assert observed == [2]
    assert len(records) == 2
    assert json.loads(records[0]["completion"])[0]["function"] == {
        "name": "identity", "arguments": '{"value":2}',
    }
    assert records[1]["completion"] == "done"
    assert first.closed and second.closed and not state["active"]
    traces = [json.loads(item.read_text()) for item in tmp_path.glob("*.json")]
    assert sorted(row["status"] for row in traces) == ["completed", "tool_call"]


def test_async_cancellation_closes_stream_before_releasing_lease(
    monkeypatch, tmp_path,
):
    _enable(monkeypatch, tmp_path)
    state = {"active": False}
    events = []
    stream = AsyncStream([
        _chunk(delta={"role": "assistant", "reasoning_content": "partial"}),
    ], state, events, block_after=True)
    completions = AsyncCompletions(stream, state, events)
    monkeypatch.setattr(
        W,
        "_async_client",
        SimpleNamespace(chat=SimpleNamespace(completions=completions)),
    )
    monkeypatch.setattr(vllm_openai, "local_inference", _lease(events, state))

    async def scenario():
        task = asyncio.create_task(VLLMBackend().create_chat_async(
            model=MODEL, messages=MESSAGES, max_tokens=16))
        await stream.waiting.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())

    assert stream.closed
    assert events[-2:] == ["close", "lease-exit"]
    assert not state["active"]
    trace = _trace_row(tmp_path)
    assert trace["status"] == "interrupted"
    assert trace["reasoning_content"] == "partial"
    assert trace["error"] == "CancelledError"


def test_incomplete_stream_is_parser_error_not_success(monkeypatch, tmp_path):
    _enable(monkeypatch, tmp_path)
    state = {"active": False}
    events = []
    stream = SyncStream([
        _chunk(delta={"content": "incomplete"}),
        _chunk(delta={}, finish="stop"),
    ], state, events)
    completions = SyncCompletions(stream, state, events)
    monkeypatch.setattr(
        W,
        "_sync_client",
        SimpleNamespace(chat=SimpleNamespace(completions=completions)),
    )
    monkeypatch.setattr(vllm_openai, "local_inference", _lease(events, state))

    with pytest.raises(StreamProtocolError, match="terminal choice and usage"):
        VLLMBackend().create_chat(model=MODEL, messages=MESSAGES)

    assert stream.closed and not state["active"]
    trace = _trace_row(tmp_path)
    assert trace["status"] == "parser_error"
    assert "terminal choice and usage" in trace["error"]


def test_transport_failure_is_terminal_and_reraised(monkeypatch, tmp_path):
    _enable(monkeypatch, tmp_path)
    state = {"active": False}
    events = []
    stream = SyncStream([
        _chunk(delta={"reasoning_content": "partial"}),
        OSError("connection reset"),
    ], state, events)
    completions = SyncCompletions(stream, state, events)
    monkeypatch.setattr(
        W,
        "_sync_client",
        SimpleNamespace(chat=SimpleNamespace(completions=completions)),
    )
    monkeypatch.setattr(vllm_openai, "local_inference", _lease(events, state))

    with pytest.raises(OSError, match="connection reset"):
        VLLMBackend().create_chat(model=MODEL, messages=MESSAGES)

    assert _trace_row(tmp_path)["status"] == "transport_error"
    assert stream.closed and events[-2:] == ["close", "lease-exit"]


def test_qwen_backend_uses_same_opt_in_adapter(monkeypatch, tmp_path):
    _enable(monkeypatch, tmp_path)
    model = "qwen3.8-27b-nvfp4-mtp"
    state = {"active": False}
    events = []
    stream = SyncStream([
        _chunk(delta={"content": "qwen"}, model=model),
        _chunk(delta={}, finish="stop", model=model),
        _chunk(usage=_usage(prompt=2, completion=1), model=model),
    ], state, events)
    completions = SyncCompletions(stream, state, events)
    backend = VLLMQwenBackend()
    backend._sync = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    monkeypatch.setattr(qwen_vllm, "local_inference", _lease(events, state))

    response = backend.create_chat(model=model, messages=MESSAGES)

    assert response.choices[0].message.content == "qwen"
    trace = _trace_row(tmp_path)
    assert trace["backend"] == "vllm-qwen"
    assert trace["model"] == model
