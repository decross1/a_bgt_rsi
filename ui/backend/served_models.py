"""Live served-model names — the ONE place the UI learns what is actually running.

Why this exists: on 2026-08-16 an A/B window served Qwen **3.8** on :8001 while
the dashboard kept announcing "Qwen3.6-27B · NVFP4-MTP is active". The card
title was a hardcoded string and there was no endpoint anywhere that reported
the live model, so the UI could not have been right — it was printing a belief,
not an observation. A panel that names a model must name the model that is
actually answering.

``GET /api/served_models`` asks each vLLM endpoint's own ``/v1/models`` and
reports what it says:

    {"gemma": {"url": ..., "model": "gemma-4-26b-a4b", "error": null},
     "qwen":  {"url": ..., "model": "qwen3.8-27b-nvfp4-mtp", "error": null}}

Degradation is honest and per-endpoint: an unreachable or unparseable endpoint
gets ``model: null`` plus the reason in ``error`` — never a fallback to a
remembered name, because a remembered name is exactly the failure this replaces.
The frontend renders "unknown" for a null, which is true, instead of a
confident lie.

Read-only: this module makes outbound GETs and touches no repo state.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from fastapi import APIRouter

# Endpoint roles -> base URL. Env-overridable so a window (or a second host)
# does not need a code change; defaults are the pinned production ports.
DEFAULT_ENDPOINTS = {
    "gemma": os.environ.get("VLLM_GEMMA_URL", "http://localhost:8000"),
    "qwen": os.environ.get("VLLM_QWEN_URL", "http://localhost:8001"),
}

# A dashboard poll must not hang on a model server that is mid-load (a vLLM
# start takes ~5 minutes); a short timeout reports "unknown" and moves on.
TIMEOUT_S = 2.0


def probe(url: str, *, timeout: float = TIMEOUT_S, opener=urllib.request.urlopen
          ) -> dict:
    """Ask one endpoint what it serves. Never raises."""
    target = f"{url.rstrip('/')}/v1/models"
    try:
        with opener(target, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, TypeError) as exc:
        return {"url": url, "model": None,
                "error": f"{type(exc).__name__}: {exc}"}
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        return {"url": url, "model": None,
                "error": "unexpected /v1/models payload shape"}
    model = data[0].get("id")
    if not isinstance(model, str) or not model.strip():
        return {"url": url, "model": None, "error": "no model id in payload"}
    return {"url": url, "model": model.strip(), "error": None}


def register(app, *, endpoints: dict[str, str] | None = None,
             opener=urllib.request.urlopen) -> APIRouter:
    """Attach the served-models router (register-fn idiom, as loop_alert)."""
    targets = dict(endpoints or DEFAULT_ENDPOINTS)
    router = APIRouter(prefix="/api", tags=["served_models"])

    @router.get("/served_models")
    def served_models():
        return {role: probe(url, opener=opener) for role, url in targets.items()}

    app.include_router(router)
    return router
