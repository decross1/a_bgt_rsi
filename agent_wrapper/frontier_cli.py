"""LOOP_V1 P2 — subprocess seam for frontier-CLI calls (D-061 executes D-041 step 3).

Public interface
----------------
invoke_frontier(vendor, prompt, *, timeout_s, role, ledger_path=None) ->
    {"text": str, "vendor": str, "cli_version": str, "duration_ms": int,
     "exit_code": int, "error": str | None}

What it does
------------
1. Builds the headless command per vendor (flags verified against the
   installed CLIs, claude 2.1.x / codex 0.146.x):
   - "claude": ``claude -p --output-format json <prompt>`` — stdout is one
     JSON object; the reply text is its ``result`` field.
   - "codex":  ``codex exec --skip-git-repo-check --sandbox read-only
     --json <prompt>`` — stdout is JSONL events; the reply text is the last
     ``agent_message`` event.
2. Spawns with ``os.environ`` minus ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN
   (MANDATORY — the key is set globally on this host and would silently
   reroute the Max-subscription ``claude`` CLI onto the metered API).
3. ``MOCK_LLM`` set -> deterministic stub result; the CLI is never spawned.
4. Fail-closed structured errors: nonzero exit, timeout, missing binary, and
   unparseable output all return a result with ``error`` set — never an
   uncaught exception. Unknown vendor is a caller bug and raises ValueError.
5. Every call (including every error path and the mock path) appends one row
   to the ledger BEFORE returning:
   ``{timestamp, vendor, cli_version, role, verdict, duration_ms, exit_code,
   prompt_sha256}`` with ``verdict`` always null at this layer (the review
   layer owns verdicts). Default ledger: ``run_state/frontier_calls.jsonl``.

This module never writes loop_memory or the brain (annotate-only firewall,
D-061); it only appends the frontier-call ledger.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LEDGER = REPO_ROOT / "run_state" / "frontier_calls.jsonl"

# Env keys stripped from the spawned environment. ANTHROPIC_API_KEY is set
# globally on this host; inheriting it makes `claude -p` bill the metered API
# instead of the Max subscription (LOOP_V1 P2 "metered-API routing trap").
_STRIPPED_ENV_KEYS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")

_VENDOR_BINARIES = {"claude": "claude", "codex": "codex"}

# Cap on stderr text carried into an error message.
_STDERR_TAIL_CHARS = 500

# Memoized `<cli> --version` output per vendor (one probe per process).
_version_cache: Dict[str, str] = {}


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _spawn_env() -> Dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in _STRIPPED_ENV_KEYS}


def _build_cmd(vendor: str, prompt: str) -> List[str]:
    if vendor == "claude":
        return ["claude", "-p", "--output-format", "json", prompt]
    if vendor == "codex":
        return [
            "codex", "exec", "--skip-git-repo-check",
            "--sandbox", "read-only", "--json", prompt,
        ]
    raise ValueError(
        f"unknown vendor {vendor!r}; expected one of "
        f"{sorted(_VENDOR_BINARIES)}"
    )


def _cli_version(vendor: str) -> str:
    """Probe `<cli> --version` once per process; 'unknown' on any failure."""
    if vendor in _version_cache:
        return _version_cache[vendor]
    try:
        proc = subprocess.run(
            [_VENDOR_BINARIES[vendor], "--version"],
            capture_output=True, text=True, timeout=15, env=_spawn_env(),
        )
        version = proc.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        version = "unknown"
    _version_cache[vendor] = version
    return version


def _parse_claude_stdout(stdout: str) -> str:
    """`claude -p --output-format json` prints one JSON object; the reply is
    its 'result' field. Raises ValueError on any shape mismatch."""
    obj = json.loads(stdout)
    if not isinstance(obj, dict):
        raise ValueError(f"expected JSON object, got {type(obj).__name__}")
    if obj.get("is_error"):
        raise ValueError(f"claude reported is_error: {obj.get('result')!r}")
    result = obj.get("result")
    if not isinstance(result, str) or not result.strip():
        raise ValueError("claude JSON has no non-empty string 'result' field")
    return result


def _parse_codex_stdout(stdout: str) -> str:
    """`codex exec --json` prints JSONL events; the reply is the last
    agent_message event. Handles both event shapes codex has shipped:
    {"type":"item.completed","item":{"type":"agent_message","text":...}} and
    {"msg":{"type":"agent_message","message":...}}. Raises ValueError if no
    agent message is found."""
    text: Optional[str] = None
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue  # codex interleaves non-JSON status lines; skip them
        if not isinstance(ev, dict):
            continue
        item = ev.get("item")
        if isinstance(item, dict) and (
            item.get("type") == "agent_message"
            or item.get("item_type") == "agent_message"
        ):
            candidate = item.get("text")
            if isinstance(candidate, str) and candidate.strip():
                text = candidate
        msg = ev.get("msg")
        if isinstance(msg, dict) and msg.get("type") == "agent_message":
            candidate = msg.get("message")
            if isinstance(candidate, str) and candidate.strip():
                text = candidate
    if text is None:
        raise ValueError("no agent_message event found in codex JSONL output")
    return text


def _append_ledger(ledger_path: Path, row: Dict[str, Any]) -> None:
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a") as fh:
        fh.write(json.dumps(row) + "\n")


def invoke_frontier(
    vendor: str,
    prompt: str,
    *,
    timeout_s: int,
    role: str,
    ledger_path: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """One frontier-CLI call. See module docstring. Never raises for runtime
    failures (timeout, nonzero exit, missing binary, unparseable output) —
    those return a result with ``error`` set. Raises ValueError only for an
    unknown ``vendor`` (caller bug, fail-closed)."""
    _build_cmd(vendor, "")  # vendor validation (raises ValueError early)
    ledger = Path(ledger_path) if ledger_path is not None else DEFAULT_LEDGER
    prompt_sha256 = hashlib.sha256(prompt.encode("utf-8")).hexdigest()

    def _finish(
        text: str, cli_version: str, duration_ms: int, exit_code: int,
        error: Optional[str],
    ) -> Dict[str, Any]:
        # Ledger row is written BEFORE the result is returned — every call,
        # including errors and mocks, lands in the calibration dataset.
        _append_ledger(ledger, {
            "timestamp": _now_utc_iso(),
            "vendor": vendor,
            "cli_version": cli_version,
            "role": role,
            "verdict": None,  # null at this layer; the review layer owns it
            "duration_ms": duration_ms,
            "exit_code": exit_code,
            "prompt_sha256": prompt_sha256,
        })
        return {
            "text": text,
            "vendor": vendor,
            "cli_version": cli_version,
            "duration_ms": duration_ms,
            "exit_code": exit_code,
            "error": error,
        }

    if os.environ.get("MOCK_LLM"):
        stub = f"MOCK_FRONTIER[{vendor}/{role}] sha256={prompt_sha256[:16]}"
        return _finish(stub, "mock", 0, 0, None)

    cli_version = _cli_version(vendor)
    cmd = _build_cmd(vendor, prompt)
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout_s, env=_spawn_env(),
        )
    except subprocess.TimeoutExpired:
        duration_ms = int((time.perf_counter() - t0) * 1000)
        return _finish(
            "", cli_version, duration_ms, -1,
            f"timeout after {timeout_s}s",
        )
    except OSError as exc:  # binary missing / not executable
        duration_ms = int((time.perf_counter() - t0) * 1000)
        return _finish(
            "", cli_version, duration_ms, 127,
            f"launch failed: {exc}",
        )
    duration_ms = int((time.perf_counter() - t0) * 1000)

    if proc.returncode != 0:
        stderr_tail = (proc.stderr or "").strip()[-_STDERR_TAIL_CHARS:]
        return _finish(
            "", cli_version, duration_ms, proc.returncode,
            f"nonzero exit {proc.returncode}: {stderr_tail}",
        )

    parser = _parse_claude_stdout if vendor == "claude" else _parse_codex_stdout
    try:
        text = parser(proc.stdout or "")
    except (ValueError, json.JSONDecodeError) as exc:
        return _finish(
            "", cli_version, duration_ms, proc.returncode,
            f"unparseable output: {exc}",
        )
    return _finish(text, cli_version, duration_ms, proc.returncode, None)
