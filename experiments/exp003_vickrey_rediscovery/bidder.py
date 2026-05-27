"""LLM bidder for exp003 sealed-bid second-price auction.

The prompt deliberately does NOT mention "truthful bidding", "dominant
strategy", "report your value", or any auction-theory result. It states
the mechanics of the Vickrey auction (sealed-bid, four bidders, winner
pays second-highest) and the bidder's private valuation, then asks for
a JSON object ``{"bid": <float>, "reasoning": <string>}``. This is the
rediscovery probe: does the model arrive at truthful bidding without
being told to?

Reuses ``agent_wrapper.wrapper.call_sync`` per the pattern in
``experiments/exp001_repeated_pd/llm_agent.py``.
"""
from __future__ import annotations

import json
import re
from typing import Any

from agent_wrapper.wrapper import call_sync


_REASONING_CHAR_CAP = 400  # truncate model-emitted reasoning to keep logs bounded


_SYSTEM_PROMPT = (
    "You are one of four bidders in a single-round sealed-bid auction. "
    "Each bidder writes down one bid privately; no bidder sees any other "
    "bid before submitting. After all bids are collected the auctioneer "
    "announces the winner and the price. The rules are:\n"
    "  - The bidder who submitted the HIGHEST bid wins the item.\n"
    "  - The winner pays a price equal to the SECOND-HIGHEST bid (not "
    "their own bid).\n"
    "  - The other three bidders pay nothing and receive nothing.\n"
    "  - Your payoff is (your private valuation - price paid) if you "
    "win, otherwise 0.\n"
    "Ties at the highest bid are broken uniformly at random among the "
    "tied bidders.\n"
    "You will be told your own private valuation for the item — a number "
    "between 0 and 100. The three other bidders each independently drew "
    "their own private valuation from the same uniform distribution on "
    "[0, 100]; you do not know their valuations. Decide what bid to "
    "submit."
)

_FORMAT_INSTRUCTION = (
    "Respond with a single JSON object on one line and nothing else. "
    'Use exactly this shape: {"bid": <number>, "reasoning": <string>}. '
    "The bid must be a finite non-negative number. Keep the reasoning "
    "field under 300 characters."
)


_JSON_RE = re.compile(r"\{.*?\}", re.DOTALL)


def _extract_json_object(text: str) -> dict[str, Any] | None:
    """Lenient JSON-object extraction. Returns None on failure."""
    if not text:
        return None
    # Direct parse first
    try:
        obj = json.loads(text.strip())
        if isinstance(obj, dict):
            return obj
    except (json.JSONDecodeError, ValueError):
        pass
    # Then look for the first {...} substring
    m = _JSON_RE.search(text)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
        if isinstance(obj, dict):
            return obj
    except (json.JSONDecodeError, ValueError):
        return None
    return None


def _coerce_bid(raw_bid: Any) -> float | None:
    """Coerce the model-emitted bid to a non-negative float. Returns
    None when the value is not numerically usable."""
    try:
        b = float(raw_bid)
    except (TypeError, ValueError):
        return None
    if b != b:  # NaN
        return None
    if b < 0:
        return None
    return b


def compute_bid(
    private_valuation: float,
    *,
    backend: str | None = None,
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 256,
    seed: int | None = None,
    log_path: str | None = None,
    caller_tag: str = "exp003_bidder",
) -> dict:
    """Ask the LLM to submit a sealed bid given a private valuation.

    Returns ``{"bid": float, "reasoning": str, "raw": str}``.

    On parse failure the bidder logs the raw text in ``reasoning`` and
    defaults ``bid = private_valuation`` so the run can continue. Parse
    failures are observable downstream (``reasoning`` starts with
    ``"parse_failure"``) — they are not silent.
    """
    if private_valuation < 0 or private_valuation > 100:
        raise ValueError(
            f"private_valuation must be in [0, 100]; got {private_valuation}"
        )

    user_msg = (
        f"Your private valuation for the item is {private_valuation:.2f}. "
        "Submit your bid now.\n\n"
        f"{_FORMAT_INSTRUCTION}"
    )

    record = call_sync(
        [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
        seed=seed,
        caller_tag=caller_tag,
        log_path=log_path,
        model=model,
        backend=backend,
    )
    raw = (record.get("completion") or "").strip()

    obj = _extract_json_object(raw)
    if obj is None:
        return {
            "bid": float(private_valuation),
            "reasoning": f"parse_failure: could not extract JSON; raw={raw[:200]!r}",
            "raw": raw,
        }

    bid = _coerce_bid(obj.get("bid"))
    if bid is None:
        return {
            "bid": float(private_valuation),
            "reasoning": f"parse_failure: bid field invalid ({obj.get('bid')!r}); raw={raw[:200]!r}",
            "raw": raw,
        }

    reasoning = obj.get("reasoning")
    if not isinstance(reasoning, str):
        reasoning = ""
    if len(reasoning) > _REASONING_CHAR_CAP:
        reasoning = reasoning[:_REASONING_CHAR_CAP] + "...[truncated]"

    return {"bid": bid, "reasoning": reasoning, "raw": raw}
