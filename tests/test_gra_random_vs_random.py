#!/usr/bin/env python3
"""
day7_block2_openspiel_up sanity check.

Runs N episodes of OpenSpiel matrix_pd with GRA RandomAgent vs. itself
and writes a cooperation-rate summary. Per plan.yaml validation the
rate over 5 episodes must fall in [0.3, 0.7] — exact 0.5 is unlikely.
Action 0 == Cooperate, 1 == Defect (OpenSpiel matrix_pd convention).
"""

import argparse
import json
import os
import sys

import pyspiel
from game_reasoning_arena.arena.agents.random_agent import RandomAgent


def play_episode(game, agent_p0, agent_p1):
    state = game.new_initial_state()
    rounds = []
    while not state.is_terminal():
        if state.is_simultaneous_node():
            a0 = agent_p0({"legal_actions": state.legal_actions(0)})["action"]
            a1 = agent_p1({"legal_actions": state.legal_actions(1)})["action"]
            state.apply_actions([a0, a1])
            rounds.append([int(a0), int(a1)])
        else:
            cp = state.current_player()
            agent = agent_p0 if cp == 0 else agent_p1
            a = agent({"legal_actions": state.legal_actions()})["action"]
            state.apply_action(a)
            rounds.append([cp, int(a)])
    return rounds, list(state.returns())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", default="matrix_pd")
    ap.add_argument("--episodes", type=int, default=5)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--output", required=True)
    ap.add_argument("--band-low", type=float, default=0.3)
    ap.add_argument("--band-high", type=float, default=0.7)
    args = ap.parse_args()

    game = pyspiel.load_game(args.game)
    a0 = RandomAgent(seed=args.seed)
    a1 = RandomAgent(seed=args.seed + 1)

    n_actions = 0
    n_cooperate = 0
    episodes = []
    for i in range(args.episodes):
        rounds, returns = play_episode(game, a0, a1)
        for (x, y) in rounds:
            n_actions += 2
            n_cooperate += (1 if x == 0 else 0) + (1 if y == 0 else 0)
        episodes.append({"episode": i, "rounds": rounds, "returns": returns})

    rate = n_cooperate / n_actions if n_actions else 0.0
    in_band = args.band_low <= rate <= args.band_high
    out = {
        "game": args.game,
        "episodes": args.episodes,
        "seed": args.seed,
        "cooperation_rate": rate,
        "n_actions": n_actions,
        "n_cooperate": n_cooperate,
        "sanity_band": [args.band_low, args.band_high],
        "in_band": in_band,
        "per_episode": episodes,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(out, f, indent=2)
    verdict = "PASS" if in_band else "FAIL"
    print(
        f"{args.game} random-vs-random: rate={rate:.3f} "
        f"({n_cooperate}/{n_actions}) -> {verdict} "
        f"(band [{args.band_low}, {args.band_high}])"
    )
    return 0 if in_band else 1


if __name__ == "__main__":
    sys.exit(main())
