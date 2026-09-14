import hashlib
import json

import pytest

from tools.record_weekly_evaluation import observations, record


def test_adaptive_retries_do_not_expand_planned_task_denominator_or_erase_failure():
    row = {"arm": "adaptive", "status": "returned", "protocol_valid": True,
           "passed": True, "step_protocol_failures": ["malformed_json"],
           "step_transport_statuses": ["returned", "returned"], "failure_code": None}
    plan = {"kind": "role_effort", "arm_ids": ["adaptive"], "declared_attempts": 1}
    overall, arms = observations(plan, {"outcomes": [row]}, [])
    assert overall["fixed_attempts_expected"] == 1
    assert overall["objective_cases_passed"] == 1
    assert overall["failure_categories"] == [{"code": "malformed_json", "count": 1}]
    assert arms[0]["annotation_disagreements"] is None
    with pytest.raises(ValueError, match="denominator"):
        observations({**plan, "declared_attempts": 2}, {"outcomes": [row]}, [])


def test_actual_repairs_use_task_success_not_internal_pytest_case_count():
    rows = [{"arm_id": "gemma", "status": "returned", "creditable_success": p, "patch_error": None,
             "grader": {"status": "passed" if p else "timeout"}} for p in (True, False)]
    overall, _ = observations({"kind": "historical_repair", "arm_ids": ["gemma"], "declared_attempts": 2}, {"outcomes": rows}, [])
    assert overall["repair_cases_passed"] == 1
    assert overall["repair_cases_total"] == 2
    assert overall["objective_cases_total"] is None
    assert overall["fixed_attempts_protocol_valid"] is None
    assert overall["failure_categories"] == [{"code": "grader_timeout", "count": 1}]


def test_diversity_counts_calls_for_transport_and_tasks_for_success():
    row = {"condition": "diverse_select", "attempt_ids": ["a", "b", "c", "d"],
           "structured_output_diagnostics": [None, None, {"failure_code": "malformed_json", "failure_detail": "x"}, None],
           "creditable_task_success": False, "substantive_proposal_failures": [],
           "substantive_selection_failure": None}
    calls = [{"condition": "diverse_select", "status": "returned"} for _ in range(4)]
    overall, _ = observations({"kind": "diversity", "arm_ids": ["diverse_select"], "declared_attempts": 4}, {"outcomes": [row]}, calls)
    assert overall["fixed_attempts_expected"] == 4
    assert overall["fixed_attempts_protocol_valid"] == 3
    assert overall["objective_cases_total"] == 1
    assert overall["failure_categories"] == [{"code": "malformed_json", "count": 1}]


@pytest.mark.parametrize("mutate", [False, True])
def test_terminal_publication_binds_replayed_bytes_and_refuses_race(tmp_path, monkeypatch, mutate):
    from orchestrator import weekly_upgrade_trial as trial
    repo, output = tmp_path / "repo", tmp_path / "output"
    journals = repo / "run_state/weekly_upgrade/trials"
    journals.mkdir(parents=True)
    (output / "evaluation").mkdir(parents=True)
    trial_id = "2026-W38-" + "a" * 24
    plan = {"kind": "historical_repair", "trial_id": trial_id, "arm_ids": ["gemma"], "declared_attempts": 1}
    run = {"outcomes": [{"arm_id": "gemma", "status": "returned", "creditable_success": False,
                         "patch_error": None, "grader": {"status": "failed"}}]}
    path = output / "evaluation/run.json"
    path.write_text(json.dumps(run))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    receipt = {"sha256": digest, "artifact_sha256": {"run.json": digest}}
    result = {"trial_id": trial_id, "status": "completed", "evaluation": receipt}
    result_path = output / "trial_result.json"
    result_path.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    journal = {"phase": "finished", "plan": plan, "result": result, "output": str(output)}
    journal_path = journals / (trial_id + ".json")
    journal_path.write_text(json.dumps(journal))
    def replay(*args):
        if mutate:
            run["outcomes"][0]["creditable_success"] = True
            path.write_text(json.dumps(run))
        return receipt
    monkeypatch.setattr(trial, "evaluation_receipt", replay)
    if mutate:
        with pytest.raises(ValueError, match="bytes changed"):
            record(repo, trial_id)
        assert not (repo / "run_state/weekly_upgrade/evaluations" / (trial_id + ".json")).exists()
    else:
        target = record(repo, trial_id)
        value = json.loads(target.read_text())
        assert value["trial_journal_sha256"] == hashlib.sha256(journal_path.read_bytes()).hexdigest()
        assert value["trial_result_sha256"] == hashlib.sha256(result_path.read_bytes()).hexdigest()
        assert value["summary_artifact_sha256"] == digest
        assert value["observations"]["repair_cases_passed"] == 0
        assert record(repo, trial_id) == target
        from orchestrator.weekly_upgrade import _evaluation_history, _trial_history
        trials, invalid = _trial_history(repo)
        assert invalid == 0
        summaries, invalid = _evaluation_history(repo, trials)
        assert invalid == 0
        assert summaries[0]["trial_id"] == trial_id

        for field, bad in (("arm", "unplanned"), ("fixed_attempts_expected", 2)):
            changed = json.loads(json.dumps(value))
            changed["arm_observations"][0][field] = bad
            target.write_text(json.dumps(changed))
            rejected, invalid = _evaluation_history(repo, trials)
            assert rejected == [] and invalid == 1
