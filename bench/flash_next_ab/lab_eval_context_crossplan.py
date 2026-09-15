"""Publish an admitted Qwen/Mia 24-cell context comparison across frozen plans.

The Mia arm comes from the first 24 cells of the separately completed 36-cell
Gemma/Mia plan. This is a public-development diagnostic, never a same-plan pair.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

from . import harness, lab_eval_context, lab_eval_context_qwen, manifest, qualification
from .followon_dispatch import FOLLOWON_SOURCE_MODULES
from .lab_eval_runner import _admission

ARTIFACT_ROOT = Path('/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-15/lab-eight-hour')
WINDOW_ROOT = ARTIFACT_ROOT / 'model-windows'
PUBLICATION_ROOT = ARTIFACT_ROOT / 'context-crossplan-qwen-mia'
ORIGINAL_ROOT = Path('/home/decross1/projects/a_bgt_rsi_worktrees/lab-eight-hour-20260915')
QWEN_ROOT = Path('/home/decross1/projects/a_bgt_rsi_worktrees/lab-context-qwen-20260915')
INDEX_SCHEMA = 'lab-context-crossplan-publication-index/v1'
REPORT_SCHEMA = 'lab-context-crossplan-matched24-report/v1'
SOURCE_KEYS = frozenset({'bench/flash_next_ab/' + name for name in FOLLOWON_SOURCE_MODULES}
                        | {'bench/flash_next_ab/lab_window.py',
                           'orchestrator/weekly_upgrade_trial.py'})
PUBLICATION_ID = re.compile(r'qfn-context-qwen-mia-[a-z0-9][a-z0-9._-]{0,63}\Z')
WINDOW_KEYS = frozenset({
    'schema', 'window_id', 'cohort', 'created_at', 'output_dir',
    'evaluation_plan', 'runtime_certificate', 'candidate_spec_id',
    'candidate_spec_sha256', 'controller_sources', 'code_root',
    'runtime_budget_s', 'wall_s', 'restoration_reserve_s',
    'minimum_mem_available_gib', 'promotion_authorized', 'evaluation_kind',
})
REF_KEYS = frozenset({
    'window_path', 'window_raw_sha256', 'plan_path', 'plan_raw_sha256',
    'result_path', 'result_raw_sha256', 'state_path', 'state_raw_sha256',
    'supervision_path', 'supervision_raw_sha256',
    'worker_start_path', 'worker_start_raw_sha256',
    'ready_proof_path', 'ready_proof_raw_sha256', 'run_path', 'run_raw_sha256',
})
REF_PAIRS = (
    ('window_path', 'window_raw_sha256'), ('plan_path', 'plan_raw_sha256'),
    ('result_path', 'result_raw_sha256'), ('state_path', 'state_raw_sha256'),
    ('supervision_path', 'supervision_raw_sha256'),
    ('worker_start_path', 'worker_start_raw_sha256'),
    ('ready_proof_path', 'ready_proof_raw_sha256'), ('run_path', 'run_raw_sha256'),
)
SHA = re.compile(r'[0-9a-f]{64}\Z')
INDEX_KEYS = frozenset({
    'schema_version', 'publication_id', 'status', 'report_relpath',
    'report_raw_sha256', 'builder_source_path', 'builder_source_sha256',
    'qwen_source_refs', 'mia_source_refs', 'qwen_replay_relpath',
    'qwen_replay_raw_sha256', 'mia_replay_relpath', 'mia_replay_raw_sha256',
    'overlap_receipts_sha256', 'grade_replay', 'same_plan_pair',
    'qwen_plan_flash_arm_issued_for_this_comparison',
    'private_response_exported', 'promotion_authorized',
})


class CrossPlanError(ValueError):
    pass


def _doc(path: Path, *, label: str, max_bytes: int = 16_000_000) -> tuple[dict, str]:
    raw, actual = harness._read_regular_file(path, label=label, max_bytes=max_bytes)
    if actual != path.absolute():
        raise CrossPlanError(f'{label} path was redirected')
    return harness._strict_object(raw, label), hashlib.sha256(raw).hexdigest()


def _file_sha(path: Path, *, label: str, max_bytes: int) -> str:
    raw, actual = harness._read_regular_file(path, label=label, max_bytes=max_bytes)
    if actual != path.absolute():
        raise CrossPlanError(f'{label} path was redirected')
    return hashlib.sha256(raw).hexdigest()


def _plan_ref(window: dict, *, label: str) -> Path:
    ref = window.get('evaluation_plan')
    if (not isinstance(ref, dict) or set(ref) != {'path', 'sha256'}
            or not isinstance(ref['path'], str)
            or not isinstance(ref['sha256'], str)):
        raise CrossPlanError(f'{label} window lacks an exact frozen plan reference')
    path = Path(ref['path'])
    if path != path.absolute() or not path.is_relative_to(ARTIFACT_ROOT):
        raise CrossPlanError(f'{label} frozen plan is outside the registered lab root')
    return path


def _source_bundle(window: dict, root: Path) -> None:
    bundle = window.get('controller_sources')
    if (window.get('code_root') != str(root)
            or not isinstance(bundle, dict) or set(bundle) != SOURCE_KEYS):
        raise CrossPlanError('controller code root or complete source inventory differs')
    for name, source in bundle.items():
        if (not isinstance(source, dict) or set(source) != {'path', 'sha256'}
                or source['path'] != str(root / name)):
            raise CrossPlanError('controller source path differs from fixed registered root')
        actual_sha = _file_sha(root / name, label=f'controller source {name}',
                              max_bytes=8 * 1024**2)
        if actual_sha != source['sha256']:
            raise CrossPlanError('controller source changed after the window was frozen')


def _window(path: Path, *, cohort: str, kind: str, root: Path,
            plan_path: Path, loader: Any, replay_private: bool = True) -> dict[str, Any]:
    path = path.absolute()
    window, window_sha = _doc(path, label=f'{cohort} {kind} window', max_bytes=8_000_000)
    output = path.parent
    if (set(window) != WINDOW_KEYS
            or path != output / 'window.json' or output.parent != WINDOW_ROOT
            or output.name != f"{window.get('window_id')}.{cohort}"
            or window.get('schema') != 'lab-model-window/v1'
            or window.get('cohort') != cohort or window.get('evaluation_kind') != kind
            or window.get('output_dir') != str(output)
            or window.get('minimum_mem_available_gib') != 20
            or window.get('restoration_reserve_s') != 600
            or window.get('promotion_authorized') is not False
            or type(window.get('runtime_budget_s')) is not int
            or not 60 <= window['runtime_budget_s'] <= (6000 if kind == 'context' else 3000)
            or type(window.get('wall_s')) is not int
            or not window['runtime_budget_s'] + 600 + (1500 if cohort == 'flash' else 60)
            <= window['wall_s'] <= 14400):
        raise CrossPlanError(f'{cohort} window identity, kind or limits differ')
    _source_bundle(window, root)
    if (plan_path != _plan_ref(window, label=cohort)):
        raise CrossPlanError('frozen plan path or source envelope is outside lab artifacts')
    plan, _, plan_sha = loader(plan_path)
    if (window.get('evaluation_plan') != {'path': str(plan_path), 'sha256': plan_sha}
            or window.get('runtime_certificate') != {
                'path': plan['runtime_certificates']['flash']['parent_path'],
                'sha256': plan['runtime_certificates']['flash']['parent_sha256'],
            }
            or window.get('candidate_spec_id') !=
            plan['runtime_certificates']['flash']['candidate_spec_id']
            or window.get('candidate_spec_sha256') !=
            plan['runtime_certificates']['flash']['candidate_spec_sha256']):
        raise CrossPlanError(f'{cohort} frozen evaluator or candidate certificate differs')
    result, result_sha = _doc(output / 'result.json', label=f'{cohort} terminal result')
    state, state_sha = _doc(output / 'state.json', label=f'{cohort} terminal state')
    supervision, supervision_sha = _doc(
        output / 'supervision.json', label=f'{cohort} supervisor closure',
    )
    started, started_sha = _doc(
        output / 'supervision-start.json', label=f'{cohort} worker start',
    )
    _, proof_sha = _doc(
        output / 'admission-ready-proof.json', label=f'{cohort} live admission proof',
    )
    run, run_sha = _doc(output / 'evaluation/run.json', label=f'{cohort} completed run')
    restore = result.get('restoration')
    minimum = result.get('minimum_mem_available_gib')
    gate = run.get('controller_admission')
    elapsed = supervision.get('elapsed_s')
    if (result.get('schema') != 'lab-model-window-result/v1'
            or result.get('window_id') != window['window_id']
            or result.get('cohort') != cohort or result.get('status') != 'complete'
            or result.get('window_sha256') != window_sha
            or result.get('evaluation_run_sha256') != run_sha
            or result.get('error') is not None
            or result.get('promotion_authorized') is not False
            or type(minimum) not in (int, float) or not math.isfinite(minimum)
            or minimum < 20 or type(result.get('memory_samples')) is not int
            or result['memory_samples'] < 1
            or not isinstance(restore, dict)
            or restore.get('status') != 'verified'
            or restore.get('errors') != []
            or restore.get('sentinel_retained') is not False
            or state.get('phase') != 'complete'
            or state.get('window_sha256') != window_sha
            or state.get('restoration') != restore
            or supervision.get('schema') != 'lab-model-supervision/v1'
            or supervision.get('window_sha256') != window_sha
            or supervision.get('returncode') != 0
            or supervision.get('interrupted') is not None
            or supervision.get('terminated_at_cutoff') is not False
            or supervision.get('emergency_restoration') is not None
            or type(elapsed) not in (int, float) or not math.isfinite(elapsed)
            or not 0 <= elapsed <= window['wall_s'] + 30
            or started.get('window_sha256') != window_sha
            or type(state.get('worker_pid')) is not int or state['worker_pid'] <= 0
            or type(state.get('worker_start_ticks')) is not int
            or state['worker_start_ticks'] <= 0
            or not isinstance(state.get('boot_id'), str) or not state['boot_id']
            or started.get('pid') != state['worker_pid']
            or started.get('worker_start_ticks') != state['worker_start_ticks']
            or started.get('boot_id') != state['boot_id']
            or not isinstance(gate, dict)
            or gate.get('window_id') != window['window_id']
            or gate.get('window_sha256') != window_sha
            or gate.get('ready_proof_sha256') != proof_sha
            or gate.get('controller_source_bundle_sha256') !=
            qualification.sha256(window['controller_sources'])
            or run.get('status') != 'complete'
            or run.get('cohort') != cohort
            or run.get('plan_raw_sha256') != plan_sha
            or run.get('candidate_variant_id') != (
                plan['runtime_certificates']['flash']['candidate_spec_id']
                if cohort == 'flash' else 'resident-qwen'
            )
            or run.get('configured_context_tokens') != plan['endpoints'][
                'flash_next_mia' if cohort == 'flash' else 'resident_qwen'
            ]['max_model_len']):
        raise CrossPlanError(f'{cohort} run lacks closed, restored, worker-bound admission')
    _admission(plan, cohort, gate)
    replay = None
    if replay_private:
        try:
            replay = (lab_eval_context.replay_run if kind == 'context'
                      else lab_eval_context_qwen.replay_run)(
                          plan_path, output / 'evaluation/run.json',
                      )
        except Exception as exc:
            raise CrossPlanError(f'{cohort} private stream/grade replay failed') from exc
        expected_cells = 36 if kind == 'context' else 24
        if (replay.get('primary_replay_passed') is not True
                or replay.get('objective_cells_replayed') != expected_cells
                or replay.get('run_raw_sha256') != run_sha
                or replay.get('private_content_exported') is not False):
            raise CrossPlanError(f'{cohort} private stream or objective grade replay failed')
    refs = {
        'window_path': str(path), 'window_raw_sha256': window_sha,
        'plan_path': str(plan_path), 'plan_raw_sha256': plan_sha,
        'result_path': str(output / 'result.json'), 'result_raw_sha256': result_sha,
        'state_path': str(output / 'state.json'), 'state_raw_sha256': state_sha,
        'supervision_path': str(output / 'supervision.json'),
        'supervision_raw_sha256': supervision_sha,
        'worker_start_path': str(output / 'supervision-start.json'),
        'worker_start_raw_sha256': started_sha,
        'ready_proof_path': str(output / 'admission-ready-proof.json'),
        'ready_proof_raw_sha256': proof_sha,
        'run_path': str(output / 'evaluation/run.json'), 'run_raw_sha256': run_sha,
    }
    return {'window': window, 'plan': plan, 'run': run, 'replay': replay, 'refs': refs}


def _overlap(qwen: dict, mia: dict) -> tuple[list[str], str]:
    qplan, mplan = qwen['plan'], mia['plan']
    ids = qplan['declared_cells']
    if (len(ids) != 24 or mplan['declared_cells'][:24] != ids
            or qwen['run']['declared_cells'] != ids
            or mia['run']['declared_cells'][:24] != ids
            or qplan['packet_raw_sha256'] != mplan['packet_raw_sha256']
            or qplan['runtime_certificates'] != mplan['runtime_certificates']
            or qplan['endpoints']['flash_next_mia'] != mplan['endpoints']['flash_next_mia']
            or qplan['endpoints']['resident_qwen']['policies'][lab_eval_context_qwen.POLICY_ID]
            != mplan['endpoints']['flash_next_mia']['policies'][lab_eval_context.POLICY_ID]
            or qplan['hard_call_ceiling_s'] != 2880):
        raise CrossPlanError('Qwen/Mia source packet, runtime, policy or 24-cell prefix differs')
    common = set(qplan['evaluator_source_bundle']) & set(mplan['evaluator_source_bundle'])
    if any(qplan['evaluator_source_bundle'][name] != mplan['evaluator_source_bundle'][name]
           for name in common):
        raise CrossPlanError('shared grader, transport or packet builder source differs')
    receipts = []
    for index, cell_id in enumerate(ids):
        qrow, mrow = qplan['cell_receipts'][cell_id], mplan['cell_receipts'][cell_id]
        qout, mout = qwen['run']['outcomes'][index], mia['run']['outcomes'][index]
        if (qrow != mrow
                or qplan['call_routes']['resident'][cell_id] != ['resident_qwen']
                or mplan['call_routes']['flash'][cell_id] != ['flash_next_mia']
                or qplan['call_routes']['flash'][cell_id] != mplan['call_routes']['flash'][cell_id]
                or qout['cell_id'] != cell_id or mout['cell_id'] != cell_id
                or qrow['max_output_tokens'] != 2048
                or qrow['timeout_s'] != lab_eval_context.TIMEOUTS[qrow['server_context_tokens']]
                or qrow['server_context_tokens'] not in (8192, 16384)
                or any(outcome.get('server_context_tokens') != qrow['server_context_tokens']
                       or outcome.get('placement') != qrow['placement']
                       or outcome.get('messages_sha256') != qrow['messages_sha256']
                       or outcome.get('grader_sha256') != qrow['grader_sha256']
                       or outcome.get('output_reserve_tokens') != 2048
                       for outcome in (qout, mout))
                or qout.get('actual_prompt_tokens_preflight') !=
                qrow['actual_prompt_tokens_by_endpoint']['resident_qwen']
                or mout.get('actual_prompt_tokens_preflight') !=
                qrow['actual_prompt_tokens_by_endpoint']['flash_next_mia']):
            raise CrossPlanError('matched cell, route, message or call cap differs')
        receipts.append({'cell_id': cell_id, 'receipt': qrow})
    return ids, manifest.sha256_json(receipts)


def _counts(rows: list[dict], *, band: int) -> dict[str, Any]:
    statuses = ('returned', 'timeout', 'error', 'cancelled')
    if (len(rows) != 12 or any(row.get('server_context_tokens') != band
                            or row.get('status') not in statuses
                            or not isinstance(row.get('calls'), list)
                            or len(row['calls']) != 1
                            or type(row.get('passed')) is not bool
                            or type(row.get('wall_s')) not in (int, float)
                            or not math.isfinite(row['wall_s']) or row['wall_s'] < 0
                            for row in rows)):
        raise CrossPlanError('matched capacity lane is incomplete or has unissued calls')
    max_prompt = max(
        (call['usage']['prompt_tokens'] for row in rows for call in row['calls']
         if isinstance(call.get('usage'), dict)
         and type(call['usage'].get('prompt_tokens')) is int), default=None,
    )
    return {
        'declared': 12, 'attempted': 12,
        'passed': sum(row['passed'] is True for row in rows),
        'returned': sum(row['status'] == 'returned' for row in rows),
        'timeout': sum(row['status'] == 'timeout' for row in rows),
        'error': sum(row['status'] == 'error' for row in rows),
        'cancelled': sum(row['status'] == 'cancelled' for row in rows),
        'wall_s_including_failures': sum(row['wall_s'] for row in rows),
        'measured_prompt_tokens_max': max_prompt,
        'observed_2048_output_reserve_within_total_band': (
            max_prompt + 2048 <= band if max_prompt is not None else None
        ),
    }


def _report(qwen: dict, mia: dict, ids: list[str], overlap_sha: str,
            publication_id: str) -> dict[str, Any]:
    rows = {}
    for cap in (8192, 16384):
        positions = [index for index, cell_id in enumerate(ids)
                     if qwen['plan']['cell_receipts'][cell_id]['server_context_tokens'] == cap]
        if len(positions) != 12:
            raise CrossPlanError('8K/16K lane lacks twelve matched placements')
        qrows = [qwen['run']['outcomes'][index] for index in positions]
        mrows = [mia['run']['outcomes'][index] for index in positions]
        rows[str(cap)] = {
            'resident_qwen': _counts(qrows, band=cap),
            'flash_next_mia': _counts(mrows, band=cap),
            'matched_cell_pass_categories': {
                'qwen_only': sum(q['passed'] is True and m['passed'] is False
                                 for q, m in zip(qrows, mrows, strict=True)),
                'mia_only': sum(m['passed'] is True and q['passed'] is False
                                for q, m in zip(qrows, mrows, strict=True)),
                'both_pass': sum(q['passed'] is True and m['passed'] is True
                                 for q, m in zip(qrows, mrows, strict=True)),
                'neither_pass': sum(q['passed'] is False and m['passed'] is False
                                    for q, m in zip(qrows, mrows, strict=True)),
            },
        }
    return {
        'schema_version': REPORT_SCHEMA, 'publication_id': publication_id,
        'status': 'complete_cross_plan_diagnostic',
        'comparison_kind': 'cross_plan_matched24_development_diagnostic',
        'same_plan_pair': False, 'qwen_plan_flash_arm_issued_for_this_comparison': False,
        'qwen_window_id': qwen['window']['window_id'],
        'mia_window_id': mia['window']['window_id'],
        'arm_identities': {
            'resident_qwen': {
                'candidate_variant_id': qwen['run']['candidate_variant_id'],
                'served_model': qwen['plan']['endpoints']['resident_qwen']['served_model'],
                'artifact_sha256': qwen['plan']['endpoints']['resident_qwen']['artifact_sha256'],
                'runtime_sha256': qwen['plan']['endpoints']['resident_qwen']['runtime_sha256'],
                'configured_max_context_tokens': qwen['run']['configured_context_tokens'],
            },
            'flash_next_mia': {
                'candidate_variant_id': mia['run']['candidate_variant_id'],
                'served_model': mia['plan']['endpoints']['flash_next_mia']['served_model'],
                'artifact_sha256': mia['plan']['endpoints']['flash_next_mia']['artifact_sha256'],
                'runtime_sha256': mia['plan']['endpoints']['flash_next_mia']['runtime_sha256'],
                'configured_max_context_tokens': mia['run']['configured_context_tokens'],
            },
        },
        'qwen_plan_raw_sha256': qwen['refs']['plan_raw_sha256'],
        'mia_plan_raw_sha256': mia['refs']['plan_raw_sha256'],
        'packet_raw_sha256': qwen['plan']['packet_raw_sha256'],
        'overlap_receipts_sha256': overlap_sha,
        'grade_replay': 'private_sse_and_all_24_qwen_all_36_mia_objective_grades',
        'matched_cells': 24, 'capacities_total_tokens': [8192, 16384],
        'output_reserve_tokens': 2048,
        'by_capacity': rows,
        'private_response_exported': False,
        'heldout_claim': False, 'promotion_authorized': False,
        'limitations': [
            'Different frozen plans and separately admitted runtime windows; not a same-plan pair.',
            'Only the first 24 cells of the complete Mia 36-cell run are compared.',
            'Qwen 32K is unqualified; no Qwen-plan Flash arm was run for this diagnostic.',
            'All packets are public development fixtures; task placements are correlated.',
            'Call wall times exclude distinct container startup and restoration periods.',
            'Both frozen source worktrees must remain available for source rehash admission.',
        ],
    }


def _new(path: Path, value: dict) -> str:
    raw = manifest.canonical_json(value) + b'\n'
    with path.open('xb') as handle:
        handle.write(raw)
    return hashlib.sha256(raw).hexdigest()


def publish(mia_window_path: str | Path, qwen_window_path: str | Path,
            *, publication_id: str) -> dict[str, Any]:
    """Seal numeric results only after both independent windows and replays pass."""
    if PUBLICATION_ID.fullmatch(publication_id) is None:
        raise CrossPlanError('publication ID is outside the closed diagnostic registry')
    mia_window_path, qwen_window_path = Path(mia_window_path), Path(qwen_window_path)
    m_window, _ = _doc(mia_window_path.absolute(), label='Mia context window')
    q_window, _ = _doc(qwen_window_path.absolute(), label='Qwen context window')
    mia_plan_path = _plan_ref(m_window, label='Mia')
    qwen_plan_path = _plan_ref(q_window, label='Qwen')
    mia = _window(mia_window_path, cohort='flash', kind='context', root=ORIGINAL_ROOT,
                  plan_path=mia_plan_path, loader=lab_eval_context.load_plan)
    qwen = _window(qwen_window_path, cohort='resident', kind='context_qwen', root=QWEN_ROOT,
                   plan_path=qwen_plan_path, loader=lab_eval_context_qwen.load_plan)
    ids, overlap_sha = _overlap(qwen, mia)
    report = _report(qwen, mia, ids, overlap_sha, publication_id)
    output = PUBLICATION_ROOT / publication_id
    if output.exists() or not PUBLICATION_ROOT.is_dir() or PUBLICATION_ROOT.is_symlink():
        raise CrossPlanError('immutable publication child exists or parent is redirected')
    output.mkdir(mode=0o700)
    qwen_replay_sha = _new(output / 'qwen-replay.json', qwen['replay'])
    mia_replay_sha = _new(output / 'mia-replay.json', mia['replay'])
    report_sha = _new(output / 'report.json', report)
    index = {
        'schema_version': INDEX_SCHEMA, 'publication_id': publication_id,
        'status': 'complete_cross_plan_diagnostic',
        'report_relpath': 'report.json', 'report_raw_sha256': report_sha,
        'builder_source_path': 'bench/flash_next_ab/lab_eval_context_crossplan.py',
        'builder_source_sha256': manifest.sha256_file(__file__),
        'qwen_source_refs': qwen['refs'], 'mia_source_refs': mia['refs'],
        'qwen_replay_relpath': 'qwen-replay.json', 'qwen_replay_raw_sha256': qwen_replay_sha,
        'mia_replay_relpath': 'mia-replay.json', 'mia_replay_raw_sha256': mia_replay_sha,
        'overlap_receipts_sha256': overlap_sha,
        'grade_replay': 'private_sse_and_all_24_qwen_all_36_mia_objective_grades',
        'same_plan_pair': False, 'qwen_plan_flash_arm_issued_for_this_comparison': False,
        'private_response_exported': False, 'promotion_authorized': False,
    }
    index_sha = _new(output / 'index.json', index)
    return {'index_path': str(output / 'index.json'), 'index_raw_sha256': index_sha,
            'report_raw_sha256': report_sha, 'matched_cells': 24,
            'comparison_kind': report['comparison_kind']}


def read_publication(index_path: str | Path) -> dict[str, Any]:
    """Rehash the published receipts and independently recompute numeric counts.

    The publisher already replayed all private streams/grades. This bounded
    content-free reader checks those sealed replay receipts without exporting
    responses or repeating sandbox/model work during dashboard polling.
    """
    index_path = Path(index_path).absolute()
    output = index_path.parent
    if (index_path.name != 'index.json' or output.parent != PUBLICATION_ROOT
            or output.is_symlink() or PUBLICATION_ID.fullmatch(output.name) is None):
        raise CrossPlanError('publication is outside a direct registered child')
    index, _ = _doc(index_path, label='cross-plan publication index')
    if (set(index) != INDEX_KEYS
            or index.get('schema_version') != INDEX_SCHEMA
            or index.get('publication_id') != output.name
            or index.get('status') != 'complete_cross_plan_diagnostic'
            or index.get('report_relpath') != 'report.json'
            or index.get('builder_source_path') !=
            'bench/flash_next_ab/lab_eval_context_crossplan.py'
            or index.get('builder_source_sha256') != manifest.sha256_file(__file__)
            or index.get('qwen_replay_relpath') != 'qwen-replay.json'
            or index.get('mia_replay_relpath') != 'mia-replay.json'
            or index.get('grade_replay') !=
            'private_sse_and_all_24_qwen_all_36_mia_objective_grades'
            or index.get('same_plan_pair') is not False
            or index.get('qwen_plan_flash_arm_issued_for_this_comparison') is not False
            or index.get('private_response_exported') is not False
            or index.get('promotion_authorized') is not False):
        raise CrossPlanError('cross-plan index source or claim fields differ')
    report, report_sha = _doc(output / 'report.json', label='cross-plan numeric report')
    if report_sha != index.get('report_raw_sha256'):
        raise CrossPlanError('numeric report source differs from index')
    mia_refs, qwen_refs = index.get('mia_source_refs'), index.get('qwen_source_refs')
    if (not isinstance(mia_refs, dict) or set(mia_refs) != REF_KEYS
            or not isinstance(qwen_refs, dict) or set(qwen_refs) != REF_KEYS
            or any(not isinstance(ref[path], str) or Path(ref[path]) != Path(ref[path]).absolute()
                   or not isinstance(ref[digest], str) or SHA.fullmatch(ref[digest]) is None
                   for ref in (mia_refs, qwen_refs) for path, digest in REF_PAIRS)):
        raise CrossPlanError('window source references are missing')
    mia = _window(Path(mia_refs['window_path']), cohort='flash', kind='context',
                  root=ORIGINAL_ROOT, plan_path=Path(mia_refs['plan_path']),
                  loader=lab_eval_context.load_plan, replay_private=False)
    qwen = _window(Path(qwen_refs['window_path']), cohort='resident', kind='context_qwen',
                   root=QWEN_ROOT, plan_path=Path(qwen_refs['plan_path']),
                   loader=lab_eval_context_qwen.load_plan, replay_private=False)
    if mia['refs'] != mia_refs or qwen['refs'] != qwen_refs:
        raise CrossPlanError('terminal window source references differ from index')
    for cohort, item, expected in (
        ('mia', mia, 36), ('qwen', qwen, 24),
    ):
        replay, replay_sha = _doc(
            output / index[f'{cohort}_replay_relpath'], label=f'{cohort} sealed grade replay',
        )
        if (replay_sha != index.get(f'{cohort}_replay_raw_sha256')
                or replay.get('primary_replay_passed') is not True
                or replay.get('objective_cells_replayed') != expected
                or replay.get('run_raw_sha256') != item['refs']['run_raw_sha256']
                or replay.get('private_content_exported') is not False):
            raise CrossPlanError(f'{cohort} grade replay receipt differs')
    ids, overlap_sha = _overlap(qwen, mia)
    if overlap_sha != index.get('overlap_receipts_sha256'):
        raise CrossPlanError('matched 24-cell source receipt digest differs')
    if report != _report(qwen, mia, ids, overlap_sha, output.name):
        raise CrossPlanError('numeric report differs from independently bound runs')
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--publish', action='store_true')
    mode.add_argument('--read-index', type=Path)
    parser.add_argument('--mia-window', type=Path)
    parser.add_argument('--qwen-window', type=Path)
    parser.add_argument('--publication-id')
    args = parser.parse_args(argv)
    if args.publish:
        if not all((args.mia_window, args.qwen_window, args.publication_id)):
            parser.error('publication requires both closed windows and an immutable ID')
        value = publish(args.mia_window, args.qwen_window,
                        publication_id=args.publication_id)
    else:
        value = read_publication(args.read_index)
    print(json.dumps(value, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
