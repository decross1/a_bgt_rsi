"""Tests for workers.journal_writer (the Part-2 full version)."""
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from workers import journal_writer as jw_mod


def _good_inputs():
    return dict(
        topic="LLM cooperation in repeated PD",
        hypothesis={
            "text": "Cooperation rises with binding compute constraints.",
            "candidates_considered": 3,
            "all_candidates": [
                "Cooperation rises with binding compute constraints.",
                "TfT dominates above a threshold context window.",
                "Defection emerges above a critical reasoning depth.",
            ],
        },
        retrieval={
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
        novelty={
            "class": "novel",
            "rationale": "No retrieved chunk addresses this claim.",
            "top_neighbor_id": "osborne_rubinstein-chunk-831",
        },
        critique={
            "verdict": "survives",
            "rationale": "Nothing in the retrieved set contradicts.",
            "contradicting_paper_id": None,
        },
        nara_summary="Nara: A candidate worth investigating further.",
    )


@pytest.fixture
def isolated_journal(tmp_path, monkeypatch):
    """Redirect the journal-write target to tmp_path so tests don't
    accumulate entries in the real repo."""
    monkeypatch.setattr(jw_mod, "JOURNAL_DIR", tmp_path / "journal" / "iterations")
    return tmp_path / "journal" / "iterations"


def test_writes_markdown_and_returns_path(isolated_journal):
    out = jw_mod.journal_writer(**_good_inputs(), parent_request_id="p1")
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


def test_increments_iteration_number(isolated_journal):
    inputs = _good_inputs()
    out1 = jw_mod.journal_writer(**inputs)
    out2 = jw_mod.journal_writer(**inputs)
    out3 = jw_mod.journal_writer(**inputs)
    assert out1["result"]["iteration_number"] == 1
    assert out2["result"]["iteration_number"] == 2
    assert out3["result"]["iteration_number"] == 3
    assert (isolated_journal / "003.md").exists()


def test_renders_all_candidates_when_more_than_one(isolated_journal):
    out = jw_mod.journal_writer(**_good_inputs())
    body = (isolated_journal / "001.md").read_text()
    assert "<details><summary>All candidates</summary>" in body
    assert "TfT dominates" in body  # the 2nd candidate
    assert "Defection emerges" in body  # the 3rd


def test_no_details_when_single_candidate(isolated_journal):
    inputs = _good_inputs()
    inputs["hypothesis"] = {
        "text": "Only one.",
        "candidates_considered": 1,
        "all_candidates": ["Only one."],
    }
    jw_mod.journal_writer(**inputs)
    body = (isolated_journal / "001.md").read_text()
    assert "<details>" not in body
    assert "Only one." in body


def test_empty_topic_errors(isolated_journal):
    inputs = _good_inputs()
    inputs["topic"] = "   "
    out = jw_mod.journal_writer(**inputs)
    assert out["status"] == "error"
    assert any("topic" in e for e in out["errors"])
    assert not list(isolated_journal.glob("*.md"))


def test_invalid_novelty_class_errors(isolated_journal):
    inputs = _good_inputs()
    inputs["novelty"] = {**inputs["novelty"], "class": "very-novel"}
    out = jw_mod.journal_writer(**inputs)
    assert out["status"] == "error"
    assert any("novelty.class" in e for e in out["errors"])


def test_invalid_critique_verdict_errors(isolated_journal):
    inputs = _good_inputs()
    inputs["critique"] = {**inputs["critique"], "verdict": "true"}
    out = jw_mod.journal_writer(**inputs)
    assert out["status"] == "error"
    assert any("critique.verdict" in e for e in out["errors"])


def test_missing_hypothesis_text_errors(isolated_journal):
    inputs = _good_inputs()
    inputs["hypothesis"] = {"candidates_considered": 1, "all_candidates": []}
    out = jw_mod.journal_writer(**inputs)
    assert out["status"] == "error"
    assert any("hypothesis.text" in e for e in out["errors"])


def test_non_dict_substructure_errors(isolated_journal):
    inputs = _good_inputs()
    inputs["retrieval"] = "not a dict"
    out = jw_mod.journal_writer(**inputs)
    assert out["status"] == "error"


def test_renders_top_neighbor_and_contradicting_citations(isolated_journal):
    inputs = _good_inputs()
    inputs["novelty"] = {
        "class": "rediscovery",
        "rationale": "Restates a known result.",
        "top_neighbor_id": "osborne_rubinstein-chunk-831",
    }
    inputs["critique"] = {
        "verdict": "restated",
        "rationale": "Same content as the cited chunk.",
        "contradicting_paper_id": "osborne_rubinstein-chunk-831",
    }
    jw_mod.journal_writer(**inputs)
    body = (isolated_journal / "001.md").read_text()
    assert "top neighbor: `osborne_rubinstein-chunk-831`" in body
    assert "contradicting: `osborne_rubinstein-chunk-831`" in body


def test_caps_neighbor_list_at_10(isolated_journal):
    inputs = _good_inputs()
    inputs["retrieval"] = {
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
    jw_mod.journal_writer(**inputs)
    body = (isolated_journal / "001.md").read_text()
    assert "doc-0" in body
    assert "doc-9" in body
    assert "doc-10" not in body
    assert "_(+5 more)_" in body


def test_empty_nara_summary_renders_placeholder(isolated_journal):
    inputs = _good_inputs()
    inputs["nara_summary"] = "   "
    jw_mod.journal_writer(**inputs)
    body = (isolated_journal / "001.md").read_text()
    assert "_(no summary emitted)_" in body
