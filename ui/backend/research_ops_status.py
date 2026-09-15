"""Thin read-only API adapter for the registered research-operations projection."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from fastapi import APIRouter, HTTPException

DEFAULT_REPO = Path("/home/decross1/projects/a_bgt_rsi")


def register(app, *, repo_root: Path = DEFAULT_REPO,
             ingestion_root: Path | None = None,
             projector: Callable[..., dict] | None = None) -> None:
    router = APIRouter()

    @router.get("/api/research_ops_status")
    def research_ops_status():
        producer = projector
        if producer is None:
            try:
                from orchestrator.research_ops_status import project_research_ops_status
            except ImportError as exc:
                raise HTTPException(status_code=503,
                                    detail="research status source unavailable") from exc
            producer = project_research_ops_status
        return producer(repo_root=repo_root, ingestion_root=ingestion_root)

    app.include_router(router)
