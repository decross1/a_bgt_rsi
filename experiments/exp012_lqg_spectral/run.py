#!/usr/bin/env python3
"""exp012 — spectral-slowdown driver (fully numerical, zero LLM calls).

Tests the L1 claim cl-iter-2026-08-15-002: bounded rationality (a
precision constraint on belief updating) slows convergence specifically
when the information structure's adjacency spectral radius exceeds a
critical threshold. LOCKED design (v2.1, quantization-only + fixation
detection): experiments/PREREG_l2block_2026-08-17.md §exp012_lqg_spectral.
Scope limit on record there: this is a linear belief-best-response
contraction SURROGATE, not an LQG game.

Design: 30 seeds × 7 ρ_eff × 2 arms = 420 trial rows. Pairing (LOCKED):
the triple (A_s, b_s, θ0_s) is drawn once from RNG(20260817 + s) and
shared across all 14 cells of seed s — only the M rescale and the
belief map differ. Errors are recorded as rows and never abort the run;
no metric is ever coerced (inviolate rule 4).

Reproduce (pure numeric — safe under MOCK_LLM; runs in ~a minute):
    ./.venv-chroma/bin/python experiments/exp012_lqg_spectral/run.py
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from orchestrator import active_run  # noqa: E402
from orchestrator.exp_orchestrator_rows import emit_task_triple  # noqa: E402
from experiments.exp012_lqg_spectral.dynamics import (  # noqa: E402
    ARMS,
    BASE_SEED,
    N_SEEDS,
    RHO_EFF_GRID,
    T_MAX,
    draw_instance,
    run_cell,
)

EXP_DIR = Path(__file__).resolve().parent
RESULTS_DIR = EXP_DIR / "results"
TRIALS_PATH = RESULTS_DIR / "trials.jsonl"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _telemetry(fn: Callable, *args, **kwargs) -> None:
    # UI-only side channel: telemetry must never abort a numeric run.
    try:
        fn(*args, **kwargs)
    except Exception:  # noqa: BLE001
        pass


def iter_rows(n_seeds: int = N_SEEDS, base_seed: int = BASE_SEED,
              rho_grid: tuple = RHO_EFF_GRID,
              t_max: int = T_MAX) -> Iterator[dict]:
    """Pure row generator (no I/O, no telemetry) — the testable core.

    Yields one row per (seed, ρ_eff, arm) cell in the pinned order
    seeds → ρ_eff grid → (FULL, BOUNDED). The per-seed instance is drawn
    ONCE and shared across the seed's cells (LOCKED pairing). A failing
    cell yields an error row and the run continues.
    """
    trial_idx = 0
    for seed_index in range(n_seeds):
        instance = draw_instance(seed_index, base_seed)
        for rho_eff in rho_grid:
            for arm in ARMS:
                t0 = time.perf_counter()
                try:
                    cell = run_cell(instance, rho_eff, arm, t_max=t_max)
                except Exception as exc:  # noqa: BLE001 — record + continue
                    yield {
                        "trial_idx": trial_idx,
                        "seed_index": seed_index,
                        "rho_eff": rho_eff,
                        "arm": arm,
                        "error": f"{type(exc).__name__}: {exc}",
                        "wall_s": round(time.perf_counter() - t0, 4),
                    }
                    trial_idx += 1
                    continue
                yield {
                    "trial_idx": trial_idx,
                    "seed_index": seed_index,
                    "rho_eff": rho_eff,
                    "arm": arm,
                    "T": cell["T"],
                    "cycling": cell["cycling"],
                    "budget_exhausted": cell["budget_exhausted"],
                    "redraws": instance["redraws"],
                    "e0_inf": cell["e0_inf"],
                    "wall_s": round(time.perf_counter() - t0, 4),
                }
                trial_idx += 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="exp012 spectral-slowdown driver")
    p.add_argument("--seeds", type=int, default=N_SEEDS,
                   help="seeds (default 30; LOCKED headline run)")
    p.add_argument("--seed", type=int, default=BASE_SEED,
                   help="base seed (default 20260817, LOCKED)")
    p.add_argument("--out", type=str, default=str(TRIALS_PATH),
                   help="output JSONL path (default results/trials.jsonl)")
    args = p.parse_args(argv)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    total = args.seeds * len(RHO_EFF_GRID) * len(ARMS)
    t_start = _utcnow_iso()
    run_id = f"exp012_lqg_spectral_{t_start}"
    _telemetry(active_run.write_active_run,
               run_id, "experiment", "exp012 spectral slowdown (surrogate)",
               total=total, unit="trial", model=None)
    print(f"=== exp012 run starting at {t_start} ===", flush=True)
    print(f"=== {args.seeds} seeds x {len(RHO_EFF_GRID)} rho_eff x "
          f"{len(ARMS)} arms -> {total} trials; t_max={T_MAX}; "
          f"ZERO LLM calls ===", flush=True)
    print(f"=== writing per-trial JSONL to {out_path} ===", flush=True)

    f = open(out_path, "w")
    t0_total = time.perf_counter()
    n_done = 0
    n_err = 0
    try:
        for row in iter_rows(n_seeds=args.seeds, base_seed=args.seed):
            f.write(json.dumps(row) + "\n")
            f.flush()
            step = row["trial_idx"] + 1
            task_id = (f"exp012_{row['arm']}_s{row['seed_index']}"
                       f"_r{row['rho_eff']:g}")
            if "error" in row:
                n_err += 1
                narration = (f"[{step}/{total}] {row['arm']} "
                             f"rho={row['rho_eff']:g} ERROR: {row['error']}")
                status = "error"
            else:
                n_done += 1
                flags = ("cycle" if row["cycling"]
                         else "budget" if row["budget_exhausted"] else "fix")
                narration = (f"[{step}/{total}] {row['arm']} "
                             f"s={row['seed_index']} rho={row['rho_eff']:g} "
                             f"T={row['T']} {flags} ({row['wall_s']:.3f}s)")
                status = "passed"
            print(narration, flush=True)
            _telemetry(active_run.update_active_run,
                       done=step, narration=narration, n_err=n_err)
            _telemetry(emit_task_triple,
                       task_id=task_id, task_type="experiment_trial",
                       status=status, duration_ms=row["wall_s"] * 1000.0,
                       run_id=run_id)
    finally:
        f.close()
        _telemetry(active_run.clear_active_run)

    wall_s_total = time.perf_counter() - t0_total
    print(f"=== exp012 run done at {_utcnow_iso()}; ok={n_done} err={n_err} "
          f"wall={wall_s_total:.1f}s ===", flush=True)
    return 0 if n_err == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
