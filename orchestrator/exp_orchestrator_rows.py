"""
Experiment orchestrator-rows helper (UI ask #3).

Experiment sub-tasks (exp00x scripts) run outside the OrchestratorClient's
multiprocessing path, so the UI worker table + causal graph stay dark while an
experiment runs. The UI reader lights up off logs/orchestrator.jsonl rows
shaped exactly like OrchestratorClient emits (orchestrator/openclaw_runner.py:
the orchestrator_dispatch -> worker_invocation -> orchestrator_receipt triple).

This module emits that same triple for an experiment sub-task so the existing
UI reader renders it with ZERO ui change. Append-only; never raises.
"""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ORCHESTRATOR_LOG = REPO_ROOT / "logs" / "orchestrator.jsonl"


def _utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _entry(stage, request_id, parent_request_id, task_id, task_type, status,
           detail, duration_ms=None):
    # Field shape matches OrchestratorClient._entry exactly.
    e = {
        "timestamp": _utc_now(),
        "request_id": request_id,
        "parent_request_id": parent_request_id,
        "stage": stage,
        "task_id": task_id,
        "task_type": task_type,
        "status": status,
        "detail": detail,
    }
    if duration_ms is not None:
        e["duration_ms"] = duration_ms
    return e


def emit_task_triple(*, task_id, task_type, status, duration_ms, run_id=None,
                     log_path=DEFAULT_ORCHESTRATOR_LOG):
    """Append the three correctly-parented orchestrator rows for one
    experiment sub-task so the UI worker table + graph light up.

    Parent chain mirrors OrchestratorClient:
        orchestrator_dispatch  (parent = run_id)
          -> worker_invocation (parent = dispatch.request_id)
            -> orchestrator_receipt (parent = worker_invocation.request_id)

    Append-only; never raises. A logging failure must not take down the
    experiment that called it.
    """
    try:
        dispatch_id = str(uuid.uuid4())
        worker_id = str(uuid.uuid4())
        receipt_id = str(uuid.uuid4())

        rows = [
            _entry("orchestrator_dispatch", dispatch_id, run_id, task_id,
                   task_type, "dispatched", f"dispatching {task_type}"),
            _entry("worker_invocation", worker_id, dispatch_id, task_id,
                   task_type, "running", f"running {task_type}"),
            _entry("orchestrator_receipt", receipt_id, worker_id, task_id,
                   task_type, status, f"{task_type} {status}",
                   duration_ms=duration_ms),
        ]

        p = Path(log_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        # Append-only telemetry must never raise into the experiment.
        pass
