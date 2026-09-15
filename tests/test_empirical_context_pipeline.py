"""An experiment bridge's bounded result must reach both model inputs.

These hermetic tests capture the first Nara request and the critic sub-agent
prompt. They never call a model or use operator private evidence.
"""
from __future__ import annotations

import json

import pytest

from agent_wrapper.wrapper import get_run_id
from orchestrator import active_run, empirical_context, nara, research_campaign
from orchestrator.subagent import SubAgentResult
from workers import critic_loop_v0 as critic

OUTCOME = {
    "experiment_id": "known-opponent-utility-response-pilot-v1",
    "metric": "disclosed_utility_action_validity_and_full_horizon_regret",
    "value": {
        "attempted_calls": 108,
        "valid_action_calls": 96,
        "complete_episodes": 12,
        "zero_regret_complete_episodes": 3,
        "comprehension_passed": 0,
        "run_sha256": "a" * 64,
        "manifest_sha256": "b" * 64,
    },
    "trials": 12,
    "summary": "Observed local pilot behavior; no theoretical novelty claim.",
}


class _Runtime:
    def __init__(self):
        self.state = {}
        self.events = []

    def write_state(self, path, value):
        self.state[path] = json.loads(json.dumps(value))

    def read_state(self, path):
        return self.state.get(path)

    def delete_state(self, path):
        self.state.pop(path, None)

    def log_event(self, event, *, agent=None):
        self.events.append(event)

    def dispatch_tool(self, name, args, *, parent_request_id):
        raise AssertionError("backend must stop before dispatch")


class _CaptureBackend:
    name = "fake-backend"
    default_model = "fake-model"
    model_version = "fake/0"
    def __init__(self, requests):
        self.requests = requests
        self.host_metadata = {}

    def create_chat(self, **kwargs):
        self.requests.append(kwargs)
        raise RuntimeError("captured first Nara model payload")


def _nara_seams(monkeypatch, tmp_path, requests):
    monkeypatch.setattr(active_run, "ACTIVE_RUN_PATH", tmp_path / "active-run.json")
    monkeypatch.setattr(research_campaign, "load_active_campaign", lambda: None)
    monkeypatch.setattr(nara, "_next_iteration_id", lambda: "iter-2099-01-01-001")
    monkeypatch.setattr(nara, "get_backend", lambda *_a, **_k: _CaptureBackend(requests))
    monkeypatch.setattr(nara, "_meta_review", lambda **_k: {
        "status": "passed", "result": {"conditioning_bullets": []},
    })


def test_admitted_shape_reaches_nara_first_payload_and_critic(cache, monkeypatch, tmp_path):
    requests = []
    _nara_seams(monkeypatch, tmp_path, requests)
    with pytest.raises(RuntimeError, match="captured first Nara model payload"):
        nara.run_iteration("registered question", runtime=_Runtime(),
                           experiment_outcome=OUTCOME, log_path=None)
    assert len(requests) == 1
    first_user = requests[0]["messages"][1]["content"]
    snapshot = cache.read_entry("iter-2099-01-01-001", "empirical_context")
    assert snapshot == empirical_context.build(OUTCOME)
    assert snapshot["outcome_sha256"] in first_user
    assert OUTCOME["value"]["run_sha256"] in first_user
    assert "does not establish theoretical novelty" in first_user
    assert get_run_id() is None

    cache.write_entry("iter-2099-01-01-001", "retrieval", {
        "status": "passed", "result": {"k": 0, "neighbors": []},
    })
    critic_requests = []

    def _critic_stub(**kwargs):
        critic_requests.append(kwargs)
        return SubAgentResult(
            status="passed",
            result={"verdict": "undecidable", "rationale": "No matching evidence",
                    "contradicting_paper_id": None},
            errors=[], wrapper_call_ids=["critic-test"], turns_used=1,
            wall_seconds=0.1, output_tokens_used=20,
        )

    monkeypatch.setattr(critic, "run_subagent", _critic_stub)
    critic.critic_loop_v0("proposed hypothesis", "iter-2099-01-01-001")
    assert len(critic_requests) == 1
    critic_user = critic_requests[0]["user_prompt"]
    assert snapshot["outcome_sha256"] in critic_user
    assert OUTCOME["value"]["run_sha256"] in critic_user
    assert "otherwise say it remains untested" in critic_user


def test_no_experiment_preserves_original_payload(cache, monkeypatch, tmp_path):
    requests = []
    _nara_seams(monkeypatch, tmp_path, requests)
    with pytest.raises(RuntimeError, match="captured first Nara model payload"):
        nara.run_iteration("ordinary topic", runtime=_Runtime(), log_path=None)
    assert "EMPIRICAL OBSERVATION" not in requests[0]["messages"][1]["content"]
    assert not cache.has_entry("iter-2099-01-01-001", "empirical_context")


def test_invalid_or_oversized_outcome_refuses_before_model(cache, monkeypatch, tmp_path):
    requests = []
    _nara_seams(monkeypatch, tmp_path, requests)
    bad = dict(OUTCOME, summary="x" * 901)
    with pytest.raises(ValueError, match="summary exceeds"):
        nara.run_iteration("ordinary topic", runtime=_Runtime(),
                           experiment_outcome=bad, log_path=None)
    assert requests == []
    assert not cache.has_entry("iter-2099-01-01-001", "empirical_context")


def test_context_freezes_caller_owned_outcome():
    supplied = json.loads(json.dumps(OUTCOME))
    entry = empirical_context.build(supplied)
    expected_note = empirical_context.note(entry)
    supplied["value"]["complete_episodes"] = 0
    assert entry["outcome"]["value"]["complete_episodes"] == 12
    assert empirical_context.note(entry) == expected_note


def test_tampered_empirical_cache_refuses_critic_model(cache, monkeypatch):
    cache.write_entry("iter-tamper", "retrieval", {
        "status": "passed", "result": {"k": 0, "neighbors": []},
    })
    entry = empirical_context.build(OUTCOME)
    entry["outcome"]["trials"] = 13
    cache.write_entry("iter-tamper", "empirical_context", entry)
    monkeypatch.setattr(critic, "run_subagent", lambda **_kw: pytest.fail(
        "untrusted empirical evidence reached critic model"))
    result = critic.critic_loop_v0("hypothesis", "iter-tamper")
    assert result["status"] == "error"
    assert any("empirical context cache is untrusted" in e for e in result["errors"])
