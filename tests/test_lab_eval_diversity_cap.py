"""Finite paired-cap source and denominator checks; no local model requests."""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from bench.flash_next_ab import lab_eval_diversity_cap as cap
from bench.flash_next_ab import manifest, transport


def _gate(plan: dict, cohort: str) -> dict:
    certificate = plan['runtime_certificates'][cohort]
    endpoint = plan['endpoints']['flash_next_mia']
    return {
        'schema_version': 'lab-model-eval-admission/v1', 'admitted': True,
        'cohort': cohort, 'window_id': 'qfn-ab-diversity-cap-test',
        'plan_sha256': manifest.sha256_json(plan),
        'certificate_sha256': certificate['parent_sha256'],
        'endpoint_identities': {'flash_next_mia': {key: endpoint[key]
            for key in ('served_model', 'artifact_sha256', 'runtime_sha256')}},
        'candidate_spec_sha256': certificate['candidate_spec_sha256'],
        'monitor_armed': True, 'controller_source_bundle_sha256': 'a' * 64,
        'ready_proof_sha256': 'b' * 64,
    }


def _freeze(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(cap, 'ARTIFACT_ROOT', tmp_path)
    path = tmp_path / 'cap-plan.json'
    frozen = cap.freeze_plan(path)
    assert frozen['declared_calls'] == 40
    return path


def test_exact_five_reused_tasks_alternate_cap_order_and_equal_timeouts():
    plan, cells = cap.build_plan()
    assert len(plan['declared_cells']) == 10
    assert plan['declared_call_count'] == 40
    assert plan['cohorts'] == ['flash']
    assert plan['endpoints']['flash_next_mia']['policies']['explore_medium'] == {
        'temperature': 1.0, 'top_p': .95, 'top_k': 20,
        'enable_thinking': True, 'reasoning_effort': 'medium',
    }
    for index, task_id in enumerate(cap.TASK_IDS):
        first, second = (cells[item] for item in plan['declared_cells'][2 * index:2 * index + 2])
        assert first.task_id == second.task_id == task_id
        assert [int(item.cell_id.split('/cap-')[1].split('/')[0]) for item in (first, second)] == (
            [384, 1536] if index % 2 == 0 else [1536, 384]
        )
        for item in (first, second):
            assert tuple(call.seed for call in item.calls) == (101, 211, 307, 401)
            assert tuple(call.timeout_s for call in item.calls) == (60.0, 60.0, 60.0, 20.0)
            assert item.calls[-1].messages_builder == 'diversity_validator_messages/v1'
            assert item.receipt() == plan['cell_receipts'][item.cell_id]


def test_all_forty_timeout_attempts_stay_in_denominator_and_raw_grade_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    path = _freeze(tmp_path, monkeypatch)

    def timeout(*args, **kwargs):
        raise TimeoutError('synthetic bounded model timeout')

    output = tmp_path / 'run-timeout'
    run = cap.run(path, cohort='flash', output_dir=output, runtime_budget_s=300,
                  admission_gate=_gate, cancel_event=threading.Event(), invoke_fn=timeout)
    assert run['status'] == 'complete'
    assert run['all_issued_calls_used_declared_timeout'] is True
    assert run['issued_call_count'] == 40
    replay = cap.replay_run(path, output / 'run.json')
    assert replay['status'] == 'source_bound_replay_passed'
    assert replay['private_calls_verified'] == 40
    assert replay['attempted_calls'] == 40
    assert replay['by_cap']['384']['generator_timeout'] == 15
    assert replay['by_cap']['1536']['generator_timeout'] == 15
    assert replay['by_cap']['384']['selector_timeout'] == 5
    assert replay['by_cap']['1536']['selector_timeout'] == 5
    assert replay['recorded_evaluator_elapsed_s'] >= 0
    for cap_budget in ('384', '1536'):
        arm = replay['by_cap'][cap_budget]
        assert arm['generator_finish_reason_histogram'] == {'transport_timeout': 15}
        assert arm['generator_completion_usage_covered_calls'] == 0
        assert arm['generator_reasoning_usage_covered_calls'] == 0
        assert arm['generator_completion_tokens_observed_sum'] == 0
        assert arm['total_call_wall_s'] >= 0
        assert arm['total_call_wall_s'] == pytest.approx(
            arm['generator_call_wall_s'] + arm['selector_call_wall_s']
        )

    raw = json.loads((output / 'run.json').read_text())
    raw['outcomes'][0]['passed'] = True
    (output / 'run.json').write_bytes(manifest.canonical_json(raw) + b'\n')
    assert cap.replay_run(path, output / 'run.json')['status'] == 'invalid'


def test_cancelled_first_generator_seals_partial_and_unissued_slots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    path = _freeze(tmp_path, monkeypatch)
    cancel = threading.Event()

    def stop(*args, **kwargs):
        cancel.set()
        raise transport.TransportCancelled('synthetic cancellation')

    output = tmp_path / 'run-cancelled'
    run = cap.run(path, cohort='flash', output_dir=output, runtime_budget_s=300,
                  admission_gate=_gate, cancel_event=cancel, invoke_fn=stop)
    assert run['status'] == 'aborted'
    assert run['issued_call_count'] == 1
    assert run['outcomes'][0]['status'] == 'cancelled'
    assert run['outcomes'][0]['grade']['details']['structured_output_diagnostics'] == []
    assert [row['status'] for row in run['outcomes'][1:]] == ['not_run'] * 9
    with pytest.raises(cap.DiversityCapError):
        cap.replay_run(path, output / 'run.json')


def test_cutoff_shortening_one_selector_timeout_invalidates_equal_budget_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    path = _freeze(tmp_path, monkeypatch)

    class Clock:
        value = 0.0
        attempted = 0

        def monotonic(self):
            return self.value

        def timeout(self, *args, **kwargs):
            self.attempted += 1
            if self.attempted == 39:
                self.value = 295.0
            raise TimeoutError('synthetic bounded model timeout')

    clock = Clock()
    output = tmp_path / 'run-shortened'
    run = cap.run(path, cohort='flash', output_dir=output, runtime_budget_s=300,
                  admission_gate=_gate, cancel_event=threading.Event(),
                  invoke_fn=clock.timeout, monotonic=clock.monotonic)
    assert clock.attempted == 40
    assert run['issued_call_count'] == 40
    assert run['all_issued_calls_used_declared_timeout'] is False
    assert run['status'] == 'aborted'
    with pytest.raises(cap.DiversityCapError):
        cap.replay_run(path, output / 'run.json')
