"""Strict, model-aware generation policies for local vLLM calls.

The resolver is deliberately inert for legacy calls: when a caller supplies
neither a profile nor a new policy control, it returns the same three sampling
kwargs the wrapper historically sent.  Named profiles are experimental arms;
they do not change any call site's default policy by themselves.
"""

from __future__ import annotations

import copy
import json
import math
import os
from dataclasses import dataclass, field
from typing import Any, Mapping


class _Unset:
    def __repr__(self) -> str:
        return "UNSET"


UNSET = _Unset()

_GEMMA_BACKEND = "vllm-gemma"
_QWEN_BACKEND = "vllm-qwen"
_LOCAL_BACKENDS = frozenset({_GEMMA_BACKEND, _QWEN_BACKEND})
_SUPPORTED_MODELS = {
    _GEMMA_BACKEND: frozenset({"gemma-4-26b-a4b"}),
    _QWEN_BACKEND: frozenset({"qwen3.8-27b-nvfp4-mtp"}),
}
_QWEN_EFFORTS = frozenset({"low", "medium", "xhigh"})
_QWEN_STRUCTURED_OUTPUT_TRAPS = frozenset({
    "guided_choice",
    "guided_grammar",
    "guided_json",
    "guided_regex",
    "json_schema",
    "response_format",
    "structured_outputs",
})
_ALLOWED_EXTRA_BODY = frozenset({
    "top_k",
    "min_p",
    "presence_penalty",
    "repetition_penalty",
    "chat_template_kwargs",
})


@dataclass(frozen=True)
class _Profile:
    temperature: float
    top_p: float
    backends: frozenset[str] = _LOCAL_BACKENDS
    qwen_reasoning_effort: str | None = None
    extra_body: Mapping[str, Any] = field(default_factory=dict)
    gemma_thinking: bool = False


# Control profiles reproduce the policy clusters already present at call
# sites.  Card profiles are isolated experimental arms, not new defaults.
PROFILES: Mapping[str, _Profile] = {
    "deterministic": _Profile(0.0, 1.0),
    "planner": _Profile(0.1, 0.9),
    "precise": _Profile(0.2, 0.95),
    # Original Codex handoff arms retained alongside the observed-control
    # profiles above. They differ intentionally and must be named explicitly.
    "coding_precise": _Profile(0.2, 0.9, qwen_reasoning_effort="medium"),
    "dialog": _Profile(0.3, 0.9),
    "scientist": _Profile(0.7, 0.95),
    "critic_current": _Profile(
        0.2, 0.95, frozenset({_QWEN_BACKEND}), "xhigh"),
    "critic_medium": _Profile(
        0.2, 0.95, frozenset({_QWEN_BACKEND}), "medium"),
    "critic_low": _Profile(
        0.2, 0.95, frozenset({_QWEN_BACKEND}), "low"),
    "critic": _Profile(0.7, 0.95, qwen_reasoning_effort="medium"),
    "qwen_card_thinking": _Profile(
        1.0,
        0.95,
        frozenset({_QWEN_BACKEND}),
        "xhigh",
        {
            "top_k": 20,
            "min_p": 0,
            "presence_penalty": 0,
            "repetition_penalty": 1,
        },
    ),
    "qwen_card_coding": _Profile(
        0.6,
        0.95,
        frozenset({_QWEN_BACKEND}),
        "medium",
        {"top_k": 20},
    ),
    "qwen_card_instruct": _Profile(
        0.7,
        0.8,
        frozenset({_QWEN_BACKEND}),
        extra_body={
            "top_k": 20,
            "min_p": 0,
            "presence_penalty": 1.5,
            "repetition_penalty": 1,
            "chat_template_kwargs": {"enable_thinking": False},
        },
    ),
    "gemma_card": _Profile(
        1.0, 0.95, frozenset({_GEMMA_BACKEND}), extra_body={"top_k": 64}),
    "gemma_card_thinking": _Profile(
        1.0,
        0.95,
        frozenset({_GEMMA_BACKEND}),
        extra_body={
            "top_k": 64,
            "chat_template_kwargs": {"enable_thinking": True},
        },
        gemma_thinking=True,
    ),
    "explore": _Profile(1.0, 0.95, qwen_reasoning_effort="medium"),
}


@dataclass(frozen=True)
class ResolvedGenerationPolicy:
    """Validated request kwargs plus schema-safe effective-policy metadata."""

    request_kwargs: Mapping[str, Any]
    logged_params: Mapping[str, Any]
    profile_name: str | None
    reasoning_effort: str | None
    sampling_extra: Mapping[str, Any]
    gemma_thinking: bool
    preserve_tool_reasoning: bool
    metadata_enabled: bool


def _profile_override(caller_tag: str | None) -> str | None:
    raw = os.environ.get("WRAPPER_PROFILE_OVERRIDES")
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "WRAPPER_PROFILE_OVERRIDES must be a JSON object of caller tags "
            "to profile names") from exc
    if not isinstance(value, dict) or any(
            not isinstance(k, str) or not isinstance(v, str)
            for k, v in value.items()):
        raise ValueError(
            "WRAPPER_PROFILE_OVERRIDES must be a JSON object of caller tags "
            "to profile names")
    return value.get(caller_tag) if caller_tag is not None else None


def _validate_number(name: str, value: Any, low: float, high: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number in [{low}, {high}]")
    if not math.isfinite(float(value)) or not low <= float(value) <= high:
        raise ValueError(f"{name} must be a finite number in [{low}, {high}]")


def _merge_extra(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(dict(base))
    for key, value in override.items():
        if (key == "chat_template_kwargs"
                and isinstance(merged.get(key), dict)
                and isinstance(value, Mapping)):
            merged[key].update(copy.deepcopy(dict(value)))
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _validate_extra_body(backend_name: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("extra_body must be an object")
    extra = copy.deepcopy(dict(value))
    if backend_name == _QWEN_BACKEND:
        trapped = sorted(_QWEN_STRUCTURED_OUTPUT_TRAPS.intersection(extra))
        if trapped:
            raise ValueError(
                "structured output is not supported on the pinned Qwen "
                f"backend; refused fields: {trapped}")
    unknown = sorted(set(extra) - _ALLOWED_EXTRA_BODY)
    if unknown:
        raise ValueError(
            f"unsupported extra_body fields for {backend_name}: {unknown}")

    if "top_k" in extra:
        top_k = extra["top_k"]
        if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 0:
            raise ValueError("extra_body.top_k must be a non-negative integer")
    if "min_p" in extra:
        _validate_number("extra_body.min_p", extra["min_p"], 0, 1)
    for name in ("presence_penalty", "repetition_penalty"):
        if name in extra:
            _validate_number(f"extra_body.{name}", extra[name], -2, 2)

    template = extra.get("chat_template_kwargs")
    if template is not None:
        if not isinstance(template, Mapping):
            raise ValueError("extra_body.chat_template_kwargs must be an object")
        template = dict(template)
        if backend_name == _QWEN_BACKEND:
            if "reasoning_effort" in template:
                raise ValueError(
                    "put Qwen reasoning_effort in the top-level request field")
            unknown_template = sorted(set(template) - {"enable_thinking"})
            if unknown_template:
                raise ValueError(
                    "unsupported Qwen chat_template_kwargs fields: "
                    f"{unknown_template}")
            if ("enable_thinking" in template
                    and not isinstance(template["enable_thinking"], bool)):
                raise ValueError("Qwen enable_thinking must be boolean")
        elif backend_name == _GEMMA_BACKEND:
            unknown_template = sorted(set(template) - {"enable_thinking"})
            if unknown_template:
                raise ValueError(
                    "unsupported Gemma chat_template_kwargs fields: "
                    f"{unknown_template}")
            if ("enable_thinking" in template
                    and not isinstance(template["enable_thinking"], bool)):
                raise ValueError("Gemma enable_thinking must be boolean")
        extra["chat_template_kwargs"] = template

    try:
        json.dumps(extra)
    except (TypeError, ValueError) as exc:
        raise ValueError("extra_body must be JSON-serializable") from exc
    return extra


def resolve_generation_policy(
    profile: str | None,
    backend_name: str,
    model_name: str,
    *,
    caller_tag: str | None = None,
    temperature: Any = UNSET,
    top_p: Any = UNSET,
    seed: Any = UNSET,
    reasoning_effort: Any = UNSET,
    extra_body: Any = UNSET,
) -> ResolvedGenerationPolicy:
    """Resolve one policy with explicit-call values taking precedence.

    Exact backend/model validation is activated only when a named profile or
    a new control (reasoning_effort/extra_body) is requested.  This preserves
    all pre-policy backend and model behavior for calls that do not opt in.
    """

    selected = profile if profile is not None else _profile_override(caller_tag)
    spec = None
    if selected is not None:
        if selected not in PROFILES:
            raise KeyError(
                f"unknown generation profile {selected!r}; "
                f"known profiles: {sorted(PROFILES)}")
        spec = PROFILES[selected]
        if backend_name not in spec.backends:
            raise ValueError(
                f"profile {selected!r} is not supported on backend "
                f"{backend_name!r}")

    new_controls = reasoning_effort is not UNSET or extra_body is not UNSET
    metadata_enabled = spec is not None or new_controls
    if metadata_enabled:
        if backend_name not in _LOCAL_BACKENDS:
            raise ValueError(
                f"generation profiles are not supported on backend {backend_name!r}")
        supported = _SUPPORTED_MODELS[backend_name]
        if model_name not in supported:
            raise ValueError(
                f"unsupported model {model_name!r} for backend {backend_name!r}; "
                f"qualified models: {sorted(supported)}")

    resolved_temperature = (
        temperature if temperature is not UNSET
        else spec.temperature if spec is not None
        else 0.0)
    resolved_top_p = (
        top_p if top_p is not UNSET
        else spec.top_p if spec is not None
        else 1.0)
    resolved_seed = None if seed is UNSET else seed
    _validate_number("temperature", resolved_temperature, 0, 2)
    _validate_number("top_p", resolved_top_p, 0, 1)
    if (resolved_seed is not None
            and (isinstance(resolved_seed, bool)
                 or not isinstance(resolved_seed, int))):
        raise ValueError("seed must be an integer or null")

    profile_effort = None
    if spec is not None and backend_name == _QWEN_BACKEND:
        profile_effort = spec.qwen_reasoning_effort
    resolved_effort = reasoning_effort if reasoning_effort is not UNSET else profile_effort
    if reasoning_effort is not UNSET:
        if backend_name != _QWEN_BACKEND:
            raise ValueError(
                f"backend {backend_name!r} does not support reasoning_effort")
        if resolved_effort not in _QWEN_EFFORTS:
            raise ValueError(
                "Qwen reasoning_effort must be one of low, medium, xhigh; "
                f"got {resolved_effort!r}")
    elif resolved_effort is not None and resolved_effort not in _QWEN_EFFORTS:
        # Profile definitions are static, but keep the invariant local to the
        # resolver so future additions cannot bypass validation.
        raise ValueError(
            "Qwen reasoning_effort must be one of low, medium, xhigh; "
            f"got {resolved_effort!r}")

    profile_extra = spec.extra_body if spec is not None else {}
    explicit_extra = {} if extra_body is UNSET else extra_body
    if not isinstance(explicit_extra, Mapping):
        raise ValueError("extra_body must be an object")
    merged_extra = _merge_extra(profile_extra, explicit_extra)
    if merged_extra:
        if backend_name not in _LOCAL_BACKENDS:
            raise ValueError(
                f"extra_body is not supported on backend {backend_name!r}")
        merged_extra = _validate_extra_body(backend_name, merged_extra)

    qwen_thinking = bool(
        backend_name == _QWEN_BACKEND
        and merged_extra.get("chat_template_kwargs", {}).get(
            "enable_thinking", True))
    if backend_name == _QWEN_BACKEND and not qwen_thinking and resolved_effort is not None:
        raise ValueError(
            "reasoning_effort is ignored when Qwen thinking is disabled; "
            "omit it instead")

    request_kwargs: dict[str, Any] = {
        "temperature": resolved_temperature,
        "top_p": resolved_top_p,
        "seed": resolved_seed,
    }
    if resolved_effort is not None:
        request_kwargs["reasoning_effort"] = resolved_effort
    if merged_extra:
        request_kwargs["extra_body"] = copy.deepcopy(merged_extra)

    gemma_thinking = bool(
        backend_name == _GEMMA_BACKEND
        and merged_extra.get("chat_template_kwargs", {}).get("enable_thinking"))
    # Qwen3.8 preserves thought history while thinking is enabled. Gemma's
    # pinned template enters its thinking/tool format whenever tools are
    # present and preserves thought only on tool-call turns, so every profiled
    # Gemma tool loop must retain a server-supplied reasoning field.
    preserve_tool_reasoning = bool(
        metadata_enabled
        and (qwen_thinking or backend_name == _GEMMA_BACKEND))
    effective_effort = resolved_effort
    if (metadata_enabled and backend_name == _QWEN_BACKEND
            and qwen_thinking and effective_effort is None):
        effective_effort = "xhigh"  # exact pinned template default

    return ResolvedGenerationPolicy(
        request_kwargs=request_kwargs,
        logged_params={
            "temperature": resolved_temperature,
            "top_p": resolved_top_p,
            "seed": resolved_seed,
        },
        profile_name=selected,
        reasoning_effort=effective_effort,
        sampling_extra=copy.deepcopy(merged_extra),
        gemma_thinking=gemma_thinking,
        preserve_tool_reasoning=preserve_tool_reasoning,
        metadata_enabled=metadata_enabled,
    )


def reasoning_text_from_message(message: Any) -> str | None:
    """Return server-supplied reasoning text without synthesizing a value."""

    empty_value = None
    for field_name in ("reasoning", "reasoning_content"):
        value = getattr(message, field_name, None)
        if isinstance(value, str):
            if value:
                return value
            empty_value = value
    model_extra = getattr(message, "model_extra", None)
    if isinstance(model_extra, Mapping):
        for field_name in ("reasoning", "reasoning_content"):
            value = model_extra.get(field_name)
            if isinstance(value, str):
                if value:
                    return value
                empty_value = value
    return empty_value


def build_policy_record_metadata(
    resolved: ResolvedGenerationPolicy,
    response: Any,
) -> dict[str, Any]:
    """Build optional schema fields from an effective policy and response.

    Profile-free legacy calls return an empty mapping.  Once instrumentation
    is active, unavailable response fields are explicit nulls.
    """

    if not resolved.metadata_enabled:
        return {}
    choice = response.choices[0]
    reasoning = reasoning_text_from_message(choice.message)
    finish_reason = getattr(choice, "finish_reason", None)
    if not isinstance(finish_reason, str):
        finish_reason = None
    metadata: dict[str, Any] = {
        "reasoning_effort": resolved.reasoning_effort,
        "sampling_extra": copy.deepcopy(dict(resolved.sampling_extra)),
        "finish_reason": finish_reason,
        "reasoning_chars": len(reasoning) if reasoning is not None else None,
    }
    if resolved.profile_name is not None:
        metadata["profile"] = resolved.profile_name
    return metadata


# Concise alias for direct paths such as Nara's tool loop.
resolve = resolve_generation_policy


__all__ = [
    "PROFILES",
    "UNSET",
    "ResolvedGenerationPolicy",
    "build_policy_record_metadata",
    "reasoning_text_from_message",
    "resolve",
    "resolve_generation_policy",
]
