"""Autonomy-observability endpoints. Surfaces the coordinator loop so the
human-as-auditor can answer "what did the loop decide, on what basis, can I
trust it?" — the loop currently runs "dark" (ui_autonomy_observability_plan.md).

Four endpoints, all wired by ``register`` into the existing FastAPI app, all
read-only and tolerant of absent (gitignored) data files:

- ``GET /api/coordinator/cycles``   — reads ``run_state/coordinator_cycles.jsonl``,
  newest-first by ``timestamp``. Returns ``{"cycles": []}`` if absent.
- ``GET /api/coordinator/active``   — reads ``run_state/active_run.json``;
  returns 204 No Content when the file is absent.
- ``GET /api/coordinator/findings`` — reads ``memory/surfaced_findings.jsonl``,
  newest-first by ``timestamp``. Returns ``{"findings": []}`` if absent.
- ``GET /api/coordinator/bubbles``  — reads ``memory/coordinator_bubbles.jsonl``,
  newest-first by ``timestamp``. Returns ``{"bubbles": []}`` if absent.
- ``GET /api/coordinator/health_signals`` — reads ``run_state/health_signals.jsonl``
  (per-cycle degraded signals: ml-intern 0-papers, qwen empty-content).
  Newest-first by ``timestamp``. Returns ``{"health_signals": []}`` if absent.

Mirrors the ``loop_v0.py`` register-fn idiom (same ``_read_jsonl`` approach,
newest-first sort, the active-file delete-race handling). The UI never writes
to ``run_state/`` or ``memory/``.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response


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
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    # Producer's contract; skipping malformed rows keeps the
                    # endpoint useful while a primary-session bug is fixed.
                    continue
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
    """Attach the coordinator router. Reads the coordinator-cycle artifact and
    active-run from ``run_state_dir`` and the surfaced-findings / bubbles logs
    from ``memory_dir`` (mirrors loop_v0's split of run_state vs memory)."""
    router = APIRouter(prefix="/api/coordinator", tags=["coordinator"])

    @router.get("/cycles")
    def cycles():
        """One row per coordinator cycle — the join key for the Coordinator
        Cycle view. Newest-first by timestamp; ``{"cycles": []}`` if absent."""
        rows = _read_jsonl(Path(run_state_dir) / "coordinator_cycles.jsonl")
        rows.sort(key=lambda r: r.get("timestamp") or "", reverse=True)
        return {"cycles": rows}

    @router.get("/active")
    def active():
        path = Path(run_state_dir) / "active_run.json"
        if not path.exists():
            return Response(status_code=204)
        # Race: the producer deletes this file atomically at cycle end. If the
        # polling client hits the path between our exists() and read_text(),
        # treat the FileNotFoundError as 204 (same as the cold path), not 500
        # — the cycle just finished. Mirrors loop_v0.active.
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return Response(status_code=204)
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(
                status_code=500, detail=f"active_run unreadable: {exc}"
            ) from exc
        return data

    @router.get("/findings")
    def findings():
        """Promoted findings (promote_findings output). Newest-first by
        ``promoted_at`` (the row's time field per finding_promotion.py);
        ``{"findings": []}`` if absent."""
        rows = _read_jsonl(Path(memory_dir) / "surfaced_findings.jsonl")
        rows.sort(key=lambda r: r.get("promoted_at") or "", reverse=True)
        return {"findings": rows}

    @router.get("/bubbles")
    def bubbles():
        """The loop's "raise to the human" channel. Newest-first by timestamp;
        ``{"bubbles": []}`` if absent."""
        rows = _read_jsonl(Path(memory_dir) / "coordinator_bubbles.jsonl")
        rows.sort(key=lambda r: r.get("timestamp") or "", reverse=True)
        return {"bubbles": rows}

    @router.get("/health_signals")
    def health_signals():
        """Degraded-but-not-broken signals derived per cycle
        (run_state/health_signals.jsonl): ml-intern "ran but stored 0 papers"
        and qwen "generated but empty content". Newest-first by timestamp;
        ``{"health_signals": []}`` if absent."""
        rows = _read_jsonl(Path(run_state_dir) / "health_signals.jsonl")
        rows.sort(key=lambda r: r.get("timestamp") or "", reverse=True)
        return {"health_signals": rows}

    app.include_router(router)
    return router
