"""Policy and telemetry coverage for the two loops that bypass the wrapper."""
import copy
import json
from types import SimpleNamespace

import pytest

from agent_wrapper.wrapper import MEMORY_LOG
from orchestrator import nara, subagent


def response(tool=False):
    tc = SimpleNamespace(id='call-1', type='function', function=SimpleNamespace(
        name='identity', arguments='{"value": 3}'))
    return SimpleNamespace(model='gemma-4-26b-a4b',
        choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(
            content='' if tool else '{"ok": true}', tool_calls=[tc] if tool else [],
            reasoning='Check the identity operation.'))],
        usage=SimpleNamespace(prompt_tokens=4, completion_tokens=5))


class CaptureBackend:
    name = 'vllm-gemma'
    default_model = 'gemma-4-26b-a4b'
    model_version = 'test/gemma'
    host_metadata = {'backend': 'vllm'}

    def __init__(self, responses=None):
        self.calls = []
        self.responses = list(responses or [response()])

    def create_chat(self, **kwargs):
        self.calls.append(copy.deepcopy(kwargs))
        return self.responses.pop(0)


@pytest.mark.parametrize('profile,temperature,top_p', [(None, .2, None), ('scientist', .7, .95)])
def test_subagent_request_matches_persisted_record(monkeypatch, tmp_path, profile, temperature, top_p):
    backend = CaptureBackend()
    monkeypatch.setattr(subagent, 'get_backend', lambda _: backend)
    result = subagent.run_subagent(name='test', system_prompt='Return JSON', user_prompt='ping',
        expected_output_schema={'type': 'object'}, profile=profile)
    assert result.status == 'passed'
    request = backend.calls[0]
    assert request['temperature'] == temperature
    assert request.get('top_p') == top_p
    record = json.loads((tmp_path / 'calls.jsonl').read_text())
    assert record['temperature'] == temperature
    if profile:
        assert record['profile'] == profile
        assert record['finish_reason'] == 'stop'
        assert record['reasoning_chars'] > 0
    else:
        assert 'profile' not in record
        assert set(request) == {'model', 'messages', 'tools', 'temperature', 'max_tokens'}


def test_explicit_none_keeps_subagent_log_in_memory(monkeypatch, tmp_path):
    monkeypatch.setattr(subagent, 'get_backend', lambda _: CaptureBackend())
    before = len(MEMORY_LOG)
    subagent.run_subagent(name='test', system_prompt='JSON', user_prompt='ping',
        expected_output_schema={'type': 'object'}, log_path=None)
    assert len(MEMORY_LOG) == before + 1
    assert not (tmp_path / 'calls.jsonl').exists()


def test_subagent_honors_call_time_environment_log(monkeypatch, tmp_path):
    monkeypatch.setattr(subagent, 'get_backend', lambda _: CaptureBackend())
    target = tmp_path / 'experiment' / 'calls.jsonl'
    monkeypatch.setenv('LOOP_V0_CALLS_LOG', str(target))
    subagent.run_subagent(name='test', system_prompt='JSON', user_prompt='ping',
        expected_output_schema={'type': 'object'})
    assert json.loads(target.read_text())['caller_tag'] == 'subagent.test'
    assert not (tmp_path / 'calls.jsonl').exists()


def test_profiled_subagent_preserves_reasoning_on_tool_history(monkeypatch):
    backend = CaptureBackend([response(tool=True), response()])
    monkeypatch.setattr(subagent, 'get_backend', lambda _: backend)
    result = subagent.run_subagent(name='test', system_prompt='JSON', user_prompt='ping',
        expected_output_schema={'type': 'object'}, profile='gemma_card_thinking',
        tools=[{'type': 'function', 'function': {'name': 'identity',
            'parameters': {'type': 'object'}}}],
        tool_dispatch={'identity': lambda **kw: {'value': kw['value']}}, log_path=None)
    assert result.status == 'passed'
    assistant = next(m for m in backend.calls[1]['messages'] if m['role'] == 'assistant')
    assert assistant['reasoning'] == 'Check the identity operation.'


class MemoryRuntime:
    def __init__(self):
        self.state = {}
    def write_state(self, path, value):
        self.state[path] = copy.deepcopy(value)
    def delete_state(self, path):
        self.state.pop(path, None)
    def log_event(self, *args, **kwargs):
        pass


@pytest.mark.parametrize('profile,temperature', [(None, 0.0), ('scientist', .7)])
def test_nara_direct_call_uses_opt_in_profile(monkeypatch, profile, temperature):
    class StopBackend(CaptureBackend):
        def create_chat(self, **kwargs):
            self.calls.append(kwargs)
            raise RuntimeError('intentional first-call stop')
    backend = StopBackend()
    monkeypatch.setattr(nara, 'get_backend', lambda _: backend)
    monkeypatch.setattr(nara, '_next_iteration_id', lambda: 'iter-2099-01-01-001')
    monkeypatch.setattr(nara, '_meta_review', lambda **kw: {'status': 'passed', 'result': {}})
    with pytest.raises(RuntimeError, match='intentional first-call stop'):
        nara.run_iteration('test', runtime=MemoryRuntime(), profile=profile, log_path=None)
    request = backend.calls[0]
    assert request['temperature'] == temperature
    assert request.get('top_p') == (.95 if profile else None)
    assert request.get('extra_body') is None


def test_nara_records_resolved_sampling(monkeypatch):
    policy = nara.resolve_generation_policy('scientist', 'vllm-gemma', 'gemma-4-26b-a4b')
    record = nara._record_turn([{'role': 'user', 'content': 'ping'}], response(), 3.0, 'test', None, None,
        model_version='test/gemma', host_metadata={'backend': 'vllm'},
        generation_policy=policy)
    assert record['temperature'] == .7
    assert record['top_p'] == .95
    assert record['profile'] == 'scientist'


def test_qwen_profile_preserves_non_tool_repair_history(monkeypatch):
    bad = response()
    bad.choices[0].message.content = 'I will produce the object next.'
    backend = CaptureBackend([bad, response()])
    backend.name = 'vllm-qwen'
    backend.default_model = 'qwen3.8-27b-nvfp4-mtp'
    monkeypatch.setattr(subagent, 'get_backend', lambda _: backend)
    result = subagent.run_subagent(name='repair', system_prompt='JSON', user_prompt='ping',
        expected_output_schema={'type': 'object'}, profile='critic_medium', log_path=None)
    assert result.status == 'passed'
    assistant = next(m for m in backend.calls[1]['messages'] if m['role'] == 'assistant')
    assert assistant['reasoning'] == 'Check the identity operation.'


def test_qwen_nara_profile_preserves_no_tool_reprompt(monkeypatch):
    class StopAfterOne(CaptureBackend):
        name = 'vllm-qwen'
        default_model = 'qwen3.8-27b-nvfp4-mtp'
        def create_chat(self, **kwargs):
            if self.calls:
                self.calls.append(copy.deepcopy(kwargs))
                raise RuntimeError('stop after reprompt')
            return super().create_chat(**kwargs)
    backend = StopAfterOne()
    monkeypatch.setattr(nara, 'get_backend', lambda _: backend)
    monkeypatch.setattr(nara, '_next_iteration_id', lambda: 'iter-2099-01-01-002')
    monkeypatch.setattr(nara, '_meta_review', lambda **kw: {'status': 'passed', 'result': {}})
    with pytest.raises(RuntimeError, match='stop after reprompt'):
        nara.run_iteration('test', runtime=MemoryRuntime(), profile='critic_medium', log_path=None)
    assistant = next(m for m in backend.calls[1]['messages'] if m['role'] == 'assistant')
    assert assistant['reasoning'] == 'Check the identity operation.'
