"""Four-cell excluded calibration for public-goods payoff interfaces.

The runner targets the already-resident Flash service.  It never starts,
stops, or reconfigures serving and can never produce scientific admission or
evidence-rung credit.
"""

from __future__ import annotations

import argparse
import copy
import functools
import hashlib
import itertools
import json
import math
import re
import signal
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

from bench.flash_next_ab import harness, private_evidence, transport
from experiments.payoff_action_calculator import calculator
from experiments.payoff_assistance_plans import study as assistance
from experiments.payoff_tool_arithmetic import flash_resident as resident
from orchestrator.weekly_upgrade_trial import resource_lease

CODE_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_ROOT = Path(
    "/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-20/"
    "payoff-action-calibration"
)
PLAN_SCHEMA = "flash-payoff-action-calibration-plan/v1"
RUN_SCHEMA = "flash-payoff-action-calibration-run/v1"
VALIDATION_SCHEMA = "flash-payoff-action-calibration-validation/v1"
PRIVATE_SCHEMA = "flash-payoff-action-calibration-private-call/v1"
POLICY_ID = "calibration_deterministic_no_thinking"
POLICY = {"temperature": 0, "top_p": 1, "top_k": 64, "enable_thinking": False}
MAX_TOKENS = 512
CALL_TIMEOUT_S = 30.0
EVALUATOR_BUDGET_S = 900.0
MEMORY_FLOOR_GIB = 20.0
PLAYERS = 4
UNITS = 4
CONDITIONS = 12
MAX_CALLS = 20
CLAIM_LIMIT = (
    "permanently excluded four-cell interface calibration only; no confirmation, "
    "admission, L2, model-quality, strategy-generalization, or market claim"
)
SOURCE_PRIMARY_PANEL_SHA256 = (
    "9413597bbdee9ae6ae3c5bc50501f3720994c3fccf3cdb4c280562c557ac13f1"
)
SOURCE_CALIBRATION_ARTIFACT_SHA256 = (
    "d69af7769c8add83e976faed04099bfef2e7f5826575c9dcb18c36949e895049"
)
SOURCE_PATHS = (
    "agent_wrapper/__init__.py",
    "agent_wrapper/deployment.py",
    "bench/agentic_game_theory/__init__.py",
    "bench/flash_next_ab/__init__.py",
    "experiments/payoff_action_calibration/__init__.py",
    "experiments/payoff_action_calibration/runner.py",
    "experiments/payoff_action_calibration/PREREGISTRATION.md",
    "experiments/payoff_action_calculator/__init__.py",
    "experiments/payoff_action_calculator/calculator.py",
    "experiments/payoff_assistance_plans/__init__.py",
    "experiments/payoff_assistance_plans/study.py",
    "experiments/payoff_assistance_plans/PREREGISTRATION.md",
    "experiments/payoff_tool_arithmetic/flash_resident.py",
    "experiments/known_opponent_utility/pilot.py",
    "bench/payoff_tool_study/runner.py",
    "bench/agentic_game_theory/calibration.py",
    "bench/agentic_game_theory/optimal_control.py",
    "bench/flash_next_ab/adapters.py",
    "bench/flash_next_ab/harness.py",
    "bench/flash_next_ab/transport.py",
    "bench/flash_next_ab/private_evidence.py",
    "bench/flash_next_ab/manifest.py",
    "bench/flash_next_ab/qualification.py",
    "orchestrator/flash_resident.py",
    "orchestrator/weekly_stable_benchmark_report.py",
    "orchestrator/weekly_upgrade.py",
    "orchestrator/weekly_upgrade_budget.py",
    "orchestrator/weekly_upgrade_trial.py",
)
_EXPECTED_LOCAL_IMPORT_CLOSURE = {
    "agent_wrapper/__init__.py",
    "agent_wrapper/deployment.py",
    "bench/agentic_game_theory/__init__.py",
    "bench/agentic_game_theory/calibration.py",
    "bench/flash_next_ab/__init__.py",
    "bench/flash_next_ab/adapters.py",
    "bench/flash_next_ab/harness.py",
    "bench/flash_next_ab/manifest.py",
    "bench/flash_next_ab/private_evidence.py",
    "bench/flash_next_ab/qualification.py",
    "bench/flash_next_ab/transport.py",
    "bench/payoff_tool_study/runner.py",
    "experiments/payoff_action_calculator/__init__.py",
    "experiments/payoff_action_calculator/calculator.py",
    "experiments/payoff_action_calibration/__init__.py",
    "experiments/payoff_action_calibration/runner.py",
    "experiments/payoff_assistance_plans/__init__.py",
    "experiments/payoff_assistance_plans/study.py",
    "experiments/payoff_tool_arithmetic/flash_resident.py",
    "orchestrator/flash_resident.py",
    "orchestrator/weekly_stable_benchmark_report.py",
    "orchestrator/weekly_upgrade.py",
    "orchestrator/weekly_upgrade_budget.py",
    "orchestrator/weekly_upgrade_trial.py",
}

_RAW_CELLS = (
    {
        "cell_id": "calibration-action-aware-v1-01",
        "rule": "consecutive_defection_trigger",
        "rule_parameter": 1,
        "horizon": 4,
        "endowment": 6,
        "multiplier": "7/6",
        "focal_seat": 0,
        "objective": "cumulative_focal_payoff",
        "probe": {
            "joint_action": [0, 0, 0, 0],
            "focal_action": 0,
            "other_contributors": 0,
        },
        "task_sha256": "87f04056b29a7630be04a3f9dad4764d7db2a08a13d85ee5ed79559bf8a3d51e",
    },
    {
        "cell_id": "calibration-action-aware-v1-02",
        "rule": "consecutive_defection_trigger",
        "rule_parameter": 2,
        "horizon": 6,
        "endowment": 10,
        "multiplier": "8/5",
        "focal_seat": 1,
        "objective": "cumulative_focal_payoff",
        "probe": {
            "joint_action": [1, 1, 0, 0],
            "focal_action": 1,
            "other_contributors": 1,
        },
        "task_sha256": "fb1347dd0c2f79f6aeaf2b6ef419f6e25c05ac7dd5a1efecda16323b90e10786",
    },
    {
        "cell_id": "calibration-action-aware-v1-03",
        "rule": "consecutive_defection_trigger",
        "rule_parameter": 3,
        "horizon": 9,
        "endowment": 14,
        "multiplier": "9/7",
        "focal_seat": 2,
        "objective": "cumulative_focal_payoff",
        "probe": {
            "joint_action": [1, 1, 0, 0],
            "focal_action": 0,
            "other_contributors": 2,
        },
        "task_sha256": "786c5aee420d142479d20d446e7edac2ca2eb77e13f6bad6bae2ed56650288ee",
    },
    {
        "cell_id": "calibration-action-aware-v1-04",
        "rule": "consecutive_defection_trigger",
        "rule_parameter": 4,
        "horizon": 12,
        "endowment": 18,
        "multiplier": "11/6",
        "focal_seat": 3,
        "objective": "cumulative_focal_payoff",
        "probe": {
            "joint_action": [1, 1, 1, 1],
            "focal_action": 1,
            "other_contributors": 3,
        },
        "task_sha256": "08fe8f4618d6b221cdd3c8aec9beeecb27de1107ac10a6dcf8ee3b59ff1a10a9",
    },
)
_ARM_ORDERS = (
    ("direct", "table", "calculator"),
    ("table", "calculator", "direct"),
    ("calculator", "direct", "table"),
    ("direct", "calculator", "table"),
)
_DEVELOPMENTAL_PRIMARY_TASK_HASHES = {
    "3276b591c7c96086a76de5ffe1c7d59fdc8dd37c40e12109c8211bf583239536",
    "cd323857e952f92ff308936058e67682d79db05985394bfbb19a8709f0147553",
    "23112480947096934b8e6b12b88aeab77a0d94861cad9f49c9d8da68bfaff462",
    "6c806b359c98dc514b6411db3abaf1d9cde0743e5420c89e2c9be2db00ecb2da",
    "1518d481e7e40ca6be51bad197ab7a5cb5bca7b35cd7a57f1dc7681b24c32692",
    "34f74c12b5dd6e80c213609a04220d961c64846326942177d90a41e42d24e43f",
    "f2e719ffdb391af635a489be3ab0f6aee6345ce648ce49b9309712984595a5ee",
    "7e200e7168addc305eee9d09e475cd45838c601ec9c25e3a807faf97d7498c39",
    "1501c33cfe55b773f6c28a6ed796aed7cfac53b82dfc4fc767e009082c688745",
    "c238a44f5a749f19b4f80626b70b1eda31adaa23ea721d4a53ac90b571ec7402",
    "7251f46f0b708ead15a4cc327299cc0549bb96f29f35fb9b1603e30bb0f9c197",
    "0f5abc5813af09beee088a6e555e833c89d2c677bdf0bd18ce899af003ab28b6",
    "ed714916bf30f926275bf5ce6b1497c40b9286dc98199a0de926f21807a5a46a",
    "cb18d47508314bcb0b7ff7b0bceeb6de134aec99b28320cb4708312d428382d2",
    "a75e3e0368c984e8839a52427a6ad3587361b004e8e4078ed63b9b02038adb0b",
    "f2e1616157702e45661c49d46de4ff1eacd0ffe875571e6b25874914c9f27a6d",
    "abf542bd1b02076050eb69db75d92a5571fb85f2583ea577e906fe71cdb825c5",
    "a9c181e71b16b15b2eb79554175b0f864bed539f8352bfae7339cf43740358cc",
    "1a358c96e8e0f8edbca3cc7743fcc46d5a18f394b2d6b37e813e93dd20ad71d6",
    "707e9b469211148f7bceb1bf6a1fb33c82601e526e6c6e20ace6b526bb4ff2f5",
    "38dfba27712263c40f7994e745d386bf4eae51eb13ad10e8a8f0d4e0ebb8b60d",
    "b3b223e380ddcade2e2d0cac6e61c93a8420549c5f2799c339d4e6e2fc068280",
    "dcd8712d026a26681f60932a078d15f1d856aeb51693636b93b455bd40f5b578",
    "173d6346b88d613471f5bec806dd6d04b4bdfabd50c75d446eee2f95fe746fb3",
    "2badb32e59b1ae8cbfa8b5cd223a211831f4999b458e8e71f89e18a33a11909b",
    "18d0441a01951711edcbb74f6561a872c5a18c84a64aa930506ebf4d3c5b185f",
    "261de3bf47f308427bdc498566a5928b76e41f0be5cf0b376eb22a69d50b37be",
    "d32c2020fd8106282573c4329524aca5cfd8b26f515bf73eb296359b737fb52d",
    "fc62ff23a5c265414d1b05964badbf76efe6d509ebb658d40d24a3dbd29d8fa4",
    "5a740795a876ce1eb7aa69970134cdc28724b3f153309907000c643c546ed84b",
}

CALCULATOR_TOOL_SPEC = {
    "type": "function",
    "function": {
        "name": "public_goods_joint_action_payoff",
        "description": (
            "Return exact one-round payoffs for the supplied joint action. "
            "It provides no strategy, recommendation, or future utility."
        ),
        "parameters": copy.deepcopy(calculator.INPUT_SCHEMA),
    },
}
TABLE_TOOL_SPEC = copy.deepcopy(assistance.TOOL_SPEC)
FINAL_RESPONSE_CONTRACT = (
    'Return bare JSON exactly {"probe":{...},"actions":[...]}. '
    "probe must contain exactly: formula_version (the literal "
    f"{calculator.FORMULA_VERSION!r}); evaluated_joint_action (four binary "
    "integers echoing the probe action); focal_seat; contributor_count; "
    "other_contributor_count; focal_action; player_payoffs (four exact-number "
    "objects); focal_payoff (one exact-number object); total_payoff (one exact-"
    "number object); and strategy_advice_included=false. Each exact-number "
    "object has exactly numerator (integer), denominator (positive integer), "
    "and canonical (a reduced integer-or-fraction string). actions must be "
    "exactly H binary integers."
)


class CalibrationError(ValueError):
    """The excluded calibration contract or evidence is invalid."""


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise CalibrationError(reason)


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _rational(value: Fraction) -> str:
    return (
        str(value.numerator)
        if value.denominator == 1
        else f"{value.numerator}/{value.denominator}"
    )


def _sources() -> dict[str, str]:
    _require(
        _EXPECTED_LOCAL_IMPORT_CLOSURE.issubset(SOURCE_PATHS),
        "declared source set omits an expected local import",
    )
    return {path: _sha((CODE_ROOT / path).read_bytes()) for path in SOURCE_PATHS}


def _opponent_action(cell: dict[str, Any], state: int) -> int:
    _require(cell["rule"] == "consecutive_defection_trigger", "unknown rule")
    return int(state < cell["rule_parameter"])


def _transition(cell: dict[str, Any], state: int, focal_action: int) -> int:
    threshold = cell["rule_parameter"]
    if state == threshold:
        return threshold
    return 0 if focal_action == 1 else state + 1


def _focal_payoff(cell: dict[str, Any], state: int, focal_action: int) -> Fraction:
    other_action = _opponent_action(cell, state)
    contributors = 3 * other_action + focal_action
    multiplier = Fraction(cell["multiplier"])
    return Fraction(cell["endowment"] * (1 - focal_action)) + (
        multiplier * cell["endowment"] * contributors / PLAYERS
    )


def _simulate(cell: dict[str, Any], actions: tuple[int, ...]) -> Fraction:
    _require(
        len(actions) == cell["horizon"]
        and all(type(action) is int and action in (0, 1) for action in actions),
        "plan does not match the frozen horizon",
    )
    state = 0
    total = Fraction()
    for action in actions:
        total += _focal_payoff(cell, state, action)
        state = _transition(cell, state, action)
    return total


def _oracle(cell: dict[str, Any]) -> tuple[Fraction, int, tuple[int, ...]]:
    @functools.cache
    def solve(round_index: int, state: int) -> tuple[Fraction, int, tuple[int, ...]]:
        if round_index == cell["horizon"]:
            return Fraction(), 1, ()
        candidates = []
        for action in (0, 1):
            future, count, suffix = solve(
                round_index + 1, _transition(cell, state, action)
            )
            candidates.append(
                (_focal_payoff(cell, state, action) + future, count, (action, *suffix))
            )
        best_value = max(row[0] for row in candidates)
        best = [row for row in candidates if row[0] == best_value]
        return best_value, sum(row[1] for row in best), min(row[2] for row in best)

    return solve(0, 0)


def _myopic(cell: dict[str, Any]) -> tuple[int, ...]:
    state = 0
    actions = []
    for _round in range(cell["horizon"]):
        values = {action: _focal_payoff(cell, state, action) for action in (0, 1)}
        action = 0 if values[0] >= values[1] else 1
        actions.append(action)
        state = _transition(cell, state, action)
    return tuple(actions)


def _future_dependent_rounds(
    cell: dict[str, Any], actions: tuple[int, ...]
) -> list[int]:
    state = 0
    rounds = []
    for index, action in enumerate(actions):
        values = {
            candidate: _focal_payoff(cell, state, candidate) for candidate in (0, 1)
        }
        immediate = 0 if values[0] >= values[1] else 1
        if action != immediate:
            rounds.append(index + 1)
        state = _transition(cell, state, action)
    return rounds


def _calculator_input(cell: dict[str, Any]) -> dict[str, Any]:
    multiplier = Fraction(cell["multiplier"])
    return {
        "E": cell["endowment"],
        "m_num": multiplier.numerator,
        "m_den": multiplier.denominator,
        "joint_action": copy.deepcopy(cell["probe"]["joint_action"]),
        "focal_seat": cell["focal_seat"],
    }


def panel() -> list[dict[str, Any]]:
    """Return the four independently audited, permanently excluded cells."""

    rows = []
    for index, raw in enumerate(_RAW_CELLS):
        cell = copy.deepcopy(raw)
        task_hash = cell.pop("task_sha256")
        _require(_sha(_canonical(cell)) == task_hash, "source cell hash differs")
        cell["task_sha256"] = task_hash
        multiplier = Fraction(cell["multiplier"])
        cell["m_num"] = multiplier.numerator
        cell["m_den"] = multiplier.denominator
        cell["seed"] = 2_026_092_100 + index
        cell["arm_order"] = list(_ARM_ORDERS[index])
        cell["calculator_input"] = _calculator_input(cell)
        cell["expected_probe"] = calculator.calculate(cell["calculator_input"])

        oracle_value, winner_count, oracle_plan = _oracle(cell)
        exhaustive = [
            (_simulate(cell, plan), plan)
            for plan in itertools.product((0, 1), repeat=cell["horizon"])
        ]
        exhaustive_value = max(value for value, _plan in exhaustive)
        exhaustive_winners = sorted(
            plan for value, plan in exhaustive if value == exhaustive_value
        )
        myopic_plan = _myopic(cell)
        myopic_value = _simulate(cell, myopic_plan)
        dependent = _future_dependent_rounds(cell, oracle_plan)
        _require(
            winner_count == len(exhaustive_winners) == 1
            and oracle_plan == exhaustive_winners[0]
            and oracle_value == exhaustive_value
            and oracle_value > myopic_value
            and bool(dependent),
            "calibration cell is not uniquely future-dependent",
        )
        cell["controls"] = {
            "oracle_plan": list(oracle_plan),
            "oracle_plan_sha256": _sha(_canonical(list(oracle_plan))),
            "oracle_utility": _rational(oracle_value),
            "myopic_plan": list(myopic_plan),
            "myopic_utility": _rational(myopic_value),
            "myopic_regret": _rational(oracle_value - myopic_value),
            "future_dependent_rounds_1_indexed": dependent,
            "exhaustive_sequences": 2 ** cell["horizon"],
            "dp_matches_exhaustive": True,
        }
        rows.append(cell)

    _require(len(rows) == UNITS, "calibration unit count differs")
    _require({row["horizon"] for row in rows} == {4, 6, 9, 12}, "horizon drift")
    _require({row["focal_seat"] for row in rows} == set(range(4)), "seat drift")
    _require(
        {row["probe"]["focal_action"] for row in rows} == {0, 1},
        "probe focal-action coverage differs",
    )
    _require(
        {row["probe"]["other_contributors"] for row in rows} == set(range(4)),
        "probe contributor coverage differs",
    )
    # The disjoint endowments make these cells distinct from the developmental
    # primary panel, old confirmatory/shakedown panels, and E=5 pilot.
    _require(
        {row["endowment"] for row in rows} == {6, 10, 14, 18}
        and not {6, 10, 14, 18}.intersection({4, 5, 7, 8, 9, 11, 12, 13, 16, 20}),
        "calibration overlaps a known prior or proposed panel",
    )
    task_hashes = {row["task_sha256"] for row in rows}
    old_assistance_hashes = {
        row["task_sha256"]
        for cohort in ("shakedown", "confirmatory")
        for row in assistance.panel(cohort)
    }
    _require(
        len(_DEVELOPMENTAL_PRIMARY_TASK_HASHES) == 30
        and not task_hashes.intersection(_DEVELOPMENTAL_PRIMARY_TASK_HASHES)
        and not task_hashes.intersection(old_assistance_hashes),
        "calibration task hash overlaps a prior or developmental panel",
    )
    return rows


def _declared_slots(rows: list[dict[str, Any]]) -> list[str]:
    suffixes = (
        "direct",
        "table_first",
        "table_final",
        "calculator_first",
        "calculator_final",
    )
    return [f"{row['cell_id']}/{suffix}" for row in rows for suffix in suffixes]


def _messages(cell: dict[str, Any], arm: str) -> list[dict[str, Any]]:
    _require(arm in {"direct", "table", "calculator"}, "unknown arm")
    system = (
        "Plan a finite four-player public-goods game. In each round action 1 "
        "contributes all E and action 0 retains it. For k=sum(joint_action), "
        "shared=m*E*k/4 and player i receives E*(1-action_i)+shared. The other "
        "three players contribute while the consecutive focal-retention count is "
        "below threshold K. A focal contribution resets that count to zero. Once "
        "K consecutive focal retentions occur, punishment is absorbing and all "
        "three retain thereafter. Maximize cumulative focal payoff. The arithmetic "
        "probe is independent of the strategic trajectory. " + FINAL_RESPONSE_CONTRACT
    )
    user = (
        f"E={cell['endowment']}; m={cell['multiplier']}; focal seat="
        f"{cell['focal_seat']}; threshold K={cell['rule_parameter']}; horizon="
        f"{cell['horizon']}. Probe joint_action in seat order 0..3="
        f"{cell['probe']['joint_action']}. Give its exact probe output, then the "
        "separate strategic action plan."
    )
    if arm == "table":
        user += (
            " First call public_goods_payoff_table exactly once with E, m_num, "
            "m_den, players=4. Do not answer before the tool result."
        )
    elif arm == "calculator":
        user += (
            " First call public_goods_joint_action_payoff exactly once with E, "
            "m_num, m_den, the exact probe joint_action, and focal_seat. Do not "
            "answer before the tool result."
        )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _tool_spec(arm: str) -> dict[str, Any]:
    return TABLE_TOOL_SPEC if arm == "table" else CALCULATOR_TOOL_SPEC


def _tool_arguments(cell: dict[str, Any], arm: str) -> dict[str, Any]:
    if arm == "table":
        return {
            "E": cell["endowment"],
            "m_num": cell["m_num"],
            "m_den": cell["m_den"],
            "players": PLAYERS,
        }
    return copy.deepcopy(cell["calculator_input"])


def _tool_payload(cell: dict[str, Any], arm: str) -> dict[str, Any]:
    if arm == "table":
        return assistance._tool_payload(cell)
    return calculator.calculate(cell["calculator_input"])


def _grade_tool(
    status: str,
    receipt: dict[str, Any] | None,
    tool_calls: Any,
    content: str | None,
    cell: dict[str, Any],
    arm: str,
) -> dict[str, Any]:
    result = {
        "single_tool_call": False,
        "arguments_valid": False,
        "arguments_exact": False,
        "tool_executed": False,
        "failure_code": None,
    }
    if status != "returned":
        result["failure_code"] = status
        return result
    if not isinstance(tool_calls, (list, tuple)) or len(tool_calls) != 1:
        result["failure_code"] = "no_single_tool_call"
        return result
    call = tool_calls[0]
    name = _tool_spec(arm)["function"]["name"]
    if (
        not isinstance(call, dict)
        or set(call) != {"id", "type", "function"}
        or call.get("type") != "function"
        or not isinstance(call.get("id"), str)
        or not call["id"]
        or not isinstance(call.get("function"), dict)
        or set(call["function"]) != {"name", "arguments"}
        or call["function"].get("name") != name
        or not isinstance(call["function"].get("arguments"), str)
    ):
        result["failure_code"] = "tool_shape_or_name"
        return result
    result["single_tool_call"] = True
    if receipt is None or receipt.get("finish_reason") != "tool_calls" or content:
        result["failure_code"] = "tool_incomplete_or_bypass"
        return result
    try:
        arguments = transport._strict_json(call["function"]["arguments"])
    except (TypeError, ValueError):
        result["failure_code"] = "arguments_json"
        return result
    try:
        if arm == "calculator":
            calculator.calculate(arguments)
        else:
            _require(
                isinstance(arguments, dict)
                and set(arguments) == {"E", "m_num", "m_den", "players"}
                and all(type(value) is int for value in arguments.values())
                and arguments["E"] > 0
                and arguments["m_num"] > 0
                and arguments["m_den"] > 0
                and arguments["players"] == PLAYERS,
                "table arguments malformed",
            )
    except (CalibrationError, calculator.PayoffCalculatorError):
        result["failure_code"] = "arguments_shape"
        return result
    result["arguments_valid"] = True
    if arguments != _tool_arguments(cell, arm):
        result["failure_code"] = "arguments_wrong"
        return result
    result.update(arguments_exact=True, tool_executed=True)
    return result


def _final_messages(
    cell: dict[str, Any], arm: str, call: dict[str, Any], first_content: str
) -> list[dict[str, Any]]:
    return [
        *_messages(cell, arm),
        {
            "role": "assistant",
            "content": first_content,
            "tool_calls": [copy.deepcopy(call)],
        },
        {
            "role": "tool",
            "tool_call_id": call["id"],
            "name": _tool_spec(arm)["function"]["name"],
            "content": _canonical(_tool_payload(cell, arm)).decode(),
        },
        {
            "role": "user",
            "content": "Use the exact tool result. Return only the required bare JSON.",
        },
    ]


def _grade_final(
    content: str | None,
    status: str,
    cell: dict[str, Any],
    *,
    finish_reason: str | None = None,
    tool_calls: Any = (),
) -> dict[str, Any]:
    terminal_valid = status == "returned" and finish_reason == "stop" and not tool_calls
    score = calculator.score_response(
        content if status == "returned" else None,
        expected_input=cell["calculator_input"],
        expected_horizon=cell["horizon"],
    )
    observed_utility = None
    regret = None
    normalized_regret = None
    zero_regret = False
    at_least_myopic = False
    if score["action_scoreable"]:
        observed = _simulate(cell, tuple(score["actions"]))
        oracle = Fraction(cell["controls"]["oracle_utility"])
        observed_regret = oracle - observed
        _require(observed_regret >= 0, "frozen exact oracle was exceeded")
        observed_utility = _rational(observed)
        regret = _rational(observed_regret)
        normalized_regret = _rational(
            observed_regret / (cell["endowment"] * cell["horizon"])
        )
        zero_regret = observed_regret == 0
        at_least_myopic = observed_regret <= Fraction(cell["controls"]["myopic_regret"])
    return {
        "transport_returned": status == "returned",
        "terminal_valid": terminal_valid,
        "final_accepted": terminal_valid and score["strict_contract_valid"],
        "response_score": score,
        "observed_utility": observed_utility,
        "oracle_utility": cell["controls"]["oracle_utility"],
        "regret": regret,
        "normalized_regret": normalized_regret,
        "zero_regret": zero_regret,
        "at_least_myopic": at_least_myopic,
        "oracle_plan_sha256": cell["controls"]["oracle_plan_sha256"],
    }


def make_plan(
    plan_path: str | Path,
    *,
    study_id: str,
    artifact_root: str | Path = ARTIFACT_ROOT,
    runtime_snapshot_fn: Callable[[], dict[str, Any]] = resident._live_runtime_binding,
    ready_fn: Callable[[], bool] = resident._ready,
    memory_fn: Callable[[], float] = resident._available_gib,
) -> dict[str, Any]:
    """Freeze a fresh excluded calibration plan without issuing model calls."""

    _require(
        re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}", study_id) is not None,
        "study ID is malformed",
    )
    rows = panel()
    runtime_binding = runtime_snapshot_fn()
    resident._validate_runtime_binding(runtime_binding)
    _require(ready_fn(), "resident Flash is not ready")
    _require(float(memory_fn()) >= MEMORY_FLOOR_GIB, "20 GiB memory floor unavailable")
    root = Path(artifact_root).resolve(strict=False)
    path = resident._artifact_path(
        Path(plan_path), root, label="payoff action calibration plan"
    )
    slots = _declared_slots(rows)
    conditions = [f"{row['cell_id']}/{arm}" for row in rows for arm in row["arm_order"]]
    plan_value = {
        "schema_version": PLAN_SCHEMA,
        "study_id": study_id,
        "cohort": "permanently_excluded_calibration",
        "code_root": str(CODE_ROOT),
        "runtime_binding": runtime_binding,
        "source_sha256": _sources(),
        "source_design": {
            "primary_panel_sha256": SOURCE_PRIMARY_PANEL_SHA256,
            "calibration_cells_artifact_sha256": SOURCE_CALIBRATION_ARTIFACT_SHA256,
        },
        "scenarios": rows,
        "panel_sha256": _sha(_canonical(rows)),
        "declared_units": [row["cell_id"] for row in rows],
        "declared_conditions": conditions,
        "declared_slots": slots,
        "policy_id": POLICY_ID,
        "policy": copy.deepcopy(POLICY),
        "tool_specs": {
            "table": copy.deepcopy(TABLE_TOOL_SPEC),
            "calculator": copy.deepcopy(CALCULATOR_TOOL_SPEC),
        },
        "limits": {
            "max_tokens": MAX_TOKENS,
            "call_timeout_s": CALL_TIMEOUT_S,
            "evaluator_budget_s": EVALUATOR_BUDGET_S,
            "memory_floor_gib": MEMORY_FLOOR_GIB,
            "max_units": UNITS,
            "conditions": CONDITIONS,
            "max_calls": MAX_CALLS,
        },
        "unit_contract": {
            "unit": "distinct_scenario_paired_across_three_arms",
            "count": UNITS,
            "all_units_future_dependent": True,
            "requests_are_units": False,
            "rounds_are_units": False,
            "iid_population_claim": False,
            "pooled_with_any_study": False,
        },
        "coordination": {
            "mode": "exclusive_nonblocking_once",
            "cooperative_exclusion_only": True,
            "direct_http_clients_excluded": False,
            "isolated_latency_claim": False,
        },
        "budget": {
            "weekly_two_hour_debit": False,
            "authorization": "owner-authorized-current-local-research-session",
        },
        "artifact_policy": {
            "private_root": str(root),
            "outside_git_required": True,
            "directory_mode": "0700",
        },
        "claim_limit": CLAIM_LIMIT,
        "permanently_excluded": True,
        "scientific_admission_eligible": False,
        "scientific_admission_registered": False,
        "confirmation_authorized": False,
        "production_change_authorized": False,
        "promotion_authorized": False,
    }
    _require(
        len(rows) == UNITS
        and len(conditions) == CONDITIONS
        and len(slots) == MAX_CALLS,
        "calibration denominator drift",
    )
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    root.chmod(0o700)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(_canonical(plan_value) + b"\n")
    return plan_value


def load_plan(plan_path: str | Path) -> tuple[dict[str, Any], str]:
    plan_value, raw = resident._read_object(
        Path(plan_path), label="payoff action calibration plan", ceiling=6_000_000
    )
    expected_keys = {
        "schema_version",
        "study_id",
        "cohort",
        "code_root",
        "runtime_binding",
        "source_sha256",
        "source_design",
        "scenarios",
        "panel_sha256",
        "declared_units",
        "declared_conditions",
        "declared_slots",
        "policy_id",
        "policy",
        "tool_specs",
        "limits",
        "unit_contract",
        "coordination",
        "budget",
        "artifact_policy",
        "claim_limit",
        "permanently_excluded",
        "scientific_admission_eligible",
        "scientific_admission_registered",
        "confirmation_authorized",
        "production_change_authorized",
        "promotion_authorized",
    }
    _require(
        set(plan_value) == expected_keys
        and plan_value.get("schema_version") == PLAN_SCHEMA,
        "plan shape or schema differs",
    )
    rows = panel()
    conditions = [f"{row['cell_id']}/{arm}" for row in rows for arm in row["arm_order"]]
    _require(plan_value.get("source_sha256") == _sources(), "source drift")
    _require(
        plan_value.get("source_design")
        == {
            "primary_panel_sha256": SOURCE_PRIMARY_PANEL_SHA256,
            "calibration_cells_artifact_sha256": SOURCE_CALIBRATION_ARTIFACT_SHA256,
        },
        "source design binding differs",
    )
    _require(plan_value.get("scenarios") == rows, "scenario panel drift")
    _require(
        plan_value.get("panel_sha256") == _sha(_canonical(rows)),
        "panel digest drift",
    )
    _require(
        plan_value.get("declared_units") == [row["cell_id"] for row in rows]
        and plan_value.get("declared_conditions") == conditions
        and plan_value.get("declared_slots") == _declared_slots(rows),
        "declared denominator drift",
    )
    _require(
        plan_value.get("policy_id") == POLICY_ID
        and plan_value.get("policy") == POLICY
        and plan_value.get("tool_specs")
        == {"table": TABLE_TOOL_SPEC, "calculator": CALCULATOR_TOOL_SPEC},
        "policy or tool contract drift",
    )
    _require(
        plan_value.get("limits")
        == {
            "max_tokens": MAX_TOKENS,
            "call_timeout_s": CALL_TIMEOUT_S,
            "evaluator_budget_s": EVALUATOR_BUDGET_S,
            "memory_floor_gib": MEMORY_FLOOR_GIB,
            "max_units": UNITS,
            "conditions": CONDITIONS,
            "max_calls": MAX_CALLS,
        },
        "limit drift",
    )
    _require(
        plan_value.get("unit_contract")
        == {
            "unit": "distinct_scenario_paired_across_three_arms",
            "count": UNITS,
            "all_units_future_dependent": True,
            "requests_are_units": False,
            "rounds_are_units": False,
            "iid_population_claim": False,
            "pooled_with_any_study": False,
        },
        "unit contract drift",
    )
    _require(
        plan_value.get("coordination")
        == {
            "mode": "exclusive_nonblocking_once",
            "cooperative_exclusion_only": True,
            "direct_http_clients_excluded": False,
            "isolated_latency_claim": False,
        }
        and plan_value.get("budget")
        == {
            "weekly_two_hour_debit": False,
            "authorization": "owner-authorized-current-local-research-session",
        },
        "coordination or budget attribution drift",
    )
    policy = plan_value.get("artifact_policy")
    _require(
        isinstance(policy, dict)
        and set(policy) == {"private_root", "outside_git_required", "directory_mode"}
        and policy.get("outside_git_required") is True
        and policy.get("directory_mode") == "0700"
        and isinstance(policy.get("private_root"), str)
        and Path(policy["private_root"]).is_absolute(),
        "artifact policy drift",
    )
    resident._artifact_path(
        Path(plan_path), Path(policy["private_root"]), label="calibration plan"
    )
    _require(
        plan_value.get("cohort") == "permanently_excluded_calibration"
        and plan_value.get("claim_limit") == CLAIM_LIMIT
        and plan_value.get("permanently_excluded") is True
        and plan_value.get("scientific_admission_eligible") is False
        and plan_value.get("scientific_admission_registered") is False
        and plan_value.get("confirmation_authorized") is False
        and plan_value.get("production_change_authorized") is False
        and plan_value.get("promotion_authorized") is False,
        "exclusion or authority boundary drift",
    )
    _require(
        isinstance(plan_value.get("code_root"), str)
        and Path(plan_value["code_root"]).is_absolute()
        and isinstance(plan_value.get("study_id"), str)
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}", plan_value["study_id"]),
        "plan identity malformed",
    )
    resident._validate_runtime_binding(plan_value.get("runtime_binding"))
    return plan_value, _sha(raw)


@dataclass(frozen=True)
class _Call:
    status: str
    dispatch_state: str
    content: str | None
    tool_calls: tuple[dict[str, Any], ...]
    receipt: dict[str, Any]
    descriptor: dict[str, Any]


def _invoke(
    *,
    output: Path,
    ordinal: int,
    study_id: str,
    slot_id: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    seed: int,
    cancel_event: Any,
    invoke_fn: Callable[..., dict[str, Any]],
    monotonic: Callable[[], float],
) -> _Call:
    call_id = f"{study_id}/{slot_id}"
    body = transport.request_body(
        resident.ENDPOINT, messages, POLICY, MAX_TOKENS, seed, tools or None
    )
    request_sha = _sha(transport.canonical(body))
    base = {
        "call_index": ordinal,
        "call_id": call_id,
        "role": "excluded_calibration",
        "endpoint_name": resident.ENDPOINT.name,
        "served_model": resident.ENDPOINT.served_model,
        "artifact_sha256": resident.ENDPOINT.artifact_sha256,
        "policy_id": POLICY_ID,
        "resolved_policy_sha256": _sha(_canonical(POLICY)),
        "seed": seed,
        "max_tokens": MAX_TOKENS,
        "timeout_s": CALL_TIMEOUT_S,
        "messages_sha256": _sha(_canonical(messages)),
        "tools_sha256": _sha(_canonical(tools)),
        "request_sha256": request_sha,
    }
    started = monotonic()
    private_response = None
    try:
        returned = invoke_fn(
            resident.ENDPOINT,
            copy.deepcopy(messages),
            policy=copy.deepcopy(POLICY),
            max_tokens=MAX_TOKENS,
            timeout_s=CALL_TIMEOUT_S,
            seed=seed,
            tools=copy.deepcopy(tools) or None,
            cancel_event=cancel_event,
        )
        _require(isinstance(returned, dict), "transport result is not an object")
        private_response = harness._private_response(
            returned.get("private_evidence"), returned=None
        )
        _require(
            returned.get("request_sha256") == request_sha,
            "transport request digest differs",
        )
        _require(
            returned.get("response_model") == resident.ENDPOINT.served_model,
            "response model differs",
        )
        _require(
            isinstance(returned.get("content"), str)
            and isinstance(returned.get("reasoning_content"), str)
            and isinstance(returned.get("tool_calls"), list)
            and isinstance(returned.get("finish_reason"), str)
            and isinstance(returned.get("usage"), dict),
            "returned channels or terminal metadata malformed",
        )
        private_response = harness._private_response(
            returned.get("private_evidence"), returned=returned
        )
        status, dispatch_state, failure_code, error = (
            "returned",
            "confirmed_dispatched",
            None,
            None,
        )
        content = returned["content"]
        tool_calls = tuple(copy.deepcopy(returned["tool_calls"]))
        receipt = {
            **base,
            "status": status,
            "dispatch_state": dispatch_state,
            "wall_s": max(0.0, monotonic() - started),
            "response_stream_sha256": returned["response_stream_sha256"],
            "response_id": returned["response_id"],
            "response_model": returned["response_model"],
            "finish_reason": returned["finish_reason"],
            "usage": copy.deepcopy(returned["usage"]),
            "failure_code": None,
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001 - failed calls remain in denominator
        status = (
            "cancelled"
            if isinstance(exc, transport.TransportCancelled)
            else "timeout"
            if isinstance(exc, TimeoutError)
            else "error"
        )
        failure_code = (
            "transport_cancelled"
            if status == "cancelled"
            else "transport_timeout"
            if status == "timeout"
            else "transport_error"
            if isinstance(exc, transport.TransportError)
            else "unexpected_transport_error"
        )
        attached = getattr(exc, "private_evidence", None)
        if attached is not None:
            private_response = harness._private_response(attached, returned=None)
        if private_response is None:
            dispatch_state = "prewire_failure"
        elif private_response["raw_response_stream"]:
            dispatch_state = "confirmed_dispatched"
        elif isinstance(
            exc, (transport.TransportCancelled, TimeoutError, transport.TransportError)
        ):
            dispatch_state = "wire_unknown"
        else:
            dispatch_state = "prewire_failure"
        error = f"{type(exc).__name__}: {exc}"
        content, tool_calls = None, ()
        receipt = {
            **base,
            "status": status,
            "dispatch_state": dispatch_state,
            "wall_s": max(0.0, monotonic() - started),
            "response_stream_sha256": None,
            "response_id": None,
            "response_model": None,
            "finish_reason": None,
            "usage": None,
            "failure_code": failure_code,
            "error": error,
        }
    response = {
        "content": private_response["content"] if private_response else None,
        "reasoning_content": (
            private_response["reasoning_content"] if private_response else None
        ),
        "tool_calls": private_response["tool_calls"] if private_response else [],
        "response_id": private_response["response_id"] if private_response else None,
        "response_model": (
            private_response["response_model"] if private_response else None
        ),
        "finish_reason": (
            private_response["finish_reason"] if private_response else None
        ),
        "usage": private_response["usage"] if private_response else None,
        "response_stream_sha256": (
            private_response["response_stream_sha256"] if private_response else None
        ),
    }
    evidence = {
        "schema_version": PRIVATE_SCHEMA,
        "call_id": call_id,
        "call_index": ordinal,
        "role": "excluded_calibration",
        "status": status,
        "dispatch_state": dispatch_state,
        "request": {
            "endpoint_name": resident.ENDPOINT.name,
            "served_model": resident.ENDPOINT.served_model,
            "artifact_sha256": resident.ENDPOINT.artifact_sha256,
            "policy_id": POLICY_ID,
            "resolved_policy": copy.deepcopy(POLICY),
            "seed": seed,
            "max_tokens": MAX_TOKENS,
            "timeout_s": CALL_TIMEOUT_S,
            "messages": copy.deepcopy(messages),
            "tools": copy.deepcopy(tools),
            "request_sha256": request_sha,
        },
        "response": response,
        "failure_code": failure_code,
        "error": error,
        "_raw_response_stream": (
            private_response["raw_response_stream"] if private_response else None
        ),
    }
    descriptor = harness._persist_private_call(
        output, ordinal=ordinal, evidence=evidence
    )
    return _Call(status, dispatch_state, content, tool_calls, receipt, descriptor)


def _issued_slot(call: _Call, slot_id: str) -> dict[str, Any]:
    return {
        "slot_id": slot_id,
        "disposition": "returned" if call.status == "returned" else "failed",
        "status": call.status,
        "failure_code": call.receipt.get("failure_code"),
        "dispatch_state": call.dispatch_state,
        "call": call.receipt,
        "private_descriptor": call.descriptor,
    }


def _unissued_slot(slot_id: str, disposition: str, failure_code: str) -> dict[str, Any]:
    _require(
        disposition in {"skipped_unissued", "unissued_after_abort"},
        "unissued disposition invalid",
    )
    return {
        "slot_id": slot_id,
        "disposition": disposition,
        "status": "skipped" if disposition == "skipped_unissued" else "not_run",
        "failure_code": failure_code,
        "dispatch_state": "not_issued",
        "call": None,
        "private_descriptor": None,
    }


def _account(slots: list[dict[str, Any]]) -> dict[str, int]:
    counts = {
        "declared_slots": len(slots),
        "attempted_calls": 0,
        "confirmed_dispatched_calls": 0,
        "wire_unknown_attempts": 0,
        "prewire_failures": 0,
        "returned_calls": 0,
        "failed_calls": 0,
        "skipped_unissued": 0,
        "unissued_after_abort": 0,
    }
    for slot in slots:
        if slot["disposition"] in {"returned", "failed"}:
            call = slot.get("call")
            _require(
                isinstance(call, dict)
                and isinstance(slot.get("private_descriptor"), dict)
                and slot["disposition"]
                == ("returned" if call.get("status") == "returned" else "failed")
                and slot.get("status") == call.get("status")
                and slot.get("failure_code") == call.get("failure_code")
                and slot.get("dispatch_state") == call.get("dispatch_state")
                and slot["dispatch_state"]
                in {"confirmed_dispatched", "wire_unknown", "prewire_failure"},
                "issued slot does not derive from its call receipt",
            )
            counts["attempted_calls"] += 1
            counts[
                "returned_calls"
                if slot["disposition"] == "returned"
                else "failed_calls"
            ] += 1
            counts[
                {
                    "confirmed_dispatched": "confirmed_dispatched_calls",
                    "wire_unknown": "wire_unknown_attempts",
                    "prewire_failure": "prewire_failures",
                }[slot["dispatch_state"]]
            ] += 1
        else:
            _require(
                slot["disposition"] in {"skipped_unissued", "unissued_after_abort"}
                and slot.get("status")
                == (
                    "skipped"
                    if slot["disposition"] == "skipped_unissued"
                    else "not_run"
                )
                and isinstance(slot.get("failure_code"), str)
                and bool(slot["failure_code"])
                and slot.get("dispatch_state") == "not_issued"
                and slot.get("call") is None
                and slot.get("private_descriptor") is None,
                "unissued slot receipt is malformed",
            )
            counts[slot["disposition"]] += 1
    _require(
        counts["returned_calls"]
        + counts["failed_calls"]
        + counts["skipped_unissued"]
        + counts["unissued_after_abort"]
        == counts["declared_slots"],
        "slot accounting is not exhaustive",
    )
    _require(
        counts["confirmed_dispatched_calls"]
        + counts["wire_unknown_attempts"]
        + counts["prewire_failures"]
        == counts["attempted_calls"],
        "dispatch accounting is not exhaustive",
    )
    return counts


def run(
    plan_path: str | Path,
    output_dir: str | Path,
    *,
    cancel_event: Any,
    invoke_fn: Callable[..., dict[str, Any]] = transport.complete,
    runtime_snapshot_fn: Callable[[], dict[str, Any]] = resident._live_runtime_binding,
    ready_fn: Callable[[], bool] = resident._ready,
    memory_fn: Callable[[], float] = resident._available_gib,
    idle_probe_fn: Callable[[], dict[str, Any]] = resident._endpoint_idle_probe,
    lock_factory: Callable[[Path], Any] = resource_lease,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Run the excluded calibration against an unchanged warm resident."""

    plan_value, plan_sha = load_plan(plan_path)
    _require(callable(getattr(cancel_event, "is_set", None)), "cancel event missing")
    output = resident._artifact_path(
        Path(output_dir),
        Path(plan_value["artifact_policy"]["private_root"]),
        label="payoff action calibration output",
    )
    _require(not output.exists(), "output already exists")
    start = monotonic()
    deadline = start + EVALUATOR_BUDGET_S
    slots: dict[str, dict[str, Any]] = {}
    outcomes: list[dict[str, Any]] = []
    resource_observations: list[dict[str, Any]] = []
    ordinal = 0
    abort_reason: str | None = None

    def observe(stage: str, slot_id: str) -> tuple[dict[str, Any], Any]:
        row = {
            "stage": stage,
            "slot_id": slot_id,
            "ready": None,
            "memory_gib": None,
            "runtime_identity_matches": None,
            "elapsed_s": max(0.0, monotonic() - start),
            "error": None,
        }
        current = None
        try:
            ready = ready_fn()
            available = float(memory_fn())
            _require(math.isfinite(available), "memory probe is non-finite")
            current = runtime_snapshot_fn() if ready else None
            row.update(
                ready=ready,
                memory_gib=available,
                runtime_identity_matches=current == plan_value["runtime_binding"],
            )
        except Exception as exc:  # noqa: BLE001 - retained as bounded evidence
            row["error"] = f"{type(exc).__name__}:{exc}"
        resource_observations.append(row)
        return row, current

    def can_issue(slot_id: str) -> bool:
        nonlocal abort_reason
        if abort_reason is not None:
            return False
        if cancel_event.is_set():
            abort_reason = "cancelled_before_next_call"
            return False
        if deadline - monotonic() < CALL_TIMEOUT_S + 0.05:
            abort_reason = "evaluator_budget_before_next_call"
            return False
        observation, current = observe("pre_call", slot_id)
        if observation["error"] is not None:
            abort_reason = "runtime_probe_failed_before_next_call"
            return False
        if observation["ready"] is not True:
            abort_reason = "Flash_not_ready_before_next_call"
        elif observation["memory_gib"] < MEMORY_FLOOR_GIB:
            abort_reason = "memory_floor_before_next_call"
        elif current != plan_value["runtime_binding"]:
            abort_reason = "runtime_identity_changed_before_next_call"
        elif cancel_event.is_set():
            abort_reason = "cancelled_after_pre_call_probes"
        elif deadline - monotonic() < CALL_TIMEOUT_S + 0.05:
            abort_reason = "evaluator_budget_after_pre_call_probes"
        return abort_reason is None

    def issue(
        slot_id: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        seed: int,
    ) -> tuple[_Call, dict[str, Any]]:
        nonlocal ordinal, abort_reason
        call = _invoke(
            output=output,
            ordinal=ordinal,
            study_id=plan_value["study_id"],
            slot_id=slot_id,
            messages=messages,
            tools=tools,
            seed=seed,
            cancel_event=cancel_event,
            invoke_fn=invoke_fn,
            monotonic=monotonic,
        )
        ordinal += 1
        slot = _issued_slot(call, slot_id)
        post, current = observe("post_call", slot_id)
        if call.receipt.get("timeout_s") != CALL_TIMEOUT_S:
            abort_reason = f"shortened_timeout:{slot_id}"
        elif slot["dispatch_state"] == "prewire_failure":
            abort_reason = f"prewire_failure:{slot_id}"
        elif call.status == "cancelled":
            abort_reason = "transport_cancelled"
        elif post["error"] is not None:
            abort_reason = f"runtime_probe_failed_after_call:{slot_id}"
        elif post["ready"] is not True:
            abort_reason = f"Flash_not_ready_after_call:{slot_id}"
        elif post["memory_gib"] < MEMORY_FLOOR_GIB:
            abort_reason = f"memory_floor_after_call:{slot_id}"
        elif current != plan_value["runtime_binding"]:
            abort_reason = f"runtime_identity_changed_after_call:{slot_id}"
        elif cancel_event.is_set():
            abort_reason = f"cancelled_after_call:{slot_id}"
        elif deadline - monotonic() < 0:
            abort_reason = f"evaluator_budget_after_call:{slot_id}"
        return call, slot

    with lock_factory(resident.CANONICAL_ROOT):
        _require(plan_value["source_sha256"] == _sources(), "source changed")
        _require(
            ready_fn() and float(memory_fn()) >= MEMORY_FLOOR_GIB,
            "resident Flash or memory floor unavailable",
        )
        _require(
            runtime_snapshot_fn() == plan_value["runtime_binding"],
            "runtime identity changed after plan freeze",
        )
        contention = idle_probe_fn()
        resident._validate_idle_observation(contention)
        _require(contention["observed_idle"] is True, "endpoint busy before start")
        _require(not cancel_event.is_set(), "calibration cancelled during admission")
        output.mkdir(mode=0o700, parents=True)
        output.chmod(0o700)

        for cell in plan_value["scenarios"]:
            for arm in cell["arm_order"]:
                calls: list[dict[str, Any]] = []
                descriptors: list[dict[str, Any]] = []
                tool_grade = None
                if arm == "direct":
                    slot_id = f"{cell['cell_id']}/direct"
                    if can_issue(slot_id):
                        call, slot = issue(
                            slot_id, _messages(cell, arm), [], cell["seed"]
                        )
                        slots[slot_id] = slot
                        calls.append(call.receipt)
                        descriptors.append(call.descriptor)
                        final_grade = _grade_final(
                            call.content,
                            call.status,
                            cell,
                            finish_reason=call.receipt.get("finish_reason"),
                            tool_calls=call.tool_calls,
                        )
                    else:
                        slots[slot_id] = _unissued_slot(
                            slot_id, "unissued_after_abort", abort_reason or "aborted"
                        )
                        final_grade = _grade_final(None, "not_run", cell)
                else:
                    first_id = f"{cell['cell_id']}/{arm}_first"
                    final_id = f"{cell['cell_id']}/{arm}_final"
                    first = None
                    if can_issue(first_id):
                        first, first_slot = issue(
                            first_id,
                            _messages(cell, arm),
                            [copy.deepcopy(_tool_spec(arm))],
                            cell["seed"],
                        )
                        slots[first_id] = first_slot
                        calls.append(first.receipt)
                        descriptors.append(first.descriptor)
                        tool_grade = _grade_tool(
                            first.status,
                            first.receipt,
                            first.tool_calls,
                            first.content,
                            cell,
                            arm,
                        )
                    else:
                        slots[first_id] = _unissued_slot(
                            first_id,
                            "unissued_after_abort",
                            abort_reason or "aborted",
                        )
                        tool_grade = _grade_tool("not_run", None, (), None, cell, arm)
                    final_grade = _grade_final(None, "skipped", cell)
                    if (
                        first is not None
                        and tool_grade["tool_executed"]
                        and can_issue(final_id)
                    ):
                        final, final_slot = issue(
                            final_id,
                            _final_messages(
                                cell, arm, first.tool_calls[0], first.content or ""
                            ),
                            [],
                            cell["seed"],
                        )
                        slots[final_id] = final_slot
                        calls.append(final.receipt)
                        descriptors.append(final.descriptor)
                        final_grade = _grade_final(
                            final.content,
                            final.status,
                            cell,
                            finish_reason=final.receipt.get("finish_reason"),
                            tool_calls=final.tool_calls,
                        )
                    elif abort_reason is not None:
                        slots[final_id] = _unissued_slot(
                            final_id, "unissued_after_abort", abort_reason
                        )
                    else:
                        slots[final_id] = _unissued_slot(
                            final_id,
                            "skipped_unissued",
                            str(tool_grade["failure_code"] or "tool_not_executed"),
                        )
                details = {
                    "final": final_grade,
                    "_private_call_evidence": {
                        "schema_version": harness.PRIVATE_INDEX_SCHEMA,
                        "artifacts": descriptors,
                    },
                }
                if tool_grade is not None:
                    details["tool"] = tool_grade
                outcomes.append(
                    {
                        "cell_id": cell["cell_id"],
                        "arm": arm,
                        "calls": calls,
                        "grade": details,
                    }
                )

        if cancel_event.is_set() and abort_reason is None:
            abort_reason = "cancelled_after_last_call"
        for slot_id in plan_value["declared_slots"]:
            slots.setdefault(
                slot_id,
                _unissued_slot(
                    slot_id, "unissued_after_abort", abort_reason or "not_reached"
                ),
            )
        present = {(row["cell_id"], row["arm"]) for row in outcomes}
        for cell in plan_value["scenarios"]:
            for arm in cell["arm_order"]:
                if (cell["cell_id"], arm) in present:
                    continue
                details = {
                    "final": _grade_final(None, "not_run", cell),
                    "_private_call_evidence": {
                        "schema_version": harness.PRIVATE_INDEX_SCHEMA,
                        "artifacts": [],
                    },
                }
                if arm != "direct":
                    details["tool"] = _grade_tool("not_run", None, (), None, cell, arm)
                outcomes.append(
                    {
                        "cell_id": cell["cell_id"],
                        "arm": arm,
                        "calls": [],
                        "grade": details,
                    }
                )
        order = {
            (cell["cell_id"], arm): index
            for index, (cell, arm) in enumerate(
                (cell, arm)
                for cell in plan_value["scenarios"]
                for arm in cell["arm_order"]
            )
        }
        outcomes.sort(key=lambda row: order[(row["cell_id"], row["arm"])])
        ordered_slots = [slots[slot_id] for slot_id in plan_value["declared_slots"]]
        accounting = _account(ordered_slots)
        _require(accounting["attempted_calls"] <= MAX_CALLS, "call budget exceeded")
        status = "aborted" if abort_reason is not None else "complete"
        result = {
            "schema_version": RUN_SCHEMA,
            "status": status,
            "study_id": plan_value["study_id"],
            "cohort": plan_value["cohort"],
            "plan_raw_sha256": plan_sha,
            "runtime_binding": copy.deepcopy(plan_value["runtime_binding"]),
            "declared_units": plan_value["declared_units"],
            "declared_conditions": plan_value["declared_conditions"],
            "declared_slots": plan_value["declared_slots"],
            "slots": ordered_slots,
            "outcomes": outcomes,
            "accounting": accounting,
            "contention_observation": contention,
            "resource_observations": resource_observations,
            "abort_reason": abort_reason,
            "elapsed_s": max(0.0, monotonic() - start),
            "weekly_two_hour_debit": False,
            "permanently_excluded": True,
            "scientific_admission_eligible": False,
            "scientific_admission_registered": False,
            "confirmation_authorized": False,
            "production_change_authorized": False,
            "promotion_authorized": False,
            "claim_limit": CLAIM_LIMIT,
            "private_content_exported": False,
        }
        with (output / "run.json").open("xb") as stream:
            stream.write(_canonical(result) + b"\n")
        return result


def _metadata(
    output: Path, descriptor: dict[str, Any]
) -> tuple[dict[str, Any], bytes | None]:
    _require(
        isinstance(descriptor, dict)
        and set(descriptor)
        == {
            "call_id",
            "status",
            "metadata_path",
            "metadata_sha256",
            "metadata_bytes",
            "raw_stream",
        }
        and isinstance(descriptor.get("call_id"), str)
        and bool(descriptor["call_id"])
        and isinstance(descriptor.get("status"), str),
        "private descriptor shape differs",
    )
    path = descriptor.get("metadata_path") if isinstance(descriptor, dict) else None
    _require(
        isinstance(path, str)
        and re.fullmatch(r"private/calls/[0-9]{4}-[0-9a-f]{16}\.json", path)
        is not None,
        "private metadata path invalid",
    )
    raw, _resolved = harness._read_regular_file(
        output / path, label="private calibration call", max_bytes=512_000
    )
    _require(
        _sha(raw) == descriptor.get("metadata_sha256")
        and len(raw) == descriptor.get("metadata_bytes"),
        "private metadata bytes differ",
    )
    metadata = harness._strict_object(raw, "private calibration call")
    _require(
        metadata.get("schema_version") == PRIVATE_SCHEMA
        and set(metadata)
        == {
            "schema_version",
            "call_id",
            "call_index",
            "role",
            "status",
            "dispatch_state",
            "request",
            "response",
            "failure_code",
            "error",
        },
        "private metadata schema differs",
    )
    stream_descriptor = descriptor.get("raw_stream")
    stream = None
    if stream_descriptor is not None:
        _require(
            isinstance(stream_descriptor, dict)
            and set(stream_descriptor) == {"path", "sha256", "bytes"}
            and isinstance(stream_descriptor.get("path"), str)
            and re.fullmatch(
                r"private/streams/[0-9]{4}-[0-9a-f]{16}\.sse",
                stream_descriptor["path"],
            )
            is not None,
            "private stream descriptor differs",
        )
        _require(
            Path(stream_descriptor["path"]).stem == Path(path).stem,
            "private metadata and stream identity differ",
        )
        try:
            stream = private_evidence._recorded(
                output / stream_descriptor["path"],
                label="private calibration SSE",
                ceiling=transport.MAX_RESPONSE_BYTES,
                digest=stream_descriptor["sha256"],
                count=stream_descriptor["bytes"],
                allow_empty_transport=True,
            )
        except private_evidence.PrivateEvidenceError as exc:
            raise CalibrationError(f"private SSE bytes differ: {exc}") from exc
    _require(
        metadata.get("response", {}).get("raw_stream_artifact") == stream_descriptor,
        "private response/stream binding differs",
    )
    return metadata, stream


def _replay_call(
    *,
    output: Path,
    descriptor: dict[str, Any],
    call: dict[str, Any],
    slot: dict[str, Any],
    plan_value: dict[str, Any],
    cell: dict[str, Any],
    slot_id: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> tuple[dict[str, Any], bool]:
    metadata, raw_stream = _metadata(output, descriptor)
    expected_call_keys = {
        "call_index",
        "call_id",
        "role",
        "endpoint_name",
        "served_model",
        "artifact_sha256",
        "policy_id",
        "resolved_policy_sha256",
        "seed",
        "max_tokens",
        "timeout_s",
        "messages_sha256",
        "tools_sha256",
        "request_sha256",
        "status",
        "dispatch_state",
        "wall_s",
        "response_stream_sha256",
        "response_id",
        "response_model",
        "finish_reason",
        "usage",
        "failure_code",
        "error",
    }
    _require(
        set(call) == expected_call_keys
        and type(call.get("call_index")) is int
        and call["call_index"] >= 0
        and type(call.get("wall_s")) in {int, float}
        and math.isfinite(float(call["wall_s"]))
        and 0 <= float(call["wall_s"]) <= CALL_TIMEOUT_S + 5,
        "public call receipt differs",
    )
    request = metadata.get("request")
    response = metadata.get("response")
    _require(
        isinstance(request, dict) and isinstance(response, dict), "private call absent"
    )
    _require(
        request.get("messages") == messages
        and request.get("tools") == tools
        and request.get("resolved_policy") == POLICY
        and request.get("seed") == cell["seed"]
        and request.get("max_tokens") == MAX_TOKENS
        and request.get("timeout_s") == CALL_TIMEOUT_S
        and request.get("endpoint_name") == resident.ENDPOINT.name
        and request.get("served_model") == resident.ENDPOINT.served_model
        and request.get("artifact_sha256") == resident.ENDPOINT.artifact_sha256
        and request.get("policy_id") == POLICY_ID,
        "private frozen request differs",
    )
    expected_body = transport.request_body(
        resident.ENDPOINT,
        messages,
        POLICY,
        MAX_TOKENS,
        cell["seed"],
        tools or None,
    )
    _require(
        request.get("request_sha256") == _sha(transport.canonical(expected_body))
        and call.get("request_sha256") == request.get("request_sha256")
        and call.get("messages_sha256") == _sha(_canonical(messages))
        and call.get("tools_sha256") == _sha(_canonical(tools))
        and call.get("resolved_policy_sha256") == _sha(_canonical(POLICY)),
        "private/public request digest differs",
    )
    _require(
        call.get("endpoint_name") == resident.ENDPOINT.name
        and call.get("served_model") == resident.ENDPOINT.served_model
        and call.get("artifact_sha256") == resident.ENDPOINT.artifact_sha256
        and call.get("policy_id") == POLICY_ID
        and call.get("seed") == cell["seed"]
        and call.get("max_tokens") == MAX_TOKENS
        and call.get("timeout_s") == CALL_TIMEOUT_S,
        "public route, identity, policy, or limits differ",
    )
    _require(
        slot.get("call") == call
        and slot.get("private_descriptor") == descriptor
        and descriptor.get("call_id") == call.get("call_id")
        and descriptor.get("status") == call.get("status")
        and call.get("call_id") == f"{plan_value['study_id']}/{slot_id}"
        and call.get("role") == "excluded_calibration",
        "slot/public/private call binding differs",
    )
    _require(
        metadata.get("call_id") == call.get("call_id")
        and metadata.get("call_index") == call.get("call_index")
        and metadata.get("role") == call.get("role")
        and metadata.get("status") == call.get("status")
        and metadata.get("dispatch_state")
        == call.get("dispatch_state")
        == slot.get("dispatch_state")
        and metadata.get("failure_code") == call.get("failure_code")
        and metadata.get("error") == call.get("error"),
        "private/public response identity differs",
    )
    response_keys = (
        "response_stream_sha256",
        "response_id",
        "response_model",
        "finish_reason",
        "usage",
    )
    returned_stream = False
    if descriptor["raw_stream"] is not None:
        _require(
            descriptor["raw_stream"]["sha256"]
            == response.get("response_stream_sha256"),
            "raw stream digest differs",
        )
    if call["status"] == "returned":
        _require(
            raw_stream is not None
            and call.get("dispatch_state") == "confirmed_dispatched"
            and all(response.get(key) == call.get(key) for key in response_keys),
            "returned response receipt differs",
        )
        private_evidence._response_matches_raw(raw_stream, response, call)
        returned_stream = True
    else:
        _require(
            all(call.get(key) is None for key in response_keys),
            "failed response exported terminal receipt",
        )
        if slot["dispatch_state"] == "wire_unknown":
            _require(raw_stream == b"", "wire-unknown call lacks empty raw stream")
        elif slot["dispatch_state"] == "confirmed_dispatched":
            _require(
                raw_stream is not None and len(raw_stream) > 0,
                "confirmed failed call lacks raw bytes",
            )
        else:
            _require(raw_stream is None, "pre-wire failure has raw stream")
    return metadata, returned_stream


def _summary(
    grades: dict[str, dict[str, Any]],
    cell_ids: list[str],
    predicate: Callable[[dict[str, Any]], bool],
) -> dict[str, Any]:
    passing = [cell_id for cell_id in cell_ids if predicate(grades[cell_id])]
    return {
        "passed": len(passing),
        "denominator": len(cell_ids),
        "passing_cells": passing,
        "failed_cells": [cell_id for cell_id in cell_ids if cell_id not in passing],
    }


def validate(plan_path: str | Path, output_dir: str | Path) -> dict[str, Any]:
    """Replay private SSE, requests, tools, exact controls, and all grades."""

    plan_value, plan_sha = load_plan(plan_path)
    output = resident._artifact_path(
        Path(output_dir),
        Path(plan_value["artifact_policy"]["private_root"]),
        label="payoff action calibration output",
    )
    run_value, run_raw = resident._read_object(
        output / "run.json", label="payoff action calibration run", ceiling=20_000_000
    )
    expected_run_keys = {
        "schema_version",
        "status",
        "study_id",
        "cohort",
        "plan_raw_sha256",
        "runtime_binding",
        "declared_units",
        "declared_conditions",
        "declared_slots",
        "slots",
        "outcomes",
        "accounting",
        "contention_observation",
        "resource_observations",
        "abort_reason",
        "elapsed_s",
        "weekly_two_hour_debit",
        "permanently_excluded",
        "scientific_admission_eligible",
        "scientific_admission_registered",
        "confirmation_authorized",
        "production_change_authorized",
        "promotion_authorized",
        "claim_limit",
        "private_content_exported",
    }
    _require(
        set(run_value) == expected_run_keys
        and run_value.get("schema_version") == RUN_SCHEMA
        and run_value.get("study_id") == plan_value["study_id"]
        and run_value.get("cohort") == plan_value["cohort"]
        and run_value.get("plan_raw_sha256") == plan_sha
        and run_value.get("runtime_binding") == plan_value["runtime_binding"]
        and run_value.get("declared_units") == plan_value["declared_units"]
        and run_value.get("declared_conditions") == plan_value["declared_conditions"]
        and run_value.get("declared_slots") == plan_value["declared_slots"]
        and run_value.get("weekly_two_hour_debit") is False
        and run_value.get("permanently_excluded") is True
        and run_value.get("scientific_admission_eligible") is False
        and run_value.get("scientific_admission_registered") is False
        and run_value.get("confirmation_authorized") is False
        and run_value.get("production_change_authorized") is False
        and run_value.get("promotion_authorized") is False
        and run_value.get("claim_limit") == CLAIM_LIMIT
        and run_value.get("private_content_exported") is False,
        "run identity, denominator, or exclusion boundary differs",
    )
    _require(
        type(run_value.get("elapsed_s")) in {int, float}
        and math.isfinite(float(run_value["elapsed_s"]))
        and 0 <= float(run_value["elapsed_s"]) <= EVALUATOR_BUDGET_S + 5,
        "run elapsed time differs",
    )
    status = run_value.get("status")
    abort_reason = run_value.get("abort_reason")
    _require(
        (status == "complete" and abort_reason is None)
        or (status == "aborted" and isinstance(abort_reason, str) and abort_reason),
        "run status/abort reason differs",
    )
    resident._validate_runtime_binding(run_value.get("runtime_binding"))
    resident._validate_idle_observation(run_value.get("contention_observation"))
    _require(
        run_value["contention_observation"]["observed_idle"] is True,
        "pre-run contention admission differs",
    )
    slots = run_value.get("slots")
    _require(
        isinstance(slots, list)
        and len(slots) == MAX_CALLS
        and [slot.get("slot_id") for slot in slots] == plan_value["declared_slots"]
        and len({slot.get("slot_id") for slot in slots}) == MAX_CALLS,
        "slot denominator or ordering differs",
    )
    accounting = _account(slots)
    _require(run_value.get("accounting") == accounting, "stored accounting differs")
    _require(accounting["attempted_calls"] <= MAX_CALLS, "call budget exceeded")
    by_slot = {slot["slot_id"]: slot for slot in slots}
    if status == "complete":
        _require(
            accounting["prewire_failures"] == 0
            and accounting["unissued_after_abort"] == 0
            and accounting["returned_calls"] > 0,
            "complete run contains pre-wire, abort, or zero-return evidence",
        )
    attempted_slots = sorted(
        (
            (slot["call"]["call_index"], slot["slot_id"])
            for slot in slots
            if slot["call"] is not None
        ),
        key=lambda row: row[0],
    )
    observations = run_value.get("resource_observations")
    expected_observations = [
        (stage, slot_id)
        for _index, slot_id in attempted_slots
        for stage in ("pre_call", "post_call")
    ]
    paired_count = len(expected_observations)
    _require(
        isinstance(observations, list)
        and len(observations) in {paired_count, paired_count + 1}
        and [
            (row.get("stage"), row.get("slot_id"))
            for row in observations[:paired_count]
        ]
        == expected_observations
        and not (status == "complete" and len(observations) != paired_count),
        "resource observation coverage differs",
    )
    for row in observations:
        _require(
            isinstance(row, dict)
            and set(row)
            == {
                "stage",
                "slot_id",
                "ready",
                "memory_gib",
                "runtime_identity_matches",
                "elapsed_s",
                "error",
            }
            and type(row.get("elapsed_s")) in {int, float}
            and math.isfinite(float(row["elapsed_s"]))
            and 0 <= float(row["elapsed_s"]) <= EVALUATOR_BUDGET_S + 5,
            "resource observation shape differs",
        )
        if status == "complete":
            _require(
                row["error"] is None
                and row["ready"] is True
                and type(row["memory_gib"]) in {int, float}
                and math.isfinite(float(row["memory_gib"]))
                and row["memory_gib"] >= MEMORY_FLOOR_GIB
                and row["runtime_identity_matches"] is True,
                "complete run crossed a runtime or memory guard",
            )
    if len(observations) == paired_count + 1:
        terminal = observations[-1]
        terminal_slot = by_slot.get(terminal.get("slot_id"))
        memory = terminal.get("memory_gib")
        memory_valid = type(memory) in {int, float} and math.isfinite(float(memory))
        healthy = (
            terminal.get("error") is None
            and terminal.get("ready") is True
            and memory_valid
            and float(memory) >= MEMORY_FLOOR_GIB
            and terminal.get("runtime_identity_matches") is True
        )
        terminal_reason_matches = {
            "runtime_probe_failed_before_next_call": terminal.get("error") is not None,
            "Flash_not_ready_before_next_call": (
                terminal.get("error") is None and terminal.get("ready") is not True
            ),
            "memory_floor_before_next_call": (
                terminal.get("error") is None
                and terminal.get("ready") is True
                and memory_valid
                and float(memory) < MEMORY_FLOOR_GIB
            ),
            "runtime_identity_changed_before_next_call": (
                terminal.get("error") is None
                and terminal.get("ready") is True
                and memory_valid
                and float(memory) >= MEMORY_FLOOR_GIB
                and terminal.get("runtime_identity_matches") is False
            ),
            "cancelled_after_pre_call_probes": healthy,
            "evaluator_budget_after_pre_call_probes": healthy,
        }.get(abort_reason, False)
        _require(
            status == "aborted"
            and terminal.get("stage") == "pre_call"
            and isinstance(terminal_slot, dict)
            and terminal_slot.get("disposition") == "unissued_after_abort"
            and terminal.get("slot_id")
            not in {slot_id for _index, slot_id in attempted_slots}
            and terminal_reason_matches,
            "terminal pre-call guard observation differs",
        )
    outcomes = run_value.get("outcomes")
    expected_pairs = [
        (cell["cell_id"], arm)
        for cell in plan_value["scenarios"]
        for arm in cell["arm_order"]
    ]
    _require(
        isinstance(outcomes, list)
        and len(outcomes) == CONDITIONS
        and [(row.get("cell_id"), row.get("arm")) for row in outcomes]
        == expected_pairs,
        "condition denominator or order differs",
    )
    cell_by_id = {cell["cell_id"]: cell for cell in plan_value["scenarios"]}
    grades: dict[str, dict[str, dict[str, Any]]] = {
        arm: {} for arm in ("direct", "table", "calculator")
    }
    tool_grades: dict[str, dict[str, dict[str, Any]]] = {
        arm: {} for arm in ("table", "calculator")
    }
    call_indexes: list[int] = []
    returned_streams = 0
    descriptor_paths: set[str] = set()

    for outcome in outcomes:
        _require(
            isinstance(outcome, dict)
            and set(outcome) == {"cell_id", "arm", "calls", "grade"},
            "outcome shape differs",
        )
        cell = cell_by_id[outcome["cell_id"]]
        arm = outcome["arm"]
        calls = outcome["calls"]
        stored = outcome["grade"]
        _require(
            isinstance(calls, list)
            and isinstance(stored, dict)
            and set(stored)
            == (
                {"final", "_private_call_evidence"}
                if arm == "direct"
                else {"final", "tool", "_private_call_evidence"}
            ),
            "outcome evidence shape differs",
        )
        index = stored["_private_call_evidence"]
        _require(
            isinstance(index, dict)
            and set(index) == {"schema_version", "artifacts"}
            and index.get("schema_version") == harness.PRIVATE_INDEX_SCHEMA
            and isinstance(index.get("artifacts"), list)
            and len(index["artifacts"]) == len(calls),
            "private evidence index differs",
        )
        for descriptor in index["artifacts"]:
            path = descriptor.get("metadata_path")
            _require(path not in descriptor_paths, "private descriptor reused")
            descriptor_paths.add(path)

        if arm == "direct":
            _require(len(calls) in {0, 1}, "direct call count differs")
            if calls:
                slot_id = f"{cell['cell_id']}/direct"
                metadata, returned = _replay_call(
                    output=output,
                    descriptor=index["artifacts"][0],
                    call=calls[0],
                    slot=by_slot[slot_id],
                    plan_value=plan_value,
                    cell=cell,
                    slot_id=slot_id,
                    messages=_messages(cell, arm),
                    tools=[],
                )
                call_indexes.append(calls[0]["call_index"])
                returned_streams += int(returned)
                replayed_final = _grade_final(
                    metadata["response"]["content"],
                    calls[0]["status"],
                    cell,
                    finish_reason=calls[0].get("finish_reason"),
                    tool_calls=metadata["response"]["tool_calls"],
                )
            else:
                replayed_final = _grade_final(None, "not_run", cell)
            _require(replayed_final == stored["final"], "direct grade differs")
            grades[arm][cell["cell_id"]] = replayed_final
            continue

        _require(len(calls) in {0, 1, 2}, "tool-arm call count differs")
        first_id = f"{cell['cell_id']}/{arm}_first"
        final_id = f"{cell['cell_id']}/{arm}_final"
        if calls:
            first_metadata, returned = _replay_call(
                output=output,
                descriptor=index["artifacts"][0],
                call=calls[0],
                slot=by_slot[first_id],
                plan_value=plan_value,
                cell=cell,
                slot_id=first_id,
                messages=_messages(cell, arm),
                tools=[copy.deepcopy(_tool_spec(arm))],
            )
            call_indexes.append(calls[0]["call_index"])
            returned_streams += int(returned)
            replayed_tool = _grade_tool(
                calls[0]["status"],
                calls[0],
                first_metadata["response"]["tool_calls"],
                first_metadata["response"]["content"],
                cell,
                arm,
            )
        else:
            first_metadata = None
            replayed_tool = _grade_tool("not_run", None, (), None, cell, arm)
        _require(replayed_tool == stored["tool"], "tool grade differs")
        tool_grades[arm][cell["cell_id"]] = replayed_tool
        if len(calls) == 2:
            _require(
                replayed_tool["tool_executed"] and first_metadata is not None,
                "final call follows a non-executed tool",
            )
            final_messages = _final_messages(
                cell,
                arm,
                first_metadata["response"]["tool_calls"][0],
                first_metadata["response"]["content"] or "",
            )
            final_metadata, returned = _replay_call(
                output=output,
                descriptor=index["artifacts"][1],
                call=calls[1],
                slot=by_slot[final_id],
                plan_value=plan_value,
                cell=cell,
                slot_id=final_id,
                messages=final_messages,
                tools=[],
            )
            call_indexes.append(calls[1]["call_index"])
            returned_streams += int(returned)
            replayed_final = _grade_final(
                final_metadata["response"]["content"],
                calls[1]["status"],
                cell,
                finish_reason=calls[1].get("finish_reason"),
                tool_calls=final_metadata["response"]["tool_calls"],
            )
        else:
            _require(
                by_slot[final_id]["disposition"]
                in {"skipped_unissued", "unissued_after_abort"},
                "missing final call lacks an unissued slot",
            )
            replayed_final = _grade_final(None, "skipped", cell)
        _require(replayed_final == stored["final"], "tool-final grade differs")
        grades[arm][cell["cell_id"]] = replayed_final

    _require(
        sorted(call_indexes) == list(range(accounting["attempted_calls"])),
        "call chronology or coverage differs",
    )
    _require(
        len(call_indexes) == len(descriptor_paths) == accounting["attempted_calls"],
        "private descriptor coverage differs",
    )
    _require(
        returned_streams == accounting["returned_calls"],
        "returned raw-stream coverage differs",
    )
    cell_ids = plan_value["declared_units"]
    arm_summary = {}
    for arm in ("direct", "table", "calculator"):
        arm_summary[arm] = {
            "terminal_valid": _summary(
                grades[arm], cell_ids, lambda grade: grade["terminal_valid"] is True
            ),
            "strict_final": _summary(
                grades[arm], cell_ids, lambda grade: grade["final_accepted"] is True
            ),
            "probe_exact_arithmetic": _summary(
                grades[arm],
                cell_ids,
                lambda grade: grade["response_score"]["exact_arithmetic"] is True,
            ),
            "probe_binding": _summary(
                grades[arm],
                cell_ids,
                lambda grade: grade["response_score"]["probe_binding_valid"] is True,
            ),
            "action_scoreable": _summary(
                grades[arm],
                cell_ids,
                lambda grade: grade["response_score"]["action_scoreable"] is True,
            ),
            "zero_regret": _summary(
                grades[arm], cell_ids, lambda grade: grade["zero_regret"] is True
            ),
        }
        if arm != "direct":
            arm_summary[arm]["tool_exact"] = _summary(
                tool_grades[arm],
                cell_ids,
                lambda grade: grade["tool_executed"] is True,
            )
    validation_status = "passed" if status == "complete" else "validated_incomplete"
    return {
        "schema_version": VALIDATION_SCHEMA,
        "status": validation_status,
        "study_id": plan_value["study_id"],
        "cohort": plan_value["cohort"],
        "plan_raw_sha256": plan_sha,
        "run_raw_sha256": _sha(run_raw),
        "raw_sse_replay_passed": True,
        "request_replay_passed": True,
        "tool_replay_passed": True,
        "grade_replay_passed": True,
        "exact_control_replay_passed": True,
        "accounting": accounting,
        "objective_summary": {
            "derived_from_independent_raw_replay": True,
            "finite_excluded_panel": True,
            "iid_population_claim": False,
            "model_quality_claim": False,
            "denominators": {
                "distinct_scenario_units": UNITS,
                "conditions": CONDITIONS,
                "max_call_slots": MAX_CALLS,
                **accounting,
            },
            "arms": arm_summary,
        },
        "private_calls_verified": {
            "calls": len(call_indexes),
            "returned_streams": returned_streams,
        },
        "permanently_excluded": True,
        "scientific_admission_eligible": False,
        "scientific_admission_reason": "permanently_excluded_calibration",
        "confirmation_authorized": False,
        "production_change_authorized": False,
        "promotion_authorized": False,
        "weekly_two_hour_debit": False,
        "private_content_exported": False,
        "claim_limit": CLAIM_LIMIT,
    }


def _cancel_event() -> threading.Event:
    event = threading.Event()
    for number in (signal.SIGINT, signal.SIGTERM):
        signal.signal(number, lambda *_args, target=event: target.set())
    return event


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--prepare", metavar="PLAN")
    action.add_argument("--run", metavar="PLAN")
    action.add_argument("--validate", metavar="PLAN")
    parser.add_argument("--output")
    parser.add_argument("--study-id")
    args = parser.parse_args(argv)
    if args.prepare:
        _require(
            args.output is None and args.study_id,
            "--prepare requires --study-id only",
        )
        result = make_plan(args.prepare, study_id=args.study_id)
    elif args.run:
        _require(
            args.output and args.study_id is None,
            "--run requires --output and reads identity from plan",
        )
        result = run(args.run, args.output, cancel_event=_cancel_event())
    else:
        _require(
            args.output and args.study_id is None,
            "--validate requires --output and reads identity from plan",
        )
        result = validate(args.validate, args.output)
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
