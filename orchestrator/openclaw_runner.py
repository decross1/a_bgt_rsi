"""
Day 6 OrchestratorClient -- Python multiprocessing fallback.

Spawns one worker process per task with a hard wall-clock timeout. Validates
the worker_input contract (schema/worker_contract.schema.json) and never
raises on bad input: a malformed task returns a structured worker_output
with status="error" and the orchestrator logs a single rejection entry.

Each successful task appends THREE linked JSONL entries to
logs/orchestrator.jsonl, sharing a parent_request_id chain:

    orchestrator_dispatch  (parent = task.parent_request_id)
      -> worker_invocation (parent = dispatch.request_id)
        -> orchestrator_receipt (parent = worker_invocation.request_id)

The worker's wrapper call (logged separately to logs/day6.jsonl) carries
parent_request_id = worker_invocation.request_id, so tools/inspect_run.py
reconstructs the full four-level causal chain by sibling-discovering
logs/day6.jsonl alongside logs/orchestrator.jsonl.

Selected by state.fallbacks_taken.day6_orchestrator_isolation = "multiprocessing"
on the router branch when nemoclaw is unavailable (per CLAUDE.md inviolate
rule 7; Day 1 NemoClaw onboarding was skipped, see DECISIONS.md).
"""
import json
import multiprocessing as mp
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_ORCHESTRATOR_LOG = REPO_ROOT / "logs" / "orchestrator.jsonl"
DEFAULT_WRAPPER_LOG = REPO_ROOT / "logs" / "day6.jsonl"
# papers_recent lives in the main repo's chroma_db (cron writes there).
# Worktrees mount the same checkout; the path resolves from this file's
# location to the repo root via .claude/worktrees/<name>/orchestrator/.
DEFAULT_DB_PATH = Path("/home/decross1/projects/a_bgt_rsi/chroma_db")
DEFAULT_WORKER_TIMEOUT_S = 60  # DAY6-CONTRACT
KNOWN_TASK_TYPES = ("summarize_paper",)


def _utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _worker_entry(task, wrapper_log_path, db_path, parent_request_id,
                  result_queue):
    """Child process entry. Lazily imports the worker so this module stays
    cheap to import in the parent (tests do that on every run)."""
    try:
        from workers.summarize_paper import summarize
        result = summarize(
            arxiv_id=task["payload"]["arxiv_id"],
            log_path=wrapper_log_path,
            db_path=db_path,
            parent_request_id=parent_request_id,
        )
    except Exception as exc:  # surface to the parent, do not crash silently
        result = {
            "status": "error",
            "errors": [f"worker raised {type(exc).__name__}: {exc}"],
            "summary": None,
            "wrapper_request_id": None,
        }
    result_queue.put(result)


class OrchestratorClient:
    """Day 6 minimal orchestrator. Sequential by design; concurrency is a
    Week 2 problem."""

    def __init__(self, log_path=None, worker_timeout_s=DEFAULT_WORKER_TIMEOUT_S,
                 wrapper_log_path=None, db_path=None):
        self.log_path = Path(log_path or DEFAULT_ORCHESTRATOR_LOG)
        self.wrapper_log_path = Path(wrapper_log_path or DEFAULT_WRAPPER_LOG)
        self.db_path = str(db_path or DEFAULT_DB_PATH)
        self.worker_timeout_s = worker_timeout_s
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.wrapper_log_path.parent.mkdir(parents=True, exist_ok=True)
        # fork is appropriate here: vLLM is HTTP (no CUDA in the parent),
        # the wrapper opens its log file per-call (no inherited fd to
        # corrupt), and the OpenAI SDK uses lazy httpx pools. Spawn would
        # force REPO_ROOT onto every child's sys.path manually.
        self._ctx = mp.get_context("fork")

    # -- logging helpers --------------------------------------------------
    def _log(self, entry):
        with self.log_path.open("a") as fh:
            fh.write(json.dumps(entry) + "\n")

    def _entry(self, stage, request_id, parent_request_id, task_id, task_type,
               status, detail, duration_ms=None):
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

    # -- worker_input validation ------------------------------------------
    @staticmethod
    def _validate_input(task):
        """Return (errors, task_id, task_type). errors empty == accepted."""
        errors = []
        if not isinstance(task, dict):
            return ([f"input is not an object (got {type(task).__name__})"],
                    "<unknown>", None)
        for field in ("task_id", "task_type", "payload", "parent_request_id"):
            if field not in task:
                errors.append(f"missing required field '{field}'")
        tid = task.get("task_id")
        task_id = tid if isinstance(tid, str) and tid else "<unknown>"
        ttype = task.get("task_type")
        if "task_type" in task and (not isinstance(ttype, str) or not ttype):
            errors.append("task_type must be a non-empty string")
        elif isinstance(ttype, str) and ttype not in KNOWN_TASK_TYPES:
            errors.append(f"unknown task_type '{ttype}' "
                          f"(known: {', '.join(KNOWN_TASK_TYPES)})")
        payload = task.get("payload")
        if "payload" in task and not isinstance(payload, dict):
            errors.append("payload must be an object")
        elif isinstance(payload, dict) and ttype == "summarize_paper" \
                and not payload.get("arxiv_id"):
            errors.append("summarize_paper payload missing 'arxiv_id'")
        return errors, task_id, ttype

    def _error_output(self, task_id, errors):
        return {
            "task_id": task_id,
            "status": "error",
            "result": None,
            "errors": errors,
            "jsonl_log_path": str(self.log_path),
        }

    # -- main entrypoint ---------------------------------------------------
    def run_task(self, task):
        """Honours the OrchestratorClient.run_task contract: never raises on
        bad input, always returns a worker_output dict, always logs to
        self.log_path."""
        dispatch_id = str(uuid.uuid4())
        errors, task_id, ttype = self._validate_input(task)

        if errors:
            self._log(self._entry(
                "orchestrator_reject", dispatch_id, None, task_id, ttype,
                "error", f"input rejected: {'; '.join(errors)}"))
            return self._error_output(task_id, errors)

        parent = task.get("parent_request_id")
        arxiv_id = task["payload"]["arxiv_id"]
        worker_id = str(uuid.uuid4())
        receipt_id = str(uuid.uuid4())

        # Entry 1/3: orchestrator_dispatch
        self._log(self._entry(
            "orchestrator_dispatch", dispatch_id, parent, task_id, ttype,
            "dispatched", f"dispatching {ttype}({arxiv_id})"))

        # Entry 2/3: worker_invocation -- written BEFORE the worker starts
        # so the chain is visible even on crash/timeout.
        self._log(self._entry(
            "worker_invocation", worker_id, dispatch_id, task_id, ttype,
            "running",
            f"spawning worker process for {arxiv_id} "
            f"(timeout {self.worker_timeout_s}s)"))

        t0 = time.perf_counter()
        result_queue = self._ctx.Queue()
        proc = self._ctx.Process(
            target=_worker_entry,
            args=(task, str(self.wrapper_log_path), self.db_path,
                  worker_id, result_queue),
            daemon=False,
        )
        proc.start()
        proc.join(timeout=self.worker_timeout_s)

        if proc.is_alive():
            # Timeout: terminate cleanly; never leave an orphan worker.
            proc.terminate()
            proc.join(timeout=5)
            if proc.is_alive():
                proc.kill()
                proc.join()
            duration_ms = (time.perf_counter() - t0) * 1000.0
            # Entry 3/3: orchestrator_receipt (timeout)
            self._log(self._entry(
                "orchestrator_receipt", receipt_id, worker_id, task_id, ttype,
                "timeout",
                f"worker exceeded {self.worker_timeout_s}s; terminated",
                duration_ms=duration_ms))
            return {
                "task_id": task_id,
                "status": "timeout",
                "result": None,
                "errors": [f"worker exceeded {self.worker_timeout_s}s timeout"],
                "jsonl_log_path": str(self.log_path),
            }

        # Worker finished -- collect the result from the queue.
        try:
            child_result = result_queue.get(timeout=5)
        except Exception as exc:
            duration_ms = (time.perf_counter() - t0) * 1000.0
            self._log(self._entry(
                "orchestrator_receipt", receipt_id, worker_id, task_id, ttype,
                "error",
                f"worker process exited without delivering a result: {exc}",
                duration_ms=duration_ms))
            return self._error_output(
                task_id,
                [f"worker result unavailable: {type(exc).__name__}: {exc}"])

        duration_ms = (time.perf_counter() - t0) * 1000.0
        status = child_result.get("status")

        if status != "passed":
            self._log(self._entry(
                "orchestrator_receipt", receipt_id, worker_id, task_id, ttype,
                status or "error",
                f"worker reported: {'; '.join(child_result.get('errors') or [])}",
                duration_ms=duration_ms))
            return {
                "task_id": task_id,
                "status": status or "error",
                "result": None,
                "errors": child_result.get("errors") or ["worker failed"],
                "jsonl_log_path": str(self.log_path),
            }

        # Success.
        summary = child_result.get("summary") or ""
        self._log(self._entry(
            "orchestrator_receipt", receipt_id, worker_id, task_id, ttype,
            "passed",
            f"worker returned summary ({len(summary)} chars)",
            duration_ms=duration_ms))
        return {
            "task_id": task_id,
            "status": "passed",
            "result": {"arxiv_id": arxiv_id, "summary": summary},
            "errors": [],
            "jsonl_log_path": str(self.log_path),
        }
