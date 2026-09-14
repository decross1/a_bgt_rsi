"""Repeat aggregation tests built from the objective runner's real artifact shape."""
from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from agent_wrapper.generation_policy import resolve_generation_policy
from bench.weekly_upgrade_eval import repeats
from bench.weekly_upgrade_eval.manifest import load_manifest, sha256_json
from bench.weekly_upgrade_eval.repeats import (
    RepeatValidationError,
    load_and_summarize,
    main,
)
from bench.weekly_upgrade_eval.runner import (
    InvocationResult,
    grade_task,
    run_evaluation,
)
from orchestrator import weekly_upgrade_trial as trial

REPO_ROOT = Path(__file__).resolve().parent.parent
PILOT_ROOT = REPO_ROOT / "experiments" / "weekly_qwen_effort_pilot_2026-09-14"
PILOT_MANIFESTS = tuple(PILOT_ROOT / f"seed_{seed}.json" for seed in (17, 29, 43))
PassRule = Callable[[int, str, str], bool]


@pytest.fixture
def simulated_controller_evidence(monkeypatch):
    """Explicitly isolate decision-math tests from real dispatcher evidence."""
    monkeypatch.setattr(
        repeats,
        "_load_controller_evidence",
        lambda _path, _artifact_sha256: b"synthetic-controller-evidence",
    )


class _StepClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        self.value += 1.0
        return self.value


def _correct_result(request) -> InvocationResult:
    expected = request.task.grader["expected"]
    tool_calls = ()
    if request.task.grader["kind"] == "tool_semantics":
        payload = expected["answer"]
        tool_calls = ({
            "name": expected["tool_name"],
            "arguments": expected["arguments"],
        },)
    else:
        payload = expected
    resolved = resolve_generation_policy(
        profile=request.arm.profile,
        backend_name=request.arm.backend,
        model_name=request.arm.model,
        seed=request.arm.seed,
    )
    provenance = {
        "backend": request.arm.backend,
        "model": request.arm.model,
        "model_version": "test-runtime",
        "temperature": resolved.logged_params["temperature"],
        "top_p": resolved.logged_params["top_p"],
        "profile": request.arm.profile,
        "max_tokens": request.arm.max_tokens,
        "seed": request.arm.seed,
        "host_metadata": {"fixture": True},
        "reasoning_effort": resolved.reasoning_effort,
        "sampling_extra": dict(resolved.sampling_extra),
        "finish_reason": "stop",
        "reasoning_chars": 0,
    }
    completion = json.dumps(payload)
    return InvocationResult(
        completion=completion,
        records=({
            **provenance,
            "completion": completion,
            "usage": {"input_tokens": 10, "output_tokens": 5},
        },),
        tool_calls=tool_calls,
        runtime_provenance=provenance,
    )


def _make_runs(
    tmp_path: Path,
    pass_rule: PassRule | None = None,
    *,
    label: str = "runs",
    live_transport: bool = False,
) -> list[Path]:
    rule = pass_rule or (lambda _seed, _task, _arm: True)
    paths: list[Path] = []
    for manifest_path in PILOT_MANIFESTS:
        manifest = load_manifest(manifest_path)
        seed = manifest.arms[0].seed

        def invoke(request, *, _seed=seed):
            if rule(_seed, request.task.id, request.arm.id):
                return _correct_result(request)
            result = _correct_result(request)
            return InvocationResult(
                completion="{}",
                records=result.records,
                runtime_provenance=result.runtime_provenance,
            )

        if live_transport:
            invoke.__qualname__ = "invoke_via_wrapper"

        output = tmp_path / label / f"seed-{seed}"
        run_evaluation(
            manifest,
            output_dir=output,
            runtime_budget_s=2_220,
            invoke=invoke,
            monotonic=_StepClock(),
        )
        paths.append(output / "run.json")
    return paths


def _rewrite(path: Path, edit) -> None:
    document = json.loads(path.read_text())
    edit(document)
    path.write_text(json.dumps(document, sort_keys=True) + "\n")


def test_complete_three_seed_summary_has_task_level_rsr_ctt_and_clustered_bootstrap(
    tmp_path: Path, simulated_controller_evidence,
):
    runs = _make_runs(tmp_path, live_transport=True)
    summary = load_and_summarize(runs, bootstrap_samples=500)

    assert summary["validation_status"] == "VALID"
    assert summary["decision"] == "NO_MATERIAL_SIGNAL"
    assert summary["supports_gain"] is False
    assert summary["planned_outcome_count"] == 36
    assert summary["seeds"] == [17, 29, 43]
    assert summary["rsr_2of3"]["arms"]["A"]["solved_task_count"] == 6
    assert summary["rsr_2of3"]["arms"]["B"]["solved_task_count"] == 6
    assert summary["rsr_2of3"]["arms"]["A"]["all_three_success_task_count"] == 6
    assert summary["rsr_2of3"]["arms"]["A"]["success_count_distribution"] == {
        "0": 0, "1": 0, "2": 0, "3": 6,
    }
    # The six task templates, rather than 18 seeded attempts, are resampled.
    bootstrap = summary["task_clustered_paired_bootstrap"]
    assert bootstrap["n_task_templates"] == 6
    assert bootstrap["mean_delta"] == 0
    assert summary["arms"]["A"]["summed_arm_wall_s_including_failures"] == 18
    assert summary["arms"]["B"]["summed_arm_wall_s_including_failures"] == 18
    assert summary["failure_inclusive_correct_task_throughput"] == {
        "successful_arm_tasks": 36,
        "summed_all_arm_wall_s": 36.0,
        "successful_tasks_per_summed_arm_hour": 3600.0,
    }
    assert summary["arms"]["A"]["protocol_metrics"] == {
        "failure_code_counts": {},
        "parse_failures": 0,
        "semantic_tool_failures": 0,
        "empty_at_cap": 0,
        "finish_reason_counts": {"stop": 18},
        "input_tokens": 180,
        "output_tokens": 90,
        "reasoning_chars": 0,
        "reasoning_chars_observed_cells": 18,
        "reasoning_tokens": None,
        "reasoning_tokens_observed_cells": 0,
    }


def test_locked_rule_evaluates_larger_for_two_extra_successes_without_rsr_regression(
    tmp_path: Path, simulated_controller_evidence,
):
    a_failures = {
        (17, "critic_fatal_circular", "A"),
        (29, "critic_proceed_fixable", "A"),
    }
    runs = _make_runs(
        tmp_path,
        lambda seed, task, arm: (seed, task, arm) not in a_failures,
        live_transport=True,
    )
    summary = load_and_summarize(runs, bootstrap_samples=300)

    assert summary["arms"]["A"]["passed"] == 16
    assert summary["arms"]["B"]["passed"] == 18
    assert summary["rsr_2of3"]["arms"]["A"]["solved_task_count"] == 6
    assert summary["semantic_tool_failures"] == {"A": 0, "B": 0}
    assert summary["decision"] == "EVALUATE_LARGER"
    assert summary["supports_gain"] is True


def test_locked_rule_can_trigger_on_ctt_and_retain_on_success_regression(
    tmp_path: Path, simulated_controller_evidence,
):
    runs = _make_runs(tmp_path, label="ctt", live_transport=True)
    for path in runs:
        _rewrite(
            path,
            lambda doc: [
                row.update({"duration_s": 0.5})
                for row in doc["outcomes"]
                if row["arm_id"] == "B"
            ],
        )
    ctt = load_and_summarize(runs, bootstrap_samples=200)
    assert ctt["arms"]["B"]["correct_task_throughput_per_hour"] == 7200
    assert ctt["decision"] == "EVALUATE_LARGER"
    assert ctt["decision_reasons"] == ["CTT improved by at least 15%"]

    b_failure = {(17, "critic_fatal_circular", "B")}
    worse_runs = _make_runs(
        tmp_path,
        lambda seed, task, arm: (seed, task, arm) not in b_failure,
        label="worse",
        live_transport=True,
    )
    worse = load_and_summarize(worse_runs, bootstrap_samples=200)
    assert worse["decision"] == "RETAIN_INCUMBENT"
    assert worse["supports_gain"] is False


@pytest.mark.parametrize(
    ("a_failures", "b_failures", "expected_reason"),
    [
        (
            {(17, "critic_fatal_circular", "A"), (29, "critic_proceed_fixable", "A")},
            {(17, "critic_fatal_circular", "B"), (29, "critic_fatal_circular", "B")},
            "candidate has lower RSR_2of3",
        ),
        (
            {(17, "critic_fatal_circular", "A")},
            {(17, "tool_experiment_lookup", "B")},
            "candidate has more semantic tool failures",
        ),
    ],
)
def test_locked_rule_retains_on_rsr_or_tool_regression(
    tmp_path: Path,
    simulated_controller_evidence,
    a_failures: set[tuple[int, str, str]],
    b_failures: set[tuple[int, str, str]],
    expected_reason: str,
):
    failures = a_failures | b_failures
    runs = _make_runs(
        tmp_path,
        lambda seed, task, arm: (seed, task, arm) not in failures,
        label=expected_reason.replace(" ", "-"),
        live_transport=True,
    )
    summary = load_and_summarize(runs, bootstrap_samples=200)
    assert summary["decision"] == "RETAIN_INCUMBENT"
    assert expected_reason in summary["decision_reasons"]


def test_timeout_is_failure_inclusive_but_forces_incomplete_no_gain(tmp_path: Path):
    a_failures = {
        (17, "critic_fatal_circular", "A"),
        (29, "critic_proceed_fixable", "A"),
    }
    runs = _make_runs(
        tmp_path,
        lambda seed, task, arm: (seed, task, arm) not in a_failures,
        label="incomplete",
    )

    def timeout_one(document):
        row = next(
            item
            for item in document["outcomes"]
            if item["task_id"] == "critic_fatal_dominance" and item["arm_id"] == "A"
        )
        row.update({
            "status": "timeout",
            "grade": {"passed": False, "reason": "fixture timeout", "details": {}},
            "runtime_provenance": {},
            "runtime_provenance_sha256": None,
        })
        document["status"] = "incomplete_transport"

    _rewrite(runs[0], timeout_one)
    summary = load_and_summarize(runs, bootstrap_samples=200)
    assert summary["validation_status"] == "INCOMPLETE"
    assert summary["arms"]["A"]["status_counts"]["timeout"] == 1
    assert summary["decision"] == "INCOMPLETE"
    assert summary["supports_gain"] is False


def test_missing_duplicate_or_configuration_drift_is_structurally_invalid(tmp_path: Path):
    runs = _make_runs(tmp_path, label="missing")
    _rewrite(runs[0], lambda doc: doc["outcomes"].pop())
    with pytest.raises(RepeatValidationError, match="missing outcome"):
        load_and_summarize(runs)

    duplicate_runs = _make_runs(tmp_path, label="duplicate")
    copied = tmp_path / "duplicate-copy"
    shutil.copytree(duplicate_runs[0].parent, copied)
    copied_run = copied / "run.json"
    _rewrite(copied_run, lambda doc: doc.update({"run_id": doc["run_id"] + "-copy"}))
    with pytest.raises(RepeatValidationError, match="duplicate repeat seed"):
        load_and_summarize([duplicate_runs[0], copied_run])

    drift_runs = _make_runs(tmp_path, label="drift")
    _rewrite(
        drift_runs[1],
        lambda doc: doc["provenance"]["arms"][0].update({"max_tokens": 6_143}),
    )
    with pytest.raises(RepeatValidationError, match="embedded arm configuration"):
        load_and_summarize(drift_runs)

    deadline_runs = _make_runs(tmp_path, label="deadline-drift")
    _rewrite(
        deadline_runs[2],
        lambda doc: doc["outcomes"][0].update({"request_timeout_s": 181}),
    )
    with pytest.raises(RepeatValidationError, match="deadline exceeds"):
        load_and_summarize(deadline_runs)


def test_duplicate_run_id_and_partial_json_are_invalid(tmp_path: Path):
    runs = _make_runs(tmp_path, label="duplicate-id")
    with pytest.raises(RepeatValidationError, match="duplicate run_id"):
        load_and_summarize([runs[0], runs[0]])

    partial = tmp_path / "partial" / "run.json"
    partial.parent.mkdir()
    partial.write_text('{"schema_version":')
    with pytest.raises(RepeatValidationError, match="invalid JSON"):
        load_and_summarize([partial])


def test_seeded_task_bootstrap_is_reproducible(tmp_path: Path):
    failures = {
        (17, "critic_fatal_circular", "A"),
        (29, "critic_proceed_fixable", "A"),
        (43, "evidence_attrition", "B"),
    }
    runs = _make_runs(
        tmp_path,
        lambda seed, task, arm: (seed, task, arm) not in failures,
        label="bootstrap",
    )
    first = load_and_summarize(runs, bootstrap_samples=777)
    second = load_and_summarize(list(reversed(runs)), bootstrap_samples=777)
    assert first["task_clustered_paired_bootstrap"] == second[
        "task_clustered_paired_bootstrap"
    ]
    assert first["task_clustered_paired_bootstrap"]["n_task_templates"] == 6


def test_injected_transport_can_never_support_locked_pilot_gain(
    tmp_path: Path, simulated_controller_evidence
):
    a_failures = {
        (17, "critic_fatal_circular", "A"),
        (29, "critic_proceed_fixable", "A"),
    }
    runs = _make_runs(
        tmp_path,
        lambda seed, task, arm: (seed, task, arm) not in a_failures,
        label="synthetic",
    )

    summary = load_and_summarize(runs, bootstrap_samples=200)

    assert summary["arms"]["B"]["passed"] > summary["arms"]["A"]["passed"]
    assert summary["decision"] == "NOT_APPLICABLE"
    assert summary["supports_gain"] is False


def test_missing_controller_evidence_can_never_support_locked_pilot_gain(
    tmp_path: Path,
):
    a_failures = {
        (17, "critic_fatal_circular", "A"),
        (29, "critic_proceed_fixable", "A"),
    }
    runs = _make_runs(
        tmp_path,
        lambda seed, task, arm: (seed, task, arm) not in a_failures,
        label="no-controller",
        live_transport=True,
    )
    summary = load_and_summarize(runs, bootstrap_samples=200)
    assert summary["decision"] == "NOT_APPLICABLE"
    assert summary["supports_gain"] is False
    assert all(
        row["controller_verified"] is False for row in summary["provenance"]["runs"]
    )


@pytest.mark.parametrize("evaluation_status", ["complete", "incomplete_transport", "incomplete_budget"])
def test_controller_evidence_binds_result_budget_runtime_and_dependencies(
    tmp_path: Path, monkeypatch, evaluation_status: str,
):
    source = _make_runs(tmp_path, label="controller-source")[0]
    output = tmp_path / "controller"
    evaluation = output / "evaluation"
    shutil.copytree(source.parent, evaluation)
    run_path = evaluation / "run.json"
    artifact = json.loads(run_path.read_text())
    artifact_sha256 = hashlib.sha256(run_path.read_bytes()).hexdigest()
    manifest_sha256 = artifact["provenance"]["manifest_sha256"]
    plan = {
        "kind": "objective",
        "trial_id": "2026-W38-controller-test",
        "manifest_sha256": manifest_sha256,
        "production_change_authorized": False,
        "execution_dependencies": {"runner.py": "a" * 64},
    }
    terminal_status = "completed" if evaluation_status == "complete" else "failed"
    returncode = 0 if evaluation_status == "complete" else 3
    receipt = {
        "path": str(run_path),
        "sha256": artifact_sha256,
        "artifact_sha256": {
            "run.json": artifact_sha256,
            "manifest.snapshot.json": manifest_sha256,
        },
        "status": evaluation_status,
        "execution_complete": evaluation_status == "complete",
        "semantic_benefit_measured": False,
    }
    budget = {
        "run_id": plan["trial_id"],
        "manifest_sha256": trial._sha({
            "plan": plan,
            "output": str(output.resolve()),
        }),
        "state": "finished",
        "status": terminal_status,
    }
    result = {
        "status": terminal_status,
        "error": None,
        "trial_id": plan["trial_id"],
        "plan_sha256": trial._sha(plan),
        "evaluation_dir": str(evaluation),
        "evaluation": receipt,
        "semantic_benefit_measured": False,
        "production_change_authorized": False,
        "process": {"returncode": returncode},
        "budget_receipt": budget,
    }
    runtime_identity = [{"container_id": "fixed", "image_id": "sha256:fixed"}]
    for name, value in {
        "trial_plan.json": plan,
        "trial_result.json": result,
        "preflight.json": {"runtime_identity": runtime_identity},
        "postflight.json": {"runtime_identity": runtime_identity},
    }.items():
        (output / name).write_text(json.dumps(value) + "\n")
    canonical_root = tmp_path / "canonical"
    state_path = (
        canonical_root / "run_state" / "weekly_upgrade" / "trials"
        / f"{plan['trial_id']}.json"
    )
    state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps({
        "phase": "finished",
        "plan": plan,
        "output": str(output.resolve()),
        "binding_sha256": budget["manifest_sha256"],
        "result": result,
    }) + "\n")
    ledger_path = canonical_root / "run_state" / "weekly_upgrade_budget.jsonl"
    ledger_path.write_text("canonical-ledger-placeholder\n")

    class _Ledger:
        def __init__(self, path):
            assert path == ledger_path

        def existing(self, run_id):
            assert run_id == plan["trial_id"]
            return budget

    monkeypatch.setattr(trial, "evaluation_receipt", lambda _plan, _output: receipt)
    monkeypatch.setattr(trial, "canonical_root", lambda _root: canonical_root)
    monkeypatch.setattr(trial, "BudgetLedger", _Ledger)

    observed = repeats._load_controller_evidence(run_path, artifact_sha256)

    assert observed == repeats.canonical_json({
        "execution_dependencies": plan["execution_dependencies"],
        "runtime_identity": runtime_identity,
    })

    # A controller interruption or crash is not an ordinary failed task.
    for bad in (
        {"status": "interrupted"},
        {"process": {"returncode": 124}},
        {"error": "serving runtime drift"},
        {"status": "failed" if terminal_status == "completed" else "completed"},
    ):
        (output / "trial_result.json").write_text(json.dumps({**result, **bad}) + "\n")
        with pytest.raises(RepeatValidationError, match="terminal result"):
            repeats._load_controller_evidence(run_path, artifact_sha256)


@pytest.mark.parametrize(
    ("edit_runtime", "message"),
    [
        (lambda runtime: runtime.pop("reasoning_effort"), "runtime provenance is missing"),
        (
            lambda runtime: runtime.update({"reasoning_effort": "xhigh"}),
            "reasoning_effort drift",
        ),
        (lambda runtime: runtime.update({"temperature": 0.7}), "temperature drift"),
    ],
)
def test_missing_or_drifted_effective_policy_is_invalid(
    tmp_path: Path, edit_runtime, message: str,
):
    runs = _make_runs(tmp_path, label=message.replace(" ", "-"))

    def edit(document):
        row = next(item for item in document["outcomes"] if item["arm_id"] == "B")
        edit_runtime(row["runtime_provenance"])
        row["runtime_provenance_sha256"] = sha256_json(row["runtime_provenance"])

    _rewrite(runs[0], edit)
    with pytest.raises(RepeatValidationError, match=message):
        load_and_summarize(runs)


def test_runtime_identity_drift_across_repeats_is_invalid(tmp_path: Path):
    runs = _make_runs(tmp_path, label="runtime-drift")

    def edit(document):
        for row in document["outcomes"]:
            row["runtime_provenance"]["model_version"] = "different-runtime"
            row["runtime_provenance_sha256"] = sha256_json(
                row["runtime_provenance"]
            )

    _rewrite(runs[1], edit)
    with pytest.raises(RepeatValidationError, match="environment drift"):
        load_and_summarize(runs)


def test_objective_regrade_rejects_edited_status_and_grade(tmp_path: Path):
    failed = {(17, "critic_fatal_circular", "A")}
    runs = _make_runs(
        tmp_path,
        lambda seed, task, arm: (seed, task, arm) not in failed,
        label="regrade",
    )

    def edit(document):
        row = next(
            item for item in document["outcomes"]
            if item["task_id"] == "critic_fatal_circular" and item["arm_id"] == "A"
        )
        row["status"] = "passed"
        row["failure_code"] = None
        row["grade"] = {"passed": True, "reason": "edited", "details": {}}

    _rewrite(runs[0], edit)
    with pytest.raises(
        RepeatValidationError, match="derived failure code differs|objective regrade differs"
    ):
        load_and_summarize(runs)


def test_execution_order_drift_is_invalid(tmp_path: Path):
    runs = _make_runs(tmp_path, label="order-drift")
    _rewrite(
        runs[0],
        lambda document: document["execution_order"].__setitem__(
            slice(0, 2), list(reversed(document["execution_order"][:2]))
        ),
    )
    with pytest.raises(RepeatValidationError, match="execution indices"):
        load_and_summarize(runs)


def test_global_budget_may_reduce_a_request_deadline_below_arm_cap(tmp_path: Path):
    runs = _make_runs(tmp_path, label="reduced-deadline", live_transport=True)

    def edit(document):
        execution = document["execution_order"][-1]
        execution["request_timeout_s"] = 179
        outcome = next(
            row for row in document["outcomes"]
            if (row["task_id"], row["arm_id"])
            == (execution["task_id"], execution["arm_id"])
        )
        outcome["request_timeout_s"] = 179

    _rewrite(runs[0], edit)
    summary = load_and_summarize(runs, bootstrap_samples=200)
    assert summary["validation_status"] == "VALID"


def test_non_preregistered_payload_budget_cannot_support_gain(
    tmp_path: Path, simulated_controller_evidence,
):
    a_failures = {
        (17, "critic_fatal_circular", "A"),
        (29, "critic_proceed_fixable", "A"),
    }
    runs = _make_runs(
        tmp_path,
        lambda seed, task, arm: (seed, task, arm) not in a_failures,
        label="budget-drift",
        live_transport=True,
    )

    def edit(document):
        config = document["provenance"]["run_configuration"]
        config["runtime_budget_s"] = 2_219
        document["provenance"]["run_configuration_sha256"] = sha256_json(config)

    for run in runs:
        _rewrite(run, edit)
    summary = load_and_summarize(runs, bootstrap_samples=200)
    assert summary["decision"] == "NOT_APPLICABLE"
    assert summary["supports_gain"] is False


def test_cli_writes_fresh_hash_only_summary_and_never_raw_completions(
    tmp_path: Path, capsys,
):
    runs = _make_runs(tmp_path, label="cli")
    secret = "RAW-COMPLETION-MUST-NOT-BE-PUBLISHED"

    def add_failed_raw_completion(document):
        row = document["outcomes"][0]
        task = load_manifest(PILOT_MANIFESTS[0]).tasks[0]
        grade = grade_task(task, InvocationResult(completion=secret))
        row.update({
            "completion": secret,
            "status": "failed",
            "failure_code": "parse_failure",
            "grade": {
                "passed": grade.passed,
                "reason": grade.reason,
                "details": grade.details,
            },
        })

    _rewrite(runs[0], add_failed_raw_completion)
    output = tmp_path / "summary" / "repeats.json"
    args = ["--runs", *(str(path) for path in runs), "--output", str(output)]

    assert main(args) == 0
    rendered = output.read_text()
    assert secret not in rendered
    assert '"completion"' not in rendered
    assert json.loads(rendered)["provenance"]["runs"][0]["run_artifact_sha256"]
    assert main(args) == 2
    error = capsys.readouterr().err
    assert '"validation_status":"INVALID"' in error
