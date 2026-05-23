"""Week-2 unlock prerequisites (ui_plan.md §11.3).

One read-only endpoint, five sections, each mapping to one bullet in
§11.3. The UI is read-only (ui_plan.md §2; operating-contract rule 8) —
"attest" and "rollback" affordances surface the human-runnable command,
not an action the UI executes.

`verify_log_integrity` itself lives in `agent_wrapper/wrapper.py`, which
is outside Track D's zone (agent/ownership.yaml). Track D cannot import
it. We re-implement the line-by-line validator here against the run-log
schema documented in plan.yaml Appendix C — same required field set,
same "0 malformed" pass criterion.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


# Required field set for every run-log entry. Source: plan.yaml Appendix C
# "run-log entry schema", referenced from CLAUDE.md §"Inviolate rules" #8.
RUN_LOG_REQUIRED = (
    "timestamp", "day_id", "task_id", "status",
    "observable_actual", "observable_expected", "duration_ms",
)


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _iter_jsonl(path):
    """Yield (line_no, parsed_or_None). None means malformed JSON."""
    path = Path(path)
    if not path.exists():
        return
    try:
        with open(path, encoding="utf-8") as fh:
            for line_no, raw in enumerate(fh, 1):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    yield line_no, json.loads(raw)
                except json.JSONDecodeError:
                    yield line_no, None
    except OSError:
        return


def _rolling_cutoff(now_iso, days):
    if not now_iso or not days:
        return None
    try:
        now = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    cutoff = (now - timedelta(days=days)).astimezone(timezone.utc)
    return cutoff.isoformat().replace("+00:00", "Z")


def verify_run_log_integrity(run_log_path, rolling_window_days=7, now_iso=None):
    """Verify run_state/week1.run.jsonl integrity.

    A line is malformed if it does not parse OR is missing any required
    field. Returns the pass-signal alignment §4.3 expects: ok=True iff
    zero malformed entries in the file. `rolling_count` is informational
    (how many entries fall inside the rolling window).
    """
    if not Path(run_log_path).exists():
        return {"available": False, "ok": None, "total_lines": 0,
                "malformed_lines": [], "rolling_window_days": rolling_window_days,
                "rolling_count": 0}
    total = 0
    malformed_lines = []
    rolling_count = 0
    cutoff = _rolling_cutoff(now_iso, rolling_window_days)
    for line_no, record in _iter_jsonl(run_log_path):
        total += 1
        if record is None:
            malformed_lines.append(line_no)
            continue
        if any(k not in record for k in RUN_LOG_REQUIRED):
            malformed_lines.append(line_no)
            continue
        ts = record.get("timestamp")
        if cutoff is None or (isinstance(ts, str) and ts >= cutoff):
            rolling_count += 1
    return {"available": True, "ok": not malformed_lines,
            "total_lines": total, "malformed_lines": malformed_lines,
            "rolling_window_days": rolling_window_days,
            "rolling_count": rolling_count}


def read_soft_gate_queue(attestations_path):
    """Pending soft-gate requests in run_state/attestations.jsonl.

    The schema-comment line at the head is skipped. A request is pending
    until a matching `approved | rejected | no_objection` entry lands
    for the same task_id (autonomy.md §2.1 lifecycle).

    Each pending entry carries a `rollback_command` — the CLI the human
    would run to walk back a soft-gate auto-proceed (informational; the
    UI does not execute it).
    """
    path = Path(attestations_path)
    if not path.exists():
        return {"available": False, "pending": []}
    requests = {}
    closed = set()
    for _, record in _iter_jsonl(attestations_path):
        if record is None or "_schema_comment" in record:
            continue
        kind = record.get("kind")
        task_id = record.get("task_id")
        if kind == "request" and task_id:
            requests[task_id] = record
        elif kind in ("approved", "rejected", "no_objection") and task_id:
            closed.add(task_id)
    pending = []
    for task_id, rec in requests.items():
        if task_id in closed:
            continue
        pending.append({
            "task_id": task_id,
            "agent_id": rec.get("agent_id"),
            "summary": rec.get("summary"),
            "expected_observable": rec.get("expected_observable"),
            "observed_actual": rec.get("observed_actual"),
            "ts": rec.get("ts"),
            "sla_hours": rec.get("sla_hours"),
            "rollback_command":
                f"python tools/rollback_attestation.py --task-id {task_id}",
        })
    pending.sort(key=lambda p: p.get("ts") or "")
    return {"available": True, "pending": pending}


def read_hard_gate_pending(state):
    """Render state.human_gates_pending with an attest_command per entry."""
    items = []
    for entry in (state.get("human_gates_pending") or []):
        if isinstance(entry, str):
            task_id = entry
            items.append({"task_id": task_id,
                          "attest_command":
                              f"python tools/attest_gate.py --task-id {task_id}"})
        elif isinstance(entry, dict):
            task_id = entry.get("task_id") or entry.get("id")
            out = dict(entry)
            out["attest_command"] = (
                f"python tools/attest_gate.py --task-id {task_id}"
                if task_id else None)
            items.append(out)
    return {"available": True, "pending": items}


def compute_unlock_status(state_file, run_log_file, attestations_file,
                          now_iso=None):
    """Return the consolidated §11.3 Week-2-unlock payload.

    Each section is independently available=true/false so the dashboard
    can render partial state when some files have not been written yet
    (mirrors the existing /api/events, /api/robustness pattern).
    """
    state = _read_json(state_file) or {}
    return {
        "milestone": "ui_v1_week2_unlock",
        "current_day": state.get("current_day"),
        "run_log_integrity":
            verify_run_log_integrity(run_log_file, now_iso=now_iso),
        "soft_gate_queue": read_soft_gate_queue(attestations_file),
        "hard_gates_pending": read_hard_gate_pending(state),
        "metric_log": state.get("metric_log") or {},
        "fallbacks_taken": state.get("fallbacks_taken") or {},
    }
