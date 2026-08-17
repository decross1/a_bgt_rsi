"""Unit tests for experiments/exp012_lqg_spectral/ (dynamics, LOCKED
decision rules, bridge outcome shape).

PURE numeric — no model calls, MOCK_LLM-safe:
  - quantizer Q_Delta pinned formula; theta* by direct solve
  - PINNED per-step check order: a fixating trajectory (whose quantized
    state repeats consecutively — the exact case a naive hash-first
    order flags as a cycle) is NOT flagged cycling; a genuine 2-cycle
    IS, with T := t_max; the budget_exhausted third branch
  - determinism + LOCKED pairing (the (A, b, theta0) triple drawn once
    per seed, shared across all rho_eff x arm cells); acyclic redraw
  - analyze rules 1-5 on synthetic fixtures hitting YES and NO,
    including a rule-5 censoring-only breakpoint fixture that MUST be
    adjudicated FALSE with the censoring-geometry phrasing
  - BIC form / breakpoint-window / H0_construction pinned arithmetic
  - loop_bridge.build_experiment_outcome both verdict polarities +
    the LOOP_V0_CALLS_LOG source-order contract
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

from experiments.exp012_lqg_spectral import analyze, dynamics, loop_bridge
from experiments.exp012_lqg_spectral.dynamics import (
    DELTA,
    RHO_EFF_GRID,
    T_MAX,
    draw_instance,
    make_m,
    quantize,
    run_bounded,
    run_cell,
    run_full,
    spectral_radius,
    theta_star,
)
from experiments.exp012_lqg_spectral.run import iter_rows

GRID = analyze.RHO_EFF_GRID

ROW_KEYS = {"trial_idx", "seed_index", "rho_eff", "arm", "T", "cycling",
            "budget_exhausted", "redraws", "e0_inf", "wall_s"}


class LockedConstantsInSync(unittest.TestCase):
    def test_env_constants_match_across_modules(self):
        # Duplicated on purpose (analyze carries the rule verbatim);
        # this pins the two copies equal so they cannot drift.
        self.assertEqual(analyze.RHO_EFF_GRID, dynamics.RHO_EFF_GRID)
        self.assertEqual(analyze.N_SEEDS, dynamics.N_SEEDS)
        self.assertEqual(analyze.T_MAX, dynamics.T_MAX)
        self.assertEqual(analyze.DELTA, dynamics.DELTA)
        self.assertEqual(analyze.FULL_TOL, dynamics.FULL_TOL)
        self.assertEqual(analyze.ARMS, dynamics.ARMS)

    def test_locked_rule_constants(self):
        self.assertEqual(analyze.DELTA_BIC_MIN, 10.0)
        self.assertEqual((analyze.BIC_K_TWO_SEGMENT, analyze.BIC_K_LINE),
                         (4, 2))
        self.assertEqual(analyze.BREAK_GRID_STEP, 0.005)
        self.assertEqual((analyze.INTERIOR_LO, analyze.INTERIOR_HI),
                         (0.32, 0.74))
        self.assertEqual(analyze.SLOPE_ABOVE_MIN, 2.0)
        self.assertEqual(analyze.SLOPE_RATIO_MIN, 3.0)
        self.assertEqual(analyze.SLOPE_BELOW_FLOOR, 0.25)
        self.assertEqual(analyze.BOOTSTRAP_B, 1000)
        self.assertEqual(dynamics.BASE_SEED, 20260817)
        self.assertEqual(GRID, (0.21, 0.32, 0.42, 0.53, 0.63, 0.74, 0.84))


class QuantizerAndSolve(unittest.TestCase):
    def test_quantizer_pinned_formula(self):
        x = np.random.default_rng(7).uniform(-3, 3, 64)
        np.testing.assert_array_equal(quantize(x),
                                      np.round(x / DELTA) * DELTA)

    def test_quantizer_examples(self):
        self.assertAlmostEqual(float(quantize(np.array([0.12]))[0]), 0.10)
        self.assertAlmostEqual(float(quantize(np.array([0.13]))[0]), 0.15)
        self.assertAlmostEqual(float(quantize(np.array([-0.12]))[0]), -0.10)

    def test_theta_star_direct_solve(self):
        inst = draw_instance(3)
        m = make_m(inst["A"], inst["rho_A"], 0.63)
        ts = theta_star(m, inst["b"])
        np.testing.assert_allclose((np.eye(8) - m) @ ts, inst["b"],
                                   atol=1e-12)

    def test_rescale_sets_rho_eff(self):
        inst = draw_instance(5)
        for rho in (0.21, 0.53, 0.84):
            m = make_m(inst["A"], inst["rho_A"], rho)
            self.assertAlmostEqual(spectral_radius(m), rho, places=10)


class CheckOrderPinned(unittest.TestCase):
    """The LOCKED per-step check order: fixation FIRST, then revisit."""

    # M=0.5*I, b=0.5, theta0=0.9: theta walks 0.9 -> 0.95 -> 0.975 -> 1.0
    # and fixates; its quantized state repeats CONSECUTIVELY on the way,
    # which a naive hash-first order would flag as a cycle.
    FIX_M = np.array([[0.5]])
    FIX_B = np.array([0.5])
    FIX_T0 = np.array([0.9])

    def test_fixating_trajectory_not_flagged_cycling(self):
        res = run_bounded(self.FIX_M, self.FIX_B, self.FIX_T0)
        self.assertFalse(res["cycling"])
        self.assertFalse(res["budget_exhausted"])
        self.assertLess(res["T"], 10)  # settles in a handful of steps

    def test_fixture_would_trip_a_hash_first_order(self):
        # Replay the quantized trajectory: q must repeat consecutively at
        # (or before) the fixation step — i.e. q_T is already in the seen
        # set when fixation fires, so this test is load-bearing for the
        # pinned order (hash-first would return cycling=True here).
        theta = self.FIX_T0.copy()
        qs = []
        for _ in range(20):
            q = quantize(theta)
            qs.append(q.tobytes())
            theta = self.FIX_B + self.FIX_M @ q
        self.assertTrue(any(qs[t] == qs[t - 1] for t in range(1, len(qs))))

    def test_genuine_two_cycle_flagged_cycling(self):
        # M=[[-0.9]] oscillates the quantized state between two values.
        res = run_bounded(np.array([[-0.9]]), np.array([0.5]),
                          np.array([0.25]))
        self.assertTrue(res["cycling"])
        self.assertEqual(res["T"], T_MAX)  # T := t_max convention (LOCKED)
        self.assertFalse(res["budget_exhausted"])

    def test_budget_exhausted_third_branch(self):
        res = run_bounded(np.array([[-0.9]]), np.array([0.5]),
                          np.array([0.25]), t_max=1)
        self.assertTrue(res["budget_exhausted"])
        self.assertFalse(res["cycling"])
        self.assertEqual(res["T"], 1)

    def test_full_arm_settling_definition(self):
        m = np.array([[0.5, 0.1], [0.0, 0.4]])
        b = np.array([0.3, -0.2])
        t0 = np.array([0.9, 0.7])
        res = run_full(m, b, t0)
        # independently recompute: first t with ||theta_{t+1}-theta_t||inf
        # < 1e-6
        theta = t0.copy()
        expect = None
        for t in range(1000):
            nxt = b + m @ theta
            if np.max(np.abs(nxt - theta)) < 1e-6:
                expect = t
                break
            theta = nxt
        self.assertEqual(res["T"], expect)
        self.assertFalse(res["cycling"])
        self.assertFalse(res["budget_exhausted"])

    def test_full_arm_budget_branch_recorded(self):
        res = run_full(np.array([[0.99]]), np.array([1.0]),
                       np.array([0.0]), t_max=3)
        self.assertTrue(res["budget_exhausted"])
        self.assertEqual(res["T"], 3)


class InstanceDrawsAndPairing(unittest.TestCase):
    def test_instance_deterministic(self):
        a = draw_instance(4)
        b = draw_instance(4)
        np.testing.assert_array_equal(a["A"], b["A"])
        np.testing.assert_array_equal(a["b"], b["b"])
        np.testing.assert_array_equal(a["theta0"], b["theta0"])
        self.assertEqual(a["redraws"], b["redraws"])

    def test_instances_differ_across_seeds(self):
        a = draw_instance(0)
        b = draw_instance(1)
        self.assertFalse(np.array_equal(a["A"], b["A"])
                         and np.array_equal(a["b"], b["b"]))

    def test_default_draws_no_self_loops_and_cyclic(self):
        for s in range(5):
            inst = draw_instance(s)
            self.assertEqual(inst["A"].shape, (8, 8))
            np.testing.assert_array_equal(np.diag(inst["A"]), np.zeros(8))
            self.assertTrue(set(np.unique(inst["A"])) <= {0.0, 1.0})
            self.assertGreaterEqual(inst["rho_A"], 1e-6)

    def test_acyclic_redraw_path(self):
        # n=2 makes acyclic draws common (rho > 0 needs both directed
        # edges); seed 0 empirically needs 9 redraws — the redraw loop
        # must count them and still land on a cyclic instance.
        inst = draw_instance(0, n=2)
        self.assertGreaterEqual(inst["redraws"], 1)
        self.assertGreaterEqual(inst["rho_A"], 1e-6)

    def test_rows_deterministic_and_paired(self):
        rows1 = list(iter_rows(n_seeds=2))
        rows2 = list(iter_rows(n_seeds=2))
        self.assertEqual(len(rows1), 2 * 7 * 2)

        def strip(rows):
            return [{k: v for k, v in r.items() if k != "wall_s"}
                    for r in rows]
        self.assertEqual(strip(rows1), strip(rows2))
        self.assertEqual([r["trial_idx"] for r in rows1], list(range(28)))
        for r in rows1:
            self.assertEqual(set(r), ROW_KEYS)
        # LOCKED pairing: theta0 and theta* are shared within a
        # (seed, rho_eff) pair, so e0_inf is identical across its arms;
        # redraws is a per-seed property.
        by_cell = {(r["seed_index"], r["rho_eff"], r["arm"]): r
                   for r in rows1}
        for s in range(2):
            redraws = {by_cell[(s, g, a)]["redraws"]
                       for g in RHO_EFF_GRID for a in ("FULL", "BOUNDED")}
            self.assertEqual(len(redraws), 1)
            for g in RHO_EFF_GRID:
                self.assertEqual(by_cell[(s, g, "FULL")]["e0_inf"],
                                 by_cell[(s, g, "BOUNDED")]["e0_inf"])


# --- analyze fixtures -----------------------------------------------------

def _kink_lnr(rho_star=0.53, slope_below=0.25, slope_above=4.0, level=0.0):
    return {g: level + (slope_below if g <= rho_star else slope_above)
            * (g - rho_star) for g in GRID}


def _fixture_rows(lnr_by_rho, t_full_by_rho=None, bounded_spec=None,
                  n_seeds=30):
    """420 synthetic rows. bounded_spec: rho -> per-seed list of
    (T, cycling, budget_exhausted); default = uncapped on the lnR curve."""
    rows = []
    trial = 0
    for s in range(n_seeds):
        for g in GRID:
            t_full = (t_full_by_rho or {}).get(g, 100.0)
            for arm in ("FULL", "BOUNDED"):
                if arm == "FULL":
                    t, cyc, bud = t_full, False, False
                else:
                    spec = (bounded_spec or {}).get(g)
                    if spec is None:
                        t = t_full * math.exp(lnr_by_rho[g])
                        cyc, bud = False, False
                    else:
                        t, cyc, bud = spec[s]
                rows.append({"trial_idx": trial, "seed_index": s,
                             "rho_eff": g, "arm": arm, "T": t,
                             "cycling": cyc, "budget_exhausted": bud,
                             "redraws": 0, "e0_inf": 1.5, "wall_s": 0.0})
                trial += 1
    return rows


def _yes_rows():
    return _fixture_rows(_kink_lnr())


def _censoring_rows():
    """Rules 1-4 pass, but the top cell's bounded median exists ONLY via
    the T := t_max convention (all 30 trials cycle) — rule 5 must
    adjudicate censoring geometry => FALSE."""
    lnr = _kink_lnr()
    t_full_084 = T_MAX / math.exp(lnr[0.84])  # puts ln R(0.84) on-curve
    return _fixture_rows(
        lnr,
        t_full_by_rho={0.84: t_full_084},
        bounded_spec={0.84: [(T_MAX, True, False)] * 30})


class FitMachinery(unittest.TestCase):
    def test_two_segment_fit_recovers_kink(self):
        fitter = analyze.PiecewiseFitter()
        y = np.array([_kink_lnr()[g] for g in GRID])
        fit = fitter.fit(y)
        self.assertFalse(fit["degenerate"])
        self.assertAlmostEqual(fit["rho_star"], 0.53, places=6)
        self.assertAlmostEqual(fit["slope_below"], 0.25, places=6)
        self.assertAlmostEqual(fit["slope_above"], 4.0, places=6)
        self.assertGreaterEqual(fit["delta_bic"], analyze.DELTA_BIC_MIN)

    def test_candidate_window_two_points_strictly_each_side(self):
        c = analyze.PiecewiseFitter().candidates
        # >= 2 of the 7 data points strictly each side => (0.32, 0.74)
        self.assertTrue(np.all(c > 0.32))
        self.assertTrue(np.all(c < 0.74))
        np.testing.assert_allclose(np.diff(c), 0.005, atol=1e-12)

    def test_bic_pinned_form(self):
        rng = np.random.default_rng(11)
        y = 0.5 * np.asarray(GRID) + rng.normal(0, 0.05, 7)
        fit = analyze.PiecewiseFitter().fit(y)
        n = 7
        self.assertAlmostEqual(
            fit["bic_1seg"],
            n * math.log(fit["rss_1seg"] / n) + 2 * math.log(n))
        self.assertAlmostEqual(
            fit["bic_2seg"],
            n * math.log(fit["rss_2seg"] / n) + 4 * math.log(n))
        self.assertAlmostEqual(fit["delta_bic"],
                               fit["bic_1seg"] - fit["bic_2seg"])

    def test_nonfinite_points_are_degenerate_never_coerced(self):
        y = np.array([0.1, 0.2, np.nan, 0.3, 0.4, 0.5, 0.6])
        fit = analyze.PiecewiseFitter().fit(y)
        self.assertTrue(fit["degenerate"])
        rules = analyze.rules123(fit, {g: 0.0 for g in GRID})
        self.assertFalse(rules["all_pass"])

    def test_rule2_interior_window_and_cells_above(self):
        base = {"degenerate": False, "delta_bic": 100.0, "rho_star": 0.53,
                "slope_below": 0.1, "slope_above": 4.0}
        clean = {g: 0.0 for g in GRID}
        r = analyze.rules123(base, clean)
        self.assertTrue(r["rule2_pass"])
        self.assertEqual(r["cells_above"], [0.63, 0.74])
        # below the interior window
        r = analyze.rules123({**base, "rho_star": 0.30}, clean)
        self.assertFalse(r["rule2_pass"])
        # window is closed at the top: rho* = 0.74 fails (< 0.74 LOCKED)
        r = analyze.rules123({**base, "rho_star": 0.74}, clean)
        self.assertFalse(r["rule2_pass"])
        # exactly 50% capped in a cell above fails (< 50% LOCKED)
        r = analyze.rules123(base, {**clean, 0.63: 0.50})
        self.assertFalse(r["rule2_pass"])

    def test_rule3_slope_floors(self):
        clean = {g: 0.0 for g in GRID}
        base = {"degenerate": False, "delta_bic": 100.0, "rho_star": 0.53}
        ok = analyze.rules123(
            {**base, "slope_below": 0.1, "slope_above": 2.0}, clean)
        self.assertTrue(ok["rule3_pass"])  # 2.0 >= 3 * max(0.1, 0.25)? no!
        # wait: 3 * 0.25 = 0.75 <= 2.0 -> passes; keep explicit:
        self.assertTrue(2.0 >= 3.0 * max(0.1, 0.25))
        bad_abs = analyze.rules123(
            {**base, "slope_below": 0.1, "slope_above": 1.9}, clean)
        self.assertFalse(bad_abs["rule3_pass"])  # absolute floor 2.0
        bad_ratio = analyze.rules123(
            {**base, "slope_below": 1.0, "slope_above": 2.5}, clean)
        self.assertFalse(bad_ratio["rule3_pass"])  # needs >= 3.0


class DecisionRules(unittest.TestCase):
    def test_yes_fixture_all_five_rules(self):
        s = analyze.build_summary(_yes_rows())
        self.assertEqual(s["verdict"], "YES")
        self.assertTrue(s["effect_confirmed"])
        self.assertAlmostEqual(s["value"], 0.53, places=6)
        for r in ("rule1", "rule2", "rule3", "rule4", "rule5"):
            self.assertTrue(s[r]["pass"], r)
        self.assertTrue(s["counts_match_lock"])
        self.assertEqual(s["rule4"]["B"], 1000)
        self.assertAlmostEqual(s["rule4"]["pass_fraction"], 1.0)
        self.assertAlmostEqual(s["rule4"]["iqr_rho_star"], 0.0)
        self.assertEqual(s["metric"], "slowdown_breakpoint_rho_eff")

    def test_no_fixture_linear_and_value_sentinel(self):
        lnr = {g: 1.0 * (g - 0.5) for g in GRID}
        bumps = dict(zip(GRID, [0.01, -0.01, 0.008, -0.008,
                                0.01, -0.01, 0.009]))
        s = analyze.build_summary(_fixture_rows(
            {g: lnr[g] + bumps[g] for g in GRID}))
        self.assertEqual(s["verdict"], "NO")
        self.assertFalse(s["effect_confirmed"])
        self.assertEqual(s["value"], -1.0)  # never a fabricated threshold
        # raw fit still reported regardless of verdict (LOCKED)
        self.assertIsNotNone(s["fit"]["rho_star"])
        self.assertIn("LOCKED", s["verdict_reason"])

    def test_no_fixture_slope_floor(self):
        s = analyze.build_summary(_fixture_rows(
            _kink_lnr(slope_above=1.0)))
        self.assertEqual(s["verdict"], "NO")
        self.assertEqual(s["value"], -1.0)
        self.assertTrue(s["rule1"]["pass"])   # kink is real (dBIC clears)
        self.assertFalse(s["rule3"]["pass"])  # 1.0 < absolute floor 2.0

    def test_censoring_only_breakpoint_adjudicated_false(self):
        s = analyze.build_summary(_censoring_rows())
        # rules 1-4 pass individually — the fixture is censoring-only
        self.assertTrue(s["rule1"]["pass"])
        self.assertTrue(s["rule2"]["pass"])
        self.assertTrue(s["rule3"]["pass"])
        self.assertTrue(s["rule4"]["pass"])
        self.assertFalse(s["rule5"]["pass"])
        self.assertEqual(s["verdict"], "NO")
        self.assertFalse(s["effect_confirmed"])
        self.assertEqual(s["value"], -1.0)
        self.assertIn("censoring geometry", s["verdict_reason"])
        self.assertEqual(s["rule5"]["empty_survivor_cells"], ["0.84"])
        # the named non-gating finding is present
        curve = s["cycling_fraction_vs_rho"]
        self.assertAlmostEqual(curve["0.84"]["capped_frac"], 1.0)
        self.assertAlmostEqual(curve["0.84"]["cycling_frac"], 1.0)
        self.assertAlmostEqual(curve["0.21"]["capped_frac"], 0.0)

    def test_counts_guard_blocks_confirmation(self):
        rows = _yes_rows()[:-1]  # drop one trial from the last cell
        s = analyze.build_summary(rows)
        self.assertFalse(s["counts_match_lock"])
        self.assertFalse(s["effect_confirmed"])
        self.assertEqual(s["verdict"], "NO")
        self.assertIn("deviate", s["verdict_reason"])

    def test_error_rows_excluded_and_counted(self):
        rows = _yes_rows() + [{"trial_idx": 999, "seed_index": 0,
                               "rho_eff": 0.21, "arm": "BOUNDED",
                               "error": "boom", "wall_s": 0.0}]
        s = analyze.build_summary(rows)
        self.assertEqual(s["n_errors"], 1)
        self.assertEqual(s["verdict"], "YES")  # valid cells still locked-n

    def test_h0_construction_pinned_arithmetic(self):
        s = analyze.build_summary(_yes_rows())
        h0 = s["h0_construction"]
        i = GRID.index(0.53)
        e0 = 1.5
        r_dead = 0.53 * (DELTA / 2.0) / (1.0 - 0.53)
        self.assertAlmostEqual(h0["r_dead"][i], r_dead)
        self.assertAlmostEqual(h0["t_pred_bounded"][i],
                               math.log(e0 / r_dead) / (-math.log(0.53)))
        self.assertAlmostEqual(h0["t_pred_full"][i],
                               math.log(e0 / 1e-6) / (-math.log(0.53)))
        self.assertAlmostEqual(
            h0["ln_r_pred"][i],
            math.log(h0["t_pred_bounded"][i] / h0["t_pred_full"][i]))
        # both curves + the max-gap scalar are reported (LOCKED)
        for key in ("ln_r_pred", "ln_r_observed", "t_pred_bounded",
                    "t_pred_full", "abs_ln_gap"):
            self.assertEqual(len(h0[key]), 7)
        self.assertIsNotNone(h0["max_abs_ln_gap"])
        self.assertIn("max_abs_ln_gap_below_rho_star", h0)

    def test_summary_md_line1_and_scope_limit_verbatim(self):
        s = analyze.build_summary(_yes_rows())
        md = analyze.render_markdown(s)
        self.assertTrue(md.splitlines()[0].startswith("Verdict=YES."))
        self.assertIn(analyze.SCOPE_LIMIT_NOTE, md)
        self.assertEqual(s["scope_limit"], analyze.SCOPE_LIMIT_NOTE)
        no = analyze.build_summary(_fixture_rows(
            {g: 0.0 for g in GRID}))
        self.assertTrue(analyze.render_markdown(no)
                        .splitlines()[0].startswith("Verdict=NO."))


class BridgeOutcomeShape(unittest.TestCase):
    REQUIRED_KEYS = {"experiment_id", "metric", "value", "summary",
                     "results_path", "trials", "effect_confirmed"}

    def _write(self, rows: list[dict], tmp: Path) -> tuple[Path, Path]:
        summary = analyze.build_summary(rows)
        sp = tmp / "summary.json"
        sp.write_text(json.dumps(summary))
        tp = tmp / "trials.jsonl"
        with open(tp, "w") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        return sp, tp

    def test_outcome_shape_yes(self):
        with tempfile.TemporaryDirectory() as td:
            sp, tp = self._write(_yes_rows(), Path(td))
            out = loop_bridge.build_experiment_outcome(
                summary_path=sp, trials_path=tp)
        self.assertTrue(self.REQUIRED_KEYS.issubset(out.keys()))
        self.assertEqual(out["experiment_id"], "exp012_lqg_spectral")
        self.assertEqual(out["metric"], "slowdown_breakpoint_rho_eff")
        self.assertAlmostEqual(out["value"], 0.53, places=6)
        self.assertTrue(out["summary"].startswith("Verdict=YES."))
        self.assertEqual(out["trials"], 420)
        self.assertTrue(out["effect_confirmed"])
        self.assertEqual(
            out["results_path"],
            "experiments/exp012_lqg_spectral/results/summary.md")
        # the binding scope limit must reach the ledger event — it rides
        # the outcome summary VERBATIM
        self.assertIn(analyze.SCOPE_LIMIT_NOTE, out["summary"])

    def test_outcome_shape_no(self):
        with tempfile.TemporaryDirectory() as td:
            sp, tp = self._write(
                _fixture_rows({g: 0.1 * (g - 0.5) for g in GRID}), Path(td))
            out = loop_bridge.build_experiment_outcome(
                summary_path=sp, trials_path=tp)
        self.assertTrue(out["summary"].startswith("Verdict=NO."))
        self.assertEqual(out["value"], -1.0)
        self.assertFalse(out["effect_confirmed"])
        self.assertIn(analyze.SCOPE_LIMIT_NOTE, out["summary"])

    def test_missing_summary_is_fatal(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(SystemExit):
                loop_bridge.build_experiment_outcome(
                    summary_path=Path(td) / "nope.json",
                    trials_path=Path(td) / "trials.jsonl")

    def test_topic_seed_carries_claim_text(self):
        with tempfile.TemporaryDirectory() as td:
            sp, tp = self._write(_yes_rows(), Path(td))
            out = loop_bridge.build_experiment_outcome(
                summary_path=sp, trials_path=tp)
        topic = loop_bridge.build_topic_seed(out)
        self.assertIn("spectral radius", topic)
        self.assertIn("bounded rationality", topic.lower())
        self.assertIn("surrogate", topic)
        self.assertIn("Verdict=", topic)

    def test_calls_log_env_set_before_lazy_orchestrator_import(self):
        # Mirrors tests/test_experiment_log_isolation.py's contract (which
        # already lists exp012) so the invariant is pinned here too.
        src_path = (REPO_ROOT / "experiments" / "exp012_lqg_spectral"
                    / "loop_bridge.py")
        lines = src_path.read_text().splitlines()
        env_idx = next(i for i, ln in enumerate(lines)
                       if 'os.environ["LOOP_V0_CALLS_LOG"]' in ln
                       and "=" in ln)
        imp_idx = next(i for i, ln in enumerate(lines) if ln.lstrip()
                       .startswith("from orchestrator.nara import run_iteration"))
        self.assertLess(env_idx, imp_idx)
        self.assertIn("log_path=CALLS_LOG_PATH", src_path.read_text())


if __name__ == "__main__":
    unittest.main()
