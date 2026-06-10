"""MCP submit+poll seam for the host tool plane (the T2 known-gap fix).

run_loop_iteration is a long job (~74-479s observed) behind a short RPC:
the OpenClaw MCP client's 15s connection timeout cut the synchronous
verdict of the 2026-06-09 T2 drive (the SDK retry then bounced safely
off the one-at-a-time guard). This module is the asynchronous half of
the fix, composing with the D-047 registry as recorded 2026-06-10:
"submit registers a run; the agent polls honest state."

  submit (tool_plane closure -> new_ticket + start_iteration_thread):
    writes a seam-private ticket, runs the SAME nara.run_iteration in a
    daemon thread, and returns the run_id in milliseconds.
  poll (tool_plane closure -> poll): honest reads ONLY — the ticket, the
    D-047 registry doc the thread registered (kind "ad_hoc"), and
    run_state/active_iteration.json (nara refreshes it per step; its
    mtime is the live progress signal). Nothing is synthesized. The ONE
    write poll ever makes is reconciling this seam's own ticket when its
    writer pid is dead (server restart — the thread cannot exist).

Containment (D-040 + the continuous-orchestrator guardrail): exactly ONE
iteration per explicit submit — no queue, no retry, no scheduler; a busy
submit is REFUSED, never enqueued. One-in-flight is enforced twice: the
in-process latch here (_latch + _live, closing the registration-window
race) and the same active_run-mirror predicate the sync tool uses (true
for the whole run once the thread registers the ticket as an ad_hoc run).

SINGLE-PROCESS assumption: the latch is in-process and restart detection
is pid-based (threads die with the process). Run the plane as exactly
one uvicorn process — the `python -m orchestrator.tool_plane` CLI is.

Tickets are seam-private JSON files under run_state/tool_plane_submits/
(schema-free; NOT active_run-schema docs). poll serves ONLY this seam's
tickets — a sandbox cannot poll host iteration ids or experiment runs
(unknown_run_id), and everything returned is read-only telemetry.
"""
from __future__ import annotations

import json
import os
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from orchestrator import active_run
from orchestrator.runtime import PyRuntime, set_current_agent

REPO_ROOT = Path(__file__).resolve().parent.parent
TICKETS_DIR = REPO_ROOT / "run_state" / "tool_plane_submits"
# nara's per-step board (runtime.write_state(nara.ACTIVE_PATH, ...)) — read
# tolerantly at poll time. A module attribute so tests monkeypatch it.
ACTIVE_ITERATION_PATH = REPO_ROOT / "run_state" / "active_iteration.json"

# The ticket's ad_hoc registry doc is written ONCE (nara never calls
# update_active_run on it mid-iteration), so heartbeat_age grows on a
# perfectly healthy run. 900s sits far beyond every observed iteration
# (74-479s); `stale` is REPORTED, never acted on (rule 4 — report,
# don't coerce; active_iteration's mtime is the real liveness signal).
STALE_HEARTBEAT_S = 900

POLL_TOOL = "poll_run"  # envelope name; tool_plane.POLL_TOOL_NAME mirrors it

# One-submit-at-a-time latch. The submit handler (tool_plane.py) holds
# _latch across its check+create+start window so two simultaneous submits
# cannot both pass before the first thread registers its run; _live is the
# executor thread, cleared by that thread's own finally.
_latch = threading.Lock()
_live: threading.Thread | None = None


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict | None:
    """Tolerant read: missing/malformed/non-dict -> None, never raises."""
    try:
        doc = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def _atomic_write(doc: dict, path: Path) -> None:
    # write tmp + os.replace — mirrors active_run._atomic_write but
    # schema-free: tickets are seam-private, not active_run-schema docs.
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2))
    os.replace(tmp, path)


def _ticket_path(run_id: str) -> Path:
    # TICKETS_DIR resolved at CALL time so test monkeypatches apply.
    return TICKETS_DIR / f"{active_run._safe_filename(run_id)}.json"


def new_ticket(topic: str) -> dict:
    """Create a running ticket. `pid` pins the writer process: threads die
    with the process, so a pid mismatch at poll time is deterministic
    proof the executor no longer exists (restart detection)."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    run_id = f"mcpsub-{stamp}Z-{secrets.token_hex(2)}"
    doc = {
        "run_id": run_id,
        "status": "running",
        "topic": topic,
        "submitted_at": _utcnow_iso(),
        "pid": os.getpid(),
    }
    _atomic_write(doc, _ticket_path(run_id))
    return doc


def read_ticket(run_id: str) -> dict | None:
    return _read_json(_ticket_path(run_id))


def finish_ticket(run_id: str, result: dict) -> dict:
    doc = read_ticket(run_id) or {"run_id": run_id}
    doc.update(status="finished", finished_at=_utcnow_iso(), result=result)
    _atomic_write(doc, _ticket_path(run_id))
    return doc


def fail_ticket(run_id: str, error: str) -> dict:
    doc = read_ticket(run_id) or {"run_id": run_id}
    doc.update(status="failed", finished_at=_utcnow_iso(), error=error)
    _atomic_write(doc, _ticket_path(run_id))
    return doc


def thread_live() -> bool:
    """True while a submitted-run executor thread is alive — the latch's
    liveness predicate, covering the window before the thread registers
    its run in the active_run mirror (the registration race)."""
    return _live is not None and _live.is_alive()


def in_flight_summary() -> dict | None:
    """Tolerant subset of the foreground mirror naming the blocking run in
    an iteration_in_flight refusal. None when there is no/odd mirror."""
    doc = _read_json(active_run.ACTIVE_RUN_PATH)
    if doc is None:
        return None
    return {k: doc.get(k) for k in
            ("run_id", "kind", "label", "started_at", "heartbeat_at")}


def start_iteration_thread(
    ticket: dict, run_iteration_callable: Callable[..., dict]
) -> threading.Thread:
    """Start the daemon executor for a just-created ticket.

    Caller (the submit handler) holds _latch. The thread gets a FRESH
    contextvars context — which is exactly why registration happens IN
    the thread body, never in the request handler: request contexts are
    per-call copies, so a handler-side write_active_run would orphan
    ownership of the D-047 stack and a no-context clear in the thread
    would take the legacy branch and clobber a FOREIGN mirror.
    """
    global _live
    thread = threading.Thread(
        target=_execute, args=(ticket, run_iteration_callable),
        name=f"submitted-run-{ticket['run_id']}", daemon=True,
    )
    _live = thread
    thread.start()
    return thread


def _execute(ticket: dict, run_iteration_callable: Callable[..., dict]) -> None:
    """Thread body: register -> run -> persist the terminal ticket.

    Exceptions persist as ticket failure and never escape (the plane's
    never-raises discipline holds trivially — no 500 can come from here).
    The finished result is run_iteration's in-memory return persisted
    into the ticket — NOT re-parsed from memory/loop_memory.jsonl (which
    is unjoinable by ticket id; loop_memory stays the durable record)."""
    run_id, topic = ticket["run_id"], ticket["topic"]
    runtime = PyRuntime(tool_registry={})  # log_event only; no tool imports
    registered = False
    try:
        # D-043 parity: a fresh thread defaults to agent "nara"; every
        # run-log row this run emits must carry the sandbox identity.
        set_current_agent("nemoclaw_agent")
        # "submit registers a run" (D-047): the ticket is the parent
        # ad_hoc run; run_iteration's own loop_v0 registration nests on
        # this thread's stack and pops cleanly (coordinator->iteration
        # precedent), restoring the ticket doc as the mirror.
        active_run.write_active_run(
            run_id, "ad_hoc", f"MCP submitted iteration: {topic[:60]}")
        registered = True
        runtime.log_event({
            "event_type": "tool_plane_submit_accepted",
            "run_id": run_id, "topic": topic,
        })
        record = run_iteration_callable(topic, source="nemoclaw_agent")
    except Exception as exc:  # persisted as ticket failure, never a 500
        err = f"{type(exc).__name__}: {exc}"
        fail_ticket(run_id, err)
        runtime.log_event({
            "event_type": "tool_plane_submit_failed",
            "run_id": run_id, "error": err,
        })
    else:
        # Terminal persistence must not leave a zombie "running" ticket
        # (2026-06-10 review): a non-dict record or a finish-write failure
        # downgrades to a failed ticket, best-effort.
        try:
            if not isinstance(record, dict):
                raise TypeError(
                    f"run_iteration returned {type(record).__name__}, not dict")
            novelty = record.get("novelty") or {}
            critique = record.get("critique") or {}
            result = {  # the SAME 5-field envelope the sync tool extracts
                "iteration_id": record.get("iteration_id"),
                "novelty_class": novelty.get("class"),
                "critic_verdict": critique.get("verdict"),
                "low_confidence": bool(novelty.get("low_confidence")
                                       or critique.get("low_confidence")),
                "journal_entry_path": record.get("journal_entry_path"),
            }
            finish_ticket(run_id, result)
        except Exception as exc:
            err = f"terminal-persistence: {type(exc).__name__}: {exc}"
            try:
                fail_ticket(run_id, err)
            except Exception:
                pass  # disk dead: pid reconciliation + caller timeout backstop
            runtime.log_event({
                "event_type": "tool_plane_submit_failed",
                "run_id": run_id, "error": err,
            })
        else:
            runtime.log_event({
                "event_type": "tool_plane_submit_finished",
                "run_id": run_id, "iteration_id": result["iteration_id"],
            })
    finally:
        # Guarded clear (2026-06-10 review): if write_active_run itself
        # raised, this thread owns nothing — an unconditional clear would
        # take active_run's legacy branch and clobber a foreign run's
        # mirror+twin that registered in the same window.
        if registered:
            active_run.clear_active_run()
        set_current_agent(None)
        _release_latch()


def _release_latch() -> None:
    """Clear _live if this thread still owns it (belt-and-braces: a dead
    thread already fails thread_live()'s is_alive check)."""
    global _live
    me = threading.current_thread()
    with _latch:
        if _live is me:
            _live = None


def poll(run_id: Any) -> dict:
    """Resolve a poll_run call to the exact honest payload for the ticket.

    Every read resolves module attributes at CALL time (tests monkeypatch
    TICKETS_DIR / ACTIVE_ITERATION_PATH / the active_run paths); the
    registry doc resolves via active_run._run_path so the registry-
    beside-mirror invariant holds under repointed paths."""
    if not isinstance(run_id, str):
        return {"tool": POLL_TOOL, "ok": False, "error": "run_id_must_be_string"}
    ticket = read_ticket(run_id)
    if ticket is None:
        # Only this seam's tickets are pollable — not host iteration ids,
        # not experiment runs (containment for foreign/unknown ids).
        return {"tool": POLL_TOOL, "ok": False, "error": "unknown_run_id"}
    if ticket.get("status") == "finished":
        return {"tool": POLL_TOOL, "ok": True, "result": {
            "run_id": run_id, "status": "finished",
            "topic": ticket.get("topic"),
            "submitted_at": ticket.get("submitted_at"),
            "finished_at": ticket.get("finished_at"),
            "result": ticket.get("result"),
        }}
    if ticket.get("status") == "failed":
        return {"tool": POLL_TOOL, "ok": True, "result": _failed_view(ticket)}
    # status "running" — only trustworthy if OUR process started the thread.
    if ticket.get("pid") != os.getpid():
        # Threads die with the process, so the executor cannot exist. The
        # ONE reconciliation write poll ever makes, of this seam's own
        # file; orphaned registry/mirror state is REPORTED, never
        # auto-deleted (rule 4 — cleanup stays a logged human/dev action).
        ticket = fail_ticket(run_id, "server_restart_mid_run")
        view = _failed_view(ticket)
        view["orphaned_registry"] = active_run._run_path(run_id).exists()
        return {"tool": POLL_TOOL, "ok": True, "result": view}
    registry = _read_json(active_run._run_path(run_id))
    if registry is not None:
        registry = {k: registry.get(k)
                    for k in ("kind", "label", "started_at", "heartbeat_at")}
    age = _age_s(registry.get("heartbeat_at")) if registry else None
    return {"tool": POLL_TOOL, "ok": True, "result": {
        "run_id": run_id, "status": "running",
        "topic": ticket.get("topic"),
        "submitted_at": ticket.get("submitted_at"),
        # null registry == the pre-registration window — poll again.
        "registry": registry,
        "heartbeat_age_s": age,
        # The ad_hoc heartbeat is written once (no mid-run refresh), so
        # age grows on healthy runs — informational, see STALE_HEARTBEAT_S.
        "stale": bool(age is not None and age > STALE_HEARTBEAT_S),
        # The host's single active-iteration slot; one-at-a-time means it
        # is ours while our ticket runs. Its mtime is the progress pulse.
        "active_iteration": _active_iteration_view(),
    }}


def _failed_view(ticket: dict) -> dict:
    return {
        "run_id": ticket.get("run_id"), "status": "failed",
        "topic": ticket.get("topic"),
        "submitted_at": ticket.get("submitted_at"),
        "finished_at": ticket.get("finished_at"),
        "error": ticket.get("error"),
    }


def _age_s(ts: Any) -> float | None:
    """Seconds since an ISO-Z timestamp; None when unparseable."""
    try:
        then = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return round((datetime.now(timezone.utc) - then).total_seconds(), 3)


def _active_iteration_view() -> dict | None:
    """Verbatim subset of run_state/active_iteration.json + its mtime.
    None when absent/malformed (between iterations, or pre-first-step)."""
    path = ACTIVE_ITERATION_PATH
    doc = _read_json(path)
    if doc is None:
        return None
    steps = doc.get("steps")
    view = {
        "iteration_id": doc.get("iteration_id"),
        "current_step": doc.get("current_step"),
        "latest_narration": doc.get("latest_narration"),
        "steps": ([{"name": s.get("name"), "status": s.get("status")}
                   for s in steps if isinstance(s, dict)]
                  if isinstance(steps, list) else None),
    }
    try:  # mtime == when nara last refreshed the board (per step)
        view["updated_at"] = datetime.fromtimestamp(
            path.stat().st_mtime, tz=timezone.utc
        ).isoformat().replace("+00:00", "Z")
    except OSError:
        view["updated_at"] = None
    return view
