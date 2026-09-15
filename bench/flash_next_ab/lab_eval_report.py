"""Publish a content-free paired result only after two closed model windows."""
from __future__ import annotations

import hashlib
import importlib
from pathlib import Path
from typing import Any

from . import harness, manifest
from .lab_eval_plan import load_plan
from .lab_eval_replay import replay_run

SCHEMA = 'lab-model-eval-paired-report/v1'
INDEX_SCHEMA = 'lab-model-eval-publication-index/v1'
PUBLICATION_ROOT = Path('/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-15/lab-eight-hour/evaluation-pairs')


class ReportError(ValueError):
    pass


def _doc(path: Path, *, label: str, ceiling: int = 8_000_000) -> tuple[dict, str]:
    raw, actual = harness._read_regular_file(path, label=label, max_bytes=ceiling)
    if actual != path.absolute():
        raise ReportError(f'{label} redirected')
    return harness._strict_object(raw, label), hashlib.sha256(raw).hexdigest()


def _closed_window(path: Path, *, cohort: str, plan_path: Path,
                   plan_raw_sha: str) -> tuple[dict, dict, dict, dict]:
    # Reuse the actual source/qualified-parent/controller reader rather than
    # introducing another historical certificate parser.
    controller = importlib.import_module('bench.flash_next_ab.lab_window')
    window, _ = controller.load_window(path)
    output = Path(window['output_dir'])
    result, result_sha = _doc(output / 'result.json', label=f'{cohort} terminal result')
    supervision, supervision_sha = _doc(output / 'supervision.json', label=f'{cohort} supervision')
    run_path = output / 'evaluation/run.json'
    run, run_sha = _doc(run_path, label=f'{cohort} model run', ceiling=16_000_000)
    restoration = result.get('restoration')
    if (window.get('evaluation_kind') != 'primary'
            or window.get('cohort') != cohort
            or Path(window['evaluation_plan']['path']) != plan_path.absolute()
            or window['evaluation_plan']['sha256'] != plan_raw_sha
            or result.get('cohort') != cohort or result.get('status') != 'complete'
            or result.get('evaluation_run_sha256') != run_sha
            or not isinstance(restoration, dict)
            or restoration.get('status') != 'verified'
            or restoration.get('errors') != []
            or restoration.get('sentinel_retained') is not False
            or supervision.get('schema') != 'lab-model-supervision/v1'
            or supervision.get('returncode') != 0
            or supervision.get('interrupted') is not None
            or supervision.get('terminated_at_cutoff') is not False
            or supervision.get('emergency_restoration') is not None
            or run.get('cohort') != cohort or run.get('status') != 'complete'
            or run.get('plan_raw_sha256') != plan_raw_sha):
        raise ReportError(f'{cohort} window lacks exact restoration/supervision/run admission')
    window_sha = manifest.sha256_file(path)
    if (result.get('window_sha256') != window_sha
            or supervision.get('window_sha256') != window_sha
            or supervision.get('window_sha256') != result.get('window_sha256')):
        raise ReportError(f'{cohort} terminal receipts belong to another window')
    replay = replay_run(plan_path, run_path)
    if (replay['primary_replay_passed'] is not True
            or replay['primary_cells_replayed'] != 126
            or replay['run_raw_sha256'] != run_sha):
        raise ReportError(f'{cohort} independent raw/grade replay did not pass')
    refs = {
        'window_path': str(path), 'window_raw_sha256': window_sha,
        'result_path': str(output / 'result.json'), 'result_raw_sha256': result_sha,
        'supervision_path': str(output / 'supervision.json'),
        'supervision_raw_sha256': supervision_sha,
        'run_path': str(run_path), 'run_raw_sha256': run_sha,
    }
    return window, run, replay, refs


def _family(run: dict) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in run['outcomes']:
        row = result.setdefault(item['family'], {
            'declared': 0, 'attempted': 0, 'returned': 0,
            'timeout': 0, 'error': 0, 'cancelled': 0,
            'passed': 0, 'wall_s_including_failures': 0.0,
        })
        row['declared'] += 1
        row['attempted'] += int(bool(item['calls']))
        row['returned'] += int(item['status'] == 'returned')
        row['timeout'] += int(item['status'] == 'timeout')
        row['error'] += int(item['status'] == 'error')
        row['cancelled'] += int(item['status'] == 'cancelled')
        row['passed'] += int(item['passed'] is True)
        row['wall_s_including_failures'] += item['wall_s']
    return result


def build_report(plan_path: str | Path, resident_window_path: str | Path,
                 flash_window_path: str | Path) -> tuple[dict, dict, dict]:
    plan_path = Path(plan_path).absolute()
    plan, _, plan_raw_sha = load_plan(plan_path)
    resident_window, resident_run, resident_replay, resident_refs = _closed_window(
        Path(resident_window_path).absolute(), cohort='resident',
        plan_path=plan_path, plan_raw_sha=plan_raw_sha,
    )
    flash_window, flash_run, flash_replay, flash_refs = _closed_window(
        Path(flash_window_path).absolute(), cohort='flash',
        plan_path=plan_path, plan_raw_sha=plan_raw_sha,
    )
    if (resident_window['window_id'] != flash_window['window_id']
            or resident_run['declared_cells'] != flash_run['declared_cells']
            or resident_run['declared_cells'] != plan['declared_cells']
            or [row['cell_id'] for row in resident_run['outcomes']] != plan['declared_cells']
            or [row['cell_id'] for row in flash_run['outcomes']] != plan['declared_cells']):
        raise ReportError('paired windows differ in exact plan, task order or window ID')
    cohorts = {}
    refs = {'resident': resident_refs, 'flash': flash_refs}
    for name, run, replay in (
        ('resident', resident_run, resident_replay),
        ('flash', flash_run, flash_replay),
    ):
        family = _family(run)
        cohorts[name] = {
            'variant_id': run['candidate_variant_id'],
            'configured_context_tokens_by_endpoint': run['configured_context_tokens_by_endpoint'],
            'measured_prompt_tokens_max_by_endpoint': run['measured_prompt_tokens_max_by_endpoint'],
            'status': 'complete', 'declared': 126,
            'attempted': sum(bool(row['calls']) for row in run['outcomes']),
            'passed': sum(row['passed'] is True for row in run['outcomes']),
            'timeout': sum(row['status'] == 'timeout' for row in run['outcomes']),
            'elapsed_s': run['elapsed_s'], 'families': family,
            'raw_response_replay_passed': replay['primary_replay_passed'],
            'normalization_diagnostic': replay['normalization_diagnostic'],
        }
    report = {
        'schema_version': SCHEMA,
        'pair_id': resident_window['window_id'],
        'status': 'complete_admitted_pair',
        'suite_id': plan['suite_id'], 'cell_set': plan['cell_set'],
        'plan_raw_sha256': plan_raw_sha,
        'plan_sha256': manifest.sha256_json(plan),
        'cohorts': cohorts,
        'denominator': 126,
        'family_set': list(_family(resident_run)),
        'original_scores_rebased': False,
        'heldout_claim': False,
        'capacity_vs_quality_separated': True,
        'private_content_exported': False,
        'promotion_authorized': False,
        'claim_limit': 'DESCRIPTIVE_REUSED_126_TASK_DEPLOYABLE_BUNDLE_COMPARISON',
    }
    refs['plan'] = {'path': str(plan_path), 'raw_sha256': plan_raw_sha}
    refs['report_builder'] = {'path': str(Path(__file__).absolute()),
                              'raw_sha256': manifest.sha256_file(__file__)}
    return report, refs, {'resident': resident_replay, 'flash': flash_replay}


def publish(plan_path: str | Path, resident_window_path: str | Path,
            flash_window_path: str | Path, *, output_dir: str | Path) -> dict:
    report, refs, replays = build_report(
        plan_path, resident_window_path, flash_window_path,
    )
    output = Path(output_dir).absolute()
    if (output.parent != PUBLICATION_ROOT or output.name != report['pair_id']
            or output.exists() or output.parent.is_symlink()):
        raise ReportError('paired publication path is not a new registered direct child')
    output.mkdir(mode=0o700)
    report_raw = manifest.canonical_json(report) + b'\n'
    with (output / 'report.json').open('xb') as handle:
        handle.write(report_raw)
    replay_refs = {}
    for cohort, replay in replays.items():
        leaf = f'{cohort}-replay.json'
        replay_raw = manifest.canonical_json(replay) + b'\n'
        with (output / leaf).open('xb') as handle:
            handle.write(replay_raw)
        replay_refs[cohort] = {
            'relpath': leaf,
            'raw_sha256': hashlib.sha256(replay_raw).hexdigest(),
        }
    index = {
        'schema_version': INDEX_SCHEMA, 'pair_id': report['pair_id'],
        'status': 'complete_admitted_pair',
        'report_relpath': 'report.json',
        'report_raw_sha256': hashlib.sha256(report_raw).hexdigest(),
        'replay_refs': replay_refs,
        'source_refs': refs,
        'grade_replay': 'raw_sse_and_all_126_primary_grades_per_cohort',
        'private_content_exported': False,
        'promotion_authorized': False,
    }
    with (output / 'index.json').open('xb') as handle:
        handle.write(manifest.canonical_json(index) + b'\n')
    return index


def read_publication(index_path: str | Path) -> dict:
    """Return only numeric admitted fields; rehash every published source.

    This bounded display reader verifies immutable publication receipts and
    registered controller/parent sources. Publication alone ran the expensive
    private SSE and sandbox replay; this reader never exports private content.
    """
    index_path = Path(index_path).absolute()
    if (index_path.name != 'index.json'
            or index_path.parent.parent != PUBLICATION_ROOT
            or index_path.parent.name.startswith('.')
            or index_path.parent.is_symlink()):
        raise ReportError('publication is not a direct registered child')
    index, _ = _doc(index_path, label='paired evaluation publication')
    if (set(index) != {
            'schema_version', 'pair_id', 'status', 'report_relpath',
            'report_raw_sha256', 'replay_refs', 'source_refs',
            'grade_replay', 'private_content_exported', 'promotion_authorized'
        } or index['schema_version'] != INDEX_SCHEMA
            or index['pair_id'] != index_path.parent.name
            or index['status'] != 'complete_admitted_pair'
            or index['report_relpath'] != 'report.json'
            or index['grade_replay'] != 'raw_sse_and_all_126_primary_grades_per_cohort'
            or index['private_content_exported'] is not False
            or index['promotion_authorized'] is not False):
        raise ReportError('paired publication identity or claim fields differ')
    report, report_sha = _doc(index_path.parent / 'report.json', label='paired numeric report')
    if (report_sha != index['report_raw_sha256']
            or report.get('schema_version') != SCHEMA
            or report.get('pair_id') != index['pair_id']
            or report.get('status') != 'complete_admitted_pair'
            or report.get('denominator') != 126
            or report.get('private_content_exported') is not False
            or report.get('promotion_authorized') is not False):
        raise ReportError('paired numeric report differs from publication index')
    sources = index['source_refs']
    if not isinstance(sources, dict) or set(sources) != {'plan', 'report_builder', 'resident', 'flash'}:
        raise ReportError('paired source inventory differs')
    if (sources['report_builder'] != {
            'path': str(Path(__file__).absolute()),
            'raw_sha256': manifest.sha256_file(__file__),
        } or sources['plan']['raw_sha256'] != report['plan_raw_sha256']):
        raise ReportError('report builder or plan source differs')
    for cohort in ('resident', 'flash'):
        source = sources[cohort]
        if (not isinstance(source, dict) or set(source) != {
                'window_path', 'window_raw_sha256', 'result_path', 'result_raw_sha256',
                'supervision_path', 'supervision_raw_sha256', 'run_path', 'run_raw_sha256'
            } or Path(source['window_path']).name != 'window.json'
                or Path(source['result_path']).parent != Path(source['window_path']).parent
                or Path(source['supervision_path']).parent != Path(source['window_path']).parent
                or Path(source['run_path']) != Path(source['window_path']).parent / 'evaluation/run.json'):
            raise ReportError(f'{cohort} publication source paths differ')
        replay_ref = index['replay_refs'][cohort]
        if replay_ref['relpath'] != f'{cohort}-replay.json':
            raise ReportError('replay receipt path differs')
        replay, replay_sha = _doc(
            index_path.parent / replay_ref['relpath'], label=f'{cohort} grade replay',
        )
        if (replay_sha != replay_ref['raw_sha256']
                or replay.get('cohort') != cohort
                or replay.get('run_raw_sha256') != source['run_raw_sha256']
                or replay.get('primary_replay_passed') is not True
                or replay.get('primary_cells_replayed') != 126
                or report['cohorts'][cohort]['raw_response_replay_passed'] is not True):
            raise ReportError(f'{cohort} raw/grade replay receipt differs')
        for leaf, digest in (
            ('window_path', 'window_raw_sha256'),
            ('result_path', 'result_raw_sha256'),
            ('supervision_path', 'supervision_raw_sha256'),
            ('run_path', 'run_raw_sha256'),
        ):
            _, actual_sha = _doc(Path(source[leaf]), label=f'{cohort} {leaf}', ceiling=16_000_000)
            if actual_sha != source[digest]:
                raise ReportError(f'{cohort} published source bytes changed')
    _, actual_plan_sha = _doc(Path(sources['plan']['path']), label='published exact plan')
    if actual_plan_sha != sources['plan']['raw_sha256']:
        raise ReportError('published evaluation plan bytes changed')
    load_plan(Path(sources['plan']['path']))
    controller = importlib.import_module('bench.flash_next_ab.lab_window')
    for cohort in ('resident', 'flash'):
        controller.load_window(Path(sources[cohort]['window_path']))
    return report
