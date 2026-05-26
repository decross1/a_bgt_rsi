"""LOOP_V0 step 6 worker — journal_writer (Part-2 full version).

Replaces `orchestrator.journal_stub.journal_writer_stub` for the
real LOOP_V0 chain. Takes the full hypothesis / retrieval / novelty /
critique substructures Nara has gathered from the prior tools and
writes a human-readable markdown entry to
`journal/iterations/NNN.md`.

The append to `memory/loop_memory.jsonl` (with the full iteration_record
validation against `schema/iteration_record.schema.json`) still happens
in `orchestrator/nara.py` post-tool, via
`orchestrator.journal_stub.finalize_iteration_record` — that function
knows the orchestrator-owned fields (iteration_id, started_at, ended_at,
wrapper_call_ids, model_version) that Nara hasn't seen.

This worker:
  1. Validates the four substructures against the schema's enum sets
     (novelty.class, critique.verdict) — fail loud if Nara hands us
     garbage.
  2. Writes a structured markdown entry with hypothesis, top neighbors,
     novelty rationale, critique rationale, and Nara's summary.
  3. Returns the journal_entry_path for the orchestrator to slot into
     the iteration_record.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
JOURNAL_DIR = REPO_ROOT / "journal" / "iterations"

NOVELTY_CLASSES = ("novel", "rediscovery", "nonsense", "unclear")
CRITIC_VERDICTS = ("survives", "falsified", "restated", "malformed")


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _next_iteration_number() -> int:
    """Sequential NNN for journal/iterations/NNN.md. Matches the pattern
    in orchestrator/journal_stub.py."""
    JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
    existing = sorted(JOURNAL_DIR.glob("*.md"))
    if not existing:
        return 1
    try:
        last_n = max(int(p.stem) for p in existing if p.stem.isdigit())
    except ValueError:
        return len(existing) + 1
    return last_n + 1


def _format_neighbors_for_journal(neighbors: list[dict]) -> str:
    """Compact bullet list of neighbors for the markdown body."""
    if not neighbors:
        return "- _(none retrieved)_"
    lines = []
    for n in neighbors[:10]:
        doc_id = n.get("doc_id", "?")
        score = n.get("score")
        title = n.get("title") or "(untitled)"
        source = n.get("source_layer", "?")
        score_str = f"{score:.3f}" if isinstance(score, (int, float)) else "?"
        lines.append(f"- `{doc_id}` · score {score_str} · {source} · {title}")
    if len(neighbors) > 10:
        lines.append(f"- _(+{len(neighbors) - 10} more)_")
    return "\n".join(lines)


def journal_writer(
    topic: str,
    hypothesis: dict[str, Any],
    retrieval: dict[str, Any],
    novelty: dict[str, Any],
    critique: dict[str, Any],
    nara_summary: str,
    *,
    parent_request_id: str | None = None,
) -> dict[str, Any]:
    """Finalize an iteration by writing the markdown journal entry.

    Args (each matches its `iteration_record.<field>` subschema):
        topic: the seed topic string.
        hypothesis: `{text, candidates_considered, all_candidates}`.
        retrieval: `{k, neighbors}`.
        novelty: `{class, rationale, top_neighbor_id?}`.
        critique: `{verdict, rationale, contradicting_paper_id?}`.
        nara_summary: Nara's one-or-two-paragraph closing.

    Returns:
    ```
    {
        "status": "passed" | "error",
        "result": {
            "journal_entry_path": "journal/iterations/NNN.md",
            "iteration_number": int,
        } | None,
        "errors": [str, ...],
        "parent_request_id": str | None,
    }
    ```
    """
    errors: list[str] = []

    if not isinstance(topic, str) or not topic.strip():
        errors.append("topic is required and must be non-empty")
    if not isinstance(hypothesis, dict):
        errors.append("hypothesis must be an object")
    if not isinstance(retrieval, dict):
        errors.append("retrieval must be an object")
    if not isinstance(novelty, dict):
        errors.append("novelty must be an object")
    if not isinstance(critique, dict):
        errors.append("critique must be an object")
    if not isinstance(nara_summary, str):
        nara_summary = str(nara_summary) if nara_summary is not None else ""

    if errors:
        return {
            "status": "error",
            "result": None,
            "errors": errors,
            "parent_request_id": parent_request_id,
        }

    # Validate enum fields fail-loud — orchestrator caller bugs surface
    # here, not silently in loop_memory.
    novelty_class = novelty.get("class")
    if novelty_class not in NOVELTY_CLASSES:
        errors.append(
            f"novelty.class={novelty_class!r} not in {NOVELTY_CLASSES}"
        )
    critique_verdict = critique.get("verdict")
    if critique_verdict not in CRITIC_VERDICTS:
        errors.append(
            f"critique.verdict={critique_verdict!r} not in {CRITIC_VERDICTS}"
        )
    hypothesis_text = hypothesis.get("text")
    if not isinstance(hypothesis_text, str) or not hypothesis_text.strip():
        errors.append("hypothesis.text is required")

    if errors:
        return {
            "status": "error",
            "result": None,
            "errors": errors,
            "parent_request_id": parent_request_id,
        }

    nnn = _next_iteration_number()
    md_path = JOURNAL_DIR / f"{nnn:03d}.md"
    JOURNAL_DIR.mkdir(parents=True, exist_ok=True)

    neighbors = retrieval.get("neighbors") or []
    k = retrieval.get("k", len(neighbors))

    novelty_rationale = (novelty.get("rationale") or "").strip()
    novelty_top = novelty.get("top_neighbor_id")
    critique_rationale = (critique.get("rationale") or "").strip()
    critique_cite = critique.get("contradicting_paper_id")

    all_candidates = hypothesis.get("all_candidates") or []
    candidates_considered = hypothesis.get("candidates_considered", len(all_candidates))

    md = [
        f"# Iteration {nnn:03d}",
        "",
        f"*Written: {_utcnow_iso()}*",
        "",
        "## Seed",
        "",
        topic.strip(),
        "",
        "## Hypothesis",
        "",
        hypothesis_text.strip(),
        "",
        f"_{candidates_considered} candidate(s) considered._",
        "",
    ]
    if len(all_candidates) > 1:
        md.append("<details><summary>All candidates</summary>")
        md.append("")
        for c in all_candidates:
            md.append(f"- {c}")
        md.append("")
        md.append("</details>")
        md.append("")
    md.extend([
        "## Retrieval",
        "",
        f"Top-{k} nearest neighbors from `chroma_db/`:",
        "",
        _format_neighbors_for_journal(neighbors),
        "",
        "## Novelty",
        "",
        f"**Class:** `{novelty_class}`" + (
            f" · top neighbor: `{novelty_top}`" if novelty_top else ""
        ),
        "",
    ])
    if novelty_rationale:
        md.append(novelty_rationale)
        md.append("")
    md.extend([
        "## Critique",
        "",
        f"**Verdict:** `{critique_verdict}`" + (
            f" · contradicting: `{critique_cite}`" if critique_cite else ""
        ),
        "",
    ])
    if critique_rationale:
        md.append(critique_rationale)
        md.append("")
    md.extend([
        "## Nara's summary",
        "",
        nara_summary.strip() if nara_summary.strip() else "_(no summary emitted)_",
        "",
    ])

    md_path.write_text("\n".join(md))

    return {
        "status": "passed",
        "result": {
            "journal_entry_path": f"journal/iterations/{nnn:03d}.md",
            "iteration_number": nnn,
        },
        "errors": [],
        "parent_request_id": parent_request_id,
    }


if __name__ == "__main__":
    # Smoke with synthetic inputs.
    out = journal_writer(
        topic="smoke test",
        hypothesis={
            "text": "Hypothesis text for smoke.",
            "candidates_considered": 2,
            "all_candidates": ["Hypothesis text for smoke.", "Alternative."],
        },
        retrieval={
            "k": 2,
            "neighbors": [
                {"doc_id": "osborne_rubinstein-chunk-831", "score": 0.59,
                 "source_layer": "foundational", "title": "8 Repeated Games"},
                {"doc_id": "paper-2605.15049", "score": 0.45,
                 "source_layer": "live_arxiv", "title": "Some Paper"},
            ],
        },
        novelty={
            "class": "rediscovery",
            "rationale": "Well-known.",
            "top_neighbor_id": "osborne_rubinstein-chunk-831",
        },
        critique={
            "verdict": "restated",
            "rationale": "It's a restatement.",
            "contradicting_paper_id": "osborne_rubinstein-chunk-831",
        },
        nara_summary="Nara: This iteration tested a known textbook claim.",
        parent_request_id="smoke",
    )
    print(json.dumps(out, indent=2))
