"""Bundle / valuation model for exp004 — the combinatorial-auction rung.

exp004 is the HARDEST SYNTHETIC rung of the sandbox spectrum: a
combinatorial auction over two items with a KNOWN optimal solution
(welfare-maximizing allocation computable by brute force). It is the
on-ramp to — but is NOT yet — the semi-synthetic mechanism-DESIGN tier.
Everything here is pure-Python, fully seedable, with no LLM dependency.

There are two items, indexed 0 and 1. A bidder can want item 0 alone,
item 1 alone, or the pair {0, 1}. Those three non-empty bundles are the
sorted tuples in ``BUNDLES``. A *valuation* (and a *bid*) is a dict that
maps each of those three tuples to a non-negative float.
"""
from __future__ import annotations

import random

# The three non-empty bundles over items {0, 1}, as sorted tuples.
BUNDLES = [(0,), (1,), (0, 1)]


def draw_valuation(rng: random.Random) -> dict:
    """Draw one bidder's valuation over the three bundles.

    Standalone item values are i.i.d. ``U[0, 50]``. The pair value adds a
    synergy term ``U[-20, 20]`` to the sum of the standalone values:
    positive synergy means the items are complements, negative means they
    are substitutes. The pair value is floored at ``0.0`` so no valuation
    is ever negative.

    Args:
        rng: a ``random.Random`` instance; pass a seeded one for
            reproducibility.

    Returns:
        ``{(0,): v0, (1,): v1, (0, 1): v01}`` with every value ``>= 0``.
    """
    v0 = rng.uniform(0.0, 50.0)
    v1 = rng.uniform(0.0, 50.0)
    synergy = rng.uniform(-20.0, 20.0)
    v01 = max(0.0, v0 + v1 + synergy)
    return {(0,): v0, (1,): v1, (0, 1): v01}


def feasible_allocations(n_bidders: int) -> list[dict]:
    """Enumerate every feasible allocation of items {0, 1} to ``n_bidders``.

    An allocation maps ``bidder_idx -> bundle_tuple`` where the allocated
    bundles are pairwise item-disjoint across winners (no item goes to two
    bidders). Bidders not present in the dict win nothing. With only two
    items the full set of *sale patterns* is small and is enumerated
    exhaustively (no approximation):

      * nothing sold (the empty allocation ``{}``),
      * item 0 alone to some bidder ``i``: ``{i: (0,)}``,
      * item 1 alone to some bidder ``i``: ``{i: (1,)}``,
      * the pair to some bidder ``i``: ``{i: (0, 1)}``,
      * item 0 to ``i`` and item 1 to a *different* bidder ``j``:
        ``{i: (0,), j: (1,)}``.

    Args:
        n_bidders: number of bidders (>= 0).

    Returns:
        A list of allocation dicts. Always includes the empty allocation.
    """
    if n_bidders < 0:
        raise ValueError(f"n_bidders must be >= 0; got {n_bidders}")

    allocations: list[dict] = [{}]  # nothing sold
    for i in range(n_bidders):
        allocations.append({i: (0,)})       # item 0 alone to i
        allocations.append({i: (1,)})       # item 1 alone to i
        allocations.append({i: (0, 1)})     # both items as a pair to i
    # Items 0 and 1 split between two distinct bidders.
    for i in range(n_bidders):
        for j in range(n_bidders):
            if i != j:
                allocations.append({i: (0,), j: (1,)})
    return allocations


def allocation_welfare(alloc: dict, valuations: list[dict]) -> float:
    """Sum the winners' own valuations of the bundles they were allocated.

    Args:
        alloc: an allocation ``{bidder_idx: bundle_tuple}`` as produced by
            :func:`feasible_allocations`.
        valuations: per-bidder valuation dicts; ``valuations[i]`` is bidder
            ``i``'s valuation over ``BUNDLES``.

    Returns:
        ``sum(valuations[i][bundle] for i, bundle in alloc.items())``.
    """
    return sum(valuations[i][bundle] for i, bundle in alloc.items())
