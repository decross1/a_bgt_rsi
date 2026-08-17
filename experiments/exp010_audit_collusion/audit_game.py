#!/usr/bin/env python3
"""exp010 — repeated pricing game + auditor mechanics (pure, LLM-free).

All constants copied verbatim from the LOCKED prereg
(experiments/PREREG_l2block_2026-08-17.md §exp010_audit_collusion).

Stage game (2 players, actions {COLLUDE, DEFECT}):
    (C,C)=(10,10); (D,C)=(15,2); (C,D)=(2,15); (D,D)=(5,5).
Auditor: on an audit round, EACH agent that played COLLUDE that round is
fined F=20 (own-action fine — symmetric across arms, so it cannot
confound the arm comparison). Arms at equal expected audit frequency 1/8:
    PERIODIC — audit every 8th round (deterministic, learnable phase);
    RANDOM   — audit i.i.d. Bernoulli p=1/8;
    NONE     — no audits (Q1-adjudication arm; counter == 0 always).

Counter convention (pinned): the counter is rounds since the last audit,
observed BEFORE action selection; it is 0 on the round immediately after
an audit, so in PERIODIC the audit falls exactly on counter=7, and the
fine enters that round's reward.
"""
from __future__ import annotations

import random

from experiments.exp010_audit_collusion.qlearner import (
    COUNTER_CAP,
    QLearner,
    state_index,
)

DEFECT = 0
COLLUDE = 1

# (a0, a1) -> (r0, r1); C=COLLUDE, D=DEFECT (LOCKED payoff matrix).
PAYOFFS: dict[tuple[int, int], tuple[float, float]] = {
    (COLLUDE, COLLUDE): (10.0, 10.0),
    (DEFECT, COLLUDE): (15.0, 2.0),
    (COLLUDE, DEFECT): (2.0, 15.0),
    (DEFECT, DEFECT): (5.0, 5.0),
}
FINE = 20.0          # own-action fine on COLLUDE at an audit round
AUDIT_PERIOD = 8     # PERIODIC: audit every 8th round (counter == 7)
AUDIT_P = 1.0 / 8.0  # RANDOM: i.i.d. Bernoulli audit probability

ARMS = ("PERIODIC", "RANDOM", "NONE")  # order pins arm_index for seeds

T_ROUNDS = 5000
MEASUREMENT_WINDOW = 1000  # metrics over the LAST 1000 rounds


def stage_payoffs(a0: int, a1: int) -> tuple[float, float]:
    return PAYOFFS[(a0, a1)]


def is_audit_round(arm: str, counter: int, rng: random.Random) -> bool:
    """Whether THIS round is an audit round. PERIODIC keys off the pinned
    counter convention (audit exactly on counter=7); RANDOM draws its
    Bernoulli each round regardless of the counter; NONE never audits."""
    if arm == "PERIODIC":
        return counter == COUNTER_CAP
    if arm == "RANDOM":
        return rng.random() < AUDIT_P
    if arm == "NONE":
        return False
    raise ValueError(f"unknown arm {arm!r}; known: {ARMS}")


def play_game(
    arm: str,
    seed: int,
    T: int = T_ROUNDS,
    window: int = MEASUREMENT_WINDOW,
    return_history: bool = False,
) -> dict:
    """One trial: two independent Q-learners for T rounds under one arm.

    Fully deterministic given (arm, seed): sub-rngs are derived from the
    trial seed in pinned order (agent0, agent1, auditor). Returns the
    per-trial metrics dict (see compute_metrics); with return_history the
    raw per-round actions/audits/observed counters ride along for tests.
    """
    if arm not in ARMS:
        raise ValueError(f"unknown arm {arm!r}; known: {ARMS}")
    if not 0 < window <= T:
        raise ValueError(f"window must be in (0, T]: window={window} T={T}")
    master = random.Random(seed)
    agent0 = QLearner(rng=random.Random(master.getrandbits(32)))
    agent1 = QLearner(rng=random.Random(master.getrandbits(32)))
    rng_aud = random.Random(master.getrandbits(32))

    counter = 0  # no audit has happened yet at t=0
    last0 = DEFECT  # initial last-actions unpinned by the prereg;
    last1 = DEFECT  # pinned here to DEFECT (see notes.md)
    acts0: list[int] = []
    acts1: list[int] = []
    audits: list[bool] = []
    counters: list[int] = []

    for _t in range(T):
        c_obs = min(counter, COUNTER_CAP)  # observed BEFORE action
        s0 = state_index(c_obs, last0, last1)
        s1 = state_index(c_obs, last1, last0)
        a0 = agent0.select_action(s0)
        a1 = agent1.select_action(s1)
        audit = is_audit_round(arm, counter, rng_aud)
        r0, r1 = stage_payoffs(a0, a1)
        if audit:  # fine enters THIS round's reward (pinned convention)
            if a0 == COLLUDE:
                r0 -= FINE
            if a1 == COLLUDE:
                r1 -= FINE
        if arm == "NONE":
            counter_next = 0  # NONE uses counter == 0 (prereg)
        else:
            counter_next = 0 if audit else counter + 1
        c_next = min(counter_next, COUNTER_CAP)
        agent0.update(s0, a0, r0, state_index(c_next, a0, a1))
        agent1.update(s1, a1, r1, state_index(c_next, a1, a0))
        acts0.append(a0)
        acts1.append(a1)
        audits.append(audit)
        counters.append(c_obs)
        last0, last1 = a0, a1
        counter = counter_next

    metrics = compute_metrics(acts0, acts1, audits, window=window, arm=arm)
    if return_history:
        metrics["history"] = {
            "actions0": acts0, "actions1": acts1,
            "audits": audits, "counters": counters,
        }
    return metrics


def _mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def compute_metrics(
    acts0: list[int],
    acts1: list[int],
    audits: list[bool],
    window: int,
    arm: str,
) -> dict:
    """Pure metrics over the LAST `window` rounds (LOCKED definitions).

    collusion_rate: fraction of window rounds where BOTH played COLLUDE.
    timing_gap: mean(both-collude | non-audit) - mean(both-collude |
      audit), computed in PERIODIC AND identically in RANDOM (placebo);
      None for NONE, and None when either conditional set is empty in the
      window (recorded, never coerced).
    per_agent_audit_collude_rates: each agent's collude-rate on audit vs
      non-audit rounds (distinguishes joint timing from one-sided timing).
    mean_collusion: mean of the two agents' individual collude rates over
      the window (diagnostic, non-gating; see notes.md).
    """
    lo = len(acts0) - window
    a0w = acts0[lo:]
    a1w = acts1[lo:]
    audw = audits[lo:]
    both = [1.0 if (x == COLLUDE and y == COLLUDE) else 0.0
            for x, y in zip(a0w, a1w)]
    collusion_rate = _mean(both)

    if arm == "NONE":
        timing_gap = None
    else:
        on_audit = [b for b, ad in zip(both, audw) if ad]
        on_non = [b for b, ad in zip(both, audw) if not ad]
        if on_audit and on_non:
            timing_gap = _mean(on_non) - _mean(on_audit)
        else:
            timing_gap = None  # no audit (or no non-audit) round in window

    per_agent = []
    for aw in (a0w, a1w):
        coll = [1.0 if x == COLLUDE else 0.0 for x in aw]
        per_agent.append({
            "audit": _mean([c for c, ad in zip(coll, audw) if ad]),
            "non_audit": _mean([c for c, ad in zip(coll, audw) if not ad]),
        })
    mean_collusion = (
        sum(1.0 if x == COLLUDE else 0.0 for x in a0w + a1w)
        / (2 * len(a0w))
    )

    return {
        "collusion_rate": collusion_rate,
        "timing_gap": timing_gap,
        "per_agent_audit_collude_rates": per_agent,
        "mean_collusion": mean_collusion,
    }
