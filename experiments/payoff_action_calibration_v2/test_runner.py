from __future__ import annotations

import contextlib
import copy
import json
import threading
from pathlib import Path

import pytest

from . import contract as core
from . import design, replay, runner
from .fixtures import FakeInvoke, idle_observation, prepare_plan


def run_case(
    tmp_path: Path,
    *,
    fake: FakeInvoke | None = None,
    cancel_event=None,
    executors=None,
    memory_fn=None,
):
    binding, root, plan_path, plan = prepare_plan(tmp_path)
    fake = fake or FakeInvoke()
    output = root / "run"
    result = runner.run(
        plan_path,
        output,
        cancel_event=cancel_event or threading.Event(),
        invoke_fn=fake,
        runtime_snapshot_fn=lambda: copy.deepcopy(binding),
        ready_fn=lambda: True,
        memory_fn=memory_fn or (lambda: 21.0),
        idle_probe_fn=idle_observation,
        lock_factory=lambda _root: contextlib.nullcontext(),
        executors=executors,
    )
    return plan_path, output, plan, result, fake


def test_complete_run_accounts_every_slot_and_keeps_raw_channels_private(tmp_path):
    plan_path, output, plan, result, fake = run_case(tmp_path)

    assert result["status"] == "complete"
    assert fake.requests == 20
    assert len(result["outcomes"]) == len(plan["declared_conditions"]) == 12
    assert [slot["slot_id"] for slot in result["slots"]] == plan["declared_slots"]
    assert result["accounting"] == {
        "declared_slots": 20,
        "attempted_calls": 20,
        "confirmed_dispatched_calls": 20,
        "wire_unknown_attempts": 0,
        "prewire_failures": 0,
        "returned_calls": 20,
        "failed_calls": 0,
        "skipped_unissued": 0,
        "unissued_after_abort": 0,
    }
    claim = runner.read_plan_claim(
        plan["artifact_policy"]["private_root"], result["plan_claim"]
    )
    assert claim == {
        "schema_version": runner.PLAN_CLAIM_SCHEMA,
        "study_id": plan["study_id"],
        "plan_raw_sha256": result["plan_raw_sha256"],
        "output": str(output),
    }
    public = (output / "run.json").read_text(encoding="utf-8")
    assert "fixture reasoning" not in public
    assert '"retained_result"' not in public
    for outcome in result["outcomes"]:
        protocol = runner.read_protocol(output, outcome["protocol"])
        assert protocol["stage"] == "terminal"
        assert protocol["condition_id"] == outcome["condition_id"]
    validation = replay.validate(plan_path, output)
    assert validation["status"] == "valid"
    assert validation["model_calls_executed_by_replay"] == 0
    assert validation["tool_calls_executed_by_replay"] == 0


def test_retained_result_and_final_request_have_exact_private_binding(tmp_path):
    _plan_path, output, _plan, result, _fake = run_case(tmp_path)
    outcome = next(row for row in result["outcomes"] if row["arm"] == "calculator")
    private = runner.read_protocol(output, outcome["protocol"])
    classification = runner.classification_from_record(private["classification"])
    execution = runner.execution_from_record(private["execution"])
    scaffold = runner.continuation_from_record(private["continuation"])

    assert execution.source_binding_sha256 == classification.execution_binding_sha256
    assert scaffold.retained_result_json_utf8 == execution.retained_result_json_utf8
    assert scaffold.retained_result_sha256 == execution.retained_result_sha256
    messages = private["continuation_request_messages"]
    assert messages[2]["content"] == ""
    assert messages[3]["content"].encode() == execution.retained_result_json_utf8
    assert design.sha(design.canonical(messages)) == private["continuation_messages_sha256"]
    assert private["final_call"]["receipt"]["messages_sha256"] == private[
        "continuation_messages_sha256"
    ]


def test_each_wire_attempt_is_durably_marked_before_invoke(tmp_path):
    output = tmp_path / "artifacts" / "run"

    class InspectingInvoke(FakeInvoke):
        def __init__(self):
            super().__init__()
            self.markers_seen = 0

        def __call__(self, *args, **kwargs):
            active = [
                json.loads(path.read_text())
                for path in (output / "private" / "protocols").glob("*.json")
            ]
            attempting = [row for row in active if row["stage"] == "wire_attempting"]
            assert len(attempting) == 1
            marker = attempting[0]["wire_attempts"][-1]
            assert set(marker) == {"slot_id", "call_ordinal", "state"}
            assert isinstance(marker["slot_id"], str) and marker["slot_id"]
            assert marker["call_ordinal"] == self.requests
            assert marker["state"] == "attempting"
            self.markers_seen += 1
            return super().__call__(*args, **kwargs)

    fake = InspectingInvoke()
    _plan_path, _output, _plan, result, _fake = run_case(tmp_path, fake=fake)
    assert fake.markers_seen == result["accounting"]["attempted_calls"] == 20


def test_malformed_native_calls_never_execute_and_remain_in_denominator(tmp_path):
    calls = {"table": 0, "calculator": 0}

    def counted(arm):
        executor = design.executor_for(arm)

        def invoke(arguments):
            calls[arm] += 1
            return executor(arguments)

        return invoke

    plan_path, output, _plan, result, fake = run_case(
        tmp_path,
        fake=FakeInvoke(malformed_tools=True),
        executors={"table": counted("table"), "calculator": counted("calculator")},
    )

    assert result["status"] == "complete"
    assert fake.requests == 12
    assert calls == {"table": 0, "calculator": 0}
    assert result["accounting"]["declared_slots"] == 20
    assert result["accounting"]["returned_calls"] == 12
    assert result["accounting"]["skipped_unissued"] == 8
    tool_outcomes = [row for row in result["outcomes"] if row["arm"] != "direct"]
    assert all(row["classification"]["execution_eligible"] is False for row in tool_outcomes)
    assert all(row["execution"] is None and row["final_issued"] is False for row in tool_outcomes)
    assert all("tool_name_wrong" in row["classification"]["failure_codes"] for row in tool_outcomes)
    assert replay.validate(plan_path, output)["status"] == "valid"


def test_timeout_partial_channels_stay_unassessed_and_never_execute(tmp_path):
    class PartialTimeout(FakeInvoke):
        def __call__(self, *args, **kwargs):
            returned = super().__call__(*args, **kwargs)
            error = TimeoutError("injected after partial response")
            error.private_evidence = returned["private_evidence"]
            raise error

    calls = {"table": 0, "calculator": 0}

    def forbidden(arm):
        def invoke(_arguments):
            calls[arm] += 1
            raise AssertionError("unassessed response executed a tool")

        return invoke

    plan_path, output, _plan, result, fake = run_case(
        tmp_path,
        fake=PartialTimeout(),
        executors={"table": forbidden("table"), "calculator": forbidden("calculator")},
    )

    assert result["status"] == "complete"
    assert fake.requests == 12
    assert calls == {"table": 0, "calculator": 0}
    assert result["accounting"]["failed_calls"] == 12
    assert result["accounting"]["skipped_unissued"] == 8
    tool_outcomes = [row for row in result["outcomes"] if row["arm"] != "direct"]
    for outcome in tool_outcomes:
        classification = outcome["classification"]
        assert classification["transport_returned"] == "fail"
        assert classification["receipt_complete"] == "unassessed"
        assert classification["single_tool_call"] == "unassessed"
        assert classification["arguments_exact"] == "unassessed"
        assert classification["execution_eligible"] is False
        assert outcome["execution"] is None
    validation = replay.validate(plan_path, output)
    assert validation["status"] == "valid"
    assert validation["facets_by_arm"]["table"]["terminal_contract_valid"] == {
        "pass": 0,
        "fail": 0,
        "unassessed": 4,
    }


def test_runtime_probe_exception_text_is_not_exported_publicly(tmp_path):
    class SentinelProbeError(RuntimeError):
        pass

    probes = 0

    def memory_probe():
        nonlocal probes
        probes += 1
        if probes == 1:
            return 21.0
        raise SentinelProbeError("SECRET-PROBE-SENTINEL")

    plan_path, output, _plan, result, fake = run_case(
        tmp_path,
        memory_fn=memory_probe,
    )
    assert fake.requests == 0
    assert result["status"] == "aborted"
    assert result["abort_reason"] == "runtime_probe_failed_before_next_call"
    assert result["resource_observations"][0]["error"] == (
        "SentinelProbeError:runtime probe failed"
    )
    assert "SECRET-PROBE-SENTINEL" not in (output / "run.json").read_text()
    assert replay.validate(plan_path, output)["status"] == "valid"


def test_successful_execution_survives_cancellation_before_final(tmp_path):
    cancelled = threading.Event()
    calls = []
    table = design.executor_for("table")

    def execute_then_cancel(arguments):
        calls.append(copy.deepcopy(arguments))
        # The durable marker must exist before the executor can be entered.
        protocols = list((tmp_path / "artifacts" / "run" / "private" / "protocols").glob("*.json"))
        assert any(
            json.loads(path.read_text())["stage"] == "execution_attempting"
            for path in protocols
        )
        result = table(arguments)
        cancelled.set()
        return result

    plan_path, output, _plan, result, fake = run_case(
        tmp_path,
        cancel_event=cancelled,
        executors={"table": execute_then_cancel},
    )

    assert len(calls) == 1
    assert fake.requests == 2  # direct plus the first table turn; no table final
    assert result["status"] == "aborted"
    table_outcome = next(row for row in result["outcomes"] if row["arm"] == "table")
    assert table_outcome["execution"]["execution_succeeded"] == "pass"
    assert table_outcome["execution"]["result_contract_valid"] == "pass"
    assert table_outcome["final_issued"] is False
    table_final = next(
        slot for slot in result["slots"] if slot["slot_id"].endswith("/table_final")
    )
    assert table_final["disposition"] == "unissued_after_abort"
    private = runner.read_protocol(output, table_outcome["protocol"])
    assert runner.execution_from_record(private["execution"]).retained_result_json_utf8
    validation = replay.validate(plan_path, output)
    assert validation["status"] == "valid"
    assert validation["run_status"] == "aborted"


def test_wrong_finals_do_not_rewrite_successful_tool_progression(tmp_path):
    plan_path, output, _plan, result, fake = run_case(
        tmp_path, fake=FakeInvoke(wrong_finals=True)
    )
    assert fake.requests == 20
    tool_outcomes = [row for row in result["outcomes"] if row["arm"] != "direct"]
    assert all(row["classification"]["execution_eligible"] is True for row in tool_outcomes)
    assert all(row["execution"]["execution_succeeded"] == "pass" for row in tool_outcomes)
    assert all(row["final_issued"] is True for row in tool_outcomes)
    assert all(
        row["final_grade"]["contract"]["substantive_correct"] == "fail"
        for row in tool_outcomes
    )
    assert replay.validate(plan_path, output)["facets_by_arm"]["calculator"][
        "substantive_correct"
    ] == {"pass": 0, "fail": 4, "unassessed": 0}


def test_executor_exception_aborts_but_replays_without_another_execution(tmp_path):
    calls = []

    def broken(arguments):
        calls.append(copy.deepcopy(arguments))
        raise RuntimeError("injected local executor failure")

    plan_path, output, _plan, result, fake = run_case(
        tmp_path, executors={"table": broken}
    )
    assert len(calls) == 1
    assert fake.requests == 2
    assert result["status"] == "aborted"
    outcome = next(row for row in result["outcomes"] if row["arm"] == "table")
    assert outcome["execution"]["execution_attempted"] is True
    assert outcome["execution"]["execution_succeeded"] == "fail"
    assert outcome["execution"]["failure_code"] == "tool_execution_error"
    validation = replay.validate(plan_path, output)
    assert validation["status"] == "valid"
    assert validation["recorded_tool_attempts_verified"] == 1
    assert validation["tool_calls_executed_by_replay"] == 0
    assert len(calls) == 1


def test_existing_output_is_immutable_and_run_is_not_resumed(tmp_path):
    plan_path, output, _plan, _result, fake = run_case(tmp_path)
    before = (output / "run.json").read_bytes()
    with pytest.raises(design.CalibrationError, match="never resume"):
        runner.run(
            plan_path,
            output,
            cancel_event=threading.Event(),
            invoke_fn=fake,
        )
    assert fake.requests == 20
    assert (output / "run.json").read_bytes() == before


def test_plan_claim_rejects_a_second_output_before_model_or_executor(tmp_path):
    plan_path, _output, plan, _result, first_fake = run_case(tmp_path)
    second_output = Path(plan["artifact_policy"]["private_root"]) / "second-run"
    model_calls = []
    executor_calls = []

    def forbidden_model(*args, **kwargs):
        model_calls.append((args, kwargs))
        raise AssertionError("single-use rejection issued a model request")

    def forbidden_executor(arguments):
        executor_calls.append(arguments)
        raise AssertionError("single-use rejection executed a local tool")

    with pytest.raises(design.CalibrationError, match="already claimed"):
        runner.run(
            plan_path,
            second_output,
            cancel_event=threading.Event(),
            invoke_fn=forbidden_model,
            runtime_snapshot_fn=lambda: copy.deepcopy(plan["runtime_binding"]),
            ready_fn=lambda: True,
            memory_fn=lambda: 21.0,
            idle_probe_fn=idle_observation,
            lock_factory=lambda _root: contextlib.nullcontext(),
            executors={"table": forbidden_executor, "calculator": forbidden_executor},
        )
    assert first_fake.requests == 20
    assert model_calls == []
    assert executor_calls == []
    assert not second_output.exists()


def test_concurrent_outputs_have_exactly_one_claim_winner(tmp_path):
    binding, root, plan_path, plan = prepare_plan(tmp_path)
    barrier = threading.Barrier(2)
    outputs = [root / "run-a", root / "run-b"]
    fakes = [FakeInvoke(), FakeInvoke()]
    results = []
    errors = []

    def idle_at_barrier():
        barrier.wait(timeout=10)
        return idle_observation()

    def attempt(index):
        try:
            value = runner.run(
                plan_path,
                outputs[index],
                cancel_event=threading.Event(),
                invoke_fn=fakes[index],
                runtime_snapshot_fn=lambda: copy.deepcopy(binding),
                ready_fn=lambda: True,
                memory_fn=lambda: 21.0,
                idle_probe_fn=idle_at_barrier,
                lock_factory=lambda _root: contextlib.nullcontext(),
            )
        except design.CalibrationError as error:
            errors.append(error)
        else:
            results.append((index, value))

    threads = [threading.Thread(target=attempt, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
        assert not thread.is_alive()

    assert len(results) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], design.CalibrationError)
    assert "already claimed" in str(errors[0])
    winner, result = results[0]
    assert [fake.requests for fake in fakes] == [20 if index == winner else 0 for index in range(2)]
    claim = runner.read_plan_claim(plan["artifact_policy"]["private_root"], result["plan_claim"])
    assert claim["output"] == str(outputs[winner])


def test_crash_after_execute_before_result_persistence_cannot_reexecute(
    tmp_path, monkeypatch
):
    binding, root, plan_path, _plan = prepare_plan(tmp_path)
    fake = FakeInvoke()
    output = root / "run"
    calls = []
    table = design.executor_for("table")

    def counted(arguments):
        calls.append(copy.deepcopy(arguments))
        return table(arguments)

    class InjectedCrash(BaseException):
        pass

    persist = runner._persist_protocol

    def crash_before_result(output_path, ordinal, protocol):
        if protocol.stage == "execution_persisted":
            raise InjectedCrash
        return persist(output_path, ordinal, protocol)

    monkeypatch.setattr(runner, "_persist_protocol", crash_before_result)
    with pytest.raises(InjectedCrash):
        runner.run(
            plan_path,
            output,
            cancel_event=threading.Event(),
            invoke_fn=fake,
            runtime_snapshot_fn=lambda: copy.deepcopy(binding),
            ready_fn=lambda: True,
            memory_fn=lambda: 21.0,
            idle_probe_fn=idle_observation,
            lock_factory=lambda _root: contextlib.nullcontext(),
            executors={"table": counted},
        )
    assert len(calls) == 1
    assert not (output / "run.json").exists()
    active = [
        json.loads(path.read_text())
        for path in (output / "private" / "protocols").glob("*.json")
    ]
    assert any(row["stage"] == "execution_attempting" for row in active)
    with pytest.raises(ValueError):
        replay.validate(plan_path, output)

    other_output = root / "other-output"
    requests_before_retry = fake.requests
    with pytest.raises(design.CalibrationError, match="already claimed"):
        runner.run(
            plan_path,
            other_output,
            cancel_event=threading.Event(),
            invoke_fn=fake,
            runtime_snapshot_fn=lambda: copy.deepcopy(binding),
            ready_fn=lambda: True,
            memory_fn=lambda: 21.0,
            idle_probe_fn=idle_observation,
            lock_factory=lambda _root: contextlib.nullcontext(),
            executors={"table": counted},
        )
    assert fake.requests == requests_before_retry
    assert len(calls) == 1
    assert not other_output.exists()

    with pytest.raises(design.CalibrationError, match="never resume"):
        runner.run(
            plan_path,
            output,
            cancel_event=threading.Event(),
            invoke_fn=fake,
            runtime_snapshot_fn=lambda: copy.deepcopy(binding),
            ready_fn=lambda: True,
            memory_fn=lambda: 21.0,
            idle_probe_fn=idle_observation,
            lock_factory=lambda _root: contextlib.nullcontext(),
            executors={"table": counted},
        )
    assert len(calls) == 1


def test_record_helpers_round_trip_core_bytes_and_reject_bad_hex():
    classification = core.classify_tool_turn(
        status="returned",
        receipt={"finish_reason": "tool_calls"},
        tool_calls=[
            {
                "id": "call-1",
                "type": "function",
                "function": {
                    "name": "public_goods_joint_action_payoff",
                    "arguments": json.dumps(
                        {
                            "E": 10,
                            "m_num": 3,
                            "m_den": 2,
                            "joint_action": [1, 0, 1, 0],
                            "focal_seat": 0,
                        }
                    ),
                },
            }
        ],
        content="",
        reasoning_content="private",
        expectation=core.ToolExpectation(
            "public_goods_joint_action_payoff",
            "calculator",
            {
                "E": 10,
                "m_num": 3,
                "m_den": 2,
                "joint_action": [1, 0, 1, 0],
                "focal_seat": 0,
            },
        ),
    )
    restored = runner.classification_from_record(runner.record(classification))
    assert runner.record(restored) == runner.record(classification)
    with pytest.raises(design.CalibrationError, match="bytes tag"):
        runner.unrecord({"$bytes_hex": "xyz"})
