#!/usr/bin/env python3
"""exp004 — combinatorial-auction rediscovery driver.

exp004 is the HARDEST SYNTHETIC rung of the sandbox spectrum: a
combinatorial auction over two items with a KNOWN optimal solution
(welfare-maximizing allocation brute-forced over the small feasible set).
It is the on-ramp to — but is NOT yet — the semi-synthetic
mechanism-DESIGN tier; here the three mechanisms are hand-written and the
model is only probed as a bidder.

Runs N trials of an M-bidder combinatorial auction. Each trial:
  1. Draws one fresh private valuation per bidder over the three frozen
     bundles ((0,), (1,), (0, 1)) via bundles.draw_valuation.
  2. Asks the LLM bundle-bidder (bidder.compute_bundle_bids) to submit a
     sealed bundle bid for each valuation -> one shared bid profile.
  3. Runs EACH mechanism (vcg, first_price, sequential_second_price) on
     the SAME profile, recording allocation, payments, revenue, the flat
     per-bundle residuals (bid - valuation), and allocative_efficiency
     (against the TRUE valuations).
  4. Appends one JSONL row to ``results/trials.jsonl`` shaped for
     analyze.py: {"trial", "valuations", "mechanisms": {name: block}}.

Reproduce (small smoke, requires vllm-gemma on :8000):
    env -u MOCK_LLM ./.venv-chroma/bin/python \\
        experiments/exp004_combinatorial_auction/run.py --n 2 --bidders 3

Headline run:
    env -u MOCK_LLM ./.venv-chroma/bin/python \\
        experiments/exp004_combinatorial_auction/run.py --n 20 --bidders 3
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

from agent_wrapper.wrapper import set_run_id  # noqa: E402
from orchestrator import active_run  # noqa: E402
from orchestrator.exp_orchestrator_rows import emit_task_triple  # noqa: E402
from experiments.exp004_combinatorial_auction.bundles import (  # noqa: E402
    BUNDLES,
    draw_valuation,
)
from experiments.exp004_combinatorial_auction.bidder import (  # noqa: E402
    compute_bundle_bids,
)
from experiments.exp004_combinatorial_auction.efficiency import (  # noqa: E402
    allocative_efficiency,
)
from experiments.exp004_combinatorial_auction.mechanisms import (  # noqa: E402
    first_price,
    sequential_second_price,
    vcg,
)

EXP_DIR = Path(__file__).resolve().parent
RESULTS_DIR = EXP_DIR / "results"
TRIALS_PATH = RESULTS_DIR / "trials.jsonl"

# Mechanisms run on every trial, in a stable order. Each exposes
# clear(bid_profile, *, rng) and a MECHANISM name constant.
MECHANISMS = (vcg, first_price, sequential_second_price)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _jsonable_bundle_dict(d: dict) -> dict:
    """Serialize a bundle-tuple-keyed dict with str(tuple) keys.

    JSON object keys must be strings; the frozen bundle keys are tuples.
    analyze.py reads only the per-mechanism residuals/reasonings/scalars,
    never these keys, but they are kept human-readable + round-trippable.
    """
    return {str(k): v for k, v in d.items()}


def _jsonable_alloc(alloc: dict) -> dict:
    """Allocation maps int bidder_idx -> bundle tuple; stringify both."""
    return {str(i): list(bundle) for i, bundle in alloc.items()}


def _jsonable_payments(payments: dict) -> dict:
    return {str(i): p for i, p in payments.items()}


def _run_one_trial(
    trial_idx: int,
    *,
    n_bidders: int,
    rng: random.Random,
    backend: str | None,
    model: str | None,
    temperature: float,
    log_path: str | None,
) -> dict:
    # 1. Fresh private valuations, one per bidder.
    valuations = [draw_valuation(rng) for _ in range(n_bidders)]

    # 2. One shared bid profile from the LLM bundle-bidder.
    bid_profile: list[dict] = []
    reasonings: list[str] = []
    raws: list[str] = []
    for i, v in enumerate(valuations):
        out = compute_bundle_bids(
            v,
            backend=backend,
            model=model,
            temperature=temperature,
            log_path=log_path,
            caller_tag=f"exp004_bidder_t{trial_idx}_b{i}",
        )
        bid_profile.append(out["bids"])
        reasonings.append(out["reasoning"])
        raws.append(out["raw"])

    # Flat per-bundle residuals (bid - valuation), shared across mechanisms
    # since the bid profile is shared. Order: bidder-major, bundle-minor.
    residuals = [
        bid_profile[i][b] - valuations[i][b]
        for i in range(n_bidders)
        for b in BUNDLES
    ]

    # 3. Run every mechanism on the SAME profile.
    mechanisms_block: dict = {}
    for mech in MECHANISMS:
        result = mech.clear(bid_profile, rng=rng)
        alloc = result["allocation"]
        mechanisms_block[mech.MECHANISM] = {
            "allocation": _jsonable_alloc(alloc),
            "payments": _jsonable_payments(result["payments"]),
            "revenue": result["revenue"],
            "bids": [_jsonable_bundle_dict(b) for b in bid_profile],
            "residuals": residuals,
            "reasonings": reasonings,
            "allocative_efficiency": allocative_efficiency(alloc, valuations),
        }

    return {
        "trial": trial_idx,
        "valuations": [_jsonable_bundle_dict(v) for v in valuations],
        "raws": raws,
        "mechanisms": mechanisms_block,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="exp004 combinatorial-auction driver")
    p.add_argument("--n", type=int, default=20,
                   help="number of auction trials (default 20)")
    p.add_argument("--bidders", type=int, default=3,
                   help="bidders per trial (default 3)")
    p.add_argument("--seed", type=int, default=20260605,
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

    if args.bidders < 2:
        # sequential_second_price requires >= 2 bidders.
        print("FATAL: --bidders must be >= 2 (sequential_second_price needs 2+)",
              file=sys.stderr)
        return 2

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    rng = random.Random(args.seed)
    t_start = _utcnow_iso()
    run_id = f"exp004_combinatorial_auction_{t_start}"
    set_run_id(run_id)
    active_run.write_active_run(
        run_id, "experiment", "exp004 combinatorial auction",
        total=args.n, unit="trial", model=args.model,
    )
    n_calls = args.n * args.bidders
    print(f"=== exp004 run starting at {t_start} ===", flush=True)
    print(f"=== {args.n} trials × {args.bidders} bidders -> {n_calls} LLM calls; "
          f"3 mechanisms/trial ===", flush=True)
    print(f"=== writing per-trial JSONL to {out_path} ===", flush=True)

    f = open(out_path, "w")
    t0_total = time.perf_counter()
    n_done = 0
    n_err = 0
    try:
        for trial_idx in range(args.n):
            t0 = time.perf_counter()
            try:
                row = _run_one_trial(
                    trial_idx,
                    n_bidders=args.bidders,
                    rng=rng,
                    backend=args.backend,
                    model=args.model,
                    temperature=args.temperature,
                    log_path=args.wrapper_log,
                )
            except Exception as exc:  # noqa: BLE001 — record + continue
                wall_s = time.perf_counter() - t0
                err_row = {
                    "trial": trial_idx,
                    "error": f"{type(exc).__name__}: {exc}",
                    "wall_s": round(wall_s, 2),
                }
                f.write(json.dumps(err_row) + "\n")
                f.flush()
                n_err += 1
                narration = (f"[{trial_idx + 1}/{args.n}] ERROR: "
                             f"{err_row['error']} ({wall_s:.1f}s)")
                print(narration, flush=True)
                active_run.update_active_run(
                    done=trial_idx + 1, narration=narration, n_err=n_err)
                emit_task_triple(
                    task_id=f"exp004_t{trial_idx}", task_type="experiment_trial",
                    status="error", duration_ms=wall_s * 1000.0, run_id=run_id)
                continue
            wall_s = time.perf_counter() - t0
            row["wall_s"] = round(wall_s, 2)
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            n_done += 1
            vcg_eff = row["mechanisms"]["vcg"]["allocative_efficiency"]
            vcg_rev = row["mechanisms"]["vcg"]["revenue"]
            narration = (f"[{trial_idx + 1}/{args.n}] vcg_eff={vcg_eff:.3f} "
                         f"vcg_revenue={vcg_rev:.2f} ({wall_s:.1f}s)")
            print(narration, flush=True)
            active_run.update_active_run(
                done=trial_idx + 1, narration=narration, n_err=n_err)
            emit_task_triple(
                task_id=f"exp004_t{trial_idx}", task_type="experiment_trial",
                status="passed", duration_ms=wall_s * 1000.0, run_id=run_id)
    finally:
        f.close()
        active_run.clear_active_run()
        set_run_id(None)

    wall_s_total = time.perf_counter() - t0_total
    t_end = _utcnow_iso()
    print(f"=== exp004 run done at {t_end}; "
          f"ok={n_done} err={n_err} wall={wall_s_total:.1f}s ===", flush=True)
    return 0 if n_err == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
