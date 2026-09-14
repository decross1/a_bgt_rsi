"""Dispatcher tests use real journals/Git and synthetic evaluation transport."""
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from bench.weekly_upgrade_eval.manifest import load_manifest
from bench.weekly_upgrade_eval.runner import InvocationResult, run_evaluation
from orchestrator import weekly_upgrade_trial as trial
from orchestrator.weekly_upgrade_budget import BudgetLedger

MANIFEST = "bench/weekly_upgrade_eval/fixtures.json"


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True,
                                   stderr=subprocess.DEVNULL).strip()


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "canonical"
    path = root / MANIFEST
    path.parent.mkdir(parents=True)
    doc = json.loads((trial.ROOT / MANIFEST).read_text())
    doc["tasks"] = doc["tasks"][:2]
    doc["bootstrap_samples"] = 100
    path.write_text(json.dumps(doc))
    (root / "run_state").mkdir()
    (root / "agent_wrapper").mkdir()
    (root / "agent_wrapper" / "bound.py").write_text("policy = 1\n")
    (root / "AGENTS.md").write_text("maintenance authority\n")
    for name in ("manifest.py", "runner.py", "stats.py"):
        relative = f"bench/weekly_upgrade_eval/{name}"
        (root / relative).write_bytes((trial.ROOT / relative).read_bytes())
    git(root, "init", "-q")
    git(root, "add", ".")
    git(root, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
        "commit", "-qm", "frozen test inputs")
    return root


def idle(_root, *, idle):
    return {"mem_available_gib": 40, "queues": []}


def synthetic_runner(command, *, worktree, output, **kwargs):
    """Produce the real artifact format without SDK or GPU use."""
    manifest = load_manifest(command[command.index("--manifest") + 1])
    def invoke(request):
        from bench.weekly_upgrade_eval.runner import _runtime_provenance
        completion = json.dumps(request.task.grader["expected"])
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(), "request_id": str(uuid.uuid4()),
            "run_id": request.run_id, "model": request.arm.model, "backend": request.arm.backend,
            "model_version": "test/runtime", "host_metadata": {"vllm_image_tag": "test"},
            "temperature": 0.2, "top_p": 0.95, "seed": request.arm.seed,
            "max_tokens": request.arm.max_tokens, "profile": request.arm.profile,
            "reasoning_effort": "xhigh" if request.arm.id == "A" else "medium",
            "sampling_extra": {}, "finish_reason": "stop", "reasoning_chars": 0,
            "prompt_messages": [{"role": "system", "content": request.task.system},
                                {"role": "user", "content": request.task.prompt}],
            "completion": completion, "usage": {"input_tokens": 10, "output_tokens": 8},
            "latency_ms": 1, "caller_tag": f"weekly_upgrade_eval:{request.task.id}",
            "parent_request_id": request.run_id,
        }
        with request.calls_log_path.open("a") as stream:
            stream.write(json.dumps(record) + "\n")
        from agent_wrapper.worker_activity import emit_worker_activity
        emit_worker_activity(run_id=request.run_id, task_id=record["caller_tag"],
                             output_tokens=8, max_tokens=request.arm.max_tokens,
                             latency_ms=1, timestamp=record["timestamp"], backend=request.arm.backend,
                             model=request.arm.model, log_path=request.worker_activity_path)
        return InvocationResult(completion=completion, records=(record,),
                                runtime_provenance=_runtime_provenance((record,)))
    run_evaluation(
        manifest, output_dir=output / "evaluation",
        runtime_budget_s=float(command[command.index("--runtime-budget-s") + 1]), invoke=invoke,
    )
    return {"returncode": 0}


def run(repo, output, **kwargs):
    return trial.execute_trial(
        trial.plan_trial(MANIFEST, worktree=repo), output, worktree=repo,
        manual=True, probe=idle, runner=synthetic_runner, **kwargs,
    )


def state_path(repo, plan):
    return repo / "run_state" / "weekly_upgrade" / "trials" / f"{plan['trial_id']}.json"


def test_plan_is_read_only_binds_full_cells_and_utc(repo):
    before = git(repo, "status", "--porcelain")
    plan = trial.plan_trial(MANIFEST, worktree=repo,
                            now=datetime(2026, 9, 21, 1, tzinfo=timezone(timedelta(hours=2))))
    assert plan["week_id"] == "2026-W38"
    assert plan["declared_attempts"] == len(plan["expected_attempt_ids"]) == 4
    assert plan["arm_ids"] == ["A", "B"]
    assert "agent_wrapper/bound.py" in plan["execution_dependencies"]
    assert not list((repo / "run_state").iterdir())
    assert git(repo, "status", "--porcelain") == before
    with pytest.raises(trial.TrialError, match="timezone"):
        trial.plan_trial(MANIFEST, worktree=repo, now=datetime(2026, 9, 14))  # noqa: DTZ001 -- rejection test


def test_execution_requires_explicit_admission_and_rederives_plan(repo, tmp_path):
    plan = trial.plan_trial(MANIFEST, worktree=repo)
    with pytest.raises(trial.TrialError, match="requires"):
        trial.execute_trial(plan, tmp_path / "out", worktree=repo)
    with pytest.raises(trial.TrialError, match="differs"):
        trial.execute_trial({**plan, "reservation_s": 1}, tmp_path / "out",
                            worktree=repo, manual=True)
    assert not list((repo / "run_state").iterdir())


def test_context_tokenizer_drift_refuses_before_budget_and_model_calls(repo, tmp_path, monkeypatch):
    from bench.weekly_upgrade_context import preflight

    monkeypatch.setattr(trial, "CONTEXT_MANIFEST", MANIFEST)
    def drift(_path):
        assert not (repo / "run_state/weekly_upgrade_budget.jsonl").exists()
        raise ValueError("tokenizer artifacts changed")
    monkeypatch.setattr(preflight, "validate_context_preflight", drift)
    with pytest.raises(ValueError, match="tokenizer artifacts changed"):
        run(repo, tmp_path / "context-refused")
    assert not (repo / "run_state/weekly_upgrade_budget.jsonl").exists()
    assert not (tmp_path / "context-refused/evaluation").exists()


def test_context_tokenizer_receipt_is_persisted_and_bound(repo, tmp_path, monkeypatch):
    from bench.weekly_upgrade_context import preflight

    marker = {"test_tokenizer_receipt": "bound"}
    monkeypatch.setattr(trial, "CONTEXT_MANIFEST", MANIFEST)
    monkeypatch.setattr(preflight, "validate_context_preflight", lambda _path: marker)
    validations = []
    def validate(receipt, manifest_sha, dependencies):
        assert receipt == marker
        assert manifest_sha == trial.plan_trial(MANIFEST, worktree=repo)["manifest_sha256"]
        assert dependencies
        validations.append(receipt)
        return receipt
    monkeypatch.setattr(preflight, "validate_preflight_receipt", validate)
    output = tmp_path / "context-receipt"
    result = run(repo, output)
    assert result["status"] == "completed"
    assert validations == [marker]
    assert result["evaluation"]["artifact_sha256"]["../context_preflight.json"] == trial._sha(
        (output / "context_preflight.json").read_bytes(),
    )


def test_registered_manifest_cannot_redirect(repo, tmp_path):
    path = repo / MANIFEST
    copy = tmp_path / "redirect.json"
    path.rename(copy)
    path.symlink_to(copy)
    with pytest.raises(trial.TrialError, match="redirect"):
        trial.plan_trial(MANIFEST, worktree=repo)


def test_topic_protocol_repair_has_distinct_trial_identity_and_keeps_all_cells():
    moment = datetime(2026, 9, 14, tzinfo=timezone.utc)
    original = trial.plan_trial(
        "experiments/topic_scope_repair_2026-09-14.json", now=moment,
    )
    repaired = trial.plan_trial(
        "experiments/topic_scope_repair_v2_2026-09-14.json", now=moment,
    )
    assert original["manifest_sha256"] == (
        "aab09640a9d377fc0a2a1c830223f5cd8b4e7e20299ac968d7bd01f2512b06a2"
    )
    assert repaired["trial_id"] != original["trial_id"]
    assert repaired["expected_attempt_ids"] == original["expected_attempt_ids"]
    assert repaired["declared_attempts"] == 80
    assert repaired["include_primary_r0"]
    assert repaired["reservation_s"] == original["reservation_s"] == 2400
    assert repaired["payload_budget_s"] == original["payload_budget_s"] == 2370


def test_canonical_and_linked_worktrees_share_budget_and_reject_live_outputs(repo, tmp_path):
    linked = tmp_path / "linked"
    git(repo, "worktree", "add", "--detach", str(linked))
    assert trial.canonical_root(linked) == repo
    plan = trial.plan_trial(MANIFEST, worktree=linked)
    for output in (repo / "memory" / "eval", linked / "logs" / "eval"):
        with pytest.raises(trial.TrialError, match="outside both"):
            trial.execute_trial(plan, output, worktree=linked, manual=True)
    result = run(linked, tmp_path / "out")
    ledger = BudgetLedger(repo / "run_state" / "weekly_upgrade_budget.jsonl")
    assert ledger.existing(plan["trial_id"]) == result["budget_receipt"]
    with pytest.raises(trial.TrialError, match="different plan or artifact"):
        run(repo, tmp_path / "different-output")


def test_complete_is_accounted_and_resume_never_replays(repo, tmp_path):
    output = tmp_path / "out"
    result = run(repo, output)
    assert result["status"] == "completed"
    assert result["budget_receipt"]["charged_s"] < 1800
    assert result["evaluation"]["execution_complete"]
    assert not result["semantic_benefit_measured"]
    (output / "trial_result.json").write_text('{"status":"forged"}')
    def never(*args, **kwargs):
        pytest.fail("resume called the runner")
    resumed = trial.execute_trial(trial.plan_trial(MANIFEST, worktree=repo), output,
                                  worktree=repo, manual=True, probe=never, runner=never)
    assert resumed == result
    assert json.loads((output / "trial_result.json").read_text()) == result


def test_dirty_harness_blocks_before_reservation(repo, tmp_path):
    (repo / "agent_wrapper" / "bound.py").write_text("policy = 2\n")
    with pytest.raises(trial.TrialError, match="freeze"):
        run(repo, tmp_path / "out")
    assert not (repo / "run_state" / "weekly_upgrade_budget.jsonl").exists()


def test_exit_zero_without_artifacts_is_failed(repo, tmp_path):
    plan = trial.plan_trial(MANIFEST, worktree=repo)
    result = trial.execute_trial(plan, tmp_path / "out", worktree=repo, manual=True,
                                 probe=idle, runner=lambda *a, **k: {"returncode": 0})
    assert result["status"] == "failed"
    assert result["evaluation"] is None
    assert result["budget_receipt"]["status"] == "failed"


def test_unconfirmed_server_stop_charges_whole_reservation(repo, tmp_path):
    calls = []
    def probe(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise trial.TrialError("queue still running")
        return idle(*args, **kwargs)
    plan = trial.plan_trial(MANIFEST, worktree=repo)
    result = trial.execute_trial(plan, tmp_path / "out", worktree=repo, manual=True,
                                 probe=probe, runner=synthetic_runner)
    assert result["status"] == "interrupted"
    assert result["budget_receipt"]["charged_s"] == 1800


def test_serving_restart_invalidates_experiment_even_with_valid_answers(repo, tmp_path):
    probes = []
    def probe(*args, **kwargs):
        probes.append(1)
        return {**idle(*args, **kwargs), "runtime_identity": [{"id": len(probes)}]}
    result = trial.execute_trial(trial.plan_trial(MANIFEST, worktree=repo), tmp_path / "out",
                                 worktree=repo, manual=True, probe=probe, runner=synthetic_runner)
    assert result["status"] == "interrupted"
    assert result["budget_receipt"]["charged_s"] == 1800
    assert "runtime changed" in result["error"]


def test_concurrent_harness_change_invalidates_execution(repo, tmp_path):
    def changing_runner(*args, **kwargs):
        result = synthetic_runner(*args, **kwargs)
        (repo / "agent_wrapper" / "bound.py").write_text("policy = 2\n")
        return result
    result = trial.execute_trial(trial.plan_trial(MANIFEST, worktree=repo), tmp_path / "out",
                                 worktree=repo, manual=True, probe=idle, runner=changing_runner)
    assert result["status"] == "interrupted"
    assert result["budget_receipt"]["charged_s"] == 1800
    assert "dependencies changed" in result["error"]


@pytest.mark.parametrize("crash_phase", ["prepared", "reserved", "finishing", "finished"])
def test_crash_windows_are_recoverable_without_double_execution(repo, tmp_path, monkeypatch, crash_phase):
    output = tmp_path / "out"
    original = trial._write
    calls = []
    def crash(path, value):
        # Before durable write: prepared => no reservation; reserved => reserved
        # budget but only prepared journal; finishing => no terminal evidence;
        # finished => terminal evidence and budget already safely committed.
        if path.parent.name == "trials" and value.get("phase") == crash_phase:
            raise SystemExit("simulated controller death")
        return original(path, value)
    def runner(*args, **kwargs):
        calls.append(1)
        return synthetic_runner(*args, **kwargs)
    plan = trial.plan_trial(MANIFEST, worktree=repo)
    monkeypatch.setattr(trial, "_write", crash)
    with pytest.raises(SystemExit):
        trial.execute_trial(plan, output, worktree=repo, manual=True, probe=idle, runner=runner)
    monkeypatch.setattr(trial, "_write", original)
    result = trial.execute_trial(plan, output, worktree=repo, manual=True, probe=idle, runner=runner)
    expected = "completed" if crash_phase in {"prepared", "finished"} else "interrupted"
    assert result["status"] == expected
    assert result["budget_receipt"]["status"] == expected
    assert result["elapsed_s"] == result["budget_receipt"]["elapsed_s"]
    assert len(calls) == (0 if crash_phase == "reserved" else 1)
    if expected == "interrupted":
        assert result["budget_receipt"]["charged_s"] == 1800


def test_crash_after_finishing_journal_before_budget_release(repo, tmp_path, monkeypatch):
    original = BudgetLedger.finish
    monkeypatch.setattr(BudgetLedger, "finish", lambda *a, **kw: (_ for _ in ()).throw(SystemExit()))
    with pytest.raises(SystemExit):
        run(repo, tmp_path / "out")
    monkeypatch.setattr(BudgetLedger, "finish", original)
    result = run(repo, tmp_path / "out")
    assert result["status"] == "completed"
    assert result["budget_receipt"]["charged_s"] < 1800


def test_recovery_refuses_live_process_handle(repo, tmp_path, monkeypatch):
    output = tmp_path / "out"
    run(repo, output)
    monkeypatch.setattr(trial, "live_trial_processes", lambda _: [123])
    with pytest.raises(trial.TrialError, match="live process"):
        run(repo, output)


@pytest.mark.parametrize("metrics", ["", "vllm:num_requests_running 0\n",
                                     "vllm:num_requests_running NaN\nvllm:num_requests_waiting 0",
                                     "vllm:num_requests_running -1\nvllm:num_requests_waiting 0"])
def test_missing_or_invalid_metrics_fail_closed(metrics):
    with pytest.raises(trial.TrialError):
        trial._queue_counts(metrics)


def test_queue_labels_and_pause_control(repo):
    assert trial._queue_counts('vllm:num_requests_running{model_name="qwen"} 0\n'
                               'vllm:num_requests_waiting{model_name="qwen"} 1\n') == {
                                   "running": 0, "waiting": 1}
    (repo / "run_state" / "pause_weekly_upgrade").touch()
    with pytest.raises(trial.TrialError, match="pause control"):
        trial.resource_probe(repo, idle=True)


def test_deadline_command_has_no_model_supplied_shell(repo, tmp_path):
    plan = trial.plan_trial(MANIFEST, worktree=repo)
    command = trial.trial_command(plan, tmp_path / "out", 1800, worktree=repo)
    assert command[0].endswith("timeout")
    assert command[command.index("-m") + 1] == "bench.weekly_upgrade_eval.runner"
    assert float(command[command.index("--runtime-budget-s") + 1]) < 1800 - trial.KILL_GRACE_S
    later = trial.trial_command(plan, tmp_path / "out", 1795, worktree=repo)
    assert later == command  # preflight jitter cannot change a repeat's payload cap
    with pytest.raises(trial.TrialError, match="reservation exhausted"):
        trial.trial_command(plan, tmp_path / "out", 1700, worktree=repo)


def test_supervisor_terminates_owned_process_on_abort(repo, tmp_path):
    output = tmp_path / "process"
    output.mkdir()
    def abort(*args, **kwargs):
        raise trial.TrialError("stop control")
    with trial.resource_lease(repo) as descriptors, pytest.raises(trial.TrialError, match="stop control"):
        trial.supervise([sys.executable, "-c", "import time; time.sleep(60)"],
                        worktree=repo, output=output, pass_fds=descriptors,
                        root=repo, probe=abort)
    receipt = json.loads((output / "process.json").read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(receipt["pid"], 0)
    assert receipt["boot_id"] and receipt["start_ticks"] and receipt["argv_sha256"]


def reviewed(repo, output):
    # Reuse the schema-complete simulated reviewers; the synthetic receipt
    # explicitly models subscription auth. No real provider is invoked.
    from test_weekly_upgrade import FakeFrontier
    def proposal(value):
        plan = trial.plan_trial(MANIFEST, worktree=repo)
        value["experiment"].update(
            fixture_ids=plan["fixture_ids"], seeds=plan["seeds"],
            max_gpu_minutes=30, max_wall_minutes=30,
        )
        return value
    simulated = FakeFrontier(proposal_mutator=proposal)
    def provider(*args, **kwargs):
        value = simulated(*args, **kwargs)
        value["metadata"]["auth_mode"] = "subscription"
        return value
    return trial.review.run_review(repo, output, frontier_call_budget=2,
                                   total_deadline_s=600, max_gpu_minutes=30,
                                   call_timeout_s=120, invoke_fn=provider)


def test_snapshot_review_and_registered_execution_round_trip(repo, tmp_path):
    review_dir = tmp_path / "review"
    report = reviewed(repo, review_dir)
    assert report["status"] == "CONTINUE_TRIAL"
    plan = trial.plan_trial(MANIFEST, worktree=repo, review_dir=review_dir)
    frozen = json.loads((review_dir / "run_manifest.json").read_text())["snapshot"]
    entry = next(row for row in frozen["evaluation_manifests"] if row["path"] == MANIFEST)
    assert entry["execution"]["declared_attempts"] == 4
    result = trial.execute_trial(plan, tmp_path / "out", worktree=repo,
                                 review_dir=review_dir, probe=idle, runner=synthetic_runner)
    assert result["status"] == "completed"
    assert result["production_change_authorized"] is False


@pytest.mark.parametrize("tamper", ["provider", "response", "dependencies", "subset"])
def test_reviewed_execution_rejects_broken_bindings(repo, tmp_path, tamper):
    review_dir = tmp_path / "review"
    reviewed(repo, review_dir)
    if tamper == "dependencies":
        (repo / "agent_wrapper" / "bound.py").write_text("policy = 2\n")
    elif tamper == "provider":
        path = review_dir / "receipts" / "02-upgrade_adversary.json"
        row = json.loads(path.read_text())
        row["transport"]["auth_mode"] = "api_key"
        path.write_text(json.dumps(row))
    elif tamper == "response":
        path = review_dir / "unvalidated" / "01-upgrade_proposer.json"
        row = json.loads(path.read_text())
        row["text"] = '{}'
        path.write_text(json.dumps(row))
    else:
        path = review_dir / "weekly_report.json"
        row = json.loads(path.read_text())
        row["experiment_card"]["fixture_ids"].pop()
        path.write_text(json.dumps(row))
    with pytest.raises((trial.TrialError, trial.ValidationError)):
        trial.plan_trial(MANIFEST, worktree=repo, review_dir=review_dir)
    assert not (repo / "run_state" / "weekly_upgrade_budget.jsonl").exists()


def test_missing_budget_cannot_erase_same_week_canonical_trial(repo, tmp_path):
    plan = trial.plan_trial(MANIFEST, worktree=repo)
    journal = repo / "run_state" / "weekly_upgrade" / "trials" / "prior.json"
    journal.parent.mkdir(parents=True)
    journal.write_text(json.dumps({
        "phase": "finished",
        "plan": {"week_id": plan["week_id"], "trial_id": "prior"},
        "result": {"trial_id": "prior", "status": "failed"},
    }))
    with pytest.raises(trial.TrialError, match="without the canonical budget"):
        trial.execute_trial(
            plan, tmp_path / "out", worktree=repo, manual=True,
            probe=idle, runner=synthetic_runner,
        )
    assert not (repo / "run_state" / "weekly_upgrade_budget.jsonl").exists()
