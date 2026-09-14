"""Oracle and plausible-error tests for every portfolio grader."""

from __future__ import annotations

import copy

import pytest

from bench.weekly_upgrade_portfolio.graders import grade_task
from bench.weekly_upgrade_portfolio.manifest import load_manifest


@pytest.fixture(scope="module")
def tasks():
    return {task["id"]: task for task in load_manifest()["tasks"]}


VALID = {
    "SCI-D075-LD-POWER-001": {
        "baseline_hhi": 0.25,
        "delegated_hhi": 0.34375,
        "delta": 0.09375,
        "direction": "increased",
    },
    "SCI-D075-SORTITION-001": {
        "expected_a_seats": 6,
        "expected_b_seats": 6,
        "expected_a_share": 0.5,
        "population_a_share": 0.6,
        "a_representation_bias": -0.1,
    },
    "SCI-D075-SOCIAL-CHOICE-001": {
        "plurality_winner": "A",
        "condorcet_winner": "B",
        "b_over_a_margin": 1,
        "b_over_c_margin": 3,
    },
    "SCI-GT-COORDINATION-001": {
        "pure_equilibria": [["status_quo", "status_quo"], ["adopt", "adopt"]],
        "mixed_adopt_probability": 0.75,
    },
    "EVID-D075-CYCLE-BOUNDARY-001": {
        "identified": False,
        "reason_code": "no_allowed_vs_forbidden_concentration_comparison",
        "citations": ["C2", "C1"],
    },
    "EVID-GT-SIMPSON-001": {
        "aggregate_direction": "control_higher",
        "within_strata_direction": "treatment_higher_both",
        "conclusion": "aggregation_confounded",
        "citations": ["STRATA", "AGG"],
    },
}

DELEGATION_SOURCE = '''def resolve(ballots):
    totals = {"A": 0, "B": 0}
    exhausted = []
    for origin in ballots:
        current = origin
        seen = set()
        while True:
            if current in seen:
                exhausted.append(origin)
                break
            seen.add(current)
            if current not in ballots:
                exhausted.append(origin)
                break
            value = ballots[current]
            if value == "A" or value == "B":
                totals[value] = totals[value] + 1
                break
            if isinstance(value, str) and value.startswith("->") and len(value) > 2:
                current = value[2:]
            else:
                exhausted.append(origin)
                break
    return {"totals": totals, "exhausted": sorted(exhausted)}
'''

REGRET_SOURCE = '''def external_regret(payoffs, chosen):
    if not isinstance(payoffs, list) or not payoffs or not isinstance(chosen, list) or len(chosen) != len(payoffs):
        raise ValueError()
    actions = len(payoffs[0])
    if actions == 0:
        raise ValueError()
    fixed = [0] * actions
    earned = 0
    for turn in range(len(payoffs)):
        row = payoffs[turn]
        index = chosen[turn]
        if not isinstance(row, list) or len(row) != actions:
            raise ValueError()
        if isinstance(index, bool) or not isinstance(index, int) or index < 0 or index >= actions:
            raise ValueError()
        for action in range(actions):
            value = row[action]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError()
            fixed[action] = fixed[action] + value
        earned = earned + row[index]
    best = max(fixed)
    total = best - earned
    return {"chosen_total": earned, "best_fixed_total": best, "total_external_regret": total, "average_external_regret": total / len(payoffs)}
'''


@pytest.mark.parametrize("task_id", sorted(VALID))
def test_structured_oracles_pass(task_id, tasks):
    assert grade_task(tasks[task_id], VALID[task_id]).passed


@pytest.mark.parametrize(
    ("task_id", "field", "wrong"),
    [
        ("SCI-D075-LD-POWER-001", "delegated_hhi", 22),
        ("SCI-D075-LD-POWER-001", "direction", "decreased"),
        ("SCI-D075-SORTITION-001", "expected_a_share", 0.6),
        ("SCI-D075-SOCIAL-CHOICE-001", "condorcet_winner", "A"),
        ("SCI-D075-SOCIAL-CHOICE-001", "b_over_a_margin", -1),
        ("SCI-GT-COORDINATION-001", "mixed_adopt_probability", 0.25),
        ("EVID-D075-CYCLE-BOUNDARY-001", "identified", True),
        ("EVID-GT-SIMPSON-001", "conclusion", "no_reversal"),
    ],
)
def test_named_plausible_errors_fail(task_id, field, wrong, tasks):
    payload = copy.deepcopy(VALID[task_id])
    payload[field] = wrong
    result = grade_task(tasks[task_id], payload)
    assert not result.passed
    assert result.failure_code in {"substantive", "contract"}


def test_coordination_oracle_recomputes_after_action_relabel_and_payoff_scale(tasks):
    task = copy.deepcopy(tasks["SCI-GT-COORDINATION-001"])
    inputs = task["grader"]["inputs"]
    inputs["actions"] = ["delegate", "direct"]
    inputs["row_payoffs"] = [[13, 1], [10, 10]]
    inputs["column_payoffs"] = [[13, 10], [1, 10]]
    payload = {
        "pure_equilibria": [["delegate", "delegate"], ["direct", "direct"]],
        "mixed_adopt_probability": 0.75,
    }
    assert grade_task(task, payload).passed


def test_evidence_contracts_use_explicit_mutually_exclusive_values(tasks):
    cycle = tasks["EVID-D075-CYCLE-BOUNDARY-001"]["prompt"]
    assert '["effect_identified","no_allowed_vs_forbidden_concentration_comparison"]' in cycle
    assert "Here effect_identified means" in cycle
    simpson = tasks["EVID-GT-SIMPSON-001"]["prompt"]
    assert '["aggregation_confounded","no_reversal"]' in simpson


@pytest.mark.parametrize(
    ("task_id", "citations"),
    [
        ("EVID-D075-CYCLE-BOUNDARY-001", ["C1"]),
        ("EVID-D075-CYCLE-BOUNDARY-001", ["C1", "C2", "C2"]),
        ("EVID-GT-SIMPSON-001", ["AGG", "MADE_UP"]),
    ],
)
def test_evidence_omissions_duplicates_and_invented_ids_fail(task_id, citations, tasks):
    payload = copy.deepcopy(VALID[task_id])
    payload["citations"] = citations
    assert not grade_task(tasks[task_id], payload).passed


def test_extra_json_field_is_a_protocol_failure(tasks):
    payload = {**VALID["SCI-D075-LD-POWER-001"], "explanation": "looks right"}
    result = grade_task(tasks["SCI-D075-LD-POWER-001"], payload)
    assert not result.passed
    assert result.failure_code == "schema"


@pytest.mark.parametrize(
    ("task_id", "source"),
    [
        ("CODE-D075-DELEGATION-001", DELEGATION_SOURCE),
        ("CODE-GT-REGRET-001", REGRET_SOURCE),
    ],
)
def test_code_oracles_execute_in_fresh_processes(task_id, source, tasks):
    result = grade_task(tasks[task_id], {"source": source})
    assert result.passed, result
    assert result.details["function_name"] == tasks[task_id]["starter"]["function"]
    assert all(case["passed"] for case in result.details["cases"])
    assert all("oracle_sha256" in case for case in result.details["cases"])
    assert all("expected_return" not in case for case in result.details["cases"])


def test_injected_code_observations_are_regraded_by_parent_oracle(tasks):
    calls = []

    def wrong_runner(source, function_name, arguments, *, timeout_s):
        from bench.weekly_upgrade_portfolio.code_sandbox import SandboxResult

        calls.append((function_name, arguments, timeout_s))
        return SandboxResult("returned", value={"forged": "PASS"}, input_mutated=False)

    result = grade_task(
        tasks["CODE-D075-DELEGATION-001"],
        {"source": DELEGATION_SOURCE},
        code_runner=wrong_runner,
    )
    assert not result.passed
    assert result.failure_code == "substantive"
    assert len(calls) == 1
    assert result.details["cases"][0]["passed"] is False


def test_grading_deadline_refuses_case_before_invocation(tasks):
    invoked = False

    def runner(*args, **kwargs):
        nonlocal invoked
        invoked = True
        raise AssertionError("must not run")

    result = grade_task(
        tasks["CODE-D075-DELEGATION-001"],
        {"source": DELEGATION_SOURCE},
        code_runner=runner,
        grading_deadline=2.9,
        monotonic=lambda: 0.0,
    )
    assert not result.passed
    assert result.failure_code == "inconclusive_grader"
    assert not invoked
