"""`/todo` cockpit backend — the resolution seams, wired to blessed CLIs (D-046).

The four already-blessed outcomes (gate_verdict, finding_review, bubble_ack,
defer) live in ``ui/backend/attest.py`` against the D-046 write-back contract —
this module does NOT duplicate them. It carries the cockpit's remaining seams
(``docs/cockpit_seam_wiring.md`` — the authoritative per-outcome writer spec):

- ``authorize_fix``    (outcome 4 — gated autonomy) -> ``orchestrator.authorize_fix``
- ``directive_signoff`` (outcome 1 variant — sign-off WITH a ``--directive``)
                        -> ``orchestrator.finding_session --set-status``
- ``calibration``      (ARCH §6.5.4 pre-verdict capture) -> ``orchestrator.calibration_cli``
- ``spawn_topic``      (outcome 5) — a SESSION-EXIT, not a one-shot writer
- ``abstain``          (outcome 6) — a SESSION-EXIT, not a one-shot writer

The three one-shot seams exec their blessed CLI via ``attest._exec_blessed`` (the
same argv-array, runner-injected, ``human:ui``-stamped path the attest endpoints
use). D-046: the CLI is the writer of record; this module NEVER writes a ledger
directly, and out-of-shape input is rejected (422) BEFORE any spawn — never
coerced (inviolate rule 4). The CLI's own validation is the authoritative gate.

``spawn_topic`` (5) / ``abstain`` (6) have NO one-shot CLI verb — the only writer
is ``finding_session``'s ``end_session`` (outcomes ``spawn_topic`` / ``abandoned``),
reached through the interrogation / two-voice chat session ("they need the
conversation", D-046; ``docs/cockpit_seam_wiring.md`` disposition). So both
endpoints render as honest SESSION-EXIT indicators that WRITE NOTHING — they
validate the id (422 on bad), then return ``{status:"session_exit", outcome,
via}``. Their ``/available`` flags stay False: they are not one-shot writers.

The lone real read is the read-only ``run_state/active_run.json`` concurrency
guard (``GET /api/todo/concurrency``); it opens no file under ``memory/`` for
writing.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException

from .attest import _exec_blessed

# Primary checkout (the same constant attest.py / app.py pin). The blessed CLIs +
# the read-only active_run.json live here, not in the worktree.
_PRIMARY_REPO = Path("/home/decross1/projects/a_bgt_rsi")

# Every write the cockpit INITIATES stamps this identity (contract §6).
IDENTITY = "human:ui"

# Frozen enums — mirrors of the writers' own validation, never wider.
#   SPAWN_TOPIC_KINDS — the kind of follow-up a spawn-topic session exit names.
# (authorize_fix / directive_signoff / abstain / calibration carry no enum field
#  of their own; their validation is required-non-empty id/note/text.)
SPAWN_TOPIC_KINDS = ("finding", "step")

# Conservative id charset — identical to attest._ID_RE: no shell anywhere, so the
# injection vector is argv-FLAG confusion (a leading "-" parses as a flag).
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_MAX_ID_LEN = 200

# The blessed CLI modules each one-shot seam execs (the source file is
# existence-checked for the /available capability handshake). Corrected per
# docs/cockpit_seam_wiring.md "ui/backend U4 fixes": authorize_fix ->
# authorize_fix (not todo_cli); calibration -> calibration_cli (not gate_cli);
# directive_signoff -> finding_session --set-status (not gate_cli).
_PYTHON_REL = Path(".venv-chroma") / "bin" / "python"
_SEAM_MODULES = {
    # name -> (blessed CLI module, source file existence-checked)
    "authorize_fix": ("orchestrator.authorize_fix", Path("orchestrator") / "authorize_fix.py"),
    "directive_signoff": ("orchestrator.finding_session", Path("orchestrator") / "finding_session.py"),
    "calibration": ("orchestrator.calibration_cli", Path("orchestrator") / "calibration_cli.py"),
}

# spawn_topic (5) / abstain (6) are SESSION-EXITS off the finding_session
# interrogation session, NOT one-shot writers — there is no one-shot CLI verb for
# either (the only writer is end_session). So they are NOT in _SEAM_MODULES.
# These honest session-exit indicators WRITE NOTHING (docs/cockpit_seam_wiring.md
# disposition; docs/human_writeback_contract.md: "renders them as session exits").
_SESSION_EXIT_OUTCOMES = {
    "spawn_topic": "spawn_topic",   # end_session outcome="spawn_topic"
    "abstain": "abandoned",         # end_session outcome="abandoned"
}
_SESSION_EXIT_VIA = "finding_session interrogation session (end_session)"

# escalation `allowed_actions` -> cockpit endpoint(s). The escalation enum
# (schema/escalation.schema.json) names sign_off / reject / refine_defer /
# refine_authorize_fix / spawn_topic / abstain, while the cockpit/attest POST
# routes are named differently (authorize_fix, not refine_authorize_fix;
# directive_signoff, a variant of sign_off). This documents the map (per
# docs/cockpit_seam_wiring.md) so the UI lights up the right form per action.
ALLOWED_ACTION_ENDPOINTS = {
    # sign_off covers BOTH bare sign-off (attest /finding_review validated) and
    # directive sign-off (this module's /directive_signoff with a --directive).
    "sign_off": ["/api/todo/directive_signoff", "/api/attest/finding_review"],
    "reject": ["/api/attest/finding_review"],            # rejected
    "refine_defer": ["/api/attest/defer"],
    "refine_authorize_fix": ["/api/todo/authorize_fix"],
    "spawn_topic": ["session-exit"],                     # chat seam -> end_session
    "abstain": ["session-exit"],                         # chat seam -> end_session
}


def _reject_non_finite(token: str):
    """json.loads parse_constant hook: a non-finite literal (NaN/Infinity/
    -Infinity) in active_run.json means the file is malformed — raise so the
    concurrency read fails safe to active:false instead of letting a non-finite
    float reach the JSONResponse encoder (which 500s the cockpit)."""
    raise ValueError(f"non-finite JSON constant {token!r} in active_run.json")


# Surfaced active_run.json fields (kind/label/narration) are scalars in every
# valid run (depth 0). A producer that wrote a deeply-NESTED value there is
# malformed: json.loads accepts it, but FastAPI's JSONResponse encoder walks it
# RECURSIVELY — and the request call stack is already deep, so a few thousand
# levels overflow into a RecursionError that lands AFTER the read's try/except
# (during response encoding) and 500s the cockpit. Cap the surfaced value's
# depth and drop any field that exceeds it (degrade the one field, never 500),
# matching the huge-bigint case that already fails safe.
_MAX_FIELD_DEPTH = 32


def _within_depth(value, limit: int = _MAX_FIELD_DEPTH) -> bool:
    """True if `value` nests no deeper than `limit`. Iterative (no recursion of
    its own — it must not itself overflow on the pathological input it guards)."""
    stack = [(value, 0)]
    while stack:
        node, depth = stack.pop()
        if depth > limit:
            return False
        if isinstance(node, dict):
            for v in node.values():
                stack.append((v, depth + 1))
        elif isinstance(node, list):
            for v in node:
                stack.append((v, depth + 1))
    return True


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


def _require_text(value, field: str) -> str:
    """422 unless `value` is a non-empty (non-whitespace) string. Free text
    (--task / --note / --directive / prediction) is not charset-restricted —
    it is never a positional argv flag (always preceded by its --flag)."""
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(
            status_code=422, detail=f"{field} is required (non-empty string)")
    return value


def _require_enum(value, allowed: tuple, field: str) -> str:
    """422 unless `value` is one of the frozen enum members — never coerced
    (inviolate rule 4); the CLI re-validates authoritatively."""
    if value not in allowed:
        raise HTTPException(
            status_code=422,
            detail=f"{field} must be one of {list(allowed)} (got {value!r})")
    return value


def register(
    app,
    *,
    repo_root: Path | None = None,
    runner=None,
) -> APIRouter:
    """Attach the cockpit router (sibling-module pattern, cf. ``attest.register`` —
    same ``repo_root: Path | None`` defaulting to the primary checkout, same
    ``runner`` injection). ``runner`` defaults to ``subprocess.run`` and is
    injectable so tests stub the exec — tests NEVER exec a real CLI or a real
    model against the live ledgers."""
    root = Path(repo_root) if repo_root is not None else _PRIMARY_REPO
    run = runner if runner is not None else subprocess.run
    router = APIRouter(prefix="/api/todo", tags=["todo-cockpit"])

    @router.get("/available")
    def available():
        """Capability handshake (cf. attest's /available): reports which cockpit
        writers exist. Each one-shot seam lights up when its CORRECTED blessed
        module is present on disk (authorize_fix.py / finding_session.py /
        calibration_cli.py). ``two_voice_chat`` (the chat pane the frontend gates
        on) lights up when finding_session.py exists — the chat seam landed.
        ``spawn_topic`` / ``abstain`` stay False: they are session-exits, not
        one-shot writers. Never execs anything."""
        python_ok = (root / _PYTHON_REL).exists()
        actions = {
            name: python_ok and (root / rel).exists()
            for name, (_, rel) in _SEAM_MODULES.items()
        }
        # The two-voice chat pane is gated on this flag; it has no would-run CLI
        # of its own (it is the finding_session `chat` seam, not in _SEAM_MODULES).
        # The chat seam landed (P1/P2), so it is True when finding_session exists.
        finding_session_ok = (
            root / Path("orchestrator") / "finding_session.py").exists()
        actions["two_voice_chat"] = python_ok and finding_session_ok
        # spawn_topic / abstain are session-exits (no one-shot writer) — report
        # them explicitly as False so the frontend never offers a one-shot button.
        for name in _SESSION_EXIT_OUTCOMES:
            actions[name] = False
        return {
            # Available iff every one-shot seam (and the chat gate) is present.
            "available": all(actions[name] for name in _SEAM_MODULES)
            and actions["two_voice_chat"],
            "interpreter_present": python_ok,
            "actions": actions,
            # The escalation allowed_actions -> cockpit endpoint map (so the UI
            # routes an escalation's allowed action to the right form).
            "allowed_action_endpoints": ALLOWED_ACTION_ENDPOINTS,
        }

    @router.post("/authorize_fix")
    def authorize_fix(payload: dict = Body(...)):
        """Outcome 4 — authorize an autonomous fix (gated). Execs the blessed
        ``orchestrator.authorize_fix authorize-fix --ref-id <id> --task
        <statement> --note <why> --by human:ui`` (D-046; writer of record). The
        CLI enqueues a spawn-contract for the next dev session — it does NOT
        dispatch (the merge gate / D-014 firewall stay intact). 422 on bad input
        BEFORE any spawn; nonzero CLI exit -> 502 with stderr verbatim."""
        ref_id = _require_id(payload.get("ref_id"), "ref_id")
        task = _require_text(payload.get("task"), "task")
        note = _require_text(payload.get("note"), "note")
        module, _ = _SEAM_MODULES["authorize_fix"]
        return _exec_blessed(run, root, module, [
            "authorize-fix",
            "--ref-id", ref_id,
            "--task", task,
            "--note", note,
            "--by", IDENTITY,
        ])

    @router.post("/directive_signoff")
    def directive_signoff(payload: dict = Body(...)):
        """Outcome 1 variant — sign off WITH a directive ("proceed to <next
        step>"). Execs ``orchestrator.finding_session --set-status <FINDING_ID>
        validated --note <why> --directive <next-step> --by human:ui`` (a clean
        SUPERSET of the bare sign-off; the directive lands on the
        ``status_audit_row`` only — the loop_feedback schema stays frozen). Keyed
        on ``finding_id`` (NOT iteration_id). Nonzero CLI exit -> 502."""
        finding_id = _require_id(payload.get("finding_id"), "finding_id")
        note = _require_text(payload.get("note"), "note")
        directive = _require_text(payload.get("directive"), "directive")
        module, _ = _SEAM_MODULES["directive_signoff"]
        return _exec_blessed(run, root, module, [
            "--set-status", finding_id, "validated",
            "--note", note,
            "--directive", directive,
            "--by", IDENTITY,
        ])

    @router.post("/spawn_topic")
    def spawn_topic(payload: dict = Body(...)):
        """Outcome 5 — spawn a follow-up topic. This is a SESSION-EXIT, NOT a
        one-shot writer: the only writer is ``finding_session``'s ``end_session``
        (outcome ``spawn_topic`` -> ``memory/finding_followups.jsonl``), reached
        through the interrogation / chat session ("it needs the conversation",
        D-046). So this endpoint WRITES NOTHING and execs NOTHING — it validates
        the id + topic (422 on bad, never coerced) and returns an honest
        session-exit indicator the UI renders as "exit the session into
        spawn_topic", not a button."""
        finding_id = _require_id(payload.get("finding_id"), "finding_id")
        topic = _require_text(payload.get("topic"), "topic")
        return {
            "status": "session_exit",
            "outcome": _SESSION_EXIT_OUTCOMES["spawn_topic"],
            "finding_id": finding_id,
            "topic": topic,
            "via": _SESSION_EXIT_VIA,
        }

    @router.post("/abstain")
    def abstain(payload: dict = Body(...)):
        """Outcome 6 — abstain: no verdict, honest exit, re-look later. Like
        spawn_topic this is a SESSION-EXIT, NOT a one-shot writer: the only writer
        is ``end_session`` (outcome ``abandoned`` -> a session-local feedback
        event, NO verdict ledger). WRITES NOTHING and execs NOTHING — it validates
        the id + note (422 on bad, never coerced) and returns the honest
        session-exit indicator."""
        finding_id = _require_id(payload.get("finding_id"), "finding_id")
        note = _require_text(payload.get("note"), "note")
        return {
            "status": "session_exit",
            "outcome": _SESSION_EXIT_OUTCOMES["abstain"],
            "finding_id": finding_id,
            "note": note,
            "via": _SESSION_EXIT_VIA,
        }

    @router.post("/calibration")
    def calibration(payload: dict = Body(...)):
        """Pre-verdict calibration capture (ARCH §6.5.4 ``calibration_entry``):
        the human's prediction + confidence recorded BEFORE the verdict form
        opens. Execs ``orchestrator.calibration_cli calibration --ref-id <id>
        --prediction <text> --confidence <0..1> --by human:ui`` (writer of record;
        appends to run_state/events.jsonl). ``--confidence`` round-trips through
        the CLI's ``type=float`` via ``repr(float(confidence))``. Out-of-range
        confidence 422s BEFORE any spawn — never coerced."""
        ref_id = _require_id(payload.get("ref_id"), "ref_id")
        prediction = _require_text(payload.get("prediction"), "prediction")
        confidence = payload.get("confidence")
        # confidence is a probability in [0,1] — never coerced; out-of-range 422s.
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
            raise HTTPException(
                status_code=422,
                detail="confidence is required (a number in [0,1])")
        if not (0.0 <= float(confidence) <= 1.0):
            raise HTTPException(
                status_code=422,
                detail=f"confidence must be in [0,1] (got {confidence!r})")
        module, _ = _SEAM_MODULES["calibration"]
        return _exec_blessed(run, root, module, [
            "calibration",
            "--ref-id", ref_id,
            "--prediction", prediction,
            "--confidence", repr(float(confidence)),
            "--by", IDENTITY,
        ])

    @router.get("/concurrency")
    def concurrency():
        """The ONE real (non-stub) read endpoint: read-only
        ``run_state/active_run.json`` (the legacy single-slot mirror the D-047
        registry also falls back to) so
        the cockpit can warn when an iteration is mid-flight (seam-1 concurrency
        guard). Absent file => ``{active: false}``. Never writes. Reads the
        run-state mirror only; on a malformed/unreadable file we fail safe to
        ``active: false`` (a warn-banner missing is harmless; a 500 would wedge
        the cockpit)."""
        path = root / "run_state" / "active_run.json"
        if not path.exists():
            return {"active": False}
        try:
            # parse_constant fires on NaN/Infinity/-Infinity — Python's default
            # json parser ACCEPTS those tokens, but a non-finite float in a
            # surfaced field would later make the JSONResponse encoder emit
            # non-compliant `NaN` and 500 the cockpit. Treat the file as
            # malformed (fail safe to active:false), matching the doctrine: a
            # malformed active_run.json degrades, never 500s.
            data = json.loads(
                path.read_text(encoding="utf-8"),
                parse_constant=_reject_non_finite,
            )
        except (OSError, json.JSONDecodeError, ValueError):
            return {"active": False}
        if not isinstance(data, dict):
            return {"active": False}
        out: dict = {"active": True}
        for field in ("kind", "label", "narration"):
            value = data.get(field)
            if value is None:
                continue
            # A pathologically-nested surfaced value would overflow the
            # JSONResponse encoder (RecursionError -> 500, outside the read's
            # try/except). Drop the field rather than surface a value that
            # cannot be encoded; valid scalar fields (depth 0) are unaffected.
            if not _within_depth(value):
                continue
            out[field] = value
        return out

    app.include_router(router)
    return router
