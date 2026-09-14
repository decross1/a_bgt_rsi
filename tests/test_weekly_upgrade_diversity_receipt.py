"""Tamper tests for the judge-free diversity evidence graph."""

from __future__ import annotations

import hashlib
import json
import math
import uuid

import pytest

from bench.weekly_upgrade_diversity import runner
from bench.weekly_upgrade_diversity.manifest import (
    load_manifest,
    plan_dict,
    sha256_json,
)
from bench.weekly_upgrade_diversity.receipt import validate_diversity_receipt
from orchestrator import weekly_upgrade_trial as trial
from tests.test_weekly_upgrade_diversity_runner import _transport

MANIFEST = "experiments/diversity_selection_dev_v0_2026-09-14.json"
TrialError = trial.TrialError


def _rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def _write_rows(path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


@pytest.fixture
def evidence(tmp_path):
    manifest = load_manifest()
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
                "eta_s": max(0, call["max_tokens"] - call["usage"]["output_tokens"]) / rate,
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
            task["id"]: sha256_json(task["grader"]) for task in manifest["tasks"]
        },
        "execution_dependencies": {
            str(path.relative_to(runner.REPO_ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in runner.EXECUTION_SOURCE_FILES
        },
        "payload_budget_s": 850,
    }
    return plan, output


def _validate(evidence):
    plan, output = evidence

    def regular(name, *, required=True):
        path = output / name
        if not path.exists():
            if required:
                raise TrialError(f"missing {name}")
            return None
        if path.is_symlink() or not path.is_file():
            raise TrialError(f"not regular {name}")
        return path

    def json_lines(name, *, required=True):
        path = regular(name, required=required)
        return [] if path is None else _rows(path)

    def validate_calls(rows, *, run_id):
        if any(row.get("run_id") != run_id for row in rows):
            raise TrialError("wrong run id")
        ids = [row.get("request_id") for row in rows]
        if len(ids) != len(set(ids)):
            raise TrialError("duplicate call")

    def validate_activity(rows, calls, *, run_id):
        if len(rows) != len(calls) or any(row.get("run_id") != run_id for row in rows):
            raise TrialError("activity differs")

    def finite(value, where):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or value < 0
        ):
            raise TrialError(f"{where} invalid")
        return float(value)

    artifact = json.loads((output / "run.json").read_text())
    return validate_diversity_receipt(
        plan,
        artifact,
        output / "manifest.snapshot.json",
        regular=regular,
        json_lines=json_lines,
        validate_calls=validate_calls,
        validate_activity=validate_activity,
        finite_nonnegative=finite,
    )


def test_complete_receipt_reconstructs_all_calls_prompts_and_scores(evidence):
    assert _validate(evidence) is True


def test_registered_dispatch_plan_and_receipt_preserve_the_full_matrix(evidence, tmp_path):
    evidence_plan, evaluation = evidence
    plan = trial.plan_trial(MANIFEST)
    # These sources are intentionally untracked until the delivery commit;
    # live execution still refuses an uncommitted dependency tree.
    plan["execution_dependencies"].update(evidence_plan["execution_dependencies"])
    assert plan["kind"] == "diversity"
    assert plan["arm_ids"] == plan["condition_ids"] == ["control", "diverse_select"]
    assert plan["seeds"] == [0, 11, 29, 47]
    assert plan["reservation_s"] == 880
    assert plan["payload_budget_s"] == 850
    assert plan["declared_attempts"] == len(plan["expected_attempt_ids"]) == 25
    assert plan["production_change_authorized"] is False

    command = trial.trial_command(plan, tmp_path / "command-output", 880)
    assert command[command.index("-m") + 1] == "bench.weekly_upgrade_diversity.runner"
    assert command[command.index("--runtime-budget-s") + 1] == "850"

    receipt = trial.evaluation_receipt(plan, evaluation.parent)
    assert receipt["execution_complete"] is True
    assert receipt["semantic_benefit_measured"] is False
    assert set(receipt["artifact_sha256"]) == {
        "run.json",
        "manifest.snapshot.json",
        "raw_calls.jsonl",
        "outcomes.jsonl",
        "calls.jsonl",
        "worker_activity.jsonl",
    }


@pytest.mark.parametrize(
    "tamper",
    [
        "raw",
        "call_prompt",
        "policy",
        "parent",
        "grade",
        "source",
        "budget",
        "elapsed",
        "extra_call",
        "extra_raw",
    ],
)
def test_tampered_evidence_is_rejected(evidence, tamper):
    plan, output = evidence
    if tamper == "raw":
        path = output / "raw_calls.jsonl"
        rows = _rows(path)
        rows[0]["completion"] = '{"proposals":[],"selected_index":null}'
        _write_rows(path, rows)
    elif tamper == "call_prompt":
        path = output / "calls.jsonl"
        rows = _rows(path)
        rows[0]["prompt_messages"][1]["content"] = "easier replacement"
        _write_rows(path, rows)
    elif tamper == "policy":
        path = output / "calls.jsonl"
        rows = _rows(path)
        rows[0]["temperature"] = 0.9
        _write_rows(path, rows)
    elif tamper == "parent":
        raw_path, calls_path = output / "raw_calls.jsonl", output / "calls.jsonl"
        raw, calls = _rows(raw_path), _rows(calls_path)
        validator_index = next(index for index, row in enumerate(raw) if row["role"] == "validate")
        forged = str(uuid.uuid4())
        raw[validator_index]["parent_request_id"] = forged
        calls[validator_index]["parent_request_id"] = forged
        _write_rows(raw_path, raw)
        _write_rows(calls_path, calls)
    elif tamper == "grade":
        outcome_path, run_path = output / "outcomes.jsonl", output / "run.json"
        outcomes = _rows(outcome_path)
        outcomes[0]["grade"]["valid_unique_count"] += 1
        _write_rows(outcome_path, outcomes)
        artifact = json.loads(run_path.read_text())
        artifact["outcomes"] = outcomes
        run_path.write_text(json.dumps(artifact))
    elif tamper == "source":
        plan["execution_dependencies"]["bench/weekly_upgrade_diversity/graders.py"] = "0" * 64
    elif tamper == "budget":
        run_path = output / "run.json"
        artifact = json.loads(run_path.read_text())
        artifact["runtime_budget_s"] = 849
        run_path.write_text(json.dumps(artifact))
    elif tamper == "elapsed":
        run_path = output / "run.json"
        artifact = json.loads(run_path.read_text())
        artifact["summary"] = runner._summary(artifact["outcomes"], 0.000001)
        run_path.write_text(json.dumps(artifact))
    elif tamper == "extra_call":
        path = output / "calls.jsonl"
        rows = _rows(path)
        rows.append({**rows[0], "request_id": str(uuid.uuid4())})
        _write_rows(path, rows)
    else:
        path = output / "raw_calls.jsonl"
        rows = _rows(path)
        rows[0]["unexpected"] = True
        _write_rows(path, rows)
    with pytest.raises(TrialError, match="diversity"):
        _validate(evidence)
