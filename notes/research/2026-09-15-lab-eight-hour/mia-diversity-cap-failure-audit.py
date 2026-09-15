"""One-time, content-free failed cap window audit; never rewrites source evidence."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from pathlib import Path

ART = Path('/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-15/lab-eight-hour')
OUT = ART / 'model-windows/qfn-ab-lab-diversity-cap-20260915-a.flash'
CODE = Path('/home/decross1/projects/a_bgt_rsi_worktrees/lab-diversity-cap-20260915')
DEST = ART / 'mia-diversity-cap-paired-v1.failure-audit.json'
SOURCE = ART / 'mia-diversity-cap-paired-v1.failure-audit-source.py'


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def read(path: Path, limit: int = 64_000_000) -> tuple[dict, bytes]:
    assert path.is_file() and not path.is_symlink() and path.stat().st_size <= limit, path
    raw = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}, raw


def document(path: Path, limit: int = 64_000_000) -> tuple[dict, dict]:
    ref, raw = read(path, limit)
    value = json.loads(raw)
    assert isinstance(value, dict), path
    return ref, value


def main() -> None:
    assert not DEST.exists() and not DEST.is_symlink()
    assert not SOURCE.exists() and not SOURCE.is_symlink()
    plan_ref, plan = document(ART / 'mia-diversity-cap-paired-v1.plan.json', 2_000_000)
    window_ref, window = document(OUT / 'window.json', 2_000_000)
    state_ref, state = document(OUT / 'state.json', 2_000_000)
    result_ref, result = document(OUT / 'result.json', 2_000_000)
    supervision_ref, supervision = document(OUT / 'supervision.json', 2_000_000)
    start_ref, start = document(OUT / 'supervision-start.json', 2_000_000)
    verification_ref, _ = document(OUT / 'model-verification.json', 2_000_000)
    memory_ref, memory_raw = read(OUT / 'memory.jsonl', 32_000_000)
    candidate_ref, _ = read(OUT / 'candidate.log')
    controller_ref, _ = read(OUT / 'controller.log')

    assert plan_ref['sha256'] == 'f1250b9c1965f9be99790153f63263c4240ed88aca44fc535abb7d8130c90f45'
    assert window_ref['sha256'] == '765768788240c6f25ded459c98534aa771b06cb9b2408c33d3c0c43ea8e44287'
    assert window['evaluation_kind'] == 'diversity_cap' and window['cohort'] == 'flash'
    assert window['code_root'] == str(CODE) and window['candidate_spec_id'] == 'mia-925d7be6-mtp3-reduced47k-v2opt-v1'
    assert window['evaluation_plan'] == {'path': plan_ref['path'], 'sha256': plan_ref['sha256']}
    assert all(row['window_sha256'] == window_ref['sha256'] for row in (state, result, supervision, start))
    assert state['phase'] == result['status'] == 'aborted'
    assert result['error'] == 'QualificationError: startup host swap reached the 5-second byte threshold'
    assert result['evaluation_run_sha256'] is None
    assert not (OUT / 'evaluation').exists() and not (OUT / 'evaluation').is_symlink()
    assert supervision['returncode'] == 1 and supervision['interrupted'] is None
    assert supervision['terminated_at_cutoff'] is False and supervision['emergency_restoration'] is None
    restoration = result['restoration']
    assert state['restoration'] == restoration
    assert restoration['status'] == 'verified' and restoration['errors'] == []
    assert restoration['diagnostic_errors'] == [] and restoration['sentinel_retained'] is False
    assert datetime.fromisoformat(restoration['verified_at']).utcoffset().total_seconds() == 0
    assert start['pid'] == state['worker_pid'] and start['worker_pid'] == state['worker_pid']
    assert start['worker_start_ticks'] == state['worker_start_ticks'] and start['boot_id'] == state['boot_id']
    assert type(result['memory_samples']) is int and result['memory_samples'] > 0

    plan_sources = plan['evaluator_source_bundle']
    window_sources = window['controller_sources']
    assert len(plan_sources) == 16 and len(window_sources) == 45
    for name, digest in plan_sources.items():
        ref, _ = read(CODE / name, 4_000_000)
        assert ref['sha256'] == digest, name
    for name, expected in window_sources.items():
        ref, _ = read(CODE / name, 4_000_000)
        assert expected == {'path': ref['path'], 'sha256': ref['sha256']}, name
    keys = ('bench/flash_next_ab/lab_eval_diversity_cap.py',
            'bench/flash_next_ab/lab_window.py',
            'bench/flash_next_ab/qualification.py',
            'bench/flash_next_ab/candidate_registry.py')
    assert all(name in window_sources for name in keys)
    assert 'LOAD_SWAP_5S_BREACH_BYTES = 512 * 1024**2' in (CODE / keys[2]).read_text()
    assert '"window_5s_breach_bytes":536870912' in (CODE / keys[3]).read_text()

    rows = [json.loads(line) for line in memory_raw.splitlines()]
    assert rows and all(isinstance(row, dict) for row in rows)
    assert not any(row.get('monitor_phase') == 'evaluation' for row in rows)
    prior, breach, stop = rows[439], rows[440], rows[441]
    five = 512 * 1024**2
    minute = 2 * 1024**3
    total = 4 * 1024**3
    assert prior['schema'] == breach['schema'] == 'qwen-flash-next-memory-sample/v3'
    assert breach['monitor_phase'] == 'load' and breach['paging_gate'] == 'startup'
    assert breach['observed_at'] == '2026-09-15T22:35:29.879911+00:00'
    assert prior['host_swap_5s_bytes'] < five <= breach['host_swap_5s_bytes']
    assert breach['host_swap_60s_bytes'] < minute and breach['gate_pswpout_delta_bytes'] < total
    assert breach['host_page_size_bytes'] == 4096
    assert breach['gate_pswpout_delta_pages'] * 4096 == breach['gate_pswpout_delta_bytes']
    assert math.isfinite(breach['mem_available_gib']) and breach['mem_available_gib'] >= 20
    candidate = breach['candidate']
    cgroup = candidate['cgroup']
    assert candidate['id'] == state['candidate_id'] and candidate['running'] is True
    assert candidate['oom_killed'] is False and candidate['restart_count'] == 0
    assert cgroup['memory_swap_current_bytes'] == 0
    assert cgroup['memory_events_oom'] == cgroup['memory_events_oom_kill'] == 0
    assert stop['event'] == 'emergency_candidate_stop' and stop['candidate_id'] == state['candidate_id']
    assert stop['returncode'] == 0 and stop['observed_at'] == '2026-09-15T22:35:41.611257+00:00'
    assert result['minimum_mem_available_gib'] >= 20

    source_raw = Path(__file__).read_bytes()
    source_ref = {'path': str(SOURCE), 'sha256': hashlib.sha256(source_raw).hexdigest(),
                  'bytes': len(source_raw)}
    report = {
        'schema': 'lab-mia-diversity-cap-startup-failure-audit/v1',
        'window_id': window['window_id'],
        'status': 'closed_aborted_restored_no_evaluation',
        'audit_source': source_ref,
        'registered': {
            'plan': plan_ref, 'window': window_ref,
            'candidate_spec_id': window['candidate_spec_id'],
            'candidate_spec_sha256': window['candidate_spec_sha256'],
            'evaluator_source_bundle_sha256': hashlib.sha256(canonical(plan_sources)).hexdigest(),
            'controller_source_bundle_sha256': hashlib.sha256(canonical(window_sources)).hexdigest(),
            'source_refs_checked': len(plan_sources) + len(window_sources),
            'source_refs_unique': len(set(plan_sources) | set(window_sources)),
            'key_sources': {name: window_sources[name] for name in keys},
        },
        'raw_refs': {
            'state': state_ref, 'result': result_ref, 'supervision': supervision_ref,
            'supervision_start': start_ref, 'model_verification': verification_ref,
            'memory': memory_ref, 'candidate_log': candidate_ref,
            'controller_log': controller_ref,
        },
        'trigger': {
            'memory_row_index_zero_based': 440,
            'prior_row_index_zero_based': 439,
            'stop_row_index_zero_based': 441,
            'at': breach['observed_at'], 'monitor_phase': 'load',
            'paging_gate': 'startup',
            'host_swap_5s_bytes': breach['host_swap_5s_bytes'],
            'host_swap_5s_limit_bytes': five,
            'host_swap_5s_excess_bytes': breach['host_swap_5s_bytes'] - five,
            'host_swap_60s_bytes': breach['host_swap_60s_bytes'],
            'host_swap_60s_limit_bytes': minute,
            'gate_total_bytes': breach['gate_pswpout_delta_bytes'],
            'gate_total_limit_bytes': total,
            'mem_available_gib': breach['mem_available_gib'],
            'required_mem_available_gib': 20,
            'candidate_cgroup_swap_bytes': 0,
            'candidate_cgroup_oom_events': 0,
            'candidate_cgroup_oom_kill_events': 0,
            'candidate_oom_killed': False,
            'candidate_restart_count': 0,
            'emergency_stop_at': stop['observed_at'],
            'emergency_stop_returncode': 0,
            'host_paging_attribution': 'host_wide_not_candidate_attributable_from_this_evidence',
        },
        'evaluation': {
            'declared_calls': 40, 'issued_calls': 0,
            'evaluation_run_present': False,
            'evaluation_directory_present': False,
            'memory_evaluation_phase_samples': 0,
            'quality_status': 'unmeasured',
        },
        'terminal': {
            'result_status': 'aborted',
            'result_error_code': 'startup_host_swap_5s',
            'supervisor_returncode': 1,
            'supervisor_interrupted': False,
            'supervisor_emergency_restoration': False,
            'restoration_status': 'verified',
            'restoration_verified_at': restoration['verified_at'],
            'restoration_errors_count': 0,
            'restoration_diagnostic_errors_count': 0,
            'sentinel_retained': False,
            'originals_exact_restoration_verified': True,
        },
        'claim_limit': 'startup_guard_failure_no_cap_quality_inference_no_retry_no_primary_rescore',
        'private_content_exported': False,
    }
    with SOURCE.open('xb') as file:
        file.write(source_raw)
    with DEST.open('x', encoding='utf-8') as file:
        file.write(canonical(report).decode() + '\n')
    print(json.dumps({'path': str(DEST), 'sha256': hashlib.sha256(DEST.read_bytes()).hexdigest(),
                      'audit_source_sha256': source_ref['sha256'],
                      'source_refs_checked': report['registered']['source_refs_checked'],
                      'memory_rows': len(rows), 'issued_calls': 0,
                      'restoration': 'verified'}))


if __name__ == '__main__':
    main()
