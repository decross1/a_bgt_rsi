"""Mechanism-designer probe for exp004 — the genuine SEMI-SYNTHETIC seed.

EXPLORATORY. exp004 itself is the HARDEST SYNTHETIC rung: combinatorial
auctions over two items with KNOWN optimal solutions (the VCG mechanism in
``mechanisms/vcg.py`` clears them exactly). This module is the *on-ramp seed*
to the semi-synthetic mechanism-DESIGN tier — it is NOT a validated tier and
should not be read as one. We are not yet doing semi-synthetic mechanism
design; we are probing whether the question is even tractable.

The probe: can an LLM act as a mechanism designer? We describe the submitted
bids in neutral language and ask the model to choose who gets which items and
what each bidder pays, with the only objective being "efficient and fair". We
deliberately do NOT mention VCG, the Vickrey-Clarke-Groves payment rule,
second-price, truthfulness, or any auction-theory result. Then we score the
proposal against the known optimum (allocative efficiency), check feasibility,
and check whether its allocation happens to match the VCG allocation.

Parse failures are observable, never coerced: a malformed completion yields
``is_feasible = False`` with the raw text retained — we do not silently fall
back to a feasible allocation.

Items are the ints 0 and 1; the three non-empty bundles are (0,), (1,),
(0, 1). A bid is a dict mapping each of those tuples to a float >= 0.

Reuses ``agent_wrapper.wrapper.call_sync`` per the exp003 bidder pattern.
"""
from __future__ import annotations

import json
import re
from typing import Any

from agent_wrapper.wrapper import call_sync

from experiments.exp004_combinatorial_auction import bundles
from experiments.exp004_combinatorial_auction import efficiency
from experiments.exp004_combinatorial_auction.mechanisms import vcg


_REASONING_CHAR_CAP = 600  # truncate model reasoning to keep logs bounded

# Human-readable label per bundle tuple, used only to render the prompt.
_BUNDLE_LABEL = {
    (0,): "item A alone",
    (1,): "item B alone",
    (0, 1): "both items A and B together",
}

_SYSTEM_PROMPT = (
    "You are arranging a sale of two indivisible items, item A and item B, "
    "among several buyers. Each buyer has told you, in money, how much they "
    "would value receiving item A alone, item B alone, and both items "
    "together. You must decide an outcome:\n"
    "  - which buyer (if any) receives each item, and\n"
    "  - how much money each buyer pays.\n"
    "Each item can go to at most one buyer; a buyer may receive one item, "
    "both items, or nothing. Some buyers may receive nothing and pay "
    "nothing. Choose the outcome you judge to be efficient and fair given "
    "the values the buyers reported."
)

_FORMAT_INSTRUCTION = (
    "Respond with a single JSON object and nothing else, using exactly this "
    "shape:\n"
    '{"allocation": {"<buyer_index>": <bundle>}, '
    '"payments": {"<buyer_index>": <number>}, "reasoning": <string>}\n'
    "Each <bundle> is one of the JSON arrays [0], [1], or [0, 1], naming the "
    "item(s) that buyer receives (0 = item A, 1 = item B). Only list buyers "
    "who receive something in \"allocation\". List every buyer's payment in "
    "\"payments\" (use 0 for buyers who pay nothing). Buyer indices are the "
    "integers shown below, written as JSON strings. Keep \"reasoning\" under "
    "500 characters."
)

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _describe_bids(bid_profile: list[dict]) -> str:
    """Render the bid profile as neutral prose (no theory vocabulary)."""
    lines = []
    for i, bid in enumerate(bid_profile):
        parts = [
            f"{_BUNDLE_LABEL[b]}: {float(bid[b]):.2f}"
            for b in bundles.BUNDLES
        ]
        lines.append(f"Buyer {i} values — " + "; ".join(parts) + ".")
    return "\n".join(lines)


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


def _coerce_bundle(raw: Any) -> tuple | None:
    """Coerce a model-emitted bundle (list/tuple of item ints) to one of the
    three canonical bundle tuples. Returns None when it is not a valid
    non-empty bundle."""
    if not isinstance(raw, (list, tuple)):
        return None
    try:
        items = tuple(sorted(int(x) for x in raw))
    except (TypeError, ValueError):
        return None
    if items in (tuple(b) for b in bundles.BUNDLES):
        return items
    return None


def _parse_allocation(raw_alloc: Any) -> dict | None:
    """Parse the model's allocation dict into {bidder_idx: bundle_tuple}.
    Returns None if the structure is unusable (observable parse failure)."""
    if not isinstance(raw_alloc, dict):
        return None
    alloc: dict[int, tuple] = {}
    for k, v in raw_alloc.items():
        try:
            idx = int(k)
        except (TypeError, ValueError):
            return None
        bundle = _coerce_bundle(v)
        if bundle is None:
            return None
        alloc[idx] = bundle
    return alloc


def _parse_payments(raw_pay: Any) -> dict:
    """Parse the model's payments dict into {bidder_idx: float}. Unusable
    entries are dropped (payments are not scored, only reported)."""
    out: dict[int, float] = {}
    if not isinstance(raw_pay, dict):
        return out
    for k, v in raw_pay.items():
        try:
            out[int(k)] = float(v)
        except (TypeError, ValueError):
            continue
    return out


def propose_allocation(
    bid_profile: list[dict],
    *,
    backend: str | None = None,
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 512,
    seed: int | None = None,
    log_path: str | None = None,
    caller_tag: str = "exp004_mechanism_designer",
) -> dict:
    """Ask the LLM to act as a mechanism designer for the bid profile.

    The prompt is neutral: it asks for an "efficient and fair" outcome and
    never names VCG or any auction-theory result.

    Returns ``{"allocation": dict, "payments": dict, "raw": str,
    "reasoning": str}``. ``allocation`` maps bidder_idx -> bundle tuple; an
    empty dict means "the model proposed selling nothing" OR a parse failure
    — the two are distinguished by ``reasoning`` (parse failures begin with
    ``"parse_failure"``). Parse failures are observable; they are not coerced
    into a feasible allocation here.
    """
    if not bid_profile:
        raise ValueError("bid_profile must be non-empty")

    user_msg = (
        f"There are {len(bid_profile)} buyers. Their reported values:\n"
        f"{_describe_bids(bid_profile)}\n\n"
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
            "allocation": {},
            "payments": {},
            "raw": raw,
            "reasoning": f"parse_failure: could not extract JSON; raw={raw[:200]!r}",
        }

    alloc = _parse_allocation(obj.get("allocation"))
    if alloc is None:
        return {
            "allocation": {},
            "payments": {},
            "raw": raw,
            "reasoning": f"parse_failure: allocation field invalid ({obj.get('allocation')!r}); raw={raw[:200]!r}",
        }

    payments = _parse_payments(obj.get("payments"))

    reasoning = obj.get("reasoning")
    if not isinstance(reasoning, str):
        reasoning = ""
    if len(reasoning) > _REASONING_CHAR_CAP:
        reasoning = reasoning[:_REASONING_CHAR_CAP] + "...[truncated]"

    return {
        "allocation": alloc,
        "payments": payments,
        "raw": raw,
        "reasoning": reasoning,
    }


def _is_feasible(allocation: dict, n_bidders: int) -> bool:
    """A proposed allocation is feasible iff: every bidder index is in range,
    every bundle is a canonical bundle, and the allocated bundles are pairwise
    item-disjoint across distinct winners (each item sold at most once)."""
    if not isinstance(allocation, dict):
        return False
    canonical = {tuple(b) for b in bundles.BUNDLES}
    used_items: set[int] = set()
    for idx, bundle in allocation.items():
        if not isinstance(idx, int) or idx < 0 or idx >= n_bidders:
            return False
        b = tuple(bundle)
        if b not in canonical:
            return False
        for item in b:
            if item in used_items:
                return False
            used_items.add(item)
    return True


def score_proposal(proposal: dict, valuations: list[dict]) -> dict:
    """Score an LLM mechanism-design proposal against the KNOWN optimum.

    Returns ``{"efficiency": float, "is_feasible": bool,
    "matches_vcg_alloc": bool}``.

    - ``is_feasible``: the proposed allocation sells each item at most once,
      uses only valid bundles, and only valid bidder indices. A parse failure
      (empty allocation from a malformed completion) is reported as
      ``is_feasible = False`` — NOT coerced into a pass. NB an LLM that
      genuinely proposes selling nothing also yields an empty allocation;
      that empty allocation IS feasible and scores efficiency 0.0 unless the
      true optimum is also 0.0. The probe distinguishes the two cases via the
      proposal's ``reasoning`` field, not here.
    - ``efficiency``: allocative_efficiency of the proposed allocation vs the
      optimal allocation under the true valuations. When the proposal is not
      feasible we still report the realized/optimal ratio of what it asked
      for (which may be 0.0); efficiency stays observable.
    - ``matches_vcg_alloc``: whether the proposed allocation equals the
      allocation the VCG mechanism would choose on these (truthful) bids.
    """
    allocation = proposal.get("allocation", {})
    raw_reasoning = proposal.get("reasoning", "")
    parse_failed = isinstance(raw_reasoning, str) and raw_reasoning.startswith(
        "parse_failure"
    )

    feasible = (not parse_failed) and _is_feasible(allocation, len(valuations))

    # Efficiency: ratio of realized welfare to the known optimum. A parse
    # failure reports efficiency 0.0 (it allocated nothing) but the value is
    # honest — realized welfare of an empty allocation is 0.
    efficiency_val = efficiency.allocative_efficiency(allocation, valuations)

    # VCG allocation on the truthful bids = the valuations themselves.
    vcg_result = vcg.clear(valuations)
    vcg_alloc = vcg_result["allocation"]
    matches_vcg = _normalize_alloc(allocation) == _normalize_alloc(vcg_alloc)

    return {
        "efficiency": efficiency_val,
        "is_feasible": feasible,
        "matches_vcg_alloc": matches_vcg,
    }


def _normalize_alloc(alloc: dict) -> dict:
    """Normalize an allocation for equality comparison: bidder_idx -> sorted
    bundle tuple, dropping any empty bundles so {0: ()} == {}."""
    out = {}
    for idx, bundle in alloc.items():
        b = tuple(sorted(bundle))
        if b:
            out[int(idx)] = b
    return out
