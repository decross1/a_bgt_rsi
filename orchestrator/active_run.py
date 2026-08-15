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
from typing import Any

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


# ── stale-run reaping (2026-08-15) ───────────────────────────────────────────
# A run that dies without clear_active_run() (crash, SIGKILL, closed session)
# leaves its registry file behind forever: the dashboard renders it as a run
# with an ever-growing "stale heartbeat" (two June entries were still showing
# 57 and 46 days later). Reaping is EXPLICIT and append-only — the doc moves
# to run_state/active_runs/abandoned/ with a recorded reason, never deleted —
# so a post-mortem can still read what the run was doing when it died.
STALE_RUN_HOURS = float(os.environ.get("STALE_RUN_HOURS", "2"))


def _abandoned_dir() -> Path:
    runs_dir = RUNS_DIR
    if ACTIVE_RUN_PATH.parent != REPO_ROOT / "run_state":
        runs_dir = ACTIVE_RUN_PATH.parent / "active_runs"
    return runs_dir / "abandoned"


def _age_hours(doc: dict, now: datetime) -> float | None:
    ts = doc.get("heartbeat_at") or doc.get("started_at")
    if not isinstance(ts, str):
        return None
    try:
        then = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return (now - then).total_seconds() / 3600.0


def reap_stale_runs(
    *, stale_hours: float | None = None, now: datetime | None = None,
    log: Any = None,
) -> list[dict]:
    """Move registry entries whose heartbeat is older than `stale_hours` into
    active_runs/abandoned/, recording each in the run log. Returns the reaped
    records. A doc with an unreadable/absent timestamp is LEFT ALONE (never
    reaped on a guess — rule 4). Never raises: a reap failure on one file
    does not block the others."""
    stale_hours = STALE_RUN_HOURS if stale_hours is None else stale_hours
    now = now or datetime.now(timezone.utc)
    runs_dir = RUNS_DIR
    if ACTIVE_RUN_PATH.parent != REPO_ROOT / "run_state":
        runs_dir = ACTIVE_RUN_PATH.parent / "active_runs"
    if not runs_dir.exists():
        return []
    reaped: list[dict] = []
    for path in sorted(runs_dir.glob("*.json")):
        doc = _read_json(path)
        if doc is None:
            continue
        age = _age_hours(doc, now)
        if age is None or age < stale_hours:
            continue
        rec = {"run_id": doc.get("run_id") or path.stem,
               "kind": doc.get("kind"), "label": doc.get("label"),
               "age_hours": round(age, 2),
               "reason": f"heartbeat older than {stale_hours}h — run died "
                         f"without clear_active_run()"}
        try:
            dest_dir = _abandoned_dir()
            dest_dir.mkdir(parents=True, exist_ok=True)
            doc["abandoned_at"] = _utcnow_iso()
            doc["abandoned_reason"] = rec["reason"]
            _atomic_write(doc, dest_dir / path.name)
            path.unlink()
            # A reaped run must not keep owning the foreground mirror.
            mirror = _read_json(ACTIVE_RUN_PATH)
            if mirror is not None and mirror.get("run_id") == rec["run_id"]:
                ACTIVE_RUN_PATH.unlink()
        except OSError as exc:
            rec["error"] = f"{type(exc).__name__}: {exc}"
        reaped.append(rec)
        try:
            emit = log
            if emit is None:
                from orchestrator.runtime import append_run_log as emit
            emit({"task_id": "reap_stale_run", "agent": "active_run",
                  "status": "passed" if "error" not in rec else "failed",
                  "observable_actual": (
                      f"{rec['run_id']} abandoned after {rec['age_hours']}h"
                      + (f" ({rec['error']})" if "error" in rec else "")),
                  "observable_expected": "stale registry entries reaped, not deleted",
                  "duration_ms": 0})
        except Exception:
            pass
    return reaped


def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(description="Active-run registry maintenance.")
    p.add_argument("--reap", action="store_true",
                   help="move stale entries to active_runs/abandoned/")
    p.add_argument("--stale-hours", type=float, default=None)
    args = p.parse_args(argv)
    if not args.reap:
        p.print_help()
        return 2
    reaped = reap_stale_runs(stale_hours=args.stale_hours)
    for r in reaped:
        print(f"reaped {r['run_id']} ({r['age_hours']}h) — {r['reason']}")
    print(f"{len(reaped)} stale run(s) reaped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
