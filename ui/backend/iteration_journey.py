"""Read-only iteration-journey endpoint — the data layer of the S2 cockpit
reframe (PipelineJourney). One GET returns the WHOLE ``memory/loop_memory.jsonl``
row for an iteration as the ``IterationRecord`` the journey view renders (schemas.ts
IterationJourneyResponse). The row already models the full pipeline journey:
hypothesis, retrieval.relevance, novelty, critique, redteam, meta_review,
gate_status, experiment_outcome.

- ``GET /api/iteration/{iteration_id}/journey`` — the full journey for one
  iteration. Unknown / malformed / pathological iteration_id =>
  ``{"found": false, "iteration_id": <arg>}`` at HTTP 200 (NOT 404 — the journey
  view degrades in place, never 404-blanks).

The journey view is read-only: this endpoint WRITES NOTHING. It opens no file for
writing; it only reads. It mirrors finding_detail.py: the same ``_read_jsonl``
tolerance of absent files and malformed/non-dict lines (so a producer-owned
garbled line never 500s), the same ``_safe``/``_encoder_safe`` encoder-overflow
guard (a deeply-nested / non-finite-float / huge-bigint field degrades to null,
never 500s the encoder). The iteration_id is validated against the
``iter-YYYY-MM-DD-NNN`` shape Nara emits (loop_v0._safe_iteration_id); a
non-conforming id can never be used as a path and joins to nothing => found:false,
never traverses.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from fastapi import APIRouter, HTTPException


# A loop_memory field is a scalar or a small nested block in every valid row. A
# producer that wrote a pathological value there — a value nested THOUSANDS of
# levels deep, a multi-thousand-digit bigint, or a non-finite float
# (NaN/Infinity) — yields valid JSON that survives json.loads, but FastAPI's
# JSONResponse encoder walks it and 500s the endpoint AFTER the read's
# try/except (during response encoding): a deep nest RecursionErrors, a huge int
# raises "Exceeds the limit (4300 digits)", and a non-finite float either raises
# or emits non-compliant ``NaN``. The same class finding_detail.py /
# todo_cockpit.py guards. Mirror finding_detail: cap the value's depth, bound its
# int magnitude, and reject non-finite floats; drop any row that trips the guard
# (degrade the WHOLE row to found:false, never 500 — the journey row is surfaced
# in full, so any pathological member would reach the encoder).
_MAX_FIELD_DEPTH = 32
# Comfortably under CPython's 4300-digit int->str limit: a real id / count never
# approaches it; anything bigger is producer garbage.
_MAX_INT_DIGITS = 600


def _encoder_safe(value, limit: int = _MAX_FIELD_DEPTH) -> bool:
    """True if `value` can be JSON-encoded without 500ing the response encoder:
    it nests no deeper than `limit`, contains no int whose magnitude exceeds the
    digit bound, contains no non-finite float (NaN/Infinity/-Infinity), and
    contains no string carrying a lone/unpaired surrogate code point.
    Iterative (no recursion of its own — it must not itself overflow on the
    pathological input it guards). Mirrors finding_detail._encoder_safe."""
    stack = [(value, 0)]
    while stack:
        node, depth = stack.pop()
        if depth > limit:
            return False
        if isinstance(node, bool):
            continue  # bool before int: a bool is encoder-safe and not "huge"
        if isinstance(node, int):
            if abs(node) >= 10**_MAX_INT_DIGITS:
                return False
        elif isinstance(node, float):
            if not math.isfinite(node):
                return False
        elif isinstance(node, str):
            # A producer-written ``"\udXXX"`` escape decodes through json.loads
            # into a LONE surrogate str: valid to parse, but FastAPI's
            # JSONResponse emits UTF-8 and a lone surrogate is not encodable, so
            # the encoder raises UnicodeEncodeError AFTER the read's try/except
            # (the same valid-to-parse / fatal-to-encode class as NaN/Infinity).
            # `str.isascii()` fast-paths the common case; only non-ASCII strings
            # pay the encode probe, and only a surrogate trips it.
            if not node.isascii():
                try:
                    node.encode("utf-8")
                except UnicodeEncodeError:
                    return False
        elif isinstance(node, dict):
            for k, v in node.items():
                # A surrogate can ride a dict KEY too (a producer ``"\udXXX"``
                # key parses fine but 500s the same UTF-8 encode). json.loads
                # keys are always str, so the key only needs the surrogate probe
                # — push it at the same depth so the str-branch inspects it.
                stack.append((k, depth))
                stack.append((v, depth + 1))
        elif isinstance(node, list):
            for v in node:
                stack.append((v, depth + 1))
    return True


def _safe(value):
    """The value if it is encoder-safe, else None — degrade rather than 500 the
    response (never coerced into a different value; a safe value flows through
    untouched). Mirrors finding_detail._safe."""
    return value if _encoder_safe(value) else None


def _safe_iteration_id(iteration_id: str) -> bool:
    """True iff `iteration_id` is a shape Nara emits — ``iter-YYYY-MM-DD-NNN``
    (LOOP_V0.md §iteration_record). We refuse any path-traversal or
    non-conforming id; a refused id joins to nothing (found:false), and is never
    used as a filesystem path. Mirrors loop_v0._safe_iteration_id's allow-set,
    but RETURNS a bool (the journey endpoint degrades to found:false, it never
    raises a 400 the way the loop_v0 journal route does)."""
    if not iteration_id or len(iteration_id) > 64:
        return False
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")
    return all(ch in allowed for ch in iteration_id)


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
                    parsed = json.loads(line)
                except ValueError:
                    # JSONDecodeError (a subclass) for syntactically-bad lines,
                    # PLUS the bare ValueError CPython raises when a numeric
                    # literal exceeds the int<->str digit limit (a >4300-digit
                    # bigint a producer drifted in): json.loads itself raises
                    # BEFORE the encoder ever sees it, and that ValueError is NOT
                    # a JSONDecodeError. Skipping malformed rows keeps the
                    # endpoint useful while a primary-session bug is fixed.
                    continue
                # Bare scalars/arrays are valid JSON but not row records; drop
                # them like malformed lines (mirrors finding_detail.py).
                if not isinstance(parsed, dict):
                    continue
                rows.append(parsed)
    except FileNotFoundError:
        # Delete-race: the producer atomically replaces/unlinks these JSONL logs,
        # so the file can vanish between our exists() check and open() (or
        # mid-iteration). A file that is gone is, from the reader's view, absent
        # — degrade to "no rows", NOT 500. Mirrors finding_detail.py.
        return []
    except OSError as exc:
        # A genuinely unreadable file (permissions, I/O error) is a real
        # server-side fault, not the benign delete-race — surface it as 500.
        raise HTTPException(status_code=500, detail=f"unreadable: {exc}") from exc
    return rows


def register(app, *, memory_dir: Path) -> APIRouter:
    """Attach the iteration-journey router. Reads loop_memory.jsonl from
    ``memory_dir`` (the same memory dir coordinator.register / finding_detail use,
    wired as ``register(app, memory_dir=Path(coordinator_memory))``). Read-only:
    writes nothing, ever."""
    router = APIRouter(tags=["iteration_journey"])

    @router.get("/api/iteration/{iteration_id}/journey")
    def iteration_journey(iteration_id: str):
        """The FULL loop_memory row for one iteration (the PipelineJourney).
        Unknown / malformed / pathological iteration_id => found:false at 200 (the
        journey view degrades in place, never 404-blanks). Never 500s on
        absent/garbled data files; writes NOTHING."""
        # A non-conforming id can never name a real iteration; refuse the join
        # entirely (it is never used as a path, so this also forecloses
        # traversal). Degrade to found:false at 200, never raise.
        if not _safe_iteration_id(iteration_id):
            return {"found": False, "iteration_id": iteration_id}

        row = None
        for candidate in _read_jsonl(Path(memory_dir) / "loop_memory.jsonl"):
            if candidate.get("iteration_id") == iteration_id:
                row = candidate  # last write wins, were an iteration_id duplicated
        if row is None:
            return {"found": False, "iteration_id": iteration_id}

        # The whole row is surfaced as the IterationRecord. A single pathological
        # member (deep nest / huge int / non-finite float) would reach the
        # encoder and 500 the WHOLE response — _safe degrades the entire row to
        # found:false rather than 500 (the row is surfaced in full, so we cannot
        # null one member and keep the rest meaningful as a "journey"). A clean
        # row flows through untouched (never coerced).
        if _safe(row) is None:
            return {"found": False, "iteration_id": iteration_id}

        return {"found": True, "iteration_id": iteration_id, "iteration": row}

    app.include_router(router)
    return router
