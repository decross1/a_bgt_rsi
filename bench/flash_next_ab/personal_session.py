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
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from orchestrator.weekly_upgrade_trial import canonical_root, resource_lease

from . import qualification as q
from .candidate_registry import CandidateSpec
from .followon_profiles import (
    MIA_MTP3_REDUCED47K_FP8_QSA,
    MIA_MTP3_REDUCED47K_OPT,
    SPECS_BY_ID,
    is_registered_spec,
)

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = Path('/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-18/flash-personal-recovery')
SPEC = MIA_MTP3_REDUCED47K_OPT


@dataclass(frozen=True, slots=True)
class ServingProfile:
    spec: CandidateSpec
    mtp: int
    recurrent_state: str
    kv_cache_dtype: str

    def receipt(self) -> dict:
        return {
            'candidate_spec_id': self.spec.spec_id,
            'candidate_spec_sha256': self.spec.identity_sha256(),
            'image_id': self.spec.image_id,
            'image_build_receipt': self.spec.identity_snapshot()['proof_receipts']['image_build'],
            'model_path': str(self.spec.model_path),
            'model_artifact_sha256': self.spec.model_artifact_sha256(),
            'container_name': self.spec.container_name,
            'compile_cache': str(self.spec.compile_cache),
            'contract_path': str(self.spec.contract_path),
            'mtp': self.mtp,
            'recurrent_state': self.recurrent_state,
            'kv_cache_dtype': self.kv_cache_dtype,
        }


PROFILES = {
    'mtp3-fp32-auto': ServingProfile(SPEC, 3, 'float32', 'auto'),
    'mtp0-fp32-auto': ServingProfile(SPEC, 0, 'float32', 'auto'),
    'mtp3-bf16-auto': ServingProfile(SPEC, 3, 'bfloat16', 'auto'),
    'mtp3-bf16-child-auto': ServingProfile(
        MIA_MTP3_REDUCED47K_FP8_QSA, 3, 'bfloat16', 'auto',
    ),
    'mtp3-bf16-child-fp8': ServingProfile(
        MIA_MTP3_REDUCED47K_FP8_QSA, 3, 'bfloat16', 'fp8',
    ),
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
    'kernel_fault_poll_s': 15,
    'restoration_reserve_s': 900,
    'weekly_budget_debit': False,
}
FAULT = re.compile(r'CUDA out of memory|CUDA error:|illegal memory access|Segmentation fault|OutOfMemoryError')
KERNEL_FAULT = re.compile(r'NV_ERR_NO_MEMORY|NVRM: Xid')


def write(path: Path, value):
    q._atomic_write(path, value)


def append(path: Path, value):
    with path.open('a') as f:
        f.write(json.dumps(value, sort_keys=True) + '\n')


def _profile(profile: str) -> ServingProfile:
    try:
        return PROFILES[profile]
    except KeyError as exc:
        raise ValueError('unknown personal serving profile') from exc


def _state_spec(state: dict) -> CandidateSpec:
    spec_id = state.get('session_spec_id')
    spec = SPECS_BY_ID.get(spec_id)
    if (
        spec is None
        or not is_registered_spec(spec)
        or state.get('session_spec_sha256') != spec.identity_sha256()
    ):
        raise RuntimeError('session_candidate_spec_identity_missing_or_changed')
    return spec


def profiles_for_spec(spec: CandidateSpec) -> tuple[str, ...]:
    if not is_registered_spec(spec):
        raise ValueError('personal session spec is not registered')
    return tuple(name for name, profile in PROFILES.items() if profile.spec is spec)


def argv_for(profile: str) -> list[str]:
    """Derive explicit new arms without changing the historical CandidateSpec."""
    selected = _profile(profile)
    argv = q.launch_argv(selected.spec)
    argv[argv.index('--mamba-ssm-cache-dtype') + 1] = selected.recurrent_state
    argv[argv.index('--kv-cache-dtype') + 1] = selected.kv_cache_dtype
    if not selected.mtp:
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


def hard_failure(
    sample: dict,
    floor: int,
    pressure_seconds: float,
    spec: CandidateSpec = SPEC,
) -> str | None:
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
        if cg['memory_max_bytes'] != spec.docker_memory_limit_bytes or cg['memory_swap_max_bytes'] != 0:
            return 'candidate_memory_controls_changed'
        if cg['memory_swap_current_bytes']:
            return 'candidate_swap'
        if cg['memory_events_oom'] or cg['memory_events_oom_kill']:
            return 'candidate_oom'
    return None


class Monitor:
    def __init__(self, output: Path, state: dict, floor: int, spec: CandidateSpec):
        if not is_registered_spec(spec):
            raise ValueError('monitor candidate spec is not registered')
        self.output, self.state, self.floor, self.spec = output, state, floor, spec
        self.ops = q.HostOps()
        self.pressure_since = None
        self.last_attribution = 0.0
        self.last_log_check = 0.0
        self.last_kernel_check = 0.0
        self.session_started = datetime.fromisoformat(state['at']).astimezone(timezone.utc)
        self.last_ready_check = 0.0
        self.readiness_failures = 0
        self.history = deque(maxlen=40)

    def check_kernel_faults(self):
        """Catch driver faults even when the container logs remain healthy."""
        result = self.ops.run([
            'journalctl', '-k', '--since',
            self.session_started.strftime('%Y-%m-%d %H:%M:%S UTC'),
            '--no-pager', '--quiet', '-o', 'json', '--grep=' + KERNEL_FAULT.pattern,
        ], timeout=10, check=False)
        append(self.output / 'kernel-checks.jsonl', {
            'at': q.utc_now(), 'session_started': self.state['at'],
            'returncode': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr,
        })
        if result.returncode not in (0, 1) or result.stderr.strip():
            raise RuntimeError('kernel_fault_evidence_unavailable')
        try:
            rows = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
            for row in rows:
                # journalctl's second-resolution filter may include older events.
                at_us = int(row['__REALTIME_TIMESTAMP'])
                message = row['MESSAGE']
                if not isinstance(message, str):
                    raise TypeError('kernel message must be text')
                if (at_us >= int(self.session_started.timestamp() * 1_000_000)
                        and KERNEL_FAULT.search(message)):
                    raise RuntimeError('kernel_driver_or_allocation_failure')
        except (ValueError, KeyError, TypeError) as exc:
            raise RuntimeError('kernel_fault_evidence_malformed') from exc

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
            if (candidate is None or candidate['image'] != self.spec.image_id
                    or candidate['name'] != self.spec.container_name):
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
        failure = hard_failure(
            row, self.floor, start-self.pressure_since if self.pressure_since else 0,
            self.spec,
        )
        if (identity and self.state['phase'] in {'starting', 'ready'}
                and (failure or start-self.last_kernel_check >= POLICY['kernel_fault_poll_s'])):
            # Preserve a kernel fault even when it also made the container exit.
            self.check_kernel_faults()
            self.last_kernel_check = start
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
                check_ready(self.ops, self.spec)
                self.readiness_failures = 0
            except (OSError, ValueError, RuntimeError, q.QualificationError):
                self.readiness_failures += 1
                if self.readiness_failures >= 3:
                    raise RuntimeError('sustained_candidate_unresponsive')
            self.last_ready_check = start
        return row


def check_ready(ops, spec: CandidateSpec = SPEC):
    if not is_registered_spec(spec):
        raise ValueError('readiness candidate spec is not registered')
    ops.http_bytes(f'http://127.0.0.1:{spec.host_port}/health', timeout=2)
    data = json.loads(ops.http_bytes(f'http://127.0.0.1:{spec.host_port}/v1/models', timeout=2))
    if [r['id'] for r in data['data']] != [spec.served_name]:
        raise RuntimeError('candidate_endpoint_identity_mismatch')
    return data


def candidate_idle(spec: CandidateSpec = SPEC) -> bool:
    from orchestrator.weekly_upgrade_trial import _queue_counts
    if not is_registered_spec(spec):
        raise ValueError('idle-check candidate spec is not registered')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), q.NoRedirect())
    with opener.open(f'http://127.0.0.1:{spec.host_port}/metrics', timeout=3) as response:
        counts = _queue_counts(response.read(2_000_000).decode())
    return not any(counts.values())


def start_profile(
    output: Path,
    state: dict,
    profile: str,
    monitor: Monitor,
    spec: CandidateSpec,
):
    selected = _profile(profile)
    if selected.spec is not spec or monitor.spec is not spec:
        raise RuntimeError('profile_candidate_spec_differs_from_session')
    ops = monitor.ops
    prior = state.get('candidate_id')
    if prior:
        state['phase'] = 'switching'
        write(output / 'state.json', state)
        row = q._inspect_container(ops, prior)
        if row is None or row['image'] != spec.image_id or row['name'] != spec.container_name:
            raise RuntimeError('candidate_switch_identity_changed')
        logs = ops.run(['docker', 'logs', '--timestamps', prior], timeout=10, check=False)
        (output / f'candidate-{state["profile"]}-{state["generation"]}.log').write_text(logs.stdout+logs.stderr)
        ops.run(['docker', 'stop', '--time', '20', prior], timeout=30)
        if q._inspect_container(ops, prior)['running']:
            raise RuntimeError('candidate_switch_stop_unverified')
        # A separate stopped sentinel keeps the watchdog paused across recreation.
        sentinel = ops.run(['docker', 'create', '--name', TRANSITION_NAME,
                            '--label', OWNER_LABEL+'='+state['ownership_token'],
                            '--entrypoint', '/bin/true', spec.image_id], timeout=20).stdout.strip()
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
    row = q._inspect_container(ops, spec.container_name)
    if row is None or row['id'] != created or row['image'] != spec.image_id:
        raise RuntimeError('candidate_create_identity_mismatch')
    state['candidate_id'] = created
    write(output / 'state.json', state)
    if (row['memory_limit_bytes'] != spec.docker_memory_limit_bytes
            or row['memory_swap_total_bytes'] != spec.docker_memory_limit_bytes):
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
        'candidate_spec_id': spec.spec_id,
        'candidate_spec_sha256': spec.identity_sha256(),
        'model_artifact_sha256': spec.model_artifact_sha256(), 'model_path': str(spec.model_path),
        'image_id': spec.image_id,
        'image_build_receipt': spec.identity_snapshot()['proof_receipts']['image_build'],
        'compile_cache': str(spec.compile_cache),
        'contract_path': str(spec.contract_path),
        'contract_sha256': state['contract_sha256'],
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
            models = check_ready(ops, spec)
            state.update(phase='ready', ready_at=q.utc_now(), readiness=models,
                         cold_start_s=time.monotonic()-state['startup_monotonic'])
            write(output / 'state.json', state)
            append(output / 'events.jsonl', {'event': 'ready', **state})
            return
        except (OSError, ValueError, RuntimeError, q.QualificationError) as exc:
            last = str(exc)
        time.sleep(2)
    raise RuntimeError('startup_deadline: '+str(last))


def reconcile_owned(ops, state: dict, spec: CandidateSpec | None = None):
    """Recover the tiny create-before-receipt window using a prewritten nonce."""
    selected = spec if spec is not None else _state_spec(state)
    if not is_registered_spec(selected):
        raise ValueError('restoration candidate spec is not registered')
    for name, key in (
        (selected.container_name, 'candidate_id'),
        (TRANSITION_NAME, 'transition_sentinel'),
    ):
        row = q._inspect_container(ops, name)
        if row is None:
            continue
        owner = ops.run(['docker', 'inspect', '--format',
                         '{{index .Config.Labels "'+OWNER_LABEL+'"}}', row['id']], timeout=5).stdout.strip()
        if (owner != state.get('ownership_token') or row['image'] != selected.image_id
                or row['name'] != name or not re.fullmatch('[0-9a-f]{64}', row['id'])):
            raise RuntimeError('restoration_container_not_owned: '+name)
        # A switch may have removed the previous owned container before its
        # new create was recorded. Only adopt after proving it absent.
        if (state.get(key) not in (None, row['id'])
                and q._inspect_container(ops, state[key]) is not None):
            raise RuntimeError('multiple_owned_containers_during_restoration')
        state[key] = row['id']


def restore(output: Path, state: dict):
    spec = _state_spec(state)
    reconcile_owned(q.HostOps(), state, spec)
    state['phase'] = 'restoring'
    write(output / 'state.json', state)
    result = q.restore_exact(q.HostOps(), state, deadline=time.monotonic()+900,
                             spec=spec, diagnostic_path=output / 'candidate-final.log')
    extra = state.get('transition_sentinel')
    if extra and result['status'] == 'verified':
        row = q._inspect_container(q.HostOps(), extra)
        if row and row['name'] == TRANSITION_NAME and not row['running']:
            q.HostOps().run(['docker', 'rm', extra], timeout=20)
    state['restoration'] = result
    state['phase'] = 'restored' if result['status'] == 'verified' else 'restoration_failed'
    write(output / 'state.json', state)
    return result


def worker(output: Path, hours: float, floor: int, initial_profile: str):
    state = json.loads((output / 'state.json').read_text())
    if os.getppid() != state['parent_pid']:
        raise RuntimeError('worker requires its supervising parent and inherited resource lease')
    spec = _state_spec(state)
    if state.get('initial_profile') != initial_profile or _profile(initial_profile).spec is not spec:
        raise RuntimeError('worker_initial_profile_differs_from_prepared_session')
    monitor = Monitor(output, state, floor, spec)
    stop = False

    def halt(_signum, _frame):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, halt)
    signal.signal(signal.SIGINT, halt)
    end = time.monotonic()+hours*3600
    error = None
    try:
        start_profile(output, state, initial_profile, monitor, spec)
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
                        requested = _profile(command['profile'])
                        if requested.spec is not spec:
                            append(output / 'events.jsonl', {
                                'event': 'profile_change_refused_spec_mismatch',
                                'command': command,
                                'session_spec_id': spec.spec_id,
                                'at': q.utc_now(),
                            })
                        elif candidate_idle(spec):
                            start_profile(output, state, command['profile'], monitor, spec)
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


def run(output: Path, hours: float, floor: int, initial_profile: str):
    selected_profile = _profile(initial_profile)
    spec = selected_profile.spec
    output = output.absolute()
    if output.parent != ARTIFACTS or output.exists() or not re.fullmatch(r'session-[a-z0-9-]+', output.name):
        raise ValueError('use a fresh session-* directory in the personal recovery artifact root')
    output.mkdir(mode=0o700, parents=True)
    write(output / 'policy.json', {**POLICY, 'minimum_mem_available_gib': floor,
                                   'session_hours': hours,
                                   'initial_profile': initial_profile,
                                   'session_candidate_spec_id': spec.spec_id,
                                   'session_candidate_spec_sha256': spec.identity_sha256(),
                                   'allowed_profiles': profiles_for_spec(spec),
                                   'profiles': {
                                       name: profile.receipt()
                                       for name, profile in PROFILES.items()
                                   },
                                   'controller_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    ops = q.HostOps()
    with resource_lease(canonical_root(ROOT)) as locks:
        preflight(canonical_root(ROOT), floor)
        for candidate in {profile.spec for profile in PROFILES.values()}:
            if q._inspect_container(ops, candidate.container_name) is not None:
                raise RuntimeError('existing Flash container needs reconciliation')
        if q._inspect_container(ops, TRANSITION_NAME) is not None:
            raise RuntimeError('existing Flash transition sentinel needs reconciliation')
        q._assert_port_free(spec)
        from .mia_candidate_integration import read_mia_contract
        contract, contract_sha256, _contract_raw = read_mia_contract(spec.contract_path, q)
        write(output / 'verification-start.json', {'at': q.utc_now()})
        write(output / 'model-verification.json', q.verify_model(contract, spec=spec))
        image = ops.run(['docker', 'image', 'inspect', '--format', '{{.Id}} {{.Architecture}}', spec.image_id], timeout=10)
        if image.stdout.strip().split() != [spec.image_id, 'arm64']:
            raise RuntimeError('image_identity_mismatch')
        before = preflight(canonical_root(ROOT), floor)
        initial = q._capture_initial_state(ops, before)
        state = {'phase': 'prepared', 'initial': initial, 'candidate_id': None,
                 'at': q.utc_now(), 'output': str(output), 'parent_pid': os.getpid(),
                 'ownership_token': uuid.uuid4().hex,
                 'initial_profile': initial_profile,
                 'session_spec_id': spec.spec_id,
                 'session_spec_sha256': spec.identity_sha256(),
                 'contract_sha256': contract_sha256}
        write(output / 'state.json', state)
        q._ensure_compile_cache(spec)
        command = [sys.executable, '-m', 'bench.flash_next_ab.personal_session', '--worker',
                   '--output-dir', str(output), '--hours', str(hours), '--floor', str(floor),
                   '--initial-profile', initial_profile]
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
    parser.add_argument('--initial-profile', choices=tuple(PROFILES),
                        default='mtp3-fp32-auto')
    args = parser.parse_args()
    if not 0.25 <= args.hours <= 24:
        parser.error('session must be between 15 minutes and 24 hours')
    return (worker if args.worker else run)(
        args.output_dir, args.hours, args.floor, args.initial_profile,
    )


if __name__ == '__main__':
    raise SystemExit(main())
