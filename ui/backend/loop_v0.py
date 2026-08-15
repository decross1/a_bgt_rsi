"""LOOP_V0 endpoints. Surfaces what Nara is doing to the dashboard.

Three endpoints post-S3 (UI simplification: the ``/processes`` rollup and the
``/active`` single-slot mirror retired with their Dashboard consumers — the
D-047 registry at ``/api/activity/active_runs`` is the live-run source), all
wired by ``register`` into the existing FastAPI app:

- ``POST /api/loop_v0/start``  — body ``{"topic": str}``; subprocess-spawns
  ``orchestrator.loop_v0_cli`` under ``env -u MOCK_LLM`` with cwd set to the
  primary worktree (not this UI worktree). Returns 202 + the spawned PID.
- ``GET  /api/loop_v0/iterations`` — reads ``memory/loop_memory.jsonl``,
  newest-first by ``ended_at``. Returns ``{"iterations": []}`` if absent.
- ``GET  /api/loop_v0/journal/{iteration_id}`` — reads the journal entry at
  ``journal/iterations/NNN.md`` matching the iteration. 404 when absent.

Reads from ``run_state/`` and ``journal/`` are read-only; the UI never
writes there. The subprocess invocation must prefix ``env -u MOCK_LLM`` —
``MOCK_LLM=1`` is set in the user's shell and silently stubs the embedder.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# The shell injects MOCK_LLM=1 by default (memory: mock-llm-track-a-env);
# real model + pipeline runs must strip it. The LOOP_V0 CLI talks to the
# real embedder and the real vLLM, so we strip here.
REAL_RUN_PREFIX = ["env", "-u", "MOCK_LLM"]
CLI_MODULE = "orchestrator.loop_v0_cli"
MAX_TOPIC_LEN = 2000

# The CLI imports `openai`, `chromadb`, etc. — none of which the system
# Python has. The project's working interpreter is `.venv-chroma`
# (memory: venv-chroma-bridges-openai). We prefer that over PATH lookup,
# and let UI_LOOP_V0_PYTHON override for tests / unusual installs.
def _resolve_python_bin(repo_root: Path) -> str:
    override = os.environ.get("UI_LOOP_V0_PYTHON")
    if override:
        return override
    venv_chroma = repo_root / ".venv-chroma" / "bin" / "python"
    if venv_chroma.exists():
        return str(venv_chroma)
    venv = repo_root / ".venv" / "bin" / "python"
    if venv.exists():
        return str(venv)
    # Last-resort fallback for tests and unusual installs.
    return shutil.which("python3") or shutil.which("python") or "python"


def _safe_iteration_id(iteration_id: str) -> str:
    """Allow only iteration-id shapes Nara emits.

    Format: ``iter-YYYY-MM-DD-NNN`` (LOOP_V0.md §iteration_record). We refuse
    any path-traversal or non-conforming id, so the journal-read endpoint
    can't be coaxed into reading outside ``journal/iterations/``.
    """
    if not iteration_id or len(iteration_id) > 64:
        raise HTTPException(status_code=400, detail="invalid iteration_id")
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")
    if any(ch not in allowed for ch in iteration_id):
        raise HTTPException(status_code=400, detail="invalid iteration_id")
    return iteration_id


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    # Producer's contract; skipping malformed rows keeps the
                    # endpoint useful while a primary-session bug is fixed.
                    continue
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"unreadable: {exc}") from exc
    return rows


def register(
    app,
    *,
    repo_root: Path,
    run_state_dir: Path,
    journal_dir: Path,
    loop_memory_path: Path | None = None,
    popen=subprocess.Popen,
) -> APIRouter:
    """Attach the LOOP_V0 router. `loop_memory_path` defaults to
    `<repo_root>/memory/loop_memory.jsonl` (the Layer-3 location per
    ARCHITECTURE.md §4.4). Tests can pin alternates. `run_state_dir` stays
    accepted (unused since the /active mirror retired in S3) so the
    create_app wiring + env overrides are unchanged."""
    if loop_memory_path is None:
        loop_memory_path = Path(repo_root) / "memory" / "loop_memory.jsonl"
    router = APIRouter(prefix="/api/loop_v0", tags=["loop_v0"])

    # In-memory tracker for subprocess we spawn via /start. Keyed by pid.
    # The Popen instance is kept so we can call .poll() — that returns
    # the exit code if the process has exited, or None if still running.
    # On backend restart this map is empty; running iterations from a
    # prior backend cannot be reaped here (their journal entries still
    # land via the producer's own writes).
    _processes: dict[int, dict] = {}

    def _reap_processes() -> None:
        """Lazy reap: every endpoint call checks if any tracked pid has
        exited and updates its status. Cheap; bounded by len(_processes)
        which is the count of iterations submitted since backend boot."""
        for pid, info in _processes.items():
            if info["status"] != "running":
                continue
            proc = info.get("proc")
            if proc is None or not hasattr(proc, "poll"):
                # Test stubs without poll() — leave as running.
                continue
            rc = proc.poll()
            if rc is None:
                continue
            info["ended_at"] = _utcnow_iso()
            info["exit_code"] = rc
            if rc == 0:
                info["status"] = "exited_clean"
            elif rc < 0:
                info["status"] = f"killed_signal_{-rc}"
            else:
                info["status"] = f"exited_error_{rc}"

    @router.post("/start", status_code=202)
    def start(payload: dict = Body(...)):
        topic = payload.get("topic") if isinstance(payload, dict) else None
        if not isinstance(topic, str) or not topic.strip():
            raise HTTPException(status_code=400, detail="topic is required")
        topic = topic.strip()
        if len(topic) > MAX_TOPIC_LEN:
            raise HTTPException(status_code=400, detail="topic too long")
        if not Path(repo_root).exists():
            raise HTTPException(
                status_code=500,
                detail=f"repo_root {repo_root!s} does not exist")
        # Use the project's .venv-chroma interpreter (which has openai,
        # chromadb, jsonschema, etc.) — NOT the system python, which lacks
        # the apparatus deps. See _resolve_python_bin above.
        python_bin = _resolve_python_bin(Path(repo_root))
        cmd = [*REAL_RUN_PREFIX, python_bin, "-m", CLI_MODULE, "--topic", topic]
        try:
            proc = popen(cmd, cwd=str(repo_root))
        except (OSError, ValueError) as exc:
            raise HTTPException(
                status_code=500, detail=f"subprocess failed: {exc}") from exc
        pid = getattr(proc, "pid", None)
        if isinstance(pid, int):
            _processes[pid] = {
                "pid": pid,
                "topic": topic,
                "started_at": _utcnow_iso(),
                "ended_at": None,
                "status": "running",
                "exit_code": None,
                "proc": proc,
            }
        return {"pid": pid, "topic": topic}

    # (GET /processes and GET /active were retired in UI simplification S3:
    # the in-flight rollup + active-iteration panel died with the Dashboard,
    # and the D-047 registry (/api/activity/active_runs) is the live-run
    # source. The `_processes` tracker itself survives — POST /start still
    # records spawns and /iterations still joins their status in.)

    @router.get("/iterations")
    def iterations():
        _reap_processes()
        rows = _read_jsonl(Path(loop_memory_path))
        rows.sort(key=lambda r: r.get("ended_at") or "", reverse=True)
        # Join in-memory process status by topic. The match is best-effort —
        # if the same topic was submitted twice since backend boot, we attach
        # the *latest* matching process. Iterations from before backend boot
        # have no process info, and the field is omitted.
        topic_to_status: dict[str, dict] = {}
        for info in _processes.values():
            t = info.get("topic")
            if not t:
                continue
            existing = topic_to_status.get(t)
            if existing is None or (info.get("started_at") or "") > (existing.get("started_at") or ""):
                topic_to_status[t] = info
        for row in rows:
            topic = (row.get("seed") or {}).get("topic")
            info = topic_to_status.get(topic)
            if info is None:
                continue
            row["process_status"] = info["status"]
            row["process_pid"] = info["pid"]
            if info.get("exit_code") is not None:
                row["process_exit_code"] = info["exit_code"]
        return {"iterations": rows}

    @router.get("/journal/{iteration_id}")
    def journal(iteration_id: str):
        iteration_id = _safe_iteration_id(iteration_id)
        # The journal entry's path is recorded in the loop_memory row. Look
        # it up there first; fall back to a glob over the journal dir if
        # loop_memory has no row yet (Part-1 hello-world race window).
        memory = _read_jsonl(Path(loop_memory_path))
        path: Path | None = None
        for row in memory:
            if row.get("iteration_id") == iteration_id and isinstance(
                row.get("journal_entry_path"), str
            ):
                candidate = Path(row["journal_entry_path"])
                if not candidate.is_absolute():
                    candidate = Path(repo_root) / candidate
                if candidate.exists() and _is_within(candidate, Path(journal_dir)):
                    path = candidate
                    break
        if path is None:
            # Fallback: scan journal_dir for a file whose body references the
            # iteration_id. Cheap because journal entries are short.
            for entry in sorted(Path(journal_dir).glob("*.md")):
                try:
                    if iteration_id in entry.read_text(encoding="utf-8"):
                        path = entry
                        break
                except OSError:
                    continue
        if path is None or not path.exists():
            raise HTTPException(
                status_code=404, detail=f"no journal entry for {iteration_id}")
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise HTTPException(
                status_code=500, detail=f"journal unreadable: {exc}") from exc
        return {
            "iteration_id": iteration_id,
            "path": str(path.relative_to(repo_root))
            if _is_within(path, Path(repo_root))
            else str(path),
            "content": content,
        }

    app.include_router(router)
    return router


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False
