"""Loop-alert + ideas-board read seams (2026-08-14 UI work order A + C).

Two read-only GETs, wired by ``register`` into the existing FastAPI app:

- ``GET /api/loop_alert`` — reads ``run_state/loop_alert.json``
  (``{level: red|amber|ok, reasons[], updated_at}``, written every executed
  coordinator cycle by orchestrator/loop_health.write_alert_flag). Returns
  the file's JSON verbatim; 204 No Content when the file is absent (mirrors
  ``coordinator.active``). Staleness (the ~26h "silent cron" check) is the
  FRONTEND's judgment off ``updated_at`` — the backend never editorializes.
- ``GET /api/ideas`` — reads ``memory/ideas.md`` (the deterministic
  idea-ledger projection, workers/idea_projection.py). Returns
  ``{"markdown": "<file text>"}``; 204 when absent.

Mirrors the ``coordinator.py`` register-fn idiom: absent file = 204/empty
(never a 500 for a merely-missing gitignored artifact), unreadable file =
an honest 500 with the error in ``detail``. The UI never writes
``run_state/`` or ``memory/``.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response


def register(
    app,
    *,
    run_state_dir: Path,
    memory_dir: Path,
) -> APIRouter:
    """Attach the loop-alert + ideas router. ``run_state_dir`` carries
    loop_alert.json; ``memory_dir`` carries ideas.md (the same split the
    coordinator/human_todo registrations use)."""
    router = APIRouter(prefix="/api", tags=["loop_alert"])

    @router.get("/loop_alert")
    def loop_alert():
        """The coordinator's cross-cycle alert flag, verbatim. 204 when the
        file is absent (no cycle has ever written it on this checkout)."""
        path = Path(run_state_dir) / "loop_alert.json"
        if not path.exists():
            return Response(status_code=204)
        # Race: a coordinator cycle rewrites the flag atomically; if the
        # poll hits between exists() and read_text(), FileNotFoundError is
        # the cold path (204), not a 500 (mirrors coordinator.active).
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return Response(status_code=204)
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(
                status_code=500, detail=f"loop_alert unreadable: {exc}"
            ) from exc
        return data

    @router.get("/ideas")
    def ideas():
        """memory/ideas.md verbatim (a deterministic projection of the idea
        ledger — plain markdown is the correct render). 204 when absent."""
        path = Path(memory_dir) / "ideas.md"
        if not path.exists():
            return Response(status_code=204)
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return Response(status_code=204)
        except OSError as exc:
            raise HTTPException(
                status_code=500, detail=f"ideas.md unreadable: {exc}"
            ) from exc
        return {"markdown": text}

    app.include_router(router)
    return router
