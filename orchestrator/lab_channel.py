"""Lab Channel — the blessed CLI behind the always-on human ⇄ Nara ⇄ PI
conversation (LOOP_V1, spawn loop10h-lab-channel-core + amend1).

Exactly three subcommands (the fence test pins the surface):
  timeline   deterministic merge (by ts) of the stored transcript with events
             DERIVED AT READ TIME from the existing ledgers — kind "event",
             NEVER stored; pure reads, re-derived on every call.
  turn       one turn with a role voice ("nara" = coordinator/operations,
             "pi" = research): fail-open context pack -> Gemma via call_sync
             -> append the author row THEN the reply row. `--as` names the
             author (default "human"; "oracle" = the ratified mission steward,
             an observer that holds no capability here) so every turn is
             attributable. MOCK_LLM=1 -> a deterministic stub; nothing real
             is called.
  delegate   the human's blessed hand-off seam (no LLM): research -> an
             agenda_item_added idea-ledger event (source "human");
             improvement -> an enqueue row consume_authorize_fix_queue
             accepts (the D-046/D-062 seam).

Transcript: memory/lab_channel.jsonl — append-only, created on first write;
rows {ts, kind: "human"|"oracle"|"nara"|"pi", message, context_digest?,
wrapper_request_id?}. The channel never writes loop_memory; the idea ledger
is written ONLY via delegate (workers.idea_ledger.append_event, validated).
All ledger paths are injectable kwargs resolved at call time (None -> the
module DEFAULT_*), so tests pass tmp paths or monkeypatch the attributes.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_wrapper.wrapper import call_sync
from orchestrator import authorize_fix as _af
from orchestrator.runtime import append_run_log

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TRANSCRIPT = REPO_ROOT / "memory" / "lab_channel.jsonl"
DEFAULT_CYCLES = REPO_ROOT / "run_state" / "coordinator_cycles.jsonl"
DEFAULT_IDEA_LEDGER = REPO_ROOT / "memory" / "idea_ledger.jsonl"
DEFAULT_SURFACED = REPO_ROOT / "memory" / "surfaced_findings.jsonl"
DEFAULT_LOOP_ALERT = REPO_ROOT / "run_state" / "loop_alert.json"
DEFAULT_IDEAS_MD = REPO_ROOT / "memory" / "ideas.md"
DEFAULT_FIX_QUEUE = REPO_ROOT / "memory" / "authorize_fix_queue.jsonl"

CALLS_LOG_PATH = os.environ.get("LOOP_V0_CALLS_LOG", "logs/calls.jsonl")
AGENT_NAME = "lab_channel"
STANDING_CLUSTER = "cl-human-delegations"
TRANSCRIPT_TAIL_ROWS = 12  # context-pack transcript tail size
_ROLES = ("nara", "pi")
# Who may ADDRESS the lab. "human" is the owner; "oracle" is the ratified
# mission steward (2026-08-16) — an OBSERVER of this apparatus: it may
# converse and propose through the blessed seams, never edit the system.
# Adding a participant here does NOT grant any write capability: the
# channel fence (no disposition verbs) binds every participant equally.
_PARTICIPANTS = ("human", "oracle")

_SHARED_HONESTY = (
    "Honesty (D-033/D-036): both channel voices run on the SAME underlying "
    "model (Gemma); 'nara' and 'pi' are perspectives, not independent judges "
    "— never present the other voice as independent confirmation. The "
    "independent voice is the Qwen adversarial skeptic, and it lives in the "
    "finding-session seam, not in this channel."
)

NARA_SYSTEM_PROMPT = (
    "You are NARA, the coordinator/operations voice of the a_bgt_rsi "
    "research apparatus, answering in its lab channel.\n"
    "Speak to WHAT IS RUNNING and WHY: the latest cycle (topic, status, "
    "plan), planner-state gaps, the loop-alert level, and what the apparatus "
    "does next. Cite the context pack; when a part is marked "
    "'[unavailable: ...]' or a number is not in the pack, SAY SO plainly — "
    "never fabricate a number, an id, or a status.\n"
    "CONTEXT PRECEDENCE (2026-08-16): the LIVE pack sections — ideas.md, "
    "coordinator_cycle.planner_state, loop_alert — are AUTHORITATIVE. The "
    "transcript tail is HISTORY and may contain superseded figures: a count "
    "or status you remember from an earlier turn must be re-read from the "
    "live sections before you restate it. Never carry a number forward from "
    "the conversation (Nara restated a stale '31 findings / 8 gates' to "
    "another session this way).\n"
    # NOTE: name seams DESCRIPTIVELY here — this module's fence test greps
    # its source for disposition-seam tokens, and a literal one in a prompt
    # string trips it. The fence stays blunt; the prose adapts.
    "SEAM HONESTY: when asked HOW to do something, name only seams that "
    "exist. If you do not know the seam, say so — never invent a procedure. "
    "The improvement path is ORDERED and you state it in this order, never "
    "reordered or paraphrased into new steps: (1) the proposal enters as an "
    "improvement delegation, which appends an enqueue row to the authorize-fix "
    "queue (memory/authorize_fix_queue.jsonl); (2) an authorized row becomes a "
    "task packet under schema/task_packet.schema.json — RED FIRST: its "
    "acceptance test must exist and be observed FAILING before any builder "
    "runs; (3) the packet dispatcher invokes the builder agent (Qwen on :8001) "
    "under the packet's file scope and attempt cap; (4) tools/premerge_check.sh "
    "plus the full suite gate the branch, and the primary session is the single "
    "merge authority; (5) D-062 entrenchment decides autonomy: Tier P "
    "(workers/, tools/, tests/, docs/, bench/, experiments/) flows through "
    "automatically, Tier S (the orchestrator spine, schema/, version pins, "
    "CLAUDE.md, DECISIONS.md, cron/serve-models.sh, run_state semantics) "
    "requires the owner's ratification, and an untiered path is REFUSED. "
    "Nara's own self-improvement loop (D-066, orchestrator/self_improve.py) "
    "enters that same path at step 2. Research proposals are a DIFFERENT seam: "
    "a research delegation writes an agenda item onto an idea-ledger cluster. "
    "The human's verdict CLI is for gate verdicts on iterations — it is NOT a "
    "step in the improvement path.\n"
    "EVIDENCE A PROPOSAL MUST CARRY: a named live telemetry signal it is "
    "responding to, and an acceptance test that fails today. Ambition, "
    "argument, and a claimed benefit are not evidence.\n"
    "LADDER-ERA FRAMING (D-059): legacy below-bar findings and iterations "
    "belonging to killed clusters are NOT owed human attention — the ladder "
    "owns their fate. Never recommend 'reviewing the backlog' of demoted "
    "items; the human's queue is ONLY what cleared the bar plus live gate "
    "items.\n" + _SHARED_HONESTY
)

PI_SYSTEM_PROMPT = (
    "You are the PI voice of the a_bgt_rsi research apparatus, answering in "
    "its lab channel.\n"
    "Speak to the RESEARCH: clusters, the agenda, the ideas board — what is "
    "alive, what is buried and why, what looks promising. You PROPOSE next "
    "steps; you NEVER dispose — verdicts, promotions, and kills belong to "
    "the human and the evidence ladder. When you discuss a candidate, state "
    "its current evidence rung and what it still OWES per that rung (the "
    "'next:' line in the ideas context) before proposing anything further.\n"
    "CONTEXT PRECEDENCE (2026-08-16): the LIVE pack sections (ideas.md, "
    "coordinator_cycle.planner_state, loop_alert) are AUTHORITATIVE; the "
    "transcript tail is HISTORY and may carry superseded counts — re-read "
    "before restating.\n"
    "LADDER-ERA FRAMING (D-059): demoted/below-bar legacy findings are the "
    "ladder's problem, not the human's — never propose that the human "
    "review them; propose the TESTS their clusters owe instead.\n"
    + _SHARED_HONESTY
)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _norm_ts(ts: Any) -> str:
    """Canonicalize the repo's two UTC spellings so ISO strings sort."""
    return str(ts).replace("+00:00", "Z")


def _or(value, default: Path) -> Path:
    """Injectable-path resolution at CALL time (test/monkeypatch norm)."""
    return Path(value) if value is not None else default


def _read_text(path) -> str | None:
    try:
        return Path(path).read_text()
    except OSError:
        return None


def _read_jsonl(path) -> list[dict[str, Any]]:
    """Missing -> []; malformed lines skipped (read-only observability
    surface, never crashes on a partial write; meta_review's posture)."""
    p = Path(path)
    if not p.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in p.read_text().splitlines():
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _append_jsonl(path, row: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _log(task_id: str, actual: str, expected: str, t0: float) -> None:
    append_run_log({
        "task_id": task_id, "status": "passed",
        "observable_actual": actual, "observable_expected": expected,
        "duration_ms": int((time.perf_counter() - t0) * 1000),
    }, agent=AGENT_NAME)


# ── timeline: stored rows + read-time derived events ─────────────────────────

def _event(ts, source: str, message: str) -> dict[str, str]:
    return {"ts": _norm_ts(ts), "kind": "event", "source": source,
            "message": message}


def _cycle_events(path) -> list[dict]:
    return [
        _event(row["timestamp"], "coordinator_cycles",
               f"cycle: {row.get('topic', '?')} · {row.get('status', '?')} · "
               f"{len(row.get('plan') or [])} plan action(s) · "
               f"promoted {len(row.get('promoted_finding_ids') or [])}")
        for row in _read_jsonl(path) if row.get("timestamp")
    ]


def _idea_events(path) -> list[dict]:
    """Kills/reopens line-by-line; cluster_created batched per (ts, origin)
    so a 70-cluster consolidation is ONE line, not 70."""
    from workers import idea_ledger
    out: list[dict] = []
    created: dict[tuple[str, str], list[dict]] = {}
    for ev in idea_ledger._read_events(path):  # validated raw events
        et = ev["event_type"]
        if et == "cluster_created":
            created.setdefault((ev["ts"], ev["origin"]), []).append(ev)
        elif et == "cluster_killed":
            kr = ev["kill_reason"]
            out.append(_event(ev["ts"], "idea_ledger",
                              f"cluster killed: {ev['cluster_id']} — "
                              f"{kr['code']}: {kr['detail'][:80]}"))
        elif et == "cluster_reopened":
            out.append(_event(ev["ts"], "idea_ledger",
                              f"cluster reopened: {ev['cluster_id']} — "
                              f"{ev['evidence']['evidence_kind']}"))
    for (ts, origin), evs in created.items():
        out.append(_event(ts, "idea_ledger",
                          f"cluster created: {evs[0]['cluster_id']} ({origin})"
                          if len(evs) == 1
                          else f"clusters created: {len(evs)} ({origin})"))
    return out


def _promotion_events(path) -> list[dict]:
    return [
        _event(row["promoted_at"], "surfaced_findings",
               f"promoted: {row.get('finding_id', '?')} — "
               f"{row.get('title', '?')}")
        for row in _read_jsonl(path) if row.get("promoted_at")
    ]


def _alert_event(path) -> list[dict]:
    try:
        alert = json.loads(_read_text(path) or "")
    except json.JSONDecodeError:
        return []
    if not isinstance(alert, dict) or not alert.get("updated_at"):
        return []
    reasons = [r for r in (alert.get("reasons") or []) if isinstance(r, str)]
    msg = f"loop alert: {alert.get('level', '?')}"
    return [_event(alert["updated_at"], "loop_alert",
                   msg + (" — " + "; ".join(reasons) if reasons else ""))]


def timeline(*, transcript_path=None, cycles_path=None, idea_ledger_path=None,
             surfaced_path=None, loop_alert_path=None,
             since: str | None = None, limit: int | None = None) -> list[dict]:
    """Deterministic merged view: same ledgers -> same timeline, every read.
    Derived events (kind "event") are re-derived each call, never written.
    `since` keeps ts >= since (ISO UTC); `limit` keeps the NEWEST N."""
    rows: list[dict] = [
        {**row, "ts": _norm_ts(row["ts"])}
        for row in _read_jsonl(_or(transcript_path, DEFAULT_TRANSCRIPT))
        if row.get("ts") and row.get("kind")
    ]
    rows += _cycle_events(_or(cycles_path, DEFAULT_CYCLES))
    rows += _idea_events(_or(idea_ledger_path, DEFAULT_IDEA_LEDGER))
    rows += _promotion_events(_or(surfaced_path, DEFAULT_SURFACED))
    rows += _alert_event(_or(loop_alert_path, DEFAULT_LOOP_ALERT))
    rows.sort(key=lambda e: (e["ts"], e.get("kind", ""), e.get("message", "")))
    if since:
        lo = _norm_ts(since)
        rows = [e for e in rows if e["ts"] >= lo]
    if limit is not None:
        rows = rows[-max(int(limit), 0):] if int(limit) > 0 else []
    return rows


# ── turn: one conversational exchange with a role voice ──────────────────────

def _author_header(author: str) -> str:
    """How the voices are told WHO is speaking. The steward gets named so
    a reply can be addressed to it — capability is unchanged."""
    if author == "oracle":
        return ("MESSAGE FROM ORACLE (ratified mission steward, "
                "2026-08-16 — observer of this apparatus; it proposes "
                "through the blessed seams and never edits the system. "
                "Answer it with the same seam honesty you owe the "
                "owner, and address it by name):")
    return "HUMAN MESSAGE:"


def _context_pack(*, ideas_md_path, cycles_path, loop_alert_path,
                  transcript_path) -> tuple[str, str]:
    """(pack_text, digest). Every part fails OPEN with an honest
    "[unavailable: X]" marker — a missing ledger is stated, never papered
    over, so the voices cannot cite context that was not there."""
    sections: list[str] = []
    marks: list[str] = []

    def add(name: str, text: str | None) -> None:
        ok = bool(text and text.strip())
        sections.append(f"## {name}\n"
                        + (text.strip() if ok else f"[unavailable: {name}]"))
        marks.append(f"{name}={'ok' if ok else 'unavailable'}")

    ideas = _read_text(ideas_md_path)
    add("ideas.md", ideas[:6000] if ideas else None)
    cycles = _read_jsonl(cycles_path)
    add("coordinator_cycle", json.dumps(
        {k: cycles[-1].get(k) for k in
         ("timestamp", "topic", "status", "plan", "planner_state")},
        ensure_ascii=False) if cycles else None)
    add("loop_alert", _read_text(loop_alert_path))
    tail = _read_jsonl(transcript_path)[-TRANSCRIPT_TAIL_ROWS:]
    add("transcript_tail", "\n".join(
        f"{r.get('kind', '?')}: {r.get('message', '')}" for r in tail) or None)
    marks[-1] = f"tail={len(tail)}"
    return "\n\n".join(sections), ";".join(marks)


def turn(*, role: str, message: str, author: str = "human",
         transcript_path=None, cycles_path=None,
         loop_alert_path=None, ideas_md_path=None, model: str | None = None,
         parent_request_id: str | None = None) -> dict[str, Any]:
    """One channel turn: context pack -> role-voiced reply -> append the
    AUTHOR row THEN the reply row. `author` is who is addressing the lab
    ("human" the owner, "oracle" the ratified mission steward) — it is stored
    as the row kind so the exchange is attributable; it grants no capability.
    Refuses an empty message (raises; a blank turn is never a silent noop).
    MOCK_LLM -> deterministic stub, no call."""
    if role not in _ROLES:
        raise ValueError(f"role must be one of {_ROLES}, got {role!r}")
    if author not in _PARTICIPANTS:
        raise ValueError(
            f"author must be one of {_PARTICIPANTS}, got {author!r}")
    if not isinstance(message, str) or not message.strip():
        raise ValueError("message must be non-empty — refusing a blank turn")
    message = message.strip()
    transcript = _or(transcript_path, DEFAULT_TRANSCRIPT)
    t0 = time.perf_counter()
    pack, digest = _context_pack(
        ideas_md_path=_or(ideas_md_path, DEFAULT_IDEAS_MD),
        cycles_path=_or(cycles_path, DEFAULT_CYCLES),
        loop_alert_path=_or(loop_alert_path, DEFAULT_LOOP_ALERT),
        transcript_path=transcript)

    if os.environ.get("MOCK_LLM"):
        # Deterministic stub: same message + same context -> same reply.
        reply = (f"[MOCK_LLM stub · {role}] context: {digest} · "
                 f"message head: {message[:80]}")
        rid = None
    else:
        record = call_sync(
            [{"role": "system",
              "content": NARA_SYSTEM_PROMPT if role == "nara"
              else PI_SYSTEM_PROMPT},
             {"role": "user",
              "content": (f"CONTEXT PACK (the only ground truth you may "
                          f"cite):\n\n{pack}\n\n"
                          f"{_author_header(author)}\n{message}")}],
            temperature=0.4, top_p=0.9, max_tokens=700,
            caller_tag=f"lab_channel:{role}",
            parent_request_id=parent_request_id,
            log_path=CALLS_LOG_PATH, model=model)
        reply = (record.get("completion") or "").strip() or "[empty completion]"
        rid = record.get("request_id")

    _append_jsonl(transcript,
                  {"ts": _utcnow_iso(), "kind": author, "message": message})
    reply_row: dict[str, Any] = {"ts": _utcnow_iso(), "kind": role,
                                 "message": reply, "context_digest": digest}
    if rid is not None:
        reply_row["wrapper_request_id"] = rid
    _append_jsonl(transcript, reply_row)
    _log(f"lab_channel:turn:{role}",
         f"reply {len(reply)} chars (context {digest})",
         "one human row + one reply row appended", t0)
    return {"status": "passed", "role": role, "reply": reply,
            "context_digest": digest, "wrapper_request_id": rid}


# ── delegate: the human's blessed hand-off seam (no LLM) ─────────────────────

def delegate(*, kind: str, text: str, cluster_id: str | None = None,
             objective: str | None = None, transcript_path=None,
             idea_ledger_path=None, fix_queue_path=None) -> dict[str, Any]:
    """research -> agenda_item_added (source "human") on the named cluster,
    or on STANDING_CLUSTER auto-created (origin "manual") when absent; a
    NAMED cluster that does not exist raises — appending would corrupt the
    reducer (rule 4). improvement -> a full-contract enqueue row that
    consume_authorize_fix_queue accepts. Both mirror a "DELEGATED[...]"
    human row into the transcript."""
    if kind not in ("research", "improvement"):
        raise ValueError(f"kind must be research|improvement, got {kind!r}")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text must be non-empty — refusing a blank delegation")
    text = text.strip()
    transcript = _or(transcript_path, DEFAULT_TRANSCRIPT)
    t0 = time.perf_counter()
    written: list[dict] = []

    if kind == "research":
        from workers import idea_ledger
        ledger = _or(idea_ledger_path, DEFAULT_IDEA_LEDGER)
        state = idea_ledger.load_state(ledger)
        target = cluster_id or STANDING_CLUSTER
        if target not in state:
            if cluster_id is not None:
                raise ValueError(
                    f"cluster {cluster_id!r} not found in the idea ledger — "
                    "refusing an agenda item the reducer would reject")
            create = {"event_type": "cluster_created", "ts": _utcnow_iso(),
                      "cluster_id": STANDING_CLUSTER, "origin": "manual",
                      "member_id": "human:delegation"}
            idea_ledger.append_event(ledger, create)
            written.append(create)
        event = {"event_type": "agenda_item_added", "ts": _utcnow_iso(),
                 "cluster_id": target, "topic": text, "source": "human"}
        idea_ledger.append_event(ledger, event)
        written.append(event)
    else:
        # Full spawn-contract block, reusing the outcome-4 writer-of-record's
        # scaffold constants so the queue keeps ONE shape (D-046/D-062 seam).
        row = {"ref_id": f"lab-{uuid.uuid4().hex[:8]}",
               "outcome": "authorize_fix", "status": "enqueued",
               "note": text, "authorized_by": "human:lab_channel",
               "authorized_at": _utcnow_iso(),
               "contract": {
                   "task_statement": (objective or text).strip(),
                   "state_basis": "HEAD@dispatch",
                   "done_condition": _af.DEFAULT_DONE_CONDITION,
                   "skill_subset": list(_af.DEFAULT_SKILL_SUBSET),
                   "budget": dict(_af.DEFAULT_BUDGET),
                   "authority_cap": _af.DEFAULT_AUTHORITY_CAP,
                   "self_gating_rules": _af.DEFAULT_SELF_GATING,
                   "reporting_format": _af.DEFAULT_REPORTING,
                   "escalation_path": _af.DEFAULT_ESCALATION,
               }}
        _append_jsonl(_or(fix_queue_path, DEFAULT_FIX_QUEUE), row)
        written.append(row)

    mirror = {"ts": _utcnow_iso(), "kind": "human",
              "message": f"DELEGATED[{kind}]: {text}"}
    _append_jsonl(transcript, mirror)
    _log(f"lab_channel:delegate:{kind}",
         f"{len(written)} row(s) + transcript mirror",
         "delegation recorded append-only", t0)
    return {"status": "passed", "kind": kind, "rows": written,
            "mirror": mirror}


# ── CLI ──────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="lab_channel",
        description="Lab Channel: the human ⇄ Nara ⇄ PI conversation seam.")
    sub = p.add_subparsers(dest="cmd", required=True)
    p_tl = sub.add_parser("timeline", help="merged transcript + apparatus events")
    p_tl.add_argument("--since", default=None, help="ISO UTC lower bound")
    p_tl.add_argument("--limit", type=int, default=None, help="newest N events")
    p_turn = sub.add_parser("turn", help="one conversational turn")
    p_turn.add_argument("--role", required=True, choices=list(_ROLES))
    p_turn.add_argument("--message", required=True)
    p_turn.add_argument("--as", dest="author", default="human",
                        choices=list(_PARTICIPANTS),
                        help="who is addressing the lab (default: human)")
    p_del = sub.add_parser("delegate", help="hand work to the apparatus")
    p_del.add_argument("--kind", required=True,
                       choices=["research", "improvement"])
    p_del.add_argument("--text", required=True)
    p_del.add_argument("--cluster-id", default=None)
    p_del.add_argument("--objective", default=None)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "timeline":
            for e in timeline(since=args.since, limit=args.limit):
                print(f"{e['ts']}  [{e.get('kind', '?')}]  {e.get('message', '')}")
        elif args.cmd == "turn":
            print(turn(role=args.role, message=args.message,
                       author=args.author)["reply"])
        else:
            print(json.dumps(
                delegate(kind=args.kind, text=args.text,
                         cluster_id=args.cluster_id,
                         objective=args.objective),
                ensure_ascii=False, indent=2))
    except ValueError as exc:
        print(f"rejected: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
