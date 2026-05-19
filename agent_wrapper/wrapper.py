"""
Thin wrapper around vLLM's OpenAI-compatible API. Every model call writes
exactly one schema-valid JSONL line (schema/calls.jsonl.schema.json).

Public interface:
  call_sync(messages, ...)   -> dict   the logged record
  call_async(messages, ...)  -> dict   the logged record  [coroutine]
  verify_log_integrity(path) -> int    count of malformed lines (0 == clean)

Two log modes (per call, via log_path):
  log_path=<file>  append-only  (production)
  log_path=None    in-memory    (tests) -- records collected in MEMORY_LOG

Config is read from the environment so the same code serves any host:
  VLLM_BASE_URL, VLLM_API_KEY, VLLM_MODEL, VLLM_MODEL_VERSION,
  VLLM_IMAGE_TAG, CUDA_DRIVER.

Day 4 adds: call_with_tools (max recursion depth 3).
"""
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import jsonschema
from openai import AsyncOpenAI, OpenAI

_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema" / "calls.jsonl.schema.json"
_VALIDATOR = jsonschema.Draft202012Validator(json.loads(_SCHEMA_PATH.read_text()))

BASE_URL = os.environ.get("VLLM_BASE_URL", "http://localhost:8000/v1")
MODEL = os.environ.get("VLLM_MODEL", "gemma-4-26b-a4b")  # served-model-name, not the -nvfp4 weights path
MODEL_VERSION = os.environ.get("VLLM_MODEL_VERSION", "unknown")
HOST_METADATA = {
    "cuda_driver": os.environ.get("CUDA_DRIVER", "13.0"),
    "vllm_image_tag": os.environ.get("VLLM_IMAGE_TAG", "vllm/vllm-openai:v0.20.0"),
}

# In-memory sink for tests (log_path=None). Cleared by callers as needed.
MEMORY_LOG = []

_sync_client = OpenAI(base_url=BASE_URL, api_key=os.environ.get("VLLM_API_KEY", "EMPTY"))
_async_client = AsyncOpenAI(base_url=BASE_URL, api_key=os.environ.get("VLLM_API_KEY", "EMPTY"))


def _record(messages, params, resp, latency_ms, caller_tag, parent_request_id):
    """Build a schema-conforming record from a chat-completion response."""
    return {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "request_id": str(uuid.uuid4()),
        "model": resp.model,
        "model_version": MODEL_VERSION,
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
        "host_metadata": dict(HOST_METADATA),
        "caller_tag": caller_tag,
        "parent_request_id": parent_request_id,
    }


def _emit(record, log_path):
    """Schema-validate, then persist the record. Raises on an invalid record
    rather than writing a malformed line."""
    _VALIDATOR.validate(record)
    if log_path is None:
        MEMORY_LOG.append(record)
    else:
        with open(log_path, "a") as fh:
            fh.write(json.dumps(record) + "\n")
    return record


def call_sync(messages, *, temperature=0.0, top_p=1.0, seed=None, max_tokens=None,
              caller_tag="unspecified", parent_request_id=None,
              log_path=None, model=None):
    """Synchronous chat completion. Returns the logged record. max_tokens caps
    generation; it is a request param, not one of the 14 logged schema fields."""
    params = {"temperature": temperature, "top_p": top_p, "seed": seed}
    t0 = time.perf_counter()
    resp = _sync_client.chat.completions.create(
        model=model or MODEL, messages=messages, max_tokens=max_tokens, **params)
    latency_ms = (time.perf_counter() - t0) * 1000.0
    return _emit(_record(messages, params, resp, latency_ms,
                         caller_tag, parent_request_id), log_path)


async def call_async(messages, *, temperature=0.0, top_p=1.0, seed=None, max_tokens=None,
                     caller_tag="unspecified", parent_request_id=None,
                     log_path=None, model=None):
    """Async chat completion (needed for OpenClaw on Day 6). Returns the record."""
    params = {"temperature": temperature, "top_p": top_p, "seed": seed}
    t0 = time.perf_counter()
    resp = await _async_client.chat.completions.create(
        model=model or MODEL, messages=messages, max_tokens=max_tokens, **params)
    latency_ms = (time.perf_counter() - t0) * 1000.0
    return _emit(_record(messages, params, resp, latency_ms,
                         caller_tag, parent_request_id), log_path)


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
