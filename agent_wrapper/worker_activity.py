"""Per-call inference-internals emitter.

After each real inference call the wrapper records one honest row of
per-call internals so the UI can surface what actually happened on the
last call — tokens generated vs. target, throughput, and a rough ETA.

This is PER-CALL data (one row per finished call), not a live
per-decode-step stream. Because it is real data, the UI's synthetic
marker drops (`synthetic: false`). Live streaming is a future upgrade,
not this.

Append-only and pure: the emitter NEVER raises. A logging failure must
never break an inference call, so every failure path is swallowed and
the function returns cleanly.
"""
from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOG_PATH = REPO_ROOT / "logs" / "worker_activity.jsonl"


def emit_worker_activity(
    *,
    run_id: str,
    task_id: str,
    output_tokens: int,
    max_tokens: int,
    latency_ms: float,
    timestamp: str,
    backend: str | None = None,
    model: str | None = None,
    log_path: Path | str | None = None,
) -> None:
    """Append one per-call inference-internals row to worker_activity.jsonl.

    backend/model: registry name + served-model-name that handled the call
    (UI attribution, 2026-06-10). None on legacy callers — fields omitted.
    log_path None resolves to DEFAULT_LOG_PATH at call time (not def time)
    so tests can monkeypatch the module attribute.

    Never raises: any failure (bad arithmetic, unwritable path) is
    swallowed so a logging failure cannot break the inference call.
    """
    try:
        if log_path is None:
            log_path = DEFAULT_LOG_PATH
        latency_s = latency_ms / 1000.0
        tok_per_s = output_tokens / latency_s if latency_s > 0 else 0.0
        if tok_per_s == 0.0:
            eta_s = None
        else:
            eta_s = max(0, max_tokens - output_tokens) / tok_per_s

        row = {
            "timestamp": timestamp,
            "run_id": run_id,
            "task_id": task_id,
            "tokens_generated": output_tokens,
            "tokens_target": max_tokens,
            "tok_per_s": tok_per_s,
            "eta_s": eta_s,
            "synthetic": False,
        }
        if backend is not None:
            row["backend"] = backend
        if model is not None:
            row["model"] = model

        p = Path(log_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        # A logging failure must never break the inference call.
        return
