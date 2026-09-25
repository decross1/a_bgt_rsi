"""Live read model for the Now page's "Today's research path" panel.

Every section is derived from a live producer, read-only, on each refresh:

* plan of record: the newest ``run_state/daily_plans/<date>[-rN].json``
  (highest date, then highest N) and the meta-oracle ``review`` replying to the
  ``PLAN READY`` note whose ``ref.path`` names that file;
* research focus: ``orchestrator.research_focus.project_focus``;
* work items and "waiting on you": the Oracle<->Nara mailbox
  (``orchestrator.oracle_mailbox.read``/``fold``) plus read-only git;
* accomplishments and improvements: the same sources over the last 7 days.

Nothing here writes, and a quiet producer shows its age rather than old content.
Match rules (each is tested):

* ``nara_dev`` item -> the newest ``plan_item`` Oracle posted inside the plan's
  revision window whose title equals the item title, or names this item's id as
  a whole word and no other id of the same plan.  A current plan's window is
  anchored to the exact ``PLAN READY`` receipt whose ``ref.path`` and
  ``ref.sha256`` identify that immutable plan.  Older receipts without those
  references retain a fallback only when one receipt maps to one plan revision.
* ``oracle_dev`` item -> Oracle's newest in-window ``READY FOR REVIEW`` note
  naming ``oracle/<date>-<id>`` (optionally ``-rN``).  Only an authorized review
  replying to that exact note decides the verdict.  Current Git ancestry,
  branch refs, commit timestamps and model-authored ``main_before`` fields do
  not prove when a merge happened, so this view never upgrades an Oracle item
  to "merged" without a separately trusted append-only integration receipt.
* ``owner_decision`` item -> actionable only when a real ``question`` to the
  owner inside the window names the item id (``ref.item`` or a whole-word title
  match). Mailbox actor labels, including an original asker's label, are
  unauthenticated evidence and cannot close it.  Resolution rows are retained
  as contextual claims until a separately authenticated attestation exists.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .daily_ops import _read_regular, _unique_object
from .card_presentation_policy import historical_archive, interactive_claude_handoff

LIVE_SCHEMA = "daily-ops-summary/v3"
LAB_TZ = ZoneInfo("America/Los_Angeles")  # the daily loop's day (META_ORACLE_DAILY_LOOP §2)
WINDOW_DAYS = 7
MAX_PLAN_BYTES = 262_144
MAX_WORK_ITEMS = 12
MAX_ROWS = 16
MAX_IMPROVEMENTS = 40
CODE_ROOT = Path(__file__).resolve().parents[2]  # the checkout that ships this UI code
MAILBOX_ROW_FIELDS = {
    "schema", "seq", "ts", "actor", "to", "kind", "in_reply_to", "body",
    "expires_at", "prev_sha256", "msg_id", "row_sha256",
}
PLAN_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:-r(\d+))?\.json$")
PLAN_READY = re.compile(r"^PLAN READY:\s*(\d{4}-\d{2}-\d{2})")
GOAL = re.compile(r"\bG\d+(?:\.\d+)?\b")
CLI = ".venv-chroma/bin/python -m orchestrator.oracle_mailbox post --as human:derrick"
WORK_STATUSES = {
    "not_started", "awaiting_review", "held", "building", "validated", "failed",
    "withdrawn", "expired", "amend_requested", "accepted", "rejected", "merged",
    "waiting_on_you", "answered", "resolved",
}
FOLD_STATUS = {"open": "awaiting_review", "held": "held", "claimed": "building",
               "validated": "validated", "failed": "failed", "withdrawn": "withdrawn",
               "expired": "expired"}
VERDICT_STATUS = {"accept": "accepted", "amend": "amend_requested", "reject": "rejected"}
QUESTION_RESOLUTIONS = {"withdrawn", "superseded", "prerequisite", "informational"}
QUESTION_UPDATE_DISPOSITIONS = {*QUESTION_RESOLUTIONS, "contested", "presentation_archived_claim"}
AGENT_STATUSES = {
    "online", "active", "working", "idle", "waiting", "degraded", "stale", "failed", "offline",
    "unknown",
}
_git_lock = threading.Lock()
_git_cache: dict = {}


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _when(value: object) -> datetime | None:
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _stamp(value: object) -> str | None:
    parsed = _when(value)
    return _iso(parsed) if parsed else None


def _clip(value: object, maximum: int = 240) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join("".join(c if ord(c) >= 32 else " " for c in value).split())
    if not text:
        return None
    return text if len(text) <= maximum else text[:maximum - 1].rstrip() + "…"


def _first_clip(*values: object, maximum: int) -> str | None:
    """Return the first usable bounded display value, not merely the first truthy value."""
    for value in values:
        clipped = _clip(value, maximum)
        if clipped is not None:
            return clipped
    return None


def _body(row: dict) -> dict:
    return row["body"] if isinstance(row.get("body"), dict) else {}


def _ref(row: dict) -> dict:
    ref = _body(row).get("ref")
    return ref if isinstance(ref, dict) else {}


def _title(row: dict) -> str:
    body = _body(row)
    return str(body.get("title") or body.get("question") or "")


def _human_answer(question: dict, rows: list[dict]) -> dict | None:
    """Never promote a self-asserted ``human:*`` answer into a closure.

    Actor labels are useful evidence but the mailbox has no strong human
    authentication.  Such rows are surfaced separately as contested context.
    """
    return None


def _unverified_human_claim(question: dict, rows: list[dict]) -> dict | None:
    """Newest direct human answer/disposition claim, for non-terminal context."""
    claims = _unverified_human_claims(question, rows)
    return claims[-1] if claims else None


def _unverified_human_claims(question: dict, rows: list[dict], *, after: dict | None = None) -> list[dict]:
    """Ordered direct human claims, optionally only after an update row."""
    question_id = question.get("msg_id") if isinstance(question, dict) else None
    question_positions = [position for position, row in enumerate(rows)
                          if row.get("msg_id") == question_id]
    if (not isinstance(question_id, str) or len(question_positions) != 1
            or rows[question_positions[0]] is not question):
        return []
    question_position = question_positions[0]
    if after is not None:
        later = [position for position, row in enumerate(rows) if row is after]
        if len(later) != 1:
            return []
        question_position = max(question_position, later[0])
    claims = []
    for position, row in enumerate(rows):
        if (position <= question_position or row.get("kind") not in {"answer", "question_resolution"}
                or row.get("in_reply_to") != question_id
                or not isinstance(row.get("actor"), str) or not row["actor"].startswith("human:")):
            continue
        # A duplicated terminal identity is ambiguous even if one copy has the
        # desired actor label. Projection input normally removes it earlier;
        # this guard keeps direct helper callers fail closed too.
        if sum(candidate.get("msg_id") == row.get("msg_id") for candidate in rows) == 1:
            claims.append(row)
    return claims


def _owner_reconciliation_request(question: dict, rows: list[dict]) -> dict | None:
    """Newest protected-route reconciliation request; it remains non-terminal."""
    requests = _owner_reconciliation_requests(question, rows)
    return requests[-1] if requests else None


def _owner_reconciliation_requests(question: dict, rows: list[dict], *, after: dict | None = None) -> list[dict]:
    """Ordered protected-route context rows, without treating them as proof."""
    question_id = question.get("msg_id") if isinstance(question, dict) else None
    if not isinstance(question_id, str):
        return []
    start = -1
    if after is not None:
        later = [position for position, row in enumerate(rows) if row is after]
        if len(later) != 1:
            return []
        start = later[0]
    found = []
    for position, row in enumerate(rows):
        body = _body(row)
        if (position > start and row.get("kind") == "note" and row.get("in_reply_to") == question_id
                and body.get("via") == "authorized-owner-ui"
                and body.get("reconciliation") == "genuine_owner_confirmation_required"):
            found.append(row)
    return found


def _question_resolution(question: dict, rows: list[dict]) -> dict | None:
    """Return a terminal disposition only when authentication supports one.

    The current mailbox has no authenticated signer.  A generic CLI caller can
    write ``--as claude`` or any other allowed actor label, so no resolution
    claim is terminal in this projection.
    """
    return None


def _historical_presentation_archive(question: dict, rows: list[dict]) -> dict | None:
    """Exact legacy presentation exception, invalidated by later owner context.

    The exception is deliberately narrower than a mailbox closure.  A later
    human-labelled answer or protected owner-route reconciliation is still not
    authenticated, but it is current evidence which must be visible rather
    than hidden behind an older presentation archive.
    """
    candidate = historical_archive(question, rows)
    if candidate is None:
        return None
    oracle_mailbox, _ = _orchestrator()
    # This remains presentation only.  The validation adds the important
    # fail-open condition: evidence that is later provenance-contested cannot
    # hide an owner card, even when its older bytes are on the allowlist.
    if not oracle_mailbox.is_valid_question_resolution(question, candidate, rows):
        return None
    if _unverified_human_claims(question, rows, after=candidate):
        return None
    if _owner_reconciliation_requests(question, rows, after=candidate):
        return None
    return candidate


def _unverified_resolution_claims(question: dict, rows: list[dict], *, after: dict | None = None) -> list[dict]:
    """Ordered same-thread resolution claims retained as non-terminal context."""
    oracle_mailbox, _ = _orchestrator()
    question_id = question.get("msg_id") if isinstance(question, dict) else None
    question_positions = [position for position, row in enumerate(rows)
                          if row.get("msg_id") == question_id]
    if (not isinstance(question_id, str) or len(question_positions) != 1
            or rows[question_positions[0]] is not question):
        return None
    start = question_positions[0]
    if after is not None:
        later = [position for position, row in enumerate(rows) if row is after]
        if len(later) != 1:
            return []
        start = max(start, later[0])
    return [
        row for position, row in enumerate(rows)
        if position > start
        and row.get("kind") == "question_resolution"
        and row.get("in_reply_to") == question_id
        and sum(candidate.get("msg_id") == row.get("msg_id") for candidate in rows) == 1
        and oracle_mailbox._valid_question_resolution_record(question, row, rows)
    ]


def _unverified_question_claims(question: dict, rows: list[dict], *, after: dict | None = None) -> list[dict]:
    """All readable but unauthenticated terminal-looking claims in row order."""
    claims = _unverified_human_claims(question, rows, after=after)
    claims.extend(_unverified_resolution_claims(question, rows, after=after))
    positions = {id(row): position for position, row in enumerate(rows)}
    return sorted(claims, key=lambda row: positions[id(row)])


def _question_contest(question: dict, rows: list[dict]) -> dict | None:
    """Newest evidence-bound contest when no later valid terminal replaces it."""
    oracle_mailbox, _ = _orchestrator()
    return oracle_mailbox.latest_question_contest(question, rows)


def _question_choice(value: object) -> str | None:
    if isinstance(value, str):
        return _clip(value, 300)
    if not isinstance(value, dict):
        return None
    label = _clip(value.get("label"), 180)
    ident = _clip(value.get("id"), 60)
    if label is None or ident is None:
        return None
    effect = _clip(value.get("effect"), 180)
    return _clip(f"{label} [{ident}]" + (f" — {effect}" if effect else ""), 300)


def _question_card(row: dict) -> dict:
    """Bounded, typed display fields for a genuine owner question."""
    body = _body(row)
    title_from_body = _clip(body.get("title"), 300)
    title = _first_clip(body.get("title"), body.get("question"), body.get("text"), maximum=300) or row["msg_id"]
    question = title
    full_question = _clip(body.get("question"), 1200)
    short_question = _clip(body.get("question"), 300)
    context = _first_clip(body.get("context"), body.get("decision_context"), body.get("why"), maximum=1200)
    if context is not None and title_from_body is not None and short_question is not None and short_question != title:
        question = short_question
    if context is None and full_question is not None and (
            (title_from_body is not None and short_question != title)
            or (title_from_body is None and full_question != short_question)):
        context = full_question
    if context is None:
        text = _clip(body.get("text"), 1200)
        if text is not None and text != title:
            context = text
    choices = body.get("options")
    if not isinstance(choices, list):
        choices = []
    return {
        "title": title,
        "question": question,
        "context": context,
        "choices": [projected for choice in choices[:8] if (projected := _question_choice(choice))],
        "recommendation": _clip(body.get("recommendation"), 600),
        "consequence": _clip(body.get("consequence") or body.get("impact") or body.get("if_deferred")
                             or body.get("consequence_of_deferring"), 600),
    }


def _all_question_updates(rows: list[dict]) -> list[dict]:
    """Recent explicit non-answer dispositions, kept separate from actions."""
    rows = _relational_live_rows(rows)
    found = []

    def add(question: dict, card: dict, update: dict) -> None:
        found.append({**update, "question_id": question["msg_id"],
                      "title": card["title"], "question": card["question"]})

    for question in rows:
        if question.get("kind") != "question" or question.get("to") != "owner":
            continue
        archived = _historical_presentation_archive(question, rows)
        if archived is not None:
            body = _body(archived)
            card = _question_card(question)
            add(question, card, {
                "id": archived["msg_id"], "disposition": "presentation_archived_claim",
                "summary": (_clip(body.get("summary"), 1200)
                            or "Exact historical evidence is shown as an archived claim."),
                "reason": ("This is a source-controlled, exact-row-hash presentation exception; "
                           "it is not a mailbox closure or a precedent for future questions."),
                "blocking_artifact": _clip(body.get("blocking_artifact"), 240),
                "resolved_by": _clip(str(archived.get("actor")), 60) or "?",
                "resolved_at": _stamp(archived.get("ts")),
                "evidence_msg_ids": [question["msg_id"], archived["msg_id"]],
            })
            continue
        resolution = _question_resolution(question, rows)
        contest = None if resolution is not None else _question_contest(question, rows)
        claim = None if resolution is not None or contest is not None else (
            _unverified_question_claims(question, rows) or [None])[-1]
        reconciliation = (None if resolution is not None or contest is not None or claim is not None
                          else _owner_reconciliation_request(question, rows))
        if resolution is None and contest is None and claim is None and reconciliation is None:
            continue
        card = _question_card(question)
        if resolution is not None:
            body = _body(resolution)
            add(question, card, {
                "id": resolution["msg_id"], "disposition": body["disposition"],
                "summary": _clip(body.get("summary"), 1200), "reason": _clip(body.get("reason"), 1200),
                "blocking_artifact": _clip(body.get("blocking_artifact"), 240),
                "resolved_by": _clip(str(resolution.get("actor")), 60) or "?",
                "resolved_at": _stamp(resolution.get("ts")),
                "evidence_msg_ids": [value for value in body.get("evidence_msg_ids", [])
                                     if isinstance(value, str)][:8],
            })
        elif contest is not None:
            body = _body(contest)
            provenance = body["provenance_contestation"]
            add(question, card, {
                "id": contest["msg_id"], "disposition": "contested",
                "summary": _clip(body.get("title"), 1200)
                or "A later evidence-bound provenance contest reopened this question.",
                "reason": _clip(body.get("text"), 1200)
                or "The contested resolution's actor label is not safe to treat as authenticated.",
                "blocking_artifact": None,
                "resolved_by": _clip(str(contest.get("actor")), 60) or "?",
                "resolved_at": _stamp(contest.get("ts")),
                "evidence_msg_ids": provenance["basis_msg_ids"][:8],
            })
            # A later claim remains untrusted, but contest evidence must not
            # hide its current text or a later protected-route context row.
            for later_claim in _unverified_question_claims(question, rows, after=contest):
                text = _first_clip(_body(later_claim).get("text"),
                                   _body(later_claim).get("summary"), maximum=900)
                add(question, card, {
                    "id": later_claim["msg_id"], "disposition": "contested",
                    "summary": _clip("Later unverified human claim remains non-terminal"
                                     + (f": {text}" if text else "."), 1200),
                    "reason": "The actor label is not proof of owner identity; this is current context only.",
                    "blocking_artifact": None,
                    "resolved_by": _clip(str(later_claim.get("actor")), 60) or "?",
                    "resolved_at": _stamp(later_claim.get("ts")),
                    "evidence_msg_ids": [later_claim["msg_id"]],
                })
            for request in _owner_reconciliation_requests(question, rows, after=contest):
                text = _clip(_body(request).get("text"), 900)
                add(question, card, {
                    "id": request["msg_id"], "disposition": "contested",
                    "summary": _clip("Later authorized-route reconciliation remains non-terminal"
                                     + (f": {text}" if text else "."), 1200),
                    "reason": "The route supplies current context but repository code cannot make it durable proof of a genuine owner ruling.",
                    "blocking_artifact": None,
                    "resolved_by": _clip(str(request.get("actor")), 60) or "?",
                    "resolved_at": _stamp(request.get("ts")),
                    "evidence_msg_ids": [request["msg_id"]],
                })
        elif claim is not None:
            body = _body(claim)
            is_resolution = claim.get("kind") == "question_resolution"
            text = _first_clip(body.get("summary"), body.get("text"), body.get("reason"), maximum=900)
            add(question, card, {
                "id": claim["msg_id"], "disposition": "contested",
                "summary": _clip(
                    ("An unauthenticated resolution claim did not close this question."
                     if is_resolution else "An unverified human answer claim did not close this question.")
                    + (f" Claimed context: {text}" if text else ""), 1200),
                "reason": "Mailbox actor labels are not strong authentication; use the authorized owner UI route to reconcile the genuine owner response.",
                "blocking_artifact": None,
                "resolved_by": _clip(str(claim.get("actor")), 60) or "?",
                "resolved_at": _stamp(claim.get("ts")),
                "evidence_msg_ids": [value for value in body.get("evidence_msg_ids", [])
                                     if isinstance(value, str)][:8] + [claim["msg_id"]],
            })
            # Do not let a newer protected-route reconciliation disappear
            # merely because the same thread also has an unauthenticated
            # answer claim.  Both remain non-terminal context.
            for request in _owner_reconciliation_requests(question, rows, after=claim):
                text = _clip(_body(request).get("text"), 900)
                add(question, card, {
                    "id": request["msg_id"], "disposition": "contested",
                    "summary": _clip("Later authorized-route reconciliation remains non-terminal"
                                     + (f": {text}" if text else "."), 1200),
                    "reason": "The route supplies current context but repository code cannot make it durable proof of a genuine owner ruling.",
                    "blocking_artifact": None,
                    "resolved_by": _clip(str(request.get("actor")), 60) or "?",
                    "resolved_at": _stamp(request.get("ts")),
                    "evidence_msg_ids": [request["msg_id"]],
                })
        else:
            add(question, card, {
                "id": reconciliation["msg_id"], "disposition": "contested",
                "summary": "Owner reconciliation was requested; this question remains open.",
                "reason": "The authorized UI route carries context but repository code cannot turn it into durable human authentication or a terminal ruling.",
                "blocking_artifact": None,
                "resolved_by": _clip(str(reconciliation.get("actor")), 60) or "?",
                "resolved_at": _stamp(reconciliation.get("ts")),
                "evidence_msg_ids": [reconciliation["msg_id"]],
            })
    found.sort(key=lambda row: row["resolved_at"] or "", reverse=True)
    return found


def question_updates(rows: list[dict]) -> list[dict]:
    """Recent explicit non-answer dispositions, bounded for the v3 payload."""
    return _all_question_updates(rows)[:10]


def question_updates_overflow(rows: list[dict]) -> int:
    """Count update evidence omitted by the v3 payload's fixed display bound."""
    return max(0, len(_all_question_updates(rows)) - 10)


def _word(value: str, text: str) -> bool:
    return re.search(rf"(?<![\w/-]){re.escape(value)}(?![\w-])", text) is not None


def _orchestrator():
    """The orchestrator modules shipped with this UI checkout (lazy, like ladder.py)."""
    root = str(CODE_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    from orchestrator import oracle_mailbox, research_focus
    return oracle_mailbox, research_focus


# -- sources -----------------------------------------------------------------

def plan_files(repo: Path) -> dict[str, list[tuple[int, str]]]:
    """date -> [(revision number, file name)], ascending; other names are ignored."""
    try:
        names = os.listdir(repo / "run_state" / "daily_plans")
    except OSError:
        return {}
    found: dict[str, list[tuple[int, str]]] = {}
    for name in names:
        match = PLAN_NAME.match(name)
        if match:
            found.setdefault(match.group(1), []).append((int(match.group(2) or 1), name))
    return {date: sorted(revs) for date, revs in found.items()}


def _load_plan(repo: Path, name: str) -> tuple[dict, str, datetime]:
    path = repo / "run_state" / "daily_plans" / name
    raw = _read_regular(path, MAX_PLAN_BYTES)
    plan = json.loads(raw, object_pairs_hook=_unique_object)
    items = plan.get("items") if isinstance(plan, dict) else None
    if (not isinstance(plan, dict) or plan.get("date") != name[:10] or not isinstance(items, list)
            or not all(isinstance(i, dict) and isinstance(i.get("id"), str)
                       and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,39}", i["id"]) for i in items)
            or len({i["id"] for i in items}) != len(items)):
        raise ValueError(f"{name} does not match the daily plan contract")
    written = datetime.fromtimestamp(os.stat(path).st_mtime, timezone.utc)
    return plan, hashlib.sha256(raw).hexdigest(), written


def _mailbox(repo: Path) -> list[dict]:
    oracle_mailbox, _ = _orchestrator()
    return oracle_mailbox.read(repo / "run_state" / "oracle_nara_mailbox.jsonl")


def _fallback_live_rows(rows: list[dict]) -> list[dict]:
    """Fail-closed projection adapter until the shared quarantine API lands.

    ``read`` verifies the append-only hash chain but intentionally preserves
    hash-valid malformed evidence.  UI actions must not treat such a row as
    live coordination state.  This local boundary is deliberately conservative
    and can be removed once the reviewed mailbox ``live_rows`` helper is on the
    release base.
    """
    oracle_mailbox, _ = _orchestrator()
    found = []
    for position, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != MAILBOX_ROW_FIELDS:
            continue
        if row.get("schema") != oracle_mailbox.SCHEMA:
            continue
        if type(row.get("seq")) is not int or row["seq"] != position + 1:
            continue
        actor, recipient = row.get("actor"), row.get("to")
        kind, body = row.get("kind"), row.get("body")
        if not isinstance(actor, str) or not oracle_mailbox._actor_ok(actor):
            continue
        if not isinstance(recipient, str) or recipient not in oracle_mailbox.RECIPIENTS:
            continue
        if not isinstance(kind, str) or kind not in oracle_mailbox.KINDS:
            continue
        if not (actor in oracle_mailbox.KINDS[kind]
                or (actor.startswith("human:") and kind in oracle_mailbox.HUMAN_KINDS)):
            continue
        if not isinstance(body, dict) or not isinstance(row.get("msg_id"), str) or not row["msg_id"]:
            continue
        reply = row.get("in_reply_to")
        if reply is not None and not isinstance(reply, str):
            continue
        if kind in {"receipt", "withdraw", "answer", "review", "question_resolution"} and not reply:
            continue
        at, expires = _when(row.get("ts")), _when(row.get("expires_at"))
        if at is None or (row.get("expires_at") is not None and expires is None):
            continue
        if expires is not None and expires <= at:
            continue
        try:
            if kind == "plan_item":
                oracle_mailbox.validate_plan_item(body)
            elif kind == "receipt" and body.get("state") not in oracle_mailbox.RECEIPT_STATES:
                continue
            elif kind == "review" and body.get("verdict") not in oracle_mailbox.VERDICTS:
                continue
            elif kind == "question_resolution":
                oracle_mailbox.validate_question_resolution(body)
        except Exception:
            continue
        previous = rows[position - 1] if position else None
        previous_sha = previous.get("row_sha256") if isinstance(previous, dict) else None
        if row.get("prev_sha256") != previous_sha:
            continue
        claimed_sha = row.get("row_sha256")
        if not isinstance(claimed_sha, str) or re.fullmatch(r"[0-9a-f]{64}", claimed_sha) is None:
            continue
        without_sha = dict(row)
        without_sha.pop("row_sha256")
        if hashlib.sha256(oracle_mailbox._canonical(without_sha)).hexdigest() != claimed_sha:
            continue
        msg_id = without_sha.pop("msg_id")
        expected_id = (
            f"{actor.split(':')[0]}-"
            f"{hashlib.sha256(oracle_mailbox._canonical(without_sha)).hexdigest()[:16]}"
        )
        if msg_id != expected_id:
            continue
        found.append(row)
    return _relational_live_rows(found)


def _relational_live_rows(rows: list[dict]) -> list[dict]:
    """Keep only first identities and replies to one preceding admitted question.

    Structural validity is not enough for owner actions. A future row cannot
    retroactively make an earlier human answer claim or resolution valid, and
    a later duplicate id cannot replace the question object the owner originally
    saw. The first admitted identity wins; later duplicates remain append-only
    evidence but are not projection state. Model answer rows remain context,
    never terminal authority.
    """
    admitted: list[dict] = []
    seen_ids: set[str] = set()
    questions: dict[str, dict] = {}
    owner_requests: dict[str, tuple[str, str, str]] = {}
    for row in rows:
        msg_id = row["msg_id"]
        if msg_id in seen_ids:
            continue
        seen_ids.add(msg_id)
        kind = row.get("kind")
        human_answer = (kind == "answer" and isinstance(row.get("actor"), str)
                        and row["actor"].startswith("human:"))
        if kind == "question_resolution" or human_answer:
            question = questions.get(row.get("in_reply_to"))
            if question is None:
                continue
            if kind == "question_resolution":
                actor = row.get("actor")
                if not (isinstance(actor, str)
                        and (actor == question.get("actor") or actor.startswith("human:"))):
                    continue
            if human_answer:
                body = _body(row)
                if body.get("via") == "owner-ui":
                    request_id = body.get("request_id")
                    revision = body.get("expected_plan_revision")
                    if (not isinstance(request_id, str)
                            or re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", request_id) is None
                            or body.get("target_kind") != "question"
                            or not isinstance(revision, str)
                            or PLAN_NAME.fullmatch(f"{revision}.json") is None):
                        continue
                    binding = (str(row.get("in_reply_to")), revision,
                               json.dumps(body, sort_keys=True, separators=(",", ":")))
                    if request_id in owner_requests and owner_requests[request_id] != binding:
                        continue
                    owner_requests[request_id] = binding
        admitted.append(row)
        if kind == "question":
            questions[msg_id] = row
    return admitted


def _projection_rows(rows: list[dict]) -> list[dict]:
    """Structurally and relationally live rows, without mutating evidence."""
    oracle_mailbox, _ = _orchestrator()
    shared = getattr(oracle_mailbox, "live_rows", None)
    return _relational_live_rows(shared(rows)) if callable(shared) else _fallback_live_rows(rows)


def _project_focus(repo: Path) -> dict:
    _, research_focus = _orchestrator()
    return research_focus.project_focus(repo)


class _Git:
    """Read-only git facts pinned to one ``main`` head; branch heads are read each refresh."""

    def __init__(self, repo: Path):
        self.repo = repo
        self.available = (repo / ".git").exists()
        self.main = self._run("rev-parse", "--verify", "--quiet", "main^{commit}") if self.available else None
        self.available = self.main is not None
        refs = self._run("for-each-ref", "--format=%(refname:short) %(objectname)",
                         "refs/heads/oracle/") if self.available else None
        self.heads = dict(line.split(" ", 1) for line in (refs or "").splitlines() if " " in line)
        key = (str(repo), self.main)
        with _git_lock:
            cached = _git_cache.get(key)
            if cached is None:
                log = self._run("log", "--first-parent", self.main, "--since=8.days", "-n", "400",
                                "--format=%H%x1f%P%x1f%cI%x1f%s") if self.available else None
                history = [line.split("\x1f", 3) for line in (log or "").splitlines()
                           if line.count("\x1f") == 3]
                cached = {
                    "history": history,
                    "log": [[sha, when, subject] for sha, _, when, subject in history],
                }
                _git_cache.clear()  # one repo, one main head: keep the cache bounded
                _git_cache[key] = cached
        self.history = cached["history"]
        self.log = cached["log"]

    def _run(self, *args: str) -> str | None:
        try:
            result = subprocess.run(["git", "-C", str(self.repo), *args], capture_output=True,
                                    text=True, timeout=5, check=False)
        except (OSError, subprocess.SubprocessError):
            return None
        return result.stdout.strip() if result.returncode == 0 else None

# -- derivations ---------------------------------------------------------------

def current_plan(repo: Path, now: datetime | None = None) -> tuple[str, dict] | None:
    """Return an actionable current plan, never merely the newest filename.

    A retained prior-day plan stays visible in the read model as historical
    context, but owner controls and their append-time linearization must not
    accept it as today's plan of record.
    """
    plans = plan_files(Path(repo))
    if not plans:
        return None
    now = now or datetime.now(timezone.utc)
    date = now.astimezone(LAB_TZ).date().isoformat()
    revisions = plans.get(date)
    if not revisions:
        return None
    name = revisions[-1][1]
    plan = _load_plan(Path(repo), name)[0]
    if plan["date"] != date:
        return None
    return name[:-5], plan


def plan_windows(rows: list[dict], max_date: str | None = None) -> dict[str, tuple[int, float]]:
    """Date windows; a future receipt cannot end today's evidence window."""
    firsts: dict[str, int] = {}
    for row in rows:
        match = (PLAN_READY.match(_title(row))
                 if row.get("kind") == "note" and row.get("actor") == "oracle" else None)
        if match and (max_date is None or match.group(1) <= max_date):
            firsts.setdefault(match.group(1), row["seq"])
    ordered = sorted(firsts.items(), key=lambda pair: pair[0])
    windows = {}
    for index, (date, start) in enumerate(ordered):
        later = [seq for _, seq in ordered[index + 1:]]
        windows[date] = (start, min(later) if later else float("inf"))
    return windows


def _window(rows: list[dict], windows: dict, date: str, first_written: datetime | None):
    """Legacy date-scoped fallback for plans published before hash references."""
    if date in windows:
        return windows[date]
    start = next((row["seq"] for row in rows if first_written and _when(row.get("ts"))
                  and _when(row["ts"]) >= first_written), float("inf"))
    return (start, float("inf"))


def _plan_catalog(repo: Path, plans: dict[str, list[tuple[int, str]]]) \
        -> dict[str, tuple[str, str | None]]:
    """Known plan paths, dates and content hashes; unreadable files stay ambiguous."""
    found = {}
    for date, revisions in plans.items():
        for _, name in revisions:
            try:
                _, sha256, _ = _load_plan(repo, name)
            except (OSError, ValueError):
                sha256 = None
            found[f"run_state/daily_plans/{name}"] = (date, sha256)
    return found


def _plan_ready_date(row: dict) -> str | None:
    if row.get("actor") != "oracle" or row.get("kind") != "note":
        return None
    match = PLAN_READY.match(_title(row))
    return match.group(1) if match else None


def _exact_plan_anchor(row: dict, path: str, date: str, sha256: str | None) -> bool:
    """A PLAN READY authority boundary names one immutable on-disk plan."""
    ref = _ref(row)
    return (_plan_ready_date(row) == date and sha256 is not None
            and ref.get("path") == path and ref.get("sha256") == sha256)


def _legacy_plan_anchors(rows: list[dict], catalog: dict[str, tuple[str, str | None]]) -> dict[str, str]:
    """Map an unambiguous pre-reference receipt to its sole plan path.

    A structured receipt with a missing or wrong field is evidence of a failed
    publication, not permission to fall back to date matching.
    """
    paths_by_date: dict[str, list[str]] = {}
    for path, (date, _) in catalog.items():
        paths_by_date.setdefault(date, []).append(path)
    receipts_by_date: dict[str, list[dict]] = {}
    for row in rows:
        title_date = _plan_ready_date(row)
        if title_date is None:
            continue
        dates = {title_date}
        path = _ref(row).get("path")
        if isinstance(path, str) and path in catalog:
            dates.add(catalog[path][0])
        for receipt_date in dates:
            receipts_by_date.setdefault(receipt_date, []).append(row)
    found = {}
    for date, paths in paths_by_date.items():
        receipts = receipts_by_date.get(date, [])
        legacy = [row for row in receipts
                  if "path" not in _ref(row) and "sha256" not in _ref(row)]
        if len(paths) == 1 and len(receipts) == 1 and len(legacy) == 1:
            found[legacy[0]["msg_id"]] = paths[0]
    return found


def _verified_plan_anchor(row: dict, catalog: dict[str, tuple[str, str | None]],
                          legacy: dict[str, str]) -> str | None:
    path = _ref(row).get("path")
    if isinstance(path, str) and path in catalog:
        date, sha256 = catalog[path]
        if _exact_plan_anchor(row, path, date, sha256):
            return path
    return legacy.get(row.get("msg_id"))


def _revision_window(rows: list[dict], windows: dict, date: str, name: str | None,
                     sha256: str | None, first_written: datetime | None,
                     catalog: dict[str, tuple[str, str | None]] | None = None) \
        -> tuple[int, float, bool]:
    """Return the evidence interval for one immutable plan revision.

    The exact plan-ready receipt is the authority boundary. Reusing ``d1`` on
    a later revision cannot pull in an earlier item, ready note, review, branch
    or owner question. The date window remains only for historical plans whose
    publication did not carry a path-and-hash reference.
    """
    if name is None or sha256 is None:
        start, end = _window(rows, windows, date, first_written)
        return start, end, False

    path = f"run_state/daily_plans/{name}"
    catalog_known = catalog is not None
    catalog = catalog or {path: (date, sha256)}
    catalog = {**catalog, path: (date, sha256)}
    exact = [row for row in rows if _exact_plan_anchor(row, path, date, sha256)]
    legacy = _legacy_plan_anchors(rows, catalog) if catalog_known else {}
    anchors = [(row, _verified_plan_anchor(row, catalog, legacy)) for row in rows]
    anchors = [(row, anchored_path) for row, anchored_path in anchors if anchored_path]
    def identity(anchored_path: str) -> tuple[str, int]:
        match = PLAN_NAME.match(anchored_path.rsplit("/", 1)[-1])
        return (match.group(1), int(match.group(2) or 1)) if match else ("", 0)
    target_identity = identity(path)
    if exact:
        anchor = min(exact, key=lambda row: row["seq"])
    else:
        fallback = [row for row, anchored_path in anchors if anchored_path == path
                    and row.get("msg_id") in legacy]
        if not fallback:
            return float("inf"), float("inf"), True
        anchor = min(fallback, key=lambda row: row["seq"])
    # Old/backdated receipts cannot truncate a newer plan or gain a fresh
    # window after that newer plan was already published.
    if any(row["seq"] <= anchor["seq"] and identity(anchored_path) > target_identity
           for row, anchored_path in anchors):
        return float("inf"), float("inf"), True
    end = min((row["seq"] for row, anchored_path in anchors
               if row["seq"] > anchor["seq"] and identity(anchored_path) > target_identity),
              default=float("inf"))
    return anchor["seq"], end, True


def plan_review(rows: list[dict], name: str, sha256: str) -> dict | None:
    path = f"run_state/daily_plans/{name}"
    notes = [row for row in rows if _exact_plan_anchor(row, path, name[:10], sha256)]
    if not notes:
        return None
    # Reposting the same receipt cannot discard evidence already attached to
    # the first immutable publication boundary.
    note = min(notes, key=lambda row: row["seq"])
    oracle_mailbox, _ = _orchestrator()
    reviews = [row for row in rows if row.get("kind") == "review"
               and row.get("actor") in oracle_mailbox.REVIEWERS
               and row.get("in_reply_to") == note["msg_id"] and row["seq"] > note["seq"]]
    review = max(reviews, key=lambda row: row["seq"], default=None)
    body = _body(review) if review else {}
    accepted = body.get("accepted_items") if isinstance(body.get("accepted_items"), list) else []
    return {
        "note_msg_id": note["msg_id"],
        "sha_matches": True,
        "verdict": body.get("verdict") if body.get("verdict") in VERDICT_STATUS else None,
        "review_msg_id": review["msg_id"] if review else None,
        "reviewed_at": _stamp(review.get("ts")) if review else None,
        "summary": _clip(body.get("summary"), 400),
        "accepted_items": [str(i)[:40] for i in accepted if isinstance(i, str)][:MAX_WORK_ITEMS],
    }


def _nara_item(item, ids, rows, window, folded):
    posted = [row for row in rows if row.get("kind") == "plan_item" and row.get("actor") == "oracle"
              and window[0] <= row["seq"] < window[1]
              and (_clip(_title(row), 400) == _clip(item.get("title"), 400)
                   or {i for i in ids if _word(i, _title(row))} == {item["id"]})]
    if not posted:
        return "not_started", "No matching plan item posted to Nara's lane yet.", None, None, None
    row = posted[-1]
    entry = folded.get(row["msg_id"], {"state": "open", "receipts": []})
    status = FOLD_STATUS.get(entry["state"], "not_started")
    last = entry["receipts"][-1] if entry["receipts"] else row
    body = _body(last)
    reviews = [r for r in rows if r.get("kind") == "review" and r.get("in_reply_to") == row["msg_id"]]
    detail = f"Lane item {row['msg_id']}: {entry['state']}"
    if isinstance(body.get("reasons"), list) and body["reasons"]:
        detail += f" ({_clip(str(body['reasons'][0]), 160)})"
    if reviews:
        detail += f"; claimed review {_body(reviews[-1]).get('verdict')} ({reviews[-1]['msg_id']})"
    sha = body.get("head_sha") if isinstance(body.get("head_sha"), str) else None
    return status, detail + ".", last["msg_id"], (sha or "")[:12] or None, _stamp(last.get("ts"))


def _oracle_item(item, date, rows, git, window, revision_scoped):
    branch = re.compile(rf"oracle/{re.escape(date)}-{re.escape(item['id'])}(?:-r\d+)?(?![\w-])")
    ready = [row for row in rows if row.get("actor") == "oracle" and row.get("kind") == "note"
             and _title(row).startswith("READY FOR REVIEW")
             and window[0] <= row["seq"] < window[1]
             and (branch.fullmatch(str(_ref(row).get("branch"))) if _ref(row).get("branch")
                  else branch.search(_title(row)))]
    if not ready:
        if revision_scoped:
            return "not_started", "No revision-scoped READY FOR REVIEW note yet.", None, None, None
        heads = [name for name in git.heads if branch.fullmatch(name)]
        if heads:
            return "building", f"Branch {heads[-1]} exists; no READY FOR REVIEW note yet.", None, None, None
        return "not_started", "No branch or READY FOR REVIEW note yet.", None, None, None
    note = max(ready, key=lambda row: row["seq"])
    oracle_mailbox, _ = _orchestrator()
    reviews = [row for row in rows if row.get("kind") == "review"
               and row.get("actor") in oracle_mailbox.REVIEWERS
               and row.get("in_reply_to") == note["msg_id"] and row["seq"] > note["seq"]]
    review = max(reviews, key=lambda row: row["seq"], default=None)
    if review is None:
        return "awaiting_review", _clip(_title(note), 200), note["msg_id"], None, _stamp(note.get("ts"))
    verdict = _body(review).get("verdict")
    return (VERDICT_STATUS.get(verdict, "awaiting_review"),
            f"Claimed review {verdict}: {_clip(_body(review).get('summary'), 200) or _title(note)}",
            review["msg_id"], None, _stamp(review.get("ts")))


def _owner_question(item, ids, rows, window):
    asked = [row for row in rows if row.get("kind") == "question" and row.get("to") == "owner"
             and window[0] <= row["seq"] < window[1]
             and (_ref(row).get("item") == item["id"]
                  or {i for i in ids if _word(i, _title(row))} == {item["id"]})]
    return asked[-1] if asked else None


def work_items(plan: dict, rows: list[dict], windows: dict, git: _Git, now: datetime,
               first_written: datetime | None, name: str | None = None,
               sha256: str | None = None,
               catalog: dict[str, tuple[str, str | None]] | None = None) -> tuple[list[dict], dict]:
    """One row per plan item, and the owner questions those items already claim."""
    oracle_mailbox, _ = _orchestrator()
    folded = oracle_mailbox.fold(rows, now, already_live=True)
    date = plan["date"]
    ids = [item["id"] for item in plan["items"]]
    start, end, revision_scoped = _revision_window(
        rows, windows, date, name, sha256, first_written, catalog)
    window = (start, end)
    result, claimed = [], {}
    for item in plan["items"][:MAX_WORK_ITEMS]:
        lane = item.get("lane")
        if lane == "nara_dev":
            status, detail, msg, sha, at = _nara_item(item, ids, rows, window, folded)
        elif lane == "oracle_dev":
            status, detail, msg, sha, at = _oracle_item(item, date, rows, git, window, revision_scoped)
        elif lane == "owner_decision":
            question = _owner_question(item, ids, rows, window)
            if question is not None:
                claimed[question["msg_id"]] = item["id"]
            resolution = _question_resolution(question, rows) if question is not None else None
            if resolution is not None:
                body = _body(resolution)
                disposition = body["disposition"]
                status = "held" if disposition == "prerequisite" else "resolved"
                detail = (f"Question {disposition}: {_clip(body.get('summary'), 240)} "
                          f"({resolution['msg_id']} from {resolution.get('actor')}).")
                msg, at = resolution["msg_id"], _stamp(resolution.get("ts"))
            elif question is not None:
                status = "waiting_on_you"
                detail = f"Owner question {question['msg_id']} from {question.get('actor')} is open."
                msg, at = question["msg_id"], _stamp(question.get("ts"))
            else:
                status = "held"
                detail = ("Held for agent action: no matching owner question has been posted; "
                          "Oracle or Nara must resolve the item or post a structured owner question.")
                msg, at = None, None
            sha = None
        else:
            status, detail, msg, sha, at = "not_started", f"No live producer for lane {lane}.", None, None, None
        result.append({
            "id": item["id"],
            "goal": _clip(item.get("goal"), 40) or "—",
            "owner": _clip(item.get("owner"), 40) or "—",
            "lane": _clip(lane, 40) or "—",
            "repo": _clip(item.get("repo"), 60) or "—",
            "title": _clip(item.get("title"), 300) or item["id"],
            "summary": _clip(item.get("summary"), 90),
            "why_today": _clip(item.get("why_today"), 1200),
            "acceptance": _clip(item.get("acceptance"), 1200),
            "depends_on": [str(d)[:40] for d in item.get("depends_on", []) if isinstance(d, str)][:8]
            if isinstance(item.get("depends_on"), list) else [],
            "status": status,
            "detail": _clip(detail, 400) or status,
            "evidence_msg_id": msg,
            "evidence_sha": sha,
            "evidence_at": at,
        })
    return result, claimed


def _reply_to(row: dict | None) -> str:
    asker = str((row or {}).get("actor", "oracle")).split(":")[0]
    return asker if asker in {"oracle", "nara", "claude", "codex"} else "oracle"


def _waiting_cards(plan_id: str | None, items: list[dict], claimed: dict, rows: list[dict],
                   plan_written: str | None) -> list[dict]:
    rows = _relational_live_rows(rows)
    by_id = {row["msg_id"]: row for row in rows}
    waiting = []
    for item in items:
        if item["status"] != "waiting_on_you":
            continue
        msg = item["evidence_msg_id"]
        question = by_id.get(msg) if msg else None
        if question is None:  # an owner-facing action must have one concrete answer target
            continue
        if (question is not None and (_human_answer(question, rows) is not None
                                     or _question_resolution(question, rows) is not None)):
            continue
        card = _question_card(question)
        cli = (f"{CLI} --kind answer --to {_reply_to(question)} --in-reply-to {msg} "
               f"--body '{{\"text\": \"...\"}}'")
        if _historical_presentation_archive(question, rows) is not None:
            continue
        handoff = interactive_claude_handoff(question, rows)
        waiting.append({"kind": "owner_decision", "id": f"{plan_id}:{item['id']}", **card,
                        "asked_by": _reply_to(question),
                        "asked_at": item["evidence_at"] or plan_written, "msg_id": msg, "cli": cli,
                        "awaiting_asker": handoff is not None,
                        "handoff_msg_id": handoff["msg_id"] if handoff else None})
    for row in rows:
        if (row.get("kind") != "question" or row.get("to") != "owner" or row["msg_id"] in claimed
                or _human_answer(row, rows) is not None or _question_resolution(row, rows) is not None):
            continue
        if _historical_presentation_archive(row, rows) is not None:
            continue
        to = _reply_to(row)
        card = _question_card(row)
        handoff = interactive_claude_handoff(row, rows)
        waiting.append({
            "kind": "question", "id": row["msg_id"],
            **card,
            "asked_by": _clip(str(row.get("actor")), 60) or "?", "asked_at": _stamp(row.get("ts")),
            "msg_id": row["msg_id"],
            "cli": f"{CLI} --kind answer --to {to} --in-reply-to {row['msg_id']} --body '{{\"text\": \"...\"}}'",
            "awaiting_asker": handoff is not None,
            "handoff_msg_id": handoff["msg_id"] if handoff else None,
        })
    # Actionable owner cards are never displaced by display-only routed cards.
    return sorted(waiting, key=lambda card: card["awaiting_asker"])


def waiting_on_you(plan_id: str | None, items: list[dict], claimed: dict, rows: list[dict],
                   plan_written: str | None) -> list[dict]:
    """At most MAX_ROWS cards; use ``waiting_overflow`` to expose any remainder."""
    return _waiting_cards(plan_id, items, claimed, rows, plan_written)[:MAX_ROWS]


def waiting_overflow(plan_id: str | None, items: list[dict], claimed: dict, rows: list[dict],
                     plan_written: str | None) -> int:
    """Count cards omitted by the bounded response, without silently losing them."""
    return max(0, len(_waiting_cards(plan_id, items, claimed, rows, plan_written)) - MAX_ROWS)


def research_focus(repo: Path, now: datetime) -> dict:
    try:
        value = _project_focus(repo)
    except Exception as exc:  # the projection is a boundary; any failure is shown, not hidden
        return {"status": "source_invalid", "reason": _clip(f"{type(exc).__name__}: {exc}", 240),
                "observed_at": _iso(now)}
    status = value.get("status") if isinstance(value, dict) else None
    result = {"status": status if status in {"selected", "none"} else "source_invalid",
              "observed_at": _iso(now)}
    if result["status"] == "selected":
        result.update({key: _clip(value.get(key), 1200 if key == "next_action" else 300)
                       for key in ("focus_id", "title", "stage", "next_action", "intake_policy")})
        result["selected_at"] = _stamp(value.get("selected_at"))
    elif result["status"] == "source_invalid":
        result["reason"] = _clip(value.get("reason") if isinstance(value, dict) else None, 240) or "unreadable"
    closure = value.get("last_closure") if isinstance(value, dict) else None
    if isinstance(closure, dict) and closure.get("status") == "source_invalid":
        result["closure_error"] = _clip(closure.get("reason"), 240) or "unreadable"
    elif isinstance(closure, dict):
        result["last_closure"] = {
            "focus_id": _clip(closure.get("focus_id"), 120), "title": _clip(closure.get("title"), 300),
            "disposition": _clip(closure.get("disposition"), 40), "closed_at": _stamp(closure.get("closed_at")),
            "reason": _clip(closure.get("reason"), 1200),
            "closure_sha256": _clip(closure.get("closure_sha256"), 64),
        }
    return result


def _closures(repo: Path) -> list[dict]:
    directory = repo / "run_state" / "research_focus" / "closures"
    found = []
    for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
        try:
            raw = _read_regular(path, 16_384)
            closure = json.loads(raw)
        except (OSError, ValueError):
            continue
        if hashlib.sha256(raw).hexdigest() == path.stem and isinstance(closure, dict):
            found.append({**closure, "closure_sha256": path.stem})
    return found


def accomplishments(repo: Path, rows: list[dict], windows: dict, git: _Git, now: datetime,
                    plans: dict, catalog: dict[str, tuple[str, str | None]]) -> list[dict]:
    since = now - timedelta(days=WINDOW_DAYS)
    found = []
    oldest = (now.astimezone(LAB_TZ) - timedelta(days=WINDOW_DAYS)).date().isoformat()
    for date, revisions in plans.items():
        if date < oldest:
            continue
        try:
            first = datetime.fromtimestamp(
                os.stat(repo / "run_state" / "daily_plans" / revisions[0][1]).st_mtime, timezone.utc)
        except OSError:
            continue
        for _, name in revisions:
            try:
                plan, sha, written = _load_plan(repo, name)
            except (OSError, ValueError):
                continue
            items, _ = work_items(plan, rows, windows, git, now, first, name, sha, catalog)
            historical = name != revisions[-1][1]
            for item in items:
                if item["status"] in {"merged", "validated"}:
                    evidence = item["evidence_sha"] or item["evidence_msg_id"] or name
                    # Older same-day revisions retain an immutable id instead
                    # of colliding with a reused dN in the plan of record.
                    identifier = (f"{date}:{name[:-5]}:{item['id']}"
                                  if historical else f"{date}:{item['id']}")
                    found.append({"id": identifier, "kind": item["status"],
                                  "title": f"{date} {item['id']} ({item['goal']}): {item['title']}",
                                  "at": item["evidence_at"] or _iso(written), "evidence": evidence})
    for closure in _closures(repo):
        at = _when(closure.get("closed_at"))
        if at and at >= since:
            found.append({"id": f"closure:{closure['closure_sha256'][:16]}", "kind": "focus_closed",
                          "title": _clip(f"Focus {closure.get('disposition')}: {closure.get('title')}", 300),
                          "at": _iso(at), "evidence": closure["closure_sha256"][:12]})
    for row in rows:
        at = _when(row.get("ts"))
        if (row.get("kind") == "note" and row.get("actor") == "oracle"
                and _title(row).startswith("DAY CLOSED") and at and at >= since):
            found.append({"id": row["msg_id"], "kind": "day_closed", "title": _clip(_title(row), 300),
                          "at": _iso(at), "evidence": row["msg_id"]})
    found.sort(key=lambda row: row["at"], reverse=True)
    return found[:MAX_ROWS]


def improvements(git: _Git, now: datetime) -> list[dict]:
    since = now - timedelta(days=WINDOW_DAYS)
    rows = []
    for sha, when, subject in git.log:
        at = _when(when)
        if at and at >= since:
            rows.append({"sha": sha[:12], "at": _iso(at), "subject": _clip(subject, 240) or sha[:12],
                         "goals": sorted(set(GOAL.findall(subject)))[:6]})
    return rows[:MAX_IMPROVEMENTS]


def build(repo: Path, now: datetime, *, recorded_rows: list[dict] | None = None) -> dict:
    """Every v3 summary field except ``agents``; failures become warnings, never old content."""
    repo = Path(repo)
    warnings: list[str] = []
    try:
        recorded_rows = _mailbox(repo) if recorded_rows is None else recorded_rows
        rows = _projection_rows(recorded_rows)
        mailbox_error = None
        omitted = len(recorded_rows) - len(rows)
        if omitted:
            warnings.append(
                f"Lab mailbox contains {omitted} structurally invalid row(s); they are preserved as evidence "
                "but omitted from live actions and statuses.")
    except Exception as exc:  # a broken hash chain is shown, not papered over
        rows, mailbox_error = [], _clip(f"{type(exc).__name__}: {exc}", 200)
        warnings.append(f"Lab mailbox is unreadable ({mailbox_error}); work statuses are not derived.")
    git = _Git(repo)
    if not git.available:
        warnings.append("Read-only git on main is unavailable; merged status and improvements are not derived.")
    plans = plan_files(repo)
    lab_now = now.astimezone(LAB_TZ)
    today = lab_now.date().isoformat()
    oldest = (lab_now - timedelta(days=WINDOW_DAYS)).date().isoformat()
    eligible_plans = {date: revisions for date, revisions in plans.items() if date <= today}
    catalog_plans = {date: revisions for date, revisions in eligible_plans.items() if date >= oldest}
    if eligible_plans and max(eligible_plans) not in catalog_plans:
        catalog_plans[max(eligible_plans)] = eligible_plans[max(eligible_plans)]
    catalog = _plan_catalog(repo, catalog_plans)
    windows = plan_windows(rows, max_date=today)
    daily_plan, items, claimed, plan_id = None, [], {}, None
    if plans:
        # A queued future plan is useful history, but must never shadow a
        # valid plan for the lab's present day.
        date = today if today in plans else max(eligible_plans) if eligible_plans else min(plans)
        revision, name = plans[date][-1]
        try:
            plan, sha, written = _load_plan(repo, name)
            first = datetime.fromtimestamp(os.stat(repo / "run_state" / "daily_plans" / plans[date][0][1]).st_mtime,
                                           timezone.utc)
            plan_id = name[:-5]
            bottlenecks = plan.get("bottlenecks") if isinstance(plan.get("bottlenecks"), list) else []
            is_current = date == today
            daily_plan = {
                "id": plan_id, "date": date, "revision": f"r{revision}", "path": f"run_state/daily_plans/{name}",
                "sha256": sha, "written_at": _iso(written),
                "is_current": is_current,
                "week_alignment": _clip(plan.get("week_alignment"), 1200),
                "bottlenecks": [text for text in (_clip(b.get("what"), 400) for b in bottlenecks[:5]
                                                  if isinstance(b, dict)) if text],
                "review": plan_review(rows, name, sha),
            }
            if not mailbox_error and is_current:
                items, claimed = work_items(plan, rows, windows, git, now, first, name, sha, catalog)
            elif not is_current:
                warnings.append(
                    f"Daily plan {name} is outside the current lab day; it remains visible as context, but its work and owner controls are disabled."
                )
        except (OSError, ValueError) as exc:
            warnings.append(_clip(f"Newest daily plan {name} is unreadable: {exc}", 480))
    newest_row = _stamp(rows[-1].get("ts")) if rows else None
    focus = research_focus(repo, now)
    active_plan_id = plan_id if daily_plan and daily_plan["is_current"] else None
    waiting = waiting_on_you(active_plan_id, items, claimed, rows,
                             daily_plan["written_at"] if daily_plan else None)
    overflow = waiting_overflow(active_plan_id, items, claimed, rows,
                                daily_plan["written_at"] if daily_plan else None)
    if overflow:
        warnings.append(
            f"{overflow} additional open owner card(s) are not displayed in this bounded view; actionable owner cards were prioritized over routed cards."
        )
    update_overflow = question_updates_overflow(rows)
    if update_overflow:
        warnings.append(
            f"{update_overflow} additional non-terminal or historical update(s) are not displayed in this bounded view."
        )
    if any(row.get("kind") == "review" for row in rows):
        warnings.append(
            "Mailbox review actor labels are unauthenticated claims, not authenticated Meta-oracle verdicts."
        )
    return {
        "schema_version": LIVE_SCHEMA,
        "generated_at": _iso(now),
        "current_plan_revision": active_plan_id,
        "daily_plan": daily_plan,
        "research_focus": focus,
        "work_items": items,
        "waiting_on_you": waiting,
        "question_updates": question_updates(rows),
        "accomplishments": accomplishments(repo, rows, windows, git, now, eligible_plans, catalog),
        "improvements": improvements(git, now),
        "warnings": warnings,
        "sources": {
            "plan": daily_plan["written_at"] if daily_plan else None,
            "mailbox": newest_row,
            "focus": focus.get("selected_at") or (focus.get("last_closure") or {}).get("closed_at"),
            "git": _stamp(git.log[0][1]) if git.log else None,
        },
    }


def live_summary(repo: Path, now: datetime | None = None) -> dict:
    """The full v3 summary with agent cards, for a backend that has no relay configured."""
    from .daily_ops_agents import observe, observe_nara_service
    now = now or datetime.now(timezone.utc)
    # The HTTP v3 boundary is fail-closed for the required mailbox source.  A
    # direct read-model caller may still inspect an unreadable source as a
    # warning, but a 200 response must never silently substitute an empty view.
    recorded_rows = _mailbox(Path(repo))
    value = build(repo, now, recorded_rows=recorded_rows)
    value["agents"] = observe(Path(repo), now=now, nara_service=observe_nara_service(now))
    return value


# -- validation ------------------------------------------------------------------

def _text(value, maximum, *, optional=False):
    if value is None:
        return optional
    return isinstance(value, str) and 0 < len(value) <= maximum and value == value.strip() \
        and all(ord(char) >= 32 for char in value)


def _time(value, *, optional=False):
    return (optional and value is None) or _stamp(value) == value


def _rows(value, keys, maximum, check):
    return isinstance(value, list) and len(value) <= maximum and all(
        isinstance(row, dict) and set(row) == keys and check(row) for row in value)


def validate_agents(value: object) -> bool:
    """Validate the v3-only live agent cards without widening the v2 schema.

    The older daily-ops view has a smaller status enum and a three-card shape.
    This separate validator admits the v3 observation vocabulary while keeping
    that legacy contract entirely unchanged.
    """
    required = {"oracle", "pi_client", "nara"}
    permitted = required | {"meta_oracle"}
    if not isinstance(value, dict) or not required <= set(value) <= permitted:
        return False
    fields = {"label", "role", "status", "detail", "observed_at", "source", "activity", "activity_at", "since"}
    for key, row in value.items():
        if not isinstance(row, dict) or set(row) != fields:
            return False
        if not (
            _text(row.get("label"), 512)
            and _text(row.get("role"), 512)
            and row.get("status") in AGENT_STATUSES
            and _text(row.get("detail"), 512)
            and _time(row.get("observed_at"))
            and _text(row.get("source"), 512)
            and (row.get("activity") is None or _text(row["activity"], 512))
            and _time(row.get("activity_at"), optional=True)
            and _time(row.get("since"), optional=True)
            and (key != "pi_client" or "client" in row["label"].lower())
        ):
            return False
    return True


def validate_live(value: dict, agents_ok) -> None:
    """Raise ValueError unless ``value`` is an exact v3 summary."""
    expected = {"schema_version", "generated_at", "current_plan_revision", "daily_plan", "research_focus",
                "work_items", "waiting_on_you", "question_updates", "accomplishments", "improvements", "agents",
                "warnings", "sources"}
    if set(value) != expected or value["schema_version"] != LIVE_SCHEMA or not _time(value["generated_at"]):
        raise ValueError("v3 summary fields or timestamp are invalid")
    plan = value["daily_plan"]
    if plan is not None:
        review = plan.get("review") if isinstance(plan, dict) else None
        if not (isinstance(plan, dict) and set(plan) == {
                "id", "date", "revision", "path", "sha256", "written_at", "is_current", "week_alignment",
                "bottlenecks", "review"}
                and ((plan["is_current"] and plan["id"] == value["current_plan_revision"])
                     or (not plan["is_current"] and value["current_plan_revision"] is None))
                and _text(plan["id"], 64)
                and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(plan["date"])) and _text(plan["revision"], 12)
                and _text(plan["path"], 200) and re.fullmatch(r"[0-9a-f]{64}", str(plan["sha256"]))
                and _time(plan["written_at"]) and isinstance(plan["is_current"], bool)
                and _text(plan["week_alignment"], 1200, optional=True)
                and isinstance(plan["bottlenecks"], list) and len(plan["bottlenecks"]) <= 5
                and all(_text(b, 400) for b in plan["bottlenecks"])
                and (review is None or (isinstance(review, dict) and set(review) == {
                    "note_msg_id", "sha_matches", "verdict", "review_msg_id", "reviewed_at", "summary",
                    "accepted_items"} and _text(review["note_msg_id"], 80)
                    and isinstance(review["sha_matches"], bool)
                    and review["verdict"] in {None, *VERDICT_STATUS}
                    and _text(review["review_msg_id"], 80, optional=True)
                    and _time(review["reviewed_at"], optional=True)
                    and _text(review["summary"], 400, optional=True)
                    and isinstance(review["accepted_items"], list)
                    and all(_text(i, 40) for i in review["accepted_items"])))):
            raise ValueError("v3 daily plan is invalid")
    elif value["current_plan_revision"] is not None:
        raise ValueError("v3 plan revision without a plan")
    focus = value["research_focus"]
    if not (isinstance(focus, dict) and focus.get("status") in {"selected", "none", "source_invalid"}
            and _time(focus.get("observed_at"))
            and set(focus) <= {"status", "observed_at", "focus_id", "title", "stage", "next_action",
                               "intake_policy", "selected_at", "reason", "last_closure", "closure_error"}
            and all(_text(focus.get(k), 1200, optional=True) for k in (
                "focus_id", "title", "stage", "next_action", "intake_policy", "reason", "closure_error"))
            and _time(focus.get("selected_at"), optional=True)
            and (focus.get("last_closure") is None or (
                isinstance(focus["last_closure"], dict)
                and set(focus["last_closure"]) == {"focus_id", "title", "disposition", "closed_at", "reason",
                                                   "closure_sha256"}
                and _time(focus["last_closure"]["closed_at"], optional=True)
                and all(_text(focus["last_closure"][k], 1200, optional=True)
                        for k in ("focus_id", "title", "disposition", "reason", "closure_sha256"))))):
        raise ValueError("v3 research focus is invalid")
    item_keys = {"id", "goal", "owner", "lane", "repo", "title", "summary", "why_today", "acceptance",
                 "depends_on", "status", "detail", "evidence_msg_id", "evidence_sha", "evidence_at"}
    if not _rows(value["work_items"], item_keys, MAX_WORK_ITEMS, lambda r: (
            r["status"] in WORK_STATUSES and all(_text(r[k], 300) for k in ("id", "goal", "owner", "lane",
                                                                             "repo", "title", "detail"))
            and _text(r["summary"], 90, optional=True)
            and _text(r["why_today"], 1200, optional=True) and _text(r["acceptance"], 1200, optional=True)
            and isinstance(r["depends_on"], list) and all(_text(d, 40) for d in r["depends_on"])
            and _text(r["evidence_msg_id"], 80, optional=True) and _text(r["evidence_sha"], 40, optional=True)
            and _time(r["evidence_at"], optional=True))):
        raise ValueError("v3 work items are invalid")
    if not _rows(value["waiting_on_you"], {"kind", "id", "title", "question", "context", "choices",
                                             "recommendation", "consequence", "asked_by", "asked_at", "msg_id", "cli",
                                             "awaiting_asker", "handoff_msg_id"},
                 MAX_ROWS, lambda r: (
                     r["kind"] in {"question", "owner_decision"} and _text(r["id"], 120)
                     and _text(r["title"], 300) and _text(r["question"], 300)
                     and _text(r["context"], 1200, optional=True)
                     and isinstance(r["choices"], list) and len(r["choices"]) <= 8
                     and all(_text(choice, 300) for choice in r["choices"])
                     and _text(r["recommendation"], 600, optional=True)
                     and _text(r["consequence"], 600, optional=True)
                     and _text(r["asked_by"], 60) and _time(r["asked_at"], optional=True)
                     and _text(r["msg_id"], 80, optional=True) and _text(r["cli"], 600)
                     and type(r["awaiting_asker"]) is bool
                     and _text(r["handoff_msg_id"], 80, optional=True)
                     and (r["awaiting_asker"] == (r["handoff_msg_id"] is not None)))):
        raise ValueError("v3 owner requests are invalid")
    if not _rows(value["question_updates"], {"id", "question_id", "title", "question", "disposition",
                                               "summary", "reason", "blocking_artifact", "resolved_by",
                                               "resolved_at", "evidence_msg_ids"}, 10, lambda r: (
                                                   _text(r["id"], 80) and _text(r["question_id"], 80)
                                                   and _text(r["title"], 300) and _text(r["question"], 300)
                                                   and r["disposition"] in QUESTION_UPDATE_DISPOSITIONS
                                                   and _text(r["summary"], 1200) and _text(r["reason"], 1200)
                                                   and _text(r["blocking_artifact"], 240, optional=True)
                                                   and _text(r["resolved_by"], 60) and _time(r["resolved_at"])
                                                   and isinstance(r["evidence_msg_ids"], list)
                                                   and len(r["evidence_msg_ids"]) <= 8
                                                   and all(_text(value, 80) for value in r["evidence_msg_ids"]))):
        raise ValueError("v3 question updates are invalid")
    if not _rows(value["accomplishments"], {"id", "kind", "title", "at", "evidence"}, MAX_ROWS, lambda r: (
            r["kind"] in {"merged", "validated", "focus_closed", "day_closed"} and _text(r["id"], 120)
            and _text(r["title"], 400) and _time(r["at"]) and _text(r["evidence"], 120))):
        raise ValueError("v3 accomplishments are invalid")
    if not _rows(value["improvements"], {"sha", "at", "subject", "goals"}, MAX_IMPROVEMENTS, lambda r: (
            re.fullmatch(r"[0-9a-f]{7,40}", str(r["sha"])) and _time(r["at"]) and _text(r["subject"], 240)
            and isinstance(r["goals"], list) and all(GOAL.fullmatch(str(g)) for g in r["goals"]))):
        raise ValueError("v3 improvements are invalid")
    sources = value["sources"]
    if not (isinstance(sources, dict) and set(sources) == {"plan", "mailbox", "focus", "git"}
            and all(_time(v, optional=True) for v in sources.values())):
        raise ValueError("v3 source times are invalid")
    warnings = value["warnings"]
    if not (isinstance(warnings, list) and len(warnings) <= 16 and all(_text(w, 512) for w in warnings)):
        raise ValueError("v3 warnings are invalid")
    if not agents_ok(value["agents"]):
        raise ValueError("v3 agent observations are invalid")
