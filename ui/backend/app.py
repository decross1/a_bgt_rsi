"""FastAPI app for the dashboard + chain inspector. See ui_plan.md section 5.2.

Read-only over the apparatus: it reads the JSONL logs and run_state, and
never writes anything. The WebSocket /api/live endpoint is build step 6.4
and is not implemented here.

Run:  cd ui && ui/backend/run.sh        (serves on :8700)
Point at fixture logs:  UI_LOGS_DIR=/tmp/fixture_logs ui/backend/run.sh
"""
import asyncio
import json
import os
import socket
import subprocess
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .baseline import compute_baseline
from .chain import LogStore, build_chain, build_chain_by_request_id, recent_tasks
from .day4 import read_events, read_robustness
from .loop_v0 import register as register_loop_v0
from .tailer import JsonlTailer
from .unlock import compute_unlock_status
from .workload import compute_workload_hint

_REPO = Path(__file__).resolve().parents[2]
# When the UI runs from the worktree at .claude/worktrees/ui-session, paths
# like run_state/ and journal/ live in the primary worktree, not this one.
# The default repo root is the real primary checkout; override via env vars
# in tests (UI_REPO_ROOT / UI_RUN_STATE_DIR / UI_JOURNAL_DIR).
_PRIMARY_REPO = Path("/home/decross1/projects/a_bgt_rsi")
DEFAULT_LOGS_DIR = _REPO / "logs"                       # apparatus call/orchestrator logs
DEFAULT_TELEMETRY = _REPO / "ui" / "logs" / "telemetry.jsonl"
DEFAULT_STATE = _REPO / "run_state" / "week1.state.json"
DEFAULT_BENCH_CSV = _REPO / "bench" / "day1.csv"        # day-1 throughput sweep (pre-MTP)
DEFAULT_MTP_CSV = _REPO / "bench" / "mtp.csv"           # MTP-enabled sweep (D-022)
DEFAULT_RUN_LOG = _REPO / "run_state" / "week1.run.jsonl"
DEFAULT_ATTESTATIONS = _REPO / "run_state" / "attestations.jsonl"
DEFAULT_LOOP_V0_REPO = _PRIMARY_REPO
DEFAULT_LOOP_V0_RUN_STATE = _PRIMARY_REPO / "run_state"
DEFAULT_LOOP_V0_JOURNAL = _PRIMARY_REPO / "journal" / "iterations"


def _git_sha():
    try:
        proc = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              cwd=_REPO, capture_output=True, text=True, timeout=5)
    except (subprocess.SubprocessError, OSError):
        return "unknown"
    return proc.stdout.strip() or "unknown" if proc.returncode == 0 else "unknown"


def _tail_lines(path, limit):
    """Return up to `limit` parsed JSON objects from the end of a JSONL file.

    Reads a bounded window from the end rather than the whole file, so it
    stays cheap as telemetry.jsonl grows.
    """
    path = Path(path)
    if not path.exists():
        return []
    try:
        size = path.stat().st_size
        window = min(size, limit * 1024)          # ~1 KB/line is generous
        with open(path, "rb") as fh:
            fh.seek(size - window)
            data = fh.read()
    except OSError:
        return []
    lines = data.decode("utf-8", errors="replace").splitlines()
    if window < size and lines:
        lines = lines[1:]                          # drop the partial first line
    out = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def create_app(logs_dir=DEFAULT_LOGS_DIR, telemetry_file=DEFAULT_TELEMETRY,
               state_file=DEFAULT_STATE, bench_csv=DEFAULT_BENCH_CSV,
               mtp_csv=DEFAULT_MTP_CSV, run_log_file=DEFAULT_RUN_LOG,
               attestations_file=DEFAULT_ATTESTATIONS,
               loop_v0_repo=DEFAULT_LOOP_V0_REPO,
               loop_v0_run_state=DEFAULT_LOOP_V0_RUN_STATE,
               loop_v0_journal=DEFAULT_LOOP_V0_JOURNAL,
               loop_v0_popen=subprocess.Popen):
    app = FastAPI(title="UI backend — orchestrator dashboard", version=_git_sha())
    # Permissive CORS for local dev (Vite serves the SPA on another port).
    app.add_middleware(CORSMiddleware, allow_origins=["*"],
                       allow_methods=["*"], allow_headers=["*"])

    store = LogStore(logs_dir)
    telemetry = JsonlTailer(telemetry_file)
    seen = {"telemetry_ts": None}

    @app.get("/api/health")
    def health():
        for record in telemetry.read_new():
            ts = record.get("timestamp")
            if ts:
                seen["telemetry_ts"] = ts
        return {"ok": True,
                "hostname": socket.gethostname(),
                "telemetry_last_seen": seen["telemetry_ts"],
                "version": _git_sha()}

    @app.get("/api/chain/{task_id}")
    def chain(task_id: str):
        result = build_chain(store, task_id)
        if not result["found"]:
            raise HTTPException(
                status_code=404,
                detail=f"no orchestrator dispatch for task_id {task_id!r}")
        return result

    @app.get("/api/chain_by_request/{request_id}")
    def chain_by_request(request_id: str):
        """Walk a tool-call chain rooted at a wrapper request_id (day-4)."""
        result = build_chain_by_request_id(store, request_id)
        if not result["found"]:
            raise HTTPException(
                status_code=404,
                detail=f"no call record for request_id {request_id!r}")
        return result

    @app.get("/api/recent_tasks")
    def recent(limit: int = 50):
        return {"tasks": recent_tasks(store, limit)}

    @app.get("/api/day4/chains")
    def day4_chains():
        """Root wrapper request_ids from day4_e2e.jsonl, newest last.

        Scoped to day4_e2e.jsonl specifically rather than the cross-file
        LogStore index: day-2 records all carry parent_request_id=null
        (chains start day 4 per the schema), so a cross-file enumeration
        would surface ~50 day-2 standalone calls as "day-4 chains".
        """
        store.refresh()
        path = Path(logs_dir) / "day4_e2e.jsonl"
        if not path.exists():
            return {"available": False, "chains": []}
        chains = []
        try:
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if (record.get("parent_request_id") is None
                            and isinstance(record.get("request_id"), str)):
                        rid = record["request_id"]
                        walk = build_chain_by_request_id(store, rid)
                        chains.append({
                            "request_id": rid,
                            "caller_tag": record.get("caller_tag"),
                            "timestamp": record.get("timestamp"),
                            "node_count": walk["node_count"],
                            "total_latency_ms": walk["total_latency_ms"],
                            "malformed_tool_calls": walk["malformed_tool_calls"],
                        })
        except OSError:
            return {"available": False, "chains": []}
        chains.sort(key=lambda c: c.get("timestamp") or "", reverse=True)
        return {"available": True, "chains": chains}

    @app.get("/api/events")
    def events(limit: int = 200):
        """events.jsonl passthrough (day-3.5 surface). Available=False if absent."""
        return read_events(Path(logs_dir) / "events.jsonl", limit=max(1, limit))

    @app.get("/api/robustness")
    def robustness():
        """day4_robust.jsonl summary: invocation rate + median latency."""
        return read_robustness(Path(logs_dir) / "day4_robust.jsonl")

    @app.get("/api/telemetry/recent")
    def telemetry_recent(limit: int = 300):
        """Last N telemetry samples, so the dashboard can seed its sparklines."""
        capped = min(max(limit, 1), 2000)
        return {"samples": _tail_lines(telemetry_file, capped)}

    @app.get("/api/baseline")
    def baseline():
        """Healthy-baseline card rows, each annotated measured vs documented.

        Data-driven from bench/mtp.csv (MTP-enabled), bench/day1.csv and
        run_state metric_log when those exist; documented constants
        otherwise (ui_plan.md sections 5.3, 9).
        """
        return compute_baseline(bench_csv, state_file, mtp_csv)

    @app.get("/api/workload_hint")
    def workload_hint(sample_size: int = 200, window_s: int = 120):
        """Workload-shape hint so the decode-tok/s tile is contextualized.

        Day-7 UX audit (ui_plan.md r10): the day-1 decode band [80,130]
        was measured with 256-tok completions. PD experiment runs with
        ~2-tok completions decode-rate ~11 by construction — not a
        regression but the UI made it look like one. This endpoint
        returns the *current workload shape* so the frontend can label
        the tile accordingly.
        """
        capped = min(max(sample_size, 10), 2000)
        return compute_workload_hint(logs_dir, sample_size=capped,
                                     window_s=max(10, window_s))

    @app.get("/api/unlock_status")
    def unlock_status():
        """§11.3 Week-2 unlock prerequisites, consolidated.

        Five sections (run-log integrity, soft-gate queue, hard-gate
        pending, metric_log, fallbacks_taken) — each independently
        available, so the dashboard can render partial state. Read-only:
        attest/rollback affordances surface the CLI command, not actions.
        """
        from datetime import datetime, timezone
        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        return compute_unlock_status(state_file, run_log_file,
                                     attestations_file, now_iso=now_iso)

    @app.get("/api/state")
    def state():
        path = Path(state_file)
        if not path.exists():
            raise HTTPException(status_code=404, detail="state file not found")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=500, detail=f"state unreadable: {exc}")

    @app.websocket("/api/live")
    async def live(websocket: WebSocket):
        """Stream new telemetry / orchestrator lines as they are appended.

        Forward-only: lines present before the client connects are not
        replayed. One message per new line: {source, line}. Tail-based
        (mtime + byte offset), polled at 0.5 s -- no inotify dependency.
        """
        await websocket.accept()
        telemetry = JsonlTailer(telemetry_file)
        orchestrator = JsonlTailer(Path(logs_dir) / "orchestrator.jsonl")
        telemetry.seek_to_end()
        orchestrator.seek_to_end()

        async def pump():
            while True:
                for record in telemetry.read_new():
                    await websocket.send_json({"source": "telemetry", "line": record})
                for record in orchestrator.read_new():
                    await websocket.send_json({"source": "orchestrator", "line": record})
                await asyncio.sleep(0.5)

        async def drain():
            # The client never sends; receive() returns only on disconnect.
            while True:
                await websocket.receive_text()

        pump_task = asyncio.create_task(pump())
        drain_task = asyncio.create_task(drain())
        try:
            await asyncio.wait({pump_task, drain_task},
                               return_when=asyncio.FIRST_COMPLETED)
        except WebSocketDisconnect:
            pass
        finally:
            pump_task.cancel()
            drain_task.cancel()

    register_loop_v0(
        app,
        repo_root=Path(loop_v0_repo),
        run_state_dir=Path(loop_v0_run_state),
        journal_dir=Path(loop_v0_journal),
        popen=loop_v0_popen,
    )

    return app


def _env_path(var, default):
    value = os.environ.get(var)
    return Path(value) if value else default


# Module-level app for uvicorn. Paths overridable via env vars so the
# backend can be pointed at fixture logs without code changes.
app = create_app(
    logs_dir=_env_path("UI_LOGS_DIR", DEFAULT_LOGS_DIR),
    telemetry_file=_env_path("UI_TELEMETRY_FILE", DEFAULT_TELEMETRY),
    state_file=_env_path("UI_STATE_FILE", DEFAULT_STATE),
    bench_csv=_env_path("UI_BENCH_CSV", DEFAULT_BENCH_CSV),
    mtp_csv=_env_path("UI_MTP_CSV", DEFAULT_MTP_CSV),
    run_log_file=_env_path("UI_RUN_LOG_FILE", DEFAULT_RUN_LOG),
    attestations_file=_env_path("UI_ATTESTATIONS_FILE", DEFAULT_ATTESTATIONS),
    loop_v0_repo=_env_path("UI_LOOP_V0_REPO", DEFAULT_LOOP_V0_REPO),
    loop_v0_run_state=_env_path("UI_LOOP_V0_RUN_STATE", DEFAULT_LOOP_V0_RUN_STATE),
    loop_v0_journal=_env_path("UI_LOOP_V0_JOURNAL", DEFAULT_LOOP_V0_JOURNAL),
)
