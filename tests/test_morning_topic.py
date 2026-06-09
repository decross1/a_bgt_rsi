"""Tests for orchestrator.morning_topic — the coordinator topic auto-picker.

Hermetic: the single network/disk seam is `_recent_papers_metadata` (the
`papers_recent` Chroma read), which every test monkeypatches so NO real store /
BGE-M3 model / network is touched — green under MOCK_LLM=1. The module makes no
LLM call, so there is nothing else to stub. loop_memory reads go to a tmp file.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from orchestrator import morning_topic as mt


def _stub_papers(monkeypatch, metadatas):
    """Replace the only IO seam so no real Chroma store is hit."""
    monkeypatch.setattr(mt, "_recent_papers_metadata", lambda *a, **k: list(metadatas))


def _write_loop_memory(tmp_path, rows):
    p = tmp_path / "loop_memory.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return p


# ── primary path: newest arXiv paper ──────────────────────────────────────


def test_returns_newest_paper_title_by_publication_date(monkeypatch, tmp_path):
    _stub_papers(monkeypatch, [
        {"title": "Older Coordination Paper", "arxiv_id": "2604.00001",
         "publication_date": "2026-04-01"},
        {"title": "Newest Repeated-Games Paper", "arxiv_id": "2606.00002",
         "publication_date": "2026-06-07"},
        {"title": "Middle Paper", "arxiv_id": "2605.00003",
         "publication_date": "2026-05-15"},
    ])
    topic, source = mt.pick_morning_topic(
        loop_memory_path=_write_loop_memory(tmp_path, []))
    assert topic == "Newest Repeated-Games Paper"
    assert source == "arxiv_pick"


def test_tie_break_on_arxiv_id_when_dates_equal(monkeypatch, tmp_path):
    # Same publication_date -> the higher arxiv_id is the later submission.
    _stub_papers(monkeypatch, [
        {"title": "Same-Day Earlier", "arxiv_id": "2606.00010",
         "publication_date": "2026-06-08"},
        {"title": "Same-Day Later", "arxiv_id": "2606.00099",
         "publication_date": "2026-06-08"},
    ])
    topic, source = mt.pick_morning_topic(
        loop_memory_path=_write_loop_memory(tmp_path, []))
    assert topic == "Same-Day Later"
    assert source == "arxiv_pick"


def test_skips_rows_without_a_usable_title(monkeypatch, tmp_path):
    # The newest-by-date row has a blank title; the picker must skip it and
    # take the newest *titled* row rather than returning an empty string.
    _stub_papers(monkeypatch, [
        {"title": "   ", "arxiv_id": "2606.00500", "publication_date": "2026-06-09"},
        {"title": "Real Titled Paper", "arxiv_id": "2606.00001",
         "publication_date": "2026-06-05"},
    ])
    topic, source = mt.pick_morning_topic(
        loop_memory_path=_write_loop_memory(tmp_path, []))
    assert topic == "Real Titled Paper"
    assert source == "arxiv_pick"


def test_missing_publication_date_floors_below_dated_papers(monkeypatch, tmp_path):
    _stub_papers(monkeypatch, [
        {"title": "Dateless Paper", "arxiv_id": "2606.09999"},  # no date
        {"title": "Dated Paper", "arxiv_id": "2606.00001",
         "publication_date": "2026-06-01"},
    ])
    topic, source = mt.pick_morning_topic(
        loop_memory_path=_write_loop_memory(tmp_path, []))
    assert topic == "Dated Paper"
    assert source == "arxiv_pick"


# ── fallback 1: loop_memory gap probe ──────────────────────────────────────


def test_empty_papers_falls_back_to_loop_memory_angle(monkeypatch, tmp_path):
    _stub_papers(monkeypatch, [])  # papers_recent empty / unreachable
    lm = _write_loop_memory(tmp_path, [
        {"iteration_id": "iter-1",
         "hypothesis": {"text": "VCG truthfulness decays with item count"},
         "seed": {"topic": "auctions", "source": "human_cli"}},
    ])
    topic, source = mt.pick_morning_topic(loop_memory_path=lm)
    assert source == "loop_memory_probe"
    assert "VCG truthfulness decays with item count" in topic
    assert topic.strip()


def test_loop_memory_angle_uses_seed_topic_when_no_hypothesis(monkeypatch, tmp_path):
    _stub_papers(monkeypatch, [])
    lm = _write_loop_memory(tmp_path, [
        {"iteration_id": "iter-2",
         "seed": {"topic": "risk dominance in coordination games",
                  "source": "human_cli"}},  # no hypothesis key
    ])
    topic, source = mt.pick_morning_topic(loop_memory_path=lm)
    assert source == "loop_memory_probe"
    assert "risk dominance in coordination games" in topic


# ── fallback 2: safe fixed topic ───────────────────────────────────────────


def test_empty_papers_and_empty_memory_uses_safe_fallback(monkeypatch, tmp_path):
    _stub_papers(monkeypatch, [])
    lm = _write_loop_memory(tmp_path, [])  # nothing in loop_memory either
    topic, source = mt.pick_morning_topic(loop_memory_path=lm)
    assert topic == mt._SAFE_FALLBACK_TOPIC
    assert source == "loop_memory_probe"
    assert topic.strip()


def test_missing_loop_memory_file_still_yields_safe_fallback(monkeypatch, tmp_path):
    _stub_papers(monkeypatch, [])
    topic, source = mt.pick_morning_topic(
        loop_memory_path=tmp_path / "does_not_exist.jsonl")
    assert topic == mt._SAFE_FALLBACK_TOPIC
    assert source == "loop_memory_probe"


# ── invariants the coordinator action schema relies on ─────────────────────


@pytest.mark.parametrize("metas", [
    [],
    [{"title": "X", "arxiv_id": "2606.1", "publication_date": "2026-06-01"}],
    [{"arxiv_id": "2606.2"}],  # untitled only -> must still produce a topic
])
def test_topic_is_always_nonempty(monkeypatch, tmp_path, metas):
    _stub_papers(monkeypatch, metas)
    topic, source = mt.pick_morning_topic(
        loop_memory_path=_write_loop_memory(tmp_path, []))
    assert isinstance(topic, str) and topic.strip(), "schema requires minLength:1"
    assert source in ("arxiv_pick", "loop_memory_probe")


def test_seam_raising_degrades_to_fallback_without_network(monkeypatch, tmp_path):
    """Exercise the real `_recent_papers_metadata` against a collection whose
    read raises — proves the try/except degrades to [] (no network escape) and
    the picker still returns a valid topic."""
    class _Boom:
        def get(self, *a, **k):
            raise RuntimeError("store unreachable")

    monkeypatch.setattr(mt.chroma_query, "_get_collection", lambda name: _Boom())
    # No loop_memory either -> safe fallback, all without touching a real store.
    topic, source = mt.pick_morning_topic(
        loop_memory_path=tmp_path / "none.jsonl")
    assert topic == mt._SAFE_FALLBACK_TOPIC
    assert source == "loop_memory_probe"
