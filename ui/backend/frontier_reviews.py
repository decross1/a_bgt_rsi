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

Plus a per-vendor ``health`` block off run_state/frontier_calls.jsonl with
DECODED failures (127 → "binary not found (PATH)", -1/124 → "timed out",
other nonzero → "CLI error (exit N)") — the 2026-08-18T06:00:43Z outage
(claude exit 1 + codex exit 127) must read as one legible outage line in
the strip, not two mystery rows in a table.

Bounded tail reads (frontier_calls.py's `_tail_records`, reused), a short
TTL cache (served_models.py's pattern — the compose walks three ledgers +
one full reduction), and honest degradation: an absent file is
``available: false`` with zero events from it; an unreadable idea ledger
is REPORTED in ``ledger_join`` (rule 4 — never silently coerced) while
the screen/agenda feed still serves. Read-only: writes nothing.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

from fastapi import APIRouter

from .frontier_calls import (
    DEFAULT_FRONTIER_LEDGER,
    TAIL_BYTES as CALLS_TAIL_BYTES,
    _env_path,
    _exit_streaks,
    _parse_ts,
    _tail_records,
    _utcnow_iso,
)
from datetime import datetime, timedelta, timezone

_PRIMARY = Path("/home/decross1/projects/a_bgt_rsi")
DEFAULT_SCREEN_LEDGER = _PRIMARY / "run_state" / "frontier_cluster_screen.jsonl"
DEFAULT_AGENDA_PATH = _PRIMARY / "memory" / "frontier_agenda.jsonl"
DEFAULT_IDEA_LEDGER = _PRIMARY / "memory" / "idea_ledger.jsonl"

# Screen rows carry two full reasoning texts (~3-6 KB/row) → 512 KiB ≈ 100+
# screenings; agenda rows are ~0.8 KB → 128 KiB ≈ 150 proposals. Weeks of
# frontier traffic either way (the tier fires on promotion candidates only).
SCREEN_TAIL_BYTES = 512 * 1024
AGENDA_TAIL_BYTES = 128 * 1024

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
             calls_path: Path | None = None,
             idea_ledger_path: Path | None = None,
             loop_memory_path: Path | None = None,
             repo_root: Path = _PRIMARY,
             screen_tail_bytes: int = SCREEN_TAIL_BYTES,
             agenda_tail_bytes: int = AGENDA_TAIL_BYTES,
             calls_tail_bytes: int = CALLS_TAIL_BYTES,
             ttl_s: float = CACHE_TTL_S,
             clock=time.monotonic) -> APIRouter:
    """Attach the frontier-reviews router (register-fn idiom). Paths resolve
    kwarg → UI_* env override → primary checkout; tests pin tmp paths via
    the kwargs. ``ttl_s``/``clock`` are injectable for the TTL tests."""
    screen_path = Path(screen_path) if screen_path else _env_path(
        "UI_FRONTIER_SCREEN_LEDGER", DEFAULT_SCREEN_LEDGER)
    agenda_path = Path(agenda_path) if agenda_path else _env_path(
        "UI_FRONTIER_AGENDA", DEFAULT_AGENDA_PATH)
    calls_path = Path(calls_path) if calls_path else _env_path(
        "UI_FRONTIER_LEDGER", DEFAULT_FRONTIER_LEDGER)
    idea_ledger_path = Path(idea_ledger_path) if idea_ledger_path else \
        _env_path("UI_IDEA_LEDGER", DEFAULT_IDEA_LEDGER)
    loop_memory_path = Path(loop_memory_path) if loop_memory_path else \
        _env_path("UI_LOOP_MEMORY", DEFAULT_LOOP_MEMORY)

    router = APIRouter(prefix="/api", tags=["frontier_reviews"])
    cache: dict = {"at": None, "payload": None}
    lock = threading.Lock()

    def _size_of(path: Path) -> int:
        try:
            return path.stat().st_size
        except OSError:
            return -1  # absent/unreadable — distinct from an empty file (0)

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
        screen_size = _size_of(screen_path)
        agenda_size = _size_of(agenda_path)
        calls_size = _size_of(calls_path)

        idea_state, ledger_join = _load_idea_state()

        events: list[dict] = []
        hypo_heads: dict | None = None  # lazy — only read on first miss
        for row in _tail_records(screen_path, screen_tail_bytes):
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

        for row in _tail_records(agenda_path, agenda_tail_bytes):
            events.append({
                "type": "agenda",
                "ts": row.get("ts"),
                "proposal_id": row.get("proposal_id"),
                "proposed_by": row.get("proposed_by"),
                "topic": row.get("topic"),
                "rationale": row.get("rationale"),
                "status": row.get("status"),
            })

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

        calls_rows = _tail_records(calls_path, calls_tail_bytes)
        return {
            "available": {
                "screen": screen_size >= 0,
                "agenda": agenda_size >= 0,
                "calls": calls_size >= 0,
            },
            "events": events,
            "events_in_window": len(events),
            "health": _health(calls_rows),
            "ledger_join": ledger_join,
            "windows": {
                "screen": {"bytes": screen_tail_bytes,
                           "truncated": screen_size > screen_tail_bytes},
                "agenda": {"bytes": agenda_tail_bytes,
                           "truncated": agenda_size > agenda_tail_bytes},
                "calls": {"bytes": calls_tail_bytes,
                          "truncated": calls_size > calls_tail_bytes},
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

    app.include_router(router)
    return router
