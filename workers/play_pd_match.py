"""Worker: one repeated PD match between the LLM player and a named opponent.

task_type = "play_pd_match"
payload = {
    "opponent":   str,   # one of: tft, grim_trigger, all_c, all_d, mirror_llm
    "n_rounds":   int,   # rounds in the match
    "log_path":   str,   # optional override; default falls through to wrapper log
}

worker_output (per schema/worker_contract.schema.json):
    {"task_id": ..., "status": "passed"|"error", "result": {...}, "errors": [...], "jsonl_log_path": ...}
"""

from __future__ import annotations

from typing import Any, Dict

from experiments.exp001_repeated_pd.llm_agent import LLMAgent, C, D, ACTION_INT
from experiments.exp001_repeated_pd.strategies import (
    ConstantCAgent,
    ConstantDAgent,
    LatchAgent,
    MirrorAgent,
)

INT_ACTION = {v: k for k, v in ACTION_INT.items()}

# Payoff matrix matches OpenSpiel matrix_pd: CC=(5,5), CD=(0,10), DC=(10,0), DD=(1,1).
PAYOFFS = {
    (C, C): (5, 5),
    (C, D): (0, 10),
    (D, C): (10, 0),
    (D, D): (1, 1),
}

# Coded opponent names (the academic literature names never appear here or
# in any string the LLM sees — see notes/track-c-day4-pd.md).
OPPONENTS = {
    "tft": MirrorAgent,
    "grim_trigger": LatchAgent,
    "all_c": ConstantCAgent,
    "all_d": ConstantDAgent,
}


def _first_d_round(actions):
    for i, a in enumerate(actions, start=1):
        if a == D:
            return i
    return None


def play_match(
    *,
    payload: Dict[str, Any],
    log_path: str,
    parent_request_id: str,
) -> Dict[str, Any]:
    opponent = payload["opponent"]
    n_rounds = int(payload["n_rounds"])
    task_id = payload.get("task_id") or f"match-{opponent}"
    temperature = float(payload.get("temperature", 0.0))
    rules_variant = payload.get("rules_variant", "baseline")

    llm = LLMAgent(log_path=log_path, caller_tag=f"exp001_{opponent}_player",
                   temperature=temperature, rules_variant=rules_variant)
    if opponent == "mirror_llm":
        opp = LLMAgent(log_path=log_path, caller_tag="exp001_mirror_llm_opp",
                       temperature=temperature, rules_variant=rules_variant)
    elif opponent in OPPONENTS:
        opp = OPPONENTS[opponent]()
    else:
        return {
            "task_id": task_id,
            "status": "error",
            "result": None,
            "errors": [f"play_match: unknown opponent {opponent!r}"],
            "jsonl_log_path": log_path,
        }

    rounds = []
    llm_payoff_total = 0.0
    opp_payoff_total = 0.0
    obs = {"legal_actions": [0, 1]}

    for r in range(1, n_rounds + 1):
        llm_out = llm.compute_action(observation=obs)
        opp_out = opp.compute_action(observation=obs)
        a_llm = INT_ACTION[llm_out["action"]]
        a_opp = INT_ACTION[opp_out["action"]]
        llm.observe(a_llm, a_opp)
        opp.observe(a_opp, a_llm)
        p_llm, p_opp = PAYOFFS[(a_llm, a_opp)]
        llm_payoff_total += p_llm
        opp_payoff_total += p_opp
        rounds.append({"round": r, "llm": a_llm, "opp": a_opp,
                       "llm_payoff": p_llm, "opp_payoff": p_opp})

    llm_actions = [x["llm"] for x in rounds]
    opp_actions = [x["opp"] for x in rounds]
    llm_coop_rate = sum(1 for a in llm_actions if a == C) / n_rounds
    opp_coop_rate = sum(1 for a in opp_actions if a == C) / n_rounds
    llm_parse_failures = llm.parse_failures
    llm_default_d = llm.default_d_plays
    opp_parse_failures = opp.parse_failures if opponent == "mirror_llm" else 0
    opp_default_d = opp.default_d_plays if opponent == "mirror_llm" else 0

    return {
        "task_id": task_id,
        "status": "passed",
        "result": {
            "opponent": opponent,
            "n_rounds": n_rounds,
            "rounds": rounds,
            "llm_coop_rate": llm_coop_rate,
            "opp_coop_rate": opp_coop_rate,
            "llm_mean_payoff": llm_payoff_total / n_rounds,
            "opp_mean_payoff": opp_payoff_total / n_rounds,
            "first_d_round_llm": _first_d_round(llm_actions),
            "first_d_round_opp": _first_d_round(opp_actions),
            "llm_parse_failures": llm_parse_failures,
            "llm_default_d_plays": llm_default_d,
            "opp_parse_failures": opp_parse_failures,
            "opp_default_d_plays": opp_default_d,
        },
        "errors": [],
        "jsonl_log_path": log_path,
    }
