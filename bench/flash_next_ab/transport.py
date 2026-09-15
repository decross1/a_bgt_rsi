"""Evaluation-only streaming transport for the three declared local endpoints.

No backend aliases, production wrapper changes, API keys, retries or log writes.
The caller owns the hardware reservation and independent process deadline.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import math
import os
import socket
import threading
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

_ENDPOINTS = {
    "resident_gemma": (8000, "gemma-4-26b-a4b"),
    "resident_qwen": (8001, "qwen3.8-27b-nvfp4-mtp"),
    "flash_next": (8012, "qwen3.8-flash-next"),
}
MAX_RESPONSE_BYTES = 8 * 1024 * 1024


class TransportError(RuntimeError):
    """A failed or incomplete call; never a successful empty response."""


class TransportCancelled(TransportError):
    """The caller canceled an in-flight local evaluation request."""


@dataclass(frozen=True)
class LocalEndpoint:
    name: str
    base_url: str
    served_model: str
    artifact_sha256: str

    def validate(self) -> int:
        parsed = urlsplit(self.base_url)
        if self.name not in _ENDPOINTS:
            raise ValueError("undeclared evaluation endpoint")
        port, model = _ENDPOINTS[self.name]
        if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1"
                or parsed.port != port or parsed.path not in ("", "/v1")
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or self.served_model != model):
            raise ValueError("endpoint identity differs from the local allowlist")
        if (len(self.artifact_sha256) != 64
                or any(c not in "0123456789abcdef" for c in self.artifact_sha256)):
            raise ValueError("endpoint requires an immutable artifact SHA-256")
        return port


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _strict_json(value: str) -> Any:
    def unique_object(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("duplicate streaming JSON key")
            result[key] = item
        return result

    def invalid_constant(_value):
        raise ValueError("non-finite streaming JSON value")

    return json.loads(
        value,
        object_pairs_hook=unique_object,
        parse_constant=invalid_constant,
    )


def _number(value, name, low, high):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or not low <= value <= high):
        raise ValueError(f"{name} is outside its declared range")


def request_body(endpoint, messages, policy, max_tokens, seed, tools=None):
    endpoint.validate()
    if not isinstance(messages, list) or not messages:
        raise ValueError("messages must be nonempty")
    if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or not 1 <= max_tokens <= 32768:
        raise ValueError("output budget must be an integer in 1..32768")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError("seed must be an integer")
    if not isinstance(policy, dict) or set(policy) - {
        "temperature", "top_p", "top_k", "min_p", "presence_penalty",
        "repetition_penalty", "reasoning_effort", "enable_thinking", "preserve_thinking",
    }:
        raise ValueError("unsupported inference policy fields")
    if not {"temperature", "top_p"} <= set(policy):
        raise ValueError("temperature and top_p must be explicit")
    _number(policy["temperature"], "temperature", 0, 2)
    _number(policy["top_p"], "top_p", 0, 1)
    body = {
        "model": endpoint.served_model, "messages": messages,
        "max_tokens": max_tokens, "seed": seed, "stream": True,
        "stream_options": {"include_usage": True},
        "temperature": policy["temperature"], "top_p": policy["top_p"],
    }
    for key, bounds in {"top_k": (0, 10000), "min_p": (0, 1),
                        "presence_penalty": (-2, 2), "repetition_penalty": (0.01, 2)}.items():
        if key in policy:
            _number(policy[key], key, *bounds)
            if key == "top_k" and not isinstance(policy[key], int):
                raise ValueError("top_k must be integral")
            body[key] = policy[key]
    template = {}
    for key in ("enable_thinking", "preserve_thinking"):
        if key in policy:
            if not isinstance(policy[key], bool):
                raise ValueError(f"{key} must be boolean")
            template[key] = policy[key]
    if "reasoning_effort" in policy:
        effort = policy["reasoning_effort"]
        if endpoint.name == "resident_gemma" or effort not in {"low", "medium", "xhigh"}:
            raise ValueError("reasoning effort unsupported for endpoint")
        body["reasoning_effort"] = effort
        # Preserve the exact Qwen chat-template control as well as API metadata.
        template["reasoning_effort"] = effort
    if template:
        body["chat_template_kwargs"] = template
    if tools is not None:
        if not isinstance(tools, list) or not tools:
            raise ValueError("tools must be a nonempty list when supplied")
        body["tools"] = tools
        body["tool_choice"] = "auto"
    canonical(body)
    return body


class StreamAccumulator:
    def __init__(self, expected_model):
        self.expected_model = expected_model
        self.content = []
        self.reasoning = []
        self.tools = {}
        self.usage = None
        self.finish_reason = None
        self.response_id = None
        self.done = False
        self.has_model = False
        self.events = 0

    def accept(self, data):
        if self.done:
            raise TransportError("data after terminal stream marker")
        if data == "[DONE]":
            self.done = True
            return False
        try:
            obj = _strict_json(data)
        except (ValueError, TypeError) as exc:
            raise TransportError("malformed streaming JSON") from exc
        if not isinstance(obj, dict) or obj.get("error") is not None:
            raise TransportError("server returned a streaming error")
        if obj.get("model") != self.expected_model:
            raise TransportError("response model identity drift")
        self.has_model = True
        response_id = obj.get("id")
        if not isinstance(response_id, str) or not response_id:
            raise TransportError("response identifier is absent or invalid")
        if self.response_id is not None and response_id != self.response_id:
            raise TransportError("response identifier drift")
        self.response_id = response_id
        choices = obj.get("choices")
        if not isinstance(choices, list) or len(choices) > 1:
            raise TransportError("expected one generation stream")
        if self.finish_reason is not None and choices:
            raise TransportError("choice data after terminal choice")
        generated = False
        for choice in choices:
            if not isinstance(choice, dict) or choice.get("index") != 0:
                raise TransportError("invalid stream choice")
            delta = choice.get("delta", {})
            if not isinstance(delta, dict):
                raise TransportError("invalid stream delta")
            if (delta.get("reasoning_content") is not None
                    and delta.get("reasoning") is not None):
                raise TransportError("ambiguous reasoning delta aliases")
            for key, destination in (("content", self.content), ("reasoning_content", self.reasoning), ("reasoning", self.reasoning)):
                value = delta.get(key)
                if value is not None:
                    if not isinstance(value, str):
                        raise TransportError("non-text content delta")
                    destination.append(value)
                    generated = generated or bool(value)
            tool_calls = delta.get("tool_calls")
            if tool_calls is not None and not isinstance(tool_calls, list):
                raise TransportError("invalid tool delta collection")
            for call in tool_calls or []:
                if not isinstance(call, dict):
                    raise TransportError("invalid tool delta")
                index = call.get("index")
                if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < 64:
                    raise TransportError("invalid tool call index")
                target = self.tools.setdefault(index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                call_type = call.get("type")
                if call_type is not None and call_type != "function":
                    raise TransportError("unsupported tool call type")
                if "id" in call and call["id"] is not None:
                    call_id = call["id"]
                    if not isinstance(call_id, str) or not call_id:
                        raise TransportError("invalid tool identifier")
                    if target["id"] and call_id != target["id"]:
                        raise TransportError("tool identifier drift")
                    target["id"] = call_id
                function = call.get("function", {})
                if not isinstance(function, dict):
                    raise TransportError("invalid function delta")
                for key in ("name", "arguments"):
                    piece = function.get(key)
                    if piece is not None:
                        if not isinstance(piece, str):
                            raise TransportError("non-text tool delta")
                        target["function"][key] += piece
                        generated = generated or bool(piece)
            finish = choice.get("finish_reason")
            if finish is not None:
                if self.finish_reason is not None or finish not in {"stop", "length", "tool_calls", "content_filter"}:
                    raise TransportError("invalid or repeated terminal choice")
                self.finish_reason = finish
        if obj.get("usage") is not None:
            if self.usage is not None or self.finish_reason is None:
                raise TransportError("invalid or repeated token usage")
            usage = obj["usage"]
            if not isinstance(usage, dict):
                raise TransportError("invalid token usage")
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                value = usage.get(key)
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    raise TransportError("invalid token usage")
            if usage["total_tokens"] != (
                usage["prompt_tokens"] + usage["completion_tokens"]
            ):
                raise TransportError("inconsistent token usage")
            self.usage = usage
        self.events += 1
        return generated

    def result(self):
        if (not self.done or self.finish_reason is None or not self.has_model
                or self.usage is None or self.response_id is None):
            raise TransportError("incomplete response or missing model/usage provenance")
        return {"content": "".join(self.content), "reasoning_content": "".join(self.reasoning),
                "tool_calls": [self.tools[k] for k in sorted(self.tools)], "usage": self.usage,
                "finish_reason": self.finish_reason, "response_model": self.expected_model,
                "response_id": self.response_id, "stream_events": self.events}


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("model request exceeded its wall-clock deadline")
    return max(0.001, remaining)


def _is_cancelled(cancel_event) -> bool:
    return cancel_event is not None and bool(cancel_event.is_set())


def _raise_if_cancelled(cancel_event, observed=None) -> None:
    if _is_cancelled(cancel_event) or (observed is not None and observed.is_set()):
        raise TransportCancelled("model request canceled")


def _sse_data(line: bytes) -> str | None:
    """Return one OpenAI data payload; ignore ordinary SSE metadata/comments."""
    if not line or line.startswith(b":"):
        return None
    field, separator, value = line.partition(b":")
    if not separator or field != b"data":
        return None
    if value.startswith(b" "):
        value = value[1:]
    try:
        return value.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise TransportError("stream contains invalid UTF-8") from exc


def complete(
    endpoint,
    messages,
    *,
    policy,
    max_tokens,
    timeout_s,
    seed,
    tools=None,
    cancel_event=None,
):
    if os.environ.get("MOCK_LLM"):
        raise ValueError("live evaluation refuses MOCK_LLM")
    _number(timeout_s, "timeout_s", 0.001, 1200)
    if cancel_event is not None and not callable(getattr(cancel_event, "is_set", None)):
        raise TypeError("cancel_event must expose is_set()")
    _raise_if_cancelled(cancel_event)
    body = request_body(endpoint, messages, policy, max_tokens, seed, tools)
    raw = canonical(body)
    start = time.monotonic()
    deadline = start + timeout_s
    connection = http.client.HTTPConnection(
        "127.0.0.1", endpoint.validate(), timeout=_remaining(deadline),
    )
    accumulator = StreamAccumulator(endpoint.served_model)
    first_token = None
    digest = hashlib.sha256()
    total = 0
    buffer = b""
    stop_watcher = threading.Event()
    cancellation_observed = threading.Event()
    watcher = None
    if cancel_event is not None:
        def interrupt_on_cancel():
            while not stop_watcher.wait(0.01):
                if not _is_cancelled(cancel_event):
                    continue
                cancellation_observed.set()
                sock = connection.sock
                if sock is not None:
                    try:
                        sock.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                try:
                    connection.close()
                except OSError:
                    pass
                return

        watcher = threading.Thread(
            target=interrupt_on_cancel,
            name="flash-next-eval-cancel",
            daemon=True,
        )
        watcher.start()
    try:
        connection.connect()
        _raise_if_cancelled(cancel_event, cancellation_observed)
        sock = connection.sock
        if sock is None:
            raise TransportError("local endpoint connected without a socket")
        sock.settimeout(_remaining(deadline))
        connection.request("POST", "/v1/chat/completions", body=raw,
                           headers={"Content-Type": "application/json", "Accept": "text/event-stream"})
        _raise_if_cancelled(cancel_event, cancellation_observed)
        sock.settimeout(_remaining(deadline))
        response = connection.getresponse()
        _raise_if_cancelled(cancel_event, cancellation_observed)
        if response.status != 200:
            raise TransportError(f"model request failed with HTTP {response.status}")
        content_type = response.getheader("Content-Type", "").split(";", 1)[0]
        if content_type.strip().lower() != "text/event-stream":
            raise TransportError("expected a streaming response")
        while not accumulator.done:
            _raise_if_cancelled(cancel_event, cancellation_observed)
            sock.settimeout(_remaining(deadline))
            chunk = response.read1(65536)
            if not chunk:
                if buffer:
                    line = buffer.rstrip(b"\r")
                    buffer = b""
                    payload = _sse_data(line)
                    if payload is not None:
                        generated = accumulator.accept(payload)
                        if generated and first_token is None:
                            first_token = time.monotonic() - start
                break
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                raise TransportError("stream exceeded response byte ceiling")
            digest.update(chunk)
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                line = line.rstrip(b"\r")
                payload = _sse_data(line)
                if payload is not None:
                    generated = accumulator.accept(payload)
                    if generated and first_token is None:
                        first_token = time.monotonic() - start
            if accumulator.done and buffer.strip(b"\r\n"):
                raise TransportError("bytes after terminal stream marker")
        _raise_if_cancelled(cancel_event, cancellation_observed)
        result = accumulator.result()
    except TransportCancelled:
        raise
    except TransportError:
        raise
    except TimeoutError as exc:
        if _is_cancelled(cancel_event) or cancellation_observed.is_set():
            raise TransportCancelled("model request canceled") from exc
        raise TimeoutError("model request exceeded its wall-clock deadline") from exc
    except (OSError, http.client.HTTPException) as exc:
        if _is_cancelled(cancel_event) or cancellation_observed.is_set():
            raise TransportCancelled("model request canceled") from exc
        if time.monotonic() >= deadline:
            raise TimeoutError("model request exceeded its wall-clock deadline") from exc
        raise TransportError(
            f"local model transport failed: {type(exc).__name__}"
        ) from exc
    finally:
        stop_watcher.set()
        try:
            connection.close()
        except OSError:
            pass
        if watcher is not None:
            watcher.join(timeout=0.25)
    result.update({"latency_s": time.monotonic() - start, "ttft_s": first_token,
                   "request_sha256": hashlib.sha256(raw).hexdigest(),
                   "response_stream_sha256": digest.hexdigest(),
                   "endpoint": endpoint.__dict__, "resolved_request": body,
                   "response_bytes": total, "retries": 0})
    return result
