"""Tests for workers.failure_match — generation-time adopt-or-reject (P3 A6).

Hermetic + deterministic: NO real model, NO Chroma. One seam is monkeypatched —
`mine_paper_gap._embed_texts` maps a 2-char marker `[[xx]]` in each text to a
fixed vector (markers never tokenize: the regex needs 3+ chars, so they cannot
pollute the lexical layer). MOCK_LLM=1 is forced. failure_match itself does no
file I/O, so no tmp paths are needed.

Covers all three contract statuses (none / killed / paper_niche), both match
bases (load-bearing lexical Jaccard; near-identical cosine), the delta-required
rejection payload (kill_reason surfaced for the retry path), the live-cluster
firewall (open/surfaced never match), and the empty-hypothesis ValueError.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from workers import failure_match as fm
from workers import mine_paper_gap as mpg

# Orthogonal unit vectors -> cosine 0.0 across distinct markers, 1.0 for a
# shared marker (>= TAU_DUP 0.97).
VEC = {
    "h1": [1.0, 0.0, 0.0, 0.0],
    "c1": [0.0, 1.0, 0.0, 0.0],
    "c2": [0.0, 0.0, 1.0, 0.0],
    "c3": [0.0, 0.0, 0.0, 1.0],
}


def _stub_embed(texts):
    out = []
    for t in texts:
        vec = next((list(v) for key, v in VEC.items() if f"[[{key}]]" in t), None)
        out.append(vec if vec is not None else [0.5, 0.5, 0.5, 0.5])
    return out


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch):
    monkeypatch.setenv("MOCK_LLM", "1")
    monkeypatch.setattr(mpg, "_embed_texts", _stub_embed)


def _cluster(cid, *, status="killed", origin="loop", problem="", mechanism="",
             kill_reason=None, marker="c1"):
    """Contract-shaped cluster_state row; marker rides in mechanism so the
    embed stub sees it while lexical content stays controlled."""
    return {
        "cluster_id": cid,
        "status": status,
        "evidence_level": "L2",
        "elite": {
            "iteration_id": f"iter-{cid}",
            "claim": {"problem": problem, "mechanism": f"{mechanism} [[{marker}]]",
                      "predicted_effect": ""},
        },
        "members": [f"iter-{cid}"],
        "kill_reason": kill_reason,
        "reopening_condition": None,
        "origin": origin,
        "last_event_ts": "2026-08-14T00:00:00Z",
    }


HYP = "bidders shade sealed bids under valuation uncertainty [[h1]]"
KILL = {"code": "redteam_fatal_flaw", "detail": "collusion channel unmodeled"}


def test_status_none_when_nothing_matches():
    state = {"cl-1": _cluster("cl-1", problem="quantal response noise",
                              mechanism="logit tremble scaling", kill_reason=KILL)}
    out = fm.match(HYP, state)
    assert out["status"] == "none"
    assert out["matched_cluster_id"] is None
    assert out["kill_reason"] is None
    assert out["delta_required"] is False


def test_status_none_on_empty_ledger():
    assert fm.match(HYP, {})["status"] == "none"


def test_killed_match_via_lexical_returns_kill_reason_and_requires_delta():
    """Reworded restatement: orthogonal vectors (cosine 0), so ONLY the
    load-bearing lexical layer can catch it. The rejection payload carries the
    cluster's kill_reason for the _hypothesize_retry critique path."""
    state = {"cl-kill": _cluster(
        "cl-kill", status="killed", kill_reason=KILL,
        problem="bidders shade sealed bids under valuation uncertainty",
        mechanism="risk aversion drives shading")}
    out = fm.match(HYP, state)
    assert out["status"] == "killed"
    assert out["matched_cluster_id"] == "cl-kill"
    assert out["kill_reason"] == KILL
    assert out["delta_required"] is True
    assert out["match_detail"]["basis"] == "lexical_jaccard"


def test_paper_niche_match_requires_delta():
    state = {"niche-1": _cluster(
        "niche-1", status="killed", origin="paper_niche", kill_reason=None,
        problem="bidders shade sealed bids under valuation uncertainty")}
    out = fm.match(HYP, state)
    assert out["status"] == "paper_niche"
    assert out["matched_cluster_id"] == "niche-1"
    assert out["delta_required"] is True
    assert out["kill_reason"] is None  # niches carry no fabricated kill_reason


def test_cosine_layer_catches_near_identical_with_no_lexical_overlap():
    """Disjoint tokens but an identical embedding (cosine 1.0 >= TAU_DUP)."""
    state = {"cl-cos": _cluster("cl-cos", kill_reason=KILL,
                                problem="auction participants lowball offers",
                                marker="h1")}
    out = fm.match(HYP, state)
    assert out["status"] == "killed"
    assert out["match_detail"]["basis"] == "cosine_tau_dup"
    assert out["delta_required"] is True


def test_open_and_surfaced_clusters_never_match():
    """Live ideas are the novelty gate's business, not a rejection target —
    even a verbatim collision returns none."""
    verbatim = "bidders shade sealed bids under valuation uncertainty"
    state = {
        "cl-open": _cluster("cl-open", status="open", problem=verbatim, marker="h1"),
        "cl-surf": _cluster("cl-surf", status="surfaced", problem=verbatim, marker="h1"),
    }
    out = fm.match(HYP, state)
    assert out["status"] == "none"
    assert out["delta_required"] is False


def test_strongest_eligible_cluster_wins_deterministically():
    partial = "bidders shade sealed bids"  # 3/5 hyp tokens -> below full overlap
    full = "bidders shade sealed bids under valuation uncertainty"
    state = {
        "cl-b": _cluster("cl-b", problem=full, kill_reason=KILL, marker="c2"),
        "cl-a": _cluster("cl-a", problem=partial, marker="c1",
                         kill_reason={"code": "other"}),
    }
    out = fm.match(HYP, state)
    assert out["matched_cluster_id"] == "cl-b"
    assert out["kill_reason"] == KILL


def test_empty_hypothesis_raises():
    with pytest.raises(ValueError):
        fm.match("   ", {"cl-1": _cluster("cl-1", kill_reason=KILL)})
    with pytest.raises(ValueError):
        fm.match(None, {})  # type: ignore[arg-type]
