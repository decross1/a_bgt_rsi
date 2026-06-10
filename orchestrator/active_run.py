"""Generalized active-run state helper: multi-run registry + foreground mirror.

Each live run gets its own file, run_state/active_runs/<run_id>.json —
the multi-run source of truth (one file per live run, deleted on
completion) — so concurrent runs (a loop iteration, the coordinator, a
battery) never clobber each other's state. run_state/active_run.json
stays as the single-slot *foreground mirror*: the most recent writer
owns it, the UI keeps polling that one file, and an update never
clobbers a mirror owned by a different run (only the owner clears it).
Ownership is keyed per execution context via a ContextVar holding the
run_id, so the public API keeps its zero-argument call sites.

Writes are atomic (write tmp + os.replace) — mirrors the active_iteration
write/delete pattern in orchestrator/runtime.py:106-118, so the UI never
reads a half-written file. Every doc (per-run and mirror) is validated
against schema/active_run.schema.json on every write; every write also
refreshes "heartbeat_at" so consumers can spot possibly-dead runs.

Lifecycle:
    write_active_run(...)   open a run (registers it; takes the mirror)
    update_active_run(...)  merge in progress/step/narration + heartbeat
    clear_active_run()      deregister this context's run (absent == idle)
"""
from __future__ import annotations

import contextvars
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import jsonschema

REPO_ROOT = Path(__file__).resolve().parent.parent
ACTIVE_RUN_PATH = REPO_ROOT / "run_state" / "active_run.json"
RUNS_DIR = REPO_ROOT / "run_state" / "active_runs"
SCHEMA_PATH = REPO_ROOT / "schema" / "active_run.schema.json"

_KINDS = {"experiment", "autoresearch", "loop_v0", "ad_hoc", "coordinator"}

# Which run(s) this execution context opened, innermost last; keys
# updates/clears to the caller's own per-run file even when several runs
# are live at once. A STACK (not a single id) because registration nests
# in-process: the coordinator registers, then executes nara.run_iteration,
# which registers the iteration — the iteration's clear must restore the
# coordinator as this context's current run, not wipe ownership (the
# 2026-06-10 review's orphaned-coordinator-file finding).
_active_run_stack: contextvars.ContextVar[tuple] = contextvars.ContextVar(
    "_active_run_stack", default=()
)


def _current_run_id() -> str | None:
    stack = _active_run_stack.get()
    return stack[-1] if stack else None


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _validate(doc: dict) -> None:
    schema = json.loads(SCHEMA_PATH.read_text())
    jsonschema.validate(doc, schema)


def _safe_filename(run_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", run_id) or "run"


def _run_path(run_id: str) -> Path:
    # Invariant: the registry lives beside the mirror. If ACTIVE_RUN_PATH
    # was repointed (tests monkeypatch it) without RUNS_DIR, follow the
    # mirror so the two never split across run_state dirs.
    runs_dir = RUNS_DIR
    if runs_dir.parent != ACTIVE_RUN_PATH.parent:
        runs_dir = ACTIVE_RUN_PATH.parent / "active_runs"
    return runs_dir / f"{_safe_filename(run_id)}.json"


def _read_json(path: Path) -> dict | None:
    """Tolerant read: missing or malformed file -> None, never raises."""
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _atomic_write(doc: dict, path: Path) -> None:
    # write tmp + os.replace; see runtime.py:106-113
    _validate(doc)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2))
    os.replace(tmp, path)


def write_active_run(
    run_id: str,
    kind: str,
    label: str,
    *,
    total: int | None = None,
    unit: str | None = None,
    model: str | None = None,
) -> dict:
    """Open an active run: register its per-run file and take the mirror."""
    if kind not in _KINDS:
        raise ValueError(f"kind must be one of {sorted(_KINDS)}, got {kind!r}")
    doc: dict = {
        "run_id": run_id,
        "kind": kind,
        "label": label,
        "started_at": _utcnow_iso(),
    }
    doc["heartbeat_at"] = doc["started_at"]
    if model is not None:
        doc["model"] = model
    if total is not None or unit is not None:
        doc["progress"] = {"done": 0, "total": total, "unit": unit}
    _atomic_write(doc, _run_path(run_id))
    _atomic_write(doc, ACTIVE_RUN_PATH)  # foreground = most recent writer
    _active_run_stack.set(_active_run_stack.get() + (run_id,))
    return doc


def update_active_run(
    *,
    done: int | None = None,
    current_step: str | None = None,
    step_started_at: str | None = None,
    narration: str | None = None,
    n_err: int | None = None,
) -> dict | None:
    """Merge fields into this context's run (read-modify-write).

    Resolution: own per-run file -> minimal recreate under the context's
    run_id -> adopt the mirror (legacy caller) -> bare ad_hoc record, so
    an update is never silently dropped. Always refreshes heartbeat_at.
    The mirror is rewritten only when absent or owned by this run. The
    per-run REGISTRY file is rewritten only by its OWNING context — a
    legacy adopt-the-mirror update must not refresh a foreign run's
    heartbeat (that would mask a dead run as alive).
    """
    ctx_run_id = _current_run_id()
    if ctx_run_id is not None:
        doc = _read_json(_run_path(ctx_run_id))
        if doc is None:
            # recreate minimally so the update isn't silently dropped
            doc = {
                "run_id": ctx_run_id,
                "kind": "ad_hoc",
                "label": "unknown",
                "started_at": _utcnow_iso(),
            }
    else:
        # legacy caller: adopt the mirror, but don't take ownership
        doc = _read_json(ACTIVE_RUN_PATH)
        if doc is None:
            # no-op-create: a bare record so the update isn't silently dropped
            doc = {
                "run_id": "unknown",
                "kind": "ad_hoc",
                "label": "unknown",
                "started_at": _utcnow_iso(),
            }
    if current_step is not None:
        doc["current_step"] = current_step
    if step_started_at is not None:
        doc["step_started_at"] = step_started_at
    if narration is not None:
        doc["narration"] = narration
    if n_err is not None:
        doc["n_err"] = n_err
    if done is not None:
        progress = doc.get("progress") or {}
        progress["done"] = done
        doc["progress"] = progress
    doc["heartbeat_at"] = _utcnow_iso()
    if ctx_run_id is not None:
        _atomic_write(doc, _run_path(doc["run_id"]))
    mirror = _read_json(ACTIVE_RUN_PATH)
    if mirror is None or mirror.get("run_id") == doc["run_id"]:
        _atomic_write(doc, ACTIVE_RUN_PATH)
    return doc


def clear_active_run() -> None:
    """Deregister this context's INNERMOST run. Idempotent; absent == idle.

    Deletes the per-run file, and the mirror only if this run owns it
    (only-owner-clears); pops the ownership stack and — when a parent run
    remains in this context (nested registration, e.g. coordinator ->
    iteration) — restores the parent's doc as the foreground mirror.

    Legacy callers with NO registration in this context clear the mirror
    and its per-run twin unconditionally — that branch is the cleanup-tool
    path (a human clearing a stale run). Note a context that already
    cleared its own run falls into it too: clear() is paired with ONE
    write_active_run; do not call it speculatively.
    """
    stack = _active_run_stack.get()
    if stack:
        own = stack[-1]
        run_path = _run_path(own)
        if run_path.exists():
            run_path.unlink()
        mirror = _read_json(ACTIVE_RUN_PATH)  # missing/malformed = no owner
        if mirror is not None and mirror.get("run_id") == own:
            if ACTIVE_RUN_PATH.exists():
                ACTIVE_RUN_PATH.unlink()
        remaining = stack[:-1]
        _active_run_stack.set(remaining)
        if remaining and not ACTIVE_RUN_PATH.exists():
            # Foreground returns to the parent run, if it is still live.
            parent_doc = _read_json(_run_path(remaining[-1]))
            if parent_doc is not None:
                _atomic_write(parent_doc, ACTIVE_RUN_PATH)
        return
    # legacy caller: clear the mirror and its per-run twin
    mirror = _read_json(ACTIVE_RUN_PATH)  # tolerate malformed: no run_id
    if ACTIVE_RUN_PATH.exists():
        ACTIVE_RUN_PATH.unlink()
    if mirror is not None and isinstance(mirror.get("run_id"), str):
        twin = _run_path(mirror["run_id"])
        if twin.exists():
            twin.unlink()
