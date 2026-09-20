"""Evidence-ladder read seam (UI simplification S1 — GET /api/ladder).

One read-only GET, wired by ``register`` into the existing FastAPI app
(the ``loop_alert.py`` register-fn idiom). It reduces the idea ledger
(``memory/idea_ledger.jsonl``, append-only — workers/idea_ledger.py) to
the /ladder page's payload.  The ledger's recorded rung is historical state;
the public ``evidence_level`` and live status are rederived from exact source
rows through the canonical evidence grader on every read:

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
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Response

from .research_scope import ResearchScope, ScopeName, read_records

# The six ladder rungs (schema/idea_ledger.schema.json evidence_level enum).
_LEVELS = ("L0", "L1", "L2", "L3", "L4", "L5")
_LEVEL_INDEX = {level: index for index, level in enumerate(_LEVELS)}


def _identity(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _unique_index(
    rows: list[dict[str, Any]], field: str,
) -> tuple[dict[str, dict[str, Any]], set[str]]:
    counts = Counter(
        identity
        for row in rows
        if (identity := _identity(row.get(field))) is not None
    )
    return (
        {
            row[field]: row
            for row in rows
            if _identity(row.get(field)) is not None and counts[row[field]] == 1
        },
        {identity for identity, count in counts.items() if count > 1},
    )


def _time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _latest(rows: list[dict[str, Any]], *fields: str) -> dict[str, Any] | None:
    timed = []
    for index, row in enumerate(rows):
        timestamp = next(
            (parsed for field in fields if (parsed := _time(row.get(field))) is not None),
            None,
        )
        timed.append((timestamp, index, row))
    timed = [item for item in timed if item[0] is not None]
    return max(timed, key=lambda item: (item[0], item[1]))[2] if timed else None


def _same_campaign(source: dict[str, Any], related: dict[str, Any]) -> bool:
    campaign = source.get("campaign")
    return not isinstance(campaign, dict) or related.get("campaign") == campaign


def _project_evidence(
    cluster: dict[str, Any],
    *,
    iterations: dict[str, dict[str, Any]],
    ambiguous_iterations: set[str],
    findings: dict[str, dict[str, Any]],
    ambiguous_findings: set[str],
    findings_by_iteration: dict[str, list[dict[str, Any]]],
    feedback_by_iteration: dict[str, list[dict[str, Any]]],
    health_rows: list[dict[str, Any]],
    repo_root: Path,
    derive_verified_level,
    v2_hypothesis_failures,
) -> dict[str, Any]:
    """Rebind a cluster to unique source rows and rederive its elite rung."""
    members = cluster.get("members")
    member_ids = members if isinstance(members, list) else []
    resolved: dict[str, dict[str, Any]] = {}
    unresolved: list[str] = []
    ambiguous = False
    for member in member_ids:
        if not isinstance(member, str) or not member:
            unresolved.append("invalid_member")
            continue
        row = iterations.get(member)
        if row is None:
            finding = findings.get(member)
            if finding is not None:
                source_id = _identity(finding.get("source_iteration_id"))
                source = iterations.get(source_id or "")
                if source is not None and _same_campaign(source, finding):
                    row = source
                else:
                    unresolved.append("missing_finding_source")
                    ambiguous = ambiguous or bool(
                        source_id in ambiguous_iterations
                    )
                    continue
            else:
                unresolved.append("ambiguous_member" if (
                    member in ambiguous_iterations or member in ambiguous_findings
                ) else "missing_member")
                ambiguous = ambiguous or (
                    member in ambiguous_iterations or member in ambiguous_findings
                )
                continue
        iteration_id = _identity(row.get("iteration_id"))
        if iteration_id is None:
            unresolved.append("missing_iteration_identity")
            continue
        resolved[iteration_id] = row

    levels: list[str] = []
    provisional: set[str] = set()
    source_contracts: set[str] = set()
    for iteration_id, row in resolved.items():
        feedback = _latest(
            feedback_by_iteration.get(iteration_id, []), "gated_at", "timestamp"
        )
        compatible_findings = [
            finding
            for finding in findings_by_iteration.get(iteration_id, [])
            if _same_campaign(row, finding)
        ]
        finding = _latest(compatible_findings, "promoted_at", "timestamp")
        adversarial = (
            finding.get("adversarial")
            if isinstance(finding, dict) and isinstance(finding.get("adversarial"), dict)
            else None
        )
        derived = derive_verified_level(
            row, feedback, adversarial, health_rows, repo_root=repo_root
        )
        level = derived.get("level")
        if level in _LEVEL_INDEX:
            levels.append(level)
        provisional.update(
            marker
            for marker in derived.get("provisional", [])
            if isinstance(marker, str)
        )
        if isinstance(row.get("campaign"), dict):
            source_contracts.add(
                "v2_contract_valid"
                if not v2_hypothesis_failures(row)
                else "v2_contract_invalid"
            )
        else:
            source_contracts.add("legacy_unverified")

    level = max(levels, key=_LEVEL_INDEX.__getitem__) if levels else None
    if not resolved:
        qualification = "source_ambiguous" if ambiguous else "source_unavailable"
    elif unresolved:
        qualification = "partial"
    else:
        qualification = "rederived"
    if "v2_contract_invalid" in source_contracts:
        claim_source_status = "v2_contract_invalid"
    elif source_contracts == {"v2_contract_valid"}:
        claim_source_status = "v2_contract_valid"
    elif source_contracts == {"legacy_unverified"}:
        claim_source_status = "legacy_unverified"
    elif source_contracts:
        claim_source_status = "mixed"
    else:
        claim_source_status = "unavailable"
    return {
        "level": level,
        "qualification": {
            "status": qualification,
            "exact_source_count": len(resolved),
            "unresolved_member_count": len(unresolved),
            "provisional": sorted(provisional),
        },
        "claim_source_status": claim_source_status,
    }


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
    def ladder(research_scope: ScopeName = "all"):
        """The reduced idea-ledger state, projected for the /ladder page.
        204 when the ledger has never been written on this checkout."""
        scope = ResearchScope(research_scope, Path(repo_root), Path(memory_dir))
        path = Path(memory_dir) / "idea_ledger.jsonl"
        if research_scope == "all" and not path.exists():
            return Response(status_code=204)

        # LAZY import: workers.* lives in the primary repo, not under ui/.
        # sys.path gains the repo root once (idempotent) — the loop_v0
        # registrations thread the same root for their subprocess work.
        root = str(Path(repo_root))
        if root not in sys.path:
            sys.path.insert(0, root)
        try:
            import jsonschema  # idea_ledger's hard dep; names its errors below

            from orchestrator.experiment_admission import derive_verified_level
            from workers import idea_projection
            from workers.evidence_ladder import v2_hypothesis_failures
            from workers.idea_ledger import load_state
        except ImportError as exc:
            raise HTTPException(
                status_code=500,
                detail=f"idea-ledger workers unimportable from {root}: {exc}",
            ) from exc

        try:
            state = scope.ledger_snapshot()[1] if research_scope == "active" else load_state(path)
        except FileNotFoundError:
            # Race: ledger rotated between exists() and read (cold path).
            return Response(status_code=204)
        except (OSError, ValueError, jsonschema.ValidationError) as exc:
            # A malformed line / invalid event / reducer violation is a LOUD
            # failure (rule 4) — surfaced honestly, never a thinner state.
            raise HTTPException(
                status_code=500, detail=f"idea_ledger unreadable: {exc}"
            ) from exc

        original_count = len(state)
        state = scope.clusters(state)
        all_iterations = read_records(Path(memory_dir) / "loop_memory.jsonl")
        unique_iterations, ambiguous_iterations = _unique_index(
            all_iterations, "iteration_id"
        )
        if research_scope == "active":
            scoped = scope.records(all_iterations, "iteration_id")
            iterations = {
                row["iteration_id"]: row
                for row in scoped
                if _identity(row.get("iteration_id")) is not None
            }
        else:
            iterations = unique_iterations

        surfaced_rows = read_records(Path(memory_dir) / "surfaced_findings.jsonl")
        findings, ambiguous_findings = _unique_index(surfaced_rows, "finding_id")
        findings_by_iteration: dict[str, list[dict[str, Any]]] = defaultdict(list)
        # Only globally unique, convention-bound findings may donate an
        # adversarial vote.  A duplicated or differently keyed finding stays
        # readable elsewhere, but cannot raise a source row to L4 here.
        for finding in findings.values():
            source_id = _identity(finding.get("source_iteration_id"))
            if (
                source_id is not None
                and _identity(finding.get("finding_id")) == f"sf-{source_id}"
            ):
                findings_by_iteration[source_id].append(finding)
        feedback_by_iteration: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for feedback in read_records(Path(memory_dir) / "loop_feedback.jsonl"):
            iteration_id = _identity(feedback.get("iteration_id"))
            if iteration_id is not None:
                feedback_by_iteration[iteration_id].append(feedback)
        health_rows = read_records(Path(repo_root) / "run_state/health_signals.jsonl")

        clusters = []
        counts = {"open": 0, "surfaced": 0, "killed": 0}
        histogram = {level: 0 for level in _LEVELS}
        for cid, c in sorted(state.items()):
            historical_status = c.get("status")
            historical_level = c.get("evidence_level")
            evidence = _project_evidence(
                c,
                iterations=iterations,
                ambiguous_iterations=ambiguous_iterations,
                findings=findings,
                ambiguous_findings=ambiguous_findings,
                findings_by_iteration=findings_by_iteration,
                feedback_by_iteration=feedback_by_iteration,
                health_rows=health_rows,
                repo_root=Path(repo_root),
                derive_verified_level=derive_verified_level,
                v2_hypothesis_failures=v2_hypothesis_failures,
            )
            level = evidence["level"]
            # An explicit negative result remains killed. Every other live
            # disposition follows the currently rederived rung, rather than a
            # stale ledger status that may have been earned under older rules.
            status = (
                "killed"
                if historical_status == "killed"
                else "surfaced"
                if level in {"L4", "L5"}
                else "open"
            )
            if status in counts:
                counts[status] += 1
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
                "historical_status": historical_status,
                "historical_evidence_level": historical_level,
                "evidence_qualification": evidence["qualification"],
                "claim_source_status": evidence["claim_source_status"],
                "origin": c.get("origin"),
                "members": members,
                "member_count": len(members),
                "last_event_ts": c.get("last_event_ts"),
                "kill_reason": c.get("kill_reason"),
                "reopening_condition": c.get("reopening_condition"),
                "open_agenda_count": open_agenda,
            })

        return {
            **({"research_scope": {**scope.metadata(), "omitted_clusters": original_count - len(state)}} if research_scope == "active" else {}),
            "clusters": clusters,
            "histogram": histogram,
            "counts": counts,
            "agenda": idea_projection.agenda_topics(state),
            "next_owed": {level: idea_projection._owed(level) for level in _LEVELS},
        }

    app.include_router(router)
    return router
