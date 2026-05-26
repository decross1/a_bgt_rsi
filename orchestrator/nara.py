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
from agent_wrapper.wrapper import (
    HOST_METADATA,
    MEMORY_LOG,
    MODEL,
    MODEL_VERSION,
    _emit,
    _project_for_log,
    _sync_client,
)
from orchestrator.journal_stub import finalize_iteration_record
from orchestrator.runtime import PyRuntime, Runtime
from orchestrator.tool_registry import TOOL_SPECS


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
    "Always run these five tool calls in this exact order, one per turn:\n"
    "\n"
    "  1. hypothesize(topic=<the user's topic>)\n"
    "     → returns {text, candidates_considered, all_candidates}.\n"
    "       The `text` field is the chosen hypothesis.\n"
    "\n"
    "  2. retrieve_literature(hypothesis_text=<step 1's text>, k=10)\n"
    "     → returns {k, neighbors: [{doc_id, content_hash, score,\n"
    "       chunk_text, source_layer, title}, ...]}.\n"
    "\n"
    "  3. novelty_classify(hypothesis_text=<step 1's text>,\n"
    "                      neighbors=<step 2's neighbors>)\n"
    "     → returns {class, rationale, top_neighbor_id}.\n"
    "\n"
    "  4. critic_loop_v0(hypothesis_text=<step 1's text>,\n"
    "                    neighbors=<step 2's neighbors>)\n"
    "     → returns {verdict, rationale, contradicting_paper_id}.\n"
    "\n"
    "  5. journal_writer(topic=<original topic>,\n"
    "                    hypothesis=<step 1 result>,\n"
    "                    retrieval=<step 2 result>,\n"
    "                    novelty=<step 3 result>,\n"
    "                    critique=<step 4 result>,\n"
    "                    nara_summary=<your one-paragraph summary>)\n"
    "     → writes the journal entry. Always call last.\n"
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
    "  - Pass results verbatim — do not paraphrase the hypothesis text\n"
    "    or trim the neighbors list between steps.\n"
    "  - Emit valid JSON for all tool arguments."
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
        "model_version": MODEL_VERSION,
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
        "host_metadata": dict(HOST_METADATA),
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


def _initial_active(iteration_id: str, topic: str) -> dict:
    return {
        "iteration_id": iteration_id,
        "topic": topic,
        "started_at": _utcnow_iso(),
        "current_step": "starting",
        "step_started_at": _utcnow_iso(),
        "latest_narration": None,
        "tool_calls_so_far": [],
    }


def run_iteration(
    topic: str,
    *,
    runtime: Runtime | None = None,
    source: str = "human_cli",
    log_path: str | None = _DEFAULT_LOG_PATH,
    max_depth: int = _DEFAULT_MAX_DEPTH,
) -> dict:
    """Run one LOOP_V0 hello-world iteration. Returns the final
    iteration_record dict."""
    runtime = runtime or PyRuntime()
    iteration_id = _next_iteration_id()
    started_at = _utcnow_iso()
    active = _initial_active(iteration_id, topic)
    runtime.write_state(ACTIVE_PATH, active)
    runtime.log_event({
        "event_type": "loop_v0_iteration_start",
        "iteration_id": iteration_id,
        "topic": topic,
        "source": source,
    })

    # Conversation state for the LLM
    openai_messages: list[dict] = [
        {"role": "system", "content": NARA_PROMPT_V0},
        {"role": "user", "content": f"Evaluate this research topic: {topic}"},
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

    for depth in range(max_depth):
        # Update active: between calls, Nara is "thinking"
        active["current_step"] = "nara_thinking"
        active["step_started_at"] = _utcnow_iso()
        runtime.write_state(ACTIVE_PATH, active)

        t0 = time.perf_counter()
        resp = _sync_client.chat.completions.create(
            model=MODEL,
            messages=openai_messages,
            tools=tool_specs,
            temperature=0.0,
        )
        latency_ms = (time.perf_counter() - t0) * 1000.0

        record = _record_turn(
            openai_messages, resp, latency_ms,
            caller_tag="nara.run_iteration",
            parent_request_id=last_id or parent_request_id,
            log_path=log_path,
        )
        wrapper_call_ids.append(record["request_id"])
        last_id = record["request_id"]

        msg = resp.choices[0].message
        # Strip Gemma's chat-template markers (`<|channel|>`, lone "thought"
        # lines, etc.) from anything that lands in the iteration_record.
        # The raw record in logs/calls.jsonl is preserved as-is for forensics.
        text_content = strip_channel_markup((msg.content or "").strip())
        tool_calls = list(msg.tool_calls or [])

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
                active["tool_calls_so_far"].append({
                    "tool": name,
                    "started_at": active["step_started_at"],
                    "ended_at": None,
                    "status": "in_progress",
                    "narration": active.get("latest_narration"),
                })
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
            if isinstance(tool_result, dict) and tool_result.get("status") == "passed":
                payload = tool_result.get("result")
                if isinstance(payload, dict):
                    if name == "hypothesize":
                        captured["hypothesis"] = payload
                    elif name == "retrieve_literature":
                        captured["retrieval"] = payload
                    elif name == "novelty_classify":
                        captured["novelty"] = payload
                    elif name == "critic_loop_v0":
                        captured["critique"] = payload
                    elif name == "journal_writer":
                        captured["journal"] = payload
                        journal_entry_path = payload.get("journal_entry_path")

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
            # explicit placeholders so journal_writer's enum validation
            # doesn't reject the call.
            placeholder_novelty = {
                "class": "unclear",
                "rationale": "(novelty_classify did not run)",
                "top_neighbor_id": None,
            }
            placeholder_critique = {
                "verdict": "survives",
                "rationale": "(critic_loop_v0 did not run)",
                "contradicting_paper_id": None,
            }
            out = _full_jw(
                topic=topic,
                hypothesis=captured["hypothesis"],
                retrieval=captured.get("retrieval") or {"k": 0, "neighbors": []},
                novelty=captured.get("novelty") or placeholder_novelty,
                critique=captured.get("critique") or placeholder_critique,
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
        "model_version":      MODEL_VERSION,
        "wrapper_call_ids":   wrapper_call_ids,
    }
    # Attach the four substructures when present so the iteration_record
    # reflects the full chain.
    for key in ("hypothesis", "retrieval", "novelty", "critique"):
        if key in captured:
            record[key] = captured[key]

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
