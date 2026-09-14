"""Artifact-graph contract tests for weekly trial evaluation receipts."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent_wrapper import worker_activity, wrapper
from agent_wrapper.generation_policy import resolve_generation_policy
from bench.weekly_upgrade_eval import topic_scope
from bench.weekly_upgrade_eval.manifest import load_manifest
from bench.weekly_upgrade_eval.runner import (
    InvocationResult,
    _decode_tool_calls,
    _runtime_provenance,
    run_evaluation,
)
from orchestrator import weekly_upgrade_trial as trial

OBJECTIVE_MANIFEST = "bench/weekly_upgrade_eval/fixtures.json"
TOPIC_MANIFEST = "experiments/topic_scope_repair_2026-09-14.json"


def _append(path: Path, row: dict) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, sort_keys=True) + "\n")


def _activity(call: dict, path: Path) -> None:
    worker_activity.emit_worker_activity(
        run_id=call["run_id"],
        task_id=call["caller_tag"],
        output_tokens=call["usage"]["output_tokens"],
        max_tokens=call["max_tokens"],
        latency_ms=call["latency_ms"],
        timestamp=call["timestamp"],
        backend=call["backend"],
        model=call["model"],
        log_path=path,
    )


def _record(
    *, run_id: str, model: str, backend: str, messages: list[dict],
    completion: str, temperature: float, top_p: float, seed: int,
    max_tokens: int, caller_tag: str, parent_request_id: str | None,
    policy: dict | None = None,
) -> dict:
    row = {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "request_id": str(uuid.uuid4()),
        "run_id": run_id,
        "model": model,
        "model_version": "test/runtime@sha256:receipt",
        "backend": backend,
        "temperature": temperature,
        "top_p": top_p,
        "seed": seed,
        "max_tokens": max_tokens,
        "prompt_messages": messages,
        "completion": completion,
        "usage": {"input_tokens": 10, "output_tokens": 8},
        "latency_ms": 2.0,
        "host_metadata": {"vllm_image_tag": "test/runtime@sha256:receipt"},
        "caller_tag": caller_tag,
        "parent_request_id": parent_request_id,
        "finish_reason": "stop",
        "reasoning_chars": 0,
    }
    if policy is not None:
        row.update(policy)
    return row


def _objective_artifacts(tmp_path: Path) -> tuple[dict, Path]:
    plan = trial.plan_trial(OBJECTIVE_MANIFEST, worktree=trial.ROOT)
    output = tmp_path / "objective"
    manifest = load_manifest(trial.ROOT / OBJECTIVE_MANIFEST)

    def invoke(request):
        caller_tag = f"weekly_upgrade_eval:{request.task.id}"
        resolved = resolve_generation_policy(
            profile=request.arm.profile,
            backend_name=request.arm.backend,
            model_name=request.arm.model,
            seed=request.arm.seed,
            caller_tag=caller_tag,
        )
        policy = {
            **dict(resolved.logged_params),
            "profile": request.arm.profile,
            "reasoning_effort": resolved.reasoning_effort,
            "sampling_extra": dict(resolved.sampling_extra),
        }
        initial = [
            {"role": "system", "content": request.task.system},
            {"role": "user", "content": request.task.prompt},
        ]
        records = []
        if request.task.mode == "tools":
            expected = request.task.grader["expected"]
            tool_completion = json.dumps([{
                "id": "tool-call-1", "type": "function",
                "function": {
                    "name": expected["tool_name"],
                    "arguments": json.dumps(expected["arguments"]),
                },
            }])
            records.append(_record(
                run_id=request.run_id, model=request.arm.model,
                backend=request.arm.backend, messages=initial,
                completion=tool_completion, temperature=policy["temperature"],
                top_p=policy["top_p"], seed=request.arm.seed,
                max_tokens=request.arm.max_tokens, caller_tag=caller_tag,
                parent_request_id=request.run_id, policy=policy,
            ))
            final_messages = [
                *initial,
                {"role": "assistant", "content": ""},
                {"role": "tool", "content": json.dumps(request.task.tools[0]["result"])},
            ]
            completion = json.dumps(expected["answer"])
            records.append(_record(
                run_id=request.run_id, model=request.arm.model,
                backend=request.arm.backend, messages=final_messages,
                completion=completion, temperature=policy["temperature"],
                top_p=policy["top_p"], seed=request.arm.seed,
                max_tokens=request.arm.max_tokens, caller_tag=caller_tag,
                parent_request_id=records[-1]["request_id"], policy=policy,
            ))
        else:
            completion = json.dumps(request.task.grader["expected"])
            records.append(_record(
                run_id=request.run_id, model=request.arm.model,
                backend=request.arm.backend, messages=initial,
                completion=completion, temperature=policy["temperature"],
                top_p=policy["top_p"], seed=request.arm.seed,
                max_tokens=request.arm.max_tokens, caller_tag=caller_tag,
                parent_request_id=request.run_id, policy=policy,
            ))
        for row in records:
            _append(request.calls_log_path, row)
            _activity(row, request.worker_activity_path)
        rows = tuple(records)
        return InvocationResult(
            completion=rows[-1]["completion"], records=rows,
            tool_calls=_decode_tool_calls(rows),
            runtime_provenance=_runtime_provenance(rows),
        )

    run_evaluation(
        manifest,
        output_dir=output / "evaluation",
        runtime_budget_s=plan["payload_budget_s"],
        invoke=invoke,
    )
    return plan, output


def _topic_completion(messages: list[dict], call_number: int, *, invalid_first: bool) -> str:
    # The first planner call has no downstream R0 dependency. Its malformed
    # result is a measured protocol failure while all 80 transports can finish.
    if invalid_first and call_number == 33:
        return "not-json"
    user = messages[1]["content"]
    if user.startswith("Research topic: "):
        topic = user.removeprefix("Research topic: ")
        return json.dumps({"candidates": [topic], "chosen": topic})
    if "COORDINATOR brain" in messages[0]["content"]:
        return json.dumps([{"action": "noop", "args": {"reason": "diagnostic"}}])
    return json.dumps({"domain": "on", "reason": "strategic interaction"})


def _topic_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, invalid_first: bool = False,
) -> tuple[dict, Path]:
    plan = trial.plan_trial(TOPIC_MANIFEST, worktree=trial.ROOT)
    # This delivery worktree has not been committed yet, so git ls-files does
    # not include the new harness. Production execution requires it tracked.
    plan["execution_dependencies"]["bench/weekly_upgrade_eval/topic_scope.py"] = hashlib.sha256(
        (trial.ROOT / "bench/weekly_upgrade_eval/topic_scope.py").read_bytes()
    ).hexdigest()
    output = tmp_path / "topic"
    manifest = topic_scope.load_manifest(trial.ROOT / TOPIC_MANIFEST)
    calls = {"count": 0}

    def call_sync(messages, **kwargs):
        calls["count"] += 1
        completion = _topic_completion(messages, calls["count"], invalid_first=invalid_first)
        row = _record(
            run_id=wrapper.get_run_id(), model=kwargs["model"], backend=kwargs["backend"],
            messages=messages, completion=completion,
            temperature=kwargs["temperature"], top_p=kwargs["top_p"], seed=kwargs["seed"],
            max_tokens=kwargs["max_tokens"], caller_tag=kwargs["caller_tag"],
            parent_request_id=kwargs["parent_request_id"],
        )
        _append(Path(kwargs["log_path"]), row)
        _activity(row, worker_activity.DEFAULT_LOG_PATH)
        return row

    monkeypatch.delenv("MOCK_LLM", raising=False)
    monkeypatch.setattr(wrapper, "call_sync", call_sync)
    topic_scope.run_experiment(
        manifest,
        output_dir=output / "evaluation",
        runtime_budget_s=plan["payload_budget_s"],
        include_r0=True,
    )
    return plan, output


def _rewrite(path: Path, mutate) -> None:
    value = json.loads(path.read_text())
    mutate(value)
    path.write_text(json.dumps(value, sort_keys=True) + "\n")


def test_objective_receipt_reconstructs_full_artifact_graph(tmp_path):
    plan, output = _objective_artifacts(tmp_path)
    receipt = trial.evaluation_receipt(plan, output)
    assert receipt["status"] == "complete"
    assert receipt["execution_complete"] is True
    assert receipt["semantic_benefit_measured"] is False
    assert {
        "run.json", "manifest.snapshot.json", "calls.A.jsonl",
        "calls.B.jsonl", "worker_activity.jsonl",
    } <= set(receipt["artifact_sha256"])


@pytest.mark.parametrize("tamper", ["summary", "completion", "prompt", "activity", "payload"])
def test_objective_receipt_rejects_unbound_or_fabricated_artifacts(tmp_path, tamper):
    plan, output = _objective_artifacts(tmp_path)
    evaluation = output / "evaluation"
    if tamper == "summary":
        _rewrite(evaluation / "run.json", lambda value: value["summary"].update({"elapsed_s": -1}))
    elif tamper == "completion":
        _rewrite(evaluation / "run.json", lambda value: value["outcomes"][0].update({"completion": "{}"}))
    elif tamper == "prompt":
        rows = (evaluation / "calls.A.jsonl").read_text().splitlines()
        first = json.loads(rows[0])
        first["prompt_messages"][1]["content"] = "unregistered input"
        rows[0] = json.dumps(first)
        (evaluation / "calls.A.jsonl").write_text("\n".join(rows) + "\n")
    elif tamper == "activity":
        rows = (evaluation / "worker_activity.jsonl").read_text().splitlines()
        row = json.loads(rows[0])
        row["tokens_generated"] += 1
        rows[0] = json.dumps(row)
        (evaluation / "worker_activity.jsonl").write_text("\n".join(rows) + "\n")
    else:
        _rewrite(
            evaluation / "run.json",
            lambda value: value["provenance"]["run_configuration"].update({"runtime_budget_s": 1}),
        )
    with pytest.raises(trial.TrialError):
        trial.evaluation_receipt(plan, output)


def test_topic_receipt_binds_all_80_attempts_without_semantic_success(tmp_path, monkeypatch):
    plan, output = _topic_artifacts(tmp_path, monkeypatch, invalid_first=True)
    receipt = trial.evaluation_receipt(plan, output)
    assert receipt["status"] == "awaiting_annotation"
    assert receipt["execution_complete"] is True
    assert receipt["semantic_benefit_measured"] is False
    run = json.loads((output / "evaluation" / "run.json").read_text())
    assert len(run["outcomes"]) == 80
    assert next(row for row in run["outcomes"] if row["stage"] == "planner")["protocol_valid"] is False


@pytest.mark.parametrize("tamper", ["raw", "parsed", "private", "blind", "activity", "payload"])
def test_topic_receipt_rejects_broken_raw_parsed_blind_or_runtime_views(
    tmp_path, monkeypatch, tamper,
):
    plan, output = _topic_artifacts(tmp_path, monkeypatch)
    evaluation = output / "evaluation"
    if tamper in {"raw", "parsed"}:
        path = evaluation / f"{tamper}_attempts.jsonl"
        rows = path.read_text().splitlines()
        row = json.loads(rows[0])
        row["case_id"] = "T8"
        rows[0] = json.dumps(row)
        path.write_text("\n".join(rows) + "\n")
    elif tamper == "private":
        _rewrite(evaluation / "arm_map_private.json", lambda value: value["items"].reverse())
    elif tamper == "blind":
        _rewrite(
            evaluation / "annotation_blind.json",
            lambda value: value["items"][0].update({"input_topic": "unregistered topic"}),
        )
    elif tamper == "activity":
        rows = (evaluation / "worker_activity.jsonl").read_text().splitlines()
        rows.pop()
        (evaluation / "worker_activity.jsonl").write_text("\n".join(rows) + "\n")
    else:
        _rewrite(evaluation / "run.json", lambda value: value.update({"runtime_budget_s": 1}))
    with pytest.raises(trial.TrialError):
        trial.evaluation_receipt(plan, output)
