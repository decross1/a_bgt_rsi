#!/usr/bin/env python3
# DESIGN-ONLY paper forecasting; NO live trading (CLAUDE.md CFTC guardrail).
"""exp007 — Polymarket paper-forecasting harness (NO TRADING).

For each RESOLVED market in a read-only data source, asks the LLM
forecaster for a calibrated YES probability and records one row of
``{market_id, question, prob, market_prob, outcome}`` to
``results/forecasts.jsonl``. Those rows are scored OFFLINE by
``analyze.py`` (Brier / Brier Skill Score vs the market-implied
probability, per docs/sources/research_program_v2.md).

This harness emits probabilities only. It NEVER places an order, signs a
transaction, touches a wallet/private key, spends money, or authenticates
to a trading endpoint. Polymarket remains design-only until CFTC
compliance work is done.

Data source:
  --fixture PATH   load a committed Gamma-shaped fixture (offline; default)
  --live-data      fetch real read-only public Polymarket data instead

Offline by default. Under ``MOCK_LLM`` (the default shell env) the
forecaster is a deterministic stub keyed on (seed, question) — no live
model is called — so the full pipeline runs with no GPU and no network.
For a real forecast run, prefix with ``env -u MOCK_LLM`` and a live
backend.

Reproduce (offline smoke, MOCK_LLM default):
    ./.venv-chroma/bin/python \\
        experiments/exp007_polymarket/run.py --n 12

Real forecast run (requires a live backend):
    env -u MOCK_LLM ./.venv-chroma/bin/python \\
        experiments/exp007_polymarket/run.py --n 20 --live-data
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from experiments.exp007_polymarket import forecaster, market_data  # noqa: E402

EXP_DIR = Path(__file__).resolve().parent
RESULTS_DIR = EXP_DIR / "results"
FORECASTS_PATH = RESULTS_DIR / "forecasts.jsonl"
DEFAULT_FIXTURE = EXP_DIR / "fixtures" / "run_markets.json"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _stub_forecast(question: str, *, seed: int | None) -> dict:
    """Deterministic offline forecaster used under MOCK_LLM.

    Keys a pseudo-probability on (seed, question) so the harness runs with
    no live model and no network. Emits a probability ONLY — no trading.
    """
    key = f"{seed}|{question}".encode("utf-8")
    digest = hashlib.sha256(key).hexdigest()
    # Map first 8 hex digits to a prob in [0.05, 0.95].
    frac = int(digest[:8], 16) / 0xFFFFFFFF
    prob = 0.05 + 0.90 * frac
    return {
        "prob": prob,
        "reasoning": "mock_stub: deterministic offline forecast (no model call)",
        "raw": "",
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="exp007 Polymarket paper-forecasting harness")
    p.add_argument("--n", type=int, default=20,
                   help="max markets to consider (default 20)")
    p.add_argument("--fixture", type=str, default=str(DEFAULT_FIXTURE),
                   help="path to a Gamma-shaped fixture (default committed fixture)")
    p.add_argument("--seed", type=int, default=20260605,
                   help="seed threaded to the forecaster (determinism)")
    p.add_argument("--live-data", action="store_true",
                   help="fetch real read-only Polymarket data instead of the fixture")
    p.add_argument("--backend", type=str, default=None,
                   help="backend name (real runs only; default env DEFAULT_BACKEND)")
    p.add_argument("--model", type=str, default=None,
                   help="model id override (real runs only)")
    p.add_argument("--temperature", type=float, default=0.2,
                   help="forecaster sampling temperature (default 0.2)")
    p.add_argument("--out", type=str, default=str(FORECASTS_PATH),
                   help="output JSONL path (default results/forecasts.jsonl)")
    p.add_argument("--wrapper-log", type=str, default=None,
                   help="optional wrapper call_sync log path (real runs)")
    args = p.parse_args(argv)

    mock = bool(os.environ.get("MOCK_LLM"))

    # Read-only data source. fetch_markets / load_fixture raise
    # MarketDataError on failure and never crash; surface it as exit 2.
    try:
        if args.live_data:
            print("=== fetching read-only public Polymarket data (no auth, no trading) ===",
                  flush=True)
            markets = market_data.fetch_markets(limit=args.n, closed=True)
        else:
            print(f"=== loading fixture {args.fixture} (offline) ===", flush=True)
            markets = market_data.load_fixture(args.fixture)
    except market_data.MarketDataError as exc:
        print(f"FATAL: market-data load failed: {exc}", flush=True)
        return 2

    resolved = [m for m in markets if m.get("resolved") and m.get("outcome") is not None]
    resolved = resolved[: args.n]

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    t_start = _utcnow_iso()
    print(f"=== exp007 paper-forecasting run starting at {t_start} ===", flush=True)
    print(f"=== {len(resolved)} resolved markets to forecast "
          f"(mock={mock}) ===", flush=True)
    print(f"=== writing forecasts to {out_path} ===", flush=True)

    # Run-provenance registration (2026-06-10, exp009 pattern). Open the
    # output file FIRST: an open() failure must not strand a registered
    # run (the registration sits inside the try/finally below). The prior
    # run_id is RESTORED on exit (not None) so an in-process parent — the
    # coordinator's forecast_markets handler — keeps its attribution.
    from agent_wrapper.wrapper import get_run_id, set_run_id
    from orchestrator import active_run

    f = open(out_path, "w")
    run_id = f"exp007_polymarket_{t_start}"
    _prev_run_id = get_run_id()
    set_run_id(run_id)
    active_run.write_active_run(
        run_id, "experiment", "exp007 Polymarket paper-forecasting",
        total=len(resolved), unit="market", model=args.model,
    )
    t0_total = time.perf_counter()
    n_done = 0
    n_err = 0
    try:
        for i, m in enumerate(resolved):
            question = m.get("question") or ""
            t0 = time.perf_counter()
            try:
                if mock:
                    out = _stub_forecast(question, seed=args.seed)
                else:
                    out = forecaster.forecast(
                        question,
                        backend=args.backend,
                        model=args.model,
                        temperature=args.temperature,
                        seed=args.seed,
                        log_path=args.wrapper_log,
                        caller_tag=f"exp007_forecaster_m{i}",
                    )
            except Exception as exc:  # noqa: BLE001 — record + continue
                wall_s = time.perf_counter() - t0
                err_row = {
                    "market_id": m.get("market_id"),
                    "error": f"{type(exc).__name__}: {exc}",
                    "wall_s": round(wall_s, 2),
                }
                f.write(json.dumps(err_row) + "\n")
                f.flush()
                n_err += 1
                print(f"[{i + 1}/{len(resolved)}] ERROR: {err_row['error']} "
                      f"({wall_s:.1f}s)", flush=True)
                active_run.update_active_run(
                    done=i + 1,
                    narration=f"[{i + 1}/{len(resolved)}] ERROR ({wall_s:.1f}s)",
                    n_err=n_err,
                )
                continue
            wall_s = time.perf_counter() - t0
            row = {
                "market_id": m.get("market_id"),
                "question": question,
                "prob": out["prob"],
                "market_prob": m.get("implied_prob"),
                "outcome": m.get("outcome"),
                "wall_s": round(wall_s, 2),
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            n_done += 1
            print(f"[{i + 1}/{len(resolved)}] prob={out['prob']:.3f} "
                  f"market={row['market_prob']} outcome={row['outcome']} "
                  f"({wall_s:.1f}s)", flush=True)
            active_run.update_active_run(
                done=i + 1,
                narration=(f"[{i + 1}/{len(resolved)}] "
                           f"prob={out['prob']:.3f} ({wall_s:.1f}s)"),
                n_err=n_err,
            )
    finally:
        f.close()
        active_run.clear_active_run()
        set_run_id(_prev_run_id)

    wall_s_total = time.perf_counter() - t0_total
    t_end = _utcnow_iso()
    print(f"=== exp007 run done at {t_end}; "
          f"ok={n_done} err={n_err} wall={wall_s_total:.1f}s ===", flush=True)
    return 0 if n_err == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
