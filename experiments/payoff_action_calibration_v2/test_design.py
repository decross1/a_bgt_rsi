from __future__ import annotations

import copy
import json

import pytest

from experiments.payoff_action_calibration import runner as v1
from experiments.payoff_action_calibration_v2 import design


@pytest.fixture(scope="module")
def cells():
    return design.panel()


def response(cell, *, optimal=True):
    return json.dumps(
        {
            "probe": cell["expected_probe"],
            "actions": cell["controls"]["oracle_plan" if optimal else "myopic_plan"],
        }
    )


def grade(text, cell):
    return design.final_grade(text, "returned", {"finish_reason": "stop"}, [], cell)


def test_panel_has_new_identities_and_independently_checked_controls(cells):
    prior = v1.panel()
    assert not {c["cell_id"] for c in cells} & {c["cell_id"] for c in prior}
    assert not {c["task_sha256"] for c in cells} & {c["task_sha256"] for c in prior}
    assert {c["endowment"] for c in cells} == {22, 26, 30, 34}
    assert all(c["controls"]["dp_matches_exhaustive"] for c in cells)
    assert all(c["controls"]["future_dependent_rounds_1_indexed"] for c in cells)


@pytest.mark.parametrize("index", range(4))
def test_final_strategy_correctness_is_separate_from_terminal_contract(cells, index):
    cell = cells[index]
    correct, wrong = (
        grade(response(cell), cell),
        grade(response(cell, optimal=False), cell),
    )
    assert correct["contract"]["substantive_correct"] == "pass"
    assert wrong["contract"]["terminal_contract_valid"] == "pass"
    assert wrong["contract"]["substantive_correct"] == "fail"
    assert wrong["diagnostic"]["zero_regret"] is False
    assert "actions" not in wrong["diagnostic"]["response_score"]


def test_wrong_arithmetic_is_substance_not_malformed_json(cells):
    value = json.loads(response(cells[0]))
    value["probe"]["focal_payoff"] = {
        "numerator": 999,
        "denominator": 1,
        "canonical": "999",
    }
    result = grade(json.dumps(value), cells[0])["contract"]
    assert result["terminal_contract_valid"] == "pass"
    assert result["substantive_correct"] == "fail"


def test_malformed_final_does_not_claim_observed_bad_strategy(cells):
    result = grade("not json", cells[0])["contract"]
    assert result["terminal_contract_valid"] == "fail"
    assert result["substantive_correct"] == "unassessed"
    assert "strategy_suboptimal" not in result["failure_codes"]


def test_grader_error_remains_unassessed(cells, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("grader unavailable")

    monkeypatch.setattr(design.legacy, "_grade_final", broken)
    result = grade(response(cells[0]), cells[0])
    assert result["contract"]["terminal_protocol_valid"]
    assert result["contract"]["terminal_contract_valid"] == "unassessed"
    assert result["contract"]["substantive_correct"] == "unassessed"
    assert result["diagnostic"] == {}


def test_table_uses_parsed_arguments_and_validates_without_calling_executor(
    cells, monkeypatch
):
    args = dict(design.expectation(cells[0], "table").expected_arguments)
    result = design.table_executor(args)
    changed_args = {**args, "E": args["E"] + 1}
    assert design.table_executor(changed_args) != result

    def forbidden(*args, **kwargs):
        raise AssertionError("validator must not invoke live executor")

    monkeypatch.setattr(design, "table_executor", forbidden)
    assert design.table_result_valid(result, args)
    assert not design.table_result_valid(result, changed_args)
    forged = copy.deepcopy(result)
    forged["rows"][0]["focal_action"] = False
    assert not design.table_result_valid(forged, args)
    forged = copy.deepcopy(result)
    forged["rows"][0]["focal_payoff"] = "123"
    assert not design.table_result_valid(forged, args)


@pytest.mark.parametrize(
    "mutation",
    [
        {"E": True},
        {"players": False},
        {"extra": 1},
        {"m_den": 0},
    ],
)
def test_table_rejects_invalid_argument_types(cells, mutation):
    args = dict(design.expectation(cells[0], "table").expected_arguments)
    result = design.table_executor(args)
    assert not design.table_result_valid(result, {**args, **mutation})
    assert not design.table_result_valid(result, {})


@pytest.mark.parametrize(
    "key,value",
    [
        ("focal_seat", False),
        ("formula_version", 3),
        ("contributor_count", False),
        ("strategy_advice_included", 0),
        ("evaluated_joint_action", [False, 0, 0, 0]),
    ],
)
def test_probe_representation_failure_is_not_substantive(cells, key, value):
    payload = json.loads(response(cells[0]))
    payload["probe"][key] = value
    result = grade(json.dumps(payload), cells[0])["contract"]
    assert result["terminal_contract_valid"] == "fail"
    assert result["substantive_correct"] == "unassessed"


def test_table_rejects_exponential_rational_before_parsing(cells):
    args = dict(design.expectation(cells[0], "table").expected_arguments)
    result = design.table_executor(args)
    result["rows"][0]["focal_payoff"] = "1e1000000000"
    assert not design.table_result_valid(result, args)
