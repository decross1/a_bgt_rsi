"""Unit tests for experiments/exp003_vickrey_rediscovery/auctioneer.py.

Pure-mechanics tests: sealed-bid second-price logic + tie-breaking.
No LLM dependency.
"""
from __future__ import annotations

import random
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from experiments.exp003_vickrey_rediscovery.auctioneer import run_auction


class WinnerSelection(unittest.TestCase):
    def test_strict_winner_pays_second_highest(self):
        out = run_auction([30.0, 75.0, 50.0, 10.0])
        self.assertEqual(out["winner_idx"], 1)
        self.assertEqual(out["max_bid"], 75.0)
        self.assertEqual(out["second_bid"], 50.0)
        self.assertEqual(out["price_paid"], 50.0)
        self.assertFalse(out["tie_break"])

    def test_two_bidder_auction(self):
        out = run_auction([10.0, 20.0])
        self.assertEqual(out["winner_idx"], 1)
        self.assertEqual(out["price_paid"], 10.0)
        self.assertFalse(out["tie_break"])


class TieBreaking(unittest.TestCase):
    def test_tie_winner_pays_max_when_all_tied(self):
        """When all bidders tie at the top, the second-highest = max."""
        out = run_auction([42.0, 42.0, 42.0, 42.0], rng=random.Random(0))
        self.assertEqual(out["max_bid"], 42.0)
        self.assertEqual(out["second_bid"], 42.0)
        self.assertEqual(out["price_paid"], 42.0)
        self.assertTrue(out["tie_break"])
        self.assertIn(out["winner_idx"], {0, 1, 2, 3})

    def test_partial_tie_at_top(self):
        out = run_auction([60.0, 60.0, 30.0, 10.0], rng=random.Random(0))
        self.assertEqual(out["max_bid"], 60.0)
        self.assertEqual(out["second_bid"], 60.0)
        self.assertEqual(out["price_paid"], 60.0)
        self.assertTrue(out["tie_break"])
        self.assertIn(out["winner_idx"], {0, 1})

    def test_seeded_tie_break_is_deterministic(self):
        """Same seed -> same winner pick across runs."""
        a = run_auction([5.0, 5.0, 5.0], rng=random.Random(1234))
        b = run_auction([5.0, 5.0, 5.0], rng=random.Random(1234))
        self.assertEqual(a["winner_idx"], b["winner_idx"])


class InputValidation(unittest.TestCase):
    def test_empty_bids_raises(self):
        with self.assertRaises(ValueError):
            run_auction([])

    def test_single_bid_raises(self):
        with self.assertRaises(ValueError):
            run_auction([42.0])

    def test_nan_bid_raises(self):
        nan = float("nan")
        with self.assertRaises(ValueError):
            run_auction([10.0, nan, 20.0])


if __name__ == "__main__":
    unittest.main()
