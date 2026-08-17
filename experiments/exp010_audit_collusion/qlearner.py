#!/usr/bin/env python3
"""exp010 — tabular Q-learner, constants pinned by the LOCKED prereg
(experiments/PREREG_l2block_2026-08-17.md §exp010_audit_collusion).

Pinned: alpha=0.1, gamma=0.95, epsilon-greedy with eps 0.20 -> 0.01 via
multiplicative decay 0.999 applied once per round (floor reached by round
~2995, so the last-1000 measurement window is a converged-eps window).

State = (min(rounds_since_last_audit, 7), own_last, opp_last) -> the
counter cap at 7 gives BOTH audit arms an identical 8 x 2 x 2 = 32-state
space (state-cardinality confound removal, prereg amendment). 2 actions.

Same agent code in every arm (prereg: "Same agent code in every arm";
the NONE arm feeds counter == 0).
"""
from __future__ import annotations

import random

# --- pinned learner constants (LOCKED prereg, copied verbatim) ----------
ALPHA = 0.1
GAMMA = 0.95
EPS_START = 0.20
EPS_FLOOR = 0.01
EPS_DECAY = 0.999  # multiplicative, once per round

COUNTER_CAP = 7          # values >= 7 collapse to 7
N_COUNTER = COUNTER_CAP + 1
N_ACTIONS = 2
N_STATES = N_COUNTER * N_ACTIONS * N_ACTIONS  # 8 x 2 x 2 = 32


def state_index(counter_capped: int, own_last: int, opp_last: int) -> int:
    """Bijective (counter, own_last, opp_last) -> [0, 32) index.
    Out-of-range components are a caller bug — raised, never clamped
    (inviolate rule 4)."""
    if not 0 <= counter_capped <= COUNTER_CAP:
        raise ValueError(f"counter_capped out of range: {counter_capped}")
    if own_last not in (0, 1) or opp_last not in (0, 1):
        raise ValueError(f"actions out of range: {own_last}, {opp_last}")
    return (counter_capped * N_ACTIONS + own_last) * N_ACTIONS + opp_last


class QLearner:
    """Independent tabular Q-learner (one per agent, no shared state).

    ``update()`` is called exactly once per round by the game loop; the
    eps decay lives inside it so the per-round decay pinned by the prereg
    cannot drift from the update cadence.
    """

    def __init__(
        self,
        rng: random.Random,
        alpha: float = ALPHA,
        gamma: float = GAMMA,
        eps: float = EPS_START,
        eps_floor: float = EPS_FLOOR,
        eps_decay: float = EPS_DECAY,
    ) -> None:
        self.rng = rng
        self.alpha = alpha
        self.gamma = gamma
        self.eps = eps
        self.eps_floor = eps_floor
        self.eps_decay = eps_decay
        self.q: list[list[float]] = [[0.0, 0.0] for _ in range(N_STATES)]

    def select_action(self, state: int) -> int:
        """eps-greedy. Greedy tie-break is pinned deterministic (lowest
        action index) so a fixed seed reproduces the trajectory exactly."""
        if self.rng.random() < self.eps:
            return self.rng.randrange(N_ACTIONS)
        row = self.q[state]
        return 0 if row[0] >= row[1] else 1

    def update(self, state: int, action: int, reward: float,
               next_state: int) -> None:
        """One-step Q-learning update + the once-per-round eps decay."""
        best_next = max(self.q[next_state])
        self.q[state][action] += self.alpha * (
            reward + self.gamma * best_next - self.q[state][action])
        self.eps = max(self.eps_floor, self.eps * self.eps_decay)
