from __future__ import annotations

import itertools
import json
from fractions import Fraction

import pytest

from experiments.payoff_action_calculator import calculator


def _fraction(value: dict) -> Fraction:
    assert set(value) == {"numerator", "denominator", "canonical"}
    result = Fraction(value["numerator"], value["denominator"])
    expected = (
        str(result.numerator)
        if result.denominator == 1
        else f"{result.numerator}/{result.denominator}"
    )
    assert value["canonical"] == expected
    return result


def _payload(
    *,
    endowment: int = 3,
    numerator: int = 3,
    denominator: int = 2,
    action: list[int] | None = None,
    seat: int = 0,
) -> dict:
    return {
        "E": endowment,
        "m_num": numerator,
        "m_den": denominator,
        "joint_action": action if action is not None else [0, 1, 0, 1],
        "focal_seat": seat,
    }


def _response(probe: dict, actions: list[int]) -> str:
    return json.dumps({"probe": probe, "actions": actions}, separators=(",", ":"))


@pytest.mark.parametrize("endowment", [1, 3, 7])
@pytest.mark.parametrize("multiplier", [(1, 1), (3, 2), (7, 3)])
def test_calculator_exhaustively_matches_all_joint_actions_and_seats(
    endowment, multiplier
):
    m_num, m_den = multiplier
    for bits in itertools.product((0, 1), repeat=4):
        contributors = sum(bits)
        shared = Fraction(m_num, m_den) * endowment * contributors / 4
        expected_players = [
            Fraction(endowment * (1 - action)) + shared for action in bits
        ]
        for seat in range(4):
            result = calculator.calculate(
                _payload(
                    endowment=endowment,
                    numerator=m_num,
                    denominator=m_den,
                    action=list(bits),
                    seat=seat,
                )
            )
            assert result["formula_version"] == calculator.FORMULA_VERSION
            assert result["evaluated_joint_action"] == list(bits)
            assert result["contributor_count"] == contributors
            assert result["other_contributor_count"] == contributors - bits[seat]
            assert result["focal_action"] == bits[seat]
            assert [_fraction(value) for value in result["player_payoffs"]] == (
                expected_players
            )
            assert _fraction(result["focal_payoff"]) == expected_players[seat]
            assert _fraction(result["total_payoff"]) == sum(
                expected_players, Fraction()
            )
            assert result["strategy_advice_included"] is False


def test_player_permutation_preserves_and_permutes_exact_payoffs():
    original_action = [0, 1, 1, 0]
    original = calculator.calculate(_payload(action=original_action, seat=2))
    original_payoffs = [_fraction(value) for value in original["player_payoffs"]]
    for permutation in itertools.permutations(range(4)):
        permuted_action = [original_action[index] for index in permutation]
        permuted_focal = permutation.index(2)
        permuted = calculator.calculate(
            _payload(action=permuted_action, seat=permuted_focal)
        )
        assert [_fraction(value) for value in permuted["player_payoffs"]] == [
            original_payoffs[index] for index in permutation
        ]
        assert _fraction(permuted["focal_payoff"]) == _fraction(
            original["focal_payoff"]
        )
        assert _fraction(permuted["total_payoff"]) == _fraction(
            original["total_payoff"]
        )
        assert permuted["contributor_count"] == original["contributor_count"]
        assert (
            permuted["other_contributor_count"] == original["other_contributor_count"]
        )


def test_endowment_scaling_scales_every_payoff_but_not_binding_counts():
    base = calculator.calculate(_payload(endowment=3, action=[1, 0, 1, 1], seat=1))
    scaled = calculator.calculate(_payload(endowment=15, action=[1, 0, 1, 1], seat=1))
    for base_value, scaled_value in zip(
        base["player_payoffs"], scaled["player_payoffs"], strict=True
    ):
        assert _fraction(scaled_value) == 5 * _fraction(base_value)
    assert _fraction(scaled["focal_payoff"]) == 5 * _fraction(base["focal_payoff"])
    assert _fraction(scaled["total_payoff"]) == 5 * _fraction(base["total_payoff"])
    for key in (
        "evaluated_joint_action",
        "focal_seat",
        "contributor_count",
        "other_contributor_count",
        "focal_action",
    ):
        assert scaled[key] == base[key]


@pytest.mark.parametrize(
    "mutation",
    [
        {"E": True},
        {"m_num": True},
        {"m_den": True},
        {"joint_action": [0, 1, False, 1]},
        {"focal_seat": False},
        {"m_den": 0},
        {"m_num": -1},
        {"focal_seat": 4},
        {"joint_action": [0, 1, 0]},
        {"joint_action": [0, 1, 0, 2]},
        {"m_num": 6, "m_den": 4},
        {"E": 10**19},
    ],
)
def test_calculator_rejects_malformed_numeric_and_binary_inputs(mutation):
    payload = _payload()
    payload.update(mutation)
    with pytest.raises(calculator.PayoffCalculatorError):
        calculator.calculate(payload)


def test_calculator_requires_exact_input_fields():
    missing = _payload()
    missing.pop("E")
    extra = {**_payload(), "players": 4}
    for payload in (missing, extra, [], None):
        with pytest.raises(calculator.PayoffCalculatorError):
            calculator.calculate(payload)


def test_strict_response_passes_every_independent_dimension():
    probe = calculator.calculate(_payload())
    actions = [0, 1, 0, 1, 1, 0, 1, 0]
    grade = calculator.score_response(
        _response(probe, actions), expected_input=_payload(), expected_horizon=8
    )
    assert grade["strict_contract_valid"] is True
    assert grade["failure_codes"] == []
    assert grade["actions"] == actions
    assert len(grade["action_sha256"]) == 64


def test_non_strict_decimal_probe_can_be_arithmetically_right_and_action_scoreable():
    expected = calculator.calculate(_payload())
    probe = json.loads(json.dumps(expected))
    probe["player_payoffs"] = [
        float(_fraction(value)) for value in expected["player_payoffs"]
    ]
    probe["focal_payoff"] = float(_fraction(expected["focal_payoff"]))
    probe["total_payoff"] = float(_fraction(expected["total_payoff"]))
    actions = [1, 0, 1, 0]
    grade = calculator.score_response(
        _response(probe, actions), expected_input=_payload(), expected_horizon=4
    )
    assert grade["field_valid"] is True
    assert grade["numeric_representation_valid"] is False
    assert grade["numeric_values_parseable"] is True
    assert grade["exact_arithmetic"] is True
    assert grade["action_array_valid"] is True
    assert grade["action_scoreable"] is True
    assert grade["strict_contract_valid"] is False


def test_wrong_or_unparseable_probe_does_not_erase_valid_action_vector():
    expected = calculator.calculate(_payload())
    wrong = json.loads(json.dumps(expected))
    wrong["focal_payoff"] = {"numerator": 999, "denominator": 1, "canonical": "999"}
    actions = [0, 1] * 6
    wrong_grade = calculator.score_response(
        _response(wrong, actions), expected_input=_payload(), expected_horizon=12
    )
    assert wrong_grade["exact_arithmetic"] is False
    assert wrong_grade["assessment_status"]["arithmetic"] == "failed"
    assert "arithmetic_wrong" in wrong_grade["failure_codes"]
    assert wrong_grade["action_scoreable"] is True
    assert wrong_grade["actions"] == actions

    malformed = json.loads(json.dumps(expected))
    malformed["focal_payoff"] = "not-a-number"
    malformed_grade = calculator.score_response(
        _response(malformed, actions), expected_input=_payload(), expected_horizon=12
    )
    assert malformed_grade["numeric_values_parseable"] is False
    assert malformed_grade["assessment_status"]["arithmetic"] == "unassessed"
    assert "arithmetic_wrong" not in malformed_grade["failure_codes"]
    assert malformed_grade["action_scoreable"] is True
    assert malformed_grade["actions"] == actions


def test_structurally_invalid_probe_does_not_erase_valid_action_vector():
    actions = [1, 0, 1, 0]
    content = json.dumps({"probe": {"unexpected": 1}, "actions": actions})
    grade = calculator.score_response(
        content, expected_input=_payload(), expected_horizon=4
    )
    assert grade["json_valid"] is True
    assert grade["field_valid"] is False
    assert grade["action_array_valid"] is True
    assert grade["action_scoreable"] is True
    assert grade["actions"] == actions
    assert grade["failure_codes"] == ["response_fields_invalid"]
    assert grade["assessment_status"]["numeric_values"] == "unassessed"
    assert grade["assessment_status"]["arithmetic"] == "unassessed"


def test_wrong_row_binding_is_separate_from_exact_numeric_representation():
    expected = calculator.calculate(_payload())
    wrong_row = json.loads(json.dumps(expected))
    wrong_row["contributor_count"] = 1
    wrong_row["other_contributor_count"] = 1
    grade = calculator.score_response(
        _response(wrong_row, [1, 0, 1, 0]),
        expected_input=_payload(),
        expected_horizon=4,
    )
    assert grade["numeric_representation_valid"] is True
    assert grade["exact_arithmetic"] is True
    assert grade["probe_binding_valid"] is False
    assert grade["contributor_counts_correct"] is False
    assert grade["action_scoreable"] is True


def test_self_consistent_forged_expected_values_cannot_cross_the_trust_boundary():
    expected = calculator.calculate(_payload())
    forged = json.loads(json.dumps(expected))
    forged_value = {"numerator": 999, "denominator": 1, "canonical": "999"}
    forged["player_payoffs"] = [forged_value.copy() for _ in range(4)]
    forged["focal_payoff"] = forged_value.copy()
    forged["total_payoff"] = {
        "numerator": 3996,
        "denominator": 1,
        "canonical": "3996",
    }
    grade = calculator.score_response(
        _response(forged, [0, 1, 0, 1]),
        expected_input=_payload(),
        expected_horizon=4,
    )
    assert grade["numeric_representation_valid"] is True
    assert grade["probe_binding_valid"] is True
    assert grade["exact_arithmetic"] is False
    assert grade["strict_contract_valid"] is False
    assert "arithmetic_wrong" in grade["failure_codes"]


def test_canonical_rational_strings_are_diagnosed_but_not_strict():
    expected = calculator.calculate(_payload())
    probe = json.loads(json.dumps(expected))
    for index, value in enumerate(expected["player_payoffs"]):
        probe["player_payoffs"][index] = value["canonical"]
    probe["focal_payoff"] = expected["focal_payoff"]["canonical"]
    probe["total_payoff"] = expected["total_payoff"]["canonical"]
    grade = calculator.score_response(
        _response(probe, [0, 1, 0, 1]),
        expected_input=_payload(),
        expected_horizon=4,
    )
    assert grade["numeric_representation_valid"] is False
    assert grade["numeric_values_parseable"] is True
    assert grade["exact_arithmetic"] is True
    assert grade["action_scoreable"] is True


def test_invalid_action_does_not_erase_valid_probe_arithmetic():
    expected = calculator.calculate(_payload())
    grade = calculator.score_response(
        _response(expected, [0, 1, 2, 0]),
        expected_input=_payload(),
        expected_horizon=4,
    )
    assert grade["exact_arithmetic"] is True
    assert grade["probe_binding_valid"] is True
    assert grade["action_array_valid"] is False
    assert grade["action_scoreable"] is False


def test_binary_action_of_wrong_horizon_is_valid_but_not_scoreable():
    expected = calculator.calculate(_payload())
    grade = calculator.score_response(
        _response(expected, [0, 1, 0, 1]),
        expected_input=_payload(),
        expected_horizon=8,
    )
    assert grade["action_array_valid"] is True
    assert grade["action_scoreable"] is False
    assert "action_array_invalid" not in grade["failure_codes"]
    assert "action_horizon_mismatch" in grade["failure_codes"]
    assert grade["assessment_status"]["action_array"] == "passed"
    assert grade["assessment_status"]["action_scoreability"] == "failed"

    empty_grade = calculator.score_response(
        _response(expected, []), expected_input=_payload(), expected_horizon=8
    )
    assert empty_grade["action_array_valid"] is False
    assert empty_grade["action_scoreable"] is False
    assert "action_array_invalid" in empty_grade["failure_codes"]
    assert "action_horizon_mismatch" not in empty_grade["failure_codes"]


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_json_and_duplicate_keys_are_rejected(constant):
    expected = calculator.calculate(_payload())
    nonfinite = (
        '{"probe":'
        + json.dumps(expected, separators=(",", ":"))
        + ',"actions":[0,1,0,1]}'
    )
    marker = '"numerator":'
    marker_index = nonfinite.index(marker) + len(marker)
    value_end = nonfinite.index(",", marker_index)
    nonfinite = nonfinite[:marker_index] + constant + nonfinite[value_end:]
    grade = calculator.score_response(
        nonfinite, expected_input=_payload(), expected_horizon=4
    )
    assert grade["json_valid"] is False
    assert grade["action_scoreable"] is False
    assert grade["failure_codes"] == ["json_invalid"]
    assert grade["assessment_status"]["arithmetic"] == "unassessed"
    assert grade["assessment_status"]["action_array"] == "unassessed"

    duplicate = (
        '{"probe":' + json.dumps(expected) + ',"actions":[0,1,0,1],"actions":[1,1,1,1]}'
    )
    duplicate_grade = calculator.score_response(
        duplicate, expected_input=_payload(), expected_horizon=4
    )
    assert duplicate_grade["json_valid"] is False
    assert duplicate_grade["action_scoreable"] is False
    assert duplicate_grade["failure_codes"] == ["json_invalid"]


def test_deeply_nested_json_is_a_bounded_parse_failure_not_an_exception():
    expected_input = _payload()
    deeply_nested = "[" * 10_000 + "0" + "]" * 10_000
    grade = calculator.score_response(
        deeply_nested, expected_input=expected_input, expected_horizon=4
    )
    assert grade["json_valid"] is False
    assert grade["failure_codes"] == ["json_invalid"]
    assert set(grade["assessment_status"].values()) == {"failed", "unassessed"}


def test_numeric_tokens_and_response_size_are_bounded_before_fraction_work():
    expected = calculator.calculate(_payload())
    huge_exponent = _response(expected, [0, 1, 0, 1]).replace(
        '"numerator":21', '"numerator":1e9999', 1
    )
    exponent_grade = calculator.score_response(
        huge_exponent, expected_input=_payload(), expected_horizon=4
    )
    assert exponent_grade["json_valid"] is False
    assert exponent_grade["action_scoreable"] is False

    huge_integer = _response(expected, [0, 1, 0, 1]).replace(
        '"numerator":21', '"numerator":' + ("9" * 129), 1
    )
    integer_grade = calculator.score_response(
        huge_integer, expected_input=_payload(), expected_horizon=4
    )
    assert integer_grade["json_valid"] is False

    oversized = " " * (calculator.MAX_RESPONSE_BYTES + 1)
    size_grade = calculator.score_response(
        oversized, expected_input=_payload(), expected_horizon=4
    )
    assert size_grade["json_valid"] is False


def test_expected_horizon_is_explicit_and_not_hard_coded():
    expected = calculator.calculate(_payload())
    for horizon in (4, 8, 12):
        grade = calculator.score_response(
            _response(expected, [0] * horizon),
            expected_input=_payload(),
            expected_horizon=horizon,
        )
        assert grade["action_scoreable"] is True
        assert grade["expected_horizon"] == horizon
    for invalid in (True, 0, 3, 13, 129):
        with pytest.raises(calculator.PayoffCalculatorError):
            calculator.score_response(
                _response(expected, [0]),
                expected_input=_payload(),
                expected_horizon=invalid,
            )


def test_output_contains_only_declared_audit_fields_and_no_strategy_result():
    result = calculator.calculate(_payload())
    assert set(result) == calculator._PROBE_KEYS
    assert result["strategy_advice_included"] is False
    assert not (
        {"optimal_action", "recommended_action", "future_utility"} & set(result)
    )
