"""Unit tests for experiments/exp011_matching_reconstruction/.

PURE mechanics — no model calls, MOCK_LLM-safe:
  - Gale-Shapley determinism + stability under fixed seeds (n=12)
  - perturbation semantics pinned by the prereg (always from baseline,
    never cumulative, k=2, remainder original order)
  - attack invariants: budget Q<=44, <=2 perturbed lists per query,
    merge-sort <=33 comparisons, recorded constraints sound, Mode-1
    recording exactly as pinned (c not in {a,b} -> c>a and c>b)
  - LOCKED scoring neutrality: unordered pairs contribute exactly 0
  - analyze verdict on synthetic rows hitting YES/NO on each locked
    rule + the locked two-case Verdict=NO attribution
  - bridge experiment_outcome shape on tmp fixtures, both polarities
"""
from __future__ import annotations

import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from experiments.exp011_matching_reconstruction import analyze, loop_bridge
from experiments.exp011_matching_reconstruction.attack import (
    MODE1_MAX_COMPARISONS,
    N,
    Q_MAX,
    perturb,
    run_attack,
    tau_scored,
    topological_extension,
    transitive_closure,
)
from experiments.exp011_matching_reconstruction.matching import (
    gale_shapley,
    is_stable,
    match_of_man,
)
from experiments.exp011_matching_reconstruction.run import run_one_trial


def _instance(seed: int):
    rng = np.random.default_rng(seed)
    men = [[int(x) for x in rng.permutation(N)] for _ in range(N)]
    women = [[int(x) for x in rng.permutation(N)] for _ in range(N)]
    t = int(rng.integers(N))
    return men, women, t


def _attack(men, women, t):
    baseline = gale_shapley(men, women)
    oracle = lambda pmp: gale_shapley(pmp, women)  # noqa: E731
    return baseline, run_attack(oracle, men, t, baseline)


class MechanismDeterminismStability(unittest.TestCase):
    def test_deterministic_and_stable_across_seeds(self):
        for seed in range(5):
            men, women, _t = _instance(seed)
            m1 = gale_shapley(men, women)
            m2 = gale_shapley(men, women)
            self.assertEqual(m1, m2, f"seed {seed}: nondeterministic")
            self.assertTrue(is_stable(m1, men, women), f"seed {seed}: unstable")

    def test_distinct_first_choices_market(self):
        # Every man's first choice distinct -> everyone gets it.
        men = [[i] + [w for w in range(N) if w != i] for i in range(N)]
        women = [list(range(N)) for _ in range(N)]
        self.assertEqual(gale_shapley(men, women), list(range(N)))

    def test_invalid_profile_raises_never_coerced(self):
        men = [[0] * N for _ in range(N)]  # not permutations
        women = [list(range(N)) for _ in range(N)]
        with self.assertRaises(ValueError):
            gale_shapley(men, women)

    def test_match_of_man_inverts(self):
        men, women, _ = _instance(7)
        mow = gale_shapley(men, women)
        mom = match_of_man(mow)
        for w, m in enumerate(mow):
            self.assertEqual(mom[m], w)


class PerturbationSemantics(unittest.TestCase):
    """Prereg pin: perturbations ALWAYS from the original baseline
    profile, never cumulative; at most 2 lists per query."""

    def setUp(self):
        self.men, _, _ = _instance(11)
        self.t = 4

    def test_always_from_baseline_never_cumulative(self):
        orig = [list(r) for r in self.men]
        p1 = perturb(self.men, self.t, top=(0, 1))
        p2 = perturb(self.men, self.t, top=(2,))
        self.assertEqual(self.men, orig)          # input untouched
        self.assertEqual(p2[0], orig[0])          # p1's edits absent in p2
        self.assertEqual(p2[1], orig[1])
        self.assertNotEqual(p1[0], orig[0])

    def test_top_remainder_keeps_original_order(self):
        p = perturb(self.men, self.t, top=(3,))
        self.assertEqual(p[3][0], self.t)
        self.assertEqual(p[3][1:], [x for x in self.men[3] if x != self.t])

    def test_bottom_remainder_keeps_original_order(self):
        p = perturb(self.men, self.t, bottom=(5,))
        self.assertEqual(p[5][-1], self.t)
        self.assertEqual(p[5][:-1], [x for x in self.men[5] if x != self.t])

    def test_k2_enforced(self):
        with self.assertRaises(ValueError):
            perturb(self.men, self.t, top=(0, 1), bottom=(2,))


class AttackInvariants(unittest.TestCase):
    def test_budget_k2_and_mode1_cap(self):
        for seed in (0, 1, 2):
            men, women, t = _instance(seed)
            baseline = gale_shapley(men, women)
            diffs_per_call = []

            def oracle(pmp):
                diffs_per_call.append(
                    sum(1 for m in range(N) if pmp[m] != men[m]))
                return gale_shapley(pmp, women)

            res = run_attack(oracle, men, t, baseline)
            self.assertLessEqual(res["queries_used"], Q_MAX)
            self.assertEqual(len(diffs_per_call), res["queries_used"])
            self.assertLessEqual(max(diffs_per_call), 2)
            self.assertLessEqual(res["mode1_queries"], MODE1_MAX_COMPARISONS)

    def test_constraints_sound_and_reconstruction_consistent(self):
        for seed in range(6):
            men, women, t = _instance(seed)
            _, res = _attack(men, women, t)
            true_ranking = women[t]
            tau, unresolved, conc, disc = tau_scored(
                res["closure"], true_ranking)
            self.assertEqual(disc, 0,
                             f"seed {seed}: unsound constraint recorded")
            self.assertAlmostEqual(tau, conc / 66.0)
            self.assertEqual(conc + unresolved, 66)
            recon = res["reconstruction"]
            self.assertEqual(sorted(recon), list(range(N)))
            for u, v in res["constraints"]:
                self.assertLess(recon.index(u), recon.index(v))

    def test_attack_deterministic(self):
        men, women, t = _instance(3)
        _, r1 = _attack(men, women, t)
        _, r2 = _attack(men, women, t)
        self.assertEqual(r1["query_log"], r2["query_log"])
        self.assertEqual(r1["constraints"], r2["constraints"])
        self.assertEqual(r1["reconstruction"], r2["reconstruction"])

    def test_mode1_pinned_recording_when_winner_outside_pair(self):
        # Constructed market: man 0's only natural proposal path hits
        # t=0 first and t ranks him top, so every Mode-1 probe not
        # involving 0 returns winner 0 -> must record (0,a) AND (0,b),
        # exactly the pinned rule, and the pair stays unresolved.
        t = 0
        men = [[i] + [w for w in range(N) if w != i] for i in range(N)]
        women = [list(range(N)) for _ in range(N)]  # t's truth: 0 best
        baseline = gale_shapley(men, women)
        self.assertEqual(baseline[t], 0)
        _, res = _attack(men, women, t)
        mode1 = [q for q in res["query_log"] if q["mode"] == 1]
        outside = [q for q in mode1 if 0 not in q["pair"]]
        self.assertTrue(outside, "no probe with winner outside the pair")
        for q in outside:
            self.assertEqual(q["winner"], 0)
            a, b = q["pair"]
            self.assertIn((0, a), res["constraints"])
            self.assertIn((0, b), res["constraints"])
        # soundness on the constructed truth [0, 1, ..., 11]
        _tau, _unres, _conc, disc = tau_scored(res["closure"], women[t])
        self.assertEqual(disc, 0)


class ScoringNeutrality(unittest.TestCase):
    """LOCKED: tau = (concordant_known - discordant_known)/C(12,2);
    unordered pairs contribute exactly 0, never favorably."""

    TRUTH = list(range(N))

    def _tau(self, constraints):
        return tau_scored(transitive_closure(constraints), self.TRUTH)

    def test_no_constraints_is_chance_zero(self):
        tau, unresolved, conc, disc = self._tau(set())
        self.assertEqual(tau, 0.0)
        self.assertEqual(unresolved, 66)
        self.assertEqual((conc, disc), (0, 0))

    def test_full_chain_closure_is_one(self):
        chain = {(i, i + 1) for i in range(N - 1)}
        tau, unresolved, _, disc = self._tau(chain)
        self.assertEqual(tau, 1.0)
        self.assertEqual(unresolved, 0)
        self.assertEqual(disc, 0)

    def test_single_correct_edge_contributes_exactly_one_pair(self):
        tau, unresolved, _, _ = self._tau({(0, 1)})
        self.assertAlmostEqual(tau, 1 / 66)
        self.assertEqual(unresolved, 65)

    def test_discordant_edge_counts_negative(self):
        tau, unresolved, conc, disc = self._tau({(1, 0)})
        self.assertAlmostEqual(tau, -1 / 66)
        self.assertEqual((conc, disc), (0, 1))
        self.assertEqual(unresolved, 65)

    def test_cycle_raises_never_coerced(self):
        with self.assertRaises(RuntimeError):
            transitive_closure({(0, 1), (1, 0)})

    def test_topological_extension_deterministic_and_consistent(self):
        c = {(5, 3), (3, 7)}
        o1 = topological_extension(c)
        o2 = topological_extension(c)
        self.assertEqual(o1, o2)
        self.assertLess(o1.index(5), o1.index(3))
        self.assertLess(o1.index(3), o1.index(7))
        self.assertEqual(topological_extension(set()), list(range(N)))


class PreregPinnedConstants(unittest.TestCase):
    def test_budget_is_ceil_n_log2_n(self):
        self.assertEqual(Q_MAX, 44)
        self.assertEqual(Q_MAX, math.ceil(12 * math.log2(12)))

    def test_mode1_merge_sort_cap(self):
        self.assertEqual(MODE1_MAX_COMPARISONS, 33)

    def test_locked_rule_constants_verbatim(self):
        self.assertEqual(analyze.MEDIAN_TAU_THRESHOLD, 0.90)
        self.assertEqual(analyze.TRIAL_TAU_FLOOR, 0.80)
        self.assertEqual(analyze.TRIAL_FRACTION_REQUIRED, 0.90)
        self.assertEqual(analyze.Q_MAX, 44)
        self.assertEqual(analyze.LAST5_WINDOW, 5)
        self.assertEqual(analyze.METRIC_NAME,
                         "median_kendall_tau_at_termination")
        self.assertAlmostEqual(analyze.BITS_REQUIRED, 28.835, places=2)


ROW_KEYS = {
    "trial_idx", "seed", "target", "kendall_tau_scored", "queries_used",
    "unresolved_pairs", "bits_per_query", "median_deviation_size",
    "rank_t_best_natural_proposer", "null_tau_p95", "constraints_recorded",
    "constraints_in_last5_queries",
}


class TrialRow(unittest.TestCase):
    def test_row_shape_and_bounds(self):
        row = run_one_trial(0, 123)
        self.assertEqual(set(row), ROW_KEYS)  # driver appends wall_s
        self.assertGreaterEqual(row["kendall_tau_scored"], -1.0)
        self.assertLessEqual(row["kendall_tau_scored"], 1.0)
        self.assertLessEqual(row["queries_used"], Q_MAX)
        self.assertTrue(0 <= row["unresolved_pairs"] <= 66)
        self.assertTrue(1 <= row["rank_t_best_natural_proposer"] <= 12)
        self.assertEqual(row["seed"], 123)

    def test_reproducible_from_derived_seed(self):
        self.assertEqual(run_one_trial(2, 500), run_one_trial(2, 500))
        self.assertEqual(run_one_trial(2, 500)["seed"], 502)


def _srow(i, tau, queries=40, unresolved=0, last5=0, rank=1):
    return {
        "trial_idx": i, "seed": 1000 + i, "target": 0,
        "kendall_tau_scored": tau, "queries_used": queries,
        "unresolved_pairs": unresolved, "bits_per_query": 0.7,
        "median_deviation_size": 2.0,
        "rank_t_best_natural_proposer": rank, "null_tau_p95": 0.3,
        "constraints_recorded": 30, "constraints_in_last5_queries": last5,
        "wall_s": 0.01,
    }


class DecisionRule(unittest.TestCase):
    def test_verdict_yes_both_rules(self):
        s = analyze.build_summary([_srow(i, 0.95) for i in range(20)])
        self.assertEqual(s["verdict"], "YES")
        self.assertTrue(s["effect_confirmed"])
        self.assertTrue(s["rules"]["rule1_median_tau"]["pass"])
        self.assertTrue(s["rules"]["rule2_trial_floor"]["pass"])
        self.assertEqual(s["attribution"]["case"], "not_applicable")
        self.assertFalse(s["attribution"]["refutation_supported"])

    def test_yes_at_exact_thresholds(self):
        # median exactly 0.90 and fraction-at-floor exactly 0.90: >= passes.
        rows = ([_srow(i, 0.90) for i in range(18)]
                + [_srow(18 + i, 0.5) for i in range(2)])
        s = analyze.build_summary(rows)
        self.assertAlmostEqual(
            s["rules"]["rule2_trial_floor"]["observed_fraction"], 0.90)
        self.assertEqual(s["verdict"], "YES")

    def test_no_rule1_median_below(self):
        s = analyze.build_summary([_srow(i, 0.85) for i in range(20)])
        self.assertEqual(s["verdict"], "NO")
        self.assertFalse(s["effect_confirmed"])
        self.assertFalse(s["rules"]["rule1_median_tau"]["pass"])
        self.assertTrue(s["rules"]["rule2_trial_floor"]["pass"])
        self.assertIn("median tau", s["verdict_reason"])

    def test_no_rule2_fraction_below(self):
        rows = ([_srow(i, 0.95) for i in range(17)]
                + [_srow(17 + i, 0.5) for i in range(3)])
        s = analyze.build_summary(rows)
        self.assertEqual(s["verdict"], "NO")
        self.assertTrue(s["rules"]["rule1_median_tau"]["pass"])
        self.assertFalse(s["rules"]["rule2_trial_floor"]["pass"])

    def test_no_on_budget_violation_even_with_high_tau(self):
        rows = [_srow(i, 0.95) for i in range(19)] + [_srow(19, 0.95,
                                                           queries=45)]
        s = analyze.build_summary(rows)
        self.assertEqual(s["verdict"], "NO")
        self.assertFalse(s["rules"]["rule1_median_tau"]["budget_respected"])
        self.assertFalse(s["rules"]["rule1_median_tau"]["pass"])

    def test_attribution_case_i_budget_limited(self):
        rows = [_srow(i, 0.5, queries=44, unresolved=20, last5=3)
                for i in range(20)]
        s = analyze.build_summary(rows)
        self.assertEqual(s["verdict"], "NO")
        self.assertEqual(s["attribution"]["case"], "budget_limited")
        self.assertTrue(s["attribution"]["refutation_supported"])

    def test_attribution_case_ii_attack_limited(self):
        rows = [_srow(i, 0.5, queries=30, unresolved=20, last5=0)
                for i in range(20)]
        s = analyze.build_summary(rows)
        self.assertEqual(s["verdict"], "NO")
        self.assertEqual(s["attribution"]["case"], "attack_limited")
        self.assertFalse(s["attribution"]["refutation_supported"])

    def test_attribution_unattributed_when_neither_case(self):
        rows = [_srow(i, 0.5, queries=44, unresolved=0, last5=0)
                for i in range(20)]
        s = analyze.build_summary(rows)
        self.assertEqual(s["verdict"], "NO")
        self.assertEqual(s["attribution"]["case"], "unattributed")

    def test_error_rows_excluded_and_counted(self):
        rows = ([_srow(i, 0.95) for i in range(19)]
                + [{"trial_idx": 19, "seed": 1019,
                    "error": "RuntimeError: boom", "wall_s": 0.0}])
        s = analyze.build_summary(rows)
        self.assertEqual(s["n_errors"], 1)
        self.assertEqual(s["n_valid"], 19)
        self.assertEqual(s["verdict"], "YES")  # medians from valid rows only

    def test_zero_valid_rows_is_no_not_coerced(self):
        rows = [{"trial_idx": 0, "error": "boom", "wall_s": 0.0}]
        s = analyze.build_summary(rows)
        self.assertEqual(s["verdict"], "NO")
        self.assertIsNone(s["value"])
        self.assertFalse(s["effect_confirmed"])
        md = analyze.render_markdown(s)
        self.assertTrue(md.startswith("Verdict=NO."))

    def test_markdown_verdict_is_line_one(self):
        s_yes = analyze.build_summary([_srow(i, 0.95) for i in range(20)])
        self.assertTrue(analyze.render_markdown(s_yes)
                        .splitlines()[0].startswith("Verdict=YES."))
        s_no = analyze.build_summary([_srow(i, 0.5) for i in range(20)])
        self.assertTrue(analyze.render_markdown(s_no)
                        .splitlines()[0].startswith("Verdict=NO."))

    def test_control_arm_absence_stated(self):
        s = analyze.build_summary([_srow(i, 0.95) for i in range(20)])
        self.assertIn("random-perturbation control arm",
                      s["control_arm_note"])
        self.assertIn("random-perturbation control arm",
                      analyze.render_markdown(s))

    def test_stratified_tau_by_frontier_rank(self):
        rows = ([_srow(i, 0.9, rank=1) for i in range(10)]
                + [_srow(10 + i, 0.5, rank=3) for i in range(10)])
        s = analyze.build_summary(rows)
        strata = s["stratified_tau_by_rank_t_best_natural_proposer"]
        self.assertEqual(set(strata), {"1", "3"})
        self.assertEqual(strata["1"]["n"], 10)
        self.assertAlmostEqual(strata["1"]["median_tau"], 0.9)
        self.assertAlmostEqual(strata["3"]["median_tau"], 0.5)


class BridgeOutcomeShape(unittest.TestCase):
    OUTCOME_KEYS = {"experiment_id", "metric", "value", "summary",
                    "results_path", "trials", "effect_confirmed"}

    def _fixture(self, rows):
        tmp = Path(self.tmp.name)
        summary = analyze.build_summary(rows)
        summary_path = tmp / "summary.json"
        summary_path.write_text(json.dumps(summary))
        trials_path = tmp / "trials.jsonl"
        with open(trials_path, "w") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        return summary_path, trials_path

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_yes_polarity_shape(self):
        sp, tp = self._fixture([_srow(i, 0.95) for i in range(20)])
        out = loop_bridge.build_experiment_outcome(summary_path=sp,
                                                   trials_path=tp)
        self.assertEqual(set(out), self.OUTCOME_KEYS)
        self.assertEqual(out["experiment_id"],
                         "exp011_matching_reconstruction")
        self.assertEqual(out["metric"],
                         "median_kendall_tau_at_termination")
        self.assertAlmostEqual(out["value"], 0.95)
        self.assertTrue(out["summary"].startswith("Verdict=YES."))
        self.assertEqual(out["trials"], 20)
        self.assertTrue(out["effect_confirmed"])
        self.assertEqual(
            out["results_path"],
            "experiments/exp011_matching_reconstruction/results/summary.md")

    def test_no_polarity_shape(self):
        sp, tp = self._fixture(
            [_srow(i, 0.5, queries=44, unresolved=20, last5=3)
             for i in range(20)])
        out = loop_bridge.build_experiment_outcome(summary_path=sp,
                                                   trials_path=tp)
        self.assertTrue(out["summary"].startswith("Verdict=NO."))
        self.assertFalse(out["effect_confirmed"])
        self.assertIn("budget_limited", out["summary"])

    def test_topic_seed_carries_claim_text(self):
        sp, tp = self._fixture([_srow(i, 0.95) for i in range(20)])
        out = loop_bridge.build_experiment_outcome(summary_path=sp,
                                                   trials_path=tp)
        topic = loop_bridge.build_topic_seed(out)
        self.assertIn("reconstruct the preference rankings", topic)
        self.assertIn("stable matching", topic)
        self.assertIn("0.9500", topic)

    def test_missing_summary_is_fatal(self):
        with self.assertRaises(SystemExit):
            loop_bridge.build_experiment_outcome(
                summary_path=Path(self.tmp.name) / "nope.json",
                trials_path=Path(self.tmp.name) / "trials.jsonl")

    def test_null_value_is_fatal_not_coerced(self):
        rows = [{"trial_idx": 0, "error": "boom", "wall_s": 0.0}]
        sp, tp = self._fixture(rows)
        with self.assertRaises(SystemExit):
            loop_bridge.build_experiment_outcome(summary_path=sp,
                                                 trials_path=tp)


if __name__ == "__main__":
    unittest.main()
