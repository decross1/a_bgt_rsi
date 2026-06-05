"""Tests for exp006 — the semi-synthetic mechanism-DESIGN tier.

This IS the genuine semi-synthetic mechanism-DESIGN tier: the LLM designs
the mechanism (allocation + payments) and the design is scored against the
VCG benchmark (no single ground-truth output). These tests label it as such.

Strategy: monkeypatch the designer's ``call_sync`` (imported into
``experiments.exp004_combinatorial_auction.mechanism_designer``) so no real
Gemma is hit — MOCK_LLM stubs embedders only, not the model. We script the
designer's completion and assert the run + analyze + verdict pipeline:

  - a scripted EFFICIENT + FEASIBLE design  -> verdict YES,
  - a scripted INFEASIBLE / garbage design  -> feasibility is COUNTED, the
    near-miss is NOT coerced into a YES (validate discipline),
  - the loop_bridge metric/topic are derived from the design results.
"""
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from experiments.exp004_combinatorial_auction import mechanism_designer
from experiments.exp006_mechanism_design import analyze as analyze_mod
from experiments.exp006_mechanism_design import loop_bridge as bridge_mod
from experiments.exp006_mechanism_design import run as run_mod


# Valuations whose unique welfare-maximizing allocation is item A -> bidder 0,
# item B -> bidder 1 (optimal welfare 80.0; VCG picks {0:(0,), 1:(1,)}).
_VALS = [
    {(0,): 40.0, (1,): 5.0, (0, 1): 45.0},
    {(0,): 5.0, (1,): 40.0, (0, 1): 45.0},
    {(0,): 1.0, (1,): 1.0, (0, 1): 2.0},
]


def _fake_call_sync(completion_text: str):
    """call_sync stub returning a logged record with the given completion."""
    def stub(messages, *, temperature=0.0, top_p=1.0, seed=None, max_tokens=None,
             caller_tag="unspecified", parent_request_id=None,
             retrieval_context=None, log_path=None, model=None, backend=None):
        return {
            "request_id": "req-exp006",
            "completion": completion_text,
            "model": "gemma-4-26b-a4b",
            "model_version": "test",
            "caller_tag": caller_tag,
            "usage": {"input_tokens": 100, "output_tokens": 50},
            "latency_ms": 100.0,
        }
    return stub


# --- scripted designer completions ---------------------------------------

# Efficient + feasible: A->0, B->1. Matches the VCG allocation exactly.
_EFFICIENT_JSON = json.dumps({
    "allocation": {"0": [0], "1": [1]},
    "payments": {"0": 5.0, "1": 5.0, "2": 0.0},
    "reasoning": "Give each buyer the single item they value most.",
})

# Infeasible: item 0 is handed to BOTH bidder 0 (in the pair) and bidder 1.
_INFEASIBLE_JSON = json.dumps({
    "allocation": {"0": [0, 1], "1": [0]},
    "payments": {"0": 1.0, "1": 1.0},
    "reasoning": "Sell aggressively.",
})

# Garbage: not JSON at all -> observable parse failure.
_GARBAGE = "I cannot decide. Sorry!"


def test_label_is_honest_semi_synthetic_design_tier():
    """The module docstrings must name this the semi-synthetic mechanism-
    DESIGN tier, scored against VCG — not mislabel it as a synthetic rung."""
    for mod in (run_mod, analyze_mod, bridge_mod):
        doc = (mod.__doc__ or "").lower()
        assert "mechanism-design" in doc or "mechanism design" in doc, mod.__name__
    assert "vcg" in (run_mod.__doc__ or "").lower()


def test_efficient_feasible_design_yields_yes(tmp_path, monkeypatch):
    """A scripted efficient + feasible proposal -> efficiency 1.0,
    feasibility 1.0, verdict YES."""
    monkeypatch.setattr(mechanism_designer, "call_sync",
                        _fake_call_sync(_EFFICIENT_JSON))

    proposal = mechanism_designer.propose_allocation(
        [dict(v) for v in _VALS])
    score = mechanism_designer.score_proposal(proposal, _VALS)
    assert score["is_feasible"] is True
    assert score["efficiency"] == pytest.approx(1.0)
    assert score["matches_vcg_alloc"] is True

    # Drive analyze.py over a 1-trial JSONL and check the verdict.
    trials = tmp_path / "trials.jsonl"
    row = {
        "trial": 0,
        "valuations": [run_mod._jsonable_bundle_dict(v) for v in _VALS],
        "proposal": {
            "allocation": run_mod._jsonable_alloc(proposal["allocation"]),
            "payments": run_mod._jsonable_payments(proposal["payments"]),
            "reasoning": proposal["reasoning"],
            "raw": proposal["raw"],
        },
        "efficiency": score["efficiency"],
        "is_feasible": score["is_feasible"],
        "matches_vcg_alloc": score["matches_vcg_alloc"],
    }
    trials.write_text(json.dumps(row) + "\n")
    summary_md = tmp_path / "summary.md"
    summary_json = tmp_path / "summary.json"
    monkeypatch.setattr(analyze_mod, "TRIALS_PATH", trials)
    monkeypatch.setattr(analyze_mod, "SUMMARY_MD_PATH", summary_md)
    monkeypatch.setattr(analyze_mod, "SUMMARY_JSON_PATH", summary_json)

    rc = analyze_mod.main()
    assert rc == 0
    out = json.loads(summary_json.read_text())
    assert out["verdict"] == "YES"
    assert out["designer_mean_efficiency"] == pytest.approx(1.0)
    assert out["feasibility_rate"] == pytest.approx(1.0)
    assert out["matches_vcg_rate"] == pytest.approx(1.0)


def test_infeasible_design_is_counted_not_coerced(tmp_path, monkeypatch):
    """A scripted infeasible proposal: feasibility is counted as failure and
    the verdict is NOT coerced to YES. With every design infeasible the
    feasibility_rate hits 0.0, which gates the verdict to INVALID rather than
    silently passing a near-optimal-looking efficiency number."""
    monkeypatch.setattr(mechanism_designer, "call_sync",
                        _fake_call_sync(_INFEASIBLE_JSON))

    proposal = mechanism_designer.propose_allocation(
        [dict(v) for v in _VALS])
    score = mechanism_designer.score_proposal(proposal, _VALS)
    assert score["is_feasible"] is False  # item 0 sold twice

    trials = tmp_path / "trials.jsonl"
    row = {
        "trial": 0,
        "valuations": [run_mod._jsonable_bundle_dict(v) for v in _VALS],
        "proposal": {
            "allocation": run_mod._jsonable_alloc(proposal["allocation"]),
            "payments": run_mod._jsonable_payments(proposal["payments"]),
            "reasoning": proposal["reasoning"],
            "raw": proposal["raw"],
        },
        "efficiency": score["efficiency"],
        "is_feasible": score["is_feasible"],
        "matches_vcg_alloc": score["matches_vcg_alloc"],
    }
    trials.write_text(json.dumps(row) + "\n")
    summary_md = tmp_path / "summary.md"
    summary_json = tmp_path / "summary.json"
    monkeypatch.setattr(analyze_mod, "TRIALS_PATH", trials)
    monkeypatch.setattr(analyze_mod, "SUMMARY_MD_PATH", summary_md)
    monkeypatch.setattr(analyze_mod, "SUMMARY_JSON_PATH", summary_json)

    analyze_mod.main()
    out = json.loads(summary_json.read_text())
    assert out["feasibility_rate"] == pytest.approx(0.0)
    assert out["verdict"] != "YES"          # never coerced into a pass
    assert out["verdict"] == "INVALID"      # gated: efficiency mean unreliable


def test_garbage_completion_is_observable_parse_failure(monkeypatch):
    """A non-JSON completion is an observable parse failure: reasoning starts
    with 'parse_failure', the design is infeasible, and it is not coerced."""
    monkeypatch.setattr(mechanism_designer, "call_sync",
                        _fake_call_sync(_GARBAGE))
    proposal = mechanism_designer.propose_allocation(
        [dict(v) for v in _VALS])
    assert proposal["reasoning"].startswith("parse_failure")
    score = mechanism_designer.score_proposal(proposal, _VALS)
    assert score["is_feasible"] is False


def test_run_one_trial_uses_truthful_bids(monkeypatch):
    """run._run_one_trial must feed the designer the TRUTHFUL bids
    (bids == valuations). We capture the bid_profile the designer sees."""
    seen = {}

    def capture_propose(bid_profile, **kw):
        seen["profile"] = bid_profile
        return {
            "allocation": {0: (0,), 1: (1,)},
            "payments": {0: 5.0, 1: 5.0},
            "raw": _EFFICIENT_JSON,
            "reasoning": "ok",
        }

    monkeypatch.setattr(run_mod, "propose_allocation", capture_propose)
    import random
    rng = random.Random(123)
    row = run_mod._run_one_trial(
        0, n_bidders=3, rng=rng, backend=None, model=None,
        temperature=0.2, log_path=None)
    # The reported bid profile equals the drawn valuations exactly.
    assert seen["profile"] == row_valuations_back(row)
    assert row["is_feasible"] is True


def row_valuations_back(row):
    """Reconstruct the bundle-tuple-keyed valuations from a serialized row."""
    from experiments.exp004_combinatorial_auction.bundles import BUNDLES
    out = []
    for v in row["valuations"]:
        out.append({b: v[str(b)] for b in BUNDLES})
    return out


def test_loop_bridge_metric_and_topic(tmp_path, monkeypatch):
    """loop_bridge derives METRIC_NAME=designer_mean_efficiency from
    summary.json and builds a semi-synthetic-tier topic seed."""
    summary_json = tmp_path / "summary.json"
    summary_md = tmp_path / "summary.md"
    summary_md.write_text("# exp006\n")
    summary_json.write_text(json.dumps({
        "verdict": "YES",
        "designer_mean_efficiency": 0.97,
        "feasibility_rate": 1.0,
    }))
    monkeypatch.setattr(bridge_mod, "SUMMARY_JSON_PATH", summary_json)
    monkeypatch.setattr(bridge_mod, "SUMMARY_MD_PATH", summary_md)
    monkeypatch.setattr(bridge_mod, "TRIALS_PATH", tmp_path / "nope.jsonl")

    outcome = bridge_mod.build_experiment_outcome()
    assert outcome["experiment_id"] == "exp006_mechanism_design"
    assert outcome["metric"] == "designer_mean_efficiency"
    assert outcome["value"] == pytest.approx(0.97)
    topic = bridge_mod.build_topic_seed(outcome)
    assert "mechanism designer" in topic.lower()
    assert "97" in topic  # the efficiency percentage is threaded in
