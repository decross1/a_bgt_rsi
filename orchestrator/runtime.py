"""Runtime abstraction for Nara (the orchestrator).

A Runtime answers four questions for Nara at every step:

1. How do I execute a named tool with these arguments? (`dispatch_tool`)
2. How do I write a structured event so it's auditable? (`log_event`)
3. How do I read a small piece of live state? (`read_state`)
4. How do I write a small piece of live state? (`write_state` / `delete_state`)

Today: `PyRuntime` runs everything in-process, dispatches tools via a
local Python registry, and writes state files directly. Adequate for
single-shot human-triggered iterations.

Tomorrow: `NemoClawRuntime` shells out to the NemoClaw CLI (or speaks
to its blueprint API) so each tool runs in a network-policied
OpenShell sandbox. The Nara orchestrator does not care which Runtime
it has — same interface.

D-031 documents why NemoClawRuntime is a stub today.
"""
from __future__ import annotations

import contextvars
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol


REPO_ROOT = Path(__file__).resolve().parent.parent
RUN_STATE_DIR = REPO_ROOT / "run_state"
RUN_LOG_PATH = RUN_STATE_DIR / "week1.run.jsonl"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# Agent attribution for the run log (D-043 / inviolate rule 6). A run-mode
# driver sets this once (coordinator / nara / a fanned-out workflow role);
# every log_event in that context inherits it. A ContextVar (not a global) so
# concurrent async iterations don't clobber each other — same pattern as
# agent_wrapper.wrapper._run_id. Default "nara" = the host orchestrator
# identity, so the existing nara.py call sites attribute correctly with zero
# edits.
_current_agent: contextvars.ContextVar = contextvars.ContextVar(
    "_current_agent", default="nara"
)


def set_current_agent(agent: str | None) -> None:
    """Set the active agent for run-log attribution (None resets to 'nara')."""
    _current_agent.set(agent if agent is not None else "nara")


def get_current_agent() -> str:
    """Return the active agent identity for the current context."""
    return _current_agent.get()


def append_run_log(event: dict, *, agent: str | None = None) -> None:
    """Module-level run-log append (same row shape as PyRuntime.log_event)
    for code that has no Runtime handle — e.g. orchestrator/subagent.py's
    start/finish events. Keeps the heavy tool-registry import out of the
    caller's path. Like log_event, RAISES on an unwritable run_state/ —
    rule-6 loudness is intentional; the run log failing silently would be
    worse than the caller crashing."""
    resolved = agent if agent is not None else get_current_agent()
    row = {"timestamp": _utcnow_iso(), "agent": resolved, **event}
    RUN_STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(RUN_LOG_PATH, "a") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


class Runtime(Protocol):
    """The substrate interface Nara consumes. Implementations differ in
    where dispatched tools execute (in-process vs. sandbox)."""

    def dispatch_tool(
        self,
        name: str,
        args: dict,
        *,
        parent_request_id: str,
    ) -> dict: ...

    def log_event(self, event: dict, *, agent: str | None = None) -> None: ...

    def read_state(self, path: str) -> dict | None: ...

    def write_state(self, path: str, value: dict) -> None: ...

    def delete_state(self, path: str) -> None: ...


class PyRuntime:
    """In-process Python runtime. Tool dispatch goes through a callable
    registry; state I/O uses local files under `run_state/`."""

    def __init__(self, tool_registry: dict[str, Callable] | None = None):
        # Imported lazily to avoid a hard dependency at module load — the
        # tool_registry module imports workers, which may have heavy deps
        # (Chroma, openai client) we don't always want eager.
        if tool_registry is None:
            from orchestrator.tool_registry import TOOL_REGISTRY
            tool_registry = TOOL_REGISTRY
        self._tools = tool_registry

    def dispatch_tool(
        self,
        name: str,
        args: dict,
        *,
        parent_request_id: str,
    ) -> dict:
        if name not in self._tools:
            raise KeyError(
                f"unknown tool {name!r}; known: {sorted(self._tools)}"
            )
        impl = self._tools[name]
        # Worker contract: every tool accepts parent_request_id as a
        # kwarg (matches workers/summarize_paper.py and the salvaged
        # workers/critic.py). Unknown kwargs surface as TypeErrors at
        # call time — that's the right failure mode.
        return impl(**args, parent_request_id=parent_request_id)

    def log_event(self, event: dict, *, agent: str | None = None) -> None:
        # Append to the existing run.jsonl. The run-log format is
        # permissive (see tools/inspect_run.py's candidate-key fallback);
        # a new event_type passes cleanly. `agent` (rule 6 / D-043): the
        # explicit param wins, else the context-scoped identity, else 'nara'.
        # Keyword-only so the existing positional-dict callers are untouched.
        resolved = agent if agent is not None else get_current_agent()
        row = {"timestamp": _utcnow_iso(), "agent": resolved, **event}
        RUN_STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(RUN_LOG_PATH, "a") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    def read_state(self, path: str) -> dict | None:
        p = REPO_ROOT / path
        if not p.exists():
            return None
        return json.loads(p.read_text())

    def write_state(self, path: str, value: dict) -> None:
        # Atomic: write to .tmp, then rename. Prevents the UI from
        # reading a half-written file mid-tool-call.
        p = REPO_ROOT / path
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
        os.replace(tmp, p)

    def delete_state(self, path: str) -> None:
        p = REPO_ROOT / path
        if p.exists():
            p.unlink()


class NemoClawRuntime:
    """Stub. NemoClaw is installable on this host but the installer
    requires sudo interaction the autonomous session can't provide
    (D-031). When the human installs NemoClaw, replace each method
    body with the corresponding NemoClaw CLI call (shell out to
    `nemoclaw run --tool ...` or speak to the blueprint API).

    The interface signatures here are the contract Nara depends on.
    """

    def dispatch_tool(self, name, args, *, parent_request_id):
        raise NotImplementedError(
            "NemoClawRuntime not yet activated; see DECISIONS.md D-031. "
            "Use PyRuntime() until NemoClaw is installed."
        )

    def log_event(self, event, *, agent=None):
        raise NotImplementedError("see DECISIONS.md D-031")

    def read_state(self, path):
        raise NotImplementedError("see DECISIONS.md D-031")

    def write_state(self, path, value):
        raise NotImplementedError("see DECISIONS.md D-031")

    def delete_state(self, path):
        raise NotImplementedError("see DECISIONS.md D-031")
