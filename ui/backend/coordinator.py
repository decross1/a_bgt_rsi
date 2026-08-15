"""Autonomy-observability endpoint. Surfaces the coordinator loop so the
human-as-auditor can answer "what did the loop decide, on what basis, can I
trust it?" (ui_autonomy_observability_plan.md).

ONE endpoint post-S3 (UI simplification, docs/ui_simplification_plan_2026-08-15.md),
wired by ``register`` into the existing FastAPI app, read-only and tolerant of
an absent (gitignored) data file:

- ``GET /api/coordinator/cycles`` — reads ``run_state/coordinator_cycles.jsonl``,
  newest-first by ``timestamp``. Returns ``{"cycles": []}`` if absent.

The findings / bubbles / health_signals / active siblings were retired in S3
with their panels: the dossier picker + OweStrip read the human_todo
composition, LoopAlertBanner supersedes the health-signals panel, and the
D-047 registry (``/api/activity/active_runs``) is the live-run source.

Mirrors the ``loop_v0.py`` register-fn idiom (same ``_read_jsonl`` approach,
newest-first sort). The UI never writes to ``run_state/`` or ``memory/``.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    parsed = json.loads(line)
                except json.JSONDecodeError:
                    # Producer's contract; skipping malformed rows keeps the
                    # endpoint useful while a primary-session bug is fixed.
                    continue
                # A bare scalar/array line (`42`, `"x"`, `[1,2]`) is VALID JSON,
                # so it survives json.loads and would land in `rows` as a non-dict.
                # Every endpoint then does `rows.sort(key=lambda r: r.get(...))`,
                # and `.get` on an int/str/list raises AttributeError → a 500 from
                # one stray line. The rows are dict records by contract; drop any
                # non-dict the same way a malformed line is dropped.
                if not isinstance(parsed, dict):
                    continue
                rows.append(parsed)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"unreadable: {exc}") from exc
    return rows


def register(
    app,
    *,
    repo_root: Path,
    run_state_dir: Path,
    memory_dir: Path,
) -> APIRouter:
    """Attach the coordinator router. Reads the coordinator-cycle artifact
    from ``run_state_dir``. ``repo_root``/``memory_dir`` stay accepted so the
    ``create_app`` wiring (and its env overrides) is unchanged."""
    router = APIRouter(prefix="/api/coordinator", tags=["coordinator"])

    @router.get("/cycles")
    def cycles():
        """One row per coordinator cycle — the join key for the /cycles
        narrative view. Newest-first by timestamp; ``{"cycles": []}`` if absent."""
        rows = _read_jsonl(Path(run_state_dir) / "coordinator_cycles.jsonl")
        rows.sort(key=lambda r: r.get("timestamp") or "", reverse=True)
        return {"cycles": rows}

    app.include_router(router)
    return router
