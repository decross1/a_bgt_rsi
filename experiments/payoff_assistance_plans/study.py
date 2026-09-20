"""Source-frozen repeated-game payoff-assistance study for resident Flash.

The runner uses an already-running service.  It never starts, stops, or
reconfigures model serving, and it never promotes a scientific evidence rung.
"""

from __future__ import annotations

import argparse
import copy
import functools
import hashlib
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
from experiments.payoff_tool_arithmetic import flash_resident as resident
from orchestrator.weekly_upgrade_trial import resource_lease

CODE_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_ROOT = Path(
    "/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-20/payoff-assistance-plans"
)
PLAN_SCHEMA = "flash-payoff-assistance-plan/v1"
RUN_SCHEMA = "flash-payoff-assistance-run/v1"
VALIDATION_SCHEMA = "flash-payoff-assistance-validation/v1"
PRIVATE_SCHEMA = "flash-payoff-assistance-private-call/v1"
POLICY_ID = "plan_deterministic_no_thinking"
POLICY = {"temperature": 0, "top_p": 1, "top_k": 64, "enable_thinking": False}
MAX_TOKENS = 256
CALL_TIMEOUT_S = 30.0
EVALUATOR_BUDGET_S = 3600.0
MEMORY_FLOOR_GIB = 20.0
HORIZON = 8
PLAYERS = 4
CONFIRMATORY_N = 30
SHAKEDOWN_N = 3
CLAIM_LIMIT = (
    "finite-panel payoff-assistance comprehension and exact plan-regret study; "
    "no IID population, significance, L2, strategy, market, production, or "
    "model-upgrade claim"
)
RESEARCH_CONTEXT = {
    "source_iteration_id": "iter-2026-09-15-007",
    "source_campaign": "v2-utility-mechanism-followon-20260915",
    "prior_pilot_units": 12,
    "relationship": "motivation_only_until_separately_registered",
    "claim_binding": False,
}
SOURCE_PATHS = (
    "experiments/payoff_assistance_plans/study.py",
    "experiments/payoff_assistance_plans/PREREGISTRATION.md",
    "experiments/payoff_tool_arithmetic/flash_resident.py",
    "bench/flash_next_ab/adapters.py",
    "bench/flash_next_ab/harness.py",
    "bench/flash_next_ab/transport.py",
    "bench/flash_next_ab/private_evidence.py",
    "bench/flash_next_ab/manifest.py",
    "bench/flash_next_ab/qualification.py",
    "agent_wrapper/deployment.py",
    "orchestrator/flash_resident.py",
    "orchestrator/weekly_upgrade_trial.py",
)
CONFIRMATORY_MULTIPLIERS = (
    "6/5",
    "5/4",
    "4/3",
    "7/5",
    "3/2",
    "8/5",
    "5/3",
    "7/4",
    "9/5",
    "11/6",
    "2",
    "13/6",
    "11/5",
    "9/4",
    "7/3",
    "12/5",
    "5/2",
    "8/3",
    "11/4",
    "14/5",
    "17/6",
    "3",
    "19/6",
    "13/4",
    "10/3",
    "7/2",
    "18/5",
    "11/3",
    "15/4",
    "19/5",
)
SHAKEDOWN_MULTIPLIERS = ("7/6", "23/10", "29/8")

TOOL_SPEC = {
    "type": "function",
    "function": {
        "name": "public_goods_payoff_table",
        "description": (
            "Return exact focal and group payoffs for both focal actions and "
            "each possible count of other contributors. It gives no strategy."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "E": {"type": "integer", "minimum": 1},
                "m_num": {"type": "integer", "minimum": 1},
                "m_den": {"type": "integer", "minimum": 1},
                "players": {"type": "integer", "enum": [PLAYERS]},
            },
            "required": ["E", "m_num", "m_den", "players"],
            "additionalProperties": False,
        },
    },
}


class PayoffAssistanceError(ValueError):
    """The frozen study contract or its evidence is invalid."""


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise PayoffAssistanceError(reason)


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sources() -> dict[str, str]:
    return {path: _sha((CODE_ROOT / path).read_bytes()) for path in SOURCE_PATHS}


def _rational(value: Fraction) -> str:
    return (
        str(value.numerator)
        if value.denominator == 1
        else f"{value.numerator}/{value.denominator}"
    )


def _parse_rational(value: Any) -> Fraction | None:
    if (
        not isinstance(value, str)
        or re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:/[1-9][0-9]*)?", value) is None
    ):
        return None
    try:
        result = Fraction(value)
    except (ValueError, ZeroDivisionError):
        return None
    return result if _rational(result) == value else None


def _joint_actions(
    scenario: dict[str, Any], focal_action: int, triggered: bool
) -> tuple[int, ...]:
    script = scenario["opponent_script"]
    if script == "retainers":
        other = 0
    elif script == "contributors":
        other = 1
    elif script == "grim":
        other = 0 if triggered else 1
    else:  # protected by the frozen panel check
        raise PayoffAssistanceError("unknown opponent script")
    actions = [other] * PLAYERS
    actions[scenario["focal_seat"]] = focal_action
    return tuple(actions)


def _round_payoffs(
    actions: tuple[int, ...], *, endowment: int, multiplier: Fraction
) -> tuple[Fraction, ...]:
    _require(
        len(actions) == PLAYERS
        and all(type(action) is int and action in (0, 1) for action in actions),
        "four binary actions required",
    )
    shared = multiplier * endowment * sum(actions) / PLAYERS
    return tuple(Fraction(endowment * (1 - action)) + shared for action in actions)


def _round_objective(scenario: dict[str, Any], actions: tuple[int, ...]) -> Fraction:
    values = _round_payoffs(
        actions,
        endowment=scenario["endowment"],
        multiplier=Fraction(scenario["m_num"], scenario["m_den"]),
    )
    if scenario["objective"] == "own_payoff":
        return values[scenario["focal_seat"]]
    return sum(values, Fraction())


def _simulate(scenario: dict[str, Any], plan: tuple[int, ...]) -> dict[str, Any]:
    _require(
        len(plan) == HORIZON
        and all(type(action) is int and action in (0, 1) for action in plan),
        "an eight-action binary plan is required",
    )
    triggered = False
    focal_total = Fraction()
    group_total = Fraction()
    objective_total = Fraction()
    rounds: list[list[int]] = []
    for focal_action in plan:
        actions = _joint_actions(scenario, focal_action, triggered)
        values = _round_payoffs(
            actions,
            endowment=scenario["endowment"],
            multiplier=Fraction(scenario["m_num"], scenario["m_den"]),
        )
        focal_total += values[scenario["focal_seat"]]
        group_total += sum(values, Fraction())
        objective_total += (
            values[scenario["focal_seat"]]
            if scenario["objective"] == "own_payoff"
            else sum(values, Fraction())
        )
        rounds.append(list(actions))
        if scenario["opponent_script"] == "grim" and focal_action == 0:
            triggered = True
    return {
        "focal": focal_total,
        "total": group_total,
        "objective": objective_total,
        "rounds": rounds,
    }


def _oracle(scenario: dict[str, Any]) -> tuple[Fraction, int, tuple[int, ...]]:
    @functools.cache
    def solve(
        round_index: int, triggered: bool
    ) -> tuple[Fraction, int, tuple[int, ...]]:
        if round_index == HORIZON:
            return Fraction(), 1, ()
        candidates = []
        for action in (0, 1):
            actions = _joint_actions(scenario, action, triggered)
            next_triggered = triggered or (
                scenario["opponent_script"] == "grim" and action == 0
            )
            future, count, suffix = solve(round_index + 1, next_triggered)
            candidates.append(
                (_round_objective(scenario, actions) + future, count, (action, *suffix))
            )
        best_value = max(row[0] for row in candidates)
        best = [row for row in candidates if row[0] == best_value]
        return best_value, sum(row[1] for row in best), min(row[2] for row in best)

    return solve(0, False)


def _myopic(scenario: dict[str, Any]) -> tuple[int, ...]:
    result: list[int] = []
    triggered = False
    for _round in range(HORIZON):
        values = {
            action: _round_objective(
                scenario, _joint_actions(scenario, action, triggered)
            )
            for action in (0, 1)
        }
        # The tie rule is frozen to retain (0).
        action = 0 if values[0] >= values[1] else 1
        result.append(action)
        if scenario["opponent_script"] == "grim" and action == 0:
            triggered = True
    return tuple(result)


def _with_controls(base: dict[str, Any]) -> dict[str, Any]:
    scenario = copy.deepcopy(base)
    scenario["analysis_stratum"] = (
        "dynamic_strategic"
        if scenario["opponent_script"] == "grim"
        and scenario["objective"] == "own_payoff"
        else "joint_objective_control"
        if scenario["objective"] == "joint_payoff"
        else "static_opponent_control"
    )
    probe = tuple(scenario["arithmetic_probe_actions"])
    probe_values = _round_payoffs(
        probe,
        endowment=scenario["endowment"],
        multiplier=Fraction(scenario["m_num"], scenario["m_den"]),
    )
    oracle_value, oracle_count, oracle_plan = _oracle(scenario)
    myopic_plan = _myopic(scenario)
    myopic_value = _simulate(scenario, myopic_plan)["objective"]
    scenario["probe_expected"] = {
        "focal": _rational(probe_values[scenario["focal_seat"]]),
        "total": _rational(sum(probe_values, Fraction())),
    }
    scenario["controls"] = {
        "oracle_utility": _rational(oracle_value),
        "oracle_plan_count": oracle_count,
        "lexicographic_oracle_plan": list(oracle_plan),
        "myopic_plan": list(myopic_plan),
        "myopic_utility": _rational(myopic_value),
        "myopic_regret": _rational(oracle_value - myopic_value),
        "method": "exact_dynamic_program_and_deterministic_myopic_tie_retain",
    }
    scenario["task_sha256"] = _sha(_canonical(scenario))
    return scenario


def _probe_joint_actions(ordinal: int) -> list[int]:
    # Cycle through nontrivial, explicitly disclosed one-round profiles.  This
    # arithmetic probe is deliberately independent of opponent state/lookahead.
    value = (ordinal * 5 + 3) % 14 + 1
    return [(value >> bit) & 1 for bit in range(PLAYERS)]


def panel(cohort: str) -> list[dict[str, Any]]:
    """Return the complete frozen panel including exact rational controls."""
    _require(cohort in {"confirmatory", "shakedown"}, "unknown cohort")
    if cohort == "shakedown":
        rows = []
        for index, multiplier in enumerate(SHAKEDOWN_MULTIPLIERS):
            fraction = Fraction(multiplier)
            rows.append(
                _with_controls(
                    {
                        "scenario_id": f"shake-{index + 1:02d}",
                        "cohort": cohort,
                        "endowment": (4, 8, 12)[index],
                        "m_num": fraction.numerator,
                        "m_den": fraction.denominator,
                        "opponent_script": ("retainers", "contributors", "grim")[index],
                        "objective": ("own_payoff", "joint_payoff", "own_payoff")[
                            index
                        ],
                        "focal_seat": (0, 3, 0)[index],
                        "horizon": HORIZON,
                        "arithmetic_probe_actions": _probe_joint_actions(100 + index),
                        "seed": 9101 + index * 37,
                        "arm_order": ["direct", "tool"]
                        if index % 2 == 0
                        else ["tool", "direct"],
                    }
                )
            )
        return rows

    rows = []
    ordinal = 0
    for replicate in range(5):
        for script_index, script in enumerate(("retainers", "contributors", "grim")):
            for objective_index, objective in enumerate(("own_payoff", "joint_payoff")):
                multiplier = Fraction(CONFIRMATORY_MULTIPLIERS[ordinal])
                rows.append(
                    _with_controls(
                        {
                            "scenario_id": f"plan-{ordinal + 1:02d}",
                            "cohort": cohort,
                            "endowment": (5, 7, 9, 11, 13)[replicate],
                            "m_num": multiplier.numerator,
                            "m_den": multiplier.denominator,
                            "opponent_script": script,
                            "objective": objective,
                            "focal_seat": (0, 3)[(ordinal // 4 + objective_index) % 2],
                            "horizon": HORIZON,
                            "arithmetic_probe_actions": _probe_joint_actions(ordinal),
                            "seed": 7001 + ordinal * 37,
                            "arm_order": ["direct", "tool"]
                            if (ordinal // 2 + objective_index) % 2 == 0
                            else ["tool", "direct"],
                        }
                    )
                )
                ordinal += 1
    _require(len(rows) == CONFIRMATORY_N, "confirmatory panel denominator drift")
    return rows


def _declared_slots(rows: list[dict[str, Any]]) -> list[str]:
    return [
        f"{scenario['scenario_id']}/{suffix}"
        for scenario in rows
        for suffix in ("direct", "tool_first", "tool_final")
    ]


def _stratum_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = row["analysis_stratum"]
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _script_text(script: str) -> str:
    return {
        "retainers": "The other three players retain in every round.",
        "contributors": "The other three players contribute in every round.",
        "grim": (
            "The other three players contribute until the focal player has "
            "retained in any earlier round; thereafter all three retain."
        ),
    }[script]


def _messages(scenario: dict[str, Any], *, tool_first: bool) -> list[dict[str, Any]]:
    system = (
        "Plan for an eight-round four-player public-goods game. In each round, "
        "binary action 1 contributes the entire endowment E and action 0 retains it. "
        "Let k=sum(actions). Every player receives shared=m*E*k/4. Player i receives "
        "E*(1-action_i)+shared. Group payoff is E*(4-k)+4*shared. Opponents follow "
        "the disclosed script and observe prior focal actions. Return bare JSON only: "
        '{"probe":{"focal":"canonical rational","total":"canonical rational"},'
        '"actions":[eight binary integers]}. The probe is one disclosed round and is '
        "separate from the strategic script. Objective own_payoff means cumulative focal payoff; objective "
        "joint_payoff means cumulative group payoff. Optimize the declared objective."
    )
    user = (
        f"E={scenario['endowment']}; m={scenario['m_num']}/{scenario['m_den']}; "
        f"focal seat={scenario['focal_seat']}; objective={scenario['objective']}. "
        f"{_script_text(scenario['opponent_script'])} "
        f"One-round arithmetic probe joint actions in seat order 0..3="
        f"{scenario['arithmetic_probe_actions']}. Give that round's focal and group "
        "payoffs, then your separate full eight-action strategic plan."
    )
    if tool_first:
        user += (
            " First call public_goods_payoff_table exactly once with E, m_num, "
            "m_den, and players=4. Do not provide the final JSON before its result."
        )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _tool_arguments(scenario: dict[str, Any]) -> dict[str, int]:
    return {
        "E": scenario["endowment"],
        "m_num": scenario["m_num"],
        "m_den": scenario["m_den"],
        "players": PLAYERS,
    }


def _tool_payload(scenario: dict[str, Any]) -> dict[str, Any]:
    E = scenario["endowment"]
    multiplier = Fraction(scenario["m_num"], scenario["m_den"])
    rows = []
    for others in range(PLAYERS):
        for focal_action in (0, 1):
            contributors = others + focal_action
            shared = multiplier * E * contributors / PLAYERS
            focal = E * (1 - focal_action) + shared
            total = E * (PLAYERS - contributors) + PLAYERS * shared
            rows.append(
                {
                    "other_contributors": others,
                    "focal_action": focal_action,
                    "shared_per_player": _rational(shared),
                    "focal_payoff": _rational(focal),
                    "group_payoff": _rational(total),
                }
            )
    return {
        "formula": {
            "k": "other_contributors+focal_action",
            "shared_per_player": "m*E*(other_contributors+focal_action)/4",
            "focal_payoff": "E*(1-focal_action)+shared_per_player",
            "group_payoff": "E*(4-k)+4*shared_per_player",
        },
        "rows": rows,
        "strategy_or_recommendation_included": False,
    }


def _grade_tool(
    call_status: str,
    receipt: dict[str, Any] | None,
    tool_calls: Any,
    content: str | None,
    scenario: dict[str, Any],
) -> dict[str, Any]:
    grade = {
        "parsed_tool_call": False,
        "args_shape_valid": False,
        "args_correct": False,
        "tool_executed": False,
        "failure_code": None,
    }
    if call_status != "returned":
        grade["failure_code"] = call_status
        return grade
    if not isinstance(tool_calls, (tuple, list)) or len(tool_calls) != 1:
        grade["failure_code"] = "no_single_tool_call"
        return grade
    call = tool_calls[0]
    if (
        not isinstance(call, dict)
        or set(call) != {"id", "type", "function"}
        or call.get("type") != "function"
        or not isinstance(call.get("id"), str)
        or not call["id"]
    ):
        grade["failure_code"] = "tool_shape"
        return grade
    function = call.get("function")
    if (
        not isinstance(function, dict)
        or set(function) != {"name", "arguments"}
        or function.get("name") != "public_goods_payoff_table"
        or not isinstance(function.get("arguments"), str)
    ):
        grade["failure_code"] = "tool_name_or_shape"
        return grade
    grade["parsed_tool_call"] = True
    if receipt is None or receipt.get("finish_reason") != "tool_calls" or content:
        grade["failure_code"] = "tool_incomplete_or_bypass"
        return grade
    try:
        arguments = transport._strict_json(function["arguments"])
    except (TypeError, ValueError):
        grade["failure_code"] = "args_json"
        return grade
    if (
        not isinstance(arguments, dict)
        or set(arguments) != {"E", "m_num", "m_den", "players"}
        or any(type(arguments[key]) is not int for key in arguments)
        or arguments["E"] <= 0
        or arguments["m_den"] <= 0
        or arguments["players"] != PLAYERS
    ):
        grade["failure_code"] = "args_shape"
        return grade
    grade["args_shape_valid"] = True
    if arguments != _tool_arguments(scenario):
        grade["failure_code"] = "wrong_args"
        return grade
    grade.update(args_correct=True, tool_executed=True)
    return grade


def _tool_result_message(
    call: dict[str, Any], scenario: dict[str, Any]
) -> dict[str, Any]:
    return {
        "role": "tool",
        "tool_call_id": call["id"],
        "name": "public_goods_payoff_table",
        "content": _canonical(_tool_payload(scenario)).decode(),
    }


def _final_messages(
    scenario: dict[str, Any], call: dict[str, Any], first_content: str
) -> list[dict[str, Any]]:
    return [
        *_messages(scenario, tool_first=True),
        {
            "role": "assistant",
            "content": first_content,
            "tool_calls": [copy.deepcopy(call)],
        },
        _tool_result_message(call, scenario),
        {
            "role": "user",
            "content": "Use the exact table and disclosed script. Return only the required bare JSON.",
        },
    ]


def _grade_final(
    content: str | None,
    status: str,
    scenario: dict[str, Any],
    *,
    finish_reason: str | None = None,
    tool_calls: Any = (),
) -> dict[str, Any]:
    grade = {
        "strict_shape": False,
        "comprehension_correct": False,
        "valid_plan": False,
        "zero_regret": False,
        "at_least_myopic": False,
        "objective_utility": None,
        "oracle_utility": scenario["controls"]["oracle_utility"],
        "regret": None,
        "myopic_regret": scenario["controls"]["myopic_regret"],
        "action_plan_sha256": None,
        "failure_code": None,
    }
    if status != "returned" or not isinstance(content, str):
        grade["failure_code"] = status
        return grade
    if finish_reason != "stop" or tool_calls:
        grade["failure_code"] = "final_incomplete_or_tool"
        return grade
    try:
        value = transport._strict_json(content)
    except (TypeError, ValueError):
        grade["failure_code"] = "final_json"
        return grade
    if not isinstance(value, dict) or set(value) != {"probe", "actions"}:
        grade["failure_code"] = "final_shape"
        return grade
    probe = value.get("probe")
    actions = value.get("actions")
    if (
        not isinstance(probe, dict)
        or set(probe) != {"focal", "total"}
        or _parse_rational(probe.get("focal")) is None
        or _parse_rational(probe.get("total")) is None
        or type(actions) is not list
        or len(actions) != HORIZON
        or any(type(action) is not int or action not in (0, 1) for action in actions)
    ):
        grade["failure_code"] = "final_value_shape"
        return grade
    grade["strict_shape"] = True
    grade["valid_plan"] = True
    grade["comprehension_correct"] = probe == scenario["probe_expected"]
    observed = _simulate(scenario, tuple(actions))["objective"]
    oracle = Fraction(scenario["controls"]["oracle_utility"])
    regret = oracle - observed
    myopic_regret = Fraction(scenario["controls"]["myopic_regret"])
    _require(regret >= 0, "exact oracle was exceeded")
    grade.update(
        {
            "zero_regret": regret == 0,
            "at_least_myopic": regret <= myopic_regret,
            "objective_utility": _rational(observed),
            "regret": _rational(regret),
            "action_plan_sha256": _sha(_canonical(actions)),
            "failure_code": None if grade["comprehension_correct"] else "probe_wrong",
        }
    )
    return grade


def make_plan(
    plan_path: str | Path,
    *,
    study_id: str,
    cohort: str,
    artifact_root: str | Path = ARTIFACT_ROOT,
    runtime_snapshot_fn: Callable[[], dict[str, Any]] = resident._live_runtime_binding,
    ready_fn: Callable[[], bool] = resident._ready,
    memory_fn: Callable[[], float] = resident._available_gib,
) -> dict[str, Any]:
    """Freeze a fresh plan; this function issues no generation request."""
    _require(
        re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}", study_id) is not None,
        "study ID is malformed",
    )
    _require(
        cohort == "shakedown",
        "confirmatory preparation is deferred pending redesign and campaign registration",
    )
    rows = panel(cohort)
    runtime_binding = runtime_snapshot_fn()
    resident._validate_runtime_binding(runtime_binding)
    _require(ready_fn(), "resident Flash is not ready")
    _require(float(memory_fn()) >= MEMORY_FLOOR_GIB, "20 GiB memory floor unavailable")
    expected_n = CONFIRMATORY_N if cohort == "confirmatory" else SHAKEDOWN_N
    root = Path(artifact_root).resolve(strict=False)
    path = resident._artifact_path(
        Path(plan_path), root, label="payoff-assistance plan"
    )
    slots = _declared_slots(rows)
    plan_value = {
        "schema_version": PLAN_SCHEMA,
        "study_id": study_id,
        "cohort": cohort,
        "code_root": str(CODE_ROOT),
        "runtime_binding": runtime_binding,
        "source_sha256": _sources(),
        "scenarios": rows,
        "panel_sha256": _sha(_canonical(rows)),
        "declared_units": [row["scenario_id"] for row in rows],
        "declared_conditions": [
            f"{row['scenario_id']}/{arm}" for row in rows for arm in row["arm_order"]
        ],
        "declared_slots": slots,
        "policy_id": POLICY_ID,
        "policy": copy.deepcopy(POLICY),
        "tool_spec": copy.deepcopy(TOOL_SPEC),
        "limits": {
            "max_tokens": MAX_TOKENS,
            "call_timeout_s": CALL_TIMEOUT_S,
            "evaluator_budget_s": EVALUATOR_BUDGET_S,
            "memory_floor_gib": MEMORY_FLOOR_GIB,
            "max_calls": expected_n * 3,
        },
        "unit_contract": {
            "unit": "distinct_scenario_pair",
            "count": expected_n,
            "requests_are_units": False,
            "rounds_are_units": False,
            "iid_population_claim": False,
            "shakedown_pooled_with_confirmatory": False,
            "analysis_strata": _stratum_counts(rows),
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
        "research_context": copy.deepcopy(RESEARCH_CONTEXT),
        "claim_limit": CLAIM_LIMIT,
        "scientific_admission_registered": False,
        "production_change_authorized": False,
        "promotion_authorized": False,
    }
    _require(len(slots) == expected_n * 3, "call-slot denominator drift")
    if cohort == "confirmatory":
        shake_hashes = {row["task_sha256"] for row in panel("shakedown")}
        _require(
            not shake_hashes.intersection(row["task_sha256"] for row in rows),
            "shakedown overlaps confirmatory panel",
        )
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    root.chmod(0o700)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(_canonical(plan_value) + b"\n")
    return plan_value


def load_plan(plan_path: str | Path) -> tuple[dict[str, Any], str]:
    plan_value, raw = resident._read_object(
        Path(plan_path), label="payoff-assistance plan", ceiling=4_000_000
    )
    expected_keys = {
        "schema_version",
        "study_id",
        "cohort",
        "code_root",
        "runtime_binding",
        "source_sha256",
        "scenarios",
        "panel_sha256",
        "declared_units",
        "declared_conditions",
        "declared_slots",
        "policy_id",
        "policy",
        "tool_spec",
        "limits",
        "unit_contract",
        "coordination",
        "budget",
        "artifact_policy",
        "research_context",
        "claim_limit",
        "scientific_admission_registered",
        "production_change_authorized",
        "promotion_authorized",
    }
    _require(
        set(plan_value) == expected_keys
        and plan_value.get("schema_version") == PLAN_SCHEMA,
        "plan shape or schema differs",
    )
    cohort = plan_value.get("cohort")
    rows = panel(cohort)
    expected_n = CONFIRMATORY_N if cohort == "confirmatory" else SHAKEDOWN_N
    _require(plan_value.get("source_sha256") == _sources(), "evaluator source drift")
    _require(plan_value.get("scenarios") == rows, "frozen scenario panel drift")
    _require(
        plan_value.get("panel_sha256") == _sha(_canonical(rows)), "panel digest drift"
    )
    _require(
        plan_value.get("declared_units") == [row["scenario_id"] for row in rows],
        "unit denominator drift",
    )
    conditions = [
        f"{row['scenario_id']}/{arm}" for row in rows for arm in row["arm_order"]
    ]
    _require(
        plan_value.get("declared_conditions") == conditions,
        "condition denominator drift",
    )
    _require(
        plan_value.get("declared_slots") == _declared_slots(rows),
        "slot denominator drift",
    )
    _require(
        plan_value.get("policy_id") == POLICY_ID and plan_value.get("policy") == POLICY,
        "inference policy drift",
    )
    _require(plan_value.get("tool_spec") == TOOL_SPEC, "tool contract drift")
    _require(
        plan_value.get("limits")
        == {
            "max_tokens": MAX_TOKENS,
            "call_timeout_s": CALL_TIMEOUT_S,
            "evaluator_budget_s": EVALUATOR_BUDGET_S,
            "memory_floor_gib": MEMORY_FLOOR_GIB,
            "max_calls": expected_n * 3,
        },
        "limits drift",
    )
    _require(
        plan_value.get("unit_contract")
        == {
            "unit": "distinct_scenario_pair",
            "count": expected_n,
            "requests_are_units": False,
            "rounds_are_units": False,
            "iid_population_claim": False,
            "shakedown_pooled_with_confirmatory": False,
            "analysis_strata": _stratum_counts(rows),
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
        },
        "coordination contract drift",
    )
    _require(
        plan_value.get("budget")
        == {
            "weekly_two_hour_debit": False,
            "authorization": "owner-authorized-current-local-research-session",
        },
        "budget attribution drift",
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
        Path(plan_path), Path(policy["private_root"]), label="payoff-assistance plan"
    )
    _require(
        plan_value.get("research_context") == RESEARCH_CONTEXT,
        "research context drift",
    )
    _require(
        plan_value.get("claim_limit") == CLAIM_LIMIT
        and plan_value.get("scientific_admission_registered") is False
        and plan_value.get("production_change_authorized") is False
        and plan_value.get("promotion_authorized") is False,
        "claim or authority boundary drift",
    )
    _require(
        isinstance(plan_value.get("code_root"), str)
        and Path(plan_value["code_root"]).is_absolute(),
        "origin path malformed",
    )
    _require(
        isinstance(plan_value.get("study_id"), str)
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}", plan_value["study_id"]),
        "study ID malformed",
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
        "role": "strategic_plan",
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
    except Exception as exc:  # noqa: BLE001 - failures remain denominator cells
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
        "reasoning_content": private_response["reasoning_content"]
        if private_response
        else None,
        "tool_calls": private_response["tool_calls"] if private_response else [],
        "response_id": private_response["response_id"] if private_response else None,
        "response_model": private_response["response_model"]
        if private_response
        else None,
        "finish_reason": private_response["finish_reason"]
        if private_response
        else None,
        "usage": private_response["usage"] if private_response else None,
        "response_stream_sha256": (
            private_response["response_stream_sha256"] if private_response else None
        ),
    }
    evidence = {
        "schema_version": PRIVATE_SCHEMA,
        "call_id": call_id,
        "call_index": ordinal,
        "role": "strategic_plan",
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
                "issued slot does not derive exactly from its call receipt",
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
    """Execute a frozen cohort against the warm resident Flash endpoint."""
    plan_value, plan_sha = load_plan(plan_path)
    _require(
        plan_value["cohort"] != "confirmatory"
        or plan_value["scientific_admission_registered"] is True,
        "confirmatory execution requires a new source-frozen campaign registration",
    )
    _require(callable(getattr(cancel_event, "is_set", None)), "cancel event missing")
    output = resident._artifact_path(
        Path(output_dir),
        Path(plan_value["artifact_policy"]["private_root"]),
        label="payoff-assistance output",
    )
    _require(not output.exists(), "output already exists")
    start = monotonic()
    deadline = start + EVALUATOR_BUDGET_S
    slots: dict[str, dict[str, Any]] = {}
    outcomes: list[dict[str, Any]] = []
    ordinal = 0
    abort_reason: str | None = None

    def can_issue() -> bool:
        nonlocal abort_reason
        if abort_reason is not None:
            return False
        if cancel_event.is_set():
            abort_reason = "cancelled_before_next_call"
            return False
        if deadline - monotonic() < CALL_TIMEOUT_S + 0.05:
            abort_reason = "evaluator_budget_before_next_call"
            return False
        try:
            ready = ready_fn()
            available = float(memory_fn())
            current = runtime_snapshot_fn() if ready else None
        except Exception as exc:  # noqa: BLE001
            abort_reason = f"runtime_probe_failed:{type(exc).__name__}"
            return False
        if not ready:
            abort_reason = "Flash_not_ready_before_next_call"
        elif available < MEMORY_FLOOR_GIB:
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
    ) -> tuple[Any, dict[str, Any]]:
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
        if call.receipt.get("timeout_s") != CALL_TIMEOUT_S:
            abort_reason = f"shortened_timeout:{slot_id}"
        elif slot["dispatch_state"] == "prewire_failure":
            abort_reason = f"prewire_failure:{slot_id}"
        elif call.status == "cancelled":
            abort_reason = "transport_cancelled"
        return call, slot

    with lock_factory(resident.CANONICAL_ROOT):
        _require(
            plan_value["source_sha256"] == _sources(), "source changed after admission"
        )
        _require(
            ready_fn() and float(memory_fn()) >= MEMORY_FLOOR_GIB,
            "resident Flash or memory floor unavailable",
        )
        _require(
            runtime_snapshot_fn() == plan_value["runtime_binding"],
            "runtime identity changed after preparation",
        )
        contention = idle_probe_fn()
        resident._validate_idle_observation(contention)
        _require(
            contention["observed_idle"] is True, "endpoint busy before study start"
        )
        _require(not cancel_event.is_set(), "study cancelled during admission")
        output.mkdir(mode=0o700, parents=True)
        output.chmod(0o700)
        for scenario in plan_value["scenarios"]:
            for arm_name in scenario["arm_order"]:
                calls: list[dict[str, Any]] = []
                descriptors: list[dict[str, Any]] = []
                if arm_name == "direct":
                    slot_id = f"{scenario['scenario_id']}/direct"
                    if can_issue():
                        call, slot = issue(
                            slot_id,
                            _messages(scenario, tool_first=False),
                            [],
                            scenario["seed"],
                        )
                        slots[slot_id] = slot
                        calls.append(call.receipt)
                        descriptors.append(slot["private_descriptor"])
                        grade = _grade_final(
                            call.content,
                            call.status,
                            scenario,
                            finish_reason=call.receipt.get("finish_reason"),
                            tool_calls=call.tool_calls,
                        )
                    else:
                        slots[slot_id] = _unissued_slot(
                            slot_id, "unissued_after_abort", abort_reason or "aborted"
                        )
                        grade = _grade_final(None, "not_run", scenario)
                    outcomes.append(
                        {
                            "scenario_id": scenario["scenario_id"],
                            "arm": "direct",
                            "calls": calls,
                            "grade": {
                                "details": {
                                    **grade,
                                    "_private_call_evidence": {
                                        "schema_version": harness.PRIVATE_INDEX_SCHEMA,
                                        "artifacts": descriptors,
                                    },
                                }
                            },
                        }
                    )
                else:
                    first_id = f"{scenario['scenario_id']}/tool_first"
                    final_id = f"{scenario['scenario_id']}/tool_final"
                    if can_issue():
                        first, first_slot = issue(
                            first_id,
                            _messages(scenario, tool_first=True),
                            [copy.deepcopy(TOOL_SPEC)],
                            scenario["seed"],
                        )
                        slots[first_id] = first_slot
                        calls.append(first.receipt)
                        descriptors.append(first_slot["private_descriptor"])
                        tool_grade = _grade_tool(
                            first.status,
                            first.receipt,
                            first.tool_calls,
                            first.content,
                            scenario,
                        )
                    else:
                        slots[first_id] = _unissued_slot(
                            first_id, "unissued_after_abort", abort_reason or "aborted"
                        )
                        tool_grade = _grade_tool("not_run", None, (), None, scenario)
                        first = None
                    final_grade = _grade_final(None, "skipped", scenario)
                    if (
                        first is not None
                        and tool_grade["tool_executed"]
                        and can_issue()
                    ):
                        final, final_slot = issue(
                            final_id,
                            _final_messages(
                                scenario, first.tool_calls[0], first.content or ""
                            ),
                            [],
                            scenario["seed"],
                        )
                        slots[final_id] = final_slot
                        calls.append(final.receipt)
                        descriptors.append(final_slot["private_descriptor"])
                        final_grade = _grade_final(
                            final.content,
                            final.status,
                            scenario,
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
                    outcomes.append(
                        {
                            "scenario_id": scenario["scenario_id"],
                            "arm": "tool",
                            "calls": calls,
                            "grade": {
                                "details": {
                                    **final_grade,
                                    "tool": tool_grade,
                                    "_private_call_evidence": {
                                        "schema_version": harness.PRIVATE_INDEX_SCHEMA,
                                        "artifacts": descriptors,
                                    },
                                }
                            },
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
        # Preserve every preregistered condition even after an abort.
        present = {(row["scenario_id"], row["arm"]) for row in outcomes}
        for scenario in plan_value["scenarios"]:
            for arm_name in scenario["arm_order"]:
                if (scenario["scenario_id"], arm_name) not in present:
                    detail = _grade_final(None, "not_run", scenario)
                    if arm_name == "tool":
                        detail["tool"] = _grade_tool(
                            "not_run", None, (), None, scenario
                        )
                    detail["_private_call_evidence"] = {
                        "schema_version": harness.PRIVATE_INDEX_SCHEMA,
                        "artifacts": [],
                    }
                    outcomes.append(
                        {
                            "scenario_id": scenario["scenario_id"],
                            "arm": arm_name,
                            "calls": [],
                            "grade": {"details": detail},
                        }
                    )
        order = {
            (scenario["scenario_id"], arm): index
            for index, (scenario, arm) in enumerate(
                pair
                for scenario in plan_value["scenarios"]
                for pair in (
                    (scenario, scenario["arm_order"][0]),
                    (scenario, scenario["arm_order"][1]),
                )
            )
        }
        outcomes.sort(key=lambda row: order[(row["scenario_id"], row["arm"])])
        ordered_slots = [slots[slot_id] for slot_id in plan_value["declared_slots"]]
        accounting = _account(ordered_slots)
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
            "research_context": copy.deepcopy(RESEARCH_CONTEXT),
            "abort_reason": abort_reason,
            "elapsed_s": max(0.0, monotonic() - start),
            "weekly_two_hour_debit": False,
            "scientific_admission_registered": False,
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
    path = descriptor.get("metadata_path") if isinstance(descriptor, dict) else None
    _require(
        isinstance(path, str)
        and re.fullmatch(r"private/calls/[0-9]{4}-[0-9a-f]{16}\.json", path)
        is not None,
        "private metadata path invalid",
    )
    raw, _resolved = harness._read_regular_file(
        output / path, label="private payoff-assistance call", max_bytes=512_000
    )
    _require(
        _sha(raw) == descriptor.get("metadata_sha256")
        and len(raw) == descriptor.get("metadata_bytes"),
        "private metadata bytes differ",
    )
    metadata = harness._strict_object(raw, "private payoff-assistance call")
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
                r"private/streams/[0-9]{4}-[0-9a-f]{16}\.sse", stream_descriptor["path"]
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
                label="private payoff-assistance SSE",
                ceiling=transport.MAX_RESPONSE_BYTES,
                digest=stream_descriptor["sha256"],
                count=stream_descriptor["bytes"],
                allow_empty_transport=True,
            )
        except private_evidence.PrivateEvidenceError as exc:
            raise PayoffAssistanceError(f"private SSE bytes differ: {exc}") from exc
    _require(
        metadata.get("response", {}).get("raw_stream_artifact") == stream_descriptor,
        "private response/stream binding differs",
    )
    return metadata, stream


def _summary(
    grades: dict[str, dict[str, Any]], expected: list[str], key: str, label: str
) -> dict[str, Any]:
    missing = [cell for cell in expected if cell not in grades]
    failed = [
        cell
        for cell in expected
        if cell in grades and grades[cell].get(key) is not True
    ]
    categories: dict[str, int] = {}
    for cell in failed:
        code = grades[cell].get("failure_code")
        category = code if isinstance(code, str) and code else f"{key}_false"
        categories[category] = categories.get(category, 0) + 1
    return {
        label: sum(grades.get(cell, {}).get(key) is True for cell in expected),
        "denominator": len(expected),
        "missing_cells": missing,
        "failed_cells": failed,
        "failure_categories": dict(sorted(categories.items())),
    }


def validate(plan_path: str | Path, output_dir: str | Path) -> dict[str, Any]:
    """Independently replay raw SSE, exact requests, controls, and grades."""
    plan_value, plan_sha = load_plan(plan_path)
    output = resident._artifact_path(
        Path(output_dir),
        Path(plan_value["artifact_policy"]["private_root"]),
        label="payoff-assistance output",
    )
    run_value, run_raw = resident._read_object(
        output / "run.json", label="payoff-assistance run", ceiling=16_000_000
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
        "research_context",
        "abort_reason",
        "elapsed_s",
        "weekly_two_hour_debit",
        "scientific_admission_registered",
        "production_change_authorized",
        "promotion_authorized",
        "claim_limit",
        "private_content_exported",
    }
    _require(
        set(run_value) == expected_run_keys
        and run_value.get("schema_version") == RUN_SCHEMA
        and run_value.get("status") == "complete"
        and run_value.get("abort_reason") is None,
        "run is not a complete frozen study",
    )
    _require(
        run_value.get("study_id") == plan_value["study_id"]
        and run_value.get("cohort") == plan_value["cohort"]
        and run_value.get("plan_raw_sha256") == plan_sha
        and run_value.get("runtime_binding") == plan_value["runtime_binding"],
        "run identity or runtime differs",
    )
    _require(
        run_value.get("declared_units") == plan_value["declared_units"]
        and run_value.get("declared_conditions") == plan_value["declared_conditions"]
        and run_value.get("declared_slots") == plan_value["declared_slots"],
        "run denominators differ",
    )
    _require(
        run_value.get("scientific_admission_registered") is False
        and run_value.get("weekly_two_hour_debit") is False
        and run_value.get("production_change_authorized") is False
        and run_value.get("promotion_authorized") is False
        and run_value.get("private_content_exported") is False
        and run_value.get("claim_limit") == CLAIM_LIMIT,
        "run claim or authority boundary differs",
    )
    _require(
        run_value.get("research_context")
        == plan_value["research_context"]
        == RESEARCH_CONTEXT,
        "run research context differs",
    )
    _require(
        type(run_value.get("elapsed_s")) in {int, float}
        and math.isfinite(float(run_value["elapsed_s"]))
        and 0 <= float(run_value["elapsed_s"]) <= EVALUATOR_BUDGET_S + 5,
        "run elapsed time invalid",
    )
    resident._validate_idle_observation(run_value.get("contention_observation"))

    slots = run_value.get("slots")
    outcomes = run_value.get("outcomes")
    _require(
        isinstance(slots, list)
        and [slot.get("slot_id") for slot in slots if isinstance(slot, dict)]
        == plan_value["declared_slots"],
        "slot order differs",
    )
    _require(
        all(
            isinstance(slot, dict)
            and set(slot)
            == {
                "slot_id",
                "disposition",
                "status",
                "failure_code",
                "dispatch_state",
                "call",
                "private_descriptor",
            }
            for slot in slots
        ),
        "slot shape differs",
    )
    expected_order = [
        (scenario["scenario_id"], arm)
        for scenario in plan_value["scenarios"]
        for arm in scenario["arm_order"]
    ]
    _require(
        isinstance(outcomes, list)
        and [
            (row.get("scenario_id"), row.get("arm"))
            for row in outcomes
            if isinstance(row, dict)
        ]
        == expected_order,
        "condition order or denominator differs",
    )
    _require(
        all(
            isinstance(row, dict)
            and set(row) == {"scenario_id", "arm", "calls", "grade"}
            and isinstance(row.get("grade"), dict)
            and set(row["grade"]) == {"details"}
            for row in outcomes
        ),
        "condition shape differs",
    )
    accounting = _account(slots)
    _require(
        accounting == run_value.get("accounting")
        and accounting["unissued_after_abort"] == 0
        and accounting["returned_calls"] > 0
        and accounting["prewire_failures"] == 0,
        "run accounting is not admissible for replay",
    )
    by_slot = {slot["slot_id"]: slot for slot in slots}
    scenario_by_id = {row["scenario_id"]: row for row in plan_value["scenarios"]}
    direct_grades: dict[str, dict[str, Any]] = {}
    tool_grades: dict[str, dict[str, Any]] = {}
    tool_final_grades: dict[str, dict[str, Any]] = {}
    call_indexes: list[int] = []
    returned_streams = 0
    seen_call_ids: set[str] = set()
    seen_metadata_paths: set[str] = set()

    def replay_call(
        call: dict[str, Any],
        descriptor: dict[str, Any],
        slot_id: str,
        scenario: dict[str, Any],
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> dict[str, Any]:
        nonlocal returned_streams
        metadata, raw_stream = _metadata(output, descriptor)
        _require(
            set(descriptor)
            == {
                "call_id",
                "status",
                "metadata_path",
                "metadata_sha256",
                "metadata_bytes",
                "raw_stream",
            }
            and descriptor.get("call_id") == call.get("call_id")
            and descriptor.get("status") == call.get("status")
            and descriptor["call_id"] not in seen_call_ids
            and descriptor["metadata_path"] not in seen_metadata_paths,
            "private descriptor identity is duplicate or differs",
        )
        expected_stem = (
            f"{call['call_index']:04d}-"
            f"{hashlib.sha256(call['call_id'].encode()).hexdigest()[:16]}"
        )
        _require(
            Path(descriptor["metadata_path"]).stem == expected_stem,
            "private artifact name differs from call chronology/identity",
        )
        seen_call_ids.add(descriptor["call_id"])
        seen_metadata_paths.add(descriptor["metadata_path"])
        request = metadata.get("request")
        response = metadata.get("response")
        _require(
            set(call)
            == {
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
            and type(call.get("call_index")) is int
            and call["call_index"] >= 0
            and type(call.get("wall_s")) in {int, float}
            and math.isfinite(float(call["wall_s"]))
            and 0 <= float(call["wall_s"]) <= CALL_TIMEOUT_S + 5,
            "public call receipt shape or elapsed time differs",
        )
        _require(
            isinstance(request, dict) and isinstance(response, dict),
            "private request or response absent",
        )
        _require(
            request.get("messages") == messages
            and request.get("tools") == tools
            and request.get("resolved_policy") == POLICY
            and request.get("seed") == scenario["seed"]
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
            scenario["seed"],
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
            and call.get("seed") == scenario["seed"]
            and call.get("max_tokens") == MAX_TOKENS
            and call.get("timeout_s") == CALL_TIMEOUT_S,
            "public route, model, policy, or limits differ",
        )
        slot = by_slot.get(slot_id)
        _require(
            isinstance(slot, dict)
            and slot.get("call") == call
            and slot.get("private_descriptor") == descriptor
            and call.get("call_id") == f"{plan_value['study_id']}/{slot_id}"
            and call.get("role") == "strategic_plan",
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
        if descriptor["raw_stream"] is not None:
            _require(
                descriptor["raw_stream"]["sha256"]
                == response.get("response_stream_sha256"),
                "raw stream digest differs from private response",
            )
        if call["status"] == "returned":
            _require(
                raw_stream is not None
                and call.get("dispatch_state") == "confirmed_dispatched"
                and all(response.get(key) == call.get(key) for key in response_keys),
                "returned response receipt differs",
            )
            private_evidence._response_matches_raw(raw_stream, response, call)
            returned_streams += 1
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
        call_indexes.append(call["call_index"])
        return metadata

    for outcome in outcomes:
        scenario = scenario_by_id[outcome["scenario_id"]]
        details = outcome.get("grade", {}).get("details")
        calls = outcome.get("calls")
        _require(
            isinstance(details, dict) and isinstance(calls, list),
            "condition evidence missing",
        )
        index = details.get("_private_call_evidence")
        _require(
            isinstance(index, dict)
            and set(index) == {"schema_version", "artifacts"}
            and index.get("schema_version") == harness.PRIVATE_INDEX_SCHEMA
            and isinstance(index.get("artifacts"), list)
            and len(index["artifacts"]) == len(calls),
            "private evidence index differs",
        )
        if outcome["arm"] == "direct":
            _require(len(calls) == 1, "direct condition call count differs")
            slot_id = f"{scenario['scenario_id']}/direct"
            metadata = replay_call(
                calls[0],
                index["artifacts"][0],
                slot_id,
                scenario,
                _messages(scenario, tool_first=False),
                [],
            )
            grade = _grade_final(
                metadata["response"]["content"],
                calls[0]["status"],
                scenario,
                finish_reason=calls[0].get("finish_reason"),
                tool_calls=metadata["response"]["tool_calls"],
            )
            stored = {
                key: value
                for key, value in details.items()
                if key != "_private_call_evidence"
            }
            _require(grade == stored, "direct grade differs on replay")
            direct_grades[scenario["scenario_id"]] = grade
            continue

        _require(len(calls) in (1, 2), "tool condition call count differs")
        first_id = f"{scenario['scenario_id']}/tool_first"
        final_id = f"{scenario['scenario_id']}/tool_final"
        first_metadata = replay_call(
            calls[0],
            index["artifacts"][0],
            first_id,
            scenario,
            _messages(scenario, tool_first=True),
            [copy.deepcopy(TOOL_SPEC)],
        )
        tool_grade = _grade_tool(
            calls[0]["status"],
            calls[0],
            first_metadata["response"]["tool_calls"],
            first_metadata["response"]["content"],
            scenario,
        )
        _require(tool_grade == details.get("tool"), "tool grade differs on replay")
        tool_grades[scenario["scenario_id"]] = tool_grade
        if tool_grade["tool_executed"]:
            _require(len(calls) == 2, "executed tool has no final call")
            final_messages = _final_messages(
                scenario,
                first_metadata["response"]["tool_calls"][0],
                first_metadata["response"]["content"] or "",
            )
            final_metadata = replay_call(
                calls[1], index["artifacts"][1], final_id, scenario, final_messages, []
            )
            grade = _grade_final(
                final_metadata["response"]["content"],
                calls[1]["status"],
                scenario,
                finish_reason=calls[1].get("finish_reason"),
                tool_calls=final_metadata["response"]["tool_calls"],
            )
        else:
            _require(
                len(calls) == 1
                and by_slot[final_id]["disposition"] == "skipped_unissued"
                and by_slot[final_id]["failure_code"] == tool_grade["failure_code"],
                "invalid tool did not causally skip final call",
            )
            grade = _grade_final(None, "skipped", scenario)
        stored = {
            key: value
            for key, value in details.items()
            if key not in {"tool", "_private_call_evidence"}
        }
        _require(grade == stored, "tool-final grade differs on replay")
        tool_final_grades[scenario["scenario_id"]] = grade

    _require(
        call_indexes == list(range(accounting["attempted_calls"])),
        "call chronology or coverage differs",
    )
    _require(
        returned_streams == accounting["returned_calls"],
        "returned raw-stream coverage differs",
    )
    expected = plan_value["declared_units"]
    complete_pairs = [
        scenario_id
        for scenario_id in expected
        if direct_grades[scenario_id]["valid_plan"]
        and tool_final_grades[scenario_id]["valid_plan"]
    ]
    regret_direction = {
        "tool_lower": 0,
        "equal": 0,
        "tool_higher": 0,
        "incomplete": len(expected) - len(complete_pairs),
    }
    paired_regret_rows = []
    regret_delta_sum = Fraction()
    for scenario_id in complete_pairs:
        direct = Fraction(direct_grades[scenario_id]["regret"])
        tool = Fraction(tool_final_grades[scenario_id]["regret"])
        delta = tool - direct
        regret_delta_sum += delta
        paired_regret_rows.append(
            {
                "scenario_id": scenario_id,
                "direct_regret": _rational(direct),
                "tool_regret": _rational(tool),
                "tool_minus_direct_regret": _rational(delta),
            }
        )
        regret_direction[
            "tool_lower"
            if tool < direct
            else "tool_higher"
            if tool > direct
            else "equal"
        ] += 1
    comprehension_transitions = {
        "both_correct": 0,
        "direct_only": 0,
        "tool_only": 0,
        "neither": 0,
    }
    for scenario_id in expected:
        direct_correct = direct_grades[scenario_id]["comprehension_correct"]
        tool_correct = tool_final_grades[scenario_id]["comprehension_correct"]
        comprehension_transitions[
            "both_correct"
            if direct_correct and tool_correct
            else "direct_only"
            if direct_correct
            else "tool_only"
            if tool_correct
            else "neither"
        ] += 1
    strata = []
    for objective in ("own_payoff", "joint_payoff"):
        for script in ("retainers", "contributors", "grim"):
            ids = [
                row["scenario_id"]
                for row in plan_value["scenarios"]
                if row["objective"] == objective and row["opponent_script"] == script
            ]
            if not ids:
                continue
            paired = [
                scenario_id
                for scenario_id in ids
                if direct_grades[scenario_id]["valid_plan"]
                and tool_final_grades[scenario_id]["valid_plan"]
            ]
            direction = {
                "tool_lower": 0,
                "equal": 0,
                "tool_higher": 0,
                "incomplete": len(ids) - len(paired),
            }
            delta_sum = Fraction()
            for scenario_id in paired:
                direct = Fraction(direct_grades[scenario_id]["regret"])
                tool = Fraction(tool_final_grades[scenario_id]["regret"])
                delta_sum += tool - direct
                direction[
                    "tool_lower"
                    if tool < direct
                    else "tool_higher"
                    if tool > direct
                    else "equal"
                ] += 1
            strata.append(
                {
                    "objective": objective,
                    "opponent_script": script,
                    "analysis_stratum": scenario_by_id[ids[0]]["analysis_stratum"],
                    "horizon_sensitive_strategic_stratum": (
                        objective == "own_payoff" and script == "grim"
                    ),
                    "distinct_scenario_pairs": len(ids),
                    "direct_comprehension": _summary(
                        direct_grades, ids, "comprehension_correct", "correct"
                    ),
                    "tool_comprehension": _summary(
                        tool_final_grades, ids, "comprehension_correct", "correct"
                    ),
                    "direct_zero_regret": _summary(
                        direct_grades, ids, "zero_regret", "passed"
                    ),
                    "tool_zero_regret": _summary(
                        tool_final_grades, ids, "zero_regret", "passed"
                    ),
                    "tool_invocation": _summary(
                        tool_grades, ids, "tool_executed", "exact"
                    ),
                    "paired_regret_direction": direction,
                    "tool_minus_direct_regret_sum": _rational(delta_sum),
                    "tool_minus_direct_regret_mean": (
                        _rational(delta_sum / len(paired)) if paired else None
                    ),
                }
            )
    dynamic_ids = [
        row["scenario_id"]
        for row in plan_value["scenarios"]
        if row["analysis_stratum"] == "dynamic_strategic"
    ]
    objective_summary = {
        "derived_from_independent_raw_replay": True,
        "finite_designed_panel": True,
        "iid_population_claim": False,
        "p_values_or_significance_reported": False,
        "denominators": {
            "distinct_scenario_pairs": len(expected),
            "conditions": len(expected) * 2,
            "max_call_slots": len(expected) * 3,
            **accounting,
        },
        "direct_valid_plan": _summary(direct_grades, expected, "valid_plan", "passed"),
        "direct_comprehension": _summary(
            direct_grades, expected, "comprehension_correct", "correct"
        ),
        "direct_zero_regret": _summary(
            direct_grades, expected, "zero_regret", "passed"
        ),
        "direct_at_least_myopic": _summary(
            direct_grades, expected, "at_least_myopic", "passed"
        ),
        "tool_invocation": _summary(tool_grades, expected, "tool_executed", "exact"),
        "tool_valid_plan": _summary(
            tool_final_grades, expected, "valid_plan", "passed"
        ),
        "tool_comprehension": _summary(
            tool_final_grades, expected, "comprehension_correct", "correct"
        ),
        "tool_zero_regret": _summary(
            tool_final_grades, expected, "zero_regret", "passed"
        ),
        "tool_at_least_myopic": _summary(
            tool_final_grades, expected, "at_least_myopic", "passed"
        ),
        "paired_valid_plans": {
            "complete": len(complete_pairs),
            "denominator": len(expected),
        },
        "paired_regret_direction": regret_direction,
        "paired_regret": {
            "complete": len(complete_pairs),
            "denominator": len(expected),
            "tool_minus_direct_sum": _rational(regret_delta_sum),
            "tool_minus_direct_mean": (
                _rational(regret_delta_sum / len(complete_pairs))
                if complete_pairs
                else None
            ),
            "rows": paired_regret_rows,
        },
        "paired_comprehension_transitions": comprehension_transitions,
        "objective_by_script_strata": strata,
        "strategic_interpretation": {
            "primary_stratum": "dynamic_strategic",
            "primary_stratum_units": len(dynamic_ids),
            "control_units": len(expected) - len(dynamic_ids),
            "aggregate_plan_success_is_not_a_strategic_effect_estimate": True,
        },
    }
    permanently_excluded = plan_value["cohort"] == "shakedown"
    return {
        "schema_version": VALIDATION_SCHEMA,
        "status": "passed",
        "study_id": plan_value["study_id"],
        "cohort": plan_value["cohort"],
        "plan_raw_sha256": plan_sha,
        "run_raw_sha256": _sha(run_raw),
        "raw_sse_replay_passed": True,
        "grade_replay_passed": True,
        "control_replay_passed": True,
        "accounting": accounting,
        "objective_summary": objective_summary,
        "private_calls_verified": {
            "calls": len(call_indexes),
            "returned_streams": returned_streams,
        },
        "shakedown_permanently_excluded": permanently_excluded,
        "scientific_admission_eligible": False,
        "scientific_admission_reason": (
            "permanently_excluded_shakedown"
            if permanently_excluded
            else "study_not_registered_in_campaign_admission_layer"
        ),
        "production_change_authorized": False,
        "promotion_authorized": False,
        "private_content_exported": False,
        "weekly_two_hour_debit": False,
        "research_context": copy.deepcopy(RESEARCH_CONTEXT),
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
    parser.add_argument("--cohort", choices=("shakedown", "confirmatory"))
    args = parser.parse_args(argv)
    if args.prepare:
        _require(
            args.output is None and args.study_id and args.cohort,
            "--prepare requires --study-id and --cohort only",
        )
        result = make_plan(args.prepare, study_id=args.study_id, cohort=args.cohort)
    elif args.run:
        _require(
            args.output and args.study_id is None and args.cohort is None,
            "--run requires --output and reads identity from plan",
        )
        result = run(args.run, args.output, cancel_event=_cancel_event())
    else:
        _require(
            args.output and args.study_id is None and args.cohort is None,
            "--validate requires --output and reads identity from plan",
        )
        result = validate(args.validate, args.output)
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
