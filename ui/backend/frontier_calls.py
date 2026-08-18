"""Frontier-tier ledger read seam (NARA_FRONTIER_SCREEN armed 2026-08-18).

The frontier tier (D-061: Claude = methods reviewer, Codex = novelty
reviewer; plus the refine-cycle / improve-loop reviewer roles) logs every
CLI invocation to ``run_state/frontier_calls.jsonl`` — row shape pinned by
``schema/frontier_call.schema.json`` — and NONE of it was visible in the
dashboard. This is the read seam for the /model-io "frontier reviews"
section:

- ``GET /api/frontier_calls`` — bounded tail-read of the ledger,
  newest-first PASSTHROUGH rows (verdict may be null: the frontier_cli
  layer always writes null — the review layer owns verdicts; candidate_id
  / reasoning_digest are review-layer fields and may be absent), plus a
  tiny derived summary ``{last_call_ts, calls_24h,
  consecutive_nonzero_exit_by_vendor, vendors_down}`` — the same
  vendor-down signal shape ``orchestrator/loop_health.py``'s
  ``detect_frontier_vendor_down`` uses, derived from the SAME tail (the
  byte bound is stated on the wire; ``calls_24h`` is a floor whenever
  ``window_truncated`` is true).

Why the down signal rides here: on 2026-08-16 the codex CLI returned HTTP
400 for ~6 hours and every D-061 consumer kept reporting "inconclusive"
reviews — one layer up, a dead vendor is indistinguishable from a reviewer
declining to commit. A dead vendor must never look like a quiet reviewer,
so the exit_code streaks are derived HERE (server-side) and the frontend
only passes them through.

Read-only: nothing here writes run_state/.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter

# The ledger lives under run_state/ in the PRIMARY checkout (frontier_cli
# writes it there, not in a UI worktree) — the model_io.py spawn-ledger
# idiom. Env-overridable (UI_FRONTIER_LEDGER) because app.py's register
# call passes no path; tests pin tmp paths via the kwarg.
_PRIMARY = Path("/home/decross1/projects/a_bgt_rsi")
DEFAULT_FRONTIER_LEDGER = _PRIMARY / "run_state" / "frontier_calls.jsonl"

# Bounded tail: ledger rows are ~330 B, so 256 KiB ≈ 800 rows — weeks of
# frontier traffic (the tier fires on promotion candidates only). Rows
# older than the window are honestly out of scope for a live panel.
TAIL_BYTES = 256 * 1024

# How many consecutive nonzero-exit calls make a vendor "down". MIRRORS
# orchestrator/loop_health.py FRONTIER_DOWN_STREAK (= 3: one failure is
# noise, two a coincidence) — mirrored, not imported, so the UI backend
# stays runnable on the thin ui/.venv without the orchestrator package.
FRONTIER_DOWN_STREAK = 3


def _env_path(var: str, default: Path) -> Path:
    """app.py's env-override idiom (UI_* var wins, else the baked default)."""
    value = os.environ.get(var)
    return Path(value) if value else default


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_ts(ts) -> datetime:
    """ISO timestamp -> aware datetime for COMPARISON (never display).
    Unparseable/absent -> datetime.min so a malformed row can never claim
    to be inside the 24h window (model_io.py idiom)."""
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return datetime.min.replace(tzinfo=timezone.utc)


def _tail_records(path: Path, window_bytes: int) -> list[dict]:
    """Parse JSON objects from the last `window_bytes` of a JSONL file, in
    FILE ORDER (oldest-first within the window). Bounded-tail discipline:
    drops the (likely partial) first line of a windowed read and skips
    malformed lines. (activity.py / model_io.py idiom.)"""
    if not path.exists():
        return []
    try:
        size = path.stat().st_size
        window = min(size, window_bytes)
        with open(path, "rb") as fh:
            fh.seek(size - window)
            data = fh.read()
    except OSError:
        return []
    lines = data.decode("utf-8", errors="replace").splitlines()
    if window < size and lines:
        lines = lines[1:]
    out: list[dict] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def _exit_streaks(newest_first: list[dict]) -> dict[str, int]:
    """Per-vendor count of CONSECUTIVE nonzero exit_codes from the newest
    row back — the loop_health detect_frontier_vendor_down shape. Only rows
    carrying a string vendor AND an integer exit_code are judged; an
    unjudgeable row is never scored as success or failure (inviolate rule 4
    stance, same as loop_health). A clean (0) exit closes the vendor's
    streak at whatever it reached."""
    streaks: dict[str, int] = {}
    closed: set[str] = set()
    for rec in newest_first:
        vendor = rec.get("vendor")
        code = rec.get("exit_code")
        if not isinstance(vendor, str) or not vendor \
                or not isinstance(code, int) or isinstance(code, bool):
            continue
        if vendor in closed:
            continue
        if code != 0:
            streaks[vendor] = streaks.get(vendor, 0) + 1
        else:
            streaks.setdefault(vendor, 0)
            closed.add(vendor)
    return streaks


def register(app, *, ledger_path: Path | None = None,
             tail_bytes: int = TAIL_BYTES) -> APIRouter:
    """Attach the frontier-calls router (register-fn idiom, as model_io).

    ``ledger_path`` resolves None → ``UI_FRONTIER_LEDGER`` env override →
    the primary checkout's ``run_state/frontier_calls.jsonl``; tests pin a
    tmp path via the kwarg. ``tail_bytes`` is the tail-read bound — tests
    shrink it to prove the bound is real."""
    if ledger_path is None:
        ledger_path = _env_path("UI_FRONTIER_LEDGER", DEFAULT_FRONTIER_LEDGER)
    ledger_path = Path(ledger_path)
    router = APIRouter(prefix="/api", tags=["frontier_calls"])

    @router.get("/frontier_calls")
    def frontier_calls(limit: int = 30):
        """Newest-first passthrough rows from the ledger tail + the derived
        summary. Degrades honestly: an absent file is ``available: false``
        with empty rows, never a 500 and never fabricated rows."""
        capped = min(max(limit, 1), 100)
        try:
            size = ledger_path.stat().st_size
            available = True
        except OSError:
            size = 0
            available = False
        rows = _tail_records(ledger_path, tail_bytes)
        newest_first = list(reversed(rows))

        last_call_ts = next(
            (r["timestamp"] for r in newest_first
             if isinstance(r.get("timestamp"), str) and r["timestamp"]),
            None)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        calls_24h = sum(1 for r in rows
                        if _parse_ts(r.get("timestamp")) >= cutoff)
        streaks = _exit_streaks(newest_first)
        vendors_down = sorted(v for v, n in streaks.items()
                              if n >= FRONTIER_DOWN_STREAK)

        return {
            "available": available,
            # Pure passthrough — the schema's row shape, verdict/candidate_id
            # /reasoning_digest exactly as written (null / absent included).
            "calls": newest_first[:capped],
            "rows_in_window": len(rows),
            "summary": {
                "last_call_ts": last_call_ts,
                # Derived from the SAME tail — a floor, not a census, when
                # window_truncated is true.
                "calls_24h": calls_24h,
                "consecutive_nonzero_exit_by_vendor": streaks,
                "vendors_down": vendors_down,
                "down_streak_threshold": FRONTIER_DOWN_STREAK,
            },
            "window_bytes": tail_bytes,
            # True iff the file extends beyond the tail window — older rows
            # exist that were never examined (summary included).
            "window_truncated": size > tail_bytes,
            "generated_at": _utcnow_iso(),
        }

    app.include_router(router)
    return router
