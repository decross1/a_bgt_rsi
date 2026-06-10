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
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response

from .chain import LogStore, build_chain, recent_tasks

# _REPO == the ui-session worktree root (this file is ui/backend/activity.py).
_REPO = Path(__file__).resolve().parents[2]
DEFAULT_LOGS_DIR = _REPO / "logs"
DEFAULT_TELEMETRY = _REPO / "ui" / "logs" / "telemetry.jsonl"

# The primary checkout (mirror of app.py's _PRIMARY_REPO / loop_v0's run_state
# dir). active_run.json and worker_activity.jsonl are written by the primary
# session's run drivers there, NOT in this UI worktree. Baked as the default so
# app.py's register_activity(app, logs_dir=..., telemetry_file=...) call keeps
# working with no signature change; tests pin a tmp path.
_PRIMARY = Path("/home/decross1/projects/a_bgt_rsi")
DEFAULT_ACTIVE_RUN = _PRIMARY / "run_state" / "active_run.json"
# D-047 multi-run registry: one JSON file per LIVE run under
# run_state/active_runs/ in the PRIMARY checkout (deleted on completion;
# absent dir == no live runs). Like DEFAULT_ACTIVE_RUN this must point at
# the primary checkout, not the UI worktree. Env-overridable below
# (UI_ACTIVE_RUNS_DIR) because app.py's register_activity(...) call passes
# only logs_dir/telemetry_file — the DEFAULT_COORDINATOR_RUN_STATE idiom
# from app.py, replicated locally so app.py needs no edit.
DEFAULT_ACTIVE_RUNS_DIR = _PRIMARY / "run_state" / "active_runs"


def _env_path(var: str, default: Path) -> Path:
    """app.py's env-override idiom (UI_* var wins, else the baked default)."""
    value = os.environ.get(var)
    return Path(value) if value else default
# worker_activity.jsonl is written by the primary session's run drivers into
# the PRIMARY checkout's logs dir, NOT this UI worktree's logs dir. Source it
# from the primary checkout (mirroring DEFAULT_ACTIVE_RUN) so the live-inference
# marker actually drops in deployment; tests pin a tmp path distinct from
# logs_dir.
DEFAULT_WORKER_ACTIVITY = _PRIMARY / "logs" / "worker_activity.jsonl"

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

# "Live calls": EVERY run mode (orchestrator dispatch, the LOOP_V0 loop, the
# autoresearch driver, a raw experiment runner like exp005/run.py) funnels its
# LLM calls through the wrapper into the call log. A call within this many
# seconds of now means the apparatus is actively working RIGHT NOW even when no
# orchestrator task and no loop iteration is registered — which is exactly the
# blind spot that left /activity empty during a live exp run. We read the tail
# of the call log(s) and surface the recent-call rate + caller_tag + model.
LIVE_CALLS_WINDOW_S = 15
_CALL_LOG_PATTERNS = ("calls.jsonl", "day*.jsonl", "exp*.jsonl")
# live_calls.groups[] is capped so a pathological window (many distinct
# caller_tag/model/backend/run_id combinations) cannot balloon the monitor
# payload; the tail is summarized as other_count + groups_truncated.
LIVE_CALLS_GROUPS_CAP = 12

# Real per-call inference internals (tokens generated / tok_per_s / ETA) land
# in logs/worker_activity.jsonl, one row per wrapper call. When a row falls
# within this window the data is genuinely live and REPLACES the synthetic
# fixture; older rows are stale and we fall back to the labelled fixture so the
# `synthetic` flag is never false over data that isn't being measured right now.
WORKER_ACTIVITY_FILE = "worker_activity.jsonl"
WORKER_ACTIVITY_WINDOW_S = 30

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


def _tail_records(path: Path, window_bytes: int = 256 * 1024) -> list[dict]:
    """Parse JSON objects from the last `window_bytes` of a JSONL file.

    A bounded tail read so it stays cheap as calls.jsonl grows to many MB.
    Drops the (likely partial) first line of a windowed read and skips
    malformed lines.
    """
    if not path.exists():
        return []
    try:
        size = path.stat().st_size
        window = min(size, window_bytes)
        with open(path, "rb") as fh:
            fh.seek(size - window)
            data = fh.read()
    except OSError:
        return []
    lines = data.decode("utf-8", errors="replace").splitlines()
    if window < size and lines:
        lines = lines[1:]
    out: list[dict] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def _passthrough_str(value) -> str | None:
    """A group-key field is the record's own value or None — NEVER derived.

    Non-string / empty values normalize to None ("absent"). In particular a
    missing `backend` (every pre-2026-06-10 calls.jsonl row) stays None; it
    is never guessed from the model name (CLAUDE.md rule 4 — render absent,
    don't fabricate)."""
    return value if isinstance(value, str) and value else None


def _live_calls(logs_dir: Path, window_s: int, now: datetime) -> dict:
    """Recent wrapper-call activity across the call log(s).

    Reads the tail of calls.jsonl + day*/exp* and keeps records whose
    `timestamp` falls within the last `window_s` seconds of `now`. Returns
    `{active, count, window_s, calls_per_s, last_call_at, caller_tags, model,
    groups, groups_truncated, other_count}`.
    `active` is True iff at least one call landed inside the window — the
    run-mode-agnostic "something is happening now" signal. Old logs (May
    timestamps) fall outside the window and contribute nothing.

    `groups[]` (ADDITIVE — the pre-existing keys above are untouched, so
    older renders/tests stay valid) aggregates the same windowed records per
    (caller_tag, model, backend, run_id) into
    `{tag, model, backend, run_id, count, last_call_at}`, sorted count-desc
    (ties: most recent first, then tag), capped at LIVE_CALLS_GROUPS_CAP.
    `groups_truncated` flags a hit cap; `other_count` is the number of CALLS
    in the groups beyond the cap, so
    sum(g.count) + other_count == count always holds. `backend` and `run_id`
    are pure passthrough from the record (see _passthrough_str): `backend` is
    stamped by the 2026-06-10 EMIT and is null on older rows; `run_id` is
    optional — neither is ever fabricated.
    """
    cutoff = now.timestamp() - window_s
    files: list[Path] = []
    for pattern in _CALL_LOG_PATTERNS:
        files.extend(sorted(logs_dir.glob(pattern)))
    count = 0
    last_call_at: str | None = None
    last_instant: datetime | None = None
    tags: dict[str, int] = {}
    models: dict[str, int] = {}
    # (tag, model, backend, run_id) -> {count, last_instant, last_call_at}
    groups: dict[tuple, dict] = {}
    for path in files:
        for rec in _tail_records(path):
            ts = rec.get("timestamp")
            if not isinstance(ts, str):
                continue
            dt = _parse_ts(ts)
            if dt.timestamp() < cutoff:
                continue
            count += 1
            if last_instant is None or dt > last_instant:
                last_instant, last_call_at = dt, ts
            tag = rec.get("caller_tag")
            if isinstance(tag, str) and tag:
                tags[tag] = tags.get(tag, 0) + 1
            model = rec.get("model")
            if isinstance(model, str) and model:
                models[model] = models.get(model, 0) + 1
            key = (
                _passthrough_str(tag),
                _passthrough_str(model),
                _passthrough_str(rec.get("backend")),
                _passthrough_str(rec.get("run_id")),
            )
            grp = groups.get(key)
            if grp is None:
                groups[key] = {"count": 1, "last_instant": dt,
                               "last_call_at": ts}
            else:
                grp["count"] += 1
                if dt > grp["last_instant"]:
                    grp["last_instant"], grp["last_call_at"] = dt, ts
    top_tags = sorted(tags.items(), key=lambda kv: kv[1], reverse=True)[:3]
    top_model = max(models.items(), key=lambda kv: kv[1])[0] if models else None
    # count-desc; ties most-recent-first then tag, so the cap is deterministic.
    ordered = sorted(
        groups.items(),
        key=lambda kv: (-kv[1]["count"],
                        -kv[1]["last_instant"].timestamp(),
                        kv[0][0] or ""),
    )
    kept, overflow = (ordered[:LIVE_CALLS_GROUPS_CAP],
                      ordered[LIVE_CALLS_GROUPS_CAP:])
    group_rows = [
        {"tag": k[0], "model": k[1], "backend": k[2], "run_id": k[3],
         "count": g["count"], "last_call_at": g["last_call_at"]}
        for k, g in kept
    ]
    return {
        "active": count > 0,
        "count": count,
        "window_s": window_s,
        "calls_per_s": round(count / window_s, 2) if window_s > 0 else None,
        "last_call_at": last_call_at,
        "caller_tags": [{"tag": t, "count": c} for t, c in top_tags],
        "model": top_model,
        "groups": group_rows,
        "groups_truncated": bool(overflow),
        "other_count": sum(g["count"] for _, g in overflow),
    }


def _real_inference(path: Path, window_s: int, now: datetime) -> dict | None:
    """REAL per-worker inference internals from worker_activity.jsonl.

    Reads the tail of the file (same bounded-tail discipline as _live_calls /
    _tail_records), keeps rows whose `timestamp` is within the last `window_s`
    seconds, and collapses to the LATEST row per task_id. Returns the
    synthetic_inference-shaped block with `synthetic: False` when at least one
    recent row exists, else None (the caller falls back to the labelled
    SYNTHETIC_INFERENCE fixture). Returning None — not a synthetic:False block —
    on a stale/absent file is what keeps the load-bearing flag honest.

    `path` is the worker_activity.jsonl path (the PRIMARY checkout's logs dir in
    production — decoupled from this router's logs_dir, which points at the UI
    worktree). A row that flags ITSELF `synthetic: True` is a producer-written
    placeholder and is dropped here, so a per-row synthetic flag can never be
    surfaced as measured under the load-bearing `synthetic: False`.
    """
    cutoff = now.timestamp() - window_s
    latest: dict[str, dict] = {}
    latest_instant: dict[str, datetime] = {}
    for rec in _tail_records(path):
        if rec.get("synthetic") is True:
            continue
        ts = rec.get("timestamp")
        if not isinstance(ts, str):
            continue
        dt = _parse_ts(ts)
        if dt.timestamp() < cutoff:
            continue
        task_id = rec.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            continue
        prev = latest_instant.get(task_id)
        if prev is None or dt > prev:
            latest_instant[task_id] = dt
            latest[task_id] = rec
    if not latest:
        return None
    workers = [
        {
            "task_id": rec.get("task_id"),
            "run_id": rec.get("run_id"),
            "tokens_generated": rec.get("tokens_generated"),
            "tokens_target": rec.get("tokens_target"),
            "tok_per_s": rec.get("tok_per_s"),
            "eta_s": rec.get("eta_s"),
        }
        for rec in latest.values()
    ]
    return {
        "synthetic": False,
        "source": "worker_activity.jsonl",
        "workers": workers,
    }


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
             telemetry_file: Path = DEFAULT_TELEMETRY,
             active_run_path: Path = DEFAULT_ACTIVE_RUN,
             worker_activity_path: Path = DEFAULT_WORKER_ACTIVITY,
             active_runs_dir: Path | None = None) -> APIRouter:
    """Attach the PAGE A router. Defaults are baked in so the integrator
    adds exactly one ``register(app)`` call; tests pin tmp paths.

    ``active_run_path`` and ``worker_activity_path`` BOTH default to the PRIMARY
    checkout (not this UI worktree) — the run drivers write
    ``run_state/active_run.json`` and ``logs/worker_activity.jsonl`` there, while
    this router's ``logs_dir`` points at the UI worktree. Keying
    worker_activity off logs_dir would mean the live-inference marker never drops
    in production. app.py's existing ``register_activity(app, logs_dir=...,
    telemetry_file=...)`` call works unchanged because these are keywords with
    baked defaults.

    ``active_runs_dir`` (the D-047 multi-run registry) resolves None →
    ``UI_ACTIVE_RUNS_DIR`` env override → the primary checkout's
    ``run_state/active_runs`` — the app.py env-path idiom replicated here
    because app.py's register call passes no path for it; tests pin a tmp
    path via the kwarg."""
    logs_dir = Path(logs_dir)
    telemetry_file = Path(telemetry_file)
    active_run_path = Path(active_run_path)
    worker_activity_path = Path(worker_activity_path)
    if active_runs_dir is None:
        active_runs_dir = _env_path("UI_ACTIVE_RUNS_DIR", DEFAULT_ACTIVE_RUNS_DIR)
    active_runs_dir = Path(active_runs_dir)
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
        now = datetime.now(timezone.utc)
        # Run-mode-agnostic live signal — computed first so it surfaces even
        # when the orchestrator log is absent/stale (the exp-run blind spot).
        live_calls = _live_calls(logs_dir, LIVE_CALLS_WINDOW_S, now)
        # REAL inference internals when worker_activity.jsonl has recent rows;
        # else the labelled fixture. synthetic:False ONLY over genuinely-live
        # measured data (CLAUDE.md rule 4 — never present the fixture as
        # measured).
        inference = (_real_inference(worker_activity_path,
                                     WORKER_ACTIVITY_WINDOW_S, now)
                     or SYNTHETIC_INFERENCE)
        orch_path = logs_dir / ORCHESTRATOR_FILE
        if not orch_path.exists():
            return {"available": False,
                    "reason": f"{ORCHESTRATOR_FILE} absent",
                    "active": [], "recent": [],
                    "live_calls": live_calls,
                    "synthetic_inference": inference,
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
                "live_calls": live_calls,
                "synthetic_inference": inference,
                "generated_at": _utcnow_iso()}

    @router.get("/active_run")
    def active_run():
        """The single 'what is running now' state, regardless of run kind.

        Mirrors loop_v0's /active: 204 when the file is absent (no run in
        flight, the driver deletes it on completion), the parsed JSON when
        present (ALL keys passed through, including unknown ones a later
        nemoclaw revision may add — additionalProperties true in the schema),
        500 only on a genuinely unreadable/corrupt file. The delete-race
        between exists() and read is treated as 204, not 500."""
        if not active_run_path.exists():
            return Response(status_code=204)
        try:
            text = active_run_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return Response(status_code=204)
        # A zero-length (or whitespace-only) read is the mid-write window of a
        # non-atomic producer, not a corrupt file — treat it as "no run" (204)
        # rather than a 500 page-error banner.
        if not text.strip():
            return Response(status_code=204)
        try:
            return json.loads(text)
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(
                status_code=500, detail=f"active_run unreadable: {exc}"
            ) from exc

    @router.get("/active_runs")
    def active_runs():
        """ALL live runs — the D-047 multi-run registry (NowBoard source).

        Reads ``run_state/active_runs/*.json`` — one file per live run,
        written/heartbeated by orchestrator/active_run.py and deleted on
        completion. Every doc passes through RAW (all keys, incl.
        ``heartbeat_at`` and kinds newer than this build — the active_run
        kind set is {experiment, autoresearch, loop_v0, ad_hoc, coordinator}
        today and may grow; unknown kinds are NOT filtered or normalized).

        Never 500s on data states: an absent registry dir == ``{runs: []}``;
        a malformed/unparseable/non-object file is SKIPPED and counted in
        ``skipped``; a file deleted between listing and read is a completed
        run, dropped silently. FALLBACK: when the dir is absent or has no
        .json files (pre-D-047 apparatus) but the legacy single-slot
        ``active_run.json`` mirror exists, its doc is wrapped as
        ``{runs: [{...legacy fields, legacy_mirror: true}]}`` (an
        empty/whitespace mirror is the mid-write window == no run; a corrupt
        mirror counts as skipped). A registry dir WITH .json files wins over
        the mirror even if every file was skipped — the mirror is the most
        recent writer, not the union, so falling back there could resurrect
        a stale run.
        """
        runs: list[dict] = []
        skipped = 0
        files = (sorted(active_runs_dir.glob("*.json"))
                 if active_runs_dir.is_dir() else [])
        for path in files:
            try:
                text = path.read_text(encoding="utf-8")
            except FileNotFoundError:
                continue  # delete race: the run completed mid-listing
            except OSError:
                skipped += 1
                continue
            try:
                doc = json.loads(text)
            except json.JSONDecodeError:
                skipped += 1
                continue
            if not isinstance(doc, dict):
                skipped += 1
                continue
            runs.append(doc)
        if not files:
            # Legacy fallback (pre-D-047 apparatus): wrap the single-slot
            # mirror so the board still renders one honest card.
            try:
                text = active_run_path.read_text(encoding="utf-8")
            except OSError:
                text = ""
            if text.strip():
                try:
                    legacy = json.loads(text)
                except json.JSONDecodeError:
                    legacy = None
                if isinstance(legacy, dict):
                    runs = [{**legacy, "legacy_mirror": True}]
                else:
                    skipped += 1
        return {"runs": runs, "skipped": skipped,
                "generated_at": _utcnow_iso()}

    app.include_router(router)
    return router
