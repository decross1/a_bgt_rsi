"""Exact one-round payoffs and an independent response-scoring contract.

This module is a development-only instrument.  It calculates the payoffs for
one *supplied* joint action.  It does not choose an action, optimize a plan, or
calculate future utility.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from typing import Any

PLAYERS = 4
FORMULA_VERSION = "four-player-public-goods-payoff/v1"
RESPONSE_SCHEMA_VERSION = "payoff-action-response-score/v1"
MAX_RESPONSE_BYTES = 65_536
MAX_INPUT_INTEGER = 10**18 - 1
MAX_NUMERIC_DIGITS = 128
MAX_DECIMAL_EXPONENT = 128
_PROBE_KEYS = {
    "formula_version",
    "evaluated_joint_action",
    "focal_seat",
    "contributor_count",
    "other_contributor_count",
    "focal_action",
    "player_payoffs",
    "focal_payoff",
    "total_payoff",
    "strategy_advice_included",
}
_EXACT_VALUE_KEYS = {"numerator", "denominator", "canonical"}
_CANONICAL_RATIONAL = re.compile(r"-?(?:0|[1-9][0-9]*)(?:/[1-9][0-9]*)?\Z")
_DECIMAL_TEXT = re.compile(
    r"[+-]?(?:(?:0|[1-9][0-9]*)(?:\.[0-9]+)?|\.[0-9]+)"
    r"(?:[eE][+-]?[0-9]+)?\Z"
)

INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "E": {"type": "integer", "minimum": 1, "maximum": MAX_INPUT_INTEGER},
        "m_num": {
            "type": "integer",
            "minimum": 1,
            "maximum": MAX_INPUT_INTEGER,
        },
        "m_den": {
            "type": "integer",
            "minimum": 1,
            "maximum": MAX_INPUT_INTEGER,
        },
        "joint_action": {
            "type": "array",
            "items": {"type": "integer", "enum": [0, 1]},
            "minItems": PLAYERS,
            "maxItems": PLAYERS,
        },
        "focal_seat": {"type": "integer", "minimum": 0, "maximum": 3},
    },
    "required": ["E", "m_num", "m_den", "joint_action", "focal_seat"],
    "additionalProperties": False,
}


class PayoffCalculatorError(ValueError):
    """The calculator input or scoring contract is invalid."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PayoffCalculatorError(message)


def _canonical_rational(value: Fraction) -> str:
    if value.denominator == 1:
        return str(value.numerator)
    return f"{value.numerator}/{value.denominator}"


def _exact_value(value: Fraction) -> dict[str, int | str]:
    return {
        "numerator": value.numerator,
        "denominator": value.denominator,
        "canonical": _canonical_rational(value),
    }


def _strict_integer(value: Any, name: str, *, minimum: int) -> int:
    _require(type(value) is int, f"{name} must be an exact integer")
    _require(value >= minimum, f"{name} must be at least {minimum}")
    _require(value <= MAX_INPUT_INTEGER, f"{name} exceeds the bounded input range")
    return value


def _validated_input(payload: Any) -> tuple[int, Fraction, tuple[int, ...], int]:
    _require(type(payload) is dict, "input must be a JSON object")
    required = {"E", "m_num", "m_den", "joint_action", "focal_seat"}
    _require(set(payload) == required, "input fields must match the strict contract")

    endowment = _strict_integer(payload["E"], "E", minimum=1)
    numerator = _strict_integer(payload["m_num"], "m_num", minimum=1)
    denominator = _strict_integer(payload["m_den"], "m_den", minimum=1)
    _require(
        math.gcd(numerator, denominator) == 1,
        "the multiplier numerator and denominator must be reduced",
    )

    raw_action = payload["joint_action"]
    _require(
        type(raw_action) is list and len(raw_action) == PLAYERS,
        "joint_action must contain exactly four entries",
    )
    _require(
        all(type(action) is int and action in (0, 1) for action in raw_action),
        "joint_action must contain exact binary integers",
    )
    focal_seat = _strict_integer(payload["focal_seat"], "focal_seat", minimum=0)
    _require(focal_seat < PLAYERS, "focal_seat must be between 0 and 3")
    return (
        endowment,
        Fraction(numerator, denominator),
        tuple(raw_action),
        focal_seat,
    )


def calculate(payload: Any) -> dict[str, Any]:
    """Calculate exact one-round payoffs for the supplied joint action."""

    endowment, multiplier, joint_action, focal_seat = _validated_input(payload)
    contributor_count = sum(joint_action)
    focal_action = joint_action[focal_seat]
    shared_return = multiplier * endowment * contributor_count / PLAYERS
    payoffs = tuple(
        Fraction(endowment * (1 - action)) + shared_return for action in joint_action
    )
    total_payoff = sum(payoffs, Fraction())
    return {
        "formula_version": FORMULA_VERSION,
        "evaluated_joint_action": list(joint_action),
        "focal_seat": focal_seat,
        "contributor_count": contributor_count,
        "other_contributor_count": contributor_count - focal_action,
        "focal_action": focal_action,
        "player_payoffs": [_exact_value(value) for value in payoffs],
        "focal_payoff": _exact_value(payoffs[focal_seat]),
        "total_payoff": _exact_value(total_payoff),
        "strategy_advice_included": False,
    }


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PayoffCalculatorError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise PayoffCalculatorError(f"non-finite JSON number: {value}")


def _bounded_json_integer(value: str) -> int:
    digits = value.removeprefix("-")
    _require(len(digits) <= MAX_NUMERIC_DIGITS, "JSON integer is too large")
    return int(value)


def _bounded_json_decimal(value: str) -> Decimal:
    _require(len(value) <= MAX_NUMERIC_DIGITS, "JSON decimal token is too long")
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:  # pragma: no cover - JSON lexer protects it
        raise PayoffCalculatorError("invalid JSON decimal") from error
    digits = parsed.as_tuple().digits
    exponent = parsed.as_tuple().exponent
    _require(len(digits) <= MAX_NUMERIC_DIGITS, "JSON decimal has too many digits")
    _require(
        -MAX_DECIMAL_EXPONENT <= exponent <= MAX_DECIMAL_EXPONENT,
        "JSON decimal exponent is outside the bounded range",
    )
    return parsed


def _load_json_exact(content: str) -> Any:
    _require(
        len(content.encode("utf-8")) <= MAX_RESPONSE_BYTES,
        "response exceeds the bounded JSON size",
    )
    return json.loads(
        content,
        object_pairs_hook=_strict_object,
        parse_int=_bounded_json_integer,
        parse_float=_bounded_json_decimal,
        parse_constant=_reject_constant,
    )


def _diagnostic_fraction(value: Any) -> Fraction | None:
    """Parse exact numeric evidence without ever round-tripping through float."""

    if type(value) is int:
        return Fraction(value)
    if isinstance(value, Decimal):
        return Fraction(value) if value.is_finite() else None
    if isinstance(value, str):
        if len(value) > (2 * MAX_NUMERIC_DIGITS + 1):
            return None
        if _CANONICAL_RATIONAL.fullmatch(value):
            integer_parts = value.removeprefix("-").split("/")
            if any(len(part) > MAX_NUMERIC_DIGITS for part in integer_parts):
                return None
            try:
                parsed = Fraction(value)
            except (ValueError, ZeroDivisionError):
                return None
            return parsed if _canonical_rational(parsed) == value else None
        if _DECIMAL_TEXT.fullmatch(value):
            try:
                parsed_decimal = _bounded_json_decimal(value)
            except InvalidOperation:  # pragma: no cover - regex excludes it
                return None
            except PayoffCalculatorError:
                return None
            return Fraction(parsed_decimal) if parsed_decimal.is_finite() else None
        return None
    if type(value) is dict and set(value) == _EXACT_VALUE_KEYS:
        numerator = value["numerator"]
        denominator = value["denominator"]
        canonical = value["canonical"]
        if (
            type(numerator) is not int
            or type(denominator) is not int
            or denominator <= 0
            or not isinstance(canonical, str)
            or len(str(abs(numerator))) > MAX_NUMERIC_DIGITS
            or len(str(denominator)) > MAX_NUMERIC_DIGITS
            or len(canonical) > (2 * MAX_NUMERIC_DIGITS + 1)
        ):
            return None
        parsed = Fraction(numerator, denominator)
        if (
            parsed.numerator != numerator
            or parsed.denominator != denominator
            or _canonical_rational(parsed) != canonical
        ):
            return None
        return parsed
    return None


def _strict_exact_value(value: Any) -> bool:
    return type(value) is dict and _diagnostic_fraction(value) is not None


def _probe_shape_valid(probe: Any) -> bool:
    return (
        type(probe) is dict
        and set(probe) == _PROBE_KEYS
        and type(probe.get("player_payoffs")) is list
        and len(probe["player_payoffs"]) == PLAYERS
        and type(probe.get("evaluated_joint_action")) is list
        and len(probe["evaluated_joint_action"]) == PLAYERS
    )


def _probe_numeric_values(probe: dict[str, Any]) -> list[Any]:
    return [
        *probe["player_payoffs"],
        probe["focal_payoff"],
        probe["total_payoff"],
    ]


def _binding_valid(probe: dict[str, Any], expected: dict[str, Any]) -> bool:
    action = probe["evaluated_joint_action"]
    scalar_types_valid = (
        isinstance(probe["formula_version"], str)
        and all(type(value) is int and value in (0, 1) for value in action)
        and type(probe["focal_seat"]) is int
        and type(probe["contributor_count"]) is int
        and type(probe["other_contributor_count"]) is int
        and type(probe["focal_action"]) is int
        and probe["strategy_advice_included"] is False
    )
    if not scalar_types_valid:
        return False
    keys = (
        "formula_version",
        "evaluated_joint_action",
        "focal_seat",
        "contributor_count",
        "other_contributor_count",
        "focal_action",
        "strategy_advice_included",
    )
    return all(probe[key] == expected[key] for key in keys)


def _action_state(value: Any, expected_horizon: int) -> tuple[bool, bool]:
    valid = (
        type(value) is list
        and bool(value)
        and all(type(action) is int and action in (0, 1) for action in value)
    )
    return valid, bool(valid and len(value) == expected_horizon)


def score_response(
    content: str | None,
    *,
    expected_input: dict[str, Any],
    expected_horizon: int,
) -> dict[str, Any]:
    """Score probe and action validity independently.

    The probe uses a strict declared representation, while its diagnostic
    arithmetic accepts other exact JSON representations.  A bad probe never
    suppresses an otherwise valid, correctly sized action vector.
    """

    expected = calculate(expected_input)
    _require(
        type(expected_horizon) is int and 4 <= expected_horizon <= 12,
        "expected_horizon must be an exact integer between 4 and 12",
    )

    parsed: Any = None
    json_valid = False
    if isinstance(content, str):
        try:
            parsed = _load_json_exact(content)
            json_valid = True
        except (
            json.JSONDecodeError,
            PayoffCalculatorError,
            RecursionError,
            ValueError,
        ):
            pass

    root_fields_valid = type(parsed) is dict and set(parsed) == {"probe", "actions"}
    probe = parsed.get("probe") if type(parsed) is dict else None
    field_valid = bool(root_fields_valid and _probe_shape_valid(probe))
    action_present = type(parsed) is dict and "actions" in parsed
    actions = parsed.get("actions") if type(parsed) is dict else None
    action_array_valid, action_scoreable = _action_state(actions, expected_horizon)

    numeric_representation_valid = False
    numeric_values_parseable = False
    probe_binding_valid = False
    contributor_counts_correct = False
    exact_arithmetic = False
    if field_valid:
        observed_numeric = _probe_numeric_values(probe)
        numeric_representation_valid = all(
            _strict_exact_value(value) for value in observed_numeric
        )
        observed_fractions = [_diagnostic_fraction(value) for value in observed_numeric]
        numeric_values_parseable = all(
            value is not None for value in observed_fractions
        )
        probe_binding_valid = _binding_valid(probe, expected)
        contributor_counts_correct = (
            type(probe["contributor_count"]) is int
            and type(probe["other_contributor_count"]) is int
            and probe["contributor_count"] == expected["contributor_count"]
            and probe["other_contributor_count"] == expected["other_contributor_count"]
        )
        if numeric_values_parseable:
            expected_fractions = [
                _diagnostic_fraction(value) for value in _probe_numeric_values(expected)
            ]
            exact_arithmetic = observed_fractions == expected_fractions

    strict_contract_valid = all(
        (
            json_valid,
            field_valid,
            numeric_representation_valid,
            probe_binding_valid,
            contributor_counts_correct,
            exact_arithmetic,
            action_scoreable,
        )
    )
    assessment_status = {
        "json": "passed" if json_valid else "failed",
        "fields": (
            "passed" if field_valid else "failed" if json_valid else "unassessed"
        ),
        "numeric_representation": (
            "passed"
            if numeric_representation_valid
            else "failed"
            if field_valid
            else "unassessed"
        ),
        "numeric_values": (
            "passed"
            if numeric_values_parseable
            else "failed"
            if field_valid
            else "unassessed"
        ),
        "probe_binding": (
            "passed"
            if probe_binding_valid
            else "failed"
            if field_valid
            else "unassessed"
        ),
        "contributor_counts": (
            "passed"
            if contributor_counts_correct
            else "failed"
            if field_valid
            else "unassessed"
        ),
        "arithmetic": (
            "passed"
            if exact_arithmetic
            else "failed"
            if numeric_values_parseable
            else "unassessed"
        ),
        "action_array": (
            "passed"
            if action_array_valid
            else "failed"
            if json_valid and action_present
            else "unassessed"
        ),
        "action_scoreability": (
            "passed"
            if action_scoreable
            else "failed"
            if action_array_valid
            else "unassessed"
        ),
    }
    failure_codes: list[str] = []
    if not json_valid:
        failure_codes.append("json_invalid")
    else:
        if not field_valid:
            failure_codes.append("response_fields_invalid")
        if field_valid:
            if not numeric_representation_valid:
                failure_codes.append("numeric_representation_invalid")
            if not numeric_values_parseable:
                failure_codes.append("numeric_values_unparseable")
            if not probe_binding_valid:
                failure_codes.append("probe_binding_mismatch")
            if not contributor_counts_correct:
                failure_codes.append("contributor_counts_wrong")
            if numeric_values_parseable and not exact_arithmetic:
                failure_codes.append("arithmetic_wrong")
        if action_present:
            if not action_array_valid:
                failure_codes.append("action_array_invalid")
            elif not action_scoreable:
                failure_codes.append("action_horizon_mismatch")

    action_hash = None
    if action_scoreable:
        action_hash = hashlib.sha256(
            json.dumps(actions, separators=(",", ":")).encode()
        ).hexdigest()
    return {
        "schema_version": RESPONSE_SCHEMA_VERSION,
        "expected_horizon": expected_horizon,
        "json_valid": json_valid,
        "field_valid": field_valid,
        "numeric_representation_valid": numeric_representation_valid,
        "numeric_values_parseable": numeric_values_parseable,
        "probe_binding_valid": probe_binding_valid,
        "contributor_counts_correct": contributor_counts_correct,
        "exact_arithmetic": exact_arithmetic,
        "action_array_valid": action_array_valid,
        "action_scoreable": action_scoreable,
        "strict_contract_valid": strict_contract_valid,
        "assessment_status": assessment_status,
        "actions": actions if action_scoreable else None,
        "action_sha256": action_hash,
        "failure_codes": failure_codes,
    }
