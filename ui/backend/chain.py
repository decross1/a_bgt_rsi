"""Causal-chain reconstruction over the apparatus's JSONL logs.

See ui_plan.md sections 4.2-4.3, 5.2. There is no single calls.jsonl: the
call log is the union of logs/day*.jsonl and logs/exp*.jsonl. LogStore
indexes those plus logs/orchestrator.jsonl incrementally (byte-offset
tailing via JsonlTailer) so repeated requests do not re-parse whole files.

A chain is reconstructed by walking parent_request_id: the orchestrator
dispatch for a task carries the root request_id; call records whose
parent_request_id points at it (transitively) form the tree.
"""
import json
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


# Tool calls reach the inspector in one of three shapes (ui_plan.md section 9):
#
#   1. As their own call-log lines, with a request_id and a parent_request_id
#      — handled by the ordinary parent_request_id walk.
#   2. Embedded as a `tool_calls` array inside a wrapper record. Each entry is
#      synthesized into a child node; an entry's own latency_ms, when present,
#      is summed into total_latency_ms exactly as a separate-line tool call's
#      latency is (r4) — so the total does not depend on shapes 1 vs 2.
#   3. As an OpenAI-style tool-call JSON string in the wrapper record's
#      `completion` field — the shape Track A's real day-4 logs actually use
#      (logs/day4_e2e.jsonl, logs/day4_robust.jsonl). The day-4 sync built
#      for shapes 1-2 against fixtures; shape 3 was the real answer (r7). A
#      completion tool call has no latency of its own — the wrapper record's
#      latency_ms already covers the call that produced it — so its
#      synthesized node contributes 0 to total_latency_ms.
#
# All three converge to one inspector tree: a synthesized tool call is a child
# node (kind="tool", embedded=True, request_id=None), so a chain renders the
# same tree regardless of how the wrapper logged its tool use.
# total_latency_ms stays a labelled rough sum, not wall-clock.
EMBEDDED_TOOL_KEY = "tool_calls"


def tool_call_name(tool):
    """Best-effort tool name from a tool-call object of either shape.

    Embedded `tool_calls` entries (shape 2) carry `name` at the top level;
    OpenAI-style tool calls parsed out of `completion` (shape 3) nest it
    under `function.name`. Returns None when neither is present.
    """
    if not isinstance(tool, dict):
        return None
    name = tool.get("name")
    if isinstance(name, str) and name:
        return name
    fn = tool.get("function")
    if isinstance(fn, dict) and isinstance(fn.get("name"), str) and fn["name"]:
        return fn["name"]
    return None


def _is_openai_tool_call(obj):
    """True when obj is an OpenAI-style function tool-call object.

    The shape vLLM emits into `completion`: {id, type: "function",
    function: {name, arguments}}. Stricter than `tool_call_name` so an
    ordinary JSON array landing in a completion is not mistaken for tools.
    """
    if not isinstance(obj, dict):
        return False
    fn = obj.get("function")
    if isinstance(fn, dict) and isinstance(fn.get("name"), str) and fn["name"]:
        return True
    return obj.get("type") == "function" and isinstance(obj.get("name"), str)


def parse_completion_tool_calls(completion):
    """Extract OpenAI-style tool calls embedded in a `completion` string.

    Shape 3 (see the module comment above): day-4 wrapper records log the
    model's tool call in the `completion` field as a JSON string — a list of
    {id, type, function: {name, arguments}} objects — rather than as a
    structured `tool_calls` array.

    Returns (tool_calls, malformed):
      - ([...], False) — completion parsed to a non-empty tool-call list.
      - ([],   False) — completion is an ordinary text answer, no tool call.
      - ([],   True)  — completion opens like a tool-call array but does not
                        parse. Surfaced as malformed, never silently repaired
                        (CLAUDE.md rule 4 / ui_plan.md operating rule 8).
    """
    if not isinstance(completion, str):
        return [], False
    stripped = completion.strip()
    if not stripped:
        return [], False
    # A completion that opens an array and carries both an OpenAI tool-call
    # `"type"` and `"function"` key is almost certainly a tool-call payload;
    # if it then fails to parse it is malformed — flagged, not fixed.
    # Requiring both substrings keeps ordinary prose that merely opens with
    # "[" from being mis-flagged.
    looks_like_tool_payload = (stripped.startswith("[")
                               and '"function"' in stripped
                               and '"type"' in stripped)
    try:
        parsed = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        return [], looks_like_tool_payload
    if not isinstance(parsed, list):
        return [], False
    tool_calls = [item for item in parsed if _is_openai_tool_call(item)]
    return (tool_calls, False) if tool_calls else ([], False)


def _tool_node(tool, parent_request_id):
    return {
        "kind": "tool",
        "request_id": None,                      # synthesized — no own request_id
        "parent_request_id": parent_request_id,
        "caller_tag": tool_call_name(tool) or tool.get("caller_tag") or "tool",
        "timestamp": tool.get("timestamp"),
        "latency_ms": tool.get("latency_ms"),
        "parse_error": bool(tool.get("parse_error")),
        "embedded": True,
        "raw": tool,                             # opaque passthrough for the inspector
        "children": [],
    }


def _call_node(record):
    embedded = record.get(EMBEDDED_TOOL_KEY)
    # A wrapper recorded its tool_calls as the wrong type (e.g. a string left by
    # an upstream serializer bug). Tracked as its own flag and rendered as its
    # own badge — kept separate from `parse_error` (the record's explicit flag)
    # so the inspector banner can react to malformed_tool_calls specifically
    # rather than to any parse_error in the chain.
    tool_calls_malformed = embedded is not None and not isinstance(embedded, list)
    # Shape 3: the model's tool call logged as an OpenAI-style JSON string in
    # `completion` (Track A's real day-4 logs). A completion that opens like a
    # tool-call array but fails to parse is flagged the same way — surfaced,
    # never silently repaired.
    completion_tools, completion_malformed = parse_completion_tool_calls(
        record.get("completion"))
    if completion_malformed:
        tool_calls_malformed = True
    node = {
        "kind": "call",
        "request_id": record.get("request_id"),
        "parent_request_id": record.get("parent_request_id"),
        "caller_tag": record.get("caller_tag"),
        "timestamp": record.get("timestamp"),
        "latency_ms": record.get("latency_ms"),
        "parse_error": bool(record.get("parse_error")),
        "tool_calls_malformed": tool_calls_malformed,
        # Day-3.5 schema addition (optional). Pass through if present and shaped
        # like a list — the inspector renders each retrieval doc generically.
        "retrieval_context": (record.get("retrieval_context")
                              if isinstance(record.get("retrieval_context"), list)
                              else None),
        "embedded": False,
        "raw": record,                           # opaque passthrough for the inspector
        "children": [],
    }
    if isinstance(embedded, list):
        for tool in embedded:
            if isinstance(tool, dict):
                node["children"].append(_tool_node(tool, record.get("request_id")))
    for tool in completion_tools:
        node["children"].append(_tool_node(tool, record.get("request_id")))
    return node


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
        # Every node with a numeric latency contributes — including tool nodes,
        # embedded or separate-line — so the total does not depend on how the
        # wrapper logged its tools (see EMBEDDED_TOOL_KEY comment above).
        if isinstance(latency, (int, float)):
            counters["latency"] += latency
        for child in node["children"]:
            tally(child)

    tally(root)
    return {"task_id": task_id, "found": True, "malformed": malformed,
            "root": root, "node_count": counters["nodes"],
            "total_latency_ms": counters["latency"],
            "malformed_tool_calls": _count_malformed_tool_calls(root)}


def _count_malformed_tool_calls(node):
    """Count nodes whose tool_calls payload was the wrong shape.

    Drives the inspector's red banner — narrowly: only nodes flagged
    `tool_calls_malformed` contribute. Generic `parse_error` (a wrapper that
    failed for some reason unrelated to tool_calls) is a per-node badge, not a
    banner-level signal. Conflating the two would fire the banner on any
    failed wrapper, which misrepresents the cause.
    """
    total = 1 if node.get("tool_calls_malformed") else 0
    for child in node.get("children", []):
        total += _count_malformed_tool_calls(child)
    return total


def build_chain_by_request_id(store, root_request_id):
    """Reconstruct a tool-call chain rooted at an arbitrary request_id.

    Day-4 tool-call chains land before day 6's orchestrator runs, so they are
    rooted at a wrapper request (no orchestrator dispatch). build_chain keyed
    by task_id can't reach them; this walker is the read path.

    Returns the same shape as build_chain but with `root_request_id` in place
    of `task_id` and no `dispatch` root node — the wrapper record is the tree
    root. Returns found=False if no record carries that request_id.
    """
    store.refresh()
    record = store.calls_by_id.get(root_request_id)
    if record is None:
        return {"root_request_id": root_request_id, "found": False,
                "malformed": False, "root": None, "node_count": 0,
                "total_latency_ms": 0, "malformed_tool_calls": 0}

    seen = {root_request_id}
    malformed = False

    def attach_children(node, request_id):
        nonlocal malformed
        for child_record in store.children.get(request_id, []):
            child_id = child_record.get("request_id")
            if child_id in seen:
                malformed = True
                continue
            seen.add(child_id)
            child = _call_node(child_record)
            attach_children(child, child_id)
            node["children"].append(child)

    root = _call_node(record)
    attach_children(root, record.get("request_id"))

    counters = {"nodes": 0, "latency": 0}

    def tally(node):
        counters["nodes"] += 1
        latency = node.get("latency_ms")
        if isinstance(latency, (int, float)):
            counters["latency"] += latency
        for child in node["children"]:
            tally(child)

    tally(root)
    return {"root_request_id": root_request_id, "found": True,
            "malformed": malformed, "root": root,
            "node_count": counters["nodes"],
            "total_latency_ms": counters["latency"],
            "malformed_tool_calls": _count_malformed_tool_calls(root)}


def recent_tasks(store, limit=50):
    """Most-recent orchestrator dispatches, latest first. See ui_plan.md section 5.2.

    Sort key precedence: `timestamp` (Day-6+ schema — every orchestrator
    record carries one) -> `dispatch_ts` (pre-Day-6 fallback). The Day-7
    UX audit caught the original sort relying on `dispatch_ts` alone,
    which Day-6+ records do not carry — every record sorted as "" and
    the result was dict-insertion order, pushing fresh experiment tasks
    below stale `summarize_paper` rows. See ui_plan.md r10.
    """
    store.refresh()

    def sort_key(record):
        return (record.get("timestamp")
                or record.get("dispatch_ts")
                or "")

    ordered = sorted(store.orch_by_task.values(), key=sort_key, reverse=True)
    summary = []
    for record in ordered[:max(0, limit)]:
        summary.append({
            "task_id": record.get("task_id"),
            "task_type": record.get("task_type"),
            "status": record.get("status"),
            "worker_pid": record.get("worker_pid"),
            # Day-6+ records carry `timestamp` + `stage`; older ones carry
            # `dispatch_ts` + `receipt_ts`. Surface both so the frontend
            # can render either without an extra round-trip.
            "timestamp": record.get("timestamp"),
            "stage": record.get("stage"),
            # Human-readable per-stage detail ("spawning worker process for
            # 2605.21448 …"). Surfaced so the monitor's HERO worker rows can
            # render "what it's doing"; enrich() passes it straight through.
            "detail": record.get("detail"),
            "dispatch_ts": record.get("dispatch_ts"),
            "receipt_ts": record.get("receipt_ts"),
        })
    return summary
