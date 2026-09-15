"""New quantitative game and one-file repair canaries under the lab controller.

These twelve development fixtures are distinct from the reused original 126.
They test instrument validity and coding execution, not market edge or novelty.
"""
from __future__ import annotations

import copy
import hashlib
import math
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from bench.weekly_upgrade_eval.manifest import Task
from bench.weekly_upgrade_eval.runner import InvocationResult, grade_task
from bench.weekly_upgrade_historical import runner as patch_wire
from bench.weekly_upgrade_historical import sandbox

from . import harness, manifest, transport
from .lab_eval_plan import _certificates
from .lab_eval_runner import _admission
from .private_evidence import validate_private_evidence

PLAN_SCHEMA = 'lab-model-fresh-plan/v1'
RUN_SCHEMA = 'lab-model-fresh-run/v1'
POLICY_SCIENCE = 'fresh_science_medium'
POLICY_CODING = 'fresh_coding_off'
SEED = 509
OUTPUT_SCIENCE = 1024
OUTPUT_CODING = 4096
TIMEOUT_SCIENCE = 60.0
TIMEOUT_CODING = 150.0
REPAIR_PATH = 'solver.py'
ROOT = Path(__file__).resolve().parents[2]
HISTORICAL_MANIFEST = ROOT / 'experiments/weekly_historical_coding_patch_wire_v1_2026-09-14.json'
HISTORICAL_SHA256 = 'ff6e3c57698694ed9e80838a5d982fa874923371895fa83f61e1063aa7d773d9'

SCIENCE = (
    ('FSG-001', 'zero_sum_equilibrium',
     'Solve the row-player zero-sum 2×2 payoff matrix [[2,0],[0,2]]. Return strict JSON with row_mixture, column_mixture, and value.',
     {'row_mixture': [0.5, 0.5], 'column_mixture': [0.5, 0.5], 'value': 1.0}),
    ('FSG-002', 'zero_sum_equilibrium',
     'Solve the row-player zero-sum 2×2 payoff matrix [[4,0],[0,1]]. Return strict JSON with row_mixture, column_mixture, and value.',
     {'row_mixture': [0.2, 0.8], 'column_mixture': [0.2, 0.8], 'value': 0.8}),
    ('FSG-003', 'external_regret',
     'Four rounds have action A payoffs [2,0,3,1] and B payoffs [0,3,1,2]. Chosen actions were B,A,B,A. Return strict JSON with chosen_total, best_fixed_total, total_external_regret, average_external_regret.',
     {'chosen_total': 2, 'best_fixed_total': 6, 'total_external_regret': 4, 'average_external_regret': 1.0}),
    ('FSG-004', 'external_regret',
     'Four rounds have action A payoffs [1,4,2,0] and B payoffs [3,0,1,5]. Chosen actions were A,B,A,B. Return strict JSON with chosen_total, best_fixed_total, total_external_regret, average_external_regret.',
     {'chosen_total': 8, 'best_fixed_total': 9, 'total_external_regret': 1, 'average_external_regret': 0.25}),
    ('FSG-005', 'repeated_pd_trace',
     'Three rounds of PD use T=5,R=3,P=1,S=0. Player1 is Tit-for-Tat (C first, then copy opponent previous action); player2 Always Defects. Return strict JSON with player1_actions, player2_actions, player1_total, player2_total.',
     {'player1_actions': ['C', 'D', 'D'], 'player2_actions': ['D', 'D', 'D'], 'player1_total': 2, 'player2_total': 7}),
    ('FSG-006', 'repeated_pd_trace',
     'Four rounds of PD use T=5,R=3,P=1,S=0. Player1 Always Defects; player2 Tit-for-Tat (C first, then copy opponent previous action). Return strict JSON with player1_actions, player2_actions, player1_total, player2_total.',
     {'player1_actions': ['D', 'D', 'D', 'D'], 'player2_actions': ['C', 'D', 'D', 'D'], 'player1_total': 8, 'player2_total': 3}),
)

CODING = (
    ('FCR-001', 'Round-trip fee is charged once per leg.',
     'def round_trip_bps(ask, bid, fee_bps):\n    return (bid - ask) / ask * 10000 - fee_bps\n',
     'from solver import round_trip_bps\n\ndef test_two_legs():\n    assert round_trip_bps(100, 101, 10) == 80\n\ndef test_flat_quotes():\n    assert round_trip_bps(100, 100, 5) == -10\n'),
    ('FCR-002', 'Inventory penalty is quadratic in normalized inventory.',
     'def inventory_cost(inventory, limit):\n    return abs(inventory) / limit\n',
     'from solver import inventory_cost\n\ndef test_half():\n    assert inventory_cost(-5, 10) == .25\n\ndef test_full():\n    assert inventory_cost(10, 10) == 1\n'),
    ('FCR-003', 'Reference size cannot exceed displayed depth or the cap.',
     'def risk_cap(depth, cap):\n    return max(depth, cap)\n',
     'from solver import risk_cap\n\ndef test_shallow():\n    assert risk_cap(3, 10) == 3\n\ndef test_cap():\n    assert risk_cap(20, 10) == 10\n'),
    ('FCR-004', 'Timestamp bucketing must use the completed hour floor.',
     'from datetime import timedelta\n\ndef hour_start(ts):\n    return ts.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)\n',
     'from datetime import datetime, timezone\nfrom solver import hour_start\n\ndef test_inside_hour():\n    assert hour_start(datetime(2026, 9, 15, 10, 31, tzinfo=timezone.utc)).hour == 10\n\ndef test_boundary():\n    assert hour_start(datetime(2026, 9, 15, 10, 0, tzinfo=timezone.utc)).hour == 10\n'),
    ('FCR-005', 'External regret is best fixed payoff minus chosen payoff.',
     'def external_regret(chosen_total, best_fixed_total):\n    return chosen_total - best_fixed_total\n',
     'from solver import external_regret\n\ndef test_positive():\n    assert external_regret(2, 6) == 4\n\ndef test_negative():\n    assert external_regret(10, 6) == -4\n'),
    ('FCR-006', 'Spread basis points use the quote midpoint denominator.',
     'def spread_bps(bid, ask):\n    return (ask - bid) / ask * 10000\n',
     'from solver import spread_bps\n\ndef test_midpoint():\n    assert spread_bps(99, 101) == 200\n\ndef test_flat():\n    assert spread_bps(100, 100) == 0\n'),
)


class FreshEvalError(ValueError):
    pass


def _fixture(cell_id: str) -> dict:
    for task_id, kind, prompt, expected in SCIENCE:
        if task_id == cell_id:
            grader = {'kind': kind, 'absolute_tolerance': 1e-6,
                      'expected': expected}
            messages = [
                {'role': 'system', 'content': 'Solve the stated finite game exactly. Return one raw JSON object and no prose.'},
                {'role': 'user', 'content': prompt},
            ]
            return {'cell_id': task_id, 'kind': 'science', 'messages': messages,
                    'grader': grader, 'max_tokens': OUTPUT_SCIENCE,
                    'timeout_s': TIMEOUT_SCIENCE}
    for task_id, title, base, tests in CODING:
        if task_id == cell_id:
            messages = [
                {'role': 'system', 'content': 'Return one raw unified diff for solver.py. Start with diff --git a/solver.py b/solver.py. Include exact --- and +++ headers, complete hunks, and a terminal newline. No Markdown, JSON, or prose.'},
                {'role': 'user', 'content': f'Fix this one-file Python bug: {title}\n\nCurrent solver.py:\n{base}\nThe immutable focused tests will execute the repaired function.'},
            ]
            return {'cell_id': task_id, 'kind': 'coding', 'messages': messages,
                    'base_source': base, 'base_sha256': manifest.sha256_json(base),
                    'test_source': tests, 'tests_sha256': manifest.sha256_json(tests),
                    'repair_path': REPAIR_PATH, 'expected_cases': 2,
                    'max_tokens': OUTPUT_CODING, 'timeout_s': TIMEOUT_CODING}
    raise FreshEvalError('unregistered fresh fixture')


def _policies(endpoint: str) -> dict:
    top_k = 64 if endpoint == 'resident_gemma' else 20
    return {
        POLICY_SCIENCE: {'temperature': 0.0, 'top_p': 1.0,
                         'top_k': top_k, 'enable_thinking': endpoint != 'resident_gemma',
                         **({'reasoning_effort': 'medium'} if endpoint != 'resident_gemma' else {})},
        POLICY_CODING: {'temperature': 0.2, 'top_p': .95,
                        'top_k': top_k, 'enable_thinking': False},
    }


def build_plan() -> tuple[dict, dict[str, dict]]:
    certificates, identities = _certificates()
    declared = [row[0] for row in SCIENCE] + [row[0] for row in CODING]
    fixtures = {cell_id: _fixture(cell_id) for cell_id in declared}
    endpoints = {name: {**identity, 'policies': _policies(name)}
                 for name, identity in identities.items()}
    plan = {
        'schema_version': PLAN_SCHEMA,
        'suite_id': 'lab-fresh-game-and-one-file-repair-development-20260915-v1',
        'cell_set': 'new_six_finite_games_six_one_file_repairs',
        'cohorts': ['resident', 'flash'],
        'runtime_certificates': certificates,
        'endpoints': endpoints,
        'call_routes': {
            'resident': {cell_id: ['resident_qwen' if fixtures[cell_id]['kind'] == 'science'
                                   else 'resident_gemma'] for cell_id in declared},
            'flash': {cell_id: ['flash_next_mia'] for cell_id in declared},
        },
        'declared_cells': declared,
        'cell_receipts': {
            cell_id: {key: value for key, value in fixture.items() if key not in
                      {'messages', 'base_source', 'test_source'}}
            | {'messages_sha256': manifest.sha256_json(fixture['messages']),
               'fixture_sha256': manifest.sha256_json(fixture)}
            for cell_id, fixture in fixtures.items()
        },
        'evaluator_source_bundle': {
            name: manifest.sha256_file(ROOT / name) for name in (
                'bench/flash_next_ab/lab_eval_fresh.py',
                'bench/flash_next_ab/lab_eval_plan.py',
                'bench/flash_next_ab/lab_eval_runner.py',
                'bench/flash_next_ab/lab_eval_replay.py',
                'bench/flash_next_ab/harness.py',
                'bench/flash_next_ab/manifest.py',
                'bench/flash_next_ab/transport.py',
                'bench/flash_next_ab/private_evidence.py',
                'bench/weekly_upgrade_eval/runner.py',
                'bench/weekly_upgrade_eval/manifest.py',
                'bench/weekly_upgrade_historical/runner.py',
                'bench/weekly_upgrade_historical/manifest.py',
                'bench/weekly_upgrade_historical/sandbox.py',
            )
        },
        'historical_sandbox_manifest_sha256': HISTORICAL_SHA256,
        'presentation_diagnostic': {
            'primary_raw_diff_parser_unchanged': True,
            'secondary_whole_fence_or_one_terminal_lf_only': True,
            'sandbox_reexecute_after_transform': True,
            'secondary_never_replaces_primary': True,
        },
        'hard_call_ceiling_s': 6 * TIMEOUT_SCIENCE + 6 * TIMEOUT_CODING,
        'promotion_authorized': False,
        'claim_limit': 'NEW_SYNTHETIC_DEVELOPMENT_CANARIES_NOT_TRADING_EVIDENCE',
    }
    return plan, fixtures


def load_plan(path: str | Path) -> tuple[dict, dict[str, dict], str]:
    raw, actual = harness._read_regular_file(
        path, label='frozen fresh canary plan', max_bytes=2_000_000,
    )
    plan = harness._strict_object(raw, 'frozen fresh canary plan')
    expected, fixtures = build_plan()
    if actual != Path(path).absolute() or plan != expected:
        raise FreshEvalError('fresh plan differs from code-owned fixtures/sources/certificates')
    return plan, fixtures, hashlib.sha256(raw).hexdigest()


def freeze_plan(path: str | Path) -> dict:
    plan, _ = build_plan()
    destination = Path(path)
    if destination.exists() or destination.parent.is_symlink():
        raise FreshEvalError('fresh plan output exists or redirected')
    raw = manifest.canonical_json(plan) + b'\n'
    with destination.open('xb') as handle:
        handle.write(raw)
    return {'path': str(destination), 'raw_sha256': hashlib.sha256(raw).hexdigest(),
            'plan_sha256': manifest.sha256_json(plan), 'declared_cells': 12}


def _science_grade(fixture: dict, content: str | None, status: str) -> dict:
    messages = fixture['messages']
    contract = fixture['grader']
    task = Task(
        id=fixture['cell_id'], family='game_theory', mode='chat',
        system=messages[0]['content'], prompt=messages[1]['content'],
        grader=contract, tools=(),
        input_sha256=manifest.sha256_json(messages),
        grader_sha256=manifest.sha256_json(contract),
    )
    grade = grade_task(task, InvocationResult(
        completion=content or '',
        failure_code=None if status == 'returned' else status,
    ))
    return {'passed': bool(grade.passed),
            'failure_code': None if grade.passed else grade.reason,
            'raw_contract_passed': bool(grade.passed),
            'substantive_passed': bool(grade.passed),
            'sandbox_executed': False}


def _coding_grade(fixture: dict, content: str | None) -> dict:
    parsed, parse_error = patch_wire._parse_patch_completion(
        content, REPAIR_PATH, patch_wire.PATCH_WIRE_SCHEMA_VERSION,
    )
    if parse_error:
        return {'passed': False, 'failure_code': parse_error,
                'raw_contract_passed': False, 'patch_applied': False,
                'substantive_passed': False, 'sandbox_executed': False}
    raw_identity, actual_identity = harness._read_regular_file(
        HISTORICAL_MANIFEST, label='historical sandbox identity', max_bytes=512_000,
    )
    if (actual_identity != HISTORICAL_MANIFEST.absolute()
            or hashlib.sha256(raw_identity).hexdigest() != HISTORICAL_SHA256):
        raise FreshEvalError('historical sandbox identity changed')
    historical = harness._strict_object(raw_identity, 'historical sandbox identity')
    identity = historical['sandbox_runtime']
    try:
        observed = sandbox.sandbox_runtime_identity(
            bwrap_path=identity['bubblewrap_path'],
            python_path=identity['python_path'],
        )
    except sandbox.SandboxUnavailable:
        return {'passed': False, 'failure_code': 'sandbox_runtime_unavailable',
                'raw_contract_passed': True, 'patch_applied': False,
                'substantive_passed': False, 'sandbox_executed': False}
    if observed != identity:
        return {'passed': False, 'failure_code': 'sandbox_runtime_drift',
                'raw_contract_passed': True, 'patch_applied': False,
                'substantive_passed': False, 'sandbox_executed': False}
    with tempfile.TemporaryDirectory(prefix='lab-fresh-repair-') as raw:
        workspace = Path(raw) / 'workspace'
        workspace.mkdir()
        (workspace / REPAIR_PATH).write_text(fixture['base_source'])
        test_path = workspace / 'test_solver.py'
        test_path.write_text(fixture['test_source'])
        test_path.chmod(0o444)
        patch = sandbox.apply_candidate_patch(
            workspace, allowed_path=REPAIR_PATH, patch=parsed['patch'],
            max_patch_bytes=32_768,
        )
        if not patch.valid:
            return {'passed': False, 'failure_code': patch.code,
                    'raw_contract_passed': True, 'patch_applied': False,
                    'substantive_passed': False, 'sandbox_executed': False,
                    'patch_sha256': patch.patch_sha256}
        try:
            grade = sandbox.run_grader(
                {'grader': {'test_node': 'test_solver.py', 'expected_cases': 2}},
                workspace, bwrap_path=identity['bubblewrap_path'],
                python_path=identity['python_path'], timeout_s=10,
                max_output_bytes=128_000,
            )
        except sandbox.SandboxUnavailable:
            return {'passed': False, 'failure_code': 'grader_unavailable',
                    'raw_contract_passed': True, 'patch_applied': True,
                    'substantive_passed': False, 'sandbox_executed': False,
                    'patch_sha256': patch.patch_sha256}
    return {'passed': grade.passed,
            'failure_code': None if grade.passed else 'grader_failed',
            'raw_contract_passed': True, 'patch_applied': True,
            'substantive_passed': grade.passed, 'sandbox_executed': True,
            'patch_sha256': patch.patch_sha256,
            'sandbox_result_sha256': manifest.sha256_json(grade.__dict__),
            'sandbox_cases_passed': grade.counts['passed'],
            'sandbox_cases_expected': 2}


def _grade(fixture: dict, content: str | None, status: str) -> dict:
    if fixture['kind'] == 'science':
        return _science_grade(fixture, content, status)
    if status != 'returned':
        return {'passed': False, 'failure_code': status,
                'raw_contract_passed': False, 'patch_applied': False,
                'substantive_passed': False, 'sandbox_executed': False}
    return _coding_grade(fixture, content)


def run(
    plan_path: str | Path, *, cohort: str, output_dir: str | Path,
    runtime_budget_s: float, admission_gate: Any, cancel_event: Any,
    invoke_fn: Any = transport.complete, monotonic: Any = time.monotonic,
    run_id: str | None = None,
) -> dict:
    if (cohort not in {'resident', 'flash'} or not callable(admission_gate)
            or not callable(getattr(cancel_event, 'is_set', None))
            or not callable(invoke_fn) or type(runtime_budget_s) not in (int, float)
            or not math.isfinite(runtime_budget_s) or not 0 < runtime_budget_s <= 1800):
        raise FreshEvalError('fresh run lacks registered bounded controller')
    plan, fixtures, plan_raw_sha = load_plan(plan_path)
    gate = _admission(plan, cohort, admission_gate(plan, cohort))
    if cancel_event.is_set():
        raise FreshEvalError('controller cancelled before output creation')
    output = harness._output_dir(output_dir)
    if output.parent.is_symlink() or not output.parent.is_dir():
        raise FreshEvalError('fresh output parent absent or redirected')
    output.mkdir(mode=0o700)
    start, deadline = monotonic(), monotonic() + runtime_budget_s
    run_id = run_id or f'lab-fresh-{cohort}-{uuid.uuid4().hex[:16]}'
    outcomes, ordinal, stopped = [], 0, False
    for cell_id in plan['declared_cells']:
        fixture = fixtures[cell_id]
        before = monotonic()
        if stopped or cancel_event.is_set() or before >= deadline:
            stopped = True
            outcome = {'cell_id': cell_id, 'kind': fixture['kind'],
                       'status': 'not_run', 'passed': False, 'wall_s': 0.0,
                       'failure_code': 'controller_cancelled' if cancel_event.is_set()
                                       else 'runtime_budget_exhausted',
                       'calls': [], 'grade': None}
        else:
            private = []
            endpoint_name = plan['call_routes'][cohort][cell_id][0]
            identity = plan['endpoints'][endpoint_name]
            policy_id = POLICY_SCIENCE if fixture['kind'] == 'science' else POLICY_CODING
            arm = {'routes': [{
                'role': 'generator' if fixture['kind'] == 'science' else 'coding',
                'endpoint_name': endpoint_name,
                'served_model': identity['served_model'],
                'artifact_sha256': identity['artifact_sha256'],
                'runtime_sha256': identity['runtime_sha256'],
                'policies': identity['policies'],
            }]}
            spec = harness.CallSpec(
                call_index=0, call_id=f'{run_id}/{cell_id}#0',
                role='generator' if fixture['kind'] == 'science' else 'coding',
                policy_id=policy_id, seed=SEED,
                max_tokens=fixture['max_tokens'], timeout_s=fixture['timeout_s'],
                required=True, messages=tuple(fixture['messages']),
            )
            call = harness._invoke_call(
                spec, arm=arm, deadline=deadline, invoke_fn=invoke_fn,
                cancel_event=cancel_event, monotonic=monotonic,
                evidence_sink=private.append,
            )
            descriptor = harness._persist_private_call(
                output, ordinal=ordinal,
                evidence={**private[-1], 'run_id': run_id,
                          'cohort': cohort, 'cell_id': cell_id},
            )
            ordinal += 1
            grade = _grade(fixture, call.content, call.status)
            passed = grade['passed'] and call.status == 'returned'
            failure_code = None if passed else grade['failure_code'] or call.receipt['failure_code']
            outcome = {
                'cell_id': cell_id, 'kind': fixture['kind'],
                'status': call.status, 'passed': passed,
                'wall_s': max(0.0, monotonic() - before),
                'failure_code': failure_code,
                'messages_sha256': manifest.sha256_json(fixture['messages']),
                'fixture_sha256': manifest.sha256_json(fixture),
                'calls': [copy.deepcopy(call.receipt)],
                'grade': {'grader_id': fixture['kind'] + '/fresh-v1',
                          'passed': passed, 'failure_code': failure_code,
                          'details': {**grade,
                              '_private_call_evidence': {
                                  'schema_version': harness.PRIVATE_INDEX_SCHEMA,
                                  'artifacts': [descriptor],
                              }}},
            }
        outcomes.append(outcome)
        harness._write_json(output / 'checkpoint.json', {
            'schema_version': 'lab-model-fresh-checkpoint/v1',
            'run_id': run_id, 'plan_raw_sha256': plan_raw_sha,
            'recorded_cells': [row['cell_id'] for row in outcomes],
        })
    status = 'aborted' if stopped or cancel_event.is_set() else 'complete'
    counts = {name: max((call['usage']['prompt_tokens'] for row in outcomes
                         for call in row['calls'] if call['endpoint_name'] == name
                         and isinstance(call.get('usage'), dict)
                         and type(call['usage'].get('prompt_tokens')) is int), default=None)
              for name in plan['endpoints'] if name in {
                  route for routes in plan['call_routes'][cohort].values()
                  for route in routes}}
    result = {
        'schema_version': RUN_SCHEMA, 'run_id': run_id, 'cohort': cohort,
        'status': status, 'plan_raw_sha256': plan_raw_sha,
        'plan_sha256': manifest.sha256_json(plan),
        'runtime_certificate': copy.deepcopy(plan['runtime_certificates'][cohort]),
        'controller_admission': gate,
        'candidate_variant_id': plan['runtime_certificates']['flash']['candidate_spec_id']
                                if cohort == 'flash' else 'resident-role-bundle',
        'configured_context_tokens_by_endpoint': {
            name: plan['endpoints'][name]['max_model_len'] for name in counts},
        'measured_prompt_tokens_max_by_endpoint': counts,
        'declared_cells': list(plan['declared_cells']), 'outcomes': outcomes,
        'elapsed_s': max(0.0, monotonic() - start),
        'promotion_authorized': False, 'claim_limit': plan['claim_limit'],
    }
    harness._write_json(output / 'run.json', result)
    (output / 'checkpoint.json').unlink(missing_ok=True)
    return result


def replay_run(plan_path: str | Path, run_path: str | Path) -> dict:
    plan, fixtures, plan_raw_sha = load_plan(plan_path)
    raw, actual = harness._read_regular_file(
        run_path, label='completed fresh lab run', max_bytes=8_000_000,
    )
    run = harness._strict_object(raw, 'completed fresh lab run')
    cohort = run.get('cohort')
    if (run.get('schema_version') != RUN_SCHEMA or cohort not in {'resident', 'flash'}
            or run.get('status') != 'complete'
            or run.get('plan_raw_sha256') != plan_raw_sha
            or run.get('plan_sha256') != manifest.sha256_json(plan)
            or run.get('runtime_certificate') != plan['runtime_certificates'][cohort]
            or [row.get('cell_id') for row in run.get('outcomes', [])] != plan['declared_cells']):
        raise FreshEvalError('fresh run is partial or source/certificate drifted')
    _admission(plan, cohort, run['controller_admission'])
    evidence = validate_private_evidence(run, actual.parent)
    mismatches = []
    normalized_attempted = normalized_passes = 0
    from .lab_eval_replay import _normalized_diff
    for item in run['outcomes']:
        fixture = fixtures[item['cell_id']]
        call, descriptor = item['calls'][0], item['grade']['details']['_private_call_evidence']['artifacts'][0]
        private_raw, _ = harness._read_regular_file(
            actual.parent / descriptor['metadata_path'],
            label='private fresh call metadata', max_bytes=harness.MAX_PRIVATE_METADATA_BYTES,
        )
        private = harness._strict_object(private_raw, 'private fresh call metadata')
        endpoint_name = plan['call_routes'][cohort][item['cell_id']][0]
        endpoint = plan['endpoints'][endpoint_name]
        policy_id = POLICY_SCIENCE if fixture['kind'] == 'science' else POLICY_CODING
        if (private['request']['messages'] != fixture['messages']
                or private['request']['endpoint_name'] != endpoint_name
                or private['request']['served_model'] != endpoint['served_model']
                or private['request']['artifact_sha256'] != endpoint['artifact_sha256']
                or private['request']['resolved_policy'] != endpoint['policies'][policy_id]
                or private['request']['max_tokens'] != fixture['max_tokens']
                or private['request']['seed'] != SEED):
            raise FreshEvalError('fresh private request differs from frozen fixture/arm')
        content = private['response']['content'] if item['status'] == 'returned' else None
        grade = _grade(fixture, content, item['status'])
        failure = None if grade['passed'] else grade['failure_code'] or call['failure_code']
        if grade['passed'] != item['passed'] or failure != item['failure_code']:
            mismatches.append({'cell_id': item['cell_id'], 'kind': 'primary_grade_difference'})
        if fixture['kind'] == 'coding' and item['status'] == 'returned':
            normalized_attempted += 1
            normalized, changes = _normalized_diff(content)
            if changes:
                normalized_passes += int(_coding_grade(fixture, normalized)['passed'])
    return {
        'schema_version': 'lab-model-fresh-grade-replay/v1',
        'run_id': run['run_id'], 'cohort': cohort,
        'run_raw_sha256': hashlib.sha256(raw).hexdigest(),
        'private_calls_verified': evidence['calls_verified'],
        'private_streams_verified': evidence['response_streams_verified'],
        'primary_cells_replayed': len(run['outcomes']),
        'primary_grade_mismatches': mismatches,
        'primary_replay_passed': len(run['outcomes']) == 12 and not mismatches,
        'normalization_diagnostic': {
            'coding_returned_attempted': normalized_attempted,
            'sandbox_passes_after_predeclared_transform': normalized_passes,
            'never_replaces_primary_score': True,
        },
        'private_content_exported': False, 'promotion_authorized': False,
    }
