"""VCG (Clarke-pivot) combinatorial auction mechanism for exp004.

exp004 is the HARDEST SYNTHETIC rung of the sandbox spectrum:
combinatorial auctions over a 2-item world with a KNOWN closed-form
optimum (we can brute-force the welfare-maximizing allocation and the
exact Clarke-pivot payments). It is the on-ramp to — but NOT yet — the
semi-synthetic mechanism-DESIGN tier; here the mechanism is fixed and we
only check that the model behaves against a solved benchmark.

VCG is the cross-rung anchor: it is the canonical strategyproof
(dominant-strategy-truthful) combinatorial mechanism. Reporting one's
true valuation is a best response regardless of others' reports, so a
model that has internalised the mechanism should bid truthfully.

Pure-Python, no LLM dependency, fully seeded (the only randomness is
``rng``-driven tie-breaking among equal-welfare allocations).

Mechanism (Clarke pivot):
  - Pick the feasible allocation A* maximising REPORTED welfare
    (sum of each bidder's bid for the bundle it is allocated).
  - Each bidder i pays the externality it imposes on the others:
        p_i = W_{-i} - (W(A*) - b_i(A*_i))
    where W_{-i} is the maximum reported welfare achievable by the
    OTHER bidders when i is excluded entirely (i wins nothing), and
    (W(A*) - b_i(A*_i)) is the others' reported welfare in A*.
  - revenue = sum of payments.

This is the standard Clarke-pivot form; payments are >= 0 and a winner
who wins nothing in A* pays 0 (W_{-i} == others' welfare in A*).
"""
from __future__ import annotations

import random

from experiments.exp004_combinatorial_auction.bundles import (
    allocation_welfare,
    feasible_allocations,
)

MECHANISM = "vcg"


def _best_allocation(
    allocs: list[dict],
    bid_profile: list[dict],
    rng: random.Random | None,
) -> dict:
    """Welfare-maximising allocation under reported bids; rng tie-break.

    Ties (allocations within floating tolerance of the best reported
    welfare) are broken uniformly at random with ``rng`` when supplied,
    else the first encountered best allocation is returned (deterministic).
    """
    best_w = max(allocation_welfare(a, bid_profile) for a in allocs)
    winners = [
        a
        for a in allocs
        if abs(allocation_welfare(a, bid_profile) - best_w) <= 1e-9
    ]
    if rng is not None and len(winners) > 1:
        return rng.choice(winners)
    return winners[0]


def _welfare_excluding(
    excluded: int,
    bid_profile: list[dict],
    allocs: list[dict],
) -> float:
    """Max reported welfare over allocations that give ``excluded`` nothing.

    An allocation gives bidder ``excluded`` nothing when ``excluded`` is
    not a key in its winner map. We do NOT tie-break here — we only need
    the optimal achievable value W_{-i}.
    """
    best = 0.0
    for a in allocs:
        if excluded in a:
            continue
        w = allocation_welfare(a, bid_profile)
        if w > best:
            best = w
    return best


def clear(bid_profile: list[dict], *, rng: random.Random | None = None) -> dict:
    """Clear a VCG (Clarke-pivot) combinatorial auction.

    Args:
        bid_profile: list of bids, one per bidder, each a dict mapping
            every bundle tuple in BUNDLES -> reported value >= 0.
        rng: optional seeded Random for tie-breaking among equal-welfare
            allocations.

    Returns:
        {"allocation": {bidder_idx: bundle_tuple},
         "payments":   {bidder_idx: float},   # one entry per winner
         "revenue":    float,
         "mechanism":  "vcg"}
    """
    n = len(bid_profile)
    allocs = feasible_allocations(n)

    alloc = _best_allocation(allocs, bid_profile, rng)
    total_w = allocation_welfare(alloc, bid_profile)

    payments: dict[int, float] = {}
    for i, bundle in alloc.items():
        # Reported welfare of the OTHER bidders in the chosen allocation.
        others_in_alloc = total_w - bid_profile[i][bundle]
        # Best welfare the others could get with i excluded entirely.
        w_minus_i = _welfare_excluding(i, bid_profile, allocs)
        p = w_minus_i - others_in_alloc
        # Clarke pivot is provably >= 0; clamp only float dust, never a
        # genuine negative (none can arise). Keep the raw arithmetic
        # observable by rounding dust to exactly 0.0.
        if -1e-9 <= p < 0.0:
            p = 0.0
        payments[i] = p

    revenue = sum(payments.values())
    return {
        "allocation": alloc,
        "payments": payments,
        "revenue": revenue,
        "mechanism": MECHANISM,
    }
