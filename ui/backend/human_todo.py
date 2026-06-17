"""Human TODO composition endpoint — the B3 read-only slice of
ui/notes/observability_reconciliation_plan.md.

The human's queue is invisible today: 11+ iterations sit at
``gate_status="pending"`` with no ``loop_feedback`` verdict and no surface
says so. This module composes everything awaiting a human into ONE list,
each item carrying the exact CLI command that resolves it (the sanctioned
write-back channels already exist; the UI backend stays read-only).

One endpoint, wired by ``register`` into the existing FastAPI app:

- ``GET /api/human_todo`` — ``{"items": [...], "counts": {...}}``,
  items oldest-first by ``since``, each
  ``{kind, id, title, since, detail, resolve_command}``. Kinds:

  - ``gate_verdict``     — ``loop_memory.jsonl`` rows with
    ``gate_status="pending"`` and NO row in ``loop_feedback.jsonl``
    (orchestrator/gate_cli.py is the resolve channel).
  - ``finding_review``   — ``surfaced_findings.jsonl`` rows whose EFFECTIVE
    status (base row overridden by the LAST
    ``surfaced_findings.status.jsonl`` row per finding_id) is ``surfaced``
    or ``in_review`` (orchestrator/finding_session.py REPL resolves).
  - ``bubble_ack``       — ``coordinator_bubbles.jsonl`` rows with no ack in
    ``memory/coordinator_acks.jsonl`` (absent file = nothing acked; the ack
    channel itself is pending main-session blessing — plan A5).
  - ``stale_active_run`` — ``run_state/active_run.json`` exists and its
    freshest of ``step_started_at``/``started_at`` is >30 min old (the
    known lock-leak failure). Malformed/missing timestamps = NOT stale.
  - ``state_gate``       — ``run_state/week1.state.json``
    ``human_gates_pending`` entries (inviolate rule 3: blocking).

Mirrors the ``coordinator.py`` register-fn idiom (same ``_read_jsonl``
tolerance of absent files and malformed lines). Read-only: the UI never
writes ``run_state/`` or ``memory/``. The endpoint never 500s on absent
or garbled data files.

Dev-session deferrals (D-046, additive): ``memory/dev_session_queue.jsonl``
is read alongside the sources above — rows fold by ``ref_id``, LAST status
wins (``defer`` appends ``status:"open"``, ``close`` appends
``status:"closed"``; mirrors ``orchestrator/todo_cli.py list_deferred``).
An item whose ``ref_id`` has an open deferral gets ``deferred: true`` plus
a ``deferral: {note, by, at}`` block — it is STILL listed and STILL counted
(the contract: a deferral assigns the work; it does not resolve the item).
No existing keys change.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException

KINDS = (
    "gate_verdict",
    "finding_review",
    "bubble_ack",
    "stale_active_run",
    "state_gate",
)

# active_run.json older than this (freshest timestamp) is a lock-leak suspect.
STALE_ACTIVE_RUN_AFTER = timedelta(minutes=30)

# Verdict enum mirrors schema/loop_feedback.schema.json (frozen shape).
_GATE_RESOLVE_TEMPLATE = (
    ".venv-chroma/bin/python -m orchestrator.gate_cli "
    "--iteration-id {iteration_id} --verdict <valid|invalid|needs_revision> "
    "--note '<why>'"
)
# finding_session is a REPL: launch it, then `start <finding_id>` and close
# with /validate, /reject, /spawn or /refine (orchestrator/finding_session.py).
_FINDING_RESOLVE_TEMPLATE = (
    ".venv-chroma/bin/python -m orchestrator.finding_session"
    "  # then: start {finding_id} ; /validate|/reject|/spawn|/refine <note>"
)
_BUBBLE_RESOLVE = (
    "(ack channel pending main-session blessing — see "
    "ui/notes/observability_reconciliation_plan.md A5)"
)


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
                except json.JSONDecodeError:
                    # Producer's contract; skipping malformed rows keeps the
                    # endpoint useful while a primary-session bug is fixed.
                    continue
                # Bare scalars/arrays are valid JSON but not row records;
                # drop them like malformed lines (mirrors coordinator.py).
                if not isinstance(parsed, dict):
                    continue
                rows.append(parsed)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"unreadable: {exc}") from exc
    return rows


def _as_text(value, default: str = "") -> str:
    """Defensive coercion — producer-owned JSONL fields may be any shape."""
    if isinstance(value, str):
        return value
    if value is None:
        return default
    try:
        return str(value)
    except Exception:  # noqa: BLE001 — never let a weird repr 500 the endpoint
        return default


def _parse_ts(value) -> datetime | None:
    """Parse an ISO timestamp; None on anything unparseable. Naive values
    are taken as UTC (the producers stamp Z-suffixed UTC)."""
    if not isinstance(value, str) or not value:
        return None
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def _item(kind: str, id_: str, title: str, since: str, detail: str,
          resolve_command: str) -> dict:
    return {
        "kind": kind,
        "id": id_,
        "title": title,
        "since": since,
        "detail": detail,
        "resolve_command": resolve_command,
    }


def _gate_verdict_items(memory_dir: Path) -> list[dict]:
    feedback_ids = {
        r.get("iteration_id")
        for r in _read_jsonl(memory_dir / "loop_feedback.jsonl")
    }
    items = []
    for row in _read_jsonl(memory_dir / "loop_memory.jsonl"):
        if row.get("gate_status") != "pending":
            continue
        iteration_id = _as_text(row.get("iteration_id"))
        if not iteration_id or iteration_id in feedback_ids:
            continue
        seed = row.get("seed") if isinstance(row.get("seed"), dict) else {}
        items.append(_item(
            "gate_verdict",
            iteration_id,
            _as_text(seed.get("topic")) or iteration_id,
            _as_text(row.get("ended_at")),
            f"iteration {iteration_id} finished and awaits a human gate "
            "verdict (Step-8; no loop_feedback row yet)",
            _GATE_RESOLVE_TEMPLATE.format(iteration_id=iteration_id),
        ))
    return items


def _finding_review_items(memory_dir: Path) -> list[dict]:
    findings = _read_jsonl(memory_dir / "surfaced_findings.jsonl")
    # Effective status = LAST audit row per finding_id overriding the base
    # row (surfaced_findings.jsonl is never edited in place).
    overrides: dict[str, str] = {}
    for status_row in _read_jsonl(memory_dir / "surfaced_findings.status.jsonl"):
        fid = status_row.get("finding_id")
        if isinstance(fid, str) and fid:
            overrides[fid] = _as_text(status_row.get("status"))
    items = []
    for finding in findings:
        fid = _as_text(finding.get("finding_id"))
        if not fid:
            continue
        status = overrides.get(fid, _as_text(finding.get("status")))
        if status not in ("surfaced", "in_review"):
            continue
        items.append(_item(
            "finding_review",
            fid,
            _as_text(finding.get("title")) or fid,
            _as_text(finding.get("promoted_at")),
            f"promoted finding awaits human interrogation (status: {status})",
            _FINDING_RESOLVE_TEMPLATE.format(finding_id=fid),
        ))
    return items


def _bubble_ack_items(memory_dir: Path) -> list[dict]:
    acked = {
        a.get("bubble_run_id")
        for a in _read_jsonl(memory_dir / "coordinator_acks.jsonl")
    }
    items = []
    for bubble in _read_jsonl(memory_dir / "coordinator_bubbles.jsonl"):
        run_id = _as_text(bubble.get("run_id"))
        if run_id and run_id in acked:
            continue
        items.append(_item(
            "bubble_ack",
            run_id or _as_text(bubble.get("timestamp")),
            _as_text(bubble.get("note")) or "(bubble with no note)",
            _as_text(bubble.get("timestamp")),
            "the loop raised this to the human; no acknowledgement recorded",
            _BUBBLE_RESOLVE,
        ))
    return items


def _stale_active_run_items(run_state_dir: Path) -> list[dict]:
    path = run_state_dir / "active_run.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # Unreadable/garbled mirror is a producer problem, not a TODO we can
        # date — and "malformed = NOT stale" by contract.
        return []
    if not isinstance(data, dict):
        return []
    stamps = [
        ts for ts in (
            _parse_ts(data.get("step_started_at")),
            _parse_ts(data.get("started_at")),
        ) if ts is not None
    ]
    if not stamps:
        return []  # missing/malformed timestamps = NOT stale
    freshest = max(stamps)
    if datetime.now(timezone.utc) - freshest <= STALE_ACTIVE_RUN_AFTER:
        return []
    return [_item(
        "stale_active_run",
        _as_text(data.get("run_id")) or "active_run",
        "investigate/clear stale active_run — possible lock-leak",
        freshest.isoformat().replace("+00:00", "Z"),
        f"run_state/active_run.json claims a live run (kind="
        f"{_as_text(data.get('kind')) or '?'}) but its freshest timestamp "
        f"is over {int(STALE_ACTIVE_RUN_AFTER.total_seconds() // 60)} min old",
        "inspect run_state/active_run.json; if no apparatus process is "
        "live, remove the file (lock-leak cleanup)",
    )]


def _state_gate_items(run_state_dir: Path) -> list[dict]:
    path = run_state_dir / "week1.state.json"
    if not path.exists():
        return []
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(state, dict):
        return []
    gates = state.get("human_gates_pending")
    if not isinstance(gates, list):
        return []
    items = []
    for index, gate in enumerate(gates):
        if isinstance(gate, dict):
            gate_id = (_as_text(gate.get("id")) or _as_text(gate.get("gate_id"))
                       or _as_text(gate.get("task_id")) or f"state-gate-{index}")
            title = (_as_text(gate.get("title")) or _as_text(gate.get("description"))
                     or _as_text(gate.get("note")) or gate_id)
            since = (_as_text(gate.get("since")) or _as_text(gate.get("created_at"))
                     or _as_text(gate.get("timestamp")))
        else:
            gate_id = f"state-gate-{index}"
            title = _as_text(gate) or gate_id
            since = ""
        items.append(_item(
            "state_gate",
            gate_id,
            title,
            since,
            "human_gates_pending entry in run_state/week1.state.json — "
            "blocking until the human explicitly clears it (inviolate rule 3)",
            "the human clears the gate explicitly in the primary session; "
            "the entry is then removed from run_state/week1.state.json",
        ))
    return items


def _open_deferrals(memory_dir: Path) -> dict[str, dict]:
    """Fold ``memory/dev_session_queue.jsonl`` by ``ref_id`` — LAST status
    wins (``defer`` appends ``status:"open"``, ``close`` appends
    ``status:"closed"``; the ledger is append-only, never edited in place).
    Returns ref_id -> the winning OPEN row. Same fold as
    ``orchestrator/todo_cli.py list_deferred``: the ledger's identity key is
    ``ref_id`` alone. Absent file == no deferrals (D-046; the ledger is new
    and gitignored)."""
    folded: dict[str, dict] = {}
    for row in _read_jsonl(memory_dir / "dev_session_queue.jsonl"):
        ref = row.get("ref_id")
        if not isinstance(ref, str) or not ref:
            continue
        status = row.get("status")
        if status == "open":
            folded[ref] = row  # last open row wins (freshest note)
        elif status == "closed":
            folded.pop(ref, None)
        # Unknown statuses: skipped, like malformed lines — a future writer's
        # contract is not ours to interpret.
    return folded


def _tag_deferred(items: list[dict], memory_dir: Path) -> None:
    """ADDITIVE in place: an item whose id has an open deferral gains
    ``deferred: true`` + ``deferral: {note, by, at}``. The item stays listed
    and stays counted — a deferral assigns the work; it does not resolve the
    item. Untagged items are untouched (no existing keys change)."""
    deferrals = _open_deferrals(memory_dir)
    if not deferrals:
        return
    for item in items:
        row = deferrals.get(item["id"])
        if row is None:
            continue
        item["deferred"] = True
        item["deferral"] = {
            "note": _as_text(row.get("note")),
            "by": _as_text(row.get("attested_by")),
            "at": _as_text(row.get("deferred_at")),
        }


def register(
    app,
    *,
    run_state_dir: Path,
    memory_dir: Path,
) -> APIRouter:
    """Attach the human-TODO router. Reads loop_memory / loop_feedback /
    surfaced_findings(+status) / bubbles / acks from ``memory_dir`` and
    active_run.json / week1.state.json from ``run_state_dir`` (the same
    split ``coordinator.register`` uses)."""
    router = APIRouter(prefix="/api/human_todo", tags=["human_todo"])

    @router.get("")
    def human_todo():
        """Everything awaiting the human, oldest-first by ``since``, each
        with the exact CLI command that resolves it. Never 500s on absent
        or garbled data files."""
        run_state = Path(run_state_dir)
        memory = Path(memory_dir)
        items: list[dict] = []
        items.extend(_gate_verdict_items(memory))
        items.extend(_finding_review_items(memory))
        items.extend(_bubble_ack_items(memory))
        items.extend(_stale_active_run_items(run_state))
        items.extend(_state_gate_items(run_state))
        # D-046 additive fold: tag (never remove) items with open deferrals.
        _tag_deferred(items, memory)
        # Oldest-first: the longest-waiting item tops the queue. Items with
        # no parseable `since` sort first (unknown age is surfaced, not hidden).
        items.sort(key=lambda item: item.get("since") or "")
        counts = {kind: 0 for kind in KINDS}
        for item in items:
            counts[item["kind"]] += 1
        return {"items": items, "counts": counts}

    app.include_router(router)
    return router
