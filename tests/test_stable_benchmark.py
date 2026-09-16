from __future__ import annotations

import hashlib
import json
import time
from copy import deepcopy
from pathlib import Path

import pytest

from bench.stable_benchmark import (
    admit_replay,
    bind_run_manifest,
    load_definition,
    load_run_manifest,
    make_draft,
    program_projection,
    publish_definition,
    replay_run,
    run_arm,
    write_unissued_receipt,
)
from bench.stable_benchmark.graders import grade_task
from bench.stable_benchmark.manifest import LoadedDocument, ManifestError, canonical_json, write_document
from bench.stable_benchmark.runner import (
    InvocationFailure,
    InvocationRequest,
    InvocationResult,
    _execute_system_tool,
    _validate_record,
    execution_source_hashes,
    invoke_via_wrapper,
)
from bench.stable_benchmark.projection import _safe_metrics


ZERO = "0" * 64
ONE = "1" * 64


def _published(tmp_path: Path):
    definition = publish_definition(
        make_draft(),
        published_at="2026-09-16T04:30:00Z",
        witness={"kind": "preregistration_receipt", "ref": "test-witness", "sha256": ONE},
    )
    path = tmp_path / "definition.json"
    write_document(path, definition)
    return load_definition(path, require_published=True)


def _route(model: str, backend: str, profile: str, *, reasoning_effort: str | None = None) -> dict:
    return {
        "backend": backend,
        "model": model,
        "profile": profile,
        "expected_policy": {
            "temperature": 0.2,
            "top_p": 0.95,
            "reasoning_effort": reasoning_effort,
            "sampling_extra": {},
        },
        "runtime_identity": {
            "served_model": model,
            "artifact_sha256": ZERO,
            "runtime_sha256": ONE,
            "max_context_tokens": 32768,
        },
    }


def _arm() -> dict:
    return {
        "id": "resident-stack",
        "label": "Gemma actor with Qwen critic",
        "seed": 17,
        "routes": {
            "gemma": _route("gemma-test", "vllm-gemma", "precise"),
            "qwen": _route(
                "qwen-test", "vllm-qwen", "critic_current", reasoning_effort="xhigh"
            ),
        },
        "role_map": {
            "capability": "gemma",
            "system_actor": "gemma",
            "system_critic": "qwen",
        },
    }


def _bound_manifest(tmp_path: Path, definition):
    manifest = bind_run_manifest(
        definition,
        arm=_arm(),
        comparison_id="stable-test-pair",
        harness_identity={
            "scaffold_id": "stable-benchmark-runner-v1",
            "transport_contract": "injected-supervised-endpoint/v1",
            "source_sha256": execution_source_hashes(),
        },
    )
    path = tmp_path / "run-manifest.json"
    write_document(path, manifest)
    return load_run_manifest(path, definition)


def test_definition_counts_projection_and_safe_loader(tmp_path: Path):
    draft = make_draft()
    assert len([t for t in draft["tasks"] if t["panel"] == "model_capability"]) == 18
    assert len([t for t in draft["tasks"] if t["panel"] == "system_micro_workflow"]) == 3
    assert draft["resource_envelope"] == {
        "max_model_calls_per_arm": 29,
        "max_model_calls_paired": 58,
        "max_output_tokens_per_arm": 25088,
        "max_episode_runtime_s_per_arm": 1575,
        "max_supervised_window_s": 7200,
        "paid_api_cost_usd": 0,
        "execution": "serial_one_spark",
    }
    path = tmp_path / "draft.json"
    write_document(path, draft)
    loaded = load_definition(path)
    projection = program_projection(loaded)
    encoded = json.dumps(projection)
    assert len(projection["task_index"]) == 21
    assert '"prompt"' not in encoded
    assert '"grader"' not in encoded
    link = tmp_path / "redirect.json"
    link.symlink_to(path)
    with pytest.raises(ManifestError, match="regular non-symlink"):
        load_definition(link)


def test_strategic_oracles_derive_utility_and_regret():
    tasks = {task["id"]: task for task in make_draft()["tasks"]}
    public_goods = grade_task(tasks["GAME-PUBLIC-GOODS-101"], {"action": 0})
    assert public_goods.passed
    assert public_goods.metrics["own_utility_regret"] == {"numerator": 0, "denominator": 1}
    cournot = grade_task(tasks["GAME-COURNOT-307"], {"action": 6})
    assert cournot.passed
    proper = grade_task(tasks["GAME-BRIER-401"], {"action": 65})
    assert proper.passed
    assert proper.metrics["joint_utility_interpretation"] == "descriptive_only"
    nearby = grade_task(tasks["GAME-BRIER-401"], {"action": 64})
    assert not nearby.passed
    assert nearby.metrics["own_utility_regret"] == {"numerator": 1, "denominator": 10000}


def test_public_response_contracts_disclose_exact_enums_fields_and_numeric_tolerance():
    tasks = {task["id"]: task for task in make_draft()["tasks"]}
    support = tasks["EVID-SUPPORT-001"]
    abstain = tasks["EVID-ABSTAIN-001"]
    assert "randomized_observed_rate_higher" in support["prompt"]
    assert "minimal sufficient source set" in support["prompt"]
    assert "missing_denominator" in abstain["prompt"]
    assert "minimal sufficient source set" in abstain["prompt"]

    markov = tasks["SCI-MARKOV-001"]
    assert "absolute error <=1e-9" in markov["prompt"]
    rounded = grade_task(markov, {
        "stationary_a": 0.6666666667,
        "stationary_b": 0.3333333333,
        "long_run_reward": 5.0,
    })
    assert rounded.passed

    mission_literals = {
        "SYSTEM-PAYOFF-001": (
            "focal_num", "focal_den", "joint_num", "joint_den", "decision", "retain",
        ),
        "SYSTEM-AUCTION-001": (
            "mechanism", "recommended_bid", "own_utility", "regret", "verdict",
            "vickrey", "proceed",
        ),
        "SYSTEM-EVIDENCE-001": (
            "decision", "reason_code", "requested_next_field",
            "missing_denominator", "denominator",
        ),
    }
    for task_id, literals in mission_literals.items():
        prompt = tasks[task_id]["prompt"]
        assert all(literal in prompt for literal in literals), task_id


def test_system_critic_uses_remaining_episode_budget_after_bounded_actor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    task = next(task for task in make_draft()["tasks"] if task["id"] == "SYSTEM-EVIDENCE-001")
    arm = _arm()
    observed_timeouts = []
    completions = iter((
        json.dumps({
            "tool": "check_evidence_support",
            "arguments": {"claim": "rate_is_60_percent", "count": 12, "denominator": None},
            "draft": {"decision": "abstain"},
        }),
        json.dumps(task["grader"]["expected_final"]),
    ))

    def fake_call_sync(_messages, **kwargs):
        observed_timeouts.append(kwargs["request_timeout_s"])
        return {"completion": next(completions)}

    monkeypatch.setattr("agent_wrapper.wrapper.call_sync", fake_call_sync)
    request = InvocationRequest(
        run_id="critic-budget-test",
        task=task,
        arm=arm,
        absolute_deadline_monotonic=time.monotonic() + 120,
        calls_log_path=tmp_path / "calls.jsonl",
        worker_activity_path=tmp_path / "activity.jsonl",
    )
    result = invoke_via_wrapper(request)
    assert result.failure_code is None
    assert len(result.records) == 2
    assert 0 < observed_timeouts[0] <= 60
    assert observed_timeouts[1] > 100
    assert observed_timeouts[1] < 115.1


def test_system_tools_compute_instead_of_looking_up_fixture():
    result = _execute_system_tool(
        "compute_public_goods",
        {
            "endowment": 10,
            "contributions": [0, 3, 8, 4],
            "multiplier_num": 8,
            "multiplier_den": 5,
            "focal_index": 3,
        },
    )
    assert result == {"focal_num": 12, "focal_den": 1, "joint_num": 49, "joint_den": 1}
    changed = _execute_system_tool(
        "compute_public_goods",
        {
            "endowment": 10,
            "contributions": [0, 3, 8, 5],
            "multiplier_num": 8,
            "multiplier_den": 5,
            "focal_index": 3,
        },
    )
    assert changed != result
    negative = _execute_system_tool(
        "check_evidence_support",
        {"claim": "rate_is_60_percent", "count": 12, "denominator": None},
    )
    assert negative == {"supported": False, "reason_code": "missing_denominator"}


def test_policy_and_json_types_are_part_of_the_frozen_contract():
    task = next(task for task in make_draft()["tasks"] if task["id"] == "SCI-MARKOV-001")
    arm = _arm()
    route = arm["routes"][arm["role_map"]["capability"]]
    record = {
        "request_id": "req",
        "model": route["model"],
        "model_version": "runtime",
        "backend": route["backend"],
        "profile": route["profile"],
        "temperature": 0.2,
        "top_p": 0.95,
        "reasoning_effort": None,
        "sampling_extra": {},
        "seed": arm["seed"],
        "max_tokens": task["resource"]["max_tokens_per_call"],
        "host_metadata": {},
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
    assert _validate_record(record, task, arm, "capability") is None
    record["reasoning_effort"] = "xhigh"
    assert "reasoning_effort" in _validate_record(record, task, arm, "capability")

    mission = next(task for task in make_draft()["tasks"] if task["id"] == "SYSTEM-AUCTION-001")
    wrong_boolean = dict(mission["grader"]["expected_final"])
    wrong_boolean["verdict"] = "proceed"
    wrong_boolean["own_utility"] = True
    grade = grade_task(
        mission,
        wrong_boolean,
        tool_trace=mission["grader"]["expected_trace"],
    )
    assert not grade.passed
    strategic = next(task for task in make_draft()["tasks"] if task["id"] == "GAME-COURNOT-307")
    assert _safe_metrics(strategic, {"completion": "raw payload must not escape"}) == {}

    definition = make_draft()
    published = publish_definition(
        definition,
        published_at="2026-09-16T04:30:00Z",
        witness={"kind": "preregistration_receipt", "ref": "test", "sha256": ONE},
    )
    loaded = LoadedDocument(published, ZERO)
    bad_arm = _arm()
    bad_arm["routes"]["unused"] = _route("unused", "vllm-gemma", "precise")
    with pytest.raises(ManifestError, match="exactly the routes used"):
        bind_run_manifest(
            loaded,
            arm=bad_arm,
            comparison_id="bad-unused-route",
            harness_identity={
                "scaffold_id": "stable-benchmark-runner-v1",
                "transport_contract": "injected-supervised-endpoint/v1",
                "source_sha256": execution_source_hashes(),
            },
        )
    bad_arm = _arm()
    bad_arm["routes"]["gemma"]["expected_policy"]["top_p"] = 1.5
    with pytest.raises(ManifestError, match="top_p"):
        bind_run_manifest(
            loaded,
            arm=bad_arm,
            comparison_id="bad-policy-range",
            harness_identity={
                "scaffold_id": "stable-benchmark-runner-v1",
                "transport_contract": "injected-supervised-endpoint/v1",
                "source_sha256": execution_source_hashes(),
            },
        )


def test_fresh_code_repairs_execute_in_isolated_function_sandbox():
    tasks = {task["id"]: task for task in make_draft()["tasks"]}
    sources = {
        "CODE-MERGE-001": '''def merge_windows(windows):
    rows = []
    for window in windows:
        if len(window) != 2 or window[0] > window[1]:
            raise ValueError("invalid window")
        rows.append([window[0], window[1]])
    rows = sorted(rows)
    merged = []
    for row in rows:
        if not merged or row[0] > merged[-1][1]:
            merged.append([row[0], row[1]])
        elif row[1] > merged[-1][1]:
            merged[-1][1] = row[1]
    return merged''',
        "CODE-WEIGHTED-MEDIAN-001": '''def weighted_median(values, weights):
    if len(values) == 0 or len(values) != len(weights):
        raise ValueError("invalid lengths")
    for weight in weights:
        if weight < 0:
            raise ValueError("negative weight")
    total = sum(weights)
    if total <= 0:
        raise ValueError("zero weight")
    cumulative = 0
    for pair in sorted(zip(values, weights)):
        cumulative += pair[1]
        if cumulative * 2 >= total:
            return pair[0]
    raise ValueError("unreachable")''',
        "CODE-DRAWDOWN-001": '''def max_drawdown(values):
    if not values:
        raise ValueError("empty")
    for value in values:
        if value < 0:
            raise ValueError("negative")
    peak_value = values[0]
    peak_index = 0
    best_drop = 0
    best_peak = 0
    best_trough = 0
    for index in range(1, len(values)):
        drop = peak_value - values[index]
        if drop > best_drop:
            best_drop = drop
            best_peak = peak_index
            best_trough = index
        if values[index] > peak_value:
            peak_value = values[index]
            peak_index = index
    return {"drop": best_drop, "peak_index": best_peak, "trough_index": best_trough}''',
        "CODE-WATERFALL-001": '''def waterfall_payments(claims, cash):
    if cash < 0:
        raise ValueError("negative cash")
    for claim in claims:
        if claim < 0:
            raise ValueError("negative claim")
    remaining = cash
    payments = []
    for claim in claims:
        payment = min(claim, remaining)
        payments.append(payment)
        remaining -= payment
    return {"payments": payments, "residual": remaining}''',
    }
    for task_id, source in sources.items():
        grade = grade_task(tasks[task_id], {"source": source})
        assert grade.passed, f"{task_id}: {grade.reason}"


class _NeverCancel:
    def is_set(self) -> bool:
        return False


def test_run_replay_admission_chain_never_self_admits(tmp_path: Path):
    definition = _published(tmp_path)
    manifest = _bound_manifest(tmp_path, definition)
    arm = manifest.document["arm"]

    def invoke(request: InvocationRequest) -> InvocationResult:
        role = "system_actor" if request.task["mode"] == "system_mission" else "capability"
        route = arm["routes"][arm["role_map"][role]]
        record = {
            "request_id": f"req-{request.task['id']}",
            "model": route["model"],
            "model_version": "test-runtime",
            "backend": route["backend"],
            "profile": route["profile"],
            "temperature": route["expected_policy"]["temperature"],
            "top_p": route["expected_policy"]["top_p"],
            "reasoning_effort": route["expected_policy"]["reasoning_effort"],
            "sampling_extra": route["expected_policy"]["sampling_extra"],
            "seed": arm["seed"],
            "max_tokens": request.task["resource"]["max_tokens_per_call"],
            "host_metadata": {"test": True},
            "usage": {"input_tokens": 3, "output_tokens": 1},
            "completion": "{}",
        }
        return InvocationResult(
            completion="{}",
            records=(record,),
            failure_code="synthetic_invalid",
            failure_detail="test intentionally exercises invalid model output",
            attempt_count=1,
        )

    gate = {
        "admitted": True,
        "definition_sha256": definition.raw_sha256,
        "run_manifest_sha256": manifest.raw_sha256,
        "route_runtime_identities": {
            route_id: route["runtime_identity"] for route_id, route in arm["routes"].items()
        },
        "endpoint_bindings_sha256": ZERO,
        "supervision_receipt_sha256": ONE,
        "resource_guard_sha256": ZERO,
    }
    run_dir = tmp_path / "run"
    run = run_arm(
        definition,
        manifest,
        output_dir=run_dir,
        execution_gate=gate,
        absolute_deadline_monotonic=time.monotonic() + 60,
        cancel_event=_NeverCancel(),
        invoke=invoke,
    )
    assert run["terminal_status"] == "complete"
    assert run["summary"]["model_calls"] == 21
    assert run["admission_status"] == "not_evaluated"
    replay = replay_run(definition, manifest, run_dir=run_dir)
    assert replay["verified"] is True
    assert replay["arm_id"] == manifest.document["arm"]["id"]
    assert replay["comparison_id"] == manifest.document["comparison_id"]

    run_bytes = (run_dir / "run.json").read_bytes()
    replay_bytes = (run_dir / "replay.json").read_bytes()
    supervisor = {
        "schema_version": "stable-benchmark-supervisor-final/v1",
        "terminal_status": "complete",
        "definition_sha256": definition.raw_sha256,
        "run_manifest_sha256": manifest.raw_sha256,
        "run_receipt_sha256": hashlib.sha256(run_bytes).hexdigest(),
        "replay_receipt_sha256": hashlib.sha256(replay_bytes).hexdigest(),
        "execution_gate_sha256": run["execution_gate_sha256"],
        "monitor_end_passed": True,
        "no_guard_breach": True,
        "restoration_passed": True,
        "controller_source_sha256": {"controller.py": ZERO},
        "finished_at": "2026-09-16T05:00:00Z",
    }
    supervisor_path = tmp_path / "supervisor-final.json"
    supervisor_path.write_bytes(canonical_json(supervisor) + b"\n")
    admission = admit_replay(
        definition,
        manifest,
        run_dir=run_dir,
        supervisor_final_path=supervisor_path,
    )
    assert admission["admitted"] is True
    projection = program_projection(
        definition,
        run_receipts=[(run, hashlib.sha256(run_bytes).hexdigest())],
        replay_receipts=[(replay, hashlib.sha256(replay_bytes).hexdigest())],
        admission_receipts=[
            (admission, hashlib.sha256((run_dir / "admission.json").read_bytes()).hexdigest())
        ],
    )
    assert projection["runs"][0]["admission_status"] == "admitted"
    assert projection["runs"][0]["summary"]["independent_units"] == 21

    # A self-consistent-looking admission object must not make an invalid
    # replay row public.  Booleans are integers in Python, so this protects a
    # particularly easy model-call accounting bypass.
    bad_replay = deepcopy(replay)
    bad_replay["outcomes"][0]["model_calls"] = True
    bad_replay_sha = hashlib.sha256(canonical_json(bad_replay) + b"\n").hexdigest()
    bad_admission = deepcopy(admission)
    bad_admission["replay_receipt_sha256"] = bad_replay_sha
    rejected = program_projection(
        definition,
        run_receipts=[(run, hashlib.sha256(run_bytes).hexdigest())],
        replay_receipts=[(bad_replay, bad_replay_sha)],
        admission_receipts=[(bad_admission, ZERO)],
    )
    assert rejected["runs"][0]["replay_status"] == "invalid"
    assert rejected["runs"][0]["summary"] is None

    wrong_arm = deepcopy(replay)
    wrong_arm["arm_id"] = "different-arm"
    wrong_arm_sha = hashlib.sha256(canonical_json(wrong_arm) + b"\n").hexdigest()
    wrong_arm_admission = deepcopy(admission)
    wrong_arm_admission["replay_receipt_sha256"] = wrong_arm_sha
    rejected = program_projection(
        definition,
        run_receipts=[(run, hashlib.sha256(run_bytes).hexdigest())],
        replay_receipts=[(wrong_arm, wrong_arm_sha)],
        admission_receipts=[(wrong_arm_admission, ONE)],
    )
    assert rejected["runs"][0]["summary"] is None
    admission_record = (admission, hashlib.sha256((run_dir / "admission.json").read_bytes()).hexdigest())
    with pytest.raises(ValueError, match="duplicate conflicting"):
        program_projection(
            definition,
            run_receipts=[(run, hashlib.sha256(run_bytes).hexdigest())],
            replay_receipts=[(replay, hashlib.sha256(replay_bytes).hexdigest())],
            admission_receipts=[admission_record, admission_record],
        )


def test_transport_failures_charge_conservative_attempt_ceiling(tmp_path: Path):
    definition = _published(tmp_path)
    manifest = _bound_manifest(tmp_path, definition)
    arm = manifest.document["arm"]
    gate = {
        "admitted": True,
        "definition_sha256": definition.raw_sha256,
        "run_manifest_sha256": manifest.raw_sha256,
        "route_runtime_identities": {
            route_id: route["runtime_identity"] for route_id, route in arm["routes"].items()
        },
        "endpoint_bindings_sha256": ZERO,
        "supervision_receipt_sha256": ONE,
        "resource_guard_sha256": ZERO,
    }

    def failed(_request: InvocationRequest) -> InvocationResult:
        raise RuntimeError("transport failed without a lower-level attempt receipt")

    run_dir = tmp_path / "failed-run"
    run = run_arm(
        definition,
        manifest,
        output_dir=run_dir,
        execution_gate=gate,
        absolute_deadline_monotonic=time.monotonic() + 60,
        cancel_event=_NeverCancel(),
        invoke=failed,
    )
    assert run["summary"]["model_calls"] == 29
    assert run["summary"]["model_calls_semantics"] == "conservative_upper_bound_where_transport_failed"
    assert all(row["cell_status"] == "transport_error" for row in run["outcomes"])
    assert replay_run(definition, manifest, run_dir=run_dir)["verified"] is True


def test_wrapped_timeouts_remain_timeouts_with_exact_attempt_ledger(tmp_path: Path):
    definition = _published(tmp_path)
    manifest = _bound_manifest(tmp_path, definition)
    arm = manifest.document["arm"]
    gate = {
        "admitted": True,
        "definition_sha256": definition.raw_sha256,
        "run_manifest_sha256": manifest.raw_sha256,
        "route_runtime_identities": {
            route_id: route["runtime_identity"] for route_id, route in arm["routes"].items()
        },
        "endpoint_bindings_sha256": ZERO,
        "supervision_receipt_sha256": ONE,
        "resource_guard_sha256": ZERO,
    }

    def timed_out(_request: InvocationRequest) -> InvocationResult:
        cause = TimeoutError("endpoint deadline")
        try:
            raise cause
        except TimeoutError as exc:
            raise InvocationFailure(
                "wrapped endpoint deadline", attempt_count=1, timed_out=True
            ) from exc

    run_dir = tmp_path / "timeout-run"
    run = run_arm(
        definition,
        manifest,
        output_dir=run_dir,
        execution_gate=gate,
        absolute_deadline_monotonic=time.monotonic() + 60,
        cancel_event=_NeverCancel(),
        invoke=timed_out,
    )
    assert run["summary"]["model_calls"] == 21
    assert run["summary"]["model_calls_semantics"] == "exact"
    assert all(row["cell_status"] == "timeout" for row in run["outcomes"])
    assert replay_run(definition, manifest, run_dir=run_dir)["verified"] is True


def test_unissued_arm_stays_visible_without_imputed_score(tmp_path: Path):
    definition = _published(tmp_path)
    manifest = _bound_manifest(tmp_path, definition)
    run_dir = tmp_path / "unissued-run"
    run = write_unissued_receipt(
        definition,
        manifest,
        output_dir=run_dir,
        reason="candidate runtime admission failed before any model request",
    )
    run_sha = hashlib.sha256((run_dir / "run.json").read_bytes()).hexdigest()
    projection = program_projection(definition, run_receipts=[(run, run_sha)])
    row = projection["runs"][0]
    assert row["observed_terminal_status"] == "unissued"
    assert row["admission_status"] == "not_evaluated"
    assert row["summary"] is None
    assert row["task_outcomes"] == []
    assert run["summary"]["model_calls"] == 0
    assert (run_dir / "definition.snapshot.json").read_bytes() == definition.path.read_bytes()
    assert (run_dir / "run-manifest.snapshot.json").read_bytes() == manifest.path.read_bytes()
