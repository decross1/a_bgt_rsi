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
from agent_wrapper import worker_activity
from agent_wrapper.backends import get_backend
from agent_wrapper.wrapper import (
    DEFAULT_BACKEND,
    MEMORY_LOG,
    _emit,
    _project_for_log,
    get_run_id,
    set_run_id,
)
from orchestrator import active_run
from orchestrator import iteration_cache
from orchestrator.journal_stub import finalize_iteration_record
from orchestrator.runtime import PyRuntime, Runtime
from orchestrator.tool_registry import TOOL_SPECS
from workers.meta_review import meta_review as _meta_review
from workers.ml_intern import ml_intern as _ml_intern
from workers.retrieval_relevance import relevance
from orchestrator import domain_anchor
from orchestrator import topicality as topicality_mod
from workers.redteam_critic import redteam_critic as _redteam_critic


REPO_ROOT = Path(__file__).resolve().parent.parent
LOOP_MEMORY_PATH = REPO_ROOT / "memory" / "loop_memory.jsonl"  # ARCHITECTURE.md §4.4 — Layer-3
ACTIVE_PATH = "run_state/active_iteration.json"  # relative to REPO_ROOT
CALLS_LOG_PATH = REPO_ROOT / "logs" / "calls.jsonl"

_DEFAULT_LOG_PATH = str(CALLS_LOG_PATH)
# Sentinel default for run_iteration's log_path: None means the in-memory
# MEMORY_LOG (test mode), so "use the live calls log" needs a distinct
# marker, resolved at CALL time from _DEFAULT_LOG_PATH — def-time binding
# made the live log unpatchable and tests polluted logs/calls.jsonl with
# fake-model rows (D-048).
_USE_DEFAULT_LOG = object()
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
    backend_name: str | None = None,
    max_tokens: int | None = None,
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
    # Stamp the active run_id so loop_v0 orchestrator turns are attributable
    # (nara builds its own record, bypassing wrapper._record's run_id stamp).
    run_id = get_run_id()
    if run_id is not None:
        rec["run_id"] = run_id
    if backend_name is not None:
        rec["backend"] = backend_name
    if max_tokens is not None:
        rec["max_tokens"] = max_tokens
    _emit(rec, log_path)
    # Per-call UI inference-internals row (best-effort; never raises) —
    # orchestrator turns get the same live-panel visibility as worker calls.
    worker_activity.emit_worker_activity(
        run_id=run_id,
        task_id=caller_tag,
        output_tokens=rec["usage"]["output_tokens"],
        max_tokens=(max_tokens if max_tokens is not None
                    else rec["usage"]["output_tokens"]),
        latency_ms=latency_ms,
        timestamp=rec["timestamp"],
        backend=backend_name,
        model=rec["model"],
    )
    return rec


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
        # Planned-chain status board (UI timeline, 2026-06-10). meta_review
        # always runs as the pre-step; dynamic sub-loops (redteam, ml_intern)
        # insert themselves via _steps_mark when they fire.
        "steps": [
            {"name": s, "status": "pending"}
            for s in ["meta_review", *_LOOP_V0_STEPS]
        ],
    }


def _steps_mark(
    runtime: Runtime,
    active: dict,
    iteration_id: str,
    name: str,
    status: str,
    *,
    insert_after: str | None = None,
) -> None:
    """Set active['steps'] entry `name` to `status` and emit one
    loop_v0_active_step event. Unknown names are inserted after
    `insert_after` (or appended) — that is how dynamic sub-loop steps
    (redteam, ml_intern) join the board. Stamps started_at on first
    'running', ended_at on terminal statuses. Never raises: the status
    board is telemetry and must not break the chain. The caller decides
    when to persist `active` (write_state)."""
    try:
        steps = active.get("steps")
        if not isinstance(steps, list):
            return
        entry = next((s for s in steps if s.get("name") == name), None)
        if entry is None:
            entry = {"name": name, "status": "pending"}
            idx = next(
                (i for i, s in enumerate(steps)
                 if s.get("name") == insert_after),
                None,
            )
            steps.insert(idx + 1 if idx is not None else len(steps), entry)
        now = _utcnow_iso()
        if status == "running" and not entry.get("started_at"):
            entry["started_at"] = now
        if status in ("passed", "failed", "skipped"):
            entry["ended_at"] = now
        entry["status"] = status
        runtime.log_event({
            "event_type": "loop_v0_active_step",
            "iteration_id": iteration_id,
            "step": name,
            "status": status,
        })
    except Exception:
        return


def run_iteration(
    topic: str,
    *,
    runtime: Runtime | None = None,
    source: str = "human_cli",
    log_path=_USE_DEFAULT_LOG,
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
    if log_path is _USE_DEFAULT_LOG:
        log_path = _DEFAULT_LOG_PATH  # resolved at call time (patchable)
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
    # UI observability: mirror the iteration into the generalized active_run.json
    # (active_iteration.json stays the loop-detail subset). set_run_id stamps
    # every wrapper call this iteration makes. Cleared in the finally below —
    # restoring the PRIOR run_id, not None, so an in-process parent run (the
    # coordinator executing this iteration) keeps its own call attribution.
    _prev_run_id = get_run_id()
    set_run_id(iteration_id)
    active_run.write_active_run(
        iteration_id, "loop_v0", f"LOOP_V0 iteration {iteration_id}",
        model=be.default_model,
    )
    runtime.log_event({
        "event_type": "loop_v0_iteration_start",
        "iteration_id": iteration_id,
        "topic": topic,
        "source": source,
    })
    # Registration/cleanup wrapper (2026-06-10). The cleanup used to live in
    # finalize's narrow `finally`, so any exception in the ~550-line chain
    # body leaked the run_id contextvar + the live state files — in the
    # long-lived tool-plane process that stamped STALE iteration ids onto
    # later calls (the 2026-06-09 attribution bug). This wrapper guarantees
    # cleanup on every exit path.
    try:
        return _run_iteration_impl(
            runtime, be, iteration_id, started_at, active, topic,
            source=source, log_path=log_path, max_depth=max_depth,
            experiment_outcome=experiment_outcome,
            cross_tier_comparison=cross_tier_comparison,
        )
    finally:
        runtime.delete_state(ACTIVE_PATH)
        active_run.clear_active_run()
        set_run_id(_prev_run_id)


def _run_iteration_impl(
    runtime: Runtime,
    be,
    iteration_id: str,
    started_at: str,
    active: dict,
    topic: str,
    *,
    source: str,
    log_path: str | None,
    max_depth: int,
    experiment_outcome: dict | None,
    cross_tier_comparison: dict | None,
) -> dict:
    """The iteration chain body. Registration (state files, run_id, events)
    and cleanup are the caller's job — run_iteration wraps this in
    try/finally. Do not call directly."""
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
    _steps_mark(runtime, active, iteration_id, "meta_review", "running")
    runtime.write_state(ACTIVE_PATH, active)
    try:
        mr = _meta_review(parent_request_id=iteration_id)
        if isinstance(mr, dict) and mr.get("status") == "passed":
            _steps_mark(runtime, active, iteration_id, "meta_review", "passed")
            meta_review_record = mr.get("result")
            bullets = (mr.get("result") or {}).get("conditioning_bullets") or []
            if bullets:
                user_content += "\n\nPrior-iteration conditioning:\n" + "\n".join(
                    f"- {b}" for b in bullets
                )
        else:
            _steps_mark(runtime, active, iteration_id, "meta_review", "failed")
            runtime.log_event({
                "event_type": "loop_v0_fallback",
                "skill_used": "fallback",
                "iteration_id": iteration_id,
                "note": (
                    "meta_review did not produce conditioning bullets "
                    f"(status={mr.get('status') if isinstance(mr, dict) else 'n/a'}); "
                    "proceeding un-conditioned."
                ),
            })
    except Exception as exc:
        _steps_mark(runtime, active, iteration_id, "meta_review", "failed")
        runtime.log_event({
            "event_type": "loop_v0_fallback",
            "skill_used": "fallback",
            "iteration_id": iteration_id,
            "note": (
                f"meta_review raised {type(exc).__name__}: {exc}; "
                "proceeding un-conditioned."
            ),
        })
    runtime.write_state(ACTIVE_PATH, active)

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
    # Slice-2 ML-Intern (D-038) — orchestrator-driven topic-based S2
    # backfill. Fires at most ONCE per iteration when retrieve_literature
    # signals escalation; the guard stops a re-escalating weak topic from
    # looping.
    ml_intern_done = False

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
            backend_name=be.name,
            max_tokens=1024,
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
                _steps_mark(runtime, active, iteration_id, name, "running")
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
                _steps_mark(
                    runtime, active, iteration_id, name,
                    "passed"
                    if active["tool_calls_so_far"][-1]["status"] == "passed"
                    else "failed",
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
                        # Topical-relevance gate (rule 4): score the retrieved
                        # neighbors against the hypothesis so novelty/critic and
                        # the UI never trust 'novel/survives' on off-topic
                        # retrieval. Orchestrator-driven (not a Nara tool —
                        # Gemma mis-sequences such steps); mutates payload in
                        # place so it lands in the cache + the final record.
                        _hyp_text = (captured.get("hypothesis") or {}).get("text") or ""
                        # T1a: hypothesis<->GT-domain-anchor cosine, computed
                        # ONCE here (relevance() stays pure). None under
                        # MOCK_LLM / missing anchor / embed failure -> anchor
                        # rules inert. The LLM topicality check (R0) is the
                        # 2026-06-09 replacement signal after both embedding
                        # anchors were falsified as separators.
                        _anchor = domain_anchor.anchor_cosine(_hyp_text)
                        _topic = topicality_mod.check(_hyp_text)
                        payload["relevance"] = relevance(
                            payload.get("neighbors") or [],
                            _hyp_text,
                            anchor_cosine=_anchor,
                            topicality=_topic,
                        )
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
                    _steps_mark(runtime, active, iteration_id, "redteam",
                                "running", insert_after="hypothesize")
                    runtime.write_state(ACTIVE_PATH, active)
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
                    # Terminal red-team chip status: failed = the final
                    # verdict is still fatal_flaw (the chain proceeds —
                    # red-team is advisory after retries are exhausted —
                    # but the board shows the honest outcome).
                    _final_rt_verdict = (
                        (redteam_result.get("result") or {}).get("verdict")
                        if isinstance(redteam_result, dict) else None
                    )
                    _steps_mark(
                        runtime, active, iteration_id, "redteam",
                        "failed" if _final_rt_verdict == "fatal_flaw"
                        else "passed",
                    )
                    runtime.write_state(ACTIVE_PATH, active)

                # Slice-2 ML-Intern (D-038) — DETERMINISTIC, orchestrator-
                # driven topic backfill. After retrieve_literature lands, if
                # it signaled escalation (weak signal AND narrow foundational
                # coverage), fetch topic-relevant papers from Semantic Scholar
                # into `ml_intern_fetched`, then re-run retrieval so the now-
                # registered collection is queried. NOT a Nara tool / not in
                # _LOOP_V0_STEPS. At most once per iteration (the guard stops a
                # still-weak topic from re-escalating into a loop). Any
                # ml_intern error / 0 papers stored leaves the original weak
                # retrieval and lets the chain proceed — never crashes.
                if name == "retrieve_literature" and not ml_intern_done:
                    esc = (captured.get("retrieval") or {}).get("escalation") or {}
                    if esc.get("should_escalate"):
                        ml_intern_done = True
                        _steps_mark(runtime, active, iteration_id, "ml_intern",
                                    "running",
                                    insert_after="retrieve_literature")
                        runtime.write_state(ACTIVE_PATH, active)
                        hyp_text = (captured.get("hypothesis") or {}).get("text") or ""
                        runtime.log_event({
                            "event_type": "loop_v0_ml_intern",
                            "phase": "dispatch",
                            "iteration_id": iteration_id,
                            "parent_request_id": last_id,
                        })
                        mi = _ml_intern(hyp_text, iteration_id,
                                        parent_request_id=last_id)
                        mi_result = mi.get("result") or {} if isinstance(mi, dict) else {}
                        runtime.log_event({
                            "event_type": "loop_v0_ml_intern",
                            "phase": "result",
                            "iteration_id": iteration_id,
                            "status": mi.get("status") if isinstance(mi, dict) else "unknown",
                            "papers_fetched": mi_result.get("papers_fetched", 0),
                            "papers_stored": mi_result.get("papers_stored", 0),
                            "parent_request_id": last_id,
                        })
                        mi_ok = (
                            isinstance(mi, dict)
                            and mi.get("status") == "passed"
                            and mi_result.get("papers_stored", 0) > 0
                        )
                        # failed = backfill stored nothing (the chain
                        # proceeds on the original weak retrieval).
                        _steps_mark(runtime, active, iteration_id,
                                    "ml_intern",
                                    "passed" if mi_ok else "failed")
                        runtime.write_state(ACTIVE_PATH, active)
                        if mi_ok:
                            re_ret = runtime.dispatch_tool(
                                "retrieve_literature",
                                {"hypothesis_text": hyp_text, "k": 10,
                                 "include_ml_intern": True},
                                parent_request_id=last_id,
                            )
                            if (isinstance(re_ret, dict)
                                    and re_ret.get("status") == "passed"
                                    and isinstance(re_ret.get("result"), dict)):
                                captured["retrieval"] = re_ret["result"]
                                _hyp_text = (captured.get("hypothesis") or {}).get("text") or ""
                                _anchor = domain_anchor.anchor_cosine(_hyp_text)
                                _topic = topicality_mod.check(_hyp_text)
                                re_ret["result"]["relevance"] = relevance(
                                    re_ret["result"].get("neighbors") or [],
                                    _hyp_text,
                                    anchor_cosine=_anchor,
                                    topicality=_topic,
                                )
                                iteration_cache.write_entry(
                                    iteration_id, "retrieval", re_ret
                                )

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
                # A critic that never ran is not evidence of survival —
                # same dangerous-default class fixed in the worker
                # fallbacks on 2026-06-09 (undecidable fails closed).
                "verdict": "undecidable",
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
        # The journal DID get written (orchestrator-filled); the fallback
        # event above records the degraded path.
        _steps_mark(runtime, active, iteration_id, "journal_writer", "passed")
        runtime.log_event({
            "event_type": "loop_v0_fallback",
            "skill_used": "fallback",
            "iteration_id": iteration_id,
            "note": (
                "Nara did not call journal_writer; orchestrator filled "
                f"using captured={sorted(captured)}."
            ),
        })

    # Terminal sweep: any step never reached is 'skipped' — the board never
    # ends an iteration claiming work is still pending.
    for _s in list(active.get("steps") or []):
        if _s.get("status") == "pending":
            _steps_mark(runtime, active, iteration_id, _s["name"], "skipped")
    runtime.write_state(ACTIVE_PATH, active)

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
    # State-file/run_id cleanup happens in run_iteration's finally.

    return record
