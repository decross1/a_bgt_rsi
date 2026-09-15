"""Prospective five-task Mia diversity cap pair under an exact lab window.

The old 126-cell result and diversity manifest remain immutable. This module
runs ten reused development condition-cells (40 calls) with equal timeouts;
it publishes only content-free counts after raw-response and grade replay.
"""
from __future__ import annotations

import argparse
import copy
import dataclasses
import hashlib
import importlib
import math
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from . import adapters, harness, manifest, transport
from .lab_eval_plan import _certificates, definitions
from .lab_eval_replay import _grade as replay_grade
from .lab_eval_replay import _private_calls
from .lab_eval_runner import _admission
from .private_evidence import validate_private_evidence

ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_ROOT = Path('/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-15/lab-eight-hour')
SOURCE_MANIFEST = ROOT / 'experiments/diversity_selection_v1_2026-09-14.json'
SOURCE_MANIFEST_SHA256 = '0cf6b1e426f1572df3f2b7433e48f776c87137258041ac5c3c4e09150916cc02'
PRIMARY_PLAN = ARTIFACT_ROOT / 'primary-model-comparison-v2.plan.json'
PRIMARY_PLAN_SHA256 = '9616a6f5b982585570fb1bcd6de76aa754fcb722225f90ecded3d737838ec0b8'
PRIMARY_RUN = ARTIFACT_ROOT / 'model-windows/qfn-ab-lab-primary-20260915-b.flash/evaluation/run.json'
PRIMARY_RUN_SHA256 = '68193bdb172405ea07022b5e8f25de19a4a384825717dc6dc597f0d06eb28667'
TASK_IDS = (
    'DIV1-GT-ASSURANCE-002', 'DIV1-GT-CONDORCET-002',
    'DIV1-GT-DELEGATION-002', 'DIV1-GT-COORDINATION-002',
    'DIV1-GT-COALITION-002',
)
PLAN_SCHEMA = 'lab-mia-diversity-cap-plan/v1'
RUN_SCHEMA = 'lab-mia-diversity-cap-run/v1'
REPLAY_SCHEMA = 'lab-mia-diversity-cap-replay/v1'
CAPS = (384, 1536)
GENERATOR_TIMEOUT_S = 60.0
SELECTOR_TIMEOUT_S = 20.0
MAX_EVALUATOR_S = 2200
HARD_CALL_CEILING_S = 2000
CLAIM_LIMIT = 'REUSED_FIVE_TASK_DEVELOPMENT_CAP_DIAGNOSTIC_NOT_HELDOUT'
SOURCE_FILES = (
    'bench/flash_next_ab/lab_eval_diversity_cap.py',
    'bench/flash_next_ab/lab_eval_plan.py',
    'bench/flash_next_ab/lab_eval_runner.py',
    'bench/flash_next_ab/lab_eval_replay.py',
    'bench/flash_next_ab/adapters.py',
    'bench/flash_next_ab/harness.py',
    'bench/flash_next_ab/manifest.py',
    'bench/flash_next_ab/transport.py',
    'bench/flash_next_ab/private_evidence.py',
    'bench/flash_next_ab/followon_qualification_admission.py',
    'bench/flash_next_ab/followon_canaries.py',
    'bench/flash_next_ab/followon_profiles.py',
    'bench/weekly_upgrade_diversity/manifest.py',
    'bench/weekly_upgrade_diversity/runner.py',
    'bench/weekly_upgrade_diversity/graders.py',
    'bench/weekly_upgrade_eval/structured_output.py',
)


class DiversityCapError(ValueError):
    """The prospective plan, call evidence, or grade replay is incomplete."""


def _source_bytes(path: Path, sha256: str, label: str, ceiling: int) -> bytes:
    raw, actual = harness._read_regular_file(path, label=label, max_bytes=ceiling)
    if actual != path.absolute() or hashlib.sha256(raw).hexdigest() != sha256:
        raise DiversityCapError(f'{label} raw source changed')
    return raw


def _source_plan() -> dict[str, Any]:
    _source_bytes(SOURCE_MANIFEST, SOURCE_MANIFEST_SHA256, 'diversity source manifest', 512_000)
    return harness._strict_object(
        _source_bytes(PRIMARY_PLAN, PRIMARY_PLAN_SHA256, 'admitted primary plan', 2_000_000),
        'admitted primary plan',
    )


def _source_run() -> None:
    _source_bytes(PRIMARY_RUN, PRIMARY_RUN_SHA256, 'admitted primary raw run', 16_000_000)


def _definitions() -> list[adapters.CellDefinition]:
    old_plan = _source_plan()
    old = [cell for cell in definitions()
           if cell.family == 'diversity' and cell.condition == 'diverse_select']
    if tuple(cell.task_id for cell in old) != TASK_IDS or len(old) != 5:
        raise DiversityCapError('five diversity source tasks changed order')
    pairs = []
    for index, original in enumerate(old):
        if (original.receipt() != old_plan['cell_receipts'].get(original.cell_id)
                or tuple(call.seed for call in original.calls) != (101, 211, 307, 401)
                or tuple(call.policy_id for call in original.calls)
                != ('explore_medium', 'explore_medium', 'explore_medium', 'deterministic_off')
                or tuple(call.max_tokens for call in original.calls) != (384, 384, 384, 128)
                or tuple(call.timeout_s for call in original.calls) != (20.0, 20.0, 20.0, 20.0)
                or original.calls[-1].messages_builder != 'diversity_validator_messages/v1'):
            raise DiversityCapError('source call/prompt/grader contract differs from frozen primary')
        order = CAPS if index % 2 == 0 else tuple(reversed(CAPS))
        for cap in order:
            cell_id = f'diversity-cap/{original.task_id}/cap-{cap}/seed-401'
            calls = tuple(dataclasses.replace(
                call, call_id=f'{cell_id}#{call.call_index}',
                max_tokens=cap if call.role == 'generator' else 128,
                timeout_s=GENERATOR_TIMEOUT_S if call.role == 'generator'
                          else SELECTOR_TIMEOUT_S,
            ) for call in original.calls)
            pairs.append(dataclasses.replace(original, cell_id=cell_id, calls=calls))
    if len(pairs) != 10 or len({cell.cell_id for cell in pairs}) != 10:
        raise DiversityCapError('cap-pair task/cell denominator differs')
    return pairs


def _policies() -> dict[str, dict[str, Any]]:
    return {
        'explore_medium': {'temperature': 1.0, 'top_p': .95, 'top_k': 20,
                           'enable_thinking': True, 'reasoning_effort': 'medium'},
        'deterministic_off': {'temperature': 0.0, 'top_p': 1.0, 'top_k': 20,
                              'enable_thinking': False},
    }


def build_plan() -> tuple[dict[str, Any], dict[str, adapters.CellDefinition]]:
    _source_run()
    refs, identities = _certificates()
    cells = _definitions()
    declared = [cell.cell_id for cell in cells]
    endpoint = {**identities['flash_next_mia'], 'policies': _policies()}
    plan = {
        'schema_version': PLAN_SCHEMA,
        'suite_id': 'mia-diversity-cap384-cap1536-five-reused-task-pairs-20260915-v1',
        'cell_set': 'reused_five_diverse_select_tasks_two_caps_equal_timeout',
        'cohorts': ['flash'],
        'runtime_certificates': {'flash': refs['flash']},
        'endpoints': {'flash_next_mia': endpoint},
        'call_routes': {'flash': {cell_id: ['flash_next_mia'] * 4 for cell_id in declared}},
        'declared_cells': declared,
        'cell_receipts': {cell.cell_id: cell.receipt() for cell in cells},
        'evaluator_source_bundle': {
            name: manifest.sha256_file(ROOT / name) for name in SOURCE_FILES
        },
        'source_manifest_raw_sha256': SOURCE_MANIFEST_SHA256,
        'historical_primary_plan_raw_sha256': PRIMARY_PLAN_SHA256,
        'historical_primary_run_raw_sha256': PRIMARY_RUN_SHA256,
        'generator_timeout_s': GENERATOR_TIMEOUT_S,
        'selector_timeout_s': SELECTOR_TIMEOUT_S,
        'caps': list(CAPS),
        'hard_call_ceiling_s': HARD_CALL_CEILING_S,
        'declared_call_count': 40,
        'claim_limit': CLAIM_LIMIT,
        'promotion_authorized': False,
    }
    return plan, {cell.cell_id: cell for cell in cells}


def load_plan(path: str | Path) -> tuple[dict[str, Any], dict[str, adapters.CellDefinition], str]:
    raw, actual = harness._read_regular_file(
        path, label='frozen Mia diversity-cap plan', max_bytes=2_000_000,
    )
    plan = harness._strict_object(raw, 'frozen Mia diversity-cap plan')
    expected, cells = build_plan()
    if actual != Path(path).absolute() or plan != expected:
        raise DiversityCapError('diversity-cap plan differs from exact tasks/source/runtime')
    return plan, cells, hashlib.sha256(raw).hexdigest()


def freeze_plan(path: str | Path) -> dict[str, Any]:
    destination = Path(path).absolute()
    if (not destination.is_relative_to(ARTIFACT_ROOT)
            or destination.exists() or destination.parent.is_symlink()
            or not destination.parent.is_dir()):
        raise DiversityCapError('plan destination is outside registered artifact root or exists')
    plan, _ = build_plan()
    raw = manifest.canonical_json(plan) + b'\n'
    with destination.open('xb') as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    return {'path': str(destination), 'raw_sha256': hashlib.sha256(raw).hexdigest(),
            'plan_sha256': manifest.sha256_json(plan), 'declared_cells': 10,
            'declared_calls': 40}


def _content_free_details(details: dict[str, Any]) -> dict[str, Any]:
    """Retain objective numbers while excluding canonical proposal values."""
    keep = (
        'proposal_count', 'valid_count', 'valid_unique_count', 'valid_indices',
        'selected_index', 'selected_valid', 'selection_correct',
        'recovered_from_invalid_candidates', 'expected_selected_index',
        'selection_exact', 'task_success',
    )
    grade = details.get('existing_grade')
    if not isinstance(grade, dict) or any(key not in grade for key in keep):
        raise DiversityCapError('objective diversity grade is incomplete')
    diagnostics = details.get('structured_output_diagnostics')
    if not isinstance(diagnostics, list) or len(diagnostics) > 4:
        raise DiversityCapError('structured output diagnostics are incomplete')
    return {
        'existing_grade': {key: copy.deepcopy(grade[key]) for key in keep},
        'structured_output_diagnostics': [
            {'failure_code': item.get('failure_code')} if isinstance(item, dict) else None
            for item in diagnostics
        ],
        'proposal_protocol_valid': copy.deepcopy(details.get('proposal_protocol_valid')),
        'dynamic_validator_messages': details.get('dynamic_validator_messages'),
    }


def run(
    plan_path: str | Path, *, cohort: str, output_dir: str | Path,
    runtime_budget_s: float, admission_gate: Any, cancel_event: Any,
    invoke_fn: Any = transport.complete, monotonic: Any = time.monotonic,
    run_id: str | None = None,
) -> dict[str, Any]:
    if (cohort != 'flash' or not callable(admission_gate)
            or not callable(getattr(cancel_event, 'is_set', None))
            or not callable(invoke_fn) or type(runtime_budget_s) not in (int, float)
            or not math.isfinite(runtime_budget_s)
            or not 0 < runtime_budget_s <= MAX_EVALUATOR_S):
        raise DiversityCapError('cap diagnostic lacks registered bounded controller')
    plan, cells, plan_raw_sha = load_plan(plan_path)
    gate = _admission(plan, cohort, admission_gate(plan, cohort))
    if cancel_event.is_set():
        raise DiversityCapError('controller cancelled before output creation')
    output = harness._output_dir(output_dir)
    if output.parent.is_symlink() or not output.parent.is_dir():
        raise DiversityCapError('cap-diagnostic output parent absent or redirected')
    output.mkdir(mode=0o700)
    run_id = run_id or f'lab-mia-diversity-cap-{uuid.uuid4().hex[:16]}'
    if not isinstance(run_id, str) or not run_id:
        raise DiversityCapError('run identity is malformed')
    start = monotonic()
    deadline = start + float(runtime_budget_s)
    endpoint = plan['endpoints']['flash_next_mia']
    arm = {'cohort': 'flash', 'routes': [
        {'role': role, 'endpoint_name': 'flash_next_mia',
         'served_model': endpoint['served_model'],
         'artifact_sha256': endpoint['artifact_sha256'],
         'runtime_sha256': endpoint['runtime_sha256'],
         'policies': endpoint['policies']}
        for role in ('generator', 'validator')
    ]}
    ordinal = 0
    outcomes: list[dict[str, Any]] = []
    stopped = False

    def persist(cell: adapters.CellDefinition, evidence: dict[str, Any]) -> dict[str, Any]:
        nonlocal ordinal
        complete = {'schema_version': evidence.pop('schema_version'),
                    'run_id': run_id, 'cohort': cohort, 'cell_id': cell.cell_id,
                    **evidence}
        descriptor = harness._persist_private_call(output, ordinal=ordinal, evidence=complete)
        ordinal += 1
        return descriptor

    def checkpoint() -> None:
        harness._write_json(output / 'checkpoint.json', {
            'schema_version': 'lab-mia-diversity-cap-checkpoint/v1',
            'run_id': run_id, 'plan_raw_sha256': plan_raw_sha,
            'recorded_cells': [row['cell_id'] for row in outcomes],
            'issued_private_calls': ordinal,
            'elapsed_s': max(0.0, monotonic() - start),
        })

    checkpoint()
    for cell_id in plan['declared_cells']:
        cell = cells[cell_id]
        if stopped or cancel_event.is_set() or monotonic() >= deadline:
            stopped = True
            reason = 'controller_cancelled' if cancel_event.is_set() else 'runtime_budget_exhausted'
            row = harness._not_run_outcome(cell, cohort, failure_code=reason, error=reason)
        else:
            row = harness._execute_outcome(
                cell, cohort, arm=arm, deadline=deadline,
                invoke_fn=invoke_fn, cancel_event=cancel_event,
                monotonic=monotonic, persist_evidence=persist,
            )
            details = row['grade']['details']
            private_index = details.pop('_private_call_evidence')
            if 'existing_grade' in details:
                public_details = _content_free_details(details)
            else:
                public_details = {'grader_error_type': details.get('exception_type')}
            public_details['_private_call_evidence'] = private_index
            row['grade']['details'] = public_details
            if row['status'] == 'cancelled':
                stopped = True
        outcomes.append(row)
        checkpoint()
    call_count = sum(len(row['calls']) for row in outcomes)
    full_call_timeouts = all(
        call.get('timeout_s') == spec.timeout_s
        for row in outcomes for spec, call in zip(cells[row['cell_id']].calls, row['calls'])
    )
    status = ('complete' if not stopped and not cancel_event.is_set()
              and full_call_timeouts and call_count == 40
              and all(row['status'] != 'not_run' for row in outcomes)
              else 'aborted')
    used = [call['usage']['prompt_tokens'] for row in outcomes
            for call in row['calls'] if isinstance(call.get('usage'), dict)
            and type(call['usage'].get('prompt_tokens')) is int]
    result = {
        'schema_version': RUN_SCHEMA, 'run_id': run_id,
        'cohort': cohort, 'status': status,
        'suite_id': plan['suite_id'], 'cell_set': plan['cell_set'],
        'plan_raw_sha256': plan_raw_sha,
        'plan_sha256': manifest.sha256_json(plan),
        'evaluator_source_bundle': copy.deepcopy(plan['evaluator_source_bundle']),
        'runtime_certificate': copy.deepcopy(plan['runtime_certificates'][cohort]),
        'controller_admission': gate,
        'candidate_variant_id': plan['runtime_certificates']['flash']['candidate_spec_id'],
        'configured_context_tokens': endpoint['max_model_len'],
        'measured_prompt_tokens_max': max(used) if used else None,
        'runtime_budget_s': float(runtime_budget_s),
        'elapsed_s': max(0.0, monotonic() - start),
        'declared_cells': list(plan['declared_cells']),
        'declared_call_count': 40, 'issued_call_count': call_count,
        'all_issued_calls_used_declared_timeout': full_call_timeouts,
        'outcomes': outcomes,
        'promotion_authorized': False, 'claim_limit': CLAIM_LIMIT,
    }
    harness._write_json(output / 'run.json', result)
    (output / 'checkpoint.json').unlink(missing_ok=True)
    return result


def replay_run(plan_path: str | Path, run_path: str | Path) -> dict[str, Any]:
    """Bind all forty raw calls and re-execute the original diversity grader."""
    plan, cells, plan_raw_sha = load_plan(plan_path)
    raw, actual = harness._read_regular_file(
        run_path, label='completed Mia diversity-cap run', max_bytes=16_000_000,
    )
    run = harness._strict_object(raw, 'completed Mia diversity-cap run')
    if (run.get('schema_version') != RUN_SCHEMA or run.get('cohort') != 'flash'
            or run.get('status') != 'complete'
            or run.get('plan_raw_sha256') != plan_raw_sha
            or run.get('plan_sha256') != manifest.sha256_json(plan)
            or run.get('evaluator_source_bundle') != plan['evaluator_source_bundle']
            or run.get('runtime_certificate') != plan['runtime_certificates']['flash']
            or run.get('candidate_variant_id')
            != plan['runtime_certificates']['flash']['candidate_spec_id']
            or run.get('declared_cells') != plan['declared_cells']
            or run.get('declared_call_count') != 40
            or run.get('issued_call_count') != 40
            or run.get('all_issued_calls_used_declared_timeout') is not True
            or [row.get('cell_id') for row in run.get('outcomes', [])] != plan['declared_cells']
            or run.get('promotion_authorized') is not False
            or run.get('claim_limit') != CLAIM_LIMIT):
        raise DiversityCapError('only a complete exact-source forty-call run can replay')
    _admission(plan, 'flash', run.get('controller_admission'))
    evidence = validate_private_evidence(run, actual.parent)
    if evidence['calls_verified'] != 40:
        raise DiversityCapError('forty distinct private call receipts are required')
    summary = {str(cap): {
        'condition_cells': 0, 'generator_calls': 0,
        'generator_returned': 0, 'generator_timeout': 0,
        'length_reasoning_only_empty': 0, 'empty_visible_final': 0,
        'valid_proposals': 0, 'selector_calls': 0,
        'selector_returned': 0, 'selector_timeout': 0,
        'total_call_wall_s': 0.0, 'generator_call_wall_s': 0.0,
        'selector_call_wall_s': 0.0,
        'generator_completion_tokens_observed_sum': 0,
        'generator_completion_usage_covered_calls': 0,
        'generator_reasoning_tokens_observed_sum': 0,
        'generator_reasoning_usage_covered_calls': 0,
        'generator_finish_reason_histogram': {},
        'underlying_objective_success': 0,
        'creditable_protocol_pass': 0,
    } for cap in CAPS}
    mismatches: list[dict[str, str]] = []
    pair_rows: dict[str, dict[str, bool]] = {task_id: {} for task_id in TASK_IDS}
    for row in run['outcomes']:
        cell = cells[row['cell_id']]
        cap = int(cell.cell_id.split('/cap-')[1].split('/')[0])
        group = summary[str(cap)]
        group['condition_cells'] += 1
        if (row.get('source') != cell.source or row.get('adapter') != cell.adapter
                or row.get('grader') != cell.grader or row.get('condition') != 'diverse_select'
                or row.get('cohort') != 'flash' or row.get('task_id') != cell.task_id
                or row.get('family') != cell.family or row.get('seed') != cell.seed
                or row.get('grade', {}).get('grader_id') != cell.grader['id']
                or len(row.get('calls', [])) != 4):
            raise DiversityCapError('condition call/source/grader identity differs')
        statuses = {call.get('status') for call in row['calls']}
        observed_status = ('cancelled' if 'cancelled' in statuses else
                           'timeout' if 'timeout' in statuses else
                           'error' if 'error' in statuses else 'returned')
        if row.get('status') != observed_status:
            mismatches.append({'cell_id': cell.cell_id, 'kind': 'aggregate_call_status'})
        metadata = _private_calls(row, actual.parent)
        for spec, call, private in zip(cell.calls, row['calls'], metadata, strict=True):
            wall = call.get('wall_s')
            if type(wall) not in (int, float) or not math.isfinite(wall) or wall < 0:
                mismatches.append({'cell_id': cell.cell_id, 'kind': 'unbounded_call_wall'})
                wall = 0.0
            group['total_call_wall_s'] += wall
            if (call.get('max_tokens') != spec.max_tokens
                    or call.get('timeout_s') != spec.timeout_s
                    or private['request'].get('timeout_s') != spec.timeout_s):
                mismatches.append({'cell_id': cell.cell_id, 'kind': 'call_budget_or_timeout'})
            response = private['response']
            if spec.role == 'generator':
                group['generator_calls'] += 1
                group['generator_call_wall_s'] += wall
                group['generator_returned'] += int(call['status'] == 'returned')
                group['generator_timeout'] += int(call['status'] == 'timeout')
                finish = call.get('finish_reason') if call['status'] == 'returned' else None
                if call['status'] == 'returned':
                    finish_key = (finish if finish in {'stop', 'length', 'tool_calls'}
                                  else 'other_returned_finish_reason')
                elif call['status'] in {'timeout', 'error', 'cancelled'}:
                    finish_key = f"transport_{call['status']}"
                else:
                    finish_key = 'other_transport_status'
                    mismatches.append({'cell_id': cell.cell_id, 'kind': 'generator_status'})
                histogram = group['generator_finish_reason_histogram']
                histogram[finish_key] = histogram.get(finish_key, 0) + 1
                content = response.get('content')
                empty = isinstance(content, str) and not content.strip()
                if call['status'] == 'returned' and empty:
                    group['empty_visible_final'] += 1
                usage = response.get('usage') or {}
                details = usage.get('completion_tokens_details') or {}
                reasoning = details.get('reasoning_tokens')
                total = usage.get('completion_tokens')
                if type(total) is int and total >= 0:
                    group['generator_completion_usage_covered_calls'] += 1
                    group['generator_completion_tokens_observed_sum'] += total
                if type(reasoning) is int and reasoning >= 0:
                    group['generator_reasoning_usage_covered_calls'] += 1
                    group['generator_reasoning_tokens_observed_sum'] += reasoning
                group['length_reasoning_only_empty'] += int(
                    call['status'] == 'returned' and call.get('finish_reason') == 'length'
                    and empty and type(reasoning) is int and reasoning == total == cap
                )
            else:
                group['selector_calls'] += 1
                group['selector_call_wall_s'] += wall
                group['selector_returned'] += int(call['status'] == 'returned')
                group['selector_timeout'] += int(call['status'] == 'timeout')
        try:
            graded, changes = replay_grade(
                cell, row, metadata, plan=plan, cohort='flash', normalize_diff=False,
            )
            if changes:
                raise DiversityCapError('diversity grade replay unexpectedly normalized text')
            expected_pass = bool(graded.passed and row['status'] == 'returned')
            expected_code = None if expected_pass else (
                graded.failure_code or f"outcome_{row['status']}")
            expected_details = _content_free_details(graded.details)
            observed_details = {key: value for key, value in row['grade']['details'].items()
                                if key != '_private_call_evidence'}
            if (row['passed'] != expected_pass
                    or row['failure_code'] != expected_code
                    or row['grade']['passed'] != expected_pass
                    or row['grade']['failure_code'] != expected_code
                    or observed_details != expected_details):
                mismatches.append({'cell_id': cell.cell_id, 'kind': 'objective_or_protocol_grade'})
            objective = bool(graded.details['existing_grade']['task_success'])
            group['underlying_objective_success'] += int(objective)
            group['valid_proposals'] += graded.details['existing_grade']['valid_count']
            group['creditable_protocol_pass'] += int(expected_pass)
            pair_rows[cell.task_id][str(cap)] = expected_pass
        except (KeyError, TypeError, ValueError) as exc:
            mismatches.append({'cell_id': cell.cell_id, 'kind': type(exc).__name__})
    paired = all(set(values) == {'384', '1536'} for values in pair_rows.values())
    elapsed = run.get('elapsed_s')
    if type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed < 0:
        mismatches.append({'cell_id': 'run', 'kind': 'unbounded_evaluator_elapsed'})
        elapsed = None
    result = {
        'schema_version': REPLAY_SCHEMA,
        'status': 'source_bound_replay_passed' if not mismatches and paired else 'invalid',
        'run_id': run['run_id'],
        'plan_raw_sha256': plan_raw_sha,
        'run_raw_sha256': hashlib.sha256(raw).hexdigest(),
        'candidate_variant_id': run['candidate_variant_id'],
        'private_calls_verified': evidence['calls_verified'],
        'private_streams_verified': evidence['response_streams_verified'],
        'declared_task_pairs': 5, 'declared_condition_cells': 10,
        'declared_calls': 40, 'attempted_calls': 40,
        'recorded_evaluator_elapsed_s': elapsed,
        'by_cap': summary,
        'paired_task_protocol_differences': {
            'cap1536_pass_cap384_fail': sum(values.get('1536') is True and values.get('384') is False
                                           for values in pair_rows.values()),
            'cap384_pass_cap1536_fail': sum(values.get('384') is True and values.get('1536') is False
                                           for values in pair_rows.values()),
            'both_pass': sum(values.get('384') is True and values.get('1536') is True
                             for values in pair_rows.values()),
            'neither_pass': sum(values.get('384') is False and values.get('1536') is False
                                for values in pair_rows.values()),
        } if paired else None,
        'mismatches': mismatches,
        'original_primary_scores_changed': False,
        'claim_limit': CLAIM_LIMIT,
        'private_content_exported': False,
        'promotion_authorized': False,
    }
    return result


def _validate_window_memory(output: Path, result: dict[str, Any], state: dict[str, Any],
                            parent: Any) -> dict[str, Any]:
    """Recheck bounded raw sample chronology, arm identity, reserve and no-swap."""
    raw, actual = harness._read_regular_file(
        output / 'memory.jsonl', label='closed cap safety log', max_bytes=32_000_000,
    )
    if actual != (output / 'memory.jsonl').absolute():
        raise DiversityCapError('safety log redirected')
    rows = [harness._strict_object(line, f'cap safety row {index}')
            for index, line in enumerate(raw.splitlines(), 1) if line]
    if len(rows) > 15_000:
        raise DiversityCapError('safety log exceeds finite controller window')
    binds = [row for row in rows if row.get('schema') == 'qwen-flash-next-cgroup-bind/v1']
    samples = [row for row in rows if row.get('schema') == 'qwen-flash-next-memory-sample/v3']
    if len(binds) != 1 or not samples or len(samples) != result.get('memory_samples'):
        raise DiversityCapError('candidate arm or safety sample denominator differs')
    bind = binds[0]
    inspect = bind.get('container_inspect') or {}
    cgroup = bind.get('cgroup') or {}
    spec = parent.spec
    limit = spec.docker_memory_limit_bytes
    if (bind.get('candidate_id') != state.get('candidate_id')
            or bind.get('candidate_spec') != {
                'id': spec.spec_id, 'spec_sha256': spec.identity_sha256()}
            or bind.get('pid') != state.get('candidate_cgroup_pid')
            or inspect.get('id') != state.get('candidate_id')
            or inspect.get('pid') != state.get('candidate_cgroup_pid')
            or inspect.get('name') != spec.container_name
            or inspect.get('image') != spec.image_id
            or inspect.get('running') is not True
            or inspect.get('oom_killed') is not False
            or inspect.get('restart_count') != 0
            or inspect.get('memory_limit_bytes') != limit
            or inspect.get('memory_swap_total_bytes') != limit
            or cgroup.get('path') != state.get('candidate_cgroup_path')
            or cgroup.get('process_start_ticks') != state.get('candidate_cgroup_start_ticks')
            or cgroup.get('memory_max_bytes') != limit
            or cgroup.get('memory_swap_max_bytes') != 0
            or cgroup.get('memory_swap_current_bytes') != 0
            or cgroup.get('memory_events_oom') != 0
            or cgroup.get('memory_events_oom_kill') != 0):
        raise DiversityCapError('raw candidate cgroup binding differs from exact profile')
    minimum = math.inf
    previous = None
    evaluation_samples = 0
    for row in samples:
        observed = harness._utc_datetime(row.get('observed_at'), 'cap safety timestamp')
        gap = row.get('sample_gap_seconds')
        available = row.get('mem_available_gib')
        if (type(gap) not in (int, float) or not math.isfinite(gap)
                or not 0 <= gap <= 10
                or type(available) not in (int, float) or not math.isfinite(available)
                or available < 20
                or previous is not None and (observed - previous).total_seconds() > 10
                or previous is not None and observed < previous):
            raise DiversityCapError('raw safety sample has gap or reserve violation')
        previous = observed
        minimum = min(minimum, available)
        candidate = row.get('candidate')
        if candidate is not None and not isinstance(candidate, dict):
            raise DiversityCapError('armed safety sample candidate shape differs')
        if candidate is not None and candidate.get('armed'):
            cg = candidate.get('cgroup') or {}
            if not isinstance(cg, dict):
                raise DiversityCapError('armed safety sample cgroup shape differs')
            if (candidate.get('id') != state['candidate_id']
                    or candidate.get('pid') != state['candidate_cgroup_pid']
                    or candidate.get('name') != spec.container_name
                    or candidate.get('image') != spec.image_id
                    or candidate.get('memory_limit_bytes') != limit
                    or candidate.get('memory_swap_total_bytes') != limit
                    or candidate.get('running') is not True
                    or candidate.get('oom_killed') is not False
                    or candidate.get('restart_count') != 0
                    or cg.get('path') != state['candidate_cgroup_path']
                    or cg.get('process_start_ticks') != state['candidate_cgroup_start_ticks']
                    or cg.get('memory_max_bytes') != limit
                    or type(cg.get('memory_current_bytes')) is not int
                    or not 0 <= cg['memory_current_bytes'] <= limit
                    or cg.get('memory_swap_max_bytes') != 0
                    or cg.get('memory_swap_current_bytes') != 0
                    or cg.get('memory_events_oom') != 0
                    or cg.get('memory_events_oom_kill') != 0):
                raise DiversityCapError('armed safety sample changed candidate identity')
        if row.get('monitor_phase') == 'evaluation':
            evaluation_samples += 1
            if (not isinstance(candidate, dict) or candidate.get('armed') is not True
                    or row.get('paging_gate') != 'extended_serving'
                    or row.get('host_swap_5s_bytes') != 0
                    or row.get('host_swap_60s_bytes') != 0
                    or row.get('gate_pswpout_delta_bytes') != 0):
                raise DiversityCapError('evaluator safety sample lost serving/no-swap gate')
    reported = result.get('minimum_mem_available_gib')
    if (evaluation_samples == 0 or type(reported) not in (int, float)
            or abs(minimum - reported) > 1e-9):
        raise DiversityCapError('closed safety result differs from raw sample minimum')
    return {'memory_raw_sha256': hashlib.sha256(raw).hexdigest(),
            'memory_samples_verified': len(samples),
            'evaluation_samples_verified': evaluation_samples,
            'minimum_mem_available_gib': minimum,
            'candidate_swap_bytes_max': 0, 'candidate_oom_count_max': 0}


def replay_window(window_path: str | Path) -> dict[str, Any]:
    """Release numeric counts only after controller closure and raw grade replay."""
    controller = importlib.import_module('bench.flash_next_ab.lab_window')
    window_path = Path(window_path).absolute()
    window, parent = controller.load_window(window_path)
    output = Path(window['output_dir'])
    if (window.get('evaluation_kind') != 'diversity_cap'
            or window.get('cohort') != 'flash'
            or window.get('promotion_authorized') is not False
            or window.get('runtime_budget_s') != 2200
            or window.get('wall_s') != 4500
            or window.get('restoration_reserve_s') != 600
            or window.get('minimum_mem_available_gib') != 20):
        raise DiversityCapError('window is not the exact prospective Flash cap study')
    plan_path = Path(window['evaluation_plan']['path'])
    plan, _, plan_sha = load_plan(plan_path)
    if window['evaluation_plan']['sha256'] != plan_sha:
        raise DiversityCapError('window refers to a different frozen cap plan')

    def document(name: str, ceiling: int = 8_000_000) -> tuple[dict[str, Any], str]:
        path = output / name
        raw, actual = harness._read_regular_file(path, label=name, max_bytes=ceiling)
        if actual != path.absolute():
            raise DiversityCapError(f'{name} redirected')
        return harness._strict_object(raw, name), hashlib.sha256(raw).hexdigest()

    result, result_sha = document('result.json')
    state, state_sha = document('state.json')
    supervision, supervision_sha = document('supervision.json')
    supervision_start, supervision_start_sha = document('supervision-start.json')
    canary, canary_sha = document('profile-canary.json')
    ready_proof, ready_proof_sha = document('admission-ready-proof.json')
    readiness_raw, readiness_actual = harness._read_regular_file(
        output / 'readiness.json', label='admitted readiness', max_bytes=1_000_000,
    )
    probes_raw, probes_actual = harness._read_regular_file(
        output / 'probes.json', label='admitted probes', max_bytes=1_000_000,
    )
    run, run_sha = document('evaluation/run.json', 16_000_000)
    window_sha = manifest.sha256_file(window_path)
    restoration = result.get('restoration')
    if (result.get('schema') != 'lab-model-window-result/v1'
            or result.get('window_id') != window['window_id']
            or result.get('window_sha256') != window_sha
            or result.get('cohort') != 'flash' or result.get('status') != 'complete'
            or result.get('error') is not None
            or result.get('evaluation_run_sha256') != run_sha
            or result.get('promotion_authorized') is not False
            or state.get('phase') != 'complete'
            or state.get('window_sha256') != window_sha
            or state.get('restoration') != restoration
            or state.get('canaries') != canary
            or canary.get('status') != 'passed'
            or ready_proof.get('canaries') != canary
            or ready_proof.get('candidate', {}).get('id') != state.get('candidate_id')
            or ready_proof.get('candidate', {}).get('image') != parent.spec.image_id
            or ready_proof.get('candidate', {}).get('name') != parent.spec.container_name
            or ready_proof.get('candidate', {}).get('running') is not True
            or ready_proof.get('candidate', {}).get('oom_killed') is not False
            or ready_proof.get('readiness_sha256') != hashlib.sha256(readiness_raw).hexdigest()
            or ready_proof.get('probes_sha256') != hashlib.sha256(probes_raw).hexdigest()
            or readiness_actual != (output / 'readiness.json').absolute()
            or probes_actual != (output / 'probes.json').absolute()
            or supervision_start.get('window_sha256') != window_sha
            or supervision_start.get('pid') != state.get('worker_pid')
            or supervision_start.get('worker_pid') != state.get('worker_pid')
            or supervision_start.get('worker_start_ticks') != state.get('worker_start_ticks')
            or supervision_start.get('boot_id') != state.get('boot_id')
            or not isinstance(supervision_start.get('argv'), list)
            or supervision_start['argv'][1:] != [
                '-m', 'bench.flash_next_ab.lab_window', '--worker', '--window',
                str(window_path),
            ]
            or supervision_start['argv'][0] != sys.executable
            or not isinstance(restoration, dict)
            or restoration.get('status') != 'verified'
            or restoration.get('errors') != []
            or restoration.get('diagnostic_errors') != []
            or restoration.get('sentinel_retained') is not False
            or not isinstance(restoration.get('verified_at'), str)
            or supervision.get('schema') != 'lab-model-supervision/v1'
            or supervision.get('window_sha256') != window_sha
            or supervision.get('returncode') != 0
            or supervision.get('interrupted') is not None
            or supervision.get('terminated_at_cutoff') is not False
            or supervision.get('emergency_restoration') is not None
            or run.get('schema_version') != RUN_SCHEMA
            or run.get('status') != 'complete'
            or run.get('plan_raw_sha256') != plan_sha
            or run.get('controller_admission', {}).get('window_id') != window['window_id']
            or run.get('controller_admission', {}).get('window_sha256') != window_sha
            or run.get('controller_admission', {}).get('ready_proof_sha256')
               != ready_proof_sha
            or run.get('controller_admission', {}).get('controller_source_bundle_sha256')
               != manifest.sha256_json(window['controller_sources'])):
        raise DiversityCapError('terminal controller, restoration, or run proof differs')
    attempts, attempts_sha = document('profile-canary-attempts.json', 8_000_000)
    from .followon_qualification_admission import _validate_profile_canary

    canary_result = {
        'profile_canary_status': canary.get('status'),
        'profile_canary_sha256': canary_sha,
        'profile_canary_attempts_sha256': attempts_sha,
        'profile_canary_protocol_sha256': canary.get('protocol_sha256'),
        'profile_canary_suite': canary.get('suite'),
        'profile_canary_attempt_count': canary.get('attempt_count'),
        'profile_canary_timeout_seconds': parent.spec.profile_canary_timeout_seconds,
        'started_at': state.get('started_at'),
        'restoration': restoration,
    }
    if attempts.get('schema') != 'flash-next-mia-profile-canary-attempts/v1':
        raise DiversityCapError('profile canary attempts changed schema')
    _validate_profile_canary(output, canary_result, parent.spec)
    memory = _validate_window_memory(output, result, state, parent)
    replay = replay_run(plan_path, output / 'evaluation/run.json')
    if replay['status'] != 'source_bound_replay_passed' or replay['run_raw_sha256'] != run_sha:
        raise DiversityCapError('forty-call private stream and objective replay failed')
    return {
        **replay,
        'status': 'closed_window_replay_passed',
        'window_id': window['window_id'],
        'window_raw_sha256': window_sha,
        'plan_raw_sha256': plan_sha,
        'result_raw_sha256': result_sha,
        'state_raw_sha256': state_sha,
        'supervision_raw_sha256': supervision_sha,
        'supervision_start_raw_sha256': supervision_start_sha,
        'profile_canary_raw_sha256': canary_sha,
        'profile_canary_attempts_raw_sha256': attempts_sha,
        'admission_ready_proof_raw_sha256': ready_proof_sha,
        'run_raw_sha256': run_sha,
        'configured_context_tokens': plan['endpoints']['flash_next_mia']['max_model_len'],
        'measured_prompt_tokens_max': run.get('measured_prompt_tokens_max'),
        'restoration_verified': True,
        'supervisor_closed': True,
        'private_content_exported': False,
        **memory,
    }


def publish_replay(window_path: str | Path, output_path: str | Path) -> dict[str, Any]:
    destination = Path(output_path).absolute()
    if (not destination.is_relative_to(ARTIFACT_ROOT)
            or destination.exists() or destination.parent.is_symlink()
            or not destination.parent.is_dir()):
        raise DiversityCapError('public receipt destination is redirected or exists')
    receipt = replay_window(window_path)
    raw = manifest.canonical_json(receipt) + b'\n'
    with destination.open('xb') as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    return {'path': str(destination), 'raw_sha256': hashlib.sha256(raw).hexdigest(),
            'status': receipt['status'], 'declared_calls': 40}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--freeze-plan', type=Path)
    mode.add_argument('--publish-replay', type=Path)
    parser.add_argument('--window', type=Path)
    args = parser.parse_args(argv)
    if args.freeze_plan is not None:
        print(manifest.canonical_json(freeze_plan(args.freeze_plan)).decode())
        return 0
    if args.window is None:
        parser.error('--publish-replay requires --window')
    print(manifest.canonical_json(publish_replay(args.window, args.publish_replay)).decode())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
