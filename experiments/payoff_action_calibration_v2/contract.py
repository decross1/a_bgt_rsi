"""Offline native-tool v2 contract seam.

This module deliberately has no model, network, filesystem, or scheduler path.
It separates classification, one local execution, continuation construction,
and terminal grading so an eligibility decision cannot masquerade as an
execution receipt or a correct final answer.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Literal

from experiments.payoff_action_calculator import calculator

Assessment = Literal["pass", "fail", "unassessed"]
ArgumentContract = Literal["calculator", "table"]
ContentState = Literal[
    "null",
    "empty",
    "whitespace",
    "nonempty",
    "invalid_type",
    "unencodable",
]

PASS: Assessment = "pass"
FAIL: Assessment = "fail"
UNASSESSED: Assessment = "unassessed"

CONTRACT_VERSION = "payoff-action-native-tool-core/v2"
CONTINUATION_POLICY = "empty-pretool-content/v2"
PRETOOL_CONTENT_LIMIT_BYTES = 512


class ContractError(ValueError):
    """The caller supplied an invalid contract or requested an invalid transition."""


@dataclass(frozen=True)
class ToolExpectation:
    """Frozen facts against which one native call is classified."""

    name: str
    argument_contract: ArgumentContract
    expected_arguments: Mapping[str, Any]


@dataclass(frozen=True)
class TextEvidence:
    """Exact text evidence without semantic or lexical interpretation."""

    raw: str | None
    state: ContentState
    type_valid: Assessment
    encoding_valid: Assessment
    utf8_bytes: int | None
    within_bound: Assessment


@dataclass(frozen=True)
class ToolTurnClassification:
    schema_version: str
    transport_status: str
    transport_returned: Assessment
    receipt_complete: Assessment
    finish_reason_tool_calls: Assessment
    tool_calls_container: Assessment
    single_tool_call: Assessment
    call_shape_valid: Assessment
    tool_name_valid: Assessment
    arguments_json_valid: Assessment
    arguments_contract_valid: Assessment
    arguments_exact: Assessment
    pretool_content: TextEvidence
    reasoning_content: TextEvidence
    call_count: int | None
    _parsed_arguments_json_utf8: bytes | None
    _accepted_call_json_utf8: bytes | None
    _execution_binding_sha256: str | None
    execution_eligible: bool
    strict_v1_comparable: bool
    failure_codes: tuple[str, ...]

    @property
    def parsed_arguments(self) -> dict[str, Any] | None:
        if self._parsed_arguments_json_utf8 is None:
            return None
        value = json.loads(self._parsed_arguments_json_utf8.decode("utf-8"))
        if type(value) is not dict:  # construction invariant
            raise ContractError("retained parsed arguments are not an object")
        return value

    @property
    def accepted_call(self) -> dict[str, Any] | None:
        if self._accepted_call_json_utf8 is None:
            return None
        value = json.loads(self._accepted_call_json_utf8.decode("utf-8"))
        if type(value) is not dict:  # construction invariant
            raise ContractError("retained accepted call is not an object")
        return value

    @property
    def execution_binding_sha256(self) -> str | None:
        """Identify the exact parsed arguments and accepted call for execution."""

        return self._execution_binding_sha256


@dataclass(frozen=True)
class ExecutionOutcome:
    schema_version: str
    execution_attempted: bool
    execution_succeeded: Assessment
    result_contract_valid: Assessment
    source_binding_sha256: str | None
    retained_result: Any | None
    retained_result_json_utf8: bytes | None
    retained_result_sha256: str | None
    failure_code: str | None
    error_type: str | None


@dataclass(frozen=True)
class ContinuationScaffold:
    """Immutable primitives used to construct the two tool-continuation messages."""

    schema_version: str
    continuation_content_policy: str
    tool_call_id: str
    tool_name: str
    tool_arguments_json: str
    retained_result_json_utf8: bytes
    retained_result_sha256: str

    def messages(self) -> tuple[dict[str, Any], dict[str, Any]]:
        """Return fresh messages; raw pre-tool prose is intentionally absent."""

        return (
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": self.tool_call_id,
                        "type": "function",
                        "function": {
                            "name": self.tool_name,
                            "arguments": self.tool_arguments_json,
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": self.tool_call_id,
                "name": self.tool_name,
                "content": self.retained_result_json_utf8.decode("utf-8"),
            },
        )


@dataclass(frozen=True)
class FinalContentAssessment:
    """Result returned by a pure task-specific terminal-content grader."""

    contract_valid: bool
    substantive_correct: bool
    failure_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.contract_valid) is not bool or type(self.substantive_correct) is not bool:
            raise ContractError("final content assessment flags must be exact booleans")
        if not self.contract_valid and self.substantive_correct:
            raise ContractError("substantive correctness requires a valid terminal contract")
        if any(not isinstance(code, str) or not code for code in self.failure_codes):
            raise ContractError("final content failure codes must be nonempty strings")
        if len(set(self.failure_codes)) != len(self.failure_codes):
            raise ContractError("final content failure codes must be unique")
        if self.substantive_correct and self.failure_codes:
            raise ContractError("a substantively correct final cannot carry failure codes")


@dataclass(frozen=True)
class FinalGrade:
    schema_version: str
    transport_returned: Assessment
    receipt_complete: Assessment
    finish_reason_stop: Assessment
    no_final_tool_calls: Assessment
    content_type_valid: Assessment
    content_encoding_valid: Assessment
    terminal_protocol_valid: bool
    terminal_contract_valid: Assessment
    substantive_correct: Assessment
    final_contract_accepted: bool
    content_sha256: str | None
    failure_codes: tuple[str, ...]


ResultValidator = Callable[[Any, Mapping[str, Any]], bool]
FinalContentGrader = Callable[[str], FinalContentAssessment]


def _json_clone(value: Any) -> Any:
    return json.loads(_canonical_json(value).decode("utf-8"))


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8", errors="strict")


def _strict_json(value: str) -> Any:
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = item
        return result

    def invalid_constant(_value: str) -> None:
        raise ValueError("non-finite JSON constant")

    parsed = json.loads(
        value,
        object_pairs_hook=unique_object,
        parse_constant=invalid_constant,
    )

    def require_finite(item: Any) -> None:
        if isinstance(item, float) and not math.isfinite(item):
            raise ValueError("non-finite JSON number")
        if isinstance(item, list):
            for child in item:
                require_finite(child)
        elif isinstance(item, dict):
            for child in item.values():
                require_finite(child)

    require_finite(parsed)
    return parsed


def _execution_binding(arguments_json: bytes, call_json: bytes) -> str:
    material = b"\x00".join(
        (CONTRACT_VERSION.encode("utf-8"), arguments_json, call_json)
    )
    return hashlib.sha256(material).hexdigest()


def _text_evidence(value: Any, *, byte_limit: int | None) -> TextEvidence:
    if value is None:
        return TextEvidence(
            raw=None,
            state="null",
            type_valid=PASS,
            encoding_valid=PASS,
            utf8_bytes=0,
            within_bound=PASS,
        )
    if not isinstance(value, str):
        return TextEvidence(
            raw=None,
            state="invalid_type",
            type_valid=FAIL,
            encoding_valid=UNASSESSED,
            utf8_bytes=None,
            within_bound=UNASSESSED,
        )
    state: ContentState
    if value == "":
        state = "empty"
    elif value.isspace():
        state = "whitespace"
    else:
        state = "nonempty"
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return TextEvidence(
            raw=value,
            state="unencodable",
            type_valid=PASS,
            encoding_valid=FAIL,
            utf8_bytes=None,
            within_bound=UNASSESSED,
        )
    return TextEvidence(
        raw=value,
        state=state,
        type_valid=PASS,
        encoding_valid=PASS,
        utf8_bytes=len(encoded),
        within_bound=(PASS if byte_limit is None or len(encoded) <= byte_limit else FAIL),
    )


def _argument_contract_valid(arguments: Any, contract: ArgumentContract) -> bool:
    if type(arguments) is not dict:
        return False
    if contract == "calculator":
        if set(arguments) != {"E", "m_num", "m_den", "joint_action", "focal_seat"}:
            return False
        for key in ("E", "m_num", "m_den"):
            value = arguments[key]
            if type(value) is not int or not 1 <= value <= calculator.MAX_INPUT_INTEGER:
                return False
        if math.gcd(arguments["m_num"], arguments["m_den"]) != 1:
            return False
        actions = arguments["joint_action"]
        if type(actions) is not list or len(actions) != calculator.PLAYERS:
            return False
        if any(type(action) is not int or action not in (0, 1) for action in actions):
            return False
        seat = arguments["focal_seat"]
        return type(seat) is int and 0 <= seat < calculator.PLAYERS
    if contract == "table":
        if set(arguments) != {"E", "m_num", "m_den", "players"}:
            return False
        return (
            all(type(arguments[key]) is int for key in arguments)
            and arguments["E"] > 0
            and arguments["m_num"] > 0
            and arguments["m_den"] > 0
            and arguments["players"] == calculator.PLAYERS
        )
    raise ContractError(f"unknown argument contract: {contract}")


def _transport_failure_code(status: str) -> str:
    return {
        "timeout": "transport_timeout",
        "cancelled": "transport_cancelled",
        "transport_error": "transport_error",
    }.get(status, "transport_not_returned")


def classify_tool_turn(
    *,
    status: Any,
    receipt: Any,
    tool_calls: Any,
    content: Any,
    reasoning_content: Any,
    expectation: ToolExpectation,
) -> ToolTurnClassification:
    """Classify one tool turn without invoking any executor or calculator."""

    if not isinstance(expectation.name, str) or not expectation.name:
        raise ContractError("expected tool name must be a nonempty string")
    if expectation.argument_contract not in {"calculator", "table"}:
        raise ContractError("unsupported expected argument contract")
    try:
        expected_arguments = copy.deepcopy(dict(expectation.expected_arguments))
    except (TypeError, ValueError) as error:
        raise ContractError("expected arguments must be an object-like mapping") from error
    if not _argument_contract_valid(expected_arguments, expectation.argument_contract):
        raise ContractError("expected arguments do not satisfy their declared contract")

    failures: list[str] = []
    if isinstance(status, str):
        transport_status = status
        transport_returned = PASS if status == "returned" else FAIL
        if transport_returned == FAIL:
            failures.append(_transport_failure_code(status))
    else:
        transport_status = "invalid_type"
        transport_returned = FAIL
        failures.append("transport_status_invalid")

    if type(receipt) is dict and isinstance(receipt.get("finish_reason"), str):
        receipt_complete = PASS
        finish_reason_tool_calls = PASS if receipt["finish_reason"] == "tool_calls" else FAIL
        if finish_reason_tool_calls == FAIL:
            failures.append("finish_reason_not_tool_calls")
    else:
        receipt_complete = FAIL
        finish_reason_tool_calls = UNASSESSED
        failures.append("receipt_incomplete")

    call_count: int | None = None
    parsed_arguments: dict[str, Any] | None = None
    accepted_call: dict[str, Any] | None = None
    tool_calls_container: Assessment
    single_tool_call: Assessment
    call_shape_valid: Assessment = UNASSESSED
    tool_name_valid: Assessment = UNASSESSED
    arguments_json_valid: Assessment = UNASSESSED
    arguments_contract_valid: Assessment = UNASSESSED
    arguments_exact: Assessment = UNASSESSED

    if not isinstance(tool_calls, (list, tuple)):
        tool_calls_container = FAIL
        single_tool_call = UNASSESSED
        failures.append("tool_calls_container_invalid")
    else:
        tool_calls_container = PASS
        call_count = len(tool_calls)
        single_tool_call = PASS if call_count == 1 else FAIL
        if single_tool_call == FAIL:
            failures.append("single_tool_call_required")
            if (
                transport_returned == PASS
                and receipt_complete == PASS
                and receipt.get("finish_reason") == "stop"
                and call_count == 0
            ):
                failures.append("no_call_bypass")
        else:
            call = tool_calls[0]
            shape_ok = (
                type(call) is dict
                and set(call) == {"id", "type", "function"}
                and call.get("type") == "function"
                and isinstance(call.get("id"), str)
                and bool(call["id"])
                and type(call.get("function")) is dict
                and set(call["function"]) == {"name", "arguments"}
                and isinstance(call["function"].get("name"), str)
                and bool(call["function"]["name"])
                and isinstance(call["function"].get("arguments"), str)
            )
            call_shape_valid = PASS if shape_ok else FAIL
            if not shape_ok:
                failures.append("tool_call_shape_invalid")
            else:
                function = call["function"]
                tool_name_valid = PASS if function["name"] == expectation.name else FAIL
                if tool_name_valid == FAIL:
                    failures.append("tool_name_wrong")
                try:
                    parsed = _strict_json(function["arguments"])
                except (TypeError, ValueError, json.JSONDecodeError, UnicodeError):
                    arguments_json_valid = FAIL
                    failures.append("arguments_json_invalid")
                else:
                    arguments_json_valid = PASS
                    contract_ok = _argument_contract_valid(parsed, expectation.argument_contract)
                    arguments_contract_valid = PASS if contract_ok else FAIL
                    if not contract_ok:
                        failures.append("arguments_contract_invalid")
                    else:
                        parsed_arguments = copy.deepcopy(parsed)
                        arguments_exact = PASS if parsed == expected_arguments else FAIL
                        if arguments_exact == FAIL:
                            failures.append("arguments_wrong")

    pretool = _text_evidence(content, byte_limit=PRETOOL_CONTENT_LIMIT_BYTES)
    if pretool.type_valid == FAIL:
        failures.append("pretool_content_type_invalid")
    elif pretool.encoding_valid == FAIL:
        failures.append("pretool_content_encoding_invalid")
    elif pretool.within_bound == FAIL:
        failures.append("pretool_content_too_large")

    reasoning = _text_evidence(reasoning_content, byte_limit=None)
    if reasoning.type_valid == FAIL:
        failures.append("reasoning_content_type_invalid")
    elif reasoning.encoding_valid == FAIL:
        failures.append("reasoning_content_encoding_invalid")

    required = (
        transport_returned,
        receipt_complete,
        finish_reason_tool_calls,
        tool_calls_container,
        single_tool_call,
        call_shape_valid,
        tool_name_valid,
        arguments_json_valid,
        arguments_contract_valid,
        arguments_exact,
        pretool.type_valid,
        pretool.encoding_valid,
        pretool.within_bound,
        reasoning.type_valid,
        reasoning.encoding_valid,
    )
    execution_eligible = all(item == PASS for item in required)
    strict_v1_comparable = execution_eligible and (
        content is None or (isinstance(content, str) and content == "")
    )
    if execution_eligible:
        call = tool_calls[0]
        accepted_call = copy.deepcopy(call)

    parsed_arguments_json = (
        _canonical_json(parsed_arguments) if parsed_arguments is not None else None
    )
    accepted_call_json = _canonical_json(accepted_call) if accepted_call is not None else None
    execution_binding = (
        _execution_binding(parsed_arguments_json, accepted_call_json)
        if execution_eligible
        and parsed_arguments_json is not None
        and accepted_call_json is not None
        else None
    )

    return ToolTurnClassification(
        schema_version=CONTRACT_VERSION,
        transport_status=transport_status,
        transport_returned=transport_returned,
        receipt_complete=receipt_complete,
        finish_reason_tool_calls=finish_reason_tool_calls,
        tool_calls_container=tool_calls_container,
        single_tool_call=single_tool_call,
        call_shape_valid=call_shape_valid,
        tool_name_valid=tool_name_valid,
        arguments_json_valid=arguments_json_valid,
        arguments_contract_valid=arguments_contract_valid,
        arguments_exact=arguments_exact,
        pretool_content=pretool,
        reasoning_content=reasoning,
        call_count=call_count,
        _parsed_arguments_json_utf8=parsed_arguments_json,
        _accepted_call_json_utf8=accepted_call_json,
        _execution_binding_sha256=execution_binding,
        execution_eligible=execution_eligible,
        strict_v1_comparable=strict_v1_comparable,
        failure_codes=tuple(failures),
    )


def _exact_fraction(value: Any) -> Fraction | None:
    if type(value) is not dict or set(value) != {"numerator", "denominator", "canonical"}:
        return None
    numerator = value["numerator"]
    denominator = value["denominator"]
    canonical = value["canonical"]
    if (
        type(numerator) is not int
        or type(denominator) is not int
        or denominator <= 0
        or not isinstance(canonical, str)
        or math.gcd(abs(numerator), denominator) != 1
    ):
        return None
    parsed = Fraction(numerator, denominator)
    expected = (
        str(parsed.numerator)
        if parsed.denominator == 1
        else f"{parsed.numerator}/{parsed.denominator}"
    )
    return parsed if canonical == expected else None


def calculator_result_contract_valid(result: Any, arguments: Mapping[str, Any]) -> bool:
    """Validate result structure and internal consistency without re-executing the tool."""

    if not _argument_contract_valid(arguments, "calculator") or type(result) is not dict:
        return False
    required = {
        "formula_version",
        "evaluated_joint_action",
        "focal_seat",
        "contributor_count",
        "other_contributor_count",
        "focal_action",
        "player_payoffs",
        "focal_payoff",
        "total_payoff",
        "strategy_advice_included",
    }
    if set(result) != required or result["formula_version"] != calculator.FORMULA_VERSION:
        return False
    actions = arguments["joint_action"]
    seat = arguments["focal_seat"]
    count = sum(actions)
    if (
        result["evaluated_joint_action"] != actions
        or result["focal_seat"] != seat
        or type(result["contributor_count"]) is not int
        or result["contributor_count"] != count
        or type(result["other_contributor_count"]) is not int
        or result["other_contributor_count"] != count - actions[seat]
        or type(result["focal_action"]) is not int
        or result["focal_action"] != actions[seat]
        or result["strategy_advice_included"] is not False
    ):
        return False
    player_values = result["player_payoffs"]
    if type(player_values) is not list or len(player_values) != calculator.PLAYERS:
        return False
    parsed_players = [_exact_fraction(value) for value in player_values]
    if any(value is None for value in parsed_players):
        return False
    focal = _exact_fraction(result["focal_payoff"])
    total = _exact_fraction(result["total_payoff"])
    return (
        focal is not None
        and total is not None
        and focal == parsed_players[seat]
        and total == sum(parsed_players, Fraction())
    )


def execute_once(
    classification: ToolTurnClassification,
    *,
    executor: Callable[[dict[str, Any]], Any],
    result_validator: ResultValidator,
) -> ExecutionOutcome:
    """Invoke an eligible tool once and retain the one canonicalized result."""

    if not classification.execution_eligible:
        return ExecutionOutcome(
            schema_version=CONTRACT_VERSION,
            execution_attempted=False,
            execution_succeeded=UNASSESSED,
            result_contract_valid=UNASSESSED,
            source_binding_sha256=None,
            retained_result=None,
            retained_result_json_utf8=None,
            retained_result_sha256=None,
            failure_code="execution_ineligible",
            error_type=None,
        )
    if classification.parsed_arguments is None or classification.accepted_call is None:
        raise ContractError("eligible classification is missing retained call evidence")
    if classification.execution_binding_sha256 is None:
        raise ContractError("eligible classification is missing its execution binding")
    if not callable(executor) or not callable(result_validator):
        raise ContractError("executor and result validator must be callable")

    arguments = copy.deepcopy(classification.parsed_arguments)
    try:
        raw_result = executor(arguments)
    except Exception as error:  # noqa: BLE001 - executor failures are classified evidence
        return ExecutionOutcome(
            schema_version=CONTRACT_VERSION,
            execution_attempted=True,
            execution_succeeded=FAIL,
            result_contract_valid=UNASSESSED,
            source_binding_sha256=classification.execution_binding_sha256,
            retained_result=None,
            retained_result_json_utf8=None,
            retained_result_sha256=None,
            failure_code="tool_execution_error",
            error_type=type(error).__name__,
        )

    try:
        result_json = _canonical_json(raw_result)
        retained_result = json.loads(result_json.decode("utf-8"))
    except (TypeError, ValueError, UnicodeError, json.JSONDecodeError) as error:
        return ExecutionOutcome(
            schema_version=CONTRACT_VERSION,
            execution_attempted=True,
            execution_succeeded=FAIL,
            result_contract_valid=FAIL,
            source_binding_sha256=classification.execution_binding_sha256,
            retained_result=None,
            retained_result_json_utf8=None,
            retained_result_sha256=None,
            failure_code="tool_result_not_finite_json",
            error_type=type(error).__name__,
        )

    try:
        valid = result_validator(
            copy.deepcopy(retained_result),
            copy.deepcopy(classification.parsed_arguments),
        )
    except Exception as error:  # noqa: BLE001 - validator failures are classified evidence
        return ExecutionOutcome(
            schema_version=CONTRACT_VERSION,
            execution_attempted=True,
            execution_succeeded=FAIL,
            result_contract_valid=FAIL,
            source_binding_sha256=classification.execution_binding_sha256,
            retained_result=retained_result,
            retained_result_json_utf8=result_json,
            retained_result_sha256=hashlib.sha256(result_json).hexdigest(),
            failure_code="tool_result_validator_error",
            error_type=type(error).__name__,
        )
    if type(valid) is not bool or not valid:
        return ExecutionOutcome(
            schema_version=CONTRACT_VERSION,
            execution_attempted=True,
            execution_succeeded=FAIL,
            result_contract_valid=FAIL,
            source_binding_sha256=classification.execution_binding_sha256,
            retained_result=retained_result,
            retained_result_json_utf8=result_json,
            retained_result_sha256=hashlib.sha256(result_json).hexdigest(),
            failure_code="tool_result_contract_invalid",
            error_type=None,
        )
    return ExecutionOutcome(
        schema_version=CONTRACT_VERSION,
        execution_attempted=True,
        execution_succeeded=PASS,
        result_contract_valid=PASS,
        source_binding_sha256=classification.execution_binding_sha256,
        retained_result=retained_result,
        retained_result_json_utf8=result_json,
        retained_result_sha256=hashlib.sha256(result_json).hexdigest(),
        failure_code=None,
        error_type=None,
    )


def build_empty_content_continuation(
    classification: ToolTurnClassification,
    execution: ExecutionOutcome,
) -> ContinuationScaffold:
    """Build the primary v2 scaffold from the retained result; never re-execute."""

    if not classification.execution_eligible or classification.accepted_call is None:
        raise ContractError("continuation requires an eligible classified call")
    if (
        classification.execution_binding_sha256 is None
        or execution.source_binding_sha256 != classification.execution_binding_sha256
    ):
        raise ContractError("continuation execution does not belong to the classified call")
    if (
        execution.execution_attempted is not True
        or execution.execution_succeeded != PASS
        or execution.result_contract_valid != PASS
        or execution.retained_result_json_utf8 is None
        or execution.retained_result_sha256 is None
    ):
        raise ContractError("continuation requires one successful retained execution result")
    if hashlib.sha256(execution.retained_result_json_utf8).hexdigest() != (
        execution.retained_result_sha256
    ):
        raise ContractError("retained execution result digest does not match its bytes")
    call = classification.accepted_call
    function = call["function"]
    return ContinuationScaffold(
        schema_version=CONTRACT_VERSION,
        continuation_content_policy=CONTINUATION_POLICY,
        tool_call_id=call["id"],
        tool_name=function["name"],
        tool_arguments_json=function["arguments"],
        retained_result_json_utf8=execution.retained_result_json_utf8,
        retained_result_sha256=execution.retained_result_sha256,
    )


def grade_final_turn(
    *,
    status: Any,
    receipt: Any,
    tool_calls: Any,
    content: Any,
    content_grader: FinalContentGrader,
) -> FinalGrade:
    """Grade terminal protocol and task content independently of tool progression."""

    failures: list[str] = []
    if isinstance(status, str):
        transport_returned = PASS if status == "returned" else FAIL
        if transport_returned == FAIL:
            failures.append(_transport_failure_code(status))
    else:
        transport_returned = FAIL
        failures.append("transport_status_invalid")

    if type(receipt) is dict and isinstance(receipt.get("finish_reason"), str):
        receipt_complete = PASS
        finish_reason_stop = PASS if receipt["finish_reason"] == "stop" else FAIL
        if finish_reason_stop == FAIL:
            failures.append("final_finish_reason_not_stop")
    else:
        receipt_complete = FAIL
        finish_reason_stop = UNASSESSED
        failures.append("final_receipt_incomplete")

    if tool_calls is None or (isinstance(tool_calls, (list, tuple)) and len(tool_calls) == 0):
        no_final_tool_calls = PASS
    elif isinstance(tool_calls, (list, tuple)):
        no_final_tool_calls = FAIL
        failures.append("final_tool_call_present")
    else:
        no_final_tool_calls = FAIL
        failures.append("final_tool_calls_container_invalid")

    if not isinstance(content, str):
        content_type_valid = FAIL
        content_encoding_valid = UNASSESSED
        content_sha256 = None
        failures.append("final_content_type_invalid")
    else:
        content_type_valid = PASS
        try:
            encoded = content.encode("utf-8", errors="strict")
        except UnicodeEncodeError:
            content_encoding_valid = FAIL
            content_sha256 = None
            failures.append("final_content_encoding_invalid")
        else:
            content_encoding_valid = PASS
            content_sha256 = hashlib.sha256(encoded).hexdigest()

    terminal_protocol_valid = all(
        item == PASS
        for item in (
            transport_returned,
            receipt_complete,
            finish_reason_stop,
            no_final_tool_calls,
            content_type_valid,
            content_encoding_valid,
        )
    )
    terminal_contract_valid: Assessment = UNASSESSED
    substantive_correct: Assessment = UNASSESSED
    if terminal_protocol_valid:
        if not callable(content_grader):
            raise ContractError("final content grader must be callable")
        try:
            assessment = content_grader(content)
            if not isinstance(assessment, FinalContentAssessment):
                raise ContractError("final content grader returned the wrong type")
        except Exception:  # noqa: BLE001 - grader failures remain unassessed evidence
            failures.append("final_content_grader_error")
        else:
            failures.extend(assessment.failure_codes)
            terminal_contract_valid = PASS if assessment.contract_valid else FAIL
            if assessment.contract_valid:
                substantive_correct = PASS if assessment.substantive_correct else FAIL
            if (
                assessment.contract_valid
                and not assessment.substantive_correct
                and not assessment.failure_codes
            ):
                failures.append("final_substantive_wrong")
            elif not assessment.contract_valid and not assessment.failure_codes:
                failures.append("final_contract_invalid")

    return FinalGrade(
        schema_version=CONTRACT_VERSION,
        transport_returned=transport_returned,
        receipt_complete=receipt_complete,
        finish_reason_stop=finish_reason_stop,
        no_final_tool_calls=no_final_tool_calls,
        content_type_valid=content_type_valid,
        content_encoding_valid=content_encoding_valid,
        terminal_protocol_valid=terminal_protocol_valid,
        terminal_contract_valid=terminal_contract_valid,
        substantive_correct=substantive_correct,
        final_contract_accepted=terminal_protocol_valid and terminal_contract_valid == PASS,
        content_sha256=content_sha256,
        failure_codes=tuple(failures),
    )


__all__ = [
    "CONTINUATION_POLICY",
    "CONTRACT_VERSION",
    "PRETOOL_CONTENT_LIMIT_BYTES",
    "ContinuationScaffold",
    "ContractError",
    "ExecutionOutcome",
    "FinalContentAssessment",
    "FinalGrade",
    "TextEvidence",
    "ToolExpectation",
    "ToolTurnClassification",
    "build_empty_content_continuation",
    "calculator_result_contract_valid",
    "classify_tool_turn",
    "execute_once",
    "grade_final_turn",
]
