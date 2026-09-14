from fractions import Fraction
from itertools import product

import pytest

from bench.agentic_game_theory.calibration import (
    DEFAULT_MANIFEST,
    act,
    calibrate,
    load_manifest,
    observation,
    payoffs,
    regret,
)


def test_known_public_goods_payoffs_and_distinct_utilities():
    assert payoffs((0, 0, 0, 0)) == (5, 5, 5, 5)
    assert payoffs((1, 1, 1, 1)) == (10, 10, 10, 10)
    assert payoffs((0, 1, 1, 1)) == (Fraction(25, 2), Fraction(15, 2), Fraction(15, 2), Fraction(15, 2))
    for opponents in product((0, 1), repeat=3):
        assert regret((0, *opponents), 0, "own_payoff") == 0
        assert regret((1, *opponents), 0, "own_payoff") == Fraction(5, 2)
        assert regret((1, *opponents), 0, "joint_payoff") == 0
        assert regret((0, *opponents), 0, "joint_payoff") == 5


def test_no_false_information_blindness_from_own_payoff():
    for history in product((0, 1), repeat=4):
        for player in range(4):
            private = observation([history], player, "own_outcomes")
            public = observation([history], player, "public_history")
            assert "public_actions" not in private
            assert act("previous_majority", private) == act("previous_majority", public)


def test_exhaustive_classical_controls_are_not_model_results():
    result = calibrate(load_manifest(DEFAULT_MANIFEST))
    assert result["model_calls"] == 0
    assert result["stage_game"][0]["pure_nash_profiles"] == [[0, 0, 0, 0]]
    assert result["stage_game"][1]["pure_nash_profiles"] == [[1, 1, 1, 1]]
    assert len(result["classical_simulations"]) == 324
    for row in result["classical_simulations"]:
        assert len(row["actions"]) == 8
        assert 0 <= row["cooperation_rate"] <= 1


@pytest.mark.parametrize("actions", [(True, 0, 0, 0), (2, 0, 0, 0), (0, 0), (0.0, 0, 0, 0)])
def test_invalid_actions_fail_closed(actions):
    with pytest.raises(ValueError):
        payoffs(actions)
