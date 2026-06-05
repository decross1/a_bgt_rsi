"""Unit tests for experiments/exp004_combinatorial_auction/efficiency.py.

Pure-mechanics tests: allocative-efficiency arithmetic over a KNOWN
optimal allocation. No LLM dependency (runs green under MOCK_LLM).

``efficiency.py`` imports ``feasible_allocations`` / ``allocation_welfare``
from the FROZEN ``bundles`` contract. ``bundles.py`` is a parallel
component that may not be merged when this test runs, so we install a
faithful in-memory module implementing that exact frozen interface into
``sys.modules`` BEFORE importing ``efficiency``. The real ``bundles.py``
honors the same contract, so these tests pin ``efficiency`` behaviour
without depending on the sibling component's merge order.
"""
from __future__ import annotations

import itertools
import sys
import types
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# --- Frozen bundles contract, implemented in-memory for the test ----------
BUNDLES = [(0,), (1,), (0, 1)]


def _allocation_welfare(alloc: dict, valuations: list[dict]) -> float:
    return sum(valuations[i][bundle] for i, bundle in alloc.items())


def _feasible_allocations(n_bidders: int) -> list[dict]:
    """Every allocation of disjoint bundles to bidders, incl. empty/partial.

    For each bidder a choice of one of the three bundles or "nothing";
    keep only profiles whose assigned bundles are pairwise item-disjoint
    across winners.
    """
    options = [None] + BUNDLES  # None == bidder wins nothing
    out: list[dict] = []
    for combo in itertools.product(options, repeat=n_bidders):
        used: set[int] = set()
        ok = True
        alloc: dict = {}
        for idx, bundle in enumerate(combo):
            if bundle is None:
                continue
            items = set(bundle)
            if used & items:
                ok = False
                break
            used |= items
            alloc[idx] = bundle
        if ok:
            out.append(alloc)
    return out


_bundles_mod = types.ModuleType(
    "experiments.exp004_combinatorial_auction.bundles"
)
_bundles_mod.BUNDLES = BUNDLES
_bundles_mod.allocation_welfare = _allocation_welfare
_bundles_mod.feasible_allocations = _feasible_allocations
sys.modules["experiments.exp004_combinatorial_auction.bundles"] = _bundles_mod

from experiments.exp004_combinatorial_auction.efficiency import (  # noqa: E402
    allocative_efficiency,
    optimal_welfare,
    realized_welfare,
)

# efficiency has bound its bundles imports above; remove the stub so the real
# bundles.py (which also exposes draw_valuation) loads for other test modules
# (e.g. test_exp006_design). Without this the stub leaks and breaks collection.
sys.modules.pop("experiments.exp004_combinatorial_auction.bundles", None)


class OptimalWelfare(unittest.TestCase):
    def test_known_optimum_two_bidders(self):
        """Hand example with a known welfare-maximizing allocation.

        Bidder 0 values item 0 highly; bidder 1 values item 1 highly;
        neither wants the pair. The optimum splits the items: 0->(0,),
        1->(1,), welfare = 40 + 35 = 75.
        """
        valuations = [
            {(0,): 40.0, (1,): 5.0, (0, 1): 42.0},
            {(0,): 3.0, (1,): 35.0, (0, 1): 36.0},
        ]
        self.assertEqual(optimal_welfare(valuations), 75.0)

    def test_grand_bundle_optimum(self):
        """When one bidder values the pair above any split, optimum = pair."""
        valuations = [
            {(0,): 10.0, (1,): 10.0, (0, 1): 90.0},
            {(0,): 8.0, (1,): 8.0, (0, 1): 12.0},
        ]
        # Best split: 0->(0,)=10, 1->(1,)=8 => 18. Grand bundle to 0 => 90.
        self.assertEqual(optimal_welfare(valuations), 90.0)


class RealizedAndEfficiency(unittest.TestCase):
    def setUp(self):
        self.valuations = [
            {(0,): 40.0, (1,): 5.0, (0, 1): 42.0},
            {(0,): 3.0, (1,): 35.0, (0, 1): 36.0},
        ]

    def test_efficiency_ratio_in_unit_interval(self):
        # Suboptimal: give both items to bidder 0 as the grand bundle (42),
        # leaving bidder 1 nothing. Optimal is the 0->(0,),1->(1,) split (75).
        alloc = {0: (0, 1)}
        self.assertEqual(realized_welfare(alloc, self.valuations), 42.0)
        eff = allocative_efficiency(alloc, self.valuations)
        self.assertAlmostEqual(eff, 42.0 / 75.0)
        self.assertGreaterEqual(eff, 0.0)
        self.assertLessEqual(eff, 1.0)

    def test_optimal_allocation_efficiency_is_one(self):
        alloc = {0: (0,), 1: (1,)}
        self.assertEqual(realized_welfare(alloc, self.valuations), 75.0)
        self.assertEqual(allocative_efficiency(alloc, self.valuations), 1.0)

    def test_empty_allocation_efficiency_is_zero(self):
        # Nothing sold while positive welfare was available -> 0.0, no error.
        self.assertEqual(realized_welfare({}, self.valuations), 0.0)
        self.assertEqual(allocative_efficiency({}, self.valuations), 0.0)


class DegenerateZeroOptimum(unittest.TestCase):
    def test_zero_optimum_efficiency_is_one_no_div0(self):
        """optimal_welfare == 0 -> efficiency defined as 1.0, no ZeroDivision."""
        valuations = [
            {(0,): 0.0, (1,): 0.0, (0, 1): 0.0},
            {(0,): 0.0, (1,): 0.0, (0, 1): 0.0},
        ]
        self.assertEqual(optimal_welfare(valuations), 0.0)
        eff = allocative_efficiency({0: (0,), 1: (1,)}, valuations)
        self.assertEqual(eff, 1.0)


if __name__ == "__main__":
    unittest.main()
