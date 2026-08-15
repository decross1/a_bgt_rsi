"""Lab-channel exec seam — the always-on human ⇄ Nara ⇄ PI conversation (S4).

The Channel page talks to ONE blessed CLI: ``orchestrator.lab_channel``
(LOOP_V1 spawn loop10h-lab-channel-core), whose surface is exactly
``{timeline, turn, delegate}`` — no disposition verb exists on it, and none
is reachable here (the verdict fence: dispositions live in the dossier
reader's forms, never in a chat surface). Like ``chat_seam``, this module
NEVER writes a ledger — it execs the CLI as an **argv array** (no shell, no
string interpolation), ``cwd`` = the primary repo root, interpreter
``.venv-chroma/bin/python``. The CLI owns the transcript
(``memory/lab_channel.jsonl``) and every ledger write.

Environment: the runner inherits the SERVER's env verbatim (chat_seam
idiom) — the backend is launched with MOCK_LLM handled by its own launch
script, so ``env -u MOCK_LLM`` semantics ride in from the server env; the
seam neither sets nor strips anything.

Endpoints, wired by ``register`` into the existing FastAPI app:

- ``GET  /api/channel/available`` — capability handshake (attest idiom:
  existence-check the CLI module + interpreter; never execs). A frontend
  seeing ``available: false`` — or a 404 from an older backend — renders
  the composers preview-only.
- ``GET  /api/channel/timeline?since=&limit=`` — execs ``timeline``
  (pure read, SHORT 30s cap) and returns its printed rows parsed back to
  ``{rows: [{ts, kind, message}]}``. The CLI prints one
  ``"<ts>  [<kind>]  <message>"`` line per row; a multi-line message
  continues its row verbatim (un-matching continuation lines are appended,
  never dropped mid-row).
- ``POST /api/channel/turn`` — ``{role: nara|pi, message}``. Capability-
  gated: when the probe fails it returns a preview that WRITES NOTHING and
  execs nothing (the cockpit's preview idiom). Live: execs ``turn`` under
  the chat seam's 300s cap (a real Gemma turn) and returns
  ``{status, role, reply}`` — the reply text is the CLI's stdout verbatim.
- ``POST /api/channel/delegate`` — ``{kind: research|improvement, text,
  cluster_id?, objective?}``. The human-click hand-off seam (no LLM),
  capability-gated the same way. Live: execs ``delegate`` under the fast
  120s write cap and returns the CLI's stdout JSON verbatim (the written
  rows + transcript mirror).

Failure semantics (D-046): nonzero exit -> 502 carrying ``{rc, stderr}``
with stderr VERBATIM (the CLI's ``rejected: ...`` line rides
un-summarized). Pre-validation here is UX-only (422 before any spawn);
the CLI re-validates authoritatively (inviolate rule 4).
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import JSONResponse

# Reuse the blessed-exec runner + primary-checkout constant (import only;
# attest is read-only to this module). _exec_blessed json-parses stdout —
# right for `delegate` (prints JSON); timeline/turn print raw text and go
# through the local _exec_raw below with the same 502 error surface.
from .attest import _PRIMARY_REPO, _exec_blessed

_CHANNEL_MODULE = "orchestrator.lab_channel"
_PYTHON_REL = Path(".venv-chroma") / "bin" / "python"
_MODULE_REL = Path("orchestrator") / "lab_channel.py"

# Per-verb exec caps. timeline is a pure ledger read (short); turn is a live
# Gemma call (the chat seam's measured 300s cap — a two-voice turn ran ~170s,
# and a channel turn is one voice + context pack); delegate is a one-shot
# validate-then-append writer (attest's fast 120s write cap).
_TIMELINE_TIMEOUT_S = 30
_TURN_TIMEOUT_S = 300
_DELEGATE_TIMEOUT_S = 120

# Frozen enums — mirrors of the CLI's own argparse choices, never wider
# (lab_channel.py _ROLES / delegate kinds).
ROLES = ("nara", "pi")
DELEGATE_KINDS = ("research", "improvement")

# Conservative id charset — identical to attest._ID_RE (no shell anywhere; the
# injection vector is argv-FLAG confusion, hence no leading dash).
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_MAX_ID_LEN = 200

# `--since` is an ISO-UTC lower bound: digits/T/colon/dot/+/Z/dash only,
# starting with a digit (so it can never parse as a flag). The CLI treats it
# as a plain string bound — this is argv hygiene, not date validation.
_SINCE_RE = re.compile(r"^\d[0-9T:.+Z-]*$")
_MAX_SINCE_LEN = 64
_MAX_LIMIT = 1000

# One printed timeline row: "<ts>  [<kind>]  <message>" (lab_channel.main).
# ts is the first token (no spaces in ISO UTC); kind rides in brackets.
_ROW_RE = re.compile(r"^(\S+)  \[([^\]]*)\]  (.*)$")


def _parse_timeline(stdout: str) -> list[dict]:
    """Parse the CLI's printed timeline back into rows.

    A line matching the row shape starts a new row; any other line is a
    CONTINUATION of the previous row's message (turn replies are model text
    and legitimately span lines) and is appended verbatim. A leading
    un-matching line has no row to belong to and is skipped — the same
    tolerant read-only posture the CLI itself takes on its ledgers.
    """
    rows: list[dict] = []
    for line in stdout.splitlines():
        m = _ROW_RE.match(line)
        if m:
            rows.append({"ts": m.group(1), "kind": m.group(2),
                         "message": m.group(3)})
        elif rows:
            rows[-1]["message"] += "\n" + line
    return rows


def _exec_raw(runner, repo_root: Path, args: list[str], *, timeout: int):
    """Exec the blessed channel CLI, returning ``(stdout, error_response)``.

    Same discipline + failure surface as ``attest._exec_blessed`` (argv ARRAY,
    ``cwd`` = primary repo root, rc!=0 / spawn failure -> a 502 ``{rc,
    stderr}`` JSONResponse with stderr verbatim) — but stdout is returned RAW:
    ``timeline`` prints formatted lines and ``turn`` prints the bare reply
    text, so no JSON parse belongs here.
    """
    python_bin = repo_root / _PYTHON_REL
    argv = [str(python_bin), "-m", _CHANNEL_MODULE, *args]
    try:
        proc = runner(argv, cwd=str(repo_root), capture_output=True,
                      text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, JSONResponse(status_code=502, content={
            "rc": None,
            "stderr": f"exec failed before the CLI completed: {exc}"})
    rc = getattr(proc, "returncode", None)
    if rc != 0:
        return None, JSONResponse(status_code=502, content={
            "rc": rc, "stderr": getattr(proc, "stderr", "") or ""})
    return (getattr(proc, "stdout", "") or ""), None


def _require_text(value, field: str) -> str:
    """422 unless `value` is a non-empty (non-whitespace) string. Free text —
    never a positional argv flag (always preceded by its --flag)."""
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


def register(
    app,
    *,
    repo_root: Path | None = None,
    runner=None,
) -> APIRouter:
    """Attach the channel router (sibling-module pattern, cf.
    ``chat_seam.register``). ``runner`` defaults to ``subprocess.run`` and is
    injectable so tests stub the exec — tests NEVER exec a real CLI or a real
    model."""
    root = Path(repo_root) if repo_root is not None else _PRIMARY_REPO
    run = runner if runner is not None else subprocess.run
    router = APIRouter(prefix="/api/channel", tags=["lab-channel"])

    def _capability() -> dict:
        python_ok = (root / _PYTHON_REL).exists()
        cli_ok = (root / _MODULE_REL).exists()
        ok = python_ok and cli_ok
        return {"available": ok, "interpreter_present": python_ok,
                "actions": {"timeline": ok, "turn": ok, "delegate": ok}}

    @router.get("/available")
    def available():
        """Capability handshake (attest idiom): existence-check the blessed
        CLI module + the .venv-chroma interpreter under the primary repo
        root. Never execs anything."""
        return _capability()

    @router.get("/timeline")
    def timeline(since: str | None = Query(default=None),
                 limit: int | None = Query(default=None)):
        """Merged transcript + derived apparatus events, via the CLI's
        ``timeline`` (pure read — derived events are re-derived by the CLI on
        every call, never stored). Returns ``{rows: [{ts, kind, message}]}``
        parsed from the printed lines."""
        args = ["timeline"]
        if since is not None:
            if len(since) > _MAX_SINCE_LEN or not _SINCE_RE.match(since):
                raise HTTPException(
                    status_code=422,
                    detail="since must be an ISO-UTC timestamp "
                           "(digits/T/:/./+/Z/- only, starting with a digit)")
            args += ["--since", since]
        if limit is not None:
            if limit < 1 or limit > _MAX_LIMIT:
                raise HTTPException(
                    status_code=422,
                    detail=f"limit must be in [1, {_MAX_LIMIT}]")
            args += ["--limit", str(limit)]
        stdout, err = _exec_raw(run, root, args, timeout=_TIMELINE_TIMEOUT_S)
        if err is not None:
            return err
        return {"rows": _parse_timeline(stdout)}

    @router.post("/turn")
    def turn(payload: dict = Body(...)):
        """One channel turn with a role voice. Capability-gated: when the
        probe fails, a PREVIEW is returned — nothing is executed, nothing is
        written (the cockpit preview idiom; the frontend renders "not sent").
        Live: execs ``turn --role <nara|pi> --message <text>`` (the CLI
        appends the human row + the reply row to its own transcript) and
        returns ``{status, role, reply}`` with the reply text = the CLI's
        stdout verbatim."""
        role = _require_enum(payload.get("role"), ROLES, "role")
        message = _require_text(payload.get("message"), "message")
        cap = _capability()
        if not cap["available"]:
            return {"status": "preview", "available": False,
                    "would_run": {"role": role, "message": message},
                    "note": "lab_channel CLI not present on this backend — "
                            "nothing was executed or written"}
        stdout, err = _exec_raw(run, root,
                                ["turn", "--role", role, "--message", message],
                                timeout=_TURN_TIMEOUT_S)
        if err is not None:
            return err
        return {"status": "passed", "role": role,
                "reply": stdout.rstrip("\n")}

    @router.post("/delegate")
    def delegate(payload: dict = Body(...)):
        """The human's blessed hand-off (no LLM): research -> an
        agenda_item_added idea-ledger event; improvement -> an authorize_fix
        queue packet row. This endpoint is reached ONLY from the frontend's
        confirm-card click. Capability-gated like /turn (preview when off).
        Live: execs ``delegate`` and returns the CLI's stdout JSON verbatim
        (the written rows + transcript mirror)."""
        kind = _require_enum(payload.get("kind"), DELEGATE_KINDS, "kind")
        text = _require_text(payload.get("text"), "text")
        args = ["delegate", "--kind", kind, "--text", text]
        cluster_id = payload.get("cluster_id")
        if cluster_id is not None:
            args += ["--cluster-id", _require_id(cluster_id, "cluster_id")]
        objective = payload.get("objective")
        if objective is not None:
            args += ["--objective", _require_text(objective, "objective")]
        cap = _capability()
        if not cap["available"]:
            return {"status": "preview", "available": False,
                    "would_run": {"kind": kind, "text": text,
                                  "cluster_id": cluster_id,
                                  "objective": objective},
                    "note": "lab_channel CLI not present on this backend — "
                            "nothing was executed or written"}
        # delegate prints JSON on stdout — _exec_blessed parses + returns it
        # verbatim (rc!=0 -> the same 502 {rc, stderr} surface).
        return _exec_blessed(run, root, _CHANNEL_MODULE, args,
                             timeout=_DELEGATE_TIMEOUT_S)

    app.include_router(router)
    return router
