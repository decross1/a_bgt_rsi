"""Sequential second-price mechanism for exp004 (combinatorial auction).

exp004 is the HARDEST SYNTHETIC rung of the sandbox spectrum: combinatorial
auctions over two items with KNOWN analytic solutions. It is the on-ramp to —
but NOT yet — the semi-synthetic mechanism-DESIGN tier. Everything here is
pure-Python, fully seeded, with no LLM dependency.

This module is the diagnostic *middle* case. Rather than clearing the whole
combinatorial problem at once (the VCG-style global welfare maximization that a
sealed combinatorial mechanism would do), it sells item 0 and then item 1 in
two *separate* single-item second-price (Vickrey) auctions. Each bidder's
single-item willingness for item k is read straight off their reported bid
``bid[(k,)]``; their bundle bid ``bid[(0, 1)]`` is ignored by this mechanism.

Because the two items are sold independently, a bidder who wants the *pair*
must commit to item 0 before knowing whether they will also win item 1. That is
the classic **exposure problem**: a bidder can win one item at a price that only
made sense if they also won the other, and end up over-exposed. Selling the
items sequentially makes that failure mode observable, which is the whole point
of this middle rung.

Mechanism interface (shared across every exp004 mechanism):

    clear(bid_profile, *, rng=None) -> {
        "allocation": {bidder_idx: bundle_tuple},
        "payments":   {bidder_idx: float},
        "revenue":    float,
        "mechanism":  "sequential_second_price",
    }

A bidder who wins both single items is recorded once with the combined bundle
``(0, 1)``; a bidder who wins exactly one item is recorded with ``(0,)`` or
``(1,)``. Bidders who win nothing do not appear in ``allocation``/``payments``.
"""
from __future__ import annotations

import random


MECHANISM = "sequential_second_price"


def _single_item_second_price(
    bids: list[float], *, rng: random.Random
) -> tuple[int, float]:
    """One sealed-bid second-price auction over ``bids`` (positional).

    Returns ``(winner_idx, price_paid)`` where ``price_paid`` is the
    second-highest bid. Ties at the top are broken uniformly via ``rng``;
    when two or more bidders tie at the maximum the second-highest equals the
    maximum, so the winner pays their own bid. Mirrors exp003's auctioneer.
    """
    max_bid = max(bids)
    top_idxs = [i for i, b in enumerate(bids) if b == max_bid]
    if len(top_idxs) > 1:
        winner_idx = rng.choice(top_idxs)
        second_bid = max_bid
    else:
        winner_idx = top_idxs[0]
        remaining = [b for i, b in enumerate(bids) if i != winner_idx]
        second_bid = max(remaining)
    return winner_idx, second_bid


def clear(bid_profile: list[dict], *, rng: random.Random | None = None) -> dict:
    """Sell item 0 then item 1 as two independent second-price auctions.

    Args:
        bid_profile: one reported valuation dict per bidder. Bidder identity is
            positional. Each dict maps the bundle tuples ``(0,)``, ``(1,)`` and
            ``(0, 1)`` to non-negative floats; this mechanism reads only the
            two single-item bids ``bid[(0,)]`` and ``bid[(1,)]``.
        rng: optional ``random.Random`` used only for tie-breaking. Defaults to
            ``random.Random()`` (system entropy) when ``None`` so tests can pin
            behaviour with a seeded generator.

    Returns:
        ``{"allocation", "payments", "revenue", "mechanism"}``. ``allocation``
        maps each winning ``bidder_idx`` to the bundle they ended up with: a
        bidder who took only item 0 -> ``(0,)``, only item 1 -> ``(1,)``, and a
        bidder who won *both* single-item rounds -> the combined bundle
        ``(0, 1)``. ``payments`` maps each winning bidder to the sum of the
        second-prices they paid across the rounds they won. ``revenue`` is the
        sum of all payments.

    Raises:
        ValueError: if fewer than two bidders are supplied (a second-price
            auction needs a second bid to define the price).
    """
    if len(bid_profile) < 2:
        raise ValueError(
            f"clear requires at least 2 bidders; got {len(bid_profile)}"
        )

    rng = rng or random.Random()

    # Per-bidder accumulators. Winners may pick up one item in each round.
    won_items: dict[int, list[int]] = {}
    payments: dict[int, float] = {}

    for item in (0, 1):
        item_bids = [float(bid[(item,)]) for bid in bid_profile]
        winner_idx, price = _single_item_second_price(item_bids, rng=rng)
        won_items.setdefault(winner_idx, []).append(item)
        payments[winner_idx] = payments.get(winner_idx, 0.0) + price

    # Collapse per-item wins into a single bundle tuple per winning bidder.
    allocation: dict[int, tuple[int, ...]] = {
        idx: tuple(sorted(items)) for idx, items in won_items.items()
    }

    revenue = sum(payments.values())

    return {
        "allocation": allocation,
        "payments": payments,
        "revenue": revenue,
        "mechanism": MECHANISM,
    }
