"""Bounded sub-agent dispatch — the fan-out/fan-in primitive.

A sub-agent is a separate LLM conversation with:
  - its own system prompt (specialized for the task)
  - its own optional toolbelt (which the sub-agent can call recursively)
  - a hard budget on turns + wall time + total tokens
  - a structured final output that's validated before return

The orchestrator (Nara) dispatches a sub-agent via `run_subagent(...)`,
which is opaque from the outside — Nara never sees the sub-agent's
internal turns. The sub-agent's wrapper calls land in `logs/calls.jsonl`
linked by `parent_request_id` so the chain is reconstructible.

This is the pure-Python implementation. NemoClawRuntime (D-031, when
the runtime swap lands) will dispatch the same conversation inside an
OpenShell sandbox via `nemoclaw exec` — the SubAgent API stays the
same; only where the conversation runs changes.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Literal

import jsonschema

from agent_wrapper.cleanup import strip_channel_markup
from agent_wrapper.gemma_tool_parse import (
    SynthToolCall,
    parse_inline_tool_calls,
    split_narration_and_markup,
)
from agent_wrapper.backends import get_backend
from agent_wrapper.wrapper import (
    DEFAULT_BACKEND,
    _emit,
    _project_for_log,
)


SubAgentStatus = Literal["passed", "error", "timeout", "schema_mismatch"]


@dataclass
class SubAgentBudget:
    """Hard caps a sub-agent must respect.

    - `max_turns`: maximum LLM turns (each turn = one round-trip to vLLM).
    - `max_wall_seconds`: total wall-clock cap including tool execution.
    - `max_tokens_total`: cumulative output tokens across all turns.

    Exceeding any cap returns status="timeout" with whatever's been
    captured so far. Hard caps prevent run-away sub-agent loops from
    burning the GPU or stalling the iteration.
    """
    max_turns: int = 8
    max_wall_seconds: float = 90.0
    max_tokens_total: int = 8000


@dataclass
class SubAgentResult:
    """Return shape from `run_subagent`. Mirrors the worker contract.

    - `status`: passed = final structured output validated against schema;
      error = sub-agent exception or wrapper failure; timeout = budget
      exceeded; schema_mismatch = the sub-agent emitted a final message
      that didn't validate against `expected_output_schema`.
    - `result`: the validated final-output dict (when status=passed),
      else None.
    - `errors`: list of error strings explaining non-passed status.
    - `wrapper_call_ids`: every wrapper request_id this sub-agent
      produced, in order. Pairs with `logs/calls.jsonl` entries.
    - `turns_used`: how many LLM turns the sub-agent consumed.
    - `wall_seconds`: total wall-clock time including tool execution.
    - `output_tokens_used`: cumulative output tokens across turns.
    """
    status: SubAgentStatus
    result: dict | None
    errors: list[str] = field(default_factory=list)
    wrapper_call_ids: list[str] = field(default_factory=list)
    turns_used: int = 0
    wall_seconds: float = 0.0
    output_tokens_used: int = 0


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _extract_json_object(text: str) -> dict[str, Any] | None:
    """Same balanced-brace JSON extractor used in the LLM-using workers.
    A copy lives here to keep this module self-contained — if the
    pattern shows up a fourth time we hoist to a shared util."""
    if not isinstance(text, str):
        return None
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _emit_record(
    openai_messages: list[dict],
    resp,
    latency_ms: float,
    *,
    caller_tag: str,
    parent_request_id: str | None,
    log_path: str | None,
    model_version: str,
    host_metadata: dict,
) -> dict:
    """Log one sub-agent turn to logs/calls.jsonl in the standard
    call-record shape. Mirrors orchestrator/nara.py's `_record_turn`
    but tagged with the sub-agent name so chains are demuxable."""
    msg = resp.choices[0].message
    text_content = msg.content or ""
    tool_calls = list(msg.tool_calls or [])
    if tool_calls:
        completion = json.dumps([
            {
                "id": tc.id,
                "type": tc.type,
                "function": {"name": tc.function.name,
                             "arguments": tc.function.arguments},
            }
            for tc in tool_calls
        ])
    else:
        completion = text_content
    rec = {
        "timestamp": _utcnow_iso(),
        "request_id": str(uuid.uuid4()),
        "model": resp.model,
        "model_version": model_version,
        "temperature": 0.0,
        "top_p": 1.0,
        "seed": None,
        "prompt_messages": _project_for_log(openai_messages),
        "completion": completion,
        "usage": {
            "input_tokens": resp.usage.prompt_tokens,
            "output_tokens": resp.usage.completion_tokens,
        },
        "latency_ms": latency_ms,
        "host_metadata": dict(host_metadata),
        "caller_tag": caller_tag,
        "parent_request_id": parent_request_id,
    }
    return _emit(rec, log_path)


def run_subagent(
    *,
    name: str,
    system_prompt: str,
    user_prompt: str,
    expected_output_schema: dict,
    tools: list[dict] | None = None,
    tool_dispatch: dict[str, Callable] | None = None,
    budget: SubAgentBudget | None = None,
    parent_request_id: str | None = None,
    log_path: str | None = None,
    model: str | None = None,
    backend: str | None = None,
) -> SubAgentResult:
    """Run a bounded sub-agent conversation. Returns a SubAgentResult.

    The sub-agent runs in this process (same Python interpreter as the
    caller) with its own conversation context. Tools (if any) execute
    via `tool_dispatch[name]` — these are the sub-agent's toolbelt,
    NOT the caller's. The sub-agent stops when:

      - it emits a non-tool-calling assistant message whose JSON-extracted
        payload validates against `expected_output_schema` → passed
      - it emits a non-tool-calling message whose payload does NOT validate
        → schema_mismatch
      - it exceeds the budget's max_turns / max_wall_seconds /
        max_tokens_total → timeout
      - an unhandled exception → error

    Args:
        name: identifier for the sub-agent (e.g. "critic_loop_v0").
            Used in caller_tag for call logs.
        system_prompt: the sub-agent's system message. Should include
            an explicit STRICT-JSON output instruction matching
            `expected_output_schema`.
        user_prompt: the task statement (the inputs the sub-agent acts on).
        expected_output_schema: JSON Schema the final assistant message
            must validate against.
        tools: optional list of OpenAI tool specs the sub-agent may call.
            Each spec must reference a callable in `tool_dispatch`.
        tool_dispatch: name → callable. The callable must accept
            **kwargs matching the tool's parameter schema, plus an
            optional `parent_request_id` kwarg.
        budget: cap on turns, wall time, and tokens. Defaults reasonable
            for a one-step research worker.
        parent_request_id: ties the sub-agent's wrapper calls into the
            outer iteration's chain.
    """
    budget = budget or SubAgentBudget()
    tools = tools or []
    tool_dispatch = tool_dispatch or {}
    tool_specs = [t["spec"] if "spec" in t else t for t in tools]
    be = get_backend(backend or DEFAULT_BACKEND)

    started_perf = time.perf_counter()
    wrapper_call_ids: list[str] = []
    output_tokens = 0
    last_id = parent_request_id

    openai_messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    def _elapsed() -> float:
        return time.perf_counter() - started_perf

    for turn in range(budget.max_turns):
        if _elapsed() > budget.max_wall_seconds:
            return SubAgentResult(
                status="timeout",
                result=None,
                errors=[
                    f"wall-clock cap {budget.max_wall_seconds}s exceeded "
                    f"after {turn} turns"
                ],
                wrapper_call_ids=wrapper_call_ids,
                turns_used=turn,
                wall_seconds=_elapsed(),
                output_tokens_used=output_tokens,
            )
        if output_tokens > budget.max_tokens_total:
            return SubAgentResult(
                status="timeout",
                result=None,
                errors=[
                    f"output-token cap {budget.max_tokens_total} exceeded "
                    f"({output_tokens}) after {turn} turns"
                ],
                wrapper_call_ids=wrapper_call_ids,
                turns_used=turn,
                wall_seconds=_elapsed(),
                output_tokens_used=output_tokens,
            )

        try:
            t0 = time.perf_counter()
            resp = be.create_chat(
                model=model or be.default_model,
                messages=openai_messages,
                tools=tool_specs if tool_specs else None,
                temperature=0.2,
                # Same cap as nara.py — bounded per-turn output so a
                # tool-call-as-text emission can't run away.
                max_tokens=1024,
            )
            latency_ms = (time.perf_counter() - t0) * 1000.0
        except Exception as exc:
            return SubAgentResult(
                status="error",
                result=None,
                errors=[
                    f"backend {be.name!r} call failed: "
                    f"{type(exc).__name__}: {exc}"
                ],
                wrapper_call_ids=wrapper_call_ids,
                turns_used=turn,
                wall_seconds=_elapsed(),
                output_tokens_used=output_tokens,
            )

        record = _emit_record(
            openai_messages, resp, latency_ms,
            caller_tag=f"subagent.{name}",
            parent_request_id=last_id,
            log_path=log_path,
            model_version=be.model_version,
            host_metadata=be.host_metadata,
        )
        wrapper_call_ids.append(record["request_id"])
        last_id = record["request_id"]
        output_tokens += record["usage"]["output_tokens"]

        msg = resp.choices[0].message
        raw_content = msg.content or ""
        tool_calls = list(msg.tool_calls or [])

        # Same fallback parser as nara.py: if vLLM's gemma4 parser missed
        # an inline `<|tool_call>call:NAME{...}` markup, synthesize tool
        # calls from the text content and treat anything before the marker
        # as narration (which we then attempt to validate as a final
        # JSON answer, since for sub-agents a non-tool-call final IS the
        # exit condition).
        if not tool_calls:
            synthesized = parse_inline_tool_calls(raw_content)
            if synthesized:
                tool_calls = [SynthToolCall(t) for t in synthesized]
                narration_only, _ = split_narration_and_markup(raw_content)
                raw_content = narration_only

        text_content = raw_content.strip()

        if not tool_calls:
            # Sub-agent's final message — try to validate against schema.
            final_text = strip_channel_markup(text_content)
            payload = _extract_json_object(final_text)
            if payload is None:
                return SubAgentResult(
                    status="schema_mismatch",
                    result=None,
                    errors=[
                        "final message had no extractable JSON object; "
                        f"raw: {final_text[:300]!r}"
                    ],
                    wrapper_call_ids=wrapper_call_ids,
                    turns_used=turn + 1,
                    wall_seconds=_elapsed(),
                    output_tokens_used=output_tokens,
                )
            try:
                jsonschema.Draft7Validator(expected_output_schema).validate(payload)
            except jsonschema.ValidationError as exc:
                return SubAgentResult(
                    status="schema_mismatch",
                    result=payload,  # caller may still find it useful
                    errors=[
                        f"final payload failed schema validation: "
                        f"{exc.message} at {list(exc.absolute_path)}"
                    ],
                    wrapper_call_ids=wrapper_call_ids,
                    turns_used=turn + 1,
                    wall_seconds=_elapsed(),
                    output_tokens_used=output_tokens,
                )
            return SubAgentResult(
                status="passed",
                result=payload,
                errors=[],
                wrapper_call_ids=wrapper_call_ids,
                turns_used=turn + 1,
                wall_seconds=_elapsed(),
                output_tokens_used=output_tokens,
            )

        # Stage the assistant turn (with tool_calls) for the next request.
        openai_messages.append({
            "role": "assistant",
            "content": text_content,
            "tool_calls": [
                {"id": tc.id, "type": tc.type,
                 "function": {"name": tc.function.name,
                              "arguments": tc.function.arguments}}
                for tc in tool_calls
            ],
        })

        # Dispatch the sub-agent's tools.
        for tc in tool_calls:
            tool_name = tc.function.name
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError as exc:
                tool_result: Any = {
                    "status": "error",
                    "errors": [f"malformed tool arguments JSON: {exc}"],
                }
            else:
                impl = tool_dispatch.get(tool_name)
                if impl is None:
                    tool_result = {
                        "status": "error",
                        "errors": [
                            f"sub-agent called unknown tool {tool_name!r}; "
                            f"known: {sorted(tool_dispatch)}"
                        ],
                    }
                else:
                    try:
                        tool_result = impl(**args, parent_request_id=last_id)
                    except Exception as exc:
                        tool_result = {
                            "status": "error",
                            "errors": [f"{type(exc).__name__}: {exc}"],
                        }

            openai_messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(tool_result, default=str),
            })

    # max_turns exhausted.
    return SubAgentResult(
        status="timeout",
        result=None,
        errors=[
            f"max_turns={budget.max_turns} exhausted without a "
            f"non-tool-calling final message"
        ],
        wrapper_call_ids=wrapper_call_ids,
        turns_used=budget.max_turns,
        wall_seconds=_elapsed(),
        output_tokens_used=output_tokens,
    )
