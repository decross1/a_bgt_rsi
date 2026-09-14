"""Fresh-task and strict-protocol contracts for diversity scaffold v1."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone

import pytest

from bench.weekly_upgrade_diversity import runner
from bench.weekly_upgrade_diversity.graders import grade_proposal
from bench.weekly_upgrade_diversity.manifest import (
    DEFAULT_MANIFEST,
    SCAFFOLD_V1_TASK_IDS,
    V1_MANIFEST,
    _candidate_space,
    load_manifest,
    plan_dict,
    sha256_json,
)
from bench.weekly_upgrade_eval.structured_output import (
    FIELD_SCHEMA,
    MARKDOWN_ENVELOPE,
    REASONING_CHANNEL_LEAKAGE,
)
from orchestrator.weekly_upgrade_trial import TrialError
from tests.test_weekly_upgrade_diversity_receipt import _validate


def _valid_proposals(task):
    return [
        proposal
        for proposal in _candidate_space(task)
        if grade_proposal(task, proposal).valid
    ]


def _transport(manifest, *, override=None):
    by_problem = {task["problem"]: task for task in manifest["tasks"]}

    def invoke(messages, **kwargs):
        user = messages[-1]["content"]
        task = next(task for problem, task in by_problem.items() if problem in user)
        valid = _valid_proposals(task)
        if kwargs["profile"] == "explore":
            index = {101: 0, 211: 1, 307: 2}[kwargs["seed"]] % len(valid)
            completion = json.dumps({"proposal": valid[index]})
            role = "generate"
        elif "Candidate slots:" in user:
            packet = user.split("Candidate slots: ", 1)[1].split("\nCheck each", 1)[0]
            proposals = [row["proposal"] for row in json.loads(packet)]
            selected = next(
                (
                    index
                    for index, proposal in enumerate(proposals)
                    if grade_proposal(task, proposal).valid
                ),
                None,
            )
            completion = json.dumps({"selected_slot": selected})
            role = "validate"
        else:
            proposals = [valid[index % len(valid)] for index in range(3)]
            completion = json.dumps(
                {"proposals": proposals, "selected_index": 0}
            )
            role = "control"
        if override is not None:
            completion = override(
                task=task,
                seed=kwargs["seed"],
                role=role,
                completion=completion,
            )
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "request_id": str(uuid.uuid4()),
            "model": kwargs["model"],
            "model_version": "stub-gemma-content-sha256:v1",
            "backend": kwargs["backend"],
            "host_metadata": {"host": "test"},
            "profile": kwargs["profile"],
            "temperature": 0.0 if kwargs["profile"] == "deterministic" else 1.0,
            "top_p": 1.0 if kwargs["profile"] == "deterministic" else 0.95,
            "seed": kwargs["seed"],
            "reasoning_effort": None,
            "sampling_extra": {},
            "max_tokens": kwargs["max_tokens"],
            "prompt_messages": messages,
            "completion": completion,
            "usage": {"input_tokens": 20, "output_tokens": 10},
            "latency_ms": 1,
            "caller_tag": kwargs["caller_tag"],
            "parent_request_id": kwargs["parent_request_id"],
            "finish_reason": "stop",
            "reasoning_chars": None,
        }
        with open(kwargs["log_path"], "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
        return record

    return invoke


def _rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def _write_rows(path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def test_v1_manifest_uses_fresh_tasks_seeds_and_matched_caps():
    legacy = load_manifest(DEFAULT_MANIFEST)
    manifest = load_manifest(V1_MANIFEST)
    plan = plan_dict(manifest)
    assert tuple(task["id"] for task in manifest["tasks"]) == SCAFFOLD_V1_TASK_IDS
    assert not set(SCAFFOLD_V1_TASK_IDS).intersection(
        task["id"] for task in legacy["tasks"]
    )
    assert sorted({row["seed"] for row in plan["calls"]}) == [101, 211, 307, 401, 503]
    assert plan["planned_calls"] == 25
    control, diverse = manifest["conditions"]
    assert control["max_tokens_per_call"] == (
        3 * diverse["generation_max_tokens_per_call"]
        + diverse["validator_max_tokens"]
    ) == 1280
    assert control["timeout_s_per_call"] == (
        3 * diverse["generation_timeout_s_per_call"]
        + diverse["validator_timeout_s"]
    ) == 80
    assert [len(_valid_proposals(task)) for task in manifest["tasks"]] == [
        2,
        18,
        64,
        28,
        5,
    ]


def test_v1_proposal_calls_are_independent_and_directive_separated():
    task = load_manifest(V1_MANIFEST)["tasks"][0]
    messages = [
        runner._explore_messages(task, directive_index=index)
        for index in range(3)
    ]
    assert len({rows[-1]["content"] for rows in messages}) == 3
    assert all("Candidate slots:" not in rows[-1]["content"] for rows in messages)
    assert all("reasoning channel" in rows[0]["content"] for rows in messages)
    assert all("exactly one JSON object" in rows[0]["content"] for rows in messages)


def test_v1_stubbed_run_has_strict_objective_success_and_taxonomy(tmp_path):
    manifest = load_manifest(V1_MANIFEST)
    artifact = runner.run_experiment(
        manifest,
        output_dir=tmp_path / "run",
        runtime_budget_s=850,
        invoke=_transport(manifest),
    )
    assert artifact["status"] == "complete"
    assert artifact["declared_calls"] == artifact["calls_recorded"] == 25
    assert all(row["creditable_task_success"] for row in artifact["outcomes"])
    assert all(
        diagnostic is None
        for row in artifact["outcomes"]
        for diagnostic in row["structured_output_diagnostics"]
    )
    assert artifact["summary"]["failure_taxonomy"] == {
        "structured_output": {},
        "substantive_invalid_proposals": 0,
        "substantive_selection_failures": 0,
    }


def test_v1_fence_and_reasoning_leakage_are_not_salvaged(tmp_path):
    manifest = load_manifest(V1_MANIFEST)
    first_id = manifest["tasks"][0]["id"]

    def override(*, task, seed, role, completion):
        if task["id"] == first_id and seed == 101:
            return f"```json\n{completion}\n```"
        if task["id"] == first_id and role == "validate":
            return f"<think>check slots</think>{completion}"
        return completion

    artifact = runner.run_experiment(
        manifest,
        output_dir=tmp_path / "run",
        runtime_budget_s=850,
        invoke=_transport(manifest, override=override),
    )
    row = next(
        item
        for item in artifact["outcomes"]
        if item["task_id"] == first_id and item["condition"] == "diverse_select"
    )
    assert not row["creditable_task_success"]
    assert [item and item["failure_code"] for item in row["structured_output_diagnostics"]] == [
        MARKDOWN_ENVELOPE,
        None,
        None,
        REASONING_CHANNEL_LEAKAGE,
    ]
    assert row["substantive_proposal_failures"] == []


def test_v1_separates_proposal_shape_from_substantive_feasibility(tmp_path):
    manifest = load_manifest(V1_MANIFEST)
    first_id = manifest["tasks"][0]["id"]

    def override(*, task, seed, role, completion):
        if task["id"] != first_id or role != "generate":
            return completion
        if seed == 101:
            return '{"proposal":{"row_action":"invest"}}'
        if seed == 211:
            return (
                '{"proposal":{"row_action":"invest",'
                '"column_action":"wait"}}'
            )
        return completion

    artifact = runner.run_experiment(
        manifest,
        output_dir=tmp_path / "run",
        runtime_budget_s=850,
        invoke=_transport(manifest, override=override),
    )
    row = next(
        item
        for item in artifact["outcomes"]
        if item["task_id"] == first_id and item["condition"] == "diverse_select"
    )
    assert row["structured_output_diagnostics"][0]["failure_code"] == FIELD_SCHEMA
    assert row["structured_output_diagnostics"][1] is None
    assert row["substantive_proposal_failures"] == [
        {
            "slot": 1,
            "reason": "profile admits a profitable unilateral deviation",
        }
    ]


def test_v1_wrong_valid_slot_is_substantive_selector_failure(tmp_path):
    manifest = load_manifest(V1_MANIFEST)
    first_id = manifest["tasks"][0]["id"]

    def override(*, task, seed, role, completion):
        if task["id"] == first_id and role == "validate":
            return '{"selected_slot":1}'
        return completion

    artifact = runner.run_experiment(
        manifest,
        output_dir=tmp_path / "run",
        runtime_budget_s=850,
        invoke=_transport(manifest, override=override),
    )
    row = next(
        item
        for item in artifact["outcomes"]
        if item["task_id"] == first_id and item["condition"] == "diverse_select"
    )
    assert all(item is None for item in row["structured_output_diagnostics"])
    assert not row["grade"]["selection_exact"]
    assert row["substantive_selection_failure"]
    assert not row["creditable_task_success"]


def test_v1_receipt_reconstructs_prompts_taxonomy_and_scores(tmp_path):
    manifest = load_manifest(V1_MANIFEST)
    frozen = plan_dict(manifest)
    output = tmp_path / "evaluation"
    artifact = runner.run_experiment(
        manifest,
        output_dir=output,
        runtime_budget_s=850,
        invoke=_transport(manifest),
    )
    calls = _rows(output / "calls.jsonl")
    for call in calls:
        call["run_id"] = artifact["run_id"]
    _write_rows(output / "calls.jsonl", calls)
    activity = []
    for call in calls:
        rate = call["usage"]["output_tokens"] / (call["latency_ms"] / 1000)
        activity.append(
            {
                "timestamp": call["timestamp"],
                "run_id": artifact["run_id"],
                "task_id": call["caller_tag"],
                "tokens_generated": call["usage"]["output_tokens"],
                "tokens_target": call["max_tokens"],
                "tok_per_s": rate,
                "eta_s": max(
                    0, call["max_tokens"] - call["usage"]["output_tokens"]
                )
                / rate,
                "synthetic": False,
                "backend": call["backend"],
                "model": call["model"],
            }
        )
    _write_rows(output / "worker_activity.jsonl", activity)
    plan = {
        "manifest_sha256": manifest["_raw_sha256"],
        "manifest_configuration_sha256": manifest["_configuration_sha256"],
        "condition_ids": [row["id"] for row in manifest["conditions"]],
        "expected_attempt_ids": [row["attempt_id"] for row in frozen["calls"]],
        "expected_input_sha256": manifest["frozen_hashes"]["tasks"],
        "expected_grader_sha256": {
            task["id"]: sha256_json(task["grader"])
            for task in manifest["tasks"]
        },
        "execution_dependencies": {
            str(path.relative_to(runner.REPO_ROOT)): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in runner.EXECUTION_SOURCE_FILES
        },
        "payload_budget_s": 850,
    }
    assert _validate((plan, output)) is True

    outcomes = _rows(output / "outcomes.jsonl")
    outcomes[0]["structured_output_diagnostics"][0] = {
        "failure_code": "malformed_json",
        "failure_detail": "forged after execution",
    }
    _write_rows(output / "outcomes.jsonl", outcomes)
    run = json.loads((output / "run.json").read_text())
    run["outcomes"] = outcomes
    (output / "run.json").write_text(json.dumps(run))
    with pytest.raises(TrialError, match="diversity parsed outcomes"):
        _validate((plan, output))
