"""Fresh canary math, wire grading and private-evidence producer checks."""
from __future__ import annotations

import hashlib
import json
import threading
import time

import pytest

from bench.flash_next_ab import followon_market_canaries as m


def test_both_valid_json_and_semantic_failure():
    expected = {"expected_profit_bps": -3.7, "positive_expected_profit": False}
    assert m.grade(json.dumps(expected), expected)["passed"] is True
    wrong = {"expected_profit_bps": 3.7, "positive_expected_profit": True}
    assert m.grade(json.dumps(wrong), expected)["failure_code"] == "substantive_mistake"


def test_markdown_is_only_a_separate_diagnostic():
    expected = {"profitable": False}
    result = m.grade('```json\n{"profitable": false}\n```', expected)
    assert result == {"passed": False, "failure_code": "markdown_envelope",
                      "normalized_envelope_passed": True}
    result = m.grade('Explanation\n```json\n{"profitable": false}\n```', expected)
    assert result["failure_code"] == "malformed_json"
    assert result["normalized_envelope_passed"] is None


def test_duplicates_nonfinite_extra_keys_and_numeric_booleans_fail():
    expected = {"amount": 1.0}
    for content in ('{"amount": 0, "amount": 1}', '{"amount": NaN}',
                    '{"amount": Infinity}', '{"amount": 1, "extra": 2}',
                    '{"amount": true}', '{"amount": "1"}'):
        assert m.grade(content, expected)["passed"] is False


def test_integer_cardinality_and_repeating_probability():
    assert m.grade('{"n": 2}', {"n": 2})["passed"] is True
    assert m.grade('{"n": 2.0}', {"n": 2})["passed"] is False
    assert m.grade('{"p": 0.666667}', {"p": 2 / 3})["passed"] is True
    assert m.grade('{"p": 0.666}', {"p": 2 / 3})["passed"] is False


def test_empty_and_non_object_outputs_fail():
    for content in (None, "", "  ", "[]", "true", "null"):
        assert m.grade(content, {"x": False})["passed"] is False


def test_malformed_or_oversized_answer_is_a_failed_cell():
    giant_integer = '{"amount": ' + '9' * 400 + '}'
    assert m.grade(giant_integer, {"amount": 1.0})["failure_code"] == "substantive_mistake"
    nested = '{"x": ' + '[' * 2000 + '0' + ']' * 2000 + '}'
    assert m.grade(nested, {"x": False})["failure_code"] in {"malformed_json", "schema_violation"}
    assert m.grade('{"x": 0}', {"x": False})["failure_code"] == "schema_violation"
    assert m.grade('{"x": false, "y": 1}', {"x": False})["failure_code"] == "schema_violation"


def test_independently_enumerated_winner_posterior():
    # Enumerate the finite joint model independently of the model-facing prompt.
    probabilities = {(0, "H", "L"): 0.5 * 0.25 * 0.75,
                     (10, "H", "L"): 0.5 * 0.75 * 0.25}
    strict_win_mean = sum(state[0] * prob for state, prob in probabilities.items()) / sum(probabilities.values())
    own_high_mean = (10 * 0.5 * 0.75) / (0.5 * 0.75 + 0.5 * 0.25)
    assert own_high_mean == 7.5
    assert strict_win_mean == 5.0
    assert strict_win_mean - 6 == -1.0


def _routes():
    return {name: {"served_model": model, "artifact_sha256": ("a40ce50173dd3aff54da88503894967e5248bbb927f9e4a91eff5a6a7270c168" if name == "flash_next_mia" else "a" * 64),
                   "runtime_sha256": "b" * 64, "qualification_receipt_sha256": "c" * 64}
            for name, model in m.ENDPOINTS.items()}


def _reply_factory(*, timeout_ordinal=None, bad_ordinal=None, cancel_event=None):
    from bench.flash_next_ab import transport

    data, _ = m._source()
    expected = {task["prompt"]: task["expected"] for task in data["tasks"]}
    count = 0

    def reply(endpoint, messages, **kwargs):
        nonlocal count
        count += 1
        if count == timeout_ordinal:
            raise TimeoutError("bounded fixture timeout")
        answer = expected[messages[0]["content"]]
        content = json.dumps(answer)
        if count == bad_ordinal:
            content = '{"expected_profit_bps": ' + '9' * 400 + '}'
        payload = {
            "id": f"fixture-{count}", "model": endpoint.served_model,
            "choices": [{"index": 0, "delta": {"content": content,
                "reasoning_content": "PRIVATE REASONING IS NOT PUBLIC"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 30, "completion_tokens": 15, "total_tokens": 45},
        }
        accumulator = transport.StreamAccumulator(endpoint.served_model)
        accumulator.accept(json.dumps(payload))
        accumulator.accept("[DONE]")
        stream = b"data: " + json.dumps(payload).encode() + b"\n\ndata: [DONE]\n\n"
        body = transport.request_body(endpoint, messages, kwargs["policy"],
                                      kwargs["max_tokens"], kwargs["seed"], kwargs["tools"])
        response = {
            **accumulator.result(),
            "request_sha256": hashlib.sha256(transport.canonical(body)).hexdigest(),
            "response_stream_sha256": hashlib.sha256(stream).hexdigest(),
            "private_evidence": transport._private_response_evidence(
                accumulator, stream, response_bytes=len(stream)),
        }
        if cancel_event is not None:
            cancel_event.set()
        return response

    return reply


def test_real_producer_preserves_timeouts_and_private_sse_denominators(tmp_path):
    from bench.flash_next_ab.private_evidence import validate_private_evidence

    plan = m.build_plan(_routes())
    output = tmp_path / "run"
    run = m.run_model(
        plan, "flash_next_mia", seed_block=107, output_dir=output,
        runtime_budget_s=m.BLOCK_SECONDS, admission_gate=lambda *_: None,
        safety_check=lambda: None, work_cutoff_s=time.monotonic() + 2400,
        invoke_fn=_reply_factory(timeout_ordinal=2, bad_ordinal=3),
    )
    assert run["status"] == "complete"
    assert len(run["outcomes"]) == run["declared_cells"] == 24
    assert sum(row["passed"] for row in run["outcomes"]) == 22
    assert run["outcomes"][1]["status"] == "timeout"
    assert run["comparison_eligible"] is False
    assert validate_private_evidence(run, output)["calls_verified"] == 24
    assert "PRIVATE REASONING" not in (output / "run.json").read_text()


def test_controller_cancellation_keeps_unissued_cells_incomplete(tmp_path):
    cancel = threading.Event()
    run = m.run_model(
        m.build_plan(_routes()), "resident_qwen", seed_block=509,
        output_dir=tmp_path / "run", runtime_budget_s=m.BLOCK_SECONDS,
        admission_gate=lambda *_: None, safety_check=lambda: None,
        work_cutoff_s=time.monotonic() + 2400, cancel_event=cancel,
        invoke_fn=_reply_factory(cancel_event=cancel),
    )
    assert run["status"] == "incomplete"
    assert len(run["outcomes"]) == 24
    assert sum(len(row["calls"]) for row in run["outcomes"]) == 1
    assert sum(row["status"] == "not_run" for row in run["outcomes"]) == 23
    assert all(not row["passed"] for row in run["outcomes"])


def test_rejected_admission_cannot_create_output_or_issue_call(tmp_path):
    output = tmp_path / "run"

    def reject(*_):
        raise ValueError("not the isolated worker")

    with pytest.raises(ValueError, match="isolated worker"):
        m.run_model(
            m.build_plan(_routes()), "flash_next_mia", seed_block=107,
            output_dir=output, runtime_budget_s=m.BLOCK_SECONDS,
            admission_gate=reject, safety_check=lambda: None,
            work_cutoff_s=time.monotonic() + 2400,
            invoke_fn=lambda *_args, **_kwargs: pytest.fail("unadmitted call"),
        )
    assert not output.exists()
