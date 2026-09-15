"""LOOP_V1 P2 — subprocess seam for frontier-CLI calls (D-061 executes D-041 step 3).

Public interface
----------------
invoke_frontier(vendor, prompt, *, timeout_s, role, ledger_path=None) ->
    {"text": str, "vendor": str, "cli_version": str, "duration_ms": int,
     "exit_code": int, "error": str | None, "failure_code": str | None,
     "resolved_binary_path": str | None}

What it does
------------
1. Builds the headless command per vendor (flags verified against the
   installed CLIs, claude 2.1.x / codex 0.146.x):
   - "claude": ``claude -p --output-format json <prompt>`` — stdout is one
     JSON object; the reply text is its ``result`` field.
   - "codex":  ``codex exec --skip-git-repo-check --sandbox read-only
     -m <CODEX_MODEL> -c model_reasoning_effort=<CODEX_REASONING_EFFORT>
     --json <prompt>`` — stdout is JSONL events; the reply text is the last
     ``agent_message`` event. The model/effort are PINNED here (see
     ``CODEX_MODEL``) rather than inherited from ~/.codex/config.toml.
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
   prompt_sha256, resolved_binary_path, failure_code}`` with ``verdict`` always
   null at this layer (the review layer owns verdicts). Default ledger:
   ``run_state/frontier_calls.jsonl``. Old rows keep their original shape.

This module never writes loop_memory or the brain (annotate-only firewall,
D-061); it only appends the frontier-call ledger.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
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

# The user-level npm prefix where the CURRENT CLIs live. Under cron/systemd
# the minimal PATH misses it: on 2026-08-18T06:00Z the first cron-context
# frontier screen resolved a stale root install of claude (2.1.143, exit 1)
# and no codex at all (exit 127). Resolution order: explicit env pin >
# known user install > current ~/.local/bin install > PATH. An explicit pin
# stays authoritative even if it is missing: a bad pin is a typed launch
# failure, not permission to silently select a different executable.
_USER_NPM_BIN = Path.home() / ".npm-global" / "bin"
_USER_LOCAL_BIN = Path.home() / ".local" / "bin"


def _resolve_binary(vendor: str) -> str:
    name = _VENDOR_BINARIES[vendor]
    pinned = os.environ.get(f"FRONTIER_{vendor.upper()}_BIN")
    if pinned:
        return pinned
    local = _USER_NPM_BIN / name
    if local.is_file() and os.access(local, os.X_OK):
        return str(local)
    local = _USER_LOCAL_BIN / name
    if local.is_file() and os.access(local, os.X_OK):
        return str(local)
    return shutil.which(name) or name


def _binary_path(binary: str) -> Optional[str]:
    """Path actually selected for the subprocess, or null when unavailable."""
    if os.path.sep in binary:
        return str(Path(binary).resolve(strict=False))
    found = shutil.which(binary)
    return str(Path(found).resolve(strict=False)) if found else None

# Codex model + reasoning effort are pinned HERE, not inherited from the
# machine-global ~/.codex/config.toml. On 2026-08-16 that config's
# `model = "gpt-5.6"` / `model_reasoning_effort = "max"` both started coming
# back 400 ("not supported when using Codex with a ChatGPT account"), which
# silently took the novelty/risk half of the D-061 falsifier panel dark
# between 2026-08-15T19:30Z and the fix — 32 clean calls, then every call
# nonzero. The apparatus states what it runs on rather than inheriting a file
# it does not version. Env-overridable so a restored entitlement (or a vendor
# rename) needs no code change.
# gpt-5.6-sol at effort "max" (owner-directed 2026-08-16, after the account
# regained 5.6-class access). Both were probed live through the isolated home
# before pinning: model reachable, and max/xhigh/high all accepted — the
# falsifier tier gets the deepest tier the account will serve, since its whole
# job is finding the defect the local models missed. gpt-5.5 + "high" was the
# D-068 recovery pin and remains the known-good fallback.
CODEX_MODEL = os.environ.get("FRONTIER_CODEX_MODEL", "gpt-5.6-sol")
CODEX_REASONING_EFFORT = os.environ.get("FRONTIER_CODEX_EFFORT", "max")
# Repo-owned CODEX_HOME (gitignored): our own config.toml + a symlink to the
# machine's auth.json. See _ensure_codex_home.
CODEX_HOME_DIR = REPO_ROOT / "run_state" / "codex_home"

# Memoized `<cli> --version` output per selected binary. An env override can
# change during a process; vendor-only caching would mislabel the new binary.
_version_cache: Dict[tuple[str, str], str] = {}


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _spawn_env(vendor: Optional[str] = None) -> Dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in _STRIPPED_ENV_KEYS}
    if vendor == "codex":
        home = _ensure_codex_home()
        if home is not None:
            env["CODEX_HOME"] = str(home)
    return env


def _ensure_codex_home() -> Optional[Path]:
    """A repo-owned CODEX_HOME so the apparatus does not read the machine's
    global ~/.codex/config.toml.

    That file is shared with the owner's other projects and is rewritten by
    the CLI itself: on 2026-08-16 it acquired an `[agents]` table mid-session
    that the installed codex could not parse, and every call started failing
    in ~35ms — a second outage of the same class as D-068, hours after the
    first. The apparatus keeps its own two-line config and borrows only the
    credential (a SYMLINK, never a copy — a copied token is a token that
    outlives its rotation).

    Returns None when the credential is absent: there is nowhere else for it
    to come from, so we leave CODEX_HOME unset and let the call fail with the
    real error rather than manufacturing a broken home directory."""
    auth = Path.home() / ".codex" / "auth.json"
    if not auth.exists():
        return None
    try:
        CODEX_HOME_DIR.mkdir(parents=True, exist_ok=True)
        # Rewritten every call: the pin is whatever this module says NOW, so a
        # stale home can never silently outvote CODEX_MODEL.
        (CODEX_HOME_DIR / "config.toml").write_text(
            f'model = "{CODEX_MODEL}"\n'
            f'model_reasoning_effort = "{CODEX_REASONING_EFFORT}"\n')
        link = CODEX_HOME_DIR / "auth.json"
        if not link.exists() and not link.is_symlink():
            link.symlink_to(auth)
    except OSError:
        return None
    return CODEX_HOME_DIR


def _build_cmd(vendor: str, prompt: str, *, binary: Optional[str] = None) -> List[str]:
    if vendor == "claude":
        return [binary or _resolve_binary("claude"), "-p", "--output-format", "json",
                prompt]
    if vendor == "codex":
        return [
            binary or _resolve_binary("codex"), "exec", "--skip-git-repo-check",
            "--sandbox", "read-only",
            "-m", CODEX_MODEL,
            "-c", f"model_reasoning_effort={CODEX_REASONING_EFFORT}",
            "--json", prompt,
        ]
    raise ValueError(
        f"unknown vendor {vendor!r}; expected one of "
        f"{sorted(_VENDOR_BINARIES)}"
    )


def _cli_version(vendor: str, binary: Optional[str] = None,
                 resolved_binary_path: Optional[str] = None) -> str:
    """Probe the selected binary once per process; unknown on any failure."""
    binary = binary or _resolve_binary(vendor)
    cache_key = (vendor, resolved_binary_path or binary)
    if cache_key in _version_cache:
        return _version_cache[cache_key]
    try:
        proc = subprocess.run(
            [binary, "--version"],
            capture_output=True, text=True, timeout=15,
            env=_spawn_env(vendor),
        )
        version = proc.stdout.strip()[:120] if proc.returncode == 0 else "unknown"
        version = version or "unknown"
    except (OSError, subprocess.SubprocessError):
        version = "unknown"
    _version_cache[cache_key] = version
    return version


class CLIReportedError(ValueError):
    """The Claude JSON response itself marked the call as an error."""


def _parse_claude_stdout(stdout: str) -> str:
    """`claude -p --output-format json` prints one JSON object; the reply is
    its 'result' field. Raises ValueError on any shape mismatch."""
    obj = json.loads(stdout)
    if not isinstance(obj, dict):
        raise ValueError(f"expected JSON object, got {type(obj).__name__}")
    if obj.get("is_error"):
        raise CLIReportedError("claude reported is_error")
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
    if vendor not in _VENDOR_BINARIES:
        _build_cmd(vendor, "")  # vendor validation (raises ValueError early)
    ledger = Path(ledger_path) if ledger_path is not None else DEFAULT_LEDGER
    prompt_sha256 = hashlib.sha256(prompt.encode("utf-8")).hexdigest()

    def _finish(
        text: str, cli_version: str, duration_ms: int, exit_code: int,
        error: Optional[str], failure_code: Optional[str],
        resolved_binary_path: Optional[str],
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
            "resolved_binary_path": resolved_binary_path,
            "failure_code": failure_code,
        })
        return {
            "text": text,
            "vendor": vendor,
            "cli_version": cli_version,
            "duration_ms": duration_ms,
            "exit_code": exit_code,
            "error": error,
            "resolved_binary_path": resolved_binary_path,
            "failure_code": failure_code,
        }

    if os.environ.get("MOCK_LLM"):
        stub = f"MOCK_FRONTIER[{vendor}/{role}] sha256={prompt_sha256[:16]}"
        return _finish(stub, "mock", 0, 0, None, None, None)

    binary = _resolve_binary(vendor)
    resolved_binary_path = _binary_path(binary)
    cli_version = _cli_version(vendor, binary, resolved_binary_path)
    cmd = _build_cmd(vendor, prompt, binary=binary)
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout_s, env=_spawn_env(vendor),
        )
    except subprocess.TimeoutExpired:
        duration_ms = int((time.perf_counter() - t0) * 1000)
        return _finish(
            "", cli_version, duration_ms, -1,
            f"timeout after {timeout_s}s", "timeout", resolved_binary_path,
        )
    except OSError as exc:  # binary missing / not executable
        duration_ms = int((time.perf_counter() - t0) * 1000)
        return _finish(
            "", cli_version, duration_ms, 127,
            f"launch failed: {type(exc).__name__}", "launch_error",
            resolved_binary_path,
        )
    duration_ms = int((time.perf_counter() - t0) * 1000)

    if proc.returncode != 0:
        return _finish(
            "", cli_version, duration_ms, proc.returncode,
            f"nonzero exit {proc.returncode}", "nonzero_exit",
            resolved_binary_path,
        )

    parser = _parse_claude_stdout if vendor == "claude" else _parse_codex_stdout
    try:
        text = parser(proc.stdout or "")
    except CLIReportedError as exc:
        return _finish(
            "", cli_version, duration_ms, proc.returncode,
            str(exc), "cli_reported_error", resolved_binary_path,
        )
    except (ValueError, json.JSONDecodeError) as exc:
        return _finish(
            "", cli_version, duration_ms, proc.returncode,
            f"unparseable output: {type(exc).__name__}",
            "unparseable_output", resolved_binary_path,
        )
    return _finish(text, cli_version, duration_ms, proc.returncode, None,
                   None, resolved_binary_path)
