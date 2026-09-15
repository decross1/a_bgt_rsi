"""Model identity, separated channels, termination and explicit policy checks."""
import hashlib
import json
import threading
import time
from itertools import pairwise

import pytest

from bench.flash_next_ab import transport
from bench.flash_next_ab.transport import (
    LocalEndpoint,
    StreamAccumulator,
    TransportCancelled,
    TransportError,
    complete,
    request_body,
)


def endpoint(name="flash_next"):
    options = {
        "flash_next": (8012, "qwen3.8-flash-next"),
        "resident_gemma": (8000, "gemma-4-26b-a4b"),
    }
    port, model = options[name]
    return LocalEndpoint(name, f"http://127.0.0.1:{port}/v1", model, "a" * 64)


def frame(delta=None, finish=None, **overrides):
    return json.dumps({
        "id": "request1", "model": "qwen3.8-flash-next",
        "choices": [{"index": 0, "delta": delta or {}, "finish_reason": finish}],
        **overrides,
    })


def terminate(stream):
    stream.accept(json.dumps({
        "id": "request1", "model": "qwen3.8-flash-next", "choices": [],
        "usage": {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18},
    }))
    stream.accept("[DONE]")


def test_reasoning_is_not_salvaged_into_an_empty_final_answer():
    stream = StreamAccumulator("qwen3.8-flash-next")
    stream.accept(frame({"reasoning_content": '{"answer": 4}'}))
    stream.accept(frame(finish="length"))
    terminate(stream)
    result = stream.result()
    assert result["content"] == ""
    assert result["reasoning_content"] == '{"answer": 4}'
    assert result["finish_reason"] == "length"


def test_fragmented_tool_arguments_stay_exact_and_separate_from_content():
    stream = StreamAccumulator("qwen3.8-flash-next")
    stream.accept(frame({"tool_calls": [{"index": 0, "id": "tool1", "function": {
        "name": "lookup", "arguments": '{"x":',
    }}]}))
    stream.accept(frame({"tool_calls": [{"index": 0, "function": {"arguments": "2}"}}]}))
    stream.accept(frame(finish="tool_calls"))
    terminate(stream)
    assert stream.result()["tool_calls"] == [{
        "id": "tool1", "type": "function", "function": {"name": "lookup", "arguments": '{"x":2}'},
    }]
    assert stream.result()["content"] == ""


@pytest.mark.parametrize("bad", [
    {"model": "qwen3.8-27b-nvfp4-mtp"},
    {"id": "other-request"},
    {"choices": [{"index": 1, "delta": {}}]},
    {"error": {"message": "failure"}},
    {"usage": {"prompt_tokens": True, "completion_tokens": 8, "total_tokens": 18}},
])
def test_identity_or_protocol_drift_rejected(bad):
    stream = StreamAccumulator("qwen3.8-flash-next")
    stream.accept(frame())
    with pytest.raises(TransportError):
        stream.accept(frame(**bad))


@pytest.mark.parametrize("missing", ["finish", "done", "usage"])
def test_truncated_stream_cannot_be_a_success(missing):
    stream = StreamAccumulator("qwen3.8-flash-next")
    stream.accept(frame({"content": "4"}, finish=None if missing == "finish" else "stop"))
    with pytest.raises(TransportError):
        if missing == "usage":
            stream.accept("[DONE]")
        elif missing != "done":
            terminate(stream)
        stream.result()


@pytest.mark.parametrize("url", [
    "http://example.com:8012/v1", "http://127.0.0.1:8001/v1",
    "http://user:secret@127.0.0.1:8012/v1", "http://127.0.0.1:8012/v1?override=true",
])
def test_endpoint_cannot_redirect_to_cloud_or_impersonate_incumbent(url):
    with pytest.raises(ValueError):
        LocalEndpoint("flash_next", url, "qwen3.8-flash-next", "a" * 64).validate()


def test_thinking_effort_sampling_and_output_budget_explicit():
    body = request_body(endpoint(), [{"role": "user", "content": "solve"}], {
        "temperature": 1.0, "top_p": 0.95, "top_k": 20,
        "reasoning_effort": "medium", "enable_thinking": True,
    }, 512, 17)
    assert body["model"] == "qwen3.8-flash-next"
    assert body["max_tokens"] == 512
    assert body["chat_template_kwargs"] == {"reasoning_effort": "medium", "enable_thinking": True}
    assert body["temperature"] == 1.0
    assert body["stream_options"] == {"include_usage": True}


def test_gemma_cannot_silently_inherit_qwen_effort():
    with pytest.raises(ValueError, match="unsupported"):
        request_body(endpoint("resident_gemma"), [{"role": "user", "content": "solve"}], {
            "temperature": 0, "top_p": 1, "reasoning_effort": "medium",
        }, 128, 17)


@pytest.mark.parametrize("bad", [
    '{"id":"request1","model":"wrong","model":"qwen3.8-flash-next","choices":[]}',
    '{"id":"request1","model":"qwen3.8-flash-next","choices":[],"usage":{"prompt_tokens":NaN}}',
])
def test_streaming_json_is_strict(bad):
    with pytest.raises(TransportError, match="malformed streaming JSON"):
        StreamAccumulator("qwen3.8-flash-next").accept(bad)


@pytest.mark.parametrize("missing", ["model", "id"])
def test_every_stream_event_carries_exact_response_identity(missing):
    stream = StreamAccumulator("qwen3.8-flash-next")
    stream.accept(frame({"content": "first"}))
    event = {
        "id": "request1",
        "model": "qwen3.8-flash-next",
        "choices": [{"index": 0, "delta": {"content": "second"}, "finish_reason": None}],
    }
    event.pop(missing)
    with pytest.raises(TransportError, match="identity|identifier"):
        stream.accept(json.dumps(event))


def test_usage_cannot_precede_finish_repeat_or_disagree():
    usage = {
        "id": "request1", "model": "qwen3.8-flash-next", "choices": [],
        "usage": {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18},
    }
    with pytest.raises(TransportError, match="token usage"):
        StreamAccumulator("qwen3.8-flash-next").accept(json.dumps(usage))

    stream = StreamAccumulator("qwen3.8-flash-next")
    stream.accept(frame(finish="stop"))
    inconsistent = json.loads(json.dumps(usage))
    inconsistent["usage"]["total_tokens"] = 19
    with pytest.raises(TransportError, match="inconsistent"):
        stream.accept(json.dumps(inconsistent))

    stream.accept(json.dumps(usage))
    with pytest.raises(TransportError, match="repeated"):
        stream.accept(json.dumps(usage))


def test_choice_data_after_finish_is_rejected():
    stream = StreamAccumulator("qwen3.8-flash-next")
    stream.accept(frame(finish="stop"))
    with pytest.raises(TransportError, match="after terminal"):
        stream.accept(frame({"content": "late"}))


@pytest.mark.parametrize("tool_calls", [
    {"index": 0, "function": {}},
    [{"index": 0, "type": "computer", "function": {}}],
    [{"index": 0, "id": 7, "function": {}}],
])
def test_malformed_tool_delta_is_a_transport_error(tool_calls):
    stream = StreamAccumulator("qwen3.8-flash-next")
    with pytest.raises(TransportError, match="tool"):
        stream.accept(frame({"tool_calls": tool_calls}))


class FakeSocket:
    def __init__(self):
        self.timeouts = []
        self.shutdown_called = threading.Event()

    def settimeout(self, value):
        self.timeouts.append(value)

    def shutdown(self, _how):
        self.shutdown_called.set()


class FakeResponse:
    def __init__(self, chunks, *, content_type="text/event-stream; charset=utf-8"):
        self.status = 200
        self._chunks = iter(chunks)
        self.content_type = content_type

    def getheader(self, name, default=None):
        return self.content_type if name.lower() == "content-type" else default

    def read1(self, _size):
        return next(self._chunks, b"")


class FakeConnection:
    def __init__(self, response, timeout):
        self.sock = FakeSocket()
        self.response = response
        self.initial_timeout = timeout
        self.request_timeout = None
        self.closed = False

    def connect(self):
        return None

    def request(self, _method, _path, *, body, headers):
        self.request_timeout = self.sock.timeouts[-1]
        self.body = body
        self.headers = headers

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


def stream_bytes(*, data_prefix=b"data:"):
    chunks = [
        data_prefix + frame({"content": "ok"}).encode() + b"\n\n",
        data_prefix + frame(finish="stop").encode() + b"\n\n",
        data_prefix + json.dumps({
            "id": "request1", "model": "qwen3.8-flash-next", "choices": [],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }).encode() + b"\n\n",
        data_prefix + b"[DONE]\n\n",
    ]
    return chunks


def install_connection(monkeypatch, response, *, clock=None):
    holder = {}

    def factory(_host, _port, timeout):
        connection = FakeConnection(response, timeout)
        holder["connection"] = connection
        return connection

    monkeypatch.setattr(transport.http.client, "HTTPConnection", factory)
    monkeypatch.delenv("MOCK_LLM", raising=False)
    if clock is not None:
        monkeypatch.setattr(transport.time, "monotonic", clock)
    return holder


def invoke(**kwargs):
    return complete(
        endpoint(),
        [{"role": "user", "content": "solve"}],
        policy={"temperature": 0, "top_p": 1},
        max_tokens=32,
        timeout_s=kwargs.pop("timeout_s", 2),
        seed=17,
        **kwargs,
    )


def test_complete_accepts_sse_data_without_optional_space(monkeypatch):
    response = FakeResponse(stream_bytes(data_prefix=b"data:"))
    holder = install_connection(monkeypatch, response)
    result = invoke()
    assert result["content"] == "ok"
    assert result["response_id"] == "request1"
    assert holder["connection"].closed is True


def test_content_type_is_an_exact_media_type(monkeypatch):
    response = FakeResponse(
        stream_bytes(), content_type="application/not-text/event-stream-backup",
    )
    install_connection(monkeypatch, response)
    with pytest.raises(TransportError, match="streaming response"):
        invoke()


def test_buffered_bytes_after_done_are_rejected(monkeypatch):
    response = FakeResponse([b"".join(stream_bytes()) + b"private trailing bytes"])
    install_connection(monkeypatch, response)
    with pytest.raises(TransportError, match="after terminal"):
        invoke()


def test_malformed_stream_retains_bounded_private_partial_evidence(monkeypatch):
    chunks = [
        b"data: " + frame({"content": "partial-output"}).encode() + b"\n\n",
        b"data: {malformed-json}\n\n",
    ]
    install_connection(monkeypatch, FakeResponse(chunks))
    with pytest.raises(TransportError, match="malformed") as caught:
        invoke()
    evidence = caught.value.private_evidence
    assert evidence["content"] == "partial-output"
    assert evidence["reasoning_content"] == ""
    assert evidence["raw_response_stream"] == b"".join(chunks)
    assert evidence["response_stream_sha256"] == hashlib.sha256(b"".join(chunks)).hexdigest()


def test_absolute_deadline_is_reapplied_before_every_blocking_phase(monkeypatch):
    ticks = iter(i / 10 for i in range(30))
    response = FakeResponse(stream_bytes())
    holder = install_connection(monkeypatch, response, clock=lambda: next(ticks))
    invoke(timeout_s=2)
    connection = holder["connection"]
    observed = [connection.initial_timeout, *connection.sock.timeouts]
    assert all(later < earlier for earlier, later in pairwise(observed))
    assert connection.request_timeout < connection.initial_timeout


def test_socket_timeout_is_normalized_and_connection_closed(monkeypatch):
    class TimedOutResponse(FakeResponse):
        def read1(self, _size):
            raise TimeoutError("socket stalled")

    holder = install_connection(monkeypatch, TimedOutResponse([]))
    with pytest.raises(TimeoutError, match="wall-clock deadline"):
        invoke(timeout_s=1)
    assert holder["connection"].closed is True


def test_inflight_cancellation_interrupts_read_and_closes(monkeypatch):
    read_started = threading.Event()

    class BlockingResponse(FakeResponse):
        def __init__(self):
            super().__init__([])
            self.sock = None

        def read1(self, _size):
            read_started.set()
            assert self.sock.shutdown_called.wait(1)
            raise OSError("socket closed by cancellation")

    response = BlockingResponse()
    holder = install_connection(monkeypatch, response)
    cancel = threading.Event()

    def cancel_after_read_starts():
        assert read_started.wait(1)
        cancel.set()

    setter = threading.Thread(target=cancel_after_read_starts)
    setter.start()
    start = time.monotonic()
    try:
        # Attach the fake socket after construction but before read1 executes.
        original_getresponse = FakeConnection.getresponse

        def getresponse(connection):
            response.sock = connection.sock
            return original_getresponse(connection)

        monkeypatch.setattr(FakeConnection, "getresponse", getresponse)
        with pytest.raises(TransportCancelled, match="canceled"):
            invoke(cancel_event=cancel, timeout_s=2)
    finally:
        setter.join(timeout=1)
    assert time.monotonic() - start < 1
    assert holder["connection"].sock.shutdown_called.is_set()
    assert holder["connection"].closed is True
