"""Cockpit chat exec seam — the LIVE `finding_session chat` start/turn surface.

The `/todo` cockpit's interrogation panes (U2 tutor / U3 two-voice) talk to a
real model session through ONE blessed CLI: ``orchestrator.finding_session chat
start|turn`` (docs/cockpit_seam_wiring.md, the chat-seam rows). Like
``ui/backend/attest.py``, this module NEVER writes a ledger — it execs the
blessed CLI as an **argv array** (no shell, no string interpolation), with
``cwd`` = the primary repo root and interpreter ``.venv-chroma/bin/python``. The
CLI owns its own session transcript (D-046); the seam writes nothing itself.

The chat branch is **VERDICT-FENCED**: ``_chat_cli`` exposes ONLY ``start`` and
``turn`` — there is no disposition/verdict verb reachable here (a tutor
transcript can never be closed with a verdict). This seam therefore offers
exactly two endpoints, neither of which can dispose of a finding.

Endpoints, wired by ``register`` into the existing FastAPI app:

- ``POST /api/todo/chat/start`` — ``{mode, finding_id}``
- ``POST /api/todo/chat/turn``  — ``{mode, finding_id, session_id, message,
  addressee?}``

Mode semantics (mirrors the landed CLI, finding_session.py:1149-1210):

- ``tutor`` is single-voice — ``--addressee`` is INVALID (the CLI rejects it),
  so this seam NEVER forwards an addressee in tutor mode. Start returns
  ``stances: null``; a turn returns one reply with ``stance: null`` and NO
  ``addressee`` key.
- ``two_voice`` carries the two-stance object (defender = vllm-gemma, attacker
  = vllm-qwen). ``--addressee`` (``defender|attacker|both``) is forwarded only
  when provided; the CLI defaults it to ``both``.

Success (CLI exit 0): ONE JSON line on stdout, parsed and returned as-is.
Failure (CLI exit != 0): a 502 carrying ``{rc, stderr}`` with the CLI's stderr
VERBATIM — the JSON error envelope (KeyError/ValueError, exit 1) or argparse
usage (exit 2) rides in stderr un-summarized. Pre-validation here is UX-only
(422 on a bad mode / empty id / missing turn fields / a tutor addressee) and
happens BEFORE any spawn; the CLI re-validates authoritatively (inviolate rule
4 — out-of-shape input is rejected, never coerced).
"""
from __future__ import annotations

import math
import re
import subprocess
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import JSONResponse

# Reuse the blessed-exec runner + the primary-checkout constant from attest. The
# helper absolutizes ``.venv-chroma/bin/python`` under ``repo_root``, runs an
# argv ARRAY with ``cwd=repo_root`` (never ``shell=True``), returns the parsed
# stdout on rc==0, and a 502 ``{rc, stderr}`` verbatim on rc!=0 / spawn failure.
# attest is read-only to this module (import only).
from .attest import _PRIMARY_REPO, _exec_blessed

# The one blessed module this seam execs (its only writer of record).
_CHAT_MODULE = "orchestrator.finding_session"

# Frozen enums — mirrors of the CLI's own argparse ``choices``, never wider:
#   CHAT_MODES  — finding_session.py:1150 (TUTOR_MODE, "two_voice")
#   ADDRESSEES  — two_voice_turn addressee (defender|attacker|both)
TUTOR_MODE = "tutor"
CHAT_MODES = ("tutor", "two_voice")
ADDRESSEES = ("defender", "attacker", "both")

# Conservative id charset — identical to attest._ID_RE: no shell anywhere, so the
# injection vector is argv-FLAG confusion (a leading "-" parses as a flag).
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_MAX_ID_LEN = 200

# The seam returns the CLI's stdout JSON verbatim (via attest._exec_blessed). A
# (malformed/hostile) CLI could emit a parseable-but-UNENCODABLE envelope:
#   - deeply NESTED (json.loads accepts it; the JSONResponse encoder then walks
#     it recursively, and the request call stack is already deep — a few thousand
#     levels RecursionError -> 500, AFTER _exec_blessed returned the dict);
#   - a NON-FINITE float (json.loads accepts NaN/Infinity by default; the encoder
#     then emits non-compliant `NaN` / 500s);
#   - a huge BIGINT (>4300 digits) — json.loads itself raises a bare ValueError
#     (NOT a JSONDecodeError), which escapes attest's (JSONDecodeError, TypeError)
#     catch and 500s before any response is built.
# None of these can reach attest (a finalized file). The seam guards them here:
# the bigint ValueError is caught around the exec, and a returned envelope is
# depth/finite-checked before it leaves the seam. An unencodable envelope is an
# envelope-contract break (D-046) — surfaced as a 502 (never 500, never faked as
# success), the same shape the zero-exit-non-JSON case already returns. Cap
# mirrors todo_cockpit._MAX_FIELD_DEPTH (32): well past any real chat envelope.
_MAX_ENVELOPE_DEPTH = 32


def _encode_safe(value, limit: int = _MAX_ENVELOPE_DEPTH) -> bool:
    """True if `value` is JSON-encode-safe for a FastAPI JSONResponse: it nests
    no deeper than `limit`, contains no non-finite float (NaN/Infinity), and
    contains no string carrying a lone/unpaired surrogate code point. The walk is
    ITERATIVE (an explicit stack) so the guard cannot itself overflow on the
    pathological input it exists to reject — same idiom as the cockpit's
    ``_within_depth``. Chat envelopes are MODEL output, so a stray surrogate /
    non-finite float is a real vector."""
    stack = [(value, 0)]
    while stack:
        node, depth = stack.pop()
        if depth > limit:
            return False
        if isinstance(node, float) and not math.isfinite(node):
            return False
        if isinstance(node, str) and not node.isascii():
            # A lone/unpaired surrogate (a producer/model ``"\udXXX"``) parses
            # fine but is not UTF-8-encodable, so JSONResponse 500s AFTER the read
            # (same valid-to-parse / fatal-to-encode class as NaN/Infinity).
            # isascii() fast-paths; only a surrogate trips the encode probe.
            try:
                node.encode("utf-8")
            except UnicodeEncodeError:
                return False
        if isinstance(node, dict):
            for k, v in node.items():
                # a surrogate can ride a dict KEY too — push at the same depth
                stack.append((k, depth))
                stack.append((v, depth + 1))
        elif isinstance(node, list):
            for v in node:
                stack.append((v, depth + 1))
    return True


def _exec_chat(run, root, args):
    """Exec the blessed chat CLI and return an ENCODE-SAFE response.

    Delegates to ``attest._exec_blessed`` (the one blessed-exec path), then hardens
    the success branch against a pathological stdout envelope that would otherwise
    500 the response encoder (deep nesting / non-finite float / huge bigint).

    - ``_exec_blessed`` already maps rc!=0, spawn failure, and zero-exit
      non-JSON to a 502 ``JSONResponse`` — those pass straight through.
    - A huge bigint makes ``json.loads`` (inside ``_exec_blessed``) raise a bare
      ``ValueError`` that its ``(JSONDecodeError, TypeError)`` catch misses; we
      catch it here and surface a 502 (the same envelope-broke-the-contract shape).
    - A returned dict/list is depth/finite-checked; if it is not encode-safe it is
      a contract break -> 502 (never a 500, never a clipped/faked reply shape)."""
    try:
        result = _exec_blessed(run, root, _CHAT_MODULE, args)
    except ValueError:
        # json.loads of a >4300-digit int raises a bare ValueError (not a
        # JSONDecodeError) inside _exec_blessed; treat as a broken envelope.
        return JSONResponse(status_code=502, content={
            "rc": 0,
            "error": "CLI exited 0 but stdout JSON was not encode-safe "
                     "(unparseable numeric literal)"})
    if isinstance(result, (dict, list)) and not _encode_safe(result):
        return JSONResponse(status_code=502, content={
            "rc": 0,
            "error": "CLI exited 0 but stdout JSON was not encode-safe "
                     "(over-deep or non-finite envelope)"})
    return result


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
    """422 unless `value` is a non-empty (non-whitespace) string. The message is
    free text — never a positional argv flag (always preceded by ``--message``)."""
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
    """Attach the chat-seam router (sibling-module pattern, cf.
    ``attest.register`` — the same ``repo_root: Path | None`` defaulting to the
    primary checkout). ``runner`` defaults to ``subprocess.run`` and is injectable
    so tests stub the exec — tests NEVER exec a real CLI or a real model."""
    root = Path(repo_root) if repo_root is not None else _PRIMARY_REPO
    run = runner if runner is not None else subprocess.run
    router = APIRouter(prefix="/api/todo/chat", tags=["todo-cockpit-chat"])

    @router.post("/start")
    def chat_start(payload: dict = Body(...)):
        """Open a chat session via ``finding_session chat start``. Returns the
        start envelope ``{ok, mode, action:"start", finding_id, session_id,
        stances}`` (``stances`` null in tutor, the two-stance object in
        two_voice). No verdict verb is reachable (the fence)."""
        mode = _require_enum(payload.get("mode"), CHAT_MODES, "mode")
        finding_id = _require_id(payload.get("finding_id"), "finding_id")
        return _exec_chat(run, root, [
            "chat", "start",
            "--mode", mode,
            "--finding-id", finding_id,
        ])

    @router.post("/turn")
    def chat_turn(payload: dict = Body(...)):
        """Send ONE human-directed turn via ``finding_session chat turn``.
        Returns the turn envelope (tutor: single ``stance:null`` reply, NO
        ``addressee`` key; two_voice: stance-tagged replies + ``addressee`` +
        ``warning``). In tutor mode the seam NEVER forwards ``--addressee`` (the
        CLI rejects it); in two_voice it forwards ``--addressee`` only when
        provided. The CLI owns the session transcript — the seam writes nothing."""
        mode = _require_enum(payload.get("mode"), CHAT_MODES, "mode")
        finding_id = _require_id(payload.get("finding_id"), "finding_id")
        session_id = _require_id(payload.get("session_id"), "session_id")
        message = _require_text(payload.get("message"), "message")
        args = [
            "chat", "turn",
            "--mode", mode,
            "--finding-id", finding_id,
            "--session-id", session_id,
            "--message", message,
        ]
        addressee = payload.get("addressee")
        if mode == TUTOR_MODE:
            # Tutor is single-voice — the CLI rejects --addressee. Reject a
            # supplied addressee here for a clean 422 (never coerced, never
            # forwarded) rather than spawning into a guaranteed CLI error.
            if addressee is not None:
                raise HTTPException(
                    status_code=422,
                    detail="addressee is not valid in tutor mode (single-voice)")
        elif addressee is not None:
            # two_voice: forward only when provided; the CLI defaults to "both".
            args += ["--addressee",
                     _require_enum(addressee, ADDRESSEES, "addressee")]
        return _exec_chat(run, root, args)

    app.include_router(router)
    return router
