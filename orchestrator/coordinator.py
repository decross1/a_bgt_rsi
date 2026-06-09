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
from orchestrator import active_run, tier_registry
from orchestrator.coordinator_actions import known_actions, validate_plan
from orchestrator.morning_topic import pick_morning_topic
from orchestrator.runtime import set_current_agent

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOOP_MEMORY = REPO_ROOT / "memory" / "loop_memory.jsonl"
DEFAULT_SURFACED = REPO_ROOT / "memory" / "surfaced_findings.jsonl"
DEFAULT_FEEDBACK = REPO_ROOT / "memory" / "loop_feedback.jsonl"
DEFAULT_ACTIVE_RUN = REPO_ROOT / "run_state" / "active_run.json"
DEFAULT_COORDINATOR_BUBBLES = REPO_ROOT / "memory" / "coordinator_bubbles.jsonl"

CALLS_LOG_PATH = os.environ.get("LOOP_V0_CALLS_LOG", "logs/calls.jsonl")

# How many recent loop_memory rows the assessment digests.
_RECENT_N = 8
# Bounded replan retries (after the first plan attempt). <= 2 per the contract.
_MAX_REPLANS = 2


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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
) -> list[dict[str, str]]:
    """One morning-loop topic candidate (newest arXiv paper, else a
    loop-memory gap probe, else a safe fallback). Never raises; degrades to
    [] so assess_state stays a pure read. Surfacing this is what un-blinds
    the planner — run_loop_iteration's arg_schema requires a non-empty topic
    and the planner had no candidate to offer before."""
    try:
        topic, source = pick_morning_topic(loop_memory_path=loop_memory_path)
    except Exception:
        return []
    return [{"topic": topic, "source": source}]


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
        # An "open thread" = a recent iteration with no human verdict yet.
        if human_verdict is None and r.get("gate_status") == "pending":
            open_threads.append(iid)

    # --- surfaced findings awaiting review ---
    surfaced_pending: list[dict[str, Any]] = []
    for sf in _read_jsonl(surfaced_path):
        status = sf.get("status")
        if status in ("surfaced", "in_review"):
            surfaced_pending.append({
                "finding_id": sf.get("finding_id"),
                "title": str(sf.get("title") or "")[:200],
                "status": status,
            })

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
    # novel-but-unpromoted: a recent novel+survives iteration with no surfaced row.
    surfaced_src = {
        sf.get("source_iteration_id") for sf in _read_jsonl(surfaced_path)
    }
    novel_unpromoted = [
        f["iteration_id"] for f in recent_findings
        if f["novelty"] == "novel"
        and f["critic"] == "survives"
        and f["iteration_id"] not in surfaced_src
    ]
    if novel_unpromoted:
        gaps.append(
            f"{len(novel_unpromoted)} recent novel+surviving iteration(s) "
            "not yet through promotion"
        )

    return {
        "in_flight": in_flight,
        "recent_findings": recent_findings,
        "open_threads": open_threads,
        "gaps": gaps,
        "surfaced_pending": surfaced_pending,
        "experiments": experiments,
        "topic_suggestions": _topic_suggestions(loop_memory_path),
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
        "for scope). Prefer fewer, higher-value actions; the total cost of the\n"
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


def handle_bubble_up(*, finding_ids: list[str], note: str | None = None) -> dict[str, Any]:
    """bubble_up handler — surface finding ids into the coordinator report.

    Writes nothing to disk and touches no shared state; the surfacing IS the
    report entry. Referenced by coordinator_actions handler_ref."""
    return {
        "status": "passed",
        "result": {"finding_ids": list(finding_ids), "note": note},
    }


def handle_noop(*, reason: str) -> dict[str, Any]:
    """noop handler — explicitly do nothing, recording the reason."""
    return {"status": "passed", "result": {"reason": reason}}


def _default_execute_handlers() -> dict[str, Callable[..., Any]]:
    """The real dispatch table, resolved lazily so importing the coordinator
    pulls in nara / finding_promotion only when an --execute cycle runs."""
    from orchestrator.nara import run_iteration as _run_iteration
    from orchestrator.finding_promotion import promote_findings as _promote_findings

    def _run_loop_iteration(*, topic: str) -> Any:
        return _run_iteration(topic, source="coordinator")

    def _promote(*, max_candidates: int | None = None) -> Any:
        return _promote_findings(max_candidates=max_candidates)

    return {
        "run_loop_iteration": _run_loop_iteration,
        "promote_findings": _promote,
        "bubble_up": handle_bubble_up,
        "noop": handle_noop,
    }


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
    set_run_id(run_id)
    set_current_agent("coordinator")
    active_run.write_active_run(run_id, kind="ad_hoc", label="coordinator_cycle")
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
        return {
            "run_id": run_id,
            "status": "no_valid_plan",
            "errors": attempts[-1]["errors"] if attempts else ["no plan produced"],
            "attempts": attempts,
            "state": state,
            "plan": [],
            "executed": [],
            "bubble_up": [],
        }

    # Dry-run: return the validated plan WITHOUT executing.
    if dry_run:
        return {
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

    # Execute: dispatch each validated action in order, within budget.
    handlers = execute_handlers or _default_execute_handlers()
    executed: list[dict[str, Any]] = []
    spent = 0
    for step in validated:
        name = step["name"]
        args = step.get("args", {})
        cost = int(step.get("cost", 0))
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
        except Exception as exc:
            executed.append({
                "action": name, "status": "error",
                "reason": f"{type(exc).__name__}: {exc}",
            })

    bubbles = _collect_bubble_up(validated, executed=executed)
    _persist_bubble_up(bubbles, run_id=run_id)
    return {
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


def _collect_bubble_up(
    validated: list[dict[str, Any]], *, executed: list[dict[str, Any]] | None
) -> list[dict[str, Any]]:
    """Summarize every bubble_up action in the plan for the human-facing report."""
    out: list[dict[str, Any]] = []
    for step in validated:
        if step.get("name") != "bubble_up":
            continue
        args = step.get("args", {})
        out.append({
            "finding_ids": args.get("finding_ids", []),
            "note": args.get("note"),
        })
    return out


def _persist_bubble_up(
    bubbles: list[dict[str, Any]], *, run_id: str,
    path: str | os.PathLike = DEFAULT_COORDINATOR_BUBBLES,
) -> None:
    """Append each bubble_up entry to memory/coordinator_bubbles.jsonl so a
    coordinator surfacing OUTLIVES the run — today bubble_up is report-only
    (returned + printed, then lost). Execute-only by design: a bubble is an
    actual surfacing (handle_bubble_up ran), not a dry-run proposal, so a
    planned-but-not-executed bubble is never recorded as a real one (rule 4).
    One row per bubble; append-only (matches the JSONL convention); never raises."""
    if not bubbles:
        return
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a") as fh:
            for bu in bubbles:
                fh.write(json.dumps({
                    "timestamp": _utcnow_iso(),
                    "run_id": run_id,
                    "finding_ids": bu.get("finding_ids", []),
                    "note": bu.get("note"),
                }, ensure_ascii=False) + "\n")
    except Exception:
        return


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
