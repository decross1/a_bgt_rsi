import json

from bench.flash_next_ab.adapters import CallResult, execute_cell, load_cells


def returned(spec, content, *, endpoint="flash_next"):
    return CallResult(
        spec=spec,
        status="returned",
        content=content,
        tool_calls=(),
        receipt={
            "wall_s": 0.1,
            "endpoint_name": endpoint,
            "response_model": "qwen3.8-flash-next",
            "response_id": f"response-{spec.call_index}",
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            "error": None,
        },
    )


def test_objective_and_context_reuse_the_existing_objective_grader():
    for family in ("objective", "context"):
        cell = load_cells(families=[family])[0]
        expected = cell.payload["task"].grader["expected"]
        expected_json = json.dumps(expected)
        result = execute_cell(
            cell,
            lambda spec, value=expected_json: returned(spec, value),
        )
        assert result.passed is True
        assert result.details["existing_grade"]["passed"] is True


def test_topic_hypothesis_is_explicitly_protocol_only():
    cell = next(
        item
        for item in load_cells(families=["topic"])
        if item.payload["attempt"]["stage"] == "hypothesis"
    )
    content = json.dumps({"candidates": ["A testable hypothesis"], "chosen": "A testable hypothesis"})
    result = execute_cell(cell, lambda spec: returned(spec, content))
    assert result.passed is True
    assert result.details["metric_scope"] == "protocol_compliance_only"
    assert result.details["semantic_status"] == "awaiting_separate_blinded_annotation"


def test_portfolio_structured_result_uses_existing_finite_oracle():
    cell = load_cells(families=["portfolio"])[0]
    content = json.dumps(
        {
            "baseline_hhi": 0.25,
            "delegated_hhi": 0.34375,
            "delta": 0.09375,
            "direction": "increased",
        }
    )
    result = execute_cell(cell, lambda spec: returned(spec, content))
    assert result.passed is True
    assert result.details["existing_grade"]["passed"] is True


def test_diversity_staged_validator_uses_all_four_declared_calls():
    cell = next(
        item
        for item in load_cells(families=["diversity"])
        if item.condition == "diverse_select"
    )
    observed = []

    def invoke(spec):
        observed.append(spec)
        assert spec.messages is not None
        content = '{"selected_slot":null}' if spec.role == "validator" else '{"proposal":null}'
        return returned(spec, content)

    result = execute_cell(cell, invoke)
    assert len(observed) == 4
    assert [spec.call_index for spec in observed] == [0, 1, 2, 3]
    assert observed[-1].role == "validator"
    assert result.passed is False
    assert result.details["dynamic_validator_messages"] is True


def test_role_effort_adaptive_retry_reuses_public_trigger_and_grader():
    cell = next(
        item
        for item in load_cells(families=["role_effort"])
        if item.condition == "adaptive" and item.payload["task"]["role"] == "evidence"
    )
    task = cell.payload["task"]
    attempts = []

    def invoke(spec):
        attempts.append(spec)
        payload = {**task["expected"], "needs_review": len(attempts) == 1}
        return returned(spec, json.dumps(payload))

    result = execute_cell(cell, invoke)
    assert len(attempts) == 2
    assert attempts[0].policy_id == "critic_medium"
    assert attempts[1].policy_id == "critic_current"
    assert result.passed is True
    assert result.details["conditional_escalation_triggered"] is True


def test_historical_malformed_patch_is_graded_without_opening_a_sandbox():
    cell = load_cells(families=["historical"])[0]
    result = execute_cell(cell, lambda spec: returned(spec, "not a patch"))
    assert result.passed is False
    assert result.failure_code == "completion_not_raw_diff"
    assert result.details["existing_grade"]["patch_status"] == "invalid"
