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
    for name, (mtp, state, kv) in p.PROFILES.items():
        argv = p.argv_for(name)
        assert argv[argv.index('--mamba-ssm-cache-dtype')+1] == state
        assert argv[argv.index('--kv-cache-dtype')+1] == kv
        assert ('--speculative-config' in argv) == bool(mtp)
    assert p.SPEC.identity_snapshot() == baseline


def test_mtp_control_preserves_image_and_pins_full_decode_width_one():
    argv = p.argv_for('mtp0-fp32-auto')
    assert p.SPEC.image_id in argv
    assert 'VLLM_USE_V2_MODEL_RUNNER=1' in argv
    assert '"cudagraph_capture_sizes":[1]' in argv[argv.index('--compilation-config')+1]
    assert 'FULL_DECODE_ONLY' in argv[argv.index('--compilation-config')+1]


def test_recovery_adopts_created_container_when_receipt_was_interrupted(monkeypatch):
    row = {'id': 'a'*64, 'name': p.SPEC.container_name, 'image': p.SPEC.image_id}
    monkeypatch.setattr(p.q, '_inspect_container', lambda _ops, name: row if name==p.SPEC.container_name else None)
    ops = SimpleNamespace(run=lambda *a, **k: SimpleNamespace(stdout='session-token\n'))
    state = {'candidate_id': None, 'ownership_token': 'session-token'}
    p.reconcile_owned(ops, state)
    assert state['candidate_id'] == row['id']


def test_recovery_refuses_other_sessions_container(monkeypatch):
    row = {'id': 'a'*64, 'name': p.SPEC.container_name, 'image': p.SPEC.image_id}
    monkeypatch.setattr(p.q, '_inspect_container', lambda _ops, name: row)
    ops = SimpleNamespace(run=lambda *a, **k: SimpleNamespace(stdout='other-token\n'))
    state = {'candidate_id': None, 'ownership_token': 'session-token'}
    with pytest.raises(RuntimeError, match='not_owned'):
        p.reconcile_owned(ops, state)
    assert state['candidate_id'] is None
