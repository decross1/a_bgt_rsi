"""Pure content-free projection guards for admitted game-pilot reports."""
from __future__ import annotations

import importlib
import json
import subprocess
import sys
from copy import deepcopy

import pytest

from bench.agentic_game_theory import known_opponent_comparison as c


def test_normal_import_does_not_change_python_module_resolution():
    before = list(sys.path)
    importlib.reload(c)
    assert sys.path == before
    with pytest.raises(c.ComparisonError, match="direct-script entrypoint"):
        c._registered_modules()
    assert sys.path == before


def _task(ordinal: int) -> dict:
    return {"cell": {"ordinal": ordinal, "id": f"test-{ordinal}",
                     "mix": "retainers", "objective": "own_payoff",
                     "seat": 0, "rule_label": "A"},
            "task_sha256": f"{ordinal:064x}"}


def _row(task: dict, *, complete: bool) -> dict:
    return {"cell": task["cell"], "task_sha256": task["task_sha256"],
            "scheduled_actions": 8, "comprehension": "passed",
            "valid_prefix_actions": 8 if complete else 3,
            "first_invalid_round": None if complete else 4,
            "full_episode": {"episode_regret": "0"} if complete else None,
            "calls": [{"wall_s": 0.1,
                       "usage": {"completion_tokens": 1}} for _ in range(
                           9 if complete else 5)]}


def test_cell_projection_keeps_unknown_regret_and_rejects_invented_full_score():
    task = _task(0)
    incomplete = _row(task, complete=False)
    projected = c.project_cell(task, incomplete)
    assert projected["valid_action_prefix"] == 3
    assert projected["episode_regret"] is None
    assert projected["zero_regret"] is None
    invented = deepcopy(incomplete)
    invented["full_episode"] = {"episode_regret": "0"}
    with pytest.raises(c.ComparisonError, match="invented a full regret"):
        c.project_cell(task, invented)


def test_full_arm_denominators_bind_independent_replay_counts():
    tasks = [_task(i) for i in range(12)]
    rows = [_row(task, complete=i < 4) for i, task in enumerate(tasks)]
    replay = {"admission_eligible": True, "recorded_episodes": 12,
              "comprehension_passed": 12, "valid_action_calls": 56,
              "complete_episodes": 4, "zero_regret_complete_episodes": 4,
              "attempted_calls": 76, "scheduled_action_calls": 96,
              "returned_sse_verified": 76}
    projected, summary = c.project_arm(
        {"tasks": tasks, "max_tokens": 64},
        {"cells": rows, "elapsed_s": 10.0}, replay)
    assert len(projected) == 12
    assert summary["complete_episodes"] == 4
    assert summary["scheduled_action_calls"] == 96
    assert summary["reported_completion_tokens"] == 76
    assert summary["calls_with_reported_usage"] == 76
    assert summary["issued_call_wall_s_sum"] == 7.6
    altered = {**replay, "zero_regret_complete_episodes": 5}
    with pytest.raises(c.ComparisonError, match="replayed denominators"):
        c.project_arm({"tasks": tasks, "max_tokens": 64},
                      {"cells": rows, "elapsed_s": 10.0}, altered)


def test_matching_requires_exact_ordered_tasks_and_seed_policy():
    tasks = [_task(i) for i in range(12)]
    manifest = {"schedule": [task["cell"] for task in tasks], "tasks": tasks,
                "policy": c.MIA_POLICY, "seed_base": 301,
                "max_tokens": 64, "per_call_timeout_s": 30.0,
                "max_window_s": 900, "max_calls": 108, "horizon": 8}
    matched = c._matching(manifest, deepcopy(manifest))
    assert matched["fixed_game_conditions_matched"] is True
    assert matched["adaptive_histories_and_later_call_seeds_may_differ"] is True
    reordered = deepcopy(manifest)
    reordered["tasks"][0], reordered["tasks"][1] = (
        reordered["tasks"][1], reordered["tasks"][0])
    with pytest.raises(c.ComparisonError, match="task, seed or request policy"):
        c._matching(manifest, reordered)
    changed_seed = {**manifest, "seed_base": 302}
    with pytest.raises(c.ComparisonError, match="task, seed or request policy"):
        c._matching(manifest, changed_seed)


def test_historical_gemma_replay_uses_registered_root_and_rejects_failed_child(
    monkeypatch: pytest.MonkeyPatch,
):
    expected = {"admission_eligible": True, "recorded_episodes": 12}

    def good(argv, **kwargs):
        assert argv[:2] == [sys.executable, "-c"]
        assert argv[-1] == str(c.GEMMA_OUTPUT / "pilot")
        assert kwargs["cwd"] == c.GEMMA_CODE_ROOT
        assert kwargs["env"]["PYTHONPATH"] == str(c.GEMMA_CODE_ROOT)
        assert kwargs["timeout"] == 30
        return subprocess.CompletedProcess(
            argv, 0, json.dumps(expected, sort_keys=True,
                                separators=(",", ":")) + "\n", "")

    monkeypatch.setattr(c.subprocess, "run", good)
    assert c._replay_historical_gemma() == expected

    def failed(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 1, "", "private failure withheld")

    monkeypatch.setattr(c.subprocess, "run", failed)
    with pytest.raises(c.ComparisonError, match="did not pass"):
        c._replay_historical_gemma()
