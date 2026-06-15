"""`/todo` cockpit backend — the NOT-YET-BUILT resolution seams as honest STUBS.

The four already-blessed outcomes (gate_verdict, finding_review, bubble_ack,
defer) live in ``ui/backend/attest.py`` against the D-046 write-back contract —
this module does NOT duplicate them. It carries the cockpit's NET-NEW seams
(``docs/todo_cockpit_seam_plan.md``) that have no writer of record yet:

- ``authorize_fix``    (outcome 4 — the gated autonomy boundary, seam 3/4)
- ``directive_signoff`` (outcome 1 variant — sign-off WITH a ``--directive``)
- ``spawn_topic``      (outcome 5 — the ``finding_followups`` queue)
- ``abstain``          (outcome 6 — honest no-verdict exit)
- ``calibration``      (ARCH §6.5.4 pre-verdict ``calibration_entry`` capture)

Until the primary ships ``docs/todo_cockpit_seam_plan.md``'s writers, every POST
here is a STUB (inviolate rule 4 — a stub never fakes a write or a verdict). A
stub VALIDATES the payload shape exactly as ``attest.py`` does (422 on
missing/empty/out-of-enum, never a silent default), then returns
``{status:"stub", seam, would_run:[argv...]}`` — the argv the future blessed CLI
WILL be invoked with — and writes NOTHING. It opens no file under ``memory/`` or
``run_state/`` (the lone exception is the read-only ``active_run.json`` concurrency
read). ``GET /api/todo/available`` reports these NEW seams as currently false/stub.

The argv shapes mirror the seam plan verbatim so the integrator can swap the stub
body for an ``attest._exec_blessed`` call with zero argv churn once the seams land.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException

# Primary checkout (the same constant attest.py / app.py pin). The future CLIs +
# the read-only active_run.json live here, not in the worktree.
_PRIMARY_REPO = Path("/home/decross1/projects/a_bgt_rsi")

# Every write the cockpit will INITIATE stamps this identity (contract §6). The
# stubs only echo it in would_run; nothing is written yet.
IDENTITY = "human:ui"

# Frozen enums — mirrors of the future writers' own validation, never wider.
#   SPAWN_TOPIC_STATUSES — finding_session spawn-topic dispositions (seam 3)
# (authorize_fix / directive_signoff / abstain / calibration carry no enum field
#  of their own; their validation is required-non-empty id/note/text.)
SPAWN_TOPIC_KINDS = ("finding", "step")

# Conservative id charset — identical to attest._ID_RE: no shell anywhere, so the
# injection vector is argv-FLAG confusion (a leading "-" parses as a flag).
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_MAX_ID_LEN = 200

# The interpreter the contract names (echoed into would_run argv, never executed
# by a stub). Future CLI modules these seams will target.
_PYTHON_REL = Path(".venv-chroma") / "bin" / "python"
_SEAM_MODULES = {
    # name -> (module the future CLI lives in, source file existence-checked)
    "authorize_fix": ("orchestrator.todo_cli", Path("orchestrator") / "todo_cli.py"),
    "directive_signoff": ("orchestrator.gate_cli", Path("orchestrator") / "gate_cli.py"),
    "spawn_topic": ("orchestrator.finding_session", Path("orchestrator") / "finding_session.py"),
    "abstain": ("orchestrator.finding_session", Path("orchestrator") / "finding_session.py"),
    "calibration": ("orchestrator.gate_cli", Path("orchestrator") / "gate_cli.py"),
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
    (inviolate rule 4); the future CLI re-validates authoritatively."""
    if value not in allowed:
        raise HTTPException(
            status_code=422,
            detail=f"{field} must be one of {list(allowed)} (got {value!r})")
    return value


def _stub(seam: str, module: str, args: list[str]) -> dict:
    """The honest stub response: the argv the future blessed CLI WILL run,
    echoed read-only. Writes NOTHING (inviolate rule 4 — no faked write).

    ``would_run`` uses the bare interpreter token ``.venv-chroma/bin/python``
    (relative — it is illustrative, not an exec target); when the seam lands the
    integrator swaps this for ``attest._exec_blessed`` which absolutizes it under
    the primary repo root."""
    return {
        "status": "stub",
        "seam": seam,
        "would_run": [str(_PYTHON_REL), "-m", module, *args],
    }


def register(
    app,
    *,
    repo_root: Path | None = None,
) -> APIRouter:
    """Attach the cockpit router (sibling-module pattern, cf. ``attest.register``).
    ``repo_root`` defaults to the primary checkout and is only read for the
    ``/available`` existence checks + the read-only ``/concurrency`` read; no
    runner is injected because nothing here execs (every POST is a stub)."""
    root = Path(repo_root) if repo_root is not None else _PRIMARY_REPO
    router = APIRouter(prefix="/api/todo", tags=["todo-cockpit"])

    @router.get("/available")
    def available():
        """Capability handshake (cf. attest's /available): reports which NEW
        cockpit writers exist. They are NOT built yet, so every action is
        currently false. The handshake structurally checks the interpreter + the
        seam's target module so it lights up automatically when the writer lands;
        until then ``stub: True`` flags the whole router as advisory-only."""
        python_ok = (root / _PYTHON_REL).exists()
        # Even when the target module file exists, the SEAM (the new subcommand /
        # --directive flag / calibration writer) does not — so actions stay False
        # by design until the seam plan ships and this gate is flipped per-action.
        actions = {name: False for name in _SEAM_MODULES}
        # The two-voice chat pane (seam 1) is NOT a POST-seam in _SEAM_MODULES
        # (it has no would-run CLI), but the cockpit gates the chat pane on this
        # flag, so the handshake MUST report it. It stays False until the
        # finding_session two-stance extension lands.
        actions["two_voice_chat"] = False
        return {
            "available": False,            # no NEW seam is built yet
            "stub": True,                  # the whole router is stub/advisory
            "interpreter_present": python_ok,
            "actions": actions,
        }

    @router.post("/authorize_fix")
    def authorize_fix(payload: dict = Body(...)):
        """Outcome 4 — authorize an autonomous fix (NET-NEW, gated). STUB until
        the seam-4 spawn-contract enqueue writer is blessed. Echoes the future
        argv ``authorize-fix --ref-id <id> --task <statement> --note <why> --by
        human:ui`` (seam plan §Seam 3). Writes NOTHING — the merge gate / D-014
        firewall stay intact (no runtime dispatch here)."""
        ref_id = _require_id(payload.get("ref_id"), "ref_id")
        task = _require_text(payload.get("task"), "task")
        note = _require_text(payload.get("note"), "note")
        module, _ = _SEAM_MODULES["authorize_fix"]
        return _stub("authorize-fix", module, [
            "authorize-fix",
            "--ref-id", ref_id,
            "--task", task,
            "--note", note,
            "--by", IDENTITY,
        ])

    @router.post("/directive_signoff")
    def directive_signoff(payload: dict = Body(...)):
        """Outcome 1 variant — sign off WITH a directive ("proceed to <next
        step>"). STUB until the ``--directive`` flag lands on the sign-off path.
        ``would_run`` is a SUPERSET of the blessed gate_verdict argv (attest's
        gate_verdict) plus ``--directive <next-step>`` — so the form degrades to
        the bare gate_verdict endpoint when the superset is unavailable. Writes
        NOTHING."""
        iteration_id = _require_id(payload.get("iteration_id"), "iteration_id")
        note = _require_text(payload.get("note"), "note")
        directive = _require_text(payload.get("directive"), "directive")
        module, _ = _SEAM_MODULES["directive_signoff"]
        return _stub("directive-signoff", module, [
            "--iteration-id", iteration_id,
            "--verdict", "valid",
            "--note", note,
            "--directive", directive,
            "--gated-by", IDENTITY,
        ])

    @router.post("/spawn_topic")
    def spawn_topic(payload: dict = Body(...)):
        """Outcome 5 — spawn a follow-up topic into ``finding_followups``. STUB
        until the followups writer is wired through a one-shot CLI. Echoes
        ``spawn-topic --ref-id <id> --kind <finding|step> --topic <text> --by
        human:ui``. Writes NOTHING."""
        ref_id = _require_id(payload.get("ref_id"), "ref_id")
        kind = _require_enum(payload.get("kind"), SPAWN_TOPIC_KINDS, "kind")
        topic = _require_text(payload.get("topic"), "topic")
        module, _ = _SEAM_MODULES["spawn_topic"]
        return _stub("spawn-topic", module, [
            "spawn-topic",
            "--ref-id", ref_id,
            "--kind", kind,
            "--topic", topic,
            "--by", IDENTITY,
        ])

    @router.post("/abstain")
    def abstain(payload: dict = Body(...)):
        """Outcome 6 — abstain: no verdict, honest exit, re-look later. STUB. An
        abstain is an explicit non-decision (it does NOT write a verdict ledger —
        rule 4); the future CLI records a session-local feedback event only.
        Echoes ``abstain --ref-id <id> --note <why> --by human:ui``. Writes
        NOTHING."""
        ref_id = _require_id(payload.get("ref_id"), "ref_id")
        note = _require_text(payload.get("note"), "note")
        module, _ = _SEAM_MODULES["abstain"]
        return _stub("abstain", module, [
            "abstain",
            "--ref-id", ref_id,
            "--note", note,
            "--by", IDENTITY,
        ])

    @router.post("/calibration")
    def calibration(payload: dict = Body(...)):
        """Pre-verdict calibration capture (ARCH §6.5.4 ``calibration_entry``):
        the human's prediction + confidence recorded BEFORE the verdict form
        opens. STUB — the calibration_entry run-log writer is a primary seam; do
        NOT write the run-log here. Echoes ``calibration --ref-id <id>
        --prediction <text> --confidence <0..1> --by human:ui``. Writes
        NOTHING."""
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
        return _stub("calibration", module, [
            "calibration",
            "--ref-id", ref_id,
            "--prediction", prediction,
            "--confidence", repr(float(confidence)),
            "--by", IDENTITY,
        ])

    @router.get("/concurrency")
    def concurrency():
        """The ONE real (non-stub) read endpoint: read-only
        ``run_state/active_run.json`` (the same file coordinator/active reads) so
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
