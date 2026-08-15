"""Evidence-ladder read seam (UI simplification S1 — GET /api/ladder).

One read-only GET, wired by ``register`` into the existing FastAPI app
(the ``loop_alert.py`` register-fn idiom). It reduces the idea ledger
(``memory/idea_ledger.jsonl``, append-only — workers/idea_ledger.py) to
the /ladder page's payload:

    {clusters: [{cluster_id, stem, status, evidence_level, origin,
                 members, member_count, last_event_ts, kill_reason,
                 reopening_condition, open_agenda_count}],
     histogram: {L0..L5: n},        # non-killed clusters per rung
     counts: {open, surfaced, killed},
     agenda: [{topic, source, cluster_id}],
     next_owed: {L0..L5: "<test owed>"}}

The reducer + projection helpers are REUSED via lazy import inside the
handler — never reimplemented. uvicorn's cwd is ``ui/``, so the primary
repo root (threaded in like the other registrations get memory_dir) is
put on sys.path first. Absent ledger = 204 (a cold checkout is not an
error); an unreadable/invalid ledger is an honest 500 with the error in
``detail`` — idea_ledger's loud-failure ValueErrors are never coerced
into a thinner state (rule 4). The UI never writes ``memory/``.
"""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response

# The six ladder rungs (schema/idea_ledger.schema.json evidence_level enum).
_LEVELS = ("L0", "L1", "L2", "L3", "L4", "L5")


def register(
    app,
    *,
    repo_root: Path,
    memory_dir: Path,
) -> APIRouter:
    """Attach the ladder router. ``repo_root`` is the primary checkout (its
    ``workers/`` package carries the reducer); ``memory_dir`` carries
    idea_ledger.jsonl (the same split the coordinator registrations use)."""
    router = APIRouter(prefix="/api", tags=["ladder"])

    @router.get("/ladder")
    def ladder():
        """The reduced idea-ledger state, projected for the /ladder page.
        204 when the ledger has never been written on this checkout."""
        path = Path(memory_dir) / "idea_ledger.jsonl"
        if not path.exists():
            return Response(status_code=204)

        # LAZY import: workers.* lives in the primary repo, not under ui/.
        # sys.path gains the repo root once (idempotent) — the loop_v0
        # registrations thread the same root for their subprocess work.
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

        try:
            state = load_state(path)
        except FileNotFoundError:
            # Race: ledger rotated between exists() and read (cold path).
            return Response(status_code=204)
        except (OSError, ValueError, jsonschema.ValidationError) as exc:
            # A malformed line / invalid event / reducer violation is a LOUD
            # failure (rule 4) — surfaced honestly, never a thinner state.
            raise HTTPException(
                status_code=500, detail=f"idea_ledger unreadable: {exc}"
            ) from exc

        clusters = []
        counts = {"open": 0, "surfaced": 0, "killed": 0}
        histogram = {level: 0 for level in _LEVELS}
        for cid, c in sorted(state.items()):
            status = c.get("status")
            if status in counts:
                counts[status] += 1
            level = c.get("evidence_level")
            # Histogram = live rungs only: a killed cluster's residual level
            # is graveyard detail, not "what's cooking".
            if status != "killed" and level in histogram:
                histogram[level] += 1
            agenda_items = c.get("agenda") or []
            open_agenda = sum(
                1
                for a in agenda_items
                if isinstance(a, dict) and a.get("status") != "consumed"
            )
            # The member ids themselves (normally iteration_ids — see the
            # schema's member_id def; niche-seeded clusters carry
            # "paper:<arxiv_id>"). R1's peek panel links the iteration-shaped
            # ones onward to /dossier/:id, so the list ships, not just its
            # length.
            members = list(c.get("members") or [])
            clusters.append({
                "cluster_id": cid,
                # Reuse the projection's deterministic naming/owed helpers —
                # the same stems ideas.md shows (never a second impl).
                "stem": idea_projection._stem(c),
                "status": status,
                "evidence_level": level,
                "origin": c.get("origin"),
                "members": members,
                "member_count": len(members),
                "last_event_ts": c.get("last_event_ts"),
                "kill_reason": c.get("kill_reason"),
                "reopening_condition": c.get("reopening_condition"),
                "open_agenda_count": open_agenda,
            })

        return {
            "clusters": clusters,
            "histogram": histogram,
            "counts": counts,
            "agenda": idea_projection.agenda_topics(state),
            "next_owed": {level: idea_projection._owed(level) for level in _LEVELS},
        }

    app.include_router(router)
    return router
