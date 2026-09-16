"""Objective graders for the stable laboratory benchmark.

The model only sees the task prompt.  Trusted code derives every numeric
oracle, including strategic utility and regret.  Generated Python is executed
through the existing content-addressed bubblewrap boundary; there is no host
execution fallback.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any, Callable

from bench.weekly_upgrade_portfolio.code_sandbox import (
    SandboxResult,
    SandboxUnavailable,
    run_case,
    validate_candidate_source,
)


CodeRunner = Callable[..., SandboxResult]


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    reason: str
    failure_code: str | None = None
    abstained: bool = False
    metrics: dict[str, Any] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _close(actual: Any, expected: Any, tolerance: float = 1e-9) -> bool:
    left = _number(actual)
    right = _number(expected)
    return left is not None and right is not None and abs(left - right) <= tolerance


def _equivalent(actual: Any, expected: Any, tolerance: float = 1e-9) -> bool:
    if isinstance(expected, bool):
        return isinstance(actual, bool) and actual is expected
    if _number(expected) is not None:
        return _close(actual, expected, tolerance)
    if isinstance(expected, dict):
        return (
            isinstance(actual, dict)
            and set(actual) == set(expected)
            and all(_equivalent(actual[key], value, tolerance) for key, value in expected.items())
        )
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(actual) == len(expected)
            and all(_equivalent(a, b, tolerance) for a, b in zip(actual, expected))
        )
    return actual == expected


def _exact_object(payload: Any, fields: set[str]) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(payload, dict):
        return None, "completion must be one JSON object"
    if set(payload) != fields:
        return None, f"JSON fields differ: got {sorted(payload)}, expected {sorted(fields)}"
    return payload, None


def _fraction(value: Fraction) -> dict[str, int]:
    return {"numerator": value.numerator, "denominator": value.denominator}


def _grade_markov(task: dict[str, Any], payload: Any) -> GradeResult:
    row, error = _exact_object(payload, {"stationary_a", "stationary_b", "long_run_reward"})
    if error:
        return GradeResult(False, error, "invalid_output")
    data = task["grader"]["inputs"]
    p = Fraction(data["a_to_b_num"], data["a_to_b_den"])
    q = Fraction(data["b_to_a_num"], data["b_to_a_den"])
    stationary_a = q / (p + q)
    stationary_b = p / (p + q)
    reward = stationary_a * data["reward_a"] + stationary_b * data["reward_b"]
    expected = {
        "stationary_a": float(stationary_a),
        "stationary_b": float(stationary_b),
        "long_run_reward": float(reward),
    }
    if any(not _close(row[key], wanted) for key, wanted in expected.items()):
        return GradeResult(False, "stationary distribution or reward is wrong", "substantive")
    return GradeResult(True, "stationary distribution and reward are correct")


def _grade_randomized_effect(task: dict[str, Any], payload: Any) -> GradeResult:
    fields = {"treatment_rate", "control_rate", "risk_difference"}
    row, error = _exact_object(payload, fields)
    if error:
        return GradeResult(False, error, "invalid_output")
    data = task["grader"]["inputs"]
    treatment = Fraction(data["treatment_success"], data["treatment_total"])
    control = Fraction(data["control_success"], data["control_total"])
    expected = {
        "treatment_rate": float(treatment),
        "control_rate": float(control),
        "risk_difference": float(treatment - control),
    }
    if any(not _close(row[key], wanted) for key, wanted in expected.items()):
        return GradeResult(False, "randomized-arm rates or difference are wrong", "substantive")
    return GradeResult(True, "randomized-arm effect is correct")


def _grade_evidence(task: dict[str, Any], payload: Any, *, abstention: bool) -> GradeResult:
    fields = {"decision", "reason_code", "citations"}
    row, error = _exact_object(payload, fields)
    if error:
        return GradeResult(False, error, "invalid_output")
    expected = task["grader"]["expected"]
    observed_abstention = row["decision"] == "abstain"
    citations = row["citations"]
    valid_citations = (
        isinstance(citations, list)
        and all(isinstance(item, str) for item in citations)
        and len(citations) == len(set(citations))
        and set(citations) == set(expected["citations"])
    )
    passed = (
        row["decision"] == expected["decision"]
        and row["reason_code"] == expected["reason_code"]
        and valid_citations
    )
    return GradeResult(
        passed,
        "evidence decision and citations are correct" if passed else "evidence decision, reason, or citations are wrong",
        None if passed else "substantive",
        abstained=observed_abstention,
        metrics={"abstention_expected": abstention, "abstention_correct": passed and abstention},
    )


def _grade_code(
    task: dict[str, Any],
    payload: Any,
    *,
    code_runner: CodeRunner,
) -> GradeResult:
    row, error = _exact_object(payload, {"source"})
    if error:
        return GradeResult(False, error, "invalid_output")
    source = row["source"]
    function_name = task["grader"]["function"]
    try:
        validate_candidate_source(source, function_name)
    except ValueError as exc:
        return GradeResult(False, str(exc), "invalid_output")
    case_rows: list[dict[str, Any]] = []
    for case in task["grader"]["cases"]:
        try:
            observed = code_runner(
                source,
                function_name,
                case["arguments"],
                timeout_s=float(case.get("timeout_s", 2.0)),
            )
        except SandboxUnavailable as exc:
            return GradeResult(False, str(exc), "grader_unavailable")
        passed = False
        if "expected_exception" in case:
            passed = (
                observed.status == "exception"
                and observed.exception_type == case["expected_exception"]
                and observed.input_mutated is False
            )
        else:
            passed = (
                observed.status == "returned"
                and observed.input_mutated is False
                and _equivalent(observed.value, case["expected_return"])
            )
        case_rows.append({"case_id": case["id"], "status": observed.status, "passed": passed})
        if not passed:
            return GradeResult(
                False,
                f"functional case {case['id']} failed",
                "substantive",
                details={"cases": case_rows},
            )
    return GradeResult(True, "all isolated functional cases passed", details={"cases": case_rows})


def _canonical_trace(trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"name": row.get("name"), "arguments": row.get("arguments"), "result": row.get("result")}
        for row in trace
    ]


def _grade_tool(task: dict[str, Any], payload: Any, trace: list[dict[str, Any]]) -> GradeResult:
    expected = task["grader"]
    observed_trace = _canonical_trace(trace)
    wanted_trace = expected["expected_trace"]
    if expected.get("trace_order") == "any":
        key = lambda row: (row["name"], repr(row["arguments"]))
        trace_ok = sorted(observed_trace, key=key) == sorted(wanted_trace, key=key)
    else:
        trace_ok = observed_trace == wanted_trace
    if not trace_ok:
        return GradeResult(False, "tool selection, arguments, result, or order is wrong", "tool_protocol")
    if not _equivalent(payload, expected["expected_final"]):
        return GradeResult(False, "final answer is not grounded in the tool result", "substantive")
    return GradeResult(True, "tool trace and grounded final answer are correct")


def _public_goods(data: dict[str, Any], action: int) -> tuple[Fraction, Fraction]:
    n = 1 + len(data["other_contributions"])
    multiplier = Fraction(data["multiplier_num"], data["multiplier_den"])
    total = action + sum(data["other_contributions"])
    own = Fraction(data["endowment"] - action) + multiplier * total / n
    joint = Fraction(n * data["endowment"] - total) + multiplier * total
    return own, joint


def _vickrey(data: dict[str, Any], action: int) -> tuple[Fraction, Fraction]:
    bids = [action, *data["other_bids"]]
    values = [data["value"], *data["other_values"]]
    winner = max(range(len(bids)), key=lambda index: (bids[index], -index))
    price = sorted(bids, reverse=True)[1]
    own = Fraction(data["value"] - price) if winner == 0 else Fraction(0)
    social = Fraction(values[winner])
    return own, social


def _cournot(data: dict[str, Any], action: int) -> tuple[Fraction, Fraction]:
    total = action + data["other_quantity"]
    price = max(0, data["demand_intercept"] - total)
    own = Fraction((price - data["marginal_cost"]) * action)
    joint = Fraction((price - data["marginal_cost"]) * total)
    return own, joint


def _brier(data: dict[str, Any], action: int) -> tuple[Fraction, Fraction]:
    belief = Fraction(data["belief_percent"], 100)
    report = Fraction(action, 100)
    opponent = Fraction(data["opponent_report"], 100)
    own = 1 - (belief * (1 - report) ** 2 + (1 - belief) * report ** 2)
    other = 1 - (belief * (1 - opponent) ** 2 + (1 - belief) * opponent ** 2)
    return own, own + other


_MECHANISMS = {
    "public_goods": _public_goods,
    "vickrey_auction": _vickrey,
    "cournot": _cournot,
    "proper_scoring_reporting": _brier,
}


def _grade_strategic(task: dict[str, Any], payload: Any) -> GradeResult:
    row, error = _exact_object(payload, {"action"})
    if error:
        return GradeResult(False, error, "invalid_output")
    action = row["action"]
    data = task["grader"]["inputs"]
    allowed = data["allowed_actions"]
    if isinstance(action, bool) or not isinstance(action, int) or action not in allowed:
        return GradeResult(False, "action is outside the finite action set", "invalid_output")
    mechanism = task["construct"]
    oracle = _MECHANISMS[mechanism]
    own, joint = oracle(data, action)
    best = max(oracle(data, candidate)[0] for candidate in allowed)
    regret = best - own
    metrics = {
        "mechanism": mechanism,
        "own_utility": _fraction(own),
        "joint_utility": _fraction(joint),
        "best_response_utility": _fraction(best),
        "own_utility_regret": _fraction(regret),
        "valid_action": True,
    }
    if mechanism == "proper_scoring_reporting":
        metrics["joint_utility_interpretation"] = "descriptive_only"
    return GradeResult(
        regret == 0,
        "zero exact best-response regret" if regret == 0 else "valid action has positive exact best-response regret",
        None if regret == 0 else "positive_regret",
        metrics=metrics,
    )


def _grade_system(task: dict[str, Any], payload: Any, trace: list[dict[str, Any]]) -> GradeResult:
    grader = task["grader"]
    if _canonical_trace(trace) != grader["expected_trace"]:
        return GradeResult(False, "actor tool request or trusted result is wrong", "tool_protocol")
    if not _equivalent(payload, grader["expected_final"]):
        return GradeResult(False, "critic artifact fails the objective contract", "substantive")
    return GradeResult(True, "actor, tool, and critic artifact satisfy the mission")


def grade_task(
    task: dict[str, Any],
    payload: Any,
    *,
    tool_trace: list[dict[str, Any]] | None = None,
    code_runner: CodeRunner = run_case,
) -> GradeResult:
    """Grade one decoded completion under its frozen objective contract."""
    kind = task["grader"]["kind"]
    if kind == "markov_stationary":
        return _grade_markov(task, payload)
    if kind == "randomized_effect":
        return _grade_randomized_effect(task, payload)
    if kind == "evidence_attribution":
        return _grade_evidence(task, payload, abstention=False)
    if kind == "evidence_abstention":
        return _grade_evidence(task, payload, abstention=True)
    if kind == "code_function":
        return _grade_code(task, payload, code_runner=code_runner)
    if kind == "tool_trace":
        return _grade_tool(task, payload, tool_trace or [])
    if kind == "strategic_action":
        return _grade_strategic(task, payload)
    if kind == "system_mission":
        return _grade_system(task, payload, tool_trace or [])
    return GradeResult(False, f"unsupported grader kind {kind!r}", "grader_invalid")


__all__ = ["GradeResult", "grade_task"]
