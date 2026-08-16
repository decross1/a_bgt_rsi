"""The coordinator BRAIN — assess -> plan -> validate -> dispatch.

Slice-Alpha proof that an LLM can *coordinate* the apparatus (decide what to
run next) WITHOUT being trusted to free-form sequence it. The guardrail is the
constrained action space in orchestrator.coordinator_actions: the planner may
ONLY choose actions from the fixed validated menu; an off-menu, malformed, or
over-budget plan is rejected and re-planned (bounded retries) and NEVER
executed.

This is BUILT ALONGSIDE the proven scripted orchestrator.nara.run_iteration,
which stays the DEFAULT and is NOT modified. The coordinator is opt-in: it runs
only via its own CLI (`python -m orchestrator.coordinator --once`). Importing or
running it does NOT affect nara's default path.

Alpha guardrails baked in here:
  - a single --once cycle (NOT continuous),
  - DRY-RUN by default (plan only, no execution); --execute required to dispatch,
  - constrained action space + bounded replan as the safety envelope,
  - no live trades anywhere (the menu has no such action).

Reuses, never reinvents:
  - agent_wrapper.wrapper.call_sync     — the ONE plan LLM call (low temp),
  - orchestrator.coordinator_actions    — known_actions() + validate_plan(),
  - orchestrator.nara.run_iteration     — the run_loop_iteration handler,
  - orchestrator.finding_promotion.promote_findings — the promote handler,
  - orchestrator.tier_registry          — experiments discovery,
  - orchestrator.active_run + wrapper.set_run_id — instrumentation adoption,
  - the meta_review tail-read + call_sync + balanced-brace JSON-extract pattern.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from agent_wrapper.wrapper import call_sync, set_run_id
from orchestrator import active_run, coordinator_cycle_log, tier_registry
from orchestrator.coordinator_actions import known_actions, validate_plan
from orchestrator.morning_topic import pick_morning_topic
from orchestrator.runtime import append_run_log, set_current_agent

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOOP_MEMORY = REPO_ROOT / "memory" / "loop_memory.jsonl"
DEFAULT_SURFACED = REPO_ROOT / "memory" / "surfaced_findings.jsonl"
DEFAULT_FEEDBACK = REPO_ROOT / "memory" / "loop_feedback.jsonl"
DEFAULT_ACTIVE_RUN = REPO_ROOT / "run_state" / "active_run.json"
DEFAULT_COORDINATOR_BUBBLES = REPO_ROOT / "memory" / "coordinator_bubbles.jsonl"
DEFAULT_FOLLOWUPS = REPO_ROOT / "memory" / "finding_followups.jsonl"
DEFAULT_NEAR_MISSES = REPO_ROOT / "memory" / "promotion_near_misses.jsonl"
DEFAULT_IDEA_LEDGER = REPO_ROOT / "memory" / "idea_ledger.jsonl"
# Pause file: when present, every cycle refuses to run (β kill switch,
# D-049). Checked BEFORE any registration or LLM call.
PAUSE_PATH = REPO_ROOT / "run_state" / "pause_coordinator"
# Daily executed-cycle budget ledger (β bound, D-049): one row per
# EXECUTED cycle {date, run_id, spent}; a new execute cycle refuses when
# today's total would exceed the cap. Dry-runs are never charged.
BUDGET_LEDGER_PATH = REPO_ROOT / "run_state" / "coordinator_budget.jsonl"
# D-063 (2026-08-15, owner-ratified): 18 -> 60 for hourly/always-on cadence
# (24 cycles x ~2.5 avg cost; ~50 min GPU/day). Env-overridable as before.
DAILY_BUDGET_CAP = int(os.environ.get("COORDINATOR_DAILY_CAP", "60"))
# The cap is a DAY's budget, but first-come-first-served spends it by late
# morning: the 2026-08-16 cadence (hourly cron + the 30-min daemon heartbeat,
# both picking the 3-unit run_loop_iteration every time) burned 57/60 across 19
# cycles by 11:00, and the next NINE hourly cycles produced nothing but empty
# "no valid plan (daily_budget_exhausted)" rows. The 2.5-average the cap was
# sized on never materialised — the planner has never once chosen a cheaper
# action. So the allowance now GROWS WITH THE CLOCK: a cycle may spend only up
# to the day's elapsed share, which paces the lab across all 24 hours instead
# of racing to exhaustion and idling for 13. The floor keeps the first cycle
# of the day runnable.
BUDGET_PACING = os.environ.get("COORDINATOR_BUDGET_PACING", "1") != "0"

# ACTIVITY PORTFOLIO (owner directive 2026-08-16): "some time on ideation and
# debate, some time progressing current research across their stages, some time
# evaluating what is wrong with the system and delegating to a dev team, and
# some time on review/SDLC." One undifferentiated pool does not produce that —
# on 2026-08-16 the planner spent 100% of the day's 60 units on ideation, all
# 19 cycles on ONE topic, and touched no other class. Each class now draws from
# its OWN daily share, so exhausting ideation cannot starve research, system
# work, or SDLC: it just means today's ideation is done.
#
# Nara still chooses WHAT to do inside a class; the portfolio only decides how
# much of the day each class may have. Shares are fractions of DAILY_BUDGET_CAP
# and are env-overridable per class.
ACTIVITY_CLASS_OF = {
    "run_loop_iteration": "ideation",
    "mine_paper_gap": "ideation",
    "refine_idea": "ideation",      # the amend half of propose->kill->amend
    "bubble_up": "research",
    "promote_findings": "research",
    "run_experiment": "research",
    "forecast_markets": "research",
    "improve_system": "system",
    "noop": "free",                 # costs 0; never charged to a class
}
ACTIVITY_SHARES = {
    "ideation": float(os.environ.get("COORDINATOR_SHARE_IDEATION", "0.40")),
    "research": float(os.environ.get("COORDINATOR_SHARE_RESEARCH", "0.35")),
    "system": float(os.environ.get("COORDINATOR_SHARE_SYSTEM", "0.15")),
    "sdlc": float(os.environ.get("COORDINATOR_SHARE_SDLC", "0.10")),
}


def activity_budget_state() -> dict[str, dict[str, int]]:
    """Per-class {spent, share, remaining} for today — the planner reads this
    so it stops planning into a class whose day is done (an all-skipped plan
    is another empty cycle on the dashboard)."""
    spent = _daily_spent_by_class()
    out: dict[str, dict[str, int]] = {}
    for cls in ACTIVITY_SHARES:
        share = class_allowance(cls)
        used = spent.get(cls, 0)
        out[cls] = {"spent": used, "share": share,
                    "remaining": max(0, share - used)}
    return out


def activity_class(action_name: str) -> str:
    """The portfolio class an action draws from. An UNMAPPED action is a
    contract gap, not an excuse to spend from nowhere — it charges to
    'ideation', the largest share, and says so in the ledger row."""
    return ACTIVITY_CLASS_OF.get(action_name, "ideation")


def class_allowance(cls: str, *, cap: int | None = None) -> int:
    """This class's slice of the daily cap (floor 0; unknown class -> 0)."""
    cap = DAILY_BUDGET_CAP if cap is None else cap
    return int(cap * ACTIVITY_SHARES.get(cls, 0.0))

CALLS_LOG_PATH = os.environ.get("LOOP_V0_CALLS_LOG", "logs/calls.jsonl")

# How many recent loop_memory rows the assessment digests.
_RECENT_N = 8
# Bounded replan retries (after the first plan attempt). <= 2 per the contract.
_MAX_REPLANS = 2

# Escalation taxonomy (kind) — A=judgment, B=blocking-halt, C=read-receipt.
# Legacy finding-id bubbles are read-receipts (C). The COUNT CONTRACT the
# dashboard idle-hero renders against: actionable escalations = kind A or B
# ONLY, never C (a read-receipt is not unresolved work) — see
# count_actionable_escalations. Schema: schema/escalation.schema.json.
ESCALATION_KINDS = ("A", "B", "C")
ACTIONABLE_ESCALATION_KINDS = ("A", "B")
# The 6 resolution outcomes a generic escalation may permit (seam 3).
ALLOWED_ESCALATION_ACTIONS = (
    "sign_off", "reject", "refine_defer",
    "refine_authorize_fix", "spawn_topic", "abstain",
)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _budget_allowance(now: "datetime | None" = None,
                     cap: int | None = None,
                     floor: int = 3) -> int:
    """Today's spendable budget SO FAR — the elapsed share of the daily cap.

    At 00:00 this is `floor` (one cycle, so the day can start); at 23:59 it is
    the full cap. Pacing is disabled with COORDINATOR_BUDGET_PACING=0, in which
    case the whole cap is available immediately (the pre-2026-08-16 behaviour).
    """
    cap = DAILY_BUDGET_CAP if cap is None else cap
    if not BUDGET_PACING:
        return cap
    now = now or datetime.now(timezone.utc)
    elapsed = (now.hour * 3600 + now.minute * 60 + now.second) / 86400.0
    return max(floor, min(cap, int(cap * elapsed) + floor))


def _daily_spent(
    *, path: str | os.PathLike | None = None, today: str | None = None,
) -> int:
    """Sum of `spent` over today's rows in the daily budget ledger.
    Missing/malformed file -> 0. path=None resolves at call time."""
    if path is None:
        path = BUDGET_LEDGER_PATH
    if today is None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    total = 0
    for row in _read_jsonl(path):
        if row.get("date") == today and isinstance(row.get("spent"), int):
            total += row["spent"]
    return total


def _daily_spent_by_class(
    *, path: str | os.PathLike | None = None, today: str | None = None,
) -> dict[str, int]:
    """Today's spend per activity class. Rows written before the portfolio
    existed carry no by_class map; they are counted under 'ideation', which is
    what they in fact were — not silently dropped."""
    if path is None:
        path = BUDGET_LEDGER_PATH
    if today is None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out: dict[str, int] = {}
    for row in _read_jsonl(path):
        if row.get("date") != today:
            continue
        by = row.get("by_class")
        if isinstance(by, dict):
            for cls, amount in by.items():
                if isinstance(amount, int):
                    out[cls] = out.get(cls, 0) + amount
        elif isinstance(row.get("spent"), int):
            out["ideation"] = out.get("ideation", 0) + row["spent"]
    return out


def _charge_daily_ledger(
    run_id: str, spent: int, *, path: str | os.PathLike | None = None,
    by_class: dict[str, int] | None = None,
) -> None:
    """Append one executed-cycle charge row. Append-only; never raises."""
    if path is None:
        path = BUDGET_LEDGER_PATH
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a") as fh:
            fh.write(json.dumps({
                "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "timestamp": _utcnow_iso(),
                "run_id": run_id,
                "spent": int(spent),
                "by_class": {k: int(v) for k, v in (by_class or {}).items()},
            }, ensure_ascii=False) + "\n")
    except Exception:
        return


# ── instrumentation readers (pure, never raise) ──────────────────────────


def _read_jsonl(path: str | os.PathLike) -> list[dict[str, Any]]:
    """Read a JSONL file into a list of dicts. Missing file / unreadable -> [].
    Skips blank and malformed lines (mirrors workers.meta_review._read_jsonl)."""
    rows: list[dict[str, Any]] = []
    try:
        p = Path(path)
        if not p.exists():
            return rows
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                rows.append(obj)
    except Exception:
        return rows
    return rows


def _read_json(path: str | os.PathLike) -> dict[str, Any] | None:
    """Read a single JSON object. Missing / unreadable / malformed -> None."""
    try:
        p = Path(path)
        if not p.exists():
            return None
        obj = json.loads(p.read_text())
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _sub(row: dict[str, Any], key: str) -> dict[str, Any]:
    """row[key] when a dict, else {} (mirrors workers.meta_review._sub)."""
    v = row.get(key)
    return v if isinstance(v, dict) else {}


def _extract_json(text: str) -> Any | None:
    """Find the first balanced JSON object OR array in `text` and parse it.

    Mirrors workers.meta_review._extract_json_object but also handles a
    top-level JSON array (the plan is a list). Scans for the first `{` or `[`
    and finds its matching close by counting brackets (string-aware)."""
    if not isinstance(text, str):
        return None
    opens = {"{": "}", "[": "]"}
    start = -1
    open_ch = ""
    for i, ch in enumerate(text):
        if ch in opens:
            start = i
            open_ch = ch
            break
    if start < 0:
        return None
    close_ch = opens[open_ch]
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


# ── assess ────────────────────────────────────────────────────────────────


def _topic_suggestions(
    loop_memory_path: str | os.PathLike,
    *,
    followups_path: str | os.PathLike | None = None,
) -> list[dict[str, str]]:
    """Topic candidates for the planner. Never raises; degrades to [] so
    assess_state stays a pure read. Surfacing this is what un-blinds the
    planner — run_loop_iteration's arg_schema requires a non-empty topic.

    Sources, in order: (1) up to 2 queued human follow-up topics from
    memory/finding_followups.jsonl (written by finding_session's
    spawn_topic outcome; this read closes the orphaned-queue gap — the
    queue finally has a consumer); (2) the morning pick (newest arXiv
    paper, else a loop-memory gap probe, else a safe fallback).
    followups_path=None resolves at call time (patchable)."""
    if followups_path is None:
        followups_path = DEFAULT_FOLLOWUPS
    out: list[dict[str, str]] = []
    # (0) D-060 agenda-first: open idea-ledger agenda items lead. The agenda
    # carries provenance (what opened it), so topic selection advances the
    # program instead of chasing the day's arXiv draw. Missing/empty ledger
    # degrades silently — pre-consolidation state is legitimate.
    try:
        from workers.idea_ledger import load_state
        from workers.idea_projection import agenda_topics
        for item in agenda_topics(load_state(DEFAULT_IDEA_LEDGER))[:3]:
            # cluster_id RIDES ALONG so a dispatched agenda topic can be
            # marked consumed. Without it the item stayed open forever: 26 of
            # the 30 executed cycles to 2026-08-16 ran the SAME topic, because
            # agenda_topics kept returning it and the planner is instructed to
            # take an agenda topic verbatim. Zero agenda_item_consumed events
            # existed in 251 ledger events.
            out.append({"topic": item["topic"], "source": "agenda",
                        "cluster_id": item.get("cluster_id")})
    except Exception:
        pass
    for row in _read_jsonl(followups_path)[-2:]:
        topic = row.get("new_topic")
        if isinstance(topic, str) and topic.strip():
            # graft 4 (P4): machine-mined rows share this queue but must NOT
            # masquerade as human follow-ups (which the planner prefers below).
            src = ("coordinator_propose"
                   if row.get("origin") == "coordinator_propose"
                   else "finding_followup")
            out.append({"topic": topic, "source": src})
    # The morning arXiv pick is the LAST resort — an agenda candidate, not
    # the program driver (D-060; the Jul-Aug seed churn came from here).
    try:
        topic, source = pick_morning_topic(loop_memory_path=loop_memory_path)
        out.append({"topic": topic, "source": source})
    except Exception:
        pass
    return out


def _consume_agenda_topic(topic: Any, state: dict[str, Any] | None) -> None:
    """Mark a dispatched agenda topic CONSUMED so it stops leading the queue.

    Nothing wrote this event before 2026-08-16: `agenda_topics` correctly skips
    consumed items, but no consumer existed, so the same item led every cycle —
    26 of 30 executed cycles ran one topic. Fail-open (a ledger write must
    never break a cycle that already did its work), and only for a topic that
    really came from an agenda suggestion carrying its cluster_id."""
    if not isinstance(topic, str) or not topic.strip():
        return
    suggestions = (state or {}).get("topic_suggestions") or []
    match = next(
        (sg for sg in suggestions
         if isinstance(sg, dict) and sg.get("source") == "agenda"
         and sg.get("topic") == topic and sg.get("cluster_id")),
        None)
    if match is None:
        return
    try:
        from workers.idea_ledger import append_event
        append_event(DEFAULT_IDEA_LEDGER, {
            "event_type": "agenda_item_consumed",
            "ts": _utcnow_iso(),
            "cluster_id": match["cluster_id"],
            "topic": topic,
        })
    except Exception:
        return


def _killed_member_ids() -> set:
    """Member ids of KILLED idea-ledger clusters (memoization-free pure read;
    absent/unreadable ledger -> empty set, fail-open)."""
    try:
        from workers.idea_ledger import load_state
        state = load_state(DEFAULT_IDEA_LEDGER)
    except Exception:
        return set()
    out: set = set()
    for c in state.values():
        if c.get("status") == "killed":
            for m in c.get("members") or []:
                out.add(m)
                if isinstance(m, str) and m.startswith("sf-"):
                    out.add(m[3:])
    return out


def assess_state(
    *,
    loop_memory_path: str | os.PathLike = DEFAULT_LOOP_MEMORY,
    surfaced_path: str | os.PathLike = DEFAULT_SURFACED,
    feedback_path: str | os.PathLike = DEFAULT_FEEDBACK,
    active_run_path: str | os.PathLike = DEFAULT_ACTIVE_RUN,
    recent_n: int = _RECENT_N,
) -> dict[str, Any]:
    """Read the instrumentation and return a compact structured snapshot.

    Pure reads. NEVER raises — any missing/partial source degrades to an
    empty/partial section so the planner still gets a usable (if thin) picture.

    Returns:
        {
          "in_flight": {"active": bool, "run": {run_id, kind, label} | None},
          "recent_findings": [ {iteration_id, hypothesis, novelty, critic,
                                 experiment_outcome, gate_status, human_verdict} ],
          "open_threads": [iteration_id, ...],   # recent, no human verdict yet
          "gaps": [str, ...],                     # what's thin / worth doing
          "surfaced_pending": [ {finding_id, title, status} ],  # awaiting review
          "experiments": {tier: count, ...},
          "topic_suggestions": [ {topic, source} ],  # morning-loop candidate(s)
        }
    """
    # --- in-flight: is a run live right now? ---
    ar = _read_json(active_run_path)
    if ar is not None:
        in_flight = {
            "active": True,
            "run": {
                "run_id": ar.get("run_id"),
                "kind": ar.get("kind"),
                "label": ar.get("label"),
            },
        }
    else:
        in_flight = {"active": False, "run": None}

    # --- recent loop iterations + their human verdicts ---
    rows = _read_jsonl(loop_memory_path)
    feedback = {
        f["iteration_id"]: f
        for f in _read_jsonl(feedback_path)
        if isinstance(f.get("iteration_id"), str)
    }
    recent = rows[-max(int(recent_n), 1):] if rows else []

    recent_findings: list[dict[str, Any]] = []
    open_threads: list[str] = []
    for r in recent:
        iid = r.get("iteration_id")
        if not isinstance(iid, str):
            continue
        exp = _sub(r, "experiment_outcome")
        human_verdict = (feedback.get(iid) or {}).get("verdict")
        recent_findings.append({
            "iteration_id": iid,
            "hypothesis": str(_sub(r, "hypothesis").get("text") or "")[:300],
            "novelty": _sub(r, "novelty").get("class"),
            "critic": _sub(r, "critique").get("verdict"),
            "experiment_outcome": (
                str(exp.get("summary") or "")[:200] if exp else None
            ),
            "gate_status": r.get("gate_status"),
            "human_verdict": human_verdict,
        })
        # An "open thread" = a recent iteration with no human verdict yet —
        # EXCLUDING members of killed clusters (D-059: the ladder already
        # disposed of them; a gate verdict on a dead cluster's iteration is
        # not owed). Ledger absent -> no exclusion (fail-open).
        if human_verdict is None and r.get("gate_status") == "pending":
            if iid not in _killed_member_ids():
                open_threads.append(iid)

    # --- surfaced findings awaiting review (D-059 bar-aware) ---
    # Only findings that CLEARED the ladder bar (evidence_level L4/L5) await
    # the human; legacy pre-ladder rows (no evidence_level — the demoted 31)
    # are counted separately as information, never as owed attention. This
    # was the "clear the 31 findings" echo the channel kept recommending
    # after consolidation had already demoted them (owner-reported
    # 2026-08-15).
    surfaced_pending: list[dict[str, Any]] = []
    surfaced_below_bar = 0
    for sf in _read_jsonl(surfaced_path):
        status = sf.get("status")
        if status not in ("surfaced", "in_review"):
            continue
        if sf.get("evidence_level") in ("L4", "L5"):
            surfaced_pending.append({
                "finding_id": sf.get("finding_id"),
                "title": str(sf.get("title") or "")[:200],
                "status": status,
                "evidence_level": sf.get("evidence_level"),
            })
        else:
            surfaced_below_bar += 1

    # --- experiments discovery (filesystem inspection only) ---
    try:
        experiments = tier_registry.tiers_status()
    except Exception:
        experiments = {}

    # --- gaps: a short, derived list of what's thin or pending ---
    gaps: list[str] = []
    if not rows:
        gaps.append("no loop iterations recorded yet")
    if open_threads:
        gaps.append(
            f"{len(open_threads)} recent iteration(s) await a human gate verdict"
        )
    if surfaced_pending:
        gaps.append(
            f"{len(surfaced_pending)} surfaced finding(s) await human review"
        )
    # Below-bar legacy findings are INFORMATION, not a gap of any kind —
    # they ride in the state as `surfaced_below_bar` (see return) so the
    # planner/channel can mention them without the daemon's work_exists or
    # the planner reading them as owed work.
    # novel-but-unpromoted: a recent novel+survives iteration with no surfaced row.
    surfaced_src = {
        sf.get("source_iteration_id") for sf in _read_jsonl(surfaced_path)
    }
    # D-059: novel+surviving is NOT promotable on its own — promote_findings
    # defers anything below L3 (the vote IS the L3->L4 rung). Reporting the
    # bare novel+surviving count invited the planner to spend a slot on a
    # promotion pass that provably could not promote, producing a genuine
    # no-op cycle (caught red by the stall detector 2026-08-15T23:00Z). Only
    # vote-ready (L3) iterations are an actionable promotion gap.
    _rows_by_id = {r.get("iteration_id"): r for r in recent
                   if isinstance(r.get("iteration_id"), str)}
    novel_unpromoted: list[str] = []
    try:
        from workers.evidence_ladder import derive_level
        for f in recent_findings:
            iid = f["iteration_id"]
            if (f["novelty"] != "novel" or f["critic"] != "survives"
                    or iid in surfaced_src):
                continue
            row = _rows_by_id.get(iid)
            if row is None:
                continue
            if derive_level(row, feedback.get(iid), None, [])["level"] == "L3":
                novel_unpromoted.append(iid)
    except Exception:
        novel_unpromoted = []
    if novel_unpromoted:
        gaps.append(
            f"{len(novel_unpromoted)} iteration(s) at L3 are vote-ready for "
            "promotion (novel + survives + replication)"
        )

    # --- D-059/P0 un-zombie gaps: staleness + ladder-owed tests. These are
    # the gaps that never starve: "await human" gaps saturate and freeze the
    # planner (the 2026-08-05..14 fixed point); these two always argue for
    # doing research. Pure reads; failures degrade silently. ---
    try:
        from datetime import datetime, timezone
        from orchestrator.loop_health import staleness_gap
        stale = staleness_gap(rows, datetime.now(timezone.utc))
        if stale:
            gaps.append(stale)
    except Exception:
        pass
    try:
        from orchestrator.loop_health import ladder_gaps
        from workers.idea_ledger import load_state
        gaps.extend(ladder_gaps(load_state(DEFAULT_IDEA_LEDGER)))
    except Exception:
        pass

    return {
        "in_flight": in_flight,
        "recent_findings": recent_findings,
        "open_threads": open_threads,
        "gaps": gaps,
        "surfaced_pending": surfaced_pending,
        "surfaced_below_bar": surfaced_below_bar,
        "experiments": experiments,
        "topic_suggestions": _topic_suggestions(loop_memory_path),
        "activity_budget": activity_budget_state(),
    }


# ── plan ────────────────────────────────────────────────────────────────


def _planner_system_prompt(budget: int) -> str:
    menu = known_actions()
    return (
        "You are the COORDINATOR brain of the a_bgt_rsi research apparatus.\n"
        "Given a snapshot of the apparatus state, decide what to do NEXT by\n"
        "emitting a short ordered PLAN.\n"
        "\n"
        "HARD CONSTRAINT — you may ONLY use actions from this fixed menu. Any\n"
        "action name not on this menu, any unlisted argument, or a plan over\n"
        f"the budget of {budget} cost units will be REJECTED and you will be\n"
        "asked to re-plan. Do NOT invent actions. The menu:\n"
        f"{json.dumps(menu, indent=2)}\n"
        "\n"
        "Choose the smallest plan that advances the research: e.g. run a loop\n"
        "iteration on a worthwhile topic, promote vetted findings, bubble up a\n"
        "specific finding for the human, or noop with a reason if nothing is\n"
        "worth doing. When the state's 'topic_suggestions' is non-empty and a\n"
        "loop iteration is worthwhile, use a suggested topic VERBATIM as the\n"
        "run_loop_iteration 'topic' arg (it is a real candidate already vetted\n"
        "for scope). Topic preference order: source 'agenda' (the research\n"
        "program's own open questions — advancing these IS the job) >\n"
        "'finding_followup' (HUMAN-spawned) > everything else; the arXiv\n"
        "morning pick is a last resort, not the program driver.\n"
        "\n"
        "GAP SEMANTICS (D-059 evidence ladder): gaps like 'k candidate(s) at\n"
        "Lx awaiting <test>' are LADDER gaps — actionable by YOU (run the owed\n"
        "test: an experiment for L1, a loop iteration/battery for L2-L3).\n"
        "'await human' gaps are NOT actionable by you — never let them freeze\n"
        "the plan into promote-only cycles; a 'loop has not iterated' gap\n"
        "means research is OWED and a run_loop_iteration belongs in the plan.\n"
        "Use run_experiment only\n"
        "when a recent novel+surviving finding clearly maps to a built\n"
        "experiment (tier 'synthetic'; run_real only with strong reason).\n"
        "forecast_markets is the standing applied-tier PAPER workstream —\n"
        "worth one slot when no fresher applied data exists; it never trades.\n"
        "mine_paper_gap proposes a fresh, deduped arXiv topic when the\n"
        "topic_suggestions queue is thin — cheap insurance against repeating a\n"
        "near-duplicate of a prior hypothesis.\n"
        "ACTIVITY PORTFOLIO — the day is divided between classes of work, and\n"
        "each class has its OWN remaining budget in the state's\n"
        "'activity_budget'. ideation = run_loop_iteration, mine_paper_gap,\n"
        "refine_idea; research = run_experiment, promote_findings,\n"
        "forecast_markets, bubble_up; system = improve_system. An action whose\n"
        "class has 'remaining': 0 WILL BE SKIPPED — do not plan it, plan from a\n"
        "class that still has room. This is deliberate: ideation must not eat\n"
        "the day and leave the research already on the ladder unadvanced.\n"
        "AMEND BEFORE PROPOSING: when a cluster was killed on a critique that\n"
        "named fixable prior work or a confound, refine_idea (cost 2) amends it\n"
        "and re-screens. A new run_loop_iteration proposes ANOTHER idea and\n"
        "leaves the old one dead; prefer amending a near-miss over proposing\n"
        "again, and never re-propose a topic already in topic_suggestions'\n"
        "recent history.\n"
        "Prefer fewer, higher-value actions; the total cost of the\n"
        f"actions must not exceed {budget}.\n"
        "\n"
        "Output STRICT JSON, nothing else — no prose, no markdown fences, no\n"
        "channel markers. The output is a JSON ARRAY of action objects:\n"
        "[\n"
        '  {"action": "<menu action name>", "args": {<args per the menu>}}\n'
        "]\n"
    )


def plan(
    state: dict[str, Any],
    *,
    budget: int,
    backend: str | None = None,
    model: str | None = None,
    extra_guidance: str | None = None,
    parent_request_id: str | None = None,
) -> list[dict[str, Any]]:
    """ONE low-temp call_sync that returns an ordered plan = [{action, args}].

    Reuses the meta_review call_sync + JSON-extract pattern. The system prompt
    tells the model it may ONLY use the listed actions. On any failure (call
    raises, no JSON, JSON is not a list) returns [] — the validator then
    rejects an empty plan, which routes into the bounded replan.

    extra_guidance: validator error feedback appended on a replan attempt.
    """
    user = (
        "Apparatus state snapshot:\n"
        f"{json.dumps(state, indent=2, default=str)}\n\n"
        f"Emit the plan as a JSON array (budget={budget})."
    )
    if extra_guidance:
        user += (
            "\n\nYour PREVIOUS plan was REJECTED. Fix these errors and re-plan:\n"
            + extra_guidance
        )
    try:
        record = call_sync(
            [
                {"role": "system", "content": _planner_system_prompt(budget)},
                {"role": "user", "content": user},
            ],
            temperature=0.1,
            top_p=0.9,
            max_tokens=512,
            caller_tag="coordinator.plan",
            parent_request_id=parent_request_id,
            log_path=CALLS_LOG_PATH,
            backend=backend,
            model=model,
        )
    except Exception:
        return []

    parsed = _extract_json(record.get("completion") or "")
    if isinstance(parsed, list):
        return parsed
    # Some models wrap the array under a key; accept {"plan": [...]}.
    if isinstance(parsed, dict) and isinstance(parsed.get("plan"), list):
        return parsed["plan"]
    return []


# ── built-in handlers for the report-only actions ───────────────────────


def handle_bubble_up(
    *,
    finding_ids: list[str] | None = None,
    note: str | None = None,
    question: str | None = None,
    context: str | None = None,
    kind: str | None = None,
    allowed_actions: list[str] | None = None,
) -> dict[str, Any]:
    """bubble_up handler — surface an escalation into the coordinator report.

    Two additive forms (schema/escalation.schema.json):
      - LEGACY finding-id bubble: ``finding_ids`` (+ optional ``note``) — the
        original ack-only surfacing (taxonomy kind C).
      - GENERIC escalation: ``question`` (+ optional ``context``, ``kind``,
        ``allowed_actions``) — lets Nara escalate ANY uncertain step, not just
        finding ids.
    At least one of ``finding_ids`` / ``question`` must be supplied; an empty
    escalation is rejected (rule 4 — we never fabricate a surfacing).

    Fail-closed validation, mirroring novelty_skeptic.attack()'s discipline of
    never coercing an off-enum value into a pass: an unknown ``kind`` or an
    out-of-enum ``allowed_actions`` entry raises ``ValueError`` — the dispatch
    loop records that as ``status: error``, never a silent coercion to a valid
    value (inviolate rule 4).

    Writes nothing to disk and touches no shared state; the surfacing IS the
    report entry (persistence is _persist_bubble_up's job, execute-only).
    Referenced by coordinator_actions handler_ref."""
    fids = list(finding_ids) if finding_ids else []
    if not fids and not (isinstance(question, str) and question.strip()):
        raise ValueError(
            "bubble_up requires finding_ids or a non-empty question"
        )
    if kind is not None and kind not in ESCALATION_KINDS:
        raise ValueError(
            f"bubble_up kind {kind!r} not in {ESCALATION_KINDS}"
        )
    if allowed_actions is not None:
        bad = [a for a in allowed_actions if a not in ALLOWED_ESCALATION_ACTIONS]
        if bad:
            raise ValueError(
                f"bubble_up allowed_actions {bad!r} not in "
                f"{ALLOWED_ESCALATION_ACTIONS}"
            )
    return {
        "status": "passed",
        "result": {
            "finding_ids": fids,
            "note": note,
            "question": question,
            "context": context,
            "kind": kind,
            "allowed_actions": (
                list(allowed_actions) if allowed_actions is not None else None
            ),
        },
    }


def handle_noop(*, reason: str) -> dict[str, Any]:
    """noop handler — explicitly do nothing, recording the reason."""
    return {"status": "passed", "result": {"reason": reason}}


def handle_run_experiment(
    *, tier: str, experiment_id: str, run_real: bool = False,
) -> dict[str, Any]:
    """run_experiment handler — the T3 reverse path, coordinator-plannable.

    Bridges ONE experiment through the autoresearch driver into ONE
    LOOP_V0 iteration (live=True threads the experiment_outcome). Default
    is the cheap/safe form: reuse the committed results. run_real=True
    re-runs the experiment on the real model first (guarded; the planner
    must justify it). Lazy import — autoresearch pulls heavy deps."""
    from orchestrator.autoresearch import run_autoresearch

    payload = run_autoresearch(
        tier,
        experiment_id,
        reuse_results=not run_real,
        run_experiment=run_real,
        live=True,
        source="coordinator",
    )
    return {"status": "passed", "result": payload}


def handle_forecast_markets(
    *, n: int = 20, live_data: bool = True,
) -> dict[str, Any]:
    """forecast_markets handler — the exp007 Polymarket PAPER workstream.

    Sweep -> score -> strategy memo, all inside the design-only guardrail
    (read-only public data; the harness has zero trading surface and the
    memo carries the no-execution disclaimer). The memo stage degrades
    gracefully when the strategy module is absent (explicit in the
    result, never silent — rule 7)."""
    from experiments.exp007_polymarket import analyze as exp007_analyze
    from experiments.exp007_polymarket import run as exp007_run

    argv = ["--n", str(int(n))]
    if live_data:
        argv.append("--live-data")
    rc_run = exp007_run.main(argv)
    if rc_run != 0:
        return {"status": "error",
                "result": {"stage": "run", "exit_code": rc_run}}
    rc_an = exp007_analyze.main()
    out: dict[str, Any] = {"run_exit": rc_run, "analyze_exit": rc_an}
    # Memo failure degrades the result, never the cycle — but EXPLICITLY
    # (rule 7): the exception text is carried, not summarized away.
    try:
        from experiments.exp007_polymarket.strategy_memo import (
            build_and_write_memo,
        )
        out["memo"] = build_and_write_memo()
    except Exception as exc:
        out["memo"] = None
        out["memo_note"] = f"memo stage failed: {type(exc).__name__}: {exc}"
    return {"status": "passed" if rc_an == 0 else "error", "result": out}


def _default_execute_handlers() -> dict[str, Callable[..., Any]]:
    """The real dispatch table, resolved lazily so importing the coordinator
    pulls in nara / finding_promotion only when an --execute cycle runs."""
    from orchestrator.nara import run_iteration as _run_iteration
    from orchestrator.finding_promotion import promote_findings as _promote_findings
    from workers.mine_paper_gap import mine_paper_gap as _mine_paper_gap

    def _run_loop_iteration(*, topic: str) -> Any:
        return _run_iteration(topic, source="coordinator")

    def _promote(*, max_candidates: int | None = None) -> Any:
        result = _promote_findings(max_candidates=max_candidates)
        _persist_near_misses(result)
        return result

    def _mine_gap(*, n: int = 20, max_emit: int = 2) -> Any:
        return _mine_paper_gap(n=n, max_emit=max_emit)

    def _refine_idea(*, cluster_id: str, max_rounds: int = 5) -> Any:
        """D-064: bounded critique-refine on one cluster. Imported lazily so
        the frontier CLI seam is only touched when the action actually runs."""
        from workers.refine_cycle import refine_cluster
        return refine_cluster(cluster_id, max_rounds=max_rounds)

    def _improve_system(*, max_rounds: int = 3, emit: bool = True) -> Any:
        """D-066: telemetry -> proposal -> frontier debate -> red-first packet.

        Dark by default (the menu hides it), and the flag is checked HERE too
        so a hallucinated action name cannot spend frontier calls. The refusal
        is a returned status, never a silent noop — the cycle records it."""
        from orchestrator.coordinator_actions import DARK_ACTIONS
        flag = DARK_ACTIONS["improve_system"]
        if not os.environ.get(flag):
            return {"status": "refused",
                    "reason": f"improve_system is dark: {flag} is unset"}
        from orchestrator.self_improve import plan_improvement
        return plan_improvement(max_rounds=max_rounds, emit=emit)

    return {
        "run_loop_iteration": _run_loop_iteration,
        "promote_findings": _promote,
        "bubble_up": handle_bubble_up,
        "noop": handle_noop,
        "run_experiment": handle_run_experiment,
        "forecast_markets": handle_forecast_markets,
        "mine_paper_gap": _mine_gap,
        "refine_idea": _refine_idea,
        "improve_system": _improve_system,
    }


def _persist_near_misses(
    result: Any, *, path: str | os.PathLike | None = None,
) -> None:
    """Append promotion near-misses to memory/promotion_near_misses.jsonl.

    The 2026-06-09 cycle promoted 0/5 candidates and the per-candidate
    WHY was lost (the cycle log keeps action status only). One row per
    near-miss, append-only, never raises. path=None resolves at call time
    (patchable).

    P0 (LOOP_V1): keyed dedup on (source_iteration_id, stage, reason) — the
    stalled 2026-08-05..14 cycles re-appended the same ~140 rows/day, 5,513
    rows of pure duplication. Legacy rows stay untouched (append-only) and
    seed the key set; only novel keys append."""
    if path is None:
        path = DEFAULT_NEAR_MISSES
    try:
        misses = (result or {}).get("near_misses") if isinstance(result, dict) else None
        if not misses:
            return
        p = Path(path)
        seen = {
            (r.get("source_iteration_id"), r.get("stage"), r.get("reason"))
            for r in _read_jsonl(p)
        }
        ts = _utcnow_iso()
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a") as fh:
            for nm in misses:
                if not isinstance(nm, dict):
                    continue
                key = (nm.get("source_iteration_id"), nm.get("stage"),
                       nm.get("reason"))
                if key in seen:
                    continue
                seen.add(key)
                fh.write(json.dumps(
                    {"timestamp": ts, **nm}, ensure_ascii=False) + "\n")
    except Exception:
        return


# ── cycle ────────────────────────────────────────────────────────────────


def coordinator_cycle(
    *,
    budget: int = 6,
    dry_run: bool = True,
    execute_handlers: dict[str, Callable[..., Any]] | None = None,
    backend: str | None = None,
    model: str | None = None,
    loop_memory_path: str | os.PathLike = DEFAULT_LOOP_MEMORY,
    surfaced_path: str | os.PathLike = DEFAULT_SURFACED,
    feedback_path: str | os.PathLike = DEFAULT_FEEDBACK,
    active_run_path: str | os.PathLike = DEFAULT_ACTIVE_RUN,
) -> dict[str, Any]:
    """One coordinator cycle: assess -> plan -> validate (-> dispatch).

    Bounded replan: if the first plan is invalid, re-plan with the validator
    errors appended, up to _MAX_REPLANS (2) more attempts. If still invalid,
    return {"status": "no_valid_plan", ...} and execute NOTHING.

    dry_run=True (default): return the validated plan WITHOUT executing — NO
    handler is called. dry_run=False: execute each validated action via
    `execute_handlers` (defaulting to the real nara / finding_promotion table),
    in order, within budget, logging each.

    Always returns a coordinator_report: the plan, a bubble_up summary, and a
    per-action status list. Adopts active_run (kind="ad_hoc") + set_run_id
    around the cycle so the UI sees a live coordinator run.
    """
    run_id = f"coordinator_{uuid.uuid4().hex[:8]}"
    # β bounds (D-049) — checked BEFORE any registration or LLM call. A
    # refusal still writes a cycle-log row (best-effort) so the audit/UI
    # surface never has a silent gap where a cycle was refused.
    # (1) Kill switch: a pause file halts every cycle, supervised or not.
    if PAUSE_PATH.exists():
        report = {
            "run_id": run_id, "status": "paused",
            "errors": [f"pause file present: {PAUSE_PATH}"],
            "plan": [], "executed": [], "bubble_up": [], "attempts": [],
        }
        coordinator_cycle_log.write_coordinator_cycle(report)
        return report
    # (2) Daily executed-cycle budget: an EXECUTE cycle refuses when today's
    # ledger total PLUS this cycle's potential budget would exceed the cap
    # (conservative refusal; only ACTUAL spend is charged afterwards).
    # Dry-runs are never charged or blocked.
    if not dry_run:
        spent_today = _daily_spent()
        allowance = _budget_allowance()
        if spent_today + budget > allowance:
            # Two DIFFERENT refusals, never conflated: the day's cap is truly
            # gone, or this cycle is merely early for its share.
            exhausted = spent_today + budget > DAILY_BUDGET_CAP
            status = ("daily_budget_exhausted" if exhausted
                      else "daily_budget_paced")
            detail = (f"daily ledger {spent_today} + cycle budget {budget} > "
                      + (f"cap {DAILY_BUDGET_CAP}" if exhausted
                         else f"elapsed-share allowance {allowance} of cap "
                              f"{DAILY_BUDGET_CAP}")
                      + " (run_state/coordinator_budget.jsonl)")
            report = {
                "run_id": run_id, "status": status, "errors": [detail],
                "plan": [], "executed": [], "bubble_up": [], "attempts": [],
            }
            # A refusal is NOT a cycle: writing it to coordinator_cycles.jsonl
            # is what put nine empty "no valid plan" rows on the dashboard in
            # one afternoon. It is still logged (rule 6) — as what it is.
            append_run_log({
                "task_id": "coordinator:budget_refusal", "status": "refused",
                "observable_actual": detail,
                "observable_expected": (
                    "a cycle whose budget fits today's elapsed share"),
                "duration_ms": 0.0,
            }, agent="coordinator")
            return report
    set_run_id(run_id)
    set_current_agent("coordinator")
    active_run.write_active_run(run_id, kind="coordinator", label="coordinator_cycle")
    try:
        return _coordinator_cycle(
            run_id=run_id,
            budget=budget,
            dry_run=dry_run,
            execute_handlers=execute_handlers,
            backend=backend,
            model=model,
            loop_memory_path=loop_memory_path,
            surfaced_path=surfaced_path,
            feedback_path=feedback_path,
            active_run_path=active_run_path,
        )
    finally:
        active_run.clear_active_run()
        set_run_id(None)
        set_current_agent(None)


def _coordinator_cycle(
    *,
    run_id: str,
    budget: int,
    dry_run: bool,
    execute_handlers: dict[str, Callable[..., Any]] | None,
    backend: str | None,
    model: str | None,
    loop_memory_path: str | os.PathLike,
    surfaced_path: str | os.PathLike,
    feedback_path: str | os.PathLike,
    active_run_path: str | os.PathLike,
) -> dict[str, Any]:
    state = assess_state(
        loop_memory_path=loop_memory_path,
        surfaced_path=surfaced_path,
        feedback_path=feedback_path,
        active_run_path=active_run_path,
    )
    _ts = (state.get("topic_suggestions") or [{}])[0]
    active_run.update_active_run(
        current_step="assess",
        narration=(
            f"assessed state; {len(state.get('recent_findings') or [])} recent "
            f"iter(s); candidate topic {_ts.get('topic')!r} (source={_ts.get('source')})"
        ),
    )
    active_run.update_active_run(
        current_step="plan",
        narration="planning next action over the constrained action menu",
    )

    # assess -> plan -> validate, with bounded replan on rejection.
    attempts: list[dict[str, Any]] = []
    extra_guidance: str | None = None
    validated: list[dict[str, Any]] | None = None
    raw_plan: list[dict[str, Any]] = []
    for attempt in range(_MAX_REPLANS + 1):
        raw_plan = plan(
            state,
            budget=budget,
            backend=backend,
            model=model,
            extra_guidance=extra_guidance,
            parent_request_id=run_id,
        )
        verdict = validate_plan(raw_plan, budget=budget)
        attempts.append({
            "attempt": attempt,
            "raw_plan": raw_plan,
            "ok": verdict["ok"],
            "errors": verdict["errors"],
        })
        if verdict["ok"]:
            validated = verdict["normalized"]
            break
        # Append the validator errors as guidance for the next attempt.
        extra_guidance = "\n".join(f"- {e}" for e in verdict["errors"])

    if validated is None:
        # All attempts rejected — the GUARDRAIL fires: execute NOTHING.
        report = {
            "run_id": run_id,
            "status": "no_valid_plan",
            "errors": attempts[-1]["errors"] if attempts else ["no plan produced"],
            "attempts": attempts,
            "state": state,
            "plan": [],
            "executed": [],
            "bubble_up": [],
        }
        coordinator_cycle_log.write_coordinator_cycle(report)
        return report

    # Dry-run: return the validated plan WITHOUT executing.
    if dry_run:
        report = {
            "run_id": run_id,
            "status": "planned",
            "dry_run": True,
            "plan": validated,
            "attempts": attempts,
            "state": state,
            "executed": [],
            "bubble_up": _collect_bubble_up(validated, executed=None),
            "errors": [],
        }
        coordinator_cycle_log.write_coordinator_cycle(report)
        return report

    active_run.update_active_run(
        current_step="validate",
        narration=f"plan validated: {[s.get('name') for s in validated]}",
    )
    active_run.update_active_run(
        current_step="dispatch",
        narration=f"dispatching {len(validated)} action(s)",
    )
    # Execute: dispatch each validated action in order, within budget.
    handlers = execute_handlers or _default_execute_handlers()
    executed: list[dict[str, Any]] = []
    spent = 0
    # Portfolio state: today's per-class spend BEFORE this cycle, so a class
    # that has had its day cannot take the whole cycle budget again.
    class_spent = _daily_spent_by_class()
    cycle_by_class: dict[str, int] = {}
    for step in validated:
        name = step["name"]
        args = step.get("args", {})
        cost = int(step.get("cost", 0))
        cls = activity_class(name)
        if cost and cls != "free":
            used, allow = class_spent.get(cls, 0), class_allowance(cls)
            if used + cost > allow:
                executed.append({
                    "action": name, "status": "skipped",
                    "reason": (f"activity share spent: {cls} used {used} + "
                               f"{cost} > today's {cls} share {allow} "
                               f"(cap {DAILY_BUDGET_CAP})"),
                })
                continue
        if spent + cost > budget:
            executed.append({
                "action": name, "status": "skipped",
                "reason": f"budget exhausted (spent={spent}, cost={cost}, budget={budget})",
            })
            continue
        handler = handlers.get(name)
        if handler is None:
            executed.append({
                "action": name, "status": "error",
                "reason": f"no handler registered for action {name!r}",
            })
            continue
        try:
            result = handler(**args)
            executed.append({
                "action": name, "status": "passed", "result": result,
            })
            spent += cost
            if cost and cls != "free":
                class_spent[cls] = class_spent.get(cls, 0) + cost
                cycle_by_class[cls] = cycle_by_class.get(cls, 0) + cost
            if name == "run_loop_iteration":
                _consume_agenda_topic(args.get("topic"), state)
        except Exception as exc:
            executed.append({
                "action": name, "status": "error",
                "reason": f"{type(exc).__name__}: {exc}",
            })

    _charge_daily_ledger(run_id, spent, by_class=cycle_by_class)
    bubbles = _collect_bubble_up(validated, executed=executed)
    _persist_bubble_up(bubbles, run_id=run_id)
    report = {
        "run_id": run_id,
        "status": "executed",
        "dry_run": False,
        "plan": validated,
        "attempts": attempts,
        "state": state,
        "executed": executed,
        "bubble_up": bubbles,
        "errors": [],
    }
    coordinator_cycle_log.write_coordinator_cycle(report)
    coordinator_cycle_log.emit_health_signals(report)
    return report


def _collect_bubble_up(
    validated: list[dict[str, Any]], *, executed: list[dict[str, Any]] | None
) -> list[dict[str, Any]]:
    """Summarize every bubble_up action in the plan for the human-facing report.

    Carries both the legacy finding-id fields and the generic-escalation fields
    (question/context/kind/allowed_actions) so the report and the persist see
    the full additive shape (schema/escalation.schema.json)."""
    out: list[dict[str, Any]] = []
    for step in validated:
        if step.get("name") != "bubble_up":
            continue
        args = step.get("args", {})
        out.append({
            "finding_ids": args.get("finding_ids", []),
            "note": args.get("note"),
            "question": args.get("question"),
            "context": args.get("context"),
            "kind": args.get("kind"),
            "allowed_actions": args.get("allowed_actions"),
        })
    return out


def _persist_bubble_up(
    bubbles: list[dict[str, Any]], *, run_id: str,
    path: str | os.PathLike | None = None,
) -> None:
    """Append each bubble_up entry to memory/coordinator_bubbles.jsonl so a
    coordinator surfacing OUTLIVES the run — today bubble_up is report-only
    (returned + printed, then lost). Execute-only by design: a bubble is an
    actual surfacing (handle_bubble_up ran), not a dry-run proposal, so a
    planned-but-not-executed bubble is never recorded as a real one (rule 4).
    One row per bubble; append-only (matches the JSONL convention); never raises.
    path=None resolves to DEFAULT_COORDINATOR_BUBBLES at call time (patchable)."""
    if not bubbles:
        return
    if path is None:
        path = DEFAULT_COORDINATOR_BUBBLES
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a") as fh:
            for bu in bubbles:
                # Legacy fields stay byte-shape identical (run_id/timestamp/
                # finding_ids/note) so the existing UI reader
                # (human_todo._bubble_ack_items) never breaks. The generic
                # escalation fields are ADDITIVE — written only when present
                # so a legacy finding-id bubble carries no empty generic keys.
                row: dict[str, Any] = {
                    "timestamp": _utcnow_iso(),
                    "run_id": run_id,
                    "finding_ids": bu.get("finding_ids", []),
                    "note": bu.get("note"),
                }
                for key in ("question", "context", "kind", "allowed_actions"):
                    val = bu.get(key)
                    if val is not None:
                        row[key] = val
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        return


def count_actionable_escalations(
    *, path: str | os.PathLike | None = None,
) -> int:
    """COUNT CONTRACT for the dashboard idle-hero count: the number of
    persisted escalations of kind A (judgment) or B (blocking-halt) ONLY —
    NEVER C (read-receipt). A read-receipt is not unresolved work, so legacy
    finding-id bubbles (which carry no `kind`, i.e. taxonomy C) are excluded.

    This is the contract the UI renders against; the UI does the rendering,
    this function produces the count. Rows are read from
    memory/coordinator_bubbles.jsonl (path=None resolves at call time).
    Never raises; a missing/unreadable file -> 0."""
    if path is None:
        path = DEFAULT_COORDINATOR_BUBBLES
    return sum(
        1 for row in _read_jsonl(path)
        if row.get("kind") in ACTIONABLE_ESCALATION_KINDS
    )


# ── CLI ────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m orchestrator.coordinator",
        description=(
            "Coordinator brain (assess -> plan -> validate -> dispatch). "
            "OPT-IN and SEPARATE from nara's default scripted path. Default "
            "is a single dry-run cycle: it plans only and prints the plan + "
            "report. --execute is required to actually dispatch handlers."
        ),
    )
    p.add_argument("--once", action="store_true",
                   help="Run a single coordinator cycle (the only mode).")
    p.add_argument("--execute", action="store_true",
                   help="Actually dispatch the validated plan. Without this "
                        "flag the cycle is DRY-RUN (plan only, no execution).")
    p.add_argument("--budget", type=int, default=6,
                   help="Max plan cost (budget units). Over-budget plans are rejected.")
    p.add_argument("--backend", default=None,
                   help="Backend for the plan LLM call (default: wrapper default).")
    p.add_argument("--model", default=None,
                   help="Model override for the plan LLM call.")
    args = p.parse_args(argv)

    report = coordinator_cycle(
        budget=args.budget,
        dry_run=not args.execute,
        backend=args.backend,
        model=args.model,
    )

    print(f"status={report['status']} run_id={report['run_id']} "
          f"dry_run={report.get('dry_run', True)}")
    if report["status"] == "no_valid_plan":
        print("NO VALID PLAN — guardrail rejected every attempt; nothing executed.")
        for e in report.get("errors", []):
            print(f"  reject: {e}", file=sys.stderr)
        return 0
    print("PLAN:")
    for i, step in enumerate(report["plan"]):
        print(f"  [{i}] {step['name']}(cost={step['cost']}) args={step['args']}")
    for bu in report.get("bubble_up", []):
        print(f"  BUBBLE_UP: {bu['finding_ids']} note={bu['note']!r}")
    for ex in report.get("executed", []):
        print(f"  EXEC {ex['action']}: {ex['status']}"
              + (f" — {ex.get('reason')}" if ex.get("reason") else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
