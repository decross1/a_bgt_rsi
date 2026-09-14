"""Strict protocol taxonomy for weekly-upgrade structured outputs."""

from __future__ import annotations

import pytest

from bench.weekly_upgrade_eval.structured_output import (
    DUPLICATE_JSON_KEY,
    FIELD_SCHEMA,
    MALFORMED_JSON,
    MARKDOWN_ENVELOPE,
    NON_FINITE_JSON,
    REASONING_CHANNEL_LEAKAGE,
    TOP_LEVEL_SCHEMA,
    parse_strict_json_object,
)


def test_accepts_exact_object_without_rewriting_values():
    result = parse_strict_json_object(
        '  {"selected_slot":2,"explanation":"kept as data"}\n',
        expected_keys={"selected_slot", "explanation"},
    )
    assert result.valid
    assert result.payload == {"selected_slot": 2, "explanation": "kept as data"}
    assert result.diagnostic() is None


@pytest.mark.parametrize(
    ("content", "code"),
    [
        ('{"selected_slot":0}{"selected_slot":1}', MALFORMED_JSON),
        ('prefix {"selected_slot":0}', MALFORMED_JSON),
        ('```json\n{"selected_slot":0}\n```', MARKDOWN_ENVELOPE),
        ('<think>choose zero</think>{"selected_slot":0}', REASONING_CHANNEL_LEAKAGE),
        ('{"selected_slot":NaN}', NON_FINITE_JSON),
        ('{"selected_slot":0,"selected_slot":1}', DUPLICATE_JSON_KEY),
        ('[0]', TOP_LEVEL_SCHEMA),
        ('{"slot":0}', FIELD_SCHEMA),
    ],
)
def test_rejects_protocol_failures_without_salvage(content, code):
    result = parse_strict_json_object(content, expected_keys={"selected_slot"})
    assert not result.valid
    assert result.payload is None
    assert result.failure_code == code
    assert result.diagnostic() == {
        "failure_code": code,
        "failure_detail": result.failure_detail,
    }


def test_separate_reasoning_echo_is_classified_without_exposing_text_in_diagnostic():
    reasoning = "candidate zero satisfies every inequality"
    result = parse_strict_json_object(
        f'{reasoning}\n{{"selected_slot":0}}',
        expected_keys={"selected_slot"},
        reasoning_text=reasoning,
    )
    assert result.failure_code == REASONING_CHANNEL_LEAKAGE
    assert reasoning not in (result.failure_detail or "")


def test_value_types_are_left_for_caller_schema_validation():
    result = parse_strict_json_object(
        '{"selected_slot":"0"}', expected_keys={"selected_slot"}
    )
    assert result.valid
    assert result.payload == {"selected_slot": "0"}

