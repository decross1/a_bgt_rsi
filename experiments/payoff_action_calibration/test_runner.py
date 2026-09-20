from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import threading
from pathlib import Path

import pytest

from bench.flash_next_ab import transport
from experiments.payoff_action_calibration import runner
from experiments.payoff_tool_arithmetic import flash_resident as resident


def _binding() -> dict:
    image = resident.RUNTIME_IMAGE_ID
    value = {
        "endpoint": {
            "name": resident.ENDPOINT.name,
            "base_url": resident.ENDPOINT.base_url,
            "served_model": resident.ENDPOINT.served_model,
            "checkpoint_artifact_sha256": resident.ENDPOINT.artifact_sha256,
        },
        "checkpoint": {
            "model_revision": resident.MODEL_REVISION,
            "artifact_sha256": resident.ENDPOINT.artifact_sha256,
        },
        "runtime": {
            "backend": "sglang-flash",
            "image_id": image,
            "profile_sha256": resident.SERVING_PROFILE_SHA256,
            "context_length": 32768,
            "max_running_requests": 1,
            "host_reserve_gib": 20,
        },
        "deployment": {
            "path": str(resident.CANONICAL_ROOT / "config/model_deployment.json"),
            "config_sha256": "4" * 64,
            "selected_at": "2026-09-19",
        },
        "live": {
            "boot_id": "12345678-1234-1234-1234-123456789abc",
            "pid": 101,
            "process_start_ticks": 202,
            "guard_pid": 303,
            "guard_start_ticks": 404,
            "container_id": "5" * 64,
            "image_id": image,
            "artifact_dir": "/private/resident-test",
        },
    }
    value["live_identity_sha256"] = hashlib.sha256(
        json.dumps(value["live"], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return value


def _idle() -> dict:
    return {
        "schema_version": "flash-payoff-idle-probe/v1",
        "endpoint_name": resident.ENDPOINT.name,
        "running_requests": 0.0,
        "waiting_requests": 0.0,
        "metrics_sha256": "8" * 64,
        "metrics_bytes": 123,
        "observed_idle": True,
        "cooperative_exclusion_only": True,
        "direct_http_clients_excluded": False,
        "isolated_latency_claim": False,
    }


class FakeInvoke:
    def __init__(self) -> None:
        self.requests = 0

    def __call__(
        self,
        endpoint,
        messages,
        *,
        policy,
        max_tokens,
        timeout_s,
        seed,
        tools,
        cancel_event,
    ):
        self.requests += 1
        cell = next(
            row
            for row in runner.panel()
            if any(
                messages[:2] == runner._messages(row, arm) for arm in row["arm_order"]
            )
        )
        if tools:
            name = tools[0]["function"]["name"]
            arm = "table" if name == "public_goods_payoff_table" else "calculator"
            arguments = runner._tool_arguments(cell, arm)
            content = ""
            tool_calls = [
                {
                    "index": 0,
                    "id": f"call-{cell['cell_id']}-{arm}",
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": json.dumps(arguments, separators=(",", ":")),
                    },
                }
            ]
            finish = "tool_calls"
        else:
            content = json.dumps(
                {
                    "probe": cell["expected_probe"],
                    "actions": cell["controls"]["oracle_plan"],
                },
                separators=(",", ":"),
            )
            tool_calls = []
            finish = "stop"
        response_id = f"fake-{self.requests}"
        chunk = {
            "id": response_id,
            "model": endpoint.served_model,
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": content, "tool_calls": tool_calls},
                    "finish_reason": finish,
                }
            ],
        }
        usage = {
            "id": response_id,
            "model": endpoint.served_model,
            "choices": [],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        raw = (
            b"data: "
            + json.dumps(chunk, separators=(",", ":")).encode()
            + b"\n\n"
            + b"data: "
            + json.dumps(usage, separators=(",", ":")).encode()
            + b"\n\n"
            + b"data: [DONE]\n\n"
        )
        accumulator = transport.StreamAccumulator(endpoint.served_model)
        for line in raw.splitlines():
            payload = transport._sse_data(line)
            if payload is not None:
                accumulator.accept(payload)
        result = accumulator.result()
        body = transport.request_body(
            endpoint, messages, policy, max_tokens, seed, tools
        )
        result.update(
            {
                "request_sha256": hashlib.sha256(transport.canonical(body)).hexdigest(),
                "response_stream_sha256": hashlib.sha256(raw).hexdigest(),
                "endpoint": endpoint.__dict__,
                "resolved_request": body,
                "response_bytes": len(raw),
                "retries": 0,
                "private_evidence": transport._private_response_evidence(
                    accumulator, raw, response_bytes=len(raw)
                ),
            }
        )
        return result


class CancelAfterAdmission:
    def __init__(self) -> None:
        self.checks = 0

    def is_set(self) -> bool:
        self.checks += 1
        return self.checks >= 2


class CancelAfterHealthyPreCallProbe:
    def __init__(self) -> None:
        self.checks = 0

    def is_set(self) -> bool:
        self.checks += 1
        return self.checks >= 3


def _prepare(tmp_path: Path):
    binding = _binding()
    root = tmp_path / "artifacts"
    plan_path = root / "plan.json"
    plan = runner.make_plan(
        plan_path,
        study_id="excluded-action-calibration-v1",
        artifact_root=root,
        runtime_snapshot_fn=lambda: copy.deepcopy(binding),
        ready_fn=lambda: True,
        memory_fn=lambda: 21.0,
    )
    return binding, root, plan_path, plan


def _run(tmp_path: Path, *, cancel_event=None, run_memory_fn=None):
    binding, root, plan_path, plan = _prepare(tmp_path)
    fake = FakeInvoke()
    output = root / "run"
    result = runner.run(
        plan_path,
        output,
        cancel_event=cancel_event or threading.Event(),
        invoke_fn=fake,
        runtime_snapshot_fn=lambda: copy.deepcopy(binding),
        ready_fn=lambda: True,
        memory_fn=run_memory_fn or (lambda: 21.0),
        idle_probe_fn=_idle,
        lock_factory=lambda _root: contextlib.nullcontext(),
    )
    return plan_path, output, plan, result, fake


def test_panel_is_exact_dynamic_disjoint_and_covers_binding_axes():
    rows = runner.panel()
    assert len(rows) == 4
    assert {row["focal_seat"] for row in rows} == {0, 1, 2, 3}
    assert {row["probe"]["focal_action"] for row in rows} == {0, 1}
    assert {row["probe"]["other_contributors"] for row in rows} == {0, 1, 2, 3}
    assert {row["horizon"] for row in rows} == {4, 6, 9, 12}
    assert {row["endowment"] for row in rows} == {6, 10, 14, 18}
    assert not {row["task_sha256"] for row in rows}.intersection(
        runner._DEVELOPMENTAL_PRIMARY_TASK_HASHES
    )
    for raw, row in zip(runner._RAW_CELLS, rows, strict=True):
        unhashed = {key: value for key, value in raw.items() if key != "task_sha256"}
        assert runner._sha(runner._canonical(unhashed)) == raw["task_sha256"]
        controls = row["controls"]
        assert controls["dp_matches_exhaustive"] is True
        assert controls["future_dependent_rounds_1_indexed"]
        assert runner._simulate(row, tuple(controls["oracle_plan"])) > runner._simulate(
            row, tuple(controls["myopic_plan"])
        )
        assert controls["oracle_plan_sha256"] == runner._sha(
            runner._canonical(controls["oracle_plan"])
        )


def test_all_arms_share_complete_final_contract_without_answer_leakage():
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
        "numerator",
        "denominator",
        "canonical",
    }
    for cell in runner.panel():
        messages = {
            arm: runner._messages(cell, arm)
            for arm in ("direct", "table", "calculator")
        }
        assert len({rows[0]["content"] for rows in messages.values()}) == 1
        system = messages["direct"][0]["content"]
        assert all(field in system for field in required)
        assert runner._canonical(cell["expected_probe"]).decode() not in system
        assert runner._canonical(cell["controls"]["oracle_plan"]).decode() not in system
        assert "public_goods_payoff_table" not in messages["direct"][1]["content"]
        assert (
            "public_goods_joint_action_payoff" not in messages["direct"][1]["content"]
        )
        assert "public_goods_payoff_table" in messages["table"][1]["content"]
        assert (
            "public_goods_joint_action_payoff" in messages["calculator"][1]["content"]
        )


def test_plan_freezes_exact_denominators_guards_sources_and_plan_hash(tmp_path):
    _binding_value, _root, plan_path, plan = _prepare(tmp_path)
    loaded, raw_hash = runner.load_plan(plan_path)
    assert loaded == plan
    assert raw_hash == hashlib.sha256(plan_path.read_bytes()).hexdigest()
    assert len(plan["declared_units"]) == 4
    assert len(plan["declared_conditions"]) == 12
    assert len(plan["declared_slots"]) == 20
    assert plan["limits"]["max_calls"] == 20
    assert plan["limits"]["max_tokens"] == 512
    assert plan["limits"]["memory_floor_gib"] == 20.0
    assert plan["permanently_excluded"] is True
    assert plan["scientific_admission_eligible"] is False
    assert plan["confirmation_authorized"] is False
    assert "experiments/known_opponent_utility/pilot.py" in plan["source_sha256"]
    assert "bench/flash_next_ab/manifest.py" in plan["source_sha256"]
    assert "bench/flash_next_ab/qualification.py" in plan["source_sha256"]
    assert runner._EXPECTED_LOCAL_IMPORT_CLOSURE.issubset(plan["source_sha256"])


def test_complete_run_replays_all_requests_streams_tools_grades_and_resources(tmp_path):
    plan_path, output, _plan, result, fake = _run(tmp_path)
    assert result["status"] == "complete"
    assert fake.requests == 20
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
    assert len(result["resource_observations"]) == 40
    assert all(row["memory_gib"] == 21.0 for row in result["resource_observations"])
    validation = runner.validate(plan_path, output)
    assert validation["status"] == "passed"
    assert validation["raw_sse_replay_passed"] is True
    assert validation["private_calls_verified"] == {
        "calls": 20,
        "returned_streams": 20,
    }
    for arm in ("direct", "table", "calculator"):
        assert (
            validation["objective_summary"]["arms"][arm]["strict_final"]["passed"] == 4
        )
        assert (
            validation["objective_summary"]["arms"][arm]["zero_regret"]["passed"] == 4
        )
    assert validation["objective_summary"]["arms"]["table"]["tool_exact"]["passed"] == 4
    assert (
        validation["objective_summary"]["arms"]["calculator"]["tool_exact"]["passed"]
        == 4
    )
    assert validation["scientific_admission_eligible"] is False


def test_aborted_zero_call_bundle_is_explicitly_nonpassing(tmp_path):
    plan_path, output, _plan, result, fake = _run(
        tmp_path, cancel_event=CancelAfterAdmission()
    )
    assert fake.requests == 0
    assert result["status"] == "aborted"
    assert result["accounting"]["attempted_calls"] == 0
    assert result["accounting"]["returned_calls"] == 0
    validation = runner.validate(plan_path, output)
    assert validation["status"] == "validated_incomplete"
    assert validation["raw_sse_replay_passed"] is True
    assert validation["private_calls_verified"] == {"calls": 0, "returned_streams": 0}
    assert validation["scientific_admission_eligible"] is False


def test_post_probe_cancellation_binds_healthy_terminal_observation(tmp_path):
    plan_path, output, _plan, result, fake = _run(
        tmp_path, cancel_event=CancelAfterHealthyPreCallProbe()
    )
    assert fake.requests == 0
    assert result["status"] == "aborted"
    assert result["abort_reason"] == "cancelled_after_pre_call_probes"
    assert len(result["resource_observations"]) == 1
    terminal = result["resource_observations"][0]
    assert terminal["ready"] is True
    assert terminal["memory_gib"] == 21.0
    assert terminal["runtime_identity_matches"] is True
    validation = runner.validate(plan_path, output)
    assert validation["status"] == "validated_incomplete"


@pytest.mark.parametrize(
    ("samples", "expected_requests"),
    [([21.0, 19.0], 0), ([21.0, 21.0, 21.0, 19.0], 1)],
)
def test_pre_call_memory_guard_abort_is_sealed_and_validates_incomplete(
    tmp_path, samples, expected_requests
):
    remaining = iter(samples)
    plan_path, output, _plan, result, fake = _run(
        tmp_path, run_memory_fn=lambda: next(remaining)
    )
    assert result["status"] == "aborted"
    assert result["abort_reason"] == "memory_floor_before_next_call"
    assert fake.requests == expected_requests
    assert result["accounting"]["attempted_calls"] == expected_requests
    assert len(result["resource_observations"]) == expected_requests * 2 + 1
    terminal = result["resource_observations"][-1]
    assert terminal["stage"] == "pre_call"
    assert terminal["memory_gib"] == 19.0
    validation = runner.validate(plan_path, output)
    assert validation["status"] == "validated_incomplete"
    assert validation["scientific_admission_eligible"] is False


def test_validator_rejects_mutated_grade_and_descriptor_identity(tmp_path):
    plan_path, output, _plan, _result, _fake = _run(tmp_path)
    run_path = output / "run.json"
    value = json.loads(run_path.read_text())
    value["outcomes"][0]["grade"]["final"]["zero_regret"] = False
    run_path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")
    with pytest.raises(runner.CalibrationError, match="grade differs"):
        runner.validate(plan_path, output)

    # Restore through a separate run, then mutate only descriptor identity.
    other = tmp_path / "other"
    plan_path, output, _plan, _result, _fake = _run(other)
    run_path = output / "run.json"
    value = json.loads(run_path.read_text())
    descriptor = value["slots"][0]["private_descriptor"]
    descriptor["call_id"] = "forged-call"
    value["outcomes"][0]["grade"]["_private_call_evidence"]["artifacts"][0][
        "call_id"
    ] = "forged-call"
    run_path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")
    with pytest.raises(runner.CalibrationError, match="call binding differs"):
        runner.validate(plan_path, output)
