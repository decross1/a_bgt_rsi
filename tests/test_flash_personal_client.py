import dataclasses
import json

import pytest

from bench.flash_next_ab import personal_client
from bench.flash_next_ab.followon_profiles import MIA_MTP3_REDUCED47K_OPT
from bench.flash_next_ab.personal_client import (
    TimedAccumulator,
    TurnResult,
    build_request,
    endpoint_for_candidate,
    run_tool_loop,
    stream_chat,
)
from bench.flash_next_ab.personal_tasks import FILESYSTEM_TOOLS, get_policy

MODEL = "qwen3.8-flash-next-mia"


class Clock:
    def __init__(self, value=100.0):
        self.value = value

    def __call__(self):
        return self.value


def frame(*, delta=None, finish=None, choices=None, usage=None):
    row = {
        "id": "personal-response-1",
        "model": MODEL,
        "choices": choices if choices is not None else [{
            "index": 0,
            "delta": delta or {},
            "finish_reason": finish,
        }],
    }
    if usage is not None:
        row["usage"] = usage
    return json.dumps(row, separators=(",", ":"))


def usage_frame(prompt=10, completion=5):
    return frame(
        choices=[],
        usage={
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
            "completion_tokens_details": {"reasoning_tokens": 3},
        },
    )


class FakeSocket:
    def __init__(self):
        self.timeouts = []

    def settimeout(self, value):
        self.timeouts.append(value)


class FakeResponse:
    def __init__(self, chunks, *, status=200, content_type="text/event-stream"):
        self.status = status
        self.chunks = iter(chunks)
        self.content_type = content_type

    def getheader(self, name, default=None):
        return self.content_type if name.lower() == "content-type" else default

    def read1(self, _size):
        return next(self.chunks, b"")


class FakeConnection:
    def __init__(self, response, *, fail_connect=False):
        self.response = response
        self.fail_connect = fail_connect
        self.sock = FakeSocket()
        self.closed = False
        self.request_body = None

    def connect(self):
        if self.fail_connect:
            raise OSError("connection refused")

    def request(self, _method, _path, *, body, headers):
        self.request_body = body
        self.headers = headers

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


def connection_factory(connection):
    def make(_host, _port, timeout):
        connection.initial_timeout = timeout
        return connection
    return make


def test_optional_live_trace_does_not_change_wire_or_raw_stream(tmp_path, monkeypatch):
    chunks = sse(frame(delta={"reasoning_content": "Check the premise."}),
                 frame(delta={"content": "The answer."}, finish="stop"),
                 usage_frame(), "[DONE]")
    policy = get_policy("off")
    messages = [{"role": "user", "content": "Question"}]
    monkeypatch.delenv("LOCAL_MODEL_TRACE_DIR", raising=False)
    plain = stream_chat(MIA_MTP3_REDUCED47K_OPT, messages, policy, seed=7,
                        connection_factory=connection_factory(FakeConnection(FakeResponse(chunks))))
    monkeypatch.setenv("LOCAL_MODEL_TRACE_DIR", str(tmp_path))
    observed = stream_chat(MIA_MTP3_REDUCED47K_OPT, messages, policy, seed=7,
                           connection_factory=connection_factory(FakeConnection(FakeResponse(chunks))))
    assert observed.request_bytes == plain.request_bytes
    assert observed.response_bytes == plain.response_bytes
    assert observed.classification == plain.classification == "completed"
    rows = list(tmp_path.glob("*.json"))
    assert len(rows) == 1
    row = json.loads(rows[0].read_text())
    assert row["status"] == "completed" and row["model"] == MODEL
    assert row["reasoning_content"] == "Check the premise."
    assert row["content"] == "The answer."


def test_live_trace_transport_failure_is_terminal(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_MODEL_TRACE_DIR", str(tmp_path))
    result = stream_chat(MIA_MTP3_REDUCED47K_OPT, [{"role": "user", "content": "Q"}],
                         get_policy("off"), seed=0,
                         connection_factory=connection_factory(
                             FakeConnection(FakeResponse([]), fail_connect=True)))
    row = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert row["status"] == result.classification == "transport_error"
    assert row["error"] == "connection refused"


def test_live_reasoning_is_visible_before_final_answer(tmp_path, monkeypatch):
    from agent_wrapper import live_trace

    monkeypatch.setenv("LOCAL_MODEL_TRACE_DIR", str(tmp_path))
    ticks = iter(range(100))
    monkeypatch.setattr(live_trace.time, "monotonic", lambda: float(next(ticks)))
    chunks = sse(frame(delta={"reasoning_content": "First step"}),
                 frame(delta={"content": "Answer"}, finish="stop"),
                 usage_frame(), "[DONE]")

    class ObservedResponse(FakeResponse):
        reads = 0

        def read1(self, size):
            if self.reads == 1:
                row = json.loads(next(tmp_path.glob("*.json")).read_text())
                assert row["status"] == "streaming"
                assert row["reasoning_content"] == "First step"
                assert row["content"] == ""
            self.reads += 1
            return super().read1(size)

    response = ObservedResponse(chunks)
    result = stream_chat(MIA_MTP3_REDUCED47K_OPT, [{"role": "user", "content": "Q"}],
                         get_policy("off"), seed=0, clock=Clock(),
                         connection_factory=connection_factory(FakeConnection(response)))
    assert result.classification == "completed" and response.reads >= 2


def sse(*rows):
    return [("data: " + row + "\n\n").encode() for row in rows]


def turn(
    classification,
    *,
    content="",
    reasoning="",
    tools=(),
    finish="stop",
):
    return TurnResult(
        classification=classification,
        content=content,
        reasoning_content=reasoning,
        tool_calls=tuple(tools),
        usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        finish_reason=finish,
        response_id="r1",
        response_model=MODEL,
        timing={"first_channel": "reasoning_first"},
        elapsed_s=0.1,
        request_body={},
        request_bytes=b"{}",
        response_bytes=b"data",
    )


def test_endpoint_comes_from_registered_candidate_identity_only():
    endpoint = endpoint_for_candidate(MIA_MTP3_REDUCED47K_OPT)
    assert endpoint.base_url == "http://127.0.0.1:8012/v1"
    assert endpoint.served_model == MODEL
    with pytest.raises(ValueError, match="registered"):
        endpoint_for_candidate(dataclasses.replace(MIA_MTP3_REDUCED47K_OPT))


def test_sglang_endpoint_uses_registered_nvidia_manifest_and_fixed_port():
    from bench.flash_next_ab.qualification import model_artifact_sha256

    target = personal_client.SGLANG_ENDPOINT
    assert endpoint_for_candidate(target) is target
    assert target.validate() == 30080
    assert target.artifact_sha256 == model_artifact_sha256()
    with pytest.raises(ValueError, match="registered"):
        endpoint_for_candidate(dataclasses.replace(target))
    with pytest.raises(ValueError, match="NVIDIA checkpoint"):
        dataclasses.replace(target, artifact_sha256="a" * 64).validate()


def test_sglang_stream_preserves_reasoning_and_final_without_mia_identity():
    target = personal_client.SGLANG_ENDPOINT
    chunks = [chunk.replace(MODEL.encode(), target.served_model.encode()) for chunk in sse(
        frame(delta={"reasoning_content": "Check the game."}),
        frame(delta={"content": "Two equilibria."}, finish="stop"),
        usage_frame(), "[DONE]",
    )]
    connection = FakeConnection(FakeResponse(chunks))
    result = stream_chat(
        target, [{"role": "user", "content": "Analyze this game."}],
        get_policy("medium"), seed=17, connection_factory=connection_factory(connection),
    )
    assert result.classification == "completed"
    assert result.response_model == target.served_model
    assert result.reasoning_content == "Check the game."
    assert result.content == "Two equilibria."
    body = json.loads(connection.request_body)
    assert body["model"] == target.served_model
    assert body["chat_template_kwargs"] == {"enable_thinking": True, "reasoning_effort": "medium"}


def test_sglang_cli_does_not_claim_a_mia_runtime_spec(monkeypatch, tmp_path):
    def fake_stream(target, *_args, **_kwargs):
        assert target is personal_client.SGLANG_ENDPOINT
        return dataclasses.replace(turn("completed", content="answer"), response_model=target.served_model)

    monkeypatch.setattr(personal_client, "stream_chat", fake_stream)
    assert personal_client.main([
        "--backend", "sglang", "--prompt", "hello", "--policy", "off",
        "--output-dir", str(tmp_path / "sglang"),
    ]) == 0
    summary = json.loads((tmp_path / "sglang/summary.json").read_text())
    assert summary["requested_candidate_spec_id"] is None
    assert summary["requested_backend"] == "sglang"
    assert summary["requested_model"] == personal_client.SGLANG_ENDPOINT.served_model
    assert summary["runtime_profile_verified"] is False


@pytest.mark.parametrize(
    ("policy_id", "expected"),
    [
        ("off", {
            "temperature": 0.7, "top_p": 0.8, "top_k": 20,
            "chat_template_kwargs": {"enable_thinking": False},
            "max_tokens": 8192,
        }),
        ("medium", {
            "temperature": 1.0, "top_p": 0.95, "top_k": 20,
            "reasoning_effort": "medium",
            "chat_template_kwargs": {
                "enable_thinking": True, "reasoning_effort": "medium",
            },
            "max_tokens": 16384,
        }),
    ],
)
def test_request_policies_are_explicit(policy_id, expected):
    _, body, raw = build_request(
        MIA_MTP3_REDUCED47K_OPT,
        [{"role": "user", "content": "calculate"}],
        get_policy(policy_id),
        seed=17,
    )
    assert json.loads(raw) == body
    for key, value in expected.items():
        assert body[key] == value
    assert body["stream_options"] == {"include_usage": True}


def test_logprobs_are_optional_and_bounded():
    _, body, _ = build_request(
        MIA_MTP3_REDUCED47K_OPT,
        [{"role": "user", "content": "x"}],
        get_policy("off"),
        seed=2,
        logprobs=True,
        top_logprobs=5,
    )
    assert body["logprobs"] is True
    assert body["top_logprobs"] == 5
    with pytest.raises(ValueError, match="requires"):
        build_request(
            MIA_MTP3_REDUCED47K_OPT,
            [{"role": "user", "content": "x"}],
            get_policy("off"),
            seed=2,
            top_logprobs=2,
        )


def test_accumulator_records_first_response_reasoning_final_and_usage():
    clock = Clock()
    accumulator = TimedAccumulator(MODEL, started=clock(), clock=clock)
    clock.value = 100.2
    accumulator.accept(frame(delta={"role": "assistant"}))
    clock.value = 100.4
    accumulator.accept(frame(delta={"reasoning_content": "work"}))
    clock.value = 100.8
    accumulator.accept(frame(delta={"content": "answer"}))
    clock.value = 100.9
    accumulator.accept(frame(finish="stop"))
    accumulator.accept(usage_frame())
    accumulator.accept("[DONE]")
    result = accumulator.result()
    timing = accumulator.timing()
    assert result["reasoning_content"] == "work"
    assert result["content"] == "answer"
    assert result["usage"]["completion_tokens"] == 5
    assert timing["first_response_s"] == pytest.approx(0.2)
    assert timing["first_reasoning_s"] == pytest.approx(0.4)
    assert timing["first_final_s"] == pytest.approx(0.8)
    assert timing["ttft_s"] == pytest.approx(0.4)
    assert timing["first_channel"] == "reasoning_first"


def test_stream_chat_captures_raw_sse_and_proper_token_counts():
    chunks = sse(
        frame(delta={"reasoning_content": "think"}),
        frame(delta={"content": "final"}),
        frame(finish="stop"),
        usage_frame(11, 7),
        "[DONE]",
    )
    response = FakeResponse(chunks)
    connection = FakeConnection(response)
    result = stream_chat(
        MIA_MTP3_REDUCED47K_OPT,
        [{"role": "user", "content": "solve"}],
        get_policy("medium"),
        seed=17,
        connection_factory=connection_factory(connection),
    )
    assert result.classification == "completed"
    assert result.content == "final"
    assert result.reasoning_content == "think"
    assert result.usage["prompt_tokens"] == 11
    assert result.receipt()["reasoning_tokens"] == 3
    assert result.timing["first_channel"] == "reasoning_first"
    assert result.response_bytes == b"".join(chunks)
    assert connection.request_body == result.request_bytes
    assert connection.closed is True


@pytest.mark.parametrize("usage,expected", [
    ({"completion_tokens": 8, "reasoning_tokens": 5}, 5),
    ({"completion_tokens": 8, "reasoning_tokens": 0}, 0),
    ({"reasoning_tokens": 5, "completion_tokens_details": {"reasoning_tokens": 0}}, 0),
    ({"reasoning_tokens": 5, "completion_tokens_details": None}, 5),
    ({"completion_tokens": 8}, None),
])
def test_receipt_preserves_runtime_reasoning_usage(usage, expected):
    usage = {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18, **usage}
    chunks = sse(frame(delta={"content": "answer"}, finish="stop"),
                 frame(choices=[], usage=usage), "[DONE]")
    result = stream_chat(
        MIA_MTP3_REDUCED47K_OPT, [{"role": "user", "content": "Q"}],
        get_policy("off"), seed=17,
        connection_factory=connection_factory(FakeConnection(FakeResponse(chunks))),
    )
    assert result.receipt()["reasoning_tokens"] == expected
    assert result.receipt()["usage"] == usage


def test_final_first_and_length_exhaustion_are_not_hidden_by_content():
    chunks = sse(
        frame(delta={"content": "partial answer"}),
        frame(delta={"reasoning_content": "late reasoning"}),
        frame(finish="length"),
        usage_frame(),
        "[DONE]",
    )
    result = stream_chat(
        MIA_MTP3_REDUCED47K_OPT,
        [{"role": "user", "content": "solve"}],
        get_policy("medium"),
        seed=17,
        connection_factory=connection_factory(FakeConnection(FakeResponse(chunks))),
    )
    assert result.classification == "exhausted"
    assert result.finish_reason == "length"
    assert result.content == "partial answer"
    assert result.timing["first_channel"] == "final_first"


def test_streamed_tool_fragments_keep_reasoning_and_exact_arguments():
    chunks = sse(
        frame(delta={"reasoning_content": "inspect first"}),
        frame(delta={"tool_calls": [{
            "index": 0, "id": "call-7", "type": "function",
            "function": {"name": "read_file", "arguments": '{"path":'},
        }]}),
        frame(delta={"tool_calls": [{
            "index": 0, "function": {"arguments": '"orders.py"}'},
        }]}),
        frame(finish="tool_calls"),
        usage_frame(),
        "[DONE]",
    )
    result = stream_chat(
        MIA_MTP3_REDUCED47K_OPT,
        [{"role": "user", "content": "repair"}],
        get_policy("medium"),
        seed=17,
        tools=list(FILESYSTEM_TOOLS),
        connection_factory=connection_factory(FakeConnection(FakeResponse(chunks))),
    )
    assert result.classification == "tool_call"
    assert result.reasoning_content == "inspect first"
    assert result.tool_calls == ({
        "id": "call-7", "type": "function",
        "function": {"name": "read_file", "arguments": '{"path":"orders.py"}'},
    },)
    assert result.receipt()["tool_call_count"] == 1


def test_reasoning_without_final_is_not_counted_as_completion():
    chunks = sse(
        frame(delta={"reasoning_content": "only hidden work"}),
        frame(finish="stop"),
        usage_frame(),
        "[DONE]",
    )
    result = stream_chat(
        MIA_MTP3_REDUCED47K_OPT,
        [{"role": "user", "content": "solve"}],
        get_policy("medium"),
        seed=17,
        connection_factory=connection_factory(FakeConnection(FakeResponse(chunks))),
    )
    assert result.classification == "no_final"
    assert result.reasoning_content == "only hidden work"
    assert result.content == ""


def test_exact_long_repetition_aborts_and_retains_received_sse():
    block = "".join(f"{index:04x}" for index in range(128))
    chunks = sse(
        frame(delta={"reasoning_content": block}),
        frame(delta={"reasoning_content": block}),
        frame(delta={"reasoning_content": block}),
        frame(finish="stop"),
        usage_frame(),
        "[DONE]",
    )
    result = stream_chat(
        MIA_MTP3_REDUCED47K_OPT,
        [{"role": "user", "content": "solve"}],
        get_policy("medium"),
        seed=17,
        connection_factory=connection_factory(FakeConnection(FakeResponse(chunks))),
    )
    assert result.classification == "repetition_aborted"
    assert result.error_type == "RepetitionAborted"
    assert result.reasoning_content == block * 3
    assert result.response_bytes == b"".join(chunks[:3])


def test_parser_and_transport_failures_are_separate():
    malformed = FakeConnection(FakeResponse([b"data: {bad json}\n\n"]))
    parsed = stream_chat(
        MIA_MTP3_REDUCED47K_OPT,
        [{"role": "user", "content": "x"}],
        get_policy("off"),
        seed=1,
        connection_factory=connection_factory(malformed),
    )
    assert parsed.classification == "parser_error"
    assert parsed.response_bytes == b"data: {bad json}\n\n"

    refused = FakeConnection(FakeResponse([]), fail_connect=True)
    transported = stream_chat(
        MIA_MTP3_REDUCED47K_OPT,
        [{"role": "user", "content": "x"}],
        get_policy("off"),
        seed=1,
        connection_factory=connection_factory(refused),
    )
    assert transported.classification == "transport_error"
    assert transported.error_type == "OSError"


def test_tool_loop_preserves_reasoning_and_function_schema_turns():
    calls = []
    tool_call = {
        "id": "call-1",
        "type": "function",
        "function": {"name": "read_file", "arguments": '{"path":"x.py"}'},
    }

    def invoke(_candidate, messages, _policy, **_kwargs):
        calls.append(json.loads(json.dumps(messages)))
        if len(calls) == 1:
            return turn(
                "tool_call", reasoning="I should inspect it.", tools=(tool_call,),
                finish="tool_calls",
            )
        return turn("completed", content="Fixed and tested.", reasoning="The test passes.")

    observed = []

    def execute(name, arguments):
        observed.append((name, arguments))
        return {"path": "x.py", "content": "broken"}

    result = run_tool_loop(
        MIA_MTP3_REDUCED47K_OPT,
        [{"role": "user", "content": "repair"}],
        get_policy("medium"),
        tools=list(FILESYSTEM_TOOLS),
        execute_tool=execute,
        seed=10,
        invoke=invoke,
    )
    assert result.classification == "completed"
    assert result.interventions == 1
    assert observed == [("read_file", {"path": "x.py"})]
    assistant = calls[1][1]
    assert assistant["role"] == "assistant"
    assert assistant["reasoning_content"] == "I should inspect it."
    assert assistant["tool_calls"] == [tool_call]
    assert calls[1][2] == {
        "role": "tool",
        "tool_call_id": "call-1",
        "content": '{"content":"broken","path":"x.py"}',
    }


def test_cli_writes_exact_request_and_sse_per_repeat(monkeypatch, tmp_path, capsys):
    raw_request = b'{"model":"fixed"}'
    raw_sse = b"data: fixed\n\n"

    def fake_stream(*_args, **_kwargs):
        result = turn("completed", content="answer")
        return dataclasses.replace(
            result,
            request_body={"model": "fixed"},
            request_bytes=raw_request,
            response_bytes=raw_sse,
        )

    monkeypatch.setattr(personal_client, "stream_chat", fake_stream)
    output = tmp_path / "client-output"
    assert personal_client.main([
        "--prompt", "hello", "--policy", "off", "--output-dir", str(output),
        "--repeat", "2", "--seed", "9",
    ]) == 0
    for index in (1, 2):
        attempt = output / f"attempt-{index:03d}"
        assert (attempt / "request.json").read_bytes() == raw_request
        assert (attempt / "response.sse").read_bytes() == raw_sse
        receipt = json.loads((attempt / "result.json").read_text())
        assert receipt["classification"] == "completed"
        assert receipt["seed"] == 9
    summary = json.loads((output / "summary.json").read_text())
    assert summary["policy"] == "off"
    assert summary["requested_candidate_spec_id"] == MIA_MTP3_REDUCED47K_OPT.spec_id
    assert summary["runtime_profile_verified"] is False
    assert "completed" in capsys.readouterr().out
