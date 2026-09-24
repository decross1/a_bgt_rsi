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
    # 2026-09-21 owner floor: an SSH session at 15 GiB available stays ready.
    monkeypatch.setattr(resident, 'mem_available_gib', lambda: 15)
    assert resident.check_ready(tmp_path)
    monkeypatch.setattr(resident, 'mem_available_gib', lambda: 9.9)
    assert not resident.check_ready(tmp_path)


def test_pinned_bundle_enforces_owner_reserve():
    import hashlib
    import pytest
    if not resident.BUNDLE.exists():
        pytest.skip('host-specific serving bundle is absent')
    raw = resident.BUNDLE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == resident.BUNDLE_SHA
    text = raw.decode()
    import re
    floor = float(re.search(r'\nHOST_FLOOR_GIB = ([0-9.]+)\n', text).group(1))
    guard = float(re.search(r'"--mem-available-floor-gib", "([0-9.]+)",', text).group(1))
    config = json.loads((resident.ROOT / 'config/model_deployment.json').read_text())
    assert resident.HOST_RESERVE_GIB == floor == config['host_reserve_gib'] == 10
    # The guard is a backstop below the monitor, inside guard.py's [4, 16] range.
    assert 4.0 <= guard < floor and guard / 2 >= 4.0
    assert f'record.get("mem_available_floor_gib") != {guard}' in text


def test_pinned_bundle_serves_the_deployed_c4_profile():
    import hashlib
    import re
    import pytest
    if not resident.BUNDLE.exists():
        pytest.skip('host-specific serving bundle is absent')
    text = resident.BUNDLE.read_text()
    config = json.loads((resident.ROOT / 'config/model_deployment.json').read_text())
    profile_sha = re.search(r'\nPROFILE_SHA256 = "([0-9a-f]{64})"\n', text).group(1)
    profile_name = re.search(r'\nPROFILE = BASE / "([^"]+)"\n', text).group(1)
    profile = resident.PREP / profile_name
    assert profile_sha == config['profile_sha256'] == hashlib.sha256(profile.read_bytes()).hexdigest()
    loaded = json.loads(profile.read_text())
    assert (loaded['max_running_requests'] == config['max_running_requests']
            == resident.BUNDLE_MAX_RUNNING_REQUESTS == 4)
    # SGLang caps running requests at max_mamba_cache_size // 5 on this model.
    assert loaded['max_mamba_cache_size'] == 24 and loaded['max_mamba_cache_size'] // 5 >= 4
    # Live readiness admits only a server that reports four uncapped running
    # requests in the full 262K pool.
    readiness = text[text.index('def server_profile()'):text.index('def raise_if_startup_stop_requested')]
    assert '"max_running_requests": 4,' in readiness and '"max_total_tokens": 262144,' in readiness
    assert '"max_mamba_cache_size": 24,' in readiness
    assert '"internal_states[0].effective_max_running_requests_per_dp", 4,' in readiness
    assert 'if value.get("max_total_num_tokens") != 262144:' in readiness


def _selected_with(tmp_path, **changes):
    (tmp_path / 'config').mkdir(exist_ok=True)
    manifest = json.loads((Path(__file__).resolve().parents[1] / 'config/model_deployment.json').read_text())
    for key, value in changes.items():
        if value is _DROP:
            manifest.pop(key)
        else:
            manifest[key] = value
    (tmp_path / 'config/model_deployment.json').write_text(json.dumps(manifest))
    return resident.selected(tmp_path)


_DROP = object()


def test_selected_binds_running_requests_to_the_pinned_profile(tmp_path):
    import pytest
    assert _selected_with(tmp_path, max_running_requests=4)
    # C1 and C2 are valid deployment counts, but not for the pinned C4 profile.
    for running in (1, 2):
        with pytest.raises(ValueError, match='reviewed serving bundle'):
            _selected_with(tmp_path, max_running_requests=running)
    # Counts without a reviewed profile fail in the deployment loader.
    for running in (3, 8, True, _DROP):
        with pytest.raises(ValueError, match='max_running_requests'):
            _selected_with(tmp_path, max_running_requests=running)


def test_selected_rejects_a_stale_profile_digest(tmp_path):
    import pytest
    c2 = '495f1f3c59f559185720257538646354a5995ab9ca82e042565ae989ca4452a3'
    with pytest.raises(ValueError, match='reviewed serving bundle'):
        _selected_with(tmp_path, profile_sha256=c2)


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
    monkeypatch.setattr(resident, 'host_memory_kib',
                        lambda: {'MemFree': 118 * 1024**2, 'MemAvailable': 118 * 1024**2, 'Cached': 1024**2})
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
        MODEL_ROOT=tmp_path / 'model', CACHE=tmp_path / 'bundle/runtime/cache',
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


def test_handoff_state_skips_previous_helper_cleanup(tmp_path, monkeypatch):
    events = _service_bundle(tmp_path, monkeypatch)
    bundle = resident.load_bundle()
    cleaned = []
    bundle.finalize_owned_fallback = lambda output, *args: cleaned.append(output.name) or {}
    resident.STATE.parent.mkdir(parents=True)
    old = tmp_path / 'bundle/runtime/resident-old'
    resident.STATE.write_text(json.dumps({'phase': 'stopped', 'launch_attempted': True,
                                          'prior_artifact_dir': str(old)}))
    assert resident.run() == 0
    state = json.loads(resident.STATE.read_text())
    assert cleaned == [Path(state['artifact_dir']).name] and 'resident-old' not in cleaned
    assert state['bundle_sha256'] == resident.BUNDLE_SHA
    assert state['host_reserve_gib'] == resident.HOST_RESERVE_GIB
    assert 'launch' in events


def test_helper_mismatch_requires_handoff(tmp_path, monkeypatch):
    events = _service_bundle(tmp_path, monkeypatch)
    resident.STATE.parent.mkdir(parents=True)
    old = tmp_path / 'bundle/runtime/resident-old'
    resident.STATE.write_text(json.dumps({'phase': 'stopped', 'artifact_dir': str(old),
                                          'bundle_sha256': 'a' * 64}))
    record = resident.STATE.read_text()
    assert resident.run() == 1
    assert resident.run() == 1  # the old record is kept, so a retry refuses too
    assert resident.STATE.read_text() == record and events == []  # no lease, no launch, no latch
    import pytest
    with pytest.raises(RuntimeError, match='helper handoff required'):
        resident.cleanup()
    resident.STATE.write_text(json.dumps({'phase': 'stopped', 'artifact_dir': str(old)}))  # pre-v8 record
    assert resident.run() == 1 and events == []
    with pytest.raises(RuntimeError, match='helper handoff required'):
        resident.cleanup()


def test_prelaunch_free_memory_gate_refuses_without_arming_latch(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone
    events = _service_bundle(tmp_path, monkeypatch)
    ticks = [datetime(2026, 9, 21, 16, 0, tzinfo=timezone.utc)]

    class Clock:  # distinct per-run artifact directory names
        @staticmethod
        def now(tz=None):
            ticks[0] += timedelta(seconds=1)
            return ticks[0]
    monkeypatch.setattr(resident, 'datetime', Clock)
    monkeypatch.setattr(resident, 'PRELAUNCH_WAIT_S', 0)
    monkeypatch.setattr(resident, 'host_memory_kib',
                        lambda: {'MemFree': 77 * 1024**2, 'MemAvailable': 118 * 1024**2, 'Cached': 38 * 1024**2})
    assert resident.run() == 1
    state = json.loads(resident.STATE.read_text())
    assert 'prelaunch MemFree below' in state['error'] and 'launch' not in events
    assert not state.get('launch_attempted') and state['prelaunch']['meminfo_kib']['MemFree'] == 77 * 1024**2
    monkeypatch.setattr(resident, 'host_memory_kib',
                        lambda: {'MemFree': 118 * 1024**2, 'MemAvailable': 118 * 1024**2, 'Cached': 1024**2})
    resident.STATE.write_text(json.dumps({**state, 'pid': 2**22 + 1}))  # the refused supervisor exited
    assert resident.run() == 0  # a refused launch leaves the next start admitted
    assert 'launch' in events


def test_evict_model_page_cache_drops_only_large_regular_files(tmp_path, monkeypatch):
    big = tmp_path / 'model/model-00001-of-00010.safetensors'
    big.parent.mkdir()
    with big.open('wb') as handle:
        handle.truncate(64 * 1024**2)  # sparse; size is what matters
    (tmp_path / 'model/config.json').write_text('{}')
    (tmp_path / 'model/link.safetensors').symlink_to(big)
    calls = []
    monkeypatch.setattr(resident.os, 'posix_fadvise', lambda fd, off, length, advice: calls.append(advice))
    assert resident.evict_model_page_cache((tmp_path / 'model', tmp_path / 'absent')) == 1
    assert calls == [resident.os.POSIX_FADV_DONTNEED]


def test_prelaunch_gate_waits_for_free_memory_then_launches(tmp_path, monkeypatch):
    events = _service_bundle(tmp_path, monkeypatch)
    readings = iter([60, 60, 110])  # e.g. unrelated host cache until the next cache drop
    monkeypatch.setattr(resident, 'host_memory_kib',
                        lambda: {'MemFree': next(readings) * 1024**2, 'MemAvailable': 118 * 1024**2, 'Cached': 1})
    waits = []
    monkeypatch.setattr(resident.threading.Event, 'wait', lambda self, timeout=None: waits.append(timeout) or self.is_set())
    monkeypatch.setattr(resident.LoadEvictor, 'start', lambda self: None)  # its wait is patched too; don't spin
    assert resident.run() == 0
    state = json.loads(resident.STATE.read_text())
    assert state['prelaunch']['waits'] == 2 and waits[:2] == [30, 30] and 'launch' in events


def test_load_evictor_runs_during_startup_and_stops_at_readiness(tmp_path, monkeypatch):
    events = _service_bundle(tmp_path, monkeypatch)
    seen = []
    monkeypatch.setattr(resident, 'evict_model_page_cache', lambda roots: seen.append(tuple(roots)) or 0)
    monkeypatch.setattr(resident.LoadEvictor, '__init__',
                        lambda self, root, interval=0.01: _init_evictor(self, root, interval))
    bundle = resident.load_bundle()
    stop_at_ready = bundle.wait_ready

    def ready_after_one_pass(output, monitor, deadline, stop):  # the model "loads" until one pass is seen
        for _ in range(500):
            if any(len(roots) == 1 for roots in seen):
                break
            __import__('time').sleep(0.01)
        stop_at_ready(output, monitor, deadline, stop)
    bundle.wait_ready = ready_after_one_pass
    assert resident.run() == 0
    state = json.loads(resident.STATE.read_text())
    assert state['load_eviction']['errors'] == [] and state['load_eviction']['passes'] >= 1
    assert not any(t.name == 'load-evictor' and t.is_alive() for t in __import__('threading').enumerate())
    prelaunch = [roots for roots in seen if len(roots) == 2]
    during_load = [roots for roots in seen if len(roots) == 1]
    assert prelaunch == [(tmp_path / 'model', tmp_path / 'bundle/runtime/cache')]
    assert during_load and all(roots == (tmp_path / 'model',) for roots in during_load)  # never the PLE cache
    assert 'launch' in events


def _init_evictor(self, root, interval):
    import threading
    self.root, self.interval = root, interval
    self.done = threading.Event()
    self.passes = 0
    self.errors = []
    self.thread = threading.Thread(target=self._loop, name='load-evictor', daemon=True)

