"""Morning topic auto-picker — un-blinds the coordinator planner.

The Slice-Alpha coordinator planner is topic-BLIND: `assess_state` carries no
candidate topics, so on 2026-06-08 the planner never proposed
`run_loop_iteration` (its arg schema REQUIRES a non-empty `topic`). This module
supplies one topic suggestion the planner can lift into that action.

Three sources, tried in order (each names the `seed.source` enum value Nara
stamps on the iteration record — see schema/iteration_record.schema.json):

  1. ``arxiv_pick``        — the NEWEST paper title in the live `papers_recent`
                             Chroma layer (by `publication_date`, tie-broken by
                             arxiv_id). This is the live-arXiv front door.
  2. ``loop_memory_probe`` — when no recent paper is reachable, a gap-derived
                             angle off the most recent loop_memory hypothesis
                             (a "go deeper / adjacent" probe).
  3. ``loop_memory_probe`` — a fixed in-scope safe topic, so the picker NEVER
                             returns an empty string (the action schema rejects
                             one) and the morning loop always has something
                             worthwhile to run.

Reuse, not reinvention: the newest-paper read goes through
`orchestrator.chroma_query._get_collection`, which already owns the cached
BGE-M3 embedder + PersistentClient. Fetching the newest paper is a pure
METADATA read (`collection.get`), so no query embedding is computed here — we
do NOT reimplement embedding. `publication_date` / `title` / `arxiv_id` are the
metadata fields `pipeline/embed_and_store.py` writes on every `papers_recent`
row.

MOCK_LLM note: `chroma_query` only stubs its semantic `query_top_k`, NOT
`_get_collection` (which would load the real BGE-M3 model). So the
metadata-fetch seam `_recent_papers_metadata` is what tests monkeypatch; this
module reaches no network/model when that seam is stubbed.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from orchestrator import chroma_query

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOOP_MEMORY = REPO_ROOT / "memory" / "loop_memory.jsonl"

# The live-arXiv collection populated by pipeline/embed_and_store.py.
PAPERS_RECENT = "papers_recent"

# Final safety net: a concrete, in-scope topic so the picker never yields the
# empty string the run_loop_iteration arg schema rejects. Behavioural game
# theory in repeated games is the apparatus's home turf (see research_program).
_SAFE_FALLBACK_TOPIC = (
    "Strategic stability of cooperation in repeated games played by LLM agents"
)


def _recent_papers_metadata(collection_name: str = PAPERS_RECENT) -> list[dict[str, Any]]:
    """Return the raw metadata dicts for every row in `papers_recent`.

    A pure metadata read via Chroma `collection.get` — no embedding is computed
    (the newest-paper pick is recency-ordered, not semantic). Reuses
    `chroma_query._get_collection` for the cached client/embedder. This is the
    single network/disk seam; tests monkeypatch it so they hit no real store.
    Never raises — an unreachable/empty store degrades to ``[]``.
    """
    try:
        coll = chroma_query._get_collection(collection_name)
        got = coll.get(include=["metadatas"])
    except Exception:
        return []
    metas = got.get("metadatas") if isinstance(got, dict) else None
    return [m for m in (metas or []) if isinstance(m, dict)]


def _newest_paper_title(metadatas: list[dict[str, Any]]) -> str | None:
    """Pick the newest paper title from `papers_recent` metadata rows.

    Ordered by `publication_date` (the `YYYY-MM-DD` string written by
    embed_and_store; lexical order == chronological order for that format),
    tie-broken by `arxiv_id` descending (arxiv ids are date-ordered within an
    era, so the higher id is the later submission). Rows without a usable title
    are skipped. Returns None when no titled row exists.
    """
    candidates = [
        m for m in metadatas
        if isinstance(m.get("title"), str) and m["title"].strip()
    ]
    if not candidates:
        return None
    # Sort key: (publication_date, arxiv_id) ascending; the last is newest.
    # Empty/missing dates floor to "" so a dated paper always outranks them.
    candidates.sort(
        key=lambda m: (
            str(m.get("publication_date") or ""),
            str(m.get("arxiv_id") or ""),
        )
    )
    return candidates[-1]["title"].strip()


def _read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    """Read a JSONL file into dicts. Missing/unreadable/malformed -> []/skip.

    Mirrors orchestrator.coordinator._read_jsonl (same tolerant contract)."""
    rows: list[dict[str, Any]] = []
    try:
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
    except Exception:
        return rows
    return rows


def _loop_memory_angle(loop_memory_path: str | Path) -> str | None:
    """Derive a gap-probe topic from the most recent loop_memory hypothesis.

    Reads the last row carrying a non-empty hypothesis text (falling back to its
    seed topic) and frames a "go deeper / find the boundary" angle off it — a
    cheap way to keep the morning loop moving when the live-arXiv layer is dry.
    Returns None when loop_memory holds nothing usable.
    """
    rows = _read_jsonl(loop_memory_path)
    for row in reversed(rows):
        hyp = row.get("hypothesis")
        text = hyp.get("text") if isinstance(hyp, dict) else None
        if not (isinstance(text, str) and text.strip()):
            seed = row.get("seed")
            text = seed.get("topic") if isinstance(seed, dict) else None
        if isinstance(text, str) and text.strip():
            seed_text = " ".join(text.split())[:200]
            return (
                "Probe an unresolved boundary of a recent line of inquiry: "
                f"{seed_text}"
            )
    return None


def pick_morning_topic(
    *,
    loop_memory_path: str | Path = DEFAULT_LOOP_MEMORY,
    collection_name: str = PAPERS_RECENT,
) -> tuple[str, str]:
    """Pick a topic + its source for one autonomous morning iteration.

    Returns ``(topic, source)`` where ``source`` is a seed.source enum value:

      - ``"arxiv_pick"``        — newest `papers_recent` paper title (primary).
      - ``"loop_memory_probe"`` — gap angle off recent loop_memory, OR the safe
                                  fallback topic, when no recent paper is found.

    The returned topic is ALWAYS a non-empty string (the run_loop_iteration arg
    schema requires `minLength: 1`). Never raises.
    """
    title = _newest_paper_title(_recent_papers_metadata(collection_name))
    if title:
        return title, "arxiv_pick"

    angle = _loop_memory_angle(loop_memory_path)
    if angle:
        return angle, "loop_memory_probe"

    return _SAFE_FALLBACK_TOPIC, "loop_memory_probe"


if __name__ == "__main__":
    # Smoke: `env -u MOCK_LLM .venv-chroma/bin/python -m orchestrator.morning_topic`
    topic, source = pick_morning_topic()
    print(json.dumps({"topic": topic, "source": source}, indent=2))
