"""LOOP_V0 step 3 worker — retrieve_literature.

Given a hypothesis text, return top-K most-similar prior results from
Chroma across foundational (textbook) and live-arXiv collections.
Deterministic — does NOT call the LLM. The downstream `novelty_classify`
and `critic_loop_v0` workers consume the returned neighbors.

Wraps `orchestrator.chroma_query.query_top_k` with three additions:
- **Deduplication by content_hash** — when the same chunk happens to
  appear in multiple collections (or twice in one), we keep only the
  highest-scoring instance. The standalone query helper does NOT dedupe.
- **Worker contract shape** — Nara dispatches via the runtime, which
  passes `parent_request_id`; we thread it through.
- **Slice-2 ML-Intern escalation decision** (`result.escalation`) — a
  compound trigger evaluates whether retrieval signal is weak AND
  coverage is narrow. When both hold, downstream (eventually
  `workers.ml_intern` once Slice 2 lands) should query Semantic Scholar
  for fresh literature. Today this worker only computes + reports the
  decision; the actual escalation call site is a Slice-2 task.

The tool sees this as `retrieve_literature(hypothesis_text, k=10)`.
"""
from __future__ import annotations

from typing import Any

from orchestrator.chroma_query import query_top_k


# Slice-2 ML-Intern escalation trigger. Thresholds chosen via
# `experiments/exp003_vickrey_rediscovery/paraphrase_probe.py` — see
# `results/paraphrase_probe.md` for the 4-seed evaluation that picked
# 0.70 (over Agent β's original 0.55 spec, which fired on 0/4 seeds)
# and the compound coverage gate (which suppresses escalation on
# already-diverse retrievals like the behavioral-econ seed).
RETRIEVAL_ESCALATION_SCORE_THRESHOLD = 0.70
RETRIEVAL_ESCALATION_MIN_DISTINCT_BOOKS = 3
RETRIEVAL_ESCALATION_TOP_K = 10


def _foundational_book_name(doc_id: str, source_layer: str) -> str | None:
    """Pull the foundational book name from a chunk doc_id (e.g.,
    `camerer_bgt-chunk-71` → `camerer_bgt`). Returns None for arXiv
    chunks or any doc_id that doesn't match the `<book>-chunk-<n>`
    convention. Used by the diversity-coverage half of the escalation
    trigger; arXiv papers do not count toward the foundational-book gate
    because the trigger's purpose is to detect 'retrieval is narrow on
    foundational angles' — exactly the cue that fetching more recent
    literature (which is ML-Intern's job) might help."""
    if source_layer != "foundational":
        return None
    if "-chunk-" not in doc_id:
        return None
    return doc_id.split("-chunk-", 1)[0]


def _evaluate_escalation(neighbors: list[dict]) -> dict:
    """Compute the ML-Intern escalation decision for a deduped neighbor
    set. Trigger fires iff BOTH:
      - max(score) over top-K < RETRIEVAL_ESCALATION_SCORE_THRESHOLD
        (signal is weak — no chunk is a strong match)
      - distinct foundational books in top-K < RETRIEVAL_ESCALATION_MIN_DISTINCT_BOOKS
        (foundational-coverage is narrow — only 1-2 books contribute)

    The compound shape exists because a narrow-coverage retrieval with
    a strong top match (textbook-phrasing case) does NOT benefit from
    ML-Intern, and a diverse retrieval with a weak top match
    (behavioral-econ case) also does NOT — only the BOTH case warrants
    paying the Semantic Scholar / external-API round-trip."""
    if not neighbors:
        return {
            "should_escalate": False,
            "max_score": 0.0,
            "distinct_books": 0,
            "books": [],
            "reason": "no neighbors retrieved",
            "score_threshold": RETRIEVAL_ESCALATION_SCORE_THRESHOLD,
            "min_distinct_books": RETRIEVAL_ESCALATION_MIN_DISTINCT_BOOKS,
        }
    top = neighbors[:RETRIEVAL_ESCALATION_TOP_K]
    max_score = max((n.get("score", 0.0) for n in top), default=0.0)
    books_seen: list[str] = []
    for n in top:
        book = _foundational_book_name(
            n.get("doc_id", "") or "",
            n.get("source_layer", "") or "",
        )
        if book and book not in books_seen:
            books_seen.append(book)
    distinct_books = len(books_seen)

    weak_signal = max_score < RETRIEVAL_ESCALATION_SCORE_THRESHOLD
    narrow_coverage = distinct_books < RETRIEVAL_ESCALATION_MIN_DISTINCT_BOOKS
    should = weak_signal and narrow_coverage

    if should:
        reason = (
            f"weak signal AND narrow coverage: "
            f"max_score={max_score:.4f} < {RETRIEVAL_ESCALATION_SCORE_THRESHOLD} "
            f"AND distinct_foundational_books={distinct_books} "
            f"< {RETRIEVAL_ESCALATION_MIN_DISTINCT_BOOKS}"
        )
    elif weak_signal:
        reason = (
            f"weak signal (max_score={max_score:.4f}) but coverage is "
            f"diverse ({distinct_books} foundational books in top-"
            f"{RETRIEVAL_ESCALATION_TOP_K}); no escalation"
        )
    elif narrow_coverage:
        reason = (
            f"narrow coverage ({distinct_books} foundational books) but "
            f"signal is strong (max_score={max_score:.4f}); no escalation"
        )
    else:
        reason = (
            f"signal strong (max_score={max_score:.4f}) and coverage "
            f"diverse ({distinct_books} foundational books); no escalation"
        )
    return {
        "should_escalate": should,
        "max_score": max_score,
        "distinct_books": distinct_books,
        "books": books_seen,
        "reason": reason,
        "score_threshold": RETRIEVAL_ESCALATION_SCORE_THRESHOLD,
        "min_distinct_books": RETRIEVAL_ESCALATION_MIN_DISTINCT_BOOKS,
    }


def retrieve_literature(
    hypothesis_text: str,
    k: int = 10,
    *,
    parent_request_id: str | None = None,
) -> dict[str, Any]:
    """Return top-K nearest-neighbor literature chunks for the hypothesis.

    Args:
        hypothesis_text: the hypothesis to search against. The text is
            embedded with BGE-M3 and queried against Chroma.
        k: total neighbors to return AFTER deduplication. We pull
            slightly more from Chroma to give dedup headroom.

    Returns:
        Worker-shaped dict matching `iteration_record.retrieval`:
        ```
        {
            "status": "passed" | "error",
            "result": {
                "k": <int — count after dedup>,
                "neighbors": [
                    {
                        "doc_id": str,
                        "content_hash": str,  # "sha256:..."
                        "score": float,        # 1.0 - distance, higher = more similar
                        "chunk_text": str,
                        "source_layer": "foundational" | "live_arxiv",
                        "title": str | None,
                    },
                    ...
                ],
                "latency_ms": float,
            },
            "errors": [str, ...],
            "parent_request_id": str | None,
        }
        ```
    """
    if not isinstance(hypothesis_text, str) or not hypothesis_text.strip():
        return {
            "status": "error",
            "result": {"k": 0, "neighbors": [], "latency_ms": 0.0},
            "errors": ["hypothesis_text is required and must be non-empty"],
            "parent_request_id": parent_request_id,
        }
    k = max(1, min(k, 50))

    # Pull a bit more than k so dedup doesn't undershoot. Chroma can
    # return duplicate chunks across collections (we saw this on iter-001:
    # `osborne_rubinstein-chunk-831` and `-836` returned identical content).
    overshoot = min(k * 2, 50)
    raw = query_top_k(hypothesis_text, k=overshoot, parent_request_id=parent_request_id)

    if raw["status"] != "passed":
        return {
            "status": "error",
            "result": raw.get("result", {"k": 0, "neighbors": [], "latency_ms": 0.0}),
            "errors": raw.get("errors", ["query_top_k returned error status"]),
            "parent_request_id": parent_request_id,
        }

    neighbors = raw["result"].get("neighbors", [])
    seen: dict[str, dict] = {}
    for n in neighbors:
        h = n.get("content_hash")
        if not h:
            # No hash means we can't dedupe; keep distinct entries by doc_id.
            h = f"no-hash:{n.get('doc_id', '?')}"
        existing = seen.get(h)
        if existing is None or n.get("score", 0.0) > existing.get("score", 0.0):
            seen[h] = n
    deduped = sorted(seen.values(), key=lambda n: n.get("score", 0.0), reverse=True)[:k]

    return {
        "status": "passed",
        "result": {
            "k": len(deduped),
            "neighbors": deduped,
            "latency_ms": raw["result"].get("latency_ms", 0.0),
            "escalation": _evaluate_escalation(deduped),
        },
        "errors": [],
        "parent_request_id": parent_request_id,
    }


if __name__ == "__main__":
    # Smoke: `env -u MOCK_LLM ./.venv-chroma/bin/python -m workers.retrieve_literature`
    import json
    out = retrieve_literature(
        "Tit-for-Tat dominance in repeated Prisoner's Dilemma", k=8
    )
    print(json.dumps(
        {
            "status": out["status"],
            "k": out["result"]["k"],
            "latency_ms": out["result"]["latency_ms"],
            "first_two": out["result"]["neighbors"][:2],
        },
        indent=2,
        default=str,
    ))
