"""Deployment admission tests; no model calls, containers or service writes."""
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace
from contextlib import contextmanager

from orchestrator import flash_resident as resident


def test_selected_requires_explicit_owner_decision(tmp_path):
    assert not resident.selected(tmp_path)
    (tmp_path / 'config').mkdir()
    path = tmp_path / 'config/model_deployment.json'
    path.write_text(json.dumps({'topology': 'single_flash', 'production_authorized': False}))
    assert not resident.selected(tmp_path)
    path.write_text((Path(__file__).resolve().parents[1] / 'config/model_deployment.json').read_text())
    assert resident.selected(tmp_path)


def _ready_state(tmp_path):
    path = tmp_path / 'run_state/flash_resident.json'
    path.parent.mkdir()
    state = dict(phase='ready', boot_id=resident.BOOT.read_text().strip(),
                 heartbeat_epoch=time.time(), pid=os.getpid(),
                 process_start_ticks=int(Path('/proc/self/stat').read_text().rsplit(')', 1)[1].split()[19]))
    path.write_text(json.dumps(state))
    return path, state


def test_readiness_rejects_stale_boot_heartbeat_and_wrong_pid(tmp_path, monkeypatch):
    path, state = _ready_state(tmp_path)
    monkeypatch.setattr(resident, 'mem_available_gib', lambda: 25)
    for field, value in [('boot_id', 'old-boot'), ('heartbeat_epoch', 0), ('process_start_ticks', 0), ('phase', 'fault')]:
        path.write_text(json.dumps({**state, field: value}))
        assert not resident.check_ready(tmp_path)


def test_readiness_requires_exact_live_model_and_reserve(tmp_path, monkeypatch):
    _ready_state(tmp_path)
    monkeypatch.setattr(resident, 'mem_available_gib', lambda: 25)
    class Response:
        status = 200
        model = resident.MODEL
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def read(self, size): return json.dumps({'data': [{'id': self.model}]}).encode()
    class Opener:
        def open(self, url, timeout):
            assert url == 'http://127.0.0.1:30080/v1/models'
            return Response()
    monkeypatch.setattr(resident.urllib.request, 'build_opener', lambda *args: Opener())
    assert resident.check_ready(tmp_path)
    Response.model = 'gemma-4-26b-a4b'
    assert not resident.check_ready(tmp_path)
    Response.model = resident.MODEL
    monkeypatch.setattr(resident, 'mem_available_gib', lambda: 19.9)
    assert not resident.check_ready(tmp_path)


def test_nara_flash_admission_does_not_apply_legacy_30g_floor(tmp_path, monkeypatch):
    from orchestrator import nara_daemon
    monkeypatch.setattr(nara_daemon, 'REPO_ROOT', tmp_path)
    monkeypatch.setattr(resident, 'selected', lambda root: True)
    monkeypatch.setattr(resident, 'check_ready', lambda root: True)
    assert nara_daemon._preflight_ok()
    monkeypatch.setattr(resident, 'check_ready', lambda root: False)
    assert not nara_daemon._preflight_ok()


def _service_bundle(tmp_path, monkeypatch, *, startup_failure=False):
    events = []
    monkeypatch.setattr(resident, 'ROOT', tmp_path)
    monkeypatch.setattr(resident, 'STATE', tmp_path / 'run_state/flash_resident.json')
    monkeypatch.setattr(resident, 'PREP', tmp_path / 'bundle')
    (tmp_path / 'bundle/runtime').mkdir(parents=True)
    monkeypatch.setattr(resident, 'selected', lambda: True)
    monkeypatch.setattr(resident, 'wait_docker', lambda stop: None)
    monkeypatch.setattr(resident, 'mem_available_gib', lambda: 120)
    monkeypatch.setattr(resident.signal, 'signal', lambda *args: None)
    class Ops:
        def run(self, argv, **kwargs): events.append(tuple(argv))
    class Monitor:
        def __init__(self, *args): pass
        def start(self): events.append('monitor_start')
        def arm_passive_models(self): pass
        def quiesce(self): events.append('monitor_quiesce')
        def summary(self): return {}
    class Stopper:
        def __init__(self, *args): pass
        def stop(self, reason): events.append('container_stop')
    @contextmanager
    def lease(root):
        events.append('lease_acquire')
        yield ()
        events.append('lease_release')
    def launch(output, receipt, sha, fds):
        assert fds == ()
        events.append('launch')
        return SimpleNamespace(pid=42, poll=lambda: None), SimpleNamespace(close=lambda: None), 123
    def launch_record(*args):
        if startup_failure: raise RuntimeError('before model readiness')
        return {'cid': 'f' * 64}
    def ready(output, monitor, deadline, stop):
        events.append('ready')
        stop.set()  # normal stop after readiness, no real waiting
    def terminated(output, state, process, reason):
        assert state['guard_pid'] == process.pid == 42
        assert state['guard_start_ticks'] == 123
        events.append('guard_terminated')
    bundle = SimpleNamespace(
        canonical_root=lambda root: root,
        verify_control_sources=lambda: {}, inspect_image=lambda ops: {},
        verify_checkpoint_receipt=lambda *args: {}, resource_lease=lease,
        assert_no_fallback_or_transition=lambda ops: None, assert_port_free=lambda: None,
        q=SimpleNamespace(HostOps=Ops, NARA_SERVICE='nara-daemon.service',
                          RESIDENTS=[], _inspect_container=lambda *args: None),
        PREFLIGHT_FLOOR_GIB=104, STARTUP_DEADLINE_S=1800, IMAGE='image',
        launch_guard=launch, wait_launch_record=launch_record,
        capture_candidate_allocator_environment=lambda *args: None,
        GuardStopper=Stopper, RuntimeMonitor=Monitor, wait_ready=ready,
        terminate_guard_process=terminated,
        finalize_owned_fallback=lambda *args: events.append('owned_cleanup') or {},
        endpoint_idle=lambda **kwargs: events.append('endpoint_drained'),
    )
    monkeypatch.setattr(resident, 'load_bundle', lambda: bundle)
    return events


def test_service_releases_transition_lease_before_resuming_research(tmp_path, monkeypatch):
    events = _service_bundle(tmp_path, monkeypatch)
    assert resident.run() == 0
    resume = ('systemctl', '--user', 'start', 'nara-daemon.service')
    assert events.index('ready') < events.index('lease_release') < events.index(resume)
    assert events.index('guard_terminated') < events.index('owned_cleanup')
    assert json.loads(resident.STATE.read_text())['phase'] == 'stopped'


def test_prebind_failure_cleans_guard_and_latches_same_boot(tmp_path, monkeypatch):
    events = _service_bundle(tmp_path, monkeypatch, startup_failure=True)
    assert resident.run() == 1
    assert 'guard_terminated' in events and 'owned_cleanup' in events
    assert ('systemctl', '--user', 'start', 'nara-daemon.service') not in events
    before = list(events)
    assert resident.run() == 78
    assert events == before
