#!/usr/bin/env python3
"""Self-tests for the literature-falsification accuracy battery's SCORING.

Mirrors tests/test_critic_eval_scoring.py: we pin the scoring ALGORITHM and
the PASS BAR with deterministic stub observations — NO real model, NO Chroma,
NO iteration cache. The model-touching `run_case` is the integrator's serial
`env -u MOCK_LLM` smoke, not a unit-test concern (under MOCK_LLM the workers
are stubbed and verdict accuracy is meaningless).

The three end-to-end stubs prove the scaffold distinguishes a pipe that
falsifies correctly from one that doesn't:

  * an ORACLE stub (emits each case's expected verdicts + correct gate)
    scores 100% verdict accuracy and clears the proposed pass bar.
  * a LABEL-BLIND stub (always 'novel'/'survives', never flags) FAILS the
    accuracy bar AND trips the off-domain regression guard (false
    novel/survives) AND misses gate recall.
  * an ORACLE-EXCEPT-FASE stub (correct everywhere but does NOT
    low-confidence-flag the FASE off-domain case) FAILS the proposed bar
    via incomplete gate recall — the specific regression this battery exists
    to catch.

Run standalone:
    MOCK_LLM=1 ./.venv-chroma/bin/python -m pytest tests/test_lit_falsification_battery.py
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from experiments.lit_falsification_battery.battery import (  # noqa: E402
    CRITIC_ENUM,
    VERDICT_ACCURACY_BAR,
    CaseObservation,
    load_cases,
    result_to_dict,
    score_battery,
    score_case,
)

FASE_CASE_ID = "fase_off_01_semantic_entropy"
PBEAUTY_CASE_ID = "pbeauty_068_01_levelk"


# ──────────────────────────────────────────────────────────────────────
# score_case — per-case correctness + the on/off-domain pass logic.
# ──────────────────────────────────────────────────────────────────────
class ScoreCaseTest(unittest.TestCase):
    def _on_case(self, **over):
        c = {
            "case_id": "on1",
            "domain": "on",
            "expected_novelty": "rediscovery",
            "expected_critic": "falsified",
            "expect_low_confidence": False,
        }
        c.update(over)
        return c

    def _off_case(self, **over):
        c = {
            "case_id": "off1",
            "domain": "off",
            "expected_novelty": "unclear",
            "expected_critic": "falsified",
            "expect_low_confidence": True,
        }
        c.update(over)
        return c

    def _obs(self, cid="on1", nov="rediscovery", crit="falsified", low=False):
        return CaseObservation(case_id=cid, novelty_class=nov,
                               critic_verdict=crit, low_confidence=low)

    # -- on-domain: exact-enum on both axes + gate must match -------------
    def test_on_domain_all_correct_passes(self):
        s = score_case(self._on_case(), self._obs())
        self.assertTrue(s.passed)
        self.assertTrue(s.novelty_correct and s.critic_correct and s.gate_correct)

    def test_on_domain_wrong_critic_fails_no_coercion(self):
        # off-by-one verdict is a MISS (rule 4), not a near-pass.
        s = score_case(self._on_case(), self._obs(crit="survives"))
        self.assertFalse(s.critic_correct)
        self.assertFalse(s.passed)

    def test_on_domain_unexpected_gate_fire_fails(self):
        # on-domain expects gate OFF; an unexpected fire is a gate miss.
        s = score_case(self._on_case(), self._obs(low=True))
        self.assertFalse(s.gate_correct)
        self.assertFalse(s.passed)

    # -- off-domain: regression guard (gate fired + no false novel/survives)
    def test_off_domain_gate_fires_and_not_novel_passes(self):
        s = score_case(self._off_case(),
                       self._obs(cid="off1", nov="unclear", crit="falsified", low=True))
        self.assertTrue(s.passed)
        self.assertFalse(s.novel_or_survives)

    def test_off_domain_ungated_novel_fails_and_flags_regression(self):
        # THE 2026-06-09 bug shape: off-domain scored 'novel'/'survives' with
        # the gate OFF. This is the hard regression -> case fails.
        s = score_case(self._off_case(),
                       self._obs(cid="off1", nov="novel", crit="survives", low=False))
        self.assertTrue(s.ungated_novel_or_survives)
        self.assertFalse(s.gated_novel_or_survives)
        self.assertFalse(s.passed)

    def test_off_domain_gated_survives_is_soft_not_a_hard_fail(self):
        # Gate FIRED but the model still emitted 'survives' (no dedicated
        # low-confidence enum). Honestly tempered: surfaced as a soft signal,
        # NOT the bug, and the case still passes the regression guard.
        s = score_case(self._off_case(),
                       self._obs(cid="off1", nov="unclear", crit="survives", low=True))
        self.assertTrue(s.gated_novel_or_survives)
        self.assertFalse(s.ungated_novel_or_survives)
        self.assertTrue(s.passed)

    def test_off_domain_gate_must_fire_when_required(self):
        # Correct non-novel verdicts but gate did NOT fire -> still a fail
        # (the gate is the durable guard; a verdict that happens to be right
        # without the gate is luck, not the fix holding).
        s = score_case(self._off_case(),
                       self._obs(cid="off1", nov="unclear", crit="falsified", low=False))
        self.assertFalse(s.passed)

    def test_off_domain_exact_enum_not_demanded_but_recorded(self):
        # 'restated' instead of the modal 'falsified' is still a NOT-survives
        # honest tempering -> passes; but the axis is recorded as a miss for
        # the confusion matrix (we never silently call it correct).
        s = score_case(self._off_case(),
                       self._obs(cid="off1", nov="unclear", crit="restated", low=True))
        self.assertTrue(s.passed)
        self.assertFalse(s.critic_correct)  # exact-enum still reported honestly

    # -- "undecidable" (T1d) ------------------------------------------------
    def test_critic_enum_includes_undecidable(self):
        self.assertIn("undecidable", CRITIC_ENUM)

    def test_off_domain_undecidable_is_honest_tempering(self):
        # The new fail-closed verdict: undecidable != survives, so an
        # off-domain case with the gate fired passes the regression guard.
        s = score_case(self._off_case(),
                       self._obs(cid="off1", nov="unclear", crit="undecidable", low=True))
        self.assertTrue(s.passed)
        self.assertFalse(s.novel_or_survives)

    def test_undecidable_lands_in_confusion_matrix_not_invalid(self):
        cases = [self._off_case()]
        obs = [self._obs(cid="off1", nov="unclear", crit="undecidable", low=True)]
        res = score_battery(cases, obs)
        self.assertEqual(res.critic_confusion["falsified"]["undecidable"], 1)
        self.assertEqual(res.critic_confusion["falsified"]["<invalid>"], 0)

    # -- accepted_critic (explicit label-side allowance) ---------------------
    def test_accepted_critic_counts_as_correct(self):
        c = self._on_case(expected_critic="restated",
                          accepted_critic=["undecidable"],
                          expected_novelty="rediscovery")
        s = score_case(c, self._obs(nov="rediscovery", crit="undecidable", low=False))
        self.assertTrue(s.critic_correct)
        self.assertTrue(s.passed)

    def test_accepted_critic_does_not_open_the_door_to_survives(self):
        c = self._on_case(expected_critic="restated",
                          accepted_critic=["undecidable"],
                          expected_novelty="rediscovery")
        s = score_case(c, self._obs(nov="rediscovery", crit="survives", low=False))
        self.assertFalse(s.critic_correct)
        self.assertFalse(s.passed)

    # -- expected_axes soft signal -------------------------------------------
    def test_axes_not_scored_when_case_has_no_expected_axes(self):
        s = score_case(self._on_case(), self._obs())
        self.assertIsNone(s.axes_correct)

    def test_axes_scored_when_present_match(self):
        c = self._on_case(expected_axes={"phenomenon": "known",
                                         "substrate": "unstudied_llm",
                                         "predicted_direction": "matches"})
        o = self._obs()
        o.novelty_axes = {"phenomenon": "known", "substrate": "unstudied_llm",
                          "predicted_direction": "matches"}
        s = score_case(c, o)
        self.assertTrue(s.axes_correct)

    def test_axes_mismatch_reported_but_does_not_change_pass(self):
        # Soft secondary signal: a wrong axes decomposition is reported but
        # never moves the locked pass bar.
        c = self._on_case(expected_axes={"phenomenon": "known"})
        o = self._obs()  # correct enums + gate, no axes emitted
        s = score_case(c, o)
        self.assertFalse(s.axes_correct)
        self.assertTrue(s.passed)  # locked-bar pass unaffected

    # -- relevance diagnostics passthrough ------------------------------------
    def test_diagnostics_flow_from_observation_to_score_and_dict(self):
        o = self._obs()
        o.anchor_cosine = 0.41
        o.mean_top3_overlap = 0.12
        o.curated_overlap = 0.2
        o.neighbor_spread = 0.05
        o.max_cosine = 0.66
        o.category = "ok"
        o.rule_fired = None
        s = score_case(self._on_case(), o)
        self.assertEqual(s.anchor_cosine, 0.41)
        self.assertEqual(s.category, "ok")
        res = score_battery([self._on_case()], [o])
        row = result_to_dict(res)["per_case"][0]
        for key in ("anchor_cosine", "mean_top3_overlap", "curated_overlap",
                    "neighbor_spread", "max_cosine", "category", "rule_fired",
                    "axes_expected", "axes_actual", "axes_correct"):
            self.assertIn(key, row)
        self.assertEqual(row["anchor_cosine"], 0.41)
        self.assertEqual(row["category"], "ok")

    # -- skeptic/topicality provenance fields (residual-1/2 observability) ----
    def test_new_observation_fields_default_none_and_passthrough(self):
        fields = ("topicality", "skeptic_verdict", "restate_verdict",
                  "verdict_overridden_from", "contradicting_paper_id",
                  "topicality_advisory")
        # Default: a pre-seam observation carries None on all four and they
        # survive score_case as None (additive — never required, never
        # affecting pass logic).
        s = score_case(self._on_case(), self._obs())
        for name in fields:
            self.assertIsNone(getattr(s, name))
        self.assertTrue(s.passed)  # provenance fields never move the bar
        # Populated: values pass through score_case + result_to_dict verbatim.
        o = self._obs()
        o.topicality = "off_independent"
        o.skeptic_verdict = "survives_attack"
        o.restate_verdict = "restated"
        o.verdict_overridden_from = "survives"
        # A 'restated' flip carries the restating citation; the per_case row
        # MUST surface it or the pre-registered C2 criterion ("restated WITH
        # non-null contradicting_paper_id") is structurally unmeasurable.
        o.contradicting_paper_id = "osborne_rubinstein-chunk-979"
        # D-052 NON-GATING advisory: passes through verbatim, additive only.
        o.topicality_advisory = "off"
        s2 = score_case(self._on_case(), o)
        self.assertEqual(s2.topicality, "off_independent")
        self.assertEqual(s2.skeptic_verdict, "survives_attack")
        self.assertEqual(s2.restate_verdict, "restated")
        self.assertEqual(s2.verdict_overridden_from, "survives")
        self.assertEqual(s2.contradicting_paper_id, "osborne_rubinstein-chunk-979")
        self.assertEqual(s2.topicality_advisory, "off")
        # The advisory NEVER moves the locked pass bar (additive observability).
        self.assertTrue(s2.passed)
        row = result_to_dict(score_battery([self._on_case()], [o]))["per_case"][0]
        for name in fields:
            self.assertIn(name, row)
        self.assertEqual(row["topicality"], "off_independent")
        self.assertEqual(row["skeptic_verdict"], "survives_attack")
        self.assertEqual(row["restate_verdict"], "restated")
        self.assertEqual(row["verdict_overridden_from"], "survives")
        self.assertEqual(row["contradicting_paper_id"],
                         "osborne_rubinstein-chunk-979")
        self.assertEqual(row["topicality_advisory"], "off")
        # And the None default serializes as None (not dropped) in the dict.
        row_none = result_to_dict(
            score_battery([self._on_case()], [self._obs()]))["per_case"][0]
        for name in fields:
            self.assertIsNone(row_none[name])


# ──────────────────────────────────────────────────────────────────────
# score_battery — roll-up arithmetic + the proposed pass bar.
# ──────────────────────────────────────────────────────────────────────
class ScoreBatteryTest(unittest.TestCase):
    def test_alignment_by_case_id_missing_obs_raises(self):
        cases = [{"case_id": "x", "domain": "on", "expected_novelty": "novel",
                  "expected_critic": "survives", "expect_low_confidence": False}]
        with self.assertRaises(KeyError):
            score_battery(cases, [])

    def test_verdict_accuracy_arithmetic(self):
        # 2 on-domain cases, one fully correct, one with a wrong critic.
        cases = [
            {"case_id": "a", "domain": "on", "expected_novelty": "novel",
             "expected_critic": "survives", "expect_low_confidence": False},
            {"case_id": "b", "domain": "on", "expected_novelty": "rediscovery",
             "expected_critic": "falsified", "expect_low_confidence": False},
        ]
        obs = [
            CaseObservation("a", "novel", "survives", False),       # 2/2 right
            CaseObservation("b", "rediscovery", "survives", False),  # nov right, crit wrong
        ]
        res = score_battery(cases, obs)
        # 3 of 4 verdict decisions correct.
        self.assertEqual(res.verdict_correct, 3)
        self.assertEqual(res.verdict_decisions, 4)
        self.assertAlmostEqual(res.verdict_accuracy, 0.75)

    def test_confusion_records_invalid_actual(self):
        cases = [{"case_id": "a", "domain": "on", "expected_novelty": "novel",
                  "expected_critic": "survives", "expect_low_confidence": False}]
        obs = [CaseObservation("a", "<missing>", "<missing>", False)]
        res = score_battery(cases, obs)
        # A worker that emitted a non-enum value lands under '<invalid>',
        # never silently dropped.
        self.assertEqual(res.novelty_confusion["novel"]["<invalid>"], 1)
        self.assertEqual(res.critic_confusion["survives"]["<invalid>"], 1)


# ──────────────────────────────────────────────────────────────────────
# End-to-end against the REAL cases.jsonl with stub observations.
# ──────────────────────────────────────────────────────────────────────
class EndToEndAgainstRealCasesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("MOCK_LLM", "1")
        cls.cases = load_cases()
        # Sanity-tie to the case-set invariants this battery commits to.
        if len(cls.cases) < 10:
            raise unittest.SkipTest(
                f"case set has {len(cls.cases)} entries; expected >= 10")

    def test_case_set_spans_required_modes(self):
        # The headline question needs all falsification modes present, or the
        # battery doesn't measure what it claims to.
        novs = {c["expected_novelty"] for c in self.cases}
        crits = {c["expected_critic"] for c in self.cases}
        domains = {c["domain"] for c in self.cases}
        offs_flagged = [c for c in self.cases
                        if c["domain"] == "off" and c["expect_low_confidence"]]
        self.assertIn("novel", novs)
        self.assertIn("rediscovery", novs)
        self.assertIn("nonsense", novs)
        self.assertIn("falsified", crits)
        self.assertIn("restated", crits)
        self.assertIn("malformed", crits)
        self.assertEqual(domains, {"on", "off"})
        self.assertGreaterEqual(len(offs_flagged), 1)
        # The FASE regression guard MUST be present and gate-required.
        fase = [c for c in self.cases if c["case_id"] == FASE_CASE_ID]
        self.assertEqual(len(fase), 1, "FASE regression case missing")
        self.assertTrue(fase[0]["expect_low_confidence"])
        self.assertEqual(fase[0]["domain"], "off")

    def test_t1d_expanded_case_set_invariants(self):
        # T1d battery expansion: 12 originals + 10 new = 22, every original
        # case_id intact, plus the new probe families.
        self.assertGreaterEqual(len(self.cases), 22)
        ids = {c["case_id"] for c in self.cases}
        self.assertEqual(len(ids), len(self.cases), "duplicate case_ids")
        for cid in ("novel_on_01_quant_lockin", "redisc_on_02_folk_theorem",
                    "fase_off_02_db_index_tuning", "nonsense_01_word_salad",
                    "falsifiable_01_finite_pd_cooperate"):
            self.assertIn(cid, ids)
        # Every case carries a rationale (defensible labels, P-009).
        for c in self.cases:
            self.assertTrue(str(c.get("rationale", "")).strip(),
                            f"{c['case_id']} missing rationale")
        # 4 vocabulary-camouflaged off-domain probes: off + gate-required.
        camo = [c for c in self.cases if c["case_id"].startswith("camo_off_")]
        self.assertEqual(len(camo), 4)
        for c in camo:
            self.assertEqual(c["domain"], "off")
            self.assertTrue(c["expect_low_confidence"])
        # 2 drifted-corpus-adjacent off-domain probes.
        drift = [c for c in self.cases if c["case_id"].startswith("drift_off_")]
        self.assertGreaterEqual(len(drift), 2)
        for c in drift:
            self.assertEqual(c["domain"], "off")
            self.assertTrue(c["expect_low_confidence"])
        # 3 over-gating canaries: on-domain, gate must stay OFF.
        canary = [c for c in self.cases if c["case_id"].startswith("canary_on_")]
        self.assertEqual(len(canary), 3)
        for c in canary:
            self.assertEqual(c["domain"], "on")
            self.assertFalse(c["expect_low_confidence"])

    def test_pbeauty_068_case_shape(self):
        pb = [c for c in self.cases if c["case_id"] == PBEAUTY_CASE_ID]
        self.assertEqual(len(pb), 1, "p-beauty 068-class case missing")
        c = pb[0]
        # NOT novel/survives: known phenomenon, corpus-gap substrate.
        self.assertEqual(c["expected_novelty"], "rediscovery")
        self.assertEqual(c["expected_critic"], "restated")
        self.assertEqual(c.get("accepted_critic"), ["undecidable"])
        self.assertNotIn("survives",
                         [c["expected_critic"]] + list(c.get("accepted_critic") or []))
        self.assertEqual(c.get("expected_axes"), {
            "phenomenon": "known",
            "substrate": "unstudied_llm",
            "predicted_direction": "matches",
        })

    def test_axes_cases_counted_separately_from_bar(self):
        # Oracle obs emit no novelty_axes -> the expected_axes case scores
        # axes_correct False, reported separately; the locked bar still passes.
        res = score_battery(self.cases, self._oracle_obs())
        n_axes_cases = sum(1 for c in self.cases
                           if isinstance(c.get("expected_axes"), dict))
        self.assertEqual(res.axes_cases, n_axes_cases)
        self.assertGreaterEqual(n_axes_cases, 1)
        self.assertEqual(res.axes_correct_count, 0)
        self.assertTrue(res.all_pass)  # soft signal never moves the bar

    def _oracle_obs(self):
        """Emit each case's expected verdicts + the expected gate state."""
        return [
            CaseObservation(
                case_id=c["case_id"],
                novelty_class=c["expected_novelty"],
                critic_verdict=c["expected_critic"],
                low_confidence=bool(c["expect_low_confidence"]),
            )
            for c in self.cases
        ]

    def test_oracle_stub_clears_proposed_bar(self):
        res = score_battery(self.cases, self._oracle_obs())
        self.assertEqual(res.verdict_accuracy, 1.0)
        self.assertTrue(res.meets_accuracy_bar)
        self.assertTrue(res.gate_recall_complete)
        self.assertEqual(res.offdomain_ungated_novel_or_survives, 0)
        self.assertTrue(res.all_pass)
        self.assertEqual(res.cases_passed, res.cases_scored)

    def test_label_blind_stub_fails_bar_and_trips_regression_guard(self):
        # Always 'novel'/'survives', never flags low-confidence — the exact
        # pathology the fix targets. Must fail loudly on every axis.
        blind = [
            CaseObservation(c["case_id"], "novel", "survives", False)
            for c in self.cases
        ]
        res = score_battery(self.cases, blind)
        self.assertLess(res.verdict_accuracy, VERDICT_ACCURACY_BAR)
        self.assertFalse(res.meets_accuracy_bar)
        # Off-domain cases all scored novel/survives with gate OFF -> the hard
        # 2026-06-09 regression trips.
        self.assertGreater(res.offdomain_ungated_novel_or_survives, 0)
        self.assertFalse(res.no_ungated_novel_survives)
        # Gate never fired on the cases that required it.
        self.assertFalse(res.gate_recall_complete)
        self.assertFalse(res.all_pass)

    def test_oracle_except_fase_not_flagged_fails_via_gate_recall(self):
        # Identical to the oracle EXCEPT the FASE off-domain case is NOT
        # low-confidence-flagged. The verdict enums are otherwise the modal
        # honest ones, so this isolates the gate: the proposed bar must FAIL
        # because gate recall is incomplete (and the off-domain pass requires
        # the gate to have fired).
        obs = []
        for c in self.cases:
            low = bool(c["expect_low_confidence"])
            nov = c["expected_novelty"]
            crit = c["expected_critic"]
            if c["case_id"] == FASE_CASE_ID:
                low = False  # the regression: gate did NOT fire on FASE
            obs.append(CaseObservation(c["case_id"], nov, crit, low))
        res = score_battery(self.cases, obs)
        self.assertFalse(res.gate_recall_complete)
        self.assertLess(res.gate_fired_when_required, res.gate_must_fire_cases)
        self.assertFalse(res.all_pass)
        # The FASE case specifically must not pass when its gate didn't fire.
        fase_score = next(s for s in res.per_case if s.case_id == FASE_CASE_ID)
        self.assertFalse(fase_score.passed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
