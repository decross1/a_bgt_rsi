#!/usr/bin/env python3
"""exp010 — audit-cadence collusion driver (fully numerical, zero LLM calls).

Tests the L1 claim cl-iter-2026-07-13-001: periodic audits increase
collusion rates in non-equilibrium markets because a predictable audit
cadence lets agents synchronize deviations into oversight gaps. LOCKED
design: experiments/PREREG_l2block_2026-08-17.md §exp010_audit_collusion.

Design: repeated 2-player pricing game, T=5000 rounds, two independent
tabular Q-learners per trial, three audit arms (PERIODIC / RANDOM / NONE)
at equal expected audit frequency 1/8, 40 seeds per arm -> 120 trial
rows. Metrics over the LAST 1000 rounds. Per-trial seed =
base + arm_index*1000 + seed_index (arm order PERIODIC, RANDOM, NONE).

Errors are recorded as rows and never abort the run; no metric is ever
coerced (inviolate rule 4).

Reproduce (pure numeric — safe under MOCK_LLM; runs in ~seconds):
    ./.venv-chroma/bin/python experiments/exp010_audit_collusion/run.py
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from orchestrator import active_run  # noqa: E402
from orchestrator.exp_orchestrator_rows import emit_task_triple  # noqa: E402
from experiments.exp010_audit_collusion.audit_game import (  # noqa: E402
    ARMS,
    MEASUREMENT_WINDOW,
    T_ROUNDS,
    play_game,
)

EXP_DIR = Path(__file__).resolve().parent
RESULTS_DIR = EXP_DIR / "results"
TRIALS_PATH = RESULTS_DIR / "trials.jsonl"

SEED_DEFAULT = 20260817
TRIALS_PER_ARM_DEFAULT = 40  # LOCKED: 40 seeds x 3 arms = 120 rows
ARM_SEED_STRIDE = 1000       # per-trial seed = base + arm_index*1000 + seed_index


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _telemetry(fn, *args, **kwargs) -> None:
    # UI-only side channel: telemetry must never abort a numeric run.
    try:
        fn(*args, **kwargs)
    except Exception:  # noqa: BLE001
        pass


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="exp010 audit-collusion driver")
    p.add_argument("--trials", type=int, default=TRIALS_PER_ARM_DEFAULT,
                   help="seeds per arm (default 40; LOCKED headline run)")
    p.add_argument("--seed", type=int, default=SEED_DEFAULT,
                   help="base seed (default 20260817)")
    p.add_argument("--out", type=str, default=str(TRIALS_PATH),
                   help="output JSONL path (default results/trials.jsonl)")
    args = p.parse_args(argv)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    total = args.trials * len(ARMS)
    t_start = _utcnow_iso()
    run_id = f"exp010_audit_collusion_{t_start}"
    _telemetry(active_run.write_active_run,
               run_id, "experiment", "exp010 audit-cadence collusion",
               total=total, unit="trial", model=None)
    print(f"=== exp010 run starting at {t_start} ===", flush=True)
    print(f"=== arms={list(ARMS)} x {args.trials} seeds -> {total} trials; "
          f"T={T_ROUNDS} rounds, window={MEASUREMENT_WINDOW}; "
          f"ZERO LLM calls ===", flush=True)
    print(f"=== writing per-trial JSONL to {out_path} ===", flush=True)

    f = open(out_path, "w")
    t0_total = time.perf_counter()
    n_done = 0
    n_err = 0
    try:
        trial_idx = 0
        for arm_index, arm in enumerate(ARMS):
            for seed_index in range(args.trials):
                trial_seed = args.seed + arm_index * ARM_SEED_STRIDE + seed_index
                t0 = time.perf_counter()
                try:
                    m = play_game(arm, trial_seed,
                                  T=T_ROUNDS, window=MEASUREMENT_WINDOW)
                except Exception as exc:  # noqa: BLE001 — record + continue
                    wall_s = time.perf_counter() - t0
                    err_row = {
                        "trial_idx": trial_idx,
                        "arm": arm,
                        "seed": trial_seed,
                        "error": f"{type(exc).__name__}: {exc}",
                        "wall_s": round(wall_s, 3),
                    }
                    f.write(json.dumps(err_row) + "\n")
                    f.flush()
                    n_err += 1
                    narration = (f"[{trial_idx + 1}/{total}] {arm} ERROR: "
                                 f"{err_row['error']} ({wall_s:.2f}s)")
                    print(narration, flush=True)
                    _telemetry(active_run.update_active_run,
                               done=trial_idx + 1, narration=narration,
                               n_err=n_err)
                    _telemetry(emit_task_triple,
                               task_id=f"exp010_{arm}_s{seed_index}",
                               task_type="experiment_trial", status="error",
                               duration_ms=wall_s * 1000.0, run_id=run_id)
                    trial_idx += 1
                    continue
                wall_s = time.perf_counter() - t0
                row = {
                    "trial_idx": trial_idx,
                    "arm": arm,
                    "seed": trial_seed,
                    "collusion_rate": m["collusion_rate"],
                    "timing_gap": m["timing_gap"],
                    "per_agent_audit_collude_rates":
                        m["per_agent_audit_collude_rates"],
                    "mean_collusion": m["mean_collusion"],
                    "wall_s": round(wall_s, 3),
                }
                f.write(json.dumps(row) + "\n")
                f.flush()
                n_done += 1
                gap = m["timing_gap"]
                narration = (f"[{trial_idx + 1}/{total}] {arm} seed={trial_seed} "
                             f"collusion_rate={m['collusion_rate']:.3f} "
                             f"timing_gap="
                             f"{'-' if gap is None else format(gap, '.3f')} "
                             f"({wall_s:.2f}s)")
                print(narration, flush=True)
                _telemetry(active_run.update_active_run,
                           done=trial_idx + 1, narration=narration,
                           n_err=n_err)
                _telemetry(emit_task_triple,
                           task_id=f"exp010_{arm}_s{seed_index}",
                           task_type="experiment_trial", status="passed",
                           duration_ms=wall_s * 1000.0, run_id=run_id)
                trial_idx += 1
    finally:
        f.close()
        _telemetry(active_run.clear_active_run)

    wall_s_total = time.perf_counter() - t0_total
    print(f"=== exp010 run done at {_utcnow_iso()}; ok={n_done} err={n_err} "
          f"wall={wall_s_total:.1f}s ===", flush=True)
    return 0 if n_err == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
