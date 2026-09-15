"""Context support, source drift and all-declared denominator checks."""
from __future__ import annotations

import threading
from pathlib import Path

import pytest

from bench.flash_next_ab import lab_eval_context as context
from bench.flash_next_ab import manifest
from bench.flash_next_ab.private_evidence import validate_private_evidence


def _gate(plan: dict, cohort: str) -> dict:
    names = {name for routes in plan['call_routes'][cohort].values() for name in routes}
    cert = plan['runtime_certificates'][cohort]
    return {
        'schema_version': 'lab-model-eval-admission/v1', 'admitted': True,
        'cohort': cohort, 'window_id': 'qfn-ab-context-test',
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


def test_36_packets_fit_qualified_total_context_with_2048_output():
    plan, rows = context.build_plan()
    assert len(rows) == len(plan['declared_cells']) == 36
    assert plan['hard_call_ceiling_s'] == 5760
    assert set(plan['call_routes']['resident']) == set(plan['call_routes']['flash'])
    for row in rows.values():
        cap = row['server_context_tokens']
        assert row['actual_prompt_tokens_by_endpoint']['resident_gemma'] + 2048 <= cap
        assert row['actual_prompt_tokens_by_endpoint']['flash_next_mia'] + 2048 <= cap
        if cap == 32768:
            assert 'resident_qwen' not in row['supported_endpoints']
        else:
            assert row['actual_prompt_tokens_by_endpoint']['resident_qwen'] + 2048 <= cap


def test_context_plan_rejects_packet_or_plan_drift(tmp_path: Path):
    path = tmp_path / 'plan.json'
    context.freeze_plan(path)
    assert len(context.load_plan(path)[1]) == 36
    value = context.load_plan(path)[0]
    value['cell_receipts'][value['declared_cells'][0]]['timeout_s'] = 5
    path.write_bytes(manifest.canonical_json(value) + b'\n')
    with pytest.raises(context.ContextEvalError, match='exact packet'):
        context.load_plan(path)


def test_all_36_attempted_transport_timeouts_keep_complete_denominator(tmp_path: Path):
    path = tmp_path / 'plan.json'
    context.freeze_plan(path)

    def timeout(*args, **kwargs):
        raise TimeoutError('synthetic local timeout')

    result = context.run(
        path, cohort='resident', output_dir=tmp_path / 'resident-context',
        runtime_budget_s=120, admission_gate=_gate,
        cancel_event=threading.Event(), invoke_fn=timeout,
    )
    assert result['status'] == 'complete'
    assert len(result['outcomes']) == 36
    assert all(row['status'] == 'timeout' for row in result['outcomes'])
    checked = validate_private_evidence(result, tmp_path / 'resident-context')
    assert checked['calls_verified'] == 36
    replay = context.replay_run(path, tmp_path / 'resident-context' / 'run.json')
    assert replay['primary_replay_passed'] is True
    assert replay['objective_cells_replayed'] == 36
