"""Wrapper-level tests for named policies, telemetry, and timeout bounds."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_wrapper import wrapper as W
from agent_wrapper.backends.qwen_vllm import VLLMQwenBackend


MESSAGES = [{"role": "user", "content": "ping"}]


def _response(*, content="pong", tool_calls=None, reasoning=None,
              finish_reason="stop", model="gemma-4-26b-a4b"):
    return SimpleNamespace(
        model=model,
        choices=[SimpleNamespace(
            finish_reason=finish_reason,
            message=SimpleNamespace(
                content=content,
                tool_calls=tool_calls,
                reasoning=reasoning,
            ),
        )],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=2),
    )


class _CaptureBackend:
    name = "vllm-gemma"
    default_model = "gemma-4-26b-a4b"
    model_version = "vllm/test/gemma"
    host_metadata = {"backend": "vllm"}

    def __init__(self, responses=None):
        self.calls = []
        self.responses = list(responses or [_response()])

    def create_chat(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)

    async def create_chat_async(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def _tool_call():
    return SimpleNamespace(
        id="call-1",
        type="function",
        function=SimpleNamespace(name="identity", arguments='{"value": 3}'),
    )


TOOLS = [{
    "spec": {
        "type": "function",
        "function": {
            "name": "identity",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"value": {"type": "integer"}},
                "required": ["value"],
            },
        },
    },
    "impl": lambda value: {"value": value},
}]


def test_legacy_call_preserves_exact_request_and_record_keys():
    be = _CaptureBackend()
    with patch.object(W, "get_backend", return_value=be):
        rec = W.call_sync(MESSAGES, caller_tag="test/legacy", log_path=None)
    assert be.calls == [{
        "model": "gemma-4-26b-a4b",
        "messages": MESSAGES,
        "max_tokens": None,
        "temperature": 0.0,
        "top_p": 1.0,
        "seed": None,
    }]
    assert set(rec) == {
        "timestamp", "request_id", "model", "model_version", "temperature",
        "top_p", "seed", "prompt_messages", "completion", "usage",
        "latency_ms", "host_metadata", "caller_tag", "parent_request_id",
        "backend",
    }


def test_sync_profile_sends_resolved_policy_and_logs_effective_metadata():
    be = _CaptureBackend([_response(reasoning="abc", finish_reason="length")])
    with patch.object(W, "get_backend", return_value=be):
        rec = W.call_sync(
            MESSAGES, profile="gemma_card_thinking",
            temperature=0.0, caller_tag="test/profile", log_path=None)
    sent = be.calls[0]
    assert sent["temperature"] == 0.0
    assert sent["top_p"] == 0.95
    assert sent["extra_body"] == {
        "top_k": 64,
        "chat_template_kwargs": {"enable_thinking": True},
    }
    assert rec["profile"] == "gemma_card_thinking"
    assert rec["reasoning_effort"] is None
    assert rec["sampling_extra"] == sent["extra_body"]
    assert rec["finish_reason"] == "length"
    assert rec["reasoning_chars"] == 3


def test_unavailable_finish_and_reasoning_are_explicit_nulls_for_profile():
    resp = _response()
    delattr(resp.choices[0], "finish_reason")
    delattr(resp.choices[0].message, "reasoning")
    be = _CaptureBackend([resp])
    with patch.object(W, "get_backend", return_value=be):
        rec = W.call_sync(MESSAGES, profile="scientist", log_path=None)
    assert rec["finish_reason"] is None
    assert rec["reasoning_chars"] is None


def test_qwen_profile_forwards_only_supported_effort():
    be = _CaptureBackend([
        _response(model="qwen3.8-27b-nvfp4-mtp", reasoning="think")])
    be.name = "vllm-qwen"
    be.default_model = "qwen3.8-27b-nvfp4-mtp"
    with patch.object(W, "get_backend", return_value=be):
        rec = W.call_sync(MESSAGES, profile="critic_medium", log_path=None)
    assert be.calls[0]["reasoning_effort"] == "medium"
    assert "extra_body" not in be.calls[0]
    assert rec["reasoning_effort"] == "medium"


def test_qwen_nonthinking_profile_sends_no_ignored_effort():
    be = _CaptureBackend([
        _response(model="qwen3.8-27b-nvfp4-mtp", reasoning=None)])
    be.name = "vllm-qwen"
    be.default_model = "qwen3.8-27b-nvfp4-mtp"
    with patch.object(W, "get_backend", return_value=be):
        rec = W.call_sync(
            MESSAGES, profile="qwen_card_instruct", log_path=None)
    assert "reasoning_effort" not in be.calls[0]
    assert be.calls[0]["extra_body"]["chat_template_kwargs"] == {
        "enable_thinking": False}
    assert rec["reasoning_effort"] is None


def test_async_profile_matches_sync_request_shape():
    be = _CaptureBackend()
    with patch.object(W, "get_backend", return_value=be):
        rec = asyncio.run(W.call_async(
            MESSAGES, profile="scientist", log_path=None))
    assert be.calls[0]["temperature"] == 0.7
    assert be.calls[0]["top_p"] == 0.95
    assert rec["profile"] == "scientist"


def test_tool_loop_reuses_policy_and_preserves_thought_only_for_tool_history():
    be = _CaptureBackend([
        _response(content=None, tool_calls=[_tool_call()], reasoning="tool thought"),
        _response(content="done", tool_calls=None, reasoning="final thought"),
    ])
    with patch.object(W, "get_backend", return_value=be):
        records = W.call_with_tools(
            MESSAGES, TOOLS, profile="gemma_card_thinking", max_depth=1,
            log_path=None)
    assert len(records) == 2
    for call in be.calls:
        assert call["extra_body"]["chat_template_kwargs"]["enable_thinking"] is True
    staged_assistant = be.calls[1]["messages"][1]
    assert staged_assistant["reasoning"] == "tool thought"
    assert "reasoning" not in records[1]["prompt_messages"][1]
    assert records[0]["reasoning_chars"] == len("tool thought")


def test_tool_loop_does_not_change_legacy_history_shape():
    be = _CaptureBackend([
        _response(content=None, tool_calls=[_tool_call()], reasoning="not staged"),
        _response(content="done", tool_calls=None),
    ])
    with patch.object(W, "get_backend", return_value=be):
        W.call_with_tools(MESSAGES, TOOLS, max_depth=1, log_path=None)
    assert "reasoning" not in be.calls[1]["messages"][1]


def test_sync_timeout_is_forwarded_only_when_explicit():
    be = _CaptureBackend([_response(), _response()])
    with patch.object(W, "get_backend", return_value=be):
        W.call_sync(MESSAGES, request_timeout_s=2.5, log_path=None)
        W.call_sync(MESSAGES, log_path=None)
    assert be.calls[0]["timeout"] == 2.5
    assert "timeout" not in be.calls[1]


def test_async_timeout_is_forwarded_as_sdk_timeout():
    be = _CaptureBackend()
    with patch.object(W, "get_backend", return_value=be):
        asyncio.run(W.call_async(
            MESSAGES, request_timeout_s=4.0, log_path=None))
    assert be.calls[0]["timeout"] == 4.0


def test_tool_timeout_is_one_absolute_deadline_across_turns():
    be = _CaptureBackend([
        _response(content=None, tool_calls=[_tool_call()]),
        _response(content="done", tool_calls=None),
    ])
    with patch.object(W, "get_backend", return_value=be), \
         patch.object(W.time, "monotonic", side_effect=[100.0, 101.0, 104.0]):
        W.call_with_tools(
            MESSAGES, TOOLS, request_timeout_s=10.0, max_depth=1,
            log_path=None)
    assert be.calls[0]["timeout"] == 9.0
    assert be.calls[1]["timeout"] == 6.0


def test_tool_timeout_expires_before_starting_another_model_turn():
    be = _CaptureBackend([
        _response(content=None, tool_calls=[_tool_call()]),
        _response(content="must not run"),
    ])
    with patch.object(W, "get_backend", return_value=be), \
         patch.object(W.time, "monotonic", side_effect=[100.0, 101.0, 111.0]):
        with pytest.raises(TimeoutError, match="whole tool loop"):
            W.call_with_tools(
                MESSAGES, TOOLS, request_timeout_s=10.0, max_depth=1,
                log_path=None)
    assert len(be.calls) == 1


def test_vllm_qwen_backend_has_vllm_identity_without_endpoint_drift():
    be = VLLMQwenBackend()
    assert be.name == "vllm-qwen"
    assert be.default_model == "qwen3.8-27b-nvfp4-mtp"
    assert be.base_url == "http://127.0.0.1:8001/v1"
    assert be.model_version.endswith("/qwen3.8-27b-nvfp4-mtp")
    assert be.host_metadata["backend"] == "vllm"
    assert "ollama" not in str(be.host_metadata).lower()


def test_registered_qwen_backend_uses_vllm_adapter():
    be = W.get_backend("vllm-qwen")
    assert isinstance(be, VLLMQwenBackend)
    assert be.base_url == "http://127.0.0.1:8001/v1"
    assert be.default_model == "qwen3.8-27b-nvfp4-mtp"


def test_qwen_budgeted_call_disables_retries_without_changing_legacy_client():
    be = VLLMQwenBackend()
    be._sync = MagicMock()
    retryless = MagicMock()
    be._sync.with_options.return_value = retryless
    retryless.chat.completions.create.return_value = "budgeted"
    be._sync.chat.completions.create.return_value = "legacy"

    assert be.create_chat(model="m", messages=[], timeout=3.0) == "budgeted"
    be._sync.with_options.assert_called_once_with(max_retries=0)
    retryless.chat.completions.create.assert_called_once_with(
        model="m", messages=[], timeout=3.0)
    assert be.create_chat(model="m", messages=[]) == "legacy"
    be._sync.chat.completions.create.assert_called_once_with(
        model="m", messages=[])


def test_vllm_retry_policy_changes_only_for_budgeted_call():
    with patch.object(W, "_sync_client", MagicMock()) as client:
        retryless = MagicMock()
        client.with_options.return_value = retryless
        retryless.chat.completions.create.return_value = "budgeted"
        client.chat.completions.create.return_value = "legacy"
        be = W.VLLMBackend()
        assert be.create_chat(model="m", messages=[], timeout=3.0) == "budgeted"
        client.with_options.assert_called_once_with(max_retries=0)
        retryless.chat.completions.create.assert_called_once_with(
            model="m", messages=[], timeout=3.0)
        assert be.create_chat(model="m", messages=[]) == "legacy"
        client.chat.completions.create.assert_called_once_with(model="m", messages=[])


def test_async_vllm_budgeted_call_disables_sdk_retries():
    with patch.object(W, "_async_client", MagicMock()) as client:
        retryless = MagicMock()
        client.with_options.return_value = retryless
        retryless.chat.completions.create = AsyncMock(return_value="budgeted")
        be = W.VLLMBackend()
        result = asyncio.run(be.create_chat_async(
            model="m", messages=[], timeout=3.0))
        assert result == "budgeted"
        client.with_options.assert_called_once_with(max_retries=0)
        retryless.chat.completions.create.assert_awaited_once_with(
            model="m", messages=[], timeout=3.0)


@pytest.mark.parametrize("bad", [0, -1, float("inf"), float("nan"), True])
def test_timeout_must_be_a_positive_finite_number(bad):
    be = _CaptureBackend()
    with patch.object(W, "get_backend", return_value=be), \
         pytest.raises(ValueError, match="request_timeout_s"):
        W.call_sync(MESSAGES, request_timeout_s=bad, log_path=None)
