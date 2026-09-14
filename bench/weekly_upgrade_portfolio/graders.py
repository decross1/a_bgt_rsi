"""Objective graders for the public synthetic development portfolio."""

from __future__ import annotations

import hashlib
import json
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any

from .code_sandbox import (
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
    details: dict[str, Any] = dataclass_field(default_factory=dict)
    failure_code: str | None = None


def _receipt_sha(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _close(actual: Any, expected: Any, tolerance: float) -> bool:
    left = _number(actual)
    right = _number(expected)
    return left is not None and right is not None and abs(left - right) <= tolerance


def _equivalent(actual: Any, expected: Any, tolerance: float) -> bool:
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
            and all(_equivalent(left, right, tolerance) for left, right in zip(actual, expected))
        )
    return actual == expected


def _exact_fields(payload: Any, fields: set[str]) -> str | None:
    if not isinstance(payload, dict):
        return "completion must be one JSON object"
    if set(payload) != fields:
        return f"JSON fields differ: got {sorted(payload)}, expected {sorted(fields)}"
    return None


def _numeric_fields(payload: dict[str, Any], expected: dict[str, float], tolerance: float) -> str | None:
    for field, wanted in expected.items():
        if not _close(payload.get(field), wanted, tolerance):
            return f"{field} is numerically wrong"
    return None


def _grade_delegation_hhi(payload: dict[str, Any], inputs: dict[str, Any], tolerance: float) -> GradeResult:
    fields = {"baseline_hhi", "delegated_hhi", "delta", "direction"}
    if error := _exact_fields(payload, fields):
        return GradeResult(False, error, failure_code="schema")

    def hhi(weights: list[float]) -> float:
        total = sum(weights)
        return sum((weight / total) ** 2 for weight in weights)

    baseline = hhi(inputs["baseline_weights"])
    delegated = hhi(inputs["delegated_weights"])
    delta = delegated - baseline
    expected = {"baseline_hhi": baseline, "delegated_hhi": delegated, "delta": delta}
    if error := _numeric_fields(payload, expected, tolerance):
        return GradeResult(False, error, {"oracle": expected}, "substantive")
    direction = "increased" if delta > tolerance else "decreased" if delta < -tolerance else "unchanged"
    if payload["direction"] != direction:
        return GradeResult(False, "direction disagrees with the computed delta", failure_code="substantive")
    return GradeResult(True, "normalized concentration and direction are correct")


def _grade_sortition(payload: dict[str, Any], inputs: dict[str, Any], tolerance: float) -> GradeResult:
    fields = {
        "expected_a_seats",
        "expected_b_seats",
        "expected_a_share",
        "population_a_share",
        "a_representation_bias",
    }
    if error := _exact_fields(payload, fields):
        return GradeResult(False, error, failure_code="schema")
    population = inputs["population"]
    eligible = inputs["eligible"]
    seats = inputs["seats"]
    eligible_total = eligible["A"] + eligible["B"]
    expected_a_share = eligible["A"] / eligible_total
    population_a_share = population["A"] / (population["A"] + population["B"])
    expected = {
        "expected_a_seats": seats * expected_a_share,
        "expected_b_seats": seats * (1 - expected_a_share),
        "expected_a_share": expected_a_share,
        "population_a_share": population_a_share,
        "a_representation_bias": expected_a_share - population_a_share,
    }
    if error := _numeric_fields(payload, expected, tolerance):
        return GradeResult(False, error, {"oracle": expected}, "substantive")
    return GradeResult(True, "eligible-pool expectation and representation bias are correct")


def _grade_social_choice(payload: dict[str, Any], inputs: dict[str, Any], tolerance: float) -> GradeResult:
    fields = {"plurality_winner", "condorcet_winner", "b_over_a_margin", "b_over_c_margin"}
    if error := _exact_fields(payload, fields):
        return GradeResult(False, error, failure_code="schema")
    ballots = inputs["ballots"]
    candidates = inputs["candidates"]
    plurality = {candidate: 0 for candidate in candidates}
    pairwise = {(left, right): 0 for left in candidates for right in candidates if left != right}
    for ballot in ballots:
        ranking = ballot["ranking"]
        count = ballot["count"]
        plurality[ranking[0]] += count
        positions = {candidate: index for index, candidate in enumerate(ranking)}
        for left, right in pairwise:
            if positions[left] < positions[right]:
                pairwise[(left, right)] += count
    max_votes = max(plurality.values())
    plurality_winners = [candidate for candidate, votes in plurality.items() if votes == max_votes]
    condorcet = [
        candidate
        for candidate in candidates
        if all(pairwise[(candidate, other)] > pairwise[(other, candidate)] for other in candidates if other != candidate)
    ]
    if len(plurality_winners) != 1 or len(condorcet) != 1:
        return GradeResult(False, "fixture oracle is not uniquely defined", failure_code="grader")
    expected = {
        "plurality_winner": plurality_winners[0],
        "condorcet_winner": condorcet[0],
        "b_over_a_margin": pairwise[("B", "A")] - pairwise[("A", "B")],
        "b_over_c_margin": pairwise[("B", "C")] - pairwise[("C", "B")],
    }
    for field in ("plurality_winner", "condorcet_winner"):
        if payload[field] != expected[field]:
            return GradeResult(False, f"{field} is wrong", {"oracle": expected}, "substantive")
    if error := _numeric_fields(
        payload,
        {key: expected[key] for key in ("b_over_a_margin", "b_over_c_margin")},
        tolerance,
    ):
        return GradeResult(False, error, {"oracle": expected}, "substantive")
    return GradeResult(True, "plurality and pairwise outcomes are correct")


def _grade_coordination(payload: dict[str, Any], inputs: dict[str, Any], tolerance: float) -> GradeResult:
    fields = {"pure_equilibria", "mixed_adopt_probability"}
    if error := _exact_fields(payload, fields):
        return GradeResult(False, error, failure_code="schema")
    actions = inputs["actions"]
    row = inputs["row_payoffs"]
    column = inputs["column_payoffs"]
    pure: set[tuple[str, str]] = set()
    for i, row_action in enumerate(actions):
        for j, column_action in enumerate(actions):
            row_best = row[i][j] >= max(row[k][j] for k in range(2)) - tolerance
            column_best = column[i][j] >= max(column[i][k] for k in range(2)) - tolerance
            if row_best and column_best:
                pure.add((row_action, column_action))
    observed = payload["pure_equilibria"]
    if not isinstance(observed, list) or any(
        not isinstance(item, list) or len(item) != 2 or any(not isinstance(value, str) for value in item)
        for item in observed
    ):
        return GradeResult(False, "pure_equilibria must be an array of two-action arrays", failure_code="schema")
    if len(observed) != len({tuple(item) for item in observed}) or {tuple(item) for item in observed} != pure:
        return GradeResult(False, "pure equilibrium set is incomplete or incorrect", failure_code="substantive")
    denominator = row[0][0] - row[0][1] - row[1][0] + row[1][1]
    if abs(denominator) <= tolerance:
        return GradeResult(False, "fixture has no unique interior mixing threshold", failure_code="grader")
    mixed = (row[1][1] - row[0][1]) / denominator
    if not _close(payload["mixed_adopt_probability"], mixed, tolerance):
        return GradeResult(False, "mixed adoption probability is wrong", {"oracle": mixed}, "substantive")
    return GradeResult(True, "complete pure set and mixed indifference probability are correct")


def _grade_cycle_evidence(payload: dict[str, Any], inputs: dict[str, Any]) -> GradeResult:
    fields = {"identified", "reason_code", "citations"}
    if error := _exact_fields(payload, fields):
        return GradeResult(False, error, failure_code="schema")
    if payload["identified"] is not False:
        return GradeResult(False, "the packet has no allowed-versus-forbidden concentration comparison", failure_code="substantive")
    if payload["reason_code"] != "no_allowed_vs_forbidden_concentration_comparison":
        return GradeResult(False, "reason_code does not name the uniquely defined missing comparison", failure_code="contract")
    expected_ids = set(inputs["required_citations"])
    citations = payload["citations"]
    if not isinstance(citations, list) or any(not isinstance(item, str) for item in citations):
        return GradeResult(False, "citations must be document IDs", failure_code="schema")
    if len(citations) != len(set(citations)) or set(citations) != expected_ids:
        return GradeResult(False, "citation set is incomplete, duplicated, or unsupported", failure_code="substantive")
    return GradeResult(True, "correct identification verdict, unique reason, and evidence set")


def _grade_simpson(payload: dict[str, Any], inputs: dict[str, Any]) -> GradeResult:
    fields = {"aggregate_direction", "within_strata_direction", "conclusion", "citations"}
    if error := _exact_fields(payload, fields):
        return GradeResult(False, error, failure_code="schema")
    strata = inputs["strata"]
    t_success = sum(row["treatment_success"] for row in strata)
    t_total = sum(row["treatment_total"] for row in strata)
    c_success = sum(row["control_success"] for row in strata)
    c_total = sum(row["control_total"] for row in strata)
    aggregate = "treatment_higher" if t_success / t_total > c_success / c_total else "control_higher"
    signs = [
        row["treatment_success"] / row["treatment_total"]
        > row["control_success"] / row["control_total"]
        for row in strata
    ]
    within = "treatment_higher_both" if all(signs) else "not_treatment_higher_both"
    expected = {
        "aggregate_direction": aggregate,
        "within_strata_direction": within,
        "conclusion": "aggregation_confounded" if aggregate == "control_higher" and all(signs) else "no_reversal",
    }
    for field, wanted in expected.items():
        if payload[field] != wanted:
            return GradeResult(False, f"{field} is wrong", {"oracle": expected}, "substantive")
    citations = payload["citations"]
    expected_ids = set(inputs["required_citations"])
    if not isinstance(citations, list) or len(citations) != len(set(citations)) or set(citations) != expected_ids:
        return GradeResult(False, "citation set is incomplete, duplicated, or unsupported", failure_code="substantive")
    return GradeResult(True, "aggregate reversal, stratified direction, and evidence IDs are correct")


def _grade_code(
    payload: dict[str, Any],
    task: dict[str, Any],
    tolerance: float,
    *,
    code_runner: CodeRunner,
    grading_deadline: float | None,
    monotonic: Callable[[], float],
) -> GradeResult:
    if error := _exact_fields(payload, {"source"}):
        return GradeResult(False, error, failure_code="schema")
    source = payload["source"]
    function_name = task["starter"]["function"]
    try:
        validate_candidate_source(source, function_name)
    except ValueError as exc:
        return GradeResult(False, str(exc), failure_code="unsafe_source")
    case_results: list[dict[str, Any]] = []
    details: dict[str, Any] = {
        "sandbox": "bubblewrap-fresh-process-per-case",
        "function_name": function_name,
        "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "cases": case_results,
    }
    for case in task["grader"]["inputs"]["cases"]:
        timeout_s = float(case["timeout_s"])
        if grading_deadline is not None and monotonic() + timeout_s > grading_deadline:
            return GradeResult(
                False,
                f"grading budget cannot admit {case['id']}",
                details,
                "inconclusive_grader",
            )
        try:
            result = code_runner(
                source,
                function_name,
                case["arguments"],
                timeout_s=timeout_s,
            )
        except SandboxUnavailable as exc:
            return GradeResult(
                False,
                str(exc),
                details,
                "inconclusive_grader",
            )
        if result.status == "returned":
            observation = {"status": "returned", "value": result.value}
        elif result.status == "exception":
            observation = {
                "status": "exception",
                "exception_type": result.exception_type,
            }
        else:
            observation = {"status": result.status, "detail": result.detail}
        oracle = (
            {"status": "exception", "exception_type": case["expected_exception"]}
            if "expected_exception" in case
            else {"status": "returned", "value": case["expected_return"]}
        )
        row = {
            "case_id": case["id"],
            "status": result.status,
            "timeout_s": timeout_s,
            "arguments_sha256": _receipt_sha(case["arguments"]),
            "observation": observation,
            "observation_sha256": _receipt_sha(observation),
            "oracle_sha256": _receipt_sha(oracle),
            "input_mutated": result.input_mutated,
            "passed": False,
        }
        case_results.append(row)
        if result.input_mutated:
            return GradeResult(
                False,
                f"{case['id']} mutated its arguments",
                details,
                "substantive",
            )
        if "expected_exception" in case:
            passed = result.status == "exception" and result.exception_type == case["expected_exception"]
        else:
            passed = result.status == "returned" and _equivalent(result.value, case["expected_return"], tolerance)
        row["passed"] = passed and not bool(result.input_mutated)
        if not passed:
            row["expected_kind"] = "exception" if "expected_exception" in case else "return"
            return GradeResult(
                False,
                f"{case['id']} failed its behavioral oracle",
                details,
                "substantive",
            )
    return GradeResult(
        True,
        "all fresh-process behavioral cases passed",
        details,
    )


def grade_task(
    task: dict[str, Any],
    payload: Any,
    *,
    code_runner: CodeRunner | None = None,
    grading_deadline: float | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> GradeResult:
    grader = task["grader"]
    kind = grader["kind"]
    inputs = grader["inputs"]
    tolerance = float(grader["absolute_tolerance"])
    if kind == "delegation_hhi":
        return _grade_delegation_hhi(payload, inputs, tolerance)
    if kind == "sortition_representation":
        return _grade_sortition(payload, inputs, tolerance)
    if kind == "social_choice":
        return _grade_social_choice(payload, inputs, tolerance)
    if kind == "coordination_equilibrium":
        return _grade_coordination(payload, inputs, tolerance)
    if kind == "evidence_cycle_boundary":
        return _grade_cycle_evidence(payload, inputs)
    if kind == "evidence_simpson":
        return _grade_simpson(payload, inputs)
    if kind == "code_function":
        return _grade_code(
            payload,
            task,
            tolerance,
            code_runner=run_case if code_runner is None else code_runner,
            grading_deadline=grading_deadline,
            monotonic=monotonic,
        )
    return GradeResult(False, f"unsupported grader kind {kind!r}", failure_code="grader")
