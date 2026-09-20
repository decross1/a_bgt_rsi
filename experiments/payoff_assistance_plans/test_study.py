from __future__ import annotations

import contextlib
import copy
import hashlib
import itertools
import json
import threading
from collections import Counter
from fractions import Fraction
from pathlib import Path

import pytest

from bench.flash_next_ab import private_evidence, transport
from experiments.payoff_assistance_plans import study
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
    def __init__(self, mode: str = "valid") -> None:
        self.mode = mode
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
        scenario = next(
            row
            for row in study.panel("shakedown")
            if messages == study._messages(row, tool_first=False)
            or messages == study._messages(row, tool_first=True)
            or (
                len(messages) == 5
                and messages[:2] == study._messages(row, tool_first=True)
            )
        )
        if self.mode == "prewire" and self.requests == 1:
            raise ValueError("local construction error")
        if self.mode == "timeout":
            exc = TimeoutError("no response bytes")
            accumulator = transport.StreamAccumulator(endpoint.served_model)
            exc.private_evidence = transport._private_response_evidence(
                accumulator, b"", response_bytes=0
            )
            raise exc
        if tools:
            arguments = study._tool_arguments(scenario)
            if self.mode == "wrong_args" and scenario["scenario_id"] == "shake-01":
                arguments["E"] += 1
            content = ""
            tool_calls = [
                {
                    "index": 0,
                    "id": f"call-{scenario['scenario_id']}",
                    "type": "function",
                    "function": {
                        "name": "public_goods_payoff_table",
                        "arguments": json.dumps(arguments, separators=(",", ":")),
                    },
                }
            ]
            finish = "tool_calls"
        else:
            content = json.dumps(
                {
                    "probe": scenario["probe_expected"],
                    "actions": scenario["controls"]["lexicographic_oracle_plan"],
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
                    "delta": {
                        "content": content,
                        "tool_calls": tool_calls,
                    },
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


def _prepare(tmp_path: Path, cohort: str = "shakedown"):
    binding = _binding()
    root = tmp_path / "artifacts"
    path = root / "plan.json"
    plan = study.make_plan(
        path,
        study_id=f"payoff-plan-{cohort}-v1",
        cohort=cohort,
        artifact_root=root,
        runtime_snapshot_fn=lambda: copy.deepcopy(binding),
        ready_fn=lambda: True,
        memory_fn=lambda: 21.0,
    )
    return binding, path, plan


def _run(tmp_path: Path, mode: str = "valid"):
    binding, plan_path, _plan = _prepare(tmp_path)
    fake = FakeInvoke(mode)
    output = tmp_path / "artifacts" / "run"
    result = study.run(
        plan_path,
        output,
        cancel_event=threading.Event(),
        invoke_fn=fake,
        runtime_snapshot_fn=lambda: copy.deepcopy(binding),
        ready_fn=lambda: True,
        memory_fn=lambda: 21.0,
        idle_probe_fn=_idle,
        lock_factory=lambda _root: contextlib.nullcontext(),
    )
    return plan_path, output, result, fake


def test_panels_are_unique_balanced_and_permanently_disjoint():
    confirmatory = study.panel("confirmatory")
    shake = study.panel("shakedown")
    assert len(confirmatory) == 30
    assert len(shake) == 3
    assert len({row["task_sha256"] for row in confirmatory}) == 30
    assert not (
        {row["task_sha256"] for row in confirmatory}
        & {row["task_sha256"] for row in shake}
    )
    assert {
        script: sum(row["opponent_script"] == script for row in confirmatory)
        for script in ("retainers", "contributors", "grim")
    } == {
        "retainers": 10,
        "contributors": 10,
        "grim": 10,
    }
    assert sum(row["objective"] == "own_payoff" for row in confirmatory) == 15
    assert sum(row["focal_seat"] == 0 for row in confirmatory) == 15
    assert Counter(row["analysis_stratum"] for row in confirmatory) == {
        "dynamic_strategic": 5,
        "joint_objective_control": 15,
        "static_opponent_control": 10,
    }
    direct_first = {
        objective: sum(
            row["objective"] == objective and row["arm_order"][0] == "direct"
            for row in confirmatory
        )
        for objective in ("own_payoff", "joint_payoff")
    }
    assert direct_first == {"own_payoff": 8, "joint_payoff": 7}
    crosses = Counter(
        (row["objective"], row["focal_seat"], row["arm_order"][0])
        for row in confirmatory
    )
    assert set(crosses) == {
        (objective, seat, first)
        for objective in ("own_payoff", "joint_payoff")
        for seat in (0, 3)
        for first in ("direct", "tool")
    }


def test_exact_simulator_dynamic_program_and_myopic_control():
    scenario = next(
        row
        for row in study.panel("confirmatory")
        if row["opponent_script"] == "grim" and row["objective"] == "own_payoff"
    )
    value, count, best = study._oracle(scenario)
    assert value == study._simulate(scenario, best)["objective"]
    assert count >= 1
    assert Fraction(scenario["controls"]["oracle_utility"]) == value
    myopic = tuple(scenario["controls"]["myopic_plan"])
    assert Fraction(scenario["controls"]["myopic_regret"]) == (
        value - study._simulate(scenario, myopic)["objective"]
    )


def test_dynamic_program_exhaustively_matches_all_33_frozen_scenarios():
    for cohort in ("confirmatory", "shakedown"):
        for scenario in study.panel(cohort):
            enumerated = [
                (study._simulate(scenario, plan)["objective"], plan)
                for plan in itertools.product((0, 1), repeat=study.HORIZON)
            ]
            maximum = max(value for value, _plan in enumerated)
            winners = [plan for value, plan in enumerated if value == maximum]
            value, count, best = study._oracle(scenario)
            assert value == maximum
            assert count == len(winners)
            assert best == min(winners)
            assert scenario["controls"]["oracle_utility"] == study._rational(maximum)


def test_tool_table_uses_exact_disclosed_formulas_without_strategy():
    scenario = study.panel("shakedown")[0]
    payload = study._tool_payload(scenario)
    assert payload["strategy_or_recommendation_included"] is False
    row = next(
        row
        for row in payload["rows"]
        if row["other_contributors"] == 2 and row["focal_action"] == 0
    )
    m = Fraction(scenario["m_num"], scenario["m_den"])
    shared = m * scenario["endowment"] * 2 / 4
    assert Fraction(row["shared_per_player"]) == shared
    assert Fraction(row["focal_payoff"]) == scenario["endowment"] + shared
    for cohort in ("confirmatory", "shakedown"):
        for scenario in study.panel(cohort):
            payload = study._tool_payload(scenario)
            for row in payload["rows"]:
                actions = [0] * study.PLAYERS
                actions[scenario["focal_seat"]] = row["focal_action"]
                remaining = [
                    seat
                    for seat in range(study.PLAYERS)
                    if seat != scenario["focal_seat"]
                ]
                for seat in remaining[: row["other_contributors"]]:
                    actions[seat] = 1
                values = study._round_payoffs(
                    tuple(actions),
                    endowment=scenario["endowment"],
                    multiplier=Fraction(scenario["m_num"], scenario["m_den"]),
                )
                assert Fraction(row["focal_payoff"]) == values[scenario["focal_seat"]]
                assert Fraction(row["group_payoff"]) == sum(values, Fraction())


def test_arithmetic_comprehension_and_strategic_regret_are_separate_scores():
    scenario = study.panel("shakedown")[0]
    wrong_probe = {"focal": "0", "total": "0"}
    oracle_content = json.dumps(
        {
            "probe": wrong_probe,
            "actions": scenario["controls"]["lexicographic_oracle_plan"],
        },
        separators=(",", ":"),
    )
    grade = study._grade_final(
        oracle_content, "returned", scenario, finish_reason="stop", tool_calls=()
    )
    assert grade["valid_plan"] is True
    assert grade["zero_regret"] is True
    assert grade["comprehension_correct"] is False

    all_contribute = json.dumps(
        {
            "probe": scenario["probe_expected"],
            "actions": [1] * study.HORIZON,
        },
        separators=(",", ":"),
    )
    grade = study._grade_final(
        all_contribute, "returned", scenario, finish_reason="stop", tool_calls=()
    )
    assert grade["comprehension_correct"] is True
    assert grade["valid_plan"] is True
    assert grade["zero_regret"] is False


def test_plan_freezes_denominators_runtime_sources_and_claim_boundary(tmp_path):
    binding, path, plan = _prepare(tmp_path, "shakedown")
    loaded, digest = study.load_plan(path)
    assert loaded == plan
    assert plan["runtime_binding"] == binding
    assert len(plan["declared_units"]) == 3
    assert len(plan["declared_conditions"]) == 6
    assert len(plan["declared_slots"]) == 9
    assert plan["limits"]["max_calls"] == 9
    assert plan["research_context"] == study.RESEARCH_CONTEXT
    assert plan["scientific_admission_registered"] is False
    assert digest == hashlib.sha256(path.read_bytes()).hexdigest()


def test_confirmatory_prepare_and_run_are_hard_gated(tmp_path, monkeypatch):
    called = False

    def snapshot():
        nonlocal called
        called = True
        return _binding()

    with pytest.raises(study.PayoffAssistanceError, match="deferred"):
        study.make_plan(
            tmp_path / "artifacts" / "confirm.json",
            study_id="confirmatory-must-not-run",
            cohort="confirmatory",
            artifact_root=tmp_path / "artifacts",
            runtime_snapshot_fn=snapshot,
            ready_fn=lambda: True,
            memory_fn=lambda: 21.0,
        )
    assert called is False

    monkeypatch.setattr(
        study,
        "load_plan",
        lambda _path: (
            {
                "cohort": "confirmatory",
                "scientific_admission_registered": False,
            },
            "0" * 64,
        ),
    )
    with pytest.raises(study.PayoffAssistanceError, match="registration"):
        study.run("unused-plan", "unused-output", cancel_event=threading.Event())


def test_shakedown_run_replays_raw_evidence_controls_and_all_grades(tmp_path):
    plan_path, output, result, fake = _run(tmp_path)
    assert result["status"] == "complete"
    assert fake.requests == 9
    receipt = study.validate(plan_path, output)
    assert receipt["status"] == "passed"
    assert receipt["shakedown_permanently_excluded"] is True
    assert receipt["scientific_admission_eligible"] is False
    summary = receipt["objective_summary"]
    assert summary["direct_comprehension"]["correct"] == 3
    assert summary["tool_invocation"]["exact"] == 3
    assert summary["tool_zero_regret"]["passed"] == 3
    assert summary["paired_regret_direction"] == {
        "tool_lower": 0,
        "equal": 3,
        "tool_higher": 0,
        "incomplete": 0,
    }
    assert summary["paired_regret"]["tool_minus_direct_mean"] == "0"
    assert summary["paired_comprehension_transitions"]["both_correct"] == 3
    assert len(summary["objective_by_script_strata"]) == 3
    assert summary["strategic_interpretation"] == {
        "primary_stratum": "dynamic_strategic",
        "primary_stratum_units": 1,
        "control_units": 2,
        "aggregate_plan_success_is_not_a_strategic_effect_estimate": True,
    }


def test_wrong_tool_arguments_remain_denominator_and_skip_only_final(tmp_path):
    plan_path, output, result, fake = _run(tmp_path, "wrong_args")
    assert result["status"] == "complete"
    assert fake.requests == 8
    receipt = study.validate(plan_path, output)
    assert receipt["objective_summary"]["tool_invocation"]["exact"] == 2
    assert receipt["accounting"]["skipped_unissued"] == 1


def test_zero_return_and_prewire_runs_cannot_validate(tmp_path):
    plan_path, output, result, _fake = _run(tmp_path / "timeouts", "timeout")
    assert result["status"] == "complete"
    assert result["accounting"]["returned_calls"] == 0
    with pytest.raises(study.PayoffAssistanceError, match="accounting"):
        study.validate(plan_path, output)
    plan_path, output, result, _fake = _run(tmp_path / "prewire", "prewire")
    assert result["status"] == "aborted"
    assert result["accounting"]["prewire_failures"] == 1
    record_path = output / "run.json"
    forged = json.loads(record_path.read_text())
    forged["status"] = "complete"
    forged["abort_reason"] = None
    record_path.write_bytes(study._canonical(forged) + b"\n")
    with pytest.raises(study.PayoffAssistanceError, match="accounting"):
        study.validate(plan_path, output)


def test_raw_sse_tampering_is_rejected(tmp_path):
    plan_path, output, _result, _fake = _run(tmp_path)
    stream = next((output / "private" / "streams").iterdir())
    stream.write_bytes(stream.read_bytes() + b"data: [DONE]\n\n")
    with pytest.raises(
        (study.PayoffAssistanceError, private_evidence.PrivateEvidenceError, ValueError)
    ):
        study.validate(plan_path, output)


def test_forged_slot_status_cannot_pass_accounting(tmp_path):
    plan_path, output, _result, _fake = _run(tmp_path)
    record_path = output / "run.json"
    forged = json.loads(record_path.read_text())
    forged["slots"][0]["status"] = "forged-timeout"
    forged["slots"][0]["failure_code"] = "forged"
    record_path.write_bytes(study._canonical(forged) + b"\n")
    with pytest.raises(study.PayoffAssistanceError, match="derive exactly"):
        study.validate(plan_path, output)
