"""Offline tests for the bounded weekly inference-policy canary."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from bench.weekly_upgrade_eval import manifest as manifest_mod
from bench.weekly_upgrade_eval.manifest import ManifestError, load_manifest
from bench.weekly_upgrade_eval.runner import (
    InvocationRequest,
    InvocationResult,
    grade_task,
    invoke_via_wrapper,
    main,
    run_evaluation,
    validate_live_configuration,
    validate_output_dir,
)
from bench.weekly_upgrade_eval.stats import paired_bootstrap_ci, summarize_outcomes


@pytest.fixture
def manifest():
    return load_manifest()


def _successful_result(task) -> InvocationResult:
    expected = task.grader["expected"]
    if task.grader["kind"] == "tool_semantics":
        completion = json.dumps(expected["answer"], sort_keys=True)
        tool_calls = ({
            "name": expected["tool_name"],
            "arguments": expected["arguments"],
        },)
    else:
        completion = json.dumps(expected, sort_keys=True)
        tool_calls = ()
    return InvocationResult(
        completion=completion,
        records=({
            "usage": {"input_tokens": 25, "output_tokens": 10},
            "model": "offline-test-model",
            "model_version": "offline/test",
            "backend": "offline",
        },),
        tool_calls=tool_calls,
        runtime_provenance={"model": "offline-test-model"},
    )


def test_bundled_manifest_is_frozen_balanced_and_ab_ba(manifest):
    assert manifest.schema_version == "weekly-upgrade-eval-manifest/v1"
    assert len(manifest.tasks) == 12
    assert len(manifest.raw_sha256) == len(manifest.configuration_sha256) == 64
    assert len({task.input_sha256 for task in manifest.tasks}) == 12
    # Expected answers are part of each grader hash, so no two task graders
    # can be silently exchanged merely because they use the same algorithm.
    assert len({task.grader_sha256 for task in manifest.tasks}) == 12
    critic_expected = [
        task.grader["expected"]["verdict"]
        for task in manifest.tasks
        if task.family == "critic"
    ]
    assert critic_expected.count("fatal_flaw") == 2
    assert critic_expected.count("proceed") == 2
    plan = manifest.plan_dict()
    assert plan["planned_invocations"] == 24
    assert plan["pair_order"][0]["order"] == ["A", "B"]
    assert plan["pair_order"][1]["order"] == ["B", "A"]
    assert [arm["seed"] for arm in plan["arms"]] == [0, 0]
    assert plan["notice"].startswith("Descriptive canary only")


def test_manifest_hash_changes_when_an_input_changes(tmp_path):
    original = json.loads(manifest_mod.DEFAULT_MANIFEST_PATH.read_text())
    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"
    first_path.write_text(json.dumps(original))
    original["tasks"][0]["prompt"] += " Material change."
    second_path.write_text(json.dumps(original))
    first = load_manifest(first_path)
    second = load_manifest(second_path)
    assert first.raw_sha256 != second.raw_sha256
    assert first.configuration_sha256 != second.configuration_sha256
    assert first.tasks[0].input_sha256 != second.tasks[0].input_sha256
    assert first.tasks[0].grader_sha256 == second.tasks[0].grader_sha256


def test_manifest_refuses_duplicate_task_id(tmp_path):
    doc = json.loads(manifest_mod.DEFAULT_MANIFEST_PATH.read_text())
    doc["tasks"][1]["id"] = doc["tasks"][0]["id"]
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(doc))
    with pytest.raises(ManifestError, match="task ids must be unique"):
        load_manifest(path)


def test_manifest_refuses_broken_grader_before_any_invocation(tmp_path):
    doc = json.loads(manifest_mod.DEFAULT_MANIFEST_PATH.read_text())
    doc["tasks"][0]["grader"]["expected"]["plausible_but_wrong_field"] = 1.5
    path = tmp_path / "bad-grader.json"
    path.write_text(json.dumps(doc))
    with pytest.raises(ManifestError, match="expected fields must be exactly"):
        load_manifest(path)


def test_arm_seed_is_backward_compatible_and_hashed(tmp_path):
    doc = json.loads(manifest_mod.DEFAULT_MANIFEST_PATH.read_text())
    with_seed = tmp_path / "with-seed.json"
    with_seed.write_text(json.dumps(doc))
    for arm in doc["arms"]:
        arm.pop("seed")
    legacy = tmp_path / "legacy-no-seed.json"
    legacy.write_text(json.dumps(doc))

    seeded_manifest = load_manifest(with_seed)
    legacy_manifest = load_manifest(legacy)
    assert [arm.seed for arm in seeded_manifest.arms] == [0, 0]
    assert [arm.seed for arm in legacy_manifest.arms] == [None, None]
    assert legacy_manifest.plan_dict()["arms"][0]["seed"] is None
    assert seeded_manifest.configuration_sha256 != legacy_manifest.configuration_sha256


@pytest.mark.parametrize("bad_seed", [True, False, 2 ** 63, -(2 ** 63) - 1])
def test_arm_seed_rejects_bool_and_values_outside_int64(tmp_path, bad_seed):
    doc = json.loads(manifest_mod.DEFAULT_MANIFEST_PATH.read_text())
    doc["arms"][0]["seed"] = bad_seed
    path = tmp_path / "bad-seed.json"
    path.write_text(json.dumps(doc))
    with pytest.raises(ManifestError, match="signed 64-bit"):
        load_manifest(path)


def test_bundled_live_profile_tuples_resolve_without_a_model_call(manifest):
    # This resolves only local Python policy data. It performs no HTTP request.
    validate_live_configuration(manifest)


def test_live_preflight_registers_backends_in_a_fresh_process():
    code = (
        "from bench.weekly_upgrade_eval.manifest import load_manifest; "
        "from bench.weekly_upgrade_eval.runner import validate_live_configuration; "
        "validate_live_configuration(load_manifest())"
    )
    env = dict(os.environ)
    env["MOCK_LLM"] = "1"
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0, proc.stderr


def test_plan_is_read_only_and_does_not_invoke(monkeypatch, tmp_path, capsys):
    output = tmp_path / "must-not-exist"

    def explode(_request):
        raise AssertionError("plan contacted transport")

    monkeypatch.setattr(
        "bench.weekly_upgrade_eval.runner.invoke_via_wrapper", explode
    )
    rc = main([
        "--plan", "--manifest", str(manifest_mod.DEFAULT_MANIFEST_PATH),
        "--output-dir", str(output),
    ])
    assert rc == 0
    assert not output.exists()
    rendered = json.loads(capsys.readouterr().out)
    assert rendered["task_count"] == 12


def test_live_cli_requires_explicit_output_and_budget():
    with pytest.raises(SystemExit) as exc:
        main(["--run", "--manifest", str(manifest_mod.DEFAULT_MANIFEST_PATH)])
    assert exc.value.code == 2


def test_live_cli_refuses_mock_before_writing(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("MOCK_LLM", "1")
    output = tmp_path / "must-not-exist"
    rc = main([
        "--run", "--manifest", str(manifest_mod.DEFAULT_MANIFEST_PATH),
        "--output-dir", str(output), "--runtime-budget-s", "30",
    ])
    assert rc == 2
    assert "REFUSE" in capsys.readouterr().err
    assert not output.exists()


def test_fresh_output_guard_rejects_live_artifact_roots(tmp_path):
    with pytest.raises(ValueError, match="live artifact root"):
        validate_output_dir(Path(__file__).resolve().parents[1] / "run_state" / "eval")
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(FileExistsError, match="fresh path"):
        validate_output_dir(existing)


def test_run_interleaves_arms_and_writes_complete_artifact(manifest, tmp_path):
    seen: list[tuple[str, str, float]] = []

    def invoke(request: InvocationRequest) -> InvocationResult:
        seen.append((request.task.id, request.arm.id, request.request_timeout_s))
        assert request.calls_log_path.parent == tmp_path / "run"
        assert request.worker_activity_path.parent == tmp_path / "run"
        return _successful_result(request.task)

    artifact = run_evaluation(
        manifest,
        output_dir=tmp_path / "run",
        runtime_budget_s=600,
        invoke=invoke,
    )
    assert artifact["status"] == "complete"
    assert [arm for _, arm, _ in seen[:6]] == ["A", "B", "B", "A", "A", "B"]
    assert len(seen) == 24
    assert artifact["summary"]["pair_counts"]["both_pass"] == 12
    assert artifact["summary"]["arms"]["A"]["failure_inclusive_pass_rate"] == 1.0
    assert artifact["promotion"]["authorized"] is False
    saved = json.loads((tmp_path / "run" / "run.json").read_text())
    assert saved["run_id"] == artifact["run_id"]
    assert (tmp_path / "run" / "manifest.snapshot.json").read_bytes() == (
        manifest.path.read_bytes()
    )


@pytest.mark.parametrize(
    ("task_id", "plausible_wrong"),
    [
        (
            "gt_zero_sum_2x2",
            {"row_mixture": [0.5, 0.5], "column_mixture": [0.25, 0.75], "value": 1.5},
        ),
        (
            "gt_external_regret",
            {"chosen_total": 0, "best_fixed_total": 4, "total_external_regret": 4, "average_external_regret": 1},
        ),
        (
            "gt_pd_tft_vs_alld",
            {"player1_actions": ["C", "D", "D", "D"], "player2_actions": ["D", "D", "D", "D"], "player1_total": 3, "player2_total": 7},
        ),
        (
            "critic_proceed_fixable",
            {"verdict": "fatal_flaw", "reason_code": "fixable_identification"},
        ),
        (
            "critic_fatal_dominance",
            {"verdict": "fatal_flaw", "reason_code": "theorem_consistent_testable"},
        ),
        (
            "evidence_abstention",
            {"answer_code": "increase", "citations": ["D1", "D2"]},
        ),
        (
            "evidence_thresholds",
            {"answer_code": "compatible", "citations": ["D1"]},
        ),
    ],
)
def test_objective_graders_reject_plausible_wrong_answers(
    manifest, task_id, plausible_wrong
):
    task = next(task for task in manifest.tasks if task.id == task_id)
    grade = grade_task(task, InvocationResult(completion=json.dumps(plausible_wrong)))
    assert grade.passed is False
    assert grade.reason


def test_all_frozen_reference_answers_pass(manifest):
    for task in manifest.tasks:
        result = _successful_result(task)
        assert grade_task(task, result).passed, task.id


def test_tool_grader_requires_call_name_arguments_and_grounded_answer(manifest):
    task = next(task for task in manifest.tasks if task.id == "tool_experiment_lookup")
    answer = json.dumps({"mean_cooperation": 0.37})
    no_call = grade_task(task, InvocationResult(completion=answer))
    wrong_tool = grade_task(task, InvocationResult(
        completion=answer,
        tool_calls=({"name": "lookup_paper", "arguments": {"paper_id": "exp-042"}},),
    ))
    wrong_argument = grade_task(task, InvocationResult(
        completion=answer,
        tool_calls=({"name": "lookup_experiment", "arguments": {"experiment_id": "exp-024"}},),
    ))
    assert not no_call.passed
    assert not wrong_tool.passed
    assert not wrong_argument.passed


def test_wrapper_adapter_passes_profile_timeout_and_local_paths(
    manifest, monkeypatch, tmp_path
):
    task = next(task for task in manifest.tasks if task.id == "tool_experiment_lookup")
    arm = manifest.arms[0]
    captured = {}

    def fake_tools(messages, tools, **kwargs):
        captured.update(kwargs)
        assert len(messages) == 2
        assert tools[0]["impl"](experiment_id="exp-042")["mean_cooperation"] == 0.37
        return [
            {
                "completion": json.dumps([{
                    "id": "tc-1", "type": "function",
                    "function": {
                        "name": "lookup_experiment",
                        "arguments": json.dumps({"experiment_id": "exp-042"}),
                    },
                }]),
                "usage": {"input_tokens": 10, "output_tokens": 5},
                "model": arm.model,
                "model_version": "test/runtime",
                "backend": arm.backend,
                "host_metadata": {"vllm_image_tag": "test"},
            },
            {
                "completion": json.dumps({"mean_cooperation": 0.37}),
                "usage": {"input_tokens": 20, "output_tokens": 5},
                "model": arm.model,
                "model_version": "test/runtime",
                "backend": arm.backend,
                "host_metadata": {"vllm_image_tag": "test"},
            },
        ]

    from agent_wrapper import worker_activity

    old_activity_path = tmp_path / "old-activity.jsonl"
    worker_activity.DEFAULT_LOG_PATH = old_activity_path
    run_ids = []
    monkeypatch.setattr("agent_wrapper.wrapper.call_with_tools", fake_tools)
    monkeypatch.setattr("agent_wrapper.wrapper.get_run_id", lambda: "prior-run")
    monkeypatch.setattr("agent_wrapper.wrapper.set_run_id", run_ids.append)
    request = InvocationRequest(
        run_id="run-test",
        task=task,
        arm=arm,
        request_timeout_s=17.5,
        calls_log_path=tmp_path / "calls.jsonl",
        worker_activity_path=tmp_path / "activity.jsonl",
    )
    result = invoke_via_wrapper(request)
    assert captured["profile"] == arm.profile
    assert captured["request_timeout_s"] == 17.5
    assert captured["log_path"] == str(tmp_path / "calls.jsonl")
    assert captured["max_depth"] == 2
    assert captured["seed"] == 0
    assert grade_task(task, result).passed
    assert run_ids == ["run-test", "prior-run"]
    assert worker_activity.DEFAULT_LOG_PATH == old_activity_path


def test_wrapper_adapter_omits_null_seed(manifest, monkeypatch, tmp_path):
    task = manifest.tasks[0]
    arm = replace(manifest.arms[0], seed=None)
    captured = {}

    def fake_sync(_messages, **kwargs):
        captured.update(kwargs)
        return {
            "completion": json.dumps(task.grader["expected"]),
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "model": arm.model,
            "model_version": "test/runtime",
            "backend": arm.backend,
            "host_metadata": {"vllm_image_tag": "test"},
        }

    monkeypatch.setattr("agent_wrapper.wrapper.call_sync", fake_sync)
    monkeypatch.setattr("agent_wrapper.wrapper.set_run_id", lambda _run_id: None)
    invoke_via_wrapper(InvocationRequest(
        run_id="run-test",
        task=task,
        arm=arm,
        request_timeout_s=10,
        calls_log_path=tmp_path / "calls.jsonl",
        worker_activity_path=tmp_path / "activity.jsonl",
    ))
    assert "seed" not in captured


def test_wrapper_adapter_refuses_model_identity_drift(manifest, monkeypatch, tmp_path):
    task = manifest.tasks[0]
    arm = manifest.arms[0]

    def fake_sync(_messages, **_kwargs):
        return {
            "completion": json.dumps(task.grader["expected"]),
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "model": "unexpected-model",
            "model_version": "test/runtime",
            "backend": arm.backend,
            "host_metadata": {"vllm_image_tag": "test"},
        }

    monkeypatch.setattr("agent_wrapper.wrapper.call_sync", fake_sync)
    monkeypatch.setattr("agent_wrapper.wrapper.set_run_id", lambda _run_id: None)
    request = InvocationRequest(
        run_id="run-test",
        task=task,
        arm=arm,
        request_timeout_s=10,
        calls_log_path=tmp_path / "calls.jsonl",
        worker_activity_path=tmp_path / "activity.jsonl",
    )
    with pytest.raises(RuntimeError, match="does not match frozen arm"):
        invoke_via_wrapper(request)


def test_timeout_is_failure_and_makes_run_incomplete(manifest, tmp_path):
    first_task = manifest.tasks[0].id

    def invoke(request):
        if request.task.id == first_task and request.arm.id == "A":
            raise TimeoutError("bounded transport deadline")
        return _successful_result(request.task)

    artifact = run_evaluation(
        manifest,
        output_dir=tmp_path / "timeout",
        runtime_budget_s=600,
        invoke=invoke,
    )
    outcome = next(
        item for item in artifact["outcomes"]
        if item["task_id"] == first_task and item["arm_id"] == "A"
    )
    assert outcome["status"] == "timeout"
    assert outcome["grade"]["passed"] is False
    assert artifact["status"] == "incomplete_transport"
    assert artifact["summary"]["arms"]["A"]["planned"] == 12
    assert artifact["summary"]["arms"]["A"]["passed"] == 11


class StepClock:
    def __init__(self):
        self.value = -1.0

    def __call__(self):
        self.value += 1.0
        return self.value


def test_global_budget_stops_new_calls_and_marks_every_skipped_cell(manifest, tmp_path):
    calls = []

    def invoke(request):
        calls.append((request.task.id, request.arm.id))
        return _successful_result(request.task)

    artifact = run_evaluation(
        manifest,
        output_dir=tmp_path / "budget",
        runtime_budget_s=10,
        invoke=invoke,
        monotonic=StepClock(),
    )
    assert 0 < len(calls) < 24
    assert artifact["status"] == "incomplete_budget"
    statuses = [outcome["status"] for outcome in artifact["outcomes"]]
    assert "not_run_budget" in statuses
    assert len(statuses) == 24
    assert artifact["summary"]["planned_arm_task_outcomes"] == 24
    assert artifact["summary"]["pair_counts"]["incomplete_pair"] > 0


def test_bootstrap_and_failure_inclusive_ctt_are_deterministic():
    one = paired_bootstrap_ci([1, 0, -1, 1], samples=500, seed=7)
    two = paired_bootstrap_ci([1, 0, -1, 1], samples=500, seed=7)
    assert one == two
    outcomes = [
        {"task_id": "t1", "arm_id": "A", "status": "passed", "duration_s": 1},
        {"task_id": "t1", "arm_id": "B", "status": "failed", "duration_s": 2},
        {"task_id": "t2", "arm_id": "A", "status": "error", "duration_s": 3},
        {"task_id": "t2", "arm_id": "B", "status": "passed", "duration_s": 4},
    ]
    summary = summarize_outcomes(
        outcomes,
        task_ids=["t1", "t2"],
        task_families={"t1": "x", "t2": "x"},
        arm_ids=("A", "B"),
        elapsed_s=10,
        bootstrap_samples=500,
        bootstrap_seed=7,
    )
    assert summary["arms"]["A"]["failure_inclusive_pass_rate"] == 0.5
    assert summary["arms"]["B"]["failure_inclusive_pass_rate"] == 0.5
    assert summary["pair_counts"]["incomplete_pair"] == 1
    ctt = summary["failure_inclusive_correct_task_throughput"]
    assert ctt["successful_arm_tasks"] == 2
    assert ctt["elapsed_wall_s_including_failures"] == 10
    assert ctt["successful_arm_tasks_per_wall_hour"] == 720.0
