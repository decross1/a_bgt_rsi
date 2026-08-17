#!/usr/bin/env python3
"""exp012 — quantized linear belief-contraction dynamics (pure numpy).

LOCKED design: experiments/PREREG_l2block_2026-08-17.md
§exp012_lqg_spectral (v2.1). Every constant below is copied verbatim
from the lock; any later change is a new dated amendment, never an edit.

Environment: N=8 agents; directed Erdős–Rényi graph p=0.35, no
self-loops, drawn fresh per seed — an acyclic instance (pre-rescale
spectral radius < 1e-6) is redrawn with the redraw count logged;
b_i, θ0_i ~ U[-1, 1] i.i.d. per seed; M = A · (ρ_eff / ρ(A));
synchronous update θ_{t+1} = b + M · belief(θ_t), no damping.

  FULL arm    : belief = identity. T_full = first t with
                ||θ_{t+1} − θ_t||∞ < 1e-6. θ* = (I − M)^{-1} b by
                direct linear solve, never the empirical limit.
  BOUNDED arm : belief = Q_Δ, Δ = 0.05, Q_Δ(x) = np.round(x/Δ)·Δ
                (ties-to-even, deterministic). Per-step check order is
                PINNED: compute q_t and θ_{t+1} = b + M·q_t; test
                FIXATION FIRST (θ_{t+1} == θ_t bitwise, equivalently
                q_t == q_{t-1}); only then the hash-set revisit
                (q_t seen before with q_t != q_{t-1}) ⇒ limit cycle,
                T := t_max = 20000, cycling=true; t_max reached with
                neither ⇒ T := t_max, budget_exhausted=true.

Pairing (PINNED): base seed 20260817; the triple (A_s, b_s, θ0_s) is
drawn ONCE from RNG(base+s) and SHARED across all 7 ρ_eff × 2 arms.
Draw order inside RNG(base+s), pinned here for reproducibility: the
graph A first (redraws consume further draws), then b, then θ0.
"""
from __future__ import annotations

import numpy as np

# --- LOCKED environment constants (prereg v2.1, verbatim) ---------------
N_AGENTS = 8
ER_P = 0.35
BASE_SEED = 20260817
N_SEEDS = 30
RHO_EFF_GRID = (0.21, 0.32, 0.42, 0.53, 0.63, 0.74, 0.84)
DELTA = 0.05          # quantizer step Q_Δ(x) = np.round(x/Δ)·Δ
T_MAX = 20000         # bounded-arm step budget; cycling/budget T convention
FULL_TOL = 1e-6       # full-arm settling tolerance (inf-norm)
ACYCLIC_RHO_MIN = 1e-6  # pre-rescale ρ(A) below this => acyclic => redraw
ARMS = ("FULL", "BOUNDED")

# Safety cap only — NOT part of the locked design. With p=0.35 on 8 nodes
# an acyclic draw is already rare; hitting this cap means the parameters
# were changed to something degenerate, which must fail loudly.
_MAX_REDRAWS = 10_000


def spectral_radius(a: np.ndarray) -> float:
    return float(np.max(np.abs(np.linalg.eigvals(np.asarray(a, dtype=float)))))


def quantize(x: np.ndarray) -> np.ndarray:
    """Q_Δ(x) = np.round(x/Δ)·Δ — ties-to-even, deterministic (LOCKED)."""
    return np.round(np.asarray(x, dtype=float) / DELTA) * DELTA


def draw_instance(seed_index: int, base_seed: int = BASE_SEED,
                  n: int = N_AGENTS, p: float = ER_P) -> dict:
    """Draw the per-seed triple (A_s, b_s, θ0_s) from RNG(base+s), once.

    Directed ER(p) with no self-loops; if the drawn digraph's pre-rescale
    spectral radius < 1e-6 (acyclic instance) redraw, counting redraws.
    n and p are parameters only for unit tests; defaults are LOCKED.
    """
    rng = np.random.default_rng(base_seed + seed_index)
    redraws = 0
    while True:
        a = (rng.random((n, n)) < p).astype(float)
        np.fill_diagonal(a, 0.0)
        rho_a = spectral_radius(a)
        if rho_a >= ACYCLIC_RHO_MIN:
            break
        redraws += 1
        if redraws > _MAX_REDRAWS:
            raise RuntimeError(
                f"draw_instance(seed_index={seed_index}, n={n}, p={p}): "
                f"{redraws} consecutive acyclic draws — degenerate parameters")
    b = rng.uniform(-1.0, 1.0, n)
    theta0 = rng.uniform(-1.0, 1.0, n)
    return {"A": a, "b": b, "theta0": theta0, "rho_A": rho_a,
            "redraws": redraws}


def make_m(a: np.ndarray, rho_a: float, rho_eff: float) -> np.ndarray:
    """Information matrix M = A · (ρ_eff / ρ(A)); ρ(M) = ρ_eff."""
    return np.asarray(a, dtype=float) * (rho_eff / rho_a)


def theta_star(m: np.ndarray, b: np.ndarray) -> np.ndarray:
    """θ* = (I − M)^{-1} b by direct linear solve (LOCKED — never the
    empirical limit)."""
    return np.linalg.solve(np.eye(m.shape[0]) - m, b)


def run_full(m: np.ndarray, b: np.ndarray, theta0: np.ndarray,
             t_max: int = T_MAX) -> dict:
    """FULL arm: T_full = first t with ||θ_{t+1} − θ_t||∞ < 1e-6."""
    theta = np.asarray(theta0, dtype=float).copy()
    for t in range(t_max):
        theta_next = b + m @ theta
        if np.max(np.abs(theta_next - theta)) < FULL_TOL:
            return {"T": t, "cycling": False, "budget_exhausted": False}
        theta = theta_next
    # ρ(M) < 1 makes this branch theoretically unreachable at the locked
    # grid; recorded honestly if it ever fires (never coerced).
    return {"T": t_max, "cycling": False, "budget_exhausted": True}


def run_bounded(m: np.ndarray, b: np.ndarray, theta0: np.ndarray,
                t_max: int = T_MAX) -> dict:
    """BOUNDED arm with the PINNED per-step check order (prereg v2.1).

    Each step t: q_t = Q_Δ(θ_t); θ_{t+1} = b + M·q_t.
      1. FIXATION FIRST: θ_{t+1} == θ_t (bitwise; equivalently
         q_t == q_{t-1}, since the update depends only on the quantized
         vector) ⇒ T = t.
      2. Only then hash-set revisit: q_t seen before with q_t != q_{t-1}
         ⇒ limit cycle (period >= 2) ⇒ T := t_max, cycling=true.
      3. t_max reached with neither ⇒ T := t_max, budget_exhausted=true.
    The natural other order (hash first) flags 100% of fixating
    trajectories as cycles — that is the exact regression the pin closes.
    """
    theta = np.asarray(theta0, dtype=float).copy()
    seen: set[bytes] = set()
    q_prev: np.ndarray | None = None
    for t in range(t_max):
        q = quantize(theta)
        theta_next = b + m @ q
        # (1) fixation FIRST (pinned order)
        if np.array_equal(theta_next, theta):
            return {"T": t, "cycling": False, "budget_exhausted": False}
        # (2) hash-set revisit => limit cycle
        key = q.tobytes()
        if key in seen and (q_prev is None or not np.array_equal(q, q_prev)):
            return {"T": t_max, "cycling": True, "budget_exhausted": False}
        seen.add(key)
        q_prev = q
        theta = theta_next
    # (3) budget exhausted
    return {"T": t_max, "cycling": False, "budget_exhausted": True}


def run_cell(instance: dict, rho_eff: float, arm: str,
             t_max: int = T_MAX) -> dict:
    """One (seed, ρ_eff, arm) cell on a SHARED per-seed instance.

    Only the M rescale and the belief map differ across a seed's 14
    cells (LOCKED pairing). Returns T/cycling/budget_exhausted plus
    e0_inf = ||θ0 − θ*||∞ with θ* from the direct solve.
    """
    if arm not in ARMS:
        raise ValueError(f"unknown arm {arm!r}; known: {ARMS}")
    m = make_m(instance["A"], instance["rho_A"], rho_eff)
    tstar = theta_star(m, instance["b"])
    e0_inf = float(np.max(np.abs(instance["theta0"] - tstar)))
    if arm == "FULL":
        res = run_full(m, instance["b"], instance["theta0"], t_max=t_max)
    else:
        res = run_bounded(m, instance["b"], instance["theta0"], t_max=t_max)
    res["e0_inf"] = e0_inf
    return res
