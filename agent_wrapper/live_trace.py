"""Opt-in, bounded snapshots of a local model's emitted stream for the UI.

This observer never changes a request or grades an answer. It is deliberately
disabled unless LOCAL_MODEL_TRACE_DIR is set. Files are local operational data,
not benchmark evidence; the original request/SSE receipts remain authoritative.
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "local-model-trace/v1"
CHANNEL_BYTES = 128 * 1024
MAX_SNAPSHOT_BYTES = 512 * 1024
MAX_FILES = 96
WRITE_INTERVAL_S = 0.5
STATUSES = frozenset({"streaming", "completed", "tool_call", "exhausted", "no_final",
                      "repetition_aborted", "transport_error", "parser_error", "interrupted"})


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clip(value: str, limit: int) -> tuple[str, bool]:
    raw = value.encode("utf-8")
    return (raw[-limit:].decode("utf-8", errors="ignore"), True) if len(raw) > limit else (value, False)


def _usage(value: dict[str, Any] | None) -> tuple[dict[str, Any] | None, bool]:
    if value is None:
        return None, False
    output: dict[str, Any] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        count = value.get(key)
        if isinstance(count, int) and not isinstance(count, bool) and 0 <= count < 2**63:
            output[key] = count
    for key, field in (("completion_tokens_details", "reasoning_tokens"),
                       ("prompt_tokens_details", "cached_tokens")):
        details = value.get(key)
        count = details.get(field) if isinstance(details, dict) else None
        if isinstance(count, int) and not isinstance(count, bool) and 0 <= count < 2**63:
            output[key] = {field: count}
    return output, output != value


class LocalModelTrace:
    """Best-effort observer: telemetry failure must not fail model inference."""

    def __init__(self, directory: Path, *, model: str, backend: str,
                 source: str, messages: list[dict[str, Any]]) -> None:
        self.directory = directory
        self.request_id = uuid.uuid4().hex
        self.started = time.monotonic()
        self.last_write = float("-inf")
        self.disabled = False
        prompt = next((m.get("content", "") for m in reversed(messages)
                       if m.get("role") == "user"), "")
        preview, clipped = _clip(prompt if isinstance(prompt, str) else "[non-text input]", 4096)
        self.base = {
            "schema": SCHEMA, "request_id": self.request_id,
            "model": model[:256], "backend": backend[:256], "source": source[:256],
            "started_at": _utc(), "prompt_preview": preview,
            "prompt_truncated": clipped,
        }
        try:
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            if directory.is_symlink() or not directory.is_dir():
                raise OSError("trace directory must be a real directory")
            # A finite local history; never remove files belonging to other formats.
            candidates = []
            for index, entry in enumerate(directory.iterdir()):
                if index >= 512:
                    raise OSError("trace history scan limit reached")
                if (entry.suffix == ".json" and len(entry.stem) == 32
                        and all(c in "0123456789abcdef" for c in entry.stem)
                        and stat.S_ISREG(entry.lstat().st_mode)):
                    candidates.append(entry)
            candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            for old in candidates[MAX_FILES - 1:]:
                old.unlink(missing_ok=True)
            self.update(force=True)
        except (OSError, ValueError, TypeError):
            self.disabled = True

    def update(self, *, reasoning_content: str = "", content: str = "",
               tool_calls: list[dict[str, Any]] | None = None,
               usage: dict[str, Any] | None = None, status: str = "streaming",
               finish_reason: str | None = None, error: str | None = None,
               force: bool = False) -> None:
        if self.disabled:
            return
        now = time.monotonic()
        if not force and now - self.last_write < WRITE_INTERVAL_S:
            return
        temporary: str | None = None
        try:
            if not isinstance(status, str) or status not in STATUSES:
                status = "interrupted"
                error = "Trace observer received an unsupported status."
            reasoning, reasoning_clipped = _clip(reasoning_content, CHANNEL_BYTES)
            answer, answer_clipped = _clip(content, CHANNEL_BYTES)
            token_usage, usage_clipped = _usage(usage)
            tools = []
            tool_clipped = len(tool_calls or []) > 16
            for call in (tool_calls or [])[:16]:
                function = call.get("function") or {}
                arguments, clipped = _clip(str(function.get("arguments", "")), 4096)
                tool_clipped |= clipped
                tools.append({"id": str(call.get("id", ""))[:256], "type": "function",
                              "function": {"name": str(function.get("name", ""))[:256],
                                           "arguments": arguments}})
            row = {
                **self.base, "updated_at": _utc(), "elapsed_s": max(0, now - self.started),
                "status": status, "reasoning_content": reasoning, "content": answer,
                "tool_calls": tools, "usage": token_usage, "usage_truncated": usage_clipped,
                "finish_reason": finish_reason[:256] if finish_reason else None,
                "error": str(error)[:2048] if error else None,
                "truncated": {"reasoning_content": reasoning_clipped,
                              "content": answer_clipped, "tool_calls": tool_clipped},
            }
            raw = json.dumps(row, ensure_ascii=False, allow_nan=False).encode("utf-8")
            # JSON escaping can expand even byte-bounded text (e.g. control
            # characters). Retain a terminal status with explicitly clipped
            # channels instead of abandoning the last streaming snapshot.
            while len(raw) > MAX_SNAPSHOT_BYTES:
                longest = max(("reasoning_content", "content"), key=lambda k: len(row[k]))
                if len(row[longest]) > 1024:
                    row[longest] = row[longest][len(row[longest]) // 2:]
                    row["truncated"][longest] = True
                elif row["tool_calls"]:
                    row["tool_calls"] = []
                    row["truncated"]["tool_calls"] = True
                else:
                    raise ValueError("bounded trace metadata exceeds snapshot limit")
                raw = json.dumps(row, ensure_ascii=False, allow_nan=False).encode("utf-8")
            fd, temporary = tempfile.mkstemp(prefix=".trace-", dir=self.directory)
            with os.fdopen(fd, "wb") as output:
                output.write(raw)
            os.replace(temporary, self.directory / f"{self.request_id}.json")
            temporary = None
            self.last_write = now
        except (OSError, ValueError, TypeError, AttributeError):
            self.disabled = True
        finally:
            if temporary:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass


def start_trace(*, model: str, backend: str, source: str,
                messages: list[dict[str, Any]]) -> LocalModelTrace | None:
    directory = os.environ.get("LOCAL_MODEL_TRACE_DIR")
    if not directory:
        return None
    try:
        return LocalModelTrace(Path(directory), model=model, backend=backend,
                               source=source, messages=messages)
    except (OSError, ValueError, TypeError):
        return None
