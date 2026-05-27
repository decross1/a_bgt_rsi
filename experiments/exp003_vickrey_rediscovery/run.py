#!/usr/bin/env python3
"""exp003 — Vickrey rediscovery driver.

Runs N trials of a 4-bidder sealed-bid second-price auction. Each
trial:
  1. Draws 4 fresh private valuations ~ U[0, 100].
  2. Asks the LLM bidder to submit a sealed bid for each valuation.
  3. Resolves the auction (highest bid wins, pays second-highest).
  4. Appends one JSONL row to ``results/trials.jsonl``.

Reproduce (small smoke, requires vllm-gemma on :8000):
    env -u MOCK_LLM ./.venv-chroma/bin/python \\
        experiments/exp003_vickrey_rediscovery/run.py --trials 2

Headline run (~17 min):
    env -u MOCK_LLM ./.venv-chroma/bin/python \\
        experiments/exp003_vickrey_rediscovery/run.py --trials 50
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from experiments.exp003_vickrey_rediscovery.auctioneer import run_auction  # noqa: E402
from experiments.exp003_vickrey_rediscovery.bidder import compute_bid  # noqa: E402

EXP_DIR = Path(__file__).resolve().parent
RESULTS_DIR = EXP_DIR / "results"
TRIALS_PATH = RESULTS_DIR / "trials.jsonl"

N_BIDDERS = 4


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _run_one_trial(
    trial_idx: int,
    *,
    rng: random.Random,
    backend: str | None,
    model: str | None,
    temperature: float,
    log_path: str | None,
) -> dict:
    valuations = [rng.uniform(0.0, 100.0) for _ in range(N_BIDDERS)]
    bids: list[float] = []
    reasonings: list[str] = []
    raws: list[str] = []
    for i, v in enumerate(valuations):
        out = compute_bid(
            v,
            backend=backend,
            model=model,
            temperature=temperature,
            log_path=log_path,
            caller_tag=f"exp003_bidder_t{trial_idx}_b{i}",
        )
        bids.append(out["bid"])
        reasonings.append(out["reasoning"])
        raws.append(out["raw"])

    auction = run_auction(bids, rng=rng)
    residuals = [b - v for b, v in zip(bids, valuations)]
    return {
        "trial_idx": trial_idx,
        "valuations": valuations,
        "bids": bids,
        "reasonings": reasonings,
        "raws": raws,
        "winner_idx": auction["winner_idx"],
        "price_paid": auction["price_paid"],
        "max_bid": auction["max_bid"],
        "second_bid": auction["second_bid"],
        "tie_break": auction["tie_break"],
        "bid_residuals": residuals,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="exp003 Vickrey rediscovery driver")
    p.add_argument("--trials", type=int, default=50,
                   help="number of auction trials (default 50)")
    p.add_argument("--seed", type=int, default=20260527,
                   help="RNG seed for valuations + tie-breaking")
    p.add_argument("--backend", type=str, default=None,
                   help="backend name (default: env DEFAULT_BACKEND -> vllm-gemma)")
    p.add_argument("--model", type=str, default=None,
                   help="model id override (default: backend default)")
    p.add_argument("--temperature", type=float, default=0.2,
                   help="bidder sampling temperature (default 0.2)")
    p.add_argument("--out", type=str, default=str(TRIALS_PATH),
                   help="output JSONL path (default results/trials.jsonl)")
    p.add_argument("--wrapper-log", type=str, default=None,
                   help="optional wrapper call_sync log path")
    args = p.parse_args(argv)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    rng = random.Random(args.seed)
    t_start = _utcnow_iso()
    print(f"=== exp003 run starting at {t_start} ===", flush=True)
    print(f"=== {args.trials} trials × {N_BIDDERS} bidders -> "
          f"{args.trials * N_BIDDERS} LLM calls ===", flush=True)
    print(f"=== writing per-trial JSONL to {out_path} ===", flush=True)

    f = open(out_path, "w")
    t0_total = time.perf_counter()
    n_done = 0
    n_err = 0
    try:
        for trial_idx in range(args.trials):
            t0 = time.perf_counter()
            try:
                row = _run_one_trial(
                    trial_idx,
                    rng=rng,
                    backend=args.backend,
                    model=args.model,
                    temperature=args.temperature,
                    log_path=args.wrapper_log,
                )
            except Exception as exc:  # noqa: BLE001 — record + continue
                wall_s = time.perf_counter() - t0
                err_row = {
                    "trial_idx": trial_idx,
                    "error": f"{type(exc).__name__}: {exc}",
                    "wall_s": round(wall_s, 2),
                }
                f.write(json.dumps(err_row) + "\n")
                f.flush()
                n_err += 1
                print(f"[{trial_idx + 1}/{args.trials}] ERROR: {err_row['error']} "
                      f"({wall_s:.1f}s)", flush=True)
                continue
            wall_s = time.perf_counter() - t0
            row["wall_s"] = round(wall_s, 2)
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            n_done += 1
            mean_resid = (
                sum(row["bid_residuals"]) / len(row["bid_residuals"])
                if row["bid_residuals"] else 0.0
            )
            print(f"[{trial_idx + 1}/{args.trials}] winner={row['winner_idx']} "
                  f"price={row['price_paid']:.2f} "
                  f"mean_residual={mean_resid:+.2f} ({wall_s:.1f}s)",
                  flush=True)
    finally:
        f.close()

    wall_s_total = time.perf_counter() - t0_total
    t_end = _utcnow_iso()
    print(f"=== exp003 run done at {t_end}; "
          f"ok={n_done} err={n_err} wall={wall_s_total:.1f}s ===", flush=True)
    return 0 if n_err == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
