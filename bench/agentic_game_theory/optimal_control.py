"""Finite-horizon best responses against declared scripted opponents.

The scripts are commitments, not strategic equilibrium players. An LLM can be
graded against this oracle only if their policies, state, payoff rule and horizon
are all disclosed. There are no model calls in this calibration.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from fractions import Fraction
from functools import cache
from pathlib import Path

from . import calibration
from .calibration import OBJECTIVES, payoffs, utility

MIXES = {"retainers": ("retain",) * 3, "contributors": ("contribute",) * 3,
         "grim": ("grim_trigger",) * 3}


def actions_for(bots: tuple[str, ...], player: int, action: int, defect_seen: bool) -> tuple[int, ...]:
    if len(bots) != 3 or any(b not in {"retain", "contribute", "grim_trigger"} for b in bots):
        raise ValueError("three known scripted opponents required")
    if type(player) is not int or not 0 <= player < 4 or type(action) is not int or action not in (0, 1):
        raise ValueError("invalid focal player/action")
    others = tuple(0 if b == "retain" or (b == "grim_trigger" and defect_seen) else 1 for b in bots)
    return others[:player] + (action,) + others[player:]


def oracle(bots: tuple[str, ...], objective: str, rounds: int, player: int = 0):
    if objective not in OBJECTIVES or type(rounds) is not int or not 1 <= rounds <= 16:
        raise ValueError("bounded horizon and known utility required")
    actions_for(bots, player, 0, False)
    @cache
    def solve(remaining: int, defect_seen: bool):
        if type(remaining) is not int or not 0 <= remaining <= rounds or type(defect_seen) is not bool:
            raise ValueError("oracle state is outside the declared game")
        if remaining == 0:
            return Fraction(), ()
        choices = []
        for action in (0, 1):
            joint = actions_for(bots, player, action, defect_seen)
            immediate = utility(joint, player, objective)
            later, _ = solve(remaining - 1, defect_seen or 0 in joint)
            choices.append(immediate + later)
        best = max(choices)
        return best, tuple(i for i, value in enumerate(choices) if value == best)
    return solve


def evaluate_sequence(actions: list[int], bots: tuple[str, ...], objective: str,
                      *, player: int = 0) -> dict:
    solve = oracle(bots, objective, len(actions), player)
    seen, total, rows = False, Fraction(), []
    for index, action in enumerate(actions):
        remaining = len(actions) - index
        best, optimal_actions = solve(remaining, seen)
        joint = actions_for(bots, player, action, seen)
        next_seen = seen or 0 in joint
        immediate = utility(joint, player, objective)
        continuation, _ = solve(remaining - 1, next_seen)
        regret = best - immediate - continuation
        rows.append({"round": index + 1, "joint_actions": list(joint),
                     "aggregate_contributors": sum(joint), "defection_previously_seen": seen,
                     "optimal_actions": list(optimal_actions), "chosen_action": action,
                     "decision_regret": str(regret), "material_payoffs": list(map(str, payoffs(joint))),
                     "utility": str(immediate)})
        total += immediate
        seen = next_seen
    best, _ = solve(len(actions), False)
    return {"objective": objective, "player": player, "bots": list(bots),
            "total_utility": str(total), "optimal_total_utility": str(best),
            "episode_regret": str(best - total),
            "cooperation_rate": sum(actions) / len(actions), "rounds": rows}


def optimal_sequence(bots, objective, rounds, player):
    solve, seen, sequence = oracle(bots, objective, rounds, player), False, []
    for remaining in range(rounds, 0, -1):
        _, options = solve(remaining, seen)
        action = min(options)  # Stable tie break, all tied actions remain credited.
        sequence.append(action)
        seen = seen or 0 in actions_for(bots, player, action, seen)
    return sequence


def calibrate() -> dict:
    cells = []
    for name, bots in MIXES.items():
        for objective in OBJECTIVES:
            for player in (0, 3):
                sequence = optimal_sequence(bots, objective, 8, player)
                cells.append({"opponent_mix": name, **evaluate_sequence(sequence, bots, objective, player=player)})
    return {"schema_version": "agentic-game-theory-optimal-control/v1",
            "campaign_id": "v2-agentic-game-theory-20260914", "model_calls": 0,
            "status": "cpu_oracle_calibrated", "cells": cells,
            "source_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in (Path(__file__), Path(calibration.__file__))},
            "limits": ["Optimal response to known committed scripts, not a Nash equilibrium claim.",
                       "One group/episode is a sampling unit; eight rounds are dependent observations.",
                       "No model responsiveness or human behavior measured.",
                       "A future model must know exact opponent policies, payoff rule, state and horizon."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = calibrate()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"status": result["status"], "cells": len(result["cells"]), "model_calls": 0}))


if __name__ == "__main__":
    main()
