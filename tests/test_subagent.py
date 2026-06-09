"""Tests for orchestrator.subagent.

The sub-agent makes real-looking openai client calls; we patch
_sync_client.chat.completions.create on the orchestrator.subagent module
to deliver scripted responses. Each scripted response is a SimpleNamespace
mimicking the OpenAI ChatCompletion object's shape.
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from orchestrator import subagent as sa_mod
from orchestrator.subagent import (
    SubAgentBudget,
    SubAgentResult,
    run_subagent,
)


# ── helpers to build scripted vLLM responses ──────────────────────────


def _resp(
    *,
    content: str = "",
    tool_calls=None,
    prompt_tokens: int = 50,
    completion_tokens: int = 40,
    model: str = "gemma-4-26b-a4b",
):
    """Build a fake OpenAI ChatCompletion response object."""
    return SimpleNamespace(
        model=model,
        choices=[SimpleNamespace(
            message=SimpleNamespace(
                content=content,
                tool_calls=tool_calls or None,
            ),
        )],
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        ),
    )


def _tool_call(*, call_id: str, fn_name: str, args: dict):
    """Build a fake OpenAI tool_call object."""
    return SimpleNamespace(
        id=call_id,
        type="function",
        function=SimpleNamespace(name=fn_name, arguments=json.dumps(args)),
    )


@pytest.fixture
def fake_vllm(monkeypatch):
    """Scripted creator. Tests set .scripts to a list of _resp() outputs;
    each .create() call pops the next one.

    Patches `agent_wrapper.wrapper._sync_client` since the SubAgent now
    routes through the backend registry (post D-035 multi-backend
    substrate) — the default vllm-gemma backend reads _sync_client from
    the wrapper module lazily, so patching it there flows through cleanly."""
    calls: list[dict] = []
    scripts: list = []

    class _ChatCompletions:
        def create(self, **kw):
            calls.append(kw)
            if not scripts:
                raise AssertionError("unexpected vllm call — script empty")
            return scripts.pop(0)

    class _Chat:
        completions = _ChatCompletions()

    fake = SimpleNamespace(chat=_Chat())
    from agent_wrapper import wrapper as W
    monkeypatch.setattr(W, "_sync_client", fake)
    return SimpleNamespace(scripts=scripts, calls=calls)


SIMPLE_SCHEMA = {
    "type": "object",
    "required": ["verdict"],
    "properties": {
        "verdict": {"type": "string", "enum": ["yes", "no"]},
        "rationale": {"type": "string"},
    },
}


# ── tests ─────────────────────────────────────────────────────────────


def test_single_turn_passed(fake_vllm):
    fake_vllm.scripts.append(_resp(content=json.dumps({"verdict": "yes", "rationale": "ok"})))
    out = run_subagent(
        name="t",
        system_prompt="sys",
        user_prompt="user",
        expected_output_schema=SIMPLE_SCHEMA,
    )
    assert out.status == "passed"
    assert out.result == {"verdict": "yes", "rationale": "ok"}
    assert out.turns_used == 1
    assert out.wall_seconds >= 0
    assert len(out.wrapper_call_ids) == 1


def test_schema_mismatch_when_payload_invalid(fake_vllm):
    fake_vllm.scripts.append(_resp(content=json.dumps({"verdict": "maybe"})))
    out = run_subagent(
        name="t",
        system_prompt="sys",
        user_prompt="user",
        expected_output_schema=SIMPLE_SCHEMA,
    )
    assert out.status == "schema_mismatch"
    assert out.result == {"verdict": "maybe"}  # still returned for debugging
    assert any("failed schema validation" in e for e in out.errors)


def test_schema_mismatch_when_no_json_extractable(fake_vllm):
    # max_turns=1 leaves no room for the repair-retry, so a single
    # no-JSON final message resolves straight to schema_mismatch.
    fake_vllm.scripts.append(_resp(content="just some prose, no json here"))
    out = run_subagent(
        name="t",
        system_prompt="sys",
        user_prompt="user",
        expected_output_schema=SIMPLE_SCHEMA,
        budget=SubAgentBudget(max_turns=1),
    )
    assert out.status == "schema_mismatch"
    assert out.result is None
    assert any("no extractable JSON" in e for e in out.errors)


def test_repair_retry_recovers_on_second_turn(fake_vllm):
    # First final message has no extractable JSON; the bounded repair-retry
    # asks for JSON-only and the second turn delivers it -> passed.
    fake_vllm.scripts.append(_resp(content="still thinking, no json yet"))
    fake_vllm.scripts.append(_resp(content=json.dumps({"verdict": "no"})))
    out = run_subagent(
        name="t",
        system_prompt="sys",
        user_prompt="user",
        expected_output_schema=SIMPLE_SCHEMA,
        budget=SubAgentBudget(max_turns=4),
    )
    assert out.status == "passed"
    assert out.result == {"verdict": "no"}
    assert out.turns_used == 2
    # the corrective user turn is staged before the second model call
    assert any(
        "ONLY the JSON object" in str(m.get("content", ""))
        for kw in fake_vllm.calls for m in kw["messages"]
    )


def test_repair_retry_exhausts_to_schema_mismatch(fake_vllm):
    # Every turn is non-JSON: the retry never coerces a verdict and the
    # failure surfaces as schema_mismatch once max_turns is spent.
    for _ in range(3):
        fake_vllm.scripts.append(_resp(content="never any json"))
    out = run_subagent(
        name="t",
        system_prompt="sys",
        user_prompt="user",
        expected_output_schema=SIMPLE_SCHEMA,
        budget=SubAgentBudget(max_turns=3),
    )
    assert out.status == "schema_mismatch"
    assert out.result is None
    assert any("no extractable JSON" in e for e in out.errors)


def test_max_tokens_per_turn_forwarded_to_backend(fake_vllm):
    # The per-turn token cap must reach the backend create() call so a
    # reasoning model can be given headroom (default 1024 stays for Gemma).
    fake_vllm.scripts.append(_resp(content=json.dumps({"verdict": "yes"})))
    run_subagent(
        name="t",
        system_prompt="sys",
        user_prompt="user",
        expected_output_schema=SIMPLE_SCHEMA,
        budget=SubAgentBudget(max_tokens_per_turn=3072),
    )
    assert fake_vllm.calls[0]["max_tokens"] == 3072


def test_reasoning_content_fallback_when_content_has_no_json(fake_vllm):
    """Qwen3.x family (reasoning models served by vLLM with
    --reasoning-parser) route the model's thinking to a separate
    `reasoning_content` slot on the message; sometimes the strict-JSON
    final answer lands there instead of in `content`. SubAgent should
    try the reasoning slot when content parsing yields no JSON. Without
    this fallback, the iter-2026-05-27-006 critic run failed schema
    extraction and defaulted to 'survives' even though Qwen had emitted
    a valid verdict."""
    # Simulate a Qwen-style response: empty content, JSON in
    # model_extra['reasoning_content'].
    msg = SimpleNamespace(
        content="",
        tool_calls=None,
        model_extra={
            "reasoning_content":
                'The retrieved literature contradicts the claim.\n'
                + json.dumps({"verdict": "no", "rationale": "contradicted by chunk-X"})
        },
    )
    fake_resp = SimpleNamespace(
        model="qwen3.6-27b-nvfp4-mtp",
        choices=[SimpleNamespace(message=msg)],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=80),
    )
    fake_vllm.scripts.append(fake_resp)
    out = run_subagent(
        name="t",
        system_prompt="sys",
        user_prompt="user",
        expected_output_schema=SIMPLE_SCHEMA,
    )
    assert out.status == "passed", f"expected passed, got {out.status}: {out.errors}"
    assert out.result == {"verdict": "no", "rationale": "contradicted by chunk-X"}


def test_content_branch_still_preferred_over_reasoning(fake_vllm):
    """When BOTH content and reasoning have JSON, content wins
    (backward-compat: existing Gemma path is unaffected)."""
    msg = SimpleNamespace(
        content=json.dumps({"verdict": "yes", "rationale": "from content"}),
        tool_calls=None,
        model_extra={
            "reasoning_content":
                json.dumps({"verdict": "no", "rationale": "from reasoning — should be ignored"})
        },
    )
    fake_resp = SimpleNamespace(
        model="qwen3.6-27b-nvfp4-mtp",
        choices=[SimpleNamespace(message=msg)],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=80),
    )
    fake_vllm.scripts.append(fake_resp)
    out = run_subagent(
        name="t",
        system_prompt="sys",
        user_prompt="user",
        expected_output_schema=SIMPLE_SCHEMA,
    )
    assert out.status == "passed"
    assert out.result == {"verdict": "yes", "rationale": "from content"}


def test_strips_channel_markup_before_extraction(fake_vllm):
    # Real Gemma leak shape — JSON wrapped in chat-template markup.
    fake_vllm.scripts.append(_resp(
        content="<channel|>\nthought\n" + json.dumps({"verdict": "yes"}),
    ))
    out = run_subagent(
        name="t",
        system_prompt="sys",
        user_prompt="user",
        expected_output_schema=SIMPLE_SCHEMA,
    )
    assert out.status == "passed"
    assert out.result == {"verdict": "yes"}


def test_tool_call_then_final_answer(fake_vllm):
    """Sub-agent uses one tool, then emits final JSON."""
    captured: list = []

    def search_tool(query: str, *, parent_request_id=None):
        captured.append((query, parent_request_id))
        return {"status": "passed", "result": {"hits": ["a", "b"]}, "errors": []}

    tools = [{
        "spec": {
            "type": "function",
            "function": {
                "name": "search",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        },
        "impl": search_tool,
    }]
    tool_dispatch = {"search": search_tool}

    fake_vllm.scripts.append(_resp(
        content="",
        tool_calls=[_tool_call(call_id="c1", fn_name="search", args={"query": "ttf"})],
    ))
    fake_vllm.scripts.append(_resp(
        content=json.dumps({"verdict": "yes", "rationale": "found ttf"}),
    ))

    out = run_subagent(
        name="t",
        system_prompt="sys",
        user_prompt="user",
        expected_output_schema=SIMPLE_SCHEMA,
        tools=tools,
        tool_dispatch=tool_dispatch,
    )
    assert out.status == "passed"
    assert out.turns_used == 2
    assert out.result["verdict"] == "yes"
    # tool was invoked, parent_request_id was threaded through
    assert len(captured) == 1
    assert captured[0][0] == "ttf"
    assert captured[0][1] is not None


def test_unknown_tool_returns_error_to_subagent(fake_vllm):
    """If the sub-agent hallucinates a tool name, the dispatcher returns
    an error result to it; the sub-agent should adapt and emit final JSON."""
    fake_vllm.scripts.append(_resp(
        content="",
        tool_calls=[_tool_call(call_id="c1", fn_name="nonexistent", args={})],
    ))
    fake_vllm.scripts.append(_resp(
        content=json.dumps({"verdict": "no"}),
    ))
    out = run_subagent(
        name="t",
        system_prompt="sys",
        user_prompt="user",
        expected_output_schema=SIMPLE_SCHEMA,
        # No tool_dispatch — any tool call is "unknown"
    )
    # Sub-agent recovered and emitted final answer on next turn
    assert out.status == "passed"
    assert out.turns_used == 2


def test_max_turns_exhausted_returns_timeout(fake_vllm):
    """Sub-agent keeps calling tools forever — runs out of turns."""
    def search_tool(**kw):
        return {"status": "passed", "result": {}, "errors": []}

    tools = [{
        "spec": {
            "type": "function",
            "function": {
                "name": "search",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        "impl": search_tool,
    }]
    tool_dispatch = {"search": search_tool}

    # Script 3 turns that all emit a tool call, with max_turns=3 -> timeout.
    for i in range(3):
        fake_vllm.scripts.append(_resp(
            content="",
            tool_calls=[_tool_call(call_id=f"c{i}", fn_name="search", args={})],
        ))

    out = run_subagent(
        name="t",
        system_prompt="sys",
        user_prompt="user",
        expected_output_schema=SIMPLE_SCHEMA,
        tools=tools,
        tool_dispatch=tool_dispatch,
        budget=SubAgentBudget(max_turns=3, max_wall_seconds=60.0),
    )
    assert out.status == "timeout"
    assert out.turns_used == 3
    assert any("max_turns" in e for e in out.errors)


def test_vllm_exception_returns_error(fake_vllm, monkeypatch):
    def boom(**kw):
        raise ConnectionError("vllm down")

    # Patch through the wrapper module (post D-035 backend substrate);
    # the VLLMBackend reads _sync_client.chat.completions lazily.
    from agent_wrapper import wrapper as W
    monkeypatch.setattr(W._sync_client.chat.completions, "create", boom)
    out = run_subagent(
        name="t",
        system_prompt="sys",
        user_prompt="user",
        expected_output_schema=SIMPLE_SCHEMA,
    )
    assert out.status == "error"
    assert any("vllm down" in e for e in out.errors)
    assert out.turns_used == 0


def test_parent_request_id_threads_through(fake_vllm):
    fake_vllm.scripts.append(_resp(content=json.dumps({"verdict": "yes"})))
    out = run_subagent(
        name="t",
        system_prompt="sys",
        user_prompt="user",
        expected_output_schema=SIMPLE_SCHEMA,
        parent_request_id="iter-root-abc",
    )
    assert out.status == "passed"
    # The single call's parent_request_id should be the iter-root we passed
    # in (because it's the first turn). On subsequent turns it chains to
    # the previous wrapper request_id.
    assert len(out.wrapper_call_ids) == 1


def test_wrapper_call_ids_chain(fake_vllm):
    fake_vllm.scripts.append(_resp(
        content="",
        tool_calls=[_tool_call(call_id="c1", fn_name="t", args={})],
    ))
    fake_vllm.scripts.append(_resp(content=json.dumps({"verdict": "yes"})))

    def t_impl(**kw):
        return {"status": "passed", "result": {}}

    out = run_subagent(
        name="t",
        system_prompt="sys",
        user_prompt="user",
        expected_output_schema=SIMPLE_SCHEMA,
        tools=[{
            "spec": {
                "type": "function",
                "function": {"name": "t", "parameters": {"type": "object"}},
            },
            "impl": t_impl,
        }],
        tool_dispatch={"t": t_impl},
    )
    assert out.status == "passed"
    assert len(out.wrapper_call_ids) == 2
    assert out.wrapper_call_ids[0] != out.wrapper_call_ids[1]
