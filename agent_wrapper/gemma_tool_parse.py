"""Fallback parser for Gemma 4's inline tool-call markup.

vLLM's `--tool-call-parser gemma4` recognizes ONE of the two formats
Gemma 4 emits — the OpenAI-shaped `tool_calls` field in the response.
Stochastically (~50% of the time on long contexts), Gemma instead
emits a custom text-content format that the parser misses, e.g.::

    I will now classify the novelty of the hypothesis...

    <|tool_call>call:novelty_classify{hypothesis_text:<|"|>...<|"|>,neighbors:[{doc_id:<|"|>...<|"|>,score:0.6253,...}]}

When that happens, `msg.tool_calls` is None and the whole tool-call
ends up as a string blob in `msg.content`. This module parses that
blob back into OpenAI-shaped tool_call dicts the runtime can dispatch.

Caught on iter-010 (2026-05-26). Documented as the cause of the
chain-stall pattern; this is the bridging parser until either the
vLLM image is upgraded or Nara migrates off OpenAI tool_calls.

Format details:
  - Marker: ``<|tool_call>call:NAME{...}``
  - String values: delimited by ``<|"|>...<|"|>`` (NOT regular quotes)
  - Numbers: bare (``0.6253``)
  - Arrays: ``[...]``
  - Objects: ``{...}``
  - Keys: bare identifiers (NOT quoted)
  - Separator: ``,`` between fields/items
  - Booleans: ``true`` / ``false`` (seen rarely)
  - Null: ``null`` (seen rarely)
"""
from __future__ import annotations

import json
import uuid
from typing import Any


_TOOL_CALL_MARKER = "<|tool_call>call:"
_QUOTE = '<|"|>'


class GemmaToolCallParseError(ValueError):
    """Raised on malformed inline tool-call markup. Callers should fall
    back to the (now visible) failure mode, not silently swap content."""


def _skip_ws(text: str, pos: int) -> int:
    while pos < len(text) and text[pos] in " \t\n\r":
        pos += 1
    return pos


def _parse_string(text: str, pos: int) -> tuple[str, int]:
    """text[pos:pos+len(_QUOTE)] must be _QUOTE. Returns (string, end_pos)."""
    assert text.startswith(_QUOTE, pos), f"expected {_QUOTE!r} at {pos}"
    start = pos + len(_QUOTE)
    end = text.find(_QUOTE, start)
    if end < 0:
        raise GemmaToolCallParseError(
            f"unterminated string starting at position {pos}"
        )
    return text[start:end], end + len(_QUOTE)


def _parse_value(text: str, pos: int) -> tuple[Any, int]:
    """Parse a value starting at text[pos]. Returns (value, end_pos)."""
    pos = _skip_ws(text, pos)
    if pos >= len(text):
        raise GemmaToolCallParseError(f"unexpected end of input at {pos}")
    if text.startswith(_QUOTE, pos):
        return _parse_string(text, pos)
    if text[pos] == "[":
        return _parse_array(text, pos)
    if text[pos] == "{":
        return _parse_object(text, pos)
    # Bare token: number, true/false/null, or a stray identifier.
    end = pos
    while end < len(text) and text[end] not in ",]}":
        end += 1
    token = text[pos:end].strip()
    if not token:
        raise GemmaToolCallParseError(f"empty value at {pos}")
    if token == "true":
        return True, end
    if token == "false":
        return False, end
    if token == "null":
        return None, end
    # Try number.
    try:
        if "." in token or "e" in token.lower():
            return float(token), end
        return int(token), end
    except ValueError:
        # Last-resort: treat as a bare string. Less common but Gemma
        # sometimes drops the <|"|> wrap on short identifiers.
        return token, end


def _parse_array(text: str, pos: int) -> tuple[list, int]:
    """text[pos] must be '['. Returns (list, end_pos)."""
    assert text[pos] == "[", f"expected '[' at {pos}"
    out: list = []
    pos += 1
    pos = _skip_ws(text, pos)
    if pos < len(text) and text[pos] == "]":
        return out, pos + 1
    while pos < len(text):
        value, pos = _parse_value(text, pos)
        out.append(value)
        pos = _skip_ws(text, pos)
        if pos < len(text) and text[pos] == ",":
            pos += 1
            pos = _skip_ws(text, pos)
            continue
        if pos < len(text) and text[pos] == "]":
            return out, pos + 1
        raise GemmaToolCallParseError(
            f"expected ',' or ']' in array at {pos}"
        )
    raise GemmaToolCallParseError("unterminated array")


def _parse_key(text: str, pos: int) -> tuple[str, int]:
    """Parse a key (bare identifier until ':'). Tolerates _QUOTE-wrapped
    keys too, though Gemma typically emits them bare."""
    pos = _skip_ws(text, pos)
    if text.startswith(_QUOTE, pos):
        return _parse_string(text, pos)
    end = pos
    while end < len(text) and text[end] not in ":,}":
        end += 1
    if end >= len(text):
        raise GemmaToolCallParseError(f"missing ':' after key at {pos}")
    key = text[pos:end].strip()
    if not key:
        raise GemmaToolCallParseError(f"empty key at {pos}")
    return key, end


def _parse_object(text: str, pos: int) -> tuple[dict, int]:
    """text[pos] must be '{'. Returns (dict, end_pos)."""
    assert text[pos] == "{", f"expected '{{' at {pos}"
    obj: dict = {}
    pos += 1
    pos = _skip_ws(text, pos)
    if pos < len(text) and text[pos] == "}":
        return obj, pos + 1
    while pos < len(text):
        key, pos = _parse_key(text, pos)
        pos = _skip_ws(text, pos)
        if pos >= len(text) or text[pos] != ":":
            raise GemmaToolCallParseError(
                f"expected ':' after key {key!r} at {pos}"
            )
        pos += 1  # consume ':'
        value, pos = _parse_value(text, pos)
        obj[key] = value
        pos = _skip_ws(text, pos)
        if pos < len(text) and text[pos] == ",":
            pos += 1
            pos = _skip_ws(text, pos)
            continue
        if pos < len(text) and text[pos] == "}":
            return obj, pos + 1
        raise GemmaToolCallParseError(
            f"expected ',' or '}}' in object at {pos}"
        )
    raise GemmaToolCallParseError("unterminated object")


def parse_inline_tool_calls(content: str) -> list[dict]:
    """Find all `<|tool_call>` markers in `content` and synthesize
    OpenAI-shaped tool_call dicts. Returns [] when no markers are found.

    Each result has the shape::

        {
            "id": "synth-<uuid8>",
            "type": "function",
            "function": {
                "name": "novelty_classify",
                "arguments": '{"hypothesis_text": "...", ...}',  # JSON string
            },
        }

    Multiple markers in one content blob → multiple entries (very rare,
    but we handle it). Malformed markers raise GemmaToolCallParseError;
    callers should catch and log so a single bad emission doesn't kill
    the iteration.
    """
    if not isinstance(content, str):
        return []
    out: list[dict] = []
    i = 0
    while True:
        idx = content.find(_TOOL_CALL_MARKER, i)
        if idx < 0:
            break
        synth, end = _parse_one_marker(content, idx)
        if synth is None:
            # Malformed marker; advance past it and try the next.
            i = idx + len(_TOOL_CALL_MARKER)
            continue
        out.append(synth)
        i = end
    return out


def _parse_one_marker(content: str, start: int) -> tuple[dict | None, int]:
    """Parse one `<|tool_call>call:NAME{...}` marker starting at `start`.
    Returns (synthesized_tool_call_dict, end_pos). Returns (None, start)
    when the marker is malformed past recovery."""
    name_start = start + len(_TOOL_CALL_MARKER)
    brace_idx = content.find("{", name_start)
    if brace_idx < 0:
        return None, start
    name = content[name_start:brace_idx].strip()
    # Tool names are bare identifiers; reject any with whitespace etc.
    if not name or not all(c.isalnum() or c == "_" for c in name):
        return None, start
    try:
        body, end = _parse_object(content, brace_idx)
    except GemmaToolCallParseError:
        return None, start
    if not isinstance(body, dict):
        return None, start
    return (
        {
            "id": f"synth-{uuid.uuid4().hex[:8]}",
            "type": "function",
            "function": {
                "name": name,
                "arguments": json.dumps(body, default=str, ensure_ascii=False),
            },
        },
        end,
    )


class _SynthFunc:
    """Function-namespace shim for a synthesized tool_call dict.
    Exposes `.name` and `.arguments` to match the OpenAI SDK shape."""
    __slots__ = ("name", "arguments")

    def __init__(self, fn: dict) -> None:
        self.name = fn["name"]
        self.arguments = fn["arguments"]


class SynthToolCall:
    """Tool-call-namespace shim for a parsed inline tool call. Adapts a
    plain dict from `parse_inline_tool_calls` to the
    `.id/.type/.function.{name,arguments}` attribute interface that the
    rest of the system expects from the OpenAI SDK's
    ChatCompletionMessageToolCall objects."""
    __slots__ = ("id", "type", "function")

    def __init__(self, synth: dict) -> None:
        self.id = synth["id"]
        self.type = synth["type"]
        self.function = _SynthFunc(synth["function"])


def split_narration_and_markup(content: str) -> tuple[str, str]:
    """Return (narration, markup_suffix). The narration is the text BEFORE
    the first `<|tool_call>` marker (or the whole content if no marker).
    The markup suffix is everything from the first marker onward — useful
    for logging / debugging.

    Narration is stripped; trailing whitespace and blank lines removed.
    """
    if not isinstance(content, str):
        return "", ""
    idx = content.find(_TOOL_CALL_MARKER)
    if idx < 0:
        return content.strip(), ""
    return content[:idx].rstrip(), content[idx:]
