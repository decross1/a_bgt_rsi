"""Worker: consolidate_memory — one-shot idempotent migration CLI (LOOP_V1 P1,
agent A7). Folds the historical corpus (memory/loop_memory.jsonl +
memory/surfaced_findings.jsonl) into idea-ledger events: clusters near-dup
claims, derives each cluster's evidence rung, kills redteam-fatal clusters
programmatically, seeds paper niches for rediscoveries, and archives near-dup
non-elite members. **Dry-run is the DEFAULT** — nothing is written until
`--execute` — because the dry-run summary is a blocking human gate (G2).

Discipline:
  * Source files (loop_memory / surfaced_findings) are NEVER rewritten or
    deleted from — the migration is append-only into the idea ledger +
    memory/idea_archive.jsonl.
  * Clustering reuses the P4 dedup layers from workers.mine_paper_gap: the
    lexical-Jaccard layer is LOAD-BEARING (the falsifier proved cosine alone
    cannot collapse reworded near-dups); cosine >= TAU_DUP catches
    near-identical restatements only.
  * Rung derivation is delegated to workers.evidence_ladder.derive_level
    (pure Python, never coerced); leaked-JSON-blob claims are repaired via
    workers.claim_extract.extract_claim; events are appended via
    workers.idea_ledger.append_event. All three resolve lazily and are
    injectable for hermetic tests (`*_fn` kwargs).
  * Idempotent: member ids already present in the ledger's
    cluster_created/member_added events are skipped, so a second `--execute`
    appends ZERO events (test-pinned).
  * D-075 R4 (owner-ratified): fresh items are matched against EXISTING
    open (not-killed) ledger clusters — same prefilter layers, same
    thresholds as intra-batch — BEFORE any new cluster is minted; a refill
    near-dup member_adds to the original instead of founding a duplicate
    (the 08-18 case: 3 duplicate clusters minted next to their open
    originals). Killed clusters are never matched — re-entry into a killed
    niche stays accept_candidate's evidence-keyed job.
  * Missing input files RAISE (rule 7 — a missing corpus is not a silent
    empty migration); an out-of-enum rung from derive_level RAISES (rule 4).
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any, Callable

from orchestrator import runtime
from workers.idea_ledger import (
    kill_reason_from_redteam,
    reduce_events,
    reopening_condition,
)
from workers.mine_paper_gap import (
    JACCARD_DUP,
    TAU_DUP,
    _append_jsonl,
    _cosine,
    _embed_texts,
    _lexical_overlap,
    _read_jsonl,
    _utcnow,
)
from workers.retrieval_relevance import _tokenize

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOOP_MEMORY = REPO_ROOT / "memory" / "loop_memory.jsonl"
DEFAULT_SURFACED = REPO_ROOT / "memory" / "surfaced_findings.jsonl"
DEFAULT_FEEDBACK = REPO_ROOT / "memory" / "loop_feedback.jsonl"
DEFAULT_LEDGER = REPO_ROOT / "memory" / "idea_ledger.jsonl"
DEFAULT_ARCHIVE = REPO_ROOT / "memory" / "idea_archive.jsonl"

LEVELS = ("L0", "L1", "L2", "L3", "L4", "L5")
_MEMBER_EVENTS = ("cluster_created", "member_added")
_NEAR_DUP_LAYERS = ("lexical_jaccard", "cosine_tau_dup")
_EXCERPT = 240


# ── Lazy seams for parallel-built contract modules (injectable in tests). ────
def _default_derive_level() -> Callable:
    from workers.evidence_ladder import derive_level
    return derive_level


def _default_extract_claim() -> Callable:
    from workers.claim_extract import extract_claim
    return extract_claim


def _default_append_event() -> Callable:
    from workers.idea_ledger import append_event
    return append_event


def _is_leaked_blob(text: str) -> bool:
    """True when a claim/hypothesis surface is a leaked JSON blob (the model
    emitted its raw structured scratchpad instead of prose). Full parses count;
    so does a truncated blob that opens like a JSON object."""
    t = (text or "").strip()
    if not t.startswith(("{", "[")):
        return False
    try:
        parsed = json.loads(t)
        return isinstance(parsed, (dict, list))
    except json.JSONDecodeError:
        return bool(re.match(r'^[{\[]\s*"', t))


def _repaired_surface(claim: dict[str, Any], iteration_id: str) -> str:
    parts = [claim.get(k) for k in ("problem", "mechanism", "predicted_effect")]
    parts = [p.strip() for p in parts if isinstance(p, str) and p.strip()]
    if not parts:
        raise ValueError(
            f"consolidate_memory: claim_extract returned an empty claim for "
            f"{iteration_id} — cannot repair a leaked blob with nothing (rule 4)."
        )
    return " — ".join(parts)


def _build_items(
    loop_rows: list[dict],
    surfaced_rows: list[dict],
    extract_claim_fn: Callable,
) -> tuple[list[dict], list[str]]:
    """Flatten both corpora into cluster items {id, kind, row, source_row,
    text}. Leaked-blob claims are repaired via claim_extract (counted)."""
    by_iter = {r["iteration_id"]: r for r in loop_rows if r.get("iteration_id")}
    repaired: list[str] = []
    items: list[dict] = []

    for row in loop_rows:
        iid = row.get("iteration_id")
        if not isinstance(iid, str) or not iid:
            raise ValueError("consolidate_memory: loop_memory row without an "
                             "iteration_id — refusing to migrate blind (rule 4).")
        hyp = row.get("hypothesis") if isinstance(row.get("hypothesis"), dict) else {}
        text = hyp.get("text") if isinstance(hyp.get("text"), str) else ""
        topic = ""
        if isinstance(row.get("seed"), dict):
            topic = row["seed"].get("topic") or ""
        if text.strip() and _is_leaked_blob(text):
            text = _repaired_surface(extract_claim_fn(row), iid)
            repaired.append(iid)
        if not text.strip():
            text = topic
        if not text.strip():
            raise ValueError(f"consolidate_memory: {iid} has no hypothesis text "
                             f"and no seed topic — cannot cluster an empty surface.")
        items.append({"id": iid, "kind": "loop", "row": row, "source_row": row,
                      "text": (text + " " + topic).strip()})

    for row in surfaced_rows:
        fid = row.get("finding_id")
        if not isinstance(fid, str) or not fid:
            raise ValueError("consolidate_memory: surfaced_findings row without "
                             "a finding_id — refusing to migrate blind (rule 4).")
        src_id = row.get("source_iteration_id")
        src = by_iter.get(src_id) if isinstance(src_id, str) else None
        text = row.get("claim") if isinstance(row.get("claim"), str) else ""
        if not text.strip():
            text = row.get("title") if isinstance(row.get("title"), str) else ""
        if text.strip() and _is_leaked_blob(text):
            if src is None:
                raise ValueError(
                    f"consolidate_memory: {fid} has a leaked-blob claim but no "
                    f"resolvable source iteration ({src_id!r}) to repair from.")
            text = _repaired_surface(extract_claim_fn(src), fid)
            repaired.append(fid)
        if not text.strip():
            raise ValueError(f"consolidate_memory: {fid} has neither claim nor "
                             f"title — cannot cluster an empty surface.")
        items.append({"id": fid, "kind": "surfaced", "row": row,
                      "source_row": src, "source_id": src_id, "text": text.strip()})
    return items, repaired


def _match_cluster(item: dict, clusters: list[dict]) -> tuple[dict | None, dict | None]:
    """First cluster the item near-dups into, via the load-bearing lexical
    layer then the near-identical-only cosine layer. None = founds its own."""
    for cl in clusters:
        lex = max((_lexical_overlap(item["tokens"], m["text"]) for m in cl["members"]),
                  default=0.0)
        if lex >= JACCARD_DUP:
            return cl, {"layer": "lexical_jaccard", "score": round(lex, 4)}
        cos = max((_cosine(item.get("vector"), m.get("vector")) for m in cl["members"]),
                  default=0.0)
        if cos >= TAU_DUP:
            return cl, {"layer": "cosine_tau_dup", "score": round(cos, 4)}
    return None, None


def _existing_open_clusters(ledger_events: list[dict],
                            all_items: list[dict]) -> list[dict]:
    """The D-075 R4 matching pool: EXISTING not-killed clusters reduced from
    the ledger, carrying every member text recoverable from the corpora
    (ledger events do not store texts; the source corpora do, and every
    ledger member id is by definition an already-processed corpus id).
    Killed clusters are EXCLUDED — a fresh dup of a killed cluster founds
    its own cluster and faces its own signals; silent member_added into a
    dead niche would bypass evidence-keyed reopening (rule 4)."""
    if not ledger_events:
        return []
    text_by_id = {i["id"]: i["text"] for i in all_items}
    pool: list[dict] = []
    for cid, c in reduce_events(ledger_events).items():
        if c["status"] == "killed":
            continue
        members = [{"text": text_by_id[m]} for m in c["members"] if m in text_by_id]
        if members:
            pool.append({"cluster_id": cid, "existing": True, "members": members})
    return pool


def _cluster_items(items: list[dict], existing: list[dict] | None = None) -> list[dict]:
    """Greedy clustering in corpus order. EXISTING open ledger clusters (when
    supplied) sit FIRST in the match order — D-075 R4: a fresh near-dup of an
    already-minted cluster joins it instead of founding a duplicate, through
    the SAME layers at the SAME thresholds as intra-batch. A surfaced finding
    attaches to its source iteration's cluster directly (same evidence, not a
    near-dup); everything else goes through the dedup layers. Returns the
    existing clusters (with any fresh joiners appended) plus the new ones."""
    existing = existing or []
    ex_members = [m for cl in existing for m in cl["members"]]
    # One embed batch for fresh + existing texts: same vector space per call.
    vecs = _embed_texts([i["text"] for i in items] + [m["text"] for m in ex_members])
    for item, vec in zip(items, vecs[:len(items)]):
        item["vector"] = vec
        item["tokens"] = _tokenize(item["text"])
    for m, vec in zip(ex_members, vecs[len(items):]):
        m["vector"] = vec
    clusters: list[dict] = list(existing)
    member_cluster: dict[str, dict] = {}
    for item in items:
        target, how = None, None
        src_id = item.get("source_id")
        if item["kind"] == "surfaced" and src_id in member_cluster:
            target, how = member_cluster[src_id], {"layer": "source_iteration", "score": None}
        else:
            target, how = _match_cluster(item, clusters)
        if target is None:
            target = {"cluster_id": f"cl-{item['id']}", "members": []}
            clusters.append(target)
            how = {"layer": "founder", "score": None}
        item["joined_via"] = how
        target["members"].append(item)
        member_cluster[item["id"]] = target
    return clusters


def _derive_member_level(item: dict, feedback_by_iter: dict, cluster: dict,
                         derive_level_fn: Callable) -> dict:
    """Rung for one member. Loop rows carry no adversarial block themselves —
    a surfaced sibling for the same iteration supplies it; a surfaced item
    without a resolvable source derives from its own row."""
    row = item["source_row"] if item["source_row"] is not None else item["row"]
    iid = row.get("iteration_id") or item["id"]
    adv = None
    for m in cluster["members"]:
        if m["kind"] == "surfaced" and m.get("source_id") == iid \
                and isinstance(m["row"].get("adversarial"), dict):
            adv = m["row"]["adversarial"]
            break
    if adv is None and isinstance(item["row"].get("adversarial"), dict):
        adv = item["row"]["adversarial"]
    derived = derive_level_fn(row, feedback_by_iter.get(iid), adv, [])
    level = derived.get("level")
    if level not in LEVELS:
        raise ValueError(f"consolidate_memory: derive_level returned "
                         f"{level!r} for {item['id']} — not in {LEVELS} (rule 4).")
    return derived


def _accept_reason(via: dict) -> str:
    return via["layer"] + (f":{via['score']:.3f}"
                           if isinstance(via.get("score"), float) else "")


def _plan_existing_merges(clusters: list[dict], ts: str) -> tuple[list[dict], list[dict], list[dict]]:
    """member_added events + archive rows for fresh items that matched an
    EXISTING open ledger cluster (D-075 R4). NEVER a cluster_created, and no
    kill / elite / rung re-derivation — the cluster's standing state is the
    ledger's; this only records the new member. Near-dup joiners archive with
    the same reason as intra-batch near-dups (their text lives in the archive,
    not the ledger); source-attached surfaced members do not archive."""
    events: list[dict] = []
    archive: list[dict] = []
    merges: list[dict] = []
    for cl in clusters:
        for m in cl["members"]:
            if "id" not in m:
                continue  # pre-existing ledger member (text/vector only)
            via = m["joined_via"]
            events.append({"event_type": "member_added", "ts": ts,
                           "cluster_id": cl["cluster_id"], "member_id": m["id"],
                           "accept_reason": _accept_reason(via)})
            if via["layer"] in _NEAR_DUP_LAYERS:
                archive.append({"archived_at": ts, "cluster_id": cl["cluster_id"],
                                "member_id": m["id"], "kind": m["kind"],
                                "text": m["text"], "joined_via": via,
                                "reason": "near_dup_non_elite"})
            merges.append({"cluster_id": cl["cluster_id"], "member_id": m["id"],
                           "layer": via["layer"], "score": via.get("score")})
    return events, archive, merges


def _cluster_verdicts(elite_row: dict) -> tuple[str | None, str | None]:
    rt = elite_row.get("redteam") if isinstance(elite_row.get("redteam"), dict) else {}
    nv = elite_row.get("novelty") if isinstance(elite_row.get("novelty"), dict) else {}
    nclass = nv.get("class") or elite_row.get("novelty_class")
    return rt.get("verdict"), nclass


def _plan_cluster(cluster: dict, feedback_by_iter: dict, derive_level_fn: Callable,
                  ts: str) -> tuple[list[dict], list[dict], dict]:
    """Events + archive rows + facts for one cluster. Elite = highest-rung
    member (ties -> corpus order). Kill/niche is programmatic from the elite's
    signals: redteam fatal_flaw kills; novelty rediscovery seeds a paper niche."""
    for item in cluster["members"]:
        item["derived"] = _derive_member_level(item, feedback_by_iter, cluster,
                                               derive_level_fn)
    elite = max(cluster["members"], key=lambda m: LEVELS.index(m["derived"]["level"]))
    level = elite["derived"]["level"]
    cid = cluster["cluster_id"]
    founder, rest = cluster["members"][0], cluster["members"][1:]

    # Events use the idea_ledger schema shapes verbatim (schema/idea_ledger
    # .schema.json, additionalProperties:false) so the real write path —
    # idea_ledger.append_event, which validates — accepts them. Member texts
    # live in the archive rows, not the ledger.
    events = [{"event_type": "cluster_created", "ts": ts, "cluster_id": cid,
               "member_id": founder["id"], "origin": "consolidation",
               **({"iteration_id": founder["id"]} if founder["kind"] == "loop" else {})}]
    archive: list[dict] = []
    for m in rest:
        events.append({"event_type": "member_added", "ts": ts, "cluster_id": cid,
                       "member_id": m["id"],
                       **({"as_elite": True} if m is elite else {}),
                       "accept_reason": _accept_reason(m["joined_via"])})
    for m in cluster["members"]:
        if m is not elite and m["joined_via"]["layer"] in _NEAR_DUP_LAYERS:
            archive.append({"archived_at": ts, "cluster_id": cid,
                            "member_id": m["id"], "kind": m["kind"],
                            "text": m["text"], "joined_via": m["joined_via"],
                            "reason": "near_dup_non_elite"})
    if level != "L0":
        events.append({"event_type": "evidence_level_changed", "ts": ts,
                       "cluster_id": cid, "evidence_level": level,
                       "basis": f"evidence_ladder:{elite['id']}"})

    elite_row = elite["source_row"] if elite["source_row"] is not None else elite["row"]
    rt_verdict, nclass = _cluster_verdicts(elite_row)
    status, niche = "open", False
    if rt_verdict == "fatal_flaw":
        status = "killed"
        events.append({"event_type": "cluster_killed", "ts": ts, "cluster_id": cid,
                       "kill_reason": kill_reason_from_redteam(elite_row),
                       "reopening_condition": reopening_condition(
                           "redteam_proceed_on_revision")})
    elif nclass == "rediscovery":
        # A rediscovery closes THIS cluster with the paper-prior kill code
        # (niche_seeded creates a NEW paper niche and would collide with the
        # cluster_created above — the reducer forbids duplicate creates).
        niche = True
        iid = elite_row.get("iteration_id") or elite["id"]
        rationale = (elite_row.get("novelty") or {}).get("rationale") or ""
        events.append({"event_type": "cluster_killed", "ts": ts, "cluster_id": cid,
                       "kill_reason": {"code": "paper_prior_exists",
                                       "evidence_key": f"iteration:{iid}:novelty",
                                       "detail": rationale[:_EXCERPT]
                                                 or f"novelty class rediscovery on {iid}"},
                       "reopening_condition": reopening_condition("articulated_delta")})
    return events, archive, {"cluster_id": cid, "level": level, "status": status,
                             "niche": niche, "elite_id": elite["id"],
                             "size": len(cluster["members"])}


def _print_summary(report: dict) -> None:
    mode = ("DRY-RUN — nothing written; re-run with --execute"
            if report["dry_run"] else "EXECUTE — events appended")
    rungs = " ".join(f"{lvl}={report['rungs'].get(lvl, 0)}" for lvl in LEVELS)
    lines = [
        f"== consolidate_memory [{mode}] ==",
        f"  rows                loop={report['loop_rows']} "
        f"surfaced={report['surfaced_rows']} "
        f"already_processed={report['skipped_already_processed']}",
        f"  clusters            {report['clusters']}",
        f"  merged into existing {report['merged_into_existing']}",
        f"  rungs               {rungs}",
        f"  killed (fatal_flaw) {report['killed']}",
        f"  paper niches        {report['paper_niches']}",
        f"  archive rows        "
        f"{report['archived'] if not report['dry_run'] else report['archive_planned']}",
        f"  claims repaired     {report['claims_repaired']}",
        f"  events {'appended' if not report['dry_run'] else 'planned '}     "
        f"{report['events_appended'] if not report['dry_run'] else report['events_planned']}",
    ]
    print("\n".join(lines))


def consolidate(
    *,
    loop_memory_path: str | Path | None = None,
    surfaced_path: str | Path | None = None,
    feedback_path: str | Path | None = None,
    ledger_path: str | Path | None = None,
    archive_path: str | Path | None = None,
    execute: bool = False,
    derive_level_fn: Callable | None = None,
    extract_claim_fn: Callable | None = None,
    append_event_fn: Callable | None = None,
) -> dict[str, Any]:
    """Run the migration. Dry-run (default) computes and prints the human-gate
    summary and writes NOTHING. `execute=True` appends idea-ledger events +
    archive rows; source corpora are never modified. Idempotent by member id."""
    t0 = time.perf_counter()
    loop_memory_path = Path(loop_memory_path or DEFAULT_LOOP_MEMORY)
    surfaced_path = Path(surfaced_path or DEFAULT_SURFACED)
    feedback_path = Path(feedback_path or DEFAULT_FEEDBACK)
    ledger_path = Path(ledger_path or DEFAULT_LEDGER)
    archive_path = Path(archive_path or DEFAULT_ARCHIVE)
    derive_level_fn = derive_level_fn or _default_derive_level()
    extract_claim_fn = extract_claim_fn or _default_extract_claim()
    append_event_fn = append_event_fn or _default_append_event()

    for p, name in ((loop_memory_path, "loop_memory"), (surfaced_path, "surfaced_findings")):
        if not p.exists():
            raise FileNotFoundError(
                f"consolidate_memory: {name} missing at {p} — cannot migrate an "
                f"absent corpus (rule 7: no silent empty migration).")

    loop_rows = _read_jsonl(loop_memory_path)
    surfaced_rows = _read_jsonl(surfaced_path)
    feedback_by_iter = {r["iteration_id"]: r for r in _read_jsonl(feedback_path)
                        if isinstance(r.get("iteration_id"), str)}

    items, repaired = _build_items(loop_rows, surfaced_rows, extract_claim_fn)
    ledger_events = _read_jsonl(ledger_path)
    processed = {e.get("member_id") for e in ledger_events
                 if e.get("event_type") in _MEMBER_EVENTS}
    fresh = [i for i in items if i["id"] not in processed]
    skipped = len(items) - len(fresh)

    # D-075 R4: existing open clusters are matched BEFORE any minting.
    pool = _existing_open_clusters(ledger_events, items) if fresh else []

    ts = _utcnow()
    new_events: list[dict] = []
    archive: list[dict] = []
    facts: list[dict] = []
    existing_hit: list[dict] = []
    for cluster in _cluster_items(fresh, existing=pool):
        if cluster.get("existing"):
            if any("id" in m for m in cluster["members"]):
                existing_hit.append(cluster)
            continue
        ev, ar, fact = _plan_cluster(cluster, feedback_by_iter, derive_level_fn, ts)
        new_events.extend(ev)
        archive.extend(ar)
        facts.append(fact)
    merge_events, merge_archive, merges = _plan_existing_merges(existing_hit, ts)
    events = merge_events + new_events
    archive = merge_archive + archive

    appended = 0
    if execute:
        for ev in events:
            append_event_fn(ledger_path, ev)
            appended += 1
        for row in archive:
            _append_jsonl(archive_path, row)

    rungs: dict[str, int] = {}
    for f in facts:
        rungs[f["level"]] = rungs.get(f["level"], 0) + 1
    report = {
        "dry_run": not execute,
        "loop_rows": len(loop_rows),
        "surfaced_rows": len(surfaced_rows),
        "skipped_already_processed": skipped,
        "clusters": len(facts),
        "merged_into_existing": len(merges),
        "existing_merges": merges,
        "rungs": rungs,
        "killed": sum(1 for f in facts if f["status"] == "killed"),
        "paper_niches": sum(1 for f in facts if f["niche"]),
        "archived": len(archive) if execute else 0,
        "archive_planned": len(archive),
        "claims_repaired": len(repaired),
        "repaired_ids": repaired,
        "events_planned": len(events),
        "events_appended": appended,
        "cluster_facts": facts,
    }
    _print_summary(report)
    runtime.append_run_log({
        "task_id": "consolidate_memory",
        "status": "passed",
        "observable_actual": f"mode={'execute' if execute else 'dry_run'} "
                             f"clusters={report['clusters']} "
                             f"merged={report['merged_into_existing']} "
                             f"killed={report['killed']} "
                             f"events_appended={appended} skipped={skipped}",
        "observable_expected": "idempotent append-only migration; dry-run writes nothing",
        "duration_ms": round((time.perf_counter() - t0) * 1000.0, 3),
    })
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="One-shot idempotent consolidation of loop_memory + "
                    "surfaced_findings into idea-ledger events. DRY-RUN by "
                    "default; the summary is the G2 human-gate artifact.")
    ap.add_argument("--execute", action="store_true",
                    help="write events + archive rows (default: dry-run, no writes)")
    ap.add_argument("--loop-memory", default=None)
    ap.add_argument("--surfaced", default=None)
    ap.add_argument("--feedback", default=None)
    ap.add_argument("--ledger", default=None)
    ap.add_argument("--archive", default=None)
    args = ap.parse_args(argv)
    consolidate(loop_memory_path=args.loop_memory, surfaced_path=args.surfaced,
                feedback_path=args.feedback, ledger_path=args.ledger,
                archive_path=args.archive, execute=args.execute)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
