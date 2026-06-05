"""Nara — the LOOP_V0 orchestrator.

Today (Part 1, hello-world): given a topic, Nara picks one of four
tools (summarize_paper, play_pd_match, query_chroma) based on her
read of the topic, emits a brief one-sentence narration before each
tool call, then calls journal_writer_stub to finalize. The substrate
(Runtime) routes tool dispatch, state I/O, and event logging.

Tomorrow (Part 2): the prompt expands to mandate the 5-step LOOP_V0
chain (hypothesize → retrieve → novelty → critique → journal). Same
orchestrator code; different system prompt.

Why a custom loop instead of `wrapper.call_with_tools`: that helper's
auto-dispatch logs ONLY tool_calls when present (no separate text
content), so per-turn narration isn't visible. Here we drive the
multi-turn loop manually, log each turn through the wrapper's
schema-valid `_emit`, and pull text_content for the active_iteration
narration field.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

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
    MEMORY_LOG,
    _emit,
    _project_for_log,
)
from orchestrator import iteration_cache
from orchestrator.journal_stub import finalize_iteration_record
from orchestrator.runtime import PyRuntime, Runtime
from orchestrator.tool_registry import TOOL_SPECS
from workers.meta_review import meta_review as _meta_review
from workers.redteam_critic import redteam_critic as _redteam_critic


REPO_ROOT = Path(__file__).resolve().parent.parent
LOOP_MEMORY_PATH = REPO_ROOT / "memory" / "loop_memory.jsonl"  # ARCHITECTURE.md §4.4 — Layer-3
ACTIVE_PATH = "run_state/active_iteration.json"  # relative to REPO_ROOT
CALLS_LOG_PATH = REPO_ROOT / "logs" / "calls.jsonl"

_DEFAULT_LOG_PATH = str(CALLS_LOG_PATH)
# 5 tool turns + 1 final assistant turn + headroom = 12. Each turn is one
# LLM round-trip; we cap so a run-away chain can't burn the GPU.
_DEFAULT_MAX_DEPTH = 12


NARA_PROMPT_V0 = (
    "You are Nara, the research orchestrator for the a_bgt_rsi "
    "apparatus. Your job is to evaluate a research topic in game theory, "
    "behavioral game theory, or learning in games by running the LOOP_V0 "
    "cognitive chain.\n"
    "\n"
    "**Iteration id.** The user message tells you the `iteration_id` for "
    "this run. The orchestrator caches each tool's full result under this "
    "id. Downstream workers fetch heavy payloads (neighbors arrays, etc.) "
    "from that cache by `iteration_id` — you do NOT re-emit those payloads "
    "in tool_call args. You only pass the small fields each step computes "
    "(hypothesis_text, iteration_id, nara_summary).\n"
    "\n"
    "Always run these five tool calls in this exact order, one per turn:\n"
    "\n"
    "  1. hypothesize(topic=<the user's topic>)\n"
    "     → returns {text, candidates_considered, all_candidates}.\n"
    "       The `text` field is the chosen hypothesis.\n"
    "\n"
    "  2. retrieve_literature(hypothesis_text=<step 1's text>, k=10)\n"
    "     → returns {k, neighbors: [...]}. The neighbors are cached for\n"
    "       you under iteration_id — do not copy them into later args.\n"
    "\n"
    "  3. novelty_classify(hypothesis_text=<step 1's text>,\n"
    "                      iteration_id=<the iteration_id>)\n"
    "     → reads neighbors from cache; returns\n"
    "       {class, rationale, top_neighbor_id}.\n"
    "\n"
    "  4. critic_loop_v0(hypothesis_text=<step 1's text>,\n"
    "                    iteration_id=<the iteration_id>)\n"
    "     → reads neighbors from cache; returns\n"
    "       {verdict, rationale, contradicting_paper_id}.\n"
    "\n"
    "  5. journal_writer(topic=<original topic>,\n"
    "                    iteration_id=<the iteration_id>,\n"
    "                    nara_summary=<your one-paragraph summary>)\n"
    "     → reads all four substructures from cache and writes the\n"
    "       markdown journal entry. Always call last.\n"
    "\n"
    "Before EACH tool call, emit ONE short narration sentence in your "
    "assistant content describing what you're about to do and why. "
    "Then emit the tool_call(s). When a tool returns, briefly note what "
    "you learned in your next narration line.\n"
    "\n"
    "After step 5, emit a final assistant message (no tool_calls) with "
    "a 1-2 paragraph human-readable summary of the iteration: the "
    "hypothesis, the novelty class, the critic's verdict, and what "
    "the human reader should take away.\n"
    "\n"
    "Strict rules:\n"
    "  - Never skip a step. The chain is fixed at five.\n"
    "  - Never call the same step twice.\n"
    "  - Do NOT re-emit captured payloads (neighbors, retrieval, novelty,\n"
    "    critique, hypothesis blobs) in tool_call args. Pass iteration_id\n"
    "    plus only the new fields each step computes.\n"
    "  - Emit valid JSON for all tool arguments.\n"
    "  - **CRITICAL: emit tool calls via the OpenAI tool_calls field, NEVER\n"
    "    as text content.** Do not write `<|tool_call>` or any inline\n"
    "    markup mimicking a tool call. The runtime only sees tool_calls\n"
    "    delivered through the proper structured field. If you write a\n"
    "    tool call as text, NOTHING HAPPENS — the chain stalls and you\n"
    "    will be re-prompted. Your assistant message has TWO slots:\n"
    "    (a) `content` for narration text, (b) `tool_calls` for the\n"
    "    actual structured calls. Use both, in the same message."
)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _next_iteration_id(today: str | None = None) -> str:
    """iter-YYYY-MM-DD-NNN, sequential within the day."""
    if today is None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prefix = f"iter-{today}-"
    LOOP_MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing = []
    if LOOP_MEMORY_PATH.exists():
        for line in LOOP_MEMORY_PATH.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            iid = row.get("iteration_id", "")
            if iid.startswith(prefix):
                try:
                    n = int(iid[len(prefix):])
                    existing.append(n)
                except ValueError:
                    pass
    next_n = (max(existing) + 1) if existing else 1
    return f"{prefix}{next_n:03d}"


def _record_turn(
    openai_messages: list[dict],
    resp,
    latency_ms: float,
    caller_tag: str,
    parent_request_id: str | None,
    log_path: str | None,
    *,
    model_version: str,
    host_metadata: dict,
) -> dict:
    """Schema-valid call record. Mirrors wrapper._record but is local so
    we can decide what goes in 'completion' (text vs tool_calls) ourselves."""
    msg = resp.choices[0].message
    text_content = msg.content or ""
    tool_calls = list(msg.tool_calls or [])

    if tool_calls:
        completion = json.dumps([
            {
                "id": tc.id,
                "type": tc.type,
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
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


_LOOP_V0_STEPS = [
    "hypothesize",
    "retrieve_literature",
    "novelty_classify",
    "critic_loop_v0",
    "journal_writer",
]




def _captured_to_step(name: str) -> str:
    """Map a tool name to the captured-key it populates."""
    return {
        "hypothesize":         "hypothesis",
        "retrieve_literature": "retrieval",
        "novelty_classify":    "novelty",
        "critic_loop_v0":      "critique",
        "journal_writer":      "journal",
    }.get(name, name)


def _next_chain_step(captured: dict) -> str:
    """Walk the LOOP_V0 step list; return the first one whose result
    isn't yet captured. If the chain is fully captured (including
    journal_writer), returns 'journal_writer' as a safe default — the
    caller is expected to gate on `journal_entry_path is None` first."""
    for step in _LOOP_V0_STEPS:
        key = _captured_to_step(step)
        if key not in captured:
            return step
    return "journal_writer"


def _hypothesize_retry(
    runtime: Runtime,
    topic: str,
    critique: str,
    parent_request_id: str | None,
) -> dict:
    """Re-call the hypothesize worker through the runtime with the
    red-team critique appended to the topic (Loop v1 Step 2.5 retry).
    Returns the worker contract dict (or an error-shaped dict on a
    dispatch exception)."""
    revised_topic = (
        f"{topic}\n\n[Red-team critique of the prior hypothesis — "
        f"revise to address it]: {critique}"
    )
    try:
        return runtime.dispatch_tool(
            "hypothesize",
            {"topic": revised_topic},
            parent_request_id=parent_request_id,
        )
    except Exception as exc:  # never let a retry crash the chain
        return {
            "status": "error",
            "result": None,
            "errors": [f"{type(exc).__name__}: {exc}"],
        }


def _initial_active(
    iteration_id: str,
    topic: str,
    *,
    orchestrator_backend: str | None = None,
    orchestrator_model: str | None = None,
) -> dict:
    return {
        "iteration_id": iteration_id,
        "topic": topic,
        "started_at": _utcnow_iso(),
        "current_step": "starting",
        "step_started_at": _utcnow_iso(),
        "latest_narration": None,
        "orchestrator_backend": orchestrator_backend,
        "orchestrator_model": orchestrator_model,
        "tool_calls_so_far": [],
    }


def run_iteration(
    topic: str,
    *,
    runtime: Runtime | None = None,
    source: str = "human_cli",
    log_path: str | None = _DEFAULT_LOG_PATH,
    max_depth: int = _DEFAULT_MAX_DEPTH,
    backend: str | None = None,
    experiment_outcome: dict | None = None,
    cross_tier_comparison: dict | None = None,
) -> dict:
    """Run one LOOP_V0 iteration. Returns the final iteration_record dict.

    backend: which backend the orchestrator brain (Nara) runs on.
        None -> DEFAULT_BACKEND (vllm-gemma). Workers picked via tool_calls
        are dispatched by the runtime and may run on a different backend
        per the per-tool tier (a future routing extension).

    experiment_outcome: optional Tier-1/Tier-2 sandbox-experiment outcome to
        attach to the resulting iteration_record. When non-None, the dict is
        threaded into the iteration_record under the `experiment_outcome`
        field (schema-validated by `finalize_iteration_record`). Used by
        experiment → LOOP_V0 bridges (e.g., exp003_vickrey_rediscovery's
        loop_bridge.py).

    cross_tier_comparison: optional Loop v1 Step-5 cross-mechanism
        replication comparison (from experiments/replication_driver). When
        non-None, threaded into the iteration_record under the
        `cross_tier_comparison` field. Mirrors `experiment_outcome`."""
    runtime = runtime or PyRuntime()
    be = get_backend(backend or DEFAULT_BACKEND)
    iteration_id = _next_iteration_id()
    started_at = _utcnow_iso()
    active = _initial_active(
        iteration_id, topic,
        orchestrator_backend=be.name,
        orchestrator_model=be.default_model,
    )
    runtime.write_state(ACTIVE_PATH, active)
    runtime.log_event({
        "event_type": "loop_v0_iteration_start",
        "iteration_id": iteration_id,
        "topic": topic,
        "source": source,
    })

    # Conversation state for the LLM. Inject iteration_id into the user
    # message so Nara has the value to pass as the `iteration_id` arg on
    # novelty_classify / critic_loop_v0 / journal_writer.
    user_content = (
        f"iteration_id: {iteration_id}\n\n"
        f"Evaluate this research topic: {topic}"
    )

    # Loop v1 Step 1.5 — meta-review PRE-STEP. Read the loop's own memory
    # and condition the next iteration on it. Orchestrator-driven (not a
    # Nara tool). A failure degrades gracefully: we log a fallback per
    # inviolate rule 7 and proceed un-conditioned — never crash the chain.
    meta_review_record: dict | None = None
    try:
        mr = _meta_review(parent_request_id=iteration_id)
        if isinstance(mr, dict) and mr.get("status") == "passed":
            meta_review_record = mr.get("result")
            bullets = (mr.get("result") or {}).get("conditioning_bullets") or []
            if bullets:
                user_content += "\n\nPrior-iteration conditioning:\n" + "\n".join(
                    f"- {b}" for b in bullets
                )
        else:
            runtime.log_event({
                "event_type": "loop_v0_fallback",
                "iteration_id": iteration_id,
                "note": (
                    "meta_review did not produce conditioning bullets "
                    f"(status={mr.get('status') if isinstance(mr, dict) else 'n/a'}); "
                    "proceeding un-conditioned."
                ),
            })
    except Exception as exc:
        runtime.log_event({
            "event_type": "loop_v0_fallback",
            "iteration_id": iteration_id,
            "note": (
                f"meta_review raised {type(exc).__name__}: {exc}; "
                "proceeding un-conditioned."
            ),
        })

    openai_messages: list[dict] = [
        {"role": "system", "content": NARA_PROMPT_V0},
        {"role": "user", "content": user_content},
    ]
    parent_request_id = iteration_id  # iteration-level lineage anchor
    wrapper_call_ids: list[str] = []
    narration_log: list[dict] = []
    tool_calls_made: list[str] = []
    journal_entry_path: str | None = None
    final_summary: str | None = None
    tool_specs = TOOL_SPECS
    last_id: str | None = None
    # Capture each LOOP_V0 step's result for the iteration_record. Keyed
    # by tool name → the tool's `result` payload. If Nara skips a step
    # we still serialize what we have.
    captured: dict[str, dict] = {}
    # Loop v1 Step 2.5 — red-team retry sub-loop state. Set when the
    # hypothesis is first captured; `redteam_retries` caps re-hypothesize
    # attempts at 2.
    redteam_result: dict | None = None
    redteam_retries = 0

    for depth in range(max_depth):
        # Update active: between calls, Nara is "thinking"
        active["current_step"] = "nara_thinking"
        active["step_started_at"] = _utcnow_iso()
        runtime.write_state(ACTIVE_PATH, active)

        t0 = time.perf_counter()
        resp = be.create_chat(
            model=be.default_model,
            messages=openai_messages,
            tools=tool_specs,
            temperature=0.0,
            # Cap per-turn output so a confused Gemma can't generate the
            # entire neighbor list as a stringified `<|tool_call>...` text
            # blob (a real failure mode we hit on iter-010). 1024 tokens
            # is plenty for narration + a single proper tool_call, and a
            # tight cap also forces faster turn cycles when re-prompting.
            max_tokens=1024,
        )
        latency_ms = (time.perf_counter() - t0) * 1000.0

        record = _record_turn(
            openai_messages, resp, latency_ms,
            caller_tag="nara.run_iteration",
            parent_request_id=last_id or parent_request_id,
            log_path=log_path,
            model_version=be.model_version,
            host_metadata=be.host_metadata,
        )
        wrapper_call_ids.append(record["request_id"])
        last_id = record["request_id"]

        msg = resp.choices[0].message
        raw_content = msg.content or ""
        tool_calls = list(msg.tool_calls or [])

        # Fallback parser: Gemma 4 stochastically emits tool calls as
        # inline `<|tool_call>call:NAME{...}` markup in `content` instead
        # of using the OpenAI tool_calls field (vLLM's --tool-call-parser
        # gemma4 misses this format on ~50% of long-context turns; caught
        # on iter-010). When that happens, synthesize tool_calls from the
        # text content and treat the text BEFORE the marker as narration.
        if not tool_calls:
            synthesized = parse_inline_tool_calls(raw_content)
            if synthesized:
                tool_calls = [SynthToolCall(t) for t in synthesized]
                narration_only, _ = split_narration_and_markup(raw_content)
                raw_content = narration_only
                runtime.log_event({
                    "event_type": "loop_v0_synth_tool_call",
                    "iteration_id": iteration_id,
                    "count": len(synthesized),
                    "names": [s["function"]["name"] for s in synthesized],
                    "parent_request_id": last_id,
                })

        # Strip Gemma's chat-template markers (`<|channel|>`, lone "thought"
        # lines, etc.) from anything that lands in the iteration_record.
        # The raw record in logs/calls.jsonl is preserved as-is for forensics.
        text_content = strip_channel_markup(raw_content.strip())

        # Narration: any text Nara emitted this turn (before tool_calls or as
        # a final message) is treated as her commentary.
        if text_content:
            narration_log.append({
                "timestamp": _utcnow_iso(),
                "tool": tool_calls[0].function.name if tool_calls else None,
                "text": text_content,
            })
            active["latest_narration"] = text_content

        if not tool_calls:
            # No tool_calls. Two cases:
            #   (a) chain is complete (journal_writer already returned) →
            #       this is Nara's final summary, exit the loop.
            #   (b) chain is incomplete → Nara emitted an intermediate
            #       narration without a tool_call. Re-prompt with the
            #       next-step nudge so the chain doesn't stall.
            chain_complete = journal_entry_path is not None
            if chain_complete:
                final_summary = text_content or "(no final summary emitted)"
                break
            # Re-prompt: append the narration as an assistant message and
            # then a user nudge naming the next step.
            openai_messages.append({
                "role": "assistant",
                "content": text_content,
            })
            next_step = _next_chain_step(captured)
            openai_messages.append({
                "role": "user",
                "content": (
                    f"Continue the chain. Your next tool call must be "
                    f"`{next_step}`. Emit narration AND the tool_call in the "
                    f"same assistant message."
                ),
            })
            runtime.log_event({
                "event_type": "loop_v0_reprompt",
                "iteration_id": iteration_id,
                "next_step": next_step,
                "parent_request_id": last_id,
            })
            continue

        # Stage the assistant turn (with tool_calls) for the next request
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

        # Dispatch each tool through the Runtime
        for tc in tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError as exc:
                tool_result = {
                    "status": "error",
                    "errors": [f"malformed tool arguments JSON: {exc}"],
                }
            else:
                # Mark active.current_step
                active["current_step"] = name
                active["step_started_at"] = _utcnow_iso()
                # Backend/model: orchestrator-default for now. If a worker
                # used a different backend, it can override via
                # `backend_used`/`model_used` in its tool_result, which we
                # read post-dispatch below. For critic_loop_v0, pre-populate
                # subagent fields with the orchestrator default; the worker
                # echoes the actually-used sub-agent backend back in result,
                # which we also pick up post-dispatch.
                entry: dict = {
                    "tool": name,
                    "started_at": active["step_started_at"],
                    "ended_at": None,
                    "status": "in_progress",
                    "narration": active.get("latest_narration"),
                    "backend": be.name,
                    "model": be.default_model,
                }
                if name == "critic_loop_v0":
                    entry["subagent_backend"] = be.name
                    entry["subagent_model"] = be.default_model
                active["tool_calls_so_far"].append(entry)
                runtime.write_state(ACTIVE_PATH, active)

                runtime.log_event({
                    "event_type": "loop_v0_tool_dispatch",
                    "iteration_id": iteration_id,
                    "tool": name,
                    "parent_request_id": last_id,
                })

                try:
                    tool_result = runtime.dispatch_tool(
                        name, args, parent_request_id=last_id,
                    )
                except Exception as exc:
                    tool_result = {
                        "status": "error",
                        "errors": [f"{type(exc).__name__}: {exc}"],
                    }

                # Update active: tool finished
                active["tool_calls_so_far"][-1]["ended_at"] = _utcnow_iso()
                active["tool_calls_so_far"][-1]["status"] = (
                    tool_result.get("status", "passed")
                    if isinstance(tool_result, dict) else "passed"
                )
                # Backend overrides reported by the worker (forward-compat
                # hook for selective per-tool backend tiers; Phase-3
                # critic-flip uses subagent_backend/subagent_model in
                # particular).
                if isinstance(tool_result, dict):
                    result_payload = tool_result.get("result")
                    if isinstance(result_payload, dict):
                        for src_key, dst_key in (
                            ("backend_used", "backend"),
                            ("model_used", "model"),
                            ("subagent_backend", "subagent_backend"),
                            ("subagent_model", "subagent_model"),
                        ):
                            val = result_payload.get(src_key)
                            if val:
                                active["tool_calls_so_far"][-1][dst_key] = val
                runtime.write_state(ACTIVE_PATH, active)

                runtime.log_event({
                    "event_type": "loop_v0_tool_receipt",
                    "iteration_id": iteration_id,
                    "tool": name,
                    "status": (
                        tool_result.get("status")
                        if isinstance(tool_result, dict) else "unknown"
                    ),
                    "parent_request_id": last_id,
                })

            tool_calls_made.append(name)
            # Capture each LOOP_V0 step's payload so the iteration_record
            # ends up complete even if Nara forgets a step at the end.
            # Also write the FULL tool_result to the per-iteration cache
            # so downstream workers can fetch by iteration_id rather than
            # receiving heavy payloads in tool_call args (reference-passing
            # refactor — keeps Nara's emissions under the 1024 max_tokens
            # per-turn cap regardless of Gemma's stochastic inline format).
            if isinstance(tool_result, dict) and tool_result.get("status") == "passed":
                payload = tool_result.get("result")
                cache_key: str | None = None
                if isinstance(payload, dict):
                    if name == "hypothesize":
                        captured["hypothesis"] = payload
                        cache_key = "hypothesis"
                    elif name == "retrieve_literature":
                        captured["retrieval"] = payload
                        cache_key = "retrieval"
                    elif name == "novelty_classify":
                        captured["novelty"] = payload
                        cache_key = "novelty"
                    elif name == "critic_loop_v0":
                        captured["critique"] = payload
                        cache_key = "critique"
                    elif name == "journal_writer":
                        captured["journal"] = payload
                        journal_entry_path = payload.get("journal_entry_path")
                        # journal_writer is the consumer, not a producer —
                        # nothing downstream reads its result from cache.
                if cache_key is not None:
                    iteration_cache.write_entry(
                        iteration_id, cache_key, tool_result
                    )

                # Loop v1 Step 2.5 — DETERMINISTIC red-team retry sub-loop.
                # After hypothesize lands, red-team the hypothesis ITSELF
                # before downstream budget is spent. This is orchestrator-
                # driven (NOT a Nara prompt instruction — Gemma mis-sequences
                # such instructions, as the re-prompt machinery attests).
                # If the critic finds a fatal flaw and we have retries left,
                # re-call hypothesize with the critique appended, overwrite
                # the cached hypothesis, and increment. Cap at 2 retries.
                # A critic failure never blocks: redteam_critic returns
                # verdict "proceed" with status "passed" in that case.
                if name == "hypothesize" and "hypothesis" in captured:
                    hyp_text = captured["hypothesis"].get("text") or ""
                    while True:
                        rt = _redteam_critic(hyp_text, iteration_id,
                                             parent_request_id=last_id)
                        redteam_result = rt
                        verdict = (rt.get("result") or {}).get("verdict") \
                            if isinstance(rt, dict) else None
                        if verdict != "fatal_flaw" or redteam_retries >= 2:
                            break
                        critique = (rt.get("result") or {}).get("critique") or ""
                        runtime.log_event({
                            "event_type": "loop_v0_redteam_retry",
                            "iteration_id": iteration_id,
                            "retry": redteam_retries + 1,
                            "parent_request_id": last_id,
                        })
                        revised = _hypothesize_retry(
                            runtime, topic, critique, last_id,
                        )
                        redteam_retries += 1
                        if not (isinstance(revised, dict)
                                and revised.get("status") == "passed"
                                and isinstance(revised.get("result"), dict)):
                            # Re-hypothesize failed; keep the prior hypothesis
                            # and stop retrying (don't loop on a broken worker).
                            break
                        captured["hypothesis"] = revised["result"]
                        iteration_cache.write_entry(
                            iteration_id, "hypothesis", revised
                        )
                        hyp_text = revised["result"].get("text") or ""

            openai_messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(tool_result, default=str),
            })

    else:
        # max_depth exhausted without a non-tool-emitting turn
        final_summary = (
            f"(max_depth={max_depth} exhausted; iteration cut short)"
        )

    ended_at = _utcnow_iso()

    # Build the iteration_record. If Nara skipped journal_writer, the
    # orchestrator calls it directly with whatever it captured during
    # the loop — degraded path, logged as a fallback event.
    if journal_entry_path is None:
        from workers.journal_writer import journal_writer as _full_jw
        from orchestrator.journal_stub import journal_writer_stub as _stub_jw

        if "hypothesis" in captured:
            # We have at least step 1 captured — use the full writer with
            # whatever substructures landed; fill missing ones with
            # explicit placeholder cache entries so journal_writer's
            # enum validation (which now reads from cache) doesn't reject
            # the call.
            def _ensure_cached(key: str, fallback_result: dict) -> None:
                if not iteration_cache.has_entry(iteration_id, key):
                    iteration_cache.write_entry(iteration_id, key, {
                        "status": "passed",
                        "result": fallback_result,
                        "errors": ["(orchestrator-supplied placeholder; worker did not run)"],
                    })

            _ensure_cached("retrieval", {"k": 0, "neighbors": []})
            _ensure_cached("novelty", {
                "class": "unclear",
                "rationale": "(novelty_classify did not run)",
                "top_neighbor_id": None,
            })
            _ensure_cached("critique", {
                "verdict": "survives",
                "rationale": "(critic_loop_v0 did not run)",
                "contradicting_paper_id": None,
            })
            out = _full_jw(
                topic=topic,
                iteration_id=iteration_id,
                nara_summary=final_summary or "(Nara did not emit a final summary)",
                parent_request_id=last_id,
            )
        else:
            # No hypothesis even — fall all the way back to the stub.
            out = _stub_jw(
                summary=(final_summary or "(Nara skipped the chain entirely)"),
                tool_calls_made=tool_calls_made or ["(none)"],
                parent_request_id=last_id,
            )
        journal_entry_path = out["result"]["journal_entry_path"]
        runtime.log_event({
            "event_type": "loop_v0_fallback",
            "iteration_id": iteration_id,
            "note": (
                "Nara did not call journal_writer; orchestrator filled "
                f"using captured={sorted(captured)}."
            ),
        })

    record = {
        "iteration_id":       iteration_id,
        "started_at":         started_at,
        "ended_at":           ended_at,
        "seed": {
            "topic":  topic,
            "source": source,
        },
        "nara_summary":       final_summary or "",
        "tool_calls_made":    tool_calls_made,
        "narration_log":      narration_log,
        "journal_entry_path": journal_entry_path,
        "model_version":      be.model_version,
        "wrapper_call_ids":   wrapper_call_ids,
    }
    # Attach the four substructures when present so the iteration_record
    # reflects the full chain.
    for key in ("hypothesis", "retrieval", "novelty", "critique"):
        if key in captured:
            record[key] = captured[key]

    # Loop v1 Step 1.5 — store the meta-review synthesis used to condition
    # this iteration (None when meta_review degraded; omit then).
    if meta_review_record is not None:
        record["meta_review"] = meta_review_record

    # Loop v1 Step 2.5 — store the final red-team result + retries used.
    if redteam_result is not None and isinstance(redteam_result.get("result"), dict):
        rt_res = dict(redteam_result["result"])
        rt_res["retries_used"] = redteam_retries
        record["redteam"] = rt_res

    # Loop v1 Step 8 — open the human gate. A verdict is written later via
    # orchestrator.gate_cli to memory/loop_feedback.jsonl.
    record["gate_status"] = "pending"

    # Bridge field for Tier-1/Tier-2 sandbox experiments (Slice 1 / exp003).
    if experiment_outcome is not None:
        record["experiment_outcome"] = experiment_outcome

    # Loop v1 Step 5 — cross-mechanism replication comparison bridge.
    if cross_tier_comparison is not None:
        record["cross_tier_comparison"] = cross_tier_comparison

    # Validate + append to loop_memory
    try:
        finalize_iteration_record(record)
        runtime.log_event({
            "event_type": "loop_v0_iteration_complete",
            "iteration_id": iteration_id,
            "tool_calls_made": tool_calls_made,
            "duration_ms": int(
                (datetime.fromisoformat(ended_at.replace("Z", "+00:00"))
                 - datetime.fromisoformat(started_at.replace("Z", "+00:00"))
                 ).total_seconds() * 1000
            ),
        })
    except jsonschema.ValidationError as exc:
        runtime.log_event({
            "event_type": "loop_v0_iteration_failed",
            "iteration_id": iteration_id,
            "error": str(exc),
        })
        raise
    finally:
        runtime.delete_state(ACTIVE_PATH)

    return record
