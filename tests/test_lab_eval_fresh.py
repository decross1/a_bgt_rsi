"""New finite-game oracle and real one-file sandbox canaries; no model calls."""
from __future__ import annotations

import difflib
import json
import threading
from pathlib import Path

import pytest

from bench.flash_next_ab import lab_eval_fresh as fresh
from bench.flash_next_ab import manifest


def _known_patch(before: str, after: str) -> str:
    return 'diff --git a/solver.py b/solver.py\n' + ''.join(difflib.unified_diff(
        before.splitlines(keepends=True), after.splitlines(keepends=True),
        fromfile='a/solver.py', tofile='b/solver.py',
    ))


def _gate(plan: dict, cohort: str) -> dict:
    cert = plan['runtime_certificates'][cohort]
    names = {route for routes in plan['call_routes'][cohort].values()
             for route in routes}
    return {
        'schema_version': 'lab-model-eval-admission/v1', 'admitted': True,
        'cohort': cohort, 'window_id': 'qfn-ab-fresh-test',
        'plan_sha256': manifest.sha256_json(plan),
        'certificate_sha256': cert['parent_sha256'] if cohort == 'flash' else cert['receipt_sha256'],
        'endpoint_identities': {
            name: {key: plan['endpoints'][name][key]
                   for key in ('served_model', 'artifact_sha256', 'runtime_sha256')}
            for name in names
        },
        'candidate_spec_sha256': cert['candidate_spec_sha256'] if cohort == 'flash' else None,
        'monitor_armed': True,
        'controller_source_bundle_sha256': 'a' * 64,
        'ready_proof_sha256': 'b' * 64,
    }


def test_six_new_finite_game_oracles_and_twelve_routes():
    plan, fixtures = fresh.build_plan()
    assert len(fixtures) == len(plan['declared_cells']) == 12
    assert plan['hard_call_ceiling_s'] == 1260
    assert {plan['call_routes']['flash'][cell_id][0]
            for cell_id in plan['declared_cells']} == {'flash_next_mia'}
    for task_id, _, _, expected in fresh.SCIENCE:
        fixture = fixtures[task_id]
        assert fresh._science_grade(fixture, json.dumps(expected), 'returned')['passed'] is True
        assert fresh._science_grade(fixture, '{}', 'returned')['passed'] is False


@pytest.mark.parametrize('task_id,old,new', [
    ('FCR-001', '- fee_bps', '- 2 * fee_bps'),
    ('FCR-002', 'abs(inventory) / limit', '(inventory / limit) ** 2'),
    ('FCR-003', 'max(depth, cap)', 'min(max(depth, 0), cap)'),
    ('FCR-004', ' + timedelta(hours=1)', ''),
    ('FCR-005', 'chosen_total - best_fixed_total', 'best_fixed_total - chosen_total'),
    ('FCR-006', '/ ask * 10000', '/ ((ask + bid) / 2) * 10000'),
])
def test_each_new_repair_runs_two_focus_cases_in_existing_bwrap_sandbox(task_id, old, new):
    fixture = fresh._fixture(task_id)
    before = fixture['base_source']
    assert old in before
    result = fresh._coding_grade(fixture, _known_patch(before, before.replace(old, new)))
    assert result['raw_contract_passed'] is True
    assert result['patch_applied'] is True
    assert result['sandbox_executed'] is True
    assert result['sandbox_cases_passed'] == 2
    assert result['passed'] is True


def test_fresh_plan_and_all_attempted_timeout_denominator(tmp_path: Path):
    path = tmp_path / 'plan.json'
    fresh.freeze_plan(path)
    assert len(fresh.load_plan(path)[1]) == 12

    def timeout(*args, **kwargs):
        raise TimeoutError('synthetic local timeout')

    result = fresh.run(
        path, cohort='resident', output_dir=tmp_path / 'fresh-run',
        runtime_budget_s=60, admission_gate=_gate,
        cancel_event=threading.Event(), invoke_fn=timeout,
    )
    assert result['status'] == 'complete'
    assert len(result['outcomes']) == 12
    assert all(row['status'] == 'timeout' for row in result['outcomes'])
    replay = fresh.replay_run(path, tmp_path / 'fresh-run' / 'run.json')
    assert replay['primary_replay_passed'] is True
    assert replay['private_calls_verified'] == 12
