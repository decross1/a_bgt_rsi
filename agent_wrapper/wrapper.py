"""
Thin wrapper around vLLM's OpenAI-compatible API. Every model call writes
exactly one schema-valid JSONL line (schema/calls.jsonl.schema.json).

Public interface:
  call_sync(messages, ...)        -> dict        the logged record
  call_async(messages, ...)       -> dict        the logged record  [coroutine]
  call_with_tools(messages, tools, ...) -> list  chain of records (>=1)
  verify_log_integrity(path)      -> int         count of malformed lines

Two log modes (per call, via log_path):
  log_path=<file>  append-only  (production)
  log_path=None    in-memory    (tests) -- records collected in MEMORY_LOG

Config is read from the environment so the same code serves any host:
  VLLM_BASE_URL, VLLM_API_KEY, VLLM_MODEL, VLLM_MODEL_VERSION,
  VLLM_IMAGE_TAG, CUDA_DRIVER.

Day 4 adds: call_with_tools with bounded recursion (max_depth=3). Malformed
tool-call JSON is surfaced (ToolCallError) -- never silently retried; the
program needs to SEE the failure rate before deciding to add guided_json.
"""
import contextvars
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import jsonschema
from openai import AsyncOpenAI, OpenAI

from . import worker_activity
from .backends import get_backend, register_backend
from .backends.anthropic import AnthropicBackend
from .backends.ollama_openai import OllamaBackend
from .backends.vllm_openai import VLLMBackend

_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema" / "calls.jsonl.schema.json"
_VALIDATOR = jsonschema.Draft202012Validator(json.loads(_SCHEMA_PATH.read_text()))

BASE_URL = os.environ.get("VLLM_BASE_URL", "http://localhost:8000/v1")
MODEL = os.environ.get("VLLM_MODEL", "gemma-4-26b-a4b")  # served-model-name, not the -nvfp4 weights path
# Default tracks CLAUDE.md inviolate rule 2 — the pinned image. Day 2's
# D-022 re-pin moved this from v0.20.0 to v0.21.0; that release is
# required for Gemma 4 MTP (PR #41745) and tool calling.
VLLM_IMAGE_TAG = os.environ.get("VLLM_IMAGE_TAG", "vllm/vllm-openai:v0.21.0")
# MODEL_VERSION defaults to <image>/<model> so iteration_records have
# meaningful provenance without requiring a separate env var. Override
# with VLLM_MODEL_VERSION when stamping a specific build hash.
MODEL_VERSION = os.environ.get(
    "VLLM_MODEL_VERSION",
    f"{VLLM_IMAGE_TAG}/{MODEL}",
)
HOST_METADATA = {
    "cuda_driver": os.environ.get("CUDA_DRIVER", "13.0"),
    "vllm_image_tag": VLLM_IMAGE_TAG,
}

# In-memory sink for tests (log_path=None). Cleared by callers as needed.
MEMORY_LOG = []

# Run-id context. A run-mode driver (experiment, autoresearch, loop_v0) sets
# this once at the start of a run; every call_sync/call_with_tools made within
# that run stamps it into the call record (optional field) and into the
# per-call worker_activity row. contextvars (not a module global) so concurrent
# async iterations don't clobber each other. Default None -> field omitted.
_run_id: contextvars.ContextVar = contextvars.ContextVar("_run_id", default=None)


def set_run_id(run_id):
    """Set the active run_id for the current context (None to clear)."""
    _run_id.set(run_id)


def get_run_id():
    """Return the active run_id for the current context, or None."""
    return _run_id.get()

_sync_client = OpenAI(base_url=BASE_URL, api_key=os.environ.get("VLLM_API_KEY", "EMPTY"))
_async_client = AsyncOpenAI(base_url=BASE_URL, api_key=os.environ.get("VLLM_API_KEY", "EMPTY"))

# Backend registry. The vllm-gemma backend reads _sync_client/_async_client
# from this module lazily so existing tests that patch those clients still
# work unchanged. Ollama (coder tier) and anthropic (planner tier) register
# alongside; the default remains vllm-gemma.
register_backend(VLLMBackend())
register_backend(OllamaBackend())
register_backend(AnthropicBackend())
# Second vLLM container on :8001 serving Qwen3.6-27B NVFP4-MTP (the
# Phase-3 critic-flip target per the Co-Scientist insight, D-035).
# Reuses the OllamaBackend class since it's an OpenAI-compat wrapper and
# vllm exposes the same API. Toggle via CRITIC_BACKEND=vllm-qwen at the
# call site (see workers/critic_loop_v0.py).
register_backend(OllamaBackend(
    name="vllm-qwen",
    base_url="http://127.0.0.1:8001/v1",
    model="qwen3.6-27b-nvfp4-mtp",
))
DEFAULT_BACKEND = os.environ.get("WRAPPER_DEFAULT_BACKEND", "vllm-gemma")


def _record(messages, params, resp, latency_ms, caller_tag, parent_request_id,
            retrieval_context=None, model_version=None, host_metadata=None,
            max_tokens=None, backend_name=None):
    """Build a schema-conforming record from a chat-completion response.

    retrieval_context (D-025 / P2): None when no retrieval ran -- the field is
    OMITTED from the record (legacy semantics). A list when at least one
    retrieval contributed to the prompt; each item must carry doc_id,
    content_hash, chunk_offset, chunk_length per the schema.

    model_version / host_metadata: per-call provenance from the backend. If
    None, falls back to the module-level defaults (vllm-gemma) so existing
    callers and tests work unchanged.

    backend_name: backend registry name (e.g. 'vllm-qwen') stamped into the
    optional top-level `backend` field (UI attribution, 2026-06-10). None ->
    field omitted, so legacy records and tests still validate.
    """
    rec = {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "request_id": str(uuid.uuid4()),
        "model": resp.model,
        "model_version": model_version if model_version is not None else MODEL_VERSION,
        "temperature": params["temperature"],
        "top_p": params["top_p"],
        "seed": params["seed"],
        "prompt_messages": [{"role": m["role"], "content": m["content"]} for m in messages],
        "completion": resp.choices[0].message.content or "",
        # vLLM returns prompt_tokens/completion_tokens; the schema names
        # them input_tokens/output_tokens -- map here, at the boundary.
        "usage": {
            "input_tokens": resp.usage.prompt_tokens,
            "output_tokens": resp.usage.completion_tokens,
        },
        "latency_ms": latency_ms,
        "host_metadata": dict(host_metadata) if host_metadata is not None else dict(HOST_METADATA),
        "caller_tag": caller_tag,
        "parent_request_id": parent_request_id,
    }
    if retrieval_context is not None:
        rec["retrieval_context"] = retrieval_context
    # Optional UI-observability fields (omitted when unset, so legacy
    # records and tests still validate). run_id from the run-mode context;
    # max_tokens echoes the generation cap the caller requested.
    run_id = get_run_id()
    if run_id is not None:
        rec["run_id"] = run_id
    if max_tokens is not None:
        rec["max_tokens"] = max_tokens
    if backend_name is not None:
        rec["backend"] = backend_name
    return rec


def _emit(record, log_path):
    """Schema-validate, then persist the record. Raises on an invalid record
    rather than writing a malformed line."""
    _VALIDATOR.validate(record)
    if log_path is None:
        MEMORY_LOG.append(record)
    else:
        # Ensure the log dir exists. Experiment loop_bridge / replication_driver
        # modules set LOOP_V0_CALLS_LOG to <exp>/runs/calls.jsonl at IMPORT time
        # but only mkdir it inside their main(); when autoresearch imports them
        # the env var leaks process-wide and the dir may be absent, which would
        # fail every call_sync (root cause of the 2026-06-19 experiment-grounded
        # chain stalls: hypothesize/novelty/critic all FileNotFoundError'd).
        p = Path(log_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a") as fh:
            fh.write(json.dumps(record) + "\n")
    return record


def call_sync(messages, *, temperature=0.0, top_p=1.0, seed=None, max_tokens=None,
              caller_tag="unspecified", parent_request_id=None,
              retrieval_context=None, log_path=None, model=None, backend=None):
    """Synchronous chat completion. Returns the logged record. max_tokens caps
    generation; it is a request param, not one of the 14 logged schema fields.

    retrieval_context: see _record. Default None -> field absent from record.
    backend: backend registry name (e.g. "vllm-gemma", "ollama-coder",
        "anthropic"). Default None -> DEFAULT_BACKEND env, falling back to
        "vllm-gemma" so existing callers are unaffected.
    """
    be = get_backend(backend or DEFAULT_BACKEND)
    params = {"temperature": temperature, "top_p": top_p, "seed": seed}
    t0 = time.perf_counter()
    resp = be.create_chat(
        model=model or be.default_model, messages=messages,
        max_tokens=max_tokens, **params)
    latency_ms = (time.perf_counter() - t0) * 1000.0
    rec = _emit(_record(messages, params, resp, latency_ms,
                        caller_tag, parent_request_id,
                        retrieval_context=retrieval_context,
                        model_version=be.model_version,
                        host_metadata=be.host_metadata,
                        max_tokens=max_tokens,
                        backend_name=be.name), log_path)
    # Per-call UI inference-internals row (best-effort; never raises).
    worker_activity.emit_worker_activity(
        run_id=get_run_id(),
        task_id=caller_tag,
        output_tokens=rec["usage"]["output_tokens"],
        max_tokens=max_tokens if max_tokens is not None else rec["usage"]["output_tokens"],
        latency_ms=latency_ms,
        timestamp=rec["timestamp"],
        backend=be.name,
        model=rec["model"],
    )
    return rec


async def call_async(messages, *, temperature=0.0, top_p=1.0, seed=None, max_tokens=None,
                     caller_tag="unspecified", parent_request_id=None,
                     retrieval_context=None, log_path=None, model=None,
                     backend=None):
    """Async chat completion (needed for OpenClaw on Day 6). Returns the record."""
    be = get_backend(backend or DEFAULT_BACKEND)
    params = {"temperature": temperature, "top_p": top_p, "seed": seed}
    t0 = time.perf_counter()
    resp = await be.create_chat_async(
        model=model or be.default_model, messages=messages,
        max_tokens=max_tokens, **params)
    latency_ms = (time.perf_counter() - t0) * 1000.0
    rec = _emit(_record(messages, params, resp, latency_ms,
                        caller_tag, parent_request_id,
                        retrieval_context=retrieval_context,
                        model_version=be.model_version,
                        host_metadata=be.host_metadata,
                        max_tokens=max_tokens,
                        backend_name=be.name), log_path)
    # Per-call UI inference-internals row (best-effort; never raises).
    # Parity with call_sync — this path was a worker-activity blind spot
    # until 2026-06-10.
    worker_activity.emit_worker_activity(
        run_id=get_run_id(),
        task_id=caller_tag,
        output_tokens=rec["usage"]["output_tokens"],
        max_tokens=max_tokens if max_tokens is not None else rec["usage"]["output_tokens"],
        latency_ms=latency_ms,
        timestamp=rec["timestamp"],
        backend=be.name,
        model=rec["model"],
    )
    return rec


_DEFAULT_MAX_TOOL_DEPTH = 3


class ToolCallError(RuntimeError):
    """Raised when a model-emitted tool_calls.arguments string fails JSON
    parse or fails schema validation against the tool's declared parameters,
    or when the model hallucinates a tool name, or when max_depth is reached
    without a final answer. By design we do NOT silently retry: the program
    must see failure rates first."""


def _index_tools(tools):
    """tools is [{"spec": <openai-function-schema>, "impl": <callable>}, ...].
    Returns {name -> {"spec", "impl", "validator"}}."""
    out = {}
    for entry in tools:
        spec = entry["spec"]
        name = spec["function"]["name"]
        params_schema = spec["function"].get("parameters", {"type": "object"})
        out[name] = {
            "spec": spec,
            "impl": entry["impl"],
            "validator": jsonschema.Draft202012Validator(params_schema),
        }
    return out


def _serialize_tool_calls(tool_calls):
    """OpenAI ChatCompletionMessageToolCall objects -> stable JSON string."""
    return json.dumps([
        {"id": tc.id, "type": tc.type,
         "function": {"name": tc.function.name,
                      "arguments": tc.function.arguments}}
        for tc in tool_calls
    ])


def _project_for_log(messages):
    """Project OpenAI-shaped messages to the call schema's {role, content}
    pair shape. Assistant turns that carry tool_calls serialize them into
    content (as JSON); tool-result turns keep their string content.

    tool_calls may be SDK objects (first time round, straight from the API)
    OR plain dicts (after we re-stage them onto openai_messages for the next
    request). The dict branch is production today; the SDK-object branch is
    exercised by mocks but is real — do not remove."""
    out = []
    for m in messages:
        role = m["role"]
        if role == "assistant" and m.get("tool_calls"):
            content = _serialize_tool_calls(m["tool_calls"]) \
                if not isinstance(m["tool_calls"][0], dict) \
                else json.dumps(m["tool_calls"])
        else:
            content = m.get("content") or ""
        out.append({"role": role, "content": content})
    return out


def call_with_tools(messages, tools, *, temperature=0.0, top_p=1.0, seed=None,
                    max_tokens=None, caller_tag="call_with_tools",
                    parent_request_id=None, retrieval_context=None,
                    log_path=None, model=None, backend=None,
                    max_depth=_DEFAULT_MAX_TOOL_DEPTH):
    """Multi-turn tool-call loop. Returns the list of recorded chain calls.

    tools: list of {"spec": <openai-function-schema>, "impl": <callable>}.
    max_depth: maximum number of tool-emitting turns (>=1). The final
        non-tool-emitting turn is always permitted on top, so the chain has
        at most max_depth+1 records.
    backend: backend registry name; None -> DEFAULT_BACKEND.

    Each turn:
      1. Send the current message stack with the `tools` parameter.
      2. Log one record (linked via parent_request_id to the previous turn).
      3. If the response carries no tool_calls -> return.
      4. Else: schema-validate each tool_calls.arguments, execute the tool,
         append a role:"tool" message with the JSON-serialized result, recur.

    Raises ToolCallError on malformed tool args, unknown tool names, or
    max_depth exhaustion. NO silent retry on Day 1 of tool calling.
    """
    if max_depth < 1:
        raise ValueError(f"max_depth must be >= 1, got {max_depth}")
    be = get_backend(backend or DEFAULT_BACKEND)
    tool_index = _index_tools(tools)
    tool_specs = [t["spec"] for t in tools]
    openai_messages = [dict(m) for m in messages]
    records = []
    last_id = parent_request_id
    params = {"temperature": temperature, "top_p": top_p, "seed": seed}

    for depth in range(max_depth + 1):
        t0 = time.perf_counter()
        resp = be.create_chat(
            model=model or be.default_model,
            messages=openai_messages,
            tools=tool_specs,
            max_tokens=max_tokens,
            **params,
        )
        latency_ms = (time.perf_counter() - t0) * 1000.0

        msg = resp.choices[0].message
        text_content = msg.content or ""
        tool_calls = list(msg.tool_calls or [])

        completion_for_log = (
            _serialize_tool_calls(tool_calls) if tool_calls else text_content
        )

        record = {
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "request_id": str(uuid.uuid4()),
            "model": resp.model,
            "model_version": be.model_version,
            "temperature": params["temperature"],
            "top_p": params["top_p"],
            "seed": params["seed"],
            "prompt_messages": _project_for_log(openai_messages),
            "completion": completion_for_log,
            "usage": {
                "input_tokens": resp.usage.prompt_tokens,
                "output_tokens": resp.usage.completion_tokens,
            },
            "latency_ms": latency_ms,
            "host_metadata": dict(be.host_metadata),
            "caller_tag": caller_tag,
            "parent_request_id": last_id,
        }
        if retrieval_context is not None:
            record["retrieval_context"] = retrieval_context
        run_id = get_run_id()
        if run_id is not None:
            record["run_id"] = run_id
        if max_tokens is not None:
            record["max_tokens"] = max_tokens
        record["backend"] = be.name
        _emit(record, log_path)
        records.append(record)
        last_id = record["request_id"]
        # Per-call UI inference-internals row (best-effort; never raises).
        worker_activity.emit_worker_activity(
            run_id=run_id,
            task_id=caller_tag,
            output_tokens=record["usage"]["output_tokens"],
            max_tokens=(max_tokens if max_tokens is not None
                        else record["usage"]["output_tokens"]),
            latency_ms=latency_ms,
            timestamp=record["timestamp"],
            backend=be.name,
            model=record["model"],
        )

        if not tool_calls:
            return records

        # Stage the assistant turn (with tool_calls) for the next OpenAI request.
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

        # Execute each tool_call. Surface every failure mode.
        for tc in tool_calls:
            name = tc.function.name
            raw_args = tc.function.arguments
            if name not in tool_index:
                raise ToolCallError(
                    f"model hallucinated tool name {name!r}; "
                    f"known tools: {sorted(tool_index)}")
            try:
                args = json.loads(raw_args)
            except json.JSONDecodeError as exc:
                raise ToolCallError(
                    f"malformed JSON in tool_calls[{name}].arguments "
                    f"(request_id={record['request_id']}): {exc}; "
                    f"raw={raw_args!r}") from exc
            errs = list(tool_index[name]["validator"].iter_errors(args))
            if errs:
                raise ToolCallError(
                    f"tool {name} arguments failed schema validation "
                    f"(request_id={record['request_id']}): {errs[0].message}; "
                    f"args={args!r}")
            result = tool_index[name]["impl"](**args)
            openai_messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result),
            })

    raise ToolCallError(
        f"reached max_depth={max_depth} without a final answer; "
        f"last record: {records[-1]['request_id']}")


def verify_log_integrity(path):
    """Read a JSONL log back and return the count of malformed lines -- a line
    that is not valid JSON, or is valid JSON that fails the call schema.
    0 means every line is a well-formed call record."""
    malformed = 0
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                _VALIDATOR.validate(json.loads(line))
            except (json.JSONDecodeError, jsonschema.ValidationError):
                malformed += 1
    return malformed
