#!/usr/bin/env python3
"""exp005 — mechanism-AWARE bidding driver.

exp005 sharpens exp004's rediscovery probe: the bidder is told each
mechanism's PAYMENT rule in plain mechanics (no auction-theory priming) and
bids SEPARATELY into each one. The headline signal is the SIGNED residual
(bid - valuation) per mechanism: negative under first_price = bid-shading,
~0 under vcg = truthful. Because the payment rule changes the bid, the bid
profile is NOT shared across mechanisms — each mechanism gets its own LLM
call per bidder (3 mechanisms × bidders calls per trial).

Each trial:
  1. Draws one fresh private valuation per bidder over the three frozen
     bundles ((0,), (1,), (0, 1)) via bundles.draw_valuation. Valuations are
     SHARED across mechanisms (same private values, different payment rule).
  2. For each mechanism in [vcg, first_price, sequential_second_price]:
     asks the aware bundle-bidder for a bid profile UNDER THAT mechanism,
     clears with the matching mechanism module, and records the per-mechanism
     bids, signed residuals (bid - valuation), reasonings, allocation,
     payments, revenue, and allocative_efficiency (against TRUE valuations).
  3. Appends one JSONL row to ``results/trials.jsonl`` shaped for analyze.py:
     {"trial", "valuations", "mechanisms": {name: block}}.

Reproduce (small smoke, requires vllm-gemma on :8000):
    env -u MOCK_LLM ./.venv-chroma/bin/python \\
        experiments/exp005_mechanism_aware/run.py --n 2 --bidders 3

Headline run:
    env -u MOCK_LLM ./.venv-chroma/bin/python \\
        experiments/exp005_mechanism_aware/run.py --n 20 --bidders 3
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
from experiments.exp004_combinatorial_auction.efficiency import (  # noqa: E402
    allocative_efficiency,
)
from experiments.exp004_combinatorial_auction.mechanisms import (  # noqa: E402
    first_price,
    sequential_second_price,
    vcg,
)
from experiments.exp005_mechanism_aware.bidder_aware import (  # noqa: E402
    compute_aware_bundle_bids,
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
    # 1. Fresh private valuations, one per bidder; SHARED across mechanisms.
    valuations = [draw_valuation(rng) for _ in range(n_bidders)]

    # 2 + 3. For each mechanism, a fresh bid profile under THAT payment rule.
    mechanisms_block: dict = {}
    for mech in MECHANISMS:
        name = mech.MECHANISM
        bid_profile: list[dict] = []
        reasonings: list[str] = []
        raws: list[str] = []
        for i, v in enumerate(valuations):
            out = compute_aware_bundle_bids(
                v,
                name,
                backend=backend,
                model=model,
                temperature=temperature,
                log_path=log_path,
                caller_tag=f"exp005_bidder_t{trial_idx}_b{i}_{name}",
            )
            bid_profile.append(out["bids"])
            reasonings.append(out["reasoning"])
            raws.append(out["raw"])

        # SIGNED residuals (bid - valuation), bidder-major, bundle-minor.
        residuals = [
            bid_profile[i][b] - valuations[i][b]
            for i in range(n_bidders)
            for b in BUNDLES
        ]

        result = mech.clear(bid_profile, rng=rng)
        alloc = result["allocation"]
        mechanisms_block[name] = {
            "allocation": _jsonable_alloc(alloc),
            "payments": _jsonable_payments(result["payments"]),
            "revenue": result["revenue"],
            "bids": [_jsonable_bundle_dict(b) for b in bid_profile],
            "residuals": residuals,
            "reasonings": reasonings,
            "raws": raws,
            "allocative_efficiency": allocative_efficiency(alloc, valuations),
        }

    return {
        "trial": trial_idx,
        "valuations": [_jsonable_bundle_dict(v) for v in valuations],
        "mechanisms": mechanisms_block,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="exp005 mechanism-aware bidding driver")
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
    run_id = f"exp005_mechanism_aware_{t_start}"
    set_run_id(run_id)
    active_run.write_active_run(
        run_id, "experiment", "exp005 mechanism-aware bidding",
        total=args.n, unit="trial", model=args.model,
    )
    n_calls = args.n * args.bidders * len(MECHANISMS)
    print(f"=== exp005 run starting at {t_start} ===", flush=True)
    print(f"=== {args.n} trials × {args.bidders} bidders × {len(MECHANISMS)} "
          f"mechanisms -> {n_calls} LLM calls ===", flush=True)
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
                    task_id=f"exp005_t{trial_idx}", task_type="experiment_trial",
                    status="error", duration_ms=wall_s * 1000.0, run_id=run_id)
                continue
            wall_s = time.perf_counter() - t0
            row["wall_s"] = round(wall_s, 2)
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            n_done += 1
            fp = row["mechanisms"]["first_price"]
            fp_resid = sum(fp["residuals"]) / len(fp["residuals"]) if fp["residuals"] else 0.0
            narration = (f"[{trial_idx + 1}/{args.n}] fp_mean_residual={fp_resid:.2f} "
                         f"fp_eff={fp['allocative_efficiency']:.3f} ({wall_s:.1f}s)")
            print(narration, flush=True)
            active_run.update_active_run(
                done=trial_idx + 1, narration=narration, n_err=n_err)
            emit_task_triple(
                task_id=f"exp005_t{trial_idx}", task_type="experiment_trial",
                status="passed", duration_ms=wall_s * 1000.0, run_id=run_id)
    finally:
        f.close()
        active_run.clear_active_run()
        set_run_id(None)

    wall_s_total = time.perf_counter() - t0_total
    t_end = _utcnow_iso()
    print(f"=== exp005 run done at {t_end}; "
          f"ok={n_done} err={n_err} wall={wall_s_total:.1f}s ===", flush=True)
    return 0 if n_err == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
