"""Frozen lab evaluation route and denominator tests; no model calls."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import pytest

from bench.flash_next_ab import adapters, harness, manifest, transport
from bench.flash_next_ab import lab_eval_plan as plan_mod
from bench.flash_next_ab import lab_eval_replay as replay
from bench.flash_next_ab import lab_eval_runner as runner


def _gate(plan: dict, cohort: str) -> dict:
    names = {name for routes in plan['call_routes'][cohort].values() for name in routes}
    cert = plan['runtime_certificates'][cohort]
    return {
        'schema_version': 'lab-model-eval-admission/v1',
        'admitted': True, 'cohort': cohort,
        'plan_sha256': manifest.sha256_json(plan),
        'certificate_sha256': cert['parent_sha256'] if cohort == 'flash' else cert['receipt_sha256'],
        'endpoint_identities': {
            name: {key: plan['endpoints'][name][key]
                   for key in ('served_model', 'artifact_sha256', 'runtime_sha256')}
            for name in names
        },
        'candidate_spec_sha256': cert['candidate_spec_sha256'] if cohort == 'flash' else None,
        'monitor_armed': True, 'window_id': 'lab-eval-test-window',
        'controller_source_bundle_sha256': 'a' * 64,
        'ready_proof_sha256': 'b' * 64,
    }


class CancelAfterFirst:
    stopped = False

    def is_set(self) -> bool:
        return self.stopped


def _fake_complete(cancel: CancelAfterFirst, *, stop_after_first: bool = True):
    def invoke(endpoint, messages, *, policy, max_tokens, timeout_s, seed,
               tools, cancel_event):
        assert cancel_event is cancel
        body = transport.request_body(endpoint, messages, policy, max_tokens, seed, tools)
        request_sha = hashlib.sha256(transport.canonical(body)).hexdigest()
        rid = 'chatcmpl-lab-test'
        first = {'id': rid, 'model': endpoint.served_model, 'choices': [
            {'index': 0, 'delta': {'content': '{}'}, 'finish_reason': 'stop'}]}
        second = {'id': rid, 'model': endpoint.served_model, 'choices': [],
                  'usage': {'prompt_tokens': 2, 'completion_tokens': 2, 'total_tokens': 4}}
        events = [json.dumps(first, separators=(',', ':')),
                  json.dumps(second, separators=(',', ':')), '[DONE]']
        raw = b''.join(b'data: ' + event.encode() + b'\n\n' for event in events)
        accumulator = transport.StreamAccumulator(endpoint.served_model)
        for event in events:
            accumulator.accept(event)
        response = accumulator.result()
        response['request_sha256'] = request_sha
        response['response_stream_sha256'] = hashlib.sha256(raw).hexdigest()
        response['private_evidence'] = transport._private_response_evidence(
            accumulator, raw, response_bytes=len(raw))
        if stop_after_first:
            cancel.stopped = True
        return response
    return invoke


def test_new_plan_reuses_exact_126_sources_and_routes_science_to_qwen():
    plan, cells = plan_mod.build_plan()
    assert len(cells) == len(plan['declared_cells']) == 126
    assert sum(len(cell.calls) for cell in cells.values()) == 145
    assert plan['hard_call_ceiling_s'] == 9740
    assert plan['promotion_authorized'] is False
    assert plan['runtime_certificates']['flash']['candidate_spec_id'].endswith('v2opt-v1')
    for cell_id in plan['declared_cells']:
        family = cells[cell_id].family
        endpoints = plan['call_routes']['resident'][cell_id]
        if family in {'topic', 'context', 'historical'}:
            assert set(endpoints) == {'resident_gemma'}
        assert set(plan['call_routes']['flash'][cell_id]) == {'flash_next_mia'}
    science = next(cell for cell in cells.values()
                   if cell.family == 'objective' and cell.calls[0].role == 'generator')
    assert plan['call_routes']['resident'][science.cell_id] == ['resident_qwen']
    assert plan['endpoints']['resident_gemma']['policies']['science_medium']['enable_thinking'] is False
    assert plan['endpoints']['flash_next_mia']['policies']['science_medium']['reasoning_effort'] == 'medium'


def test_role_effort_keeps_actual_medium_to_xhigh_retry_on_both_arms():
    plan, cells = plan_mod.build_plan()
    originals = {cell.cell_id: cell for cell in adapters.load_cells(families=('role_effort',))}
    selected = [cell for cell in cells.values()
                if cell.family == 'role_effort' and cell.condition == 'adaptive'
                and cell.calls[0].role in {'evidence', 'execution'}]
    assert selected
    for cell in selected:
        assert [call.policy_id for call in cell.calls] == [
            call.policy_id for call in originals[cell.cell_id].calls
        ] == ['critic_medium', 'critic_current']
        assert plan['call_routes']['resident'][cell.cell_id] == ['resident_qwen'] * 2
        assert plan['call_routes']['flash'][cell.cell_id] == ['flash_next_mia'] * 2
        for endpoint_name in ('resident_qwen', 'flash_next_mia'):
            policies = plan['endpoints'][endpoint_name]['policies']
            assert policies['critic_medium']['reasoning_effort'] == 'medium'
            assert policies['critic_current']['reasoning_effort'] == 'xhigh'

        issued = []

        def invoke(spec, issued=issued):
            issued.append(spec)
            return adapters.CallResult(
                spec, 'returned', '{}', (),
                {'usage': {'completion_tokens': 0}, 'response_id': f'test-{len(issued)}',
                 'endpoint_name': 'resident_qwen', 'response_model': 'qwen3.8-27b-nvfp4-mtp',
                 'wall_s': 0.01},
            )

        result = adapters.execute_cell(cell, invoke)
        assert [call.policy_id for call in issued] == ['critic_medium', 'critic_current']
        assert result.details['conditional_escalation_triggered'] is True
        assert result.details['existing_grade']['escalated'] is True

    critics = [cell for cell in cells.values() if cell.family == 'role_effort'
               and cell.calls[0].role == 'critic' and cell.condition in {'xhigh', 'adaptive'}]
    assert critics
    assert all(cell.calls[0].policy_id == 'critic_current' for cell in critics)
    assert all(plan['call_routes']['resident'][cell.cell_id] == ['resident_qwen']
               for cell in critics)


def test_adaptive_effort_second_call_is_privately_bound_and_replays(tmp_path: Path):
    plan, cells = plan_mod.build_plan()
    cell = next(cell for cell in cells.values() if cell.family == 'role_effort'
                and cell.condition == 'adaptive' and cell.calls[0].role == 'evidence')
    cancel = CancelAfterFirst()
    output = tmp_path / 'private-adaptive'
    output.mkdir(mode=0o700)
    ordinal = 0

    def persist(source_cell, evidence):
        nonlocal ordinal
        descriptor = harness._persist_private_call(
            output, ordinal=ordinal,
            evidence={'schema_version': evidence.pop('schema_version'),
                      'run_id': 'adaptive-private-test', 'cohort': 'resident',
                      'cell_id': source_cell.cell_id, **evidence},
        )
        ordinal += 1
        return descriptor

    outcome = harness._execute_outcome(
        cell, 'resident', arm=runner._arm_for_cell(plan, 'resident', cell.cell_id, cell),
        deadline=time.monotonic() + 120,
        invoke_fn=_fake_complete(cancel, stop_after_first=False),
        cancel_event=cancel, monotonic=time.monotonic, persist_evidence=persist,
    )
    assert [call['policy_id'] for call in outcome['calls']] == [
        'critic_medium', 'critic_current',
    ]
    assert outcome['status'] == 'returned'
    metadata = replay._private_calls(outcome, output)
    assert metadata[1]['request']['resolved_policy']['reasoning_effort'] == 'xhigh'
    graded, transformations = replay._grade(
        cell, outcome, metadata, plan=plan, cohort='resident', normalize_diff=False,
    )
    assert transformations == []
    assert graded.passed == outcome['passed']


def test_frozen_plan_rehashes_sources_and_rejects_tamper(tmp_path: Path):
    path = tmp_path / 'plan.json'
    receipt = plan_mod.freeze_plan(path)
    loaded, cells, raw_sha = plan_mod.load_plan(path)
    assert receipt['raw_sha256'] == raw_sha
    assert len(cells) == 126
    value = dict(loaded)
    value['hard_call_ceiling_s'] = 100
    path.write_bytes(manifest.canonical_json(value) + b'\n')
    with pytest.raises(plan_mod.LabPlanError, match='code-owned'):
        plan_mod.load_plan(path)


def test_controller_gate_binds_endpoint_and_runtime_certificate():
    plan, _ = plan_mod.build_plan()
    gate = _gate(plan, 'flash')
    assert runner._admission(plan, 'flash', gate)['admitted'] is True
    gate['endpoint_identities']['flash_next_mia']['artifact_sha256'] = '0' * 64
    with pytest.raises(runner.LabRunError, match='admission differs'):
        runner._admission(plan, 'flash', gate)


def test_cancelled_prefix_preserves_all_126_declared_cells(tmp_path: Path):
    path = tmp_path / 'plan.json'
    plan_mod.freeze_plan(path)
    cancel = CancelAfterFirst()
    result = runner.run(
        path, cohort='resident', output_dir=tmp_path / 'resident-run',
        runtime_budget_s=300, admission_gate=_gate,
        cancel_event=cancel, invoke_fn=_fake_complete(cancel),
    )
    assert result['status'] == 'aborted'
    assert len(result['outcomes']) == len(result['declared_cells']) == 126
    assert result['outcomes'][0]['status'] == 'returned'
    assert all(row['status'] == 'not_run' for row in result['outcomes'][1:])
    assert result['outcomes'][0]['grade']['details']['_private_call_evidence']['artifacts']
    assert (tmp_path / 'resident-run' / 'run.json').is_file()


def test_independent_replay_accepts_all_attempted_timeout_denominator(tmp_path: Path):
    path = tmp_path / 'plan.json'
    plan_mod.freeze_plan(path)

    def timeout(*args, **kwargs):
        raise TimeoutError('synthetic bounded transport timeout')

    result = runner.run(
        path, cohort='resident', output_dir=tmp_path / 'timeout-run',
        runtime_budget_s=300, admission_gate=_gate,
        cancel_event=CancelAfterFirst(), invoke_fn=timeout,
    )
    assert result['status'] == 'complete'
    assert len(result['outcomes']) == 126
    assert all(row['status'] == 'timeout' for row in result['outcomes'])
    checked = replay.replay_run(path, tmp_path / 'timeout-run' / 'run.json')
    assert checked['primary_replay_passed'] is True
    assert checked['primary_cells_replayed'] == 126
    assert checked['private_calls_verified'] > 0
