from __future__ import annotations

import copy
import json

import pytest

from experiments.payoff_action_calculator import calculator
from experiments.payoff_action_calibration_v2.contract import (
    CONTINUATION_POLICY,
    PRETOOL_CONTENT_LIMIT_BYTES,
    ContractError,
    FinalContentAssessment,
    ToolExpectation,
    build_empty_content_continuation,
    calculator_result_contract_valid,
    classify_tool_turn,
    execute_once,
    grade_final_turn,
)

ARGS = {
    "E": 10,
    "m_num": 3,
    "m_den": 2,
    "joint_action": [1, 0, 1, 0],
    "focal_seat": 0,
}
TOOL_NAME = "public_goods_joint_action_payoff"
EXPECTATION = ToolExpectation(
    name=TOOL_NAME,
    argument_contract="calculator",
    expected_arguments=ARGS,
)


def native_call(*, arguments: str | None = None, name: str = TOOL_NAME) -> dict:
    return {
        "id": "call-1",
        "type": "function",
        "function": {
            "name": name,
            "arguments": arguments if arguments is not None else json.dumps(ARGS),
        },
    }


def classify(**overrides):
    values = {
        "status": "returned",
        "receipt": {"finish_reason": "tool_calls"},
        "tool_calls": [native_call()],
        "content": None,
        "reasoning_content": None,
        "expectation": EXPECTATION,
    }
    values.update(overrides)
    return classify_tool_turn(**values)


def successful_execution(classification=None, *, calls=None):
    classification = classification or classify()
    calls = [] if calls is None else calls

    def executor(arguments):
        calls.append(copy.deepcopy(arguments))
        return calculator.calculate(arguments)

    return execute_once(
        classification,
        executor=executor,
        result_validator=calculator_result_contract_valid,
    )


def test_classification_is_pure_and_never_calls_the_calculator(monkeypatch):
    calls = []

    def forbidden(_arguments):
        calls.append("called")
        raise AssertionError("classification executed the calculator")

    monkeypatch.setattr(calculator, "calculate", forbidden)
    result = classify(content="I will use the exact payoff tool.")
    assert result.execution_eligible is True
    assert result.strict_v1_comparable is False
    assert calls == []


@pytest.mark.parametrize(
    ("status", "receipt", "expected_code", "receipt_state"),
    [
        ("timeout", {"finish_reason": "tool_calls"}, "transport_timeout", "pass"),
        ("cancelled", {"finish_reason": "tool_calls"}, "transport_cancelled", "pass"),
        ("transport_error", {"finish_reason": "tool_calls"}, "transport_error", "pass"),
        ("returned", None, "receipt_incomplete", "fail"),
        ("returned", {}, "receipt_incomplete", "fail"),
    ],
)
def test_transport_and_receipt_failures_do_not_hide_apparent_call_structure(
    status, receipt, expected_code, receipt_state
):
    result = classify(status=status, receipt=receipt)
    assert result.execution_eligible is False
    assert expected_code in result.failure_codes
    assert result.receipt_complete == receipt_state
    assert result.single_tool_call == "pass"
    assert result.call_shape_valid == "pass"
    assert result.arguments_exact == "pass"


def test_true_no_call_bypass_is_distinct():
    result = classify(
        receipt={"finish_reason": "stop"},
        tool_calls=[],
        content="An answer that bypassed the required tool.",
    )
    assert result.execution_eligible is False
    assert result.call_count == 0
    assert result.finish_reason_tool_calls == "fail"
    assert result.single_tool_call == "fail"
    assert "no_call_bypass" in result.failure_codes


@pytest.mark.parametrize(
    ("tool_calls", "code", "field", "state"),
    [
        ({}, "tool_calls_container_invalid", "tool_calls_container", "fail"),
        ([], "single_tool_call_required", "single_tool_call", "fail"),
        ([native_call(), native_call()], "single_tool_call_required", "single_tool_call", "fail"),
        (
            [{**native_call(), "extra": True}],
            "tool_call_shape_invalid",
            "call_shape_valid",
            "fail",
        ),
        (
            [{**native_call(), "id": ""}],
            "tool_call_shape_invalid",
            "call_shape_valid",
            "fail",
        ),
        (
            [{**native_call(), "type": "other"}],
            "tool_call_shape_invalid",
            "call_shape_valid",
            "fail",
        ),
        (
            [{**native_call(), "function": {"name": TOOL_NAME}}],
            "tool_call_shape_invalid",
            "call_shape_valid",
            "fail",
        ),
    ],
)
def test_call_envelope_boundaries(tool_calls, code, field, state):
    result = classify(tool_calls=tool_calls)
    assert result.execution_eligible is False
    assert code in result.failure_codes
    assert getattr(result, field) == state


def test_wrong_tool_name_remains_separate_from_valid_arguments():
    result = classify(tool_calls=[native_call(name="wrong_tool")])
    assert result.call_shape_valid == "pass"
    assert result.tool_name_valid == "fail"
    assert result.arguments_json_valid == "pass"
    assert result.arguments_contract_valid == "pass"
    assert result.arguments_exact == "pass"
    assert result.failure_codes == ("tool_name_wrong",)


@pytest.mark.parametrize(
    ("arguments", "code", "json_state", "contract_state", "exact_state"),
    [
        ("{", "arguments_json_invalid", "fail", "unassessed", "unassessed"),
        (
            '{"E":10,"E":10,"m_num":3,"m_den":2,"joint_action":[1,0,1,0],"focal_seat":0}',
            "arguments_json_invalid",
            "fail",
            "unassessed",
            "unassessed",
        ),
        (
            '{"E":NaN,"m_num":3,"m_den":2,"joint_action":[1,0,1,0],"focal_seat":0}',
            "arguments_json_invalid",
            "fail",
            "unassessed",
            "unassessed",
        ),
        (
            '{"E":1e999,"m_num":3,"m_den":2,"joint_action":[1,0,1,0],"focal_seat":0}',
            "arguments_json_invalid",
            "fail",
            "unassessed",
            "unassessed",
        ),
        (
            json.dumps({key: value for key, value in ARGS.items() if key != "focal_seat"}),
            "arguments_contract_invalid",
            "pass",
            "fail",
            "unassessed",
        ),
        (
            json.dumps({**ARGS, "E": True}),
            "arguments_contract_invalid",
            "pass",
            "fail",
            "unassessed",
        ),
        (
            json.dumps({**ARGS, "m_num": 6, "m_den": 4}),
            "arguments_contract_invalid",
            "pass",
            "fail",
            "unassessed",
        ),
        (
            json.dumps({**ARGS, "E": 11}),
            "arguments_wrong",
            "pass",
            "pass",
            "fail",
        ),
    ],
)
def test_argument_boundaries(arguments, code, json_state, contract_state, exact_state):
    result = classify(tool_calls=[native_call(arguments=arguments)])
    assert result.execution_eligible is False
    assert code in result.failure_codes
    assert result.arguments_json_valid == json_state
    assert result.arguments_contract_valid == contract_state
    assert result.arguments_exact == exact_state


@pytest.mark.parametrize(
    ("content", "state", "byte_count", "eligible", "strict", "failure"),
    [
        (None, "null", 0, True, True, None),
        ("", "empty", 0, True, True, None),
        ("   ", "whitespace", 3, True, False, None),
        ("Calling the payoff tool.", "nonempty", 24, True, False, None),
        ("a" * 512, "nonempty", 512, True, False, None),
        ("a" * 513, "nonempty", 513, False, False, "pretool_content_too_large"),
        ("界" * 170, "nonempty", 510, True, False, None),
        ("界" * 171, "nonempty", 513, False, False, "pretool_content_too_large"),
        (7, "invalid_type", None, False, False, "pretool_content_type_invalid"),
        ("\ud800", "unencodable", None, False, False, "pretool_content_encoding_invalid"),
    ],
)
def test_pretool_content_uses_strict_utf8_byte_boundary(
    content, state, byte_count, eligible, strict, failure
):
    result = classify(content=content)
    assert PRETOOL_CONTENT_LIMIT_BYTES == 512
    assert result.pretool_content.state == state
    assert result.pretool_content.utf8_bytes == byte_count
    assert result.execution_eligible is eligible
    assert result.strict_v1_comparable is strict
    if failure is not None:
        assert failure in result.failure_codes


def test_reasoning_channel_is_separate_and_not_visible_leakage():
    result = classify(
        content="Ordinary visible acknowledgement.",
        reasoning_content="private intended reasoning channel",
    )
    assert result.execution_eligible is True
    assert result.reasoning_content.state == "nonempty"
    assert result.reasoning_content.raw == "private intended reasoning channel"
    assert result.pretool_content.raw == "Ordinary visible acknowledgement."
    assert result.failure_codes == ()


@pytest.mark.parametrize(
    ("reasoning", "code"),
    [
        ({"not": "text"}, "reasoning_content_type_invalid"),
        ("\ud800", "reasoning_content_encoding_invalid"),
    ],
)
def test_invalid_reasoning_channel_is_an_explicit_integrity_failure(reasoning, code):
    result = classify(reasoning_content=reasoning)
    assert result.execution_eligible is False
    assert code in result.failure_codes


def test_table_argument_contract_is_supported_without_running_a_tool():
    expected = {"E": 10, "m_num": 3, "m_den": 2, "players": 4}
    result = classify_tool_turn(
        status="returned",
        receipt={"finish_reason": "tool_calls"},
        tool_calls=[native_call(arguments=json.dumps(expected), name="public_goods_payoff_table")],
        content=None,
        reasoning_content=None,
        expectation=ToolExpectation(
            name="public_goods_payoff_table",
            argument_contract="table",
            expected_arguments=expected,
        ),
    )
    assert result.execution_eligible is True
    assert result.arguments_contract_valid == "pass"


def test_ineligible_turn_never_invokes_executor():
    calls = []
    result = execute_once(
        classify(content="x" * 513),
        executor=lambda arguments: calls.append(arguments),
        result_validator=lambda result, arguments: True,
    )
    assert calls == []
    assert result.execution_attempted is False
    assert result.execution_succeeded == "unassessed"
    assert result.failure_code == "execution_ineligible"


def test_eligible_turn_executes_exactly_once_and_retains_one_result():
    calls = []
    classification = classify(content="Using the exact calculator.")
    execution = successful_execution(classification, calls=calls)
    assert calls == [ARGS]
    assert classification.parsed_arguments == ARGS
    assert execution.execution_attempted is True
    assert execution.execution_succeeded == "pass"
    assert execution.result_contract_valid == "pass"
    assert execution.retained_result == calculator.calculate(ARGS)
    assert execution.retained_result_json_utf8 is not None
    assert execution.retained_result_sha256 is not None


def test_executor_receives_a_detached_argument_copy():
    classification = classify()

    def mutating_executor(arguments):
        arguments["joint_action"][0] = 0
        raise RuntimeError("synthetic failure")

    execution = execute_once(
        classification,
        executor=mutating_executor,
        result_validator=calculator_result_contract_valid,
    )
    assert execution.failure_code == "tool_execution_error"
    assert classification.parsed_arguments == ARGS


def test_retained_call_and_arguments_are_returned_as_detached_copies():
    classification = classify()
    arguments = classification.parsed_arguments
    call = classification.accepted_call
    assert arguments is not None and call is not None
    arguments["E"] = 999
    call["id"] = "redirected"
    assert classification.parsed_arguments == ARGS
    assert classification.accepted_call == native_call()


@pytest.mark.parametrize(
    ("executor", "validator", "code", "contract_state"),
    [
        (
            lambda _arguments: (_ for _ in ()).throw(RuntimeError("boom")),
            calculator_result_contract_valid,
            "tool_execution_error",
            "unassessed",
        ),
        (
            lambda _arguments: {"wrong": "shape"},
            calculator_result_contract_valid,
            "tool_result_contract_invalid",
            "fail",
        ),
        (
            lambda _arguments: {"value": float("nan")},
            lambda _result, _arguments: True,
            "tool_result_not_finite_json",
            "fail",
        ),
        (
            calculator.calculate,
            lambda _result, _arguments: (_ for _ in ()).throw(ValueError("bad validator")),
            "tool_result_validator_error",
            "fail",
        ),
    ],
)
def test_execution_failures_are_not_model_performance(executor, validator, code, contract_state):
    outcome = execute_once(classify(), executor=executor, result_validator=validator)
    assert outcome.execution_attempted is True
    assert outcome.execution_succeeded == "fail"
    assert outcome.result_contract_valid == contract_state
    assert outcome.failure_code == code


def test_scaffold_uses_empty_assistant_content_and_exact_retained_result_bytes():
    calls = []
    raw_content = "I will calculate before answering."
    classification = classify(content=raw_content)
    execution = successful_execution(classification, calls=calls)
    scaffold = build_empty_content_continuation(classification, execution)
    assistant, tool = scaffold.messages()

    assert calls == [ARGS]
    assert classification.pretool_content.raw == raw_content
    assert scaffold.continuation_content_policy == CONTINUATION_POLICY
    assert assistant["content"] == ""
    assert raw_content not in json.dumps(assistant)
    assert assistant["tool_calls"] == [classification.accepted_call]
    assert tool["content"].encode("utf-8") == execution.retained_result_json_utf8
    assert scaffold.retained_result_sha256 == execution.retained_result_sha256
    assert calls == [ARGS], "building and reading the scaffold must not re-execute"


def test_scaffold_rejects_a_result_from_a_different_eligible_call():
    first = classify()
    first_execution = successful_execution(first)
    different_arguments = {**ARGS, "E": 11}
    different = classify(
        tool_calls=[native_call(arguments=json.dumps(different_arguments))],
        expectation=ToolExpectation(
            name=TOOL_NAME,
            argument_contract="calculator",
            expected_arguments=different_arguments,
        ),
    )
    assert first.execution_binding_sha256 != different.execution_binding_sha256
    with pytest.raises(ContractError, match="does not belong"):
        build_empty_content_continuation(different, first_execution)


def test_unsuccessful_execution_cannot_construct_a_continuation():
    classification = classify()
    execution = execute_once(
        classification,
        executor=lambda _arguments: {"wrong": "shape"},
        result_validator=calculator_result_contract_valid,
    )
    with pytest.raises(ContractError, match="successful retained execution"):
        build_empty_content_continuation(classification, execution)


@pytest.mark.parametrize(
    ("status", "receipt", "tool_calls", "content", "code", "field"),
    [
        ("timeout", {"finish_reason": "stop"}, [], "{}", "transport_timeout", "transport_returned"),
        ("returned", None, [], "{}", "final_receipt_incomplete", "receipt_complete"),
        (
            "returned",
            {"finish_reason": "tool_calls"},
            [],
            "{}",
            "final_finish_reason_not_stop",
            "finish_reason_stop",
        ),
        (
            "returned",
            {"finish_reason": "stop"},
            [native_call()],
            "{}",
            "final_tool_call_present",
            "no_final_tool_calls",
        ),
        (
            "returned",
            {"finish_reason": "stop"},
            [],
            None,
            "final_content_type_invalid",
            "content_type_valid",
        ),
    ],
)
def test_final_protocol_failures_are_orthogonal(status, receipt, tool_calls, content, code, field):
    grader_calls = []
    grade = grade_final_turn(
        status=status,
        receipt=receipt,
        tool_calls=tool_calls,
        content=content,
        content_grader=lambda text: grader_calls.append(text) or FinalContentAssessment(True, True),
    )
    assert grade.terminal_protocol_valid is False
    assert grade.terminal_contract_valid == "unassessed"
    assert grade.substantive_correct == "unassessed"
    assert code in grade.failure_codes
    assert getattr(grade, field) == "fail"
    assert grader_calls == []


@pytest.mark.parametrize(
    ("content", "assessment", "contract", "substantive", "accepted", "code"),
    [
        ("correct", FinalContentAssessment(True, True), "pass", "pass", True, None),
        (
            "wrong action",
            FinalContentAssessment(True, False, ("wrong_action",)),
            "pass",
            "fail",
            True,
            "wrong_action",
        ),
        (
            "```json\n{}\n```",
            FinalContentAssessment(False, False, ("fenced_json",)),
            "fail",
            "unassessed",
            False,
            "fenced_json",
        ),
        (
            "<think>visible</think>{}",
            FinalContentAssessment(False, False, ("visible_reasoning_marker",)),
            "fail",
            "unassessed",
            False,
            "visible_reasoning_marker",
        ),
    ],
)
def test_final_contract_and_substantive_quality_are_independent(
    content, assessment, contract, substantive, accepted, code
):
    calls = []
    grade = grade_final_turn(
        status="returned",
        receipt={"finish_reason": "stop"},
        tool_calls=[],
        content=content,
        content_grader=lambda text: calls.append(text) or assessment,
    )
    assert calls == [content]
    assert grade.terminal_protocol_valid is True
    assert grade.terminal_contract_valid == contract
    assert grade.substantive_correct == substantive
    assert grade.final_contract_accepted is accepted
    if code is not None:
        assert code in grade.failure_codes


def test_wrong_final_does_not_rewrite_successful_tool_progression():
    calls = []
    classification = classify(content="bounded prose")
    execution = successful_execution(classification, calls=calls)
    scaffold = build_empty_content_continuation(classification, execution)
    wrong_final = grade_final_turn(
        status="returned",
        receipt={"finish_reason": "stop"},
        tool_calls=None,
        content="valid contract, wrong strategy",
        content_grader=lambda _text: FinalContentAssessment(
            contract_valid=True,
            substantive_correct=False,
            failure_codes=("wrong_strategy",),
        ),
    )
    assert classification.execution_eligible is True
    assert execution.execution_succeeded == "pass"
    assert scaffold.continuation_content_policy == CONTINUATION_POLICY
    assert wrong_final.final_contract_accepted is True
    assert wrong_final.substantive_correct == "fail"
    assert calls == [ARGS]


def test_final_grader_failure_is_unassessed_not_a_wrong_model_answer():
    grade = grade_final_turn(
        status="returned",
        receipt={"finish_reason": "stop"},
        tool_calls=[],
        content="{}",
        content_grader=lambda _text: (_ for _ in ()).throw(RuntimeError("grader broke")),
    )
    assert grade.terminal_protocol_valid is True
    assert grade.terminal_contract_valid == "unassessed"
    assert grade.substantive_correct == "unassessed"
    assert grade.failure_codes == ("final_content_grader_error",)


def test_invalid_expected_contract_fails_before_classification():
    with pytest.raises(ContractError, match="expected arguments"):
        classify(expectation=ToolExpectation(TOOL_NAME, "calculator", {"E": 10}))


def test_final_content_assessment_rejects_impossible_credit():
    with pytest.raises(ContractError, match="requires a valid terminal contract"):
        FinalContentAssessment(contract_valid=False, substantive_correct=True)
