"""Durability and denominator contracts for the diversity runner."""

from __future__ import annotations

import inspect
import json
import uuid
from datetime import datetime, timezone

import pytest

from agent_wrapper import wrapper
from bench.weekly_upgrade_diversity import runner
from bench.weekly_upgrade_diversity.manifest import load_manifest, plan_dict
from tests.test_weekly_upgrade_diversity import INVALID, VALID


def _transport(manifest, *, malformed_attempt=None):
    by_problem = {task["problem"]: task for task in manifest["tasks"]}
    counter = 0

    def invoke(messages, **kwargs):
        nonlocal counter
        counter += 1
        user = messages[-1]["content"]
        task = next(task for problem, task in by_problem.items() if problem in user)
        valid = VALID[task["id"]]
        invalid = INVALID[task["id"]]
        if kwargs["profile"] == "explore":
            index = {11: 0, 29: 1, 47: 2}[kwargs["seed"]]
            proposal = valid[index] if index < 2 else invalid
            completion = json.dumps({"proposal": proposal})
        elif "Candidate slots:" in user:
            completion = json.dumps({"selected_slot": 0})
        else:
            completion = json.dumps(
                {"proposals": [valid[0], valid[1], invalid], "selected_index": 1}
            )
        if counter == malformed_attempt:
            completion = '{"proposal":NaN}'
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "request_id": str(uuid.uuid4()),
            "model": kwargs["model"],
            "model_version": "stub-gemma-content-sha256:abc",
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


def _jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_stubbed_run_preserves_25_calls_and_objective_condition_scores(tmp_path):
    manifest = load_manifest()
    output = tmp_path / "run"
    artifact = runner.run_experiment(
        manifest,
        output_dir=output,
        runtime_budget_s=850,
        invoke=_transport(manifest),
    )
    assert artifact["status"] == "complete"
    assert artifact["declared_calls"] == artifact["calls_recorded"] == 25
    assert len(artifact["outcomes"]) == 10
    assert all(row["creditable_task_success"] for row in artifact["outcomes"])
    assert all(row["grade"]["valid_unique_count"] == 2 for row in artifact["outcomes"])
    assert all(
        row["grade"]["recovered_from_invalid_candidates"]
        for row in artifact["outcomes"]
    )
    raw = _jsonl(output / "raw_calls.jsonl")
    calls = _jsonl(output / "calls.jsonl")
    assert [row["attempt_id"] for row in raw] == [
        row["attempt_id"] for row in plan_dict(manifest)["calls"]
    ]
    assert [row["request_id"] for row in raw] == [row["request_id"] for row in calls]


def test_malformed_call_stays_in_denominator_and_cannot_be_credited(tmp_path):
    manifest = load_manifest()
    artifact = runner.run_experiment(
        manifest,
        output_dir=tmp_path / "run",
        runtime_budget_s=850,
        invoke=_transport(manifest, malformed_attempt=2),
    )
    assert artifact["status"] == "complete"
    assert artifact["calls_recorded"] == 25
    affected = next(row for row in artifact["outcomes"] if row["parse_errors"][0])
    assert affected["creditable_task_success"] is False


def test_expired_budget_retains_every_call_without_invoking(tmp_path):
    manifest = load_manifest()
    ticks = 0

    def clock():
        nonlocal ticks
        ticks += 1
        return 0.0 if ticks == 1 else 2.0

    def forbidden(*args, **kwargs):
        raise AssertionError("transport cannot run after deadline")

    artifact = runner.run_experiment(
        manifest,
        output_dir=tmp_path / "run",
        runtime_budget_s=1,
        invoke=forbidden,
        monotonic=clock,
    )
    assert artifact["status"] == "incomplete_transport"
    assert artifact["calls_recorded"] == 25
    assert all(row["status"] == "not_run_budget" for row in _jsonl(tmp_path / "run" / "raw_calls.jsonl"))


def test_raw_completion_is_durable_before_grader_failure(tmp_path, monkeypatch):
    manifest = load_manifest()

    def explode(*args, **kwargs):
        raise RuntimeError("synthetic grader crash")

    monkeypatch.setattr(runner, "grade_set", explode)
    output = tmp_path / "run"
    with pytest.raises(RuntimeError, match="grader crash"):
        runner.run_experiment(
            manifest,
            output_dir=output,
            runtime_budget_s=850,
            invoke=_transport(manifest),
        )
    rows = _jsonl(output / "raw_calls.jsonl")
    assert len(rows) == 1
    assert rows[0]["completion"]


def test_real_wrapper_signature_accepts_every_frozen_call(tmp_path):
    manifest = load_manifest()
    spec = plan_dict(manifest)["calls"][0]
    kwargs = {
        "profile": spec["profile"],
        "seed": spec["seed"],
        "max_tokens": spec["max_tokens"],
        "request_timeout_s": spec["timeout_s"],
        "caller_tag": "weekly_upgrade.diversity.generate",
        "parent_request_id": None,
        "log_path": str(tmp_path / "calls.jsonl"),
        "backend": manifest["model"]["backend"],
        "model": manifest["model"]["served_name"],
    }
    inspect.signature(wrapper.call_sync).bind(runner._control_messages(manifest["tasks"][0]), **kwargs)


def test_output_directory_inside_repository_is_rejected():
    manifest = load_manifest()
    with pytest.raises(ValueError, match="outside the repository"):
        runner.run_experiment(
            manifest,
            output_dir=runner.REPO_ROOT / "untracked-diversity-output",
            runtime_budget_s=850,
            invoke=lambda *_args, **_kwargs: {},
        )
