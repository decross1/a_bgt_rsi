"""Worker: generation-time adopt-or-reject vs killed clusters + paper niches
(P3 A6, LOOP_V1).

After hypothesize, the orchestrator asks: has this idea already been KILLED, or
is it a pre-closed PAPER NICHE (a known published result)? A hit does not ban
the hypothesis — it demands an articulated delta (`delta_required=True`); the
caller routes a no-delta rediscovery back through the existing
`_hypothesize_retry` path with the kill_reason as critique.

Matching reuses the mine_paper_gap prefilter layers by IMPORT (never
reimplemented — LOOP_V1 P3): the LOAD-BEARING lexical-Jaccard layer
(`JACCARD_DUP`, catches reworded restatements) OR the high near-identical
cosine layer (`TAU_DUP`). Thresholds are the calibrated constants from
mine_paper_gap — one dedup vocabulary across the apparatus.

Pure given `ledger_state` (the idea_ledger reduction, dict keyed by
cluster_id): no file I/O, no run-log side effects — the orchestrator step owns
logging. Embeddings go through `mine_paper_gap._embed_texts` (MOCK_LLM ->
deterministic stubs; tests monkeypatch that one seam).

Eligibility: only clusters with status=="killed" or origin=="paper_niche" are
match targets. Open/surfaced clusters are live ideas — colliding with them is
the novelty gate's job downstream, not a generation-time rejection.
"""
from __future__ import annotations

from typing import Any

from workers import mine_paper_gap as _mpg
from workers.retrieval_relevance import _tokenize

# Calibrated constants imported for reference/monkeypatch visibility; the
# thresholds applied are always mine_paper_gap's current values (read at call
# time via the module attr so a recalibration there propagates here).
JACCARD_DUP = _mpg.JACCARD_DUP
TAU_DUP = _mpg.TAU_DUP


def _cluster_texts(cluster: dict[str, Any]) -> list[str]:
    """Collect the matchable surface strings of a cluster: the elite claim's
    problem/mechanism/predicted_effect (nested under `claim` or inline) plus
    any topic/title/text field. Tolerant of shape drift; unknown -> []."""
    texts: list[str] = []
    elite = cluster.get("elite")
    records: list[dict[str, Any]] = []
    if isinstance(elite, dict):
        records.append(elite)
        if isinstance(elite.get("claim"), dict):
            records.append(elite["claim"])
    records.append(cluster)
    for rec in records:
        for key in ("problem", "mechanism", "predicted_effect", "topic", "title", "text"):
            val = rec.get(key)
            if isinstance(val, str) and val.strip():
                texts.append(val.strip())
    return texts


def _eligible(cluster: dict[str, Any]) -> str | None:
    """Return the match-status a hit on this cluster would carry, or None if
    the cluster is not a rejection target (open/surfaced live ideas)."""
    if not isinstance(cluster, dict):
        return None
    # The reducer stamps paper niches with origin "paper_seed"
    # (workers/idea_ledger.py _new_cluster via niche_seeded) — the old
    # "paper_niche" literal matched nothing (2026-08-14 review).
    if cluster.get("origin") in ("paper_seed", "paper_niche"):
        return "paper_niche"
    if cluster.get("status") == "killed":
        return "killed"
    return None


def match(hypothesis_text: str, ledger_state: dict) -> dict[str, Any]:
    """Match a hypothesis against killed clusters + paper niches.

    Returns {matched_cluster_id, kill_reason, status: "none"|"killed"|
    "paper_niche", delta_required} plus a diagnostic `match_detail` (basis,
    score, threshold, per contract-extra observability). A match on EITHER
    layer (lexical >= JACCARD_DUP, cosine >= TAU_DUP) counts; the strongest
    eligible cluster wins (deterministic cluster_id tie-break). Raises
    ValueError on an empty hypothesis — an upstream failure, never a silent
    "no match" (rule 7).
    """
    if not isinstance(hypothesis_text, str) or not hypothesis_text.strip():
        raise ValueError(
            "failure_match.match: empty hypothesis_text — refusing to report "
            "'none' for a blank hypothesis (no silent fallback)."
        )
    hyp = hypothesis_text.strip()
    hyp_tokens = _tokenize(hyp)

    targets: list[tuple[str, str, list[str]]] = []  # (cluster_id, status, texts)
    for cid in sorted(k for k in ledger_state if isinstance(k, str)):
        cluster = ledger_state[cid]
        status = _eligible(cluster)
        if status is None:
            continue
        texts = _cluster_texts(cluster)
        if texts:
            targets.append((cid, status, texts))

    no_match: dict[str, Any] = {
        "matched_cluster_id": None, "kill_reason": None,
        "status": "none", "delta_required": False, "match_detail": None,
    }
    if not targets:
        return no_match

    # One embed call for the hypothesis + every target surface (MOCK_LLM-safe).
    surfaces = [" ".join(texts) for _, _, texts in targets]
    vecs = _mpg._embed_texts([hyp] + surfaces)
    hyp_vec, target_vecs = vecs[0], vecs[1:]

    best: dict[str, Any] | None = None
    for (cid, status, texts), tvec in zip(targets, target_vecs):
        lex = max((_mpg._lexical_overlap(hyp_tokens, t) for t in texts), default=0.0)
        cos = _mpg._cosine(hyp_vec, tvec)
        if lex >= _mpg.JACCARD_DUP:
            basis, score, threshold = "lexical_jaccard", lex, _mpg.JACCARD_DUP
        elif cos >= _mpg.TAU_DUP:
            basis, score, threshold = "cosine_tau_dup", cos, _mpg.TAU_DUP
        else:
            continue
        # Cross-base ranking uses the EXCESS over the base's own threshold —
        # raw scores are incommensurable (lexical lives near 0.6, cosine near
        # 0.97; comparing them raw let a marginal cosine hit outrank a
        # decisive lexical one — 2026-08-14 review).
        excess = score - threshold
        if best is None or excess > best["excess"]:  # ties keep first (sorted cid)
            best = {"cluster_id": cid, "status": status, "basis": basis,
                    "score": round(score, 4), "threshold": threshold,
                    "excess": excess}

    if best is None:
        return no_match
    cluster = ledger_state[best["cluster_id"]]
    kill_reason = cluster.get("kill_reason") if isinstance(cluster.get("kill_reason"), dict) else None
    return {
        "matched_cluster_id": best["cluster_id"],
        "kill_reason": kill_reason,
        "status": best["status"],
        "delta_required": True,
        "match_detail": {"basis": best["basis"], "score": best["score"],
                         "threshold": best["threshold"]},
    }
