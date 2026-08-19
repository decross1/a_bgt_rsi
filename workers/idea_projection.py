"""Worker: deterministic projections of the idea-ledger state (P3 / A4,
LOOP_V1.md).

The ledger (`workers/idea_ledger.py`) is the append-only source of truth;
THIS module is pure projection — three read-only views over the reduced
cluster state (`idea_ledger.load_state` shape: dict keyed by cluster_id):

  * `render_ideas_md(state)`      -> the three-section `ideas.md` text
  * `conditioning_lines(state, topic)` -> compact prompt-conditioning lines
  * `agenda_topics(state)`        -> open agenda items as topic dicts

BYTE-STABLE: the same state dict renders to identical bytes regardless of
dict insertion order — every iteration sorts on cluster_id, no wall-clock
reads, no randomness. Timestamps shown are the ledger's own `last_event_ts`.

Section semantics (per the A4 contract):
  ## Live work  — one line per status=="open" cluster: stem, evidence level,
                  next test owed, last touched. (status=="surfaced" clusters
                  are deliberately NOT re-listed here — they live in
                  surfaced_findings; the projection does not duplicate them.)
  ## Graveyard  — status=="killed": kill_reason code + reopening condition.
  ## Agenda     — open agenda items with provenance (source + cluster). A
                  KILLED cluster's agenda is NOT listed: it lives in the
                  Graveyard, and re-entry is the evidence-keyed
                  `cluster_reopened` event, never an agenda item.

Agenda convention (tolerant, documented — reconciled with idea_ledger at
integration): a cluster entry carries agenda items under its "agenda" key,
either one dict or a list of dicts, each {"topic": str, "source": str?,
"status": "open"|"consumed"?}. Consumed items are skipped; a missing topic
falls back to the cluster stem; a missing source falls back to the cluster's
`origin`.

`next_test_owed` prefers the cross-module `workers.evidence_ladder` import;
when that sibling is absent (parallel build) the EXPLICIT local map below is
used — same rung ordering, spec'd in LOOP_V1 P1. This is the spec-authorized
import-guard, not a silent fallback: `LADDER_SOURCE` records which path is
live.
"""
from __future__ import annotations

import json
from typing import Any

from workers.retrieval_relevance import _tokenize

try:  # sibling A1 worker; absent while limbs build in parallel (see docstring)
    from workers.evidence_ladder import next_test_owed as _next_test_owed
    LADDER_SOURCE = "evidence_ladder"
except ImportError:
    _next_test_owed = None
    LADDER_SOURCE = "local_map"

# Local rung->owed-test map (LOOP_V1 P1 ladder), used only when
# workers.evidence_ladder is not importable.
_NEXT_TEST_OWED = {
    "L0": "literature screen (relevance ok + novel + critique survives + redteam not fatal)",
    "L1": "experiment_outcome with trials >= 30 and a non-INVALID summary",
    "L2": "cross-tier comparison / replication evidence",
    "L3": "adversarial vote survived=True AND redteam verdict proceed",
    "L4": "human validity verdict",
    "L5": "none — ladder complete",
}

STEM_MAX = 80             # stem truncation for one-line views
GRAVEYARD_MATCH_CAP = 5   # conditioning: max lexically-adjacent killed clusters
AGENDA_CONTEXT_CAP = 3    # conditioning: max agenda-context lines


def _owed(level: str) -> str:
    """Next test owed for an evidence level — evidence_ladder when importable,
    else the explicit local map. An unknown level renders as such, never
    coerced to a rung."""
    if _next_test_owed is not None:
        return str(_next_test_owed(level))
    return _NEXT_TEST_OWED.get(level, f"unknown level {level!r}")


def _stem(cluster: dict) -> str:
    """Short human label for a cluster: elite claim's problem, else the
    cluster topic, else the cluster_id. Truncated to STEM_MAX."""
    elite = cluster.get("elite") if isinstance(cluster.get("elite"), dict) else {}
    claim = elite.get("claim") if isinstance(elite.get("claim"), dict) else elite
    text = claim.get("problem") if isinstance(claim.get("problem"), str) else None
    if not (text and text.strip()):
        topic = cluster.get("topic")
        text = topic if isinstance(topic, str) and topic.strip() else ""
    if not text.strip():
        text = str(cluster.get("cluster_id") or "unnamed-cluster")
    text = " ".join(text.split())  # collapse whitespace for one-line stability
    if len(text) > STEM_MAX:
        text = text[: STEM_MAX - 3].rstrip() + "..."
    return text


def _dict_str(d: Any, *keys: str, empty: str) -> str:
    """First present string among `keys` in dict d; a non-dict/miss renders
    the whole value deterministically (sorted-key JSON), None -> `empty`."""
    if isinstance(d, dict):
        for k in keys:
            v = d.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return json.dumps(d, sort_keys=True, ensure_ascii=False)
    if d is None:
        return empty
    return str(d)


def _kill_str(kill_reason: Any) -> str:
    return _dict_str(kill_reason, "code", "reason", empty="unspecified")


def _reopen_str(cond: Any) -> str:
    return _dict_str(cond, "description", "condition", empty="none recorded")


def _sorted_clusters(state: dict) -> list[tuple[str, dict]]:
    return sorted(
        ((cid, c) for cid, c in state.items() if isinstance(c, dict)),
        key=lambda kv: str(kv[0]),
    )


def agenda_topics(state: dict) -> list[dict]:
    """Open agenda items as [{topic, source, cluster_id}], sorted on
    (cluster_id, topic). See module docstring for the carrier convention.

    A KILLED cluster contributes NOTHING (defense in depth, layer 2). This is
    the projection the coordinator's agenda-first topic selection reads
    (`orchestrator/coordinator.py` puts these at the HEAD of its topic list),
    so an agenda item left on a cluster that was later killed would put the
    graveyard direction back in the loop with no `cluster_reopened` event —
    exactly what `idea_ledger`'s evidence-keyed reopen gate exists to stop.
    `agenda_cli.accept` refuses a killed cluster up front, but the ordering
    "accepted while OPEN, killed afterwards" is reachable and only this layer
    covers it. A reopen (which clears kill_reason) restores the items."""
    out: list[dict] = []
    for cid, cluster in _sorted_clusters(state):
        if cluster.get("status") == "killed":
            continue
        raw = cluster.get("agenda")
        items = raw if isinstance(raw, list) else [raw] if isinstance(raw, dict) else []
        for item in items:
            if not isinstance(item, dict) or item.get("status") == "consumed":
                continue
            topic = item.get("topic")
            topic = topic.strip() if isinstance(topic, str) and topic.strip() else _stem(cluster)
            source = item.get("source")
            if not (isinstance(source, str) and source.strip()):
                source = str(cluster.get("origin") or "unknown")
            out.append({"topic": topic, "source": source.strip(), "cluster_id": str(cid)})
    out.sort(key=lambda d: (d["cluster_id"], d["topic"]))
    return out


def render_ideas_md(state: dict) -> str:
    """Render the byte-stable three-section ideas.md text (see module
    docstring for section semantics). Ends with a single trailing newline."""
    live: list[str] = []
    grave: list[str] = []
    for cid, c in _sorted_clusters(state):
        status = c.get("status")
        if status == "open":
            level = c.get("evidence_level") if isinstance(c.get("evidence_level"), str) else "L0"
            live.append(
                f"- {_stem(c)} · {level} · next: {_owed(level)}"
                f" · last touched {c.get('last_event_ts') or 'unknown'}"
            )
        elif status == "killed":
            grave.append(
                f"- {_stem(c)} · killed: {_kill_str(c.get('kill_reason'))}"
                f" · reopen when: {_reopen_str(c.get('reopening_condition'))}"
            )
    agenda = [
        f"- {a['topic']} · source: {a['source']} · cluster: {a['cluster_id']}"
        for a in agenda_topics(state)
    ]
    parts = ["# Ideas", ""]
    for title, lines in (("## Live work", live), ("## Graveyard", grave), ("## Agenda", agenda)):
        parts.append(title)
        parts.append("")
        parts.extend(lines if lines else ["(none)"])
        parts.append("")
    return "\n".join(parts[:-1]) + "\n"


def conditioning_lines(state: dict, topic: str) -> list[str]:
    """Compact lines for the generation prompt: killed clusters lexically
    adjacent to `topic` (directional token overlap on stem + kill reason,
    best-first, capped) followed by agenda context (capped). Deterministic;
    an off-topic graveyard contributes zero lines — never padded."""
    ttoks = _tokenize(topic)
    scored: list[tuple[float, str, dict]] = []
    for cid, c in _sorted_clusters(state):
        if c.get("status") != "killed":
            continue
        ktoks = _tokenize(f"{_stem(c)} {_kill_str(c.get('kill_reason'))}")
        if not ttoks or not ktoks:
            continue
        overlap = len(ttoks & ktoks) / len(ttoks)
        if overlap > 0.0:
            scored.append((overlap, str(cid), c))
    scored.sort(key=lambda x: (-x[0], x[1]))
    lines = [
        f"KILLED prior [{cid}]: {_stem(c)} — {_kill_str(c.get('kill_reason'))};"
        f" reopen only if: {_reopen_str(c.get('reopening_condition'))}"
        for _, cid, c in scored[:GRAVEYARD_MATCH_CAP]
    ]
    lines += [
        f"AGENDA [{a['cluster_id']}]: {a['topic']} (source: {a['source']})"
        for a in agenda_topics(state)[:AGENDA_CONTEXT_CAP]
    ]
    return lines
