"""Mechanism-AWARE LLM bundle-bidder for exp005.

exp005 sharpens the exp004 rediscovery probe with ONE change: the bidder is
told, in plain mechanics, how it PAYS under the specific mechanism it is
bidding into. exp004 stated only the allocation rule and asked for bids; the
model bid into a payment rule it had to infer. Here each mechanism's payment
rule is spelled out — but still with NO auction-theory priming ("truthful",
"dominant strategy", "shade", "strategyproof", "VCG" never appear). The
question: does naming the payment mechanics alone elicit the textbook
behaviours — bid-SHADING under first-price, truthfulness under VCG — without
ever naming the answer?

Mirrors ``experiments/exp004_combinatorial_auction/bidder.py`` and reuses
``agent_wrapper.wrapper.call_sync``. The ONLY structural difference is that the
system prompt is mechanism-specific.
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


# Shared allocation framing (identical across mechanisms; the payment clause is
# what differs). Deliberately free of any auction-theory term.
_FRAMING = (
    "You are one of several bidders in a sealed-bid auction for two items, "
    "called item A and item B. Each bidder writes down their bids privately; "
    "no bidder sees any other bid before submitting. You may place a bid on "
    "three things:\n"
    "  - item A on its own,\n"
    "  - item B on its own,\n"
    "  - the bundle of both items together (A and B).\n"
    "After all bids are collected the auctioneer awards each item to at most "
    "one bidder; a bidder who wins the A+B bundle takes both items (so no one "
    "else can win A or B). Some items may go unsold. If you win nothing you "
    "pay nothing.\n"
)

# Per-mechanism PAYMENT clause, stated in plain mechanics. No theory words.
_PAYMENT_CLAUSES = {
    "vcg": (
        "How you pay: if you win, you pay the amount your winning reduces the "
        "total value available to the OTHER bidders (the harm your win imposes "
        "on them) — NOT your own bid."
    ),
    "first_price": (
        "How you pay: if you win, you pay exactly the amount YOU bid for what "
        "you win."
    ),
    "sequential_second_price": (
        "How you pay: the two items are sold one at a time; for each item the "
        "highest bidder wins and pays the SECOND-highest bid for that item."
    ),
}

_VALUE_CLAUSE = (
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


def system_prompt_for(mechanism_name: str) -> str:
    """Build the mechanism-specific system prompt (payment rule, no theory)."""
    if mechanism_name not in _PAYMENT_CLAUSES:
        raise ValueError(
            f"unknown mechanism_name {mechanism_name!r}; expected one of "
            f"{sorted(_PAYMENT_CLAUSES)}"
        )
    return (
        _FRAMING
        + _PAYMENT_CLAUSES[mechanism_name]
        + "\n"
        + _VALUE_CLAUSE
    )


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


def compute_aware_bundle_bids(
    valuation: dict,
    mechanism_name: str,
    *,
    backend: str | None = None,
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 384,
    seed: int | None = None,
    log_path: str | None = None,
    caller_tag: str = "exp005_bidder",
) -> dict:
    """Ask the LLM to bid given a private valuation AND this mechanism's
    payment rule (stated in plain mechanics, no auction-theory priming).

    ``valuation`` maps each of the three frozen bundle tuples ((0,), (1,),
    (0, 1)) to a non-negative float. ``mechanism_name`` is one of "vcg",
    "first_price", "sequential_second_price". Returns
    ``{"bids": dict, "reasoning": str, "raw": str}`` where ``bids`` maps the
    same three tuples to floats.

    On any parse failure the bidder defaults ``bids := valuation`` and prefixes
    ``reasoning`` with ``"parse_failure:"``. Parse failures are observable
    downstream — never silent.
    """
    for t in _BUNDLE_TUPLES:
        if t not in valuation:
            raise ValueError(f"valuation missing bundle key {t!r}")
        if valuation[t] < 0:
            raise ValueError(f"valuation[{t!r}] must be >= 0; got {valuation[t]}")

    system_prompt = system_prompt_for(mechanism_name)

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
            {"role": "system", "content": system_prompt},
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
