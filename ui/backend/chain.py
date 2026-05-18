"""Causal-chain reconstruction over the apparatus's JSONL logs.

See ui_plan.md sections 4.2-4.3, 5.2. There is no single calls.jsonl: the
call log is the union of logs/day*.jsonl and logs/exp*.jsonl. LogStore
indexes those plus logs/orchestrator.jsonl incrementally (byte-offset
tailing via JsonlTailer) so repeated requests do not re-parse whole files.

A chain is reconstructed by walking parent_request_id: the orchestrator
dispatch for a task carries the root request_id; call records whose
parent_request_id points at it (transitively) form the tree.
"""
from collections import defaultdict
from pathlib import Path

from .tailer import JsonlTailer

ORCHESTRATOR_FILE = "orchestrator.jsonl"
CALL_LOG_GLOBS = ("day*.jsonl", "exp*.jsonl")


class LogStore:
    """In-memory, incrementally-updated index over the apparatus logs."""

    def __init__(self, logs_dir):
        self.logs_dir = Path(logs_dir)
        self._tailers = {}                       # path -> JsonlTailer
        self.calls_by_id = {}                    # request_id -> call record
        self.children = defaultdict(list)        # parent_request_id -> [records]
        self.orch_by_task = {}                   # task_id -> orchestrator record

    def _log_files(self):
        files = [(self.logs_dir / ORCHESTRATOR_FILE, "orchestrator")]
        for pattern in CALL_LOG_GLOBS:
            for path in sorted(self.logs_dir.glob(pattern)):
                files.append((path, "call"))
        return files

    def refresh(self):
        """Pick up new files and newly-appended lines. Cheap to call per request."""
        for path, kind in self._log_files():
            tailer = self._tailers.get(path)
            if tailer is None:
                tailer = JsonlTailer(path)
                self._tailers[path] = tailer
            for record in tailer.read_new():
                if kind == "orchestrator":
                    self._index_orchestrator(record)
                else:
                    self._index_call(record)

    def _index_call(self, record):
        request_id = record.get("request_id")
        if request_id is None:
            return
        self.calls_by_id[request_id] = record
        self.children[record.get("parent_request_id")].append(record)

    def _index_orchestrator(self, record):
        task_id = record.get("task_id")
        if task_id is None:
            return
        self.orch_by_task[task_id] = record      # latest line for a task wins


def _call_node(record):
    return {
        "kind": "call",
        "request_id": record.get("request_id"),
        "parent_request_id": record.get("parent_request_id"),
        "caller_tag": record.get("caller_tag"),
        "timestamp": record.get("timestamp"),
        "latency_ms": record.get("latency_ms"),
        "parse_error": bool(record.get("parse_error")),
        "raw": record,                           # opaque passthrough for the inspector
        "children": [],
    }


def build_chain(store, task_id):
    """Reconstruct the causal tree for one task_id. See ui_plan.md section 5.2.

    Returns {task_id, found, malformed, root, node_count, total_latency_ms}.
    `malformed` is True when a parent_request_id cycle was detected (a re-run
    that reused an id); the walk stops recursing rather than looping forever.
    """
    store.refresh()
    orch = store.orch_by_task.get(task_id)
    if orch is None:
        return {"task_id": task_id, "found": False, "malformed": False,
                "root": None, "node_count": 0, "total_latency_ms": 0}

    root_request_id = orch.get("parent_request_id")
    seen = set()
    malformed = False

    def attach_children(node, request_id):
        nonlocal malformed
        for child_record in store.children.get(request_id, []):
            child_id = child_record.get("request_id")
            if child_id in seen:                 # cycle
                malformed = True
                continue
            seen.add(child_id)
            child = _call_node(child_record)
            attach_children(child, child_id)
            node["children"].append(child)

    root = {
        "kind": "dispatch",
        "task_id": task_id,
        "task_type": orch.get("task_type"),
        "status": orch.get("status"),
        "worker_pid": orch.get("worker_pid"),
        "request_id": root_request_id,
        "parent_request_id": None,
        "timestamp": orch.get("dispatch_ts"),
        "latency_ms": None,
        "raw": orch,
        "children": [],
    }
    attach_children(root, root_request_id)

    counters = {"nodes": 0, "latency": 0}

    def tally(node):
        counters["nodes"] += 1
        latency = node.get("latency_ms")
        if isinstance(latency, (int, float)):
            counters["latency"] += latency
        for child in node["children"]:
            tally(child)

    tally(root)
    return {"task_id": task_id, "found": True, "malformed": malformed,
            "root": root, "node_count": counters["nodes"],
            "total_latency_ms": counters["latency"]}


def recent_tasks(store, limit=50):
    """Most-recent orchestrator dispatches, latest first. See ui_plan.md section 5.2."""
    store.refresh()
    ordered = sorted(store.orch_by_task.values(),
                     key=lambda r: r.get("dispatch_ts") or "", reverse=True)
    summary = []
    for record in ordered[:max(0, limit)]:
        summary.append({
            "task_id": record.get("task_id"),
            "task_type": record.get("task_type"),
            "status": record.get("status"),
            "worker_pid": record.get("worker_pid"),
            "dispatch_ts": record.get("dispatch_ts"),
            "receipt_ts": record.get("receipt_ts"),
        })
    return summary
