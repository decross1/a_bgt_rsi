"""The routing policy cannot peek at the hidden answer or expand its budget."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from bench.weekly_upgrade_effort.manifest import load_manifest, plan_dict
from bench.weekly_upgrade_effort.runner import (
    grade_outcome,
    messages,
    protocol,
    route,
    run,
)
from bench.weekly_upgrade_eval.manifest import canonical_json

MANIFEST = Path(__file__).resolve().parents[1] / "experiments/weekly_role_effort_v1_2026-09-14.json"


def test_balanced_frozen_matrix_and_oracle_not_prompted():
    m = load_manifest(MANIFEST)
    assert len(plan_dict(m)["order"]) == 18
    task = deepcopy(m["tasks"][0])
    original = messages(task)
    task["expected"] = {"hidden_secret": "NEVER SHOW"}
    assert messages(task) == original
    assert "NEVER SHOW" not in json.dumps(messages(task, True))


def test_schema_and_uncertainty_escalate_but_semantic_oracle_cannot():
    assert route("critic", "adaptive") == "xhigh"
    assert route("evidence", "adaptive") == "medium"
    prior = {"effort": "medium", "status": "returned", "protocol_failure": None, "needs_review": False}
    assert route("evidence", "adaptive", prior) is None
    for changed in ({"protocol_failure": "markdown_envelope"}, {"needs_review": True}):
        assert route("evidence", "adaptive", {**prior, **changed}) == "xhigh"
    assert route("evidence", "adaptive", {**prior, "status": "timeout"}) is None
    assert route("evidence", "medium", {**prior, "needs_review": True}) is None
    assert route("evidence", "adaptive", {**prior, "effort": "xhigh", "needs_review": True}) is None


def test_protocol_vs_substantive_and_unordered_citations():
    m = load_manifest(MANIFEST)
    task = m["tasks"][1]
    correct = {**task["expected"], "citations": list(reversed(task["expected"]["citations"])), "needs_review": False}
    step = {"status": "returned", "completion": json.dumps(correct), "runtime_valid": True, "output_tokens": 20, "request_id": "r1"}
    planned = {"attempt_id": task["id"] + ":medium", "task_id": task["id"], "arm": "medium"}
    assert grade_outcome(m, task, planned, [step], 1)["passed"] is True
    step["completion"] = json.dumps({**correct, "answer_code": "causal_comparison_not_identified"})
    assert grade_outcome(m, task, planned, [step], 1)["failure_code"] == "substantive_mistake"
    assert protocol('```json\n' + json.dumps(correct) + '\n```', task["output_schema"])[1] == "markdown_envelope"
    step["completion"] = json.dumps({**correct, "needs_review": "false"})
    assert grade_outcome(m, task, planned, [step], 1)["failure_code"] == "value_schema"
    assert grade_outcome(m, task, planned, [], 0)["status"] == "not_run_budget"


def test_adaptive_budget_is_cumulative_and_protocol_failure_retained(tmp_path):
    clock_value = [0.0]
    seen = []
    def fake(
        manifest,
        task,
        effort,
        seed,
        max_tokens,
        timeout_s,
        retry,
        output,
        run_id,
        parent_request_id,
    ):
        seen.append(
            (task["id"], effort, max_tokens, timeout_s, retry, parent_request_id)
        )
        clock_value[0] += 2
        # Every medium response violates the public envelope; adaptive retries.
        payload = {**task["expected"], "needs_review": False}
        completion = json.dumps(payload)
        if effort == "medium":
            completion = f"```json\n{completion}\n```"
        return {"completion": completion, "request_id": str(len(seen)),
                "usage": {"output_tokens": 600}, "model": manifest["model"], "backend": manifest["backend"],
                "profile": "critic_current" if effort == "xhigh" else "critic_medium", "reasoning_effort": effort,
                "seed": seed, "max_tokens": max_tokens, "temperature": .2, "top_p": .95,
                "model_version": "pin", "host_metadata": {}, "sampling_extra": {}}
    result = run(MANIFEST, tmp_path / "eval", 1630, invoke_fn=fake, clock=lambda: clock_value[0])
    assert result["status"] == "completed"
    assert result["summary"]["arms"]["adaptive"]["escalations"] == 4
    assert result["summary"]["arms"]["adaptive"]["protocol_failure_counts"] == {
        "markdown_envelope": 4
    }
    assert len(seen) == 22
    for _, effort, max_tokens, timeout_s, retry, parent_request_id in seen:
        if retry:
            assert effort == "xhigh" and max_tokens == 4096 - 600 and timeout_s <= 88
            assert parent_request_id is not None
        else:
            assert parent_request_id is None


def test_bad_seed_and_budget_rejected(tmp_path):
    m = json.loads(MANIFEST.read_text())
    m["seed"] = True
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(m))
    with pytest.raises(ValueError, match="seed"):
        load_manifest(path)
    with pytest.raises(ValueError, match="runtime budget"):
        run(MANIFEST, tmp_path / "eval", float("nan"))


def test_controller_receipt_replays_and_rejects_forged_score(tmp_path, monkeypatch):
    import hashlib
    from datetime import datetime, timezone

    from agent_wrapper.worker_activity import emit_worker_activity
    from bench.weekly_upgrade_effort.runner import SOURCE_PATHS, write_json
    from orchestrator import weekly_upgrade_trial as controller
    root = MANIFEST.parents[1]
    monkeypatch.setattr(controller, "execution_fingerprint", lambda w: {
        p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in SOURCE_PATHS})
    plan = controller.plan_trial(str(MANIFEST.relative_to(root)), worktree=root)
    clock_value = [0.0]
    counter = [0]
    def fake(
        manifest,
        task,
        effort,
        seed,
        max_tokens,
        timeout_s,
        retry,
        output,
        run_id,
        parent_request_id,
    ):
        counter[0] += 1
        clock_value[0] += 1
        record = {"timestamp": datetime.now(timezone.utc).isoformat(), "run_id": run_id,
                  "completion": json.dumps({**task["expected"], "needs_review": effort == "medium"}),
                  "request_id": f"req-{counter[0]}", "usage": {"input_tokens": 30, "output_tokens": 20},
                  "model": manifest["model"], "backend": manifest["backend"], "model_version": "test/pin",
                  "profile": "critic_current" if effort == "xhigh" else "critic_medium", "reasoning_effort": effort,
                  "seed": seed, "max_tokens": max_tokens, "temperature": .2, "top_p": .95,
                  "host_metadata": {}, "sampling_extra": {}, "finish_reason": "stop", "reasoning_chars": 10,
                  "caller_tag": f"weekly_upgrade.role_effort.{task['role']}",
                  "parent_request_id": parent_request_id,
                  "prompt_messages": messages(task, retry), "latency_ms": 1}
        with (output / "calls.jsonl").open("a") as f:
            f.write(json.dumps(record) + "\n")
        emit_worker_activity(run_id=run_id, task_id=record["caller_tag"], output_tokens=20,
                             max_tokens=max_tokens, latency_ms=1, timestamp=record["timestamp"],
                             backend=record["backend"], model=record["model"], log_path=output / "worker_activity.jsonl")
        return record
    result = run(MANIFEST, tmp_path / "evaluation", 1630, invoke_fn=fake, clock=lambda: clock_value[0])
    assert controller.evaluation_receipt(plan, tmp_path)["execution_complete"] is True

    raw_path = tmp_path / "evaluation/raw_attempts.jsonl"
    pristine_raw = raw_path.read_bytes()
    raw = [json.loads(line) for line in pristine_raw.splitlines()]
    adaptive = next(
        row for row in raw if row["arm"] == "adaptive" and len(row["steps"]) == 2
    )
    assert adaptive["steps"][1]["parent_request_id"] == adaptive["steps"][0]["request_id"]

    adaptive["steps"][1]["parent_request_id"] = "forged-parent"
    raw_path.write_bytes(b"".join(canonical_json(row) + b"\n" for row in raw))
    with pytest.raises(controller.TrialError, match="routing or parent chain"):
        controller.evaluation_receipt(plan, tmp_path)
    raw_path.write_bytes(pristine_raw)

    raw = [json.loads(line) for line in pristine_raw.splitlines()]
    raw[0]["steps"][0]["output_tokens"] = raw[0]["steps"][0]["max_tokens"] + 1
    raw_path.write_bytes(b"".join(canonical_json(row) + b"\n" for row in raw))
    with pytest.raises(controller.TrialError, match="output-token budget"):
        controller.evaluation_receipt(plan, tmp_path)
    raw_path.write_bytes(pristine_raw)

    raw = [json.loads(line) for line in pristine_raw.splitlines()]
    del raw[0]["steps"][0]["needs_review"]
    raw_path.write_bytes(b"".join(canonical_json(row) + b"\n" for row in raw))
    with pytest.raises(controller.TrialError, match="step fields differ"):
        controller.evaluation_receipt(plan, tmp_path)
    raw_path.write_bytes(pristine_raw)

    raw = [json.loads(line) for line in pristine_raw.splitlines()]
    raw[0]["duration_s"] = 91
    raw_path.write_bytes(b"".join(canonical_json(row) + b"\n" for row in raw))
    with pytest.raises(controller.TrialError, match="cumulative cap"):
        controller.evaluation_receipt(plan, tmp_path)
    raw_path.write_bytes(pristine_raw)

    result["outcomes"][0]["passed"] = False
    write_json(tmp_path / "evaluation/run.json", result)
    with pytest.raises(controller.TrialError, match="coverage"):
        controller.evaluation_receipt(plan, tmp_path)
