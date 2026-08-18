"""The lab's queue read seam (GET /api/lab_todo).

One read-only GET, wired by ``register`` into the existing FastAPI app (the
``ladder.py`` / ``loop_alert.py`` register-fn idiom). It answers ONE question
the apparatus could previously only answer by reading three places (/ladder,
memory/ideas.md, and the channel transcript): **what do Nara and the PI have on
their own to-do list?**

    {agent_gaps: [str],        # gaps the AGENT can advance
     human_gaps: [str],        # gaps that wait on the HUMAN
     gaps_source: "assess_state" | "last_cycle" | "unavailable",
     gaps_as_of: iso | null,   # null = live; set = the cycle the gaps are from
     owed: [{test, rung, clusters: [{cluster_id, stem, last_event_ts}]}],
     agenda: [{topic, source, cluster_id}],
     refine_candidates: [{cluster_id, stem, kill_code}],
     generated_at: iso}

Everything here is REUSED, never reimplemented: the gap SENTENCES are
``orchestrator.coordinator.assess_state``'s own ``gaps`` strings, the cluster
stems and next-owed test text are ``workers.idea_projection._stem`` / ``._owed``
(the same strings ``memory/ideas.md`` renders), and the ledger reduction is
``workers.idea_ledger.load_state``.

GAPS COME FROM ONE OF TWO PLACES, AND THE PAYLOAD ALWAYS SAYS WHICH
(rule 7 — a fallback is explicit and named, never a silent degraded path):

- ``assess_state`` — LIVE, preferred, used whenever ``orchestrator.coordinator``
  is importable in the serving process.
- ``last_cycle`` — the ``planner_state.gaps`` the coordinator PERSISTED on its
  most recent cycle (``run_state/coordinator_cycles.jsonl``), with that cycle's
  timestamp in ``gaps_as_of`` so the UI can label the age. Still the
  coordinator's own text; nothing is re-derived here.

  This path is not hypothetical: the production backend runs from ``ui/.venv``,
  a deliberately thin read-only venv (fastapi/jsonschema/psutil — no ``openai``,
  no ``chromadb``). ``orchestrator.coordinator`` imports ``agent_wrapper.wrapper``
  at module scope, so on the live :8700 process the import raises
  ModuleNotFoundError and the persisted gaps are the only honest source. The
  ledger sections below are unaffected — ``workers.idea_ledger`` imports fine
  there.

  It is also the CHEAP path, which matters: ``assess_state`` ends with
  ``_topic_suggestions`` → ``pick_morning_topic`` → ``chroma_query``, which
  loads the BGE-M3 embedder (~3-5 s, then resident) and queries Chroma. A
  backend served from ``.venv-chroma`` WITHOUT ``MOCK_LLM`` therefore pays that
  cost inside this poll. That is assess_state's own shape and cannot be fixed
  from ``ui/`` — flagged to the primary session rather than worked around.

The agent/human SPLIT mirrors ``orchestrator.nara_daemon.HUMAN_GAP_MARKERS``
verbatim (the daemon's ``work_exists`` predicate), so this surface can never
disagree with what the daemon will act on. The constant is mirrored rather than
imported because the daemon is unimportable on the production venv for the same
reason the coordinator is; ``ui/backend/tests/test_lab_todo.py`` pins the mirror
against the daemon's own tuple, so drift fails loudly in CI.

uvicorn's cwd is ``ui/``, so the primary repo root (threaded in like the other
registrations get memory_dir) is put on sys.path first for the lazy imports. An
ABSENT ledger is not an error — a cold checkout still gets its gaps, with the
ledger-derived lists empty. An unreadable/invalid ledger is an honest 500 with
the error in ``detail``: idea_ledger's loud-failure ValueErrors are never
coerced into a thinner state (rule 4). The UI never writes ``memory/``.
"""
from __future__ import annotations

import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from .coordinator import _read_jsonl

# PERF (2026-08-18): on a backend served from .venv-chroma the live
# assess_state path holds for a LONG time (BGE-M3 embedder + Chroma query
# inside the request — measured >120 s under load), and the UI's old bare
# 30 s poll kept stacking concurrent builds until the whole threadpool was
# starved. The endpoint now serves STALE-WHILE-REVALIDATE: a cached payload
# is returned instantly; when it is older than CACHE_FRESH_S ONE background
# thread rebuilds it (single-flight — never two builds at once). Honesty:
# the payload's own ``generated_at`` is the build instant, and every response
# additionally carries ``cache_age_s`` (0.0 on a fresh build) plus
# ``refresh_error`` naming the last failed rebuild, if any — stale is always
# legible as stale, never dressed up as live (rule 7: the degraded path is
# explicit and named).
#
# The SAME single-flight invariant covers the COLD path (adversarial review
# 2026-08-18): before anything is cached, concurrent GETs must not each run
# their own >120 s build — that is the identical threadpool stampede, just
# earlier in the process's life. Exactly ONE cold request takes the
# ``building`` latch and builds synchronously (the honest first-request
# cost); every concurrent arrival is answered IMMEDIATELY with an honest
# 503 + ``building: true`` (never blocked behind the build — parking waiter
# threads for minutes is the starvation this cache exists to prevent; the
# UI's poll simply retries and gets the cached result). A FAILING cold
# builder BACKS OFF: its named error is served for COLD_RETRY_S without
# re-invoking the build, so a broken ledger cannot be hammered into a
# build-per-poll loop. Both degraded shapes are explicit and named (rule 7).
CACHE_FRESH_S = 90.0
COLD_RETRY_S = 15.0

# MIRRORS orchestrator/nara_daemon.py HUMAN_GAP_MARKERS — the two "await human"
# gap shapes, which are NOT agent-actionable. Pinned against the daemon's own
# tuple by test_lab_todo.py (the daemon is unimportable on the production venv,
# so the constant is mirrored, not imported).
HUMAN_GAP_MARKERS = ("await a human gate verdict", "await human review")

# The six ladder rungs (schema/idea_ledger.schema.json evidence_level enum).
# `idea_projection._owed` RAISES on anything else (its evidence_ladder path,
# `next_test_owed`, refuses unknown levels), so an off-enum level is reported
# explicitly below rather than asked for.
_LEVELS = ("L0", "L1", "L2", "L3", "L4", "L5")

# The kill codes D-064's `refine_idea` can still act on: a cluster killed by a
# CRITIQUE that named concrete prior work or a fixable flaw — the improvement
# information is otherwise discarded with the idea. The other three codes
# (adversarial_refuted / experiment_invalid / experiment_null_effect) died on
# RESULTS, which re-articulation cannot argue away.
REFINABLE_KILL_CODES = ("redteam_fatal_flaw", "paper_prior_exists")
REFINE_CAP = 12  # newest first; the paper-seeded graveyard is thousands long


def _persisted_gaps(run_state_dir: Path) -> tuple[list[str], str | None]:
    """The gaps the coordinator planned from on its most recent cycle, and
    that cycle's timestamp. ``([], None)`` when no cycle has ever recorded
    one (a cold checkout, or a log predating planner_state)."""
    rows = _read_jsonl(Path(run_state_dir) / "coordinator_cycles.jsonl")
    rows.sort(key=lambda r: r.get("timestamp") or "", reverse=True)
    for row in rows:
        planner_state = row.get("planner_state")
        if not isinstance(planner_state, dict):
            continue
        gaps = [g for g in (planner_state.get("gaps") or []) if isinstance(g, str)]
        if gaps:
            ts = row.get("timestamp")
            return gaps, ts if isinstance(ts, str) else None
    return [], None


def register(
    app,
    *,
    repo_root: Path,
    run_state_dir: Path,
    memory_dir: Path,
    fresh_s: float = CACHE_FRESH_S,
    cold_retry_s: float = COLD_RETRY_S,
    clock=time.monotonic,
    builder=None,
) -> APIRouter:
    """Attach the lab-todo router. ``repo_root`` is the primary checkout (its
    ``orchestrator/`` + ``workers/`` packages carry every projection used
    here); ``run_state_dir`` carries active_run.json + coordinator_cycles.jsonl
    and ``memory_dir`` the loop_memory / surfaced / feedback / idea_ledger
    files (the same split the coordinator + human_todo registrations use)."""
    router = APIRouter(prefix="/api", tags=["lab_todo"])

    def _build():
        """The full (potentially slow) payload build — see module docstring;
        the route below serves it through the stale-while-revalidate cache."""
        # LAZY import: orchestrator/* and workers/* live in the primary repo,
        # not under ui/. sys.path gains the repo root once (idempotent).
        root = str(Path(repo_root))
        if root not in sys.path:
            sys.path.insert(0, root)
        try:
            import jsonschema  # idea_ledger's hard dep; names its errors below
            from workers import idea_projection
            from workers.idea_ledger import load_state
        except ImportError as exc:
            raise HTTPException(
                status_code=500,
                detail=f"idea-ledger workers unimportable from {root}: {exc}",
            ) from exc

        # --- gaps: live when the coordinator is importable, else the cycle
        # log's persisted copy. Either way the SENTENCES are the coordinator's.
        gaps_as_of: str | None = None
        try:
            from orchestrator import coordinator
        except ImportError:
            # Expected on the thin production venv — NOT an error, and NOT
            # silent: gaps_source says exactly which path produced the list.
            gaps, gaps_as_of = _persisted_gaps(run_state_dir)
            gaps_source = "last_cycle" if gaps else "unavailable"
        else:
            # assess_state is documented as never raising (a missing source
            # degrades to a thinner section), so no guard is invented here.
            snapshot = coordinator.assess_state(
                loop_memory_path=Path(memory_dir) / "loop_memory.jsonl",
                surfaced_path=Path(memory_dir) / "surfaced_findings.jsonl",
                feedback_path=Path(memory_dir) / "loop_feedback.jsonl",
                active_run_path=Path(run_state_dir) / "active_run.json",
            )
            gaps = [g for g in (snapshot.get("gaps") or []) if isinstance(g, str)]
            gaps_source = "assess_state"

        # The two lists are exact complements of `gaps` by construction.
        human_gaps = [
            g for g in gaps if any(m in g for m in HUMAN_GAP_MARKERS)
        ]
        agent_gaps = [
            g for g in gaps if not any(m in g for m in HUMAN_GAP_MARKERS)
        ]

        # --- ledger-derived lists. Absent ledger = a cold checkout, not an
        # error: the gaps above still ship.
        owed: list[dict] = []
        agenda: list[dict] = []
        refine_candidates: list[dict] = []
        path = Path(memory_dir) / "idea_ledger.jsonl"
        if path.exists():
            try:
                state = load_state(path)
            except FileNotFoundError:
                state = {}  # rotated between exists() and read (cold path)
            except (OSError, ValueError, jsonschema.ValidationError) as exc:
                # A malformed line / invalid event / reducer violation is a
                # LOUD failure (rule 4) — never a silently thinner state.
                raise HTTPException(
                    status_code=500, detail=f"idea_ledger unreadable: {exc}"
                ) from exc

            # OPEN clusters grouped by the test their rung owes. (A cluster at
            # L4/L5 derives status "surfaced", not "open" — the surfacing bar,
            # D-059 — so these groups are L0..L3 plus any off-enum level.)
            groups: dict[str, dict] = {}
            for cid, cluster in sorted(state.items()):
                if not isinstance(cluster, dict):
                    continue
                if cluster.get("status") != "open":
                    continue
                level = cluster.get("evidence_level")
                rung = level if isinstance(level, str) else str(level)
                if rung not in groups:
                    groups[rung] = {
                        "test": (
                            idea_projection._owed(rung)
                            if rung in _LEVELS
                            # Honest, uncoerced: an off-enum rung has no owed
                            # test to name (loop_health.ladder_gaps says the
                            # same thing about the same clusters).
                            else f"unknown evidence level {rung!r} — "
                                 "ladder position cannot be assessed"
                        ),
                        "rung": rung,
                        "clusters": [],
                    }
                groups[rung]["clusters"].append({
                    "cluster_id": str(cid),
                    "stem": idea_projection._stem(cluster),
                    "last_event_ts": cluster.get("last_event_ts"),
                })
            owed = sorted(
                groups.values(),
                key=lambda g: (
                    _LEVELS.index(g["rung"]) if g["rung"] in _LEVELS
                    else len(_LEVELS),
                    g["rung"],
                ),
            )

            agenda = idea_projection.agenda_topics(state)

            # KILLED clusters `refine_idea` (D-064) could still improve: a
            # critique-shaped kill with no refinement attempted yet.
            scored: list[tuple[str, str, dict]] = []
            for cid, cluster in state.items():
                if not isinstance(cluster, dict):
                    continue
                if cluster.get("status") != "killed":
                    continue
                kr = cluster.get("kill_reason")
                code = kr.get("code") if isinstance(kr, dict) else None
                if code not in REFINABLE_KILL_CODES:
                    continue
                if cluster.get("refine_history"):
                    continue  # already been through a refine cycle
                scored.append((
                    str(cluster.get("last_event_ts") or ""),
                    str(cid),
                    {"cluster_id": str(cid),
                     "stem": idea_projection._stem(cluster),
                     "kill_code": code},
                ))
            scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
            refine_candidates = [row[2] for row in scored[:REFINE_CAP]]

        return {
            "agent_gaps": agent_gaps,
            "human_gaps": human_gaps,
            "gaps_source": gaps_source,
            "gaps_as_of": gaps_as_of,
            "owed": owed,
            "agenda": agenda,
            "refine_candidates": refine_candidates,
            "generated_at": datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
        }

    build = builder or _build  # test seam: inject a counting/stub builder
    # Stale-while-revalidate state (module docstring). ``building`` is the
    # single-flight latch shared by BOTH build paths — the background
    # rebuild thread (stale) and the synchronous first build (cold).
    # ``cold_error``/``cold_error_at`` carry the failing-cold-build backoff.
    state: dict = {"payload": None, "built_at": None, "building": False,
                   "refresh_error": None, "cold_error": None,
                   "cold_error_at": None}
    lock = threading.Lock()

    def _rebuild():
        """Background single-flight rebuild. A failure keeps the last good
        payload serving and is NAMED on it via refresh_error (rule 7)."""
        try:
            payload = build()
        except HTTPException as exc:
            with lock:
                state["refresh_error"] = str(exc.detail)
                state["building"] = False
            return
        except Exception as exc:  # a crashed rebuild must not kill serving
            with lock:
                state["refresh_error"] = f"{type(exc).__name__}: {exc}"
                state["building"] = False
            return
        with lock:
            state["payload"] = payload
            state["built_at"] = clock()
            state["refresh_error"] = None
            state["building"] = False

    @router.get("/lab_todo")
    def lab_todo():
        """What the lab owes ITSELF: the agent-actionable gaps, the test each
        open cluster's rung owes, the queued agenda, and the killed clusters
        `refine_idea` could still improve. Served stale-while-revalidate; the
        response names its own age (cache_age_s) and any failed refresh."""
        with lock:
            cached = state["payload"]
            built_at = state["built_at"]
            if cached is not None and built_at is not None:
                age = max(0.0, clock() - built_at)
                if age >= fresh_s and not state["building"]:
                    state["building"] = True
                    threading.Thread(target=_rebuild, daemon=True).start()
                out = dict(cached)
                out["cache_age_s"] = round(age, 1)
                out["refresh_error"] = state["refresh_error"]
                return out
            # COLD path: nothing cached yet. Same ``building`` single-flight
            # latch as the stale path — exactly ONE request builds; a
            # concurrent arrival is answered immediately and honestly
            # rather than stacking a second >120 s build (see the invariant
            # comment at CACHE_FRESH_S).
            if state["building"]:
                return JSONResponse(
                    status_code=503,
                    content={
                        "detail": "lab_todo payload is building — retry "
                                  "shortly",
                        "building": True,
                    },
                )
            # Failing-builder backoff: within cold_retry_s of a failed cold
            # build, serve the SAME named error without re-invoking the
            # builder — a broken ledger must not be hammered per poll.
            erred_at = state["cold_error_at"]
            if erred_at is not None and (clock() - erred_at) < cold_retry_s:
                raise HTTPException(
                    status_code=500,
                    detail=f"{state['cold_error']} (cold build backing off; "
                           f"retries after {cold_retry_s:g}s)",
                )
            state["building"] = True
        # Build OUTSIDE the lock (the whole point — nothing serializes on
        # the >120 s build); errors surface exactly as they always did,
        # with the latch released and the backoff window recorded.
        try:
            payload = build()
        except HTTPException as exc:
            with lock:
                state["building"] = False
                state["cold_error"] = str(exc.detail)
                state["cold_error_at"] = clock()
            raise
        except Exception as exc:
            with lock:
                state["building"] = False
                state["cold_error"] = f"{type(exc).__name__}: {exc}"
                state["cold_error_at"] = clock()
            raise
        with lock:
            state["payload"] = payload
            state["built_at"] = clock()
            state["refresh_error"] = None
            state["building"] = False
            state["cold_error"] = None
            state["cold_error_at"] = None
        out = dict(payload)
        out["cache_age_s"] = 0.0
        out["refresh_error"] = None
        return out

    app.include_router(router)
    return router
