"""Per-iteration filesystem cache for heavy LOOP_V0 payloads.

Why this exists: Nara dispatches a five-step chain, and on iter-009/010/011
the chain truncated mid-emission because Nara was copying the full neighbors
array (~1500 tokens) into every downstream tool_call's args, which Gemma 4's
inline `<|tool_call>` text format can't fit in the 1024 per-turn cap. The
fix is reference-passing: workers fetch heavy payloads from a per-iteration
cache by `iteration_id` instead of receiving them in args. Tool_call
emissions stay small; downstream steps still see the full payload.

This module is intentionally tiny (~50 LOC) and reuses the atomic-write
pattern from `orchestrator/runtime.py::PyRuntime.write_state`. Nara writes
each tool's result to the cache after a successful dispatch; workers read
by `iteration_id` + a step-name key.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_ROOT = REPO_ROOT / "run_state" / "iteration_cache"


def cache_dir(iteration_id: str) -> Path:
    """Return the per-iteration cache directory (does not create it)."""
    return CACHE_ROOT / iteration_id


def write_entry(iteration_id: str, key: str, payload: dict) -> Path:
    """Atomic JSON write of one step's payload. Creates the iteration
    directory on first call. Returns the written path.

    `key` is the captured-step name (e.g. "hypothesis", "retrieval",
    "novelty", "critique"). Multiple writes with the same key overwrite
    atomically.
    """
    d = cache_dir(iteration_id)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{key}.json"
    # D-075 R3b clobber guard: on 2026-08-18 a double critic dispatch
    # erased a 470s debate transcript (iter-...-007) via last-write-wins.
    # Evidence is never destroyed: when an overwrite would drop a debate
    # block the prior payload is preserved side-by-side as <key>.json.N
    # (append-only versions; readers still see last-write-wins at <key>).
    if path.exists():
        try:
            old = json.loads(path.read_text())
            old_debate = (old.get("result") or {}).get("debate")
            new_debate = (payload.get("result") or {}).get("debate")
            if old_debate and not new_debate:
                n = 1
                while (d / f"{key}.json.{n}").exists():
                    n += 1
                os.replace(path, d / f"{key}.json.{n}")
        except (json.JSONDecodeError, OSError):
            pass  # unreadable prior entry: plain overwrite, never a crash
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    os.replace(tmp, path)
    return path


def read_entry(iteration_id: str, key: str) -> dict:
    """Load one step's payload by iteration_id + key. Raises KeyError with
    the missing path embedded so callers can diagnose cache misses cleanly
    (a worker called with a stale or wrong iteration_id surfaces here)."""
    path = cache_dir(iteration_id) / f"{key}.json"
    if not path.exists():
        raise KeyError(
            f"iteration cache miss: {path} not found "
            f"(iteration_id={iteration_id!r}, key={key!r})"
        )
    return json.loads(path.read_text())


def has_entry(iteration_id: str, key: str) -> bool:
    """Non-raising existence check (handy for tests + journal_writer's
    'gather what's present' final pass)."""
    return (cache_dir(iteration_id) / f"{key}.json").exists()
