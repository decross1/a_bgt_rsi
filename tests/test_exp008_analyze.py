"""Deterministic tests for experiments/exp008_qat_eval/analyze.py.

EVAL-ONLY benchmark. No model, no network — runs green under MOCK_LLM (the
default shell env). We exercise the pure aggregation/verdict function
``analyze`` with hand-built fixture rows shaped exactly like the runs/*.jsonl
the eval harnesses write:

  - one H0-shaped fixture (no material difference -> pin vindicated)
  - one H1-shaped fixture (QAT materially better AND tool-call adherence holds)
  - one small-N fixture (-> INSUFFICIENT)

We also assert the tertiary tok/s + memory metrics are flagged NON-DECISION,
and that an H1-shaped quality delta with a tool-call adherence floor BREACH
falls back to H0 (the gate guard).
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from experiments.exp008_qat_eval.analyze import (
    _DEFAULT_CONFIG,
    DECISION_METRICS,
    _load_config,
    analyze,
)


def _quality_rows(arm: str, *, novelty: float, calib: float, adherence: float,
                  n: int = 12) -> list[dict]:
    """n decision rows per metric for one arm, each at the given mean value."""
    rows: list[dict] = []
    for _ in range(n):
        rows.append({"arm": arm, "metric": "novelty_agreement", "value": novelty,
                     "reference_verdict": "novel", "predicted_verdict": "novel"})
        rows.append({"arm": arm, "metric": "calibration_error", "value": calib})
        rows.append({"arm": arm, "metric": "tool_call_adherence", "value": adherence,
                     "reference_verdict": "well_formed",
                     "predicted_verdict": "well_formed"})
    return rows


def _tertiary_rows(arm: str, *, tok_per_s: float, memory_gb: float) -> list[dict]:
    return [
        {"arm": arm, "metric": "tok_per_s", "value": tok_per_s},
        {"arm": arm, "metric": "memory_gb", "value": memory_gb},
    ]


def _robustness_summary(arm: str, *, modal_share: float, variance: float) -> dict:
    return {
        "kind": "summary", "arm": arm, "metric": "robustness",
        "n_hypotheses": 4, "n_per_hypothesis": 12,
        "mean_modal_share": modal_share, "max_score_variance": variance,
    }


CFG = _DEFAULT_CONFIG


class TestH0Vindicated(unittest.TestCase):
    def test_no_material_diff_is_H0(self):
        # pin and qat essentially identical -> below every materiality threshold.
        rows = []
        rows += _quality_rows("pin", novelty=0.80, calib=0.10, adherence=0.95)
        rows += _quality_rows("qat", novelty=0.81, calib=0.105, adherence=0.95)
        rows.append(_robustness_summary("pin", modal_share=1.0, variance=0.0))
        rows.append(_robustness_summary("qat", modal_share=1.0, variance=0.0))
        out = analyze(rows, CFG, config_source="default")
        self.assertEqual(out["verdict"], "H0")
        # every decision metric present and judged non-material
        for m in DECISION_METRICS:
            self.assertIn(m, out["per_metric"])
            self.assertFalse(out["per_metric"][m]["material"])


class TestH1GateOpens(unittest.TestCase):
    def test_qat_materially_better_and_adherence_holds_is_H1(self):
        rows = []
        rows += _quality_rows("pin", novelty=0.70, calib=0.12, adherence=0.95)
        # qat: +0.12 novelty (>0.05 thresh), no regression, adherence above floor
        rows += _quality_rows("qat", novelty=0.82, calib=0.115, adherence=0.96)
        rows.append(_robustness_summary("pin", modal_share=1.0, variance=0.0))
        rows.append(_robustness_summary("qat", modal_share=1.0, variance=0.0))
        out = analyze(rows, CFG, config_source="default")
        self.assertEqual(out["verdict"], "H1")
        self.assertTrue(out["per_metric"]["novelty_agreement"]["material"])
        self.assertEqual(
            out["per_metric"]["novelty_agreement"]["direction"], "qat_better")

    def test_qat_better_but_adherence_below_floor_falls_back_to_H0(self):
        # Quality gain is real, but tool-call adherence breaches the floor (0.90)
        # -> the gate must NOT open.
        rows = []
        rows += _quality_rows("pin", novelty=0.70, calib=0.12, adherence=0.95)
        rows += _quality_rows("qat", novelty=0.85, calib=0.10, adherence=0.80)
        out = analyze(rows, CFG, config_source="default")
        self.assertEqual(out["verdict"], "H0")
        joined = " ".join(out["reasons"]).lower()
        self.assertIn("adherence", joined)

    def test_qat_material_regression_is_H0(self):
        # qat improves novelty but materially regresses calibration -> H0.
        rows = []
        rows += _quality_rows("pin", novelty=0.70, calib=0.05, adherence=0.95)
        rows += _quality_rows("qat", novelty=0.85, calib=0.20, adherence=0.95)
        out = analyze(rows, CFG, config_source="default")
        self.assertEqual(out["verdict"], "H0")


class TestInsufficient(unittest.TestCase):
    def test_small_N_is_INSUFFICIENT(self):
        # Only 3 scored items per metric per arm; min_sample is 10.
        rows = []
        rows += _quality_rows("pin", novelty=0.80, calib=0.10, adherence=0.95, n=3)
        rows += _quality_rows("qat", novelty=0.95, calib=0.05, adherence=0.99, n=3)
        out = analyze(rows, CFG, config_source="default")
        self.assertEqual(out["verdict"], "INSUFFICIENT")
        self.assertTrue(out["per_metric"] == {})

    def test_missing_arm_is_INSUFFICIENT(self):
        rows = _quality_rows("pin", novelty=0.80, calib=0.10, adherence=0.95)
        out = analyze(rows, CFG, config_source="default")
        self.assertEqual(out["verdict"], "INSUFFICIENT")
        self.assertTrue(any("qat" in r for r in out["reasons"]))


class TestTertiaryNonDecision(unittest.TestCase):
    def test_tertiary_flagged_non_decision(self):
        rows = []
        rows += _quality_rows("pin", novelty=0.80, calib=0.10, adherence=0.95)
        rows += _quality_rows("qat", novelty=0.81, calib=0.10, adherence=0.95)
        rows += _tertiary_rows("pin", tok_per_s=70.0, memory_gb=24.0)
        rows += _tertiary_rows("qat", tok_per_s=120.0, memory_gb=14.0)
        out = analyze(rows, CFG, config_source="default")
        for arm in ("pin", "qat"):
            tert = out["arms"][arm]["tertiary_metrics"]
            self.assertIn("tok_per_s", tert)
            self.assertIn("memory_gb", tert)
            self.assertTrue(tert["tok_per_s"]["non_decision"])
            self.assertTrue(tert["memory_gb"]["non_decision"])
        # The summary carries a disclaimer naming tertiary as non-decision.
        self.assertIn("non-comparable", out["tertiary_disclaimer"].lower())

    def test_huge_tertiary_gap_does_not_move_verdict(self):
        # qat is dramatically faster + lighter, but quality is at parity.
        # Verdict MUST stay H0 (tertiary is never a decision input).
        rows = []
        rows += _quality_rows("pin", novelty=0.80, calib=0.10, adherence=0.95)
        rows += _quality_rows("qat", novelty=0.80, calib=0.10, adherence=0.95)
        rows += _tertiary_rows("pin", tok_per_s=40.0, memory_gb=48.0)
        rows += _tertiary_rows("qat", tok_per_s=400.0, memory_gb=8.0)
        out = analyze(rows, CFG, config_source="default")
        self.assertEqual(out["verdict"], "H0")


class TestConfusionMatrix(unittest.TestCase):
    def test_confusion_cells_aggregated(self):
        rows = [
            {"arm": "qat", "metric": "tool_call_adherence", "value": 0.9,
             "reference_verdict": "well_formed", "predicted_verdict": "well_formed"},
            {"arm": "qat", "metric": "tool_call_adherence", "value": 0.9,
             "reference_verdict": "well_formed", "predicted_verdict": "malformed"},
        ]
        out = analyze(rows, CFG, config_source="default")
        conf = out["arms"]["qat"]["confusion"]["tool_call_adherence"]
        self.assertEqual(conf["well_formed->well_formed"], 1)
        self.assertEqual(conf["well_formed->malformed"], 1)


class TestConfigProvenance(unittest.TestCase):
    """No silent coercion: the verdict reports WHERE its thresholds came from."""

    def test_default_source_string_passes_through(self):
        rows = []
        rows += _quality_rows("pin", novelty=0.80, calib=0.10, adherence=0.95)
        rows += _quality_rows("qat", novelty=0.80, calib=0.10, adherence=0.95)
        out = analyze(rows, CFG, config_source="default")
        self.assertEqual(out["config"]["source"], "default")
        self.assertTrue(out["config"]["used_default"])

    def test_config_yaml_source_is_not_used_default(self):
        rows = []
        rows += _quality_rows("pin", novelty=0.80, calib=0.10, adherence=0.95)
        rows += _quality_rows("qat", novelty=0.80, calib=0.10, adherence=0.95)
        out = analyze(rows, CFG, config_source="config.yaml")
        self.assertEqual(out["config"]["source"], "config.yaml")
        self.assertFalse(out["config"]["used_default"])

    def test_loader_flags_config_lacking_threshold_keys(self):
        # The committed config.yaml pre-registers a DIFFERENT materiality scheme
        # (tier-disagreement noise floor) than this analyzer's per-metric
        # thresholds. The loader must NOT mislabel the back-filled default as
        # config-sourced — it reports the honest fallback string.
        _cfg, source = _load_config()
        if source.startswith("config.yaml"):
            # If a future config.yaml DOES carry the keys, that's fine too —
            # then the source is legitimately config.yaml.
            self.skipTest("config.yaml now supplies this analyzer's keys")
        self.assertTrue(source.startswith("default"))
        if "config.yaml present" in source:
            # the descriptive fallback path: it must name config.yaml so the
            # provenance is auditable, not silently coerced.
            self.assertIn("config.yaml", source)


if __name__ == "__main__":
    unittest.main()
