# DESIGN-ONLY paper forecasting; NO live trading (CLAUDE.md CFTC guardrail).
"""Read-only Polymarket market-data adapter for exp007.

Fetches public, unauthenticated market metadata from the Polymarket
Gamma API and normalizes it into a flat dict the forecasting harness can
score offline. The research metric is forecasting skill (Brier / Brier
Skill Score vs the market-implied probability), per
``docs/sources/research_program_v2.md``.

READ-ONLY by construction: this module issues a single ``requests.get``
against a public endpoint. There is no POST, no order/trade placement,
no wallet, no private key, and no authentication anywhere. Polymarket
remains design-only until CFTC compliance work is done (CLAUDE.md
out-of-scope guardrail).

Normalized market shape::

    {
        "market_id":    str,
        "question":     str,
        "implied_prob": float | None,  # YES outcome price/midpoint, [0, 1]
        "resolved":     bool,
        "outcome":      1.0 | 0.0 | None,
        "category":     str | None,
        "end_date":     str | None,
    }
"""
from __future__ import annotations

import json
from typing import Any

import requests

GAMMA_MARKETS_URL = "https://gamma-api.polymarket.com/markets"


class MarketDataError(Exception):
    """Raised on any failure to fetch or read market data.

    The caller decides how to react (retry, fall back to a fixture, skip).
    Import of this module never performs network I/O, so it cannot crash
    at import time.
    """


def _coerce_listish(value: Any) -> list[Any]:
    """Return a list from a value that may be a JSON-encoded string.

    Gamma encodes ``outcomes`` / ``outcomePrices`` as JSON strings, e.g.
    ``'["Yes", "No"]'`` and ``'["0.62", "0.38"]'``. Already-decoded lists
    pass through. Anything unparseable yields an empty list.
    """
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _yes_index(outcomes: list[Any]) -> int:
    """Index of the YES leg, defaulting to 0 (the conventional YES slot)."""
    for i, name in enumerate(outcomes):
        if isinstance(name, str) and name.strip().lower() == "yes":
            return i
    return 0


def _implied_prob(market: dict) -> float | None:
    """Extract the YES-outcome implied probability in [0, 1], or None.

    Prefers the ``outcomePrices`` array (price of the YES leg). Falls back
    to a ``best_bid``/``best_ask`` midpoint when prices are absent. Returns
    ``None`` when no usable signal exists. Out-of-range values are clamped
    to [0, 1] rather than dropped.
    """
    outcomes = _coerce_listish(market.get("outcomes"))
    prices = _coerce_listish(market.get("outcomePrices"))
    idx = _yes_index(outcomes)
    if idx < len(prices):
        try:
            return _clamp01(float(prices[idx]))
        except (TypeError, ValueError):
            pass
    bid = market.get("bestBid")
    ask = market.get("bestAsk")
    try:
        if bid is not None and ask is not None:
            return _clamp01((float(bid) + float(ask)) / 2.0)
    except (TypeError, ValueError):
        pass
    return None


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def _resolved_outcome(market: dict) -> tuple[bool, float | None]:
    """Return ``(resolved, outcome)`` for a market.

    ``resolved`` is true when the market is closed AND a winning outcome is
    identifiable. ``outcome`` is ``1.0`` if the YES leg won, ``0.0`` if it
    lost, and ``None`` when closed-but-undetermined or still open.
    """
    closed = bool(market.get("closed", False))
    if not closed:
        return False, None
    outcomes = _coerce_listish(market.get("outcomes"))
    yes_idx = _yes_index(outcomes)

    # Gamma may report resolution via an index, a price vector, or a label.
    raw_idx = market.get("resolvedOutcomeIndex")
    if raw_idx is not None:
        try:
            return True, 1.0 if int(raw_idx) == yes_idx else 0.0
        except (TypeError, ValueError):
            pass

    prices = _coerce_listish(market.get("outcomePrices"))
    if yes_idx < len(prices):
        try:
            p = float(prices[yes_idx])
        except (TypeError, ValueError):
            p = None
        if p is not None:
            if p >= 0.99:
                return True, 1.0
            if p <= 0.01:
                return True, 0.0

    return False, None


def _normalize(market: dict) -> dict:
    """Map one raw Gamma market dict onto the normalized shape.

    Tolerates missing fields: every accessor uses ``.get`` and bad values
    degrade to ``None`` / ``False`` rather than raising.
    """
    resolved, outcome = _resolved_outcome(market)
    market_id = market.get("id")
    return {
        "market_id": str(market_id) if market_id is not None else None,
        "question": market.get("question"),
        "implied_prob": _implied_prob(market),
        "resolved": resolved,
        "outcome": outcome,
        "category": market.get("category"),
        "end_date": market.get("endDate"),
    }


def fetch_markets(
    *, limit: int = 20, closed: bool = True, timeout_s: float = 15
) -> list[dict]:
    """Fetch and normalize public Polymarket markets (READ-ONLY).

    Issues a single unauthenticated ``GET`` against the Gamma API. No
    auth, no trading, no wallet.

    Args:
        limit: max markets to request (Gamma ``limit`` query param).
        closed: filter to closed/resolved markets when ``True`` (these are
            the ones with realized outcomes for offline Brier scoring).
        timeout_s: per-request timeout in seconds.

    Returns:
        A list of normalized market dicts (see module docstring).

    Raises:
        MarketDataError: on any network error, non-200 status, or
            non-JSON / non-list response body. Never crashes the process.
    """
    params = {"limit": limit, "closed": str(bool(closed)).lower()}
    try:
        resp = requests.get(GAMMA_MARKETS_URL, params=params, timeout=timeout_s)
        resp.raise_for_status()
        payload = resp.json()
    except requests.RequestException as exc:
        raise MarketDataError(f"Gamma fetch failed: {exc}") from exc
    except ValueError as exc:  # JSON decode error
        raise MarketDataError(f"Gamma response was not JSON: {exc}") from exc

    if not isinstance(payload, list):
        raise MarketDataError(
            f"Gamma response was not a list of markets: got {type(payload).__name__}"
        )
    return [_normalize(m) for m in payload if isinstance(m, dict)]


def load_fixture(path: str) -> list[dict]:
    """Load and normalize a committed Gamma-shaped fixture file (offline).

    Lets tests and the harness exercise the full normalization path with
    no network access. The fixture must be a JSON list of raw market dicts
    (the same shape Gamma returns).

    Raises:
        MarketDataError: if the file is missing, unreadable, not JSON, or
            not a JSON list.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, ValueError) as exc:
        raise MarketDataError(f"fixture load failed for {path!r}: {exc}") from exc
    if not isinstance(payload, list):
        raise MarketDataError(
            f"fixture {path!r} was not a JSON list: got {type(payload).__name__}"
        )
    return [_normalize(m) for m in payload if isinstance(m, dict)]
