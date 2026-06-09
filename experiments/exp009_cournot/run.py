#!/usr/bin/env python3
"""exp009 — Cournot duopoly, few-shot marginal-cost treatment driver.

Tests the surviving literature thesis (iter-2026-06-06-001): LLM
convergence to the Nash quantity in a Cournot duopoly is modulated by
few-shot prompting examples that explicitly define the marginal cost
parameter, reducing quantity-selection variance.

Game: symmetric Cournot duopoly with linear inverse demand
P(Q) = a - b*Q (floored at 0) and constant marginal cost c. The unique
symmetric Nash quantity per firm is q* = (a - c) / (3b). Defaults
a=100, b=1, c=10 -> q* = 30.

Each trial asks two independent LLM agents (no shared context) for a
production quantity. Treatment factor ``few_shot_marginal_cost``:
  - absent   : rules only (marginal cost stated once, no worked examples)
  - explicit : rules + two worked profit examples that explicitly define
               the marginal cost parameter c

Unparseable completions are recorded as invalid trials — quantities are
NEVER coerced to a default (inviolate rule 4).

Reproduce (small smoke, requires vllm-gemma on :8000):
    env -u MOCK_LLM ./.venv-chroma/bin/python \\
        experiments/exp009_cournot/run.py --n-trials 2

Headline run (both arms, 50 trials each -> 200 LLM calls):
    env -u MOCK_LLM ./.venv-chroma/bin/python \\
        experiments/exp009_cournot/run.py --n-trials 50
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent_wrapper.wrapper import call_sync, set_run_id  # noqa: E402
from orchestrator import active_run  # noqa: E402
from orchestrator.exp_orchestrator_rows import emit_task_triple  # noqa: E402

EXP_DIR = Path(__file__).resolve().parent
RESULTS_DIR = EXP_DIR / "results"
TRIALS_PATH = RESULTS_DIR / "trials.jsonl"

A_DEFAULT = 100.0
B_DEFAULT = 1.0
C_DEFAULT = 10.0
N_FIRMS = 2
TREATMENTS = ("absent", "explicit")

_REASONING_CHAR_CAP = 400


def nash_quantity(a: float, b: float, c: float) -> float:
    """Unique symmetric Cournot-Nash quantity per firm (duopoly):
    q* = (a - c) / (3b)."""
    return (a - c) / (3.0 * b)


def market_price(q1: float, q2: float, a: float, b: float) -> float:
    """Linear inverse demand, floored at zero (no negative prices)."""
    return max(a - b * (q1 + q2), 0.0)


def profit(q_own: float, q_other: float, a: float, b: float, c: float) -> float:
    """Firm profit: (P(Q) - c) * q_own."""
    return (market_price(q_own, q_other, a, b) - c) * q_own


def nash_deviation(q: float, q_star: float) -> float:
    """Relative absolute deviation from the Nash quantity: |q - q*| / q*."""
    return abs(q - q_star) / q_star


# --- prompts -----------------------------------------------------------

def build_system_prompt(treatment: str, a: float, b: float, c: float) -> str:
    """Game rules; the prompt never names Nash, equilibrium, or any
    game-theory result. The 'explicit' arm appends two worked profit
    examples that explicitly define the marginal cost parameter c."""
    if treatment not in TREATMENTS:
        raise ValueError(f"unknown treatment {treatment!r}; known: {TREATMENTS}")
    rules = (
        "You are one of two firms producing an identical product for the "
        "same market. Both firms choose their production quantity "
        "simultaneously and independently; neither sees the other's choice "
        "before committing. The market price is set by total supply: "
        f"price = {a:g} - {b:g} * (your quantity + the other firm's "
        f"quantity), and the price is never below 0. Producing each unit "
        f"costs you {c:g}. Your profit is (price - {c:g}) * your quantity. "
        "The other firm faces exactly the same costs and the same rules "
        "and is also trying to maximize its own profit. Choose the "
        "production quantity that maximizes your own profit."
    )
    if treatment == "absent":
        return rules
    # Explicit few-shot examples. Example quantities deliberately avoid
    # the Nash quantity so the examples define the cost parameter without
    # leaking the answer.
    ex1_q, ex1_o = 20.0, 40.0
    ex2_q, ex2_o = 50.0, 25.0
    ex1_p = market_price(ex1_q, ex1_o, a, b)
    ex2_p = market_price(ex2_q, ex2_o, a, b)
    examples = (
        "\n\nHere are two worked examples of how profit is computed in "
        f"this market. The marginal cost parameter is c = {c:g}: the cost "
        "of producing one additional unit is always exactly c.\n"
        f"Example 1: you produce {ex1_q:g} units and the other firm "
        f"produces {ex1_o:g}. Price = {a:g} - {b:g} * ({ex1_q:g} + "
        f"{ex1_o:g}) = {ex1_p:g}. Your profit = ({ex1_p:g} - c) * "
        f"{ex1_q:g} = ({ex1_p:g} - {c:g}) * {ex1_q:g} = "
        f"{profit(ex1_q, ex1_o, a, b, c):g}.\n"
        f"Example 2: you produce {ex2_q:g} units and the other firm "
        f"produces {ex2_o:g}. Price = {a:g} - {b:g} * ({ex2_q:g} + "
        f"{ex2_o:g}) = {ex2_p:g}. Your profit = ({ex2_p:g} - c) * "
        f"{ex2_q:g} = ({ex2_p:g} - {c:g}) * {ex2_q:g} = "
        f"{profit(ex2_q, ex2_o, a, b, c):g}."
    )
    return rules + examples


def _format_instruction(q_max: float) -> str:
    return (
        "Respond with a single JSON object on one line and nothing else. "
        'Use exactly this shape: {"quantity": <number>, "reasoning": '
        "<string>}. The quantity must be a number between 0 and "
        f"{q_max:g}. Keep the reasoning field under 300 characters."
    )


# --- parsing -----------------------------------------------------------

_JSON_RE = re.compile(r"\{.*?\}", re.DOTALL)
_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _extract_json_object(text: str) -> dict[str, Any] | None:
    try:
        obj = json.loads(text.strip())
        if isinstance(obj, dict):
            return obj
    except (json.JSONDecodeError, ValueError):
        pass
    m = _JSON_RE.search(text)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
        if isinstance(obj, dict):
            return obj
    except (json.JSONDecodeError, ValueError):
        return None
    return None


def parse_quantity(text: str, q_max: float) -> float | None:
    """Robust quantity extraction with bounds [0, q_max].

    Order: JSON object with a "quantity" field, then the first bare
    number in the text. Out-of-bounds, NaN, or no number -> None.
    The caller records None as an INVALID trial — never coerced."""
    if not text:
        return None
    candidate: float | None = None
    obj = _extract_json_object(text)
    if obj is not None and "quantity" in obj:
        try:
            candidate = float(obj["quantity"])
        except (TypeError, ValueError):
            candidate = None
    if candidate is None:
        m = _NUM_RE.search(text)
        if m:
            candidate = float(m.group(0))
    if candidate is None:
        return None
    if candidate != candidate:  # NaN
        return None
    if candidate < 0 or candidate > q_max:
        return None
    return candidate


# --- one agent call ----------------------------------------------------

def compute_quantity(
    treatment: str,
    *,
    a: float = A_DEFAULT,
    b: float = B_DEFAULT,
    c: float = C_DEFAULT,
    backend: str | None = None,
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 256,
    seed: int | None = None,
    log_path: str | None = None,
    caller_tag: str = "exp009_firm",
) -> dict:
    """Ask one LLM firm for a production quantity.

    Returns ``{"quantity": float | None, "raw": str}``. ``quantity`` is
    None on parse failure (observable downstream as an invalid trial)."""
    q_max = a / b
    user_msg = (
        "Submit your production quantity now.\n\n"
        f"{_format_instruction(q_max)}"
    )
    record = call_sync(
        [
            {"role": "system", "content": build_system_prompt(treatment, a, b, c)},
            {"role": "user", "content": user_msg},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
        seed=seed,
        caller_tag=caller_tag,
        log_path=log_path,
        model=model,
        backend=backend,
    )
    raw = (record.get("completion") or "").strip()
    return {"quantity": parse_quantity(raw, q_max), "raw": raw[:_REASONING_CHAR_CAP]}


def _run_one_trial(
    trial_idx: int,
    treatment: str,
    *,
    a: float,
    b: float,
    c: float,
    backend: str | None,
    model: str | None,
    temperature: float,
    log_path: str | None,
    seed: int | None = None,
) -> dict:
    q_star = nash_quantity(a, b, c)
    qs: list[float | None] = []
    raws: list[str] = []
    for i in range(N_FIRMS):
        out = compute_quantity(
            treatment,
            a=a, b=b, c=c,
            backend=backend,
            model=model,
            temperature=temperature,
            log_path=log_path,
            # per-call derived seed: distinct per (trial, firm), reproducible
            # from the base --seed (2026-06-09 review: --seed was parsed but
            # never threaded — a dead reproducibility knob).
            seed=None if seed is None else seed + trial_idx * N_FIRMS + i,
            caller_tag=f"exp009_firm_{treatment}_t{trial_idx}_f{i}",
        )
        qs.append(out["quantity"])
        raws.append(out["raw"])
    devs = [nash_deviation(q, q_star) if q is not None else None for q in qs]
    return {
        "trial": trial_idx,
        "treatment": treatment,
        "q1": qs[0],
        "q2": qs[1],
        "deviation_1": devs[0],
        "deviation_2": devs[1],
        "raw_1": raws[0],
        "raw_2": raws[1],
        "valid": qs[0] is not None and qs[1] is not None,
        "q_star": q_star,
    }


# --- driver ------------------------------------------------------------

def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="exp009 Cournot duopoly driver")
    p.add_argument("--treatment", choices=[*TREATMENTS, "both"], default="both",
                   help="few_shot_marginal_cost arm to run (default both). "
                        "Single-arm runs APPEND to --out; 'both' rewrites it.")
    p.add_argument("--n-trials", type=int, default=50,
                   help="trials per treatment arm (default 50)")
    p.add_argument("--seed", type=int, default=20260609,
                   help="base seed passed to the backend per call")
    p.add_argument("--a", type=float, default=A_DEFAULT, help="demand intercept")
    p.add_argument("--b", type=float, default=B_DEFAULT, help="demand slope")
    p.add_argument("--c", type=float, default=C_DEFAULT, help="marginal cost")
    p.add_argument("--backend", type=str, default=None,
                   help="backend name (default: env DEFAULT_BACKEND -> vllm-gemma)")
    p.add_argument("--model", type=str, default=None,
                   help="model id override (default: backend default)")
    p.add_argument("--temperature", type=float, default=0.2,
                   help="sampling temperature (default 0.2)")
    p.add_argument("--out", type=str, default=str(TRIALS_PATH),
                   help="output JSONL path (default results/trials.jsonl)")
    p.add_argument("--wrapper-log", type=str, default=None,
                   help="optional wrapper call_sync log path")
    args = p.parse_args(argv)

    if args.a <= args.c:
        raise SystemExit(f"FATAL: need a > c for a positive Nash quantity "
                         f"(a={args.a}, c={args.c})")

    arms = list(TREATMENTS) if args.treatment == "both" else [args.treatment]
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    mode = "w" if args.treatment == "both" else "a"

    total = args.n_trials * len(arms)
    t_start = _utcnow_iso()
    run_id = f"exp009_cournot_{t_start}"
    set_run_id(run_id)
    active_run.write_active_run(
        run_id, "experiment", "exp009 Cournot few-shot marginal cost",
        total=total, unit="trial", model=args.model,
    )
    q_star = nash_quantity(args.a, args.b, args.c)
    print(f"=== exp009 run starting at {t_start} ===", flush=True)
    print(f"=== arms={arms} x {args.n_trials} trials x {N_FIRMS} firms -> "
          f"{total * N_FIRMS} LLM calls; q*={q_star:g} ===", flush=True)
    print(f"=== writing per-trial JSONL to {out_path} (mode={mode}) ===", flush=True)

    f = open(out_path, mode)
    t0_total = time.perf_counter()
    n_done = 0
    n_err = 0
    n_invalid = 0
    try:
        step = 0
        for treatment in arms:
            for trial_idx in range(args.n_trials):
                step += 1
                t0 = time.perf_counter()
                try:
                    row = _run_one_trial(
                        trial_idx,
                        treatment,
                        a=args.a, b=args.b, c=args.c,
                        backend=args.backend,
                        model=args.model,
                        temperature=args.temperature,
                        log_path=args.wrapper_log,
                        seed=args.seed,
                    )
                except Exception as exc:  # noqa: BLE001 — record + continue
                    wall_s = time.perf_counter() - t0
                    err_row = {
                        "trial": trial_idx,
                        "treatment": treatment,
                        "error": f"{type(exc).__name__}: {exc}",
                        "wall_s": round(wall_s, 2),
                    }
                    f.write(json.dumps(err_row) + "\n")
                    f.flush()
                    n_err += 1
                    narration = (f"[{step}/{total}] {treatment} ERROR: "
                                 f"{err_row['error']} ({wall_s:.1f}s)")
                    print(narration, flush=True)
                    active_run.update_active_run(
                        done=step, narration=narration, n_err=n_err)
                    emit_task_triple(
                        task_id=f"exp009_{treatment}_t{trial_idx}",
                        task_type="experiment_trial", status="error",
                        duration_ms=wall_s * 1000.0, run_id=run_id)
                    continue
                wall_s = time.perf_counter() - t0
                row["wall_s"] = round(wall_s, 2)
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                f.flush()
                n_done += 1
                if not row["valid"]:
                    n_invalid += 1
                q1, q2 = row["q1"], row["q2"]
                narration = (f"[{step}/{total}] {treatment} "
                             f"q1={'-' if q1 is None else f'{q1:.1f}'} "
                             f"q2={'-' if q2 is None else f'{q2:.1f}'} "
                             f"valid={row['valid']} ({wall_s:.1f}s)")
                print(narration, flush=True)
                active_run.update_active_run(
                    done=step, narration=narration, n_err=n_err)
                emit_task_triple(
                    task_id=f"exp009_{treatment}_t{trial_idx}",
                    task_type="experiment_trial", status="passed",
                    duration_ms=wall_s * 1000.0, run_id=run_id)
    finally:
        f.close()
        active_run.clear_active_run()
        set_run_id(None)

    wall_s_total = time.perf_counter() - t0_total
    print(f"=== exp009 run done at {_utcnow_iso()}; ok={n_done} "
          f"(invalid={n_invalid}) err={n_err} wall={wall_s_total:.1f}s ===",
          flush=True)
    return 0 if n_err == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
