"""Tests for experiments/exp004_combinatorial_auction/mechanism_designer.py.

This is the mechanism-DESIGNER probe (the exploratory semi-synthetic seed):
can an LLM choose an "efficient and fair" combinatorial-auction outcome when
never told VCG? The module under test calls the LLM via call_sync and scores
the result against the KNOWN optimum.

The LLM path is exercised with a monkeypatched call_sync — NO real model is
hit (mirrors tests/test_hypothesize.py / the exp003 bidder pattern).

The frozen-contract siblings the module imports — bundles, efficiency, and
mechanisms.vcg — are owned by parallel build components and may not exist on
disk yet. To keep this test self-contained and green, we inject minimal,
CONTRACT-FAITHFUL stub modules into sys.modules BEFORE importing the module
under test. The stubs implement exactly the frozen exp004 interface, so when
the real siblings land the import resolves to identical behavior.
"""
from __future__ import annotations

import importlib
import itertools
import json
import random
import sys
import types
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

PKG = "experiments.exp004_combinatorial_auction"

# Canonical frozen contract.
_BUNDLES = [(0,), (1,), (0, 1)]


# ── contract-faithful stub siblings ──────────────────────────────────────


def _install_stub_siblings() -> None:
    """Install bundles / efficiency / mechanisms.vcg stubs into sys.modules
    iff the real modules are not importable. The stubs implement the frozen
    exp004 contract verbatim."""

    def _feasible_allocations(n_bidders):
        # Each allocation maps a subset of bidders -> disjoint bundles;
        # includes the empty (nothing-sold) allocation.
        allocs = [{}]
        # one bidder gets (0,1)
        for i in range(n_bidders):
            allocs.append({i: (0, 1)})
        # item 0 -> i, item 1 -> j (i may equal j -> that bidder gets both)
        for i in range(n_bidders):
            for j in range(n_bidders):
                if i == j:
                    allocs.append({i: (0, 1)})
                else:
                    allocs.append({i: (0,), j: (1,)})
        # single item sold, the other unsold
        for i in range(n_bidders):
            allocs.append({i: (0,)})
            allocs.append({i: (1,)})
        # dedupe
        seen = []
        for a in allocs:
            key = tuple(sorted((k, v) for k, v in a.items()))
            if key not in {tuple(sorted((k, v) for k, v in s.items())) for s in seen}:
                seen.append(a)
        return seen

    def _allocation_welfare(alloc, valuations):
        return sum(valuations[i][bundle] for i, bundle in alloc.items())

    def _draw_valuation(rng):
        a = rng.uniform(0, 50)
        b = rng.uniform(0, 50)
        both = max(0.0, a + b + rng.uniform(-20, 20))
        return {(0,): a, (1,): b, (0, 1): both}

    # --- bundles stub ---
    try:
        importlib.import_module(f"{PKG}.bundles")
    except Exception:
        bundles_mod = types.ModuleType(f"{PKG}.bundles")
        bundles_mod.BUNDLES = [tuple(b) for b in _BUNDLES]
        bundles_mod.draw_valuation = _draw_valuation
        bundles_mod.feasible_allocations = _feasible_allocations
        bundles_mod.allocation_welfare = _allocation_welfare
        sys.modules[f"{PKG}.bundles"] = bundles_mod

    # --- efficiency stub ---
    try:
        importlib.import_module(f"{PKG}.efficiency")
    except Exception:
        eff_mod = types.ModuleType(f"{PKG}.efficiency")

        def _optimal_welfare(valuations):
            return max(
                _allocation_welfare(a, valuations)
                for a in _feasible_allocations(len(valuations))
            )

        def _realized_welfare(allocation, valuations):
            return _allocation_welfare(allocation, valuations)

        def _allocative_efficiency(allocation, valuations):
            opt = _optimal_welfare(valuations)
            if opt == 0:
                return 1.0
            return _realized_welfare(allocation, valuations) / opt

        eff_mod.optimal_welfare = _optimal_welfare
        eff_mod.realized_welfare = _realized_welfare
        eff_mod.allocative_efficiency = _allocative_efficiency
        sys.modules[f"{PKG}.efficiency"] = eff_mod

    # --- mechanisms package + vcg stub ---
    try:
        importlib.import_module(f"{PKG}.mechanisms.vcg")
    except Exception:
        if f"{PKG}.mechanisms" not in sys.modules:
            mech_pkg = types.ModuleType(f"{PKG}.mechanisms")
            mech_pkg.__path__ = []  # mark as package
            sys.modules[f"{PKG}.mechanisms"] = mech_pkg
        vcg_mod = types.ModuleType(f"{PKG}.mechanisms.vcg")

        def _clear(bid_profile, *, rng=None):
            rng = rng or random.Random(0)
            allocs = _feasible_allocations(len(bid_profile))
            best_w = None
            best = []
            for a in allocs:
                w = _allocation_welfare(a, bid_profile)
                if best_w is None or w > best_w:
                    best_w, best = w, [a]
                elif w == best_w:
                    best.append(a)
            chosen = best[0] if len(best) == 1 else rng.choice(best)
            return {
                "allocation": chosen,
                "payments": {i: 0.0 for i in chosen},
                "revenue": 0.0,
                "mechanism": "vcg-stub",
            }

        vcg_mod.clear = _clear
        sys.modules[f"{PKG}.mechanisms.vcg"] = vcg_mod


_install_stub_siblings()

# Import the module under test AFTER stubs are installed.
from experiments.exp004_combinatorial_auction import mechanism_designer as md  # noqa: E402


# ── call_sync stub ────────────────────────────────────────────────────────


def _fake_call_sync(completion_text: str):
    """Build a call_sync stub returning a logged-record dict with the given
    completion. Accepts the full call_sync kwarg surface."""

    def stub(messages, *, temperature=0.0, top_p=1.0, seed=None, max_tokens=None,
             caller_tag="unspecified", parent_request_id=None,
             retrieval_context=None, log_path=None, model=None, backend=None):
        return {
            "request_id": "req-md-test",
            "completion": completion_text,
            "model": "gemma-4-26b-a4b",
            "model_version": "test",
            "parent_request_id": parent_request_id,
            "caller_tag": caller_tag,
            "usage": {"input_tokens": 120, "output_tokens": 60},
            "latency_ms": 100.0,
        }

    return stub


# A 2-bidder profile with a clear efficient allocation: bidder 0 strongly
# prefers item A alone, bidder 1 strongly prefers item B alone. Splitting the
# items (0->bidder0, 1->bidder1) is the welfare-maximizing outcome.
_VALS = [
    {(0,): 40.0, (1,): 5.0, (0, 1): 44.0},
    {(0,): 5.0, (1,): 40.0, (0, 1): 44.0},
]


class ProposeAllocation(unittest.TestCase):
    def setUp(self):
        self._orig = md.call_sync

    def tearDown(self):
        md.call_sync = self._orig

    def test_neutral_prompt_omits_vcg_vocabulary(self):
        md.call_sync = _fake_call_sync(
            json.dumps({"allocation": {"0": [0], "1": [1]},
                        "payments": {"0": 5.0, "1": 5.0},
                        "reasoning": "split"})
        )
        captured = {}
        orig = md.call_sync

        def spy(messages, **kw):
            captured["messages"] = messages
            return orig(messages, **kw)

        md.call_sync = spy
        md.propose_allocation(_VALS)
        text = " ".join(m["content"] for m in captured["messages"]).lower()
        for forbidden in ("vcg", "vickrey", "clarke", "groves", "second-price",
                           "truthful", "dominant strateg"):
            self.assertNotIn(forbidden, text)

    def test_clean_json_proposal_parsed(self):
        md.call_sync = _fake_call_sync(
            json.dumps({"allocation": {"0": [0], "1": [1]},
                        "payments": {"0": 5.0, "1": 5.0},
                        "reasoning": "give A to 0, B to 1"})
        )
        out = md.propose_allocation(_VALS)
        self.assertEqual(out["allocation"], {0: (0,), 1: (1,)})
        self.assertEqual(out["payments"], {0: 5.0, 1: 5.0})
        self.assertEqual(out["reasoning"], "give A to 0, B to 1")

    def test_json_wrapped_in_prose_parsed(self):
        md.call_sync = _fake_call_sync(
            'Sure, here is my plan: {"allocation": {"0": [0, 1]}, '
            '"payments": {"0": 30.0}, "reasoning": "bundle to 0"} done.'
        )
        out = md.propose_allocation(_VALS)
        self.assertEqual(out["allocation"], {0: (0, 1)})

    def test_empty_profile_raises(self):
        md.call_sync = _fake_call_sync("{}")
        with self.assertRaises(ValueError):
            md.propose_allocation([])


class ScoreProposal(unittest.TestCase):
    def test_efficient_split_scores_in_range_and_feasible(self):
        proposal = {
            "allocation": {0: (0,), 1: (1,)},
            "payments": {0: 5.0, 1: 5.0},
            "raw": "...",
            "reasoning": "split",
        }
        score = md.score_proposal(proposal, _VALS)
        self.assertTrue(0.0 <= score["efficiency"] <= 1.0)
        self.assertTrue(score["is_feasible"])
        # the split is the optimum here -> efficiency 1.0
        self.assertAlmostEqual(score["efficiency"], 1.0, places=6)

    def test_matches_vcg_alloc_true_for_optimal_split(self):
        proposal = {
            "allocation": {0: (0,), 1: (1,)},
            "payments": {0: 5.0, 1: 5.0},
            "raw": "...",
            "reasoning": "split",
        }
        score = md.score_proposal(proposal, _VALS)
        self.assertTrue(score["matches_vcg_alloc"])

    def test_suboptimal_feasible_allocation_lower_efficiency(self):
        # Giving the whole bundle to bidder 0: welfare 44 vs optimum 80.
        proposal = {
            "allocation": {0: (0, 1)},
            "payments": {0: 44.0},
            "raw": "...",
            "reasoning": "bundle",
        }
        score = md.score_proposal(proposal, _VALS)
        self.assertTrue(score["is_feasible"])
        self.assertTrue(0.0 <= score["efficiency"] < 1.0)
        self.assertFalse(score["matches_vcg_alloc"])

    def test_infeasible_double_sold_item_not_coerced(self):
        # Both bidders allotted item 0 -> item sold twice -> infeasible.
        proposal = {
            "allocation": {0: (0,), 1: (0,)},
            "payments": {0: 5.0, 1: 5.0},
            "raw": "...",
            "reasoning": "double",
        }
        score = md.score_proposal(proposal, _VALS)
        self.assertFalse(score["is_feasible"])
        self.assertTrue(0.0 <= score["efficiency"] <= 1.0)

    def test_parse_failure_yields_infeasible_not_coerced(self):
        # A malformed completion: propose_allocation must mark it observable
        # AND score_proposal must report is_feasible False (rule 4: no coercion).
        bad = "I think buyer 0 should probably get item A. (no JSON here)"
        md_call_orig = md.call_sync
        md.call_sync = _fake_call_sync(bad)
        try:
            proposal = md.propose_allocation(_VALS)
        finally:
            md.call_sync = md_call_orig
        self.assertEqual(proposal["allocation"], {})
        self.assertTrue(proposal["reasoning"].startswith("parse_failure"))
        score = md.score_proposal(proposal, _VALS)
        self.assertFalse(score["is_feasible"])

    def test_invalid_bundle_in_completion_is_parse_failure(self):
        # Bundle [2] is not a valid item -> allocation parse fails, observable.
        md_call_orig = md.call_sync
        md.call_sync = _fake_call_sync(
            json.dumps({"allocation": {"0": [2]}, "payments": {}, "reasoning": "x"})
        )
        try:
            proposal = md.propose_allocation(_VALS)
        finally:
            md.call_sync = md_call_orig
        self.assertEqual(proposal["allocation"], {})
        self.assertTrue(proposal["reasoning"].startswith("parse_failure"))
        score = md.score_proposal(proposal, _VALS)
        self.assertFalse(score["is_feasible"])


if __name__ == "__main__":
    unittest.main()
