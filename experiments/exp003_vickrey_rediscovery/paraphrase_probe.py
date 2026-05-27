#!/usr/bin/env python3
"""exp003 — paraphrased-seed retrieval probe.

Follow-up to the 50-trial run: the original Tier-2 → Tier-3 topic seed
surfaced Osborne & Rubinstein chunks as the dominant auction-theory
neighbors in retrieval, but Camerer BGT (which is indexed in the
`camerer_bgt` collection and has substantial Vickrey/auction content)
did not appear in the top-10. Is that a ranking outcome, or an artifact
of the seed's wording?

This script bypasses ``hypothesize`` and queries ``orchestrator.chroma_
query.query_top_k`` DIRECTLY with four seed variants of the same
underlying claim, then tabulates the top-15 neighbors for each. The
question is: under any phrasing, does a Camerer BGT chunk reach the
top-10?

Variants:
  A — original (Tier-2 experimental vocabulary, as used in the live
      LOOP_V0 iteration on 2026-05-27 → iter-028)
  B — Camerer / behavioral-economics vocabulary
  C — Myerson / mechanism-design vocabulary
  D — textbook-style minimal phrasing

Run:
    env -u MOCK_LLM ./.venv-chroma/bin/python \\
        experiments/exp003_vickrey_rediscovery/paraphrase_probe.py

Output: ``results/paraphrase_probe.md``.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from orchestrator.chroma_query import query_top_k  # noqa: E402

EXP_DIR = Path(__file__).resolve().parent
OUT_PATH = EXP_DIR / "results" / "paraphrase_probe.md"

K = 15

# Threshold candidates for Slice-2 ML-Intern escalation trigger.
# Escalation fires when max neighbor score is BELOW the threshold
# (signal too weak → query Semantic Scholar via ML-Intern). 0.55 was
# Agent β's spec; 0.70 is the current bump-candidate.
THRESHOLDS = [0.55, 0.65, 0.70, 0.75]

SEEDS = [
    {
        "label": "A_original",
        "tag": "Tier-2 experimental vocabulary (verbatim from iter-028)",
        "text": (
            "In repeated single-round sealed-bid second-price auctions with "
            "four LLM bidders drawing independent private valuations from "
            "U[0, 100] and no priming on auction theory, bidders converge "
            "on submitting bids approximately equal to their private "
            "valuations (observed truthful-bid fraction: 100.00% of trials "
            "had mean |bid − valuation| ≤ 5)."
        ),
    },
    {
        "label": "B_camerer_behavioral",
        "tag": "Behavioral-economics / Camerer vocabulary",
        "text": (
            "In behavioral economics experiments with second-price sealed-"
            "bid auctions, subjects systematically converge on truthful "
            "value-revelation as the dominant strategy, an empirical "
            "finding that holds across diverse experimental populations "
            "and is replicated here with four LLM agents."
        ),
    },
    {
        "label": "C_myerson_mechanism_design",
        "tag": "Mechanism-design / Myerson vocabulary",
        "text": (
            "Vickrey's incentive-compatibility result for the second-price "
            "sealed-bid mechanism states that bidding one's private "
            "valuation is a weakly dominant strategy; empirical play in a "
            "four-bidder setting with independent valuations on a bounded "
            "interval confirms this rediscovery."
        ),
    },
    {
        "label": "D_textbook_minimal",
        "tag": "Textbook minimal phrasing",
        "text": (
            "In a second-price (Vickrey) auction with N=4 bidders drawing "
            "independent private valuations, every bidder's weakly "
            "dominant action is to bid their valuation. Empirical bidding "
            "behavior in LLM-driven plays matches this prediction."
        ),
    },
]


def _query(text: str) -> list[dict]:
    res = query_top_k(text=text, k=K)
    if res["status"] != "passed":
        raise SystemExit(f"FATAL: chroma query failed: {res['errors']}")
    return res["result"]["neighbors"]


def _book_from_doc_id(doc_id: str) -> str:
    """Pull the leading book-name from a foundational doc_id (e.g.,
    `camerer_bgt-chunk-42` → `camerer_bgt`). Returns the doc_id itself
    for arXiv ids."""
    if "-chunk-" in doc_id:
        return doc_id.split("-chunk-", 1)[0]
    return doc_id


def _render_table(neighbors: list[dict]) -> str:
    out = ["| rank | doc_id | score | source | book | title |",
           "|---|---|---|---|---|---|"]
    for i, n in enumerate(neighbors, 1):
        doc_id = n.get("doc_id", "?")
        score = n.get("score", float("nan"))
        layer = n.get("source_layer", "?")
        title = n.get("title")
        title_disp = (title or "(none)").replace("|", "\\|")
        if len(title_disp) > 60:
            title_disp = title_disp[:57] + "..."
        book = _book_from_doc_id(doc_id) if layer == "foundational" else "arxiv"
        out.append(f"| {i} | `{doc_id}` | {score:.4f} | {layer} | `{book}` "
                   f"| {title_disp} |")
    return "\n".join(out)


def main() -> int:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    blocks: list[str] = []
    book_appearances: dict[str, list[int]] = {}  # book -> [seed_indices with appearance in top-10]
    max_scores: dict[str, float] = {}  # seed_label -> max neighbor score

    blocks.append("# exp003 — paraphrased-seed retrieval probe")
    blocks.append("")
    blocks.append(
        "Direct Chroma queries (bypassing `hypothesize`) on four "
        "phrasings of the same Vickrey-rediscovery claim. "
        f"Top-{K} merged neighbors per seed. Two questions: (1) under "
        "any phrasing, does a Camerer BGT chunk reach the top-10? "
        "(2) which Slice-2 ML-Intern escalation threshold would fire "
        "on these seeds?"
    )
    blocks.append("")

    for i, spec in enumerate(SEEDS, 1):
        print(f"[{i}/{len(SEEDS)}] querying seed {spec['label']!r}...", flush=True)
        neighbors = _query(spec["text"])
        blocks.append(f"## Seed {spec['label']}")
        blocks.append("")
        blocks.append(f"**Phrasing:** {spec['tag']}")
        blocks.append("")
        blocks.append("> " + spec["text"])
        blocks.append("")
        blocks.append(_render_table(neighbors))
        blocks.append("")

        # Track which foundational books appear in the top-10.
        for rank, n in enumerate(neighbors[:10], 1):
            if n.get("source_layer") == "foundational":
                book = _book_from_doc_id(n.get("doc_id", ""))
                book_appearances.setdefault(book, []).append(i)

        # Track max neighbor score for threshold evaluation.
        max_scores[spec["label"]] = max(
            (n.get("score", 0.0) for n in neighbors), default=0.0
        )

    # Cross-seed summary: which books showed up in the top-10 for which seeds.
    blocks.append("## Cross-seed summary: foundational-book appearances in top-10")
    blocks.append("")
    blocks.append("| book | seeds (1-indexed) with appearance | count |")
    blocks.append("|---|---|---|")
    for book in sorted(book_appearances):
        seeds = sorted(set(book_appearances[book]))
        blocks.append(f"| `{book}` | {seeds} | {len(seeds)} |")
    blocks.append("")

    camerer_seeds = sorted(set(book_appearances.get("camerer_bgt", [])))
    if camerer_seeds:
        blocks.append(
            f"**Camerer BGT reached top-10 under seeds {camerer_seeds} — "
            "the original-seed retrieval gap is at least partially "
            "phrasing-dependent.**"
        )
    else:
        blocks.append(
            "**Camerer BGT did NOT reach top-10 under any of the four "
            "seed phrasings. The retrieval gap is not just a wording "
            "artifact — the embedder consistently ranks Osborne & "
            "Rubinstein closer to this claim than Camerer BGT.**"
        )
    blocks.append("")

    # Slice-2 ML-Intern escalation threshold evaluation.
    blocks.append("## Slice-2 ML-Intern escalation threshold evaluation")
    blocks.append("")
    blocks.append(
        "ML-Intern escalation (Agent β's spec) fires when "
        "`max(neighbor.score) < THRESHOLD`. The 4 seeds here are all "
        "phrasings of the SAME Vickrey-rediscovery claim — a single "
        "Tier-2 finding. For threshold tuning, the question is: under "
        "which threshold does escalation fire for some-but-not-all "
        "phrasings (an over-sensitive or under-sensitive trigger)?"
    )
    blocks.append("")
    blocks.append("| seed | max neighbor score |"
                  + "".join(f" fires at {t}? |" for t in THRESHOLDS))
    blocks.append("|---|---|" + "---|" * len(THRESHOLDS))
    for spec in SEEDS:
        label = spec["label"]
        ms = max_scores.get(label, 0.0)
        fire_cells = "".join(
            f" {'YES' if ms < t else 'no'} |" for t in THRESHOLDS
        )
        blocks.append(f"| `{label}` | {ms:.4f} |{fire_cells}")
    blocks.append("")
    blocks.append("**Summary:**")
    blocks.append("")
    for t in THRESHOLDS:
        fires = [s["label"] for s in SEEDS if max_scores[s["label"]] < t]
        if not fires:
            line = f"- threshold **{t:.2f}**: never fires (under-sensitive)"
        elif len(fires) == len(SEEDS):
            line = f"- threshold **{t:.2f}**: fires on all 4 seeds (over-sensitive)"
        else:
            line = (f"- threshold **{t:.2f}**: fires on {len(fires)}/4 "
                    f"seeds — {fires}")
        blocks.append(line)
    blocks.append("")

    OUT_PATH.write_text("\n".join(blocks))
    print(f"wrote {OUT_PATH}")
    print(f"camerer_bgt top-10 appearances: seeds {camerer_seeds or '(none)'}")
    print(f"max scores: {[(k, round(v, 4)) for k, v in max_scores.items()]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
