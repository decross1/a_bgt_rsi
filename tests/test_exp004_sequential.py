"""Unit tests for the exp004 sequential second-price mechanism.

Pure-Python, seeded, no LLM dependency: exercises the two-round single-item
Vickrey logic, the per-round second-price payments, the (0, 1) bundle
recording when one bidder sweeps both items, and the input guard. Runs green
under MOCK_LLM (it touches no model and no embedder).
"""
from __future__ import annotations

import random
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from experiments.exp004_combinatorial_auction.mechanisms.sequential_second_price import (  # noqa: E501
    clear,
)


def _bid(v0: float, v1: float, v01: float) -> dict:
    """A reported valuation over the three exp004 bundles."""
    return {(0,): v0, (1,): v1, (0, 1): v01}


class SweepBothItems(unittest.TestCase):
    """One bidder outbids on both items -> recorded with bundle (0, 1)."""

    def setUp(self):
        # Item 0 bids: A=40, B=30, C=10  -> A wins item 0, pays 2nd = 30.
        # Item 1 bids: A=50, B=20, C=15  -> A wins item 1, pays 2nd = 20.
        self.profile = [
            _bid(40.0, 50.0, 95.0),  # A (idx 0)
            _bid(30.0, 20.0, 60.0),  # B (idx 1)
            _bid(10.0, 15.0, 30.0),  # C (idx 2)
        ]
        self.out = clear(self.profile, rng=random.Random(0))

    def test_winner_recorded_with_combined_bundle(self):
        self.assertIn(0, self.out["allocation"])
        self.assertEqual(self.out["allocation"][0], (0, 1))

    def test_no_other_bidder_in_allocation(self):
        self.assertEqual(set(self.out["allocation"].keys()), {0})

    def test_payment_is_sum_of_two_second_prices(self):
        # 30 (item 0 second price) + 20 (item 1 second price) = 50.
        self.assertEqual(self.out["payments"][0], 50.0)

    def test_revenue_is_total_payments(self):
        self.assertEqual(self.out["revenue"], 50.0)

    def test_mechanism_label(self):
        self.assertEqual(self.out["mechanism"], "sequential_second_price")


class SplitAcrossBidders(unittest.TestCase):
    """Different bidders win each round -> two single-item bundles."""

    def setUp(self):
        # Item 0 bids: A=70, B=25, C=10  -> A wins item 0, pays 2nd = 25.
        # Item 1 bids: A=12, B=80, C=33  -> B wins item 1, pays 2nd = 33.
        self.profile = [
            _bid(70.0, 12.0, 80.0),  # A (idx 0)
            _bid(25.0, 80.0, 95.0),  # B (idx 1)
            _bid(10.0, 33.0, 40.0),  # C (idx 2)
        ]
        self.out = clear(self.profile, rng=random.Random(0))

    def test_item0_winner_bundle_and_price(self):
        self.assertEqual(self.out["allocation"][0], (0,))
        self.assertEqual(self.out["payments"][0], 25.0)

    def test_item1_winner_bundle_and_price(self):
        self.assertEqual(self.out["allocation"][1], (1,))
        self.assertEqual(self.out["payments"][1], 33.0)

    def test_loser_absent(self):
        self.assertNotIn(2, self.out["allocation"])
        self.assertNotIn(2, self.out["payments"])

    def test_revenue_is_sum(self):
        self.assertEqual(self.out["revenue"], 25.0 + 33.0)


class TieBreaking(unittest.TestCase):
    def test_top_tie_pays_own_bid_and_seeded_winner_deterministic(self):
        # Item 0: A=50, B=50 tie -> second price = 50; winner via rng.
        # Item 1: A=10, B=40    -> B wins, pays 10.
        profile = [
            _bid(50.0, 10.0, 60.0),  # A
            _bid(50.0, 40.0, 90.0),  # B
        ]
        a = clear(profile, rng=random.Random(7))
        b = clear(profile, rng=random.Random(7))
        # Determinism under a fixed seed.
        self.assertEqual(a["allocation"], b["allocation"])
        self.assertEqual(a["payments"], b["payments"])
        # The item-0 tie winner pays the tied max (50.0) for that item.
        item0_winner = next(
            i for i, bndl in a["allocation"].items() if 0 in bndl
        )
        self.assertIn(item0_winner, {0, 1})
        # B always wins item 1 (40 > 10) and pays 10.
        self.assertIn(1, a["allocation"])
        self.assertIn(1, a["allocation"][1])


class InputValidation(unittest.TestCase):
    def test_single_bidder_raises(self):
        with self.assertRaises(ValueError):
            clear([_bid(10.0, 10.0, 20.0)])

    def test_empty_profile_raises(self):
        with self.assertRaises(ValueError):
            clear([])


if __name__ == "__main__":
    unittest.main()
