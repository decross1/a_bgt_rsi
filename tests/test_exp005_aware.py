"""Tests for exp005 mechanism-aware bidding (bidder_aware + analyze).

MOCK_LLM-safe. The aware-bidder tests monkeypatch ``call_sync`` on the bidder
module so they never hit the real Gemma (mirrors the exp003/exp004 pattern).
The analyze tests are pure-Python over a fixture.

Load-bearing assertions:
  - the aware bidder returns the 3 frozen bundle keys;
  - each of the three mechanism system prompts states its payment rule with NO
    auction-theory word (truthful / dominant / shade / strategyproof / VCG) —
    the probe is only valid if the prompt never names the answer;
  - analyze surfaces the SHADING signal: on a fixture where first_price
    residuals are negative, mean_signed_residual < 0 is reported; on vcg where
    residuals are ~0, mean_signed_residual ~ 0.
"""
import json
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from experiments.exp005_mechanism_aware import analyze
from experiments.exp005_mechanism_aware import bidder_aware as bidder_mod


BUNDLE_TUPLES = ((0,), (1,), (0, 1))
MECHANISMS = ("vcg", "first_price", "sequential_second_price")
# Theory words that must never leak into the prompt (the probe names the
# payment MECHANICS only — never the textbook answer).
FORBIDDEN = ("truthful", "dominant", "shade", "strategyproof", "vcg")


def _fake_call_sync(completion_text: str, request_id: str = "req-xyz"):
    def stub(messages, **kwargs):
        return {"completion": completion_text, "wrapper_request_id": request_id}

    return stub


def _valuation():
    return {(0,): 30.0, (1,): 40.0, (0, 1): 65.0}


# --- bidder_aware: shape ----------------------------------------------------

@pytest.mark.parametrize("mech", MECHANISMS)
def test_aware_bidder_returns_three_bundle_keys(monkeypatch, mech):
    completion = json.dumps(
        {"bids": {"A": 25, "B": 33, "AB": 55}, "reasoning": "below value"}
    )
    monkeypatch.setattr(bidder_mod, "call_sync", _fake_call_sync(completion))

    out = bidder_mod.compute_aware_bundle_bids(_valuation(), mech)

    assert set(out["bids"].keys()) == set(BUNDLE_TUPLES)
    for t in BUNDLE_TUPLES:
        assert isinstance(out["bids"][t], float)
    assert out["bids"][(0,)] == 25.0
    assert out["bids"][(1,)] == 33.0
    assert out["bids"][(0, 1)] == 55.0
    assert not out["reasoning"].startswith("parse_failure:")


def test_parse_failure_defaults_to_valuation(monkeypatch):
    completion = "no json here, just prose"
    monkeypatch.setattr(bidder_mod, "call_sync", _fake_call_sync(completion))

    val = _valuation()
    out = bidder_mod.compute_aware_bundle_bids(val, "first_price")

    assert out["bids"] == {t: float(val[t]) for t in BUNDLE_TUPLES}
    assert out["reasoning"].startswith("parse_failure:")


def test_unknown_mechanism_raises(monkeypatch):
    monkeypatch.setattr(bidder_mod, "call_sync", _fake_call_sync("{}"))
    with pytest.raises(ValueError):
        bidder_mod.compute_aware_bundle_bids(_valuation(), "english_auction")


# --- bidder_aware: NO theory leak in any mechanism prompt -------------------

@pytest.mark.parametrize("mech", MECHANISMS)
def test_mechanism_prompt_has_no_theory_words(mech):
    blob = (
        bidder_mod.system_prompt_for(mech) + bidder_mod._FORMAT_INSTRUCTION
    ).lower()
    for forbidden in FORBIDDEN:
        assert forbidden not in blob, (
            f"theory word {forbidden!r} leaked into {mech} prompt"
        )


def test_payment_rules_actually_differ():
    # The whole point of exp005: each mechanism states a DIFFERENT payment rule.
    prompts = {m: bidder_mod.system_prompt_for(m) for m in MECHANISMS}
    assert len(set(prompts.values())) == len(MECHANISMS)


# --- analyze: the SHADING signal is visible ---------------------------------

def _block(residuals, reasonings):
    return {
        "bids": [{"(0,)": 1.0, "(1,)": 1.0, "(0, 1)": 1.0}],
        "residuals": residuals,
        "reasonings": reasonings,
        "allocative_efficiency": 0.95,
        "revenue": 10.0,
    }


def _write_fixture(path: Path) -> None:
    # first_price: clearly NEGATIVE residuals (shading). vcg: ~0 residuals
    # (truthful). No parse failures in either -> both valid.
    fp_resid = [-8.0, -6.0, -10.0, -7.0, -9.0, -5.0]
    vcg_resid = [0.5, -1.0, 0.0, 1.0, -0.5, 0.0]
    ok = ["computed bid", "computed bid"]
    rows = [
        {
            "trial": i,
            "valuations": [{"(0,)": 29.0, "(1,)": 22.0, "(0, 1)": 55.0}],
            "mechanisms": {
                "first_price": _block(fp_resid, ok),
                "vcg": _block(vcg_resid, ok),
            },
        }
        for i in range(4)
    ]
    with open(path, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def test_first_price_mean_signed_residual_is_negative():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "trials.jsonl"
        _write_fixture(path)
        rows = analyze._load_rows(path)
        summary = analyze.build_summary(rows)
        by_name = {m["mechanism"]: m for m in summary["per_mechanism"]}

        fp = by_name["first_price"]
        # The shading signal: negative mean signed residual.
        assert fp["mean_signed_residual"] < 0
        assert fp["parse_failure_rate"] == 0.0
        # Bids are clearly below value -> NOT truthful at eps=5.
        assert fp["verdict"] == "NO"

        vcg = by_name["vcg"]
        # Truthful: residuals ~0 -> mean near 0 and YES verdict.
        assert abs(vcg["mean_signed_residual"]) < 1.0
        assert vcg["verdict"] == "YES"


def test_parse_failure_gate_overrides_and_masks_shading():
    # A first_price block whose residuals would read as shading, but most calls
    # are parse failures -> verdict INVALID, never silently passed/failed clean.
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "trials.jsonl"
        rows = [
            {
                "trial": i,
                "valuations": [{"(0,)": 29.0, "(1,)": 22.0, "(0, 1)": 55.0}],
                "mechanisms": {
                    "first_price": _block(
                        [0.0, 0.0, 0.0, 0.0],
                        ["parse_failure: x", "parse_failure: y", "ok"],
                    ),
                },
            }
            for i in range(3)
        ]
        with open(path, "w") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        rows = analyze._load_rows(path)
        summary = analyze.build_summary(rows)
        fp = summary["per_mechanism"][0]
        assert fp["parse_failure_rate"] > analyze.PARSE_FAILURE_GATE
        assert fp["verdict"] == "INVALID"


def test_summary_json_schema_includes_mean_signed_residual():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "trials.jsonl"
        _write_fixture(path)
        rows = analyze._load_rows(path)
        pub = analyze._public_summary(analyze.build_summary(rows))
        assert pub["n_trials"] == 4
        for entry in pub["per_mechanism"]:
            assert set(entry.keys()) == {
                "mechanism",
                "truthful_fraction",
                "mean_signed_residual",
                "parse_failure_rate",
                "verdict",
            }
