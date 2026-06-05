"""LLM bundle-bidder for exp004 combinatorial auction (rediscovery probe).

exp004 is the HARDEST SYNTHETIC rung of the sandbox spectrum: a combinatorial
auction with two items (A and B) and three biddable bundles (A alone, B alone,
or the A+B bundle), with a KNOWN optimal solution (welfare-maximizing
allocation under reported bids). It is the on-ramp to — but NOT yet — the
semi-synthetic mechanism-DESIGN tier; here the mechanism is fixed and known and
we only probe the bidder.

The prompt deliberately does NOT mention "truthful", "dominant strategy",
"VCG", "report your value", or strategyproofness. It states only the mechanics
(sealed-bid, several bidders, you may bid on item A alone, item B alone, or the
A+B bundle; exactly one feasible allocation is chosen and you pay per the
rules), then asks for a JSON object
``{"bids": {"A": <num>, "B": <num>, "AB": <num>}, "reasoning": <str>}``. This is
the rediscovery probe: does the model arrive at truthful bundle bidding without
being told to?

Mirrors the structure of ``experiments/exp003_vickrey_rediscovery/bidder.py``
and reuses ``agent_wrapper.wrapper.call_sync``.
"""
from __future__ import annotations

import json
import re
from typing import Any

from agent_wrapper.wrapper import call_sync


_REASONING_CHAR_CAP = 400  # truncate model-emitted reasoning to keep logs bounded

# Frozen exp004 bundle keys (see bundles.BUNDLES). The bidder speaks "A"/"B"/
# "AB" to the model and maps to these sorted tuples on the way back.
_BUNDLE_TUPLES = ((0,), (1,), (0, 1))
_LABEL_TO_TUPLE = {"A": (0,), "B": (1,), "AB": (0, 1)}
_TUPLE_TO_LABEL = {(0,): "A", (1,): "B", (0, 1): "AB"}


_SYSTEM_PROMPT = (
    "You are one of several bidders in a single-round sealed-bid auction for "
    "two items, called item A and item B. Each bidder writes down their bids "
    "privately; no bidder sees any other bid before submitting. You may place "
    "a bid on three things:\n"
    "  - item A on its own,\n"
    "  - item B on its own,\n"
    "  - the bundle of both items together (A and B).\n"
    "After all bids are collected the auctioneer chooses exactly one feasible "
    "allocation: each item is awarded to at most one bidder, and a bidder who "
    "wins the A+B bundle takes both items (so no one else can win A or B). "
    "Some items may go unsold. You pay according to the auction's rules only "
    "for what you are actually awarded; if you win nothing you pay nothing.\n"
    "You will be told your own private values for A alone, B alone, and the "
    "A+B bundle. The other bidders each independently drew their own private "
    "values; you do not know them. Decide what to bid on each of the three."
)

_FORMAT_INSTRUCTION = (
    "Respond with a single JSON object on one line and nothing else. "
    'Use exactly this shape: {"bids": {"A": <number>, "B": <number>, '
    '"AB": <number>}, "reasoning": <string>}. Each bid must be a finite '
    "non-negative number. Keep the reasoning field under 300 characters."
)


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _truthful_default(valuation: dict) -> dict:
    """The truthful fallback bid: bid your own value on every bundle."""
    return {t: float(valuation[t]) for t in _BUNDLE_TUPLES}


def _extract_json_object(text: str) -> dict[str, Any] | None:
    """Lenient JSON-object extraction. Returns None on failure."""
    if not text:
        return None
    try:
        obj = json.loads(text.strip())
        if isinstance(obj, dict):
            return obj
    except (json.JSONDecodeError, ValueError):
        pass
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
    """Coerce a model-emitted bid to a non-negative float. Returns None when
    the value is not numerically usable."""
    try:
        b = float(raw_bid)
    except (TypeError, ValueError):
        return None
    if b != b:  # NaN
        return None
    if b < 0:
        return None
    return b


def compute_bundle_bids(
    valuation: dict,
    *,
    backend: str | None = None,
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 384,
    seed: int | None = None,
    log_path: str | None = None,
    caller_tag: str = "exp004_bidder",
) -> dict:
    """Ask the LLM to submit a sealed bundle bid given a private valuation.

    ``valuation`` maps each of the three frozen bundle tuples ((0,), (1,),
    (0, 1)) to a non-negative float. Returns
    ``{"bids": dict, "reasoning": str, "raw": str}`` where ``bids`` maps the
    same three tuples to floats.

    On any parse failure the bidder defaults ``bids := valuation`` (the
    truthful default) and prefixes ``reasoning`` with ``"parse_failure:"``.
    Parse failures are observable downstream — never silent.
    """
    for t in _BUNDLE_TUPLES:
        if t not in valuation:
            raise ValueError(f"valuation missing bundle key {t!r}")
        if valuation[t] < 0:
            raise ValueError(f"valuation[{t!r}] must be >= 0; got {valuation[t]}")

    user_msg = (
        "Your private values are: "
        f"A alone = {float(valuation[(0,)]):.2f}, "
        f"B alone = {float(valuation[(1,)]):.2f}, "
        f"the A+B bundle = {float(valuation[(0, 1)]):.2f}. "
        "Submit your bids now.\n\n"
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
            "bids": _truthful_default(valuation),
            "reasoning": f"parse_failure: could not extract JSON; raw={raw[:200]!r}",
            "raw": raw,
        }

    raw_bids = obj.get("bids")
    if not isinstance(raw_bids, dict):
        return {
            "bids": _truthful_default(valuation),
            "reasoning": f"parse_failure: 'bids' field missing or not an object ({raw_bids!r}); raw={raw[:200]!r}",
            "raw": raw,
        }

    bids: dict = {}
    for label, tup in _LABEL_TO_TUPLE.items():
        coerced = _coerce_bid(raw_bids.get(label))
        if coerced is None:
            return {
                "bids": _truthful_default(valuation),
                "reasoning": f"parse_failure: bid for {label!r} invalid ({raw_bids.get(label)!r}); raw={raw[:200]!r}",
                "raw": raw,
            }
        bids[tup] = coerced

    reasoning = obj.get("reasoning")
    if not isinstance(reasoning, str):
        reasoning = ""
    if len(reasoning) > _REASONING_CHAR_CAP:
        reasoning = reasoning[:_REASONING_CHAR_CAP] + "...[truncated]"

    return {"bids": bids, "reasoning": reasoning, "raw": raw}
