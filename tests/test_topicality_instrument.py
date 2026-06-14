#!/usr/bin/env python3
"""Self-tests for the D-052 topicality-instrument boundary probe's SCORING.

Mirrors tests/test_lit_falsification_battery.py: we pin the PURE scoring
(`score_probe`) and the pre-registered D-052 Phase-1 rule with hand-built
canned `per_case` observations — NO real model, NO network, NO Chroma. The
model-touching `run_probe` is the integrator's real `env -u MOCK_LLM` run, not
a unit-test concern (under MOCK_LLM every variant returns None).

Run standalone:
    MOCK_LLM=1 ./.venv-chroma/bin/python -m pytest tests/test_topicality_instrument.py
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("MOCK_LLM", "1")  # belt-and-suspenders: never the network

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from experiments.topicality_instrument.boundary_probe import (  # noqa: E402
    NON_PRIMARY_VARIANTS,
    _modal,
    score_probe,
)


def _entry(*labels):
    """Build one variant's observation block from repeat labels.

    Matches run_probe's shape: modal = most-common (ties -> first-seen),
    stable = all labels identical."""
    labels = list(labels)
    return {"labels": labels, "modal": _modal(labels), "stable": len(set(labels)) == 1}


def _case_row(domain, primary, adversarial, positive_id, neutral):
    """One per_case row; each of the five judges given a single stable label
    unless a tuple of repeat-labels is passed."""
    def block(v):
        return _entry(*v) if isinstance(v, tuple) else _entry(v, v, v)
    return {
        "domain": domain,
        "primary-gemma": block(primary),
        "adversarial-qwen": block(adversarial),
        "positive-id-qwen": block(positive_id),
        "neutral-qwen": block(neutral),
    }


def _case_meta(cid, domain):
    return {"case_id": cid, "domain": domain}


class ModalHelperTest(unittest.TestCase):
    def test_modal_majority(self):
        self.assertEqual(_modal(["on", "off", "on"]), "on")

    def test_modal_tie_breaks_first_seen(self):
        # 1-1 tie -> the first-seen label wins (deterministic).
        self.assertEqual(_modal(["off", "on"]), "off")
        self.assertEqual(_modal(["on", "off"]), "on")

    def test_modal_empty_is_none(self):
        self.assertIsNone(_modal([]))


class ScoreProbeTest(unittest.TestCase):
    # A primary judge that MISSES one off-domain case (modal != "off"), so a
    # skeptic has a real marginal-catch job to do.
    def _cases(self):
        return [
            _case_meta("fase_off_01", "off"),
            _case_meta("redisc_on_02", "on"),
            _case_meta("canary_on_01", "on"),
            _case_meta("nonsense_01", "on"),
        ]

    def _per_case_clean(self):
        # primary MISSES fase_off_01 (says "on"); a clean variant catches it
        # off, condemns no on-domain case, all boundary labels stable.
        return {
            "fase_off_01": _case_row("off", "on", "off", "off", "off"),
            "redisc_on_02": _case_row("on", "on", "on", "on", "on"),
            "canary_on_01": _case_row("on", "on", "on", "on", "on"),
            # nonsense is informational: even an "off" here is neither catch
            # nor over-gate. Give it a noisy label to prove it's excluded.
            "nonsense_01": _case_row("on", "unsure", ("off", "on", "off"), "unsure", "unsure"),
        }

    def test_clean_variant_qualifies(self):
        per_case = self._per_case_clean()
        summary = score_probe(per_case, self._cases())
        self.assertEqual(summary["primary_misses"], ["fase_off_01"])
        # adversarial-qwen is the clean one here.
        adv = summary["per_variant"]["adversarial-qwen"]
        self.assertTrue(adv["qualifies"])
        self.assertTrue(adv["covers_primary_misses"])
        self.assertEqual(adv["over_gated"], [])
        self.assertEqual(adv["unstable_boundary"], [])
        self.assertTrue(summary["recommended_outcome"].startswith("PAUSE for Phase-2"))
        # nonsense excluded from both boundary sets.
        self.assertNotIn("nonsense_01", summary["must_catch"])
        self.assertNotIn("nonsense_01", summary["must_not_condemn"])

    def test_over_gating_disqualifies(self):
        per_case = self._per_case_clean()
        # positive-id-qwen condemns an on-domain must-not-condemn case.
        per_case["canary_on_01"] = _case_row("on", "on", "on", "off", "on")
        summary = score_probe(per_case, self._cases())
        pv = summary["per_variant"]["positive-id-qwen"]
        self.assertFalse(pv["qualifies"])
        self.assertIn("canary_on_01", pv["over_gated"])

    def test_instability_disqualifies(self):
        per_case = self._per_case_clean()
        # neutral-qwen flips a boundary case across repeats (not all-equal).
        per_case["redisc_on_02"]["neutral-qwen"] = _entry("on", "off", "on")
        summary = score_probe(per_case, self._cases())
        pv = summary["per_variant"]["neutral-qwen"]
        self.assertFalse(pv["qualifies"])
        self.assertIn("redisc_on_02", pv["unstable_boundary"])

    def test_marginal_miss_disqualifies(self):
        per_case = self._per_case_clean()
        # neutral-qwen does NOT catch the primary's miss (says "on").
        per_case["fase_off_01"]["neutral-qwen"] = _entry("on", "on", "on")
        summary = score_probe(per_case, self._cases())
        pv = summary["per_variant"]["neutral-qwen"]
        self.assertFalse(pv["covers_primary_misses"])
        self.assertFalse(pv["qualifies"])

    def test_vacuous_clause1_yields_outcome_A(self):
        # primary catches ALL off-domain -> primary_misses empty -> clause 1 is
        # vacuous -> outcome A even though a variant is otherwise clean.
        cases = self._cases()
        per_case = {
            "fase_off_01": _case_row("off", "off", "off", "off", "off"),
            "redisc_on_02": _case_row("on", "on", "on", "on", "on"),
            "canary_on_01": _case_row("on", "on", "on", "on", "on"),
            "nonsense_01": _case_row("on", "unsure", "unsure", "unsure", "unsure"),
        }
        summary = score_probe(per_case, cases)
        self.assertEqual(summary["primary_misses"], [])
        # A variant can still "qualify" structurally (vacuous clause 1)...
        self.assertTrue(summary["per_variant"]["adversarial-qwen"]["qualifies"])
        # ...but the recommended outcome is A (no marginal value), not PAUSE.
        self.assertTrue(summary["recommended_outcome"].startswith("A "))
        self.assertNotIn("PAUSE", summary["recommended_outcome"])

    def test_all_fail_yields_outcome_A_plus_C(self):
        # primary MISSES an off case and NO variant qualifies (each over-gates).
        cases = self._cases()
        per_case = {
            "fase_off_01": _case_row("off", "on", "off", "off", "off"),
            # every non-primary variant condemns this on-domain case.
            "redisc_on_02": _case_row("on", "on", "off", "off", "off"),
            "canary_on_01": _case_row("on", "on", "on", "on", "on"),
            "nonsense_01": _case_row("on", "unsure", "unsure", "unsure", "unsure"),
        }
        summary = score_probe(per_case, cases)
        self.assertEqual(summary["primary_misses"], ["fase_off_01"])
        for v in NON_PRIMARY_VARIANTS:
            self.assertFalse(summary["per_variant"][v]["qualifies"])
        self.assertTrue(summary["recommended_outcome"].startswith("A+C"))


class ImportSafetyTest(unittest.TestCase):
    def test_import_does_not_hit_network(self):
        # Importing + calling the PURE scorer must never touch the wrapper /
        # network. Done under MOCK_LLM=1 (module top-level), and score_probe
        # takes only canned dicts — if this completes, scoring is model-free.
        import experiments.topicality_instrument.boundary_probe as bp
        self.assertTrue(hasattr(bp, "score_probe"))
        self.assertTrue(hasattr(bp, "run_probe"))
        out = bp.score_probe(
            {"x_off": _case_row("off", "off", "off", "off", "off")},
            [_case_meta("x_off", "off")],
        )
        self.assertEqual(out["must_catch"], ["x_off"])
        self.assertEqual(out["primary_misses"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
