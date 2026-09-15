"""Exercise real resident supervisor/worker/harness/gate with fake host I/O.

No Docker, systemd, model endpoint or GPU is contacted. Only qualification
file admission and operating-system observations are injected; result,
restoration, memory, private SSE and supervisor artifacts use real producers.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from bench.flash_next_ab import evaluation_window as ew
from bench.flash_next_ab import harness, transport
from bench.flash_next_ab import resident_admission as gate
from bench.flash_next_ab import resident_evaluation_window as resident
from bench.flash_next_ab.manifest import build_plan, make_arm_receipt, sha256_json


def _benchmark():
    arms = [
        make_arm_receipt(
            'resident', qualification_receipt_sha256='1' * 64,
            artifact_sha256_by_endpoint={'resident_gemma': '2' * 64, 'resident_qwen': '3' * 64},
            runtime_sha256_by_endpoint={'resident_gemma': '4' * 64, 'resident_qwen': '5' * 64},
        ),
        make_arm_receipt(
            'flash', qualification_receipt_sha256='6' * 64,
            artifact_sha256_by_endpoint={'flash_next': '7' * 64},
            runtime_sha256_by_endpoint={'flash_next': '8' * 64},
        ),
    ]
    full, _ = build_plan(arms, families=['objective'])
    # Force declaration order to differ from sorted JSON object keys so this
    # also exercises the real run writer's canonical serialization.
    cells = list(reversed(full['declared_cells'][:2]))
    return build_plan(arms, families=['objective'], cell_ids=cells)[0]


class FakeHost:
    """Closed in-memory Docker/systemd surface; unknown commands fail."""
    def __init__(self):
        self.nara_active = True
        self.nara_pid = 300
        self.sentinel = None
        self.commands = []
        self.residents = []
        for index, spec in enumerate(resident.RESIDENTS):
            self.residents.append({
                'id': spec['id'], 'name': spec['name'], 'image': spec['image_id'],
                'running': True, 'oom_killed': False, 'state_error': '',
                'restart_policy': 'unless-stopped', 'restart_count': 0,
                'pid': 200 + index, 'started_at': '2026-09-15T00:00:00+00:00',
            })

    def inspect(self, identity):
        for row in self.residents + ([self.sentinel] if self.sentinel else []):
            if identity in (row['id'], row['name']):
                return copy.deepcopy(row)
        return None

    def http_bytes(self, url, **kwargs):
        assert url in {row['health_url'] for row in resident.RESIDENTS}
        return b'{}'

    def run(self, argv, **kwargs):
        self.commands.append(argv)
        if argv[:3] == ['systemctl', '--user', 'show']:
            text = (f'ActiveState={"active" if self.nara_active else "inactive"}\n'
                    f'SubState={"running" if self.nara_active else "dead"}\n'
                    f'MainPID={self.nara_pid if self.nara_active else 0}\n')
        elif argv[:3] == ['systemctl', '--user', 'stop']:
            self.nara_active = False
            text = ''
        elif argv[:3] == ['systemctl', '--user', 'start']:
            self.nara_active = True
            self.nara_pid += 1
            text = ''
        elif argv[:2] == ['docker', 'create']:
            assert self.sentinel is None and '--gpus' not in argv
            self.sentinel = {
                'id': 'e' * 64, 'name': argv[argv.index('--name') + 1],
                'image': resident.IMAGE_ID, 'running': False,
                'oom_killed': False, 'state_error': '', 'restart_policy': 'no',
            }
            text = self.sentinel['id']
        elif argv[:2] == ['docker', 'rm']:
            assert self.sentinel is not None and argv[2] == self.sentinel['id']
            self.sentinel = None
            text = ''
        else:
            raise AssertionError(f'Unexpected host command: {argv}')
        return SimpleNamespace(stdout=text, returncode=0)


def _response(endpoint, messages, *, fail, **kwargs):
    accumulator = transport.StreamAccumulator(endpoint.served_model)
    body = transport.request_body(endpoint, messages, kwargs['policy'], kwargs['max_tokens'],
                                  kwargs['seed'], kwargs.get('tools'))
    if fail:
        error = TimeoutError('synthetic timeout before first byte')
        transport._attach_private_evidence(error, accumulator, b'', response_bytes=0)
        raise error
    events = [
        {'id': 'cmpl-fixture', 'model': endpoint.served_model,
         'choices': [{'index': 0, 'delta': {'content': '{}'}, 'finish_reason': 'stop'}]},
        {'id': 'cmpl-fixture', 'model': endpoint.served_model, 'choices': [],
         'usage': {'prompt_tokens': 10, 'completion_tokens': 1, 'total_tokens': 11}},
    ]
    payloads = [json.dumps(event) for event in events] + ['[DONE]']
    raw = b''.join(('data: ' + data + '\n\n').encode() for data in payloads)
    for data in payloads:
        accumulator.accept(data)
    response = accumulator.result()
    response.update({
        'request_sha256': hashlib.sha256(transport.canonical(body)).hexdigest(),
        'response_stream_sha256': hashlib.sha256(raw).hexdigest(),
        'response_id': accumulator.response_id, 'response_model': endpoint.served_model,
        'latency_s': 0.01, 'ttft_s': 0.005,
        'private_evidence': transport._private_response_evidence(accumulator, raw, response_bytes=len(raw)),
    })
    return response


@pytest.mark.parametrize('first_call_timeout', [False, True])
def test_resident_real_producers_admit_complete_run_including_timeout(
    tmp_path, monkeypatch, first_call_timeout
):
    benchmark = _benchmark()
    pair = 'qfn-ab-resident-producer-test'
    output = tmp_path / (pair + '.resident')
    window = SimpleNamespace(
        pair_id=pair, source_path=tmp_path / (pair + '.resident.window.json'),
        source_sha256='a' * 64, benchmark_plan_file_sha256=sha256_json(benchmark),
        qualification_summary={'qualification_receipt_sha256': '1' * 64},
        benchmark_plan=benchmark, runtime_budget_seconds=10430,
    )
    host = FakeHost()
    monkeypatch.setattr(resident, 'HostOps', lambda: host)
    monkeypatch.setattr(resident, '_inspect_container', lambda ops, identity: ops.inspect(identity))
    monkeypatch.setattr(resident, '_available_gib', lambda: 44.0)
    monkeypatch.setattr(resident, '_pswpout_pages', lambda: 42)
    monkeypatch.setattr(resident, 'resource_lease', lambda root: nullcontext())
    monkeypatch.setattr(resident, 'canonical_root', lambda root: tmp_path)
    monkeypatch.setattr(resident, 'WINDOW_RUN_ROOT', tmp_path)
    journal = tmp_path / 'usage.jsonl'
    monkeypatch.setattr(ew, 'RESEARCH_LEDGER', journal)
    monkeypatch.setattr(resident, 'RESEARCH_LEDGER', journal)
    monkeypatch.setattr(gate, 'RESEARCH_LEDGER', journal)
    monkeypatch.setattr(gate, 'load_evaluation_window', lambda *args, **kwargs: window)
    monkeypatch.setattr(resident, '_qualification_gate', lambda window: lambda plan, cohort: None)

    def cgroup(container_id, pid):
        return {
            'path': f'/system.slice/docker-{container_id}.scope',
            'process_start_ticks': pid * 100, 'memory_max_bytes': 'max',
            'memory_swap_max_bytes': 'max', 'memory_current_bytes': 30000000,
            'memory_swap_current_bytes': 1024, 'memory_events_oom': 0,
            'memory_events_oom_kill': 0,
        }

    monkeypatch.setattr(resident, '_incumbent_cgroup_snapshot', cgroup)
    calls = []

    def invoke(endpoint, messages, **kwargs):
        assert host.nara_active is False and host.sentinel is not None
        calls.append(endpoint.name)
        return _response(endpoint, messages, fail=first_call_timeout and len(calls) == 1, **kwargs)

    def real_harness(*args, **kwargs):
        return harness.run_harness(*args, invoke_fn=invoke, **kwargs)

    monkeypatch.setattr(resident, 'run_harness', real_harness)
    plan = resident._resident_plan(window, output)
    # The original pair's producer receipt names the older registered checkout.
    # Simulate that exact root when replaying this fixture from the follow-on
    # checkout; the production execution guard remains strict.
    monkeypatch.setattr(resident, 'ROOT', ew.REGISTERED_CODE_ROOT)

    class InProcessWorker:
        def __init__(self, command, **kwargs):
            assert '--worker' in command and kwargs['start_new_session'] is True
            self.pid = os.getpid()
            self.returncode = resident._worker(window, plan, output)

        def poll(self):
            return self.returncode

        def wait(self, **kwargs):
            return self.returncode

    monkeypatch.setattr(resident.subprocess, 'Popen', InProcessWorker)
    code = resident._supervise(window, plan, output)
    result = json.loads((output / 'result.json').read_text())
    assert code == 0, result
    proof = gate.validate_completed_resident_window(window.source_path, output)
    assert proof['restoration_verified'] is True
    run = json.loads((output / 'harness/run.json').read_text())
    assert run['status'] == 'complete' and len(run['outcomes']) == 2 and len(calls) == 2
    assert host.nara_active and host.nara_pid == 301 and host.sentinel is None
    assert not any(argv[:2] in (['docker', 'stop'], ['docker', 'start']) for argv in host.commands)
    if first_call_timeout:
        assert run['outcomes'][0]['calls'][0]['status'] == 'timeout'
