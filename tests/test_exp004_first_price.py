"""Unit tests for the first-price combinatorial mechanism (exp004).

Pure-Python, fully seeded, no LLM dependency — runs green under the
default MOCK_LLM shell env. exp004 is the HARDEST SYNTHETIC rung (a
combinatorial auction with a KNOWN optimal allocation), the on-ramp to —
but NOT yet — the semi-synthetic mechanism-DESIGN tier.

These tests pin first-price's defining property: each winner pays THEIR
OWN bid for the bundle they win (pay-your-bid), the chosen allocation
maximizes reported welfare, and the allocation is item-feasible.
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
    allocation_welfare,
    feasible_allocations,
)
from experiments.exp004_combinatorial_auction.mechanisms import first_price


class PayYourBid(unittest.TestCase):
    def test_winner_pays_own_bid_on_hand_computed_split(self):
        """Two bidders; the welfare-max allocation splits the two items.

        Bidder 0 bids 30 for item 0, bidder 1 bids 25 for item 1. The
        best feasible allocation is the split {0:(0,), 1:(1,)} with
        reported welfare 30 + 25 = 55, beating the pair (32 or 20) or any
        single sale. Under first price each winner pays THEIR OWN bid.
        """
        bid_profile = [
            {(0,): 30.0, (1,): 5.0, (0, 1): 32.0},
            {(0,): 4.0, (1,): 25.0, (0, 1): 20.0},
        ]
        out = first_price.clear(bid_profile, rng=random.Random(0))

        self.assertEqual(out["mechanism"], "first_price")
        self.assertEqual(out["allocation"], {0: (0,), 1: (1,)})
        # Pay-your-bid: each winner pays their own reported bid.
        self.assertEqual(out["payments"], {0: 30.0, 1: 25.0})
        self.assertEqual(out["revenue"], 55.0)

    def test_sole_pair_winner_pays_own_pair_bid(self):
        """When the pair bid dominates, one bidder wins {0,1} and pays it."""
        bid_profile = [
            {(0,): 10.0, (1,): 10.0, (0, 1): 90.0},
            {(0,): 12.0, (1,): 12.0, (0, 1): 15.0},
        ]
        out = first_price.clear(bid_profile, rng=random.Random(0))
        self.assertEqual(out["allocation"], {0: (0, 1)})
        self.assertEqual(out["payments"], {0: 90.0})
        self.assertEqual(out["revenue"], 90.0)


class WelfareMaximization(unittest.TestCase):
    def test_chosen_allocation_maximizes_reported_welfare(self):
        """Across random profiles, the chosen allocation's reported welfare
        equals the brute-force max over feasible allocations."""
        for seed in range(50):
            rng = random.Random(seed)
            bid_profile = [
                {
                    (0,): rng.uniform(0.0, 50.0),
                    (1,): rng.uniform(0.0, 50.0),
                    (0, 1): rng.uniform(0.0, 80.0),
                }
                for _ in range(3)
            ]
            out = first_price.clear(bid_profile, rng=random.Random(seed))
            best = max(
                allocation_welfare(a, bid_profile)
                for a in feasible_allocations(len(bid_profile))
            )
            self.assertEqual(
                allocation_welfare(out["allocation"], bid_profile), best
            )

    def test_revenue_equals_sum_of_own_bids(self):
        """Revenue is exactly the sum of winners' own bids on their bundles."""
        for seed in range(20):
            rng = random.Random(seed)
            bid_profile = [
                {
                    (0,): rng.uniform(0.0, 50.0),
                    (1,): rng.uniform(0.0, 50.0),
                    (0, 1): rng.uniform(0.0, 80.0),
                }
                for _ in range(3)
            ]
            out = first_price.clear(bid_profile, rng=random.Random(seed))
            expected = sum(
                bid_profile[i][b] for i, b in out["allocation"].items()
            )
            self.assertEqual(out["revenue"], expected)
            self.assertEqual(
                out["payments"],
                {i: bid_profile[i][b] for i, b in out["allocation"].items()},
            )


class Feasibility(unittest.TestCase):
    def test_no_item_allocated_twice(self):
        """The chosen allocation never gives the same item to two winners."""
        for seed in range(50):
            rng = random.Random(seed)
            bid_profile = [
                {
                    (0,): rng.uniform(0.0, 50.0),
                    (1,): rng.uniform(0.0, 50.0),
                    (0, 1): rng.uniform(0.0, 80.0),
                }
                for _ in range(4)
            ]
            out = first_price.clear(bid_profile, rng=random.Random(seed))
            allocated_items: list[int] = []
            for bundle in out["allocation"].values():
                allocated_items.extend(bundle)
            self.assertEqual(
                len(allocated_items),
                len(set(allocated_items)),
                f"double-allocated item in {out['allocation']} (seed={seed})",
            )

    def test_seeded_tie_break_is_deterministic(self):
        """Equal-welfare allocations tie; the same seed picks the same one."""
        # Symmetric bids: item 0 alone to bidder 0 and to bidder 1 tie.
        bid_profile = [
            {(0,): 20.0, (1,): 0.0, (0, 1): 5.0},
            {(0,): 20.0, (1,): 0.0, (0, 1): 5.0},
        ]
        a = first_price.clear(bid_profile, rng=random.Random(7))
        b = first_price.clear(bid_profile, rng=random.Random(7))
        self.assertEqual(a["allocation"], b["allocation"])
        # Whoever wins item 0 pays their own bid of 20.
        self.assertEqual(a["revenue"], 20.0)


if __name__ == "__main__":
    unittest.main()
