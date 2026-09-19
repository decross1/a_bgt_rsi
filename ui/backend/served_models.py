"""Bounded live inventory for the three registered local model services.

``GET /api/served_models`` retains the original role-keyed response and its
``url``, ``model``, ``error`` and ``probed_at`` fields. It now also reports
the registered Flash-Next research candidate and independently describes
static configuration, the observed service identity, and live request stats.

A reachable idle service is not offline; a configured context limit is not an
observed statistic; and a candidate answering on :8012 is not qualification
evidence or permission to promote it. Per-model memory is intentionally absent
because GB10 unified memory does not make vLLM's configured GPU-memory fraction
a measured model allocation.

Production targets are a fixed loopback allowlist. Reads are GET-only,
redirect-free, size-bounded and cached for eight seconds. Test callers may
inject known-role targets and an opener, but no API request can supply a URL.
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter
from sampler.sources.vllm_metrics import VllmMetricsAccumulator

from .model_runtime import project_model_runtime

CACHE_TTL_S = 8.0
TIMEOUT_S = 2.0
MAX_MODELS_BYTES = 1_000_000
MAX_METRICS_BYTES = 2_000_000

# Deployment facts, not mutable UI configuration. Flash stays a research
# candidate even while it is the only live server. The default candidate is
# the registered Mia checkpoint; a controller-selected alternate remains
# separately identified by the runtime projection.
REGISTERED_MODELS: dict[str, dict[str, Any]] = {
    "gemma": {
        "url": "http://127.0.0.1:8000",
        "configured_model": "gemma-4-26b-a4b",
        "configured_max_context_tokens": 32_768,
        "deployment_role": "production_resident",
        "benchmark_cohort": "resident",
    },
    "qwen": {
        "url": "http://127.0.0.1:8001",
        "configured_model": "qwen3.8-27b-nvfp4-mtp",
        "configured_max_context_tokens": 16_384,
        "deployment_role": "production_resident",
        "benchmark_cohort": "resident",
    },
    "flash": {
        "url": "http://127.0.0.1:8012",
        "configured_model": "qwen3.8-flash-next-mia",
        "configured_max_context_tokens": 32_768,
        "deployment_role": "research_candidate",
        "benchmark_cohort": "flash",
    },
}

# Backward-compatible public name used by older importers. Values are literals
# rather than environment-derived URLs, so startup configuration cannot turn
# the backend into an SSRF proxy.
DEFAULT_ENDPOINTS = {role: row["url"] for role, row in REGISTERED_MODELS.items()}

# The active personal-session projection may select this second fixed Flash
# endpoint.  Neither the HTTP request nor environment variables can add a URL.
PERSONAL_FLASH_TARGETS: dict[str, dict[str, Any]] = {
    "mia": {**REGISTERED_MODELS["flash"], "metrics_backend": "vllm"},
    "sglang": {
        "url": "http://127.0.0.1:30080",
        "configured_model": "nvidia/Qwen3.8-Flash-Next-NVFP4",
        "configured_max_context_tokens": 32_768,
        "deployment_role": "research_candidate",
        "benchmark_cohort": "flash",
        "metrics_backend": "sglang",
    },
}
_CANDIDATE_ID = re.compile(r"[0-9a-f]{64}\Z")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_FIXED_OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}), _NoRedirect()
).open


class _InvalidResponse(ValueError):
    pass


def _read_limited(response, limit: int) -> bytes:
    """Read at most ``limit + 1`` bytes, including simple test doubles."""
    try:
        raw = response.read(limit + 1)
    except TypeError:  # legacy in-memory test responses expose read() only
        raw = response.read()
    if not isinstance(raw, bytes) or len(raw) > limit:
        raise _InvalidResponse("response exceeds the byte limit")
    return raw


def _get_bytes(target: str, *, timeout: float, opener, limit: int
               ) -> tuple[bytes | None, str, str | None]:
    """Return bytes plus ``available|unreachable|invalid_response``."""
    try:
        with opener(target, timeout=timeout) as response:
            status = getattr(response, "status", None)
            if status is None and hasattr(response, "getcode"):
                status = response.getcode()
            if status is not None and status != 200:
                raise _InvalidResponse(f"HTTP {status}")
            if hasattr(response, "geturl") and response.geturl() != target:
                raise _InvalidResponse("redirected response")
            return _read_limited(response, limit), "available", None
    except urllib.error.HTTPError as exc:
        return None, "invalid_response", f"HTTPError: HTTP {exc.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return None, "unreachable", f"{type(exc).__name__}: {exc}"
    except (UnicodeError, ValueError, TypeError) as exc:
        return None, "invalid_response", f"{type(exc).__name__}: {exc}"


def _strict_json(raw: bytes) -> Any:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise _InvalidResponse("duplicate JSON key")
            result[key] = value
        return result

    def nonfinite(value):
        raise _InvalidResponse(f"non-finite JSON number: {value}")

    return json.loads(
        raw.decode("utf-8"), object_pairs_hook=unique, parse_constant=nonfinite
    )


def _probe_models(url: str, *, timeout: float, opener) -> dict[str, Any]:
    target = f"{url.rstrip('/')}/v1/models"
    raw, endpoint_status, failure = _get_bytes(
        target, timeout=timeout, opener=opener, limit=MAX_MODELS_BYTES
    )
    if raw is None:
        return {
            "url": url,
            "model": None,
            "error": failure,
            "models_endpoint_status": endpoint_status,
        }
    try:
        payload = _strict_json(raw)
        data = payload.get("data") if isinstance(payload, dict) else None
        if (not isinstance(data, list) or len(data) != 1
                or not isinstance(data[0], dict)):
            raise _InvalidResponse("unexpected /v1/models payload shape")
        model = data[0].get("id")
        if not isinstance(model, str) or not model.strip():
            raise _InvalidResponse("no model id in payload")
        model = model.strip()
        observed_context = data[0].get("max_model_len")
        if (
            isinstance(observed_context, bool)
            or not isinstance(observed_context, int)
            or not 1 <= observed_context <= 10_000_000
        ):
            observed_context = None
    except (UnicodeError, ValueError, TypeError) as exc:
        return {
            "url": url,
            "model": None,
            "error": str(exc),
            "models_endpoint_status": "invalid_response",
        }
    return {
        "url": url,
        "model": model,
        "observed_max_context_tokens": observed_context,
        "error": None,
        "models_endpoint_status": "available",
    }


def probe(url: str, *, timeout: float = TIMEOUT_S, opener=_FIXED_OPENER) -> dict:
    """Legacy one-endpoint model probe. It retains its exact return shape."""
    result = _probe_models(url, timeout=timeout, opener=opener)
    return {key: result[key] for key in ("url", "model", "error")}


def _probe_metrics(
    url: str,
    *,
    timeout: float,
    opener,
    accumulator: VllmMetricsAccumulator,
    metric_clock,
) -> dict[str, Any]:
    target = f"{url.rstrip('/')}/metrics"
    raw, endpoint_status, failure = _get_bytes(
        target, timeout=timeout, opener=opener, limit=MAX_METRICS_BYTES
    )
    if raw is None:
        accumulator.reset()
        return {
            "metrics_endpoint_status": endpoint_status,
            "metrics": None,
            "metrics_error": failure,
        }
    try:
        text = raw.decode("utf-8")
        metrics, error = accumulator.observe(text, now=metric_clock())
    except (UnicodeError, ValueError, TypeError) as exc:
        accumulator.reset()
        metrics, error = None, f"{type(exc).__name__}: {exc}"
    if metrics is None:
        return {
            "metrics_endpoint_status": "invalid_response",
            "metrics": None,
            "metrics_error": error or "invalid /metrics response",
        }
    return {
        "metrics_endpoint_status": "available",
        "metrics": metrics,
        "metrics_error": None,
    }


def _compose_row(role: str, model: dict[str, Any], metrics: dict[str, Any],
                 stamp: str, configured: dict[str, Any] | None = None
                 ) -> dict[str, Any]:
    configured = configured or REGISTERED_MODELS[role]
    endpoint_status = model["models_endpoint_status"]
    service_status = (
        "online" if endpoint_status == "available"
        else "offline" if endpoint_status == "unreachable"
        else "unknown"
    )
    identity_status = (
        "match" if model["model"] == configured["configured_model"]
        else "mismatch" if model["model"] is not None
        else "unknown"
    )
    live = metrics["metrics"]
    activity_status = (
        "busy"
        if live is not None
        and (live["running_requests"] > 0 or live["waiting_requests"] > 0)
        else "idle"
        if live is not None
        else "unknown"
    )
    return {
        # Original contract, unchanged.
        "url": model["url"],
        "model": model["model"],
        "error": model["error"],
        "probed_at": stamp,
        # Registered configuration.
        "configured_model": configured["configured_model"],
        "configured_max_context_tokens": configured[
            "configured_max_context_tokens"
        ],
        "observed_max_context_tokens": model.get("observed_max_context_tokens"),
        "deployment_role": configured["deployment_role"],
        "benchmark_cohort": configured["benchmark_cohort"],
        "promotion_authorized": configured.get("promotion_authorized", False),
        # Independent live observations.
        "models_endpoint_status": endpoint_status,
        "service_status": service_status,
        "identity_status": identity_status,
        "metrics_endpoint_status": metrics["metrics_endpoint_status"],
        "activity_status": activity_status,
        "metrics": live,
        "metrics_error": metrics["metrics_error"],
    }


def register(
    app,
    *,
    endpoints: dict[str, str] | None = None,
    opener=_FIXED_OPENER,
    ttl_s: float = CACHE_TTL_S,
    clock=time.monotonic,
    metric_clock=time.monotonic,
    runtime_projector=project_model_runtime,
    runtime_ttl_s: float = 1.0,
) -> APIRouter:
    """Attach the cached, read-only served-model inventory router.

    ``endpoints`` is an in-process test seam limited to registered role names.
    The application calls this without it and always uses the fixed targets.
    """
    production_targets = endpoints is None
    targets = dict(DEFAULT_ENDPOINTS if production_targets else endpoints)
    if not targets or any(role not in REGISTERED_MODELS for role in targets):
        raise ValueError("served-model targets must use registered roles")
    if endpoints is None and targets != DEFAULT_ENDPOINTS:
        raise ValueError("production served-model targets differ from the allowlist")

    router = APIRouter(prefix="/api", tags=["served_models"])
    cache: dict[str, Any] = {"at": None, "payload": None}
    lock = threading.Lock()
    runtime_cache: dict[str, Any] = {"at": None, "payload": None}
    runtime_lock = threading.Lock()
    accumulators = {role: VllmMetricsAccumulator() for role in targets}
    selected_flash: dict[str, Any] = {
        "signature": ("mia", None),
        "configured": PERSONAL_FLASH_TARGETS["mia"],
    }

    def _flash_selection() -> tuple[tuple[str, str | None], dict[str, Any]]:
        if not production_targets:
            return ("injected", None), REGISTERED_MODELS["flash"]
        try:
            runtime = runtime_projector()
        except (OSError, ValueError, TypeError, AttributeError):
            runtime = None
        if isinstance(runtime, dict):
            if runtime.get("mode_source") == "permanent_deployment" and runtime.get("production_authorized") is True:
                return ("sglang", runtime.get("candidate_id")), {
                    **PERSONAL_FLASH_TARGETS["sglang"],
                    "deployment_role": "production_resident",
                    "promotion_authorized": True,
                }
            endpoint = runtime.get("personal_endpoint")
            candidate_id = runtime.get("candidate_id")
            if (
                runtime.get("mode_source") == "personal_session_state"
                and runtime.get("mode") == "candidate_research"
                and runtime.get("phase") in {"starting", "ready"}
                and isinstance(endpoint, str)
                and endpoint in PERSONAL_FLASH_TARGETS
                and _CANDIDATE_ID.fullmatch(str(candidate_id or ""))
            ):
                return (endpoint, candidate_id), PERSONAL_FLASH_TARGETS[endpoint]
        return ("mia", None), PERSONAL_FLASH_TARGETS["mia"]

    def _probe_all(configured_rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
        roles = [
            (
                role,
                configured_rows[role]["url"] if production_targets else targets[role],
            )
            for role in targets
        ]
        # Both paths for all roles share one parallel round: a down candidate
        # cannot add its two timeout ceilings serially to a dashboard request.
        with ThreadPoolExecutor(max_workers=max(1, 2 * len(roles))) as pool:
            models = {
                role: pool.submit(
                    _probe_models, url, timeout=TIMEOUT_S, opener=opener
                )
                for role, url in roles
            }
            live_metrics = {
                role: pool.submit(
                    _probe_metrics,
                    url,
                    timeout=TIMEOUT_S,
                    opener=opener,
                    accumulator=accumulators[role],
                    metric_clock=metric_clock,
                )
                for role, url in roles
            }
            model_rows = {role: future.result() for role, future in models.items()}
            metric_rows = {
                role: future.result() for role, future in live_metrics.items()
            }
        stamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        return {
            role: _compose_row(
                role, model_rows[role], metric_rows[role], stamp,
                configured_rows[role],
            )
            for role, _ in roles
        }

    @router.get("/served_models")
    def served_models():
        # Hold the lock through a cache miss so concurrent dashboard tabs share
        # one bounded probe round and one counter-accumulator observation.
        with lock:
            if production_targets:
                signature, configured_flash = _flash_selection()
                if signature != selected_flash["signature"]:
                    accumulators["flash"].reset()
                    accumulators["flash"] = VllmMetricsAccumulator(
                        backend=configured_flash["metrics_backend"]
                    )
                    selected_flash["signature"] = signature
                    selected_flash["configured"] = configured_flash
                    cache["at"] = None
                    cache["payload"] = None
                configured_rows = {
                    role: (
                        selected_flash["configured"]
                        if role == "flash"
                        else REGISTERED_MODELS[role]
                    )
                    for role in targets
                }
                if configured_flash.get("promotion_authorized") is True:
                    for role in ("gemma", "qwen"):
                        if role in configured_rows:
                            configured_rows[role] = {**configured_rows[role], "deployment_role": "rollback_available"}
            else:
                configured_rows = {role: REGISTERED_MODELS[role] for role in targets}
            now = clock()
            fresh = (
                cache["payload"] is not None
                and cache["at"] is not None
                and now - cache["at"] < ttl_s
            )
            if fresh:
                return cache["payload"]
            payload = _probe_all(configured_rows)
            cache["at"] = clock()
            cache["payload"] = payload
            return payload

    @router.get("/model_runtime")
    def model_runtime():
        with runtime_lock:
            now = clock()
            fresh = (
                runtime_cache["payload"] is not None
                and runtime_cache["at"] is not None
                and now - runtime_cache["at"] < runtime_ttl_s
            )
            if fresh:
                return runtime_cache["payload"]
            payload = runtime_projector()
            runtime_cache["at"] = clock()
            runtime_cache["payload"] = payload
            return payload

    app.include_router(router)
    return router
