"""Generalized active-run state helper.

A single live-state file, run_state/active_run.json, that says *what is
running right now* for any run kind: an experiment, an autoresearch
sweep, a LOOP_V0 iteration, or an ad-hoc run. The UI polls this one file
to render the "what is running now" panel instead of knowing about each
run mode's bespoke state file.

Writes are atomic (write tmp + os.replace) — mirrors the active_iteration
write/delete pattern in orchestrator/runtime.py:106-118, so the UI never
reads a half-written file. The file is validated against
schema/active_run.schema.json on every write.

Lifecycle:
    write_active_run(...)   open a run (overwrites any stale file)
    update_active_run(...)  merge in progress/step/narration
    clear_active_run()      remove the file (absent == idle)
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import jsonschema

REPO_ROOT = Path(__file__).resolve().parent.parent
ACTIVE_RUN_PATH = REPO_ROOT / "run_state" / "active_run.json"
SCHEMA_PATH = REPO_ROOT / "schema" / "active_run.schema.json"

_KINDS = {"experiment", "autoresearch", "loop_v0", "ad_hoc"}


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _validate(doc: dict) -> None:
    schema = json.loads(SCHEMA_PATH.read_text())
    jsonschema.validate(doc, schema)


def _atomic_write(doc: dict) -> None:
    # write tmp + os.replace; see runtime.py:106-113
    _validate(doc)
    ACTIVE_RUN_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = ACTIVE_RUN_PATH.with_suffix(ACTIVE_RUN_PATH.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2))
    os.replace(tmp, ACTIVE_RUN_PATH)


def write_active_run(
    run_id: str,
    kind: str,
    label: str,
    *,
    total: int | None = None,
    unit: str | None = None,
    model: str | None = None,
) -> dict:
    """Open an active run. Overwrites any stale active_run.json."""
    if kind not in _KINDS:
        raise ValueError(f"kind must be one of {sorted(_KINDS)}, got {kind!r}")
    doc: dict = {
        "run_id": run_id,
        "kind": kind,
        "label": label,
        "started_at": _utcnow_iso(),
    }
    if model is not None:
        doc["model"] = model
    if total is not None or unit is not None:
        doc["progress"] = {"done": 0, "total": total, "unit": unit}
    _atomic_write(doc)
    return doc


def update_active_run(
    *,
    done: int | None = None,
    current_step: str | None = None,
    step_started_at: str | None = None,
    narration: str | None = None,
    n_err: int | None = None,
) -> dict | None:
    """Merge fields into the existing active_run.json (read-modify-write).

    Tolerates a missing file: creates a minimal ad_hoc record so an
    update is never lost. Returns the merged doc, or None if nothing
    could be done.
    """
    if ACTIVE_RUN_PATH.exists():
        doc = json.loads(ACTIVE_RUN_PATH.read_text())
    else:
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
    _atomic_write(doc)
    return doc


def clear_active_run() -> None:
    """Remove run_state/active_run.json. Idempotent; absent == idle."""
    if ACTIVE_RUN_PATH.exists():
        ACTIVE_RUN_PATH.unlink()
