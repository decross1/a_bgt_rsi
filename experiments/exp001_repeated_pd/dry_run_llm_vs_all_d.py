#!/usr/bin/env python3
"""day7_block2_strategies_and_llm_agent dry-run.

Plays N rounds of repeated PD with the LLM player against the
constant-D fixed agent. Validation per plan.yaml: the LLM should
switch to D for the majority of the last 5 rounds — i.e. is the
model tracking its opponent.

Writes a JSON summary to --output. Each wrapper call is appended to
--log-path (default ``logs/day7_dryrun.jsonl``); parse_failure events
(if any) land in the same JSONL stream.
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from experiments.exp001_repeated_pd.llm_agent import LLMAgent, C, D, ACTION_INT  # noqa: E402
from experiments.exp001_repeated_pd.strategies import ConstantDAgent  # noqa: E402

INT_ACTION = {v: k for k, v in ACTION_INT.items()}


def play(rounds: int, log_path: str) -> dict:
    llm = LLMAgent(log_path=log_path, caller_tag="exp001_dry_run_llm_vs_all_d")
    opp = ConstantDAgent()

    per_round = []
    for r in range(1, rounds + 1):
        llm_out = llm.compute_action(observation={"legal_actions": [0, 1]})
        opp_out = opp.compute_action(observation={"legal_actions": [0, 1]})
        own = INT_ACTION[llm_out["action"]]
        oth = INT_ACTION[opp_out["action"]]
        llm.observe(own, oth)
        opp.observe(oth, own)
        per_round.append({"round": r, "llm": own, "opp": oth})

    last5 = [x["llm"] for x in per_round[-5:]]
    n_llm_d_last5 = sum(1 for a in last5 if a == D)
    n_llm_c_total = sum(1 for x in per_round if x["llm"] == C)

    return {
        "rounds": rounds,
        "opponent": "constant_d",
        "llm_actions": [x["llm"] for x in per_round],
        "per_round": per_round,
        "n_llm_cooperate_total": n_llm_c_total,
        "llm_last5": last5,
        "n_llm_d_last5": n_llm_d_last5,
        "llm_switched_to_d_majority_last5": n_llm_d_last5 >= 3,
        "parse_failures": llm.parse_failures,
        "default_d_plays": llm.default_d_plays,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=10)
    ap.add_argument("--output", required=True)
    ap.add_argument("--log-path", default="logs/day7_dryrun.jsonl")
    args = ap.parse_args()

    result = play(args.rounds, args.log_path)

    os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(result, f, indent=2)

    last5_str = " ".join(result["llm_last5"])
    verdict = "PASS" if result["llm_switched_to_d_majority_last5"] else "FAIL"
    print(
        f"dry-run: {args.rounds} rounds vs constant_d; "
        f"llm last-5={last5_str}; D in last-5 = {result['n_llm_d_last5']}/5; "
        f"parse_failures={result['parse_failures']}; "
        f"default_d_plays={result['default_d_plays']} -> {verdict}"
    )
    return 0 if result["llm_switched_to_d_majority_last5"] else 1


if __name__ == "__main__":
    sys.exit(main())
