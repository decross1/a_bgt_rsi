"""Unit tests for experiments/exp009_cournot/ (run.py mechanics,
analyze.py verdict, loop_bridge.py outcome shape).

PURE mechanics — no model calls, MOCK_LLM-safe:
  - Nash quantity math, market price / profit, deviation computation
  - robust quantity parsing (JSON, bare number, bounds, garbage -> None,
    never coerced)
  - analyze verdict on synthetic trials on BOTH sides of the
    pre-registered threshold (comparative + ceiling), invalid-trial
    exclusion, the Verdict=YES|NO token in the markdown
  - bridge experiment_outcome shape from fixture summary.json/trials.jsonl
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from experiments.exp009_cournot import analyze, loop_bridge
from experiments.exp009_cournot.run import (
    build_system_prompt,
    market_price,
    nash_deviation,
    nash_quantity,
    parse_quantity,
    profit,
)

Q_STAR = 30.0  # nash_quantity(100, 1, 10)


class NashMath(unittest.TestCase):
    def test_default_parameters(self):
        self.assertAlmostEqual(nash_quantity(100.0, 1.0, 10.0), 30.0)

    def test_general_formula(self):
        # q* = (a - c) / (3b)
        self.assertAlmostEqual(nash_quantity(120.0, 2.0, 30.0), 15.0)

    def test_market_price_and_floor(self):
        self.assertAlmostEqual(market_price(30.0, 30.0, 100.0, 1.0), 40.0)
        self.assertAlmostEqual(market_price(80.0, 80.0, 100.0, 1.0), 0.0)

    def test_profit_at_nash(self):
        # P = 100 - 60 = 40; profit = (40 - 10) * 30 = 900
        self.assertAlmostEqual(profit(30.0, 30.0, 100.0, 1.0, 10.0), 900.0)

    def test_deviation(self):
        self.assertAlmostEqual(nash_deviation(33.0, Q_STAR), 0.1)
        self.assertAlmostEqual(nash_deviation(27.0, Q_STAR), 0.1)
        self.assertAlmostEqual(nash_deviation(30.0, Q_STAR), 0.0)


class QuantityParsing(unittest.TestCase):
    def test_json_object(self):
        raw = '{"quantity": 28.5, "reasoning": "balance price and volume"}'
        self.assertEqual(parse_quantity(raw, 100.0), 28.5)

    def test_json_embedded_in_prose(self):
        raw = 'Here is my answer: {"quantity": 30, "reasoning": "ok"} done'
        self.assertEqual(parse_quantity(raw, 100.0), 30.0)

    def test_bare_number_fallback(self):
        self.assertEqual(parse_quantity("I will produce 25 units.", 100.0), 25.0)

    def test_bounds_inclusive(self):
        self.assertEqual(parse_quantity('{"quantity": 0}', 100.0), 0.0)
        self.assertEqual(parse_quantity('{"quantity": 100}', 100.0), 100.0)

    def test_out_of_bounds_high_is_invalid(self):
        self.assertIsNone(parse_quantity('{"quantity": 150}', 100.0))

    def test_negative_is_invalid(self):
        self.assertIsNone(parse_quantity('{"quantity": -5}', 100.0))

    def test_garbage_is_invalid_not_coerced(self):
        self.assertIsNone(parse_quantity("I refuse to answer.", 100.0))
        self.assertIsNone(parse_quantity('{"quantity": "lots"}', 100.0))
        self.assertIsNone(parse_quantity("", 100.0))

    def test_nan_is_invalid(self):
        self.assertIsNone(parse_quantity('{"quantity": NaN}', 100.0))


class SystemPrompt(unittest.TestCase):
    def test_treatment_arms_differ_only_by_few_shot_block(self):
        absent = build_system_prompt("absent", 100.0, 1.0, 10.0)
        explicit = build_system_prompt("explicit", 100.0, 1.0, 10.0)
        self.assertTrue(explicit.startswith(absent))
        self.assertNotIn("marginal cost parameter", absent)
        self.assertIn("marginal cost parameter", explicit)
        self.assertIn("c = 10", explicit)

    def test_no_nash_leak(self):
        for arm in ("absent", "explicit"):
            text = build_system_prompt(arm, 100.0, 1.0, 10.0).lower()
            self.assertNotIn("nash", text)
            self.assertNotIn("equilibrium", text)

    def test_unknown_treatment_raises(self):
        with self.assertRaises(ValueError):
            build_system_prompt("subtle", 100.0, 1.0, 10.0)


def _row(trial: int, treatment: str, q1, q2) -> dict:
    valid = q1 is not None and q2 is not None
    return {
        "trial": trial,
        "treatment": treatment,
        "q1": q1,
        "q2": q2,
        "deviation_1": nash_deviation(q1, Q_STAR) if q1 is not None else None,
        "deviation_2": nash_deviation(q2, Q_STAR) if q2 is not None else None,
        "raw_1": "",
        "raw_2": "",
        "valid": valid,
        "q_star": Q_STAR,
    }


def _rows(treatment: str, pairs: list[tuple]) -> list[dict]:
    return [_row(i, treatment, q1, q2) for i, (q1, q2) in enumerate(pairs)]


class AnalyzeVerdict(unittest.TestCase):
    def test_verdict_yes_both_conditions_hold(self):
        # explicit mean dev = 0.05 (<= 0.15 and < absent's 0.50)
        rows = (_rows("absent", [(45.0, 45.0)] * 5)
                + _rows("explicit", [(31.5, 28.5)] * 5))
        s = analyze.build_summary(rows)
        self.assertEqual(s["verdict"], "YES")
        self.assertAlmostEqual(
            s["arms"]["explicit"]["mean_abs_deviation"], 0.05)
        self.assertAlmostEqual(
            s["arms"]["absent"]["mean_abs_deviation"], 0.50)

    def test_verdict_no_ceiling_violated(self):
        # explicit better than absent but mean dev 0.20 > 0.15 ceiling:
        # "better but not near Nash" must NOT pass (never coerced).
        rows = (_rows("absent", [(45.0, 45.0)] * 5)
                + _rows("explicit", [(36.0, 36.0)] * 5))
        s = analyze.build_summary(rows)
        self.assertEqual(s["verdict"], "NO")
        self.assertTrue(s["comparative_holds"])
        self.assertFalse(s["ceiling_holds"])

    def test_verdict_no_comparative_violated(self):
        # explicit within ceiling (0.10) but absent is BETTER (0.05).
        rows = (_rows("absent", [(31.5, 28.5)] * 5)
                + _rows("explicit", [(33.0, 27.0)] * 5))
        s = analyze.build_summary(rows)
        self.assertEqual(s["verdict"], "NO")
        self.assertFalse(s["comparative_holds"])
        self.assertTrue(s["ceiling_holds"])

    def test_verdict_yes_at_exact_ceiling(self):
        # mean dev exactly 0.15: <= is pre-registered as passing.
        rows = (_rows("absent", [(45.0, 45.0)] * 5)
                + _rows("explicit", [(34.5, 25.5)] * 5))
        s = analyze.build_summary(rows)
        self.assertAlmostEqual(
            s["arms"]["explicit"]["mean_abs_deviation"], 0.15)
        self.assertEqual(s["verdict"], "YES")

    def test_missing_arm_is_no(self):
        rows = _rows("explicit", [(30.0, 30.0)] * 5)
        s = analyze.build_summary(rows)
        self.assertEqual(s["verdict"], "NO")
        self.assertIn("zero valid trials", s["verdict_reason"])

    def test_invalid_trials_excluded_and_counted(self):
        rows = (_rows("absent", [(45.0, 45.0)] * 4 + [(None, None)])
                + _rows("explicit", [(30.0, 30.0)] * 4 + [(5.0, None)]))
        s = analyze.build_summary(rows)
        self.assertEqual(s["arms"]["absent"]["n_invalid"], 1)
        self.assertEqual(s["arms"]["explicit"]["n_invalid"], 1)
        self.assertEqual(s["arms"]["explicit"]["n_valid"], 4)
        # The invalid explicit trial's q1=5.0 must NOT pollute the metric.
        self.assertAlmostEqual(
            s["arms"]["explicit"]["mean_abs_deviation"], 0.0)
        self.assertEqual(s["verdict"], "YES")

    def test_secondary_variance_signal_reported_not_verdict_bearing(self):
        # explicit has HIGHER variance but still wins the primary metric:
        # verdict stays YES; the directional flag reports False.
        rows = (_rows("absent", [(45.0, 45.0)] * 5)
                + _rows("explicit", [(28.0, 32.0)] * 5))
        s = analyze.build_summary(rows)
        self.assertEqual(s["verdict"], "YES")
        self.assertFalse(s["variance_directional_holds"])

    def test_markdown_carries_verdict_token(self):
        rows = (_rows("absent", [(45.0, 45.0)] * 5)
                + _rows("explicit", [(30.0, 30.0)] * 5))
        md_yes = analyze.render_markdown(analyze.build_summary(rows))
        self.assertIn("Verdict=YES", md_yes)
        rows_no = (_rows("absent", [(30.0, 30.0)] * 5)
                   + _rows("explicit", [(45.0, 45.0)] * 5))
        md_no = analyze.render_markdown(analyze.build_summary(rows_no))
        self.assertIn("Verdict=NO", md_no)


class BridgeOutcomeShape(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        rows = (_rows("absent", [(45.0, 45.0)] * 5)
                + _rows("explicit", [(31.5, 28.5)] * 5))
        self.summary = analyze.build_summary(rows)
        self.summary_path = tmp / "summary.json"
        self.summary_path.write_text(json.dumps(self.summary))
        self.trials_path = tmp / "trials.jsonl"
        with open(self.trials_path, "w") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_outcome_shape(self):
        out = loop_bridge.build_experiment_outcome(
            summary_path=self.summary_path, trials_path=self.trials_path)
        self.assertEqual(out["experiment_id"], "exp009_cournot")
        self.assertEqual(out["metric"], "mean_abs_deviation_from_nash_quantity")
        self.assertAlmostEqual(out["value"], 0.05)
        self.assertIn("Verdict=YES", out["summary"])
        self.assertEqual(out["trials"], 10)
        self.assertEqual(
            out["results_path"],
            "experiments/exp009_cournot/results/summary.md")

    def test_topic_seed(self):
        out = loop_bridge.build_experiment_outcome(
            summary_path=self.summary_path, trials_path=self.trials_path)
        topic = loop_bridge.build_topic_seed(out)
        self.assertIn("Cournot duopoly", topic)
        self.assertIn("marginal cost parameter", topic)
        self.assertIn("0.0500", topic)

    def test_missing_summary_is_fatal(self):
        with self.assertRaises(SystemExit):
            loop_bridge.build_experiment_outcome(
                summary_path=Path(self.tmp.name) / "nope.json",
                trials_path=self.trials_path)


if __name__ == "__main__":
    unittest.main()
