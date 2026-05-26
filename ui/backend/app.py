"""FastAPI app for the dashboard + chain inspector.

Read-only over the apparatus: it reads the JSONL logs and run_state, and
never writes anything. LOOP_V0 endpoints live in `loop_v0.py`.
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
from .chain import LogStore, build_chain_by_request_id
from .loop_v0 import register as register_loop_v0
from .tailer import JsonlTailer
from .workload import compute_workload_hint

_REPO = Path(__file__).resolve().parents[2]
# When the UI runs from a worktree, run_state/ and journal/ live in the
# primary checkout, not the worktree. Env vars below override per-test.
_PRIMARY_REPO = Path("/home/decross1/projects/a_bgt_rsi")
DEFAULT_LOGS_DIR = _REPO / "logs"                       # apparatus call log (logs/calls.jsonl)
DEFAULT_TELEMETRY = _REPO / "ui" / "logs" / "telemetry.jsonl"
DEFAULT_STATE = _REPO / "run_state" / "week1.state.json"
DEFAULT_BENCH_CSV = _REPO / "bench" / "day1.csv"        # day-1 throughput sweep (pre-MTP)
DEFAULT_MTP_CSV = _REPO / "bench" / "mtp.csv"           # MTP-enabled sweep (D-022)
# LOOP_V0: primary worktree paths; env overrides let tests pin alternates.
# `loop_memory.jsonl` is Layer-3 of the knowledge base per
# ARCHITECTURE.md §4.4 — sibling to chroma_db/ (Layers 1+2), not run_state/.
DEFAULT_LOOP_V0_REPO = _PRIMARY_REPO
DEFAULT_LOOP_V0_RUN_STATE = _PRIMARY_REPO / "run_state"
DEFAULT_LOOP_V0_JOURNAL = _PRIMARY_REPO / "journal" / "iterations"
DEFAULT_LOOP_V0_MEMORY = _PRIMARY_REPO / "memory" / "loop_memory.jsonl"


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
               mtp_csv=DEFAULT_MTP_CSV,
               loop_v0_repo=DEFAULT_LOOP_V0_REPO,
               loop_v0_run_state=DEFAULT_LOOP_V0_RUN_STATE,
               loop_v0_journal=DEFAULT_LOOP_V0_JOURNAL,
               loop_v0_memory=DEFAULT_LOOP_V0_MEMORY,
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

    @app.get("/api/chain_by_request/{request_id}")
    def chain_by_request(request_id: str):
        """Walk a wrapper-rooted tool-call chain by request_id."""
        result = build_chain_by_request_id(store, request_id)
        if not result["found"]:
            raise HTTPException(
                status_code=404,
                detail=f"no call record for request_id {request_id!r}")
        return result

    @app.get("/api/telemetry/recent")
    def telemetry_recent(limit: int = 300):
        """Last N telemetry samples, so the dashboard can seed its sparklines."""
        capped = min(max(limit, 1), 2000)
        return {"samples": _tail_lines(telemetry_file, capped)}

    @app.get("/api/baseline")
    def baseline():
        """Healthy-baseline card rows, each annotated measured vs documented.

        Data-driven from bench/mtp.csv (MTP-enabled), bench/day1.csv and
        run_state metric_log when those exist; documented constants otherwise.
        """
        return compute_baseline(bench_csv, state_file, mtp_csv)

    @app.get("/api/workload_hint")
    def workload_hint(sample_size: int = 200, window_s: int = 120):
        """Workload-shape hint so the decode-tok/s tile is contextualized.

        The day-1 decode band [80,130] was measured with 256-tok completions;
        prefill-bound workloads (~2-tok completions) decode at ~11 tok/s by
        construction. This endpoint returns the *current workload shape* so
        the frontend can label the tile accordingly.
        """
        capped = min(max(sample_size, 10), 2000)
        return compute_workload_hint(logs_dir, sample_size=capped,
                                     window_s=max(10, window_s))

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
        """Stream new telemetry / call-log lines as they are appended.

        Forward-only: lines present before the client connects are not
        replayed. One message per new line: {source, line}. Tail-based
        (mtime + byte offset), polled at 0.5 s — no inotify dependency.
        """
        await websocket.accept()
        telemetry = JsonlTailer(telemetry_file)
        calls = JsonlTailer(Path(logs_dir) / "calls.jsonl")
        telemetry.seek_to_end()
        calls.seek_to_end()

        async def pump():
            while True:
                for record in telemetry.read_new():
                    await websocket.send_json({"source": "telemetry", "line": record})
                for record in calls.read_new():
                    await websocket.send_json({"source": "calls", "line": record})
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
        loop_memory_path=Path(loop_v0_memory),
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
    loop_v0_repo=_env_path("UI_LOOP_V0_REPO", DEFAULT_LOOP_V0_REPO),
    loop_v0_run_state=_env_path("UI_LOOP_V0_RUN_STATE", DEFAULT_LOOP_V0_RUN_STATE),
    loop_v0_journal=_env_path("UI_LOOP_V0_JOURNAL", DEFAULT_LOOP_V0_JOURNAL),
    loop_v0_memory=_env_path("UI_LOOP_V0_MEMORY", DEFAULT_LOOP_V0_MEMORY),
)
