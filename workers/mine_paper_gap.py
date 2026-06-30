"""Worker: mine recent arXiv papers for an in-domain *topic gap* — the P4
dedup-keystone v0 (design: docs/p4_topic_autogen_design.md, Decisions 2026-06-30).

NON-GENERATIVE: a proposed topic is an EXTRACTED arXiv title, never a Gemma
generation (decision #4 — defuses the same-model echo; the trusted novelty gate
stays downstream on the *hypothesis*). This worker SELECTS; never scores novelty.

The payload is the **dedup**, not the gap ranking. The falsifier proved a single
cosine threshold does NOT separate reworded near-dups from distinct findings
(lowest intra-cluster cosine 0.875 < highest cross-distinct 0.938), so the
**lexical Jaccard layer is load-bearing**; cosine τ_dup is a HIGH (~0.97)
near-identical-only filter, a tunable constant — NOT the gate (decision #3).

`_dedup` layer order (before any emit; first hit kills, kill-layer logged):
  1 reseed             — arxiv_id already a prior seed
  2 intra_batch_cosine — within ε of an already-kept batch survivor (greedy)
  3 lexical_jaccard    — overlap >= JACCARD_DUP vs prior corpus + kept (LOAD-BEARING)
  4 cosine_tau_dup     — cosine >= τ_dup vs prior corpus (near-identical only)
  5 density_saturated  — nearest backlog region is a saturated cluster
  6 off_domain         — on-domain cap via domain_anchor (smoke-only; decision #5/#6)
  7 pending_queue      — already queued as an unconsumed new_topic

MOCK_LLM: `_embed_texts` returns deterministic stub vectors and `anchor_cosine`
returns None (cap "skipped, logged" — never a fabricated pass); a missing
loop_memory file RAISES (rule 7 — no silent empty result).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from orchestrator import chroma_query, domain_anchor, runtime
from workers.retrieval_relevance import _neighbor_overlap, _tokenize

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOOP_MEMORY = REPO_ROOT / "memory" / "loop_memory.jsonl"
DEFAULT_FOLLOWUPS = REPO_ROOT / "memory" / "finding_followups.jsonl"
DEFAULT_LEDGER = REPO_ROOT / "memory" / "topic_proposals.jsonl"
DEFAULT_EMBED_CACHE = REPO_ROOT / "run_state" / "loop_memory_embeddings.json"
PAPERS_RECENT = "papers_recent"

# ── Tunable dedup constants (see module docstring + falsifier). ──────────────
JACCARD_DUP = 0.6      # layer 3 — THE LOAD-BEARING lexical gate
TAU_DUP = 0.97         # layer 4 — cosine, near-identical ONLY; tunable, NOT the gate
INTRA_BATCH_EPS = 0.95 # layer 2 — intra-batch greedy cosine
DENSITY_COSINE = 0.90  # layer 5 — a backlog neighbor counts toward saturation at/above this
SATURATION_COUNT = 4   # layer 5 — region with >= this many backlog neighbors is saturated
# layer 6 — on-domain cap. INERT until the integrator smoke-calibrates against a
# varied probe set (P-009 precedent: retrieval_relevance ships ANCHOR_LOW=None);
# anchor_cosine is logged per-candidate so the smoke produces the calibration data.
ANCHOR_MIN: float | None = None


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    """Tolerant JSONL read (mirrors morning_topic._read_jsonl). Missing -> []."""
    rows: list[dict[str, Any]] = []
    p = Path(path)
    if not p.exists():
        return rows
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def _append_jsonl(path: str | Path, row: dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _mock_vector(text: str, dim: int = 24) -> list[float]:
    """Deterministic stub embedding for MOCK_LLM — stable per content, geometry
    meaningless. NEVER masquerades as a real embed."""
    h = hashlib.sha256(text.encode("utf-8")).digest()
    return [((h[i % len(h)] / 255.0) * 2.0 - 1.0) for i in range(dim)]


def _embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed strings to vectors. Real -> the cached BGE-M3 embedder (no second
    model load). MOCK_LLM -> deterministic stubs. Tests monkeypatch this seam."""
    if not texts:
        return []
    if os.environ.get("MOCK_LLM"):
        return [_mock_vector(t) for t in texts]
    embedder, _ = chroma_query._load_real_client()
    return [[float(x) for x in v] for v in embedder(list(texts))]


def _cosine(a: list[float] | None, b: list[float] | None) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _lexical_overlap(cand_tokens: set[str], ref_text: str) -> float:
    """Directional lexical overlap (fraction of candidate tokens present in the
    reference), via the reused retrieval_relevance._neighbor_overlap. GT
    stopwords (nash/equilibrium/game/games) are already stripped by _tokenize."""
    if not cand_tokens or not ref_text:
        return 0.0
    return _neighbor_overlap(cand_tokens, {"chunk_text": ref_text, "title": ""})


def _load_prior_hyp_vectors(
    loop_memory_path: str | Path,
    *,
    cache_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Embed the prior-hypothesis corpus (hypothesis.text + seed.topic) from
    loop_memory, content-hash cached so WARM runs re-embed nothing. RAISES
    FileNotFoundError when loop_memory is missing (rule 7: a missing record is
    NOT a silent empty corpus that would fabricate every gap as maximal)."""
    p = Path(loop_memory_path)
    if not p.exists():
        raise FileNotFoundError(
            f"mine_paper_gap: loop_memory missing at {p} — cannot mine gaps "
            f"against an absent prior corpus (rule 7: no silent empty result)."
        )
    cp = Path(cache_path) if cache_path is not None else DEFAULT_EMBED_CACHE
    cache: dict[str, list[float]] = {}
    if cp.exists():
        try:
            cache = json.loads(cp.read_text())
        except (OSError, json.JSONDecodeError):
            cache = {}

    priors: list[dict[str, Any]] = []
    pending: list[tuple[str, str]] = []  # (surface, hash) needing an embed
    seen: set[str] = set()
    for row in _read_jsonl(p):
        hyp = row.get("hypothesis")
        text = hyp.get("text") if isinstance(hyp, dict) else None
        seed = row.get("seed") if isinstance(row.get("seed"), dict) else {}
        topic = seed.get("topic") if isinstance(seed.get("topic"), str) else ""
        if not (isinstance(text, str) and text.strip()):
            text = topic
        if not (isinstance(text, str) and text.strip()):
            continue
        surface = (text + " " + topic).strip()
        h = chroma_query._content_hash(surface)
        if h in seen:
            continue
        seen.add(h)
        priors.append({"text": surface, "hash": h, "tokens": _tokenize(surface), "vector": None})
        if h not in cache:
            pending.append((surface, h))

    if pending:  # warm runs leave `pending` empty -> no re-embed, no cache rewrite
        for (surface, h), vec in zip(pending, _embed_texts([s for s, _ in pending])):
            cache[h] = vec
        cp.parent.mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps(cache))
    for pr in priors:
        pr["vector"] = cache.get(pr["hash"])
    return priors


def _sample_recent_papers(n: int, *, collection_name: str = PAPERS_RECENT) -> list[dict[str, Any]]:
    """Up to n most-recent papers (title, abstract, arxiv_id, category, date)
    from papers_recent. Consistent with morning_topic's metadata-read seam, but
    also pulls `documents` (the embedded abstract). An unreachable store
    propagates (rule 7); a reachable-but-empty store returns []."""
    coll = chroma_query._get_collection(collection_name)
    got = coll.get(include=["metadatas", "documents"])
    metas = got.get("metadatas") or []
    docs = got.get("documents") or []
    papers: list[dict[str, Any]] = []
    for meta, doc in zip(metas, docs):
        if not isinstance(meta, dict):
            continue
        aid, title = meta.get("arxiv_id"), meta.get("title")
        if not (isinstance(aid, str) and aid and isinstance(title, str) and title.strip()):
            continue
        papers.append({
            "arxiv_id": str(aid),
            "title": title.strip(),
            "abstract": (doc or "").strip() if isinstance(doc, str) else "",
            "category": meta.get("category") or "",
            "publication_date": str(meta.get("publication_date") or ""),
        })
    papers.sort(key=lambda x: (x["publication_date"], x["arxiv_id"]))
    return papers[-max(int(n), 0):][::-1]  # newest first, up to n


def _gap_scores(candidates: list[dict], priors: list[dict]) -> list[dict]:
    """Annotate gap = 1 - max cosine(candidate, prior). A SELECTION heuristic
    by distance — never a novelty judgment (decision #4). Empty prior corpus ->
    gap 1.0 for all (everything is maximally far)."""
    pvecs = [p["vector"] for p in priors if p.get("vector")]
    for c in candidates:
        cv = c.get("vector")
        mx = max((_cosine(cv, pv) for pv in pvecs), default=0.0) if cv else 0.0
        c["nearest_prior_cos"] = round(mx, 4)
        c["gap"] = round(1.0 - mx, 4)
    return candidates


def _classify(c: dict, kept: list[dict], priors: list[dict],
              prior_seed_ids: set[str], pend_ids: set[str],
              pend_texts: list[str]) -> dict[str, Any]:
    """Run the 7-layer dedup ladder; return the FIRST kill-layer (None =
    survives) with its margin + detail. Reads/sets c['anchor_cosine']."""
    aid, ctoks, cvec = c["arxiv_id"], c["tokens"], c.get("vector")
    # 1 — exact re-seed skip
    if aid and aid in prior_seed_ids:
        return {"kill_layer": "reseed", "margin": None,
                "detail": f"arxiv_id {aid} is already a prior seed"}
    # 2 — intra-batch greedy cluster suppression (vs already-kept survivors)
    best_batch = max((_cosine(cvec, k["vector"]) for k in kept if k.get("vector")), default=0.0)
    if cvec and kept and best_batch >= INTRA_BATCH_EPS:
        return {"kill_layer": "intra_batch_cosine", "margin": round(best_batch - INTRA_BATCH_EPS, 4),
                "detail": f"cosine {best_batch:.3f} >= eps {INTRA_BATCH_EPS} to a kept batch survivor"}
    # 3 — lexical Jaccard vs prior corpus + kept survivors — THE LOAD-BEARING layer
    lrefs = [p["text"] for p in priors] + [k["surface"] for k in kept]
    lex = max((_lexical_overlap(ctoks, rt) for rt in lrefs), default=0.0)
    c["lexical_max"] = round(lex, 4)
    if lex >= JACCARD_DUP:
        return {"kill_layer": "lexical_jaccard", "margin": round(lex - JACCARD_DUP, 4),
                "detail": f"lexical overlap {lex:.3f} >= {JACCARD_DUP} (reworded near-dup)"}
    # 4 — candidate-vs-corpus cosine >= tau_dup (HIGH; near-identical only; tunable, NOT the gate)
    best_prior = max((_cosine(cvec, p["vector"]) for p in priors if p.get("vector")), default=0.0)
    if cvec and best_prior >= TAU_DUP:
        return {"kill_layer": "cosine_tau_dup", "margin": round(best_prior - TAU_DUP, 4),
                "detail": f"cosine {best_prior:.3f} >= tau_dup {TAU_DUP} (near-identical restatement)"}
    # 5 — density-aware target exclusion (refuse to target a saturated cluster)
    dense = sum(1 for p in priors if p.get("vector") and _cosine(cvec, p["vector"]) >= DENSITY_COSINE)
    if cvec and dense >= SATURATION_COUNT:
        return {"kill_layer": "density_saturated", "margin": dense,
                "detail": f"{dense} backlog neighbors >= {DENSITY_COSINE} cosine (saturated cluster)"}
    # 6 — on-domain cap (decision #5/#6). None under MOCK_LLM/no-anchor -> skipped + logged.
    acos = domain_anchor.anchor_cosine(c["title"])
    c["anchor_cosine"] = acos
    if acos is None:
        c["anchor_note"] = "anchor_gate_skipped (anchor_cosine None — MOCK_LLM or anchor unavailable)"
    elif ANCHOR_MIN is not None and acos < ANCHOR_MIN:
        return {"kill_layer": "off_domain", "margin": round(acos - ANCHOR_MIN, 4),
                "detail": f"anchor cosine {acos:.3f} < {ANCHOR_MIN} (a gap, but not in-domain)"}
    # 7 — pending-queue dedup vs unconsumed new_topic rows
    if aid and aid in pend_ids:
        return {"kill_layer": "pending_queue", "margin": None,
                "detail": f"arxiv_id {aid} already queued as a new_topic"}
    plex = max((_lexical_overlap(ctoks, t) for t in pend_texts), default=0.0)
    if plex >= JACCARD_DUP:
        return {"kill_layer": "pending_queue", "margin": round(plex - JACCARD_DUP, 4),
                "detail": f"topic overlaps a queued new_topic ({plex:.3f} >= {JACCARD_DUP})"}
    return {"kill_layer": None, "margin": round(lex, 4), "detail": "survived all dedup layers"}


def _dedup(candidates: list[dict], priors: list[dict], *,
           prior_seed_ids: set[str], pending: list[dict]) -> tuple[list[dict], list[dict], dict[str, int]]:
    """THE KEYSTONE. Apply the 7-layer ladder to ranked candidates; return
    (survivors, ledger_rows, dropped_by_layer). Every candidate (kept AND
    dropped) gets a ledger row with its kill-layer + margin."""
    pend_ids = {t.get("arxiv_id") for t in pending if isinstance(t.get("arxiv_id"), str)}
    pend_texts = [t["new_topic"] for t in pending if isinstance(t.get("new_topic"), str)]
    kept: list[dict] = []
    ledger: list[dict] = []
    dropped_by_layer: dict[str, int] = {}
    for c in candidates:
        d = _classify(c, kept, priors, prior_seed_ids, pend_ids, pend_texts)
        ledger.append({
            "ts": _utcnow(), "arxiv_id": c.get("arxiv_id"), "title": c.get("title"),
            "gap": c.get("gap"), "nearest_prior_cos": c.get("nearest_prior_cos"),
            "lexical_max": c.get("lexical_max"), "anchor_cosine": c.get("anchor_cosine"),
            "status": "kept" if d["kill_layer"] is None else "dropped",
            "kill_layer": d["kill_layer"], "margin": d["margin"], "detail": d["detail"],
        })
        if d["kill_layer"] is None:
            kept.append(c)
        else:
            dropped_by_layer[d["kill_layer"]] = dropped_by_layer.get(d["kill_layer"], 0) + 1
    return kept, ledger, dropped_by_layer


def mine_paper_gap(
    n: int = 20,
    max_emit: int = 2,
    *,
    loop_memory_path: str | Path | None = None,
    followups_path: str | Path | None = None,
    ledger_path: str | Path | None = None,
    cache_path: str | Path | None = None,
    collection_name: str = PAPERS_RECENT,
) -> dict[str, Any]:
    """Sample recent papers -> gap-score -> rank -> dedup -> emit up to
    max_emit survivors as `new_topic` rows tagged origin=coordinator_propose
    (ledger-only `paper_gap` provenance; decision #2). Returns
    {sampled, emitted, dropped_by_layer, emitted_topics}."""
    t0 = time.perf_counter()
    loop_memory_path = loop_memory_path or DEFAULT_LOOP_MEMORY
    followups_path = followups_path or DEFAULT_FOLLOWUPS
    ledger_path = ledger_path or DEFAULT_LEDGER

    priors = _load_prior_hyp_vectors(loop_memory_path, cache_path=cache_path)
    papers = _sample_recent_papers(n, collection_name=collection_name)
    for p, vec in zip(papers, _embed_texts([f"{p['title']} {p['abstract']}".strip() for p in papers])):
        p["surface"] = f"{p['title']} {p['abstract']}".strip()
        p["vector"] = vec
        p["tokens"] = _tokenize(p["surface"])
    _gap_scores(papers, priors)
    papers.sort(key=lambda x: x["gap"], reverse=True)  # rank: widest gap first

    pending = [r for r in _read_jsonl(followups_path) if isinstance(r.get("new_topic"), str)]
    prior_seed_ids = {r["arxiv_id"] for r in _read_jsonl(ledger_path)
                      if r.get("status") == "kept" and isinstance(r.get("arxiv_id"), str)}
    survivors, ledger, dropped_by_layer = _dedup(
        papers, priors, prior_seed_ids=prior_seed_ids, pending=pending)

    for row in ledger:
        _append_jsonl(ledger_path, row)

    emitted_topics: list[str] = []
    for c in survivors[:max(int(max_emit), 0)]:
        _append_jsonl(followups_path, {
            "new_topic": c["title"],
            "origin": "coordinator_propose",
            "provenance": "paper_gap",
            "arxiv_id": c["arxiv_id"],
            "abstract": c["abstract"],          # grounding context (decision #5)
            "gap": c["gap"],
            "nearest_prior_cos": c["nearest_prior_cos"],
            "anchor_cosine": c.get("anchor_cosine"),
            "created_at": _utcnow(),
        })
        emitted_topics.append(c["title"])

    summary = {
        "sampled": len(papers),
        "emitted": len(emitted_topics),
        "dropped_by_layer": dropped_by_layer,
        "emitted_topics": emitted_topics,
    }
    runtime.append_run_log({
        "task_id": "mine_paper_gap",
        "status": "passed",
        "observable_actual": f"sampled={summary['sampled']} emitted={summary['emitted']} "
                             f"dropped={dropped_by_layer}",
        "observable_expected": f"emit<={max_emit} after dedup",
        "duration_ms": round((time.perf_counter() - t0) * 1000.0, 3),
    })
    return summary


if __name__ == "__main__":
    # Smoke: `env -u MOCK_LLM .venv-chroma/bin/python -m workers.mine_paper_gap`
    print(json.dumps(mine_paper_gap(n=20, max_emit=2), indent=2, default=str))
