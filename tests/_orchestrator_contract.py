#!/usr/bin/env python3
"""
Shared scaffolding for the Day 6 orchestrator robustness tests
(test_orchestrator_5_sequential.py, test_orchestrator_malformed_input.py).

This is a Track B helper, NOT a runnable test. It holds three things:

  1. load_orchestrator_client() -- imports the real OrchestratorClient
     from orchestrator/openclaw_runner.py (Day 6 builds it), or returns
     None if that file does not exist yet.

  2. MockOrchestratorClient -- a deterministic stand-in honouring the
     worker contract (schema/worker_contract.schema.json). It lets the
     Day 6 tests run TODAY under MOCK_LLM=1, before the real
     orchestrator exists. It NEVER calls an LLM endpoint.

  3. validate_worker_output() -- validates a result dict against the
     worker_contract schema's #/$defs/worker_output sub-schema.

ASSUMED OrchestratorClient CONTRACT (every assumption is tagged
DAY6-CONTRACT -- `grep -rn DAY6-CONTRACT tests/`). The real Day 6 task
day6_block2_worker_contract fixes only the *message* shapes; the *class*
API below is Track B's inference and may need reconciling on Day 6:

    client = OrchestratorClient(log_path="logs/orchestrator.jsonl",
                                worker_timeout_s=60)
    output = client.run_task(task)

  - `task` is a worker_input dict: {task_id, task_type, payload,
    parent_request_id}.
  - `run_task` returns a worker_output dict: {task_id, status, result,
    errors, jsonl_log_path}.
  - `run_task` NEVER raises on bad input -- malformed input yields
    status="error" with a non-empty `errors` list. Raising is itself a
    test failure ("orchestrator did not crash").
  - Each `run_task` call appends the task's causal chain to `log_path`
    (orchestrator dispatch -> worker invocation -> orchestrator
    receipt), linked by parent_request_id.

If Day 6 picks a different class API, update the DAY6-CONTRACT lines
here -- the message contract (the JSON schema) should not need to move.
"""
import importlib.util
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "schema" / "worker_contract.schema.json"

# The one task type Day 6 defines (plan.yaml day6_block2_orchestrator_*).
KNOWN_TASK_TYPES = ("summarize_paper",)


def _utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# --------------------------------------------------------------------------
# Loading the real orchestrator (Day 6) -- with no __init__.py required.
# --------------------------------------------------------------------------
def load_orchestrator_client():
    """Return (OrchestratorClient_class, load_error).

      - (cls, None)  -- the real Day 6 orchestrator is available.
      - (None, None) -- orchestrator/openclaw_runner.py does not exist yet
                        (pre-Day-6); the caller MAY fall back to the mock.
      - (None, str)  -- the file EXISTS but failed to load. The caller must
                        SURFACE this and never fall back to the mock: a
                        broken real orchestrator must not pass as a mock.

    Absent vs. broken is decided by the file's existence, not by a caught
    exception -- so a broken Day 6 orchestrator can never masquerade as
    'not built yet'. Tries a normal package import first, then a direct
    file load (so it works whether or not Day 6 adds
    orchestrator/__init__.py)."""
    path = REPO_ROOT / "orchestrator" / "openclaw_runner.py"
    if not path.exists():
        return None, None
    try:
        from orchestrator.openclaw_runner import OrchestratorClient  # noqa
        return OrchestratorClient, None
    except Exception:  # not a package / no __init__.py -- try a file load
        pass
    try:
        spec = importlib.util.spec_from_file_location("openclaw_runner", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as exc:
        return None, (f"{path} exists but failed to import: "
                      f"{type(exc).__name__}: {exc}")
    cls = getattr(mod, "OrchestratorClient", None)
    if cls is None:
        return None, f"{path} loaded but defines no OrchestratorClient"
    return cls, None


# --------------------------------------------------------------------------
# Worker-contract validation
# --------------------------------------------------------------------------
def validate_worker_output(obj):
    """Return a list of human-readable schema-violation strings for `obj`
    against #/$defs/worker_output. Empty list == valid.

    Degrades gracefully: if jsonschema or the schema file is unavailable,
    falls back to a structural required-fields check (mirrors the Day 3-4
    scaffold pattern)."""
    required = ["task_id", "status", "result", "errors", "jsonl_log_path"]
    try:
        import jsonschema
        full = json.loads(SCHEMA_PATH.read_text())
        sub = full["$defs"]["worker_output"]
        # Resolve $defs so any internal $ref still works when validating
        # the sub-schema in isolation.
        sub = {**sub, "$defs": full.get("$defs", {})}
        v = jsonschema.Draft202012Validator(sub)
        return [f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}"
                for e in v.iter_errors(obj)]
    except Exception:
        if not isinstance(obj, dict):
            return [f"<root>: expected object, got {type(obj).__name__}"]
        return [f"missing required field '{f}'"
                for f in required if f not in obj]


# --------------------------------------------------------------------------
# Mock orchestrator -- deterministic, no LLM, honours the worker contract.
# --------------------------------------------------------------------------
class MockOrchestratorClient:
    """Deterministic stand-in for the Day 6 OrchestratorClient.

    `run_task` validates the worker_input contract, then either runs the
    (stubbed) worker or returns a clean structured error. It never raises
    on bad input and never calls an LLM -- the worker's summarization step
    is stubbed behind MOCK_LLM."""

    def __init__(self, log_path, worker_timeout_s=60):
        self.log_path = Path(log_path)
        self.worker_timeout_s = worker_timeout_s  # DAY6-CONTRACT: 60 s
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    # -- internal logging: 3 linked entries per successful task -----------
    def _log(self, entry):
        with self.log_path.open("a") as fh:
            fh.write(json.dumps(entry) + "\n")

    def _entry(self, stage, request_id, parent_request_id, task_id,
               task_type, status, detail):
        return {
            "timestamp": _utc_now(),
            "request_id": request_id,
            "parent_request_id": parent_request_id,
            "stage": stage,
            "task_id": task_id,
            "task_type": task_type,
            "status": status,
            "detail": detail,
        }

    # -- input validation against the worker_input contract ---------------
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

    @staticmethod
    def _stub_summary(arxiv_id):
        """Stubbed worker output. The real worker asks Gemma 4 to summarize
        in ~100 words; under MOCK_LLM this canned text stands in. Track B
        never calls LOCAL_LLM_BASE_URL."""
        return (f"[MOCK_LLM summary of {arxiv_id}] This paper is "
                "summarized by a stubbed worker for the Day 6 orchestrator "
                "scaffold. The real worker retrieves the abstract from the "
                "papers_recent collection and calls Gemma 4; this text "
                "stands in so the robustness suite runs without a GPU.")

    def run_task(self, task):
        """Honours the OrchestratorClient.run_task contract. Never raises
        on bad input -- a malformed task yields a clean error output."""
        dispatch_id = str(uuid.uuid4())
        errors, task_id, ttype = self._validate_input(task)

        if errors:
            # Worker is never invoked; log a single rejection entry.
            self._log(self._entry(
                "orchestrator_reject", dispatch_id, None, task_id, ttype,
                "error", f"input rejected: {'; '.join(errors)}"))
            return self._error_output(task_id, errors)

        # Valid task: 3 linked entries -- dispatch -> worker -> receipt.
        if not os.environ.get("MOCK_LLM"):
            # Track B must not reach a real LLM. The real OrchestratorClient
            # handles non-mock execution on Day 6; the mock refuses it.
            return self._error_output(
                task_id,
                ["MockOrchestratorClient requires MOCK_LLM=1 "
                 "(real execution belongs to the Day 6 OrchestratorClient)"])

        parent = task.get("parent_request_id")
        arxiv_id = task["payload"]["arxiv_id"]
        worker_id = str(uuid.uuid4())
        receipt_id = str(uuid.uuid4())

        self._log(self._entry("orchestrator_dispatch", dispatch_id, parent,
                               task_id, ttype, "dispatched",
                               f"dispatching {ttype} for {arxiv_id}"))
        self._log(self._entry("worker_invocation", worker_id, dispatch_id,
                               task_id, ttype, "running",
                               "worker summarizing (MOCK_LLM stub)"))
        summary = self._stub_summary(arxiv_id)
        self._log(self._entry("orchestrator_receipt", receipt_id, worker_id,
                               task_id, ttype, "passed",
                               "worker returned summary"))

        return {
            "task_id": task_id,
            "status": "passed",
            "result": {"arxiv_id": arxiv_id, "summary": summary},
            "errors": [],
            "jsonl_log_path": str(self.log_path),
        }


def make_summarize_task(task_id, arxiv_id, parent_request_id=None):
    """Build a well-formed summarize_paper worker_input dict."""
    return {
        "task_id": task_id,
        "task_type": "summarize_paper",
        "payload": {"arxiv_id": arxiv_id},
        "parent_request_id": parent_request_id,
    }
