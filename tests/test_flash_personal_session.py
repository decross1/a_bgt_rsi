"""Real guard and launch-policy regressions; no Docker or model calls."""
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from bench.flash_next_ab import personal_session as p


def sample():
    return {'mem_available_gib': 36.55, 'pswpout_pages': 1_000_000,
            'candidate': {'running': True, 'restart_count': 0,
                          'oom_killed': False, 'state_error': ''},
            'cgroup': {'memory_max_bytes': p.SPEC.docker_memory_limit_bytes,
                       'memory_swap_max_bytes': 0, 'memory_swap_current_bytes': 0,
                       'memory_events_oom': 0, 'memory_events_oom_kill': 0}}


def test_host_pageout_alone_does_not_reject_available_responsive_candidate():
    assert p.hard_failure(sample(), 20, 0) is None


def test_candidate_hard_stops_remain_separate_from_host_pageout():
    for key in ('memory_swap_current_bytes', 'memory_events_oom', 'memory_events_oom_kill'):
        row = sample()
        row['cgroup'][key] = 1
        assert p.hard_failure(row, 20, 0) in {'candidate_swap', 'candidate_oom'}
    row = sample()
    row['candidate']['running'] = False
    del row['cgroup']
    assert p.hard_failure(row, 20, 0) == 'candidate_exit_restart_or_oom'


def test_floor_and_sustained_pressure_are_enforced():
    row = sample()
    row['mem_available_gib'] = 19.999
    assert p.hard_failure(row, 20, 0) == 'physical_reserve_breached'
    assert p.hard_failure(row, 12, 0) is None
    assert p.hard_failure(sample(), 20, 29.999) is None
    assert p.hard_failure(sample(), 20, 30) == 'sustained_severe_memory_pressure'


def test_initial_profile_is_the_qualified_bundle_verbatim():
    assert p.argv_for('mtp3-fp32-auto') == p.q.launch_argv(p.SPEC)


def test_profiles_do_not_modify_historical_spec():
    baseline = deepcopy(p.SPEC.identity_snapshot())
    for name, profile in p.PROFILES.items():
        argv = p.argv_for(name)
        assert argv[argv.index('--mamba-ssm-cache-dtype')+1] == profile.recurrent_state
        assert argv[argv.index('--kv-cache-dtype')+1] == profile.kv_cache_dtype
        assert ('--speculative-config' in argv) == bool(profile.mtp)
        assert profile.spec.image_id in argv
    assert p.SPEC.identity_snapshot() == baseline
    assert p.SPEC.identity_sha256() == 'e71d3134f407cad3c288c21f9485c27352676dbb7de647c5b567777256702a50'


def test_mtp_control_preserves_image_and_pins_full_decode_width_one():
    argv = p.argv_for('mtp0-fp32-auto')
    assert p.SPEC.image_id in argv
    assert 'VLLM_USE_V2_MODEL_RUNNER=1' in argv
    assert '"cudagraph_capture_sizes":[1]' in argv[argv.index('--compilation-config')+1]
    assert 'FULL_DECODE_ONLY' in argv[argv.index('--compilation-config')+1]


def test_fp8_child_profiles_bind_exact_overlay_and_change_only_declared_precision():
    child = p.MIA_MTP3_REDUCED47K_FP8_QSA
    assert p.profiles_for_spec(child) == (
        'mtp3-bf16-child-auto', 'mtp3-bf16-child-fp8',
    )
    assert child.image_id == (
        'sha256:ba65a549de4dce8cab70f27c200e408b28470ea175fc8c301e27b4deb154fbed'
    )
    assert str(child.image_build_receipt_path).endswith(
        '/flash-personal-recovery/fp8-runtime-build/build-receipt.json'
    )
    assert child.image_build_receipt_bytes == 4_656
    assert child.image_build_receipt_sha256 == (
        '3a75a795ec167885794a55de29e1a39e537fb0e953508ea9475cfce450e36ebc'
    )
    auto = p.argv_for('mtp3-bf16-child-auto')
    fp8 = p.argv_for('mtp3-bf16-child-fp8')
    for argv, kv in ((auto, 'auto'), (fp8, 'fp8')):
        assert child.image_id in argv
        assert argv[argv.index('--mamba-ssm-cache-dtype')+1] == 'bfloat16'
        assert argv[argv.index('--kv-cache-dtype')+1] == kv
        assert 'VLLM_QSA_EXACT_TOPK=1' in argv
        assert str(child.compile_cache) + ':/root/.cache:rw' in argv
    differing = [(left, right) for left, right in zip(auto, fp8, strict=True) if left != right]
    assert differing == [('auto', 'fp8')]


def test_session_spec_resolution_fails_closed_and_profiles_do_not_cross_images():
    child = p.MIA_MTP3_REDUCED47K_FP8_QSA
    state = {
        'session_spec_id': child.spec_id,
        'session_spec_sha256': child.identity_sha256(),
    }
    assert p._state_spec(state) is child
    state['session_spec_sha256'] = '0' * 64
    with pytest.raises(RuntimeError, match='identity'):
        p._state_spec(state)
    assert p.profiles_for_spec(p.SPEC) == (
        'mtp3-fp32-auto', 'mtp0-fp32-auto', 'mtp3-bf16-auto',
    )


def test_recovery_adopts_created_container_when_receipt_was_interrupted(monkeypatch):
    row = {'id': 'a'*64, 'name': p.SPEC.container_name, 'image': p.SPEC.image_id}
    monkeypatch.setattr(p.q, '_inspect_container', lambda _ops, name: row if name==p.SPEC.container_name else None)
    ops = SimpleNamespace(run=lambda *a, **k: SimpleNamespace(stdout='session-token\n'))
    state = {'candidate_id': None, 'ownership_token': 'session-token'}
    p.reconcile_owned(ops, state, p.SPEC)
    assert state['candidate_id'] == row['id']


def test_recovery_refuses_other_sessions_container(monkeypatch):
    row = {'id': 'a'*64, 'name': p.SPEC.container_name, 'image': p.SPEC.image_id}
    monkeypatch.setattr(p.q, '_inspect_container', lambda _ops, name: row)
    ops = SimpleNamespace(run=lambda *a, **k: SimpleNamespace(stdout='other-token\n'))
    state = {'candidate_id': None, 'ownership_token': 'session-token'}
    with pytest.raises(RuntimeError, match='not_owned'):
        p.reconcile_owned(ops, state, p.SPEC)
    assert state['candidate_id'] is None


def test_recovery_uses_the_state_selected_child_spec(monkeypatch, tmp_path):
    child = p.MIA_MTP3_REDUCED47K_FP8_QSA
    state = {
        'session_spec_id': child.spec_id,
        'session_spec_sha256': child.identity_sha256(),
        'ownership_token': 'session-token',
        'candidate_id': None,
        'initial': {'residents': []},
    }
    observed = {}
    monkeypatch.setattr(p, 'reconcile_owned', lambda _ops, _state, spec: observed.setdefault('reconciled', spec))

    def restore_exact(_ops, _state, *, deadline, spec, diagnostic_path):
        observed.update(spec=spec, deadline=deadline, diagnostic_path=diagnostic_path)
        return {'status': 'verified'}

    monkeypatch.setattr(p.q, 'restore_exact', restore_exact)
    result = p.restore(tmp_path, state)
    assert result == {'status': 'verified'}
    assert observed['reconciled'] is child
    assert observed['spec'] is child
    assert observed['diagnostic_path'] == tmp_path / 'candidate-final.log'


def kernel_monitor(tmp_path, *, stdout='', stderr='', returncode=0):
    monitor = p.Monitor(tmp_path, {'at': '2026-09-19T01:59:29.250000+00:00'}, 20, p.SPEC)
    monitor.ops = SimpleNamespace(run=lambda *a, **k: SimpleNamespace(
        stdout=stdout, stderr=stderr, returncode=returncode,
    ))
    return monitor


@pytest.mark.parametrize('message', [
    'nvAssertFailedNoLog: Assertion failed: status == NV_OK @ mem_desc.c:1359: NV_ERR_NO_MEMORY',
    'NVRM: Xid (PCI:0000:01:00): 31, MMU Fault',
])
def test_kernel_only_driver_fault_is_recorded_and_stops_candidate(tmp_path, message):
    # Container logs, swap, and cgroup OOM counters can all be clear here.
    assert p.hard_failure(sample(), 20, 0) is None
    raw = json.dumps({'__REALTIME_TIMESTAMP': '1789783169251603', 'MESSAGE': message})
    monitor = kernel_monitor(tmp_path, stdout=raw)
    with pytest.raises(RuntimeError, match='kernel_driver_or_allocation_failure'):
        monitor.check_kernel_faults()
    assert json.loads((tmp_path / 'kernel-checks.jsonl').read_text())['stdout'] == raw


def test_kernel_fault_before_session_in_same_second_is_not_reused(tmp_path):
    raw = json.dumps({'__REALTIME_TIMESTAMP': '1789783169249999', 'MESSAGE': 'NV_ERR_NO_MEMORY'})
    kernel_monitor(tmp_path, stdout=raw).check_kernel_faults()


def test_no_matching_kernel_events_is_healthy(tmp_path):
    kernel_monitor(tmp_path, returncode=1).check_kernel_faults()


@pytest.mark.parametrize('response,reason', [
    ({'returncode': 2}, 'unavailable'),
    ({'stderr': 'You are not seeing messages from the system.'}, 'unavailable'),
    ({'stdout': '{'}, 'malformed'),
    ({'stdout': '{}'}, 'malformed'),
])
def test_unreadable_kernel_evidence_is_not_silently_healthy(tmp_path, response, reason):
    with pytest.raises(RuntimeError, match='kernel_fault_evidence_' + reason):
        kernel_monitor(tmp_path, **response).check_kernel_faults()


@pytest.mark.parametrize('running', [True, False])
def test_live_sampling_preserves_kernel_fault_even_if_container_exited(monkeypatch, tmp_path, running):
    monitor = kernel_monitor(tmp_path)
    monitor.state.update(phase='starting', candidate_id='a' * 64)
    row = sample()
    row['candidate']['running'] = running
    row['candidate'].update(image=p.SPEC.image_id, name=p.SPEC.container_name, pid=123)
    monkeypatch.setattr(p.q, '_available_gib', lambda: 36.55)
    monkeypatch.setattr(p.q, '_pswpin_pages', lambda: 0)
    monkeypatch.setattr(p.q, '_pswpout_pages', lambda: 0)
    monkeypatch.setattr(p.q, '_host_meminfo_diagnostics', dict)
    monkeypatch.setattr(p.q, '_inspect_container', lambda *_a: row['candidate'])
    monkeypatch.setattr(p.q, '_candidate_cgroup_snapshot', lambda *_a: row['cgroup'])
    monkeypatch.setattr(p, 'psi', lambda _kind: {'full': {'avg10': 0}})
    monkeypatch.setattr(p, 'process_memory', list)

    def run(argv, **_kwargs):
        if argv[0] == 'docker':
            return SimpleNamespace(returncode=0, stdout='Server running normally', stderr='')
        assert argv[0] == 'journalctl'
        return SimpleNamespace(returncode=0, stderr='', stdout=json.dumps({
            '__REALTIME_TIMESTAMP': '1789783169251603', 'MESSAGE': 'NV_ERR_NO_MEMORY',
        }))

    monitor.ops = SimpleNamespace(run=run)
    if not running:
        # A terminal container failure forces collection even between periodic checks.
        monitor.last_kernel_check = p.time.monotonic()
    with pytest.raises(RuntimeError, match='kernel_driver_or_allocation_failure'):
        monitor.sample()
    assert (tmp_path / 'heartbeat.json').is_file()
    assert (tmp_path / 'memory.jsonl').is_file()
    assert (tmp_path / 'kernel-checks.jsonl').is_file()
