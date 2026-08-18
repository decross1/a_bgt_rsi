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

PERF (2026-08-18): the two probes used to run SERIALLY inside every request —
with the 2 s timeout each, a poll against two down servers blocked a backend
thread for ~4 s, on every dashboard poll. Probes now run in parallel and the
composed payload is held in a short TTL cache (default 8 s), so concurrent
dashboard tabs share one probe round. Honesty is preserved, not approximated:
every role dict carries ``probed_at`` (the UTC instant its probe actually
ran), and a cache hit returns the ORIGINAL ``probed_at`` — the reader can
always compute the true age of the answer. Nothing is ever served from cache
beyond the TTL.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from fastapi import APIRouter

# Cache TTL. Small on purpose: the point is collapsing the 2-4 s serial probe
# cost out of every poll, not making the dashboard stale — a model swap still
# shows within TTL + one poll period.
CACHE_TTL_S = 8.0

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
             opener=urllib.request.urlopen,
             ttl_s: float = CACHE_TTL_S,
             clock=time.monotonic) -> APIRouter:
    """Attach the served-models router (register-fn idiom, as loop_alert).

    ``ttl_s``/``clock`` are injectable for the TTL tests; production callers
    take the defaults.
    """
    targets = dict(endpoints or DEFAULT_ENDPOINTS)
    router = APIRouter(prefix="/api", tags=["served_models"])
    cache: dict = {"at": None, "payload": None}
    lock = threading.Lock()

    def _probe_all() -> dict:
        """Probe every endpoint IN PARALLEL; each result is stamped with the
        UTC instant its probe ran (the honest age carrier on cache hits)."""
        roles = list(targets.items())
        with ThreadPoolExecutor(max_workers=max(1, len(roles))) as pool:
            results = list(pool.map(
                lambda kv: probe(kv[1], opener=opener), roles))
        stamp = (datetime.now(timezone.utc).isoformat()
                 .replace("+00:00", "Z"))
        return {
            role: {**result, "probed_at": stamp}
            for (role, _), result in zip(roles, results)
        }

    @router.get("/served_models")
    def served_models():
        now = clock()
        with lock:
            fresh = (cache["payload"] is not None and cache["at"] is not None
                     and now - cache["at"] < ttl_s)
            if fresh:
                return cache["payload"]
        payload = _probe_all()
        with lock:
            cache["at"] = clock()
            cache["payload"] = payload
        return payload

    app.include_router(router)
    return router
