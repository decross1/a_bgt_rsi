"""LLM probability forecaster for exp007 (Polymarket paper-forecasting).

DESIGN-ONLY paper forecasting; NO live trading (CLAUDE.md CFTC guardrail).

This module emits a single calibrated probability that a binary market
question resolves YES. It NEVER places an order, signs a transaction,
touches a wallet/private key, spends money, or authenticates to a trading
endpoint. Its sole output is a probability scored offline against the
market price (Brier / Brier Skill Score per research_program_v2.md).

The prompt is neutral: it presents the market question (plus optional
context) and asks for a calibrated YES probability as JSON
``{"prob": <0..1>, "reasoning": <string>}``. Parse failures default to
``prob = 0.5`` with an observable ``"parse_failure:"`` reasoning prefix.

Reuses ``agent_wrapper.wrapper.call_sync`` and the ``_extract_json_object``
/ coercion pattern from
``experiments/exp003_vickrey_rediscovery/bidder.py``.
"""
from __future__ import annotations

import json
import re
from typing import Any

from agent_wrapper.wrapper import call_sync


_REASONING_CHAR_CAP = 400  # truncate model-emitted reasoning to keep logs bounded


_SYSTEM_PROMPT = (
    "You are a careful forecaster estimating the probability that a "
    "real-world binary event resolves YES. You will be given a market "
    "question and possibly some context. Produce a single calibrated "
    "probability between 0 and 1 that the event resolves YES, reflecting "
    "your honest uncertainty. Use the full range; do not anchor on 0.5 "
    "unless you genuinely have no information. You are only forecasting — "
    "you are not trading, buying, or selling anything."
)

_FORMAT_INSTRUCTION = (
    "Respond with a single JSON object on one line and nothing else. "
    'Use exactly this shape: {"prob": <number between 0 and 1>, '
    '"reasoning": <string>}. The prob must be a finite number in [0, 1]. '
    "Keep the reasoning field under 300 characters."
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


def _coerce_prob(raw_prob: Any) -> float | None:
    """Coerce the model-emitted prob to a float clamped to [0, 1].
    Returns None when the value is not numerically usable (non-numeric
    or NaN)."""
    try:
        p = float(raw_prob)
    except (TypeError, ValueError):
        return None
    if p != p:  # NaN
        return None
    if p < 0.0:
        return 0.0
    if p > 1.0:
        return 1.0
    return p


def forecast(
    question: str,
    *,
    context: str = "",
    backend: str | None = None,
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 256,
    seed: int | None = None,
    log_path: str | None = None,
    caller_tag: str = "exp007_forecaster",
) -> dict:
    """Ask the LLM for a calibrated YES probability for a market question.

    DESIGN-ONLY: emits a probability only; never trades.

    Returns ``{"prob": float in [0, 1], "reasoning": str, "raw": str}``.

    On parse failure (no JSON, or a non-numeric/NaN ``prob``) the forecaster
    defaults ``prob = 0.5`` and prefixes ``reasoning`` with ``"parse_failure:"``
    so the failure is observable downstream — never silent. A numeric ``prob``
    outside [0, 1] is clamped, not treated as a failure.
    """
    parts = [f"Market question: {question.strip()}"]
    if context and context.strip():
        parts.append(f"Context: {context.strip()}")
    parts.append(
        "Estimate the probability this resolves YES.\n\n"
        f"{_FORMAT_INSTRUCTION}"
    )
    user_msg = "\n\n".join(parts)

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
            "prob": 0.5,
            "reasoning": f"parse_failure: could not extract JSON; raw={raw[:200]!r}",
            "raw": raw,
        }

    prob = _coerce_prob(obj.get("prob"))
    if prob is None:
        return {
            "prob": 0.5,
            "reasoning": f"parse_failure: prob field invalid ({obj.get('prob')!r}); raw={raw[:200]!r}",
            "raw": raw,
        }

    reasoning = obj.get("reasoning")
    if not isinstance(reasoning, str):
        reasoning = ""
    if len(reasoning) > _REASONING_CHAR_CAP:
        reasoning = reasoning[:_REASONING_CHAR_CAP] + "...[truncated]"

    return {"prob": prob, "reasoning": reasoning, "raw": raw}
