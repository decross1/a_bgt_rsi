from fractions import Fraction
from itertools import product

from bench.agentic_game_theory.optimal_control import (
    MIXES,
    calibrate,
    evaluate_sequence,
    optimal_sequence,
    oracle,
)


def test_selfish_optimal_behavior_can_cooperate_until_last_round():
    bots = MIXES["grim"]
    sequence = optimal_sequence(bots, "own_payoff", 8, 0)
    assert sequence == [1] * 7 + [0]
    result = evaluate_sequence(sequence, bots, "own_payoff")
    assert result["total_utility"] == "165/2"
    assert result["episode_regret"] == "0"
    assert evaluate_sequence([0] * 8, bots, "own_payoff")["episode_regret"] == "35"


def test_dynamic_programming_matches_exhaustive_action_sequences():
    for bots in MIXES.values():
        for objective in ("own_payoff", "joint_payoff"):
            for player in (0, 3):
                solve = oracle(bots, objective, 4, player)
                exhaustive = [evaluate_sequence(list(seq), bots, objective, player=player)
                              for seq in product((0, 1), repeat=4)]
                assert solve(4, False)[0] == max(Fraction(r["total_utility"]) for r in exhaustive)
                for row in exhaustive:
                    assert Fraction(row["episode_regret"]) == sum(Fraction(r["decision_regret"]) for r in row["rounds"])


def test_calibration_keeps_payoff_labels_distinct_and_no_model_credit():
    result = calibrate()
    assert result["model_calls"] == 0 and len(result["cells"]) == 12
    assert all(cell["episode_regret"] == "0" for cell in result["cells"])
    for cell in result["cells"]:
        if cell["objective"] == "joint_payoff":
            assert cell["focal_cooperation_rate"] == 1


def test_focal_cooperation_does_not_imply_group_cooperation():
    result = evaluate_sequence([1] * 8, MIXES["retainers"], "joint_payoff")
    assert result["focal_cooperation_rate"] == 1
    assert result["group_cooperation_rate"] == .25
