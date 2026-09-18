"""Direct, evidence-preserving client for the registered warm Mia candidate.

The endpoint is derived from a code-owned :class:`CandidateSpec`; callers
cannot provide a URL.  Streaming keeps reasoning, final, tool, timing and usage
channels separate.  The CLI is deliberately small and writes the exact request
bytes and SSE bytes for local diagnostics.
"""
from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import math
import os
import stat
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .candidate_registry import CandidateSpec
from .followon_profiles import (
    MIA_MTP3_REDUCED47K_OPT,
    is_registered_spec,
)
from .personal_tasks import RequestPolicy, get_policy
from .transport import (
    MAX_RESPONSE_BYTES,
    LocalEndpoint,
    StreamAccumulator,
    TransportError,
    canonical,
    request_body,
)

CLIENT_SCHEMA = "flash-personal-client/v1"
MAX_PROMPT_BYTES = 1024 * 1024
REPETITION_MIN_BLOCK_CHARS = 512
REPETITION_MAX_BLOCK_CHARS = 4096
REPETITION_COPIES = 3


class RepetitionAborted(RuntimeError):
    """Generation ended because one long block repeated exactly three times."""


def endpoint_for_candidate(candidate: CandidateSpec) -> LocalEndpoint:
    """Resolve only an object-identity registered Mia specification."""
    if not isinstance(candidate, CandidateSpec) or not is_registered_spec(candidate):
        raise ValueError("personal client requires a registered CandidateSpec object")
    endpoint = LocalEndpoint(
        name=candidate.endpoint_name,
        base_url=f"http://127.0.0.1:{candidate.host_port}/v1",
        served_model=candidate.served_name,
        artifact_sha256=candidate.model_artifact_sha256(),
    )
    endpoint.validate()
    return endpoint


def build_request(
    candidate: CandidateSpec,
    messages: list[dict[str, Any]],
    policy: RequestPolicy,
    *,
    seed: int,
    max_output_tokens: int | None = None,
    tools: list[dict[str, Any]] | None = None,
    logprobs: bool = False,
    top_logprobs: int | None = None,
) -> tuple[LocalEndpoint, dict[str, Any], bytes]:
    endpoint = endpoint_for_candidate(candidate)
    if not isinstance(policy, RequestPolicy):
        raise TypeError("policy must be a RequestPolicy")
    budget = policy.max_output_tokens if max_output_tokens is None else max_output_tokens
    if (
        isinstance(budget, bool)
        or not isinstance(budget, int)
        or not 1 <= budget <= policy.max_output_tokens
    ):
        raise ValueError("output budget exceeds its selected policy ceiling")
    if not isinstance(logprobs, bool):
        raise TypeError("logprobs must be boolean")
    if top_logprobs is not None and (
        isinstance(top_logprobs, bool)
        or not isinstance(top_logprobs, int)
        or not 0 <= top_logprobs <= 20
    ):
        raise ValueError("top_logprobs must be an integer in 0..20")
    if top_logprobs is not None and not logprobs:
        raise ValueError("top_logprobs requires logprobs")
    body = request_body(
        endpoint,
        messages,
        policy.inference_policy(),
        budget,
        seed,
        tools,
    )
    if logprobs:
        body["logprobs"] = True
        if top_logprobs is not None:
            body["top_logprobs"] = top_logprobs
    raw = canonical(body)
    return endpoint, body, raw


class TimedAccumulator(StreamAccumulator):
    """Add first-channel timings without changing the strict SSE parser."""

    def __init__(self, expected_model: str, *, started: float, clock: Callable[[], float]):
        super().__init__(expected_model)
        self.started = started
        self.clock = clock
        self.first_response_s: float | None = None
        self.first_reasoning_s: float | None = None
        self.first_final_s: float | None = None
        self.first_tool_s: float | None = None
        self.channel_order: list[str] = []

    def accept(self, data: str) -> bool:
        before = (
            len(self.reasoning),
            len(self.content),
            sum(
                len(call["id"])
                + len(call["function"]["name"])
                + len(call["function"]["arguments"])
                for call in self.tools.values()
            ),
        )
        generated = super().accept(data)
        if data == "[DONE]":
            return generated
        observed = max(0.0, self.clock() - self.started)
        if self.first_response_s is None:
            self.first_response_s = observed
        reasoning_new = any(
            self.reasoning[index] for index in range(before[0], len(self.reasoning))
        )
        final_new = any(self.content[index] for index in range(before[1], len(self.content)))
        tool_chars = sum(
            len(call["id"])
            + len(call["function"]["name"])
            + len(call["function"]["arguments"])
            for call in self.tools.values()
        )
        tool_new = tool_chars > before[2]
        simultaneous_first = (
            reasoning_new
            and final_new
            and self.first_reasoning_s is None
            and self.first_final_s is None
        )
        if simultaneous_first:
            self.first_reasoning_s = observed
            self.first_final_s = observed
            self.channel_order.append("reasoning+final")
        else:
            if reasoning_new and self.first_reasoning_s is None:
                self.first_reasoning_s = observed
                self.channel_order.append("reasoning")
            if final_new and self.first_final_s is None:
                self.first_final_s = observed
                self.channel_order.append("final")
        if tool_new and self.first_tool_s is None:
            self.first_tool_s = observed
            self.channel_order.append("tool")
        return generated

    def timing(self) -> dict[str, Any]:
        generated = [
            value for value in (
                self.first_reasoning_s, self.first_final_s, self.first_tool_s,
            ) if value is not None
        ]
        if self.first_reasoning_s is not None and self.first_final_s is not None:
            if self.first_reasoning_s < self.first_final_s:
                first_channel = "reasoning_first"
            elif self.first_final_s < self.first_reasoning_s:
                first_channel = "final_first"
            else:
                first_channel = "simultaneous"
        elif self.first_reasoning_s is not None:
            first_channel = "reasoning_only"
        elif self.first_final_s is not None:
            first_channel = "final_only"
        elif self.first_tool_s is not None:
            first_channel = "tool_only"
        else:
            first_channel = "none"
        return {
            "first_response_s": self.first_response_s,
            "first_reasoning_s": self.first_reasoning_s,
            "first_final_s": self.first_final_s,
            "first_tool_s": self.first_tool_s,
            "ttft_s": min(generated) if generated else None,
            "first_channel": first_channel,
            "channel_order": list(self.channel_order),
        }


class ExactRepetitionGuard:
    """Conservative suffix guard; short phrases and nonexact loops are ignored."""

    def __init__(self) -> None:
        self._checked_lengths = {"reasoning": 0, "final": 0, "tool": 0}

    @staticmethod
    def _repeated_suffix(text: str) -> int | None:
        length = len(text)
        if length < REPETITION_MIN_BLOCK_CHARS * REPETITION_COPIES:
            return None
        anchor = text[-REPETITION_MIN_BLOCK_CHARS:]
        search_end = length - REPETITION_MIN_BLOCK_CHARS
        candidates = 0
        while search_end > 0 and candidates < 64:
            position = text.rfind(anchor, max(0, length - 3 * REPETITION_MAX_BLOCK_CHARS), search_end)
            if position < 0:
                return None
            period = length - REPETITION_MIN_BLOCK_CHARS - position
            if (
                REPETITION_MIN_BLOCK_CHARS <= period <= REPETITION_MAX_BLOCK_CHARS
                and length >= period * REPETITION_COPIES
            ):
                block = text[-period:]
                if all(
                    text[-period * copy:-period * (copy - 1) if copy > 1 else None] == block
                    for copy in range(2, REPETITION_COPIES + 1)
                ):
                    return period
            search_end = position
            candidates += 1
        return None

    def observe(self, accumulator: TimedAccumulator) -> None:
        channels = {
            "reasoning": "".join(accumulator.reasoning),
            "final": "".join(accumulator.content),
            "tool": "".join(
                call["function"]["arguments"]
                for _, call in sorted(accumulator.tools.items())
            ),
        }
        for channel, value in channels.items():
            if len(value) - self._checked_lengths[channel] < 128:
                continue
            self._checked_lengths[channel] = len(value)
            period = self._repeated_suffix(value)
            if period is not None:
                raise RepetitionAborted(
                    f"{channel} repeated an exact {period}-character block "
                    f"{REPETITION_COPIES} times"
                )


@dataclass(frozen=True, slots=True)
class TurnResult:
    classification: str
    content: str
    reasoning_content: str
    tool_calls: tuple[dict[str, Any], ...]
    usage: dict[str, Any] | None
    finish_reason: str | None
    response_id: str | None
    response_model: str | None
    timing: dict[str, Any]
    elapsed_s: float
    request_body: dict[str, Any]
    request_bytes: bytes
    response_bytes: bytes
    error_type: str | None = None
    error: str | None = None

    @property
    def passed_transport(self) -> bool:
        return self.classification not in {"transport_error", "parser_error"}

    def receipt(self, *, include_channels: bool = True) -> dict[str, Any]:
        usage = self.usage
        row: dict[str, Any] = {
            "schema": CLIENT_SCHEMA,
            "classification": self.classification,
            "finish_reason": self.finish_reason,
            "response_id": self.response_id,
            "response_model": self.response_model,
            "usage": usage,
            "prompt_tokens": usage.get("prompt_tokens") if usage else None,
            "completion_tokens": usage.get("completion_tokens") if usage else None,
            "total_tokens": usage.get("total_tokens") if usage else None,
            "reasoning_tokens": (
                usage.get("completion_tokens_details", {}).get("reasoning_tokens")
                if usage and isinstance(usage.get("completion_tokens_details"), dict)
                else None
            ),
            "tool_call_count": len(self.tool_calls),
            "timing": self.timing,
            "elapsed_s": self.elapsed_s,
            "request_sha256": hashlib.sha256(self.request_bytes).hexdigest(),
            "request_bytes": len(self.request_bytes),
            "response_stream_sha256": hashlib.sha256(self.response_bytes).hexdigest(),
            "response_stream_bytes": len(self.response_bytes),
            "error_type": self.error_type,
            "error": self.error,
        }
        if include_channels:
            row.update({
                "content": self.content,
                "reasoning_content": self.reasoning_content,
                "tool_calls": list(self.tool_calls),
            })
        return row


def _remaining(deadline: float, clock: Callable[[], float]) -> float:
    value = deadline - clock()
    if value <= 0:
        raise TimeoutError("personal request exceeded its deadline")
    return max(0.001, value)


def _sse_data(line: bytes) -> str | None:
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


def _failure_result(
    classification: str,
    *,
    accumulator: TimedAccumulator,
    started: float,
    clock: Callable[[], float],
    body: dict[str, Any],
    request_bytes: bytes,
    response_bytes: bytes,
    error: BaseException,
) -> TurnResult:
    return TurnResult(
        classification=classification,
        content="".join(accumulator.content),
        reasoning_content="".join(accumulator.reasoning),
        tool_calls=tuple(accumulator.tools[key] for key in sorted(accumulator.tools)),
        usage=accumulator.usage,
        finish_reason=accumulator.finish_reason,
        response_id=accumulator.response_id,
        response_model=accumulator.expected_model if accumulator.has_model else None,
        timing=accumulator.timing(),
        elapsed_s=max(0.0, clock() - started),
        request_body=body,
        request_bytes=request_bytes,
        response_bytes=response_bytes,
        error_type=type(error).__name__,
        error=str(error),
    )


def _successful_classification(result: dict[str, Any]) -> str:
    finish = result["finish_reason"]
    tools = result["tool_calls"]
    content = result["content"]
    if tools:
        if finish != "tool_calls" or any(
            not call.get("id")
            or call.get("type") != "function"
            or not call.get("function", {}).get("name")
            for call in tools
        ):
            raise TransportError("completed tool-call structure is malformed")
        return "tool_call"
    if finish == "tool_calls":
        raise TransportError("tool-call finish has no tool call")
    if finish in {"length", "content_filter"}:
        return "exhausted"
    if content.strip():
        return "completed"
    return "no_final"


def stream_chat(
    candidate: CandidateSpec,
    messages: list[dict[str, Any]],
    policy: RequestPolicy,
    *,
    seed: int,
    timeout_s: float | None = None,
    absolute_deadline: float | None = None,
    max_output_tokens: int | None = None,
    tools: list[dict[str, Any]] | None = None,
    logprobs: bool = False,
    top_logprobs: int | None = None,
    clock: Callable[[], float] = time.monotonic,
    connection_factory: Callable[..., Any] = http.client.HTTPConnection,
) -> TurnResult:
    """Make one streaming call and return protocol failures as explicit rows."""
    endpoint, body, raw_request = build_request(
        candidate,
        messages,
        policy,
        seed=seed,
        max_output_tokens=max_output_tokens,
        tools=tools,
        logprobs=logprobs,
        top_logprobs=top_logprobs,
    )
    request_timeout = policy.request_timeout_s if timeout_s is None else timeout_s
    if (
        isinstance(request_timeout, bool)
        or not isinstance(request_timeout, (int, float))
        or not math.isfinite(request_timeout)
        or not 0.001 <= request_timeout <= policy.request_timeout_s
    ):
        raise ValueError("request timeout exceeds its policy ceiling")
    started = clock()
    deadline = started + float(request_timeout)
    if absolute_deadline is not None:
        if not isinstance(absolute_deadline, (int, float)) or not math.isfinite(absolute_deadline):
            raise ValueError("absolute deadline must be finite")
        deadline = min(deadline, float(absolute_deadline))
    accumulator = TimedAccumulator(endpoint.served_model, started=started, clock=clock)
    repetition_guard = ExactRepetitionGuard()
    raw_response = bytearray()
    connection = None
    try:
        remaining = _remaining(deadline, clock)
        connection = connection_factory("127.0.0.1", endpoint.validate(), timeout=remaining)
        connection.connect()
        sock = getattr(connection, "sock", None)
        if sock is None:
            raise OSError("local endpoint connected without a socket")
        sock.settimeout(_remaining(deadline, clock))
        connection.request(
            "POST",
            "/v1/chat/completions",
            body=raw_request,
            headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        )
        sock.settimeout(_remaining(deadline, clock))
        response = connection.getresponse()
        if response.status != 200:
            raise OSError(f"local model returned HTTP {response.status}")
        media_type = response.getheader("Content-Type", "").split(";", 1)[0].strip().lower()
        if media_type != "text/event-stream":
            raise TransportError("response is not an SSE stream")
        buffer = b""
        while not accumulator.done:
            sock.settimeout(_remaining(deadline, clock))
            chunk = response.read1(65_536)
            if not chunk:
                if buffer:
                    payload = _sse_data(buffer.rstrip(b"\r"))
                    buffer = b""
                    if payload is not None:
                        accumulator.accept(payload)
                        repetition_guard.observe(accumulator)
                break
            if len(raw_response) + len(chunk) > MAX_RESPONSE_BYTES:
                raw_response.extend(chunk[: MAX_RESPONSE_BYTES - len(raw_response)])
                raise TransportError("stream exceeded response byte ceiling")
            raw_response.extend(chunk)
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                payload = _sse_data(line.rstrip(b"\r"))
                if payload is not None:
                    accumulator.accept(payload)
                    repetition_guard.observe(accumulator)
            if accumulator.done and buffer.strip(b"\r\n"):
                raise TransportError("bytes follow the terminal SSE marker")
        parsed = accumulator.result()
        classification = _successful_classification(parsed)
        return TurnResult(
            classification=classification,
            content=parsed["content"],
            reasoning_content=parsed["reasoning_content"],
            tool_calls=tuple(parsed["tool_calls"]),
            usage=parsed["usage"],
            finish_reason=parsed["finish_reason"],
            response_id=parsed["response_id"],
            response_model=parsed["response_model"],
            timing=accumulator.timing(),
            elapsed_s=max(0.0, clock() - started),
            request_body=body,
            request_bytes=raw_request,
            response_bytes=bytes(raw_response),
        )
    except RepetitionAborted as exc:
        return _failure_result(
            "repetition_aborted",
            accumulator=accumulator,
            started=started,
            clock=clock,
            body=body,
            request_bytes=raw_request,
            response_bytes=bytes(raw_response),
            error=exc,
        )
    except TransportError as exc:
        return _failure_result(
            "parser_error",
            accumulator=accumulator,
            started=started,
            clock=clock,
            body=body,
            request_bytes=raw_request,
            response_bytes=bytes(raw_response),
            error=exc,
        )
    except (OSError, TimeoutError, http.client.HTTPException) as exc:
        return _failure_result(
            "transport_error",
            accumulator=accumulator,
            started=started,
            clock=clock,
            body=body,
            request_bytes=raw_request,
            response_bytes=bytes(raw_response),
            error=exc,
        )
    finally:
        if connection is not None:
            try:
                connection.close()
            except OSError:
                pass


@dataclass(frozen=True, slots=True)
class ConversationResult:
    classification: str
    final_content: str
    history: tuple[dict[str, Any], ...]
    turns: tuple[TurnResult, ...]
    interventions: int
    elapsed_s: float
    error: str | None = None

    def receipt(self) -> dict[str, Any]:
        return {
            "schema": "flash-personal-conversation/v1",
            "classification": self.classification,
            "final_content": self.final_content,
            "turns": [turn.receipt() for turn in self.turns],
            "interventions": self.interventions,
            "elapsed_s": self.elapsed_s,
            "error": self.error,
        }


def _strict_arguments(raw: str) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate tool argument key")
            result[key] = value
        return result

    value = json.loads(
        raw,
        object_pairs_hook=unique,
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"non-finite tool argument: {value}")
        ),
    )
    if not isinstance(value, dict):
        raise TypeError("tool arguments are not an object")
    return value


def run_tool_loop(
    candidate: CandidateSpec,
    messages: list[dict[str, Any]],
    policy: RequestPolicy,
    *,
    tools: list[dict[str, Any]],
    execute_tool: Callable[[str, dict[str, Any]], Any],
    seed: int,
    invoke: Callable[..., TurnResult] = stream_chat,
    clock: Callable[[], float] = time.monotonic,
) -> ConversationResult:
    """Run bounded function turns, preserving assistant reasoning in history."""
    if not isinstance(messages, list) or not messages:
        raise ValueError("conversation needs messages")
    history = [dict(message) for message in messages]
    turns: list[TurnResult] = []
    started = clock()
    deadline = started + policy.task_deadline_s
    interventions = 0
    for turn_index in range(policy.max_turns):
        if clock() >= deadline:
            return ConversationResult(
                "exhausted", "", tuple(history), tuple(turns), interventions,
                max(0.0, clock() - started), "task deadline reached",
            )
        turn = invoke(
            candidate,
            history,
            policy,
            seed=seed + turn_index,
            timeout_s=min(policy.request_timeout_s, max(0.001, deadline - clock())),
            absolute_deadline=deadline,
            tools=tools,
        )
        turns.append(turn)
        if turn.classification == "completed":
            history.append({
                "role": "assistant",
                "content": turn.content,
                **(
                    {"reasoning_content": turn.reasoning_content}
                    if turn.reasoning_content else {}
                ),
            })
            return ConversationResult(
                "completed", turn.content, tuple(history), tuple(turns), interventions,
                max(0.0, clock() - started),
            )
        if turn.classification != "tool_call":
            return ConversationResult(
                turn.classification, turn.content, tuple(history), tuple(turns),
                interventions, max(0.0, clock() - started), turn.error,
            )
        assistant: dict[str, Any] = {
            "role": "assistant",
            "content": turn.content or None,
            "tool_calls": list(turn.tool_calls),
        }
        if turn.reasoning_content:
            assistant["reasoning_content"] = turn.reasoning_content
        history.append(assistant)
        seen_ids: set[str] = set()
        for call in turn.tool_calls:
            call_id = call["id"]
            function = call["function"]
            if call_id in seen_ids:
                return ConversationResult(
                    "parser_error", "", tuple(history), tuple(turns), interventions,
                    max(0.0, clock() - started), "duplicate tool call identifier",
                )
            seen_ids.add(call_id)
            try:
                arguments = _strict_arguments(function["arguments"])
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                return ConversationResult(
                    "parser_error", "", tuple(history), tuple(turns), interventions,
                    max(0.0, clock() - started), str(exc),
                )
            interventions += 1
            try:
                value = execute_tool(function["name"], arguments)
                payload = value if isinstance(value, str) else json.dumps(
                    value, sort_keys=True, separators=(",", ":"), allow_nan=False,
                )
            except Exception as exc:  # noqa: BLE001 - tool error becomes model-visible data
                payload = json.dumps({
                    "error": type(exc).__name__, "message": str(exc),
                }, sort_keys=True, separators=(",", ":"))
            history.append({
                "role": "tool", "tool_call_id": call_id, "content": payload,
            })
    return ConversationResult(
        "exhausted", "", tuple(history), tuple(turns), interventions,
        max(0.0, clock() - started), "turn ceiling reached",
    )


def _read_prompt(path: str | Path) -> str:
    prompt_path = Path(path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(prompt_path, flags)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_PROMPT_BYTES:
            raise ValueError("prompt file must be a nonempty bounded regular file")
        raw = os.read(descriptor, MAX_PROMPT_BYTES + 1)
        if len(raw) != info.st_size:
            raise ValueError("prompt file changed during read")
    finally:
        os.close(descriptor)
    return raw.decode("utf-8", errors="strict")


def _output_dir(path: str | Path) -> Path:
    output = Path(path)
    if output.exists():
        if output.is_symlink() or not output.is_dir() or any(output.iterdir()):
            raise ValueError("output directory must be absent or empty")
    else:
        output.mkdir(mode=0o700, parents=True)
    output.chmod(0o700)
    return output.resolve(strict=True)


def _write_new(path: Path, raw: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        offset = 0
        while offset < len(raw):
            offset += os.write(descriptor, raw[offset:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Call the registered warm Mia endpoint")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--prompt")
    source.add_argument("--prompt-file")
    parser.add_argument("--policy", choices=("off", "medium"), required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--system", default="You are a precise and practical assistant.")
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--vary-seed", action="store_true")
    parser.add_argument("--max-output-tokens", type=int)
    parser.add_argument("--logprobs", action="store_true")
    parser.add_argument("--top-logprobs", type=int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not 1 <= args.repeat <= 20:
        raise SystemExit("--repeat must be in 1..20")
    prompt = args.prompt if args.prompt is not None else _read_prompt(args.prompt_file)
    if not prompt.strip() or len(prompt.encode()) > MAX_PROMPT_BYTES:
        raise SystemExit("prompt must be nonempty and at most 1 MiB")
    policy = get_policy(args.policy)
    output = _output_dir(args.output_dir)
    messages = [
        {"role": "system", "content": args.system},
        {"role": "user", "content": prompt},
    ]
    receipts: list[dict[str, Any]] = []
    for index in range(args.repeat):
        attempt = output / f"attempt-{index + 1:03d}"
        attempt.mkdir(mode=0o700)
        seed = args.seed + index if args.vary_seed else args.seed
        result = stream_chat(
            MIA_MTP3_REDUCED47K_OPT,
            messages,
            policy,
            seed=seed,
            max_output_tokens=args.max_output_tokens,
            logprobs=args.logprobs,
            top_logprobs=args.top_logprobs,
        )
        _write_new(attempt / "request.json", result.request_bytes)
        _write_new(attempt / "response.sse", result.response_bytes)
        receipt = {"attempt": index + 1, "seed": seed, **result.receipt()}
        _write_new(
            attempt / "result.json",
            (json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n").encode(),
        )
        receipts.append(receipt)
    summary = {
        "schema": "flash-personal-cli-run/v1",
        # The shared response route proves checkpoint identity, not which
        # registered launch profile the owner currently has active.
        "requested_candidate_spec_id": MIA_MTP3_REDUCED47K_OPT.spec_id,
        "runtime_profile_verified": False,
        "policy": args.policy,
        "attempts": receipts,
    }
    _write_new(
        output / "summary.json",
        (json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n").encode(),
    )
    print(json.dumps({
        "output_dir": str(output),
        "classifications": [row["classification"] for row in receipts],
        "first_channels": [row["timing"]["first_channel"] for row in receipts],
    }, sort_keys=True))
    return 0 if all(row["classification"] == "completed" for row in receipts) else 2


if __name__ == "__main__":
    raise SystemExit(main())
