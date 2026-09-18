"""Owner-authorized warm Flash development session, separate from old grades.

The parent holds the ordinary resource lease throughout startup, requests,
profile changes and restoration. The worker produces a heartbeat; a stalled
worker is killed and the parent restores the captured resident IDs. No old
qualification policy, receipt, grade, or production route is modified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.request
import uuid
from collections import deque
from pathlib import Path

from orchestrator.weekly_upgrade_trial import canonical_root, resource_lease

from . import qualification as q
from .followon_profiles import MIA_MTP3_REDUCED47K_OPT as SPEC

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = Path('/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-18/flash-personal-recovery')
PROFILES = {
    'mtp3-fp32-auto': (3, 'float32', 'auto'),
    'mtp0-fp32-auto': (0, 'float32', 'auto'),
    'mtp3-bf16-auto': (3, 'bfloat16', 'auto'),
}
OWNER_LABEL = 'oracle.flash.personal-session'
TRANSITION_NAME = 'vllm-qwen-ab-personal-transition'
POLICY = {
    'schema': 'flash-personal-startup-policy/v1',
    'startup_deadline_s': 1800,
    'candidate_swap_bytes': 0,
    'candidate_oom_events': 0,
    'host_pageout_action': 'record_and_attribute_not_an_independent_abort',
    'memory_psi_full_avg10_percent': 25,
    'severe_pressure_duration_s': 30,
    'worker_heartbeat_max_age_s': 45,
    'restoration_reserve_s': 900,
    'weekly_budget_debit': False,
}
FAULT = re.compile(r'CUDA out of memory|CUDA error:|illegal memory access|Segmentation fault|OutOfMemoryError')


def write(path: Path, value):
    q._atomic_write(path, value)


def append(path: Path, value):
    with path.open('a') as f:
        f.write(json.dumps(value, sort_keys=True) + '\n')


def argv_for(profile: str) -> list[str]:
    """Derive explicit new arms without changing the historical CandidateSpec."""
    mtp, state, kv = PROFILES[profile]
    argv = q.launch_argv(SPEC)
    argv[argv.index('--mamba-ssm-cache-dtype') + 1] = state
    argv[argv.index('--kv-cache-dtype') + 1] = kv
    if not mtp:
        index = argv.index('--speculative-config')
        del argv[index:index+2]
        # One verified token per step requires width 1, versus 1+3 for MTP3.
        argv[argv.index('--compilation-config') + 1] = json.dumps({
            'cudagraph_capture_sizes': [1], 'cudagraph_mode': 'FULL_DECODE_ONLY', 'mode': 0,
        }, separators=(',', ':'))
    return argv


def psi(kind: str) -> dict:
    result = {}
    for line in Path('/proc/pressure/' + kind).read_text().splitlines():
        fields = line.split()
        result[fields[0]] = {k: float(v) for k, v in (f.split('=') for f in fields[1:])}
    return result


def process_memory() -> list[dict]:
    """RSS/swap attribution is observational; GPU allocations need cgroups too."""
    rows = []
    for path in Path('/proc').glob('[0-9]*/status'):
        try:
            values = dict(line.split(':', 1) for line in path.read_text().splitlines() if ':' in line)
            swap = int(values.get('VmSwap', '0 kB').split()[0]) * 1024
            rss = int(values.get('VmRSS', '0 kB').split()[0]) * 1024
            if swap or rss > 128 * 1024**2:
                rows.append({'pid': int(path.parent.name), 'name': values['Name'].strip(),
                             'rss_bytes': rss, 'swap_bytes': swap})
        except (OSError, ValueError, KeyError):
            continue
    return sorted(rows, key=lambda row: (row['swap_bytes'], row['rss_bytes']), reverse=True)[:50]


def hard_failure(sample: dict, floor: int, pressure_seconds: float) -> str | None:
    if sample['mem_available_gib'] < floor:
        return 'physical_reserve_breached'
    if pressure_seconds >= POLICY['severe_pressure_duration_s']:
        return 'sustained_severe_memory_pressure'
    candidate = sample.get('candidate')
    if candidate:
        if not candidate['running'] or candidate['restart_count'] or candidate['oom_killed']:
            return 'candidate_exit_restart_or_oom'
        if candidate['state_error']:
            return 'candidate_state_error'
        cg = sample['cgroup']
        if cg['memory_max_bytes'] != SPEC.docker_memory_limit_bytes or cg['memory_swap_max_bytes'] != 0:
            return 'candidate_memory_controls_changed'
        if cg['memory_swap_current_bytes']:
            return 'candidate_swap'
        if cg['memory_events_oom'] or cg['memory_events_oom_kill']:
            return 'candidate_oom'
    return None


class Monitor:
    def __init__(self, output: Path, state: dict, floor: int):
        self.output, self.state, self.floor = output, state, floor
        self.ops = q.HostOps()
        self.pressure_since = None
        self.last_attribution = 0.0
        self.last_log_check = 0.0
        self.last_ready_check = 0.0
        self.readiness_failures = 0
        self.history = deque(maxlen=40)

    def sample(self):
        start = time.monotonic()
        write(self.output / 'heartbeat.json', {'at': q.utc_now(), 'monotonic': start,
                                               'phase': self.state['phase'], 'pid': os.getpid()})
        row = {'at': q.utc_now(), 'monotonic': start, 'phase': self.state['phase'],
               'profile': self.state.get('profile'), 'mem_available_gib': q._available_gib(),
               'pswpin_pages': q._pswpin_pages(), 'pswpout_pages': q._pswpout_pages(),
               'meminfo': q._host_meminfo_diagnostics(), 'memory_psi': psi('memory'), 'io_psi': psi('io')}
        if row['memory_psi']['full']['avg10'] >= POLICY['memory_psi_full_avg10_percent']:
            if self.pressure_since is None:
                self.pressure_since = start
        else:
            self.pressure_since = None
        identity = self.state.get('candidate_id')
        if identity and self.state['phase'] in {'starting', 'ready'}:
            candidate = q._inspect_container(self.ops, identity)
            if candidate is None or candidate['image'] != SPEC.image_id or candidate['name'] != SPEC.container_name:
                raise RuntimeError('candidate_identity_changed')
            row['candidate'] = candidate
            if candidate['running']:
                row['cgroup'] = q._candidate_cgroup_snapshot(identity, candidate['pid'])
            # Save the last sample even when it records a hard failure.
        if start-self.last_attribution >= 10:
            append(self.output / 'process-memory.jsonl', {'at': row['at'], 'processes': process_memory()})
            self.last_attribution = start
        row['sample_duration_s'] = time.monotonic()-start
        append(self.output / 'memory.jsonl', row)
        self.history.append(row)
        failure = hard_failure(row, self.floor, start-self.pressure_since if self.pressure_since else 0)
        if failure:
            raise RuntimeError(failure)
        if identity and self.state['phase'] in {'starting', 'ready'} and start-self.last_log_check >= 10:
            logs = self.ops.run(['docker', 'logs', '--tail', '100', identity], timeout=5, check=False)
            text = logs.stdout + logs.stderr
            (self.output / 'candidate-latest.log').write_text(text)
            self.last_log_check = start
            if FAULT.search(text):
                raise RuntimeError('candidate_driver_or_allocation_failure')
        if self.state['phase'] == 'ready' and start-self.last_ready_check >= 15:
            try:
                check_ready(self.ops)
                self.readiness_failures = 0
            except (OSError, ValueError, RuntimeError, q.QualificationError):
                self.readiness_failures += 1
                if self.readiness_failures >= 3:
                    raise RuntimeError('sustained_candidate_unresponsive')
            self.last_ready_check = start
        return row


def check_ready(ops):
    ops.http_bytes(f'http://127.0.0.1:{SPEC.host_port}/health', timeout=2)
    data = json.loads(ops.http_bytes(f'http://127.0.0.1:{SPEC.host_port}/v1/models', timeout=2))
    if [r['id'] for r in data['data']] != [SPEC.served_name]:
        raise RuntimeError('candidate_endpoint_identity_mismatch')
    return data


def candidate_idle() -> bool:
    from orchestrator.weekly_upgrade_trial import _queue_counts
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), q.NoRedirect())
    with opener.open(f'http://127.0.0.1:{SPEC.host_port}/metrics', timeout=3) as response:
        counts = _queue_counts(response.read(2_000_000).decode())
    return not any(counts.values())


def start_profile(output: Path, state: dict, profile: str, monitor: Monitor):
    ops = monitor.ops
    prior = state.get('candidate_id')
    if prior:
        state['phase'] = 'switching'
        write(output / 'state.json', state)
        row = q._inspect_container(ops, prior)
        if row is None or row['image'] != SPEC.image_id or row['name'] != SPEC.container_name:
            raise RuntimeError('candidate_switch_identity_changed')
        logs = ops.run(['docker', 'logs', '--timestamps', prior], timeout=10, check=False)
        (output / f'candidate-{state["profile"]}-{state["generation"]}.log').write_text(logs.stdout+logs.stderr)
        ops.run(['docker', 'stop', '--time', '20', prior], timeout=30)
        if q._inspect_container(ops, prior)['running']:
            raise RuntimeError('candidate_switch_stop_unverified')
        # A separate stopped sentinel keeps the watchdog paused across recreation.
        sentinel = ops.run(['docker', 'create', '--name', TRANSITION_NAME,
                            '--label', OWNER_LABEL+'='+state['ownership_token'],
                            '--entrypoint', '/bin/true', SPEC.image_id], timeout=20).stdout.strip()
        state['transition_sentinel'] = sentinel
        write(output / 'state.json', state)
        ops.run(['docker', 'rm', prior], timeout=20)
        state['candidate_id'] = None
        write(output / 'state.json', state)
    argv = argv_for(profile)
    argv[2:2] = ['--label', OWNER_LABEL+'='+state['ownership_token']]
    state.update(phase='creating', profile=profile, generation=state.get('generation', 0)+1)
    write(output / 'state.json', state)
    created = ops.run(argv, timeout=30).stdout.strip()
    row = q._inspect_container(ops, SPEC.container_name)
    if row is None or row['id'] != created or row['image'] != SPEC.image_id:
        raise RuntimeError('candidate_create_identity_mismatch')
    state['candidate_id'] = created
    write(output / 'state.json', state)
    if row['memory_limit_bytes'] != SPEC.docker_memory_limit_bytes or row['memory_swap_total_bytes'] != SPEC.docker_memory_limit_bytes:
        raise RuntimeError('candidate_create_memory_controls_mismatch')
    if state.pop('transition_sentinel', None):
        ops.run(['docker', 'rm', sentinel], timeout=20)
    # The first stopped candidate itself suppresses the incumbent watchdog.
    if not prior:
        if state['initial']['nara_was_active']:
            ops.run(['systemctl', '--user', 'stop', q.NARA_SERVICE], timeout=30)
        if q._service_state(ops)['ActiveState'] != 'inactive':
            raise RuntimeError('background_caller_not_paused')
        for resident in state['initial']['residents']:
            ops.run(['docker', 'stop', '--time', '30', resident['id']], timeout=45)
            if q._inspect_container(ops, resident['id'])['running']:
                raise RuntimeError('resident_stop_unverified')
    write(output / f'launch-{state["generation"]}.json', {
        'profile': profile, 'argv': argv, 'at': q.utc_now(), 'candidate_id': created,
        'model_artifact_sha256': SPEC.model_artifact_sha256(), 'image_id': SPEC.image_id,
        'historical_qualification_reused_as_prior_evidence_only': True,
    })
    ops.run(['docker', 'start', created], timeout=30)
    state.update(phase='starting', startup_at=q.utc_now(), startup_monotonic=time.monotonic())
    write(output / 'state.json', state)
    end = time.monotonic()+POLICY['startup_deadline_s']
    last = None
    while time.monotonic() < end:
        monitor.sample()
        try:
            models = check_ready(ops)
            state.update(phase='ready', ready_at=q.utc_now(), readiness=models,
                         cold_start_s=time.monotonic()-state['startup_monotonic'])
            write(output / 'state.json', state)
            append(output / 'events.jsonl', {'event': 'ready', **state})
            return
        except (OSError, ValueError, RuntimeError, q.QualificationError) as exc:
            last = str(exc)
        time.sleep(2)
    raise RuntimeError('startup_deadline: '+str(last))


def reconcile_owned(ops, state: dict):
    """Recover the tiny create-before-receipt window using a prewritten nonce."""
    for name, key in ((SPEC.container_name, 'candidate_id'), (TRANSITION_NAME, 'transition_sentinel')):
        row = q._inspect_container(ops, name)
        if row is None:
            continue
        owner = ops.run(['docker', 'inspect', '--format',
                         '{{index .Config.Labels "'+OWNER_LABEL+'"}}', row['id']], timeout=5).stdout.strip()
        if (owner != state.get('ownership_token') or row['image'] != SPEC.image_id
                or row['name'] != name or not re.fullmatch('[0-9a-f]{64}', row['id'])):
            raise RuntimeError('restoration_container_not_owned: '+name)
        # A switch may have removed the previous owned container before its
        # new create was recorded. Only adopt after proving it absent.
        if (state.get(key) not in (None, row['id'])
                and q._inspect_container(ops, state[key]) is not None):
            raise RuntimeError('multiple_owned_containers_during_restoration')
        state[key] = row['id']


def restore(output: Path, state: dict):
    reconcile_owned(q.HostOps(), state)
    state['phase'] = 'restoring'
    write(output / 'state.json', state)
    result = q.restore_exact(q.HostOps(), state, deadline=time.monotonic()+900,
                             spec=SPEC, diagnostic_path=output / 'candidate-final.log')
    extra = state.get('transition_sentinel')
    if extra and result['status'] == 'verified':
        row = q._inspect_container(q.HostOps(), extra)
        if row and row['name'] == TRANSITION_NAME and not row['running']:
            q.HostOps().run(['docker', 'rm', extra], timeout=20)
    state['restoration'] = result
    state['phase'] = 'restored' if result['status'] == 'verified' else 'restoration_failed'
    write(output / 'state.json', state)
    return result


def worker(output: Path, hours: float, floor: int):
    state = json.loads((output / 'state.json').read_text())
    if os.getppid() != state['parent_pid']:
        raise RuntimeError('worker requires its supervising parent and inherited resource lease')
    monitor = Monitor(output, state, floor)
    stop = False

    def halt(_signum, _frame):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, halt)
    signal.signal(signal.SIGINT, halt)
    end = time.monotonic()+hours*3600
    error = None
    try:
        start_profile(output, state, 'mtp3-fp32-auto', monitor)
        last_command = None
        while not stop and time.monotonic() < end:
            monitor.sample()
            command_path = output / 'command.json'
            if command_path.exists():
                command = json.loads(command_path.read_text())
                if command.get('id') != last_command:
                    last_command = command['id']
                    append(output / 'commands.jsonl', {**command, 'at': q.utc_now()})
                    if command.get('action') == 'restore':
                        break
                    if (command.get('action') == 'profile' and command.get('profile') in PROFILES
                            and command['profile'] != state['profile']):
                        if candidate_idle():
                            start_profile(output, state, command['profile'], monitor)
                        else:
                            append(output / 'events.jsonl', {'event': 'profile_change_refused_busy',
                                                           'command': command, 'at': q.utc_now()})
            time.sleep(2)
    except BaseException as exc:  # noqa: BLE001 - every failed runtime path must restore
        error = f'{type(exc).__name__}: {exc}'
        state['error'] = error
        write(output / 'state.json', state)
    finally:
        restored = restore(output, state)
        write(output / 'result.json', {'at': q.utc_now(), 'error': error, 'restoration': restored})
    return 0 if error is None and restored['status'] == 'verified' else 1


def preflight(root: Path, floor: int):
    """Keep caller/identity checks, using this session's explicit reserve."""
    from orchestrator.weekly_upgrade_trial import _queue_counts
    for name in ('pause_coordinator', 'pause_frontier', 'pause_weekly_upgrade'):
        if (root / 'run_state' / name).exists():
            raise RuntimeError('pause control present: '+name)
    if ((root / 'run_state/active_run.json').exists()
            or any((root / 'run_state/active_runs').glob('*.json'))):
        raise RuntimeError('active research receipt needs live-process reconciliation')
    if q._available_gib() < floor:
        raise RuntimeError('physical_reserve_unavailable')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), q.NoRedirect())
    identities = []
    for registered in q.RESIDENTS:
        port = 8000 if registered['name'] == 'vllm-gemma4' else 8001
        with opener.open(f'http://127.0.0.1:{port}/metrics', timeout=3) as response:
            if any(_queue_counts(response.read(2_000_000).decode()).values()):
                raise RuntimeError('resident_requests_are_active')
        row = q._inspect_container(q.HostOps(), registered['name'])
        if row is None:
            raise RuntimeError('resident_identity_missing')
        identities.append(row)
    return {'runtime_identity': identities}


def run(output: Path, hours: float, floor: int):
    output = output.absolute()
    if output.parent != ARTIFACTS or output.exists() or not re.fullmatch(r'session-[a-z0-9-]+', output.name):
        raise ValueError('use a fresh session-* directory in the personal recovery artifact root')
    output.mkdir(mode=0o700, parents=True)
    write(output / 'policy.json', {**POLICY, 'minimum_mem_available_gib': floor,
                                   'session_hours': hours, 'profiles': PROFILES,
                                   'controller_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    ops = q.HostOps()
    with resource_lease(canonical_root(ROOT)) as locks:
        preflight(canonical_root(ROOT), floor)
        if q._inspect_container(ops, SPEC.container_name) is not None:
            raise RuntimeError('existing Flash container needs reconciliation')
        q._assert_port_free(SPEC)
        contract = json.loads(SPEC.contract_path.read_text())
        write(output / 'verification-start.json', {'at': q.utc_now()})
        write(output / 'model-verification.json', q.verify_model(contract, spec=SPEC))
        image = ops.run(['docker', 'image', 'inspect', '--format', '{{.Id}} {{.Architecture}}', SPEC.image_id], timeout=10)
        if image.stdout.strip().split() != [SPEC.image_id, 'arm64']:
            raise RuntimeError('image_identity_mismatch')
        before = preflight(canonical_root(ROOT), floor)
        initial = q._capture_initial_state(ops, before)
        state = {'phase': 'prepared', 'initial': initial, 'candidate_id': None,
                 'at': q.utc_now(), 'output': str(output), 'parent_pid': os.getpid(),
                 'ownership_token': uuid.uuid4().hex}
        write(output / 'state.json', state)
        q._ensure_compile_cache(SPEC)
        command = [sys.executable, '-m', 'bench.flash_next_ab.personal_session', '--worker',
                   '--output-dir', str(output), '--hours', str(hours), '--floor', str(floor)]
        with (output / 'worker.log').open('w') as log:
            child = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                     start_new_session=True, pass_fds=locks, env={k:v for k,v in os.environ.items() if k!='MOCK_LLM'})
            write(output / 'supervisor.json', {'pid': os.getpid(), 'worker_pid': child.pid,
                                              'worker_start_ticks': q._process_start_ticks(child.pid), 'at': q.utc_now()})
            start = time.monotonic()
            try:
                while child.poll() is None:
                    current = json.loads((output / 'state.json').read_text())
                    if current['phase'] == 'restoring':
                        # The restoration path has its own 900-second operation deadlines.
                        heartbeat_limit = 960
                    elif current['phase'] in {'prepared', 'creating', 'switching'}:
                        heartbeat_limit = 180
                    else:
                        heartbeat_limit = POLICY['worker_heartbeat_max_age_s']
                    heartbeat = output / 'heartbeat.json'
                    age = time.time()-heartbeat.stat().st_mtime if heartbeat.exists() else time.monotonic()-start
                    if age > heartbeat_limit or time.monotonic()-start > hours*3600+960:
                        append(output / 'events.jsonl', {'event': 'supervisor_timeout', 'phase': current['phase'], 'heartbeat_age_s': age, 'at': q.utc_now()})
                        os.killpg(child.pid, signal.SIGKILL)
                        child.wait(timeout=20)
                        break
                    time.sleep(2)
            except BaseException:
                if child.poll() is None:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait(timeout=20)
                raise
            finally:
                current = json.loads((output / 'state.json').read_text())
                if current['phase'] != 'restored':
                    result = restore(output, current)
                    write(output / 'emergency-restoration.json', result)
        return child.returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--run', action='store_true')
    mode.add_argument('--worker', action='store_true')
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--hours', type=float, default=8)
    parser.add_argument('--floor', type=int, choices=[12,20], default=20)
    args = parser.parse_args()
    if not 0.25 <= args.hours <= 24:
        parser.error('session must be between 15 minutes and 24 hours')
    return (worker if args.worker else run)(args.output_dir, args.hours, args.floor)


if __name__ == '__main__':
    raise SystemExit(main())
