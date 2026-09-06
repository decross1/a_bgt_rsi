"""Frontier-review SUBSTANCE seam — what the frontier tier actually SAID.

Owner rejection 2026-08-18 of the live "Frontier reviews" panel: it listed
CLI invocations (vendor/role/exit/latency) and no content — "i can't even
see what their debating issue was". The substance was on disk the whole
time and the panel never read it. This module reads it:

``GET /api/frontier_reviews`` — ONE merged, newest-first feed of typed
events answering "what has the frontier falsifier tier (D-061: claude =
methods, codex = novelty; veto/annotate only) said about the lab's ideas,
and did it change anything?":

- ``screen`` — run_state/frontier_cluster_screen.jsonl: the promotion
  screen's per-cluster verdicts WITH each role's full reasoning text, the
  cross-run summary when the vetoing role re-ran on the other vendor
  (D-061 semantics), and a ``claim_head`` joined from the idea-ledger
  reduction so the reader sees WHAT was being judged (absent → omitted,
  never fabricated).
- ``agenda`` — memory/frontier_agenda.jsonl: the agenda_synthesist's
  proposals (topic + rationale + proposed_by).
- ``refine`` — memory/idea_ledger.jsonl ``cluster_refined`` events via the
  SAME reducer the /api/ladder seam uses (workers.idea_ledger.load_state,
  lazy-imported): round, refined-claim head, feedback digest — the D-064
  "did it change anything?" evidence.

Agenda events additionally carry ``effective_status`` — the JOIN of the
proposals file against ``memory/frontier_agenda.status.jsonl`` (the
append-only audit ``orchestrator/agenda_cli.py`` writes; last row wins). Ten
proposals sat at ``proposed`` with nothing consuming them because the HUMAN
acceptance step had no surface; ``POST /api/frontier_agenda/accept`` and
``/dismiss`` are that surface. Both exec the blessed CLI as an argv ARRAY via
``attest._exec_blessed`` (no shell, ``human:ui`` stamped, the CLI is the
writer of record — D-046); this module still writes nothing itself.

Plus a per-vendor ``health`` block off run_state/frontier_calls.jsonl with
DECODED failures (127 → "binary not found (PATH)", -1/124 → "timed out",
other nonzero → "CLI error (exit N)") — the 2026-08-18T06:00:43Z outage
(claude exit 1 + codex exit 127) must read as one legible outage line in
the strip, not two mystery rows in a table.

Bounded screen/agenda/calls tails, a complete streaming status-audit scan,
a short TTL cache (served_models.py's pattern), and honest degradation:
missing/unreadable/malformed/truncated sources are explicit in ``integrity``;
an unreadable idea ledger is separately REPORTED in ``ledger_join`` (rule 4
— never silently coerced) while the screen/agenda feed still serves.
Read-only: writes nothing.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import JSONResponse

from .attest import _exec_blessed
from .frontier_calls import (
    DEFAULT_FRONTIER_LEDGER,
    TAIL_BYTES as CALLS_TAIL_BYTES,
    _env_path,
    _exit_streaks,
    _parse_ts,
    _utcnow_iso,
)
from datetime import datetime, timedelta, timezone

_PRIMARY = Path("/home/decross1/projects/a_bgt_rsi")
DEFAULT_SCREEN_LEDGER = _PRIMARY / "run_state" / "frontier_cluster_screen.jsonl"
DEFAULT_AGENDA_PATH = _PRIMARY / "memory" / "frontier_agenda.jsonl"
DEFAULT_AGENDA_STATUS = _PRIMARY / "memory" / "frontier_agenda.status.jsonl"
DEFAULT_IDEA_LEDGER = _PRIMARY / "memory" / "idea_ledger.jsonl"

# The blessed writer of the acceptance step + the interpreter that runs it
# (existence-checked for the agenda_write capability handshake).
_AGENDA_MODULE = "orchestrator.agenda_cli"
_AGENDA_MODULE_REL = Path("orchestrator") / "agenda_cli.py"
_PYTHON_REL = Path(".venv-chroma") / "bin" / "python"

# Frozen mirror of the CLI's verbs — never wider (rule 4; the CLI
# re-validates authoritatively).
AGENDA_VERBS = ("accept", "dismiss")
# Frozen mirror of agenda_cli.STATUSES (what an audit row may say).
AGENDA_STATUSES = ("accepted", "dismissed")

# Every write the UI initiates stamps this identity (write-back contract §6).
IDENTITY = "human:ui"

# Conservative id charset — identical to attest._ID_RE. There is no shell
# anywhere here, so the injection vector is argv-FLAG confusion (a leading
# "-" parses as a flag); spaces / ";" / "&&" are simply not ids.
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_MAX_ID_LEN = 200

# Screen rows carry two full reasoning texts (~3-6 KB/row) → 512 KiB ≈ 100+
# screenings; agenda rows are ~0.8 KB → 128 KiB ≈ 150 proposals. Weeks of
# frontier traffic either way (the tier fires on promotion candidates only).
SCREEN_TAIL_BYTES = 512 * 1024
AGENDA_TAIL_BYTES = 128 * 1024
# Kept as a register() compatibility default for callers/tests that supplied
# the old knob. Status is no longer tail-read: human rulings are streamed from
# the beginning of the audit file so older decisions cannot disappear.
STATUS_TAIL_BYTES = 64 * 1024

# Source errors are counted by scanning the complete selected input, while the
# wire detail stays bounded. The final entry says how many details were elided.
MAX_SOURCE_ERROR_DETAILS = 20

# Claim heads are context, not the document — ~140 chars, marked truncation.
CLAIM_HEAD_CHARS = 140

# Compose walks 3 ledger tails + one full idea-ledger reduction; the cache
# collapses that out of every dashboard poll (served_models.py pattern).
CACHE_TTL_S = 5.0

DEFAULT_LIMIT = 20
MAX_LIMIT = 100

DEFAULT_LOOP_MEMORY = _PRIMARY / "memory" / "loop_memory.jsonl"

# {path: (mtime_ns, size, {iteration_id: hypothesis_head})} — most live
# clusters were consolidation-created WITHOUT claim text (review finding:
# 1/128 carries one), so the founding iteration's hypothesis is the honest
# fallback for "what was being judged". Memoized per file change; the file
# is a few MB and grows ~hourly.
_HYPO_MEMO: dict = {}
_HYPO_LOCK = threading.Lock()


def _hypothesis_heads(path: Path) -> dict:
    """{iteration_id: hypothesis-text head} from loop_memory, mtime-memoized.
    Unreadable file → empty dict (callers omit the head, never fabricate)."""
    import json as _json
    try:
        st = path.stat()
        key = (st.st_mtime_ns, st.st_size)
    except OSError:
        return {}
    with _HYPO_LOCK:
        cached = _HYPO_MEMO.get(str(path))
        if cached and cached[0] == key:
            return cached[1]
    heads: dict = {}
    try:
        with path.open() as fh:
            for line in fh:
                try:
                    row = _json.loads(line)
                except ValueError:
                    continue
                iid = row.get("iteration_id")
                hyp = row.get("hypothesis")
                text = hyp.get("text") if isinstance(hyp, dict) else None
                head = _head(text)
                if isinstance(iid, str) and head:
                    heads[iid] = head
    except OSError:
        return {}
    with _HYPO_LOCK:
        _HYPO_MEMO[str(path)] = (key, heads)
    return heads


def _founding_iteration(cluster, cluster_id):
    """First iter-* member of the reduced cluster, else the id embedded in
    a 'cl-iter-…' cluster_id, else None."""
    if isinstance(cluster, dict):
        for member in cluster.get("members") or []:
            if isinstance(member, str) and member.startswith("iter-"):
                return member
    if isinstance(cluster_id, str) and cluster_id.startswith("cl-iter-"):
        return cluster_id[3:]
    return None


def decode_exit(code: int) -> str:
    """Human decode of a NONZERO frontier-CLI exit code (schema: -1 =
    timeout, 127 = launch failure)."""
    if code in (-1, 124):
        return "timed out"
    if code == 127:
        # Timeless decode ONLY — the 2026-08-18 PATH incident context was
        # stripped here (review catch): a decoder that says "fixed" makes
        # any FUTURE 127 look already-healed.
        return "binary not found (PATH)"
    return f"CLI error (exit {code})"


def _head(text, limit: int = CLAIM_HEAD_CHARS):
    """Whitespace-collapsed head of a claim text, truncated with a visible
    mark. None/empty in → None out (callers omit, never fabricate)."""
    if not isinstance(text, str) or not text.strip():
        return None
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    return flat[:limit].rstrip() + "…"


def _claim_head_of(cluster: dict):
    """Best claim text for a cluster from the REDUCED ledger state: the
    latest refined_claim (D-064) wins, else the elite claim's fields.
    None when the cluster genuinely carries no claim text."""
    head = _head(cluster.get("refined_claim"))
    if head:
        return head
    elite = cluster.get("elite") if isinstance(cluster.get("elite"), dict) else {}
    claim = elite.get("claim")
    if isinstance(claim, str):
        return _head(claim)
    if isinstance(claim, dict):
        for key in ("problem", "mechanism", "predicted_effect"):
            head = _head(claim.get(key))
            if head:
                return head
    return None


def _screen_event(row: dict) -> dict:
    """One screen-ledger row → one typed feed event. Reasoning ships FULL —
    the substance is the point; the frontend owns the clamp."""
    screen = row.get("screen") if isinstance(row.get("screen"), dict) else {}
    event = {
        "type": "screen",
        "ts": row.get("ts"),
        "cluster_id": row.get("cluster_id"),
        "evidence_level": row.get("evidence_level"),
        "verdict": screen.get("verdict"),
        "seconds": row.get("seconds"),
        "roles": {},
    }
    if "escalated" in screen:
        event["escalated"] = screen.get("escalated")
    summaries = []
    for role_name in ("methods", "novelty"):
        role = screen.get(role_name)
        if not isinstance(role, dict):
            continue
        role_event = {k: role.get(k) for k in
                      ("verdict", "reasoning", "vendor", "closest_prior_work")
                      if k in role}
        cross = role.get("cross_run")
        if isinstance(cross, dict):
            role_event["cross_run"] = {
                k: cross.get(k) for k in
                ("verdict", "reasoning", "vendor", "closest_prior_work")
                if k in cross}
            # D-061 semantics on one line: the vetoing role re-ran on the
            # other vendor. Verdicts verbatim — an unparseable cross-run
            # says so rather than implying agreement.
            who = ("the vetoing" if role.get("verdict") == "veto" else "the")
            summaries.append(
                f"{who} {role_name} reviewer re-ran on "
                f"{cross.get('vendor') or 'the other vendor'}: "
                f"{cross.get('verdict') or 'unparseable'}")
        event["roles"][role_name] = role_event
    if summaries:
        event["cross_run_summary"] = "; ".join(summaries)
    return event


def _require_id(value, field: str) -> str:
    """422 unless `value` is a conservative-charset id (no leading dash).
    A proposal_id carrying spaces / ``;`` / ``&&`` is rejected HERE, before
    any spawn — belt-and-braces over the argv-array exec (there is no shell
    to inject into; the residual vector is argv-flag confusion)."""
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
    (--note / --topic-override) is not charset-restricted — it is never a
    positional argv token (always preceded by its --flag)."""
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(
            status_code=422, detail=f"{field} is required (non-empty string)")
    return value


def _agenda_event(row: dict, status_index: dict, *, status_complete: bool) -> dict:
    """One proposals-file row → one agenda feed event, joined to its ruling.
    ``effective_status`` is authoritative only after the entire status audit
    was read without error. Incomplete/missing history becomes ``unknown`` —
    never a fabricated fresh proposal. A valid observed ruling still ships in
    ``ruling`` so a separate malformed row cannot erase human evidence."""
    pid = row.get("proposal_id")
    ruling = status_index.get(pid) if isinstance(pid, str) else None
    own = row.get("status")
    if not status_complete:
        effective_status = "unknown"
    elif isinstance(ruling, dict):
        effective_status = ruling["status"]
    else:
        effective_status = own if isinstance(own, str) and own else "proposed"
    event = {
        "type": "agenda",
        "ts": row.get("ts"),
        "proposal_id": pid,
        "proposed_by": row.get("proposed_by"),
        "topic": row.get("topic"),
        "rationale": row.get("rationale"),
        "status": own,
        "effective_status": effective_status,
    }
    if isinstance(ruling, dict):
        event["ruling"] = {
            "status": ruling.get("status"),
            "note": ruling.get("note"),
            "ts": ruling.get("ts"),
            "agent_id": ruling.get("agent_id"),
            "cluster_id": ruling.get("cluster_id"),
            "topic": ruling.get("topic"),
        }
    return event


def _health(calls_rows: list[dict]) -> dict:
    """Per-vendor health off the calls-ledger tail (oldest-first input).
    Streak logic is REUSED from frontier_calls (loop_health's shape)."""
    newest_first = list(reversed(calls_rows))
    streaks = _exit_streaks(newest_first)
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)
    health: dict[str, dict] = {}
    for rec in newest_first:
        vendor = rec.get("vendor")
        code = rec.get("exit_code")
        if not isinstance(vendor, str) or not vendor \
                or not isinstance(code, int) or isinstance(code, bool):
            continue
        entry = health.setdefault(vendor, {
            "calls_24h": 0,
            "last_ok_ts": None,
            "last_ok_age_s": None,
            "consecutive_failures": streaks.get(vendor, 0),
            "last_error": None,
        })
        if _parse_ts(rec.get("timestamp")) >= cutoff:
            entry["calls_24h"] += 1
        if code == 0 and entry["last_ok_ts"] is None:
            entry["last_ok_ts"] = rec.get("timestamp")
            age = (now - _parse_ts(rec.get("timestamp"))).total_seconds()
            entry["last_ok_age_s"] = round(age, 1) if age >= 0 else None
        if code != 0 and entry["last_error"] is None:
            entry["last_error"] = {
                "ts": rec.get("timestamp"),
                "exit_code": code,
                "decoded": decode_exit(code),
            }
    return health


def register(app, *,
             screen_path: Path | None = None,
             agenda_path: Path | None = None,
             agenda_status_path: Path | None = None,
             calls_path: Path | None = None,
             idea_ledger_path: Path | None = None,
             loop_memory_path: Path | None = None,
             repo_root: Path = _PRIMARY,
             screen_tail_bytes: int = SCREEN_TAIL_BYTES,
             agenda_tail_bytes: int = AGENDA_TAIL_BYTES,
             status_tail_bytes: int = STATUS_TAIL_BYTES,
             calls_tail_bytes: int = CALLS_TAIL_BYTES,
             ttl_s: float = CACHE_TTL_S,
             clock=time.monotonic,
             runner=None) -> APIRouter:
    """Attach the frontier-reviews router (register-fn idiom). Paths resolve
    kwarg → UI_* env override → primary checkout; tests pin tmp paths via
    the kwargs. ``ttl_s``/``clock`` are injectable for the TTL tests.
    ``runner`` defaults to ``subprocess.run`` and is injectable so tests stub
    the accept/dismiss exec — they NEVER exec a real CLI (attest idiom)."""
    screen_path = Path(screen_path) if screen_path else _env_path(
        "UI_FRONTIER_SCREEN_LEDGER", DEFAULT_SCREEN_LEDGER)
    agenda_path = Path(agenda_path) if agenda_path else _env_path(
        "UI_FRONTIER_AGENDA", DEFAULT_AGENDA_PATH)
    agenda_status_path = Path(agenda_status_path) if agenda_status_path \
        else _env_path("UI_FRONTIER_AGENDA_STATUS", DEFAULT_AGENDA_STATUS)
    calls_path = Path(calls_path) if calls_path else _env_path(
        "UI_FRONTIER_LEDGER", DEFAULT_FRONTIER_LEDGER)
    idea_ledger_path = Path(idea_ledger_path) if idea_ledger_path else \
        _env_path("UI_IDEA_LEDGER", DEFAULT_IDEA_LEDGER)
    loop_memory_path = Path(loop_memory_path) if loop_memory_path else \
        _env_path("UI_LOOP_MEMORY", DEFAULT_LOOP_MEMORY)

    root = Path(repo_root)
    run = runner if runner is not None else subprocess.run
    router = APIRouter(prefix="/api", tags=["frontier_reviews"])
    cache: dict = {"at": None, "payload": None}
    lock = threading.Lock()

    def _bounded_errors(details: list[str], total: int) -> list[str]:
        """Return bounded error detail without hiding the number omitted."""
        if total <= MAX_SOURCE_ERROR_DETAILS:
            return details
        return [*details,
                f"{total - MAX_SOURCE_ERROR_DETAILS} additional error(s) omitted"]

    def _tail_source(path: Path, window_bytes: int) -> tuple[
            list[dict], int, bool, dict]:
        """Read a JSONL tail plus explicit integrity.

        ``available`` means the source could actually be opened and read; a
        successful stat alone is insufficient. Malformed/non-object rows are
        omitted from data but named in bounded ``errors``. ``complete`` means
        the whole file was in-window and every nonblank row was a JSON object.
        """
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            return [], -1, False, {
                "complete": False, "missing": True,
                "truncated": False, "errors": []}
        except OSError as exc:
            return [], -1, False, {
                "complete": False, "missing": False,
                "truncated": False,
                "errors": [f"stat failed: {type(exc).__name__}: {exc}"]}

        window = min(size, window_bytes)
        truncated = size > window_bytes
        try:
            with path.open("rb") as fh:
                fh.seek(size - window)
                data = fh.read()
        except OSError as exc:
            return [], size, False, {
                "complete": False, "missing": False,
                "truncated": truncated,
                "errors": [f"read failed: {type(exc).__name__}: {exc}"]}

        details: list[str] = []
        error_count = 0

        def note_error(message: str) -> None:
            nonlocal error_count
            error_count += 1
            if len(details) < MAX_SOURCE_ERROR_DETAILS:
                details.append(message)

        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            note_error(f"invalid UTF-8: {exc}")
            text = data.decode("utf-8", errors="replace")
        lines = text.splitlines()
        if truncated and lines:
            # The seek normally lands inside a row. That incomplete boundary
            # row is accounted for by truncated=true rather than a parse error.
            lines = lines[1:]

        rows: list[dict] = []
        for line_no, line in enumerate(lines, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                note_error(f"window line {line_no}: malformed JSON ({exc.msg})")
                continue
            if not isinstance(row, dict):
                note_error(f"window line {line_no}: expected JSON object")
                continue
            rows.append(row)

        return rows, size, error_count == 0, {
            "complete": not truncated and error_count == 0,
            "missing": False,
            "truncated": truncated,
            "errors": _bounded_errors(details, error_count),
        }

    def _status_source(proposal_ids: set[str]) -> tuple[dict, bool, dict]:
        """Stream the complete human audit, retaining only visible rulings.

        This keeps row storage bounded by the agenda window while examining
        every status row from the beginning, so a ruling cannot age out. The
        last valid in-enum row still wins for each visible proposal.
        """
        try:
            agenda_status_path.stat()
        except FileNotFoundError:
            return {}, False, {
                "complete": False, "missing": True,
                "truncated": False, "errors": []}
        except OSError as exc:
            return {}, False, {
                "complete": False, "missing": False,
                "truncated": False,
                "errors": [f"stat failed: {type(exc).__name__}: {exc}"]}

        index: dict[str, dict] = {}
        details: list[str] = []
        error_count = 0

        def note_error(message: str) -> None:
            nonlocal error_count
            error_count += 1
            if len(details) < MAX_SOURCE_ERROR_DETAILS:
                details.append(message)

        try:
            with agenda_status_path.open("rb") as fh:
                for line_no, raw_line in enumerate(fh, start=1):
                    raw_line = raw_line.strip()
                    if not raw_line:
                        continue
                    try:
                        line = raw_line.decode("utf-8")
                    except UnicodeDecodeError as exc:
                        note_error(f"line {line_no}: invalid UTF-8 ({exc})")
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError as exc:
                        note_error(
                            f"line {line_no}: malformed JSON ({exc.msg})")
                        continue
                    if not isinstance(row, dict):
                        note_error(f"line {line_no}: expected JSON object")
                        continue
                    pid = row.get("proposal_id")
                    status = row.get("status")
                    if not isinstance(pid, str) or not pid:
                        note_error(f"line {line_no}: invalid proposal_id")
                        continue
                    if status not in AGENDA_STATUSES:
                        note_error(f"line {line_no}: unrecognized status")
                        continue
                    if pid in proposal_ids:
                        index[pid] = row
        except OSError as exc:
            # Preserve any valid human rulings observed before a mid-stream
            # failure, while withholding an authoritative effective status.
            note_error(f"read failed: {type(exc).__name__}: {exc}")
            return index, False, {
                "complete": False, "missing": False,
                "truncated": False,
                "errors": _bounded_errors(details, error_count)}

        integrity = {
            "complete": error_count == 0,
            "missing": False,
            "truncated": False,
            "errors": _bounded_errors(details, error_count),
        }
        return index, True, integrity

    def _load_idea_state() -> tuple[dict, dict]:
        """Reduced idea-ledger state via the SAME reducer /api/ladder uses.
        Absent = fine (cold checkout); unreadable/invalid = the feed still
        serves, with the failure NAMED in ledger_join (rule 4: reported,
        never recoded into a thinner state)."""
        if not idea_ledger_path.exists():
            return {}, {"ok": True, "clusters": 0, "error": None}
        root = str(Path(repo_root))
        if root not in sys.path:
            sys.path.insert(0, root)
        try:
            import jsonschema  # noqa: F401 — idea_ledger's hard dep
            from workers.idea_ledger import load_state
        except ImportError as exc:
            return {}, {"ok": False, "clusters": 0,
                        "error": f"idea-ledger workers unimportable: {exc}"}
        try:
            state = load_state(idea_ledger_path)
        except Exception as exc:  # ValueError / ValidationError / OSError
            return {}, {"ok": False, "clusters": 0,
                        "error": f"idea_ledger unreadable: {exc}"}
        return state, {"ok": True, "clusters": len(state), "error": None}

    def _compose() -> dict:
        screen_rows, _screen_size, screen_available, screen_integrity = (
            _tail_source(screen_path, screen_tail_bytes))
        agenda_rows, _agenda_size, agenda_available, agenda_integrity = (
            _tail_source(agenda_path, agenda_tail_bytes))
        calls_rows, _calls_size, calls_available, calls_integrity = (
            _tail_source(calls_path, calls_tail_bytes))
        proposal_ids = {
            row["proposal_id"] for row in agenda_rows
            if isinstance(row.get("proposal_id"), str)
        }
        status_index, _status_available, status_integrity = _status_source(
            proposal_ids)

        idea_state, ledger_join = _load_idea_state()

        events: list[dict] = []
        hypo_heads: dict | None = None  # lazy — only read on first miss
        for row in screen_rows:
            event = _screen_event(row)
            cid = event.get("cluster_id")
            cluster = idea_state.get(cid) if isinstance(cid, str) else None
            head = _claim_head_of(cluster) if isinstance(cluster, dict) \
                else None
            if head:  # absent → key omitted, never fabricated
                event["claim_head"] = head
                event["claim_head_source"] = "ledger"
            else:
                # Most live clusters carry NO claim text (consolidation-
                # created); the founding iteration's hypothesis is the
                # honest "what was judged" fallback, source-labelled.
                founder = _founding_iteration(cluster, cid)
                if founder:
                    if hypo_heads is None:
                        hypo_heads = _hypothesis_heads(loop_memory_path)
                    fallback = hypo_heads.get(founder)
                    if fallback:
                        event["claim_head"] = fallback
                        event["claim_head_source"] = "founding_hypothesis"
            events.append(event)

        for row in agenda_rows:
            events.append(_agenda_event(
                row, status_index,
                status_complete=status_integrity["complete"]))

        for cid, cluster in idea_state.items():
            for rev in cluster.get("refine_history") or []:
                if not isinstance(rev, dict):
                    continue
                events.append({
                    "type": "refine",
                    "ts": rev.get("ts"),
                    "cluster_id": cid,
                    "round": rev.get("round"),
                    "refined_claim_head": _head(rev.get("refined_claim")),
                    "feedback_digest": rev.get("feedback_digest"),
                })

        # Newest-first merge; unparseable ts sorts oldest (never fakes recency).
        events.sort(key=lambda e: _parse_ts(e.get("ts")), reverse=True)

        return {
            "available": {
                "screen": screen_available,
                "agenda": agenda_available,
                "calls": calls_available,
            },
            "integrity": {
                "screen": screen_integrity,
                "agenda": agenda_integrity,
                "agenda_status": status_integrity,
                "calls": calls_integrity,
            },
            "events": events,
            "events_in_window": len(events),
            "health": _health(calls_rows),
            "ledger_join": ledger_join,
            # Capability handshake for the accept/dismiss buttons — the
            # blessed writer + its interpreter must EXIST under the primary
            # checkout. Never execs anything (attest /available idiom).
            "agenda_write": {
                "available": (root / _PYTHON_REL).exists()
                and (root / _AGENDA_MODULE_REL).exists(),
                "verbs": list(AGENDA_VERBS),
                "writer": _AGENDA_MODULE,
            },
            "windows": {
                "screen": {"bytes": screen_tail_bytes,
                           "truncated": screen_integrity["truncated"]},
                "agenda": {"bytes": agenda_tail_bytes,
                           "truncated": agenda_integrity["truncated"]},
                "calls": {"bytes": calls_tail_bytes,
                          "truncated": calls_integrity["truncated"]},
            },
            "generated_at": _utcnow_iso(),
        }

    @router.get("/frontier_reviews")
    def frontier_reviews(limit: int = DEFAULT_LIMIT):
        """The merged feed + vendor health. The TTL cache holds the FULL
        composed payload; ``limit`` slices per request so it never busts
        the cache. Cache hits keep the ORIGINAL generated_at — the reader
        can always compute the true age of the answer."""
        capped = min(max(limit, 1), MAX_LIMIT)
        now = clock()
        with lock:
            fresh = (cache["payload"] is not None and cache["at"] is not None
                     and now - cache["at"] < ttl_s)
            payload = cache["payload"] if fresh else None
        if payload is None:
            payload = _compose()
            with lock:
                cache["at"] = clock()
                cache["payload"] = payload
        return {**payload, "events": payload["events"][:capped]}

    def _rule(verb: str, payload: dict):
        """Shared accept/dismiss body: pre-validate (422 BEFORE any spawn,
        never coerced — rule 4), exec the blessed CLI as an argv ARRAY, and
        drop the TTL cache on success so the next poll shows the ruling
        instead of a stale ``proposed`` card."""
        proposal_id = _require_id(payload.get("proposal_id"), "proposal_id")
        note = _require_text(payload.get("note"), "note")
        args = [verb, "--proposal-id", proposal_id, "--note", note,
                "--by", IDENTITY]
        if verb == "accept":
            override = payload.get("topic_override")
            # Absent/None = "keep the vendor's topic". A PRESENT but blank
            # override is a mistake, not a request — 422 rather than silently
            # falling back to the vendor topic the human meant to replace.
            if override is not None:
                args += ["--topic-override",
                         _require_text(override, "topic_override")]
        result = _exec_blessed(run, root, _AGENDA_MODULE, args)
        if not isinstance(result, JSONResponse):  # rc==0: the ruling landed
            with lock:
                cache["at"] = None
                cache["payload"] = None
        return result

    @router.post("/frontier_agenda/accept")
    def frontier_agenda_accept(payload: dict = Body(...)):
        """Accept one proposal onto the idea-ledger agenda. Execs
        ``orchestrator.agenda_cli accept --proposal-id <id> --note <why>
        [--topic-override <text>] --by human:ui`` — the CLI appends the
        schema-validated ``agenda_item_added`` (source ``frontier_proposed``)
        AND the status-audit row; the coordinator consumes ledger agenda
        items first, so an accepted proposal really does reach Nara. Returns
        the CLI's envelope verbatim; nonzero exit -> 502 with stderr."""
        return _rule("accept", payload)

    @router.post("/frontier_agenda/dismiss")
    def frontier_agenda_dismiss(payload: dict = Body(...)):
        """Dismiss one proposal: the audit row ONLY (the idea ledger is not
        touched). The proposals file is never edited in place — effective
        status is the last audit row."""
        return _rule("dismiss", payload)

    app.include_router(router)
    return router
