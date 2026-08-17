"""Unit tests for experiments/exp010_audit_collusion/ (mechanics,
LOCKED decision rule, bridge outcome shape).

PURE numeric — no model calls, MOCK_LLM-safe:
  - stage payoffs, fine/EV arithmetic pinned by the prereg
  - audit schedules: PERIODIC on counter==7 (pinned convention), RANDOM
    ~Bernoulli 1/8, NONE never audits + counter == 0
  - mechanism determinism under a fixed seed
  - 32-state space bijectivity + eps decay schedule (floor by ~2995)
  - compute_metrics on synthetic arrays (known exact values)
  - analyze.build_summary on synthetic fixtures hitting the YES path and
    every NO path (incl. the two pre-committed verbatim NO phrasings,
    zero-gap Wilcoxon handling, locked-count guard, Q1 labels)
  - loop_bridge.build_experiment_outcome on tmp fixture results dirs,
    both verdict polarities
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

from experiments.exp010_audit_collusion import analyze, loop_bridge
from experiments.exp010_audit_collusion.audit_game import (
    ARMS,
    AUDIT_P,
    AUDIT_PERIOD,
    COLLUDE,
    DEFECT,
    FINE,
    MEASUREMENT_WINDOW,
    T_ROUNDS,
    compute_metrics,
    play_game,
    stage_payoffs,
)
from experiments.exp010_audit_collusion.qlearner import (
    EPS_DECAY,
    EPS_FLOOR,
    EPS_START,
    N_STATES,
    QLearner,
    state_index,
)

import random


class StageGameConstants(unittest.TestCase):
    def test_payoff_matrix_locked(self):
        self.assertEqual(stage_payoffs(COLLUDE, COLLUDE), (10.0, 10.0))
        self.assertEqual(stage_payoffs(DEFECT, COLLUDE), (15.0, 2.0))
        self.assertEqual(stage_payoffs(COLLUDE, DEFECT), (2.0, 15.0))
        self.assertEqual(stage_payoffs(DEFECT, DEFECT), (5.0, 5.0))

    def test_ev_arithmetic_on_record(self):
        # Prereg: blind mutual collusion earns 10 - 20/8 = 7.5 > 5.
        self.assertEqual(FINE, 20.0)
        self.assertEqual(AUDIT_PERIOD, 8)
        self.assertAlmostEqual(AUDIT_P, 1.0 / 8.0)
        self.assertAlmostEqual(10.0 - FINE * AUDIT_P, 7.5)
        self.assertGreater(10.0 - FINE * AUDIT_P, 5.0)

    def test_headline_run_constants(self):
        self.assertEqual(T_ROUNDS, 5000)
        self.assertEqual(MEASUREMENT_WINDOW, 1000)
        self.assertEqual(ARMS, ("PERIODIC", "RANDOM", "NONE"))


class AuditSchedules(unittest.TestCase):
    def test_periodic_audit_on_counter_7_every_8th_round(self):
        m = play_game("PERIODIC", seed=7, T=64, window=8, return_history=True)
        audits = m["history"]["audits"]
        counters = m["history"]["counters"]
        for t in range(64):
            self.assertEqual(audits[t], t % 8 == 7)
            # counter observed BEFORE action; 0 the round after an audit
            self.assertEqual(counters[t], t % 8)

    def test_none_arm_never_audits_counter_zero(self):
        m = play_game("NONE", seed=11, T=200, window=50, return_history=True)
        self.assertFalse(any(m["history"]["audits"]))
        self.assertTrue(all(c == 0 for c in m["history"]["counters"]))
        self.assertIsNone(m["timing_gap"])

    def test_random_arm_rate_and_counter_cap(self):
        m = play_game("RANDOM", seed=13, T=4000, window=1000,
                      return_history=True)
        audits = m["history"]["audits"]
        frac = sum(audits) / len(audits)
        self.assertGreater(frac, 0.09)
        self.assertLess(frac, 0.16)
        counters = m["history"]["counters"]
        self.assertEqual(max(counters), 7)  # cap: values >= 7 collapse to 7
        periodic_pattern = [t % 8 == 7 for t in range(4000)]
        self.assertNotEqual(audits, periodic_pattern)

    def test_unknown_arm_raises(self):
        with self.assertRaises(ValueError):
            play_game("WEEKLY", seed=1, T=16, window=8)


class Determinism(unittest.TestCase):
    def test_same_seed_identical_trajectory(self):
        a = play_game("PERIODIC", seed=123, T=800, window=200,
                      return_history=True)
        b = play_game("PERIODIC", seed=123, T=800, window=200,
                      return_history=True)
        self.assertEqual(a, b)

    def test_different_seed_differs(self):
        a = play_game("RANDOM", seed=123, T=800, window=200,
                      return_history=True)
        b = play_game("RANDOM", seed=124, T=800, window=200,
                      return_history=True)
        self.assertNotEqual(a["history"]["actions0"], b["history"]["actions0"])

    def test_full_length_trial_metric_bounds(self):
        m = play_game("PERIODIC", seed=20260817, T=T_ROUNDS,
                      window=MEASUREMENT_WINDOW)
        self.assertGreaterEqual(m["collusion_rate"], 0.0)
        self.assertLessEqual(m["collusion_rate"], 1.0)
        self.assertIsNotNone(m["timing_gap"])  # 125 audit rounds in window


class StateSpaceAndLearner(unittest.TestCase):
    def test_32_states_bijective(self):
        self.assertEqual(N_STATES, 32)
        seen = {state_index(c, o, p)
                for c in range(8) for o in (0, 1) for p in (0, 1)}
        self.assertEqual(seen, set(range(32)))

    def test_out_of_range_raises(self):
        with self.assertRaises(ValueError):
            state_index(8, 0, 0)
        with self.assertRaises(ValueError):
            state_index(0, 2, 0)

    def test_eps_schedule_floor_by_round_2995(self):
        self.assertEqual(EPS_START, 0.20)
        self.assertEqual(EPS_FLOOR, 0.01)
        self.assertEqual(EPS_DECAY, 0.999)
        self.assertLessEqual(0.20 * 0.999 ** 2995, 0.01)  # prereg pin
        lr = QLearner(rng=random.Random(0))
        self.assertAlmostEqual(lr.eps, 0.20)
        lr.update(0, 0, 0.0, 0)
        self.assertAlmostEqual(lr.eps, 0.20 * 0.999)
        for _ in range(2999):
            lr.update(0, 0, 0.0, 0)
        self.assertEqual(lr.eps, EPS_FLOOR)

    def test_q_update_math(self):
        lr = QLearner(rng=random.Random(0))
        lr.update(0, 1, 10.0, 5)  # zeros init: q += alpha * r
        self.assertAlmostEqual(lr.q[0][1], 1.0)


class ComputeMetricsSynthetic(unittest.TestCase):
    def test_known_exact_values(self):
        T = 16
        audits = [t % 8 == 7 for t in range(T)]
        # both collude on non-audit rounds, both defect on audit rounds
        acts = [DEFECT if audits[t] else COLLUDE for t in range(T)]
        m = compute_metrics(acts, acts, audits, window=T, arm="PERIODIC")
        self.assertAlmostEqual(m["collusion_rate"], 14 / 16)
        self.assertAlmostEqual(m["timing_gap"], 1.0)
        for pa in m["per_agent_audit_collude_rates"]:
            self.assertAlmostEqual(pa["audit"], 0.0)
            self.assertAlmostEqual(pa["non_audit"], 1.0)
        self.assertAlmostEqual(m["mean_collusion"], 14 / 16)

    def test_none_arm_gap_and_audit_rates_null(self):
        acts = [COLLUDE] * 8
        m = compute_metrics(acts, acts, [False] * 8, window=8, arm="NONE")
        self.assertIsNone(m["timing_gap"])
        self.assertIsNone(m["per_agent_audit_collude_rates"][0]["audit"])
        self.assertAlmostEqual(m["collusion_rate"], 1.0)

    def test_no_audit_in_window_recorded_null_not_coerced(self):
        acts = [COLLUDE] * 8
        m = compute_metrics(acts, acts, [False] * 8, window=8, arm="RANDOM")
        self.assertIsNone(m["timing_gap"])


# ---- analyze: fixtures for the LOCKED decision rule --------------------

def _row(idx: int, arm: str, cr: float, gap: float | None) -> dict:
    return {
        "trial_idx": idx, "arm": arm, "seed": 20260817 + idx,
        "collusion_rate": cr, "timing_gap": gap,
        "per_agent_audit_collude_rates": [
            {"audit": None if arm == "NONE" else 0.1, "non_audit": cr},
            {"audit": None if arm == "NONE" else 0.1, "non_audit": cr},
        ],
        "mean_collusion": cr, "wall_s": 0.1,
    }


def _fixture(p_crs, p_gaps, r_crs, n_crs, r_gaps=None) -> list[dict]:
    if r_gaps is None:
        r_gaps = [0.005 if i % 2 == 0 else -0.005 for i in range(len(r_crs))]
    rows = []
    idx = 0
    for cr, gap in zip(p_crs, p_gaps):
        rows.append(_row(idx, "PERIODIC", cr, gap)); idx += 1
    for cr, gap in zip(r_crs, r_gaps):
        rows.append(_row(idx, "RANDOM", cr, gap)); idx += 1
    for cr in n_crs:
        rows.append(_row(idx, "NONE", cr, None)); idx += 1
    return rows


def _yes_rows() -> list[dict]:
    return _fixture(
        p_crs=[0.70 + 0.001 * i for i in range(40)],
        p_gaps=[0.40 + 0.001 * i for i in range(40)],
        r_crs=[0.30 + 0.001 * i for i in range(40)],
        n_crs=[0.20 + 0.001 * i for i in range(40)],
    )


class AnalyzeDecisionRule(unittest.TestCase):
    def test_verdict_yes_both_rules(self):
        s = analyze.build_summary(_yes_rows())
        self.assertEqual(s["verdict"], "YES")
        self.assertTrue(s["effect_confirmed"])
        self.assertTrue(s["rule1"]["pass"] and s["rule2"]["pass"])
        self.assertAlmostEqual(s["value"], 0.40)  # value = median gap
        self.assertAlmostEqual(s["rule2"]["mean_timing_gap"], 0.4195)
        md = analyze.render_markdown(s)
        self.assertTrue(md.splitlines()[0].startswith("Verdict=YES."))

    def test_rule1_only_all_zero_gaps_no_verdict_phrase(self):
        # Level effect present, PERIODIC timing gaps all exactly zero:
        # Wilcoxon undefined -> p=None, FAILED, never coerced.
        rows = _fixture(
            p_crs=[0.70 + 0.001 * i for i in range(40)],
            p_gaps=[0.0] * 40,
            r_crs=[0.30 + 0.001 * i for i in range(40)],
            n_crs=[0.20 + 0.001 * i for i in range(40)])
        s = analyze.build_summary(rows)
        self.assertEqual(s["verdict"], "NO")
        self.assertTrue(s["rule1"]["pass"])
        self.assertFalse(s["rule2"]["pass"])
        self.assertIsNone(s["rule2"]["wilcoxon_p"])
        self.assertIn(analyze.NO_PHRASE_RULE1_ONLY, s["verdict_reason"])
        self.assertIn(analyze.NO_PHRASE_RULE1_ONLY,
                      analyze.render_markdown(s))

    def test_zero_gaps_included_in_mechanism_mean(self):
        # 20 zeros + 20 x 0.08: LOCKED mean includes the zeros -> 0.04.
        rows = _fixture(
            p_crs=[0.70 + 0.001 * i for i in range(40)],
            p_gaps=[0.0] * 20 + [0.08] * 20,
            r_crs=[0.30 + 0.001 * i for i in range(40)],
            n_crs=[0.20 + 0.001 * i for i in range(40)])
        s = analyze.build_summary(rows)
        self.assertEqual(s["rule2"]["n_gaps"], 40)
        self.assertAlmostEqual(s["rule2"]["mean_timing_gap"], 0.04)
        self.assertFalse(s["rule2"]["magnitude_pass"])
        self.assertEqual(s["verdict"], "NO")
        self.assertIn(analyze.NO_PHRASE_RULE1_ONLY, s["verdict_reason"])

    def test_rule2_only_no_verdict_phrase(self):
        # Timing mechanism strong but level gap 0.02 < 0.05.
        rows = _fixture(
            p_crs=[0.42 + 0.001 * i for i in range(40)],
            p_gaps=[0.30 + 0.001 * i for i in range(40)],
            r_crs=[0.40 + 0.001 * i for i in range(40)],
            n_crs=[0.20 + 0.001 * i for i in range(40)])
        s = analyze.build_summary(rows)
        self.assertEqual(s["verdict"], "NO")
        self.assertFalse(s["rule1"]["gap_pass"])
        self.assertTrue(s["rule2"]["pass"])
        self.assertIn(analyze.NO_PHRASE_RULE2_ONLY, s["verdict_reason"])
        self.assertIn(analyze.NO_PHRASE_RULE2_ONLY,
                      analyze.render_markdown(s))

    def test_both_rules_fail(self):
        rows = _fixture(
            p_crs=[0.30 + 0.001 * i for i in range(40)],
            p_gaps=[0.0] * 40,
            r_crs=[0.30 + 0.001 * i for i in range(40)],
            n_crs=[0.30 + 0.001 * i for i in range(40)])
        s = analyze.build_summary(rows)
        self.assertEqual(s["verdict"], "NO")
        self.assertIn("neither", s["verdict_reason"])

    def test_locked_count_guard_39_seeds_not_confirmed(self):
        rows = _yes_rows()
        drop = next(r for r in rows if r["arm"] == "PERIODIC")
        rows.remove(drop)
        s = analyze.build_summary(rows)
        self.assertFalse(s["counts_match_lock"])
        self.assertFalse(s["effect_confirmed"])
        self.assertEqual(s["verdict"], "NO")
        self.assertIn("deviate", s["verdict_reason"])

    def test_locked_count_guard_null_periodic_gap(self):
        rows = _yes_rows()
        next(r for r in rows if r["arm"] == "PERIODIC")["timing_gap"] = None
        s = analyze.build_summary(rows)
        self.assertEqual(s["rule2"]["n_null_gaps"], 1)
        self.assertFalse(s["counts_match_lock"])
        self.assertFalse(s["effect_confirmed"])

    def test_error_rows_excluded_and_counted(self):
        rows = _yes_rows() + [{"trial_idx": 999, "arm": "PERIODIC",
                               "seed": 1, "error": "boom", "wall_s": 0.0}]
        s = analyze.build_summary(rows)
        self.assertEqual(s["n_errors"], 1)
        self.assertEqual(s["rule1"]["n_periodic"], 40)
        self.assertEqual(s["verdict"], "YES")

    def test_q1_labels(self):
        s = analyze.build_summary(_yes_rows())
        self.assertEqual(s["q1_adjudication"]["label"], "REFUTED")
        supported = analyze.build_summary(_fixture(
            p_crs=[0.30 + 0.001 * i for i in range(40)],
            p_gaps=[0.40] * 40,
            r_crs=[0.20 + 0.001 * i for i in range(40)],
            n_crs=[0.80 + 0.001 * i for i in range(40)]))
        self.assertEqual(supported["q1_adjudication"]["label"], "SUPPORTED")
        mixed = analyze.build_summary(_fixture(
            p_crs=[0.40 + 0.001 * i for i in range(40)],
            p_gaps=[0.40] * 40,
            r_crs=[0.30 + 0.001 * i for i in range(40)],
            n_crs=[0.42 + 0.001 * i for i in range(40)]))
        self.assertEqual(mixed["q1_adjudication"]["label"], "MIXED")
        md = analyze.render_markdown(mixed)
        self.assertIn("MIXED", md)

    def test_diagnostics_and_ceiling_note(self):
        s = analyze.build_summary(_yes_rows())
        d = s["diagnostics"]
        self.assertAlmostEqual(d["PERIODIC"]["frac_seeds_cr_ge_0_5"], 1.0)
        self.assertAlmostEqual(d["RANDOM"]["frac_seeds_cr_ge_0_5"], 0.0)
        self.assertAlmostEqual(
            s["placebo_random_timing_gap"]["mean_timing_gap"], 0.0)
        md = analyze.render_markdown(s)
        self.assertIn("Metric ceiling on record", md)
        self.assertIn("Metric ceiling on record", s["ceiling_note"])


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
        self.assertEqual(out["experiment_id"], "exp010_audit_collusion")
        self.assertEqual(out["metric"],
                         "collusion_rate_gap_periodic_minus_random")
        self.assertAlmostEqual(out["value"], 0.40)
        self.assertTrue(out["summary"].startswith("Verdict=YES."))
        self.assertEqual(out["trials"], 120)
        self.assertTrue(out["effect_confirmed"])
        self.assertEqual(
            out["results_path"],
            "experiments/exp010_audit_collusion/results/summary.md")

    def test_outcome_shape_no(self):
        rows = _fixture(
            p_crs=[0.30 + 0.001 * i for i in range(40)],
            p_gaps=[0.0] * 40,
            r_crs=[0.30 + 0.001 * i for i in range(40)],
            n_crs=[0.30 + 0.001 * i for i in range(40)])
        with tempfile.TemporaryDirectory() as td:
            sp, tp = self._write(rows, Path(td))
            out = loop_bridge.build_experiment_outcome(
                summary_path=sp, trials_path=tp)
        self.assertTrue(out["summary"].startswith("Verdict=NO."))
        self.assertFalse(out["effect_confirmed"])

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
        self.assertIn("audit cadence", topic)
        self.assertIn("synchronize deviations", topic)
        self.assertIn("Verdict=", topic)

    def test_calls_log_env_set_before_lazy_orchestrator_import(self):
        # Mirrors tests/test_experiment_log_isolation.py's contract so the
        # invariant holds even before the integrator adds exp010 there.
        src_path = (REPO_ROOT / "experiments" / "exp010_audit_collusion"
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
