"""Read-only finding-detail endpoint — the data layer of the /todo tutor (U1,
2026-06-17 work order). One GET joins a single ``memory/surfaced_findings.jsonl``
row (the finding) with its source iteration in ``memory/loop_memory.jsonl``,
returning the compact ``FindingDetail`` shape (schemas.ts) the tutor renders.

- ``GET /api/finding/{finding_id}`` — the finding overview. Unknown finding_id
  => ``{"found": false, "finding_id": <arg>}`` at HTTP 200 (NOT 404 — the tutor
  degrades to "detail unavailable" in place, never 404-blanks).

The tutor is fenced from the verdict (D-054): this endpoint WRITES NOTHING. It
opens no file for writing; it only reads. Effective status mirrors
``human_todo._finding_review_items``: the base finding row's ``status`` overridden
by the LAST ``surfaced_findings.status.jsonl`` audit row for that finding_id
(absent file => base status; status is NEVER coerced). Mirrors the
``coordinator.py`` register-fn idiom (same ``_read_jsonl`` tolerance of absent
files and malformed/non-dict lines), so a producer-owned garbled line never 500s.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from fastapi import APIRouter, HTTPException


# A surfaced finding/iteration field is a scalar (or, for ``evidence``, a small
# dict) in every valid row. A producer that wrote a pathological value there —
# a value nested THOUSANDS of levels deep, a multi-thousand-digit bigint, or a
# non-finite float (NaN/Infinity) — yields valid JSON that survives json.loads,
# but FastAPI's JSONResponse encoder walks it and 500s the endpoint AFTER the
# read's try/except (during response encoding): a deep nest RecursionErrors, a
# huge int raises "Exceeds the limit (4300 digits)", and a non-finite float
# either raises or emits non-compliant ``NaN``. The same class todo_cockpit.py
# guards with _within_depth. Cap the surfaced value's depth, bound its int
# magnitude, and reject non-finite floats; drop any field that trips a guard
# (degrade the one field to null, never 500).
_MAX_FIELD_DEPTH = 32
# Comfortably under CPython's 4300-digit int->str limit (PEP 3.11): a real id /
# count never approaches it; anything bigger is producer garbage, dropped.
_MAX_INT_DIGITS = 600


def _encoder_safe(value, limit: int = _MAX_FIELD_DEPTH) -> bool:
    """True if `value` can be JSON-encoded without 500ing the response encoder:
    it nests no deeper than `limit`, contains no int whose magnitude exceeds the
    digit bound, and contains no non-finite float (NaN/Infinity/-Infinity).
    Iterative (no recursion of its own — it must not itself overflow on the
    pathological input it guards). Mirrors todo_cockpit._within_depth."""
    stack = [(value, 0)]
    while stack:
        node, depth = stack.pop()
        if depth > limit:
            return False
        if isinstance(node, bool):
            continue  # bool before int: a bool is encoder-safe and not "huge"
        if isinstance(node, int):
            # abs() of a multi-thousand-digit int would itself be cheap, but the
            # encoder's str() of it is what raises; bound the digit count.
            if abs(node) >= 10**_MAX_INT_DIGITS:
                return False
        elif isinstance(node, float):
            if not math.isfinite(node):
                return False
        elif isinstance(node, dict):
            for v in node.values():
                stack.append((v, depth + 1))
        elif isinstance(node, list):
            for v in node:
                stack.append((v, depth + 1))
    return True


def _safe(value):
    """The surfaced value if it is encoder-safe, else None — degrade the one
    pathological field rather than 500 the whole response (never coerced into a
    different value; a safe value flows through untouched)."""
    return value if _encoder_safe(value) else None


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
                    # BEFORE the encoder ever sees it, and that ValueError is
                    # NOT a JSONDecodeError. Skipping malformed rows keeps the
                    # endpoint useful while a primary-session bug is fixed.
                    continue
                # Bare scalars/arrays are valid JSON but not row records; drop
                # them like malformed lines (mirrors coordinator.py).
                if not isinstance(parsed, dict):
                    continue
                rows.append(parsed)
    except FileNotFoundError:
        # Delete-race: the producer atomically replaces/unlinks these JSONL
        # logs, so the file can vanish between our exists() check and open()
        # (or mid-iteration). A file that is gone is, from the reader's view,
        # absent — degrade to "no rows", NOT 500. Mirrors coordinator.active's
        # FileNotFoundError handling of the very same run-end race.
        return []
    except OSError as exc:
        # A genuinely unreadable file (permissions, I/O error) is a real
        # server-side fault, not the benign delete-race — surface it as 500.
        raise HTTPException(status_code=500, detail=f"unreadable: {exc}") from exc
    return rows


def _effective_status(memory_dir: Path, finding_id: str, base_status):
    """Base finding status overridden by the LAST status.jsonl audit row for
    this finding_id (the human_todo overlay). Absent file / no audit row =>
    the base row's status. Never coerced — the raw value flows through."""
    status = base_status
    for row in _read_jsonl(memory_dir / "surfaced_findings.status.jsonl"):
        fid = row.get("finding_id")
        if isinstance(fid, str) and fid == finding_id:
            status = row.get("status")  # last-row-wins
    return status


def _source_iteration(memory_dir: Path, source_iteration_id):
    """Project the compact FindingSourceIteration subset from the loop_memory
    row whose iteration_id matches. None when there is no usable id or no
    matching row (a finding can outlive/precede a readable iteration record)."""
    if not isinstance(source_iteration_id, str) or not source_iteration_id:
        return None
    for row in _read_jsonl(memory_dir / "loop_memory.jsonl"):
        if row.get("iteration_id") != source_iteration_id:
            continue
        seed = row.get("seed")
        topic = seed.get("topic") if isinstance(seed, dict) else None
        # Each surfaced member is independently encoder-guarded: a pathological
        # value (deep nest / huge int / non-finite float) in one field drops
        # only that field, leaving the rest of the iteration projectable.
        return {
            "iteration_id": source_iteration_id,
            "topic": _safe(topic),
            "nara_summary": _safe(row.get("nara_summary")),
            "gate_status": _safe(row.get("gate_status")),
            "journal_entry_path": _safe(row.get("journal_entry_path")),
            "started_at": _safe(row.get("started_at")),
            "ended_at": _safe(row.get("ended_at")),
        }
    return None


def register(app, *, memory_dir: Path) -> APIRouter:
    """Attach the finding-detail router. Reads surfaced_findings(+status) and
    loop_memory from ``memory_dir`` (the same memory dir coordinator.register
    uses). Read-only: writes nothing, ever."""
    router = APIRouter(tags=["finding_detail"])

    @router.get("/api/finding/{finding_id}")
    def finding_detail(finding_id: str):
        """The finding overview joined to its source iteration. Unknown
        finding_id => found:false at 200 (the tutor degrades in place).
        Never 500s on absent/garbled data files; writes NOTHING."""
        memory = Path(memory_dir)
        row = None
        for candidate in _read_jsonl(memory / "surfaced_findings.jsonl"):
            if candidate.get("finding_id") == finding_id:
                row = candidate  # last write wins, were a finding_id duplicated
        if row is None:
            return {"found": False, "finding_id": finding_id}

        evidence = row.get("evidence")
        if not isinstance(evidence, dict):
            evidence = None  # the contract: a non-dict evidence => null
        source_iteration_id = row.get("source_iteration_id")
        # Every surfaced value is encoder-guarded at the point it enters the
        # response (_safe drops a pathological field to null rather than 500 the
        # encoder). finding_id itself is the matched path arg (a clean string,
        # not row data) so it is surfaced verbatim; source_iteration_id is used
        # RAW as the join key above and only the surfaced copy is guarded.
        return {
            "found": True,
            "finding_id": finding_id,
            "title": _safe(row.get("title")),
            "claim": _safe(row.get("claim")),
            "why_it_matters": _safe(row.get("why_it_matters")),
            "what_would_change_it": _safe(row.get("what_would_change_it")),
            "novelty_class": _safe(row.get("novelty_class")),
            "critic_verdict": _safe(row.get("critic_verdict")),
            "status": _safe(_effective_status(memory, finding_id, row.get("status"))),
            "promoted_at": _safe(row.get("promoted_at")),
            "source_iteration_id": _safe(source_iteration_id),
            "evidence": _safe(evidence),
            "source_iteration": _source_iteration(memory, source_iteration_id),
        }

    app.include_router(router)
    return router
