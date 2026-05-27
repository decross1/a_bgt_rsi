"""Anthropic API backend.

Translates OpenAI-shaped chat requests/responses to the Anthropic Messages
API so the rest of the codebase keeps its OpenAI surface. Prompt-caches the
system message and tool definitions by default — both rarely change across a
sub-agent's turns, so caching them is the load-bearing optimization on the
Anthropic side.

This backend is for the planner tier (D-035): hard, complex orchestration
work. It is not the default; callers opt in with `backend="anthropic"`.
"""
import json
import os
from typing import Any

from anthropic import Anthropic, AsyncAnthropic


class _Usage:
    def __init__(self, prompt_tokens, completion_tokens):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _ToolCallFunction:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments  # JSON string, matches OpenAI SDK shape


class _ToolCall:
    def __init__(self, id, name, arguments):
        self.id = id
        self.type = "function"
        self.function = _ToolCallFunction(name, arguments)


class _Message:
    def __init__(self, content, tool_calls):
        self.content = content
        self.tool_calls = tool_calls


class _Choice:
    def __init__(self, message):
        self.message = message


class _OpenAIShapedResponse:
    """Mimics the openai SDK response on the fields _record reads:
    `.model`, `.choices[0].message.{content,tool_calls}`,
    `.usage.{prompt_tokens,completion_tokens}`."""

    def __init__(self, model, content, tool_calls, prompt_tokens, completion_tokens):
        self.model = model
        self.choices = [_Choice(_Message(content, tool_calls))]
        self.usage = _Usage(prompt_tokens, completion_tokens)


def _openai_messages_to_anthropic(messages):
    """Return (system_text, anthropic_messages).

    OpenAI's `system` messages collapse into Anthropic's top-level `system`
    param. OpenAI's `tool` role (a tool result) maps to a user message with a
    single `tool_result` content block. An assistant message that carries
    tool_calls maps to an assistant message with `tool_use` content blocks.
    """
    system_parts = []
    out = []
    for m in messages:
        role = m["role"]
        content = m.get("content") or ""
        if role == "system":
            if content:
                system_parts.append(content)
        elif role == "tool":
            out.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": m.get("tool_call_id"),
                    "content": content,
                }],
            })
        elif role == "assistant" and m.get("tool_calls"):
            blocks = []
            if content:
                blocks.append({"type": "text", "text": content})
            for tc in m["tool_calls"]:
                if isinstance(tc, dict):
                    tc_id = tc["id"]
                    tc_name = tc["function"]["name"]
                    tc_args_raw = tc["function"]["arguments"]
                else:
                    tc_id = tc.id
                    tc_name = tc.function.name
                    tc_args_raw = tc.function.arguments
                if isinstance(tc_args_raw, str):
                    try:
                        tc_args = json.loads(tc_args_raw)
                    except json.JSONDecodeError:
                        tc_args = {}
                else:
                    tc_args = tc_args_raw
                blocks.append({
                    "type": "tool_use",
                    "id": tc_id,
                    "name": tc_name,
                    "input": tc_args,
                })
            out.append({"role": "assistant", "content": blocks})
        elif role in ("user", "assistant"):
            out.append({"role": role, "content": content})
        else:
            raise ValueError(f"unsupported OpenAI message role: {role!r}")
    return "\n\n".join(system_parts), out


def _openai_tools_to_anthropic(tools):
    """OpenAI: [{type: 'function', function: {name, description, parameters}}].
    Anthropic: [{name, description, input_schema}]."""
    if not tools:
        return None
    out = []
    for t in tools:
        f = t.get("function", t)
        out.append({
            "name": f["name"],
            "description": f.get("description", ""),
            "input_schema": f.get("parameters", {"type": "object"}),
        })
    return out


def _anthropic_response_to_openai(resp, model):
    text_parts = []
    tool_calls = []
    for block in resp.content:
        btype = getattr(block, "type", None)
        if btype == "text":
            text_parts.append(block.text)
        elif btype == "tool_use":
            tool_calls.append(_ToolCall(
                id=block.id,
                name=block.name,
                arguments=json.dumps(block.input),
            ))
    content = "".join(text_parts) if text_parts else None
    return _OpenAIShapedResponse(
        model=model,
        content=content,
        tool_calls=tool_calls or None,
        prompt_tokens=resp.usage.input_tokens,
        completion_tokens=resp.usage.output_tokens,
    )


class AnthropicBackend:
    def __init__(
        self,
        *,
        name: str = "anthropic",
        model: str | None = None,
        model_version: str | None = None,
        prompt_cache: bool = True,
        api_key: str | None = None,
    ):
        self.name = name
        self._model = model or os.environ.get(
            "ANTHROPIC_MODEL", "claude-opus-4-7")
        self._model_version = model_version or os.environ.get(
            "ANTHROPIC_MODEL_VERSION", f"anthropic/{self._model}")
        self._prompt_cache = prompt_cache
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self._sync_client = None
        self._async_client = None

    def _require_key(self):
        if not self._api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY not set; anthropic backend cannot make calls")

    def _client(self):
        if self._sync_client is None:
            self._require_key()
            self._sync_client = Anthropic(api_key=self._api_key)
        return self._sync_client

    def _aclient(self):
        if self._async_client is None:
            self._require_key()
            self._async_client = AsyncAnthropic(api_key=self._api_key)
        return self._async_client

    @property
    def default_model(self) -> str:
        return self._model

    @property
    def model_version(self) -> str:
        return self._model_version

    @property
    def host_metadata(self) -> dict[str, Any]:
        return {
            "backend": "anthropic",
            "prompt_cache": self._prompt_cache,
        }

    def _build_kwargs(self, model, messages, tools, max_tokens, temperature,
                       top_p, _seed):
        system_text, anth_messages = _openai_messages_to_anthropic(messages)
        anth_tools = _openai_tools_to_anthropic(tools)
        kwargs = {
            "model": model,
            "messages": anth_messages,
            # Anthropic requires max_tokens; default to 4096 when unspecified.
            "max_tokens": max_tokens if max_tokens is not None else 4096,
            "temperature": temperature,
            "top_p": top_p,
        }
        if system_text:
            if self._prompt_cache:
                kwargs["system"] = [{
                    "type": "text",
                    "text": system_text,
                    "cache_control": {"type": "ephemeral"},
                }]
            else:
                kwargs["system"] = system_text
        if anth_tools is not None:
            if self._prompt_cache and anth_tools:
                # cache_control on the last tool entry caches the whole tools
                # block plus everything declared before it (i.e. system).
                anth_tools[-1]["cache_control"] = {"type": "ephemeral"}
            kwargs["tools"] = anth_tools
        # `seed` is OpenAI-only; Anthropic ignores it. The wrapper still
        # records the requested seed for downstream traceability.
        return kwargs

    def create_chat(self, *, model, messages, tools=None, max_tokens=None,
                     temperature=0.0, top_p=1.0, seed=None, **_extra):
        kwargs = self._build_kwargs(model, messages, tools, max_tokens,
                                     temperature, top_p, seed)
        resp = self._client().messages.create(**kwargs)
        return _anthropic_response_to_openai(resp, model)

    async def create_chat_async(self, *, model, messages, tools=None,
                                 max_tokens=None, temperature=0.0, top_p=1.0,
                                 seed=None, **_extra):
        kwargs = self._build_kwargs(model, messages, tools, max_tokens,
                                     temperature, top_p, seed)
        resp = await self._aclient().messages.create(**kwargs)
        return _anthropic_response_to_openai(resp, model)
