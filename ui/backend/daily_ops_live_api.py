"""Read-only HTTP boundary for the independent daily-operations v3 view.

This router deliberately does not reuse the v1/v2 summary cache or either
legacy writer.  A caller either receives a freshly derived, schema-checked v3
projection or an explicit temporary-unavailable response.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response

from .daily_ops_live import live_summary, validate_agents, validate_live


def _private_headers(response: Response) -> None:
    """Owner-directed card context must never enter a shared HTTP cache."""
    response.headers["Cache-Control"] = "no-store"
    response.headers["Vary"] = "Authorization, Origin"


def register(
    app,
    *,
    repo_root: Path,
    summary: Callable[[], dict] | None = None,
    owner_authorizer: Callable[[Request], bool] | None = None,
) -> APIRouter:
    """Attach the additive, read-only v3 summary endpoint.

    ``summary`` is test-only dependency injection. Production always reads
    the live projection rooted at ``repo_root`` and never a v1/v2 cache file.
    The owner authorizer is the same bearer/allowed-origin boundary as the
    existing private owner-message route; no authorizer means no private view.
    """
    router = APIRouter(prefix="/api/daily-ops/v3", tags=["daily-ops-v3"])
    build = summary or (lambda: live_summary(Path(repo_root)))

    @router.get("/summary")
    def get_summary(request: Request, response: Response):
        private_headers = {"Cache-Control": "no-store", "Vary": "Authorization, Origin"}
        if owner_authorizer is None:
            raise HTTPException(status_code=503, detail="owner authentication is unavailable",
                                headers=private_headers)
        try:
            authorized = owner_authorizer(request)
        except Exception as exc:
            raise HTTPException(status_code=503, detail="owner authentication is unavailable",
                                headers=private_headers) from exc
        if authorized is not True:
            raise HTTPException(status_code=403, detail="owner authentication required",
                                headers=private_headers)
        try:
            value = build()
            validate_live(value, validate_agents)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise HTTPException(
                status_code=503,
                detail="daily operations v3 live projection is unavailable or invalid",
                headers=private_headers,
            ) from exc
        _private_headers(response)
        return value

    app.include_router(router)
    return router
