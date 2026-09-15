"""Run a separate Qwen/Mia matched 8K/16K TOTAL-context follow-on."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import time
import uuid
from pathlib import Path
from typing import Any

from . import followon_context, harness, manifest, transport
from . import lab_eval_context_packs as packs
from .lab_eval_plan import _certificates
from .lab_eval_runner import _admission
from .private_evidence import validate_private_evidence

PACK = Path('/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-15/lab-context-capacity-packets-v1.json')
PACK_RAW_SHA256 = '4a6203e9c28ff8f7b74ec21b4d530aceb1430172a049a57912a386f3626b49f9'
PLAN_SCHEMA = 'lab-model-context-qwen-plan/v1'
RUN_SCHEMA = 'lab-model-context-qwen-run/v1'
COHORTS = ('resident', 'flash')
ROLE = 'evidence'
POLICY_ID = 'deterministic_context_off'
SEED = 71
TIMEOUTS = {8192: 90.0, 16384: 150.0, 32768: 240.0}


class ContextEvalError(ValueError):
    pass


def _pack() -> dict[str, Any]:
    raw, actual = harness._read_regular_file(
        PACK, label='matched lab context packet', max_bytes=8_000_000,
    )
    value = harness._strict_object(raw, 'matched lab context packet')
    if (actual != PACK.absolute() or hashlib.sha256(raw).hexdigest() != PACK_RAW_SHA256
            or value.get('schema_version') != packs.SCHEMA
            or value.get('source_manifest_sha256') != packs.SOURCE_SHA256
            or value.get('builder_source_sha256') != manifest.sha256_file(packs.__file__)
            or value.get('helper_source_sha256') != manifest.sha256_file(packs.original.__file__)
            or value.get('output_reserve_tokens') != 2048):
        raise ContextEvalError('matched packet source, builder or output reserve changed')
    rows = value.get('cells')
    expected = {(task['id'], cap, placement)
                for task in packs._source() for cap in packs.CAPACITIES
                for placement in packs.PLACEMENTS}
    actual_matrix = set()
    if not isinstance(rows, list) or len(rows) != 36:
        raise ContextEvalError('36-cell context matrix changed')
    for row in rows:
        if not isinstance(row, dict):
            raise ContextEvalError('context row is malformed')
        identity = (row.get('source_task_id'), row.get('server_context_tokens'), row.get('placement'))
        actual_matrix.add(identity)
        if (row.get('cell_id') != f'{identity[0]}-total{identity[1]}-{identity[2]}'
                or row.get('input_target_tokens') != packs.INPUT_TARGET.get(identity[1])
                or row.get('output_reserve_tokens') != 2048
                or row.get('messages_sha256') != manifest.sha256_json(row.get('messages'))
                or row.get('grader_sha256') != manifest.sha256_json(row.get('grader'))
                or row.get('actual_prompt_tokens_by_endpoint', {}).get('resident_gemma', 10**9) + 2048 > identity[1]
                or row.get('actual_prompt_tokens_by_endpoint', {}).get('flash_next_mia', 10**9) + 2048 > identity[1]):
            raise ContextEvalError('context message, grader or qualified capacity changed')
        if identity[1] < 32768 and (
                row.get('actual_prompt_tokens_by_endpoint', {}).get('resident_qwen', 10**9) + 2048 > identity[1]
                or 'resident_qwen' not in row.get('supported_endpoints', [])):
            raise ContextEvalError('Qwen 8K/16K support preflight changed')
        if identity[1] == 32768 and 'resident_qwen' in row.get('supported_endpoints', []):
            raise ContextEvalError('unqualified resident Qwen 32K claim')
    if actual_matrix != expected:
        raise ContextEvalError('context task/capacity/placement matrix changed')
    return value


def _policy(endpoint: str) -> dict[str, Any]:
    return {
        'temperature': 0.0, 'top_p': 1.0,
        'top_k': 64 if endpoint == 'resident_gemma' else 20,
        'enable_thinking': False,
    }


def build_plan() -> tuple[dict[str, Any], dict[str, dict]]:
    packet = _pack()
    certificates, identities = _certificates()
    selected = ('resident_qwen', 'flash_next_mia')
    endpoints = {
        name: {**identities[name], 'policies': {POLICY_ID: _policy(name)}}
        for name in selected
    }
    selected_rows = [row for row in packet['cells'] if row['server_context_tokens'] <= 16384]
    if (len(selected_rows) != 24
            or any('resident_qwen' not in row['supported_endpoints'] for row in selected_rows)):
        raise ContextEvalError('qualified Qwen 8K/16K packet subset changed')
    rows = {row['cell_id']: row for row in selected_rows}
    declared = [row['cell_id'] for row in selected_rows]
    plan = {
        'schema_version': PLAN_SCHEMA,
        'suite_id': 'lab-qwen-mia-total8k16k-public-development-20260915-v1',
        'cell_set': 'public_four_evidence_tasks_three_positions',
        'cohorts': list(COHORTS),
        'packet_path': str(PACK), 'packet_raw_sha256': PACK_RAW_SHA256,
        'runtime_certificates': certificates,
        'endpoints': endpoints,
        'call_routes': {
            'resident': {cell_id: ['resident_qwen'] for cell_id in declared},
            'flash': {cell_id: ['flash_next_mia'] for cell_id in declared},
        },
        'declared_cells': declared,
        'cell_receipts': {
            cell_id: {
                'source_task_id': row['source_task_id'],
                'server_context_tokens': row['server_context_tokens'],
                'placement': row['placement'],
                'messages_sha256': row['messages_sha256'],
                'grader_sha256': row['grader_sha256'],
                'actual_prompt_tokens_by_endpoint': row['actual_prompt_tokens_by_endpoint'],
                'max_output_tokens': 2048,
                'timeout_s': TIMEOUTS[row['server_context_tokens']],
            }
            for cell_id, row in rows.items()
        },
        'evaluator_source_bundle': {
            name: manifest.sha256_file(packs.ROOT / name)
            for name in (
                'bench/flash_next_ab/lab_eval_context_qwen.py',
                'bench/flash_next_ab/lab_eval_context_packs.py',
                'bench/flash_next_ab/lab_eval_plan.py',
                'bench/flash_next_ab/lab_eval_runner.py',
                'bench/flash_next_ab/followon_context.py',
                'bench/flash_next_ab/followon_context_packs.py',
                'bench/flash_next_ab/harness.py',
                'bench/flash_next_ab/manifest.py',
                'bench/flash_next_ab/transport.py',
                'bench/flash_next_ab/private_evidence.py',
                'bench/weekly_upgrade_eval/runner.py',
            )
        },
        'hard_call_ceiling_s': sum(TIMEOUTS[row['server_context_tokens']]
                                   for row in rows.values()),
        'promotion_authorized': False,
        'claim_limit': 'PUBLIC_DEVELOPMENT_QWEN_8K_16K_ONLY_NOT_HELDOUT',
    }
    return plan, rows


def load_plan(path: str | Path) -> tuple[dict[str, Any], dict[str, dict], str]:
    raw, actual = harness._read_regular_file(
        path, label='frozen lab context plan', max_bytes=1_000_000,
    )
    expected, rows = build_plan()
    value = harness._strict_object(raw, 'frozen lab context plan')
    if actual != Path(path).absolute() or value != expected:
        raise ContextEvalError('context plan differs from exact packet, source or runtime')
    return value, rows, hashlib.sha256(raw).hexdigest()


def freeze_plan(path: str | Path) -> dict[str, Any]:
    plan, _ = build_plan()
    destination = Path(path)
    if destination.exists() or destination.parent.is_symlink():
        raise ContextEvalError('context plan output exists or redirected')
    raw = manifest.canonical_json(plan) + b'\n'
    with destination.open('xb') as handle:
        handle.write(raw)
    return {'path': str(destination), 'raw_sha256': hashlib.sha256(raw).hexdigest(),
            'plan_sha256': manifest.sha256_json(plan), 'declared_cells': 24}


def run(
    plan_path: str | Path, *, cohort: str, output_dir: str | Path,
    runtime_budget_s: float, admission_gate: Any, cancel_event: Any,
    invoke_fn: Any = transport.complete, monotonic: Any = time.monotonic,
    run_id: str | None = None,
) -> dict[str, Any]:
    if (cohort not in COHORTS or not callable(admission_gate)
            or not callable(getattr(cancel_event, 'is_set', None))
            or not callable(invoke_fn) or type(runtime_budget_s) not in (int, float)
            or not math.isfinite(runtime_budget_s) or not 0 < runtime_budget_s <= 3000):
        raise ContextEvalError('controller gate, cohort or bounded work cap missing')
    plan, rows, plan_raw_sha = load_plan(plan_path)
    gate = _admission(plan, cohort, admission_gate(plan, cohort))
    if cancel_event.is_set():
        raise ContextEvalError('controller cancelled before output creation')
    output = harness._output_dir(output_dir)
    if output.parent.is_symlink() or not output.parent.is_dir():
        raise ContextEvalError('context output parent absent or redirected')
    output.mkdir(mode=0o700)
    run_id = run_id or f'lab-context-{cohort}-{uuid.uuid4().hex[:16]}'
    start = monotonic()
    deadline = start + runtime_budget_s
    outcomes = []
    ordinal = 0
    endpoint_name = 'resident_qwen' if cohort == 'resident' else 'flash_next_mia'
    identity = plan['endpoints'][endpoint_name]
    arm = {'routes': [{
        'role': ROLE, 'endpoint_name': endpoint_name,
        'served_model': identity['served_model'],
        'artifact_sha256': identity['artifact_sha256'],
        'runtime_sha256': identity['runtime_sha256'],
        'policies': identity['policies'],
    }]}
    stopped = False
    for cell_id in plan['declared_cells']:
        row = rows[cell_id]
        before = monotonic()
        if stopped or cancel_event.is_set() or before >= deadline:
            stopped = True
            outcome = {
                'cell_id': cell_id, 'status': 'not_run', 'passed': None,
                'failure_code': 'controller_cancelled' if cancel_event.is_set() else 'runtime_budget_exhausted',
                'wall_s': 0.0, 'calls': [], 'grade': None,
            }
        else:
            private: list[dict] = []
            spec = harness.CallSpec(
                call_index=0, call_id=f'{run_id}/{cell_id}#0', role=ROLE,
                policy_id=POLICY_ID, seed=SEED, max_tokens=2048,
                timeout_s=TIMEOUTS[row['server_context_tokens']], required=True,
                messages=tuple(copy.deepcopy(row['messages'])),
            )
            call = harness._invoke_call(
                spec, arm=arm, deadline=deadline,
                invoke_fn=invoke_fn, cancel_event=cancel_event,
                monotonic=monotonic, evidence_sink=private.append,
            )
            evidence = {**private[-1], 'run_id': run_id,
                        'cohort': cohort, 'cell_id': cell_id}
            descriptor = harness._persist_private_call(
                output, ordinal=ordinal, evidence=evidence,
            )
            ordinal += 1
            grade = followon_context._grade({**row, 'id': cell_id}, call)
            outcome = {
                'cell_id': cell_id, 'status': call.status,
                'passed': grade['passed'] if call.status == 'returned' else False,
                'failure_code': None if call.status == 'returned' and grade['passed']
                                else grade['reason_code'] if call.status == 'returned'
                                else call.receipt['failure_code'],
                'wall_s': max(0.0, monotonic() - before),
                'calls': [copy.deepcopy(call.receipt)],
                'grade': {
                    'grader_id': 'objective_evidence_attribution/v1',
                    'passed': grade['passed'] if call.status == 'returned' else False,
                    'failure_code': None if call.status == 'returned' and grade['passed']
                                    else grade['reason_code'],
                    'details': {
                        '_private_call_evidence': {
                            'schema_version': harness.PRIVATE_INDEX_SCHEMA,
                            'artifacts': [descriptor],
                        },
                    },
                },
            }
        outcome.update({
            'source_task_id': row['source_task_id'],
            'server_context_tokens': row['server_context_tokens'],
            'actual_prompt_tokens_preflight': row['actual_prompt_tokens_by_endpoint'][endpoint_name],
            'output_reserve_tokens': 2048, 'placement': row['placement'],
            'messages_sha256': row['messages_sha256'],
            'grader_sha256': row['grader_sha256'],
        })
        outcomes.append(outcome)
        harness._write_json(output / 'checkpoint.json', {
            'schema_version': 'lab-model-context-checkpoint/v1',
            'run_id': run_id, 'plan_raw_sha256': plan_raw_sha,
            'recorded_cells': [item['cell_id'] for item in outcomes],
        })
    status = 'aborted' if stopped or cancel_event.is_set() else 'complete'
    used = [call['usage']['prompt_tokens'] for item in outcomes
            for call in item['calls'] if isinstance(call.get('usage'), dict)
            and type(call['usage'].get('prompt_tokens')) is int]
    result = {
        'schema_version': RUN_SCHEMA, 'run_id': run_id, 'cohort': cohort,
        'status': status, 'plan_raw_sha256': plan_raw_sha,
        'plan_sha256': manifest.sha256_json(plan),
        'packet_raw_sha256': PACK_RAW_SHA256,
        'runtime_certificate': copy.deepcopy(plan['runtime_certificates'][cohort]),
        'controller_admission': gate,
        'candidate_variant_id': plan['runtime_certificates']['flash']['candidate_spec_id']
                                if cohort == 'flash' else 'resident-qwen',
        'configured_context_tokens': identity['max_model_len'],
        'measured_prompt_tokens_max': max(used) if used else None,
        'output_reserve_tokens': 2048,
        'declared_cells': list(plan['declared_cells']), 'outcomes': outcomes,
        'elapsed_s': max(0.0, monotonic() - start),
        'promotion_authorized': False,
        'claim_limit': plan['claim_limit'],
    }
    harness._write_json(output / 'run.json', result)
    (output / 'checkpoint.json').unlink(missing_ok=True)
    return result


def replay_run(plan_path: str | Path, run_path: str | Path) -> dict[str, Any]:
    """Recheck private SSE and unchanged objective/citation grades for all 24."""
    plan, rows, plan_raw_sha = load_plan(plan_path)
    raw, actual = harness._read_regular_file(
        run_path, label='completed lab context run', max_bytes=8_000_000,
    )
    run = harness._strict_object(raw, 'completed lab context run')
    cohort = run.get('cohort')
    if (run.get('schema_version') != RUN_SCHEMA or cohort not in COHORTS
            or run.get('status') != 'complete'
            or run.get('plan_raw_sha256') != plan_raw_sha
            or run.get('plan_sha256') != manifest.sha256_json(plan)
            or run.get('runtime_certificate') != plan['runtime_certificates'][cohort]
            or run.get('packet_raw_sha256') != PACK_RAW_SHA256
            or run.get('declared_cells') != plan['declared_cells']
            or [item.get('cell_id') for item in run.get('outcomes', [])] != plan['declared_cells']
            or run.get('promotion_authorized') is not False):
        raise ContextEvalError('context run is incomplete or source/certificate changed')
    _admission(plan, cohort, run.get('controller_admission'))
    evidence = validate_private_evidence(run, actual.parent)
    endpoint_name = 'resident_qwen' if cohort == 'resident' else 'flash_next_mia'
    identity = plan['endpoints'][endpoint_name]
    mismatches = []
    for item in run['outcomes']:
        cell_id = item['cell_id']
        row = rows[cell_id]
        calls = item['calls']
        artifacts = item['grade']['details']['_private_call_evidence']['artifacts']
        if len(calls) != 1 or len(artifacts) != 1:
            raise ContextEvalError('completed context cell lacks one attempted call')
        call_receipt, descriptor = calls[0], artifacts[0]
        raw_metadata, _ = harness._read_regular_file(
            actual.parent / descriptor['metadata_path'],
            label='private context call metadata',
            max_bytes=harness.MAX_PRIVATE_METADATA_BYTES,
        )
        metadata = harness._strict_object(raw_metadata, 'private context call metadata')
        request = metadata['request']
        if (request['endpoint_name'] != endpoint_name
                or request['served_model'] != identity['served_model']
                or request['artifact_sha256'] != identity['artifact_sha256']
                or request['resolved_policy'] != identity['policies'][POLICY_ID]
                or request['messages'] != row['messages']
                or request['max_tokens'] != 2048 or request['seed'] != SEED
                or call_receipt['status'] != item['status']):
            raise ContextEvalError('context call differs from frozen arm/messages/policy')
        spec = harness.CallSpec(
            call_index=0, call_id=call_receipt['call_id'], role=ROLE,
            policy_id=POLICY_ID, seed=SEED, max_tokens=2048,
            timeout_s=TIMEOUTS[row['server_context_tokens']], required=True,
            messages=tuple(row['messages']),
        )
        response = metadata['response']
        call = harness.CallResult(
            spec, call_receipt['status'],
            response['content'] if call_receipt['status'] == 'returned' else None,
            tuple(response['tool_calls']), call_receipt,
        )
        grade = followon_context._grade({**row, 'id': cell_id}, call)
        passed = grade['passed'] if call.status == 'returned' else False
        failure = (None if passed else grade['reason_code'] if call.status == 'returned'
                   else call_receipt['failure_code'])
        if passed != item['passed'] or failure != item['failure_code']:
            mismatches.append({'cell_id': cell_id, 'kind': 'objective_grade_difference'})
    return {
        'schema_version': 'lab-model-context-qwen-grade-replay/v1',
        'run_id': run['run_id'], 'cohort': cohort,
        'run_raw_sha256': hashlib.sha256(raw).hexdigest(),
        'plan_raw_sha256': plan_raw_sha,
        'private_calls_verified': evidence['calls_verified'],
        'private_streams_verified': evidence['response_streams_verified'],
        'objective_cells_replayed': len(run['outcomes']),
        'grade_mismatches': mismatches,
        'primary_replay_passed': len(run['outcomes']) == 24 and not mismatches,
        'private_content_exported': False,
        'promotion_authorized': False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--freeze-plan', type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(freeze_plan(args.freeze_plan), sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
