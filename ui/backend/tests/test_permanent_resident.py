import json
import os
import time
from pathlib import Path

from backend.model_runtime_resident import project_permanent
from backend.human_todo import _maintenance_items
from backend.served_models import register
from fastapi import FastAPI
from fastapi.testclient import TestClient


def deployment(root):
    (root / 'config').mkdir()
    (root / 'run_state').mkdir()
    (root / 'config/model_deployment.json').write_text(json.dumps({
        'topology': 'single_flash', 'production_authorized': True,
        'model': 'nvidia/Qwen3.8-Flash-Next-NVFP4',
        'base_url': 'http://127.0.0.1:30080/v1',
    }))


def test_selection_does_not_claim_ready_without_current_supervisor(tmp_path):
    deployment(tmp_path)
    assert project_permanent(tmp_path)['phase'] == 'awaiting_start'
    path = tmp_path / 'run_state/flash_resident.json'
    row = dict(phase='ready', boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
               heartbeat_epoch=time.time(), pid=os.getpid(),
               process_start_ticks=int(Path('/proc/self/stat').read_text().rsplit(')', 1)[1].split()[19]))
    path.write_text(json.dumps(row))
    assert project_permanent(tmp_path)['mode'] == 'resident'
    path.write_text(json.dumps({**row, 'heartbeat_epoch': 0}))
    assert project_permanent(tmp_path)['phase'] == 'unverified'
    path.write_text(json.dumps({**row, 'phase': 'fault', 'error': 'driver allocation fault'}))
    value = project_permanent(tmp_path)
    assert value['mode'] == 'unknown'
    assert value['source_error'] == 'driver allocation fault'


def test_inventory_uses_sglang_for_selected_but_offline_resident():
    app = FastAPI()
    urls = []
    def offline(url, **kwargs):
        urls.append(url)
        raise OSError('offline')
    register(app, opener=offline, runtime_projector=lambda: {
        'mode_source': 'permanent_deployment', 'production_authorized': True,
        'phase': 'fault', 'candidate_id': None,
    })
    rows = TestClient(app).get('/api/served_models').json()
    assert rows['flash']['url'] == 'http://127.0.0.1:30080'
    assert rows['flash']['service_status'] == 'offline'
    assert rows['flash']['deployment_role'] == 'production_resident'
    assert rows['flash']['promotion_authorized'] is True
    assert rows['gemma']['deployment_role'] == 'rollback_available'
    assert rows['qwen']['deployment_role'] == 'rollback_available'
    assert not any(':8012' in url for url in urls)


def test_reboot_todo_visible_until_explicitly_closed(tmp_path):
    path = tmp_path / 'maintenance_todos.json'
    item = dict(id='reboot', title='Schedule Spark reboot', status='open', detail='Owner chooses time', next_action='Review service audit')
    path.write_text(json.dumps({'items': [item]}))
    assert _maintenance_items(tmp_path)[0]['id'] == 'reboot'
    path.write_text(json.dumps({'items': [{**item, 'status': 'closed'}]}))
    assert _maintenance_items(tmp_path) == []
