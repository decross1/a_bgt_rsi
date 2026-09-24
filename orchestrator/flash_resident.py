"""Persistent Flash service, using the already reviewed local serving bundle.

No evaluation calls or scheduled experiment window. The pinned local adapter
owns Docker startup/stop; this supervisor keeps the memory/kernel guard alive.
A fault inhibits another start in this boot. A new boot permits one fresh start.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
PREP = Path('/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-18/flash-personal-recovery/sglang-fallback-prep')
BUNDLE = PREP / 'sglang_session_s3_v10.py'
BUNDLE_SHA = 'e26d2aa2330a6c2e37c4629aa7074b6b7804f07f9239239bcf90f73244b90aa5'
# Running requests served by the helper's pinned profile (nextn-262k-c4-m24-s3.json).
# The deployment document must declare the same count.
BUNDLE_MAX_RUNNING_REQUESTS = 4
RECEIPT = PREP / 'checkpoint-verification-bf16-20260918T2343Z/checkpoint-receipt.json'
RECEIPT_SHA = '0489e1741832e6be63267cb1a04a1eb05736d27038fe924ac50cf02bce108287'
MODEL = 'nvidia/Qwen3.8-Flash-Next-NVFP4'
STATE = ROOT / 'run_state/flash_resident.json'
BOOT = Path('/proc/sys/kernel/random/boot_id')
# Owner lowered the steady-state host reserve from 20 to 10 GiB on 2026-09-21
# so interactive SSH sessions do not stop Flash. Must equal the pinned helper's HOST_FLOOR_GIB.
HOST_RESERVE_GIB = 10
# The main-weight load reserves ~84 GiB at once. On 2026-09-19 it logged driver
# big-page NV_ERR_NO_MEMORY lines whenever MemFree was below ~100 GiB at that
# moment (page cache 38-73 GiB); passing loads began with 102-114 GiB free.
PRELAUNCH_MIN_FREE_GIB = 100.0
# Bounded wait (logged in state) that spans one :00/:30 host cache drop, since
# the unit has Restart=no and a refusal leaves Flash and Nara offline.
PRELAUNCH_WAIT_S = 35 * 60
STATE_LOCK = threading.Lock()


def selected(root: Path = ROOT) -> bool:
    path = root / 'config/model_deployment.json'
    if path.is_symlink():
        raise ValueError('model deployment cannot be a symlink')
    if not path.exists():
        return False
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError('model deployment must be an object')
    if value.get('topology') != 'single_flash' or value.get('production_authorized') is not True:
        return False
    from agent_wrapper.deployment import load_model_deployment
    deployment = load_model_deployment(path)
    # The helper's exact artifacts and the client manifest must describe the
    # same deployed bundle, not merely a syntactically valid digest.
    if (deployment.image_id != 'sha256:2ee545cf877ae8497c123637e061b6e6313c624e30018f975969b1d554e27f56'
            or deployment.model_revision != 'fc694b54fb0174e0913e6adf86691ef85a4ead47'
            or deployment.profile_sha256 != '45546ef777af74a264d31e5b5cfd5b2f68f0bddf2954d4f243bd7ea9b3dae903'
            or deployment.max_running_requests != BUNDLE_MAX_RUNNING_REQUESTS):
        raise ValueError('deployment differs from the reviewed serving bundle')
    return True


def mem_available_gib() -> float:
    for line in Path('/proc/meminfo').read_text().splitlines():
        if line.startswith('MemAvailable:'):
            return int(line.split()[1]) / 1024**2
    raise RuntimeError('MemAvailable unavailable')


def host_memory_kib() -> dict:
    fields = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        name, _, value = line.partition(':')
        if name in {'MemFree', 'MemAvailable', 'Cached'}:
            fields[name] = int(value.split()[0])
    return fields


def evict_model_page_cache(roots) -> int:
    """Drop clean page cache of Flash's large files without privileges.

    Keeps MemFree high for the main-weight allocation. It does not address the
    draft-stage driver lines seen on 2026-09-21 at 14:21.
    """
    evicted = 0
    for root in roots:
        for path in sorted(Path(root).rglob('*')):
            if path.is_symlink() or not path.is_file() or path.stat().st_size < 64 * 1024**2:
                continue
            fd = os.open(path, os.O_RDONLY)
            try:
                try:
                    os.fdatasync(fd)  # dirty pages cannot be dropped
                except OSError:
                    pass  # read-only media has no dirty pages; the Cached gate checks the outcome
                os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
            finally:
                os.close(fd)
            evicted += 1
    return evicted


class LoadEvictor:
    """Evict the read-once checkpoint's page cache every few seconds while loading.

    Loading fills ~20-25 GiB of page cache; the draft-model and 262K KV-pool
    allocations then reclaim it and the driver logs big-page retry lines that
    the helper's kernel guard treats as fatal. With this running, the
    2026-09-22 262K evaluation loaded with no such line. The PLE cache is not
    evicted; the thread stops at readiness.
    """

    def __init__(self, root: Path, interval: float = 3.0):
        self.root, self.interval = root, interval
        self.done = threading.Event()
        self.passes = 0
        self.errors: list = []
        self.thread = threading.Thread(target=self._loop, name='load-evictor', daemon=True)

    def _loop(self) -> None:
        while not self.done.wait(self.interval):
            try:
                evict_model_page_cache((self.root,))
                self.passes += 1
            except OSError as exc:
                self.errors.append(str(exc))

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> dict:
        self.done.set()
        if self.thread.is_alive():
            self.thread.join(timeout=30)
        return {'passes': self.passes, 'errors': self.errors[:5], 'interval_s': self.interval}


def check_ready(root: Path = ROOT) -> bool:
    """Read-only admission for actual research callers, never a generation."""
    try:
        state = json.loads((root / 'run_state/flash_resident.json').read_text())
        if (state.get('phase') != 'ready' or state.get('boot_id') != BOOT.read_text().strip()
                or not 0 <= time.time() - float(state['heartbeat_epoch']) <= 45
                or mem_available_gib() < HOST_RESERVE_GIB):
            return False
        pid = int(state['pid'])
        ticks = int(Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19])
        if ticks != state['process_start_ticks']:
            return False
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open('http://127.0.0.1:30080/v1/models', timeout=3) as response:
            data = response.read(65537)
            return (response.status == 200 and len(data) <= 65536
                    and [r['id'] for r in json.loads(data)['data']] == [MODEL])
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def load_bundle():
    if hashlib.sha256(BUNDLE.read_bytes()).hexdigest() != BUNDLE_SHA:
        raise RuntimeError('reviewed serving helper changed')
    spec = importlib.util.spec_from_file_location('flash_reviewed_serving_bundle', BUNDLE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_state(value: dict):
    with STATE_LOCK:
        value['heartbeat_epoch'] = time.time()
        value['updated_at'] = datetime.now(timezone.utc).isoformat()
        STATE.parent.mkdir(parents=True, exist_ok=True)
        temporary = STATE.with_suffix('.tmp')
        temporary.write_text(json.dumps(value, indent=2) + '\n')
        temporary.replace(STATE)


def wait_docker(stop: threading.Event):
    """User units cannot order themselves after system docker.service."""
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline and not stop.is_set():
        result = subprocess.run(['docker', 'info', '--format', '{{.ServerVersion}}'],
                                capture_output=True, timeout=10)
        if result.returncode == 0 and Path('/var/run/cdi/nvidia.yaml').exists():
            return
        stop.wait(5)
    raise RuntimeError('Docker/NVIDIA device readiness deadline expired')


def raise_if_stopped(stop):
    if stop.is_set():
        raise RuntimeError('operator requested stop before next service mutation')


def run() -> int:
    if not selected():
        raise RuntimeError('Flash permanent deployment is not selected')
    boot_id = BOOT.read_text().strip()
    STATE.parent.mkdir(parents=True, exist_ok=True)
    lock = (STATE.parent / '.flash-resident.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    previous = {}
    if STATE.exists():
        previous = json.loads(STATE.read_text())
        if (previous.get('phase') == 'fault' and previous.get('boot_id') == boot_id
                and previous.get('launch_attempted')):
            print('Flash fault is latched for this boot; owner reboot follow-up remains pending.', flush=True)
            return 78
        # Checked before this run's state overwrites the record, so a retry still refuses. A record
        # without bundle_sha256 predates v8's pin and also needs the handoff.
        if previous.get('artifact_dir') and previous.get('bundle_sha256') != BUNDLE_SHA:
            print('helper handoff required: previous run used a different pinned helper', flush=True)
            return 1
    stop = threading.Event()
    for number in (signal.SIGINT, signal.SIGTERM):
        signal.signal(number, lambda *_: stop.set())
    state = dict(schema_version=1, phase='preparing', boot_id=boot_id, pid=os.getpid(),
                 process_start_ticks=int(Path('/proc/self/stat').read_text().rsplit(')', 1)[1].split()[19]),
                 model=MODEL, backend='sglang-flash', endpoint='http://127.0.0.1:30080/v1',
                 production_authorized=True, selected_at='2026-09-19', error=None,
                 bundle_sha256=BUNDLE_SHA, host_reserve_gib=HOST_RESERVE_GIB)
    write_state(state)
    bundle = None
    monitor = guard = log = stopper = evictor = None
    lease = None
    lease_open = False
    output = PREP / 'runtime' / ('resident-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    output.mkdir(mode=0o700)
    state['artifact_dir'] = str(output)
    try:
        bundle = load_bundle()
        if bundle.canonical_root(ROOT) != ROOT:
            raise RuntimeError('Run the permanent resident service from the canonical checkout')
        bundle.verify_control_sources()
        wait_docker(stop)
        ops = bundle.q.HostOps()
        bundle.inspect_image(ops)
        bundle.verify_checkpoint_receipt(RECEIPT, RECEIPT_SHA)
        # Transition locks are released after readiness, so Nara can use the
        # resident. The child adapter never inherits these descriptors.
        lease = bundle.resource_lease(ROOT)
        lease.__enter__()
        lease_open = True
        raise_if_stopped(stop)
        if previous.get('artifact_dir'):
            if previous.get('boot_id') == boot_id:
                try:
                    ticks = int(Path(f'/proc/{int(previous["pid"])}/stat').read_text().rsplit(')', 1)[1].split()[19])
                    if ticks == previous.get('process_start_ticks'):
                        raise RuntimeError('previous resident supervisor is still alive')
                except (FileNotFoundError, ProcessLookupError):
                    pass
            old_output = Path(previous['artifact_dir'])
            if old_output.parent != PREP / 'runtime' or not old_output.name.startswith('resident-') or old_output.is_symlink():
                raise RuntimeError('previous resident artifact path is invalid')
            bundle.finalize_owned_fallback(old_output, ops, RECEIPT_SHA)
        bundle.assert_no_fallback_or_transition(ops)
        bundle.assert_port_free()
        raise_if_stopped(stop)
        ops.run(['systemctl', '--user', 'stop', bundle.q.NARA_SERVICE], timeout=45)
        state['nara_transition_owned'] = True
        expected = {r['name']: r for r in bundle.q.RESIDENTS}
        for name in ('vllm-gemma4', 'vllm-qwen'):
            row = bundle.q._inspect_container(ops, name)
            if row is not None:
                if row['id'] != expected[name]['id'] or row['image'] != expected[name]['image_id']:
                    raise RuntimeError('rollback container identity changed: ' + name)
                if row['running']:
                    port = 8000 if name == 'vllm-gemma4' else 8001
                    deadline = time.monotonic() + 120
                    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
                    while True:
                        with opener.open(f'http://127.0.0.1:{port}/metrics', timeout=3) as response:
                            raw = response.read(2_000_001)
                        if len(raw) > 2_000_000:
                            raise RuntimeError('resident metrics oversized')
                        if not any(bundle._queue_counts(raw.decode()).values()):
                            break
                        if stop.is_set() or time.monotonic() >= deadline:
                            raise RuntimeError('resident requests did not drain: ' + name)
                        stop.wait(2)
                # Keep exact existing containers as manual rollback artifacts.
                raise_if_stopped(stop)
                ops.run(['docker', 'update', '--restart=no', row['id']], timeout=20)
                if row['running']:
                    raise_if_stopped(stop)
                    ops.run(['docker', 'stop', '--time', '30', row['id']], timeout=45)
        if mem_available_gib() < bundle.PREFLIGHT_FLOOR_GIB:
            raise RuntimeError('104 GiB prelaunch memory admission unavailable')
        wait_until = time.monotonic() + PRELAUNCH_WAIT_S
        waited = 0
        while True:
            evicted = evict_model_page_cache((bundle.MODEL_ROOT, bundle.CACHE))
            memory = host_memory_kib()
            state['prelaunch'] = dict(evicted_files=evicted, meminfo_kib=memory, waits=waited,
                                      buddyinfo=Path('/proc/buddyinfo').read_text())
            if memory['MemFree'] / 1024**2 >= PRELAUNCH_MIN_FREE_GIB:
                break
            if time.monotonic() >= wait_until:
                # Refused before launch_attempted, so this does not arm the latch.
                raise RuntimeError(f'prelaunch MemFree below {PRELAUNCH_MIN_FREE_GIB:g} GiB '
                                   f'after eviction and a {PRELAUNCH_WAIT_S // 60} min wait; not launching')
            write_state(state)
            waited += 1
            stop.wait(30)
            raise_if_stopped(stop)
        state['phase'] = 'starting'
        state['launch_attempted'] = True
        write_state(state)
        started = datetime.now(timezone.utc)
        raise_if_stopped(stop)
        guard, log, ticks = bundle.launch_guard(output, RECEIPT, RECEIPT_SHA, ())
        state.update(guard_pid=guard.pid, guard_start_ticks=ticks)
        evictor = LoadEvictor(bundle.MODEL_ROOT)
        evictor.start()
        deadline = time.monotonic() + bundle.STARTUP_DEADLINE_S
        record = bundle.wait_launch_record(output, guard, RECEIPT_SHA, deadline, stop)
        state['container_id'] = record['cid']
        state['image_id'] = bundle.IMAGE
        write_state(state)
        bundle.capture_candidate_allocator_environment(output, ops, record)
        stopper = bundle.GuardStopper(output)

        class ResidentMonitor(bundle.RuntimeMonitor):
            def _loop(self):
                try:
                    while not self.cancel.wait(10):
                        self.sample()
                        write_state(state)
                        # Bound persistent telemetry to two 16 MiB segments per file.
                        for name in ('memory.jsonl', 'host-memory.jsonl', 'kernel-checks.jsonl'):
                            path = output / name
                            if path.exists() and path.stat().st_size > 16 * 1024**2:
                                path.replace(path.with_suffix('.previous.jsonl'))
                except BaseException as exc:
                    self.failure = f'{type(exc).__name__}: {exc}'
                    try:
                        self.stopper.stop(self.failure)
                    except BaseException as exc:
                        self.failure += f'; stop_failed: {exc}'
                finally:
                    self.done.set()

        monitor = ResidentMonitor(output, record, stopper, started)
        monitor.start()
        # Operational readiness only: exact models/server profile and one
        # serving health check. No canaries, benchmark tasks or comparison.
        bundle.wait_ready(output, monitor, deadline, stop)
        state['load_eviction'] = evictor.stop()
        monitor.arm_passive_models()
        state['phase'] = 'ready'
        write_state(state)
        lease.__exit__(None, None, None)
        lease_open = False
        ops.run(['systemctl', '--user', 'start', bundle.q.NARA_SERVICE], timeout=30)
        print('Flash permanent resident ready; research callers resumed.', flush=True)
        while not stop.wait(10):
            monitor.check()
            if guard.poll() is not None:
                raise RuntimeError('serving guard exited')
            write_state(state)
        state['phase'] = 'stopping'
    except BaseException as exc:
        state['phase'] = 'stopping' if stop.is_set() else 'fault'
        state['error'] = f'{type(exc).__name__}: {exc}'
        print(state['error'], flush=True)
    finally:
        if evictor is not None and 'load_eviction' not in state:
            state['load_eviction'] = evictor.stop()
        try:
            write_state(state)
        except BaseException as exc:
            print(f'Unable to persist stop status: {exc}', flush=True)
        if state.get('nara_transition_owned') and bundle is not None:
            try:
                bundle.q.HostOps().run(['systemctl', '--user', 'stop', bundle.q.NARA_SERVICE], timeout=45)
            except BaseException as exc:
                state['nara_stop_error'] = str(exc)
        # Normal operator shutdown drains cooperative callers before changing
        # the engine. Resource/kernel faults retain immediate hard-stop priority.
        if bundle is not None and guard is not None and not lease_open and state['phase'] != 'fault':
            deadline = time.monotonic() + 300
            while time.monotonic() < deadline:
                try:
                    lease = bundle.resource_lease(ROOT)
                    lease.__enter__()
                    lease_open = True
                    bundle.endpoint_idle(timeout=60)
                    break
                except BaseException as exc:
                    if lease_open:
                        state['drain_error'] = str(exc)
                        break
                    if monitor is not None and getattr(monitor, 'failure', None):
                        state['phase'] = 'fault'
                        state['error'] = monitor.failure
                        break
                    time.sleep(1)
            if not lease_open:
                # Explicit service stop has a bounded drain. Never leave an
                # unmonitored Docker process after systemd kills the supervisor.
                state['drain_error'] = 'Operator stop exceeded caller drain budget; cancelling owned engine.'
        if monitor is not None:
            try:
                monitor.quiesce()
                state['monitor'] = monitor.summary()
                if getattr(monitor, 'failure', None):
                    state['phase'] = 'fault'
                    state['error'] = monitor.failure
            except BaseException as exc:
                state['monitor_cleanup_error'] = str(exc)
                state['phase'] = 'fault'
        if guard is not None:
            state['guard_returncode'] = guard.poll()  # 8 = guard watchdog stopped first
        if stopper is not None:
            try:
                stopper.stop('resident supervisor stopping')
            except BaseException as exc:
                state['cleanup_error'] = str(exc)
                state['phase'] = 'fault'
        if guard is not None:
            try:
                bundle.terminate_guard_process(output, state, guard, 'resident supervisor stopping')
            except BaseException as exc:
                state['cleanup_error'] = str(exc)
                state['phase'] = 'fault'
        if log is not None:
            try:
                log.close()
            except BaseException as exc:
                state['log_close_error'] = str(exc)
        if bundle is not None and guard is not None:
            try:
                state['cleanup'] = bundle.finalize_owned_fallback(output, bundle.q.HostOps(), RECEIPT_SHA)
            except BaseException as exc:
                state['cleanup_error'] = str(exc)
                state['phase'] = 'fault'
        if lease_open:
            lease.__exit__(None, None, None)
        if state['phase'] != 'fault':
            state['phase'] = 'stopped'
        write_state(state)
    return 1 if state['phase'] == 'fault' else 0


def cleanup() -> int:
    """systemd stop-post cleanup, including a killed supervisor process."""
    if not STATE.exists():
        return 0
    state = json.loads(STATE.read_text())
    # Never stop a different live supervisor if a duplicate start was refused.
    if state.get('boot_id') == BOOT.read_text().strip():
        try:
            ticks = int(Path(f'/proc/{int(state["pid"])}/stat').read_text().rsplit(')', 1)[1].split()[19])
            if ticks == state.get('process_start_ticks'):
                raise RuntimeError('refusing cleanup while supervisor is alive')
        except (FileNotFoundError, ProcessLookupError):
            pass
    if state.get('artifact_dir') is None:
        return 0
    if state.get('bundle_sha256') != BUNDLE_SHA:
        raise RuntimeError('helper handoff required: stopped run used a different pinned helper')
    output = Path(state['artifact_dir'])
    if output.parent != PREP / 'runtime' or not output.name.startswith('resident-') or output.is_symlink():
        raise RuntimeError('resident cleanup path is invalid')
    bundle = load_bundle()
    bundle.verify_control_sources()
    result = bundle.finalize_owned_fallback(output, bundle.q.HostOps(), RECEIPT_SHA)
    state['stop_post_cleanup'] = result
    if state.get('phase') not in {'stopped', 'fault'}:
        state.update(phase='fault', error='Supervisor exited unexpectedly; owned container stopped.')
    write_state(state)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['run', 'selected', 'check-ready', 'cleanup'])
    command = parser.parse_args().command
    if command == 'selected':
        try:
            return 0 if selected() else 1
        except (OSError, ValueError, TypeError):
            return 3
    if command == 'check-ready':
        return 0 if check_ready() else 1
    if command == 'cleanup':
        return cleanup()
    return run()


if __name__ == '__main__':
    raise SystemExit(main())
