"""In-UI attestation endpoints — the B4 write-back seam (D-046, blessed).

The UI backend NEVER opens ``run_state/`` or ``memory/`` files for writing
(docs/human_writeback_contract.md, principle 1). Each POST here execs the
blessed CLI as an **argv array** — no shell strings, no string interpolation
into a shell — with ``cwd`` = the primary repo root and interpreter
``.venv-chroma/bin/python`` (precedent: ``POST /api/loop_v0/start`` in
``ui/backend/loop_v0.py``). The CLI's own validation is the authoritative
gate; this module pre-validates for UX and returns 422 BEFORE any spawn.

Endpoints, wired by ``register`` into the existing FastAPI app:

- ``GET  /api/attest/available``      — capability handshake (a frontend
  seeing ``available: false`` — or a 404 on this endpoint from an older
  backend — degrades every form to the copy-paste CLI fallback).
- ``POST /api/attest/gate_verdict``   — ``{iteration_id, verdict, note}``
- ``POST /api/attest/finding_review`` — ``{finding_id, status, note}``
- ``POST /api/attest/bubble_ack``     — ``{bubble_run_id, note}``
- ``POST /api/attest/defer``          — ``{kind, ref_id, note}``

Direct resolution of ``stale_active_run`` / ``state_gate`` is **not
blessed** (contract table row 5: process autopsy / state-file edits stay
primary-session human actions) — for those two kinds the ONLY endpoint
here is ``defer``; no others exist by design.

Failure semantics (contract principle 3): nonzero exit -> 502 carrying the
CLI's **stderr verbatim** plus the exit code. Success (principle 4): the
CLI's stdout JSON is parsed and returned — note the shapes DIFFER by CLI
(see ``_exec_blessed`` and the per-endpoint comments). Identity (principle
6): every write initiated here stamps ``human:ui``.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import JSONResponse

# Primary checkout (the same constant app.py pins). When the UI runs from a
# worktree, the blessed CLIs + ledgers live here, not in the worktree.
_PRIMARY_REPO = Path("/home/decross1/projects/a_bgt_rsi")

# Every write initiated from the UI stamps this identity (contract §6).
IDENTITY = "human:ui"

# Frozen enums — mirrors of the writers' own validation, never wider:
#   GATE_VERDICTS    — schema/loop_feedback.schema.json verdict enum
#   FINDING_STATUSES — orchestrator/finding_session.py QUICK_STATUSES
#   DEFER_KINDS      — orchestrator/todo_cli.py DEFER_KINDS
GATE_VERDICTS = ("valid", "invalid", "needs_revision")
FINDING_STATUSES = ("validated", "rejected", "in_review")
DEFER_KINDS = (
    "gate_verdict",
    "finding_review",
    "bubble_ack",
    "stale_active_run",
    "state_gate",
)

# Conservative id charset. There is no shell anywhere in this module, so the
# injection vector is argv-FLAG confusion: a leading "-" would be parsed as a
# flag by the CLI's argparse. Hence the no-leading-dash first class.
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_MAX_ID_LEN = 200  # real ids are short (iter-2026-06-09-001, sf-001, cyc-014)

# Existence checks for the capability handshake: the three blessed writer
# modules + the interpreter the contract names, under the primary repo root.
_PYTHON_REL = Path(".venv-chroma") / "bin" / "python"
_MODULE_FILES = {
    "orchestrator.gate_cli": Path("orchestrator") / "gate_cli.py",
    "orchestrator.todo_cli": Path("orchestrator") / "todo_cli.py",
    "orchestrator.finding_session": Path("orchestrator") / "finding_session.py",
}

# The CLIs are one-shot validate-then-append writers; generous ceiling so a
# wedged interpreter cannot pin a backend worker forever.
_EXEC_TIMEOUT_S = 120


def _require_id(value, field: str) -> str:
    """422 unless `value` is a conservative-charset id (no leading dash)."""
    if not isinstance(value, str) or not value:
        raise HTTPException(
            status_code=422, detail=f"{field} is required (non-empty string)")
    if len(value) > _MAX_ID_LEN or not _ID_RE.match(value):
        raise HTTPException(
            status_code=422,
            detail=(f"{field} must match ^[A-Za-z0-9][A-Za-z0-9._:-]*$ "
                    f"(max {_MAX_ID_LEN} chars; no leading dash)"))
    return value


def _require_note(value) -> str:
    """422 unless `value` is a non-empty (non-whitespace) string.

    The contract: the CLI permits an empty gate note but the UI SHOULD
    require one — the note is the audit value. We require it on all four.
    """
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(
            status_code=422, detail="note is required (non-empty) — the note "
                                    "is the audit value")
    return value


def _require_enum(value, allowed: tuple, field: str) -> str:
    """422 unless `value` is one of the frozen enum members — never coerced
    (inviolate rule 4); the CLI re-validates authoritatively."""
    if value not in allowed:
        raise HTTPException(
            status_code=422,
            detail=f"{field} must be one of {list(allowed)} (got {value!r})")
    return value


def _exec_blessed(runner, repo_root: Path, module: str, args: list[str]):
    """Exec one blessed CLI invocation; return the endpoint response.

    Discipline (contract principle 1): argv ARRAY only — `runner` is called
    with a list, never a joined string, never ``shell=True``; ``cwd`` is the
    primary repo root; the interpreter is ``.venv-chroma/bin/python``.

    - rc != 0  -> 502 ``{rc, stderr}`` with stderr VERBATIM (principle 3).
    - rc == 0  -> the CLI's stdout parsed as JSON and returned (principle 4).
      **Stdout shapes differ by CLI**: ``gate_cli`` and ``todo_cli`` print
      the appended ledger row itself (``gated_by`` / ``ack_by`` /
      ``attested_by`` carry the human:ui stamp); ``finding_session
      --set-status`` prints an ENVELOPE ``{finding_id, session_id, outcome,
      loop_feedback_row, status_audit_row}`` whose stamp is
      ``status_audit_row.changed_by`` (``loop_feedback_row`` is null for
      ``in_review``). We return whichever shape verbatim — do not assume one.
    """
    python_bin = repo_root / _PYTHON_REL
    argv = [str(python_bin), "-m", module, *args]
    try:
        proc = runner(argv, cwd=str(repo_root), capture_output=True,
                      text=True, timeout=_EXEC_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as exc:
        # Spawn-level failure (missing interpreter, timeout, …): same 502
        # surface so the frontend renders one failure shape.
        return JSONResponse(status_code=502, content={
            "rc": None, "stderr": f"exec failed before the CLI completed: {exc}"})
    rc = getattr(proc, "returncode", None)
    stderr = getattr(proc, "stderr", "") or ""
    stdout = getattr(proc, "stdout", "") or ""
    if rc != 0:
        # stderr VERBATIM — the frontend renders it un-summarized.
        return JSONResponse(status_code=502, content={"rc": rc, "stderr": stderr})
    try:
        return json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        # A zero-exit CLI that printed non-JSON broke the D-046 contract;
        # surface everything rather than fake a success shape.
        return JSONResponse(status_code=502, content={
            "rc": rc, "stderr": stderr, "stdout": stdout,
            "error": "CLI exited 0 but stdout was not parseable JSON"})


def register(
    app,
    *,
    repo_root: Path | None = None,
    runner=None,
) -> APIRouter:
    """Attach the attestation router (sibling-module pattern, cf.
    ``todo_cockpit.register`` — the same ``repo_root: Path | None`` defaulting to
    the primary checkout). ``runner`` defaults to ``subprocess.run`` and is
    injectable so tests stub the exec — tests NEVER exec against the live
    ledgers."""
    root = Path(repo_root) if repo_root is not None else _PRIMARY_REPO
    run = runner if runner is not None else subprocess.run
    router = APIRouter(prefix="/api/attest", tags=["attest"])

    @router.get("/available")
    def available():
        """Capability handshake: existence-check the three blessed writer
        modules + the .venv-chroma interpreter under the primary repo root.
        Never execs anything."""
        python_ok = (root / _PYTHON_REL).exists()
        module_ok = {name: (root / rel).exists()
                     for name, rel in _MODULE_FILES.items()}
        actions = {
            "gate_verdict": python_ok and module_ok["orchestrator.gate_cli"],
            "finding_review": python_ok and module_ok["orchestrator.finding_session"],
            "bubble_ack": python_ok and module_ok["orchestrator.todo_cli"],
            "defer": python_ok and module_ok["orchestrator.todo_cli"],
        }
        return {"available": all(actions.values()), "actions": actions}

    @router.post("/gate_verdict")
    def gate_verdict(payload: dict = Body(...)):
        """Record a Step-8 human-gate verdict via orchestrator.gate_cli.
        Success stdout shape: the appended loop_feedback ledger row itself
        (``gated_by`` = human:ui) — NOT an envelope; cf. finding_review."""
        iteration_id = _require_id(payload.get("iteration_id"), "iteration_id")
        verdict = _require_enum(payload.get("verdict"), GATE_VERDICTS, "verdict")
        note = _require_note(payload.get("note"))
        return _exec_blessed(run, root, "orchestrator.gate_cli", [
            "--iteration-id", iteration_id,
            "--verdict", verdict,
            "--note", note,
            "--gated-by", IDENTITY,
        ])

    @router.post("/finding_review")
    def finding_review(payload: dict = Body(...)):
        """One-shot finding disposition via finding_session --set-status.
        Success stdout shape DIFFERS from the other three endpoints: an
        ENVELOPE ``{finding_id, session_id, outcome, loop_feedback_row,
        status_audit_row}`` — returned as-is. The human:ui stamp lives at
        ``status_audit_row.changed_by``; ``loop_feedback_row`` is null for
        ``in_review`` (validated/rejected also append a loop_feedback row
        against the finding's source iteration)."""
        finding_id = _require_id(payload.get("finding_id"), "finding_id")
        status = _require_enum(payload.get("status"), FINDING_STATUSES, "status")
        note = _require_note(payload.get("note"))
        return _exec_blessed(run, root, "orchestrator.finding_session", [
            "--set-status", finding_id, status,
            "--note", note,
            "--by", IDENTITY,
        ])

    @router.post("/bubble_ack")
    def bubble_ack(payload: dict = Body(...)):
        """Acknowledge a coordinator bubble via todo_cli ack. Success stdout
        shape: the appended coordinator_acks row itself (``ack_by`` =
        human:ui)."""
        bubble_run_id = _require_id(payload.get("bubble_run_id"), "bubble_run_id")
        note = _require_note(payload.get("note"))
        return _exec_blessed(run, root, "orchestrator.todo_cli", [
            "ack",
            "--bubble-run-id", bubble_run_id,
            "--note", note,
            "--by", IDENTITY,
        ])

    @router.post("/defer")
    def defer(payload: dict = Body(...)):
        """Defer a TODO item to the next dev session via todo_cli defer.
        Available for EVERY item kind — including ``stale_active_run`` and
        ``state_gate``, whose direct resolution is NOT blessed (contract
        table row 5); for those two this is the only attestation offered.
        Success stdout shape: the appended dev_session_queue row itself
        (``attested_by`` = human:ui, ``status`` = "open")."""
        kind = _require_enum(payload.get("kind"), DEFER_KINDS, "kind")
        ref_id = _require_id(payload.get("ref_id"), "ref_id")
        note = _require_note(payload.get("note"))
        return _exec_blessed(run, root, "orchestrator.todo_cli", [
            "defer",
            "--kind", kind,
            "--ref-id", ref_id,
            "--note", note,
            "--by", IDENTITY,
        ])

    app.include_router(router)
    return router
