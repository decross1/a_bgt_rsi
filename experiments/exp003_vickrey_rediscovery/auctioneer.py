"""Sealed-bid second-price (Vickrey) auctioneer for exp003.

Pure-Python, no LLM dependency. Highest bid wins; winner pays the
second-highest bid. Ties at the top are broken uniformly at random
using the provided ``rng`` (so tests can pin behaviour with a seeded
``random.Random``).
"""
from __future__ import annotations

import random
from typing import Sequence


def run_auction(bids: Sequence[float], *, rng: random.Random | None = None) -> dict:
    """Run one sealed-bid second-price auction.

    Args:
        bids: ordered iterable of bid values, one per bidder. Bidder
            identity is positional (``winner_idx`` is an index into this
            sequence).
        rng: optional ``random.Random`` used only for tie-breaking among
            tied highest bidders. Defaults to ``random.Random()`` (seeded
            from system entropy) when ``None``.

    Returns:
        ``{winner_idx, price_paid, max_bid, second_bid, tie_break}``.
        ``price_paid`` equals ``second_bid`` (the second-highest bid;
        equals ``max_bid`` when all bidders tie at the same value).
        ``tie_break`` is ``True`` iff more than one bidder tied at the
        top and the winner had to be drawn at random.

    Raises:
        ValueError: if ``bids`` is empty or contains a single bid (a
            second-price auction needs at least two bidders to define a
            second bid). Bids must be finite floats; ``NaN`` is rejected.
    """
    bids_list = list(bids)
    if len(bids_list) < 2:
        raise ValueError(
            f"run_auction requires at least 2 bids; got {len(bids_list)}"
        )
    for i, b in enumerate(bids_list):
        if b != b:  # NaN check (NaN != NaN)
            raise ValueError(f"bid at index {i} is NaN")

    rng = rng or random.Random()
    max_bid = max(bids_list)
    top_idxs = [i for i, b in enumerate(bids_list) if b == max_bid]
    tie_break = len(top_idxs) > 1

    if tie_break:
        winner_idx = rng.choice(top_idxs)
        # When all tied at the top, the second-highest equals max_bid.
        second_bid = max_bid
    else:
        winner_idx = top_idxs[0]
        # Second-highest among the remaining bidders.
        remaining = [b for i, b in enumerate(bids_list) if i != winner_idx]
        second_bid = max(remaining)

    return {
        "winner_idx": winner_idx,
        "price_paid": second_bid,
        "max_bid": max_bid,
        "second_bid": second_bid,
        "tie_break": tie_break,
    }
