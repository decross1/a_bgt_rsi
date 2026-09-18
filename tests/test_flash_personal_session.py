"""Real guard and launch-policy regressions; no Docker or model calls."""
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
