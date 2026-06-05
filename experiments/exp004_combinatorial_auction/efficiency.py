"""Allocative-efficiency metrics for exp004 (combinatorial auction).

Pure-Python, no LLM dependency. These metrics compare the welfare a
mechanism actually realized against the welfare the best feasible
allocation *could* have produced under the bidders' true valuations.

exp004 is the HARDEST SYNTHETIC rung of the sandbox spectrum:
combinatorial auctions over two items with a *known* optimal solution
(brute-force search over the small feasible-allocation set). It is the
on-ramp to the semi-synthetic mechanism-DESIGN tier — but it is NOT
that tier yet. Everything here has a closed-form ground truth, which is
exactly what lets us measure efficiency unambiguously.

Three definitions, all over the TRUE valuations (not the reported bids):

* ``optimal_welfare``    — the welfare of the welfare-maximizing feasible
                           allocation. The denominator of efficiency.
* ``realized_welfare``   — the welfare of the allocation a mechanism
                           actually chose. The numerator.
* ``allocative_efficiency`` — realized / optimal, clamped semantics:
                           when ``optimal == 0`` there is no welfare to
                           capture, so efficiency is defined as 1.0 (a
                           mechanism cannot do worse than nothing).

The ``allocation`` dict is the mechanism's ``{bidder_idx: bundle_tuple}``
map; ``valuations`` is the list of per-bidder true valuation dicts (each
mapping every bundle tuple in ``bundles.BUNDLES`` to a float >= 0).
"""
from __future__ import annotations

from experiments.exp004_combinatorial_auction.bundles import (
    allocation_welfare,
    feasible_allocations,
)


def optimal_welfare(valuations: list[dict]) -> float:
    """Welfare of the welfare-maximizing feasible allocation.

    Brute-forces every feasible allocation for ``len(valuations)``
    bidders and returns the maximum ``allocation_welfare`` over them.
    The empty (nothing-sold) allocation is always feasible and scores
    0.0, so the result is always >= 0.0.
    """
    n = len(valuations)
    return max(
        allocation_welfare(alloc, valuations)
        for alloc in feasible_allocations(n)
    )


def realized_welfare(allocation: dict, valuations: list[dict]) -> float:
    """True-valuation welfare of the allocation a mechanism chose.

    This evaluates the mechanism's allocation against the bidders' TRUE
    valuations (``allocation_welfare``), which is the honest measure of
    what the allocation was worth — independent of what bidders bid.
    """
    return allocation_welfare(allocation, valuations)


def allocative_efficiency(allocation: dict, valuations: list[dict]) -> float:
    """Realized welfare as a fraction of optimal welfare.

    Returns ``realized_welfare / optimal_welfare``. When the optimal
    welfare is exactly 0.0 there is no surplus available, so efficiency
    is defined as 1.0 (avoids division by zero and reflects that no
    mechanism could have captured more than nothing).
    """
    opt = optimal_welfare(valuations)
    if opt == 0.0:
        return 1.0
    return realized_welfare(allocation, valuations) / opt
