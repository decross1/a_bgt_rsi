"""LOOP_V0 step 3 worker — retrieve_literature.

Given a hypothesis text, return top-K most-similar prior results from
Chroma across foundational (textbook) and live-arXiv collections.
Deterministic — does NOT call the LLM. The downstream `novelty_classify`
and `critic_loop_v0` workers consume the returned neighbors.

Wraps `orchestrator.chroma_query.query_top_k` with two additions:
- **Deduplication by content_hash** — when the same chunk happens to
  appear in multiple collections (or twice in one), we keep only the
  highest-scoring instance. The standalone query helper does NOT dedupe.
- **Worker contract shape** — Nara dispatches via the runtime, which
  passes `parent_request_id`; we thread it through.

The tool sees this as `retrieve_literature(hypothesis_text, k=10)`.
"""
from __future__ import annotations

from typing import Any

from orchestrator.chroma_query import query_top_k


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
