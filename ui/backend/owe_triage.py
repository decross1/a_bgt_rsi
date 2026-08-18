"""Owe-card triage enrichment — ADDITIVE derived fields on /api/human_todo items.

The owner's 2026-08-18 ask: the "What you owe" hero listed 7 items, some ~70
days old, with no way to tell a live approval from a fossil. This module makes
each item legible — what the human is DOING, what the approval MEANS (the
concrete state change), what to VET first — and tags items the ledger has
plausibly overtaken. It derives everything from the SAME stores the queue is
composed from (plus ``memory/idea_ledger.jsonl``); it writes nothing and
removes nothing.

Triage heuristics (documented here and in every reason string; a tag NEVER
auto-dismisses — the item stays listed and counted, the human disposes):

- **H-OBS**   ``bubble_ack`` / ``stale_active_run`` are informational, not
  approvals -> ``triage: "observable"``.
- **H-KILL**  a ``gate_verdict`` / ``finding_review`` item whose iteration or
  finding is a member of an idea-ledger cluster with a ``cluster_killed``
  event -> ``triage: "likely_superseded"``. The reason names the cluster, the
  kill code, and the kill date. When the kill's ``evidence_key`` cites the
  item's OWN record (its iteration_id or its experiment_id), the reason says
  so explicitly: the loop already consumed this iteration's result — a
  verdict now ratifies or contests a kill already taken.
- everything else -> ``triage: "valid"`` (a real, live ask).

Derived keys per item (all additive; no existing key changes):
``action`` (verb phrase), ``doing`` (one sentence), ``approval_means`` (the
state change the resolution triggers), ``vet`` (2-3 bullets drawn from the
item's own record), ``triage``, ``triage_reason``, and — when the ledger knows
the item — ``cluster`` ``{cluster_id, killed, kill_code, kill_ts, kill_detail}``.

Enrichment is best-effort display derivation, NOT a validation (rule 4 is
about pass/fail checks): a failure to derive leaves the item exactly as
composed, which the card renders as an untagged generic row — visible, never
masked. The endpoint's never-500 contract is preserved.
"""
from __future__ import annotations

import json
from pathlib import Path

TRIAGE_VALID = "valid"
TRIAGE_OBSERVABLE = "observable"
TRIAGE_LIKELY_SUPERSEDED = "likely_superseded"

_OBSERVABLE_KINDS = ("bubble_ack", "stale_active_run")
_GATE_KINDS = ("gate_verdict",)
_STATE_KINDS = ("state_gate", "state_file_gate")


def _read_jsonl(path: Path) -> list[dict]:
    """Tolerant JSONL read (same shape as human_todo._read_jsonl but never
    raises: enrichment must not take the endpoint down over an unreadable
    side-store)."""
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
                    parsed = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    rows.append(parsed)
    except OSError:
        return []
    return rows


def _txt(value) -> str:
    return value if isinstance(value, str) else ""


def membership_from_rows(rows: list[dict]) -> dict[str, str]:
    """member_id -> cluster_id: THE one deterministic membership join,
    shared by this module's ``_ledger_index`` and
    ``human_todo._ledger_clusters`` (B2 fix 2026-08-18: human_todo used to
    rebuild member_of from a set union, so a member of TWO clusters — the
    live d075_r4_dup_relink pattern, where iter-2026-08-18-001/002/003 each
    sit in an open surviving cluster AND a killed superseded_duplicate
    self-cluster — mapped PYTHONHASHSEED-dependently).

    Rule: the LAST membership event in ledger FILE ORDER wins, reading
    member_id + iteration_id off every ``cluster_created`` and
    ``member_added``. The d075 R4 relink appends the surviving cluster's
    ``member_added`` AFTER the duplicate's create, so the open cluster wins
    by construction."""
    membership: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        cid = _txt(row.get("cluster_id"))
        if not cid:
            continue
        if _txt(row.get("event_type")) in ("cluster_created", "member_added"):
            for key in ("member_id", "iteration_id"):
                member = _txt(row.get(key))
                if member:
                    membership[member] = cid
    return membership


def _ledger_index(memory_dir: Path) -> tuple[dict[str, str], dict[str, dict]]:
    """Fold ``idea_ledger.jsonl`` (event-sourced) into:

    - member_id -> cluster_id via ``membership_from_rows`` (the shared
      deterministic join: last membership event in file order wins), and
    - cluster_id -> the LAST STANDING ``cluster_killed`` event. A
      ``cluster_reopened`` event CLEARS the kill — the reducer's own
      semantics (workers/idea_ledger.py reduce_events resets kill_reason to
      None on reopen), honored here in the tolerant scan too; the
      2026-08-18 docstring claim that "no reopen event type exists" was
      false (cluster_reopened is a schema member and the reducer handles
      it).
    """
    rows = _read_jsonl(memory_dir / "idea_ledger.jsonl")
    membership = membership_from_rows(rows)
    kills: dict[str, dict] = {}
    for row in rows:
        cid = _txt(row.get("cluster_id"))
        if not cid:
            continue
        event = _txt(row.get("event_type"))
        if event == "cluster_killed":
            kills[cid] = row
        elif event == "cluster_reopened":
            kills.pop(cid, None)  # kill cleared — the cluster is live again
    return membership, kills


def _cluster_of(item_id: str, membership: dict[str, str],
                kills: dict[str, dict]) -> str | None:
    """The item's cluster: explicit membership first, then the consolidator's
    self-named convention (cluster ``cl-<iteration_id>``) when that cluster
    actually exists in the ledger."""
    if item_id in membership:
        return membership[item_id]
    self_named = f"cl-{item_id}"
    if self_named in kills or self_named in membership.values():
        return self_named
    return None


def _kill_facts(kill: dict) -> tuple[str, str, str, str]:
    """(code, evidence_key, detail, ts) off a cluster_killed event — every
    field producer-owned and possibly absent."""
    reason = kill.get("kill_reason")
    reason = reason if isinstance(reason, dict) else {}
    return (
        _txt(reason.get("code")) or "unknown",
        _txt(reason.get("evidence_key")),
        _txt(reason.get("detail")),
        _txt(kill.get("ts")),
    )


def _action_phrase(kind: str, item_id: str) -> str:
    if kind in _GATE_KINDS:
        return f"Record a gate verdict on {item_id}"
    if kind in _STATE_KINDS:
        return f"Clear blocking human gate '{item_id}'"
    if kind == "finding_review":
        return f"Review + disposition finding {item_id}"
    if kind == "bubble_ack":
        return "Read a coordinator note (no approval involved)"
    if kind == "stale_active_run":
        return "Check a possibly-leaked run lock"
    return f"Resolve {item_id}"


def _doing_and_means(kind: str, item_id: str) -> tuple[str, str]:
    if kind in _GATE_KINDS:
        return (
            f"Decide whether iteration {item_id}'s result is valid, invalid, "
            "or needs revision — the loop's Step-8 human gate on an "
            "experiment-stage iteration.",
            "gate_cli appends your verdict to memory/loop_feedback.jsonl "
            "(readers are last-row-wins); the iteration stops counting as "
            "pending and your verdict becomes its record. Nothing else "
            "auto-runs off it.",
        )
    if kind in _STATE_KINDS:
        return (
            "Explicitly clear a human gate the apparatus HALTs on "
            "(inviolate rule 3 — blocking until you say so).",
            "The entry is removed from run_state/week1.state.json "
            "human_gates_pending and the halted work resumes.",
        )
    if kind == "finding_review":
        return (
            "Interrogate a promoted finding and disposition it "
            "(validate / reject / spawn / refine) in the finding session.",
            "finding_session appends a status row to "
            "surfaced_findings.status.jsonl — the finding leaves "
            "surfaced/in_review and the queue.",
        )
    if kind == "bubble_ack":
        return (
            "Read a note the coordinator raised to you. Informational — "
            "nothing blocks on it.",
            "An ack row lands in memory/coordinator_acks.jsonl; no run "
            "state or ledger changes.",
        )
    if kind == "stale_active_run":
        return (
            "Check whether run_state/active_run.json is a leaked lock from "
            "a dead run.",
            "Removing the file frees the run lock; no ledger or state "
            "change beyond that.",
        )
    return (
        "Resolve this queue item.",
        "See the resolve command — it names the exact state change.",
    )


def _vet_bullets(item: dict, kill: dict | None, cluster_id: str | None) -> list[str]:
    """2-3 vet-first bullets drawn from the item's OWN record (the additive
    facts _gate_verdict_items now carries + the evidence-ladder level + the
    ledger's kill event). Never invented; absent facts contribute nothing."""
    bullets: list[str] = []
    verdict = _txt(item.get("redteam_verdict"))
    if verdict:
        if verdict == "proceed":
            bullets.append("redteam verdict: proceed — the critique found no fatal flaw")
        else:
            bullets.append(
                f"redteam verdict: {verdict} — read its rationale before "
                "trusting the headline metric"
            )
    exp = _txt(item.get("experiment_id"))
    metric = _txt(item.get("metric"))
    value = item.get("metric_value")
    if exp and metric and isinstance(value, (int, float)) and not isinstance(value, bool):
        trials = item.get("trials")
        n = f" over {trials} trials" if isinstance(trials, int) and not isinstance(trials, bool) else ""
        bullets.append(f"{exp} reports {metric} = {value}{n} — open the dossier for the summary")
    level = _txt(item.get("evidence_level"))
    if level:
        if level in ("L4", "L5"):
            bullets.append(f"evidence level {level} — cleared the ladder bar")
        else:
            bullets.append(f"evidence level {level} only — below the L4 bar")
    if kill is not None and cluster_id:
        code, _key, _detail, ts = _kill_facts(kill)
        bullets.append(
            f"its idea-ledger cluster {cluster_id} was killed "
            f"{ts[:10] or 'undated'} ({code}) — check the kill evidence "
            "before spending review time"
        )
    return bullets[:3]


def enrich_items(items: list[dict], memory_dir: Path) -> None:
    """ADDITIVE in place, matching the _tag_deferred idiom: derived display
    fields only, no existing key changes, no item removed or re-ordered.
    Any per-item derivation failure leaves that item as composed."""
    try:
        membership, kills = _ledger_index(Path(memory_dir))
    except Exception:  # noqa: BLE001 — side-store trouble never costs the queue
        membership, kills = {}, {}
    for item in items:
        try:
            _enrich_one(item, membership, kills)
        except Exception:  # noqa: BLE001 — one bad row must not strip the rest
            continue


def _enrich_one(item: dict, membership: dict[str, str],
                kills: dict[str, dict]) -> None:
    kind = _txt(item.get("kind"))
    item_id = _txt(item.get("id"))
    item["action"] = _action_phrase(kind, item_id)
    doing, means = _doing_and_means(kind, item_id)
    item["doing"] = doing
    item["approval_means"] = means

    cluster_id = None
    kill = None
    if kind in _GATE_KINDS or kind == "finding_review":
        cluster_id = _cluster_of(item_id, membership, kills)
        if cluster_id is not None:
            kill = kills.get(cluster_id)
            item["cluster"] = {
                "cluster_id": cluster_id,
                "killed": kill is not None,
                "kill_code": _kill_facts(kill)[0] if kill else None,
                "kill_ts": _kill_facts(kill)[3] if kill else None,
                "kill_detail": (_kill_facts(kill)[2][:240] or None) if kill else None,
            }

    item["vet"] = _vet_bullets(item, kill, cluster_id)

    # --- triage tag (H-OBS / H-KILL / valid), reason always stated ---------
    if kind in _OBSERVABLE_KINDS:
        item["triage"] = TRIAGE_OBSERVABLE
        item["triage_reason"] = (
            "H-OBS: informational, not an approval — nothing blocks on it"
        )
    elif kill is not None:
        code, evidence_key, _detail, ts = _kill_facts(kill)
        # Exact ':'-segment match, never substring (2026-08-18 fix: an id
        # like iter-x substring-matched "cluster:cl-iter-x" false-positively).
        segments = evidence_key.split(":")
        exp_id = _txt(item.get("experiment_id"))
        self_cited = bool(item_id and item_id in segments) or bool(
            exp_id and exp_id in segments
        )
        reason = (
            f"H-KILL: cluster {cluster_id} was killed {ts[:10] or 'undated'} "
            f"({code})"
        )
        if self_cited:
            reason += (
                " citing this iteration's own record — the loop already "
                "consumed this result; a verdict now ratifies or contests "
                "that kill"
            )
        reason += ". A tag, not a dismissal: only you can close this item."
        item["triage"] = TRIAGE_LIKELY_SUPERSEDED
        item["triage_reason"] = reason
    else:
        item["triage"] = TRIAGE_VALID
        item["triage_reason"] = (
            "no supersession signal in the stores — treated as a live ask"
        )
