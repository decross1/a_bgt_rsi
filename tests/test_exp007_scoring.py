"""Unit tests for experiments/exp007_polymarket/scoring.py.

DESIGN-ONLY paper forecasting; NO live trading (CLAUDE.md CFTC guardrail).

Pure-arithmetic tests on hand-computed examples. No LLM, no network — runs
green under MOCK_LLM (the default shell env). The module under test is itself
pure python with no I/O, so nothing needs monkeypatching here.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from experiments.exp007_polymarket.scoring import (
    brier,
    brier_skill_score,
    summarize,
)


class TestBrier(unittest.TestCase):
    def test_perfect_forecast_scores_zero(self):
        self.assertEqual(brier(1.0, 1.0), 0.0)
        self.assertEqual(brier(0.0, 0.0), 0.0)

    def test_worst_forecast_scores_one(self):
        self.assertEqual(brier(0.0, 1.0), 1.0)
        self.assertEqual(brier(1.0, 0.0), 1.0)

    def test_midpoint(self):
        # (0.5 - 1)^2 = 0.25
        self.assertAlmostEqual(brier(0.5, 1.0), 0.25)
        self.assertAlmostEqual(brier(0.7, 0.0), 0.49)


class TestBrierSkillScore(unittest.TestCase):
    def test_model_beats_market_positive(self):
        # model briers lower than market -> BSS in (0, 1)
        model = [0.04, 0.09]   # mean 0.065
        market = [0.16, 0.25]  # mean 0.205
        bss = brier_skill_score(model, market)
        self.assertGreater(bss, 0.0)
        self.assertAlmostEqual(bss, 1.0 - 0.065 / 0.205)

    def test_model_worse_than_market_negative(self):
        model = [0.16, 0.25]   # mean 0.205
        market = [0.04, 0.09]  # mean 0.065
        bss = brier_skill_score(model, market)
        self.assertLess(bss, 0.0)
        self.assertAlmostEqual(bss, 1.0 - 0.205 / 0.065)

    def test_parity_is_zero(self):
        self.assertEqual(brier_skill_score([0.1, 0.2], [0.1, 0.2]), 0.0)

    def test_divide_by_zero_guarded(self):
        # market was a perfect forecaster -> denominator 0 -> guarded to 0.0
        self.assertEqual(brier_skill_score([0.1, 0.2], [0.0, 0.0]), 0.0)

    def test_empty_inputs_zero(self):
        self.assertEqual(brier_skill_score([], []), 0.0)
        self.assertEqual(brier_skill_score([0.1], []), 0.0)


class TestSummarize(unittest.TestCase):
    def test_unresolved_rows_skipped(self):
        rows = [
            {"prob": 0.8, "market_prob": 0.5, "outcome": 1.0},
            {"prob": 0.3, "market_prob": 0.5, "outcome": None},  # unresolved
            {"prob": 0.2, "market_prob": 0.5, "outcome": 0.0},
        ]
        out = summarize(rows)
        self.assertEqual(out["n"], 2)

    def test_no_resolved_rows(self):
        rows = [
            {"prob": 0.3, "market_prob": 0.5, "outcome": None},
            {"prob": 0.9, "market_prob": 0.5, "outcome": None},
        ]
        out = summarize(rows)
        self.assertEqual(out["n"], 0)
        self.assertEqual(out["mean_brier_model"], 0.0)
        self.assertEqual(out["mean_brier_market"], 0.0)
        self.assertEqual(out["bss"], 0.0)
        self.assertEqual(out["calibration_note"], "no resolved rows")

    def test_model_beats_market_summary(self):
        # model confidently correct, market at coin-flip
        rows = [
            {"prob": 0.9, "market_prob": 0.5, "outcome": 1.0},
            {"prob": 0.1, "market_prob": 0.5, "outcome": 0.0},
        ]
        out = summarize(rows)
        self.assertEqual(out["n"], 2)
        # model briers: 0.01, 0.01 -> mean 0.01 ; market: 0.25, 0.25 -> 0.25
        self.assertAlmostEqual(out["mean_brier_model"], 0.01)
        self.assertAlmostEqual(out["mean_brier_market"], 0.25)
        self.assertAlmostEqual(out["bss"], 1.0 - 0.01 / 0.25)
        self.assertGreater(out["bss"], 0.0)
        self.assertIn("beats market", out["calibration_note"])

    def test_model_worse_than_market_summary(self):
        rows = [
            {"prob": 0.1, "market_prob": 0.5, "outcome": 1.0},
            {"prob": 0.9, "market_prob": 0.5, "outcome": 0.0},
        ]
        out = summarize(rows)
        self.assertLess(out["bss"], 0.0)
        self.assertIn("trails market", out["calibration_note"])

    def test_perfect_model_scores_brier_zero(self):
        rows = [
            {"prob": 1.0, "market_prob": 0.6, "outcome": 1.0},
            {"prob": 0.0, "market_prob": 0.4, "outcome": 0.0},
        ]
        out = summarize(rows)
        self.assertEqual(out["mean_brier_model"], 0.0)
        self.assertEqual(out["bss"], 1.0)  # 1 - 0/market_mean

    def test_market_perfect_divide_by_zero_guarded(self):
        # market nails every outcome -> mean_brier_market 0 -> bss guarded 0.0
        rows = [
            {"prob": 0.8, "market_prob": 1.0, "outcome": 1.0},
            {"prob": 0.2, "market_prob": 0.0, "outcome": 0.0},
        ]
        out = summarize(rows)
        self.assertEqual(out["mean_brier_market"], 0.0)
        self.assertEqual(out["bss"], 0.0)


if __name__ == "__main__":
    unittest.main()
