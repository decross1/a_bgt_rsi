"""Real portfolio artifacts must bind calls, cells, grades and source code."""
import hashlib
import json
import uuid
from datetime import datetime, timezone

import pytest

from bench.weekly_upgrade_portfolio import runner
from bench.weekly_upgrade_portfolio.manifest import load_manifest
from orchestrator import weekly_upgrade_trial as trial

MANIFEST = "experiments/weekly_upgrade_game_science_dev_v0_2026-09-14.json"


@pytest.fixture
def artifacts(tmp_path, monkeypatch, request):
    manifest = load_manifest(trial.ROOT / MANIFEST)
    monkeypatch.setattr(runner, "sandbox_runtime_identity", lambda **_kwargs: manifest["sandbox_runtime"])
    code_observations = getattr(request, "param", None) == "code"
    if code_observations:
        from bench.weekly_upgrade_portfolio.code_sandbox import SandboxResult

        def fake_sandbox(source, function_name, arguments, **_kwargs):
            # Synthetic trusted-parent observations exercise receipt replay.
            # Separate sandbox tests execute correct and malicious code.
            task = next(t for t in manifest["tasks"] if t["starter"]
                        and t["starter"]["function"] == function_name)
            case = next(c for c in task["grader"]["inputs"]["cases"] if c["arguments"] == arguments)
            return (SandboxResult("exception", exception_type=case["expected_exception"], input_mutated=False)
                    if "expected_exception" in case else
                    SandboxResult("returned", value=case["expected_return"], input_mutated=False))

        monkeypatch.setattr(runner, "run_case", fake_sandbox)
    plan = trial.plan_trial(MANIFEST)
    # New sources can be untracked during implementation; live execution still
    # requires a committed clean fingerprint. Bind these exact test sources.
    for path in runner.EXECUTION_SOURCE_FILES:
        plan["execution_dependencies"][str(path.relative_to(trial.ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    output = tmp_path / "trial"
    evaluation = output / "evaluation"

    def invoke(messages, **kwargs):
        completion = "{}"
        task = next(t for t in manifest["tasks"] if t["prompt"] == messages[1]["content"])
        if code_observations and task["mode"] == "code":
            function = task["starter"]["function"]
            args = "ballots" if function == "resolve" else "payoffs, chosen"
            completion = json.dumps({"source": f"def {function}({args}):\n    return {{}}\n"})
        row = {
            "timestamp": datetime.now(timezone.utc).isoformat(), "request_id": str(uuid.uuid4()),
            "run_id": "test-portfolio", "model": kwargs["model"], "backend": kwargs["backend"],
            "model_version": "test/runtime", "host_metadata": {"vllm_image_tag": "test"},
            "temperature": 0.2, "top_p": 0.95, "seed": kwargs["seed"],
            "max_tokens": kwargs["max_tokens"], "profile": kwargs["profile"],
            "reasoning_effort": "xhigh" if kwargs["profile"] == "critic_current" else "medium",
            "sampling_extra": {}, "finish_reason": "stop", "reasoning_chars": 0,
            "prompt_messages": messages, "completion": completion,
            "usage": {"input_tokens": 10, "output_tokens": 8}, "latency_ms": 1,
            "caller_tag": kwargs["caller_tag"], "parent_request_id": None,
        }
        with open(kwargs["log_path"], "a") as stream:
            stream.write(json.dumps(row) + "\n")
        from agent_wrapper.worker_activity import emit_worker_activity
        emit_worker_activity(
            run_id=row["run_id"], task_id=row["caller_tag"], output_tokens=8,
            max_tokens=kwargs["max_tokens"], latency_ms=1, timestamp=row["timestamp"],
            backend=row["backend"], model=row["model"],
            log_path=evaluation / "worker_activity.jsonl",
        )
        return row

    artifact = runner.run_experiment(
        manifest, output_dir=evaluation, runtime_budget_s=2280, invoke=invoke,
    )
    # Align the synthetic transport's durable run identifier, without mocking
    # the receipt verifier or bypassing its schema/grade checks.
    for filename in ("calls.jsonl", "worker_activity.jsonl"):
        path = evaluation / filename
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        for row in rows:
            row["run_id"] = artifact["run_id"]
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return plan, output


def test_portfolio_registry_preserves_full_fixed_matrix():
    plan = trial.plan_trial(MANIFEST)
    assert plan["kind"] == "portfolio"
    assert plan["declared_attempts"] == 16
    assert plan["seeds"] == [0]
    assert plan["reservation_s"] == 2310 and plan["payload_budget_s"] == 2280
    assert plan["production_change_authorized"] is False


def test_correctness_failures_are_completed_transport_not_claimed_gain(artifacts):
    plan, output = artifacts
    receipt = trial.evaluation_receipt(plan, output)
    assert receipt["execution_complete"] is True
    assert receipt["semantic_benefit_measured"] is False
    assert set(receipt["artifact_sha256"]) == {
        "run.json", "manifest.snapshot.json", "raw_attempts.jsonl", "outcomes.jsonl",
        "calls.jsonl", "worker_activity.jsonl",
    }


@pytest.mark.parametrize("artifacts", ["code"], indirect=True)
def test_code_receipt_replays_parent_observations_without_executing_code(artifacts, monkeypatch):
    plan, output = artifacts
    import bench.weekly_upgrade_portfolio.code_sandbox as sandbox
    monkeypatch.setattr(sandbox, "run_case", lambda *a, **k: pytest.fail("receipt executed code"))
    assert trial.evaluation_receipt(plan, output)["execution_complete"] is True
    run = json.loads((output / "evaluation" / "run.json").read_text())
    assert sum(row["passed"] for row in run["outcomes"] if row["mode"] == "code") == 4

    # Alter the observed function value and its self-hash while retaining the
    # recorded passing grade: the trusted oracle must expose the mismatch.
    row = next(row for row in run["outcomes"] if row["mode"] == "code")
    observation = row["grade_details"]["cases"][0]
    observation["observation"]["value"] = {"fabricated": "success"}
    from bench.weekly_upgrade_portfolio.manifest import sha256_json
    observation["observation_sha256"] = sha256_json(observation["observation"])
    (output / "evaluation" / "run.json").write_text(json.dumps(run))
    (output / "evaluation" / "outcomes.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in run["outcomes"])
    )
    with pytest.raises(trial.TrialError, match="portfolio"):
        trial.evaluation_receipt(plan, output)


@pytest.mark.parametrize("tamper", [
    "grade", "call", "raw", "extra", "order", "source", "sandbox", "elapsed", "request_id",
])
def test_forged_portfolio_evidence_is_rejected(artifacts, tamper):
    plan, output = artifacts
    evaluation = output / "evaluation"
    if tamper == "grade":
        path = evaluation / "outcomes.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        rows[0]["passed"] = True
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        run_path = evaluation / "run.json"
        run = json.loads(run_path.read_text())
        run["outcomes"] = rows
        run_path.write_text(json.dumps(run))
    elif tamper in {"call", "extra"}:
        path = evaluation / "calls.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        if tamper == "call":
            rows[0]["prompt_messages"][1]["content"] = "Different easier question"
        else:
            rows.append({**rows[0], "request_id": str(uuid.uuid4())})
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    elif tamper in {"raw", "order"}:
        path = evaluation / "raw_attempts.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        if tamper == "raw":
            rows[0]["completion"] = '{"success":true}'
        else:
            rows[0], rows[1] = rows[1], rows[0]
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    elif tamper == "source":
        plan["execution_dependencies"]["bench/weekly_upgrade_portfolio/graders.py"] = "0" * 64
    else:
        path = evaluation / "run.json"
        run = json.loads(path.read_text())
        if tamper == "sandbox":
            run["sandbox_runtime_observed"]["python_sha256"] = "0" * 64
        elif tamper == "elapsed":
            run["summary"] = runner._summarize(run["outcomes"], 0.000001)
        else:
            run["outcomes"][0]["request_id"] = str(uuid.uuid4())
            (evaluation / "outcomes.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in run["outcomes"])
            )
        path.write_text(json.dumps(run))
    with pytest.raises(trial.TrialError, match="portfolio"):
        trial.evaluation_receipt(plan, output)
