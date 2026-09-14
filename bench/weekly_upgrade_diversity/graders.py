"""Finite, objective proposal graders for the diversity experiment."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProposalGrade:
    valid: bool
    reason: str
    canonical: str | None = None


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _exact_object(value: Any, keys: set[str]) -> dict[str, Any] | None:
    return value if isinstance(value, dict) and set(value) == keys else None


def _integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _pure_nash(proposal: Any, inputs: dict[str, Any]) -> ProposalGrade:
    row = _exact_object(proposal, {"row_action", "column_action"})
    if row is None:
        return ProposalGrade(False, "proposal schema differs")
    actions = inputs["actions"]
    try:
        i = actions.index(row["row_action"])
        j = actions.index(row["column_action"])
    except ValueError:
        return ProposalGrade(False, "unknown action")
    row_payoffs = inputs["row_payoffs"]
    column_payoffs = inputs["column_payoffs"]
    row_best = row_payoffs[i][j] == max(matrix_row[j] for matrix_row in row_payoffs)
    column_best = column_payoffs[i][j] == max(column_payoffs[i])
    if not row_best or not column_best:
        return ProposalGrade(False, "profile admits a profitable unilateral deviation")
    return ProposalGrade(True, "pure Nash equilibrium", _canonical(row))


def _ballot_counterexample(proposal: Any, inputs: dict[str, Any]) -> ProposalGrade:
    rankings = inputs["rankings"]
    row = _exact_object(proposal, set(rankings))
    if row is None or any(not _integer(row[key]) or row[key] < 0 for key in rankings):
        return ProposalGrade(False, "ballot counts must be nonnegative integers for every ranking")
    if sum(row.values()) != inputs["voters"]:
        return ProposalGrade(False, "ballot counts do not sum to the voter total")
    candidates = inputs["candidates"]
    plurality = {candidate: 0 for candidate in candidates}
    pairwise = {
        (left, right): 0
        for left in candidates
        for right in candidates
        if left != right
    }
    for ranking, count in row.items():
        plurality[ranking[0]] += count
        positions = {candidate: ranking.index(candidate) for candidate in candidates}
        for left, right in pairwise:
            if positions[left] < positions[right]:
                pairwise[(left, right)] += count
    plurality_winners = [
        candidate for candidate, count in plurality.items() if count == max(plurality.values())
    ]
    target_plurality = inputs["target_plurality"]
    target_condorcet = inputs["target_condorcet"]
    condorcet = [
        candidate
        for candidate in candidates
        if all(
            pairwise[(candidate, other)] > pairwise[(other, candidate)]
            for other in candidates
            if other != candidate
        )
    ]
    if plurality_winners != [target_plurality] or condorcet != [target_condorcet]:
        return ProposalGrade(False, "profile misses the unique plurality/Condorcet targets")
    return ProposalGrade(True, "valid social-choice counterexample", _canonical(row))


def _resolve_delegations(ballots: dict[str, str]) -> tuple[dict[str, int], list[str]]:
    totals = {"A": 0, "B": 0}
    exhausted: list[str] = []
    for origin in ballots:
        current = origin
        seen: set[str] = set()
        while True:
            if current in seen or current not in ballots:
                exhausted.append(origin)
                break
            seen.add(current)
            value = ballots[current]
            if value in totals:
                totals[value] += 1
                break
            if value.startswith("->") and len(value) > 2:
                current = value[2:]
            else:
                exhausted.append(origin)
                break
    return totals, sorted(exhausted)


def _delegation(proposal: Any, inputs: dict[str, Any]) -> ProposalGrade:
    voters = inputs["voters"]
    row = _exact_object(proposal, set(voters))
    allowed = set(inputs["allowed_values"])
    if row is None or any(not isinstance(row[key], str) or row[key] not in allowed for key in voters):
        return ProposalGrade(False, "delegation graph uses a missing voter or value")
    totals, exhausted = _resolve_delegations(row)
    if totals != inputs["target_totals"] or exhausted != inputs["target_exhausted"]:
        return ProposalGrade(False, "resolved graph misses the target outcome")
    return ProposalGrade(True, "valid delegation graph", _canonical(row))


def _coordination_matrix(proposal: Any, inputs: dict[str, Any]) -> ProposalGrade:
    row = _exact_object(proposal, {"a", "b", "c", "d"})
    allowed = set(inputs["allowed_payoffs"])
    if row is None or any(not _integer(row[key]) or row[key] not in allowed for key in row):
        return ProposalGrade(False, "matrix entries must be allowed integers")
    a, b, c, d = (row[key] for key in ("a", "b", "c", "d"))
    if not (a > c and d > b):
        return ProposalGrade(False, "both diagonal profiles are not strict equilibria")
    denominator = a - b - c + d
    if denominator == 0:
        return ProposalGrade(False, "mixed equilibrium is undefined")
    mixed = (d - b) / denominator
    if not math.isclose(mixed, inputs["target_mixed_probability"], abs_tol=1e-12):
        return ProposalGrade(False, "mixed probability misses the target")
    return ProposalGrade(True, "valid coordination matrix", _canonical(row))


def _minimal_winning(proposal: Any, inputs: dict[str, Any]) -> ProposalGrade:
    row = _exact_object(proposal, {"coalition"})
    if row is None or not isinstance(row["coalition"], list):
        return ProposalGrade(False, "coalition schema differs")
    coalition = row["coalition"]
    weights = inputs["weights"]
    if (
        not coalition
        or any(not isinstance(player, str) or player not in weights for player in coalition)
        or len(coalition) != len(set(coalition))
    ):
        return ProposalGrade(False, "coalition has unknown or duplicate players")
    total = sum(weights[player] for player in coalition)
    quota = inputs["quota"]
    if total < quota or any(total - weights[player] >= quota for player in coalition):
        return ProposalGrade(False, "coalition is not minimal winning")
    normalized = {"coalition": sorted(coalition)}
    return ProposalGrade(True, "minimal winning coalition", _canonical(normalized))


_GRADERS = {
    "pure_nash": _pure_nash,
    "ballot_counterexample": _ballot_counterexample,
    "delegation_graph": _delegation,
    "coordination_matrix": _coordination_matrix,
    "minimal_winning_coalition": _minimal_winning,
}


def proposal_shape_error(task: dict[str, Any], proposal: Any) -> str | None:
    """Return an exact JSON-shape failure without grading feasibility.

    This is used only by the versioned follow-through scaffold.  The frozen
    dev-v0 path continues to send every parsed value directly to its objective
    grader, preserving its original scoring contract.
    """

    kind = task["grader"]["kind"]
    inputs = task["grader"]["inputs"]
    if kind == "pure_nash":
        row = _exact_object(proposal, {"row_action", "column_action"})
        if row is None or any(not isinstance(row[key], str) for key in row):
            return "proposal must contain exactly two string action fields"
    elif kind == "ballot_counterexample":
        row = _exact_object(proposal, set(inputs["rankings"]))
        if row is None or any(not _integer(row[key]) for key in row):
            return "proposal must contain one integer for every ranking"
    elif kind == "delegation_graph":
        row = _exact_object(proposal, set(inputs["voters"]))
        if row is None or any(not isinstance(row[key], str) for key in row):
            return "proposal must contain one string value for every voter"
    elif kind == "coordination_matrix":
        row = _exact_object(proposal, {"a", "b", "c", "d"})
        if row is None or any(not _integer(row[key]) for key in row):
            return "proposal must contain exactly four integer payoff fields"
    elif kind == "minimal_winning_coalition":
        row = _exact_object(proposal, {"coalition"})
        if (
            row is None
            or not isinstance(row["coalition"], list)
            or any(not isinstance(player, str) for player in row["coalition"])
        ):
            return "proposal coalition must be an array of player strings"
    else:
        return "proposal grader kind is unsupported"
    return None


def grade_proposal(task: dict[str, Any], proposal: Any) -> ProposalGrade:
    """Grade one proposal against the task's finite objective contract."""
    kind = task["grader"]["kind"]
    grader = _GRADERS.get(kind)
    if grader is None:
        return ProposalGrade(False, f"unsupported grader {kind!r}")
    return grader(proposal, task["grader"]["inputs"])


def grade_set(
    task: dict[str, Any], proposals: list[Any], selected_index: Any
) -> dict[str, Any]:
    """Score diversity and objective selection without an LLM judge."""
    rows = [grade_proposal(task, proposal) for proposal in proposals]
    valid_indices = [index for index, row in enumerate(rows) if row.valid]
    unique = {row.canonical for row in rows if row.valid and row.canonical is not None}
    selected_valid = (
        _integer(selected_index)
        and 0 <= selected_index < len(rows)
        and rows[selected_index].valid
    )
    selection_correct = selected_valid if valid_indices else selected_index is None
    return {
        "proposal_count": len(proposals),
        "valid_count": len(valid_indices),
        "valid_unique_count": len(unique),
        "valid_indices": valid_indices,
        "selected_index": selected_index,
        "selected_valid": bool(selected_valid),
        "selection_correct": bool(selection_correct),
        "recovered_from_invalid_candidates": bool(
            selected_valid and len(valid_indices) < len(rows)
        ),
        "proposal_grades": [
            {"valid": row.valid, "reason": row.reason, "canonical": row.canonical}
            for row in rows
        ],
        "task_success": bool(valid_indices and selection_correct),
    }


def grade_set_v1(
    task: dict[str, Any], proposals: list[Any], selected_index: Any
) -> dict[str, Any]:
    """Score the follow-through scaffold's deterministic selector contract.

    The validator is instructed to select the lowest-numbered objectively valid
    slot.  Requiring that exact answer makes selector correctness independently
    reconstructible and prevents arbitrary preference among feasible outputs.
    """

    grade = grade_set(task, proposals, selected_index)
    valid_indices = grade["valid_indices"]
    expected = valid_indices[0] if valid_indices else None
    selection_exact = (
        (selected_index is None and expected is None)
        or (
            _integer(selected_index)
            and expected is not None
            and selected_index == expected
        )
    )
    return {
        **grade,
        "expected_selected_index": expected,
        "selection_exact": bool(selection_exact),
        "task_success": bool(valid_indices and selection_exact),
    }
