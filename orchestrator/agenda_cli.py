"""The HUMAN acceptance step for frontier agenda proposals (GAP 1).

``orchestrator/frontier_agenda.py`` appends vendor proposals to
``memory/frontier_agenda.jsonl`` at ``status: "proposed"`` and stops there —
the ANNOTATE-ONLY firewall (D-061) forbids it from writing the idea ledger.
``schema/idea_ledger.schema.json`` names the missing half in the
``agenda_item_added.source`` comment: *"frontier items land status: proposed
upstream; only accepted ones reach this ledger."* Nothing performed that
acceptance, so 10 proposals sat inert and the coordinator (which consumes
ledger agenda items first — ``orchestrator/coordinator.py`` agenda-first)
never saw one. This CLI is that step, and it is the ONLY writer of it.

Two frozen verbs, gate_cli's idiom throughout (argv array, no shell,
validate-then-append, out-of-enum input REJECTED with a nonzero exit and
NOTHING written — inviolate rule 4):

    accept  --proposal-id <id> [--topic-override <text>] --note <why>
    dismiss --proposal-id <id> --note <why>

``accept`` writes TWO places:

1. the idea ledger (``workers.idea_ledger.append_event``, schema-validated) —
   an ``agenda_item_added`` with ``source: "frontier_proposed"`` on the
   proposal's ``cluster_id`` when it carries one, else on a fresh
   ``cl-<proposal_id>`` cluster. A fresh cluster is OPENED first with a
   ``cluster_created`` (origin ``manual``, member ``<proposal_id>``): the
   reducer RAISES on an agenda item for an unknown cluster, so appending the
   item alone would corrupt the ledger for every reader — the same rule
   ``lab_channel.delegate`` honors. A proposal naming a cluster that does NOT
   exist is refused rather than auto-created (a named target is a claim about
   the ledger, never a coercion), and a cluster that IS KILLED is refused too
   (the reopen gate below).
2. ``memory/frontier_agenda.status.jsonl`` — a status-audit row. The
   proposals file is NEVER edited in place; effective status is the LAST
   audit row for a proposal (the append-only, last-row-wins convention
   ``frontier_agenda.load_agenda`` and ``loop_feedback`` already use).

``dismiss`` writes the audit row ONLY — a dismissal must never touch the
ledger.

THE REOPEN GATE (defense in depth, layer 1). A KILLED cluster is a graveyard
direction, and ``workers/idea_ledger.py`` guards its only way back: a
``cluster_reopened`` event whose ``evidence.evidence_kind`` MATCHES the
``reopening_condition.evidence_kind`` recorded at kill time (the reducer
RAISES on a mismatch — evidence-keyed reopening is never coerced, rule 4).
An ``agenda_item_added`` carries no evidence and does not clear
``kill_reason``, so accepting a proposal onto a killed cluster would put the
dead direction back at the HEAD of the coordinator's topic list
(``orchestrator/coordinator.py`` agenda-first) with NO reopen event —
sidestepping the one mechanism built to prevent exactly that. So ``accept``
REFUSES a killed cluster and names the legitimate route in its message.
Layer 2 lives in ``workers/idea_projection.agenda_topics``, which drops the
agenda of a killed cluster: layer 1 cannot cover an item accepted while the
cluster was OPEN and killed afterwards.

Both verbs REFUSE (nonzero, nothing written) on: an unknown proposal id, a
blank note (the note is the audit value), a blank topic, a proposal already
effectively ``accepted`` (a second accept would enqueue a duplicate agenda
item the coordinator would run twice), a cluster that is killed, and any
ledger event that fails schema validation — every event is validated BEFORE
the first byte is written.

The accept path's read-check-append sequence runs under an exclusive
``fcntl.flock`` on a sidecar lock file (the discipline ``orchestrator/
nara_daemon.py`` already uses): without it two concurrent accepts both read
``proposed``, both pass the duplicate guard, and both append — the duplicate
the guard exists to stop.
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import jsonschema

from orchestrator.frontier_agenda import DEFAULT_AGENDA, load_agenda
from workers.idea_ledger import (
    DEFAULT_LEDGER,
    append_event,
    load_state,
    validate_event,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATUS = REPO_ROOT / "memory" / "frontier_agenda.status.jsonl"

# Frozen verbs / frozen statuses — mirrors of nothing wider (rule 4).
VERBS = ("accept", "dismiss")
STATUSES = ("accepted", "dismissed")

# The schema's provenance value for a human-accepted frontier proposal.
AGENDA_SOURCE = "frontier_proposed"
# Origin of a cluster opened to carry an accepted proposal (schema enum).
CLUSTER_ORIGIN = "manual"

DEFAULT_AGENT = "human:cli"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_status(path: str | Path = DEFAULT_STATUS) -> dict[str, dict]:
    """Reduce the append-only audit file to {proposal_id: latest row}
    (last-row-wins). Missing file -> {} (no proposal has been ruled on yet)."""
    p = Path(path)
    if not p.exists():
        return {}
    out: dict[str, dict] = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        pid = row.get("proposal_id")
        if isinstance(pid, str) and row.get("status") in STATUSES:
            out[pid] = row
    return out


def effective_status(proposal: dict, audit_row: dict | None) -> str:
    """The status a reader should believe: the last audit row's, else the
    proposal row's own (``proposed`` for an unruled proposal)."""
    if isinstance(audit_row, dict) and audit_row.get("status") in STATUSES:
        return audit_row["status"]
    status = proposal.get("status") if isinstance(proposal, dict) else None
    return status if isinstance(status, str) and status else "proposed"


def cluster_id_for(proposal: dict) -> str:
    """The proposal's own cluster_id when it carries one, else a fresh id
    derived from the proposal id (deterministic, traceable back to the
    proposal — ``consolidate_memory``'s ``cl-<id>`` idiom)."""
    cid = proposal.get("cluster_id")
    if isinstance(cid, str) and cid.strip():
        return cid.strip()
    return f"cl-{proposal['proposal_id']}"


def _require(value, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{what} is required (non-empty) — refusing to write")
    return value.strip()


def _audit_row(proposal_id: str, status: str, note: str, agent_id: str,
               **extra) -> dict:
    row = {
        "proposal_id": proposal_id,
        "status": status,
        "ts": _utcnow_iso(),
        "note": note,
        "agent_id": agent_id,
    }
    row.update({k: v for k, v in extra.items() if v is not None})
    return row


def _append_audit(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


@contextlib.contextmanager
def _accept_lock(status_path: Path):
    """Serialize accept's read-check-append across processes — the same
    ``fcntl.flock`` discipline ``nara_daemon._run_pass`` uses for the cron
    lock, on a sidecar next to the audit file. BLOCKING (not LOCK_NB): a
    concurrent accept must WAIT and then re-read, so the second one sees the
    first's audit row and refuses as a duplicate. ``dismiss`` does not take
    it — it has no check-then-act (it reads no status)."""
    lock = status_path.parent / f".{status_path.name}.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, "a+", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _proposal(proposal_id: str, agenda_path) -> dict:
    proposals = load_agenda(agenda_path)
    row = proposals.get(proposal_id)
    if row is None:
        raise ValueError(
            f"no proposal {proposal_id!r} in {agenda_path} — refusing to rule "
            f"on a proposal that does not exist")
    return row


def accept(proposal_id: str, note: str, *, topic_override: str | None = None,
           agent_id: str = DEFAULT_AGENT,
           agenda_path=DEFAULT_AGENDA, status_path=DEFAULT_STATUS,
           ledger_path=DEFAULT_LEDGER) -> dict:
    """Accept one proposal onto the idea-ledger agenda + write its audit row.

    Returns the envelope ``{proposal_id, status, cluster_id, topic,
    ledger_events, audit_row}``. Raises ValueError / jsonschema.ValidationError
    with NOTHING written on any refusal."""
    proposal_id = _require(proposal_id, "proposal-id")
    note = _require(note, "note")
    proposal = _proposal(proposal_id, agenda_path)

    # Everything from the duplicate check to the last append is one critical
    # section: the guard below is a check-then-act, and two concurrent accepts
    # would otherwise both read "proposed" and both append.
    with _accept_lock(Path(status_path)):
        current = effective_status(proposal,
                                   load_status(status_path).get(proposal_id))
        if current == "accepted":
            raise ValueError(
                f"proposal {proposal_id!r} is already accepted — refusing a "
                f"second agenda item (the coordinator would run the topic twice)")

        topic = _require(topic_override if topic_override is not None
                         else proposal.get("topic"), "topic")

        state = load_state(ledger_path)  # a broken ledger RAISES, before writes
        named = proposal.get("cluster_id")
        cluster_id = cluster_id_for(proposal)
        if isinstance(named, str) and named.strip() and cluster_id not in state:
            raise ValueError(
                f"proposal {proposal_id!r} names cluster {cluster_id!r}, which "
                f"is not in {ledger_path} — refusing an agenda item the reducer "
                f"would reject")

        # THE REOPEN GATE (layer 1). A killed cluster re-enters the loop ONLY
        # through a cluster_reopened event carrying the evidence_kind recorded
        # at kill time; an agenda item carries no evidence and clears no kill,
        # so accepting one here would resurrect the direction silently.
        existing = state.get(cluster_id)
        if isinstance(existing, dict) and existing.get("status") == "killed":
            cond = existing.get("reopening_condition") or {}
            kind = cond.get("evidence_kind")
            code = (existing.get("kill_reason") or {}).get("code")
            raise ValueError(
                f"proposal {proposal_id!r} names cluster {cluster_id!r}, which "
                f"is KILLED (kill_reason.code={code!r}) — refusing to put a "
                f"graveyard direction back on the agenda. An agenda item is "
                f"not evidence and does not reopen anything. The only route "
                f"back is a cluster_reopened event on {cluster_id!r} carrying "
                f"evidence.evidence_kind={kind!r} (the reopening_condition "
                f"recorded at kill time); accept the proposal after that "
                f"reopen lands, not instead of it")

        events: list[dict] = []
        if cluster_id not in state:
            events.append({"event_type": "cluster_created", "ts": _utcnow_iso(),
                           "cluster_id": cluster_id, "origin": CLUSTER_ORIGIN,
                           "member_id": proposal_id})
        events.append({"event_type": "agenda_item_added", "ts": _utcnow_iso(),
                       "cluster_id": cluster_id, "topic": topic,
                       "source": AGENDA_SOURCE})
        for event in events:  # validate ALL before writing ANY (rule 4)
            validate_event(event)

        # Ledger FIRST, audit second. The two appends are not atomic across
        # files; this order fails toward a LOUD duplicate (an agenda item whose
        # proposal still reads unruled, which a second accept would double) over
        # a SILENT loss (a proposal marked accepted whose topic never reached the
        # ledger). Both writes are single-line appends to memory/ — the gap is a
        # disk-level failure, not a race.
        for event in events:
            append_event(ledger_path, event)
        row = _audit_row(proposal_id, "accepted", note, agent_id,
                         cluster_id=cluster_id, topic=topic)
        _append_audit(Path(status_path), row)
    return {"proposal_id": proposal_id, "status": "accepted",
            "cluster_id": cluster_id, "topic": topic,
            "ledger_events": events, "audit_row": row}


def dismiss(proposal_id: str, note: str, *, agent_id: str = DEFAULT_AGENT,
            agenda_path=DEFAULT_AGENDA, status_path=DEFAULT_STATUS) -> dict:
    """Dismiss one proposal: the audit row ONLY — the idea ledger is not
    touched. Raises ValueError with nothing written on an unknown id / blank
    note."""
    proposal_id = _require(proposal_id, "proposal-id")
    note = _require(note, "note")
    _proposal(proposal_id, agenda_path)
    row = _audit_row(proposal_id, "dismissed", note, agent_id)
    _append_audit(Path(status_path), row)
    return {"proposal_id": proposal_id, "status": "dismissed",
            "ledger_events": [], "audit_row": row}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Human acceptance step for frontier agenda proposals.")
    # Shared flags live on the SUBPARSERS (the blessed-exec idiom is
    # `<verb> --flag value …`, cf. todo_cockpit's argv arrays), so a caller
    # never has to interleave globals before the verb.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--proposal-id", required=True)
    common.add_argument("--note", required=True)
    common.add_argument("--by", default=DEFAULT_AGENT,
                        help="agent_id stamped on the audit row.")
    common.add_argument("--agenda", default=str(DEFAULT_AGENDA))
    common.add_argument("--status", default=str(DEFAULT_STATUS))
    common.add_argument("--ledger", default=str(DEFAULT_LEDGER))
    subs = p.add_subparsers(dest="verb", required=True)
    for verb in VERBS:  # frozen: argparse rejects anything else (exit 2)
        sub = subs.add_parser(verb, parents=[common])
        if verb == "accept":
            sub.add_argument("--topic-override", default=None)
    args = p.parse_args(argv)

    try:
        if args.verb == "accept":
            out = accept(args.proposal_id, args.note,
                         topic_override=args.topic_override,
                         agent_id=args.by, agenda_path=args.agenda,
                         status_path=args.status, ledger_path=args.ledger)
        else:
            out = dismiss(args.proposal_id, args.note, agent_id=args.by,
                          agenda_path=args.agenda, status_path=args.status)
    except (ValueError, jsonschema.ValidationError, OSError) as exc:
        message = getattr(exc, "message", None) or str(exc)
        print(f"rejected: {message}", file=sys.stderr)
        return 1
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
