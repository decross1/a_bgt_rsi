"""First-price (pay-your-bid) combinatorial mechanism for exp004.

exp004 is the HARDEST SYNTHETIC rung of the sandbox spectrum: a
combinatorial auction over two items with a KNOWN optimal solution. It is
the on-ramp to — but is NOT yet — the semi-synthetic mechanism-DESIGN
tier. This module is pure-Python, fully seedable, with no LLM dependency.

This mechanism is the first-price (pay-your-bid) clearing rule. The
auctioneer picks the feasible allocation that MAXIMIZES reported welfare
(the sum of bidders' bids for the bundles they are allocated), then each
winner pays THEIR OWN reported bid for the bundle they won. Unlike the
Vickrey (second-price) rule, first-price is NOT strategyproof: a truthful
bidder pays their full value and captures zero surplus, so rational
bidders should SHADE their bids below their true valuations. That gap is
exactly what exp004 is built to probe.
"""
from __future__ import annotations

import random

from experiments.exp004_combinatorial_auction.bundles import (
    allocation_welfare,
    feasible_allocations,
)

MECHANISM = "first_price"


def clear(bid_profile: list[dict], *, rng: random.Random | None = None) -> dict:
    """Clear a first-price combinatorial auction over the reported bids.

    The chosen allocation maximizes *reported* welfare — the sum of each
    winner's own bid for the bundle they are allocated — over every
    feasible allocation of items {0, 1} to ``len(bid_profile)`` bidders
    (including partial and nothing-sold allocations). Ties for the maximum
    are broken uniformly at random using ``rng`` so seeded callers get
    deterministic behaviour.

    Each winner pays their own reported bid for the bundle they won
    (pay-your-bid); bidders who win nothing pay nothing. Revenue is the
    sum of all payments.

    Args:
        bid_profile: one bid dict per bidder. Each bid maps each bundle
            tuple in ``BUNDLES`` to a non-negative float; bidder identity
            is positional (the index into this list).
        rng: optional ``random.Random`` used only to break ties among
            allocations of equal reported welfare. Defaults to a fresh
            ``random.Random()`` when ``None``.

    Returns:
        ``{"allocation": {bidder_idx: bundle_tuple},
           "payments": {bidder_idx: float},
           "revenue": float,
           "mechanism": "first_price"}``.
        Only winning bidders appear in ``allocation`` and ``payments``.
    """
    rng = rng or random.Random()

    allocs = feasible_allocations(len(bid_profile))
    best_welfare = max(allocation_welfare(a, bid_profile) for a in allocs)
    top_allocs = [
        a for a in allocs if allocation_welfare(a, bid_profile) == best_welfare
    ]
    allocation = rng.choice(top_allocs)

    # Pay-your-bid: each winner pays their own reported bid for their bundle.
    payments = {i: bid_profile[i][bundle] for i, bundle in allocation.items()}
    revenue = sum(payments.values())

    return {
        "allocation": allocation,
        "payments": payments,
        "revenue": revenue,
        "mechanism": MECHANISM,
    }
