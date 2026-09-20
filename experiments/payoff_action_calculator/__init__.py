"""Exact, strategy-free payoff instrument for public-goods experiments."""

from .calculator import (
    FORMULA_VERSION,
    INPUT_SCHEMA,
    RESPONSE_SCHEMA_VERSION,
    PayoffCalculatorError,
    calculate,
    score_response,
)

__all__ = [
    "FORMULA_VERSION",
    "INPUT_SCHEMA",
    "RESPONSE_SCHEMA_VERSION",
    "PayoffCalculatorError",
    "calculate",
    "score_response",
]
