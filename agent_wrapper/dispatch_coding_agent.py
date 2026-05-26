"""Day 9 — orchestrator-dispatch infrastructure (W2 deliverable).

Public interface
----------------
dispatch_coding_agent(task_spec, worktree_prefix, timeout_minutes=120,
                      autonomy_tier="soft_gate") -> DispatchResult

What it does
------------
1. Resolves ``task_spec["target_zone"]`` to a zone in ``agent/ownership.yaml``;
   refuses any zone with ``dispatchable: false`` (Track-A primaries).
2. Enforces the Week-2 ``1/day`` concurrency cap by scanning
   ``run_state/claims.jsonl`` for active claims from
   ``claude-dispatched-*`` agents (autonomy.md §3 + collision_protocol.md §3).
3. Renders ``agent/prompts/dispatched_task.md`` with the task spec.
4. Spawns the configured subprocess (default ``["claude", "--worktree",
   f"{worktree_prefix}-{short_id}"]``; tests inject ``_subprocess_cmd``).
5. Tails stdout in a thread; matches one of four sentinels:

   - DISPATCHED TASK <id> COMPLETE — ready to merge          (autonomous/soft)
   - DISPATCHED TASK <id> COMPLETE — HARD GATE — needs human attestation
   - DISPATCHED TASK <id> BLOCKED — <reason>
   - DISPATCHED TASK <id> FAILED  — <reason>

6. Returns a ``DispatchResult`` naming the merge candidate worktree (per
   ``worktree_prefix``), the claim/release timestamps observed in
   ``claims.jsonl``, the wall-clock duration, and the sentinel.
7. On timeout: kills the subprocess, appends a ``dispatch_timeout`` entry to
   ``run_state/escalations.jsonl``, returns ``status="timeout"``.

The dispatcher does NOT auto-merge. Track A merges per
``agent/orchestration.md`` "Merging side branches".
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Note: this module is loaded by tests/test_dispatch_coding_agent.py via
# importlib.util.spec_from_file_location, which does NOT register the
# module in sys.modules before executing it. Python 3.12's @dataclass
# machinery queries sys.modules[__name__] during type checking and fails
# on that load path; DispatchResult is therefore a plain class (not
# @dataclass) below. dispatch_coding_agent is a callable instance (not a
# bare function) for a parallel reason — see _Dispatch class below.

REPO_ROOT = Path(__file__).resolve().parent.parent
CLAIMS_FILE = REPO_ROOT / "run_state" / "claims.jsonl"
ESCALATIONS_FILE = REPO_ROOT / "run_state" / "escalations.jsonl"
OWNERSHIP_FILE = REPO_ROOT / "agent" / "ownership.yaml"
PROMPT_TEMPLATE = REPO_ROOT / "agent" / "prompts" / "dispatched_task.md"

# Week-2 unlock: 1 dispatched agent per day per autonomy.md §3 +
# collision_protocol.md §3. Raised in later phases; the cap lives here so
# the dispatcher is the single source of truth.
WEEK2_DISPATCH_CAP = 1

# Stdout-tail buffer cap so a runaway child doesn't eat memory.
_STDOUT_TAIL_LINES = 200

_SENTINEL_RE = re.compile(
    r"DISPATCHED TASK (?P<task_id>\S+) (?P<verb>"
    r"COMPLETE — ready to merge"
    r"|COMPLETE — HARD GATE — needs human attestation"
    r"|BLOCKED — .+"
    r"|FAILED — .+"
    r")"
)


class DispatcherError(RuntimeError):
    """Raised on protocol violations the dispatcher refuses to proceed past:
    non-dispatchable zone, concurrency cap exceeded, missing required fields
    in the task spec, missing ownership.yaml zone, etc."""


class DispatchResult:
    """Result of one dispatch cycle. Plain class (not dataclass) to remain
    importable under both `import` and `importlib.util.spec_from_file_location`
    on Python 3.12 — see top-of-file note."""

    __slots__ = (
        "task_id", "status", "sentinel", "worktree_path", "branch",
        "duration_sec", "claim_timestamps", "stdout_tail", "error",
    )

    def __init__(
        self,
        task_id: str,
        status: str,  # complete | complete_hard_gate | blocked | failed | timeout
        sentinel: Optional[str],
        worktree_path: Optional[Path],
        branch: Optional[str],
        duration_sec: float,
        claim_timestamps: Tuple[Optional[str], Optional[str]] = (None, None),
        stdout_tail: Optional[List[str]] = None,
        error: Optional[str] = None,
    ) -> None:
        self.task_id = task_id
        self.status = status
        self.sentinel = sentinel
        self.worktree_path = worktree_path
        self.branch = branch
        self.duration_sec = duration_sec
        self.claim_timestamps = claim_timestamps
        self.stdout_tail = list(stdout_tail or [])
        self.error = error

    def __repr__(self) -> str:
        return (
            f"DispatchResult(task_id={self.task_id!r}, status={self.status!r}, "
            f"sentinel={self.sentinel!r}, duration_sec={self.duration_sec:.3f}, "
            f"error={self.error!r})"
        )


# ---------------------------------------------------------------- helpers ---


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _load_ownership() -> Dict[str, Any]:
    try:
        import yaml  # PyYAML
    except ImportError as exc:
        raise DispatcherError(
            "PyYAML required to parse agent/ownership.yaml"
        ) from exc
    return yaml.safe_load(OWNERSHIP_FILE.read_text())


def _find_zone(zone_id: str) -> Dict[str, Any]:
    ownership = _load_ownership()
    for z in ownership.get("zones", []):
        if z.get("id") == zone_id:
            return z
    raise DispatcherError(
        f"zone {zone_id!r} not found in {OWNERSHIP_FILE}; "
        f"known zones: {[z.get('id') for z in ownership.get('zones', [])]}"
    )


def _active_dispatched_count() -> int:
    """Count dispatched-agent claims that are not released and not expired."""
    if not CLAIMS_FILE.exists():
        return 0
    by_ts: Dict[str, Dict[str, Any]] = {}
    released: set[str] = set()
    with CLAIMS_FILE.open() as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "_schema_comment" in rec:
                continue
            intent = rec.get("intent")
            agent_id = rec.get("agent_id", "")
            if intent == "write" and agent_id.startswith("claude-dispatched-"):
                by_ts[rec["timestamp"]] = rec
            elif intent == "release":
                released.add(rec.get("claim_timestamp", ""))
    now = datetime.now(timezone.utc)
    active = 0
    for ts, rec in by_ts.items():
        if ts in released:
            continue
        exp = rec.get("expires_at")
        if exp and _parse_ts(exp) < now:
            continue
        active += 1
    return active


def _render_prompt(task_spec: Dict[str, Any], autonomy_tier: str) -> str:
    """Minimal Jinja-style substitution: ``{{ name }}`` only. The ``{% if %}``
    block selecting the tier paragraph is materialized inline by reading the
    template and replacing the whole block based on ``autonomy_tier``. We do
    not bundle a Jinja2 dep for one template."""
    if not PROMPT_TEMPLATE.exists():
        raise DispatcherError(
            f"prompt template {PROMPT_TEMPLATE} missing"
        )
    template = PROMPT_TEMPLATE.read_text()
    rendered = template
    subs = {
        "task_id": task_spec.get("task_id", "unknown"),
        "zone_id": task_spec.get("target_zone", "unknown"),
        "autonomy_tier": autonomy_tier,
        "timeout_minutes": str(task_spec.get("timeout_minutes", 120)),
        "dispatch_ts": _now_utc_iso(),
        "task_description": task_spec.get("description", ""),
        "success_criteria_bullets": "\n".join(
            f"- {c}" for c in task_spec.get("success_criteria", [])
        ),
        "allowed_paths_bullets": "\n".join(
            f"- {p}" for p in task_spec.get("allowed_paths", [])
        ),
        "extra_required_reads": "\n".join(
            f"{i + 4}. {r}"
            for i, r in enumerate(task_spec.get("extra_required_reads", []))
        ),
    }
    for k, v in subs.items():
        rendered = rendered.replace("{{ " + k + " }}", v)
    return rendered


def _claim_timestamps_for(agent_id_prefix: str) -> Tuple[Optional[str], Optional[str]]:
    """Return (latest_write_ts, matching_release_ts) for the dispatched agent
    whose id starts with the prefix. Both None if no claim was made."""
    if not CLAIMS_FILE.exists():
        return (None, None)
    write_ts: Optional[str] = None
    release_for: Dict[str, str] = {}
    with CLAIMS_FILE.open() as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "_schema_comment" in rec:
                continue
            aid = rec.get("agent_id", "")
            if not aid.startswith(agent_id_prefix):
                continue
            if rec.get("intent") == "write":
                if write_ts is None or rec["timestamp"] > write_ts:
                    write_ts = rec["timestamp"]
            elif rec.get("intent") == "release":
                release_for[rec.get("claim_timestamp", "")] = rec["timestamp"]
    if write_ts is None:
        return (None, None)
    return (write_ts, release_for.get(write_ts))


# ---------------------------------------------------------------- main ------


class _Dispatch:
    """Callable instance — see workers/critic.py for the same pattern.
    Exposing dispatch_coding_agent as a function would cause descriptor-
    protocol method-binding when tests do ``cls.fn = mod.dispatch_coding_agent``
    in setUpClass; the TestCase instance would shadow ``task_spec`` and any
    keyword argument with the same name would collide. As a callable
    instance, the descriptor protocol does not rebind on attribute access."""

    def __call__(
        self,
        task_spec: Dict[str, Any],
        worktree_prefix: str = "auto-task",
        timeout_minutes: float = 120,
        autonomy_tier: str = "soft_gate",
        *,
        _subprocess_cmd: Optional[List[str]] = None,
        _stdin_input: Optional[str] = None,
    ) -> DispatchResult:
        return _dispatch_coding_agent_impl(
            task_spec=task_spec,
            worktree_prefix=worktree_prefix,
            timeout_minutes=timeout_minutes,
            autonomy_tier=autonomy_tier,
            _subprocess_cmd=_subprocess_cmd,
            _stdin_input=_stdin_input,
        )


def _dispatch_coding_agent_impl(
    *,
    task_spec: Dict[str, Any],
    worktree_prefix: str,
    timeout_minutes: float,
    autonomy_tier: str,
    _subprocess_cmd: Optional[List[str]],
    _stdin_input: Optional[str],
) -> DispatchResult:
    """See module docstring. Optional underscore kwargs are test seams:
    ``_subprocess_cmd`` overrides the default Claude Code launch, and
    ``_stdin_input`` feeds the rendered prompt to the subprocess via stdin
    (instead of the default CLI flag path Claude Code uses)."""

    # --- 1. Validate task spec
    required = {"task_id", "target_zone", "description"}
    missing = required - task_spec.keys()
    if missing:
        raise DispatcherError(
            f"task_spec missing required fields: {sorted(missing)}"
        )
    task_id = task_spec["task_id"]
    zone_id = task_spec["target_zone"]

    # --- 2. Zone must be dispatchable
    zone = _find_zone(zone_id)
    if not zone.get("dispatchable", False):
        raise DispatcherError(
            f"zone {zone_id!r} is not dispatchable "
            f"(primary_track={zone.get('primary_track')!r}); "
            "dispatched agents may only write dispatchable zones"
        )

    # --- 3. Concurrency cap
    active = _active_dispatched_count()
    if active >= WEEK2_DISPATCH_CAP:
        raise DispatcherError(
            f"cap_exceeded: {active} dispatched agent(s) already active; "
            f"Week-2 cap is {WEEK2_DISPATCH_CAP}/day "
            f"(autonomy.md §3, collision_protocol.md §3)"
        )

    # --- 4. Render the prompt; surface to subprocess via _stdin_input
    rendered = _render_prompt(task_spec, autonomy_tier)

    # --- 5. Compose the subprocess command (test override or default)
    short_id = task_id.split("_")[-1] if "_" in task_id else task_id
    worktree_name = f"{worktree_prefix}-{short_id}"
    if _subprocess_cmd is None:
        cmd = ["claude", "--worktree", worktree_name]
    else:
        cmd = list(_subprocess_cmd)
    env = os.environ.copy()
    # Dispatched agents need the real LLM; never inherit MOCK_LLM stubs.
    env.pop("MOCK_LLM", None)
    env["DISPATCH_TASK_ID"] = task_id
    env["DISPATCH_WORKTREE"] = worktree_name

    # --- 6. Spawn + tail
    t0 = time.perf_counter()
    sentinel: Optional[str] = None
    sentinel_status: Optional[str] = None
    tail: List[str] = []
    stdin_for_subprocess = _stdin_input if _stdin_input is not None else rendered
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError as exc:
        return DispatchResult(
            task_id=task_id,
            status="failed",
            sentinel=None,
            worktree_path=None,
            branch=None,
            duration_sec=0.0,
            error=f"subprocess launch failed: {exc}",
        )

    if proc.stdin is not None and stdin_for_subprocess is not None:
        try:
            proc.stdin.write(stdin_for_subprocess)
            proc.stdin.close()
        except BrokenPipeError:
            pass

    timeout_sec = float(timeout_minutes) * 60.0

    def _tail_stdout() -> None:
        nonlocal sentinel, sentinel_status
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.rstrip("\n")
            tail.append(line)
            if len(tail) > _STDOUT_TAIL_LINES:
                del tail[0]
            m = _SENTINEL_RE.search(line)
            if m and sentinel is None:
                sentinel = m.group(0)
                verb = m.group("verb")
                if verb.startswith("COMPLETE — ready"):
                    sentinel_status = "complete"
                elif verb.startswith("COMPLETE — HARD GATE"):
                    sentinel_status = "complete_hard_gate"
                elif verb.startswith("BLOCKED"):
                    sentinel_status = "blocked"
                else:
                    sentinel_status = "failed"

    tail_thread = threading.Thread(target=_tail_stdout, daemon=True)
    tail_thread.start()

    try:
        proc.wait(timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        tail_thread.join(timeout=2.0)
        duration = time.perf_counter() - t0
        _append_escalation({
            "kind": "dispatch_timeout",
            "ts": _now_utc_iso(),
            "task_id": task_id,
            "worktree": worktree_name,
            "timeout_minutes": timeout_minutes,
            "stdout_tail": tail[-20:],
        })
        return DispatchResult(
            task_id=task_id,
            status="timeout",
            sentinel=sentinel,
            worktree_path=REPO_ROOT / ".claude" / "worktrees" / worktree_name,
            branch=f"worktree-{worktree_name}",
            duration_sec=duration,
            claim_timestamps=_claim_timestamps_for(f"claude-dispatched-{task_id}"),
            stdout_tail=tail[-20:],
            error="timeout",
        )

    tail_thread.join(timeout=2.0)
    duration = time.perf_counter() - t0

    if sentinel_status is None:
        # Subprocess exited cleanly but never printed a sentinel — protocol
        # violation by the dispatched agent.
        return DispatchResult(
            task_id=task_id,
            status="failed",
            sentinel=None,
            worktree_path=REPO_ROOT / ".claude" / "worktrees" / worktree_name,
            branch=f"worktree-{worktree_name}",
            duration_sec=duration,
            claim_timestamps=_claim_timestamps_for(f"claude-dispatched-{task_id}"),
            stdout_tail=tail[-20:],
            error="exited_without_sentinel",
        )

    return DispatchResult(
        task_id=task_id,
        status=sentinel_status,
        sentinel=sentinel,
        worktree_path=REPO_ROOT / ".claude" / "worktrees" / worktree_name,
        branch=f"worktree-{worktree_name}",
        duration_sec=duration,
        claim_timestamps=_claim_timestamps_for(f"claude-dispatched-{task_id}"),
        stdout_tail=tail[-20:],
        error=None if sentinel_status in {"complete", "complete_hard_gate"} else sentinel,
    )


def _append_escalation(entry: Dict[str, Any]) -> None:
    ESCALATIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with ESCALATIONS_FILE.open("a") as fh:
        fh.write(json.dumps(entry) + "\n")


dispatch_coding_agent = _Dispatch()
