"""Unit tests for the model-aware generation-policy resolver."""

import json
from pathlib import Path

import pytest

from agent_wrapper.generation_policy import (
    PROFILES,
    UNSET,
    reasoning_text_from_message,
    resolve_generation_policy,
)


GEMMA_MODEL = "gemma-4-26b-a4b"
QWEN_MODEL = "qwen3.8-27b-nvfp4-mtp"


def _resolve(profile=None, backend="vllm-gemma", model=GEMMA_MODEL, **kwargs):
    return resolve_generation_policy(
        profile=profile,
        backend_name=backend,
        model_name=model,
        caller_tag="test/role",
        **kwargs,
    )


def test_no_profile_or_new_controls_is_exact_legacy_policy():
    resolved = _resolve()
    assert resolved.request_kwargs == {
        "temperature": 0.0,
        "top_p": 1.0,
        "seed": None,
    }
    assert resolved.logged_params == resolved.request_kwargs
    assert resolved.profile_name is None
    assert resolved.metadata_enabled is False


def test_scientist_profile_maps_to_gemma_sampling_without_qwen_effort():
    resolved = _resolve("scientist")
    assert resolved.request_kwargs == {
        "temperature": 0.7,
        "top_p": 0.95,
        "seed": None,
    }
    assert resolved.reasoning_effort is None
    assert resolved.sampling_extra == {}


def test_original_coding_and_critic_arms_remain_explicit_experiments():
    coding = _resolve(
        "coding_precise", backend="vllm-qwen", model=QWEN_MODEL)
    critic = _resolve("critic", backend="vllm-qwen", model=QWEN_MODEL)
    assert (coding.request_kwargs["temperature"], coding.request_kwargs["top_p"],
            coding.request_kwargs["reasoning_effort"]) == (0.2, 0.9, "medium")
    assert (critic.request_kwargs["temperature"], critic.request_kwargs["top_p"],
            critic.request_kwargs["reasoning_effort"]) == (0.7, 0.95, "medium")


def test_explicit_zero_beats_profile_via_unset_sentinel():
    resolved = _resolve("scientist", temperature=0.0, top_p=UNSET)
    assert resolved.request_kwargs["temperature"] == 0.0
    assert resolved.request_kwargs["top_p"] == 0.95


def test_qwen_effort_profile_reaches_top_level_request_field():
    resolved = _resolve(
        "critic_medium", backend="vllm-qwen", model=QWEN_MODEL)
    assert resolved.request_kwargs == {
        "temperature": 0.2,
        "top_p": 0.95,
        "seed": None,
        "reasoning_effort": "medium",
    }
    assert resolved.reasoning_effort == "medium"


@pytest.mark.parametrize("invalid", [None, "none", "minimal", "high", "max"])
def test_qwen_rejects_every_unsupported_effort_without_coercion(invalid):
    with pytest.raises(ValueError, match="Qwen.*reasoning_effort"):
        _resolve(
            "deterministic",
            backend="vllm-qwen",
            model=QWEN_MODEL,
            reasoning_effort=invalid,
        )


def test_qwen_card_profile_has_exact_documented_experimental_controls():
    resolved = _resolve(
        "qwen_card_thinking", backend="vllm-qwen", model=QWEN_MODEL)
    assert resolved.request_kwargs["temperature"] == 1.0
    assert resolved.request_kwargs["top_p"] == 0.95
    assert resolved.request_kwargs["reasoning_effort"] == "xhigh"
    assert resolved.request_kwargs["extra_body"] == {
        "top_k": 20,
        "min_p": 0,
        "presence_penalty": 0,
        "repetition_penalty": 1,
    }


def test_gemma_thinking_uses_chat_template_kwargs_and_no_effort():
    resolved = _resolve("gemma_card_thinking")
    assert "reasoning_effort" not in resolved.request_kwargs
    assert resolved.request_kwargs["extra_body"] == {
        "top_k": 64,
        "chat_template_kwargs": {"enable_thinking": True},
    }
    assert resolved.gemma_thinking is True
    assert resolved.preserve_tool_reasoning is True


def test_profiled_gemma_tool_history_preserves_reasoning_even_without_opt_in_thinking():
    # The exact pinned Gemma template enters its thinking/tool format whenever
    # tools are present; the history exception therefore applies to all named
    # Gemma profiles, not only gemma_card_thinking.
    assert _resolve("deterministic").preserve_tool_reasoning is True


def test_gemma_rejects_qwen_reasoning_control():
    with pytest.raises(ValueError, match="does not support reasoning_effort"):
        _resolve("scientist", reasoning_effort="medium")


def test_qwen_nonthinking_card_profile_matches_the_pinned_template_contract():
    resolved = _resolve(
        "qwen_card_instruct", backend="vllm-qwen", model=QWEN_MODEL)
    assert "reasoning_effort" not in resolved.request_kwargs
    assert resolved.reasoning_effort is None
    assert resolved.request_kwargs["temperature"] == 0.7
    assert resolved.request_kwargs["top_p"] == 0.8
    assert resolved.request_kwargs["extra_body"] == {
        "top_k": 20,
        "min_p": 0,
        "presence_penalty": 1.5,
        "repetition_penalty": 1,
        "chat_template_kwargs": {"enable_thinking": False},
    }


def test_qwen_refuses_ignored_effort_when_thinking_is_disabled():
    with pytest.raises(ValueError, match="ignored when Qwen thinking is disabled"):
        _resolve(
            "qwen_card_instruct",
            backend="vllm-qwen",
            model=QWEN_MODEL,
            reasoning_effort="low",
        )


@pytest.mark.parametrize("field", ["response_format", "guided_json", "structured_outputs"])
def test_qwen_rejects_known_structured_output_traps(field):
    with pytest.raises(ValueError, match="structured output"):
        _resolve(
            "critic_current",
            backend="vllm-qwen",
            model=QWEN_MODEL,
            extra_body={field: {}},
        )


def test_explicit_extra_body_overrides_profile_sampling_extra():
    resolved = _resolve(
        "qwen_card_thinking",
        backend="vllm-qwen",
        model=QWEN_MODEL,
        extra_body={"top_k": 7},
    )
    assert resolved.request_kwargs["extra_body"]["top_k"] == 7
    assert resolved.request_kwargs["extra_body"]["min_p"] == 0


def test_profile_backend_and_exact_model_are_both_validated():
    with pytest.raises(ValueError, match="not supported on backend"):
        _resolve("critic_low")
    with pytest.raises(ValueError, match="unsupported model"):
        _resolve("scientist", model="gemma-future-unqualified")
    with pytest.raises(ValueError, match="unsupported model"):
        _resolve(
            "critic_low", backend="vllm-qwen", model="qwen-future-unqualified")


def test_unknown_profile_is_an_observable_error():
    with pytest.raises(KeyError, match="unknown generation profile"):
        _resolve("not-a-profile")


def test_profiles_are_not_silently_applied_to_anthropic_or_ollama():
    with pytest.raises(ValueError, match="not supported on backend"):
        _resolve("scientist", backend="anthropic", model="claude-opus-4-7")
    with pytest.raises(ValueError, match="not supported on backend"):
        _resolve("precise", backend="ollama-coder", model="coder")


def test_caller_override_env_applies_only_without_explicit_profile(monkeypatch):
    monkeypatch.setenv(
        "WRAPPER_PROFILE_OVERRIDES",
        json.dumps({"test/role": "gemma_card"}),
    )
    implicit = _resolve()
    explicit = _resolve("scientist")
    assert implicit.profile_name == "gemma_card"
    assert implicit.request_kwargs["extra_body"] == {"top_k": 64}
    assert explicit.profile_name == "scientist"
    assert explicit.request_kwargs["temperature"] == 0.7


def test_malformed_profile_override_env_fails_closed(monkeypatch):
    monkeypatch.setenv("WRAPPER_PROFILE_OVERRIDES", "not-json")
    with pytest.raises(ValueError, match="WRAPPER_PROFILE_OVERRIDES"):
        _resolve()


def test_call_schema_profile_enum_covers_the_resolver_catalog_exactly():
    schema = json.loads(
        (Path(__file__).resolve().parent.parent
         / "schema" / "calls.jsonl.schema.json").read_text())
    assert set(schema["properties"]["profile"]["enum"]) == set(PROFILES)


def test_reasoning_extraction_prefers_nonempty_compatibility_field():
    message = type("Message", (), {
        "reasoning": "",
        "reasoning_content": "actual thought",
        "model_extra": None,
    })()
    assert reasoning_text_from_message(message) == "actual thought"
