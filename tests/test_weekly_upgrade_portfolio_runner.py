"""End-to-end artifact contracts for the public synthetic portfolio runner."""

from __future__ import annotations

import inspect
import json
import uuid
from datetime import datetime, timezone

import pytest

from agent_wrapper import wrapper
from bench.weekly_upgrade_portfolio import runner
from bench.weekly_upgrade_portfolio.manifest import load_manifest, plan_dict
from tests.test_weekly_upgrade_portfolio_graders import (
    DELEGATION_SOURCE,
    REGRET_SOURCE,
    VALID,
)


def _answers(manifest):
    answers = dict(VALID)
    answers["CODE-D075-DELEGATION-001"] = {"source": DELEGATION_SOURCE}
    answers["CODE-GT-REGRET-001"] = {"source": REGRET_SOURCE}
    return {
        task["prompt"]: json.dumps(answers[task["id"]], separators=(",", ":"))
        for task in manifest["tasks"]
    }


def _transport(manifest, *, override=None):
    answers = _answers(manifest)
    call_number = 0

    def invoke(messages, **kwargs):
        nonlocal call_number
        call_number += 1
        completion = answers[messages[-1]["content"]]
        if override is not None:
            completion = override(call_number, completion)
        effort = "xhigh" if kwargs["profile"] == "critic_current" else "medium"
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "request_id": str(uuid.uuid4()),
            "model": kwargs["model"],
            "model_version": "stub-content-sha256:abc",
            "backend": kwargs["backend"],
            "profile": kwargs["profile"],
            "temperature": 0.2,
            "top_p": 0.95,
            "seed": kwargs["seed"],
            "reasoning_effort": effort,
            "sampling_extra": {},
            "max_tokens": kwargs["max_tokens"],
            "prompt_messages": messages,
            "completion": completion,
            "usage": {"input_tokens": 10, "output_tokens": 5},
            "latency_ms": 1.0,
            "host_metadata": {"host": "deterministic-test"},
            "caller_tag": kwargs["caller_tag"],
            "parent_request_id": kwargs["parent_request_id"],
            "finish_reason": "stop",
            "reasoning_chars": 0,
        }
        with open(kwargs["log_path"], "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
        return record

    return invoke


def _jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_stubbed_run_writes_auditable_16_cell_artifact(tmp_path):
    manifest = load_manifest()
    output = tmp_path / "run"
    artifact = runner.run_experiment(
        manifest,
        output_dir=output,
        runtime_budget_s=2280,
        invoke=_transport(manifest),
    )
    assert artifact["status"] == "complete"
    assert artifact["declared_attempts"] == artifact["attempts_recorded"] == 16
    assert all(row["passed"] for row in artifact["outcomes"])
    assert artifact["sandbox_runtime_valid"] is True

    raw = _jsonl(output / "raw_attempts.jsonl")
    outcomes = _jsonl(output / "outcomes.jsonl")
    calls = _jsonl(output / "calls.jsonl")
    assert [row["attempt_id"] for row in raw] == [
        row["attempt_id"] for row in plan_dict(manifest)["order"]
    ]
    assert [row["request_id"] for row in raw] == [row["request_id"] for row in calls]
    assert [row["request_id"] for row in outcomes] == [
        row["request_id"] for row in calls
    ]
    code_rows = [row for row in outcomes if row["mode"] == "code"]
    assert code_rows
    for row in code_rows:
        details = row["grade_details"]
        assert details["sandbox"] == "bubblewrap-fresh-process-per-case"
        assert len(details["source_sha256"]) == 64
        assert all(
            set(case) >= {
                "case_id",
                "timeout_s",
                "arguments_sha256",
                "observation",
                "observation_sha256",
                "oracle_sha256",
                "input_mutated",
                "passed",
            }
            for case in details["cases"]
        )


@pytest.mark.parametrize("bad", ['{"x":1,"x":2}', '{"x":NaN}'])
def test_duplicate_keys_and_nonfinite_completion_fail_but_keep_denominator(tmp_path, bad):
    manifest = load_manifest()
    artifact = runner.run_experiment(
        manifest,
        output_dir=tmp_path / "run",
        runtime_budget_s=2280,
        invoke=_transport(manifest, override=lambda number, value: bad if number == 1 else value),
    )
    assert artifact["status"] == "complete"
    assert artifact["attempts_recorded"] == 16
    first = artifact["outcomes"][0]
    assert first["passed"] is False
    assert first["failure_code"] == "schema"
    assert _jsonl(tmp_path / "run" / "raw_attempts.jsonl")[0]["completion"] == bad


def test_resolved_policy_drift_invalidates_run(tmp_path):
    manifest = load_manifest()
    base = _transport(manifest)
    count = 0

    def drift(messages, **kwargs):
        nonlocal count
        count += 1
        record = base(messages, **kwargs)
        if count == 1:
            record["max_tokens"] += 1
        return record

    artifact = runner.run_experiment(
        manifest,
        output_dir=tmp_path / "run",
        runtime_budget_s=2280,
        invoke=drift,
    )
    assert artifact["status"] == "invalid_runtime_drift"
    assert artifact["attempts_recorded"] == 16
    assert artifact["outcomes"][0]["failure_code"] == "runtime_drift"


def test_expired_budget_keeps_all_declared_cells_without_invocation(tmp_path):
    manifest = load_manifest()
    ticks = 0

    def clock():
        nonlocal ticks
        ticks += 1
        return 0.0 if ticks == 1 else 2.0

    def forbidden(*args, **kwargs):
        raise AssertionError("expired budget must not invoke transport")

    artifact = runner.run_experiment(
        manifest,
        output_dir=tmp_path / "run",
        runtime_budget_s=1,
        invoke=forbidden,
        monotonic=clock,
    )
    assert artifact["status"] == "incomplete_transport"
    assert artifact["attempts_recorded"] == 16
    assert all(row["failure_code"] == "budget" for row in artifact["outcomes"])


def test_call_kwargs_bind_real_wrapper_signature(tmp_path):
    manifest = load_manifest()
    arm = manifest["arms"][0]
    task = manifest["tasks"][0]
    kwargs = runner._call_kwargs(arm, task, tmp_path / "calls.jsonl", 200)
    inspect.signature(wrapper.call_sync).bind(runner._messages(task), **kwargs)
    assert kwargs["seed"] == 0
    assert kwargs["request_timeout_s"] == task["request_timeout_s"]
    assert kwargs["log_path"] == str(tmp_path / "calls.jsonl")
