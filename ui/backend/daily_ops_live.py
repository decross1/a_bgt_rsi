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
  mailbox window whose title equals the item title, or names this item's id as a
  whole word and no other id of the same plan.  The window runs from the first
  ``PLAN READY: <date>`` note to the first ``PLAN READY`` note of a later date;
  without a note it starts at the plan file's first revision time.
* ``oracle_dev`` item -> ``READY FOR REVIEW`` notes whose ``ref.branch`` (or, with
  no ref, the title) names ``oracle/<date>-<id>`` (optionally ``-rN``).  The
  newest of those notes and their ``review`` replies decides the verdict;
  "merged" when a local branch head of that name is an ancestor of ``main`` or a
  first-parent ``main`` commit is titled ``Merge oracle/<date>-<id>...``.
* ``owner_decision`` item -> "waiting on you" unless a ``question`` to the owner
  inside the window names the item id (``ref.item`` or a whole-word title
  match); only a direct human ``answer`` or a valid asker/human
  ``question_resolution`` closes it.
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

LIVE_SCHEMA = "daily-ops-summary/v3"
LAB_TZ = ZoneInfo("America/Los_Angeles")  # the daily loop's day (META_ORACLE_DAILY_LOOP §2)
WINDOW_DAYS = 7
MAX_PLAN_BYTES = 262_144
MAX_WORK_ITEMS = 12
MAX_ROWS = 16
MAX_IMPROVEMENTS = 40
CODE_ROOT = Path(__file__).resolve().parents[2]  # the checkout that ships this UI code
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
    return str(_body(row).get("title") or "")


def _human_answer(question: dict, rows: list[dict]) -> dict | None:
    """A card closes as answered only on a direct human reply."""
    answers = [row for row in rows if row.get("kind") == "answer"
               and row.get("in_reply_to") == question.get("msg_id")
               and isinstance(row.get("actor"), str) and row["actor"].startswith("human:")]
    return answers[-1] if answers else None


def _question_resolution(question: dict, rows: list[dict]) -> dict | None:
    """Return the latest valid original-asker/human disposition."""
    oracle_mailbox, _ = _orchestrator()
    for row in reversed(rows):
        if oracle_mailbox.is_valid_question_resolution(question, row, rows):
            return row
    return None


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


def _project_focus(repo: Path) -> dict:
    _, research_focus = _orchestrator()
    return research_focus.project_focus(repo)


class _Git:
    """Read-only git facts about ``main``, cached per (main head, oracle branch heads)."""

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
                log = self._run("log", "--first-parent", "main", "--since=8.days", "-n", "400",
                                "--format=%H%x1f%cI%x1f%s") if self.available else None
                cached = {"log": [line.split("\x1f", 2) for line in (log or "").splitlines()
                                  if line.count("\x1f") == 2],
                          "ancestor": {}}
                _git_cache.clear()  # one repo, one main head: keep the cache bounded
                _git_cache[key] = cached
        self.log = cached["log"]
        self._ancestor = cached["ancestor"]

    def _run(self, *args: str) -> str | None:
        try:
            result = subprocess.run(["git", "-C", str(self.repo), *args], capture_output=True,
                                    text=True, timeout=5, check=False)
        except (OSError, subprocess.SubprocessError):
            return None
        return result.stdout.strip() if result.returncode == 0 else None

    def is_ancestor(self, sha: str) -> bool:
        if not self.available:
            return False
        with _git_lock:
            if sha not in self._ancestor:
                try:
                    code = subprocess.run(["git", "-C", str(self.repo), "merge-base", "--is-ancestor",
                                           sha, self.main], capture_output=True, timeout=5,
                                          check=False).returncode
                except (OSError, subprocess.SubprocessError):
                    code = 1
                self._ancestor[sha] = code == 0
            return self._ancestor[sha]


# -- derivations ---------------------------------------------------------------

def current_plan(repo: Path) -> tuple[str, dict] | None:
    """(plan id, plan) of the plan of record, or None; an unreadable newest plan raises."""
    plans = plan_files(Path(repo))
    if not plans:
        return None
    name = plans[max(plans)][-1][1]
    return name[:-5], _load_plan(Path(repo), name)[0]


def plan_windows(rows: list[dict]) -> dict[str, tuple[int, float]]:
    """date -> [first PLAN READY seq for that date, first PLAN READY seq of a later date)."""
    firsts: dict[str, int] = {}
    for row in rows:
        match = PLAN_READY.match(_title(row)) if row.get("kind") == "note" else None
        if match:
            firsts.setdefault(match.group(1), row["seq"])
    ordered = sorted(firsts.items(), key=lambda pair: pair[0])
    windows = {}
    for index, (date, start) in enumerate(ordered):
        later = [seq for _, seq in ordered[index + 1:]]
        windows[date] = (start, min(later) if later else float("inf"))
    return windows


def _window(rows: list[dict], windows: dict, date: str, first_written: datetime | None):
    if date in windows:
        return windows[date]
    start = next((row["seq"] for row in rows if first_written and _when(row.get("ts"))
                  and _when(row["ts"]) >= first_written), float("inf"))
    return (start, float("inf"))


def plan_review(rows: list[dict], name: str, sha256: str) -> dict | None:
    path = f"run_state/daily_plans/{name}"
    notes = [row for row in rows if row.get("kind") == "note" and PLAN_READY.match(_title(row))
             and _ref(row).get("path") == path]
    if not notes:
        return None
    note = notes[-1]
    reviews = [row for row in rows if row.get("kind") == "review" and row.get("in_reply_to") == note["msg_id"]]
    review = reviews[-1] if reviews else None
    body = _body(review) if review else {}
    accepted = body.get("accepted_items") if isinstance(body.get("accepted_items"), list) else []
    return {
        "note_msg_id": note["msg_id"],
        "sha_matches": _ref(note).get("sha256") == sha256,
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
        detail += f"; meta review {_body(reviews[-1]).get('verdict')} ({reviews[-1]['msg_id']})"
    sha = body.get("head_sha") if isinstance(body.get("head_sha"), str) else None
    return status, detail + ".", last["msg_id"], (sha or "")[:12] or None, _stamp(last.get("ts"))


def _oracle_item(item, date, rows, git):
    branch = re.compile(rf"oracle/{re.escape(date)}-{re.escape(item['id'])}(?:-r\d+)?(?![\w-])")
    ready = [row for row in rows if row.get("kind") == "note" and _title(row).startswith("READY FOR REVIEW")
             and (branch.fullmatch(str(_ref(row).get("branch"))) if _ref(row).get("branch")
                  else branch.search(_title(row)))]
    ready_ids = {row["msg_id"] for row in ready}
    reviews = [row for row in rows if row.get("kind") == "review" and row.get("in_reply_to") in ready_ids]
    if item.get("repo", "a_bgt_rsi") == "a_bgt_rsi":
        for sha, when, subject in git.log:
            if re.match(r"Merge (?:branch ')?" + branch.pattern, subject):
                return "merged", _clip(subject, 200), None, sha[:12], _stamp(when)
        for name, sha in sorted(git.heads.items()):
            if branch.fullmatch(name) and git.is_ancestor(sha):
                return "merged", f"Branch {name} is on main.", None, sha[:12], None
    if not ready:
        heads = [name for name in git.heads if branch.fullmatch(name)]
        if heads:
            return "building", f"Branch {heads[-1]} exists; no READY FOR REVIEW note yet.", None, None, None
        return "not_started", "No branch or READY FOR REVIEW note yet.", None, None, None
    note, review = ready[-1], (reviews[-1] if reviews else None)
    if review is None or review["seq"] < note["seq"]:
        return "awaiting_review", _clip(_title(note), 200), note["msg_id"], None, _stamp(note.get("ts"))
    verdict = _body(review).get("verdict")
    return (VERDICT_STATUS.get(verdict, "awaiting_review"),
            f"Meta-oracle {verdict}: {_clip(_body(review).get('summary'), 200) or _title(note)}",
            review["msg_id"], None, _stamp(review.get("ts")))


def _owner_question(item, ids, rows, window):
    asked = [row for row in rows if row.get("kind") == "question" and row.get("to") == "owner"
             and window[0] <= row["seq"] < window[1]
             and (_ref(row).get("item") == item["id"]
                  or {i for i in ids if _word(i, _title(row))} == {item["id"]})]
    return asked[-1] if asked else None


def work_items(plan: dict, rows: list[dict], windows: dict, git: _Git, now: datetime,
               first_written: datetime | None) -> tuple[list[dict], dict]:
    """One row per plan item, and the owner questions those items already claim."""
    oracle_mailbox, _ = _orchestrator()
    folded = oracle_mailbox.fold(rows, now)
    date = plan["date"]
    ids = [item["id"] for item in plan["items"]]
    window = _window(rows, windows, date, first_written)
    result, claimed = [], {}
    for item in plan["items"][:MAX_WORK_ITEMS]:
        lane = item.get("lane")
        if lane == "nara_dev":
            status, detail, msg, sha, at = _nara_item(item, ids, rows, window, folded)
        elif lane == "oracle_dev":
            status, detail, msg, sha, at = _oracle_item(item, date, rows, git)
        elif lane == "owner_decision":
            question = _owner_question(item, ids, rows, window)
            if question is not None:
                claimed[question["msg_id"]] = item["id"]
            answer = _human_answer(question, rows) if question is not None else None
            resolution = _question_resolution(question, rows) if question is not None else None
            if answer is not None:
                status = "answered"
                detail = f"Owner question {question['msg_id']} has a direct human answer {answer['msg_id']}."
                msg, at = answer["msg_id"], _stamp(answer.get("ts"))
            elif resolution is not None:
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
                status = "waiting_on_you"
                detail, msg, at = "No owner question posted for this item; reply with a note.", None, None
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


def waiting_on_you(plan_id: str | None, items: list[dict], claimed: dict, rows: list[dict],
                   plan_written: str | None) -> list[dict]:
    by_id = {row["msg_id"]: row for row in rows}
    waiting = []
    for item in items:
        if item["status"] != "waiting_on_you":
            continue
        msg = item["evidence_msg_id"]
        question = by_id.get(msg) if msg else None
        if (question is not None and (_human_answer(question, rows) is not None
                                     or _question_resolution(question, rows) is not None)):
            continue
        card = _question_card(question) if question is not None else {
            "title": item["title"], "question": item["title"], "context": None,
            "choices": [], "recommendation": None, "consequence": None,
        }
        cli = (f"{CLI} --kind answer --to {_reply_to(question)} --in-reply-to {msg} "
               f"--body '{{\"text\": \"...\"}}'" if msg
               else f"{CLI} --kind note --to oracle --body '{{\"text\": \"{plan_id} {item['id']}: ...\"}}'")
        waiting.append({"kind": "owner_decision", "id": f"{plan_id}:{item['id']}", **card,
                        "asked_by": _reply_to(question) if question else "oracle",
                        "asked_at": item["evidence_at"] or plan_written, "msg_id": msg, "cli": cli})
    for row in rows:
        if (row.get("kind") != "question" or row.get("to") != "owner" or row["msg_id"] in claimed
                or _human_answer(row, rows) is not None or _question_resolution(row, rows) is not None):
            continue
        to = _reply_to(row)
        card = _question_card(row)
        waiting.append({
            "kind": "question", "id": row["msg_id"],
            **card,
            "asked_by": _clip(str(row.get("actor")), 60) or "?", "asked_at": _stamp(row.get("ts")),
            "msg_id": row["msg_id"],
            "cli": f"{CLI} --kind answer --to {to} --in-reply-to {row['msg_id']} --body '{{\"text\": \"...\"}}'",
        })
    return waiting[:MAX_ROWS]


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
                    plans: dict) -> list[dict]:
    since = now - timedelta(days=WINDOW_DAYS)
    found = []
    oldest = (now.astimezone(LAB_TZ) - timedelta(days=WINDOW_DAYS)).date().isoformat()
    for date, revisions in plans.items():
        if date < oldest:
            continue
        try:
            plan, _, written = _load_plan(repo, revisions[-1][1])
            first = datetime.fromtimestamp(
                os.stat(repo / "run_state" / "daily_plans" / revisions[0][1]).st_mtime, timezone.utc)
        except (OSError, ValueError):
            continue
        items, _ = work_items(plan, rows, windows, git, now, first)
        for item in items:
            if item["status"] in {"merged", "validated"}:
                evidence = item["evidence_sha"] or item["evidence_msg_id"] or revisions[-1][1]
                found.append({"id": f"{date}:{item['id']}", "kind": item["status"],
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


def build(repo: Path, now: datetime) -> dict:
    """Every v3 summary field except ``agents``; failures become warnings, never old content."""
    repo = Path(repo)
    warnings: list[str] = []
    try:
        rows = _mailbox(repo)
        mailbox_error = None
    except Exception as exc:  # a broken hash chain is shown, not papered over
        rows, mailbox_error = [], _clip(f"{type(exc).__name__}: {exc}", 200)
        warnings.append(f"Lab mailbox is unreadable ({mailbox_error}); work statuses are not derived.")
    git = _Git(repo)
    if not git.available:
        warnings.append("Read-only git on main is unavailable; merged status and improvements are not derived.")
    plans = plan_files(repo)
    windows = plan_windows(rows)
    daily_plan, items, claimed, plan_id = None, [], {}, None
    if plans:
        date = max(plans)
        revision, name = plans[date][-1]
        try:
            plan, sha, written = _load_plan(repo, name)
            first = datetime.fromtimestamp(os.stat(repo / "run_state" / "daily_plans" / plans[date][0][1]).st_mtime,
                                           timezone.utc)
            plan_id = name[:-5]
            bottlenecks = plan.get("bottlenecks") if isinstance(plan.get("bottlenecks"), list) else []
            daily_plan = {
                "id": plan_id, "date": date, "revision": f"r{revision}", "path": f"run_state/daily_plans/{name}",
                "sha256": sha, "written_at": _iso(written),
                "is_current": date >= now.astimezone(LAB_TZ).date().isoformat(),
                "week_alignment": _clip(plan.get("week_alignment"), 1200),
                "bottlenecks": [text for text in (_clip(b.get("what"), 400) for b in bottlenecks[:5]
                                                  if isinstance(b, dict)) if text],
                "review": plan_review(rows, name, sha),
            }
            if not mailbox_error:
                items, claimed = work_items(plan, rows, windows, git, now, first)
        except (OSError, ValueError) as exc:
            warnings.append(_clip(f"Newest daily plan {name} is unreadable: {exc}", 480))
    newest_row = _stamp(rows[-1].get("ts")) if rows else None
    focus = research_focus(repo, now)
    return {
        "schema_version": LIVE_SCHEMA,
        "generated_at": _iso(now),
        "current_plan_revision": plan_id if daily_plan else None,
        "daily_plan": daily_plan,
        "research_focus": focus,
        "work_items": items,
        "waiting_on_you": waiting_on_you(plan_id, items, claimed, rows,
                                         daily_plan["written_at"] if daily_plan else None),
        "accomplishments": accomplishments(repo, rows, windows, git, now, plans),
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
    value = build(repo, now)
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


def validate_live(value: dict, agents_ok) -> None:
    """Raise ValueError unless ``value`` is an exact v3 summary."""
    expected = {"schema_version", "generated_at", "current_plan_revision", "daily_plan", "research_focus",
                "work_items", "waiting_on_you", "accomplishments", "improvements", "agents",
                "warnings", "sources"}
    if set(value) != expected or value["schema_version"] != LIVE_SCHEMA or not _time(value["generated_at"]):
        raise ValueError("v3 summary fields or timestamp are invalid")
    plan = value["daily_plan"]
    if plan is not None:
        review = plan.get("review") if isinstance(plan, dict) else None
        if not (isinstance(plan, dict) and set(plan) == {
                "id", "date", "revision", "path", "sha256", "written_at", "is_current", "week_alignment",
                "bottlenecks", "review"}
                and plan["id"] == value["current_plan_revision"] and _text(plan["id"], 64)
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
                                             "recommendation", "consequence", "asked_by", "asked_at", "msg_id", "cli"},
                 MAX_ROWS, lambda r: (
                     r["kind"] in {"question", "owner_decision"} and _text(r["id"], 120)
                     and _text(r["title"], 300) and _text(r["question"], 300)
                     and _text(r["context"], 1200, optional=True)
                     and isinstance(r["choices"], list) and len(r["choices"]) <= 8
                     and all(_text(choice, 300) for choice in r["choices"])
                     and _text(r["recommendation"], 600, optional=True)
                     and _text(r["consequence"], 600, optional=True)
                     and _text(r["asked_by"], 60) and _time(r["asked_at"], optional=True)
                     and _text(r["msg_id"], 80, optional=True) and _text(r["cli"], 600))):
        raise ValueError("v3 owner requests are invalid")
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
