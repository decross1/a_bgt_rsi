"""Translation correctness + key-handling for the Anthropic backend.

Pure-Python unit tests (no live API). A separate live smoke is run manually
via `tests/smoke_anthropic_live.py` once an ANTHROPIC_API_KEY is configured.
"""
import json
import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agent_wrapper.backends.anthropic import (
    AnthropicBackend,
    _anthropic_response_to_openai,
    _openai_messages_to_anthropic,
    _openai_tools_to_anthropic,
)


class TestMessageTranslation:
    def test_system_collapses_into_top_level_string(self):
        sys_text, msgs = _openai_messages_to_anthropic([
            {"role": "system", "content": "you are X"},
            {"role": "user", "content": "hi"},
        ])
        assert sys_text == "you are X"
        assert msgs == [{"role": "user", "content": "hi"}]

    def test_multiple_systems_concat(self):
        sys_text, _ = _openai_messages_to_anthropic([
            {"role": "system", "content": "rule A"},
            {"role": "system", "content": "rule B"},
            {"role": "user", "content": "go"},
        ])
        assert sys_text == "rule A\n\nrule B"

    def test_tool_role_becomes_user_tool_result(self):
        _, msgs = _openai_messages_to_anthropic([
            {"role": "user", "content": "do X"},
            {"role": "tool", "tool_call_id": "call_42",
             "content": json.dumps({"result": "ok"})},
        ])
        assert msgs[1] == {
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": "call_42",
                "content": json.dumps({"result": "ok"}),
            }],
        }

    def test_assistant_with_dict_tool_calls(self):
        _, msgs = _openai_messages_to_anthropic([
            {"role": "user", "content": "what?"},
            {"role": "assistant", "content": "calling",
             "tool_calls": [{
                 "id": "call_1", "type": "function",
                 "function": {"name": "lookup",
                              "arguments": json.dumps({"q": "x"})},
             }]},
        ])
        asst = msgs[1]
        assert asst["role"] == "assistant"
        assert {"type": "text", "text": "calling"} in asst["content"]
        tool_use = [b for b in asst["content"] if b["type"] == "tool_use"][0]
        assert tool_use["name"] == "lookup"
        assert tool_use["input"] == {"q": "x"}
        assert tool_use["id"] == "call_1"

    def test_assistant_with_sdk_object_tool_calls(self):
        tc = SimpleNamespace(
            id="call_2", type="function",
            function=SimpleNamespace(name="t", arguments=json.dumps({"a": 1})))
        _, msgs = _openai_messages_to_anthropic([
            {"role": "assistant", "content": "",
             "tool_calls": [tc]},
        ])
        tool_use = [b for b in msgs[0]["content"] if b["type"] == "tool_use"][0]
        assert tool_use["name"] == "t"
        assert tool_use["input"] == {"a": 1}

    def test_unsupported_role_raises(self):
        with pytest.raises(ValueError, match="unsupported"):
            _openai_messages_to_anthropic([{"role": "function", "content": ""}])


class TestToolTranslation:
    def test_openai_function_spec_to_anthropic_tool(self):
        anth = _openai_tools_to_anthropic([{
            "type": "function",
            "function": {
                "name": "lookup",
                "description": "fetch a thing",
                "parameters": {"type": "object",
                                "properties": {"q": {"type": "string"}}},
            },
        }])
        assert anth == [{
            "name": "lookup",
            "description": "fetch a thing",
            "input_schema": {"type": "object",
                              "properties": {"q": {"type": "string"}}},
        }]

    def test_empty_tools_returns_none(self):
        assert _openai_tools_to_anthropic(None) is None
        assert _openai_tools_to_anthropic([]) is None


class TestResponseTranslation:
    def _resp(self, *blocks, in_tok=10, out_tok=5):
        return SimpleNamespace(
            content=list(blocks),
            usage=SimpleNamespace(input_tokens=in_tok, output_tokens=out_tok),
        )

    def test_text_only(self):
        resp = self._resp(SimpleNamespace(type="text", text="hello"))
        out = _anthropic_response_to_openai(resp, "claude-opus-4-7")
        assert out.choices[0].message.content == "hello"
        assert out.choices[0].message.tool_calls is None
        assert out.usage.prompt_tokens == 10
        assert out.usage.completion_tokens == 5
        assert out.model == "claude-opus-4-7"

    def test_tool_use_only(self):
        resp = self._resp(SimpleNamespace(
            type="tool_use", id="tu_1", name="lookup", input={"q": "x"}))
        out = _anthropic_response_to_openai(resp, "claude-opus-4-7")
        tc = out.choices[0].message.tool_calls[0]
        assert tc.id == "tu_1"
        assert tc.function.name == "lookup"
        assert json.loads(tc.function.arguments) == {"q": "x"}
        assert out.choices[0].message.content is None

    def test_text_and_tool_use_mixed(self):
        resp = self._resp(
            SimpleNamespace(type="text", text="let me check"),
            SimpleNamespace(type="tool_use", id="tu_2", name="lookup",
                             input={"q": "y"}),
        )
        out = _anthropic_response_to_openai(resp, "claude-opus-4-7")
        assert out.choices[0].message.content == "let me check"
        assert len(out.choices[0].message.tool_calls) == 1


class TestBackendLifecycle:
    def test_no_key_lazy_until_call(self):
        # Construction is safe even without a key.
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}, clear=False):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            be = AnthropicBackend(api_key=None)
            assert be.default_model == "claude-opus-4-7"
            with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
                be.create_chat(model="claude-opus-4-7",
                                messages=[{"role": "user", "content": "hi"}])

    def test_create_chat_prompt_cache_on_system_and_tools(self):
        be = AnthropicBackend(api_key="sk-test")
        fake_client = MagicMock()
        # Return a minimal Anthropic-shaped response.
        fake_client.messages.create.return_value = SimpleNamespace(
            content=[SimpleNamespace(type="text", text="ok")],
            usage=SimpleNamespace(input_tokens=1, output_tokens=1),
        )
        be._sync_client = fake_client
        be.create_chat(
            model="claude-opus-4-7",
            messages=[
                {"role": "system", "content": "be brief"},
                {"role": "user", "content": "hi"},
            ],
            tools=[{
                "type": "function",
                "function": {"name": "lookup", "description": "",
                              "parameters": {"type": "object"}},
            }],
        )
        kwargs = fake_client.messages.create.call_args.kwargs
        # System block carries cache_control
        assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}
        # Last (only) tool carries cache_control — caches system+tools together
        assert kwargs["tools"][-1]["cache_control"] == {"type": "ephemeral"}

    def test_max_tokens_default_4096_when_none(self):
        be = AnthropicBackend(api_key="sk-test")
        fake_client = MagicMock()
        fake_client.messages.create.return_value = SimpleNamespace(
            content=[SimpleNamespace(type="text", text="ok")],
            usage=SimpleNamespace(input_tokens=1, output_tokens=1),
        )
        be._sync_client = fake_client
        be.create_chat(model="claude-opus-4-7",
                        messages=[{"role": "user", "content": "hi"}])
        assert fake_client.messages.create.call_args.kwargs["max_tokens"] == 4096

    def test_response_round_trip_through_wrapper_call_sync(self):
        """End-to-end: call_sync(backend='anthropic') stamps the anthropic
        backend's provenance into the record."""
        from agent_wrapper import wrapper as W
        be = W.get_backend("anthropic")
        fake_client = MagicMock()
        fake_client.messages.create.return_value = SimpleNamespace(
            model_id="claude-opus-4-7",
            content=[SimpleNamespace(type="text", text="response")],
            usage=SimpleNamespace(input_tokens=2, output_tokens=3),
        )
        be._sync_client = fake_client
        rec = W.call_sync(
            [{"role": "user", "content": "hi"}],
            backend="anthropic", caller_tag="t", log_path=None)
        assert rec["model_version"].startswith("anthropic/")
        assert rec["host_metadata"]["backend"] == "anthropic"
        assert rec["completion"] == "response"
        assert rec["usage"] == {"input_tokens": 2, "output_tokens": 3}
