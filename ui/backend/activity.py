"""PAGE A — Live Activity Graph + Agent Monitor.

Two read-only endpoints over the apparatus logs (and the UI telemetry
sample stream), mounted at ``/api/activity``:

- ``GET /api/activity/graph?limit=N`` — flattens the per-task causal
  trees (orchestrator dispatch -> wrapper call -> synthesized tool) into
  a node+edge list for the @xyflow/react graph. Each node carries the
  ``request_id`` the frontend deep-links into the existing inspector at
  ``/chain/req/:requestId``; for that linkage to resolve, this router must
  read the SAME ``logs_dir`` the main app uses.
- ``GET /api/activity/monitor`` — what is active *right now*: recent
  orchestrator dispatches still in flight, cross-referenced against the
  latest telemetry sample's ``processes[]`` for cpu/rss, plus a clearly
  labelled ``synthetic_inference`` block. The per-worker decode-step /
  tokens-generated / ETA numbers DO NOT EXIST on disk anywhere — they
  come from a fixture and are flagged ``synthetic: True`` so the frontend
  can mark them as not-yet-measured (needs ``worker_activity.jsonl`` from
  the primary session). CLAUDE.md rule 4: never present synthetic numbers
  as measured.

Both endpoints degrade to ``{"available": false, ...}`` when their source
file/dir is absent — they never 500 on missing data and never fabricate.
Reads are read-only; the UI never mutates apparatus state.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter

from .chain import LogStore, build_chain, recent_tasks

# _REPO == the ui-session worktree root (this file is ui/backend/activity.py).
_REPO = Path(__file__).resolve().parents[2]
DEFAULT_LOGS_DIR = _REPO / "logs"
DEFAULT_TELEMETRY = _REPO / "ui" / "logs" / "telemetry.jsonl"

ORCHESTRATOR_FILE = "orchestrator.jsonl"

# A single experiment task's chain can transitively pull in its entire call
# log (thousands of wrapper-call records) via parent_request_id. That is
# neither legible as a graph nor cheap to render — react-flow chokes on
# thousands of nodes and the payload balloons to megabytes. Bound the graph
# to a render-able size and flag truncation; the inspector (/chain/req/...)
# remains the tool for walking a full chain in depth.
MAX_GRAPH_NODES = 250

# Statuses that mean "this task is still doing something" — drives the
# monitor's `active` partition and the graph node coloring.
ACTIVE_STATUSES = {"started", "dispatched", "running"}

# Synthetic per-worker inference internals. These fields have no on-disk
# source today; they are surfaced under a clearly-named key with
# `synthetic: True` so the frontend can render the "needs
# worker_activity.jsonl (primary-session)" marker. See module docstring.
SYNTHETIC_INFERENCE = {
    "synthetic": True,
    "source": "fixture",
    "needs": "worker_activity.jsonl (primary-session)",
    "note": "decode-step / tokens-generated / ETA are NOT measured — placeholder.",
    "workers": [
        {
            "task_id": "synthetic-demo",
            "decode_step": 312,
            "tokens_generated": 312,
            "tokens_target": 512,
            "eta_s": 4.7,
            "tok_per_s": 42.0,
        }
    ],
}


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_ts(ts: str) -> datetime:
    """Parse an ISO timestamp for ORDERING (max) — never for display.

    The orchestrator writes via datetime.isoformat(), which drops the
    fractional second when microseconds == 0 ('…14Z') but keeps it
    otherwise ('…14.5Z'); a raw-string max mis-orders the two at the same
    integer second. Parse to an aware datetime so the comparison is by
    instant. Unparseable strings sort to the bottom (datetime.min, UTC) so a
    malformed row can never win the max.
    """
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return datetime.min.replace(tzinfo=timezone.utc)


def _status_for(status: str | None) -> str:
    """Normalize an orchestrator/call status into one of the tones the
    frontend keys colors off of: 'active' | 'ok' | 'error' | 'unknown'."""
    if status in ACTIVE_STATUSES:
        return "active"
    if status == "passed":
        return "ok"
    if status in ("failed", "error", "rejected"):
        return "error"
    return "unknown"


def _latest_processes(telemetry_path: Path) -> dict[int, dict]:
    """pid -> {cpu_pct, rss_mb} from the most recent telemetry sample.

    Reads only the tail of the file (one line is enough) so it stays cheap
    as telemetry.jsonl grows. Returns {} when the file is absent or has no
    parseable processes[].
    """
    if not telemetry_path.exists():
        return {}
    try:
        size = telemetry_path.stat().st_size
        window = min(size, 64 * 1024)
        with open(telemetry_path, "rb") as fh:
            fh.seek(size - window)
            data = fh.read()
    except OSError:
        return {}
    lines = [ln for ln in data.decode("utf-8", errors="replace").splitlines() if ln.strip()]
    for line in reversed(lines):
        try:
            sample = json.loads(line)
        except json.JSONDecodeError:
            continue
        procs = sample.get("processes")
        if not isinstance(procs, list):
            return {}
        out: dict[int, dict] = {}
        for proc in procs:
            if not isinstance(proc, dict):
                continue
            pid = proc.get("pid")
            if isinstance(pid, int):
                out[pid] = {
                    "cpu_pct": proc.get("cpu_pct"),
                    "rss_mb": proc.get("rss_mb"),
                    "name": proc.get("name"),
                }
        return out
    return {}


def _flatten_tree(node: dict, nodes: list, edges: list, parent_id: str | None,
                  task_id: str | None, seen_ids: set, state: dict,
                  depth: int = 0) -> None:
    """Walk a build_chain tree, appending {id,kind,label,...} nodes and
    parent->child edges. `id` is request_id when present, else a stable
    synthesized id (so synthesized tool nodes still get an id and an edge).

    Stops once the shared node budget (`state["max"]`) is reached and marks
    `state["truncated"]`, so one giant experiment chain cannot blow up the
    graph payload or the react-flow render. `state["max_depth"]` bounds how
    deep the walk recurses: 0 = roots only (the navigable "overview"), None =
    unlimited (the "full" detail view, still node-capped).
    """
    if len(nodes) >= state["max"]:
        state["truncated"] = True
        return
    request_id = node.get("request_id")
    kind = node.get("kind", "call")
    if request_id:
        node_id = request_id
    else:
        # Synthesized tool node has no request_id of its own — derive a
        # stable id from its parent + caller_tag so it is addressable but
        # NOT mistaken for a real request_id (the frontend won't deep-link
        # a node whose request_id is null).
        tag = node.get("caller_tag") or kind
        node_id = f"{parent_id or task_id or 'root'}::{tag}::{len(nodes)}"

    # De-dup: a request_id can appear once. Guards against a malformed
    # re-run that reused an id (build_chain already breaks the cycle, but
    # the flattened list must still carry unique node ids for the graph).
    if node_id in seen_ids:
        if parent_id is not None:
            edges.append({"id": f"{parent_id}->{node_id}",
                          "source": parent_id, "target": node_id})
        return
    seen_ids.add(node_id)

    if kind == "dispatch":
        label = node.get("task_type") or task_id or "dispatch"
        status = node.get("status")
    elif kind == "tool":
        label = node.get("caller_tag") or "tool"
        status = "error" if node.get("parse_error") else "ok"
    else:  # call
        label = node.get("caller_tag") or "call"
        status = "error" if node.get("parse_error") else None

    nodes.append({
        "id": node_id,
        "kind": kind,
        "label": label,
        "task_id": task_id,
        # Only real request_ids are deep-linkable; synthesized ids are null.
        "request_id": request_id,
        "status": _status_for(status) if kind != "tool" else status,
    })
    if parent_id is not None:
        edges.append({"id": f"{parent_id}->{node_id}",
                      "source": parent_id, "target": node_id})

    max_depth = state.get("max_depth")
    if max_depth is None or depth < max_depth:
        for child in node.get("children", []):
            _flatten_tree(child, nodes, edges, node_id, task_id, seen_ids,
                          state, depth + 1)


def register(app, *, logs_dir: Path = DEFAULT_LOGS_DIR,
             telemetry_file: Path = DEFAULT_TELEMETRY) -> APIRouter:
    """Attach the PAGE A router. Defaults are baked in so the integrator
    adds exactly one ``register(app)`` call; tests pin tmp paths."""
    logs_dir = Path(logs_dir)
    telemetry_file = Path(telemetry_file)
    store = LogStore(logs_dir)
    router = APIRouter(prefix="/api/activity", tags=["activity"])

    @router.get("/graph")
    def graph(limit: int = 25, detail: str = "full"):
        """`detail=overview` shows one node per task (dispatch roots only) —
        the navigable default the frontend requests. `detail=full` expands
        each task's whole causal chain (node-capped). Anything else == full."""
        orch_path = logs_dir / ORCHESTRATOR_FILE
        if not orch_path.exists():
            return {"available": False,
                    "reason": f"{ORCHESTRATOR_FILE} absent",
                    "nodes": [], "edges": [], "detail": detail,
                    "generated_at": _utcnow_iso()}
        capped = min(max(limit, 1), 200)
        tasks = recent_tasks(store, limit=capped)
        nodes: list[dict] = []
        edges: list[dict] = []
        seen_ids: set = set()
        state = {"max": MAX_GRAPH_NODES, "truncated": False,
                 "max_depth": 0 if detail == "overview" else None}
        for task in tasks:
            task_id = task.get("task_id")
            if task_id is None:
                continue
            chain = build_chain(store, task_id)
            root = chain.get("root")
            if root is None:
                continue
            _flatten_tree(root, nodes, edges, None, task_id, seen_ids, state)
            if state["truncated"]:
                break
        return {"available": True, "nodes": nodes, "edges": edges,
                "task_count": len(tasks),
                "detail": detail,
                "truncated": state["truncated"],
                "node_limit": MAX_GRAPH_NODES,
                "generated_at": _utcnow_iso()}

    @router.get("/monitor")
    def monitor(limit: int = 25):
        orch_path = logs_dir / ORCHESTRATOR_FILE
        if not orch_path.exists():
            return {"available": False,
                    "reason": f"{ORCHESTRATOR_FILE} absent",
                    "active": [], "recent": [],
                    "synthetic_inference": SYNTHETIC_INFERENCE,
                    "generated_at": _utcnow_iso()}
        capped = min(max(limit, 1), 200)
        tasks = recent_tasks(store, limit=capped)
        procs = _latest_processes(telemetry_file)
        # telemetry_available is its own signal: a present-but-empty (or
        # absent) telemetry file means cpu/rss are null, not that the
        # monitor endpoint is unavailable. Surface it so the frontend can
        # say "process metrics unavailable" rather than guessing zeros.
        telemetry_available = telemetry_file.exists() and bool(procs)

        def enrich(task: dict) -> dict:
            pid = task.get("worker_pid")
            proc = procs.get(pid) if isinstance(pid, int) else None
            return {
                "task_id": task.get("task_id"),
                "task_type": task.get("task_type"),
                "status": task.get("status"),
                "worker_pid": pid,
                "timestamp": task.get("timestamp") or task.get("dispatch_ts"),
                # Pure passthrough from recent_tasks(): the per-stage label
                # ("orchestrator_dispatch" / "worker_invocation" / ...) and the
                # human-readable detail ("spawning worker process for ...").
                # The HERO active-worker view renders `detail` as "what it is
                # doing"; `stage` is the coarse phase. enrich() previously
                # dropped both — surface them.
                "stage": task.get("stage"),
                "detail": task.get("detail"),
                "cpu_pct": proc.get("cpu_pct") if proc else None,
                "rss_mb": proc.get("rss_mb") if proc else None,
            }

        enriched = [enrich(t) for t in tasks]
        active = [e for e in enriched if e["status"] in ACTIVE_STATUSES]
        # last_activity_at = the most recent timestamp across all recent tasks.
        # Drives the idle empty-state's "last activity … ago". None when no
        # task carries a timestamp. NOTE: compare as datetimes, not raw ISO
        # strings — isoformat() omits the fractional second when microseconds
        # == 0 ('…14Z') but includes it otherwise ('…14.5Z'), so a string max
        # at the same integer second mis-orders ('.' < 'Z'). Return the
        # original string of the argmax so the wire format is unchanged.
        timestamps = [e["timestamp"] for e in enriched if e["timestamp"]]
        last_activity_at = max(timestamps, key=_parse_ts) if timestamps else None
        return {"available": True,
                "telemetry_available": telemetry_available,
                "active": active,
                "recent": enriched,
                "last_activity_at": last_activity_at,
                "synthetic_inference": SYNTHETIC_INFERENCE,
                "generated_at": _utcnow_iso()}

    app.include_router(router)
    return router
