"""Tests for workers.journal_writer (post reference-passing).

Substructures (hypothesis / retrieval / novelty / critique) are read from
the per-iteration cache by `iteration_id` rather than being passed in.
Each test stages the cache via the `cache` fixture (tests/conftest.py)
mirroring what Nara does in production.
"""
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from workers import journal_writer as jw_mod


def _good_substructures():
    """The four worker payloads as Nara would have them in `captured`,
    BEFORE wrapping into the tool_result envelope for cache staging."""
    return {
        "hypothesis": {
            "text": "Cooperation rises with binding compute constraints.",
            "candidates_considered": 3,
            "all_candidates": [
                "Cooperation rises with binding compute constraints.",
                "TfT dominates above a threshold context window.",
                "Defection emerges above a critical reasoning depth.",
            ],
        },
        "retrieval": {
            "k": 2,
            "neighbors": [
                {
                    "doc_id": "osborne_rubinstein-chunk-831",
                    "score": 0.589,
                    "source_layer": "foundational",
                    "title": "8 Repeated Games",
                },
                {
                    "doc_id": "paper-2605.15049",
                    "score": 0.452,
                    "source_layer": "live_arxiv",
                    "title": "LLM Agents in Games",
                },
            ],
        },
        "novelty": {
            "class": "novel",
            "rationale": "No retrieved chunk addresses this claim.",
            "top_neighbor_id": "osborne_rubinstein-chunk-831",
        },
        "critique": {
            "verdict": "survives",
            "rationale": "Nothing in the retrieved set contradicts.",
            "contradicting_paper_id": None,
        },
    }


def _stage_all(cache, iteration_id: str, substructures: dict) -> None:
    """Wrap each substructure in a Nara-style tool_result envelope and
    write it to the cache under the right key."""
    for key, payload in substructures.items():
        cache.write_entry(iteration_id, key, {
            "status": "passed",
            "result": payload,
            "errors": [],
            "wrapper_request_id": f"rid-{key}",
            "parent_request_id": None,
        })


@pytest.fixture
def isolated_journal(tmp_path, monkeypatch):
    """Redirect journal output to tmp_path so tests don't accumulate
    entries in the real repo."""
    monkeypatch.setattr(jw_mod, "JOURNAL_DIR", tmp_path / "journal" / "iterations")
    return tmp_path / "journal" / "iterations"


# ── happy path ───────────────────────────────────────────────────────


def test_writes_markdown_and_returns_path(cache, isolated_journal):
    _stage_all(cache, "it-1", _good_substructures())
    out = jw_mod.journal_writer(
        topic="LLM cooperation in repeated PD",
        iteration_id="it-1",
        nara_summary="Nara: A candidate worth investigating further.",
        parent_request_id="p1",
    )
    assert out["status"] == "passed"
    assert out["result"]["iteration_number"] == 1
    assert out["result"]["journal_entry_path"] == "journal/iterations/001.md"
    assert out["parent_request_id"] == "p1"
    md_file = isolated_journal / "001.md"
    assert md_file.exists()
    body = md_file.read_text()
    assert "# Iteration 001" in body
    assert "Cooperation rises with binding compute constraints." in body
    assert "novelty" in body.lower()
    assert "`novel`" in body
    assert "`survives`" in body


def test_increments_iteration_number(cache, isolated_journal):
    subs = _good_substructures()
    _stage_all(cache, "it-a", subs)
    _stage_all(cache, "it-b", subs)
    _stage_all(cache, "it-c", subs)
    for n, iid in enumerate(("it-a", "it-b", "it-c"), 1):
        out = jw_mod.journal_writer(topic="t", iteration_id=iid, nara_summary="s")
        assert out["result"]["iteration_number"] == n
    assert (isolated_journal / "003.md").exists()


def test_renders_all_candidates_when_more_than_one(cache, isolated_journal):
    _stage_all(cache, "it-cands", _good_substructures())
    jw_mod.journal_writer(topic="t", iteration_id="it-cands", nara_summary="s")
    body = (isolated_journal / "001.md").read_text()
    assert "<details><summary>All candidates</summary>" in body
    assert "TfT dominates" in body
    assert "Defection emerges" in body


def test_no_details_when_single_candidate(cache, isolated_journal):
    subs = _good_substructures()
    subs["hypothesis"] = {
        "text": "Only one.",
        "candidates_considered": 1,
        "all_candidates": ["Only one."],
    }
    _stage_all(cache, "it-solo", subs)
    jw_mod.journal_writer(topic="t", iteration_id="it-solo", nara_summary="s")
    body = (isolated_journal / "001.md").read_text()
    assert "<details>" not in body
    assert "Only one." in body


# ── input + cache validation ─────────────────────────────────────────


def test_empty_topic_errors(cache, isolated_journal):
    _stage_all(cache, "it-2", _good_substructures())
    out = jw_mod.journal_writer(topic="   ", iteration_id="it-2", nara_summary="s")
    assert out["status"] == "error"
    assert any("topic" in e for e in out["errors"])
    assert not list(isolated_journal.glob("*.md"))


def test_empty_iteration_id_errors(cache, isolated_journal):
    out = jw_mod.journal_writer(topic="t", iteration_id="", nara_summary="s")
    assert out["status"] == "error"
    assert any("iteration_id" in e for e in out["errors"])


def test_cache_miss_errors(cache, isolated_journal):
    out = jw_mod.journal_writer(topic="t", iteration_id="it-missing", nara_summary="s")
    assert out["status"] == "error"
    assert any("iteration cache miss" in e for e in out["errors"])


def test_invalid_novelty_class_errors(cache, isolated_journal):
    subs = _good_substructures()
    subs["novelty"] = {**subs["novelty"], "class": "very-novel"}
    _stage_all(cache, "it-3", subs)
    out = jw_mod.journal_writer(topic="t", iteration_id="it-3", nara_summary="s")
    assert out["status"] == "error"
    assert any("novelty.class" in e for e in out["errors"])


def test_invalid_critique_verdict_errors(cache, isolated_journal):
    subs = _good_substructures()
    subs["critique"] = {**subs["critique"], "verdict": "true"}
    _stage_all(cache, "it-4", subs)
    out = jw_mod.journal_writer(topic="t", iteration_id="it-4", nara_summary="s")
    assert out["status"] == "error"
    assert any("critique.verdict" in e for e in out["errors"])


def test_missing_hypothesis_text_errors(cache, isolated_journal):
    subs = _good_substructures()
    subs["hypothesis"] = {"candidates_considered": 1, "all_candidates": []}
    _stage_all(cache, "it-5", subs)
    out = jw_mod.journal_writer(topic="t", iteration_id="it-5", nara_summary="s")
    assert out["status"] == "error"
    assert any("hypothesis.text" in e for e in out["errors"])


# ── rendering details ────────────────────────────────────────────────


def test_renders_top_neighbor_and_contradicting_citations(cache, isolated_journal):
    subs = _good_substructures()
    subs["novelty"] = {
        "class": "rediscovery",
        "rationale": "Restates a known result.",
        "top_neighbor_id": "osborne_rubinstein-chunk-831",
    }
    subs["critique"] = {
        "verdict": "restated",
        "rationale": "Same content as the cited chunk.",
        "contradicting_paper_id": "osborne_rubinstein-chunk-831",
    }
    _stage_all(cache, "it-cite", subs)
    jw_mod.journal_writer(topic="t", iteration_id="it-cite", nara_summary="s")
    body = (isolated_journal / "001.md").read_text()
    assert "top neighbor: `osborne_rubinstein-chunk-831`" in body
    assert "contradicting: `osborne_rubinstein-chunk-831`" in body


def test_caps_neighbor_list_at_10(cache, isolated_journal):
    subs = _good_substructures()
    subs["retrieval"] = {
        "k": 15,
        "neighbors": [
            {
                "doc_id": f"doc-{i}",
                "score": 0.5 - 0.01 * i,
                "source_layer": "foundational",
                "title": f"t-{i}",
            }
            for i in range(15)
        ],
    }
    _stage_all(cache, "it-cap", subs)
    jw_mod.journal_writer(topic="t", iteration_id="it-cap", nara_summary="s")
    body = (isolated_journal / "001.md").read_text()
    assert "doc-0" in body
    assert "doc-9" in body
    assert "doc-10" not in body
    assert "_(+5 more)_" in body


def test_empty_nara_summary_renders_placeholder(cache, isolated_journal):
    _stage_all(cache, "it-emp", _good_substructures())
    jw_mod.journal_writer(topic="t", iteration_id="it-emp", nara_summary="   ")
    body = (isolated_journal / "001.md").read_text()
    assert "_(no summary emitted)_" in body
