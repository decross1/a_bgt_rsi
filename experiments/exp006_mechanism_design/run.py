#!/usr/bin/env python3
"""exp006 — semi-synthetic mechanism-DESIGN driver (THE genuine tier).

This IS the semi-synthetic mechanism-DESIGN tier of the sandbox spectrum,
labelled honestly. Unlike exp004 (the hardest SYNTHETIC rung, where the
three mechanisms are hand-written and the model is only a bidder), here the
LLM DESIGNS the mechanism: it proposes both the allocation and the payments
for a reported bid profile. There is no single ground-truth output — the
design is scored against the VCG benchmark (allocative efficiency vs the
known optimum, feasibility, and whether the proposed allocation happens to
match the VCG allocation).

This module promotes exp004's exploratory ``mechanism_designer`` PROBE into
a real experiment. It reuses exp004 wholesale and does not reimplement any
auction logic:
  - bundles.draw_valuation for the private valuations,
  - mechanism_designer.propose_allocation for the LLM design,
  - mechanism_designer.score_proposal for the VCG-benchmarked scoring.

Each trial:
  1. Seeds a fresh ``random.Random`` derived from --seed + trial index.
  2. Draws one private valuation per bidder over the frozen bundles
     ((0,), (1,), (0, 1)) via bundles.draw_valuation.
  3. Uses the TRUTHFUL bids (bids := valuations) as the reported bid
     profile the designer sees — the designer is graded on the easiest
     possible input, so any inefficiency is the design's, not bidding noise.
  4. Calls mechanism_designer.propose_allocation to get the LLM-designed
     allocation + payments.
  5. Scores with mechanism_designer.score_proposal against the truthful
     valuations -> {efficiency, is_feasible, matches_vcg_alloc}.
  6. Appends one JSONL row to ``results/trials.jsonl`` for analyze.py.

Parse/feasibility failures are observable, never coerced: the proposal's
``reasoning`` field carries the ``parse_failure`` marker and score_proposal
reports ``is_feasible=False`` for them.

Reproduce (small smoke, requires vllm-gemma on :8000):
    env -u MOCK_LLM ./.venv-chroma/bin/python \\
        experiments/exp006_mechanism_design/run.py --n 2 --bidders 3

Headline run:
    env -u MOCK_LLM ./.venv-chroma/bin/python \\
        experiments/exp006_mechanism_design/run.py --n 20 --bidders 3
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

from experiments.exp004_combinatorial_auction.bundles import (  # noqa: E402
    draw_valuation,
)
from experiments.exp004_combinatorial_auction.mechanism_designer import (  # noqa: E402
    propose_allocation,
    score_proposal,
)

EXP_DIR = Path(__file__).resolve().parent
RESULTS_DIR = EXP_DIR / "results"
TRIALS_PATH = RESULTS_DIR / "trials.jsonl"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _jsonable_bundle_dict(d: dict) -> dict:
    """Serialize a bundle-tuple-keyed dict with str(tuple) keys (JSON object
    keys must be strings; the frozen bundle keys are tuples)."""
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

    # 2. Truthful bids: the reported bid profile the designer sees IS the
    #    valuations. Grading the designer on truthful input isolates design
    #    quality from any bidding noise.
    bid_profile = [dict(v) for v in valuations]

    # 3. LLM designs the mechanism (allocation + payments).
    proposal = propose_allocation(
        bid_profile,
        backend=backend,
        model=model,
        temperature=temperature,
        log_path=log_path,
        caller_tag=f"exp006_designer_t{trial_idx}",
    )

    # 4. Score the design against the VCG benchmark on the truthful values.
    score = score_proposal(proposal, valuations)

    return {
        "trial": trial_idx,
        "valuations": [_jsonable_bundle_dict(v) for v in valuations],
        "proposal": {
            "allocation": _jsonable_alloc(proposal["allocation"]),
            "payments": _jsonable_payments(proposal["payments"]),
            "reasoning": proposal["reasoning"],
            "raw": proposal["raw"],
        },
        "efficiency": score["efficiency"],
        "is_feasible": score["is_feasible"],
        "matches_vcg_alloc": score["matches_vcg_alloc"],
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="exp006 mechanism-design driver")
    p.add_argument("--n", type=int, default=20,
                   help="number of design trials (default 20)")
    p.add_argument("--bidders", type=int, default=3,
                   help="bidders per trial (default 3)")
    p.add_argument("--seed", type=int, default=20260605,
                   help="RNG seed for valuations")
    p.add_argument("--backend", type=str, default=None,
                   help="backend name (default: env DEFAULT_BACKEND -> vllm-gemma)")
    p.add_argument("--model", type=str, default=None,
                   help="model id override (default: backend default)")
    p.add_argument("--temperature", type=float, default=0.2,
                   help="designer sampling temperature (default 0.2)")
    p.add_argument("--out", type=str, default=str(TRIALS_PATH),
                   help="output JSONL path (default results/trials.jsonl)")
    p.add_argument("--wrapper-log", type=str, default=None,
                   help="optional wrapper call_sync log path")
    args = p.parse_args(argv)

    if args.bidders < 1:
        print("FATAL: --bidders must be >= 1", file=sys.stderr)
        return 2

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    t_start = _utcnow_iso()
    print(f"=== exp006 run starting at {t_start} ===", flush=True)
    print(f"=== {args.n} trials × {args.bidders} bidders -> {args.n} design "
          f"calls (LLM DESIGNS the mechanism) ===", flush=True)
    print(f"=== writing per-trial JSONL to {out_path} ===", flush=True)

    f = open(out_path, "w")
    t0_total = time.perf_counter()
    n_done = 0
    n_err = 0
    try:
        for trial_idx in range(args.n):
            t0 = time.perf_counter()
            # Per-trial seeded RNG so each trial is independently reproducible.
            rng = random.Random(args.seed + trial_idx)
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
                print(f"[{trial_idx + 1}/{args.n}] ERROR: {err_row['error']} "
                      f"({wall_s:.1f}s)", flush=True)
                continue
            wall_s = time.perf_counter() - t0
            row["wall_s"] = round(wall_s, 2)
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            n_done += 1
            print(f"[{trial_idx + 1}/{args.n}] eff={row['efficiency']:.3f} "
                  f"feasible={row['is_feasible']} "
                  f"matches_vcg={row['matches_vcg_alloc']} "
                  f"({wall_s:.1f}s)", flush=True)
    finally:
        f.close()

    wall_s_total = time.perf_counter() - t0_total
    t_end = _utcnow_iso()
    print(f"=== exp006 run done at {t_end}; "
          f"ok={n_done} err={n_err} wall={wall_s_total:.1f}s ===", flush=True)
    return 0 if n_err == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
