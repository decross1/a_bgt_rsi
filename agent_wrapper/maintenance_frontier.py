"""Bounded, subscription-only CLI transport for manual maintenance reviews.

The scientific frontier seam stays unchanged. This adapter runs in an empty
directory, disables model tool/plugin paths, probes the actual executable and
auth route, sends prompts on stdin, and kills the entire child process group on
timeout or excess output. Receipts contain hashes and metadata, never prompts.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import selectors
import shutil
import signal
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from .frontier_cli import (
    CODEX_MODEL,
    CODEX_REASONING_EFFORT,
    _parse_claude_stdout,
    _parse_codex_stdout,
)

MAX_PROMPT_BYTES = 256_000
MAX_OUTPUT_BYTES = 2_000_000


class OutputLimit(ValueError):
    pass


class StopRequested(RuntimeError):
    """A cooperative maintenance pause was observed while a CLI was active."""


def _check_stop(cancel_paths):
    if any(Path(path).exists() for path in cancel_paths):
        raise StopRequested("maintenance stop control is active")


def _home():
    return Path.home()


def _environment():
    # Keep subscription credentials at their normal location, but never allow
    # a globally exported API key or alternate cloud route to change billing.
    blocked = ("ANTHROPIC_", "OPENAI_", "CLAUDE_CODE_USE_")
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(blocked) and k not in
           {"CODEX_API_KEY", "CODEX_HOME", "CLAUDE_CONFIG_DIR", "CLAUDECODE"}}
    env["DISABLE_AUTOUPDATER"] = "1"
    return env


def _run(cmd, *, env, cwd, deadline, input_text="", cancel_paths=()):
    """Drain bounded pipes without an unbounded communicate() buffer."""
    _check_stop(cancel_paths)
    if time.monotonic() >= deadline:
        raise subprocess.TimeoutExpired(cmd, 0)
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=env, cwd=cwd,
                            start_new_session=True)
    selector = selectors.DefaultSelector()
    data = input_text.encode()
    offset = 0
    output = {"stdout": bytearray(), "stderr": bytearray()}
    for stream, name in [(proc.stdout, "stdout"), (proc.stderr, "stderr")]:
        os.set_blocking(stream.fileno(), False)
        selector.register(stream, selectors.EVENT_READ, name)
    if data:
        os.set_blocking(proc.stdin.fileno(), False)
        selector.register(proc.stdin, selectors.EVENT_WRITE, "stdin")
    else:
        proc.stdin.close()
    try:
        while selector.get_map():
            _check_stop(cancel_paths)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(cmd, 0)
            for key, _ in selector.select(min(remaining, .1)):
                if key.data == "stdin":
                    try:
                        offset += os.write(key.fd, data[offset:offset + 65536])
                    except BrokenPipeError:
                        offset = len(data)
                    if offset == len(data):
                        selector.unregister(key.fileobj)
                        key.fileobj.close()
                else:
                    chunk = os.read(key.fd, 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        key.fileobj.close()
                    else:
                        output[key.data].extend(chunk)
                        if sum(map(len, output.values())) > MAX_OUTPUT_BYTES:
                            raise OutputLimit("CLI output exceeded byte limit")
        proc.wait(timeout=max(.001, deadline - time.monotonic()))
        return subprocess.CompletedProcess(cmd, proc.returncode,
            output["stdout"].decode(errors="replace"),
            output["stderr"].decode(errors="replace"))
    finally:
        selector.close()
        # A grandchild can retain pipes even after its direct parent exits.
        # Killing the session group also prevents hidden work after a timeout.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait(timeout=5)
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            if not stream.closed:
                stream.close()


def _preflight(vendor, env, cwd, deadline, *, cancel_paths=()):
    pinned = os.environ.get(f"FRONTIER_{vendor.upper()}_BIN")
    candidates = [pinned] if pinned else [
        str(_home() / ".npm-global/bin" / vendor), shutil.which(vendor),
        f"/usr/bin/{vendor}"]
    failures = []
    for binary in dict.fromkeys(x for x in candidates if x):
        try:
            r = _run([binary, "--version"], env=env, cwd=cwd,
                     deadline=min(deadline, time.monotonic() + 5),
                     cancel_paths=cancel_paths)
            if r.returncode == 0 and r.stdout.strip():
                return binary, r.stdout.strip()[:160], failures
            failures.append({"binary": binary, "status": "nonzero_version"})
        except OSError:
            failures.append({"binary": binary, "status": "unavailable"})
    raise ValueError("No working CLI executable; explicit pins never fall back")


def _codex_auth():
    auth = _home() / ".codex/auth.json"
    try:
        mode = json.loads(auth.read_text()).get("auth_mode")
    except (OSError, ValueError, AttributeError):
        mode = None
    if mode != "chatgpt":
        raise ValueError("Codex subscription authentication is required")
    return auth


def _command(vendor, binary, model):
    if vendor == "claude":
        return [binary, "-p", "--output-format", "json", "--model", model,
                "--tools", "", "--setting-sources", "", "--settings",
                '{"disableAllHooks":true}', "--strict-mcp-config",
                "--mcp-config", '{"mcpServers":{}}', "--no-chrome",
                "--no-session-persistence"]
    cmd = [binary, "exec", "--skip-git-repo-check", "--sandbox", "read-only",
           "--ignore-user-config", "--ignore-rules", "--ephemeral",
           "-m", model, "-c", f'model_reasoning_effort="{CODEX_REASONING_EFFORT}"',
           "-c", 'approval_policy="never"', "-c", 'web_search="disabled"']
    for feature in ("shell_tool", "unified_exec", "apps", "plugins", "hooks",
                    "multi_agent", "browser_use", "computer_use", "image_generation",
                    "skill_search", "workspace_dependencies"):
        cmd += ["--disable", feature]
    return cmd + ["--json", "-"]


def _parse_response(vendor, stdout):
    if vendor == "claude":
        text = _parse_claude_stdout(stdout)
        obj = json.loads(stdout)
        return text, sorted((obj.get("modelUsage") or {}).keys()), obj.get("usage")
    ids, usage, completed = set(), None, False
    for line in stdout.splitlines():
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if not isinstance(obj, dict):
            continue
        if obj.get("type") in ("turn.failed", "error"):
            raise ValueError("Codex reported a failed turn")
        if isinstance(obj.get("model"), str):
            ids.add(obj["model"])
        if obj.get("type") == "turn.completed":
            completed = True
            usage = obj.get("usage")
    if not completed:
        raise ValueError("Codex did not complete its turn")
    return _parse_codex_stdout(stdout), sorted(ids), usage


def invoke_maintenance_frontier(
    vendor, prompt, *, timeout_s, role, ledger_path, cancel_paths=(),
):
    """Return structured transport status; ledger_path is always explicit.

    Unknown vendor, invalid budget, or oversize input are caller errors.
    Authentication, process and response failures are recorded outcomes.
    """
    if vendor not in ("claude", "codex"):
        raise ValueError("vendor must be claude or codex")
    if isinstance(timeout_s, bool) or not math.isfinite(timeout_s) or timeout_s <= 0:
        raise ValueError("timeout_s must be finite and positive")
    if not isinstance(prompt, str) or len(prompt.encode()) > MAX_PROMPT_BYTES:
        raise ValueError("prompt must be a bounded string")
    if not isinstance(cancel_paths, (list, tuple)) or len(cancel_paths) > 4:
        raise ValueError("cancel_paths must be a bounded path sequence")
    cancel_paths = tuple(Path(path) for path in cancel_paths)
    start = time.monotonic()
    result = {"text": "", "vendor": vendor, "cli_version": "unknown",
              "exit_code": -1, "error": None, "error_category": None,
              "resolved_binary": None, "model_ids": [], "usage": None,
              "requested_model": os.environ.get("FRONTIER_CLAUDE_MODEL", "opus")
                  if vendor == "claude" else CODEX_MODEL,
              "auth_mode": "unverified", "mock": bool(os.environ.get("MOCK_LLM")),
              "binary_fallbacks": []}
    category = "PREFLIGHT_FAILED"
    try:
        if result["mock"]:
            category = "MOCK_MODE"
            raise ValueError("Mock mode is not a completed frontier analysis")
        with tempfile.TemporaryDirectory(prefix="weekly-frontier-") as tmp:
            env = _environment()
            deadline = start + timeout_s
            binary, version, failures = _preflight(
                vendor, env, tmp, deadline, cancel_paths=cancel_paths,
            )
            result.update(resolved_binary=binary, cli_version=version, binary_fallbacks=failures)
            category = "AUTH_FAILED"
            if vendor == "claude":
                auth = _run(
                    [binary, "auth", "status"], env=env, cwd=tmp,
                    deadline=deadline, cancel_paths=cancel_paths,
                )
                status = json.loads(auth.stdout)
                if (auth.returncode or not status.get("loggedIn")
                        or status.get("authMethod") != "claude.ai"
                        or status.get("apiProvider") != "firstParty"):
                    raise ValueError("Claude subscription authentication is required")
            else:
                auth = _codex_auth()
                home = Path(tmp) / "codex-home"
                home.mkdir()
                (home / "auth.json").symlink_to(auth)
                env["CODEX_HOME"] = str(home)
            result["auth_mode"] = "subscription"
            category = "LAUNCH_FAILED"
            proc = _run(_command(vendor, binary, result["requested_model"]),
                        env=env, cwd=tmp, deadline=deadline, input_text=prompt,
                        cancel_paths=cancel_paths)
            result["exit_code"] = proc.returncode
            if proc.returncode:
                category = "NONZERO_EXIT"
                raise ValueError(f"CLI exited with code {proc.returncode}")
            category = "INVALID_RESPONSE"
            text, ids, usage = _parse_response(vendor, proc.stdout)
            result.update(text=text, model_ids=ids, usage=usage)
    except subprocess.TimeoutExpired:
        result.update(error="Frontier deadline exceeded", error_category="TIMEOUT")
    except OutputLimit:
        result.update(error="Frontier output byte limit exceeded", error_category="OUTPUT_LIMIT")
    except StopRequested:
        result.update(error="Maintenance stop requested", error_category="CANCELLED")
    except (OSError, ValueError, TypeError, AttributeError):
        # Do not persist provider stderr/tracebacks: they can echo credentials
        # or source text. The typed outcome is the public failure contract.
        result.update(error=category, error_category=category)
    result["duration_ms"] = round((time.monotonic() - start) * 1000)
    receipt = {k: v for k, v in result.items() if k != "text"}
    receipt.update(timestamp=datetime.now(timezone.utc).isoformat(), role=role,
                   prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
                   response_sha256=hashlib.sha256(result["text"].encode()).hexdigest())
    ledger = Path(ledger_path)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a") as fh:
        fh.write(json.dumps(receipt, allow_nan=False) + "\n")
    return result
