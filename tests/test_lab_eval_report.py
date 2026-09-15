"""Source-bound numeric reporting keeps failed calls and private data out."""
from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from bench.flash_next_ab import lab_eval_plan as plan_mod
from bench.flash_next_ab import lab_eval_report as report
from bench.flash_next_ab import lab_eval_runner as runner
from bench.flash_next_ab import manifest


def test_family_metrics_include_timeouts_and_all_declared_denominators():
    family = report._family({'outcomes': [
        {'family': 'objective', 'status': 'returned', 'passed': True,
         'calls': [{'status': 'returned'}], 'wall_s': 1.5},
        {'family': 'objective', 'status': 'timeout', 'passed': False,
         'calls': [{'status': 'timeout'}], 'wall_s': 75.0},
        {'family': 'historical', 'status': 'error', 'passed': False,
         'calls': [{'status': 'error'}], 'wall_s': 3.0},
    ]})
    assert family['objective'] == {
        'declared': 2, 'attempted': 2, 'returned': 1,
        'timeout': 1, 'error': 0, 'cancelled': 0, 'passed': 1,
        'wall_s_including_failures': 76.5,
    }
    assert family['historical']['declared'] == 1
    assert family['historical']['error'] == 1


def test_publication_reader_rejects_unregistered_path_before_read(tmp_path: Path):
    outside = tmp_path / 'index.json'
    outside.write_text('{}')
    with pytest.raises(report.ReportError, match='direct registered child'):
        report.read_publication(outside)


def test_producer_shaped_complete_pair_replay_and_forged_numeric_rejection(tmp_path: Path,
                                                                           monkeypatch):
    plan_path = tmp_path / 'plan.json'
    plan_mod.freeze_plan(plan_path)
    _, _, plan_raw_sha = plan_mod.load_plan(plan_path)
    pair_id = 'qfn-ab-report-test'

    def gate(value: dict, cohort: str) -> dict:
        cert = value['runtime_certificates'][cohort]
        names = {name for routes in value['call_routes'][cohort].values()
                 for name in routes}
        return {
            'schema_version': 'lab-model-eval-admission/v1',
            'admitted': True, 'cohort': cohort,
            'window_id': pair_id, 'plan_sha256': manifest.sha256_json(value),
            'certificate_sha256': cert['parent_sha256'] if cohort == 'flash'
                                  else cert['receipt_sha256'],
            'endpoint_identities': {
                name: {key: value['endpoints'][name][key]
                       for key in ('served_model', 'artifact_sha256', 'runtime_sha256')}
                for name in names
            },
            'candidate_spec_sha256': cert['candidate_spec_sha256'] if cohort == 'flash' else None,
            'monitor_armed': True, 'controller_source_bundle_sha256': 'a' * 64,
            'ready_proof_sha256': 'b' * 64,
        }

    def timeout(*args, **kwargs):
        raise TimeoutError('synthetic local timeout')

    windows = {}
    for cohort in ('resident', 'flash'):
        output = tmp_path / f'{pair_id}.{cohort}'
        output.mkdir()
        run = runner.run(
            plan_path, cohort=cohort, output_dir=output / 'evaluation',
            runtime_budget_s=300, admission_gate=gate,
            cancel_event=threading.Event(), invoke_fn=timeout,
        )
        assert run['status'] == 'complete'
        window_path = output / 'window.json'
        window = {
            'window_id': pair_id, 'cohort': cohort,
            'evaluation_kind': 'primary', 'output_dir': str(output),
            'evaluation_plan': {'path': str(plan_path), 'sha256': plan_raw_sha},
            'code_root': str(tmp_path),
            'controller_sources': {'bench/flash_next_ab/lab_window.py': {
                'path': str(tmp_path / 'bench/flash_next_ab/lab_window.py'),
                'sha256': 'a' * 64,
            }},
        }
        window_path.write_bytes(manifest.canonical_json(window) + b'\n')
        window_sha = manifest.sha256_file(window_path)
        restoration = {'status': 'verified', 'errors': [], 'sentinel_retained': False}
        (output / 'state.json').write_bytes(manifest.canonical_json({
            'phase': 'complete', 'window_sha256': window_sha,
            'restoration': restoration,
        }) + b'\n')
        (output / 'result.json').write_bytes(manifest.canonical_json({
            'cohort': cohort, 'status': 'complete', 'window_sha256': window_sha,
            'restoration': restoration,
            'evaluation_run_sha256': manifest.sha256_file(output / 'evaluation/run.json'),
        }) + b'\n')
        (output / 'supervision.json').write_bytes(manifest.canonical_json({
            'schema': 'lab-model-supervision/v1', 'window_sha256': window_sha,
            'returncode': 0, 'interrupted': None,
            'terminated_at_cutoff': False, 'emergency_restoration': None,
        }) + b'\n')
        windows[cohort] = window_path

    class FakeController:
        def load_window(self, path):
            return json.loads(path.read_bytes()), SimpleNamespace()

    monkeypatch.setattr(report.importlib, 'import_module', lambda _name: FakeController())
    publications = tmp_path / 'publications'
    publications.mkdir()
    monkeypatch.setattr(report, 'PUBLICATION_ROOT', publications)
    output = publications / pair_id
    report.publish(plan_path, windows['resident'], windows['flash'], output_dir=output)
    admitted = json.loads((output / 'report.json').read_bytes())
    assert admitted['cohorts']['resident']['timeout'] == 126
    assert admitted['cohorts']['flash']['timeout'] == 126
    assert admitted['cohorts']['resident']['attempted'] == 126
    forged = dict(admitted)
    forged['cohorts']['resident']['passed'] = 1
    forged_raw = manifest.canonical_json(forged) + b'\n'
    (output / 'report.json').write_bytes(forged_raw)
    index = json.loads((output / 'index.json').read_bytes())
    index['report_raw_sha256'] = hashlib.sha256(forged_raw).hexdigest()
    (output / 'index.json').write_bytes(manifest.canonical_json(index) + b'\n')
    with pytest.raises(report.ReportError, match='numeric family/total'):
        report.read_publication(output / 'index.json')
