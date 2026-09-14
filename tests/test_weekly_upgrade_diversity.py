"""Objective graders and frozen-input contracts for diversity selection."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys

import pytest

from bench.weekly_upgrade_diversity.graders import grade_proposal, grade_set
from bench.weekly_upgrade_diversity.manifest import (
    DEFAULT_MANIFEST,
    ManifestError,
    _candidate_space,
    load_manifest,
    plan_dict,
)

VALID = {
    "DIV-GT-PURE-NASH-001": [
        {"row_action": "adopt", "column_action": "adopt"},
        {"row_action": "status_quo", "column_action": "status_quo"},
    ],
    "DIV-D075-BALLOT-001": [
        {"ABC": 2, "ACB": 1, "BAC": 0, "BCA": 2, "CAB": 0, "CBA": 2},
        {"ABC": 3, "ACB": 0, "BAC": 1, "BCA": 1, "CAB": 0, "CBA": 2},
    ],
    "DIV-D075-DELEGATION-001": [
        {"x": "A", "y": "A", "z": "B"},
        {"x": "A", "y": "B", "z": "->x"},
    ],
    "DIV-GT-COORDINATION-001": [
        {"a": 1, "b": 0, "c": 0, "d": 1},
        {"a": 2, "b": 0, "c": 0, "d": 2},
    ],
    "DIV-GT-COALITION-001": [
        {"coalition": ["p", "q"]},
        {"coalition": ["p", "r"]},
    ],
}

INVALID = {
    "DIV-GT-PURE-NASH-001": {"row_action": "adopt", "column_action": "status_quo"},
    "DIV-D075-BALLOT-001": {"ABC": 7, "ACB": 0, "BAC": 0, "BCA": 0, "CAB": 0, "CBA": 0},
    "DIV-D075-DELEGATION-001": {"x": "->y", "y": "->x", "z": "B"},
    "DIV-GT-COORDINATION-001": {"a": 0, "b": 0, "c": 0, "d": 0},
    "DIV-GT-COALITION-001": {"coalition": ["p"]},
}


@pytest.fixture(scope="module")
def tasks():
    return {task["id"]: task for task in load_manifest()["tasks"]}


def test_manifest_freezes_five_public_tasks_and_matched_budgets():
    manifest = load_manifest()
    assert manifest["publication_class"] == "public_synthetic_development"
    assert len(manifest["tasks"]) == 5
    assert all(task["provenance"]["origin"] == "synthetic_authored_for_eval" for task in manifest["tasks"])
    control, diverse = manifest["conditions"]
    assert control["max_tokens_per_call"] == (
        3 * diverse["generation_max_tokens_per_call"] + diverse["validator_max_tokens"]
    ) == 1280
    assert control["timeout_s_per_call"] == (
        3 * diverse["generation_timeout_s_per_call"] + diverse["validator_timeout_s"]
    ) == 80


def test_every_task_has_multiple_finitely_enumerated_valid_solutions(tasks):
    expected_counts = {
        "DIV-GT-PURE-NASH-001": 2,
        "DIV-D075-BALLOT-001": 6,
        "DIV-D075-DELEGATION-001": 9,
        "DIV-GT-COORDINATION-001": 30,
        "DIV-GT-COALITION-001": 3,
    }
    for task_id, task in tasks.items():
        assert sum(grade_proposal(task, proposal).valid for proposal in _candidate_space(task)) == expected_counts[task_id]


@pytest.mark.parametrize("task_id", sorted(VALID))
def test_each_objective_grader_accepts_two_valid_and_rejects_plausible_error(task_id, tasks):
    assert all(grade_proposal(tasks[task_id], proposal).valid for proposal in VALID[task_id])
    assert not grade_proposal(tasks[task_id], INVALID[task_id]).valid


def test_selection_metric_counts_unique_feasible_and_recovery(tasks):
    task = tasks["DIV-GT-COALITION-001"]
    grade = grade_set(
        task,
        [VALID[task["id"]][0], {"coalition": ["q", "p"]}, INVALID[task["id"]]],
        1,
    )
    assert grade["valid_count"] == 2
    assert grade["valid_unique_count"] == 1
    assert grade["selected_valid"] is True
    assert grade["recovered_from_invalid_candidates"] is True
    assert grade["task_success"] is True


def test_selector_cannot_claim_success_by_selecting_invalid_or_out_of_range(tasks):
    task = tasks["DIV-GT-PURE-NASH-001"]
    proposals = [INVALID[task["id"]], VALID[task["id"]][0], VALID[task["id"]][1]]
    for selected in (0, 8, True, None):
        assert not grade_set(task, proposals, selected)["task_success"]


def test_plan_has_25_serial_calls_and_alternates_condition_groups():
    plan = plan_dict(load_manifest())
    assert plan["planned_calls"] == 25
    assert len({row["attempt_id"] for row in plan["calls"]}) == 25
    first = [row["condition"] for row in plan["calls"][:5]]
    second = [row["condition"] for row in plan["calls"][5:10]]
    assert first == ["control"] + ["diverse_select"] * 4
    assert second == ["diverse_select"] * 4 + ["control"]


def test_manifest_rejects_duplicates_hash_drift_and_budget_mismatch(tmp_path):
    text = DEFAULT_MANIFEST.read_text()
    duplicate = text.replace(
        '"schema_version": "weekly-upgrade-diversity-selection/v1",',
        '"schema_version": "weekly-upgrade-diversity-selection/v1",\n'
        '  "schema_version": "weekly-upgrade-diversity-selection/v1",',
        1,
    )
    path = tmp_path / "duplicate.json"
    path.write_text(duplicate)
    with pytest.raises(ManifestError, match="duplicate"):
        load_manifest(path)

    document = json.loads(text)
    document["tasks"][0]["problem"] += " easier"
    path = tmp_path / "drift.json"
    path.write_text(json.dumps(document))
    with pytest.raises(ManifestError, match="frozen hashes"):
        load_manifest(path)

    document = json.loads(text)
    document["conditions"][1]["validator_max_tokens"] = 129
    path = tmp_path / "budget.json"
    path.write_text(json.dumps(document))
    with pytest.raises(ManifestError, match="diverse condition"):
        load_manifest(path)


def test_plan_subprocess_does_not_import_wrapper_or_write(tmp_path):
    code = (
        "import json,sys; from bench.weekly_upgrade_diversity.runner import main; "
        f"rc=main(['--plan','--manifest',{str(DEFAULT_MANIFEST)!r}]); "
        "print(json.dumps({'rc':rc,'wrapper':'agent_wrapper.wrapper' in sys.modules}))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=DEFAULT_MANIFEST.parents[1],
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
        env={**os.environ, "MOCK_LLM": "1"},
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout.splitlines()[-1]) == {"rc": 0, "wrapper": False}
    assert not list(tmp_path.iterdir())


def test_task_hash_covers_grader_and_problem():
    manifest = load_manifest()
    mutated = copy.deepcopy(manifest["tasks"][0])
    mutated["grader"]["inputs"]["row_payoffs"][0][0] += 1
    from bench.weekly_upgrade_diversity.manifest import sha256_json

    assert sha256_json(mutated) != manifest["frozen_hashes"]["tasks"][mutated["id"]]
