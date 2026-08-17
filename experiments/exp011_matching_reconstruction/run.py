#!/usr/bin/env python3
"""exp011 — stable-matching preference-reconstruction driver.

Tests the L1 claim (cl-iter-2026-07-15-001): "An adversary can
reconstruct the preference rankings of a specific agent by observing
the deviation in the resulting stable matching when a small, targeted
subset of agent preferences is perturbed."

Fully numerical (synthetic tier): deterministic man-proposing
Gale–Shapley at n=12, uniform-random profiles, ZERO LLM calls. Prereg
(LOCKED): experiments/PREREG_l2block_2026-08-17.md §exp011.

Per trial (fresh derived seed = --seed + trial_idx): fresh uniform
profiles + uniform receiving-side target t; the unperturbed baseline
matching is computed first and shown to the adversary; then the
two-mode attack (attack.py) under budget Q_max=44 with <= 2 perturbed
lists per query. Rows append to trials.jsonl, one per trial; errors are
recorded as rows and never abort the run.

Reproduce (headline, milliseconds-scale — no model needed):
    ./.venv-chroma/bin/python experiments/exp011_matching_reconstruction/run.py
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy.stats import kendalltau

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from experiments.exp011_matching_reconstruction.attack import (  # noqa: E402
    N, Q_MAX, run_attack, tau_scored)
from experiments.exp011_matching_reconstruction.matching import (  # noqa: E402
    gale_shapley)
from orchestrator import active_run  # noqa: E402
from orchestrator.exp_orchestrator_rows import emit_task_triple  # noqa: E402

EXP_DIR = Path(__file__).resolve().parent
RESULTS_DIR = EXP_DIR / "results"
TRIALS_PATH = RESULTS_DIR / "trials.jsonl"

N_NULL_PERMUTATIONS = 100  # chance baseline draw count (prereg)
LAST5_WINDOW = 5


def _uniform_profile(rng: np.random.Generator, n: int) -> list[list[int]]:
    return [[int(x) for x in rng.permutation(n)] for _ in range(n)]


def _full_tau(true_ranking: list[int], candidate: list[int]) -> float:
    """Plain Kendall tau between two complete rankings (all 66 pairs
    decided) — the null draws, not the scored attack tau."""
    pos_true = {m: i for i, m in enumerate(true_ranking)}
    pos_cand = {m: i for i, m in enumerate(candidate)}
    n = len(true_ranking)
    x = [pos_true[m] for m in range(n)]
    y = [pos_cand[m] for m in range(n)]
    return float(kendalltau(x, y).statistic)


def run_one_trial(trial_idx: int, base_seed: int) -> dict:
    """One full trial. Pure given (trial_idx, base_seed): per-trial
    derived seed (exp009 pattern) makes rows reproducible bit-for-bit.
    The driver appends wall_s."""
    trial_seed = base_seed + trial_idx
    rng = np.random.default_rng(trial_seed)
    men_prefs = _uniform_profile(rng, N)
    women_prefs = _uniform_profile(rng, N)
    t = int(rng.integers(N))  # uniform receiving-side target

    baseline = gale_shapley(men_prefs, women_prefs)  # shown to adversary

    def oracle(perturbed_men_prefs):
        # The attack only ever sees oracle outputs; women_prefs (and so
        # t's true ranking) stay on this side of the boundary.
        return gale_shapley(perturbed_men_prefs, women_prefs)

    res = run_attack(oracle, men_prefs, t, baseline, n=N, q_max=Q_MAX)

    true_ranking = women_prefs[t]  # best-first
    tau, unresolved, _conc, _disc = tau_scored(res["closure"], true_ranking, N)
    queries_used = res["queries_used"]
    constraints_recorded = len(res["constraints"])
    devs = [q["deviation_size"] for q in res["query_log"]]
    last5 = sum(q["new_constraints"]
                for q in res["query_log"][-LAST5_WINDOW:])
    # 1-based rank of the baseline match (best natural proposer) in t's
    # true ranking — the frontier-ceiling stratification key.
    rank_best = true_ranking.index(baseline[t]) + 1
    null_taus = [
        _full_tau(true_ranking, [int(x) for x in rng.permutation(N)])
        for _ in range(N_NULL_PERMUTATIONS)
    ]
    return {
        "trial_idx": trial_idx,
        "seed": trial_seed,
        "target": t,
        "kendall_tau_scored": round(tau, 6),
        "queries_used": queries_used,
        "unresolved_pairs": unresolved,
        "bits_per_query": round(constraints_recorded / queries_used, 6),
        "median_deviation_size": float(np.median(devs)),
        "rank_t_best_natural_proposer": rank_best,
        "null_tau_p95": round(float(np.percentile(null_taus, 95)), 6),
        "constraints_recorded": constraints_recorded,
        "constraints_in_last5_queries": last5,
    }


# --- driver ------------------------------------------------------------

def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="exp011 stable-matching reconstruction driver")
    p.add_argument("--trials", type=int, default=40,
                   help="number of trials (default 40, prereg)")
    p.add_argument("--seed", type=int, default=20260817,
                   help="base seed; trial i uses seed + i")
    p.add_argument("--out", type=str, default=str(TRIALS_PATH),
                   help="output JSONL path (default results/trials.jsonl)")
    args = p.parse_args(argv)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    t_start = _utcnow_iso()
    run_id = f"exp011_matching_reconstruction_{t_start}"
    # Telemetry is optional plumbing: a telemetry failure must never
    # abort a numerical run (exp003 pattern, try/except-wrapped).
    try:
        active_run.write_active_run(
            run_id, "experiment", "exp011 matching reconstruction",
            total=args.trials, unit="trial")
    except Exception:
        pass
    print(f"=== exp011 run starting at {t_start} ===", flush=True)
    print(f"=== {args.trials} trials, n={N}, Q_max={Q_MAX}, "
          f"base seed {args.seed}; zero LLM calls ===", flush=True)
    print(f"=== writing per-trial JSONL to {out_path} ===", flush=True)

    f = open(out_path, "w")
    t0_total = time.perf_counter()
    n_done = 0
    n_err = 0
    try:
        for trial_idx in range(args.trials):
            t0 = time.perf_counter()
            try:
                row = run_one_trial(trial_idx, args.seed)
            except Exception as exc:  # noqa: BLE001 — record + continue
                wall_s = time.perf_counter() - t0
                err_row = {
                    "trial_idx": trial_idx,
                    "seed": args.seed + trial_idx,
                    "error": f"{type(exc).__name__}: {exc}",
                    "wall_s": round(wall_s, 4),
                }
                f.write(json.dumps(err_row) + "\n")
                f.flush()
                n_err += 1
                narration = (f"[{trial_idx + 1}/{args.trials}] ERROR: "
                             f"{err_row['error']}")
                print(narration, flush=True)
                try:
                    active_run.update_active_run(
                        done=trial_idx + 1, narration=narration, n_err=n_err)
                    emit_task_triple(
                        task_id=f"exp011_t{trial_idx}",
                        task_type="experiment_trial", status="error",
                        duration_ms=wall_s * 1000.0, run_id=run_id)
                except Exception:
                    pass
                continue
            wall_s = time.perf_counter() - t0
            row["wall_s"] = round(wall_s, 4)
            f.write(json.dumps(row) + "\n")
            f.flush()
            n_done += 1
            narration = (f"[{trial_idx + 1}/{args.trials}] "
                         f"tau={row['kendall_tau_scored']:+.3f} "
                         f"q={row['queries_used']} "
                         f"unresolved={row['unresolved_pairs']} "
                         f"rank_f={row['rank_t_best_natural_proposer']}")
            print(narration, flush=True)
            try:
                active_run.update_active_run(
                    done=trial_idx + 1, narration=narration, n_err=n_err)
                emit_task_triple(
                    task_id=f"exp011_t{trial_idx}",
                    task_type="experiment_trial", status="passed",
                    duration_ms=wall_s * 1000.0, run_id=run_id)
            except Exception:
                pass
    finally:
        f.close()
        try:
            active_run.clear_active_run()
        except Exception:
            pass

    wall_s_total = time.perf_counter() - t0_total
    print(f"=== exp011 run done at {_utcnow_iso()}; ok={n_done} "
          f"err={n_err} wall={wall_s_total:.1f}s ===", flush=True)
    return 0 if n_err == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
