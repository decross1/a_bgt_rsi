"""Unit tests for experiments/exp004_combinatorial_auction/bundles.py.

Pure-Python model tests (bundles, valuation draw, feasible allocations,
welfare). No LLM dependency; green under MOCK_LLM.
"""
from __future__ import annotations

import random
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from experiments.exp004_combinatorial_auction.bundles import (
    BUNDLES,
    allocation_welfare,
    draw_valuation,
    feasible_allocations,
)


class BundlesConstant(unittest.TestCase):
    def test_bundles_exact(self):
        self.assertEqual(BUNDLES, [(0,), (1,), (0, 1)])


class DrawValuation(unittest.TestCase):
    def test_keys_are_the_three_bundles(self):
        v = draw_valuation(random.Random(0))
        self.assertEqual(set(v.keys()), {(0,), (1,), (0, 1)})

    def test_reproducible_with_seed(self):
        a = draw_valuation(random.Random(7))
        b = draw_valuation(random.Random(7))
        self.assertEqual(a, b)

    def test_standalone_values_in_range(self):
        rng = random.Random(123)
        for _ in range(2000):
            v = draw_valuation(rng)
            self.assertGreaterEqual(v[(0,)], 0.0)
            self.assertLessEqual(v[(0,)], 50.0)
            self.assertGreaterEqual(v[(1,)], 0.0)
            self.assertLessEqual(v[(1,)], 50.0)

    def test_pair_obeys_synergy_formula_and_nonnegative(self):
        rng = random.Random(99)
        for _ in range(2000):
            v = draw_valuation(rng)
            self.assertGreaterEqual(v[(0, 1)], 0.0)
            base = v[(0,)] + v[(1,)]
            # Synergy is U[-20, 20], floored at 0; so the pair value is
            # either exactly within [base-20, base+20], or 0.0 (the floor).
            if v[(0, 1)] > 0.0:
                self.assertGreaterEqual(v[(0, 1)], base - 20.0 - 1e-9)
                self.assertLessEqual(v[(0, 1)], base + 20.0 + 1e-9)

    def test_synergy_can_be_positive_and_negative(self):
        rng = random.Random(2024)
        pos = neg = False
        for _ in range(2000):
            v = draw_valuation(rng)
            if v[(0, 1)] > v[(0,)] + v[(1,)] + 1e-9:
                pos = True
            if 0.0 < v[(0, 1)] < v[(0,)] + v[(1,)] - 1e-9:
                neg = True
        self.assertTrue(pos, "expected some complements (positive synergy)")
        self.assertTrue(neg, "expected some substitutes (negative synergy)")


class FeasibleAllocations(unittest.TestCase):
    def test_contains_empty_allocation(self):
        allocs = feasible_allocations(2)
        self.assertIn({}, allocs)

    def test_contains_single_item_allocations(self):
        allocs = feasible_allocations(2)
        self.assertIn({0: (0,)}, allocs)
        self.assertIn({0: (1,)}, allocs)
        self.assertIn({1: (0,)}, allocs)
        self.assertIn({1: (1,)}, allocs)

    def test_contains_full_bundle_to_one_bidder(self):
        allocs = feasible_allocations(2)
        self.assertIn({0: (0, 1)}, allocs)
        self.assertIn({1: (0, 1)}, allocs)

    def test_contains_split_between_distinct_bidders(self):
        allocs = feasible_allocations(2)
        self.assertIn({0: (0,), 1: (1,)}, allocs)
        self.assertIn({1: (0,), 0: (1,)}, allocs)

    def test_never_assigns_an_item_to_two_bidders(self):
        for n in (1, 2, 3, 4):
            for alloc in feasible_allocations(n):
                seen_items: set[int] = set()
                for bundle in alloc.values():
                    for item in bundle:
                        self.assertNotIn(
                            item, seen_items,
                            f"item {item} assigned twice in {alloc}",
                        )
                        seen_items.add(item)

    def test_all_bundles_are_valid(self):
        for alloc in feasible_allocations(3):
            for bundle in alloc.values():
                self.assertIn(bundle, BUNDLES)

    def test_no_duplicate_allocations(self):
        allocs = feasible_allocations(3)
        # dicts aren't hashable; compare by sorted-items signature.
        sigs = [tuple(sorted(a.items())) for a in allocs]
        self.assertEqual(len(sigs), len(set(sigs)))


class AllocationWelfare(unittest.TestCase):
    def test_empty_allocation_is_zero(self):
        vals = [{(0,): 10.0, (1,): 20.0, (0, 1): 25.0}]
        self.assertEqual(allocation_welfare({}, vals), 0.0)

    def test_sums_winners_own_valuations(self):
        vals = [
            {(0,): 10.0, (1,): 5.0, (0, 1): 12.0},
            {(0,): 3.0, (1,): 8.0, (0, 1): 9.0},
        ]
        # bidder 0 gets item 0 (=10), bidder 1 gets item 1 (=8)
        self.assertEqual(allocation_welfare({0: (0,), 1: (1,)}, vals), 18.0)
        # bidder 0 gets the pair (=12)
        self.assertEqual(allocation_welfare({0: (0, 1)}, vals), 12.0)


if __name__ == "__main__":
    unittest.main()
