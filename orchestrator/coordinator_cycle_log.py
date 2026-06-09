"""Persist a coordinator cycle + derive its health signals — the EMIT layer
the UI session renders (Limb C of the 2026-06-09 autonomy-observability cycle).

The coordinator loop runs "dark": `coordinator_cycle` assembles a rich report
dict (plan, per-action outcomes, bubbles) but it lives only in stdout + the
return value and is lost. This module turns that report into two append-only
artifacts the UI reads:

  - run_state/coordinator_cycles.jsonl — ONE row per cycle: the whole decision
    arc (topic + source, plan, per-action outcome INCL. errors, the dispatched
    iteration, promoted findings, bubbles). The join key for the UI's
    Coordinator view. A FAILED dispatch is captured here as an explicit
    `outcomes` row (status="errored" + error) so absence never masquerades as
    "nothing happened" (the headline 2026-06-09 gap).

  - run_state/health_signals.jsonl — degraded-but-not-broken signals the
    sampler/UI surfaces amber: ml-intern "ran but stored 0 papers" and Qwen
    "generated but emitted empty content". Both are derived from evidence the
    cycle already produced (the run log's `loop_v0_ml_intern` result event; the
    calls log's empty-completion Qwen rows for the dispatched iteration) — this
    module adds NO new model calls.

Discipline (mirrors orchestrator/coordinator.py readers + active_run writes):
  - Every function is BEST-EFFORT and NEVER raises: a missing/partial source
    degrades to a no-op or a partial row so a logging failure can never crash
    the autonomous cycle (inviolate rule 7).
  - Append-only JSONL, one object per line, atomic-ish single write() per row
    (matches the run-log / coordinator_bubbles convention).
  - Pure builders (cycle_row_from_report / detect_*) are separated from the I/O
    so they unit-test hermetically with no files and no clock.

The cycle row's `status` per action is NORMALIZED to the UI contract enum
{passed, skipped, errored} — the coordinator's internal "error" status maps to
"errored" so the contract is unambiguous (the doc/handoff spell it "errored").
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CYCLES_PATH = REPO_ROOT / "run_state" / "coordinator_cycles.jsonl"
DEFAULT_HEALTH_PATH = REPO_ROOT / "run_state" / "health_signals.jsonl"
DEFAULT_RUN_LOG = REPO_ROOT / "run_state" / "week1.run.jsonl"
DEFAULT_CALLS_LOG = REPO_ROOT / "logs" / "calls.jsonl"

# A completion at or below this length (after strip) is treated as
# empty-content for the qwen-degraded signal: Qwen-MTP burns max_tokens on
# reasoning and emits nothing on the content channel (handoff 2026-06-09).
_EMPTY_CONTENT_MAXLEN = 0


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# ── pure readers (never raise) ────────────────────────────────────────────


def _read_jsonl(path: str | os.PathLike) -> list[dict[str, Any]]:
    """Read a JSONL file into dicts. Missing/unreadable -> []. Skips blank and
    malformed lines (mirrors orchestrator.coordinator._read_jsonl)."""
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


def _append_jsonl(path: str | os.PathLike, row: dict[str, Any]) -> bool:
    """Append one JSON object as a line. Best-effort; never raises. Returns
    True on a successful write, False otherwise (so a caller can log a fallback
    if it wants — today nobody does, matching coordinator._persist_bubble_up)."""
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        return True
    except Exception:
        return False


# ── pure builders (no I/O, no clock — unit-testable) ──────────────────────


def _normalize_status(status: Any) -> str:
    """Map a coordinator executed-action status onto the UI contract enum.

    The coordinator emits {"passed","skipped","error"}; the UI contract (the
    handoff doc) spells the failure case "errored". Map error->errored and pass
    anything else through unchanged so an unexpected value is surfaced verbatim
    rather than silently coerced to a pass (inviolate rule 4)."""
    s = str(status or "").strip()
    return "errored" if s == "error" else s


def _dispatched_iteration_id(executed: list[dict[str, Any]]) -> str | None:
    """The iteration_id a successful run_loop_iteration produced, if any.

    nara.run_iteration returns the full iteration_record; the coordinator wraps
    it as {"status":"passed","result":<record>}. We read result.iteration_id.
    Returns None when no run_loop_iteration ran or it errored (a failed dispatch
    has no iteration_id — its failure lives in the outcomes row instead)."""
    for ex in executed:
        if ex.get("action") != "run_loop_iteration":
            continue
        if ex.get("status") != "passed":
            continue
        result = ex.get("result")
        # result may be the record dict, or {"result": record}, or a wrapper
        # envelope {"status":..., "result": record}. Probe the common shapes.
        for cand in (result, (result or {}).get("result") if isinstance(result, dict) else None):
            if isinstance(cand, dict) and isinstance(cand.get("iteration_id"), str):
                return cand["iteration_id"]
    return None


def _promoted_finding_ids(executed: list[dict[str, Any]]) -> list[str]:
    """finding_ids surfaced by a successful promote_findings action.

    promote_findings returns {"promoted":[{finding_id,...}, ...], ...}. Collect
    every promoted finding_id across all promote actions in the cycle."""
    out: list[str] = []
    for ex in executed:
        if ex.get("action") != "promote_findings" or ex.get("status") != "passed":
            continue
        result = ex.get("result")
        if not isinstance(result, dict):
            continue
        promoted = result.get("promoted")
        if isinstance(promoted, list):
            for f in promoted:
                if isinstance(f, dict) and isinstance(f.get("finding_id"), str):
                    out.append(f["finding_id"])
    return out


def cycle_row_from_report(
    report: dict[str, Any], *, agent: str = "coordinator",
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Map a coordinator_cycle report onto the coordinator_cycles.jsonl row.

    PURE: no I/O, no clock unless `timestamp` is omitted (then _utcnow_iso).
    Reads the report's `plan` (validated steps: {name,cost,args}), `executed`
    (per-action {action,status,result|reason}), `state.topic_suggestions` (the
    auto-chosen topic + source), and `bubble_up`.

    The row schema (the UI contract — see docs/ui_session_handoff_2026-06-09.md):
      {timestamp, run_id, agent, topic, topic_source, status,
       plan:[{action,args}],
       outcomes:[{action, status: passed|skipped|errored, error?}],
       dispatched_iteration_id?, promoted_finding_ids:[], bubble_run_ids:[]}
    """
    plan = report.get("plan") or []
    executed = report.get("executed") or []
    state = report.get("state") or {}

    # auto-chosen topic + source: the candidate assess_state surfaced.
    topic: str | None = None
    topic_source: str | None = None
    suggestions = state.get("topic_suggestions") or []
    if isinstance(suggestions, list) and suggestions and isinstance(suggestions[0], dict):
        topic = suggestions[0].get("topic")
        topic_source = suggestions[0].get("source")
    # Prefer the topic the plan actually ran, if a run_loop_iteration is present
    # (the planner is told to use the suggestion verbatim, but trust the plan).
    for step in plan:
        if isinstance(step, dict) and step.get("name") == "run_loop_iteration":
            arg_topic = (step.get("args") or {}).get("topic")
            if isinstance(arg_topic, str) and arg_topic:
                topic = arg_topic
            break

    plan_rows = [
        {"action": s.get("name"), "args": s.get("args", {})}
        for s in plan if isinstance(s, dict)
    ]

    outcomes: list[dict[str, Any]] = []
    for ex in executed:
        if not isinstance(ex, dict):
            continue
        row: dict[str, Any] = {
            "action": ex.get("action"),
            "status": _normalize_status(ex.get("status")),
        }
        # Failed/skipped actions carry their reason as `error` so the UI can
        # render the explicit error string (failed dispatch is NEVER silent).
        if row["status"] in ("errored", "skipped") and ex.get("reason"):
            row["error"] = ex["reason"]
        outcomes.append(row)

    dispatched = _dispatched_iteration_id(executed)
    promoted = _promoted_finding_ids(executed)

    # bubble_run_ids: a bubble is persisted under the cycle's own run_id (see
    # coordinator._persist_bubble_up), so a non-empty bubble_up means this
    # run_id appears in coordinator_bubbles.jsonl. Empty list when no bubble.
    bubbles = report.get("bubble_up") or []
    bubble_run_ids = [report.get("run_id")] if bubbles and report.get("run_id") else []

    out: dict[str, Any] = {
        "timestamp": timestamp or _utcnow_iso(),
        "run_id": report.get("run_id"),
        "agent": agent,
        "topic": topic,
        "topic_source": topic_source,
        "status": report.get("status"),
        "plan": plan_rows,
        "outcomes": outcomes,
        "promoted_finding_ids": promoted,
        "bubble_run_ids": bubble_run_ids,
    }
    if dispatched is not None:
        out["dispatched_iteration_id"] = dispatched
    return out


# ── health-signal detection (pure) ────────────────────────────────────────


def detect_ml_intern_zero(
    iteration_id: str | None, run_log_rows: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """ml-intern "ran but stored 0 papers" for `iteration_id`, or None.

    Reads the run log's `loop_v0_ml_intern` phase="result" event: ml_intern was
    invoked (the event exists) but `papers_stored == 0` -> degraded-silent. If
    ml_intern never ran (no event) there is nothing to flag (None).

    This is the signal the 2026-06-09 critic-honesty finding needs surfaced:
    the critic judged on local-only literature because external search came back
    empty — and that emptiness was silent. Here it becomes a first-class row."""
    if not iteration_id:
        return None
    for r in run_log_rows:
        if (r.get("event_type") == "loop_v0_ml_intern"
                and r.get("phase") == "result"
                and r.get("iteration_id") == iteration_id):
            stored = r.get("papers_stored")
            if isinstance(stored, int) and stored == 0:
                return {
                    "signal": "ml_intern_zero_papers",
                    "severity": "degraded",
                    "iteration_id": iteration_id,
                    "papers_stored": 0,
                    "status": r.get("status"),
                    "detail": (
                        "ml_intern ran but stored 0 papers; the external-search "
                        "layer was effectively blind — any novelty/critic verdict "
                        "this iteration rests on LOCAL literature only."
                    ),
                }
    return None


def detect_qwen_degraded(
    iteration_id: str | None, calls_rows: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Qwen "generated but emitted empty content" for `iteration_id`, or None.

    Scans the calls log for rows of THIS iteration (run_id == iteration_id)
    served by Qwen (model/model_version contains 'qwen', or the ollama :8001
    endpoint) whose `completion` is empty after strip. Empty content on a
    served call is degraded (the route is up but unusable), distinct from the
    endpoint being unreachable (that's the sampler's job to flag as down).

    Returns a single summary row across the iteration's Qwen calls (count of
    empty vs total), or None if Qwen wasn't called this iteration."""
    if not iteration_id:
        return None
    total = 0
    empty = 0
    model_seen: str | None = None
    for r in calls_rows:
        if r.get("run_id") != iteration_id:
            continue
        if not _is_qwen_row(r):
            continue
        total += 1
        model_seen = model_seen or (r.get("model") or r.get("model_version"))
        completion = r.get("completion")
        if not isinstance(completion, str) or len(completion.strip()) <= _EMPTY_CONTENT_MAXLEN:
            empty += 1
    if total == 0 or empty == 0:
        return None
    return {
        "signal": "qwen_degraded_empty_content",
        "severity": "degraded",
        "iteration_id": iteration_id,
        "model": model_seen,
        "empty_calls": empty,
        "total_calls": total,
        "detail": (
            f"Qwen returned empty content on {empty}/{total} call(s) this "
            "iteration (route up but unusable: reasoning burns the token budget, "
            "content channel empty). The independent skeptic is DEGRADED, not down."
        ),
    }


def _is_qwen_row(row: dict[str, Any]) -> bool:
    """Whether a calls-log row was served by the Qwen route."""
    model = str(row.get("model") or "").lower()
    version = str(row.get("model_version") or "").lower()
    if "qwen" in model or "qwen" in version:
        return True
    meta = row.get("host_metadata")
    if isinstance(meta, dict):
        url = str(meta.get("ollama_base_url") or "")
        if ":8001" in url:
            return True
    return False


# ── public writers (best-effort, never raise) ─────────────────────────────


def write_coordinator_cycle(
    report: dict[str, Any], *, agent: str = "coordinator",
    cycles_path: str | os.PathLike = DEFAULT_CYCLES_PATH,
) -> dict[str, Any] | None:
    """Append one coordinator_cycles.jsonl row built from `report`.

    Best-effort: a build or write failure degrades to None so the autonomous
    cycle never crashes on its own bookkeeping. Returns the written row (so the
    caller / a test can assert on it) or None."""
    try:
        row = cycle_row_from_report(report, agent=agent)
    except Exception:
        return None
    _append_jsonl(cycles_path, row)
    return row


def emit_health_signals(
    report: dict[str, Any], *,
    health_path: str | os.PathLike = DEFAULT_HEALTH_PATH,
    run_log_path: str | os.PathLike = DEFAULT_RUN_LOG,
    calls_log_path: str | os.PathLike = DEFAULT_CALLS_LOG,
) -> list[dict[str, Any]]:
    """Derive + append degraded health signals for this cycle's dispatched
    iteration. Returns the list of signals written ([] if none / on failure).

    Adds NO model calls: ml-intern-0-papers comes from the run log's
    loop_v0_ml_intern result event; qwen-degraded from the calls log's
    empty-completion Qwen rows. Both are scoped to the dispatched iteration_id
    so the calls-log scan is cheap and the signals attribute to a concrete run.
    A signal carries a timestamp so the UI can show the most-recent one."""
    signals: list[dict[str, Any]] = []
    try:
        executed = report.get("executed") or []
        iteration_id = _dispatched_iteration_id(executed)
        if iteration_id is None:
            return signals
        run_log_rows = _read_jsonl(run_log_path)
        calls_rows = _read_jsonl(calls_log_path)
        mi = detect_ml_intern_zero(iteration_id, run_log_rows)
        qw = detect_qwen_degraded(iteration_id, calls_rows)
        for sig in (mi, qw):
            if sig is None:
                continue
            sig = {"timestamp": _utcnow_iso(), "run_id": report.get("run_id"), **sig}
            _append_jsonl(health_path, sig)
            signals.append(sig)
    except Exception:
        return signals
    return signals
