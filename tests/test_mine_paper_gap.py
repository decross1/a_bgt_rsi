"""Tests for workers.mine_paper_gap — the P4 dedup-keystone v0.

Hermetic + deterministic: NO real model, NO Chroma store. Two seams are
monkeypatched —
  * `_embed_texts`        -> a stub mapping a 2-char marker `[[xx]]` embedded in
                             each text to a fixed vector (the markers never
                             tokenize, so they don't pollute the lexical layer);
  * `_sample_recent_papers` -> returns hand-built candidate papers.
`MOCK_LLM=1` is forced so `domain_anchor.anchor_cosine` returns None (the
on-domain cap is smoke-only) and all file writes go to `tmp_path` (the
conftest `_no_live_artifacts` discipline is honored — zero live ledgers).

The keystone assertion is the falsifier oracle: stem-shared *reworded* near-dups
(distinct vectors, so the cosine layers CANNOT collapse them) are collapsed to
<=1 survivor by the LOAD-BEARING lexical layer, while genuinely distinct claims
are preserved.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from workers import mine_paper_gap as mpg


@pytest.fixture(autouse=True)
def _hermetic_idea_ledger(tmp_path, monkeypatch):
    """D-060 hermeticity: mine_paper_gap seeds paper niches + agenda items
    into DEFAULT_IDEA_LEDGER — point it at a tmp path so these tests never
    write the real repo ledger (which happened once, 2026-08-14, and was
    cleaned; this fixture is the pin)."""
    monkeypatch.setattr(mpg, "DEFAULT_IDEA_LEDGER",
                        tmp_path / "idea_ledger.jsonl")


# Marker -> fixed vector. Orthogonal unit vectors give clean cosines; the
# reworded near-dups (k1/k2/k3) are MUTUALLY orthogonal so the cosine layers
# stay silent and ONLY the lexical layer can collapse them.
VEC = {
    "k1": [1.0, 0.0, 0.0, 0.0, 0.0],
    "k2": [0.0, 1.0, 0.0, 0.0, 0.0],
    "k3": [0.0, 0.0, 1.0, 0.0, 0.0],
    "d1": [0.0, 0.0, 0.0, 1.0, 0.0],
    "d2": [0.0, 0.0, 0.0, 0.0, 1.0],
    "q1": [1.0, 0.0, 0.0, 0.0, 0.0],   # intra-batch: two papers, one vector
    "t1": [1.0, 0.0, 0.0, 0.0, 0.0],   # tau_dup: prior + candidate identical
    "pq": [0.0, 1.0, 0.0, 0.0, 0.0],
    "rp": [1.0, 0.0, 0.0, 0.0, 0.0],   # ranking prior
    "ra": [0.5, 0.8660254, 0.0, 0.0, 0.0],   # cos 0.5 to rp -> gap 0.5
    "rb": [0.1, 0.9949874, 0.0, 0.0, 0.0],   # cos 0.1 to rp -> gap 0.9
}


def _stub_embed(texts):
    out = []
    for t in texts:
        vec = next((list(v) for key, v in VEC.items() if f"[[{key}]]" in t), None)
        out.append(vec if vec is not None else [0.0, 0.0, 0.0, 0.0, 1.0])
    return out


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch):
    """Force MOCK_LLM (anchor None, no model) and the deterministic embedder."""
    monkeypatch.setenv("MOCK_LLM", "1")
    monkeypatch.setattr(mpg, "_embed_texts", _stub_embed)


def _paper(arxiv_id, title, abstract):
    return {"arxiv_id": arxiv_id, "title": title, "abstract": abstract,
            "category": "cs.GT", "publication_date": "2026-06-20"}


def _stub_papers(monkeypatch, papers):
    monkeypatch.setattr(mpg, "_sample_recent_papers",
                        lambda n, **k: [dict(p) for p in papers])


def _empty_loop_memory(tmp_path):
    p = tmp_path / "loop_memory.jsonl"
    p.write_text("")          # exists, zero usable rows -> empty prior corpus
    return p


def _write_loop_memory(tmp_path, rows):
    p = tmp_path / "loop_memory.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return p


def _run(tmp_path, loop_memory, max_emit=10):
    return mpg.mine_paper_gap(
        n=20, max_emit=max_emit,
        loop_memory_path=loop_memory,
        followups_path=tmp_path / "finding_followups.jsonl",
        ledger_path=tmp_path / "topic_proposals.jsonl",
        cache_path=tmp_path / "emb.json",
    )


# ── THE KEYSTONE: the falsifier oracle ─────────────────────────────────────

# Identical prose stem (drives lexical overlap); the marker is appended so the
# three near-dups get DISTINCT vectors (so cosine cannot be what collapses them).
_STEM = ("conditional cooperators using bayesian belief updating exhibit faster "
         "contribution decay under noisy contribution observation in repeated "
         "public goods")


def _near_dup_batch():
    return [
        _paper("2606.0001", "Faster decay under noisy observation",
               f"{_STEM} [[k1]]"),
        _paper("2606.0002", "Noisy observation accelerates contribution collapse",
               f"{_STEM} [[k2]]"),
        _paper("2606.0003", "Belief-driven decay among conditional cooperators",
               f"{_STEM} [[k3]]"),
        # genuinely distinct claims (disjoint vocabulary) -> must be preserved
        _paper("2606.0010", "Truthful bidding in combinatorial auctions",
               "truthful bidding degrades as the number of items grows under "
               "combinatorial valuations [[d1]]"),
        _paper("2606.0011", "Prompt length and agreement frequency",
               "prompt length raises agreement frequency between language models "
               "[[d2]]"),
    ]


def test_falsifier_oracle_lexical_collapses_reworded_near_dups(tmp_path, monkeypatch):
    """KEYSTONE: 3 reworded stem-shared near-dups (distinct vectors) collapse to
    exactly 1 survivor via the LEXICAL layer; 2 distinct claims are preserved."""
    _stub_papers(monkeypatch, _near_dup_batch())
    summary = _run(tmp_path, _empty_loop_memory(tmp_path))

    emitted = summary["emitted_topics"]
    near_dup_titles = {"Faster decay under noisy observation",
                       "Noisy observation accelerates contribution collapse",
                       "Belief-driven decay among conditional cooperators"}
    # cluster collapsed to <=1 survivor ...
    assert len(near_dup_titles & set(emitted)) == 1
    # ... and it was the top-ranked (first) member, ...
    assert "Faster decay under noisy observation" in emitted
    # ... while BOTH distinct claims survived.
    assert "Truthful bidding in combinatorial auctions" in emitted
    assert "Prompt length and agreement frequency" in emitted
    # the LEXICAL layer (not cosine) is what killed the 2 reworded dups.
    assert summary["dropped_by_layer"].get("lexical_jaccard") == 2
    assert summary["emitted"] == 3


def test_ledger_records_dropped_candidates_with_kill_layer(tmp_path, monkeypatch):
    """Every dropped candidate is logged to topic_proposals.jsonl with the dedup
    layer that killed it + its margin (the ARCH §6 logged-human-sample seam)."""
    _stub_papers(monkeypatch, _near_dup_batch())
    _run(tmp_path, _empty_loop_memory(tmp_path))

    ledger = [json.loads(l) for l in
              (tmp_path / "topic_proposals.jsonl").read_text().splitlines()]
    assert len(ledger) == 5  # every candidate logged (kept AND dropped)
    dropped = [r for r in ledger if r["status"] == "dropped"]
    assert len(dropped) == 2
    for r in dropped:
        assert r["kill_layer"] == "lexical_jaccard"
        assert r["margin"] is not None and r["detail"]
    assert any(r["status"] == "kept" for r in ledger)


# ── individual layers ──────────────────────────────────────────────────────


def test_intra_batch_greedy_suppression_fires(tmp_path, monkeypatch):
    """Two papers with an IDENTICAL vector but disjoint vocab: the lexical layer
    can't see them as dups, so layer 2 (cosine >= eps vs a kept survivor) fires."""
    _stub_papers(monkeypatch, [
        _paper("2606.1001", "Quantal response equilibrium selection",
               "logit choice noise in network coordination [[q1]]"),
        _paper("2606.1002", "Stochastic bandit convergence",
               "gradient estimators reduce regret bounds [[q1]]"),
    ])
    summary = _run(tmp_path, _empty_loop_memory(tmp_path))
    assert summary["dropped_by_layer"].get("intra_batch_cosine") == 1
    assert summary["emitted"] == 1


def test_high_cosine_tau_dup_catches_near_identical_restatement(tmp_path, monkeypatch):
    """A candidate whose vector ~ a prior hypothesis (cosine >= tau_dup ~0.97)
    but with DISJOINT vocabulary (lexical layer silent) is caught by layer 4."""
    lm = _write_loop_memory(tmp_path, [{
        "iteration_id": "iter-x",
        "hypothesis": {"text": "stochastic stability of risk-dominant conventions "
                               "under logit dynamics [[t1]]"},
        "seed": {"topic": "", "source": "human_cli"},
    }])
    _stub_papers(monkeypatch, [
        _paper("2606.2001", "Photonic lattice edge transport",
               "waveguide arrays exhibit protected boundary modes [[t1]]"),
    ])
    summary = _run(tmp_path, lm)
    assert summary["dropped_by_layer"].get("cosine_tau_dup") == 1
    assert summary["emitted"] == 0


def test_pending_queue_dedup_drops_already_queued_topic(tmp_path, monkeypatch):
    """A candidate whose arxiv_id is already an unconsumed new_topic row in
    finding_followups is dropped by layer 7 (survives layers 1-6 first)."""
    followups = tmp_path / "finding_followups.jsonl"
    followups.write_text(json.dumps(
        {"new_topic": "Already queued elsewhere", "arxiv_id": "2606.3001",
         "origin": "coordinator_propose"}) + "\n")
    _stub_papers(monkeypatch, [
        _paper("2606.3001", "Mean-field control of epidemic diffusion",
               "compartmental susceptible-infected dynamics on graphs [[pq]]"),
    ])
    summary = mpg.mine_paper_gap(
        n=20, max_emit=10,
        loop_memory_path=_empty_loop_memory(tmp_path),
        followups_path=followups,
        ledger_path=tmp_path / "topic_proposals.jsonl",
        cache_path=tmp_path / "emb.json")
    assert summary["dropped_by_layer"].get("pending_queue") == 1
    assert summary["emitted"] == 0
    # the pre-existing queued row is untouched (no duplicate emit).
    assert len(followups.read_text().splitlines()) == 1


def test_ranking_by_gap_score_orders_emits_widest_gap_first(tmp_path, monkeypatch):
    """Both candidates survive dedup; the wider-gap (farther-from-prior) one is
    emitted first. gap = 1 - max cosine to the prior corpus."""
    lm = _write_loop_memory(tmp_path, [{
        "iteration_id": "iter-r",
        "hypothesis": {"text": "convention selection under perturbed best response [[rp]]"},
        "seed": {"topic": "", "source": "human_cli"},
    }])
    _stub_papers(monkeypatch, [
        _paper("2606.4001", "Adaptive mesh refinement for turbulent flow",
               "spectral solvers reduce numerical dissipation [[ra]]"),   # gap 0.5
        _paper("2606.4002", "Holographic entanglement entropy bounds",
               "boundary conformal field correlators [[rb]]"),            # gap 0.9
    ])
    summary = mpg.mine_paper_gap(
        n=20, max_emit=2, loop_memory_path=lm,
        followups_path=tmp_path / "finding_followups.jsonl",
        ledger_path=tmp_path / "topic_proposals.jsonl",
        cache_path=tmp_path / "emb.json")
    assert summary["emitted_topics"] == [
        "Holographic entanglement entropy bounds",      # gap 0.9 first
        "Adaptive mesh refinement for turbulent flow",  # gap 0.5 second
    ]


# ── no silent fallback (rule 7) ────────────────────────────────────────────


def test_missing_loop_memory_raises_not_silent_empty(tmp_path, monkeypatch):
    """A missing loop_memory file RAISES — it is NOT a silent empty corpus that
    would fabricate every gap as maximal (inviolate rule 7)."""
    _stub_papers(monkeypatch, _near_dup_batch())
    with pytest.raises(FileNotFoundError):
        mpg.mine_paper_gap(
            n=20, max_emit=2,
            loop_memory_path=tmp_path / "does_not_exist.jsonl",
            followups_path=tmp_path / "finding_followups.jsonl",
            ledger_path=tmp_path / "topic_proposals.jsonl",
            cache_path=tmp_path / "emb.json")


def test_emitted_rows_carry_origin_and_grounding_abstract(tmp_path, monkeypatch):
    """Emitted new_topic rows are tagged origin=coordinator_propose, carry the
    ledger-only paper_gap provenance, and pass the abstract as grounding (#5)."""
    _stub_papers(monkeypatch, _near_dup_batch())
    _run(tmp_path, _empty_loop_memory(tmp_path), max_emit=1)
    rows = [json.loads(l) for l in
            (tmp_path / "finding_followups.jsonl").read_text().splitlines()]
    assert rows and rows[0]["origin"] == "coordinator_propose"
    assert rows[0]["provenance"] == "paper_gap"
    assert rows[0]["new_topic"] and rows[0]["abstract"]
    assert isinstance(rows[0]["new_topic"], str)
