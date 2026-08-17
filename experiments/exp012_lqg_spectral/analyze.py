#!/usr/bin/env python3
"""exp012 — analyze trials.jsonl into the LOCKED spectral-slowdown verdict.

Reads ``results/trials.jsonl`` (written by ``run.py``) and writes
``results/summary.md`` (Verdict=YES|NO on LINE 1) plus
``results/summary.json`` (machine-readable, read by loop_bridge.py).

LOCKED decision rule (experiments/PREREG_l2block_2026-08-17.md
§exp012_lqg_spectral, v2.1 — constants below copied VERBATIM; any later
change is a new dated amendment, never an edit):

  R(ρ) := median T_bounded(ρ) / median T_full(ρ). All logs are natural
  logs (np.log) everywhere in these rules and the null comparison.
  effect_confirmed = TRUE iff ALL of:
  1. a continuous two-segment piecewise-linear fit of the 7
     (ρ_eff, ln R) MEDIAN points beats the single-line fit by
     ΔBIC >= 10, with the fit and BIC pinned: unweighted least squares
     on the 7 median points; BIC = n·ln(RSS/n) + k·ln(n) with n=7,
     k=4 (two-segment) vs k=2 (line); ΔBIC = BIC_1seg − BIC_2seg;
     breakpoint by dense grid search (step 0.005) over ρ* ∈ [0.21, 0.84]
     with >= 2 grid points required strictly on each side of ρ*;
  2. fitted breakpoint interior: 0.32 <= ρ* < 0.74, AND the two grid
     cells immediately above ρ* each have < 50% capped trials (cycling
     OR budget_exhausted) in the bounded arm;
  3. slope above ρ* >= 2.0 (ln R per unit ρ_eff) AND >= 3× max(slope
     below, 0.25);
  4. stability: seed-level bootstrap B=1000 (resample seeds within each
     (ρ, arm) cell, recompute medians, refit rules 1–3): rules 1–3 hold
     in >= 90% of resamples AND bootstrap IQR of ρ* <= 0.15, where the
     IQR is computed over ALL B resamples (never the passing subset)
     and a resample whose two-segment fit yields no ρ* inside
     [0.21, 0.84] or a degenerate segment counts as a rules-failure for
     the >= 90% criterion;
  5. censoring robustness: rules 1–3 must ALSO hold when every
     bounded-arm cell median is recomputed over non-cycling,
     non-budget-exhausted trials only. A breakpoint present only under
     the T_bounded := t_max convention is adjudicated as censoring
     geometry ⇒ effect_confirmed = FALSE, with the
     cycling-fraction-vs-ρ curve reported as its own named non-gating
     finding.

  H0_construction (closed-form null on record): e_0(ρ, arm) := median
  over seeds of ||θ_0 − θ*||∞ in that cell; T_pred_bounded(ρ) =
  ln(e_0 / r_dead(ρ)) / (−ln ρ) with r_dead(ρ) = ρ·(Δ/2)/(1−ρ);
  T_pred_full(ρ) = ln(e_0 / 1e-6) / (−ln ρ); R_pred = T_pred_bounded /
  T_pred_full — smooth in ρ, no breakpoint (R_pred sits well BELOW 1
  across the sweep). This file computes and reports
  max_ρ |ln R_observed(ρ) − ln R_pred(ρ)| and both curves.

  metric="slowdown_breakpoint_rho_eff", value = fitted ρ* (or −1.0 on
  Verdict=NO — never a fabricated threshold; raw fit still reported).

Invalid/error rows are excluded from statistics and counted — never
imputed (inviolate rule 4). The rules were locked at 30 seeds × 7 ρ_eff
× 2 arms; if the data does not carry the locked counts the rules are
still reported as computed but effect_confirmed is FALSE with the
deviation stated (exp010 norm).

Run:
    ./.venv-chroma/bin/python experiments/exp012_lqg_spectral/analyze.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

EXP_DIR = Path(__file__).resolve().parent
TRIALS_PATH = EXP_DIR / "results" / "trials.jsonl"
SUMMARY_MD_PATH = EXP_DIR / "results" / "summary.md"
SUMMARY_JSON_PATH = EXP_DIR / "results" / "summary.json"

EXPERIMENT_ID = "exp012_lqg_spectral"
METRIC_NAME = "slowdown_breakpoint_rho_eff"
SOURCE_ITERATION_ID = "cl-iter-2026-08-15-002"

# --- LOCKED environment constants (prereg v2.1, verbatim; duplicated in
# dynamics.py on purpose — a test pins the two copies equal) -------------
RHO_EFF_GRID = (0.21, 0.32, 0.42, 0.53, 0.63, 0.74, 0.84)
N_SEEDS = 30
T_MAX = 20000
DELTA = 0.05
FULL_TOL = 1e-6
ARMS = ("FULL", "BOUNDED")

# --- LOCKED decision-rule constants (prereg v2.1, verbatim) -------------
DELTA_BIC_MIN = 10.0        # rule 1: ΔBIC = BIC_1seg − BIC_2seg >= 10
BIC_K_TWO_SEGMENT = 4       # k=4 (two segments; breakpoint is a parameter)
BIC_K_LINE = 2              # k=2 (single line)
BREAK_GRID_STEP = 0.005     # dense breakpoint grid step
BREAK_GRID_LO = 0.21        # grid search over ρ* ∈ [0.21, 0.84]
BREAK_GRID_HI = 0.84
MIN_POINTS_EACH_SIDE = 2    # >= 2 data points strictly each side of ρ*
INTERIOR_LO = 0.32          # rule 2: 0.32 <= ρ* < 0.74
INTERIOR_HI = 0.74
CAPPED_FRAC_MAX = 0.50      # rule 2: two cells above ρ* each < 50% capped
SLOPE_ABOVE_MIN = 2.0       # rule 3: slope above ρ* >= 2.0 (ln R / ρ_eff)
SLOPE_RATIO_MIN = 3.0       # rule 3: AND >= 3× max(slope below, 0.25)
SLOPE_BELOW_FLOOR = 0.25
BOOTSTRAP_B = 1000          # rule 4: seed-level bootstrap B=1000
BOOTSTRAP_PASS_MIN = 0.90   # rules 1–3 hold in >= 90% of resamples
BOOTSTRAP_IQR_MAX = 0.15    # bootstrap IQR of ρ* <= 0.15 (ALL resamples)
# Bootstrap RNG seed: NOT in the locked text; pinned here for
# reproducibility of the rule-4 evaluation.
BOOTSTRAP_SEED = 20260817

# Scope limit (prereg v2.1, VERBATIM — binding on the summary and the
# ledger events; it must reach the evidence_level_changed/cluster event).
SCOPE_LIMIT_NOTE = (
    "This environment is a linear belief-best-response contraction "
    "surrogate — it is NOT an LQG game (no state dynamics or cost "
    "matrices) and NOT partially nested (the sweep requires cyclic "
    "digraphs; genuinely nested/acyclic structures have adjacency "
    "spectral radius exactly 0, degenerating the claim's threshold "
    "quantity — this degeneracy is itself recorded as a finding about "
    "the claim's framing). Any Verdict binds to the surrogate; the "
    "evidence_level_changed / cluster event must carry this scope limit "
    "verbatim.")

# Rule-5 adjudication phrasing (prereg v2.1, verbatim clause).
NO_PHRASE_CENSORING = (
    "A breakpoint present only under the T_bounded := t_max convention "
    "is adjudicated as censoring geometry ⇒ effect_confirmed = FALSE, "
    "with the cycling-fraction-vs-ρ curve reported as its own named "
    "non-gating finding (cycling_fraction_vs_rho).")


# --- data loading --------------------------------------------------------

def _load_rows(path: Path = TRIALS_PATH) -> list[dict]:
    if not path.exists():
        raise SystemExit(f"FATAL: {path} does not exist — run run.py first")
    rows: list[dict] = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _grid_key(rho: float) -> float | None:
    """Map a row's rho_eff onto the locked grid value (exact float
    round-trip expected; tolerance guards only JSON representation)."""
    for g in RHO_EFF_GRID:
        if abs(float(rho) - g) < 1e-9:
            return g
    return None


def _cell_map(rows: list[dict]) -> dict:
    """(grid ρ, arm) -> list of valid rows. Error rows and off-grid rows
    are excluded here and counted by the caller."""
    cells: dict = {(r, a): [] for r in RHO_EFF_GRID for a in ARMS}
    for row in rows:
        if "error" in row:
            continue
        g = _grid_key(row.get("rho_eff", float("nan")))
        arm = row.get("arm")
        if g is None or arm not in ARMS:
            continue
        cells[(g, arm)].append(row)
    return cells


# --- LOCKED fit (rule 1 machinery) ---------------------------------------

class PiecewiseFitter:
    """Continuous two-segment least-squares fitter on a fixed x grid.

    Breakpoint by dense grid search (step 0.005) over [0.21, 0.84] with
    >= 2 data points strictly on each side of every candidate (LOCKED).
    Model at candidate c: y = a + b_lo·min(x−c, 0) + b_hi·max(x−c, 0)
    (continuous at c). RSS-minimizing candidate wins; ties break to the
    lowest c (np.argmin). Design matrices/pseudo-inverses precomputed so
    the rule-4 bootstrap refits cheaply.
    """

    def __init__(self, x=RHO_EFF_GRID):
        self.x = np.asarray(x, dtype=float)
        n_steps = int(round((BREAK_GRID_HI - BREAK_GRID_LO) / BREAK_GRID_STEP))
        dense = BREAK_GRID_LO + BREAK_GRID_STEP * np.arange(n_steps + 1)
        keep = [c for c in dense
                if (self.x < c).sum() >= MIN_POINTS_EACH_SIDE
                and (self.x > c).sum() >= MIN_POINTS_EACH_SIDE]
        self.candidates = np.asarray(keep, dtype=float)
        ones = np.ones_like(self.x)
        mats = [np.column_stack([ones,
                                 np.minimum(self.x - c, 0.0),
                                 np.maximum(self.x - c, 0.0)])
                for c in self.candidates]
        if mats:
            self.X2 = np.stack(mats)                  # (C, n, 3)
            self.P2 = np.linalg.pinv(self.X2)         # (C, 3, n)
        else:
            self.X2 = np.zeros((0, self.x.size, 3))
            self.P2 = np.zeros((0, 3, self.x.size))
        self.X1 = np.column_stack([ones, self.x])
        self.P1 = np.linalg.pinv(self.X1)

    def fit(self, y) -> dict:
        """Unweighted LS on the (x, y) points; natural logs upstream."""
        y = np.asarray(y, dtype=float)
        n = self.x.size
        if (y.shape != self.x.shape or not np.all(np.isfinite(y))
                or self.candidates.size == 0):
            return {"degenerate": True, "rho_star": None,
                    "slope_below": None, "slope_above": None,
                    "delta_bic": None, "rss_2seg": None, "rss_1seg": None,
                    "bic_2seg": None, "bic_1seg": None, "line_slope": None,
                    "value_at_break": None}
        params = self.P2 @ y                          # (C, 3)
        fitted = np.einsum("cij,cj->ci", self.X2, params)
        rss2_all = ((y - fitted) ** 2).sum(axis=1)
        i = int(np.argmin(rss2_all))
        rss2 = float(rss2_all[i])
        coef1 = self.P1 @ y
        rss1 = float(((y - self.X1 @ coef1) ** 2).sum())
        # RSS can be exactly 0 on degenerate/synthetic inputs: BIC -> -inf
        # and a doubly-perfect fit yields dBIC = nan, which FAILS rule 1
        # (nan >= 10 is False) — honest, never coerced.
        with np.errstate(divide="ignore", invalid="ignore"):
            bic2 = n * np.log(rss2 / n) + BIC_K_TWO_SEGMENT * np.log(n)
            bic1 = n * np.log(rss1 / n) + BIC_K_LINE * np.log(n)
            delta_bic = float(bic1 - bic2)
        return {
            "degenerate": False,
            "rho_star": float(self.candidates[i]),
            "value_at_break": float(params[i, 0]),
            "slope_below": float(params[i, 1]),
            "slope_above": float(params[i, 2]),
            "rss_2seg": rss2,
            "rss_1seg": rss1,
            "bic_2seg": float(bic2),
            "bic_1seg": float(bic1),
            "delta_bic": delta_bic,
            "line_slope": float(coef1[1]),
        }


_FITTER: PiecewiseFitter | None = None


def _fitter() -> PiecewiseFitter:
    global _FITTER
    if _FITTER is None:
        _FITTER = PiecewiseFitter()
    return _FITTER


# --- rules 1-3 on a set of medians ---------------------------------------

def rules123(fit: dict, capped_frac: dict) -> dict:
    """Rules 1–3 (LOCKED) given a fit and the per-ρ bounded-arm capped
    fractions. Degenerate fits fail every rule (never coerced)."""
    if fit.get("degenerate"):
        return {"rule1_pass": False, "rule2_pass": False,
                "rule3_pass": False, "all_pass": False,
                "cells_above": [], "degenerate": True}
    dbic = fit["delta_bic"]
    rule1 = bool(dbic is not None and dbic >= DELTA_BIC_MIN)  # NaN -> False
    rs = fit["rho_star"]
    interior = bool(INTERIOR_LO <= rs < INTERIOR_HI)
    cells_above = [g for g in RHO_EFF_GRID if g > rs][:2]
    uncensored = (len(cells_above) == 2 and all(
        capped_frac.get(g) is not None and capped_frac[g] < CAPPED_FRAC_MAX
        for g in cells_above))
    rule2 = bool(interior and uncensored)
    sa, sb = fit["slope_above"], fit["slope_below"]
    rule3 = bool(np.isfinite(sa) and np.isfinite(sb)
                 and sa >= SLOPE_ABOVE_MIN
                 and sa >= SLOPE_RATIO_MIN * max(sb, SLOPE_BELOW_FLOOR))
    return {"rule1_pass": rule1, "rule2_pass": rule2, "rule3_pass": rule3,
            "all_pass": bool(rule1 and rule2 and rule3),
            "interior": interior, "uncensored_cells_above": uncensored,
            "cells_above": cells_above, "degenerate": False}


def _ln_r(median_bounded: np.ndarray, median_full: np.ndarray) -> np.ndarray:
    """ln R(ρ) = ln(median T_bounded / median T_full) — natural log
    (LOCKED). Non-positive medians propagate as -inf/nan, which the fit
    reports as degenerate (never coerced)."""
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.log(np.asarray(median_bounded, dtype=float)
                      / np.asarray(median_full, dtype=float))


# --- rule 4: seed-level bootstrap ----------------------------------------

def _bootstrap(tb: dict, tf: dict, capped: dict, n_seeds: int) -> dict:
    """Seed-level bootstrap (LOCKED): B=1000 resamples of the seed index
    vector (the seed is the resampling unit — the paired triple moves
    together across all 14 cells), recompute medians + capped fractions,
    refit rules 1–3. Degenerate/no-ρ* resamples count as rules-failures;
    the IQR is over ALL resamples' fitted ρ* (never the passing subset).
    """
    fitter = _fitter()
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    n_pass = 0
    n_degenerate = 0
    stars: list[float] = []
    for _ in range(BOOTSTRAP_B):
        idx = rng.integers(0, n_seeds, n_seeds)
        med_b = np.array([np.median(tb[g][idx]) for g in RHO_EFF_GRID])
        med_f = np.array([np.median(tf[g][idx]) for g in RHO_EFF_GRID])
        cf = {g: float(np.mean(capped[g][idx])) for g in RHO_EFF_GRID}
        fit = fitter.fit(_ln_r(med_b, med_f))
        if fit["degenerate"]:
            n_degenerate += 1
            continue  # rules-failure; no ρ* for the IQR set
        stars.append(fit["rho_star"])
        if rules123(fit, cf)["all_pass"]:
            n_pass += 1
    pass_fraction = n_pass / BOOTSTRAP_B
    if stars:
        iqr = float(np.percentile(stars, 75) - np.percentile(stars, 25))
    else:
        iqr = None
    rule4_pass = bool(pass_fraction >= BOOTSTRAP_PASS_MIN
                      and iqr is not None and iqr <= BOOTSTRAP_IQR_MAX)
    return {"B": BOOTSTRAP_B, "pass_fraction": pass_fraction,
            "pass_fraction_min": BOOTSTRAP_PASS_MIN,
            "iqr_rho_star": iqr, "iqr_max": BOOTSTRAP_IQR_MAX,
            "n_degenerate": n_degenerate, "rng_seed": BOOTSTRAP_SEED,
            "pass": rule4_pass}


# --- H0_construction (closed-form null on record) -------------------------

def _h0_construction(cells: dict, ln_r_obs: np.ndarray) -> dict:
    rho = np.asarray(RHO_EFF_GRID)
    e0_b = np.array([_median_or_nan([r["e0_inf"] for r in cells[(g, "BOUNDED")]])
                     for g in RHO_EFF_GRID])
    e0_f = np.array([_median_or_nan([r["e0_inf"] for r in cells[(g, "FULL")]])
                     for g in RHO_EFF_GRID])
    r_dead = rho * (DELTA / 2.0) / (1.0 - rho)
    with np.errstate(divide="ignore", invalid="ignore"):
        t_pred_bounded = np.log(e0_b / r_dead) / (-np.log(rho))
        t_pred_full = np.log(e0_f / FULL_TOL) / (-np.log(rho))
        ln_r_pred = np.log(t_pred_bounded / t_pred_full)
    gaps = np.abs(ln_r_obs - ln_r_pred)
    finite = np.isfinite(gaps)
    return {
        "rho_grid": list(RHO_EFF_GRID),
        "e0_bounded": e0_b.tolist(),
        "e0_full": e0_f.tolist(),
        "r_dead": r_dead.tolist(),
        "t_pred_bounded": t_pred_bounded.tolist(),
        "t_pred_full": t_pred_full.tolist(),
        "ln_r_pred": ln_r_pred.tolist(),
        "ln_r_observed": ln_r_obs.tolist(),
        "abs_ln_gap": gaps.tolist(),
        "max_abs_ln_gap": float(np.max(gaps[finite])) if finite.any() else None,
        "n_nonfinite_gaps": int((~finite).sum()),
        "note": ("R_pred, not 1, is the no-threshold expectation; the "
                 "null is SMOOTH in ρ — rule 3's positive-slope floor is "
                 "the load-bearing defense against its own curvature."),
    }


def _median_or_nan(values: list) -> float:
    return float(np.median(values)) if values else float("nan")


# --- summary --------------------------------------------------------------

def build_summary(rows: list[dict]) -> dict:
    """Pure: trial rows -> summary dict carrying the LOCKED verdict."""
    cells = _cell_map(rows)
    n_errors = sum(1 for r in rows if "error" in r)

    cell_counts = {f"{g:g}/{a}": len(cells[(g, a)])
                   for g in RHO_EFF_GRID for a in ARMS}
    # The rules were LOCKED at 30 seeds x 7 rho_eff x 2 arms; error rows
    # are excluded above and counted below (exp010 norm) — the guard is
    # on the valid per-cell counts.
    counts_match_lock = all(
        len(cells[(g, a)]) == N_SEEDS for g in RHO_EFF_GRID for a in ARMS)

    # Per-cell medians + bounded-arm capped fractions (capped = cycling
    # OR budget_exhausted — the T := t_max convention rows).
    med_b = np.array([_median_or_nan([r["T"] for r in cells[(g, "BOUNDED")]])
                      for g in RHO_EFF_GRID])
    med_f = np.array([_median_or_nan([r["T"] for r in cells[(g, "FULL")]])
                      for g in RHO_EFF_GRID])

    def _is_capped(r: dict) -> bool:
        return bool(r.get("cycling") or r.get("budget_exhausted"))

    capped_frac = {}
    cycling_curve = {}
    for g in RHO_EFF_GRID:
        brows = cells[(g, "BOUNDED")]
        n = len(brows)
        n_cyc = sum(1 for r in brows if r.get("cycling"))
        n_bud = sum(1 for r in brows if r.get("budget_exhausted"))
        n_cap = sum(1 for r in brows if _is_capped(r))
        capped_frac[g] = (n_cap / n) if n else None
        cycling_curve[f"{g:g}"] = {
            "n": n,
            "cycling_frac": (n_cyc / n) if n else None,
            "budget_exhausted_frac": (n_bud / n) if n else None,
            "capped_frac": capped_frac[g],
        }

    fitter = _fitter()
    ln_r_obs = _ln_r(med_b, med_f)
    fit = fitter.fit(ln_r_obs)
    main_rules = rules123(fit, capped_frac)

    rule1 = {"delta_bic": fit["delta_bic"], "delta_bic_min": DELTA_BIC_MIN,
             "bic_1seg": fit["bic_1seg"], "bic_2seg": fit["bic_2seg"],
             "rss_1seg": fit["rss_1seg"], "rss_2seg": fit["rss_2seg"],
             "pass": main_rules["rule1_pass"]}
    rule2 = {"rho_star": fit["rho_star"],
             "interior_lo": INTERIOR_LO, "interior_hi": INTERIOR_HI,
             "interior": main_rules.get("interior"),
             "cells_above": main_rules["cells_above"],
             "capped_frac_cells_above": [capped_frac.get(g)
                                         for g in main_rules["cells_above"]],
             "capped_frac_max": CAPPED_FRAC_MAX,
             "pass": main_rules["rule2_pass"]}
    rule3 = {"slope_above": fit["slope_above"],
             "slope_below": fit["slope_below"],
             "slope_above_min": SLOPE_ABOVE_MIN,
             "slope_ratio_min": SLOPE_RATIO_MIN,
             "slope_below_floor": SLOPE_BELOW_FLOOR,
             "pass": main_rules["rule3_pass"]}

    # Rule 4 — seed-level bootstrap over the seeds common to all cells
    # (the locked data has 0..29 in every cell; anything else already
    # fails the counts guard but is still evaluated honestly).
    seed_maps = {(g, a): {r["seed_index"]: r for r in cells[(g, a)]}
                 for g in RHO_EFF_GRID for a in ARMS}
    common = set.intersection(*(set(m) for m in seed_maps.values())) \
        if seed_maps else set()
    common_seeds = sorted(common)
    if len(common_seeds) >= 2:
        tb = {g: np.array([seed_maps[(g, "BOUNDED")][s]["T"]
                           for s in common_seeds], dtype=float)
              for g in RHO_EFF_GRID}
        tf = {g: np.array([seed_maps[(g, "FULL")][s]["T"]
                           for s in common_seeds], dtype=float)
              for g in RHO_EFF_GRID}
        capped_by_seed = {g: np.array(
            [_is_capped(seed_maps[(g, "BOUNDED")][s]) for s in common_seeds],
            dtype=float) for g in RHO_EFF_GRID}
        rule4 = _bootstrap(tb, tf, capped_by_seed, len(common_seeds))
        rule4["n_seeds"] = len(common_seeds)
    else:
        rule4 = {"B": BOOTSTRAP_B, "pass": False, "pass_fraction": None,
                 "iqr_rho_star": None, "n_degenerate": None,
                 "n_seeds": len(common_seeds),
                 "reason": "fewer than 2 seeds common to all 14 cells"}

    # Rule 5 — censoring robustness: bounded medians recomputed over
    # non-cycling, non-budget-exhausted trials only (full arm unchanged;
    # capped fractions stay a property of the full data).
    surv_med = []
    empty_cells = []
    for g in RHO_EFF_GRID:
        surv = [r["T"] for r in cells[(g, "BOUNDED")] if not _is_capped(r)]
        if surv:
            surv_med.append(float(np.median(surv)))
        else:
            surv_med.append(float("nan"))
            empty_cells.append(g)
    if empty_cells:
        fit5 = {"degenerate": True, "rho_star": None, "delta_bic": None,
                "slope_above": None, "slope_below": None}
        rules5 = rules123(fit5, capped_frac)
        rule5_note = (f"survivor recompute undefined — zero uncensored "
                      f"bounded trials in cell(s) "
                      f"{[f'{g:g}' for g in empty_cells]}")
    else:
        fit5 = fitter.fit(_ln_r(np.array(surv_med), med_f))
        rules5 = rules123(fit5, capped_frac)
        rule5_note = None
    rule5 = {"survivor_medians_bounded": surv_med,
             "empty_survivor_cells": [f"{g:g}" for g in empty_cells],
             "fit": {k: fit5.get(k) for k in
                     ("rho_star", "delta_bic", "slope_above", "slope_below",
                      "degenerate")},
             "rule1_pass": rules5["rule1_pass"],
             "rule2_pass": rules5["rule2_pass"],
             "rule3_pass": rules5["rule3_pass"],
             "note": rule5_note,
             "pass": rules5["all_pass"]}

    h0 = _h0_construction(cells, ln_r_obs)
    if fit["rho_star"] is not None:
        below = [abs(o - p) for g, o, p in
                 zip(RHO_EFF_GRID, ln_r_obs.tolist(), h0["ln_r_pred"])
                 if g <= fit["rho_star"] and np.isfinite(o - p)]
        h0["max_abs_ln_gap_below_rho_star"] = max(below) if below else None

    r123 = main_rules["all_pass"]
    effect_confirmed = bool(r123 and rule4["pass"] and rule5["pass"]
                            and counts_match_lock)
    verdict = "YES" if effect_confirmed else "NO"

    if effect_confirmed:
        verdict_reason = (
            f"all five LOCKED rules met: dBIC={fit['delta_bic']:.2f}>="
            f"{DELTA_BIC_MIN:g}, rho*={fit['rho_star']:.3f} interior with "
            f"uncensored cells above, slope_above={fit['slope_above']:.2f}, "
            f"bootstrap pass_fraction={rule4['pass_fraction']:.3f} "
            f"IQR={rule4['iqr_rho_star']:.4f}, censoring-robust.")
    elif r123 and rule4["pass"] and not rule5["pass"]:
        verdict_reason = NO_PHRASE_CENSORING
        if rule5_note:
            verdict_reason += f" [{rule5_note}]"
    else:
        failed = [name for name, ok in (
            ("rule1(dBIC)", main_rules["rule1_pass"]),
            ("rule2(interior/uncensored)", main_rules["rule2_pass"]),
            ("rule3(slopes)", main_rules["rule3_pass"]),
            ("rule4(bootstrap)", rule4["pass"]),
            ("rule5(censoring)", rule5["pass"])) if not ok]
        verdict_reason = ("LOCKED criteria not met: failed "
                          + ", ".join(failed) + ".")
    if not counts_match_lock:
        verdict_reason += (
            f" [trial counts deviate from the LOCKED design (30 seeds x 7 "
            f"rho_eff x 2 arms, 0 errors): errors={n_errors}, "
            f"min cell n={min(cell_counts.values()) if cell_counts else 0} "
            f"— not coerced]")

    value = float(fit["rho_star"]) if effect_confirmed else -1.0

    return {
        "experiment_id": EXPERIMENT_ID,
        "source_iteration_id": SOURCE_ITERATION_ID,
        "metric": METRIC_NAME,
        "value": value,
        "verdict": verdict,
        "effect_confirmed": effect_confirmed,
        "verdict_reason": verdict_reason,
        "scope_limit": SCOPE_LIMIT_NOTE,
        "fit": fit,                       # raw fit ALWAYS reported (LOCKED)
        "rule1": rule1,
        "rule2": rule2,
        "rule3": rule3,
        "rule4": rule4,
        "rule5": rule5,
        "counts_match_lock": counts_match_lock,
        "cell_counts": cell_counts,
        "medians": {"rho_grid": list(RHO_EFF_GRID),
                    "median_t_full": med_f.tolist(),
                    "median_t_bounded": med_b.tolist(),
                    "ln_r": ln_r_obs.tolist()},
        "h0_construction": h0,
        "cycling_fraction_vs_rho": cycling_curve,
        "n_rows": len(rows),
        "n_errors": n_errors,
    }


# --- rendering ------------------------------------------------------------

def _fmt(x, spec=".4f") -> str:
    if x is None:
        return "n/a"
    try:
        if not np.isfinite(x):
            return str(x)
    except TypeError:
        return str(x)
    return format(x, spec)


def render_markdown(summary: dict) -> str:
    r1, r2, r3 = summary["rule1"], summary["rule2"], summary["rule3"]
    r4, r5 = summary["rule4"], summary["rule5"]
    fit = summary["fit"]
    med = summary["medians"]
    h0 = summary["h0_construction"]
    lines = [
        # LINE 1 carries the verdict token (bridge/promotion contract).
        f"Verdict={summary['verdict']}. {summary['verdict_reason']}",
        "",
        "# exp012 — spectral-slowdown summary (contraction surrogate)",
        "",
        f"Claim under test ({SOURCE_ITERATION_ID}, L1): bounded rationality "
        "(precision-constrained belief updating) slows convergence "
        "specifically when the information structure's adjacency spectral "
        "radius exceeds a critical threshold. LOCKED prereg (v2.1): "
        "experiments/PREREG_l2block_2026-08-17.md.",
        "",
        "## Scope limit (binding, verbatim)",
        "",
        summary["scope_limit"],
        "",
        "## Medians and fit",
        "",
        f"- rho_eff grid: {med['rho_grid']}",
        f"- median T_full: {[round(v, 2) for v in med['median_t_full']]}",
        f"- median T_bounded: "
        f"{[round(v, 2) for v in med['median_t_bounded']]}",
        f"- ln R: {[round(v, 4) for v in med['ln_r']]}",
        f"- fitted rho*: {_fmt(fit['rho_star'], '.3f')} | slope below/above: "
        f"{_fmt(fit['slope_below'])} / {_fmt(fit['slope_above'])}",
        "",
        "## Rule 1 — dBIC (LOCKED)",
        "",
        f"- dBIC = BIC_1seg - BIC_2seg = {_fmt(r1['delta_bic'], '.3f')} "
        f"(>= {DELTA_BIC_MIN:g}: {r1['pass']})",
        "",
        "## Rule 2 — interior breakpoint, uncensored cells above (LOCKED)",
        "",
        f"- rho* in [{INTERIOR_LO}, {INTERIOR_HI}): {r2['interior']}",
        f"- cells above {r2['cells_above']} capped fractions "
        f"{[_fmt(c) for c in r2['capped_frac_cells_above']]} "
        f"(each < {CAPPED_FRAC_MAX}: {r2['pass'] and r2['interior']})",
        f"- rule 2 pass: {r2['pass']}",
        "",
        "## Rule 3 — slope floors (LOCKED)",
        "",
        f"- slope above {_fmt(r3['slope_above'])} >= {SLOPE_ABOVE_MIN} and "
        f">= {SLOPE_RATIO_MIN}x max(slope below {_fmt(r3['slope_below'])}, "
        f"{SLOPE_BELOW_FLOOR}): {r3['pass']}",
        "",
        "## Rule 4 — seed-level bootstrap (LOCKED)",
        "",
        f"- B={r4.get('B')}, pass fraction "
        f"{_fmt(r4.get('pass_fraction'), '.3f')} "
        f"(>= {BOOTSTRAP_PASS_MIN}), IQR(rho*) "
        f"{_fmt(r4.get('iqr_rho_star'), '.4f')} (<= {BOOTSTRAP_IQR_MAX}), "
        f"degenerate resamples {r4.get('n_degenerate')}",
        f"- rule 4 pass: {r4['pass']}",
        "",
        "## Rule 5 — censoring robustness (LOCKED)",
        "",
        f"- survivor-median refit: rho* "
        f"{_fmt(r5['fit'].get('rho_star'), '.3f')}, rules 1-3 "
        f"{r5['rule1_pass']}/{r5['rule2_pass']}/{r5['rule3_pass']}"
        + (f" — {r5['note']}" if r5.get("note") else ""),
        f"- rule 5 pass: {r5['pass']}",
        "",
        "## H0_construction (closed-form null on record, non-gating)",
        "",
        f"- ln R_pred: {[round(v, 4) if np.isfinite(v) else None for v in h0['ln_r_pred']]}",
        f"- max |ln R_obs - ln R_pred|: {_fmt(h0['max_abs_ln_gap'])}",
        f"- {h0['note']}",
        "",
        "## Cycling fraction vs rho (named non-gating finding)",
        "",
    ]
    for g, d in summary["cycling_fraction_vs_rho"].items():
        lines.append(
            f"- rho={g}: cycling {_fmt(d['cycling_frac'], '.3f')}, "
            f"budget {_fmt(d['budget_exhausted_frac'], '.3f')}, "
            f"capped {_fmt(d['capped_frac'], '.3f')} (n={d['n']})")
    lines += [
        "",
        f"metric={summary['metric']} value={summary['value']}",
        f"Rows: {summary['n_rows']} (errors: {summary['n_errors']}). "
        f"Counts match LOCKED design: {summary['counts_match_lock']}.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    rows = _load_rows()
    summary = build_summary(rows)
    SUMMARY_MD_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_MD_PATH.write_text(render_markdown(summary))
    SUMMARY_JSON_PATH.write_text(json.dumps(summary, indent=2) + "\n")
    print(f"wrote {SUMMARY_MD_PATH}")
    print(f"wrote {SUMMARY_JSON_PATH}")
    print(f"verdict: {summary['verdict']} — {summary['verdict_reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
